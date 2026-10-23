from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import selectors
import stat
import subprocess
import time
from typing import Any

K7_L_PROTOCOL_RELATIVE = "../../cognitive-core/gg_controlled_tool_execution.py"
K7_L_EXECUTOR_PROTOCOL_SHA256 = "e2c9e0c3ce336a461ce35af4390a26deebb271a4ec0fe6b22f283f4a939bf1cb"
K7_L_REGISTRY_RELATIVE = "tool-profiles.json"
K7_L_EXECUTOR_REGISTRY_SHA256 = "c9124417e7131332535dd8c850961b2feba4b9071719e0e2f63a3905d7f492d8"

PROFILE_ID = "GG_K7K_STATUS_SHA256_READONLY_FD34_V1"
PROFILE_REVISION = "0a0282535c6395fdc53a81722fd99bd0d1825c7e3679be61b39a9ea68ad916fe"
RECEIPT_SCHEMA_ID = "gg.local-tool-execution-receipt.v1"

TARGET_EXPECTED_SHA256 = "3198274dadb91b66d8b919467e4cdc3529408e62ab5bb9f97896a2107e4edc2c"
EXECUTABLE_EXPECTED_SHA256 = "f68bf52a31beac0119654d4ac4a27b63d03a97bbdf2eb6a06ba5e4a6fbcbf652"

NETWORK_AUTHORITY_GRANTED = "NONE"
PRIVILEGED_AUTHORITY_GRANTED = "NONE"
PERSISTENT_WRITE_AUTHORITY_GRANTED = "NONE"
NETWORK_KERNEL_CONFINEMENT = "NOT_IMPLEMENTED_IN_K7_L_V1"
FILESYSTEM_WRITE_KERNEL_CONFINEMENT = "NOT_IMPLEMENTED_IN_K7_L_V1"
GENERAL_BINARY_BEHAVIOR_SANDBOX = "NOT_IMPLEMENTED"
DYNAMIC_RUNTIME_DEPENDENCY_CONTENT_AUTHORITY = "NOT_PINNED"
EXACT_PROCESS_IMAGE = "NO"
GENERAL_ACTION_AUTHORITY = "NONE"
SYSTEM_ALIVE_LOCAL = "NOT_YET"

_RECEIPT_DOMAIN = b"gg.local-tool-execution-receipt.v1\n"
_EXECUTION_REQUEST_DOMAIN = b"gg.local-tool-execution-request.v1\n"
_K7_L_EXECUTOR_CHILD_PROCESS_START_COUNT_TOTAL = 0


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_FIELDS = frozenset(['action_trace_sha256', 'approval_request_capture_sha256', 'approval_scope_revision', 'argv', 'backend', 'controlled_tool_decision_sha256', 'cwd', 'declared_target_path', 'duration_ms', 'dynamic_runtime_dependency_content_authority', 'environment_names', 'executable_device', 'executable_fd_matches_expected_after', 'executable_fd_matches_expected_before', 'executable_fd_number', 'executable_fd_sha256_after', 'executable_fd_sha256_before', 'executable_gid', 'executable_inode', 'executable_mode', 'executable_path', 'executable_reference_path', 'executable_sha256', 'executable_uid', 'execution_request_sha256', 'exit_code', 'filesystem_write_kernel_confinement', 'general_binary_behavior_sandbox', 'mandate_assertion_sha256', 'mandate_evaluation_result_sha256', 'max_stderr_bytes', 'max_stdout_bytes', 'network_authority_granted', 'network_kernel_confinement', 'origin_id', 'output_limit_exceeded', 'persistent_write_authority_granted', 'privileged_authority_granted', 'process_started', 'profile_output_contract_pass', 'receipt_sha256', 'schema', 'selected_action_node_id', 'signal', 'status', 'stderr_bytes', 'stderr_sha256', 'stdout_bytes', 'stdout_sha256', 'target_device', 'target_fd_matches_expected_after', 'target_fd_matches_expected_before', 'target_fd_number', 'target_fd_sha256_after', 'target_fd_sha256_before', 'target_inode', 'task_id', 'termination_trigger', 'timed_out', 'timeout_seconds', 'tool_execution_binding_revision', 'tool_profile_id', 'tool_profile_revision', 'tool_profile_scope_marker'])
_RECEIPT_STATUSES = frozenset(['COMPLETED', 'TIMED_OUT', 'OUTPUT_LIMIT_STOP', 'SPAWN_FAILED', 'OUTPUT_CONTRACT_MISMATCH', 'TARGET_MUTATION_DETECTED', 'EXECUTABLE_MUTATION_DETECTED'])
_TERMINATION_TRIGGERS = frozenset(['NONE', 'TIMEOUT', 'OUTPUT_LIMIT'])
_TOOL_PROFILE_SCOPE_MARKER = "gg.local-tool-profile.v1:0a0282535c6395fdc53a81722fd99bd0d1825c7e3679be61b39a9ea68ad916fe"
_EXPECTED_ARGV = ["/usr/bin/sha256sum", "--", "/proc/self/fd/3"]
_EXPECTED_CWD = "/home/GG/GoldGoblins"
_EXPECTED_TARGET_PATH = "/home/GG/GoldGoblins/status/SYSTEMSTATUS-K7-K-MANDATE-APPROVAL-COMPLETE-LOCAL-2026-08-10-v1.0.md"
_EXPECTED_STDOUT = (
    TARGET_EXPECTED_SHA256 + "  /proc/self/fd/3\n"
).encode("utf-8")
_EXPECTED_STDERR = b""
_EXPECTED_ENVIRONMENT_NAMES = ["LC_ALL", "PATH", "PYTHONDONTWRITEBYTECODE"]


