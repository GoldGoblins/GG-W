"""Bounded Blender desk contract for the EXTERNAL workspace host.

The GAME ENGINE still owns simulation data.  This module only describes the
local Blender binary, the localhost sidecar used by the visual MCP, and a
status payload the EXT surface can show.  It does not grant network, sudo or
standing write authority.
"""

from __future__ import annotations

from backend.application_paths import HOME, STATE_ROOT
from backend.platform_support import find_executable, platform_path

import json
import os
import socket
from pathlib import Path
from typing import Any


SCHEMA = "gg.ai-desktop.blender-status.v1"
SIDECAR_HOST = "127.0.0.1"
SIDECAR_PORT = int(os.environ.get("GG_BLENDER_SIDECAR_PORT", "19876"))
SIDECAR_TIMEOUT_S = 2.0
_SLOW_CMDS = {"inspect": 30.0, "turnaround": 90.0, "deform_rig": 30.0, "clean": 60.0, "exec": 240.0}
SCREENSHOT_PATH = Path(platform_path("/tmp/gg-blender-view.png"))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_SCRIPT = PROJECT_ROOT / "tools" / "blender" / "gg_blender_sidecar.py"
MCP_SCRIPT = PROJECT_ROOT / "tools" / "blender" / "gg_blender_mcp.py"
USER_SCRIPTS = PROJECT_ROOT / "tools" / "blender" / "user-scripts"
CONFIG_DIR = STATE_ROOT / "blender-ext"
SCENE_BLEND = CONFIG_DIR / "gg-village-kit.blend"
# Wayland clients default to wayland-0 when the variable is unset, so a
# dummy name is required to force GHOST onto X11 for the EXT hole.
WAYLAND_BLOCK = "gg-no-wayland"

CANDIDATE_BINS = (
    Path(str(HOME / 'blender-5.2.2-linux-x64/blender')),
    Path(os.environ.get("GG_BLENDER") or ""),
    Path("/usr/bin/blender"),
    Path("/usr/local/bin/blender"),
)


def gui_environment(
    base: dict[str, str] | None = None,
    wayland_socket: str = "",
) -> dict[str, str]:
    """Environment for Blender as an X11 child of the xcb desktop window."""
    env = dict(base if base is not None else os.environ)
    env["BLENDER_USER_CONFIG"] = str(CONFIG_DIR)
    env["BLENDER_USER_SCRIPTS"] = str(USER_SCRIPTS)
    if os.name == "nt":
        env["QT_QPA_PLATFORM"] = "windows"
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
            env.pop(name, None)
        return env
    socket_name = str(wayland_socket or "").strip()
    if socket_name:
        env["WAYLAND_DISPLAY"] = socket_name
        env["XDG_SESSION_TYPE"] = "wayland"
        env.pop("QT_QPA_PLATFORM", None)
        return env
    env["QT_QPA_PLATFORM"] = "xcb"
    env["WAYLAND_DISPLAY"] = WAYLAND_BLOCK
    env["XDG_SESSION_TYPE"] = "x11"
    if not str(env.get("DISPLAY") or "").strip():
        env["DISPLAY"] = ":0"
    return env


def ensure_user_config() -> Path:
    """Keep EXT Blender prefs out of the default user config."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (USER_SCRIPTS / "startup").mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def blender_bin() -> str:
    env = str(os.environ.get("GG_BLENDER") or "").strip()
    if env:
        path = Path(env).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    if os.name == "nt":
        return find_executable("blender")
    for path in CANDIDATE_BINS:
        if not path or not str(path):
            continue
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return ""


def sidecar_reachable() -> bool:
    return sidecar_call("ping", timeout=SIDECAR_TIMEOUT_S).get("ok") is True


def sidecar_call(cmd: str, *, timeout: float | None = None, **fields: Any) -> dict[str, Any]:
    """Send one JSON command to the live Blender sidecar."""
    wanted = str(cmd or "").strip().lower()
    if not wanted:
        return {"ok": False, "error": "BLENDER_CMD_EMPTY"}
    payload = {"cmd": wanted, **fields}
    try:
        encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    except (TypeError, ValueError):
        return {"ok": False, "error": "BLENDER_CMD_NOT_JSON"}
    if len(encoded) > 64 * 1024:
        return {"ok": False, "error": "BLENDER_CMD_TOO_LARGE"}
    try:
        deadline = timeout if timeout is not None else _SLOW_CMDS.get(wanted, 8.0)
        with socket.create_connection((SIDECAR_HOST, SIDECAR_PORT), min(SIDECAR_TIMEOUT_S, deadline)) as sock:
            sock.settimeout(deadline)
            sock.sendall(encoded + b"\n")
            raw = sock.makefile("r", encoding="utf-8").readline(2 * 1024 * 1024 + 1)
    except OSError as exc:
        return {
            "ok": False,
            "error": "BLENDER_SIDECAR_UNREACHABLE",
            "detail": type(exc).__name__,
        }
    if len(raw) > 2 * 1024 * 1024:
        return {"ok": False, "error": "BLENDER_REPLY_TOO_LARGE"}
    try:
        result = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "BLENDER_SIDECAR_BAD_JSON"}
    if not isinstance(result, dict):
        return {"ok": False, "error": "BLENDER_SIDECAR_BAD_PAYLOAD"}
    return result


def status_payload(*, probe: bool = True) -> dict[str, Any]:
    path = blender_bin()
    return {
        "schema": SCHEMA,
        "app": "blender",
        "present": bool(path),
        "path": path,
        "sidecar_script": str(SIDECAR_SCRIPT) if SIDECAR_SCRIPT.is_file() else "",
        "sidecar_host": SIDECAR_HOST,
        "sidecar_port": SIDECAR_PORT,
        "sidecar_up": sidecar_reachable() if path and probe else False,
        "screenshot_path": str(SCREENSHOT_PATH),
        "tokens": ["blender"],
        "detail": (
            "Hosted Blender in EXT. The MCP talks to the live viewport, "
            "not a headless CLI render."
        ),
    }
