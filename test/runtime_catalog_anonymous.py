"""Run in an isolated container: real Chromium identity switching, no TikTok requests."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from catalog_regular_browser import RegularBrowserTransport

with tempfile.TemporaryDirectory(prefix="anonymous-runtime-") as folder:
    with patch.dict(os.environ, {"TIKTOK_CATALOG_PROFILE": folder}), patch.object(
        RegularBrowserTransport, "navigate", lambda self, name: self.page.goto("about:blank")
    ):
        browser = RegularBrowserTransport("offline", {}, anonymous=True)
        try:
            assert browser.context.cookies() == []
            anonymous = browser.context
            for _ in range(4):
                browser.resume()
                assert browser.select_anonymous(False)
                browser.restore_cookies(Path(folder), {"sessionid": "offline-test-only"})
                assert any(c["name"] == "sessionid" for c in browser.context.cookies())
                browser.page.goto("about:blank")
                browser.pause()
                browser.resume()
                assert browser.select_anonymous(True)
                assert browser.context is anonymous
                assert not any(c["name"] == "sessionid" for c in browser.context.cookies())
                assert not browser.page.is_closed()
                browser.page.goto("about:blank")
                browser.pause()
            assert len(browser._worker_guard_contexts) == 2
            assert len(browser._reader_contexts) == 2
            for context in (browser.authenticated_context, browser.anonymous_context):
                assert len(context._impl_obj.listeners("page")) == 1
            print("PASS: 4 identity cycles; authentication isolated; one popup guard per context")
        finally:
            browser.close()
