from __future__ import annotations

from backend.platform_files import (
    secure_open,
)
from backend.platform_support import (
    private_runtime_root,
)


import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from backend import action_effect_observer
from backend import action_done_when
from backend import action_effect_recovery
from backend import action_execution_eligibility
from backend import safe_tool_contract as tool_contract


def submit_eligible_tool(
    self,
    pending_id,
    pending,
    context_reference,
    workspace_object_id,
    *,
    project,
    qprocess_type,
    safe_tool_runner_path,
    resolve_workspace_context_fn,
):
    if pending.get("status") != "APPROVED_VALID":
        raise RuntimeError("D68_PENDING_NOT_APPROVED_VALID")

    if pending.get("execution_state") != "UNUSED":
        raise RuntimeError(
            "D68_REPLAY_BLOCKED:"
            + str(pending.get("execution_state"))
        )

    if self._process is not None:
        pending["status"] = "BLOCKED_EXECUTION_BUSY"
        raise RuntimeError("D68_PROCESS_SLOT_BUSY")

    raw_eligibility = pending.get("execution_eligibility")

    if not isinstance(raw_eligibility, dict):
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_ELIGIBILITY_MISSING")

    eligibility = (
        action_execution_eligibility
        .validate_execution_eligibility(
            copy.deepcopy(raw_eligibility)
        )
    )

    if (
        eligibility.get("result") != "EXECUTION_ELIGIBLE"
        or eligibility.get("reason_code")
        != "EXACT_SAFE_TOOL_READ_REFINEMENT"
        or eligibility.get("capability_human_id")
        != "tool.safe.dispatch"
        or eligibility.get("safe_tool_profile")
        != tool_contract.PROFILE_READ
        or eligibility.get("action_authority") != "NONE"
        or eligibility.get("general_action_authority")
        != "NONE"
        or eligibility.get("capability_execution") is not False
        or eligibility.get("k7_l_execution") is not False
        or eligibility.get("participant_execution") is not False
        or eligibility.get(
            "execution_persistent_write_authority"
        )
        != "NONE"
        or eligibility.get("network") != "NONE"
        or eligibility.get("sudo") != "NO"
        or eligibility.get("model_inference") is not False
    ):
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_ELIGIBILITY_CONTRACT_FAILED")

    raw_request = eligibility.get("safe_tool_request")

    if not isinstance(raw_request, dict):
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_SAFE_TOOL_REQUEST_MISSING")

    request = tool_contract.validate_request(
        copy.deepcopy(raw_request)
    )

    if request["profile"] != tool_contract.PROFILE_READ:
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_SAFE_TOOL_PROFILE_NOT_READ")

    request_sha256 = hashlib.sha256(
        tool_contract.canonical_request_json(
            request
        ).encode("utf-8")
    ).hexdigest()

    if (
        request_sha256
        != eligibility.get("safe_tool_request_sha256")
    ):
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_SAFE_TOOL_REQUEST_SHA_MISMATCH")

    action_intent = pending.get("action_intent")

    if not isinstance(action_intent, dict):
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_ACTION_INTENT_MISSING")

    workspace = resolve_workspace_context_fn(
        workspace_object_id
    )

    safe_tool_relative = str(
        request["arguments"]["path"]
    )

    safe_tool_prefix = "projects/gg-ai-desktop/"

    if not safe_tool_relative.startswith(
        safe_tool_prefix
    ):
        pending["status"] = "BLOCKED_EXECUTION_STALE"
        raise RuntimeError(
            "D68_SAFE_TOOL_REPO_PATH_INVALID"
        )

    workspace_relative = safe_tool_relative[
        len(safe_tool_prefix):
    ]

    if workspace_relative != workspace.get("source_path"):
        pending["status"] = "BLOCKED_EXECUTION_STALE"
        raise RuntimeError("D68_TARGET_PATH_DRIFT")

    current_target_sha256 = str(
        workspace.get("sha256", "")
    )

    if (
        current_target_sha256
        != action_intent.get("target_source_revision")
    ):
        pending["status"] = "BLOCKED_EXECUTION_STALE"
        raise RuntimeError("D68_TARGET_REVISION_DRIFT")

    current_manifest_sha256 = hashlib.sha256(
        (project / "SOURCE-MANIFEST.json").read_bytes()
    ).hexdigest()

    if (
        current_manifest_sha256
        != pending.get("manifest_sha256")
    ):
        pending["status"] = "BLOCKED_EXECUTION_STALE"
        raise RuntimeError("D68_MANIFEST_REVISION_DRIFT")

    eligibility_binding = eligibility.get(
        "eligibility_binding_sha256"
    )

    if (
        not isinstance(eligibility_binding, str)
        or len(eligibility_binding) != 64
        or any(
            char not in "0123456789abcdef"
            for char in eligibility_binding
        )
    ):
        pending["status"] = "BLOCKED_EXECUTION"
        raise RuntimeError("D68_ELIGIBILITY_BINDING_INVALID")

    runtime_root = private_runtime_root()

    nonce = uuid.uuid4().hex[:24]

    evidence = runtime_root / f"gg-safe-tool.{nonce}"

    request_path = runtime_root / (
        f"gg-workbench-tool-request.{nonce}.json"
    )

    evidence.mkdir(
        mode=0o700,
        exist_ok=False,
    )

    request_bytes = (
        tool_contract.canonical_request_json(request)
        + "\n"
    ).encode("utf-8")

    try:
        fd = secure_open(
            request_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        with os.fdopen(fd, "wb") as handle:
            handle.write(request_bytes)
            handle.flush()
            os.fsync(handle.fileno())

    except Exception:
        try:
            request_path.unlink()
        except OSError:
            pass

        try:
            evidence.rmdir()
        except OSError:
            pass

        raise

    process = qprocess_type(self)

    process.setProgram(
        sys.executable
    )

    process.setArguments(
        [
            "-B",
            str(safe_tool_runner_path),
            "--execute-tool",
            str(evidence),
            str(request_path),
        ]
    )

    process.setProcessChannelMode(
        qprocess_type.ProcessChannelMode.SeparateChannels
    )

    pending["execution_state"] = "DISPATCHED"
    pending["status"] = "EXECUTION_RUNNING"
    pending["execution_receipt"] = None
    pending["execution_eligibility_binding_sha256"] = (
        eligibility_binding
    )
    pending["execution_safe_tool_request_sha256"] = (
        request_sha256
    )
    pending["execution_evidence_path"] = str(
        evidence
    )

    self._state = {
        "kind": "mandated_tool",
        "pending_id": pending_id,
        "request_id": str(request["request_id"]),
        "profile": str(request["profile"]),
        "context": context_reference,
        "workspace": workspace_object_id,
        "evidence": str(evidence),
        "request_path": str(request_path),
        "eligibility_binding_sha256": eligibility_binding,
        "safe_tool_request_sha256": request_sha256,
        "stoppable": "1",
    }

    self._process = process

    self._set_bridge_activity(
        True,
        str(request["request_id"]),
    )

    process.finished.connect(
        self._eligible_tool_finished
    )

    process.start()

    if not process.waitForStarted(5000):
        reason = process.errorString()

        pending["execution_state"] = "CONSUMED_START_FAILED"
        pending["status"] = "EXECUTION_START_FAILED"
        pending["execution_receipt"] = {
            "schema": "gg.action-execution-result.v1",
            "result": "ACTION_NOT_EXECUTED",
            "reason_code": "SAFE_TOOL_PROCESS_START_FAILED",
            "eligibility_binding_sha256": eligibility_binding,
            "safe_tool_request_sha256": request_sha256,
            "request_id": str(request["request_id"]),
            "profile": str(request["profile"]),
            "action_executed": False,
            "actual_effect_verified": False,
            "network": "NONE",
            "sudo": "NO",
            "model_inference": False,
        }

        try:
            request_path.unlink()
        except OSError:
            pass

        try:
            evidence.rmdir()
        except OSError:
            pass

        process.deleteLater()
        self._process = None
        self._state = None

        self._set_bridge_activity(
            False,
            "",
        )

        self._append(
            "GG SYSTEM",
            "ACTION",
            (
                "D68 Safe Tool kunde inte starta: "
                + reason
                + "\nMandatet är konsumerat; "
                "ingen automatisk rerun."
            ),
            context_reference + " · " + workspace_object_id,
            "FAIL",
            28,
        )
        return

    self._append(
        "GG ACTION",
        "D68 EXECUTING",
        (
            "Exact D67-staged Safe Tool READ kör.\n"
            "REQUEST_ID: "
            + str(request["request_id"])
            + "\nELIGIBILITY_BINDING_SHA256: "
            + eligibility_binding
            + "\nREPLAY_STATE: DISPATCHED\n"
            "NETWORK: NONE\n"
            "SUDO: NO\n"
            "MODEL_INFERENCE: NONE\n"
            "D69 ACTUAL EFFECT VERIFICATION: NOT YET"
        ),
        context_reference + " · " + workspace_object_id,
        "RUNNING",
        28,
    )


def eligible_tool_finished(
    self,
    exit_code,
    _exit_status,
    *,
    resolve_workspace_context_fn,
):
    process = self._process
    state = self._state

    if (
        process is None
        or state is None
        or state.get("kind") != "mandated_tool"
    ):
        return

    stderr = bytes(
        process.readAllStandardError()
    ).decode(
        "utf-8",
        errors="replace",
    )

    evidence = Path(
        str(state["evidence"])
    )
    request_path = Path(
        str(state["request_path"])
    )
    request_id = str(
        state["request_id"]
    )
    profile = str(
        state["profile"]
    )
    context = str(
        state["context"]
    )
    workspace = str(
        state["workspace"]
    )
    pending_id = str(
        state["pending_id"]
    )

    pending = self._pending_mandates.get(
        pending_id
    )

    try:
        if pending is None:
            raise RuntimeError(
                "D68_PENDING_STATE_LOST"
            )

        if state.get("stop_requested") == "1":
            pending["execution_state"] = "CONSUMED_STOPPED"
            pending["status"] = "EXECUTION_STOPPED"
            pending["execution_receipt"] = {
                "schema": "gg.action-execution-result.v1",
                "result": "ACTION_STOPPED",
                "reason_code": "USER_STOP",
                "eligibility_binding_sha256": str(
                    state["eligibility_binding_sha256"]
                ),
                "safe_tool_request_sha256": str(
                    state["safe_tool_request_sha256"]
                ),
                "request_id": request_id,
                "profile": profile,
                "action_executed": False,
                "actual_effect_verified": False,
                "network": "NONE",
                "sudo": "NO",
                "model_inference": False,
            }

            self._mark_stopped(
                state
            )
            return

        if exit_code != 0:
            reason = ""

            failure_path = (
                evidence
                / "runner-failure.json"
            )

            if (
                failure_path.is_file()
                and not failure_path.is_symlink()
            ):
                try:
                    failure = json.loads(
                        failure_path.read_text(
                            encoding="utf-8"
                        )
                    )
                    reason = str(
                        failure.get("reason", "")
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ):
                    pass

            if not reason:
                lines = [
                    line.strip()
                    for line in stderr.splitlines()
                    if line.strip()
                ]

                reason = (
                    lines[-1]
                    if lines
                    else (
                        "safe tool exit code "
                        + str(exit_code)
                    )
                )

            pending["execution_state"] = "CONSUMED_FAILED"
            pending["status"] = "EXECUTION_FAILED"
            pending["execution_receipt"] = {
                "schema": "gg.action-execution-result.v1",
                "result": "ACTION_EXECUTION_FAILED",
                "reason_code": reason,
                "eligibility_binding_sha256": str(
                    state["eligibility_binding_sha256"]
                ),
                "safe_tool_request_sha256": str(
                    state["safe_tool_request_sha256"]
                ),
                "request_id": request_id,
                "profile": profile,
                "action_executed": False,
                "actual_effect_verified": False,
                "network": "NONE",
                "sudo": "NO",
                "model_inference": False,
            }

            self._append(
                "GG SYSTEM",
                "ACTION",
                (
                    "D68 Safe Tool stoppade säkert: "
                    + reason
                    + "\nMandatet är konsumerat; "
                    "ingen automatisk rerun."
                ),
                context + " · " + workspace,
                "FAIL",
                28,
            )
            return

        request_evidence_path = (
            evidence / "request.json"
        )
        response_path = (
            evidence / "response.json"
        )

        if (
            not request_evidence_path.is_file()
            or request_evidence_path.is_symlink()
        ):
            raise RuntimeError(
                "D68 evidence request.json missing"
            )

        if (
            not response_path.is_file()
            or response_path.is_symlink()
        ):
            raise RuntimeError(
                "D68 PASS without response.json"
            )

        evidence_request = (
            tool_contract.validate_request(
                json.loads(
                    request_evidence_path.read_text(
                        encoding="utf-8"
                    )
                )
            )
        )

        evidence_request_sha256 = hashlib.sha256(
            tool_contract.canonical_request_json(
                evidence_request
            ).encode("utf-8")
        ).hexdigest()

        if (
            evidence_request_sha256
            != state.get("safe_tool_request_sha256")
        ):
            raise RuntimeError(
                "D68 runtime request evidence drift"
            )

        raw_eligibility = pending.get(
            "execution_eligibility"
        )

        if not isinstance(raw_eligibility, dict):
            raise RuntimeError(
                "D68 eligibility state lost"
            )

        eligibility = (
            action_execution_eligibility
            .validate_execution_eligibility(
                copy.deepcopy(
                    raw_eligibility
                )
            )
        )

        if (
            eligibility.get(
                "eligibility_binding_sha256"
            )
            != state.get(
                "eligibility_binding_sha256"
            )
        ):
            raise RuntimeError(
                "D68 eligibility binding drift"
            )

        response = json.loads(
            response_path.read_text(
                encoding="utf-8"
            )
        )

        validated = (
            tool_contract.validate_response(
                response,
                request_id,
                profile,
            )
        )

        if validated["status"] != "PASS":
            raise RuntimeError(
                "D68 Safe Tool response not PASS"
            )

        canonical_response = (
            tool_contract.canonical_response_json(
                validated,
                request_id,
                profile,
            )
        )

        response_sha256 = hashlib.sha256(
            canonical_response.encode(
                "utf-8"
            )
        ).hexdigest()

        observation = action_effect_observer.observe_safe_tool_read_effect(
            action_intent=copy.deepcopy(
                pending.get("action_intent")
            ),
            execution_eligibility=copy.deepcopy(
                eligibility
            ),
            validated_response=copy.deepcopy(
                validated
            ),
            workspace_object_id=str(
                state["workspace"]
            ),
            resolve_workspace_context_fn=(
                resolve_workspace_context_fn
            ),
        )
        pending["actual_effect_observation"] = (
            copy.deepcopy(observation)
        )

        receipt = {
            "schema": "gg.action-execution-result.v1",
            "result": "ACTION_EXECUTED",
            "reason_code": "SAFE_TOOL_RESPONSE_PASS",
            "eligibility_binding_sha256": str(
                state["eligibility_binding_sha256"]
            ),
            "safe_tool_request_sha256": str(
                state["safe_tool_request_sha256"]
            ),
            "request_id": request_id,
            "profile": profile,
            "evidence_path": str(evidence),
            "response_sha256": response_sha256,
            "output_sha256": str(
                validated["evidence"]["output_sha256"]
            ),
            "backend": str(
                validated["evidence"]["backend"]
            ),
            "action_executed": True,
            "actual_effect_verified": bool(observation["actual_effect_verified"]),
            "network": "NONE",
            "sudo": "NO",
            "model_inference": False,
        }

        pending["execution_state"] = "CONSUMED_PASS"
        pending["status"] = "ACTION_EXECUTED"
        pending["execution_receipt"] = (
            copy.deepcopy(receipt)
        )

        recovery = (
            action_effect_recovery
            .classify_action_effect_recovery(
                action_intent=copy.deepcopy(
                    pending.get("action_intent")
                ),
                execution_eligibility=copy.deepcopy(
                    eligibility
                ),
                actual_effect_observation=copy.deepcopy(
                    observation
                ),
                execution_state=str(
                    pending["execution_state"]
                ),
            )
        )
        pending["action_effect_recovery"] = (
            copy.deepcopy(recovery)
        )

        completion = (
            action_done_when
            .evaluate_action_done_when(
                action_intent=copy.deepcopy(
                    pending.get("action_intent")
                ),
                evaluation_context=copy.deepcopy(
                    pending.get("evaluation_context")
                ),
                execution_receipt=copy.deepcopy(
                    receipt
                ),
                actual_effect_observation=copy.deepcopy(
                    observation
                ),
                action_effect_recovery=copy.deepcopy(
                    recovery
                ),
                semantic_evidence=None,
            )
        )

        pending["action_done_when"] = (
            copy.deepcopy(completion)
        )

        output = str(
            validated["output"]
        ).strip()

        if not output:
            output = (
                "(empty read-only result)"
            )

        self._append(
            "GG TOOL",
            profile,
            output,
            (
                context
                + " · "
                + workspace
                + " · "
                + tool_contract.AUTHORITY
            ),
            "PASS",
            28,
        )

        self._append(
            "GG ACTION",
            "D68 ACTION EXECUTED",
            (
                "ACTION_EXECUTED: PASS\n"
                "REQUEST_ID: "
                + request_id
                + "\nREPLAY_STATE: CONSUMED_PASS\n"
                "SAFE_TOOL_BACKEND: "
                + str(
                    validated["evidence"]["backend"]
                )
                + "\nNETWORK: NONE\n"
                "SUDO: NO\n"
                "MODEL_INFERENCE: NONE\n"
                "D69 LOCAL OBSERVER: APPLIED\n"
                "D70 ROUTING: "
                + str(recovery["result"])
                + "\nD70 AUTHORITY REEVALUATION REQUIRED: "
                + (
                    "YES"
                    if recovery[
                        "authority_reevaluation_required"
                    ]
                    else "NO"
                )
            ),
            context + " · " + workspace,
            "PASS",
            28,
        )

    except Exception as exc:
        if pending is not None:
            if (
                pending.get("execution_state")
                != "CONSUMED_PASS"
            ):
                pending["execution_state"] = "CONSUMED_FAILED"
                pending["status"] = "EXECUTION_FAILED"
                pending["execution_receipt"] = {
                    "schema": "gg.action-execution-result.v1",
                    "result": "ACTION_EXECUTION_FAILED",
                    "reason_code": (
                        type(exc).__name__
                        + ":"
                        + str(exc)
                    ),
                    "eligibility_binding_sha256": str(
                        state.get(
                            "eligibility_binding_sha256",
                            "",
                        )
                    ),
                    "safe_tool_request_sha256": str(
                        state.get(
                            "safe_tool_request_sha256",
                            "",
                        )
                    ),
                    "request_id": request_id,
                    "profile": profile,
                    "action_executed": False,
                    "actual_effect_verified": False,
                    "network": "NONE",
                    "sudo": "NO",
                    "model_inference": False,
                }

        self._append(
            "GG SYSTEM",
            "ACTION",
            (
                "D68 response validation failed: "
                + type(exc).__name__
                + ":"
                + str(exc)
            ),
            context + " · " + workspace,
            "FAIL",
            28,
        )

    finally:
        try:
            request_path.unlink()
        except OSError:
            pass

        process.deleteLater()
        self._process = None
        self._state = None
        self._set_bridge_activity(
            False,
            "",
        )
