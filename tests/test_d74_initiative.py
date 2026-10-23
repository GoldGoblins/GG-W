from __future__ import annotations

import ast
from pathlib import Path

from backend import idekompass_decision_ingress as idekompass
from backend import initiative_proposal as initiative


PROJECT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 64
SHA_B = "b" * 64


def expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(message)


def goal_chain() -> dict[str, object]:
    return {
        "schema": "gg.test.goal-chain.v1",
        "original_intent":
            "Keep the current task goal.",
        "goal":
            "Complete bounded D74 initiative discipline.",
        "why":
            "Propose useful next steps without authority expansion.",
    }


def candidate(
    candidate_id: str,
    *,
    kind: str,
    parent_goal_sha256: str,
    relevance: str,
    information_value: str = "NONE",
    risk_class: str = "GREEN",
    reversible: bool = True,
    cost_rank: str = "LOW",
    mandate_requirement: str = "NOT_REQUIRED",
    persistent_write: bool = False,
    network: bool = False,
    sudo: bool = False,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "description":
            "Candidate " + candidate_id,
        "kind": kind,
        "parent_goal_sha256":
            parent_goal_sha256,
        "relevance": relevance,
        "information_value":
            information_value,
        "risk_class": risk_class,
        "reversible": reversible,
        "cost_rank": cost_rank,
        "mandate_requirement":
            mandate_requirement,
        "persistent_write":
            persistent_write,
        "network": network,
        "sudo": sudo,
        "source": "D74_REGRESSION",
    }


def class_set_contract() -> None:
    expect(
        initiative.CLASSIFICATIONS
        == (
            "DO_NOW",
            "PROPOSE_TO_USER",
            "FUTURE_IMPROVEMENT",
            "IRRELEVANT_NOW",
        ),
        "initiative class set drift",
    )


def information_competes_with_action() -> None:
    chain = goal_chain()
    parent = (
        initiative.goal_chain_sha256(
            chain
        )
    )

    action = candidate(
        "action-first",
        kind="ACTION",
        parent_goal_sha256=parent,
        relevance="DIRECT",
        reversible=True,
    )

    information = candidate(
        "information-second",
        kind="INFORMATION",
        parent_goal_sha256=parent,
        relevance="BLOCKING",
        information_value="HIGH",
        reversible=True,
        cost_rank="LOW",
    )

    result = (
        initiative.classify_candidates(
            task_id="task-d74-t076",
            goal_chain=chain,
            state_base_revision=SHA_A,
            candidates=[
                action,
                information,
            ],
        )
    )

    classes = {
        item["candidate_id"]:
            item["classification"]
        for item in result[
            "proposals"
        ]
    }

    expect(
        classes["information-second"]
        == "DO_NOW",
        "high-value information did not classify DO_NOW",
    )
    expect(
        classes["action-first"]
        == "PROPOSE_TO_USER",
        "action proposal gained direct execution semantics",
    )
    expect(
        result["primary_proposal_id"]
        == "information-second",
        "information did not beat action",
    )
    expect(
        result["primary_classification"]
        == "DO_NOW",
        "primary classification drift",
    )
    expect(
        result["automatic_execution"]
        is False,
        "DO_NOW became execution permission",
    )


def initiative_sprawl_contract() -> None:
    chain = goal_chain()
    parent = (
        initiative.goal_chain_sha256(
            chain
        )
    )

    values = [
        candidate(
            "observe-now",
            kind="INFORMATION",
            parent_goal_sha256=parent,
            relevance="BLOCKING",
            information_value="HIGH",
            cost_rank="LOW",
        ),
        candidate(
            "ask-before-action",
            kind="ACTION",
            parent_goal_sha256=parent,
            relevance="DIRECT",
        ),
        candidate(
            "later-cleanup",
            kind="IMPROVEMENT",
            parent_goal_sha256=parent,
            relevance="OPTIONAL",
            information_value="LOW",
            cost_rank="MEDIUM",
        ),
        candidate(
            "unrelated-project",
            kind="IMPROVEMENT",
            parent_goal_sha256=parent,
            relevance="OUT_OF_SCOPE",
            information_value="LOW",
            cost_rank="HIGH",
        ),
    ]

    result = (
        initiative.classify_candidates(
            task_id="task-d74-t080",
            goal_chain=chain,
            state_base_revision=SHA_A,
            candidates=values,
        )
    )

    classes = {
        item["candidate_id"]:
            item["classification"]
        for item in result[
            "proposals"
        ]
    }

    expect(
        classes
        == {
            "observe-now":
                "DO_NOW",
            "ask-before-action":
                "PROPOSE_TO_USER",
            "later-cleanup":
                "FUTURE_IMPROVEMENT",
            "unrelated-project":
                "IRRELEVANT_NOW",
        },
        "T-080 initiative classification drift: "
        + repr(classes),
    )

    expect(
        result["task_creation"]
        is False,
        "initiative sprawl created tasks",
    )

    for proposal in result[
        "proposals"
    ]:
        expect(
            proposal["creates_task"]
            is False,
            "finding became a task",
        )
        expect(
            proposal[
                "automatic_execution"
            ]
            is False,
            "finding became execution",
        )


