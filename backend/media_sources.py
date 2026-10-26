"""Bounded official IPTV.org source import, independent of MEDIA browsing.

The API exposes more alternative sources than its default M3U playlist.
Imported rows are candidates, never playback proofs. Existing canonical
titles and checked direct sources survive metadata rediscovery. Invoke
``refresh`` from a worker or use the explicit command-line import.
"""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit
import urllib.request

from backend import media_contract as contract, media_library as library
from backend.media_index import MediaIndex
from backend.media_request import public_headers

SCHEMA = "gg.media.sources.v1"
API_ROOT = "https://iptv-org.github.io/api/"
ENDPOINTS = {
    "streams": (API_ROOT + "streams.json", 16 * 1024 * 1024),
    "channels": (API_ROOT + "channels.json", 24 * 1024 * 1024),
    "feeds": (API_ROOT + "feeds.json", 24 * 1024 * 1024),
}
BATCH_SIZE = 200
MAX_SECONDS = 60
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,219}$")


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def __init__(self, source):
        self.source = source

    def redirect_request(self, request, response, code, message, headers, newurl):
        if urljoin(request.full_url, newurl) != self.source:
            raise ValueError("unexpected_api_source")
        return super().redirect_request(request, response, code, message, headers, newurl)


def _cancelled(cancel):
    return bool(cancel and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()))


def _url(value, *, limit=6000):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_source")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password):
        raise ValueError("invalid_source")
    return value


