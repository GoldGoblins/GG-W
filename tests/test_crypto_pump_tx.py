"""Independent unsigned wire decoding, protocol account order and WSOL prep."""
from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_pump_accounts as a
from backend import crypto_pump_tx as tx
from backend.crypto_pump_quotes import quote


def key(number):
    return a.b58encode(bytes([number]) * 32)


PAYER, MINT, BLOCKHASH, CREATOR, BUYBACK, RECIPIENT = map(key, (9, 10, 11, 12, 13, 14))


def raw_token(mint, *, amount=0, program=a.TOKEN_PROGRAM, native=None, state=1, owner=PAYER):
    raw = a.pubkey_bytes(mint) + a.pubkey_bytes(owner) + struct.pack("<Q", amount)
    raw += bytes(36) + bytes([state]) + struct.pack("<IQ", int(native is not None), native or 0)
    raw += bytes(8) + bytes(36)
    return {"owner": program, "executable": False,
            "lamports": (native or 2039280) + amount,
            "data": [base64.b64encode(raw).decode(), "base64"]}


def fixture(kind="amm", *, base_program=a.TOKEN_2022_PROGRAM):
    program = a.PUMP_PROGRAM if kind == "curve" else a.PUMP_AMM_PROGRAM
    pool_creator = a.derive_pool_authority(MINT)
    address = a.derive_curve(MINT) if kind == "curve" else a.derive_pool(MINT)
    market = dict(kind=kind, address=address, base_mint=MINT, quote_mint=a.WSOL_MINT,
        base_reserves_atoms=1_000_000_000_000, quote_reserves_atoms=30_000_000_000,
        real_base_reserves_atoms=800_000_000_000, real_quote_reserves_atoms=20_000_000_000,
        base_decimals=6, quote_decimals=9, lp_fee_bps=0 if kind == "curve" else 20,
        protocol_fee_bps=93, creator_fee_bps=30, trade_v2=kind == "amm", buyback_bps=2000,
        instruction_version=2)
    context = dict(program=program, market_address=address,
        global_address=a.derive_global(kind), fee_address=a.derive_fee_config(program),
        base_vault=a.derive_ata(address, MINT, base_program),
        quote_vault=a.derive_ata(address, a.WSOL_MINT), unsupported=[],
        token=dict(token_program=base_program, quote_supported=True),
        quote_token=dict(token_program=a.TOKEN_PROGRAM, quote_supported=True),
        decoded=dict(creator=CREATOR if kind == "curve" else pool_creator,
                     coin_creator=CREATOR, index=0),
        **{"global": dict(fee_recipient=RECIPIENT, buyback_fee_recipients=[BUYBACK])})
    base_ata = a.derive_ata(PAYER, MINT, base_program)
    quote_ata = a.derive_ata(PAYER, a.WSOL_MINT)
    context["raw_before"] = {
        PAYER: {"owner": a.ZERO_KEY, "executable": False, "lamports": 10**12,
                "data": ["", "base64"]}, base_ata: None, quote_ata: None}
    return context, market


def decode_wire(encoded):
    """Decode independently from the compiler, including signer/writable header."""
    raw = base64.b64decode(encoded, validate=True)
    offset = 0

    def take(count):
        nonlocal offset
        if offset + count > len(raw):
            raise AssertionError("truncated transaction")
        part = raw[offset:offset + count]
        offset += count
        return part

    def count():
        value = 0
        for shift in (0, 7, 14):
            byte = take(1)[0]
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise AssertionError("invalid short vector")

    signatures = [take(64) for _ in range(count())]
    message_start = offset
    signed, readonly_signed, readonly_unsigned = take(3)
    keys = [a.b58encode(take(32)) for _ in range(count())]
    permissions = {}
    for i, name in enumerate(keys):
        permissions[name] = (i < signed, i < signed - readonly_signed if i < signed
                             else i < len(keys) - readonly_unsigned)
    blockhash = a.b58encode(take(32))
    instructions = []
    for _ in range(count()):
        program_index = take(1)[0]
        account_indices = list(take(count()))
        data = take(count())
        instructions.append({"program": keys[program_index],
            "accounts": [keys[i] for i in account_indices], "data": data})
    if offset != len(raw):
        raise AssertionError("unparsed transaction bytes")
    return dict(raw=raw, signatures=signatures, signed=signed, keys=keys,
                permissions=permissions, blockhash=blockhash,
                instructions=instructions, message=raw[message_start:])


