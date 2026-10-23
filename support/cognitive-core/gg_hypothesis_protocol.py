from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import stat
from typing import Any

SCHEMA_ID = "gg.hypothesis-protocol.v1"
SOURCE_BELIEF_SCHEMA_ID = "gg.belief-view.v1"
SOURCE_GOAL_SCHEMA_ID = "gg.goal-why-chain.v1"

SOURCE_BELIEF_RUNTIME_SHA256 = "c3d754e8af0f7a05ab90190603ee1fcf410ab7add9096e7ef2ccb7ea570182b9"
SOURCE_GOAL_RUNTIME_SHA256 = "05a83a935273b106ad811aac3bb31c80eaf2bd3b444d2be855486899ad591ae6"

SOURCE_BELIEF_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
SOURCE_GOAL_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"

REQUESTED_CLAIM_KEYS_AUTHORITY = "EXPLICIT_CALLER_SELECTED_SCOPE"
REQUESTED_CLAIM_KEYS_ARE_EPISTEMIC_SOURCE_STATE = False
REQUESTED_CLAIM_KEYS_HISTORICAL_AUTHENTICITY = "NOT_VERIFIED_BY_K7-H"

HYPOTHESIS_INPUT = "EXPLICIT_CALLER_ASSERTION"
HYPOTHESIS_AUTOMATIC_SEMANTIC_GENERATION = False
HYPOTHESIS_SEMANTIC_TRUTH = "NOT_VERIFIED_BY_K7-H"
HYPOTHESIS_SOURCE_FIELDS = "CALLER_ASSERTED_PROVENANCE"
HYPOTHESIS_SOURCE_PROVENANCE_VERIFIED_BY_K7_H = False
HYPOTHESIS_SOURCE_KIND_AFFECTS_EVIDENCE_STRENGTH = False

CALLER_ASSERTED_STATE_SEMANTICS = "CURRENT_INPUT_AUTHORITY"
CALLER_ASSERTED_STATE_SEMANTICS_HISTORICAL_AUTHENTICITY = "NOT_VERIFIED_BY_K7-H"
DERIVED_STATE_SELF_CERTIFICATION = "FORBIDDEN"

GATHER_INFORMATION_EXECUTES_OPTION = False
SELECTED_INFORMATION_OPTION = "PLAN_ONLY"
SAFE_EXPERIMENT_SAFETY_VERIFIED_BY_K7_H = False
SAFE_EXPERIMENT_CLASSIFICATION = "CALLER_CLASSIFIED_REVERSIBLE_LOCAL_INFORMATION_PROPOSAL"
PLAN_ACTION_IS_APPROVAL = False
TRACEABILITY_PASS_IS_MANDATE_PASS = False
TOOL_EXECUTION = "NO"

HYPOTHESIS_DEFINITION_AUTHORITY = "CALLER_ASSERTION"
HYPOTHESIS_EVALUATION_AUTHORITY = "K7-H_DERIVED"
CALLER_MAY_DEFINE_HYPOTHESIS = True
CALLER_MAY_DEFINE_STATUS = False

ACTION_AUTHORITY = "NONE"
LIVE_PERSISTENCE = "NO"
MODEL_INFERENCE = "NO"
NETWORK = "NO"

_HYPOTHESIS_KINDS = ("HYPOTHESIS", "UNKNOWN_OTHER")
_HYPOTHESIS_STATUSES = ("OPEN", "SUPPORTED", "CONTESTED", "FALSIFIED")
_HYPOTHESIS_SET_MODES = (
    "EXPLICIT_CLOSED_FOR_DECISION",
    "OPEN_WITH_UNKNOWN_OTHER",
)
_INFORMATION_KINDS = (
    "OBSERVE_MORE",
    "LOCAL_RESEARCH",
    "SAFE_EXPERIMENT",
    "ASK_USER",
)
_EFFECT_BY_KIND = {
    "OBSERVE_MORE": "READ_ONLY",
    "LOCAL_RESEARCH": "READ_ONLY",
    "ASK_USER": "READ_ONLY",
    "SAFE_EXPERIMENT": "REVERSIBLE_LOCAL",
}
_COST_RANKS = ("LOW", "MEDIUM", "HIGH")
_COST_INDEX = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_EFFECT_INDEX = {"READ_ONLY": 0, "REVERSIBLE_LOCAL": 1}
_DECISION_KINDS = ("GATHER_INFORMATION", "PLAN_ACTION", "STOP_UNCERTAINTY")
_REASON_CODES = (
    "ALL_HYPOTHESES_FALSIFIED",
    "CONTESTED_INFORMATION_AVAILABLE",
    "CONTESTED_INFORMATION_MISSING",
    "MULTIPLE_ACTIVE_INFORMATION_AVAILABLE",
    "MULTIPLE_ACTIVE_SHARED_ACTION",
    "MULTIPLE_ACTIVE_DIVERGENT_ACTIONS",
    "SINGLE_OPEN_INFORMATION_AVAILABLE",
    "SINGLE_OPEN_UNRESOLVED",
    "UNKNOWN_OTHER_INFORMATION_AVAILABLE",
    "UNKNOWN_OTHER_UNRESOLVED",
    "SINGLE_SUPPORTED_ACTION",
    "SINGLE_SUPPORTED_ACTION_AMBIGUOUS",
)

_TOP_FIELDS = frozenset({
    "schema",
    "source_belief_schema",
    "belief_ledger_head_sha256",
    "belief_ledger_record_count",
    "belief_view_sha256",
    "requested_claim_keys",
    "belief_conflict_present",
    "belief_support_cycle_present",
    "source_goal_schema",
    "goal_chain_sha256",
    "task_id",
    "origin_id",
    "goal_trace_node_ids",
    "hypothesis_set_mode",
    "hypotheses",
    "information_options",
    "decision",
    "uncertainty_present",
})

_HYPOTHESIS_DEFINITION_FIELDS = frozenset({
    "hypothesis_id",
    "kind",
    "statement",
    "source_kind",
    "source_id",
    "source_fingerprint",
    "support_refs",
    "falsifier_refs",
    "candidate_action_node_ids",
})

