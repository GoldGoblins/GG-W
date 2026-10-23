from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


project = Path(
    os.environ["PROJECT"]
).resolve(
    strict=True
)

source_path = Path(
    os.environ["SOURCE"]
).resolve(
    strict=True
)

sys.path.insert(
    0,
    str(project),
)

executor_module = importlib.import_module(
    "backend.live_aid.post_draft_qml_executor"
)


def sha_bytes(
    value: bytes,
) -> str:
    return hashlib.sha256(
        value
    ).hexdigest()


disk_before = (
    source_path.read_bytes()
)

disk_sha_before = sha_bytes(
    disk_before
)

source = disk_before.decode(
    "utf-8"
)

needle = (
    "implicitHeight: 93"
)

if source.count(needle) != 1:
    raise SystemExit(
        "ORIGINAL_TARGET_CARDINALITY:"
        + str(
            source.count(
                needle
            )
        )
    )


lines = source.splitlines()

if (
    len(lines) < 20
    or lines[19].strip()
    != needle
):
    raise SystemExit(
        "ORIGINAL_TARGET_NOT_LINE_20"
    )


broken = source.replace(
    needle,
    "implicitHeight: ???",
    1,
)


def emit(
    event: dict,
) -> None:
    print(
        "LIVE_E2B|"
        + json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


executor = (
    executor_module
    .PostDraftQmlExecutor(
        object_id=
            "ws.file.context-composer",
        source_name=
            "ContextComposer.qml",
        source_relative_path=
            "qml/components/"
            "ContextComposer.qml",
        max_repair_attempts=1,
        model_dispatch_budget=1,
        timeout_seconds=300,
        event_sink=emit,
    )
)


print(
    "LIVE_E2B|AUTOMATIC_LOOP=START",
    flush=True,
)

result = (
    executor
    .run_complete_draft(
        broken
    )
)


if (
    result.state
    != "READY_TO_RUN"
    or not result.execution_ready
):
    raise SystemExit(
        "FINAL_STATE_NOT_READY:"
        + result.state
        + ":"
        + result.blocked_reason
    )


if (
    result.model_dispatch_count
    != 1
):
    raise SystemExit(
        "MODEL_DISPATCH_COUNT:"
        + str(
            result.model_dispatch_count
        )
    )


if (
    result.repair_attempts
    != 1
):
    raise SystemExit(
        "REPAIR_ATTEMPTS:"
        + str(
            result.repair_attempts
        )
    )


if (
    len(
        result.model_evidence_paths
    )
    != 1
):
    raise SystemExit(
        "MODEL_EVIDENCE_PATH_COUNT:"
        + str(
            len(
                result
                .model_evidence_paths
            )
        )
    )


candidate = result.source

broken_lines = (
    broken.splitlines()
)

candidate_lines = (
    candidate.splitlines()
)

if len(candidate_lines) != len(
    broken_lines
):
    raise SystemExit(
        "CANDIDATE_LINE_COUNT_CHANGED"
    )


changed = [
    index
    for index, (
        old_line,
        new_line,
    ) in enumerate(
        zip(
            broken_lines,
            candidate_lines,
            strict=True,
        ),
        start=1,
    )
    if old_line != new_line
]


if changed != [20]:
    raise SystemExit(
        "CHANGED_LINES:"
        + repr(changed)
    )


if (
    candidate_lines[19].strip()
    == "implicitHeight: ???"
):
    raise SystemExit(
        "REPAIR_DID_NOT_CHANGE_TARGET"
    )


event_names = [
    event["event"]
    for event in result.events
]


required_events = (
    "DRAFT",
    "DRAFT_COMPLETE",
    "VERIFYING",
    "REPAIRING",
    "CANDIDATE_APPLIED_IN_MEMORY",
    "PREFLIGHT_RESPONSE",
    "READY_TO_RUN",
)

for name in required_events:
    if name not in event_names:
        raise SystemExit(
            "EVENT_MISSING:"
            + name
        )


preflight_responses = [
    event
    for event in result.events
    if event["event"]
    == "PREFLIGHT_RESPONSE"
]

if len(preflight_responses) != 2:
    raise SystemExit(
        "PREFLIGHT_RESPONSE_COUNT:"
        + str(
            len(
                preflight_responses
            )
        )
    )


if (
    preflight_responses[0].get(
        "gate_status"
    )
    != "FAIL"
):
    raise SystemExit(
        "FIRST_PREFLIGHT_NOT_FAIL"
    )


if (
    preflight_responses[1].get(
        "gate_status"
    )
    != "PASS"
):
    raise SystemExit(
        "SECOND_PREFLIGHT_NOT_PASS"
    )


disk_after = (
    source_path.read_bytes()
)

if disk_after != disk_before:
    raise SystemExit(
        "ORIGINAL_DISK_SOURCE_CHANGED"
    )


print(
    "BROKEN_DRAFT_COMPLETE=PASS"
)

print(
    "REAL_QML_PREFLIGHT_1=FAIL_AS_EXPECTED"
)

print(
    "REAL_LOCAL_MODEL_DISPATCH_COUNT=1"
)

print(
    "AUTOMATIC_PRIVATE_BUFFER_APPLY=PASS"
)

print(
    "REPAIR_CHANGED_LINES=[20]"
)

print(
    "CANDIDATE_LINE_20="
    + candidate_lines[19].strip()
)

print(
    "REAL_QML_PREFLIGHT_2=PASS"
)

print(
    "READY_TO_RUN=PASS"
)

print(
    "MODEL_EVIDENCE="
    + result.model_evidence_paths[0]
)

print(
    "ORIGINAL_DISK_SOURCE_UNCHANGED=PASS"
)

print(
    "PERSISTENT_SOURCE_WRITE_BY_EXECUTOR=NONE"
)

print(
    "USER_CODE_EXECUTION=NONE"
)

print(
    "NETWORK_AUTHORITY=NONE"
)

print(
    "REAL_E2B_AUTOMATIC_LOOP=PASS"
)
