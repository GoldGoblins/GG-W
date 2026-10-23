from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.platform_support import (
    private_runtime_root,
)


import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


PROJECT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

if str(PROJECT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT),
    )


executor_module = (
    importlib.import_module(
        "backend.live_aid.post_draft_qml_executor"
    )
)


REQUEST_SCHEMA = (
    "gg.live-aid.post-draft-process-request.v1"
)

EVENT_SCHEMA = (
    "gg.live-aid.post-draft-process-event.v1"
)

RESPONSE_SCHEMA = (
    "gg.live-aid.post-draft-process-response.v1"
)

MAX_SOURCE_BYTES = 262144
MAX_REQUEST_BYTES = 300000


class ProcessRunnerError(RuntimeError):
    pass


def _sha(
    source: str,
) -> str:
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def _text(
    value: object,
    label: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ProcessRunnerError(
            label
        )

    text = value.strip()

    if (
        not text
        or len(text) > maximum
    ):
        raise ProcessRunnerError(
            label
        )

    return text


def _require_sha(
    value: object,
    label: str,
) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(
            char not in "0123456789abcdef"
            for char in value
        )
    ):
        raise ProcessRunnerError(
            label
        )

    return value


def validate_request(
    value: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("schema")
        != REQUEST_SCHEMA
    ):
        raise ProcessRunnerError(
            "REQUEST_SCHEMA"
        )

    request_id = _text(
        value.get("request_id"),
        "REQUEST_ID",
        128,
    )

    if not request_id.startswith(
        "post-draft-"
    ):
        raise ProcessRunnerError(
            "REQUEST_ID_PREFIX"
        )

    object_id = _text(
        value.get("object_id"),
        "OBJECT_ID",
        160,
    )

    source_name = _text(
        value.get("source_name"),
        "SOURCE_NAME",
        240,
    )

    language = _text(
        value.get("language"),
        "LANGUAGE",
        32,
    )

    if language != "qml":
        raise ProcessRunnerError(
            "LANGUAGE_QML_REQUIRED"
        )

    relative_raw = _text(
        value.get(
            "source_relative_path"
        ),
        "SOURCE_RELATIVE_PATH",
        512,
    )

    relative = PurePosixPath(
        relative_raw
    )

    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.name != source_name
        or relative.suffix.lower() != ".qml"
    ):
        raise ProcessRunnerError(
            "SOURCE_RELATIVE_PATH_BINDING"
        )

    source = value.get(
        "source"
    )

    if not isinstance(source, str):
        raise ProcessRunnerError(
            "SOURCE"
        )

    if (
        len(
            source.encode("utf-8")
        )
        > MAX_SOURCE_BYTES
    ):
        raise ProcessRunnerError(
            "SOURCE_TOO_LARGE"
        )

    source_sha = _require_sha(
        value.get("source_sha256"),
        "SOURCE_SHA256",
    )

    if _sha(source) != source_sha:
        raise ProcessRunnerError(
            "SOURCE_SHA_MISMATCH"
        )

    max_repairs = value.get(
        "max_repair_attempts"
    )

    if (
        not isinstance(max_repairs, int)
        or isinstance(max_repairs, bool)
        or not 1 <= max_repairs <= 8
    ):
        raise ProcessRunnerError(
            "MAX_REPAIR_ATTEMPTS"
        )

    dispatch_budget = value.get(
        "model_dispatch_budget"
    )

    if (
        not isinstance(
            dispatch_budget,
            int,
        )
        or isinstance(
            dispatch_budget,
            bool,
        )
        or not 0 <= dispatch_budget <= 8
    ):
        raise ProcessRunnerError(
            "MODEL_DISPATCH_BUDGET"
        )

    if (
        value.get(
            "persistent_write_authority"
        )
        != "NONE"
        or value.get(
            "execution_authority"
        )
        != "NONE"
        or value.get(
            "network_authority"
        )
        != "NONE"
    ):
        raise ProcessRunnerError(
            "ACTION_AUTHORITY"
        )

    return {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "object_id": object_id,
        "source_name": source_name,
        "source_relative_path":
            relative.as_posix(),
        "language": language,
        "source": source,
        "source_sha256": source_sha,
        "max_repair_attempts":
            max_repairs,
        "model_dispatch_budget":
            dispatch_budget,
        "persistent_write_authority":
            "NONE",
        "execution_authority":
            "NONE",
        "network_authority":
            "NONE",
    }


