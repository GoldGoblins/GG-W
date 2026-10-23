#!/usr/bin/env python3
"""Execution boundary for GG Workbench Limited PATCH/WRITE Authority v1.

No caller controls a filesystem path, executable, argv vector, environment,
network target, shell command, or Git mutation. The only persistent target is
the fixed real @current ContextComposer.qml file. Every apply is proposal/hash
bound, explicitly approved, QML-gated, atomic, revalidated and reversible.
"""

from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.container_platform import container_user
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
import time
from pathlib import Path
from typing import Any

from backend import write_contract as contract

PROJECT = Path(__file__).resolve().parents[1]
REPO = workspace_root()
RUNTIME = private_runtime_root()

QML_IMAGE_ID = "851b076f4c9d16ecff0b802276858ff4756bd226387f09db7b5a9bb0222d9cef"
QML_IMAGE_REF = "localhost/gg-code-gate-qml:1.0.0"

TARGET_REPO_RELATIVE = (
    "projects/gg-ai-desktop/" + contract.TARGET_RELATIVE_PATH
)
TARGET_REQUIRED_MODE = 0o644
MAX_RUN_OUTPUT = 65536

_GIT_ENV = host_environment({
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_REPLACE_OBJECTS": "1",
})


class WriteBoundaryError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail(message: str) -> None:
    raise WriteBoundaryError(message)


def _safe_request_path(raw: str) -> Path:
    path = Path(raw)
    root = RUNTIME.resolve(strict=True)
    parent = path.parent.resolve(strict=True)

    if parent != root:
        _fail("REQUEST_PATH_OUTSIDE_RUNTIME")
    if path.is_symlink() or not path.is_file():
        _fail("REQUEST_PATH_INVALID")
    if not path.name.startswith("gg-workbench-write-request."):
        _fail("REQUEST_NAME_INVALID")
    return path


def _safe_evidence_path(raw: str, proposal_id: str, create: bool) -> Path:
    path = Path(raw)
    root = RUNTIME.resolve(strict=True)
    parent = path.parent.resolve(strict=True)
    expected = "gg-write-proposal." + proposal_id.removeprefix("proposal-")

    if parent != root or path.name != expected:
        _fail("EVIDENCE_PATH_INVALID")

    if create:
        if path.exists() or path.is_symlink():
            _fail("EVIDENCE_ALREADY_EXISTS")
        path.mkdir(mode=0o700)
    else:
        if path.is_symlink() or not path.is_dir():
            _fail("EVIDENCE_NOT_FOUND")

    return path


def _read_json_regular(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail("JSON_INPUT_INVALID:" + path.name)

    flags = os.O_RDONLY | CLOEXEC | NOFOLLOW
    fd = secure_open(path, flags)

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            _fail("JSON_INPUT_NOT_REGULAR:" + path.name)
        if st.st_size < 2 or st.st_size > 65536:
            _fail("JSON_INPUT_SIZE_INVALID:" + path.name)
        data = os.read(fd, st.st_size + 1)
    finally:
        os.close(fd)

    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WriteBoundaryError("JSON_INPUT_PARSE_FAILED:" + path.name) from exc

    if not isinstance(value, dict):
        _fail("JSON_INPUT_OBJECT_REQUIRED:" + path.name)

    return value


def _write_exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        _fail("EVIDENCE_FILE_ALREADY_EXISTS:" + path.name)

    fd = secure_open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        mode,
    )

    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    data = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    _write_exclusive(path, data)


