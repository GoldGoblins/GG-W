"""Exact, offline DAGoblin capacity arithmetic; this is NOT a consensus engine.

Importing this module performs no I/O. Only the explicit CLI reads its requested
JSON file/stdin and prints JSON. Run ``python support/dagoblin/analyze.py --json``
for examples, or ``--input plan.json`` / ``--input -`` for a custom request:

    {"operation": "capacity_bounds", "parameters": {
      "transactions_per_block": 1000, "payload_bytes": 186,
      "signature_bytes": 64, "link": {"value": 6, "unit": "Gbit/s"},
      "utilization": "4/5", "cpu_verify": {
        "p95_seconds": "1/100000", "workers": 8}}}

Exact numeric inputs are integers, Fraction objects, or rational strings such as
"4/5". Floats, decimal strings, booleans and implicit unit conversions are
rejected. Derived rational JSON values are strings, never rounded floats.

ML-DSA public-key/signature sizes: NIST FIPS 204, Table 2,
https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.204.pdf . These are wire-size
parameters only: no cryptography, key generation, aggregation or PQ security
implementation is supplied here.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import re
import sys
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA = "gg.dagoblin.analysis.v1"
STATUS = "CONDITIONAL_CAPACITY_SCENARIO"
MAX_INPUT_BYTES = 65_536
ML_DSA_PARAMETERS = MappingProxyType({
    "ML-DSA-44": MappingProxyType({"signature_bytes": 2420, "public_key_bytes": 1312}),
    "ML-DSA-65": MappingProxyType({"signature_bytes": 3309, "public_key_bytes": 1952}),
    "ML-DSA-87": MappingProxyType({"signature_bytes": 4627, "public_key_bytes": 2592}),
})
COMPARISON_FIELDS = (
    "workload", "fault_model", "hardware", "network", "commit_predicate",
    "data_availability", "cryptography",
)
_EXACT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z", re.ASCII)
_LINK_UNITS = {
    "B/s": Fraction(1), "kB/s": Fraction(1000), "MB/s": Fraction(10**6),
    "GB/s": Fraction(10**9), "KiB/s": Fraction(1024), "MiB/s": Fraction(1024**2),
    "GiB/s": Fraction(1024**3), "bit/s": Fraction(1, 8),
    "Mbit/s": Fraction(10**6, 8), "Gbit/s": Fraction(10**9, 8),
    "Mibit/s": Fraction(1024**2, 8), "Gibit/s": Fraction(1024**3, 8),
    "Gib/s": Fraction(1024**3, 8),
}


def _number(value: Any, name: str, *, zero: bool = False) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(name + " must be an exact rational, not a boolean")
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, str) and len(value) <= 1024 and _EXACT.fullmatch(value):
        result = Fraction(value)
    else:
        raise ValueError(name + " must be an integer or rational string")
    if result < 0 or (not zero and result == 0):
        raise ValueError(name + (" must be nonnegative" if zero else " must be positive"))
    return result


def _integer(value: Any, name: str, *, zero: bool = False) -> int:
    result = _number(value, name, zero=zero)
    if result.denominator != 1:
        raise ValueError(name + " must be an integer")
    return result.numerator


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(name + " must be a boolean")
    return value


def _at_least_one(value: Any, name: str) -> Fraction:
    result = _number(value, name)
    if result < 1:
        raise ValueError(name + " must be at least one")
    return result


def _utilization(value: Any) -> Fraction:
    result = _number(value, "utilization")
    if result > 1:
        raise ValueError("utilization must not exceed one")
    return result


def _mapping(value: Any, name: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise ValueError(name + " must be an object")
    if set(value) - allowed:
        raise ValueError(name + " contains unknown fields")
    return dict(value)


def _ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _byte_rates(value: Fraction) -> dict[str, Fraction]:
    return {
        "bytes_per_second": value,
        "decimal_MB_per_second": value / 10**6,
        "binary_MiB_per_second": value / 1024**2,
        "decimal_Gbit_per_second": value * 8 / 10**9,
    }


def link_bytes_per_second(value: Any, unit: str) -> Fraction:
    """Convert a case-sensitive, explicitly named link unit into bytes/second."""
    if not isinstance(unit, str) or unit not in _LINK_UNITS:
        raise ValueError("link unit must be an explicitly supported bit/byte unit")
    return _number(value, "link value") * _LINK_UNITS[unit]


def wire_budget(
    *, blocks_per_second: Any, transactions_per_block: Any,
    payload_bytes: Any, signature_bytes: Any, witness_bytes: Any = 0,
    public_key_bytes: Any = 0, public_keys_cached: bool = True,
    cached_key_count: Any = 0, header_bytes: Any = 0, parent_count: Any = 0,
    parent_reference_bytes: Any = 32, replication: Any = 1,
) -> dict[str, Any]:
    """Offered UNIQUE TX wire lower bound, excluding unspecified protocol costs.

    Public-key cache fill is reported separately and is never silently free.
    Deduplication, packet framing, retransmission, proofs and vote traffic are
    not assumed away by a claim of achieved throughput: this is size arithmetic.
    """
    bps = _number(blocks_per_second, "blocks_per_second", zero=True)
    tx = _integer(transactions_per_block, "transactions_per_block")
    payload = _integer(payload_bytes, "payload_bytes", zero=True)
    signature = _integer(signature_bytes, "signature_bytes", zero=True)
    witness = _integer(witness_bytes, "witness_bytes", zero=True)
    key = _integer(public_key_bytes, "public_key_bytes", zero=True)
    cached = _boolean(public_keys_cached, "public_keys_cached")
    cache_count = _integer(cached_key_count, "cached_key_count", zero=True)
    header = _integer(header_bytes, "header_bytes", zero=True)
    parents = _integer(parent_count, "parent_count", zero=True)
    reference = _integer(parent_reference_bytes, "parent_reference_bytes")
    replicas = _integer(replication, "replication")
    tx_bytes = payload + signature + witness + (0 if cached else key)
    if tx_bytes <= 0:
        raise ValueError("serialized transaction bytes must be positive")
    block_bytes = tx * tx_bytes + header + parents * reference
    per_receiver = bps * block_bytes
    return {
        "schema": SCHEMA, "status": "SERIALIZED_WIRE_LOWER_BOUND",
        "achieved_benchmark": False,
        "blocks_per_second": bps, "transactions_per_block": tx,
        "unique_transactions_per_second": bps * tx,
        "transaction_bytes": {
            "payload": payload, "signature": signature, "witness": witness,
            "public_key_on_wire": 0 if cached else key, "total": tx_bytes,
        },
        "header_bytes": header, "parent_reference_bytes_total": parents * reference,
        "serialized_block_bytes": block_bytes, "replication": replicas,
        "per_full_receiver": _byte_rates(per_receiver),
        "all_copies": _byte_rates(per_receiver * replicas),
        "one_time_public_key_cache_fill_bytes": key * cache_count if cached else 0,
        "assumptions": [
            "Every counted transaction is unique; duplicates do not increase useful TPS.",
            "Cached keys require prior authenticated cache fill; cache misses add wire cost.",
            "Unspecified framing, votes, proofs, retransmits and state traffic are additional.",
        ],
    }


def retained_buffer(
    *, bytes_per_second: Any, window_seconds: Any, copies: Any = 1,
    overhead_factor: Any = 1,
) -> dict[str, Any]:
    rate = _number(bytes_per_second, "bytes_per_second", zero=True)
    window = _number(window_seconds, "window_seconds")
    count = _integer(copies, "copies")
    overhead = _at_least_one(overhead_factor, "overhead_factor")
    size = rate * window * count * overhead
    return {
        "status": "SERIALIZED_BUFFER_MODEL", "window_seconds": window,
        "copies": count, "overhead_factor": overhead,
        "retained_bytes_exact": size, "required_whole_bytes": _ceil(size),
        "note": "This is an explicit retained-byte model, not total process RAM.",
    }


def checkpoint_batch_cost(
    *, batch_transactions: Any, checkpoint_bytes: Any,
    verification_seconds: Any,
) -> dict[str, Any]:
    batch = _integer(batch_transactions, "batch_transactions")
    size = _integer(checkpoint_bytes, "checkpoint_bytes", zero=True)
    seconds = _number(verification_seconds, "verification_seconds", zero=True)
    return {
        "status": "AMORTIZED_BATCH_MODEL", "batch_transactions": batch,
        "checkpoint_bytes": size, "verification_seconds": seconds,
        "bytes_per_transaction": Fraction(size, batch),
        "verification_seconds_per_transaction": seconds / batch,
        "note": "A full batch amortizes cost; no security-equivalent aggregation is implied.",
    }


def peer_polling_cost(
    *, request_bytes: Any, response_bytes: Any, peers: Any = 11,
    interval_seconds: Any = 1, shared_latest_hub: bool = False,
    independent_fault_domains: Any = None,
) -> dict[str, Any]:
    count = _integer(peers, "peers")
    interval = _number(interval_seconds, "interval_seconds")
    request = _integer(request_bytes, "request_bytes", zero=True)
    response = _integer(response_bytes, "response_bytes", zero=True)
    hub = _boolean(shared_latest_hub, "shared_latest_hub")
    domains = None if independent_fault_domains is None else _integer(
        independent_fault_domains, "independent_fault_domains")
    if domains is not None and domains > count:
        raise ValueError("independent_fault_domains cannot exceed peers")
    exchanges = count / interval
    return {
        "status": "POLLING_TRANSPORT_MODEL", "peers": count,
        "exchanges_per_second": exchanges,
        "sent_bytes_per_second": exchanges * request,
        "received_bytes_per_second": exchanges * response,
        "total_bytes_per_second": exchanges * (request + response),
        "shared_latest_hub": hub, "independent_fault_domains": domains,
        "risk": "SHARED_HUB_AVAILABILITY_AND_VIEW_CONCENTRATION" if hub else "FAULT_INDEPENDENCE_NOT_PROVEN",
        "note": "Polling is not quorum, consensus, data availability or Sybil resistance.",
    }


def _metadata_known(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().upper() not in {
            "UNKNOWN", "UNSPECIFIED", "UNMEASURED", "N/A", "?", "TBD",
        }
    if isinstance(value, Mapping):
        return bool(value) and all(isinstance(k, str) and _metadata_known(v) for k, v in value.items())
    if isinstance(value, (tuple, list)):
        return bool(value) and all(_metadata_known(v) for v in value)
    return type(value) in (int, bool)


def comparison_eligibility(
    *, baseline: Mapping[str, Any], candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Require all seven experiment contracts equal before comparing speed."""
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        raise ValueError("comparison inputs must be objects")
    unknown, different = [], []
    for field in COMPARISON_FIELDS:
        left, right = baseline.get(field), candidate.get(field)
        if not _metadata_known(left) or not _metadata_known(right):
            unknown.append(field)
        elif json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True):
            different.append(field)
    return {
        "status": "INCOMPARABLE" if unknown or different else "ELIGIBLE_FOR_CONTROLLED_COMPARISON",
        "unknown_fields": unknown, "different_fields": different,
        "speedup": None,
        "note": "Matching declarations permit controlled measurement; they do not prove a speedup.",
    }


