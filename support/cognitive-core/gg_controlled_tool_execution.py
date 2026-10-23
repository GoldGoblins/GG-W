from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import stat
from typing import Any

SCHEMA_ID = "gg.local-tool-profile-registry.v1"
PROFILE_SCHEMA_ID = "gg.local-tool-profile.v1"
DECISION_SCHEMA_ID = "gg.controlled-tool-decision.v1"
RECEIPT_SCHEMA_ID = "gg.local-tool-execution-receipt.v1"

K7_K_RUNTIME_FILENAME = "gg_mandate_approval.py"
K7_K_RUNTIME_SHA256 = "896b9f33da2ef8855d811da57aeb6db2bf6591bf3da3568ab1ddc5126aeac133"
K7_L_REGISTRY_RUNTIME_RELATIVE = "../infrastructure/local-tool-executor/tool-profiles.json"
K7_L_PROTOCOL_REGISTRY_SHA256 = "c9124417e7131332535dd8c850961b2feba4b9071719e0e2f63a3905d7f492d8"
K7_L_REGISTRY_SEMANTIC_SHA256 = "655b1c0769fe3ae23eb52a7ad2af6a33c24e9bf931bb0285cbce38245e2f1794"

PROFILE_ID = "GG_K7K_STATUS_SHA256_READONLY_FD34_V1"
PROFILE_REVISION = "0a0282535c6395fdc53a81722fd99bd0d1825c7e3679be61b39a9ea68ad916fe"
TOOL_PROFILE_SCOPE_MARKER = "gg.local-tool-profile.v1:0a0282535c6395fdc53a81722fd99bd0d1825c7e3679be61b39a9ea68ad916fe"

K7_L_SUPPORTED_APPROVAL_RISK = "GREEN_ONLY"
CALLER_PROFILE_POLICY_AUTHORITY = "NONE"
PROTOCOL_PROFILE_POLICY_AUTHORITY = "EXACT_CAPTURED_CANONICAL_REGISTRY_BYTES"
CALLER_SUPPLIED_MANDATE_EVALUATION_IS_AUTHORITY = "NO"
K7_L_MAY_MINT_REPLACEMENT_APPROVAL_REQUEST = "NO"
K7_L_MAY_MUTATE_APPROVAL_REQUEST = "NO"
MANDATE_VALID_IS_TOOL_PERMISSION = "NO"
CONTROLLED_TOOL_DECISION_IS_CAPABILITY = "NO"
STORED_EXECUTION_ELIGIBLE_IS_AUTHORITY = "NO"
GENERAL_ACTION_AUTHORITY = "NONE"
SYSTEM_ALIVE_LOCAL = "NOT_YET"

