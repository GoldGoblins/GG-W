"""Saved-tail checkpoints contain only selected visible conversation text."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.chat_restore import codex_tail_marker, normalized_display_text


def message(text, *, role="assistant", phase="final_answer"):
    return {"type": "response_item", "payload": {"type": "message", "role": role,
            "phase": phase, "content": [{"type": "output_text", "text": text}]}}


class SavedTailTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-saved-tail-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "selected.jsonl"

    def write(self, rows):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_uses_latest_visible_message_and_skips_private_nonmessage_rows(self):
        self.write([message("older answer"), message("latest visible answer"),
                    message("hidden analysis", phase="analysis"),
                    message("hidden developer guidance", role="developer"),
                    {"type": "response_item", "payload": {"type": "function_call_output",
                                                            "output": "hidden tool output"}}])
        self.assertEqual(codex_tail_marker(self.path), "latestvisibleanswer")

    def test_event_formats_and_latest_user_message(self):
        for payload in (
            {"type": "task_complete", "last_agent_message": "LATEST MESSAGE"},
            {"type": "agent_message", "message": "LATEST MESSAGE"},
            {"type": "item_completed", "item": {"type": "AgentMessage", "phase": "final_answer",
             "content": [{"type": "Text", "text": "LATEST MESSAGE"}]}},
            {"type": "user_message", "message": "LATEST MESSAGE"},
            {"type": "item_completed", "item": {"type": "UserMessage",
             "content": [{"type": "text", "text": "LATEST MESSAGE"}]}},
        ):
            with self.subTest(kind=payload["type"]):
                self.write([message("older answer"), {"type": "event_msg", "payload": payload}])
                self.assertEqual(codex_tail_marker(self.path), "latestmessage")
        self.write([message("older answer"), message("newest user question", role="user")])
        self.assertEqual(codex_tail_marker(self.path), "newestuserquestion")

    def test_rendered_markdown_wraps_links_and_unicode_match(self):
        source = "**Klart**: se [ändringen](/private/source/path.py:42). Återställningen är färdig."
        rendered = "Klart: se ändringen.\n Återställningen är\n färdig."
        self.assertEqual(normalized_display_text(source), normalized_display_text(rendered))

    def test_large_image_record_before_tail_is_not_copied_or_rewritten(self):
        large = {"type": "response_item", "payload": {"type": "message", "role": "user",
                 "content": [{"type": "input_image", "image_url": "A" * 700000}]}}
        self.write([large, message("latest answer after the image")])
        original = self.path.read_bytes()
        self.assertEqual(codex_tail_marker(self.path), "latestansweraftertheimage")
        self.assertEqual(self.path.read_bytes(), original)

    def test_partial_last_record_and_bad_rows_do_not_discard_valid_checkpoint(self):
        self.write([message("last complete visible answer")])
        with self.path.open("ab") as stream:
            stream.write(b'bad json\n\xff\n{"type":"event_msg","payload":')
        self.assertEqual(codex_tail_marker(self.path), "lastcompletevisibleanswer")

    def test_unknown_and_private_only_history_stay_unknown(self):
        self.assertIsNone(codex_tail_marker(None))
        self.assertIsNone(codex_tail_marker(self.path))
        self.write([message("private", role="developer"), message("private", phase="analysis")])
        self.assertIsNone(codex_tail_marker(self.path))

    def test_malformed_record_shapes_do_not_break_startup(self):
        self.write([message("last valid answer"), [],
                    {"type": "event_msg", "payload": {"type": []}},
                    {"type": "response_item", "payload": {"type": "message", "role": []}},
                    {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": []}}}])
        self.assertEqual(codex_tail_marker(self.path), "lastvalidanswer")


if __name__ == "__main__":
    unittest.main()
