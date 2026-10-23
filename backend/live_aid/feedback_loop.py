from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .authoring_session import AuthoringSession, AuthoringSnapshot
from .contract import Status
from .repair_broker import RepairRequest, build_repair_request

@dataclass(frozen=True)
class FeedbackCycle:
    snapshot: AuthoringSnapshot
    repair_request: RepairRequest | None
    execution_ready: bool

class LiveAidFeedbackLoop:
    """One continuous authoring feedback cycle.

    It never executes code and never blocks draft generation merely because the
    draft is incomplete.  It emits a repair request once the draft contains
    actionable FAIL/WARNING/UNKNOWN/BLOCKED diagnostics.
    """

    def __init__(self, session: AuthoringSession):
        self.session = session

    def cycle(self, source: str, *, language: str | None = None, fact_context: list[dict[str, Any]] | None = None) -> FeedbackCycle:
        snapshot = self.session.update(source, language)
        actionable = [
            d for d in snapshot.diagnostics
            if d.status in {Status.FAIL, Status.WARNING, Status.UNKNOWN, Status.BLOCKED}
        ]
        request = None
        if actionable:
            request = build_repair_request(
                source,
                self.session.source_name,
                actionable,
                fact_context or [],
            )
        ready = snapshot.status == Status.PASS
        return FeedbackCycle(snapshot, request, ready)
