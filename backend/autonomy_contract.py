#!/usr/bin/env python3
"""Closed contract for GG Workbench Autonomy Bootstrap v1.

This contract does not grant general action authority. It binds one task to the
already verified @current ContextComposer target, a session-local candidate
workspace, fixed GREEN tools, bounded model calls, and the existing separate
Limited Write host-apply boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

GRANT_SCHEMA = "gg.workbench.autonomy-grant.v1"
REQUEST_SCHEMA = "gg.workbench.autonomy-request.v1"
SEMANTIC_PROPOSAL_SCHEMA = "gg.workbench.autonomy-semantic-proposal.v1"
CHANGESET_SCHEMA = "gg.workbench.autonomy-changeset.v1"
RESULT_SCHEMA = "gg.workbench.autonomy-result.v1"
HOST_VERIFY_SCHEMA = "gg.workbench.autonomy-host-verify.v1"

AUTHORITY = "YELLOW_LOCAL_TASK_BOUND_CANDIDATE_V1"
NETWORK_AUTHORITY = "NONE"
GENERAL_ACTION_AUTHORITY = "NONE"
HOST_WRITE_AUTHORITY = "NONE_BEFORE_SEPARATE_APPROVAL"
GIT_MUTATION_AUTHORITY = "NONE"
SHELL_AUTHORITY = "NONE"
SELF_AUTHORIZATION = "FORBIDDEN"
AUTHORITY_FILE_MUTATION = "FORBIDDEN"
MODEL_OUTPUT_AUTHORITY = "UNTRUSTED_MODEL_OUTPUT"
PERSISTENT_APPLY_BOUNDARY = "EXISTING_LIMITED_WRITE_PROPOSAL_APPROVAL"

TARGET_CONTEXT_REFERENCE = "@current"
TARGET_WORKSPACE_OBJECT_ID = "ws.file.context-composer"
TARGET_RELATIVE_PATH = "qml/components/ContextComposer.qml"
TARGET_MAX_BYTES = 16384

ALLOWED_GREEN_TOOLS = ("READ", "SEARCH", "GIT", "TEST", "RUN")
TEST_MODES = ("NONE", "INTENTIONAL_FIRST_GATE_FAILURE")

TASK_ID_RE = re.compile(r"^task-[0-9a-f]{32}$")
SESSION_ID_RE = re.compile(r"^session-[0-9a-f]{32}$")
REQUEST_ID_RE = re.compile(r"^autonomy-[0-9a-f]{32}$")
PROPOSAL_ID_RE = re.compile(r"^proposal-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HEAD_RE = re.compile(r"^[0-9a-f]{40,64}$")


def _dict(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != fields:
        raise ValueError(label + " fields invalid")
    return value


def _text(value: Any, label: str, limit: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(label + " text invalid")
    if "\x00" in value:
        raise ValueError(label + " contains NUL")
    return value


def _sha(value: Any, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ValueError(label + " sha256 invalid")
    return value


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


_GRANT_FIELDS = frozenset(
    (
        "schema",
        "task_id",
        "session_id",
        "base_head",
        "context_reference",
        "workspace_object_id",
        "target_relative_path",
        "goal",
        "done_when",
        "allowed_green_tools",
        "max_steps",
        "max_model_calls",
        "max_candidate_writes",
        "max_candidate_bytes",
        "network_authority",
        "general_action_authority",
        "host_write_authority",
        "git_mutation_authority",
        "shell_authority",
        "self_authorization",
        "authority_file_mutation",
        "model_output_authority",
        "candidate_workspace",
        "session_bound",
        "replay_protection",
        "monotonic_step_sequence",
        "persistent_apply_boundary",
        "test_mode",
    )
)


def validate_grant(value: Any) -> dict[str, Any]:
    grant = _dict(value, _GRANT_FIELDS, "grant")

    if grant["schema"] != GRANT_SCHEMA:
        raise ValueError("grant schema invalid")
    if type(grant["task_id"]) is not str or TASK_ID_RE.fullmatch(grant["task_id"]) is None:
        raise ValueError("grant task_id invalid")
    if type(grant["session_id"]) is not str or SESSION_ID_RE.fullmatch(grant["session_id"]) is None:
        raise ValueError("grant session_id invalid")
    if type(grant["base_head"]) is not str or HEAD_RE.fullmatch(grant["base_head"]) is None:
        raise ValueError("grant base_head invalid")

    if grant["context_reference"] != TARGET_CONTEXT_REFERENCE:
        raise ValueError("grant context invalid")
    if grant["workspace_object_id"] != TARGET_WORKSPACE_OBJECT_ID:
        raise ValueError("grant workspace invalid")
    if grant["target_relative_path"] != TARGET_RELATIVE_PATH:
        raise ValueError("grant target invalid")

    _text(grant["goal"], "grant goal", 4096)
    _text(grant["done_when"], "grant done_when", 4096)

    if grant["allowed_green_tools"] != list(ALLOWED_GREEN_TOOLS):
        raise ValueError("grant green tool set invalid")

    limits = (
        ("max_steps", 1, 32),
        ("max_model_calls", 1, 4),
        ("max_candidate_writes", 1, 8),
        ("max_candidate_bytes", 1, TARGET_MAX_BYTES),
    )
    for field, low, high in limits:
        number = grant[field]
        if type(number) is not int or not low <= number <= high:
            raise ValueError(field + " invalid")

    constants = {
        "network_authority": NETWORK_AUTHORITY,
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "host_write_authority": HOST_WRITE_AUTHORITY,
        "git_mutation_authority": GIT_MUTATION_AUTHORITY,
        "shell_authority": SHELL_AUTHORITY,
        "self_authorization": SELF_AUTHORIZATION,
        "authority_file_mutation": AUTHORITY_FILE_MUTATION,
        "model_output_authority": MODEL_OUTPUT_AUTHORITY,
        "candidate_workspace": "RUNTIME_TASK_BOUND",
        "replay_protection": "RUNTIME_SINGLE_USE_RECEIPT",
        "persistent_apply_boundary": PERSISTENT_APPLY_BOUNDARY,
    }
    for field, expected in constants.items():
        if grant[field] != expected:
            raise ValueError(field + " authority mismatch")

    if grant["session_bound"] is not True:
        raise ValueError("grant session_bound invalid")
    if grant["monotonic_step_sequence"] is not True:
        raise ValueError("grant step sequence invalid")
    if grant["test_mode"] not in TEST_MODES:
        raise ValueError("grant test_mode invalid")

    return json.loads(json.dumps(grant, ensure_ascii=False))


def grant_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(validate_grant(value))).hexdigest()


_REQUEST_FIELDS = frozenset(("schema", "request_id", "grant", "grant_sha256", "render_node"))


def validate_request(value: Any) -> dict[str, Any]:
    request = _dict(value, _REQUEST_FIELDS, "request")
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("request schema invalid")
    if type(request["request_id"]) is not str or REQUEST_ID_RE.fullmatch(request["request_id"]) is None:
        raise ValueError("request id invalid")

    grant = validate_grant(request["grant"])
    expected = grant_sha256(grant)
    if _sha(request["grant_sha256"], "request grant") != expected:
        raise ValueError("request grant binding mismatch")

    render = _text(request["render_node"], "render node", 256)
    if not render.startswith("/dev/dri/renderD"):
        raise ValueError("render node policy invalid")

    return {
        "schema": REQUEST_SCHEMA,
        "request_id": request["request_id"],
        "grant": grant,
        "grant_sha256": expected,
        "render_node": render,
    }


_SEMANTIC_FIELDS = frozenset(("schema", "hypothesis", "old_text", "new_text", "why"))


def validate_semantic_proposal(value: Any) -> dict[str, str]:
    proposal = _dict(value, _SEMANTIC_FIELDS, "semantic proposal")
    if proposal["schema"] != SEMANTIC_PROPOSAL_SCHEMA:
        raise ValueError("semantic proposal schema invalid")

    normalized: dict[str, str] = {"schema": SEMANTIC_PROPOSAL_SCHEMA}
    for field, maximum in (
        ("hypothesis", 512),
        ("old_text", 512),
        ("new_text", 512),
        ("why", 512),
    ):
        text = _text(proposal[field], field, maximum)
        if "\n" in text or "\r" in text or "|" in text:
            raise ValueError(field + " must be single-line and pipe-free")
        normalized[field] = text

    if normalized["old_text"] == normalized["new_text"]:
        raise ValueError("semantic proposal is a no-op")
    return normalized


_CHANGESET_FIELDS = frozenset(
    (
        "schema",
        "task_id",
        "base_head",
        "target_relative_path",
        "workspace_object_id",
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
        "old_text",
        "new_text",
        "qml_gate_report_sha256",
        "candidate_write_count",
        "model_call_count",
        "step_count",
        "host_repo_changed_before_approval",
    )
)


def validate_changeset(value: Any) -> dict[str, Any]:
    item = _dict(value, _CHANGESET_FIELDS, "changeset")
    if item["schema"] != CHANGESET_SCHEMA:
        raise ValueError("changeset schema invalid")
    if type(item["task_id"]) is not str or TASK_ID_RE.fullmatch(item["task_id"]) is None:
        raise ValueError("changeset task invalid")
    if type(item["base_head"]) is not str or HEAD_RE.fullmatch(item["base_head"]) is None:
        raise ValueError("changeset head invalid")
    if item["target_relative_path"] != TARGET_RELATIVE_PATH:
        raise ValueError("changeset target invalid")
    if item["workspace_object_id"] != TARGET_WORKSPACE_OBJECT_ID:
        raise ValueError("changeset workspace invalid")
    for field in ("before_sha256", "candidate_sha256", "diff_sha256", "qml_gate_report_sha256"):
        _sha(item[field], field)
    validate_semantic_proposal(
        {
            "schema": SEMANTIC_PROPOSAL_SCHEMA,
            "hypothesis": "validated changeset",
            "old_text": item["old_text"],
            "new_text": item["new_text"],
            "why": "validated changeset binding",
        }
    )
    for field in ("candidate_write_count", "model_call_count", "step_count"):
        if type(item[field]) is not int or item[field] < 0:
            raise ValueError(field + " invalid")
    if item["host_repo_changed_before_approval"] is not False:
        raise ValueError("changeset claims host repo changed before approval")
    return json.loads(json.dumps(item, ensure_ascii=False))


_RESULT_FIELDS = frozenset(
    (
        "schema",
        "status",
        "task_id",
        "grant_sha256",
        "changeset",
        "write_proposal_id",
        "write_candidate_sha256",
        "write_before_sha256",
        "write_approval_command",
        "model_output_authority",
        "network_authority",
        "general_action_authority",
        "host_write_performed",
    )
)


def validate_result(value: Any) -> dict[str, Any]:
    result = _dict(value, _RESULT_FIELDS, "result")
    if result["schema"] != RESULT_SCHEMA:
        raise ValueError("result schema invalid")
    if result["status"] != "WAITING_HOST_APPLY":
        raise ValueError("result status invalid")
    if type(result["task_id"]) is not str or TASK_ID_RE.fullmatch(result["task_id"]) is None:
        raise ValueError("result task invalid")
    _sha(result["grant_sha256"], "result grant")
    changeset = validate_changeset(result["changeset"])
    proposal_id = result["write_proposal_id"]
    if type(proposal_id) is not str or PROPOSAL_ID_RE.fullmatch(proposal_id) is None:
        raise ValueError("result proposal id invalid")
    _sha(result["write_candidate_sha256"], "result candidate")
    _sha(result["write_before_sha256"], "result before")
    _text(result["write_approval_command"], "result approval command", 2048)
    if result["model_output_authority"] != MODEL_OUTPUT_AUTHORITY:
        raise ValueError("result model authority invalid")
    if result["network_authority"] != NETWORK_AUTHORITY:
        raise ValueError("result network authority invalid")
    if result["general_action_authority"] != GENERAL_ACTION_AUTHORITY:
        raise ValueError("result general authority invalid")
    if result["host_write_performed"] is not False:
        raise ValueError("result host write invalid")
    if changeset["candidate_sha256"] != result["write_candidate_sha256"]:
        raise ValueError("result candidate binding mismatch")
    if changeset["before_sha256"] != result["write_before_sha256"]:
        raise ValueError("result before binding mismatch")
    return json.loads(json.dumps(result, ensure_ascii=False))


_HOST_VERIFY_FIELDS = frozenset(
    (
        "schema",
        "status",
        "task_id",
        "candidate_sha256",
        "actual_sha256",
        "qml_gate_report_sha256",
        "done_when_technical",
        "network_authority",
        "general_action_authority",
    )
)


def validate_host_verify(value: Any) -> dict[str, Any]:
    result = _dict(value, _HOST_VERIFY_FIELDS, "host verify")
    if result["schema"] != HOST_VERIFY_SCHEMA:
        raise ValueError("host verify schema invalid")
    if result["status"] != "DONE":
        raise ValueError("host verify status invalid")
    if type(result["task_id"]) is not str or TASK_ID_RE.fullmatch(result["task_id"]) is None:
        raise ValueError("host verify task invalid")
    for field in ("candidate_sha256", "actual_sha256", "qml_gate_report_sha256"):
        _sha(result[field], field)
    if result["candidate_sha256"] != result["actual_sha256"]:
        raise ValueError("host verify effect mismatch")
    if result["done_when_technical"] is not True:
        raise ValueError("host verify done_when invalid")
    if result["network_authority"] != NETWORK_AUTHORITY:
        raise ValueError("host verify network authority invalid")
    if result["general_action_authority"] != GENERAL_ACTION_AUTHORITY:
        raise ValueError("host verify general authority invalid")
    return json.loads(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    print("AUTONOMY_CONTRACT_SELFTEST=PASS")
    print("AUTONOMY_AUTHORITY=" + AUTHORITY)
    print("MODEL_OUTPUT_AUTHORITY=" + MODEL_OUTPUT_AUTHORITY)
    print("HOST_WRITE_AUTHORITY=" + HOST_WRITE_AUTHORITY)
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
