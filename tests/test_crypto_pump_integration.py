"""Real PumpResearch -> real QML field contracts, using only offline RPC fixtures."""
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
    import socket
    import time
    from unittest.mock import patch

    sys.path.insert(0, str(PROJECT))
    sys.path.insert(0, str(PROJECT / "tests"))
    from test_crypto_pump_runtime import MINT, PAYER, ProtocolRPC
    from backend import crypto_contract as contract
    from backend import crypto_pump as pump
    from backend import crypto_pump_accounts as accounts
    from PySide6.QtCore import QObject, QUrl, Signal, Slot
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name == "nt":
        for filename in ("consola.ttf", "consolab.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / filename))
    font = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"
    QFont.insertSubstitution("monospace", font)
    app.setFont(QFont(font))
    rpc = ProtocolRPC()
    service = pump.PumpResearch(rpc, clock=lambda: 1000.0)

    class Proxy(QObject):
        """A thin Qt boundary; every Pump field comes from the actual service."""
        cryptoStatusUpdated = Signal(str)

        def __init__(self):
            super().__init__()
            self.wallet = PAYER

        def payload(self):
            service.bind_wallet(self.wallet, "mainnet")
            return {"pump": service.snapshot(refresh=False)}

        def raw(self):
            return json.dumps(self.payload(), allow_nan=False)

        def publish(self):
            self.cryptoStatusUpdated.emit(self.raw())
            app.processEvents()

        @Slot(str, str, result=str)
        def cryptoPumpInspect(self, mint, pool):
            service.inspect(mint, pool)
            return self.raw()

        @Slot(str, str, str, result=str)
        def cryptoPumpQuote(self, side, amount, slippage):
            service.quote(side, amount, slippage)
            return self.raw()

        @Slot(result=str)
        def cryptoPumpSimulate(self):
            service.simulate(self.wallet, wallet_network="mainnet")
            return self.raw()

        @Slot(result=str)
        def cryptoPumpPaperTrade(self):
            service.paper_trade()
            return self.raw()

    proxy = Proxy()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty("fixtureProxy", proxy)
    source = '''import QtQuick
import QtQuick.Window
import "components"
Window {
    id: shell; width:430; height:760; visible:true; color:"#161616"
    property string fullStatus:"{}"
    Connections { target:fixtureProxy; function onCryptoStatusUpdated(raw) { shell.fullStatus=raw } }
    CryptoPumpPanel { objectName:"integrationPanel"; anchors.fill:parent; anchors.margins:12;
        surfaceHost:fixtureProxy; snapshot:JSON.parse(shell.fullStatus).pump || ({});
        onStatusReturned:function(raw) { shell.fullStatus=raw } }
}'''
    state_dir = staging / "private-state"
    try:
        # The service is allowed to persist only this isolated paper account.
        # Any accidental real transport fails before leaving the process.
        with patch.object(contract, "STATE_DIR", state_dir), \
             patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden in Pump integration")), \
             patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden in Pump integration")):
            engine.loadData(source.encode(), QUrl.fromLocalFile(str(staging / "integration.qml")))
            assert engine.rootObjects(), warnings
            window = engine.rootObjects()[0]
            panel = window.findChild(QQuickItem, "integrationPanel")
            assert panel is not None

            def items():
                pending = list(window.contentItem().childItems())
                found = []
                while pending:
                    item = pending.pop()
                    found.append(item)
                    pending.extend(item.childItems())
                return found

            def find(name):
                item = next((item for item in items() if item.objectName() == name), None)
                assert item is not None, name
                return item

            def texts():
                return "\n".join(str(item.property("text")) for item in items()
                    if item.isVisible() and item.property("text") is not None)

            def run(action):
                expression = QQmlExpression(qmlContext(panel), panel, 'run("' + action + '")')
                expression.evaluate()
                assert not expression.hasError(), expression.error().toString()
                app.processEvents()

            def state():
                return json.loads(window.property("fullStatus"))["pump"]

            find("cryptoPumpMint").setProperty("text", MINT)
            run("inspect")
            deadline = time.monotonic() + 3
            while service._running and time.monotonic() < deadline:
                QTest.qWait(2)
            proxy.publish()
            ready = state()
            assert ready["state"] == "ready", ready.get("error")
            token_text = find("cryptoPumpTokenState").property("text")
            assert MINT in token_text and ready["market"]["address"] in token_text
            assert "Decimals: 6" in token_text and ready["token"]["supply_display"] in token_text
            assert ready["fetched_at_text"] in find("cryptoPumpProvenance").property("text")

            find("cryptoPumpAmount").setProperty("text", "0.1")
            find("cryptoPumpSlippage").setProperty("text", "100")
            run("quote")
            quoted = state()
            quote = quoted["quote"]
            assert quote["supported"] and panel.property("currentQuote")
            assert find("cryptoPumpSimulate").isEnabled() and find("cryptoPumpPaperTrade").isEnabled()
            details = find("cryptoPumpQuoteDetails").property("text")
            for label, key in (("Input: ", "amount_in"), ("Output: ", "amount_out"),
                               ("Wallet debit: ", "wallet_debit"), ("Wallet credit: ", "wallet_credit"),
                               ("Minimum received: ", "min_out"), ("Maximum cost: ", "max_cost")):
                assert label + quote[key] in details, (label, quote[key], details)
            assert "SOL SOL" not in details
            for fee in quote["fees"]:
                assert fee["label"] + ": " + fee["amount"] + " " + fee["symbol"] in texts(), fee
            assert find("cryptoPumpStressCard").isVisible()

            run("simulate")
            simulated = state()["simulation"]
            assert simulated["state"] == "ok" and simulated["wallet"] == PAYER
            assert "5000 lamports" in find("cryptoPumpSimulationState").property("text")
            assert PAYER[:6] + "…" + PAYER[-6:] in find("cryptoPumpSimulationWallet").property("text")
            for change in simulated["balance_changes"]:
                assert change["address"] in texts(), change
                assert change["delta_display"] in texts(), change
            assert "-0.000005 SOL" in texts(), "Lamports were displayed as decimal SOL"
            assert "\n".join(simulated["logs"]) == find("cryptoPumpSimulationLogs").property("text")
            # The actual binding operation discards the old public payer's report.
            proxy.wallet = accounts.USDC_MINT
            proxy.publish()
            assert state()["simulation"] == {}
            assert not find("cryptoPumpSimulationWallet").isVisible()
            assert "-0.000005 SOL" not in texts()

            run("paper")
            filled = state()
            paper = filled["paper"]
            assert len(paper["fills"]) == 1 and len(paper["positions"]) == 1
            fill, position = paper["fills"][0], paper["positions"][0]
            visible_text = texts()
            assert fill["mint"] == MINT and fill["mint"] in visible_text
            for key in ("timestamp", "amount_in", "amount_out"):
                assert fill[key] in visible_text, (key, fill[key])
            assert position["quantity_display"] in visible_text
            assert "Value: " + position["value"] in visible_text
            summary = find("cryptoPumpPaperSummary").property("text")
            assert paper["cash_display"] in summary and paper["equity_display"] in summary
            assert not panel.property("currentQuote")
            assert not find("cryptoPumpPaperTrade").isEnabled()
            assert {path.name for path in state_dir.iterdir()} == {"pump-paper-v1.json"}
            assert {call[0] for call in rpc.calls} <= {
                "getMultipleAccounts", "getAccountInfo", "getEpochInfo", "getLatestBlockhash",
                "getFeeForMessage", "simulateTransaction"}
            QTest.qWait(30)
            assert not warnings, warnings
            print(json.dumps({"status": "PASS", "actual_pump_service": True, "actual_field_contracts": True,
                "unsigned_offline_simulation": True, "real_paper_fill": True, "width": 430,
                "rpc_fixture_calls": len(rpc.calls), "qml_warnings": len(warnings)}))
            window.close()
    finally:
        service.close()
        engine.deleteLater()
        app.processEvents()


class CryptoPumpIntegrationTests(unittest.TestCase):
    def test_actual_service_outputs_in_staged_qml(self):
        with tempfile.TemporaryDirectory(prefix="gg-pump-integration-") as temporary:
            staging = Path(temporary)
            shutil.copytree(PROJECT / "qml/components", staging / "components",
                            ignore=shutil.ignore_patterns("__pycache__"))
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic",
                       GG_DESKTOP_STATE_ROOT=str(staging / "state"), GG_DESKTOP_DATA_ROOT=str(staging / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fixture", str(staging)],
                                    cwd=staging, env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        run_fixture(Path(sys.argv[2]))
    else:
        unittest.main()
