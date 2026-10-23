from __future__ import annotations


SCHEMA = "gg.action-effect-recovery.v1"

RESULT_NO_RECOVERY_REQUIRED = (
    "NO_RECOVERY_REQUIRED"
)
RESULT_REPLAN_REQUIRED = "REPLAN_REQUIRED"

EXPECTED_EFFECT_CLASS = (
    "READ_ONLY_TOOL_EXECUTION"
)
EXPECTED_PERSISTENT_WRITE = "RUNTIME_ONLY"
EXPECTED_NETWORK = "NONE"
EXPECTED_SUDO = "NO"

OBSERVATION_SCHEMA = (
    "gg.action-effect-observation.v1"
)


def _mapping(
    value: object,
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(
            label + "_MAPPING_INVALID"
        )

    return dict(value)


def _text(
    value: object,
    label: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value
    ):
        raise RuntimeError(
            label + "_TEXT_INVALID"
        )

    return value


def _boolean(
    value: object,
    label: str,
) -> bool:
    if not isinstance(value, bool):
        raise RuntimeError(
            label + "_BOOLEAN_INVALID"
        )

    return value


def _mismatch_reasons(
    value: object,
) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(
            "MISMATCH_REASONS_INVALID"
        )

    result: list[str] = []

    for item in value:
        result.append(
            _text(
                item,
                "MISMATCH_REASON",
            )
        )

    return result


def _validate_action_envelope(
    intent: dict[str, object],
) -> None:
    if (
        intent.get("effect_class")
        != EXPECTED_EFFECT_CLASS
        or intent.get("persistent_write")
        != EXPECTED_PERSISTENT_WRITE
        or intent.get("network")
        != EXPECTED_NETWORK
        or intent.get("sudo")
        != EXPECTED_SUDO
    ):
        raise RuntimeError(
            "D70_ACTION_ENVELOPE_UNSUPPORTED"
        )

    _text(
        intent.get("target_object_id"),
        "TARGET_OBJECT_ID",
    )
    _text(
        intent.get("target_source_revision"),
        "TARGET_SOURCE_REVISION",
    )


def _validate_execution_authority(
    eligibility: dict[str, object],
) -> None:
    if (
        eligibility.get("action_authority")
        != "NONE"
        or eligibility.get(
            "general_action_authority"
        )
        != "NONE"
        or eligibility.get(
            "execution_persistent_write_authority"
        )
        != "NONE"
        or eligibility.get(
            "capability_execution"
        )
        is not False
        or eligibility.get(
            "k7_l_execution"
        )
        is not False
        or eligibility.get(
            "participant_execution"
        )
        is not False
        or eligibility.get("network")
        != "NONE"
        or eligibility.get("sudo")
        != "NO"
        or eligibility.get(
            "model_inference"
        )
        is not False
    ):
        raise RuntimeError(
            "D70_EXECUTION_AUTHORITY_UNSUPPORTED"
        )


def _result(
    *,
    result: str,
    reason_code: str,
    observation_reason_code: str,
    mismatch_reasons: list[str],
    target_object_id: str,
    target_source_revision: str,
) -> dict[str, object]:
    replan_required = (
        result == RESULT_REPLAN_REQUIRED
    )

    return {
        "schema": SCHEMA,
        "result": result,
        "reason_code": reason_code,
        "observation_reason_code": (
            observation_reason_code
        ),
        "mismatch_reasons": list(
            mismatch_reasons
        ),
        "target_object_id": (
            target_object_id
        ),
        "target_source_revision": (
            target_source_revision
        ),
        "replan_required": (
            replan_required
        ),
        "authority_reevaluation_required": (
            replan_required
        ),
        "repair_execution": False,
        "automatic_rerun": False,
        "existing_mandate_reusable": False,
        "new_action_authority_granted": False,
        "action_authority": "NONE",
        "general_action_authority": "NONE",
        "execution_persistent_write_authority": (
            "NONE"
        ),
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,
    }


def classify_action_effect_recovery(
    *,
    action_intent: dict[str, object],
    execution_eligibility: dict[str, object],
    actual_effect_observation: dict[str, object],
    execution_state: str,
) -> dict[str, object]:
    intent = _mapping(
        action_intent,
        "ACTION_INTENT",
    )
    eligibility = _mapping(
        execution_eligibility,
        "EXECUTION_ELIGIBILITY",
    )
    observation = _mapping(
        actual_effect_observation,
        "ACTUAL_EFFECT_OBSERVATION",
    )

    if execution_state != "CONSUMED_PASS":
        raise RuntimeError(
            "D70_EXECUTION_NOT_CONSUMED_PASS"
        )

    _validate_action_envelope(
        intent
    )
    _validate_execution_authority(
        eligibility
    )

    if (
        observation.get("schema")
        != OBSERVATION_SCHEMA
    ):
        raise RuntimeError(
            "D70_OBSERVATION_SCHEMA_INVALID"
        )

    result = _text(
        observation.get("result"),
        "OBSERVATION_RESULT",
    )
    reason_code = _text(
        observation.get("reason_code"),
        "OBSERVATION_REASON_CODE",
    )
    actual_effect_verified = _boolean(
        observation.get(
            "actual_effect_verified"
        ),
        "ACTUAL_EFFECT_VERIFIED",
    )
    d70_required = _boolean(
        observation.get("d70_required"),
        "D70_REQUIRED",
    )
    mismatches = _mismatch_reasons(
        observation.get(
            "mismatch_reasons"
        )
    )

    target_object_id = _text(
        intent.get("target_object_id"),
        "TARGET_OBJECT_ID",
    )
    target_source_revision = _text(
        intent.get(
            "target_source_revision"
        ),
        "TARGET_SOURCE_REVISION",
    )

    if result == "MATCH":
        if (
            actual_effect_verified is not True
            or d70_required is not False
            or mismatches
            or reason_code
            != "EXPECTED_ACTUAL_MATCH"
        ):
            raise RuntimeError(
                "D70_MATCH_CONTRACT_INVALID"
            )

        return _result(
            result=(
                RESULT_NO_RECOVERY_REQUIRED
            ),
            reason_code=(
                "ACTUAL_EFFECT_VERIFIED"
            ),
            observation_reason_code=(
                reason_code
            ),
            mismatch_reasons=[],
            target_object_id=(
                target_object_id
            ),
            target_source_revision=(
                target_source_revision
            ),
        )

    if result == "MISMATCH":
        if (
            actual_effect_verified is not False
            or d70_required is not True
            or not mismatches
            or reason_code != mismatches[0]
        ):
            raise RuntimeError(
                "D70_MISMATCH_CONTRACT_INVALID"
            )

        return _result(
            result=RESULT_REPLAN_REQUIRED,
            reason_code=(
                "ACTUAL_EFFECT_MISMATCH_"
                "REQUIRES_REPLAN"
            ),
            observation_reason_code=(
                reason_code
            ),
            mismatch_reasons=mismatches,
            target_object_id=(
                target_object_id
            ),
            target_source_revision=(
                target_source_revision
            ),
        )

    raise RuntimeError(
        "D70_OBSERVATION_RESULT_UNSUPPORTED:"
        + result
    )
