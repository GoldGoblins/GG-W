//! The original skill tree, over actual known GG professions.
use engine_ui_core::script::{SkillEntry,SkillsState,ScriptValue,UiScript};
use serde_json::{Value,json};
use super::Host;

pub(super) fn feed(h:&mut Host,v:&Value)->Result<(),String>{
    if !v.is_object() || h.views.get("gg_skills")==Some(v){return Ok(());}
    let rows=v["rows"].as_array().filter(|r|r.len()<=40).ok_or("skill capacity")?;
    let mut entries=Vec::new();let mut seen=std::collections::HashSet::new();
    for row in rows{
        let id=row["id"].as_u64().filter(|&n|n>0&&n<=u32::MAX as u64).ok_or("invalid skill id")? as u32;
        if !seen.insert(id){return Err("duplicate skill id".into());}
        let name=row["name"].as_str().filter(|s|!s.is_empty()&&s.len()<=256).ok_or("invalid skill name")?;
        let value=row["level"].as_u64().filter(|&n|(1..=100).contains(&n)).ok_or("invalid skill rank")? as u32;
        let max=row["max_level"].as_u64().filter(|&n|(value as u64..=100).contains(&n)).ok_or("invalid skill maximum")? as u32;
        entries.push(SkillEntry{skill_id:id,name:name.into(),value,max,mono:false,temp_bonus:0,perm_bonus:0,
            min_level:1,cost_index:0,category_id:11,category_name:"GG Professions".into(),category_order:1,
            description:"Local GG crafting profession. Unlearning loses its rank and experience.".into(),abandonable:row["abandonable"]==true});
    }
    h.ui.set_skills(SkillsState{entries});h.views.insert("gg_skills".into(),v.clone());
    h.ui.fire_event("SKILL_LINES_CHANGED",vec![ScriptValue::Int(0)]);Ok(())
}

pub(super) fn requests(ui:&mut UiScript)->Vec<Value>{
    ui.take_skill_abandons().into_iter().map(|skill_id|json!({"op":"SkillAbandon","skill_id":skill_id})).collect()
}
