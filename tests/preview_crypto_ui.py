"""Render CRYPTO pages with offline fixtures and a read-only fake Qt bridge."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-background-networking")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from backend import crypto_bots, crypto_contract, crypto_strategy_factory, crypto_desk, polymarket_research, crypto_portfolio


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="gg-crypto-preview-"))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gg-crypto-ui-state-") as state:
        crypto_contract.STATE_DIR = Path(state)
        n=240
        closes=[100+i*.03+math.sin(i/7)*3 for i in range(n)]
        frame={"closes":closes,"highs":[p+1 for p in closes],"lows":[p-1 for p in closes],"volumes":[50]*n,"times":[1700000000+i*3600 for i in range(n)]}
        report=crypto_bots.compare_books({"1h":frame})
        payload={"legend":"LOCALNET","portfolio":{"asset":"SOL"},"wallet":{"pubkey":"offline-preview-public-address","balance_sol":"2.00"},
                 "quote":{"usd":"$200.00","sol_usd":100},
                 "chart":{"closes":closes,"times":frame["times"],"interval":"1h","requested_interval":"1h","actual_interval":"1h","source":"offline-fixture","age_seconds":3600,"stale":True},
                 "kas_chart":{"closes":closes,"times":frame["times"],"interval":"1d","actual_interval":"1d","requested_interval":"4h","source":"offline-coarse-fixture","age_seconds":3600,"stale":True},
                 "trader":{"book":"gg","books":crypto_bots.catalog(),"backtest":report},
                 "strategy_factory":crypto_strategy_factory.run_factory({"1h":frame}),
                 "desk":crypto_desk.run_desk({"1h":frame}),
                 "kaspa":{"value_kas":2,"count":1,"legend":"PAPER","address":"kaspa:offline-preview"},
                 "ledger":[{"ts":1,"side":"buy","mode":"PAPER","status":"simulated","hint":"Simulated portfolio buy."},
                           {"ts":2,"side":"buy","mode":"LOCALNET_DIAGNOSTIC","status":"unconfirmed","hint":"Self-transfer awaiting confirmation.","error":"CRYPTO_TX_UNCONFIRMED"},
                           {"ts":3,"side":"buy","mode":"LOCALNET_DIAGNOSTIC","status":"confirmed","hint":"Confirmed self-transfer; no token swap."}],
                 "polymarket":polymarket_research.snapshot()}
        payload["polymarket"].update({"state":"done","result":{"lines":["MINUTE    BID        ASK        OUTCOME / ASSET","17:00      0.20       0.30       Yes","17:00      0.70       0.80       No"],"source_metadata":{"bytes":1000000,"coverage":"Offline fixture. Feed completeness is not verified."}}})
        # Explicitly synthetic assets exercise scrolling, missing prices and dust.
        payload["wallet"].update(balance_sol="200.999975", network="testnet")
        payload["kas_chart"]["closes"] = [p * 0.0007 for p in closes]
        payload["kas_chart"]["times"] = [1700000000 + i * 86400 for i in range(n)]
        payload["holdings"] = [{"symbol":"SOL","mint":"native","display":"200.999975"}]
        for symbol, name, amount, price in [
            ("USDC","USD Coin","1250.500000",1.0001),
            ("JUP","Jupiter","10000",0.6324),
            ("BONK","Bonk","9500000",0.00002431),
            ("ORCA","Orca","52.13",2.4321),
            ("TINY","Small balance","0.000000125",0.00000004),
            ("ALFA","Alpha fixture","38.5",4.123),
            ("BRAVO","Bravo fixture","13.99999999",0.831),
            ("UNKNOWN","Token without a quote","12.340000",None),
            ("LAST","Last asset in the list","0.00005",None),
        ]:
            payload["holdings"].append({"symbol":symbol,"name":name,"mint":"fixture-"+symbol,
                "display":amount,"price_usd":price,"price_source":"offline-fixture" if price else "",
                "price_stale":False,"change_24h_pct":-2.96})
        payload["portfolio"].update(
            sol=crypto_portfolio.summarize(payload["holdings"],payload["chart"],usd_sek=10.02),
            kas=crypto_portfolio.summarize([{"symbol":"KAS","mint":"native","display":"2"}],payload["kas_chart"],native_symbol="KAS",usd_sek=10.02))
        payload["paper_engine"] = {"mode":"PAPER_ONLY", "base_asset":"SOL", "primary":"1h", "source":"offline-fixture", "price":100,
            "accounts":[{"book":r["id"],"name":r["name"],"enabled":i<4,"status":["RUNNING","RUNNING","WAITING_FOR_CLOSED_BAR","RUNNING","PAUSED","RISK_HALT"][i],
                "tokens":1.8,"quote":20,"equity_quote":200,"pnl_quote":0,"buy_hold_quote":199.3,"token_equivalent":2,"fills":i*4,"recovery_bars":0,
                "halt_reason":"PORTFOLIO_DRAWDOWN_OR_DAILY_LOSS" if i==5 else ""} for i,r in enumerate(crypto_bots.BOOKS)]}
        class Host(QObject):
            @Slot(result=str)
            def cryptoStatus(self): return json.dumps(payload)
            @Slot(result=str)
            def cryptoRefreshChart(self): return self.cryptoStatus()
            @Slot(result=str)
            def cryptoRefreshKasChart(self): return self.cryptoStatus()
        QtWebEngineQuick.initialize()
        app=QGuiApplication([])
        if os.name == 'nt':
            for font_file in ('consola.ttf', 'consolab.ttf', 'seguisym.ttf'):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts' / font_file))
        QFont.insertSubstitution('monospace', 'Consolas' if os.name == 'nt' else 'DejaVu Sans Mono')
        app.setFont(QFont('Consolas' if os.name == 'nt' else 'DejaVu Sans Mono'))
        engine=QQmlApplicationEngine()
        messages=[]
        engine.warnings.connect(lambda warnings: messages.extend(w.toString() for w in warnings))
        host=Host()
        engine.rootContext().setContextProperty("previewHost",host)
        qml=output/'preview.qml'
        qml.write_text('import QtQuick\nimport QtQuick.Window\nimport "'+(PROJECT/'qml/components').as_uri()+'"\nWindow { width:1100; height:780; visible:true; color:"#161616"; CryptoSurface { objectName:"reviewPane"; anchors.fill:parent; anchors.margins:16; surfaceHost:previewHost } }')
        engine.load(QUrl.fromLocalFile(str(qml)))
        if not engine.rootObjects(): raise RuntimeError("QML failed: " + "\n".join(messages))
        window=engine.rootObjects()[0]
        pane=window.findChild(QObject,"reviewPane")
        pane.setProperty("statusJson",json.dumps(payload))
        pages=["PORTFOLIO","PORTFOLIO_BOTTOM","PORTFOLIO_WALLET","PORTFOLIO_NARROW","PORTFOLIO_430","PORTFOLIO_EMPTY","PORTFOLIO_NOPRICE","PORTFOLIO_SINGLE","BACKTEST","TRADER","TRADER_NARROW","PUMP","PUMP_NARROW","SIGNAL","ARB","FACTORY","FACTORY_BOTTOM","FACTORY_NARROW","DESK","POLY","KAS","KAS_WALLET","ACTIVITY"]
        index=0
        geometry=[]
        def capture():
            nonlocal index
            page=pages[index]
            narrow = page in ("PORTFOLIO_430", "PUMP_NARROW", "FACTORY_NARROW")
            window.setWidth(430 if narrow else 720 if page in ("PORTFOLIO_NARROW","TRADER_NARROW") else 1100)
            window.setHeight(650 if narrow or page in ("PORTFOLIO_NARROW","TRADER_NARROW") else 780)
            pane.setProperty("statusJson",json.dumps(payload))
            pane.setProperty("assetPick","KAS" if page.startswith("KAS") else "SOL")
            pane.setProperty("walletToolsOpen",page.endswith("WALLET"))
            pane.setProperty("page","PORTFOLIO" if page.startswith(("PORTFOLIO","KAS")) else page.split("_")[0])
            if page in ("PORTFOLIO_EMPTY","PORTFOLIO_NOPRICE","PORTFOLIO_SINGLE"):
                fixture=json.loads(json.dumps(payload))
                assets=[] if page.endswith("EMPTY") else payload["holdings"][:1] if page.endswith("SINGLE") else [dict(a,price_usd=None) for a in payload["holdings"]]
                if page.endswith("NOPRICE"):
                    fixture["chart"]={"error":"OFFLINE_FIXTURE_MISSING_QUOTE","stale":True}
                fixture["portfolio"]["sol"]=crypto_portfolio.summarize(assets,fixture["chart"])
                if page.endswith("EMPTY"): fixture["wallet"]={}
                pane.setProperty("statusJson",json.dumps(fixture))
            holdings=pane.findChild(QObject,"cryptoHoldingsList")
            holdings.setProperty("contentY",0)
            if page=="PORTFOLIO_BOTTOM":
                holdings.setProperty("contentY",max(0,holdings.property("contentHeight")-holdings.property("height")))
            if page.startswith("FACTORY"):
                scroll=pane.findChild(QObject,"cryptoFactoryScroll")
                scroll.setProperty("contentY",max(0,scroll.property("contentHeight")-scroll.property("height")) if page=="FACTORY_BOTTOM" else 0)
            if page=="BACKTEST": pane.setProperty("botTape","bt0")
            def save():
                nonlocal index
                if page.startswith(("PORTFOLIO","KAS")):
                    chart=pane.findChild(QObject,"cryptoPortfolioChart")
                    header=pane.findChild(QObject,"cryptoPortfolioHeader")
                    bottom=pane.findChild(QObject,"cryptoPortfolioBottom")
                    geometry.append({"page":page,"header_height":header.height(),"chart_height":chart.height(),"bottom_height":bottom.height(),"list_height":holdings.height()})
                    if chart.y() < header.y()+header.height() or bottom.y() < chart.y()+chart.height() or holdings.height() < 60:
                        messages.append("PORTFOLIO_LAYOUT_OVERLAP:"+page)
                image=window.grabWindow()
                if image.isNull(): messages.append("NULL_CAPTURE:"+page)
                else: image.save(str(output/(page.lower()+'.png')))
                index+=1
                if index<len(pages): QTimer.singleShot(50,capture)
                else: app.quit()
            QTimer.singleShot(500,save)
        QTimer.singleShot(800,capture)
        QTimer.singleShot(30000,app.quit)
        app.exec()
        (output/'warnings.json').write_text(json.dumps(messages,indent=2))
        (output/'geometry.json').write_text(json.dumps(geometry,indent=2))
        if messages: print("QML_WARNINGS",json.dumps(messages))
        print("CRYPTO_UI_PREVIEW", output)
        return 1 if messages or index != len(pages) else 0


if __name__=="__main__": raise SystemExit(main())
