#!/usr/bin/env python3
"""Strict contract for GG Workbench Limited PATCH/WRITE Authority v1."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REQUEST_SCHEMA = "gg.workbench.write-request.v1"
RESPONSE_SCHEMA = "gg.workbench.write-response.v1"
PROPOSAL_SCHEMA = "gg.workbench.write-proposal.v1"

AUTHORITY = "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1"
EFFECT_CLASS = "BOUNDED_SINGLE_FILE_WRITE"
NETWORK_AUTHORITY = "NONE"
GENERAL_ACTION_AUTHORITY = "NONE"
MODEL_AUTONOMOUS_WRITE_INVOCATION = "DISABLED_V1"

TARGET_CONTEXT_REFERENCE = "@current"
TARGET_WORKSPACE_OBJECT_ID = "ws.file.context-composer"
TARGET_RELATIVE_PATH = "qml/components/ContextComposer.qml"
TARGET_MAX_BYTES = 16384
PATCH_TEXT_MAX_CHARS = 512

ACTION_PROPOSE = "PROPOSE"
ACTION_APPROVE = "APPROVE"
ACTION_REJECT = "REJECT"
ACTION_ROLLBACK = "ROLLBACK"
ACTIONS = frozenset((ACTION_PROPOSE, ACTION_APPROVE, ACTION_REJECT, ACTION_ROLLBACK))

REQUEST_ID_RE = re.compile(r"^write-[0-9a-f]{32}$")
PROPOSAL_ID_RE = re.compile(r"^proposal-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _exact_dict(value: Any, fields: frozenset[str], message: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(message)
    return value


def _sha_text(value: Any, message: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(message)
    return value


def validate_request(value: Any) -> dict[str, Any]:
    request = _exact_dict(
        value,
        frozenset(
            (
                "schema",
                "request_id",
                "action",
                "proposal_id",
                "context_reference",
                "workspace_object_id",
                "arguments",
            )
        ),
        "write request fields invalid",
    )

    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("write request schema invalid")

    request_id = request["request_id"]
    if not isinstance(request_id, str) or REQUEST_ID_RE.fullmatch(request_id) is None:
        raise ValueError("write request id invalid")

    proposal_id = request["proposal_id"]
    if not isinstance(proposal_id, str) or PROPOSAL_ID_RE.fullmatch(proposal_id) is None:
        raise ValueError("write proposal id invalid")

    if request["context_reference"] != TARGET_CONTEXT_REFERENCE:
        raise ValueError("write context reference invalid")
    if request["workspace_object_id"] != TARGET_WORKSPACE_OBJECT_ID:
        raise ValueError("write Workspace object invalid")

    action = request["action"]
    if action not in ACTIONS:
        raise ValueError("write action unsupported")

    arguments = request["arguments"]

    if action == ACTION_PROPOSE:
        arguments = _exact_dict(
            arguments,
            frozenset(("old_text", "new_text")),
            "write proposal arguments invalid",
        )
        old_text = arguments["old_text"]
        new_text = arguments["new_text"]

        for label, item in (("old", old_text), ("new", new_text)):
            if not isinstance(item, str):
                raise ValueError("write " + label + " text invalid")
            if "\x00" in item:
                raise ValueError("write " + label + " text contains NUL")
            if len(item) > PATCH_TEXT_MAX_CHARS:
                raise ValueError("write " + label + " text too large")

        if not old_text:
            raise ValueError("write old text must be nonempty")
        if not new_text:
            raise ValueError("write new text must be nonempty")
        if old_text == new_text:
            raise ValueError("write patch must change content")

    elif action in (ACTION_APPROVE, ACTION_REJECT):
        arguments = _exact_dict(
            arguments,
            frozenset(("candidate_sha256",)),
            "write approval arguments invalid",
        )
        _sha_text(arguments["candidate_sha256"], "candidate sha invalid")

    else:
        arguments = _exact_dict(
            arguments,
            frozenset(("candidate_sha256", "before_sha256")),
            "write rollback arguments invalid",
        )
        _sha_text(arguments["candidate_sha256"], "candidate sha invalid")
        _sha_text(arguments["before_sha256"], "before sha invalid")

    return json.loads(json.dumps(request))


def validate_response(
    value: Any,
    request_id: str,
    action: str,
    proposal_id: str,
) -> dict[str, Any]:
    response = _exact_dict(
        value,
        frozenset(
            (
                "schema",
                "request_id",
                "action",
                "proposal_id",
                "status",
                "output",
                "evidence",
            )
        ),
        "write response fields invalid",
    )

    if response["schema"] != RESPONSE_SCHEMA:
        raise ValueError("write response schema invalid")
    if response["request_id"] != request_id:
        raise ValueError("write response request id mismatch")
    if response["action"] != action:
        raise ValueError("write response action mismatch")
    if response["proposal_id"] != proposal_id:
        raise ValueError("write response proposal id mismatch")
    if response["status"] not in (
        "WAITING_APPROVAL",
        "APPLIED_VERIFIED",
        "REJECTED_NO_WRITE",
        "ROLLED_BACK_VERIFIED",
        "BLOCKED",
    ):
        raise ValueError("write response status invalid")

    output = response["output"]
    if not isinstance(output, str) or len(output.encode("utf-8")) > 65536:
        raise ValueError("write response output invalid")

    evidence = _exact_dict(
        response["evidence"],
        frozenset(
            (
                "authority",
                "effect_class",
                "network_authority",
                "general_action_authority",
                "model_autonomous_write_invocation",
                "target_relative_path",
                "before_sha256",
                "candidate_sha256",
                "output_sha256",
                "gate_status",
            )
        ),
        "write response evidence invalid",
    )

    constants = {
        "authority": AUTHORITY,
        "effect_class": EFFECT_CLASS,
        "network_authority": NETWORK_AUTHORITY,
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "model_autonomous_write_invocation": MODEL_AUTONOMOUS_WRITE_INVOCATION,
        "target_relative_path": TARGET_RELATIVE_PATH,
    }
    for key, expected in constants.items():
        if evidence[key] != expected:
            raise ValueError("write response evidence mismatch: " + key)

    _sha_text(evidence["before_sha256"], "write response before sha invalid")
    _sha_text(evidence["candidate_sha256"], "write response candidate sha invalid")
    _sha_text(evidence["output_sha256"], "write response output sha invalid")

    if evidence["output_sha256"] != hashlib.sha256(
        output.encode("utf-8")
    ).hexdigest():
        raise ValueError("write response output sha mismatch")

    if evidence["gate_status"] not in ("PASS", "NOT_RUN"):
        raise ValueError("write response gate status invalid")

    return json.loads(json.dumps(response))


def canonical_request_json(value: Any) -> str:
    return json.dumps(
        validate_request(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_response_json(
    value: Any,
    request_id: str,
    action: str,
    proposal_id: str,
) -> str:
    return json.dumps(
        validate_response(value, request_id, action, proposal_id),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


if __name__ == "__main__":
    probe = validate_request(
        {
            "schema": REQUEST_SCHEMA,
            "request_id": "write-" + ("a" * 32),
            "action": ACTION_PROPOSE,
            "proposal_id": "proposal-" + ("b" * 32),
            "context_reference": TARGET_CONTEXT_REFERENCE,
            "workspace_object_id": TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {
                "old_text": "implicitHeight: 92",
                "new_text": "implicitHeight: 93",
            },
        }
    )
    print(canonical_request_json(probe))
    print("WRITE_CONTRACT_SELFTEST=PASS")
