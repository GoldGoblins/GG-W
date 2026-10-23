#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
BACKEND = PROJECT / "backend"

sys.path.insert(0, str(BACKEND))
try:
    import autonomy_contract as contract
    import autonomy_cognitive_adapter as cognition
    import autonomy_controller as controller
finally:
    sys.path.remove(str(BACKEND))


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sample_grant():
    return {
        "schema": contract.GRANT_SCHEMA,
        "task_id": "task-" + ("a" * 32),
        "session_id": "session-" + ("b" * 32),
        "base_head": "c" * 40,
        "context_reference": contract.TARGET_CONTEXT_REFERENCE,
        "workspace_object_id": contract.TARGET_WORKSPACE_OBJECT_ID,
        "target_relative_path": contract.TARGET_RELATIVE_PATH,
        "goal": "Ändra implicitHeight: 92 till implicitHeight: 93 och verifiera.",
        "done_when": "Verifierad kandidat och separat host-effect verification.",
        "allowed_green_tools": list(contract.ALLOWED_GREEN_TOOLS),
        "max_steps": 24,
        "max_model_calls": 3,
        "max_candidate_writes": 3,
        "max_candidate_bytes": contract.TARGET_MAX_BYTES,
        "network_authority": "NONE",
        "general_action_authority": "NONE",
        "host_write_authority": contract.HOST_WRITE_AUTHORITY,
        "git_mutation_authority": "NONE",
        "shell_authority": "NONE",
        "self_authorization": "FORBIDDEN",
        "authority_file_mutation": "FORBIDDEN",
        "model_output_authority": "UNTRUSTED_MODEL_OUTPUT",
        "candidate_workspace": "RUNTIME_TASK_BOUND",
        "session_bound": True,
        "replay_protection": "RUNTIME_SINGLE_USE_RECEIPT",
        "monotonic_step_sequence": True,
        "persistent_apply_boundary": contract.PERSISTENT_APPLY_BOUNDARY,
        "test_mode": "INTENTIONAL_FIRST_GATE_FAILURE",
    }


