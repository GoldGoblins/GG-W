from __future__ import annotations

import ast
import copy
import hashlib
import importlib
from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]

project_string = str(PROJECT)
if project_string not in sys.path:
    sys.path.insert(0, project_string)

eligibility = importlib.import_module(
    "backend.action_execution_eligibility"
)
action_intent_contract = importlib.import_module(
    "backend.action_intent_contract"
)
capability_registry = importlib.import_module(
    "backend.capability_registry"
)
safe_tool_contract = importlib.import_module(
    "backend.safe_tool_contract"
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


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


def fixture() -> dict[str, object]:
    current_registry = registry()
    record = current_registry.get("tool.safe.dispatch")

    target_path = "qml/components/ContextComposer.qml"
    target_sha = hashlib.sha256(
        (PROJECT / target_path).read_bytes()
    ).hexdigest()

    proposal = action_intent_contract.make_action_proposal(
        route_primary_capability="tool.safe.dispatch",
        capability_record=record,
        target_object_id="ws.file.context-composer",
        target_source_revision=target_sha,
    )

    intent = action_intent_contract.bind_action_intent(
        action_proposal=proposal,
        task_id="task-d67",
        origin_id="origin-d67",
        state_base_revision=SHA_A,
        goal_chain_sha256=SHA_B,
        action_trace_sha256=SHA_C,
    )

    approval_request = {
        "task_id": intent["task_id"],
        "origin_id": intent["origin_id"],
        "approval_scope": {
            "ready_core": {
                "risk_class": "YELLOW",
                "scope": [],
            },
            "selected_action_node_id": SHA_D,
            "action_trace_sha256": intent["action_trace_sha256"],
            "state_base_revision": intent["state_base_revision"],
        },
        "approval_scope_revision": SHA_E,
        "request_capture_sha256": SHA_F,
    }

    assertion_sha = SHA_D

    receipt = {
        "schema": "gg.mandate-evaluation-result.v1",
        "request_capture_sha256": SHA_F,
        "approval_scope_revision": SHA_E,
        "current_approval_scope_revision": SHA_E,
        "mandate_assertion_sha256": assertion_sha,
        "result": "MANDATE_VALID",
        "reason_code": "APPROVAL_SCOPE_MATCH",
    }

    manifest_sha = hashlib.sha256(
        (PROJECT / "SOURCE-MANIFEST.json").read_bytes()
    ).hexdigest()

    return {
        "record": record,
        "target_path": target_path,
        "target_sha": target_sha,
        "intent": intent,
        "approval_request": approval_request,
        "assertion_sha": assertion_sha,
        "receipt": receipt,
        "manifest_sha": manifest_sha,
    }


def evaluate(
    value: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    kwargs = {
        "action_intent": value["intent"],
        "capability_record": value["record"],
        "approval_request": value["approval_request"],
        "approval_receipt": value["receipt"],
        "mandate_assertion_sha256": value["assertion_sha"],
        "current_manifest_sha256": value["manifest_sha"],
        "expected_manifest_sha256": value["manifest_sha"],
        "current_target_object_id": "ws.file.context-composer",
        "current_target_source_path": value["target_path"],
        "current_target_source_revision": value["target_sha"],
        "replay_state": "UNUSED",
    }
    kwargs.update(overrides)
    return eligibility.evaluate_execution_eligibility(**kwargs)


def expect_block(
    value: dict[str, object],
    reason: str,
    **overrides: object,
) -> None:
    decision = evaluate(value, **overrides)
    expect(
        decision["result"] == "EXECUTION_BLOCKED",
        "negative fixture became eligible: " + reason,
    )
    expect(
        decision["reason_code"] == reason,
        "block reason drift: "
        + str(decision["reason_code"])
        + " != "
        + reason,
    )
    expect(
        decision["safe_tool_request"] is None,
        "blocked decision exposed runnable safe-tool request",
    )
    expect(
        decision["capability_execution"] is False,
        "blocked decision executed capability",
    )


def positive_contract() -> None:
    value = fixture()

    first = evaluate(value)
    second = evaluate(value)

    expect(first == second, "eligibility decision is not deterministic")

    validated = eligibility.validate_execution_eligibility(first)

    expect(
        validated["result"] == "EXECUTION_ELIGIBLE",
        "exact action was not eligible",
    )
    expect(
        validated["reason_code"]
        == "EXACT_SAFE_TOOL_READ_REFINEMENT",
        "eligibility reason drift",
    )
    expect(
        validated["capability_human_id"] == "tool.safe.dispatch",
        "capability identity drift",
    )
    expect(
        validated["safe_tool_profile"] == safe_tool_contract.PROFILE_READ,
        "safe tool profile drift",
    )

    safe_request = safe_tool_contract.validate_request(
        validated["safe_tool_request"]
    )

    expect(
        validated["target_source_path"] == value["target_path"],
        "workspace target path drift",
    )

    expect(
        safe_request["arguments"]["path"]
        == "projects/gg-ai-desktop/" + value["target_path"],
        "safe READ repository path drift",
    )

    expect(
        validated["execution_persistent_write_authority"] == "NONE",
        "D67 gained persistent write authority",
    )
    expect(
        validated["action_authority"] == "NONE",
        "D67 gained action authority",
    )
    expect(
        validated["general_action_authority"] == "NONE",
        "D67 gained general authority",
    )
    expect(
        validated["capability_execution"] is False,
        "D67 executed capability",
    )
    expect(
        validated["k7_l_execution"] is False,
        "D67 executed K7-L",
    )
    expect(
        validated["participant_execution"] is False,
        "D67 executed participant",
    )
    expect(
        validated["network"] == "NONE",
        "D67 gained network authority",
    )
    expect(
        validated["sudo"] == "NO",
        "D67 gained sudo authority",
    )
    expect(
        validated["model_inference"] is False,
        "D67 invoked model inference",
    )

    print("D67_ELIGIBILITY_CONTRACT=PASS")
    print("D67_EXACT_CAPABILITY_BINDING=PASS")
    print("D67_TARGET_STATE_MANDATE_BINDING=PASS")
    print("D67_SAFE_TOOL_READ_REFINEMENT=PASS")


def negative_contracts() -> None:
    value = fixture()

    record_contract = copy.deepcopy(value["record"].as_dict())
    record_contract["contract_sha256"] = SHA_A
    expect_block(
        value,
        "CAPABILITY_CONTRACT_SHA_MISMATCH",
        capability_record=record_contract,
    )

    record_execution = copy.deepcopy(value["record"].as_dict())
    record_execution["execution_revision_sha256"] = SHA_A
    expect_block(
        value,
        "CAPABILITY_EXECUTION_REVISION_MISMATCH",
        capability_record=record_execution,
    )

    record_metadata = copy.deepcopy(value["record"].as_dict())
    record_metadata["metadata_sha256"] = SHA_A
    expect_block(
        value,
        "CAPABILITY_METADATA_SHA_MISMATCH",
        capability_record=record_metadata,
    )

    record_network = copy.deepcopy(value["record"].as_dict())
    record_network["contract"]["network"] = "FULL"
    expect_block(
        value,
        "CAPABILITY_CONTRACT_UNSUPPORTED:network",
        capability_record=record_network,
    )

    record_sudo = copy.deepcopy(value["record"].as_dict())
    record_sudo["contract"]["sudo"] = "YES"
    expect_block(
        value,
        "CAPABILITY_CONTRACT_UNSUPPORTED:sudo",
        capability_record=record_sudo,
    )

    record_model = copy.deepcopy(value["record"].as_dict())
    record_model["contract"]["model_inference"] = True
    expect_block(
        value,
        "CAPABILITY_CONTRACT_UNSUPPORTED:model_inference",
        capability_record=record_model,
    )

    expect_block(
        value,
        "TARGET_OBJECT_ID_MISMATCH",
        current_target_object_id="ws.file.other",
    )

    expect_block(
        value,
        "TARGET_SOURCE_REVISION_MISMATCH",
        current_target_source_revision=SHA_A,
    )

    expect_block(
        value,
        "MANIFEST_REVISION_MISMATCH",
        current_manifest_sha256=SHA_A,
    )

    stale_request = copy.deepcopy(value["approval_request"])
    stale_request["approval_scope"]["state_base_revision"] = SHA_B
    expect_block(
        value,
        "APPROVAL_STATE_BASE_MISMATCH",
        approval_request=stale_request,
    )

    trace_request = copy.deepcopy(value["approval_request"])
    trace_request["approval_scope"]["action_trace_sha256"] = SHA_B
    expect_block(
        value,
        "APPROVAL_ACTION_TRACE_MISMATCH",
        approval_request=trace_request,
    )

    risk_request = copy.deepcopy(value["approval_request"])
    risk_request["approval_scope"]["ready_core"]["risk_class"] = "GREEN"
    expect_block(
        value,
        "APPROVAL_RISK_MISMATCH",
        approval_request=risk_request,
    )

    bad_receipt = copy.deepcopy(value["receipt"])
    bad_receipt["result"] = "MANDATE_REQUIRED"
    expect_block(
        value,
        "MANDATE_RESULT_INVALID",
        approval_receipt=bad_receipt,
    )

    bad_reason = copy.deepcopy(value["receipt"])
    bad_reason["reason_code"] = "EXPLICIT_MANDATE_MISSING"
    expect_block(
        value,
        "MANDATE_REASON_INVALID",
        approval_receipt=bad_reason,
    )

    bad_assertion = copy.deepcopy(value["receipt"])
    bad_assertion["mandate_assertion_sha256"] = SHA_B
    expect_block(
        value,
        "MANDATE_ASSERTION_MISMATCH",
        approval_receipt=bad_assertion,
    )

    expect_block(
        value,
        "REPLAY_STATE_INVALID",
        replay_state="USED",
    )

    print("D67_REPLAY_FORBIDDEN_EFFECTS=PASS")
    print("D67_CAPABILITY_EXECUTION=NO")
    print("D68_EXECUTION=NO")


def static_contract() -> None:
    module_path = PROJECT / "backend/action_execution_eligibility.py"
    adapter_path = PROJECT / "backend/action_execution_safe_tool_adapter.py"
    main_path = PROJECT / "main.py"

    module_source = module_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    adapter_source = adapter_path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    main_source = main_path.read_text(
        encoding="utf-8",
        errors="strict",
    )

    for forbidden in (
        "safe_tool_runner",
        "subprocess",
        "QProcess",
        "write_runner",
    ):
        expect(
            forbidden not in module_source,
            "eligibility module gained execution dependency: "
            + forbidden,
        )

    for forbidden in (
        "import subprocess",
        "from backend import write_runner",
        "shell=True",
    ):
        expect(
            forbidden not in adapter_source,
            "D68 adapter gained forbidden execution surface: "
            + forbidden,
        )

    expect(
        main_source.count(
            "from backend import action_execution_eligibility"
        )
        == 1,
        "D67 main import cardinality drift",
    )

    expect(
        main_source.count(
            "from backend import "
            "action_execution_safe_tool_adapter"
        )
        == 1,
        "D68 adapter import cardinality drift",
    )

    tree = ast.parse(main_source)

    bridge = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ChatBridge"
    ]

    expect(
        len(bridge) == 1,
        "ChatBridge cardinality drift",
    )

    submit_mandate = [
        node
        for node in bridge[0].body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_submit_mandate"
    ]

    expect(
        len(submit_mandate) == 1,
        "_submit_mandate cardinality drift",
    )

    eligibility_calls = [
        node
        for node in ast.walk(submit_mandate[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id
            == "action_execution_eligibility"
        and node.func.attr
            == "evaluate_execution_eligibility"
    ]

    expect(
        len(eligibility_calls) == 1,
        "D67 eligibility call cardinality drift",
    )

    expect(
        "D67 EXECUTION ELIGIBILITY: PASS"
        in main_source,
        "D67 visible eligibility receipt missing",
    )

    d68_submit = [
        node
        for node in bridge[0].body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_submit_eligible_tool"
    ]

    d68_finished = [
        node
        for node in bridge[0].body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_eligible_tool_finished"
    ]

    expect(
        len(d68_submit) == 1,
        "_submit_eligible_tool cardinality drift",
    )

    expect(
        len(d68_finished) == 1,
        "_eligible_tool_finished cardinality drift",
    )

    mandate_calls = [
        node
        for node in ast.walk(submit_mandate[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr == "_submit_eligible_tool"
    ]

    expect(
        len(mandate_calls) == 1,
        "D68 mandate dispatch call cardinality drift",
    )

    submit_wrapper_calls = [
        node
        for node in ast.walk(d68_submit[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id
            == "action_execution_safe_tool_adapter"
        and node.func.attr == "submit_eligible_tool"
    ]

    finished_wrapper_calls = [
        node
        for node in ast.walk(d68_finished[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id
            == "action_execution_safe_tool_adapter"
        and node.func.attr == "eligible_tool_finished"
    ]

    expect(
        len(submit_wrapper_calls) == 1,
        "D68 submit wrapper adapter call cardinality drift",
    )

    expect(
        len(finished_wrapper_calls) == 1,
        "D68 finish wrapper adapter call cardinality drift",
    )

    submit_wrapper_source = (
        ast.get_source_segment(
            main_source,
            d68_submit[0],
        )
        or ""
    )

    finished_wrapper_source = (
        ast.get_source_segment(
            main_source,
            d68_finished[0],
        )
        or ""
    )

    for forbidden in (
        "validate_execution_eligibility",
        "tool_contract.validate_request",
        "tool_contract.validate_response",
        '"--execute-tool"',
        '"CONSUMED_PASS"',
    ):
        expect(
            forbidden not in submit_wrapper_source
            and forbidden not in finished_wrapper_source,
            "D68 thin wrapper regained implementation marker: "
            + forbidden,
        )

    expect(
        "project=PROJECT" in submit_wrapper_source
        and "qprocess_type=QProcess" in submit_wrapper_source
        and "safe_tool_runner_path=SAFE_TOOL_RUNNER_PATH"
            in submit_wrapper_source
        and "resolve_workspace_context_fn=resolve_workspace_context"
            in submit_wrapper_source,
        "D68 submit dependency injection seam drift",
    )

    adapter_tree = ast.parse(
        adapter_source
    )

    adapter_submit = [
        node
        for node in adapter_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "submit_eligible_tool"
    ]

    adapter_finished = [
        node
        for node in adapter_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "eligible_tool_finished"
    ]

    expect(
        len(adapter_submit) == 1,
        "D68 adapter submit function cardinality drift",
    )

    expect(
        len(adapter_finished) == 1,
        "D68 adapter finish function cardinality drift",
    )

    submit_source = (
        ast.get_source_segment(
            adapter_source,
            adapter_submit[0],
        )
        or ""
    )

    finished_source = (
        ast.get_source_segment(
            adapter_source,
            adapter_finished[0],
        )
        or ""
    )

    def qualified_calls(
        node: ast.AST,
    ) -> set[str]:
        result: set[str] = set()

        for candidate in ast.walk(node):
            if not isinstance(
                candidate,
                ast.Call,
            ):
                continue

            func = candidate.func

            if not (
                isinstance(func, ast.Attribute)
                and isinstance(
                    func.value,
                    ast.Name,
                )
            ):
                continue

            result.add(
                func.value.id
                + "."
                + func.attr
            )

        return result

    submit_security_calls = qualified_calls(
        adapter_submit[0]
    )

    finish_security_calls = qualified_calls(
        adapter_finished[0]
    )

    for required in (
        "action_execution_eligibility."
        "validate_execution_eligibility",
        "tool_contract.validate_request",
        "tool_contract.canonical_request_json",
        "os.open",
        "os.fsync",
    ):
        expect(
            required in submit_security_calls,
            "D68 submit security call missing: "
            + required,
        )

    for required in (
        "action_execution_eligibility."
        "validate_execution_eligibility",
        "tool_contract.validate_request",
        "tool_contract.validate_response",
        "tool_contract.canonical_request_json",
        "tool_contract.canonical_response_json",
    ):
        expect(
            required in finish_security_calls,
            "D68 completion security call missing: "
            + required,
        )

    for marker in (
        "safe_tool_request",
        "safe_tool_request_sha256",
        "eligibility_binding_sha256",
        '"DISPATCHED"',
        "safe_tool_runner_path",
        '"--execute-tool"',
        "self._eligible_tool_finished",
        "request_path",
        "os.O_EXCL",
    ):
        expect(
            marker in submit_source,
            "D68 backend dispatch marker missing: "
            + marker,
        )

    for marker in (
        '"CONSUMED_PASS"',
        '"ACTION_EXECUTED"',
        '"actual_effect_verified": False',
        "tool_contract.validate_response",
        "tool_contract.canonical_response_json",
        "D69 LOCAL OBSERVER: APPLIED",
        "request.json",
        "response.json",
    ):
        expect(
            marker in finished_source,
            "D68 backend completion marker missing: "
            + marker,
        )

    expect(
        'request_id = "tool-" + uuid.uuid4().hex'
        not in submit_source,
        "D68 generated a replacement request id",
    )

    expect(
        '"execution_state": "UNUSED"'
        in main_source,
        "D68 replay owner missing",
    )

    expect(
        "D68 EXECUTION: STARTING - exact staged READ"
        in main_source,
        "D68 mandate transition receipt missing",
    )

    print("D68_BACKEND_EXTRACTION_WIRING=PASS")
    print("D68_BACKEND_SECURITY_INVARIANTS=PASS")
    print("D68_LIVE_STATIC_WIRING=PASS")
    print("D68_EXACT_STAGED_REQUEST_CONSUMER=PASS")
    print("D68_REPLAY_STATE_OWNER=PASS")
    print("D69_LOCAL_OBSERVER_WIRING=PASS")
    print("D67_LIVE_STATIC_WIRING=PASS")



def main() -> int:
    positive_contract()
    negative_contracts()
    static_contract()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
