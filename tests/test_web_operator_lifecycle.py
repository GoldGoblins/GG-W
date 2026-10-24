"""Exercise durable WEB claim/cancel/restart semantics without opening a site."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import web_operator as op


class WebOperatorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-web-lifecycle-")
        self.saved = op.ROOT
        op.ROOT = Path(self.temporary.name)
        self.authorization = patch.object(op.task_scoped_action_grant, "runtime_authorize_effect", return_value=None)
        self.authorization.start()

    def tearDown(self):
        self.authorization.stop()
        op.ROOT = self.saved
        self.temporary.cleanup()

    def pending(self, action="SNAPSHOT", *, expires=0):
        command = op.make_command(action, selector="#button" if action == "CLICK" else "")
        command["expires_at"] = expires
        (op.ROOT / op.COMMAND_NAME).write_text(json.dumps(command), encoding="utf-8")
        return command

    def result(self, command):
        return op.make_result(command, ok=True, reason_code="TEST_COMPLETED")

    def test_repeated_notifications_claim_once(self):
        command = self.pending("CLICK")
        claimed = op.take_command(owner="first-host")
        self.assertEqual(claimed["command_id"], command["command_id"])
        for _ in range(5):
            self.assertIsNone(op.take_command(owner="first-host"))
        self.assertTrue(op.write_result(self.result(claimed)))
        self.assertFalse(op.write_result(self.result(claimed)))
        self.assertEqual(json.loads((op.ROOT / op.HISTORY_NAME).read_text())[0]["state"], "COMPLETED")

    def test_concurrent_host_polls_dispatch_once(self):
        self.pending("CLICK")
        results, errors = [], []
        def claim():
            try:
                results.append(op.take_command(owner="same-host"))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=claim) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertFalse(errors)
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_restart_marks_uncertain_effect_without_replay(self):
        command = self.pending("CLICK")
        op.take_command(owner="old-host")
        self.assertIsNone(op.take_command(owner="new-host"))
        result = json.loads((op.ROOT / op.RESULT_NAME).read_text())
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "OPERATOR_INTERRUPTED")
        self.assertFalse((op.ROOT / op.ACTIVE_NAME).exists())
        self.assertEqual(op.take_cancellations()[0]["command_id"], command["command_id"])

    def test_late_result_cannot_clear_or_replace_next_command(self):
        first = self.pending("CLICK")
        op.take_command()
        self.assertTrue(op.cancel(first["command_id"]))
        second = self.pending()
        op.take_command()
        self.assertFalse(op.write_result(self.result(first)))
        active = json.loads((op.ROOT / op.ACTIVE_NAME).read_text())
        self.assertEqual(active["command_id"], second["command_id"])
        self.assertTrue(op.write_result(self.result(second)))
        self.assertEqual(json.loads((op.ROOT / op.RESULT_NAME).read_text())["command_id"], second["command_id"])

    def test_expired_pending_never_dispatches_and_next_job_works(self):
        command = self.pending("CLICK", expires=time.time() - 1)
        self.assertIsNone(op.take_command())
        self.assertEqual(op.take_cancellations()[0]["command_id"], command["command_id"])
        second = self.pending()
        self.assertEqual(op.take_command()["command_id"], second["command_id"])

    def test_expired_active_rejects_late_completion(self):
        command = self.pending()
        op.take_command()
        path = op.ROOT / op.ACTIVE_NAME
        value = json.loads(path.read_text())
        value["expires_at"] = time.time() - 1
        path.write_text(json.dumps(value))
        self.assertFalse(op.write_result(self.result(command)))
        self.assertEqual(json.loads((op.ROOT / op.RESULT_NAME).read_text())["transport_state"], "EXPIRED")

    def test_submit_timeout_cleans_pending_without_replaying(self):
        command = op.make_command("SNAPSHOT")
        with self.assertRaisesRegex(op.WebOperatorError, "OPERATOR_TIMEOUT"):
            op.submit(command, timeout=.05)
        self.assertFalse((op.ROOT / op.COMMAND_NAME).exists())
        self.assertFalse((op.ROOT / op.ACTIVE_NAME).exists())
        with self.assertRaisesRegex(op.WebOperatorError, "COMMAND_ALREADY_FINISHED"):
            op.submit(command, timeout=.05)

    def test_restart_after_tombstone_write_cleans_claim(self):
        command = self.pending("CLICK")
        op.take_command(owner="old-host")
        (op.ROOT / op.HISTORY_NAME).write_text(json.dumps([
            {"command_id": command["command_id"], "state": "COMPLETED"}]))
        self.assertIsNone(op.take_command(owner="new-host"))
        self.assertFalse((op.ROOT / op.ACTIVE_NAME).exists())
        self.assertEqual(json.loads((op.ROOT / op.RESULT_NAME).read_text())["reason_code"], "OPERATOR_INTERRUPTED")

    def test_result_authority_and_action_bound_to_claim(self):
        command = self.pending()
        op.take_command()
        result = self.result(command)
        result.update(action="CLICK", action_authority="OTHER", text="x" * 10000,
                      links=[{"t": "y" * 1000, "h": "z" * 10000}] * 100)
        self.assertTrue(op.write_result(result))
        result = json.loads((op.ROOT / op.RESULT_NAME).read_text())
        self.assertEqual(result["action"], "SNAPSHOT")
        self.assertEqual(result["action_authority"], "NONE")
        self.assertEqual(len(result["text"]), 8000)
        self.assertEqual(len(result["links"]), 40)
        self.assertEqual(len(result["links"][0]["h"]), 2000)

    def test_deadlines_are_finite(self):
        command = op.make_command("SNAPSHOT")
        for deadline in (float("nan"), float("inf"), True, -1):
            with self.assertRaises(op.WebOperatorError):
                op.validate_command({**command, "expires_at": deadline})

    def test_completed_id_not_replayable_after_display_history_eviction(self):
        first = None
        for _ in range(66):
            command = self.pending()
            if first is None:
                first = command
            op.take_command()
            self.assertTrue(op.write_result(self.result(command)))
        self.assertLessEqual(len(json.loads((op.ROOT / op.HISTORY_NAME).read_text())), 64)
        (op.ROOT / op.COMMAND_NAME).write_text(json.dumps(first))
        self.assertIsNone(op.take_command())
        self.assertFalse((op.ROOT / op.COMMAND_NAME).exists())
        with self.assertRaisesRegex(op.WebOperatorError, "COMMAND_ALREADY_FINISHED"):
            op.submit(first, timeout=.05)

    def test_partial_pending_or_active_record_does_not_wedge_next_job(self):
        for name in (op.COMMAND_NAME, op.ACTIVE_NAME):
            (op.ROOT / name).write_text('{"schema":')
            self.assertIsNone(op.take_command())
            self.assertFalse((op.ROOT / name).exists())
            command = self.pending()
            self.assertEqual(op.take_command()["command_id"], command["command_id"])
            self.assertTrue(op.write_result(self.result(command)))

    def test_crash_before_atomic_pending_replace_leaves_no_partial_command(self):
        command = op.make_command("SNAPSHOT")
        original = op.atomic_replace
        def crash(source, target):
            if target.name == op.COMMAND_NAME:
                self.assertTrue(source.is_file())
                self.assertEqual(json.loads(source.read_text())["command_id"], command["command_id"])
                self.assertFalse(target.exists())
                raise OSError("Synthetic publication interruption")
            original(source, target)
        with patch.object(op, "atomic_replace", side_effect=crash):
            with self.assertRaises(OSError):
                op.submit(command, timeout=.05)
        self.assertFalse((op.ROOT / op.COMMAND_NAME).exists())
        self.assertFalse(list(op.ROOT.glob(".record-*")))
        next_command = self.pending()
        self.assertEqual(op.take_command()["command_id"], next_command["command_id"])


if __name__ == "__main__":
    unittest.main()
