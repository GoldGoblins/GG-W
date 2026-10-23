#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import kaspa_contract, kaspa_covenant


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gg-kaspa-"))
    kaspa_contract.STATE_DIR = tmp

    snap = kaspa_covenant.snapshot()
    if snap["legend"] != "PAPER":
        raise AssertionError("default network is not paper")
    if snap["mainnet_armed"] is not False:
        raise AssertionError("mainnet must start disarmed")

    observe = kaspa_covenant.set_network("mainnet")
    if observe.get("error"):
        raise AssertionError("mainnet observe should not error")
    if observe.get("legend") != "OBSERVE" or observe.get("mainnet_observe") is not True:
        raise AssertionError("mainnet should be observe-only")
    born_on_observe = kaspa_covenant.genesis()
    if int(born_on_observe["count"]) != 0:
        raise AssertionError("paper genesis must still run while observing mainnet")
    kaspa_covenant.set_network("paper")

    born = kaspa_covenant.genesis()
    if int(born["count"]) != 0:
        raise AssertionError("genesis count")
    if not str(born["covenant_id"]):
        raise AssertionError("genesis covenant id")
    first_addr = str(born["address"])
    if not first_addr.startswith("paper:"):
        raise AssertionError("paper address prefix")

    added = kaspa_covenant.transition("add", 5)
    if int(added["count"]) != 5:
        raise AssertionError("add did not advance count")
    if str(added["address"]) == first_addr:
        raise AssertionError("address must change with state")
    if str(added["covenant_id"]) != str(born["covenant_id"]):
        raise AssertionError("covenant id must stay")

    sub = kaspa_covenant.transition("subtract", 3)
    if int(sub["count"]) != 2:
        raise AssertionError("subtract")
    try:
        kaspa_covenant.transition("subtract", 9)
        raise AssertionError("overdraft must fail")
    except ValueError as exc:
        if str(exc) != "KASPA_COUNT":
            raise

    src = (PROJECT / "kaspa" / "counter.sil").read_text(encoding="utf-8")
    if "#[covenant(binding = auth" not in src:
        raise AssertionError("counter.sil missing auth singleton")
    if "entry " in src and "function add" not in src:
        raise AssertionError("counter.sil should use covenant functions")

    host = (PROJECT / "backend" / "crypto_host.py").read_text(encoding="utf-8")
    if "kaspa_covenant.snapshot()" not in host:
        raise AssertionError("crypto_host missing kaspa snapshot")
    if "KASUSDT" not in host or "def set_portfolio_asset" not in host:
        raise AssertionError("SOL and KAS must share one portfolio tape")
    if "CRYPTO_KLINE_SYMBOL" not in host:
        raise AssertionError("kline symbol guard missing")
    slots = (PROJECT / "backend" / "chat_surface_host.py").read_text(encoding="utf-8")
    if "def cryptoSetPortfolioAsset" not in slots or "def cryptoRefreshKasChart" not in slots:
        raise AssertionError("portfolio asset slot missing")
    try:
        from backend import crypto_host

        crypto_host.fetch_klines("15m", 8, symbol="BTCUSDT")
        raise AssertionError("foreign kline symbol must fail closed")
    except RuntimeError as exc:
        if "CRYPTO_KLINE_SYMBOL" not in str(exc):
            raise
    qml = (PROJECT / "qml" / "components" / "CryptoSurface.qml").read_text(
        encoding="utf-8"
    )
    if '"KASPA"' not in qml:
        raise AssertionError("CryptoSurface missing KASPA wallet")
    if 'visible: root.page === "KASPA"' in qml:
        raise AssertionError("Kaspa must live on the portfolio, not its own page")
    if "pickAsset" not in qml or "kas_chart" not in qml:
        raise AssertionError("currency switch missing")
    if "sidebarCollapsed" not in qml or "function navIcon" not in qml:
        raise AssertionError("crypto chrome should match TMOG/OSINT sidebar")
    if "function menuKids" not in qml or "function pickChild" not in qml:
        raise AssertionError("crypto nav missing accordion children")
    if '"SCAN"' not in qml or "Strategy004" not in qml:
        raise AssertionError("crypto submenu entries missing")
    if "Kaspa TN" not in qml:
        raise AssertionError("kaspa submenu must not reuse SOL testnet")
    popup = (PROJECT / "qml" / "components" / "WalletPopup.qml").read_text(
        encoding="utf-8"
    )
    if "RECEIVE" not in popup or "cryptoSetNetwork" not in popup:
        raise AssertionError("wallet popup missing phantom-style account actions")
    main = (PROJECT / "qml" / "Main.qml").read_text(encoding="utf-8")
    if "walletOpen" not in main or "WalletPopup" not in main:
        raise AssertionError("top bar wallet chip must open a popup")
    if "walletDragBar" not in popup or "drag.target" not in popup:
        raise AssertionError("wallet popup must drag from the title bar")
    print("test_kaspa_covenant: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
