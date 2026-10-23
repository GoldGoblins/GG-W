//! Catalog-backed tooltip fields and exact instance enchant names.
use engine_ui_core::script::{UiScript,ItemTemplateView,ItemSetView,PlayerReqState,EnchantView};
use serde_json::{Value,json};
fn n(v:&Value,k:&str)->u32{v[k].as_f64().unwrap_or(0.).clamp(0.,u32::MAX as f64) as u32}
fn s(v:&Value,k:&str)->String{v[k].as_str().unwrap_or("").into()}
pub(super) fn defaults(ui:&mut UiScript)->Result<(),String>{
    let globals=ui.lua().globals();
    for (key,value) in [
        ("ARMOR_TEMPLATE","%d Armor"),("SHIELD_BLOCK_TEMPLATE","%d Block"),("DURABILITY_TEMPLATE","Durability %d / %d"),
        ("ITEM_MOD_HEALTH","%c%d Health"),("ITEM_MOD_AGILITY","%c%d Agility"),("ITEM_MOD_STRENGTH","%c%d Strength"),
        ("ITEM_MOD_INTELLECT","%c%d Intellect"),("ITEM_MOD_SPIRIT","%c%d Spirit"),("ITEM_MOD_STAMINA","%c%d Stamina"),
        ("ITEM_MIN_LEVEL","Requires Level %d"),("ITEM_UNSELLABLE","Cannot be sold"),("CURRENTLY_EQUIPPED","Currently equipped"),
        ("ITEM_SOULBOUND","Soulbound"),("ITEM_BIND_ON_PICKUP","Binds when picked up"),("ITEM_BIND_ON_EQUIP","Binds when equipped"),
        ("ITEM_BIND_ON_USE","Binds when used"),("ITEM_BIND_QUEST","Quest item"),
        ("ITEM_SET_NAME","%s (%d/%d)"),("ITEM_SET_BONUS","Set: %s"),("ITEM_SET_BONUS_GRAY","(%d) Set: %s"),
        ("ITEM_MIN_SKILL","Requires %s (%d)"),("ITEM_REQ_SKILL","Requires %s"),
        ("INVTYPE_HEAD","Head"),("INVTYPE_NECK","Neck"),("INVTYPE_SHOULDER","Shoulders"),("INVTYPE_BODY","Shirt"),
        ("INVTYPE_CHEST","Chest"),("INVTYPE_WAIST","Waist"),("INVTYPE_LEGS","Legs"),("INVTYPE_FEET","Feet"),
        ("INVTYPE_WRIST","Wrist"),("INVTYPE_HAND","Hands"),("INVTYPE_FINGER","Finger"),("INVTYPE_TRINKET","Trinket"),
        ("INVTYPE_WEAPON","One hand"),("INVTYPE_2HWEAPON","Two hand"),("INVTYPE_WEAPONMAINHAND","Main hand"),
        ("INVTYPE_WEAPONOFFHAND","Off hand"),("INVTYPE_HOLDABLE","Off hand"),("INVTYPE_SHIELD","Shield"),
        ("INVTYPE_RANGED","Ranged"),("INVTYPE_CLOAK","Back"),("INVTYPE_TABARD","Tabard")
    ]{if globals.get::<mlua::Value>(key).map_err(|e|e.to_string())?.is_nil(){globals.set(key,value).map_err(|e|e.to_string())?;}}
    Ok(())
}
pub(super) fn feed(ui:&mut UiScript,rows:&Value,level:u32,requirements:&Value)->Result<(),String>{
    if !rows.is_array(){return Ok(());}
    let rows=rows.as_array().filter(|r|r.len()<=512).ok_or("item catalog capacity")?;
    for row in rows{
        let damage=row["damage"].as_f64().unwrap_or(0.);if !damage.is_finite()||!(0. ..=1e6).contains(&damage){return Err("invalid item damage".into());}
        let stats:Vec<(u32,i32)>=serde_json::from_value(row["stats"].clone()).map_err(|e|e.to_string())?;
        if stats.len()>16{return Err("item stat capacity".into());}
        ui.set_item_template(n(row,"item_id"),ItemTemplateView{name:s(row,"name"),quality:n(row,"quality"),class:n(row,"class_id"),
            subclass:n(row,"subclass"),inventory_type:n(row,"inventory_type"),item_type:Some(s(row,"item_type")),
            item_sub_type:Some(s(row,"subname")),sub_class_display:Some(s(row,"subname")),stackable:n(row,"stackable"),
            stats,damages:if damage>0.{vec![(damage as f32,damage as f32,0)]}else{Vec::new()},armor:n(row,"armor"),
            max_durability:n(row,"max_durability"),required_level:n(row,"required_level"),bonding:n(row,"bonding"),item_set:n(row,"item_set"),description:s(row,"description"),
            allowable_class:-1,allowable_race:-1,
            icon:row["icon"].as_str().map(str::to_owned),..Default::default()});
    }
    // Older hand-authored catalog snapshots have no requirement block.
    let skills:Vec<(u32,u32)>=if requirements.is_null(){Vec::new()}else{
        serde_json::from_value(requirements["skills"].clone()).map_err(|e|e.to_string())?};
    if skills.len()>40||skills.iter().any(|(id,rank)|*id==0||!(1..=100).contains(rank)){return Err("item requirement skill capacity/rank".into());}
    ui.set_player_req_state(PlayerReqState{level,class_id:n(requirements,"class_id").clamp(1,32),
        race_id:n(requirements,"race_id").clamp(1,32),skills:skills.into_iter().collect(),can_dual_wield:true,..Default::default()});Ok(())
}
pub(super) fn enchants(v:&Value)->Vec<EnchantView>{
    v["enchants"].as_array().into_iter().flatten().take(7).map(|row|EnchantView{slot:n(row,"slot").min(6) as u8,
        negative:row["negative"]==true,name:s(row,"name"),charges:n(row,"charges"),remaining_ms:row["remaining_ms"].as_u64()}).collect()
}
pub(super) fn locked(v:&Value,services:&Value)->bool {
    v["locked"]==true || services["item_binding"]["locked_items"].as_array().is_some_and(|a|a.contains(&v["instance_id"]))
}
pub(super) fn feed_sets(ui:&mut UiScript,v:&Value)->Result<(),String>{
    if !v.is_array(){return Ok(());}
    for row in v.as_array().filter(|r|r.len()<=64).ok_or("item set capacity")? {
        let members:Vec<(u32,Option<String>)>=serde_json::from_value(row["members"].clone()).map_err(|e|e.to_string())?;
        let bonuses:Vec<(u32,String)>=serde_json::from_value(row["bonuses"].clone()).map_err(|e|e.to_string())?;
        if members.is_empty()||members.len()>17||bonuses.len()>8{return Err("item set member/bonus capacity".into());}
        ui.set_item_set(n(row,"id"),ItemSetView{name:s(row,"name"),members,bonuses,
            required_skill:n(row,"required_skill"),required_skill_rank:n(row,"required_skill_rank"),
            required_skill_name:row["required_skill_name"].as_str().map(str::to_owned)});
    }Ok(())
}
pub(super) fn requests(ui:&mut UiScript)->Vec<Value>{
    let mut rows:Vec<Value>=ui.take_item_stat_asks().into_iter().map(|id|json!({"op":"ItemInfo","id":id})).collect();
    rows.extend(ui.take_item_set_asks().into_iter().map(|id|json!({"op":"ItemSetInfo","id":id})));rows
}
