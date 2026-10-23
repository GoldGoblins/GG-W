//! Local GG inventory transactions through the unchanged original crafting/loot APIs.
use crate::Host;
use engine_ui_core::script::{CraftRecipe,CraftReagent,CraftState,CraftTooltip,LootRow,LootState,
    ScriptValue,TradeSkillDifficulty,TradeSkillRecipe,TradeSkillReagent,TradeSkillState,UiScript};
use serde_json::{json,Value};

fn uint(v:&Value,key:&str)->Result<u32,String>{
    v[key].as_u64().and_then(|n|n.try_into().ok()).ok_or_else(||format!("invalid local action {key}"))
}
fn text(v:&Value,key:&str)->Result<String,String>{
    let s=v[key].as_str().ok_or_else(||format!("local action {key} required"))?;
    if s.len()>1024{return Err("local action text capacity exceeded".into())}Ok(s.into())
}
fn rows<'a>(v:&'a Value,key:&str,limit:usize)->Result<&'a [Value],String>{
    let rows=v[key].as_array().map(Vec::as_slice).unwrap_or(&[]);
    if rows.len()>limit{return Err("local action row capacity exceeded".into())}Ok(rows)
}

pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    let book=&v["craft_book"];
    if book.is_object() && host.views.get("craft_book")!=Some(book){
        let opened=book["open"]==true;
        let kind=book["book"].as_str().unwrap_or("");
        if opened&&!matches!(kind,"TRADE_SKILL"|"CRAFT"){return Err("unknown local craft book".into())}
        let mut trades=Vec::new();let mut crafts=Vec::new();
        for row in rows(book,"rows",128)?{
            let spell_id=uint(row,"spell_id")?;let product=uint(row,"product_item")?;
            let name=text(row,"name")?;let quantity=uint(row,"quantity")?;
            let mut trade_reagents=Vec::new();let mut craft_reagents=Vec::new();
            for r in rows(row,"reagents",8)?{
                let item=uint(r,"item_id")?;let name=Some(text(r,"name")?);
                let icon=r["icon"].as_str().map(str::to_owned);
                let need=uint(r,"need")?;let have=uint(r,"have")?;
                trade_reagents.push(TradeSkillReagent{item,name:name.clone(),icon:icon.clone(),need,have});
                craft_reagents.push(CraftReagent{item,name,icon,need,have});
            }
            let icon=row["icon"].as_str().map(str::to_owned);let available=uint(row,"available")?;
            // GG has no original profession difficulty rolls: project its
            // deterministic recipes as trivial, without inventing skill-ups.
            trades.push(TradeSkillRecipe{group:Some((0,0,"GG Recipes".into())),spell_id,name:name.clone(),difficulty:TradeSkillDifficulty::Trivial,
                num_available:available,icon:icon.clone(),min_made:quantity,max_made:quantity,cooldown_secs:None,
                product_item:product,product_inv_type:0,product_item_level:0,reagents:trade_reagents,tools:vec![]});
            crafts.push(CraftRecipe{spell_id,name,sub_name:String::new(),difficulty:TradeSkillDifficulty::Trivial,
                num_available:available,icon,description:Some(text(row,"description")?),needs_item_target:false,
                reagents:craft_reagents,tools:vec![],tooltip:CraftTooltip::Item(product),spell_level:0});
        }
        let previous=host.views.get("craft_book");
        let old_kind=previous.and_then(|b|b["book"].as_str()).unwrap_or("").to_owned();
        let old_open=previous.is_some_and(|b|b["open"]==true);
        let changed=!old_open || previous.map(|b|&b["session"])!=Some(&book["session"]);
        host.ui.set_trade_skill(if opened&&kind=="TRADE_SKILL"{Some(TradeSkillState{line:0x4747,line_name:text(book,"name")?,rank:0,max_rank:0,recipes:trades,repeat_count:uint(book,"repeat_count")?})}else{None});
        host.ui.set_craft(if opened&&kind=="CRAFT"{Some(CraftState{name:text(book,"name")?,rank:0,max_rank:0,craft_type:3,recipes:crafts})}else{None});
        host.ui.set_casting(opened&&book["repeat_count"].as_u64().unwrap_or(0)>0);
        if old_open&&(!opened||old_kind!=kind){host.ui.fire_event(if old_kind=="CRAFT"{"CRAFT_CLOSE"}else{"TRADE_SKILL_CLOSE"},vec![]);}
        host.views.insert("craft_book".into(),book.clone());
        if let Some(error)=book["error"].as_str().filter(|s|!s.is_empty()){
            host.ui.fire_event("UI_ERROR_MESSAGE",vec![ScriptValue::Str(error.into())]);
        }
        if opened{host.ui.fire_event(if kind=="CRAFT"{if changed{"CRAFT_SHOW"}else{"CRAFT_UPDATE"}}else if changed{"TRADE_SKILL_SHOW"}else{"TRADE_SKILL_UPDATE"},vec![]);}
    }
    let loot=&v["loot"];
    if loot.is_object() && host.views.get("loot")!=Some(loot){
        let opened=loot["open"]==true;let mut projected=Vec::new();
        for row in rows(loot,"rows",64)?{
            projected.push(if row.is_null(){None}else{Some(LootRow{name:Some(text(row,"name")?),
                texture:row["texture"].as_str().map(str::to_owned),quantity:uint(row,"quantity")?,
                quality:Some(uint(row,"quality")?.min(6)),item_id:uint(row,"item_id")?,
                link:row["link"].as_str().map(str::to_owned),..Default::default()})});
        }
        let old=host.views.get("loot");let old_open=old.is_some_and(|l|l["open"]==true);
        let changed=!old_open || old.map(|l|&l["session"])!=Some(&loot["session"]);
        let cleared:Vec<usize>=if !changed&&opened{rows(old.unwrap(),"rows",64)?.iter().enumerate()
            .filter(|(i,r)|!r.is_null()&&loot["rows"][*i].is_null()).map(|(i,_)|i+1).collect()}else{vec![]};
        let master_candidates=loot["master_candidates"].as_array().map(|v|v.iter().take(40).map(|s|s.as_str().map(str::to_owned)).collect()).unwrap_or_default();
        host.ui.set_loot(if opened{Some(LootState{rows:projected,master_candidates,..Default::default()})}else{None});
        host.views.insert("loot".into(),loot.clone());
        if old_open&&(!opened||changed){host.ui.fire_event("LOOT_CLOSED",vec![]);}
        if opened&&changed{host.ui.fire_event("LOOT_OPENED",vec![]);}
        for index in cleared{host.ui.fire_event("LOOT_SLOT_CLEARED",vec![ScriptValue::Int(index as i64)]);}
    }
    Ok(())
}

pub(super) fn requests(ui:&mut UiScript)->Value{
    let touched=ui.take_trade_skill_touched();
    if touched{ui.fire_event("TRADE_SKILL_UPDATE",vec![]);}
    json!({"craft_dos":ui.take_craft_dos(),"craft_close":ui.take_craft_close(),
        "trade_skill_dos":ui.take_trade_skill_dos(),"trade_skill_close":ui.take_trade_skill_close(),
        "loot_picks":ui.take_loot_picks(),"loot_confirms":ui.take_loot_confirms(),
        "loot_close":ui.take_loot_close(),"loot_master_gives":ui.take_loot_master_gives()})
}
