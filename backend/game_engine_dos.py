"""Bounded command grammar for the GAME ENGINE's DOS presentation.

The terminal surface is an alternate input/output skin, not an alternate
simulation.  This module only tokenizes and validates a small command
language.  The runtime maps the resulting commands to existing canonical
movement, item, NPC, crafting, persistence and presentation operations; it
never evaluates shell text or arbitrary scripts.
"""

from __future__ import annotations

import shlex
from typing import Any


SCHEMA = "gg.game-engine.dos.v1"
VERSION = 1
MAX_COMMAND_LENGTH = 96
MAX_ARGUMENTS = 6
MAX_ARGUMENT_LENGTH = 48
MAX_HISTORY = 16
MAX_MOVE_STEPS = 12

COMMANDS = (
    "HELP",
    "STATUS",
    "LOOK",
    "PLAY",
    "PAUSE",
    "STEP",
    "MOVE",
    "TURN",
    "JUMP",
    "MODE",
    "INTERACT",
    "PICKUP",
    "OPEN",
    "LOOT",
    "EQUIP",
    "DROP",
    "NPC",
    "TALK",
    "PACK",
    "EVENTS",
    "ATTACK",
    "QUESTS",
    "ACCEPT",
    "CLAIM",
    "TRADE",
    "BUY",
    "SELL",
    "CRAFT",
    "GEARCRAFT",
    "SAVE",
    "LOAD",
    "DOS",
    "3D",
    "RETRY",
    "BURST",
)

_ALIASES = {
    "?": "HELP",
    "H": "HELP",
    "L": "LOOK",
    "W": "MOVE",
    "PICK": "PICKUP",
    "USE": "INTERACT",
    "GEAR_CRAFT": "GEARCRAFT",
    "RICH": "3D",
}
_DIRECTIONS = {
    "W": "FORWARD",
    "FORWARD": "FORWARD",
    "UP": "FORWARD",
    "S": "BACK",
    "BACK": "BACK",
    "DOWN": "BACK",
    "Q": "LEFT",
    "LEFT": "LEFT",
    "A": "LEFT",
    "E": "RIGHT",
    "RIGHT": "RIGHT",
    "D": "RIGHT",
}
_MODES = {"GROUND", "SWIM", "FLY"}
_TARGET_COMMANDS = {"PICKUP", "OPEN", "LOOT", "EQUIP", "DROP"}


def _text(value: Any, default: str = "", limit: int = MAX_ARGUMENT_LENGTH) -> str:
    return str(value or default).strip()[:limit]


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _error(raw: str, message: str, usage: str = "") -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "ok": False,
        "input": _text(raw, limit=MAX_COMMAND_LENGTH),
        "command": "",
        "args": [],
        "error": _text(message, "DOS_COMMAND_INVALID", 96),
        "usage": _text(usage, limit=96),
    }


