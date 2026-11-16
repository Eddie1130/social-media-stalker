"""Produce bounded upload copies without changing the archived original."""

import subprocess
import os,signal,threading,time


_split_slot=threading.Semaphore(1)
def delivery_parts(file,limit=1_900_000_000,stop=None):
    if file.suffix != ".mp4" or file.stat().st_size<=limit:return [file]
    while not _split_slot.acquire(timeout=.1):
        if stop and stop.is_set():raise RuntimeError("TIKTOK_SPLIT_INTERRUPTED")
    try:
        if stop and stop.is_set():raise RuntimeError("TIKTOK_SPLIT_INTERRUPTED")
        return _delivery_parts(file,limit,stop)
    finally:_split_slot.release()

def _delivery_parts(file, limit, stop=None):
    if file.suffix != ".mp4" or file.stat().st_size <= limit:
        return [file]
    duration = float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(file),
            ],
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    )
    seconds = max(1, int(duration * limit / file.stat().st_size * 0.8))
    folder = file.parent / (file.stem + "_parts")
    folder.mkdir(exist_ok=True)
    while True:
        for part in folder.glob("*.mp4"):
            part.unlink()
        proc=subprocess.Popen(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-i",
                str(file),
                "-map",
                "0:v?",
                "-map",
                "0:a?",
                "-c",
                "copy",
                "-f",
                "segment",
                "-segment_time",
                str(seconds),
                "-reset_timestamps",
                "1",
                str(folder / "%04d.mp4"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline=time.monotonic()+1800
        try:
            while proc.poll() is None:
                if (stop and stop.is_set()) or time.monotonic()>deadline:
                    raise RuntimeError("TIKTOK_SPLIT_INTERRUPTED")
                time.sleep(.1)
            if proc.returncode:raise subprocess.CalledProcessError(proc.returncode,proc.args)
        finally:
            if proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    proc.wait()
        parts = sorted(folder.glob("*.mp4"))
        if parts and all(12 <= p.stat().st_size <= limit for p in parts):
            return parts
        if seconds <= 1:
            raise RuntimeError("TIKTOK_SPLIT_FAILED")
        seconds = max(1, seconds // 2)
