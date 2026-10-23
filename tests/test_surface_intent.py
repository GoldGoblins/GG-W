from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.surface_intent import parse_surface_intent
    from backend.grok_worker_contract import (
        hash_workspace_identity,
        resolve_workspace_surface,
    )
    from backend.chat_context_compiler import compile_chat_prompt

    assert parse_surface_intent("öppna terminalen") == "TERMINAL"
    assert parse_surface_intent("visa koden") == "CODE"
    assert parse_surface_intent("öppna webben") == "WEB"
    assert parse_surface_intent("öppna coden") == "CODE"
    assert parse_surface_intent("öppna programmet") == "EXTERNAL"
    assert parse_surface_intent("öppna hemsidan") == "SITE"
    assert parse_surface_intent("site") == "SITE"
    assert parse_surface_intent("tmog") == "TMOG"
    assert parse_surface_intent("öppna tmog") == "TMOG"
    assert parse_surface_intent("osint") == "OSINT"
    assert parse_surface_intent("osiris") == "OSINT"
    assert parse_surface_intent("öppna osirisai") == "OSINT"
    assert parse_surface_intent("visa intelligence") == "OSINT"
    assert parse_surface_intent("qip") == "QIP"
    assert parse_surface_intent("öppna wasm") == "QIP"
    assert parse_surface_intent("öppna research") == "RESEARCH"
    assert parse_surface_intent("visa ghidra") == "RESEARCH"
    assert parse_surface_intent("rea") == "RESEARCH"
    assert parse_surface_intent("game engine") == "GAME_ENGINE"
    assert parse_surface_intent("öppna spelmotorn") == "GAME_ENGINE"
    assert parse_surface_intent("nodes") == "NODES"
    assert parse_surface_intent("öppna noder") == "NODES"
    assert parse_surface_intent("game") == "MEDIA"
    assert parse_surface_intent("öppna game") == "MEDIA"
    assert parse_surface_intent("marketplace") == "MARKETPLACE"
    assert parse_surface_intent("öppna marketplace") == "MARKETPLACE"
    assert parse_surface_intent("nft") == "MARKETPLACE"
    assert parse_surface_intent("musik") == "MEDIA"
    assert parse_surface_intent("öppna radion") == "MEDIA"
    assert parse_surface_intent("öppna emulatorn") == "MEDIA"
    assert parse_surface_intent("draw") == "DRAW"
    assert parse_surface_intent("öppna gimp") == "DRAW"
    assert parse_surface_intent("blender") == "EXTERNAL"
    assert parse_surface_intent("öppna blender") == "EXTERNAL"
    assert parse_surface_intent("terminal") == "TERMINAL"
    assert parse_surface_intent("Hej") == ""
    assert parse_surface_intent("läs main.py") == ""
    long_prompt = (
        "Terminalruta Kör echo hello world i terminalen. "
        "Visa resultatet i terminalrutan i chatten, inte bara som text. "
        + ("x" * 40)
    )
    assert parse_surface_intent(long_prompt) == ""

    ident = hash_workspace_identity("ws.terminal.user")
    assert ident["object_id"] == "ws.terminal.user"
    assert ident["object_type"] == "USER_TERMINAL"
    assert ident["sha256"] == ""
    surface = resolve_workspace_surface("ws.terminal.user")
    assert "no file bytes" in str(surface["body"])
    prompt = compile_chat_prompt("hej", "@current", surface)
    assert "LASER_IDENTITY" in prompt
    assert "hej" in prompt
    print("SURFACE_INTENT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
