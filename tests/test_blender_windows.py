"""Blender transport and nonblocking EXT regressions; no visible GUI opened."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BlenderTransportTests(unittest.TestCase):
    def test_standard_stdio_negotiates_and_lists_tools(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        result = subprocess.run([sys.executable, "-B", str(ROOT / "gg-blender"), "mcp"],
            input="".join(json.dumps(request) + "\n" for request in requests).encode(),
            capture_output=True, timeout=5, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("exec", {tool["name"] for tool in responses[1]["result"]["tools"]})

    def test_legacy_framing_still_replies_to_existing_bridge(self):
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
        result = subprocess.run([sys.executable, "-B", str(ROOT / "gg-blender")],
            input=(f"Content-Length: {len(request)}\r\n\r\n".encode() + request),
            capture_output=True, timeout=5, cwd=ROOT)
        header, body = result.stdout.split(b"\r\n\r\n", 1)
        self.assertTrue(header.startswith(b"Content-Length:"))
        self.assertEqual(json.loads(body)["id"], 1)

    def test_wrong_arguments_do_not_reach_blender(self):
        from tools.blender import gg_blender_mcp as bridge
        with patch.object(bridge, "sidecar_call") as call:
            result = bridge._call_tool("exec", {"code": "print(1)", "cmd": "clean"})
            self.assertTrue(result["isError"])
            call.assert_not_called()

    def test_unreachable_sidecar_is_reported_as_mcp_error(self):
        from tools.blender import gg_blender_mcp as bridge
        with patch.object(bridge, "sidecar_call", return_value={"ok": False, "error": "OFFLINE"}):
            self.assertTrue(bridge._call_tool("scene", {})["isError"])

    def test_cached_status_never_probes_a_socket(self):
        from backend import blender_contract as contract
        with patch.object(contract, "sidecar_reachable", side_effect=AssertionError("UI socket probe")):
            result = contract.status_payload(probe=False)
            self.assertFalse(result["sidecar_up"])


@unittest.skipUnless(os.name == "nt", "Windows EXT implementation")
class WindowsExtResponsivenessTests(unittest.TestCase):
    def test_slow_sidecar_does_not_block_qt_heartbeat(self):
        from PySide6.QtCore import QCoreApplication, QObject, QTimer
        from backend import windows_blender_embed as embed_module
        app = QCoreApplication.instance() or QCoreApplication([])
        owner = QObject()
        embed = embed_module.WindowsBlenderEmbed(owner)
        beats = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(time.monotonic()))
        timer.start()

        def stalled_probe(*_):
            time.sleep(0.55)
            return {"up": False}

        with patch.object(embed_module, "_probe", side_effect=stalled_probe), \
                patch.object(embed_module.contract, "blender_bin", return_value="fixture-blender"):
            begin = time.monotonic()
            self.assertTrue(embed.start())
            self.assertLess(time.monotonic() - begin, 0.05)
            until = time.monotonic() + 0.7
            while time.monotonic() < until:
                app.processEvents()
                time.sleep(0.001)
            embed.stop()
        timer.stop()
        self.assertGreater(len(beats), 30, "EXT blocked the event loop")
        self.assertLess(max(b-a for a,b in zip(beats, beats[1:])), 0.12)


if __name__ == "__main__":
    unittest.main()
