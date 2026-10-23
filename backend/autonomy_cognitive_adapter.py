#!/usr/bin/env python3
"""Content-bound adapter from Workbench Autonomy v1 into existing K7 cognition.

No cognitive semantics are reimplemented here. The adapter verifies and loads
the already published K7 modules, then delegates task envelope, ledger, belief,
Goal/WHY, hypothesis and state-revalidation operations to them.
"""

from __future__ import annotations
from backend.application_paths import resource_path
from backend.bound_source_platform import adapt_bound_sources, prepare_bound_namespace
from backend.platform_support import workspace_root

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from . import autonomy_contract as contract
except ImportError:
    import autonomy_contract as contract  # type: ignore

PROJECT = Path(__file__).resolve().parents[1]
REPO = workspace_root()
COGNITIVE_ROOT = resource_path("cognitive-core", workspace=REPO)

SOURCE_LOCK = {
    "gg_cognitive_contract.py":
        "e8824222fdb8f638f12c57f21a9b060f577e3a5ef5db8e034c9595677e03d79d",
    "gg_epistemic_ledger.py":
        "dd9b28b78bc6bff0770c544807dc56ab2791fee78eb5eb6aa14eb316a5a80be7",
    "gg_belief_view.py":
        "c3d754e8af0f7a05ab90190603ee1fcf410ab7add9096e7ef2ccb7ea570182b9",
    "gg_goal_why.py":
        "05a83a935273b106ad811aac3bb31c80eaf2bd3b444d2be855486899ad591ae6",
    "gg_hypothesis_protocol.py":
        "fa5abef6f8f87deeda8e9e083d067611b18b0038b07d040ef1363582658fdac3",
    "gg_state_revalidation.py":
        "8a58a8b7077ac977c035225f182d46c7efb9c842f357b80be9618e6caa0ee548",
    "gg_mandate_approval.py":
        "896b9f33da2ef8855d811da57aeb6db2bf6591bf3da3568ab1ddc5126aeac133",
    "gg_memory_discipline.py":
        "ba9cf88bc2be1283b6aae02603868d0fb5b2f64308d1b2def9678ee0f03a824b",
}

REUSED_HIERARCHY = (
    "TASK_ENVELOPE",
    "EPISTEMIC_LEDGER",
    "BELIEF_VIEW",
    "GOAL_WHY",
    "HYPOTHESIS_PROTOCOL",
    "STATE_REVALIDATION",
)
PARALLEL_AGENT_BRAIN = "FORBIDDEN"
FLAT_MODEL_COMMAND_LOOP = "FORBIDDEN"


class CognitiveAdapterError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str) -> ModuleType:
    expected = SOURCE_LOCK[name]
    path = COGNITIVE_ROOT / name
    if path.is_symlink() or not path.is_file():
        raise CognitiveAdapterError("COGNITIVE_SOURCE_INVALID:" + name)
    if _sha256(path) != expected:
        raise CognitiveAdapterError("COGNITIVE_SOURCE_SHA_DRIFT:" + name)

    module_name = "_gg_autonomy_bound_" + name.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise CognitiveAdapterError("COGNITIVE_IMPORT_SPEC_FAILED:" + name)
    module = importlib.util.module_from_spec(spec)
    prepare_bound_namespace(module.__dict__)
    spec.loader.exec_module(module)
    return adapt_bound_sources(module)


def load_stack() -> dict[str, ModuleType]:
    return {
        "task": _load("gg_cognitive_contract.py"),
        "ledger": _load("gg_epistemic_ledger.py"),
        "belief": _load("gg_belief_view.py"),
        "goal": _load("gg_goal_why.py"),
        "hypothesis": _load("gg_hypothesis_protocol.py"),
        "state": _load("gg_state_revalidation.py"),
    }