def _run_fixed(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WriteBoundaryError("FIXED_PROCESS_TIMEOUT") from exc

    if len(result.stdout) > MAX_RUN_OUTPUT or len(result.stderr) > MAX_RUN_OUTPUT:
        _fail("FIXED_PROCESS_OUTPUT_LIMIT")

    return result


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return _run_fixed(
        [executable_path("git"), "-C", str(REPO), *args],
        cwd=REPO,
        env=dict(_GIT_ENV),
        timeout=10,
    )


def _git_text(*args: str) -> str:
    result = _git(*args)
    if result.returncode != 0:
        _fail("GIT_READ_FAILED:" + ":".join(args))
    return result.stdout.decode("utf-8", errors="strict").strip()


def _porcelain_paths(data: bytes) -> list[str]:
    entries = data.split(b"\0")
    paths: list[str] = []

    for raw in entries:
        if not raw:
            continue
        if len(raw) < 4:
            _fail("GIT_PORCELAIN_INVALID")
        text = raw.decode("utf-8", errors="strict")
        paths.append(text[3:])

    return paths


def _require_repo_clean() -> None:
    result = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0:
        _fail("GIT_STATUS_FAILED")
    if result.stdout:
        _fail("REPOSITORY_NOT_CLEAN")


def _require_only_target_modified() -> None:
    result = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0:
        _fail("GIT_STATUS_FAILED")

    paths = _porcelain_paths(result.stdout)
    if paths != [TARGET_REPO_RELATIVE]:
        _fail("ROLLBACK_REPOSITORY_SCOPE_CHANGED")


def _require_tracked_target() -> None:
    result = _git(
        "ls-files",
        "--error-unmatch",
        "--",
        TARGET_REPO_RELATIVE,
    )
    if result.returncode != 0:
        _fail("TARGET_NOT_GIT_TRACKED")


def _target_path() -> Path:
    project_root = PROJECT.resolve(strict=True)
    relative = Path(contract.TARGET_RELATIVE_PATH)

    if relative.is_absolute() or ".." in relative.parts:
        _fail("TARGET_POLICY_INVALID")

    target = PROJECT / relative
    parent = target.parent.resolve(strict=True)

    if not parent.is_relative_to(project_root):
        _fail("TARGET_PARENT_ESCAPED_PROJECT")

    return target


def _read_target() -> tuple[bytes, os.stat_result]:
    target = _target_path()
    flags = os.O_RDONLY | CLOEXEC | NOFOLLOW

    try:
        fd = secure_open(target, flags)
    except OSError as exc:
        raise WriteBoundaryError("TARGET_OPEN_FAILED") from exc

    try:
        st = os.fstat(fd)

        if not stat.S_ISREG(st.st_mode):
            _fail("TARGET_NOT_REGULAR")
        if not owned_by_current_user(fd):
            _fail("TARGET_OWNER_INVALID")
        if not mode_matches(fd, TARGET_REQUIRED_MODE):
            _fail("TARGET_MODE_INVALID")
        if st.st_size < 1 or st.st_size > contract.TARGET_MAX_BYTES:
            _fail("TARGET_SIZE_INVALID")

        data = bytearray()
        while len(data) <= contract.TARGET_MAX_BYTES:
            chunk = os.read(fd, min(65536, contract.TARGET_MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)

        if len(data) > contract.TARGET_MAX_BYTES:
            _fail("TARGET_READ_LIMIT_EXCEEDED")

    finally:
        os.close(fd)

    try:
        bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WriteBoundaryError("TARGET_NOT_UTF8") from exc

    return bytes(data), st


def _canonical_qml_image_id() -> str:
    result = _run_fixed(
        [
            executable_path("podman"),
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            QML_IMAGE_REF,
        ],
        timeout=10,
    )
    if result.returncode != 0:
        _fail("QML_IMAGE_INSPECT_FAILED")

    value = result.stdout.decode("ascii", errors="strict").strip()
    if value.startswith("sha256:"):
        value = value[7:]

    if value != QML_IMAGE_ID:
        _fail("QML_IMAGE_ID_DRIFT")

    return value


def _qml_gate(candidate: bytes, evidence: Path, label: str) -> str:
    _canonical_qml_image_id()

    run_dir = evidence / label
    input_dir = run_dir / "input"
    output_dir = run_dir / "output"

    if run_dir.exists() or run_dir.is_symlink():
        _fail("QML_GATE_EVIDENCE_ALREADY_EXISTS")

    input_dir.mkdir(parents=True, mode=0o700)
    output_dir.mkdir(parents=True, mode=0o700)

    _write_exclusive(input_dir / "source", candidate, 0o400)

    components = PROJECT / "qml/components"
    target_name = Path(contract.TARGET_RELATIVE_PATH).name

    for dep in sorted(components.glob("*.qml")):
        if dep.name == target_name:
            continue
        if dep.is_symlink() or not dep.is_file():
            _fail("QML_DEPENDENCY_INVALID:" + dep.name)
        destination = input_dir / dep.name
        _write_exclusive(destination, dep.read_bytes(), 0o400)

    argv = [
        executable_path("podman"),
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--no-hosts",
        "--read-only",
        "--read-only-tmpfs=false",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs",
        "/work:rw,noexec,nosuid,nodev,size=64m,mode=0755",
        "--cap-drop=all",
        "--security-opt=no-new-privileges",
        "--userns=keep-id",
        "--user",
        container_user(),
        "--pids-limit=128",
        "--memory=512m",
        "--memory-swap=512m",
        "--cpus=1",
        "--mount",
        f"type=bind,src={input_dir},target=/input,ro=true,relabel=private",
        "--mount",
        f"type=bind,src={output_dir},target=/output,rw=true,relabel=private",
        QML_IMAGE_ID,
        "--target",
        "/input/source",
        "--name",
        target_name,
        "--output",
        "/output/report.json",
    ]

    result = _run_fixed(argv, timeout=30)
    if result.returncode != 0:
        _fail("QML_GATE_PROCESS_FAILED")

    report_path = output_dir / "report.json"
    report = _read_json_regular(report_path)
    qml = report.get("qml")
    source = report.get("source")

    if not isinstance(qml, dict) or not isinstance(source, dict):
        _fail("QML_GATE_REPORT_SURFACE_INVALID")
    if report.get("status") != "PASS":
        _fail("QML_GATE_STATUS_NOT_PASS")
    if qml.get("success") is not True or qml.get("return_code") != 0:
        _fail("QML_GATE_QML_RESULT_INVALID")
    if source.get("container_path") != "/input/source":
        _fail("QML_GATE_SOURCE_PATH_INVALID")
    if source.get("original_name") != target_name:
        _fail("QML_GATE_ORIGINAL_NAME_INVALID")

    return _sha256(report_path.read_bytes())


def _proposal_path(evidence: Path) -> Path:
    return evidence / "proposal.json"


def _load_proposal(evidence: Path, proposal_id: str) -> dict[str, Any]:
    proposal = _read_json_regular(_proposal_path(evidence))

    expected_fields = {
        "schema",
        "proposal_id",
        "target_relative_path",
        "workspace_object_id",
        "context_reference",
        "head",
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
        "proposal_gate_report_sha256",
        "approval_command",
        "reject_command",
    }
    if set(proposal) != expected_fields:
        _fail("PROPOSAL_FIELDS_INVALID")
    if proposal["schema"] != contract.PROPOSAL_SCHEMA:
        _fail("PROPOSAL_SCHEMA_INVALID")
    if proposal["proposal_id"] != proposal_id:
        _fail("PROPOSAL_ID_MISMATCH")
    if proposal["target_relative_path"] != contract.TARGET_RELATIVE_PATH:
        _fail("PROPOSAL_TARGET_MISMATCH")
    if proposal["workspace_object_id"] != contract.TARGET_WORKSPACE_OBJECT_ID:
        _fail("PROPOSAL_WORKSPACE_MISMATCH")
    if proposal["context_reference"] != contract.TARGET_CONTEXT_REFERENCE:
        _fail("PROPOSAL_CONTEXT_MISMATCH")

    head = proposal["head"]
    if (
        not isinstance(head, str)
        or len(head) not in (40, 64)
        or any(ch not in "0123456789abcdef" for ch in head)
    ):
        _fail("PROPOSAL_GIT_HEAD_INVALID")

    for key in (
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
        "proposal_gate_report_sha256",
    ):
        value = proposal[key]
        if not isinstance(value, str) or contract.SHA256_RE.fullmatch(value) is None:
            _fail("PROPOSAL_SHA_INVALID:" + key)

    return proposal


def _load_bound_bytes(
    evidence: Path,
    proposal: dict[str, Any],
) -> tuple[bytes, bytes]:
    before_path = evidence / "before.bin"
    candidate_path = evidence / "candidate.bin"

    if before_path.is_symlink() or not before_path.is_file():
        _fail("PROPOSAL_BEFORE_MISSING")
    if candidate_path.is_symlink() or not candidate_path.is_file():
        _fail("PROPOSAL_CANDIDATE_MISSING")

    before = before_path.read_bytes()
    candidate = candidate_path.read_bytes()

    if _sha256(before) != proposal["before_sha256"]:
        _fail("PROPOSAL_BEFORE_HASH_MISMATCH")
    if _sha256(candidate) != proposal["candidate_sha256"]:
        _fail("PROPOSAL_CANDIDATE_HASH_MISMATCH")
    if len(before) > contract.TARGET_MAX_BYTES or len(candidate) > contract.TARGET_MAX_BYTES:
        _fail("PROPOSAL_BOUND_BYTES_TOO_LARGE")

    return before, candidate


def _atomic_replace(candidate: bytes) -> None:
    target = _target_path()
    parent = target.parent
    temporary = parent / (
        "." + target.name + ".gg-write-" + str(time.time_ns())
    )

    fd = secure_open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
    )

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(candidate)
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary, TARGET_REQUIRED_MODE)
        os.replace(temporary, target)

        sync_directory(parent)

    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _response(
    request: dict[str, Any],
    *,
    status: str,
    output: str,
    before_sha: str,
    candidate_sha: str,
    gate_status: str,
) -> dict[str, Any]:
    value = {
        "schema": contract.RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "action": request["action"],
        "proposal_id": request["proposal_id"],
        "status": status,
        "output": output,
        "evidence": {
            "authority": contract.AUTHORITY,
            "effect_class": contract.EFFECT_CLASS,
            "network_authority": contract.NETWORK_AUTHORITY,
            "general_action_authority": contract.GENERAL_ACTION_AUTHORITY,
            "model_autonomous_write_invocation":
                contract.MODEL_AUTONOMOUS_WRITE_INVOCATION,
            "target_relative_path": contract.TARGET_RELATIVE_PATH,
            "before_sha256": before_sha,
            "candidate_sha256": candidate_sha,
            "output_sha256": _sha256(output.encode("utf-8")),
            "gate_status": gate_status,
        },
    }
    return contract.validate_response(
        value,
        request["request_id"],
        request["action"],
        request["proposal_id"],
    )


