#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

PROJECT = Path(__file__).resolve().parents[1]
QML = PROJECT / "qml" / "components" / "ChatActivityEvent.qml"
CONFIG = PROJECT / "config" / "workbench-v1.2.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_event():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML)))
    require(not component.isError(), "ChatActivityEvent.qml failed to load: "
            + "; ".join(err.toString() for err in component.errors()))
    event = component.create()
    require(event is not None, "ChatActivityEvent.qml create failed.")
    event.setParent(engine)
    return app, engine, component, event


def call_json(event, source: str):
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    context = QQmlEngine.contextForObject(event)
    require(context is not None, "QML context missing.")
    expression = QQmlExpression(context, event, source)
    value = expression.evaluate()
    require(not expression.hasError(), "QML expression failed: "
            + str(expression.error()))
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    if hasattr(value, "toString"):
        value = value.toString()
    require(isinstance(value, str), "QML expression did not return string.")
    return value


def parse_rows(event, raw) -> list:
    encoded = json.dumps(raw) if not isinstance(raw, str) else raw
    dumped = call_json(
        event,
        "JSON.stringify(parseStageRows(" + json.dumps(encoded) + "))",
    )
    rows = json.loads(dumped)
    require(isinstance(rows, list), "parseStageRows did not return a list.")
    return rows


def color_of(event, label: str) -> str:
    return call_json(
        event,
        "String(colorForState(" + json.dumps(label) + "))",
    ).lower()


def main() -> int:
    _app, _engine, _component, event = load_event()

    valid = {
        "INTENT": {"state": "RUNNING", "text": "real intent"},
        "RESULT": {"state": "PASS", "text": "real result"},
    }
    valid_rows = parse_rows(event, json.dumps(valid))
    require(
        valid_rows
        == [
            {"phase": "INTENT", "state": "RUNNING", "text": "real intent"},
            {"phase": "RESULT", "state": "PASS", "text": "real result"},
        ],
        "Valid stage object rendering changed.",
    )

    require(parse_rows(event, "null") == [], "Top-level null fabricated rows.")
    require(parse_rows(event, "{") == [], "Malformed JSON fabricated rows.")
    require(
        parse_rows(event, json.dumps({"INTENT": None})) == [],
        "Nested null fabricated a row.",
    )
    require(
        parse_rows(event, json.dumps({"INTENT": "bad"})) == [],
        "Nested string fabricated a row.",
    )
    require(
        parse_rows(event, json.dumps({"INTENT": 123})) == [],
        "Nested number fabricated a row.",
    )
    require(
        parse_rows(event, json.dumps({"INTENT": []})) == [],
        "Nested array fabricated a row.",
    )

    mixed = {
        "INTENT": None,
        "OBSERVE": {"state": "PASS", "text": "kept"},
        "RESULT": "bad",
    }
    mixed_rows = parse_rows(event, json.dumps(mixed))
    require(
        mixed_rows
        == [{"phase": "OBSERVE", "state": "PASS", "text": "kept"}],
        "Mixed payload did not keep only valid objects.",
    )

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    states = cfg["activity"]["states"]
    require(
        states
        == [
            "IDLE",
            "QUEUED",
            "STARTING",
            "RUNNING",
            "STREAMING",
            "GENERATING",
            "WAITING",
            "WAITING_FOR_USER",
            "BLOCKED",
            "STOPPING",
            "PASS",
            "FAIL",
            "CANCELLED",
            "TIMED_OUT",
        ],
        "Canonical activity state set changed.",
    )

    green = "#8db89a"
    red = "#c98989"
    amber = "#c8a97e"
    idle = "#8b949e"
    expected_colors = {
        "PASS": green,
        "FAIL": red,
        "CANCELLED": red,
        "BLOCKED": red,
        "TIMED_OUT": red,
        "QUEUED": amber,
        "STARTING": amber,
        "RUNNING": amber,
        "STREAMING": amber,
        "GENERATING": amber,
        "WAITING": amber,
        "WAITING_FOR_USER": amber,
        "STOPPING": amber,
        "IDLE": idle,
    }
    for label, expected in expected_colors.items():
        actual = color_of(event, label)
        require(
            expected in actual,
            "colorForState mismatch for " + label + ": " + actual,
        )

    print("CHAT_ACTIVITY_EVENT_PARSE_FAIL_CLOSED=PASS")
    print("CHAT_ACTIVITY_EVENT_STATE_COLORS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