_HYPOTHESIS_STATE_FIELDS = frozenset(set(_HYPOTHESIS_DEFINITION_FIELDS) | {
    "status",
    "decisive_support_claim_ids",
    "decisive_falsifier_claim_ids",
    "conflicted_claim_ids",
})

_INFORMATION_OPTION_FIELDS = frozenset({
    "option_id",
    "kind",
    "description",
    "effect_class",
    "cost_rank",
    "discriminates_hypothesis_ids",
})

_EVIDENCE_REF_FIELDS = frozenset({"claim_key", "claim_id"})

_DECISION_FIELDS = frozenset({
    "kind",
    "reason_code",
    "selected_information_option_id",
    "selected_action_node_id",
    "active_hypothesis_ids",
    "falsified_hypothesis_ids",
    "contested_hypothesis_ids",
})

_SCHEMA_JSON = '{"$defs":{"decision":{"additionalProperties":false,"allOf":[{"if":{"properties":{"kind":{"const":"GATHER_INFORMATION"}},"required":["kind"]},"then":{"properties":{"selected_action_node_id":{"type":"null"},"selected_information_option_id":{"$ref":"#/$defs/sha256"}}}},{"if":{"properties":{"kind":{"const":"PLAN_ACTION"}},"required":["kind"]},"then":{"properties":{"selected_action_node_id":{"$ref":"#/$defs/sha256"},"selected_information_option_id":{"type":"null"}}}},{"if":{"properties":{"kind":{"const":"STOP_UNCERTAINTY"}},"required":["kind"]},"then":{"properties":{"selected_action_node_id":{"type":"null"},"selected_information_option_id":{"type":"null"}}}}],"properties":{"active_hypothesis_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"contested_hypothesis_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"falsified_hypothesis_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"kind":{"enum":["GATHER_INFORMATION","PLAN_ACTION","STOP_UNCERTAINTY"],"type":"string"},"reason_code":{"enum":["ALL_HYPOTHESES_FALSIFIED","CONTESTED_INFORMATION_AVAILABLE","CONTESTED_INFORMATION_MISSING","MULTIPLE_ACTIVE_INFORMATION_AVAILABLE","MULTIPLE_ACTIVE_SHARED_ACTION","MULTIPLE_ACTIVE_DIVERGENT_ACTIONS","SINGLE_OPEN_INFORMATION_AVAILABLE","SINGLE_OPEN_UNRESOLVED","UNKNOWN_OTHER_INFORMATION_AVAILABLE","UNKNOWN_OTHER_UNRESOLVED","SINGLE_SUPPORTED_ACTION","SINGLE_SUPPORTED_ACTION_AMBIGUOUS"],"type":"string"},"selected_action_node_id":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]},"selected_information_option_id":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]}},"required":["kind","reason_code","selected_information_option_id","selected_action_node_id","active_hypothesis_ids","falsified_hypothesis_ids","contested_hypothesis_ids"],"type":"object"},"evidence_ref":{"additionalProperties":false,"properties":{"claim_id":{"$ref":"#/$defs/sha256"},"claim_key":{"$ref":"#/$defs/nonblank"}},"required":["claim_key","claim_id"],"type":"object"},"hypothesis_state":{"additionalProperties":false,"properties":{"candidate_action_node_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"conflicted_claim_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"decisive_falsifier_claim_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"decisive_support_claim_ids":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"falsifier_refs":{"items":{"$ref":"#/$defs/evidence_ref"},"type":"array","uniqueItems":true},"hypothesis_id":{"$ref":"#/$defs/sha256"},"kind":{"enum":["HYPOTHESIS","UNKNOWN_OTHER"],"type":"string"},"source_fingerprint":{"$ref":"#/$defs/nonblank"},"source_id":{"$ref":"#/$defs/nonblank"},"source_kind":{"$ref":"#/$defs/nonblank"},"statement":{"$ref":"#/$defs/nonblank"},"status":{"enum":["OPEN","SUPPORTED","CONTESTED","FALSIFIED"],"type":"string"},"support_refs":{"items":{"$ref":"#/$defs/evidence_ref"},"type":"array","uniqueItems":true}},"required":["hypothesis_id","kind","statement","source_kind","source_id","source_fingerprint","support_refs","falsifier_refs","candidate_action_node_ids","status","decisive_support_claim_ids","decisive_falsifier_claim_ids","conflicted_claim_ids"],"type":"object"},"information_option":{"additionalProperties":false,"allOf":[{"if":{"properties":{"kind":{"const":"OBSERVE_MORE"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"READ_ONLY"}}}},{"if":{"properties":{"kind":{"const":"LOCAL_RESEARCH"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"READ_ONLY"}}}},{"if":{"properties":{"kind":{"const":"ASK_USER"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"READ_ONLY"}}}},{"if":{"properties":{"kind":{"const":"SAFE_EXPERIMENT"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"REVERSIBLE_LOCAL"}}}}],"properties":{"cost_rank":{"enum":["LOW","MEDIUM","HIGH"],"type":"string"},"description":{"$ref":"#/$defs/nonblank"},"discriminates_hypothesis_ids":{"items":{"$ref":"#/$defs/sha256"},"minItems":1,"type":"array","uniqueItems":true},"effect_class":{"enum":["READ_ONLY","REVERSIBLE_LOCAL"],"type":"string"},"kind":{"enum":["OBSERVE_MORE","LOCAL_RESEARCH","SAFE_EXPERIMENT","ASK_USER"],"type":"string"},"option_id":{"$ref":"#/$defs/sha256"}},"required":["option_id","kind","description","effect_class","cost_rank","discriminates_hypothesis_ids"],"type":"object"},"nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"nullable_sha256":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]},"sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"}},"$id":"gg.hypothesis-protocol.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"belief_conflict_present":{"type":"boolean"},"belief_ledger_head_sha256":{"$ref":"#/$defs/nullable_sha256"},"belief_ledger_record_count":{"minimum":0,"type":"integer"},"belief_support_cycle_present":{"type":"boolean"},"belief_view_sha256":{"$ref":"#/$defs/sha256"},"decision":{"$ref":"#/$defs/decision"},"goal_chain_sha256":{"$ref":"#/$defs/sha256"},"goal_trace_node_ids":{"items":{"$ref":"#/$defs/sha256"},"minItems":4,"type":"array","uniqueItems":true},"hypotheses":{"items":{"$ref":"#/$defs/hypothesis_state"},"minItems":1,"type":"array"},"hypothesis_set_mode":{"enum":["EXPLICIT_CLOSED_FOR_DECISION","OPEN_WITH_UNKNOWN_OTHER"],"type":"string"},"information_options":{"items":{"$ref":"#/$defs/information_option"},"type":"array"},"origin_id":{"$ref":"#/$defs/nonblank"},"requested_claim_keys":{"items":{"$ref":"#/$defs/nonblank"},"minItems":1,"type":"array","uniqueItems":true},"schema":{"const":"gg.hypothesis-protocol.v1","type":"string"},"source_belief_schema":{"$ref":"#/$defs/nonblank"},"source_goal_schema":{"$ref":"#/$defs/nonblank"},"task_id":{"$ref":"#/$defs/nonblank"},"uncertainty_present":{"type":"boolean"}},"required":["schema","source_belief_schema","belief_ledger_head_sha256","belief_ledger_record_count","belief_view_sha256","requested_claim_keys","belief_conflict_present","belief_support_cycle_present","source_goal_schema","goal_chain_sha256","task_id","origin_id","goal_trace_node_ids","hypothesis_set_mode","hypotheses","information_options","decision","uncertainty_present"],"title":"GG Hypothesis Idekompass Protocol v1","type":"object"}'


