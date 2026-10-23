//! Original guild, loot-roll and trainer models over canonical GG transactions.
use crate::Host;
use engine_ui_core::script::{UiScript, ScriptValue, GuildState, GuildMemberInfo, GuildRankInfo,
    GuildRequest, LootRollEntry, LootRollsState, TrainerState, TrainerService, TrainerServiceCategory,
    PetStats, PetBookState, SpellSlotView, PetActionView,TrainerTooltip,SpellTooltipView};
use serde_json::{Value,json};
fn n(v:&Value,k:&str)->u32 {v[k].as_f64().filter(|n|n.is_finite()).unwrap_or(0.).clamp(0.,u32::MAX as f64) as u32}
fn s(v:&Value,k:&str)->String {v[k].as_str().unwrap_or("").into()}

pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let old=host.views.get("social_services").cloned().unwrap_or(Value::Null);
    let g=&v["guild"];
    if old["guild"]!=*g{
        let mut state=GuildState::default();
        if g.is_object(){
            let roster=g["roster"].as_array().filter(|r|r.len()<=64).ok_or("guild roster capacity")?;
            let ranks=g["ranks"].as_array().filter(|r|r.len()<=10).ok_or("guild rank capacity")?;
            state.in_guild=g["in_guild"]==true;state.name=s(g,"name");state.rank_index=n(g,"own_rank");state.is_leader=state.in_guild&&state.rank_index==0;
            state.rank_name=ranks.get(state.rank_index as usize).map(|r|s(r,"name")).unwrap_or_default();
            state.rights=n(g,"rights");state.motd=s(g,"motd");state.info_text=s(g,"info");state.selection=n(g,"selection");state.show_offline=g["show_offline"]==true;
            state.ranks=ranks.iter().map(|r|GuildRankInfo{name:s(r,"name"),rights:n(r,"rights")}).collect();
            state.roster=roster.iter().map(|r|GuildMemberInfo{name:s(r,"name"),rank:s(r,"rank_name"),rank_index:n(r,"rank"),
                level:n(r,"level"),class:s(r,"class_name"),zone:s(r,"zone"),note:s(r,"note"),officer_note:s(r,"officer_note"),online:r["online"]==true,..Default::default()}).collect();
            state.num_members=state.roster.iter().filter(|r|state.show_offline||r.online).count();
        }
        host.ui.set_guild(state);host.ui.fire_event("GUILD_ROSTER_UPDATE",vec![]);host.ui.fire_event("PLAYER_GUILD_UPDATE",vec![ScriptValue::Str("player".into())]);
    }
    let rolls=match v["loot_rolls"].as_array(){
        Some(r) if r.len()<=64=>r.as_slice(),None if v["loot_rolls"].is_null()=>&[],_=>return Err("loot roll capacity".into())
    };
    let mut projected=Vec::new();let previous=old["loot_rolls"].as_array();
    for r in rolls{
        if s(r,"method")=="master"{continue;}
        let item=&r["attachment"];
        projected.push(LootRollEntry{roll_id:n(r,"id"),name:Some(s(item,"name")),texture:Some(s(item,"icon")),quantity:n(item,"quantity"),
            quality:Some(n(item,"quality")),bind_on_pickup:r["bind"]==true,time_left_ms:n(r,"remaining_ms"),item_id:n(item,"item_id"),link:Some(s(item,"link")),..Default::default()});
    }
    host.ui.set_loot_rolls(LootRollsState{rolls:projected});
    for r in rolls{if s(r,"method")!="master"&&!previous.is_some_and(|p|p.iter().any(|x|x["id"]==r["id"])){
        host.ui.fire_event("START_LOOT_ROLL",vec![ScriptValue::Int(n(r,"id") as i64),ScriptValue::Int(n(r,"remaining_ms") as i64)]);}}
    if let Some(previous)=previous{for r in previous{if !rolls.iter().any(|x|x["id"]==r["id"]){host.ui.fire_event("CANCEL_LOOT_ROLL",vec![ScriptValue::Int(n(r,"id") as i64)]);}}}
    let trainer=&v["trainer"];
    if old["trainer"]!=*trainer{
        let profession=trainer["kind"]=="PROFESSION";
        let mut services=Vec::new();
        if let Some(rows)=trainer["rows"].as_array(){
            if rows.len()>64{return Err("trainer capacity".into());}
            for r in rows{
                if profession{host.ui.set_spell_tooltip(n(r,"id"),SpellTooltipView{name:s(r,"name"),description:s(r,"description"),item_met:true,form_met:true,..Default::default()});}
                services.push(TrainerService{spell_id:n(r,"id"),name:Some(s(r,"name")),texture:Some(s(r,"icon")),cost:n(r,"cost"),description:s(r,"description"),
                level_req:n(r,"level"),category:match r["category"].as_str(){Some("used")=>TrainerServiceCategory::Used,Some("available")=>TrainerServiceCategory::Available,_=>TrainerServiceCategory::Unavailable},
                group_key:1,group_name:if profession{"GG Professions"}else{"Pet abilities"}.into(),tooltip:TrainerTooltip::Spell{spell_id:n(r,"id"),alt_caster:!profession},..Default::default()});}
        }
        let kind=if profession{2}else{3};
        host.ui.set_trainer(if trainer["open"]==true{Some(TrainerState{services,greeting:if profession{"GG crafting professions"}else{"GG pet training"}.into(),trainer_type:kind,..Default::default()})}else{None});
        if trainer["open"]==true{if old["trainer"]["open"]!=true||old["trainer"]["kind"]!=trainer["kind"]{host.ui.reset_trainer_list_state(kind);host.ui.fire_event("TRAINER_SHOW",vec![]);}else{host.ui.fire_event("TRAINER_UPDATE",vec![]);}}
        else if old["trainer"]["open"]==true{host.ui.fire_event("TRAINER_CLOSED",vec![]);}
    }
    let pet=&v["pet"];
    if pet.is_object()&&old["pet"]!=*pet{
        let learned=pet["learned"].as_array().filter(|r|r.len()<=32).ok_or("pet learned spell capacity")?;
        let slots=learned.iter().map(|r|SpellSlotView{spell_id:n(r,"id"),name:s(r,"name"),texture:Some(s(r,"icon")),passive:r["passive"]==true,autocast:Some((r["passive"]!=true,r["autocast"]==true)),
            packed:n(r,"id")|((if r["autocast"]==true{192}else{128})<<24),..Default::default()}).collect();
        host.ui.set_pet_book(PetBookState{token:Some("PET".into()),slots});
        host.ui.set_pet_stats(true,PetStats{hunter_pet:true,happiness:Some(n(pet,"happiness")),damage_percentage:n(pet,"damage_percentage") as f32,
            loyalty_rate:pet["loyalty_rate"].as_f64().unwrap_or(0.) as f32,loyalty:Some(format!("(Loyalty Level {})",n(pet,"loyalty"))),
            training_points:(n(pet,"training_total") as u16,n(pet,"training_spent") as u16),experience:(n(pet,"xp"),n(pet,"next_xp")),family:Some(s(pet,"species")),
            food_types:pet["food_types"].as_array().map(|v|v.iter().filter_map(|s|s.as_str().map(str::to_owned)).collect()).unwrap_or_default(),..Default::default()});
        let mut actions=Vec::new();
        for word in pet["slots"].as_array().ok_or("pet bar required")?{
            let word=word.as_u64().unwrap_or(0) as u32;let value=word&0xffffff;let kind=word>>24;
            let spell=learned.iter().find(|r|n(r,"id")==value);
            let token=match(kind,value){(7,2)=>"PET_ACTION_ATTACK",(7,1)=>"PET_ACTION_FOLLOW",(7,0)=>"PET_ACTION_STAY",(6,2)=>"PET_MODE_AGGRESSIVE",(6,1)=>"PET_MODE_DEFENSIVE",(6,0)=>"PET_MODE_PASSIVE",_=>""};
            actions.push(PetActionView{name:spell.map(|r|s(r,"name")).or_else(||if token.is_empty(){None}else{Some(token.into())}),texture:spell.map(|r|s(r,"icon")).or_else(||Some(token.into())),
                is_token:spell.is_none(),spell_id:spell.map(|_|value),autocast_allowed:spell.is_some_and(|r|r["passive"]!=true),autocast_enabled:spell.is_some_and(|r|r["autocast"]==true),
                packed:spell.map(|r|value|((if r["autocast"]==true{192}else{128})<<24)).unwrap_or(word),active:(kind==7&&value==n(pet,"command"))||(kind==6&&value==n(pet,"reaction")),
                attack_active:kind==7&&value==2&&!s(pet,"target").is_empty(),..Default::default()});
        }
        let alive=n(pet,"health")>0;host.ui.set_pet_actions(true,alive,alive,actions);
    }
    host.views.insert("social_services".into(),v.clone());Ok(())
}