def make_task_context(
    grant: dict[str, Any],
    *,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    grant = contract.validate_grant(grant)
    stack = load_stack() if stack is None else stack
    task = stack["task"]
    goal = stack["goal"]

    intake = {
        "schema": task.SCHEMA_ID,
        "task_id": grant["task_id"],
        "origin_id": grant["session_id"],
        "state": "INTAKE",
        "original_expression": grant["goal"],
        "current_interpretation": None,
        "ready_core": None,
    }
    task.validate_envelope(intake)

    ready = {
        "schema": task.SCHEMA_ID,
        "task_id": grant["task_id"],
        "origin_id": grant["session_id"],
        "state": "READY_FOR_CONTROL",
        "original_expression": grant["goal"],
        "current_interpretation": (
            "Task-bunden autonom kandidat-reparation av verifierad @current-fil; "
            "host-write kräver separat Limited Write approval."
        ),
        "ready_core": {
            "owner": "GG",
            "goal": grant["goal"],
            "expected_value": (
                "Verifierat kandidat-changeset med spårbar kognitiv loop utan "
                "host-write före separat approval."
            ),
            "scope": [
                grant["workspace_object_id"],
                "task-bound candidate workspace",
                "GREEN Safe Tools",
                "local model semantic proposal",
                "QML Gate",
            ],
            "forbidden_scope": [
                "network",
                "general action authority",
                "arbitrary path",
                "shell",
                "git mutation",
                "host write before separate approval",
                "self authorization",
                "authority-file mutation",
            ],
            "risk_class": "YELLOW",
            "stop_conditions": [
                "base HEAD drift",
                "repository dirty before proposal",
                "grant mismatch or replay",
                "step/model/write limit",
                "state revalidation conflict",
                "unresolved uncertainty",
                "unexpected target or authority expansion",
            ],
            "expected_artifacts": [
                "task envelope",
                "Goal/WHY chain",
                "epistemic ledger",
                "belief view",
                "hypothesis state",
                "state revalidation result",
                "verified changeset",
            ],
            "acceptance_criteria": [
                "ORIGINAL_INTENT preserved",
                "WHY trace to controlled action",
                "GREEN observation before candidate action",
                "state revalidation before candidate action",
                "host repo unchanged before separate approval",
                "QML Gate PASS for final candidate",
                "verified changeset bound to base HEAD and target SHA",
            ],
        },
    }
    task.validate_envelope(ready)
    task.validate_transition(intake, ready)

    source = goal._validated_source(ready)

    root = goal.make_node(
        node_type="ORIGINAL_INTENT",
        parent_node_id=None,
        why=None,
        body={"statement": grant["goal"]},
    )
    current = goal.make_node(
        node_type="CURRENT_TARGET",
        parent_node_id=root["node_id"],
        why="För att operationalisera ORIGINAL_INTENT mot exakt verifierad @current.",
        body={
            "statement": (
                grant["workspace_object_id"]
                + " → "
                + grant["target_relative_path"]
            )
        },
    )
    goal_node = goal.make_node(
        node_type="GOAL",
        parent_node_id=current["node_id"],
        why="För att behålla användarens mål som aktiv WHY-rot under hela tasken.",
        body={"statement": grant["goal"]},
    )
    subgoal_node = goal.make_node(
        node_type="SUBGOAL",
        parent_node_id=goal_node["node_id"],
        why=(
            "För att bryta ned GOAL till minsta verifierbara delmål "
            "utan scope- eller authority-expansion."
        ),
        body={
            "statement": (
                "Ta fram och verifiera ett task-bound kandidat-changeset för "
                + grant["target_relative_path"]
                + "; host-write förblir separat approval."
            )
        },
    )
    task_node = goal.make_node(
        node_type="TASK",
        parent_node_id=subgoal_node["node_id"],
        why="För att realisera delmålet i minsta avgränsade autonomi-task.",
        body={
            "task_id": grant["task_id"],
            "source_task_sha256": source["source_task_sha256"],
        },
    )

    action_specs = (
        ("observe-target", "Läs verifierad target med GREEN Safe Tool READ."),
        ("model-propose", "Begär en strikt semantisk reparationshypotes från lokal modell."),
        ("inspect-proposal", "Kontrollera exakt patch-precondition deterministiskt."),
        ("candidate-patch", "Applicera exakt replacement endast i task candidate workspace."),
        ("repair-candidate", "Reparera kandidat efter observerat verifieringsfel."),
        ("create-host-proposal", "Skapa befintlig Limited Write proposal utan host-write."),
        ("verify-host", "Observera verklig host-effekt efter separat approval."),
    )
    nodes = [root, current, goal_node, subgoal_node, task_node]
    actions: dict[str, str] = {}
    for action_id, description in action_specs:
        node = goal.make_node(
            node_type="ACTION",
            parent_node_id=task_node["node_id"],
            why="För att föra tasken mot DONE_WHEN inom uttryckligt mandat.",
            body={"action_id": action_id, "description": description},
        )
        nodes.append(node)
        actions[action_id] = node["node_id"]

    chain = goal.build_goal_why_chain(ready, nodes)

    return {
        "intake": intake,
        "envelope": ready,
        "goal_chain": chain,
        "actions": actions,
    }


def read_records(
    ledger_path: Path,
    *,
    stack: dict[str, ModuleType] | None = None,
) -> list[dict[str, Any]]:
    stack = load_stack() if stack is None else stack
    if not ledger_path.exists():
        return []
    return stack["ledger"].read_chain(ledger_path)


def append_claim(
    ledger_path: Path,
    *,
    task_id: str,
    origin_id: str,
    claim_key: str,
    statement: str,
    epistemic_class: str,
    source_kind: str,
    source_id: str,
    source_fingerprint: str,
    parent_entry_sha256s: list[str] | None = None,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    stack = load_stack() if stack is None else stack
    ledger = stack["ledger"]
    records = read_records(ledger_path, stack=stack)
    head = None if not records else records[-1]["entry_sha256"]
    candidate = ledger.make_claim_candidate(
        task_id=task_id,
        origin_id=origin_id,
        claim_key=claim_key,
        statement=statement,
        epistemic_class=epistemic_class,
        source_kind=source_kind,
        source_id=source_id,
        source_fingerprint=source_fingerprint,
        parent_entry_sha256s=parent_entry_sha256s,
    )
    return ledger.append_candidate(
        ledger_path,
        candidate,
        expected_head_sha256=head,
    )


def make_claim_candidate(
    *,
    task_id: str,
    origin_id: str,
    claim_key: str,
    statement: str,
    epistemic_class: str,
    source_kind: str,
    source_id: str,
    source_fingerprint: str,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    stack = load_stack() if stack is None else stack
    return stack["ledger"].make_claim_candidate(
        task_id=task_id,
        origin_id=origin_id,
        claim_key=claim_key,
        statement=statement,
        epistemic_class=epistemic_class,
        source_kind=source_kind,
        source_id=source_id,
        source_fingerprint=source_fingerprint,
    )



def append_prebuilt_candidate(
    ledger_path: Path,
    candidate: dict[str, Any],
    *,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    stack = load_stack() if stack is None else stack
    ledger = stack["ledger"]
    records = read_records(ledger_path, stack=stack)
    head = None if not records else records[-1]["entry_sha256"]
    return ledger.append_candidate(
        ledger_path,
        candidate,
        expected_head_sha256=head,
    )


def claim_ref(candidate: dict[str, Any]) -> dict[str, str]:
    body = candidate["body"]
    return {
        "claim_key": body["claim_key"],
        "claim_id": body["claim_id"],
    }


def make_binary_hypothesis_state(
    *,
    records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    envelope: dict[str, Any],
    pass_candidate: dict[str, Any],
    fail_candidate: dict[str, Any],
    pass_action_node_id: str,
    fail_action_node_id: str,
    pass_statement: str,
    fail_statement: str,
    information_description: str,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    stack = load_stack() if stack is None else stack
    hyp = stack["hypothesis"]

    pass_ref = claim_ref(pass_candidate)
    fail_ref = claim_ref(fail_candidate)

    pass_h = hyp.make_hypothesis(
        kind="HYPOTHESIS",
        statement=pass_statement,
        source_kind="DERIVATION",
        source_id="autonomy-controller",
        source_fingerprint=hashlib.sha256(pass_statement.encode("utf-8")).hexdigest(),
        support_refs=[pass_ref],
        falsifier_refs=[fail_ref],
        candidate_action_node_ids=[pass_action_node_id],
    )
    fail_h = hyp.make_hypothesis(
        kind="HYPOTHESIS",
        statement=fail_statement,
        source_kind="DERIVATION",
        source_id="autonomy-controller",
        source_fingerprint=hashlib.sha256(fail_statement.encode("utf-8")).hexdigest(),
        support_refs=[fail_ref],
        falsifier_refs=[pass_ref],
        candidate_action_node_ids=[fail_action_node_id],
    )
    option = hyp.make_information_option(
        kind="OBSERVE_MORE",
        description=information_description,
        cost_rank="LOW",
        discriminates_hypothesis_ids=[
            pass_h["hypothesis_id"],
            fail_h["hypothesis_id"],
        ],
    )

    return hyp.build_hypothesis_state(
        records,
        requested_claim_keys,
        goal_chain,
        envelope,
        [pass_h, fail_h],
        [option],
        "EXPLICIT_CLOSED_FOR_DECISION",
    )


def decision(
    state: dict[str, Any],
    records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    envelope: dict[str, Any],
    *,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    stack = load_stack() if stack is None else stack
    return stack["hypothesis"].select_next_step(
        state,
        records,
        requested_claim_keys,
        goal_chain,
        envelope,
    )


def make_and_revalidate_state(
    *,
    participant_id: str,
    records: list[dict[str, Any]],
    requested_claim_keys: list[str],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    envelope: dict[str, Any],
    stack: dict[str, ModuleType] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stack = load_stack() if stack is None else stack
    state = stack["state"]
    base = state.make_state_base(
        participant_id,
        records,
        requested_claim_keys,
        [],
        [],
        goal_chain,
        hypothesis_state,
        envelope,
    )
    result = state.revalidate_state_base(
        base,
        records,
        [],
        goal_chain,
        hypothesis_state,
        envelope,
    )
    return base, result


def trace_action(
    goal_chain: dict[str, Any],
    envelope: dict[str, Any],
    action_node_id: str,
    *,
    stack: dict[str, ModuleType] | None = None,
) -> dict[str, Any]:
    stack = load_stack() if stack is None else stack
    return stack["goal"].trace_action(
        goal_chain,
        envelope,
        action_node_id,
    )


def selftest() -> int:
    stack = load_stack()
    if set(stack) != {"task", "ledger", "belief", "goal", "hypothesis", "state"}:
        raise CognitiveAdapterError("STACK_SURFACE_INVALID")
    print("AUTONOMY_COGNITIVE_ADAPTER_SELFTEST=PASS")
    print("MUST_REUSE_EXISTING_COGNITIVE_HIERARCHY=YES")
    print("PARALLEL_AGENT_BRAIN=FORBIDDEN")
    print("FLAT_MODEL_COMMAND_LOOP=FORBIDDEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
