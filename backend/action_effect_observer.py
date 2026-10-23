from __future__ import annotations

import hashlib
from typing import Any, Callable


SCHEMA = "gg.action-effect-observation.v1"
RESULT_MATCH = "MATCH"
RESULT_MISMATCH = "MISMATCH"

EXPECTED_INTENT_EFFECT_CLASS = "READ_ONLY_TOOL_EXECUTION"
EXPECTED_INTENT_PERSISTENT_WRITE = "RUNTIME_ONLY"
EXPECTED_INTENT_NETWORK = "NONE"
EXPECTED_INTENT_SUDO = "NO"

OBSERVED_EFFECT_CLASS = "READ_ONLY"
OBSERVED_PERSISTENT_WRITE_AUTHORITY = "NONE"
OBSERVED_NETWORK_AUTHORITY = "NONE"
OBSERVED_BACKEND = "IN_PROCESS_TRACKED_READ"

PROJECT_REQUEST_PREFIX = "projects/gg-ai-desktop/"


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(label + "_INVALID")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(label + "_INVALID")
    return value


def _sha256_text(value: object, label: str) -> str:
    text = _text(value, label)

    if len(text) != 64:
        raise RuntimeError(label + "_INVALID")

    try:
        int(text, 16)
    except ValueError as exc:
        raise RuntimeError(label + "_INVALID") from exc

    return text


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(label + "_INVALID")
    return value


def _observation(
    *,
    mismatch_reasons: list[str],
    target_object_id: str,
    target_source_path: str,
    expected_target_source_revision: str,
    observed_target_source_revision: str,
    output_sha256: str,
    backend: str,
    observed_effect_class: str,
    observed_persistent_write_authority: str,
    observed_network_authority: str,
) -> dict[str, object]:
    matched = not mismatch_reasons

    return {
        "schema": SCHEMA,
        "result": RESULT_MATCH if matched else RESULT_MISMATCH,
        "reason_code": (
            "EXPECTED_ACTUAL_MATCH"
            if matched
            else mismatch_reasons[0]
        ),
        "actual_effect_verified": matched,
        "d70_required": not matched,
        "mismatch_reasons": list(mismatch_reasons),
        "target_object_id": target_object_id,
        "target_source_path": target_source_path,
        "expected_target_source_revision": (
            expected_target_source_revision
        ),
        "observed_target_source_revision": (
            observed_target_source_revision
        ),
        "output_sha256": output_sha256,
        "backend": backend,
        "observed_effect_class": observed_effect_class,
        "observed_persistent_write_authority": (
            observed_persistent_write_authority
        ),
        "observed_network_authority": (
            observed_network_authority
        ),
    }


