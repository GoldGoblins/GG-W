#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_desk


def _frames() -> dict[str, dict[str, list[float]]]:
    closes = []
    volumes = []
    price = 100.0
    for index in range(180):
        if index % 18 == 0:
            volumes.append(500.0)
            price *= 1.001
        elif index % 18 == 1:
            volumes.append(40.0)
            price *= 1.012
        else:
            volumes.append(80.0 + (index % 5))
            price *= 1.0004
        closes.append(price)
    return {"1h": {"closes": closes, "volumes": volumes}}


def main() -> int:
    empty = crypto_desk.run_desk({})
    assert empty["state"] == "ERROR"
    assert empty["mainnet"] == "NOT_ARMED"

    man = crypto_desk.front_man(
        {"vote": "ATTRACTIVE"},
        {"vote": "SPIKE"},
        {"vote": "SIZE"},
        {"hit": False},
        has_volume=True,
        trades_today=0,
        in_position=False,
        thin=False,
    )
    assert man["light"] == "RED"
    assert "CROWD_SPIKE" in man["reasons"]
    assert man["in_code"] is True

    report = crypto_desk.run_desk(_frames())
    assert report["schema"] == crypto_desk.SCHEMA
    assert report["mode"] == "PAPER_ONLY"
    assert report["orchestration"]["kill_switch"] == "CODE"
    assert report["orchestration"]["model_agents"] is False
    assert report["orchestration"]["cross_talk_during_inference"] is False
    assert report["front_man"]["id"] == "FRONT_MAN"
    ids = {row["id"] for row in report["seats"]}
    assert {"456", "067", "218", "240", "001"} <= ids

    qml = (PROJECT / "qml/components/CryptoSurface.qml").read_text(encoding="utf-8")
    for marker in (
        '"DESK"',
        'text: "PAPER DESK"',
        "cryptoDesk",
        "cryptoDeskReset",
        "FRONT MAN IN CODE",
    ):
        if marker not in qml:
            raise AssertionError("Crypto QML desk marker missing: " + marker)

    host = (PROJECT / "backend/crypto_host.py").read_text(encoding="utf-8")
    bridge = (PROJECT / "backend/chat_surface_host.py").read_text(encoding="utf-8")
    for marker in ("def start_desk", "def reset_desk", '"desk": desk_status()'):
        if marker not in host:
            raise AssertionError("crypto host desk marker missing: " + marker)
    for marker in ("def cryptoDesk", "def cryptoDeskReset"):
        if marker not in bridge:
            raise AssertionError("Qt bridge desk marker missing: " + marker)

    print("test_crypto_desk: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
