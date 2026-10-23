from __future__ import annotations

import copy
from pathlib import Path
import os
import tempfile
import types

from backend import action_intent_contract
from backend import capability_registry
from backend import idekompass_decision_ingress as ingress
from backend import orchestrator_mandate_evaluation_adapter as evaluation_adapter
import main as workbench


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
WORKSPACE_ID = "ws.file.context-composer"
CONTEXT_REFERENCE = "@current"


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def registry() -> capability_registry.CapabilityRegistry:
    return capability_registry.CapabilityRegistry.load(
        repo_root=REPO,
        project_root=PROJECT,
        seed_path=PROJECT / "config" / "capability-seeds-v1.json",
        manifest_path=PROJECT / "SOURCE-MANIFEST.json",
    )


def action_route(primary: str | None = "tool.safe.dispatch") -> object:
    return types.SimpleNamespace(
        intent="EDIT",
        route_mode="SOURCE_BOUND_LASER",
        primary_capability=primary,
        automatic_model_dispatch=False,
        registered_capability_execution=False,
        why="Explicit deterministic capability proposal test.",
    )


def fake_bridge(capability_registry_value: object) -> object:
    messages: list[tuple[object, ...]] = []
    ledger_tmp = tempfile.TemporaryDirectory(
        prefix="gg-d66b-task-ledger-",
        dir=Path("/run/user") / str(os.getuid()),
    )
    task_ledger = workbench.control_contract.TaskLedger(
        Path(ledger_tmp.name),
    )
    value = types.SimpleNamespace(
        _intent_capability_registry=capability_registry_value,
        _mandate_session_id="mandate-session-test-local-human",
        _pending_mandates={},
    )
    value._task_ledger = task_ledger
    value._task_ledger_tmp = ledger_tmp
    value._append = lambda *args: messages.append(args)
    value._messages = messages
    return value


def live_action_proposal_contract() -> tuple[
    object,
    dict[str, object],
    dict[str, object],
]:
    actual_registry = registry()
    workspace = workbench.resolve_workspace_context(WORKSPACE_ID)
    bridge = fake_bridge(actual_registry)

    no_primary = workbench.ChatBridge._natural_action_proposal(
        bridge,
        action_route(None),
        workspace,
    )
    expect(
        no_primary is None,
        "ordinary/model-fallback route became action proposal",
    )

    proposal = workbench.ChatBridge._natural_action_proposal(
        bridge,
        action_route(),
        workspace,
    )
    expect(isinstance(proposal, dict), "live bridge did not create action proposal")

    validated = action_intent_contract.validate_action_proposal(proposal)
    expect(
        validated["capability_human_id"] == "tool.safe.dispatch",
        "live capability binding drift",
    )
    expect(validated["risk_floor"] == "YELLOW", "live risk floor drift")
    expect(
        validated["target_object_id"] == workspace["object_id"],
        "live target object drift",
    )
    expect(
        validated["target_source_revision"] == workspace["sha256"],
        "live target source drift",
    )
    expect(
        validated["action_authority"] == "NONE",
        "action proposal expanded authority",
    )

    print("LIVE_ACTION_PROPOSAL_BRIDGE=PASS")
    print("ORDINARY_CHAT_PRIMARY_NONE=NO_ACTION_PROPOSAL")
    return bridge, workspace, proposal


def make_decision(
    workspace: dict[str, object],
    proposal: dict[str, object],
) -> dict[str, object]:
    return ingress.decide(
        user_text="Inspect the verified current workspace source.",
        workspace_context=workspace,
        route_decision=action_route(),
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
        action_proposal=proposal,
    )


