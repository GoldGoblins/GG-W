#!/usr/bin/env python3
"Pure fail-closed data contract for future local AI request/response transport."

from __future__ import annotations

import json
from typing import Any

REQUEST_SCHEMA = "gg.workbench.local-ai-request.v1"
RESPONSE_SCHEMA = "gg.workbench.local-ai-response.v1"

MAX_REQUEST_ID_CHARS = 128
MAX_PROMPT_CHARS = 32768
MAX_RESPONSE_TEXT_CHARS = 65536
MAX_IMAGE_ID_CHARS = 256
MAX_DURATION_MS = 900000

REQUEST_KEYS = frozenset({"schema", "request_id", "mode", "prompt"})
RESPONSE_KEYS = frozenset(
    {"schema", "request_id", "status", "text", "evidence"}
)
RESPONSE_STATUSES = frozenset({"PASS", "BLOCK", "ERROR"})
EVIDENCE_KEYS = frozenset(
    {
        "model_sha256",
        "runtime_image_id",
        "runtime_image_digest",
        "exit_code",
        "stderr_sha256",
        "duration_ms",
    }
)
REQUEST_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789._:-"
)
HEX_CHARS = frozenset("0123456789abcdef")


class ContractError(ValueError):
    "Raised when request or response data violates the contract."


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractError(label + " must be a JSON object")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(value)
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise ContractError(
            label
            + " field set mismatch; missing="
            + repr(missing)
            + "; extra="
            + repr(extra)
        )


def _require_text(
    value: Any,
    label: str,
    maximum: int,
    *,
    allow_blank: bool = False,
) -> str:
    if type(value) is not str:
        raise ContractError(label + " must be a string")
    if not value:
        raise ContractError(label + " must not be empty")
    if len(value) > maximum:
        raise ContractError(label + " exceeds maximum length")
    if not allow_blank and not value.strip():
        raise ContractError(label + " must not be blank")
    if "\x00" in value:
        raise ContractError(label + " contains NUL")
    return value


def _validate_request_id(value: Any) -> str:
    request_id = _require_text(
        value,
        "request_id",
        MAX_REQUEST_ID_CHARS,
    )
    if any(char not in REQUEST_ID_CHARS for char in request_id):
        raise ContractError("request_id contains forbidden characters")
    return request_id


def _validate_sha256(value: Any, label: str) -> str:
    digest = _require_text(value, label, 64)
    if len(digest) != 64:
        raise ContractError(label + " must contain 64 hexadecimal characters")
    if any(char not in HEX_CHARS for char in digest):
        raise ContractError(label + " must be lowercase hexadecimal")
    return digest


def _validate_evidence(value: Any) -> dict[str, Any]:
    evidence = _require_dict(value, "evidence")
    unknown = frozenset(evidence) - EVIDENCE_KEYS
    if unknown:
        raise ContractError(
            "evidence contains unknown fields: " + repr(sorted(unknown))
        )

    normalized: dict[str, Any] = {}

    for key in ("model_sha256", "stderr_sha256"):
        if key in evidence:
            normalized[key] = _validate_sha256(evidence[key], key)

    for key in ("runtime_image_id", "runtime_image_digest"):
        if key in evidence:
            normalized[key] = _require_text(
                evidence[key],
                key,
                MAX_IMAGE_ID_CHARS,
            )

    if "exit_code" in evidence:
        exit_code = evidence["exit_code"]
        if type(exit_code) is not int:
            raise ContractError("exit_code must be an integer")
        if not -255 <= exit_code <= 255:
            raise ContractError("exit_code is outside the contract range")
        normalized["exit_code"] = exit_code

    if "duration_ms" in evidence:
        duration_ms = evidence["duration_ms"]
        if type(duration_ms) is not int:
            raise ContractError("duration_ms must be an integer")
        if not 0 <= duration_ms <= MAX_DURATION_MS:
            raise ContractError("duration_ms is outside the contract range")
        normalized["duration_ms"] = duration_ms

    return normalized


def validate_request(value: Any) -> dict[str, Any]:
    request = _require_dict(value, "request")
    _require_exact_keys(request, REQUEST_KEYS, "request")

    if request["schema"] != REQUEST_SCHEMA:
        raise ContractError("request schema mismatch")

    request_id = _validate_request_id(request["request_id"])

    if request["mode"] != "CHAT":
        raise ContractError("request mode must be CHAT")

    prompt = _require_text(
        request["prompt"],
        "prompt",
        MAX_PROMPT_CHARS,
    )

    return {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "mode": "CHAT",
        "prompt": prompt,
    }


def validate_response(
    value: Any,
    expected_request_id: str,
) -> dict[str, Any]:
    response = _require_dict(value, "response")
    _require_exact_keys(response, RESPONSE_KEYS, "response")

    if response["schema"] != RESPONSE_SCHEMA:
        raise ContractError("response schema mismatch")

    request_id = _validate_request_id(response["request_id"])
    expected = _validate_request_id(expected_request_id)
    if request_id != expected:
        raise ContractError("response request_id does not match request")

    status = response["status"]
    if type(status) is not str or status not in RESPONSE_STATUSES:
        raise ContractError("response status is invalid")

    text = _require_text(
        response["text"],
        "text",
        MAX_RESPONSE_TEXT_CHARS,
    )
    evidence = _validate_evidence(response["evidence"])

    return {
        "schema": RESPONSE_SCHEMA,
        "request_id": request_id,
        "status": status,
        "text": text,
        "evidence": evidence,
    }


def canonical_request_json(value: Any) -> str:
    normalized = validate_request(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_response_json(
    value: Any,
    expected_request_id: str,
) -> str:
    normalized = validate_response(value, expected_request_id)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
