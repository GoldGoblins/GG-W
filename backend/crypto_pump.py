"""Read-only Pump research with one bounded asynchronous account lane.

Public RPC data is decoded independently from pinned official interfaces.
No key files, signatures, transaction submission or program execution occur.
All UI reads return prepared data; only explicit selection enables refresh.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
from typing import Any, Callable

from backend import crypto_pump_accounts as accounts
from backend import crypto_pump_quotes as quotes
from backend import crypto_contract

REFRESH_SECONDS = 20.0
STALE_SECONDS = 45.0
MAX_ACCOUNTS = 24
MAX_HISTORY = 128
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"


def _error(exc: BaseException) -> str:
    value = str(exc)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", value) else "PUMP_ACCOUNT_UNSUPPORTED" if isinstance(exc, accounts.AccountDecodeError) else type(exc).__name__


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    return value


def units(value: int | str, decimals: int) -> str:
    value = int(value)
    if not 0 <= decimals <= 38:
        raise ValueError("PUMP_DECIMALS_UNSUPPORTED")
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 10**decimals)
    tail = f"{fraction:0{decimals}d}".rstrip("0") if decimals else ""
    return sign + str(whole) + ("." + tail if tail else "")


def parse_amount(text: str, decimals: int) -> int:
    if not isinstance(text, str) or len(text) > 80 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", text.strip()):
        raise ValueError("PUMP_AMOUNT_INVALID")
    if not 0 <= decimals <= 38:
        raise ValueError("PUMP_DECIMALS_UNSUPPORTED")
    whole, _, fraction = text.strip().partition(".")
    if len(fraction) > decimals:
        raise ValueError("PUMP_AMOUNT_PRECISION")
    value = int(whole) * 10**decimals + int((fraction + "0" * decimals)[:decimals] or "0")
    if not 0 < value <= 2**64 - 1:
        raise ValueError("PUMP_AMOUNT_RANGE")
    return value


def _fee_transfer(mint: dict) -> dict | None:
    fee = mint.get("transfer_fee")
    if fee is None:
        return None
    return {"bps": fee["transfer_fee_basis_points"], "max_fee": fee["maximum_fee"]}


def initial() -> dict:
    return {"state": "idle", "loading": False, "network": "mainnet", "mode": "OBSERVE",
            "mint": "", "pool": "", "slot": 0, "fetched_at": 0, "stale": True,
        "error": "", "warnings": [], "token": {}, "market": {}, "risks": [], "stress": {},
            "quote": {}, "simulation": {}, "paper": {}, "source": accounts.PROTOCOL_SOURCE}


class PumpResearch:
    def __init__(self, rpc: Callable, *, clock=time.time):
        self._rpc = rpc
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False
        self._running = False
        self._pending = None
        self._generation = 0
        self._last_attempt = 0.0
        self._state = initial()
        self._market: dict = {}
        self._raw_context: dict = {}
        self._quote: dict = {}
        self._quote_generation = -1
        self._quote_revision = 0
        self._history: list[dict] = []
        self._paper = None
        self._paper_error = ""
        self._paper_loaded = False

    def _call(self, method, params):
        if self._closed:
            raise RuntimeError("PUMP_CLOSED")
        reply = self._rpc(method, params, "mainnet")
        if not isinstance(reply, dict) or reply.get("error") or "result" not in reply:
            raise RuntimeError("PUMP_RPC_UNAVAILABLE")
        return reply["result"]

    def _batch(self, keys, minimum=0):
        keys = list(dict.fromkeys(keys))
        if not 1 <= len(keys) <= MAX_ACCOUNTS:
            raise ValueError("PUMP_ACCOUNT_BUDGET")
        for key in keys:
            accounts.pubkey_bytes(key)
        opts = {"encoding": "base64", "commitment": "confirmed"}
        if minimum:
            opts["minContextSlot"] = minimum
        result = self._call("getMultipleAccounts", [keys, opts])
        if not isinstance(result, dict) or not isinstance(result.get("value"), list) or len(result["value"]) != len(keys):
            raise RuntimeError("PUMP_RPC_ACCOUNT_SHAPE")
        slot = (result.get("context") or {}).get("slot")
        if type(slot) is not int or slot < minimum:
            raise RuntimeError("PUMP_RPC_SLOT")
        return dict(zip(keys, result["value"])), slot

    def inspect(self, mint: str, pool: str = "") -> dict:
        try:
            mint, pool = str(mint).strip(), str(pool or "").strip()
            accounts.pubkey_bytes(mint)
            if pool:
                accounts.pubkey_bytes(pool)
        except (ValueError, TypeError):
            with self._lock:
                self._generation += 1
                self._quote_revision += 1
                self._pending = None
                self._market, self._raw_context, self._quote = {}, {}, {}
                self._state.update(initial(), state="error", error="PUMP_MINT_INVALID")
            return self.snapshot(refresh=False)
        self._enqueue(mint, pool)
        return self.snapshot(refresh=False)

    def _enqueue(self, mint: str, pool: str, *, expected_generation=None):
        launch = False
        with self._lock:
            if self._closed or expected_generation is not None and expected_generation != self._generation:
                return
            self._generation += 1
            self._quote_revision += 1
            self._pending = (self._generation, mint, pool)
            self._state.update(state="loading", loading=True, mint=mint, pool=pool, error="", stale=True,
                               token={}, market={}, risks=[], quote={}, simulation={}, stress={})
            self._market, self._raw_context, self._quote = {}, {}, {}
            if not self._running:
                self._running, launch = True, True
                self._last_attempt = self._clock()
        if launch:
            try:
                threading.Thread(target=self._run, name="gg-pump-research", daemon=True).start()
            except Exception:
                with self._lock:
                    self._running = False
                    self._pending = None
                    self._state.update(state="error", loading=False, error="PUMP_WORKER_START")

    def heartbeat(self):
        """Cheap desktop-owned scheduling, independent of Qt paint/focus."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            now = self._clock()
            if (self._closed or self._running or not self._state["mint"]
                    or now - self._last_attempt <= REFRESH_SECONDS
                    or self._quote and now - self._state["fetched_at"] <= STALE_SECONDS):
                return
            generation, mint, pool = self._generation, self._state["mint"], self._state["pool"]
            self._enqueue(mint, pool, expected_generation=generation)
        finally:
            self._lock.release()

    def refresh(self) -> dict:
        with self._lock:
            mint, pool = self._state["mint"], self._state["pool"]
        return self.inspect(mint, pool) if mint else self.snapshot(refresh=False)

    def snapshot(self, *, refresh=True) -> dict:
        with self._lock:
            out = deepcopy(self._state)
            out["fetched_at_text"] = datetime.fromtimestamp(out["fetched_at"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if out["fetched_at"] else "—"
            out["stale"] = out["state"] != "ready" or not out["fetched_at"] or self._clock() - out["fetched_at"] > STALE_SECONDS
            due = bool(refresh and out["mint"] and not self._running and not self._closed
                       and self._clock() - self._last_attempt > REFRESH_SECONDS
                       and (not self._quote or out["stale"]))
        if due:
            # Called only by the existing background status lane; schedules a
            # single network worker and never waits for the network here.
            self.refresh()
            return self.snapshot(refresh=False)
        with self._lock:
            out["history"] = deepcopy(self._history[-32:])
        out["paper"] = self.paper_snapshot()
        return _safe(out)

    def _run(self):
        while True:
            with self._lock:
                request, self._pending = self._pending, None
                if self._closed or request is None:
                    self._running = False
                    return
                self._last_attempt = self._clock()
            generation, mint, pool = request
            try:
                state, market, context = self._fetch(mint, pool)
                error = ""
            except Exception as exc:
                state, market, context, error = None, {}, {}, _error(exc)
            with self._lock:
                if self._closed:
                    self._running = False
                    return
                if generation == self._generation:
                    if state is not None:
                        self._state.update(state, state="ready", loading=False, error="")
                        self._market, self._raw_context = market, context
                    else:
                        self._state.update(state="error", loading=False, error=error, stale=True)
                if self._pending is None:
                    self._running = False
                    return

    def _fetch(self, mint, pool):
        curve_address = accounts.derive_curve(mint)
        first, slot = self._batch([mint, curve_address] + ([pool] if pool else []))
        curve = accounts.decode_curve(first[curve_address]) if first[curve_address] else None
        if not pool and curve and not curve["complete"]:
            kind, market_address = "curve", curve_address
            quote_mint = curve["quote_mint"]
        else:
            kind = "amm"
            market_address = pool or accounts.derive_pool(mint, curve["quote_mint"] if curve else accounts.WSOL_MINT)
            candidate = first.get(market_address)
            if candidate is None:
                discovered, slot = self._batch([market_address], slot)
                candidate = discovered[market_address]
            if candidate is None:
                raise ValueError("PUMP_POOL_NOT_FOUND")
            parsed_pool = accounts.decode_pool(candidate)
            if parsed_pool["base_mint"] != mint:
                raise ValueError("PUMP_POOL_MINT_MISMATCH")
            quote_mint = parsed_pool["quote_mint"]
        program = accounts.PUMP_PROGRAM if kind == "curve" else accounts.PUMP_AMM_PROGRAM
        global_address = accounts.derive_global(kind)
        fee_address = accounts.derive_fee_config(program)
        base_owner = (first.get(mint) or {}).get("owner")
        if base_owner not in (accounts.TOKEN_PROGRAM, accounts.TOKEN_2022_PROGRAM):
            raise ValueError("PUMP_MINT_OWNER")
        if kind == "curve":
            base_vault = accounts.derive_ata(market_address, mint, base_owner)
            quote_vault = accounts.derive_ata(market_address, quote_mint)
        else:
            base_vault, quote_vault = parsed_pool["pool_base_token_account"], parsed_pool["pool_quote_token_account"]
        keys = [mint, market_address, quote_mint, base_vault, quote_vault, global_address, fee_address, program]
        raw, slot = self._batch(keys, slot)
        epoch_result = self._call("getEpochInfo", [{"commitment": "confirmed", "minContextSlot": slot}])
        epoch = epoch_result.get("epoch") if isinstance(epoch_result, dict) else None
        if type(epoch) is not int or epoch < 0:
            raise RuntimeError("PUMP_RPC_EPOCH")
        token = accounts.decode_mint(raw[mint], epoch=epoch)
        quote_token = accounts.decode_mint(raw[quote_mint], epoch=epoch)
        configuration = accounts.decode_global(raw[global_address], kind=kind)
        fee_config = accounts.decode_fee_config(raw[fee_address]) if raw[fee_address] else None
        market_data = accounts.decode_curve(raw[market_address]) if kind == "curve" else accounts.decode_pool(raw[market_address])
        if kind == "curve" and market_data["quote_mint"] != quote_mint or kind == "amm" and (market_data["base_mint"] != mint or market_data["quote_mint"] != quote_mint or market_data["pool_base_token_account"] != base_vault or market_data["pool_quote_token_account"] != quote_vault):
            raise RuntimeError("PUMP_MARKET_CHANGED_RETRY")
        base_account = accounts.decode_token_account(raw[base_vault])
        if base_account["mint"] != mint or base_account["owner"] != market_address or base_account["token_program"] != token["token_program"] or base_account["state"] != 1:
            raise ValueError("PUMP_BASE_VAULT_MISMATCH")
        if base_vault != accounts.derive_ata(market_address, mint, token["token_program"]):
            raise ValueError("PUMP_BASE_VAULT_ADDRESS")
        if kind == "curve" and market_data["real_quote_reserves"] > raw[market_address].get("lamports", 0) and quote_mint == accounts.WSOL_MINT:
            raise ValueError("PUMP_CURVE_RESERVE_BALANCE")
        if kind == "amm" and market_address != accounts.derive_pool(mint, quote_mint, creator=market_data["creator"], index=market_data["index"]):
            raise ValueError("PUMP_POOL_ADDRESS")
        quote_account = None
        if kind == "amm" or quote_mint != accounts.WSOL_MINT:
            quote_account = accounts.decode_token_account(raw[quote_vault])
            if quote_account["mint"] != quote_mint or quote_account["owner"] != market_address or quote_account["token_program"] != quote_token["token_program"] or quote_account["state"] != 1:
                raise ValueError("PUMP_QUOTE_VAULT_MISMATCH")
            if quote_vault != accounts.derive_ata(market_address, quote_mint, quote_token["token_program"]):
                raise ValueError("PUMP_QUOTE_VAULT_ADDRESS")
        program_account = raw.get(program)
        if not isinstance(program_account, dict) or program_account.get("executable") is not True or program_account.get("owner") != LOADER:
            raise ValueError("PUMP_PROGRAM_IDENTITY")
        data = program_account.get("data") or []
        try:
            header = base64.b64decode(data[0], validate=True)
        except Exception:
            raise ValueError("PUMP_PROGRAM_IDENTITY") from None
        if len(header) != 36 or int.from_bytes(header[:4], "little") != 2:
            raise ValueError("PUMP_PROGRAM_IDENTITY")
        program_data_address = accounts.b58encode(header[4:36])
        # Fetch loader metadata only, never the multi-megabyte executable.
        metadata = self._call("getAccountInfo", [program_data_address, {"encoding": "base64", "commitment": "confirmed", "minContextSlot": slot, "dataSlice": {"offset": 0, "length": 45}}])
        loader = metadata.get("value") if isinstance(metadata, dict) else None
        try:
            loader_header = base64.b64decode(loader["data"][0], validate=True)
        except Exception:
            raise ValueError("PUMP_PROGRAM_METADATA") from None
        metadata_slot = (metadata.get("context") or {}).get("slot")
        if (loader.get("owner") != LOADER or loader.get("executable") is not False
                or loader.get("data", [None, None])[1] != "base64"
                or len(loader_header) != 45 or int.from_bytes(loader_header[:4], "little") != 3
                or loader_header[12] not in (0, 1) or type(metadata_slot) is not int or metadata_slot < slot):
            raise ValueError("PUMP_PROGRAM_METADATA")
        deployment_slot = int.from_bytes(loader_header[4:12], "little")
        if deployment_slot > metadata_slot:
            raise ValueError("PUMP_PROGRAM_METADATA")
        if deployment_slot > slot:
            raise ValueError("PUMP_PROGRAM_CHANGED_RETRY")
        symbol = "SOL" if quote_mint == accounts.WSOL_MINT else "USDC" if quote_mint == accounts.USDC_MINT else "QUOTE"
        market = {"kind": kind, "mint": mint, "base_mint": mint, "quote_mint": quote_mint,
            "base_decimals": token["decimals"], "quote_decimals": quote_token["decimals"],
            "mint_supply_atoms": token["supply"], "epoch": epoch,
            "base_reserves_atoms": market_data["virtual_token_reserves"] if kind == "curve" else base_account["amount"],
            "quote_reserves_atoms": market_data["virtual_quote_reserves"] if kind == "curve" else quote_account["amount"],
            "real_base_reserves_atoms": min(market_data["real_token_reserves"], base_account["amount"]) if kind == "curve" else base_account["amount"],
            "real_quote_reserves_atoms": market_data["real_quote_reserves"] if kind == "curve" else quote_account["amount"],
            "virtual_quote_reserves_atoms": 0 if kind == "curve" else market_data["virtual_quote_reserves"],
            "protocol_fees_atoms": 0 if kind == "curve" else market_data["protocol_fees"],
            "creator_fees_atoms": 0 if kind == "curve" else market_data["creator_fees"],
            "protocol_fee_bps": configuration.get("fee_basis_points", configuration.get("protocol_fee_basis_points", 0)),
            "creator_fee_bps": configuration.get("creator_fee_basis_points", configuration.get("coin_creator_fee_basis_points", 0)),
            "lp_fee_bps": configuration.get("lp_fee_basis_points", 0), "fee_config": fee_config,
            "base_transfer_fee": _fee_transfer(token), "quote_transfer_fee": _fee_transfer(quote_token),
            "is_pump_pool": market_data.get("is_pump_pool", True),
            "creator_present": market_data.get("creator" if kind == "curve" else "coin_creator") != accounts.ZERO_KEY,
            "creator_fee_configurable": configuration.get("creator_fee_configurable", False),
            "configured_creator_fee_bps": market_data.get("creator_fee_bps", 0),
            "complete": market_data.get("complete", False), "mayhem": market_data.get("is_mayhem_mode", False),
            "cashback": market_data.get("is_cashback_coin", False),
            "trade_v2": kind == "amm", "buyback_bps": configuration.get("buyback_basis_points", 0),
            "instruction_version": 2, "quote_symbol": symbol, "address": market_address,
            "market_id": market_address, "timestamp_ms": int(self._clock() * 1000)}
        warnings = list(dict.fromkeys(token["warnings"] + quote_token["warnings"] + market_data["warnings"]
                                      + base_account["warnings"] + (quote_account or {}).get("warnings", [])))
        unsupported = []
        if not token["quote_supported"] or not quote_token["quote_supported"]:
            unsupported.append("PUMP_TOKEN_EXTENSION_UNSUPPORTED")
        if token["decimals"] > 18 or quote_token["decimals"] > 18:
            unsupported.append("PUMP_DECIMALS_UNSUPPORTED")
        if market_data.get("depth") or market_data.get("post_complete_base_out"):
            unsupported.append("PUMP_MIGRATION_ROUTE_UNSUPPORTED")
        if not base_account["quote_supported"] or quote_account is not None and not quote_account["quote_supported"]:
            unsupported.append("PUMP_VAULT_EXTENSION_UNSUPPORTED")
        if kind == "amm" and configuration.get("disable_flags", 0) & 24:
            unsupported.append("PUMP_TRADING_DISABLED")
        if kind == "curve" and market_data.get("quote_mint") != quote_mint:
            unsupported.append("PUMP_QUOTE_MINT_MISMATCH")
        try:
            quotes.validate_market(market)
        except ValueError as exc:
            unsupported.append(_error(exc))
        risks = [{"code": warning, "severity": "warning", "label": warning.replace("_", " ")} for warning in warnings]
        risks += [{"code": item, "severity": "error", "label": item.replace("_", " ")} for item in unsupported]
        token.update(mint=mint, supply_atoms=str(token["supply"]), supply_display=units(token["supply"], token["decimals"]))
        fingerprint = hashlib.sha256(json.dumps({"accounts": raw, "epoch": epoch, "deployment_slot": deployment_slot}, sort_keys=True).encode()).hexdigest()
        lifecycle = "BONDING CURVE" if kind == "curve" else "PUMPSWAP"
        state = {"mint": mint, "pool": market_address if kind == "amm" else "", "slot": slot,
            "fetched_at": self._clock(), "stale": False, "token": token,
            "market": {**market, "lifecycle": lifecycle, "supported": not unsupported,
                "effective_quote_display": units(market["quote_reserves_atoms"] + market["virtual_quote_reserves_atoms"], quote_token["decimals"]) + " " + symbol,
                "base_reserves_display": units(market["base_reserves_atoms"], token["decimals"]),
                "quote_reserves_display": units(market["quote_reserves_atoms"], quote_token["decimals"]) + " " + symbol},
            "warnings": warnings, "risks": risks, "quote": {}, "simulation": {},
            "program": {"address": program, "deployment_slot": deployment_slot, "observed_slot": slot,
                        "schema_commit": accounts.PROTOCOL_COMMIT, "source": accounts.PROTOCOL_SOURCE},
            "unsupported": unsupported}
        context = {"raw": raw, "token": token, "quote_token": quote_token, "decoded": market_data,
                   "global": configuration, "program": program, "fingerprint": fingerprint,
                   "base_vault": base_vault, "quote_vault": quote_vault, "slot": slot,
                   "market_address": market_address, "global_address": global_address,
                   "fee_address": fee_address, "unsupported": unsupported}
        return state, market, context

    def quote(self, side: str, amount: str, slippage: str = "100") -> dict:
        with self._lock:
            self._quote, self._quote_generation = {}, -1
            self._quote_revision += 1
            quote_revision = self._quote_revision
            self._state.update(quote={}, simulation={}, stress={})
            generation, market, state = self._generation, deepcopy(self._market), deepcopy(self._state)
            if self._closed or self._running or not market:
                raise ValueError("PUMP_INSPECTION_REQUIRED")
            if self._clock() - state["fetched_at"] > STALE_SECONDS:
                raise ValueError("PUMP_SNAPSHOT_STALE")
            if self._raw_context.get("unsupported"):
                raise ValueError(self._raw_context["unsupported"][0])
        side = str(side).strip().lower()
        side = {"buy": "buy_exact_in", "sell": "sell_exact_in"}.get(side, side)
        if side not in ("buy_exact_in", "buy_exact_out", "sell_exact_in"):
            raise ValueError("PUMP_SIDE_UNSUPPORTED")
        if not isinstance(slippage, str) or not re.fullmatch(r"[0-9]{1,4}", slippage) or int(slippage) > 5000:
            raise ValueError("PUMP_SLIPPAGE_INVALID")
        decimals = market["quote_decimals"] if side == "buy_exact_in" else market["base_decimals"]
        amount_atoms = parse_amount(amount, decimals)
        result = quotes.quote(market, side, amount_atoms, int(slippage))
        buy = side.startswith("buy")
        input_decimals, output_decimals = (market["quote_decimals"], market["base_decimals"]) if buy else (market["base_decimals"], market["quote_decimals"])
        input_symbol, output_symbol = (market["quote_symbol"], "TOKEN") if buy else ("TOKEN", market["quote_symbol"])
        result.update(supported=True, error="", amount_in=units(result["debit_atoms"], input_decimals) + " " + input_symbol,
                      amount_out=units(result["received_atoms"], output_decimals) + " " + output_symbol,
                      wallet_debit=units(result["debit_atoms"], input_decimals) + " " + input_symbol,
                      wallet_credit=units(result["received_atoms"], output_decimals) + " " + output_symbol,
                      min_out=units(result["min_received_atoms"], output_decimals) + " " + output_symbol,
                      max_cost=units(result["max_debit_atoms"], input_decimals) + " " + input_symbol,
                      slot=state["slot"], fetched_at=state["fetched_at"],
                      price_impact_pct=format(Decimal(result["price_impact_bps"]) / Decimal(100), "f"))
        result["fees"] = [{"label": key.removesuffix("_atoms").replace("_", " "),
                           "amount": units(value, market["base_decimals"] if key == "base_transfer_atoms" else market["quote_decimals"]),
                           "symbol": "TOKEN" if key == "base_transfer_atoms" else market["quote_symbol"]}
                          for key, value in result["fee_breakdown"].items()]
        from backend.crypto_pump_stress import analyze
        stress = analyze(market, result)
        with self._lock:
            if generation != self._generation or quote_revision != self._quote_revision or self._closed:
                raise ValueError("PUMP_SELECTION_CHANGED")
            self._quote, self._quote_generation = deepcopy(result), generation
            self._state.update(quote=result, simulation={}, stress=stress)
        return self.snapshot(refresh=False)

    def close(self):
        with self._lock:
            self._closed = True
            self._pending = None
            self._generation += 1

    def _current(self):
        with self._lock:
            if self._closed or self._running or not self._quote or self._quote_generation != self._generation:
                raise ValueError("PUMP_FRESH_QUOTE_REQUIRED")
            if self._clock() - self._state["fetched_at"] > STALE_SECONDS:
                raise ValueError("PUMP_SNAPSHOT_STALE")
            context = deepcopy(self._raw_context)
            context["quote_revision"] = self._quote_revision
            return (self._generation, deepcopy(self._market), deepcopy(self._quote), context, deepcopy(self._state))

    def simulate(self, pubkey: str, *, wallet_network: str = "mainnet") -> dict:
        from backend.crypto_pump_tx import build_unsigned
        generation, market, proposal, context, state = self._current()
        accounts.pubkey_bytes(pubkey)
        with self._lock:
            self._state["simulation"] = {}
        # No signing API exists on this path. Every transaction carries only
        # zero signatures and is sent solely to simulateTransaction.
        base_ata = accounts.derive_ata(pubkey, market["base_mint"], context["token"]["token_program"])
        quote_ata = accounts.derive_ata(pubkey, market["quote_mint"], context["quote_token"]["token_program"])
        before, before_slot = self._batch([pubkey, base_ata, quote_ata], state["slot"])
        context["raw_before"] = before
        latest = self._call("getLatestBlockhash", [{"commitment": "confirmed", "minContextSlot": before_slot}])
        blockhash = ((latest or {}).get("value") or {}).get("blockhash")
        if not isinstance(blockhash, str):
            raise ValueError("PUMP_BLOCKHASH_UNAVAILABLE")
        transaction = build_unsigned(context, market, proposal, pubkey, blockhash)
        fee = self._call("getFeeForMessage", [transaction["message"], {"commitment": "confirmed"}])
        fee_value = fee.get("value") if isinstance(fee, dict) else None
        if type(fee_value) is not int or not 0 <= fee_value < 2**64:
            raise ValueError("PUMP_FEE_ESTIMATE_UNAVAILABLE")
        observed = transaction["observed_accounts"]
        result = self._call("simulateTransaction", [transaction["transaction"], {
            "encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True,
            "commitment": "confirmed", "minContextSlot": before_slot,
            "accounts": {"encoding": "base64", "addresses": observed}, "innerInstructions": True}])
        value = result.get("value") if isinstance(result, dict) else None
        after_slot = (result.get("context") or {}).get("slot") if isinstance(result, dict) else None
        if not isinstance(value, dict) or type(after_slot) is not int or after_slot < before_slot:
            raise ValueError("PUMP_SIMULATION_RESPONSE")
        post = value.get("accounts")
        if not value.get("err") and (not isinstance(post, list) or len(post) != len(observed)):
            raise ValueError("PUMP_SIMULATION_ACCOUNTS_MISSING")
        changes = []
        if isinstance(post, list) and len(post) == len(observed):
            for key, after in zip(observed, post):
                previous = before[key]
                if key == pubkey:
                    old = (previous or {}).get("lamports", 0)
                    new = (after or {}).get("lamports", 0)
                    decimals, symbol = 9, "SOL"
                else:
                    mint = market["base_mint"] if key == base_ata else market["quote_mint"]
                    program = context["token"]["token_program"] if key == base_ata else context["quote_token"]["token_program"]
                    old = accounts.decode_token_account(previous, expected_mint=mint, expected_owner=pubkey, expected_program=program)["amount"] if previous else 0
                    new = accounts.decode_token_account(after, expected_mint=mint, expected_owner=pubkey, expected_program=program)["amount"] if after else 0
                    decimals, symbol = (market["base_decimals"], "TOKEN") if key == base_ata else (market["quote_decimals"], market["quote_symbol"])
                if type(old) is not int or type(new) is not int or not 0 <= old < 2**64 or not 0 <= new < 2**64:
                    raise ValueError("PUMP_SIMULATION_BALANCE")
                changes.append({"address": key, "account": key, "symbol": symbol, "before_atoms": str(old), "after_atoms": str(new),
                                "delta_atoms": str(new-old), "before": units(old, decimals), "after": units(new, decimals),
                                "delta": units(new-old, decimals), "delta_display": units(new-old, decimals) + " " + symbol})
        logs = value.get("logs") or []
        logs = [str(line)[:600] for line in logs[:80]] if isinstance(logs, list) else []
        consumed = value.get("unitsConsumed")
        report = {"state": "error" if value.get("err") else "ok", "error": "PUMP_SIMULATION_FAILED" if value.get("err") else "",
                  "units": consumed if type(consumed) is int and 0 <= consumed <= 2**64-1 else None,
                  "fee_lamports": str(fee_value), "fee_display": units(fee_value, 9) + " SOL",
                  "balance_changes": changes, "logs": logs, "slot": after_slot, "before_slot": before_slot,
                  "quote_slot": state["slot"], "instruction": transaction["instruction"], "mode": "RPC SIMULATION",
                  "signatures": "NONE", "broadcast": False,
                  "wallet": pubkey,
                  "wallet_network": wallet_network, "network": "mainnet",
                  "preparation_wrap_lamports": transaction.get("preparation_wrap_lamports", "0"),
                  "limits": ["RPC simulation only", "Before and simulation slots may differ", "No inclusion guarantee"]}
        with self._lock:
            if generation != self._generation or self._closed or context["quote_revision"] != self._quote_revision:
                raise ValueError("PUMP_SELECTION_CHANGED")
            self._state["simulation"] = report
        return self.snapshot(refresh=False)

    def bind_wallet(self, pubkey: str, network: str):
        with self._lock:
            report = self._state.get("simulation") or {}
            if report and (report.get("wallet") != pubkey or report.get("wallet_network") != network):
                self._state["simulation"] = {}

    def _load_paper(self):
        from backend import crypto_pump_paper as paper
        if self._paper_loaded:
            return
        self._paper_loaded = True
        try:
            value = crypto_contract.read_state_json(crypto_contract.STATE_DIR / "pump-paper-v1.json", max_bytes=1024*1024)
            self._paper = paper.validate_state(value)
            consumed = value.get("consumed_snapshots", [])
            if not isinstance(consumed, list) or len(consumed) > 128 or any(not isinstance(item, str) or not re.fullmatch(r"[a-f0-9]{64}", item) for item in consumed):
                raise ValueError("PUMP_PAPER_STATE_CORRUPT")
        except FileNotFoundError:
            self._paper = paper.new_state(100 * 10**9)
        except (ValueError, OSError):
            self._paper_error = "PUMP_PAPER_STATE_CORRUPT"

    def paper_snapshot(self):
        from backend import crypto_pump_paper as paper
        with self._lock:
            self._load_paper()
            if self._paper_error:
                return {"error": self._paper_error, "mode": "PAPER", "positions": [], "fills": []}
            state, market = deepcopy(self._paper), deepcopy(self._market)
        marks = {market["address"]: market} if market else {}
        result = paper.snapshot(state, marks, timestamp_ms=max(state["last_timestamp_ms"], int(self._clock()*1000)))
        result["quote_symbol"] = "SOL"
        result["cash_display"] = units(result["cash_atoms"], 9) + " SOL"
        result["equity_display"] = units(result["equity_atoms"], 9) + " SOL" if result["equity_atoms"] is not None else "—"
        result["pnl_display"] = units(result["pnl_atoms"], 9) + " SOL" if result["pnl_atoms"] is not None else "—"
        result["positions"] = [{"market": identity, "mint": position["base_mint"], **position,
                                "value": units(result["position_values_atoms"][identity], 9) + " SOL" if identity in result["position_values_atoms"] else "—",
                                "quantity_display": units(position["base_atoms"], market["base_decimals"]) if market and position["base_mint"] == market["base_mint"] else position["base_atoms"] + " atoms"}
                               for identity, position in state["positions"].items()]
        result["fills"] = []
        for fill in reversed(state["fills"][-32:]):
            row = deepcopy(fill)
            mint = row.get("base_mint") or (row.get("evidence") or {}).get("mint") or ""
            buy = str(row["side"]).startswith("buy")
            decimals = market["base_decimals"] if market and mint == market["base_mint"] else None
            def base_display(value):
                return units(value, decimals) + " TOKEN" if decimals is not None else str(value) + " atoms"
            row.update(mint=mint, timestamp=datetime.fromtimestamp(row["timestamp_ms"]/1000, timezone.utc).isoformat(),
                       amount_in=units(row["debit_atoms"], 9) + " SOL" if buy else base_display(row["debit_atoms"]),
                       amount_out=base_display(row["received_atoms"]) if buy else units(row["received_atoms"], 9) + " SOL")
            result["fills"].append(row)
        result["error"] = ""
        return result

    def paper_trade(self) -> dict:
        from backend import crypto_pump_paper as paper
        generation, market, proposal, context, state = self._current()
        if market["quote_mint"] != accounts.WSOL_MINT:
            raise ValueError("PUMP_PAPER_QUOTE_MISMATCH")
        with self._lock:
            self._load_paper()
            if self._paper_error:
                raise ValueError(self._paper_error)
            current = deepcopy(self._paper)
        used = current.get("consumed_snapshots", [])
        fingerprint = context["fingerprint"]
        if fingerprint in used:
            raise ValueError("PUMP_PAPER_REFRESH_REQUIRED")
        timestamp = int(self._clock()*1000)
        execution = paper.execute(current, market, proposal["side"], int(proposal["amount_atoms"]), proposal["slippage_bps"],
                                  timestamp_ms=timestamp, expected_quote=proposal)
        updated = execution["state"]
        updated["consumed_snapshots"] = (used + [fingerprint])[-128:]
        with self._lock:
            if generation != self._generation or self._closed or context["quote_revision"] != self._quote_revision:
                raise ValueError("PUMP_SELECTION_CHANGED")
            if fingerprint in self._paper.get("consumed_snapshots", []):
                raise ValueError("PUMP_PAPER_REFRESH_REQUIRED")
            path = crypto_contract.ensure_state_dir() / "pump-paper-v1.json"
            try:
                disk = crypto_contract.read_state_json(path, max_bytes=1024*1024)
            except FileNotFoundError:
                disk = None
            if disk is not None and disk != current:
                self._paper_loaded = False
                raise ValueError("PUMP_PAPER_STATE_CHANGED")
            # Store an explicit replay receipt with the fill. The internal
            # identity binds observed protocol state; it is not a UI approval.
            updated["fills"][-1]["evidence"] = {
                "network": "mainnet", "slot": state["slot"], "epoch": market["epoch"],
                "program": context["program"], "deployment_slot": state["program"]["deployment_slot"],
                "market": market["address"], "mint": market["base_mint"], "quote_mint": market["quote_mint"],
                "schema_commit": accounts.PROTOCOL_COMMIT, "side": proposal["side"],
                "fee_rates": proposal["fee_rates"], "fee_breakdown": proposal["fee_breakdown"],
                "debit_atoms": proposal["debit_atoms"], "received_atoms": proposal["received_atoms"],
                "cash_before_atoms": current["cash_atoms"], "cash_after_atoms": updated["cash_atoms"]}
            encoded_size = len((json.dumps(updated, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8"))
            if encoded_size > 1024 * 1024:
                raise ValueError("PUMP_PAPER_STORAGE_LIMIT")
            crypto_contract.write_state_json(path, updated)
            self._paper = updated
            self._state.update(quote={}, simulation={}, stress={})
            self._quote, self._quote_generation = {}, -1
            self._quote_revision += 1
            self._history.append({"ts": timestamp, "kind": "PAPER", "side": proposal["side"], "mint": state["mint"],
                                  "debit": proposal["wallet_debit"], "received": proposal["wallet_credit"]})
            self._history = self._history[-MAX_HISTORY:]
        return self.snapshot(refresh=False)

    def paper_reset(self) -> dict:
        from backend import crypto_pump_paper as paper
        state = paper.new_state(100 * 10**9)
        with self._lock:
            if self._closed:
                raise ValueError("PUMP_CLOSED")
            crypto_contract.write_state_json(crypto_contract.ensure_state_dir() / "pump-paper-v1.json", state)
            self._paper, self._paper_loaded, self._paper_error = state, True, ""
            self._quote, self._quote_generation = {}, -1
            self._quote_revision += 1
            self._state.update(quote={}, simulation={}, stress={})
        return self.snapshot(refresh=False)

    def enrich_holdings(self, holdings, sol_price, *, wallet_network):
        """Only value the inspected mint from fresh, understood real reserves."""
        with self._lock:
            market, context = deepcopy(self._market), deepcopy(self._raw_context)
            fetched, slot = self._state["fetched_at"], self._state["slot"]
        if wallet_network != "mainnet" or not market or context.get("unsupported") or self._clock()-fetched > STALE_SECONDS:
            return holdings
        quote_mint = market["quote_mint"]
        try:
            # USDC quotes remain explicitly USD approximations; missing FX or
            # unknown quote assets do not become invented USD token prices.
            if quote_mint == accounts.WSOL_MINT:
                fx = Decimal(str(sol_price))
                if not fx.is_finite() or fx <= 0:
                    return holdings
            else:
                return holdings
            normalized = quotes.validate_market(market)
            with localcontext() as ctx:
                ctx.prec = 60
                price = Decimal(normalized["quote_reserves_atoms"] + normalized["virtual_quote_reserves_atoms"]) / Decimal(normalized["base_reserves_atoms"])
                price *= Decimal(10)**(market["base_decimals"]-market["quote_decimals"]) * fx
                if not price.is_finite() or price <= 0:
                    return holdings
        except (ValueError, InvalidOperation, TypeError):
            return holdings
        return [dict(row, price_usd=str(price), price_source="Pump RPC reserve estimate · SOL/USD approximation",
                     price_stale=False, price_slot=slot, price_kind="reserve_spot_not_liquidation")
                if row.get("mint") == market["base_mint"] else row for row in holdings]
