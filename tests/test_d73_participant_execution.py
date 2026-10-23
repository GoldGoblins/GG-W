from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from backend import (
    idekompass_decision_ingress as idekompass,
)
from backend import participant_task_receiver as receiver


PROJECT = Path(__file__).resolve().parents[1]


def expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(message)


def context() -> dict[str, str]:
    return {
        "source_path":
            "qml/components/ContextComposer.qml",
        "object_id":
            "ws.file.context-composer",
        "sha256": "b" * 64,
    }


def result(
    participant: str = "GG-AI-installator",
    user_text: str = (
        "Inspect the verified current source "
        "without executing tools."
    ),
) -> dict[str, object]:
    return idekompass.decide(
        user_text=user_text,
        workspace_context=context(),
        route_decision=None,
        information_available=True,
        assigned_participant=participant,
        creator_actor="human:owner",
    )


def positive_contract() -> None:
    prepared = receiver.prepare_participant_execution(
        idekompass_result=result(),
        effective_prompt=(
            "Verified current prompt."
        ),
        user_text=(
            "Inspect the verified current source "
            "without executing tools."
        ),
        workspace_context=context(),
    )

    state = prepared["state"]
    accepted = state["accepted_task"]

    expect(
        accepted["schema"]
        == receiver.ACCEPTED_TASK_SCHEMA,
        "accepted task schema drift",
    )
    expect(
        accepted["assigned_participant"]
        == "GG-AI-installator",
        "participant identity drift",
    )
    expect(
        accepted["risk_class"] == "GREEN",
        "participant source task risk drift",
    )
    expect(
        accepted["participant_execution_class"]
        == "LOCAL_MODEL_COGNITIVE_ONLY",
        "execution class drift",
    )
    expect(
        accepted["action_authority"] == "NONE",
        "action authority expanded",
    )
    expect(
        accepted["model_output_as_evidence"]
        is False,
        "model output became evidence",
    )
    expect(
        accepted["forbidden_effects"][
            "capability_execution"
        ]
        is True,
        "capability execution not forbidden",
    )
    expect(
        len(prepared["prompt"])
        <= receiver.MAX_PROMPT_CHARS,
        "participant prompt budget exceeded",
    )
    expect(
        receiver.canonical_state_json(state)
        == json.dumps(
            state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "participant state canonicalization drift",
    )


def fail_closed_contracts() -> None:
    base = result()

    action = copy.deepcopy(base)
    action["action_intent"] = {
        "schema": "forbidden",
    }

    try:
        receiver.prepare_participant_execution(
            idekompass_result=action,
            effective_prompt="prompt",
            user_text="intent",
            workspace_context=context(),
        )
    except receiver.ParticipantTaskError as exc:
        expect(
            str(exc)
            == "PARTICIPANT_ACTION_INTENT_FORBIDDEN",
            "wrong action-intent failure",
        )
    else:
        raise AssertionError(
            "participant action intent passed"
        )

    stale = copy.deepcopy(base)
    stale["revalidation_result"] = "STALE"

    try:
        receiver.prepare_participant_execution(
            idekompass_result=stale,
            effective_prompt="prompt",
            user_text="intent",
            workspace_context=context(),
        )
    except receiver.ParticipantTaskError as exc:
        expect(
            str(exc)
            == "PARTICIPANT_STATE_NOT_REVALIDATED",
            "wrong stale-state failure",
        )
    else:
        raise AssertionError(
            "stale participant state passed"
        )

    original = (
        receiver
        .EXPECTED_INVENTORY_SHA256[
            "GG-AI-installator"
        ]
    )

    receiver.EXPECTED_INVENTORY_SHA256[
        "GG-AI-installator"
    ] = "0" * 64

    try:
        try:
            receiver.prepare_participant_execution(
                idekompass_result=base,
                effective_prompt="prompt",
                user_text="intent",
                workspace_context=context(),
            )
        except receiver.ParticipantTaskError as exc:
            expect(
                str(exc)
                == "PARTICIPANT_SOURCE_INVENTORY_DRIFT",
                "wrong package drift failure",
            )
        else:
            raise AssertionError(
                "participant package drift passed"
            )
    finally:
        receiver.EXPECTED_INVENTORY_SHA256[
            "GG-AI-installator"
        ] = original


def structured_result_contract() -> None:
    prepared = receiver.prepare_participant_execution(
        idekompass_result=result(),
        effective_prompt="Verified current prompt.",
        user_text=(
            "Inspect the verified current source "
            "without executing tools."
        ),
        workspace_context=context(),
    )

    state_json = receiver.canonical_state_json(
        prepared["state"]
    )

    response = {
        "schema":
            "gg.workbench.local-ai-response.v1",
        "request_id":
            "participant-test",
        "status": "PASS",
        "text":
            "GG_MODEL_RUNNER_OK bounded specialist result",
        "evidence": {},
    }

    with tempfile.TemporaryDirectory(
        prefix="gg-d73-result-test."
    ) as temporary:
        root = Path(temporary)

        final = receiver.finalize_participant_response(
            state_json=state_json,
            validated_response=response,
            answer="bounded specialist result",
            evidence_path=root,
        )

        expect(
            final["schema"]
            == receiver.RESULT_SCHEMA,
            "participant result schema drift",
        )
        expect(
            final["participant_execution"]
            is True,
            "participant execution not recorded",
        )
        expect(
            final["action_authority"] == "NONE",
            "participant gained action authority",
        )
        expect(
            final["capability_execution"]
            is False,
            "participant gained capability execution",
        )
        expect(
            final["model_output_as_evidence"]
            is False,
            "participant output became evidence",
        )
        expect(
            final["handoff_back"]["to_role"]
            == "orchestrator",
            "handoff-back target drift",
        )
        expect(
            (
                root
                / "participant-accepted-task.json"
            ).is_file(),
            "accepted task evidence missing",
        )
        expect(
            (
                root
                / "participant-result.json"
            ).is_file(),
            "participant result evidence missing",
        )


def two_specialist_continuity_contract() -> None:
    original_intent = (
        "Inspect the verified current source "
        "without executing tools."
    )

    first_prepared = receiver.prepare_participant_execution(
        idekompass_result=result(
            "GG-AI-installator",
            original_intent,
        ),
        effective_prompt="Verified current prompt.",
        user_text=original_intent,
        workspace_context=context(),
    )

    first_response = {
        "schema":
            "gg.workbench.local-ai-response.v1",
        "request_id":
            "participant-first",
        "status": "PASS",
        "text":
            "GG_MODEL_RUNNER_OK first specialist analysis",
        "evidence": {},
    }

    with tempfile.TemporaryDirectory(
        prefix="gg-d73-first-specialist."
    ) as temporary:
        first = receiver.finalize_participant_response(
            state_json=receiver.canonical_state_json(
                first_prepared["state"]
            ),
            validated_response=first_response,
            answer="first specialist analysis",
            evidence_path=Path(temporary),
        )

    first_accepted = first_prepared[
        "state"
    ]["accepted_task"]

    handoff = first["handoff_back"]

    expected_intent_sha = hashlib.sha256(
        original_intent.encode("utf-8")
    ).hexdigest()

    expect(
        handoff["original_intent"]
        == original_intent,
        "handoff-back lost original intent",
    )

    expect(
        handoff["original_intent_sha256"]
        == expected_intent_sha,
        "handoff-back original intent hash drift",
    )

    second_prepared = receiver.prepare_participant_execution(
        idekompass_result=result(
            "GG-Webmaster",
            original_intent,
        ),
        effective_prompt=(
            "Continue the same bounded task "
            "as the second specialist."
        ),
        user_text=original_intent,
        workspace_context=context(),
        prior_participant_result=first,
    )

    second = second_prepared[
        "state"
    ]["accepted_task"]

    expect(
        second["assigned_participant"]
        == "GG-Webmaster",
        "second specialist identity drift",
    )

    expect(
        second["task_id"]
        == first_accepted["task_id"],
        "same task changed task id across specialists",
    )

    expect(
        second["state_base_revision"]
        == first_accepted["state_base_revision"],
        "same task changed state base across specialists",
    )

    expect(
        second["original_intent"]
        == original_intent,
        "second specialist replaced original intent",
    )

    expect(
        second["original_intent_sha256"]
        == expected_intent_sha,
        "second specialist original intent hash drift",
    )

    expect(
        second[
            "continuity_from_participant_result_sha256"
        ]
        == first["binding_sha256"],
        "second specialist continuity provenance drift",
    )

    rendered_second = json.dumps(
        second,
        ensure_ascii=False,
        sort_keys=True,
    )

    expect(
        "first specialist analysis"
        not in rendered_second,
        "prior model output was laundered into next task",
    )

    expect(
        second["action_authority"]
        == "NONE",
        "second specialist gained action authority",
    )

    expect(
        second["model_output_as_evidence"]
        is False,
        "second specialist promoted model output to evidence",
    )

    changed_intent = (
        "Perform a materially different "
        "verified-source task."
    )

    changed_blocked = False

    try:
        receiver.prepare_participant_execution(
            idekompass_result=result(
                "GG-Webmaster",
                changed_intent,
            ),
            effective_prompt=changed_intent,
            user_text=changed_intent,
            workspace_context=context(),
            prior_participant_result=first,
        )
    except receiver.ParticipantTaskError as exc:
        expect(
            "PRIOR_HANDOFF_STATE_BASE_DRIFT"
            in str(exc),
            "changed task blocked for wrong reason: "
            + str(exc),
        )
        changed_blocked = True

    expect(
        changed_blocked,
        "changed task incorrectly reused prior participant result",
    )


def source_boundaries() -> None:
    source_path = Path(receiver.__file__).resolve()
    source = source_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    tree = ast.parse(
        source,
        filename=str(source_path),
    )

    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    for forbidden in (
        "subprocess",
        "PySide6",
    ):
        expect(
            forbidden not in imports,
            "receiver gained runtime launcher: "
            + forbidden,
        )

    for forbidden in (
        "safe_tool_runner",
        "write_runner",
        "action_execution_eligibility",
        "action_execution_safe_tool_adapter",
        "shell=True",
    ):
        expect(
            forbidden not in source,
            "receiver gained forbidden capability: "
            + forbidden,
        )

    main = (
        PROJECT / "main.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    main_tree = ast.parse(
        main,
        filename=str(
            PROJECT / "main.py"
        ),
    )

    def receiver_call_count(
        method_name: str,
    ) -> int:
        return sum(
            1
            for node in ast.walk(main_tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Attribute,
                )
                and isinstance(
                    node.func.value,
                    ast.Name,
                )
                and node.func.value.id
                == "participant_task_receiver"
                and node.func.attr
                == method_name
            )
        )

    expect(
        receiver_call_count(
            "prepare_participant_execution"
        )
        == 1,
        "main prepare contact drift",
    )
    expect(
        receiver_call_count(
            "finalize_participant_response"
        )
        == 1,
        "main result contact drift",
    )

    eligibility_path = (
        PROJECT
        / "backend"
        / "action_execution_eligibility.py"
    )
    eligibility_source = eligibility_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    eligibility_tree = ast.parse(
        eligibility_source,
        filename=str(eligibility_path),
    )

    validators = [
        node
        for node in eligibility_tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name
            == "validate_execution_eligibility"
        )
    ]

    expect(
        len(validators) == 1,
        "D67 validator cardinality drift",
    )

    validator = validators[0]
    participant_false_constants = 0
    authority_drift_loops = 0

    for node in ast.walk(validator):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(
                node.targets[0],
                ast.Name,
            )
            and node.targets[0].id == "constants"
            and isinstance(node.value, ast.Dict)
        ):
            for key, value in zip(
                node.value.keys,
                node.value.values,
                strict=True,
            ):
                if (
                    isinstance(key, ast.Constant)
                    and key.value
                    == "participant_execution"
                    and isinstance(
                        value,
                        ast.Constant,
                    )
                    and value.value is False
                ):
                    participant_false_constants += 1

        if not (
            isinstance(node, ast.For)
            and isinstance(
                node.target,
                ast.Tuple,
            )
            and len(
                node.target.elts
            ) == 2
            and all(
                isinstance(item, ast.Name)
                for item in node.target.elts
            )
            and [
                item.id
                for item in node.target.elts
            ]
            == [
                "field",
                "expected",
            ]
            and isinstance(node.iter, ast.Call)
            and isinstance(
                node.iter.func,
                ast.Attribute,
            )
            and isinstance(
                node.iter.func.value,
                ast.Name,
            )
            and node.iter.func.value.id
            == "constants"
            and node.iter.func.attr == "items"
        ):
            continue

        mismatch_compare = False
        drift_raise = False

        for child in ast.walk(node):
            if (
                isinstance(child, ast.Compare)
                and len(child.ops) == 1
                and isinstance(
                    child.ops[0],
                    ast.NotEq,
                )
                and len(
                    child.comparators
                ) == 1
                and isinstance(
                    child.left,
                    ast.Subscript,
                )
                and isinstance(
                    child.left.value,
                    ast.Name,
                )
                and child.left.value.id
                == "result"
                and isinstance(
                    child.left.slice,
                    ast.Name,
                )
                and child.left.slice.id
                == "field"
                and isinstance(
                    child.comparators[0],
                    ast.Name,
                )
                and child.comparators[0].id
                == "expected"
            ):
                mismatch_compare = True

            if not (
                isinstance(child, ast.Raise)
                and isinstance(
                    child.exc,
                    ast.Call,
                )
                and isinstance(
                    child.exc.func,
                    ast.Name,
                )
                and child.exc.func.id
                == "ActionExecutionEligibilityError"
                and len(child.exc.args) == 1
            ):
                continue

            argument = child.exc.args[0]

            if (
                isinstance(argument, ast.BinOp)
                and isinstance(
                    argument.op,
                    ast.Add,
                )
                and isinstance(
                    argument.left,
                    ast.Constant,
                )
                and argument.left.value
                == "ELIGIBILITY_AUTHORITY_DRIFT:"
                and isinstance(
                    argument.right,
                    ast.Name,
                )
                and argument.right.id
                == "field"
            ):
                drift_raise = True

        if mismatch_compare and drift_raise:
            authority_drift_loops += 1

    expect(
        participant_false_constants == 1,
        "D67 participant_execution=False lock drift",
    )
    expect(
        authority_drift_loops == 1,
        "D67 authority-drift rejection loop drift",
    )

    safe_path = (
        PROJECT
        / "backend"
        / "action_execution_safe_tool_adapter.py"
    )
    safe_source = safe_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    safe_tree = ast.parse(
        safe_source,
        filename=str(safe_path),
    )

    submitters = [
        node
        for node in safe_tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name
            == "submit_eligible_tool"
        )
    ]

    expect(
        len(submitters) == 1,
        "D68 submitter cardinality drift",
    )

    d68_participant_guards = 0

    for node in ast.walk(submitters[0]):
        if not isinstance(node, ast.If):
            continue

        participant_compare = False
        blocked_status = False
        contract_raise = False

        for child in ast.walk(node.test):
            if not (
                isinstance(child, ast.Compare)
                and len(child.ops) == 1
                and isinstance(
                    child.ops[0],
                    ast.IsNot,
                )
                and len(
                    child.comparators
                ) == 1
                and isinstance(
                    child.comparators[0],
                    ast.Constant,
                )
                and child.comparators[0].value
                is False
                and isinstance(
                    child.left,
                    ast.Call,
                )
                and isinstance(
                    child.left.func,
                    ast.Attribute,
                )
                and isinstance(
                    child.left.func.value,
                    ast.Name,
                )
                and child.left.func.value.id
                == "eligibility"
                and child.left.func.attr == "get"
                and len(
                    child.left.args
                ) == 1
                and isinstance(
                    child.left.args[0],
                    ast.Constant,
                )
                and child.left.args[0].value
                == "participant_execution"
            ):
                continue

            participant_compare = True

        for child in node.body:
            for nested in ast.walk(child):
                if (
                    isinstance(
                        nested,
                        ast.Assign,
                    )
                    and len(
                        nested.targets
                    ) == 1
                    and isinstance(
                        nested.targets[0],
                        ast.Subscript,
                    )
                    and isinstance(
                        nested.targets[0].value,
                        ast.Name,
                    )
                    and nested.targets[0].value.id
                    == "pending"
                    and isinstance(
                        nested.targets[0].slice,
                        ast.Constant,
                    )
                    and nested.targets[0].slice.value
                    == "status"
                    and isinstance(
                        nested.value,
                        ast.Constant,
                    )
                    and nested.value.value
                    == "BLOCKED_EXECUTION"
                ):
                    blocked_status = True

                if (
                    isinstance(
                        nested,
                        ast.Raise,
                    )
                    and isinstance(
                        nested.exc,
                        ast.Call,
                    )
                    and isinstance(
                        nested.exc.func,
                        ast.Name,
                    )
                    and nested.exc.func.id
                    == "RuntimeError"
                    and len(
                        nested.exc.args
                    ) == 1
                    and isinstance(
                        nested.exc.args[0],
                        ast.Constant,
                    )
                    and nested.exc.args[0].value
                    == "D68_ELIGIBILITY_CONTRACT_FAILED"
                ):
                    contract_raise = True

        if (
            participant_compare
            and blocked_status
            and contract_raise
        ):
            d68_participant_guards += 1

    expect(
        d68_participant_guards == 1,
        "D68 participant fail-closed guard drift",
    )


def main() -> None:
    positive_contract()
    fail_closed_contracts()
    structured_result_contract()
    two_specialist_continuity_contract()
    source_boundaries()

    print("D73_ACCEPTED_TASK_ENVELOPE=PASS")
    print("D73_PACKAGE_INVENTORY_BINDING=PASS")
    print("D73_FAIL_CLOSED_BOUNDARIES=PASS")
    print("D73_STRUCTURED_RESULT_HANDOFF_BACK=PASS")
    print("D73_T068_TWO_SPECIALIST_CONTINUITY=PASS")
    print("D73_T072_CHANGED_TASK_STATE_BASE_BLOCK=PASS")
    print("D73_PARTICIPANT_EXECUTION_CLASS=LOCAL_MODEL_COGNITIVE_ONLY")
    print("D73_ACTION_AUTHORITY=NONE")
    print("D73_TEST=PASS")


if __name__ == "__main__":
    main()
