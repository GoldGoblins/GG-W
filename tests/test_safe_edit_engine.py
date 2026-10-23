from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT = Path(
    __file__
).resolve().parents[1]

BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

from safe_edit_engine import (  # noqa: E402
    MachineEdit,
    SafeEditError,
    SafeEditRequest,
    SourcePosition,
    apply_safe_edits,
    sha256_text,
)


EVIDENCE_SHA = "a" * 64


def request(
    source: str,
    edits: tuple[MachineEdit, ...],
    *,
    source_sha256: str | None = None,
) -> SafeEditRequest:
    return SafeEditRequest(
        source_name="fixture.py",
        source=source,
        source_sha256=(
            source_sha256
            if source_sha256 is not None
            else sha256_text(source)
        ),
        evidence_sha256=EVIDENCE_SHA,
        edits=edits,
    )


def edit(
    start_row: int,
    start_column: int,
    end_row: int,
    end_column: int,
    content: str,
    *,
    applicability: str = "safe",
) -> MachineEdit:
    return MachineEdit(
        start=SourcePosition(
            row=start_row,
            column=start_column,
        ),
        end=SourcePosition(
            row=end_row,
            column=end_column,
        ),
        content=content,
        applicability=applicability,
        producer="fixture.machine",
        code="FIXTURE",
    )


class SafeEditEngineTests(
    unittest.TestCase
):
    def test_line_deletion_like_f401(
        self,
    ) -> None:
        source = (
            "import os\n"
            "import json\n"
            "value = 1\n"
        )

        result = apply_safe_edits(
            request(
                source,
                (
                    edit(
                        2,
                        1,
                        3,
                        1,
                        "",
                    ),
                ),
            )
        )

        self.assertEqual(
            result.candidate,
            (
                "import os\n"
                "value = 1\n"
            ),
        )

        self.assertTrue(
            result.changed
        )

        self.assertFalse(
            result.persistent_write
        )

        self.assertFalse(
            result.model_inference
        )

    def test_stale_source_sha_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "STALE_SOURCE_SHA",
        ):
            apply_safe_edits(
                request(
                    "value = 1\n",
                    (
                        edit(
                            1,
                            9,
                            1,
                            10,
                            "2",
                        ),
                    ),
                    source_sha256=(
                        "0" * 64
                    ),
                )
            )

    def test_unsafe_applicability_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "EDIT_NOT_SAFE",
        ):
            apply_safe_edits(
                request(
                    "value = 1\n",
                    (
                        edit(
                            1,
                            9,
                            1,
                            10,
                            "2",
                            applicability="unsafe",
                        ),
                    ),
                )
            )

    def test_out_of_range_row_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "POSITION_ROW_OUT_OF_RANGE",
        ):
            apply_safe_edits(
                request(
                    "value = 1\n",
                    (
                        edit(
                            99,
                            1,
                            99,
                            1,
                            "",
                        ),
                    ),
                )
            )

    def test_out_of_range_column_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "POSITION_COLUMN_OUT_OF_RANGE",
        ):
            apply_safe_edits(
                request(
                    "x\n",
                    (
                        edit(
                            1,
                            99,
                            1,
                            99,
                            "",
                        ),
                    ),
                )
            )

    def test_reversed_range_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "EDIT_RANGE_REVERSED",
        ):
            apply_safe_edits(
                request(
                    "abc\n",
                    (
                        edit(
                            1,
                            3,
                            1,
                            2,
                            "",
                        ),
                    ),
                )
            )

    def test_overlapping_edits_fail_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "EDIT_CONFLICT_OR_OVERLAP",
        ):
            apply_safe_edits(
                request(
                    "abcdef\n",
                    (
                        edit(
                            1,
                            2,
                            1,
                            5,
                            "X",
                        ),
                        edit(
                            1,
                            4,
                            1,
                            6,
                            "Y",
                        ),
                    ),
                )
            )

    def test_multiple_non_overlapping_edits(
        self,
    ) -> None:
        source = "abc def ghi\n"

        result = apply_safe_edits(
            request(
                source,
                (
                    edit(
                        1,
                        1,
                        1,
                        4,
                        "ABC",
                    ),
                    edit(
                        1,
                        9,
                        1,
                        12,
                        "GHI",
                    ),
                ),
            )
        )

        self.assertEqual(
            result.candidate,
            "ABC def GHI\n",
        )

    def test_unicode_columns_are_codepoint_based(
        self,
    ) -> None:
        source = "åäö value\n"

        result = apply_safe_edits(
            request(
                source,
                (
                    edit(
                        1,
                        5,
                        1,
                        10,
                        "VALUE",
                    ),
                ),
            )
        )

        self.assertEqual(
            result.candidate,
            "åäö VALUE\n",
        )

    def test_crlf_is_preserved(
        self,
    ) -> None:
        source = (
            "first\r\n"
            "remove\r\n"
            "last\r\n"
        )

        result = apply_safe_edits(
            request(
                source,
                (
                    edit(
                        2,
                        1,
                        3,
                        1,
                        "",
                    ),
                ),
            )
        )

        self.assertEqual(
            result.candidate,
            (
                "first\r\n"
                "last\r\n"
            ),
        )

    def test_no_effect_edit_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            SafeEditError,
            "EDIT_SET_HAS_NO_EFFECT",
        ):
            apply_safe_edits(
                request(
                    "abc\n",
                    (
                        edit(
                            1,
                            1,
                            1,
                            2,
                            "a",
                        ),
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