def parse(raw: Any) -> dict[str, Any]:
    """Parse one bounded command without executing it."""
    source = str(raw or "").strip()
    if not source:
        return _error(source, "DOS_COMMAND_EMPTY", "HELP")
    if len(source) > MAX_COMMAND_LENGTH:
        return _error(source, "DOS_COMMAND_TOO_LONG", "96 characters maximum")
    try:
        tokens = shlex.split(source, posix=True)
    except ValueError:
        return _error(source, "DOS_COMMAND_QUOTES_INVALID")
    if not tokens:
        return _error(source, "DOS_COMMAND_EMPTY", "HELP")
    if len(tokens) > MAX_ARGUMENTS + 1:
        return _error(source, "DOS_COMMAND_TOO_MANY_ARGUMENTS")
    command = _ALIASES.get(str(tokens[0]).upper(), str(tokens[0]).upper())
    if command not in COMMANDS:
        return _error(source, "DOS_COMMAND_UNKNOWN", "HELP")
    args = [str(token).strip()[:MAX_ARGUMENT_LENGTH] for token in tokens[1:]]

    if command in {"HELP", "STATUS", "LOOK", "PLAY", "PAUSE", "STEP", "INTERACT", "NPC", "QUESTS", "EVENTS", "SAVE", "LOAD", "DOS", "3D", "RETRY", "BURST"}:
        if args:
            return _error(source, "DOS_COMMAND_ARGUMENTS_INVALID", command)
    elif command in {"MOVE", "TURN"}:
        if not args:
            return _error(source, "DOS_DIRECTION_REQUIRED", f"{command} W 1")
        direction = _DIRECTIONS.get(args[0].upper())
        if direction is None:
            return _error(source, "DOS_DIRECTION_INVALID", f"{command} W 1")
        if len(args) > 2:
            return _error(source, "DOS_COMMAND_ARGUMENTS_INVALID", f"{command} W 1")
        requested_steps = _safe_int(args[1], 1) if len(args) == 2 else 1
        if requested_steps < 1:
            return _error(source, "DOS_STEP_COUNT_INVALID", f"{command} W 1")
        steps = min(MAX_MOVE_STEPS, requested_steps)
        args = [direction, str(steps)]
    elif command == "JUMP":
        if args:
            return _error(source, "DOS_COMMAND_ARGUMENTS_INVALID", "JUMP")
    elif command == "MODE":
        if len(args) != 1 or args[0].upper() not in _MODES:
            return _error(source, "DOS_MOVEMENT_MODE_INVALID", "MODE GROUND|SWIM|FLY")
        args = [args[0].upper()]
    elif command in _TARGET_COMMANDS:
        if len(args) > 1:
            return _error(source, "DOS_TARGET_ARGUMENT_INVALID", f"{command} [instance-id]")
    elif command == "TRADE":
        if len(args) not in {2, 3} or any(not value for value in args):
            return _error(
                source,
                "DOS_TRADE_ARGUMENT_INVALID",
                "TRADE [npc-id] give-instance receive-instance",
            )
        if len(args) == 2:
            args = ["", args[0], args[1]]
    elif command in {"BUY", "SELL"}:
        if len(args) not in {1, 2} or any(not value for value in args):
            return _error(
                source,
                "DOS_VENDOR_ARGUMENT_INVALID",
                f"{command} [vendor-id] instance-id",
            )
        if len(args) == 1:
            args = ["", args[0]]
    elif command == "CRAFT":
        if len(args) > 1:
            return _error(source, "DOS_RECIPE_ARGUMENT_INVALID", "CRAFT [recipe-id]")
    elif command == "GEARCRAFT":
        if len(args) > 2:
            return _error(source, "DOS_RECIPE_ARGUMENT_INVALID", "GEARCRAFT [recipe-id] [station-id]")
    elif command == "TALK":
        if len(args) > 2:
            return _error(source, "DOS_TALK_ARGUMENT_INVALID", "TALK [npc-id] [choice-id]")
    elif command == "PACK":
        if len(args) > 1:
            return _error(source, "DOS_PACK_ARGUMENT_INVALID", "PACK [pack-id]")
    elif command in {"ATTACK", "ACCEPT", "CLAIM"}:
        if len(args) > 1:
            return _error(source, "DOS_TARGET_ARGUMENT_INVALID", f"{command} [id]")

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "ok": True,
        "input": source[:MAX_COMMAND_LENGTH],
        "command": command,
        "args": args,
    }


def record(
    parsed: dict[str, Any],
    *,
    ok: bool,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one bounded presentation/input history row."""
    details_copy = dict(details) if isinstance(details, dict) else {}
    error = _text(
        parsed.get("error") if not ok else details_copy.get("error"),
        "",
        96,
    )
    return {
        "input": _text(parsed.get("input"), limit=MAX_COMMAND_LENGTH),
        "command": _text(parsed.get("command"), "", 32).upper(),
        "args": [
            _text(value, limit=MAX_ARGUMENT_LENGTH)
            for value in parsed.get("args", [])[:MAX_ARGUMENTS]
        ],
        "ok": bool(ok),
        "message": _text(message, "DOS_COMMAND", 128),
        "error": error,
        "details": details_copy,
    }


def history_view(history: Any, last: Any = None) -> dict[str, Any]:
    """Expose bounded command history to QML and the fallback renderer."""
    rows = history if isinstance(history, list) else []
    safe_rows = [row for row in rows[-MAX_HISTORY:] if isinstance(row, dict)]
    last_row = last if isinstance(last, dict) else {}
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "commands": safe_rows,
        "count": len(safe_rows),
        "last": dict(last_row),
        "grammar": "BOUNDED_NO_SHELL_NO_SCRIPT",
        "allowed": list(COMMANDS),
    }


def help_lines() -> list[str]:
    return [
        "HELP STATUS LOOK PLAY PAUSE STEP",
        "MOVE W|S|Q|E [1-12]  TURN A|D [1-12]",
        "JUMP  MODE GROUND|SWIM|FLY",
        "INTERACT PICKUP OPEN LOOT EQUIP DROP NPC TALK ATTACK QUESTS ACCEPT CLAIM",
        "TRADE [npc-id] give-instance receive-instance",
        "BUY|SELL [vendor-id] instance-id",
        "CRAFT [recipe]  GEARCRAFT [recipe] [station]",
        "PACK [pack-id]  EVENTS",
        "SAVE LOAD DOS 3D RETRY  BURST",
    ]