def explicit_mandate_contract() -> None:
    bridge, workspace, proposal = live_action_proposal_contract()
    decision = make_decision(workspace, proposal)

    expect(decision["decision_kind"] == "PLAN_ACTION", "PLAN_ACTION missing")
    action_intent = decision["action_intent"]
    expect(isinstance(action_intent, dict), "bound action intent missing")
    expect(action_intent["risk_floor"] == "YELLOW", "bound action risk drift")

    mandate = decision["orchestrator_mandate"]
    expect(mandate["status"] == "VALIDATED", "live mandate request not validated")
    expect(
        mandate["mandate_requirement"] == "EXPLICIT_REQUIRED",
        "live YELLOW did not require explicit mandate",
    )

    missing = evaluation_adapter.evaluate_not_required(copy.deepcopy(mandate))
    expect(missing["status"] == "DEFERRED", "missing mandate did not defer")
    expect(
        missing["reason_code"] == "MANDATE_REQUIRED_VERIFIED",
        "missing mandate reason drift",
    )
    missing_receipt = missing["evaluation_receipt"]
    expect(missing_receipt["result"] == "MANDATE_REQUIRED", "native missing result drift")
    expect(
        missing_receipt["reason_code"] == "EXPLICIT_MANDATE_MISSING",
        "native missing reason drift",
    )

    pending_id = workbench.ChatBridge._capture_pending_mandate(
        bridge,
        mandate_result=mandate,
        action_intent=action_intent,
        user_text="Inspect the verified current workspace source.",
        route_decision=action_route(),
        context_reference=CONTEXT_REFERENCE,
        workspace_object_id=WORKSPACE_ID,
    )
    pending = bridge._pending_mandates[pending_id]
    expect(pending["status"] == "WAITING_APPROVAL", "pending state drift")
    expect(pending["mandate_result"] == mandate, "exact original mandate not preserved")
    expect(
        pending["evaluation_context"] == mandate["evaluation_context"],
        "exact evaluation context not preserved",
    )
    expect(pending["action_intent"] == action_intent, "pending action intent drift")
    approval_message = str(bridge._messages[-1][2])
    expect("Svara bara `ja`" in approval_message, "chat approval prompt missing")
    expect("REQUEST_CAPTURE_SHA256" not in approval_message, "request hash leaked to chat")
    expect("APPROVAL_SCOPE_REVISION" not in approval_message, "scope hash leaked to chat")
    expect("/approve-mandate" not in approval_message, "slash approval command leaked to chat")
    expect("/reject-mandate" not in approval_message, "slash rejection command leaked to chat")

    scope = str(pending["approval_scope_revision"])
    parsed = workbench.parse_mandate_command(
        "/approve-mandate " + pending_id + " " + scope + " human:owner"
    )
    expect(parsed is not None, "approve command not parsed")
    expect(parsed["approver_id"] == "human:owner", "human approver input drift")

    workbench.ChatBridge._submit_mandate(
        bridge,
        parsed,
        CONTEXT_REFERENCE,
        WORKSPACE_ID,
    )
    approved = bridge._pending_mandates[pending_id]
    expect(approved["status"] == "APPROVED_VALID", "approval state drift")
    receipt = approved["approval_receipt"]
    expect(isinstance(receipt, dict), "approval receipt missing")
    expect(receipt["result"] == "MANDATE_VALID", "explicit mandate result drift")
    expect(
        receipt["reason_code"] == "APPROVAL_SCOPE_MATCH",
        "approval scope match drift",
    )
    assertion_sha = receipt["mandate_assertion_sha256"]
    expect(
        isinstance(assertion_sha, str) and len(assertion_sha) == 64,
        "mandate assertion hash missing",
    )

    before_messages = len(bridge._messages)
    workbench.ChatBridge._submit_mandate(
        bridge,
        parsed,
        CONTEXT_REFERENCE,
        WORKSPACE_ID,
    )
    expect(
        bridge._pending_mandates[pending_id]["status"] == "APPROVED_VALID",
        "replay changed approved mandate state",
    )
    expect(
        len(bridge._messages) == before_messages + 1,
        "replay did not fail closed visibly",
    )

    print("D66B4_PENDING_EXACT_MANDATE=PASS")
    print("D66B5_EXPLICIT_HUMAN_COMMAND_INGRESS=PASS")
    print("D66B6_NATIVE_EXACT_REEVALUATION=PASS")
    print("MANDATE_RESULT=MANDATE_VALID")
    print("MANDATE_REASON=APPROVAL_SCOPE_MATCH")
    print("MANDATE_ASSERTION_CREATED=YES")
    print("MANDATE_ASSERTION_SHA256=" + assertion_sha)


