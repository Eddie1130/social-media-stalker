import importlib.util
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('tiktok_worker', Path(__file__).resolve().parents[1] / 'tiktok/worker.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class TikTokWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(w, 'ROOT', self.root / 'downloads'), patch.object(w, 'STATE', self.root / 'state')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_subscription_union_and_revocation(self):
        s = {'allowedIds': ['100', '200'], 'users': {uid: {'tiktokTargets': {'alice': {'generation': uid}}} for uid in ['100', '200']}}
        self.assertEqual(len(w.subscriptions(s)['alice']), 2)
        s['allowedIds'] = ['200']
        self.assertEqual(w.subscriptions(s)['alice'][0]['userId'], '200')
        s['users']['200']['tiktokTargets'] = {}
        self.assertEqual(w.subscriptions(s), {})

    def test_cookie_dictionary_and_browser_array_without_exposing_values(self):
        file = self.root / 'cookies.json'
        for raw in ({'example': 'private'}, [{'name': 'example', 'value': 'private'}]):
            file.write_text(json.dumps(raw))
            with patch.dict(w.os.environ, {'TIKTOK_COOKIE_FILE': str(file)}):
                self.assertEqual(set(w.cookies()), {'example'})
        file.write_text('42')
        with patch.dict(w.os.environ, {'TIKTOK_COOKIE_FILE': str(file)}):
            with self.assertRaises(ValueError):
                w.cookies()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg unavailable')
    def test_real_mp4_remux_and_durable_video_event(self):
        folder = w.ROOT / 'tiktok/alice/live'
        folder.mkdir(parents=True)
        source = folder / '20261114_120000_JST_123_hls.ts'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=128x128:rate=10', '-t', '2', '-c:v', 'mpeg2video', '-f', 'mpegts', str(source)], check=True)
        dest = folder / '20261114_120000_JST_123.mp4'
        job = {'source': str(source), 'dest': str(dest), 'username': 'alice', 'recipients': [{'userId': '100', 'generation': 'test'}], 'at': 1000}
        w.finalize(job)
        self.assertGreater(dest.stat().st_size, 4096)
        self.assertFalse(source.exists())
        event = next(e for e in (json.loads(p.read_text()) for p in (w.STATE / 'events').glob('*.json')) if e['kind'] == 'video')
        self.assertEqual(event['kind'], 'video')
        self.assertEqual(event['files'], [str(dest.relative_to(w.ROOT))])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg unavailable')
    def test_real_split_preserves_full_mp4_and_caps_every_part(self):
        folder = w.ROOT / 'tiktok/alice/live'
        folder.mkdir(parents=True)
        source = folder / 'recording.ts'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=128x128:rate=10', '-t', '10', '-c:v', 'mpeg2video', '-g', '5', '-f', 'mpegts', str(source)], check=True)
        dest = folder / 'recording.mp4'
        job = {'source': str(source), 'dest': str(dest), 'username': 'alice', 'recipients': [], 'at': 1000}
        w.finalize(job, limit=60000)
        self.assertGreater(dest.stat().st_size, 60000)
        event = next(e for e in (json.loads(p.read_text()) for p in (w.STATE / 'events').glob('*.json')) if e['kind'] == 'video')
        self.assertGreater(len(event['files']), 1)
        self.assertTrue(all((w.ROOT / f).stat().st_size <= 60000 for f in event['files']))

    def test_start_cleanup_is_durable_and_scoped_to_recording(self):
        job = {'username': 'alice', 'recipients': [], 'at': 1000,
               'dest': str(self.root / 'recording.mp4')}
        w.cleanup_recording_start(job)
        w.cleanup_recording_start(job)
        events = list((w.STATE / 'events').glob('*.json'))
        self.assertEqual(len(events), 1)
        event = json.loads(events[0].read_text())
        self.assertEqual(event['noticeKey'], 'recording-start:alice:1000')
        self.assertEqual(event['noticeKind'], 'recovery')

    def test_failed_conversion_keeps_original(self):
        source = self.root / 'broken.ts'
        source.write_bytes(b'preserve me')
        job = {'source': str(source), 'dest': str(self.root / 'out.mp4')}
        with patch.object(w, 'run_tool', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                w.finalize(job)
        self.assertTrue(source.exists())

    def test_processing_waits_three_attempts_and_persists_failure_count(self):
        file = w.STATE / 'processing/test.json'
        w.atomic(file, {'username': 'alice', 'recipients': []})
        jobs = queue.Queue()
        jobs.put(file)
        stop = Mock()
        stop.is_set.return_value = False

        def fail(_job):
            if _job.get('failures', 0) >= 3:
                stop.is_set.return_value = True
                return
            raise TimeoutError()

        with patch.object(w, 'PROCESSING', jobs), patch.object(w, 'PROCESS_STOP', stop), \
                patch.object(w, 'STOP', Mock(is_set=Mock(return_value=False))), \
                patch.object(w, 'finalize', side_effect=fail), patch.object(w, 'emit') as emit:
            w.processing()
        self.assertEqual(emit.call_count, 2)
        self.assertEqual(emit.call_args_list[0].kwargs['notice_kind'], 'error')
        self.assertEqual(emit.call_args_list[1].kwargs['notice_kind'], 'recovery')
        self.assertEqual(emit.call_args_list[0].kwargs['notice_key'], emit.call_args_list[1].kwargs['notice_key'])
        self.assertFalse(file.exists())

    def test_link_records_without_subscription_and_routes_to_requester(self):
        self.assert_live_link_records('123')

    def test_link_uses_verified_room_when_username_has_no_room(self):
        self.assert_live_link_records(None, room_owner='Alice')

    def test_link_does_not_record_a_room_owned_by_another_account(self):
        self.assert_live_link_records(None, room_owner='bob', expect_recording=False)

    def assert_live_link_records(self, username_room, room_owner=None, expect_recording=True):
        job = {'id': '100-1-0', 'userId': '100', 'name': 'alice', 'room': '123',
               'url': 'https://vt.tiktok.com/test/', 'at': 1}
        config = {'allowedIds': ['100'], 'users': {'100': {}}, 'tiktokRequests': {job['id']: job}}
        pending = w.STATE / 'live-requests' / (job['id'] + '.json')
        w.atomic(pending, job)
        api = Mock()
        api.get_room_id_from_user.return_value = username_room
        api.get_user_from_room_id.return_value = room_owner
        api.is_room_alive.return_value = True
        class Base:
            def __init__(self, config):
                self.tiktok = api
            def start_recording(self, name, room):
                source = self._build_output_path(name)
                Path(source).write_bytes(b'x' * 4096)
                self.finalize(source)
        modules = {'core.tiktok_recorder': SimpleNamespace(TikTokRecorder=Base),
                   'utils.custom_exceptions': SimpleNamespace(UserLiveError=ValueError, LiveNotFound=LookupError),
                   'utils.enums': SimpleNamespace(TikTokError=SimpleNamespace(USER_NOT_CURRENTLY_LIVE='offline'))}
        with patch.dict(sys.modules, modules), patch.object(w, 'settings', return_value=config), patch.object(w, 'PROCESSING', queue.Queue()):
            w.record_account('alice', {})
        self.assertFalse(pending.exists())
        if username_room is None:
            api.get_user_from_room_id.assert_called_once_with('123')
        if not expect_recording:
            api.is_room_alive.assert_not_called()
            self.assertFalse(list((w.STATE / 'processing').glob('*.json')))
            return
        api.is_room_alive.assert_called_once_with('123')
        result = json.loads(next((w.STATE / 'processing').glob('*.json')).read_text())
        self.assertEqual(result['recipients'], [w.manual_recipient(job)])
        self.assertEqual(w.subscriptions(config), {})

    def run_live_monitor(self, outcomes):
        recipients = {'allowedIds': ['100'], 'users': {'100': {
            'tiktokTargets': {'alice': {'generation': 'test'}}}}}
        api = Mock()
        api.get_room_id_from_user.return_value = '123'
        api.is_room_alive.side_effect = outcomes

        class BaseRecorder:
            def __init__(self, _config):
                self.tiktok = api

        class UserLiveError(Exception):
            pass

        class LiveNotFound(Exception):
            pass

        modules = {
            'core.tiktok_recorder': SimpleNamespace(TikTokRecorder=BaseRecorder),
            'utils.custom_exceptions': SimpleNamespace(UserLiveError=UserLiveError, LiveNotFound=LiveNotFound),
            'utils.enums': SimpleNamespace(TikTokError=SimpleNamespace(USER_NOT_CURRENTLY_LIVE='offline')),
        }
        stop = Mock()
        ticks = []
        stop.is_set.side_effect = lambda: len(ticks) >= len(outcomes)
        stop.wait.side_effect = lambda _seconds: ticks.append(1)
        with patch.dict(sys.modules, modules), patch.object(w, 'STOP', stop), \
                patch.object(w, 'settings', return_value=recipients), patch.object(w, 'emit') as emit:
            w.record_account('alice', {})
        return emit

    def test_live_monitor_waits_three_failures_then_recovers_once(self):
        emit = self.run_live_monitor([TimeoutError(), TimeoutError(), TimeoutError(), False])
        self.assertEqual(emit.call_count, 2)
        self.assertIn('失敗', emit.call_args_list[0].args[2])
        self.assertIn('恢復', emit.call_args_list[1].args[2])

    def test_live_monitor_two_failures_recover_silently(self):
        emit = self.run_live_monitor([TimeoutError(), TimeoutError(), False, TimeoutError()])
        self.assertEqual(emit.call_count, 0)

    def test_live_monitor_captcha_is_immediate(self):
        emit = self.run_live_monitor([RuntimeError('TIKTOK_CAPTCHA_REQUIRED')])
        self.assertEqual(emit.call_count, 1)


if __name__ == '__main__':
    unittest.main()
