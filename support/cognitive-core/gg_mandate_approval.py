from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import stat
from typing import Any

SCHEMA_ID = "gg.mandate-approval-request.v1"
MANDATE_ASSERTION_SCHEMA_ID = "gg.mandate-assertion.v1"
EVALUATION_RESULT_SCHEMA_ID = "gg.mandate-evaluation-result.v1"
JSON_SCHEMA_DRAFT = "2020-12"
SCHEMA_ADDITIONAL_PROPERTIES = "FALSE_AT_ALL_OBJECT_LEVELS"

SOURCE_TASK_SCHEMA_ID = "gg.cognitive-task-envelope.v1"
SOURCE_TASK_RUNTIME_FILENAME = "gg_cognitive_contract.py"
SOURCE_TASK_RUNTIME_SHA256 = "e8824222fdb8f638f12c57f21a9b060f577e3a5ef5db8e034c9595677e03d79d"
SOURCE_GOAL_SCHEMA_ID = "gg.goal-why-chain.v1"
SOURCE_GOAL_RUNTIME_FILENAME = "gg_goal_why.py"
SOURCE_GOAL_RUNTIME_SHA256 = "05a83a935273b106ad811aac3bb31c80eaf2bd3b444d2be855486899ad591ae6"
SOURCE_HYPOTHESIS_SCHEMA_ID = "gg.hypothesis-protocol.v1"
SOURCE_HYPOTHESIS_RUNTIME_FILENAME = "gg_hypothesis_protocol.py"
SOURCE_HYPOTHESIS_RUNTIME_SHA256 = "fa5abef6f8f87deeda8e9e083d067611b18b0038b07d040ef1363582658fdac3"
SOURCE_STATE_SCHEMA_ID = "gg.state-revalidation-base.v1"
SOURCE_STATE_REVALIDATION_SCHEMA_ID = "gg.state-revalidation-result.v1"
SOURCE_STATE_RUNTIME_FILENAME = "gg_state_revalidation.py"
SOURCE_STATE_RUNTIME_SHA256 = "8a58a8b7077ac977c035225f182d46c7efb9c842f357b80be9618e6caa0ee548"

SOURCE_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
AMBIENT_PYTHONPATH_AUTHORITY = "FORBIDDEN"
SYS_PATH_DISCOVERY = "FORBIDDEN"
SYS_MODULES_REGISTRATION = "NO"
FALLBACK_SOURCE_LOADER = None

REQUESTED_CLAIM_KEYS_AUTHORITY = "VALIDATED_K7_J_STATE_BASE_DEPENDENCY_SCOPE"
HYPOTHESIS_STATE_REQUESTED_CLAIM_KEYS_AS_AUTHORITY = "NO"
UNVALIDATED_STATE_BASE_METADATA_HAS_SCOPE_AUTHORITY = "NO"
MANDATE_REQUIREMENT_VALUES = ("NOT_REQUIRED", "EXPLICIT_REQUIRED")
MANDATE_REQUIREMENT_AUTHORITY = "K7_K_DERIVED_FROM_APPROVAL_SCOPE_RISK_CLASS"
K7_K_OWNS_RISK_CLASSIFICATION_CORRECTNESS = "NO"
K7_K_MAY_LOWER_RISK_CLASS = "NO"
CALLER_SUPPLIED_REVALIDATION_RESULT_IS_AUTHORITY = "NO"
K7_K_REVALIDATES_STATE_ITSELF = "YES"
K7_J_OWNS_PLAN_STATE_DRIFT = "YES"

APPROVER_ID_AUTHORITY = "CALLER_SUPPLIED_LABEL"
APPROVER_ID_AUTHENTICITY = "NOT_VERIFIED_BY_K7-K"
MANDATE_HASH_INTEGRITY = "STRUCTURAL_AND_DERIVED_CONTENT_INTEGRITY"
MANDATE_HASH_PROVES_HISTORICAL_APPROVAL = "NO"
MANDATE_HASH_PROVES_HUMAN_CREATED_ASSERTION = "NO"
MANDATE_ASSERTION_HISTORICAL_AUTHENTICITY = "NOT_VERIFIED_BY_K7-K"
APPROVAL_REQUEST_HISTORICAL_AUTHENTICITY = "NOT_VERIFIED_BY_K7-K"

LIVE_MANDATE_STORE = "NO"
DEFAULT_MANDATE_PATH = None
MANDATE_SINGLE_USE_ENFORCEMENT = "NOT_IMPLEMENTED"
MANDATE_REPLAY_PREVENTION = "NOT_IMPLEMENTED"
TRUSTED_APPROVAL_TIMESTAMP = None
TEMPORAL_EXPIRY_AUTHORITY = None
MANDATE_REVOCATION_STORE = None
MANDATE_VALID_IS_CAPABILITY = "NO"
MANDATE_VALID_IS_TOOL_PERMISSION = "NO"
MANDATE_VALID_IS_ACTION_AUTHORITY = "NO"

LIVE_PERSISTENCE = "NO"
MODEL_INFERENCE = "NO"
NETWORK = "NO"
TOOL_EXECUTION = "NO"
TASK_MUTATION = "NO"
GOAL_MUTATION = "NO"
HYPOTHESIS_MUTATION = "NO"
STATE_BASE_MUTATION = "NO"
ACTION_AUTHORITY = "NONE"
SYSTEM_ALIVE_LOCAL = "NOT_YET"

_APPROVAL_SCOPE_DOMAIN = b"gg.mandate-approval.scope.v1\n"
_REQUEST_CAPTURE_DOMAIN = b"gg.mandate-approval.request.v1\n"
_MANDATE_ASSERTION_DOMAIN = b"gg.mandate-assertion.v1\n"

