.pragma library

// Numeric label validation only. These helpers never read or update graph state.
function finiteValue(raw) {
    return typeof raw === "number" && isFinite(raw) ? raw : null
}

function probeKey(key) {
    if (key === "cpu_busy" || key === "cores")
        return "cpu"
    if (key.indexOf("mem_") === 0)
        return "memory"
    if (key === "mhz" || key === "mhz_max")
        return "frequency"
    if (key === "disk_read_bps" || key === "disk_write_bps"
            || key === "net_rx_bps" || key === "net_tx_bps")
        return "io"
    return ""
}

function metadataAvailable(payload, key) {
    if (!payload || typeof payload !== "object" || payload.pending || payload.error)
        return false
    var unavailable = payload.unavailable
    if (Array.isArray(unavailable) && unavailable.indexOf(key) >= 0)
        return false
    var probe = probeKey(key)
    if (probe) {
        if (payload.sample_errors && payload.sample_errors[probe])
            return false
        if (payload.sampled_at && payload.sampled_at[probe] === null)
            return false
    }
    if (probe === "cpu") {
        if (payload.cpu_pending)
            return false
        var age = finiteValue(payload.cpu_sample_age_ms)
        if (age !== null && age > 1000)
            return false
    }
    return true
}

function rawValue(payload, key) {
    if (key === "energy_w" && payload.energy_w === undefined)
        return payload.energy && payload.energy.watts
    return payload[key]
}

function validNumber(raw, key) {
    var number = finiteValue(raw)
    if (number === null)
        return null
    if ((key === "cpu_busy" || key === "gpu_busy" || key === "cores")
            && (number < 0 || number > 100))
        return null
    if ((probeKey(key) === "memory" || probeKey(key) === "frequency"
            || probeKey(key) === "io" || key === "energy_w") && number < 0)
        return null
    return number
}

function available(payload, key) {
    if (!metadataAvailable(payload, key))
        return false
    if (key === "cores")
        return Array.isArray(payload.cores) && payload.cores.length > 0
    return validNumber(rawValue(payload, key), key) !== null
}

function value(payload, key) {
    if (!available(payload, key) || key === "cores")
        return null
    return validNumber(rawValue(payload, key), key)
}

function text(payload, key, digits, suffix) {
    var number = value(payload, key)
    if (number === null)
        return "--"
    return number.toFixed(digits === undefined ? 0 : digits)
        + (suffix === undefined ? "" : suffix)
}

function coreText(payload, index, digits) {
    if (!available(payload, "cores")
            || !metadataAvailable(payload, "cpu_busy")
            || finiteValue(index) === null || index < 0 || Math.floor(index) !== index
            || index >= payload.cores.length)
        return "--"
    var row = payload.cores[index]
    var number = validNumber(row && typeof row === "object" ? row.pct : row, "cores")
    if (number === null)
        return "--"
    return number.toFixed(digits === undefined ? 1 : digits) + "%"
}
