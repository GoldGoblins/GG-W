from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

from backend import orchestrator_ingress as ingress
from backend import orchestrator_policy_adapter as adapter


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def envelope() -> dict[str, object]:
    return {
        "task_id": "chat-policy-adapter-test",
        "state": "READY_FOR_CONTROL",
        "ready_core": {
            "owner": "Gold Goblins",
            "goal": "Validate current task policy.",
            "expected_value": "Read-only policy metadata.",
            "scope": ["local"],
            "forbidden_scope": ["network", "production"],
            "risk_class": "GREEN",
            "stop_conditions": ["policy failure"],
            "expected_artifacts": ["policy metadata"],
            "acceptance_criteria": ["validate_task PASS"],
        },
    }


def verified_context() -> dict[str, str]:
    return {
        "source_path": "qml/components/ContextComposer.qml",
        "object_id": "ws.file.context-composer",
        "sha256": "a" * 64,
    }


def static_adapter_contract() -> None:
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
    validate = functions.get("validate_prepared_task")
    expect(validate is not None, "validate_prepared_task missing")

    attrs = {
        node.func.attr
        for node in ast.walk(validate)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    expect("validate_task" in attrs, "validate_task contact missing")
    for forbidden in (
        "evaluate",
        "validate_handoff",
        "validate_gate",
        "validate_review",
    ):
        expect(
            forbidden not in attrs,
            "forbidden stage called: " + forbidden,
        )

    expect(
        adapter.ORCHESTRATOR_SHA256
        == "f6fbddd9cdaf31984ae9c6c99bab66aa3622fc098c4946081460ed6a51b97123",
        "orchestrator SHA pin drift",
    )


def blocked_ingress_does_not_load_source() -> None:
    blocked = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
    )

    with mock.patch.object(
        adapter,
        "_load_orchestrator",
        side_effect=AssertionError(
            "blocked ingress attempted orchestrator load"
        ),
    ):
        result = adapter.validate_prepared_task(blocked)

    expect(result["status"] == "BLOCKED", "blocked ingress changed")
    expect(
        result["reason_code"]
        == "EXPLICIT_ASSIGNMENT_AND_CREATOR_ACTOR_REQUIRED",
        "blocked ingress reason drift",
    )
    expect(
        result["ordinary_chat_blocked"] is False,
        "ordinary chat became blocked",
    )
    expect(
        result["action_authority"] == "NONE",
        "action authority expanded",
    )


def positive_real_validate_task() -> None:
    prepared = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )
    expect(
        prepared["status"] == "CONDITIONAL",
        "prepared task not conditional",
    )

    result = adapter.validate_prepared_task(prepared)
    expect(
        result["status"] == "VALIDATED",
        "valid task did not validate: " + repr(result),
    )
    expect(
        result["reason_code"] == "VALIDATE_TASK_PASS",
        "policy pass reason drift",
    )
    expect(
        result["source_binding"]["validator"] == "validate_task",
        "validator binding drift",
    )
    expect(
        result["validated_task"]["first_gate"]
        == "idekompassen-2.0",
        "first gate drift",
    )
    expect(
        result["validated_task"]["historical_context"] == {},
        "history fabricated",
    )
    expect(
        result["validated_task"]["rights_expansion"] is False,
        "rights expansion changed",
    )
    expect(
        all(
            value is False
            for value in result["validated_task"][
                "requested_effects"
            ].values()
        ),
        "blocked effects not all false",
    )
    expect(
        result["orchestrator_evaluate"] is False,
        "evaluate authority appeared",
    )
    expect(
        result["handoff_created"] is False,
        "handoff created",
    )


def unknown_participant_fails_closed() -> None:
    prepared = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        assigned_participant="UNKNOWN",
        creator_actor="human:owner",
    )
    result = adapter.validate_prepared_task(prepared)
    expect(result["status"] == "BLOCKED", "unknown participant passed")
    expect(
        result["reason_code"] == "unknown_participant",
        "unknown participant reason drift: "
        + repr(result["reason_code"]),
    )
    expect(
        result["validated_task"] is None,
        "blocked task exposed as validated",
    )


def trap_later_stages() -> None:
    class FakePolicyError(RuntimeError):
        pass

    class FakeModule:
        PolicyError = FakePolicyError
        IDEKOMPASS_REQUIRED = adapter.IDEKOMPASS_REQUIRED
        BLOCKED_EFFECTS = adapter.BLOCKED_EFFECTS

        @staticmethod
        def validate_task(task: dict[str, object]) -> None:
            if task["assigned_participant"] != "GG-AI-installator":
                raise FakePolicyError("unknown_participant")

        @staticmethod
        def evaluate(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("evaluate called")

        @staticmethod
        def validate_handoff(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("handoff called")

        @staticmethod
        def validate_gate(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("gate called")

        @staticmethod
        def validate_review(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("review called")

    prepared = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )

    with mock.patch.object(
        adapter,
        "_load_orchestrator",
        return_value=FakeModule(),
    ):
        result = adapter.validate_prepared_task(prepared)

    expect(result["status"] == "VALIDATED", "validate_task trap failed")


def main() -> None:
    static_adapter_contract()
    blocked_ingress_does_not_load_source()
    positive_real_validate_task()
    unknown_participant_fails_closed()
    trap_later_stages()

    print("ORCHESTRATOR_POLICY_ADAPTER_STATIC=PASS")
    print("BLOCKED_INGRESS_SOURCE_LOAD=NO")
    print("REAL_VALIDATE_TASK=PASS")
    print("UNKNOWN_PARTICIPANT_FAIL_CLOSED=PASS")
    print("LATER_ORCHESTRATOR_STAGES=NOT_CALLED")
    print("ACTION_AUTHORITY=NONE")
    print("ORCHESTRATOR_POLICY_ADAPTER_TEST=PASS")


if __name__ == "__main__":
    main()