class _ReceiptValidationFailure(Exception):
    pass


def _receipt_fail(cause: str) -> None:
    raise _ReceiptValidationFailure(cause)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _receipt_sha_text(value: Any, cause: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _receipt_fail(cause)
    return value


def _receipt_exact_int(value: Any, expected: int, cause: str) -> None:
    if not _is_int(value) or value != expected:
        _receipt_fail(cause)


def _receipt_nonnegative_int(value: Any, cause: str) -> None:
    if not _is_int(value) or value < 0:
        _receipt_fail(cause)


def _validate_execution_receipt_private(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != _RECEIPT_FIELDS:
        _receipt_fail("RECEIPT_FIELDS_INVALID")

    receipt = copy.deepcopy(value)

    if receipt["schema"] != RECEIPT_SCHEMA_ID:
        _receipt_fail("RECEIPT_SCHEMA_INVALID")

    for key in (
        "approval_request_capture_sha256",
        "mandate_evaluation_result_sha256",
        "controlled_tool_decision_sha256",
        "execution_request_sha256",
        "selected_action_node_id",
        "action_trace_sha256",
        "approval_scope_revision",
        "tool_execution_binding_revision",
        "tool_profile_revision",
        "target_fd_sha256_before",
        "target_fd_sha256_after",
        "executable_sha256",
        "executable_fd_sha256_before",
        "executable_fd_sha256_after",
        "stdout_sha256",
        "stderr_sha256",
        "receipt_sha256",
    ):
        _receipt_sha_text(receipt[key], "RECEIPT_SHA_INVALID:" + key)

    assertion_sha = receipt["mandate_assertion_sha256"]
    if assertion_sha is not None:
        _receipt_sha_text(assertion_sha, "RECEIPT_ASSERTION_SHA_INVALID")

    for key in ("task_id", "origin_id"):
        if not isinstance(receipt[key], str) or not receipt[key]:
            _receipt_fail("RECEIPT_TEXT_INVALID:" + key)

    constants = {
        "backend": "SUBPROCESS_POPEN_FD34_PINNED_V1",
        "executable_path": "/usr/bin/sha256sum",
        "executable_sha256": EXECUTABLE_EXPECTED_SHA256,
        "cwd": _EXPECTED_CWD,
        "network_authority_granted": "NONE",
        "privileged_authority_granted": "NONE",
        "persistent_write_authority_granted": "NONE",
        "network_kernel_confinement": "NOT_IMPLEMENTED_IN_K7_L_V1",
        "filesystem_write_kernel_confinement": "NOT_IMPLEMENTED_IN_K7_L_V1",
        "general_binary_behavior_sandbox": "NOT_IMPLEMENTED",
        "dynamic_runtime_dependency_content_authority": "NOT_PINNED",
        "declared_target_path": _EXPECTED_TARGET_PATH,
        "executable_reference_path": "/proc/self/fd/4",
        "executable_mode": "0755",
        "tool_profile_id": PROFILE_ID,
        "tool_profile_revision": PROFILE_REVISION,
        "tool_profile_scope_marker": _TOOL_PROFILE_SCOPE_MARKER,
    }
    for key, expected in constants.items():
        if receipt[key] != expected:
            _receipt_fail("RECEIPT_CONST_INVALID:" + key)

    if receipt["argv"] != _EXPECTED_ARGV:
        _receipt_fail("RECEIPT_ARGV_INVALID")
    if receipt["environment_names"] != _EXPECTED_ENVIRONMENT_NAMES:
        _receipt_fail("RECEIPT_ENVIRONMENT_NAMES_INVALID")

    for key, expected in (
        ("target_fd_number", 3),
        ("executable_fd_number", 4),
        ("executable_uid", 0),
        ("executable_gid", 0),
        ("timeout_seconds", 5),
        ("max_stdout_bytes", 4096),
        ("max_stderr_bytes", 4096),
    ):
        _receipt_exact_int(receipt[key], expected, "RECEIPT_INT_CONST_INVALID:" + key)

    for key in (
        "target_device",
        "target_inode",
        "executable_device",
        "executable_inode",
        "stdout_bytes",
        "stderr_bytes",
        "duration_ms",
    ):
        _receipt_nonnegative_int(receipt[key], "RECEIPT_NONNEGATIVE_INT_INVALID:" + key)

    for key in (
        "target_fd_matches_expected_before",
        "target_fd_matches_expected_after",
        "executable_fd_matches_expected_before",
        "executable_fd_matches_expected_after",
        "process_started",
        "timed_out",
        "output_limit_exceeded",
        "profile_output_contract_pass",
    ):
        if type(receipt[key]) is not bool:
            _receipt_fail("RECEIPT_BOOL_INVALID:" + key)

    exit_code = receipt["exit_code"]
    signal_value = receipt["signal"]
    if exit_code is not None and not _is_int(exit_code):
        _receipt_fail("RECEIPT_EXIT_CODE_INVALID")
    if signal_value is not None and (not _is_int(signal_value) or signal_value <= 0):
        _receipt_fail("RECEIPT_SIGNAL_INVALID")

    trigger = receipt["termination_trigger"]
    if trigger not in _TERMINATION_TRIGGERS:
        _receipt_fail("RECEIPT_TERMINATION_TRIGGER_INVALID")
    status = receipt["status"]
    if status not in _RECEIPT_STATUSES:
        _receipt_fail("RECEIPT_STATUS_INVALID")

    if receipt["target_fd_matches_expected_before"] != (
        receipt["target_fd_sha256_before"] == TARGET_EXPECTED_SHA256
    ):
        _receipt_fail("RECEIPT_TARGET_BEFORE_BOOLEAN_MISMATCH")
    if receipt["target_fd_matches_expected_after"] != (
        receipt["target_fd_sha256_after"] == TARGET_EXPECTED_SHA256
    ):
        _receipt_fail("RECEIPT_TARGET_AFTER_BOOLEAN_MISMATCH")
    if receipt["executable_fd_matches_expected_before"] != (
        receipt["executable_fd_sha256_before"] == EXECUTABLE_EXPECTED_SHA256
    ):
        _receipt_fail("RECEIPT_EXECUTABLE_BEFORE_BOOLEAN_MISMATCH")
    if receipt["executable_fd_matches_expected_after"] != (
        receipt["executable_fd_sha256_after"] == EXECUTABLE_EXPECTED_SHA256
    ):
        _receipt_fail("RECEIPT_EXECUTABLE_AFTER_BOOLEAN_MISMATCH")

    # A receipt-capable execution stage is reached only after exact pre-hash checks.
    if not receipt["target_fd_matches_expected_before"]:
        _receipt_fail("RECEIPT_TARGET_PRECONDITION_NOT_MET")
    if not receipt["executable_fd_matches_expected_before"]:
        _receipt_fail("RECEIPT_EXECUTABLE_PRECONDITION_NOT_MET")

    if receipt["timed_out"] != (trigger == "TIMEOUT"):
        _receipt_fail("RECEIPT_TIMEOUT_BOOLEAN_MISMATCH")
    if receipt["output_limit_exceeded"] != (trigger == "OUTPUT_LIMIT"):
        _receipt_fail("RECEIPT_OUTPUT_LIMIT_BOOLEAN_MISMATCH")

    process_started = receipt["process_started"]
    if process_started:
        valid_terminal = (
            (exit_code is not None and signal_value is None)
            or (exit_code is None and signal_value is not None)
        )
        if not valid_terminal:
            _receipt_fail("RECEIPT_PROCESS_TERMINAL_STATE_INVALID")
    else:
        if exit_code is not None or signal_value is not None:
            _receipt_fail("RECEIPT_UNSTARTED_PROCESS_HAS_TERMINAL_STATE")
        if trigger != "NONE":
            _receipt_fail("RECEIPT_UNSTARTED_PROCESS_HAS_TRIGGER")

    stdout_matches_expected = (
        receipt["stdout_bytes"] == len(_EXPECTED_STDOUT)
        and receipt["stdout_sha256"] == _sha256(_EXPECTED_STDOUT)
    )
    stderr_matches_expected = (
        receipt["stderr_bytes"] == len(_EXPECTED_STDERR)
        and receipt["stderr_sha256"] == _sha256(_EXPECTED_STDERR)
    )
    output_contract_expected = (
        process_started
        and trigger == "NONE"
        and exit_code == 0
        and signal_value is None
        and stdout_matches_expected
        and stderr_matches_expected
    )
    if receipt["profile_output_contract_pass"] != output_contract_expected:
        _receipt_fail("RECEIPT_OUTPUT_CONTRACT_BOOLEAN_MISMATCH")

    if not receipt["executable_fd_matches_expected_after"]:
        expected_status = "EXECUTABLE_MUTATION_DETECTED"
    elif not receipt["target_fd_matches_expected_after"]:
        expected_status = "TARGET_MUTATION_DETECTED"
    elif not process_started:
        expected_status = "SPAWN_FAILED"
    elif trigger == "TIMEOUT":
        expected_status = "TIMED_OUT"
    elif trigger == "OUTPUT_LIMIT":
        expected_status = "OUTPUT_LIMIT_STOP"
    elif not output_contract_expected:
        expected_status = "OUTPUT_CONTRACT_MISMATCH"
    else:
        expected_status = "COMPLETED"

    if status != expected_status:
        _receipt_fail("RECEIPT_STATUS_PRECEDENCE_MISMATCH")

    if status == "SPAWN_FAILED":
        if receipt["stdout_bytes"] != 0 or receipt["stderr_bytes"] != 0:
            _receipt_fail("RECEIPT_SPAWN_FAILED_OUTPUT_INVALID")
        if receipt["stdout_sha256"] != _sha256(b"") or receipt["stderr_sha256"] != _sha256(b""):
            _receipt_fail("RECEIPT_SPAWN_FAILED_OUTPUT_SHA_INVALID")

    without_hash = {
        key: copy.deepcopy(item)
        for key, item in receipt.items()
        if key != "receipt_sha256"
    }
    if _receipt_hash(without_hash) != receipt["receipt_sha256"]:
        _receipt_fail("RECEIPT_SHA256_MISMATCH")

    return receipt


def validate_execution_receipt(value: Any) -> dict[str, Any]:
    try:
        return _validate_execution_receipt_private(value)
    except _ReceiptValidationFailure as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            "RECEIPT_VALIDATION_FAILED:" + str(exc),
            None,
        ) from exc


class LocalToolExecutorError(RuntimeError):
    def __init__(
        self,
        code: str,
        cause_code: str,
        receipt: dict[str, Any] | None = None,
    ):
        if receipt is not None:
            try:
                receipt = _validate_execution_receipt_private(receipt)
            except _ReceiptValidationFailure:
                code = "STOP_LOCAL_EXECUTOR"
                cause_code = "INVALID_ERROR_RECEIPT"
                receipt = None
        super().__init__(code + ":" + cause_code)
        self.code = code
        self.cause_code = cause_code
        self.receipt = copy.deepcopy(receipt)


def _stop(cause: str, receipt: dict[str, Any] | None = None) -> None:
    raise LocalToolExecutorError("STOP_LOCAL_EXECUTOR", cause, receipt)


def canonical_json(value: Any) -> bytes:
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _capture_regular(path: pathlib.Path, expected_sha: str, prefix: str) -> bytes:
    if not hasattr(os, "O_NOFOLLOW"):
        _stop(prefix + "_O_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            prefix + "_OPEN_FAILED",
            None,
        ) from exc
    try:
        a = os.fstat(fd)
        if not stat.S_ISREG(a.st_mode):
            _stop(prefix + "_NOT_REGULAR")
        chunks: list[bytes] = []
        while True:
            part = os.read(fd, 1024 * 1024)
            if not part:
                break
            chunks.append(part)
        raw = b"".join(chunks)
        b = os.fstat(fd)
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            _stop(prefix + "_IDENTITY_CHANGED")
        if _sha256(raw) != expected_sha:
            _stop(prefix + "_SHA256_MISMATCH")
        return raw
    finally:
        os.close(fd)


def _module_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def _protocol_path() -> pathlib.Path:
    return (_module_root() / K7_L_PROTOCOL_RELATIVE).resolve()


def _registry_path() -> pathlib.Path:
    return (_module_root() / K7_L_REGISTRY_RELATIVE).resolve()


def _load_protocol() -> dict[str, Any]:
    path = _protocol_path()
    raw = _capture_regular(
        path,
        K7_L_EXECUTOR_PROTOCOL_SHA256,
        "K7_L_PROTOCOL_AUTHORITY",
    )
    ns: dict[str, Any] = {
        "__file__": str(path),
        "__name__": "_gg_k7l_exact_protocol_authority",
        "__package__": None,
    }
    try:
        exec(compile(raw, str(path), "exec"), ns, ns)
    except BaseException as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            "K7_L_PROTOCOL_EXEC_FAILED",
            None,
        ) from exc
    required = (
        "ControlledToolExecutionError",
        "canonical_json",
        "validate_profile_registry",
        "validate_execution_decision",
        "evaluate_controlled_tool",
    )
    for name in required:
        if name not in ns:
            _stop("K7_L_PROTOCOL_PRIMITIVE_MISSING:" + name)
    if ns.get("K7_L_PROTOCOL_REGISTRY_SHA256") != K7_L_EXECUTOR_REGISTRY_SHA256:
        _stop("PROTOCOL_EXECUTOR_REGISTRY_SHA_MISMATCH")
    return ns