_SCHEMA_JSON = '{"$defs":{"decision":{"$id":"gg.controlled-tool-decision.v1","additionalProperties":false,"properties":{"action_trace_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"approval_request_capture_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"approval_scope_revision":{"pattern":"^[0-9a-f]{64}$","type":"string"},"decision_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"mandate_assertion_sha256":{"anyOf":[{"pattern":"^[0-9a-f]{64}$","type":"string"},{"type":"null"}]},"mandate_evaluation_result":{"type":"object"},"mandate_evaluation_result_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"reason_code":{"enum":["GREEN_PROFILE_MANDATE_NOT_REQUIRED","GREEN_PROFILE_MANDATE_VALID","K7_K_MANDATE_REQUIRED","K7_K_MANDATE_MISMATCH","K7_K_MANDATE_BLOCKED","K7_L_RISK_CLASS_UNSUPPORTED","PROFILE_SCOPE_MARKER_MISMATCH"]},"result":{"enum":["EXECUTION_ELIGIBLE","EXECUTION_BLOCKED"]},"schema":{"const":"gg.controlled-tool-decision.v1"},"selected_action_node_id":{"pattern":"^[0-9a-f]{64}$","type":"string"},"tool_execution_binding_revision":{"pattern":"^[0-9a-f]{64}$","type":"string"},"tool_profile_id":{"const":"GG_K7K_STATUS_SHA256_READONLY_FD34_V1"},"tool_profile_revision":{"const":"0a0282535c6395fdc53a81722fd99bd0d1825c7e3679be61b39a9ea68ad916fe"},"tool_profile_scope_marker":{"pattern":"^gg\\\\.local-tool-profile\\\\.v1:[0-9a-f]{64}$","type":"string"}},"required":["action_trace_sha256","approval_request_capture_sha256","approval_scope_revision","decision_sha256","mandate_assertion_sha256","mandate_evaluation_result","mandate_evaluation_result_sha256","reason_code","result","schema","selected_action_node_id","tool_execution_binding_revision","tool_profile_id","tool_profile_revision","tool_profile_scope_marker"],"type":"object"},"profile":{"$id":"gg.local-tool-profile.v1","additionalProperties":false,"properties":{"argv":{"const":["/usr/bin/sha256sum","--","/proc/self/fd/3"]},"automatic_retry":{"const":false},"backend":{"const":"SUBPROCESS_POPEN_FD34_PINNED_V1"},"background_execution":{"const":false},"cwd":{"const":"/home/GG/GoldGoblins"},"declared_target_path":{"const":"/home/GG/GoldGoblins/status/SYSTEMSTATUS-K7-K-MANDATE-APPROVAL-COMPLETE-LOCAL-2026-08-10-v1.0.md"},"declared_target_sha256":{"const":"3198274dadb91b66d8b919467e4cdc3529408e62ab5bb9f97896a2107e4edc2c"},"dynamic_runtime_dependency_content_authority":{"const":"NOT_PINNED"},"effect_class":{"const":"READ_ONLY"},"environment":{"const":{"LC_ALL":"C","PATH":"/usr/bin:/bin","PYTHONDONTWRITEBYTECODE":"1"}},"executable_fd_number":{"const":4},"executable_open_flags":{"const":["O_RDONLY","O_CLOEXEC","O_NOFOLLOW"]},"executable_package":{"const":"coreutils|0|9.10|4.fc44|x86_64"},"executable_path":{"const":"/usr/bin/sha256sum"},"executable_reference_path":{"const":"/proc/self/fd/4"},"executable_require_regular_file":{"const":true},"executable_required_gid":{"const":0},"executable_required_mode":{"const":"0755"},"executable_required_uid":{"const":0},"executable_sha256":{"const":"f68bf52a31beac0119654d4ac4a27b63d03a97bbdf2eb6a06ba5e4a6fbcbf652"},"expected_exit_code":{"const":0},"expected_stderr_utf8":{"const":""},"expected_stdout_utf8":{"const":"3198274dadb91b66d8b919467e4cdc3529408e62ab5bb9f97896a2107e4edc2c  /proc/self/fd/3\\n"},"filesystem_write_kernel_confinement":{"const":"NOT_IMPLEMENTED_IN_K7_L_V1"},"general_binary_behavior_sandbox":{"const":"NOT_IMPLEMENTED"},"max_stderr_bytes":{"const":4096},"max_stdout_bytes":{"const":4096},"network_authority_granted":{"const":"NONE"},"network_kernel_confinement":{"const":"NOT_IMPLEMENTED_IN_K7_L_V1"},"parameterized_argv":{"const":false},"persistent_write_authority_granted":{"const":"NONE"},"privileged_authority_granted":{"const":"NONE"},"process_start_count_max":{"const":1},"profile_id":{"const":"GG_K7K_STATUS_SHA256_READONLY_FD34_V1"},"profile_revision":{"pattern":"^[0-9a-f]{64}$","type":"string"},"risk_class":{"const":"GREEN"},"schema":{"const":"gg.local-tool-profile.v1"},"shell_execution":{"const":false},"stdin_policy":{"const":"DEVNULL"},"target_fd_number":{"const":3},"target_open_flags":{"const":["O_RDONLY","O_CLOEXEC","O_NOFOLLOW"]},"target_reference_path":{"const":"/proc/self/fd/3"},"target_require_regular_file":{"const":true},"timeout_seconds":{"const":5}},"required":["argv","automatic_retry","backend","background_execution","cwd","declared_target_path","declared_target_sha256","dynamic_runtime_dependency_content_authority","effect_class","environment","executable_fd_number","executable_open_flags","executable_package","executable_path","executable_reference_path","executable_require_regular_file","executable_required_gid","executable_required_mode","executable_required_uid","executable_sha256","expected_exit_code","expected_stderr_utf8","expected_stdout_utf8","filesystem_write_kernel_confinement","general_binary_behavior_sandbox","max_stderr_bytes","max_stdout_bytes","network_authority_granted","network_kernel_confinement","parameterized_argv","persistent_write_authority_granted","privileged_authority_granted","process_start_count_max","profile_id","profile_revision","risk_class","schema","shell_execution","stdin_policy","target_fd_number","target_open_flags","target_reference_path","target_require_regular_file","timeout_seconds"],"type":"object"},"receipt":{"$id":"gg.local-tool-execution-receipt.v1","additionalProperties":false,"properties":{"action_trace_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"approval_request_capture_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"approval_scope_revision":{"pattern":"^[0-9a-f]{64}$","type":"string"},"argv":{"const":["/usr/bin/sha256sum","--","/proc/self/fd/3"]},"backend":{"const":"SUBPROCESS_POPEN_FD34_PINNED_V1"},"controlled_tool_decision_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"cwd":{"const":"/home/GG/GoldGoblins"},"declared_target_path":{"const":"/home/GG/GoldGoblins/status/SYSTEMSTATUS-K7-K-MANDATE-APPROVAL-COMPLETE-LOCAL-2026-08-10-v1.0.md"},"duration_ms":{"minimum":0,"type":"integer"},"dynamic_runtime_dependency_content_authority":{"const":"NOT_PINNED"},"environment_names":{"const":["LC_ALL","PATH","PYTHONDONTWRITEBYTECODE"]},"executable_device":{"minimum":0,"type":"integer"},"executable_fd_matches_expected_after":{"type":"boolean"},"executable_fd_matches_expected_before":{"type":"boolean"},"executable_fd_number":{"const":4},"executable_fd_sha256_after":{"pattern":"^[0-9a-f]{64}$","type":"string"},"executable_fd_sha256_before":{"pattern":"^[0-9a-f]{64}$","type":"string"},"executable_gid":{"const":0},"executable_inode":{"minimum":0,"type":"integer"},"executable_mode":{"const":"0755"},"executable_path":{"const":"/usr/bin/sha256sum"},"executable_reference_path":{"const":"/proc/self/fd/4"},"executable_sha256":{"const":"f68bf52a31beac0119654d4ac4a27b63d03a97bbdf2eb6a06ba5e4a6fbcbf652"},"executable_uid":{"const":0},"execution_request_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"exit_code":{"anyOf":[{"type":"integer"},{"type":"null"}]},"filesystem_write_kernel_confinement":{"const":"NOT_IMPLEMENTED_IN_K7_L_V1"},"general_binary_behavior_sandbox":{"const":"NOT_IMPLEMENTED"},"mandate_assertion_sha256":{"anyOf":[{"pattern":"^[0-9a-f]{64}$","type":"string"},{"type":"null"}]},"mandate_evaluation_result_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"max_stderr_bytes":{"const":4096},"max_stdout_bytes":{"const":4096},"network_authority_granted":{"const":"NONE"},"network_kernel_confinement":{"const":"NOT_IMPLEMENTED_IN_K7_L_V1"},"origin_id":{"minLength":1,"type":"string"},"output_limit_exceeded":{"type":"boolean"},"persistent_write_authority_granted":{"const":"NONE"},"privileged_authority_granted":{"const":"NONE"},"process_started":{"type":"boolean"},"profile_output_contract_pass":{"type":"boolean"},"receipt_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"schema":{"const":"gg.local-tool-execution-receipt.v1"},"selected_action_node_id":{"pattern":"^[0-9a-f]{64}$","type":"string"},"signal":{"anyOf":[{"type":"integer"},{"type":"null"}]},"status":{"enum":["COMPLETED","TIMED_OUT","OUTPUT_LIMIT_STOP","SPAWN_FAILED","OUTPUT_CONTRACT_MISMATCH","TARGET_MUTATION_DETECTED","EXECUTABLE_MUTATION_DETECTED"]},"stderr_bytes":{"minimum":0,"type":"integer"},"stderr_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"stdout_bytes":{"minimum":0,"type":"integer"},"stdout_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"target_device":{"minimum":0,"type":"integer"},"target_fd_matches_expected_after":{"type":"boolean"},"target_fd_matches_expected_before":{"type":"boolean"},"target_fd_number":{"const":3},"target_fd_sha256_after":{"pattern":"^[0-9a-f]{64}$","type":"string"},"target_fd_sha256_before":{"pattern":"^[0-9a-f]{64}$","type":"string"},"target_inode":{"minimum":0,"type":"integer"},"task_id":{"minLength":1,"type":"string"},"termination_trigger":{"enum":["NONE","TIMEOUT","OUTPUT_LIMIT"]},"timed_out":{"type":"boolean"},"timeout_seconds":{"const":5},"tool_execution_binding_revision":{"pattern":"^[0-9a-f]{64}$","type":"string"},"tool_profile_id":{"const":"GG_K7K_STATUS_SHA256_READONLY_FD34_V1"},"tool_profile_revision":{"const":"0a0282535c6395fdc53a81722fd99bd0d1825c7e3679be61b39a9ea68ad916fe"},"tool_profile_scope_marker":{"type":"string"}},"required":["action_trace_sha256","approval_request_capture_sha256","approval_scope_revision","argv","backend","controlled_tool_decision_sha256","cwd","declared_target_path","duration_ms","dynamic_runtime_dependency_content_authority","environment_names","executable_device","executable_fd_matches_expected_after","executable_fd_matches_expected_before","executable_fd_number","executable_fd_sha256_after","executable_fd_sha256_before","executable_gid","executable_inode","executable_mode","executable_path","executable_reference_path","executable_sha256","executable_uid","execution_request_sha256","exit_code","filesystem_write_kernel_confinement","general_binary_behavior_sandbox","mandate_assertion_sha256","mandate_evaluation_result_sha256","max_stderr_bytes","max_stdout_bytes","network_authority_granted","network_kernel_confinement","origin_id","output_limit_exceeded","persistent_write_authority_granted","privileged_authority_granted","process_started","profile_output_contract_pass","receipt_sha256","schema","selected_action_node_id","signal","status","stderr_bytes","stderr_sha256","stdout_bytes","stdout_sha256","target_device","target_fd_matches_expected_after","target_fd_matches_expected_before","target_fd_number","target_fd_sha256_after","target_fd_sha256_before","target_inode","task_id","termination_trigger","timed_out","timeout_seconds","tool_execution_binding_revision","tool_profile_id","tool_profile_revision","tool_profile_scope_marker"],"type":"object"}},"$id":"gg.local-tool-profile-registry.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"profiles":{"items":{"$ref":"#/$defs/profile"},"maxItems":1,"minItems":1,"type":"array"},"registry_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"schema":{"const":"gg.local-tool-profile-registry.v1"}},"required":["schema","profiles","registry_sha256"],"title":"GG Controlled Local Tool Execution v1.4","type":"object"}\n'

