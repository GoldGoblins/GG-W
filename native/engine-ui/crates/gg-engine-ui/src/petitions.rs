//! Original charter getters over the canonical owned item and local signers.
use engine_ui_core::script::{PetitionState,PetitionRecordView,PetitionRequest};
use serde_json::{Value,json};
use super::Host;

pub(super) fn feed(h:&mut Host,v:&Value)->Result<(),String>{
    let old=h.views.get("petition").cloned().unwrap_or(Value::Null);
    if old==*v{return Ok(());}
    let r=&v["record"];
    let signers=if r.is_object(){r["signer_names"].as_array().filter(|s|s.len()<=9).ok_or("petition signer capacity")?
        .iter().map(|n|n.as_str().map(str::to_owned)).collect()}else{Vec::new()};
    let record=if r.is_object(){Some(PetitionRecordView{petition_type:"charter".into(),title:r["title"].as_str().ok_or("petition title required")?.into(),
        body_text:String::new(),max_signatures:r["max_signatures"].as_u64().filter(|n|*n<=9).ok_or("petition signature requirement")? as i32,
        originator:r["owner_name"].as_str().map(str::to_owned),is_originator:r["is_originator"]==true})}else{None};
    h.ui.set_petition(PetitionState{charter_cost:if v["registrar_open"]==true{v["cost"].as_u64().unwrap_or(0).min(u32::MAX as u64) as u32}else{0},
        signers,record,can_sign:if v["open"]==true{v["can_sign"]==true}else{true}});
    let switched=old["open"]==true&&v["open"]==true&&old["record"]["item"]!=r["item"];
    if (old["open"]==true&&v["open"]!=true)||switched{h.ui.fire_event("PETITION_CLOSED",vec![]);h.ui.drop_petition_close_intents();}
    if v["open"]==true{h.ui.fire_event("PETITION_SHOW",vec![]);}
    if (old["registrar_open"]==true)!=(v["registrar_open"]==true){h.ui.fire_event(if v["registrar_open"]==true{"GUILD_REGISTRAR_SHOW"}else{"GUILD_REGISTRAR_CLOSED"},vec![]);h.ui.drop_petition_close_intents();}
    h.views.insert("petition".into(),v.clone());Ok(())
}

pub(super) fn requests(ui:&mut engine_ui_core::script::UiScript)->Vec<Value>{
    ui.take_petition_requests().into_iter().map(|r|match r{
        PetitionRequest::Buy(name)=>json!({"op":"PetitionBuy","name":name}),
        PetitionRequest::TurnIn=>json!({"op":"PetitionTurnIn"}),
        PetitionRequest::CloseRegistrar=>json!({"op":"PetitionRegistrarClose"}),
        PetitionRequest::TabardInfo=>json!({"op":"TabardOpen"}),
        PetitionRequest::Sign(_)=>json!({"op":"PetitionSign"}),
        PetitionRequest::Offer=>json!({"op":"PetitionOffer","target":"target"}),
        PetitionRequest::Rename(name)=>json!({"op":"PetitionRename","name":name}),
        PetitionRequest::ClosePetition=>json!({"op":"PetitionClose"}),
        PetitionRequest::NameRefused(_)=>json!({"op":"PetitionNameRefused"})
    }).collect()
}
