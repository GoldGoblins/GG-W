"""Staged real-QML Pump interactions with an offline synthetic Qt proxy."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def run_fixture(staging: Path) -> None:
    import json
    from PySide6.QtCore import QObject, QPointF, QUrl, Qt, Signal, Slot
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    app = QGuiApplication([])
    if os.name == "nt":
        for filename in ("consola.ttf", "consolab.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / filename))
    QFont.insertSubstitution("monospace", "Consolas" if os.name == "nt" else "DejaVu Sans Mono")
    app.setFont(QFont("Consolas" if os.name == "nt" else "DejaVu Sans Mono"))
    app.setQuitOnLastWindowClosed(False)
    mint = "synthetic-token-mint-00000000000000000000001"
    precise = "18446744073709551615"

    class Host(QObject):
        cryptoStatusUpdated = Signal(str)

        def __init__(self):
            super().__init__()
            self.calls = []
            self.status_calls = 0
            self.payload = {"legend": "OBSERVE", "holdings": [{"mint": mint, "symbol": "TEST", "display": "1"}],
                            "wallet": {"pubkey": "synthetic-public-watch-account"}, "ui_operation": {}}

        def raw(self):
            return json.dumps(self.payload)

        def publish(self):
            self.cryptoStatusUpdated.emit(self.raw())
            app.processEvents()

        def start(self, name, *args):
            self.calls.append((name, args))
            self.payload.setdefault("pump", {})["loading"] = True
            self.payload["pump"]["state"] = "loading"
            self.publish()
            return self.raw()

        def finish(self):
            self.payload["pump"]["loading"] = False
            self.payload["pump"]["state"] = "ready"
            self.publish()

        @Slot(result=str)
        def cryptoStatus(self):
            self.status_calls += 1
            return self.raw()

        @Slot(result=str)
        def cryptoRefreshChart(self):
            return self.raw()

        @Slot(str, str, result=str)
        def cryptoPumpInspect(self, selected, pool):
            self.payload["pump"] = {"mint": selected, "pool": pool, "network": "mainnet-beta", "slot": "987654321",
                "fetched_at": "2026-01-01T00:00:00Z", "stale": False,
                "token": {"mint": selected, "decimals": 6, "supply_atoms": precise, "token_program": "SPL Token"},
                "market": {"kind": "Pump AMM", "address": "synthetic-pool", "quote_symbol": "SOL", "lifecycle": "active"},
                "risks": [{"code": "UNVERIFIED", "severity": "high", "label": "<b>Unverified token</b>"}],
                "paper": {"cash_atoms": precise, "quote_symbol": "SOL", "positions": [], "fills": []}}
            return self.start("inspect", selected, pool)

        @Slot(str, str, str, result=str)
        def cryptoPumpQuote(self, side, amount, slippage):
            self.payload["pump"]["quote"] = {"side": side, "supported": True, "amount_in": amount + " SOL",
                "amount_out": "150 TEST", "wallet_debit": "0.1005 SOL", "wallet_credit": "150 TEST",
                "min_out": "148.5 TEST", "max_cost": "0.101 SOL", "price_impact_pct": "0.2",
                "fees": [{"label": "Network", "amount": "0.000005", "symbol": "SOL"}]}
            self.payload["pump"]["stress"] = {"mode": "HYPOTHETICAL COST STRESS", "rows": [
                {"label": "Original quote", "supported": True, "within_slippage": True,
                 "debit_display": "0.1 SOL", "received_display": "150 TEST"},
                {"label": "Adverse price +10%", "supported": True, "within_slippage": False,
                 "debit_display": "0.1 SOL", "received_display": "130 TEST"},
                {"label": "Depth remaining 50%", "supported": False, "within_slippage": False,
                 "error": "PUMP_INSUFFICIENT_REAL_QUOTE"}]}
            return self.start("quote", side, amount, slippage)

        @Slot(result=str)
        def cryptoPumpSimulate(self):
            self.payload["pump"]["simulation"] = {"state": "ok", "units": "100", "fee_lamports": "5000", "wallet": "synthetic-public-watch-account",
                "balance_changes": [{"address": "synthetic-account", "delta_atoms": "-5000", "symbol": "SOL"}],
                "logs": ["<b>synthetic log</b> " + str(i) + "x" * 900 for i in range(150)]}
            return self.start("simulate")

        @Slot(result=str)
        def cryptoPumpPaperTrade(self):
            self.payload["pump"]["paper"] = {"cash_display": "9.8995", "equity_display": "9.9995", "quote_symbol": "SOL",
                "positions": [{"mint": mint, "quantity_display": "150"}],
                "fills": [{"side": "BUY", "mint": mint, "amount_in": "0.1 SOL", "amount_out": "150 TEST"}]}
            return self.start("paper")

        @Slot(result=str)
        def cryptoPumpPaperReset(self):
            self.payload["pump"]["paper"] = {"cash_display": "10", "equity_display": "10", "quote_symbol": "SOL"}
            return self.start("reset")

    host = Host()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty("fixtureHost", host)
    source = '''import QtQuick
import QtQuick.Window
import "components"
Window {
    id: shell; width:1100; height:800; visible:true; color:"#161616"
    property string sharedStatus:"{}"
    readonly property var sharedSnapshot:JSON.parse(sharedStatus)
    Connections { target:fixtureHost; function onCryptoStatusUpdated(raw) { shell.sharedStatus=raw } }
    CryptoSurface { objectName:"fixturePane"; width:shell.width-(rail.visible?220:0); height:shell.height; page:"PUMP"; surfaceHost:fixtureHost }
    WalletPopup { objectName:"fixtureWallet"; visible:false; x:40; y:40; surfaceHost:fixtureHost;
        externallyManagedStatus:true; statusJson:shell.sharedStatus; statusSnapshot:shell.sharedSnapshot }
    TelemetryRail { id:rail; objectName:"fixtureRail"; visible:shell.width>=600; x:shell.width-210; width:200; height:shell.height;
        cryptoStatusJson:shell.sharedStatus; cryptoSnapshot:shell.sharedSnapshot }
}'''
    engine.loadData(source.encode(), QUrl.fromLocalFile(str(staging / "fixture.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    pane = window.findChild(QQuickItem, "fixturePane")
    popup = window.findChild(QQuickItem, "fixtureWallet")
    panel = pane.findChild(QQuickItem, "cryptoPumpPanel")
    assert panel is not None
    QTest.qWait(80)

    def find(name):
        item = window.findChild(QQuickItem, name)
        if item is None:
            pending = list(window.contentItem().childItems())
            while pending:
                candidate = pending.pop()
                if candidate.objectName() == name:
                    item = candidate
                    break
                pending.extend(candidate.childItems())
        assert item is not None, name
        return item

    def evaluate(target, text):
        expression = QQmlExpression(qmlContext(target), target, text)
        result = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        result = result[0] if isinstance(result, tuple) else result
        return result.toVariant() if hasattr(result, "toVariant") else result

    def click(name):
        item = find(name)
        flick = panel.property("contentItem")
        if item is not popup and panel.isAncestorOf(item):
            origin = item.mapToItem(flick.property("contentItem"), QPointF(0, 0))
            flick.setProperty("contentY", max(0, min(origin.y() - 30,
                                flick.property("contentHeight") - flick.height())))
            app.processEvents()
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        assert item.isEnabled() and item.isVisible(), name
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        app.processEvents()

    def capture(name, top=False, at=None):
        destination = os.environ.get("GG_PUMP_UI_PREVIEW")
        if not destination:
            return
        if top:
            panel.property("contentItem").setProperty("contentY", 0)
        if at:
            target = find(at)
            flick = panel.property("contentItem")
            origin = target.mapToItem(flick.property("contentItem"), QPointF(0, 0))
            flick.setProperty("contentY", max(0, min(origin.y(), flick.property("contentHeight") - flick.height())))
        QTest.qWait(80)
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        assert window.grabWindow().save(str(path / (name + ".png")))

    # Missing data remains usable and disables downstream actions.
    assert not find("cryptoPumpQuote").isEnabled()
    assert not find("cryptoPumpSimulate").isEnabled()
    assert not find("cryptoPumpPaperTrade").isEnabled()
    assert not find("cryptoRailPumpState").isVisible()
    find("cryptoPumpMint").setProperty("text", mint)
    click("cryptoPumpInspect")
    assert host.calls[-1] == ("inspect", (mint, ""))
    assert panel.property("busy")
    for name in ("cryptoPumpInspect", "cryptoPumpQuote", "cryptoPumpSimulate", "cryptoPumpPaperTrade", "cryptoPumpPaperReset"):
        assert not find(name).isEnabled(), name
    # Async Pump jobs participate in the shared adaptive status timer.
    timer = pane.findChild(QObject, "cryptoStatusRefreshTimer")
    assert timer.property("interval") == 1000
    host.finish()
    assert precise in find("cryptoPumpTokenState").property("text"), "Atomic quantity lost integer precision"
    assert precise in find("cryptoPumpPaperSummary").property("text")
    assert find("cryptoRailPumpState").isVisible()
    capture("pump-wide", top=True)
    find("cryptoPumpAmount").setProperty("text", "0.000000001")
    find("cryptoPumpSlippage").setProperty("text", "175")
    click("cryptoPumpQuote")
    assert host.calls[-1] == ("quote", ("BUY", "0.000000001", "175"))
    host.finish()
    assert panel.property("currentQuote")
    assert find("cryptoPumpStressCard").isVisible()
    assert "SOL SOL" not in find("cryptoPumpQuoteDetails").property("text")
    assert "150 TEST" in find("cryptoPumpQuoteDetails").property("text")
    capture("pump-quote")
    capture("pump-stress", at="cryptoPumpStressCard")
    click("cryptoPumpSimulate")
    assert host.calls[-1][0] == "simulate"
    host.finish()
    assert "synthe…ccount" in find("cryptoPumpSimulationWallet").property("text")
    logs = find("cryptoPumpSimulationLogs")
    assert len(logs.property("text").splitlines()) == 80
    assert max(map(len, logs.property("text").splitlines())) <= 600
    assert evaluate(logs, "textFormat === TextEdit.PlainText")
    click("cryptoPumpPaperTrade")
    assert host.calls[-1][0] == "paper"
    host.finish()
    assert "9.8995 SOL" in find("cryptoPumpPaperSummary").property("text")
    capture("pump-paper")
    assert not panel.property("currentQuote"), "A filled quote remained executable"
    click("cryptoPumpPaperReset")
    assert host.calls[-1][0] == "reset"
    host.finish()
    # Changed inputs, stale data, unsupported and failed quotes cannot be executed.
    click("cryptoPumpQuote")
    host.finish()
    find("cryptoPumpSide").setProperty("currentIndex", 1)
    assert not find("cryptoPumpSimulate").isEnabled()
    assert not find("cryptoPumpStressCard").isVisible()
    click("cryptoPumpQuote")
    assert host.calls[-1][1][0] == "SELL"
    host.finish()
    host.payload["pump"]["stale"] = True
    host.publish()
    assert not find("cryptoPumpQuote").isEnabled()
    assert not find("cryptoPumpPaperTrade").isEnabled()
    assert "STALE" in find("cryptoPumpProvenance").property("text")
    host.payload["pump"].update(stale=False, state="error", error="OFFLINE_FIXTURE")
    host.publish()
    assert "OFFLINE_FIXTURE" in find("cryptoPumpError").property("text")
    assert not find("cryptoPumpQuote").isEnabled()
    host.payload["pump"].update(state="ready", error="")
    host.payload["pump"]["quote"].update(supported=False, error="UNSUPPORTED_FIXTURE")
    host.publish()
    assert not find("cryptoPumpSimulate").isEnabled()
    assert not find("cryptoPumpPaperTrade").isEnabled()

    # A narrow view keeps fields and actions within the scrolling viewport.
    window.setWidth(430)
    window.setHeight(620)
    QTest.qWait(180)
    assert pane.property("compactSidebar")
    assert panel.width() > 300, (window.width(), pane.width(), panel.width())
    capture("pump-narrow", top=True)
    for name in ("cryptoPumpMint", "cryptoPumpPool", "cryptoPumpAmount", "cryptoPumpSlippage", "cryptoPumpInspect", "cryptoPumpQuote", "cryptoPumpSimulate", "cryptoPumpPaperTrade"):
        item = find(name)
        assert item.width() <= panel.width(), (name, item.width(), panel.width())
        assert item.mapToItem(panel, QPointF(0, 0)).x() >= 0, name
    # Editing retains exact text, standard selection and keyboard tab navigation.
    field = find("cryptoPumpMint")
    field.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Tab)
    assert find("cryptoPumpPool").hasActiveFocus()
    assert field.property("selectByMouse")
    # The existing Factory scroll shows historical uncertainty without changing controls.
    quality = {"bootstrap": {"available": True, "sample_count": 120, "block_size": 5, "replicas": 128,
        "observed": {"total_return": 0.15, "max_drawdown": 0.08},
        "intervals": {"total_return": {"lower": -0.125, "median": 0.1, "upper": 0.25},
                      "max_drawdown": {"lower": 0.02, "median": 0.08, "upper": 0.3}},
        "limits": ["Synthetic historical sample; not a forecast."]},
        "causality": {"passed": True, "checks": [{"kind": "prefix"}], "limits": []}}
    host.payload["strategy_factory"] = {"research_quality": quality}
    pane.setProperty("page", "FACTORY")
    host.publish()
    QTest.qWait(180)
    card = find("cryptoFactoryResearchQuality")
    assert card.isVisible()
    assert "PASS" in find("cryptoFactoryPrefixAudit").property("text")
    assert "-12.50% to 25.00%" in find("cryptoFactoryBootstrapRanges").property("text")
    assert "2.00% to 30.00%" in find("cryptoFactoryBootstrapRanges").property("text")
    assert "120" in find("cryptoFactoryBootstrapSamples").property("text")
    assert card.width() <= pane.width() and card.width() > 0
    assert evaluate(find("cryptoFactoryBootstrapRanges"), "textFormat === Text.PlainText")
    quality["bootstrap"].update(available=False, reason="<b>INSUFFICIENT_RETURNS</b>", intervals=None)
    quality["causality"]["passed"] = False
    host.publish()
    assert "FAILED" in find("cryptoFactoryPrefixAudit").property("text")
    unavailable = find("cryptoFactoryBootstrapRanges").property("text")
    assert "<b>INSUFFICIENT_RETURNS</b>" in unavailable and "0.00%" not in unavailable
    quality["causality"]["passed"] = None
    host.publish()
    assert "UNKNOWN" in find("cryptoFactoryPrefixAudit").property("text")
    # Hidden/background panes stop the shared timer and never call the network themselves.
    pane.setVisible(False)
    calls_before = host.status_calls
    QTest.qWait(1150)
    assert host.status_calls == calls_before

    # Wallet Inspect uses the same host API and preserves its external status binding.
    window.setWidth(1100)
    window.setHeight(800)
    popup.setVisible(True)
    QTest.qWait(20)
    click("walletPumpInspect")
    assert host.calls[-1] == ("inspect", (mint, ""))
    host.finish()
    assert mint in find("walletPumpSelection").property("text")
    host.payload["pump"]["error"] = "WALLET_OFFLINE_FIXTURE"
    host.publish()
    assert "WALLET_OFFLINE_FIXTURE" in find("walletPumpSelection").property("text")
    capture("pump-wallet")
    assert not warnings, warnings
    print(json.dumps({"status": "PASS", "real_qml": True, "synthetic_proxy_calls": len(host.calls),
                      "narrow_width": 430, "bounded_log_rows": 80, "warnings": len(warnings)}))
    window.close()
    engine.deleteLater()
    app.processEvents()


class CryptoPumpUiTests(unittest.TestCase):
    def test_staged_real_qml_offline_interactions_and_layout(self):
        with tempfile.TemporaryDirectory(prefix="gg-pump-ui-") as temporary:
            staging = Path(temporary)
            shutil.copytree(PROJECT / "qml/components", staging / "components",
                            ignore=shutil.ignore_patterns("__pycache__"))
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic",
                       GG_DESKTOP_STATE_ROOT=str(staging / "state"), GG_DESKTOP_DATA_ROOT=str(staging / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fixture", str(staging)],
                                    cwd=staging, env=env, capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        run_fixture(Path(sys.argv[2]))
    else:
        unittest.main()
