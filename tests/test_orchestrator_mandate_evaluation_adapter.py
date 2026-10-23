from __future__ import annotations

import hashlib
from pathlib import Path
import types

from backend import idekompass_decision_ingress as ingress
from backend import orchestrator_mandate_evaluation_adapter as evaluation_adapter


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


def current_green_contract() -> None:
    result = ingress.decide(
        user_text="Repair the verified current source.",
        workspace_context=workspace_context(),
        route_decision=route(),
        information_available=True,
        assigned_participant="GG-AI-installator",
        creator_actor="human:owner",
    )

    expect(result["decision_kind"] == "PLAN_ACTION", "PLAN_ACTION missing")
    expect(
        result["revalidation_result"] == "REVALIDATED",
        "PLAN_ACTION did not revalidate",
    )

    mandate = result["orchestrator_mandate"]
    expect(mandate["status"] == "VALIDATED", "D65 request not validated")
    expect(
        mandate["mandate_requirement"] == "NOT_REQUIRED",
        "current GREEN request requirement drift",
    )

    evaluation = evaluation_adapter.evaluate_not_required(mandate)
    expect(
        evaluation["status"] == "EVALUATED",
        "D66A evaluation failed: " + repr(evaluation),
    )
    expect(
        evaluation["reason_code"] == "MANDATE_NOT_REQUIRED_VERIFIED",
        "D66A outer reason drift",
    )
    receipt = evaluation["evaluation_receipt"]
    expect(isinstance(receipt, dict), "native evaluation receipt missing")
    expect(
        receipt["result"] == "MANDATE_NOT_REQUIRED",
        "native result drift",
    )
    expect(
        receipt["reason_code"] == "GREEN_RISK_CLASS",
        "native reason drift",
    )
    expect(
        receipt["request_capture_sha256"]
        == mandate["request_capture_sha256"],
        "request capture continuity failed",
    )
    expect(
        receipt["approval_scope_revision"]
        == mandate["approval_request"]["approval_scope_revision"],
        "approval scope continuity failed",
    )
    expect(
        receipt["current_approval_scope_revision"]
        == receipt["approval_scope_revision"],
        "current approval scope drift",
    )
    expect(
        receipt["mandate_assertion_sha256"] is None,
        "unexpected assertion hash",
    )
    expect(evaluation["mandate_assertion_created"] is False, "assertion appeared")
    expect(evaluation["mandate_evaluated"] is True, "evaluation marker missing")
    expect(evaluation["capability_execution"] is False, "capability executed")
    expect(evaluation["participant_execution"] is False, "participant executed")
    expect(evaluation["ordinary_chat_blocked"] is False, "GREEN chat blocked")
    expect(evaluation["action_authority"] == "NONE", "authority expanded")
    expect(evaluation["network"] is False, "network authority appeared")
    expect(evaluation["runtime_write"] is False, "runtime write appeared")


def nonplan_contract() -> None:
    result = ingress.decide(
        user_text="Inspect the verified current source.",
        workspace_context=workspace_context(),
        route_decision=None,
        information_available=True,
    )
    expect(
        result["decision_kind"] == "GATHER_INFORMATION",
        "fixture decision drift",
    )
    evaluation = evaluation_adapter.evaluate_not_required(
        result["orchestrator_mandate"]
    )
    expect(
        evaluation["status"] == "NOT_APPLICABLE",
        "non-plan evaluation should be not applicable",
    )
    expect(
        evaluation["mandate_evaluated"] is False,
        "non-plan evaluated mandate",
    )
    expect(
        evaluation["ordinary_chat_blocked"] is False,
        "non-plan ordinary chat blocked",
    )
    expect(evaluation["action_authority"] == "NONE", "authority expanded")


def static_authority_contract() -> None:
    import ast as _ast
    import inspect as _inspect

    module_source = Path(evaluation_adapter.__file__).read_text(
        encoding="utf-8",
        errors="strict",
    )
    tree = _ast.parse(module_source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, _ast.FunctionDef)
    }

    for required_name in (
        "evaluate_not_required",
        "evaluate_explicit_approval",
    ):
        expect(
            required_name in functions,
            "evaluation adapter function missing: " + required_name,
        )

    def call_names(node: _ast.AST) -> list[str]:
        output = []
        for child in _ast.walk(node):
            if not isinstance(child, _ast.Call):
                continue
            target = child.func
            if isinstance(target, _ast.Name):
                output.append(target.id)
            elif isinstance(target, _ast.Attribute):
                output.append(target.attr)
        return output

    not_required_calls = call_names(functions["evaluate_not_required"])
    explicit_calls = call_names(functions["evaluate_explicit_approval"])

    expect(
        not_required_calls.count("evaluate_mandate") == 1,
        "native no-assertion evaluation cardinality drift",
    )
    expect(
        "make_mandate_assertion" not in not_required_calls,
        "GREEN/missing-mandate path created assertion",
    )
    expect(
        explicit_calls.count("evaluate_not_required") == 1,
        "explicit baseline evaluation cardinality drift",
    )
    expect(
        explicit_calls.count("evaluate_mandate") == 1,
        "explicit native reevaluation cardinality drift",
    )

    explicit_source = _inspect.getsource(
        evaluation_adapter.evaluate_explicit_approval
    )
    expect(
        '"make_mandate_assertion"' in explicit_source,
        "explicit native assertion operation missing",
    )
    for token in (
        "gg_controlled_tool_execution",
        "subprocess",
        "socket",
        "autonomy_controller",
    ):
        expect(
            token not in explicit_source,
            "explicit approval crossed execution boundary: " + token,
        )



def main() -> None:
    static_authority_contract()
    current_green_contract()
    nonplan_contract()
    print("ORCHESTRATOR_MANDATE_EVALUATION_ADAPTER_TEST=PASS")
    print("CURRENT_GREEN_NATIVE_EVALUATION=PASS")
    print("MANDATE_RESULT=MANDATE_NOT_REQUIRED")
    print("MANDATE_REASON=GREEN_RISK_CLASS")
    print("MANDATE_ASSERTION_CREATED=NO")
    print("CONTROLLED_TOOL_EXECUTION=NO")
    print("PARTICIPANT_EXECUTION=NO")
    print("ACTION_AUTHORITY=NONE")


if __name__ == "__main__":
    main()
