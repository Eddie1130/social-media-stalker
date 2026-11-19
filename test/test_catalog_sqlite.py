"""Real SQLite transactions and commit-failure recovery."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tiktok'))
import test_tiktok_catalog as fixtures


class CommitOnce:
    def __init__(self, db, code):
        self.db, self.code, self.failed = db, code, False

    def __getattr__(self, key):
        return getattr(self.db, key)

    def commit(self):
        if not self.failed:
            self.failed = True
            error = sqlite3.OperationalError('private diagnostic payload') if self.code is not None else RuntimeError('TIKTOK_CHECKPOINT_FAILED')
            if self.code is not None:error.sqlite_errorcode = self.code
            raise error
        return self.db.commit()


class SQLiteRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CatalogTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_failed_commit_cannot_advance_cursor_without_its_page(self):
        f = self.f
        f.fetch.return_value = f.page(more=True, cursor='20')
        f.catalog.db = CommitOnce(f.catalog.db, sqlite3.SQLITE_BUSY)
        try:
            f.catalog.poll('alice', 'post', f.settings)
        except sqlite3.OperationalError:
            pass
        self.assertEqual(f.catalog.stream('alice', 'post')['cursor'], '0')
        self.assertFalse(f.catalog.stream('alice', 'post')['baseline'])
        self.assertEqual(f.records(), [])

    def test_other_commit_failure_preserves_baseline_and_cursor(self):
        f = self.f
        f.fetch.return_value = f.page(more=True, cursor='20')
        f.catalog.db = CommitOnce(f.catalog.db, None)
        f.catalog.poll('alice', 'post', f.settings)
        state = f.catalog.stream('alice', 'post')
        self.assertEqual(state['cursor'], '0')
        self.assertFalse(state['baseline'])
        self.assertNotIn('lastSuccess', state)
        self.assertEqual(f.records(), [])

    def test_real_reader_lock_retries_without_losing_existing_pending_items(self):
        import threading
        from catalog_worker import run_catalog_loop
        f = self.f
        f.fetch.return_value = f.page(more=True, cursor='10')
        f.catalog.poll('alice', 'post', f.settings)
        before = f.catalog.stream('alice', 'post')
        f.time += 30001
        f.fetch.return_value = f.page(rows=[f.row('2')], more=True, cursor='20')
        f.catalog.db.execute('PRAGMA busy_timeout=0')
        reader = sqlite3.connect(f.catalog.folder / 'catalog.sqlite')
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM streams').fetchall()
        stop = threading.Event()
        waits = []
        session = Mock()
        original_poll = f.catalog.poll

        def tick():
            original_poll('alice', 'post', f.settings)
            stop.set()

        def wait(delay):
            if f.catalog.storage_blocked:
                waits.append(delay)
                # A reader still sees the last committed cursor, not page 20.
                row = reader.execute("SELECT data FROM streams WHERE name='alice' AND kind='post'").fetchone()
                self.assertEqual(json.loads(row[0]), before)
                self.assertEqual(len(f.records()), 1)
                reader.rollback()
            return stop.is_set()

        f.catalog.tick = tick
        stop.wait = wait
        run_catalog_loop(f.catalog, session, stop)
        self.assertEqual(waits, [1])
        self.assertFalse(f.catalog.storage_blocked)
        self.assertEqual({r['item']['id'] for r in f.records()}, {'1', '2'})
        self.assertTrue(all(r['status'] == 'pending' for r in f.records()))
        state = f.catalog.stream('alice', 'post')
        self.assertEqual(state['cursor'], '20')
        self.assertEqual(state['failures'], 0)
        self.assertEqual(f.notices(), [])
        session.idle.assert_called_once()

    def test_busy_backoff_is_bounded_and_cancellable(self):
        import threading
        from catalog_worker import run_catalog_loop
        stop = threading.Event()
        catalog, session = Mock(), Mock()
        error = sqlite3.OperationalError('private payload')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        catalog.tick.side_effect = error
        waits = []

        def wait(delay):
            waits.append(delay)
            if len(waits) == 8:
                stop.set()
            return stop.is_set()

        stop.wait = wait
        run_catalog_loop(catalog, session, stop)
        self.assertEqual(waits, [1, 2, 4, 8, 16, 30, 30, 30])
        self.assertEqual(catalog.db.rollback.call_count, 8)
        session.idle.assert_not_called()

    def test_corruption_is_not_hidden_as_transient_contention(self):
        import threading
        from catalog_worker import run_catalog_loop
        catalog = Mock()
        error = sqlite3.OperationalError('corrupt')
        error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
        catalog.tick.side_effect = error
        with self.assertRaises(sqlite3.OperationalError):
            run_catalog_loop(catalog, Mock(), threading.Event())

    def test_heartbeat_reports_storage_blockage(self):
        f = self.f
        f.catalog.storage_blocked = True
        f.catalog.heartbeat()
        health = json.loads((f.catalog.folder / 'health.json').read_text())
        self.assertTrue(health['storageBlocked'])

    def test_manual_request_does_not_spend_attempts_on_database_failure(self):
        from unittest.mock import patch
        f = self.f
        f.settings['tiktokRequests'] = {'100-1-0': {'userId': '100', 'url': 'https://www.tiktok.com/@alice/video/1', 'at': f.time}}
        error = sqlite3.OperationalError('private')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        f.fetch.side_effect = error
        with patch.dict(sys.modules, {'requests': Mock()}):
            for _ in range(3):
                with self.assertRaises(sqlite3.OperationalError):
                    f.catalog.manual_requests(f.settings)
                f.catalog.db.rollback()
        self.assertEqual(f.catalog.db.execute('SELECT attempts,done FROM manual_jobs').fetchall(), [])
        self.assertEqual(f.catalog.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_nonbusy_database_error_from_poll_is_fatal_without_cursor_advance(self):
        f = self.f
        f.fetch.return_value = f.page(more=True, cursor='20')
        f.catalog.db = CommitOnce(f.catalog.db, sqlite3.SQLITE_IOERR)
        with self.assertRaises(sqlite3.OperationalError):
            f.catalog.poll('alice', 'post', f.settings)
        self.assertEqual(f.catalog.stream('alice', 'post')['cursor'], '0')
        self.assertEqual(f.records(), [])

    def test_repair_preserves_its_retry_budget_on_database_failure(self):
        f = self.f
        item = f.row()
        item.update(assets=[], unresolvedReason='TIKTOK_MEDIA_MISSING')
        f.fetch.return_value = f.page(rows=[item])
        f.catalog.poll('alice', 'post', f.settings)
        before = f.records()[0]
        error = sqlite3.OperationalError('private')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        f.fetch.side_effect = error
        with self.assertRaises(sqlite3.OperationalError):
            f.catalog.repair(f.settings)
        self.assertEqual(f.records()[0], before)

    def test_refresh_preserves_retry_budget_on_database_failure(self):
        from catalog_scheduler import ArchiveCoordinator
        import threading
        f = self.f
        f.fetch.return_value = f.page()
        f.catalog.poll('alice', 'post', f.settings)
        r = f.records()[0]
        key = (r['target'], 'post', r['item']['id'])
        coordinator = ArchiveCoordinator(f.catalog, threading.Event())
        coordinator.refresh = [(*key, r)]
        coordinator.refreshing.add(key)
        error = sqlite3.OperationalError('private')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        f.fetch.side_effect = error
        try:
            with self.assertRaises(sqlite3.OperationalError):
                coordinator.refresh_one(f.settings)
            self.assertEqual(r['retryAt'], 0)
            self.assertNotIn(key, coordinator.refreshing)
        finally:
            coordinator.close(f.settings)

    def test_logging_pipe_failure_does_not_abort_database_retry(self):
        import threading
        from unittest.mock import patch
        from catalog_worker import run_catalog_loop
        stop = threading.Event()
        catalog, session = Mock(), Mock()
        error = sqlite3.OperationalError('private')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        catalog.tick.side_effect = error
        stop.wait = lambda _: stop.set()
        with patch('builtins.print', side_effect=BrokenPipeError):
            run_catalog_loop(catalog, session, stop)
        self.assertTrue(catalog.storage_blocked)
        catalog.db.rollback.assert_called_once()

    def test_manual_guard_is_held_until_running_download_stops_after_pump_failure(self):
        import threading
        from catalog_scheduler import ArchiveCoordinator
        f = self.f
        f.fetch.return_value = f.page()
        f.catalog.poll('alice', 'post', f.settings)
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def archive(*_):
            entered.set()
            release.wait(3)
            finished.set()
            return []
        f.catalog.archive = archive
        coordinator = ArchiveCoordinator(f.catalog, threading.Event())
        error = sqlite3.OperationalError('private')
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        def fail_pump(*_):
            self.assertTrue(entered.wait(1))
            raise error
        coordinator.pump = fail_pump
        timer = threading.Timer(.2, release.set)
        timer.start()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                coordinator.archive_manual(f.records()[0], f.settings)
            self.assertTrue(finished.is_set(), 'no second manual attempt may overlap its previous writer')
            self.assertEqual(coordinator.manual_count, 0)
            self.assertFalse(coordinator.busy)
        finally:
            release.set()
            timer.join()
            coordinator.pool.shutdown(wait=True)

    def test_default_sqlite_timeout_recovers_after_a_long_reader_releases(self):
        import threading
        from catalog_worker import run_catalog_loop
        f = self.f
        f.fetch.return_value = f.page(more=True, cursor='10')
        f.catalog.poll('alice', 'post', f.settings)
        f.time += 30001
        f.fetch.return_value = f.page(rows=[f.row('2')], more=True, cursor='20')
        reader = sqlite3.connect(f.catalog.folder / 'catalog.sqlite', check_same_thread=False)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM streams').fetchall()
        timer = threading.Timer(7, reader.rollback)
        real_db = f.catalog.db
        class TimedCommit:
            started = False
            def __getattr__(self, key):return getattr(real_db, key)
            def commit(self):
                if not self.started:
                    self.started = True
                    timer.start()
                return real_db.commit()
        db = TimedCommit()
        f.catalog.db = db
        stop, session = threading.Event(), Mock()
        original_wait = stop.wait
        busy_seen = []
        def tick():
            f.catalog.poll('alice', 'post', f.settings)
            stop.set()
        def wait(delay):
            if getattr(f.catalog, 'storage_blocked', False):busy_seen.append(delay)
            return original_wait(delay)
        f.catalog.tick, stop.wait = tick, wait
        try:
            run_catalog_loop(f.catalog, session, stop)
            self.assertTrue(busy_seen, 'the real default five-second SQLite commit timeout must be exercised')
            self.assertEqual({r['item']['id'] for r in f.records()}, {'1', '2'})
            self.assertEqual(f.catalog.stream('alice', 'post')['cursor'], '20')
            self.assertFalse(f.catalog.storage_blocked)
        finally:
            timer.cancel()
            if db.started:timer.join()
            reader.rollback()

    def test_controlled_stop_does_not_spend_manual_attempts(self):
        from catalog_worker import STOP
        from unittest.mock import patch
        self.addCleanup(STOP.clear)
        f = self.f
        f.settings['tiktokRequests'] = {'100-1-0': {'userId':'100','url':'https://www.tiktok.com/@alice/video/1','at':f.time}}
        def interrupted(*_args, **_kwargs):
            STOP.set()
            raise RuntimeError('TIKTOK_STOPPING')
        f.fetch.side_effect = interrupted
        with patch.dict(sys.modules, {'requests':Mock()}):
            for _ in range(3):
                STOP.clear()
                f.catalog.manual_requests(f.settings)
        self.assertEqual(f.catalog.db.execute('SELECT attempts,done FROM manual_jobs').fetchall(), [])
        self.assertEqual(f.catalog.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_cancelled_queued_media_keeps_pending_and_closes_cleanly(self):
        import threading
        from concurrent.futures import Future
        from catalog_scheduler import ArchiveCoordinator
        f = self.f
        f.fetch.return_value = f.page()
        f.catalog.poll('alice', 'post', f.settings)
        before = f.records()[0]
        future = Future();future.cancel()
        stop = threading.Event();stop.set()
        coordinator = ArchiveCoordinator(f.catalog, stop)
        coordinator.active[future] = ((before['target'],'post',before['item']['id'],before),before['item']['id'])
        coordinator.busy.add(before['item']['id'])
        try:
            coordinator.pump(f.settings)
            self.assertFalse(coordinator.active)
            self.assertFalse(coordinator.busy)
            self.assertEqual(f.records()[0], before)
        finally:
            coordinator.pool.shutdown(wait=True)

    def test_controlled_stop_preserves_repair_retry_budget(self):
        from catalog_worker import STOP
        self.addCleanup(STOP.clear)
        f = self.f
        item = f.row();item.update(assets=[],unresolvedReason='TIKTOK_MEDIA_MISSING')
        f.fetch.return_value = f.page(rows=[item])
        f.catalog.poll('alice','post',f.settings)
        before = f.records()[0]
        def interrupted(*_args,**_kwargs):
            STOP.set();raise RuntimeError('TIKTOK_STOPPING')
        f.fetch.side_effect = interrupted
        f.catalog.repair(f.settings)
        self.assertEqual(f.records()[0],before)

    def test_controlled_stop_preserves_interrupted_media_retry_budget(self):
        from catalog_worker import STOP
        from concurrent.futures import Future
        self.addCleanup(STOP.clear)
        f = self.f
        f.fetch.return_value = f.page()
        f.catalog.poll('alice','post',f.settings)
        before = f.records()[0]
        future = Future();future.set_exception(RuntimeError('TIKTOK_DOWNLOAD_INTERRUPTED'))
        STOP.set()
        f.catalog.finish_archive((before['target'],'post',before['item']['id'],before),future,f.settings)
        self.assertEqual(f.records()[0],before)

    def test_controlled_stop_preserves_refresh_retry_budget(self):
        from catalog_scheduler import ArchiveCoordinator
        import threading
        f = self.f
        f.fetch.return_value = f.page()
        f.catalog.poll('alice','post',f.settings)
        before = f.records()[0]
        stop = threading.Event()
        coordinator = ArchiveCoordinator(f.catalog,stop)
        key=(before['target'],'post',before['item']['id'])
        coordinator.refresh=[(*key,before)];coordinator.refreshing.add(key)
        def interrupted(*_args,**_kwargs):
            stop.set();raise RuntimeError('TIKTOK_STOPPING')
        f.fetch.side_effect=interrupted
        try:
            coordinator.refresh_one(f.settings)
            self.assertEqual(f.records()[0]['retryAt'],0)
            self.assertEqual(before['retryAt'],0)
        finally:coordinator.close(f.settings)
