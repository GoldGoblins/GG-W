#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys
from typing import Any

PARTICIPANTS = (
    "GG-idekompassen",
    "GG-Metaarkitekt-gptskapare",
    "GG-Agentarkitekt-agentskapare",
    "GG-AI-installator",
    "GG-Webmaster",
    "GG-Content-Studio",
    "GG-Marknadsföring",
)

IDEKOMPASS_REQUIRED = (
    "task_id",
    "owner",
    "goal",
    "expected_value",
    "scope",
    "forbidden_scope",
    "risk_class",
    "stop_conditions",
    "expected_artifacts",
    "acceptance_criteria",
)

HANDOFF_REQUIRED = (
    "handoff_id",
    "from_role",
    "to_role",
    "task_id",
    "status",
    "artifacts",
    "risks",
    "next_action",
)

TASK_SCOPED_EFFECTS = (
    "network",
    "credentials",
    "production",
    "one_com",
    "merge",
    "deploy",
    "write",
    "sudo",
)

# These effects are available only through a current hash-bound
# TASK_SCOPED grant.  Unbounded background authority remains forbidden.
BLOCKED_EFFECTS = ("unbounded_background_autonomy",)

ALLOWED_HANDOFF_STATUS = {
    "PASS",
    "CONDITIONAL",
    "FAIL",
    "BLOCKED",
}


STATE_MACHINE = (
    "NEW",
    "IDEKOMPASS_REQUIRED",
    "TASK_ACCEPTED",
    "EXPLICIT_PARTICIPANT_ASSIGNED",
    "HANDOFF_READY",
    "EVIDENCE_REQUIRED",
    "CODE_GATE_REQUIRED",
    "CODE_GATE_PASS",
    "INDEPENDENT_REVIEW_REQUIRED",
    "ACCEPTED",
    "BLOCKED",
    "STOPPED_COMPLETE",
)

CODE_TASK_SUCCESS_TRACE = (
    "NEW",
    "IDEKOMPASS_REQUIRED",
    "TASK_ACCEPTED",
    "EXPLICIT_PARTICIPANT_ASSIGNED",
    "HANDOFF_READY",
    "EVIDENCE_REQUIRED",
    "CODE_GATE_REQUIRED",
    "CODE_GATE_PASS",
    "INDEPENDENT_REVIEW_REQUIRED",
    "ACCEPTED",
    "STOPPED_COMPLETE",
)

NONCODE_SUCCESS_TRACE = (
    "NEW",
    "IDEKOMPASS_REQUIRED",
    "TASK_ACCEPTED",
    "EXPLICIT_PARTICIPANT_ASSIGNED",
    "HANDOFF_READY",
    "EVIDENCE_REQUIRED",
    "INDEPENDENT_REVIEW_REQUIRED",
    "ACCEPTED",
    "STOPPED_COMPLETE",
)


class PolicyError(RuntimeError):
    pass


class KillSwitchStop(RuntimeError):
    pass