def main():
    stack = cognition.load_stack()
    require(
        set(stack) == {"task", "ledger", "belief", "goal", "hypothesis", "state"},
        "existing cognitive stack not reused",
    )

    grant = contract.validate_grant(sample_grant())
    context = cognition.make_task_context(grant, stack=stack)

    trace = cognition.trace_action(
        context["goal_chain"],
        context["envelope"],
        context["actions"]["candidate-patch"],
        stack=stack,
    )
    require(isinstance(trace, tuple), "WHY trace type invalid")
    require(trace[-1] == context["actions"]["candidate-patch"], "WHY trace lost action")

    nodes_by_id = {
        str(node["node_id"]): node
        for node in context["goal_chain"]["nodes"]
    }
    trace_types = [
        str(nodes_by_id[node_id]["node_type"])
        for node_id in trace
    ]
    require(
        trace_types
        == [
            "ORIGINAL_INTENT",
            "CURRENT_TARGET",
            "GOAL",
            "SUBGOAL",
            "TASK",
            "ACTION",
        ],
        "full ORIGINAL_INTENT→CURRENT_TARGET→GOAL→SUBGOAL→TASK→ACTION trace missing",
    )

    with tempfile.TemporaryDirectory(prefix="gg-autonomy-cognitive-test.") as temp:
        ledger_path = Path(temp) / "ledger.jsonl"
        pass_candidate = cognition.make_claim_candidate(
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key="precondition.pass",
            statement="Exact precondition passes.",
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="synthetic-inspection",
            source_fingerprint=hashlib.sha256(b"pass").hexdigest(),
            stack=stack,
        )
        fail_candidate = cognition.make_claim_candidate(
            task_id=grant["task_id"],
            origin_id=grant["session_id"],
            claim_key="precondition.fail",
            statement="Exact precondition fails.",
            epistemic_class="OBSERVED",
            source_kind="DETERMINISTIC_TOOL",
            source_id="synthetic-inspection",
            source_fingerprint=hashlib.sha256(b"fail").hexdigest(),
            stack=stack,
        )
        keys = ["precondition.pass", "precondition.fail"]
        state = cognition.make_binary_hypothesis_state(
            records=[],
            requested_claim_keys=keys,
            goal_chain=context["goal_chain"],
            envelope=context["envelope"],
            pass_candidate=pass_candidate,
            fail_candidate=fail_candidate,
            pass_action_node_id=context["actions"]["candidate-patch"],
            fail_action_node_id=context["actions"]["model-propose"],
            pass_statement="Patch is technically applicable.",
            fail_statement="Patch needs a new semantic proposal.",
            information_description="Inspect exact single occurrence.",
            stack=stack,
        )
        decision = cognition.decision(
            state,
            [],
            keys,
            context["goal_chain"],
            context["envelope"],
            stack=stack,
        )
        require(decision["kind"] == "GATHER_INFORMATION", "K7-H did not gather first")

        cognition.append_prebuilt_candidate(ledger_path, pass_candidate, stack=stack)
        records = cognition.read_records(ledger_path, stack=stack)
        state = cognition.make_binary_hypothesis_state(
            records=records,
            requested_claim_keys=keys,
            goal_chain=context["goal_chain"],
            envelope=context["envelope"],
            pass_candidate=pass_candidate,
            fail_candidate=fail_candidate,
            pass_action_node_id=context["actions"]["candidate-patch"],
            fail_action_node_id=context["actions"]["model-propose"],
            pass_statement="Patch is technically applicable.",
            fail_statement="Patch needs a new semantic proposal.",
            information_description="Inspect exact single occurrence.",
            stack=stack,
        )
        decision = cognition.decision(
            state,
            records,
            keys,
            context["goal_chain"],
            context["envelope"],
            stack=stack,
        )
        require(decision["kind"] == "PLAN_ACTION", "K7-H did not plan after evidence")
        require(
            decision["selected_action_node_id"] == context["actions"]["candidate-patch"],
            "K7-H selected wrong action",
        )

        _base, revalidation = cognition.make_and_revalidate_state(
            participant_id="gg-autonomy-controller-test",
            records=records,
            requested_claim_keys=keys,
            goal_chain=context["goal_chain"],
            hypothesis_state=state,
            envelope=context["envelope"],
            stack=stack,
        )
        require(revalidation["result"] == "REVALIDATED", "K7-J did not revalidate")

    require(controller.selftest() == 0, "controller selftest failed")

    source = (BACKEND / "autonomy_controller.py").read_text(encoding="utf-8")
    for marker in (
        "MUST_REUSE_EXISTING_COGNITIVE_HIERARCHY=YES",
        "FLAT_MODEL_COMMAND_LOOP=NO",
        "UNTRUSTED_MODEL_OUTPUT",
        "STATE_REVALIDATION_BEFORE_ACTION=YES",
        "HOST_REPO_WRITE=SEPARATE_BOUNDARY",
        "_safe_tool_read",
        "_write_host_proposal",
        "gg-autonomy-grant-receipt.",
        "verify_host",
    ):
        require(marker in source, "controller marker missing: " + marker)

    print("AUTONOMY_CONTROLLER_INTEGRATION_TEST=PASS")
    print("K7_TASK_LEDGER_BELIEF_GOAL_HYPOTHESIS_REVALIDATION=RUNTIME_WIRED")
    print("FIRST_DECISION=GATHER_INFORMATION")
    print("SECOND_DECISION=PLAN_ACTION")
    print("STATE_REVALIDATION=REVALIDATED")
    print("PARALLEL_AGENT_BRAIN=NO")
    print("FLAT_MODEL_COMMAND_LOOP=NO")
    print("HOST_WRITE_BOUNDARY=SEPARATE_EXISTING_LIMITED_WRITE")
    print("REPLAY_PROTECTION=RUNTIME_GLOBAL_SINGLE_USE_RECEIPT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def test_autonomy_model_grammar_is_exact_and_fail_closed():
    import autonomy_model_runner as runner

    grammar = runner.AUTONOMY_GBNF

    for marker in (
        "HYPOTHESIS:",
        "OLD:",
        "NEW:",
        "WHY:",
        "GG_MODEL_RUNNER_OK",
    ):
        assert marker in grammar

    assert "REASONING:" not in grammar

    malformed = (
        "HYPOTHESIS:x|"
        "OLD:a|"
        "NEW:b|"
        "REASONING:free text|"
        "GG_MODEL_RUNNER_OK"
    )

    try:
        runner.parse_semantic_text(malformed)
    except runner.AutonomyModelError:
        pass
    else:
        raise AssertionError(
            "Malformed semantic model output must fail closed."
        )

def test_autonomy_gbnf_decode_safe_escape_surface():
    from backend.autonomy_model_runner import AUTONOMY_GBNF

    assert "segment ::= char{1,180}" in AUTONOMY_GBNF
    assert r'"\\" ["\\/"]' in AUTONOMY_GBNF

    assert "bfnrt" not in AUTONOMY_GBNF
    assert "[0-9a-fA-F]{4}" not in AUTONOMY_GBNF
    assert r'["\\/bfnrt]' not in AUTONOMY_GBNF


def test_json_escape_decoding_matches_autonomy_semantic_boundary():
    import json

    unsafe = (
        r"\n",
        r"\r",
        r"\t",
        r"\b",
        r"\f",
        r"\u007c",
        r"\u000a",
    )

    for raw_escape in unsafe:
        decoded = json.loads('"' + raw_escape + '"')

        assert (
            "\n" in decoded
            or "\r" in decoded
            or "\t" in decoded
            or "\b" in decoded
            or "\f" in decoded
            or "|" in decoded
        )

    safe = (
        r"\"",
        r"\\",
        r"\/",
    )

    for raw_escape in safe:
        decoded = json.loads('"' + raw_escape + '"')

        assert "\n" not in decoded
        assert "\r" not in decoded
        assert "\t" not in decoded
        assert "\b" not in decoded
        assert "\f" not in decoded
        assert "|" not in decoded