def _stage_limit(config: Any, name: str, factor: Fraction, *, gpu: bool = False) -> dict[str, Any]:
    stage = _mapping(config, name, {
        "p95_seconds", "p95_nanoseconds", "workers", "transactions_per_batch",
        "operations_per_batch", "scope",
    })
    if ("p95_seconds" in stage) == ("p95_nanoseconds" in stage):
        raise ValueError(name + " requires exactly one measured p95 time unit")
    seconds = _number(stage["p95_seconds"], name + " p95_seconds") if "p95_seconds" in stage else (
        _number(stage["p95_nanoseconds"], name + " p95_nanoseconds") / 10**9)
    workers = _integer(stage.get("workers", 1), name + " workers")
    batch = _integer(stage.get("transactions_per_batch", 1), name + " transactions_per_batch")
    operations = _integer(stage.get("operations_per_batch", 1), name + " operations_per_batch")
    if gpu and stage.get("scope") not in {
        "transaction_validation", "signature_verification", "proof_verification",
    }:
        raise ValueError("gpu requires a caller-measured appropriate validation scope")
    return {
        "status": "SERVICE_TIME_SCENARIO_ESTIMATE",
        "unique_transactions_per_second": workers * batch * factor / (seconds * operations),
        "measured_p95_seconds": seconds, "workers": workers,
        "transactions_per_batch": batch, "operations_per_batch": operations,
        "scope": stage.get("scope", name),
        "condition": "Treat the caller's p95 as FIXED service time for this scenario only; the unmodelled tail can dominate queues.",
    }


