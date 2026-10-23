#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import thought_desk
from backend.omni_gpt_profiles import build_context


def main() -> int:
    talk = thought_desk.sit("hejsan")
    assert talk["schema"] == thought_desk.SCHEMA
    assert talk["parallel_agent_brain"] == "FORBIDDEN"
    assert talk["model_agents"] is False
    assert talk["front_man"]["in_code"] is True
    assert talk["verifier_context"] == "FRESH"
    assert talk["diamond"]["verify"] == "TEST"
    assert talk["expected_seats"] == talk["got_seats"]
    assert talk["seats"]["builder"]["mode"] == "TALK"
    assert talk["seats"]["memory"]["id"] == "MEMORY"
    assert "MEMORY hits=" in talk["text"]
    assert "SAME_TASK_DESK" in talk["text"]

    linear = thought_desk.sit(
        "fixa header.php sen deploy till one.com och wp-admin"
    )
    assert linear["front_man"]["light"] in {"HOLD", "SPLIT"}
    assert "RED_EFFECT" in linear["front_man"]["reasons"] or linear["seats"]["risk"]["light"] == "RED"
    assert "LINEAR_TRAP" in linear["seats"]["critic"]["flags"]
    assert linear["loops"] >= 1
    assert linear["loops"] <= thought_desk.MAX_LOOPS

    parallel = thought_desk.sit(
        "koda crypto_desk.py och testa test_crypto_desk.py"
    )
    assert parallel["seats"]["intent"]["work"] is True
    assert parallel["seats"]["builder"]["mode"] in {"PARALLEL", "ONE"}
    assert parallel["front_man"]["parallel_agent_brain"] == "FORBIDDEN"

    compact = build_context(
        "Jag har en idé om en GPT och vill förstå vad jag menar",
        max_chars=2200,
        include_registry=False,
    )
    assert "[SAME_TASK_DESK]" in compact
    assert "parallel_agent_brain=FORBIDDEN" in compact
    assert "[/GG OMNIGPT PROFILE LAYER]" in compact
    assert len(compact) <= 2200

    print("test_thought_desk: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
