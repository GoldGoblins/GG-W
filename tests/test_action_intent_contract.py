from __future__ import annotations

import copy

from backend import action_intent_contract as contract


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def record() -> dict[str, object]:
    return {
        "human_id": "tool.safe.dispatch",
        "contract_sha256": SHA_A,
        "execution_revision_sha256": SHA_B,
        "metadata_sha256": SHA_C,
        "contract": {
            "effect_class": "READ_ONLY_TOOL_EXECUTION",
            "execution_authority": "CONTROLLED_PROFILE",
            "model_inference": False,
            "network": "NONE",
            "persistent_write": "RUNTIME_ONLY",
            "risk_floor": "YELLOW",
            "sudo": "NO",
        },
    }


def proposal_contract() -> None:
    first = contract.make_action_proposal(
        route_primary_capability="tool.safe.dispatch",
        capability_record=record(),
        target_object_id="ws.file.current",
        target_source_revision=SHA_D,
    )
    second = contract.make_action_proposal(
        route_primary_capability="tool.safe.dispatch",
        capability_record=record(),
        target_object_id="ws.file.current",
        target_source_revision=SHA_D,
    )

    expect(first == second, "proposal is not deterministic")
    expect(first["risk_floor"] == "YELLOW", "risk floor was lowered")
    expect(first["action_authority"] == "NONE", "authority appeared")

    try:
        contract.make_action_proposal(
            route_primary_capability="write.limited.apply",
            capability_record=record(),
            target_object_id="ws.file.current",
            target_source_revision=SHA_D,
        )
    except contract.ActionIntentContractError as exc:
        expect(
            str(exc) == "ROUTE_CAPABILITY_BINDING_MISMATCH",
            "route mismatch reason drift",
        )
    else:
        raise AssertionError("route mismatch was accepted")

    tampered = copy.deepcopy(first)
    tampered["risk_floor"] = "GREEN"
    try:
        contract.validate_action_proposal(tampered)
    except contract.ActionIntentContractError as exc:
        expect(
            str(exc) == "ACTION_PROPOSAL_BINDING_MISMATCH",
            "tamper reason drift",
        )
    else:
        raise AssertionError("risk-floor lowering survived binding")


def intent_contract() -> None:
    proposal = contract.make_action_proposal(
        route_primary_capability="tool.safe.dispatch",
        capability_record=record(),
        target_object_id="ws.file.current",
        target_source_revision=SHA_D,
    )
    intent = contract.bind_action_intent(
        action_proposal=proposal,
        task_id="task-1",
        origin_id="origin-1",
        state_base_revision=SHA_E,
        goal_chain_sha256=SHA_A,
        action_trace_sha256=SHA_B,
    )

    expect(
        intent["capability_action_node_id"].startswith(
            "capability-action-"
        ),
        "capability action identity missing",
    )
    expect(
        intent["proposal_binding_sha256"]
        == proposal["proposal_binding_sha256"],
        "proposal lineage lost",
    )
    expect(intent["risk_floor"] == "YELLOW", "intent risk drift")
    expect(intent["action_authority"] == "NONE", "intent authority appeared")

    tampered = copy.deepcopy(intent)
    tampered["target_source_revision"] = SHA_C
    try:
        contract.validate_action_intent(tampered)
    except contract.ActionIntentContractError as exc:
        expect(
            str(exc) == "ACTION_INTENT_BINDING_MISMATCH",
            "intent tamper reason drift",
        )
    else:
        raise AssertionError("intent target tamper survived binding")


def main() -> None:
    proposal_contract()
    intent_contract()
    print("ACTION_INTENT_CONTRACT_TEST=PASS")
    print("ACTION_AUTHORITY=NONE")
    print("RISK_FLOOR_LOWERING=BLOCKED")


if __name__ == "__main__":
    main()
