#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import desktop_operator as op


class DesktopOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="gg-desk-op-",
            dir=None if os.name == "nt" else Path("/run/user") / str(os.getuid()),
        )
        self.saved = op.ROOT
        op.ROOT = Path(self.tmp.name)

    def tearDown(self) -> None:
        op.ROOT = self.saved
        self.tmp.cleanup()

    def test_click_named_is_yellow(self) -> None:
        cmd = op.make_command("CLICK", name="workspaceSpawnInstanceButton")
        self.assertEqual(cmd["risk_class"], "YELLOW")
        self.assertTrue(cmd["visible_cursor"])
        self.assertEqual(cmd["button"], "left")
        seen = op.make_command("CLICK", text="WEB")
        self.assertEqual(seen["text"], "WEB")
        self.assertEqual(seen["name"], "")

    def test_move_and_snapshot_are_green(self) -> None:
        self.assertEqual(op.make_command("MOVE", x=10, y=20)["risk_class"], "GREEN")
        self.assertEqual(op.make_command("SNAPSHOT")["risk_class"], "GREEN")
        self.assertEqual(op.make_command("FIND", text="workspace")["risk_class"], "GREEN")

    def test_key_and_type(self) -> None:
        self.assertEqual(op.make_command("KEY", text="Enter")["action"], "KEY")
        typed = op.make_command("TYPE", text="hello", name="workspaceWebAddress")
        self.assertEqual(typed["text"], "hello")
        with self.assertRaises(op.DesktopOperatorError):
            op.make_command("KEY", text="Click")

    def test_roundtrip(self) -> None:
        cmd = op.make_command("MOVE", name="deskAgentCursor")
        op.ensure_root()
        (op.ROOT / op.COMMAND_NAME).write_text(json.dumps(cmd), encoding="utf-8")
        taken = op.take_command()
        self.assertIsNotNone(taken)
        assert taken is not None
        result = op.make_result(taken, ok=True, reason_code="MOVED", x=4, y=8)
        self.assertTrue(result["visible_cursor"])
        op.write_result(result)
        stored = json.loads((op.ROOT / op.RESULT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(stored["reason_code"], "MOVED")


if __name__ == "__main__":
    unittest.main()
