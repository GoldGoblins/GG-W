from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import pathlib
import stat
from typing import Any

SCHEMA_ID = "gg.memory-discipline-record.v1"
VIEW_SCHEMA_ID = "gg.memory-discipline-view.v1"
CONTENT_SCHEMA_ID = SCHEMA_ID

SOURCE_BELIEF_SCHEMA_ID = "gg.belief-view.v1"
SOURCE_HYPOTHESIS_SCHEMA_ID = "gg.hypothesis-protocol.v1"
SOURCE_BELIEF_RUNTIME_SHA256 = "c3d754e8af0f7a05ab90190603ee1fcf410ab7add9096e7ef2ccb7ea570182b9"
SOURCE_HYPOTHESIS_RUNTIME_SHA256 = "fa5abef6f8f87deeda8e9e083d067611b18b0038b07d040ef1363582658fdac3"

SOURCE_BELIEF_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
SOURCE_HYPOTHESIS_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
LEDGER_RECORDS_INPUT_AUTHORITY = "EXPLICIT_CALLER_SUPPLIED_VERIFIED_SNAPSHOT"
K7_I_PROVES_LEDGER_SNAPSHOT_IS_LATEST = False
K7_I_PROVES_NO_NEWER_LEDGER_STATE_EXISTS = False
APPEND_TIME_SOURCE_REVALIDATION = "MANDATORY_AGAINST_APPEND_CALL_SOURCE_SNAPSHOT"

MEMORY_HASH_CHAIN_INTEGRITY = "STRUCTURAL_CONTENT_AND_ORDER_INTEGRITY"
MEMORY_HASH_CHAIN_PROVES_HISTORICAL_AUTHENTICITY = False
MEMORY_HASH_CHAIN_PROVES_RECORD_CREATED_BY_K7_I = False
PERSISTED_SOURCE_BINDING_HISTORICAL_AUTHENTICITY = "NOT_PROVEN_BY_HASH_CHAIN_ALONE"

PERSISTED_MEMORY_BYTES = "CANONICAL_UTF8_JSONL_ONLY"
LOCAL_APPEND_SERIALIZATION = "MANDATORY"
LOCAL_APPEND_SERIALIZATION_SCOPE = "COOPERATING_K7_I_WRITERS_ON_THE_SAME_OPENED_LOG"
MULTIAGENT_CONFLICT_RECONCILIATION = "NOT_CLAIMED_IN_K7-I"
CRASH_ATOMIC_APPEND = "NOT_CLAIMED_IN_K7-I-v1"
EXTERNAL_NONCOOPERATIVE_PATH_REPLACEMENT_SAFETY = "NOT_CLAIMED"

CANONICAL_POLICY_CREATION = "FORBIDDEN"
AUTOMATIC_POLICY_PROMOTION = False
AUTOMATIC_LEARNING = False
DEFAULT_MEMORY_PATH = None
LIVE_MEMORY_STORE_CREATED = False
MODEL_INFERENCE = "NO"
NETWORK = "NO"
ACTION_AUTHORITY = "NONE"
SYSTEM_ALIVE_LOCAL = "NOT_YET"

POSITIVE_REFRESH_AUTHORITY = "NOT_IMPLEMENTED_IN_K7-I-v1"
LEDGER_SEQUENCE_IS_FRESHNESS = False
POST_CAPTURE_OBSERVED_RECORD_ALONE_SATISFIES_REFRESH = False
K7_F_REVALIDATION_IS_TEMPORAL_FRESHNESS = False
FRESHNESS_POLICY_AUTHORITY = "EXPLICIT_CALLER_ASSERTION"
FRESHNESS_POLICY_SEMANTIC_SUITABILITY_VERIFIED_BY_K7_I = False

CANDIDATE_HAS_SCHEMA_FIELD = False
CONTENT_HASH_SCHEMA_SOURCE = "RUNTIME_LOCKED_SCHEMA_ID_CONSTANT"
PROJECT_SEMANTIC_BODY_AUTHORITY = "EXPLICIT_CALLER_ASSERTION"
PROJECT_SEMANTIC_SOURCE_BINDING_AUTHORITY = "K7-F_DERIVED_FROM_APPEND_CALL_SNAPSHOT"
EPISODIC_BODY_AUTHORITY = "EXPLICIT_CALLER_ASSERTION"
EPISODIC_SOURCE_BINDING_AUTHORITY = "K7-H_DERIVED_FROM_APPEND_CALL_SNAPSHOT"
PROCEDURAL_EPISODE_REFERENCE_AUTHORITY = "CALLER_SELECTED_REFERENCES"
PROCEDURAL_EPISODE_REFERENCE_HISTORICAL_AUTHENTICITY = "NOT_VERIFIED_BY_K7-I"

_MEMORY_CLASSES = ("EPISODIC_MEMORY", "PROJECT_SEMANTIC_MEMORY", "PROCEDURAL_CANDIDATE")
_PROJECT_POLICIES = ("REVALIDATE_BEFORE_USE", "REFRESH_BEFORE_USE")
_DECISION_KINDS = ("GATHER_INFORMATION", "PLAN_ACTION", "STOP_UNCERTAINTY")

_CANDIDATE_FIELDS = frozenset({
    "memory_class",
    "memory_id",
    "body",
    "source_binding",
    "use_policy",
    "content_sha256",
})
_RECORD_FIELDS = frozenset(set(_CANDIDATE_FIELDS) | {
    "schema",
    "sequence",
    "previous_record_sha256",
    "record_sha256",
})
_EPISODIC_BODY_FIELDS = frozenset({
    "episode_key", "event_kind", "summary", "outcome", "artifact_refs",
})
_EPISODIC_SOURCE_FIELDS = frozenset({
    "source_schema",
    "task_id",
    "origin_id",
    "hypothesis_state_sha256",
    "belief_view_sha256",
    "goal_chain_sha256",
    "decision_kind",
    "uncertainty_present",
})
_PROJECT_BODY_FIELDS = frozenset({"project_key", "claim_key", "claim_id"})
_PROJECT_SOURCE_FIELDS = frozenset({
    "source_schema",
    "ledger_head_sha256",
    "ledger_record_count",
    "statement",
    "candidate_record_entry_sha256s",
    "qualified_record_entry_sha256s",
})
_PROCEDURAL_BODY_FIELDS = frozenset({"procedure_key", "statement", "limitations"})
_PROCEDURAL_SOURCE_FIELDS = frozenset({"supporting_episode_record_sha256s"})
_VIEW_FIELDS = frozenset({
    "schema",
    "memory_head_sha256",
    "memory_record_count",
    "episodic_memory",
    "revalidated_project_semantic_memory",
    "stale_project_semantic_memory",
    "refresh_required_project_semantic_memory",
    "procedural_candidates",
    "stale_memory_present",
    "refresh_required_present",
})

