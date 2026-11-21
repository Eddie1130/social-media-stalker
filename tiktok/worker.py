"""Telegram-controlled TikTok recording using the imported recorder/API implementation."""
import hashlib
import errno
import json
import logging
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

STATE = Path(os.getenv('IG_STATE_DIR', '/app/state')) / 'tiktok'
ROOT = Path(os.getenv('IG_ARCHIVE_DIR', '/downloads'))
CONTROL = Path(os.getenv('IG_CONTROL_DIR', '/app/control'))
NAME = re.compile(r'^[a-z0-9_][a-z0-9_.]{0,23}$')
STOP = threading.Event()
PROCESSING = queue.Queue()
PROCESS_STOP = threading.Event()
STATUS = {}
STATUS_LOCK = threading.Lock()


def needs_attention(error):
    """Local storage, authentication and unsafe state cannot heal by retrying."""
    return (
        isinstance(error, OSError) and error.errno in {
            errno.ENOSPC, errno.EDQUOT, errno.EACCES, errno.EPERM, errno.EROFS,
            errno.EIO, errno.ENOENT, errno.ENOTDIR,
        }
        or bool(re.search(
            r'CAPTCHA_REQUIRED|LOGIN_REQUIRED|COOKIE_.*INVALID|SETTINGS_INVALID|'
            r'UNSAFE|HISTORY_.*(?:MISSING|INVALID)|IDENTITY_INVALID', str(error)
        ))
    )


def atomic(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + '.' + str(threading.get_ident()) + '.tmp')
    with tmp.open('w', encoding='utf-8') as out:
        os.chmod(tmp, 0o600)
        json.dump(value, out)
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(file)


def settings():
    value = json.loads((CONTROL / 'settings.json').read_text())
    if value.get('version') != 1 or not isinstance(value.get('allowedIds'), list):
        raise ValueError('TIKTOK_SETTINGS_INVALID')
    return value


def subscriptions(value):
    result = {}
    for uid in value['allowedIds']:
        for name, sub in value['users'].get(uid, {}).get('tiktokTargets', {}).items():
            if not NAME.fullmatch(name) or name.endswith('.'):
                raise ValueError('TIKTOK_SETTINGS_INVALID')
            result.setdefault(name, []).append({'userId': uid, 'generation': sub['generation']})
    return result


def status(name, phase):
    with STATUS_LOCK:
        STATUS[name] = {'phase': phase}


def emit(name, kind, text, recipients, files=None, at=None, identity=None, notice_key=None, notice_kind=None):
    event = {'username': name, 'kind': kind, 'text': text, 'recipients': recipients,
             'files': files or [], 'at': at or int(time.time() * 1000)}
    if notice_key:
        event.update(noticeKey=notice_key, noticeKind=notice_kind)
    key = hashlib.sha256((identity or json.dumps(event, sort_keys=True)).encode()).hexdigest()
    atomic(STATE / 'events' / (key + '.json'), event)


def cookies():
    value = json.loads(Path(os.getenv('TIKTOK_COOKIE_FILE', '/app/cookies.json')).read_text())
    if isinstance(value, list):
        value = {c['name']: c['value'] for c in value if isinstance(c, dict) and isinstance(c.get('name'), str) and isinstance(c.get('value'), str)}
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
        raise ValueError('TIKTOK_COOKIE_FORMAT_INVALID')
    return value


def run_tool(args):
    # Stream URLs and credentials must never appear in error output.
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)


def cleanup_recording_start(job):
    emit(job['username'], 'notice', '', job['recipients'],
         identity='recording-start-cleanup:' + str(job['dest']),
         notice_key=f"recording-start:{job['username']}:{job['at']}", notice_kind='recovery')


