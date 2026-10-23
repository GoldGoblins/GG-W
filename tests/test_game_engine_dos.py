"""Regression for the bounded DOS command grammar and canonical dispatch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_dos as dos
    from backend import game_engine_fallback as fallback
    from backend.game_engine_host import GameEngineRuntime

    parsed = dos.parse("MOVE W 999")
    assert parsed["ok"] is True
    assert parsed["command"] == "MOVE"
    assert parsed["args"] == ["FORWARD", "12"]
    assert dos.parse("MOVE W; STATUS")["ok"] is False
    assert dos.parse("UNKNOWN")["error"] == "DOS_COMMAND_UNKNOWN"
    assert len(dos.help_lines()) >= 3

    direct = fallback.build_view(
        [],
        [],
        command=dos.record(
            dos.parse("HELP"),
            ok=True,
            message="DOS command grammar ready.",
        ),
    )
    assert any(line.startswith("> HELP") for line in direct["terminal"]["lines"])

    runtime = GameEngineRuntime()
    try:
        initial = runtime.snapshot()
        before = (initial["player"]["x"], initial["player"]["z"])
        moved = runtime.dos_command("MOVE W 3")
        after = (moved["player"]["x"], moved["player"]["z"])
        assert moved["dos_command"]["ok"] is True
        assert moved["dos_command"]["command"] == "MOVE"
        assert moved["dos_command"]["details"]["steps"] == 3
        assert before != after
        assert moved["state"] == "PAUSED"
        assert any(
            row["kind"] == "DOS_MOVE" and row["actor_id"] == "player"
            for row in moved["event_journal"]["events"]
        )
        terminal = moved["render"]["fallback"]["terminal"]["lines"]
        assert any(line.startswith("> MOVE W 3") for line in terminal)

        stable = json.dumps(moved["player"], sort_keys=True)
        invalid = runtime.dos_command("rm -rf world")
        assert invalid["dos_command"]["ok"] is False
        assert invalid["dos_command"]["error"] == "DOS_COMMAND_UNKNOWN"
        assert json.dumps(invalid["player"], sort_keys=True) == stable

        help_view = runtime.dos_command("HELP")
        assert help_view["dos"]["last"]["command"] == "HELP"
        assert len(help_view["dos"]["last"]["details"]["lines"]) >= 3

        swim = runtime.dos_command("MODE SWIM")
        assert swim["player"]["movement_mode"] == "SWIM"
        dos_view = runtime.dos_command("DOS")
        assert dos_view["render"]["presentation"]["mode"] == "DOS_2D"
        rich_view = runtime.dos_command("RETRY")
        assert rich_view["render"]["presentation"]["mode"] == "RICH_3D"
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_DOS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
