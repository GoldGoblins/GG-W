//! Ordered original dressing-room verbs over GG's ephemeral character look.
use super::Host;
use engine_ui_core::script::DressUpIntent;
use serde_json::{json,Value};
pub(super) fn requests(h:&mut Host)->Vec<Value>{
    let mut rows=Vec::new();
    for intent in h.ui.take_dressup_intents(){rows.push(match intent{
        DressUpIntent::Dress=>json!({"op":"DressupDress"}),
        DressUpIntent::Undress=>json!({"op":"DressupUndress"}),
        DressUpIntent::TryOn(id)=>json!({"op":"DressupTryOn","id":id}),
        DressUpIntent::Close=>json!({"op":"DressupClose"}),
    });}
    let opening=rows.iter().any(|r|matches!(r["op"].as_str(),Some("DressupDress"|"DressupUndress"|"DressupTryOn")));
    if (opening || h.views.get("dressup").is_some_and(|v|v["open"]==true)) && h.ui.eval::<bool>("return DressUpModel ~= nil").unwrap_or(false){
        let angle=h.ui.model_pane_facing("DressUpModel").to_degrees();
        if angle.is_finite() && h.views.get("dressup_angle")!=Some(&json!(angle)){
            rows.push(json!({"op":"DressupRotate","angle":angle}));h.views.insert("dressup_angle".into(),json!(angle));
        }
    }
    let shown=h.ui.frame_visible("DressUpFrame") || h.ui.frame_visible("AuctionDressUpFrame");
    if !shown && h.views.get("dressup_stock_visible")==Some(&json!(true)){rows.push(json!({"op":"DressupClose"}));}
    h.views.insert("dressup_stock_visible".into(),json!(shown));rows
}
