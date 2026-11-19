"""Cross-container exclusion for catalog readers and interactive login.

Never remove Chromium singleton files here: an unknown owner may be in another
PID namespace. Stale foreign-host locks need an operator's owner check.
"""
import fcntl
from pathlib import Path


class ProfileLease:
    def __init__(self, profile):
        profile = Path(profile)
        profile.mkdir(parents=True, exist_ok=True)
        self.file = (profile / '.catalog-owner.lock').open('a')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('TIKTOK_PROFILE_IN_USE') from None

    def close(self):
        self.file.close()
