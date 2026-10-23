#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import draw_contract
    from backend.surface_intent import parse_surface_intent

    payload = draw_contract.status_payload()
    if payload.get("schema") != draw_contract.SCHEMA:
        raise AssertionError("draw schema")
    ids = [row["id"] for row in payload["editors"]]
    for name in ("krita", "gimp", "inkscape", "darktable", "kolourpaint"):
        if name not in ids:
            raise AssertionError("editor missing " + name)
    if not payload.get("sketch"):
        raise AssertionError("sketch fallback missing")
    if draw_contract.default_editor_id() not in ids + ["sketch"]:
        raise AssertionError("default editor")
    qml = (PROJECT / "qml" / "components" / "DrawSurface.qml").read_text(
        encoding="utf-8"
    )
    if 'leftLegend: "DRAW"' in qml:
        raise AssertionError("draw pane still nests a DRAW GgFrame inside the workspace frame")
    if 'objectName: "workspaceDrawHole"' not in qml:
        raise AssertionError("draw hole missing")
    if "drawStart" not in qml or "SKETCH" not in qml:
        raise AssertionError("draw editor switch missing")
    host = (PROJECT / "backend" / "chat_surface_host.py").read_text(encoding="utf-8")
    if "def drawStart" not in host or "def hideDraw" not in host:
        raise AssertionError("draw host slots missing")
    embed = (PROJECT / "backend" / "draw_embed.py").read_text(encoding="utf-8")
    if "/bin/sh" in embed or "bash -c" in embed:
        raise AssertionError("generic shell in draw embed")
    if parse_surface_intent("draw") != "DRAW":
        raise AssertionError("draw intent")
    if parse_surface_intent("öppna gimp") != "DRAW":
        raise AssertionError("gimp intent")
    present = [row for row in payload["editors"] if row.get("present")]
    print("DRAW_EDITORS=" + json.dumps([row["id"] for row in present]))
    print("DRAW_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
