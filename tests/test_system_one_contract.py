#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.system_one_contract import (
        BACKEND_LOCAL,
        SCHEMA,
        SystemOneError,
        decide_turn,
        evaluate,
        format_compact,
    )

    ticket = evaluate(
        "Help! My payouts have been failing for 3 days.",
        {
            "is_urgent": {
                "type": "noul",
                "instructions": "Does this convey urgency?",
            },
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "Payments, invoicing, refunds",
                    "technical": "Bugs, outages, integrations",
                    "sales": "Pricing, upgrades, new accounts",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "How severe is the issue?",
                "criteria": {
                    "0": "Noise",
                    "1": "Annoying",
                    "2": "Blocking money",
                    "3": "Outage",
                },
            },
        },
    )
    assert ticket["schema"] == SCHEMA
    assert ticket["backend"] == BACKEND_LOCAL
    assert ticket["authority"] == "NONE"
    assert ticket["network"] == "NONE"
    assert ticket["latency_ms"] < 50
    assert ticket["answers"]["is_urgent"]["type"] == "noul"
    assert 0.0 <= float(ticket["answers"]["is_urgent"]["noul"]) <= 1.0
    assert ticket["answers"]["department"]["choice"] in {
        "billing",
        "technical",
        "sales",
    }
    assert abs(sum(ticket["answers"]["department"]["probs"].values()) - 1.0) < 0.02

    blender = decide_turn("öppna blender i EXT och bygg hyddan")
    assert blender["answers"]["surface"]["choice"] == "EXTERNAL"
    assert blender["answers"]["task_kind"]["choice"] in {"operate", "code"}
    assert blender["answers"]["motor_hint"]["choice"] in {"GROK", "EITHER"}
    compact = format_compact(blender)
    assert compact.startswith("[GG SYSTEM ONE]")
    assert "authority=NONE" in compact
    assert "surface=EXTERNAL" in compact
    assert "next_worker=" in compact
    assert "split=LLM_WRITES SYSTEM_ONE_DECIDES CODE_EXECUTES" in compact

    chat = decide_turn("hej, hur är läget?")
    assert chat["answers"]["task_kind"]["choice"] == "chat"
    assert float(chat["answers"]["needs_write"]["noul"]) < 0.4

    write = decide_turn("fixa QML-filen och applicera patchen")
    assert write["answers"]["task_kind"]["choice"] == "code"
    assert float(write["answers"]["needs_write"]["noul"]) > 0.2

    try:
        evaluate("state", {})
    except SystemOneError:
        pass
    else:
        raise AssertionError("empty questions must fail closed")

    first = evaluate("same state", {"ok": {"type": "noul", "instructions": "Is this ok?"}})
    second = evaluate(
        "same state", {"ok": {"type": "noul", "instructions": "Is this ok?"}}
    )
    assert first["answers"] == second["answers"]

    from backend.system_one_contract import keep_drop, handoff_packet

    live = decide_turn("öppna blender", available_surfaces=("EXTERNAL", "CODE"))
    assert live["answers"]["surface"]["choice"] == "EXTERNAL"
    assert live["answers"]["next_worker"]["choice"] == "operate"
    assert live["split"] == "LLM_WRITES SYSTEM_ONE_DECIDES CODE_EXECUTES"
    assert live["verifier"] == "TEST"
    assert live["handoff"]["authority"] == "NONE"
    assert live["handoff"]["execute"] == "MOTOR"
    packet = handoff_packet("öppna blender", live)
    assert packet["next_worker"] == "operate"
    kept = keep_drop(
        "fixa QML",
        {"qml": "QML layout and desktop chrome", "crypto": "wallet trading"},
        threshold=0.2,
    )
    assert "qml" in kept
    print("SYSTEM_ONE_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