def mandate_creep_contract() -> None:
    chain = goal_chain()
    parent = (
        initiative.goal_chain_sha256(
            chain
        )
    )

    result = (
        initiative.classify_candidates(
            task_id="task-d74-t081",
            goal_chain=chain,
            state_base_revision=SHA_A,
            candidates=[
                candidate(
                    "network-better-way",
                    kind="IMPROVEMENT",
                    parent_goal_sha256=parent,
                    relevance="DIRECT",
                    information_value="MEDIUM",
                    risk_class="YELLOW",
                    reversible=False,
                    cost_rank="MEDIUM",
                    mandate_requirement="EXPLICIT_REQUIRED",
                    persistent_write=True,
                    network=True,
                )
            ],
        )
    )

    proposal = result[
        "proposals"
    ][0]

    expect(
        proposal["classification"]
        == "PROPOSE_TO_USER",
        "mandate creep was not reduced to proposal",
    )
    expect(
        proposal["automatic_execution"]
        is False,
        "mandate creep executed",
    )
    expect(
        result["action_authority"]
        == "NONE",
        "mandate creep expanded authority",
    )
    expect(
        result["network"] is False,
        "initiative layer gained network authority",
    )
    expect(
        result["persistent_write"]
        is False,
        "initiative layer gained write authority",
    )


def parent_goal_contract() -> None:
    chain = goal_chain()

    result = (
        initiative.classify_candidates(
            task_id="task-d74-parent",
            goal_chain=chain,
            state_base_revision=SHA_A,
            candidates=[
                candidate(
                    "stale-parent",
                    kind="IMPROVEMENT",
                    parent_goal_sha256=SHA_B,
                    relevance="DIRECT",
                )
            ],
        )
    )

    expect(
        result[
            "proposals"
        ][0]["classification"]
        == "IRRELEVANT_NOW",
        "parent-goal drift was promoted",
    )
    expect(
        result["task_creation"]
        is False,
        "parent-goal drift created task",
    )


def deterministic_binding_contract() -> None:
    chain = goal_chain()
    parent = (
        initiative.goal_chain_sha256(
            chain
        )
    )
    values = [
        candidate(
            "deterministic",
            kind="IMPROVEMENT",
            parent_goal_sha256=parent,
            relevance="OPTIONAL",
        )
    ]

    first = (
        initiative.classify_candidates(
            task_id="task-d74-deterministic",
            goal_chain=chain,
            state_base_revision=SHA_A,
            candidates=values,
        )
    )

    second = (
        initiative.classify_candidates(
            task_id="task-d74-deterministic",
            goal_chain=chain,
            state_base_revision=SHA_A,
            candidates=values,
        )
    )

    expect(
        first == second,
        "initiative binding is nondeterministic",
    )


def idekompass_runtime_contract() -> None:
    context = {
        "source_path":
            "qml/components/ContextComposer.qml",
        "object_id":
            "ws.file.context-composer",
        "sha256":
            SHA_B,
    }

    result = idekompass.decide(
        user_text=(
            "Inspect the current verified source "
            "and choose the safest useful next step."
        ),
        workspace_context=context,
        route_decision=None,
        information_available=True,
    )

    proposals = result.get(
        "initiative_proposals"
    )

    expect(
        isinstance(proposals, dict),
        "Idékompass did not produce initiative proposal set",
    )
    expect(
        proposals["schema"]
        == initiative.SET_SCHEMA,
        "Idékompass initiative schema drift",
    )
    expect(
        proposals[
            "state_base_revision"
        ]
        == result[
            "state_base"
        ][
            "state_base_revision"
        ],
        "initiative state-base binding drift",
    )
    expect(
        proposals[
            "parent_goal_sha256"
        ]
        == initiative.goal_chain_sha256(
            result["goal_chain"]
        ),
        "initiative parent goal binding drift",
    )
    expect(
        proposals["proposal_count"]
        >= 1,
        "information option did not become initiative proposal",
    )
    expect(
        proposals[
            "automatic_execution"
        ]
        is False,
        "Idékompass initiative auto-executed",
    )
    expect(
        proposals["task_creation"]
        is False,
        "Idékompass initiative created task",
    )
    expect(
        proposals["action_authority"]
        == "NONE",
        "Idékompass initiative expanded authority",
    )
    expect(
        proposals["capability_execution"]
        is False,
        "Idékompass initiative executed capability",
    )
    expect(
        proposals["participant_execution"]
        is False,
        "Idékompass initiative executed participant",
    )


