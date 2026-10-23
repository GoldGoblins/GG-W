from __future__ import annotations

import hashlib
import sys
from pathlib import Path
import types

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import idekompass_decision_ingress as ingress


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def workspace_context() -> dict[str, str]:
    main_path = Path(__file__).resolve().parents[1] / "main.py"
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


def explicit_orchestrator_assignment_forwarding_contract() -> None:
    from backend import idekompass_decision_ingress as assignment_ingress

    assigned = assignment_ingress.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )
    assigned_ingress = assigned["orchestrator_ingress"]

    expected = {
        "status": "CONDITIONAL",
        "reason_code": "ORCHESTRATOR_POLICY_VALIDATION_REQUIRED",
        "assigned_participant": "GG-AI-installator",
        "creator_actor": "human:owner",
        "ordinary_chat_blocked": False,
        "action_authority": "NONE",
        "orchestrator_evaluate": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }
    for key, value in expected.items():
        if assigned_ingress.get(key) != value:
            raise AssertionError(
                "Assigned ingress mismatch: "
                + key
                + "="
                + repr(assigned_ingress.get(key))
            )

    unassigned = assignment_ingress.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
    )
    unassigned_ingress = unassigned["orchestrator_ingress"]
    if unassigned_ingress["status"] != "BLOCKED":
        raise AssertionError(
            "Unassigned ingress must remain BLOCKED."
        )
    if unassigned_ingress["ordinary_chat_blocked"] is not False:
        raise AssertionError(
            "Unassigned ordinary chat became blocked."
        )


def orchestrator_policy_adapter_integration_contract() -> None:
    from backend import idekompass_decision_ingress as policy_idea

    assigned = policy_idea.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )

    assigned_ingress = assigned["orchestrator_ingress"]
    assigned_policy = assigned["orchestrator_policy"]

    if assigned_ingress["status"] != "CONDITIONAL":
        raise AssertionError(
            "D46 ingress layer no longer remains conditional."
        )
    if (
        assigned_ingress["reason_code"]
        != "ORCHESTRATOR_POLICY_VALIDATION_REQUIRED"
    ):
        raise AssertionError("D46 ingress reason changed.")

    expected_policy = {
        "status": "VALIDATED",
        "reason_code": "VALIDATE_TASK_PASS",
        "assigned_participant": "GG-AI-installator",
        "creator_actor": "human:owner",
        "ordinary_chat_blocked": False,
        "action_authority": "NONE",
        "orchestrator_evaluate": False,
        "handoff_created": False,
        "handoff_validated": False,
        "gate_validated": False,
        "review_validated": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }

    for key, value in expected_policy.items():
        if assigned_policy.get(key) != value:
            raise AssertionError(
                "Assigned policy mismatch: "
                + key
                + "="
                + repr(assigned_policy.get(key))
            )

    if assigned_policy["source_binding"]["validator"] != "validate_task":
        raise AssertionError("Policy validator identity drift.")
    if assigned_policy["validated_task"]["historical_context"] != {}:
        raise AssertionError("Historical provenance was fabricated.")

    invalid = policy_idea.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
        assigned_participant="UNKNOWN",
        creator_actor="human:owner",
    )
    if invalid["orchestrator_ingress"]["status"] != "CONDITIONAL":
        raise AssertionError("Invalid participant bypassed policy layer.")
    if invalid["orchestrator_policy"]["status"] != "BLOCKED":
        raise AssertionError("Invalid participant was not policy-blocked.")
    if invalid["orchestrator_policy"]["reason_code"] != "unknown_participant":
        raise AssertionError("Invalid participant reason drift.")

    unassigned = policy_idea.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
    )
    if unassigned["orchestrator_ingress"]["status"] != "BLOCKED":
        raise AssertionError("Unassigned D46 ingress no longer blocks.")
    if unassigned["orchestrator_policy"]["status"] != "BLOCKED":
        raise AssertionError("Unassigned policy did not fail closed.")
    if (
        unassigned["orchestrator_policy"]["ordinary_chat_blocked"]
        is not False
    ):
        raise AssertionError("Unassigned policy blocked ordinary chat.")


