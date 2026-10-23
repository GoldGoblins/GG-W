//! Durable original chat records and placed-frame anchors, scoped by the GG host.
use engine_ui_core::script::{UiScript,ChatWindowLook,FrameLayout,LayoutPoint};
use serde_json::{Value,json};

pub fn state(ui:&UiScript)->Value{
    json!({"schema":"gg.engine.ui-cache.v1",
        "colors":ui.chat_colors().iter().map(|r|json!({"name":r.name,"rgb":r.rgb})).collect::<Vec<_>>(),
        "windows":ui.chat_window_looks().iter().map(|r|json!({"rgba":[r.r,r.g,r.b,r.a],"font_size":r.font_size,
            "locked":r.locked,"docked":r.docked,"name":r.name,"shown":r.shown,"messages":r.messages,"channels":r.channels})).collect::<Vec<_>>(),
        "frames":ui.user_placed_layouts().iter().map(|r|json!({"name":r.name,"width":r.width,"height":r.height,
            "points":r.points.iter().map(|p|json!({"point":p.point,"relative_to":p.relative_to,"relative_point":p.relative_point,"x":p.x,"y":p.y})).collect::<Vec<_>>()})).collect::<Vec<_>>()})
}
fn name(v:&Value,cap:usize)->Result<String,String>{
    let s=v.as_str().ok_or("UI cache string required")?;
    if s.len()>cap||s.chars().any(|c|c.is_control()){return Err("UI cache string capacity".into());}Ok(s.into())
}
fn number(v:&Value,cap:f64)->Result<f32,String>{
    let n=v.as_f64().filter(|n|n.is_finite()&&n.abs()<=cap).ok_or("invalid UI cache geometry")?;Ok(n as f32)
}
fn flag(v:&Value)->Result<bool,String>{v.as_bool().ok_or("UI cache boolean required".into())}
pub fn load(ui:&mut UiScript,v:&Value)->Result<(),String>{
    if v["schema"]!="gg.engine.ui-cache.v1"{return Err("invalid UI cache schema".into());}
    let colors=v["colors"].as_array().filter(|a|a.len()<=104).ok_or("UI color capacity")?;
    let window_count=ui.chat_window_looks().len();
    let windows=v["windows"].as_array().filter(|a|a.len()==window_count).ok_or("UI window count")?;
    let frames=v["frames"].as_array().filter(|a|a.len()<=256).ok_or("UI layout capacity")?;
    // Validate the whole file before touching any live frame or chat record.
    let mut cs=Vec::new();let mut ws=Vec::new();let mut fs=Vec::new();
    for r in colors{cs.push((name(&r["name"],64)?,serde_json::from_value::<[u8;3]>(r["rgb"].clone()).map_err(|_|"UI cache RGB required")?));}
    for (i,r) in windows.iter().enumerate(){
        let [red,green,blue,alpha]=serde_json::from_value::<[u8;4]>(r["rgba"].clone()).map_err(|_|"UI cache RGBA required")?;
        let size=r["font_size"].as_i64().filter(|n|(0..=32768).contains(n)).ok_or("invalid UI font size")? as i32;
        let docked=if r["docked"].is_null(){None}else{Some(r["docked"].as_u64().filter(|&n|(1..=10).contains(&n)).ok_or("invalid UI dock")? as u8)};
        let messages=r["messages"].as_array().filter(|a|a.len()<=68).ok_or("UI message capacity")?.iter().map(|s|name(s,64)).collect::<Result<Vec<_>,_>>()?;
        let channels=r["channels"].as_array().filter(|a|a.len()<=10).ok_or("UI channel capacity")?.iter().map(|c|{
            if c.as_array().is_none_or(|c|c.len()!=2){return Err("invalid UI channel".into());}
            Ok((name(&c[0],512)?,c[1].as_u64().filter(|&n|n<=u32::MAX as u64).ok_or("invalid UI channel id")? as u32))
        }).collect::<Result<Vec<_>,String>>()?;
        ws.push((i,ChatWindowLook{r:red,g:green,b:blue,a:alpha,font_size:size,locked:flag(&r["locked"])?,docked,name:name(&r["name"],512)?,shown:flag(&r["shown"])?,messages,channels}));
    }
    for r in frames{
        let points=r["points"].as_array().filter(|a|a.len()<=16).ok_or("UI anchor capacity")?.iter().map(|p|Ok(LayoutPoint{
            point:name(&p["point"],32)?,relative_to:if p["relative_to"].is_null(){None}else{Some(name(&p["relative_to"],128)?)},relative_point:name(&p["relative_point"],32)?,x:number(&p["x"],1e6)?,y:number(&p["y"],1e6)?
        })).collect::<Result<Vec<_>,String>>()?;
        fs.push(FrameLayout{name:name(&r["name"],128)?,width:number(&r["width"],16384.)?,height:number(&r["height"],16384.)?,points});
    }
    ui.set_chat_colors(cs);ui.set_chat_window_looks(ws);ui.restore_user_placed_layouts(fs);Ok(())
}
pub fn requests(ui:&mut UiScript)->Option<Value>{
    let colors=ui.take_chat_color_changes();let windows=ui.take_chat_window_changes();let layout=ui.take_user_placed_change();
    (colors||!windows.is_empty()||layout).then(||state(ui))
}