def capacity_bounds(
    *, transactions_per_block: Any, payload_bytes: Any, signature_bytes: Any,
    witness_bytes: Any = 0, public_key_bytes: Any = 0,
    public_keys_cached: bool = True, header_bytes: Any = 0, parent_count: Any = 0,
    parent_reference_bytes: Any = 32, utilization: Any = 1, safety_factor: Any = 1,
    fanout: Any = 1, copies: Any = 1, link: Any = None, cpu_sign: Any = None,
    cpu_verify: Any = None, gpu: Any = None, storage: Any = None,
    memory: Any = None, checkpoint: Any = None,
) -> dict[str, Any]:
    """Compare stated byte ceilings and fixed-service-time scenarios, without a TPS cap.

    Network/storage/window arithmetic supplies upper bounds only under the stated
    byte model. Inverse p95 CPU/GPU costs are NOT bounds or safe control rates;
    their unmodelled tail can dominate. Missing resources/quorum/DA/latency are
    NOT assumed fast. CPU worker budgets must actually be able to coexist.
    """
    wire = wire_budget(
        blocks_per_second=1, transactions_per_block=transactions_per_block,
        payload_bytes=payload_bytes, signature_bytes=signature_bytes,
        witness_bytes=witness_bytes, public_key_bytes=public_key_bytes,
        public_keys_cached=public_keys_cached, header_bytes=header_bytes,
        parent_count=parent_count, parent_reference_bytes=parent_reference_bytes,
    )
    tx = wire["transactions_per_block"]
    block_bytes = Fraction(wire["serialized_block_bytes"])
    factor = _utilization(utilization) / _at_least_one(safety_factor, "safety_factor")
    fan = _integer(fanout, "fanout")
    replicas = _integer(copies, "copies")
    limits: dict[str, dict[str, Any]] = {}
    checkpoint_cost = None
    if checkpoint is not None:
        cp = _mapping(checkpoint, "checkpoint", {
            "batch_transactions", "checkpoint_bytes", "verification_seconds", "verification_workers",
        })
        checkpoint_cost = checkpoint_batch_cost(
            batch_transactions=cp["batch_transactions"], checkpoint_bytes=cp["checkpoint_bytes"],
            verification_seconds=cp["verification_seconds"],
        )
        block_bytes += tx * checkpoint_cost["bytes_per_transaction"]
        if "verification_workers" in cp:
            if checkpoint_cost["verification_seconds"] == 0:
                raise ValueError("checkpoint verification stage requires a positive measured time")
            limits["checkpoint_verify"] = _stage_limit({
                "p95_seconds": checkpoint_cost["verification_seconds"],
                "workers": cp["verification_workers"],
                "transactions_per_batch": checkpoint_cost["batch_transactions"],
            }, "checkpoint_verify", factor)
    if link is not None:
        network = _mapping(link, "link", {"value", "unit"})
        raw_bytes = link_bytes_per_second(network["value"], network["unit"])
        usable_bytes = raw_bytes * factor / (fan * replicas)
        limits["network"] = {
            "status": "UNDER_STATED_BYTE_MODEL",
            "unique_transactions_per_second": usable_bytes * tx / block_bytes,
            "link_bytes_per_second": raw_bytes,
            "usable_bytes_per_second_per_full_receiver": usable_bytes,
            "fanout": fan, "copies": replicas,
        }
    for name, stage in (("cpu_sign", cpu_sign), ("cpu_verify", cpu_verify), ("gpu", gpu)):
        if stage is not None:
            limits[name] = _stage_limit(stage, name, factor, gpu=name == "gpu")
    if storage is not None:
        disk = _mapping(storage, "storage", {
            "bytes_per_second", "write_amplification", "stored_bytes_per_block",
        })
        disk_rate = _number(disk["bytes_per_second"], "storage bytes_per_second")
        amplification = _at_least_one(disk.get("write_amplification", 1), "write_amplification")
        stored_block = _number(disk.get("stored_bytes_per_block", block_bytes), "stored_bytes_per_block")
        limits["storage"] = {
            "status": "UNDER_STATED_BYTE_MODEL",
            "unique_transactions_per_second": disk_rate * factor * tx / (stored_block * amplification),
            "bytes_per_second": disk_rate, "stored_bytes_per_block": stored_block,
            "write_amplification": amplification,
        }
    if memory is not None:
        ram = _mapping(memory, "memory", {
            "budget_bytes", "reserved_bytes", "window_seconds", "copies", "overhead_factor",
        })
        budget = _integer(ram["budget_bytes"], "memory budget_bytes")
        reserve = _integer(ram.get("reserved_bytes", 0), "memory reserved_bytes", zero=True)
        if reserve >= budget:
            raise ValueError("memory reserved_bytes must be less than budget_bytes")
        window = _number(ram["window_seconds"], "memory window_seconds")
        ram_copies = _integer(ram.get("copies", 1), "memory copies")
        overhead = _at_least_one(ram.get("overhead_factor", 1), "memory overhead_factor")
        retained_per_block = block_bytes * ram_copies * overhead
        usable = (budget - reserve) * factor
        slots = usable // retained_per_block
        limits["memory"] = {
            "status": "UNDER_STATED_BYTE_MODEL",
            "unique_transactions_per_second": slots * tx / window,
            "retained_bytes_per_block": retained_per_block,
            "usable_budget_bytes": usable, "whole_block_slots": slots,
            "window_seconds": window,
            "condition": "Serialized retained blocks only; reserve other process RAM explicitly.",
        }
    if not limits:
        raise ValueError("at least one explicitly measured resource capacity is required")
    for limit in limits.values():
        limit["blocks_per_second"] = limit["unique_transactions_per_second"] / tx
    bottleneck = min(limit["unique_transactions_per_second"] for limit in limits.values())
    byte_limits = [limit["unique_transactions_per_second"] for limit in limits.values()
                   if limit["status"] == "UNDER_STATED_BYTE_MODEL"]
    byte_upper_bound = min(byte_limits) if byte_limits else None
    omitted = [name for name, value in (
        ("network", link), ("cpu_sign", cpu_sign), ("cpu_verify", cpu_verify),
        ("gpu", gpu), ("storage", storage), ("memory", memory),
    ) if value is None]
    return {
        "schema": SCHEMA, "status": STATUS, "achieved_benchmark": False,
        "transactions_per_block": tx,
        "serialized_block_bytes_including_amortized_checkpoint": block_bytes,
        "checkpoint": checkpoint_cost,
        "utilization_and_safety_multiplier": factor,
        "resource_limits": limits,
        "bottlenecks": [name for name, value in limits.items()
                        if value["unique_transactions_per_second"] == bottleneck],
        "scenario_unique_transactions_per_second": bottleneck,
        "scenario_blocks_per_second": bottleneck / tx,
        "byte_model_upper_bound_unique_transactions_per_second": byte_upper_bound,
        "byte_model_upper_bound_blocks_per_second": None if byte_upper_bound is None else byte_upper_bound / tx,
        "unspecified_resource_stages": omitted,
        "unmodelled_constraints": [
            "BFT quorum and fault-domain independence, propagation/commit latency and data availability.",
            "Disk tail latency, state growth, contention, cache misses and unspecified protocol bytes.",
            "Inverse p95 service time is a fixed-cost scenario, not an upper bound or safe control rate.",
        ],
        "assumptions": [
            "Full-receiver wire lower bound; unique transactions only; no protocol security claims.",
            "Worker budgets are dedicated, measured and feasible concurrently; GPU work is caller-measured.",
            "Checkpoint bytes are amortized over full batches; burst and fill latency are additional.",
            "A negotiated finite queue/window budget is required; this planner changes no runtime limits.",
            "Controller eligibility requires sustained end-to-end load, tail measurement and queue guards.",
        ],
    }


