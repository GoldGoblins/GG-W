.pragma library

// BEGIN AUTHORED ENCHANT CATALOG
var ENCHANT_CHOICES = [
  {
    "id": "enchant.chromatic.violet",
    "name": "Void Whisper",
    "style": "VIOLET",
    "colors": [
      "#9956ef",
      "#b87aff"
    ],
    "description": "Purple: target deals 18% less damage for 4s.",
    "tier": 1,
    "families": [
      "DEFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.magenta",
    "name": "Blood Orchid",
    "style": "MAGENTA",
    "colors": [
      "#ed36cc",
      "#ff6fe2"
    ],
    "description": "Magenta: steal 16% of damage dealt as health.",
    "tier": 1,
    "families": [
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.pink",
    "name": "Roseheart",
    "style": "PINK",
    "colors": [
      "#ff85bb",
      "#ffc2d8"
    ],
    "description": "Pink: restore 3 health on a successful hit.",
    "tier": 1,
    "families": [
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.red",
    "name": "Crimson Ember",
    "style": "RED",
    "colors": [
      "#f43c4b",
      "#ff666b"
    ],
    "description": "Red: burn for 2 damage each second for 4s.",
    "tier": 1,
    "families": [
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.yellow",
    "name": "Thunder Gold",
    "style": "YELLOW",
    "colors": [
      "#f4dd36",
      "#fff081"
    ],
    "description": "Yellow: +4 lightning damage on hit.",
    "tier": 1,
    "families": [
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.white",
    "name": "Moonward",
    "style": "WHITE",
    "colors": [
      "#ddeaf5",
      "#fffefa"
    ],
    "description": "White: gain a 5-damage shield for 4s (refreshes).",
    "tier": 1,
    "families": [
      "DEFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.green",
    "name": "Viper Moss",
    "style": "GREEN",
    "colors": [
      "#32b86a",
      "#6bd992"
    ],
    "description": "Green: poison for 1.5 damage each second for 6s.",
    "tier": 1,
    "families": [
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.lime",
    "name": "Caustic Thorn",
    "style": "LIME",
    "colors": [
      "#9be32c",
      "#c9f766"
    ],
    "description": "Lime: +4 acid damage on hit.",
    "tier": 1,
    "families": [
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.turquoise",
    "name": "Tidepulse",
    "style": "TURQUOISE",
    "colors": [
      "#35cfc3",
      "#79ece2"
    ],
    "description": "Turquoise: regenerate 1.5 health each second for 4s.",
    "tier": 1,
    "families": [
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.blue",
    "name": "Glacier Edge",
    "style": "BLUE",
    "colors": [
      "#428aef",
      "#79b7ff"
    ],
    "description": "Blue: enemy movement slowed by 30% for 4s.",
    "tier": 1,
    "families": [
      "DEFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.orange",
    "name": "Forgeflame",
    "style": "ORANGE",
    "colors": [
      "#f38624",
      "#ffc36a"
    ],
    "description": "Orange: +4 fire damage on hit.",
    "tier": 1,
    "families": [
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.indigo",
    "name": "Duskbind",
    "style": "INDIGO",
    "colors": [
      "#565bdf",
      "#8b91fa"
    ],
    "description": "Indigo: root enemy movement for 1.2s; attacks remain possible.",
    "tier": 1,
    "families": [
      "DEFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.magenta_red",
    "name": "Bloodfire",
    "style": "MAGENTA_RED",
    "colors": [
      "#ed36cc",
      "#f43c4b"
    ],
    "description": "Magenta / red: 10% lifesteal and 1 burn damage per second for 4s.",
    "tier": 2,
    "families": [
      "OFFENSIVE",
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.yellow_orange",
    "name": "Solar Tempest",
    "style": "YELLOW_ORANGE",
    "colors": [
      "#f4dd36",
      "#f38624"
    ],
    "description": "Yellow / orange: 1 fire damage per second for 3s; gain a golden 3-damage shield for 3s.",
    "tier": 2,
    "families": [
      "DEFENSIVE",
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.blue_turquoise",
    "name": "Frozen Tide",
    "style": "BLUE_TURQUOISE",
    "colors": [
      "#428aef",
      "#35cfc3"
    ],
    "description": "Blue / turquoise: enemy movement -20%; regenerate 1 health per second for 4s.",
    "tier": 2,
    "families": [
      "DEFENSIVE",
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.green_yellow",
    "name": "Stormvenom",
    "style": "GREEN_YELLOW",
    "colors": [
      "#32b86a",
      "#f4dd36"
    ],
    "description": "Green / yellow: 1 poison damage per second for 4s; enemy attack interval +15% for 3s.",
    "tier": 2,
    "families": [
      "DEFENSIVE",
      "OFFENSIVE"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.pink_violet",
    "name": "Dreamrose",
    "style": "PINK_VIOLET",
    "colors": [
      "#ff85bb",
      "#9956ef"
    ],
    "description": "Pink / purple: restore 2 health; enemy damage -10% for 3s.",
    "tier": 2,
    "families": [
      "DEFENSIVE",
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.turquoise_lime",
    "name": "Reef Venom",
    "style": "TURQUOISE_LIME",
    "colors": [
      "#35cfc3",
      "#9be32c"
    ],
    "description": "Turquoise / lime: +2 acid damage; regenerate 1 health per second for 3s.",
    "tier": 2,
    "families": [
      "OFFENSIVE",
      "RECOVERY"
    ],
    "required_level": 1
  },
  {
    "id": "enchant.chromatic.triad_flame",
    "name": "Phoenix Covenant",
    "style": "TRIAD_FLAME",
    "colors": [
      "#f43c4b",
      "#ddeaf5",
      "#ff85bb"
    ],
    "description": "Artifact / level 60: burn 3 / 4s; ward 6 / 4s; heal 3",
    "tier": 3,
    "families": [
      "OFFENSIVE",
      "DEFENSIVE",
      "RECOVERY"
    ],
    "required_level": 60
  },
  {
    "id": "enchant.chromatic.triad_frost",
    "name": "Glacial Trinity",
    "style": "TRIAD_FROST",
    "colors": [
      "#9956ef",
      "#428aef",
      "#35cfc3"
    ],
    "description": "Artifact / level 60: arcane 5; slow 0.35 / 4s; regen 2 / 4s",
    "tier": 3,
    "families": [
      "OFFENSIVE",
      "DEFENSIVE",
      "RECOVERY"
    ],
    "required_level": 60
  },
  {
    "id": "enchant.chromatic.triad_venom",
    "name": "Ancient Thorn",
    "style": "TRIAD_VENOM",
    "colors": [
      "#32b86a",
      "#565bdf",
      "#ed36cc"
    ],
    "description": "Artifact / level 60: poison 3 / 4s; snare 1 / 1.2s; lifesteal 0.2",
    "tier": 3,
    "families": [
      "OFFENSIVE",
      "DEFENSIVE",
      "RECOVERY"
    ],
    "required_level": 60
  }
]
var GEAR_ENCHANT_CHOICES = [
  {
    "id": "enchant.gear.vitality",
    "name": "Vitality Stitch",
    "stat": "health",
    "value": 12,
    "allowed_categories": [
      "ARMOR",
      "TRINKET",
      "UTILITY",
      "SHIELD"
    ],
    "tags": [
      "ENCHANT",
      "STAT_BOOST"
    ],
    "visual_fx": "",
    "required_level": 1,
    "tier": 1,
    "description": "Vitality Stitch: +12 health"
  },
  {
    "id": "enchant.gear.armor",
    "name": "Stoneweave",
    "stat": "armor",
    "value": 4,
    "allowed_categories": [
      "ARMOR",
      "TRINKET",
      "UTILITY",
      "SHIELD"
    ],
    "tags": [
      "ENCHANT",
      "STAT_BOOST"
    ],
    "visual_fx": "",
    "required_level": 1,
    "tier": 1,
    "description": "Stoneweave: +4 armor"
  },
  {
    "id": "enchant.gear.stamina",
    "name": "Enduring Thread",
    "stat": "stamina",
    "value": 5,
    "allowed_categories": [
      "ARMOR",
      "TRINKET",
      "UTILITY",
      "SHIELD"
    ],
    "tags": [
      "ENCHANT",
      "STAT_BOOST"
    ],
    "visual_fx": "",
    "required_level": 1,
    "tier": 1,
    "description": "Enduring Thread: +5 stamina"
  },
  {
    "id": "enchant.gear.precision",
    "name": "Keen Stitch",
    "stat": "crit",
    "value": 2,
    "allowed_categories": [
      "ARMOR",
      "TRINKET",
      "UTILITY",
      "SHIELD"
    ],
    "tags": [
      "ENCHANT",
      "STAT_BOOST"
    ],
    "visual_fx": "",
    "required_level": 1,
    "tier": 1,
    "description": "Keen Stitch: +2 crit"
  },
  {
    "id": "enchant.gear.celerity",
    "name": "Swiftweave",
    "stat": "attack_speed",
    "value": 2,
    "allowed_categories": [
      "ARMOR",
      "TRINKET",
      "UTILITY",
      "SHIELD"
    ],
    "tags": [
      "ENCHANT",
      "STAT_BOOST"
    ],
    "visual_fx": "",
    "required_level": 1,
    "tier": 1,
    "description": "Swiftweave: +2 attack speed"
  },
  {
    "id": "enchant.gear.spellpower",
    "name": "Spellweave",
    "stat": "spell_power",
    "value": 6,
    "allowed_categories": [
      "ARMOR",
      "TRINKET",
      "UTILITY",
      "SHIELD"
    ],
    "tags": [
      "ENCHANT",
      "STAT_BOOST"
    ],
    "visual_fx": "",
    "required_level": 1,
    "tier": 1,
    "description": "Spellweave: +6 spell power"
  }
]
// END AUTHORED ENCHANT CATALOG

// Render-only effects. Positions follow the authoritative player and water
// snapshot; every style has a fixed number of cards in the shared FX mesh.
var PREVIEW_STYLES = ["FIRE", "SMOKE", "GAS", "LIGHTNING", "ARCANE", "SHADOW", "LASER"]

function singleChoices() {
    return ENCHANT_CHOICES.filter(function(row) { return row.tier === 1 })
}

function recipeForChoices(primaryIndex, secondIndex, thirdIndex, gearIndex, mode) {
    if (mode === 1)
        return GEAR_ENCHANT_CHOICES[gearIndex] || GEAR_ENCHANT_CHOICES[0]
    var primary = ENCHANT_CHOICES[primaryIndex] || ENCHANT_CHOICES[0]
    if (primary.tier !== 1 || (secondIndex === 0 && thirdIndex === 0))
        return primary
    var singles = singleChoices(), selected = [primary]
    if (secondIndex > 0) selected.push(singles[secondIndex-1])
    if (thirdIndex > 0) selected.push(singles[thirdIndex-1])
    var families = [], parts = []
    for (var i=0; i<selected.length; ++i) {
        if (parts.indexOf(selected[i].style.toLowerCase()) >= 0)
            return {id:"", description:"Choose different effects for a mixed scroll."}
        parts.push(selected[i].style.toLowerCase())
        selected[i].families.forEach(function(family) {
            if (families.indexOf(family) < 0) families.push(family)
        })
    }
    if (selected.length === 3 && families.length !== 3)
        return {id:"", description:"Artifact: choose one offensive, one defensive and one recovery effect."}
    return {id:"enchant.custom."+parts.sort().join("+"), tier:selected.length,
        required_level:selected.length===3 ? 60 : 1,
        name:selected.map(function(row) { return row.name }).join(" + "),
        description:selected.map(function(row) { return row.description }).join(" ")}
}

function scrollError(error) {
    var messages={ENCHANT_SCROLL_REQUIRED:"Craft or select an owned enchanting scroll first.",
        ENCHANT_TABLE_REQUIRED:"Use the enchanting table.",
        ENCHANT_TABLE_OUT_OF_REACH:"Move within reach of the enchanting table.",
        ENCHANT_LEVEL_REQUIRED:"This artifact enchant requires character level 60.",
        ENCHANT_RECIPE_INVALID:"Choose a valid scroll recipe.",
        GEAR_MATERIALS_MISSING:"Not enough fiber, runic oil or moon shards.",
        GEAR_ENCHANTMENT_SLOT_INVALID:"This scroll does not match the selected equipment.",
        GEAR_ENCHANTMENT_SLOTS_FULL:"This item already has two enchants.",
        GEAR_ENCHANTMENT_DUPLICATE:"This item already has that enchant."}
    return messages[error] || error
}

function isAdditive(row) {
    return ["ENCHANT", "FLAME", "SPARK", "ARCANE", "LIGHTNING", "LASER", "AURA", "XP", "LAMP", "LIGHT_BEACON"].indexOf(String(row.kind || "").toUpperCase()) >= 0
}

var LIGHT_PROFILES={
    ENCHANT:[2.5,2.8],FLAME:[8,2.4],SPARK:[2,.3],ARCANE:[7,2.4],
    LIGHTNING:[10,2.3],LASER:[8,1.8],AURA:[5,1.6],XP:[3,.7],LAMP:[8,2.2]
}

function pointLightQuadraticFade(radius) {
    // Qt scales quadraticFade by .0001. Convert metre-based attenuation:
    // at the authored radius only 1/26 of the source energy remains.
    return 250000/Math.max(.01,radius*radius)
}

function lightSources(rows,lamps,camera,night) {
    var groups={}
    for (var i=0;i<rows.length;++i) {
        var row=rows[i],kind=String(row.kind || "").toUpperCase()
        var profile=LIGHT_PROFILES[kind]
        if (!profile || finite(row.opacity,1)<=.02) continue
        var id=row.light_emitter || row.source_id ||
            "fx:"+Math.floor(row.x/1.5)+":"+Math.floor(row.y/1.5)+":"+Math.floor(row.z/1.5)
        var group=groups[id]
        if (!group) group=groups[id]={id:id,x:0,y:0,z:0,r:0,g:0,b:0,weight:0,
            light_radius_m:0,light_energy:0,kind:kind,
            attachment_slot:row.attachment_slot,attachment_index:row.attachment_index}
        var weight=finite(row.opacity,1)
        var color=String(row.color || "#ffc777")
        group.x+=row.x*weight;group.y+=row.y*weight;group.z+=row.z*weight
        group.r+=parseInt(color.substr(1,2),16)/255*weight
        group.g+=parseInt(color.substr(3,2),16)/255*weight
        group.b+=parseInt(color.substr(5,2),16)/255*weight
        group.weight+=weight
        var radius=finite(row.light_radius_m,profile[0]),energy=finite(row.light_energy,profile[1])
        if (kind==="ENCHANT") radius=Math.min(2.5,radius)
        group.light_radius_m=Math.max(group.light_radius_m,radius)
        group.light_energy=Math.max(group.light_energy,energy*weight)
    }
    var result=[]
    for (var key in groups) {
        var light=groups[key],w=light.weight
        light.x/=w;light.y/=w;light.z/=w
        light.color="#"+[light.r/w,light.g/w,light.b/w].map(function(c) {
            var hex=Math.round(Math.max(0,Math.min(1,c))*255).toString(16)
            return hex.length<2 ? "0"+hex : hex
        }).join("")
        result.push(light)
    }
    for (var j=0;j<lamps.length;++j) {
        var lamp=lamps[j]
        var existing=result.filter(function(row){return row.id===lamp.id})[0]
        if (existing) {
            existing.light_energy=(.75+night*2.35)*lamp.fade
            existing.light_radius_m=8;continue
        }
        result.push({id:lamp.id,kind:"LAMP",x:lamp.x,y:lamp.y,z:lamp.z,color:"#ffbf6c",
            light_radius_m:8,light_energy:(.75+night*2.35)*lamp.fade})
    }
    for (var n=0;n<result.length;++n) {
        var item=result[n]
        item.distance_m=Math.hypot(item.x-camera.x,item.y-camera.y,item.z-camera.z)
    }
    return result.sort(function(a,b) { return a.distance_m-b.distance_m || String(a.id).localeCompare(String(b.id)) })
}

function nearbyLights(sources,budget) {
    // One source for an entire enchant cloud, rather than fourteen lights.
    return sources.filter(function(row) { return row.distance_m<48 && row.light_energy>.04 })
        .slice(0,Math.max(0,budget)).sort(function(a,b){return String(a.id).localeCompare(String(b.id))})
}

function emitLightBeacons(result,sources,lamps,camera,range,night,budget) {
    var all=sources.filter(function(row){return row.kind!=="LAMP"}).concat(lamps)
    all=all.filter(function(row) {
        var d=Math.hypot(row.x-camera.x,row.y-camera.y,row.z-camera.z)
        row.beacon_distance=d;return d>40 && d<range
    }).sort(function(a,b){return a.beacon_distance-b.beacon_distance})
    // Keep the same distant reserve when active spells share the lamp budget.
    var far=all.filter(function(row){return row.beacon_distance>range/1.18})
        .slice(0,Math.floor(budget/4))
    var selected=all.filter(function(row){return far.indexOf(row)<0})
        .slice(0,Math.max(0,budget-far.length)).concat(far)
    for (var i=0;i<selected.length;++i) {
        var source=selected[i],distance=source.beacon_distance
        var envelope=source.kind==="LAMP" ? .35+.65*night : 1
        var power=Math.min(1,source.light_energy || 1)*envelope
        var size=Math.min(3.0,.08+distance*.0009)
        var entry=Math.max(0,Math.min(1,(distance-40)/24))
        entry=entry*entry*(3-2*entry)
        result.push({kind:"LIGHT_BEACON",x:source.x,y:source.y,z:source.z,
            color:source.color,size:size,opacity:.78*power*entry,through_fog:true})
    }
}

function emitMagicCores(result,sockets,time) {
    var count=0
    for (var slot in sockets) {
        var magic=sockets[slot].magic
        if (!magic || !magic.point || !magic.colors || !magic.colors.length || count>=3) continue
        ++count
        var p=magic.point,r=finite(magic.radius,.1),theme=String(magic.theme),colors=magic.colors
        var lightStart=result.length
        // Additive billboards supplement the painted emissive mesh. Effects
        // remain attached to the actual model core when the character turns.
        add(result,"AURA",p.x,p.y,p.z,colors[0],r*1.55,.34+.10*Math.sin(time*2.1))
        for (var j=0;j<4 && result.length<96;++j) {
            var phase=time*(theme==="nature" ? .72 : 1.45)+j*2.39996
            var color=colors[j%colors.length],dx=Math.cos(phase)*r*.76,dz=Math.sin(phase)*r*.76
            var py=p.y+Math.sin(phase*1.7)*r*.65
            if (theme==="fire")
                add(result,"FLAME",p.x+dx*.35,p.y+r*((time*1.7+j*.23)%1),p.z+dz*.35,color,r*.44,.54)
            else if (theme==="storm")
                add(result,"LIGHTNING",p.x,p.y,p.z,color,r*.065,.56,p.x+dx,py,p.z+dz)
            else
                add(result,theme==="nature" ? "SPARK" : "ARCANE",p.x+dx,py,p.z+dz,color,r*.28,.54)
        }
        for (var k=lightStart;k<result.length;++k) result[k].light_emitter="core:"+slot
    }
}

var GUNSHOT_MUZZLES = ({})
function gunEnchantBurst(result,shot,point,age,phase,strength) {
    var colors=shot.enchant_colors || [],enchants=shot.enchants || [],lightning=false,fire=false
    for (var e=0;e<enchants.length;++e) {
        var kinds=enchants[e].kinds || []
        if (kinds.indexOf("shock")>=0 || enchants[e].style==="LIGHTNING") lightning=true
        if (kinds.indexOf("burn")>=0 || kinds.indexOf("fire")>=0) fire=true
    }
    for (var c=0;c<colors.length && c<6 && result.length<224;++c) {
        var a=phase+c*2.39996,radius=.045+Math.max(0,age)*.7
        var x=point.x+Math.cos(a)*radius,y=point.y+Math.sin(a)*radius,z=point.z+Math.sin(a*1.7)*radius
        add(result,fire ? "FLAME" : "SPARK",x,y,z,colors[c],.08*strength,.85*strength)
        if (lightning && result.length<224)
            add(result,"LIGHTNING",point.x,point.y,point.z,colors[c],.014,.8*strength,x,y,z)
    }
}
function emitGunfire(result,shots,time,sockets) {
    // Fixed event identities and lifetimes; never a loop of persistent lights.
    var active=({})
    for (var i=shots.length-1;i>=Math.max(0,shots.length-24) && result.length<224;--i) {
        var shot=shots[i],age=time-shot.time_s
        if (age<0 || age>shot.flight_s+.28) continue
        var start=shot.start, target=shot.target
        var socket=sockets && sockets[shot.slot]
        var key=shot.id+":"+shot.time_s
        active[key]=true
        if (!GUNSHOT_MUZZLES[key]) {
            var points=socket && socket.muzzles && socket.muzzles.length ? socket.muzzles : [socket && socket.tip || {x:start[0],y:start[1],z:start[2]}]
            if (shot.kind==="WAND" && socket && socket.magic) points=[socket.magic.point]
            GUNSHOT_MUZZLES[key]=points.map(function(p){return {x:p.x,y:p.y,z:p.z}})
        }
        var origins=GUNSHOT_MUZZLES[key]
        var multiple=["duckfoot","frost","hive"].indexOf(shot.construction)>=0
        var barrel=shot.kind==="WAND" ? 0 : (Number(String(shot.id).split(":").pop())-1)%origins.length
        var muzzle=origins[barrel]
        if (shot.kind==="WAND") start=[muzzle.x,muzzle.y,muzzle.z]
        var colors=shot.enchant_colors || []
        if (age<.085) {
            for (var m=0;m<(multiple ? origins.length : 1);++m) {
                var flash=multiple ? origins[m] : muzzle
                if (!shot.silent) {
                    add(result,"SPARK",flash.x,flash.y,flash.z,colors.length ? colors[m%colors.length] : shot.color,.18*(1-age/.09),.9)
                    add(result,"SPARK",flash.x,flash.y,flash.z,"#fff2cc",.065,.95)
                }
                gunEnchantBurst(result,shot,flash,age,barrel+m,(1-age/.10)*(shot.silent ? .35 : 1))
            }
        }
        var progress=Math.max(0,Math.min(1,age/shot.flight_s))
        var previous=Math.max(0,progress-.08)
        var dx=target[0]-start[0],dz=target[2]-start[2],length=Math.hypot(dx,dz) || 1
        for (var p=0;p<shot.offsets.length && p<10 && result.length<224;++p) {
            var origin=multiple ? origins[p%origins.length] : muzzle
            start=[origin.x,origin.y,origin.z]
            var offset=shot.offsets[p],ex=target[0]+dz/length*offset[0],ey=target[1]+offset[1],ez=target[2]-dx/length*offset[0]
            var x=start[0]+(ex-start[0])*progress,y=start[1]+(ey-start[1])*progress,z=start[2]+(ez-start[2])*progress
            var color=colors.length ? colors[p%colors.length] : shot.color
            if (progress<1) {
                var tx=start[0]+(ex-start[0])*previous,ty=start[1]+(ey-start[1])*previous,tz=start[2]+(ez-start[2])*previous
                add(result,"LASER",tx,ty,tz,color,shot.shape==="rocket" ? .07 : colors.length ? .023 : .014,.8,x,y,z)
                for (var c=0;c<Math.min(3,colors.length) && result.length<224;++c) {
                    var angle=age*45+c*2.094+p,r=.025
                    add(result,"SPARK",x+Math.cos(angle)*r,y+Math.sin(angle)*r,z,colors[(p*3+c)%colors.length],.065,.8)
                }
                if (["rocket","ember"].indexOf(shot.shape)>=0) {
                    add(result,"FLAME",x,y,z,color,.10,.9)
                    add(result,"SMOKE",tx,ty,tz,"#81776d",.13,.35)
                } else if (["soul","cell","crystal"].indexOf(shot.shape)>=0)
                    add(result,"ARCANE",x,y,z,color,.07,.75)
            } else if (shot.impact) {
                var fade=1-(age-shot.flight_s)/.28
                add(result,"SPARK",ex,ey,ez,color,shot.impact_size*(1.4-fade),fade*.8)
                gunEnchantBurst(result,shot,{x:ex,y:ey,z:ez},age-shot.flight_s,p,fade)
                if (shot.shape==="rocket")
                    add(result,"FLAME",ex,ey+.10,ez,"#ffbc58",.6*fade,fade)
            }
        }
    }
    for (var old in GUNSHOT_MUZZLES) if (!active[old]) delete GUNSHOT_MUZZLES[old]
}

function emitLamps(result, anchors, time, night) {
    var envelope=.6+.4*finite(night,0)
    for (var i=0; i<anchors.length; ++i) {
        var lamp=anchors[i], phase=0
        var lightStart=result.length
        for (var c=0; c<lamp.id.length; ++c) phase+=lamp.id.charCodeAt(c)
        var flicker=.9+.1*Math.sin(time*5.1+phase)
        add(result,"LAMP",lamp.x,lamp.y,lamp.z,"#ffbe59",.48,lamp.fade*.28*flicker*envelope)
        add(result,"FLAME",lamp.x,lamp.y,lamp.z,"#ffe5ad",.15,lamp.fade*.9*flicker)
        for (var spark=0; spark<2; ++spark) {
            var rise=(time*.65+spark*.5+phase*.031)%1
            add(result,"SPARK",lamp.x+.09*Math.sin(time+spark+phase),
                lamp.y+.2+rise*.65,lamp.z,"#ffcb6b",.04,lamp.fade*.55*(1-rise))
        }
        for (var index=lightStart;index<result.length;++index)
            result[index].light_emitter=lamp.id
    }
}

function emitEnvironment(result, anchors, time, atmosphere) {
    // Each tiny swarm drifts around a persistent world anchor. Camera yaw is
    // absent: visibility may change with distance, but the scene stays put.
    for (var i=0;i<anchors.length;++i) {
        var anchor=anchors[i],night=finite(atmosphere.night,0)
        if (anchor.kind==="WATERFALL") {
            for (var spray=0;spray<10;++spray) {
                var rise=(time*.38+spray*.271+anchor.phase)%1
                var angle=spray*2.39996+anchor.phase
                var spread=Math.min(6,anchor.width_m*.16)*(.25+rise)
                add(result,"MIST",anchor.x+Math.cos(angle)*spread,
                    anchor.y+rise*3.5,anchor.z+Math.sin(angle)*spread,
                    "#d6edf2",.45+rise*.75,anchor.fade*(1-rise)*.22)
            }
            continue
        }
        var style=String(anchor.biome)==="VOLCANIC" ? "EMBER"
            : String(anchor.biome)==="TUNDRA" ? "SNOW" : atmosphere.fx
        for (var j=0;j<3;++j) {
            var phase=anchor.phase+j*2.39996
            var drift=time*.24+phase
            var x=anchor.x+Math.sin(drift)*3.0
            var z=anchor.z+Math.cos(drift*.73)*2.4
            var y=anchor.y+.7+(Math.sin(drift*1.3)+1)*1.8
            var fade=anchor.fade
            if (style==="EMBER") {
                y=anchor.y+((time*.3+phase)%1)*4
                add(result,"SPARK",x,y,z,j%2 ? "#ffba63" : "#ff6849",.065,fade*.6)
            } else if (style==="SNOW") {
                y=anchor.y+4-((time*.12+phase)%1)*3.6
                add(result,"SNOW",x,y,z,"#e2edff",.075,fade*.34)
            } else {
                // Daytime pollen/leaves, warm lime fireflies at dusk/night.
                add(result,style==="LEAF" ? "LEAF" : "POLLEN",x,y,z,
                    style==="LEAF" ? "#afc675" : "#f6e8b7",.065,fade*.25*(1-night))
                if (night>.25) {
                    var pulse=.4+.6*smoothPulse(time*1.2+phase)
                    add(result,"SPARK",x,y,z,j%2 ? "#a9ef80" : "#ffe69a",.085,
                        fade*night*pulse*.7)
                    add(result,"AURA",x,y,z,"#bbe27d",.24,fade*night*pulse*.10)
                    for (var tiny=result.length-2;tiny<result.length;++tiny) {
                        result[tiny].light_radius_m=.4;result[tiny].light_energy=.08
                    }
                }
            }
        }
    }
}

function smoothPulse(phase) { return .5+.5*Math.sin(phase) }

function finite(value, fallback) {
    var number = Number(value)
    return isFinite(number) ? number : fallback
}

function add(rows, kind, x, y, z, color, size, opacity, ex, ey, ez) {
    var row = {
        kind: kind, x: x, y: y, z: z,
        color: color, size: size, opacity: opacity
    }
    var light=LIGHT_PROFILES[kind]
    if (light) { row.light_radius_m=light[0];row.light_energy=light[1] }
    if (ex !== undefined) {
        row.ex = ex
        row.ey = ey
        row.ez = ez
    }
    rows.push(row)
}

function styleForEnchant(enchant) {
    var authored = String(enchant && enchant.visual_fx || "").toUpperCase()
    if (authored === "CUSTOM" || ENCHANT_CHOICES.some(function(row) { return row.style === authored })
        || authored === "WATER" || PREVIEW_STYLES.indexOf(authored) >= 0)
        return authored
    var id = String(enchant && enchant.id || "").toLowerCase()
    if (id.indexOf("aquatic") >= 0 || id.indexOf("tide") >= 0)
        return "WATER"
    if (id.indexOf("night") >= 0 || id.indexOf("shadow") >= 0)
        return "SHADOW"
    if (id.indexOf("steady") >= 0 || id.indexOf("storm") >= 0)
        return "LIGHTNING"
    if (id.indexOf("fire") >= 0 || id.indexOf("ember") >= 0)
        return "FIRE"
    if (id.indexOf("venom") >= 0 || id.indexOf("fieldcraft") >= 0)
        return "GAS"
    if (id.indexOf("hardened") >= 0)
        return "SMOKE"
    return "ARCANE"
}

function enchantForStyle(style) {
    var ids = {
        FIRE: "enchant.ember_edge",
        SMOKE: "enchant.smoke_edge",
        GAS: "enchant.venom_edge",
        LIGHTNING: "enchant.storm_edge",
        ARCANE: "enchant.arcane_edge",
        SHADOW: "enchant.shadow_edge",
        LASER: "enchant.sun_lance"
    }
    return ids[String(style || "")] || ""
}

function emitStyle(rows, style, x, y, z, yaw, time, strength) {
    var phase = time * 2.3
    var opacity = Math.max(0, Math.min(1, strength))
    var index, angle, radius, px, pz, rise
    if (style === "FIRE") {
        for (index = 0; index < 8; ++index) {
            angle = index * 2.39996 + phase
            radius = 0.16 + (index % 3) * 0.10
            px = x + Math.cos(angle) * radius
            pz = z + Math.sin(angle) * radius
            rise = ((time * 1.7 + index * 0.37) % 1)
            add(rows, "FLAME", px, y + rise * 0.9, pz,
                index % 3 ? "#ff9e39" : "#ffe37a", 0.17 + 0.08 * rise,
                opacity * (1 - 0.6 * rise))
        }
        for (index = 0; index < 4; ++index) {
            angle = index * 1.57 + phase * 0.3
            rise = (time * 0.38 + index * 0.26) % 1
            add(rows, "SMOKE", x + Math.cos(angle) * 0.28,
                y + 0.9 + rise * 1.4, z + Math.sin(angle) * 0.28,
                "#8a8380", 0.28 + rise * 0.38, opacity * (0.34 - rise * 0.24))
        }
    } else if (style === "SMOKE" || style === "GAS" || style === "SHADOW") {
        var color = style === "GAS" ? "#81d8a2"
            : (style === "SHADOW" ? "#513b77" : "#a7aaa9")
        for (index = 0; index < 10; ++index) {
            rise = (time * (style === "GAS" ? 0.45 : 0.32) + index * 0.23) % 1
            angle = index * 2.39996 + phase * 0.18
            radius = 0.18 + rise * (style === "SHADOW" ? 0.65 : 0.50)
            add(rows, style, x + Math.cos(angle) * radius,
                y + rise * (style === "SHADOW" ? 1.1 : 1.8),
                z + Math.sin(angle) * radius, color,
                0.30 + rise * 0.36, opacity * (0.48 - rise * 0.36))
        }
    } else if (style === "LIGHTNING") {
        for (index = 0; index < 5; ++index) {
            angle = index * 2.51327 + phase * 0.7
            radius = 0.36 + (index % 2) * 0.26
            add(rows, "LIGHTNING", x, y + 0.35, z, "#bfeaff",
                0.055, opacity * 0.85,
                x + Math.cos(angle) * radius,
                y + 0.55 + Math.sin(phase * 4 + index) * 0.28,
                z + Math.sin(angle) * radius)
            add(rows, "SPARK", x + Math.cos(angle) * radius,
                y + 0.55 + Math.sin(phase * 4 + index) * 0.28,
                z + Math.sin(angle) * radius,
                "#e7fbff", 0.10, opacity * 0.8)
        }
    } else if (style === "LASER") {
        var dx = Math.sin(yaw), dz = Math.cos(yaw)
        var beamLength = strength < 0.8 ? 0.85 : 3.4
        add(rows, "LASER", x, y + 0.45, z, "#ff6176", 0.10, opacity,
            x + dx * beamLength, y + 0.45, z + dz * beamLength)
        add(rows, "LASER", x, y + 0.45, z, "#ffe3c0", 0.037, opacity,
            x + dx * beamLength, y + 0.45, z + dz * beamLength)
        for (index = 0; index < 5; ++index) {
            angle = index * 2.39996 + phase
            add(rows, "SPARK", x + dx * beamLength + Math.cos(angle) * 0.25,
                y + 0.45 + Math.sin(angle) * 0.25,
                z + dz * beamLength, "#ffbf93", 0.10, opacity * 0.7)
        }
    } else {
        var watery = style === "WATER"
        for (index = 0; index < 10; ++index) {
            angle = index * 0.628319 + phase * (watery ? 0.38 : 0.82)
            radius = watery ? 0.65 : 0.42 + (index % 3) * 0.13
            add(rows, watery ? "FOAM" : "ARCANE",
                x + Math.cos(angle) * radius,
                y + (watery ? 0.05 : 0.35 + Math.sin(angle * 2 + phase) * 0.24),
                z + Math.sin(angle) * radius,
                watery ? "#c8f4ed" : (index % 2 ? "#a07bfb" : "#79e4ed"),
                watery ? 0.18 : 0.13, opacity * (watery ? 0.40 : 0.72))
        }
    }
}

function emitWeaponClouds(result, style, frame, time, phaseOffset, authoredColors) {
    var lightStart=result.length
    var choice = ENCHANT_CHOICES.filter(function(row) { return row.style === style })[0]
    var colors = authoredColors && authoredColors.length ? authoredColors
        : choice ? choice.colors : {
        FIRE:["#ff751f","#f7a648"], SMOKE:["#b8c2df","#e1e4f2"],
        GAS:["#67d855","#9aeb75"], SHADOW:["#9155dc","#ba7fed"],
        LIGHTNING:["#669fe7","#bad5f3"], ARCANE:["#ad69e5","#8e99e3"],
        WATER:["#79cee7","#b4e8f0"], LASER:["#efd260","#f4e2a7"]
    }[style] || ["#ad69e5","#8e99e3"]
    var base=frame.base, tip=frame.tip
    var dx=tip.x-base.x, dy=tip.y-base.y, dz=tip.z-base.z
    var length=Math.hypot(dx,dy,dz)
    var path=Array.isArray(frame.path) && frame.path.length>1 ? frame.path.slice(0,64) : [base,tip]
    var distances=[0]
    for (var point=1;point<path.length;++point)
        distances.push(distances[point-1]+Math.hypot(path[point].x-path[point-1].x,path[point].y-path[point-1].y,path[point].z-path[point-1].z))
    length=distances[distances.length-1]
    if (length<.01) return
    var ax=dx/length, ay=dy/length, az=dz/length
    var side=Math.hypot(ax,az)
    var rx=side>.001 ? az/side : 1, ry=0, rz=side>.001 ? -ax/side : 0
    var ux=ay*rz, uy=az*rx-ax*rz, uz=-ay*rx
    // Twice the cloud width, with slightly stronger opacity for readable color.
    // The fourteen overlapping puffs still follow the same blade axis. No rising fire/smoke
    // column or world-space emitter at the hand.
    for (var puff=0;puff<14;++puff) {
        var t=(puff+.5)/14
        var target=t*length, segment=1
        while (segment<path.length-1 && distances[segment]<target) ++segment
        var segmentLength=distances[segment]-distances[segment-1]
        var f=segmentLength>.0001 ? (target-distances[segment-1])/segmentLength : 0
        var a=path[segment-1],b=path[segment]
        var cx=a.x+(b.x-a.x)*f,cy=a.y+(b.y-a.y)*f,cz=a.z+(b.z-a.z)*f
        var phase=time*.75+phaseOffset+puff*2.39996
        var breathe=.5+.5*Math.sin(time*1.8+puff*1.73+phaseOffset)
        var radius=2*Math.min(.09,.015+length*.025)*( .5+.5*breathe )
        var edge=Math.sin(t*Math.PI)
        add(result,"ENCHANT",cx+(rx*Math.cos(phase)+ux*Math.sin(phase))*radius,
            cy+(ry*Math.cos(phase)+uy*Math.sin(phase))*radius,
            cz+(rz*Math.cos(phase)+uz*Math.sin(phase))*radius,
            colors[puff%colors.length],2*Math.min(.18,.05+length*.065)*(.78+.22*breathe),
            1.25*(.22+.16*breathe)*(.45+.55*edge))
    }
    for (var index=lightStart;index<result.length;++index)
        result[index].light_emitter="enchant:"+phaseOffset
}

function rows(player, equipment, previewStyle, worldScale, fauna, sockets) {
    var result = []
    var x = finite(player.x, 0), y = finite(player.y, 0), z = finite(player.z, 0)
    var yaw = finite(player.yaw, 0), time = finite(player.time_s, 0)
    var water = player.mobility && player.mobility.water_surface || ({})
    var waterY = finite(water.height_m, 0)
    var medium = String(player.medium || "")
    if (medium === "WATER" || String(player.vehicle || "") === "BOAT") {
        for (var foamIndex = 0; foamIndex < 12; ++foamIndex) {
            var angle = foamIndex * 0.523599 + time * 0.22
            var radius = 0.78 + 0.12 * Math.sin(time * 1.8 + foamIndex)
            add(result, "FOAM", x + Math.cos(angle) * radius, waterY + 0.05,
                z + Math.sin(angle) * radius, "#d5f9ef", 0.14,
                0.38 + 0.16 * Math.sin(time * 2.2 + foamIndex))
        }
    }

    var schools = fauna && Array.isArray(fauna.fish) ? fauna.fish : []
    for (var schoolIndex = 0; schoolIndex < schools.length && schoolIndex < 3; ++schoolIndex) {
        var school = schools[schoolIndex] || ({})
        var sx = finite(school.x, 100000), sz = finite(school.z, 100000)
        if (Math.hypot(sx - x, sz - z) > 80)
            continue
        for (var wake = 0; wake < 5; ++wake) {
            var wakeAngle = wake * 1.256637 + time * 0.40 + schoolIndex
            add(result, "FOAM", sx + Math.cos(wakeAngle) * 1.3,
                finite(school.y, 0) + 0.20,
                sz + Math.sin(wakeAngle) * 1.3,
                "#bdeee7", 0.13, 0.28)
        }
    }

    emitMagicCores(result,sockets || {},time)
    var equipped = Array.isArray(equipment) ? equipment : []
    var effects = 0
    for (var itemIndex = 0; itemIndex < equipped.length && effects < 2; ++itemIndex) {
        var item = equipped[itemIndex] || ({})
        // Firearm enchants are event bursts at the muzzle and on projectiles.
        if (item.firearm || item.definition_id === "item.weapon_pistol") continue
        var gear = item.gear || ({})
        var enchants = Array.isArray(gear.enchantments) ? gear.enchantments : []
        if (["MAIN_HAND", "OFF_HAND", "RANGED"].indexOf(String(item.equipped_slot || gear.slot || "")) < 0)
            continue
        if (!enchants.length && Array.isArray(item.enchantments))
            enchants = item.enchantments
        for (var enchantIndex = 0; enchantIndex < enchants.length && effects < 2; ++enchantIndex) {
            var style = styleForEnchant(enchants[enchantIndex])
            var right = effects ? -0.55 : 0.55
            var slot=String(item.equipped_slot || item.equip_slot || "MAIN_HAND")
            var anchor=sockets && sockets[slot]
            var attachedStart=result.length
            if (anchor && anchor.base && anchor.tip) {
                emitWeaponClouds(result,style,anchor,time,effects*.41,enchants[enchantIndex].colors)
            } else {
                // Explicit fallback blade axis until the equipment delegate is ready.
                var bx=x+Math.cos(yaw)*right+Math.sin(yaw)*.25
                var bz=z-Math.sin(yaw)*right+Math.cos(yaw)*.25
                emitWeaponClouds(result,style,{base:{x:bx,y:y+.8,z:bz},
                    tip:{x:bx,y:y+1.5,z:bz}},time,effects*.41,enchants[enchantIndex].colors)
            }
            for (var attached=attachedStart;attached<result.length;++attached) {
                result[attached].attachment_slot=slot
                result[attached].attachment_index=effects
            }
            ++effects
        }
    }

    var abilityAge = time - finite(player.last_ability_time, -10)
    if (abilityAge >= 0 && abilityAge < 0.75) {
        var ability = String(player.last_ability || "")
        var abilityStyle = ability.indexOf("undertow") >= 0 ? "WATER"
            : (ability.indexOf("leap") >= 0 ? "LIGHTNING" : "ARCANE")
        emitStyle(result, abilityStyle, x, y + 0.65, z, yaw, time,
            1 - abilityAge / 0.75)
        for (var aura=0; aura<12; ++aura) {
            var aa=aura*Math.PI/6+time*.6
            add(result,"AURA",x+Math.cos(aa)*.9,y+.12,z+Math.sin(aa)*.9,
                "#73dfff",.19,.35*(1-abilityAge/.75))
        }
    }

    var xp=player.xp_visual || ({}), xpAge=time-finite(xp.time_s,-10)
    if (xpAge>=0 && xpAge<1.15) {
        var t=xpAge/1.15, travel=t*t*(3-2*t)
        for (var orb=0; orb<8; ++orb) {
            var a=orb*Math.PI/4, spread=Math.sin(Math.PI*t)*.65
            add(result,"XP",finite(xp.x,x)*(1-travel)+x*travel+Math.cos(a)*spread,
                finite(xp.y,y)*(1-travel)+(y+1.1)*travel+Math.sin(Math.PI*t)*(.7+orb*.06),
                finite(xp.z,z)*(1-travel)+z*travel+Math.sin(a)*spread,
                orb%2 ? "#64ffd5" : "#ffe8a4",.10,.8*(1-t*t))
        }
    }

    if (PREVIEW_STYLES.indexOf(previewStyle) >= 0) {
        var scale = Math.max(0.5, finite(worldScale, 1.85))
        emitStyle(result, previewStyle, x + 1.45 * scale,
            y + 0.25, z + 1.2 * scale, yaw, time, 1)
    }
    return result.slice(0, 80)
}
