"""Bounded public-read idle fetch. Not a standing grant and not a second brain.

Same 45s host timer as catalog idle-learn. One allowlisted GET per tick,
compact lesson only. No credentials, no mainnet, no crawl of the open web.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from backend import long_memory


SCHEMA = "gg.idle-frontier.v1"
ACTION_AUTHORITY = "NONE"
PROMOTION_AUTHORITY = "NONE"
PARALLEL_AGENT_BRAIN = "FORBIDDEN"
NETWORK = "PUBLIC_READ_ALLOWLIST"
MAX_BYTES = 48_000
TIMEOUT_S = 8.0
FETCHES_PER_TICK = 1
CONSOLIDATE_EVERY = 8
CURSOR_NAME = "idle-frontier-cursor.json"
USER_AGENT = "GG-IdleFrontier/1.0"

ALLOWED_HOSTS = frozenset(
    {
        "raw.githubusercontent.com",
        "docs.kaspa.org",
        "arxiv.org",
        "research.google",
        "kaspanet.github.io",
    }
)

FEEDS = (
    {
        "url": "https://docs.kaspa.org/toccata/agent-brief",
        "query": "kaspa toccata agent brief",
        "tags": ("kaspa", "covenant", "toccata"),
    },
    {
        "url": "https://raw.githubusercontent.com/kaspanet/silverscript/master/README.md",
        "query": "silverscript compiler readme",
        "tags": ("silverscript", "kaspa", "silverc"),
    },
    {
        "url": "https://arxiv.org/abs/2504.19874",
        "query": "turboquant online vector quantization",
        "tags": ("turboquant", "quantization", "memory"),
    },
    {
        "url": "https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/",
        "query": "google turboquant compression blog",
        "tags": ("turboquant", "kv", "compression"),
    },
    {
        "url": "https://raw.githubusercontent.com/RyanCodrai/turbovec/main/README.md",
        "query": "turbovec vector index readme",
        "tags": ("turbovec", "ann", "index"),
    },
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _root(tree_root=None):
    return long_memory._root(tree_root)


def _cursor_path(root):
    return root / CURSOR_NAME


def _load_cursor(root) -> dict[str, Any]:
    path = _cursor_path(root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_cursor(root, payload: dict[str, Any]) -> None:
    path = _cursor_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _working_tokens(root) -> set[str]:
    path = root / long_memory.WORKING_NAME
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8").lower()
    except OSError:
        return set()
    return set(re.findall(r"[a-z]{4,}", text))


def _pick_feed(cursor: dict[str, Any], tokens: set[str]) -> dict[str, str]:
    seen = set(cursor.get("seen") or [])
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, feed in enumerate(FEEDS):
        url = str(feed["url"])
        if url in seen:
            continue
        score = sum(1 for tag in feed["tags"] if tag in tokens)
        ranked.append((score, -index, feed))
    if ranked:
        ranked.sort(reverse=True)
        return ranked[0][2]
    # wrap
    index = int(cursor.get("index") or 0) % len(FEEDS)
    return FEEDS[index]


def _allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host in ALLOWED_HOSTS and urlparse(url).scheme == "https"


def _plain(body: bytes, content_type: str) -> str:
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or text.lstrip()[:15].lower().startswith("<!doctype html") or text.lstrip()[:6].lower().startswith("<html"):
        parser = _TextExtractor()
        try:
            parser.feed(text)
        except Exception:
            return " ".join(text.split())[:1200]
        return " ".join(parser.parts)[:1200]
    return " ".join(text.split())[:1200]


def fetch_url(url: str) -> str:
    if not _allowed(url):
        raise ValueError("FRONTIER_HOST")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        raw = response.read(MAX_BYTES + 1)
        content_type = str(response.headers.get("Content-Type") or "")
    if len(raw) > MAX_BYTES:
        raw = raw[:MAX_BYTES]
    return _plain(raw, content_type)


def status(*, tree_root=None) -> dict[str, Any]:
    root = _root(tree_root)
    cursor = _load_cursor(root)
    return {
        "schema": SCHEMA,
        "status": "READY",
        "feeds": len(FEEDS),
        "seen": len(cursor.get("seen") or []),
        "ticks": int(cursor.get("ticks") or 0),
        "network": NETWORK,
        "action_authority": ACTION_AUTHORITY,
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "canonical_policy_change": False,
    }


def tick(*, tree_root=None) -> dict[str, Any]:
    root = _root(tree_root)
    cursor = _load_cursor(root)
    ticks = int(cursor.get("ticks") or 0)
    seen = [str(item) for item in (cursor.get("seen") or []) if isinstance(item, str)]
    feed = _pick_feed(cursor, _working_tokens(root))
    url = str(feed["url"])
    learned = 0
    note = ""
    try:
        body = fetch_url(url)
        note = long_memory._compact(str(feed["query"]) + " · " + body, long_memory.MAX_NOTE)
        recorded = long_memory.capture(
            str(feed["query"]),
            motor="SHARED",
            kind="semantic",
            note=note,
            tree_root=root,
            force=True,
        )
        if recorded.get("status") == "RECORDED":
            learned = 1
    except (ValueError, OSError, TimeoutError, urllib.error.URLError, UnicodeError):
        note = ""
    if url not in seen:
        seen.append(url)
    ticks += 1
    index = int(cursor.get("index") or 0) + 1
    _write_cursor(
        root,
        {
            "schema": SCHEMA,
            "index": index,
            "seen": seen[-32:],
            "ticks": ticks,
            "last": url,
        },
    )
    consolidated = False
    if ticks % CONSOLIDATE_EVERY == 0 and learned:
        long_memory.consolidate(tree_root=root)
        consolidated = True
    return {
        "schema": SCHEMA,
        "status": "LEARNED" if learned else "IDLE",
        "learned": learned,
        "url": url,
        "ticks": ticks,
        "consolidated": consolidated,
        "network": NETWORK,
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": False,
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "model_inference": False,
        "fetches_per_tick": FETCHES_PER_TICK,
    }
