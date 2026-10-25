"""Protocol fixtures are locally constructed; address vectors are official docs."""
from __future__ import annotations

import base64
import struct
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_pump_accounts as p


def account(raw, owner=p.PUMP_PROGRAM, **overrides):
    return {"owner": owner, "data": [base64.b64encode(raw).decode(), "base64"], "executable": False, **overrides}


def fields(names, values=None):
    values = values or {}
    raw = b""
    for name, kind in names:
        value = values.get(name, p.ZERO_KEY if kind == "key" else [] if kind.startswith("keys") else 0)
        if kind == "key":
            raw += p.pubkey_bytes(value)
        elif kind.startswith("keys"):
            raw += b"".join(p.pubkey_bytes(v) for v in (value or [p.ZERO_KEY] * int(kind[4:])))
        else:
            raw += int(value).to_bytes(1 if kind == "bool" else int(kind[1:]) // 8, "little", signed=kind.startswith("i"))
    return raw


def mint(*, authority=None, freeze=None, initialized=1, extensions=()):
    raw = struct.pack("<I", int(authority is not None)) + p.pubkey_bytes(authority or p.ZERO_KEY)
    raw += struct.pack("<QBBI", 10**15, 6, initialized, int(freeze is not None)) + p.pubkey_bytes(freeze or p.ZERO_KEY)
    if extensions:
        raw += bytes(83) + b"\x01" + b"".join(struct.pack("<HH", kind, len(value)) + value for kind, value in extensions)
    return raw


def token(*, state=1, extensions=()):
    raw = p.pubkey_bytes(p.USDC_MINT) + p.pubkey_bytes(p.PUMP_PROGRAM) + struct.pack("<Q", 5000)
    raw += bytes(36) + bytes([state]) + bytes(12) + bytes(8) + bytes(36)
    if extensions:
        raw += b"\x02" + b"".join(struct.pack("<HH", kind, len(value)) + value for kind, value in extensions)
    return raw


class PublicAddressVectors(unittest.TestCase):
    # Official docs/PUMP_PROGRAM_README.md and docs/PUMP_SWAP_README.md at
    # PROTOCOL_COMMIT, rather than expected values derived by this module.
    def test_global_vectors(self):
        self.assertEqual(p.derive_global("curve"), "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf")
        self.assertEqual(p.derive_global("amm"), "ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw")

    def test_pool_and_both_ata_vectors(self):
        mint_key = "7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump"
        pool = p.derive_pool(mint_key, creator="9XDYTfQKwW8sHPqnFdUreMmtmffmkHVPGTNV2e3LKxNW")
        self.assertEqual(pool, "GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J")
        self.assertEqual(p.derive_ata(pool, mint_key), "5jMpkf4JF4noHftLgNKyPNh6roVfPSGSjuEk3U4eLKRa")
        self.assertEqual(p.derive_ata(pool, p.WSOL_MINT), "43DVcZR4kQFjh4Xm2i3DcneRxNjZp7HMud8yDrJWrDr8")
        self.assertEqual(p.derive_pool_authority(mint_key), "9XDYTfQKwW8sHPqnFdUreMmtmffmkHVPGTNV2e3LKxNW")
        self.assertEqual(p.derive_pool(mint_key), pool)

    def test_bad_public_keys_and_seed_bounds(self):
        for bad in ["", "0" * 32, "1" * 31, "1" * 33, "z" * 44, None]:
            with self.subTest(bad=bad), self.assertRaises(p.AccountDecodeError):
                p.derive_curve(bad)
        with self.assertRaises(p.AccountDecodeError):
            p.find_program_address([b"x" * 33], p.PUMP_PROGRAM)
        with self.assertRaises(p.AccountDecodeError):
            p.find_program_address([b"x"] * 16, p.PUMP_PROGRAM)
        for bad in [-1, True, 65536]:
            with self.assertRaises(p.AccountDecodeError):
                p.derive_pool(p.USDC_MINT, index=bad)


class MintAccounts(unittest.TestCase):
    def test_classic_mint_and_authority_warnings(self):
        decoded = p.decode_mint(account(mint(authority=p.PUMP_PROGRAM, freeze=p.PUMP_AMM_PROGRAM), p.TOKEN_PROGRAM))
        self.assertEqual(decoded["supply"], 10**15)
        self.assertEqual(decoded["decimals"], 6)
        self.assertEqual(decoded["mint_authority"], p.PUMP_PROGRAM)
        self.assertEqual(decoded["freeze_authority"], p.PUMP_AMM_PROGRAM)
        self.assertIn("freeze_authority_present", decoded["warnings"])
        self.assertIsNone(p.decode_mint(account(mint(), p.TOKEN_PROGRAM))["mint_authority"])

    def test_transfer_fee_epoch_exact_boundary(self):
        config = bytes(64) + struct.pack("<Q", 40) + struct.pack("<QQH", 1, 1000, 125) + struct.pack("<QQH", 9, 2000, 250)
        source = account(mint(extensions=[(1, config)]), p.TOKEN_2022_PROGRAM)
        older, newer = p.decode_mint(source, epoch=8), p.decode_mint(source, epoch=9)
        self.assertEqual(older["transfer_fee"]["transfer_fee_basis_points"], 125)
        self.assertEqual(newer["transfer_fee"]["transfer_fee_basis_points"], 250)
        self.assertEqual(newer["transfer_fee_config"]["withheld_amount"], 40)
        self.assertTrue(newer["quote_supported"])

    def test_token2022_risks_and_unknown_fail_closed(self):
        source = account(mint(extensions=[(9, b""), (12, p.pubkey_bytes(p.PUMP_PROGRAM)),
                                          (14, bytes(32) + p.pubkey_bytes(p.PUMP_PROGRAM)), (60000, b"abc")]), p.TOKEN_2022_PROGRAM)
        decoded = p.decode_mint(source)
        self.assertTrue(decoded["non_transferable"])
        self.assertEqual(decoded["permanent_delegate"], p.PUMP_PROGRAM)
        self.assertEqual(decoded["transfer_hook"]["program_id"], p.PUMP_PROGRAM)
        self.assertFalse(decoded["quote_supported"])
        self.assertEqual(decoded["unsupported_extensions"], [60000])

    def test_malformed_mints_and_tlv(self):
        invalid = [mint(initialized=2), mint(initialized=0), mint()[:-1], mint() + bytes(1),
                   mint(extensions=[(9, b"x")]), mint(extensions=[(9, b""), (9, b"")]),
                   mint(extensions=[(1, bytes(107))]), mint(extensions=[(6, b"\x03")])]
        for raw in invalid:
            with self.subTest(size=len(raw)), self.assertRaises(p.AccountDecodeError):
                p.decode_mint(account(raw, p.TOKEN_2022_PROGRAM))
        valid = bytearray(mint(extensions=[(9, b"")]))
        valid[82] = 1
        with self.assertRaises(p.AccountDecodeError):
            p.decode_mint(account(valid, p.TOKEN_2022_PROGRAM))
        valid[82] = 0
        valid[165] = 2
        with self.assertRaises(p.AccountDecodeError):
            p.decode_mint(account(valid, p.TOKEN_2022_PROGRAM))
        for pos in (0, 46):
            raw = bytearray(mint())
            raw[pos:pos + 4] = struct.pack("<I", 2)
            with self.assertRaises(p.AccountDecodeError):
                p.decode_mint(account(raw, p.TOKEN_PROGRAM))


class ProgramAccounts(unittest.TestCase):
    def test_independent_published_binary_fixtures(self):
        # Fixed struct pack and published values deliberately do not consult
        # implementation field lists. Catch an accidentally shifted layout.
        curve = bytes([23, 183, 248, 55, 96, 216, 172, 96]) + struct.pack(
            "<QQQQQB", 1072999999992855, 30000000013, 793099999992855, 13, 1000000000000000, 0)
        decoded = p.decode_curve(account(curve))
        self.assertEqual(decoded["real_quote_reserves"], 13)
        self.assertEqual(decoded["virtual_token_reserves"], 1072999999992855)
        self.assertFalse(decoded["complete"])
        keys = ["9XDYTfQKwW8sHPqnFdUreMmtmffmkHVPGTNV2e3LKxNW", "7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump",
                p.WSOL_MINT, "6dpnPD6UWDw5hbJEuPQwnCCMba1JYwHANKuL6GQ6otAH", "5jMpkf4JF4noHftLgNKyPNh6roVfPSGSjuEk3U4eLKRa",
                "43DVcZR4kQFjh4Xm2i3DcneRxNjZp7HMud8yDrJWrDr8"]
        pool = bytes([241, 154, 109, 4, 17, 177, 109, 188]) + struct.pack("<BH", 254, 0)
        pool += b"".join(p.pubkey_bytes(k) for k in keys) + struct.pack("<Q", 4194352106721)
        pool += p.pubkey_bytes("5L5k7gtNLbeXdzpvNrFshg1E1id1ceUDfc6vPUTxp98q") + b"\0\0" + bytes(16)
        decoded = p.decode_pool(account(pool, p.PUMP_AMM_PROGRAM))
        self.assertEqual(decoded["lp_supply"], 4194352106721)
        self.assertEqual(decoded["pool_base_token_account"], keys[4])
        self.assertEqual(decoded["pool_quote_token_account"], keys[5])
        self.assertTrue(decoded["is_pump_pool"])

    def test_legacy_and_current_curve(self):
        values = {"virtual_token_reserves": 1073000000000000, "virtual_quote_reserves": 30000000000,
                  "real_token_reserves": 793100000000000, "token_total_supply": 10**15,
                  "creator": p.PUMP_PROGRAM, "depth": 2, "quote_mint": p.USDC_MINT}
        disc = p._DISCRIMINATORS["BondingCurve"]
        legacy = p.decode_curve(account(disc + fields(p._CURVE_FIELDS[:6], values)))
        self.assertEqual(legacy["quote_mint"], p.WSOL_MINT)
        self.assertEqual(legacy["creator"], p.ZERO_KEY)
        self.assertEqual(legacy["virtual_sol_reserves"], 30000000000)
        current = p.decode_curve(account(disc + fields(p._CURVE_FIELDS, values)))
        self.assertEqual(current["quote_mint"], p.USDC_MINT)
        self.assertEqual(current["depth"], 2)
        self.assertIn("quote_chain_curve_requires_v3", current["warnings"])

    def test_every_whole_append_boundary_and_partial_field(self):
        disc = p._DISCRIMINATORS["BondingCurve"]
        for count in range(6, len(p._CURVE_FIELDS) + 1):
            raw = disc + fields(p._CURVE_FIELDS[:count])
            p.decode_curve(account(raw))
            if p._CURVE_FIELDS[count - 1][1] not in ("bool", "u8"):
                with self.assertRaises(p.AccountDecodeError):
                    p.decode_curve(account(raw[:-1]))

    def test_signed_pool_and_fees_are_not_double_subtracted(self):
        raw = p._DISCRIMINATORS["Pool"] + fields(p._POOL_FIELDS, {"virtual_quote_reserves": -30,
                  "protocol_fees": 20, "creator_fees": 10, "base_mint": p.USDC_MINT})
        decoded = p.decode_pool(account(raw, p.PUMP_AMM_PROGRAM))
        self.assertEqual(decoded["virtual_quote_reserves"], -30)
        self.assertEqual(decoded["reserved_quote_fees"], 30)
        self.assertEqual(decoded["boost_quote_reserves"], 0)
        self.assertEqual(p.effective_pool_quote_reserves(decoded, 1030), 1000)
        for amount in (29, p.U64_MAX + 1, True):
            with self.assertRaises(p.AccountDecodeError):
                p.effective_pool_quote_reserves(decoded, amount)
        with self.assertRaises(p.AccountDecodeError):
            p.effective_pool_quote_reserves({"virtual_quote_reserves": 1}, p.U64_MAX)
        legacy = p.decode_pool(account(p._DISCRIMINATORS["Pool"] + fields(p._POOL_FIELDS[:9]), p.PUMP_AMM_PROGRAM))
        self.assertEqual(legacy["virtual_quote_reserves"], 0)

    def test_documented_extended_pool_zero_allocation_only(self):
        raw = p._DISCRIMINATORS["Pool"] + fields(p._POOL_FIELDS, {"virtual_quote_reserves": -30, "creator_fees": 30})
        self.assertEqual(len(raw), 287)
        current = p.decode_pool(account(raw + bytes(13), p.PUMP_AMM_PROGRAM))
        self.assertEqual(current["layout_bytes"], 300)
        self.assertEqual(current["serialized_bytes"], 287)
        self.assertEqual(current["virtual_quote_reserves"], -30)
        invalid = [raw[:-1], raw + bytes(1), raw + bytes(12), raw + bytes(14), raw + bytes(12) + b"\x01"]
        for data in invalid:
            with self.subTest(size=len(data)), self.assertRaises(p.AccountDecodeError):
                p.decode_pool(account(data, p.PUMP_AMM_PROGRAM))

    def test_global_flags_and_fees(self):
        decoded = p.decode_global(account(p._DISCRIMINATORS["Global"] + fields(p._GLOBAL_FIELDS,
                                  {"initialized": 1, "fee_basis_points": 95, "creator_fee_basis_points": 30})))
        self.assertEqual(decoded["fee_basis_points"], 95)
        amm = p.decode_global(account(p._DISCRIMINATORS["GlobalConfig"] + fields(p._AMM_GLOBAL_FIELDS,
                              {"disable_flags": 24, "lp_fee_basis_points": 20}), p.PUMP_AMM_PROGRAM), kind="amm")
        self.assertEqual(amm["disable_flags"], 24)
        self.assertEqual(amm["lp_fee_basis_points"], 20)

    def test_fee_vectors_order_bound_and_legacy(self):
        header = p._DISCRIMINATORS["FeeConfig"] + b"\xff" + bytes(32) + struct.pack("<QQQ", 20, 5, 30)
        tier = (10**15).to_bytes(16, "little") + struct.pack("<QQQ", 20, 10, 40)
        def allocated(payload, length):
            return payload + bytes(length-len(payload))
        legacy = p.decode_fee_config(account(allocated(header + struct.pack("<I", 1) + tier, 2512), p.PUMP_FEES_PROGRAM))
        self.assertEqual(legacy["fee_tiers"][0]["market_cap_lamports_threshold"], 10**15)
        current = p.decode_fee_config(account(allocated(header + struct.pack("<I", 1) + tier + struct.pack("<I", 0) + struct.pack("<QQQ", 20, 25, 35), 4097), p.PUMP_FEES_PROGRAM))
        self.assertEqual(current["exotic_flat_fees"]["protocol_fee_bps"], 25)
        for tail in [struct.pack("<I", 129), struct.pack("<I", 62), struct.pack("<I", 2) + tier + tier]:
            with self.assertRaises(p.AccountDecodeError):
                p.decode_fee_config(account(allocated(header + tail, 2512), p.PUMP_FEES_PROGRAM))

    def test_fee_allocation_version_gates_ignore_documented_stale_bytes(self):
        header = p._DISCRIMINATORS["FeeConfig"] + b"\xff" + bytes(32) + struct.pack("<QQQ", 20, 5, 30)
        tier = bytes(16) + struct.pack("<QQQ", 20, 10, 40)
        primary = header + struct.pack("<I", 1) + tier
        # These bytes LOOK like newly appended stable/exotic fields but the
        # pre-stable allocation version must never read them as such.
        apparent_stable = struct.pack("<I", 1) + tier + struct.pack("<QQQ", 9, 9, 9)
        legacy = primary + apparent_stable
        legacy += b"\xfe" * (2512-len(legacy))
        decoded = p.decode_fee_config(account(legacy, p.PUMP_FEES_PROGRAM))
        self.assertEqual(decoded["stable_fee_tiers"], [])
        self.assertEqual(decoded["exotic_flat_fees"], {"lp_fee_bps": 0, "protocol_fee_bps": 0, "creator_fee_bps": 0})
        stable = primary + struct.pack("<I", 1) + tier
        stable += struct.pack("<QQQ", 9, 9, 9) + b"\xfd" * (4073-len(stable)-24)
        decoded = p.decode_fee_config(account(stable, p.PUMP_FEES_PROGRAM))
        self.assertEqual(len(decoded["stable_fee_tiers"]), 1)
        self.assertEqual(decoded["exotic_flat_fees"]["creator_fee_bps"], 0)
        current = primary + struct.pack("<I", 0) + struct.pack("<QQQ", 20, 25, 35)
        current += b"\xfc" * (4097-len(current))
        decoded = p.decode_fee_config(account(current, p.PUMP_FEES_PROGRAM))
        self.assertEqual(decoded["exotic_flat_fees"]["creator_fee_bps"], 35)
        self.assertGreater(decoded["allocation_tail_bytes"], 0)
        for data in [primary, legacy[:-1], legacy + b"\0", current + b"\0"]:
            with self.subTest(size=len(data)), self.assertRaises(p.AccountDecodeError):
                p.decode_fee_config(account(data, p.PUMP_FEES_PROGRAM))
        # An actual selected field that exceeds its known allocation is not
        # padding. Stable vector capacity must be checked before reading.
        invalid = primary + struct.pack("<I", 128)
        invalid += bytes(4073-len(invalid))
        with self.assertRaises(p.AccountDecodeError):
            p.decode_fee_config(account(invalid, p.PUMP_FEES_PROGRAM))

    def test_owners_executable_discriminator_size_and_encoding(self):
        raw = p._DISCRIMINATORS["BondingCurve"] + fields(p._CURVE_FIELDS[:6])
        invalid = [account(raw, p.PUMP_AMM_PROGRAM), account(raw, executable=True),
                   account(raw, executable=0), account(b"bad-disc" + raw[8:]),
                   account(raw + bytes(p.MAX_ACCOUNT_BYTES)), {"owner": p.PUMP_PROGRAM, "executable": False, "data": ["@@", "base64"]},
                   {"owner": p.PUMP_PROGRAM, "executable": False, "data": ["", "base64+zstd"]}]
        for item in invalid:
            with self.subTest(keys=list(item)), self.assertRaises(p.AccountDecodeError):
                p.decode_curve(item)
        boolean = bytearray(raw)
        boolean[48] = 2
        with self.assertRaises(p.AccountDecodeError):
            p.decode_curve(account(boolean))
        with self.assertRaises(p.AccountDecodeError):
            p.decode_curve(account(raw + b"unknown-tail"))


class TokenAccounts(unittest.TestCase):
    def test_account_bindings_and_frozen(self):
        decoded = p.decode_token_account(account(token(), p.TOKEN_PROGRAM), expected_mint=p.USDC_MINT,
                                         expected_owner=p.PUMP_PROGRAM, expected_program=p.TOKEN_PROGRAM)
        self.assertEqual(decoded["amount"], 5000)
        self.assertTrue(decoded["quote_supported"])
        frozen = p.decode_token_account(account(token(state=2), p.TOKEN_PROGRAM))
        self.assertFalse(frozen["quote_supported"])
        for kwargs in [{"expected_mint": p.WSOL_MINT}, {"expected_owner": p.PUMP_AMM_PROGRAM}, {"expected_program": p.TOKEN_2022_PROGRAM}]:
            with self.assertRaises(p.AccountDecodeError):
                p.decode_token_account(account(token(), p.TOKEN_PROGRAM), **kwargs)

    def test_token2022_extensions(self):
        decoded = p.decode_token_account(account(token(extensions=[(2, struct.pack("<Q", 8)), (7, b"")]), p.TOKEN_2022_PROGRAM))
        self.assertEqual(decoded["withheld_amount"], 8)
        self.assertEqual(decoded["amount"], 5000)  # Withheld amount is separate from spendable amount.
        for raw in [token(state=0), token(state=3), token()[:-1], token(extensions=[(15, b"\x02")]), token(extensions=[(2, b"")])]:
            with self.assertRaises(p.AccountDecodeError):
                p.decode_token_account(account(raw, p.TOKEN_2022_PROGRAM))


if __name__ == "__main__":
    unittest.main()
