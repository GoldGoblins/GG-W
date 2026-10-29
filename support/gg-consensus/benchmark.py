"""Explicit, bounded benchmarks of fresh GG test engines; never attaches a node.

Examples (run from the application root, with the optional engine installed):
  .venv-windows/Scripts/python.exe support/gg-consensus/benchmark.py --engine hardhat
  .venv-windows/Scripts/python.exe support/gg-consensus/benchmark.py --engine consensus --count 32 --output result.json

Importing this module does not import a backend, start a process, or install a
tool. Public JSON deliberately excludes node identities, endpoints and keys.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[2]
SCHEMA = "gg.owned-network-benchmark.v1"


class BenchmarkError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise BenchmarkError(code)


def bounded_count(engine, count=None):
    require(engine in {"hardhat", "consensus"}, "GG_BENCHMARK_ENGINE")
    count = (20 if engine == "hardhat" else 32) if count is None else count
    require(type(count) is int, "GG_BENCHMARK_COUNT")
    if engine == "hardhat":
        require(count == 20, "GG_BENCHMARK_HARDHAT_REQUIRES_20_PER_ASSET")
    else:
        require(32 <= count <= 128, "GG_BENCHMARK_CONSENSUS_COUNT_32_TO_128")
    return count


def summary(values):
    require(bool(values) and all(type(v) in {int, float} and math.isfinite(v) and v >= 0 for v in values),
            "GG_BENCHMARK_INVALID_LATENCY")
    ordered = sorted(values)
    def percentile(p):
        position = (len(ordered) - 1) * p
        low = math.floor(position); high = math.ceil(position)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)
    return {"samples": len(values), "min_ms": round(min(values), 3), "p50_ms": percentile(.5),
            "p95_ms": percentile(.95), "p99_ms": percentile(.99),
            "mean_ms": round(statistics.mean(values), 3), "max_ms": round(max(values), 3)}


def public_error(error):
    # Never expose exception messages containing a path, request, address or key.
    message = str(error)
    safe_service_errors = {"GG_TESTNET_TOOLCHAIN_REQUIRED", "GG_CONSENSUS_TOOLCHAIN_REQUIRED",
                           "GG_CONSENSUS_REBUILD_REQUIRED", "GG_CONSENSUS_BINARY_CHANGED",
                           "GG_CONSENSUS_BUILD_RECEIPT_REQUIRED"}
    return message if (isinstance(error, BenchmarkError) and re.fullmatch(r"GG_BENCHMARK_[A-Z0-9_]{1,96}", message)
                       or message in safe_service_errors) else "GG_BENCHMARK_FAILED"


def hardware():
    import psutil
    cpu = platform.processor()
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return {"cpu": str(cpu)[:160], "architecture": platform.machine(), "platform": platform.system(),
            "platform_release": platform.release(), "physical_cores": psutil.cpu_count(logical=False),
            "logical_cpus": psutil.cpu_count(), "ram_gib": round(psutil.virtual_memory().total / 1024**3, 1),
            "shared_desktop_workload": True}


def version(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9.+_-]{1,48}", value) else None


def software(engine, service):
    result = {"python": platform.python_version()}
    if engine == "hardhat":
        try:
            record = json.loads((service.TOOLCHAIN / "node_modules/hardhat/package.json").read_text(encoding="utf-8"))
            result["hardhat"] = version(record.get("version"))
        except (OSError, ValueError, AttributeError):
            result["hardhat"] = None
        try:
            response = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            result["node"] = version(response.stdout.strip()) if response.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            result["node"] = None
    else:
        try:
            path = service.TOOLS / "build-manifest.json"
            require(path.stat().st_size <= 16384, "GG_BENCHMARK_BUILD_METADATA_LIMIT")
            record = json.loads(path.read_text(encoding="utf-8"))
            result.update(cometbft=version(record.get("cometbft")), go=version(record.get("go")))
        except (OSError, ValueError, AttributeError):
            result.update(cometbft=None, go=None)
    return result


@contextmanager
def private_state():
    names = ("GG_DESKTOP_STATE_ROOT", "GG_DESKTOP_DATA_ROOT")
    before = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory(prefix="gg-owned-benchmark-") as temporary:
        for name, suffix in zip(names, ("state", "data")):
            os.environ[name] = str(Path(temporary) / suffix)
        try:
            yield
        finally:
            for name, value in before.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def fresh(engine, service):
    require(not service._closed, "GG_BENCHMARK_FRESH_SERVICE_REQUIRED")
    if engine == "hardhat":
        valid = service._process is None and not service._port and not service._session and not service._accounts
    else:
        valid = not service._nodes and service._genesis is None and not service._accounts and service._temporary is None
    require(valid, "GG_BENCHMARK_FRESH_SERVICE_REQUIRED")


def processes(engine, service):
    if engine == "hardhat":
        return [service._process] if service._process is not None else []
    return [row["process"] for row in service._nodes if row.get("process") is not None]


class RpcCounter:
    """Count attempted HTTP exchanges, retaining no URL, parameters or bodies.

    The CLI is a fresh process. The temporary wrapper affects only this process
    and rejects requests whose loopback port is not owned by its selected service.
    Backend write requests retain their original single-attempt behavior.
    """
    def __init__(self, engine, service):
        self.engine = engine; self.service = service
        self.requests = 0; self.responses = 0; self.transport_failures = 0
        self.observed_processes = set()

    def values(self):
        return {"http_attempts": self.requests, "http_responses": self.responses,
                "transport_failures": self.transport_failures}

    def __enter__(self):
        counter = self
        self.original = self.service.http.client.HTTPConnection
        class CountedConnection(self.original):
            def request(connection, *args, **kwargs):
                ports = ({counter.service._port} if counter.engine == "hardhat"
                         else {row["rpc_port"] for row in counter.service._nodes})
                require(connection.host == "127.0.0.1" and connection.port in ports,
                        "GG_BENCHMARK_NONOWNED_ENDPOINT")
                counter.observed_processes.update(processes(counter.engine, counter.service))
                require(counter.requests < 100000, "GG_BENCHMARK_RPC_LIMIT")
                counter.requests += 1
                try:
                    return super().request(*args, **kwargs)
                except Exception:
                    counter.transport_failures += 1
                    raise

            def getresponse(connection):
                try:
                    response = super().getresponse()
                except Exception:
                    counter.transport_failures += 1
                    raise
                counter.responses += 1
                return response
        self.service.http.client.HTTPConnection = CountedConnection
        return self

    def __exit__(self, *_args):
        self.service.http.client.HTTPConnection = self.original


def delta(after, before):
    result = {name: after[name] - before[name] for name in before}
    require(all(type(value) is int and value >= 0 for value in result.values()), "GG_BENCHMARK_COUNTER_REGRESSION")
    return result


def finite(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def resources(rows):
    memory = [r.get("memory_private_bytes") for r in rows if finite(r.get("memory_private_bytes"))]
    cpu = [r.get("cpu_seconds") for r in rows if finite(r.get("cpu_seconds"))]
    return {"private_memory_mib": round(sum(memory) / 1048576, 3) if memory else None,
            "cpu_seconds_accumulated": round(sum(cpu), 3) if cpu else None,
            "memory_samples": len(memory), "cpu_samples": len(cpu),
            "definition": "Sum of owned node-process observations at the end; cumulative CPU time, not utilization or peak memory. Excludes verifier subprocesses and the Python harness."}


def run_hardhat(service, report, count, counter):
    service.deploy_token()
    seen = set()
    def transfer(source, target, asset, amount):
        draft = service.prepare(source, service._accounts[target], amount, asset)["review"]
        state = service.send(draft["id"], draft["review_digest"])
        receipt = state["transactions"][0]
        require(receipt["state"] == "CONFIRMED", "GG_BENCHMARK_UNCONFIRMED")
        digest = receipt.get("txid", "")
        require(isinstance(digest, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", digest) and digest.lower() not in seen,
                "GG_BENCHMARK_DUPLICATE_OR_INVALID_RECEIPT")
        seen.add(digest.lower())
        report["unique_successes_including_warmup"] = len(seen)
        return state
    transfer(0, 1, "GG-TEST", "0.000001")
    transfer(1, 0, "NATIVE", "0.000000000000000001")
    readings = []
    for _ in range(10):
        started = time.perf_counter(); service._rpc("eth_getBlockByNumber", ["latest", False])
        readings.append((time.perf_counter() - started) * 1000)
    report["rpc_read"] = summary(readings)
    report["batches"] = []
    for asset, amount in (("GG-TEST", "0.000001"), ("NATIVE", "0.000000000000000001")):
        batch = {"asset": asset, "amount": amount, "requested": count, "unique_confirmed": 0,
                 "not_confirmed": count, "rpc_counts_per_full_cycle": []}
        report["batches"].append(batch)
        full = []; send = []
        before_tokens = [service._balance(address, True) for address in service._accounts]
        height_before = int(service._rpc("eth_getBlockByNumber", ["latest", False])["number"], 16)
        batch_rpc = counter.values(); batch_started = time.perf_counter()
        for index in range(count):
            rpc_before = dict(service._rpc_stats); http_before = counter.requests
            started = time.perf_counter()
            transfer(index % 2, 1 - index % 2, asset, amount)
            full.append((time.perf_counter() - started) * 1000)
            counts = delta(dict(service._rpc_stats), rpc_before)
            require(counts["requests"] == counter.requests - http_before, "GG_BENCHMARK_RPC_ACCOUNTING_MISMATCH")
            batch["rpc_counts_per_full_cycle"].append(counts)
            metric = next(m for m in reversed(service._measurements) if m["operation"] == "transaction")
            require(metric["state"] == "CONFIRMED", "GG_BENCHMARK_UNCONFIRMED_METRIC")
            send.append(metric["elapsed_ms"])
            batch.update(unique_confirmed=index + 1, not_confirmed=count - index - 1)
        elapsed = time.perf_counter() - batch_started
        batch_http = delta(counter.values(), batch_rpc)
        height_after = int(service._rpc("eth_getBlockByNumber", ["latest", False])["number"], 16)
        require(height_after - height_before == count, "GG_BENCHMARK_AUTOMINE_BLOCK_COUNT")
        require([service._balance(address, True) for address in service._accounts] == before_tokens,
                "GG_BENCHMARK_TOKEN_BALANCES_NOT_RESTORED")
        batch.update(batch_elapsed_seconds=round(elapsed, 6), observed_serial_tps=round(count / elapsed, 3),
                     active_batch_bps=round(count / elapsed, 3), full_gg_api_cycle=summary(full),
                     send_receipt_metric=summary(send), rpc_http=batch_http,
                     full_gg_api_samples_ms=[round(value, 3) for value in full], send_receipt_samples_ms=send)
    resource = service._resource_metrics()
    report["owned_node_resources_at_end"] = resources([{"memory_private_bytes": resource.get("memory_committed_bytes"),
                                                       "cpu_seconds": resource.get("cpu_seconds")}])
    require(service._quantity(service._rpc("eth_call", [{"to": service._contract, "data": "0x18160ddd"}, "latest"])) == service.SUPPLY,
            "GG_BENCHMARK_SUPPLY_CHANGED")
    report["verified"] = {"unique_transfer_receipts": len(seen), "one_block_per_transaction": True,
                          "token_balances_restored_after_each_batch": True, "fixed_supply_unchanged": True,
                          "final_height": int(service._rpc("eth_getBlockByNumber", ["latest", False])["number"], 16)}
    report["measured_successes"] = count * 2


def run_consensus(service, report, count, counter):
    before_cache = set(service._execution_cache)
    batch_rpc = counter.values(); started = time.perf_counter()
    state = service.benchmark(count=count)
    elapsed = time.perf_counter() - started
    measured = state.get("benchmark") or {}
    require(measured.get("state") == "PASS" and measured.get("count") == count
            and measured.get("successful") == count and measured.get("unique_finalized") == count
            and measured.get("state_matches_expected") is True, "GG_BENCHMARK_UNVERIFIED_RESULT")
    require(measured.get("mode") == "PIPELINED_BLOCK_VERIFICATION" and measured.get("independent_senders") == 4
            and measured.get("scope") == "LOCAL_FIXED_VALIDATORS" and measured.get("validators") == 4
            and measured.get("physical_hosts") == 1 and type(measured.get("verified_blocks")) is int
            and 1 <= measured["verified_blocks"] <= count, "GG_BENCHMARK_SCOPE_MISMATCH")
    verified = set(service._execution_cache) - before_cache
    require(len(verified) == count and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in verified),
            "GG_BENCHMARK_UNIQUE_FINALIZATIONS_REQUIRED")
    require(all(service._execution_cache[value]["certificate_height"] == service._execution_cache[value]["height"] + 1
                for value in verified), "GG_BENCHMARK_CERTIFICATE_HEIGHT")
    proof = state.get("proof") or {}
    require(proof.get("verified") is True and proof.get("validator_count") == 4 and proof.get("quorum_required") == 3
            and proof.get("certificate_height") == proof.get("state_height", -2) + 1,
            "GG_BENCHMARK_FINAL_STATE_PROOF_REQUIRED")
    require(state.get("online") == 4 and len(state.get("validators", [])) == 4
            and all(row.get("identity_verified") is True for row in state["validators"]),
            "GG_BENCHMARK_ALL_FOUR_REQUIRED")
    require(len(state.get("accounts", [])) == 4 and sum(int(row["atomic"]) for row in state["accounts"]) == service.SUPPLY,
            "GG_BENCHMARK_SUPPLY_CHANGED")
    latency = {name: measured.get(name) for name in ("p50_ms", "p95_ms", "p99_ms")}
    require(all(finite(value) for value in latency.values()), "GG_BENCHMARK_INVALID_LATENCY")
    require(finite(measured.get("elapsed_seconds")) and measured["elapsed_seconds"] > 0
            and finite(measured.get("tps")), "GG_BENCHMARK_INVALID_THROUGHPUT")
    report["batch"] = {"asset": "GG-NET-TEST", "amount": "0.000001", "requested": count,
                       "unique_finalized": len(verified), "not_finalized": 0, "latency": latency,
                       "mode": "PIPELINED_BLOCK_VERIFICATION", "independent_senders": 4,
                       "verified_blocks": measured.get("verified_blocks"),
                       "service_elapsed_seconds": measured["elapsed_seconds"], "service_tps": measured["tps"],
                       "api_elapsed_seconds": round(elapsed, 6), "observed_api_wall_tps": round(count / elapsed, 3),
                       "rpc_http": delta(counter.values(), batch_rpc)}
    report["verified"] = {"sdk_verified_unique_finalizations": len(verified), "fixed_supply_unchanged": True,
                          "state_matches_expected": True, "validators": 4, "quorum_required": 3,
                          "state_height": proof.get("state_height"), "certificate_height": proof.get("certificate_height")}
    report["owned_node_resources_at_end"] = resources(state["validators"])
    report["unique_successes_including_warmup"] = len(verified)
    report["measured_successes"] = len(verified)


def base_report(engine, count):
    report = {"schema": SCHEMA, "engine": engine, "status": "RUNNING",
              "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "hardware": hardware(), "software": {}, "failures": [], "measured_successes": 0,
              "unique_successes_including_warmup": 0, "owned_nodes_stopped": None,
              "scope": "LOCAL_FIXED_VALIDATORS" if engine == "consensus" else "LOCAL_SERIAL_DEVELOPMENT_EVM",
              "physical_hosts": 1, "operator_count": 1, "validator_processes": 4 if engine == "consensus" else 1,
              "production": False,
              "definitions": {
                  "percentiles": "Linear interpolation over ordered samples at index (n-1)*p; milliseconds.",
                  "rpc_http": "Attempted HTTP requests to the fresh service's owned loopback ports, including failures; no automatic retry or request data logging.",
                  "whole_run_tps": "Unique successful transfers including warmup divided by elapsed start/deploy/warmup/measure/verify/resource-read/cleanup wall time; excludes Python import, hardware/version discovery and JSON output.",
                  "failure_counts": "Not-confirmed/not-finalized includes requested transfers not completed or never submitted; failure codes do not imply a safe resend."},
              "interpretation_limits": [
                  "One physical computer and operator; shared desktop load can affect measurements.",
                  "A bounded local observation, not maximum/sustained/global capacity or a production-network ranking.",
                  "The two engines perform different workloads and finality checks; their TPS values are not interchangeable.",
                  "No real assets, public node, production keys or existing application node are used."]}
    if engine == "hardhat":
        report["measurement_plan"] = {"warmup_transactions": 2, "native_transactions": count,
                                      "erc20_transactions": count, "rpc_reads": 10, "parallel_transactions": 1,
                                      "baseline_compatible": "gg.local-speed-microbenchmark.v1/v2"}
        report["definitions"].update(
            full_gg_api_cycle="prepare() through send() returning its full snapshot: identity, nonce, fee and balance guards, draft, local broadcast, canonical receipt and two account snapshots; excludes human review, UI scheduling and deployment.",
            send_receipt_metric="Backend transaction timer: local eth_sendTransaction through canonical receipt/block read; excludes preparation, identity precheck and final full snapshot.",
            observed_serial_tps="20 successful transfers divided by the active serial batch wall time.",
            active_batch_bps="New automined Hardhat blocks divided by batch wall time; one block per accepted transaction, not distributed consensus cadence.",
            rpc_read="One eth_getBlockByNumber latest call over owned loopback; not a UI status snapshot.")
        report["interpretation_limits"].append("Hardhat confirmed receipts have no P2P propagation or independent-validator finality.")
    else:
        report["measurement_plan"] = {"transactions": count, "warmup_transactions": 0, "independent_senders": 4,
                                      "mode": "PIPELINED_BLOCK_VERIFICATION", "quorum_required": 3}
        report["definitions"].update(
            latency="Each transaction's pre-broadcast perf_counter through observation after SDK certificate, inclusion and full-block execution verification against certified state H and header H+1; excludes human prepare/review and startup. Polling and queueing are included.",
            service_tps="Unique SDK-finalized transfers divided by the backend benchmark wall time, including initial/final state verification and broadcast/reconciliation; excludes the returned dashboard snapshot.",
            observed_api_wall_tps="Unique finalized transfers divided by the entire benchmark() API call including its returned snapshot.")
        report["interpretation_limits"].append("Four separate CometBFT processes use a fixed permissioned validator set with one operator/fault domain; this does not establish Sybil resistance or a new consensus algorithm.")
    return report


def execute(engine, count=None, *, service=None):
    count = bounded_count(engine, count)
    report = base_report(engine, count)
    with private_state():
        if service is None:
            if str(PROJECT) not in sys.path:
                sys.path.insert(0, str(PROJECT))
            service = importlib.import_module("backend.gg_testnet" if engine == "hardhat" else "backend.gg_consensus")
        # Failure here MUST NOT stop or otherwise mutate a pre-existing service.
        fresh(engine, service)
        report["software"] = software(engine, service)
        with RpcCounter(engine, service) as counter:
            started = time.perf_counter(); owned = set()
            try:
                service.start()
                owned.update(processes(engine, service))
                if engine == "hardhat":
                    require(len(owned) == 1 and service._owns_listener(), "GG_BENCHMARK_FRESH_OWNED_NODE_REQUIRED")
                    run_hardhat(service, report, count, counter)
                else:
                    require(len(owned) == 4 and all(service._owned(i) for i in range(4)),
                            "GG_BENCHMARK_FRESH_OWNED_NODES_REQUIRED")
                    run_consensus(service, report, count, counter)
                report["status"] = "PASS"
            except KeyboardInterrupt:
                report["status"] = "INTERRUPTED"; report["failures"].append({"code": "GG_BENCHMARK_INTERRUPTED"})
            except Exception as error:
                report["status"] = "FAIL"; report["failures"].append({"code": public_error(error)})
            finally:
                if engine == "hardhat":
                    report["measured_successes"] = max(0, report["unique_successes_including_warmup"] - 2)
                    report["not_confirmed"] = count * 2 - report["measured_successes"]
                else:
                    finalized = {value for value in service._execution_cache if re.fullmatch(r"[0-9a-f]{64}", value)}
                    report["measured_successes"] = min(count, len(finalized))
                    report["unique_successes_including_warmup"] = min(count, len(finalized))
                owned.update(processes(engine, service)); owned.update(counter.observed_processes)
                try:
                    service.stop()
                except Exception as error:
                    report["status"] = "FAIL"; report["failures"].append({"code": public_error(error)})
                report["owned_nodes_stopped"] = not processes(engine, service) and all(process.poll() is not None for process in owned)
                if not report["owned_nodes_stopped"]:
                    report["status"] = "FAIL"; report["failures"].append({"code": "GG_BENCHMARK_OWNED_NODE_SURVIVED"})
                elapsed = time.perf_counter() - started
                report["entire_run_seconds"] = round(elapsed, 6)
                report["whole_run_tps_including_startup_cleanup"] = round(report["unique_successes_including_warmup"] / elapsed, 3)
                report["rpc_http_total"] = counter.values()
                if engine == "hardhat":
                    report["rpc_totals"] = {name: service._rpc_stats[name] for name in ("requests", "members", "batches")}
                else:
                    report["not_finalized"] = count - report["measured_successes"]
    return report


def parser():
    result = argparse.ArgumentParser(description="Benchmark a fresh owned local test engine; never attach to an existing node or install/download tools.")
    result.add_argument("--engine", required=True, choices=("hardhat", "consensus"))
    result.add_argument("--count", type=int, help="Consensus: 32–128 (default 32). Hardhat comparison: exactly 20 per asset (default 20), plus 2 warmups.")
    result.add_argument("--output", type=Path, help="Optional new JSON file; existing files are never overwritten. The same public JSON is printed to stdout.")
    return result


def main(argv=None):
    arguments = parser(); args = arguments.parse_args(argv)
    try:
        count = bounded_count(args.engine, args.count)
    except BenchmarkError as error:
        arguments.error(public_error(error))
    output = None
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = args.output.open("x", encoding="utf-8")
        try:
            report = execute(args.engine, count)
        except KeyboardInterrupt:
            report = {"schema": SCHEMA, "engine": args.engine, "status": "INTERRUPTED",
                      "failures": [{"code": "GG_BENCHMARK_INTERRUPTED"}], "owned_nodes_stopped": None}
        except Exception as error:
            report = {"schema": SCHEMA, "engine": args.engine, "status": "FAIL",
                      "failures": [{"code": public_error(error)}], "owned_nodes_stopped": None}
        encoded = json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if output:
            output.write(encoded); output.flush()
        print(encoded, end="")
        return 0 if report["status"] == "PASS" else 130 if report["status"] == "INTERRUPTED" else 1
    except OSError:
        print('{"status":"FAIL","failures":[{"code":"GG_BENCHMARK_OUTPUT_UNAVAILABLE"}]}', file=sys.stderr)
        return 2
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
