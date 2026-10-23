from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

from backend import orchestrator_handoff_adapter as adapter
from backend import orchestrator_ingress as ingress
from backend import orchestrator_policy_adapter as policy_adapter


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def envelope() -> dict[str, object]:
    return {
        "task_id": "chat-handoff-adapter-test",
        "state": "READY_FOR_CONTROL",
        "ready_core": {
            "owner": "Gold Goblins",
            "goal": "Validate selection handoff.",
            "expected_value": "Validated handoff metadata.",
            "scope": ["local"],
            "forbidden_scope": ["network", "production"],
            "risk_class": "GREEN",
            "stop_conditions": ["handoff policy failure"],
            "expected_artifacts": ["handoff metadata"],
            "acceptance_criteria": ["validate_handoff PASS"],
        },
    }


def verified_context() -> dict[str, str]:
    return {
        "source_path": "qml/components/ContextComposer.qml",
        "object_id": "ws.file.context-composer",
        "sha256": "b" * 64,
    }


def validated_policy() -> dict[str, object]:
    prepared = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )
    result = policy_adapter.validate_prepared_task(prepared)
    expect(
        result["status"] == "VALIDATED",
        "fixture policy did not validate",
    )
    return result


def static_contract() -> None:
    source_path = Path(adapter.__file__).resolve()
    source = source_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    tree = ast.parse(source, filename=str(source_path))

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    validate = functions.get("validate_policy_handoff")
    expect(validate is not None, "entrypoint missing")

    attrs = {
        node.func.attr
        for node in ast.walk(validate)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }

    expect(
        "validate_handoff" in attrs,
        "validate_handoff contact missing",
    )

    for forbidden in (
        "evaluate",
        "validate_task",
        "validate_gate",
        "validate_review",
    ):
        expect(
            forbidden not in attrs,
            "forbidden stage called: " + forbidden,
        )


def positive_real_validate_handoff() -> None:
    result = adapter.validate_policy_handoff(
        validated_policy()
    )

    expect(
        result["status"] == "VALIDATED",
        "handoff did not validate: " + repr(result),
    )
    expect(
        result["reason_code"] == "VALIDATE_HANDOFF_PASS",
        "handoff reason drift",
    )

    handoff = result["handoff"]

    expect(
        handoff["status"] == "PASS",
        "internal handoff status drift",
    )
    expect(
        handoff["from_role"] == "idekompassen-2.0",
        "from_role drift",
    )
    expect(
        handoff["to_role"] == "GG-AI-installator",
        "to_role drift",
    )
    expect(
        handoff["artifacts"] == [],
        "artifacts were fabricated",
    )
    expect(
        handoff["risks"] == [],
        "risks were fabricated",
    )
    expect(
        handoff["next_action"]
        == "SELECTION_HANDOFF_ONLY_NO_EXECUTION",
        "next action drift",
    )
    expect(
        result["selection_handoff_only"] is True,
        "selection-only flag drift",
    )
    expect(
        result["participant_execution"] is False,
        "participant execution appeared",
    )
    expect(
        result["action_authority"] == "NONE",
        "action authority expanded",
    )


def blocked_policy_does_not_load_source() -> None:
    blocked = policy_adapter.validate_prepared_task(
        ingress.prepare_or_block(
            envelope=envelope(),
            verified_context=verified_context(),
        )
    )

    expect(
        blocked["status"] == "BLOCKED",
        "policy fixture did not block",
    )

    with mock.patch.object(
        adapter,
        "_load_orchestrator",
        side_effect=AssertionError(
            "blocked policy attempted orchestrator load"
        ),
    ):
        result = adapter.validate_policy_handoff(blocked)

    expect(
        result["status"] == "BLOCKED",
        "blocked policy produced handoff",
    )
    expect(
        result["handoff"] is None,
        "blocked policy exposed handoff",
    )


def deterministic_id() -> None:
    policy = validated_policy()

    first = adapter.validate_policy_handoff(policy)
    second = adapter.validate_policy_handoff(policy)

    expect(
        first["handoff"]["handoff_id"]
        == second["handoff"]["handoff_id"],
        "handoff id not deterministic",
    )


def trap_later_stages() -> None:
    class FakePolicyError(RuntimeError):
        pass

    class FakeModule:
        PolicyError = FakePolicyError

        @staticmethod
        def validate_handoff(
            handoff: dict[str, object],
            task: dict[str, object],
        ) -> None:
            if handoff["task_id"] != task["task_id"]:
                raise FakePolicyError("handoff_task_mismatch")

        @staticmethod
        def evaluate(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("evaluate called")

        @staticmethod
        def validate_task(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("validate_task called")

        @staticmethod
        def validate_gate(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("validate_gate called")

        @staticmethod
        def validate_review(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("validate_review called")

    with mock.patch.object(
        adapter,
        "_load_orchestrator",
        return_value=FakeModule(),
    ):
        result = adapter.validate_policy_handoff(
            validated_policy()
        )

    expect(
        result["status"] == "VALIDATED",
        "validate_handoff trap failed",
    )


def main() -> None:
    static_contract()
    positive_real_validate_handoff()
    blocked_policy_does_not_load_source()
    deterministic_id()
    trap_later_stages()

    print("ORCHESTRATOR_HANDOFF_ADAPTER_STATIC=PASS")
    print("REAL_VALIDATE_HANDOFF=PASS")
    print("BLOCKED_POLICY_SOURCE_LOAD=NO")
    print("DETERMINISTIC_HANDOFF_ID=PASS")
    print("ARTIFACTS_FABRICATED=NO")
    print("RISKS_FABRICATED=NO")
    print("PARTICIPANT_EXECUTION=NO")
    print("LATER_ORCHESTRATOR_STAGES=NOT_CALLED")
    print("ACTION_AUTHORITY=NONE")
    print("ORCHESTRATOR_HANDOFF_ADAPTER_TEST=PASS")


if __name__ == "__main__":
    main()