def _response_path(evidence: Path, action: str) -> Path:
    return evidence / ("response-" + action.lower() + ".json")


def _write_response(evidence: Path, request: dict[str, Any], response: dict[str, Any]) -> None:
    _write_json_exclusive(_response_path(evidence, request["action"]), response)


def _propose(
    request: dict[str, Any],
    evidence: Path,
) -> dict[str, Any]:
    _require_repo_clean()
    _require_tracked_target()

    before, _st = _read_target()
    before_text = before.decode("utf-8")
    old_text = request["arguments"]["old_text"]
    new_text = request["arguments"]["new_text"]

    count = before_text.count(old_text)
    if count != 1:
        _fail("PATCH_MATCH_COUNT_" + str(count))

    candidate_text = before_text.replace(old_text, new_text, 1)
    candidate = candidate_text.encode("utf-8")

    if len(candidate) < 1 or len(candidate) > contract.TARGET_MAX_BYTES:
        _fail("CANDIDATE_SIZE_INVALID")

    before_sha = _sha256(before)
    candidate_sha = _sha256(candidate)

    if before_sha == candidate_sha:
        _fail("CANDIDATE_HASH_UNCHANGED")

    diff = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile="a/" + TARGET_REPO_RELATIVE,
            tofile="b/" + TARGET_REPO_RELATIVE,
            n=3,
        )
    )

    diff_bytes = diff.encode("utf-8")
    if not diff_bytes or len(diff_bytes) > 32768:
        _fail("DIFF_SIZE_INVALID")

    _write_exclusive(evidence / "before.bin", before)
    _write_exclusive(evidence / "candidate.bin", candidate)
    _write_exclusive(evidence / "diff.txt", diff_bytes)

    gate_report_sha = _qml_gate(candidate, evidence, "qml-gate-proposal")
    head = _git_text("rev-parse", "HEAD")

    approval_command = (
        "/approve-write "
        + request["proposal_id"]
        + " "
        + candidate_sha
    )
    reject_command = (
        "/reject-write "
        + request["proposal_id"]
        + " "
        + candidate_sha
    )

    proposal = {
        "schema": contract.PROPOSAL_SCHEMA,
        "proposal_id": request["proposal_id"],
        "target_relative_path": contract.TARGET_RELATIVE_PATH,
        "workspace_object_id": request["workspace_object_id"],
        "context_reference": request["context_reference"],
        "head": head,
        "before_sha256": before_sha,
        "candidate_sha256": candidate_sha,
        "diff_sha256": _sha256(diff_bytes),
        "proposal_gate_report_sha256": gate_report_sha,
        "approval_command": approval_command,
        "reject_command": reject_command,
    }
    _write_json_exclusive(_proposal_path(evidence), proposal)

    output = (
        "WRITE_PROPOSAL=WAITING_APPROVAL\n"
        + "TARGET="
        + contract.TARGET_RELATIVE_PATH
        + "\n"
        + "BEFORE_SHA256="
        + before_sha
        + "\n"
        + "CANDIDATE_SHA256="
        + candidate_sha
        + "\n"
        + "DIFF_SHA256="
        + proposal["diff_sha256"]
        + "\n"
        + "QML_GATE=PASS\n"
        + "----- BEGIN DIFF -----\n"
        + diff
        + "----- END DIFF -----\n"
        + "APPROVAL_COMMAND="
        + approval_command
        + "\n"
        + "REJECT_COMMAND="
        + reject_command
    )

    return _response(
        request,
        status="WAITING_APPROVAL",
        output=output,
        before_sha=before_sha,
        candidate_sha=candidate_sha,
        gate_status="PASS",
    )