_SCHEMA_JSON = '{"$defs":{"candidate":{"additionalProperties":false,"allOf":[{"if":{"properties":{"memory_class":{"const":"EPISODIC_MEMORY"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/episodic_body"},"source_binding":{"$ref":"#/$defs/episodic_source_binding"},"use_policy":{"const":"HISTORICAL_ONLY"}}}},{"if":{"properties":{"memory_class":{"const":"PROJECT_SEMANTIC_MEMORY"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/project_semantic_body"},"source_binding":{"$ref":"#/$defs/project_semantic_source_binding"},"use_policy":{"enum":["REVALIDATE_BEFORE_USE","REFRESH_BEFORE_USE"]}}}},{"if":{"properties":{"memory_class":{"const":"PROCEDURAL_CANDIDATE"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/procedural_body"},"source_binding":{"$ref":"#/$defs/procedural_source_binding"},"use_policy":{"const":"PROPOSAL_ONLY"}}}}],"properties":{"body":{},"content_sha256":{"$ref":"#/$defs/sha256"},"memory_class":{"enum":["EPISODIC_MEMORY","PROJECT_SEMANTIC_MEMORY","PROCEDURAL_CANDIDATE"],"type":"string"},"memory_id":{"$ref":"#/$defs/sha256"},"source_binding":{},"use_policy":{"enum":["HISTORICAL_ONLY","REVALIDATE_BEFORE_USE","REFRESH_BEFORE_USE","PROPOSAL_ONLY"],"type":"string"}},"required":["memory_class","memory_id","body","source_binding","use_policy","content_sha256"],"type":"object"},"episodic_body":{"additionalProperties":false,"properties":{"artifact_refs":{"$ref":"#/$defs/nonblank_list"},"episode_key":{"$ref":"#/$defs/nonblank"},"event_kind":{"$ref":"#/$defs/nonblank"},"outcome":{"$ref":"#/$defs/nonblank"},"summary":{"$ref":"#/$defs/nonblank"}},"required":["episode_key","event_kind","summary","outcome","artifact_refs"],"type":"object"},"episodic_source_binding":{"additionalProperties":false,"properties":{"belief_view_sha256":{"$ref":"#/$defs/sha256"},"decision_kind":{"enum":["GATHER_INFORMATION","PLAN_ACTION","STOP_UNCERTAINTY"],"type":"string"},"goal_chain_sha256":{"$ref":"#/$defs/sha256"},"hypothesis_state_sha256":{"$ref":"#/$defs/sha256"},"origin_id":{"$ref":"#/$defs/nonblank"},"source_schema":{"const":"gg.hypothesis-protocol.v1","type":"string"},"task_id":{"$ref":"#/$defs/nonblank"},"uncertainty_present":{"type":"boolean"}},"required":["source_schema","task_id","origin_id","hypothesis_state_sha256","belief_view_sha256","goal_chain_sha256","decision_kind","uncertainty_present"],"type":"object"},"finalized_record":{"additionalProperties":false,"allOf":[{"if":{"properties":{"memory_class":{"const":"EPISODIC_MEMORY"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/episodic_body"},"source_binding":{"$ref":"#/$defs/episodic_source_binding"},"use_policy":{"const":"HISTORICAL_ONLY"}}}},{"if":{"properties":{"memory_class":{"const":"PROJECT_SEMANTIC_MEMORY"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/project_semantic_body"},"source_binding":{"$ref":"#/$defs/project_semantic_source_binding"},"use_policy":{"enum":["REVALIDATE_BEFORE_USE","REFRESH_BEFORE_USE"]}}}},{"if":{"properties":{"memory_class":{"const":"PROCEDURAL_CANDIDATE"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/procedural_body"},"source_binding":{"$ref":"#/$defs/procedural_source_binding"},"use_policy":{"const":"PROPOSAL_ONLY"}}}}],"properties":{"body":{},"content_sha256":{"$ref":"#/$defs/sha256"},"memory_class":{"enum":["EPISODIC_MEMORY","PROJECT_SEMANTIC_MEMORY","PROCEDURAL_CANDIDATE"],"type":"string"},"memory_id":{"$ref":"#/$defs/sha256"},"previous_record_sha256":{"$ref":"#/$defs/nullable_sha256"},"record_sha256":{"$ref":"#/$defs/sha256"},"schema":{"const":"gg.memory-discipline-record.v1","type":"string"},"sequence":{"minimum":0,"type":"integer"},"source_binding":{},"use_policy":{"enum":["HISTORICAL_ONLY","REVALIDATE_BEFORE_USE","REFRESH_BEFORE_USE","PROPOSAL_ONLY"],"type":"string"}},"required":["schema","sequence","memory_class","memory_id","body","source_binding","use_policy","content_sha256","previous_record_sha256","record_sha256"],"type":"object"},"memory_view":{"$id":"gg.memory-discipline-view.v1","additionalProperties":false,"properties":{"episodic_memory":{"items":{"$ref":"#/$defs/finalized_record"},"type":"array"},"memory_head_sha256":{"$ref":"#/$defs/nullable_sha256"},"memory_record_count":{"minimum":0,"type":"integer"},"procedural_candidates":{"items":{"$ref":"#/$defs/finalized_record"},"type":"array"},"refresh_required_present":{"type":"boolean"},"refresh_required_project_semantic_memory":{"items":{"$ref":"#/$defs/finalized_record"},"type":"array"},"revalidated_project_semantic_memory":{"items":{"$ref":"#/$defs/finalized_record"},"type":"array"},"schema":{"const":"gg.memory-discipline-view.v1","type":"string"},"stale_memory_present":{"type":"boolean"},"stale_project_semantic_memory":{"items":{"$ref":"#/$defs/finalized_record"},"type":"array"}},"required":["schema","memory_head_sha256","memory_record_count","episodic_memory","revalidated_project_semantic_memory","stale_project_semantic_memory","refresh_required_project_semantic_memory","procedural_candidates","stale_memory_present","refresh_required_present"],"type":"object"},"nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"nonblank_list":{"items":{"$ref":"#/$defs/nonblank"},"type":"array","uniqueItems":true},"nullable_sha256":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]},"procedural_body":{"additionalProperties":false,"properties":{"limitations":{"$ref":"#/$defs/nonblank_list"},"procedure_key":{"$ref":"#/$defs/nonblank"},"statement":{"$ref":"#/$defs/nonblank"}},"required":["procedure_key","statement","limitations"],"type":"object"},"procedural_source_binding":{"additionalProperties":false,"properties":{"supporting_episode_record_sha256s":{"items":{"$ref":"#/$defs/sha256"},"minItems":1,"type":"array","uniqueItems":true}},"required":["supporting_episode_record_sha256s"],"type":"object"},"project_semantic_body":{"additionalProperties":false,"properties":{"claim_id":{"$ref":"#/$defs/sha256"},"claim_key":{"$ref":"#/$defs/nonblank"},"project_key":{"$ref":"#/$defs/nonblank"}},"required":["project_key","claim_key","claim_id"],"type":"object"},"project_semantic_source_binding":{"additionalProperties":false,"properties":{"candidate_record_entry_sha256s":{"items":{"$ref":"#/$defs/sha256"},"minItems":1,"type":"array","uniqueItems":true},"ledger_head_sha256":{"$ref":"#/$defs/nullable_sha256"},"ledger_record_count":{"minimum":0,"type":"integer"},"qualified_record_entry_sha256s":{"items":{"$ref":"#/$defs/sha256"},"minItems":1,"type":"array","uniqueItems":true},"source_schema":{"const":"gg.belief-view.v1","type":"string"},"statement":{"$ref":"#/$defs/nonblank"}},"required":["source_schema","ledger_head_sha256","ledger_record_count","statement","candidate_record_entry_sha256s","qualified_record_entry_sha256s"],"type":"object"},"sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"sha256_list":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true}},"$id":"gg.memory-discipline-record.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"allOf":[{"if":{"properties":{"memory_class":{"const":"EPISODIC_MEMORY"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/episodic_body"},"source_binding":{"$ref":"#/$defs/episodic_source_binding"},"use_policy":{"const":"HISTORICAL_ONLY"}}}},{"if":{"properties":{"memory_class":{"const":"PROJECT_SEMANTIC_MEMORY"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/project_semantic_body"},"source_binding":{"$ref":"#/$defs/project_semantic_source_binding"},"use_policy":{"enum":["REVALIDATE_BEFORE_USE","REFRESH_BEFORE_USE"]}}}},{"if":{"properties":{"memory_class":{"const":"PROCEDURAL_CANDIDATE"}},"required":["memory_class"]},"then":{"properties":{"body":{"$ref":"#/$defs/procedural_body"},"source_binding":{"$ref":"#/$defs/procedural_source_binding"},"use_policy":{"const":"PROPOSAL_ONLY"}}}}],"properties":{"body":{},"content_sha256":{"$ref":"#/$defs/sha256"},"memory_class":{"enum":["EPISODIC_MEMORY","PROJECT_SEMANTIC_MEMORY","PROCEDURAL_CANDIDATE"],"type":"string"},"memory_id":{"$ref":"#/$defs/sha256"},"previous_record_sha256":{"$ref":"#/$defs/nullable_sha256"},"record_sha256":{"$ref":"#/$defs/sha256"},"schema":{"const":"gg.memory-discipline-record.v1","type":"string"},"sequence":{"minimum":0,"type":"integer"},"source_binding":{},"use_policy":{"enum":["HISTORICAL_ONLY","REVALIDATE_BEFORE_USE","REFRESH_BEFORE_USE","PROPOSAL_ONLY"],"type":"string"}},"required":["schema","sequence","memory_class","memory_id","body","source_binding","use_policy","content_sha256","previous_record_sha256","record_sha256"],"title":"GG Memory Discipline Finalized Record v1","type":"object"}'


