//! Bounded GG control packet for the retained Lua view, without private state.
use engine_ui_core::script::UiScript;
use serde_json::{Value,json};

fn value(lua:&mlua::Lua,v:&Value,depth:usize,budget:&mut usize)->Result<mlua::Value,String>{
    if depth>6||*budget==0{return Err("GG control snapshot capacity exceeded".into());}
    *budget-=1;
    let error=|e:mlua::Error|e.to_string();
    Ok(match v{
        Value::Null=>mlua::Value::Nil,
        Value::Bool(b)=>mlua::Value::Boolean(*b),
        Value::Number(n)=>mlua::Value::Number(n.as_f64().filter(|n|n.is_finite()).ok_or("GG snapshot number invalid")?),
        Value::String(s)=>{
            if s.len()>384{return Err("GG control snapshot string too long".into());}
            mlua::Value::String(lua.create_string(s).map_err(error)?)
        },
        Value::Array(rows)=>{
            let table=lua.create_table().map_err(error)?;
            for (i,row) in rows.iter().enumerate(){table.raw_set(i+1,value(lua,row,depth+1,budget)?).map_err(error)?;}
            mlua::Value::Table(table)
        },
        Value::Object(rows)=>{
            let table=lua.create_table().map_err(error)?;
            for (k,row) in rows{
                if k.len()>64{return Err("GG control snapshot key too long".into());}
                table.raw_set(k.as_str(),value(lua,row,depth+1,budget)?).map_err(error)?;
            }
            mlua::Value::Table(table)
        },
    })
}

pub(crate) fn publish(ui:&UiScript,v:&Value)->Result<(),String>{
    let lua=ui.lua();let table=lua.create_table().map_err(|e|e.to_string())?;
    for (key,row) in v.as_object().ok_or("snapshot object required")?{
        if matches!(row,Value::String(_)|Value::Bool(_)|Value::Number(_)){
            let item=match row{
                Value::String(s)=>mlua::Value::String(lua.create_string(s).map_err(|e|e.to_string())?),
                Value::Bool(b)=>mlua::Value::Boolean(*b),
                Value::Number(n)=>mlua::Value::Number(n.as_f64().filter(|n|n.is_finite()).ok_or("snapshot number invalid")?),
                _=>unreachable!(),
            };
            table.raw_set(key.as_str(),item).map_err(|e|e.to_string())?;
        }
    }
    let s=&v["client_controls"]["spells"];let survival=&v["client_controls"]["survival"];
    // The view needs current public control values, not journals, target GUIDs,
    // service ledgers, passwords, registry keys or persistence records.
    let controls=json!({"spells":{"pending":s["pending"],"casting":s["casting"]},
        "survival":{"submerged":survival["submerged"],"breath_s":survival["breath_s"],"max_breath_s":survival["max_breath_s"]}});
    table.raw_set("client_controls",value(lua,&controls,0,&mut 128)?).map_err(|e|e.to_string())?;
    lua.globals().set("GGSnapshot",table).map_err(|e|e.to_string())
}