def _require_live_proposal(
    request: dict[str, Any],
    evidence: Path,
) -> tuple[dict[str, Any], bytes, bytes]:
    proposal = _load_proposal(evidence, request["proposal_id"])
    before, candidate = _load_bound_bytes(evidence, proposal)

    if _git_text("rev-parse", "HEAD") != proposal["head"]:
        _fail("PROPOSAL_HEAD_STALE")

    return proposal, before, candidate


def _approve(
    request: dict[str, Any],
    evidence: Path,
) -> dict[str, Any]:
    proposal, before, candidate = _require_live_proposal(request, evidence)

    candidate_sha = request["arguments"]["candidate_sha256"]
    if candidate_sha != proposal["candidate_sha256"]:
        _fail("APPROVAL_CANDIDATE_SHA_MISMATCH")

    exact_command = (
        "/approve-write "
        + request["proposal_id"]
        + " "
        + candidate_sha
    )
    if exact_command != proposal["approval_command"]:
        _fail("APPROVAL_COMMAND_BINDING_MISMATCH")

    if (evidence / "rejected.json").exists():
        _fail("PROPOSAL_ALREADY_REJECTED")
    if (evidence / "applied.json").exists():
        _fail("PROPOSAL_ALREADY_APPLIED")

    _require_repo_clean()
    current, before_st = _read_target()

    if _sha256(current) != proposal["before_sha256"] or current != before:
        _fail("PROPOSAL_STALE_BEFORE_APPLY")

    _write_json_exclusive(
        evidence / "approval-attempt.json",
        {
            "proposal_id": request["proposal_id"],
            "candidate_sha256": candidate_sha,
            "approval_command": exact_command,
        },
    )

    _qml_gate(candidate, evidence, "qml-gate-approval")

    current2, st2 = _read_target()
    if _sha256(current2) != proposal["before_sha256"] or current2 != before:
        _fail("TARGET_CHANGED_DURING_GATE")
    if (
        before_st.st_dev != st2.st_dev
        or before_st.st_ino != st2.st_ino
    ):
        _fail("TARGET_IDENTITY_CHANGED_DURING_GATE")

    write_started = False

    try:
        _atomic_replace(candidate)
        write_started = True

        after, _after_st = _read_target()
        after_sha = _sha256(after)

        if after_sha != proposal["candidate_sha256"] or after != candidate:
            _fail("POSTWRITE_VERIFICATION_FAILED")

        applied = {
            "schema": "gg.workbench.write-apply-receipt.v1",
            "proposal_id": request["proposal_id"],
            "target_relative_path": contract.TARGET_RELATIVE_PATH,
            "before_sha256": proposal["before_sha256"],
            "candidate_sha256": proposal["candidate_sha256"],
            "post_sha256": after_sha,
            "approval_command": exact_command,
            "effect_verified": True,
        }
        _write_json_exclusive(evidence / "applied.json", applied)

    except BaseException:
        if write_started:
            try:
                current_after_failure, _failure_st = _read_target()
                if current_after_failure == candidate:
                    _atomic_replace(before)
                    restored, _restored_st = _read_target()
                    if restored != before:
                        _fail("AUTOMATIC_ROLLBACK_VERIFICATION_FAILED")
            except BaseException:
                pass
        raise

    rollback_command = (
        "/rollback-write "
        + request["proposal_id"]
        + " "
        + proposal["candidate_sha256"]
        + " "
        + proposal["before_sha256"]
    )

    output = (
        "WRITE_APPLY=PASS\n"
        + "TARGET="
        + contract.TARGET_RELATIVE_PATH
        + "\n"
        + "BEFORE_SHA256="
        + proposal["before_sha256"]
        + "\n"
        + "POST_SHA256="
        + after_sha
        + "\n"
        + "EFFECT_VERIFIED=YES\n"
        + "ROLLBACK_COMMAND="
        + rollback_command
    )

    return _response(
        request,
        status="APPLIED_VERIFIED",
        output=output,
        before_sha=proposal["before_sha256"],
        candidate_sha=proposal["candidate_sha256"],
        gate_status="PASS",
    )


