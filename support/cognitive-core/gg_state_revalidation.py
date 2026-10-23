from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import stat
from typing import Any

SCHEMA_ID = "gg.state-revalidation-base.v1"
REVALIDATION_SCHEMA_ID = "gg.state-revalidation-result.v1"
RECONCILIATION_SCHEMA_ID = "gg.multiagent-state-reconciliation.v1"

ACTION_AUTHORITY = "NONE"
SYSTEM_ALIVE_LOCAL = "NOT_YET"
LIVE_PERSISTENCE = "NO"
DEFAULT_STATE_PATH = None
LEDGER_MUTATION = "NO"
MEMORY_MUTATION = "NO"
GOAL_MUTATION = "NO"
HYPOTHESIS_MUTATION = "NO"
MODEL_INFERENCE = "NO"
NETWORK = "NO"
TOOL_EXECUTION = "NO"
LAST_WRITER_WINS = "NO"
AUTO_CONFLICT_RESOLUTION = "NO"
MULTIAGENT_WINNER_SELECTION = "NONE"
REVALIDATION_PASS_IS_MANDATE_PASS = False
REVALIDATION_PASS_IS_ACTION_APPROVAL = False
REVALIDATED_IS_GLOBAL_LATEST = False
REVALIDATED_IS_CURRENT_ENVIRONMENT_FACT = False

DEPENDENCY_SCOPE_AUTHORITY = "EXPLICIT_CALLER_ASSERTION"
PROJECT_MEMORY_DEPENDENCY_SELECTION_AUTHORITY = "EXPLICIT_CALLER_ASSERTION"
CALLER_ORDER_IS_SEMANTIC = False
SILENT_DEDUPLICATION = "FORBIDDEN"
REVALIDATION_USES_CAPTURED_DEPENDENCY_SCOPE = True
CALLER_SUPPLIES_NEW_SCOPE_DURING_REVALIDATION = False
AUTOMATIC_SCOPE_NARROWING = "FORBIDDEN"
AUTOMATIC_SCOPE_INTERSECTION = "FORBIDDEN"
AUTOMATIC_SCOPE_UNION = "NOT_IMPLEMENTED_IN_K7-J-v1"

PARTICIPANT_ID_AUTHENTICITY = "NOT_VERIFIED_BY_K7-J"
STATE_BASE_HASH_INTEGRITY = "STRUCTURAL_AND_DERIVED_CONTENT_INTEGRITY"
STATE_BASE_HASH_PROVES_HISTORICAL_AUTHENTICITY = False
STATE_BASE_HASH_PROVES_PARTICIPANT_CREATED_CAPTURE = False
STATE_BASE_HISTORICAL_AUTHENTICITY = "NOT_VERIFIED_BY_K7-J"
RECONCILIATION_INPUT_BASES = "CALLER_SUPPLIED_STATE_BASE_ASSERTIONS"
BASE_PREVALIDATION_BEFORE_REVALIDATION = "MANDATORY"
BASE_PREVALIDATION_BEFORE_RECONCILIATION = "MANDATORY"
BASE_METADATA_HAS_CONTROL_AUTHORITY_BEFORE_VALIDATION = False

STATE_BASE_REVISION_IS_LEDGER_HEAD = False
STATE_BASE_REVISION_IS_LEDGER_SEQUENCE = False
STATE_BASE_REVISION_IS_GLOBAL_CLOCK = False
STATE_BASE_REVISION_PROVES_GLOBAL_LATEST = False
VALID_CALLER_SUPPLIED_SNAPSHOT_IS_GLOBALLY_LATEST = False

SOURCE_BELIEF_RUNTIME_FILENAME = "gg_belief_view.py"
SOURCE_BELIEF_RUNTIME_SHA256 = "c3d754e8af0f7a05ab90190603ee1fcf410ab7add9096e7ef2ccb7ea570182b9"
SOURCE_BELIEF_SCHEMA_ID = "gg.belief-view.v1"

SOURCE_GOAL_RUNTIME_FILENAME = "gg_goal_why.py"
SOURCE_GOAL_RUNTIME_SHA256 = "05a83a935273b106ad811aac3bb31c80eaf2bd3b444d2be855486899ad591ae6"
SOURCE_GOAL_SCHEMA_ID = "gg.goal-why-chain.v1"

SOURCE_HYPOTHESIS_RUNTIME_FILENAME = "gg_hypothesis_protocol.py"
SOURCE_HYPOTHESIS_RUNTIME_SHA256 = "fa5abef6f8f87deeda8e9e083d067611b18b0038b07d040ef1363582658fdac3"
SOURCE_HYPOTHESIS_SCHEMA_ID = "gg.hypothesis-protocol.v1"

SOURCE_MEMORY_RUNTIME_FILENAME = "gg_memory_discipline.py"
SOURCE_MEMORY_RUNTIME_SHA256 = "ba9cf88bc2be1283b6aae02603868d0fb5b2f64308d1b2def9678ee0f03a824b"
SOURCE_MEMORY_SCHEMA_ID = "gg.memory-discipline-record.v1"
SOURCE_MEMORY_VIEW_SCHEMA_ID = "gg.memory-discipline-view.v1"

SOURCE_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
AMBIENT_PYTHONPATH_AUTHORITY = "FORBIDDEN"
SYS_PATH_DISCOVERY = "FORBIDDEN"
SYS_MODULES_REGISTRATION = "NO"
IMPORT_BY_MODULE_NAME_WITHOUT_CONTENT_BINDING = "FORBIDDEN"
FALLBACK_SOURCE_LOADER = None

_REVISION_DOMAIN = b"gg.state-revalidation.revision.v1\n"
_SNAPSHOT_DOMAIN = b"gg.state-revalidation.snapshot.v1\n"
_CAPTURE_DOMAIN = b"gg.state-revalidation.capture.v1\n"

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_BASE_FIELDS = frozenset({
    "schema",
    "participant_id",
    "task_id",
    "origin_id",
    "dependency_scope",
    "dependency_projection",
    "source_binding",
    "state_base_revision",
    "source_snapshot_sha256",
    "capture_sha256",
})
_SCOPE_FIELDS = frozenset({
    "requested_claim_keys",
    "project_memory_record_sha256s",
})
_PROJECTION_FIELDS = frozenset({
    "belief",
    "goal",
    "hypothesis",
    "project_memory",
})
_BELIEF_PROJECTION_FIELDS = frozenset({
    "requested_claim_keys",
    "claim_views",
    "relevant_relations",
    "relevant_support_cycles",
    "conflict_present",
    "support_cycle_present",
})
_GOAL_PROJECTION_FIELDS = frozenset({
    "goal_task_trace_sha256",
    "action_trace_sha256",
})
_HYPOTHESIS_PROJECTION_FIELDS = frozenset({
    "requested_claim_keys",
    "belief_conflict_present",
    "belief_support_cycle_present",
    "task_id",
    "origin_id",
    "goal_trace_node_ids",
    "hypothesis_set_mode",
    "hypotheses",
    "information_options",
    "decision",
    "uncertainty_present",
})
_PROJECT_MEMORY_FIELDS = frozenset({
    "record_sha256",
    "memory_id",
    "reuse_state",
})
_SOURCE_BINDING_FIELDS = frozenset({
    "belief_ledger_head_sha256",
    "belief_ledger_record_count",
    "belief_view_sha256",
    "goal_chain_sha256",
    "goal_task_trace_sha256",
    "action_trace_sha256",
    "hypothesis_state_sha256",
    "memory_view_sha256",
})
_REVALIDATION_RESULT_FIELDS = frozenset({
    "schema",
    "base_capture_sha256",
    "base_state_base_revision",
    "reconstructed_state_base_revision",
    "reconstructed_source_snapshot_sha256",
    "result",
    "reason_code",
})
_RECONCILIATION_RESULT_FIELDS = frozenset({
    "schema",
    "bases",
    "scope_state",
    "base_revision_state",
    "per_base_revalidation",
    "result",
    "reason_code",
})

_REVALIDATION_RESULTS = frozenset({
    "REVALIDATED",
    "PLAN_STALE",
    "STATE_CONFLICT",
    "REVALIDATION_BLOCKED",
})
_REVALIDATION_REASONS = frozenset({
    "DEPENDENCY_PROJECTION_UNCHANGED",
    "DEPENDENCY_PROJECTION_CHANGED",
    "RELEVANT_BELIEF_CONFLICT",
    "PROJECT_MEMORY_STALE",
    "PROJECT_MEMORY_MISSING",
    "PROJECT_MEMORY_REFRESH_REQUIRED",
})
_SCOPE_STATES = frozenset({
    "ALIGNED_SCOPE",
    "SCOPE_DIVERGENCE",
    "NOT_COMPARABLE",
})
_BASE_REVISION_STATES = frozenset({
    "ALIGNED_BASES",
    "DIVERGENT_BASES",
    "NOT_COMPARABLE",
})
_RECONCILIATION_RESULTS = frozenset({
    "ALIGNED_REVALIDATED",
    "RECONCILE_REQUIRED",
    "RECONCILIATION_BLOCKED",
})
_RECONCILIATION_REASONS = frozenset({
    "WORK_ITEM_MISMATCH",
    "SCOPE_DIVERGENCE",
    "BASE_REVALIDATION_BLOCKED",
    "BASE_STATE_CONFLICT",
    "BASE_PLAN_STALE",
    "BASE_REVISION_DIVERGENCE",
    "BASES_ALIGNED_REVALIDATED",
})