def _public_header(value, *, referrer=False):
    if value in (None, ""):
        return ""
    if (not isinstance(value, str) or len(value) > (2048 if referrer else 512)
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("invalid_public_header")
    return _url(value) if referrer else value.strip()


def _fetch_json(endpoint, *, deadline, cancel=None):
    """Read one fixed official endpoint with a shared finite time/byte budget."""
    source, maximum = ENDPOINTS[endpoint]
    request = urllib.request.Request(source, headers={
        "User-Agent": "GG-AI-Desktop-Media-Sources/1.0", "Accept": "application/json",
        "Accept-Encoding": "identity"}, method="GET")
    if _cancelled(cancel) or time.monotonic() >= deadline:
        raise TimeoutError("source_import_stopped")
    opener = urllib.request.build_opener(_OfficialRedirect(source))
    with opener.open(request, timeout=max(.1, min(12, deadline - time.monotonic()))) as response:
        # These static metadata requests never follow a redirect to an unrelated
        # service, credential endpoint or another origin's response body.
        final = urlsplit(response.geturl())
        if final.scheme != "https" or final.netloc != "iptv-org.github.io" or final.path != "/api/" + endpoint + ".json":
            raise ValueError("unexpected_api_source")
        blocks, size = [], 0
        read = getattr(response, "read1", response.read)
        while True:
            if _cancelled(cancel) or time.monotonic() >= deadline:
                raise TimeoutError("source_import_stopped")
            socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if socket is not None:
                socket.settimeout(max(.1, min(4, deadline - time.monotonic())))
            chunk = read(min(64 * 1024, maximum + 1 - size))
            if not chunk:
                break
            blocks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise ValueError("api_response_too_large")
        payload = json.loads(b"".join(blocks).decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("invalid_api_payload")
    return payload


def _candidate(stream, channels, feeds, main_feeds):
    if not isinstance(stream, dict):
        raise ValueError("invalid_stream")
    source = _url(stream.get("url"))
    base_channel = str(stream.get("channel") or "")
    feed = str(stream.get("feed") or "")
    if (base_channel and not _ID.fullmatch(base_channel)) or (feed and not _ID.fullmatch(feed)):
        raise ValueError("invalid_channel")
    channel = channels.get(base_channel) or {}
    feed_metadata = feeds.get((base_channel, feed)) if feed else main_feeds.get(base_channel)
    feed_metadata = feed_metadata or {}
    title = library._text(stream.get("title") or channel.get("name"), 180)
    if not title:
        raise ValueError("missing_title")
    referrer = _public_header(stream.get("referrer"), referrer=True)
    user_agent = _public_header(stream.get("user_agent"))
    public_headers(dict(referrer=referrer, user_agent=user_agent))
    channel_id = base_channel + ("@" + feed if base_channel and feed else "")
    categories = channel.get("categories")
    category = "; ".join(library._text(value, 50) for value in categories[:8]) if isinstance(categories, list) else ""
    labels = stream.get("labels")
    row = dict(
        id=contract.item_id("TV", source), kind="TV", content_type="live", title=title,
        source=source, media="stream", play="video", player="qml", is_live=True,
        channel_id=channel_id, base_channel_id=base_channel, feed=feed,
        category=category or "Live", country=library._text(channel.get("country"), 8),
        language=library._language(feed_metadata.get("languages")),
        provider="IPTV.org", source_label="IPTV.org API", source_page="https://github.com/iptv-org/api",
        quality=library._text(stream.get("quality"), 24),
        source_labels=[library._text(label, 60) for label in labels[:8]] if isinstance(labels, list) else [],
        availability="metadata", playable=False,
    )
    if referrer:
        row["referrer"] = referrer
    if user_agent:
        row["user_agent"] = user_agent
    return library.annotate(row)


def refresh(index: MediaIndex, *, cancel=None, metadata=True):
    """Import a finite official source snapshot in batches of at most 200 rows.

    Optional channel/feed failure leaves the stream's own correct title and
    explicit request headers usable. No source probe or media download occurs.
    Calling again is idempotent for unchanged rows and fills new alternatives.
    """
    started = time.monotonic()
    deadline = started + MAX_SECONDS
    result = dict(schema=SCHEMA, provider="IPTV.org", api_calls=0, candidate_sources=0,
                  new_sources=0, rejected_streams=0, duplicate_urls=0,
                  metadata_warnings=[], cancelled=False, error="", verified_by_import=0)
    if _cancelled(cancel):
        return dict(result, cancelled=True)
    result["api_calls"] += 1
    try:
        streams = _fetch_json("streams", deadline=deadline, cancel=cancel)
    except (OSError, ValueError, TimeoutError, http.client.HTTPException):
        return dict(result, cancelled=_cancelled(cancel), error="source_api_unavailable")
    channels, feeds, main_feeds = {}, {}, {}
    if metadata:
        for endpoint in ("channels", "feeds"):
            if _cancelled(cancel) or time.monotonic() >= deadline:
                break
            result["api_calls"] += 1
            try:
                entries = _fetch_json(endpoint, deadline=deadline, cancel=cancel)
            except (OSError, ValueError, TimeoutError, http.client.HTTPException):
                result["metadata_warnings"].append(endpoint + "_unavailable")
                continue
            if endpoint == "channels":
                channels = {entry["id"]: entry for entry in entries if isinstance(entry, dict)
                            and isinstance(entry.get("id"), str) and _ID.fullmatch(entry["id"])}
            else:
                for entry in entries:
                    if not isinstance(entry, dict) or not entry.get("channel") or not entry.get("id"):
                        continue
                    feeds[(str(entry["channel"]), str(entry["id"]))] = entry
                    if entry.get("is_main"):
                        main_feeds[str(entry["channel"])] = entry
    if _cancelled(cancel):
        return dict(result, cancelled=True)
    # Reading IDs alone is bounded to the actual source snapshot, not the
    # complete video index; source bodies never enter a GUI model.
    seen, batch = set(), []

    def publish():
        if not batch:
            return
        with index.connection() as db:
            placeholders = ",".join("?" for _ in batch)
            existing = db.execute("SELECT COUNT(*) FROM items WHERE id IN (" + placeholders + ")",
                                  [row["id"] for row in batch]).fetchone()[0]
        rows = index.ingest_discovered(batch)
        result["candidate_sources"] += len(rows)
        result["new_sources"] += max(0, len(rows) - existing)
        batch.clear()

    for stream in streams:
        if _cancelled(cancel):
            result["cancelled"] = True
            break
        try:
            row = _candidate(stream, channels, feeds, main_feeds)
        except (ValueError, TypeError):
            result["rejected_streams"] += 1
            continue
        if row["source"] in seen:
            result["duplicate_urls"] += 1
            continue
        seen.add(row["source"])
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            publish()
    if not result["cancelled"]:
        publish()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("import",))
    parser.add_argument("--index", type=Path)
    parser.add_argument("--streams-only", action="store_true")
    args = parser.parse_args(argv)
    index = MediaIndex(args.index)
    index.initialize()
    print(json.dumps(refresh(index, metadata=not args.streams_only), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
