import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scraper


class ScraperTests(unittest.TestCase):
    def setUp(self):
        self.proxy_env = patch.dict(scraper.os.environ, {"VN_PROXY": ""})
        self.proxy_env.start()
        self.addCleanup(self.proxy_env.stop)
        self.proxy_value = patch.object(scraper, "VN_PROXY", None)
        self.proxy_value.start()
        self.addCleanup(self.proxy_value.stop)

    def test_signature_is_url_safe_base64_md5(self):
        self.assertEqual(scraper.md5_base64url("abc"), "kAFQmDzST7DWlj99KOF_cg")

    def test_signed_params_preserve_extra_values(self):
        with patch.object(scraper.time, "time", return_value=1_700_000_000):
            params = scraper.build_signed_params("/navigation/page/home", {"page": 2})
        self.assertEqual(params["page"], 2)
        self.assertEqual(params["e"], 1_700_003_600)
        self.assertEqual(params["version"], scraper.APP_VERSION)
        self.assertNotIn("=", params["st"])
        self.assertNotIn("/", params["st"])

    def test_block_request_uses_full_url_and_browser_headers(self):
        response = Mock(ok=True)
        response.json.return_value = {"status": True, "data": {"items": None}}
        session = Mock()
        curl_client = Mock()
        curl_client.get.return_value = response

        with patch.object(scraper.time, "time", return_value=1_700_000_000), patch.object(
            scraper, "curl_requests_module", return_value=curl_client
        ):
            url = scraper.build_block_highlight_url("fresh/st token")
            scraper.block_highlight_request(session, "fresh/st token")

        self.assertIn("st=fresh%2Fst%20token", url)
        self.assertIn("e=1700003600", url)
        self.assertIn(
            "block_type=horizontal_slider&custom_data=&page=1&page_size=31&page_id=",
            url,
        )
        self.assertIn(
            "device=Microsoft+Edge+Simulate(version%3A127.0.6533.144)",
            url,
        )
        self.assertIn("drm=1&version=8.7.21", url)
        request_headers = curl_client.get.call_args.kwargs["headers"]
        self.assertEqual(request_headers["User-Agent"], scraper.USER_AGENT)
        self.assertEqual(request_headers["Referer"], "https://fptplay.vn/")
        self.assertEqual(request_headers["Origin"], "https://fptplay.vn")
        curl_client.get.assert_called_once_with(
            url,
            headers=request_headers,
            impersonate="chrome120",
            timeout=30,
        )

    def test_fetch_st_token_uses_anonymous_post_and_vn_proxy(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": {"st": "fresh-token"}}
        session = Mock()
        curl_client = Mock()
        curl_client.post.return_value = response

        with patch.object(scraper, "VN_PROXY", "http://vn-proxy.test:8080"), patch.object(
            scraper, "curl_requests_module", return_value=curl_client
        ):
            token = scraper.fetch_st_token(session)

        self.assertEqual(token, "fresh-token")
        self.assertEqual(
            curl_client.post.call_args.kwargs["proxies"],
            {"http": "http://vn-proxy.test:8080", "https": "http://vn-proxy.test:8080"},
        )
        self.assertEqual(curl_client.post.call_args.args[0], scraper.ANONYMOUS_URL)
        self.assertEqual(curl_client.post.call_args.kwargs["impersonate"], "chrome120")

    def test_fetch_st_token_falls_back_from_http_to_socks5(self):
        failed_response = Mock(ok=False, status_code=403)
        failed_response.headers = {"content-type": "text/html"}
        failed_response.text = "Forbidden"
        success_response = Mock(ok=True)
        success_response.json.return_value = {"data": {"st": "socks-token"}}
        session = Mock()
        curl_client = Mock()
        curl_client.post.side_effect = [failed_response, success_response]

        with patch.object(scraper, "VN_PROXY", "http://user:pass@proxy.test:443"), patch.object(
            scraper, "ensure_socks_support"
        ) as ensure_socks, patch.object(scraper, "curl_requests_module", return_value=curl_client):
            token = scraper.fetch_st_token(session)

        self.assertEqual(token, "socks-token")
        ensure_socks.assert_called_once()
        self.assertEqual(curl_client.post.call_count, 2)
        self.assertEqual(
            curl_client.post.call_args_list[0].kwargs["proxies"],
            {"http": "http://user:pass@proxy.test:443", "https": "http://user:pass@proxy.test:443"},
        )
        self.assertEqual(
            curl_client.post.call_args_list[1].kwargs["proxies"],
            {"http": "socks5://user:pass@proxy.test:443", "https": "socks5://user:pass@proxy.test:443"},
        )

    def test_fetch_st_token_falls_back_for_curl_transport_error(self):
        success_response = Mock(ok=True)
        success_response.json.return_value = {"data": {"st": "socks-token"}}
        session = Mock()
        curl_client = Mock()
        curl_client.post.side_effect = [OSError("curl CONNECT aborted"), success_response]

        with patch.object(scraper, "VN_PROXY", "http://user:pass@proxy.test:443"), patch.object(
            scraper, "ensure_socks_support"
        ), patch.object(scraper, "curl_requests_module", return_value=curl_client):
            token = scraper.fetch_st_token(session)

        self.assertEqual(token, "socks-token")
        self.assertEqual(curl_client.post.call_count, 2)

    def test_request_options_uses_active_socks_proxy(self):
        with patch.object(scraper, "ACTIVE_PROXY_URL", "socks5://user:pass@proxy.test:443"):
            self.assertEqual(
                scraper.request_options(),
                {
                    "proxies": {
                        "http": "socks5://user:pass@proxy.test:443",
                        "https": "socks5://user:pass@proxy.test:443",
                    }
                },
            )

    def test_block_items_parser_extracts_events(self):
        payload = {
            "data": {
                "items": [
                    {
                        "id": "event-1",
                        "type": "event",
                        "title": "Heineken Pickleball World Cup 2026",
                    }
                ],
            }
        }
        events = scraper.find_block_items(payload)
        self.assertEqual(
            events,
            [
                {
                    "id": "event-1",
                    "type": "event",
                    "title": "Heineken Pickleball World Cup 2026",
                }
            ],
        )
        self.assertEqual(scraper.find_block_items({"data": {"items": None}}), [])

    def test_build_playlist_uses_block_items_and_streams(self):
        block_payload = {
            "status": True,
            "data": {
                "items": [
                    {
                        "id": "event-1",
                        "type": "event",
                        "title": "Sự kiện thể thao",
                    }
                ]
            },
        }
        stream_payload = {
            "data": {
                "url": "https://cdn.example.test/event-1/master.m3u8",
            }
        }
        session = Mock()
        with patch.object(scraper, "fetch_st_token", return_value="fresh-token"), patch.object(
            scraper, "block_highlight_request", return_value=block_payload
        ) as block_request, patch.object(scraper, "api_request", return_value=stream_payload) as stream_request:
            playlist = scraper.build_playlist(session)

        self.assertIn('group-title="Sự Kiện FPT",Sự kiện thể thao', playlist)
        self.assertIn("https://cdn.example.test/event-1/master.m3u8", playlist)
        self.assertNotIn("/topic", playlist)
        block_request.assert_called_once_with(session, "fresh-token")
        stream_request.assert_called_once()
        self.assertNotIn("st_token", stream_request.call_args.kwargs)

    def test_build_playlist_rejects_empty_block_items(self):
        session = Mock()
        with patch.object(scraper, "fetch_st_token", return_value="fresh-token"), patch.object(
            scraper,
            "block_highlight_request",
            return_value={"status": True, "data": {"items": None}},
        ):
            with self.assertRaisesRegex(RuntimeError, "playlist was not replaced"):
                scraper.build_playlist(session)

    def test_parser_handles_current_item_shape_and_clearkey(self):
        payload = {
            "data": {
                "items": [
                    {
                        "id": "event-1",
                        "type": "event",
                        "title": "Live &amp; Clear",
                        "stream": {
                            "url": "https://cdn.example.test/event-1/master.m3u8",
                            "keyId": "kid-1",
                            "key": "key-1",
                        },
                    }
                ]
            }
        }
        self.assertEqual(
            scraper.find_highlights(payload),
            [{"id": "event-1", "type": "event", "title": "Live &amp; Clear"}],
        )
        self.assertEqual(
            scraper.find_streams(payload),
            [{"url": "https://cdn.example.test/event-1/master.m3u8", "key_id": "kid-1", "key": "key-1"}],
        )
        self.assertEqual(scraper.clean_title("Live &amp; Clear"), "Live & Clear")

    def test_stream_parser_rejects_embed_and_image_urls(self):
        self.assertTrue(scraper.is_stream_url("https://cdn.example.test/live.mpd", "url"))
        self.assertFalse(scraper.is_stream_url("https://fptplay.vn/embed/event", "url"))
        self.assertFalse(scraper.is_stream_url("https://cdn.example.test/poster.jpg", "url"))

    def test_atomic_write_replaces_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playlist.m3u"
            scraper.atomic_write(path, "#EXTM3U\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "#EXTM3U\n")
            self.assertFalse((path.parent / ".playlist.m3u.tmp").exists())

    def test_main_keeps_existing_playlist_when_generation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playlist.m3u"
            old_playlist = "#EXTM3U\n# old valid entry\n"
            path.write_text(old_playlist, encoding="utf-8")
            with patch.object(scraper, "OUTPUT_PATH", path), patch.object(
                scraper, "build_playlist", side_effect=RuntimeError("API unavailable")
            ):
                with self.assertRaises(RuntimeError):
                    scraper.main()
            self.assertEqual(path.read_text(encoding="utf-8"), old_playlist)


if __name__ == "__main__":
    unittest.main()