_DECISION_FIELDS = frozenset(['action_trace_sha256', 'approval_request_capture_sha256', 'approval_scope_revision', 'decision_sha256', 'mandate_assertion_sha256', 'mandate_evaluation_result', 'mandate_evaluation_result_sha256', 'reason_code', 'result', 'schema', 'selected_action_node_id', 'tool_execution_binding_revision', 'tool_profile_id', 'tool_profile_revision', 'tool_profile_scope_marker'])
_DECISION_RESULTS = frozenset(("EXECUTION_ELIGIBLE", "EXECUTION_BLOCKED"))
_REASON_CODES = frozenset(['GREEN_PROFILE_MANDATE_NOT_REQUIRED', 'GREEN_PROFILE_MANDATE_VALID', 'K7_K_MANDATE_REQUIRED', 'K7_K_MANDATE_MISMATCH', 'K7_K_MANDATE_BLOCKED', 'K7_L_RISK_CLASS_UNSUPPORTED', 'PROFILE_SCOPE_MARKER_MISMATCH'])
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MARKER_RE = re.compile(r"^gg\.local-tool-profile\.v1:[0-9a-f]{64}$")

_PROFILE_DOMAIN = b"gg.local-tool-profile.v1\n"
_REGISTRY_DOMAIN = b"gg.local-tool-profile-registry.v1\n"
_BINDING_DOMAIN = b"gg.controlled-tool-binding.v1\n"
_DECISION_DOMAIN = b"gg.controlled-tool-decision.v1\n"
_K7K_EVALUATION_DOMAIN = b"gg.k7k-mandate-evaluation-result.v1\n"


