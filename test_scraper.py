import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scraper


class ScraperTests(unittest.TestCase):
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
        session.get.return_value = response

        self.assertIn(
            "block_type=horizontal_slider&custom_data=&page=1&page_size=31&page_id=",
            scraper.BLOCK_HIGHLIGHT_URL,
        )
        self.assertIn("st=Usc8ZRLFvbSv3g9L6eLjgw", scraper.BLOCK_HIGHLIGHT_URL)
        self.assertIn("e=1788060689", scraper.BLOCK_HIGHLIGHT_URL)
        self.assertIn(
            "device=Microsoft%20Edge%20Simulate(version%3A127.0.6533.144)",
            scraper.BLOCK_HIGHLIGHT_URL,
        )
        self.assertIn("drm=1&version=8.7.21", scraper.BLOCK_HIGHLIGHT_URL)

        scraper.block_highlight_request(session)
        request_headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(request_headers["User-Agent"], scraper.USER_AGENT)
        self.assertEqual(request_headers["Referer"], "https://fptplay.vn/")
        self.assertEqual(request_headers["Origin"], "https://fptplay.vn")
        session.get.assert_called_once_with(
            scraper.BLOCK_HIGHLIGHT_URL,
            headers=request_headers,
            timeout=30,
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
        with patch.object(scraper, "block_highlight_request", return_value=block_payload), patch.object(
            scraper, "api_request", return_value=stream_payload
        ) as stream_request:
            playlist = scraper.build_playlist(session)

        self.assertIn('group-title="Sự Kiện FPT",Sự kiện thể thao', playlist)
        self.assertIn("https://cdn.example.test/event-1/master.m3u8", playlist)
        self.assertNotIn("/topic", playlist)
        stream_request.assert_called_once()
        self.assertNotIn("st_token", stream_request.call_args.kwargs)

    def test_build_playlist_rejects_empty_block_items(self):
        session = Mock()
        with patch.object(
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