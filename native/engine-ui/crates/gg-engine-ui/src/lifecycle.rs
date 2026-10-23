//! Original death/duel/bind APIs over the GG authoritative lifecycle.
use engine_ui_core::script::{UiScript,DeathAction,DeathUiState,DuelRequest,ScriptValue};
use serde_json::{Value,json};
use crate::Host;

pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let old=host.views.get("lifecycle").cloned().unwrap_or(Value::Null);
    let finite=|key:&str|->Result<f32,String>{let n=v[key].as_f64().unwrap_or(0.);if !n.is_finite()||n<0.||n>1e9{return Err("invalid lifecycle timer".into());}Ok(n as f32)};
    host.ui.set_death(DeathUiState{release_remaining:if v["dead"]==true{Some(finite("release_remaining")?)}else{None},
        recovery_delay:finite("recovery_delay")?,resurrect_sickness:v["has_sickness"]==true,resurrect_has_timer:v["has_timer"]==true,
        spirit_healer_in_range:v["healer_in_range"]==true,sickness_duration:v["sickness_duration"].as_str().map(str::to_owned),self_res_label:v["self_res_label"].as_str().map(str::to_owned)});
    host.ui.set_binder_pending(v["binder_pending"]==true);
    if old["dead"]!=true&&v["dead"]==true{host.ui.fire_event("PLAYER_DEAD",vec![]);}
    if old["ghost"]!=true&&v["ghost"]==true{host.ui.fire_event("PLAYER_GHOST",vec![]);}
    if old["dead"]==true&&v["dead"]!=true{host.ui.fire_event("PLAYER_ALIVE",vec![]);host.ui.fire_event("PLAYER_UNGHOST",vec![]);}
    if old["duel"]["state"]!=v["duel"]["state"]&&v["duel"]["state"]=="ACTIVE"{host.ui.fire_event("DUEL_INBOUNDS",vec![]);}
    if old["duel"].is_object()&&!v["duel"].is_object(){host.ui.fire_event("DUEL_FINISHED",vec![]);}
    if old["duel"]["bounds_at"]!=v["duel"]["bounds_at"]&&v["duel"]["bounds_at"].as_f64().unwrap_or(0.)>0.{host.ui.fire_event("DUEL_OUTOFBOUNDS",vec![ScriptValue::Int(10000)]);}
    host.views.insert("lifecycle".into(),v.clone());Ok(())
}

pub(super) fn requests(ui:&mut UiScript)->Vec<Value>{
    let mut out=Vec::new();
    for action in ui.take_death_actions(){out.push(json!({"op":match action{
        DeathAction::Repop=>"DeathRepop",DeathAction::RetrieveCorpse=>"DeathRetrieveCorpse",DeathAction::AcceptResurrect=>"DeathAcceptResurrect",
        DeathAction::DeclineResurrect=>"DeathDeclineResurrect",DeathAction::AcceptXpLoss=>"DeathAcceptXpLoss",DeathAction::UseSoulstone=>"DeathUseSoulstone"}}));}
    for action in ui.take_duel_requests(){out.push(match action{
        DuelRequest::Accept=>json!({"op":"DuelAccept"}),DuelRequest::Cancel=>json!({"op":"DuelCancel"}),
        DuelRequest::StartByName(target)|DuelRequest::StartByUnit(target)=>json!({"op":"DuelStart","target":target})});}
    if ui.take_binder_confirms()>0{out.push(json!({"op":"BinderConfirm"}));}
    if ui.take_area_spirit_accepts()>0{out.push(json!({"op":"DeathAcceptXpLoss"}));}
    out
}