class ControlledToolExecutionError(ValueError):
    def __init__(self, code: str, cause_code: str):
        super().__init__(code + ":" + cause_code)
        self.code = code
        self.cause_code = cause_code


def _fail(cause_code: str) -> None:
    raise ControlledToolExecutionError("STOP_CONTROLLED_TOOL", cause_code)


def canonical_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "CANONICAL_JSON_INVALID",
        ) from exc


def schema_document() -> dict[str, Any]:
    return json.loads(_SCHEMA_JSON)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_text(value: Any, cause: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _fail(cause)
    return value


def _exact_dict(value: Any, fields: frozenset[str], cause: str) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != fields:
        _fail(cause)
    return value


def _capture_regular(path: pathlib.Path, expected_sha256: str, cause_prefix: str) -> bytes:
    if not hasattr(os, "O_NOFOLLOW"):
        _fail(cause_prefix + "_O_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            cause_prefix + "_OPEN_FAILED",
        ) from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _fail(cause_prefix + "_NOT_REGULAR")
        chunks: list[bytes] = []
        while True:
            part = os.read(fd, 1024 * 1024)
            if not part:
                break
            chunks.append(part)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            _fail(cause_prefix + "_IDENTITY_CHANGED")
        if _sha256(raw) != expected_sha256:
            _fail(cause_prefix + "_SHA256_MISMATCH")
        return raw
    finally:
        os.close(fd)


def _runtime_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def _registry_path() -> pathlib.Path:
    return (_runtime_root() / K7_L_REGISTRY_RUNTIME_RELATIVE).resolve()


def _k7k_path() -> pathlib.Path:
    return _runtime_root() / K7_K_RUNTIME_FILENAME


def profile_revision(profile_without_revision: dict[str, Any]) -> str:
    return _sha256(_PROFILE_DOMAIN + canonical_json(profile_without_revision))


def registry_sha256(registry_without_sha256: dict[str, Any]) -> str:
    return _sha256(_REGISTRY_DOMAIN + canonical_json(registry_without_sha256))


def _profile_expected_fields() -> frozenset[str]:
    return frozenset(['argv', 'automatic_retry', 'backend', 'background_execution', 'cwd', 'declared_target_path', 'declared_target_sha256', 'dynamic_runtime_dependency_content_authority', 'effect_class', 'environment', 'executable_fd_number', 'executable_open_flags', 'executable_package', 'executable_path', 'executable_reference_path', 'executable_require_regular_file', 'executable_required_gid', 'executable_required_mode', 'executable_required_uid', 'executable_sha256', 'expected_exit_code', 'expected_stderr_utf8', 'expected_stdout_utf8', 'filesystem_write_kernel_confinement', 'general_binary_behavior_sandbox', 'max_stderr_bytes', 'max_stdout_bytes', 'network_authority_granted', 'network_kernel_confinement', 'parameterized_argv', 'persistent_write_authority_granted', 'privileged_authority_granted', 'process_start_count_max', 'profile_id', 'profile_revision', 'risk_class', 'schema', 'shell_execution', 'stdin_policy', 'target_fd_number', 'target_open_flags', 'target_reference_path', 'target_require_regular_file', 'timeout_seconds'])


def validate_profile_registry(value: Any) -> dict[str, Any]:
    registry = _exact_dict(
        value,
        frozenset(("schema", "profiles", "registry_sha256")),
        "REGISTRY_FIELDS_INVALID",
    )
    if registry["schema"] != SCHEMA_ID:
        _fail("REGISTRY_SCHEMA_INVALID")
    profiles = registry["profiles"]
    if not isinstance(profiles, list) or len(profiles) != 1:
        _fail("REGISTRY_PROFILE_CARDINALITY_INVALID")
    profile = _exact_dict(
        profiles[0],
        _profile_expected_fields(),
        "PROFILE_FIELDS_INVALID",
    )
    expected_constants = {
        "schema": PROFILE_SCHEMA_ID,
        "profile_id": PROFILE_ID,
        "profile_revision": PROFILE_REVISION,
        "backend": "SUBPROCESS_POPEN_FD34_PINNED_V1",
        "risk_class": "GREEN",
        "effect_class": "READ_ONLY",
        "executable_path": "/usr/bin/sha256sum",
        "executable_sha256": "f68bf52a31beac0119654d4ac4a27b63d03a97bbdf2eb6a06ba5e4a6fbcbf652",
        "executable_package": "coreutils|0|9.10|4.fc44|x86_64",
        "executable_fd_number": 4,
        "executable_reference_path": "/proc/self/fd/4",
        "executable_open_flags": ["O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"],
        "executable_require_regular_file": True,
        "executable_required_uid": 0,
        "executable_required_gid": 0,
        "executable_required_mode": "0755",
        "argv": ["/usr/bin/sha256sum", "--", "/proc/self/fd/3"],
        "cwd": "/home/GG/GoldGoblins",
        "environment": {
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "stdin_policy": "DEVNULL",
        "timeout_seconds": 5,
        "max_stdout_bytes": 4096,
        "max_stderr_bytes": 4096,
        "network_authority_granted": "NONE",
        "privileged_authority_granted": "NONE",
        "persistent_write_authority_granted": "NONE",
        "network_kernel_confinement": "NOT_IMPLEMENTED_IN_K7_L_V1",
        "filesystem_write_kernel_confinement": "NOT_IMPLEMENTED_IN_K7_L_V1",
        "general_binary_behavior_sandbox": "NOT_IMPLEMENTED",
        "dynamic_runtime_dependency_content_authority": "NOT_PINNED",
        "declared_target_path": "/home/GG/GoldGoblins/status/SYSTEMSTATUS-K7-K-MANDATE-APPROVAL-COMPLETE-LOCAL-2026-08-10-v1.0.md",
        "declared_target_sha256": "3198274dadb91b66d8b919467e4cdc3529408e62ab5bb9f97896a2107e4edc2c",
        "target_fd_number": 3,
        "target_reference_path": "/proc/self/fd/3",
        "target_open_flags": ["O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"],
        "target_require_regular_file": True,
        "expected_exit_code": 0,
        "expected_stdout_utf8": "3198274dadb91b66d8b919467e4cdc3529408e62ab5bb9f97896a2107e4edc2c  /proc/self/fd/3\n",
        "expected_stderr_utf8": "",
        "process_start_count_max": 1,
        "automatic_retry": False,
        "background_execution": False,
        "parameterized_argv": False,
        "shell_execution": False,
    }
    for key, expected in expected_constants.items():
        if profile.get(key) != expected:
            _fail("PROFILE_CONSTANT_MISMATCH:" + key)
    without_revision = {k: copy.deepcopy(v) for k, v in profile.items() if k != "profile_revision"}
    if profile_revision(without_revision) != profile["profile_revision"]:
        _fail("PROFILE_REVISION_MISMATCH")
    base = {k: copy.deepcopy(v) for k, v in registry.items() if k != "registry_sha256"}
    if registry_sha256(base) != registry["registry_sha256"]:
        _fail("REGISTRY_SEMANTIC_SHA256_MISMATCH")
    return copy.deepcopy(registry)


def _load_registry() -> dict[str, Any]:
    raw = _capture_regular(
        _registry_path(),
        K7_L_PROTOCOL_REGISTRY_SHA256,
        "REGISTRY_AUTHORITY",
    )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "REGISTRY_JSON_INVALID",
        ) from exc
    validated = validate_profile_registry(parsed)
    if canonical_json(validated) != raw:
        _fail("REGISTRY_NONCANONICAL_BYTES")
    return validated


def _load_k7k() -> dict[str, Any]:
    path = _k7k_path()
    raw = _capture_regular(path, K7_K_RUNTIME_SHA256, "K7_K_AUTHORITY")
    namespace: dict[str, Any] = {
        "__file__": str(path),
        "__name__": "_gg_k7l_exact_k7k_authority",
        "__package__": None,
    }
    try:
        exec(compile(raw, str(path), "exec"), namespace, namespace)
    except BaseException as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "K7_K_AUTHORITY_EXEC_FAILED",
        ) from exc
    required = (
        "MandateApprovalError",
        "canonical_json",
        "validate_approval_request",
        "evaluate_mandate",
    )
    for name in required:
        if name not in namespace:
            _fail("K7_K_AUTHORITY_PRIMITIVE_MISSING:" + name)
    return namespace


