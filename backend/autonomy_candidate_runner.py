#!/usr/bin/env python3
"""Task-bound candidate workspace for GG Autonomy Bootstrap v1.

All writes are confined to /run/user/<uid>/gg-autonomy-task.<task-id-suffix>/.
The host repository target is read-only here. Persistent host apply remains the
separate existing Limited Write boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.platform_files import (
    CLOEXEC,
    NOFOLLOW,
    mode_matches,
    owned_by_current_user,
    secure_open,
    set_private_mode,
    sync_directory,
)
from backend.platform_support import (
    private_runtime_root,
    workspace_root,
)


import difflib
import hashlib
import importlib.util
import os
import stat
import sys
from pathlib import Path
from typing import Any, Callable

try:
    from . import autonomy_contract as contract
except ImportError:
    import autonomy_contract as contract  # type: ignore

PROJECT = Path(__file__).resolve().parents[1]
REPO = workspace_root()
RUNTIME = private_runtime_root()

WRITE_RUNNER_PATH = PROJECT / "backend/write_runner.py"
WRITE_RUNNER_SHA256 = (
    "54be63540f3868f214c717d6e65da6a97ca5abbd3b545ec0f06b30b8e301a8be"
)

TARGET = PROJECT / contract.TARGET_RELATIVE_PATH
CANDIDATE_DIR_NAME = "candidate"
CANDIDATE_FILE_NAME = "ContextComposer.qml"
BEFORE_FILE_NAME = "before.bin"


class CandidateError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _task_root(path: Path, task_id: str | None = None) -> Path:
    runtime = RUNTIME.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved.parent != runtime:
        raise CandidateError("TASK_ROOT_PARENT_INVALID")
    if not resolved.name.startswith("gg-autonomy-task."):
        raise CandidateError("TASK_ROOT_NAME_INVALID")
    if task_id is not None:
        expected = "gg-autonomy-task." + task_id.removeprefix("task-")
        if resolved.name != expected:
            raise CandidateError("TASK_ROOT_TASK_BINDING_MISMATCH")
    if path.is_symlink() or not path.is_dir():
        raise CandidateError("TASK_ROOT_INVALID")
    info = path.stat()
    if not owned_by_current_user(path) or not mode_matches(path, 0o700):
        raise CandidateError("TASK_ROOT_OWNER_MODE_INVALID")
    return resolved


def _read_host_target() -> bytes:
    project = PROJECT.resolve(strict=True)
    relative = Path(contract.TARGET_RELATIVE_PATH)
    if relative.is_absolute() or ".." in relative.parts:
        raise CandidateError("TARGET_POLICY_INVALID")

    target = PROJECT / relative
    parent = target.parent.resolve(strict=True)
    if not parent.is_relative_to(project):
        raise CandidateError("TARGET_PARENT_ESCAPED")

    fd = secure_open(target, os.O_RDONLY | CLOEXEC | NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CandidateError("TARGET_NOT_REGULAR")
        if not owned_by_current_user(fd):
            raise CandidateError("TARGET_OWNER_INVALID")
        if not mode_matches(fd, 0o644):
            raise CandidateError("TARGET_MODE_INVALID")
        if not 1 <= info.st_size <= contract.TARGET_MAX_BYTES:
            raise CandidateError("TARGET_SIZE_INVALID")
        data = os.read(fd, contract.TARGET_MAX_BYTES + 1)
    finally:
        os.close(fd)

    if len(data) > contract.TARGET_MAX_BYTES:
        raise CandidateError("TARGET_READ_LIMIT")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CandidateError("TARGET_NOT_UTF8") from exc
    return data


def _write_exclusive(path: Path, data: bytes, mode: int) -> None:
    if path.exists() or path.is_symlink():
        raise CandidateError("CANDIDATE_PATH_EXISTS:" + path.name)
    fd = secure_open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        mode,
    )
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_replace(path: Path, data: bytes, mode: int) -> None:
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise CandidateError("CANDIDATE_PARENT_INVALID")
    temporary = parent / ("." + path.name + ".autonomy-" + str(os.getpid()))
    if temporary.exists() or temporary.is_symlink():
        raise CandidateError("CANDIDATE_TEMP_EXISTS")
    fd = secure_open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        sync_directory(parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def initialize(
    task_root: Path,
    task_id: str,
    *,
    expected_before_sha256: str | None = None,
) -> dict[str, Any]:
    root = _task_root(task_root, task_id)
    before = _read_host_target()
    before_sha = sha256_bytes(before)
    if expected_before_sha256 is not None and before_sha != expected_before_sha256:
        raise CandidateError("TARGET_PREIMAGE_DRIFT")

    before_path = root / BEFORE_FILE_NAME
    candidate_dir = root / CANDIDATE_DIR_NAME
    candidate_path = candidate_dir / CANDIDATE_FILE_NAME

    if before_path.exists() or before_path.is_symlink():
        raise CandidateError("BEFORE_PATH_EXISTS")
    if candidate_dir.exists() or candidate_dir.is_symlink():
        raise CandidateError("CANDIDATE_DIR_EXISTS")

    candidate_dir.mkdir(mode=0o700)
    _write_exclusive(before_path, before, 0o400)
    _write_exclusive(candidate_path, before, 0o600)

    return {
        "before_path": str(before_path),
        "candidate_path": str(candidate_path),
        "before_sha256": before_sha,
        "bytes": len(before),
    }


def read_before(task_root: Path, task_id: str) -> bytes:
    root = _task_root(task_root, task_id)
    path = root / BEFORE_FILE_NAME
    if path.is_symlink() or not path.is_file():
        raise CandidateError("BEFORE_MISSING")
    data = path.read_bytes()
    if not 1 <= len(data) <= contract.TARGET_MAX_BYTES:
        raise CandidateError("BEFORE_SIZE_INVALID")
    return data


def read_candidate(task_root: Path, task_id: str) -> bytes:
    root = _task_root(task_root, task_id)
    path = root / CANDIDATE_DIR_NAME / CANDIDATE_FILE_NAME
    if path.is_symlink() or not path.is_file():
        raise CandidateError("CANDIDATE_MISSING")
    data = path.read_bytes()
    if not 1 <= len(data) <= contract.TARGET_MAX_BYTES:
        raise CandidateError("CANDIDATE_SIZE_INVALID")
    return data


def intended_patch(
    before: bytes,
    old_text: str,
    new_text: str,
) -> bytes:
    try:
        text = before.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CandidateError("BEFORE_NOT_UTF8") from exc
    if text.count(old_text) != 1:
        raise CandidateError("PATCH_OLD_TEXT_NOT_EXACTLY_ONCE")
    if old_text == new_text:
        raise CandidateError("PATCH_NOOP")
    candidate = text.replace(old_text, new_text, 1).encode("utf-8")
    if not 1 <= len(candidate) <= contract.TARGET_MAX_BYTES:
        raise CandidateError("PATCH_RESULT_SIZE_INVALID")
    return candidate


def write_attempt(
    task_root: Path,
    task_id: str,
    *,
    old_text: str,
    new_text: str,
    inject_invalid_qml: bool = False,
) -> dict[str, Any]:
    root = _task_root(task_root, task_id)
    before = read_before(root, task_id)
    intended = intended_patch(before, old_text, new_text)
    candidate = intended
    if inject_invalid_qml:
        candidate += b"\nGG_AUTONOMY_INTENTIONAL_INVALID_QML: ???\n"
        if len(candidate) > contract.TARGET_MAX_BYTES:
            raise CandidateError("INJECTED_CANDIDATE_TOO_LARGE")

    path = root / CANDIDATE_DIR_NAME / CANDIDATE_FILE_NAME
    _atomic_replace(path, candidate, 0o600)
    return {
        "candidate_sha256": sha256_bytes(candidate),
        "intended_sha256": sha256_bytes(intended),
        "injected_failure": inject_invalid_qml,
        "bytes": len(candidate),
    }


def repair_to_intended(
    task_root: Path,
    task_id: str,
    *,
    old_text: str,
    new_text: str,
) -> dict[str, Any]:
    root = _task_root(task_root, task_id)
    before = read_before(root, task_id)
    intended = intended_patch(before, old_text, new_text)
    path = root / CANDIDATE_DIR_NAME / CANDIDATE_FILE_NAME
    _atomic_replace(path, intended, 0o600)
    return {
        "candidate_sha256": sha256_bytes(intended),
        "bytes": len(intended),
        "repair": "RESTORE_INTENDED_EXACT_PATCH",
    }


def diff_text(
    before: bytes,
    candidate: bytes,
) -> tuple[str, str]:
    before_text = before.decode("utf-8")
    candidate_text = candidate.decode("utf-8")
    diff = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile="a/" + contract.TARGET_RELATIVE_PATH,
            tofile="b/" + contract.TARGET_RELATIVE_PATH,
            n=3,
        )
    )
    if not diff:
        raise CandidateError("CANDIDATE_DIFF_EMPTY")
    if len(diff.encode("utf-8")) > 32768:
        raise CandidateError("CANDIDATE_DIFF_TOO_LARGE")
    return diff, sha256_bytes(diff.encode("utf-8"))


def _load_write_runner():
    if WRITE_RUNNER_PATH.is_symlink() or not WRITE_RUNNER_PATH.is_file():
        raise CandidateError("WRITE_RUNNER_INVALID")
    if hashlib.sha256(WRITE_RUNNER_PATH.read_bytes()).hexdigest() != WRITE_RUNNER_SHA256:
        raise CandidateError("WRITE_RUNNER_SHA_DRIFT")

    backend = str(WRITE_RUNNER_PATH.parent)
    inserted = backend not in sys.path
    if inserted:
        sys.path.insert(0, backend)
    try:
        spec = importlib.util.spec_from_file_location(
            "_gg_autonomy_bound_write_runner",
            WRITE_RUNNER_PATH,
        )
        if spec is None or spec.loader is None:
            raise CandidateError("WRITE_RUNNER_IMPORT_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(backend)


def qml_gate(
    task_root: Path,
    task_id: str,
    *,
    label: str,
    gate_override: Callable[[bytes, Path, str], str] | None = None,
) -> str:
    root = _task_root(task_root, task_id)
    candidate = read_candidate(root, task_id)
    if gate_override is not None:
        return gate_override(candidate, root, label)
    runner = _load_write_runner()
    return runner._qml_gate(candidate, root, label)


def selftest() -> int:
    before = b"alpha\nimplicitHeight: 92\nomega\n"
    candidate = intended_patch(before, "implicitHeight: 92", "implicitHeight: 93")
    if candidate != b"alpha\nimplicitHeight: 93\nomega\n":
        raise CandidateError("SELFTEST_PATCH_MISMATCH")
    diff, digest = diff_text(before, candidate)
    if "implicitHeight: 93" not in diff or len(digest) != 64:
        raise CandidateError("SELFTEST_DIFF_MISMATCH")
    print("AUTONOMY_CANDIDATE_RUNNER_SELFTEST=PASS")
    print("CANDIDATE_WORKSPACE=RUNTIME_TASK_BOUND")
    print("HOST_WRITE_AUTHORITY=NONE_BEFORE_SEPARATE_APPROVAL")
    print("ARBITRARY_PATH_AUTHORITY=NONE")
    print("NETWORK_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
