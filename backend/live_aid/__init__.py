"""GG Live Aid Authoring foundation.

This package is deliberately action-authority free.  It analyzes draft source,
records evidence-bound facts and produces structured requests for existing GG
capability bridges.  Execution remains owned by the existing controllers.
"""

from .contract import Diagnostic, Fact, Status
from .authoring_session import AuthoringSession, AuthoringSnapshot
from .diagnostic_engine import DiagnosticEngine
from .fact_store import FactStore
from .source_index import SourceIndex
from .bridge import LiveAidService

__all__ = [
    "AuthoringSession",
    "AuthoringSnapshot",
    "Diagnostic",
    "DiagnosticEngine",
    "Fact",
    "FactStore",
    "LiveAidService",
    "SourceIndex",
    "Status",
]