def _reject(
    request: dict[str, Any],
    evidence: Path,
) -> dict[str, Any]:
    proposal, before, _candidate = _require_live_proposal(request, evidence)

    candidate_sha = request["arguments"]["candidate_sha256"]
    if candidate_sha != proposal["candidate_sha256"]:
        _fail("REJECT_CANDIDATE_SHA_MISMATCH")

    exact_command = (
        "/reject-write "
        + request["proposal_id"]
        + " "
        + candidate_sha
    )
    if exact_command != proposal["reject_command"]:
        _fail("REJECT_COMMAND_BINDING_MISMATCH")

    if (evidence / "approval-attempt.json").exists() or (evidence / "applied.json").exists():
        _fail("PROPOSAL_ALREADY_USED")
    if (evidence / "rejected.json").exists():
        _fail("PROPOSAL_ALREADY_REJECTED")

    _require_repo_clean()
    current, _st = _read_target()
    if current != before or _sha256(current) != proposal["before_sha256"]:
        _fail("PROPOSAL_STALE_BEFORE_REJECT")

    _write_json_exclusive(
        evidence / "rejected.json",
        {
            "schema": "gg.workbench.write-reject-receipt.v1",
            "proposal_id": request["proposal_id"],
            "candidate_sha256": candidate_sha,
            "reject_command": exact_command,
            "source_write": False,
        },
    )

    output = (
        "WRITE_REJECT=PASS\n"
        + "SOURCE_WRITE=NO\n"
        + "TARGET="
        + contract.TARGET_RELATIVE_PATH
        + "\n"
        + "BEFORE_SHA256="
        + proposal["before_sha256"]
    )

    return _response(
        request,
        status="REJECTED_NO_WRITE",
        output=output,
        before_sha=proposal["before_sha256"],
        candidate_sha=proposal["candidate_sha256"],
        gate_status="NOT_RUN",
    )


