"""Finite, local visual-layout command grammar shared by all chat motors."""

from __future__ import annotations

import shlex
import re
from typing import Any


VISUAL_COMMANDS = (
    "/theme",
    "/profile",
    "/layout",
    "/source",
    "/view",
    "/engine",
    "/extension",
    "/settings",
    "/quickopen",
)

HOST_KINDS = {
    "CODE",
    "TERMINAL",
    "WEB",
    "EXTERNAL",
    "SITE",
    "CRYPTO",
    "MARKETPLACE",
    "TMOG",
    "OSINT",
    "QIP",
    "MEDIA",
    "DRAW",
    "GAME_ENGINE",
    "NODES",
    "FLOW",
    "RESEARCH",
}
ENGINE_TARGETS = {
    "LOCAL_QWEN",
    "GROK_WORKER",
    "GROK_TUI",
    "GPT_TUI",
    "FLOW_TUI",
}
SETTINGS_PAGES = {
    "PROFILES",
    "SURFACES",
    "EDITOR",
    "APPEARANCE",
    "LAYOUT",
    "CHAT",
    "WORKSPACE",
    "ACTIVITY",
    "DEVELOPER",
    "EXTENSIONS",
}
_EXTENSION_ID = re.compile(r"^[a-z][a-z0-9._-]{0,79}$")


def parse_visual_command(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return None
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if not parts or parts[0].lower() not in VISUAL_COMMANDS:
        return None
    command = parts[0].lower()
    args = parts[1:]
    if command == "/theme":
        action = args[0].lower() if args else "list"
        if action not in {"list", "use", "save"}:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VISUAL: /theme list | use ID | save ID"}
        if action in {"use", "save"} and len(args) != 2:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VISUAL: /theme use ID | /theme save ID"}
        return {"handled": True, "valid": True, "command": command,
                "action": action, "id": args[1] if len(args) > 1 else ""}
    if command == "/profile":
        action = args[0].lower() if args else "list"
        if action not in {"list", "use", "save", "reset"}:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VISUAL: /profile list | use ID | save ID | reset"}
        if action in {"use", "save"} and len(args) != 2:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VISUAL: /profile use ID | /profile save ID"}
        return {"handled": True, "valid": True, "command": command,
                "action": action, "id": args[1] if len(args) > 1 else ""}
    if command == "/layout":
        action = args[0].lower() if args else "status"
        if action not in {"lock", "unlock", "reset", "status", "surfaces"}:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VISUAL: /layout lock | unlock | reset | status | surfaces"}
        return {"handled": True, "valid": True, "command": command,
                "action": action}
    if command == "/view":
        if len(args) > 1:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VIEW: /view CODE | TERMINAL | WEB | ..."}
        kind = args[0].upper() if args else "LIST"
        if kind != "LIST" and kind not in HOST_KINDS:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG VIEW: unknown host surface " + kind}
        return {"handled": True, "valid": True, "command": command,
                "action": "list" if kind == "LIST" else "open",
                "kind": "" if kind == "LIST" else kind}
    if command == "/engine":
        if len(args) > 1:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG ENGINE: /engine GROK_TUI | GPT_TUI | FLOW_TUI | ..."}
        target = args[0].upper() if args else "LIST"
        aliases = {"GPTUI": "GPT_TUI", "GROK": "GROK_WORKER", "QWEN": "LOCAL_QWEN"}
        target = aliases.get(target, target)
        if target != "LIST" and target not in ENGINE_TARGETS:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG ENGINE: unknown motor " + target}
        return {"handled": True, "valid": True, "command": command,
                "action": "list" if target == "LIST" else "use",
                "target": "" if target == "LIST" else target}
    if command == "/extension":
        action = args[0].lower() if args else "list"
        if action not in {"list", "enable", "disable"}:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG EXTENSION: /extension list | enable ID | disable ID"}
        if action in {"enable", "disable"}:
            if len(args) != 2 or not _EXTENSION_ID.fullmatch(args[1].lower()):
                return {"handled": True, "valid": False, "command": command,
                        "message": "GG EXTENSION: /extension enable ID | disable ID"}
            extension_id = args[1].lower()
        else:
            if len(args) != 1:
                return {"handled": True, "valid": False, "command": command,
                        "message": "GG EXTENSION: /extension list | enable ID | disable ID"}
            extension_id = ""
        return {"handled": True, "valid": True, "command": command,
                "action": action, "id": extension_id}
    if command == "/settings":
        if len(args) > 1:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG SETTINGS: /settings PAGE"}
        page = args[0].upper() if args else "APPEARANCE"
        if page not in SETTINGS_PAGES:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG SETTINGS: unknown page " + page}
        return {"handled": True, "valid": True, "command": command,
                "action": "open", "page": page}
    if command == "/quickopen":
        if args:
            return {"handled": True, "valid": False, "command": command,
                    "message": "GG QUICK OPEN: /quickopen"}
        return {"handled": True, "valid": True, "command": command,
                "action": "open"}
    # /source always opens one named surface, or closes the current editor.
    if len(args) > 1 or (args and args[0].lower() in {"apply", "save"}):
        return {"handled": True, "valid": False, "command": command,
                "message": "GG VISUAL: /source SURFACE | /source close"}
    surface = args[0] if args else ""
    return {"handled": True, "valid": True, "command": command,
            "action": "close" if surface.lower() == "close" else "open",
            "surface": "" if surface.lower() == "close" else surface}


def command_message(parsed: dict[str, Any]) -> str:
    if not parsed.get("valid"):
        return str(parsed.get("message") or "GG VISUAL: ogiltigt kommando")
    command = str(parsed.get("command") or "")
    action = str(parsed.get("action") or "")
    if command == "/layout":
        return "GG VISUAL: " + action.upper() + " routed to shared layout state."
    if command == "/source":
        return "GG VISUAL: source editor routed to shared settings surface."
    if command == "/view":
        return "GG VIEW: " + (action.upper() if action != "open" else str(parsed.get("kind") or "").upper()) + " routed to workspace."
    if command == "/engine":
        return "GG ENGINE: " + (str(parsed.get("target") or action).upper()) + " routed to chat."
    if command == "/extension":
        return "GG EXTENSION: " + action.upper() + (" " + str(parsed.get("id")) if parsed.get("id") else "") + " routed to registry."
    if command == "/settings":
        return "GG SETTINGS: " + str(parsed.get("page") or "APPEARANCE") + " opened."
    if command == "/quickopen":
        return "GG QUICK OPEN: palette opened."
    return "GG VISUAL: " + command[1:].upper() + " " + action.upper() + " routed to shared state."
