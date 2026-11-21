"""Cross-container exclusion for catalog readers and interactive login.

Only clean up this reader's original links after its Chromium child exits.
Stale foreign-host locks still need an operator's owner check.
"""
import fcntl
import stat
from pathlib import Path


def fingerprint(path):
    try:
        info = path.lstat()
        target = str(path.readlink()) if stat.S_ISLNK(info.st_mode) else None
        return info.st_dev, info.st_ino, target
    except FileNotFoundError:
        return None


class ProfileLease:
    def __init__(self, profile):
        profile = Path(profile)
        self.profile = profile
        profile.mkdir(parents=True, exist_ok=True)
        self.file = (profile / '.catalog-owner.lock').open('a')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('TIKTOK_PROFILE_IN_USE') from None

    def chromium_links(self, process, hostname):
        if self.file.closed or process.poll() is not None:
            return {}
        # Remove the lock last so the profile stays marked in-use during cleanup.
        names = ('SingletonCookie', 'SingletonSocket', 'SingletonLock')
        links = {}
        for name in names:
            value = fingerprint(self.profile / name)
            if value and value[2] is not None:
                links[name] = value
        lock = links.get('SingletonLock')
        return links if lock and lock[2] == f'{hostname}-{process.pid}' else {}

    def clear_chromium_links(self, process, links):
        if self.file.closed or not links or process.poll() is None:
            return
        current = {name: fingerprint(self.profile / name) for name in links}
        if any(value is not None and value != links[name] for name, value in current.items()):
            return
        for name, value in current.items():
            if value is not None:
                (self.profile / name).unlink(missing_ok=True)

    def close(self):
        self.file.close()