def _rollback(
    request: dict[str, Any],
    evidence: Path,
) -> dict[str, Any]:
    proposal, before, candidate = _require_live_proposal(request, evidence)

    if request["arguments"]["candidate_sha256"] != proposal["candidate_sha256"]:
        _fail("ROLLBACK_CANDIDATE_SHA_MISMATCH")
    if request["arguments"]["before_sha256"] != proposal["before_sha256"]:
        _fail("ROLLBACK_BEFORE_SHA_MISMATCH")

    exact_command = (
        "/rollback-write "
        + request["proposal_id"]
        + " "
        + proposal["candidate_sha256"]
        + " "
        + proposal["before_sha256"]
    )

    applied_path = evidence / "applied.json"
    applied = _read_json_regular(applied_path)
    if applied.get("effect_verified") is not True:
        _fail("ROLLBACK_APPLY_RECEIPT_INVALID")
    if applied.get("proposal_id") != request["proposal_id"]:
        _fail("ROLLBACK_APPLY_RECEIPT_MISMATCH")
    if (evidence / "rollback.json").exists():
        _fail("ROLLBACK_ALREADY_USED")

    _require_only_target_modified()
    current, _st = _read_target()
    if current != candidate or _sha256(current) != proposal["candidate_sha256"]:
        _fail("ROLLBACK_TARGET_NOT_EXACT_CANDIDATE")

    _write_json_exclusive(
        evidence / "rollback-attempt.json",
        {
            "proposal_id": request["proposal_id"],
            "rollback_command": exact_command,
            "before_sha256": proposal["before_sha256"],
        },
    )

    _qml_gate(before, evidence, "qml-gate-rollback")

    current2, _st2 = _read_target()
    if current2 != candidate or _sha256(current2) != proposal["candidate_sha256"]:
        _fail("ROLLBACK_TARGET_CHANGED_DURING_GATE")

    _atomic_replace(before)

    restored, _restored_st = _read_target()
    if restored != before or _sha256(restored) != proposal["before_sha256"]:
        _fail("ROLLBACK_POSTWRITE_VERIFICATION_FAILED")

    _require_repo_clean()

    _write_json_exclusive(
        evidence / "rollback.json",
        {
            "schema": "gg.workbench.write-rollback-receipt.v1",
            "proposal_id": request["proposal_id"],
            "before_sha256": proposal["before_sha256"],
            "restored_sha256": _sha256(restored),
            "rollback_command": exact_command,
            "effect_verified": True,
        },
    )

    output = (
        "WRITE_ROLLBACK=PASS\n"
        + "TARGET="
        + contract.TARGET_RELATIVE_PATH
        + "\n"
        + "RESTORED_SHA256="
        + proposal["before_sha256"]
        + "\n"
        + "EFFECT_VERIFIED=YES\n"
        + "GIT_STATUS=CLEAN"
    )

    return _response(
        request,
        status="ROLLED_BACK_VERIFIED",
        output=output,
        before_sha=proposal["before_sha256"],
        candidate_sha=proposal["candidate_sha256"],
        gate_status="PASS",
    )


