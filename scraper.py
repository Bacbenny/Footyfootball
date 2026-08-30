#!/usr/bin/env python3
"""Generate an M3U playlist for the FPT Play "Sự Kiện FPT" group."""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import os
import re
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE_URL = "https://api.fptplay.net"
API_VERSION = os.environ.get("FPT_API_VERSION", "v7.1_w")
APP_VERSION = os.environ.get("FPT_APP_VERSION", "8.7.21")
SIGNATURE_SECRET = "6ea6d2a4e2d3a4bd5e275401aa086d"
PAGE_ID = os.environ.get("FPT_PAGE_ID", "home")
BLOCK_ID = os.environ.get("FPT_BLOCK_ID", "632f01322089bd00e5c5ed3d")
BLOCK_TYPE = os.environ.get("FPT_BLOCK_TYPE", "highlight")
DISCOVERY_PATHS = ("/navigation/sport", "/home", "/navigation/page/home")
STREAM_URL_TEMPLATE = os.environ.get(
    "FPT_STREAM_URL_TEMPLATE",
    "/stream/{stream_type}/{highlight_id}/0/adaptive_bitrate",
)
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
    "Accept": "application/json, text/plain, */*",
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
HIGHLIGHT_ID_KEYS = (
    "highlight_id",
    "highlightId",
    "highlightID",
    "content_id",
    "contentId",
    "target_id",
    "targetId",
    "id",
    "_id",
)
BLOCK_ID_KEYS = ("block_id", "blockId", "_id", "id")
TYPE_KEYS = (
    "type",
    "stream_type",
    "streamType",
    "content_type",
    "contentType",
    "data_type",
)
TITLE_KEYS = (
    "title",
    "name",
    "label",
    "event_name",
    "eventName",
    "display_name",
    "displayName",
    "title_vie",
    "title_vi",
)
KEY_ID_KEYS = ("keyId", "key_id", "keyID", "kid", "contentId", "content_id")
KEY_VALUE_KEYS = ("key", "clearKey", "clear_key", "clearkey", "license_key", "licenseKey")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)


class FptApiError(RuntimeError):
    """An API error whose message is safe to print in CI logs."""

    def __init__(self, label: str, status: int, detail: str) -> None:
        super().__init__(f"{label} failed with HTTP {status}: {detail}")
        self.label = label
        self.status = status


def _safe_response_detail(response: requests.Response) -> str:
    """Return a short, non-sensitive response description for workflow logs."""
    content_type = response.headers.get("content-type", "unknown").split(";")[0]
    body = re.sub(r"\s+", " ", response.text[:240]).strip()
    body = re.sub(r"(?i)(bearer|token|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", body)
    return f"content-type={content_type}; body={body or '<empty>'}"


def md5_base64url(value: str) -> str:
    """Match FPT Play's browser request signature (MD5 bytes, URL-safe base64)."""
    digest_hex = hashlib.md5(value.encode("utf-8")).hexdigest()
    return base64.urlsafe_b64encode(bytes.fromhex(digest_hex)).decode("ascii").rstrip("=")


