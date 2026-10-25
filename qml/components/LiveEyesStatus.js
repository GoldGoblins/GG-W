.pragma library

function number(value) {
    return typeof value === "number" && isFinite(value) && value >= 0 ? value : null
}

function state(value) {
    return value && typeof value.state === "string" ? value.state : "off"
}

function title(value) {
    var current = state(value)
    if (current === "capturing") return value.observation_kind === "video" ? "ÖGON · VIDEO" : "ÖGON · FÅNGAR"
    if (current === "observed") return "ÖGON · NYSS"
    if (current === "stopping") return "ÖGON · STOPPAR"
    if (current === "error") return "ÖGON · FEL"
    if (current === "live") return "ÖGON · " + (number(value.received_fps) || 0) + " fps"
    return "ÖGON · VÄNTAR"
}

function fresh(value) {
    var current = state(value)
    var age = number(value && value.frame_age_ms)
    return (current === "live" || current === "capturing") && age !== null && age <= 2000
}

function details(value) {
    var current = state(value)
    var result = title(value)
    if (current === "capturing") {
        var frames = number(value.frame_count) || 0
        var fps = number(value.received_fps) || 0
        return result + "\n" + (value.reason || "Hämtar skärmbilder på begäran")
            + (frames > 0 ? "\n" + frames + " bilder" + (fps > 0 ? " · " + fps + " fps" : "") : "")
    }
    if (current === "observed") {
        var age = number(value.last_delivered_age_ms)
        return result + "\n" + (number(value.last_observation_frames) || 0) + " bilder hämtade"
            + (age === null ? "" : " · " + Math.round(age / 1000) + " s sedan")
            + "\nIngen kontinuerlig fångst"
    }
    if (current === "live") {
        var delivered = number(value.last_delivered_age_ms)
        return result + "\n" + (delivered === null ? "Ingen bild hämtad av AI ännu"
            : "Bild hämtad " + Math.round(delivered / 1000) + " s sedan")
            + "\nRAM " + ((number(value.buffer_bytes) || 0) / 1048576).toFixed(1) + " MiB"
    }
    return result + "\n" + ((value && value.reason) || "Väntar på skärmdelning")
}

function tooltip(value) {
    return details(value) + (state(value) === "observed"
        ? "\nKlicka för att rensa indikatorn." : "\nKlicka för att stoppa observationen.")
}
