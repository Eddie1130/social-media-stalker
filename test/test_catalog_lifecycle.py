"""Fault injection for browser supervision, without network or credentials."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tiktok'))
from catalog_query import BrowserWorker


class LifecycleTests(unittest.TestCase):
    def test_close_reaps_descendant_even_when_worker_exits_first(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'alive'
            child = ('import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                     f'p=pathlib.Path({str(marker)!r}); '\
                     '\nwhile True:p.write_text(str(time.monotonic()));time.sleep(.02)')
            command = [sys.executable, '-u', '-c',
                       'import subprocess,sys,time; '
                       f'subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(30)']
            worker = BrowserWorker(command=command)
            worker._start()
            pgid = worker.proc.pid
            try:
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                closer = threading.Thread(target=worker.close, daemon=True)
                closer.start()
                closer.join(timeout=2)
                self.assertFalse(closer.is_alive(), "shutdown blocked on orphan stdout pipe")
                time.sleep(.1)
                before = marker.read_text()
                time.sleep(.15)
                self.assertEqual(marker.read_text(), before, 'browser descendant survived worker shutdown')
            finally:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if "closer" in locals():
                    closer.join(timeout=2)
                worker.close()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process-group teardown; verified in catalog image")
    def test_crashed_worker_restarts_on_next_query(self):
        worker = BrowserWorker(command=[sys.executable, '-c', 'raise SystemExit(2)'], timeout=2)
        try:
            with self.assertRaisesRegex(RuntimeError, 'TRANSPORT_FAILED'):
                worker('alice', 'post')
            worker.command = [sys.executable, '-u', '-c',
                'import sys,json\nfor l in sys.stdin:\n d=json.loads(l);print(json.dumps({**d,"result":{"ok":True}}),flush=True)']
            self.assertEqual(worker('alice', 'post'), {'ok': True})
        finally:
            worker.close()


class ProfileTests(unittest.TestCase):
    def test_profile_exclusion_preserves_singleton_and_session(self):
        from catalog_profile import ProfileLease
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            (profile / 'SingletonLock').symlink_to('foreign-host-999')
            (profile / 'Cookies').write_bytes(b'preserve-session')
            lease = ProfileLease(profile)
            try:
                with self.assertRaisesRegex(RuntimeError, 'PROFILE_IN_USE'):
                    ProfileLease(profile)
                command = [sys.executable, '-c',
                           'import sys;sys.path.insert(0,sys.argv[1]);from catalog_profile import ProfileLease;ProfileLease(sys.argv[2])',
                           str(Path(__file__).resolve().parents[1] / 'tiktok'), folder]
                result = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('TIKTOK_PROFILE_IN_USE', result.stderr)
            finally:
                lease.close()
            replacement = ProfileLease(profile)
            replacement.close()
            self.assertEqual(os.readlink(profile / 'SingletonLock'), 'foreign-host-999')
            self.assertEqual((profile / 'Cookies').read_bytes(), b'preserve-session')

    def test_driver_stop_failure_releases_profile_lease(self):
        from catalog_browser import BrowserTransport
        from catalog_profile import ProfileLease
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            browser = BrowserTransport.__new__(BrowserTransport)
            browser.context = Mock()
            browser.engine = Mock()
            browser.engine.stop.side_effect = RuntimeError('driver stopped')
            browser.lease = ProfileLease(folder)
            with self.assertRaisesRegex(RuntimeError, 'driver stopped'):
                browser.close()
            lease = ProfileLease(folder)
            lease.close()

    def test_cache_cleanup_failure_releases_profile_lease(self):
        from catalog_regular_browser import RegularBrowserTransport
        from catalog_profile import ProfileLease
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            browser = RegularBrowserTransport.__new__(RegularBrowserTransport)
            browser.context = browser.remote = browser.engine = None
            browser.chrome = browser.display = None
            browser.cache = Mock()
            browser.cache.cleanup.side_effect = OSError('cache unavailable')
            browser.lease = ProfileLease(folder)
            with self.assertRaisesRegex(OSError, 'cache unavailable'):
                browser.close()
            lease = ProfileLease(folder)
            lease.close()


class ProtocolDiagnosticTests(unittest.TestCase):
    def test_query_error_keeps_child_location_without_private_message(self):
        command = [sys.executable, '-u', '-c',
            'import sys,json\nfor l in sys.stdin:\n d=json.loads(l);print(json.dumps({**d,"error":"TIKTOK_PROVIDER_FAILED","diagnostic":{"exception":"ValueError","frames":[{"file":"catalog_provider.py","line":1,"function":"fetch_page"}]}}),flush=True)']
        worker = BrowserWorker(command=command, timeout=2)
        try:
            with self.assertRaisesRegex(RuntimeError, 'TIKTOK_PROVIDER_FAILED') as caught:
                worker('alice', 'post')
            self.assertEqual(caught.exception.browser_diagnostic['exception'], 'ValueError')
            self.assertEqual(caught.exception.browser_diagnostic['frames'][0]['function'], 'fetch_page')
        finally:
            worker.close()

    def test_owner_pump_failure_cancels_inflight_query_before_retry(self):
        import sqlite3
        error = sqlite3.OperationalError('private')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        worker = BrowserWorker(command=[sys.executable, '-u', '-c', 'import time;time.sleep(5)'],
                               pump=lambda: (_ for _ in ()).throw(error), timeout=2)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                worker('alice', 'post')
            self.assertIsNone(worker.proc)
            self.assertIsNone(worker.scratch)
            self.assertIsNone(worker.pending)
        finally:
            worker.close()


class CacheBudgetTests(unittest.TestCase):
    def test_mounted_cache_uses_hard_profile_budgets(self):
        from catalog_regular_browser import RegularBrowserTransport
        from unittest.mock import patch
        browser = RegularBrowserTransport.__new__(RegularBrowserTransport)
        browser.cache = None
        with patch('catalog_regular_browser.os.path.ismount', return_value=True), patch('catalog_regular_browser.tempfile.TemporaryDirectory') as temporary:
            self.assertEqual(browser.prepare_cache(Path('/profile')), '/profile')
        temporary.assert_not_called()
        self.assertIsNone(browser.cache)

    def test_standalone_fallback_stays_disposable(self):
        from catalog_regular_browser import RegularBrowserTransport
        from unittest.mock import patch
        browser = RegularBrowserTransport.__new__(RegularBrowserTransport)
        browser.cache = None
        with patch('catalog_regular_browser.os.path.ismount', return_value=False):
            root = Path(browser.prepare_cache(Path('/profile')))
        try:
            self.assertTrue(root.exists())
            self.assertNotEqual(root, Path('/profile'))
        finally:
            browser.cache.cleanup()
        self.assertFalse(root.exists())
