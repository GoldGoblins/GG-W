"""Real Qt event delivery and bounded UI calls with delayed offline work."""
from pathlib import Path
import json
import math
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from backend.crypto_ui_runtime import CryptoUiRuntime
from backend import crypto_host as host


def payload():
    return {"wallet": {"pubkey": "1" * 32}, "lab": {"label": "LAB ON", "healthy": True},
            "chart": {"closes": list(range(5000))}, "holdings": [{"symbol": "SOL"}]}


class UiRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def wait(self, condition, timeout=3):
        until = time.monotonic() + timeout
        while not condition() and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.002)
        self.app.processEvents()
        self.assertTrue(condition(), "Offline worker did not finish")

    def test_snapshot_and_serialization_never_own_ui_lock(self):
        entered, release = threading.Event(), threading.Event()
        runtime = CryptoUiRuntime(snapshot=payload, ttl=60)
        self.addCleanup(runtime.close)
        original = CryptoUiRuntime._encode
        def encode(value):
            entered.set()
            release.wait(2)
            return original(value)
        samples = []
        with patch.object(CryptoUiRuntime, "_encode", side_effect=encode):
            runtime.snapshot()
            self.assertTrue(entered.wait(1))
            try:
                for _ in range(1000):
                    started = time.perf_counter()
                    runtime.snapshot()
                    samples.append((time.perf_counter()-started)*1000)
                self.assertLess(max(samples), 16.7)
                # Submission also uses prepared JSON while the serializer waits.
                started = time.perf_counter()
                raw = runtime.submit("offline_action", lambda: {})
                self.assertLess((time.perf_counter()-started)*1000, 16.7)
                self.assertEqual(json.loads(raw)["ui_operation"]["state"], "running")
            finally:
                release.set()
            self.wait(lambda: not runtime._running)
        print(json.dumps({"cached_ui_reads": 1000, "p95_ms": round(sorted(samples)[949], 4),
                          "max_ms": round(max(samples), 4), "worker_serializer_delayed": True}))

    def test_one_action_and_matching_rail_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        calls, updates = [], []
        def action():
            calls.append(threading.get_ident())
            entered.set()
            release.wait(2)
            return {}
        runtime = CryptoUiRuntime(snapshot=payload, ttl=60)
        self.addCleanup(runtime.close)
        runtime.updated.connect(updates.append)
        runtime.submit("test", action)
        self.assertTrue(entered.wait(1))
        for _ in range(20):
            runtime.submit("test", action)
        release.set()
        self.wait(lambda: not runtime._running and len(updates) >= 2)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], threading.get_ident())
        full, rail = json.loads(runtime.snapshot()), json.loads(runtime.snapshot(rail=True))
        for key in ("wallet", "lab", "holdings", "ui_operation"):
            self.assertEqual(full[key], rail[key])
        self.assertNotIn("chart", rail)
        self.assertEqual(full["ui_operation"]["state"], "done")

    def test_errors_keep_last_good_snapshot_and_hide_exception_values(self):
        runtime = CryptoUiRuntime(snapshot=payload, ttl=60)
        self.addCleanup(runtime.close)
        runtime.snapshot()
        self.wait(lambda: not runtime._running)
        def broken():
            raise ValueError("private-value-must-not-be-echoed")
        runtime.submit("fixture", broken)
        self.wait(lambda: not runtime._running)
        raw = runtime.snapshot()
        self.assertNotIn("private-value", raw)
        self.assertEqual(json.loads(raw)["ui_operation"]["error"], "ValueError")
        self.assertTrue(json.loads(raw)["lab"]["healthy"])

    def test_shutdown_discards_unstarted_action_and_queued_publication(self):
        entered, release = threading.Event(), threading.Event()
        calls, updates = [], []
        def slow():
            entered.set(); release.wait(2)
            return payload()
        runtime = CryptoUiRuntime(snapshot=slow)
        runtime.updated.connect(updates.append)
        runtime.snapshot()
        self.assertTrue(entered.wait(1))
        runtime.submit("must_not_run", lambda: calls.append(True))
        runtime.close()
        release.set()
        self.wait(lambda: not runtime._running)
        self.assertEqual(calls, [])
        # The running notice was delivered synchronously before close; no
        # completed snapshot arrives after close.
        self.assertTrue(all(json.loads(raw)["ui_operation"].get("state") == "running" for raw in updates))

    def test_thread_start_failure_can_be_retried(self):
        runtime = CryptoUiRuntime(snapshot=payload, ttl=60)
        self.addCleanup(runtime.close)
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("fixture")):
            result = json.loads(runtime.submit("retry", lambda: {}))
        self.assertEqual(result["ui_operation"]["error"], "CRYPTO_WORKER_START")
        runtime.submit("retry", lambda: {})
        self.wait(lambda: not runtime._running)
        self.assertEqual(json.loads(runtime.snapshot())["ui_operation"]["state"], "done")

    def test_host_slots_queue_work_and_decode_windows_file_url(self):
        from backend.chat_surface_host import ChatSurfaceHost
        runtime = CryptoUiRuntime(snapshot=payload, ttl=60)
        self.addCleanup(runtime.close)
        class Facade:
            _crypto_runtime = ChatSurfaceHost._crypto_runtime
            _crypto_async = ChatSurfaceHost._crypto_async
            _crypto_ui = runtime
        facade = Facade()
        seen = []
        with patch.object(host, "import_keypair_file", side_effect=lambda path: seen.append(path) or {}):
            raw = ChatSurfaceHost.cryptoImportKeypair(facade, "file:///C:/synthetic%20fixture/keypair.json")
            self.assertEqual(json.loads(raw)["ui_operation"]["name"], "import_wallet")
            self.wait(lambda: not runtime._running)
        self.assertEqual(seen, ["C:/synthetic fixture/keypair.json"])

    def test_running_reset_never_reenters_nonreentrant_job_lock(self):
        for reset, lock_name, job_name, read in (
            (host.reset_strategy_factory, "_strategy_factory_lock", "_strategy_factory_job", host.strategy_factory_status),
            (host.reset_desk, "_desk_lock", "_desk_job", host.desk_status),
        ):
            done = threading.Event()
            with patch.object(host, lock_name, threading.Lock()), patch.dict(getattr(host, job_name), state="running"), \
                 patch.object(host, "status_payload", side_effect=lambda: read()):
                thread = threading.Thread(target=lambda: (reset(), done.set()), daemon=True)
                thread.start()
                self.assertTrue(done.wait(1), "Reset deadlocked on its own job lock")

    def test_failed_rpc_preserves_known_balance_and_old_generation_cannot_return(self):
        key = ("1"*32, "testnet")
        with patch.dict(host._rpc_bundle, {key: (1., 10, [{"symbol": "fixture"}])}, clear=True), \
             patch.dict(host._rpc_errors, {}, clear=True), patch.dict(host._rpc_retry_after, {}, clear=True), \
             patch.object(host, "fetch_balance", return_value=15), \
             patch.object(host, "fetch_tokens", side_effect=RuntimeError("offline")):
            host._refresh_bundle(*key, host._rpc_generation)
            self.assertEqual(host._rpc_bundle[key][1], 10)
            self.assertEqual(host._rpc_errors[key], "RPC_UNREACHABLE")
        with patch.dict(host._rpc_bundle, {}, clear=True), patch.object(host, "fetch_balance", return_value=15), \
             patch.object(host, "fetch_tokens", return_value=[]):
            host._refresh_bundle(*key, host._rpc_generation-1)
            self.assertNotIn(key, host._rpc_bundle)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