def _load_registry(protocol: dict[str, Any]) -> dict[str, Any]:
    raw = _capture_regular(
        _registry_path(),
        K7_L_EXECUTOR_REGISTRY_SHA256,
        "K7_L_REGISTRY_AUTHORITY",
    )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            "REGISTRY_JSON_INVALID",
            None,
        ) from exc
    try:
        validated = protocol["validate_profile_registry"](parsed)
        canonical = protocol["canonical_json"](validated)
    except BaseException as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            "REGISTRY_PROTOCOL_VALIDATION_FAILED",
            None,
        ) from exc
    if not isinstance(canonical, (bytes, bytearray)) or bytes(canonical) != raw:
        _stop("REGISTRY_NONCANONICAL_BYTES")
    return validated


def _fd_is_closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


def _hash_fd(fd: int) -> str:
    h = hashlib.sha256()
    offset = 0
    while True:
        part = os.pread(fd, 1024 * 1024, offset)
        if not part:
            return h.hexdigest()
        h.update(part)
        offset += len(part)


def _proc_identity(fd: int, st: os.stat_result) -> bool:
    pst = os.stat("/proc/self/fd/" + str(fd), follow_symlinks=True)
    return (pst.st_dev, pst.st_ino) == (st.st_dev, st.st_ino)


