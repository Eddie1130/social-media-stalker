"""Exercise post diagnostics against loopback fixtures in a network-isolated image."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from playwright.sync_api import sync_playwright
from catalog_browser import BrowserTransport
from catalog_errors import safe_diagnostic


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"items":[]}' if self.path.endswith('json') else b''
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        if self.path.endswith('broken'):
            self.send_header('Content-Length', '10')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


with ThreadingHTTPServer(('127.0.0.1', 0), Fixture) as server, sync_playwright() as engine:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = engine.chromium.launch(executable_path=engine.chromium.executable_path, args=['--no-sandbox'])
    try:
        page = browser.new_page()
        base = f'http://127.0.0.1:{server.server_port}'
        page.goto(base)
        ctx = SimpleNamespace(page=page)
        def request(case):
            return BrowserTransport.post_response(ctx, base + '/api/post/item_list/?' + case)
        empty = request('empty')
        assert empty.text == '' and empty.post_trace['readBytes'] == 0
        assert empty.post_trace['declaredBytes'] is None
        normal = request('json')
        assert json.loads(normal.text) == {'items': []}
        assert normal.post_trace['readBytes'] == len(normal.text)
        assert normal.post_trace['id'] != empty.post_trace['id']
        try:
            request('broken')
        except RuntimeError as error:
            trace = safe_diagnostic(error)['postResponse']
            assert trace['stage'] == 'read' and trace['declaredBytes'] == 10
            assert trace['readError'] == 'TypeError' and 'readBytes' not in trace
        else:
            raise AssertionError('truncated transfer accepted')
        print('PASS: empty, JSON, truncated transfer')
    finally:
        browser.close()
        server.shutdown()
