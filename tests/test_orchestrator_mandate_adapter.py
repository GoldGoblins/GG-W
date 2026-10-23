from __future__ import annotations

import hashlib
from pathlib import Path
import types

from backend import idekompass_decision_ingress as ingress
from backend import orchestrator_mandate_adapter as mandate_adapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def workspace_context() -> dict[str, str]:
    main_path = PROJECT_ROOT / "main.py"
    return {
        "object_id": "real-local-file-main",
        "source_path": "projects/gg-ai-desktop/main.py",
        "sha256": hashlib.sha256(main_path.read_bytes()).hexdigest(),
    }


def route() -> object:
    return types.SimpleNamespace(
        intent="EDIT",
        route_mode="SOURCE_BOUND_LASER",
        why="Deterministic source-bound route fixture.",
    )


def plan_action_contract() -> None:
    result = ingress.decide(
        user_text="Repair the verified current source.",
        workspace_context=workspace_context(),
        route_decision=route(),
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )

    expect(
        result["decision_kind"] == "PLAN_ACTION",
        "source-backed route did not produce PLAN_ACTION",
    )
    expect(
        result["revalidation_result"] == "REVALIDATED",
        "PLAN_ACTION did not revalidate",
    )

    mandate = result["orchestrator_mandate"]

    expect(
        mandate["status"] == "VALIDATED",
        "mandate request adapter did not validate: " + repr(mandate),
    )
    expect(
        mandate["reason_code"] == "MANDATE_REQUEST_PREPARED",
        "mandate adapter reason drift",
    )
    expect(
        mandate["mandate_requirement"] == "NOT_REQUIRED",
        "GREEN PLAN_ACTION mandate requirement drift",
    )
    expect(
        mandate["task_id"]
        == result["orchestrator_policy"]["validated_task"]["task_id"],
        "task identity continuity failed",
    )
    expect(
        mandate["handoff_id"]
        == result["orchestrator_handoff"]["handoff"]["handoff_id"],
        "handoff identity continuity failed",
    )
    expect(
        mandate["assigned_participant"] == "GG-AI-installator",
        "participant binding drift",
    )
    expect(
        mandate["creator_actor"] == "human:owner",
        "creator binding drift",
    )

    request = mandate["approval_request"]
    expect(
        isinstance(request, dict),
        "approval request missing",
    )
    expect(
        request["task_id"] == mandate["task_id"],
        "K7-K task ID continuity failed",
    )
    expect(
        request["request_capture_sha256"]
        == mandate["request_capture_sha256"],
        "request capture SHA continuity failed",
    )
    expect(
        request["approval_scope"]["selected_action_node_id"]
        == result["selected_action_node_id"],
        "selected action binding failed",
    )
    expect(
        request["approval_scope"]["state_base_revision"]
        == result["state_base"]["state_base_revision"],
        "state-base binding failed",
    )
    expect(
        request["approval_scope"]["ready_core"]["risk_class"]
        == result["orchestrator_policy"]["validated_task"]["risk_class"],
        "risk binding failed",
    )

    evaluation_context = mandate["evaluation_context"]
    expect(
        set(evaluation_context)
        == {
            "source_envelope",
            "goal_chain",
            "hypothesis_state",
            "state_base",
            "ledger_records",
            "memory_records",
        },
        "evaluation context surface drift",
    )
    expect(
        evaluation_context["goal_chain"] == result["goal_chain"],
        "goal-chain carriage drift",
    )
    expect(
        evaluation_context["hypothesis_state"] == result["hypothesis_state"],
        "hypothesis-state carriage drift",
    )
    expect(
        evaluation_context["state_base"] == result["state_base"],
        "state-base carriage drift",
    )
    expect(
        isinstance(evaluation_context["ledger_records"], list),
        "ledger-record carriage invalid",
    )
    expect(
        evaluation_context["memory_records"] == [],
        "memory-record carriage must remain explicit empty list",
    )
    expect(
        evaluation_context["source_envelope"]["ready_core"]["risk_class"] == "GREEN",
        "current evaluation source-envelope risk drift",
    )

    expected_binding = hashlib.sha256(
        "\x1f".join(
            (
                mandate["task_id"],
                mandate["handoff_id"],
                mandate["assigned_participant"],
                mandate["creator_actor"],
                mandate["request_capture_sha256"],
            )
        ).encode("utf-8")
    ).hexdigest()

    expect(
        mandate["provenance_binding_sha256"] == expected_binding,
        "outer provenance binding drift",
    )

    expect(
        mandate["canonical_request_mutated"] is False,
        "canonical K7-K request mutation appeared",
    )
    expect(
        mandate["mandate_assertion_created"] is False,
        "mandate assertion creation appeared",
    )
    expect(
        mandate["mandate_evaluated"] is False,
        "mandate evaluation appeared",
    )
    expect(
        mandate["capability_execution"] is False,
        "capability execution appeared",
    )
    expect(
        mandate["participant_execution"] is False,
        "participant execution appeared",
    )
    expect(
        mandate["ordinary_chat_blocked"] is False,
        "ordinary chat became blocked",
    )
    expect(
        mandate["action_authority"] == "NONE",
        "action authority expanded",
    )
    expect(
        mandate["network"] is False,
        "network authority appeared",
    )
    expect(
        mandate["runtime_write"] is False,
        "runtime write authority appeared",
    )