def _open_pinned(path: str, expected_fd: int, cause: str) -> tuple[int, os.stat_result]:
    if not _fd_is_closed(expected_fd):
        _stop(cause + "_PREOPEN_FD_NOT_CLOSED")
    if not hasattr(os, "O_NOFOLLOW"):
        _stop(cause + "_O_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            cause + "_OPEN_FAILED",
            None,
        ) from exc
    if fd != expected_fd:
        os.close(fd)
        _stop(cause + "_FD_NUMBER_UNEXPECTED")
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        _stop(cause + "_NOT_REGULAR")
    if os.get_inheritable(fd):
        os.close(fd)
        _stop(cause + "_O_CLOEXEC_NOT_EFFECTIVE")
    if not _proc_identity(fd, st):
        os.close(fd)
        _stop(cause + "_PROC_IDENTITY_MISMATCH")
    return fd, st


def _execution_request_sha(decision: dict[str, Any]) -> str:
    value = {
        "approval_request_capture_sha256": decision["approval_request_capture_sha256"],
        "mandate_assertion_sha256": decision["mandate_assertion_sha256"],
        "mandate_evaluation_result_sha256": decision["mandate_evaluation_result_sha256"],
        "controlled_tool_decision_sha256": decision["decision_sha256"],
        "tool_execution_binding_revision": decision["tool_execution_binding_revision"],
        "tool_profile_id": decision["tool_profile_id"],
        "tool_profile_revision": decision["tool_profile_revision"],
    }
    return _sha256(_EXECUTION_REQUEST_DOMAIN + canonical_json(value))


