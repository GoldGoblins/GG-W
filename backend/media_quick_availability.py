"""Small file/HTTP availability checks, without playback or decoder processes.

A positive result means readable local media or reachable media responses. It
does not establish semantic programme identity, successful decoding, seeking or
permanent availability. Call from a bounded worker; reports never contain URLs.
"""
from __future__ import annotations

import math
from pathlib import Path
import time
from urllib.parse import unquote, urlsplit

from backend import media_availability as deep, media_contract as contract, media_library as library
from backend.media_request import public_headers

SCHEMA = "gg.media.quick-availability.v1"
MAX_SECONDS = 4.0
MAX_BYTES = 64 * 1024
LIVE_TTL_SECONDS = 900
VOD_TTL_SECONDS = 86400
_SCOPES = frozenset({"local_file", "http_media", "hls_media"})
SAMPLE_BYTES = 768


class _QuickBudget(deep._Budget):
    def fetch(self, source, **kwargs):
        result = super().fetch(source, **kwargs)
        if (kwargs.get("manifest") and result["data"].lstrip(b"\xef\xbb\xbf\r\n ").startswith(b"#EXTM3U")
                and not result["complete"]):
            raise deep._Unknown("playlist_too_large")
        return result


def _local_path(source):
    from backend.platform_support import local_file_path
    path = local_file_path(source)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ValueError("MEDIA_PATH_DENIED")
    return path


def check_quick_identity(row):
    """Check catalogue/source structure without a provider lookup or decoder."""
    source = str(row.get("source") or "")
    parsed = urlsplit(source)
    try:
        public_headers(row)
        if parsed.scheme in ("http", "https"):
            deep._url(source)
        elif parsed.scheme == "file" or "://" not in source:
            contract.confined(_local_path(source))
            return dict(status="consistent", scope="confined_local_file", decoded=False,
                        semantic_identity_verified=False)
        else:
            return dict(status="failed", scope="source", reason="unsupported_source", decoded=False)
    except (ValueError, deep._Unknown):
        return dict(status="failed", scope="source", reason="invalid_source", decoded=False)
    if not str(row.get("title") or "").strip():
        return dict(status="unknown", scope="link_identity", reason="missing_title", decoded=False)
    identifier = str(row.get("archive_id") or "")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    archive_host = (parsed.hostname or "").lower()
    archive_host = archive_host == "archive.org" or archive_host.endswith(".archive.org")
    if identifier:
        if not library._IDENTIFIER.fullmatch(identifier) or not archive_host:
            return dict(status="failed", scope="link_identity", reason="archive_source_mismatch", decoded=False)
        descriptor = len(parts) == 2 and parts[0] == "details"
        marker = 0 if parts and parts[0] == "download" else parts.index("items") if "items" in parts else -1
        if descriptor:
            if parts[1] != identifier:
                return dict(status="failed", scope="link_identity", reason="archive_source_mismatch", decoded=False)
            return dict(status="consistent", scope="archive_descriptor", decoded=False,
                        semantic_identity_verified=False)
        if marker < 0 or len(parts) <= marker + 2 or parts[marker + 1] != identifier:
            return dict(status="failed", scope="link_identity", reason="archive_source_mismatch", decoded=False)
        filename = str(row.get("archive_file") or "")
        if filename and "/".join(parts[marker + 2:]) != filename:
            return dict(status="failed", scope="link_identity", reason="archive_file_mismatch", decoded=False)
    return dict(status="consistent", scope="link_identity", decoded=False,
                semantic_identity_verified=False)


def prepare_quick_identity(row):
    candidate = dict(row)
    return candidate, check_quick_identity(candidate)


