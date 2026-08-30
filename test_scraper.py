import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_find_st_token_and_preserve_it_for_signed_requests(self):
        self.assertEqual(scraper.find_st_token({"data": {"ST_TOKEN": "st-token"}}), "st-token")
        params = scraper.build_signed_params("/topic", st_token="st-token")
        self.assertEqual(params["st"], "st-token")

    def test_topic_category_parser_extracts_live_events(self):
        payload = {
            "data": {
                "page": {"id": "page-1", "type": "page", "title": "Thể thao"},
                "items": [
                    {
                        "id": "event-1",
                        "type": "event",
                        "title": "Heineken Pickleball World Cup 2026",
                    }
                ],
            }
        }
        events = scraper.find_event_items(payload, {"items": []})
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