def _receipt_hash(receipt_without_hash: dict[str, Any]) -> str:
    return _sha256(_RECEIPT_DOMAIN + canonical_json(receipt_without_hash))


def _base_receipt(
    approval_request: dict[str, Any],
    decision: dict[str, Any],
    profile: dict[str, Any],
    target_st: os.stat_result,
    exe_st: os.stat_result,
    target_before: str,
    exe_before: str,
) -> dict[str, Any]:
    try:
        task_id = approval_request["task_id"]
        origin_id = approval_request["origin_id"]
    except (KeyError, TypeError):
        _stop("APPROVAL_REQUEST_ID_SURFACE_INVALID")
    return {
        "schema": RECEIPT_SCHEMA_ID,
        "task_id": task_id,
        "origin_id": origin_id,
        "approval_request_capture_sha256": decision["approval_request_capture_sha256"],
        "mandate_assertion_sha256": decision["mandate_assertion_sha256"],
        "mandate_evaluation_result_sha256": decision["mandate_evaluation_result_sha256"],
        "controlled_tool_decision_sha256": decision["decision_sha256"],
        "execution_request_sha256": _execution_request_sha(decision),
        "selected_action_node_id": decision["selected_action_node_id"],
        "action_trace_sha256": decision["action_trace_sha256"],
        "approval_scope_revision": decision["approval_scope_revision"],
        "tool_profile_scope_marker": decision["tool_profile_scope_marker"],
        "tool_execution_binding_revision": decision["tool_execution_binding_revision"],
        "tool_profile_id": profile["profile_id"],
        "tool_profile_revision": profile["profile_revision"],
        "backend": profile["backend"],
        "executable_path": profile["executable_path"],
        "executable_sha256": profile["executable_sha256"],
        "argv": copy.deepcopy(profile["argv"]),
        "cwd": profile["cwd"],
        "environment_names": sorted(profile["environment"]),
        "network_authority_granted": profile["network_authority_granted"],
        "privileged_authority_granted": profile["privileged_authority_granted"],
        "persistent_write_authority_granted": profile["persistent_write_authority_granted"],
        "network_kernel_confinement": profile["network_kernel_confinement"],
        "filesystem_write_kernel_confinement": profile["filesystem_write_kernel_confinement"],
        "general_binary_behavior_sandbox": profile["general_binary_behavior_sandbox"],
        "dynamic_runtime_dependency_content_authority": profile["dynamic_runtime_dependency_content_authority"],
        "declared_target_path": profile["declared_target_path"],
        "target_fd_number": 3,
        "target_device": int(target_st.st_dev),
        "target_inode": int(target_st.st_ino),
        "target_fd_sha256_before": target_before,
        "target_fd_sha256_after": target_before,
        "target_fd_matches_expected_before": target_before == profile["declared_target_sha256"],
        "target_fd_matches_expected_after": False,
        "executable_fd_number": 4,
        "executable_reference_path": profile["executable_reference_path"],
        "executable_device": int(exe_st.st_dev),
        "executable_inode": int(exe_st.st_ino),
        "executable_uid": int(exe_st.st_uid),
        "executable_gid": int(exe_st.st_gid),
        "executable_mode": format(stat.S_IMODE(exe_st.st_mode), "04o"),
        "executable_fd_sha256_before": exe_before,
        "executable_fd_sha256_after": exe_before,
        "executable_fd_matches_expected_before": exe_before == profile["executable_sha256"],
        "executable_fd_matches_expected_after": False,
        "timeout_seconds": profile["timeout_seconds"],
        "max_stdout_bytes": profile["max_stdout_bytes"],
        "max_stderr_bytes": profile["max_stderr_bytes"],
        "process_started": False,
        "exit_code": None,
        "signal": None,
        "timed_out": False,
        "output_limit_exceeded": False,
        "termination_trigger": "NONE",
        "stdout_bytes": 0,
        "stdout_sha256": _sha256(b""),
        "stderr_bytes": 0,
        "stderr_sha256": _sha256(b""),
        "profile_output_contract_pass": False,
        "duration_ms": 0,
        "status": "SPAWN_FAILED",
    }


