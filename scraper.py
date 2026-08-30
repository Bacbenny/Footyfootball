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
ANONYMOUS_URL = f"{API_BASE_URL}/api/{API_VERSION}/user/anonymous"
BLOCK_HIGHLIGHT_URL_TEMPLATE = (
    f"{API_BASE_URL}/api/{API_VERSION}/navigation/block/highlight/"
    "632f01322089bd00e5c5ed3d?"
    "block_type=horizontal_slider&custom_data=&page=1&page_size=31&page_id=&"
    "st={st}&e={e}&"
    "device=Microsoft+Edge+Simulate(version%3A127.0.6533.144)&"
    "drm=1&version=8.7.21"
)
VN_PROXY = os.environ.get("VN_PROXY")
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


def build_signed_params(
    path: str,
    extra: Mapping[str, Any] | None = None,
    *,
    st_token: str | None = None,
) -> dict[str, Any]:
    """Build the signed query used by the current FPT Play web client."""
    clean_path = path.lstrip("/")
    expires = int(time.time()) + 3600
    suffix = f"/api/{API_VERSION}/{clean_path}"
    signature = md5_base64url(f"{SIGNATURE_SECRET}{expires}{suffix}")
    params: dict[str, Any] = dict(extra or {})
    params.update(
        {
            "st": st_token or signature,
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
    st_token: str | None = None,
    params: Mapping[str, Any] | None = None,
    label: str,
) -> Any:
    """Call an FPT endpoint with the same signed URL scheme as fptplay.vn."""
    clean_path = "/" + path.lstrip("/")
    url = f"{API_BASE_URL}/api/{API_VERSION}{clean_path}"
    headers: dict[str, str] = dict(REQUEST_HEADERS)
    headers.update({
        "X-Did": os.environ.get("FPT_DEVICE_ID", "github-actions-footyfootball")
    })
    if user_token:
        headers["Authorization"] = f"{os.environ.get('FPT_AUTH_SCHEME', 'Bearer')} {user_token}"

    response = session.request(
        method,
        url,
        params=build_signed_params(clean_path, params, st_token=st_token),
        headers=headers,
        timeout=30,
        **request_options(),
    )
    if not response.ok:
        raise FptApiError(label, response.status_code, _safe_response_detail(response))
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc


def request_options() -> dict[str, Any]:
    """Return proxy options for every outbound request when configured."""
    proxy = VN_PROXY or os.environ.get("VN_PROXY")
    if not proxy:
        return {}
    return {"proxies": {"http": proxy, "https": proxy}}


def find_st_token(payload: Any) -> str | None:
    """Extract the short-lived ST token from the anonymous response."""
    for mapping in walk_dicts(payload):
        for key in ("st", "st_token", "stToken", "ST_TOKEN", "token"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def fetch_st_token(session: requests.Session) -> str:
    """Get a fresh ST token before every Block Highlight scrape."""
    headers = dict(REQUEST_HEADERS)
    headers["X-Did"] = os.environ.get("FPT_DEVICE_ID", "github-actions-footyfootball")
    response = session.post(
        ANONYMOUS_URL,
        headers=headers,
        timeout=30,
        **request_options(),
    )
    if not response.ok:
        raise FptApiError(
            "FPT Play anonymous API",
            response.status_code,
            _safe_response_detail(response),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("FPT Play anonymous API returned invalid JSON") from exc
    token = find_st_token(payload)
    if not token:
        raise RuntimeError("FPT Play anonymous API returned no ST token")
    return token


def build_block_highlight_url(st_token: str) -> str:
    """Build the Block Highlight URL with a fresh token and one-hour expiry."""
    expires = int(time.time() + 3600)
    return BLOCK_HIGHLIGHT_URL_TEMPLATE.format(st=quote(st_token, safe=""), e=expires)


def block_highlight_request(session: requests.Session, st_token: str) -> Any:
    """Fetch Block Highlight using the complete URL and browser headers."""
    headers = dict(REQUEST_HEADERS)
    headers["X-Did"] = os.environ.get("FPT_DEVICE_ID", "github-actions-footyfootball")
    response = session.get(
        build_block_highlight_url(st_token),
        headers=headers,
        timeout=30,
        **request_options(),
    )
    if not response.ok:
        raise FptApiError(
            "FPT Play Block Highlight API",
            response.status_code,
            _safe_response_detail(response),
        )
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("FPT Play Block Highlight API returned invalid JSON") from exc


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
        stream_type = first_text(mapping, TYPE_KEYS) or "event"
        if not highlight_id:
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


def find_block_items(payload: Any) -> list[dict[str, str]]:
    """Extract only event records from the Block Highlight data.items array."""
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return []
    return find_highlights(items)


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
    try:
        st_token = fetch_st_token(session)
        block_payload = block_highlight_request(session, st_token)
    except (FptApiError, requests.RequestException, RuntimeError) as exc:
        LOGGER.warning("FPT Play data request unavailable; keeping existing playlist: %s", exc)
        raise RuntimeError("FPT Play data request failed; playlist was not replaced") from exc

    events = find_block_items(block_payload)

    LOGGER.info("Found %d FPT Play event items", len(events))
    print(f"FPT Play events found: {len(events)}")
    for event in events:
        print(f"- {event['title']} [{event['type']}/{event['id']}]")
    if not events:
        raise RuntimeError(
            "FPT Play Block Highlight returned no items; playlist was not replaced."
        )

    lines = ["#EXTM3U"]
    playlist_urls: set[str] = set()
    for event in events:
        path = STREAM_URL_TEMPLATE.format(
            stream_type=quote(event["type"], safe=""),
            highlight_id=quote(event["id"], safe=""),
        )
        try:
            stream_payload = api_request(
                session,
                "GET",
                path,
                user_token=user_token,
                label=f"FPT Play stream API for {event['id']}",
            )
        except (FptApiError, requests.RequestException, RuntimeError) as exc:
            LOGGER.warning("Skipping %s: %s", event["id"], exc)
            continue

        streams = find_streams(stream_payload)
        for stream in streams:
            stream_url = stream["url"]
            if not stream_url or stream_url in playlist_urls:
                continue
            playlist_urls.add(stream_url)
            title = clean_title(event["title"])
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