def nonplan_contract() -> None:
    result = ingress.decide(
        user_text="Inspect the verified current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
    )

    expect(
        result["decision_kind"] == "GATHER_INFORMATION",
        "unresolved route did not gather information",
    )

    mandate = result["orchestrator_mandate"]

    expect(
        mandate["status"] == "NOT_APPLICABLE",
        "non-plan decision invoked mandate preparation",
    )
    expect(
        mandate["approval_request"] is None,
        "non-plan decision exposed approval request",
    )
    expect(
        mandate["ordinary_chat_blocked"] is False,
        "non-plan ordinary chat became blocked",
    )
    expect(
        mandate["action_authority"] == "NONE",
        "non-plan authority expanded",
    )


def blocked_policy_contract() -> None:
    result = ingress.decide(
        user_text="Repair the verified current source.",
        workspace_context=workspace_context(),
        route_decision=route(),
        information_available=True,
        assigned_participant="UNKNOWN",
        creator_actor="human:owner",
    )

    expect(
        result["decision_kind"] == "PLAN_ACTION",
        "route fixture decision changed",
    )
    expect(
        result["orchestrator_policy"]["status"] == "BLOCKED",
        "invalid participant policy did not block",
    )
    expect(
        result["orchestrator_handoff"]["status"] == "BLOCKED",
        "invalid participant handoff did not block",
    )

    mandate = result["orchestrator_mandate"]

    expect(
        mandate["status"] == "BLOCKED",
        "invalid orchestration produced mandate request",
    )
    expect(
        mandate["approval_request"] is None,
        "blocked orchestration exposed approval request",
    )
    expect(
        mandate["action_authority"] == "NONE",
        "blocked orchestration expanded authority",
    )


def static_authority_contract() -> None:
    source = Path(mandate_adapter.__file__).read_text(
        encoding="utf-8",
        errors="strict",
    )

    forbidden = (
        "make_mandate_assertion",
        "evaluate_mandate",
        "gg_controlled_tool_execution",
        "autonomy_controller",
        "subprocess",
        "socket",
    )

    for token in forbidden:
        expect(
            token not in source,
            "forbidden mandate adapter token present: " + token,
        )

    expect(
        'ACTION_AUTHORITY = "NONE"' in source,
        "mandate adapter authority constant drift",
    )
    expect(
        '"make_approval_request"' in source,
        "allowed K7-K operation missing",
    )


def main() -> None:
    static_authority_contract()
    plan_action_contract()
    nonplan_contract()
    blocked_policy_contract()

    print("ORCHESTRATOR_MANDATE_ADAPTER_TEST=PASS")
    print("PLAN_ACTION_K7K_REQUEST=PASS")
    print("GATHER_INFORMATION_NOT_APPLICABLE=PASS")
    print("BLOCKED_POLICY_FAILS_CLOSED=PASS")
    print("MANDATE_ASSERTION_CREATED=NO")
    print("MANDATE_EVALUATED=NO")
    print("CONTROLLED_TOOL_EXECUTION=NO")
    print("PARTICIPANT_EXECUTION=NO")
    print("ACTION_AUTHORITY=NONE")


if __name__ == "__main__":
    main()
