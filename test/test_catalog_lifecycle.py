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
    def test_shutdown_signals_worker_before_its_process_group(self):
        from unittest.mock import Mock, call, patch

        worker = BrowserWorker()
        proc = Mock(pid=123)
        worker.proc = proc
        operations = Mock()
        operations.attach_mock(proc, 'proc')
        with patch('catalog_query.os.killpg') as kill_group:
            operations.attach_mock(kill_group, 'kill_group')
            worker.close()
        self.assertEqual(operations.mock_calls[:4], [
            call.proc.terminate(),
            call.proc.wait(timeout=20),
            call.kill_group(123, signal.SIGKILL),
            call.proc.wait(timeout=5),
        ])

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
    def test_cleanup_requires_original_owned_singleton_links(self):
        from catalog_profile import ProfileLease
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            lock = profile / 'SingletonLock'
            cookie = profile / 'SingletonCookie'
            socket = profile / 'SingletonSocket'
            lock.symlink_to('owned-host-123')
            cookie.symlink_to('original-cookie')
            socket.symlink_to('/tmp/original-socket')
            process = Mock(pid=123)
            process.poll.return_value = None
            lease = ProfileLease(profile)
            try:
                self.assertEqual(lease.chromium_links(process, 'foreign-host'), {})
                owned = lease.chromium_links(process, 'owned-host')
                self.assertEqual(len(owned), 3)
                lease.clear_chromium_links(process, owned)
                self.assertTrue(lock.is_symlink())

                socket.unlink()
                socket.symlink_to('/tmp/replacement-socket')
                process.poll.return_value = 0
                lease.clear_chromium_links(process, owned)
                self.assertTrue(lock.is_symlink())
                self.assertTrue(cookie.is_symlink())
                self.assertEqual(os.readlink(socket), '/tmp/replacement-socket')

                socket.unlink()
                lease.clear_chromium_links(process, owned)
                self.assertFalse(lock.is_symlink())
                self.assertFalse(cookie.is_symlink())
            finally:
                lease.close()

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