def build_event(
    request: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ProcessRunnerError(
            "EVENT_OBJECT"
        )

    event_name = _text(
        event.get("event"),
        "EVENT_NAME",
        128,
    )

    event_source_sha = _require_sha(
        event.get("source_sha256"),
        "EVENT_SOURCE_SHA256",
    )

    normalized_event = dict(
        event
    )

    normalized_event[
        "event"
    ] = event_name

    normalized_event[
        "source_sha256"
    ] = event_source_sha

    return {
        "schema": EVENT_SCHEMA,
        "kind": "event",
        "request_id":
            request["request_id"],
        "object_id":
            request["object_id"],
        "initial_source_sha256":
            request["source_sha256"],
        "event":
            normalized_event,
    }


def validate_event(
    value: dict[str, Any],
    *,
    expected_request_id: str,
    expected_object_id: str,
    expected_initial_source_sha256: str,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("schema")
        != EVENT_SCHEMA
        or value.get("kind")
        != "event"
    ):
        raise ProcessRunnerError(
            "EVENT_SCHEMA"
        )

    if (
        value.get("request_id")
        != expected_request_id
    ):
        raise ProcessRunnerError(
            "EVENT_REQUEST_BINDING"
        )

    if (
        value.get("object_id")
        != expected_object_id
    ):
        raise ProcessRunnerError(
            "EVENT_OBJECT_BINDING"
        )

    if (
        value.get(
            "initial_source_sha256"
        )
        != expected_initial_source_sha256
    ):
        raise ProcessRunnerError(
            "EVENT_SOURCE_BINDING"
        )

    event = value.get(
        "event"
    )

    if not isinstance(event, dict):
        raise ProcessRunnerError(
            "EVENT_PAYLOAD"
        )

    _text(
        event.get("event"),
        "EVENT_NAME",
        128,
    )

    _require_sha(
        event.get("source_sha256"),
        "EVENT_SOURCE_SHA256",
    )

    return dict(value)


def build_response(
    request: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    source = getattr(
        result,
        "source",
        None,
    )

    if not isinstance(source, str):
        raise ProcessRunnerError(
            "RESULT_SOURCE"
        )

    source_sha = _sha(
        source
    )

    if (
        getattr(
            result,
            "source_sha256",
            None,
        )
        != source_sha
    ):
        raise ProcessRunnerError(
            "RESULT_SOURCE_SHA"
        )

    evidence = getattr(
        result,
        "model_evidence_paths",
        (),
    )

    if not isinstance(
        evidence,
        (tuple, list),
    ):
        raise ProcessRunnerError(
            "RESULT_EVIDENCE"
        )

    evidence_list: list[str] = []

    for item in evidence:
        if (
            not isinstance(item, str)
            or not item
            or len(item) > 1024
        ):
            raise ProcessRunnerError(
                "RESULT_EVIDENCE_ITEM"
            )

        evidence_list.append(
            item
        )

    return {
        "schema": RESPONSE_SCHEMA,
        "kind": "result",
        "request_id":
            request["request_id"],
        "object_id":
            request["object_id"],
        "initial_source_sha256":
            request["source_sha256"],
        "source": source,
        "source_sha256":
            source_sha,
        "state":
            str(
                getattr(
                    result,
                    "state",
                    "",
                )
            ),
        "repair_attempts":
            int(
                getattr(
                    result,
                    "repair_attempts",
                    0,
                )
            ),
        "model_dispatch_count":
            int(
                getattr(
                    result,
                    "model_dispatch_count",
                    0,
                )
            ),
        "execution_ready":
            bool(
                getattr(
                    result,
                    "execution_ready",
                    False,
                )
            ),
        "blocked_fault_layer":
            str(
                getattr(
                    result,
                    "blocked_fault_layer",
                    "",
                )
            ),
        "blocked_reason":
            str(
                getattr(
                    result,
                    "blocked_reason",
                    "",
                )
            ),
        "model_evidence_paths":
            evidence_list,
        "persistent_write_authority":
            "NONE",
        "execution_authority":
            "NONE",
        "network_authority":
            "NONE",
    }


def validate_response(
    value: dict[str, Any],
    *,
    expected_request_id: str,
    expected_object_id: str,
    expected_initial_source_sha256: str,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("schema")
        != RESPONSE_SCHEMA
        or value.get("kind")
        != "result"
    ):
        raise ProcessRunnerError(
            "RESPONSE_SCHEMA"
        )

    if (
        value.get("request_id")
        != expected_request_id
    ):
        raise ProcessRunnerError(
            "RESPONSE_REQUEST_BINDING"
        )

    if (
        value.get("object_id")
        != expected_object_id
    ):
        raise ProcessRunnerError(
            "RESPONSE_OBJECT_BINDING"
        )

    if (
        value.get(
            "initial_source_sha256"
        )
        != expected_initial_source_sha256
    ):
        raise ProcessRunnerError(
            "RESPONSE_INITIAL_SOURCE_BINDING"
        )

    source = value.get(
        "source"
    )

    if not isinstance(source, str):
        raise ProcessRunnerError(
            "RESPONSE_SOURCE"
        )

    if (
        value.get("source_sha256")
        != _sha(source)
    ):
        raise ProcessRunnerError(
            "RESPONSE_SOURCE_SHA"
        )

    state = value.get(
        "state"
    )

    if state not in {
        "READY_TO_RUN",
        "BLOCKED",
    }:
        raise ProcessRunnerError(
            "RESPONSE_STATE"
        )

    execution_ready = value.get(
        "execution_ready"
    )

    if not isinstance(
        execution_ready,
        bool,
    ):
        raise ProcessRunnerError(
            "RESPONSE_EXECUTION_READY"
        )

    if (
        state == "READY_TO_RUN"
        and execution_ready is not True
    ):
        raise ProcessRunnerError(
            "READY_WITHOUT_EXECUTION_READY"
        )

    if (
        value.get(
            "persistent_write_authority"
        )
        != "NONE"
        or value.get(
            "execution_authority"
        )
        != "NONE"
        or value.get(
            "network_authority"
        )
        != "NONE"
    ):
        raise ProcessRunnerError(
            "RESPONSE_ACTION_AUTHORITY"
        )

    evidence = value.get(
        "model_evidence_paths"
    )

    if not isinstance(
        evidence,
        list,
    ):
        raise ProcessRunnerError(
            "RESPONSE_EVIDENCE"
        )

    for item in evidence:
        if (
            not isinstance(item, str)
            or not item
            or len(item) > 1024
        ):
            raise ProcessRunnerError(
                "RESPONSE_EVIDENCE_ITEM"
            )

    return dict(value)


def run_request(
    request: dict[str, Any],
    *,
    event_writer: Any,
) -> dict[str, Any]:
    validated = validate_request(
        request
    )

    def emit(
        event: dict[str, Any],
    ) -> None:
        envelope = build_event(
            validated,
            event,
        )

        event_writer(
            envelope
        )

    executor = (
        executor_module
        .PostDraftQmlExecutor(
            object_id=
                validated["object_id"],
            source_name=
                validated["source_name"],
            source_relative_path=
                validated[
                    "source_relative_path"
                ],
            max_repair_attempts=
                validated[
                    "max_repair_attempts"
                ],
            model_dispatch_budget=
                validated[
                    "model_dispatch_budget"
                ],
            event_sink=emit,
        )
    )

    result = (
        executor
        .run_complete_draft(
            validated["source"]
        )
    )

    return build_response(
        validated,
        result,
    )


def _read_request(
    path: Path,
) -> dict[str, Any]:
    runtime = private_runtime_root().resolve(
        strict=True
    )

    resolved = path.resolve(
        strict=True
    )

    if (
        not resolved.is_relative_to(
            runtime
        )
        or resolved.name
        != "request.json"
        or not re.fullmatch(
            r"gg-live-aid-post-draft-ui\.[0-9a-f]{32}",
            resolved.parent.name,
        )
    ):
        raise ProcessRunnerError(
            "REQUEST_PATH"
        )

    if (
        resolved.is_symlink()
        or not resolved.is_file()
    ):
        raise ProcessRunnerError(
            "REQUEST_FILE"
        )

    payload = resolved.read_bytes()

    if len(payload) > MAX_REQUEST_BYTES:
        raise ProcessRunnerError(
            "REQUEST_TOO_LARGE"
        )

    try:
        value = json.loads(
            payload.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ProcessRunnerError(
            "REQUEST_JSON"
        ) from exc

    return validate_request(
        value
    )


def _print_json(
    value: dict[str, Any],
) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "POST_DRAFT_STOP=ARGUMENT_COUNT",
            file=sys.stderr,
        )
        return 2

    try:
        request = _read_request(
            Path(sys.argv[1])
        )

        response = run_request(
            request,
            event_writer=_print_json,
        )

        validated = validate_response(
            response,
            expected_request_id=
                request["request_id"],
            expected_object_id=
                request["object_id"],
            expected_initial_source_sha256=
                request["source_sha256"],
        )

        _print_json(
            validated
        )

        return 0

    except Exception as exc:
        print(
            "POST_DRAFT_STOP="
            + type(exc).__name__
            + ":"
            + str(exc),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
