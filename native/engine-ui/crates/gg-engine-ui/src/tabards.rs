//! TabardModel keeps the original five fields; payment and cloth live in GG.
use super::Host;
use engine_ui_core::script::{TabardHost,TabardIntent};
use serde_json::{Value,json};

pub(super) fn feed(h:&mut Host,v:&Value)->Result<(),String>{
    let record=if v["in_guild"]==true{
        if v["emblem"].is_null(){Some([-1;5])}else{Some(serde_json::from_value::<[i32;5]>(v["emblem"].clone()).map_err(|_|"invalid guild emblem")?)}
    }else{None};
    h.ui.set_tabard_host(TabardHost{guild_record:record,save_pending:false});
    let old=h.views.get("tabard").cloned().unwrap_or(Value::Null);
    if (old["open"]==true)!=(v["open"]==true){
        h.ui.fire_event(if v["open"]==true{"OPEN_TABARD_FRAME"}else{"CLOSE_TABARD_FRAME"},vec![]);
    }
    h.views.insert("tabard".into(),v.clone());Ok(())
}

pub(super) fn requests(h:&mut Host)->Vec<Value>{
    let mut rows=h.ui.take_tabard_intents().into_iter().map(|r|match r{
        TabardIntent::Save(design)=>json!({"op":"TabardSave","design":design}),TabardIntent::Close=>json!({"op":"TabardClose"})
    }).collect::<Vec<_>>();
    if h.views.get("tabard").is_some_and(|v|v["open"]==true){
        if let Some(design)=h.ui.tabard_design(){let value=json!(design);
            if h.views.get("native_tabard_preview")!=Some(&value){h.views.insert("native_tabard_preview".into(),value);rows.insert(0,json!({"op":"TabardPreview","design":design}));}
        }
    }else{h.views.remove("native_tabard_preview");}
    rows
}