def examples() -> dict[str, Any]:
    """Small, deterministic examples, without machine or network measurement."""
    classical = wire_budget(blocks_per_second=100, transactions_per_block=1000,
                            payload_bytes=256, signature_bytes=64)
    hybrid = wire_budget(blocks_per_second=100, transactions_per_block=1000,
                         payload_bytes=256, signature_bytes=64 + ML_DSA_PARAMETERS["ML-DSA-65"]["signature_bytes"],
                         public_key_bytes=ML_DSA_PARAMETERS["ML-DSA-65"]["public_key_bytes"],
                         cached_key_count=1)
    return {
        "schema": SCHEMA, "status": "ANALYTICAL_EXAMPLES_NOT_BENCHMARKS",
        "300_blocks_1000_tx_250_bytes": wire_budget(
            blocks_per_second=300, transactions_per_block=1000, payload_bytes=186, signature_bytes=64),
        "3000_blocks_1000_tx_250_bytes": wire_budget(
            blocks_per_second=3000, transactions_per_block=1000, payload_bytes=186, signature_bytes=64),
        "100k_classical_transactions": classical, "100k_hybrid_ml_dsa_65_transactions": hybrid,
        "one_Gib_per_second_bytes": link_bytes_per_second(1, "Gib/s"),
        "one_GiB_per_second_bytes": link_bytes_per_second(1, "GiB/s"),
        "eleven_peers_latest_hub": peer_polling_cost(
            request_bytes=64, response_bytes=1024, peers=11, shared_latest_hub=True),
        "six_Gbit_capacity_example": capacity_bounds(
            transactions_per_block=1000, payload_bytes=186, signature_bytes=64,
            link={"value": 6, "unit": "Gbit/s"}, utilization="4/5",
            cpu_verify={"p95_nanoseconds": 10000, "workers": 8},
            storage={"bytes_per_second": 10**9, "write_amplification": 2},
            memory={"budget_bytes": 300 * 1024**2, "reserved_bytes": 100 * 1024**2,
                    "window_seconds": 2, "overhead_factor": 2}),
    }