def tool_execution_binding_revision(
    approval_scope_revision: str,
    selected_action_node_id: str,
    action_trace_sha256: str,
    tool_profile_id: str,
    tool_profile_revision_value: str,
) -> str:
    value = {
        "approval_scope_revision": _sha_text(
            approval_scope_revision, "BINDING_APPROVAL_SCOPE_INVALID"
        ),
        "selected_action_node_id": _sha_text(
            selected_action_node_id, "BINDING_ACTION_NODE_INVALID"
        ),
        "action_trace_sha256": _sha_text(
            action_trace_sha256, "BINDING_ACTION_TRACE_INVALID"
        ),
        "tool_profile_id": tool_profile_id,
        "tool_profile_revision": _sha_text(
            tool_profile_revision_value, "BINDING_PROFILE_REVISION_INVALID"
        ),
    }
    if tool_profile_id != PROFILE_ID:
        _fail("BINDING_PROFILE_ID_INVALID")
    return _sha256(_BINDING_DOMAIN + canonical_json(value))


def _decision_hash(value_without_hash: dict[str, Any]) -> str:
    return _sha256(_DECISION_DOMAIN + canonical_json(value_without_hash))


def validate_execution_decision(value: Any) -> dict[str, Any]:
    decision = _exact_dict(value, _DECISION_FIELDS, "DECISION_FIELDS_INVALID")
    if decision["schema"] != DECISION_SCHEMA_ID:
        _fail("DECISION_SCHEMA_INVALID")
    for key in (
        "approval_request_capture_sha256",
        "mandate_evaluation_result_sha256",
        "approval_scope_revision",
        "selected_action_node_id",
        "action_trace_sha256",
        "tool_profile_revision",
        "tool_execution_binding_revision",
        "decision_sha256",
    ):
        _sha_text(decision[key], "DECISION_SHA_INVALID:" + key)
    assertion_sha = decision["mandate_assertion_sha256"]
    if assertion_sha is not None:
        _sha_text(assertion_sha, "DECISION_ASSERTION_SHA_INVALID")
    if decision["tool_profile_id"] != PROFILE_ID:
        _fail("DECISION_PROFILE_ID_INVALID")
    if decision["tool_profile_revision"] != PROFILE_REVISION:
        _fail("DECISION_PROFILE_REVISION_INVALID")
    if decision["tool_profile_scope_marker"] != TOOL_PROFILE_SCOPE_MARKER:
        _fail("DECISION_PROFILE_MARKER_INVALID")
    if decision["result"] not in _DECISION_RESULTS:
        _fail("DECISION_RESULT_INVALID")
    if decision["reason_code"] not in _REASON_CODES:
        _fail("DECISION_REASON_INVALID")
    without = {k: copy.deepcopy(v) for k, v in decision.items() if k != "decision_sha256"}
    if _decision_hash(without) != decision["decision_sha256"]:
        _fail("DECISION_SHA256_MISMATCH")
    return copy.deepcopy(decision)


