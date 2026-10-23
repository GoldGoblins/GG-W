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

from backend import web_operator as op


class WebOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="gg-web-op-",
            dir=None if os.name == "nt" else Path("/run/user") / str(os.getuid()),
        )
        self.saved = op.ROOT
        op.ROOT = Path(self.tmp.name)

    def tearDown(self) -> None:
        op.ROOT = self.saved
        self.tmp.cleanup()

    def test_open_goldgoblins_is_yellow_visible(self) -> None:
        cmd = op.make_command("OPEN", url="goldgoblins.se")
        self.assertEqual(cmd["url"], "https://goldgoblins.se")
        self.assertEqual(cmd["risk_class"], "YELLOW")
        self.assertEqual(cmd["general_action_authority"], "NONE")
        self.assertTrue(cmd["visible_cursor"])

    def test_one_com_is_red_password_blocked(self) -> None:
        cmd = op.make_command("OPEN", url="https://www.one.com/login")
        self.assertEqual(cmd["risk_class"], "RED")
        with self.assertRaises(op.WebOperatorError) as exc:
            op.make_command("TYPE", selector="#password", text="secret")
        self.assertIn("PASSWORD_FIELD_FORBIDDEN", str(exc.exception))
        with self.assertRaises(op.WebOperatorError):
            op.make_command("TYPE", selector="input[type=password]", text="x")

    def test_javascript_url_rejected(self) -> None:
        with self.assertRaises(op.WebOperatorError):
            op.make_command("OPEN", url="javascript:alert(1)")
        with self.assertRaises(op.WebOperatorError):
            op.make_command("CLICK", selector="javascript:foo")

    def test_click_type_reload_helpers_exist(self) -> None:
        click = op.make_command("CLICK", selector="a.cta")
        self.assertEqual(click["action"], "CLICK")
        typed = op.make_command("TYPE", selector="#q", text="lidkoping")
        self.assertEqual(typed["action"], "TYPE")
        self.assertEqual(op.make_command("RELOAD")["action"], "RELOAD")
        self.assertEqual(op.make_command("BACK")["action"], "BACK")
        self.assertTrue(callable(op.click))
        self.assertTrue(callable(op.type_text))
        self.assertTrue(callable(op.reload_page))
        self.assertTrue(callable(op.go_back))

    def test_visible_cursor_actions(self) -> None:
        moved = op.make_command("MOVE", x=120, y=80)
        self.assertEqual(moved["risk_class"], "GREEN")
        self.assertTrue(moved["visible_cursor"])
        hover = op.make_command("HOVER", selector="#go")
        self.assertEqual(hover["risk_class"], "YELLOW")
        scrolled = op.make_command("SCROLL", dy=400)
        self.assertEqual(scrolled["action"], "SCROLL")
        self.assertEqual(scrolled["dy"], 400)
        into = op.make_command("SCROLL", selector="text=Aurora")
        self.assertEqual(into["selector"], "text=Aurora")
        self.assertEqual(op.make_command("WAIT")["risk_class"], "GREEN")
        self.assertEqual(op.make_command("STAGE")["risk_class"], "GREEN")
        keyed = op.make_command("KEY", text="Enter", selector="#q")
        self.assertEqual(keyed["action"], "KEY")
        self.assertEqual(keyed["risk_class"], "YELLOW")
        with self.assertRaises(op.WebOperatorError):
            op.make_command("KEY", text="Click")
        self.assertEqual(op.make_command("TAB_NEW")["risk_class"], "GREEN")
        self.assertEqual(
            op.make_command("TAB_NEW", url="https://goldgoblins.se")["risk_class"],
            "YELLOW",
        )
        self.assertEqual(op.make_command("TAB_NEXT")["action"], "TAB_NEXT")
        mid = op.make_command("TAB_NEW", selector="a#blank")
        self.assertEqual(mid["risk_class"], "YELLOW")
        self.assertEqual(op.make_command("FORWARD")["risk_class"], "GREEN")
        picked = op.make_command("SELECT", selector="#city", text="Lidkoping")
        self.assertEqual(picked["action"], "SELECT")
        with self.assertRaises(op.WebOperatorError):
            op.make_command("MOVE")
        with self.assertRaises(op.WebOperatorError):
            op.make_command("SCROLL")

    def test_take_and_result_roundtrip(self) -> None:
        cmd = op.make_command("SNAPSHOT")
        op.ensure_root()
        path = op.ROOT / op.COMMAND_NAME
        path.write_text(json.dumps(cmd), encoding="utf-8")
        taken = op.take_command()
        self.assertIsNotNone(taken)
        assert taken is not None
        self.assertEqual(taken["command_id"], cmd["command_id"])
        result = op.make_result(
            taken,
            ok=True,
            reason_code="SNAPSHOT",
            url="https://goldgoblins.se/",
            title="Gold Goblins",
            text="hello",
        )
        self.assertTrue(result["visible_web_tab"])
        self.assertTrue(result["visible_cursor"])
        op.write_result(result)
        stored = json.loads((op.ROOT / op.RESULT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(stored["reason_code"], "SNAPSHOT")
        self.assertFalse((op.ROOT / op.ACTIVE_NAME).exists())

    def test_cli_parses_stage_and_move(self) -> None:
        self.assertTrue(callable(op.main))
        self.assertIn("STAGE", op.ACTIONS)
        self.assertIn("MOVE", op.ACTIONS)
        self.assertIn("HOVER", op.ACTIONS)
        self.assertTrue(callable(op.stage))
        self.assertTrue(callable(op.move))


if __name__ == "__main__":
    unittest.main()
