from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from backend import action_task_continuity as C
from backend import control_plane_contract as K
import main as W


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def legacy_record() -> dict[str, object]:
    return {
        "schema":
            "gg.workbench.control-task.v1",
        "task_id":
            "task-11111111111111111111111111111111",
        "kind": "SELFDEV",
        "status": "DONE",
        "goal": "legacy done task",
        "context_reference": "@current",
        "workspace_object_id":
            "ws.file.context-composer",
        "base_head": "",
        "candidate_sha256": "",
        "diff_sha256": "",
        "grant_sha256": "",
        "write_proposal_id": "",
        "write_candidate_sha256": "",
        "write_before_sha256": "",
        "parent_task_id": "",
        "last_reason": "APPLIED_VERIFIED",
        "created_seq": 1,
        "updated_seq": 0,
        "logs": [],
    }


def pending(
    binding: str = SHA_A,
) -> dict[str, object]:
    return {
        "pending_id":
            "mandate-11111111111111111111111111111111",
        "session_id":
            "mandate-session-test",
        "status": "WAITING_APPROVAL",
        "context_reference": "@current",
        "workspace_object_id":
            "ws.file.context-composer",
        "manifest_sha256": SHA_D,
        "request_capture_sha256": SHA_B,
        "approval_scope_revision": SHA_C,
        "user_text":
            "Inspect the exact current workspace source.",
        "route_why":
            "Verify the selected local source.",
        "action_intent": {
            "task_id":
                "chat-11111111111111111111111111111111",
            "binding_sha256": binding,
            "state_base_revision": SHA_B,
            "target_object_id":
                "ws.file.context-composer",
            "target_source_revision": SHA_C,
            "capability_human_id":
                "tool.safe.dispatch",
        },
        "mandate_result": {
            "result": "MANDATE_REQUIRED",
        },
        "evaluation_context": {
            "source_envelope": {
                "ready_core": {
                    "goal":
                        "Inspect current workspace source.",
                },
            },
        },
        "approval_receipt": None,
        "approver_id": None,
        "mandate_assertion_sha256": None,
        "execution_eligibility": None,
        "execution_state": "UNUSED",
        "execution_receipt": None,
        "action_effect_recovery": None,
        "action_done_when": None,
        "execution_eligibility_binding_sha256":
            None,
        "execution_safe_tool_request_sha256":
            None,
        "execution_evidence_path": None,
    }


