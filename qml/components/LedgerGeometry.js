.pragma library

// Retained border geometry; recomputed only when bounds/openings change.
function segments(start, end, gaps) {
    start = Number(start)
    end = Number(end)
    if (!isFinite(start) || !isFinite(end) || end <= start) return []
    var openings = []
    var source = Array.isArray(gaps) ? gaps : []
    for (var i = 0; i < source.length; ++i) {
        if (!source[i]) continue
        var a = Number(source[i].start)
        var b = Number(source[i].end)
        if (!isFinite(a) || !isFinite(b) || b <= a) continue
        a = Math.max(start, a)
        b = Math.min(end, b)
        if (b > a) openings.push({start: a, end: b})
    }
    openings.sort(function(a, b) { return a.start - b.start })
    var result = []
    var cursor = start
    for (var j = 0; j < openings.length; ++j) {
        if (openings[j].start > cursor)
            result.push({start: cursor, end: openings[j].start})
        cursor = Math.max(cursor, openings[j].end)
    }
    if (cursor < end) result.push({start: cursor, end: end})
    return result
}
