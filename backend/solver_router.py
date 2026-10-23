"""Deterministic solver routing and compiled Laser Focus cache for GG.

This module selects existing capability identities but never executes them.
Model capabilities may be returned only as explicit fallbacks.

A route focus is intentionally stable across normal source-buffer revisions.
A separate source binding carries exact freshness for downstream verification.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass

from capability_registry import (
    CapabilityRecord,
    CapabilityRegistry,
    digest_json,
)


ROUTE_CONTEXT_SCHEMA = "gg.solver-route-context.v1"
ROUTE_DECISION_SCHEMA = "gg.solver-route-decision.v1"
ROUTE_FOCUS_KEY_SCHEMA = 'gg.solver-route-focus-key.v2'
ROUTE_EVIDENCE_SCHEMA = "gg.capability-route-evidence.v1"
MAX_ROUTE_EVIDENCE = 8
ROUTE_EVIDENCE_REQUIRED_TAG = "route_evidence_required"
LASER_FOCUS_HANDLE_SCHEMA = "gg.laser-focus-handle.v1"
LASER_FOCUS_BINDING_SCHEMA = "gg.laser-focus-binding.v1"
GRAPH_REVISION_SCHEMA = "gg.capability-routing-graph-revision.v1"
POLICY_SCHEMA = "gg.solver-router-policy.v1"

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_LANGUAGE_TAGS = {
    "qml",
    "python",
    "shell",
    "json",
}

_REPAIR_WORDS = {
    "repair",
    "fix",
    "patch",
    "correct",
    "broken",
    "error",
}

_VERIFY_WORDS = {
    "verify",
    "gate",
    "preflight",
    "validate",
    "check",
}

_ANALYZE_WORDS = {
    "analyze",
    "analyse",
    "diagnostic",
    "diagnose",
    "lint",
}

_SEARCH_WORDS = {
    "search",
    "find",
    "lookup",
    "index",
    "symbol",
}

_TASK_WORDS = {
    "task",
    "goal",
    "why",
    "ledger",
    "autonomy",
}

_CHAT_WORDS = {
    "chat",
    "conversation",
    "talk",
}

_POLICY = {
    "schema": POLICY_SCHEMA,
    "deterministic_before_model": True,
    "automatic_model_dispatch": False,
    "registered_capability_execution": False,
    "working_set_limit": 12,
    "working_set_depth": 2,
    "route_focus_excludes_source_revision": True,
    "source_binding_required": True,
    "capability_route_evidence": True,
    "route_evidence_limit": MAX_ROUTE_EVIDENCE,
    "route_evidence_required_tag": ROUTE_EVIDENCE_REQUIRED_TAG,
    "raw_source_in_route_evidence": False,
}

POLICY_REVISION_SHA256 = digest_json(_POLICY)


class SolverRouterError(ValueError):
    """Fail-closed router/cache contract error."""


@dataclass(frozen=True)
class CapabilityRouteEvidence:
    capability_id: str
    evidence_sha256: str
    source_revision: str
    applicability: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema":
                ROUTE_EVIDENCE_SCHEMA,
            "capability_id":
                self.capability_id,
            "evidence_sha256":
                self.evidence_sha256,
            "source_revision":
                self.source_revision,
            "applicability":
                self.applicability,
        }


@dataclass(frozen=True)
class RouteContext:
    query: str
    goal_id: str
    object_id: str
    source_revision: str
    language: str
    diagnostic_class: str
    route_evidence: tuple[CapabilityRouteEvidence, ...] = ()

    def normalized_query(self) -> str:
        return " ".join(_tokens(self.query))

    def validate(self) -> None:
        values = {
            "query": self.query,
            "goal_id": self.goal_id,
            "object_id": self.object_id,
            "source_revision": self.source_revision,
            "language": self.language,
            "diagnostic_class": self.diagnostic_class,
        }

        for name, value in values.items():
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 1024
            ):
                raise SolverRouterError(
                    "route context field invalid:"
                    + name
                )

        if (
            not isinstance(
                self.route_evidence,
                tuple,
            )
            or len(
                self.route_evidence
            ) > MAX_ROUTE_EVIDENCE
        ):
            raise SolverRouterError(
                "route evidence collection invalid"
            )

        seen_capabilities: set[str] = set()

        for evidence in self.route_evidence:
            if not isinstance(
                evidence,
                CapabilityRouteEvidence,
            ):
                raise SolverRouterError(
                    "route evidence item invalid"
                )

            values = {
                "capability_id":
                    evidence.capability_id,
                "source_revision":
                    evidence.source_revision,
                "applicability":
                    evidence.applicability,
            }

            for name, value in values.items():
                if (
                    not isinstance(
                        value,
                        str,
                    )
                    or not value.strip()
                    or len(value) > 1024
                ):
                    raise SolverRouterError(
                        "route evidence field invalid:"
                        + name
                    )

            if (
                not isinstance(
                    evidence.evidence_sha256,
                    str,
                )
                or len(
                    evidence.evidence_sha256
                ) != 64
                or any(
                    character
                    not in "0123456789abcdef"
                    for character
                    in evidence.evidence_sha256
                )
            ):
                raise SolverRouterError(
                    "route evidence sha256 invalid"
                )

            if (
                evidence.capability_id
                in seen_capabilities
            ):
                raise SolverRouterError(
                    "duplicate capability route evidence"
                )

            seen_capabilities.add(
                evidence.capability_id
            )


@dataclass(frozen=True)
class RouteDecision:
    schema: str
    intent: str
    route_mode: str
    primary_capability: str | None
    deterministic_solvers: tuple[str, ...]
    deterministic_prechecks: tuple[str, ...]
    model_fallbacks: tuple[str, ...]
    working_set: tuple[str, ...]
    graph_revision_sha256: str
    policy_revision_sha256: str
    automatic_model_dispatch: bool
    registered_capability_execution: bool
    why: str

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "intent": self.intent,
            "route_mode": self.route_mode,
            "primary_capability": self.primary_capability,
            "deterministic_solvers": list(
                self.deterministic_solvers
            ),
            "deterministic_prechecks": list(
                self.deterministic_prechecks
            ),
            "model_fallbacks": list(
                self.model_fallbacks
            ),
            "working_set": list(
                self.working_set
            ),
            "graph_revision_sha256":
                self.graph_revision_sha256,
            "policy_revision_sha256":
                self.policy_revision_sha256,
            "automatic_model_dispatch":
                self.automatic_model_dispatch,
            "registered_capability_execution":
                self.registered_capability_execution,
            "why": self.why,
        }


@dataclass(frozen=True)
class LaserFocusHandle:
    schema: str
    handle_id: str
    route_focus_key_sha256: str
    route: RouteDecision

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "handle_id": self.handle_id,
            "route_focus_key_sha256":
                self.route_focus_key_sha256,
            "route": self.route.as_dict(),
        }


@dataclass(frozen=True)
class LaserFocusBinding:
    schema: str
    handle_id: str
    source_revision: str
    binding_sha256: str

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "handle_id": self.handle_id,
            "source_revision": self.source_revision,
            "binding_sha256": self.binding_sha256,
        }


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        _TOKEN_RE.findall(value.lower())
    )


def _record_language_matches(
    record: CapabilityRecord,
    language: str,
) -> bool:
    wanted = language.lower()
    tagged_languages = (
        set(record.tags)
        & _LANGUAGE_TAGS
    )

    if not tagged_languages:
        return True

    return wanted in tagged_languages


def _model_capability(
    record: CapabilityRecord,
) -> bool:
    return bool(
        record.contract["model_inference"]
    )


def _safe_deterministic_record(
    record: CapabilityRecord,
) -> bool:
    if _model_capability(record):
        return False

    if record.contract["persistent_write"] == "BOUNDED_SOURCE":
        return False

    return True


def _intent(
    context: RouteContext,
) -> str:
    query_tokens = set(
        _tokens(
            context.query
        )
    )

    diagnostic_tokens = set(
        _tokens(
            context.diagnostic_class
        )
    )

    rules = (
        ("REPAIR", _REPAIR_WORDS),
        ("VERIFY", _VERIFY_WORDS),
        ("ANALYZE", _ANALYZE_WORDS),
        ("SEARCH", _SEARCH_WORDS),
        ("TASK", _TASK_WORDS),
        ("CHAT", _CHAT_WORDS),
    )

    for tokens in (
        query_tokens,
        diagnostic_tokens,
    ):
        for intent, words in rules:
            if tokens & words:
                return intent

    return "GENERAL"


class SolverRouter:
    """Passive deterministic route selector over one resident registry."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        working_set_limit: int = 12,
        working_set_depth: int = 2,
        edge_enabled: object | None = None,
    ) -> None:
        if (
            working_set_limit < 1
            or working_set_limit > 64
        ):
            raise SolverRouterError(
                "working_set_limit invalid"
            )

        if (
            working_set_depth < 0
            or working_set_depth > 4
        ):
            raise SolverRouterError(
                "working_set_depth invalid"
            )

        if (
            edge_enabled is not None
            and not callable(edge_enabled)
        ):
            raise SolverRouterError(
                "edge_enabled invalid"
            )

        self._registry = registry
        self._edge_enabled = edge_enabled
        self._working_set_limit = (
            working_set_limit
        )
        self._working_set_depth = (
            working_set_depth
        )

        self._graph_revision_sha256 = (
            self._derive_graph_revision()
        )

    @property
    def graph_revision_sha256(self) -> str:
        return self._graph_revision_sha256

    @property
    def policy_revision_sha256(self) -> str:
        return POLICY_REVISION_SHA256

    def _derive_graph_revision(self) -> str:
        records = self._registry.records()

        return digest_json(
            {
                "schema":
                    GRAPH_REVISION_SCHEMA,
                "records": [
                    {
                        "human_id":
                            record.human_id,
                        "execution_revision_sha256":
                            record.execution_revision_sha256,
                        "metadata_sha256":
                            record.metadata_sha256,
                    }
                    for record in records
                ],
            }
        )

    def route_focus_key(
        self,
        context: RouteContext,
    ) -> str:
        context.validate()

        return digest_json(
            {
                "schema":
                    ROUTE_FOCUS_KEY_SCHEMA,
                "goal_id":
                    context.goal_id,
                "object_id":
                    context.object_id,
                "language":
                    context.language.lower(),
                "diagnostic_class":
                    context.diagnostic_class,
                "query":
                    context.normalized_query(),
                "route_evidence": [
                    {
                        "capability_id":
                            evidence.capability_id,
                        "evidence_sha256":
                            evidence.evidence_sha256,
                        "applicability":
                            evidence.applicability,
                    }
                    for evidence, _
                    in self._validated_route_evidence(
                        context
                    )
                ],
                "graph_revision_sha256":
                    self.graph_revision_sha256,
                "policy_revision_sha256":
                    self.policy_revision_sha256,
            }
        )

    def _validated_route_evidence(
        self,
        context: RouteContext,
    ) -> tuple[
        tuple[
            CapabilityRouteEvidence,
            CapabilityRecord,
        ],
        ...,
    ]:
        context.validate()

        by_id = {
            record.human_id:
                record
            for record
            in self._registry.records()
        }

        validated: list[
            tuple[
                CapabilityRouteEvidence,
                CapabilityRecord,
            ]
        ] = []

        for evidence in context.route_evidence:
            if (
                evidence.source_revision
                != context.source_revision
            ):
                continue

            record = by_id.get(
                evidence.capability_id
            )

            if record is None:
                continue

            if (
                ROUTE_EVIDENCE_REQUIRED_TAG
                not in record.tags
            ):
                continue

            if evidence.applicability != "safe":
                continue

            if not _safe_deterministic_record(
                record
            ):
                continue

            validated.append(
                (
                    evidence,
                    record,
                )
            )

        validated.sort(
            key=lambda item: (
                item[0].capability_id,
                item[0].evidence_sha256,
                item[0].applicability,
            )
        )

        return tuple(
            validated
        )


    def _runtime_edge_enabled(
        self,
        edge_id: str,
    ) -> bool:
        callback = self._edge_enabled

        if callback is None:
            return True

        if not callable(callback):
            raise SolverRouterError(
                "edge_enabled invalid"
            )

        enabled = callback(edge_id)

        if not isinstance(enabled, bool):
            raise SolverRouterError(
                "edge_enabled result invalid"
            )

        return enabled


    def _working_set(
        self,
        context: RouteContext,
    ) -> tuple[CapabilityRecord, ...]:
        if not self._runtime_edge_enabled(
            "call-11"
        ):
            raise SolverRouterError(
                "MACHINE_GRAPH_EDGE_DISABLED:"
                "call-11"
            )

        raw = self._registry.active_working_set(
            context.normalized_query(),
            limit=self._working_set_limit,
            depth=self._working_set_depth,
        )

        return tuple(
            record
            for record in raw
            if _record_language_matches(
                record,
                context.language,
            )
        )

    def route(
        self,
        context: RouteContext,
    ) -> RouteDecision:
        context.validate()

        intent = _intent(context)
        working = self._working_set(context)

        evidence_records = tuple(
            record
            for _, record
            in self._validated_route_evidence(
                context
            )
        )

        evidence_ids = {
            record.human_id
            for record
            in evidence_records
        }

        route_pool = (
            evidence_records
            + tuple(
                record
                for record in working
                if (
                    record.human_id
                    not in evidence_ids
                    and ROUTE_EVIDENCE_REQUIRED_TAG
                    not in record.tags
                )
            )
        )

        deterministic = tuple(
            record
            for record in route_pool
            if _safe_deterministic_record(
                record
            )
        )

        model = tuple(
            record
            for record in route_pool
            if _model_capability(record)
        )

        deterministic_solvers: tuple[
            CapabilityRecord,
            ...
        ]

        deterministic_prechecks: tuple[
            CapabilityRecord,
            ...
        ]

        model_fallbacks: tuple[
            CapabilityRecord,
            ...
        ]

        if intent == "REPAIR":
            deterministic_solvers = tuple(
                record
                for record in deterministic
                if record.kind == "REPAIR"
            )

            deterministic_prechecks = tuple(
                record
                for record in deterministic
                if record.kind
                in {
                    "ANALYZER",
                    "VERIFIER",
                    "STATE_SERVICE",
                }
            )

            model_fallbacks = tuple(
                record
                for record in model
                if record.kind
                in {
                    "REPAIR",
                    "COMPOSITE",
                    "MODEL",
                }
            )

        elif intent == "VERIFY":
            deterministic_solvers = tuple(
                record
                for record in deterministic
                if record.kind == "VERIFIER"
            )

            deterministic_prechecks = tuple(
                record
                for record in deterministic
                if record.kind
                in {
                    "ANALYZER",
                    "STATE_SERVICE",
                }
            )

            model_fallbacks = ()

        elif intent == "ANALYZE":
            deterministic_solvers = tuple(
                record
                for record in deterministic
                if record.kind == "ANALYZER"
            )

            deterministic_prechecks = tuple(
                record
                for record in deterministic
                if record.kind
                in {
                    "STATE_SERVICE",
                    "VERIFIER",
                }
            )

            model_fallbacks = ()

        elif intent == "SEARCH":
            deterministic_solvers = tuple(
                record
                for record in deterministic
                if record.kind
                in {
                    "STATE_SERVICE",
                    "ANALYZER",
                    "ACTION",
                }
            )

            deterministic_prechecks = ()

            model_fallbacks = ()

        elif intent == "TASK":
            deterministic_solvers = tuple(
                record
                for record in deterministic
                if record.kind
                in {
                    "STATE_SERVICE",
                    "CONTROL",
                }
            )

            deterministic_prechecks = tuple(
                record
                for record in deterministic
                if record.kind == "ACTION"
            )

            model_fallbacks = tuple(
                record
                for record in model
                if record.kind
                in {
                    "CONTROL",
                    "MODEL",
                }
            )

        elif intent == "CHAT":
            deterministic_solvers = ()
            deterministic_prechecks = ()
            model_fallbacks = tuple(
                record
                for record in model
                if record.kind == "MODEL"
            )

        else:
            deterministic_solvers = deterministic
            deterministic_prechecks = ()
            model_fallbacks = model

        primary = (
            deterministic_solvers[0].human_id
            if deterministic_solvers
            else None
        )

        if deterministic_solvers:
            route_mode = "REUSE_DETERMINISTIC"

        elif (
            deterministic_prechecks
            and model_fallbacks
        ):
            route_mode = (
                "DETERMINISTIC_PRECHECK_THEN_MODEL_FALLBACK"
            )

        elif model_fallbacks:
            route_mode = "MODEL_FALLBACK_REQUIRED"

        elif deterministic_prechecks:
            route_mode = "DETERMINISTIC_PRECHECK_ONLY"

        else:
            route_mode = "NO_SUITABLE_CAPABILITY"

        fallback_id = (
            model_fallbacks[0].human_id
            if model_fallbacks
            else "NONE"
        )

        why = (
            "intent="
            + intent
            + "; deterministic_solvers="
            + str(len(deterministic_solvers))
            + "; deterministic_prechecks="
            + str(len(deterministic_prechecks))
            + "; model_fallback="
            + fallback_id
            + "; automatic_model_dispatch=NO"
        )

        return RouteDecision(
            schema=ROUTE_DECISION_SCHEMA,
            intent=intent,
            route_mode=route_mode,
            primary_capability=primary,
            deterministic_solvers=tuple(
                record.human_id
                for record
                in deterministic_solvers
            ),
            deterministic_prechecks=tuple(
                record.human_id
                for record
                in deterministic_prechecks
            ),
            model_fallbacks=tuple(
                record.human_id
                for record
                in model_fallbacks
            ),
            working_set=tuple(
                record.human_id
                for record in route_pool
            ),
            graph_revision_sha256=(
                self.graph_revision_sha256
            ),
            policy_revision_sha256=(
                self.policy_revision_sha256
            ),
            automatic_model_dispatch=False,
            registered_capability_execution=False,
            why=why,
        )


