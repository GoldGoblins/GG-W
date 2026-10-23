//! The same GG live camera exposes the original cinematic flag and edges.
use crate::Host;
use serde_json::{Value,json};
pub(super) fn feed(h:&mut Host,v:&Value){
    let active=v["active"]==true;
    let previous=h.views.get("opening_cinematic").is_some_and(|r|r["active"]==true);
    h.ui.set_in_cinematic(active);
    if active!=previous{h.ui.fire_event(if active{"CINEMATIC_START"}else{"CINEMATIC_STOP"},vec![]);}
    h.views.insert("opening_cinematic".into(),v.clone());
}
pub(super) fn requests(h:&mut Host)->Vec<Value>{
    let count=h.ui.take_opening_cinematic_asks();
    if count==0{vec![]}else{vec![json!({"op":"CinematicStart","requests":count})]}
}
