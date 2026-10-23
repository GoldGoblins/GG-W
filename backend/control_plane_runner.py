#!/usr/bin/env python3
"""Exact, approval-bound apply runner for verified GG selfdev candidates.

The only persistent target is projects/gg-ai-desktop/main.py.  The runner
derives every path from a validated task id, revalidates the clean base HEAD,
candidate hashes, diff, Python compilation and fixed regression tests, and
then performs one same-directory atomic replacement with rollback on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.platform_files import (
    NOFOLLOW,
    mode_matches,
    owned_by_current_user,
    secure_open,
    set_private_mode,
    sync_directory,
)
from backend.platform_support import (
    executable_path,
    host_environment,
    private_runtime_root,
    workspace_root,
)


import difflib
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from backend import control_plane_contract as contract
except ModuleNotFoundError:  # Direct fixed runner invocation.
    import control_plane_contract as contract  # type: ignore[no-redef]


PROJECT = Path(__file__).resolve().parents[1]
REPO = workspace_root()
TARGET = REPO / contract.TARGET_RELATIVE_PATH
MAX_TARGET_BYTES = 327680

REGRESSION_TESTS = (
    "tests/test_autonomy_contract.py",
    "tests/test_autonomy_controller.py",
    "tests/test_write_contract.py",
    "tests/test_ux_baseline_contract.py",
)


class ControlApplyError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _runtime_root() -> Path:
    root = private_runtime_root()
    resolved = root.resolve(strict=True)
    if resolved != root or not resolved.is_dir():
        raise ControlApplyError("RUNTIME_ROOT_INVALID")
    return resolved


def _safe_cli_path(raw: str, prefix: str, require_file: bool) -> Path:
    runtime = _runtime_root()
    path = Path(raw)
    if path.parent != runtime or not path.name.startswith(prefix):
        raise ControlApplyError("CLI_PATH_POLICY:" + prefix)
    if require_file:
        if path.is_symlink() or not path.is_file():
            raise ControlApplyError("CLI_FILE_INVALID:" + prefix)
        info = path.stat()
        if not owned_by_current_user(path) or not mode_matches(path, 0o600):
            raise ControlApplyError("CLI_FILE_OWNER_MODE_INVALID:" + prefix)
    else:
        if path.is_symlink() or not path.is_dir():
            raise ControlApplyError("CLI_DIRECTORY_INVALID:" + prefix)
        info = path.stat()
        if not owned_by_current_user(path):
            raise ControlApplyError("CLI_DIRECTORY_OWNER_INVALID")
        if not mode_matches(path, 0o700):
            raise ControlApplyError("CLI_DIRECTORY_MODE_INVALID")
    return path


def _read_json(path: Path, maximum: int = 131072) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ControlApplyError("JSON_FILE_INVALID:" + path.name)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size < 2 or info.st_size > maximum:
        raise ControlApplyError("JSON_SIZE_INVALID:" + path.name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlApplyError("JSON_DECODE_FAILED:" + path.name) from exc


def _write_exclusive(path: Path, data: bytes) -> None:
    fd = secure_open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [executable_path("git"), "-C", str(REPO), *args],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=host_environment({
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }),
    )


def _clean_head(expected: str) -> None:
    status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status.returncode != 0:
        raise ControlApplyError("GIT_STATUS_FAILED")
    if status.stdout:
        raise ControlApplyError("HOST_REPO_NOT_CLEAN")
    head = _git("rev-parse", "HEAD")
    if head.returncode != 0:
        raise ControlApplyError("GIT_HEAD_FAILED")
    actual = head.stdout.decode("ascii", errors="strict").strip()
    if actual != expected:
        raise ControlApplyError("BASE_HEAD_DRIFT")


def _regular_bytes(path: Path, maximum: int) -> tuple[bytes, os.stat_result]:
    if path.is_symlink() or not path.is_file():
        raise ControlApplyError("FILE_INVALID:" + path.name)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > maximum:
        raise ControlApplyError("FILE_SIZE_INVALID:" + path.name)
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ControlApplyError("FILE_READ_SIZE_DRIFT:" + path.name)
    return data, info


def _diff(before: bytes, after: bytes) -> str:
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ControlApplyError("CANDIDATE_NOT_UTF8") from exc
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile="a/main.py",
            tofile="b/main.py",
            n=3,
        )
    )


def _validated_result(task_root: Path, request: dict[str, str]) -> dict[str, object]:
    result = _read_json(task_root / "verified-result.json")
    required = {
        "schema",
        "task_id",
        "base_head",
        "target_relative_path",
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
        "foundation_gate_report_sha256",
        "candidate_write_count",
        "model_call_count",
        "host_repo_changed",
        "persistent_selfdev_write",
        "status",
    }
    if type(result) is not dict or set(result) != required:
        raise ControlApplyError("VERIFIED_RESULT_FIELDS_INVALID")
    expected = {
        "schema": "gg.workbench.selfdev-result.v1",
        "task_id": request["task_id"],
        "base_head": request["base_head"],
        "target_relative_path": request["target_relative_path"],
        "before_sha256": request["before_sha256"],
        "candidate_sha256": request["candidate_sha256"],
        "diff_sha256": request["diff_sha256"],
        "host_repo_changed": False,
        "persistent_selfdev_write": "NONE",
        "status": "WAITING_PERSISTENT_APPLY",
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise ControlApplyError("VERIFIED_RESULT_BINDING:" + key)
    if type(result["candidate_write_count"]) is not int or result["candidate_write_count"] < 1:
        raise ControlApplyError("VERIFIED_RESULT_WRITE_COUNT")
    if type(result["model_call_count"]) is not int or result["model_call_count"] < 0:
        raise ControlApplyError("VERIFIED_RESULT_MODEL_COUNT")
    if contract.SHA256_RE.fullmatch(str(result["foundation_gate_report_sha256"])) is None:
        raise ControlApplyError("VERIFIED_RESULT_GATE_SHA")
    return result


def _run_regression(candidate_project: Path) -> None:
    for relative in REGRESSION_TESTS:
        path = candidate_project / relative
        if path.is_symlink() or not path.is_file():
            raise ControlApplyError("REGRESSION_TEST_MISSING:" + relative)
        result = subprocess.run(
            [executable_path("python3"), "-B", str(path)],
            cwd=str(candidate_project),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            env=host_environment({
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
            }),
        )
        if result.returncode != 0:
            detail = (result.stdout + b"\n" + result.stderr).decode(
                "utf-8", errors="replace"
            )[-4000:]
            raise ControlApplyError("REGRESSION_FAILED:" + relative + ":" + detail)


def _replace_target(candidate: bytes, original: bytes, original_mode: int) -> None:
    suffix = ".gg-control-apply." + str(os.getpid())
    temporary = TARGET.with_name(".main.py" + suffix + ".tmp")
    rollback = TARGET.with_name(".main.py" + suffix + ".rollback")

    def materialize(path: Path, data: bytes) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        fd = secure_open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            stat.S_IMODE(original_mode),
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    applied = False
    try:
        materialize(temporary, candidate)
        materialize(rollback, original)
        os.replace(temporary, TARGET)
        applied = True
        sync_directory(TARGET.parent)
        if TARGET.read_bytes() != candidate:
            raise ControlApplyError("HOST_POSTIMAGE_MISMATCH")
    except Exception:
        if applied and rollback.is_file() and not rollback.is_symlink():
            os.replace(rollback, TARGET)
            sync_directory(TARGET.parent)
        raise
    finally:
        for path in (temporary, rollback):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def execute(evidence_raw: str, request_raw: str) -> dict[str, object]:
    evidence = _safe_cli_path(evidence_raw, "gg-control-apply.", False)
    request_path = _safe_cli_path(request_raw, "gg-control-apply-request.", True)
    request = contract.validate_apply_request(_read_json(request_path))

    task_suffix = request["task_id"].removeprefix("task-")
    task_root = _runtime_root() / ("gg-selfdev-task." + task_suffix)
    if task_root.is_symlink() or not task_root.is_dir():
        raise ControlApplyError("SELFDEV_TASK_ROOT_INVALID")
    info = task_root.stat()
    if not owned_by_current_user(task_root):
        raise ControlApplyError("SELFDEV_TASK_OWNER_INVALID")
    if not mode_matches(task_root, 0o700):
        raise ControlApplyError("SELFDEV_TASK_MODE_INVALID")

    if (task_root / "apply-receipt.json").exists():
        raise ControlApplyError("TASK_ALREADY_APPLIED")
    if (task_root / "rejected.json").exists():
        raise ControlApplyError("TASK_ALREADY_REJECTED")

    _validated_result(task_root, request)
    _clean_head(request["base_head"])

    host_before, host_info = _regular_bytes(TARGET, MAX_TARGET_BYTES)
    if sha256_bytes(host_before) != request["before_sha256"]:
        raise ControlApplyError("HOST_BEFORE_SHA_DRIFT")

    candidate_project = task_root / "tree" / "projects" / "gg-ai-desktop"
    candidate_path = candidate_project / "main.py"
    candidate, _candidate_info = _regular_bytes(candidate_path, MAX_TARGET_BYTES)
    if sha256_bytes(candidate) != request["candidate_sha256"]:
        raise ControlApplyError("CANDIDATE_SHA_DRIFT")
    if candidate == host_before:
        raise ControlApplyError("CANDIDATE_NO_OP")

    diff_text = _diff(host_before, candidate)
    diff_path = task_root / "verified.diff"
    diff_bytes, _diff_info = _regular_bytes(diff_path, MAX_TARGET_BYTES * 4)
    if diff_bytes != diff_text.encode("utf-8"):
        raise ControlApplyError("VERIFIED_DIFF_CONTENT_DRIFT")
    if sha256_bytes(diff_bytes) != request["diff_sha256"]:
        raise ControlApplyError("VERIFIED_DIFF_SHA_DRIFT")

    try:
        compile(
            candidate.decode("utf-8"),
            str(candidate_path),
            "exec",
            dont_inherit=True,
        )
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise ControlApplyError("CANDIDATE_COMPILE_FAILED") from exc

    _run_regression(candidate_project)
    _clean_head(request["base_head"])
    if TARGET.read_bytes() != host_before:
        raise ControlApplyError("HOST_CHANGED_DURING_REVALIDATION")

    attempt = {
        "schema": "gg.workbench.control-apply-attempt.v1",
        "task_id": request["task_id"],
        "base_head": request["base_head"],
        "before_sha256": request["before_sha256"],
        "candidate_sha256": request["candidate_sha256"],
        "diff_sha256": request["diff_sha256"],
    }
    _write_exclusive(task_root / "apply-attempt.json", contract.canonical_json(attempt))

    evidence_response = evidence / "response.json"
    applied = False
    try:
        _replace_target(candidate, host_before, host_info.st_mode)
        applied = True
        after = TARGET.read_bytes()
        after_sha = sha256_bytes(after)
        if after_sha != request["candidate_sha256"] or after != candidate:
            raise ControlApplyError("HOST_POSTHASH_FAILED")

        status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if status.returncode != 0:
            raise ControlApplyError("POST_APPLY_GIT_STATUS_FAILED")
        expected_path = contract.TARGET_RELATIVE_PATH.encode("utf-8")
        records = [item for item in status.stdout.split(b"\x00") if item]
        if len(records) != 1 or len(records[0]) < 4 or records[0][3:] != expected_path:
            raise ControlApplyError("POST_APPLY_SCOPE_INVALID")

        response: dict[str, object] = {
            "schema": contract.APPLY_RESPONSE_SCHEMA,
            "task_id": request["task_id"],
            "status": "APPLIED_VERIFIED",
            "base_head": request["base_head"],
            "before_sha256": request["before_sha256"],
            "candidate_sha256": request["candidate_sha256"],
            "host_after_sha256": after_sha,
            "host_repo_changed": True,
            "output": (
                "Verified main.py candidate applied atomically. "
                "Restart GG AI Desktop to load the new Python source. "
                "Git commit authority remains NONE."
            ),
        }
        contract.validate_apply_response(response, request)
        response_bytes = contract.canonical_json(response)
        _write_exclusive(evidence_response, response_bytes)
        _write_exclusive(task_root / "apply-receipt.json", response_bytes)
        return response
    except Exception:
        if applied:
            _replace_target(host_before, candidate, host_info.st_mode)
            if TARGET.read_bytes() != host_before:
                raise ControlApplyError("ROLLBACK_POSTHASH_FAILED")
        try:
            evidence_response.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] != "--apply-selfdev":
        print("CONTROL_APPLY_USAGE=INVALID", file=sys.stderr)
        return 2
    evidence_raw = sys.argv[2]
    request_raw = sys.argv[3]
    try:
        response = execute(evidence_raw, request_raw)
    except Exception as exc:
        try:
            evidence = _safe_cli_path(evidence_raw, "gg-control-apply.", False)
            failure = {
                "schema": "gg.workbench.control-apply-failure.v1",
                "reason": type(exc).__name__ + ":" + str(exc),
            }
            if not (evidence / "failure.json").exists():
                _write_exclusive(evidence / "failure.json", contract.canonical_json(failure))
        except Exception:
            pass
        print("CONTROL_APPLY=STOP", file=sys.stderr)
        print("CONTROL_APPLY_REASON=" + type(exc).__name__ + ":" + str(exc), file=sys.stderr)
        return 1
    print("CONTROL_APPLY=PASS")
    print("CONTROL_APPLY_TASK=" + str(response["task_id"]))
    print("CONTROL_APPLY_HOST_SHA256=" + str(response["host_after_sha256"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
