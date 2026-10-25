from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from backend.crypto_keys import (
    ensure_test_wallet,
    has_signer,
    signer_for,
    import_solana_keypair,
    load_test_pubkey,
)
from backend import crypto_strategy004
from backend import crypto_bots, crypto_flash_arb, crypto_trader
from backend import crypto_strategy_factory
from backend import crypto_desk
from backend import crypto_data, crypto_market, crypto_paper
from backend import crypto_portfolio
from backend import polymarket_research
from backend import kaspa_covenant
from backend.crypto_lab import (
    current_slot,
    has_blockhash,
    lab_status,
    start_lab,
    stop_lab,
    wait_ready,
)
from backend.crypto_tx import confirm_signature, send_self_transfer
from backend.crypto_contract import (
    NETWORK_DEFAULT,
    RPC_ALLOWLIST,
    append_ledger,
    clear_wallet,
    write_state_json,
    read_state_json,
    decorate_ledger_row,
    format_sol,
    format_units,
    human_error,
    load_network,
    load_proven,
    load_wallet,
    mark_proven,
    parse_signal,
    read_ledger,
    save_network,
    save_wallet,
    short_error,
    validate_pubkey,
    account_catalog,
)


LAB_AIRDROP_LAMPORTS = 100 * 1_000_000_000
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
KNOWN_MINTS = {
    "CXk2AMBfi3TwaEL2468s6zP8xq9NxTXjp9gjMgzeUynM": "PYUSD",
}
_RPC_TTL = 20.0
_rpc_bundle: dict[tuple[str, str], tuple[float, int | None, list[dict[str, Any]]]] = {}
_rpc_lock = threading.Lock()
_rpc_inflight: set[tuple[str, str]] = set()
_rpc_errors: dict[tuple[str, str], str] = {}
_rpc_retry_after: dict[tuple[str, str], float] = {}
_rpc_generation = 0
_RPC_RESPONSE_LIMIT = 8 * 1024 * 1024
_pump_research = None
_pump_research_lock = threading.Lock()


def pump_service():
    global _pump_research
    with _pump_research_lock:
        if _pump_research is None:
            from backend.crypto_pump import PumpResearch
            _pump_research = PumpResearch(rpc_call)
        return _pump_research


def pump_inspect(mint: str, pool: str = ""):
    return pump_service().inspect(mint, pool)


def pump_quote(side: str, amount: str, slippage: str = "100"):
    return pump_service().quote(side, amount, slippage)


def pump_simulate():
    pubkey = str(load_wallet().get("pubkey") or "")
    network = load_network()
    if not pubkey:
        raise ValueError("PUMP_WATCH_WALLET_REQUIRED")
    service = pump_service()
    result = service.simulate(pubkey, wallet_network=network)
    if str(load_wallet().get("pubkey") or "") != pubkey or load_network() != network:
        service.bind_wallet(str(load_wallet().get("pubkey") or ""), load_network())
        raise ValueError("PUMP_WALLET_CHANGED")
    return result


def pump_paper_trade():
    return pump_service().paper_trade()


def pump_paper_reset():
    return pump_service().paper_reset()


def pump_refresh():
    return pump_service().refresh()


def pump_heartbeat():
    if not _pump_research_lock.acquire(blocking=False):
        return
    try:
        service = _pump_research
    finally:
        _pump_research_lock.release()
    if service is not None:
        service.heartbeat()


def close_pump():
    global _pump_research
    with _pump_research_lock:
        service, _pump_research = _pump_research, None
    if service is not None:
        service.close()


def _rpc_url(network: str) -> str:
    return RPC_ALLOWLIST.get(network, RPC_ALLOWLIST[NETWORK_DEFAULT])


def fetch_balance(pubkey: str, network: str = NETWORK_DEFAULT) -> int | None:
    if network not in RPC_ALLOWLIST:
        return None
    url = _rpc_url(network)
    host = urlparse(url).hostname or ""
    allowed = {urlparse(item).hostname for item in RPC_ALLOWLIST.values()}
    if host not in allowed:
        return None
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey, {"commitment": "confirmed"}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        timeout = 5
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_RPC_RESPONSE_LIMIT + 1)
            if len(raw) > _RPC_RESPONSE_LIMIT:
                return None
            payload = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    value = result.get("value") if isinstance(result, dict) else None
    return value if type(value) is int and 0 <= value < 2**64 else None


def _refresh_bundle(pubkey: str, network: str, generation: int | None = None) -> None:
    key = (pubkey, network)
    try:
        lamports = fetch_balance(pubkey, network)
        tokens = fetch_tokens(pubkey, network, strict=True)
        if lamports is None:
            raise RuntimeError("RPC_UNREACHABLE")
        with _rpc_lock:
            if generation is not None and generation != _rpc_generation:
                return
            _rpc_bundle[key] = (time.monotonic(), lamports, tokens)
            _rpc_errors.pop(key, None)
            _rpc_retry_after.pop(key, None)
            while len(_rpc_bundle) > 32:
                oldest = min(_rpc_bundle, key=lambda item: _rpc_bundle[item][0])
                _rpc_bundle.pop(oldest, None)
                _rpc_errors.pop(oldest, None)
    except Exception:
        with _rpc_lock:
            if generation is None or generation == _rpc_generation:
                _rpc_errors[key] = "RPC_UNREACHABLE"
                _rpc_retry_after[key] = time.monotonic() + _RPC_TTL
    finally:
        with _rpc_lock:
            if generation is None or generation == _rpc_generation:
                _rpc_inflight.discard(key)


def _bundle(pubkey: str, network: str, force: bool = False) -> tuple[int | None, list[dict[str, Any]]]:
    """UI path never waits on RPC. force=True is for an explicit user action."""
    key = (pubkey, network)
    now = time.monotonic()
    with _rpc_lock:
        hit = _rpc_bundle.get(key)
    if not force and hit is not None and now - hit[0] < _RPC_TTL:
        return hit[1], hit[2]
    if force:
        lamports = fetch_balance(pubkey, network)
        tokens = fetch_tokens(pubkey, network, strict=True)
        with _rpc_lock:
            _rpc_bundle[key] = (time.monotonic(), lamports, tokens)
        return lamports, tokens
    with _rpc_lock:
        if key not in _rpc_inflight and len(_rpc_inflight) < 4 and now >= _rpc_retry_after.get(key, 0):
            _rpc_inflight.add(key)
            try:
                threading.Thread(
                    target=_refresh_bundle,
                    args=(pubkey, network, _rpc_generation),
                    daemon=True,
                ).start()
            except Exception:
                _rpc_inflight.discard(key)
                _rpc_errors[key] = "CRYPTO_WORKER_START"
                _rpc_retry_after[key] = now + 1.0
    if hit is not None:
        return hit[1], hit[2]
    return None, []


def invalidate_rpc_cache() -> None:
    global _rpc_generation
    with _rpc_lock:
        _rpc_generation += 1
        _rpc_bundle.clear()
        _rpc_errors.clear()
        _rpc_retry_after.clear()
        _rpc_inflight.clear()


def _lab_gate(wait_s: float = 0.0) -> tuple[bool, str]:
    status = lab_status()
    if status.get("healthy") and (current_slot() or 0) > 0 and has_blockhash():
        return True, ""
    if status.get("running") and wait_s > 0:
        status = wait_ready(wait_s)
        if status.get("healthy") and (current_slot() or 0) > 0 and has_blockhash():
            return True, ""
        return False, "LAB_STARTING"
    if status.get("running"):
        return False, "LAB_STARTING"
    return False, "LAB_OFF"


def _wait_balance_at_least(
    pubkey: str, target: int, timeout_s: float = 8.0
) -> int | None:
    deadline = time.monotonic() + max(0.2, float(timeout_s))
    last: int | None = None
    while time.monotonic() < deadline:
        last = fetch_balance(pubkey, "testnet")
        if last is not None and last >= int(target):
            return last
        time.sleep(0.25)
    return last