_SCHEMA_JSON = '{"$defs":{"belief_projection":{"additionalProperties":false,"properties":{"claim_views":{"items":{"$ref":"#/$defs/f_claim_view"},"type":"array"},"conflict_present":{"type":"boolean"},"relevant_relations":{"items":{"$ref":"#/$defs/f_relevant_relation"},"type":"array"},"relevant_support_cycles":{"items":{"$ref":"#/$defs/f_support_cycle"},"type":"array"},"requested_claim_keys":{"items":{"$ref":"#/$defs/nonblank"},"minItems":1,"type":"array","uniqueItems":true},"support_cycle_present":{"type":"boolean"}},"required":["requested_claim_keys","claim_views","relevant_relations","relevant_support_cycles","conflict_present","support_cycle_present"],"type":"object"},"dependency_projection":{"additionalProperties":false,"properties":{"belief":{"$ref":"#/$defs/belief_projection"},"goal":{"$ref":"#/$defs/goal_projection"},"hypothesis":{"$ref":"#/$defs/hypothesis_projection"},"project_memory":{"items":{"$ref":"#/$defs/project_memory_dependency"},"type":"array"}},"required":["belief","goal","hypothesis","project_memory"],"type":"object"},"dependency_scope":{"additionalProperties":false,"properties":{"project_memory_record_sha256s":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"requested_claim_keys":{"items":{"$ref":"#/$defs/nonblank"},"minItems":1,"type":"array","uniqueItems":true}},"required":["requested_claim_keys","project_memory_record_sha256s"],"type":"object"},"f_candidate":{"additionalProperties":false,"properties":{"claim_id":{"$ref":"#/$defs/f_sha256"},"record_refs":{"items":{"$ref":"#/$defs/f_record_ref"},"minItems":1,"type":"array"},"statement":{"$ref":"#/$defs/f_nonblank"}},"required":["claim_id","statement","record_refs"],"type":"object"},"f_claim_view":{"additionalProperties":false,"allOf":[{"if":{"properties":{"state":{"const":"ABSENT"}},"required":["state"]},"then":{"properties":{"candidates":{"maxItems":0}}}},{"if":{"properties":{"state":{"const":"UNCONTESTED"}},"required":["state"]},"then":{"properties":{"candidates":{"maxItems":1,"minItems":1}}}},{"if":{"properties":{"state":{"const":"CONFLICT"}},"required":["state"]},"then":{"properties":{"candidates":{"minItems":2}}}}],"properties":{"candidates":{"items":{"$ref":"#/$defs/f_candidate"},"type":"array"},"claim_key":{"$ref":"#/$defs/f_nonblank"},"state":{"enum":["ABSENT","UNCONTESTED","CONFLICT"],"type":"string"}},"required":["claim_key","state","candidates"],"type":"object"},"f_nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"f_record_ref":{"additionalProperties":false,"properties":{"entry_sha256":{"$ref":"#/$defs/f_sha256"},"epistemic_class":{"enum":["ASSUMPTION","UNTRUSTED_MODEL_OUTPUT","OBSERVED","VERIFIED","DERIVED"],"type":"string"},"parent_entry_sha256s":{"items":{"$ref":"#/$defs/f_sha256"},"type":"array","uniqueItems":true},"provenance_root_entry_sha256s":{"items":{"$ref":"#/$defs/f_sha256"},"minItems":1,"type":"array","uniqueItems":true},"sequence":{"minimum":0,"type":"integer"},"source_fingerprint":{"$ref":"#/$defs/f_nonblank"},"source_id":{"$ref":"#/$defs/f_nonblank"},"source_kind":{"enum":["HUMAN_INPUT","LOCAL_OBSERVATION","DETERMINISTIC_TOOL","MODEL_OUTPUT","HISTORICAL_ARTIFACT","DERIVATION"],"type":"string"}},"required":["entry_sha256","sequence","epistemic_class","source_kind","source_id","source_fingerprint","parent_entry_sha256s","provenance_root_entry_sha256s"],"type":"object"},"f_relevant_relation":{"additionalProperties":false,"properties":{"entry_sha256":{"$ref":"#/$defs/f_sha256"},"epistemic_class":{"enum":["ASSUMPTION","UNTRUSTED_MODEL_OUTPUT","OBSERVED","VERIFIED","DERIVED"],"type":"string"},"object_entry_sha256":{"$ref":"#/$defs/f_sha256"},"relation_type":{"enum":["SUPPORTS","CONTRADICTS"],"type":"string"},"sequence":{"minimum":0,"type":"integer"},"source_fingerprint":{"$ref":"#/$defs/f_nonblank"},"source_id":{"$ref":"#/$defs/f_nonblank"},"source_kind":{"enum":["HUMAN_INPUT","LOCAL_OBSERVATION","DETERMINISTIC_TOOL","MODEL_OUTPUT","HISTORICAL_ARTIFACT","DERIVATION"],"type":"string"},"subject_entry_sha256":{"$ref":"#/$defs/f_sha256"}},"required":["entry_sha256","sequence","relation_type","subject_entry_sha256","object_entry_sha256","epistemic_class","source_kind","source_id","source_fingerprint"],"type":"object"},"f_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"f_support_cycle":{"items":{"$ref":"#/$defs/f_sha256"},"minItems":1,"type":"array","uniqueItems":true},"goal_projection":{"additionalProperties":false,"properties":{"action_trace_sha256":{"$ref":"#/$defs/nullable_sha256"},"goal_task_trace_sha256":{"$ref":"#/$defs/sha256"}},"required":["goal_task_trace_sha256","action_trace_sha256"],"type":"object"},"h_decision":{"additionalProperties":false,"allOf":[{"if":{"properties":{"kind":{"const":"GATHER_INFORMATION"}},"required":["kind"]},"then":{"properties":{"selected_action_node_id":{"type":"null"},"selected_information_option_id":{"$ref":"#/$defs/h_sha256"}}}},{"if":{"properties":{"kind":{"const":"PLAN_ACTION"}},"required":["kind"]},"then":{"properties":{"selected_action_node_id":{"$ref":"#/$defs/h_sha256"},"selected_information_option_id":{"type":"null"}}}},{"if":{"properties":{"kind":{"const":"STOP_UNCERTAINTY"}},"required":["kind"]},"then":{"properties":{"selected_action_node_id":{"type":"null"},"selected_information_option_id":{"type":"null"}}}}],"properties":{"active_hypothesis_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"contested_hypothesis_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"falsified_hypothesis_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"kind":{"enum":["GATHER_INFORMATION","PLAN_ACTION","STOP_UNCERTAINTY"],"type":"string"},"reason_code":{"enum":["ALL_HYPOTHESES_FALSIFIED","CONTESTED_INFORMATION_AVAILABLE","CONTESTED_INFORMATION_MISSING","MULTIPLE_ACTIVE_INFORMATION_AVAILABLE","MULTIPLE_ACTIVE_SHARED_ACTION","MULTIPLE_ACTIVE_DIVERGENT_ACTIONS","SINGLE_OPEN_INFORMATION_AVAILABLE","SINGLE_OPEN_UNRESOLVED","UNKNOWN_OTHER_INFORMATION_AVAILABLE","UNKNOWN_OTHER_UNRESOLVED","SINGLE_SUPPORTED_ACTION","SINGLE_SUPPORTED_ACTION_AMBIGUOUS"],"type":"string"},"selected_action_node_id":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/h_sha256"}]},"selected_information_option_id":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/h_sha256"}]}},"required":["kind","reason_code","selected_information_option_id","selected_action_node_id","active_hypothesis_ids","falsified_hypothesis_ids","contested_hypothesis_ids"],"type":"object"},"h_evidence_ref":{"additionalProperties":false,"properties":{"claim_id":{"$ref":"#/$defs/h_sha256"},"claim_key":{"$ref":"#/$defs/h_nonblank"}},"required":["claim_key","claim_id"],"type":"object"},"h_hypothesis_state":{"additionalProperties":false,"properties":{"candidate_action_node_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"conflicted_claim_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"decisive_falsifier_claim_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"decisive_support_claim_ids":{"items":{"$ref":"#/$defs/h_sha256"},"type":"array","uniqueItems":true},"falsifier_refs":{"items":{"$ref":"#/$defs/h_evidence_ref"},"type":"array","uniqueItems":true},"hypothesis_id":{"$ref":"#/$defs/h_sha256"},"kind":{"enum":["HYPOTHESIS","UNKNOWN_OTHER"],"type":"string"},"source_fingerprint":{"$ref":"#/$defs/h_nonblank"},"source_id":{"$ref":"#/$defs/h_nonblank"},"source_kind":{"$ref":"#/$defs/h_nonblank"},"statement":{"$ref":"#/$defs/h_nonblank"},"status":{"enum":["OPEN","SUPPORTED","CONTESTED","FALSIFIED"],"type":"string"},"support_refs":{"items":{"$ref":"#/$defs/h_evidence_ref"},"type":"array","uniqueItems":true}},"required":["hypothesis_id","kind","statement","source_kind","source_id","source_fingerprint","support_refs","falsifier_refs","candidate_action_node_ids","status","decisive_support_claim_ids","decisive_falsifier_claim_ids","conflicted_claim_ids"],"type":"object"},"h_information_option":{"additionalProperties":false,"allOf":[{"if":{"properties":{"kind":{"const":"OBSERVE_MORE"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"READ_ONLY"}}}},{"if":{"properties":{"kind":{"const":"LOCAL_RESEARCH"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"READ_ONLY"}}}},{"if":{"properties":{"kind":{"const":"ASK_USER"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"READ_ONLY"}}}},{"if":{"properties":{"kind":{"const":"SAFE_EXPERIMENT"}},"required":["kind"]},"then":{"properties":{"effect_class":{"const":"REVERSIBLE_LOCAL"}}}}],"properties":{"cost_rank":{"enum":["LOW","MEDIUM","HIGH"],"type":"string"},"description":{"$ref":"#/$defs/h_nonblank"},"discriminates_hypothesis_ids":{"items":{"$ref":"#/$defs/h_sha256"},"minItems":1,"type":"array","uniqueItems":true},"effect_class":{"enum":["READ_ONLY","REVERSIBLE_LOCAL"],"type":"string"},"kind":{"enum":["OBSERVE_MORE","LOCAL_RESEARCH","SAFE_EXPERIMENT","ASK_USER"],"type":"string"},"option_id":{"$ref":"#/$defs/h_sha256"}},"required":["option_id","kind","description","effect_class","cost_rank","discriminates_hypothesis_ids"],"type":"object"},"h_nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"h_nullable_sha256":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/h_sha256"}]},"h_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"hypothesis_projection":{"additionalProperties":false,"properties":{"belief_conflict_present":{"type":"boolean"},"belief_support_cycle_present":{"type":"boolean"},"decision":{"$ref":"#/$defs/h_decision"},"goal_trace_node_ids":{"items":{"$ref":"#/$defs/sha256"},"minItems":4,"type":"array"},"hypotheses":{"items":{"$ref":"#/$defs/h_hypothesis_state"},"minItems":1,"type":"array"},"hypothesis_set_mode":{"enum":["EXPLICIT_CLOSED_FOR_DECISION","OPEN_WITH_UNKNOWN_OTHER"],"type":"string"},"information_options":{"items":{"$ref":"#/$defs/h_information_option"},"type":"array"},"origin_id":{"$ref":"#/$defs/identifier"},"requested_claim_keys":{"items":{"$ref":"#/$defs/nonblank"},"minItems":1,"type":"array","uniqueItems":true},"task_id":{"$ref":"#/$defs/identifier"},"uncertainty_present":{"type":"boolean"}},"required":["requested_claim_keys","belief_conflict_present","belief_support_cycle_present","task_id","origin_id","goal_trace_node_ids","hypothesis_set_mode","hypotheses","information_options","decision","uncertainty_present"],"type":"object"},"identifier":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]{1,128}$","type":"string"},"nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"nullable_sha256":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]},"project_memory_dependency":{"additionalProperties":false,"properties":{"memory_id":{"$ref":"#/$defs/sha256"},"record_sha256":{"$ref":"#/$defs/sha256"},"reuse_state":{"const":"REVALIDATED","type":"string"}},"required":["record_sha256","memory_id","reuse_state"],"type":"object"},"reconciliation_result":{"$id":"gg.multiagent-state-reconciliation.v1","additionalProperties":false,"properties":{"base_revision_state":{"enum":["ALIGNED_BASES","DIVERGENT_BASES","NOT_COMPARABLE"],"type":"string"},"bases":{"items":{"$ref":"#/$defs/state_base"},"minItems":2,"type":"array"},"per_base_revalidation":{"items":{"$ref":"#/$defs/revalidation_result"},"type":"array"},"reason_code":{"enum":["WORK_ITEM_MISMATCH","SCOPE_DIVERGENCE","BASE_REVALIDATION_BLOCKED","BASE_STATE_CONFLICT","BASE_PLAN_STALE","BASE_REVISION_DIVERGENCE","BASES_ALIGNED_REVALIDATED"],"type":"string"},"result":{"enum":["ALIGNED_REVALIDATED","RECONCILE_REQUIRED","RECONCILIATION_BLOCKED"],"type":"string"},"schema":{"const":"gg.multiagent-state-reconciliation.v1","type":"string"},"scope_state":{"enum":["ALIGNED_SCOPE","SCOPE_DIVERGENCE","NOT_COMPARABLE"],"type":"string"}},"required":["schema","bases","scope_state","base_revision_state","per_base_revalidation","result","reason_code"],"type":"object"},"revalidation_result":{"$id":"gg.state-revalidation-result.v1","additionalProperties":false,"properties":{"base_capture_sha256":{"$ref":"#/$defs/sha256"},"base_state_base_revision":{"$ref":"#/$defs/sha256"},"reason_code":{"enum":["DEPENDENCY_PROJECTION_UNCHANGED","DEPENDENCY_PROJECTION_CHANGED","RELEVANT_BELIEF_CONFLICT","PROJECT_MEMORY_STALE","PROJECT_MEMORY_MISSING","PROJECT_MEMORY_REFRESH_REQUIRED"],"type":"string"},"reconstructed_source_snapshot_sha256":{"$ref":"#/$defs/sha256"},"reconstructed_state_base_revision":{"$ref":"#/$defs/nullable_sha256"},"result":{"enum":["REVALIDATED","PLAN_STALE","STATE_CONFLICT","REVALIDATION_BLOCKED"],"type":"string"},"schema":{"const":"gg.state-revalidation-result.v1","type":"string"}},"required":["schema","base_capture_sha256","base_state_base_revision","reconstructed_state_base_revision","reconstructed_source_snapshot_sha256","result","reason_code"],"type":"object"},"sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"source_binding":{"additionalProperties":false,"properties":{"action_trace_sha256":{"$ref":"#/$defs/nullable_sha256"},"belief_ledger_head_sha256":{"$ref":"#/$defs/nullable_sha256"},"belief_ledger_record_count":{"minimum":0,"type":"integer"},"belief_view_sha256":{"$ref":"#/$defs/sha256"},"goal_chain_sha256":{"$ref":"#/$defs/sha256"},"goal_task_trace_sha256":{"$ref":"#/$defs/sha256"},"hypothesis_state_sha256":{"$ref":"#/$defs/sha256"},"memory_view_sha256":{"$ref":"#/$defs/sha256"}},"required":["belief_ledger_head_sha256","belief_ledger_record_count","belief_view_sha256","goal_chain_sha256","goal_task_trace_sha256","action_trace_sha256","hypothesis_state_sha256","memory_view_sha256"],"type":"object"},"state_base":{"additionalProperties":false,"properties":{"capture_sha256":{"$ref":"#/$defs/sha256"},"dependency_projection":{"$ref":"#/$defs/dependency_projection"},"dependency_scope":{"$ref":"#/$defs/dependency_scope"},"origin_id":{"$ref":"#/$defs/identifier"},"participant_id":{"$ref":"#/$defs/identifier"},"schema":{"const":"gg.state-revalidation-base.v1","type":"string"},"source_binding":{"$ref":"#/$defs/source_binding"},"source_snapshot_sha256":{"$ref":"#/$defs/sha256"},"state_base_revision":{"$ref":"#/$defs/sha256"},"task_id":{"$ref":"#/$defs/identifier"}},"required":["schema","participant_id","task_id","origin_id","dependency_scope","dependency_projection","source_binding","state_base_revision","source_snapshot_sha256","capture_sha256"],"type":"object"}},"$id":"gg.state-revalidation-base.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"capture_sha256":{"$ref":"#/$defs/sha256"},"dependency_projection":{"$ref":"#/$defs/dependency_projection"},"dependency_scope":{"$ref":"#/$defs/dependency_scope"},"origin_id":{"$ref":"#/$defs/identifier"},"participant_id":{"$ref":"#/$defs/identifier"},"schema":{"const":"gg.state-revalidation-base.v1","type":"string"},"source_binding":{"$ref":"#/$defs/source_binding"},"source_snapshot_sha256":{"$ref":"#/$defs/sha256"},"state_base_revision":{"$ref":"#/$defs/sha256"},"task_id":{"$ref":"#/$defs/identifier"}},"required":["schema","participant_id","task_id","origin_id","dependency_scope","dependency_projection","source_binding","state_base_revision","source_snapshot_sha256","capture_sha256"],"title":"GG State Revalidation Base v1","type":"object"}'


