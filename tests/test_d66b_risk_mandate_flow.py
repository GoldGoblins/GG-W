from __future__ import annotations

import hashlib
from pathlib import Path
import types

from backend import action_intent_contract
from backend import capability_registry
from backend import idekompass_decision_ingress as ingress
from backend import orchestrator_mandate_evaluation_adapter as evaluation_adapter


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def actual_registry() -> capability_registry.CapabilityRegistry:
    return capability_registry.CapabilityRegistry.load(
        repo_root=REPO,
        project_root=PROJECT,
        seed_path=PROJECT / "config" / "capability-seeds-v1.json",
        manifest_path=PROJECT / "SOURCE-MANIFEST.json",
    )


def current_context() -> dict[str, str]:
    path = PROJECT / "main.py"
    return {
        "object_id": "real-local-file-main",
        "source_path": "projects/gg-ai-desktop/main.py",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def route() -> object:
    return types.SimpleNamespace(
        intent="EDIT",
        route_mode="SOURCE_BOUND_LASER",
        primary_capability="tool.safe.dispatch",
        automatic_model_dispatch=False,
        registered_capability_execution=False,
        why="Verified capability action proposal fixture.",
    )


def d66b_native_missing_mandate_contract() -> None:
    registry = actual_registry()
    record = registry.get("tool.safe.dispatch")
    context = current_context()

    expect(
        record.contract["effect_class"] == "READ_ONLY_TOOL_EXECUTION",
        "actual safe-tool effect drift",
    )
    expect(
        record.contract["execution_authority"] == "CONTROLLED_PROFILE",
        "actual safe-tool execution profile drift",
    )
    expect(
        record.contract["risk_floor"] == "YELLOW",
        "actual safe-tool risk floor drift",
    )

    proposal = action_intent_contract.make_action_proposal(
        route_primary_capability="tool.safe.dispatch",
        capability_record=record,
        target_object_id=context["object_id"],
        target_source_revision=context["sha256"],
    )

    result = ingress.decide(
        user_text="Repair the verified current source.",
        workspace_context=context,
        route_decision=route(),
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
        action_proposal=proposal,
    )

    expect(result["decision_kind"] == "PLAN_ACTION", "PLAN_ACTION missing")
    expect(result["action_authority"] == "NONE", "Idékompass authority changed")
    expect(result["capability_execution"] == "NONE", "capability executed")

    intent = result["action_intent"]
    expect(intent is not None, "action intent missing")
    expect(intent["risk_floor"] == "YELLOW", "intent risk floor drift")
    expect(
        intent["capability_human_id"] == "tool.safe.dispatch",
        "capability binding drift",
    )
    expect(
        intent["target_source_revision"] == context["sha256"],
        "target source binding drift",
    )

    policy = result["orchestrator_policy"]
    expect(policy["status"] == "VALIDATED", "policy did not validate")
    expect(
        policy["validated_task"]["risk_class"] == "YELLOW",
        "YELLOW risk did not propagate to policy",
    )

    mandate = result["orchestrator_mandate"]
    expect(mandate["status"] == "VALIDATED", "mandate request not validated")
    expect(
        mandate["mandate_requirement"] == "EXPLICIT_REQUIRED",
        "K7-K did not require explicit mandate",
    )
    expect(mandate["mandate_assertion_created"] is False, "assertion appeared")
    expect(mandate["capability_execution"] is False, "capability executed")
    expect(mandate["participant_execution"] is False, "participant executed")

    evaluated = evaluation_adapter.evaluate_not_required(mandate)
    expect(evaluated["status"] == "DEFERRED", "missing mandate did not defer")
    expect(
        evaluated["reason_code"] == "MANDATE_REQUIRED_VERIFIED",
        "missing mandate verification reason drift",
    )
    expect(evaluated["mandate_evaluated"] is True, "native evaluation missing")
    expect(
        evaluated["ordinary_chat_blocked"] is True,
        "explicit-required action did not block progression",
    )

    receipt = evaluated["evaluation_receipt"]
    expect(receipt is not None, "native K7-K receipt missing")
    expect(receipt["result"] == "MANDATE_REQUIRED", "K7-K result drift")
    expect(
        receipt["reason_code"] == "EXPLICIT_MANDATE_MISSING",
        "K7-K reason drift",
    )
    expect(
        receipt["mandate_assertion_sha256"] is None,
        "unexpected assertion hash",
    )

    print("D66B0_ACTION_PROPOSAL_INTENT=PASS")
    print("D66B1_CAPABILITY_BINDING_CORE=PASS")
    print("D66B2_RISK_DERIVATION=PASS")
    print("D66B3_EXPLICIT_REQUIRED_PROPAGATION=PASS")
    print("NATIVE_MISSING_MANDATE_PROOF=PASS")
    print("MANDATE_RESULT=MANDATE_REQUIRED")
    print("MANDATE_REASON=EXPLICIT_MANDATE_MISSING")
    print("MANDATE_ASSERTION_CREATED=NO")
    print("CONTROLLED_TOOL_EXECUTION=NO")
    print("PARTICIPANT_EXECUTION=NO")
    print("ACTION_AUTHORITY_CHANGE=NONE")


def main() -> None:
    d66b_native_missing_mandate_contract()


if __name__ == "__main__":
    main()