_REQUEST_FIELDS = frozenset({
    "schema",
    "task_id",
    "origin_id",
    "approval_scope",
    "source_binding",
    "mandate_requirement",
    "approval_scope_revision",
    "request_capture_sha256",
})
_SCOPE_FIELDS = frozenset({
    "ready_core",
    "selected_action_node_id",
    "action_trace_sha256",
    "state_base_revision",
})
_READY_FIELDS = frozenset({
    "owner",
    "goal",
    "expected_value",
    "scope",
    "forbidden_scope",
    "risk_class",
    "stop_conditions",
    "expected_artifacts",
    "acceptance_criteria",
})
_SOURCE_BINDING_FIELDS = frozenset({
    "task_envelope_sha256",
    "goal_chain_sha256",
    "action_trace_sha256",
    "hypothesis_state_sha256",
    "state_base_capture_sha256",
    "revalidation_result_sha256",
})
_ASSERTION_FIELDS = frozenset({
    "schema",
    "approver_id",
    "approval_scope_revision",
    "decision",
    "mandate_assertion_sha256",
})
_EVALUATION_FIELDS = frozenset({
    "schema",
    "request_capture_sha256",
    "approval_scope_revision",
    "current_approval_scope_revision",
    "mandate_assertion_sha256",
    "result",
    "reason_code",
})
_RESULTS = (
    "MANDATE_NOT_REQUIRED",
    "MANDATE_REQUIRED",
    "MANDATE_VALID",
    "MANDATE_MISMATCH",
    "MANDATE_BLOCKED",
)
_REASONS = (
    "GREEN_RISK_CLASS",
    "EXPLICIT_MANDATE_MISSING",
    "APPROVAL_SCOPE_MATCH",
    "ASSERTION_SCOPE_MISMATCH",
    "APPROVAL_SCOPE_CHANGED",
    "STATE_NOT_REVALIDATED",
)
_RESULT_REASONS = {
    "MANDATE_NOT_REQUIRED": frozenset({"GREEN_RISK_CLASS"}),
    "MANDATE_REQUIRED": frozenset({"EXPLICIT_MANDATE_MISSING"}),
    "MANDATE_VALID": frozenset({"APPROVAL_SCOPE_MATCH"}),
    "MANDATE_MISMATCH": frozenset({
        "ASSERTION_SCOPE_MISMATCH",
        "APPROVAL_SCOPE_CHANGED",
    }),
    "MANDATE_BLOCKED": frozenset({"STATE_NOT_REVALIDATED"}),
}
_RISK_CLASSES = ("GREEN", "YELLOW", "RED")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_SCHEMA_JSON = '{"$defs":{"approval_scope":{"additionalProperties":false,"properties":{"action_trace_sha256":{"$ref":"#/$defs/sha256"},"ready_core":{"$ref":"#/$defs/ready_core"},"selected_action_node_id":{"$ref":"#/$defs/sha256"},"state_base_revision":{"$ref":"#/$defs/sha256"}},"required":["ready_core","selected_action_node_id","action_trace_sha256","state_base_revision"],"type":"object"},"evaluation_result":{"$id":"gg.mandate-evaluation-result.v1","additionalProperties":false,"properties":{"approval_scope_revision":{"$ref":"#/$defs/sha256"},"current_approval_scope_revision":{"$ref":"#/$defs/nullable_sha256"},"mandate_assertion_sha256":{"$ref":"#/$defs/nullable_sha256"},"reason_code":{"enum":["GREEN_RISK_CLASS","EXPLICIT_MANDATE_MISSING","APPROVAL_SCOPE_MATCH","ASSERTION_SCOPE_MISMATCH","APPROVAL_SCOPE_CHANGED","STATE_NOT_REVALIDATED"],"type":"string"},"request_capture_sha256":{"$ref":"#/$defs/sha256"},"result":{"enum":["MANDATE_NOT_REQUIRED","MANDATE_REQUIRED","MANDATE_VALID","MANDATE_MISMATCH","MANDATE_BLOCKED"],"type":"string"},"schema":{"const":"gg.mandate-evaluation-result.v1","type":"string"}},"required":["schema","request_capture_sha256","approval_scope_revision","current_approval_scope_revision","mandate_assertion_sha256","result","reason_code"],"type":"object"},"identifier":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]{1,128}$","type":"string"},"mandate_assertion":{"$id":"gg.mandate-assertion.v1","additionalProperties":false,"properties":{"approval_scope_revision":{"$ref":"#/$defs/sha256"},"approver_id":{"$ref":"#/$defs/identifier"},"decision":{"const":"APPROVE","type":"string"},"mandate_assertion_sha256":{"$ref":"#/$defs/sha256"},"schema":{"const":"gg.mandate-assertion.v1","type":"string"}},"required":["schema","approver_id","approval_scope_revision","decision","mandate_assertion_sha256"],"type":"object"},"nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"nullable_sha256":{"anyOf":[{"$ref":"#/$defs/sha256"},{"type":"null"}]},"ready_core":{"additionalProperties":false,"properties":{"acceptance_criteria":{"items":{"$ref":"#/$defs/nonblank"},"maxItems":64,"minItems":0,"type":"array","uniqueItems":true},"expected_artifacts":{"items":{"$ref":"#/$defs/nonblank"},"maxItems":64,"minItems":0,"type":"array","uniqueItems":true},"expected_value":{"$ref":"#/$defs/nonblank"},"forbidden_scope":{"items":{"$ref":"#/$defs/nonblank"},"maxItems":64,"minItems":0,"type":"array","uniqueItems":true},"goal":{"$ref":"#/$defs/nonblank"},"owner":{"$ref":"#/$defs/nonblank"},"risk_class":{"enum":["GREEN","YELLOW","RED"],"type":"string"},"scope":{"items":{"$ref":"#/$defs/nonblank"},"maxItems":64,"minItems":0,"type":"array","uniqueItems":true},"stop_conditions":{"items":{"$ref":"#/$defs/nonblank"},"maxItems":64,"minItems":0,"type":"array","uniqueItems":true}},"required":["owner","goal","expected_value","scope","forbidden_scope","risk_class","stop_conditions","expected_artifacts","acceptance_criteria"],"type":"object"},"sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"source_binding":{"additionalProperties":false,"properties":{"action_trace_sha256":{"$ref":"#/$defs/sha256"},"goal_chain_sha256":{"$ref":"#/$defs/sha256"},"hypothesis_state_sha256":{"$ref":"#/$defs/sha256"},"revalidation_result_sha256":{"$ref":"#/$defs/sha256"},"state_base_capture_sha256":{"$ref":"#/$defs/sha256"},"task_envelope_sha256":{"$ref":"#/$defs/sha256"}},"required":["task_envelope_sha256","goal_chain_sha256","action_trace_sha256","hypothesis_state_sha256","state_base_capture_sha256","revalidation_result_sha256"],"type":"object"}},"$id":"gg.mandate-approval-request.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"approval_scope":{"$ref":"#/$defs/approval_scope"},"approval_scope_revision":{"$ref":"#/$defs/sha256"},"mandate_requirement":{"enum":["NOT_REQUIRED","EXPLICIT_REQUIRED"],"type":"string"},"origin_id":{"$ref":"#/$defs/identifier"},"request_capture_sha256":{"$ref":"#/$defs/sha256"},"schema":{"const":"gg.mandate-approval-request.v1","type":"string"},"source_binding":{"$ref":"#/$defs/source_binding"},"task_id":{"$ref":"#/$defs/identifier"}},"required":["schema","task_id","origin_id","approval_scope","source_binding","mandate_requirement","approval_scope_revision","request_capture_sha256"],"type":"object"}'


