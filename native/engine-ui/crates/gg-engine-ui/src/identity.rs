//! Actual GG identity labels, without inferred original class/race policies.
use engine_ui_core::script::{PlayerRecord,UnitState};
use serde_json::Value;

fn pair(row:&Value)->Result<Option<(String,String)>,String>{
    if row.is_null(){return Ok(None);}
    let object=row.as_object().filter(|o|o.len()==3&&o.keys().all(|k|matches!(k.as_str(),"id"|"name"|"file")))
        .ok_or("character identity row invalid")?;
    let id=object["id"].as_str().filter(|s|!s.is_empty()&&s.len()<=64&&s.bytes().all(|b|b.is_ascii_lowercase()||b.is_ascii_digit()||matches!(b,b'_'|b'.'|b'-')))
        .ok_or("character identity id invalid")?;
    let name=object["name"].as_str().filter(|s|!s.is_empty()&&s.len()<=384&&!s.chars().any(char::is_control))
        .ok_or("character identity name invalid")?;
    let file=object["file"].as_str().filter(|s|!s.is_empty()&&s.len()<=64&&s.bytes().all(|b|b.is_ascii_uppercase()||b.is_ascii_digit()||b==b'_'))
        .ok_or("character identity token invalid")?;
    let expected=id.split_once('.').map_or(id,|(_,tail)|tail).replace('-',"_").to_ascii_uppercase();
    if file!=expected{return Err("character identity token mismatch".into());}
    Ok(Some((name.into(),file.into())))
}

pub(crate) fn apply(unit:&mut UnitState,record:&mut PlayerRecord,data:&Value)->Result<(),String>{
    if data.is_null(){return Ok(());}
    let object=data.as_object().filter(|o|o.len()==3&&o.keys().all(|k|matches!(k.as_str(),"schema"|"class"|"race")))
        .ok_or("character identity packet invalid")?;
    if object["schema"]!="gg.engine.character-identity.v1"{return Err("character identity schema invalid".into());}
    // Validate the complete packet before touching either retained view.
    let class=pair(&object["class"])?;let race=pair(&object["race"])?;
    unit.class=class.as_ref().map(|v|v.0.clone());unit.class_file=class.as_ref().map(|v|v.1.clone());
    unit.race=race.as_ref().map(|v|v.0.clone());unit.race_file=race.as_ref().map(|v|v.1.clone());
    record.class=class;record.race=race;
    Ok(())
}