_OPERATIONS = {
    "wire_budget": wire_budget, "retained_buffer": retained_buffer,
    "checkpoint_batch_cost": checkpoint_batch_cost, "peer_polling_cost": peer_polling_cost,
    "comparison_eligibility": comparison_eligibility, "capacity_bounds": capacity_bounds,
    "link_bytes_per_second": link_bytes_per_second,
}


def run_request(request: Any) -> Any:
    """Execute an explicit pure calculation; a bare object means capacity_bounds."""
    if not isinstance(request, dict) or not all(isinstance(k, str) for k in request):
        raise ValueError("request must be an object")
    if "operation" in request:
        if set(request) != {"operation", "parameters"}:
            raise ValueError("request requires only operation and parameters")
        operation, parameters = request["operation"], request["parameters"]
    else:
        operation, parameters = "capacity_bounds", request
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise ValueError("unsupported calculation operation")
    if not isinstance(parameters, dict) or not all(isinstance(k, str) for k in parameters):
        raise ValueError("parameters must be an object")
    try:
        return _OPERATIONS[operation](**parameters)
    except (KeyError, TypeError) as error:
        raise ValueError("calculation has missing or invalid parameter fields") from error


def _json_ready(value: Any) -> Any:
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON objects must not contain duplicate fields")
        result[key] = value
    return result


def _reject_inexact_json(_: str) -> Any:
    raise ValueError("JSON numbers must be integers; use rational strings for exact fractions")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print exact JSON (the default); no input means examples")
    parser.add_argument("--input", metavar="PATH", help="read a custom JSON plan; '-' reads stdin; maximum 64 KiB")
    args = parser.parse_args(argv)
    try:
        if args.input is None:
            result = examples()
        else:
            if args.input == "-":
                raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            else:
                with open(args.input, "rb") as stream:
                    raw = stream.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("JSON input exceeds the 64 KiB calculation budget")
            try:
                request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                     parse_float=_reject_inexact_json, parse_constant=_reject_inexact_json)
            except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
                raise ValueError("input must be bounded valid UTF-8 JSON") from error
            result = run_request(request)
        print(json.dumps(_json_ready(result), sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, RecursionError) as error:
        message = "requested JSON input could not be read" if isinstance(error, OSError) else str(error)
        print(json.dumps({"schema": SCHEMA, "status": "INVALID_INPUT", "error": message}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