def _request_risk(validated_request: dict[str, Any]) -> str:
    try:
        return validated_request["approval_scope"]["ready_core"]["risk_class"]
    except (KeyError, TypeError) as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "APPROVAL_REQUEST_RISK_SURFACE_INVALID",
        ) from exc


def _request_marker(validated_request: dict[str, Any]) -> tuple[str | None, int]:
    try:
        scope = validated_request["approval_scope"]["ready_core"]["scope"]
    except (KeyError, TypeError) as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "APPROVAL_REQUEST_SCOPE_SURFACE_INVALID",
        ) from exc
    if not isinstance(scope, list) or any(not isinstance(x, str) for x in scope):
        _fail("APPROVAL_REQUEST_SCOPE_INVALID")
    matches = [x for x in scope if _MARKER_RE.fullmatch(x)]
    return (matches[0] if len(matches) == 1 else None, len(matches))


def evaluate_controlled_tool(
    approval_request: dict[str, Any],
    tool_profile_id: str,
    mandate_assertion: dict[str, Any] | None,
    source_envelope: dict[str, Any],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    state_base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
) -> dict[str, Any]:
    if tool_profile_id != PROFILE_ID:
        _fail("TOOL_PROFILE_ID_UNSUPPORTED")
    registry = _load_registry()
    profile = registry["profiles"][0]
    k7k = _load_k7k()
    try:
        validated_request = k7k["validate_approval_request"](approval_request)
    except BaseException as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "K7_K_APPROVAL_REQUEST_INVALID",
        ) from exc
    if not isinstance(validated_request, dict):
        _fail("K7_K_APPROVAL_REQUEST_RETURN_INVALID")
    try:
        evaluation = k7k["evaluate_mandate"](
            approval_request,
            mandate_assertion,
            source_envelope,
            goal_chain,
            hypothesis_state,
            state_base,
            ledger_records,
            memory_records,
        )
    except BaseException as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "K7_K_MANDATE_EVALUATION_FAILED",
        ) from exc
    if not isinstance(evaluation, dict):
        _fail("K7_K_MANDATE_EVALUATION_RETURN_INVALID")
    result = evaluation.get("result")
    reason_map = {
        "MANDATE_REQUIRED": "K7_K_MANDATE_REQUIRED",
        "MANDATE_MISMATCH": "K7_K_MANDATE_MISMATCH",
        "MANDATE_BLOCKED": "K7_K_MANDATE_BLOCKED",
    }
    if result in reason_map:
        decision_result = "EXECUTION_BLOCKED"
        reason = reason_map[result]
    elif result not in ("MANDATE_NOT_REQUIRED", "MANDATE_VALID"):
        _fail("K7_K_MANDATE_RESULT_UNSUPPORTED")
    else:
        risk = _request_risk(validated_request)
        if risk != "GREEN":
            decision_result = "EXECUTION_BLOCKED"
            reason = "K7_L_RISK_CLASS_UNSUPPORTED"
        else:
            marker, count = _request_marker(validated_request)
            if count != 1 or marker != TOOL_PROFILE_SCOPE_MARKER:
                decision_result = "EXECUTION_BLOCKED"
                reason = "PROFILE_SCOPE_MARKER_MISMATCH"
            else:
                decision_result = "EXECUTION_ELIGIBLE"
                reason = (
                    "GREEN_PROFILE_MANDATE_NOT_REQUIRED"
                    if result == "MANDATE_NOT_REQUIRED"
                    else "GREEN_PROFILE_MANDATE_VALID"
                )
    try:
        scope = validated_request["approval_scope"]
        approval_scope_revision = validated_request["approval_scope_revision"]
        request_capture = validated_request["request_capture_sha256"]
        selected_action = scope["selected_action_node_id"]
        action_trace = scope["action_trace_sha256"]
    except (KeyError, TypeError) as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "K7_K_APPROVAL_REQUEST_SURFACE_INVALID",
        ) from exc
    assertion_sha = evaluation.get("mandate_assertion_sha256")
    if assertion_sha is not None:
        _sha_text(assertion_sha, "K7_K_ASSERTION_SHA_INVALID")
    binding = tool_execution_binding_revision(
        approval_scope_revision,
        selected_action,
        action_trace,
        profile["profile_id"],
        profile["profile_revision"],
    )
    try:
        evaluation_bytes = k7k["canonical_json"](evaluation)
    except BaseException as exc:
        raise ControlledToolExecutionError(
            "STOP_CONTROLLED_TOOL",
            "K7_K_CANONICAL_JSON_FAILED",
        ) from exc
    if not isinstance(evaluation_bytes, (bytes, bytearray)):
        _fail("K7_K_CANONICAL_JSON_RETURN_INVALID")
    decision = {
        "schema": DECISION_SCHEMA_ID,
        "approval_request_capture_sha256": request_capture,
        "mandate_assertion_sha256": assertion_sha,
        "mandate_evaluation_result_sha256": _sha256(
            _K7K_EVALUATION_DOMAIN + bytes(evaluation_bytes)
        ),
        "mandate_evaluation_result": copy.deepcopy(evaluation),
        "approval_scope_revision": approval_scope_revision,
        "selected_action_node_id": selected_action,
        "action_trace_sha256": action_trace,
        "tool_profile_scope_marker": TOOL_PROFILE_SCOPE_MARKER,
        "tool_profile_id": profile["profile_id"],
        "tool_profile_revision": profile["profile_revision"],
        "tool_execution_binding_revision": binding,
        "result": decision_result,
        "reason_code": reason,
    }
    decision["decision_sha256"] = _decision_hash(decision)
    return validate_execution_decision(decision)
