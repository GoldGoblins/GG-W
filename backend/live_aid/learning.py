from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable

from .contract import Fact

@dataclass(frozen=True)
class LearningCandidate:
    claim_key: str
    statement: str
    supporting_fact_ids: tuple[str, ...]
    limitation: str
    promotion_authority: str = "NONE"
    status: str = "PROPOSAL_ONLY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "gg.live-aid.learning-candidate.v1",
            "claim_key": self.claim_key,
            "statement": self.statement,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "limitation": self.limitation,
            "promotion_authority": self.promotion_authority,
            "status": self.status,
        }

def propose_learning(
    *,
    claim_key: str,
    statement: str,
    facts: Iterable[Fact],
    limitation: str,
) -> LearningCandidate:
    ids = tuple(sorted({fact.fact_id for fact in facts}))
    if not ids:
        raise ValueError("LEARNING_REQUIRES_FACT_EVIDENCE")
    return LearningCandidate(claim_key, statement, ids, limitation)
