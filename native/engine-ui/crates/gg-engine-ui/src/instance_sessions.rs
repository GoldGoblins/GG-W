//! Actual owned GG lockouts and local group-finder status through original Lua.
use engine_ui_core::script::SavedInstanceInfo;
use serde_json::{Value,json};
use crate::Host;
fn n(v:&Value,k:&str)->u32{v[k].as_u64().unwrap_or(0).min(u32::MAX as u64) as u32}
fn s(v:&Value,k:&str)->String{v[k].as_str().unwrap_or("").into()}
pub(super) fn feed(h:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object(){return Ok(());}
    let lockouts=v["lockouts"].as_array().filter(|r|r.len()<=32).ok_or("instance lockout capacity")?;
    h.ui.set_saved_instances(lockouts.iter().map(|row|SavedInstanceInfo{name:s(row,"name"),instance:n(row,"id"),reset:n(row,"remaining")}).collect());
    h.ui.set_can_reset_instances(v["can_reset"]==true);
    if h.views.get("battlefields").is_none_or(|b|b["active"]!=true){h.ui.set_instance_type(Some(n(v,"type")));}
    let meeting=&v["meeting"];
    let text=if meeting.is_object(){format!("{}: {}",s(meeting,"name"),if meeting["stage"]=="OFFER"{"Local companions ready"}else{"Looking for local companions"})}
             else{"No local group request".into()};
    h.ui.set_meeting_stone(n(meeting,"area"),Some(text));
    let signature=json!({"lockouts":lockouts.iter().map(|r|json!([r["id"],r["defeated"]])).collect::<Vec<_>>(),
        "can_reset":v["can_reset"],"type":v["type"]});
    if h.views.get("instance_signature")!=Some(&signature) {
        h.ui.fire_event("UPDATE_INSTANCE_INFO",vec![]);
        h.views.insert("instance_signature".into(),signature);
    }
    let signature=json!([meeting["ref"],meeting["stage"],meeting["candidates"]]);
    if h.views.get("meeting_signature")!=Some(&signature) {
        h.ui.fire_event("MEETINGSTONE_CHANGED",vec![]);
        h.views.insert("meeting_signature".into(),signature);
    }
    h.views.insert("instance_sessions".into(),v.clone());Ok(())
}
pub(super) fn requests(h:&mut Host)->Vec<Value>{
    let mut rows=Vec::new();let resets=h.ui.take_reset_instance_asks();
    if resets>0{rows.push(json!({"op":"InstanceReset","requests":resets}));}
    let cancels=h.ui.take_meeting_stone_cancels();
    if cancels>0{rows.push(json!({"op":"MeetingStoneCancel","requests":cancels}));}
    rows
}
