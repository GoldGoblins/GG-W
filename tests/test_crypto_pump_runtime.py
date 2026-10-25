"""Offline runtime boundary checks: no RPC transport, wallets or submissions."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_contract as contract
from backend import crypto_pump as runtime
from backend import crypto_pump_accounts as a
from backend import crypto_pump_tx as transaction

MINT = "7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump"
MINT_TWO = a.USDC_MINT
CREATOR = a.b58encode(bytes([9]) * 32)
RECIPIENT = a.b58encode(bytes([10]) * 32)
PAYER = a.b58encode(bytes([11]) * 32)
BLOCKHASH = a.b58encode(bytes([12]) * 32)


def rpc_account(data, owner, *, lamports=1_000_000_000, executable=False):
    return {"owner": owner, "data": [base64.b64encode(data).decode(), "base64"],
            "lamports": lamports, "executable": executable, "rentEpoch": 0}


def encoded_fields(schema, values):
    data = b""
    for name, kind in schema:
        value = values.get(name, a.ZERO_KEY if kind == "key" else 0)
        if kind == "key":
            data += a.pubkey_bytes(value)
        elif kind.startswith("keys"):
            data += b"".join(a.pubkey_bytes(key) for key in values.get(name, [RECIPIENT] * int(kind[4:])))
        else:
            data += int(value).to_bytes(1 if kind == "bool" else int(kind[1:]) // 8, "little", signed=kind.startswith("i"))
    return data


def mint_account(decimals=6, supply=10**15):
    # Fixed SPL base layout, independent of runtime field interpretation.
    return rpc_account(bytes(36) + struct.pack("<QBB", supply, decimals, 1) + bytes(36), a.TOKEN_PROGRAM)


def token_account(mint, authority, amount, *, state=1, extensions=None):
    data = a.pubkey_bytes(mint) + a.pubkey_bytes(authority) + struct.pack("<Q", amount)
    data += bytes(36) + bytes([state]) + bytes(12) + bytes(8) + bytes(36)
    if extensions is not None:
        data += b"\x02" + b"".join(struct.pack("<HH", key, len(value)) + value for key, value in extensions)
    return rpc_account(data, a.TOKEN_2022_PROGRAM if extensions is not None else a.TOKEN_PROGRAM)


def decode_wire(encoded):
    """Independent compact-array reader for assertions on emitted legacy wire."""
    wire = base64.b64decode(encoded, validate=True)
    if wire[:65] != b"\x01" + bytes(64):
        raise AssertionError("unsigned simulation requires one zero signature")
    cursor = [65]
    def take(count):
        start = cursor[0]
        cursor[0] += count
        if cursor[0] > len(wire):
            raise AssertionError("truncated wire")
        return wire[start:cursor[0]]
    def count():
        value, shift = 0, 0
        for _ in range(3):
            byte = take(1)[0]
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
            shift += 7
        raise AssertionError("invalid compact array")
    header = take(3)
    keys = [a.b58encode(take(32)) for _ in range(count())]
    blockhash = a.b58encode(take(32))
    instructions = []
    for _ in range(count()):
        program = keys[take(1)[0]]
        metas = [keys[index] for index in take(count())]
        data = take(count())
        instructions.append({"program": program, "metas": metas, "data": data})
    if cursor[0] != len(wire):
        raise AssertionError("unknown wire tail")
    return {"wire": wire, "header": header, "keys": keys, "blockhash": blockhash, "instructions": instructions}


class ProtocolRPC:
    """Only returns bounded in-memory account fixtures for allowed read methods."""
    def __init__(self, *, kind="curve", mint=MINT, flags=0):
        self.kind, self.mint, self.slot = kind, mint, 500
        self.calls = []
        self.accounts = {}
        self.hook = None
        self.simulation_error = None
        self.simulation_logs = ["Program fixture invoke [1]", "Program fixture success"]
        self.simulation_slot = None
        self.curve = a.derive_curve(mint)
        self.pool = a.derive_pool(mint)
        self.market = self.curve if kind == "curve" else self.pool
        self.base_vault = a.derive_ata(self.market, mint)
        self.quote_vault = a.derive_ata(self.market, a.WSOL_MINT)
        self.program = a.PUMP_PROGRAM if kind == "curve" else a.PUMP_AMM_PROGRAM
        self.global_address = a.derive_global(kind)
        self.fee_address = a.derive_fee_config(self.program)
        self.program_data = a.b58encode(bytes([3 if kind == "curve" else 4]) * 32)
        self.accounts[mint] = mint_account()
        self.accounts[a.WSOL_MINT] = mint_account(9, 10**18)
        curve = encoded_fields(a._CURVE_FIELDS, {"virtual_token_reserves": 1_073_000_000_000_000,
            "virtual_quote_reserves": 40_000_000_000, "real_token_reserves": 793_100_000_000_000,
            "real_quote_reserves": 10_000_000_000, "token_total_supply": 10**15,
            "complete": kind == "amm", "creator": CREATOR})
        self.accounts[self.curve] = rpc_account(a._DISCRIMINATORS["BondingCurve"] + curve, a.PUMP_PROGRAM, lamports=11_000_000_000)
        pool = encoded_fields(a._POOL_FIELDS, {"pool_bump": a.find_program_address([b"pool", bytes(2), a.pubkey_bytes(a.derive_pool_authority(mint)),
            a.pubkey_bytes(mint), a.pubkey_bytes(a.WSOL_MINT)], a.PUMP_AMM_PROGRAM)[1],
            "creator": a.derive_pool_authority(mint), "base_mint": mint, "quote_mint": a.WSOL_MINT,
            "lp_mint": RECIPIENT, "pool_base_token_account": self.base_vault, "pool_quote_token_account": self.quote_vault,
            "lp_supply": 10**12, "coin_creator": CREATOR, "virtual_quote_reserves": -30_000_000,
            "protocol_fees": 20_000_000, "creator_fees": 10_000_000})
        self.accounts[self.pool] = rpc_account(a._DISCRIMINATORS["Pool"] + pool, a.PUMP_AMM_PROGRAM)
        self.accounts[self.base_vault] = token_account(mint, self.market, 793_100_000_000_000)
        self.accounts[self.quote_vault] = token_account(a.WSOL_MINT, self.market, 40_030_000_000)
        global_values = {"initialized": 1, "authority": RECIPIENT, "fee_recipient": RECIPIENT, "fee_basis_points": 95,
            "creator_fee_basis_points": 30, "lp_fee_basis_points": 20, "protocol_fee_basis_points": 5,
            "coin_creator_fee_basis_points": 30, "disable_flags": flags}
        schema = a._GLOBAL_FIELDS if kind == "curve" else a._AMM_GLOBAL_FIELDS
        disc = a._DISCRIMINATORS["Global" if kind == "curve" else "GlobalConfig"]
        self.accounts[self.global_address] = rpc_account(disc + encoded_fields(schema, global_values), self.program)
        fees = struct.pack("<QQQ", 20, 95, 30)
        config = a._DISCRIMINATORS["FeeConfig"] + b"\xff" + a.pubkey_bytes(RECIPIENT) + fees
        config += struct.pack("<I", 1) + bytes(16) + fees + struct.pack("<I", 0) + fees
        config += bytes(a.FEE_CONFIG_CURRENT_BYTES - len(config))
        self.accounts[self.fee_address] = rpc_account(config, a.PUMP_FEES_PROGRAM)
        self.accounts[self.program] = rpc_account(struct.pack("<I", 2) + a.pubkey_bytes(self.program_data), runtime.LOADER, executable=True)
        self.accounts[self.program_data] = rpc_account(struct.pack("<IQB", 3, 400, 1) + a.pubkey_bytes(RECIPIENT), runtime.LOADER)
        self.accounts[PAYER] = rpc_account(b"", a.ZERO_KEY, lamports=10_000_000_000)
        self.accounts[a.derive_ata(PAYER, mint)] = token_account(mint, PAYER, 1_000_000_000_000)

    def __call__(self, method, params, network):
        self.calls.append((method, deepcopy(params), network))
        if network != "mainnet":
            raise AssertionError("research must explicitly use mainnet")
        if self.hook:
            result = self.hook(method, params)
            if result is not None:
                return result
        if method == "getMultipleAccounts":
            keys, opts = params
            assert len(keys) <= runtime.MAX_ACCOUNTS
            assert opts["encoding"] == "base64" and opts["commitment"] == "confirmed"
            return {"result": {"context": {"slot": self.slot}, "value": [deepcopy(self.accounts.get(key)) for key in keys]}}
        if method == "getEpochInfo":
            return {"result": {"epoch": 50, "absoluteSlot": self.slot}}
        if method == "getAccountInfo":
            key, opts = params
            if key == self.program_data:
                assert opts["dataSlice"] == {"offset": 0, "length": 45}
            return {"result": {"context": {"slot": self.slot}, "value": deepcopy(self.accounts.get(key))}}
        if method == "getLatestBlockhash":
            return {"result": {"context": {"slot": self.slot}, "value": {"blockhash": BLOCKHASH, "lastValidBlockHeight": 600}}}
        if method == "getFeeForMessage":
            return {"result": {"context": {"slot": self.slot}, "value": 5000}}
        if method == "simulateTransaction":
            assert params[1]["sigVerify"] is False
            wire = base64.b64decode(params[0], validate=True)
            assert wire[:65] == b"\x01" + bytes(64), "simulation must carry a zero signature"
            observed = params[1]["accounts"]["addresses"]
            after = [deepcopy(self.accounts.get(key)) for key in observed]
            if after[0]:
                after[0]["lamports"] -= 5000
            return {"result": {"context": {"slot": self.slot if self.simulation_slot is None else self.simulation_slot}, "value": {"err": self.simulation_error,
                "logs": self.simulation_logs, "unitsConsumed": 100_000, "returnData": None, "accounts": after}}}
        raise AssertionError("forbidden or unexpected RPC method: " + method)


class Runtime(unittest.TestCase):
    def setUp(self):
        self.now = [1_000.0]
        directory = tempfile.TemporaryDirectory(prefix="gg-pump-runtime-test-")
        self.addCleanup(directory.cleanup)
        patcher = patch.object(contract, "STATE_DIR", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state_dir = Path(directory.name)

    def research(self, rpc=None):
        rpc = rpc or ProtocolRPC()
        engine = runtime.PumpResearch(rpc, clock=lambda: self.now[0])
        self.addCleanup(engine.close)
        return engine, rpc

    def ready(self, engine, mint=MINT, pool=""):
        engine.inspect(mint, pool)
        deadline = time.monotonic() + 3
        while engine._running and time.monotonic() < deadline:
            time.sleep(0.001)
        state = engine.snapshot(refresh=False)
        self.assertFalse(state["loading"], state)
        self.assertEqual(state["state"], "ready", state.get("error"))
        return state

    def test_curve_fetch_quote_cache_and_no_wallet_or_network_change(self):
        engine, rpc = self.research()
        state = self.ready(engine)
        self.assertEqual(state["market"]["kind"], "curve")
        self.assertTrue(state["market"]["supported"], state["risks"])
        self.assertEqual(state["slot"], 500)
        count = len(rpc.calls)
        for _ in range(50):
            self.assertEqual(engine.snapshot(refresh=False)["slot"], 500)
        self.assertEqual(len(rpc.calls), count)
        quote = engine.quote("buy", "0.1", "100")["quote"]
        self.assertGreater(int(quote["received_atoms"]), 0)
        self.assertIn("SOL", quote["wallet_debit"])
        self.assertEqual(len(rpc.calls), count)
        self.assertEqual(list(self.state_dir.iterdir()), [])
        self.assertTrue(all(call[2] == "mainnet" for call in rpc.calls))

    def test_canonical_amm_signed_quote_and_vault_bindings(self):
        engine, rpc = self.research(ProtocolRPC(kind="amm"))
        state = self.ready(engine)
        self.assertEqual(state["pool"], rpc.pool)
        self.assertEqual(state["market"]["virtual_quote_reserves_atoms"], -30_000_000)
        self.assertTrue(state["market"]["is_pump_pool"])
        self.assertEqual(state["market"]["effective_quote_display"], "40 SOL")
        quote = engine.quote("sell", "1000", "75")["quote"]
        self.assertGreater(int(quote["received_atoms"]), 0)
        self.assertEqual(quote["slippage_bps"], 75)

    def test_wrong_owner_frozen_and_mint_authority_bindings_block(self):
        for mutation in ("owner", "mint", "authority", "frozen", "token_program"):
            with self.subTest(mutation=mutation):
                rpc = ProtocolRPC(kind="amm")
                vault = rpc.accounts[rpc.base_vault]
                if mutation == "owner":
                    vault["owner"] = a.PUMP_PROGRAM
                elif mutation == "mint":
                    rpc.accounts[rpc.base_vault] = token_account(a.WSOL_MINT, rpc.market, 1000)
                elif mutation == "authority":
                    rpc.accounts[rpc.base_vault] = token_account(MINT, CREATOR, 1000)
                elif mutation == "frozen":
                    rpc.accounts[rpc.base_vault] = token_account(MINT, rpc.market, 1000, state=2)
                else:
                    rpc.accounts[rpc.base_vault] = token_account(MINT, rpc.market, 1000, extensions=[])
                engine, _ = self.research(rpc)
                engine.inspect(MINT)
                self.wait_idle(engine)
                self.assertEqual(engine.snapshot(refresh=False)["state"], "error")
                with self.assertRaisesRegex(ValueError, "INSPECTION_REQUIRED"):
                    engine.quote("buy", "0.1")

    def wait_idle(self, engine):
        deadline = time.monotonic() + 3
        while engine._running and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertFalse(engine._running)

    def test_rpc_shape_slot_owner_and_loader_failure_close_readiness(self):
        for mutation in ("shape", "slot", "program", "metadata", "curve_discriminator"):
            with self.subTest(mutation=mutation):
                rpc = ProtocolRPC()
                if mutation == "shape":
                    rpc.hook = lambda method, params: {"result": {"context": {"slot": 500}, "value": []}} if method == "getMultipleAccounts" else None
                elif mutation == "slot":
                    rpc.hook = lambda method, params: {"result": {"context": {"slot": 0}, "value": [rpc.accounts.get(k) for k in params[0]]}} if method == "getMultipleAccounts" and params[1].get("minContextSlot") else None
                elif mutation == "program":
                    rpc.accounts[rpc.program]["executable"] = False
                elif mutation == "metadata":
                    rpc.accounts[rpc.program_data]["owner"] = a.PUMP_PROGRAM
                else:
                    rpc.accounts[rpc.curve]["data"][0] = base64.b64encode(bytes(49)).decode()
                engine, _ = self.research(rpc)
                engine.inspect(MINT)
                self.wait_idle(engine)
                self.assertEqual(engine.snapshot(refresh=False)["state"], "error")

    def test_buy_and_sell_disable_bits_not_withdraw_bit(self):
        for flag, trading_disabled in ((4, False), (8, True), (16, True)):
            with self.subTest(flag=flag):
                engine, rpc = self.research(ProtocolRPC(kind="amm", flags=flag))
                state = self.ready(engine)
                self.assertEqual("PUMP_TRADING_DISABLED" in state.get("unsupported", []), trading_disabled)
                if trading_disabled:
                    with self.assertRaisesRegex(ValueError, "TRADING_DISABLED"):
                        engine.quote("buy", "0.1")

    def test_provided_pool_must_match_stored_creator_index_and_mints(self):
        rpc = ProtocolRPC(kind="amm")
        wrong_pool = a.b58encode(bytes([21]) * 32)
        rpc.accounts[wrong_pool] = deepcopy(rpc.accounts[rpc.pool])
        # Rebind both vaults to remove the simpler authority/address failure.
        base_vault = a.derive_ata(wrong_pool, MINT)
        quote_vault = a.derive_ata(wrong_pool, a.WSOL_MINT)
        data = bytearray(base64.b64decode(rpc.accounts[wrong_pool]["data"][0]))
        data[139:171], data[171:203] = a.pubkey_bytes(base_vault), a.pubkey_bytes(quote_vault)
        rpc.accounts[wrong_pool]["data"][0] = base64.b64encode(data).decode()
        rpc.accounts[base_vault] = token_account(MINT, wrong_pool, 793_100_000_000_000)
        rpc.accounts[quote_vault] = token_account(a.WSOL_MINT, wrong_pool, 40_030_000_000)
        engine, _ = self.research(rpc)
        engine.inspect(MINT, wrong_pool)
        self.wait_idle(engine)
        self.assertEqual(engine.snapshot(refresh=False)["state"], "error")

    def test_program_metadata_slot_option_and_executable_are_checked(self):
        for mutation in ("stale_slot", "option", "executable", "future_deploy"):
            with self.subTest(mutation=mutation):
                rpc = ProtocolRPC()
                if mutation == "stale_slot":
                    rpc.hook = lambda method, params: {"result": {"context": {"slot": 499}, "value": deepcopy(rpc.accounts[rpc.program_data])}} if method == "getAccountInfo" else None
                elif mutation == "executable":
                    rpc.accounts[rpc.program_data]["executable"] = True
                else:
                    header = struct.pack("<IQB", 3, 501 if mutation == "future_deploy" else 400, 2 if mutation == "option" else 1) + a.pubkey_bytes(RECIPIENT)
                    rpc.accounts[rpc.program_data]["data"][0] = base64.b64encode(header).decode()
                engine, _ = self.research(rpc)
                engine.inspect(MINT)
                self.wait_idle(engine)
                self.assertEqual(engine.snapshot(refresh=False)["state"], "error")

    def test_token2022_vault_cpi_guard_disables_quote(self):
        rpc = ProtocolRPC(kind="amm")
        rpc.accounts[MINT]["owner"] = a.TOKEN_2022_PROGRAM
        vault_address = a.derive_ata(rpc.market, MINT, a.TOKEN_2022_PROGRAM)
        data = bytearray(base64.b64decode(rpc.accounts[rpc.pool]["data"][0]))
        data[139:171] = a.pubkey_bytes(vault_address)
        rpc.accounts[rpc.pool]["data"][0] = base64.b64encode(data).decode()
        rpc.accounts[vault_address] = token_account(MINT, rpc.market, 793_100_000_000_000, extensions=[(11, b"\x01")])
        engine, _ = self.research(rpc)
        state = self.ready(engine)
        self.assertFalse(state["market"]["supported"])
        with self.assertRaises(ValueError):
            engine.quote("buy", "0.1")

    def test_stale_snapshot_and_bad_amount_do_not_publish_quote(self):
        engine, rpc = self.research()
        self.ready(engine)
        for amount in ("0", "-1", "nan", "1e3", "0.0000000001", "1.1.1"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                engine.quote("buy", amount)
        self.assertEqual(engine.snapshot(refresh=False)["quote"], {})
        self.now[0] += runtime.STALE_SECONDS + 1
        self.assertTrue(engine.snapshot(refresh=False)["stale"])
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_STALE"):
            engine.quote("buy", "0.1")

    def test_unsigned_wire_has_exact_pinned_instruction_and_slippage_limits(self):
        for kind in ("curve", "amm"):
            for side, amount in (("buy", "0.1"), ("buy_exact_out", "1000"), ("sell", "1000")):
                with self.subTest(kind=kind, side=side):
                    engine, rpc = self.research(ProtocolRPC(kind=kind))
                    self.ready(engine)
                    quote = engine.quote(side, amount, "125")["quote"]
                    context = deepcopy(engine._raw_context)
                    context["raw_before"] = {key: deepcopy(rpc.accounts.get(key)) for key in
                        (PAYER, a.derive_ata(PAYER, MINT), a.derive_ata(PAYER, a.WSOL_MINT))}
                    built = transaction.build_unsigned(context, engine._market, quote, PAYER, BLOCKHASH)
                    parsed = decode_wire(built["transaction"])
                    self.assertLessEqual(len(parsed["wire"]), 1232)
                    self.assertEqual(parsed["header"][:2], bytes([1, 0]))
                    self.assertEqual(parsed["keys"][0], PAYER)
                    self.assertEqual(parsed["blockhash"], BLOCKHASH)
                    instruction = parsed["instructions"][-1]
                    self.assertEqual(instruction["program"], rpc.program)
                    self.assertEqual(instruction["data"][:8], hashlib.sha256(("global:" + built["instruction"]).encode()).digest()[:8])
                    first, second = struct.unpack("<QQ", instruction["data"][8:24])
                    if built["instruction"] == "buy_v2":
                        self.assertEqual(first, int(quote["received_atoms"]) + int(quote["fee_breakdown"]["base_transfer_atoms"]))
                        self.assertEqual(second, int(quote["max_debit_atoms"]))
                    elif side == "buy":
                        self.assertEqual(first, int(quote["amount_atoms"]))
                        self.assertEqual(second, int(quote["min_received_atoms"]))
                    else:
                        self.assertEqual(first, int(quote["debit_atoms"]))
                        self.assertEqual(second, int(quote["min_received_atoms"]))
                    self.assertIn(rpc.market, instruction["metas"])
                    self.assertIn(rpc.base_vault, instruction["metas"])
                    self.assertEqual(len(instruction["metas"]), 27 if kind == "curve" and side != "sell" else 26 if kind == "curve" else 17)
                    self.assertEqual(instruction["data"][24:], b"\0" if kind == "curve" and side != "sell" else b"")

    def test_simulation_is_unsigned_read_only_with_observed_balances(self):
        for kind in ("curve", "amm"):
            with self.subTest(kind=kind):
                engine, rpc = self.research(ProtocolRPC(kind=kind))
                self.ready(engine)
                engine.quote("buy", "0.1", "100")
                report = engine.simulate(PAYER)["simulation"]
                self.assertEqual(report["state"], "ok")
                self.assertFalse(report["broadcast"])
                self.assertEqual(report["signatures"], "NONE")
                self.assertEqual(report["fee_lamports"], "5000")
                self.assertEqual(report["balance_changes"][0]["delta_atoms"], "-5000")
                self.assertEqual(len(report["balance_changes"]), 3)
                self.assertEqual(list(self.state_dir.iterdir()), [])
                self.assertEqual(sum(method == "simulateTransaction" for method, _, _ in rpc.calls), 1)

    def test_simulation_error_logs_bound_stale_slot_and_quote_change(self):
        engine, rpc = self.research()
        self.ready(engine)
        engine.quote("buy", "0.1")
        rpc.simulation_error = {"InstructionError": [1, {"Custom": 6000}]}
        rpc.simulation_logs = ["x" * 1000] * 150
        report = engine.simulate(PAYER)["simulation"]
        self.assertEqual(report["state"], "error")
        self.assertLessEqual(len(report["logs"]), 80)
        self.assertTrue(all(len(line) <= 600 for line in report["logs"]))
        rpc.simulation_slot = 499
        with self.assertRaisesRegex(ValueError, "SIMULATION_RESPONSE"):
            engine.simulate(PAYER)
        self.assertEqual(engine.snapshot(refresh=False)["simulation"], {})
        rpc.simulation_slot = None
        rpc.simulation_error = None
        changed = []
        def change_quote(method, params):
            if method == "simulateTransaction" and not changed:
                changed.append(True)
                engine.quote("buy", "0.2")
            return None
        rpc.hook = change_quote
        with self.assertRaisesRegex(ValueError, "CHANGED|QUOTE"):
            engine.simulate(PAYER)
        self.assertEqual(engine.snapshot(refresh=False)["simulation"], {})

    def test_simulation_report_invalidated_by_wallet_network_or_disconnect(self):
        engine, rpc = self.research()
        self.ready(engine)
        engine.quote("buy", "0.1")
        for changed_wallet, changed_network in ((CREATOR, "mainnet"),
                                               (PAYER, "testnet"), ("", "mainnet")):
            with self.subTest(wallet=changed_wallet, network=changed_network):
                report = engine.simulate(PAYER, wallet_network="mainnet")["simulation"]
                engine.bind_wallet(PAYER, "mainnet")
                self.assertEqual(engine.snapshot(refresh=False)["simulation"], report)
                engine.bind_wallet(changed_wallet, changed_network)
                self.assertEqual(engine.snapshot(refresh=False)["simulation"], {})

    def test_host_simulation_rechecks_wallet_and_network_before_return(self):
        from backend import crypto_host as host
        engine, rpc = self.research()
        self.ready(engine)
        engine.quote("buy", "0.1")
        for changed_wallet, changed_network in ((CREATOR, "mainnet"),
                                               (PAYER, "testnet")):
            identity = {"wallet": PAYER, "network": "mainnet"}

            def change_identity(method, params):
                if method == "simulateTransaction":
                    identity.update(wallet=changed_wallet, network=changed_network)
                return None

            rpc.hook = change_identity
            with self.subTest(wallet=changed_wallet, network=changed_network), \
                    patch.object(host, "pump_service", return_value=engine), \
                    patch.object(host, "load_wallet", side_effect=lambda: {"pubkey": identity["wallet"]}), \
                    patch.object(host, "load_network", side_effect=lambda: identity["network"]):
                with self.assertRaisesRegex(ValueError, "PUMP_WALLET_CHANGED"):
                    host.pump_simulate()
            self.assertEqual(engine.snapshot(refresh=False)["simulation"], {})
        self.assertEqual(list(self.state_dir.iterdir()), [])

    def test_paper_persistence_one_use_snapshot_and_other_state_isolated(self):
        untouched = {"wallet.json": b'{"connected":false}', "network.json": b'{"network":"testnet"}', "ledger.jsonl": b"fixture\n"}
        for filename, data in untouched.items():
            (self.state_dir / filename).write_bytes(data)
        engine, rpc = self.research()
        self.ready(engine)
        initial = int(engine.snapshot(refresh=False)["paper"]["cash_atoms"])
        proposal = engine.quote("buy", "0.1")["quote"]
        state = engine.paper_trade()
        self.assertEqual(state["quote"], {})
        self.assertEqual(state["paper"]["fill_count"], 1)
        self.assertEqual(int(state["paper"]["cash_atoms"]), initial - int(proposal["debit_atoms"]))
        path = self.state_dir / "pump-paper-v1.json"
        persisted = path.read_bytes()
        engine.quote("buy", "0.1")
        with self.assertRaisesRegex(ValueError, "REFRESH_REQUIRED"):
            engine.paper_trade()
        self.assertEqual(path.read_bytes(), persisted)
        restarted, _ = self.research()
        restored = restarted.snapshot(refresh=False)["paper"]
        self.assertEqual(restored["cash_atoms"], state["paper"]["cash_atoms"])
        # Restored holdings use raw atoms until their mint is inspected again.
        # Position accounting persists; current valuation/formatting requires
        # a new observed market after restart and must not reuse an old mark.
        ephemeral = {"quantity_display", "value"}
        self.assertEqual([{key: value for key, value in row.items() if key not in ephemeral} for row in restored["positions"]],
                         [{key: value for key, value in row.items() if key not in ephemeral} for row in state["paper"]["positions"]])
        self.assertTrue(all(row["value"] == "—" for row in restored["positions"]))
        self.assertIsNone(restored["equity_atoms"])
        for filename, data in untouched.items():
            self.assertEqual((self.state_dir / filename).read_bytes(), data)
        reset = restarted.paper_reset()["paper"]
        self.assertEqual(reset["fill_count"], 0)
        self.assertEqual(int(reset["cash_atoms"]), 100 * 10**9)

    def test_paper_storage_limit_preserves_readable_disk_cache_and_quote(self):
        from backend import crypto_pump_paper as paper
        engine, rpc = self.research()
        self.ready(engine)
        engine.quote("buy", "0.001")
        engine.paper_trade()
        original = deepcopy(engine._paper)
        fill = deepcopy(original["fills"][0])
        cap = 1024 * 1024

        def filled_state(count):
            candidate = deepcopy(original)
            candidate["fills"] = [dict(fill, number=number + 1) for number in range(count)]
            return candidate

        def stored_bytes(candidate):
            return (json.dumps(candidate, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")

        # Construct a valid saved account immediately below the actual byte
        # bound, using normal evidence rows rather than an oversized field.
        low, high = 1, paper.MAX_FILLS - 1
        while low < high:
            middle = (low + high + 1) // 2
            if len(stored_bytes(filled_state(middle))) <= cap:
                low = middle
            else:
                high = middle - 1
        saved = filled_state(low)
        self.assertLess(low, paper.MAX_FILLS - 1)
        self.assertLessEqual(len(stored_bytes(saved)), cap)
        self.assertGreater(len(stored_bytes(filled_state(low + 1))), cap)
        paper.validate_state(saved)
        path = self.state_dir / "pump-paper-v1.json"
        contract.write_state_json(path, saved)
        engine._paper = deepcopy(saved)
        engine._raw_context["fingerprint"] = "f" * 64
        engine.quote("buy", "0.001")
        prior_quote = deepcopy(engine._quote)
        prior_history = deepcopy(engine._history)
        persisted = path.read_bytes()

        with self.assertRaisesRegex(ValueError, "PUMP_PAPER_STORAGE_LIMIT"):
            engine.paper_trade()
        self.assertEqual(path.read_bytes(), persisted)
        self.assertEqual(engine._paper, saved)
        self.assertEqual(engine._quote, prior_quote)
        self.assertEqual(engine._history, prior_history)
        restarted, _ = self.research()
        restored = restarted.snapshot(refresh=False)["paper"]
        self.assertEqual(restored["error"], "")
        self.assertEqual(restored["fill_count"], low)

    def test_corrupt_paper_preserved_until_explicit_reset(self):
        path = self.state_dir / "pump-paper-v1.json"
        original = b'{"version":1,"cash_atoms":"invalid"'
        path.write_bytes(original)
        engine, rpc = self.research()
        state = self.ready(engine)
        self.assertEqual(state["paper"]["error"], "PUMP_PAPER_STATE_CORRUPT")
        engine.quote("buy", "0.1")
        with self.assertRaisesRegex(ValueError, "STATE_CORRUPT"):
            engine.paper_trade()
        self.assertEqual(path.read_bytes(), original)
        reset = engine.paper_reset()
        self.assertEqual(reset["paper"]["error"], "")
        self.assertNotEqual(path.read_bytes(), original)

    def test_paper_history_and_fingerprint_memory_are_bounded(self):
        engine, rpc = self.research()
        self.ready(engine)
        # Writes are tested separately. Avoid repeated disk IO for bound test.
        with patch.object(contract, "write_state_json"):
            for number in range(runtime.MAX_HISTORY + 5):
                engine._raw_context["fingerprint"] = "fixture-" + str(number)
                engine.quote("buy", "0.001")
                engine.paper_trade()
        self.assertEqual(len(engine._history), runtime.MAX_HISTORY)
        state = engine.snapshot(refresh=False)
        self.assertEqual(len(state["history"]), 32)
        self.assertEqual(len(engine._paper["consumed_snapshots"]), 128)
        self.assertEqual(len(state["paper"]["fills"]), 32)

    def test_concurrent_paper_fills_cannot_consume_one_snapshot_twice(self):
        from backend import crypto_pump_paper as paper
        engine, rpc = self.research()
        self.ready(engine)
        engine.quote("buy", "0.1")
        barrier = threading.Barrier(2)
        execute = paper.execute
        errors, successes = [], []
        def both_compute(*args, **kwargs):
            barrier.wait(timeout=2)
            return execute(*args, **kwargs)
        def trade():
            try:
                successes.append(engine.paper_trade())
            except ValueError as exc:
                errors.append(str(exc))
        with patch.object(paper, "execute", side_effect=both_compute):
            workers = [threading.Thread(target=trade) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=3)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(engine._history), 1)
        self.assertEqual(engine.snapshot(refresh=False)["paper"]["fill_count"], 1)

    def test_worker_start_failure_and_close_never_resume(self):
        engine, rpc = self.research()
        with patch.object(runtime.threading.Thread, "start", side_effect=RuntimeError("fixture")):
            state = engine.inspect(MINT)
        self.assertEqual(state["error"], "PUMP_WORKER_START")
        self.assertFalse(engine._running)
        self.assertEqual(rpc.calls, [])
        self.ready(engine)  # A failed thread start must not wedge later work.
        call_count = len(rpc.calls)
        engine.close()
        engine.inspect(MINT)
        self.assertEqual(len(rpc.calls), call_count)

    def test_close_during_fetch_prevents_publish_and_refresh(self):
        engine, rpc = self.research()
        entered, release = threading.Event(), threading.Event()
        def held(method, params):
            if method == "getMultipleAccounts" and not entered.is_set():
                entered.set()
                release.wait(2)
            return None
        rpc.hook = held
        engine.inspect(MINT)
        self.assertTrue(entered.wait(2))
        engine.close()
        release.set()
        self.wait_idle(engine)
        state = engine.snapshot(refresh=False)
        self.assertNotEqual(state["state"], "ready")
        self.assertEqual(state["market"], {})
        calls = len(rpc.calls)
        self.now[0] += 100
        engine.snapshot(refresh=True)
        engine.inspect(MINT_TWO)
        self.assertEqual(len(rpc.calls), calls)

    def test_only_latest_selection_publishes_with_one_worker(self):
        first, second = ProtocolRPC(), ProtocolRPC(mint=MINT_TWO)
        combined = {**first.accounts, **second.accounts}
        first.accounts = combined
        entered, release = threading.Event(), threading.Event()
        thread_ids = set()
        def hook(method, params):
            thread_ids.add(threading.get_ident())
            if method == "getMultipleAccounts" and params[0][0] == MINT and not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(2))
            return None
        first.hook = hook
        engine, rpc = self.research(first)
        engine.inspect(MINT)
        self.assertTrue(entered.wait(2))
        for _ in range(10):
            engine.inspect(MINT_TWO)
        release.set()
        self.wait_idle(engine)
        state = engine.snapshot(refresh=False)
        self.assertEqual(state["state"], "ready", state["error"])
        self.assertEqual(state["mint"], MINT_TWO)
        self.assertEqual(len(thread_ids), 1)
        self.assertFalse(state["loading"])

    def test_selection_change_while_quote_computes_discards_result(self):
        engine, rpc = self.research()
        self.ready(engine)
        original = runtime.quotes.quote
        def change(*args, **kwargs):
            result = original(*args, **kwargs)
            engine.inspect(MINT_TWO)
            return result
        with patch.object(runtime.quotes, "quote", side_effect=change), self.assertRaisesRegex(ValueError, "SELECTION_CHANGED"):
            engine.quote("buy", "0.1")
        self.wait_idle(engine)
        self.assertEqual(engine.snapshot(refresh=False)["quote"], {})


    def test_desktop_heartbeat_skips_contended_paper_and_service_locks(self):
        from backend import crypto_host as host
        engine, rpc = self.research()
        self.ready(engine)
        previous = len(rpc.calls)
        generation = engine._generation
        self.now[0] += runtime.REFRESH_SECONDS + 1
        with patch.object(host, "_pump_research", engine):
            for name, lock, callback in (("paper write", engine._lock, engine.heartbeat),
                                         ("service initialization", host._pump_research_lock, host.pump_heartbeat)):
                with self.subTest(lock=name):
                    held, release = threading.Event(), threading.Event()

                    def slow_critical_section():
                        with lock:
                            held.set()
                            release.wait(timeout=2)

                    worker = threading.Thread(target=slow_critical_section)
                    worker.start()
                    try:
                        self.assertTrue(held.wait(timeout=1))
                        start = time.monotonic()
                        callback()
                        elapsed = time.monotonic() - start
                        self.assertLess(elapsed, 0.05, "Qt heartbeat must skip an occupied lock")
                    finally:
                        release.set()
                        worker.join(timeout=2)
                    self.assertFalse(worker.is_alive())
                    self.assertFalse(engine._running)
                    self.assertEqual(engine._generation, generation)
                    self.assertEqual(len(rpc.calls), previous)
            # A skipped heartbeat does not lose the selected refresh request.
            host.pump_heartbeat()
            self.wait_idle(engine)
            self.assertGreater(len(rpc.calls), previous)

    def test_desktop_heartbeat_refreshes_without_visible_consumers(self):
        engine, rpc = self.research()
        engine.heartbeat()
        self.assertEqual(rpc.calls, [])
        self.ready(engine)
        previous = len(rpc.calls)
        self.now[0] += runtime.REFRESH_SECONDS + 1
        engine.heartbeat()
        self.wait_idle(engine)
        self.assertGreater(len(rpc.calls), previous)
        self.assertEqual(engine._state["fetched_at"], self.now[0])
        engine.quote("buy", "0.1")
        previous = len(rpc.calls)
        self.now[0] += runtime.REFRESH_SECONDS + 1
        engine.heartbeat()
        self.assertEqual(len(rpc.calls), previous, "A still-valid quote must remain inspectable")
        self.now[0] += runtime.STALE_SECONDS
        engine.heartbeat()
        self.wait_idle(engine)
        self.assertGreater(len(rpc.calls), previous)
        self.assertEqual(engine._state["quote"], {})
        engine.close()
        previous = len(rpc.calls)
        self.now[0] += 100
        engine.heartbeat()
        self.assertEqual(len(rpc.calls), previous)


if __name__ == "__main__":
    unittest.main()
