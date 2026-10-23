//! Live equipment, reach and statuses through original inspection/aura getters.
use engine_ui_core::script::{UiScript,InspectView,UnitReach,UnitGuids,InventorySlots,InvSlotView,AuraState,SpellTooltipView};
use serde_json::{Value,json};
use std::collections::HashMap;
fn n(v:&Value,key:&str)->u32{v[key].as_f64().unwrap_or(0.).clamp(0.,u32::MAX as f64) as u32}
fn s(v:&Value,key:&str)->String{v[key].as_str().unwrap_or("").into()}

pub(super) fn feed(ui:&mut UiScript,v:&Value,target:&Value)->Result<UnitGuids,String>{
    if !v.is_object(){return Ok(UnitGuids::default());}
    let mut reach=HashMap::new();reach.insert(1,UnitReach{dist_sq:0.,inspectable:true});
    let mut guids=UnitGuids{player:1,..Default::default()};
    let mut identities=HashMap::from([("player".to_owned(),1u64)]);
    if let Some(people)=v["people"].as_array(){for p in people{
        let guid=n(p,"guid") as u64;identities.insert(s(p,"id"),guid);
        let d=p["distance_sq"].as_f64().unwrap_or(f64::MAX);if p["online"]==true&&guid>0&&d.is_finite()&&d>=0.{
            reach.insert(guid,UnitReach{dist_sq:d,inspectable:p["inspectable"]==true});guids.held.insert(guid,n(p,"target_guid") as u64);
            let state=engine_ui_core::script::UnitState{exists:true,has_object:true,guid,name:Some(s(p,"name")),
                health:n(p,"health"),max_health:n(p,"max_health").max(1),level:n(p,"level").max(1),dead:n(p,"health")==0,
                can_attack:p["inspectable"]!=true,reaction:if p["inspectable"]==true{5}else{2},..Default::default()};
            ui.set_unit_by_guid(guid,Some(state));
        }
    }}
    guids.target=target["id"].as_str().and_then(|id|identities.get(id)).copied().unwrap_or(0);
    guids.held.insert(1,guids.target);guids.npc=n(v,"interaction_guid") as u64;
    if v["trade"]["shared_trade"]==true && v["trade"]["open"]==true{
        guids.npc=v["trade"]["target_profile"]["guid"].as_u64().unwrap_or(0);
    }
    let group=&v["group"];let subgroup=n(&group["subgroups"],"player").max(1);let mut party=0;
    if let Some(roster)=group["roster"].as_array(){for p in roster{
        let guid=n(p,"guid") as u64;
        if group["raid"]==true{guids.raid.push(guid);guids.raid_pets.push(0);}
        if p["id"]!="player"&&(group["raid"]!=true||n(&group["subgroups"],&s(p,"id")).max(1)==subgroup)&&party<4{guids.party[party]=guid;party+=1;}
    }}
    let pet=&v["pet"];if pet.is_object(){guids.pet=0xfffffff0;guids.held.insert(guids.pet,pet["target"].as_str().and_then(|id|identities.get(id)).copied().unwrap_or(0));}
    guids.mouseover=ui.hovered_nameplate().filter(|guid|guids.held.contains_key(guid)).unwrap_or(0);
    ui.set_unit_guids(&guids);
    ui.set_unit_reach(reach);
    let inspect=&v["inspection"];
    if inspect["open"]==true{
        let mut slots:InventorySlots=Default::default();
        let items=inspect["items"].as_array().filter(|r|r.len()<=19).ok_or("inspect item capacity")?;
        for item in items{
            let slot=n(item,"slot") as usize;if !(1..=19).contains(&slot){return Err("inspect slot range".into());}
            slots[slot]=Some(InvSlotView{item_id:n(item,"item_id"),name:Some(s(item,"name")),icon:item["icon"].as_str().map(str::to_owned),
                count:n(item,"quantity"),quality:n(item,"quality") as i32,link:Some(s(item,"link")),durability:serde_json::from_value(item["durability"].clone()).ok(),enchants:crate::item_info::enchants(item),already_bound:item["already_bound"]==true,flags:n(item,"flags"),..Default::default()});
        }
        ui.set_inspect(Some(InspectView{unit:s(inspect,"unit"),guid:n(inspect,"guid") as u64,slots}));
    }else{ui.set_inspect(None);}
    let clock:f64=ui.eval("return GetTime()").map_err(|e|e.to_string())?;
    if !clock.is_finite(){return Err("invalid aura clock".into());}
    if let Some(rows)=v["auras"].as_array(){
        if rows.len()>128{return Err("aura unit capacity".into());}
        for row in rows{
            let mut auras=Vec::new();
            for aura in row["auras"].as_array().filter(|r|r.len()<=16).ok_or("aura capacity")?{
                let remaining=aura["remaining"].as_f64().unwrap_or(0.);if !remaining.is_finite()||remaining<0.||remaining>600.{return Err("invalid aura duration".into());}
                let spell_id=n(aura,"id");let name=s(aura,"name");let description=s(aura,"description");
                ui.set_spell_tooltip(spell_id,SpellTooltipView{name:name.clone(),description:description.clone(),aura_description:description,..Default::default()});
                auras.push(AuraState{spell_id,name:Some(name),icon:Some(s(aura,"icon")),count:1,debuff_type:aura["debuff_type"].as_str().map(str::to_owned),
                    duration:aura["duration"].as_f64().unwrap_or(remaining),expiration_time:clock+remaining,helpful:aura["helpful"]==true,cancelable:aura["cancelable"]==true,until_cancelled:false,channeled:false});
            }
            let guid=n(row,"guid") as u64;if guid==1{ui.set_player_auras(auras);}else{ui.set_unit_auras(guid,Some(auras));}
        }
    }
    Ok(guids)
}

