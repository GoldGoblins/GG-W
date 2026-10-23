#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import idle_frontier, long_memory


def main() -> int:
    if idle_frontier.FETCHES_PER_TICK != 1:
        raise AssertionError("frontier must stay one GET per tick")
    if idle_frontier.PARALLEL_AGENT_BRAIN != "FORBIDDEN":
        raise AssertionError("second brain leaked into frontier")
    if idle_frontier.ACTION_AUTHORITY != "NONE":
        raise AssertionError("frontier must not grant authority")
    for feed in idle_frontier.FEEDS:
        host = (urlparse(str(feed["url"])).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host not in idle_frontier.ALLOWED_HOSTS:
            raise AssertionError("feed host not allowlisted: " + host)
        if str(feed["url"]).startswith("http://"):
            raise AssertionError("cleartext feed")

    try:
        idle_frontier.fetch_url("https://example.invalid/nope")
        raise AssertionError("arbitrary host accepted")
    except ValueError:
        pass

    tmp = Path(tempfile.mkdtemp(prefix="gg-frontier-"))
    (tmp / "WORKING.md").write_text(
        "# GG long memory\n- [semantic] kaspa silverscript covenant\n",
        encoding="utf-8",
    )
    feed = idle_frontier._pick_feed({}, {"kaspa", "covenant", "silverscript"})
    if "kaspa" not in " ".join(feed["tags"]) and "silverscript" not in " ".join(
        feed["tags"]
    ):
        raise AssertionError("seed did not prefer current attention")

    calls = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return "Kaspa agent brief: validate the next output, not only the old input."

    idle_frontier.fetch_url = fake_fetch  # type: ignore[method-assign]
    first = idle_frontier.tick(tree_root=tmp)
    if first["learned"] != 1:
        raise AssertionError("tick did not record a lesson")
    if len(calls) != 1:
        raise AssertionError("tick fetched more than once")
    hits = long_memory.recall("kaspa toccata agent brief", tree_root=tmp)
    if not hits:
        raise AssertionError("frontier lesson missing from recall")

    host_src = (PROJECT / "backend" / "chat_surface_host.py").read_text(
        encoding="utf-8"
    )
    if "idle_frontier" not in host_src:
        raise AssertionError("host timer does not tick frontier")
    print("test_idle_frontier: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