class HypothesisProtocolError(ValueError):
    def __init__(self, code: str, cause_message: str | None = None) -> None:
        self.code = code
        self.cause_message = cause_message
        message = code if cause_message is None else code + ": " + cause_message
        super().__init__(message)


def _fail(code: str, cause_message: str | None = None) -> None:
    raise HypothesisProtocolError(code, cause_message)


def canonical_json(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_JSON_VALUE", str(exc))
    return (text + "\n").encode("utf-8")


def schema_document() -> dict[str, Any]:
    return json.loads(_SCHEMA_JSON)


def _exact_fields(value: Any, fields: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != fields:
        _fail(code)
    return value


def _nonblank(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        _fail(code)
    return value


def _sha256_text(value: Any, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        _fail(code)
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_requested_claim_keys(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail("REQUESTED_CLAIM_SCOPE_INVALID")
    result = [_nonblank(item, "REQUESTED_CLAIM_SCOPE_INVALID") for item in value]
    if len(result) != len(set(result)):
        _fail("REQUESTED_CLAIM_SCOPE_INVALID")
    return sorted(result)


def _normalize_sha_array(value: Any, code: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail(code)
    result = [_sha256_text(item, code) for item in value]
    if len(result) != len(set(result)):
        _fail(code)
    return sorted(result)


def _normalize_ref(value: Any, code: str) -> dict[str, str]:
    ref = _exact_fields(value, _EVIDENCE_REF_FIELDS, code)
    return {
        "claim_key": _nonblank(ref["claim_key"], code),
        "claim_id": _sha256_text(ref["claim_id"], code),
    }


def _normalize_refs(value: Any, code: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        _fail(code)
    refs = [_normalize_ref(item, code) for item in value]
    keys = [(item["claim_key"], item["claim_id"]) for item in refs]
    if len(keys) != len(set(keys)):
        _fail(code)
    return sorted(refs, key=lambda item: (item["claim_key"], item["claim_id"]))


def _hypothesis_semantics(value: Any, *, require_id: bool) -> tuple[dict[str, Any], str | None]:
    if not isinstance(value, dict):
        _fail("HYPOTHESIS_DEFINITION_INVALID")
    expected = _HYPOTHESIS_DEFINITION_FIELDS if require_id else frozenset(
        set(_HYPOTHESIS_DEFINITION_FIELDS) - {"hypothesis_id"}
    )
    if frozenset(value) != expected:
        _fail("HYPOTHESIS_DEFINITION_INVALID")

    kind = value["kind"]
    if kind not in _HYPOTHESIS_KINDS:
        _fail("HYPOTHESIS_DEFINITION_INVALID")

    support = _normalize_refs(value["support_refs"], "HYPOTHESIS_DEFINITION_INVALID")
    falsifiers = _normalize_refs(value["falsifier_refs"], "HYPOTHESIS_DEFINITION_INVALID")
    support_keys = {(x["claim_key"], x["claim_id"]) for x in support}
    falsifier_keys = {(x["claim_key"], x["claim_id"]) for x in falsifiers}
    if support_keys & falsifier_keys:
        _fail("HYPOTHESIS_DEFINITION_INVALID", "SUPPORT_FALSIFIER_REF_OVERLAP")
    if kind == "HYPOTHESIS" and not falsifiers:
        _fail("HYPOTHESIS_DEFINITION_INVALID", "FALSIFIER_REQUIRED")

    actions = _normalize_sha_array(
        value["candidate_action_node_ids"],
        "HYPOTHESIS_DEFINITION_INVALID",
        allow_empty=True,
    )

    semantics: dict[str, Any] = {
        "kind": kind,
        "statement": _nonblank(value["statement"], "HYPOTHESIS_DEFINITION_INVALID"),
        "source_kind": _nonblank(value["source_kind"], "HYPOTHESIS_DEFINITION_INVALID"),
        "source_id": _nonblank(value["source_id"], "HYPOTHESIS_DEFINITION_INVALID"),
        "source_fingerprint": _nonblank(
            value["source_fingerprint"],
            "HYPOTHESIS_DEFINITION_INVALID",
        ),
        "support_refs": support,
        "falsifier_refs": falsifiers,
        "candidate_action_node_ids": actions,
    }
    supplied_id = None
    if require_id:
        supplied_id = _sha256_text(value["hypothesis_id"], "HYPOTHESIS_DEFINITION_INVALID")
    return semantics, supplied_id


def hypothesis_id(definition_semantics: dict[str, Any]) -> str:
    semantics, supplied_id = _hypothesis_semantics(definition_semantics, require_id=False)
    if supplied_id is not None:
        _fail("HYPOTHESIS_DEFINITION_INVALID")
    return _sha256_bytes(
        b"gg.hypothesis-protocol.hypothesis.v1\n" + canonical_json(semantics)
    )


def make_hypothesis(
    *,
    kind: str,
    statement: str,
    source_kind: str,
    source_id: str,
    source_fingerprint: str,
    support_refs: list[dict[str, str]],
    falsifier_refs: list[dict[str, str]],
    candidate_action_node_ids: list[str],
) -> dict[str, Any]:
    semantics = {
        "kind": kind,
        "statement": statement,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_fingerprint": source_fingerprint,
        "support_refs": support_refs,
        "falsifier_refs": falsifier_refs,
        "candidate_action_node_ids": candidate_action_node_ids,
    }
    normalized, _ = _hypothesis_semantics(semantics, require_id=False)
    return {"hypothesis_id": hypothesis_id(normalized), **copy.deepcopy(normalized)}


def _information_semantics(value: Any, *, require_id: bool) -> tuple[dict[str, Any], str | None]:
    if not isinstance(value, dict):
        _fail("INFORMATION_OPTION_INVALID")
    expected = _INFORMATION_OPTION_FIELDS if require_id else frozenset(
        set(_INFORMATION_OPTION_FIELDS) - {"option_id"}
    )
    if frozenset(value) != expected:
        _fail("INFORMATION_OPTION_INVALID")

    kind = value["kind"]
    if kind not in _INFORMATION_KINDS:
        _fail("INFORMATION_OPTION_INVALID")
    effect = value["effect_class"]
    if effect != _EFFECT_BY_KIND[kind]:
        _fail("INFORMATION_OPTION_INVALID", "EFFECT_CLASS_KIND_MISMATCH")
    cost = value["cost_rank"]
    if cost not in _COST_RANKS:
        _fail("INFORMATION_OPTION_INVALID")

    discriminates = _normalize_sha_array(
        value["discriminates_hypothesis_ids"],
        "INFORMATION_OPTION_INVALID",
        allow_empty=False,
    )
    semantics: dict[str, Any] = {
        "kind": kind,
        "description": _nonblank(value["description"], "INFORMATION_OPTION_INVALID"),
        "effect_class": effect,
        "cost_rank": cost,
        "discriminates_hypothesis_ids": discriminates,
    }
    supplied_id = None
    if require_id:
        supplied_id = _sha256_text(value["option_id"], "INFORMATION_OPTION_INVALID")
    return semantics, supplied_id


def information_option_id(definition_semantics: dict[str, Any]) -> str:
    semantics, supplied_id = _information_semantics(definition_semantics, require_id=False)
    if supplied_id is not None:
        _fail("INFORMATION_OPTION_INVALID")
    return _sha256_bytes(
        b"gg.hypothesis-protocol.information-option.v1\n" + canonical_json(semantics)
    )


def make_information_option(
    *,
    kind: str,
    description: str,
    cost_rank: str,
    discriminates_hypothesis_ids: list[str],
) -> dict[str, Any]:
    if kind not in _EFFECT_BY_KIND:
        _fail("INFORMATION_OPTION_INVALID")
    semantics = {
        "kind": kind,
        "description": description,
        "effect_class": _EFFECT_BY_KIND[kind],
        "cost_rank": cost_rank,
        "discriminates_hypothesis_ids": discriminates_hypothesis_ids,
    }
    normalized, _ = _information_semantics(semantics, require_id=False)
    return {"option_id": information_option_id(normalized), **copy.deepcopy(normalized)}


def _authority_path(filename: str) -> pathlib.Path:
    return pathlib.Path(__file__).resolve().with_name(filename)


def _read_exact_regular_file(path: pathlib.Path, code: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        _fail(code, "OPEN_FAILED:" + type(exc).__name__)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _fail(code, "NOT_REGULAR")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        captured = b"".join(chunks)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or after.st_size != len(captured)
        ):
            _fail(code, "SOURCE_CHANGED_DURING_CAPTURE")
        return captured
    finally:
        os.close(fd)


def _load_bound_authority(
    *,
    path: pathlib.Path,
    expected_sha256: str,
    schema_id: str,
    required_callables: tuple[str, ...],
    error_class_name: str,
    private_name: str,
    authority_code: str,
) -> dict[str, Any]:
    captured = _read_exact_regular_file(path, authority_code)
    if _sha256_bytes(captured) != expected_sha256:
        _fail(authority_code, "SHA256_MISMATCH")
    try:
        code = compile(captured, str(path), "exec", dont_inherit=True, optimize=0)
    except BaseException as exc:
        _fail(authority_code, "COMPILE_FAILED:" + type(exc).__name__)

    namespace: dict[str, Any] = {
        "__file__": str(path),
        "__name__": private_name,
        "__package__": None,
        "__builtins__": __builtins__,
    }
    try:
        exec(code, namespace, namespace)
    except BaseException as exc:
        _fail(authority_code, "EXEC_FAILED:" + type(exc).__name__)

    if namespace.get("SCHEMA_ID") != schema_id:
        _fail(authority_code, "SCHEMA_ID_MISMATCH")
    error_type = namespace.get(error_class_name)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail(authority_code, "ERROR_TYPE_MISSING:" + error_class_name)
    for name in required_callables:
        if not callable(namespace.get(name)):
            _fail(authority_code, "PRIMITIVE_MISSING:" + name)
    return namespace


def _belief_authority() -> dict[str, Any]:
    return _load_bound_authority(
        path=_authority_path("gg_belief_view.py"),
        expected_sha256=SOURCE_BELIEF_RUNTIME_SHA256,
        schema_id=SOURCE_BELIEF_SCHEMA_ID,
        required_callables=("reconstruct_belief_view", "validate_view"),
        error_class_name="BeliefViewError",
        private_name="_gg_hypothesis_bound_belief_view",
        authority_code="SOURCE_BELIEF_AUTHORITY_INVALID",
    )


def _goal_authority() -> dict[str, Any]:
    return _load_bound_authority(
        path=_authority_path("gg_goal_why.py"),
        expected_sha256=SOURCE_GOAL_RUNTIME_SHA256,
        schema_id=SOURCE_GOAL_SCHEMA_ID,
        required_callables=("canonical_json", "validate_chain", "trace_task", "trace_action"),
        error_class_name="GoalWhyError",
        private_name="_gg_hypothesis_bound_goal_why",
        authority_code="SOURCE_GOAL_AUTHORITY_INVALID",
    )


def _call_source(
    authority: dict[str, Any],
    function_name: str,
    error_class_name: str,
    outer_code: str,
    *args: Any,
) -> Any:
    fn = authority[function_name]
    error_type = authority[error_class_name]
    try:
        return fn(*args)
    except error_type as exc:
        raise HypothesisProtocolError(outer_code, str(exc)) from exc


def _current_sources(
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[str],
]:
    belief = _belief_authority()
    goal = _goal_authority()

    view = _call_source(
        belief,
        "reconstruct_belief_view",
        "BeliefViewError",
        "SOURCE_BELIEF_INVALID",
        copy.deepcopy(ledger_records),
        copy.deepcopy(requested_claim_keys),
    )
    _call_source(
        belief,
        "validate_view",
        "BeliefViewError",
        "SOURCE_BELIEF_INVALID",
        copy.deepcopy(view),
    )

    normalized_goal = _call_source(
        goal,
        "validate_chain",
        "GoalWhyError",
        "SOURCE_GOAL_INVALID",
        copy.deepcopy(goal_chain),
        copy.deepcopy(source_envelope),
    )
    trace = list(_call_source(
        goal,
        "trace_task",
        "GoalWhyError",
        "SOURCE_GOAL_INVALID",
        copy.deepcopy(goal_chain),
        copy.deepcopy(source_envelope),
    ))
    return belief, goal, view, normalized_goal, trace


def _normalize_definition(value: Any) -> dict[str, Any]:
    semantics, supplied_id = _hypothesis_semantics(value, require_id=True)
    expected = hypothesis_id(semantics)
    if supplied_id != expected:
        _fail("HYPOTHESIS_DEFINITION_INVALID", "HYPOTHESIS_ID_MISMATCH")
    return {"hypothesis_id": expected, **semantics}


def _normalize_information_definition(value: Any) -> dict[str, Any]:
    semantics, supplied_id = _information_semantics(value, require_id=True)
    expected = information_option_id(semantics)
    if supplied_id != expected:
        _fail("INFORMATION_OPTION_INVALID", "OPTION_ID_MISMATCH")
    return {"option_id": expected, **semantics}


def _validate_hypothesis_set(
    mode: Any,
    definitions: list[dict[str, Any]],
) -> str:
    if mode not in _HYPOTHESIS_SET_MODES:
        _fail("HYPOTHESIS_SET_INVALID")
    if not definitions:
        _fail("HYPOTHESIS_SET_EMPTY")
    ids = [item["hypothesis_id"] for item in definitions]
    if len(ids) != len(set(ids)):
        _fail("HYPOTHESIS_SET_INVALID", "DUPLICATE_HYPOTHESIS_ID")
    unknown_count = sum(item["kind"] == "UNKNOWN_OTHER" for item in definitions)
    if mode == "EXPLICIT_CLOSED_FOR_DECISION" and unknown_count != 0:
        _fail("HYPOTHESIS_SET_INVALID", "UNKNOWN_OTHER_FORBIDDEN_IN_CLOSED_MODE")
    if mode == "OPEN_WITH_UNKNOWN_OTHER" and unknown_count != 1:
        _fail("HYPOTHESIS_SET_INVALID", "UNKNOWN_OTHER_REQUIRED_EXACTLY_ONCE")
    return mode


def _validate_ref_scope(
    definitions: list[dict[str, Any]],
    requested_claim_keys: list[str],
) -> None:
    allowed = set(requested_claim_keys)
    for definition in definitions:
        for ref in definition["support_refs"] + definition["falsifier_refs"]:
            if ref["claim_key"] not in allowed:
                _fail("HYPOTHESIS_DEFINITION_INVALID", "CLAIM_KEY_OUTSIDE_REQUESTED_SCOPE")


def _validate_actions(
    goal_authority: dict[str, Any],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
    definitions: list[dict[str, Any]],
) -> None:
    actions = sorted({
        action
        for definition in definitions
        for action in definition["candidate_action_node_ids"]
    })
    for action in actions:
        _call_source(
            goal_authority,
            "trace_action",
            "GoalWhyError",
            "SOURCE_GOAL_INVALID",
            copy.deepcopy(goal_chain),
            copy.deepcopy(source_envelope),
            action,
        )


def _validate_information_options(
    values: Any,
    hypothesis_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        _fail("INFORMATION_OPTION_INVALID")
    options = [_normalize_information_definition(item) for item in values]
    ids = [item["option_id"] for item in options]
    if len(ids) != len(set(ids)):
        _fail("INFORMATION_OPTION_INVALID", "DUPLICATE_OPTION_ID")
    for option in options:
        refs = set(option["discriminates_hypothesis_ids"])
        if not refs or not refs.issubset(hypothesis_ids):
            _fail("INFORMATION_OPTION_INVALID", "HYPOTHESIS_REFERENCE_OUTSIDE_SET")
    return sorted(options, key=lambda item: item["option_id"])


def _claim_views(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["claim_key"]: item for item in view["claim_views"]}


def _contradicted_entry_ids(view: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for relation in view["relevant_relations"]:
        if relation["relation_type"] == "CONTRADICTS":
            result.add(relation["subject_entry_sha256"])
            result.add(relation["object_entry_sha256"])
    return result


def _evaluate_ref(
    ref: dict[str, str],
    views: dict[str, dict[str, Any]],
    contradicted_entries: set[str],
) -> tuple[bool, bool]:
    claim_view = views[ref["claim_key"]]
    candidate = next(
        (
            item
            for item in claim_view["candidates"]
            if item["claim_id"] == ref["claim_id"]
        ),
        None,
    )
    if candidate is None:
        return False, False
    if claim_view["state"] == "CONFLICT":
        return False, True
    if claim_view["state"] != "UNCONTESTED":
        return False, False

    record_refs = candidate["record_refs"]
    if any(item["entry_sha256"] in contradicted_entries for item in record_refs):
        return False, True

    decisive = any(
        item["epistemic_class"] in ("OBSERVED", "VERIFIED")
        for item in record_refs
    )
    return decisive, False


def _evaluate_hypothesis(
    definition: dict[str, Any],
    view: dict[str, Any],
) -> dict[str, Any]:
    views = _claim_views(view)
    contradicted = _contradicted_entry_ids(view)

    decisive_support: set[str] = set()
    decisive_falsifier: set[str] = set()
    conflicted: set[str] = set()

    for ref in definition["support_refs"]:
        decisive, conflict = _evaluate_ref(ref, views, contradicted)
        if decisive:
            decisive_support.add(ref["claim_id"])
        if conflict:
            conflicted.add(ref["claim_id"])

    for ref in definition["falsifier_refs"]:
        decisive, conflict = _evaluate_ref(ref, views, contradicted)
        if decisive:
            decisive_falsifier.add(ref["claim_id"])
        if conflict:
            conflicted.add(ref["claim_id"])

    if conflicted or (decisive_support and decisive_falsifier):
        status_value = "CONTESTED"
    elif decisive_falsifier:
        status_value = "FALSIFIED"
    elif decisive_support:
        status_value = "SUPPORTED"
    else:
        status_value = "OPEN"

    return {
        **copy.deepcopy(definition),
        "status": status_value,
        "decisive_support_claim_ids": sorted(decisive_support),
        "decisive_falsifier_claim_ids": sorted(decisive_falsifier),
        "conflicted_claim_ids": sorted(conflicted),
    }


def _option_coverage(
    option: dict[str, Any],
    active_ids: set[str],
) -> set[str]:
    return set(option["discriminates_hypothesis_ids"]) & active_ids


def _option_is_relevant(
    option: dict[str, Any],
    active: dict[str, dict[str, Any]],
) -> bool:
    coverage = _option_coverage(option, set(active))
    if len(coverage) >= 2:
        return True
    return any(
        active[item]["status"] in ("OPEN", "CONTESTED")
        for item in coverage
    )


def _rank_option(
    option: dict[str, Any],
    active_ids: set[str],
) -> tuple[int, int, int, str]:
    coverage = _option_coverage(option, active_ids)
    return (
        _EFFECT_INDEX[option["effect_class"]],
        -len(coverage),
        _COST_INDEX[option["cost_rank"]],
        option["option_id"],
    )


def _best_option(
    options: list[dict[str, Any]],
    active: dict[str, dict[str, Any]],
    *,
    require_coverage_two: bool = False,
    require_contested: bool = False,
) -> dict[str, Any] | None:
    active_ids = set(active)
    contested_ids = {
        item_id
        for item_id, hypothesis in active.items()
        if hypothesis["status"] == "CONTESTED"
    }
    eligible: list[dict[str, Any]] = []
    for option in options:
        coverage = _option_coverage(option, active_ids)
        if not _option_is_relevant(option, active):
            continue
        if require_coverage_two and len(coverage) < 2:
            continue
        if require_contested and not (coverage & contested_ids):
            continue
        eligible.append(option)
    if not eligible:
        return None
    return min(eligible, key=lambda item: _rank_option(item, active_ids))


def _decision(
    hypotheses: list[dict[str, Any]],
    options: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {item["hypothesis_id"]: item for item in hypotheses}
    active = {
        item_id: item
        for item_id, item in by_id.items()
        if item["status"] != "FALSIFIED"
    }
    active_ids = sorted(active)
    falsified_ids = sorted(
        item_id for item_id, item in by_id.items() if item["status"] == "FALSIFIED"
    )
    contested_ids = sorted(
        item_id for item_id, item in active.items() if item["status"] == "CONTESTED"
    )

    kind: str
    reason: str
    selected_info: str | None = None
    selected_action: str | None = None

    if not active:
        kind = "STOP_UNCERTAINTY"
        reason = "ALL_HYPOTHESES_FALSIFIED"
    elif contested_ids:
        option = _best_option(options, active, require_contested=True)
        if option is not None:
            kind = "GATHER_INFORMATION"
            reason = "CONTESTED_INFORMATION_AVAILABLE"
            selected_info = option["option_id"]
        else:
            kind = "STOP_UNCERTAINTY"
            reason = "CONTESTED_INFORMATION_MISSING"
    elif len(active) >= 2:
        option = _best_option(options, active, require_coverage_two=True)
        if option is not None:
            kind = "GATHER_INFORMATION"
            reason = "MULTIPLE_ACTIVE_INFORMATION_AVAILABLE"
            selected_info = option["option_id"]
        else:
            single_actions = [
                item["candidate_action_node_ids"]
                for item in active.values()
            ]
            if (
                all(len(actions) == 1 for actions in single_actions)
                and len({actions[0] for actions in single_actions}) == 1
            ):
                kind = "PLAN_ACTION"
                reason = "MULTIPLE_ACTIVE_SHARED_ACTION"
                selected_action = single_actions[0][0]
            else:
                kind = "STOP_UNCERTAINTY"
                reason = "MULTIPLE_ACTIVE_DIVERGENT_ACTIONS"
    else:
        only = next(iter(active.values()))
        if only["kind"] == "UNKNOWN_OTHER":
            option = _best_option(options, active)
            if option is not None:
                kind = "GATHER_INFORMATION"
                reason = "UNKNOWN_OTHER_INFORMATION_AVAILABLE"
                selected_info = option["option_id"]
            else:
                kind = "STOP_UNCERTAINTY"
                reason = "UNKNOWN_OTHER_UNRESOLVED"
        elif only["status"] == "OPEN":
            option = _best_option(options, active)
            if option is not None:
                kind = "GATHER_INFORMATION"
                reason = "SINGLE_OPEN_INFORMATION_AVAILABLE"
                selected_info = option["option_id"]
            else:
                kind = "STOP_UNCERTAINTY"
                reason = "SINGLE_OPEN_UNRESOLVED"
        elif only["status"] == "SUPPORTED":
            actions = only["candidate_action_node_ids"]
            if len(actions) == 1:
                kind = "PLAN_ACTION"
                reason = "SINGLE_SUPPORTED_ACTION"
                selected_action = actions[0]
            else:
                kind = "STOP_UNCERTAINTY"
                reason = "SINGLE_SUPPORTED_ACTION_AMBIGUOUS"
        else:
            _fail("STATE_INVALID", "UNREACHABLE_SINGLE_ACTIVE_STATUS")

    return {
        "kind": kind,
        "reason_code": reason,
        "selected_information_option_id": selected_info,
        "selected_action_node_id": selected_action,
        "active_hypothesis_ids": active_ids,
        "falsified_hypothesis_ids": falsified_ids,
        "contested_hypothesis_ids": contested_ids,
    }


def _uncertainty_present(
    hypotheses: list[dict[str, Any]],
    decision: dict[str, Any],
) -> bool:
    active = [item for item in hypotheses if item["status"] != "FALSIFIED"]
    return (
        decision["kind"] == "STOP_UNCERTAINTY"
        or any(item["status"] in ("OPEN", "CONTESTED") for item in active)
        or any(item["kind"] == "UNKNOWN_OTHER" for item in active)
        or len(active) > 1
    )


def _validate_state_shape(value: Any) -> dict[str, Any]:
    state_value = _exact_fields(value, _TOP_FIELDS, "STATE_INVALID")
    if state_value["schema"] != SCHEMA_ID:
        _fail("STATE_INVALID")

    _nonblank(state_value["source_belief_schema"], "STATE_INVALID")
    head = state_value["belief_ledger_head_sha256"]
    if head is not None:
        _sha256_text(head, "STATE_INVALID")
    count = state_value["belief_ledger_record_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        _fail("STATE_INVALID")
    _sha256_text(state_value["belief_view_sha256"], "STATE_INVALID")

    requested = _normalize_requested_claim_keys(state_value["requested_claim_keys"])
    if requested != state_value["requested_claim_keys"]:
        _fail("STATE_INVALID")

    if not isinstance(state_value["belief_conflict_present"], bool):
        _fail("STATE_INVALID")
    if not isinstance(state_value["belief_support_cycle_present"], bool):
        _fail("STATE_INVALID")

    _nonblank(state_value["source_goal_schema"], "STATE_INVALID")
    _sha256_text(state_value["goal_chain_sha256"], "STATE_INVALID")
    _nonblank(state_value["task_id"], "STATE_INVALID")
    _nonblank(state_value["origin_id"], "STATE_INVALID")
    trace_value = state_value["goal_trace_node_ids"]
    if not isinstance(trace_value, list) or len(trace_value) < 4:
        _fail("STATE_INVALID")
    trace = [_sha256_text(item, "STATE_INVALID") for item in trace_value]
    if len(trace) != len(set(trace)):
        _fail("STATE_INVALID")

    mode = state_value["hypothesis_set_mode"]
    if mode not in _HYPOTHESIS_SET_MODES:
        _fail("STATE_INVALID")

    raw_hypotheses = state_value["hypotheses"]
    if not isinstance(raw_hypotheses, list) or not raw_hypotheses:
        _fail("STATE_INVALID")

    normalized_hypotheses: list[dict[str, Any]] = []
    for raw in raw_hypotheses:
        hypothesis = _exact_fields(raw, _HYPOTHESIS_STATE_FIELDS, "STATE_INVALID")
        definition = {key: hypothesis[key] for key in _HYPOTHESIS_DEFINITION_FIELDS}
        normalized_definition = _normalize_definition(definition)
        if normalized_definition != definition:
            _fail("STATE_INVALID")
        if hypothesis["status"] not in _HYPOTHESIS_STATUSES:
            _fail("STATE_INVALID")
        for field in (
            "decisive_support_claim_ids",
            "decisive_falsifier_claim_ids",
            "conflicted_claim_ids",
        ):
            normalized = _normalize_sha_array(hypothesis[field], "STATE_INVALID")
            if normalized != hypothesis[field]:
                _fail("STATE_INVALID")
        normalized_hypotheses.append(copy.deepcopy(hypothesis))

    if [x["hypothesis_id"] for x in normalized_hypotheses] != sorted(
        x["hypothesis_id"] for x in normalized_hypotheses
    ):
        _fail("STATE_INVALID")
    _validate_hypothesis_set(mode, normalized_hypotheses)
    _validate_ref_scope(normalized_hypotheses, requested)

    raw_options = state_value["information_options"]
    if not isinstance(raw_options, list):
        _fail("STATE_INVALID")
    normalized_options = [
        _normalize_information_definition(option)
        for option in raw_options
    ]
    if normalized_options != raw_options:
        _fail("STATE_INVALID")
    if [x["option_id"] for x in normalized_options] != sorted(
        x["option_id"] for x in normalized_options
    ):
        _fail("STATE_INVALID")
    hypothesis_ids = {x["hypothesis_id"] for x in normalized_hypotheses}
    if len(hypothesis_ids) != len(normalized_hypotheses):
        _fail("STATE_INVALID")
    option_ids = {x["option_id"] for x in normalized_options}
    if len(option_ids) != len(normalized_options):
        _fail("STATE_INVALID")
    for option in normalized_options:
        refs = set(option["discriminates_hypothesis_ids"])
        if not refs or not refs.issubset(hypothesis_ids):
            _fail("STATE_INVALID")

    decision = _exact_fields(state_value["decision"], _DECISION_FIELDS, "STATE_INVALID")
    if decision["kind"] not in _DECISION_KINDS or decision["reason_code"] not in _REASON_CODES:
        _fail("STATE_INVALID")
    for field in (
        "active_hypothesis_ids",
        "falsified_hypothesis_ids",
        "contested_hypothesis_ids",
    ):
        normalized = _normalize_sha_array(decision[field], "STATE_INVALID")
        if normalized != decision[field] or not set(normalized).issubset(hypothesis_ids):
            _fail("STATE_INVALID")
    selected_info = decision["selected_information_option_id"]
    selected_action = decision["selected_action_node_id"]
    if selected_info is not None:
        _sha256_text(selected_info, "STATE_INVALID")
    if selected_action is not None:
        _sha256_text(selected_action, "STATE_INVALID")

    if decision["kind"] == "GATHER_INFORMATION":
        if selected_info not in option_ids or selected_action is not None:
            _fail("STATE_INVALID")
    elif decision["kind"] == "PLAN_ACTION":
        if selected_info is not None or selected_action is None:
            _fail("STATE_INVALID")
    elif selected_info is not None or selected_action is not None:
        _fail("STATE_INVALID")

    if not isinstance(state_value["uncertainty_present"], bool):
        _fail("STATE_INVALID")

    return state_value


def _build_from_current_sources(
    *,
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
    hypothesis_definitions: list[dict[str, Any]],
    information_option_definitions: list[dict[str, Any]],
    hypothesis_set_mode: str,
) -> dict[str, Any]:
    requested = _normalize_requested_claim_keys(requested_claim_keys)
    _belief, goal, view, normalized_goal, trace = _current_sources(
        ledger_records,
        requested,
        goal_chain,
        source_envelope,
    )

    if not isinstance(hypothesis_definitions, list) or not hypothesis_definitions:
        _fail("HYPOTHESIS_SET_EMPTY")
    definitions = [_normalize_definition(item) for item in hypothesis_definitions]
    definitions.sort(key=lambda item: item["hypothesis_id"])
    mode = _validate_hypothesis_set(hypothesis_set_mode, definitions)
    _validate_ref_scope(definitions, requested)

    _validate_actions(goal, goal_chain, source_envelope, definitions)

    hypothesis_ids = {item["hypothesis_id"] for item in definitions}
    options = _validate_information_options(
        information_option_definitions,
        hypothesis_ids,
    )

    evaluated = [_evaluate_hypothesis(item, view) for item in definitions]
    evaluated.sort(key=lambda item: item["hypothesis_id"])
    decision = _decision(evaluated, options)

    goal_canonical = _call_source(
        goal,
        "canonical_json",
        "GoalWhyError",
        "SOURCE_GOAL_INVALID",
        normalized_goal,
    )
    state_value: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "source_belief_schema": view["schema"],
        "belief_ledger_head_sha256": view["ledger_head_sha256"],
        "belief_ledger_record_count": view["ledger_record_count"],
        "belief_view_sha256": _sha256_bytes(canonical_json(view)),
        "requested_claim_keys": requested,
        "belief_conflict_present": view["conflict_present"],
        "belief_support_cycle_present": view["support_cycle_present"],
        "source_goal_schema": normalized_goal["schema"],
        "goal_chain_sha256": _sha256_bytes(goal_canonical),
        "task_id": normalized_goal["task_id"],
        "origin_id": normalized_goal["origin_id"],
        "goal_trace_node_ids": trace,
        "hypothesis_set_mode": mode,
        "hypotheses": evaluated,
        "information_options": options,
        "decision": decision,
        "uncertainty_present": _uncertainty_present(evaluated, decision),
    }
    _validate_state_shape(state_value)
    return state_value


def build_hypothesis_state(
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
    hypothesis_definitions: list[dict[str, Any]],
    information_option_definitions: list[dict[str, Any]],
    hypothesis_set_mode: str,
) -> dict[str, Any]:
    return _build_from_current_sources(
        ledger_records=copy.deepcopy(ledger_records),
        requested_claim_keys=copy.deepcopy(requested_claim_keys),
        goal_chain=copy.deepcopy(goal_chain),
        source_envelope=copy.deepcopy(source_envelope),
        hypothesis_definitions=copy.deepcopy(hypothesis_definitions),
        information_option_definitions=copy.deepcopy(information_option_definitions),
        hypothesis_set_mode=hypothesis_set_mode,
    )


def validate_state(
    state: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    supplied = copy.deepcopy(state)
    _validate_state_shape(supplied)

    current_scope = _normalize_requested_claim_keys(copy.deepcopy(requested_claim_keys))
    if supplied["requested_claim_keys"] != current_scope:
        _fail("REQUESTED_CLAIM_SCOPE_MISMATCH")

    definitions = [
        {key: item[key] for key in _HYPOTHESIS_DEFINITION_FIELDS}
        for item in supplied["hypotheses"]
    ]
    options = copy.deepcopy(supplied["information_options"])

    fresh = _build_from_current_sources(
        ledger_records=copy.deepcopy(ledger_records),
        requested_claim_keys=current_scope,
        goal_chain=copy.deepcopy(goal_chain),
        source_envelope=copy.deepcopy(source_envelope),
        hypothesis_definitions=definitions,
        information_option_definitions=options,
        hypothesis_set_mode=supplied["hypothesis_set_mode"],
    )

    belief_binding_fields = (
        "source_belief_schema",
        "belief_ledger_head_sha256",
        "belief_ledger_record_count",
        "belief_view_sha256",
    )
    if any(supplied[field] != fresh[field] for field in belief_binding_fields):
        _fail("SOURCE_BELIEF_SNAPSHOT_MISMATCH")

    goal_binding_fields = (
        "source_goal_schema",
        "goal_chain_sha256",
        "task_id",
        "origin_id",
        "goal_trace_node_ids",
    )
    if any(supplied[field] != fresh[field] for field in goal_binding_fields):
        _fail("SOURCE_GOAL_SNAPSHOT_MISMATCH")

    if supplied != fresh:
        _fail("STATE_INVALID")

    return fresh


def select_next_step(
    state: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    fresh = validate_state(
        state,
        ledger_records,
        requested_claim_keys,
        goal_chain,
        source_envelope,
    )
    return copy.deepcopy(fresh["decision"])
