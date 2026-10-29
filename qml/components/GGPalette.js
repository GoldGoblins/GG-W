.pragma library

// GG Terminal: curated colors from the same xterm256 table used by MiniVt.
// Codex can select syntax themes; these are GG roles, not a universal Codex theme.
// Canonical data: config/gg-palette.json; tested for exact agreement.
var palette = ["#87afd7", "#87afaf", "#af87d7", "#d78787", "#d7af87", "#87af87", "#d7d787", "#d787af", "#afd7ff", "#87d7af", "#afafd7", "#d7afd7", "#afafaf", "#afd7d7", "#d7afaf", "#bcbcbc", "#5f87d7", "#5fafaf", "#8787d7", "#d75f5f", "#d7875f", "#87af5f", "#d7d75f", "#d75f87", "#87d7ff", "#87ffaf", "#af87ff", "#d7afff", "#949494", "#d0d0d0", "#ffaf5f", "#ffd7af", "#ff0000", "#ff5f5f", "#d70000", "#ff5f00", "#ff8700", "#ffd700", "#ffff00", "#87ff00", "#00ff00", "#00ff87", "#00ffff", "#00afff", "#005fff", "#5f00ff", "#af00ff", "#ff00ff", "#870000", "#875f00", "#008700", "#008787", "#005f87", "#000087", "#5f0087", "#87005f", "#000000", "#ffffff", "#121212", "#262626", "#444444", "#808080", "#dadada", "#eeeeee"]

// Retain explicit old wallet/preferences values without adding extra displayed swatches.
var legacyPalette = ["#005faf", "#0087af", "#5f5faf", "#875f5f", "#af5f00", "#5f875f", "#878700", "#875f87", "#5fafd7", "#5fd7d7", "#87afff", "#af87af", "#af875f", "#afaf5f", "#afaf87", "#afd7af", "#5f87af", "#5faf87", "#8787af", "#af5f5f", "#af8700", "#87875f", "#af8787", "#afafff", "#afffff", "#afffd7", "#d7ffff", "#d7ffd7", "#d7d7ff", "#ffd7ff", "#e4e4e4", "#4e4e4e"]

var base = "#111111"
var canvas = "#101010"
var panel = "#161616"
var raised = "#202020"
var hover = "#272727"
var selected = "#303030"
var line = "#383838"
var edge = "#6a6a6a"
var bright = "#eeeeee"
var text = "#d8dee9"
var muted = "#a8a8a8"
var dim = "#858585"
var blue = "#87afd7"
var cyan = "#87afaf"
var purple = "#af87d7"
var negative = "#d78787"
var orange = "#d7af87"
var positive = "#87af87"
var warning = "#d7d787"
var pink = "#d787af"
var accent = "#87afd7"
var info = "#87afd7"

function swatches(count) {
    var size = Number(count)
    return palette.slice(0, size === 32 || size === 64 ? size : 16)
}
function colors(count) { return swatches(count) }
function color(index) {
    var value = Number(index)
    return Number.isInteger(value) && value >= 0 && value < palette.length ? palette[value] : accent
}
function validColor(value) {
    return typeof value === "string" && (palette.indexOf(value.toLowerCase()) >= 0 || legacyPalette.indexOf(value.toLowerCase()) >= 0)
}
function defaultColor(assetId) {
    var identity = String(assetId)
    var hash = 2166136261
    for (var i = 0; i < identity.length; ++i)
        hash = Math.imul(hash ^ identity.charCodeAt(i), 16777619) >>> 0
    return palette[hash % 12]
}
function defaultTokenColor(assetId) { return defaultColor(assetId) }
