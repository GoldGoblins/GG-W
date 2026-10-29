"""Real isolated Hardhat execution of the bundled standard ERC20 test token."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from backend.application_paths import PROJECT_ROOT, TOOLS_ROOT

SOURCE = PROJECT_ROOT / "support/gg-testnet"
TOOLCHAIN = Path(os.environ.get("GG_TESTNET_TOOLCHAIN", TOOLS_ROOT / "gg-testnet"))
NODE = shutil.which("node")
CLI = TOOLCHAIN / "node_modules/hardhat/dist/src/cli.js"


class GGTestTokenArtifactTests(unittest.TestCase):
    def test_public_artifact_is_fixed_supply_standard_erc20(self):
        artifact = json.loads((SOURCE / "GGTestToken.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["token"], {"name": "GG Test Token", "symbol": "GG-TEST",
            "decimals": 6, "supply_atomic": "1000000000000", "production": False})
        names = {a.get("name") for a in artifact["abi"] if a["type"] == "function"}
        self.assertTrue({"transfer", "balanceOf", "approve", "allowance", "transferFrom", "totalSupply", "decimals"} <= names)
        self.assertFalse({"mint", "owner", "upgradeTo", "setTax"} & names)
        self.assertTrue(artifact["bytecode"].startswith("0x"))

    @unittest.skipUnless(NODE and (TOOLCHAIN / "node_modules/solc").is_dir(), "Optional pinned test compiler not installed")
    def test_recompilation_is_identical(self):
        with tempfile.TemporaryDirectory(prefix="gg-token-artifact-") as directory:
            target = Path(directory) / "token.json"
            result = subprocess.run([NODE, str(SOURCE / "compile.mjs"), str(TOOLCHAIN), str(target)],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.assertEqual(result.returncode, 0, "GG_TESTNET_RECOMPILE_FAILED")
            self.assertEqual(target.read_bytes(), (SOURCE / "GGTestToken.json").read_bytes())


@unittest.skipUnless(NODE and CLI.is_file(), "Optional pinned Hardhat toolchain not installed")
class GGTestTokenExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process = None
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cls.url = "http://127.0.0.1:" + str(port)
        shutil.copy2(SOURCE / "hardhat.config.ts", TOOLCHAIN / "hardhat.config.ts")
        allowed = {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT','TEMP','TMP',
                   'USERPROFILE','HOME','LOCALAPPDATA','APPDATA','LANG','LC_ALL'}
        env = {name:value for name,value in os.environ.items() if name.upper() in allowed}
        # Fresh synthetic keys are never printed or written. Hardhat's raw
        # console is intentionally disconnected from all logs and test output.
        env["GG_TESTNET_ACCOUNTS"] = json.dumps([{
            "privateKey": "0x" + secrets.token_hex(32), "balance": "10000000000000000000000"
        } for _ in range(4)])
        env.update(DO_NOT_TRACK="1", HARDHAT_DISABLE_TELEMETRY_PROMPT="true")
        cls.process = subprocess.Popen([NODE, str(CLI), "node", "--config", str(TOOLCHAIN / "hardhat.config.ts"),
            "--network", "ggtest", "--hostname", "127.0.0.1", "--port", str(port)], cwd=TOOLCHAIN,
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        env.pop("GG_TESTNET_ACCOUNTS", None)
        cls.addClassCleanup(cls.stop_node)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise RuntimeError("GG_TESTNET_NODE_EXITED")
            try:
                if cls.rpc("eth_chainId", []) == "0x7a69":
                    cls.accounts = cls.rpc("eth_accounts", [])
                    cls.artifact = json.loads((SOURCE / "GGTestToken.json").read_text(encoding="utf-8"))
                    return
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(.1)
        raise RuntimeError("GG_TESTNET_NODE_START_TIMEOUT")

    @classmethod
    def stop_node(cls):
        if cls.process is not None and cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)

    @classmethod
    def rpc(cls, method, params):
        request = urllib.request.Request(cls.url, data=json.dumps({"jsonrpc": "2.0", "id": 1,
            "method": method, "params": params}).encode("utf-8"), headers={"Content-Type": "application/json"})
        # No proxies or redirects are needed for the owned loopback fixture.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            result = json.loads(response.read(1024 * 1024))
        if "error" in result:
            raise ValueError("GG_TESTNET_RPC_REJECTED")
        return result["result"]

    def setUp(self):
        self.assertEqual(self.rpc("eth_chainId", []), "0x7a69")
        txid = self.rpc("eth_sendTransaction", [{"from": self.accounts[0], "data": self.artifact["bytecode"], "gas": hex(3_000_000)}])
        receipt = self.receipt(txid)
        self.assertEqual(receipt["status"], "0x1")
        self.token = receipt["contractAddress"]

    def receipt(self, txid):
        for _ in range(30):
            result = self.rpc("eth_getTransactionReceipt", [txid])
            if result is not None:
                return result
            time.sleep(.05)
        self.fail("GG_TESTNET_RECEIPT_TIMEOUT")

    @staticmethod
    def address_word(address):
        return address[2:].lower().rjust(64, "0")

    @staticmethod
    def uint_word(amount):
        return format(amount, "064x")

    def call_uint(self, data):
        return int(self.rpc("eth_call", [{"to": self.token, "data": data}, "latest"]), 16)

    def balance(self, index):
        return self.call_uint("0x70a08231" + self.address_word(self.accounts[index]))

    def send(self, index, data):
        txid = self.rpc("eth_sendTransaction", [{"from": self.accounts[index], "to": self.token,
            "data": data, "gas": hex(200_000)}])
        result = self.receipt(txid)
        self.assertEqual(result["status"], "0x1")
        return result

    def test_code_metadata_and_initial_supply(self):
        self.assertEqual(self.rpc("eth_getCode", [self.token, "latest"]), self.artifact["deployedBytecode"])
        self.assertEqual(self.call_uint("0x313ce567"), 6)
        self.assertEqual(self.call_uint("0x18160ddd"), 1_000_000 * 10**6)
        self.assertEqual(self.balance(0), 1_000_000 * 10**6)
        self.assertEqual(self.balance(1), 0)

    def test_exact_transfer_and_return_receipts(self):
        amount = 12_345_678
        out = self.send(0, "0xa9059cbb" + self.address_word(self.accounts[1]) + self.uint_word(amount))
        self.assertEqual(self.balance(1), amount)
        self.assertEqual(self.balance(0), 1_000_000 * 10**6 - amount)
        self.assertEqual(len(out["logs"]), 1)
        self.assertGreater(int(out["gasUsed"], 16), 0)
        self.send(1, "0xa9059cbb" + self.address_word(self.accounts[0]) + self.uint_word(amount))
        self.assertEqual(self.balance(1), 0)
        self.assertEqual(self.balance(0), 1_000_000 * 10**6)

    def test_allowance_is_required_and_consumed(self):
        amount = 123_456
        transfer_from = "0x23b872dd" + self.address_word(self.accounts[0]) + self.address_word(self.accounts[2]) + self.uint_word(amount)
        with self.assertRaises(ValueError):
            self.send(1, transfer_from)
        self.send(0, "0x095ea7b3" + self.address_word(self.accounts[1]) + self.uint_word(amount))
        self.assertEqual(self.call_uint("0xdd62ed3e" + self.address_word(self.accounts[0]) + self.address_word(self.accounts[1])), amount)
        self.send(1, transfer_from)
        self.assertEqual(self.balance(2), amount)
        self.assertEqual(self.call_uint("0xdd62ed3e" + self.address_word(self.accounts[0]) + self.address_word(self.accounts[1])), 0)

    def test_failed_transfers_do_not_change_balances_or_supply(self):
        before = self.balance(0)
        for recipient, amount in [(self.accounts[1], before + 1), ("0x" + "0" * 40, 1)]:
            with self.subTest(recipient_is_zero=recipient.endswith("0" * 40)), self.assertRaises(ValueError):
                self.send(0, "0xa9059cbb" + self.address_word(recipient) + self.uint_word(amount))
        self.assertEqual(self.balance(0), before)
        self.assertEqual(self.call_uint("0x18160ddd"), 1_000_000 * 10**6)

    def test_no_administrator_or_external_mint(self):
        with self.assertRaises(ValueError):
            self.rpc("eth_call", [{"to": self.token, "data": "0x8da5cb5b"}, "latest"])
        with self.assertRaises(ValueError):
            self.send(0, "0x40c10f19" + self.address_word(self.accounts[0]) + self.uint_word(1))
        self.assertEqual(self.call_uint("0x18160ddd"), 1_000_000 * 10**6)


if __name__ == "__main__":
    unittest.main()
