//! Cast/stance feed from the local authoritative GG simulation.
use engine_ui_core::script::{ScriptValue,ShapeshiftFormView};
use serde_json::{Value,json};
use crate::Host;

pub(crate) fn feed(host:&mut Host,v:&Value,clock:f64)->Result<(),String>{
    let state=&v["client_controls"]["spells"];
    if state.is_null(){return Ok(());}
    let epoch=state["epoch"].as_u64().ok_or("spell epoch required")?;
    let rows=state["forms"].as_array().ok_or("spell forms required")?;
    if rows.len()>32{return Err("spell form capacity exceeded".into());}
    let mut forms=Vec::new();
    for row in rows{
        let reference=row["ref"].as_str().ok_or("form reference required")?;
        let spell=v["spells"].as_array().and_then(|rows|rows.iter().find(|r|r["ref"].as_str()==Some(reference)))
            .ok_or("form missing from spellbook")?;
        let id=spell["spell_id"].as_u64().filter(|id|*id<=u32::MAX as u64).ok_or("form spell id required")? as u32;
        let name=row["name"].as_str().filter(|s|!s.is_empty()&&s.len()<=384).ok_or("form name required")?;
        let remaining=row["cooldown_s"].as_f64().filter(|n|n.is_finite()&&*n>=0.&&*n<=300.).ok_or("form cooldown required")?;
        let duration=row["cooldown_duration_s"].as_f64().filter(|n|n.is_finite()&&*n>=remaining&&*n<=300.).ok_or("form duration required")?;
        forms.push(ShapeshiftFormView{spell_id:id,name:name.into(),active:row["active"]==true,
            castable:row["castable"]==true,texture:spell["texture"].as_str().map(str::to_owned),
            cooldown:if remaining>0.{Some((((clock+remaining-duration)*1000.).max(0.) as i64,(duration*1000.) as u32,true))}else{None}});
    }
    let events=state["events"].as_array().filter(|e|e.len()<=32).ok_or("spell event capacity exceeded")?;
    let old=host.views.get("spell_events");
    let fresh=old.is_none()||old.is_some_and(|s|s["epoch"].as_u64()!=Some(epoch));
    let last=old.filter(|s|s["epoch"].as_u64()==Some(epoch)).and_then(|s|s["id"].as_u64()).unwrap_or(0);
    let mut next=last;let mut edges=Vec::new();
    for event in events{
        let id=event["id"].as_u64().ok_or("spell event id required")?;
        let name=event["event"].as_str().ok_or("spell event name required")?;
        if !matches!(name,"SPELLCAST_START"|"SPELLCAST_STOP"|"SPELLCAST_FAILED"|"SPELLCAST_INTERRUPTED"|
            "SPELLCAST_DELAYED"|"SPELLCAST_CHANNEL_START"|"SPELLCAST_CHANNEL_UPDATE"|"SPELLCAST_CHANNEL_STOP"|
            "UPDATE_SHAPESHIFT_FORM"|"MIRROR_TIMER_START"|"MIRROR_TIMER_STOP"){return Err("unknown spell lifecycle event".into());}
        let arity=match name{"SPELLCAST_START"|"SPELLCAST_CHANNEL_START"=>2,
            "SPELLCAST_DELAYED"|"SPELLCAST_CHANNEL_UPDATE"|"MIRROR_TIMER_STOP"=>1,
            "MIRROR_TIMER_START"=>6,_=>0};
        let args=event["args"].as_array().filter(|a|a.len()==arity).ok_or("spell event arguments invalid")?;
        let mut values=Vec::new();
        for arg in args{
            if let Some(s)=arg.as_str().filter(|s|s.len()<=384){values.push(ScriptValue::Str(s.into()));}
            else if let Some(i)=arg.as_i64().filter(|i|*i>=-1&&*i<=60000){values.push(ScriptValue::Int(i));}
            else{return Err("spell event argument invalid".into());}
        }
        if id>last{
            if !fresh{edges.push((name.to_owned(),values));}
            next=next.max(id);
        }
    }
    if fresh && old.is_some(){
        edges.push(("SPELLCAST_STOP".into(),vec![]));
        edges.push(("SPELLCAST_CHANNEL_STOP".into(),vec![]));
        edges.push(("MIRROR_TIMER_STOP".into(),vec![ScriptValue::Str("BREATH".into())]));
        edges.push(("MIRROR_TIMER_STOP".into(),vec![ScriptValue::Str("EXHAUSTION".into())]));
    }
    if fresh && state["casting"]==true{
        let pending=&state["pending"];
        let remaining=pending["remaining_s"].as_f64().filter(|n|n.is_finite()&&*n>=0.&&*n<=60.).ok_or("cast remaining invalid")?;
        let name=pending["name"].as_str().filter(|s|s.len()<=384).ok_or("cast name invalid")?;
        let duration=ScriptValue::Int((remaining*1000.).round() as i64);
        if pending["channel"]==true{edges.push(("SPELLCAST_CHANNEL_START".into(),vec![duration,ScriptValue::Str(name.into())]));}
        else{edges.push(("SPELLCAST_START".into(),vec![ScriptValue::Str(name.into()),duration]));}
    }
    if let Some(timers)=v["client_controls"]["survival"]["mirror_timers"].as_array(){
        if timers.len()>2{return Err("mirror timer capacity exceeded".into());}
        let mut seen=std::collections::HashSet::new();
        for timer in timers{
            let kind=timer["kind"].as_str().filter(|s|matches!(*s,"BREATH"|"EXHAUSTION"))
                .ok_or("mirror timer kind invalid")?;
            if !seen.insert(kind){return Err("duplicate mirror timer".into());}
            let remaining=timer["remaining_ms"].as_i64().filter(|n|*n>=0&&*n<=60000).ok_or("mirror timer remaining invalid")?;
            let maximum=timer["max_ms"].as_i64().filter(|n|*n>=remaining&&*n>0&&*n<=60000).ok_or("mirror timer maximum invalid")?;
            let scale=timer["scale"].as_i64().filter(|n|matches!(*n,-1|10)).ok_or("mirror timer scale invalid")?;
            let label=timer["label"].as_str().filter(|s|s.len()<=384).ok_or("mirror timer label invalid")?;
            if fresh{edges.push(("MIRROR_TIMER_START".into(),vec![ScriptValue::Str(kind.into()),ScriptValue::Int(remaining),
                ScriptValue::Int(maximum),ScriptValue::Int(scale),ScriptValue::Int(0),ScriptValue::Str(label.into())]));}
        }
    }else if fresh && v["client_controls"]["survival"]["submerged"]==true{
        let remaining=v["client_controls"]["survival"]["breath_s"].as_f64().filter(|n|n.is_finite()&&*n>=0.&&*n<=60.).ok_or("breath remaining invalid")?;
        edges.push(("MIRROR_TIMER_START".into(),vec![ScriptValue::Str("BREATH".into()),ScriptValue::Int((remaining*1000.).round() as i64),
            ScriptValue::Int(60000),ScriptValue::Int(-1),ScriptValue::Int(0),ScriptValue::Str("Breath".into())]));
    }
    let forms_changed=host.views.get("spell_forms")!=Some(&state["forms"]);
    let target_guids=state["target_guids"].as_array().filter(|r|r.len()<=65).ok_or("spell targets invalid")?;
    let guids=target_guids.iter().map(|v|v.as_u64().ok_or("spell target guid invalid")).collect::<Result<Vec<_>,_>>()?;
    host.ui.set_shapeshift_forms(forms);
    host.ui.set_spell_targetable_units(guids);
    // Original spell and item cursors share spell_targeting; preserve an armed enchant cursor.
    host.ui.set_spell_targeting(state["targeting"]==true || v["services"]["item_targeting"]["active"]==true);
    host.ui.set_casting(state["casting"]==true || v["services"]["travel"]["stuck_remaining"].as_f64().unwrap_or(0.)>0.
        ||(v["craft_book"]["open"]==true&&v["craft_book"]["repeat_count"].as_u64().unwrap_or(0)>0));
    host.views.insert("spell_forms".into(),state["forms"].clone());
    host.views.insert("spell_events".into(),json!({"epoch":epoch,"id":next}));
    if forms_changed{host.ui.fire_event("UPDATE_SHAPESHIFT_FORMS",vec![]);}
    for (name,args) in edges{host.ui.fire_event(&name,args);}
    Ok(())
}
