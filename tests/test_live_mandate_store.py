#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import importlib.util

from backend import live_mandate_store as store_mod
from backend import task_scoped_action_grant as grant_mod
from backend.application_paths import SUPPORT_ROOT
from backend.platform_support import private_runtime_root, workspace_root

REPO = SUPPORT_ROOT


def _load_k7k():
    path = REPO / "cognitive-core" / "gg_mandate_approval.py"
    spec = importlib.util.spec_from_file_location(
        "gg_mandate_approval_locked_for_store_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("K7K_LOADER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pending(
    *,
    capture: str,
    scope: str,
    risk: str = "YELLOW",
    requirement: str = "EXPLICIT_REQUIRED",
) -> dict[str, object]:
    return {
        "pending_id": "mandate-" + capture[:32],
        "request_capture_sha256": capture,
        "approval_scope_revision": scope,
        "action_intent": {
            "capability_human_id": "tool.safe.dispatch",
            "target_object_id": "ws.file.context-composer",
            "target_source_revision": "a" * 64,
            "binding_sha256": "b" * 64,
        },
        "mandate_result": {
            "task_id": "chat-" + capture[:32],
            "mandate_requirement": requirement,
            "approval_request": {
                "origin_id": "workbench-" + scope[:32],
                "task_id": "chat-" + capture[:32],
                "approval_scope": {
                    "ready_core": {"risk_class": risk},
                },
            },
        },
    }


def _receipt(capture: str, scope: str, assertion: str) -> dict[str, object]:
    return {
        "schema": "gg.mandate-evaluation-result.v1",
        "request_capture_sha256": capture,
        "approval_scope_revision": scope,
        "current_approval_scope_revision": scope,
        "mandate_assertion_sha256": assertion,
        "result": "MANDATE_VALID",
        "reason_code": "APPROVAL_SCOPE_MATCH",
    }


class LiveMandateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="gg-mandate-store-",
            dir=private_runtime_root(),
        )
        self.store = store_mod.MandateStore(Path(self.tmp.name))
        self.store.initialize()
        self.capture = "c" * 64
        self.scope = "d" * 64

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_green_does_not_use_store(self) -> None:
        green = grant_mod.green_path_no_grant()
        self.assertEqual(green["action_authority"], "NONE")
        self.assertEqual(green["general_action_authority"], "NONE")
        self.assertEqual(green["reason_code"], "GREEN_RISK_CLASS")
        self.assertEqual(green["mandate_requirement"], "NOT_REQUIRED")

    def test_green_pending_rejected(self) -> None:
        pending = _pending(
            capture=self.capture,
            scope=self.scope,
            risk="GREEN",
            requirement="NOT_REQUIRED",
        )
        with self.assertRaises(store_mod.LiveMandateStoreError):
            store_mod.put_pending(self.store, pending)

    def test_pending_approve_grant_and_replay(self) -> None:
        pending = _pending(capture=self.capture, scope=self.scope)
        first = store_mod.put_pending(self.store, pending)
        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(first["action_authority"], "NONE")
        self.assertEqual(first["general_action_authority"], "NONE")

        with self.assertRaises(store_mod.LiveMandateStoreError):
            store_mod.put_pending(self.store, pending)

        assertion = "e" * 64
        approved = store_mod.approve(
            self.store,
            request_capture_sha256=self.capture,
            approval_scope_revision=self.scope,
            approver_id="human:owner",
            mandate_assertion_sha256=assertion,
            evaluation_receipt=_receipt(self.capture, self.scope, assertion),
        )
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["seq"], 2)

        with self.assertRaises(store_mod.LiveMandateStoreError) as replay:
            store_mod.approve(
                self.store,
                request_capture_sha256=self.capture,
                approval_scope_revision=self.scope,
                approver_id="human:owner",
                mandate_assertion_sha256=assertion,
                evaluation_receipt=_receipt(
                    self.capture, self.scope, assertion
                ),
            )
        self.assertIn("MANDATE_STATE_INVALID", str(replay.exception))

        grant = grant_mod.issue_from_approved_record(approved)
        self.assertEqual(grant["action_authority"], "TASK_SCOPED")
        self.assertEqual(grant["general_action_authority"], "TASK_SCOPED")
        self.assertEqual(grant["scope_authority"], "ALL_TASK_SCOPED_EFFECTS")
        self.assertEqual(grant["grant_status"], "ACTIVE")
        for effect in (
            "network",
            "production",
            "one.com",
            "credentials",
            "deploy",
            "write",
            "sudo",
        ):
            self.assertNotIn(effect, grant["forbidden_scope"])
            authorization = grant_mod.authorize_effect(
                grant,
                effect=effect,
                current_target_object_id="ws.file.context-composer",
                current_target_source_revision="a" * 64,
            )
            self.assertEqual(
                authorization["action_authority"],
                "TASK_SCOPED",
            )
            self.assertEqual(
                authorization["general_action_authority"],
                "TASK_SCOPED",
            )
            self.assertEqual(
                authorization["scope_authority"],
                "ALL_TASK_SCOPED_EFFECTS",
            )
            self.assertEqual(
                grant_mod.validate_authorization(authorization),
                authorization,
            )
        bound = grant_mod.bind_current_target(
            grant,
            current_target_object_id="ws.file.context-composer",
            current_target_source_revision="a" * 64,
        )
        self.assertEqual(bound["grant_sha256"], grant["grant_sha256"])
        with self.assertRaises(grant_mod.TaskScopedActionGrantError):
            grant_mod.bind_current_target(
                grant,
                current_target_object_id="ws.file.context-composer",
                current_target_source_revision="f" * 64,
            )

        consumed = store_mod.consume(
            self.store,
            request_capture_sha256=self.capture,
            approval_scope_revision=self.scope,
        )
        self.assertEqual(consumed["status"], "CONSUMED")
        with self.assertRaises(store_mod.LiveMandateStoreError) as consumed_replay:
            store_mod.consume(
                self.store,
                request_capture_sha256=self.capture,
                approval_scope_revision=self.scope,
            )
        self.assertIn("REPLAY_FORBIDDEN", str(consumed_replay.exception))

    def test_reject_and_scope_drift(self) -> None:
        pending = _pending(capture=self.capture, scope=self.scope)
        store_mod.put_pending(self.store, pending)
        rejected = store_mod.reject(
            self.store,
            request_capture_sha256=self.capture,
            approval_scope_revision=self.scope,
        )
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIsNone(rejected["mandate_assertion_sha256"])

        other = "1" * 64
        store_mod.put_pending(
            self.store,
            _pending(capture=other, scope=self.scope),
        )
        with self.assertRaises(store_mod.LiveMandateStoreError):
            store_mod.approve(
                self.store,
                request_capture_sha256=other,
                approval_scope_revision="2" * 64,
                approver_id="human:owner",
                mandate_assertion_sha256="3" * 64,
                evaluation_receipt=_receipt(other, "2" * 64, "3" * 64),
            )

    def test_bridge_capture_persists_pending(self) -> None:
        import types
        import main as workbench
        from backend import action_intent_contract
        from backend import capability_registry
        from backend import idekompass_decision_ingress as ingress

        project = Path(__file__).resolve().parents[1]
        repo = workspace_root()
        registry = capability_registry.CapabilityRegistry.load(
            repo_root=repo,
            project_root=project,
            seed_path=project / "config" / "capability-seeds-v1.json",
            manifest_path=project / "SOURCE-MANIFEST.json",
        )
        workspace = {
            "object_id": "ws.file.context-composer",
            "source_path": "qml/components/ContextComposer.qml",
            "sha256": "a" * 64,
        }
        route = types.SimpleNamespace(
            intent="EDIT",
            route_mode="SOURCE_BOUND_LASER",
            primary_capability="tool.safe.dispatch",
            automatic_model_dispatch=False,
            registered_capability_execution=False,
            why="Store capture wiring test.",
        )
        ledger_tmp = tempfile.TemporaryDirectory(
            prefix="gg-mandate-ledger-",
            dir=private_runtime_root(),
        )
        self.addCleanup(ledger_tmp.cleanup)
        bridge = types.SimpleNamespace(
            _intent_capability_registry=registry,
            _mandate_session_id="mandate-session-store-test",
            _pending_mandates={},
            _live_mandate_store=self.store,
            _task_ledger=workbench.control_contract.TaskLedger(
                Path(ledger_tmp.name),
            ),
        )
        messages: list[tuple[object, ...]] = []
        bridge._append = lambda *args: messages.append(args)
        proposal = workbench.ChatBridge._natural_action_proposal(
            bridge,
            route,
            workspace,
        )
        self.assertIsInstance(proposal, dict)
        self.assertEqual(proposal["risk_floor"], "YELLOW")
        validated = action_intent_contract.validate_action_proposal(proposal)
        decision = ingress.decide(
            user_text="Inspect the verified current workspace source.",
            workspace_context=workspace,
            route_decision=route,
            information_available=True,
            assigned_participant="GG-AI-installator",
            creator_actor="human:owner",
            action_proposal=validated,
        )
        self.assertEqual(decision["decision_kind"], "PLAN_ACTION")
        mandate = decision["orchestrator_mandate"]
        self.assertEqual(mandate["mandate_requirement"], "EXPLICIT_REQUIRED", mandate.get("reason_code"))
        pending_id = workbench.ChatBridge._capture_pending_mandate(
            bridge,
            mandate_result=mandate,
            action_intent=decision["action_intent"],
            user_text="Inspect the verified current workspace source.",
            route_decision=route,
            context_reference="@current",
            workspace_object_id="ws.file.context-composer",
        )
        stored = self.store.get(str(bridge._pending_mandates[pending_id]["request_capture_sha256"]))
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "PENDING")
        self.assertEqual(stored["action_authority"], "NONE")
        self.assertEqual(stored["general_action_authority"], "NONE")

    def test_k7k_authority_unchanged(self) -> None:
        mandate = _load_k7k()
        self.assertEqual(mandate.ACTION_AUTHORITY, "NONE")
        self.assertEqual(mandate.LIVE_MANDATE_STORE, "NO")
        self.assertEqual(mandate.MANDATE_VALID_IS_ACTION_AUTHORITY, "NO")

    def test_this_task_is_red_and_allows_task_scoped_effects(self) -> None:
        task = grant_mod.THIS_TASK
        self.assertEqual(task["risk_class"], "RED")
        self.assertNotIn("one.com", task["forbidden_scope"])
        self.assertNotIn("credentials", task["forbidden_scope"])
        self.assertIn("approval bypass", task["forbidden_scope"])
        self.assertIn("GENERAL_ACTION_AUTHORITY other than TASK_SCOPED", task["forbidden_scope"])

    def test_one_com_named_mandate_is_red_and_task_scoped(self) -> None:
        task = grant_mod.ONE_COM_MANDATE
        self.assertEqual(task["risk_class"], "RED")
        self.assertIn("one.com login and production read/write/deploy", task["scope"])
        self.assertNotIn("autonomous one.com login", task["forbidden_scope"])
        self.assertNotIn("agent-held credentials", task["forbidden_scope"])
        self.assertIn("GENERAL_ACTION_AUTHORITY other than TASK_SCOPED", task["forbidden_scope"])

if __name__ == "__main__":
    unittest.main()
