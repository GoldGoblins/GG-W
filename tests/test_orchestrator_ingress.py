from __future__ import annotations

from backend import idekompass_decision_ingress as idekompass
from backend import orchestrator_ingress as ingress


def expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(message)


def ready_core() -> dict[str, object]:
    return {
        "owner": "GG",
        "goal": "Inspect the current source.",
        "expected_value": "A read-only provenance-bound decision.",
        "scope": [
            "verified local workspace source",
            "ordinary local chat",
        ],
        "forbidden_scope": [
            "network",
            "host write",
            "automatic action authority",
        ],
        "risk_class": "GREEN",
        "stop_conditions": [
            "source identity drift",
            "unexpected authority expansion",
        ],
        "expected_artifacts": [
            "decision envelope",
            "state revalidation result",
        ],
        "acceptance_criteria": [
            "ORIGINAL_INTENT preserved",
            "ACTION_AUTHORITY remains NONE",
        ],
    }


def envelope() -> dict[str, object]:
    return {
        "schema": "synthetic-task-envelope",
        "task_id": "chat-0123456789abcdef0123456789abcdef",
        "origin_id": "workbench-test",
        "state": "READY_FOR_CONTROL",
        "original_expression": "Inspect the current source.",
        "current_interpretation": "Read-only test.",
        "ready_core": ready_core(),
    }


def verified_context() -> dict[str, str]:
    return {
        "source_path": "qml/components/ContextComposer.qml",
        "object_id": "ws.file.context-composer",
        "sha256": "a" * 64,
    }


def main() -> None:
    source_envelope = envelope()
    source_context = verified_context()

    blocked = ingress.prepare_or_block(
        envelope=source_envelope,
        verified_context=source_context,
    )

    expect(
        blocked["schema"] == ingress.SCHEMA_ID,
        "wrong ingress schema",
    )
    expect(
        blocked["status"] == "BLOCKED",
        "unassigned ingress did not block",
    )
    expect(
        blocked["reason_code"]
        == "EXPLICIT_ASSIGNMENT_AND_CREATOR_ACTOR_REQUIRED",
        "wrong unassigned reason",
    )
    expect(
        blocked["task_seed"]["task_id"]
        == source_envelope["task_id"],
        "task id was not reused",
    )
    expect(
        blocked["task_seed"]["ready_core"]
        == source_envelope["ready_core"],
        "ready core was not preserved",
    )
    expect(
        blocked["task_seed"]["verified_context"]
        == source_context,
        "verified context was not preserved",
    )
    expect(
        blocked["ordinary_chat_blocked"] is False,
        "ordinary chat became blocked",
    )
    expect(
        blocked["action_authority"] == "NONE",
        "action authority expanded",
    )
    expect(
        blocked["orchestrator_evaluate"] is False,
        "orchestrator evaluate became executable",
    )
    expect(
        blocked["agent_core_execution"] is False,
        "agent core became executable",
    )
    expect(
        blocked["model_inference"] is False,
        "model inference became available",
    )
    expect(
        blocked["network"] is False,
        "network became available",
    )
    expect(
        blocked["runtime_write"] is False,
        "runtime write became available",
    )

    blocked["task_seed"]["ready_core"]["scope"].append(
        "mutated-copy"
    )
    expect(
        "mutated-copy"
        not in source_envelope["ready_core"]["scope"],
        "ready core alias leaked",
    )

    participant_only = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        assigned_participant="GG-AI-installator",
    )
    expect(
        participant_only["status"] == "BLOCKED"
        and participant_only["reason_code"]
        == "CREATOR_ACTOR_REQUIRED",
        "participant-only input did not fail closed",
    )

    actor_only = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        creator_actor="explicit-human-actor",
    )
    expect(
        actor_only["status"] == "BLOCKED"
        and actor_only["reason_code"]
        == "EXPLICIT_ASSIGNMENT_REQUIRED",
        "actor-only input did not fail closed",
    )

    conditional = ingress.prepare_or_block(
        envelope=envelope(),
        verified_context=verified_context(),
        assigned_participant="GG-AI-installator",
        creator_actor="explicit-human-actor",
    )
    expect(
        conditional["status"] == "CONDITIONAL",
        "complete explicit inputs bypassed policy validation",
    )
    expect(
        conditional["reason_code"]
        == "ORCHESTRATOR_POLICY_VALIDATION_REQUIRED",
        "wrong policy-validation boundary",
    )
    expect(
        conditional["action_authority"] == "NONE",
        "conditional result expanded authority",
    )

    workbench_result = idekompass.decide(
        user_text="Inspect the current source.",
        workspace_context=verified_context(),
        route_decision=None,
        information_available=True,
    )
    integrated = workbench_result["orchestrator_ingress"]

    expect(
        integrated["status"] == "BLOCKED",
        "ordinary chat ingress did not remain fail closed",
    )
    expect(
        integrated["ordinary_chat_blocked"] is False,
        "ordinary chat was blocked by unassigned orchestration",
    )
    expect(
        integrated["task_seed"]["task_id"].startswith(
            "chat-"
        ),
        "canonical Idékompass task id was not exposed",
    )
    expect(
        integrated["task_seed"]["verified_context"]["sha256"]
        == verified_context()["sha256"],
        "verified source provenance drifted",
    )

    print("ORCHESTRATOR_INGRESS_DIRECT=PASS")
    print("ORCHESTRATOR_INGRESS_IDEEKOMPASS_CONTACT=PASS")
    print("UNASSIGNED_FAIL_CLOSED=PASS")
    print("ORDINARY_CHAT_BLOCKED=NO")
    print("ACTION_AUTHORITY=NONE")
    print("ORCHESTRATOR_EVALUATE=NO")
    print("AGENT_CORE_EXECUTION=NO")
    print("ORCHESTRATOR_INGRESS_TEST=PASS")


if __name__ == "__main__":
    main()
