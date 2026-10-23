#!/usr/bin/env python3
"""Strict typed contract for GG Workbench Safe Tools v1."""

from __future__ import annotations

import json
import re
from typing import Any

REQUEST_SCHEMA = "gg.workbench.safe-tool-request.v1"
RESPONSE_SCHEMA = "gg.workbench.safe-tool-response.v1"
AUTHORITY = "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1"

PROFILE_READ = "READ"
PROFILE_SEARCH = "SEARCH"
PROFILE_GIT = "GIT"
PROFILE_TEST = "TEST"
PROFILE_RUN = "RUN"

PROFILES = frozenset(
    (
        PROFILE_READ,
        PROFILE_SEARCH,
        PROFILE_GIT,
        PROFILE_TEST,
        PROFILE_RUN,
    )
)

GIT_OPERATIONS = frozenset(("status", "diff", "log", "show-head"))
REQUEST_ID_RE = re.compile(r"^tool-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _exact_dict(
    value: Any,
    fields: frozenset[str],
    message: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(message)
    return value


def validate_request(value: Any) -> dict[str, Any]:
    request = _exact_dict(
        value,
        frozenset(("schema", "request_id", "profile", "arguments")),
        "safe tool request fields invalid",
    )

    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("safe tool request schema invalid")

    request_id = request["request_id"]
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("safe tool request id invalid")

    profile = request["profile"]
    if profile not in PROFILES:
        raise ValueError("safe tool profile unsupported")

    args = request["arguments"]

    if profile == PROFILE_READ:
        args = _exact_dict(
            args,
            frozenset(("path",)),
            "READ arguments invalid",
        )
        path = args["path"]
        if not isinstance(path, str) or not (1 <= len(path) <= 240):
            raise ValueError("READ path invalid")
        if "\x00" in path or "\n" in path or "\r" in path:
            raise ValueError("READ path contains forbidden characters")

    elif profile == PROFILE_SEARCH:
        args = _exact_dict(
            args,
            frozenset(("literal",)),
            "SEARCH arguments invalid",
        )
        literal = args["literal"]
        if not isinstance(literal, str) or not (1 <= len(literal) <= 128):
            raise ValueError("SEARCH literal invalid")
        if "\x00" in literal or "\n" in literal or "\r" in literal:
            raise ValueError("SEARCH literal contains forbidden characters")

    elif profile == PROFILE_GIT:
        args = _exact_dict(
            args,
            frozenset(("operation",)),
            "GIT arguments invalid",
        )
        if args["operation"] not in GIT_OPERATIONS:
            raise ValueError("GIT operation unsupported")

    else:
        _exact_dict(
            args,
            frozenset(),
            profile + " arguments must be empty",
        )

    return json.loads(json.dumps(request))


def validate_response(
    value: Any,
    request_id: str,
    profile: str,
) -> dict[str, Any]:
    response = _exact_dict(
        value,
        frozenset(
            (
                "schema",
                "request_id",
                "status",
                "profile",
                "output",
                "evidence",
            )
        ),
        "safe tool response fields invalid",
    )

    if response["schema"] != RESPONSE_SCHEMA:
        raise ValueError("safe tool response schema invalid")
    if response["request_id"] != request_id:
        raise ValueError("safe tool response request id mismatch")
    if response["profile"] != profile:
        raise ValueError("safe tool response profile mismatch")
    if response["status"] not in ("PASS", "BLOCK", "ERROR"):
        raise ValueError("safe tool response status invalid")

    output = response["output"]
    if not isinstance(output, str) or len(output.encode("utf-8")) > 32768:
        raise ValueError("safe tool response output invalid")

    evidence = _exact_dict(
        response["evidence"],
        frozenset(
            (
                "authority",
                "effect_class",
                "network_authority",
                "persistent_write_authority",
                "backend",
                "output_sha256",
            )
        ),
        "safe tool response evidence invalid",
    )

    if evidence["authority"] != AUTHORITY:
        raise ValueError("safe tool authority mismatch")
    if evidence["effect_class"] != "READ_ONLY":
        raise ValueError("safe tool effect class mismatch")
    if evidence["network_authority"] != "NONE":
        raise ValueError("safe tool network authority mismatch")
    if evidence["persistent_write_authority"] != "NONE":
        raise ValueError("safe tool write authority mismatch")

    if evidence["backend"] not in (
        "IN_PROCESS_TRACKED_READ",
        "IN_PROCESS_TRACKED_LITERAL_SEARCH",
        "HOST_GIT_FIXED_ARGV",
        "PODMAN_LOCKED_READONLY_SANDBOX",
    ):
        raise ValueError("safe tool backend invalid")

    digest = evidence["output_sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError("safe tool output sha invalid")

    return json.loads(json.dumps(response))


def canonical_request_json(value: Any) -> str:
    request = validate_request(value)
    return json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_response_json(
    value: Any,
    request_id: str,
    profile: str,
) -> str:
    response = validate_response(value, request_id, profile)
    return json.dumps(
        response,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


if __name__ == "__main__":
    probe = validate_request(
        {
            "schema": REQUEST_SCHEMA,
            "request_id": "tool-" + ("a" * 32),
            "profile": PROFILE_GIT,
            "arguments": {"operation": "status"},
        }
    )
    print(canonical_request_json(probe))
    print("SAFE_TOOL_CONTRACT_SELFTEST=PASS")
