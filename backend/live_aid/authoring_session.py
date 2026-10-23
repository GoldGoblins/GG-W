from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .contract import Diagnostic, Status
from .diagnostic_engine import DiagnosticEngine
from .fact_store import FactStore
from .forensic_resolver import ForensicResolver, ProbeRequest

@dataclass(frozen=True)
class AuthoringSnapshot:
    sequence: int
    source_name: str
    source_sha256: str
    status: Status
    diagnostics: tuple[Diagnostic, ...]
    new_fact_ids: tuple[str, ...]
    probes: tuple[ProbeRequest, ...]

class AuthoringSession:
    """Continuous analysis loop for an editor/model candidate buffer.

    update() is non-blocking authoring feedback.  The caller decides when a
    completed block advances to preflight and controlled execution.
    """

    def __init__(
        self,
        *,
        source_name: str,
        engine: DiagnosticEngine,
        resolver: ForensicResolver | None = None,
        facts: FactStore | None = None,
    ):
        self.source_name = source_name
        self.engine = engine
        self.resolver = resolver
        self.facts = facts
        self.sequence = 0

    def update(self, source: str, language: str | None = None) -> AuthoringSnapshot:
        self.sequence += 1
        diagnostics = tuple(self.engine.analyze(source, self.source_name, language))
        fact_ids: list[str] = []
        probes: list[ProbeRequest] = []
        if self.resolver is not None:
            for diagnostic in diagnostics:
                if diagnostic.status != Status.UNKNOWN:
                    continue
                new_facts, new_probes = self.resolver.resolve(diagnostic)
                probes.extend(new_probes)
                if self.facts is not None:
                    for fact in new_facts:
                        fact_ids.append(self.facts.append(fact))
        status = self._aggregate(diagnostics)
        return AuthoringSnapshot(
            self.sequence,
            self.source_name,
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            status,
            diagnostics,
            tuple(fact_ids),
            tuple(probes),
        )

    @staticmethod
    def _aggregate(diagnostics: tuple[Diagnostic, ...]) -> Status:
        if any(d.status == Status.BLOCKED for d in diagnostics):
            return Status.BLOCKED
        if any(d.status == Status.FAIL or d.blocking for d in diagnostics):
            return Status.FAIL
        if any(d.status == Status.INCOMPLETE for d in diagnostics):
            return Status.INCOMPLETE
        if any(d.status == Status.UNKNOWN for d in diagnostics):
            return Status.UNKNOWN
        if any(d.status == Status.WARNING for d in diagnostics):
            return Status.WARNING
        return Status.PASS