def _finalize_receipt(
    base: dict[str, Any],
    *,
    target_after: str,
    exe_after: str,
    stdout: bytes,
    stderr: bytes,
    returncode: int | None,
    trigger: str,
    process_started: bool,
    duration_ms: int,
    profile: dict[str, Any],
    spawn_failed: bool,
) -> dict[str, Any]:
    r = copy.deepcopy(base)
    r["target_fd_sha256_after"] = target_after
    r["target_fd_matches_expected_after"] = target_after == profile["declared_target_sha256"]
    r["executable_fd_sha256_after"] = exe_after
    r["executable_fd_matches_expected_after"] = exe_after == profile["executable_sha256"]
    r["process_started"] = process_started
    r["timed_out"] = trigger == "TIMEOUT"
    r["output_limit_exceeded"] = trigger == "OUTPUT_LIMIT"
    r["termination_trigger"] = trigger
    r["stdout_bytes"] = len(stdout)
    r["stdout_sha256"] = _sha256(stdout)
    r["stderr_bytes"] = len(stderr)
    r["stderr_sha256"] = _sha256(stderr)
    r["duration_ms"] = max(0, int(duration_ms))
    if returncode is not None and returncode < 0:
        r["exit_code"] = None
        r["signal"] = -returncode
    else:
        r["exit_code"] = returncode
        r["signal"] = None
    expected_stdout = profile["expected_stdout_utf8"].encode("utf-8")
    expected_stderr = profile["expected_stderr_utf8"].encode("utf-8")
    output_contract = (
        process_started
        and trigger == "NONE"
        and returncode == profile["expected_exit_code"]
        and stdout == expected_stdout
        and stderr == expected_stderr
    )
    r["profile_output_contract_pass"] = output_contract
    if not r["executable_fd_matches_expected_after"]:
        status = "EXECUTABLE_MUTATION_DETECTED"
    elif not r["target_fd_matches_expected_after"]:
        status = "TARGET_MUTATION_DETECTED"
    elif spawn_failed:
        status = "SPAWN_FAILED"
    elif trigger == "TIMEOUT":
        status = "TIMED_OUT"
    elif trigger == "OUTPUT_LIMIT":
        status = "OUTPUT_LIMIT_STOP"
    elif not output_contract:
        status = "OUTPUT_CONTRACT_MISMATCH"
    else:
        status = "COMPLETED"
    r["status"] = status
    r["receipt_sha256"] = _receipt_hash(r)
    return validate_execution_receipt(r)


