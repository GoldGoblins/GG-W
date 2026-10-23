//! Original taxi, summon and stuck intents over real local destinations.
use engine_ui_core::script::{UiScript,TaxiUiState,TaxiUiNode,TaxiNodeType,SummonConfirmUiState};
use serde_json::{Value,json};
use crate::Host;
fn n(v:&Value,k:&str)->u32{v[k].as_f64().unwrap_or(0.).clamp(0.,u32::MAX as f64) as u32}
fn s(v:&Value,k:&str)->String{v[k].as_str().unwrap_or("").into()}
pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let state=if v["open"]==true{
        let mut nodes=Vec::new();
        for row in v["nodes"].as_array().filter(|r|r.len()<=32).ok_or("taxi node capacity")?{
            let p:[f32;2]=serde_json::from_value(row["position"].clone()).map_err(|e|e.to_string())?;
            let src:[f32;2]=serde_json::from_value(row["source"].clone()).map_err(|e|e.to_string())?;
            if p.iter().chain(src.iter()).any(|n|!n.is_finite()||!(0. ..=1.).contains(n)){return Err("invalid taxi map coordinates".into());}
            let current=row["current"]==true;
            nodes.push(TaxiUiNode{name:s(row,"name"),node_type:if current{TaxiNodeType::Current}else{TaxiNodeType::Reachable},
                pos:(p[0],p[1]),cost:n(row,"cost"),routes:if current{vec![]}else{vec![[src[0],src[1],p[0],p[1]]]}});
        }
        Some(TaxiUiState{art:"GG\\TaxiMap".into(),nodes})
    }else{None};
    let riding=v["riding"]==true;
    let previous=host.views.get("travel_riding").and_then(Value::as_bool);
    host.ui.set_taxi(state);host.ui.set_on_taxi(riding);
    host.ui.set_summon_confirm(SummonConfirmUiState{summoner:s(&v["summon"],"summoner"),area:s(&v["summon"],"area"),time_left_ms:n(&v["summon"],"remaining_ms")});
    if riding&&previous!=Some(true){host.ui.fire_event("PLAYER_CONTROL_LOST",vec![]);}
    if !riding&&previous==Some(true){host.ui.fire_event("PLAYER_CONTROL_GAINED",vec![]);}
    host.views.insert("travel_riding".into(),json!(riding));Ok(())
}
pub(super) fn requests(ui:&mut UiScript)->Vec<Value>{
    let mut rows=Vec::new();for index in ui.take_taxi_node(){rows.push(json!({"op":"TaxiTake","index":index}));}
    if ui.take_taxi_close(){rows.push(json!({"op":"TaxiClose"}));}
    if ui.take_summon_confirms()>0{rows.push(json!({"op":"SummonConfirm"}));}
    if ui.take_stuck_casts()>0{rows.push(json!({"op":"StuckStart"}));}
    rows
}
