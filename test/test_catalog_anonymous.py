"""Public post reads must not inherit account authentication."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tiktok"))
from catalog_worker import SessionProvider
from catalog_regular_browser import POST_LIST_HEADER, RegularBrowserTransport


class AnonymousPostsTests(unittest.TestCase):
    def test_only_explicit_post_list_request_can_reach_the_endpoint(self):
        browser = RegularBrowserTransport.__new__(RegularBrowserTransport)
        for allow_post, path, method, marker, blocked in (
            (False, "/api/post/item_list/", "GET", "active", True),
            (False, "/api/story/item_list/", "GET", None, False),
            (True, "/api/post/item_list/", "GET", None, True),
            (True, "/api/post/item_list/", "GET", "stale", True),
            (True, "/api/post/item_list/", "POST", "active", True),
            (True, "/api/post/item_list/", "GET", "active", False),
        ):
            with self.subTest(allow_post=allow_post, path=path, method=method, marker=marker):
                browser.allow_post_list = allow_post
                browser.post_list_token = "active"
                route = Mock()
                route.request.url = f"https://www.tiktok.com{path}?count=20"
                route.request.resource_type = "fetch"
                route.request.method = method
                headers = {"accept": "application/json"}
                if marker:
                    headers[POST_LIST_HEADER] = marker
                route.request.headers = headers
                route.request.all_headers.return_value = headers.copy()
                browser.guard(route)
                self.assertEqual(route.abort.called, blocked)
                self.assertEqual(route.continue_.called, not blocked)
                if not blocked and marker:
                    route.continue_.assert_called_once_with(headers={"accept": "application/json"})
                    self.assertIsNone(browser.post_list_token)

    def test_post_uses_empty_cookie_input_and_authenticated_story_restores_identity(self):
        browser = Mock()
        browser.select_anonymous.return_value = True
        session = SessionProvider()
        with patch.dict(os.environ, {"TIKTOK_CATALOG_ANONYMOUS_POSTS": "1"}), patch(
            "catalog_worker.cookies", return_value={"sessionid": "private"}
        ) as cookie_source, patch("catalog_regular_browser.RegularBrowserTransport", return_value=browser) as factory, patch(
            "catalog_provider.fetch_page", return_value={"items": []}
        ) as fetch:
            session._query("alice", "post")
            cookie_source.assert_not_called()
            factory.assert_called_once_with("alice", {}, anonymous=True, allow_post_list=True)
            self.assertEqual(fetch.call_args.args[0]["cookies"], {})
            session._query("alice", "story")
            browser.select_anonymous.assert_called_with(False)
            self.assertFalse(browser.allow_post_list)
            self.assertEqual(fetch.call_args.args[0]["cookies"], {"sessionid": "private"})
            self.assertEqual(factory.call_count, 1)

    def test_opt_out_keeps_authenticated_posts(self):
        session = SessionProvider()
        with patch.dict(os.environ, {"TIKTOK_CATALOG_ANONYMOUS_POSTS": "0"}), patch(
            "catalog_worker.cookies", return_value={"sessionid": "private"}
        ), patch("catalog_regular_browser.RegularBrowserTransport", return_value=Mock()) as factory, patch(
            "catalog_provider.fetch_page", return_value={}
        ) as fetch:
            session._query("alice", "post")
            factory.assert_called_once_with(
                "alice", {"sessionid": "private"}, anonymous=False, allow_post_list=True
            )
            self.assertEqual(fetch.call_args.args[0]["cookies"], {"sessionid": "private"})

    def test_context_switch_reuses_anonymous_context_without_copying_cookies(self):
        browser = RegularBrowserTransport.__new__(RegularBrowserTransport)
        browser.anonymous = False
        browser.authenticated_context = Mock()
        browser.anonymous_context = None
        browser.context = browser.authenticated_context
        browser.remote = Mock()
        browser.prepare_reader_page = Mock()
        browser.guard_workers = Mock()
        browser.page = Mock()
        browser.lifecycle = Mock()
        browser.park = Mock()
        self.assertTrue(browser.select_anonymous(True))
        anon = browser.remote.new_context.return_value
        self.assertIs(browser.context, anon)
        anon.add_cookies.assert_not_called()
        self.assertFalse(browser.select_anonymous(True))
        self.assertTrue(browser.select_anonymous(False))
        self.assertIs(browser.context, browser.authenticated_context)
        self.assertTrue(browser.select_anonymous(True))
        self.assertEqual(browser.remote.new_context.call_count, 1)