def _read_limited_process(
    proc: subprocess.Popen[bytes],
    profile: dict[str, Any],
) -> tuple[bytes, bytes, str]:
    if proc.stdout is None or proc.stderr is None:
        _stop("PROCESS_PIPE_SETUP_INVALID")
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "stdout")
    sel.register(proc.stderr, selectors.EVENT_READ, "stderr")
    out = bytearray()
    err = bytearray()
    deadline = time.monotonic() + profile["timeout_seconds"]
    trigger = "NONE"
    while sel.get_map():
        timeout_left = max(0.0, deadline - time.monotonic())
        events = sel.select(min(timeout_left, 0.05))
        for key, _mask in events:
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                sel.unregister(key.fileobj)
                continue
            if key.data == "stdout":
                out.extend(chunk)
            else:
                err.extend(chunk)
        output_hit = (
            len(out) > profile["max_stdout_bytes"]
            or len(err) > profile["max_stderr_bytes"]
        )
        timeout_hit = time.monotonic() >= deadline
        if trigger == "NONE":
            if output_hit:
                trigger = "OUTPUT_LIMIT"
            elif timeout_hit:
                trigger = "TIMEOUT"
        if trigger != "NONE":
            break
        if proc.poll() is not None and not events:
            # Drain once more via selector until EOF.
            continue
    if trigger != "NONE" and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
    if proc.poll() is None:
        proc.wait(timeout=1)
    # Drain any bounded residual bytes.
    for stream, target, limit in (
        (proc.stdout, out, profile["max_stdout_bytes"] + 65536),
        (proc.stderr, err, profile["max_stderr_bytes"] + 65536),
    ):
        try:
            part = stream.read(limit)
        except Exception:
            part = b""
        if part:
            target.extend(part)
    return bytes(out), bytes(err), trigger