class LaserFocusCache:
    """Bounded compiled route-focus cache with O(1) direct-handle lookup."""

    def __init__(
        self,
        router: SolverRouter,
        *,
        max_entries: int = 256,
        edge_enabled: object | None = None,
    ) -> None:
        if (
            max_entries < 1
            or max_entries > 4096
        ):
            raise SolverRouterError(
                "max_entries invalid"
            )

        if (
            edge_enabled is not None
            and not callable(edge_enabled)
        ):
            raise SolverRouterError(
                "edge_enabled invalid"
            )

        self._router = router
        self._edge_enabled = edge_enabled
        self._max_entries = max_entries
        self._handles: dict[
            str,
            LaserFocusHandle,
        ] = {}
        self._insertion_order: deque[str] = deque()

    def _runtime_edge_enabled(
        self,
        edge_id: str,
    ) -> bool:
        callback = self._edge_enabled

        if callback is None:
            return True

        if not callable(callback):
            raise SolverRouterError(
                "edge_enabled invalid"
            )

        enabled = callback(edge_id)

        if not isinstance(enabled, bool):
            raise SolverRouterError(
                "edge_enabled result invalid"
            )

        return enabled

    @property
    def size(self) -> int:
        return len(self._handles)

    def lookup(
        self,
        handle_id: str,
    ) -> LaserFocusHandle | None:
        return self._handles.get(handle_id)

    def _compile(
        self,
        context: RouteContext,
        handle_id: str,
    ) -> LaserFocusHandle:
        if not self._runtime_edge_enabled(
            "call-09"
        ):
            raise SolverRouterError(
                "MACHINE_GRAPH_EDGE_DISABLED:"
                "call-09"
            )

        route = self._router.route(context)

        handle = LaserFocusHandle(
            schema=LASER_FOCUS_HANDLE_SCHEMA,
            handle_id=handle_id,
            route_focus_key_sha256=handle_id,
            route=route,
        )

        if (
            handle_id not in self._handles
            and len(self._handles)
            >= self._max_entries
        ):
            oldest = self._insertion_order.popleft()
            self._handles.pop(
                oldest,
                None,
            )

        if handle_id not in self._handles:
            self._insertion_order.append(
                handle_id
            )

        self._handles[handle_id] = handle

        return handle

    def focus(
        self,
        context: RouteContext,
    ) -> LaserFocusHandle:
        if not self._runtime_edge_enabled(
            "call-10"
        ):
            raise SolverRouterError(
                "MACHINE_GRAPH_EDGE_DISABLED:"
                "call-10"
            )

        handle_id = (
            self._router.route_focus_key(
                context
            )
        )

        existing = self._handles.get(
            handle_id
        )

        if existing is not None:
            return existing

        return self._compile(
            context,
            handle_id,
        )

    def bind(
        self,
        context: RouteContext,
    ) -> LaserFocusBinding:
        context.validate()

        handle = self.focus(context)

        binding_sha256 = digest_json(
            {
                "schema":
                    LASER_FOCUS_BINDING_SCHEMA,
                "handle_id":
                    handle.handle_id,
                "source_revision":
                    context.source_revision,
            }
        )

        return LaserFocusBinding(
            schema=LASER_FOCUS_BINDING_SCHEMA,
            handle_id=handle.handle_id,
            source_revision=context.source_revision,
            binding_sha256=binding_sha256,
        )


def sha256_text(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()
