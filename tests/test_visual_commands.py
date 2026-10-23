from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend.visual_commands import parse_visual_command


def check(raw: str, **expected: object) -> None:
    value = parse_visual_command(raw)
    assert value is not None, raw
    assert value["valid"] is True, (raw, value)
    for key, wanted in expected.items():
        assert value.get(key) == wanted, (raw, key, value)


check("/view crypto", command="/view", action="open", kind="CRYPTO")
check("/view", command="/view", action="list")
check("/engine GPTUI", command="/engine", action="use", target="GPT_TUI")
check("/extension disable gg.surface.osint", command="/extension", action="disable", id="gg.surface.osint")
check("/settings extensions", command="/settings", action="open", page="EXTENSIONS")
check("/quickopen", command="/quickopen", action="open")

for invalid in (
    "/view not-a-surface",
    "/engine unknown",
    "/extension disable ../unsafe",
    "/settings unknown",
    "/quickopen extra",
):
    value = parse_visual_command(invalid)
    assert value is not None and value["valid"] is False, invalid

print("Shared workbench slash-command contract PASS")
