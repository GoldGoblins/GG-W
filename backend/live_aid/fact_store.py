from __future__ import annotations

import json
import os
from pathlib import Path

from .contract import Fact, canonical_json

class FactStoreError(RuntimeError):
    pass

class FactStore:
    """Append-only content-addressed fact store.

    The store never silently replaces an older claim.  Current selection is a
    retrieval operation over explicit provenance, not last-writer-wins.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.index = self.root / "index.jsonl"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.objects.mkdir(exist_ok=True, mode=0o700)
        if not self.index.exists():
            fd = os.open(self.index, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)

    def append(self, fact: Fact) -> str:
        self.initialize()
        payload = (canonical_json(fact.as_dict()) + "\n").encode("utf-8")
        fact_id = fact.fact_id
        object_path = self.objects / (fact_id + ".json")
        if object_path.exists():
            if object_path.read_bytes() != payload:
                raise FactStoreError("FACT_ID_COLLISION")
        else:
            fd = os.open(object_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        line = canonical_json({"fact_id": fact_id, "key": fact.key}) + "\n"
        existing = self._index_rows()
        if not any(row["fact_id"] == fact_id for row in existing):
            with self.index.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return fact_id

    def _index_rows(self) -> list[dict[str, str]]:
        if not self.index.exists():
            return []
        rows = []
        for raw in self.index.read_text(encoding="utf-8").splitlines():
            if raw:
                rows.append(json.loads(raw))
        return rows

    def get(self, fact_id: str) -> Fact:
        path = self.objects / (fact_id + ".json")
        if not path.is_file() or path.is_symlink():
            raise FactStoreError("FACT_NOT_FOUND")
        value = json.loads(path.read_text(encoding="utf-8"))
        return Fact(
            key=value["key"],
            value=value["value"],
            epistemic_class=value["epistemic_class"],
            source_kind=value["source_kind"],
            source_id=value["source_id"],
            source_sha256=value["source_sha256"],
            scope=value["scope"],
            freshness=value.get("freshness", "CONTENT_BOUND"),
            supersedes=tuple(value.get("supersedes", [])),
        )

    def find(self, key: str) -> list[Fact]:
        return [self.get(row["fact_id"]) for row in self._index_rows() if row["key"] == key]

    def current_candidates(self, key: str) -> list[Fact]:
        facts = self.find(key)
        superseded = {item for fact in facts for item in fact.supersedes}
        return [fact for fact in facts if fact.fact_id not in superseded]