class PumpUnsignedTests(unittest.TestCase):
    def test_curve_v2_token2022_exact_base_wire_and_optional_false(self):
        context, market = fixture("curve")
        market["base_transfer_fee"] = {"bps": 100, "max_fee": 50}
        estimate = quote(market, "buy", 100_000_000, 100)
        built = tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        wire = decode_wire(built["transaction"])
        self.assertEqual(wire["signatures"], [bytes(64)])
        self.assertEqual(wire["signed"], 1)
        self.assertEqual(wire["blockhash"], BLOCKHASH)
        self.assertEqual(wire["keys"][0], PAYER)
        self.assertEqual(wire["permissions"][PAYER], (True, True))
        self.assertEqual(base64.b64decode(built["message"]), wire["message"])
        self.assertLessEqual(len(wire["raw"]), 1232)
        trade = wire["instructions"][-1]
        self.assertEqual(trade["program"], a.PUMP_PROGRAM)
        self.assertEqual(trade["data"][:8], bytes([184, 23, 238, 97, 103, 197, 211, 61]))
        self.assertEqual(len(trade["data"]), 25)
        gross, cap = struct.unpack("<QQ", trade["data"][8:24])
        self.assertEqual(gross, int(estimate["received_atoms"]) + 50)
        self.assertEqual(cap, int(estimate["max_debit_atoms"]))
        self.assertEqual(trade["data"][24], 0)
        self.assertEqual(len(trade["accounts"]), 27)
        self.assertEqual(trade["accounts"][:6], [a.derive_global("curve"), MINT, a.WSOL_MINT,
                          a.TOKEN_2022_PROGRAM, a.TOKEN_PROGRAM, a.ASSOCIATED_TOKEN_PROGRAM])
        self.assertEqual(trade["accounts"][10:16], [a.derive_curve(MINT), context["base_vault"],
            context["quote_vault"], PAYER, a.derive_ata(PAYER, MINT, a.TOKEN_2022_PROGRAM),
            a.derive_ata(PAYER, a.WSOL_MINT)])
        creator_vault = a.find_program_address([b"creator-vault", a.pubkey_bytes(CREATOR)], a.PUMP_PROGRAM)[0]
        self.assertEqual(trade["accounts"][16], creator_vault)
        self.assertEqual(trade["accounts"][-5:], [a.derive_fee_config(), a.PUMP_FEES_PROGRAM,
            a.ZERO_KEY, a.find_program_address([b"__event_authority"], a.PUMP_PROGRAM)[0], a.PUMP_PROGRAM])
        for account in (MINT, a.WSOL_MINT, a.TOKEN_2022_PROGRAM, a.TOKEN_PROGRAM,
                        a.PUMP_PROGRAM, a.PUMP_FEES_PROGRAM):
            self.assertEqual(wire["permissions"][account], (False, False))
        for account in (context["market_address"], context["base_vault"], context["quote_vault"]):
            self.assertEqual(wire["permissions"][account], (False, True))
        self.assertEqual(built["preparation_wrap_lamports"], "0")
        self.assertTrue(built["native_quote"])

    def test_amm_exact_in_creates_wraps_syncs_and_uses_wallet_net_floor(self):
        context, market = fixture()
        estimate = quote(market, "buy", 100_000_000, 200)
        built = tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        wire = decode_wire(built["transaction"])
        self.assertEqual(len(wire["instructions"]), 5)
        base_create, quote_create, wrap, sync, trade = wire["instructions"]
        self.assertEqual(base_create["program"], a.ASSOCIATED_TOKEN_PROGRAM)
        self.assertEqual(base_create["accounts"][-1], a.TOKEN_2022_PROGRAM)
        self.assertEqual(base_create["data"], b"\x01")
        quote_ata = a.derive_ata(PAYER, a.WSOL_MINT)
        self.assertEqual(quote_create["accounts"], [PAYER, quote_ata, PAYER, a.WSOL_MINT,
                                                    a.ZERO_KEY, a.TOKEN_PROGRAM])
        self.assertEqual(wrap["program"], a.ZERO_KEY)
        self.assertEqual(wrap["accounts"], [PAYER, quote_ata])
        opcode, lamports = struct.unpack("<IQ", wrap["data"])
        self.assertEqual(opcode, 2)
        self.assertEqual(lamports, int(estimate["max_debit_atoms"]))
        self.assertEqual(sync, dict(program=a.TOKEN_PROGRAM, accounts=[quote_ata], data=b"\x11"))
        self.assertEqual(trade["program"], a.PUMP_AMM_PROGRAM)
        self.assertEqual(trade["data"][:8], bytes([194, 171, 28, 70, 104, 77, 91, 47]))
        self.assertEqual(struct.unpack("<QQ", trade["data"][8:]),
                         (100_000_000, int(estimate["min_received_atoms"])))
        self.assertEqual(len(trade["accounts"]), 17)
        self.assertEqual(trade["accounts"][:9], [context["market_address"], PAYER,
            a.derive_global("amm"), MINT, a.WSOL_MINT,
            a.derive_ata(PAYER, MINT, a.TOKEN_2022_PROGRAM), quote_ata,
            context["base_vault"], context["quote_vault"]])
        self.assertEqual(trade["accounts"][14], a.derive_ata(BUYBACK, a.WSOL_MINT))
        self.assertEqual(wire["signatures"], [bytes(64)])
        self.assertLessEqual(len(wire["raw"]), 1232)

    def test_amm_base_transfer_fee_network_parity_is_explicitly_unverified(self):
        context, market = fixture()
        market["base_transfer_fee"] = {"bps": 100, "max_fee": 500}
        estimate = quote(market, "buy", 100_000_000, 200)
        self.assertIn("network parity unverified", " ".join(estimate["limits"]))
        with self.assertRaisesRegex(ValueError, "BASE_TRANSFER_FEE_UNVERIFIED"):
            tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        # Plain Token-2022 and mathematically zero fee schedules still work.
        for zero in ({"bps": 0, "max_fee": 500}, {"bps": 100, "max_fee": 0}):
            market["base_transfer_fee"] = zero
            estimate = quote(market, "buy", 100_000_000, 200)
            self.assertEqual(tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)["instruction"],
                             "buy_exact_quote_in_v2")

    def test_existing_wsol_wraps_only_deficit_and_never_closes(self):
        context, market = fixture()
        quote_ata = a.derive_ata(PAYER, a.WSOL_MINT)
        context["raw_before"][quote_ata] = raw_token(a.WSOL_MINT, amount=60_000_000, native=2039280)
        estimate = quote(market, "buy_exact_out", 1_000_000_000, 100)
        # More WSOL than the cap: no System transfer. Sync allows preexisting
        # unsynced native lamports to count instead of wrapping them again.
        built = tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        wire = decode_wire(built["transaction"])
        self.assertEqual(built["preparation_wrap_lamports"], "0")
        self.assertFalse(any(ix["program"] == a.ZERO_KEY for ix in wire["instructions"]))
        self.assertFalse(any(ix["program"] == a.TOKEN_PROGRAM and ix["data"] == b"\x09"
                             for ix in wire["instructions"]))
        self.assertEqual(wire["instructions"][-1]["data"][:8],
                         bytes([184, 23, 238, 97, 103, 197, 211, 61]))
        self.assertEqual(struct.unpack("<QQ", wire["instructions"][-1]["data"][8:]),
                         (int(estimate["received_atoms"]), int(estimate["max_debit_atoms"])))
        context["raw_before"][quote_ata] = raw_token(a.WSOL_MINT, amount=10, native=2039280)
        context["raw_before"][quote_ata]["lamports"] += 100
        built = tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        self.assertEqual(int(built["preparation_wrap_lamports"]), int(estimate["max_debit_atoms"]) - 110)

    def test_sell_creates_receiving_wsol_without_wrapping(self):
        context, market = fixture(base_program=a.TOKEN_PROGRAM)
        base_ata = a.derive_ata(PAYER, MINT)
        context["raw_before"][base_ata] = raw_token(MINT, amount=2_000_000_000)
        estimate = quote(market, "sell", 1_000_000_000, 100)
        built = tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        wire = decode_wire(built["transaction"])
        self.assertEqual(len(wire["instructions"]), 2)
        self.assertEqual(wire["instructions"][0]["program"], a.ASSOCIATED_TOKEN_PROGRAM)
        trade = wire["instructions"][-1]
        self.assertEqual(trade["data"][:8], bytes([93, 246, 130, 60, 231, 233, 64, 178]))
        self.assertEqual(struct.unpack("<QQ", trade["data"][8:]),
                         (1_000_000_000, int(estimate["min_received_atoms"])))
        self.assertEqual(built["preparation_wrap_lamports"], "0")

    def test_curve_sell_native_path_has_no_wrap_or_quote_ata_create(self):
        context, market = fixture("curve")
        base_ata = a.derive_ata(PAYER, MINT, a.TOKEN_2022_PROGRAM)
        context["raw_before"][base_ata] = raw_token(MINT, amount=2_000_000_000,
                                                   program=a.TOKEN_2022_PROGRAM)
        estimate = quote(market, "sell", 1_000_000_000, 100)
        built = tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        wire = decode_wire(built["transaction"])
        self.assertEqual(len(wire["instructions"]), 1)
        trade = wire["instructions"][0]
        self.assertEqual(len(trade["accounts"]), 26)
        self.assertEqual(trade["data"][:8], bytes([93, 246, 130, 60, 231, 233, 64, 178]))
        self.assertEqual(struct.unpack("<QQ", trade["data"][8:]),
                         (1_000_000_000, int(estimate["min_received_atoms"])))
        self.assertTrue(built["native_quote"])

    def test_untrusted_interface_and_user_data_fail_closed(self):
        context, market = fixture()
        estimate = quote(market, "buy", 100_000_000)
        for field in ("debit_atoms", "received_atoms", "min_received_atoms", "max_debit_atoms"):
            tampered = {**estimate, field: str(int(estimate[field]) + 1)}
            with self.assertRaisesRegex(ValueError, "QUOTE_CHANGED"):
                tx.build_unsigned(context, market, tampered, PAYER, BLOCKHASH)
        for field, value in (("program", a.PUMP_PROGRAM), ("global_address", key(30)),
                             ("fee_address", key(31)), ("market_address", key(32)),
                             ("base_vault", key(33)), ("quote_vault", key(34))):
            with self.subTest(field=field), self.assertRaises(ValueError):
                tx.build_unsigned({**context, field: value}, market, estimate, PAYER, BLOCKHASH)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "untrusted.json"
            facts = json.loads(tx._FACTS.read_text())
            facts["programs"]["amm"]["instructions"]["buy_exact_quote_in_v2"]["accounts"][0]["writable"] = False
            path.write_text(json.dumps(facts))
            with patch.object(tx, "_FACTS", path), self.assertRaisesRegex(ValueError, "INTEGRITY"):
                tx.build_unsigned(context, market, estimate, PAYER, BLOCKHASH)
        quote_ata = a.derive_ata(PAYER, a.WSOL_MINT)
        for bad in (raw_token(a.USDC_MINT, native=2039280),
                    raw_token(a.WSOL_MINT, native=2039280, owner=CREATOR),
                    raw_token(a.WSOL_MINT, native=2039280, state=2),
                    raw_token(a.WSOL_MINT, native=None)):
            modified = deepcopy(context)
            modified["raw_before"][quote_ata] = bad
            with self.assertRaisesRegex(ValueError, "USER_TOKEN|WSOL_NATIVE"):
                tx.build_unsigned(modified, market, estimate, PAYER, BLOCKHASH)
        missing = deepcopy(context)
        del missing["raw_before"]
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_REQUIRED"):
            tx.build_unsigned(missing, market, estimate, PAYER, BLOCKHASH)
        insufficient = deepcopy(context)
        insufficient["raw_before"][PAYER]["lamports"] = 1
        with self.assertRaisesRegex(ValueError, "NATIVE_BALANCE"):
            tx.build_unsigned(insufficient, market, estimate, PAYER, BLOCKHASH)

    def test_compiler_rejects_extra_signers_bad_flags_and_oversize(self):
        with self.assertRaisesRegex(ValueError, "SIGNERS"):
            tx._compile(PAYER, BLOCKHASH, [(a.ZERO_KEY, [(MINT, True, True)], b"\x00")])
        with self.assertRaisesRegex(ValueError, "PERMISSIONS"):
            tx._compile(PAYER, BLOCKHASH, [(a.ZERO_KEY, [(MINT, 1, False)], b"\x00")])
        with self.assertRaisesRegex(ValueError, "PROGRAM_PERMISSIONS"):
            tx._compile(PAYER, BLOCKHASH, [(a.ZERO_KEY, [(a.ZERO_KEY, True, False)], b"\x00")])
        with self.assertRaisesRegex(ValueError, "TRANSACTION_SIZE"):
            tx._compile(PAYER, BLOCKHASH, [(a.ZERO_KEY, [], bytes(1200))])
        with self.assertRaisesRegex(ValueError, "INSTRUCTION_LIMIT"):
            tx._compile(PAYER, BLOCKHASH, [(a.ZERO_KEY, [], b"")] * 17)
        for bad in (True, 1.5, -1, 65536):
            with self.assertRaises(ValueError):
                tx.compact_u16(bad)


if __name__ == "__main__":
    unittest.main()
