from __future__ import annotations
from dataclasses import dataclass
import hashlib

from .contract import Diagnostic, Status
from .diagnostic_engine import DiagnosticEngine

@dataclass(frozen=True)
class PreflightResult:
    status: Status
    source_sha256: str
    diagnostics: tuple[Diagnostic, ...]
    reason: str

def preflight(
    engine: DiagnosticEngine,
    source: str,
    source_name: str,
    language: str | None = None,
    *,
    require_unknown_resolved: bool = True,
) -> PreflightResult:
    diagnostics = tuple(engine.analyze(source, source_name, language))
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if any(item.status in {Status.FAIL, Status.BLOCKED} or item.blocking for item in diagnostics):
        return PreflightResult(Status.FAIL, digest, diagnostics, "BLOCKING_DIAGNOSTIC")
    if any(item.status == Status.INCOMPLETE for item in diagnostics):
        return PreflightResult(Status.FAIL, digest, diagnostics, "AUTHORING_INCOMPLETE")
    if require_unknown_resolved and any(item.status == Status.UNKNOWN for item in diagnostics):
        return PreflightResult(
            Status.UNKNOWN,
            digest,
            diagnostics,
            "UNRESOLVED_FACT_OR_EXTERNAL_CHECK",
        )
    if any(item.status == Status.WARNING for item in diagnostics):
        return PreflightResult(
            Status.UNKNOWN,
            digest,
            diagnostics,
            "AUTHORING_WARNING_REQUIRES_RESOLUTION",
        )
    return PreflightResult(
        Status.PASS,
        digest,
        diagnostics,
        "AUTHORING_PREFLIGHT_PASS",
    )
