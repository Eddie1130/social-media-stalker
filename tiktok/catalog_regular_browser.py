"""Persistent regular Chromium with guarded read-only catalog navigation."""

import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid
from urllib.parse import urlparse
from contextlib import suppress

from catalog_browser import BrowserTransport
from catalog_profile import ProfileLease

POST_LIST_HEADER = "x-local-catalog-post"


class RegularBrowserTransport(BrowserTransport):
    def __init__(self, name, cookies, anonymous=False, *, allow_post_list=True):
        self.chrome = self.display = self.remote = self.lifecycle = self.cache = None
        self.lease = None
        self.owned_singletons = {}
        self.anonymous = anonymous
        self.allow_post_list = allow_post_list
        self.post_list_token = None
        self.authenticated_context = self.anonymous_context = None
        super().__init__(name, cookies)

    def guard(self, route):
        request = route.request
        if urlparse(request.url).path != "/api/post/item_list/":
            return super().guard(route)
        if (
            not self.allow_post_list
            or request.method != "GET"
            or not self.post_list_token
            or request.headers.get(POST_LIST_HEADER) != self.post_list_token
        ):
            return route.abort()
        # The marker distinguishes our explicit fetch from the page's own preload.
        # Forward the request without the marker, and allow it only once.
        self.post_list_token = None
        headers = request.all_headers()
        headers.pop(POST_LIST_HEADER, None)
        return route.continue_(headers=headers)

    def post_response(self, url):
        self.post_list_token = uuid.uuid4().hex
        try:
            return super().post_response(url, headers={POST_LIST_HEADER: self.post_list_token})
        finally:
            self.post_list_token = None

    def open(self, name, cookies, manual=False):
        from playwright.sync_api import sync_playwright

        profile = Path(os.getenv("TIKTOK_CATALOG_PROFILE", "/data/catalog-profile"))
        profile.mkdir(parents=True, exist_ok=True)
        profile.chmod(0o700)
        self.lease = ProfileLease(profile)
        # Use Compose's hard cache mounts when present. Chromium's size switch
        # is a hint, not a bound on allocated cache files.
        cache_root = self.prepare_cache(profile)
        self.engine = sync_playwright().start()
        # No automation/headless switches. CDP is loopback-only and not published.
        self.display = subprocess.Popen(
            ["Xvfb", ":98", "-screen", "0", "1280x800x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        self.chrome = subprocess.Popen(
            [
                self.engine.chromium.executable_path,
                "--user-data-dir=" + str(profile),
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--password-store=basic",
                "--disable-extensions",
                "--disable-sync",
                "--disable-background-networking",
                "--autoplay-policy=user-gesture-required",
                "--mute-audio",
                "--disable-features=BackForwardCache",
                "--disk-cache-dir=" + cache_root,
                "--disk-cache-size=33554432",
                "--media-cache-size=8388608",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9222",
                "about:blank",
            ],
            env={**os.environ, "DISPLAY": ":98"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.getenv("TIKTOK_BROWSER_CHILD_PROCESS") != "1",
        )
        self.wait_for_cdp()
        self.owned_singletons = self.lease.chromium_links(self.chrome, socket.gethostname())
        self.remote = self.engine.chromium.connect_over_cdp(
            "http://127.0.0.1:9222", timeout=10000
        )
        # Keep the real persistent login context. Disable existing/future TikTok
        # Service Workers before navigation, then guard every automated request.
        self.authenticated_context = self.remote.contexts[0]
        self.context = self.authenticated_context
        self.context.route("**/*", self.guard)
        self.context.route_web_socket("**/*", lambda socket: None)
        if self.anonymous:
            # Park restored authenticated tabs before any anonymous navigation.
            self.prepare_reader_page()
            self.anonymous_context = self.remote.new_context(service_workers="block")
            self.context = self.anonymous_context
            self.context.route("**/*", self.guard)
            self.context.route_web_socket("**/*", lambda socket: None)
        if not self.anonymous:
            self.restore_cookies(profile, cookies)
        self.prepare_reader_page()
        self.lifecycle = self.context.new_cdp_session(self.page)
        self.guard_workers()
        self.navigate(name)

    def select_anonymous(self, anonymous):
        """Switch identities without restarting Chromium or copying authentication."""
        if self.anonymous == anonymous:
            return False
        self.park()
        if anonymous and self.anonymous_context is None:
            context = self.remote.new_context(service_workers="block")
            context.route("**/*", self.guard)
            context.route_web_socket("**/*", lambda socket: None)
            self.anonymous_context = context
        self.context = self.anonymous_context if anonymous else self.authenticated_context
        self.anonymous = anonymous
        # Existing popup guards must allow the replacement page during switching.
        self.page = None
        self.prepare_reader_page()
        self.lifecycle = self.context.new_cdp_session(self.page)
        self.guard_workers()
        return True

    def prepare_cache(self, profile):
        if all(os.path.ismount(profile / "Default" / name)
               for name in ("Cache", "Code Cache")):
            return str(profile)
        # Standalone/login smoke tools may not have the Compose cache mounts.
        self.cache = tempfile.TemporaryDirectory(prefix="tiktok-catalog-cache-")
        return self.cache.name

    def wait_for_cdp(self, timeout=60):
        """Allow disk-bound NAS startup without waiting indefinitely."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.chrome.poll() is not None:
                raise RuntimeError("TIKTOK_BROWSER_START_FAILED")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:9222/json/version", timeout=0.5
                ):
                    return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("TIKTOK_BROWSER_CONNECT_TIMEOUT")

    def guard_workers(self):
        cdp = self.lifecycle
        cdp.send("Network.enable")
        cdp.send("Network.setBypassServiceWorker", {"bypass": True})
        registrations = []
        cdp.on(
            "ServiceWorker.workerRegistrationUpdated",
            lambda event: registrations.extend(event.get("registrations", [])),
        )
        cdp.send("ServiceWorker.enable")
        cdp.send("ServiceWorker.stopAllWorkers")
        self.page.wait_for_timeout(100)
        for registration in registrations:
            scope = registration.get("scopeURL", "")
            host = urlparse(scope).hostname or ""
            if host == "tiktok.com" or host.endswith(".tiktok.com"):
                cdp.send("ServiceWorker.unregister", {"scopeURL": scope})
        if not hasattr(self, "_worker_guard_contexts"):
            self._worker_guard_contexts = set()
        if self.context not in self._worker_guard_contexts:
            self.context.add_init_script(
                "if (window.ServiceWorkerContainer) { ServiceWorkerContainer.prototype.register = () => Promise.reject(new DOMException('Disabled by read guard', 'NotAllowedError')); }"
            )
            self._worker_guard_contexts.add(self.context)

    def navigate(self, name):
        self.profile_url = f"https://www.tiktok.com/@{name}"
        self.navigation = self.page.goto(
            self.profile_url, wait_until="domcontentloaded", timeout=120000
        )
        self.page.wait_for_timeout(2000)

    def pause(self):
        if os.getenv("TIKTOK_CATALOG_FREEZE_IDLE", "1") == "1":
            self.lifecycle.send("Emulation.setScriptExecutionDisabled", {"value": True})

    def resume(self):
        if os.getenv("TIKTOK_CATALOG_FREEZE_IDLE", "1") == "1":
            self.lifecycle.send("Emulation.setScriptExecutionDisabled", {"value": False})

    def park(self):
        """Release the TikTok renderer between scheduler ticks, retaining login."""
        old_page = self.page
        # Allow exactly this replacement through the popup guard.
        self.page = None
        try:
            self.page = self.context.new_page()
        finally:
            old_page.close()
        self.lifecycle = self.context.new_cdp_session(self.page)
        self.lifecycle.send("Network.enable")
        self.lifecycle.send("Network.setBypassServiceWorker", {"bypass": True})
        self.profile_url = "about:blank"
        self.navigation = None

    def close(self):
        if self.context:
            with suppress(Exception):
                self.context.close()
        if self.remote:
            with suppress(Exception):
                self.remote.close()
        if self.engine:
            with suppress(Exception):
                self.engine.stop()
        if self.chrome and self.chrome.poll() is None:
            with suppress(ProcessLookupError):
                if os.getenv("TIKTOK_BROWSER_CHILD_PROCESS") == "1":
                    self.chrome.terminate()
                else:
                    os.killpg(self.chrome.pid, signal.SIGTERM)
            try:
                self.chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    if os.getenv("TIKTOK_BROWSER_CHILD_PROCESS") == "1":
                        self.chrome.kill()
                    else:
                        os.killpg(self.chrome.pid, signal.SIGKILL)
                self.chrome.wait()
        if self.display and self.display.poll() is None:
            self.display.terminate()
            try:
                self.display.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.display.kill()
                self.display.wait()
        try:
            if self.cache:
                self.cache.cleanup()
        finally:
            self.cache = None
            self.context = self.engine = self.lifecycle = None
            if self.lease:
                try:
                    if self.chrome:
                        self.lease.clear_chromium_links(self.chrome, self.owned_singletons)
                finally:
                    self.lease.close()
                    self.lease = None