def execute(evidence_raw: str, request_raw: str) -> dict[str, Any]:
    request_path = _safe_request_path(request_raw)
    request = contract.validate_request(_read_json_regular(request_path))
    create = request["action"] == contract.ACTION_PROPOSE
    evidence = _safe_evidence_path(
        evidence_raw,
        request["proposal_id"],
        create=create,
    )

    action = request["action"]

    if action == contract.ACTION_PROPOSE:
        response = _propose(request, evidence)
    elif action == contract.ACTION_APPROVE:
        response = _approve(request, evidence)
    elif action == contract.ACTION_REJECT:
        response = _reject(request, evidence)
    elif action == contract.ACTION_ROLLBACK:
        response = _rollback(request, evidence)
    else:
        _fail("ACTION_UNREACHABLE")

    _write_response(evidence, request, response)
    return response


def selftest() -> int:
    if QML_IMAGE_ID != "851b076f4c9d16ecff0b802276858ff4756bd226387f09db7b5a9bb0222d9cef":
        raise RuntimeError("QML image lock mismatch")
    if contract.TARGET_RELATIVE_PATH != "qml/components/ContextComposer.qml":
        raise RuntimeError("write target drift")
    if contract.AUTHORITY != "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1":
        raise RuntimeError("write authority drift")

    fixture = b" M projects/gg-ai-desktop/qml/components/ContextComposer.qml\0"
    if _porcelain_paths(fixture) != [TARGET_REPO_RELATIVE]:
        raise RuntimeError("porcelain parser fixture failed")

    before = b"alpha\nbeta\n"
    old = "beta"
    new = "gamma"
    text = before.decode("utf-8")
    if text.count(old) != 1:
        raise RuntimeError("replace-once fixture invalid")
    candidate = text.replace(old, new, 1).encode("utf-8")
    if _sha256(candidate) == _sha256(before):
        raise RuntimeError("candidate fixture hash unchanged")

    print("WRITE_RUNNER_SELFTEST=PASS")
    print("WRITE_AUTHORITY=" + contract.AUTHORITY)
    print("TARGET=" + contract.TARGET_RELATIVE_PATH)
    print("CALLER_SUPPLIED_PATH_AUTHORITY=NONE")
    print("CALLER_SUPPLIED_ARGV_AUTHORITY=NONE")
    print("CALLER_SUPPLIED_EXECUTABLE_AUTHORITY=NONE")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    print("MODEL_AUTONOMOUS_WRITE_INVOCATION=DISABLED_V1")
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        return selftest()

    if len(sys.argv) != 4 or sys.argv[1] != "--execute-write":
        print(
            "usage: write_runner.py --execute-write EVIDENCE REQUEST_JSON",
            file=sys.stderr,
        )
        return 64

    evidence_raw = sys.argv[2]
    request_raw = sys.argv[3]

    try:
        response = execute(evidence_raw, request_raw)
    except BaseException as exc:
        # The caller receives a nonzero status. No broad exception text is
        # treated as authority or success evidence.
        try:
            request = _read_json_regular(_safe_request_path(request_raw))
            proposal_id = str(request.get("proposal_id", "unknown"))
            action = str(request.get("action", "unknown")).lower()
            path = Path(evidence_raw)
            if path.is_dir() and not path.is_symlink():
                _write_json_exclusive(
                    path / ("failure-" + action + ".json"),
                    {
                        "proposal_id": proposal_id,
                        "reason": type(exc).__name__ + ":" + str(exc),
                    },
                )
        except BaseException:
            pass
        print(
            "WRITE_EXECUTION=STOP",
            file=sys.stderr,
        )
        print(
            "STOP_REASON=" + type(exc).__name__ + ":" + str(exc),
            file=sys.stderr,
        )
        return 1

    print("WRITE_EXECUTION=PASS")
    print("WRITE_ACTION=" + str(response["action"]))
    print("WRITE_STATUS=" + str(response["status"]))
    print("WRITE_AUTHORITY=" + contract.AUTHORITY)
    print("WRITE_NETWORK_AUTHORITY=NONE")
    print("WRITE_GENERAL_ACTION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
