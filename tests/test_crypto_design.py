"""Offline real-QML regression checks for CRYPTO navigation and holdings UX."""
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
    from PySide6.QtCore import QObject, QPoint, QPointF, QUrl, Qt, Signal, Slot
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QWheelEvent
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name == "nt":
        for font_file in ("consola.ttf", "consolab.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / font_file))
    family = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"
    QFont.insertSubstitution("monospace", family)
    app.setFont(QFont(family))
    mint = "synthetic-token-mint-00000000000000000000001"
    exact_quantity = "18446744073709551615.000000001"

    class Host(QObject):
        cryptoStatusUpdated = Signal(str)

        def __init__(self):
            super().__init__()
            self.calls = []
            self.status_calls = 0
            chart = {"closes": [100, 101, 99, 102], "times": [1700000000 + i * 3600 for i in range(4)],
                     "interval": "1h", "actual_interval": "1h", "requested_interval": "1h", "source": "synthetic", "stale": False}
            assets = [
                {"symbol": "SOL", "name": "Solana", "mint": "native", "quantity_text": "0", "value_usd": 0, "price_usd": 102},
                {"symbol": "ZED", "name": "Synthetic inspectable", "mint": mint, "quantity_text": exact_quantity, "value_usd": 20, "price_usd": 1},
                {"symbol": "ALFA", "name": "Alpha fixture", "mint": "synthetic-alpha", "quantity_text": "10", "value_usd": 10, "price_usd": 1},
                {"symbol": "UNKNOWN", "name": "Missing quote", "mint": "synthetic-unknown", "quantity_text": "5", "value_usd": None, "price_usd": None},
            ]
            summary = {"assets": assets, "value_usd": 30, "price_usd": 102, "valued_count": 3,
                       "unpriced_count": 1, "complete": False, "change_24h_pct": None}
            self.payload = {"legend": "TESTNET", "wallet": {"pubkey": "synthetic-public-watch-account", "balance_sol": "0", "network": "testnet"},
                            "portfolio": {"asset": "SOL", "sol": summary, "kas": {"assets": [], "value_usd": None, "price_usd": None}},
                            "chart": chart, "kas_chart": chart, "ui_operation": {},
                            "holdings": [{"mint": mint, "symbol": "ZED", "display": exact_quantity}],
                            "trader": {"book": "gg", "backtest": {"book": "gg", "ran_at": "2026-10-25T10:00:00Z", "chart": chart}}}

        def raw(self):
            return json.dumps(self.payload)

        def publish(self):
            self.cryptoStatusUpdated.emit(self.raw())
            app.processEvents()

        @Slot(result=str)
        def cryptoStatus(self):
            self.status_calls += 1
            return self.raw()

        @Slot(result=str)
        def cryptoRefreshChart(self):
            self.calls.append(("chart",))
            return self.raw()

        @Slot(result=str)
        def cryptoRefreshKasChart(self):
            self.calls.append(("kas_chart",))
            return self.raw()

        @Slot(str, result=str)
        def cryptoSetChartInterval(self, interval):
            self.calls.append(("interval", interval))
            self.payload["chart"].update(interval=interval, actual_interval=interval, requested_interval=interval)
            return self.raw()

        @Slot(str, str, result=str)
        def cryptoPumpInspect(self, selected, pool):
            self.calls.append(("inspect", selected, pool))
            self.payload["pump"] = {"mint": selected, "state": "ready", "stale": False, "token": {"mint": selected}}
            return self.raw()

        @Slot(str, result=str)
        def cryptoSetNetwork(self, network):
            self.calls.append(('sol_network',network)); self.payload['wallet']['network']=network
            return self.raw()

        @Slot(str, result=str)
        def cryptoKaspaSetNetwork(self, network):
            self.calls.append(('kas_network',network)); self.payload['kaspa']={'network':network}
            return self.raw()

        @Slot(result=str)
        def cryptoLabOn(self):
            self.calls.append(('sol_lab_on',)); return self.raw()

        @Slot(result=str)
        def cryptoLabOff(self):
            self.calls.append(('sol_lab_off',)); return self.raw()

        @Slot(result=str)
        def cryptoKaspaLabOn(self):
            self.calls.append(('kas_lab_on',)); return self.raw()

        @Slot(result=str)
        def cryptoKaspaLabOff(self):
            self.calls.append(('kas_lab_off',)); return self.raw()

    host = Host()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty("fixtureHost", host)
    engine.loadData(b'''import QtQuick
import QtQuick.Window
import "components"
Window { id:shell; width:1100; height:780; visible:true
    CryptoSurface { objectName:"fixturePane"; anchors.fill:parent; anchors.margins:16; surfaceHost:fixtureHost }
    Item { objectName:"fixtureStyleProbe"; anchors.fill:parent; z:100
        CryptoButton { objectName:"cryptoStyleButton"; x:20; y:20; width:140; text:"PROBE" }
        WalletPopup { objectName:"fixtureWallet"; x:190; y:20; visualWidth:330; visualHeight:650
            surfaceHost:fixtureHost; statusJson:fixtureHost.cryptoStatus()
        }
    }
}''', QUrl.fromLocalFile(str(staging / "fixture.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    pane = window.findChild(QQuickItem, "fixturePane")
    QTest.qWait(60)

    def items():
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            yield item
            pending.extend(item.childItems())

    def find(name):
        found = window.findChild(QObject, name) or next((item for item in items() if item.objectName() == name), None)
        assert found is not None, name
        return found

    def evaluate(target, source):
        expression = QQmlExpression(qmlContext(target), target, source)
        result = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        result = result[0] if isinstance(result, tuple) else result
        return result.toVariant() if hasattr(result, "toVariant") else result

    def click(item):
        if isinstance(item, str):
            item = find(item)
        assert item.isEnabled() and item.isVisible(), item.objectName()
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (item.objectName(), point)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        app.processEvents()

    def holdings():
        return next(item for item in items() if item.metaObject().className().startswith("CryptoHoldings_"))

    def symbols():
        return evaluate(holdings(), "visibleAssets.map(function(row) { return row.symbol })")

    def summary():
        return next(item for item in items() if item.metaObject().className().startswith("CryptoPortfolioSummary_"))

    def type_text(value):
        for character in value:
            QTest.keyClick(window, Qt.Key(ord(character.upper())))
        app.processEvents()

    # Resolve native control states: primary actions and keyboard focus keep the
    # app's neutral chrome, with a small cool-gray selection tint permitted.
    probe = find("cryptoStyleButton")
    point = probe.mapToScene(QPointF(probe.width() / 2, probe.height() / 2)).toPoint()

    def neutral_background(state, target=probe):
        color = evaluate(target, "background.color")
        border = evaluate(target, "background.border.color")
        channels = (color.red(), color.green(), color.blue())
        assert color.alpha() == 0 or max(channels) - min(channels) <= 10, (state, color.name())
        assert border.alpha() == 0 or border.red() == border.green() == border.blue(), (state, border.name())
        return color, border

    resting, resting_border = neutral_background("normal")
    probe.setProperty("primary", True)
    primary, _ = neutral_background("primary")
    assert primary == resting, "Primary action introduced a filled accent background"
    probe.setProperty("checked", True)
    neutral_background("checked")
    probe.setProperty("checked", False)
    QTest.mouseMove(window, point)
    app.processEvents()
    assert probe.property("hovered"), "Hover state was not exercised"
    neutral_background("hover")
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    assert probe.property("down"), "Pressed state was not exercised"
    neutral_background("pressed")
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseMove(window, QPoint(window.width() - 2, window.height() - 2))
    pane.forceActiveFocus(Qt.OtherFocusReason)
    probe.forceActiveFocus(Qt.TabFocusReason)
    app.processEvents()
    assert probe.property("visualFocus"), "Keyboard focus state was not exercised"
    _, focused_border = neutral_background("focus")
    assert focused_border.lightness() > resting_border.lightness(), "Keyboard focus has no visible outline"
    probe.setEnabled(False)
    neutral_background("disabled")
    assert evaluate(probe, "background.opacity") < 1, "Disabled state lost its visual distinction"
    probe.setEnabled(True)
    probe.setProperty("flat", True)
    probe.setProperty("checked", True)
    neutral_background("flat selected")
    wallet = find("fixtureWallet")
    wallet_primary = [item for item in items() if wallet.isAncestorOf(item) and item.property("primary")]
    assert len(wallet_primary) >= 2, "Wallet primary controls were not exercised"
    for button in wallet_primary:
        neutral_background("wallet primary: " + button.property("text"), button)
    find("fixtureStyleProbe").setVisible(False)

    # Portfolio sections reuse the desktop's framed, floating-legend component.
    chart = find("cryptoPortfolioChart")
    for section in (summary(), chart):
        frames = [item for item in items() if section.isAncestorOf(item)
                  and item.metaObject().className().startswith("GgFrame_") and item.property("leftLegend")]
        assert frames, (section.objectName(), "Missing shared frame and legend")
        assert all(frame.width() > 0 and frame.height() > 0 for frame in frames), "Collapsed section frame"

    # Native navigation works with real mouse/key delivery and persistent selection.
    click("cryptoNavTRADER")
    assert pane.property("page") == "TRADER"
    click("cryptoNavPORTFOLIO")
    assert pane.property("page") == "PORTFOLIO"
    click("cryptoNavPORTFOLIO")
    active_nav_stays_selected = find("cryptoNavPORTFOLIO").property("checked")
    find("cryptoNavTRADER").forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Space)
    app.processEvents()
    assert pane.property("page") == "TRADER"
    pane.setProperty("page", "PORTFOLIO")
    click("cryptoNavigationToggle")
    QTest.qWait(180)
    assert pane.property("compactSidebar")
    click("cryptoNavigationToggle")
    QTest.qWait(180)
    assert not pane.property("compactSidebar")

    # Sorting keeps missing values last; filter matches mint/name/symbol and Escape clears.
    assert symbols() == ["SOL", "ZED", "ALFA", "UNKNOWN"]
    click("cryptoHoldingsValueSort")
    assert symbols() == ["ZED", "ALFA", "SOL", "UNKNOWN"]
    click("cryptoHoldingsNameSort")
    assert symbols() == ["ALFA", "SOL", "UNKNOWN", "ZED"]
    search = find("cryptoHoldingsSearch")
    search.forceActiveFocus()
    type_text("missing quote")
    app.processEvents()
    assert symbols() == ["UNKNOWN"]
    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert len(symbols()) == 4 and search.property("text") == ""
    type_text("synthetic-token-mint")
    app.processEvents()
    assert symbols() == ["ZED"]
    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()

    # Unknown prices remain unknown, and the full quantity survives in the tooltip.
    unknown = [item for item in items() if item.property("text") == "Pris saknas" and item.isVisible()]
    assert unknown
    assert "TESTNET" in summary().property("mode")
    host.payload["wallet"]["balance_sol"] = 0
    host.publish()
    assert summary().property("quantity") == "0", "Known zero balance must remain a known zero"
    host.payload["wallet"]["balance_sol"] = None
    host.publish()
    assert not summary().property("quantityKnown"), "Unknown balance must not appear as zero"
    host.payload["wallet"]["balance_sol"] = "0"
    host.publish()
    click("cryptoAssetKAS")
    assert pane.property("asset") == "KAS"
    assert not summary().property("quantityKnown"), "Unknown KAS balance must not appear as zero"
    click("cryptoAssetSOL")
    assert pane.property("asset") == "SOL"
    click("cryptoInterval4h")
    assert pane.property("activeTf") == "4h"
    assert find("cryptoInterval4h").property("checked")

    # Selecting a wallet token runs the same inspection API and preselects the mint.
    search.forceActiveFocus()
    type_text("synthetic-token-mint")
    app.processEvents()
    listing = find("cryptoHoldingsList")
    evaluate(listing, "forceLayout()")
    row = evaluate(listing, "itemAtIndex(0)")
    assert exact_quantity in evaluate(row, "rowTip.text"), "Full token quantity lost precision"
    click(row)
    assert host.calls[-1] == ("inspect", mint, "")
    assert pane.property("page") == "PUMP"
    selected_mint = find("cryptoPumpMint")
    inspect_route_selected_mint = selected_mint.property("text") == mint
    pane.setProperty("page", "PORTFOLIO")
    host.payload["ui_operation"] = {"state": "running", "name": "fixture"}
    host.publish()
    assert not holdings().property("tokenInspectionEnabled")
    prior = len(host.calls)
    row = evaluate(find("cryptoHoldingsList"), "itemAtIndex(0)")
    click(row)
    assert len(host.calls) == prior and pane.property("page") == "PORTFOLIO"
    pane.setProperty("page", "TRADER")
    app.processEvents()
    paper_actions = [item for item in items() if item.metaObject().indexOfProperty("down") >= 0
                     and item.property("text") in ("STARTA ALLA SEX", "PAUSA ALLA")]
    assert len(paper_actions) == 2 and all(not item.isEnabled() for item in paper_actions), "Paper account actions ignored the shared busy state"
    for button in paper_actions:
        neutral_background("paper busy: " + button.property("text"), button)
    host.payload["ui_operation"] = {}
    host.publish()
    for button in paper_actions:
        neutral_background("paper ready: " + button.property("text"), button)

    # At 430px including outer margins, all common action buttons fit the page.
    window.setWidth(430)
    window.setHeight(620)
    pane.setProperty("walletToolsOpen", True)
    QTest.qWait(200)
    violations = []
    for page in ("PORTFOLIO", "BACKTEST", "TRADER", "PUMP", "SIGNAL", "ARB", "ACTIVITY", "FACTORY", "DESK", "POLY"):
        pane.setProperty("page", page)
        QTest.qWait(30)
        preview = os.environ.get("GG_CRYPTO_DESIGN_PREVIEW")
        if preview:
            QTest.qWait(60)
            Path(preview).mkdir(parents=True, exist_ok=True)
            assert window.grabWindow().save(str(Path(preview) / (page.lower() + "-430.png")))
        for item in items():
            if not item.isVisible() or item.metaObject().indexOfProperty("primary") < 0:
                continue
            point = item.mapToItem(pane, QPointF(0, 0))
            if point.x() < -0.5 or point.x() + item.width() > pane.width() + 0.5:
                violations.append({"page": page, "text": item.property("text"), "x": round(point.x(), 1),
                                   "width": round(item.width(), 1), "pane_width": pane.width()})
    assert not violations, json.dumps(violations)
    assert active_nav_stays_selected, "Clicking active navigation removed its selected state"
    assert inspect_route_selected_mint, "Holdings inspection did not preselect the Pump mint"
    pane.setProperty("page", "PORTFOLIO")
    for total_height in (620, 650):
        window.setHeight(total_height)
        for tools_open in (False, True):
            pane.setProperty("walletToolsOpen", tools_open)
            QTest.qWait(30)
            header = find("cryptoPortfolioHeader")
            chart = find("cryptoPortfolioChart")
            bottom = find("cryptoPortfolioBottom")
            listing = find("cryptoHoldingsList")
            geometry = {"window_height": total_height, "wallet_open": tools_open,
                        "header_height": header.height(), "chart_height": chart.height(),
                        "bottom_height": bottom.height(), "list_height": listing.height()}
            assert chart.y() >= header.y() + header.height(), geometry
            assert bottom.y() >= chart.y() + chart.height(), geometry
            assert listing.height() >= 62, geometry
            tools = find("cryptoWalletTools")
            assert not tools_open or tools.height() >= 30, geometry

    # Long comparison details scroll independently while the price chart stays usable.
    window.setHeight(620)
    host.payload["trader"]["backtest"].update(
        comparison=[{"book": "synthetic-" + str(index), "name": "Synthetic strategy with a descriptive research label " + str(index),
                     "return_pct": 12.3, "return_token_equivalent_pct": 11.2, "max_drawdown_pct": 8.1,
                     "holdout": {"return_pct": -3.2}} for index in range(6)],
        cost_model={"per_leg_bps": 35},
        benchmarks={"buy_and_hold": {"return_pct": 8}, "simple_dca": {"return_pct": 5}},
        range="SCROLL_END_FIXTURE", data={"source": "offline synthetic comparison"})
    pane.setProperty("page", "BACKTEST")
    host.publish()
    QTest.qWait(50)
    details = find("cryptoBacktestDetails")
    chart = find("cryptoPortfolioChart")
    assert details.property("contentHeight") > details.height(), "Long comparison was not scrollable"
    assert chart.height() >= 100, {"chart_height": chart.height(), "details_height": details.height()}
    assert chart.y() >= details.y() + details.height(), "Comparison overlapped the chart"
    center = details.mapToScene(QPointF(details.width() / 2, details.height() / 2))
    screen = window.mapToGlobal(center.toPoint())
    for _ in range(3):
        wheel = QWheelEvent(center, QPointF(screen), QPoint(0, 0), QPoint(0, -120 * 64),
                            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        app.sendEvent(window, wheel)
        QTest.qWait(50)
    QTest.qWait(300)
    limit = details.property("contentHeight") - details.height()
    assert details.property("contentY") >= limit - 1, {"content_y": details.property("contentY"), "bottom": limit}
    last_text = next(item for item in items() if item.isVisible() and details.isAncestorOf(item)
                     and "SCROLL_END_FIXTURE" in str(item.property("text") or ""))
    final_line_bottom = last_text.mapToItem(details, QPointF(0, last_text.height())).y()
    assert 0 < final_line_bottom <= details.height() + 1, {"reason": "Final comparison line remained clipped after scrolling",
        "final_line_bottom": final_line_bottom, "viewport_height": details.height(), "content_y": details.property("contentY"),
        "content_height": details.property("contentHeight"), "last_text_class": last_text.metaObject().className(), "last_text_height": last_text.height()}
    # The same visible controls choose the correct chain's lab and network.
    pane.setProperty('page','PORTFOLIO')
    evaluate(pane,"pickAsset('SOL')")
    original_chart_height=find('cryptoPortfolioChart').height()
    click('cryptoChartExpand'); QTest.qWait(40)
    assert pane.property('chartExpanded')
    assert find('cryptoPortfolioChart').height() > original_chart_height*2
    assert not find('cryptoPortfolioBottom').isVisible()
    click('cryptoChartRestore'); QTest.qWait(30)
    assert not pane.property('chartExpanded') and find('cryptoPortfolioBottom').isVisible()
    click('cryptoLabToggle'); QTest.qWait(30)
    popup=find('cryptoConnectionPanel')
    assert popup.property('visible')
    click('cryptoModeLive'); assert host.calls[-1]==('sol_network','mainnet')
    click('cryptoModeLocal'); assert host.calls[-1]==('sol_network','testnet')
    click('cryptoConnectionLabToggle'); assert host.calls[-1]==('sol_lab_on',)
    QTest.keyClick(window,Qt.Key_Escape); QTest.qWait(25)
    evaluate(pane,"pickAsset('KAS')")
    click('cryptoLabToggle'); QTest.qWait(30)
    click('cryptoModeLocal'); assert host.calls[-1]==('kas_network','testnet')
    click('cryptoConnectionLabToggle'); assert host.calls[-1]==('kas_lab_on',)
    for width in (430,1100):
        window.setWidth(width); QTest.qWait(50)
        assert popup.property('width') <= pane.width()
        preview=os.environ.get('GG_CRYPTO_DESIGN_PREVIEW')
        if preview:
            Path(preview).mkdir(parents=True,exist_ok=True)
            assert window.grabWindow().save(str(Path(preview)/('connection-'+str(width)+'.png')))
    QTest.keyClick(window,Qt.Key_Escape)
    # Hiding the workspace disables the shared timer and avoids extra status reads.
    pane.setVisible(False)
    before = host.status_calls
    QTest.qWait(1100)
    assert host.status_calls == before
    assert not find("cryptoStatusRefreshTimer").property("running")
    assert not warnings, warnings
    print(json.dumps({"status": "PASS", "real_qml": True, "narrow_total_width": 430,
                      "neutral_button_states": True, "shared_frames": True,
                      "navigation": True, "filter_sort": True, "token_inspection": True, "warnings": len(warnings)}))
    window.close()
    engine.deleteLater()
    app.processEvents()


class CryptoDesignTests(unittest.TestCase):
    def test_staged_navigation_holdings_and_narrow_geometry(self):
        with tempfile.TemporaryDirectory(prefix="gg-crypto-design-") as temporary:
            staging = Path(temporary)
            shutil.copytree(PROJECT / "qml/components", staging / "components", ignore=shutil.ignore_patterns("__pycache__"))
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
