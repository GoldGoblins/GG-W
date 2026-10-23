from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
import hashlib
import json
from typing import Any

SCHEMA_DIAGNOSTIC = "gg.live-aid.diagnostic.v1"
SCHEMA_FACT = "gg.live-aid.fact.v1"
SCHEMA_SNAPSHOT = "gg.live-aid.authoring-snapshot.v1"

class Status(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"

BLOCKING_STATUSES = frozenset({Status.FAIL, Status.BLOCKED})

def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class EvidenceRef:
    source_kind: str
    source_id: str
    source_sha256: str
    epistemic_class: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

@dataclass(frozen=True)
class Diagnostic:
    status: Status
    code: str
    message: str
    source: str
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    suggestion: str | None = None
    blocking: bool = False
    evidence: tuple[EvidenceRef, ...] = ()
    probe: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema"] = SCHEMA_DIAGNOSTIC
        value["status"] = self.status.value
        value["evidence"] = [item.as_dict() for item in self.evidence]
        return value

    @property
    def diagnostic_id(self) -> str:
        return "diag-" + digest_json(self.as_dict())[:24]

@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    epistemic_class: str
    source_kind: str
    source_id: str
    source_sha256: str
    scope: str
    freshness: str = "CONTENT_BOUND"
    supersedes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema"] = SCHEMA_FACT
        value["supersedes"] = list(self.supersedes)
        return value

    @property
    def fact_id(self) -> str:
        return "fact-" + digest_json(self.as_dict())
