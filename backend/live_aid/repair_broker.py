from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from .contract import Diagnostic

@dataclass(frozen=True)
class RepairRequest:
    source_name: str
    source_sha256: str
    source: str
    diagnostics: tuple[dict, ...]
    fact_context: tuple[dict, ...]
    instruction: str

def build_repair_request(
    source: str,
    source_name: str,
    diagnostics: Iterable[Diagnostic],
    facts: Iterable[dict],
) -> RepairRequest:
    relevant = tuple(
        d.as_dict()
        for d in diagnostics
        if d.status.value in {"FAIL", "UNKNOWN", "WARNING", "BLOCKED"}
    )
    return RepairRequest(
        source_name=source_name,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        source=source,
        diagnostics=relevant,
        fact_context=tuple(facts),
        instruction=(
            "Repair only the supplied candidate source. Resolve each blocking finding "
            "against evidence. Do not invent paths, symbols, versions, commands or PASS. "
            "If evidence is insufficient, preserve UNKNOWN and request a forensic probe."
        ),
    )

def render_model_prompt(request: RepairRequest) -> str:
    return json.dumps({
        "role": "GG_LIVE_AID_REPAIR",
        "authority": "NO_ACTION_AUTHORITY",
        "source_name": request.source_name,
        "source_sha256": request.source_sha256,
        "diagnostics": list(request.diagnostics),
        "facts": list(request.fact_context),
        "instruction": request.instruction,
        "candidate_source": request.source,
    }, ensure_ascii=False, sort_keys=True)