def require(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise PolicyError(message)


def load_json(
    path: pathlib.Path,
) -> dict[str, Any]:
    value = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    require(
        isinstance(
            value,
            dict,
        ),
        "object_required:"
        + path.name,
    )

    return value


def load_jsonl(
    path: pathlib.Path,
) -> list[dict[str, Any]]:
    rows: list[
        dict[str, Any]
    ] = []

    for line in path.read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue

        value = json.loads(
            line
        )

        require(
            isinstance(
                value,
                dict,
            ),
            "evidence_row_not_object",
        )

        rows.append(
            value
        )

    require(
        bool(rows),
        "evidence_empty",
    )

    return rows


def load_review(
    path: pathlib.Path,
) -> dict[str, Any]:
    result: dict[
        str,
        Any,
    ] = {}

    for raw in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()

        if (
            line.startswith("- ")
            and ":" in line
        ):
            key, value = (
                line[2:].split(
                    ":",
                    1,
                )
            )

            result[
                key.strip()
            ] = value.strip()

    bool_keys = (
        "source_hash_matches",
        "code_gate_hash_matches",
        "rights_expansion",
        "forbidden_effects",
    )

    for key in bool_keys:
        if key in result:
            require(
                result[key]
                in {
                    "true",
                    "false",
                },
                "review_bool_invalid:"
                + key,
            )

            result[key] = (
                result[key]
                == "true"
            )

    return result


def validate_task(
    task: dict[str, Any],
) -> None:
    for field in (
        IDEKOMPASS_REQUIRED
    ):
        require(
            field in task,
            "missing_idekompass_field:"
            + field,
        )

        value = task[
            field
        ]

        require(
            value
            not in (
                "",
                None,
                [],
                {},
            ),
            "empty_idekompass_field:"
            + field,
        )

    require(
        task.get(
            "first_gate"
        )
        == "idekompassen-2.0",
        "idekompass_not_first",
    )

    participant = (
        task.get(
            "assigned_participant"
        )
    )

    require(
        participant
        in PARTICIPANTS,
        "unknown_participant",
    )

    require(
        "verified_context"
        in task,
        "verified_context_missing",
    )

    require(
        "historical_context"
        in task,
        "historical_context_missing",
    )

    require(
        isinstance(
            task[
                "verified_context"
            ],
            dict,
        ),
        "verified_context_not_object",
    )

    require(
        isinstance(
            task[
                "historical_context"
            ],
            dict,
        ),
        "historical_context_not_object",
    )

    require(
        task.get(
            "rights_expansion"
        )
        is not True,
        "rights_expansion",
    )

    effects = task.get(
        "requested_effects",
        {},
    )

    require(
        isinstance(
            effects,
            dict,
        ),
        "requested_effects_not_object",
    )

    for effect in (
        BLOCKED_EFFECTS
    ):
        require(
            effects.get(
                effect
            )
            is not True,
            "forbidden_effect:"
            + effect,
        )


def validate_handoff(
    handoff: dict[str, Any],
    task: dict[str, Any],
) -> None:
    for field in (
        HANDOFF_REQUIRED
    ):
        require(
            field in handoff,
            "missing_handoff_field:"
            + field,
        )

    status = handoff[
        "status"
    ]

    require(
        status
        in ALLOWED_HANDOFF_STATUS,
        "handoff_status_invalid",
    )

    require(
        status == "PASS",
        "handoff_not_pass:"
        + str(status),
    )

    require(
        handoff[
            "task_id"
        ]
        == task[
            "task_id"
        ],
        "handoff_task_mismatch",
    )

    require(
        handoff[
            "to_role"
        ]
        == task[
            "assigned_participant"
        ],
        "handoff_target_mismatch",
    )


def validate_gate(
    gate: dict[str, Any],
    code_task: bool,
) -> None:
    if code_task:
        require(
            gate.get(
                "status"
            )
            == "PASS",
            "code_gate_not_pass",
        )


def validate_review(
    review: dict[str, Any],
    creator_actor: str,
    code_task: bool,
) -> None:
    reviewer = (
        review.get(
            "reviewer_actor"
        )
    )

    require(
        isinstance(
            reviewer,
            str,
        )
        and bool(
            reviewer
        ),
        "reviewer_missing",
    )

    require(
        reviewer
        != creator_actor,
        "self_review",
    )

    require(
        review.get(
            "review_status"
        )
        == "PASS",
        "review_not_pass",
    )

    require(
        review.get(
            "source_hash_matches"
        )
        is True,
        "source_hash_mismatch",
    )

    if code_task:
        require(
            review.get(
                "code_gate_hash_matches"
            )
            is True,
            "code_gate_hash_mismatch",
        )

    require(
        review.get(
            "rights_expansion"
        )
        is False,
        "review_rights_expansion",
    )

    require(
        review.get(
            "forbidden_effects"
        )
        is False,
        "review_forbidden_effects",
    )


def evaluate(
    task: dict[str, Any],
    handoff: dict[str, Any],
    evidence: list[dict[str, Any]],
    gate: dict[str, Any],
    review: dict[str, Any],
    *,
    kill_switch: bool,
) -> dict[str, Any]:
    if kill_switch:
        raise KillSwitchStop(
            "kill_switch_active"
        )

    state_trace = [
        "NEW",
        "IDEKOMPASS_REQUIRED",
    ]

    validate_task(
        task
    )

    state_trace.extend([
        "TASK_ACCEPTED",
        "EXPLICIT_PARTICIPANT_ASSIGNED",
    ])

    validate_handoff(
        handoff,
        task,
    )

    state_trace.extend([
        "HANDOFF_READY",
        "EVIDENCE_REQUIRED",
    ])

    require(
        bool(evidence),
        "evidence_empty",
    )

    code_task = bool(
        task.get(
            "code_task",
            False,
        )
    )

    if code_task:
        state_trace.append(
            "CODE_GATE_REQUIRED"
        )

    validate_gate(
        gate,
        code_task,
    )

    if code_task:
        state_trace.append(
            "CODE_GATE_PASS"
        )

    state_trace.append(
        "INDEPENDENT_REVIEW_REQUIRED"
    )

    creator_actor = str(
        task.get(
            "creator_actor",
            "",
        )
    )

    require(
        bool(
            creator_actor
        ),
        "creator_actor_missing",
    )

    validate_review(
        review,
        creator_actor,
        code_task,
    )

    state_trace.extend([
        "ACCEPTED",
        "STOPPED_COMPLETE",
    ])

    expected_trace = (
        CODE_TASK_SUCCESS_TRACE
        if code_task
        else NONCODE_SUCCESS_TRACE
    )

    require(
        tuple(
            state_trace
        )
        == expected_trace,
        "state_trace_invalid",
    )

    require(
        all(
            state
            in STATE_MACHINE
            for state
            in state_trace
        ),
        "unknown_state_in_trace",
    )

    return {
        "schema":
            "gg.cp6b.orchestrator-result.v1",

        "status":
            "ACCEPTED",

        "terminal_state":
            "STOPPED_COMPLETE",

        "state_trace":
            state_trace,

        "task_id":
            task[
                "task_id"
            ],

        "assigned_participant":
            task[
                "assigned_participant"
            ],

        "verified_context":
            copy.deepcopy(
                task[
                    "verified_context"
                ]
            ),

        "historical_context":
            copy.deepcopy(
                task[
                    "historical_context"
                ]
            ),

        "reviewer_actor":
            review[
                "reviewer_actor"
            ],

        "routing_mode":
            "explicit_assignment_only",
    }


def base_fixture() -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    task: dict[
        str,
        Any,
    ] = {
        "task_id":
            "CP6B1-SYNTH-001",

        "owner":
            "Gold Goblins",

        "goal":
            "Validate deterministic CP6B routing.",

        "expected_value":
            "Safe explicit handoff.",

        "scope":
            ["synthetic"],

        "forbidden_scope":
            [
                "approval bypass",
                "scope drift",
                "cross-task reuse",
                "grant replay",
                "unbounded background autonomy",
            ],

        "risk_class":
            "GREEN",

        "stop_conditions":
            ["policy failure"],

        "expected_artifacts":
            [
                "HANDOFF.json",
                "REVIEW.md",
            ],

        "acceptance_criteria":
            ["review PASS"],

        "first_gate":
            "idekompassen-2.0",

        "assigned_participant":
            "GG-AI-installator",

        "creator_actor":
            "GG-AI-installator",

        "verified_context": {
            "source":
                "verified",
            "value":
                "A",
        },

        "historical_context": {
            "source":
                "historical",
            "value":
                "B",
        },

        "rights_expansion":
            False,

        "requested_effects": {
            "network": False,
            "credentials": False,
            "production": False,
            "one_com": False,
            "merge": False,
            "deploy": False,
            "write": False,
            "sudo": False,
            "unbounded_background_autonomy":
                False,
        },

        "code_task":
            True,
    }

    handoff: dict[
        str,
        Any,
    ] = {
        "handoff_id":
            "H-001",

        "from_role":
            "idekompassen-2.0",

        "to_role":
            "GG-AI-installator",

        "task_id":
            "CP6B1-SYNTH-001",

        "status":
            "PASS",

        "artifacts":
            ["synthetic"],

        "risks":
            ["none"],

        "next_action":
            "review",
    }

    evidence = [{
        "event":
            "synthetic",
        "status":
            "PASS",
    }]

    gate: dict[
        str,
        Any,
    ] = {
        "schema":
            "gg-code-gate-report-v1",
        "status":
            "PASS",
    }

    review: dict[
        str,
        Any,
    ] = {
        "reviewer_actor":
            "reviewer-control-v1",

        "review_status":
            "PASS",

        "source_hash_matches":
            True,

        "code_gate_hash_matches":
            True,

        "rights_expansion":
            False,

        "forbidden_effects":
            False,
    }

    return (
        task,
        handoff,
        evidence,
        gate,
        review,
    )


def expect_accept(
    name: str,
    mutate: Any = None,
) -> dict[str, Any]:
    (
        task,
        handoff,
        evidence,
        gate,
        review,
    ) = base_fixture()

    if mutate is not None:
        mutate(
            task,
            handoff,
            evidence,
            gate,
            review,
        )

    result = evaluate(
        task,
        handoff,
        evidence,
        gate,
        review,
        kill_switch=False,
    )

    expected_trace = (
        CODE_TASK_SUCCESS_TRACE
        if bool(
            task.get(
                "code_task",
                False,
            )
        )
        else NONCODE_SUCCESS_TRACE
    )

    require(
        tuple(
            result[
                "state_trace"
            ]
        )
        == expected_trace,
        "accept_state_trace_invalid:"
        + name,
    )

    return {
        "test":
            name,

        "expected":
            "PASS",

        "actual":
            "PASS",

        "terminal_state":
            result[
                "terminal_state"
            ],

        "state_trace":
            result[
                "state_trace"
            ],
    }


def expect_block(
    name: str,
    mutate: Any,
    expected_fragment: str,
    *,
    kill_switch: bool = False,
) -> dict[str, Any]:
    (
        task,
        handoff,
        evidence,
        gate,
        review,
    ) = base_fixture()

    mutate(
        task,
        handoff,
        evidence,
        gate,
        review,
    )

    try:
        evaluate(
            task,
            handoff,
            evidence,
            gate,
            review,
            kill_switch=kill_switch,
        )

    except KillSwitchStop as exc:
        require(
            kill_switch,
            "unexpected_kill_switch_stop:"
            + name,
        )

        require(
            expected_fragment
            in str(exc),
            "wrong_stop_reason:"
            + name
            + ":"
            + str(exc),
        )

        return {
            "test":
                name,

            "expected":
                "STOP",

            "actual":
                "STOP",

            "terminal_state":
                "STOPPED_COMPLETE",

            "reason":
                str(exc),
        }

    except PolicyError as exc:
        require(
            not kill_switch,
            "kill_switch_returned_block:"
            + name,
        )

        require(
            expected_fragment
            in str(exc),
            "wrong_block_reason:"
            + name
            + ":"
            + str(exc),
        )

        return {
            "test":
                name,

            "expected":
                "BLOCK",

            "actual":
                "BLOCK",

            "terminal_state":
                "BLOCKED",

            "reason":
                str(exc),
        }

    raise PolicyError(
        "expected_terminal_outcome_not_seen:"
        + name
    )


def self_test() -> dict[str, Any]:
    tests: list[
        dict[str, str]
    ] = []

    tests.append(
        expect_accept(
            "T01_VALID_IDEKOMPASS_AND_PARTICIPANT"
        )
    )

    for participant in (
        PARTICIPANTS
    ):
        def assign(
            task: dict[str, Any],
            handoff: dict[str, Any],
            _evidence: list[
                dict[str, Any]
            ],
            _gate: dict[str, Any],
            _review: dict[str, Any],
            participant: str = participant,
        ) -> None:
            task[
                "assigned_participant"
            ] = participant

            handoff[
                "to_role"
            ] = participant

        expect_accept(
            "T02_PARTICIPANT_"
            + participant,
            assign,
        )

    tests.append({
        "test":
            "T02_ALL_SEVEN_PARTICIPANTS",
        "expected":
            "PASS",
        "actual":
            "PASS",
    })

    tests.append(
        expect_accept(
            "T03_VALID_HANDOFF"
        )
    )

    (
        task,
        handoff,
        evidence,
        gate,
        review,
    ) = base_fixture()

    task[
        "verified_context"
    ] = {
        "kind":
            "verified",
        "value":
            1,
    }

    task[
        "historical_context"
    ] = {
        "kind":
            "historical",
        "value":
            2,
    }

    result = evaluate(
        task,
        handoff,
        evidence,
        gate,
        review,
        kill_switch=False,
    )

    require(
        result[
            "verified_context"
        ]
        != result[
            "historical_context"
        ],
        "context_separation_failed",
    )

    tests.append({
        "test":
            "T04_CONTEXT_SEPARATION",
        "expected":
            "PASS",
        "actual":
            "PASS",
    })

    tests.append(
        expect_accept(
            "T05_INDEPENDENT_REVIEWER"
        )
    )

    def missing_value(
        task: dict[str, Any],
        *_args: Any,
    ) -> None:
        del task[
            "expected_value"
        ]

    tests.append(
        expect_block(
            "T06_MISSING_EXPECTED_VALUE",
            missing_value,
            "missing_idekompass_field:"
            "expected_value",
        )
    )

    def unknown(
        task: dict[str, Any],
        handoff: dict[str, Any],
        *_args: Any,
    ) -> None:
        task[
            "assigned_participant"
        ] = "UNKNOWN"

        handoff[
            "to_role"
        ] = "UNKNOWN"

    tests.append(
        expect_block(
            "T07_UNKNOWN_PARTICIPANT",
            unknown,
            "unknown_participant",
        )
    )

    def rights(
        task: dict[str, Any],
        *_args: Any,
    ) -> None:
        task[
            "rights_expansion"
        ] = True

    tests.append(
        expect_block(
            "T08_RIGHTS_EXPANSION",
            rights,
            "rights_expansion",
        )
    )

    def self_review(
        task: dict[str, Any],
        _handoff: dict[str, Any],
        _evidence: list[
            dict[str, Any]
        ],
        _gate: dict[str, Any],
        review: dict[str, Any],
    ) -> None:
        review[
            "reviewer_actor"
        ] = task[
            "creator_actor"
        ]

    tests.append(
        expect_block(
            "T09_SELF_REVIEW",
            self_review,
            "self_review",
        )
    )

    effect_tests = (
        (
            "T10_NETWORK",
            "network",
        ),
        (
            "T11_CREDENTIALS",
            "credentials",
        ),
        (
            "T12_PRODUCTION",
            "production",
        ),
        (
            "T13_ONE_COM",
            "one_com",
        ),
        (
            "T14_MERGE",
            "merge",
        ),
        (
            "T15_DEPLOY",
            "deploy",
        ),
        (
            "T16_WRITE",
            "write",
        ),
        (
            "T17_SUDO",
            "sudo",
        ),
    )

    for (
        test_name,
        effect,
    ) in effect_tests:
        def set_effect(
            task: dict[str, Any],
            *_args: Any,
            effect: str = effect,
        ) -> None:
            task[
                "requested_effects"
            ][effect] = True

        tests.append(
            expect_accept(
                test_name,
                set_effect,
            )
        )

    def set_background_autonomy(
        task: dict[str, Any],
        *_args: Any,
    ) -> None:
        task["requested_effects"]["unbounded_background_autonomy"] = True

    tests.append(
        expect_block(
            "T18_UNBOUNDED_BACKGROUND_AUTONOMY",
            set_background_autonomy,
            "forbidden_effect:unbounded_background_autonomy",
        )
    )

    def gate_fail(
        _task: dict[str, Any],
        _handoff: dict[str, Any],
        _evidence: list[
            dict[str, Any]
        ],
        gate: dict[str, Any],
        _review: dict[str, Any],
    ) -> None:
        gate[
            "status"
        ] = "FAIL"

    tests.append(
        expect_block(
            "T19_CODE_GATE_FAIL",
            gate_fail,
            "code_gate_not_pass",
        )
    )

    def gate_conditional(
        _task: dict[str, Any],
        _handoff: dict[str, Any],
        _evidence: list[
            dict[str, Any]
        ],
        gate: dict[str, Any],
        _review: dict[str, Any],
    ) -> None:
        gate[
            "status"
        ] = "CONDITIONAL"

    tests.append(
        expect_block(
            "T20_CODE_GATE_CONDITIONAL",
            gate_conditional,
            "code_gate_not_pass",
        )
    )

    def no_change(
        *_args: Any,
    ) -> None:
        return None

    tests.append(
        expect_block(
            "T21_KILL_SWITCH",
            no_change,
            "kill_switch_active",
            kill_switch=True,
        )
    )

    require(
        len(tests) == 21,
        "test_count_differs:"
        + str(
            len(tests)
        ),
    )

    return {
        "schema":
            "gg.cp6b.orchestrator-self-test.v1",

        "status":
            "PASS",

        "passed":
            21,

        "total":
            21,

        "tests":
            tests,
    }


def validate_bundle(
    root: pathlib.Path,
) -> dict[str, Any]:
    task = load_json(
        root
        / "TASK.yml"
    )

    handoff = load_json(
        root
        / "HANDOFF.json"
    )

    evidence = load_jsonl(
        root
        / "EVIDENCE.jsonl"
    )

    gate = load_json(
        root
        / "CODE-GATE-REPORT.json"
    )

    review = load_review(
        root
        / "REVIEW.md"
    )

    kill_switch = (
        (
            root
            / "STOP"
        ).exists()
        or (
            pathlib.Path.cwd()
            / "STOP"
        ).exists()
    )

    return evaluate(
        task,
        handoff,
        evidence,
        gate,
        review,
        kill_switch=kill_switch,
    )


def main(
    argv: list[str],
) -> int:
    if argv == [
        "--self-test"
    ]:
        print(
            json.dumps(
                self_test(),
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        return 0

    if (
        len(argv) == 2
        and argv[0]
        == "--validate-bundle"
    ):
        root = pathlib.Path(
            argv[1]
        )

        try:
            result = validate_bundle(
                root
            )

        except KillSwitchStop as exc:
            print(
                json.dumps(
                    {
                        "schema":
                            "gg.cp6b.orchestrator-result.v1",

                        "status":
                            "STOP",

                        "terminal_state":
                            "STOPPED_COMPLETE",

                        "reason":
                            str(exc),

                        "routing_mode":
                            "explicit_assignment_only",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

            return 3

        except PolicyError as exc:
            print(
                json.dumps(
                    {
                        "schema":
                            "gg.cp6b.orchestrator-result.v1",

                        "status":
                            "BLOCK",

                        "terminal_state":
                            "BLOCKED",

                        "reason":
                            str(exc),

                        "routing_mode":
                            "explicit_assignment_only",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

            return 4

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        return 0

    print(
        "usage: gg_orchestrator.py "
        "--self-test | "
        "--validate-bundle <directory>",
        file=sys.stderr,
    )

    return 2


if __name__ == "__main__":
    raise SystemExit(
        main(
            sys.argv[1:]
        )
    )
