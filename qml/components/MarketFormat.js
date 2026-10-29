function money(value) {
    if(value===null || value===undefined || !isFinite(Number(value))) return "—"
    var n=Number(value)
    if(n===0)return "$0"
    return "$"+(Math.abs(n)<0.0001 ? n.toPrecision(4) : n.toLocaleString(Qt.locale("en_US"),"f",Math.abs(n)<1 ? 6 : 2))
}
function compact(value) {
    if(value===null || value===undefined || !isFinite(Number(value)))return "—"
    var n=Number(value),abs=Math.abs(n)
    if(abs>=1e12)return "$"+(n/1e12).toFixed(2)+"T"
    if(abs>=1e9)return "$"+(n/1e9).toFixed(2)+"B"
    if(abs>=1e6)return "$"+(n/1e6).toFixed(2)+"M"
    if(abs>=1e3)return "$"+(n/1e3).toFixed(1)+"K"
    return money(n)
}
function percent(value) { return value===null || value===undefined || !isFinite(Number(value)) ? "—" : (value>0?"+":"")+Number(value).toFixed(2)+" %" }
function shortAddress(value) {value=String(value || "");return value.length>22 ? value.slice(0,10)+"…"+value.slice(-8) : value}

// Wallet decimal strings are exact; never round them through a binary float.
function exactQuantity(value) {
    if(typeof value!=="string" || value.length>420 || !/^\d+(?:\.\d+)?$/.test(value))return "—"
    var parts=value.split(".")
    return parts[0].replace(/\B(?=(\d{3})+(?!\d))/g," ")+(parts.length>1 ? "."+parts[1] : "")
}
function exactMoney(value) {
    var formatted=exactQuantity(value)
    if(formatted==="—")return formatted
    var parts=formatted.split(".")
    return "$"+parts[0]+"."+(parts.length>1 ? parts[1]+(parts[1].length===1 ? "0" : "") : "00")
}
function compareExact(a,b) {
    if(exactQuantity(a)==="—" || exactQuantity(b)==="—")return 0
    var left=a.split("."),right=b.split("."),wholeA=left[0].replace(/^0+/,"") || "0",wholeB=right[0].replace(/^0+/,"") || "0"
    if(wholeA.length!==wholeB.length)return wholeA.length>wholeB.length ? 1 : -1
    if(wholeA!==wholeB)return wholeA>wholeB ? 1 : -1
    var decimals=Math.max((left[1] || "").length,(right[1] || "").length)
    var fractionA=(left[1] || "").padEnd(decimals,"0"),fractionB=(right[1] || "").padEnd(decimals,"0")
    return fractionA===fractionB ? 0 : fractionA>fractionB ? 1 : -1
}
