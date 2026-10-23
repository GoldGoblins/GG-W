#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import blender_contract
    from backend.surface_intent import parse_surface_intent

    payload = blender_contract.status_payload()
    if payload.get("schema") != blender_contract.SCHEMA:
        raise AssertionError("blender schema")
    if payload.get("app") != "blender":
        raise AssertionError("blender app id")
    if payload.get("sidecar_port") != blender_contract.SIDECAR_PORT:
        raise AssertionError("sidecar port")
    if blender_contract.SIDECAR_HOST != "127.0.0.1":
        raise AssertionError("sidecar must be localhost")
    if not blender_contract.SIDECAR_SCRIPT.is_file():
        raise AssertionError("sidecar script missing")
    if not blender_contract.MCP_SCRIPT.is_file():
        raise AssertionError("mcp script missing")

    qml = (PROJECT / "qml" / "components" / "ExternalSurface.qml").read_text(
        encoding="utf-8"
    )
    if 'objectName: "workspaceExternalHole"' not in qml:
        raise AssertionError("external hole missing")
    if "externalStart" not in qml:
        raise AssertionError("external start missing")
    if "root.openBlender()" not in qml:
        raise AssertionError("EXT must retry Blender attach while the pane is open")
    if "WaylandCompositor" in qml or "override_redirect" in qml:
        raise AssertionError("EXT must not use overlay or nested compositor")

    host = (PROJECT / "backend" / "chat_surface_host.py").read_text(encoding="utf-8")
    if "def externalStart" not in host or "def hideExternal" not in host:
        raise AssertionError("external host slots missing")
    if "def externalSetHole" not in host:
        raise AssertionError("external hole geometry slot missing")

    embed = (PROJECT / "backend" / "blender_embed.py").read_text(encoding="utf-8")
    if "/bin/sh" in embed or "bash -c" in embed:
        raise AssertionError("generic shell in blender embed")
    if "gui_environment" not in embed:
        raise AssertionError("blender embed must use the X11 child environment")
    if "Qt.Tool" in embed or "override_redirect" in embed:
        raise AssertionError("EXT must not use a Tool/overlay window")
    if "setParent" not in embed or "fromWinId" not in embed:
        raise AssertionError("EXT must parent Blender as a child of the desktop window")
    if "sidecar_reachable" not in embed or "_adopt_existing" not in embed:
        raise AssertionError("EXT must reuse a live sidecar Blender")
    if "_x11_tree_xids" not in embed or "_sidecar_pids" not in embed:
        raise AssertionError("EXT must find withdrawn sidecar Blender windows")
    if "BLENDER_SIDECAR_ALREADY_RUNNING" in embed:
        raise AssertionError("EXT must not black-hole when the sidecar is live")
    if "SCENE_BLEND" not in embed:
        raise AssertionError("EXT must reopen the village kit blend")
    kit = PROJECT / "tools/blender/build_gg_village_kit.py"
    if not kit.is_file() or "def build(" not in kit.read_text(encoding="utf-8"):
        raise AssertionError("village kit builder missing")
    if blender_contract.gui_environment().get("WAYLAND_DISPLAY") != blender_contract.WAYLAND_BLOCK:
        raise AssertionError("blender client must use X11 under the xcb host")
    main_src = (PROJECT / "main.py").read_text(encoding="utf-8")
    if 'QT_QPA_PLATFORM", "xcb"' not in main_src:
        raise AssertionError("desktop host must run as xcb for child embed")

    workspace = (PROJECT / "qml" / "components" / "WorkspaceSurface.qml").read_text(
        encoding="utf-8"
    )
    if "ExternalSurface" not in workspace:
        raise AssertionError("EXT pane missing ExternalSurface")
    if "HOSTING NOT AVAILABLE" in workspace:
        raise AssertionError("EXT still shows the old placeholder")
    if 'active: !root.settingsOpen && root.hostKind === "EXTERNAL"' in workspace:
        raise AssertionError("EXT loader must stay alive across tab switches")

    if parse_surface_intent("blender") != "EXTERNAL":
        raise AssertionError("blender intent")
    if parse_surface_intent("öppna blender") != "EXTERNAL":
        raise AssertionError("open blender intent")

    down = blender_contract.sidecar_call("ping")
    if down.get("ok") is True:
        # A live sidecar is fine; a false ok without a listener is not.
        pass
    elif down.get("error") != "BLENDER_SIDECAR_UNREACHABLE":
        raise AssertionError("expected unreachable sidecar, got " + json.dumps(down))

    proc = subprocess.Popen(
        [sys.executable, str(blender_contract.MCP_SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT),
    )

    def send(message: dict) -> None:
        raw = json.dumps(message).encode("utf-8")
        proc.stdin.write(
            f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw
        )
        proc.stdin.flush()

    def read() -> dict:
        headers: dict[str, str] = {}
        while True:
            line = proc.stdout.readline().decode("utf-8")
            if line in ("\r\n", "\n"):
                break
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length = int(headers["content-length"])
        return json.loads(proc.stdout.read(length))

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
        )
        init = read()
        if init["result"]["serverInfo"]["name"] != "gg-blender":
            raise AssertionError("mcp server name")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {row["name"] for row in read()["result"]["tools"]}
        if names != {"status", "scene", "screenshot", "exec", "export_glb", "inspect", "turnaround", "deform_rig", "clean"}:
            raise AssertionError("mcp tools " + str(names))
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "status", "arguments": {}},
            }
        )
        status_text = read()["result"]["content"][0]["text"]
        if blender_contract.SCHEMA not in status_text:
            raise AssertionError("mcp status schema")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("BLENDER_PRESENT=" + str(bool(payload.get("present"))))
    print("BLENDER_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
