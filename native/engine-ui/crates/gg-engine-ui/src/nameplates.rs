//! Original pooled plate widgets, seated by the actual Qt world camera.
use engine_ui_core::script::{PlateGeometry,PlateState,UnitState};
use serde_json::{Value,json};
use super::Host;

fn bits(h:&Host)->u8{h.views.get("plate_bits").and_then(Value::as_u64).unwrap_or(0) as u8}
fn apply(h:&mut Host){let writes=h.ui.take_nameplate_bit_writes();let value=writes.apply(bits(h));h.views.insert("plate_bits".into(),json!(value));if value==0{h.ui.retire_nameplates();}}

pub(super) fn feed(h:&mut Host,v:&Value)->Result<(),String>{
    let rows=v["services"]["people"].as_array().cloned().unwrap_or_default();
    if rows.len()>64{return Err("nameplate subject capacity".into());}
    let group=v["services"]["group"]["members"].as_array().cloned().unwrap_or_default();
    let mut subjects=Vec::new();
    for row in rows{
        if row["online"]!=true||row["health"].as_f64().unwrap_or(0.)<=0.||row["distance_sq"].as_f64().unwrap_or(f64::MAX)>400.{continue;}
        let guid=row["guid"].as_u64().filter(|g|*g>1).ok_or("invalid nameplate guid")?;
        let mut row=row;row["friend"]=json!(group.iter().any(|id|*id==row["id"]));
        row["selected"]=json!(row["id"]==v["target"]["id"]);
        row["mark"]=v["services"]["group"]["mark_guids"][guid.to_string()].clone();
        subjects.push(row);
    }
    h.views.insert("plate_subjects".into(),json!(subjects));
    h.views.insert("plate_active".into(),json!(v["health"].as_f64().unwrap_or(0.)>0.));
    if h.views["plate_active"]!=true{h.ui.retire_nameplates();}
    Ok(())
}

pub(super) fn project(h:&mut Host,v:&Value)->Result<Value,String>{
    apply(h);
    let rows=v["rows"].as_array().filter(|r|r.len()<=64).ok_or("nameplate projection capacity")?;
    let mode=bits(h);let subjects=h.views.get("plate_subjects").and_then(Value::as_array).cloned().unwrap_or_default();
    let seam:f32=h.ui.eval("return WorldFrame and WorldFrame:GetEffectiveScale() or 1").map_err(|e|e.to_string())?;
    if !seam.is_finite()||seam<=0.||seam>100.{return Err("invalid plate scale".into());}
    let mut states=Vec::new();let mut seen=std::collections::HashSet::new();
    if h.views.get("plate_active")==Some(&json!(true))&&h.ui.frame_visible("WorldFrame"){
        for row in rows{
            let key=row["guid"].as_u64().ok_or("plate guid required")?;
            if !seen.insert(key){return Err("duplicate plate projection".into());}
            let Some(subject)=subjects.iter().find(|s|s["guid"].as_u64()==Some(key)) else{continue;};
            let friendly=subject["friend"]==true;if mode & (if friendly{8}else{1})==0{continue;}
            let x=row["x"].as_f64().ok_or("plate x required")?;let y=row["y"].as_f64().ok_or("plate y required")?;
            if !x.is_finite()||!y.is_finite(){return Err("invalid plate coordinates".into());}
            if x<0.||y<0.||x>h.width as f64||y>h.height as f64{continue;}
            let mark=subject["mark"].as_u64().unwrap_or(0).min(8) as u8;
            let selected=subject["selected"]==true;let hovered=h.ui.hovered_nameplate()==Some(key);
            states.push(PlateState{key,top_centre:(x as f32/seam,(h.height-y as f32)/seam),
                health:subject["health"].as_f64().unwrap_or(0.).max(0.) as f32,max_health:subject["max_health"].as_f64().unwrap_or(1.).max(1.) as f32,
                name:subject["name"].as_str().unwrap_or("").into(),level:subject["level"].as_u64().map(|n|n.min(u32::MAX as u64) as u32),skull:false,
                bar_colour:if friendly{[0.,1.,0.]}else{[1.,0.,0.]},level_colour:[1.,0.82,0.],raid_icon:if mark>0{Some(mark-1)}else{None},
                alpha:if selected{1.}else{178./255.},lit:selected||hovered,hovered});
        }
    }
    let diagonal=h.width.hypot(h.height);let basis=if diagonal<=1280.{diagonal}else{1280.+(diagonal-1280.)*0.5};
    let gx=|n:f32|(n*basis).round()/seam;let text=|n:f32|(n*basis).round().min(32.)/seam;
    h.ui.set_nameplate_mouse(v["freelook"]!=true);h.ui.set_nameplate_hit_test_veto(v["targeting"]==true);
    h.ui.sync_nameplates(PlateGeometry{width:gx(0.1),height:gx(0.025),bar_off_x:gx(0.0031),bar_off_y:gx(0.003125),bar_width:gx(0.0804),bar_height:gx(0.007025),
        level_off_x:gx(0.0092),level_off_y:gx(0.0071),skull_size:gx(0.01),raid_size:gx(0.02),name_height:text(0.01),level_height:text(0.0086),shadow_offset:1./seam},&states);
    // A new pool member inherits mouse input after its creation too.
    h.ui.set_nameplate_mouse(v["freelook"]!=true);
    hover(h);
    Ok(json!({"shown":states.len(),"pooled":h.ui.nameplate_pool_len(),"bits":mode}))
}

pub(super) fn hover(h:&mut Host){
    let subjects=h.views.get("plate_subjects").and_then(Value::as_array).cloned().unwrap_or_default();
    let hovered=h.ui.hovered_nameplate().and_then(|key|subjects.iter().find(|s|s["guid"].as_u64()==Some(key)));
    let unit=hovered.map(|s|UnitState{exists:true,has_object:true,name:s["name"].as_str().map(str::to_owned),guid:s["guid"].as_u64().unwrap_or(0),
        health:s["health"].as_f64().unwrap_or(0.) as u32,max_health:s["max_health"].as_f64().unwrap_or(1.).max(1.) as u32,
        level:s["level"].as_u64().unwrap_or(1) as u32,can_attack:s["friend"]!=true,reaction:if s["friend"]==true{5}else{2},..Default::default()});
    let old=h.unit_guids.mouseover;
    h.unit_guids.mouseover=unit.as_ref().map(|u|u.guid).filter(|guid|h.unit_guids.held.contains_key(guid)).unwrap_or(0);
    h.ui.set_unit_guids(&h.unit_guids);
    h.ui.set_unit("mouseover",unit);
    if old!=h.unit_guids.mouseover{h.ui.fire_event("UPDATE_MOUSEOVER_UNIT",vec![]);}
}

pub(super) fn requests(h:&mut Host)->Value{
    apply(h);let mut clicks=Vec::new();
    hover(h);
    for click in h.ui.take_nameplate_clicks(){
        if let Some(row)=h.views.get("plate_subjects").and_then(Value::as_array).and_then(|rows|rows.iter().find(|r|r["guid"].as_u64()==Some(click.key))){
            clicks.push(json!({"id":row["id"],"button":click.button}));
        }
    }
    json!({"bits":bits(h),"clicks":clicks})
}