def observe_safe_tool_read_effect(
    *,
    action_intent: dict[str, object],
    execution_eligibility: dict[str, object],
    validated_response: dict[str, object],
    workspace_object_id: str,
    resolve_workspace_context_fn: Callable[
        [str],
        dict[str, object],
    ],
) -> dict[str, object]:
    intent = _mapping(
        action_intent,
        "ACTION_INTENT",
    )
    eligibility = _mapping(
        execution_eligibility,
        "EXECUTION_ELIGIBILITY",
    )
    response = _mapping(
        validated_response,
        "VALIDATED_RESPONSE",
    )

    if not callable(resolve_workspace_context_fn):
        raise RuntimeError(
            "WORKSPACE_RESOLVER_INVALID"
        )

    target_object_id = _text(
        intent.get("target_object_id"),
        "TARGET_OBJECT_ID",
    )
    expected_target_revision = _sha256_text(
        intent.get("target_source_revision"),
        "TARGET_SOURCE_REVISION",
    )

    safe_request = _mapping(
        eligibility.get("safe_tool_request"),
        "SAFE_TOOL_REQUEST",
    )
    request_arguments = _mapping(
        safe_request.get("arguments"),
        "SAFE_TOOL_REQUEST_ARGUMENTS",
    )

    request_profile = _text(
        safe_request.get("profile"),
        "SAFE_TOOL_PROFILE",
    )
    request_path = _text(
        request_arguments.get("path"),
        "SAFE_TOOL_PATH",
    )

    evidence = _mapping(
        response.get("evidence"),
        "SAFE_TOOL_RESPONSE_EVIDENCE",
    )

    observed_effect_class = _text(
        evidence.get("effect_class"),
        "OBSERVED_EFFECT_CLASS",
    )
    observed_write_authority = _text(
        evidence.get("persistent_write_authority"),
        "OBSERVED_PERSISTENT_WRITE_AUTHORITY",
    )
    observed_network_authority = _text(
        evidence.get("network_authority"),
        "OBSERVED_NETWORK_AUTHORITY",
    )
    backend = _text(
        evidence.get("backend"),
        "OBSERVED_BACKEND",
    )
    output_sha256 = _sha256_text(
        evidence.get("output_sha256"),
        "OUTPUT_SHA256",
    )

    output = _text(
        response.get("output"),
        "SAFE_TOOL_OUTPUT",
    )

    workspace = _mapping(
        resolve_workspace_context_fn(
            workspace_object_id
        ),
        "POST_ACTION_WORKSPACE_CONTEXT",
    )

    observed_object_id = _text(
        workspace.get("object_id"),
        "OBSERVED_TARGET_OBJECT_ID",
    )
    target_source_path = _text(
        workspace.get("source_path"),
        "OBSERVED_TARGET_SOURCE_PATH",
    )
    observed_target_revision = _sha256_text(
        workspace.get("sha256"),
        "OBSERVED_TARGET_SOURCE_REVISION",
    )
    observed_bytes = _integer(
        workspace.get("bytes"),
        "OBSERVED_TARGET_BYTES",
    )
    observed_body = _text(
        workspace.get("body"),
        "OBSERVED_TARGET_BODY",
    )

    expected_request_path = (
        PROJECT_REQUEST_PREFIX
        + target_source_path
    )

    expected_output = (
        "PROFILE=READ\n"
        f"PATH={expected_request_path}\n"
        f"BYTES={observed_bytes}\n"
        f"SHA256={observed_target_revision}\n"
        "----- BEGIN FILE -----\n"
        + observed_body
        + (
            ""
            if observed_body.endswith("\n")
            else "\n"
        )
        + "----- END FILE -----"
    )

    mismatches: list[str] = []

    def mismatch(
        condition: bool,
        reason: str,
    ) -> None:
        if condition:
            mismatches.append(reason)

    mismatch(
        intent.get("effect_class")
        != EXPECTED_INTENT_EFFECT_CLASS,
        "EXPECTED_EFFECT_CLASS_UNSUPPORTED",
    )
    mismatch(
        intent.get("persistent_write")
        != EXPECTED_INTENT_PERSISTENT_WRITE,
        "EXPECTED_PERSISTENT_WRITE_UNSUPPORTED",
    )
    mismatch(
        intent.get("network")
        != EXPECTED_INTENT_NETWORK,
        "EXPECTED_NETWORK_UNSUPPORTED",
    )
    mismatch(
        intent.get("sudo")
        != EXPECTED_INTENT_SUDO,
        "EXPECTED_SUDO_UNSUPPORTED",
    )

    mismatch(
        workspace_object_id != target_object_id
        or observed_object_id != target_object_id,
        "TARGET_OBJECT_ID_MISMATCH",
    )
    mismatch(
        request_profile != "READ",
        "SAFE_TOOL_PROFILE_MISMATCH",
    )
    mismatch(
        request_path != expected_request_path,
        "TARGET_SOURCE_PATH_MISMATCH",
    )
    mismatch(
        observed_target_revision
        != expected_target_revision,
        "TARGET_SOURCE_REVISION_MISMATCH",
    )
    mismatch(
        observed_effect_class
        != OBSERVED_EFFECT_CLASS,
        "EFFECT_CLASS_MISMATCH",
    )
    mismatch(
        observed_write_authority
        != OBSERVED_PERSISTENT_WRITE_AUTHORITY,
        "PERSISTENT_WRITE_AUTHORITY_MISMATCH",
    )
    mismatch(
        observed_network_authority
        != OBSERVED_NETWORK_AUTHORITY,
        "NETWORK_AUTHORITY_MISMATCH",
    )
    mismatch(
        backend != OBSERVED_BACKEND,
        "BACKEND_MISMATCH",
    )
    mismatch(
        output != expected_output,
        "OUTPUT_PROVENANCE_MISMATCH",
    )
    mismatch(
        hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest()
        != output_sha256,
        "OUTPUT_SHA256_MISMATCH",
    )

    return _observation(
        mismatch_reasons=mismatches,
        target_object_id=target_object_id,
        target_source_path=target_source_path,
        expected_target_source_revision=(
            expected_target_revision
        ),
        observed_target_source_revision=(
            observed_target_revision
        ),
        output_sha256=output_sha256,
        backend=backend,
        observed_effect_class=observed_effect_class,
        observed_persistent_write_authority=(
            observed_write_authority
        ),
        observed_network_authority=(
            observed_network_authority
        ),
    )