pub(super) fn requests(ui:&mut UiScript)->Value{
    let mut out=Vec::new();
    for r in ui.take_guild_requests(){out.push(match r{
        GuildRequest::Roster=>json!({"op":"GuildRoster"}),GuildRequest::Info=>json!({"op":"GuildInfo"}),
        GuildRequest::Invite(target)=>json!({"op":"GuildInvite","target":target}),GuildRequest::Uninvite(target)=>json!({"op":"GuildUninvite","target":target}),
        GuildRequest::Promote(target)=>json!({"op":"GuildPromote","target":target}),GuildRequest::Demote(target)=>json!({"op":"GuildDemote","target":target}),
        GuildRequest::SetLeader(target)=>json!({"op":"GuildLeader","target":target}),GuildRequest::Accept=>json!({"op":"GuildAccept"}),GuildRequest::Decline=>json!({"op":"GuildDecline"}),
        GuildRequest::Leave=>json!({"op":"GuildLeave"}),GuildRequest::Disband=>json!({"op":"GuildDisband"}),GuildRequest::SetMotd(text)=>json!({"op":"GuildMotd","text":text}),
        GuildRequest::SetInfoText(text)=>json!({"op":"GuildInfoText","text":text}),GuildRequest::SetPublicNote{index,note}=>json!({"op":"GuildPublicNote","index":index,"text":note}),
        GuildRequest::SetOfficerNote{index,note}=>json!({"op":"GuildOfficerNote","index":index,"text":note}),
        GuildRequest::SaveRank{rank_index,rights,name}=>json!({"op":"GuildSaveRank","rank_index":rank_index,"rights":rights,"name":name}),
        GuildRequest::AddRank(name)=>json!({"op":"GuildAddRank","name":name}),GuildRequest::DelRank=>json!({"op":"GuildDelRank"}),
        GuildRequest::Select(index)=>json!({"op":"GuildSelect","index":index}),GuildRequest::SetShowOffline(show)=>json!({"op":"GuildShowOffline","show":show}),
        GuildRequest::Sort(field)=>json!({"op":"GuildSort","field":field})});}
    for (id,vote) in ui.take_loot_roll_votes(){out.push(json!({"op":"LootRollVote","id":id,"vote":vote}));}
    for (id,vote) in ui.take_loot_roll_confirms(){out.push(json!({"op":"LootRollConfirm","id":id,"vote":vote}));}
    for spell_id in ui.take_trainer_buys(){out.push(json!({"op":"TrainerBuy","spell_id":spell_id}));}
    if ui.take_trainer_close(){out.push(json!({"op":"TrainerClose"}));}
    if ui.take_pet_unlearn_confirms()>0{out.push(json!({"op":"PetUnlearn"}));}
    for target in ui.take_uninvite_requests(){out.push(json!({"op":"GroupKick","target":target}));}
    json!(out)
}
