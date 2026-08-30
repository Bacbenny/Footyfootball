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

    def test_select_block_prefers_current_title_over_old_id(self):
        payload = {
            "data": {
                "blocks": [
                    {"id": scraper.BLOCK_ID, "data_type": "highlight", "title": "Old"},
                    {"id": "new-event-block", "data_type": "highlight", "title": "Sự kiện Thể thao"},
                ]
            }
        }
        self.assertEqual(scraper.select_block(payload), ("highlight", "new-event-block"))

    def test_discovery_ignores_page_metadata_and_prioritizes_event_title(self):
        payload = {
            "data": {
                "page": {"id": "page-1", "type": "page", "title": "Thể thao"},
                "blocks": [
                    {"block_id": "sports-block", "data_type": "highlight", "title": "Thể thao"},
                    {
                        "block_id": "event-block",
                        "data_type": "highlight",
                        "title": "Sự kiện Thể thao",
                    },
                ],
            }
        }
        candidates = scraper.discover_event_blocks(payload)
        self.assertEqual(candidates[0]["id"], "event-block")
        self.assertNotIn("page-1", {candidate["id"] for candidate in candidates})

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