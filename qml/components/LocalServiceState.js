.pragma library

// Reuse unchanged JSON branches so a service refresh cannot replace a pressed
// Repeater control. Changed values always come from the authoritative snapshot.
function retain(previous, incoming) {
    var remaining = 32768
    function visit(before, after, depth) {
        if (before === after) return before
        if (--remaining < 0 || depth > 64) return after
        if (before === null || after === null || typeof before !== "object" || typeof after !== "object")
            return after
        var array = Array.isArray(after)
        if (Array.isArray(before) !== array) return after
        if (array) {
            var rows = [], equal = before.length === after.length
            for (var i = 0; i < after.length; ++i) {
                rows[i] = visit(before[i], after[i], depth + 1)
                if (rows[i] !== before[i]) equal = false
            }
            return equal ? before : rows
        }
        var keys = Object.keys(after), beforeKeys = Object.keys(before)
        var value = ({}), same = keys.length === beforeKeys.length
        for (var key of keys) {
            var present = Object.prototype.hasOwnProperty.call(before, key)
            value[key] = visit(present ? before[key] : undefined, after[key], depth + 1)
            if (!present || value[key] !== before[key]) same = false
        }
        return same ? before : value
    }
    return visit(previous, incoming, 0)
}
