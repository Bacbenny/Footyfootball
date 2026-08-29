#!/usr/bin/env python3
"""Generate an M3U playlist for the FPT Play "Sự Kiện FPT" group."""

from __future__ import annotations

import html
import logging
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

ANONYMOUS_URL = "https://api.fptplay.net/api/v7.1_w/user/anonymous"
HIGHLIGHTS_URL = "https://api.fptplay.net/api/v7.1_w/navigation/block/highlight/632f01322089bd00e5c5ed3d"
STREAM_URL_TEMPLATE = "https://api.fptplay.net/api/v7.1_w/stream/{stream_type}/{highlight_id}/0/adaptive_bitrate"
OUTPUT_PATH = Path("playlist.m3u")
GROUP_TITLE = "Sự Kiện FPT"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://fptplay.vn/",
    "Origin": "https://fptplay.vn",
}
PLAYLIST_HEADERS = f"|User-Agent={USER_AGENT}&Referer=https://fptplay.vn/"
ALLOWED_TYPES = {"vod", "event", "live"}
STREAM_KEYS = (
    "url",
    "stream",
    "stream_url",
    "streamUrl",
    "play_url",
    "playUrl",
    "playback_url",
    "playbackUrl",
    "file_url",
    "fileUrl",
    "manifest_url",
    "manifestUrl",
    "hls_url",
    "hlsUrl",
    "dash_url",
    "dashUrl",
)
HIGHLIGHT_ID_KEYS = ("highlight_id", "highlightId", "highlightID")
TYPE_KEYS = ("type", "stream_type", "streamType", "content_type", "contentType")
TITLE_KEYS = (
    "title",
    "name",
    "label",
    "event_name",
    "eventName",
    "display_name",
    "displayName",
)
KEY_ID_KEYS = ("keyId", "key_id", "keyID", "kid", "contentId", "content_id")
KEY_VALUE_KEYS = ("key", "clearKey", "clear_key", "clearkey", "license_key", "licenseKey")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def walk_dicts(value: Any) -> Iterator[Mapping[str, Any]]:
    """Yield every mapping nested in an API response."""
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_dicts(nested)


def first_text(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and not isinstance(value, (Mapping, list)):
            text = str(value).strip()
            if text:
                return text
    return None


def response_json(response: requests.Response, label: str) -> Any:
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc


def find_st_token(payload: Any) -> str | None:
    token_keys = ("st", "st_token", "stToken", "ST_TOKEN", "token")
    for mapping in walk_dicts(payload):
        for key in token_keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def find_highlights(payload: Any) -> list[dict[str, str]]:
    highlights: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in walk_dicts(payload):
        highlight_id = first_text(mapping, HIGHLIGHT_ID_KEYS)
        stream_type = first_text(mapping, TYPE_KEYS)
        if not highlight_id or not stream_type:
            continue
        stream_type = stream_type.lower()
        if stream_type not in ALLOWED_TYPES:
            continue
        identity = (stream_type, highlight_id)
        if identity in seen:
            continue
        seen.add(identity)
        title = first_text(mapping, TITLE_KEYS) or f"FPT {stream_type} {highlight_id}"
        highlights.append({"id": highlight_id, "type": stream_type, "title": title})
    return highlights


def is_stream_url(value: Any, key: str) -> bool:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return False
    path = urlparse(value).path.lower()
    if re.search(r"\.(?:jpg|jpeg|png|gif|webp|svg)(?:$|/)", path):
        return False
    return key != "url" or any(marker in value.lower() for marker in (".m3u8", ".mpd", "manifest", "stream"))


def find_clear_key(value: Any) -> tuple[str, str] | None:
    for mapping in walk_dicts(value):
        key_id = first_text(mapping, KEY_ID_KEYS)
        key = first_text(mapping, KEY_VALUE_KEYS)
        if key_id and key and key_id != key:
            return key_id, key
    return None


def find_streams(payload: Any) -> list[dict[str, str | None]]:
    streams: list[dict[str, str | None]] = []
    seen_urls: set[str] = set()
    for mapping in walk_dicts(payload):
        drm = find_clear_key(mapping)
        for key in STREAM_KEYS:
            value = mapping.get(key)
            if not is_stream_url(value, key):
                continue
            assert isinstance(value, str)
            if value in seen_urls:
                continue
            seen_urls.add(value)
            streams.append({"url": value, "key_id": drm[0] if drm else None, "key": drm[1] if drm else None})
    return streams


def clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip() or "FPT Play event"


def build_playlist(session: requests.Session, st_token: str) -> str:
    navigation_response = session.get(HIGHLIGHTS_URL, params={"st": st_token}, timeout=30)
    navigation = response_json(navigation_response, "FPT Play highlight API")
    highlights = find_highlights(navigation)
    LOGGER.info("Found %d FPT Play highlights", len(highlights))
    if not highlights:
        raise RuntimeError("No supported FPT Play highlights were found")

    lines = ["#EXTM3U"]
    playlist_urls: set[str] = set()
    for highlight in highlights:
        url = STREAM_URL_TEMPLATE.format(stream_type=highlight["type"], highlight_id=highlight["id"])
        try:
            stream_response = session.get(url, params={"st": st_token}, timeout=30)
            stream_payload = response_json(stream_response, f"stream API for {highlight['id']}")
        except requests.RequestException as exc:
            LOGGER.warning("Skipping %s: %s", highlight["id"], exc)
            continue

        streams = find_streams(stream_payload)
        for stream in streams:
            stream_url = stream["url"]
            if not stream_url or stream_url in playlist_urls:
                continue
            playlist_urls.add(stream_url)
            title = clean_title(highlight["title"])
            lines.append(f'#EXTINF:-1 group-title="{GROUP_TITLE}",{title}')
            if stream["key_id"] and stream["key"]:
                lines.append("#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey")
                lines.append(f"#KODIPROP:inputstream.adaptive.license_key={stream['key_id']}:{stream['key']}")
            lines.append(f"{stream_url}{PLAYLIST_HEADERS}")

    if len(lines) == 1:
        raise RuntimeError("FPT Play returned no playable streams; keeping the existing playlist")
    LOGGER.info("Generated %d playlist entries", len(playlist_urls))
    return "\n".join(lines) + "\n"


def main() -> None:
    user_token = os.environ.get("USER_TOKEN")
    if not user_token:
        raise RuntimeError("USER_TOKEN is not set; add it as a GitHub Actions secret")

    headers = {**REQUEST_HEADERS, "Authorization": f"Bearer {user_token}"}
    with requests.Session() as session:
        session.headers.update(headers)
        anonymous_response = session.post(ANONYMOUS_URL, timeout=30)
        anonymous_payload = response_json(anonymous_response, "FPT Play anonymous API")
        st_token = find_st_token(anonymous_payload)
        if not st_token:
            raise RuntimeError("FPT Play anonymous API did not return an ST_TOKEN")
        playlist = build_playlist(session, st_token)

    OUTPUT_PATH.write_text(playlist, encoding="utf-8")
    LOGGER.info("Wrote %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