def finalize(job, limit=1_900_000_000):
    source = Path(job['source'])
    dest = Path(job['dest'])
    if not dest.exists():
        temporary = dest.with_suffix('.part.mp4')
        run_tool(['ffmpeg', '-nostdin', '-y', '-i', str(source), '-map', '0:v?', '-map', '0:a?', '-c', 'copy', '-movflags', '+faststart', str(temporary)])
        if temporary.stat().st_size < 4096:
            raise ValueError('TIKTOK_MP4_INCOMPLETE')
        temporary.replace(dest)
    if dest.stat().st_size <= limit:
        parts = [dest]
    else:
        duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(dest)], stderr=subprocess.DEVNULL, timeout=60))
        seconds = max(1, int(duration * limit / dest.stat().st_size * 0.8))
        folder = dest.parent / (dest.stem + '_parts')
        folder.mkdir(exist_ok=True)
        while True:
            for old in folder.glob('*.mp4'):
                old.unlink()
            run_tool(['ffmpeg', '-nostdin', '-y', '-i', str(dest), '-map', '0:v?', '-map', '0:a?', '-c', 'copy', '-f', 'segment', '-segment_time', str(seconds), '-reset_timestamps', '1', str(folder / '%04d.mp4')])
            parts = sorted(folder.glob('*.mp4'))
            if parts and all(4096 <= p.stat().st_size <= limit for p in parts):
                break
            if seconds <= 1:
                raise ValueError('TIKTOK_SPLIT_LIMIT_FAILED')
            seconds = max(1, seconds // 2)
    emit(job['username'], 'video', '', job['recipients'],
         [str(p.relative_to(ROOT)) for p in parts], job['at'], 'video:' + str(dest))
    cleanup_recording_start(job)
    # Preserve source until successful MP4 conversion and durable delivery enqueue.
    source.unlink(missing_ok=True)


def processing():
    while not PROCESS_STOP.is_set() or not PROCESSING.empty():
        try:
            file = PROCESSING.get(timeout=1)
        except queue.Empty:
            continue
        job = None
        try:
            job = json.loads(file.read_text())
            finalize(job)
            if job.get('alerted'):
                emit(job['username'], 'notice', '', job['recipients'],
                     identity='processing-recovery:' + file.name,
                     notice_key='processing:' + hashlib.sha256(file.name.encode()).hexdigest(), notice_kind='recovery')
            file.unlink()
        except Exception as error:
            if job:
                try:
                    job['failures'] = job.get('failures', 0) + 1
                    status(job['username'], '轉檔／分段失敗，已保留待重試' if job['failures'] >= 3 or needs_attention(error) else f"轉檔重試中（{job['failures']}/3）")
                    if not job.get('alerted') and (job['failures'] >= 3 or needs_attention(error)):
                        emit(job['username'], 'notice', 'TikTok 轉檔／分段失敗，原檔已保留；稍後重試。', job['recipients'], identity='processing-error:' + file.name, notice_key='processing:' + hashlib.sha256(file.name.encode()).hexdigest(), notice_kind='error')
                        job['alerted'] = True
                    atomic(file, job)
                except Exception:
                    status('processor', '無法寫入錯誤事件，請檢查磁碟')
            else:
                status('processor', '轉檔工作紀錄讀取失敗，請檢查本機紀錄')
            STOP.wait(30)
            if not STOP.is_set():
                PROCESSING.put(file)
        finally:
            PROCESSING.task_done()


def live_requests(config):
    pending = {}
    for file in (STATE / 'live-requests').glob('*.json'):
        try:
            job = json.loads(file.read_text())
        except FileNotFoundError:
            continue
        uid, rid = job.get('userId'), file.stem
        request = config.get('tiktokRequests', {}).get(rid)
        if (not re.fullmatch(r'[1-9]\d{0,19}-\d+-\d+', rid) or not rid.startswith(str(uid) + '-')
                or uid not in config['allowedIds'] or not request or request.get('userId') != uid
                or request.get('url') != job.get('url') or job.get('id') != rid):
            file.unlink(missing_ok=True)
            continue
        pending[rid] = job
    return pending


def manual_recipient(job):
    return {'userId': job['userId'], 'generation': job['id'],
            'requestId': job['id'], 'requestUrl': job['url']}


def finish_request(job, text=None):
    if text:
        emit(job.get('name') or 'manual', 'notice', text, [manual_recipient(job)],
             identity='live-request:' + job['id'])
    (STATE / 'live-requests' / (job['id'] + '.json')).unlink(missing_ok=True)


def merge_recipients(recipients, jobs):
    by_user = {r['userId']: r for r in recipients}
    for job in jobs:
        previous = by_user.get(job['userId'], {})
        ids = previous.get('requestIds', [previous['requestId']] if previous.get('requestId') else [])
        recipient = manual_recipient(job)
        if any(rid != job['id'] for rid in ids):
            recipient['requestIds'] = list(dict.fromkeys([*ids, job['id']]))
        by_user[job['userId']] = recipient
    return list(by_user.values())


def resolve_live_requests(config, cookie_map):
    from core.tiktok_api import TikTokAPI
    names = set()
    for job in live_requests(config).values():
        if time.time() * 1000 - job['at'] > 600000 and not (STATE / 'captures' / ((job.get('name') or '') + '.json')).is_file():
            finish_request(job, '直播連結已過期，請重新傳送。')
            continue
        if job.get('name') is None:
            try:
                room = job['room']
                if not re.fullmatch(r'\d{1,30}', room):
                    raise ValueError('TIKTOK_ROOM_INVALID')
                api = TikTokAPI(proxy=None, cookies=cookie_map)
                if not api.is_room_alive(room):
                    finish_request(job, '這場 TikTok 直播已結束或尚未開播。')
                    continue
                job['name'] = api.get_user_from_room_id(room).lower()
                if not NAME.fullmatch(job['name']) or job['name'].endswith('.'):
                    raise ValueError('TIKTOK_USERNAME_INVALID')
                atomic(STATE / 'live-requests' / (job['id'] + '.json'), job)
            except Exception:
                job['name'] = None
                finish_request(job, '暫時無法辨識這場直播，請稍後重新傳送連結。')
                continue
        if NAME.fullmatch(job['name']) and not job['name'].endswith('.'):
            names.add(job['name'])
        else:
            job['name'] = None
            finish_request(job, '直播帳號格式不正確。')
    return names


def record_account(name, cookie_map, wake=None):
    from core.tiktok_recorder import TikTokRecorder
    from utils.custom_exceptions import UserLiveError, LiveNotFound
    from utils.enums import TikTokError

    class Recorder(TikTokRecorder):
        def stopping(self):
            return STOP.is_set()

        def _build_output_path(self, user, protocol='flv', timestamp=None):
            folder = ROOT / 'tiktok' / name / 'live'
            folder.mkdir(parents=True, exist_ok=True)
            source = str(folder / (self.stem + ('_hls.ts' if protocol == 'hls' else '_flv.mp4')))
            atomic(STATE / 'captures' / (name + '.json'), {'source': source, 'dest': str(folder / (self.stem + '.mp4')), 'username': name, 'recipients': self.recipients, 'at': self.started, 'room': str(self.room_id)})
            return source

        def _download_stream(self, url, protocol):
            for chunk in super()._download_stream(url, protocol):
                if not self.announced and chunk:
                    emit(name, 'start', f'🔴 TikTok @{name} 已開播，開始錄影。', self.recipients, at=self.started)
                    self.announced = True
                    status(name, '錄影中')
                if chunk and getattr(self, '_integration_interrupted', False):
                    self._integration_interrupted = False
                    emit(name, 'notice', '', self.recipients,
                         notice_key=f'recording:{name}', notice_kind='recovery')
                elif chunk and not getattr(self, '_integration_recovered', False):
                    self._integration_recovered = True
                    emit(name, 'notice', '', self.recipients,
                         notice_key=f'recording:{name}', notice_kind='recovery')
                yield chunk

        def _tiktok_alert(self, kind, reason, stage=None):
            self._integration_interrupted = True
            now = time.monotonic()
            previous = getattr(self, '_last_integration_alert', 0)
            if previous and now - previous < 600:
                return
            self._last_integration_alert = now
            emit(name, 'notice', f'TikTok @{name} 錄影異常／中斷（{kind}）；本機已保留取得的資料。', self.recipients, notice_key=f'recording:{name}', notice_kind='error')

        def finalize(self, source):
            job = {'source': source, 'dest': str(Path(source).parent / (self.stem + '.mp4')), 'username': name, 'recipients': self.recipients, 'at': self.started}
            jobs = [j for j in live_requests(settings()).values() if j.get('name') == name
                    and (not j.get('room') or j['room'] == str(self.room_id))]
            job['recipients'] = merge_recipients(self.recipients, jobs)
            file = STATE / 'processing' / (self.stem + '_' + name + '.json')
            atomic(file, job)
            for request in jobs:
                finish_request(request)
            cleanup_recording_start(job)
            if STOP.is_set():
                emit(name, 'notice', f'TikTok @{name} 錄影因服務停止而中斷，已保留原檔及轉檔工作。', self.recipients, notice_key=f'recording:{name}', notice_kind='error')
            PROCESSING.put(file)
            (STATE / 'captures' / (name + '.json')).unlink(missing_ok=True)

    config = SimpleNamespace(proxy=None, cookies=cookie_map, url=None, user=name, room_id=None,
                             mode=None, automatic_interval=1, duration=None, output=str(ROOT), bitrate=None,
                             ffmpeg_path='ffmpeg', use_telegram=False)
    rec = Recorder(config)
    failures = 0
    alerted = False
    recipients = []
    while not STOP.is_set():
        urgent = False
        jobs = []
        try:
            config = settings()
            recipients = subscriptions(config).get(name, [])
            jobs = [j for j in live_requests(config).values() if j.get('name') == name]
            if not recipients and not jobs:
                break
            status(name, '檢查直播中')
            room = rec.tiktok.get_room_id_from_user(name)
            if not room:
                requested_rooms = {
                    job['room'] for job in jobs
                    if isinstance(job.get('room'), str) and re.fullmatch(r'\d{1,30}', job['room'])
                }
                if len(requested_rooms) == 1:
                    requested_room = requested_rooms.pop()
                    owner = rec.tiktok.get_user_from_room_id(requested_room)
                    if isinstance(owner, str) and owner.lower() == name:
                        room = requested_room
            if not room:
                raise ValueError('TIKTOK_ROOM_LOOKUP_FAILED')
            matching = []
            for job in jobs:
                if job.get('room') and job['room'] != str(room):
                    finish_request(job, '連結所指的直播已結束。')
                else:
                    matching.append(job)
            jobs = matching
            if not jobs and not recipients:
                break
            if rec.tiktok.is_room_alive(room):
                if not re.fullmatch(r'\d{1,30}', str(room)):
                    raise ValueError('TIKTOK_ROOM_INVALID')
                rec.room_id = room
                rec.recipients = merge_recipients(recipients, jobs)
                rec.started = int(time.time() * 1000)
                rec.stem = datetime.now(ZoneInfo('Asia/Tokyo')).strftime(f'TK_{name}_%Y.%m.%d_%H-%M-%S')
                rec.announced = False
                rec._integration_recovered = False
                rec._recording_bytes = rec._stream_retry_failures = 0
                rec._recording_phase = 'starting'
                rec.start_recording(name, room)
                for job in jobs:
                    if (STATE / 'live-requests' / (job['id'] + '.json')).exists():
                        finish_request(job, '未能取得可儲存的直播影片，請重新傳送連結。')
            else:
                for job in jobs:
                    finish_request(job, f'TikTok @{name} 目前未開播。')
            if alerted:
                emit(name, 'notice', f'TikTok @{name} 監控已恢復。', recipients, notice_key=f'live-monitor:{name}', notice_kind='recovery')
                alerted = False
            failures = 0
            status(name, '監看中')
        except (UserLiveError, LiveNotFound) as error:
            if str(TikTokError.USER_NOT_CURRENTLY_LIVE) in str(error):
                for job in jobs:
                    finish_request(job, f'TikTok @{name} 目前未開播。')
                if alerted:
                    emit(name, 'notice', f'TikTok @{name} 監控已恢復。', recipients, notice_key=f'live-monitor:{name}', notice_kind='recovery')
                    alerted = False
                failures = 0
                status(name, '未開播')
            else:
                failures += 1
                urgent = needs_attention(error)
        except Exception as error:
            failures += 1
            urgent = needs_attention(error)
        if failures:
            for job in jobs:
                finish_request(job, '暫時無法啟動直播錄影，請稍後重新傳送連結。')
            abnormal = alerted or failures >= 3 or urgent
            status(name, '檢查／錄影異常，重試中' if abnormal else f'等待重試（{failures}/3）')
            if abnormal and not alerted:
                emit(name, 'notice', f'TikTok @{name} 監控／錄影失敗，將持續重試。', recipients, notice_key=f'live-monitor:{name}', notice_kind='error')
                alerted = True
        if not recipients:
            break
        if wake is None:
            STOP.wait(60)
        else:
            wake.wait(60)
            wake.clear()
    status(name, '已停止監控')


def main():
    # Imported implementations may log request details; expose only sanitized health/events.
    logging.disable(logging.CRITICAL)
    cookie_map = cookies()
    STATE.mkdir(parents=True, exist_ok=True)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    for capture in (STATE / 'captures').glob('*.json'):
        job = json.loads(capture.read_text())
        source = Path(job['source'])
        if source.exists() and source.stat().st_size >= 4096:
            pending = [j for j in live_requests(settings()).values() if j.get('name') == job['username']
                       and (not j.get('room') or j['room'] == job.get('room'))]
            job['recipients'] = merge_recipients(job['recipients'], pending)
            file = STATE / 'processing' / capture.name
            atomic(file, job)
            for request in pending:
                finish_request(request)
            cleanup_recording_start(job)
            emit(job['username'], 'notice', 'TikTok 錄影曾因服務停止而中斷；正在處理保留的原檔。', job['recipients'], notice_key=f"recording:{job['username']}", notice_kind='error')
        capture.unlink()
    for file in (STATE / 'processing').glob('*.json'):
        PROCESSING.put(file)
    processor = threading.Thread(target=processing)
    processor.start()
    active, wakes = {}, {}
    try:
        while not STOP.is_set():
            if not processor.is_alive():
                raise RuntimeError('TIKTOK_PROCESSOR_STOPPED')
            config = settings()
            enabled = os.getenv('IG_TELEGRAM_CONTROL', '1') == '1'
            requested = resolve_live_requests(config, cookie_map) if enabled else set()
            targets = set(subscriptions(config)) | requested if enabled else set()
            for name in targets:
                if name not in active or not active[name].is_alive():
                    wakes[name] = threading.Event()
                    active[name] = threading.Thread(target=record_account, args=(name, cookie_map, wakes[name]), daemon=True)
                    active[name].start()
                elif name in requested:
                    wakes[name].set()
            with STATUS_LOCK:
                atomic(STATE / 'health.json', {'at': int(time.time() * 1000), 'targets': dict(STATUS), 'active': sum(t.is_alive() for t in active.values())})
            STOP.wait(5)
    finally:
        STOP.set()
        for wake in wakes.values():
            wake.set()
        deadline = time.monotonic() + 45
        for thread in active.values():
            thread.join(timeout=max(0, deadline - time.monotonic()))
        PROCESS_STOP.set()
        processor.join(timeout=30)
        atomic(STATE / 'health.json', {'at': int(time.time() * 1000), 'phase': 'stopped', 'targets': STATUS})


if __name__ == '__main__':
    main()
