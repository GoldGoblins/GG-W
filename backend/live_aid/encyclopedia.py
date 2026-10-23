from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import Fact
from .fact_store import FactStore

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def seed_snapshot_encyclopedia(
    store: FactStore,
    *,
    source_index_path: Path,
    runtime_tools_path: Path,
    base_head: str,
) -> list[str]:
    """Seed content-bound facts from the uploaded/current discovery snapshot.

    This is not a canonical-policy promotion.  Every fact remains bound to the
    report bytes and BASE_HEAD that produced it.
    """
    source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_tools_path.read_text(encoding="utf-8"))
    source_sha = _sha(source_index_path)
    runtime_sha = _sha(runtime_tools_path)
    ids: list[str] = []

    for entry in source_index.get("python", []):
        rel = entry.get("path")
        if not isinstance(rel, str):
            continue
        for symbol in entry.get("symbols", []):
            name = symbol.get("name")
            if not isinstance(name, str):
                continue
            ids.append(store.append(Fact(
                key="source.symbol." + name,
                value={"base_head": base_head, "path": rel, "symbol": symbol},
                epistemic_class="OBSERVED_CONTENT_BOUND",
                source_kind="SNAPSHOT_SOURCE_INDEX",
                source_id=str(source_index_path),
                source_sha256=source_sha,
                scope="REPOSITORY_SOURCE@" + base_head,
            )))

    for tool, record in sorted(runtime.items()):
        if not isinstance(record, dict):
            continue
        ids.append(store.append(Fact(
            key="runtime.tool." + tool,
            value={"base_head": base_head, "record": record},
            epistemic_class="OBSERVED_CAPTURE_TIME",
            source_kind="SNAPSHOT_RUNTIME_REPORT",
            source_id=str(runtime_tools_path),
            source_sha256=runtime_sha,
            scope="HOST_RUNTIME_CAPTURE",
            freshness="REFRESH_BEFORE_DECISION_CRITICAL_USE",
        )))
    return ids