class MandateApprovalError(ValueError):
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
    raise MandateApprovalError(code, cause_code, cause_message)


def _stop(cause_code: str, cause_message: str | None = None) -> None:
    _fail("STOP_MANDATE", cause_code, cause_message)


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


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact(
    value: Any,
    fields: frozenset[str],
    cause_code: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("APPROVAL_REQUEST_INVALID", cause_code)
    return value


def _identifier(value: Any, cause_code: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _fail("APPROVAL_REQUEST_INVALID", cause_code)
    return value


def _sha_text(value: Any, cause_code: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _fail("APPROVAL_REQUEST_INVALID", cause_code)
    return value


def _nullable_sha(value: Any, cause_code: str) -> str | None:
    if value is None:
        return None
    return _sha_text(value, cause_code)


def _nonblank(value: Any, cause_code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("APPROVAL_REQUEST_INVALID", cause_code)
    return value


def _nonblank_list(value: Any, cause_code: str) -> list[str]:
    if not isinstance(value, list):
        _fail("APPROVAL_REQUEST_INVALID", cause_code)
    checked = [_nonblank(item, cause_code) for item in value]
    if len(set(checked)) != len(checked):
        _fail("APPROVAL_REQUEST_INVALID", cause_code)
    return checked


def _validate_ready_core(value: Any) -> dict[str, Any]:
    item = _exact(value, _READY_FIELDS, "READY_CORE_SURFACE_INVALID")
    _nonblank(item["owner"], "READY_CORE_OWNER_INVALID")
    _nonblank(item["goal"], "READY_CORE_GOAL_INVALID")
    _nonblank(item["expected_value"], "READY_CORE_EXPECTED_VALUE_INVALID")
    _nonblank_list(item["scope"], "READY_CORE_SCOPE_INVALID")
    _nonblank_list(item["forbidden_scope"], "READY_CORE_FORBIDDEN_SCOPE_INVALID")
    if item["risk_class"] not in _RISK_CLASSES:
        _fail("APPROVAL_REQUEST_INVALID", "READY_CORE_RISK_CLASS_INVALID")
    _nonblank_list(item["stop_conditions"], "READY_CORE_STOP_CONDITIONS_INVALID")
    _nonblank_list(item["expected_artifacts"], "READY_CORE_ARTIFACTS_INVALID")
    _nonblank_list(
        item["acceptance_criteria"],
        "READY_CORE_ACCEPTANCE_CRITERIA_INVALID",
    )
    return item


def _validate_approval_scope(value: Any) -> dict[str, Any]:
    item = _exact(value, _SCOPE_FIELDS, "APPROVAL_SCOPE_SURFACE_INVALID")
    _validate_ready_core(item["ready_core"])
    _sha_text(item["selected_action_node_id"], "SELECTED_ACTION_NODE_ID_INVALID")
    _sha_text(item["action_trace_sha256"], "ACTION_TRACE_SHA256_INVALID")
    _sha_text(item["state_base_revision"], "STATE_BASE_REVISION_INVALID")
    return item


def _validate_source_binding(value: Any) -> dict[str, Any]:
    item = _exact(
        value,
        _SOURCE_BINDING_FIELDS,
        "SOURCE_BINDING_SURFACE_INVALID",
    )
    for field in sorted(_SOURCE_BINDING_FIELDS):
        _sha_text(item[field], "SOURCE_BINDING_SHA256_INVALID")
    return item


def _requirement_for_risk(risk_class: str) -> str:
    if risk_class == "GREEN":
        return "NOT_REQUIRED"
    if risk_class in {"YELLOW", "RED"}:
        return "EXPLICIT_REQUIRED"
    _fail("APPROVAL_REQUEST_INVALID", "READY_CORE_RISK_CLASS_INVALID")
    raise AssertionError("unreachable")


def approval_scope_revision(
    task_id: str,
    origin_id: str,
    approval_scope: dict[str, Any],
) -> str:
    _identifier(task_id, "TASK_ID_INVALID")
    _identifier(origin_id, "ORIGIN_ID_INVALID")
    _validate_approval_scope(approval_scope)
    semantics = {
        "task_id": task_id,
        "origin_id": origin_id,
        "approval_scope": copy.deepcopy(approval_scope),
    }
    return _sha_bytes(_APPROVAL_SCOPE_DOMAIN + canonical_json(semantics))


def approval_request_capture_sha256(
    request_without_capture_sha256: dict[str, Any],
) -> str:
    expected = _REQUEST_FIELDS - {"request_capture_sha256"}
    if (
        not isinstance(request_without_capture_sha256, dict)
        or set(request_without_capture_sha256) != expected
    ):
        _fail("APPROVAL_REQUEST_INVALID", "REQUEST_CAPTURE_SURFACE_INVALID")
    return _sha_bytes(
        _REQUEST_CAPTURE_DOMAIN + canonical_json(request_without_capture_sha256)
    )


def mandate_assertion_sha256(
    assertion_without_sha256: dict[str, Any],
) -> str:
    expected = _ASSERTION_FIELDS - {"mandate_assertion_sha256"}
    if (
        not isinstance(assertion_without_sha256, dict)
        or set(assertion_without_sha256) != expected
    ):
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_HASH_SURFACE_INVALID")
    return _sha_bytes(
        _MANDATE_ASSERTION_DOMAIN + canonical_json(assertion_without_sha256)
    )


def validate_approval_request(
    request: dict[str, Any],
) -> dict[str, Any]:
    try:
        value = copy.deepcopy(request)
    except BaseException as exc:
        _fail(
            "APPROVAL_REQUEST_INVALID",
            "DEEPCOPY_FAILED",
            type(exc).__name__,
        )
    item = _exact(value, _REQUEST_FIELDS, "REQUEST_SURFACE_INVALID")
    if item["schema"] != SCHEMA_ID:
        _fail("APPROVAL_REQUEST_INVALID", "REQUEST_SCHEMA_INVALID")
    task_id = _identifier(item["task_id"], "TASK_ID_INVALID")
    origin_id = _identifier(item["origin_id"], "ORIGIN_ID_INVALID")
    scope = _validate_approval_scope(item["approval_scope"])
    binding = _validate_source_binding(item["source_binding"])
    requirement = item["mandate_requirement"]
    if requirement not in MANDATE_REQUIREMENT_VALUES:
        _fail("APPROVAL_REQUEST_INVALID", "MANDATE_REQUIREMENT_INVALID")
    revision = _sha_text(
        item["approval_scope_revision"],
        "APPROVAL_SCOPE_REVISION_INVALID",
    )
    capture = _sha_text(
        item["request_capture_sha256"],
        "REQUEST_CAPTURE_SHA256_INVALID",
    )
    if binding["action_trace_sha256"] != scope["action_trace_sha256"]:
        _fail("APPROVAL_REQUEST_INVALID", "ACTION_TRACE_BINDING_MISMATCH")
    expected_requirement = _requirement_for_risk(
        scope["ready_core"]["risk_class"]
    )
    if requirement != expected_requirement:
        _fail("APPROVAL_REQUEST_INVALID", "MANDATE_REQUIREMENT_MISMATCH")
    expected_revision = approval_scope_revision(task_id, origin_id, scope)
    if revision != expected_revision:
        _fail("APPROVAL_REQUEST_INVALID", "APPROVAL_SCOPE_REVISION_MISMATCH")
    without_capture = {
        key: copy.deepcopy(value[key])
        for key in value
        if key != "request_capture_sha256"
    }
    expected_capture = approval_request_capture_sha256(without_capture)
    if capture != expected_capture:
        _fail("APPROVAL_REQUEST_INVALID", "REQUEST_CAPTURE_SHA256_MISMATCH")
    return value


def validate_mandate_assertion(
    assertion: dict[str, Any],
) -> dict[str, Any]:
    try:
        value = copy.deepcopy(assertion)
    except BaseException as exc:
        _fail(
            "MANDATE_ASSERTION_INVALID",
            "DEEPCOPY_FAILED",
            type(exc).__name__,
        )
    if not isinstance(value, dict) or set(value) != _ASSERTION_FIELDS:
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_SURFACE_INVALID")
    if value["schema"] != MANDATE_ASSERTION_SCHEMA_ID:
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_SCHEMA_INVALID")
    if not isinstance(value["approver_id"], str) or _ID_RE.fullmatch(
        value["approver_id"]
    ) is None:
        _fail("MANDATE_ASSERTION_INVALID", "APPROVER_ID_INVALID")
    if not isinstance(value["approval_scope_revision"], str) or _SHA_RE.fullmatch(
        value["approval_scope_revision"]
    ) is None:
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_SCOPE_REVISION_INVALID")
    if value["decision"] != "APPROVE":
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_DECISION_INVALID")
    if not isinstance(value["mandate_assertion_sha256"], str) or _SHA_RE.fullmatch(
        value["mandate_assertion_sha256"]
    ) is None:
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_SHA256_INVALID")
    without_hash = {
        key: copy.deepcopy(value[key])
        for key in value
        if key != "mandate_assertion_sha256"
    }
    expected_hash = mandate_assertion_sha256(without_hash)
    if value["mandate_assertion_sha256"] != expected_hash:
        _fail("MANDATE_ASSERTION_INVALID", "ASSERTION_SHA256_MISMATCH")
    return value


def _authority_path(filename: str) -> pathlib.Path:
    return pathlib.Path(__file__).absolute().parent / filename


def _capture_authority_bytes(
    path: pathlib.Path,
    expected_sha256: str,
    cause_code: str,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        _stop(cause_code, "AUTHORITY_OPEN_FAILED:" + type(exc).__name__)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _stop(cause_code, "AUTHORITY_NOT_REGULAR")
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
        _stop(cause_code, "AUTHORITY_CHANGED_DURING_READ")
    try:
        path_after = path.stat(follow_symlinks=False)
    except OSError as exc:
        _stop(cause_code, "AUTHORITY_RESTAT_FAILED:" + type(exc).__name__)
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
        _stop(cause_code, "AUTHORITY_PATH_IDENTITY_CHANGED")

    captured = b"".join(chunks)
    if len(captured) != before.st_size:
        _stop(cause_code, "AUTHORITY_SIZE_MISMATCH")
    if _sha_bytes(captured) != expected_sha256:
        _stop(cause_code, "AUTHORITY_SHA256_MISMATCH")
    return captured


def _load_authority(
    *,
    filename: str,
    expected_sha256: str,
    expected_schema_id: str,
    required_primitives: tuple[str, ...],
    error_class_name: str,
    cause_code: str,
    private_name: str,
) -> dict[str, Any]:
    path = _authority_path(filename)
    captured = _capture_authority_bytes(path, expected_sha256, cause_code)
    try:
        code = compile(captured, str(path), "exec")
    except BaseException as exc:
        _stop(cause_code, "AUTHORITY_COMPILE_FAILED:" + type(exc).__name__)
    namespace: dict[str, Any] = {
        "__name__": private_name,
        "__file__": str(path),
        "__package__": None,
        "__builtins__": __builtins__,
    }
    try:
        exec(code, namespace, namespace)
    except BaseException as exc:
        _stop(cause_code, "AUTHORITY_EXEC_FAILED:" + type(exc).__name__)

    if namespace.get("SCHEMA_ID") != expected_schema_id:
        _stop(cause_code, "AUTHORITY_SCHEMA_ID_MISMATCH")
    error_class = namespace.get(error_class_name)
    if not isinstance(error_class, type) or not issubclass(error_class, Exception):
        _stop(cause_code, "AUTHORITY_ERROR_CLASS_MISSING")
    for primitive in required_primitives:
        if not callable(namespace.get(primitive)):
            _stop(cause_code, "AUTHORITY_PRIMITIVE_MISSING:" + primitive)
    return namespace


def _task_authority() -> dict[str, Any]:
    return _load_authority(
        filename=SOURCE_TASK_RUNTIME_FILENAME,
        expected_sha256=SOURCE_TASK_RUNTIME_SHA256,
        expected_schema_id=SOURCE_TASK_SCHEMA_ID,
        required_primitives=("validate_envelope", "canonicalize_envelope"),
        error_class_name="ContractError",
        cause_code="SOURCE_TASK_INVALID",
        private_name="_gg_k7k_bound_task",
    )


def _goal_authority() -> dict[str, Any]:
    return _load_authority(
        filename=SOURCE_GOAL_RUNTIME_FILENAME,
        expected_sha256=SOURCE_GOAL_RUNTIME_SHA256,
        expected_schema_id=SOURCE_GOAL_SCHEMA_ID,
        required_primitives=("canonical_json", "validate_chain", "trace_action"),
        error_class_name="GoalWhyError",
        cause_code="SOURCE_GOAL_INVALID",
        private_name="_gg_k7k_bound_goal",
    )


def _hypothesis_authority() -> dict[str, Any]:
    return _load_authority(
        filename=SOURCE_HYPOTHESIS_RUNTIME_FILENAME,
        expected_sha256=SOURCE_HYPOTHESIS_RUNTIME_SHA256,
        expected_schema_id=SOURCE_HYPOTHESIS_SCHEMA_ID,
        required_primitives=("canonical_json", "validate_state"),
        error_class_name="HypothesisProtocolError",
        cause_code="SOURCE_HYPOTHESIS_INVALID",
        private_name="_gg_k7k_bound_hypothesis",
    )


def _state_authority() -> dict[str, Any]:
    authority = _load_authority(
        filename=SOURCE_STATE_RUNTIME_FILENAME,
        expected_sha256=SOURCE_STATE_RUNTIME_SHA256,
        expected_schema_id=SOURCE_STATE_SCHEMA_ID,
        required_primitives=(
            "canonical_json",
            "validate_state_base",
            "revalidate_state_base",
        ),
        error_class_name="StateRevalidationError",
        cause_code="SOURCE_STATE_REVALIDATION_INVALID",
        private_name="_gg_k7k_bound_state",
    )
    if authority.get("REVALIDATION_SCHEMA_ID") != SOURCE_STATE_REVALIDATION_SCHEMA_ID:
        _stop(
            "SOURCE_STATE_REVALIDATION_INVALID",
            "AUTHORITY_REVALIDATION_SCHEMA_ID_MISMATCH",
        )
    return authority


def _validated_task(
    authority: dict[str, Any],
    source_envelope: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    try:
        source = copy.deepcopy(source_envelope)
    except BaseException as exc:
        _stop("SOURCE_TASK_INVALID", "DEEPCOPY_FAILED:" + type(exc).__name__)
    error_class = authority["ContractError"]
    try:
        authority["validate_envelope"](source)
        canonical = authority["canonicalize_envelope"](source)
    except error_class as exc:
        _stop("SOURCE_TASK_INVALID", str(exc))
    if source.get("state") != "READY_FOR_CONTROL":
        _stop("SOURCE_TASK_INVALID", "SOURCE_TASK_NOT_READY")
    if not isinstance(source.get("ready_core"), dict):
        _stop("SOURCE_TASK_INVALID", "SOURCE_READY_CORE_MISSING")
    if not isinstance(canonical, bytes):
        _stop("SOURCE_TASK_INVALID", "CANONICALIZE_ENVELOPE_NOT_BYTES")
    return source, canonical


def _validated_goal(
    authority: dict[str, Any],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    error_class = authority["GoalWhyError"]
    try:
        return authority["validate_chain"](
            copy.deepcopy(goal_chain),
            copy.deepcopy(source_envelope),
        )
    except error_class as exc:
        _stop("SOURCE_GOAL_INVALID", str(exc))
    raise AssertionError("unreachable")


def _validated_state_base(
    authority: dict[str, Any],
    state_base: dict[str, Any],
) -> dict[str, Any]:
    error_class = authority["StateRevalidationError"]
    try:
        return authority["validate_state_base"](copy.deepcopy(state_base))
    except error_class as exc:
        _stop("STATE_BASE_INVALID", str(exc))
    raise AssertionError("unreachable")


def _validated_hypothesis(
    authority: dict[str, Any],
    hypothesis_state: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    error_class = authority["HypothesisProtocolError"]
    try:
        return authority["validate_state"](
            copy.deepcopy(hypothesis_state),
            copy.deepcopy(ledger_records),
            copy.deepcopy(requested_claim_keys),
            copy.deepcopy(goal_chain),
            copy.deepcopy(source_envelope),
        )
    except error_class as exc:
        _stop("SOURCE_HYPOTHESIS_INVALID", str(exc))
    raise AssertionError("unreachable")


def _trace_action(
    authority: dict[str, Any],
    goal_chain: dict[str, Any],
    source_envelope: dict[str, Any],
    selected_action_node_id: str,
) -> tuple[str, ...]:
    error_class = authority["GoalWhyError"]
    try:
        trace = authority["trace_action"](
            copy.deepcopy(goal_chain),
            copy.deepcopy(source_envelope),
            selected_action_node_id,
        )
    except error_class as exc:
        _stop("SOURCE_GOAL_INVALID", str(exc))
    if not isinstance(trace, tuple) or not all(
        isinstance(item, str) for item in trace
    ):
        _stop("SOURCE_GOAL_INVALID", "ACTION_TRACE_RETURN_INVALID")
    return trace


def _revalidate(
    authority: dict[str, Any],
    state_base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    error_class = authority["StateRevalidationError"]
    try:
        result = authority["revalidate_state_base"](
            copy.deepcopy(state_base),
            copy.deepcopy(ledger_records),
            copy.deepcopy(memory_records),
            copy.deepcopy(goal_chain),
            copy.deepcopy(hypothesis_state),
            copy.deepcopy(source_envelope),
        )
    except error_class as exc:
        _stop("SOURCE_STATE_REVALIDATION_INVALID", str(exc))
    if (
        not isinstance(result, dict)
        or result.get("schema") != SOURCE_STATE_REVALIDATION_SCHEMA_ID
    ):
        _stop(
            "SOURCE_STATE_REVALIDATION_INVALID",
            "REVALIDATION_RESULT_INVALID",
        )
    return result


def _work_item_agreement(
    source: dict[str, Any],
    goal: dict[str, Any],
    hypothesis: dict[str, Any],
    state_base: dict[str, Any],
) -> tuple[str, str]:
    task_id = source.get("task_id")
    origin_id = source.get("origin_id")
    pairs = (
        (goal.get("task_id"), goal.get("origin_id")),
        (hypothesis.get("task_id"), hypothesis.get("origin_id")),
        (state_base.get("task_id"), state_base.get("origin_id")),
    )
    if any(pair != (task_id, origin_id) for pair in pairs):
        _stop("WORK_ITEM_MISMATCH")
    if not isinstance(task_id, str) or _ID_RE.fullmatch(task_id) is None:
        _stop("WORK_ITEM_MISMATCH", "TASK_ID_INVALID")
    if not isinstance(origin_id, str) or _ID_RE.fullmatch(origin_id) is None:
        _stop("WORK_ITEM_MISMATCH", "ORIGIN_ID_INVALID")
    return task_id, origin_id


def _approval_scope(
    ready_core: dict[str, Any],
    selected_action_node_id: str,
    action_trace_sha256: str,
    state_base_revision: str,
) -> dict[str, Any]:
    value = {
        "ready_core": copy.deepcopy(ready_core),
        "selected_action_node_id": selected_action_node_id,
        "action_trace_sha256": action_trace_sha256,
        "state_base_revision": state_base_revision,
    }
    _validate_approval_scope(value)
    return value


def _source_binding(
    *,
    task_envelope_bytes: bytes,
    goal_authority: dict[str, Any],
    validated_goal: dict[str, Any],
    action_trace: tuple[str, ...],
    hypothesis_authority: dict[str, Any],
    validated_hypothesis: dict[str, Any],
    validated_state_base: dict[str, Any],
    state_authority: dict[str, Any],
    revalidation_result: dict[str, Any],
) -> dict[str, str]:
    goal_bytes = goal_authority["canonical_json"](validated_goal)
    action_bytes = goal_authority["canonical_json"](action_trace)
    hypothesis_bytes = hypothesis_authority["canonical_json"](
        validated_hypothesis
    )
    revalidation_bytes = state_authority["canonical_json"](
        revalidation_result
    )
    for name, value in (
        ("goal", goal_bytes),
        ("action", action_bytes),
        ("hypothesis", hypothesis_bytes),
        ("revalidation", revalidation_bytes),
    ):
        if not isinstance(value, bytes):
            _stop("SOURCE_BINDING_MISMATCH", name + "_CANONICAL_NOT_BYTES")
    binding = {
        "task_envelope_sha256": _sha_bytes(task_envelope_bytes),
        "goal_chain_sha256": _sha_bytes(goal_bytes),
        "action_trace_sha256": _sha_bytes(action_bytes),
        "hypothesis_state_sha256": _sha_bytes(hypothesis_bytes),
        "state_base_capture_sha256": validated_state_base["capture_sha256"],
        "revalidation_result_sha256": _sha_bytes(revalidation_bytes),
    }
    _validate_source_binding(binding)
    return binding


def _load_all_authorities() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    return (
        _task_authority(),
        _goal_authority(),
        _hypothesis_authority(),
        _state_authority(),
    )


def _base_context(
    *,
    source_envelope: dict[str, Any],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    state_base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
) -> dict[str, Any]:
    task_auth, goal_auth, hyp_auth, state_auth = _load_all_authorities()
    source, task_bytes = _validated_task(task_auth, source_envelope)
    goal = _validated_goal(goal_auth, goal_chain, source)
    base = _validated_state_base(state_auth, state_base)
    scope = base.get("dependency_scope")
    if not isinstance(scope, dict):
        _stop("STATE_BASE_INVALID", "DEPENDENCY_SCOPE_INVALID")
    requested = scope.get("requested_claim_keys")
    if not isinstance(requested, list):
        _stop("STATE_BASE_INVALID", "REQUESTED_CLAIM_KEYS_INVALID")
    hypothesis = _validated_hypothesis(
        hyp_auth,
        hypothesis_state,
        ledger_records,
        requested,
        goal,
        source,
    )
    task_id, origin_id = _work_item_agreement(
        source,
        goal,
        hypothesis,
        base,
    )
    return {
        "task_authority": task_auth,
        "goal_authority": goal_auth,
        "hypothesis_authority": hyp_auth,
        "state_authority": state_auth,
        "source": source,
        "task_bytes": task_bytes,
        "goal": goal,
        "base": base,
        "hypothesis": hypothesis,
        "task_id": task_id,
        "origin_id": origin_id,
    }


def _require_plan_action(context: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    decision = context["hypothesis"].get("decision")
    if not isinstance(decision, dict) or decision.get("kind") != "PLAN_ACTION":
        _stop("NO_PLAN_ACTION")
    selected = decision.get("selected_action_node_id")
    if not isinstance(selected, str) or _SHA_RE.fullmatch(selected) is None:
        _stop("NO_PLAN_ACTION", "SELECTED_ACTION_NODE_INVALID")
    trace = _trace_action(
        context["goal_authority"],
        context["goal"],
        context["source"],
        selected,
    )
    return selected, trace


def _approval_material(
    context: dict[str, Any],
    *,
    selected_action_node_id: str,
    action_trace: tuple[str, ...],
    revalidation_result: dict[str, Any],
) -> dict[str, Any]:
    base = context["base"]
    action_trace_bytes = context["goal_authority"]["canonical_json"](
        action_trace
    )
    if not isinstance(action_trace_bytes, bytes):
        _stop("SOURCE_BINDING_MISMATCH", "ACTION_CANONICAL_NOT_BYTES")
    action_trace_hash = _sha_bytes(action_trace_bytes)
    scope = _approval_scope(
        context["source"]["ready_core"],
        selected_action_node_id,
        action_trace_hash,
        base["state_base_revision"],
    )
    binding = _source_binding(
        task_envelope_bytes=context["task_bytes"],
        goal_authority=context["goal_authority"],
        validated_goal=context["goal"],
        action_trace=action_trace,
        hypothesis_authority=context["hypothesis_authority"],
        validated_hypothesis=context["hypothesis"],
        validated_state_base=base,
        state_authority=context["state_authority"],
        revalidation_result=revalidation_result,
    )
    revision = approval_scope_revision(
        context["task_id"],
        context["origin_id"],
        scope,
    )
    requirement = _requirement_for_risk(
        scope["ready_core"]["risk_class"]
    )
    return {
        "scope": scope,
        "binding": binding,
        "revision": revision,
        "requirement": requirement,
    }


def make_approval_request(
    source_envelope: dict[str, Any],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    state_base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
) -> dict[str, Any]:
    context = _base_context(
        source_envelope=source_envelope,
        goal_chain=goal_chain,
        hypothesis_state=hypothesis_state,
        state_base=state_base,
        ledger_records=ledger_records,
    )
    selected, trace = _require_plan_action(context)
    revalidation = _revalidate(
        context["state_authority"],
        context["base"],
        ledger_records,
        memory_records,
        context["goal"],
        context["hypothesis"],
        context["source"],
    )
    if revalidation.get("result") != "REVALIDATED":
        _stop("STATE_NOT_REVALIDATED", str(revalidation.get("result")))
    if (
        revalidation.get("reconstructed_state_base_revision")
        != context["base"]["state_base_revision"]
    ):
        _stop("SOURCE_BINDING_MISMATCH", "RECONSTRUCTED_REVISION_MISMATCH")
    material = _approval_material(
        context,
        selected_action_node_id=selected,
        action_trace=trace,
        revalidation_result=revalidation,
    )
    request: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "task_id": context["task_id"],
        "origin_id": context["origin_id"],
        "approval_scope": material["scope"],
        "source_binding": material["binding"],
        "mandate_requirement": material["requirement"],
        "approval_scope_revision": material["revision"],
    }
    request["request_capture_sha256"] = approval_request_capture_sha256(
        copy.deepcopy(request)
    )
    return validate_approval_request(request)


def make_mandate_assertion(
    approver_id: str,
    approval_scope_revision_value: str,
) -> dict[str, Any]:
    if not isinstance(approver_id, str) or _ID_RE.fullmatch(approver_id) is None:
        _fail("MANDATE_ASSERTION_INVALID", "APPROVER_ID_INVALID")
    if (
        not isinstance(approval_scope_revision_value, str)
        or _SHA_RE.fullmatch(approval_scope_revision_value) is None
    ):
        _fail(
            "MANDATE_ASSERTION_INVALID",
            "ASSERTION_SCOPE_REVISION_INVALID",
        )
    assertion: dict[str, Any] = {
        "schema": MANDATE_ASSERTION_SCHEMA_ID,
        "approver_id": approver_id,
        "approval_scope_revision": approval_scope_revision_value,
        "decision": "APPROVE",
    }
    assertion["mandate_assertion_sha256"] = mandate_assertion_sha256(
        copy.deepcopy(assertion)
    )
    return validate_mandate_assertion(assertion)


def _evaluation_result(
    *,
    request: dict[str, Any],
    current_revision: str | None,
    assertion_hash: str | None,
    result: str,
    reason_code: str,
) -> dict[str, Any]:
    if result not in _RESULTS or reason_code not in _REASONS:
        _fail("APPROVAL_REQUEST_INVALID", "EVALUATION_ENUM_INVALID")
    if reason_code not in _RESULT_REASONS[result]:
        _fail("APPROVAL_REQUEST_INVALID", "EVALUATION_PAIR_INVALID")
    value = {
        "schema": EVALUATION_RESULT_SCHEMA_ID,
        "request_capture_sha256": request["request_capture_sha256"],
        "approval_scope_revision": request["approval_scope_revision"],
        "current_approval_scope_revision": current_revision,
        "mandate_assertion_sha256": assertion_hash,
        "result": result,
        "reason_code": reason_code,
    }
    _validate_evaluation_result(value)
    return value


def _validate_evaluation_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _EVALUATION_FIELDS:
        _fail("APPROVAL_REQUEST_INVALID", "EVALUATION_SURFACE_INVALID")
    if value["schema"] != EVALUATION_RESULT_SCHEMA_ID:
        _fail("APPROVAL_REQUEST_INVALID", "EVALUATION_SCHEMA_INVALID")
    _sha_text(value["request_capture_sha256"], "EVALUATION_REQUEST_SHA_INVALID")
    _sha_text(value["approval_scope_revision"], "EVALUATION_SCOPE_SHA_INVALID")
    _nullable_sha(
        value["current_approval_scope_revision"],
        "EVALUATION_CURRENT_SCOPE_SHA_INVALID",
    )
    _nullable_sha(
        value["mandate_assertion_sha256"],
        "EVALUATION_ASSERTION_SHA_INVALID",
    )
    if value["result"] not in _RESULTS:
        _fail("APPROVAL_REQUEST_INVALID", "EVALUATION_RESULT_INVALID")
    if value["reason_code"] not in _RESULT_REASONS[value["result"]]:
        _fail("APPROVAL_REQUEST_INVALID", "EVALUATION_REASON_INVALID")
    return value


def evaluate_mandate(
    request: dict[str, Any],
    mandate_assertion: dict[str, Any] | None,
    source_envelope: dict[str, Any],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    state_base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        validated_request = validate_approval_request(request)
    except MandateApprovalError as exc:
        if exc.code == "STOP_MANDATE":
            raise
        _stop("APPROVAL_REQUEST_INVALID", exc.cause_code or exc.code)

    validated_assertion: dict[str, Any] | None = None
    if mandate_assertion is not None:
        try:
            validated_assertion = validate_mandate_assertion(mandate_assertion)
        except MandateApprovalError as exc:
            if exc.code == "STOP_MANDATE":
                raise
            _stop("MANDATE_ASSERTION_INVALID", exc.cause_code or exc.code)

    context = _base_context(
        source_envelope=source_envelope,
        goal_chain=goal_chain,
        hypothesis_state=hypothesis_state,
        state_base=state_base,
        ledger_records=ledger_records,
    )
    if (
        context["task_id"] != validated_request["task_id"]
        or context["origin_id"] != validated_request["origin_id"]
    ):
        _stop("WORK_ITEM_MISMATCH")

    revalidation = _revalidate(
        context["state_authority"],
        context["base"],
        ledger_records,
        memory_records,
        context["goal"],
        context["hypothesis"],
        context["source"],
    )
    assertion_hash = (
        None
        if validated_assertion is None
        else validated_assertion["mandate_assertion_sha256"]
    )
    if revalidation.get("result") != "REVALIDATED":
        return _evaluation_result(
            request=validated_request,
            current_revision=None,
            assertion_hash=assertion_hash,
            result="MANDATE_BLOCKED",
            reason_code="STATE_NOT_REVALIDATED",
        )
    if (
        revalidation.get("reconstructed_state_base_revision")
        != context["base"]["state_base_revision"]
    ):
        _stop("SOURCE_BINDING_MISMATCH", "RECONSTRUCTED_REVISION_MISMATCH")

    decision = context["hypothesis"].get("decision")
    if not isinstance(decision, dict) or decision.get("kind") != "PLAN_ACTION":
        _stop("SOURCE_BINDING_MISMATCH", "REVALIDATED_NON_PLAN_ACTION")
    selected = decision.get("selected_action_node_id")
    if not isinstance(selected, str) or _SHA_RE.fullmatch(selected) is None:
        _stop("SOURCE_BINDING_MISMATCH", "REVALIDATED_ACTION_INVALID")
    trace = _trace_action(
        context["goal_authority"],
        context["goal"],
        context["source"],
        selected,
    )
    material = _approval_material(
        context,
        selected_action_node_id=selected,
        action_trace=trace,
        revalidation_result=revalidation,
    )
    current_revision = material["revision"]

    if current_revision != validated_request["approval_scope_revision"]:
        return _evaluation_result(
            request=validated_request,
            current_revision=current_revision,
            assertion_hash=assertion_hash,
            result="MANDATE_MISMATCH",
            reason_code="APPROVAL_SCOPE_CHANGED",
        )

    if (
        validated_assertion is not None
        and validated_assertion["approval_scope_revision"] != current_revision
    ):
        return _evaluation_result(
            request=validated_request,
            current_revision=current_revision,
            assertion_hash=assertion_hash,
            result="MANDATE_MISMATCH",
            reason_code="ASSERTION_SCOPE_MISMATCH",
        )

    if validated_assertion is None:
        if validated_request["mandate_requirement"] == "NOT_REQUIRED":
            return _evaluation_result(
                request=validated_request,
                current_revision=current_revision,
                assertion_hash=None,
                result="MANDATE_NOT_REQUIRED",
                reason_code="GREEN_RISK_CLASS",
            )
        return _evaluation_result(
            request=validated_request,
            current_revision=current_revision,
            assertion_hash=None,
            result="MANDATE_REQUIRED",
            reason_code="EXPLICIT_MANDATE_MISSING",
        )

    return _evaluation_result(
        request=validated_request,
        current_revision=current_revision,
        assertion_hash=assertion_hash,
        result="MANDATE_VALID",
        reason_code="APPROVAL_SCOPE_MATCH",
    )