def source_boundaries() -> None:
    initiative_path = Path(
        initiative.__file__
    ).resolve()

    source = initiative_path.read_text(
        encoding="utf-8",
        errors="strict",
    )

    for forbidden in (
        "subprocess",
        "PySide6",
        "safe_tool_runner",
        "write_runner",
        "QProcess",
        "shell=True",
    ):
        expect(
            forbidden not in source,
            "initiative layer gained runtime surface: "
            + forbidden,
        )

    idekompass_path = Path(
        idekompass.__file__
    ).resolve()

    idekompass_source = (
        idekompass_path.read_text(
            encoding="utf-8",
            errors="strict",
        )
    )

    tree = ast.parse(
        idekompass_source,
        filename=str(
            idekompass_path
        ),
    )

    calls = [
        node
        for node in ast.walk(tree)
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
            == "initiative_proposal"
            and node.func.attr
            == "derive_from_decision"
        )
    ]

    expect(
        len(calls) == 1,
        "initiative Idékompass contact cardinality drift",
    )

    main_source = (
        PROJECT / "main.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    main_tree = ast.parse(
        main_source,
        filename=str(
            PROJECT / "main.py"
        ),
    )

    builders = [
        node
        for node in main_tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "_build_workbench_machine_graph"
        )
    ]

    expect(
        len(builders) == 1,
        "machine graph builder cardinality drift",
    )

    graph_builder = builders[0]

    assignments = {}

    for node in graph_builder.body:
        if (
            isinstance(
                node,
                ast.Assign,
            )
            and len(node.targets) == 1
            and isinstance(
                node.targets[0],
                ast.Name,
            )
        ):
            assignments[
                node.targets[0].id
            ] = node.value

    def constant_tuple(
        node: ast.AST,
    ) -> tuple[object, ...] | None:
        if not isinstance(
            node,
            ast.Tuple,
        ):
            return None

        values = []

        for item in node.elts:
            if not isinstance(
                item,
                ast.Constant,
            ):
                return None

            values.append(
                item.value
            )

        return tuple(values)

    node_contracts = assignments.get(
        "node_contracts"
    )

    expect(
        isinstance(
            node_contracts,
            ast.Tuple,
        ),
        "machine graph node contracts drift",
    )

    initiative_nodes = []

    for item in node_contracts.elts:
        values = constant_tuple(
            item
        )

        if (
            values is not None
            and len(values) == 3
            and values[0]
            == "INITIATIVE_PROPOSAL"
        ):
            initiative_nodes.append(
                values
            )

    expect(
        initiative_nodes
        == [
            (
                "INITIATIVE_PROPOSAL",
                "backend.initiative_proposal",
                "STATELESS",
            )
        ],
        "initiative machine node drift: "
        + repr(initiative_nodes),
    )

    call_100 = []

    for value in assignments.values():
        if not isinstance(
            value,
            ast.Tuple,
        ):
            continue

        for item in value.elts:
            values = constant_tuple(
                item
            )

            if (
                values is not None
                and len(values) == 4
                and values[0]
                == "call-100"
            ):
                call_100.append(
                    values
                )

    expect(
        call_100
        == [
            (
                "call-100",
                "initiative_proposal.derive_from_decision",
                "IDEKOMPASS",
                "INITIATIVE_PROPOSAL",
            )
        ],
        "initiative machine call drift: "
        + repr(call_100),
    )


def main() -> None:
    class_set_contract()
    information_competes_with_action()
    initiative_sprawl_contract()
    mandate_creep_contract()
    parent_goal_contract()
    deterministic_binding_contract()
    idekompass_runtime_contract()
    source_boundaries()

    print("D74_CLASS_SET=PASS")
    print(
        "D74_T076_INFORMATION_COMPETES_WITH_ACTION=PASS"
    )
    print(
        "D74_T080_INITIATIVE_SPRAWL=PASS"
    )
    print(
        "D74_T081_MANDATE_CREEP=PASS"
    )
    print(
        "D74_PARENT_GOAL_DISCIPLINE=PASS"
    )
    print(
        "D74_DETERMINISTIC_BINDING=PASS"
    )
    print(
        "D74_IDEEKOMPASS_RUNTIME_WIRING=PASS"
    )
    print("D74_ACTION_AUTHORITY=NONE")
    print("D74_AUTOMATIC_EXECUTION=NO")
    print("D74_TASK_CREATION=NO")
    print("D74_MODEL_INFERENCE=NONE")
    print("D74_TEST=PASS")


if __name__ == "__main__":
    main()
