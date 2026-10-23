//! GG host adapter for GgEngine's client-side macros. The unchanged UI owns edits.
//! Cast binding and line tokenization follow engine-app/src/ui_macro/run.rs (MIT).
use engine_ui_core::script::{MacroBinding, MacroState, MacroView, ScriptValue, UiScript,
    resolve_spell_by_name, MAX_MACROS, MAX_MACRO_NAME, MAX_MACRO_BODY};
use serde_json::{json, Value};
use std::collections::HashMap;

pub fn lines(body:&str)->impl Iterator<Item=&str>{
    body.split(['\r','\n']).map(str::trim).filter(|line|!line.is_empty())
}
fn aliases(ui:&UiScript,key:&str,defaults:&[&str])->Vec<String>{
    let mut out=Vec::new();
    for index in 1..=64{
        let name=format!("SLASH_{key}{index}");
        if let Ok(value)=ui.lua().globals().get::<String>(name.as_str()){
            out.push(value.trim_start_matches('/').to_ascii_lowercase());
        }else{break;}
    }
    if out.is_empty(){out.extend(defaults.iter().map(|s|s.to_string()));}out
}
pub fn bindings(ui:&UiScript)->HashMap<u32,MacroBinding>{
    let aliases=aliases(ui,"CAST",&["cast","spell"]);let book=ui.spellbook();
    let state=ui.macros();let mut out=HashMap::new();
    for id in 1..=36{
        let Some(row)=state.get(id)else{continue;};
        let mut found=None;
        for line in lines(&row.body){
            if let Some(rest)=line.strip_prefix('/'){
                let (cmd,args)=rest.split_once(' ').unwrap_or((rest,""));
                if aliases.iter().any(|a|a.eq_ignore_ascii_case(cmd))&&!args.trim().is_empty(){
                    found=Some((args.trim().to_string(),true));break;
                }
            }
            if let Some(at)=line.find("CastSpellByName("){
                if let Some(rest)=line[at+16..].trim_start().strip_prefix('"'){
                    if let Some(end)=rest.find('"'){
                        if end>0{found=Some((rest[..end].to_string(),false));break;}
                    }
                }
            }
        }
        let spell=found.map(|(name,slash)|resolve_spell_by_name(&book,&name)
            .map(|s|s.spell_id as i32).unwrap_or(if slash{-1}else{0})).unwrap_or(0);
        out.insert(id as u32,MacroBinding{spell,pet_book:false});
    }out
}
pub fn rows(ui:&mut UiScript,notify:bool)->Value{
    let bindings=bindings(ui);ui.set_macro_bindings(bindings.clone());
    if notify&&ui.take_macros_dirty(){ui.fire_event("UPDATE_MACROS",vec![]);}
    let state=ui.macros();let mut rows=Vec::new();
    for id in 1..=36{if let Some(row)=state.get(id){rows.push(json!({"index":id,
        "name":row.name,"texture":row.texture,"body":row.body,"local_only":row.local_only,
        "bound_spell":bindings.get(&(id as u32)).map(|b|b.spell).unwrap_or(0)}));}}
    json!({"generation":ui.macros_generation(),"rows":rows})
}
pub fn saved(ui:&UiScript)->Value{
    let state=ui.macros();let encode=|rows:Vec<MacroView>|rows.into_iter().map(|row|json!({
        "name":row.name,"texture":row.texture,"body":row.body,"local_only":row.local_only
    })).collect::<Vec<_>>();
    json!({"schema":"gg.engine.macros.v1","account":encode(state.account),"character":encode(state.character)})
}
pub fn load(ui:&mut UiScript,value:&Value)->Result<(),String>{
    if value["schema"]!="gg.engine.macros.v1"{return Err("unsupported macro save format".into());}
    let list=|key:&str|->Result<Vec<MacroView>,String>{
        let rows=value[key].as_array().ok_or("macro list required")?;
        if rows.len()>MAX_MACROS{return Err("macro tab capacity exceeded".into());}
        rows.iter().map(|row|{
            let name=row["name"].as_str().ok_or("macro name required")?;
            let body=row["body"].as_str().ok_or("macro body required")?;
            let texture=if row["texture"].is_null(){None}else{Some(row["texture"].as_str().ok_or("macro icon string required")?)};
            if name.chars().count()>MAX_MACRO_NAME||name.contains(['\r','\n','\0'])||body.chars().count()>MAX_MACRO_BODY||body.contains('\0')||texture.is_some_and(|t|t.len()>512||t.contains(['\r','\n','\0'])){
                return Err("invalid saved macro".into());
            }
            Ok(MacroView{name:name.into(),texture:texture.map(str::to_owned),body:body.into(),local_only:row["local_only"].as_bool().ok_or("macro local flag required")?})
        }).collect()
    };
    let state=MacroState{account:list("account")?,character:list("character")?};
    ui.set_macros(state);ui.set_macro_bindings(bindings(ui));Ok(())
}
/// Broadcast exactly the original event. A mounted stock ChatFrame consumes it.
/// GG's smaller UI needs the same slash dispatch without a fabricated ChatFrame.
pub fn line(ui:&mut UiScript,line:&str)->Result<Option<String>,String>{
    if line.chars().count()>MAX_MACRO_BODY{return Err("macro line capacity exceeded".into());}
    ui.fire_event("EXECUTE_CHAT_LINE",vec![ScriptValue::Str(line.into())]);
    let globals=ui.lua().globals();
    if globals.get::<mlua::Value>("ChatFrame1").is_ok_and(|v|!matches!(v,mlua::Value::Nil)){return Ok(None);}
    let Some(rest)=line.strip_prefix('/')else{return Ok(Some(line.into()));};
    let (cmd,args)=rest.split_once(' ').unwrap_or((rest,""));
    if let Ok(table)=globals.get::<mlua::Table>("SlashCmdList"){
        for pair in table.pairs::<String,mlua::Value>().take(4096){
            let (key,value)=pair.map_err(|e|e.to_string())?;
            if let mlua::Value::Function(call)=value{
                if aliases(ui,&key,&[]).iter().any(|a|a.eq_ignore_ascii_case(cmd)){
                    call.call::<()>(args).map_err(|e|e.to_string())?;return Ok(None);
                }
            }
        }
    }
    if aliases(ui,"CAST",&["cast","spell"]).iter().any(|a|a.eq_ignore_ascii_case(cmd)){
        let call:mlua::Function=globals.get("CastSpellByName").map_err(|e|e.to_string())?;
        if !args.is_empty(){call.call::<()>(args).map_err(|e|e.to_string())?;}return Ok(None);
    }
    if aliases(ui,"SCRIPT",&["script","run"]).iter().any(|a|a.eq_ignore_ascii_case(cmd)){
        ui.run_chunk_named(args.as_bytes(),"Macro/script").map_err(|e|e.to_string())?;return Ok(None);
    }
    Ok(Some(line.into()))
}