def build_signed_params(path: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the signed query used by the current FPT Play web client."""
    clean_path = path.lstrip("/")
    expires = int(time.time()) + 3600
    suffix = f"/api/{API_VERSION}/{clean_path}"
    signature = md5_base64url(f"{SIGNATURE_SECRET}{expires}{suffix}")
    params: dict[str, Any] = dict(extra or {})
    params.update(
        {
            "st": signature,
            "e": expires,
            "device": "Chrome(version:127.0.0.0)",
            "drm": 1,
            "version": APP_VERSION,
        }
    )
    return params


def api_request(
    session: requests.Session,
    method: str,
    path: str,
    *,
    user_token: str | None = None,
    params: Mapping[str, Any] | None = None,
    label: str,
) -> Any:
    """Call an FPT endpoint with the same signed URL scheme as fptplay.vn."""
    clean_path = "/" + path.lstrip("/")
    url = f"{API_BASE_URL}/api/{API_VERSION}{clean_path}"
    headers: dict[str, str] = {
        "X-Did": os.environ.get("FPT_DEVICE_ID", "github-actions-footyfootball")
    }
    if user_token:
        headers["Authorization"] = f"{os.environ.get('FPT_AUTH_SCHEME', 'Bearer')} {user_token}"

    response = session.request(
        method,
        url,
        params=build_signed_params(clean_path, params),
        headers=headers,
        timeout=30,
    )
    if not response.ok:
        raise FptApiError(label, response.status_code, _safe_response_detail(response))
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc


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
    parsed = urlparse(value)
    path = parsed.path.lower()
    if re.search(r"\.(?:jpg|jpeg|png|gif|webp|svg)(?:$|/)", path):
        return False
    if parsed.hostname and parsed.hostname.lower() in {
        "fptplay.vn",
        "www.fptplay.vn",
        "api.fptplay.net",
    }:
        return False
    if re.search(r"(?:/embed/|\.html?$)", path):
        return False
    # Stream endpoints sometimes return signed CDN URLs without an extension.
    return key in STREAM_KEYS


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


def page_blocks(payload: Any) -> list[Mapping[str, Any]]:
    """Return the blocks from /navigation/page/{page_id}."""
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("blocks"), list):
            return [block for block in data["blocks"] if isinstance(block, Mapping)]
    return []


def is_event_block_title(value: str) -> bool:
    title = clean_title(value).casefold()
    return any(term in title for term in ("sự kiện thể thao", "sự kiện", "thể thao"))


def discover_event_blocks(payload: Any) -> list[dict[str, str]]:
    """Find all matching blocks and retain every possible API identifier."""
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in walk_dicts(payload):
        title = first_text(mapping, TITLE_KEYS)
        if not title or not is_event_block_title(title):
            continue
        block_type = first_text(
            mapping, ("block_type", "blockType", "data_type", "dataType", "type")
        ) or BLOCK_TYPE
        if block_type not in ALLOWED_TYPES and block_type != BLOCK_TYPE:
            continue
        for key in BLOCK_ID_KEYS:
            block_id = first_text(mapping, (key,))
            if not block_id:
                continue
            identity = (block_type, block_id)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append({"type": block_type, "id": block_id, "title": clean_title(title)})

    def priority(candidate: dict[str, str]) -> tuple[int, str]:
        title = candidate["title"].casefold()
        if "sự kiện thể thao" in title:
            return 0, title
        if "sự kiện" in title:
            return 1, title
        return 2, title

    return sorted(candidates, key=priority)


def select_block(payload: Any) -> tuple[str, str]:
    """Select the first dynamically discovered event block."""
    candidates = discover_event_blocks(payload)
    if candidates:
        candidate = candidates[0]
        LOGGER.info(
            "Using event block %s (%s) discovered from page data",
            candidate["id"],
            candidate["title"],
        )
        return candidate["type"], candidate["id"]
    LOGGER.info("Falling back to configured event block %s (%s)", BLOCK_ID, BLOCK_TYPE)
    return BLOCK_TYPE, BLOCK_ID


def discover_event_block_candidates(
    session: requests.Session,
    *,
    user_token: str | None = None,
) -> list[dict[str, str]]:
    """Discover blocks from the requested catalogs, then the current page API."""
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in DISCOVERY_PATHS:
        try:
            payload = api_request(
                session,
                "GET",
                path,
                user_token=user_token,
                label=f"FPT Play block discovery {path}",
            )
        except (FptApiError, requests.RequestException, RuntimeError) as exc:
            LOGGER.warning("Block discovery skipped for %s: %s", path, exc)
            continue
        for candidate in discover_event_blocks(payload):
            identity = (candidate["type"], candidate["id"])
            if identity not in seen:
                seen.add(identity)
                candidates.append(candidate)

    if not candidates:
        candidates.append({"type": BLOCK_TYPE, "id": BLOCK_ID, "title": GROUP_TITLE})
    return candidates


def atomic_write(path: Path, content: str) -> None:
    """Replace the playlist only after a complete valid playlist was generated."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def build_playlist(
    session: requests.Session,
    *,
    user_token: str | None = None,
) -> str:
    block_candidates = discover_event_block_candidates(session, user_token=user_token)
    highlights: list[dict[str, str]] = []
    for candidate in block_candidates:
        try:
            block_payload = api_request(
                session,
                "GET",
                f"/navigation/block/{quote(candidate['type'], safe='')}/{quote(candidate['id'], safe='')}",
                user_token=user_token,
                params={
                    "page_id": PAGE_ID,
                    "page": 1,
                    "page_size": 31,
                    "block_type": candidate["type"],
                    "custom_data": "",
                },
                label=f"FPT Play event block API {candidate['id']}",
            )
            highlights = find_highlights(block_payload)
        except (FptApiError, requests.RequestException, RuntimeError) as exc:
            LOGGER.warning("Event block skipped for %s: %s", candidate["id"], exc)
            continue
        if highlights:
            LOGGER.info("Using event block %s (%s)", candidate["id"], candidate["title"])
            break

    LOGGER.info("Found %d FPT Play highlights", len(highlights))
    print(f"FPT Play events found: {len(highlights)}")
    for highlight in highlights:
        print(f"- {clean_title(highlight['title'])} [{highlight['type']}/{highlight['id']}]")
    if not highlights:
        raise RuntimeError(
            "FPT Play returned no event items; playlist was not replaced. "
            "This can mean there are currently no published events."
        )

    lines = ["#EXTM3U"]
    playlist_urls: set[str] = set()
    for highlight in highlights:
        path = STREAM_URL_TEMPLATE.format(
            stream_type=quote(highlight["type"], safe=""),
            highlight_id=quote(highlight["id"], safe=""),
        )
        try:
            stream_payload = api_request(
                session,
                "GET",
                path,
                user_token=user_token,
                label=f"FPT Play stream API for {highlight['id']}",
            )
        except (FptApiError, requests.RequestException, RuntimeError) as exc:
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
    use_user_token = os.environ.get("FPT_USE_USER_TOKEN", "false").lower() in {"1", "true", "yes"}
    if use_user_token and not user_token:
        raise RuntimeError("FPT_USE_USER_TOKEN is enabled but USER_TOKEN is not set")

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    with requests.Session() as session:
        session.headers.update(REQUEST_HEADERS)
        session.mount("https://", HTTPAdapter(max_retries=retry))
        playlist = build_playlist(
            session,
            user_token=user_token if use_user_token else None,
        )

    atomic_write(OUTPUT_PATH, playlist)
    LOGGER.info("Wrote %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
