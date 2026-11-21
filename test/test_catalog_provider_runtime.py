"""Characterize the pinned gallery-dl bridge without external requests."""

import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tiktok"))
from catalog_provider import ProviderError, fetch_page

try:
    from gallery_dl.extractor import tiktok
except ImportError:
    tiktok = None


@unittest.skipIf(tiktok is None, "requires the pinned gallery-dl runtime")
class ProviderRuntimeTests(unittest.TestCase):
    def test_paced_post_worker_sends_only_one_request_for_malformed_json(self):
        scope = {
            "webapp.user-detail": {"statusCode": 0, "userInfo": {"user": {
                "id": "123", "secUid": "fixture", "uniqueId": "alice",
            }}},
            "webapp.app-context": {},
        }
        html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">' + json.dumps({"__DEFAULT_SCOPE__": scope}) + "</script>"
        transport = self.transport(html)
        original = transport.request
        posts = []

        def request(url):
            response = original(url)
            if "/api/post/item_list/" in url:
                posts.append(url)
                response.text = "malformed JSON"
            return response

        transport.request = request
        with patch('catalog_provider.POST_REQUEST_GAP_MS', 120000, create=True):
            with self.assertRaisesRegex(ProviderError, 'TIKTOK_RESPONSE_INVALID'):
                fetch_page({"username": "alice", "kind": "post", "cookies": {}}, transport)
        self.assertEqual(len(posts), 1)

    def transport(self, html):
        return SimpleNamespace(
            page=SimpleNamespace(evaluate=lambda script: "Mozilla/5.0"),
            request=lambda url: SimpleNamespace(
                status_code=200, text=html, url=url, history=[]
            ),
        )

    def test_invalid_profile_keeps_parse_error_and_does_not_leak_payload(self):
        private = "private-cookie-secret"
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(tiktok.TiktokExtractor, "_solve_challenge", side_effect=ValueError(private)), patch.object(
            tiktok.TiktokExtractor, "sleep"
        ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(ValueError):
                fetch_page(
                    {"username": "alice", "kind": "profile", "cookies": {}},
                    self.transport("<html>" + private + "</html>"),
                )
        self.assertNotIn(private, output.getvalue() + errors.getvalue())

    def test_profile_data_still_passes_through_real_extractor(self):
        scope = {
            "webapp.user-detail": {"statusCode": 0, "userInfo": {"user": {
                "id": "123", "secUid": "secret-id", "uniqueId": "alice",
                "avatarLarger": "https://p.tiktokcdn.com/avatar.jpg",
            }}},
            "webapp.app-context": {},
        }
        html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">' + json.dumps({"__DEFAULT_SCOPE__": scope}) + "</script>"
        result = fetch_page(
            {"username": "alice", "kind": "profile", "cookies": {}},
            self.transport(html),
        )
        self.assertEqual(result["profile"]["id"], "123")
        self.assertEqual(result["profile"]["username"], "alice")
