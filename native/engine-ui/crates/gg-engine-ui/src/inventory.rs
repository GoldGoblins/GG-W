//! Exact source coordinates remain frozen by the Python presentation adapter.
use super::Host;
use serde_json::{Value,json};
pub(super) fn feed(h:&mut Host,v:&Value,target:&Value)->Result<(),String>{
    let armed=target["active"]==true;
    h.ui.set_item_pick_armed(armed);
    if armed || h.views.get("item_host_target").is_some_and(|v|v["active"]==true){h.ui.set_spell_targeting(armed);}
    h.views.insert("item_host_target".into(),target.clone());
    let wrap=&v["wrap"];
    if wrap.is_object(){
        let source=wrap["source"].as_array().filter(|s|s.len()==2).ok_or("wrap source required")?;
        let slot=source[1].as_u64().filter(|s|(1..=64).contains(s)).ok_or("wrap slot required")? as u32;
        if source[0]!=0{return Err("wrap backpack required".into());}
        if h.ui.gift_wrap_armed().is_none(){h.ui.arm_gift_wrap(0,slot);}
    }else if h.ui.gift_wrap_armed().is_some(){h.ui.clear_cursor_payload();}
    h.views.insert("gift_host_wrap".into(),wrap.clone());Ok(())
}
pub(super) fn requests(h:&mut Host)->Vec<Value>{
    let ui=&mut h.ui;
    let mut rows=Vec::new();
    let wraps=ui.take_container_wraps();
    if wraps.is_empty() && h.views.get("gift_host_wrap").is_some_and(|v|v.is_object()) && ui.gift_wrap_armed().is_none(){rows.push(json!({"op":"InventoryWrapCancel"}));}
    for (paper_bag,paper_slot,bag,slot) in wraps{rows.push(json!({"op":"InventoryWrap","paper_source":[paper_bag,paper_slot],"source":[bag,slot]}));}
    for (bag,slot) in ui.take_item_picks(){rows.push(json!({"op":"EnchantPick","source":[bag,slot]}));}
    for answer in ui.take_enchant_confirms(){rows.push(json!({"op":match answer{engine_ui_core::script::EnchantConfirm::Bind=>"EnchantBindConfirm",engine_ui_core::script::EnchantConfirm::Replace=>"EnchantReplaceConfirm"}}));}
    for a in ui.take_pending_equip_answers(){rows.push(json!({"op":"ItemBindingEquipAnswer","index":a.index,"accept":a.accept}));}
    for _ in 0..ui.take_bind_on_use_confirms(){rows.push(json!({"op":"ItemBindingUseConfirm"}));}
    for (bag,slot,count) in ui.take_container_destroys(){rows.push(json!({"op":"InventoryDestroy","source":[bag,slot],"count":count}));}
    for row in ui.take_bag_autostores(){rows.push(json!({"op":"InventoryAutoStore","source":[row.src_bag,row.src_slot],"destination":row.dst_bag,"count":row.count}));}
    for target in ui.take_drop_item_on_unit(){if let Some(item)=ui.cursor_item(){rows.push(json!({"op":"InventoryDropOnUnit","source":[item.bag,item.slot],"target":target}));}}
    rows
}
