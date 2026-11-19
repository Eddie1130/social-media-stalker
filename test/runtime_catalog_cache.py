"""Offline cache-budget smoke test. Requires /profile cache tmpfs mounts."""
import http.server
import os
import threading
import time
from unittest.mock import patch
from catalog_regular_browser import RegularBrowserTransport


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        blob = self.path.startswith('/blob')
        body = b'x' * (1024 * 1024) if blob else b'<html><body>offline cache test</body></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream' if blob else 'text/html')
        self.send_header('Cache-Control', 'public, max-age=3600')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f'http://127.0.0.1:{server.server_port}'


def navigate(browser, _name):
    browser.profile_url = base
    browser.navigation = browser.page.goto(base, wait_until='domcontentloaded', timeout=10000)


def usage(folder):
    stat = os.statvfs(folder)
    return (stat.f_blocks - stat.f_bfree) * stat.f_frsize


os.environ['TIKTOK_CATALOG_PROFILE'] = '/profile'
try:
    with patch.object(RegularBrowserTransport, 'navigate', navigate):
        before = usage('/tmp')
        browser = RegularBrowserTransport('offline', {})
        try:
            assert '--disk-cache-dir=/profile' in browser.chrome.args, 'cache bypasses hard mounts'
            assert browser.cache is None
            # Offline mock only: enable HTTP caching to exercise the hard mount.
            browser.context.unroute('**/*', browser.guard)
            browser.lifecycle.send('Network.setCacheDisabled', {'cacheDisabled': False})
            for index in range(80):
                length = browser.page.evaluate('async url => (await (await fetch(url)).arrayBuffer()).byteLength', f'{base}/blob?n={index}')
                assert length == 1024 * 1024
            stat = os.statvfs('/profile/Default/Cache')
            assert stat.f_blocks * stat.f_frsize == 32 * 1024 * 1024
            assert usage('/profile/Default/Cache') > 1024 * 1024, 'mock workload did not populate HTTP cache'
            assert usage('/tmp') - before < 64 * 1024 * 1024, 'HTTP cache leaked into /tmp'
            browser.context.add_cookies([{'name':'offline-cache-test','value':'persisted','url':base,'expires':time.time()+3600}])
            print({'requestedBytes':80*1024*1024,'cacheUsedBytes':usage('/profile/Default/Cache'),'cacheLimitBytes':32*1024*1024,'tmpGrowthBytes':usage('/tmp')-before}, flush=True)
        finally:
            browser.close()
        restarted = RegularBrowserTransport('offline', {})
        try:
            assert any(c['name']=='offline-cache-test' and c['value']=='persisted' for c in restarted.context.cookies(base))
            assert restarted.page.evaluate('document.body.textContent') == 'offline cache test'
        finally:
            restarted.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
print('Catalog hard cache bounds and persistent profile reuse passed')