def orchestrator_handoff_adapter_integration_contract() -> None:
    from backend import idekompass_decision_ingress as handoff_idea

    assigned = handoff_idea.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )

    if assigned["orchestrator_ingress"]["status"] != "CONDITIONAL":
        raise AssertionError("Ingress result changed.")
    if assigned["orchestrator_policy"]["status"] != "VALIDATED":
        raise AssertionError("Policy result changed.")

    handoff = assigned["orchestrator_handoff"]

    if handoff["status"] != "VALIDATED":
        raise AssertionError(
            "Assigned handoff did not validate: " + repr(handoff)
        )
    if handoff["reason_code"] != "VALIDATE_HANDOFF_PASS":
        raise AssertionError("Handoff reason drift.")
    if handoff["handoff"]["artifacts"] != []:
        raise AssertionError("Expected artifacts became actual artifacts.")
    if handoff["handoff"]["risks"] != []:
        raise AssertionError("Forbidden scope became observed risks.")
    if (
        handoff["handoff"]["next_action"]
        != "SELECTION_HANDOFF_ONLY_NO_EXECUTION"
    ):
        raise AssertionError("Handoff next_action drift.")
    if handoff["participant_execution"] is not False:
        raise AssertionError("Participant execution appeared.")
    if handoff["action_authority"] != "NONE":
        raise AssertionError("Action authority expanded.")

    invalid = handoff_idea.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
        assigned_participant="UNKNOWN",
        creator_actor="human:owner",
    )

    if invalid["orchestrator_policy"]["status"] != "BLOCKED":
        raise AssertionError("Invalid participant policy did not block.")
    if invalid["orchestrator_handoff"]["status"] != "BLOCKED":
        raise AssertionError("Invalid participant produced handoff.")
    if invalid["orchestrator_handoff"]["handoff"] is not None:
        raise AssertionError("Blocked handoff exposed metadata.")

    unassigned = handoff_idea.decide(
        user_text="Inspect current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
    )

    if unassigned["orchestrator_ingress"]["status"] != "BLOCKED":
        raise AssertionError("Unassigned ingress changed.")
    if unassigned["orchestrator_policy"]["status"] != "BLOCKED":
        raise AssertionError("Unassigned policy changed.")
    if unassigned["orchestrator_handoff"]["status"] != "BLOCKED":
        raise AssertionError("Unassigned handoff did not block.")
    if (
        unassigned["orchestrator_handoff"]["ordinary_chat_blocked"]
        is not False
    ):
        raise AssertionError("Ordinary chat became blocked.")


def main() -> None:
    scratch = ingress.decide(
        user_text="hejsan",
        workspace_context={
            "object_id": "ws.file.scratch.1",
            "title": "untitled",
            "object_type": "CODE_FILE",
            "provenance": "REAL_UI_STATE",
            "source_path": "",
            "sha256": "",
            "bytes": 0,
            "body": "LASER_IDENTITY · CODE_FILE · no file bytes",
        },
        route_decision=None,
        information_available=True,
    )
    expect(
        scratch["action_authority"] == "NONE",
        "scratch ordinary chat expanded action authority",
    )
    expect(
        scratch["orchestrator_ingress"]["ordinary_chat_blocked"] is False,
        "scratch ordinary chat was blocked by Idékompass",
    )
    orchestrator_handoff_adapter_integration_contract()
    orchestrator_policy_adapter_integration_contract()
    explicit_orchestrator_assignment_forwarding_contract()
    plan = ingress.decide(
        user_text="Repair the verified current source.",
        workspace_context=workspace_context(),
        route_decision=route(),
    )

    expect(
        plan["decision_kind"] == "PLAN_ACTION",
        "verified route must produce PLAN_ACTION",
    )
    expect(
        plan["reason_code"] == "SINGLE_SUPPORTED_ACTION",
        "verified route reason mismatch",
    )
    expect(
        plan["revalidation_result"] == "REVALIDATED",
        "verified route must revalidate",
    )
    expect(
        plan["action_authority"] == "NONE",
        "action authority expanded",
    )
    expect(
        plan["plan_action_is_approval"] is False,
        "PLAN_ACTION became approval",
    )
    expect(
        plan["ledger_persistence"] == "NONE",
        "ledger persistence expanded",
    )
    expect(
        plan["model_output_as_evidence"] is False,
        "model output became evidence",
    )
    expect(
        plan["capability_execution"] == "NONE",
        "capability execution expanded",
    )
    expect(
        plan["automatic_model_dispatch"] == "NONE",
        "automatic model dispatch expanded",
    )
    expect(
        plan["cognitive_core_binding"]
        == "REAL_READ_ONLY_EPHEMERAL_VERIFIED_RECORD",
        "wrong cognitive binding",
    )

    gather = ingress.decide(
        user_text="Inspect the current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
    )

    expect(
        gather["decision_kind"] == "GATHER_INFORMATION",
        "unresolved route with information option must gather",
    )

    stopped = ingress.decide(
        user_text="Inspect the current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=False,
    )

    expect(
        stopped["decision_kind"] == "STOP_UNCERTAINTY",
        "unresolved route without information option must stop",
    )

    expect(
        gather["decision_kind"] != plan["decision_kind"],
        "new verified evidence did not revise decision",
    )

    expect(
        "[GG IDEKOMPASS READ-ONLY DECISION]"
        in plan["prompt_extension"],
        "prompt extension missing",
    )

    source = Path(ingress.__file__).read_text(
        encoding="utf-8",
        errors="strict",
    )

    expect(
        "append_candidate(" not in source,
        "ledger append path present in ingress",
    )
    expect(
        "autonomy_controller" not in source,
        "autonomy controller dependency present",
    )

    print("IDEKOMPASS_REAL_COGNITIVE_BINDING=PASS")
    print("GATHER_INFORMATION=PASS")
    print("PLAN_ACTION=PASS")
    print("STOP_UNCERTAINTY=PASS")
    print("READ_ONLY_REVALIDATION=PASS")
    print("ACTION_AUTHORITY=NONE")
    print("LEDGER_PERSISTENCE=NONE")
    print("MODEL_OUTPUT_AS_EVIDENCE=NO")
    print("IDEKOMPASS_DECISION_INGRESS_TEST=PASS")


if __name__ == "__main__":
    main()
