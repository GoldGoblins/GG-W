"""CLI safety/measurement contracts; all engines and transports are synthetic."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "support/gg-consensus/benchmark.py"
spec = importlib.util.spec_from_file_location("gg_benchmark_cli_test", SOURCE)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class Process:
    def __init__(self): self.stopped = False
    def poll(self): return 0 if self.stopped else None


class Connection:
    calls = 0
    def __init__(self, host, port, **_kwargs): self.host = host; self.port = port
    def request(self, *_args, **_kwargs): Connection.calls += 1
    def getresponse(self): return object()


class Hardhat:
    SUPPLY = 1_000_000 * 10**6
    def __init__(self):
        self._closed = False; self._process = None; self._port = 0; self._session = ""; self._accounts = []
        self.http = SimpleNamespace(client=SimpleNamespace(HTTPConnection=Connection))
        self._rpc_stats = dict(requests=0, members=0, batches=0); self._measurements = []
        self._contract = "synthetic-public-contract"; self.height = 0; self.transfers = []; self.stops = 0; self.starts = 0
        self.created_process = None
    def start(self):
        self.starts += 1; self._process = self.created_process = Process(); self._port = 52001
        self._session = "synthetic-private-session"; self._accounts = ["synthetic-public-account-" + str(i) for i in range(4)]
    def stop(self):
        self.stops += 1
        if self._process: self._process.stopped = True
        self._process = None; self._port = 0
    def _owns_listener(self): return True
    def _rpc(self, method, _params):
        self._rpc_stats["requests"] += 1; self._rpc_stats["members"] += 1
        connection = self.http.client.HTTPConnection("127.0.0.1", self._port)
        connection.request("POST", "/", body="synthetic-private-input-not-for-logging"); connection.getresponse()
        return {"number": hex(self.height)} if method == "eth_getBlockByNumber" else hex(self.SUPPLY)
    def deploy_token(self): self._rpc("deploy", []); self.height += 1
    def prepare(self, source, target, amount, asset):
        self._rpc("prepare", []); self.transfers.append((source, target, amount, asset))
        return {"review": {"id": "synthetic-private-review", "review_digest": "f"*64}}
    def send(self, _identifier, _digest):
        self._rpc("send", []); self.height += 1
        self._measurements.append(dict(operation="transaction", state="CONFIRMED", elapsed_ms=1.25))
        return {"transactions": [{"state": "CONFIRMED", "txid": "0x" + f"{self.height:064x}"}]}
    def _balance(self, _address, _token): self._rpc("balance", []); return 250000
    def _quantity(self, value): return int(value, 16)
    def _resource_metrics(self): return dict(memory_committed_bytes=1048576, cpu_seconds=.125)


class Consensus:
    SUPPLY = 1_000_000 * 10**6
    def __init__(self):
        self._closed = False; self._nodes = []; self._genesis = None; self._accounts = []; self._temporary = None
        self._execution_cache = {}; self.stops = 0; self.starts = 0; self.requested = None
        self.http = SimpleNamespace(client=SimpleNamespace(HTTPConnection=Connection))
    def start(self):
        self.starts += 1; self._genesis = {"private": "NEVER_PUBLISH"}
        self._nodes = [{"process": Process(), "rpc_port": 52000+i} for i in range(4)]
    def _owned(self, _index): return True
    def stop(self):
        self.stops += 1
        for row in self._nodes: row["process"].stopped = True
        self._nodes = []; self._genesis = None
    def benchmark(self, count):
        self.requested = count
        connection = self.http.client.HTTPConnection("127.0.0.1", 52000)
        connection.request("GET", "/synthetic-sensitive-private-input"); connection.getresponse()
        self._execution_cache = {f"{i:064x}": {"height": 1, "certificate_height": 2, "raw": b"PRIVATE_RAW"} for i in range(count)}
        return {"benchmark": {"state": "PASS", "count": count, "successful": count, "unique_finalized": count,
                              "state_matches_expected": True, "p50_ms": 10, "p95_ms": 20, "p99_ms": 25,
                              "elapsed_seconds": .1, "tps": count*10, "verified_blocks": 1,
                              "mode": "PIPELINED_BLOCK_VERIFICATION", "independent_senders": 4,
                              "scope": "LOCAL_FIXED_VALIDATORS", "validators": 4, "physical_hosts": 1,
                              "secret_key": "NEVER_PUBLISH"},
                "proof": {"verified": True, "validator_count": 4, "quorum_required": 3, "state_height": 1, "certificate_height": 2},
                "online": 4, "validators": [{"identity_verified": True, "memory_private_bytes": 1048576,
                                             "cpu_seconds": .25, "pid": 515151, "rpc_url": "NEVER_PUBLISH"} for _ in range(4)],
                "accounts": [{"atomic": str(self.SUPPLY//4), "address": "NEVER_PUBLISH"} for _ in range(4)],
                "keys": "NEVER_PUBLISH"}


class BenchmarkCliTests(unittest.TestCase):
    def execute(self, engine, service, count=None):
        with patch.object(benchmark, "hardware", return_value={"synthetic": True}), patch.object(benchmark, "software", return_value={"python": "test"}):
            return benchmark.execute(engine, count, service=service)

    def test_import_and_help_have_no_backend_or_process_start(self):
        code = "import importlib.util,sys; from unittest.mock import patch; spec=importlib.util.spec_from_file_location('probe',sys.argv[1]); m=importlib.util.module_from_spec(spec); " \
               "before=set(sys.modules); " \
               "guard=patch('subprocess.Popen',side_effect=AssertionError('PROCESS_START')); guard.start(); " \
               "spec.loader.exec_module(m); assert not any(n.startswith('backend.') for n in set(sys.modules)-before); " \
               "assert m.main(['--help'])==0"
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code, str(SOURCE)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("never attach", result.stdout)

    def test_bounded_plans_and_no_endpoint_argument(self):
        self.assertEqual(benchmark.bounded_count("hardhat"), 20)
        self.assertEqual(benchmark.bounded_count("consensus"), 32)
        self.assertEqual(benchmark.bounded_count("consensus", 128), 128)
        for engine, count in (("hardhat", 21), ("consensus", 31), ("consensus", 129), ("consensus", True)):
            with self.assertRaises(benchmark.BenchmarkError): benchmark.bounded_count(engine, count)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            benchmark.parser().parse_args(["--engine", "hardhat", "--endpoint", "http://127.0.0.1:51724"])

    def test_existing_user_service_is_never_started_or_stopped(self):
        for engine, service in (("hardhat", Hardhat()), ("consensus", Consensus())):
            if engine == "hardhat": service._process = Process(); service._port = 51724
            else: service._genesis = {"existing": True}; service._nodes = [{"process": Process(), "rpc_port": 51724}]
            with self.assertRaisesRegex(benchmark.BenchmarkError, "FRESH_SERVICE_REQUIRED"):
                self.execute(engine, service)
            self.assertEqual((service.starts, service.stops), (0, 0))

    def test_hardhat_exact_baseline_plan_unique_receipts_and_rpc_accounting(self):
        service = Hardhat(); report = self.execute("hardhat", service)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual((len(service.transfers), service.height), (42, 43))
        self.assertEqual(service.transfers[:2], [(0, "synthetic-public-account-1", "0.000001", "GG-TEST"),
                                              (1, "synthetic-public-account-0", "0.000000000000000001", "NATIVE")])
        self.assertEqual([row["asset"] for row in report["batches"]], ["GG-TEST", "NATIVE"])
        self.assertEqual(report["unique_successes_including_warmup"], 42)
        self.assertEqual(report["measured_successes"], 40)
        self.assertEqual(report["not_confirmed"], 0)
        self.assertEqual(report["rpc_http_total"]["http_attempts"], report["rpc_totals"]["requests"])
        for row in report["batches"]:
            self.assertEqual(len(row["rpc_counts_per_full_cycle"]), 20)
            self.assertIn("p99_ms", row["full_gg_api_cycle"])
        self.assertTrue(report["owned_nodes_stopped"])
        self.assertTrue(service.created_process.stopped)
        encoded = json.dumps(report)
        self.assertNotIn("synthetic-private", encoded)
        self.assertNotIn("synthetic-public-account", encoded)

    def test_consensus_uses_sdk_verified_unique_cache_and_allowlisted_output(self):
        service = Consensus(); report = self.execute("consensus", service, 128)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(service.requested, 128)
        self.assertEqual(report["batch"]["unique_finalized"], 128)
        self.assertEqual(report["rpc_http_total"]["http_attempts"], 1)
        self.assertEqual(report["owned_node_resources_at_end"]["private_memory_mib"], 4)
        self.assertEqual(report["batch"]["latency"]["p99_ms"], 25)
        self.assertEqual(report["scope"], "LOCAL_FIXED_VALIDATORS")
        self.assertEqual((report["physical_hosts"], report["operator_count"]), (1, 1))
        self.assertTrue(report["owned_nodes_stopped"])
        encoded = json.dumps(report)
        for forbidden in ("NEVER_PUBLISH", "PRIVATE_RAW", "rpc_url", "secret_key", "515151", "52000"):
            self.assertNotIn(forbidden, encoded)

    def test_unverified_or_duplicate_consensus_result_cannot_pass(self):
        service = Consensus(); original = service.benchmark
        def missing(count):
            result = original(count); service._execution_cache.pop(next(iter(service._execution_cache)))
            return result
        service.benchmark = missing
        report = self.execute("consensus", service)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["failures"][0]["code"], "GG_BENCHMARK_UNIQUE_FINALIZATIONS_REQUIRED")
        self.assertEqual(report["not_finalized"], 1)
        self.assertTrue(report["owned_nodes_stopped"])

    def test_scope_mismatch_and_duplicate_hardhat_receipt_fail_closed(self):
        consensus = Consensus(); original = consensus.benchmark
        def wrong_scope(count):
            result = original(count); result["benchmark"]["physical_hosts"] = 4
            return result
        consensus.benchmark = wrong_scope
        report = self.execute("consensus", consensus)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["failures"][0]["code"], "GG_BENCHMARK_SCOPE_MISMATCH")
        hardhat = Hardhat(); send = hardhat.send
        def duplicate(identifier, digest):
            result = send(identifier, digest); result["transactions"][0]["txid"] = "0x" + "a"*64
            return result
        hardhat.send = duplicate
        report = self.execute("hardhat", hardhat)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["unique_successes_including_warmup"], 1)
        self.assertTrue(report["owned_nodes_stopped"])

    def test_failure_and_interrupt_stop_owned_nodes_and_sanitize_errors(self):
        for error in (ValueError("PRIVATE_KEY=secret; account=0x123; C:/private/path; pid=51724"), KeyboardInterrupt()):
            service = Hardhat()
            with patch.object(benchmark, "run_hardhat", side_effect=error): report = self.execute("hardhat", service)
            self.assertEqual(service.stops, 1)
            self.assertTrue(report["owned_nodes_stopped"])
            self.assertEqual(report["status"], "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAIL")
            self.assertNotIn("PRIVATE_KEY", json.dumps(report))
            self.assertNotIn("51724", json.dumps(report))
        self.assertEqual(benchmark.public_error(ValueError("GG_CONSENSUS_SECRET_ABCDEF0123456789")), "GG_BENCHMARK_FAILED")

    def test_transport_counter_rejects_unowned_target_and_restores_class(self):
        service = Hardhat(); service.start(); original = service.http.client.HTTPConnection
        with benchmark.RpcCounter("hardhat", service) as counter:
            service._rpc("read", [])
            self.assertEqual(counter.values(), dict(http_attempts=1, http_responses=1, transport_failures=0))
            bad = service.http.client.HTTPConnection("127.0.0.1", 51724)
            with self.assertRaisesRegex(benchmark.BenchmarkError, "NONOWNED_ENDPOINT"):
                bad.request("POST", "/", body="PRIVATE_VALUE")
            self.assertEqual(counter.requests, 1)
        self.assertIs(service.http.client.HTTPConnection, original)
        service.stop()

    def test_output_existing_file_is_preserved_before_engine_import(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"; target.write_text("preserve", encoding="utf-8")
            with patch.object(benchmark, "execute") as execute, redirect_stderr(io.StringIO()):
                self.assertEqual(benchmark.main(["--engine", "hardhat", "--output", str(target)]), 2)
            execute.assert_not_called(); self.assertEqual(target.read_text(encoding="utf-8"), "preserve")

    def test_main_writes_same_public_json_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"; stdout = io.StringIO()
            report = {"schema": benchmark.SCHEMA, "status": "PASS", "owned_nodes_stopped": True}
            with patch.object(benchmark, "execute", return_value=report), redirect_stdout(stdout):
                self.assertEqual(benchmark.main(["--engine", "consensus", "--count", "32", "--output", str(target)]), 0)
            self.assertEqual(json.loads(stdout.getvalue()), report)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), report)


if __name__ == "__main__":
    unittest.main()
