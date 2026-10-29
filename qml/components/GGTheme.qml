pragma Singleton
import QtQuick
import "GGPalette.js" as BasePalette

// Runtime semantic roles share one object in each engine. Immutable neutral
// surfaces and token swatches keep their canonical terminal provenance.
QtObject {
    id: root
    property var roleOverrides: ({})
    property color legacyAccent: BasePalette.accent
    readonly property var roleKeys: ["accent","info","positive","warning","negative","blue","cyan","purple","orange","pink"]
    readonly property var roleLabels: ["Markering / fokus","Information","Lyckat / klart","Väntar / varning","Fel / stopp","Länkar / blå","Nätverk / cyan","AI / agenter","Resurser / orange","Övrigt / rosa"]
    readonly property var palette: BasePalette.palette
    readonly property color base: BasePalette.base
    readonly property color canvas: BasePalette.canvas
    readonly property color panel: BasePalette.panel
    readonly property color raised: BasePalette.raised
    readonly property color hover: BasePalette.hover
    readonly property color selected: BasePalette.selected
    readonly property color line: BasePalette.line
    readonly property color edge: BasePalette.edge
    readonly property color bright: BasePalette.bright
    readonly property color text: BasePalette.text
    readonly property color muted: BasePalette.muted
    readonly property color dim: BasePalette.dim
    readonly property color accent: roleColor("accent")
    readonly property color info: roleColor("info")
    readonly property color positive: roleColor("positive")
    readonly property color warning: roleColor("warning")
    readonly property color negative: roleColor("negative")
    readonly property color blue: roleColor("blue")
    readonly property color cyan: roleColor("cyan")
    readonly property color purple: roleColor("purple")
    readonly property color orange: roleColor("orange")
    readonly property color pink: roleColor("pink")
    function defaultRole(key) { return key==="accent" ? String(legacyAccent) : String(BasePalette[key] || BasePalette.text) }
    function roleColor(key) {
        var configured=roleOverrides[key]
        return typeof configured==="string" && validColor(configured) ? configured : defaultRole(key)
    }
    function normalizeOverrides(raw) {
        var clean={}
        if(!raw || typeof raw!=="object" || Array.isArray(raw))return clean
        for(var i=0;i<roleKeys.length;i++) {
            var key=roleKeys[i],value=raw[key]
            if(typeof value==="string" && validColor(value))clean[key]=value.toLowerCase()
        }
        return clean
    }
    function setOverrides(raw) {roleOverrides=normalizeOverrides(raw)}
    function swatches(count) {return BasePalette.swatches(count)}
    function colors(count) {return BasePalette.colors(count)}
    function color(index) {return BasePalette.color(index)}
    function validColor(value) {return BasePalette.validColor(value)}
    function defaultColor(assetId) {return BasePalette.defaultColor(assetId)}
    function defaultTokenColor(assetId) {return BasePalette.defaultTokenColor(assetId)}
}
