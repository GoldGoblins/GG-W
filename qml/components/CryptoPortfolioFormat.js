.pragma library

function money(value, unit, isPrice) {
    if (value === null || value === undefined || !isFinite(Number(value)))
        return "—"
    var n = Number(value)
    if (unit !== "SEK" && n > 0 && !isPrice && n < 0.005)
        return "<$0.01"
    if (unit !== "SEK" && n > 0 && isPrice && n < 0.0000000001)
        return "$" + n.toExponential(2)
    var places = isPrice && n > 0 && n < 1 ? Math.min(10, Math.max(4, 2 - Math.floor(Math.log(n) / Math.LN10))) : 2
    var text = n.toLocaleString(Qt.locale("en_US"), "f", unit === "SEK" ? 0 : places)
    return unit === "SEK" ? text + " kr" : "$" + text
}

function percent(value) {
    if (value === null || value === undefined || !isFinite(Number(value)))
        return "—"
    return (Number(value) >= 0 ? "+" : "") + Number(value).toFixed(2) + "%"
}

function quantity(value) {
    var parts = String(value || "0").split(".")
    var whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
    var fraction = (parts[1] || "").replace(/0+$/, "")
    // Keep small balances readable without rounding them to a displayed zero.
    var places = parts[0] === "0" ? Math.max(6, fraction.search(/[1-9]/) + 3) : 6
    return whole + (fraction.length ? "." + fraction.slice(0, places) : "")
}
