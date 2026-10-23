//! Original battleground readers over an actual, bounded local GG practice match.
use engine_ui_core::script::{BattlefieldListView,BattlefieldMapInfo,BattlefieldQueueSlot,
    BattlefieldScoreRow,BattlefieldScores,BattlefieldStatColumn,HonorState,InspectHonorData,
    BattlefieldPositionView,ScriptValue};
use serde_json::{Value,json};
use crate::Host;
fn n(v:&Value,k:&str)->u32{v[k].as_u64().unwrap_or(0).min(u32::MAX as u64) as u32}
fn s(v:&Value,k:&str)->String{v[k].as_str().unwrap_or("").into()}

pub(super) fn feed(h:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let previous=h.views.get("battlefields").cloned().unwrap_or(Value::Null);
    let queue=v["queue"].as_array().filter(|r|r.len()<=3).ok_or("battlefield queue capacity")?;
    let mut slots:[BattlefieldQueueSlot;3]=Default::default();
    for (i,row) in queue.iter().enumerate(){
        slots[i]=BattlefieldQueueSlot{map_id:n(row,"map"),map_name:Some(s(v,"name")),status:n(row,"status"),
            instance_id:n(v,"instance"),min_level:1,max_level:60,port_expiration_ms:n(row,"remaining_ms"),
            estimated_wait_ms:3000,time_waited_ms:n(row,"waited_ms")};
    }
    if v["listed"]==true{
        h.ui.set_battlefield_list(BattlefieldListView{instances:vec![n(v,"instance")],bracket_min:1,bracket_max:60,
            info:Some(BattlefieldMapInfo{name:s(v,"name"),description:Some(s(v,"description")),min_level:1,max_level:60,
                ..Default::default()}),group_queue:true});
    }
    h.ui.set_battlefield_queue(slots,0);
    let mut scores=Vec::new();
    for row in v["scores"].as_array().filter(|r|r.len()<=10).ok_or("battlefield score capacity")?{
        let mut stats=[0;8];stats[0]=n(row,"wins");
        scores.push(BattlefieldScoreRow{name:s(row,"name"),honor_gained:n(row,"honor"),deaths:n(row,"deaths"),
            faction:row["team"].as_i64().unwrap_or(-1) as i32,race:Some("GG".into()),
            class:Some("Local arena combatant".into()),stats,..Default::default()});
    }
    h.ui.set_battlefield_scores(BattlefieldScores{rows:scores,ended:v["ended"]==true,winner:n(v,"winner") as u8,
        columns:vec![BattlefieldStatColumn{text:"Combat victories".into(),icon:"GG\\Arena".into(),
            tooltip:"Nonlethal wins in the local GG practice arena".into()}]});
    h.ui.set_battlefield_run_time_ms(n(v,"run_ms"));
    let mut positions=Vec::new();
    for row in v["positions"].as_array().filter(|r|r.len()<=40).ok_or("battlefield position capacity")?{
        let p:[f32;2]=serde_json::from_value(row["uv"].clone()).map_err(|e|e.to_string())?;
        if p.iter().any(|n|!n.is_finite()||!(0. ..=1.).contains(n)){return Err("invalid battlefield position".into());}
        positions.push(BattlefieldPositionView{uv:(p[0],p[1]),name:Some(s(row,"name"))});
    }
    h.ui.set_battlefield_positions(positions,None,1.);
    h.ui.set_instance_type(Some(if v["active"]==true{3}else{0}));
    let honor=&v["honor"];
    h.ui.set_honor(Some(HonorState{yesterday_honor:n(honor,"yesterday_honor"),this_week_honor:n(honor,"this_week_honor"),
        last_week_honor:n(honor,"last_week_honor"),..Default::default()}));
    // Notify only after readers contain the new values. Millisecond countdowns
    // are not status transitions and must not fire events every snapshot.
    for slot in 0..3 {
        let before=&previous["queue"][slot];let after=&v["queue"][slot];
        if before["id"]!=after["id"]||before["status"]!=after["status"] {
            h.ui.fire_event("UPDATE_BATTLEFIELD_STATUS",vec![ScriptValue::Int(slot as i64+1)]);
        }
    }
    if previous["scores"]!=v["scores"]||previous["ended"]!=v["ended"]||previous["winner"]!=v["winner"] {
        h.ui.fire_event("UPDATE_BATTLEFIELD_SCORE",vec![]);
    }
    if previous["honor"]!=v["honor"] {h.ui.fire_event("PLAYER_PVP_KILLS_CHANGED",vec![]);}
    if previous["listed"]!=true&&v["listed"]==true {h.ui.fire_event("BATTLEFIELDS_SHOW",vec![]);}
    let inspect=&v["inspect"];
    let previous=h.views.get("inspect_honor");
    if previous!=Some(inspect){
        h.ui.set_inspect_honor(if inspect.is_object(){Some(InspectHonorData{guid:inspect["guid"].as_u64().unwrap_or(0),
            yesterday_honor:n(inspect,"yesterday_honor"),this_week_honor:n(inspect,"this_week_honor"),
            last_week_honor:n(inspect,"last_week_honor"),..Default::default()})}else{None});
        if inspect.is_object(){h.ui.fire_event("INSPECT_HONOR_UPDATE",vec![ScriptValue::Int(0)]);}
        h.views.insert("inspect_honor".into(),inspect.clone());
    }
    h.views.insert("battlefields".into(),v.clone());Ok(())
}

pub(super) fn requests(h:&mut Host)->Vec<Value>{
    let shown=h.views.get("battlefields").cloned().unwrap_or(Value::Null);
    let mut rows=Vec::new();
    for map in h.ui.take_battlefield_list_requests(){rows.push(json!({"op":"BattlefieldList","map":map}));}
    for (instance,as_group) in h.ui.take_battlefield_join_requests(){
        rows.push(json!({"op":"BattlefieldJoin","map":shown["map"],"instance":instance,"as_group":as_group}));
    }
    for (slot,accept) in h.ui.take_battlefield_port_requests(){
        let id=shown["queue"].get(slot as usize-1).and_then(|v|v.get("id")).cloned().unwrap_or(Value::Null);
        rows.push(json!({"op":"BattlefieldPort","slot":slot,"queue_id":id,"accept":accept}));
    }
    if h.ui.take_battlefield_score_requests()>0{rows.push(json!({"op":"BattlefieldScore"}));}
    if h.ui.take_battlefield_position_requests()>0{rows.push(json!({"op":"BattlefieldPositions"}));}
    if h.ui.take_battlefield_leave_requests()>0{rows.push(json!({"op":"BattlefieldLeave"}));}
    if h.ui.take_inspect_honor_requests()>0{rows.push(json!({"op":"InspectHonor"}));}
    rows
}
