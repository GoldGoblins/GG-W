#!/usr/bin/env python3
"""GG Autonomy Bootstrap v1 deterministic runtime conductor.

This is not a new agent brain. It drives the published K7 task/ledger/belief/
Goal-WHY/hypothesis/revalidation layers, the existing Safe Tools, a strict
untrusted local-model semantic proposer, a task-bound candidate workspace, and
the existing Limited Write proposal boundary.
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
)
from backend.platform_support import (
    executable_path,
    host_environment,
    private_runtime_root,
    workspace_root,
)


import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from backend import autonomy_contract as contract
from backend import autonomy_cognitive_adapter as cognition
from backend import autonomy_candidate_runner as candidate_runner
from backend import safe_tool_contract
from backend import write_contract

PROJECT = Path(__file__).resolve().parents[1]
REPO = workspace_root()
RUNTIME = private_runtime_root()

SAFE_TOOL_RUNNER = PROJECT / "backend/safe_tool_runner.py"
AUTONOMY_MODEL_RUNNER = PROJECT / "backend/autonomy_model_runner.py"
WRITE_RUNNER = PROJECT / "backend/write_runner.py"

TARGET_REPO_RELATIVE = (
    "projects/gg-ai-desktop/" + contract.TARGET_RELATIVE_PATH
)

MAX_PROCESS_OUTPUT = 65536
PROCESS_TIMEOUT = 900

_GIT_ENV = host_environment({
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_REPLACE_OBJECTS": "1",
})


class AutonomyControllerError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
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


def _write_exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        raise AutonomyControllerError("EVIDENCE_EXISTS:" + path.name)
    fd = secure_open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        mode,
    )
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_exclusive(path: Path, value: Any, mode: int = 0o600) -> None:
    _write_exclusive(path, _canonical(value), mode)


def _read_json_regular(path: Path, limit: int = 131072) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AutonomyControllerError("JSON_INPUT_INVALID:" + path.name)
    info = path.stat()
    if info.st_size < 2 or info.st_size > limit:
        raise AutonomyControllerError("JSON_INPUT_SIZE_INVALID:" + path.name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutonomyControllerError("JSON_INPUT_PARSE_FAILED:" + path.name) from exc
    if type(value) is not dict:
        raise AutonomyControllerError("JSON_INPUT_OBJECT_REQUIRED:" + path.name)
    return value


def _task_root(raw: str | Path, task_id: str | None = None) -> Path:
    path = Path(raw)
    runtime = RUNTIME.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved.parent != runtime:
        raise AutonomyControllerError("TASK_ROOT_PARENT_INVALID")
    if path.is_symlink() or not path.is_dir():
        raise AutonomyControllerError("TASK_ROOT_INVALID")
    if task_id is not None:
        expected = "gg-autonomy-task." + task_id.removeprefix("task-")
        if path.name != expected:
            raise AutonomyControllerError("TASK_ROOT_TASK_BINDING_MISMATCH")
    info = path.stat()
    if not owned_by_current_user(path) or not mode_matches(path, 0o700):
        raise AutonomyControllerError("TASK_ROOT_OWNER_MODE_INVALID")
    return resolved


def _run(
    argv: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
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
        raise AutonomyControllerError("PROCESS_TIMEOUT:" + argv[0]) from exc
    if len(result.stdout) > MAX_PROCESS_OUTPUT or len(result.stderr) > MAX_PROCESS_OUTPUT:
        raise AutonomyControllerError("PROCESS_OUTPUT_LIMIT:" + argv[0])
    return result


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return _run(
        [executable_path("git"), "-C", str(REPO), *args],
        timeout=15,
        cwd=REPO,
        env=dict(_GIT_ENV),
    )


def _git_text(*args: str) -> str:
    result = _git(*args)
    if result.returncode != 0:
        raise AutonomyControllerError("GIT_READ_FAILED:" + ":".join(args))
    return result.stdout.decode("utf-8", errors="strict").strip()


def _require_base_state(base_head: str, *, allow_target_dirty: bool = False) -> None:
    head = _git_text("rev-parse", "HEAD")
    if head != base_head:
        raise AutonomyControllerError("BASE_HEAD_DRIFT")
    result = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0:
        raise AutonomyControllerError("GIT_STATUS_FAILED")
    if not result.stdout:
        if allow_target_dirty:
            raise AutonomyControllerError("EXPECTED_TARGET_EFFECT_MISSING")
        return
    if not allow_target_dirty:
        raise AutonomyControllerError("REPOSITORY_NOT_CLEAN")

    entries = [item for item in result.stdout.split(b"\0") if item]
    if len(entries) != 1:
        raise AutonomyControllerError("HOST_EFFECT_SCOPE_MULTIPLE_PATHS")
    text = entries[0].decode("utf-8", errors="strict")
    if len(text) < 4 or text[3:] != TARGET_REPO_RELATIVE:
        raise AutonomyControllerError("HOST_EFFECT_SCOPE_INVALID")


class EventStream:
    def __init__(self, root: Path, start_seq: int = 0) -> None:
        self.root = root
        self.path = root / "events.jsonl"
        self.seq = start_seq

    def emit(self, phase: str, state: str, text: str) -> None:
        self.seq += 1
        event = {
            "schema": "gg.workbench.autonomy-event.v1",
            "step_seq": self.seq,
            "phase": phase,
            "state": state,
            "text": text,
        }
        data = _canonical(event)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | NOFOLLOW
        fd = secure_open(self.path, flags, 0o600)
        with os.fdopen(fd, "ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        print(
            "GG_AUTONOMY_EVENT="
            + json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            flush=True,
        )


def _safe_tool_read(
    root: Path,
    task_id: str,
) -> tuple[str, dict[str, Any]]:
    nonce = uuid.uuid4().hex[:24]
    evidence = RUNTIME / ("gg-safe-tool." + nonce)
    request_path = RUNTIME / ("gg-workbench-tool-request." + nonce + ".json")
    if evidence.exists() or evidence.is_symlink():
        raise AutonomyControllerError("SAFE_TOOL_EVIDENCE_COLLISION")
    evidence.mkdir(mode=0o700)
    request = safe_tool_contract.validate_request(
        {
            "schema": safe_tool_contract.REQUEST_SCHEMA,
            "request_id": "tool-" + uuid.uuid4().hex,
            "profile": safe_tool_contract.PROFILE_READ,
            "arguments": {"path": TARGET_REPO_RELATIVE},
        }
    )
    _write_exclusive(
        request_path,
        (safe_tool_contract.canonical_request_json(request) + "\n").encode("utf-8"),
        0o600,
    )
    try:
        result = _run(
            [
                sys.executable,
                "-B",
                str(SAFE_TOOL_RUNNER),
                "--execute-tool",
                str(evidence),
                str(request_path),
            ],
            timeout=60,
        )
        if result.returncode != 0:
            raise AutonomyControllerError(
                "SAFE_TOOL_READ_FAILED:"
                + result.stderr.decode("utf-8", errors="replace")[-4000:]
            )
        response = _read_json_regular(evidence / "response.json")
        validated = safe_tool_contract.validate_response(
            response,
            request["request_id"],
            safe_tool_contract.PROFILE_READ,
        )
        if validated["status"] != "PASS":
            raise AutonomyControllerError("SAFE_TOOL_READ_STATUS_NOT_PASS")
        trace_target = root / "safe-tool-read-response.json"
        _write_json_exclusive(trace_target, validated)
        return str(validated["output"]), validated
    finally:
        try:
            request_path.unlink()
        except OSError:
            pass


def _extract_read_text(output: str) -> tuple[str, str]:
    begin = "----- BEGIN FILE -----\n"
    end = "\n----- END FILE -----"
    if begin not in output or end not in output:
        raise AutonomyControllerError("SAFE_READ_OUTPUT_FORMAT_INVALID")
    head, body = output.split(begin, 1)
    text, tail = body.rsplit(end, 1)
    if tail.strip():
        raise AutonomyControllerError("SAFE_READ_OUTPUT_TRAILING_DATA")
    sha_line = next(
        (line for line in head.splitlines() if line.startswith("SHA256=")),
        None,
    )
    if sha_line is None:
        raise AutonomyControllerError("SAFE_READ_SHA_MISSING")
    sha = sha_line.split("=", 1)[1].strip()
    if not text.endswith("\n"):
        # _profile_read always inserts one separator newline before END even if
        # the file itself did not end with one; use direct target verification
        # below to eliminate ambiguity.
        pass
    actual = (PROJECT / contract.TARGET_RELATIVE_PATH).read_bytes()
    if _sha256(actual) != sha:
        raise AutonomyControllerError("SAFE_READ_HOST_SHA_MISMATCH")
    return actual.decode("utf-8"), sha


def _model_proposal(
    root: Path,
    request: dict[str, Any],
    *,
    render_node: str,
) -> tuple[dict[str, str], str]:
    nonce = uuid.uuid4().hex[:24]
    evidence = RUNTIME / ("gg-wb3d-model-runner." + nonce)
    request_path = RUNTIME / ("gg-autonomy-model-request." + nonce + ".json")
    if evidence.exists() or evidence.is_symlink():
        raise AutonomyControllerError("MODEL_EVIDENCE_COLLISION")
    evidence.mkdir(mode=0o700)
    _write_json_exclusive(request_path, request, 0o600)
    try:
        result = _run(
            [
                sys.executable,
                "-B",
                str(AUTONOMY_MODEL_RUNNER),
                "--execute",
                str(evidence),
                render_node,
                str(request_path),
            ],
            timeout=PROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            raise AutonomyControllerError(
                "AUTONOMY_MODEL_FAILED:"
                + result.stderr.decode("utf-8", errors="replace")[-6000:]
            )
        proposal = _read_json_regular(evidence / "autonomy-semantic-proposal.json")
        validated = contract.validate_semantic_proposal(proposal)
        digest = _sha256(_canonical(validated))
        destination = root / ("semantic-proposal-" + str(request["attempt"]) + ".json")
        _write_json_exclusive(destination, validated)
        return validated, digest
    finally:
        try:
            request_path.unlink()
        except OSError:
            pass


def _write_host_proposal(
    root: Path,
    *,
    old_text: str,
    new_text: str,
    expected_candidate_sha: str,
) -> dict[str, Any]:
    proposal_id = "proposal-" + uuid.uuid4().hex
    evidence = RUNTIME / (
        "gg-write-proposal." + proposal_id.removeprefix("proposal-")
    )
    request_path = RUNTIME / (
        "gg-workbench-write-request." + uuid.uuid4().hex[:24] + ".json"
    )
    request = write_contract.validate_request(
        {
            "schema": write_contract.REQUEST_SCHEMA,
            "request_id": "write-" + uuid.uuid4().hex,
            "action": write_contract.ACTION_PROPOSE,
            "proposal_id": proposal_id,
            "context_reference": write_contract.TARGET_CONTEXT_REFERENCE,
            "workspace_object_id": write_contract.TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {"old_text": old_text, "new_text": new_text},
        }
    )
    _write_exclusive(
        request_path,
        (write_contract.canonical_request_json(request) + "\n").encode("utf-8"),
        0o600,
    )
    try:
        result = _run(
            [
                sys.executable,
                "-B",
                str(WRITE_RUNNER),
                "--execute-write",
                str(evidence),
                str(request_path),
            ],
            timeout=60,
        )
        if result.returncode != 0:
            raise AutonomyControllerError(
                "HOST_PROPOSAL_FAILED:"
                + result.stderr.decode("utf-8", errors="replace")[-6000:]
            )
        response = _read_json_regular(evidence / "response-propose.json")
        validated = write_contract.validate_response(
            response,
            request["request_id"],
            write_contract.ACTION_PROPOSE,
            proposal_id,
        )
        if validated["status"] != "WAITING_APPROVAL":
            raise AutonomyControllerError("HOST_PROPOSAL_STATUS_INVALID")
        proposal = _read_json_regular(evidence / "proposal.json")
        if proposal["candidate_sha256"] != expected_candidate_sha:
            raise AutonomyControllerError("HOST_PROPOSAL_CANDIDATE_MISMATCH")
        trace = root / "host-write-proposal.json"
        _write_json_exclusive(trace, proposal)
        return {
            "proposal_id": proposal_id,
            "candidate_sha256": proposal["candidate_sha256"],
            "before_sha256": proposal["before_sha256"],
            "approval_command": proposal["approval_command"],
        }
    finally:
        try:
            request_path.unlink()
        except OSError:
            pass


def _claim_statement(prefix: str, payload: str, maximum: int = 1000) -> str:
    text = prefix + payload
    if len(text) > maximum:
        text = text[:maximum]
    return text


def execute(task_root_raw: str, request_raw: str) -> int:
    request_path = Path(request_raw)
    if request_path.is_symlink() or not request_path.is_file():
        raise AutonomyControllerError("REQUEST_PATH_INVALID")
    request = contract.validate_request(_read_json_regular(request_path))
    grant = request["grant"]
    root = _task_root(task_root_raw, grant["task_id"])
    if request_path.parent.resolve(strict=True) != root:
        raise AutonomyControllerError("REQUEST_NOT_TASK_BOUND")

    global_receipt_path = RUNTIME / (
        "gg-autonomy-grant-receipt." + request["grant_sha256"]
    )
    _write_json_exclusive(
        global_receipt_path,
        {
            "schema": "gg.workbench.autonomy-global-grant-consumption.v1",
            "task_id": grant["task_id"],
            "session_id": grant["session_id"],
            "grant_sha256": request["grant_sha256"],
            "request_id": request["request_id"],
            "single_use": True,
            "runtime_lifetime": True,
        },
    )

    receipt_path = root / "grant-consumed.json"
    _write_json_exclusive(
        receipt_path,
        {
            "schema": "gg.workbench.autonomy-grant-consumption.v1",
            "task_id": grant["task_id"],
            "session_id": grant["session_id"],
            "grant_sha256": request["grant_sha256"],
            "request_id": request["request_id"],
            "single_use": True,
        },
    )

    events = EventStream(root)
    step_limit = grant["max_steps"]
    model_limit = grant["max_model_calls"]
    write_limit = grant["max_candidate_writes"]
    model_calls = 0
    candidate_writes = 0

    def emit(phase: str, state: str, text: str) -> None:
        events.emit(phase, state, text)
        if events.seq > step_limit:
            raise AutonomyControllerError("STEP_LIMIT_EXCEEDED")

    emit("INTENT", "RUNNING", "ORIGINAL_INTENT låst: " + grant["goal"])
    _require_base_state(grant["base_head"])
    emit("REVALIDATE", "PASS", "Base HEAD och clean repo revaliderade.")

    stack = cognition.load_stack()
    context = cognition.make_task_context(grant, stack=stack)
    _write_json_exclusive(root / "task-envelope.json", context["envelope"])
    _write_json_exclusive(root / "goal-why.json", context["goal_chain"])
    trace = cognition.trace_action(
        context["goal_chain"],
        context["envelope"],
        context["actions"]["candidate-patch"],
        stack=stack,
    )
    _write_json_exclusive(root / "why-trace-candidate-patch.json", trace)
    emit("WHY", "PASS", "Goal/WHY trace till kandidat-action är verifierad.")

    ledger_path = root / "ledger.jsonl"
    cognition.append_claim(
        ledger_path,
        task_id=grant["task_id"],
        origin_id=grant["session_id"],
        claim_key="user.original_intent",
        statement=grant["goal"],
        epistemic_class="OBSERVED",
        source_kind="HUMAN_INPUT",
        source_id="workbench-autonomy-goal",
        source_fingerprint=_sha256(grant["goal"].encode("utf-8")),
        stack=stack,
    )

    emit("OBSERVE", "RUNNING", "Läser exakt verifierad @current-target via GREEN Safe Tool READ.")
    read_output, read_response = _safe_tool_read(root, grant["task_id"])
    target_text, target_sha = _extract_read_text(read_output)
    cognition.append_claim(
        ledger_path,
        task_id=grant["task_id"],
        origin_id=grant["session_id"],
        claim_key="target.snapshot",
        statement=(
            contract.TARGET_RELATIVE_PATH
            + " observed sha256="
            + target_sha
        ),
        epistemic_class="OBSERVED",
        source_kind="DETERMINISTIC_TOOL",
        source_id="safe-tool:READ",
        source_fingerprint=read_response["evidence"]["output_sha256"],
        stack=stack,
    )
    emit("OBSERVE", "PASS", "Target observerad read-only · sha256 " + target_sha[:12] + "…")

    candidate_info = candidate_runner.initialize(
        root,
        grant["task_id"],
        expected_before_sha256=target_sha,
    )
    if candidate_info["bytes"] > grant["max_candidate_bytes"]:
        raise AutonomyControllerError("CANDIDATE_BYTE_LIMIT_EXCEEDED")
    emit("CANDIDATE", "PASS", "Task-bunden candidate workspace materialiserad; host repo orört.")

    diagnostic = ""
    proposal: dict[str, str] | None = None
    hypothesis_state: dict[str, Any] | None = None
    requested_keys: list[str] = []

    while proposal is None:
        model_calls += 1
        if model_calls > model_limit:
            raise AutonomyControllerError("MODEL_CALL_LIMIT_EXCEEDED")
        emit("HYPOTHESIZE", "RUNNING", "Lokal modell föreslår semantisk repair; output är UNTRUSTED_MODEL_OUTPUT.")
        model_request = {
            "schema": "gg.workbench.autonomy-model-request.v1",
            "request_id": "autonomy-model-" + uuid.uuid4().hex,
            "task_id": grant["task_id"],
            "goal": grant["goal"],
            "target_text": target_text,
            "diagnostic": diagnostic,
            "attempt": model_calls,
        }
        proposed, proposal_sha = _model_proposal(
            root,
            model_request,
            render_node=request["render_node"],
        )
        cognition.append_claim(
            ledger_path,
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key="model.proposal." + str(model_calls),
            statement=_claim_statement(
                "UNTRUSTED semantic proposal: ",
                proposed["hypothesis"] + " | why=" + proposed["why"],
            ),
            epistemic_class="UNTRUSTED_MODEL_OUTPUT",
            source_kind="MODEL_OUTPUT",
            source_id="local-autonomy-model",
            source_fingerprint=proposal_sha,
            stack=stack,
        )

        pass_key = "patch.precondition.pass." + str(model_calls)
        fail_key = "patch.precondition.fail." + str(model_calls)
        pass_candidate = cognition.make_claim_candidate(
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key=pass_key,
            statement="Exact patch precondition verified for proposal attempt " + str(model_calls),
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="autonomy-precondition",
            source_fingerprint=proposal_sha,
            stack=stack,
        )
        fail_candidate = cognition.make_claim_candidate(
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key=fail_key,
            statement="Exact patch precondition failed for proposal attempt " + str(model_calls),
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="autonomy-precondition",
            source_fingerprint=proposal_sha,
            stack=stack,
        )
        requested_keys = [pass_key, fail_key]
        records = cognition.read_records(ledger_path, stack=stack)
        hypothesis_state = cognition.make_binary_hypothesis_state(
            records=records,
            requested_claim_keys=requested_keys,
            goal_chain=context["goal_chain"],
            envelope=context["envelope"],
            pass_candidate=pass_candidate,
            fail_candidate=fail_candidate,
            pass_action_node_id=context["actions"]["candidate-patch"],
            fail_action_node_id=context["actions"]["model-propose"],
            pass_statement="Det föreslagna exakta replacementet är tekniskt applicerbart för kandidat-evaluering.",
            fail_statement="Det föreslagna replacementet kräver ny semantisk proposal innan kandidat-write.",
            information_description="Kontrollera old_text single-occurrence, non-noop och kandidatbytegräns.",
            stack=stack,
        )
        first_decision = cognition.decision(
            hypothesis_state,
            records,
            requested_keys,
            context["goal_chain"],
            context["envelope"],
            stack=stack,
        )
        if first_decision["kind"] != "GATHER_INFORMATION":
            raise AutonomyControllerError("K7H_EXPECTED_GATHER_INFORMATION")
        emit("HYPOTHESIS", "PASS", "K7-H valde GATHER_INFORMATION före kandidat-action.")

        precondition_ok = (
            target_text.count(proposed["old_text"]) == 1
            and proposed["old_text"] != proposed["new_text"]
            and len(
                target_text.replace(
                    proposed["old_text"],
                    proposed["new_text"],
                    1,
                ).encode("utf-8")
            ) <= grant["max_candidate_bytes"]
        )
        chosen = pass_candidate if precondition_ok else fail_candidate
        cognition.append_prebuilt_candidate(
            ledger_path,
            chosen,
            stack=stack,
        )
        records = cognition.read_records(ledger_path, stack=stack)
        hypothesis_state = cognition.make_binary_hypothesis_state(
            records=records,
            requested_claim_keys=requested_keys,
            goal_chain=context["goal_chain"],
            envelope=context["envelope"],
            pass_candidate=pass_candidate,
            fail_candidate=fail_candidate,
            pass_action_node_id=context["actions"]["candidate-patch"],
            fail_action_node_id=context["actions"]["model-propose"],
            pass_statement="Det föreslagna exakta replacementet är tekniskt applicerbart för kandidat-evaluering.",
            fail_statement="Det föreslagna replacementet kräver ny semantisk proposal innan kandidat-write.",
            information_description="Kontrollera old_text single-occurrence, non-noop och kandidatbytegräns.",
            stack=stack,
        )
        next_decision = cognition.decision(
            hypothesis_state,
            records,
            requested_keys,
            context["goal_chain"],
            context["envelope"],
            stack=stack,
        )
        if precondition_ok:
            if (
                next_decision["kind"] != "PLAN_ACTION"
                or next_decision["selected_action_node_id"]
                != context["actions"]["candidate-patch"]
            ):
                raise AutonomyControllerError("K7H_PATCH_PLAN_NOT_SELECTED")
            proposal = proposed
            emit("PLAN", "PASS", "K7-H promoverade stödd hypotes till PLAN_ACTION(candidate-patch).")
        else:
            if (
                next_decision["kind"] != "PLAN_ACTION"
                or next_decision["selected_action_node_id"]
                != context["actions"]["model-propose"]
            ):
                raise AutonomyControllerError("K7H_REPAIR_MODEL_PLAN_NOT_SELECTED")
            diagnostic = (
                "Föregående OLD förekom inte exakt en gång, var no-op eller överskred kandidatgräns. "
                "Föreslå en annan minimal exact single-line replacement."
            )
            emit("REPLAN", "PASS", "Precondition falsifierade första hypotesen; K7-H valde ny model-proposal.")

    assert hypothesis_state is not None
    records = cognition.read_records(ledger_path, stack=stack)
    state_base, revalidation = cognition.make_and_revalidate_state(
        participant_id="gg-autonomy-controller",
        records=records,
        requested_claim_keys=requested_keys,
        goal_chain=context["goal_chain"],
        hypothesis_state=hypothesis_state,
        envelope=context["envelope"],
        stack=stack,
    )
    _write_json_exclusive(root / "state-base-before-candidate.json", state_base)
    _write_json_exclusive(root / "state-revalidation-before-candidate.json", revalidation)
    if revalidation.get("result") != "REVALIDATED":
        raise AutonomyControllerError(
            "STATE_REVALIDATION_BLOCKED:" + str(revalidation.get("result"))
        )
    emit("REVALIDATE", "PASS", "K7-J state revalidation PASS före candidate write.")

    candidate_writes += 1
    if candidate_writes > write_limit:
        raise AutonomyControllerError("CANDIDATE_WRITE_LIMIT_EXCEEDED")
    injected = grant["test_mode"] == "INTENTIONAL_FIRST_GATE_FAILURE"
    attempt = candidate_runner.write_attempt(
        root,
        grant["task_id"],
        old_text=proposal["old_text"],
        new_text=proposal["new_text"],
        inject_invalid_qml=injected,
    )
    emit("ACT", "PASS", "Candidate edit utförd inom task-bound runtime; host repo fortfarande orört.")

    gate_label = "autonomy-candidate-gate-1"
    gate_pass = False
    gate_report_sha = ""
    try:
        gate_report_sha = candidate_runner.qml_gate(
            root,
            grant["task_id"],
            label=gate_label,
        )
        gate_pass = True
    except BaseException as exc:
        gate_error = type(exc).__name__ + ":" + str(exc)
        cognition.append_claim(
            ledger_path,
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key="candidate.gate.fail.1",
            statement=_claim_statement("Candidate QML Gate failure observed: ", gate_error),
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="qml-gate",
            source_fingerprint=_sha256(gate_error.encode("utf-8")),
            stack=stack,
        )
        emit("OBSERVE", "FAIL", "Candidate Gate FAIL observerad; plan måste repareras.")

        if not injected:
            raise AutonomyControllerError("CANDIDATE_QML_GATE_FAILED:" + gate_error)

        gate_fail_candidate = cognition.make_claim_candidate(
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key="candidate.injected-failure.observed",
            statement="Intentional first-candidate QML failure is present and bounded.",
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="autonomy-acceptance-injection",
            source_fingerprint=_sha256(gate_error.encode("utf-8")),
            stack=stack,
        )
        gate_ok_candidate = cognition.make_claim_candidate(
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key="candidate.injected-failure.absent",
            statement="Intentional QML failure is absent.",
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="autonomy-acceptance-injection",
            source_fingerprint=_sha256(attempt["intended_sha256"].encode("utf-8")),
            stack=stack,
        )
        cognition.append_prebuilt_candidate(
            ledger_path,
            gate_fail_candidate,
            stack=stack,
        )
        repair_keys = [
            gate_fail_candidate["body"]["claim_key"],
            gate_ok_candidate["body"]["claim_key"],
        ]
        records = cognition.read_records(ledger_path, stack=stack)
        repair_state = cognition.make_binary_hypothesis_state(
            records=records,
            requested_claim_keys=repair_keys,
            goal_chain=context["goal_chain"],
            envelope=context["envelope"],
            pass_candidate=gate_fail_candidate,
            fail_candidate=gate_ok_candidate,
            pass_action_node_id=context["actions"]["repair-candidate"],
            fail_action_node_id=context["actions"]["candidate-patch"],
            pass_statement="Observerad injected Gate-failure kräver bounded candidate repair.",
            fail_statement="Ingen injected failure återstår; kandidatpatch behöver inte repareras för detta fel.",
            information_description="Observera om injected acceptance-failure finns i kandidaten.",
            stack=stack,
        )
        repair_decision = cognition.decision(
            repair_state,
            records,
            repair_keys,
            context["goal_chain"],
            context["envelope"],
            stack=stack,
        )
        if (
            repair_decision["kind"] != "PLAN_ACTION"
            or repair_decision["selected_action_node_id"]
            != context["actions"]["repair-candidate"]
        ):
            raise AutonomyControllerError("K7H_REPAIR_PLAN_NOT_SELECTED")

        _base, repair_revalidation = cognition.make_and_revalidate_state(
            participant_id="gg-autonomy-controller",
            records=records,
            requested_claim_keys=repair_keys,
            goal_chain=context["goal_chain"],
            hypothesis_state=repair_state,
            envelope=context["envelope"],
            stack=stack,
        )
        if repair_revalidation.get("result") != "REVALIDATED":
            raise AutonomyControllerError("REPAIR_STATE_REVALIDATION_BLOCKED")
        emit("REPLAN", "PASS", "K7-H reviderade planen till bounded candidate repair efter verklig Gate FAIL.")

        candidate_writes += 1
        if candidate_writes > write_limit:
            raise AutonomyControllerError("CANDIDATE_WRITE_LIMIT_EXCEEDED")
        candidate_runner.repair_to_intended(
            root,
            grant["task_id"],
            old_text=proposal["old_text"],
            new_text=proposal["new_text"],
        )
        emit("REPAIR", "PASS", "Candidate reparerad till avsedd exact patch; host repo orört.")
        gate_report_sha = candidate_runner.qml_gate(
            root,
            grant["task_id"],
            label="autonomy-candidate-gate-2",
        )
        gate_pass = True

    if not gate_pass:
        raise AutonomyControllerError("CANDIDATE_GATE_NOT_PASS")
    emit("VERIFY", "PASS", "Final candidate QML Gate PASS.")

    before = candidate_runner.read_before(root, grant["task_id"])
    candidate = candidate_runner.read_candidate(root, grant["task_id"])
    before_sha = _sha256(before)
    candidate_sha = _sha256(candidate)
    diff, diff_sha = candidate_runner.diff_text(before, candidate)

    _require_base_state(grant["base_head"])
    emit("VERIFY", "PASS", "Host repo verifierat clean före persistent effect boundary.")

    changeset = contract.validate_changeset(
        {
            "schema": contract.CHANGESET_SCHEMA,
            "task_id": grant["task_id"],
            "base_head": grant["base_head"],
            "target_relative_path": contract.TARGET_RELATIVE_PATH,
            "workspace_object_id": contract.TARGET_WORKSPACE_OBJECT_ID,
            "before_sha256": before_sha,
            "candidate_sha256": candidate_sha,
            "diff_sha256": diff_sha,
            "old_text": proposal["old_text"],
            "new_text": proposal["new_text"],
            "qml_gate_report_sha256": gate_report_sha,
            "candidate_write_count": candidate_writes,
            "model_call_count": model_calls,
            "step_count": events.seq,
            "host_repo_changed_before_approval": False,
        }
    )
    _write_json_exclusive(root / "changeset.json", changeset)
    _write_exclusive(root / "changeset.diff", diff.encode("utf-8"), 0o600)
    emit("CHANGESET", "PASS", "VERIFIED CHANGESET klart; skapar endast existing Limited Write proposal.")

    host_proposal = _write_host_proposal(
        root,
        old_text=proposal["old_text"],
        new_text=proposal["new_text"],
        expected_candidate_sha=candidate_sha,
    )
    _require_base_state(grant["base_head"])

    result = contract.validate_result(
        {
            "schema": contract.RESULT_SCHEMA,
            "status": "WAITING_HOST_APPLY",
            "task_id": grant["task_id"],
            "grant_sha256": request["grant_sha256"],
            "changeset": changeset,
            "write_proposal_id": host_proposal["proposal_id"],
            "write_candidate_sha256": host_proposal["candidate_sha256"],
            "write_before_sha256": host_proposal["before_sha256"],
            "write_approval_command": host_proposal["approval_command"],
            "model_output_authority": contract.MODEL_OUTPUT_AUTHORITY,
            "network_authority": "NONE",
            "general_action_authority": "NONE",
            "host_write_performed": False,
        }
    )
    _write_json_exclusive(root / "result.json", result)
    emit(
        "BOUNDARY",
        "WAITING_FOR_USER",
        "Autonom kandidat klar. Persistent host apply kräver separat approval: "
        + result["write_approval_command"],
    )
    print("AUTONOMY_EXECUTION=PASS", flush=True)
    print("AUTONOMY_STATUS=WAITING_HOST_APPLY", flush=True)
    print("TASK_ID=" + grant["task_id"], flush=True)
    print("WRITE_PROPOSAL_ID=" + result["write_proposal_id"], flush=True)
    print("HOST_WRITE_PERFORMED=NO", flush=True)
    print("NETWORK_AUTHORITY=NONE", flush=True)
    print("GENERAL_ACTION_AUTHORITY=NONE", flush=True)
    return 0


def _existing_event_count(root: Path) -> int:
    path = root / "events.jsonl"
    if path.is_symlink() or not path.is_file():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def verify_host(task_root_raw: str) -> int:
    root = _task_root(task_root_raw)
    result = contract.validate_result(_read_json_regular(root / "result.json"))
    grant_receipt = _read_json_regular(root / "grant-consumed.json")
    task_id = result["task_id"]
    if grant_receipt.get("task_id") != task_id:
        raise AutonomyControllerError("HOST_VERIFY_TASK_BINDING_MISMATCH")

    events = EventStream(root, start_seq=_existing_event_count(root))
    events.emit("OBSERVE_HOST", "RUNNING", "Observerar verklig host-effekt efter separat Limited Write approval.")

    _require_base_state(result["changeset"]["base_head"], allow_target_dirty=True)
    actual = (PROJECT / contract.TARGET_RELATIVE_PATH).read_bytes()
    actual_sha = _sha256(actual)
    if actual_sha != result["write_candidate_sha256"]:
        raise AutonomyControllerError("HOST_EFFECT_SHA_MISMATCH")

    gate_sha = candidate_runner.qml_gate(
        root,
        task_id,
        label="autonomy-host-effect-gate",
    )
    if _sha256(candidate_runner.read_candidate(root, task_id)) != actual_sha:
        raise AutonomyControllerError("HOST_CANDIDATE_EFFECT_DIVERGED")

    stack = cognition.load_stack()
    cognition.append_claim(
        root / "ledger.jsonl",
        task_id=task_id,
        origin_id=str(grant_receipt["session_id"]),
        claim_key="host.effect",
        statement=(
            contract.TARGET_RELATIVE_PATH
            + " real host effect observed sha256="
            + actual_sha
        ),
        epistemic_class="VERIFIED",
        source_kind="LOCAL_OBSERVATION",
        source_id="autonomy-host-verify",
        source_fingerprint=actual_sha,
        stack=stack,
    )

    verify = contract.validate_host_verify(
        {
            "schema": contract.HOST_VERIFY_SCHEMA,
            "status": "DONE",
            "task_id": task_id,
            "candidate_sha256": result["write_candidate_sha256"],
            "actual_sha256": actual_sha,
            "qml_gate_report_sha256": gate_sha,
            "done_when_technical": True,
            "network_authority": "NONE",
            "general_action_authority": "NONE",
        }
    )
    _write_json_exclusive(root / "host-verify.json", verify)
    events.emit("VERIFY_DONE_WHEN", "PASS", "Real host SHA och QML Gate matchar VERIFIED CHANGESET.")
    events.emit("RESULT", "PASS", "DONE · tekniskt DONE_WHEN verifierat mot verklig host-effekt.")

    print("AUTONOMY_HOST_VERIFY=PASS")
    print("TASK_ID=" + task_id)
    print("DONE_WHEN_TECHNICAL=PASS")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    return 0


def selftest() -> int:
    stack = cognition.load_stack()
    if set(stack) != {"task", "ledger", "belief", "goal", "hypothesis", "state"}:
        raise AutonomyControllerError("SELFTEST_COGNITIVE_STACK_INVALID")

    sample_goal = "Ändra implicitHeight: 92 till implicitHeight: 93 och verifiera."
    sample_grant = {
        "schema": contract.GRANT_SCHEMA,
        "task_id": "task-" + ("a" * 32),
        "session_id": "session-" + ("b" * 32),
        "base_head": "c" * 40,
        "context_reference": contract.TARGET_CONTEXT_REFERENCE,
        "workspace_object_id": contract.TARGET_WORKSPACE_OBJECT_ID,
        "target_relative_path": contract.TARGET_RELATIVE_PATH,
        "goal": sample_goal,
        "done_when": "Exact candidate effect and QML Gate pass; host apply remains separate.",
        "allowed_green_tools": list(contract.ALLOWED_GREEN_TOOLS),
        "max_steps": 24,
        "max_model_calls": 3,
        "max_candidate_writes": 3,
        "max_candidate_bytes": contract.TARGET_MAX_BYTES,
        "network_authority": "NONE",
        "general_action_authority": "NONE",
        "host_write_authority": contract.HOST_WRITE_AUTHORITY,
        "git_mutation_authority": "NONE",
        "shell_authority": "NONE",
        "self_authorization": "FORBIDDEN",
        "authority_file_mutation": "FORBIDDEN",
        "model_output_authority": "UNTRUSTED_MODEL_OUTPUT",
        "candidate_workspace": "RUNTIME_TASK_BOUND",
        "session_bound": True,
        "replay_protection": "RUNTIME_SINGLE_USE_RECEIPT",
        "monotonic_step_sequence": True,
        "persistent_apply_boundary": contract.PERSISTENT_APPLY_BOUNDARY,
        "test_mode": "INTENTIONAL_FIRST_GATE_FAILURE",
    }
    contract.validate_grant(sample_grant)
    context = cognition.make_task_context(sample_grant, stack=stack)
    trace = cognition.trace_action(
        context["goal_chain"],
        context["envelope"],
        context["actions"]["candidate-patch"],
        stack=stack,
    )
    if (
        not isinstance(trace, tuple)
        or not trace
        or trace[-1] != context["actions"]["candidate-patch"]
    ):
        raise AutonomyControllerError("SELFTEST_WHY_TRACE_INVALID")

    print("AUTONOMY_CONTROLLER_SELFTEST=PASS")
    print("MUST_REUSE_EXISTING_COGNITIVE_HIERARCHY=YES")
    print("PARALLEL_AGENT_BRAIN=NO")
    print("FLAT_MODEL_COMMAND_LOOP=NO")
    print("MODEL_OUTPUT=UNTRUSTED_MODEL_OUTPUT")
    print("STATE_REVALIDATION_BEFORE_ACTION=YES")
    print("CANDIDATE_WORKSPACE=TASK_BOUND")
    print("HOST_REPO_WRITE=SEPARATE_BOUNDARY")
    print("SELF_AUTHORIZATION=NO")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    print("MODEL_INFERENCE=NO")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        return selftest()
    if len(args) == 3 and args[0] == "--execute":
        return execute(args[1], args[2])
    if len(args) == 2 and args[0] == "--verify-host":
        return verify_host(args[1])
    print(
        "usage: autonomy_controller.py [--execute TASK_ROOT REQUEST | --verify-host TASK_ROOT]",
        file=sys.stderr,
    )
    return 64


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        print("AUTONOMY_CONTROLLER=STOP", file=sys.stderr)
        print(
            "STOP_REASON=" + type(exc).__name__ + ":" + str(exc),
            file=sys.stderr,
        )
        raise SystemExit(1)
