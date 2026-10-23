.pragma library

// One palette for the sky, distance fog, water and lights. The clock belongs
// to the simulation; camera rotation never chooses a different atmosphere.
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }
function smooth(a, b, v) {
    var t=clamp((v-a)/(b-a),0,1); return t*t*(3-2*t)
}
function color(hex) {
    return [parseInt(hex.substr(1,2),16)/255,parseInt(hex.substr(3,2),16)/255,
            parseInt(hex.substr(5,2),16)/255]
}
function mix(a,b,t) {
    return a.map(function(v,i) { return v+(b[i]-v)*t })
}
function hex(c) {
    return "#"+c.map(function(v) {
        var s=Math.round(clamp(v,0,1)*255).toString(16);return s.length<2 ? "0"+s : s
    }).join("")
}

var CLIMATES={
    COAST:{horizon:"#a4ccd7",sky:"#418ecf",key:"#ffe3b1",fill:"#a0c4ed",near:.48,fx:"POLLEN"},
    TEMPERATE:{horizon:"#adc9bd",sky:"#5a9acb",key:"#ffe1a6",fill:"#9bbbd4",near:.40,fx:"LEAF"},
    JUNGLE:{horizon:"#94bdb0",sky:"#599fc3",key:"#ffe7ac",fill:"#94bfc8",near:.32,fx:"LEAF"},
    TUNDRA:{horizon:"#b8c9e2",sky:"#7196c6",key:"#fff1d6",fill:"#9aaee6",near:.38,fx:"SNOW"},
    VOLCANIC:{horizon:"#ba9aa0",sky:"#806f94",key:"#ffbb87",fill:"#ad9ec7",near:.30,fx:"EMBER"},
    MAELSTROM:{horizon:"#879dab",sky:"#4d6895",key:"#cddbe8",fill:"#96b8d4",near:.28,fx:"MIST"}
}

function palette(biome, time, dayLength) {
    var climate=CLIMATES[biome] || CLIMATES.COAST
    // Same phase boundaries as game_engine_life.world_clock(), with smooth
    // dawn/day/dusk/night envelopes instead of switching four static lights.
    var cycle=((Math.max(0,time)/Math.max(1,dayLength))%1+1)%1
    var daylight=smooth(.04,.20,cycle)*(1-smooth(.66,.86,cycle))
    var dawn=(1-smooth(.10,.22,cycle))*smooth(0,.04,cycle)
    var dusk=smooth(.60,.70,cycle)*(1-smooth(.78,.88,cycle))
    var twilight=Math.max(dawn,dusk)
    var night=1-daylight
    var horizon=mix(color("#344664"),color(climate.horizon),daylight)
    horizon=mix(horizon,color(dusk>dawn ? "#daa4a4" : "#dec6b2"),twilight*.56)
    var sky=mix(color("#182842"),color(climate.sky),daylight)
    sky=mix(sky,color("#7a71a9"),twilight*.35)
    return {
        horizon:hex(horizon), sky:hex(sky),
        cloud:hex(mix(color("#516888"),color("#e6edf1"),daylight)),
        ground:hex(mix(color("#172b40"),color("#527565"),daylight)),
        key:hex(mix(color("#a6bdf2"),color(climate.key),daylight)),
        fill:hex(mix(color("#7b94cf"),color(climate.fill),daylight)),
        keyEnergy:.28+daylight*.78, fillEnergy:.22+daylight*.14,
        probeEnergy:.28+daylight*.48,
        night:night, twilight:twilight, fogNear:climate.near-twilight*.08,
        lampEnergy:.75+night*2.35, fx:climate.fx,
        waterTint:hex(mix(color("#405d88"),color("#b5e2e7"),daylight)),
        glowStrength:.62+night*.20, glowIntensity:.42+night*.12
    }
}

function farClip(policyDistance, horizonDistance, planetRadius) {
    // Bounded at altitude: flying cannot silently upload half the planet.
    return Math.max(240,Math.min(policyDistance,planetRadius*.999,
        Math.max(240,horizonDistance*1.16)))
}

function fogRange(farClip, bakedTerrain, renderRadius, cellSize, cameraBoom, nearFraction) {
    // Native edited/streamed patches have less coverage than the baked world.
    // One cell of travel + the complete orbit boom stays inside the guard band.
    var coverage=coveredDistance(farClip,bakedTerrain,renderRadius,cellSize,cameraBoom)
    var end=Math.min(farClip*.92,coverage*.92)
    return {near:Math.max(3,end*nearFraction),far:end,density:1,curve:1.15}
}

function coveredDistance(farClip,bakedTerrain,renderRadius,cellSize,cameraBoom) {
    return bakedTerrain ? farClip : Math.min(farClip,
        Math.max(12,renderRadius*cellSize-cameraBoom-cellSize))
}
