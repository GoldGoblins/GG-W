//! Local GG ranks and spending through the unchanged original talent bindings.
use crate::Host;
use engine_ui_core::script::{ScriptValue,TalentUiState,TalentTabView,TalentView};
use serde_json::Value;

pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    let state=&v["talents"];
    if !state.is_object()||host.views.get("talents")==Some(state){return Ok(())}
    let uint=|v:&Value,key:&str|v[key].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or_else(||format!("invalid GG talent {key}"));
    let points=uint(state,"points")?;
    let rows=state["rows"].as_array().ok_or("GG talent rows required")?;
    if rows.len()>32{return Err("GG talent capacity exceeded".into())}
    let mut talents=Vec::new();let mut spent=0u32;
    for row in rows{
        let name=row["name"].as_str().ok_or("GG talent name required")?;
        if name.len()>512{return Err("GG talent name capacity exceeded".into())}
        let rank=uint(row,"rank")?;let max_rank=uint(row,"max_rank")?;
        let tier=uint(row,"tier")?;let column=uint(row,"column")?;
        if rank>max_rank||!(1..=8).contains(&tier)||!(1..=4).contains(&column){return Err("invalid GG talent layout/rank".into())}
        spent=spent.checked_add(rank).ok_or("GG talent points overflow")?;
        talents.push(TalentView{name:name.into(),tier,column,rank,max_rank,meets_prereq:true,
            learnable:points>0&&rank<max_rank&&row["learnable"]==true,..Default::default()});
    }
    let old_points=host.views.get("talents").and_then(|v|v["points"].as_u64());
    host.ui.set_talents(TalentUiState{tabs:vec![TalentTabView{name:"GG Talents".into(),points_spent:spent,..Default::default()}],
        talents:vec![talents],points:(points,0)});
    host.views.insert("talents".into(),state.clone());
    let delta=old_points.map(|old|i64::from(points)-old as i64).unwrap_or(0);
    host.ui.fire_event("CHARACTER_POINTS_CHANGED",vec![ScriptValue::Int(delta),ScriptValue::Int(0)]);
    Ok(())
}
