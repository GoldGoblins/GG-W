import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Item {
    id: root
    objectName: "workspaceCryptoPane"

    property var surfaceHost: null
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    readonly property color ink: "#e6edf3"
    readonly property color text: "#c8cdd4"
    readonly property color muted: "#8b949e"
    readonly property color panel: "#181818"
    readonly property color panelRaised: "#202020"
    readonly property color selectedPanel: "#34383d"
    readonly property color ledgerGold: "#c8a97e"
    readonly property color ledgerGreen: "#8db89a"
    property bool sidebarCollapsed: false
    property string statusJson: "{}"
    property string botTab: "trader"
    property string botTape: "live"
    property string page: "PORTFOLIO"
    property string assetPick: ""
    property bool walletToolsOpen: false
    readonly property var portfolioView: (root.status.portfolio || {})[root.asset === "KAS" ? "kas" : "sol"] || ({})
    readonly property string asset: {
        if (root.assetPick === "SOL" || root.assetPick === "KAS")
            return root.assetPick
        return String((root.status.portfolio || {}).asset || "") === "KAS" ? "KAS" : "SOL"
    }
    readonly property var nav: [
        "PORTFOLIO",
        "BACKTEST",
        "TRADER",
        "SIGNAL",
        "ARB",
        "ACTIVITY",
        "FACTORY",
        "DESK",
        "POLY"
    ]
    readonly property bool backtestRunning: String((root.status.backtest_job || {}).state || "") === "running"
    signal walletLabelChanged(string label)

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property var wallet: root.status.wallet || {}
    readonly property var holdings: root.status.holdings || []
    readonly property var ledger: {
        var rows = root.status.ledger || []
        var out = []
        var live = String(root.status.legend || "TESTNET") === "MAINNET"
            || String(root.status.legend || "") === "OBSERVE"
        for (var i = rows.length - 1; i >= 0; i--) {
            var row = rows[i] || {}
            var err = String(row.error || "")
            var hint = String(row.hint || "")
            if (!live && (err === "MAINNET_NOT_ARMED"
                            || err === "MAINNET_OBSERVE_ONLY"
                            || hint.indexOf("Mainnet stays locked") >= 0
                            || hint.indexOf("observe-only") >= 0))
                continue
            out.push(row)
        }
        return out
    }
    readonly property var bot: root.status.bot || {}
    readonly property var trader: root.status.trader || {}
    readonly property var arb: root.status.arb || {}
    readonly property var lab: root.status.lab || {}
    readonly property var polymarket: root.status.polymarket || {}
    readonly property var polyResult: root.polymarket.result || {}
    readonly property bool polyRunning: ["running", "cancelling"].indexOf(String(root.polymarket.state || "")) >= 0
    readonly property var strategyFactory: root.status.strategy_factory || {}
    readonly property var strategyFactoryJob: root.status.strategy_factory_job || {}
    readonly property var strategyFactoryResult: root.strategyFactory
    readonly property bool strategyFactoryRunning:
        String(root.strategyFactoryJob.state || "") === "running"
    readonly property var desk: root.status.desk || {}
    readonly property var kaspa: root.status.kaspa || {}
    readonly property var deskJob: root.status.desk_job || {}
    readonly property bool deskRunning: String(root.deskJob.state || "") === "running"
    property string polyPreset: "SUMMARY"
    property string polyDate: root.utcDate()
    property string polyHour: root.utcHour()
    property string polySlug: ""
    readonly property string legend: String(root.status.legend || "TESTNET")
    readonly property bool traderAvailable: root.legend !== "OBSERVE"
    readonly property bool paperTickRunning: String(((root.status.paper_jobs || {}).trader || {}).state || "") === "running"
    readonly property bool connected: String(root.wallet.pubkey || "").length > 12
    readonly property var quote: root.status.quote || {}
    readonly property var liveChart: root.status.chart || {}
    readonly property var sparkChart: root.liveChart
    readonly property var botTapeChart: {
        if (root.botTape === "bt0") {
            var a = ((root.trader.backtest || {}).chart) || {}
            if (a.closes && a.closes.length > 1)
                return a
        }
        if (root.botTape === "bt1") {
            var b = ((root.trader.backtest_prev || {}).chart) || {}
            if (b.closes && b.closes.length > 1)
                return b
        }
        return root.liveChart
    }
    readonly property var closes: {
        var rows = (root.sparkChart || {}).closes
        if (rows && rows.length !== undefined && rows.length > 1)
            return rows
        rows = root.bot.closes
        if (rows && rows.length !== undefined)
            return rows
        return []
    }
    readonly property var chartTimes: {
        var rows = (root.sparkChart || {}).times
        if (rows && rows.length !== undefined)
            return rows
        return []
    }
    readonly property var tradeMarks: root.buildTradeMarks(root.sparkChart, false)
    readonly property var chartPoints: root.buildChartPoints(root.sparkChart)
    readonly property var chartMarkers: []
    readonly property bool chartHasTimes: root.chartTimes.length === root.closes.length
        && root.closes.length > 1
    readonly property var botPoints: root.buildChartPoints(root.botTapeChart)
    readonly property var botMarkers: root.buildChartMarkers(
        root.botTapeChart,
        root.botTape === "live"
            ? root.buildTradeMarks(root.botTapeChart, false)
            : root.buildTradeMarks(root.botTapeChart, true)
    )
    readonly property bool botHasTimes: {
        var c = (root.botTapeChart || {}).closes || []
        var t = (root.botTapeChart || {}).times || []
        return t.length === c.length && c.length > 1
    }
    readonly property var botEquity: {
        var rows = (root.botTapeChart || {}).equity || []
        var out = []
        var i
        if (!rows || !rows.length)
            return out
        for (i = 0; i < rows.length; i++) {
            var row = rows[i] || {}
            var ts = Number(row.time || row.ts || 0)
            var val = Number(row.value || row.sol || 0)
            if (ts > 0 && val > 0)
                out.push({ "time": ts, "value": val })
        }
        return out
    }

    function navLabel(value) {
        var labels = {
            "PORTFOLIO": "Portfolio",
            "BACKTEST": "Backtest",
            "TRADER": "Trader",
            "KASPA": "Kaspa",
            "SIGNAL": "Signal",
            "ARB": "Flash arb",
            "ACTIVITY": "Fills",
            "FACTORY": "Factory",
            "DESK": "Desk",
            "POLY": "Polymarket"
        }
        return labels[String(value || "")] || String(value || "")
    }

    function navIcon(value) {
        var icons = {
            "PORTFOLIO": "⌂",
            "BACKTEST": "◒",
            "TRADER": "▥",
            "KASPA": "◆",
            "SIGNAL": "∿",
            "ARB": "ϟ",
            "ACTIVITY": "▤",
            "FACTORY": "⚙",
            "DESK": "▦",
            "POLY": "◇"
        }
        return icons[String(value || "")] || "·"
    }

    function menuKids(pageId) {
        var id = String(pageId || "")
        var out = []
        var i
        if (id === "PORTFOLIO")
            return [
                {"id": "SOL", "name": "SOL"},
                {"id": "KAS", "name": "KAS"}
            ]
        if (id === "BACKTEST" || id === "TRADER") {
            var books = root.trader.books || []
            for (i = 0; i < books.length; i++) {
                var row = books[i] || {}
                var verdict = "PAPER"
                out.push({
                    "id": String(row.id || ""),
                    "name": String(row.name || row.id || "")
                        + (verdict.length ? ("  " + verdict) : "")
                })
            }
            return out
        }
        if (id === "POLY")
            return [
                {"id": "SUMMARY", "name": "SUMMARY"},
                {"id": "TRADES", "name": "TRADES"},
                {"id": "TOUCH", "name": "TOUCH"},
                {"id": "SCAN", "name": "SCAN"}
            ]
        if (id === "KASPA")
            return [
                {"id": "paper", "name": "Paper"},
                {"id": "testnet", "name": "Kaspa TN"},
                {"id": "mainnet", "name": "Kaspa live"}
            ]
        if (id === "SIGNAL")
            return [{"id": "004", "name": "Strategy004"}]
        return out
    }

    function kidActive(pageId, kid) {
        var id = String((kid && kid.id) || "")
        if (pageId === "PORTFOLIO")
            return id === root.asset
        if (pageId === "BACKTEST" || pageId === "TRADER")
            return id === String(root.trader.book || "gg")
        if (pageId === "POLY")
            return id === String(root.polyPreset || "SUMMARY")
        if (pageId === "KASPA")
            return id === String(root.kaspa.network || "paper")
        if (pageId === "SIGNAL")
            return root.page === "SIGNAL"
        return false
    }

    function pickChild(pageId, kid) {
        var id = String((kid && kid.id) || "")
        root.page = pageId
        if (pageId === "PORTFOLIO") {
            root.pickAsset(id)
            return
        }
        if ((pageId === "BACKTEST" || pageId === "TRADER")
                && root.surfaceHost && root.surfaceHost.cryptoSetBook)
            root.statusJson = root.surfaceHost.cryptoSetBook(id || "gg")
        else if (pageId === "POLY")
            root.polyPreset = id || "SUMMARY"
        else if (pageId === "KASPA") {
            root.pickAsset("KAS")
            if (root.surfaceHost && root.surfaceHost.cryptoKaspaSetNetwork)
                root.statusJson = root.surfaceHost.cryptoKaspaSetNetwork(id || "paper")
        }
    }

    function twoDigits(value) {
        var number = Number(value)
        return number < 10 ? "0" + String(number) : String(number)
    }

    function utcDate() {
        var now = new Date()
        return String(now.getUTCFullYear()) + "-"
            + twoDigits(now.getUTCMonth() + 1) + "-"
            + twoDigits(now.getUTCDate())
    }

    function utcHour() {
        return twoDigits(new Date().getUTCHours())
    }

    function refresh() {
        if (!root.surfaceHost)
            return
        var raw = root.surfaceHost.cryptoStatus()
        if (raw === root.statusJson)
            return
        root.statusJson = raw
        if (root.assetPick === String((root.status.portfolio || {}).asset || "SOL")
                || (root.assetPick === "SOL" && String((root.status.portfolio || {}).asset || "SOL") !== "KAS"))
            root.assetPick = ""
        var w = root.status.wallet || {}
        root.walletLabelChanged(String(w.label || "WALLET · DISCONNECTED"))
        if (root.asset === "KAS") {
            var kcloses = ((root.status.kas_chart || {}).closes) || []
            if ((kcloses.length < 2 || (root.status.kas_chart || {}).stale) && root.surfaceHost.cryptoRefreshKasChart)
                Qt.callLater(root.pullKasChart)
            return
        }
        if (root.surfaceHost.cryptoRefreshChart
                && (root.closes.length < 2
                    || root.chartTimes.length !== root.closes.length || root.liveChart.stale))
            Qt.callLater(root.pullChart)
    }

    function pullOlderBars() {
        if (root.page === "BACKTEST" || !solPlot)
            return
        if (solPlot.historyBusy || solPlot.historyEnd)
            return
        if (!root.surfaceHost)
            return
        var before = Number((solPlot.stamps || [])[0] || 0)
        solPlot.rememberView()
        solPlot.historyBusy = true
        var raw = ""
        if (root.asset === "KAS") {
            if (!root.surfaceHost.cryptoExtendKasChart) {
                solPlot.historyBusy = false
                solPlot.historyEnd = true
                return
            }
            raw = root.surfaceHost.cryptoExtendKasChart()
        } else {
            if (!root.surfaceHost.cryptoExtendSolChart) {
                solPlot.historyBusy = false
                return
            }
            raw = root.surfaceHost.cryptoExtendSolChart()
        }
        try {
            var parsed = JSON.parse(raw || "{}")
            if (!parsed.error)
                root.statusJson = raw
        } catch (err) {
            solPlot.historyBusy = false
            return
        }
        var after = Number((solPlot.stamps || [])[0] || 0)
        if (!(after > 0) || after >= before)
            solPlot.historyEnd = true
        solPlot.historyBusy = false
    }

    function pullKasChart() {
        if (!root.surfaceHost || !root.surfaceHost.cryptoRefreshKasChart)
            return
        var raw = root.surfaceHost.cryptoRefreshKasChart()
        try {
            var parsed = JSON.parse(raw || "{}")
            if (!parsed.error)
                root.statusJson = raw
        } catch (err) {
            return
        }
    }

    function pickAsset(id) {
        var next = String(id || "").toUpperCase()
        if (next === "KAS" || next === "KASPA")
            next = "KAS"
        else
            next = "SOL"
        root.assetPick = next
        root.page = "PORTFOLIO"
        if (!root.surfaceHost || !root.surfaceHost.cryptoSetPortfolioAsset)
            return
        var raw = root.surfaceHost.cryptoSetPortfolioAsset(next)
        try {
            var parsed = JSON.parse(raw || "{}")
            if (!parsed.error && parsed.portfolio)
                root.statusJson = raw
        } catch (err) {
            return
        }
        if (String((root.status.portfolio || {}).asset || "") === next)
            root.assetPick = ""
    }

    function pickKasNetwork(id) {
        if (root.surfaceHost && root.surfaceHost.cryptoKaspaSetNetwork)
            root.statusJson = root.surfaceHost.cryptoKaspaSetNetwork(id || "paper")
    }

    function pullChart() {
        if (!root.surfaceHost || !root.surfaceHost.cryptoRefreshChart)
            return
        var raw = root.surfaceHost.cryptoRefreshChart()
        try {
            var parsed = JSON.parse(raw || "{}")
            if (!parsed.error)
                root.statusJson = raw
        } catch (err) {
            return
        }
        var w = root.status.wallet || {}
        root.walletLabelChanged(String(w.label || "WALLET · DISCONNECTED"))
    }

    function runPolymarketQuery() {
        if (root.polyRunning)
            return
        if (!root.surfaceHost || !root.surfaceHost.cryptoPolymarketQuery)
            return
        root.statusJson = root.surfaceHost.cryptoPolymarketQuery(
            root.polyPreset,
            polyDateField.text,
            polyHourField.text,
            polySlugField.text
        )
    }

    function pollPolymarketQuery() {
        if (!root.surfaceHost || !root.surfaceHost.cryptoPolymarketStatus)
            return
        root.statusJson = root.surfaceHost.cryptoPolymarketStatus()
    }

    function resetPolymarketQuery() {
        if (!root.surfaceHost || !root.surfaceHost.cryptoPolymarketReset)
            return
        root.statusJson = root.surfaceHost.cryptoPolymarketReset()
    }

    function factoryRolesText() {
        var roles = (root.strategyFactoryResult.orchestration || {}).roles || []
        var out = []
        for (var i = 0; i < roles.length; i++) {
            var role = roles[i] || {}
            out.push(String(role.id || "ROLE") + "=" + String(role.state || "—"))
        }
        return out.join("  ·  ")
    }

    function factoryGraveyardText() {
        var rows = root.strategyFactoryResult.graveyard || []
        var out = []
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i] || {}
            out.push(String(row.id || "ID") + "=" + String(row.verdict || "—"))
        }
        return out.join("  ·  ")
    }

    function factoryAutoresearchText() {
        var steps = ((root.strategyFactoryResult.autoresearch || {}).steps) || []
        var out = []
        for (var i = 0; i < steps.length; i++) {
            var step = steps[i] || {}
            out.push(String(step.mutation || "STEP")
                     + " " + String(step.decision || "—")
                     + " validation Sharpe " + String(step.validation_sharpe !== undefined ? step.validation_sharpe : "—"))
        }
        return out.join("  ·  ")
    }

    function factoryMetric(row) {
        var item = row || {}
        var ret = item.return_pct !== undefined ? item.return_pct : "—"
        var drawdown = item.max_drawdown_pct !== undefined
            ? item.max_drawdown_pct : "—"
        var trades = item.trades !== undefined ? item.trades : "—"
        var wins = item.win_rate_pct !== undefined ? item.win_rate_pct : "—"
        return "ret " + String(ret) + "%"
            + "  maxDD " + String(drawdown) + "%"
            + "  trades " + String(trades)
            + "  win " + String(wins) + "%"
    }

    function dataStatus() {
        var chart = root.asset === "KAS" ? (root.status.kas_chart || {}) : root.liveChart
        if (root.page === "PORTFOLIO") {
            var actual = String(chart.actual_interval || chart.interval || "—")
            var requested = String(chart.requested_interval || actual)
            var seconds = Number(chart.age_seconds || 0)
            var stamp = chart.age_seconds === undefined || chart.age_seconds === null ? "ålder okänd"
                : seconds < 60 ? Math.round(seconds) + " s" : seconds < 3600 ? Math.floor(seconds / 60) + " min" : Math.floor(seconds / 3600) + " h"
            return String(chart.source || "PRISDATA SAKNAS").toUpperCase() + " · " + actual
                + (actual !== requested ? " (begärt " + requested + ")" : "") + " · "
                + (chart.age_seconds === undefined || chart.age_seconds === null ? stamp : "hämtad för " + stamp + " sedan")
                + (chart.stale ? " · ÄLDRE / ERSÄTTNINGSDATA" : "")
                + (chart.error ? " · prisfel" : "")
        }
        var age = chart.age_seconds === undefined || chart.age_seconds === null ? "unknown age" : String(Math.round(chart.age_seconds)) + "s old"
        return String(chart.source || "NO SOURCE").toUpperCase() + " · requested "
            + String(chart.requested_interval || chart.interval || "—") + " / actual "
            + String(chart.actual_interval || chart.interval || "—") + " · " + age
            + (chart.stale ? " · STALE" : "") + (chart.error ? " · " + String(chart.error) : "")
    }

    function comparisonText() {
        var bt = root.trader.backtest || {}
        var rows = bt.comparison || []
        var cost = bt.cost_model || {}
        var out = ["SAME DATA · 200 USDT start · " + String(cost.per_leg_bps || "—") + " bps/leg · USDT return / tokenmotsvarande / drawdown / final holdout return"]
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i] || {}
            out.push(String(r.name || r.book) + "  " + (r.state === "ERROR" ? String(r.error) :
                String(r.return_pct) + "% / " + String(r.return_token_equivalent_pct === undefined ? "—" : r.return_token_equivalent_pct) + "% / " + String(r.max_drawdown_pct) + "% / " + String((r.holdout || {}).return_pct) + "%"))
            if (r.book === "hybrid")
                out.push("  HYBRID model: " + String(r.model || "—") + (r.model_note ?
                    (String(r.model_note).indexOf("OPT_IN_REQUIRED") >= 0 ? " · TimesFM 3 requires noncommercial research opt-in" : " · local forecast unavailable; fallback used") : ""))
        }
        var baselines = bt.benchmarks || {}
        if (baselines.buy_and_hold)
            out.push("Buy & hold " + String(baselines.buy_and_hold.return_pct) + "% · simple daily DCA " + String((baselines.simple_dca || {}).return_pct) + "%")
        if (rows.length && rows[0].holdout_benchmarks)
            out.push("Final holdout baselines: hold " + String(rows[0].holdout_benchmarks.buy_and_hold.return_pct)
                + "% · daily DCA " + String(rows[0].holdout_benchmarks.simple_dca.return_pct) + "%")
        out.push("Tokenmotsvarande inkluderar kassa, inte endast innehav.")
        out.push("Frozen parameters · final 20% evaluated separately · descriptive results")
        if (bt.range)
            out.push(String(bt.range) + " · " + String((bt.data || {}).source || ""))
        return out.join("\n")
    }

    function connectWatch() {
        if (!root.surfaceHost)
            return
        root.statusJson = root.surfaceHost.cryptoConnectWatch(pubkeyField.text)
        refresh()
    }

    function paperSignal() {
        if (!root.surfaceHost)
            return
        root.surfaceHost.cryptoIngestSignal(
            JSON.stringify({
                "side": "buy",
                "size_sol": 0.01,
                "symbol": "SOL",
                "source": "manual"
            })
        )
        refresh()
    }

    function shortKey(value) {
        var t = String(value || "")
        if (t.length < 12)
            return t.length ? t : "not connected"
        return t.substring(0, 4) + " ··· " + t.substring(t.length - 4)
    }

    function tokenColor(index) {
        var colors = ["#c8a97e", "#6aa8c8", "#8db89a", "#b6a6c8", "#c98989", "#d4c84a"]
        return colors[index % colors.length]
    }

    function lastClose() {
        if (root.closes.length === 0)
            return ""
        return String(root.closes[root.closes.length - 1])
    }

    function tapeRows() {
        if (root.page === "BACKTEST") {
            var back = (root.botTapeChart || {}).closes || []
            if (back.length > 1)
                return back
        }
        if (root.asset === "KAS")
            return (root.status.kas_chart || {}).closes || []
        return root.closes || []
    }

    function tapeUp() {
        var rows = root.tapeRows()
        if (!rows || rows.length < 2)
            return true
        return Number(rows[rows.length - 1]) >= Number(rows[0])
    }

    function tapeChangeText() {
        var rows = root.tapeRows()
        if (!rows || rows.length < 2)
            return ""
        var openPx = Number(rows[0])
        var lastPx = Number(rows[rows.length - 1])
        if (!(openPx > 0))
            return ""
        var pct = (lastPx - openPx) / openPx * 100
        return (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%"
    }

    function tapeExtreme(wantHigh) {
        var rows = root.tapeRows()
        if (!rows || rows.length === 0)
            return ""
        var value = Number(rows[0])
        var i
        for (i = 1; i < rows.length; i++) {
            var next = Number(rows[i])
            if (wantHigh ? next > value : next < value)
                value = next
        }
        if (!(value > 0))
            return ""
        return "$" + value.toFixed(value >= 100 ? 2 : 4)
    }

    function activeBookLine() {
        var id = String((root.trader || {}).book || "gg")
        var books = (root.trader || {}).books || []
        var i
        for (i = 0; i < books.length; i++) {
            var row = books[i] || {}
            if (String(row.id || "") === id)
                return String(row.name || id) + "  PAPER"
        }
        return id
    }

    function priceText(px) {
        var n = Number(px || 0)
        if (!(n > 0))
            return "—"
        if (n >= 100)
            return "$" + n.toFixed(2)
        if (n >= 1)
            return "$" + n.toFixed(4)
        return "$" + n.toFixed(5)
    }

    function solPriceText() {
        var rows = root.closes || []
        var px = rows.length ? Number(rows[rows.length - 1]) : Number((root.quote || {}).sol_usd || 0)
        return root.priceText(px)
    }

    function assetPriceText() {
        if (root.asset === "KAS") {
            var rows = (root.status.kas_chart || {}).closes || []
            var px = rows.length ? Number(rows[rows.length - 1]) : Number((root.status.kas_chart || {}).price || 0)
            return root.priceText(px)
        }
        return root.solPriceText()
    }

    function assetValueText() {
        if (root.asset === "KAS") {
            var rows = (root.status.kas_chart || {}).closes || []
            var px = rows.length ? Number(rows[rows.length - 1]) : Number((root.status.kas_chart || {}).price || 0)
            var kas = Number(root.kaspa.value_kas || 0)
            if (!(px > 0) || !(kas > 0))
                return ""
            return root.priceText(kas * px)
        }
        return String(root.quote.usd || "")
    }

    function assetMetaText() {
        if (root.asset === "KAS") {
            var addr = String(root.kaspa.address || "")
            var line = String(root.kaspa.value_kas || "0") + " KAS"
                + "   count " + String(root.kaspa.count)
            if (addr.length)
                line = root.shortKey(addr) + "   " + line
            line += "   " + String(root.kaspa.legend || "PAPER")
            var src = String((root.status.kas_chart || {}).source || "")
            if (src.length)
                line += "   " + src
            var lab = String((root.kaspa.lab || {}).label || "")
            if (lab.length)
                line += "   " + lab
            return line
        }
        var line = String(root.wallet.balance_sol || "0") + " SOL"
        if (root.legend !== "OBSERVE")
            line += "   SIMULATED LOCALNET VALUE"
        if (root.connected)
            line = root.shortKey(root.wallet.pubkey) + "   " + line
        if (String(root.quote.sek || "").length)
            line += "   " + String(root.quote.sek)
        var solSrc = String(root.quote.source || "")
        if (solSrc.length)
            line += "   " + solSrc
        return line
    }

    readonly property string activeTf: {
        var chart = root.asset === "KAS" ? (root.status.kas_chart || {}) : (root.sparkChart || {})
        var tf = String(chart.interval || "")
        if (tf === "1m" || tf === "5m" || tf === "15m" || tf === "1h" || tf === "4h" || tf === "1d")
            return tf
        return root.asset === "KAS" ? root.kasTf : root.chartTf
    }
    property string chartTf: "15m"
    property string kasTf: "15m"

    function pickInterval(tf) {
        var next = String(tf || "15m")
        if (root.asset === "KAS") {
            root.kasTf = next
            if (root.surfaceHost && root.surfaceHost.cryptoSetKasChartInterval)
                root.statusJson = root.surfaceHost.cryptoSetKasChartInterval(next)
            return
        }
        root.chartTf = next
        if (root.surfaceHost && root.surfaceHost.cryptoSetChartInterval)
            root.statusJson = root.surfaceHost.cryptoSetChartInterval(root.chartTf)
    }

    function lotDollars(raw) {
        var px = Number(raw || 0)
        if (px > 10000)
            px = px / 1000000.0
        return px
    }

    function buildTradeMarks(chart, fromBacktest) {
        var rows = (chart || {}).closes || []
        var n = rows.length
        var out = []
        if (n < 2)
            return out
        var times = (chart || {}).times || []
        var lots = fromBacktest
            ? ((chart || {}).marks || [])
            : ((root.trader || {}).lots || [])
        var i
        var j
        var t0 = 0
        var t1 = 0
        if (times && times.length === n) {
            t0 = Number(times[0] || 0)
            t1 = Number(times[n - 1] || 0)
        }
        for (j = 0; j < lots.length; j++) {
            var lot = lots[j] || {}
            var side = String(lot.side || "")
            if (side !== "buy" && side !== "sell")
                continue
            var ts = Number(lot.ts || 0)
            if (!(t0 > 0 && t1 >= t0 && ts > 0))
                continue
            if (ts < t0 - 7200)
                continue
            var idx = 0
            for (i = 0; i < n; i++) {
                if (Number(times[i] || 0) <= ts)
                    idx = i
            }
            out.push({
                "i": idx,
                "side": side,
                "px": root.lotDollars(lot.price !== undefined ? lot.price : lot.px)
            })
        }
        return out
    }

    function buildChartPoints(chart) {
        var rows = (chart || {}).closes || []
        var times = (chart || {}).times || []
        var out = []
        var i
        if (!rows || rows.length < 2 || times.length !== rows.length)
            return out
        for (i = 0; i < rows.length; i++) {
            var ts = Number(times[i] || 0)
            var px = Number(rows[i] || 0)
            if (ts > 0 && px > 0)
                out.push({ "time": ts, "value": px })
        }
        return out
    }

    function buildChartMarkers(chart, marks) {
        var times = (chart || {}).times || []
        var out = []
        var i
        for (i = 0; i < marks.length; i++) {
            var m = marks[i] || {}
            var idx = Math.round(Number(m.i || 0))
            var ts = Number(times[idx] || 0)
            if (!(ts > 0))
                continue
            var buy = String(m.side || "") === "buy"
            out.push({
                "time": ts,
                "position": buy ? "belowBar" : "aboveBar",
                "color": buy ? "#8db89a" : "#c98989",
                "shape": buy ? "arrowUp" : "arrowDown"
            })
        }
        return out
    }

    Timer {
        interval: 20000
        running: root.visible
        repeat: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 1000
        running: root.visible && root.backtestRunning
        repeat: true
        onTriggered: {
            root.refresh()
            var st = String((root.status.backtest_job || {}).state || "")
            if (st === "done") {
                root.page = "BACKTEST"
                root.botTab = "trader"
                root.botTape = "bt0"
            }
        }
    }

    Timer {
        interval: 1000
        running: root.visible && (root.paperTickRunning || String(((root.status.paper_jobs || {}).bot || {}).state || "") === "running")
        repeat: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 1000
        running: root.visible && root.page === "POLY" && root.polyRunning
        repeat: true
        onTriggered: root.pollPolymarketQuery()
    }

    Timer {
        interval: 1000
        running: root.visible && root.page === "FACTORY"
            && root.strategyFactoryRunning
        repeat: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 1000
        running: root.visible && root.page === "DESK" && root.deskRunning
        repeat: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 1000
        running: root.visible && String(root.lab.label || "") === "LAB STARTING"
        repeat: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 30000
        running: root.visible && root.bot.armed === true
        repeat: true
        onTriggered: {
            if (root.surfaceHost)
                root.statusJson = root.surfaceHost.cryptoTickBot()
            root.refresh()
        }
    }

    Timer {
        interval: 15000
        running: root.visible && root.trader.armed === true
        repeat: true
        onTriggered: {
            if (root.surfaceHost)
                root.statusJson = root.surfaceHost.cryptoTickTrader()
            root.refresh()
        }
    }

    onVisibleChanged: {
        if (visible)
            root.refresh()
    }
    Component.onCompleted: Qt.callLater(root.refresh)

    FileDialog {
        id: keypairDialog
        title: "IMPORT SOLANA KEYPAIR"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON (*.json)", "All files (*)"]
        onAccepted: {
            if (root.surfaceHost)
                root.surfaceHost.cryptoImportKeypair(
                    String(keypairDialog.selectedFile)
                )
            root.refresh()
        }
    }


    onPageChanged: {
        if (root.page === "KASPA") {
            root.page = "PORTFOLIO"
            root.pickAsset("KAS")
            return
        }
        if (root.page === "SIGNAL")
            root.botTab = "signal"
        else if (root.page === "ARB")
            root.botTab = "arb"
        else
            root.botTab = "trader"
    }

    Item {
        id: chrome
        clip: true
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 12
        anchors.topMargin: 8
        anchors.bottomMargin: 10

        Rectangle {
            anchors.fill: parent
            color: "#161616"
            border.width: 0
        }

        Rectangle {
            id: sidebar
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: root.sidebarCollapsed ? 48 : Math.max(168, Math.min(220, parent.width * 0.18))
            color: root.panel
            border.width: 0
            radius: 0

            Behavior on width {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }

            Component {
                id: navEntry
                Column {
                    id: group
                    required property string modelData
                    width: navCol.width
                    spacing: 1
                    readonly property var kids: root.menuKids(modelData)
                    readonly property bool opened: !root.sidebarCollapsed
                        && root.page === modelData
                        && kids.length > 0

                    Item {
                        width: parent.width
                        height: 29
                        Rectangle {
                            anchors.fill: parent
                            radius: 3
                            color: root.page === group.modelData
                                ? root.selectedPanel
                                : (navHit.containsMouse ? "#2a2a2a" : "transparent")
                        }
                        Text {
                            visible: !root.sidebarCollapsed
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.navIcon(group.modelData)
                            color: root.page === group.modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 13
                        }
                        Text {
                            visible: !root.sidebarCollapsed
                            anchors.left: parent.left
                            anchors.leftMargin: 32
                            anchors.right: caretMark.left
                            anchors.rightMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.navLabel(group.modelData)
                            color: root.page === group.modelData ? root.ink : root.text
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.page === group.modelData
                            elide: Text.ElideRight
                        }
                        Text {
                            id: caretMark
                            visible: !root.sidebarCollapsed && group.kids.length > 0
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            text: group.opened ? "▾" : "▸"
                            color: root.muted
                            font.family: "monospace"
                            font.pixelSize: 12
                        }
                        Text {
                            visible: root.sidebarCollapsed
                            anchors.centerIn: parent
                            text: root.navIcon(group.modelData)
                            color: root.page === group.modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 14
                        }
                        MouseArea {
                            id: navHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.page = group.modelData
                        }
                    }

                    Repeater {
                        model: group.opened ? group.kids : []
                        delegate: Item {
                            required property var modelData
                            width: group.width
                            height: 22
                            readonly property var kid: modelData
                            readonly property bool on: root.kidActive(group.modelData, kid)
                            Rectangle {
                                anchors.fill: parent
                                radius: 3
                                color: parent.on
                                    ? "#2a2e33"
                                    : (kidHit.containsMouse ? "#222222" : "transparent")
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 32
                                anchors.right: parent.right
                                anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: String((parent.kid && parent.kid.name) || "")
                                color: parent.on ? root.ledgerGold : root.muted
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: parent.on
                                elide: Text.ElideRight
                            }
                            MouseArea {
                                id: kidHit
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.pickChild(group.modelData, parent.kid)
                            }
                        }
                    }
                }
            }

            Flickable {
                id: navFlick
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: navBottom.top
                anchors.margins: 10
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentWidth: width
                contentHeight: navCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: navCol
                    width: navFlick.width
                    spacing: 3

                    Item {
                        width: navCol.width
                        height: 30
                        Text {
                            anchors.centerIn: parent
                            text: "☰"
                            color: root.ink
                            font.family: "monospace"
                            font.pixelSize: 19
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.sidebarCollapsed = !root.sidebarCollapsed
                        }
                    }

                    Repeater {
                        model: root.nav.slice(0, 3)
                        delegate: navEntry
                    }

                    Item { width: 1; height: 7 }

                    Rectangle {
                        width: navCol.width
                        height: 1
                        color: "#3a3a3a"
                    }

                    Text {
                        width: navCol.width
                        text: root.sidebarCollapsed ? "" : "LAB"
                        color: root.ledgerGold
                        font.family: "monospace"
                        font.pixelSize: 10
                        font.bold: true
                        leftPadding: 12
                        topPadding: 4
                        bottomPadding: 2
                    }

                    Repeater {
                        model: root.nav.slice(3)
                        delegate: navEntry
                    }
                }
            }

            Item {
                id: navBottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: root.sidebarCollapsed ? 50 : 74

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: "#3a3a3a"
                }
                Text {
                    visible: !root.sidebarCollapsed
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 42
                    text: "CRYPTO"
                    color: root.ledgerGold
                    font.family: "monospace"
                    font.pixelSize: 16
                    font.bold: true
                    font.letterSpacing: 1.2
                }
                Text {
                    visible: !root.sidebarCollapsed
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 14
                    text: root.legend === "OBSERVE" ? "MAINNET · OBSERVE" : "PAPER · LOCALNET"
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                }
                Text {
                    visible: root.sidebarCollapsed
                    anchors.centerIn: parent
                    text: "◈"
                    color: root.ledgerGold
                    font.family: "monospace"
                    font.pixelSize: 16
                }
            }
        }

        Rectangle {
            id: navSep
            anchors.left: sidebar.right
            anchors.leftMargin: 12
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: "#3a3a3a"
        }

        Item {
            id: mainHeader
            anchors.left: navSep.right
            anchors.leftMargin: 18
            anchors.right: parent.right
            anchors.top: parent.top
            height: 76

            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.topMargin: 5
                text: "GG / CRYPTO · " + root.asset + " · "
                    + (root.asset === "KAS"
                        ? String(root.kaspa.legend || "PAPER")
                        : (root.legend === "OBSERVE" ? "OBSERVE" : "PAPER"))
                color: root.muted
                font.family: "monospace"
                font.pixelSize: 12
            }
            Text {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 24
                text: root.navLabel(root.page).toUpperCase()
                color: root.ink
                font.family: "monospace"
                font.pixelSize: 18
            }

            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 4
                text: root.dataStatus()
                color: (root.asset === "KAS" ? (root.status.kas_chart || {}).stale : root.liveChart.stale) ? root.ledgerGold : root.muted
                font.family: "monospace"
                font.pixelSize: 12
                elide: Text.ElideRight
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                BufferMark {
                    objectName: "cryptoBuffer"
                    anchors.verticalCenter: parent.verticalCenter
                    active: root.backtestRunning
                        || String(root.lab.label || "") === "LAB STARTING"
                        || root.strategyFactoryRunning
                    cell: 5
                }

                Rectangle {
                    width: labLabel.implicitWidth + 22
                    height: 27
                    color: "#181b1f"
                    border.color: root.lab.healthy ? root.ledgerGreen : "#3c444d"
                    border.width: 1
                    radius: 3
                    Text {
                        id: labLabel
                        anchors.centerIn: parent
                        text: String(root.lab.label || (root.lab.healthy ? "LAB ON" : "LAB OFF"))
                        color: root.lab.healthy ? root.ledgerGreen : root.ledgerGold
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (!root.surfaceHost)
                                return
                            root.statusJson = root.lab.running
                                ? root.surfaceHost.cryptoLabOff()
                                : root.surfaceHost.cryptoLabOn()
                            root.refresh()
                        }
                    }
                }
            }
        }

        Item {
            id: field
            anchors.left: navSep.right
            anchors.leftMargin: 18
            anchors.right: parent.right
            anchors.top: mainHeader.bottom
            anchors.topMargin: 4
            anchors.bottom: parent.bottom

            Column {
                id: portHead
                objectName: "cryptoPortfolioHeader"
                width: parent.width
                spacing: 8
                visible: root.page === "PORTFOLIO"
                CryptoPortfolioSummary {
                    width: parent.width
                    snapshot: root.portfolioView
                    symbol: root.asset
                    mode: root.asset === "KAS" ? "SIMULERAT · KAS COVENANT" : root.legend === "OBSERVE" ? "SOLANA · OBSERVE" : "SIMULERAT · LOCALNET"
                    quantity: root.asset === "KAS" ? String(root.kaspa.value_kas || "0") : String(root.wallet.balance_sol || "—")
                }
                Flow {
                    width: parent.width
                    spacing: 6
                    Repeater {
                        model: ["SOL", "KAS"]
                        delegate: Rectangle {
                            required property var modelData
                            width: 44; height: 20; radius: 3
                            color: root.asset === String(modelData) ? root.selectedPanel : root.panel
                            border.color: root.asset === String(modelData) ? root.ledgerGold : "#494949"
                            Text {
                                anchors.centerIn: parent; text: String(modelData)
                                color: root.asset === String(modelData) ? root.ink : root.muted
                                font.family: "monospace"; font.pixelSize: 12
                            }
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: root.pickAsset(String(modelData))
                            }
                        }
                    }
                    Text {
                        text: "PRISGRAF · ljusintervall"; height: 20; verticalAlignment: Text.AlignVCenter
                        color: root.muted; font.family: "monospace"; font.pixelSize: 10
                        visible: portHead.width > 650
                    }
                    Repeater {
                        model: ["1m", "5m", "15m", "1h", "4h", "1d"]
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool on: root.activeTf === String(modelData)
                            width: tfHead.implicitWidth + 14
                            height: 20
                            radius: 3
                            color: on ? root.selectedPanel : root.panel
                            border.width: 1
                            border.color: on ? root.ledgerGold : root.frameBorder
                            Text {
                                id: tfHead
                                anchors.centerIn: parent
                                text: String(modelData)
                                color: parent.on ? root.ink : root.muted
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: parent.on
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.pickInterval(String(modelData))
                            }
                        }
                    }
                    Text {
                        visible: root.asset === "KAS"
                        text: "Paper"
                        color: String(root.kaspa.network || "paper") === "paper" ? root.ledgerGold : root.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: String(root.kaspa.network || "paper") === "paper"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.pickKasNetwork("paper")
                        }
                    }
                    Text {
                        visible: root.asset === "KAS"
                        text: "Kaspa TN"
                        color: String(root.kaspa.network || "") === "testnet" ? root.ledgerGold : root.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: String(root.kaspa.network || "") === "testnet"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.pickKasNetwork("testnet")
                        }
                    }
                    Text {
                        visible: root.asset === "KAS"
                        text: "Kaspa live"
                        color: String(root.kaspa.network || "") === "mainnet" ? root.ledgerGold : root.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: String(root.kaspa.network || "") === "mainnet"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.pickKasNetwork("mainnet")
                        }
                    }
                }
            }

            Column {
                id: btHead
                width: parent.width
                spacing: 4
                visible: root.page === "BACKTEST"
                Row {
                    spacing: 10
                    Text {
                        text: "LIVE"
                        color: root.botTape === "live" ? "#d8dee9" : "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.botTape === "live"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.botTape = "live"
                        }
                    }
                    Text {
                        visible: (((root.trader.backtest || {}).chart || {}).closes || []).length > 1
                        text: {
                            var t = String((root.trader.backtest || {}).ran_at || "")
                            return "BACKTEST 1  " + String((root.trader.backtest || {}).book || "").toUpperCase() + " " + t
                        }
                        color: root.botTape === "bt0" ? "#d8dee9" : "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.botTape === "bt0"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.botTape = "bt0"
                        }
                    }
                    Text {
                        visible: (((root.trader.backtest_prev || {}).chart || {}).closes || []).length > 1
                        text: {
                            var t = String((root.trader.backtest_prev || {}).ran_at || "")
                            return "BACKTEST 2  " + String((root.trader.backtest_prev || {}).book || "").toUpperCase() + " " + t
                        }
                        color: root.botTape === "bt1" ? "#d8dee9" : "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.botTape === "bt1"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.botTape = "bt1"
                        }
                    }
                    Text {
                        text: root.backtestRunning
                            ? "BACKTEST…"
                            : ("RUN  " + String(root.trader.book || "gg").toUpperCase())
                        color: root.backtestRunning ? "#c8a97e" : "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (!root.surfaceHost || !root.surfaceHost.cryptoBacktestTrader)
                                    return
                                if (root.backtestRunning)
                                    return
                                root.botTape = "live"
                                root.statusJson = root.surfaceHost.cryptoBacktestTrader()
                            }
                        }
                    }
                }
                Row {
                    spacing: 14
                    Text {
                        text: root.trader.armed ? "TRADER OFF" : (root.traderAvailable ? "STARTA VALD BOT" : "OBSERVE")
                        color: root.trader.armed ? "#c8a97e" : "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            enabled: root.traderAvailable
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (!root.surfaceHost)
                                    return
                                root.statusJson = root.surfaceHost.cryptoArmTrader(!root.trader.armed)
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: root.paperTickRunning ? "TICK…" : "TICK"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.statusJson = root.surfaceHost.cryptoTickTrader()
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: "RESET BOOK"
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.statusJson = root.surfaceHost.cryptoResetTrader()
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: root.trader.armed
                            ? "paper ticks 15s · " + String(root.trader.book || "gg")
                            : String(root.trader.book || "gg") + " · paper only"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                }
                Text {
                    width: parent.width
                    visible: root.backtestRunning
                        || String((root.status.backtest_job || {}).state || "") === "error"
                    text: root.backtestRunning
                        ? String((root.status.backtest_job || {}).note || "BACKTEST…")
                        : String((root.status.backtest_job || {}).note || "backtest failed")
                    color: root.backtestRunning ? "#c8a97e" : "#c98989"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: ((root.trader.backtest || {}).comparison || []).length > 0
                    text: root.comparisonText()
                    color: root.text
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: String((root.trader.backtest || {}).tokens || "").length > 0
                        && ((root.trader.backtest || {}).comparison || []).length === 0
                    text: {
                        var bt = root.trader.backtest || {}
                        var best = bt.best_trade || {}
                        var worst = bt.worst_trade || {}
                        var currency = String(bt.quote_currency || "SOL")
                        return String(bt.verdict || "")
                            + "  " + String(bt.fills || 0) + " fills"
                            + "  vault " + String(bt.banked_sol || "") + " " + root.asset
                            + "  win " + String(bt.win_rate || "0") + "%"
                            + "  avg " + String(bt.avg_fills_day || "") + "/d"
                            + (best.profit ? ("  best " + String(best.profit) + " " + currency) : "")
                            + (worst.profit ? ("  worst " + String(worst.profit) + " " + currency) : "")
                            + (bt.pnl_usd
                                ? ("  pnl " + String(bt.pnl_usd) + " " + String(bt.quote_currency || "USDT"))
                                : (bt.pnl_sol ? ("  pnl " + String(bt.pnl_sol) + " " + root.asset) : ""))
                            + (bt.max_drawdown_usd
                                ? ("  maxDD " + String(bt.max_drawdown_usd) + " " + String(bt.quote_currency || "USDT")) : "")
                            + (bt.range ? ("  " + String(bt.range)) : "")
                    }
                    color: String((root.trader.backtest || {}).verdict || "") === "GOOD"
                        ? "#8db89a"
                        : (String((root.trader.backtest || {}).verdict || "") === "WEAK"
                            ? "#c98989"
                            : "#c8a97e")
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: (((root.trader.backtest || {}).weeks || []).length > 0
                        || ((root.trader.backtest || {}).years || []).length > 0)
                        && ((root.trader.backtest || {}).comparison || []).length === 0
                    text: {
                        var bt = root.trader.backtest || {}
                        var start = String(bt.start_sol || "2.000000000")
                        var end = String(bt.equity_sol || bt.tokens || "")
                        var pnl = String(bt.pnl_sol || "")
                        var startUsd = String(bt.start_usd || "")
                        var endUsd = String(bt.end_usd || "")
                        var pnlUsd = String(bt.pnl_usd || "")
                        var usd = String(bt.usd || "")
                        var headline = startUsd
                            ? ("start " + startUsd + " → " + endUsd + " " + String(bt.quote_currency || "USDT") + "  pnl " + pnlUsd
                                + (bt.return_pct !== undefined ? (" (" + String(bt.return_pct) + "%)") : ""))
                            : ("start " + start + " → " + end + " " + root.asset + "  pnl " + pnl + " " + root.asset)
                        if (bt.max_drawdown_usd)
                            headline += "  maxDD $" + String(bt.max_drawdown_usd)
                        if (usd)
                            headline += "  powder $" + usd
                        var parts = [headline]
                        var years = bt.years || []
                        var yp = []
                        var i
                        for (i = 0; i < years.length; i++) {
                            var y = years[i] || {}
                            yp.push(String(y.year || "") + " Δ" + String(y.pnl_sol || "") + " f" + String(y.fills || 0))
                        }
                        if (yp.length)
                            parts.push(yp.join("  ·  "))
                        var gaps = bt.gaps || []
                        var gp = []
                        for (i = 0; i < gaps.length; i++) {
                            var g = gaps[i] || {}
                            gp.push(String(g.from || "") + "…" + String(g.to || "") + " idle " + String(g.months || 0) + "mo")
                        }
                        if (gp.length)
                            parts.push("gaps " + gp.join("  ·  "))
                        var weeks = bt.weeks || []
                        var from = Math.max(0, weeks.length - 12)
                        var wp = []
                        for (i = from; i < weeks.length; i++) {
                            var w = weeks[i] || {}
                            wp.push(String(w.week || "") + " b" + String(w.buys || 0) + "/s" + String(w.sells || 0) + " Δ" + String(w.pnl_sol || "0"))
                        }
                        if (wp.length)
                            parts.push(wp.join("  ·  "))
                        return parts.join("\n")
                    }
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }

            Item {
                id: tapeLoader
                visible: root.page === "PORTFOLIO" || root.page === "BACKTEST"
                clip: true
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: (root.page === "BACKTEST" ? btHead.height : portHead.height) + 6
                anchors.bottom: parent.bottom
                objectName: "cryptoPortfolioChart"
                // Reserve about half of the old chart's height for the holdings below.
                anchors.bottomMargin: root.page === "PORTFOLIO"
                    ? Math.max(0, field.height - anchors.topMargin - Math.min(210, Math.max(110, field.height * 0.32)))
                    : 0

                CryptoChart {
                    id: webTape
                    live: false
                    visible: false
                    width: 0
                    height: 0
                    equity: root.botEquity
                }

                Canvas {
                    id: solPlot
                    anchors.fill: parent
                    renderTarget: Canvas.Image
                    renderStrategy: Canvas.Cooperative
                    antialiasing: true
                    property bool fromZero: false
                    property string tapeAsset: root.page === "BACKTEST" ? "BT" : root.asset
                    property var series: root.page === "BACKTEST"
                        ? ((root.botTapeChart || {}).closes || [])
                        : (root.asset === "KAS"
                            ? ((root.status.kas_chart || {}).closes || [])
                            : (root.closes || []))
                    property var stamps: root.page === "BACKTEST"
                        ? ((root.botTapeChart || {}).times || [])
                        : (root.asset === "KAS"
                            ? ((root.status.kas_chart || {}).times || [])
                            : (root.chartTimes || []))
                    property var marks: root.page === "BACKTEST"
                        ? root.buildTradeMarks(root.botTapeChart, true)
                        : (root.asset === "KAS" ? [] : root.tradeMarks)
                    property int hoverIndex: -1
                    property real viewFrom: 0
                    property real viewTo: 0
                    property bool viewReady: false
                    property string viewKey: ""
                    property real anchorTime: 0
                    property real anchorFrac: 0.5
                    property real anchorSpan: 140
                    property bool historyEnd: false
                    property bool historyBusy: false
                    property bool panning: false
                    property real panX: 0
                    property real panY: 0
                    property real pressY: 0
                    property bool pricePanning: false
                    property int dragMode: 0
                    property int aim: 0
                    property bool priceManual: false
                    property real priceMin: 0
                    property real priceMax: 1
                    readonly property int padL: 8
                    readonly property int padR: 68
                    readonly property int padT: 10
                    readonly property int padB: 22

                    function seriesKey() {
                        if (root.page === "BACKTEST")
                            return "BT:" + root.botTape
                        if (root.asset === "KAS")
                            return "KAS:" + String((root.status.kas_chart || {}).interval || "")
                        return "SOL:" + String((root.sparkChart || {}).interval || "")
                    }

                    function clampView() {
                        var n = (series || []).length
                        if (n < 2)
                            return
                        var span = viewTo - viewFrom
                        var maxSpan = n - 1
                        var minSpan = Math.min(12, maxSpan)
                        if (!(span > 0))
                            span = Math.min(140, maxSpan)
                        if (span < minSpan)
                            span = minSpan
                        if (span > maxSpan)
                            span = maxSpan
                        var left = viewFrom
                        if (left < 0)
                            left = 0
                        if (left + span > maxSpan)
                            left = maxSpan - span
                        viewFrom = left
                        viewTo = left + span
                    }

                    function fitEnd() {
                        priceManual = false
                        var n = (series || []).length
                        if (n < 2) {
                            viewReady = false
                            return
                        }
                        var span = Math.min(n - 1, 140)
                        viewFrom = (n - 1) - span
                        viewTo = n - 1
                        viewReady = true
                        historyEnd = false
                        viewKey = seriesKey()
                    }

                    function rememberView() {
                        var times = stamps || []
                        var span = viewTo - viewFrom
                        var mid = viewFrom + (span > 0 ? span * 0.5 : 0)
                        var i = Math.round(mid)
                        if (i < 0)
                            i = 0
                        if (i > times.length - 1)
                            i = times.length - 1
                        anchorTime = Number(times[i] || 0)
                        anchorFrac = span > 0 ? (mid - viewFrom) / span : 0.5
                        anchorSpan = span > 0 ? span : 140
                    }

                    function restoreView() {
                        var times = stamps || []
                        var n = times.length
                        if (n < 2 || !(anchorTime > 0)) {
                            fitEnd()
                            return
                        }
                        var best = n - 1
                        var bestDiff = Math.abs(Number(times[best] || 0) - anchorTime)
                        var i
                        for (i = 0; i < n; i++) {
                            var diff = Math.abs(Number(times[i] || 0) - anchorTime)
                            if (diff < bestDiff) {
                                bestDiff = diff
                                best = i
                            }
                        }
                        var step = n > 2
                            ? Math.abs(Number(times[1] || 0) - Number(times[0] || 0))
                            : 0
                        if (step > 0 && bestDiff > step * 2) {
                            fitEnd()
                            return
                        }
                        var span = anchorSpan
                        var maxSpan = n - 1
                        if (!(span > 0))
                            span = Math.min(140, maxSpan)
                        if (span > maxSpan)
                            span = maxSpan
                        viewFrom = best - anchorFrac * span
                        viewTo = viewFrom + span
                        viewReady = true
                        viewKey = seriesKey()
                        clampView()
                    }

                    function noteSeries() {
                        hoverIndex = -1
                        var key = seriesKey()
                        if (!viewReady || key !== viewKey)
                            fitEnd()
                        else
                            restoreView()
                        requestPaint()
                    }

                    function indexAt(x) {
                        var n = (series || []).length
                        if (n < 2)
                            return -1
                        var left = viewFrom
                        var right = viewTo
                        if (!viewReady || !(right > left)) {
                            var boot = Math.min(n - 1, 140)
                            left = (n - 1) - boot
                            right = n - 1
                        }
                        var plotW = Math.max(8, width - padL - padR)
                        var t = (x - padL) / plotW
                        if (t < 0)
                            t = 0
                        if (t > 1)
                            t = 1
                        var idx = Math.round(left + t * (right - left))
                        if (idx < 0)
                            idx = 0
                        if (idx > n - 1)
                            idx = n - 1
                        return idx
                    }

                    function panBy(dx) {
                        var n = (series || []).length
                        if (n < 2)
                            return
                        if (!viewReady)
                            fitEnd()
                        var span = viewTo - viewFrom
                        var plotW = Math.max(8, width - padL - padR)
                        if (!(span > 0))
                            return
                        viewFrom -= dx / plotW * span
                        viewTo = viewFrom + span
                        clampView()
                        if (viewFrom < 2)
                            root.pullOlderBars()
                    }

                    // Drag down moves the line down. The price span stays put.
                    function panPrice(dy) {
                        if (!dy)
                            return
                        ensurePriceScale()
                        if (!(priceMax > priceMin))
                            return
                        var plotH = Math.max(8, height - padT - padB)
                        var span = priceMax - priceMin
                        var shift = dy / plotH * span
                        var nextMax = priceMax + shift
                        var nextMin = priceMin + shift
                        var ranged = visibleRange()
                        if (ranged) {
                            var band = Math.max(span, ranged.dataSpan)
                            var bandMin = ranged.minv - band
                            var bandMax = ranged.maxv + band
                            if (nextMax < bandMin) {
                                nextMin += bandMin - nextMax
                                nextMax = bandMin
                            } else if (nextMin > bandMax) {
                                nextMax -= nextMin - bandMax
                                nextMin = bandMax
                            }
                        }
                        priceMax = nextMax
                        priceMin = nextMin
                    }

                    function viewBounds() {
                        var pts = series || []
                        var n = pts.length
                        var left = viewFrom
                        var right = viewTo
                        if (!viewReady || !(right > left)) {
                            var boot = Math.min(n > 0 ? n - 1 : 0, 140)
                            left = (n > 0 ? n - 1 : 0) - boot
                            right = n > 0 ? n - 1 : 0
                        }
                        var i0 = Math.max(0, Math.floor(left))
                        var i1 = n > 0 ? Math.min(n - 1, Math.ceil(right)) : 0
                        if (i1 <= i0)
                            i1 = Math.min(Math.max(n - 1, 0), i0 + 1)
                        return { left: left, right: right, i0: i0, i1: i1, n: n }
                    }

                    function visibleRange() {
                        var pts = series || []
                        var b = viewBounds()
                        if (b.n < 2 || b.i1 < b.i0)
                            return null
                        var minv = Number(pts[b.i0])
                        var maxv = minv
                        var i
                        for (i = b.i0 + 1; i <= b.i1; i++) {
                            var sample = Number(pts[i])
                            if (sample < minv)
                                minv = sample
                            if (sample > maxv)
                                maxv = sample
                        }
                        var span = maxv - minv
                        if (span <= 0)
                            span = Math.abs(maxv) * 0.02 || 1
                        var yPad = span * 0.12
                        return {
                            minv: minv - yPad,
                            maxv: maxv + yPad,
                            dataSpan: span
                        }
                    }

                    function ensurePriceScale() {
                        if (priceManual && priceMax > priceMin)
                            return
                        var ranged = visibleRange()
                        if (!ranged)
                            return
                        priceMin = ranged.minv
                        priceMax = ranged.maxv
                        priceManual = true
                    }

                    function clampPriceSpan(next) {
                        var ranged = visibleRange()
                        var dataSpan = ranged ? ranged.dataSpan : Math.max(next, 1)
                        var floor = Math.max(dataSpan * 0.01, 1e-8)
                        var ceil = Math.max(dataSpan * 80, floor * 4)
                        if (!(next > 0) || next < floor)
                            return floor
                        if (next > ceil)
                            return ceil
                        return next
                    }

                    // Down on the price gutter shrinks the span. Today's price stays put.
                    function scaleAroundLast(factor) {
                        ensurePriceScale()
                        if (!(priceMax > priceMin) || !(factor > 0))
                            return
                        var pts = series || []
                        if (pts.length < 1)
                            return
                        var last = Number(pts[pts.length - 1])
                        if (!isFinite(last))
                            return
                        var span = priceMax - priceMin
                        var t = (priceMax - last) / span
                        if (!(last <= priceMax && last >= priceMin)) {
                            var ranged = visibleRange()
                            if (ranged && ranged.maxv > ranged.minv)
                                t = (ranged.maxv - last) / (ranged.maxv - ranged.minv)
                            else
                                t = 0.5
                        }
                        if (t < 0)
                            t = 0
                        if (t > 1)
                            t = 1
                        var next = clampPriceSpan(span * factor)
                        priceMax = last + t * next
                        priceMin = priceMax - next
                    }

                    function scalePrice(dy, mouseY) {
                        var plotH = Math.max(8, height - padT - padB)
                        scaleAroundLast(Math.exp(-dy / (plotH * 0.55)))
                    }

                    function scalePriceSpan(mouseY, factor) {
                        scaleAroundLast(factor)
                    }

                    function applyZoom(focal, t, next) {
                        var n = (series || []).length
                        if (n < 2)
                            return
                        var maxSpan = n - 1
                        var minSpan = Math.min(12, maxSpan)
                        if (!(next > 0) || next < minSpan)
                            next = minSpan
                        if (next > maxSpan)
                            next = maxSpan
                        if (t < 0)
                            t = 0
                        if (t > 1)
                            t = 1
                        viewFrom = focal - t * next
                        viewTo = viewFrom + next
                        clampView()
                        if (next >= maxSpan - 0.5 || viewFrom < 2)
                            root.pullOlderBars()
                    }

                    function zoomAt(x, zoomIn) {
                        var n = (series || []).length
                        if (n < 2)
                            return
                        if (!viewReady)
                            fitEnd()
                        var span = viewTo - viewFrom
                        var plotW = Math.max(8, width - padL - padR)
                        var t = (x - padL) / plotW
                        if (t < 0)
                            t = 0
                        if (t > 1)
                            t = 1
                        applyZoom(viewFrom + t * span, t, span * (zoomIn ? 0.8 : 1.25))
                    }

                    // Right on the time strip zooms in. The right edge stays on today's price.
                    function scaleTime(dx, x) {
                        var n = (series || []).length
                        if (n < 2)
                            return
                        if (!viewReady)
                            fitEnd()
                        var span = viewTo - viewFrom
                        if (!(span > 0))
                            return
                        var plotW = Math.max(8, width - padL - padR)
                        var factor = Math.exp(-dx / (plotW * 0.45))
                        applyZoom(n - 1, 1, span * factor)
                    }

                    function hitAim(x, y) {
                        if (x >= width - padR)
                            return 1
                        if (y >= height - Math.max(padB, 28))
                            return 2
                        return 0
                    }

                    onTapeAssetChanged: {
                        anchorTime = 0
                        viewReady = false
                        viewKey = ""
                        hoverIndex = -1
                        priceManual = false
                        dragMode = 0
                        aim = 0
                        panning = false
                        pricePanning = false
                        requestPaint()
                    }
                    onSeriesChanged: noteSeries()
                    onViewFromChanged: requestPaint()
                    onViewToChanged: requestPaint()
                    onStampsChanged: requestPaint()
                    onMarksChanged: requestPaint()
                    onHoverIndexChanged: requestPaint()
                    onPriceManualChanged: requestPaint()
                    onPriceMinChanged: requestPaint()
                    onPriceMaxChanged: requestPaint()
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onVisibleChanged: if (visible) requestPaint()
                    onPaint: {
                        var ctx = getContext("2d")
                        var w = width
                        var h = height
                        ctx.clearRect(0, 0, w, h)
                        if (w < 16 || h < 16)
                            return
                        var padL = 8
                        var padR = 68
                        var padT = 10
                        var padB = 22
                        var plotW = Math.max(8, w - padL - padR)
                        var plotH = Math.max(8, h - padT - padB)
                        var pts = series || []
                        var times = stamps || []
                        ctx.fillStyle = "#161616"
                        ctx.fillRect(0, 0, w, h)
                        ctx.strokeStyle = "#242424"
                        ctx.lineWidth = 1
                        var g
                        for (g = 0; g <= 4; g++) {
                            var gy = padT + plotH * g / 4
                            ctx.beginPath()
                            ctx.moveTo(padL, gy)
                            ctx.lineTo(padL + plotW, gy)
                            ctx.stroke()
                        }
                        for (g = 0; g <= 4; g++) {
                            var gx = padL + plotW * g / 4
                            ctx.beginPath()
                            ctx.moveTo(gx, padT)
                            ctx.lineTo(gx, padT + plotH)
                            ctx.stroke()
                        }
                        if (!pts || pts.length < 2)
                            return
                        var bounds = viewBounds()
                        var left = bounds.left
                        var right = bounds.right
                        var i0 = bounds.i0
                        var i1 = bounds.i1
                        var ranged = visibleRange()
                        if (!ranged)
                            return
                        var minv = ranged.minv
                        var maxv = ranged.maxv
                        if (priceManual && priceMax > priceMin) {
                            minv = priceMin
                            maxv = priceMax
                        }
                        var span = maxv - minv
                        if (!(span > 0))
                            return
                        var i
                        function yAt(val) {
                            return padT + (1 - (Number(val) - minv) / span) * plotH
                        }
                        function xAt(index) {
                            var widthSpan = right - left
                            if (widthSpan <= 0)
                                widthSpan = 1
                            return padL + (index - left) / widthSpan * plotW
                        }
                        function money(val) {
                            var n = Number(val)
                            if (!(n > 0))
                                return ""
                            var digits = 2
                            if (n < 1)
                                digits = 5
                            else if (n < 100)
                                digits = 4
                            var step = span / 4
                            if (step > 0 && step < 0.0001)
                                digits = Math.max(digits, 6)
                            else if (step > 0 && step < 0.001)
                                digits = Math.max(digits, 5)
                            else if (step > 0 && step < 0.01)
                                digits = Math.max(digits, 4)
                            else if (step > 0 && step < 0.1)
                                digits = Math.max(digits, 3)
                            return "$" + n.toFixed(Math.min(digits, 8))
                        }
                        ctx.font = "11px monospace"
                        ctx.fillStyle = "#8b949e"
                        ctx.textAlign = "right"
                        ctx.textBaseline = "middle"
                        for (g = 0; g <= 4; g++) {
                            var price = maxv - span * g / 4
                            var ly = padT + plotH * g / 4
                            ctx.fillText(money(price), w - 4, ly)
                        }
                        ctx.textAlign = "center"
                        ctx.textBaseline = "top"
                        var tick = 0
                        for (tick = 0; tick <= 4; tick++) {
                            var idx = Math.round(left + (right - left) * tick / 4)
                            if (idx < 0)
                                idx = 0
                            if (idx > pts.length - 1)
                                idx = pts.length - 1
                            var stamp = Number(times[idx] || 0)
                            if (stamp > 1e12)
                                stamp = Math.floor(stamp / 1000)
                            var label = ""
                            if (stamp > 0) {
                                var when = new Date(stamp * 1000)
                                label = root.twoDigits(when.getHours()) + ":" + root.twoDigits(when.getMinutes())
                                if (tick === 0 || tick === 4)
                                    label = root.twoDigits(when.getDate()) + " " + label
                            }
                            ctx.fillText(label, xAt(idx), padT + plotH + 6)
                        }
                        var up = Number(pts[i1]) >= Number(pts[i0])
                        ctx.save()
                        ctx.beginPath()
                        ctx.rect(padL, padT, plotW, plotH)
                        ctx.clip()
                        ctx.beginPath()
                        ctx.moveTo(xAt(i0), padT + plotH)
                        ctx.lineTo(xAt(i0), yAt(pts[i0]))
                        for (i = i0 + 1; i <= i1; i++)
                            ctx.lineTo(xAt(i), yAt(pts[i]))
                        ctx.lineTo(xAt(i1), padT + plotH)
                        ctx.closePath()
                        ctx.fillStyle = up ? "rgba(141,184,154,0.18)" : "rgba(201,137,137,0.16)"
                        ctx.fill()
                        ctx.beginPath()
                        ctx.moveTo(xAt(i0), yAt(pts[i0]))
                        for (i = i0 + 1; i <= i1; i++)
                            ctx.lineTo(xAt(i), yAt(pts[i]))
                        ctx.strokeStyle = up ? "#8db89a" : "#c98989"
                        ctx.lineWidth = 1.6
                        ctx.stroke()
                        var lastIdx = pts.length - 1
                        var lastY = yAt(pts[lastIdx])
                        var lastInside = lastIdx >= left && lastIdx <= right
                            && lastY >= padT && lastY <= padT + plotH
                        if (lastInside) {
                            ctx.strokeStyle = up ? "#8db89a" : "#c98989"
                            ctx.globalAlpha = 0.45
                            ctx.beginPath()
                            ctx.moveTo(padL, lastY)
                            ctx.lineTo(padL + plotW, lastY)
                            ctx.stroke()
                            ctx.globalAlpha = 1
                        }
                        ctx.restore()
                        if (lastInside) {
                            var tag = money(pts[pts.length - 1])
                            var tagW = ctx.measureText(tag).width + 10
                            var tagX = padL + plotW + 4
                            if (tagX + tagW > w - 2)
                                tagX = w - 2 - tagW
                            var tagY = Math.max(padT, Math.min(padT + plotH - 14, lastY - 7))
                            ctx.fillStyle = up ? "#1c2a22" : "#241818"
                            ctx.fillRect(tagX, tagY, tagW, 14)
                            ctx.fillStyle = up ? "#8db89a" : "#c98989"
                            ctx.textAlign = "left"
                            ctx.textBaseline = "middle"
                            ctx.fillText(tag, tagX + 5, tagY + 7)
                        }
                        var drawn = marks || []
                        for (i = 0; i < drawn.length; i++) {
                            var m = drawn[i] || {}
                            var mi = Math.round(Number(m.i || 0))
                            if (mi < i0 || mi > i1)
                                continue
                            var mx = xAt(mi)
                            var mp = Number(m.px || 0)
                            var my = yAt(mp > 0 ? mp : pts[mi])
                            var buy = String(m.side || "") === "buy"
                            ctx.beginPath()
                            if (buy) {
                                ctx.moveTo(mx, my - 6)
                                ctx.lineTo(mx - 4.5, my + 3)
                                ctx.lineTo(mx + 4.5, my + 3)
                            } else {
                                ctx.moveTo(mx, my + 6)
                                ctx.lineTo(mx - 4.5, my - 3)
                                ctx.lineTo(mx + 4.5, my - 3)
                            }
                            ctx.closePath()
                            ctx.fillStyle = buy ? "#8db89a" : "#c98989"
                            ctx.fill()
                        }
                        var hi = hoverIndex
                        if (hi >= 0 && hi < pts.length && dragMode === 0) {
                            var hx = xAt(hi)
                            var hyRaw = yAt(pts[hi])
                            var hyIn = hyRaw >= padT && hyRaw <= padT + plotH
                            var hy = hyIn ? hyRaw : (hyRaw < padT ? padT + 8 : padT + plotH - 8)
                            ctx.strokeStyle = "#c8a97e"
                            ctx.globalAlpha = 0.7
                            ctx.lineWidth = 1
                            ctx.beginPath()
                            ctx.moveTo(hx, padT)
                            ctx.lineTo(hx, padT + plotH)
                            if (hyIn) {
                                ctx.moveTo(padL, hy)
                                ctx.lineTo(padL + plotW, hy)
                            }
                            ctx.stroke()
                            ctx.globalAlpha = 1
                            if (hyIn) {
                                ctx.beginPath()
                                ctx.arc(hx, hy, 3.2, 0, Math.PI * 2)
                                ctx.fillStyle = "#c8a97e"
                                ctx.fill()
                            }
                            var hStamp = Number(times[hi] || 0)
                            if (hStamp > 1e12)
                                hStamp = Math.floor(hStamp / 1000)
                            var hWhen = ""
                            if (hStamp > 0) {
                                var hDate = new Date(hStamp * 1000)
                                hWhen = root.twoDigits(hDate.getMonth() + 1) + "-"
                                    + root.twoDigits(hDate.getDate()) + " "
                                    + root.twoDigits(hDate.getHours()) + ":"
                                    + root.twoDigits(hDate.getMinutes())
                            }
                            var hPrice = money(pts[hi])
                            var tip = hWhen.length ? (hWhen + "  " + hPrice) : hPrice
                            ctx.font = "11px monospace"
                            var tipW = ctx.measureText(tip).width + 12
                            var tipH = 16
                            var tipX = hx + 10
                            var tipY = hy - tipH - 10
                            if (tipX + tipW > padL + plotW - 4)
                                tipX = hx - tipW - 10
                            if (tipX < padL + 2)
                                tipX = padL + 2
                            if (tipY < padT)
                                tipY = hy + 10
                            if (tipY + tipH > padT + plotH)
                                tipY = padT + plotH - tipH
                            ctx.fillStyle = "#181818"
                            ctx.fillRect(tipX, tipY, tipW, tipH)
                            ctx.strokeStyle = "#c8a97e"
                            ctx.lineWidth = 1
                            ctx.strokeRect(tipX + 0.5, tipY + 0.5, tipW - 1, tipH - 1)
                            ctx.fillStyle = "#e6edf3"
                            ctx.textAlign = "left"
                            ctx.textBaseline = "middle"
                            ctx.fillText(tip, tipX + 6, tipY + tipH / 2)
                            if (hyIn) {
                                var axisTag = hPrice
                                var axisW = ctx.measureText(axisTag).width + 10
                                var axisX = padL + plotW + 4
                                if (axisX + axisW > w - 2)
                                    axisX = w - 2 - axisW
                                var axisY = Math.max(padT, Math.min(padT + plotH - 14, hy - 7))
                                ctx.fillStyle = "#2a261c"
                                ctx.fillRect(axisX, axisY, axisW, 14)
                                ctx.fillStyle = "#c8a97e"
                                ctx.fillText(axisTag, axisX + 5, axisY + 7)
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton
                        preventStealing: true
                        cursorShape: solPlot.dragMode === 1 ? Qt.ClosedHandCursor
                            : (solPlot.dragMode === 2 || (solPlot.dragMode === 0 && solPlot.aim === 1)) ? Qt.SizeVerCursor
                            : (solPlot.dragMode === 3 || (solPlot.dragMode === 0 && solPlot.aim === 2)) ? Qt.SizeHorCursor
                            : Qt.CrossCursor
                        onPressed: function(mouse) {
                            var zone = solPlot.hitAim(mouse.x, mouse.y)
                            solPlot.aim = zone
                            solPlot.panX = mouse.x
                            solPlot.panY = mouse.y
                            solPlot.pressY = mouse.y
                            solPlot.pricePanning = false
                            solPlot.hoverIndex = -1
                            solPlot.panning = zone === 0
                            if (zone === 1)
                                solPlot.dragMode = 2
                            else if (zone === 2)
                                solPlot.dragMode = 3
                            else
                                solPlot.dragMode = 1
                        }
                        onReleased: {
                            solPlot.panning = false
                            solPlot.pricePanning = false
                            solPlot.dragMode = 0
                        }
                        onCanceled: {
                            solPlot.panning = false
                            solPlot.pricePanning = false
                            solPlot.dragMode = 0
                        }
                        onDoubleClicked: function(mouse) {
                            if (solPlot.hitAim(mouse.x, mouse.y) === 1) {
                                solPlot.priceManual = false
                                return
                            }
                            solPlot.fitEnd()
                        }
                        onPositionChanged: function(mouse) {
                            if (solPlot.dragMode === 1) {
                                var dx = mouse.x - solPlot.panX
                                var dy = mouse.y - solPlot.panY
                                solPlot.panX = mouse.x
                                solPlot.panY = mouse.y
                                if (dx)
                                    solPlot.panBy(dx)
                                var vertical = solPlot.pricePanning || solPlot.priceManual
                                    || Math.abs(mouse.y - solPlot.pressY) >= 4
                                if (vertical) {
                                    var step = (solPlot.pricePanning || solPlot.priceManual)
                                        ? dy : (mouse.y - solPlot.pressY)
                                    solPlot.pricePanning = true
                                    if (step)
                                        solPlot.panPrice(step)
                                }
                                return
                            }
                            if (solPlot.dragMode === 2) {
                                var dy = mouse.y - solPlot.panY
                                solPlot.panY = mouse.y
                                solPlot.scalePrice(dy, mouse.y)
                                return
                            }
                            if (solPlot.dragMode === 3) {
                                var tx = mouse.x - solPlot.panX
                                solPlot.panX = mouse.x
                                solPlot.scaleTime(tx, mouse.x)
                                return
                            }
                            solPlot.aim = solPlot.hitAim(mouse.x, mouse.y)
                            solPlot.hoverIndex = solPlot.aim === 0 ? solPlot.indexAt(mouse.x) : -1
                        }
                        onExited: {
                            if (solPlot.dragMode === 0) {
                                solPlot.hoverIndex = -1
                                solPlot.aim = 0
                            }
                        }
                        onWheel: function(wheel) {
                            var dy = wheel.angleDelta.y
                            if (!dy)
                                dy = wheel.pixelDelta.y
                            if (solPlot.hitAim(wheel.x, wheel.y) === 1 && dy) {
                                solPlot.scalePriceSpan(wheel.y, dy > 0 ? 0.8 : 1.25)
                                wheel.accepted = true
                                return
                            }
                            if (wheel.modifiers & Qt.ShiftModifier || Math.abs(wheel.angleDelta.x) > Math.abs(dy)) {
                                var dx = wheel.angleDelta.x
                                if (!dx)
                                    dx = wheel.pixelDelta.x
                                if (!dx)
                                    dx = dy
                                solPlot.panBy(dx)
                            } else if (dy)
                                solPlot.zoomAt(wheel.x, dy > 0)
                            wheel.accepted = true
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: root.page === "PORTFOLIO" && (
                        root.asset === "KAS"
                            ? (((root.status.kas_chart || {}).closes || []).length < 2)
                            : root.closes.length < 2
                    )
                    text: root.asset === "KAS"
                        ? (String((root.status.kas_chart || {}).error || "").length
                            ? "KAS-tape saknas"
                            : "Hämtar KAS-tape…")
                        : (String((root.liveChart || {}).error || "").length ? "SOL-prisdata saknas" : "Hämtar SOL-prisdata…")
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 13
                }
            }

            Item {
                id: portfolioBottom
                objectName: "cryptoPortfolioBottom"
                visible: root.page === "PORTFOLIO"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: tapeLoader.bottom
                anchors.topMargin: 12
                anchors.bottom: parent.bottom
                CryptoHoldings {
                    id: holdingsTable
                    anchors.fill: parent
                    anchors.bottomMargin: walletTools.height + walletBar.height + 8 + recentActivity.height + (recentActivity.visible ? 8 : 0)
                    assets: root.portfolioView.assets || []
                    selectedSymbol: root.asset
                    onAssetSelected: function(symbol) { root.pickAsset(symbol) }
                }
                Item {
                    id: recentActivity
                    readonly property real freeHeight: portfolioBottom.height - walletTools.height - walletBar.height - 8
                    visible: root.asset === "SOL" && root.connected && root.ledger.length > 0
                        && (root.portfolioView.assets || []).length <= 2 && freeHeight > 230
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.bottom: walletTools.top; anchors.bottomMargin: 2
                    height: visible ? 132 : 0
                    Column {
                        width: parent.width; spacing: 9
                        Text {
                            text: "SENASTE AKTIVITET"; color: root.ledgerGold
                            font.family: "monospace"; font.pixelSize: 11; font.bold: true
                        }
                        Repeater {
                            model: Math.min(2, root.ledger.length)
                            delegate: Column {
                                width: recentActivity.width; spacing: 3
                                readonly property var row: root.ledger[index] || {}
                                Text {
                                    width: parent.width; elide: Text.ElideRight
                                    text: String(parent.row.side || "EVENT").toUpperCase() + " · " + String(parent.row.mode || "") + " · " + String(parent.row.status || "")
                                    color: parent.row.error ? "#c98989" : root.ink
                                    font.family: "monospace"; font.pixelSize: 11
                                }
                                Text {
                                    width: parent.width; elide: Text.ElideRight
                                    text: String(parent.row.hint || parent.row.error || "")
                                    color: root.muted; font.family: "monospace"; font.pixelSize: 11
                                }
                            }
                        }
                    }
                }
                Flickable {
                    id: walletTools
                    objectName: "cryptoWalletTools"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: walletBar.top
                    anchors.bottomMargin: 6
                    height: root.walletToolsOpen ? Math.min(contentHeight + 6, 146, portfolioBottom.height * 0.52) : 0
                    visible: root.walletToolsOpen
                    clip: true
                    contentHeight: root.asset === "KAS" ? kasFoot.height : portFoot.height
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Column {
                id: portFoot
                width: parent.width
                spacing: 6
                visible: root.asset !== "KAS"
                Row {
                    spacing: 8
                    width: parent.width
                    GgField {
                        id: pubkeyField
                        width: Math.max(120, parent.width - 80)
                        height: 26
                        placeholderText: "Solana pubkey"
                        text: String(root.wallet.pubkey || "")
                    }
                    Text {
                        text: "CONNECT"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.connectWatch()
                        }
                    }
                }
                Flow {
                    width: parent.width
                    spacing: 12
                    Text {
                        text: "CREATE TEST WALLET"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.surfaceHost.cryptoCreateTestWallet()
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: "AIRDROP 100 SOL"
                        color: "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.surfaceHost.cryptoAirdrop()
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: "IMPORT KEYPAIR"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: keypairDialog.open()
                        }
                    }
                    Text {
                        text: "DISCONNECT"
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.surfaceHost.cryptoDisconnect()
                                root.refresh()
                            }
                        }
                    }
                }
            }

            Column {
                id: kasFoot
                width: parent.width
                spacing: 6
                visible: root.asset === "KAS"
                Flow {
                    width: parent.width
                    spacing: 14
                    Text {
                        text: "GENESIS"
                        color: "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost && root.surfaceHost.cryptoKaspaGenesis)
                                    root.statusJson = root.surfaceHost.cryptoKaspaGenesis()
                            }
                        }
                    }
                    Text {
                        text: "ADD 5"
                        color: "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost && root.surfaceHost.cryptoKaspaTransition)
                                    root.statusJson = root.surfaceHost.cryptoKaspaTransition("add", 5)
                            }
                        }
                    }
                    Text {
                        text: "SUB 3"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost && root.surfaceHost.cryptoKaspaTransition)
                                    root.statusJson = root.surfaceHost.cryptoKaspaTransition("subtract", 3)
                            }
                        }
                    }
                    Text {
                        text: "SILVERC"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost && root.surfaceHost.cryptoKaspaCompile)
                                    root.statusJson = root.surfaceHost.cryptoKaspaCompile()
                            }
                        }
                    }
                }
                Text {
                    width: parent.width
                    text: String(root.kaspa.address || "No covenant yet. GENESIS funds 1 KAS on paper.")
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }
                Text {
                    width: parent.width
                    visible: String(root.kaspa.covenant_id || "").length > 0
                    text: "cov  " + String(root.kaspa.covenant_id || "")
                    color: "#7f8994"
                    font.family: "monospace"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }
                Text {
                    width: parent.width
                    visible: root.kaspa.mainnet_observe === true
                    text: "Mainnet is observe-only. Covenant steps stay on paper."
                    color: root.ledgerGold
                    font.family: "monospace"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    visible: String(root.kaspa.compile_note || "").length > 0
                    text: String(root.kaspa.compile_note || "")
                    color: root.kaspa.compiled ? "#8db89a" : root.ledgerGold
                    font.family: "monospace"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    visible: (root.kaspa.history || []).length === 0
                    text: String(root.kaspa.hint || "Covenant id stays. Address changes with count.")
                    color: "#8b949e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Repeater {
                    model: Math.min(3, (root.kaspa.history || []).length)
                    delegate: Text {
                        width: kasFoot.width
                        readonly property var row: (root.kaspa.history || [])[
                            (root.kaspa.history || []).length - 1 - index
                        ] || {}
                        text: String(row.op || "")
                            + "  count=" + String(row.count)
                            + "  " + String(row.note || "")
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }
            }

                }
                Item {
                    id: walletBar
                    width: parent.width; height: 28
                    anchors.bottom: parent.bottom
                    Rectangle { width: parent.width; height: 1; color: "#353535" }
                    Text {
                        anchors.left: parent.left; anchors.right: walletLinks.left; anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.asset === "KAS" ? "KAS covenant · simulerat saldo" : root.connected ? root.shortKey(root.wallet.pubkey) + " · " + String(root.wallet.network || root.legend)
                            + (root.portfolioView.unpriced_count > 0 ? " · " + root.portfolioView.unpriced_count + " utan pris" : "")
                            + (root.portfolioView.unknown_balance_count > 0 ? " · saldo saknas" : "") : "Ingen plånbok ansluten"
                        color: root.muted; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight
                    }
                    Row {
                        id: walletLinks
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        spacing: 18
                        Text {
                            text: "AKTIVITET"; color: root.ledgerGold; font.family: "monospace"; font.pixelSize: 11
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.page = "ACTIVITY" }
                        }
                        Text {
                            text: (root.walletToolsOpen ? "▾ " : "▸ ") + (root.asset === "KAS" ? "COVENANT" : "PLÅNBOK")
                            color: root.ledgerGold; font.family: "monospace"; font.pixelSize: 11
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.walletToolsOpen = !root.walletToolsOpen }
                        }
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "TRADER"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: traderCol.height
                Column {
                    id: traderCol
                    width: parent.width
                    spacing: 8
                    Flow {
                        width: parent.width
                        spacing: 14
                        Text {
                            text: root.trader.armed ? "TRADER OFF" : (root.traderAvailable ? "STARTA VALD BOT" : "OBSERVE")
                            color: root.trader.armed ? "#c8a97e" : "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                            MouseArea {
                                enabled: root.traderAvailable
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (!root.surfaceHost)
                                        return
                                    root.statusJson = root.surfaceHost.cryptoArmTrader(!root.trader.armed)
                                    root.refresh()
                                }
                            }
                        }
                        Text {
                            text: root.paperTickRunning ? "TICK…" : (root.traderAvailable ? "UPPDATERA ALLA" : "OBSERVE")
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (root.surfaceHost)
                                        root.statusJson = root.surfaceHost.cryptoTickTrader()
                                    root.refresh()
                                }
                            }
                        }
                        Text {
                            text: root.backtestRunning ? "BACKTEST…" : "BACKTEST"
                            color: root.backtestRunning ? "#c8a97e" : "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (!root.surfaceHost || !root.surfaceHost.cryptoBacktestTrader)
                                        return
                                    if (root.backtestRunning)
                                        return
                                    root.page = "BACKTEST"
                                    root.botTape = "live"
                                    root.statusJson = root.surfaceHost.cryptoBacktestTrader()
                                }
                            }
                        }
                        Text {
                            text: "RESET"
                            color: "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (root.surfaceHost)
                                        root.statusJson = root.surfaceHost.cryptoResetTrader()
                                    root.refresh()
                                }
                            }
                        }
                    }
                    CryptoPaperAccounts {
                        width: parent.width
                        engine: root.status.paper_engine || ({})
                        canStart: root.traderAvailable
                        surfaceHost: root.surfaceHost
                        onStatusChanged: function(json) { root.statusJson = json; root.refresh() }
                    }
                    Text {
                        width: parent.width
                        text: "Välj bot i menyn ovan. RESET återställer endast vald bots papperskonto; resultatet sparas som en tidigare körning."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: "KEEP / WATCH / PARK are editorial labels. Compare measured results in Backtest. All six books support persistent paper execution. Live venue execution still requires its own integration."
                        color: "#8b949e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: root.trader.books || []
                        delegate: Text {
                            required property var modelData
                            width: traderCol.width
                            text: String(modelData.name || modelData.id || "")
                                + "  " + String(modelData.verdict || "")
                                + "  " + String(modelData.why || "")
                            color: {
                                var verdict = String(modelData.verdict || "")
                                if (verdict === "KEEP")
                                    return "#8db89a"
                                if (verdict === "PARK")
                                    return "#c98989"
                                return "#c8a97e"
                            }
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            Column {
                anchors.fill: parent
                visible: root.page === "SIGNAL"
                spacing: 8
                Text {
                    width: parent.width
                    text: String(root.bot.symbol || "SOLUSDT") + "  5m  ·  size " + String(root.bot.size_sol || "0.01") + " SOL"
                    color: "#d8dee9"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
                Text {
                    width: parent.width
                    text: {
                        var last = root.bot.last || {}
                        var side = String(last.super || "none")
                        if (side === "none" && !last.buy_votes && !last.sell_votes)
                            return "NO SUPER"
                        var line = side.toUpperCase() + "   votes " + String(last.buy_votes || 0) + "/" + String(last.sell_votes || 0)
                        var rsi = last.rsi14
                        if (rsi !== undefined && rsi !== null && rsi !== "")
                            line += "   RSI " + Number(rsi).toFixed(1)
                        return line
                    }
                    color: String((root.bot.last || {}).super || "") === "buy"
                        ? "#8db89a"
                        : (String((root.bot.last || {}).super || "") === "sell" ? "#c98989" : "#8b949e")
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: ((root.bot.last || {}).notes || []).length > 0
                    text: ((root.bot.last || {}).notes || []).join(" · ")
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Row {
                    spacing: 14
                    Text {
                        text: "EVAL SIGNALS"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.surfaceHost.cryptoEvalSignals()
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: root.bot.armed ? "DISARM" : "ARM BOT"
                        color: root.bot.armed ? "#c8a97e" : "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (!root.surfaceHost)
                                    return
                                root.statusJson = root.surfaceHost.cryptoArmBot(!root.bot.armed)
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: "TEST BUY 0.01 SOL"
                        color: "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.paperSignal()
                        }
                    }
                }
                Text {
                    text: root.bot.armed
                        ? "Ticks every 30s. Lab fill on super buy/sell."
                        : (root.connected
                            ? "Strategy004 on SOLUSDT. EVAL then ARM for lab fills."
                            : "CREATE TEST WALLET, then AIRDROP 100 SOL.")
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }

            Column {
                anchors.fill: parent
                visible: root.page === "ARB"
                spacing: 8
                Text {
                    width: parent.width
                    text: "A " + String(root.arb.price_a || "—") + "    B " + String(root.arb.price_b || "—") + "    USDC/SOL"
                    color: "#d8dee9"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    text: {
                        var fire = root.arb.optimal_ok ? "FIRE" : "DROP"
                        var line = fire
                            + "  size " + String(root.arb.optimal_usd || "—")
                            + "  tip " + String(root.arb.optimal_tip || "—")
                            + "  net " + String(root.arb.optimal_net || "—")
                        var drop = String(root.arb.optimal_drop || "")
                        if (drop.length)
                            line += "  " + drop
                        var buy = String(root.arb.buy_pool || "")
                        var sell = String(root.arb.sell_pool || "")
                        if (buy.length && sell.length)
                            line += "  buy " + buy + " sell " + sell
                        return line
                    }
                    color: root.arb.optimal_ok ? "#8db89a" : "#c98989"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: String((root.status.arb_last || {}).txid || "").length > 0
                        || String((root.status.arb_last || {}).error || "").length > 0
                    text: {
                        var last = root.status.arb_last || {}
                        var line = String(last.txid || "")
                        if (last.profit)
                            line += "   profit " + String(last.profit)
                        if (last.error)
                            line += "   " + String(last.error)
                        return line
                    }
                    color: (root.status.arb_last || {}).error ? "#c98989" : "#8db89a"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
                }
                Row {
                    spacing: 14
                    Text {
                        text: "FLASH ARB"
                        color: "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.statusJson = root.surfaceHost.cryptoFlashArb()
                                root.refresh()
                            }
                        }
                    }
                    Text {
                        text: "RESET POOLS"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.surfaceHost)
                                    root.statusJson = root.surfaceHost.cryptoFlashArbReset()
                                root.refresh()
                            }
                        }
                    }
                }
                Text {
                    width: parent.width
                    text: "Paper CPMM. Tip is half the gross, where a Jito auction starts. The bundle drops when the tip eats the edge. Not a live searcher. Mainnet stays observe-only."
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }

            Flickable {
                id: factoryScroll
                objectName: "cryptoFactoryScroll"
                anchors.fill: parent
                visible: root.page === "FACTORY"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: factoryCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: factoryCol
                    width: factoryScroll.width
                    height: childrenRect.height
                    spacing: 8

                    Text {
                        text: "STRATEGY FACTORY"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        text: "ECC LOOP  ·  BOUNDED WORKERS  ·  PAPER ONLY"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: factoryCol.width
                        text: "Hypothesis → backtest → validation → paper review. "
                            + "This surface never places orders and never arms a wallet."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Row {
                        spacing: 14
                        Text {
                            text: root.strategyFactoryRunning ? "RUNNING…" : "RUN FACTORY"
                            color: root.strategyFactoryRunning ? "#c8a97e" : "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (root.strategyFactoryRunning
                                            || !root.surfaceHost
                                            || !root.surfaceHost.cryptoStrategyFactory)
                                        return
                                    root.statusJson = root.surfaceHost.cryptoStrategyFactory()
                                }
                            }
                        }
                        Text {
                            text: "RESET"
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (!root.surfaceHost
                                            || !root.surfaceHost.cryptoStrategyFactoryReset)
                                        return
                                    root.statusJson = root.surfaceHost.cryptoStrategyFactoryReset()
                                }
                            }
                        }
                    }
                    Text {
                        width: factoryCol.width
                        text: "STATE · "
                            + String(root.strategyFactoryJob.state || "idle").toUpperCase()
                            + "  ·  " + String(root.strategyFactoryJob.note || root.strategyFactoryResult.note || "")
                        color: root.strategyFactoryRunning ? "#c8a97e" : "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: factoryCol.width
                        visible: root.strategyFactoryResult.source !== undefined
                        text: {
                            var source = root.strategyFactoryResult.source || {}
                            var split = root.strategyFactoryResult.split || {}
                            return "SOURCE · " + String(source.symbol || "SOLUSDT")
                                + "  " + String(source.interval || "—")
                                + "  " + String(source.bars || 0) + " bars"
                                + "  friction " + String(source.fee_bps || 0)
                                + "+" + String(source.slippage_bps || 0) + " bps"
                                + "\nSPLIT · train " + String(split.train_pct || 60)
                                + "%  validate " + String(split.validation_pct || 20)
                                + "%  test " + String(split.test_pct || 20) + "%"
                                + "\n" + String(source.from || "") + " → " + String(source.to || "")
                        }
                        color: "#8fa8a0"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: factoryCol.width
                        text: "ROLES · " + root.factoryRolesText()
                            + "\nGATES · " + (((root.strategyFactoryResult.orchestration || {}).gates || []).join("  ·  "))
                        color: "#7f8994"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: (root.strategyFactoryResult.candidates || []).length
                        delegate: Rectangle {
                            required property int index
                            width: factoryCol.width
                            height: candidateBody.implicitHeight + 16
                            color: "#121212"
                            border.width: 1
                            border.color: "#4c4c4c"
                            radius: 2

                            Column {
                                id: candidateBody
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 4
                                readonly property var row:
                                    (root.strategyFactoryResult.candidates || [])[index] || {}
                                Text {
                                    width: candidateBody.width
                                    text: String(candidateBody.row.label || candidateBody.row.id || "CANDIDATE")
                                        + "  [" + String(candidateBody.row.verdict || "—") + "]"
                                    color: String(candidateBody.row.verdict || "") === "PASS"
                                        ? "#8db89a"
                                        : (String(candidateBody.row.verdict || "") === "REJECT"
                                            ? "#c98989" : "#c8a97e")
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                Text {
                                    width: candidateBody.width
                                    text: String(candidateBody.row.hypothesis || "")
                                    color: "#a8b0b8"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    width: candidateBody.width
                                    text: "TRAIN  " + root.factoryMetric(candidateBody.row.train)
                                        + "\nVALID  " + root.factoryMetric(candidateBody.row.validation)
                                        + "\nTEST   " + root.factoryMetric(candidateBody.row.test)
                                    color: "#c8cdd4"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    width: candidateBody.width
                                    text: String(candidateBody.row.gate_reason || "")
                                    color: "#7f8994"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                    Text {
                        width: factoryCol.width
                        visible: (root.strategyFactoryResult.candidates || []).length === 0
                        text: "No factory result yet. Run the bounded local research loop."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: factoryCol.width
                        visible: ((root.strategyFactoryResult.graveyard || []).length > 0)
                        text: "GRAVEYARD · negative results kept · "
                            + String((root.strategyFactoryResult.graveyard || []).length)
                            + "  ·  " + root.factoryGraveyardText()
                        color: "#c98989"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: factoryCol.width
                        visible: (root.strategyFactoryResult.autoresearch || {}).steps !== undefined
                        text: "AUTORESEARCH · KEEP/REVERT  best buffer "
                            + String((root.strategyFactoryResult.autoresearch || {}).best_buffer_bps || "—")
                            + "  validation Sharpe "
                            + String((root.strategyFactoryResult.autoresearch || {}).best_validation_sharpe || "—")
                            + "\nTwo expanding validation folds · " + String((root.strategyFactoryResult.autoresearch || {}).trial_count || 0)
                            + " trials · frozen final test: " + root.factoryMetric((root.strategyFactoryResult.autoresearch || {}).final_test)
                            + "\n" + root.factoryAutoresearchText()
                        color: "#8fa8a0"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Flickable {
                id: deskScroll
                anchors.fill: parent
                visible: root.page === "DESK"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: deskCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: deskCol
                    width: deskScroll.width
                    height: childrenRect.height
                    spacing: 8

                    Text {
                        text: "PAPER DESK"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        text: "SIX SEATS  ·  FRONT MAN IN CODE  ·  OBSERVE ONLY"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: deskCol.width
                        text: "456 volume-leads-price. 067 crowd spike. 218 vol size. "
                            + "240 invalidation. 001 reports only. Front Man is a hard veto, not a prompt."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Row {
                        spacing: 14
                        Text {
                            text: root.deskRunning ? "RUNNING…" : "SIT THE DESK"
                            color: root.deskRunning ? "#c8a97e" : "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (root.deskRunning
                                            || !root.surfaceHost
                                            || !root.surfaceHost.cryptoDesk)
                                        return
                                    root.statusJson = root.surfaceHost.cryptoDesk()
                                }
                            }
                        }
                        Text {
                            text: "RESET"
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (!root.surfaceHost || !root.surfaceHost.cryptoDeskReset)
                                        return
                                    root.statusJson = root.surfaceHost.cryptoDeskReset()
                                }
                            }
                        }
                    }
                    Text {
                        width: deskCol.width
                        text: "STATE · " + String(root.deskJob.state || "idle").toUpperCase()
                            + "  ·  LIGHT "
                            + String((root.desk.front_man || {}).light || "RED")
                            + "  ·  trades " + String(root.desk.trades || 0)
                            + "  ·  equity " + String(root.desk.equity_pct || 0) + "%"
                            + "  ·  red lights " + String(root.desk.red_lights || 0)
                        color: String((root.desk.front_man || {}).light || "") === "GREEN"
                            ? "#8db89a" : "#c98989"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: deskCol.width
                        text: "VOL · HMM "
                            + String(((root.desk.vol || {}).hmm || {}).last_state || "UNKNOWN")
                            + "  GARCH σ "
                            + String(((root.desk.vol || {}).garch || {}).last_sigma || "—")
                            + "  size " + String((root.desk.vol || {}).size_scale || "—")
                        color: "#8fa8a0"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: (root.desk.seats || []).length
                        delegate: Rectangle {
                            required property int index
                            width: deskCol.width
                            height: seatBody.implicitHeight + 14
                            color: "#121212"
                            border.width: 1
                            border.color: "#4c4c4c"
                            radius: 2
                            Column {
                                id: seatBody
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 2
                                readonly property var row:
                                    (root.desk.seats || [])[index] || {}
                                Text {
                                    width: seatBody.width
                                    text: String(seatBody.row.id || "SEAT")
                                        + "  " + String(seatBody.row.job || "")
                                        + "  [" + String(seatBody.row.vote || "—") + "]"
                                    color: "#c8cdd4"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                Text {
                                    width: seatBody.width
                                    text: {
                                        var r = seatBody.row
                                        var parts = []
                                        if (r.vol_z !== undefined) parts.push("volume z " + String(r.vol_z))
                                        if (r.move_bps !== undefined) parts.push("price move " + String(r.move_bps) + " bps")
                                        if (r.size_scale !== undefined) parts.push("position scale " + String(r.size_scale) + " · regime " + String(r.regime || "—"))
                                        if (r.level !== undefined) parts.push("invalidation level " + String(r.level) + " · " + (r.hit ? "crossed" : "clear"))
                                        if (r.light !== undefined) parts.push("board " + String(r.light) + " · reports only")
                                        return parts.join("  ·  ")
                                    }
                                    color: "#7f8994"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    elide: Text.ElideRight
                                    maximumLineCount: 2
                                }
                            }
                        }
                    }
                    Text {
                        width: deskCol.width
                        visible: ((root.desk.front_man || {}).reasons || []).length > 0
                        text: "FRONT MAN · "
                            + ((root.desk.front_man || {}).reasons || []).join("  ·  ")
                        color: "#c98989"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: deskCol.width
                        visible: (root.desk.seats || []).length === 0
                        text: "No sitting yet. Paper only. Kill switch is in code."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Flickable {
                id: polyScroll
                anchors.fill: parent
                visible: root.page === "POLY"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: polyCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: polyCol
                    width: polyScroll.width
                    height: childrenRect.height
                    spacing: 8

                    Text {
                        text: "POLYMARKET RESEARCH"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        text: "PENDULUMFLOW V3  ·  REMOTE PARQUET  ·  READ ONLY"
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: polyCol.width
                        text: "One UTC hour per query. No wallet, order placement or automatic archive sync is connected."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Row {
                        width: polyCol.width
                        spacing: 8
                        Text {
                            text: "UTC"
                            color: "#a8b0b8"
                            font.family: "monospace"
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        GgField {
                            id: polyDateField
                            width: 112
                            height: 26
                            placeholderText: "YYYY-MM-DD"
                            text: root.polyDate
                        }
                        GgField {
                            id: polyHourField
                            width: 54
                            height: 26
                            placeholderText: "HH"
                            text: root.polyHour
                        }
                    }

                    Row {
                        width: polyCol.width
                        spacing: 12
                        Text {
                            text: "SUMMARY"
                            color: root.polyPreset === "SUMMARY" ? "#d8dee9" : "#a8b0b8"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.polyPreset === "SUMMARY"
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.polyPreset = "SUMMARY"
                            }
                        }
                        Text {
                            text: "TRADES"
                            color: root.polyPreset === "TRADES" ? "#d8dee9" : "#a8b0b8"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.polyPreset === "TRADES"
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.polyPreset = "TRADES"
                            }
                        }
                        Text {
                            text: "TOUCH"
                            color: root.polyPreset === "TOUCH" ? "#d8dee9" : "#a8b0b8"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.polyPreset === "TOUCH"
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.polyPreset = "TOUCH"
                            }
                        }
                        Text {
                            text: "SCAN"
                            color: root.polyPreset === "SCAN" ? "#d8dee9" : "#a8b0b8"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.polyPreset === "SCAN"
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.polyPreset = "SCAN"
                            }
                        }
                    }

                    Row {
                        width: polyCol.width
                        spacing: 8
                        Text {
                            text: "SLUG"
                            color: root.polyPreset === "TOUCH" ? "#c8cdd4" : "#5d6670"
                            font.family: "monospace"
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        GgField {
                            id: polySlugField
                            width: Math.max(120, polyCol.width - 58)
                            height: 26
                            enabled: root.polyPreset === "TOUCH"
                            placeholderText: "market slug for TOUCH / optional otherwise"
                            text: root.polySlug
                        }
                    }

                    Row {
                        spacing: 14
                        Text {
                            text: root.polyRunning ? "READING…" : "RUN QUERY"
                            color: root.polyRunning ? "#c8a97e" : "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.runPolymarketQuery()
                            }
                        }
                        Text {
                            text: root.polyRunning ? "CANCEL QUERY" : "RESET"
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.resetPolymarketQuery()
                            }
                        }
                    }

                    Text {
                        width: polyCol.width
                        text: {
                            var state = String(root.polymarket.state || "IDLE").toUpperCase()
                            var mode = String(root.polymarket.preset || root.polyPreset || "SUMMARY")
                            return "STATE · " + state + "  ·  " + mode
                        }
                        color: root.polyRunning ? "#c8a97e" : "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: polyCol.width
                        text: String(root.polymarket.note || "")
                        visible: text.length > 0
                        color: String(root.polymarket.state || "") === "error" ? "#c98989" : "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: polyCol.width
                        text: "BUDGET · 512 MiB · 2 threads · 30s SQL timeout · 2 GiB source limit · 240 result rows"
                            + "\nOutcomes are grouped separately by asset. TOUCH resolves the market outside the selected archive hour."
                            + "\n" + String((root.polyResult.source_metadata || {}).coverage || "Feed completeness is not verified.")
                            + ((root.polyResult.source_metadata || {}).bytes ? " · source " + String(Math.round(root.polyResult.source_metadata.bytes / 1048576)) + " MiB" : "")
                        color: root.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: polyCol.width
                        text: "ARCHIVE · " + String(root.polymarket.url || "")
                        visible: String(root.polymarket.url || "").length > 0
                        color: "#8fa8a0"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        width: polyCol.width
                        text: "SQL PREVIEW\n" + String(root.polymarket.sql || "")
                        visible: String(root.polymarket.sql || "").length > 0
                        color: "#7f8994"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        width: polyCol.width
                        text: ((root.polyResult || {}).lines || []).join("\n")
                        visible: ((root.polyResult || {}).lines || []).length > 0
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        width: polyCol.width
                        visible: !root.polyRunning
                            && ((root.polyResult || {}).lines || []).length === 0
                            && String(root.polymarket.state || "") !== "error"
                        text: "No result yet. SUMMARY and TRADES need only a UTC hour; TOUCH also needs a market slug."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: polyCol.width
                        text: "POLY_DATA · " + String((root.polymarket.poly_data || {}).state || "OPTIONAL")
                            + "\n" + String((root.polymarket.poly_data || {}).note || "")
                        color: "#7f8994"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "ACTIVITY"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: ledCol.height
                Column {
                    id: ledCol
                    width: parent.width
                    spacing: 6
                    Text {
                        visible: root.ledger.length === 0
                        text: "No fills yet."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Repeater {
                        model: root.ledger.length
                        delegate: Row {
                            width: ledCol.width
                            spacing: 10
                            readonly property var row: root.ledger[index] || {}
                            Text {
                                width: 64
                                text: String(row.side || "").toUpperCase()
                                color: row.error ? "#c98989" : (String(row.side || "") === "buy" ? "#8db89a" : "#c8a97e")
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: true
                            }
                            Text {
                                width: parent.width - 74
                                text: {
                                    var hint = String(row.hint || "")
                                    var modes = {"PAPER":"Paper", "LOCALNET_DIAGNOSTIC":"Localnet self-transfer", "TESTNET":"Legacy localnet", "OBSERVE":"Observe"}
                                    var mode = modes[String(row.mode || "")] || "Mode not recorded"
                                    var state = String(row.status || "unrecorded confirmation")
                                    var chain = row.chain_status ? " · localnet diagnostic " + String(row.chain_status) : ""
                                    var prefix = mode + " · " + state + chain + " · "
                                    if (hint.length)
                                        return prefix + hint
                                    if (row.error)
                                        return prefix + String(row.error)
                                    var tx = String(row.txid || "")
                                    if (tx.length > 20)
                                        return prefix + tx.substring(0, 8) + "…" + tx.substring(tx.length - 6)
                                    return prefix + tx
                                }
                                color: row.error ? "#c98989" : "#c8cdd4"
                                font.family: "monospace"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }
        }
    }
}