def fetch_tokens(pubkey: str, network: str = NETWORK_DEFAULT, *, strict: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        payload = rpc_call(
            "getTokenAccountsByOwner",
            [
                pubkey,
                {"programId": program},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
            network,
        )
        if not payload or not isinstance(payload.get("result"), dict) or not isinstance(payload["result"].get("value"), list):
            if strict:
                raise RuntimeError("RPC_UNREACHABLE")
            continue
        for item in payload["result"].get("value") or []:
            if not isinstance(item, dict):
                continue
            account = item.get("account") or {}
            if not isinstance(account, dict):
                continue
            account_data = account.get("data") or {}
            if not isinstance(account_data, dict):
                continue
            data = account_data.get("parsed") or {}
            if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
                continue
            info = data.get("info") or {}
            amount = (info.get("tokenAmount") or {})
            if not isinstance(amount, dict):
                continue
            mint = str(info.get("mint") or "")
            raw = str(amount.get("amount") or "0")
            try:
                atomic = int(raw)
                decimals = int(amount.get("decimals") or 0)
            except (TypeError, ValueError):
                continue
            if not mint or atomic <= 0 or atomic >= 2**64 or not 0 <= decimals <= 255:
                continue
            symbol = KNOWN_MINTS.get(mint, mint[:4] + "…" + mint[-4:])
            display = format_units(atomic, decimals)
            rows.append(
                {
                    "mint": mint,
                    "symbol": symbol,
                    "amount": raw,
                    "decimals": decimals,
                    "display": display,
                    "ata": str(item.get("pubkey") or ""),
                    "program": "token-2022" if program == TOKEN_2022_PROGRAM else "token",
                }
            )
    return rows


def set_network(network: str) -> dict[str, Any]:
    chain = save_network(network)
    wallet = load_wallet()
    pubkey = str(wallet.get("pubkey") or "")
    if pubkey and chain in RPC_ALLOWLIST:
        lamports = fetch_balance(pubkey, chain)
        return save_wallet(pubkey, lamports, chain)
    wallet["network"] = chain
    return wallet


def rpc_call(method: str, params: list[Any], network: str | None = None) -> dict[str, Any] | None:
    chain = network or load_network()
    if chain not in RPC_ALLOWLIST:
        return {"error": {"code": -32602, "message": "CRYPTO_NETWORK"}}
    # The policy lives at the common RPC boundary, including idle Trader ticks.
    read_methods = {
        "getBalance", "getTokenAccountsByOwner", "getAccountInfo",
        "getLatestBlockhash", "getSignatureStatuses", "getTransaction",
        "getSlot", "getBlockHeight", "getHealth", "getVersion",
        "getFeeForMessage", "isBlockhashValid", "simulateTransaction",
        "getMultipleAccounts", "getEpochInfo", "getMinimumBalanceForRentExemption",
    }
    if method not in read_methods and (chain != "testnet" or load_network() != "testnet"):
        return {"error": {"code": -32001, "message": "MAINNET_OBSERVE_ONLY"}}
    if method not in read_methods | {"requestAirdrop", "sendTransaction"}:
        return {"error": {"code": -32601, "message": "CRYPTO_RPC_METHOD"}}
    url = _rpc_url(chain)
    host = urlparse(url).hostname or ""
    allowed = {urlparse(item).hostname for item in RPC_ALLOWLIST.values()}
    if host not in allowed:
        return None
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(_RPC_RESPONSE_LIMIT + 1)
            if len(raw) > _RPC_RESPONSE_LIMIT:
                return {"error": {"code": -32000, "message": "CRYPTO_RPC_RESPONSE_LIMIT"}}
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(_RPC_RESPONSE_LIMIT + 1)
            if len(raw) > _RPC_RESPONSE_LIMIT:
                return {"error": {"code": exc.code, "message": "CRYPTO_RPC_RESPONSE_LIMIT"}}
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeError, OSError):
            return {
                "error": {
                    "code": exc.code,
                    "message": "HTTP " + str(exc.code),
                }
            }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _lab_rpc(method: str, params: list[Any]) -> dict[str, Any] | None:
    """Bind every lab transaction to localnet and fail on a network switch."""
    if load_network() != "testnet":
        raise RuntimeError("MAINNET_OBSERVE_ONLY")
    return rpc_call(method, params, "testnet")


def create_test_wallet() -> dict[str, Any]:
    invalidate_rpc_cache()
    save_network("testnet")
    pubkey = ensure_test_wallet()
    lamports = fetch_balance(pubkey, "testnet")
    wallet = save_wallet(pubkey, lamports, "testnet")
    wallet["signer"] = True
    wallet["created"] = True
    ok, _code = _lab_gate(wait_s=8.0)
    if ok and (lamports is None or lamports < 10 * 1_000_000_000):
        funded = airdrop_testnet(LAB_AIRDROP_LAMPORTS)
        funded["created"] = True
        funded["signer"] = True
        return funded
    return wallet


def airdrop_testnet(lamports: int = LAB_AIRDROP_LAMPORTS) -> dict[str, Any]:
    invalidate_rpc_cache()
    save_network("testnet")
    pubkey = str(load_wallet().get("pubkey") or "") or load_test_pubkey()
    if not pubkey:
        pubkey = ensure_test_wallet()
        save_wallet(pubkey, None, "testnet")
    amount = int(lamports)
    row: dict[str, Any] = {
        "ts": int(time.time()),
        "mode": "TESTNET",
        "network": "testnet",
        "side": "airdrop",
        "size_sol": amount / 1_000_000_000,
        "symbol": "SOL",
        "source": "lab-airdrop",
        "txid": "NONE",
        "wallet": pubkey,
    }
    ok, code = _lab_gate(wait_s=20.0)
    if not ok:
        row["error"] = code
        row["hint"] = human_error(code)
        append_ledger(row)
        wallet = load_wallet()
        wallet["airdrop"] = decorate_ledger_row(row)
        wallet["signer"] = signer_for(pubkey)
        return wallet
    before = fetch_balance(pubkey, "testnet")
    if before is None:
        before = 0
    payload = rpc_call(
        "requestAirdrop",
        [pubkey, amount, {"commitment": "confirmed"}],
        "testnet",
    )
    sig = None
    err = None
    if not payload:
        err = "RPC_UNREACHABLE"
    elif payload.get("result"):
        sig = str(payload.get("result") or "")
    else:
        fault = payload.get("error")
        if isinstance(fault, dict):
            msg = str(fault.get("message") or fault)
            if fault.get("code") == -32603 or "internal" in msg.lower():
                err = "AIRDROP_FAIL"
            else:
                err = short_error(msg) or "AIRDROP_FAIL"
        else:
            err = short_error(str(fault or "")) or "AIRDROP_FAIL"
    wallet = load_wallet()
    if sig:
        landed = confirm_signature(
            lambda method, params: rpc_call(method, params, "testnet"),
            sig,
        )
        target = before + max(1, amount // 2)
        bal = _wait_balance_at_least(pubkey, target, timeout_s=10.0)
        if bal is None:
            bal = fetch_balance(pubkey, "testnet")
        wallet = save_wallet(pubkey, bal, "testnet")
        row["txid"] = sig
        if bal is not None and bal > before:
            row["hint"] = (
                "Lab airdrop landed. "
                + format_sol(before)
                + " → "
                + format_sol(bal)
                + " SOL"
            )
            mark_proven("airdrop", sig)
        else:
            row["error"] = "AIRDROP_FAIL"
            row["hint"] = (
                "Airdrop did not raise the balance. "
                + ("Signature not confirmed. " if not landed else "")
                + "Toggle LAB OFF/ON if the chain is stuck."
            )
        if bal is not None:
            row["balance_lamports"] = bal
            row["balance_sol"] = format_sol(bal)
    else:
        row["error"] = err or "AIRDROP_FAIL"
        row["hint"] = human_error(row["error"])
        bal = fetch_balance(pubkey, "testnet")
        wallet = save_wallet(pubkey, bal, "testnet")
    append_ledger(row)
    wallet["airdrop"] = decorate_ledger_row(row)
    wallet["signer"] = signer_for(pubkey)
    wallet["balance_sol"] = format_sol(wallet.get("balance_lamports"))
    return wallet


def connect_watch(pubkey: str) -> dict[str, Any]:
    key = validate_pubkey(pubkey)
    chain = load_network()
    lamports = fetch_balance(key, chain) if chain in RPC_ALLOWLIST else None
    return save_wallet(key, lamports, chain)


def ingest_paper_signal(raw: str) -> dict[str, Any]:
    signal = parse_signal(raw)
    wallet = load_wallet()
    chain = load_network()
    live = chain == "mainnet"
    pubkey = str(wallet.get("pubkey") or "")
    row: dict[str, Any] = {
        "ts": int(time.time()),
        "mode": "OBSERVE" if live else "LOCALNET_DIAGNOSTIC",
        "network": chain,
        "side": signal["side"],
        "size_sol": signal["size_sol"],
        "symbol": signal["symbol"],
        "source": signal["source"],
        "txid": "UNSENT",
        "wallet": pubkey,
    }
    if live:
        row["error"] = "MAINNET_OBSERVE_ONLY"
        row["hint"] = human_error("MAINNET_OBSERVE_ONLY")
        append_ledger(row)
        return decorate_ledger_row(row)
    if not signer_for(pubkey):
        row["error"] = "NO_SIGNER"
        row["hint"] = human_error("NO_SIGNER")
        append_ledger(row)
        return decorate_ledger_row(row)
    ok, code = _lab_gate(wait_s=12.0)
    if not ok:
        row["error"] = code
        row["txid"] = "NONE"
        row["hint"] = human_error(code)
        append_ledger(row)
        return decorate_ledger_row(row)
    lamports = fetch_balance(pubkey, "testnet") if pubkey else None
    if lamports is None:
        row["error"] = "RPC_UNREACHABLE"
        row["txid"] = "NONE"
        row["hint"] = human_error("RPC_UNREACHABLE")
        append_ledger(row)
        return decorate_ledger_row(row)
    tokens = fetch_tokens(pubkey, "testnet") if pubkey else []
    pyusd = next((t for t in tokens if t.get("symbol") == "PYUSD"), None)
    if pyusd:
        row["symbol"] = "PYUSD"
        row["size_display"] = str(pyusd.get("display") or pyusd.get("amount") or "")
    if lamports <= 5000:
        row["error"] = "NEED_FEE_SOL"
        row["txid"] = "NONE"
        row["hint"] = human_error("NEED_FEE_SOL")
        append_ledger(row)
        return decorate_ledger_row(row)
    send_lamports = min(int(signal["size_sol"] * 1_000_000_000), max(1, lamports - 5000))
    if send_lamports > lamports - 5000:
        send_lamports = 1
    try:
        sent = send_self_transfer(_lab_rpc, send_lamports, expected_pubkey=pubkey)
        row["txid"] = sent["txid"]
        row["status"] = sent["status"]
        row["size_sol"] = send_lamports / 1_000_000_000
        row["source"] = "onchain-self-transfer"
        row["hint"] = (
            "Confirmed localnet self-transfer "
            + format_sol(send_lamports)
            + " SOL."
        )
        invalidate_rpc_cache()
        fresh = fetch_balance(pubkey, "testnet")
        if fresh is not None:
            save_wallet(pubkey, fresh, "testnet")
            row["balance_lamports"] = fresh
            row["balance_sol"] = format_sol(fresh)
        mark_proven("buy", sent["txid"])
    except Exception as exc:
        row["error"] = short_error(str(exc)[:240]) or "CRYPTO_RPC"
        row["hint"] = human_error(str(exc)[:240])
        row["txid"] = str(getattr(exc, "txid", "NONE"))
        row["status"] = str(getattr(exc, "status", "failed"))
    append_ledger(row)
    return decorate_ledger_row(row)


_strategy_factory_lock = threading.Lock()
_strategy_factory_job: dict[str, Any] = {
    "state": "idle",
    "note": "",
    "started": 0.0,
    "result": crypto_strategy_factory.empty_snapshot(),
}


def _launch_job_thread(target, name: str, lock, job: dict[str, Any], args=()) -> None:
    try:
        threading.Thread(target=target, name=name, args=args, daemon=True).start()
    except Exception:
        with lock:
            job.update(state="error", note="CRYPTO_WORKER_START")
            if isinstance(job.get("result"), dict):
                job["result"] = dict(job["result"], state="ERROR", note="CRYPTO_WORKER_START")
        raise RuntimeError("CRYPTO_WORKER_START") from None


def strategy_factory_status() -> dict[str, Any]:
    with _strategy_factory_lock:
        job = dict(_strategy_factory_job)
        result = job.get("result")
        if isinstance(result, dict):
            job["result"] = result
        return job


def _factory_frames() -> dict[str, dict[str, Any]]:
    try:
        highs, lows, closes, volumes = fetch_klines(
            "1h",
            1000,
            timeout=8.0,
        )
        frame = {
            "1h": {
                "highs": highs,
                "lows": lows,
                "closes": closes,
                "volumes": volumes,
                "times": list(_kline_times.get("1h", [])),
                "source": "binance", "symbol": "SOLUSDT", "closed_only": True,
            }
        }
        frame["1h"] = crypto_data.validate_frame(frame["1h"], "1h", min_bars=120)
        if frame["1h"]["gaps"]:
            return {}
        return frame
    except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return {}


def _run_strategy_factory_job() -> None:
    try:
        report = crypto_strategy_factory.run_factory(_factory_frames())
        with _strategy_factory_lock:
            _strategy_factory_job["state"] = "done"
            _strategy_factory_job["note"] = str(report.get("note") or "")
            _strategy_factory_job["result"] = report
    except Exception as exc:
        with _strategy_factory_lock:
            _strategy_factory_job["state"] = "error"
            _strategy_factory_job["note"] = "STRATEGY_FACTORY_ERROR: " + str(exc)[:160]
            _strategy_factory_job["result"] = {
                **crypto_strategy_factory.empty_snapshot(),
                "state": "ERROR",
                "note": "Strategy factory could not finish safely.",
                "orchestration": crypto_strategy_factory.orchestration_snapshot("ERROR"),
            }


def start_strategy_factory() -> dict[str, Any]:
    launch = False
    with _strategy_factory_lock:
        if str(_strategy_factory_job.get("state") or "") != "running":
            _strategy_factory_job["state"] = "running"
            _strategy_factory_job["note"] = (
                "SOLUSDT 1h · max 2 workers · paper only"
            )
            _strategy_factory_job["started"] = time.time()
            _strategy_factory_job["result"] = {
                **crypto_strategy_factory.empty_snapshot(),
                "state": "RUNNING",
                "note": _strategy_factory_job["note"],
                "orchestration": crypto_strategy_factory.orchestration_snapshot("RUNNING"),
            }
            launch = True
    if launch:
        _launch_job_thread(_run_strategy_factory_job, "gg-crypto-strategy-factory",
                           _strategy_factory_lock, _strategy_factory_job)
    payload = status_payload()
    payload["strategy_factory_job"] = strategy_factory_status()
    return payload


def reset_strategy_factory() -> dict[str, Any]:
    with _strategy_factory_lock:
        if str(_strategy_factory_job.get("state") or "") != "running":
            _strategy_factory_job["state"] = "idle"
            _strategy_factory_job["note"] = ""
            _strategy_factory_job["started"] = 0.0
            _strategy_factory_job["result"] = crypto_strategy_factory.empty_snapshot()
    return status_payload()


_desk_lock = threading.Lock()
_desk_job: dict[str, Any] = {
    "state": "idle",
    "note": "",
    "started": 0.0,
    "result": crypto_desk.empty_snapshot(),
}


def desk_status() -> dict[str, Any]:
    with _desk_lock:
        job = dict(_desk_job)
        result = job.get("result")
        if isinstance(result, dict):
            job["result"] = result
        return job


def _run_desk_job() -> None:
    try:
        report = crypto_desk.run_desk(_factory_frames())
        with _desk_lock:
            _desk_job["state"] = "done"
            _desk_job["note"] = str(report.get("note") or "")
            _desk_job["result"] = report
    except Exception as exc:
        with _desk_lock:
            _desk_job["state"] = "error"
            _desk_job["note"] = "DESK_ERROR: " + str(exc)[:160]
            _desk_job["result"] = {
                **crypto_desk.empty_snapshot(),
                "state": "ERROR",
                "note": "Desk could not finish safely.",
            }


def start_desk() -> dict[str, Any]:
    launch = False
    with _desk_lock:
        if str(_desk_job.get("state") or "") != "running":
            _desk_job["state"] = "running"
            _desk_job["note"] = "PAPER DESK · FRONT MAN IN CODE"
            _desk_job["started"] = time.time()
            _desk_job["result"] = {
                **crypto_desk.empty_snapshot(),
                "state": "RUNNING",
                "note": _desk_job["note"],
            }
            launch = True
    if launch:
        _launch_job_thread(_run_desk_job, "gg-crypto-desk", _desk_lock, _desk_job)
    payload = status_payload()
    payload["desk_job"] = desk_status()
    return payload


def reset_desk() -> dict[str, Any]:
    with _desk_lock:
        if str(_desk_job.get("state") or "") != "running":
            _desk_job["state"] = "idle"
            _desk_job["note"] = ""
            _desk_job["started"] = 0.0
            _desk_job["result"] = crypto_desk.empty_snapshot()
    return status_payload()


def paper_pair() -> str:
    return "KASUSDT" if portfolio_asset() == "KAS" else "SOLUSDT"


def paper_snapshot() -> dict[str, Any]:
    try:
        return crypto_paper.snapshot(paper_pair())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"mode": "PAPER_ONLY", "accounts": [], "events": [],
                "error": "Paper state unavailable: " + type(exc).__name__}


def trader_snapshot(paper: dict[str, Any]) -> dict[str, Any]:
    result = dict(crypto_trader.snapshot(), books=crypto_bots.catalog())
    chosen = crypto_bots.selected()
    row = next((r for r in paper.get("accounts", []) if r["book"] == chosen), {})
    for key in ("backtest", "backtest_prev"):
        report = result.get(key) or {}
        if (report.get("data") or {}).get("symbol") != paper_pair():
            result[key] = {}
    result.update(book=chosen, armed=bool(row.get("enabled")), mode="PAPER_ONLY",
                  tokens=row.get("tokens", 0), usd=row.get("quote", 200),
                  last={"action": "paper", "note": row.get("error") or row.get("halt_reason") or row.get("status", "IDLE")},
                  paper_account=row)
    return result


def status_payload(rail: bool = False) -> dict[str, Any]:
    wallet = load_wallet()
    pubkey = str(wallet.get("pubkey") or "")
    chain = load_network()
    wallet["network"] = chain
    tokens: list[dict[str, Any]] = []
    if pubkey and chain in RPC_ALLOWLIST:
        lamports, tokens = _bundle(pubkey, chain, force=False)
        if lamports is not None and lamports != wallet.get("balance_lamports"):
            wallet = save_wallet(pubkey, lamports, chain)
        if lamports is not None:
            wallet["balance_lamports"] = lamports
    wallet["balance_sol"] = format_sol(wallet.get("balance_lamports"))
    wallet["tokens"] = tokens
    with _rpc_lock:
        wallet["rpc_error"] = _rpc_errors.get((pubkey, chain), "") if pubkey else ""
        hit = _rpc_bundle.get((pubkey, chain))
        wallet["rpc_loading"] = (pubkey, chain) in _rpc_inflight
        wallet["rpc_stale"] = bool(pubkey and (hit is None or time.monotonic() - hit[0] >= _RPC_TTL))
    pyusd = next((t for t in tokens if t.get("symbol") == "PYUSD"), None)
    if pyusd:
        wallet["pyusd"] = pyusd.get("display")
        wallet["pyusd_decimals"] = pyusd.get("decimals")
    legend = "OBSERVE" if chain == "mainnet" else "LOCALNET"
    rpc = str(RPC_ALLOWLIST.get(chain) or "")
    holdings: list[dict[str, Any]] = []
    if pubkey:
        holdings.append(
            {
                "symbol": "SOL",
                "display": wallet.get("balance_sol") or "—",
                "decimals": 9,
                "mint": "native",
                "program": "system",
            }
        )
        holdings.extend(tokens)
    pump_service().bind_wallet(pubkey, chain)
    pump = pump_service().snapshot()
    if rail:
        return {
            "wallet": {
                "pubkey": pubkey,
                "label": wallet.get("label") or "",
                "balance_sol": wallet.get("balance_sol"),
                "network": chain,
            },
            "legend": legend,
            "signer": signer_for(pubkey),
            "accounts": account_catalog(),
            "holdings": holdings[:8],
            "lab": lab_status(),
            "pump": {key: pump.get(key) for key in ("mint", "state", "loading", "stale", "slot", "error")},
        }
    paper = paper_snapshot()
    ledger = [decorate_ledger_row(item) for item in read_ledger(16)]
    for lot in crypto_trader.read_lots(16):
        side = str(lot.get("side") or "")
        if side not in ("buy", "sell"):
            continue
        hint = str(lot.get("venue") or "vault")
        if side == "buy":
            hint = "Vault float buy " + format_sol(lot.get("sol"))
        else:
            hint = "Vault sell, profit " + format_units(lot.get("profit_usd"), 6)
        ledger.append(
            decorate_ledger_row(
                {
                    "ts": lot.get("ts"),
                    "side": side,
                    "txid": str(lot.get("id") or "LOT"),
                    "hint": hint,
                    "source": "trader-80-20",
                    "mode": "PAPER",
                    "status": "simulated",
                    "error": None,
                }
            )
        )
    for event in paper.get("events", []):
        ledger.append(decorate_ledger_row({"ts": event.get("ts"), "side": event.get("side"),
            "txid": "PAPER", "source": "paper-" + str(event.get("book")),
            "mode": "PAPER", "status": "simulated", "error": None,
            "hint": str(event.get("book", "")) + " · " + str(event.get("pair", ""))
                + " · " + str(event.get("side", "")) + " " + format_units(event.get("sol"), 9)
                + " " + str(paper.get("base_asset", ""))
                + (" · historical recovery" if event.get("recovery_replay") else "")}))
    ledger.sort(key=lambda item: int(item.get("ts") or 0))
    if chain != "mainnet":
        ledger = [
            item
            for item in ledger
            if str(item.get("error") or "")
            not in ("MAINNET_NOT_ARMED", "MAINNET_OBSERVE_ONLY")
            and "Mainnet stays locked" not in str(item.get("hint") or "")
            and "observe-only" not in str(item.get("hint") or "").lower()
        ]
    ledger = ledger[-16:]
    last = ledger[-1] if ledger else {}
    chart = chart_snapshot()
    bot = load_bot()
    if not bot.get("closes") and chart.get("closes"):
        bot = dict(bot)
        bot["closes"] = list(chart["closes"])
    quote = quote_for_wallet(wallet)
    if holdings and quote.get("usd"):
        holdings[0]["usd"] = quote.get("usd")
        holdings[0]["sek"] = quote.get("sek")
    kaspa = kaspa_covenant.snapshot()
    kas_chart = kas_chart_snapshot()
    holdings = pump_service().enrich_holdings(holdings, chart.get("price") or ((chart.get("closes") or [None])[-1]), wallet_network=chain)
    tokens = [row for row in holdings if row.get("mint") != "native"]
    wallet["tokens"] = tokens
    portfolio = {
        "asset": portfolio_asset(),
        "sol": crypto_portfolio.summarize(holdings, chart, usd_sek=quote.get("usd_sek")),
        # This is the covenant's simulation balance, not an imported live wallet.
        "kas": crypto_portfolio.summarize([
            {"symbol": "KAS", "mint": "native", "display": kaspa.get("value_kas")}
        ], kas_chart, native_symbol="KAS", usd_sek=quote.get("usd_sek")),
    }
    return {
        "wallet": wallet,
        "legend": legend,
        "mainnet_observe": chain == "mainnet",
        "rpc": rpc,
        "signer": signer_for(pubkey),
        "accounts": account_catalog(),
        "tokens": tokens,
        "holdings": holdings,
        "last_signal": last,
        "ledger": ledger,
        "lab": lab_status(),
        "bot": bot,
        "chart": chart,
        "quote": quote,
        "arb": crypto_flash_arb.pool_status(),
        "trader": trader_snapshot(paper),
        "paper_engine": paper,
        "backtest_job": backtest_job(),
        "paper_jobs": paper_tick_status(),
        "polymarket": polymarket_research.snapshot(),
        "strategy_factory": strategy_factory_status().get(
            "result",
            crypto_strategy_factory.empty_snapshot(),
        ),
        "strategy_factory_job": strategy_factory_status(),
        "desk": desk_status().get("result", crypto_desk.empty_snapshot()),
        "desk_job": desk_status(),
        "kaspa": kaspa,
        "kas_chart": kas_chart,
        "portfolio": portfolio,
        "pump": pump,
        "proven": load_proven(),
        "bots": [
            {
                "id": "signal-swap-1",
                "title": "signal → localnet diagnostic",
                "state": "TESTNET",
            },
            {
                "id": "trader-80-20",
                "title": "cycle + day/week/month swings",
                "state": "ARMED" if crypto_trader.load_state().get("armed") else "IDLE",
            },
            {
                "id": "flash-cpmm",
                "title": "lab CPMM",
                "state": "LAB",
            },
        ],
    }


def kaspa_genesis() -> dict[str, Any]:
    return kaspa_covenant.genesis()


def kaspa_transition(function: str, amount: int) -> dict[str, Any]:
    return kaspa_covenant.transition(function, amount)


def kaspa_compile() -> dict[str, Any]:
    return kaspa_covenant.compile_counter()


def kaspa_set_network(network: str) -> dict[str, Any]:
    return kaspa_covenant.set_network(network)


def import_keypair_file(path: str) -> dict[str, Any]:
    pubkey = import_solana_keypair(path)
    chain = load_network()
    lamports = fetch_balance(pubkey, chain) if chain in RPC_ALLOWLIST else None
    wallet = save_wallet(pubkey, lamports, chain)
    wallet["signer"] = True
    wallet["imported"] = True
    return wallet


def disconnect() -> dict[str, Any]:
    invalidate_rpc_cache()
    return clear_wallet()


def select_account(pubkey: str) -> dict[str, Any]:
    key = validate_pubkey(pubkey)
    chain = load_network()
    lamports = fetch_balance(key, chain) if chain in RPC_ALLOWLIST else None
    save_wallet(key, lamports, chain)
    return status_payload()


def lab_on() -> dict[str, Any]:
    invalidate_rpc_cache()
    status = start_lab()
    if status.get("healthy"):
        mark_proven("lab")
        crypto_trader.set_armed(True)
    return status_payload()


def lab_off() -> dict[str, Any]:
    stop_lab()
    invalidate_rpc_cache()
    return status_payload()


def run_flash_arb(usd_units: str | None = None) -> dict[str, Any]:
    chain = load_network()
    if chain == "mainnet":
        row = {
            "ts": int(time.time()),
            "mode": "OBSERVE",
            "network": chain,
            "side": "arb",
            "txid": "UNSENT",
            "error": "MAINNET_OBSERVE_ONLY",
            "hint": human_error("MAINNET_OBSERVE_ONLY"),
        }
        append_ledger(row)
        payload = status_payload()
        payload["arb_last"] = decorate_ledger_row(row)
        return payload
    try:
        if usd_units not in (None, ""):
            borrow = int(usd_units)
        else:
            borrow = crypto_flash_arb.optimal_borrow() or 10 * 1_000_000
    except (TypeError, ValueError):
        borrow = 10 * 1_000_000
    if borrow <= 0 or borrow > 1_000_000 * 1_000_000:
        raise ValueError("CRYPTO_ARB_SIZE")
    result = crypto_flash_arb.commit_flash_arb(borrow)
    row: dict[str, Any] = {
        "ts": int(time.time()),
        "mode": "TESTNET",
        "network": chain,
        "side": "arb",
        "source": "flash-cpmm",
        "size_sol": 0,
        "symbol": "USDC",
        "txid": "REVERT",
        "profit": format_units(result.get("profit_usd"), 6),
        "buy_pool": result.get("buy_pool"),
        "sell_pool": result.get("sell_pool"),
    }
    if not result.get("ok"):
        row["error"] = str(result.get("error") or "NO_PROFIT")
        row["hint"] = human_error(row["error"])
        append_ledger(row)
        payload = status_payload()
        payload["arb_last"] = decorate_ledger_row(row)
        return payload
    mark_proven("arb")
    lab = lab_status()
    pubkey = str(load_wallet().get("pubkey") or "")
    if lab.get("healthy") and signer_for(pubkey):
        try:
            sent = send_self_transfer(_lab_rpc, 10_000, expected_pubkey=pubkey)
            row["txid"] = sent["txid"]
            row["chain_status"] = sent["status"]
            row["hint"] = "Simulated CPMM result; confirmed localnet self-transfer diagnostic."
            invalidate_rpc_cache()
        except Exception as exc:
            row["txid"] = getattr(exc, "txid", "POOLS_ONLY")
            row["chain_status"] = getattr(exc, "status", "failed")
            row["error"] = str(exc)[:160]
            row["hint"] = "Simulated CPMM result; chain diagnostic: " + human_error(str(exc)[:160])
    else:
        row["txid"] = "POOLS_ONLY"
        row["hint"] = "Simulated CPMM result. No on-chain swap or settlement."
    row["mode"] = "PAPER"
    row["status"] = "simulated"
    append_ledger(row)
    payload = status_payload()
    payload["arb_last"] = decorate_ledger_row(row)
    payload["arb_quote"] = {
        "profit": format_units(result.get("profit_usd"), 6),
        "ok": True,
        "price_a": result.get("price_a_after") or result.get("price_a"),
        "price_b": result.get("price_b_after") or result.get("price_b"),
    }
    return payload


def reset_flash_arb() -> dict[str, Any]:
    crypto_flash_arb.reset_pools()
    payload = status_payload()
    payload["arb_last"] = {"side": "arb", "txid": "RESET"}
    return payload


def start_polymarket_query(
    preset: str,
    query_date: str,
    hour: str,
    slug: str = "",
) -> dict[str, Any]:
    payload = status_payload()
    payload["polymarket"] = polymarket_research.start_query(
        preset,
        query_date,
        hour,
        slug,
    )
    return payload


def poll_polymarket_query() -> dict[str, Any]:
    payload = status_payload()
    payload["polymarket"] = polymarket_research.snapshot()
    return payload


def reset_polymarket_query() -> dict[str, Any]:
    payload = status_payload()
    payload["polymarket"] = polymarket_research.reset()
    return payload


_KLINE_HOSTS = {"api.binance.com"}
_KLINE_SYMBOLS = ("SOLUSDT", "KASUSDT")
_CHART_HOSTS = frozenset(
    {"api.binance.com", "api.coingecko.com", "api.frankfurter.app"}
)
_CHART_TTL = 15.0
_chart_cache: dict[str, Any] = {
    "ts": 0.0,
    "closes": [],
    "times": [],
    "price": "",
    "source": "",
    "interval": "",
    "usd_sek": 0.0,
}
_kline_times: dict[str, list[int]] = {}
_kas_kline_times: dict[str, list[int]] = {}
_kas_chart_cache: dict[str, Any] = {
    "ts": 0.0,
    "closes": [],
    "times": [],
    "price": "",
    "source": "",
    "interval": "15m",
    "error": "",
}
_BOT_NAME = "bot.json"


def _bot_path():
    from backend.crypto_contract import ensure_state_dir

    return ensure_state_dir() / _BOT_NAME


def load_bot() -> dict[str, Any]:
    path = _bot_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    closes = payload.get("closes")
    if not isinstance(closes, list):
        closes = []
    out_closes: list[float] = []
    for item in closes[-80:]:
        try:
            out_closes.append(float(item))
        except (TypeError, ValueError):
            continue
    return {
        "armed": bool(payload.get("armed")),
        "symbol": str(payload.get("symbol") or "SOLUSDT"),
        "size_sol": float(payload.get("size_sol") or 0.01),
        "last": payload.get("last") if isinstance(payload.get("last"), dict) else {},
        "closes": out_closes,
    }


def save_bot(payload: dict[str, Any]) -> dict[str, Any]:
    path = _bot_path()
    write_state_json(path, payload)
    path.chmod(0o600)
    return load_bot()


def fetch_klines(
    interval: str,
    limit: int,
    timeout: float = 12.0,
    start_time: int | None = None,
    end_time: int | None = None,
    symbol: str = "SOLUSDT",
    closed_only: bool = True,
) -> tuple[list[float], list[float], list[float], list[float]]:
    sym = str(symbol or "SOLUSDT").upper()
    step = crypto_data.BAR_SECONDS.get(interval)
    if not step:
        raise RuntimeError("CRYPTO_KLINE_INTERVAL")
    if sym not in _KLINE_SYMBOLS:
        raise RuntimeError("CRYPTO_KLINE_SYMBOL")
    url = (
        "https://api.binance.com/api/v3/klines?symbol="
        + sym
        + "&interval="
        + str(interval)
        + "&limit="
        + str(int(limit))
    )
    if start_time is not None:
        url += "&startTime=" + str(int(start_time))
    if end_time is not None:
        url += "&endTime=" + str(int(end_time))
    host = urlparse(url).hostname or ""
    if host not in _KLINE_HOSTS:
        raise RuntimeError("CRYPTO_KLINE_HOST")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gg-ai-desktop-crypto/1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if start_time is not None or end_time is not None:
        need = 1
    else:
        need = min(40, max(8, int(limit)))
    if not isinstance(payload, list) or len(payload) < need:
        raise RuntimeError("CRYPTO_KLINE")
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    times: list[int] = []
    for row in payload:
        if closed_only and int(row[0]) / 1000 + step > time.time():
            continue
        highs.append(float(row[2]))
        lows.append(float(row[3]))
        closes.append(float(row[4]))
        volumes.append(float(row[5]))
        times.append(int(row[0]) // 1000)
    if len(closes) < need:
        raise RuntimeError("CRYPTO_CANDLES")
    checked = crypto_data.validate_frame({"highs": highs, "lows": lows, "closes": closes,
        "volumes": volumes, "times": times, "source": "binance", "symbol": sym},
        interval, min_bars=need, require_closed=closed_only)
    if checked["gaps"]:
        raise RuntimeError("CRYPTO_DATA_GAPS")
    if sym == "KASUSDT":
        _kas_kline_times[str(interval)] = times
    else:
        _kline_times[str(interval)] = times
    return highs, lows, closes, volumes


SOL_LISTED_MS = 1597104000000
_HISTORY_NAME = "sol-klines-1h.json"


def _history_path(interval: str = "1h"):
    from backend.crypto_contract import ensure_state_dir

    name = "sol-klines-" + str(interval).replace("/", "") + ".json"
    return ensure_state_dir() / name


def fetch_klines_history(
    interval: str = "1h",
    start_ms: int = SOL_LISTED_MS,
    timeout: float = 12.0,
) -> tuple[list[float], list[float], list[float], list[float], list[int]]:
    if interval not in crypto_data.BAR_SECONDS:
        raise ValueError("CRYPTO_KLINE_INTERVAL")
    path = _history_path(interval)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        cached = {}
    if cached.get("data_version") != crypto_data.HISTORY_VERSION:
        cached = {}
    if str(cached.get("interval") or interval) != str(interval):
        cached = {}
    if cached:
        try:
            valid = crypto_data.validate_frame(cached, interval, min_bars=1)
            if valid["gaps"]:
                cached = {}
        except (ValueError, TypeError, KeyError, OverflowError):
            cached = {}
    highs = [float(x) for x in (cached.get("highs") or [])]
    lows = [float(x) for x in (cached.get("lows") or [])]
    closes = [float(x) for x in (cached.get("closes") or [])]
    volumes = [float(x) for x in (cached.get("volumes") or [])]
    times = [int(x) for x in (cached.get("times") or [])]
    # Re-fetch the tail; legacy/current partial bars must never be append-only.
    if times:
        highs.pop(); lows.pop(); closes.pop(); volumes.pop(); tail = times.pop()
    else:
        tail = None
    cursor = start_ms
    if times:
        cursor = max(cursor, times[-1] * 1000 + 1)
    if tail is not None:
        cursor = max(start_ms, tail * 1000)
    now_ms = int(time.time() * 1000)
    pages = 0
    rate_limit_retries = 0
    # Full SOLUSDT listing: ~6y. 1m ≈ 3150 pages, 5m ≈ 640.
    page_cap = {
        "1m": 3400,
        "5m": 720,
        "15m": 250,
        "1h": 80,
        "4h": 40,
        "8h": 20,
        "1d": 10,
    }.get(str(interval), 80)
    checkpoint_every = 250 if str(interval) == "1m" else (80 if str(interval) == "5m" else 0)

    def _persist() -> None:
        if not closes:
            return
        checked = crypto_data.validate_frame({"highs": highs, "lows": lows, "closes": closes,
            "volumes": volumes, "times": times}, interval, min_bars=1)
        if checked["gaps"]:
            raise RuntimeError("CRYPTO_DATA_GAPS")
        blob = json.dumps(
            {
                "data_version": crypto_data.HISTORY_VERSION,
                "source": "binance", "symbol": "SOLUSDT", "closed_only": True,
                "fetched_at": time.time(),
                "interval": interval,
                "highs": highs,
                "lows": lows,
                "closes": closes,
                "volumes": volumes,
                "times": times,
            },
            separators=(",", ":"),
        )
        path.write_text(blob + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    while cursor < now_ms and pages < page_cap:
        url = (
            "https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval="
            + str(interval)
            + "&limit=1000&startTime="
            + str(int(cursor))
        )
        host = urlparse(url).hostname or ""
        if host not in _KLINE_HOSTS:
            raise RuntimeError("CRYPTO_KLINE_HOST")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "gg-ai-desktop-crypto/1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=float(timeout)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) in (418, 429):
                rate_limit_retries += 1
                if rate_limit_retries <= 2:
                    time.sleep(2.0 * rate_limit_retries)
                    continue
            raise RuntimeError("CRYPTO_HISTORY_REFRESH") from exc
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            raise RuntimeError("CRYPTO_HISTORY_REFRESH")
        if not isinstance(payload, list) or not payload:
            break
        last_open = None
        for row in payload:
            try:
                open_ms = int(row[0])
                if open_ms / 1000 + crypto_data.BAR_SECONDS[interval] > time.time():
                    continue
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])
                vol = float(row[5])
            except (TypeError, ValueError, IndexError):
                continue
            ts = open_ms // 1000
            if times and ts <= times[-1]:
                continue
            highs.append(high)
            lows.append(low)
            closes.append(close)
            volumes.append(vol)
            times.append(ts)
            last_open = open_ms
        pages += 1
        if checkpoint_every and pages % checkpoint_every == 0:
            _persist()
        if last_open is None or len(payload) < 1000:
            break
        cursor = last_open + 1
        time.sleep(0.08)
    _persist()
    if len(closes) < 80:
        raise RuntimeError("CRYPTO_HISTORY")
    return highs, lows, closes, volumes, times


def fetch_sol_ohlcv() -> tuple[list[float], list[float], list[float], list[float]]:
    return fetch_klines("5m", 200)


def _price_rows(rows: Any, precision: int) -> tuple[list[float], list[int]]:
    if not isinstance(rows, list) or len(rows) < 8:
        raise RuntimeError("CRYPTO_CHART")
    closes: list[float] = []
    times: list[int] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise RuntimeError("CRYPTO_CHART")
        try:
            stamp = int(float(row[0]) / 1000.0)
            price = round(float(row[1]), precision)
        except (TypeError, ValueError, IndexError, OverflowError) as exc:
            raise RuntimeError("CRYPTO_CHART") from exc
        if stamp <= 0 or not math.isfinite(price) or price <= 0 or (times and stamp <= times[-1]):
            raise RuntimeError("CRYPTO_CHART")
        times.append(stamp)
        closes.append(price)
    return closes, times


def _source_chart_interval(times: list[int]) -> str:
    deltas = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    if not deltas:
        return "unknown"
    observed = deltas[len(deltas) // 2]
    return next((tf for tf in _CHART_TFS
                 if crypto_data.BAR_SECONDS[tf] >= observed * .9), f"{observed}s")


def _coingecko_sol_chart() -> tuple[list[float], list[int]]:
    url = (
        "https://api.coingecko.com/api/v3/coins/solana/market_chart"
        "?vs_currency=usd&days=3"
    )
    host = urlparse(url).hostname or ""
    if host not in _CHART_HOSTS:
        raise RuntimeError("CRYPTO_CHART_HOST")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gg-ai-desktop-crypto/1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("prices") if isinstance(payload, dict) else None
    closes, times = _price_rows(rows, 4)
    return closes[-80:], times[-80:]


def _coingecko_sol_closes() -> list[float]:
    return _coingecko_sol_chart()[0]


def _usd_sek_rate() -> float:
    url = "https://api.frankfurter.app/latest?from=USD&to=SEK"
    host = urlparse(url).hostname or ""
    if host not in _CHART_HOSTS:
        raise RuntimeError("CRYPTO_FX_HOST")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gg-ai-desktop-crypto/1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict):
        raise RuntimeError("CRYPTO_FX")
    rate = float(rates.get("SEK") or 0)
    if rate <= 0:
        raise RuntimeError("CRYPTO_FX")
    return round(rate, 4)


def format_usd(value: float) -> str:
    return "$" + f"{max(0.0, float(value)):,.2f}"


def format_sek(value: float) -> str:
    n = int(round(max(0.0, float(value))))
    grouped = f"{n:,}".replace(",", " ")
    return grouped + " kr"


def _sol_float(wallet: dict[str, Any]) -> float:
    raw = str(wallet.get("balance_sol") or "").replace(" ", "").replace(",", "")
    try:
        if raw:
            return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        return int(wallet.get("balance_lamports") or 0) / 1_000_000_000
    except (TypeError, ValueError):
        return 0.0


def quote_for_wallet(wallet: dict[str, Any]) -> dict[str, Any]:
    snap = chart_snapshot()
    try:
        px = float(snap.get("price") or 0)
    except (TypeError, ValueError):
        px = 0.0
    try:
        usd_sek = float(snap.get("usd_sek") or _chart_cache.get("usd_sek") or 0)
    except (TypeError, ValueError):
        usd_sek = 0.0
    sol = _sol_float(wallet)
    usd = sol * px
    sek = usd * usd_sek if usd_sek > 0 else 0.0
    return {
        "sol_usd": px,
        "stale": snap.get("stale", True),
        "age_seconds": snap.get("age_seconds"),
        "valuation_mode": "LOCALNET_SIMULATED" if load_network() == "testnet" else "OBSERVE_MARK_TO_MARKET",
        "usd_sek": usd_sek,
        "sol": sol,
        "value_usd": round(usd, 2),
        "value_sek": round(sek, 0),
        "usd": format_usd(usd) if px > 0 else "",
        "sek": format_sek(sek) if px > 0 and usd_sek > 0 else "",
        "source": str(snap.get("source") or ""),
        "quote_currency": str(snap.get("quote_currency") or "USD"),
        "usd_estimate": snap.get("quote_currency") == "USDT",
    }


def _chart_path():
    from backend.crypto_contract import ensure_state_dir

    return ensure_state_dir() / "sol-chart.json"


def _chart_disk_state(path, cap: int) -> dict[str, Any] | None:
    try:
        payload = read_state_json(path, max_bytes=2 * 1024 * 1024)
        rows = payload.get("closes")
        if not isinstance(rows, list) or len(rows) < 2:
            return None
        rows = rows[-cap:]
        if any(isinstance(item, bool) for item in rows):
            return None
        closes = [float(item) for item in rows]
        if any(not math.isfinite(item) or item <= 0 for item in closes):
            return None
        stamps = payload.get("times")
        stamps = stamps[-cap:] if isinstance(stamps, list) else []
        times = [int(item) for item in stamps] if len(stamps) == len(rows) else []
        if any(isinstance(item, bool) or float(item) != int(item) for item in stamps):
            times = []
        if times and (times[0] <= 0 or any(b <= a for a, b in zip(times, times[1:]))):
            times = []
        fetched_at = float(payload.get("fetched_at") or 0)
        if not times or not math.isfinite(fetched_at) or not 0 < fetched_at <= time.time() + 5:
            fetched_at = 0.0
        usd_sek = float(payload.get("usd_sek") or 0)
        if not math.isfinite(usd_sek) or usd_sek <= 0:
            usd_sek = 0.0
        interval = str(payload.get("interval") or "")
        requested = str(payload.get("requested_interval") or interval or "15m")
        return {"closes": closes, "times": times, "price": str(closes[-1]),
                "source": str(payload.get("source") or "")[:64],
                "interval": interval if interval in _CHART_TFS else "",
                "requested_interval": requested if requested in _CHART_TFS else "15m",
                "fetched_at": fetched_at, "usd_sek": usd_sek, "ts": 0.0, "error": ""}
    except (OSError, ValueError, TypeError, OverflowError, AttributeError):
        return None


def _load_chart_disk() -> None:
    payload = _chart_disk_state(_chart_path(), 5000)
    if payload is not None:
        _chart_cache.update(payload)


def _save_chart_disk() -> None:
    path = _chart_path()
    blob = json.dumps(
        {
            "closes": _chart_cache.get("closes") or [],
            "times": _chart_cache.get("times") or [],
            "price": _chart_cache.get("price") or "",
            "source": _chart_cache.get("source") or "",
            "interval": _chart_cache.get("interval") or "",
            "requested_interval": _chart_cache.get("requested_interval") or _chart_cache.get("interval") or "15m",
            "usd_sek": _chart_cache.get("usd_sek") or 0,
            "fetched_at": _chart_cache.get("fetched_at") or 0,
        },
        separators=(",", ":"),
    )
    write_state_json(path, json.loads(blob))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def chart_snapshot() -> dict[str, Any]:
    if not _chart_cache.get("closes"):
        _load_chart_disk()
    cache = dict(_chart_cache)
    return {
        **crypto_data.freshness(cache, _CHART_TTL),
        "closes": list(cache.get("closes") or []),
        "times": list(cache.get("times") or []),
        "price": str(cache.get("price") or ""),
        "source": str(cache.get("source") or ""),
        "interval": str(cache.get("interval") or ""),
        "requested_interval": chart_interval(),
        "quote_currency": "USDT" if cache.get("source") in ("binance", "gate-spot") else "USD",
        "refreshing": "SOL" in _chart_refresh_running,
        "error": str(cache.get("error") or ""),
        "usd_sek": float(cache.get("usd_sek") or 0),
    }


def _set_live_chart(
    closes: list[float],
    times: list[int],
    source: str,
    interval: str = "15m",
    live: float | None = None,
    fetched_for_interval: str | None = None,
) -> None:
    if len(closes) < 2:
        return
    out = [round(float(item), 4) for item in closes[-5000:]]
    if any(not math.isfinite(price) or price <= 0 for price in out):
        raise RuntimeError("CRYPTO_CHART")
    stamps = [int(item) for item in times[-len(out):]] if times else []
    if stamps and len(stamps) != len(out):
        stamps = []
    if live is not None:
        try:
            px = round(float(live), 4)
            if math.isfinite(px) and px > 0:
                out[-1] = px
        except (TypeError, ValueError):
            pass
    _chart_cache.update(closes=out, times=stamps, price=str(out[-1]), source=source,
                        interval=interval, history_end=False, ts=time.monotonic(),
                        fetched_at=time.time(), error="", fetched_for_interval=fetched_for_interval or interval)
    _save_chart_disk()


def _ingest_spark(
    frames: dict[str, tuple[list[float], list[float], list[float], list[float]]],
    live: float | None = None,
) -> None:
    for tf in (chart_interval(),):
        got = frames.get(tf)
        if got is None or len(got[2]) < 8:
            continue
        closes = [round(float(item), 4) for item in got[2][-80:]]
        stamps = [int(item) for item in (_kline_times.get(tf) or [])[-len(closes):]]
        _set_live_chart(closes, stamps, "binance", interval=tf, live=live)
        return


_CHART_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")


def chart_interval() -> str:
    tf = str(_chart_cache.get("requested_interval") or _chart_cache.get("interval") or "15m")
    if tf not in _CHART_TFS:
        return "15m"
    return tf


def set_chart_interval(interval: str) -> dict[str, Any]:
    """Switch the live SOL tape. Paper chart only. No order."""
    tf = str(interval or "").strip()
    if tf not in _CHART_TFS:
        tf = "15m"
    if not _chart_cache.get("closes"):
        _load_chart_disk()
    with _chart_refresh_lock:
        _chart_cache["requested_interval"] = tf
        _chart_cache["ts"] = 0.0
    request_chart_refresh("SOL")
    return status_payload()


def cached_sol_chart() -> dict[str, Any]:
    now = time.monotonic()
    cached = _chart_cache["closes"]
    stamps = list(_chart_cache.get("times") or [])
    if (
        isinstance(cached, list)
        and cached
        and len(stamps) == len(cached)
        and _chart_cache.get("fetched_for_interval") == chart_interval()
        and now - float(_chart_cache["ts"] or 0) < _CHART_TTL
    ):
        return chart_snapshot()
    if not cached:
        _load_chart_disk()
        cached = _chart_cache["closes"]
    closes: list[float] = []
    times: list[int] = []
    source = ""
    interval = chart_interval()
    requested = interval
    try:
        _highs, _lows, raw, _vols = fetch_klines(interval, 1000, timeout=8.0, closed_only=False)
        closes = [round(float(item), 4) for item in raw[-1000:]]
        times = [int(item) for item in (_kline_times.get(interval) or [])[-len(closes):]]
        source = "binance"
    except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        try:
            _highs, _lows, raw, _vols = fetch_klines("15m", 80, timeout=3.0)
            closes = [round(float(item), 4) for item in raw[-80:]]
            times = [int(item) for item in (_kline_times.get("15m") or [])[-len(closes):]]
            source = "binance"
            interval = "15m"
        except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            try:
                closes, times = _coingecko_sol_chart()
                source = "coingecko"
                interval = _source_chart_interval(times)
            except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
                _chart_cache["error"] = "NO_MARKET_DATA"
                return chart_snapshot()
    if closes:
        with _chart_refresh_lock:
            if chart_interval() != requested:
                return chart_snapshot()
            _set_live_chart(closes, times, source, interval=interval, fetched_for_interval=requested)
        try:
            rate = _usd_sek_rate()
            if rate > 0:
                _chart_cache["usd_sek"] = rate
        except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            pass
        _save_chart_disk()
    return chart_snapshot()


_chart_refresh_lock = threading.RLock()
_chart_refresh_running: set[str] = set()
_chart_refresh_pending: set[str] = set()
_chart_refresh_tokens: dict[str, object] = {}


def request_chart_refresh(asset: str = "SOL") -> None:
    """One worker per asset; UI refresh never blocks on public market requests."""
    asset = "KAS" if asset == "KAS" else "SOL"
    with _chart_refresh_lock:
        if asset in _chart_refresh_running:
            _chart_refresh_pending.add(asset)
            return
        _chart_refresh_running.add(asset)
        token = object()
        _chart_refresh_tokens[asset] = token
    def run():
        try:
            while True:
                (cached_kas_chart if asset == "KAS" else cached_sol_chart)()
                with _chart_refresh_lock:
                    if asset not in _chart_refresh_pending:
                        _chart_refresh_running.discard(asset)
                        _chart_refresh_tokens.pop(asset, None)
                        return
                    _chart_refresh_pending.discard(asset)
        finally:
            with _chart_refresh_lock:
                if _chart_refresh_tokens.get(asset) is token:
                    _chart_refresh_running.discard(asset)
                    _chart_refresh_pending.discard(asset)
                    _chart_refresh_tokens.pop(asset, None)
    try:
        threading.Thread(target=run, name="crypto-chart-" + asset, daemon=True).start()
    except Exception:
        with _chart_refresh_lock:
            if _chart_refresh_tokens.get(asset) is token:
                _chart_refresh_running.discard(asset)
                _chart_refresh_pending.discard(asset)
                _chart_refresh_tokens.pop(asset, None)
        raise RuntimeError("CRYPTO_CHART_WORKER_START") from None


def _merge_bars(
    old_closes: list[float],
    old_times: list[int],
    new_closes: list[float],
    new_times: list[int],
    cap: int = 5000,
) -> tuple[list[float], list[int]]:
    by_time: dict[int, float] = {}
    order: list[int] = []
    for stamp, price in zip(old_times, old_closes):
        try:
            key = int(stamp)
            value = float(price)
        except (TypeError, ValueError):
            continue
        if key not in by_time:
            order.append(key)
        by_time[key] = value
    for stamp, price in zip(new_times, new_closes):
        try:
            key = int(stamp)
            value = float(price)
        except (TypeError, ValueError):
            continue
        if key not in by_time:
            order.append(key)
        by_time[key] = value
    order.sort()
    if len(order) > cap:
        order = order[-cap:]
    return [by_time[key] for key in order], order


def extend_sol_chart() -> dict[str, Any]:
    """Page Binance backward from the oldest loaded SOL bar. No order."""
    times = [int(item) for item in (_chart_cache.get("times") or [])]
    closes = [float(item) for item in (_chart_cache.get("closes") or [])]
    if len(times) < 2 or len(times) != len(closes) or _chart_cache.get("history_end"):
        return status_payload()
    interval = chart_interval()
    if interval not in _CHART_TFS:
        return status_payload()
    end_ms = int(times[0]) * 1000 - 1
    try:
        _highs, _lows, raw, _vols = fetch_klines(
            interval, 1000, timeout=8.0, end_time=end_ms
        )
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        return status_payload()
    page_times = [int(item) for item in (_kline_times.get(interval) or [])]
    older_closes: list[float] = []
    older_times: list[int] = []
    first = times[0]
    for price, stamp in zip(raw, page_times):
        if stamp < first:
            older_closes.append(float(price))
            older_times.append(stamp)
    if not older_times:
        _chart_cache["history_end"] = True
        return status_payload()
    merged_closes, merged_times = _merge_bars(closes, times, older_closes, older_times)
    _chart_cache["closes"] = [round(float(item), 4) for item in merged_closes]
    _chart_cache["times"] = merged_times
    _chart_cache["history_end"] = False
    _save_chart_disk()
    return status_payload()


def _kas_chart_path():
    from backend.crypto_contract import ensure_state_dir

    return ensure_state_dir() / "kas-chart.json"


def _portfolio_path():
    from backend.crypto_contract import ensure_state_dir

    return ensure_state_dir() / "portfolio.json"


def portfolio_asset() -> str:
    path = _portfolio_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return "SOL"
    if not isinstance(payload, dict):
        return "SOL"
    token = str(payload.get("asset") or "").upper()
    if token in ("KAS", "KASPA"):
        return "KAS"
    return "SOL"


def _kas_px(value: float) -> float:
    number = float(value)
    if number >= 100:
        return round(number, 2)
    if number >= 1:
        return round(number, 4)
    return round(number, 6)


def kas_chart_snapshot() -> dict[str, Any]:
    if not _kas_chart_cache.get("closes"):
        _load_kas_chart_disk()
    cache = dict(_kas_chart_cache)
    return {
        **crypto_data.freshness(cache, _CHART_TTL),
        "symbol": "KASUSDT",
        "closes": list(cache.get("closes") or []),
        "times": list(cache.get("times") or []),
        "price": str(cache.get("price") or ""),
        "source": str(cache.get("source") or ""),
        "interval": str(cache.get("interval") or ""),
        "requested_interval": str(cache.get("requested_interval") or cache.get("interval") or "15m"),
        "quote_currency": "USDT" if cache.get("source") in ("binance", "gate-spot") else "USD",
        "refreshing": "KAS" in _chart_refresh_running,
        "error": str(cache.get("error") or ""),
    }


def _load_kas_chart_disk() -> None:
    payload = _chart_disk_state(_kas_chart_path(), 2000)
    if payload is not None:
        _kas_chart_cache.update(payload)


def _save_kas_chart_disk() -> None:
    path = _kas_chart_path()
    blob = json.dumps(
        {
            "closes": _kas_chart_cache.get("closes") or [],
            "times": _kas_chart_cache.get("times") or [],
            "price": _kas_chart_cache.get("price") or "",
            "source": _kas_chart_cache.get("source") or "",
            "interval": _kas_chart_cache.get("interval") or "",
            "requested_interval": _kas_chart_cache.get("requested_interval") or _kas_chart_cache.get("interval") or "15m",
            "fetched_at": _kas_chart_cache.get("fetched_at") or 0,
        },
        separators=(",", ":"),
    )
    write_state_json(path, json.loads(blob))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _set_kas_chart(
    closes: list[float],
    times: list[int],
    source: str,
    interval: str = "15m",
    fetched_for_interval: str | None = None,
) -> None:
    if len(closes) < 2:
        return
    out = [_kas_px(item) for item in closes[-2000:]]
    if any(not math.isfinite(price) or price <= 0 for price in out):
        raise RuntimeError("CRYPTO_CHART")
    stamps = [int(item) for item in times[-len(out):]] if times else []
    if stamps and len(stamps) != len(out):
        stamps = []
    _kas_chart_cache.update(closes=out, times=stamps, price=str(out[-1]), source=source,
                            interval=interval, error="", ts=time.monotonic(), fetched_at=time.time(),
                            fetched_for_interval=fetched_for_interval or interval)
    _save_kas_chart_disk()


def _bucket_closes(
    closes: list[float],
    times: list[int],
    step: int,
) -> tuple[list[float], list[int]]:
    """Last price inside each step. Stamps stay real seconds."""
    if step <= 0 or len(closes) < 2:
        return closes[-2000:], times[-2000:]
    order: list[int] = []
    last: dict[int, float] = {}
    for stamp, price in zip(times, closes):
        key = int(stamp) - (int(stamp) % int(step))
        if key not in last:
            order.append(key)
        last[key] = float(price)
    if len(order) < 2:
        return closes[-2000:], times[-2000:]
    kept = order[-2000:]
    return [last[key] for key in kept], kept


def _coingecko_kas_chart(interval: str = "15m") -> tuple[list[float], list[int], str]:
    """Kaspa is not on Binance spot. CoinGecko is the allowlisted tape.

    Their public chart is about 5 minutes on a 1-day window, hourly out to
    90 days, and daily after that. 1m therefore lands on the 5m tape.
    """
    spec = {
        "1m": ("1", 300, "5m"),
        "5m": ("1", 300, "5m"),
        "15m": ("1", 900, "15m"),
        "1h": ("90", 3600, "1h"),
        "4h": ("90", 14400, "4h"),
        "1d": ("365", 86400, "1d"),
    }
    days, step, actual = spec.get(str(interval), ("1", 900, "15m"))
    url = (
        "https://api.coingecko.com/api/v3/coins/kaspa/market_chart"
        "?vs_currency=usd&days=" + days
    )
    host = urlparse(url).hostname or ""
    if host not in _CHART_HOSTS:
        raise RuntimeError("CRYPTO_CHART_HOST")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "gg-ai-desktop-crypto/1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=4.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("prices") if isinstance(payload, dict) else None
    closes, times = _price_rows(rows, 8)
    deltas = sorted(b-a for a, b in zip(times, times[1:]) if b > a)
    observed = deltas[len(deltas)//2] if deltas else step
    if observed > step * 1.5:
        # Coarse source data cannot be promoted to a finer requested interval.
        actual = next((tf for tf in ("5m", "15m", "1h", "4h", "1d")
                       if crypto_data.BAR_SECONDS[tf] >= observed * .9), "1d")
        step = max(step, crypto_data.BAR_SECONDS[actual])
    bucketed, stamps = _bucket_closes(closes, times, step)
    if len(bucketed) < 8:
        raise RuntimeError("CRYPTO_CHART")
    return bucketed, stamps, actual


def cached_kas_chart() -> dict[str, Any]:
    """Public KAS/USD tape. Same hosts as SOL. No order, no Kaspa RPC."""
    now = time.monotonic()
    cached = _kas_chart_cache.get("closes")
    stamps = list(_kas_chart_cache.get("times") or [])
    if (
        isinstance(cached, list)
        and len(cached) > 1
        and len(stamps) == len(cached)
        and _kas_chart_cache.get("fetched_for_interval") == str(_kas_chart_cache.get("requested_interval") or _kas_chart_cache.get("interval") or "15m")
        and now - float(_kas_chart_cache.get("ts") or 0) < _CHART_TTL
    ):
        return kas_chart_snapshot()
    if not cached:
        _load_kas_chart_disk()
        cached = _kas_chart_cache.get("closes")
    closes: list[float] = []
    times: list[int] = []
    source = ""
    interval = str(_kas_chart_cache.get("requested_interval") or _kas_chart_cache.get("interval") or "15m")
    if interval not in _CHART_TFS:
        interval = "15m"
    requested = interval
    fetched_at = None
    try:
        frame = crypto_market.recent("KASUSDT", interval)
        closes = [_kas_px(item) for item in frame["closes"]]
        times = list(frame["times"])
        source = str(frame["source"])
        fetched_at = frame.get("fetched_at")
    except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        try:
            closes, times, interval = _coingecko_kas_chart(interval)
            source = "coingecko"
        except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            _kas_chart_cache["error"] = "NO_MARKET_DATA"
            return kas_chart_snapshot()
    if len(closes) > 1:
        with _chart_refresh_lock:
            current = str(_kas_chart_cache.get("requested_interval") or _kas_chart_cache.get("interval") or "15m")
            if current != requested:
                return kas_chart_snapshot()
            _set_kas_chart(closes, times, source, interval=interval, fetched_for_interval=requested)
            if fetched_at:
                _kas_chart_cache["fetched_at"] = fetched_at
                _save_kas_chart_disk()
    else:
        _kas_chart_cache["error"] = "NO_MARKET_DATA"
    return kas_chart_snapshot()


def extend_kas_chart() -> dict[str, Any]:
    """The loaded CoinGecko window is the whole public tape at this bar size."""
    _kas_chart_cache["history_end"] = True
    return status_payload()


def set_kas_chart_interval(interval: str) -> dict[str, Any]:
    """Switch the KAS tape. Public price only. No order."""
    tf = str(interval or "").strip()
    if tf not in _CHART_TFS:
        tf = "15m"
    if not _kas_chart_cache.get("closes"):
        _load_kas_chart_disk()
    with _chart_refresh_lock:
        _kas_chart_cache["requested_interval"] = tf
        _kas_chart_cache["history_end"] = False
        _kas_chart_cache["ts"] = 0.0
    request_chart_refresh("KAS")
    return status_payload()


def set_portfolio_asset(asset: str) -> dict[str, Any]:
    """One portfolio. SOL and KAS are wallets on it, not separate pages."""
    chosen = "KAS" if str(asset or "").strip().upper() in ("KAS", "KASPA") else "SOL"
    path = _portfolio_path()
    write_state_json(path, {"asset": chosen})
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if chosen == "KAS":
        try:
            cached_kas_chart()
        except (OSError, RuntimeError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            _kas_chart_cache["error"] = "NO_MARKET_DATA"
    return status_payload()


def _ohlcv_from_closes(closes: list[float]) -> tuple[list[float], list[float], list[float], list[float]]:
    raise RuntimeError("NO_MARKET_DATA")


def _ohlcv_for_eval() -> tuple[list[float], list[float], list[float], list[float]]:
    try:
        return fetch_sol_ohlcv()
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        snap = chart_snapshot()
        raw = snap.get("closes") or []
        closes: list[float] = []
        for item in raw:
            try:
                closes.append(float(item))
            except (TypeError, ValueError):
                continue
        return _ohlcv_from_closes(closes)


def evaluate_signals(
    ohlcv: tuple[list[float], list[float], list[float], list[float]] | None = None
) -> dict[str, Any]:
    closes: list[float] = []
    try:
        if ohlcv is None:
            highs, lows, closes, volumes = _ohlcv_for_eval()
        else:
            highs, lows, closes, volumes = ohlcv
        report = crypto_strategy004.evaluate(highs, lows, closes, volumes)
        mark_proven("bot")
    except Exception as exc:
        token = short_error(str(exc)[:120]) or "NO_MARKET_DATA"
        if "KLINE" in str(exc) or "CANDLES" in str(exc) or "CHART" in str(exc):
            token = "NO_MARKET_DATA"
        report = {
            "strategy": "Strategy004",
            "super": "none",
            "buy_votes": 0,
            "sell_votes": 0,
            "notes": [human_error(token)],
            "error": token,
        }
    bot = load_bot()
    bot["last"] = report
    if closes:
        bot["closes"] = [round(float(item), 4) for item in closes[-80:]]
    save_bot(bot)
    report["armed"] = bot["armed"]
    return report


def set_bot_armed(armed: bool) -> dict[str, Any]:
    bot = load_bot()
    bot["armed"] = bool(armed)
    save_bot(bot)
    payload = status_payload()
    payload["bot"] = load_bot()
    return payload


def tick_bot() -> dict[str, Any]:
    bot = load_bot()
    report = evaluate_signals()
    bot = load_bot()
    fired = None
    if (
        bot["armed"]
        and report.get("super") in ("buy", "sell")
        and not report.get("error")
    ):
        fired = ingest_paper_signal(
            json.dumps(
                {
                    "side": report["super"],
                    "size_sol": bot["size_sol"],
                    "symbol": "SOL",
                    "source": "strategy004",
                }
            )
        )
    payload = status_payload()
    payload["signal"] = report
    payload["fired"] = fired
    payload["bot"] = load_bot()
    return payload


def set_trader_armed(armed: bool) -> dict[str, Any]:
    if armed and load_network() != "testnet":
        raise RuntimeError("MAINNET_OBSERVE_ONLY")
    crypto_paper.set_enabled(paper_pair(), crypto_bots.selected(), bool(armed))
    return status_payload()


def set_paper_all(enabled: bool) -> dict[str, Any]:
    if enabled and load_network() != "testnet":
        raise RuntimeError("MAINNET_OBSERVE_ONLY")
    crypto_paper.set_all(paper_pair(), bool(enabled))
    return status_payload()


def reset_trader() -> dict[str, Any]:
    crypto_paper.reset(paper_pair(), crypto_bots.selected())
    crypto_trader.reset_book()
    return status_payload()


def set_trader_book(book_id: str) -> dict[str, Any]:
    crypto_bots.set_book(book_id)
    return status_payload()


def _trader_ohlcv() -> tuple[list[float], list[float], list[float], list[float]]:
    try:
        return fetch_klines("5m", 200, timeout=8.0)
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        return _ohlcv_for_eval()


def _fetch_tf(interval: str, limit: int = 240) -> tuple[list[float], list[float], list[float], list[float]] | None:
    try:
        return fetch_klines(interval, limit, timeout=6.0)
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        return None


def tick_trader() -> dict[str, Any]:
    # Public market data only. This engine has no signer, RPC writes or orders.
    if load_network() != "testnet":
        for pair in crypto_paper.active_pairs():
            crypto_paper.set_all(pair, False)
        payload = status_payload()
        payload["error"] = "MAINNET_OBSERVE_ONLY"
        return payload
    errors = []
    for pair in crypto_paper.active_pairs():
        try:
            if crypto_paper.due(pair):
                crypto_paper.advance(pair, crypto_market.recent_frames(pair))
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)[:160]
            crypto_paper.data_error(pair, reason)
            errors.append(pair + ": " + reason)
    payload = status_payload()
    if errors:
        payload["error"] = "; ".join(errors)
    return payload


_paper_tick_lock = threading.RLock()
_paper_tick_jobs: dict[str, dict[str, Any]] = {}


def paper_tick_status() -> dict[str, Any]:
    with _paper_tick_lock:
        return {key: dict(value) for key, value in _paper_tick_jobs.items()}


def start_paper_tick(kind: str = "trader") -> dict[str, Any]:
    """One tick per engine at a time; network waits stay outside Qt's thread."""
    if kind not in ("trader", "bot"):
        raise ValueError("CRYPTO_TICK_KIND")
    with _paper_tick_lock:
        if (_paper_tick_jobs.get(kind) or {}).get("state") == "running":
            return status_payload()
        _paper_tick_jobs[kind] = {"state": "running", "note": "Fetching closed market bars…"}
    def run():
        try:
            result = (tick_trader if kind == "trader" else tick_bot)()
            error = result.get("error") or (result.get("signal") or {}).get("error")
            job = {"state": "error" if error else "done", "note": str(error or "Paper tick complete.")}
        except Exception as exc:
            job = {"state": "error", "note": short_error(str(exc)[:160])}
        with _paper_tick_lock:
            _paper_tick_jobs[kind] = job
    _launch_job_thread(run, "crypto-paper-" + kind, _paper_tick_lock, _paper_tick_jobs[kind])
    return status_payload()


_backtest_lock = threading.Lock()
_backtest_job: dict[str, Any] = {
    "state": "idle",
    "note": "",
    "started": 0.0,
}
_UI_BACKTEST_TF = crypto_market.TIMEFRAMES


def backtest_job() -> dict[str, Any]:
    with _backtest_lock:
        return dict(_backtest_job)


def start_backtest_trader() -> dict[str, Any]:
    launch = False
    with _backtest_lock:
        already = str(_backtest_job.get("state") or "") == "running"
        if not already:
            _backtest_job["state"] = "running"
            _backtest_job["note"] = (
                crypto_bots.selected() + " · 1h clock, last 4000 bars, off UI thread"
            )
            _backtest_job["started"] = time.time()
            launch = True
    if launch:
        _launch_job_thread(_run_backtest_job, "gg-crypto-backtest", _backtest_lock,
                           _backtest_job, args=(paper_pair(), crypto_bots.selected()))
    payload = status_payload()
    payload["backtest_job"] = backtest_job()
    return payload


def _run_backtest_job(pair: str | None = None, chosen: str | None = None) -> None:
    try:
        backtest_trader(tfs=_UI_BACKTEST_TF, pair=pair, chosen=chosen)
        with _backtest_lock:
            _backtest_job["state"] = "done"
            _backtest_job["note"] = ""
    except Exception as exc:
        token = short_error(str(exc)[:120]) or "NO_MARKET_DATA"
        with _backtest_lock:
            _backtest_job["state"] = "error"
            _backtest_job["note"] = human_error(token)


def backtest_trader(tfs: tuple[str, ...] | None = None, *, pair: str | None = None,
                    chosen: str | None = None) -> dict[str, Any]:
    pair = pair or paper_pair()
    chosen = chosen or crypto_bots.selected()
    # Extra slow-TF history; real 15m bars supply the second fast confirmation.
    start = int(time.time() - (4000 + 2400) * 3600)
    frames = {tf: crypto_market.history(pair, tf, start) for tf in crypto_market.TIMEFRAMES}
    report = crypto_bots.compare_books(frames, book_id=chosen)
    payload = status_payload()
    payload["backtest"] = report
    trader = dict(payload.get("trader") or {})
    trader.update({"backtest": report, "books": crypto_bots.catalog(), "book": crypto_bots.selected()})
    payload["trader"] = trader
    return payload