pub(super) fn requests(ui:&mut UiScript)->Vec<Value>{
    let mut rows=Vec::new();
    for unit in ui.take_inspect_notifies(){rows.push(json!({"op":"Inspect","unit":unit}));}
    if ui.take_inspect_clear(){rows.push(json!({"op":"InspectClear"}));}
    for id in ui.take_cancel_aura_requests(){rows.push(json!({"op":"AuraCancel","id":id}));}
    for id in ui.take_spell_tooltip_asks(){rows.push(json!({"op":"SpellTooltipRequest","id":id,"pet":false}));}
    for id in ui.take_pet_spell_tooltip_asks(){rows.push(json!({"op":"SpellTooltipRequest","id":id,"pet":true}));}
    rows
}

pub(super) fn spell_tooltips(ui:&mut UiScript,spells:&Value,pet:&Value,templates:&Value)->Result<(),String>{
    if let Some(rows)=spells.as_array(){
        if rows.len()>128{return Err("spell tooltip capacity".into());}
        for row in rows{
            let cost=row["resource_cost"].as_f64().unwrap_or(0.);let range=row["range_m"].as_f64().unwrap_or(0.);
            let cast=row["cast_time_s"].as_f64().unwrap_or(0.);let channel=row["channel_time_s"].as_f64().unwrap_or(0.);let cooldown=row["cooldown_duration_s"].as_f64().unwrap_or(0.);
            if [cost,range,cast,channel,cooldown].iter().any(|n|!n.is_finite()||*n<0.||*n>1e6){return Err("invalid spell tooltip values".into());}
            ui.set_spell_tooltip(n(row,"spell_id"),SpellTooltipView{name:s(row,"name"),description:s(row,"description"),
                cost:if cost>0.{Some(format!("{} Energy",cost))}else{None},range:Some(if range>0.{format!("{} m",range)}else{"Self".into()}),
                cast_time:Some(if channel>0.{"Channeled".into()}else if cast>0.{format!("{} sec cast",cast)}else{"Instant".into()}),cooldown:if cooldown>0.{Some(format!("{} sec cooldown",cooldown))}else{None},
                item_met:true,form_met:true,..Default::default()});
        }
    }
    if let Some(rows)=templates.as_array().filter(|r|!r.is_empty()).or_else(||pet["learned"].as_array()){
        if rows.len()>128{return Err("pet tooltip capacity".into());}
        for row in rows{
            let spell=n(row,"id");let description=match spell{0x800101=>"Basic melee attack.",0x800102=>"Melee attack with 20% additional damage.",0x800103=>"Passive: adds 3 armor.",_=>return Err("pet tooltip recipe unavailable".into())};
            ui.set_pet_spell_tooltip(spell,SpellTooltipView{name:s(row,"name"),description:row["description"].as_str().unwrap_or(description).into(),cast_time:if spell==0x800103{None}else{Some("Instant".into())},item_met:true,form_met:true,..Default::default()});
        }
    }
    Ok(())
}