class MemoryDisciplineError(ValueError):
    def __init__(self, code: str, cause_code: str | None = None) -> None:
        message = code if cause_code is None else code + ":" + cause_code
        super().__init__(message)
        self.code = code
        self.cause_code = cause_code


def _fail(code: str, cause_code: str | None = None) -> None:
    raise MemoryDisciplineError(code, cause_code)


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
        _fail("CANONICAL_JSON_INVALID", type(exc).__name__)
    return (text + "\n").encode("utf-8")


def schema_document() -> dict[str, Any]:
    return json.loads(_SCHEMA_JSON)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _nonblank(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        _fail(code)
    return value


def _sha_value(value: Any, code: str) -> str:
    if not _is_sha(value):
        _fail(code)
    return value


def _closed(value: Any, fields: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value.keys()) != fields:
        _fail(code)
    return value


def _unique_sorted_strings(
    value: Any,
    code: str,
    *,
    require_nonempty: bool = False,
    sha256: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        _fail(code)
    result: list[str] = []
    for item in value:
        if sha256:
            _sha_value(item, code)
        else:
            _nonblank(item, code)
        result.append(item)
    if require_nonempty and not result:
        _fail(code)
    if len(result) != len(set(result)):
        _fail(code)
    return sorted(result)


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
    if _sha256(captured) != expected_sha256:
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
        private_name="_gg_memory_bound_belief_view",
        authority_code="SOURCE_BELIEF_AUTHORITY_INVALID",
    )


def _hypothesis_authority() -> dict[str, Any]:
    return _load_bound_authority(
        path=_authority_path("gg_hypothesis_protocol.py"),
        expected_sha256=SOURCE_HYPOTHESIS_RUNTIME_SHA256,
        schema_id=SOURCE_HYPOTHESIS_SCHEMA_ID,
        required_callables=("canonical_json", "validate_state"),
        error_class_name="HypothesisProtocolError",
        private_name="_gg_memory_bound_hypothesis_protocol",
        authority_code="SOURCE_HYPOTHESIS_AUTHORITY_INVALID",
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
        raise MemoryDisciplineError(outer_code, str(exc)) from exc


def _normalized_artifact_refs(value: Any) -> list[str]:
    return _unique_sorted_strings(value, "EPISODIC_ARTIFACT_REFS_INVALID")


def _normalized_limitations(value: Any) -> list[str]:
    return _unique_sorted_strings(value, "PROCEDURAL_LIMITATIONS_INVALID")


def memory_id(definition_semantics: dict[str, Any]) -> str:
    if not isinstance(definition_semantics, dict):
        _fail("MEMORY_ID_SEMANTICS_INVALID")
    memory_class = definition_semantics.get("memory_class")
    if memory_class == "EPISODIC_MEMORY":
        required = frozenset({"memory_class", "episode_key", "task_id", "origin_id"})
        _closed(definition_semantics, required, "MEMORY_ID_SEMANTICS_INVALID")
        normalized = {
            "memory_class": memory_class,
            "episode_key": _nonblank(definition_semantics["episode_key"], "EPISODE_KEY_INVALID"),
            "task_id": _nonblank(definition_semantics["task_id"], "TASK_ID_INVALID"),
            "origin_id": _nonblank(definition_semantics["origin_id"], "ORIGIN_ID_INVALID"),
        }
    elif memory_class == "PROJECT_SEMANTIC_MEMORY":
        required = frozenset({
            "memory_class", "project_key", "claim_key", "claim_id", "use_policy",
        })
        _closed(definition_semantics, required, "MEMORY_ID_SEMANTICS_INVALID")
        policy = definition_semantics["use_policy"]
        if policy not in _PROJECT_POLICIES:
            _fail("PROJECT_USE_POLICY_INVALID")
        normalized = {
            "memory_class": memory_class,
            "project_key": _nonblank(definition_semantics["project_key"], "PROJECT_KEY_INVALID"),
            "claim_key": _nonblank(definition_semantics["claim_key"], "CLAIM_KEY_INVALID"),
            "claim_id": _sha_value(definition_semantics["claim_id"], "CLAIM_ID_INVALID"),
            "use_policy": policy,
        }
    elif memory_class == "PROCEDURAL_CANDIDATE":
        required = frozenset({"memory_class", "procedure_key", "statement", "limitations"})
        _closed(definition_semantics, required, "MEMORY_ID_SEMANTICS_INVALID")
        normalized = {
            "memory_class": memory_class,
            "procedure_key": _nonblank(definition_semantics["procedure_key"], "PROCEDURE_KEY_INVALID"),
            "statement": _nonblank(definition_semantics["statement"], "PROCEDURAL_STATEMENT_INVALID"),
            "limitations": _unique_sorted_strings(
                definition_semantics["limitations"],
                "PROCEDURAL_LIMITATIONS_INVALID",
            ),
        }
    else:
        _fail("MEMORY_CLASS_INVALID")
    return _sha256(
        b"gg.memory-discipline.memory.v1\n"
        + canonical_json(normalized)
    )


def _content_sha256(candidate_without_content: dict[str, Any]) -> str:
    payload = {
        "schema": CONTENT_SCHEMA_ID,
        "memory_class": candidate_without_content["memory_class"],
        "memory_id": candidate_without_content["memory_id"],
        "body": candidate_without_content["body"],
        "source_binding": candidate_without_content["source_binding"],
        "use_policy": candidate_without_content["use_policy"],
    }
    return _sha256(
        b"gg.memory-discipline.content.v1\n"
        + canonical_json(payload)
    )


def _record_sha256(record_without_hash: dict[str, Any]) -> str:
    payload = {
        "schema": record_without_hash["schema"],
        "sequence": record_without_hash["sequence"],
        "memory_class": record_without_hash["memory_class"],
        "memory_id": record_without_hash["memory_id"],
        "body": record_without_hash["body"],
        "source_binding": record_without_hash["source_binding"],
        "use_policy": record_without_hash["use_policy"],
        "content_sha256": record_without_hash["content_sha256"],
        "previous_record_sha256": record_without_hash["previous_record_sha256"],
    }
    return _sha256(
        b"gg.memory-discipline.record.v1\n"
        + canonical_json(payload)
    )


def _normalize_episodic_body(value: Any) -> dict[str, Any]:
    body = _closed(copy.deepcopy(value), _EPISODIC_BODY_FIELDS, "EPISODIC_BODY_INVALID")
    return {
        "episode_key": _nonblank(body["episode_key"], "EPISODE_KEY_INVALID"),
        "event_kind": _nonblank(body["event_kind"], "EPISODIC_EVENT_KIND_INVALID"),
        "summary": _nonblank(body["summary"], "EPISODIC_SUMMARY_INVALID"),
        "outcome": _nonblank(body["outcome"], "EPISODIC_OUTCOME_INVALID"),
        "artifact_refs": _normalized_artifact_refs(body["artifact_refs"]),
    }


def _normalize_episodic_source(value: Any) -> dict[str, Any]:
    source = _closed(copy.deepcopy(value), _EPISODIC_SOURCE_FIELDS, "EPISODIC_SOURCE_BINDING_INVALID")
    if source["source_schema"] != SOURCE_HYPOTHESIS_SCHEMA_ID:
        _fail("EPISODIC_SOURCE_BINDING_INVALID")
    if source["decision_kind"] not in _DECISION_KINDS:
        _fail("EPISODIC_SOURCE_BINDING_INVALID")
    if not isinstance(source["uncertainty_present"], bool):
        _fail("EPISODIC_SOURCE_BINDING_INVALID")
    return {
        "source_schema": SOURCE_HYPOTHESIS_SCHEMA_ID,
        "task_id": _nonblank(source["task_id"], "EPISODIC_SOURCE_BINDING_INVALID"),
        "origin_id": _nonblank(source["origin_id"], "EPISODIC_SOURCE_BINDING_INVALID"),
        "hypothesis_state_sha256": _sha_value(source["hypothesis_state_sha256"], "EPISODIC_SOURCE_BINDING_INVALID"),
        "belief_view_sha256": _sha_value(source["belief_view_sha256"], "EPISODIC_SOURCE_BINDING_INVALID"),
        "goal_chain_sha256": _sha_value(source["goal_chain_sha256"], "EPISODIC_SOURCE_BINDING_INVALID"),
        "decision_kind": source["decision_kind"],
        "uncertainty_present": source["uncertainty_present"],
    }


def _normalize_project_body(value: Any) -> dict[str, Any]:
    body = _closed(copy.deepcopy(value), _PROJECT_BODY_FIELDS, "PROJECT_SEMANTIC_BODY_INVALID")
    return {
        "project_key": _nonblank(body["project_key"], "PROJECT_KEY_INVALID"),
        "claim_key": _nonblank(body["claim_key"], "CLAIM_KEY_INVALID"),
        "claim_id": _sha_value(body["claim_id"], "CLAIM_ID_INVALID"),
    }


def _normalize_project_source(value: Any) -> dict[str, Any]:
    source = _closed(copy.deepcopy(value), _PROJECT_SOURCE_FIELDS, "PROJECT_SEMANTIC_SOURCE_BINDING_INVALID")
    if source["source_schema"] != SOURCE_BELIEF_SCHEMA_ID:
        _fail("PROJECT_SEMANTIC_SOURCE_BINDING_INVALID")
    head = source["ledger_head_sha256"]
    if head is not None:
        _sha_value(head, "PROJECT_SEMANTIC_SOURCE_BINDING_INVALID")
    count = source["ledger_record_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        _fail("PROJECT_SEMANTIC_SOURCE_BINDING_INVALID")
    candidate_refs = _unique_sorted_strings(
        source["candidate_record_entry_sha256s"],
        "PROJECT_SEMANTIC_SOURCE_BINDING_INVALID",
        require_nonempty=True,
        sha256=True,
    )
    qualified_refs = _unique_sorted_strings(
        source["qualified_record_entry_sha256s"],
        "PROJECT_SEMANTIC_SOURCE_BINDING_INVALID",
        require_nonempty=True,
        sha256=True,
    )
    if not set(qualified_refs).issubset(candidate_refs):
        _fail("PROJECT_SEMANTIC_SOURCE_BINDING_INVALID")
    return {
        "source_schema": SOURCE_BELIEF_SCHEMA_ID,
        "ledger_head_sha256": head,
        "ledger_record_count": count,
        "statement": _nonblank(source["statement"], "PROJECT_SEMANTIC_SOURCE_BINDING_INVALID"),
        "candidate_record_entry_sha256s": candidate_refs,
        "qualified_record_entry_sha256s": qualified_refs,
    }


def _normalize_procedural_body(value: Any) -> dict[str, Any]:
    body = _closed(copy.deepcopy(value), _PROCEDURAL_BODY_FIELDS, "PROCEDURAL_BODY_INVALID")
    return {
        "procedure_key": _nonblank(body["procedure_key"], "PROCEDURE_KEY_INVALID"),
        "statement": _nonblank(body["statement"], "PROCEDURAL_STATEMENT_INVALID"),
        "limitations": _normalized_limitations(body["limitations"]),
    }


def _normalize_procedural_source(value: Any) -> dict[str, Any]:
    source = _closed(copy.deepcopy(value), _PROCEDURAL_SOURCE_FIELDS, "PROCEDURAL_SOURCE_BINDING_INVALID")
    return {
        "supporting_episode_record_sha256s": _unique_sorted_strings(
            source["supporting_episode_record_sha256s"],
            "PROCEDURAL_SOURCE_BINDING_INVALID",
            require_nonempty=True,
            sha256=True,
        )
    }


def _candidate_identity_semantics(candidate: dict[str, Any]) -> dict[str, Any]:
    memory_class = candidate["memory_class"]
    if memory_class == "EPISODIC_MEMORY":
        return {
            "memory_class": memory_class,
            "episode_key": candidate["body"]["episode_key"],
            "task_id": candidate["source_binding"]["task_id"],
            "origin_id": candidate["source_binding"]["origin_id"],
        }
    if memory_class == "PROJECT_SEMANTIC_MEMORY":
        return {
            "memory_class": memory_class,
            "project_key": candidate["body"]["project_key"],
            "claim_key": candidate["body"]["claim_key"],
            "claim_id": candidate["body"]["claim_id"],
            "use_policy": candidate["use_policy"],
        }
    if memory_class == "PROCEDURAL_CANDIDATE":
        return {
            "memory_class": memory_class,
            "procedure_key": candidate["body"]["procedure_key"],
            "statement": candidate["body"]["statement"],
            "limitations": candidate["body"]["limitations"],
        }
    _fail("MEMORY_CLASS_INVALID")


def _verify_procedural_refs(candidate: dict[str, Any], previous_records: list[dict[str, Any]]) -> None:
    refs = candidate["source_binding"]["supporting_episode_record_sha256s"]
    by_sha = {record["record_sha256"]: record for record in previous_records}
    for ref in refs:
        record = by_sha.get(ref)
        if record is None or record["memory_class"] != "EPISODIC_MEMORY":
            _fail("PROCEDURAL_EPISODE_REFERENCE_INVALID")


def _normalize_candidate_no_chain(
    candidate: Any,
    previous_records: list[dict[str, Any]],
) -> dict[str, Any]:
    value = _closed(copy.deepcopy(candidate), _CANDIDATE_FIELDS, "MEMORY_CANDIDATE_INVALID")
    memory_class = value["memory_class"]
    if memory_class not in _MEMORY_CLASSES:
        _fail("MEMORY_CLASS_INVALID")
    if memory_class == "EPISODIC_MEMORY":
        body = _normalize_episodic_body(value["body"])
        source = _normalize_episodic_source(value["source_binding"])
        if value["use_policy"] != "HISTORICAL_ONLY":
            _fail("EPISODIC_USE_POLICY_INVALID")
        policy = "HISTORICAL_ONLY"
    elif memory_class == "PROJECT_SEMANTIC_MEMORY":
        body = _normalize_project_body(value["body"])
        source = _normalize_project_source(value["source_binding"])
        if value["use_policy"] not in _PROJECT_POLICIES:
            _fail("PROJECT_USE_POLICY_INVALID")
        policy = value["use_policy"]
    else:
        body = _normalize_procedural_body(value["body"])
        source = _normalize_procedural_source(value["source_binding"])
        if value["use_policy"] != "PROPOSAL_ONLY":
            _fail("PROCEDURAL_USE_POLICY_INVALID")
        policy = "PROPOSAL_ONLY"

    normalized = {
        "memory_class": memory_class,
        "memory_id": value["memory_id"],
        "body": body,
        "source_binding": source,
        "use_policy": policy,
        "content_sha256": value["content_sha256"],
    }
    expected_id = memory_id(_candidate_identity_semantics(normalized))
    if not _is_sha(normalized["memory_id"]) or normalized["memory_id"] != expected_id:
        _fail("MEMORY_ID_MISMATCH")
    without_content = {key: normalized[key] for key in normalized if key != "content_sha256"}
    expected_content = _content_sha256(without_content)
    if not _is_sha(normalized["content_sha256"]) or normalized["content_sha256"] != expected_content:
        _fail("MEMORY_CONTENT_SHA256_MISMATCH")
    if memory_class == "PROCEDURAL_CANDIDATE":
        _verify_procedural_refs(normalized, previous_records)
    return normalized


def validate_candidate(
    candidate: Any,
    previous_records: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(previous_records, list):
        _fail("MEMORY_CHAIN_INVALID")
    verified = verify_chain(copy.deepcopy(previous_records))
    return _normalize_candidate_no_chain(copy.deepcopy(candidate), verified)


def _candidate_from_parts(
    *,
    memory_class: str,
    body: dict[str, Any],
    source_binding: dict[str, Any],
    use_policy: str,
) -> dict[str, Any]:
    provisional = {
        "memory_class": memory_class,
        "memory_id": "0" * 64,
        "body": copy.deepcopy(body),
        "source_binding": copy.deepcopy(source_binding),
        "use_policy": use_policy,
        "content_sha256": "0" * 64,
    }
    if memory_class == "EPISODIC_MEMORY":
        provisional["body"] = _normalize_episodic_body(provisional["body"])
        provisional["source_binding"] = _normalize_episodic_source(provisional["source_binding"])
    elif memory_class == "PROJECT_SEMANTIC_MEMORY":
        provisional["body"] = _normalize_project_body(provisional["body"])
        provisional["source_binding"] = _normalize_project_source(provisional["source_binding"])
        if use_policy not in _PROJECT_POLICIES:
            _fail("PROJECT_USE_POLICY_INVALID")
    elif memory_class == "PROCEDURAL_CANDIDATE":
        provisional["body"] = _normalize_procedural_body(provisional["body"])
        provisional["source_binding"] = _normalize_procedural_source(provisional["source_binding"])
    else:
        _fail("MEMORY_CLASS_INVALID")
    provisional["memory_id"] = memory_id(_candidate_identity_semantics(provisional))
    without_content = {key: provisional[key] for key in provisional if key != "content_sha256"}
    provisional["content_sha256"] = _content_sha256(without_content)
    return provisional


def make_episodic_candidate(
    *,
    episode_key: str,
    event_kind: str,
    summary: str,
    outcome: str,
    artifact_refs: list[str],
    hypothesis_state: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    hypothesis = _hypothesis_authority()
    state = _call_source(
        hypothesis,
        "validate_state",
        "HypothesisProtocolError",
        "SOURCE_HYPOTHESIS_INVALID",
        copy.deepcopy(hypothesis_state),
        copy.deepcopy(ledger_records),
        copy.deepcopy(requested_claim_keys),
        copy.deepcopy(goal_chain),
        copy.deepcopy(source_envelope),
    )
    state_bytes = _call_source(
        hypothesis,
        "canonical_json",
        "HypothesisProtocolError",
        "SOURCE_HYPOTHESIS_INVALID",
        copy.deepcopy(state),
    )
    if not isinstance(state_bytes, bytes):
        _fail("SOURCE_HYPOTHESIS_INVALID", "CANONICAL_JSON_NOT_BYTES")
    try:
        decision_kind = state["decision"]["kind"]
        source_binding = {
            "source_schema": state["schema"],
            "task_id": state["task_id"],
            "origin_id": state["origin_id"],
            "hypothesis_state_sha256": _sha256(state_bytes),
            "belief_view_sha256": state["belief_view_sha256"],
            "goal_chain_sha256": state["goal_chain_sha256"],
            "decision_kind": decision_kind,
            "uncertainty_present": state["uncertainty_present"],
        }
    except (KeyError, TypeError) as exc:
        _fail("SOURCE_HYPOTHESIS_INVALID", "STATE_SURFACE:" + type(exc).__name__)
    body = {
        "episode_key": episode_key,
        "event_kind": event_kind,
        "summary": summary,
        "outcome": outcome,
        "artifact_refs": artifact_refs,
    }
    return _candidate_from_parts(
        memory_class="EPISODIC_MEMORY",
        body=body,
        source_binding=source_binding,
        use_policy="HISTORICAL_ONLY",
    )


def _project_qualified_source(
    *,
    project_key: str,
    claim_key: str,
    claim_id: str,
    use_policy: str,
    ledger_records: list[dict[str, Any]],
    require_qualified: bool,
) -> tuple[dict[str, Any], bool]:
    _nonblank(project_key, "PROJECT_KEY_INVALID")
    _nonblank(claim_key, "CLAIM_KEY_INVALID")
    _sha_value(claim_id, "CLAIM_ID_INVALID")
    if use_policy not in _PROJECT_POLICIES:
        _fail("PROJECT_USE_POLICY_INVALID")
    belief = _belief_authority()
    view = _call_source(
        belief,
        "reconstruct_belief_view",
        "BeliefViewError",
        "SOURCE_BELIEF_INVALID",
        copy.deepcopy(ledger_records),
        [claim_key],
    )
    _call_source(
        belief,
        "validate_view",
        "BeliefViewError",
        "SOURCE_BELIEF_INVALID",
        copy.deepcopy(view),
    )
    try:
        claim_views = view["claim_views"]
        selected = next(item for item in claim_views if item["claim_key"] == claim_key)
    except (KeyError, TypeError, StopIteration) as exc:
        _fail("SOURCE_BELIEF_INVALID", "VIEW_SURFACE:" + type(exc).__name__)
    qualified = False
    source_binding: dict[str, Any] | None = None
    if selected["state"] == "UNCONTESTED" and len(selected["candidates"]) == 1:
        candidate = selected["candidates"][0]
        if candidate["claim_id"] == claim_id:
            entries = sorted({ref["entry_sha256"] for ref in candidate["record_refs"]})
            qualifying = sorted({
                ref["entry_sha256"]
                for ref in candidate["record_refs"]
                if ref["epistemic_class"] in ("OBSERVED", "VERIFIED")
            })
            contradicted = any(
                relation["relation_type"] == "CONTRADICTS"
                and (
                    relation["subject_entry_sha256"] in entries
                    or relation["object_entry_sha256"] in entries
                )
                for relation in view["relevant_relations"]
            )
            if qualifying and not contradicted:
                qualified = True
                source_binding = {
                    "source_schema": view["schema"],
                    "ledger_head_sha256": view["ledger_head_sha256"],
                    "ledger_record_count": view["ledger_record_count"],
                    "statement": candidate["statement"],
                    "candidate_record_entry_sha256s": entries,
                    "qualified_record_entry_sha256s": qualifying,
                }
    if not qualified:
        if require_qualified:
            _fail("PROJECT_SEMANTIC_SOURCE_NOT_QUALIFIED")
        return {}, False
    assert source_binding is not None
    return source_binding, True


def make_project_semantic_candidate(
    *,
    project_key: str,
    claim_key: str,
    claim_id: str,
    use_policy: str,
    ledger_records: list[dict[str, Any]],
) -> dict[str, Any]:
    source_binding, qualified = _project_qualified_source(
        project_key=project_key,
        claim_key=claim_key,
        claim_id=claim_id,
        use_policy=use_policy,
        ledger_records=copy.deepcopy(ledger_records),
        require_qualified=True,
    )
    if not qualified:
        _fail("PROJECT_SEMANTIC_SOURCE_NOT_QUALIFIED")
    body = {
        "project_key": project_key,
        "claim_key": claim_key,
        "claim_id": claim_id,
    }
    return _candidate_from_parts(
        memory_class="PROJECT_SEMANTIC_MEMORY",
        body=body,
        source_binding=source_binding,
        use_policy=use_policy,
    )


def make_procedural_candidate(
    *,
    procedure_key: str,
    statement: str,
    limitations: list[str],
    supporting_episode_record_sha256s: list[str],
    previous_records: list[dict[str, Any]],
) -> dict[str, Any]:
    verified = verify_chain(copy.deepcopy(previous_records))
    body = {
        "procedure_key": procedure_key,
        "statement": statement,
        "limitations": limitations,
    }
    source = {
        "supporting_episode_record_sha256s": supporting_episode_record_sha256s,
    }
    candidate = _candidate_from_parts(
        memory_class="PROCEDURAL_CANDIDATE",
        body=body,
        source_binding=source,
        use_policy="PROPOSAL_ONLY",
    )
    _verify_procedural_refs(candidate, verified)
    return candidate


def _validate_finalized_record_no_chain(
    record: Any,
    previous_records: list[dict[str, Any]],
    expected_sequence: int,
    expected_previous: str | None,
) -> dict[str, Any]:
    value = _closed(copy.deepcopy(record), _RECORD_FIELDS, "MEMORY_RECORD_INVALID")
    if value["schema"] != SCHEMA_ID:
        _fail("MEMORY_RECORD_INVALID")
    sequence = value["sequence"]
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence != expected_sequence
    ):
        _fail("MEMORY_CHAIN_INVALID")
    previous = value["previous_record_sha256"]
    if previous is not None and not _is_sha(previous):
        _fail("MEMORY_CHAIN_INVALID")
    if previous != expected_previous:
        _fail("MEMORY_CHAIN_INVALID")
    candidate = {key: value[key] for key in _CANDIDATE_FIELDS}
    normalized_candidate = _normalize_candidate_no_chain(candidate, previous_records)
    without_record_hash = {
        "schema": SCHEMA_ID,
        "sequence": sequence,
        **copy.deepcopy(normalized_candidate),
        "previous_record_sha256": previous,
    }
    expected_hash = _record_sha256(without_record_hash)
    if not _is_sha(value["record_sha256"]) or value["record_sha256"] != expected_hash:
        _fail("MEMORY_CHAIN_INVALID")
    return {**without_record_hash, "record_sha256": expected_hash}


def verify_chain(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        _fail("MEMORY_CHAIN_INVALID")
    verified: list[dict[str, Any]] = []
    seen_content: set[str] = set()
    previous: str | None = None
    for sequence, record in enumerate(records):
        normalized = _validate_finalized_record_no_chain(
            record,
            verified,
            sequence,
            previous,
        )
        if normalized["content_sha256"] in seen_content:
            _fail("DUPLICATE_MEMORY_RECORD")
        seen_content.add(normalized["content_sha256"])
        verified.append(normalized)
        previous = normalized["record_sha256"]
    return verified


def finalize_record(
    candidate: dict[str, Any],
    sequence: int,
    previous_record_sha256: str | None,
    previous_records: list[dict[str, Any]],
) -> dict[str, Any]:
    verified = verify_chain(copy.deepcopy(previous_records))
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence != len(verified):
        _fail("MEMORY_SEQUENCE_INVALID")
    expected_previous = verified[-1]["record_sha256"] if verified else None
    if previous_record_sha256 != expected_previous:
        _fail("MEMORY_HEAD_MISMATCH")
    normalized = _normalize_candidate_no_chain(copy.deepcopy(candidate), verified)
    if any(record["content_sha256"] == normalized["content_sha256"] for record in verified):
        _fail("DUPLICATE_MEMORY_RECORD")
    provisional = {
        "schema": SCHEMA_ID,
        "sequence": sequence,
        **copy.deepcopy(normalized),
        "previous_record_sha256": previous_record_sha256,
    }
    return {**provisional, "record_sha256": _record_sha256(provisional)}


class _DuplicateKey(ValueError):
    pass


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def parse_jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    if not isinstance(data, bytes):
        _fail("MEMORY_CHAIN_INVALID", "BYTES_REQUIRED")
    if data == b"":
        return []
    if not data.endswith(b"\n"):
        _fail("MEMORY_CHAIN_INVALID", "NON_CANONICAL_MEMORY_JSONL")
    raw_rows = data.splitlines(keepends=True)
    if not raw_rows:
        _fail("MEMORY_CHAIN_INVALID", "NON_CANONICAL_MEMORY_JSONL")
    records: list[dict[str, Any]] = []
    for raw in raw_rows:
        if raw == b"\n" or not raw.endswith(b"\n"):
            _fail("MEMORY_CHAIN_INVALID", "NON_CANONICAL_MEMORY_JSONL")
        try:
            text = raw[:-1].decode("utf-8", errors="strict")
            parsed = json.loads(text, object_pairs_hook=_object_pairs_no_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey) as exc:
            _fail("MEMORY_CHAIN_INVALID", "NON_CANONICAL_MEMORY_JSONL:" + type(exc).__name__)
        if not isinstance(parsed, dict):
            _fail("MEMORY_CHAIN_INVALID", "NON_CANONICAL_MEMORY_JSONL")
        if canonical_json(parsed) != raw:
            _fail("MEMORY_CHAIN_INVALID", "NON_CANONICAL_MEMORY_JSONL")
        records.append(parsed)
    return verify_chain(records)


def _secure_read_bytes(path: pathlib.Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        _fail("MEMORY_PATH_INVALID", "OPEN_FAILED:" + type(exc).__name__)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _fail("MEMORY_PATH_INVALID", "NOT_REGULAR")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        data = b"".join(chunks)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or after.st_size != len(data)
        ):
            _fail("MEMORY_PATH_INVALID", "FILE_CHANGED_DURING_READ")
        return data
    finally:
        os.close(fd)


def read_chain(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    return parse_jsonl_bytes(_secure_read_bytes(pathlib.Path(path)))


def _rebuild_for_append(
    candidate: dict[str, Any],
    locked_records: list[dict[str, Any]],
    *,
    ledger_records: list[dict[str, Any]] | None,
    requested_claim_keys: list[str] | None,
    hypothesis_state: dict[str, Any] | None,
    goal_chain: dict[str, Any] | None,
    source_envelope: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = _normalize_candidate_no_chain(candidate, locked_records)
    memory_class = normalized["memory_class"]
    if memory_class == "EPISODIC_MEMORY":
        if (
            ledger_records is None
            or requested_claim_keys is None
            or hypothesis_state is None
            or goal_chain is None
            or source_envelope is None
        ):
            _fail("MEMORY_SOURCE_BINDING_INVALID", "EPISODIC_SOURCE_ARGUMENTS_REQUIRED")
        body = normalized["body"]
        expected = make_episodic_candidate(
            episode_key=body["episode_key"],
            event_kind=body["event_kind"],
            summary=body["summary"],
            outcome=body["outcome"],
            artifact_refs=body["artifact_refs"],
            hypothesis_state=hypothesis_state,
            ledger_records=ledger_records,
            requested_claim_keys=requested_claim_keys,
            goal_chain=goal_chain,
            source_envelope=source_envelope,
        )
    elif memory_class == "PROJECT_SEMANTIC_MEMORY":
        if ledger_records is None:
            _fail("MEMORY_SOURCE_BINDING_INVALID", "PROJECT_LEDGER_SNAPSHOT_REQUIRED")
        body = normalized["body"]
        expected = make_project_semantic_candidate(
            project_key=body["project_key"],
            claim_key=body["claim_key"],
            claim_id=body["claim_id"],
            use_policy=normalized["use_policy"],
            ledger_records=ledger_records,
        )
    else:
        body = normalized["body"]
        expected = make_procedural_candidate(
            procedure_key=body["procedure_key"],
            statement=body["statement"],
            limitations=body["limitations"],
            supporting_episode_record_sha256s=normalized["source_binding"]["supporting_episode_record_sha256s"],
            previous_records=locked_records,
        )
    if canonical_json(expected) != canonical_json(normalized):
        _fail("MEMORY_SOURCE_BINDING_INVALID")
    return expected


def _validate_storage_parent(path: pathlib.Path) -> pathlib.Path:
    if not path.is_absolute():
        path = path.absolute()
    parent = path.parent
    try:
        parent_info = parent.stat(follow_symlinks=False)
    except OSError as exc:
        _fail("MEMORY_PATH_INVALID", "PARENT:" + type(exc).__name__)
    if not stat.S_ISDIR(parent_info.st_mode) or parent.is_symlink():
        _fail("MEMORY_PATH_INVALID", "PARENT_NOT_DIRECTORY")
    try:
        if parent.resolve(strict=True) != parent.absolute():
            _fail("MEMORY_PATH_INVALID", "SYMLINKED_PARENT_PATH")
    except OSError as exc:
        _fail("MEMORY_PATH_INVALID", "PARENT_RESOLVE:" + type(exc).__name__)
    return path


def _read_locked_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def append_candidate(
    path: str | os.PathLike[str],
    candidate: dict[str, Any],
    *,
    expected_head_sha256: str | None,
    ledger_records: list[dict[str, Any]] | None = None,
    requested_claim_keys: list[str] | None = None,
    hypothesis_state: dict[str, Any] | None = None,
    goal_chain: dict[str, Any] | None = None,
    source_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = _validate_storage_parent(pathlib.Path(path))
    if expected_head_sha256 is not None:
        _sha_value(expected_head_sha256, "MEMORY_HEAD_MISMATCH")
    flags = (
        os.O_RDWR
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(target, flags, 0o600)
    except OSError as exc:
        _fail("MEMORY_PATH_INVALID", "OPEN_FAILED:" + type(exc).__name__)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _fail("MEMORY_PATH_INVALID", "NOT_REGULAR")
        if stat.S_IMODE(info.st_mode) != 0o600:
            _fail("MEMORY_PATH_INVALID", "MODE_NOT_0600")
        fcntl.flock(fd, fcntl.LOCK_EX)
        old_bytes = _read_locked_fd(fd)
        locked_records = parse_jsonl_bytes(old_bytes)
        actual_head = locked_records[-1]["record_sha256"] if locked_records else None
        if expected_head_sha256 != actual_head:
            _fail("MEMORY_HEAD_MISMATCH")
        expected_candidate = _rebuild_for_append(
            copy.deepcopy(candidate),
            locked_records,
            ledger_records=copy.deepcopy(ledger_records),
            requested_claim_keys=copy.deepcopy(requested_claim_keys),
            hypothesis_state=copy.deepcopy(hypothesis_state),
            goal_chain=copy.deepcopy(goal_chain),
            source_envelope=copy.deepcopy(source_envelope),
        )
        if any(
            record["content_sha256"] == expected_candidate["content_sha256"]
            for record in locked_records
        ):
            _fail("DUPLICATE_MEMORY_RECORD")
        final = finalize_record(
            expected_candidate,
            len(locked_records),
            actual_head,
            locked_records,
        )
        suffix = canonical_json(final)
        os.lseek(fd, 0, os.SEEK_END)
        written = 0
        while written < len(suffix):
            count = os.write(fd, suffix[written:])
            if count <= 0:
                _fail("MEMORY_APPEND_FAILED", "SHORT_WRITE")
            written += count
        os.fsync(fd)
        result_bytes = _read_locked_fd(fd)
        if not result_bytes.startswith(old_bytes):
            _fail("MEMORY_APPEND_FAILED", "OLD_PREFIX_CHANGED")
        if result_bytes != old_bytes + suffix:
            _fail("MEMORY_APPEND_FAILED", "RESULT_BYTES_NOT_EXACT_APPEND")
        result_records = parse_jsonl_bytes(result_bytes)
        if len(result_records) != len(locked_records) + 1:
            _fail("MEMORY_APPEND_FAILED", "RESULT_CHAIN_LENGTH")
        if result_records[-1] != final:
            _fail("MEMORY_APPEND_FAILED", "RESULT_RECORD_MISMATCH")
        return final
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _project_reuse_status(
    record: dict[str, Any],
    ledger_records: list[dict[str, Any]],
) -> str:
    body = record["body"]
    _, qualified = _project_qualified_source(
        project_key=body["project_key"],
        claim_key=body["claim_key"],
        claim_id=body["claim_id"],
        use_policy=record["use_policy"],
        ledger_records=copy.deepcopy(ledger_records),
        require_qualified=False,
    )
    if not qualified:
        return "STALE_MEMORY"
    if record["use_policy"] == "REFRESH_BEFORE_USE":
        return "REFRESH_REQUIRED"
    return "REVALIDATED"


def reconstruct_memory_view(
    memory_records: list[dict[str, Any]],
    ledger_records: list[dict[str, Any]],
) -> dict[str, Any]:
    verified = verify_chain(copy.deepcopy(memory_records))
    if not isinstance(ledger_records, list):
        _fail("SOURCE_BELIEF_INVALID", "LEDGER_RECORDS_REQUIRED")
    episodic: list[dict[str, Any]] = []
    revalidated: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    refresh: list[dict[str, Any]] = []
    procedural: list[dict[str, Any]] = []
    for record in verified:
        if record["memory_class"] == "EPISODIC_MEMORY":
            episodic.append(copy.deepcopy(record))
        elif record["memory_class"] == "PROCEDURAL_CANDIDATE":
            procedural.append(copy.deepcopy(record))
        else:
            status = _project_reuse_status(record, ledger_records)
            if status == "STALE_MEMORY":
                stale.append(copy.deepcopy(record))
            elif status == "REFRESH_REQUIRED":
                refresh.append(copy.deepcopy(record))
            else:
                revalidated.append(copy.deepcopy(record))
    view = {
        "schema": VIEW_SCHEMA_ID,
        "memory_head_sha256": verified[-1]["record_sha256"] if verified else None,
        "memory_record_count": len(verified),
        "episodic_memory": episodic,
        "revalidated_project_semantic_memory": revalidated,
        "stale_project_semantic_memory": stale,
        "refresh_required_project_semantic_memory": refresh,
        "procedural_candidates": procedural,
        "stale_memory_present": bool(stale),
        "refresh_required_present": bool(refresh),
    }
    if frozenset(view.keys()) != _VIEW_FIELDS:
        _fail("MEMORY_VIEW_INVALID")
    return view