def reject_and_stale_contracts() -> None:
    actual_registry = registry()
    workspace = workbench.resolve_workspace_context(WORKSPACE_ID)
    proposal_bridge = fake_bridge(actual_registry)
    proposal = workbench.ChatBridge._natural_action_proposal(
        proposal_bridge,
        action_route(),
        workspace,
    )
    decision = make_decision(workspace, proposal)
    mandate = decision["orchestrator_mandate"]
    intent = decision["action_intent"]

    reject_bridge = fake_bridge(actual_registry)
    reject_id = workbench.ChatBridge._capture_pending_mandate(
        reject_bridge,
        mandate_result=mandate,
        action_intent=intent,
        user_text="Reject this action.",
        route_decision=action_route(),
        context_reference=CONTEXT_REFERENCE,
        workspace_object_id=WORKSPACE_ID,
    )
    reject_pending = reject_bridge._pending_mandates[reject_id]
    reject_scope = str(reject_pending["approval_scope_revision"])
    reject_parsed = workbench.parse_mandate_command(
        "/reject-mandate " + reject_id + " " + reject_scope
    )
    expect(reject_parsed is not None, "reject command not parsed")
    workbench.ChatBridge._submit_mandate(
        reject_bridge,
        reject_parsed,
        CONTEXT_REFERENCE,
        WORKSPACE_ID,
    )
    expect(
        reject_bridge._pending_mandates[reject_id]["status"] == "REJECTED",
        "human reject did not terminate pending mandate",
    )
    expect(
        reject_bridge._pending_mandates[reject_id]["mandate_assertion_sha256"] is None,
        "rejection created mandate assertion",
    )

    stale_bridge = fake_bridge(actual_registry)
    stale_id = workbench.ChatBridge._capture_pending_mandate(
        stale_bridge,
        mandate_result=mandate,
        action_intent=intent,
        user_text="Stale test.",
        route_decision=action_route(),
        context_reference=CONTEXT_REFERENCE,
        workspace_object_id=WORKSPACE_ID,
    )
    stale_pending = stale_bridge._pending_mandates[stale_id]
    stale_pending["manifest_sha256"] = "0" * 64
    stale_parsed = workbench.parse_mandate_command(
        "/approve-mandate "
        + stale_id
        + " "
        + str(stale_pending["approval_scope_revision"])
        + " human:owner"
    )
    workbench.ChatBridge._submit_mandate(
        stale_bridge,
        stale_parsed,
        CONTEXT_REFERENCE,
        WORKSPACE_ID,
    )
    expect(
        stale_bridge._pending_mandates[stale_id]["status"] == "BLOCKED_STALE",
        "stale manifest did not invalidate mandate",
    )
    expect(
        stale_bridge._pending_mandates[stale_id]["mandate_assertion_sha256"] is None,
        "stale mandate created assertion",
    )

    print("MANDATE_REJECT_NO_ASSERTION=PASS")
    print("MANDATE_STALE_INVALIDATION=PASS")


def static_live_wiring_contract() -> None:
    import ast as _ast

    main_source = Path(workbench.__file__).read_text(
        encoding="utf-8",
        errors="strict",
    )
    expect(
        main_source.count("from backend import action_intent_contract") == 1,
        "Action Intent import cardinality drift",
    )
    expect(
        main_source.count("action_proposal=action_proposal,") == 1,
        "submit did not pass action proposal exactly once",
    )

    tree = _ast.parse(main_source)
    bridge = next(
        node
        for node in tree.body
        if isinstance(node, _ast.ClassDef) and node.name == "ChatBridge"
    )
    methods = {
        node.name: node
        for node in bridge.body
        if isinstance(node, _ast.FunctionDef)
    }
    for name in (
        "_natural_action_proposal",
        "_capture_pending_mandate",
        "_submit_mandate",
    ):
        expect(name in methods, "live bridge method missing: " + name)

    explicit_source = Path(evaluation_adapter.__file__).read_text(
        encoding="utf-8",
        errors="strict",
    )
    for forbidden in (
        "gg_controlled_tool_execution",
        "subprocess",
        "socket",
    ):
        expect(
            forbidden not in explicit_source,
            "evaluation adapter crossed D66B execution boundary: " + forbidden,
        )

    print("LIVE_WIRING_STATIC_CONTRACT=PASS")
    print("K7_L_EXECUTION=NO")
    print("CAPABILITY_EXECUTION=NO")
    print("PARTICIPANT_EXECUTION=NO")
    print("ACTION_AUTHORITY_CHANGE=NONE")
    print("MODEL_INFERENCE=NONE")
    print("NETWORK=NONE")


def main() -> None:
    explicit_mandate_contract()
    reject_and_stale_contracts()
    static_live_wiring_contract()


if __name__ == "__main__":
    main()