class D72TaskContinuityTests(
    unittest.TestCase
):
    def test_v1_import_is_read_only_and_v2_durable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            legacy = base / "legacy"
            durable = base / "durable"

            legacy.mkdir(mode=0o700)

            source = (
                legacy
                / (
                    "task-"
                    "11111111111111111111111111111111"
                    ".json"
                )
            )

            source.write_text(
                json.dumps(
                    legacy_record(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            source.chmod(0o600)

            before = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()

            ledger = K.TaskLedger(
                durable,
                legacy_root=legacy,
            )

            record = ledger.get(
                "task-"
                "11111111111111111111111111111111"
            )

            self.assertIsNotNone(record)
            assert record is not None

            self.assertEqual(
                record["schema"],
                "gg.workbench.control-task.v2",
            )
            self.assertEqual(
                record["kind"],
                "SELFDEV",
            )
            self.assertEqual(
                record["status"],
                "DONE",
            )

            after = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()

            self.assertEqual(
                before,
                after,
            )

            self.assertEqual(
                stat.S_IMODE(
                    durable.stat().st_mode
                ),
                0o700,
            )
            self.assertEqual(
                stat.S_IMODE(
                    (durable / "objects")
                    .stat()
                    .st_mode
                ),
                0o700,
            )

    def test_content_addressed_objects_are_append_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "ledger"
            ledger = K.TaskLedger(root)

            value = {
                "schema": "fixture.v1",
                "value": 42,
            }

            first = ledger.put_object(value)
            second = ledger.put_object(value)

            self.assertEqual(
                first,
                second,
            )

            objects = list(
                (root / "objects").glob("*.json")
            )

            self.assertEqual(
                len(objects),
                1,
            )
            self.assertEqual(
                stat.S_IMODE(
                    objects[0].stat().st_mode
                ),
                0o600,
            )
            self.assertEqual(
                ledger.get_object(first),
                value,
            )

    def test_action_continuity_survives_reload_and_blocks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "ledger"
            ledger = K.TaskLedger(root)
            value = pending()

            first = C.capture_action_task(
                ledger,
                value,
            )

            self.assertEqual(
                first["status"],
                "WAITING_FOR_USER",
            )
            self.assertEqual(
                first["original_intent"],
                value["user_text"],
            )
            self.assertEqual(
                first["state_base_revision"],
                SHA_B,
            )

            value["status"] = "APPROVED_VALID"
            value["approval_receipt"] = {
                "result": "APPROVED",
            }
            value["approver_id"] = "human:test"
            value[
                "mandate_assertion_sha256"
            ] = SHA_D

            approved = (
                C.record_action_approval(
                    ledger,
                    value,
                )
            )

            self.assertEqual(
                approved["status"],
                "APPROVED",
            )

            value["status"] = "EXECUTION_RUNNING"
            value["execution_state"] = "DISPATCHED"
            value["execution_eligibility"] = {
                "result": "EXECUTION_ELIGIBLE",
            }

            running = (
                C.record_action_dispatch(
                    ledger,
                    value,
                )
            )

            self.assertEqual(
                running["status"],
                "RUNNING",
            )

            value["status"] = "ACTION_EXECUTED"
            value["execution_state"] = (
                "CONSUMED_PASS"
            )
            value["execution_receipt"] = {
                "result": "ACTION_EXECUTED",
                "action_executed": True,
            }
            value[
                "actual_effect_observation"
            ] = {
                "actual_effect_verified": True,
            }
            value["action_effect_recovery"] = {
                "result": "NO_RECOVERY_REQUIRED",
            }
            value["action_done_when"] = {
                "result": "EVIDENCE_REQUIRED",
                "reason_code":
                    "SEMANTIC_EVIDENCE_REQUIRED",
                "semantic_done": False,
                "done_when":
                    "TASK_COMPLETION_CONTRACT_SHA256="
                    + SHA_A,
            }

            blocked = (
                C.record_action_completion(
                    ledger,
                    value,
                )
            )

            self.assertEqual(
                blocked["status"],
                "BLOCKED",
            )
            self.assertEqual(
                blocked["last_reason"],
                "SEMANTIC_EVIDENCE_REQUIRED",
            )
            self.assertEqual(
                blocked["action_replay_state"],
                "CONSUMED_PASS",
            )
            self.assertEqual(
                blocked["done_when"],
                (
                    "TASK_COMPLETION_CONTRACT_SHA256="
                    + SHA_A
                ),
            )
            self.assertFalse(
                C.replay_reusable(
                    str(
                        blocked[
                            "action_replay_state"
                        ]
                    )
                )
            )

            for key in (
                "continuity_sha256",
                "mandate_sha256",
                "evidence_sha256",
                "effects_sha256",
            ):
                self.assertEqual(
                    len(str(blocked[key])),
                    64,
                )

            reloaded = K.TaskLedger(root)
            restored = reloaded.get(
                str(blocked["task_id"])
            )

            self.assertEqual(
                restored,
                blocked,
            )

    def test_nonterminal_action_reload_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "ledger"
            ledger = K.TaskLedger(root)

            first = C.capture_action_task(
                ledger,
                pending(SHA_C),
            )

            self.assertEqual(
                first["status"],
                "WAITING_FOR_USER",
            )

            reloaded = K.TaskLedger(root)
            record = reloaded.get(
                str(first["task_id"])
            )

            assert record is not None

            self.assertEqual(
                record["status"],
                "BLOCKED",
            )
            self.assertEqual(
                record["last_reason"],
                (
                    "WORKBENCH_RESTART_"
                    "REQUIRES_REVALIDATION_NO_REPLAY"
                ),
            )
            self.assertEqual(
                record["action_replay_state"],
                "RESTART_BLOCKED",
            )
            self.assertFalse(
                C.replay_reusable(
                    str(
                        record[
                            "action_replay_state"
                        ]
                    )
                )
            )

    def test_semantic_pass_can_close_without_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ledger = K.TaskLedger(
                Path(raw) / "ledger"
            )
            value = pending(SHA_D)

            C.capture_action_task(
                ledger,
                value,
            )

            value["status"] = "APPROVED_VALID"
            C.record_action_approval(
                ledger,
                value,
            )

            value["status"] = "EXECUTION_RUNNING"
            value["execution_state"] = "DISPATCHED"
            C.record_action_dispatch(
                ledger,
                value,
            )

            value["status"] = "ACTION_EXECUTED"
            value["execution_state"] = (
                "CONSUMED_PASS"
            )
            value["execution_receipt"] = {
                "result": "ACTION_EXECUTED",
            }
            value["action_done_when"] = {
                "result": "PASS",
                "semantic_done": True,
                "done_when":
                    "TASK_COMPLETION_CONTRACT_SHA256="
                    + SHA_D,
                "action_authority": "NONE",
                "general_action_authority": "NONE",
            }

            done = (
                C.record_action_completion(
                    ledger,
                    value,
                )
            )

            self.assertEqual(
                done["status"],
                "DONE",
            )
            self.assertEqual(
                done["last_reason"],
                "DONE_WHEN_VERIFIED",
            )

    def test_resume_action_never_dispatches_child(
        self,
    ) -> None:
        record = {
            "task_id":
                "task-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "kind": "ACTION",
            "status": "BLOCKED",
        }

        class Fake:
            calls = 0

            def _task_record(
                self,
                _task_id: str,
            ) -> dict[str, object]:
                return record

            def _submit_selfdev(
                self,
                *_args: object,
                **_kwargs: object,
            ) -> None:
                self.calls += 1
                raise AssertionError(
                    "SELFDEV_REPLAY"
                )

            def _submit_autonomy(
                self,
                *_args: object,
                **_kwargs: object,
            ) -> None:
                self.calls += 1
                raise AssertionError(
                    "AUTONOMY_REPLAY"
                )

            def _active(self) -> bool:
                return False

        fake = Fake()

        output = W.ChatBridge._resume_task(
            fake,
            str(record["task_id"]),
            "@current",
            "ws.file.context-composer",
        )

        self.assertIn(
            "ACTION_REVALIDATION_REQUIRED=",
            output,
        )
        self.assertIn(
            "REPLAY=FORBIDDEN",
            output,
        )
        self.assertIn(
            "NEW_TASK_ID=NONE",
            output,
        )
        self.assertEqual(
            fake.calls,
            0,
        )

    def test_machine_graph_represents_real_d72_contacts(
        self,
    ) -> None:
        source = (
            Path(W.__file__)
            .read_text(
                encoding="utf-8",
                errors="strict",
            )
        )

        expected = (
            (
                "call-94",
                "action_task_continuity."
                "capture_action_task",
            ),
            (
                "call-95",
                "action_task_continuity."
                "record_action_approval",
            ),
            (
                "call-96",
                "action_task_continuity."
                "record_action_dispatch",
            ),
            (
                "call-97",
                "action_task_continuity."
                "record_action_completion",
            ),
        )

        for edge_id, contact in expected:
            self.assertEqual(
                source.count(
                    '"' + edge_id + '"'
                ),
                1,
            )
            self.assertGreaterEqual(
                source.count(contact),
                2,
            )

        self.assertIn(
            '"ACTION_TASK_CONTINUITY"',
            source,
        )

    def test_main_remains_inside_source_envelope(
        self,
    ) -> None:
        main = Path(W.__file__)

        self.assertLessEqual(
            len(main.read_bytes()),
            327680,
        )


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        D72TaskContinuityTests
    )
    result = unittest.TextTestRunner(
        verbosity=1
    ).run(suite)

    if not result.wasSuccessful():
        return 1

    print(
        "D72_TASK_CONTINUITY=PASS"
    )
    print(
        "ORIGINAL_INTENT_CONTINUITY=PASS"
    )
    print(
        "ACTION_RESTART_REPLAY=FORBIDDEN"
    )
    print(
        "SEMANTIC_EVIDENCE_REQUIRED=BLOCKED"
    )
    print(
        "ACTION_AUTHORITY=NONE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