def _execute_profile_impl(
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
    global _K7_L_EXECUTOR_CHILD_PROCESS_START_COUNT_TOTAL
    protocol = _load_protocol()
    registry = _load_registry(protocol)
    if tool_profile_id != PROFILE_ID:
        _stop("PROFILE_ID_UNSUPPORTED")
    profile = registry["profiles"][0]
    try:
        decision = protocol["evaluate_controlled_tool"](
            approval_request,
            tool_profile_id,
            mandate_assertion,
            source_envelope,
            goal_chain,
            hypothesis_state,
            state_base,
            ledger_records,
            memory_records,
        )
        decision = protocol["validate_execution_decision"](decision)
    except BaseException as exc:
        if isinstance(exc, LocalToolExecutorError):
            raise
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            "CONTROL_PROTOCOL_EVALUATION_FAILED",
            None,
        ) from exc
    if decision["result"] != "EXECUTION_ELIGIBLE":
        _stop("EXECUTION_NOT_ELIGIBLE")
    target_fd = exe_fd = None
    start = time.monotonic_ns()
    proc: subprocess.Popen[bytes] | None = None
    stdout = b""
    stderr = b""
    trigger = "NONE"
    spawn_failed = False
    try:
        target_fd, target_st = _open_pinned(
            profile["declared_target_path"], 3, "TARGET"
        )
        target_before = _hash_fd(target_fd)
        if target_before != profile["declared_target_sha256"]:
            _stop("TARGET_PREHASH_MISMATCH")
        exe_fd, exe_st = _open_pinned(
            profile["executable_path"], 4, "EXECUTABLE"
        )
        mode = format(stat.S_IMODE(exe_st.st_mode), "04o")
        if exe_st.st_uid != profile["executable_required_uid"]:
            _stop("EXECUTABLE_UID_MISMATCH")
        if exe_st.st_gid != profile["executable_required_gid"]:
            _stop("EXECUTABLE_GID_MISMATCH")
        if mode != profile["executable_required_mode"]:
            _stop("EXECUTABLE_MODE_MISMATCH")
        exe_before = _hash_fd(exe_fd)
        if exe_before != profile["executable_sha256"]:
            _stop("EXECUTABLE_PREHASH_MISMATCH")
        base = _base_receipt(
            approval_request, decision, profile, target_st, exe_st,
            target_before, exe_before,
        )
        try:
            proc = subprocess.Popen(
                profile["argv"],
                executable=profile["executable_reference_path"],
                cwd=profile["cwd"],
                env=copy.deepcopy(profile["environment"]),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                pass_fds=(3, 4),
            )
            _K7_L_EXECUTOR_CHILD_PROCESS_START_COUNT_TOTAL += 1
        except OSError:
            spawn_failed = True
        if not spawn_failed and proc is not None:
            stdout, stderr, trigger = _read_limited_process(proc, profile)
        target_after = _hash_fd(target_fd)
        exe_after = _hash_fd(exe_fd)
        rc = None if proc is None else proc.returncode
        duration_ms = (time.monotonic_ns() - start) // 1_000_000
        receipt = _finalize_receipt(
            base,
            target_after=target_after,
            exe_after=exe_after,
            stdout=stdout,
            stderr=stderr,
            returncode=rc,
            trigger=trigger,
            process_started=(proc is not None),
            duration_ms=duration_ms,
            profile=profile,
            spawn_failed=spawn_failed,
        )
        if receipt["status"] == "EXECUTABLE_MUTATION_DETECTED":
            _stop("EXECUTABLE_MUTATION_DETECTED", receipt)
        if receipt["status"] == "TARGET_MUTATION_DETECTED":
            _stop("TARGET_MUTATION_DETECTED", receipt)
        return receipt
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:
                pass
        if exe_fd is not None:
            os.close(exe_fd)
        if target_fd is not None:
            os.close(target_fd)

_UNEXPECTED_EXECUTOR_EXCEPTION_CAUSES = (
    (ValueError, "UNEXPECTED_VALUE_ERROR"),
    (TypeError, "UNEXPECTED_TYPE_ERROR"),
    (TimeoutError, "UNEXPECTED_TIMEOUT_ERROR"),
    (OSError, "UNEXPECTED_OS_ERROR"),
    (RuntimeError, "UNEXPECTED_RUNTIME_ERROR"),
)


def _unexpected_executor_cause(exc: Exception) -> str:
    for exc_type, cause in _UNEXPECTED_EXECUTOR_EXCEPTION_CAUSES:
        if isinstance(exc, exc_type):
            return cause
    return "UNEXPECTED_EXECUTOR_ERROR"


def execute_profile(
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
    try:
        receipt = _execute_profile_impl(
            approval_request,
            tool_profile_id,
            mandate_assertion,
            source_envelope,
            goal_chain,
            hypothesis_state,
            state_base,
            ledger_records,
            memory_records,
        )
        return validate_execution_receipt(receipt)
    except LocalToolExecutorError:
        raise
    except Exception as exc:
        raise LocalToolExecutorError(
            "STOP_LOCAL_EXECUTOR",
            _unexpected_executor_cause(exc),
            None,
        ) from exc
