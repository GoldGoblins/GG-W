"""Pure deterministic in-memory application of machine-attested safe edits.

The engine performs no file I/O, process spawning, network access, model
inference, or persistent writes. Coordinates are one-based line/column
positions over the resident Python string. Ranges are half-open.

The request source SHA is SHA-256 over the UTF-8 encoding of the exact
resident source string.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


REQUEST_SCHEMA = "gg.safe-edit-request.v1"
RESULT_SCHEMA = "gg.safe-edit-result.v1"
ENGINE_HUMAN_ID = "repair.source.safe_edit"

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_EDIT_COUNT = 256
MAX_REPLACEMENT_BYTES = 2 * 1024 * 1024


class SafeEditError(ValueError):
    """Raised when a safe-edit contract cannot be proven."""


@dataclass(frozen=True)
class SourcePosition:
    row: int
    column: int


@dataclass(frozen=True)
class MachineEdit:
    start: SourcePosition
    end: SourcePosition
    content: str
    applicability: str
    producer: str
    code: str | None = None


@dataclass(frozen=True)
class SafeEditRequest:
    source_name: str
    source: str
    source_sha256: str
    evidence_sha256: str
    edits: tuple[MachineEdit, ...]


@dataclass(frozen=True)
class SafeEditResult:
    schema: str
    solver_id: str
    source_name: str
    source_sha256: str
    evidence_sha256: str
    candidate: str
    candidate_sha256: str
    edit_count: int
    changed: bool
    persistent_write: bool
    model_inference: bool


@dataclass(frozen=True)
class _ResolvedEdit:
    start_offset: int
    end_offset: int
    content: str
    edit: MachineEdit


def sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def _valid_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character
            in "0123456789abcdef"
            for character in value
        )
    )


def _validate_request(
    request: SafeEditRequest,
) -> None:
    if (
        not isinstance(
            request.source_name,
            str,
        )
        or not request.source_name
        or len(request.source_name) > 4096
    ):
        raise SafeEditError(
            "SOURCE_NAME_INVALID"
        )

    if not isinstance(
        request.source,
        str,
    ):
        raise SafeEditError(
            "SOURCE_NOT_TEXT"
        )

    source_bytes = request.source.encode(
        "utf-8"
    )

    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise SafeEditError(
            "SOURCE_BUDGET_EXCEEDED"
        )

    if not _valid_sha256(
        request.source_sha256
    ):
        raise SafeEditError(
            "SOURCE_SHA256_INVALID"
        )

    if sha256_text(
        request.source
    ) != request.source_sha256:
        raise SafeEditError(
            "STALE_SOURCE_SHA"
        )

    if not _valid_sha256(
        request.evidence_sha256
    ):
        raise SafeEditError(
            "EVIDENCE_SHA256_INVALID"
        )

    if (
        not isinstance(
            request.edits,
            tuple,
        )
        or not request.edits
        or len(request.edits)
        > MAX_EDIT_COUNT
    ):
        raise SafeEditError(
            "EDIT_COUNT_INVALID"
        )


def _line_starts(
    source: str,
) -> tuple[int, ...]:
    starts = [0]

    for index, character in enumerate(
        source
    ):
        if character == "\n":
            starts.append(
                index + 1
            )

    return tuple(starts)


def _position_to_offset(
    source: str,
    starts: tuple[int, ...],
    position: SourcePosition,
) -> int:
    if (
        not isinstance(
            position.row,
            int,
        )
        or isinstance(
            position.row,
            bool,
        )
        or not isinstance(
            position.column,
            int,
        )
        or isinstance(
            position.column,
            bool,
        )
    ):
        raise SafeEditError(
            "POSITION_TYPE_INVALID"
        )

    if (
        position.row < 1
        or position.row > len(starts)
    ):
        raise SafeEditError(
            "POSITION_ROW_OUT_OF_RANGE"
        )

    start = starts[
        position.row - 1
    ]

    if position.row < len(starts):
        segment_end = starts[
            position.row
        ]
    else:
        segment_end = len(source)

    content_end = segment_end

    if (
        content_end > start
        and source[
            content_end - 1
        ] == "\n"
    ):
        content_end -= 1

    if (
        content_end > start
        and source[
            content_end - 1
        ] == "\r"
    ):
        content_end -= 1

    maximum_column = (
        content_end
        - start
        + 1
    )

    if (
        position.column < 1
        or position.column
        > maximum_column
    ):
        raise SafeEditError(
            "POSITION_COLUMN_OUT_OF_RANGE"
        )

    return (
        start
        + position.column
        - 1
    )


def _resolve_edit(
    source: str,
    starts: tuple[int, ...],
    edit: MachineEdit,
) -> _ResolvedEdit:
    if not isinstance(
        edit,
        MachineEdit,
    ):
        raise SafeEditError(
            "EDIT_TYPE_INVALID"
        )

    if edit.applicability != "safe":
        raise SafeEditError(
            "EDIT_NOT_SAFE"
        )

    if (
        not isinstance(
            edit.producer,
            str,
        )
        or not edit.producer
        or len(edit.producer) > 512
    ):
        raise SafeEditError(
            "EDIT_PRODUCER_INVALID"
        )

    if (
        edit.code is not None
        and (
            not isinstance(
                edit.code,
                str,
            )
            or not edit.code
            or len(edit.code) > 256
        )
    ):
        raise SafeEditError(
            "EDIT_CODE_INVALID"
        )

    if not isinstance(
        edit.content,
        str,
    ):
        raise SafeEditError(
            "EDIT_CONTENT_INVALID"
        )

    if len(
        edit.content.encode(
            "utf-8"
        )
    ) > MAX_REPLACEMENT_BYTES:
        raise SafeEditError(
            "EDIT_REPLACEMENT_BUDGET_EXCEEDED"
        )

    start_offset = _position_to_offset(
        source,
        starts,
        edit.start,
    )

    end_offset = _position_to_offset(
        source,
        starts,
        edit.end,
    )

    if end_offset < start_offset:
        raise SafeEditError(
            "EDIT_RANGE_REVERSED"
        )

    return _ResolvedEdit(
        start_offset=start_offset,
        end_offset=end_offset,
        content=edit.content,
        edit=edit,
    )


def _validate_non_conflicting(
    edits: tuple[_ResolvedEdit, ...],
) -> None:
    ordered = sorted(
        edits,
        key=lambda item: (
            item.start_offset,
            item.end_offset,
        ),
    )

    previous: _ResolvedEdit | None = None

    for current in ordered:
        if previous is None:
            previous = current
            continue

        overlap = (
            current.start_offset
            < previous.end_offset
        )

        same_start = (
            current.start_offset
            == previous.start_offset
        )

        touching_zero_width = (
            current.start_offset
            == previous.end_offset
            and (
                current.start_offset
                == current.end_offset
                or previous.start_offset
                == previous.end_offset
            )
        )

        if (
            overlap
            or same_start
            or touching_zero_width
        ):
            raise SafeEditError(
                "EDIT_CONFLICT_OR_OVERLAP"
            )

        previous = current


def apply_safe_edits(
    request: SafeEditRequest,
) -> SafeEditResult:
    _validate_request(
        request
    )

    starts = _line_starts(
        request.source
    )

    resolved = tuple(
        _resolve_edit(
            request.source,
            starts,
            edit,
        )
        for edit in request.edits
    )

    _validate_non_conflicting(
        resolved
    )

    candidate = request.source

    for edit in sorted(
        resolved,
        key=lambda item: (
            item.start_offset,
            item.end_offset,
        ),
        reverse=True,
    ):
        candidate = (
            candidate[
                :edit.start_offset
            ]
            + edit.content
            + candidate[
                edit.end_offset:
            ]
        )

    if candidate == request.source:
        raise SafeEditError(
            "EDIT_SET_HAS_NO_EFFECT"
        )

    return SafeEditResult(
        schema=RESULT_SCHEMA,
        solver_id=ENGINE_HUMAN_ID,
        source_name=(
            request.source_name
        ),
        source_sha256=(
            request.source_sha256
        ),
        evidence_sha256=(
            request.evidence_sha256
        ),
        candidate=candidate,
        candidate_sha256=(
            sha256_text(candidate)
        ),
        edit_count=len(
            request.edits
        ),
        changed=True,
        persistent_write=False,
        model_inference=False,
    )