def _media_format(data):
    known = deep._format(data)
    if known:
        return known
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(b"FLV"):
        return "flv"
    if data.startswith(b"FORM") and data[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if data.startswith(b"#!AMR"):
        return "amr"
    if data.startswith(bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")):
        return "asf"
    if data.startswith(b"\x00\x00\x01\xb3"):
        return "mpeg"
    return ""


def _assert_media(response, *, encrypted=False):
    data = response["data"]
    if response["status"] not in (200, 206) or not data:
        raise deep._Failed("empty_media")
    head = data.lstrip().lower()
    content_type = response["content_type"]
    if content_type in ("text/html", "application/json", "application/problem+json") or head.startswith((b"<!doctype html", b"<html", b"{\"error\"")):
        raise deep._Failed("non_media_response")
    media_format = _media_format(data)
    if media_format or content_type.startswith(("audio/", "video/")):
        return media_format or "media_response"
    if encrypted and content_type in ("", "application/octet-stream", "binary/octet-stream"):
        return "encrypted_segment"
    raise deep._Unknown("unrecognized_media")


def _fetch(budget, source, *, count, manifest=False, start=0):
    try:
        return budget.fetch(source, start=start, count=count, manifest=manifest)
    except deep._Failed as error:
        # A handful of otherwise public streams reject byte ranges with403.
        # Retry once without Range, under the same byte/time/request budget.
        if str(error) == "access_denied" and not manifest and not start:
            return budget.fetch(source, count=count, ranged=False)
        raise


def _hls_media(source, budget, *, initial):
    # Parsing is bounded by this check's64KiB budget. Keys stay in the existing
    # RAM-only transport helper and no decoder is ever invoked.
    playlist = deep._playlist(source, budget, initial=initial)
    target, start, length, init, cipher = playlist["segment"]
    if cipher:
        deep._hls_key(cipher, budget)
    if init:
        initial_media = _fetch(budget, init[0], count=SAMPLE_BYTES, manifest=False)
        _assert_media(initial_media, encrypted=bool(init[2]))
    segment = _fetch(budget, target, start=start, count=min(SAMPLE_BYTES, length or SAMPLE_BYTES))
    media_format = _assert_media(segment, encrypted=bool(cipher))
    if playlist.get("audio_source"):
        audio = deep._playlist(playlist["audio_source"], budget)
        target, start, length, _, cipher = audio["segment"]
        if cipher:
            deep._hls_key(cipher, budget)
        _assert_media(_fetch(budget, target, start=start, count=min(SAMPLE_BYTES, length or SAMPLE_BYTES)), encrypted=bool(cipher))
    return dict(reachable=True, playlist=True, segment_available=True, format=media_format,
                encrypted=bool(playlist["segment"][4]))


def quick_check(row, *, cancel=None, max_seconds=MAX_SECONDS, max_bytes=MAX_BYTES):
    """Return bounded local/HTTP reachability evidence, never a decoded proof."""
    seconds = min(MAX_SECONDS, float(max_seconds))
    size = min(MAX_BYTES, int(max_bytes))
    if not math.isfinite(seconds) or seconds <= .35 or size <= 0:
        raise ValueError("MEDIA_QUICK_CHECK_BUDGET_INVALID")
    report = dict(schema=SCHEMA, status="unknown", scope="http_media", error="", evidence={"decoded": False})
    budget = _QuickBudget(cancel=cancel, max_seconds=seconds, max_bytes=size)
    source = str(row.get("source") or "")
    live = row.get("is_live") is True or row.get("media") == "stream" or row.get("kind") == "RADIO"
    try:
        budget.headers = public_headers(row)
        budget.check()
        parsed = urlsplit(source)
        if parsed.scheme == "file" or "://" not in source:
            report["scope"] = "local_file"
            path = _local_path(source)
            if path.suffix.lower() not in contract.AUDIO_EXT | contract.VIDEO_EXT:
                raise deep._Failed("unsupported_media_file")
            if not path.is_file():
                raise deep._Failed("local_not_found")
            with path.open("rb") as stream:
                if not stream.read(1):
                    raise deep._Failed("empty_media")
            budget.check()
            report["evidence"].update(reachable=True, readable=True, local_file=True)
        else:
            source = deep._url(source)
            playlist_url = urlsplit(source).path.casefold().endswith(".m3u8")
            response = _fetch(budget, source, count=min(32 * 1024 if playlist_url else SAMPLE_BYTES, size), manifest=playlist_url)
            hls = response["data"].lstrip(b"\xef\xbb\xbf\r\n ").startswith(b"#EXTM3U")
            if hls:
                report["scope"] = "hls_media"
                if not response["complete"]:
                    # Small unknown-extension initial reads must not parse a
                    # truncated playlist as if it contained its full segment.
                    response = _fetch(budget, response["source"], count=min(32 * 1024, size - budget.downloaded), manifest=True)
                report["evidence"].update(_hls_media(response["source"], budget, initial=response))
            else:
                report["evidence"].update(reachable=True, format=_assert_media(response))
            report["evidence"].update(http_response=response["status"], transport=report["scope"])
        report["status"] = "verified"
    except deep._Failed as error:
        report.update(status="failed", error=str(error))
    except deep._Unknown as error:
        report["error"] = str(error)
    except (ValueError, TypeError):
        report["error"] = "invalid_source"
    except (OSError, TimeoutError):
        report["error"] = "network_error" if "://" in source and not source.startswith("file:") else "local_unreadable"
    ttl = (LIVE_TTL_SECONDS if live else VOD_TTL_SECONDS) if report["status"] == "verified" else 0
    checked = time.time()
    report.update(checked_at=checked, expires_at=checked + ttl, ttl_seconds=ttl,
        elapsed_seconds=round(time.monotonic() - budget.started, 3), downloaded_bytes=budget.downloaded,
        requests=budget.requests, max_seconds=seconds, max_bytes=size)
    return report


def is_fresh_available(report):
    if (not report or report.get("schema") != SCHEMA or report.get("status") != "verified"
            or report.get("scope") not in _SCOPES or (report.get("evidence") or {}).get("reachable") is not True):
        return False
    try:
        checked, expiry, now = float(report["checked_at"]), float(report["expires_at"]), time.time()
        return math.isfinite(checked) and math.isfinite(expiry) and checked <= now < expiry
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
