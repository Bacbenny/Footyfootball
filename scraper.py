#!/usr/bin/env python3
"""Generate an M3U playlist for the FPT Play "Sự Kiện FPT" group."""

from __future__ import annotations

import base64
import hashlib
import html
import importlib
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE_URL = "https://api.fptplay.net"
API_VERSION = os.environ.get("FPT_API_VERSION", "v7.1_w")
APP_VERSION = os.environ.get("FPT_APP_VERSION", "8.8.23")
SIGNATURE_SECRET = "6ea6d2a4e2d3a4bd5e275401aa086d"
CURL_IMPERSONATE = "chrome120"
FPT_DEVICE = os.environ.get(
    "FPT_DEVICE", "Microsoft Edge Simulate(version:127.0.6533.144)"
)
FPT_EVENT_RELATED_DEVICE = os.environ.get(
    "FPT_EVENT_RELATED_DEVICE",
    "Microsoft Edge Simulate(version%3A127.0.6533.144)",
)
VN_PROXY = os.environ.get("VN_PROXY")
ACTIVE_PROXY_URL: str | None = None
STREAM_URL_TEMPLATE = os.environ.get(
    "FPT_STREAM_URL_TEMPLATE",
    "/stream/{stream_type}/{highlight_id}/adaptive_bitrate",
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
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}
PLAYLIST_HEADERS = f"|User-Agent={USER_AGENT}&Referer=https://fptplay.vn/"
ALLOWED_TYPES = {"tv", "vod", "event", "live"}
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
PLAYBACK_ID_KEYS = (
    "stream_id",
    "streamId",
    "playback_id",
    "playbackId",
    "channel_id",
    "channelId",
    "tv_id",
    "tvId",
    "media_id",
    "mediaId",
    "stream_code",
    "streamCode",
)
PLAYBACK_TYPE_KEYS = (
    "stream_type",
    "streamType",
    "playback_type",
    "playbackType",
    "channel_type",
    "channelType",
)
BLOCK_ID_KEYS = ("block_id", "blockId", "_id", "id")
TYPE_KEYS = (
    "stream_type",
    "streamType",
    "type",
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
            "device": FPT_DEVICE,
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
    proxy = ACTIVE_PROXY_URL or VN_PROXY or os.environ.get("VN_PROXY")
    if not proxy:
        return {}
    return {"proxies": {"http": proxy, "https": proxy}}


def configured_proxy_urls() -> list[str | None]:
    """Return HTTP first, then SOCKS5, preserving proxy credentials."""
    raw_proxy = VN_PROXY or os.environ.get("VN_PROXY")
    if not raw_proxy:
        return [None]
    raw_proxy = raw_proxy.strip()
    if "://" not in raw_proxy:
        parts = raw_proxy.split(":")
        if len(parts) == 4 and parts[1].isdigit():
            host, port, username, password = parts
            raw_proxy = (
                f"http://{quote(username, safe='')}:{quote(password, safe='')}"
                f"@{host}:{port}"
            )
        else:
            raw_proxy = f"http://{raw_proxy}"
    parsed = urlparse(raw_proxy)
    http_url = urlunparse(parsed._replace(scheme="http"))
    socks_url = urlunparse(parsed._replace(scheme="socks5"))
    return list(dict.fromkeys((http_url, socks_url)))


def request_options_for(proxy_url: str | None) -> dict[str, Any]:
    """Build request options for the selected proxy candidate."""
    if not proxy_url:
        return {}
    return {"proxies": {"http": proxy_url, "https": proxy_url}}


def ensure_socks_support() -> None:
    """Install PySocks on demand for requests' SOCKS5 transport."""
    try:
        importlib.import_module("socks")
        return
    except ImportError:
        pass

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "PySocks",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Could not install PySocks for SOCKS5 fallback")
    try:
        importlib.import_module("socks")
    except ImportError as exc:
        raise RuntimeError("PySocks installation completed but import still failed") from exc


def curl_requests_module() -> Any:
    """Load curl_cffi.requests, installing curl_cffi if this runner lacks it."""
    try:
        return importlib.import_module("curl_cffi.requests")
    except ImportError:
        pass

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "curl_cffi",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Could not install curl_cffi for Chrome impersonation")
    try:
        return importlib.import_module("curl_cffi.requests")
    except ImportError as exc:
        raise RuntimeError("curl_cffi installation completed but import still failed") from exc


def build_block_highlight_url() -> str:
    """Build the current signed Block Highlight URL."""
    path = "/navigation/block/highlight/632f01322089bd00e5c5ed3d"
    params = build_signed_params(
        path,
        {
            "block_type": "horizontal_slider",
            "custom_data": "",
            "page": 1,
            "page_size": 31,
            "page_id": "sport",
        },
    )
    return f"{API_BASE_URL}/api/{API_VERSION}{path}?{urlencode(params)}"


def block_highlight_request(session: requests.Session) -> Any:
    """Fetch the sports Block Highlight using the current signed endpoint."""
    path = "/navigation/block/highlight/632f01322089bd00e5c5ed3d"
    params = {
        "block_type": "horizontal_slider",
        "custom_data": "",
        "page": 1,
        "page_size": 31,
        "page_id": "sport",
    }
    return signed_block_request(path, params, "FPT Play Block Highlight API")


def event_related_request(session: requests.Session, event_id: str) -> Any:
    """Fetch related items for one event to resolve its actual playback target."""
    path = f"/navigation/block/event_related/{quote(event_id, safe='')}"
    params = {
        "block_type": "horizontal_list",
        "custom_data": "",
        "page": 1,
        "page_size": 31,
        "page_id": "",
    }
    return signed_block_request(
        path,
        params,
        "FPT Play event-related API",
        device=FPT_EVENT_RELATED_DEVICE,
    )


def signed_block_request(
    path: str,
    params: Mapping[str, Any],
    label: str,
    *,
    device: str | None = None,
) -> Any:
    """Fetch a signed FPT navigation block with browser-like TLS."""
    headers = dict(REQUEST_HEADERS)
    headers["X-Did"] = os.environ.get("FPT_DEVICE_ID", "github-actions-footyfootball")
    signed_params = build_signed_params(path, params)
    if device:
        signed_params["device"] = device
    url = f"{API_BASE_URL}/api/{API_VERSION}{path}?{urlencode(signed_params)}"
    try:
        curl_requests = curl_requests_module()
        response = curl_requests.get(
            url,
            headers=headers,
            impersonate=CURL_IMPERSONATE,
            **request_options(),
            timeout=30,
        )
    except Exception as exc:
        raise RuntimeError(f"{label} request failed") from exc
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


def find_playback_target(
    record: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Find an explicit stream/channel target without confusing it with the event ID."""
    for mapping in walk_dicts(record):
        playback_id = first_text(mapping, PLAYBACK_ID_KEYS)
        if not playback_id:
            continue

        playback_type = first_text(mapping, PLAYBACK_TYPE_KEYS)
        if not playback_type and any(
            mapping.get(key) is not None
            for key in ("channel_id", "channelId", "tv_id", "tvId")
        ):
            playback_type = "tv"
        if not playback_type and re.fullmatch(r"event-\d+", playback_id, re.IGNORECASE):
            playback_type = "tv"
        playback_type = (playback_type or first_text(mapping, TYPE_KEYS) or "event").lower()
        if playback_type in ALLOWED_TYPES:
            return playback_type, playback_id

    # Some responses nest a typed playback target as {type: "tv", id: "..."}.
    for mapping in walk_dicts(record):
        playback_type = first_text(mapping, TYPE_KEYS)
        playback_id = first_text(mapping, HIGHLIGHT_ID_KEYS)
        if playback_type and playback_id and playback_type.lower() in {"tv", "live", "vod"}:
            return playback_type.lower(), playback_id
        if (
            playback_type
            and playback_type.lower() == "event"
            and playback_id
            and re.fullmatch(r"event-\d+", playback_id, re.IGNORECASE)
        ):
            return "tv", playback_id
    return None


def find_highlights(payload: Any) -> list[dict[str, Any]]:
    """Normalize event records while retaining any separate playback target."""
    if isinstance(payload, Mapping):
        data = payload.get("data")
        items = data.get("items") if isinstance(data, Mapping) else None
        records = items if isinstance(items, list) else list(walk_dicts(payload))
    elif isinstance(payload, list):
        records = payload
    else:
        records = []

    highlights: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue

        event_id = first_text(record, HIGHLIGHT_ID_KEYS)
        event_type = first_text(record, TYPE_KEYS) or "event"
        title = first_text(record, TITLE_KEYS)
        if not event_id:
            for nested in walk_dicts(record):
                event_id = first_text(nested, HIGHLIGHT_ID_KEYS)
                if event_id:
                    event_type = first_text(nested, TYPE_KEYS) or event_type
                    title = title or first_text(nested, TITLE_KEYS)
                    break
        if not event_id:
            continue

        target = find_playback_target(record)
        if target:
            stream_type, stream_id = target
        else:
            stream_type, stream_id = event_type.lower(), None
        if stream_type not in ALLOWED_TYPES:
            continue

        identity = (event_type.lower(), event_id)
        if identity in seen:
            continue
        seen.add(identity)
        title = title or f"FPT {event_type} {event_id}"
        highlights.append(
            {
                "id": event_id,
                "type": stream_type,
                "title": title,
                "stream_id": stream_id,
            }
        )
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


def find_block_items(payload: Any) -> list[dict[str, Any]]:
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


def find_related_playback_target(
    event: Mapping[str, Any],
    related_payload: Any,
) -> Mapping[str, Any] | None:
    """Choose a related stream target that matches the event, avoiding random recommendations."""
    candidates = [
        item
        for item in find_block_items(related_payload)
        if item.get("stream_id")
    ]
    if not candidates:
        return None

    event_id = str(event.get("id", ""))
    matching_id = [item for item in candidates if item.get("id") == event_id]
    if len(matching_id) == 1:
        return matching_id[0]

    event_title = clean_title(str(event.get("title", ""))).casefold()
    matching_title = [
        item
        for item in candidates
        if clean_title(str(item.get("title", ""))).casefold() == event_title
    ]
    if len(matching_title) == 1:
        return matching_title[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


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
        block_payload = block_highlight_request(session)
    except (FptApiError, requests.RequestException, RuntimeError) as exc:
        LOGGER.warning("FPT Play data request unavailable; keeping existing playlist: %s", exc)
        raise RuntimeError("FPT Play data request failed; playlist was not replaced") from exc

    events = find_block_items(block_payload)

    LOGGER.info("Found %d FPT Play event items", len(events))
    print(f"FPT Play events found: {len(events)}")
    for event in events:
        target_label = (
            f"{event['type']}/{event['stream_id']}"
            if event["stream_id"]
            else "playback target pending"
        )
        print(
            f"- {event['title']} [{event['id']} -> "
            f"{target_label}]"
        )
    if not events:
        raise RuntimeError(
            "FPT Play Block Highlight returned no items; playlist was not replaced."
        )

    lines = ["#EXTM3U"]
    playlist_urls: set[str] = set()
    for event in events:
        stream_type = event["type"]
        stream_id = event["stream_id"]
        if not stream_id:
            try:
                related_payload = event_related_request(session, event["id"])
            except (FptApiError, requests.RequestException, RuntimeError) as exc:
                LOGGER.warning("Could not resolve target for %s: %s", event["id"], exc)
                continue
            related_target = find_related_playback_target(event, related_payload)
            if not related_target:
                LOGGER.info("No related playback target found for %s; skipping", event["id"])
                continue
            stream_type = str(related_target["type"])
            stream_id = str(related_target["stream_id"])

        path = STREAM_URL_TEMPLATE.format(
            stream_type=quote(stream_type, safe=""),
            highlight_id=quote(stream_id, safe=""),
            stream_id=quote(stream_id, safe=""),
        )
        stream_params = {
            "data_type": "highlight",
            "enable_preview": 0,
            "stream_profile": 1,
        }
        try:
            stream_payload = api_request(
                session,
                "GET",
                path,
                user_token=user_token,
                params=stream_params,
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
        LOGGER.warning("FPT_USE_USER_TOKEN is enabled but USER_TOKEN is not set; falling back to anonymous mode")
        use_user_token = False

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