class StateRevalidationError(ValueError):
    def __init__(
        self,
        code: str,
        cause_code: str | None = None,
        cause_message: str | None = None,
    ) -> None:
        self.code = code
        self.cause_code = cause_code
        self.cause_message = cause_message
        message = code
        if cause_code is not None:
            message += ":" + cause_code
        if cause_message is not None:
            message += ":" + cause_message
        super().__init__(message)


def _fail(
    code: str,
    cause_code: str | None = None,
    cause_message: str | None = None,
) -> None:
    raise StateRevalidationError(code, cause_code, cause_message)


def _stop(cause_code: str, cause_message: str | None = None) -> None:
    _fail("STOP_STATE_REVALIDATION", cause_code, cause_message)


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
        _fail("CANONICAL_JSON_INVALID", cause_message=str(exc))
    return (text + "\n").encode("utf-8")


def schema_document() -> dict[str, Any]:
    return json.loads(_SCHEMA_JSON)


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_value(value: Any) -> str:
    return _sha_bytes(canonical_json(value))


def _exact(value: Any, fields: frozenset[str], cause: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("STATE_BASE_INVALID", cause)
    return value


def _sha_text(value: Any, cause: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _fail("STATE_BASE_INVALID", cause)
    return value


def _nullable_sha(value: Any, cause: str) -> str | None:
    if value is None:
        return None
    return _sha_text(value, cause)


def _identifier(value: Any, cause: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _fail("STATE_BASE_INVALID", cause)
    return value


def _nonblank(value: Any, cause: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STATE_BASE_INVALID", cause)
    return value


def _sorted_unique_nonblank(
    values: Any,
    *,
    allow_empty: bool,
    cause: str,
) -> list[str]:
    if not isinstance(values, list):
        _fail("STATE_BASE_INVALID", cause)
    if not allow_empty and not values:
        _fail("STATE_BASE_INVALID", cause)
    checked = [_nonblank(item, cause) for item in values]
    if len(set(checked)) != len(checked):
        _fail("STATE_BASE_INVALID", cause)
    if checked != sorted(checked):
        _fail("STATE_BASE_INVALID", cause)
    return checked


def _sorted_unique_sha(
    values: Any,
    *,
    allow_empty: bool,
    cause: str,
) -> list[str]:
    if not isinstance(values, list):
        _fail("STATE_BASE_INVALID", cause)
    if not allow_empty and not values:
        _fail("STATE_BASE_INVALID", cause)
    checked = [_sha_text(item, cause) for item in values]
    if len(set(checked)) != len(checked):
        _fail("STATE_BASE_INVALID", cause)
    if checked != sorted(checked):
        _fail("STATE_BASE_INVALID", cause)
    return checked


def _normalize_scope(
    requested_claim_keys: Any,
    project_memory_record_sha256s: Any,
) -> dict[str, list[str]]:
    if not isinstance(requested_claim_keys, list) or not requested_claim_keys:
        _fail("STATE_BASE_INVALID", "DEPENDENCY_SCOPE_INVALID")
    requested: list[str] = []
    for item in requested_claim_keys:
        requested.append(_nonblank(item, "DEPENDENCY_SCOPE_INVALID"))
    if len(set(requested)) != len(requested):
        _fail("STATE_BASE_INVALID", "DEPENDENCY_SCOPE_DUPLICATE")

    if not isinstance(project_memory_record_sha256s, list):
        _fail("STATE_BASE_INVALID", "DEPENDENCY_SCOPE_INVALID")
    memory: list[str] = []
    for item in project_memory_record_sha256s:
        memory.append(_sha_text(item, "DEPENDENCY_SCOPE_INVALID"))
    if len(set(memory)) != len(memory):
        _fail("STATE_BASE_INVALID", "DEPENDENCY_SCOPE_DUPLICATE")

    return {
        "requested_claim_keys": sorted(requested),
        "project_memory_record_sha256s": sorted(memory),
    }


def state_base_revision(
    task_id: str,
    origin_id: str,
    dependency_scope: dict[str, Any],
    dependency_projection: dict[str, Any],
) -> str:
    _identifier(task_id, "TASK_ID_INVALID")
    _identifier(origin_id, "ORIGIN_ID_INVALID")
    _validate_scope(dependency_scope)
    _validate_projection(dependency_projection, base_mode=False)
    value = {
        "task_id": task_id,
        "origin_id": origin_id,
        "dependency_scope": copy.deepcopy(dependency_scope),
        "dependency_projection": copy.deepcopy(dependency_projection),
    }
    return _sha_bytes(_REVISION_DOMAIN + canonical_json(value))


def source_snapshot_sha256(source_binding: dict[str, Any]) -> str:
    _validate_source_binding(source_binding)
    return _sha_bytes(_SNAPSHOT_DOMAIN + canonical_json(source_binding))


def capture_sha256(base_without_capture_sha256: dict[str, Any]) -> str:
    expected = _BASE_FIELDS - {"capture_sha256"}
    if (
        not isinstance(base_without_capture_sha256, dict)
        or set(base_without_capture_sha256) != expected
    ):
        _fail("STATE_BASE_INVALID", "CAPTURE_SURFACE_INVALID")
    return _sha_bytes(
        _CAPTURE_DOMAIN + canonical_json(base_without_capture_sha256)
    )


def _validate_scope(value: Any) -> dict[str, Any]:
    scope = _exact(value, _SCOPE_FIELDS, "DEPENDENCY_SCOPE_INVALID")
    _sorted_unique_nonblank(
        scope["requested_claim_keys"],
        allow_empty=False,
        cause="DEPENDENCY_SCOPE_INVALID",
    )
    _sorted_unique_sha(
        scope["project_memory_record_sha256s"],
        allow_empty=True,
        cause="DEPENDENCY_SCOPE_INVALID",
    )
    return scope


def _validate_belief_projection(value: Any) -> None:
    projection = _exact(
        value,
        _BELIEF_PROJECTION_FIELDS,
        "BELIEF_PROJECTION_INVALID",
    )
    _sorted_unique_nonblank(
        projection["requested_claim_keys"],
        allow_empty=False,
        cause="BELIEF_PROJECTION_INVALID",
    )
    claim_views = projection["claim_views"]
    if not isinstance(claim_views, list):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    requested = projection["requested_claim_keys"]
    if len(claim_views) != len(requested):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    if [item.get("claim_key") for item in claim_views] != requested:
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    relations = projection["relevant_relations"]
    if not isinstance(relations, list):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    cycles = projection["relevant_support_cycles"]
    if not isinstance(cycles, list):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    if not isinstance(projection["conflict_present"], bool):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    if not isinstance(projection["support_cycle_present"], bool):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    expected_conflict = (
        any(item.get("state") == "CONFLICT" for item in claim_views)
        or any(
            item.get("relation_type") == "CONTRADICTS"
            for item in relations
        )
    )
    if projection["conflict_present"] != expected_conflict:
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")
    if projection["support_cycle_present"] != bool(cycles):
        _fail("STATE_BASE_INVALID", "BELIEF_PROJECTION_INVALID")


def _validate_goal_projection(value: Any) -> None:
    projection = _exact(
        value,
        _GOAL_PROJECTION_FIELDS,
        "GOAL_PROJECTION_INVALID",
    )
    _sha_text(
        projection["goal_task_trace_sha256"],
        "GOAL_PROJECTION_INVALID",
    )
    _nullable_sha(
        projection["action_trace_sha256"],
        "GOAL_PROJECTION_INVALID",
    )


def _validate_hypothesis_projection(value: Any) -> None:
    projection = _exact(
        value,
        _HYPOTHESIS_PROJECTION_FIELDS,
        "HYPOTHESIS_PROJECTION_INVALID",
    )
    _sorted_unique_nonblank(
        projection["requested_claim_keys"],
        allow_empty=False,
        cause="HYPOTHESIS_PROJECTION_INVALID",
    )
    if not isinstance(projection["belief_conflict_present"], bool):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    if not isinstance(projection["belief_support_cycle_present"], bool):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    _identifier(projection["task_id"], "HYPOTHESIS_PROJECTION_INVALID")
    _identifier(projection["origin_id"], "HYPOTHESIS_PROJECTION_INVALID")
    goal_trace = projection["goal_trace_node_ids"]
    if not isinstance(goal_trace, list) or len(goal_trace) < 4:
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    checked_goal_trace = [
        _sha_text(item, "HYPOTHESIS_PROJECTION_INVALID")
        for item in goal_trace
    ]
    if len(set(checked_goal_trace)) != len(checked_goal_trace):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    if projection["hypothesis_set_mode"] not in {
        "EXPLICIT_CLOSED_FOR_DECISION",
        "OPEN_WITH_UNKNOWN_OTHER",
    }:
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    if (
        not isinstance(projection["hypotheses"], list)
        or not projection["hypotheses"]
    ):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    if not isinstance(projection["information_options"], list):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    if not isinstance(projection["decision"], dict):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")
    if not isinstance(projection["uncertainty_present"], bool):
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_PROJECTION_INVALID")


def _validate_project_memory(
    values: Any,
    *,
    base_mode: bool,
) -> None:
    if not isinstance(values, list):
        _fail("STATE_BASE_INVALID", "PROJECT_MEMORY_PROJECTION_INVALID")
    seen: list[str] = []
    for value in values:
        item = _exact(
            value,
            _PROJECT_MEMORY_FIELDS,
            "PROJECT_MEMORY_PROJECTION_INVALID",
        )
        record_sha = _sha_text(
            item["record_sha256"],
            "PROJECT_MEMORY_PROJECTION_INVALID",
        )
        _sha_text(
            item["memory_id"],
            "PROJECT_MEMORY_PROJECTION_INVALID",
        )
        allowed = {"REVALIDATED"} if base_mode else {
            "REVALIDATED",
            "STALE",
            "REFRESH_REQUIRED",
        }
        if item["reuse_state"] not in allowed:
            _fail(
                "STATE_BASE_INVALID",
                "PROJECT_MEMORY_PROJECTION_INVALID",
            )
        seen.append(record_sha)
    if len(set(seen)) != len(seen) or seen != sorted(seen):
        _fail("STATE_BASE_INVALID", "PROJECT_MEMORY_PROJECTION_INVALID")


def _validate_projection(
    value: Any,
    *,
    base_mode: bool,
) -> dict[str, Any]:
    projection = _exact(
        value,
        _PROJECTION_FIELDS,
        "DEPENDENCY_PROJECTION_INVALID",
    )
    _validate_belief_projection(projection["belief"])
    _validate_goal_projection(projection["goal"])
    _validate_hypothesis_projection(projection["hypothesis"])
    _validate_project_memory(
        projection["project_memory"],
        base_mode=base_mode,
    )
    return projection


def _validate_source_binding(value: Any) -> dict[str, Any]:
    binding = _exact(
        value,
        _SOURCE_BINDING_FIELDS,
        "SOURCE_BINDING_INVALID",
    )
    head = _nullable_sha(
        binding["belief_ledger_head_sha256"],
        "SOURCE_BINDING_INVALID",
    )
    count = binding["belief_ledger_record_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        _fail("STATE_BASE_INVALID", "SOURCE_BINDING_INVALID")
    if (count == 0) != (head is None):
        _fail("STATE_BASE_INVALID", "SOURCE_BINDING_INVALID")
    for field in (
        "belief_view_sha256",
        "goal_chain_sha256",
        "goal_task_trace_sha256",
        "hypothesis_state_sha256",
        "memory_view_sha256",
    ):
        _sha_text(binding[field], "SOURCE_BINDING_INVALID")
    _nullable_sha(
        binding["action_trace_sha256"],
        "SOURCE_BINDING_INVALID",
    )
    return binding


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _schema_matches(
    value: Any,
    rule: dict[str, Any],
    root: dict[str, Any],
) -> bool:
    try:
        _schema_assert(value, rule, root)
    except StateRevalidationError:
        return False
    return True


def _schema_assert(
    value: Any,
    rule: dict[str, Any],
    root: dict[str, Any],
) -> None:
    ref = rule.get("$ref")
    if ref is not None:
        prefix = "#/$defs/"
        if not isinstance(ref, str) or not ref.startswith(prefix):
            _fail("STATE_BASE_INVALID", "SCHEMA_REF_INVALID")
        name = ref[len(prefix):]
        target = root.get("$defs", {}).get(name)
        if not isinstance(target, dict):
            _fail("STATE_BASE_INVALID", "SCHEMA_REF_INVALID")
        _schema_assert(value, target, root)
        return

    if "const" in rule and value != rule["const"]:
        _fail("STATE_BASE_INVALID", "SCHEMA_CONST_MISMATCH")

    if "enum" in rule and value not in rule["enum"]:
        _fail("STATE_BASE_INVALID", "SCHEMA_ENUM_MISMATCH")

    expected_type = rule.get("type")
    if expected_type is not None:
        if isinstance(expected_type, list):
            if not any(
                _schema_type_matches(value, item)
                for item in expected_type
            ):
                _fail("STATE_BASE_INVALID", "SCHEMA_TYPE_MISMATCH")
        elif not _schema_type_matches(value, expected_type):
            _fail("STATE_BASE_INVALID", "SCHEMA_TYPE_MISMATCH")

    any_of = rule.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or not any(
            _schema_matches(value, item, root)
            for item in any_of
        ):
            _fail("STATE_BASE_INVALID", "SCHEMA_ANY_OF_MISMATCH")

    one_of = rule.get("oneOf")
    if one_of is not None:
        matches = sum(
            1
            for item in one_of
            if _schema_matches(value, item, root)
        )
        if matches != 1:
            _fail("STATE_BASE_INVALID", "SCHEMA_ONE_OF_MISMATCH")

    all_of = rule.get("allOf")
    if all_of is not None:
        for item in all_of:
            _schema_assert(value, item, root)

    condition = rule.get("if")
    if isinstance(condition, dict) and _schema_matches(
        value,
        condition,
        root,
    ):
        then = rule.get("then")
        if isinstance(then, dict):
            _schema_assert(value, then, root)
    elif isinstance(condition, dict):
        otherwise = rule.get("else")
        if isinstance(otherwise, dict):
            _schema_assert(value, otherwise, root)

    if isinstance(value, str):
        if "minLength" in rule and len(value) < rule["minLength"]:
            _fail("STATE_BASE_INVALID", "SCHEMA_STRING_TOO_SHORT")
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            _fail("STATE_BASE_INVALID", "SCHEMA_STRING_TOO_LONG")
        pattern = rule.get("pattern")
        if pattern is not None and re.fullmatch(
            ".*",
            value,
            flags=re.DOTALL,
        ) is not None:
            if re.search(pattern, value) is None:
                _fail("STATE_BASE_INVALID", "SCHEMA_PATTERN_MISMATCH")

    if isinstance(value, int) and not isinstance(value, bool):
        minimum = rule.get("minimum")
        if minimum is not None and value < minimum:
            _fail("STATE_BASE_INVALID", "SCHEMA_MINIMUM_MISMATCH")

    if isinstance(value, list):
        minimum_items = rule.get("minItems")
        if minimum_items is not None and len(value) < minimum_items:
            _fail("STATE_BASE_INVALID", "SCHEMA_ARRAY_TOO_SHORT")
        if rule.get("uniqueItems") is True:
            try:
                encoded = [
                    json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    for item in value
                ]
            except (TypeError, ValueError):
                _fail("STATE_BASE_INVALID", "SCHEMA_ARRAY_INVALID")
            if len(set(encoded)) != len(encoded):
                _fail("STATE_BASE_INVALID", "SCHEMA_ARRAY_DUPLICATE")
        item_rule = rule.get("items")
        if isinstance(item_rule, dict):
            for item in value:
                _schema_assert(item, item_rule, root)

    if isinstance(value, dict):
        required = rule.get("required", [])
        if any(key not in value for key in required):
            _fail("STATE_BASE_INVALID", "SCHEMA_REQUIRED_MISSING")
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False:
            if any(key not in properties for key in value):
                _fail("STATE_BASE_INVALID", "SCHEMA_EXTRA_PROPERTY")
        for key, child_rule in properties.items():
            if key in value and isinstance(child_rule, dict):
                _schema_assert(value[key], child_rule, root)


def validate_state_base(base: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(base)
    _schema_assert(value, schema_document(), schema_document())
    item = _exact(value, _BASE_FIELDS, "STATE_BASE_SURFACE_INVALID")
    if item["schema"] != SCHEMA_ID:
        _fail("STATE_BASE_INVALID", "STATE_BASE_SCHEMA_INVALID")
    _identifier(item["participant_id"], "PARTICIPANT_ID_INVALID")
    task_id = _identifier(item["task_id"], "TASK_ID_INVALID")
    origin_id = _identifier(item["origin_id"], "ORIGIN_ID_INVALID")
    scope = _validate_scope(item["dependency_scope"])
    projection = _validate_projection(
        item["dependency_projection"],
        base_mode=True,
    )
    binding = _validate_source_binding(item["source_binding"])
    revision = _sha_text(
        item["state_base_revision"],
        "STATE_BASE_REVISION_INVALID",
    )
    snapshot = _sha_text(
        item["source_snapshot_sha256"],
        "SOURCE_SNAPSHOT_SHA256_INVALID",
    )
    capture = _sha_text(
        item["capture_sha256"],
        "CAPTURE_SHA256_INVALID",
    )

    if projection["belief"]["requested_claim_keys"] != scope[
        "requested_claim_keys"
    ]:
        _fail("STATE_BASE_INVALID", "BELIEF_SCOPE_MISMATCH")
    if projection["hypothesis"]["requested_claim_keys"] != scope[
        "requested_claim_keys"
    ]:
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_SCOPE_MISMATCH")
    if projection["hypothesis"]["task_id"] != task_id:
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_TASK_MISMATCH")
    if projection["hypothesis"]["origin_id"] != origin_id:
        _fail("STATE_BASE_INVALID", "HYPOTHESIS_ORIGIN_MISMATCH")
    if (
        projection["hypothesis"]["belief_conflict_present"]
        != projection["belief"]["conflict_present"]
    ):
        _fail("STATE_BASE_INVALID", "BELIEF_CONFLICT_BINDING_MISMATCH")
    if (
        projection["hypothesis"]["belief_support_cycle_present"]
        != projection["belief"]["support_cycle_present"]
    ):
        _fail("STATE_BASE_INVALID", "BELIEF_CYCLE_BINDING_MISMATCH")
    if (
        projection["goal"]["goal_task_trace_sha256"]
        != binding["goal_task_trace_sha256"]
    ):
        _fail("STATE_BASE_INVALID", "GOAL_TRACE_BINDING_MISMATCH")
    if (
        projection["goal"]["action_trace_sha256"]
        != binding["action_trace_sha256"]
    ):
        _fail("STATE_BASE_INVALID", "ACTION_TRACE_BINDING_MISMATCH")
    memory_shas = [
        entry["record_sha256"]
        for entry in projection["project_memory"]
    ]
    if memory_shas != scope["project_memory_record_sha256s"]:
        _fail("STATE_BASE_INVALID", "PROJECT_MEMORY_SCOPE_MISMATCH")

    expected_revision = state_base_revision(
        task_id,
        origin_id,
        scope,
        projection,
    )
    if revision != expected_revision:
        _fail("STATE_BASE_INVALID", "STATE_BASE_REVISION_MISMATCH")

    expected_snapshot = source_snapshot_sha256(binding)
    if snapshot != expected_snapshot:
        _fail("STATE_BASE_INVALID", "SOURCE_SNAPSHOT_SHA256_MISMATCH")

    without_capture = {
        key: copy.deepcopy(value[key])
        for key in value
        if key != "capture_sha256"
    }
    expected_capture = capture_sha256(without_capture)
    if capture != expected_capture:
        _fail("STATE_BASE_INVALID", "CAPTURE_SHA256_MISMATCH")
    return value


def _authority_path(filename: str) -> pathlib.Path:
    here = pathlib.Path(__file__).absolute()
    return here.parent / filename


def _capture_authority_bytes(
    path: pathlib.Path,
    expected_sha256: str,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        _stop("SOURCE_BINDING_MISMATCH", str(exc))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _stop("SOURCE_BINDING_MISMATCH", "AUTHORITY_NOT_REGULAR")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)

    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        _stop("SOURCE_BINDING_MISMATCH", "AUTHORITY_CHANGED_DURING_READ")
    try:
        path_after = path.stat(follow_symlinks=False)
    except OSError as exc:
        _stop("SOURCE_BINDING_MISMATCH", str(exc))
    identity_path_after = (
        path_after.st_dev,
        path_after.st_ino,
        path_after.st_size,
        path_after.st_mtime_ns,
    )
    if (
        not stat.S_ISREG(path_after.st_mode)
        or identity_path_after != identity_before
    ):
        _stop("SOURCE_BINDING_MISMATCH", "AUTHORITY_PATH_IDENTITY_CHANGED")
    data = b"".join(chunks)
    if len(data) != before.st_size:
        _stop("SOURCE_BINDING_MISMATCH", "AUTHORITY_SIZE_MISMATCH")
    if _sha_bytes(data) != expected_sha256:
        _stop("SOURCE_BINDING_MISMATCH", "AUTHORITY_SHA256_MISMATCH")
    return data


def _load_authority(
    *,
    filename: str,
    expected_sha256: str,
    expected_schema_id: str,
    required_primitives: tuple[str, ...],
    private_name: str,
) -> dict[str, Any]:
    path = _authority_path(filename)
    data = _capture_authority_bytes(path, expected_sha256)
    try:
        code = compile(data, str(path), "exec")
    except (SyntaxError, ValueError) as exc:
        _stop("SOURCE_BINDING_MISMATCH", str(exc))
    namespace: dict[str, Any] = {
        "__file__": str(path),
        "__name__": private_name,
        "__package__": None,
    }
    try:
        exec(code, namespace, namespace)
    except Exception as exc:
        _stop("SOURCE_BINDING_MISMATCH", str(exc))
    if namespace.get("SCHEMA_ID") != expected_schema_id:
        _stop("SOURCE_BINDING_MISMATCH", "AUTHORITY_SCHEMA_ID_MISMATCH")
    for primitive in required_primitives:
        if primitive not in namespace:
            _stop(
                "SOURCE_BINDING_MISMATCH",
                "AUTHORITY_PRIMITIVE_MISSING:" + primitive,
            )
    return namespace


def _belief_authority() -> dict[str, Any]:
    return _load_authority(
        filename=SOURCE_BELIEF_RUNTIME_FILENAME,
        expected_sha256=SOURCE_BELIEF_RUNTIME_SHA256,
        expected_schema_id=SOURCE_BELIEF_SCHEMA_ID,
        required_primitives=(
            "SCHEMA_ID",
            "BeliefViewError",
            "reconstruct_belief_view",
            "validate_view",
        ),
        private_name="_gg_k7j_source_belief",
    )


def _goal_authority() -> dict[str, Any]:
    return _load_authority(
        filename=SOURCE_GOAL_RUNTIME_FILENAME,
        expected_sha256=SOURCE_GOAL_RUNTIME_SHA256,
        expected_schema_id=SOURCE_GOAL_SCHEMA_ID,
        required_primitives=(
            "SCHEMA_ID",
            "GoalWhyError",
            "canonical_json",
            "validate_chain",
            "trace_task",
            "trace_action",
        ),
        private_name="_gg_k7j_source_goal",
    )


def _hypothesis_authority() -> dict[str, Any]:
    return _load_authority(
        filename=SOURCE_HYPOTHESIS_RUNTIME_FILENAME,
        expected_sha256=SOURCE_HYPOTHESIS_RUNTIME_SHA256,
        expected_schema_id=SOURCE_HYPOTHESIS_SCHEMA_ID,
        required_primitives=(
            "SCHEMA_ID",
            "HypothesisProtocolError",
            "canonical_json",
            "validate_state",
        ),
        private_name="_gg_k7j_source_hypothesis",
    )


def _memory_authority() -> dict[str, Any]:
    authority = _load_authority(
        filename=SOURCE_MEMORY_RUNTIME_FILENAME,
        expected_sha256=SOURCE_MEMORY_RUNTIME_SHA256,
        expected_schema_id=SOURCE_MEMORY_SCHEMA_ID,
        required_primitives=(
            "SCHEMA_ID",
            "VIEW_SCHEMA_ID",
            "MemoryDisciplineError",
            "canonical_json",
            "reconstruct_memory_view",
        ),
        private_name="_gg_k7j_source_memory",
    )
    if authority.get("VIEW_SCHEMA_ID") != SOURCE_MEMORY_VIEW_SCHEMA_ID:
        _stop("SOURCE_BINDING_MISMATCH", "MEMORY_VIEW_SCHEMA_ID_MISMATCH")
    return authority


def _authority_call(
    authority: dict[str, Any],
    error_name: str,
    cause_code: str,
    primitive: str,
    *args: Any,
) -> Any:
    error_class = authority[error_name]
    try:
        return authority[primitive](*args)
    except error_class as exc:
        upstream_code = getattr(exc, "code", type(exc).__name__)
        _stop(cause_code, str(upstream_code))
    except StateRevalidationError:
        raise
    except Exception as exc:
        _stop(cause_code, type(exc).__name__)


def _project_belief(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested_claim_keys": copy.deepcopy(
            view["requested_claim_keys"]
        ),
        "claim_views": copy.deepcopy(view["claim_views"]),
        "relevant_relations": copy.deepcopy(
            view["relevant_relations"]
        ),
        "relevant_support_cycles": copy.deepcopy(
            view["relevant_support_cycles"]
        ),
        "conflict_present": view["conflict_present"],
        "support_cycle_present": view["support_cycle_present"],
    }


def _project_hypothesis(state: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "requested_claim_keys",
        "belief_conflict_present",
        "belief_support_cycle_present",
        "task_id",
        "origin_id",
        "goal_trace_node_ids",
        "hypothesis_set_mode",
        "hypotheses",
        "information_options",
        "decision",
        "uncertainty_present",
    )
    return {field: copy.deepcopy(state[field]) for field in fields}


def _memory_index(
    memory_view: dict[str, Any],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    buckets = {
        "REVALIDATED": "revalidated_project_semantic_memory",
        "STALE": "stale_project_semantic_memory",
        "REFRESH_REQUIRED": "refresh_required_project_semantic_memory",
    }
    index: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for state, field in buckets.items():
        records = memory_view.get(field)
        if not isinstance(records, list):
            _stop("SOURCE_MEMORY_INVALID", "MEMORY_VIEW_BUCKET_INVALID")
        for record in records:
            if not isinstance(record, dict):
                _stop("SOURCE_MEMORY_INVALID", "MEMORY_VIEW_RECORD_INVALID")
            if record.get("memory_class") != "PROJECT_SEMANTIC_MEMORY":
                _stop("SOURCE_MEMORY_INVALID", "MEMORY_VIEW_CLASS_INVALID")
            record_sha = record.get("record_sha256")
            if not isinstance(record_sha, str) or _SHA_RE.fullmatch(record_sha) is None:
                _stop("SOURCE_MEMORY_INVALID", "MEMORY_RECORD_SHA_INVALID")
            index.setdefault(record_sha, []).append((state, record))
    return index


def _project_memory_for_capture(
    selected: list[str],
    memory_view: dict[str, Any],
) -> list[dict[str, Any]]:
    index = _memory_index(memory_view)
    result: list[dict[str, Any]] = []
    for record_sha in selected:
        matches = index.get(record_sha, [])
        if len(matches) != 1:
            _stop("SOURCE_MEMORY_INVALID", "PROJECT_MEMORY_DEPENDENCY_INVALID")
        state, record = matches[0]
        if state == "STALE":
            _stop("SOURCE_MEMORY_INVALID", "PROJECT_MEMORY_STALE_AT_CAPTURE")
        if state == "REFRESH_REQUIRED":
            _stop(
                "SOURCE_MEMORY_INVALID",
                "PROJECT_MEMORY_REFRESH_REQUIRED_AT_CAPTURE",
            )
        memory_id = record.get("memory_id")
        if not isinstance(memory_id, str) or _SHA_RE.fullmatch(memory_id) is None:
            _stop("SOURCE_MEMORY_INVALID", "PROJECT_MEMORY_DEPENDENCY_INVALID")
        result.append({
            "record_sha256": record_sha,
            "memory_id": memory_id,
            "reuse_state": "REVALIDATED",
        })
    result.sort(key=lambda item: item["record_sha256"])
    return result


def _project_memory_for_revalidation(
    selected: list[str],
    memory_view: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    index = _memory_index(memory_view)
    result: list[dict[str, Any]] = []
    states: dict[str, str] = {}
    for record_sha in selected:
        matches = index.get(record_sha, [])
        if not matches:
            states[record_sha] = "MISSING"
            continue
        if len(matches) != 1:
            _stop("SOURCE_MEMORY_INVALID", "PROJECT_MEMORY_DEPENDENCY_INVALID")
        state, record = matches[0]
        memory_id = record.get("memory_id")
        if not isinstance(memory_id, str) or _SHA_RE.fullmatch(memory_id) is None:
            _stop("SOURCE_MEMORY_INVALID", "PROJECT_MEMORY_DEPENDENCY_INVALID")
        states[record_sha] = state
        result.append({
            "record_sha256": record_sha,
            "memory_id": memory_id,
            "reuse_state": state,
        })
    result.sort(key=lambda item: item["record_sha256"])
    return result, states


def _current_source_state(
    *,
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    memory_records: list[dict[str, Any]],
    project_memory_record_sha256s: list[str],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    source_envelope: dict[str, Any],
    capture_mode: bool,
) -> dict[str, Any]:
    belief = _belief_authority()
    goal = _goal_authority()
    hypothesis = _hypothesis_authority()
    memory = _memory_authority()

    view = _authority_call(
        belief,
        "BeliefViewError",
        "SOURCE_BELIEF_INVALID",
        "reconstruct_belief_view",
        copy.deepcopy(ledger_records),
        copy.deepcopy(requested_claim_keys),
    )
    view = _authority_call(
        belief,
        "BeliefViewError",
        "SOURCE_BELIEF_INVALID",
        "validate_view",
        copy.deepcopy(view),
    )

    validated_goal = _authority_call(
        goal,
        "GoalWhyError",
        "SOURCE_GOAL_INVALID",
        "validate_chain",
        copy.deepcopy(goal_chain),
        copy.deepcopy(source_envelope),
    )
    task_trace = _authority_call(
        goal,
        "GoalWhyError",
        "SOURCE_GOAL_INVALID",
        "trace_task",
        copy.deepcopy(validated_goal),
        copy.deepcopy(source_envelope),
    )

    validated_hypothesis = _authority_call(
        hypothesis,
        "HypothesisProtocolError",
        "SOURCE_HYPOTHESIS_INVALID",
        "validate_state",
        copy.deepcopy(hypothesis_state),
        copy.deepcopy(ledger_records),
        copy.deepcopy(requested_claim_keys),
        copy.deepcopy(validated_goal),
        copy.deepcopy(source_envelope),
    )

    belief_view_sha = _sha_bytes(
        _authority_call(
            hypothesis,
            "HypothesisProtocolError",
            "SOURCE_HYPOTHESIS_INVALID",
            "canonical_json",
            copy.deepcopy(view),
        )
    )
    goal_chain_sha = _sha_bytes(
        _authority_call(
            goal,
            "GoalWhyError",
            "SOURCE_GOAL_INVALID",
            "canonical_json",
            copy.deepcopy(validated_goal),
        )
    )
    task_trace_sha = _sha_bytes(
        _authority_call(
            goal,
            "GoalWhyError",
            "SOURCE_GOAL_INVALID",
            "canonical_json",
            copy.deepcopy(task_trace),
        )
    )

    if validated_hypothesis.get("belief_view_sha256") != belief_view_sha:
        _stop("SOURCE_BINDING_MISMATCH", "BELIEF_VIEW_SHA_MISMATCH")
    if validated_hypothesis.get("goal_chain_sha256") != goal_chain_sha:
        _stop("SOURCE_BINDING_MISMATCH", "GOAL_CHAIN_SHA_MISMATCH")
    if validated_goal.get("task_id") != validated_hypothesis.get("task_id"):
        _stop("SOURCE_BINDING_MISMATCH", "TASK_ID_MISMATCH")
    if validated_goal.get("origin_id") != validated_hypothesis.get("origin_id"):
        _stop("SOURCE_BINDING_MISMATCH", "ORIGIN_ID_MISMATCH")

    action_trace_sha: str | None = None
    decision = validated_hypothesis.get("decision")
    if not isinstance(decision, dict):
        _stop("SOURCE_HYPOTHESIS_INVALID", "DECISION_INVALID")
    if decision.get("kind") == "PLAN_ACTION":
        action_id = decision.get("selected_action_node_id")
        if not isinstance(action_id, str):
            _stop("SOURCE_HYPOTHESIS_INVALID", "PLAN_ACTION_NODE_INVALID")
        action_trace = _authority_call(
            goal,
            "GoalWhyError",
            "SOURCE_GOAL_INVALID",
            "trace_action",
            copy.deepcopy(validated_goal),
            copy.deepcopy(source_envelope),
            action_id,
        )
        action_trace_sha = _sha_bytes(
            _authority_call(
                goal,
                "GoalWhyError",
                "SOURCE_GOAL_INVALID",
                "canonical_json",
                copy.deepcopy(action_trace),
            )
        )

    memory_view = _authority_call(
        memory,
        "MemoryDisciplineError",
        "SOURCE_MEMORY_INVALID",
        "reconstruct_memory_view",
        copy.deepcopy(memory_records),
        copy.deepcopy(ledger_records),
    )
    if not isinstance(memory_view, dict):
        _stop("SOURCE_MEMORY_INVALID", "MEMORY_VIEW_INVALID")
    if memory_view.get("schema") != SOURCE_MEMORY_VIEW_SCHEMA_ID:
        _stop("SOURCE_BINDING_MISMATCH", "MEMORY_VIEW_SCHEMA_MISMATCH")

    hypothesis_sha = _sha_bytes(
        _authority_call(
            hypothesis,
            "HypothesisProtocolError",
            "SOURCE_HYPOTHESIS_INVALID",
            "canonical_json",
            copy.deepcopy(validated_hypothesis),
        )
    )
    memory_sha = _sha_bytes(
        _authority_call(
            memory,
            "MemoryDisciplineError",
            "SOURCE_MEMORY_INVALID",
            "canonical_json",
            copy.deepcopy(memory_view),
        )
    )

    if capture_mode:
        project_memory = _project_memory_for_capture(
            project_memory_record_sha256s,
            memory_view,
        )
        memory_states = {
            item["record_sha256"]: "REVALIDATED"
            for item in project_memory
        }
    else:
        project_memory, memory_states = _project_memory_for_revalidation(
            project_memory_record_sha256s,
            memory_view,
        )

    projection = {
        "belief": _project_belief(view),
        "goal": {
            "goal_task_trace_sha256": task_trace_sha,
            "action_trace_sha256": action_trace_sha,
        },
        "hypothesis": _project_hypothesis(validated_hypothesis),
        "project_memory": project_memory,
    }
    if capture_mode:
        _validate_projection(projection, base_mode=True)
    elif len(project_memory) == len(project_memory_record_sha256s):
        _validate_projection(projection, base_mode=False)

    binding = {
        "belief_ledger_head_sha256": view["ledger_head_sha256"],
        "belief_ledger_record_count": view["ledger_record_count"],
        "belief_view_sha256": belief_view_sha,
        "goal_chain_sha256": goal_chain_sha,
        "goal_task_trace_sha256": task_trace_sha,
        "action_trace_sha256": action_trace_sha,
        "hypothesis_state_sha256": hypothesis_sha,
        "memory_view_sha256": memory_sha,
    }
    _validate_source_binding(binding)

    return {
        "task_id": validated_hypothesis["task_id"],
        "origin_id": validated_hypothesis["origin_id"],
        "projection": projection,
        "binding": binding,
        "memory_states": memory_states,
    }


def make_state_base(
    participant_id: str,
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    memory_records: list[dict[str, Any]],
    project_memory_record_sha256s: list[str],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    _identifier(participant_id, "PARTICIPANT_ID_INVALID")
    scope = _normalize_scope(
        copy.deepcopy(requested_claim_keys),
        copy.deepcopy(project_memory_record_sha256s),
    )
    current = _current_source_state(
        ledger_records=copy.deepcopy(ledger_records),
        requested_claim_keys=scope["requested_claim_keys"],
        memory_records=copy.deepcopy(memory_records),
        project_memory_record_sha256s=scope[
            "project_memory_record_sha256s"
        ],
        goal_chain=copy.deepcopy(goal_chain),
        hypothesis_state=copy.deepcopy(hypothesis_state),
        source_envelope=copy.deepcopy(source_envelope),
        capture_mode=True,
    )
    revision = state_base_revision(
        current["task_id"],
        current["origin_id"],
        scope,
        current["projection"],
    )
    snapshot = source_snapshot_sha256(current["binding"])
    base_without_capture = {
        "schema": SCHEMA_ID,
        "participant_id": participant_id,
        "task_id": current["task_id"],
        "origin_id": current["origin_id"],
        "dependency_scope": scope,
        "dependency_projection": current["projection"],
        "source_binding": current["binding"],
        "state_base_revision": revision,
        "source_snapshot_sha256": snapshot,
    }
    base = copy.deepcopy(base_without_capture)
    base["capture_sha256"] = capture_sha256(base_without_capture)
    return validate_state_base(base)


def _result(
    *,
    base: dict[str, Any],
    reconstructed_revision: str | None,
    reconstructed_snapshot: str,
    result: str,
    reason_code: str,
) -> dict[str, Any]:
    if result not in _REVALIDATION_RESULTS:
        _fail("STATE_BASE_INVALID", "REVALIDATION_RESULT_INVALID")
    if reason_code not in _REVALIDATION_REASONS:
        _fail("STATE_BASE_INVALID", "REVALIDATION_REASON_INVALID")
    return {
        "schema": REVALIDATION_SCHEMA_ID,
        "base_capture_sha256": base["capture_sha256"],
        "base_state_base_revision": base["state_base_revision"],
        "reconstructed_state_base_revision": reconstructed_revision,
        "reconstructed_source_snapshot_sha256": reconstructed_snapshot,
        "result": result,
        "reason_code": reason_code,
    }


def revalidate_state_base(
    base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    try:
        validated_base = validate_state_base(base)
    except StateRevalidationError as exc:
        if exc.code == "STOP_STATE_REVALIDATION":
            raise
        _stop("STATE_BASE_INVALID", exc.cause_code or exc.code)

    scope = validated_base["dependency_scope"]
    current = _current_source_state(
        ledger_records=copy.deepcopy(ledger_records),
        requested_claim_keys=scope["requested_claim_keys"],
        memory_records=copy.deepcopy(memory_records),
        project_memory_record_sha256s=scope[
            "project_memory_record_sha256s"
        ],
        goal_chain=copy.deepcopy(goal_chain),
        hypothesis_state=copy.deepcopy(hypothesis_state),
        source_envelope=copy.deepcopy(source_envelope),
        capture_mode=False,
    )
    if (
        current["task_id"] != validated_base["task_id"]
        or current["origin_id"] != validated_base["origin_id"]
    ):
        _stop("SOURCE_BINDING_MISMATCH", "WORK_ITEM_CHANGED")

    snapshot = source_snapshot_sha256(current["binding"])
    memory_states = current["memory_states"]
    missing = sorted(
        key for key, value in memory_states.items()
        if value == "MISSING"
    )

    reconstructed_revision: str | None = None
    complete = not missing
    if complete:
        reconstructed_revision = state_base_revision(
            current["task_id"],
            current["origin_id"],
            scope,
            current["projection"],
        )

    if current["projection"]["belief"]["conflict_present"]:
        return _result(
            base=validated_base,
            reconstructed_revision=reconstructed_revision,
            reconstructed_snapshot=snapshot,
            result="STATE_CONFLICT",
            reason_code="RELEVANT_BELIEF_CONFLICT",
        )

    if any(value == "REFRESH_REQUIRED" for value in memory_states.values()):
        return _result(
            base=validated_base,
            reconstructed_revision=reconstructed_revision,
            reconstructed_snapshot=snapshot,
            result="REVALIDATION_BLOCKED",
            reason_code="PROJECT_MEMORY_REFRESH_REQUIRED",
        )

    if any(value == "STALE" for value in memory_states.values()):
        return _result(
            base=validated_base,
            reconstructed_revision=reconstructed_revision,
            reconstructed_snapshot=snapshot,
            result="PLAN_STALE",
            reason_code="PROJECT_MEMORY_STALE",
        )

    if missing:
        return _result(
            base=validated_base,
            reconstructed_revision=None,
            reconstructed_snapshot=snapshot,
            result="PLAN_STALE",
            reason_code="PROJECT_MEMORY_MISSING",
        )

    if reconstructed_revision != validated_base["state_base_revision"]:
        return _result(
            base=validated_base,
            reconstructed_revision=reconstructed_revision,
            reconstructed_snapshot=snapshot,
            result="PLAN_STALE",
            reason_code="DEPENDENCY_PROJECTION_CHANGED",
        )

    return _result(
        base=validated_base,
        reconstructed_revision=reconstructed_revision,
        reconstructed_snapshot=snapshot,
        result="REVALIDATED",
        reason_code="DEPENDENCY_PROJECTION_UNCHANGED",
    )


def _reconciliation_result(
    *,
    bases: list[dict[str, Any]],
    scope_state: str,
    base_revision_state: str,
    per_base_revalidation: list[dict[str, Any]],
    result: str,
    reason_code: str,
) -> dict[str, Any]:
    if scope_state not in _SCOPE_STATES:
        _fail("STATE_BASE_INVALID", "RECONCILIATION_SCOPE_STATE_INVALID")
    if base_revision_state not in _BASE_REVISION_STATES:
        _fail(
            "STATE_BASE_INVALID",
            "RECONCILIATION_BASE_REVISION_STATE_INVALID",
        )
    if result not in _RECONCILIATION_RESULTS:
        _fail("STATE_BASE_INVALID", "RECONCILIATION_RESULT_INVALID")
    if reason_code not in _RECONCILIATION_REASONS:
        _fail("STATE_BASE_INVALID", "RECONCILIATION_REASON_INVALID")
    return {
        "schema": RECONCILIATION_SCHEMA_ID,
        "bases": copy.deepcopy(bases),
        "scope_state": scope_state,
        "base_revision_state": base_revision_state,
        "per_base_revalidation": copy.deepcopy(per_base_revalidation),
        "result": result,
        "reason_code": reason_code,
    }


def reconcile_state_bases(
    bases: list[dict[str, Any]],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(bases, list) or len(bases) < 2:
        _stop("RECONCILIATION_INPUT_INVALID")

    validated: list[dict[str, Any]] = []
    for base in bases:
        if not isinstance(base, dict):
            _stop("RECONCILIATION_INPUT_INVALID")
        try:
            validated.append(validate_state_base(base))
        except StateRevalidationError as exc:
            if exc.code == "STOP_STATE_REVALIDATION":
                raise
            _stop("STATE_BASE_INVALID", exc.cause_code or exc.code)

    captures = [item["capture_sha256"] for item in validated]
    if len(set(captures)) != len(captures):
        _stop("DUPLICATE_BASE_CAPTURE")

    validated.sort(key=lambda item: item["capture_sha256"])

    work_items = {
        (item["task_id"], item["origin_id"])
        for item in validated
    }
    if len(work_items) != 1:
        return _reconciliation_result(
            bases=validated,
            scope_state="NOT_COMPARABLE",
            base_revision_state="NOT_COMPARABLE",
            per_base_revalidation=[],
            result="RECONCILIATION_BLOCKED",
            reason_code="WORK_ITEM_MISMATCH",
        )

    scopes = [
        canonical_json(item["dependency_scope"])
        for item in validated
    ]
    if len(set(scopes)) != 1:
        return _reconciliation_result(
            bases=validated,
            scope_state="SCOPE_DIVERGENCE",
            base_revision_state="NOT_COMPARABLE",
            per_base_revalidation=[],
            result="RECONCILE_REQUIRED",
            reason_code="SCOPE_DIVERGENCE",
        )

    revisions = {item["state_base_revision"] for item in validated}
    revision_state = (
        "ALIGNED_BASES"
        if len(revisions) == 1
        else "DIVERGENT_BASES"
    )

    per_base = [
        revalidate_state_base(
            item,
            ledger_records,
            memory_records,
            goal_chain,
            hypothesis_state,
            source_envelope,
        )
        for item in validated
    ]
    per_base.sort(key=lambda item: item["base_capture_sha256"])

    results = [item["result"] for item in per_base]
    if "REVALIDATION_BLOCKED" in results:
        aggregate = "RECONCILIATION_BLOCKED"
        reason = "BASE_REVALIDATION_BLOCKED"
    elif "STATE_CONFLICT" in results:
        aggregate = "RECONCILE_REQUIRED"
        reason = "BASE_STATE_CONFLICT"
    elif "PLAN_STALE" in results:
        aggregate = "RECONCILE_REQUIRED"
        reason = "BASE_PLAN_STALE"
    elif revision_state == "DIVERGENT_BASES":
        aggregate = "RECONCILE_REQUIRED"
        reason = "BASE_REVISION_DIVERGENCE"
    else:
        aggregate = "ALIGNED_REVALIDATED"
        reason = "BASES_ALIGNED_REVALIDATED"

    return _reconciliation_result(
        bases=validated,
        scope_state="ALIGNED_SCOPE",
        base_revision_state=revision_state,
        per_base_revalidation=per_base,
        result=aggregate,
        reason_code=reason,
    )
