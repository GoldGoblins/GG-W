//! C ABI over GgEngine UI with two recorded local custody adaptations.
//! Runs inside GG's supervised Lua process; legacy UI drains stay compatible.
use engine_ui_core::{framexml, loader};
use engine_ui_core::script::{UiScript, ScriptValue, QuadContent, UnitState, PlayerRecord, AddOnInfo,
    SoundRequest, MusicRequest, widget_method_census, TextMeasure, MeasureRequest,EditBoxAdvanceRequest,EditAction,EditUnit,ActionSlot,ActionState,SelectionRequest,ScriptCall,ContainerState,ContainerSlot,ItemTemplateView,SpellBookState,SpellSlotView,SpellTabView,BankState,MerchantState,MerchantItem,RepairCosts};
use serde_json::{Value, json};
use std::{collections::BTreeMap, panic::{catch_unwind, AssertUnwindSafe}, slice};

const MAX_MESSAGE: usize = 16 * 1024 * 1024;
mod macros;
mod macro_store;
mod quests;
mod talents;
mod local_actions;
mod controls;
mod local_client;
mod identity;
mod snapshot;
mod combat_stats;
mod services;
mod social;
mod lifecycle;
mod channels;
mod inventory;
mod dressup;
mod inspection;
mod item_info;
mod travel;
mod client_tools;
mod nameplates;
mod skills;
mod petitions;
mod tabards;
mod ui_cache;
mod pending;
mod opening_cinematic;
mod battlefields;
mod instance_sessions;
mod spells;
mod world_map;
mod minimap_hover;
struct Host { ui: UiScript, response: Vec<u8>, width: f32, height: f32, measurer:Option<(MeasureCallback,*mut std::ffi::c_void)>, saved_dirs:[Option<std::path::PathBuf>;2], views:BTreeMap<String,Value>,world:std::rc::Rc<std::cell::RefCell<BTreeMap<String,Value>>>,host_model_facts:BTreeMap<String,(String,engine_ui_core::widget::ModelFileFacts,u64)>,visible_model_names:Vec<String>,appearances:std::rc::Rc<std::cell::RefCell<BTreeMap<String,Value>>>,unit_guids:engine_ui_core::script::UnitGuids,sale_cursors:Vec<Option<engine_ui_core::script::CursorItem>>,minimap_hover:minimap_hover::State }
type MeasureCallback = unsafe extern "C" fn(*mut std::ffi::c_void,*const u8,usize,*mut u8,usize)->usize;
struct Measurer { callback:MeasureCallback, user:*mut std::ffi::c_void }
impl TextMeasure for Measurer {
    fn measure(&mut self,r:&MeasureRequest)->(f32,f32,f32){
        let packet=serde_json::to_vec(&json!({"text":r.text,"font":r.font,"height":r.text_height.or(r.height).unwrap_or(12.),"scale":r.scale,"wrap_width":r.wrap_width,"outline":format!("{:?}",r.outline)})).unwrap_or_default();
        let mut out=[0u8;256];let n=unsafe{(self.callback)(self.user,packet.as_ptr(),packet.len(),out.as_mut_ptr(),out.len())};
        if n>0&&n<=out.len(){if let Ok(values)=serde_json::from_slice::<[f32;3]>(&out[..n]){return (values[0],values[1],values[2]);}}
        (0.,0.,0.)
    }
    fn editbox_advances(&mut self,r:&EditBoxAdvanceRequest)->Option<(Vec<f32>,Vec<usize>,f32)>{
        let packet=serde_json::to_vec(&json!({"kind":"editbox","text":r.text,"font":r.font,"height":r.height.unwrap_or(12.),"scale":r.scale,"wrap_width":r.wrap_width})).ok()?;
        let mut out=vec![0u8;262144];let n=unsafe{(self.callback)(self.user,packet.as_ptr(),packet.len(),out.as_mut_ptr(),out.len())};
        if n==0||n>out.len(){return None;}let values:Value=serde_json::from_slice(&out[..n]).ok()?;
        Some((serde_json::from_value(values["advances"].clone()).ok()?,serde_json::from_value(values["rows"].clone()).ok()?,values["line_height"].as_f64()? as f32))
    }
}
fn string<'a>(v: &'a Value, key: &str) -> Result<&'a str, String> {
    v[key].as_str().ok_or_else(|| format!("missing string: {key}"))
}
fn number(v: &Value, key: &str, default: f64) -> Result<f64, String> {
    let n = v[key].as_f64().unwrap_or(default);
    if !n.is_finite() || n.abs() > 1e9 { Err(format!("invalid number: {key}")) } else { Ok(n) }
}
fn lua_value(v: mlua::Value) -> Value {
    match v {
        mlua::Value::Nil => Value::Null, mlua::Value::Boolean(b) => json!(b),
        mlua::Value::Integer(i) => json!(i), mlua::Value::Number(n) => json!(n),
        mlua::Value::String(s) => json!(s.to_string_lossy()),
        _ => json!({"type": v.type_name()}),
    }
}
fn script_value(v: &Value) -> Result<ScriptValue, String> {
    Ok(match v {
        Value::Null => ScriptValue::Nil, Value::Bool(b) => ScriptValue::Bool(*b),
        Value::Number(n) => ScriptValue::Number(n.as_f64().ok_or("invalid event number")?),
        Value::String(s) if s.len() < 65536 => ScriptValue::Str(s.clone()),
        _ => return Err("event arguments must be scalar".into()),
    })
}
fn err(e: impl std::fmt::Display) -> String { e.to_string() }
// JSON strings are UTF-8; Lua source files retain their original bytes instead.
fn source_bytes(v:&Value)->Result<Vec<u8>,String>{
    let bytes=if let Some(s)=v.as_str(){s.as_bytes().to_vec()}else{
        let hex=v["hex"].as_str().ok_or("source bytes required")?;
        if hex.len()>2*1024*1024 || hex.len()%2!=0{return Err("source byte capacity exceeded".into());}
        hex.as_bytes().chunks_exact(2).map(|pair|{
            let digit=|b:u8|match b{b'0'..=b'9'=>Ok(b-b'0'),b'a'..=b'f'=>Ok(b-b'a'+10),b'A'..=b'F'=>Ok(b-b'A'+10),_=>Err("invalid source hex".to_owned())};
            Ok((digit(pair[0])?<<4)|digit(pair[1])?)
        }).collect::<Result<Vec<_>,String>>()?
    };
    if bytes.len()>1024*1024{return Err("source byte capacity exceeded".into());}
    if engine_ui_core::source::chunk(&bytes).iter().find(|b|!b.is_ascii_whitespace())==Some(&0x1b){return Err("text Lua required".into());}
    Ok(bytes)
}
fn source_map(v:&Value)->Result<BTreeMap<String,Vec<u8>>,String>{
    let mut out=BTreeMap::new();let mut total=0;
    for (name,value) in v.as_object().ok_or("files object required")?{
        let bytes=source_bytes(value)?;total+=bytes.len();
        if total>8*1024*1024 || out.len()>=2048{return Err("source tree capacity exceeded".into());}
        out.insert(name.replace('\\',"/").to_ascii_lowercase(),bytes);
    }Ok(out)
}
impl Host {
    fn binding(&mut self,v:&Value,key:&str,up:bool)->Result<bool,String>{
        let arrow_without_alt=matches!(key,"LEFT"|"RIGHT"|"UP"|"DOWN") && self.ui.editbox_alt_arrow_mode() && !v["alt"].as_bool().unwrap_or(false);
        if self.ui.has_keyboard_focus() && !arrow_without_alt{return Ok(false);}
        let mut chord=String::new();
        for (flag,prefix) in [("ctrl","CTRL-"),("alt","ALT-"),("shift","SHIFT-")]{if v[flag].as_bool().unwrap_or(false){chord.push_str(prefix);}}
        chord.push_str(key);
        let command=self.ui.binding_keys().into_iter().find(|(k,_)|k.eq_ignore_ascii_case(&chord)).map(|(_,command)|command);
        if let Some(command)=command{
            // A real key must enter the original hardware-binding gate.
            // Calling Lua RunBinding directly leaves movement silently gated.
            return self.ui.execute_binding(&command,!up).map_err(err);
        }Ok(false)
    }
    fn new() -> Result<Self, String> {
        let mut ui = UiScript::new().map_err(err)?;
        item_info::defaults(&mut ui)?;
        controls::install(&mut ui);
        local_client::install(&mut ui)?;
        ui.lua().set_memory_limit(64 * 1024 * 1024).map_err(err)?;
        ui.register_cvars([("MasterVolume","0.5"),("SoundVolume","1"),("MusicVolume","0.4"),("AmbienceVolume","0.6"),("MasterSoundEffects","1"),("EnableMusic","1"),("EnableAmbience","1"),("SoundReverb","1"),("SoundZoneMusicNoDelay","0"),("spellEffectLevel","2"),("ffx","1"),("ffxGlow","1"),("ffxDeath","1")]);
        let world=std::rc::Rc::new(std::cell::RefCell::new(BTreeMap::<String,Value>::new()));let state=world.clone();
        ui.lua().globals().set("GG_GetWorldState",ui.lua().create_function(move |lua,()|{
            let table=lua.create_table()?;
            for (key,value) in state.borrow().iter(){match value{
                Value::String(v)=>table.set(key.as_str(),v.as_str())?,Value::Bool(v)=>table.set(key.as_str(),*v)?,Value::Number(v)=>table.set(key.as_str(),v.as_f64().unwrap_or(0.))?,_=>{}}}
            Ok(table)
        }).map_err(err)?).map_err(err)?;
        let appearances=std::rc::Rc::new(std::cell::RefCell::new(BTreeMap::<String,Value>::new()));let state=appearances.clone();
        ui.lua().globals().set("GG_SetCharacterAppearance",ui.lua().create_function(move |_,(name,options):(String,Option<mlua::Table>)|{
            if name.is_empty()||name.len()>128{return Err(mlua::Error::runtime("invalid model frame name"));}
            let mut state=state.borrow_mut();
            let Some(options)=options else{state.remove(&name);return Ok(());};
            if !state.contains_key(&name)&&state.len()>=8{return Err(mlua::Error::runtime("character model capacity exceeded"));}
            let mut character=serde_json::Map::new();
            for key in ["race","sex","skin","face","facial_hair","hair_style","hair_color","cloak","helmet","shoulders","mainhand","offhand","ranged","ammo","quiver","sheath","mainhand_sheath","offhand_sheath","mainhand_inv_type","offhand_inv_type","ranged_inv_type"]{
                if let Some(value)=options.get::<Option<u32>>(key)?{character.insert(key.into(),json!(value));}
            }
            if let Some(equipment)=options.get::<Option<mlua::Table>>("equipment")?{
                if equipment.raw_len()!=8{return Err(mlua::Error::runtime("character equipment requires eight display slots"));}
                let mut rows=Vec::new();for i in 1..=8{rows.push(equipment.get::<u32>(i)?);}character.insert("equipment".into(),json!(rows));
            }
            if let Some(shield)=options.get::<Option<bool>>("offhand_is_shield")?{character.insert("offhand_is_shield".into(),json!(shield));}
            for key in ["nocked","show_helm","show_cloak"]{if let Some(value)=options.get::<Option<bool>>(key)?{character.insert(key.into(),json!(value));}}
            if let Some(state)=options.get::<Option<mlua::Table>>("visual_sheath")?{
                if state.raw_len()!=2{return Err(mlua::Error::runtime("visual sheath requires two arms"));}
                character.insert("visual_sheath".into(),json!([state.get::<u8>(1)?,state.get::<u8>(2)?]));
            }
            if let Some(preview)=options.get::<Option<bool>>("tabard_preview")?{character.insert("tabard_preview".into(),json!(preview));}
            if let Some(emblem)=options.get::<Option<mlua::Table>>("emblem")?{
                let mut fields=serde_json::Map::new();for key in ["emblem_style","emblem_color","border_style","border_color","background_color"]{fields.insert(key.into(),json!(emblem.get::<i32>(key)?));}character.insert("emblem".into(),Value::Object(fields));
            }
            state.insert(name,json!({"character":character}));Ok(())
        }).map_err(err)?).map_err(err)?;
        let state=appearances.clone();
        ui.lua().globals().set("GG_SetCreatureDisplay",ui.lua().create_function(move |_,(name,display):(String,Option<u32>)|{
            if name.is_empty()||name.len()>128{return Err(mlua::Error::runtime("invalid model frame name"));}
            let mut state=state.borrow_mut();
            let Some(display)=display else{state.remove(&name);return Ok(());};
            if display==0{return Err(mlua::Error::runtime("invalid creature display id"));}
            if !state.contains_key(&name)&&state.len()>=8{return Err(mlua::Error::runtime("character model capacity exceeded"));}
            state.insert(name,json!({"display_id":display}));Ok(())
        }).map_err(err)?).map_err(err)?;
        ui.set_screen_size(1280., 720.);
        ui.run("if not UIParent then UIParent = CreateFrame('Frame','UIParent') UIParent:SetAllPoints() end").map_err(err)?;
        ui.resolve();
        Ok(Self { ui, response: Vec::new(), width: 1280., height: 720.,measurer:None,saved_dirs:[None,None],views:BTreeMap::new(),world,appearances,host_model_facts:BTreeMap::new(),visible_model_names:Vec::new(),unit_guids:Default::default(),sale_cursors:Vec::new(),minimap_hover:Default::default() })
    }
    fn draw(&mut self) -> Result<Value, String> {
        self.ui.resolve();
        if let (Some(request),Some((callback,user)))=(self.ui.editbox_advances_request(),self.measurer){
            let mut measurer=Measurer{callback,user};
            if let Some((cum,rows,h))=measurer.editbox_advances(&request){self.ui.set_editbox_advances(request.id,request.key,cum,rows,h);}
        }
        let quads = self.ui.extract();
        let model_panes=self.ui.visible_model_panes();
        if quads.len() > 32768 { return Err("UI draw capacity exceeded".into()); }
        let mut rows = Vec::with_capacity(quads.len());
        for q in quads {
            let Some(r) = q.rect else { continue; };
            let mut row = json!({"id": format!("{:?}",q.target), "owner": self.ui.target_owner_name(q.target),
                "x":r.left,"y":self.height-r.top,"width":r.width(),"height":r.height(),
                "alpha":q.alpha,"scale":q.scale,"z":q.z,
                "clip":q.clip.map(|c|[c.left,self.height-c.top,c.width(),c.height()])});
            match q.content {
                QuadContent::Frame => row["kind"] = json!("Frame"),
                QuadContent::Texture {path,color,additive,tex_coords,circular,portrait_unit,rotation,desaturated} => {
                    row["kind"]=json!("Texture"); row["path"]=json!(path);row["color"]=json!(color);
                    row["additive"]=json!(additive);row["circular"]=json!(circular);
                    row["portrait_unit"]=json!(portrait_unit);row["rotation"]=json!(rotation);
                    row["desaturated"]=json!(desaturated);
                    row["uv"]=json!(tex_coords.map(|t|match t {
                        engine_ui_core::script::TexCoords::Rect([l,r,t,b])=>[[l,t],[r,t],[r,b],[l,b]],
                        engine_ui_core::script::TexCoords::Corners(c)=>c}));
                },
                QuadContent::Backdrop {path,color,uvs,tile}=>{
                    row["kind"]=json!("Texture");row["path"]=json!(path);row["color"]=json!(color);
                    row["uv"]=json!(uvs);row["tile"]=json!(tile);
                },
                QuadContent::Text {text,color,justify_h,justify_v,font,font_height,text_height,shadow,outline,alpha_gradient,..}=>{
                    if text.as_ref().is_some_and(|t|t.len()>65536){return Err("UI text capacity exceeded".into());}
                    row["kind"]=json!("Text");row["text"]=json!(text);row["color"]=json!(color);
                    row["justify_h"]=json!(format!("{:?}",justify_h));row["justify_v"]=json!(format!("{:?}",justify_v));
                    row["font"]=json!(font);row["font_height"]=json!(text_height.or(font_height).unwrap_or(12.));
                    row["shadow"]=json!(shadow.map(|s|json!({"offset":s.offset,"color":s.color})));row["outline"]=json!(format!("{:?}",outline));
                    row["alpha_gradient"]=json!(alpha_gradient);
                },
                QuadContent::ColorWheel=>row["kind"]=json!("ColorWheel"),
                QuadContent::ColorValue {hue,sat}=>{row["kind"]=json!("ColorValue");row["hue"]=json!(hue);row["sat"]=json!(sat);},
                QuadContent::Minimap {zoom,inside_zoom}=>{row["kind"]=json!("Minimap");row["zoom"]=json!(zoom);row["inside_zoom"]=json!(inside_zoom);},
                QuadContent::ModelPane {handle,name,model,facing,model_scale,position,own_alpha,camera,icon,light,fog}=>{
                    row["kind"]=json!("ModelPane");row["name"]=json!(name);row["model"]=json!(model);
                    if let Some(appearance)=name.as_ref().and_then(|n|self.appearances.borrow().get(n).cloned()){row["appearance"]=appearance;}
                    row["facing"]=json!(facing);row["model_scale"]=json!(model_scale);row["position"]=json!(position);
                    row["own_alpha"]=json!(own_alpha);row["camera"]=json!(camera);
                    row["icon"]=json!(icon);row["light"]=json!({"enabled":light.enabled,"omni":light.omni,"vector":light.vector,"ambient":light.ambient,"diffuse":light.diffuse});
                    row["fog"]=json!(fog.map(|f|json!({"color":f.rgb(),"near":f.near,"far":f.far})));
                    if let Some(p)=model_panes.iter().find(|p|p.handle==handle){
                        row["clock_ms"]=json!(p.clock_ms);row["play"]=json!(p.play.map(|h|json!({"anim_id":h.anim_id,"cursor_ms":h.cursor_ms})));
                    }
                    if let Some(state)=row["name"].as_str().and_then(|n|self.ui.model_pane(n)){
                        row["host_model_source"]=json!(row["name"].as_str().and_then(|n|self.host_model_facts.get(n)).map(|(source,_,_)|source));
                        row["clock_ms"]=json!(state.clock_ms);
                        if let Some(armed)=state.armed{row["raw_cursor_ms"]=json!((state.clock_ms as i64-armed.anchor_ms).max(0) as u64);}
                        if row["play"].is_null(){if let Some((_,facts,seed))=row["name"].as_str().and_then(|n|self.host_model_facts.get(n)){
                            if let Some(h)=state.play_head(facts){row["play"]=json!({"anim_id":h.anim_id,"cursor_ms":h.cursor_ms});}
                            else if state.armed.is_none(){if let Some(anim)=facts.stand_id(){let cursor=state.clock_ms.saturating_sub(*seed);row["play"]=json!({"anim_id":anim,"cursor_ms":cursor});row["raw_cursor_ms"]=json!(cursor);}}
                        }}
                    }
                    row["unit"]=json!(row["name"].as_str().and_then(|n|self.ui.model_pane(n)).and_then(|m|m.unit));
                }
            }
            rows.push(row);
        }
        if let Some(caret)=self.ui.focused_editbox_text_ui(){
            let id=format!("{:?}",caret.target);
            if let Some(row)=rows.iter_mut().find(|r|r["id"].as_str()==Some(&id)){
                row["editbox"]=json!({"display_from":caret.display_from,"multi_line":caret.multi_line,"caret_x":caret.caret_x,"caret_row":caret.caret_row,"cell_h":caret.cell_h,"caret_on":caret.caret_on,"selection":caret.selection,"highlight_color":caret.highlight_color});
            }
        }
        self.visible_model_names=rows.iter().filter(|r|r["kind"]=="ModelPane").filter_map(|r|r["name"].as_str().map(str::to_owned)).collect();
        Ok(json!({"quads":rows,"errors":self.ui.take_errors(),"warnings":self.ui.take_warnings(),
            "memory_bytes":self.ui.lua().used_memory()}))
    }
    fn command(&mut self, v: Value) -> Result<Value, String> {
        self.ui.set_instruction_budget(10_000_000);
        match string(&v,"op")? {
            "ui_cache_load"=>{ui_cache::load(&mut self.ui,&v["state"])?;Ok(Value::Null)},
            "ui_cache"=>Ok(ui_cache::state(&self.ui)),
            "macros_load"=>{macros::load(&mut self.ui,&v["state"])?;Ok(Value::Null)},
            "macros_import"=>{
                let account=string(&v,"account")?;let character=string(&v,"character")?;
                if account.len()>65536||character.len()>65536{return Err("macro cache capacity exceeded".into());}
                let previous=self.ui.macros();
                self.ui.set_macros(engine_ui_core::script::MacroState{account:macro_store::parse(account),character:macro_store::parse(character)});
                // Apply the adapter's validation to the complete candidate table.
                let state=macros::saved(&self.ui);
                if let Err(error)=macros::load(&mut self.ui,&state){self.ui.set_macros(previous);return Err(error);}
                Ok(state)
            },
            "macro_files"=>{let state=self.ui.macros();Ok(json!({"account":macro_store::write(&state.account),"character":macro_store::write(&state.character)}))},
            "macros"=>Ok(macros::rows(&mut self.ui,true)),
            "macro_line"=>Ok(json!({"fallback":macros::line(&mut self.ui,string(&v,"line")?)?})),
            "macro_icons"=>{
                let icons:Vec<String>=serde_json::from_value(v["icons"].clone()).map_err(err)?;
                if icons.len()>4096||icons.iter().any(|s|s.len()>512){return Err("macro icon capacity exceeded".into());}
                self.ui.set_macro_icons(icons);Ok(Value::Null)
            },
            "exec"=>{self.ui.run_chunk_named(&source_bytes(&v["source"])?,v["name"].as_str().unwrap_or("GG")).map_err(err)?;Ok(Value::Null)},
            "toc"=>{
                let bytes=source_bytes(&v["source"])?;let toc=engine_ui_core::toc::Toc::parse(&engine_ui_core::source::decode(&bytes));
                Ok(json!({"directives":toc.directives,"files":toc.files,"interface":toc.interface_version(),"dependencies":toc.dependencies(),"optional_dependencies":toc.optional_dependencies(),"saved_variables":toc.list("SavedVariables"),"saved_variables_per_character":toc.list("SavedVariablesPerCharacter"),"load_on_demand":toc.load_on_demand(),"enabled":toc.default_state()}))
            },
            "xml_refs"=>{
                let bytes=source_bytes(&v["source"])?;let doc=framexml::parse(&engine_ui_core::source::decode(&bytes)).map_err(err)?;
                let base=v["path"].as_str().and_then(|p|p.rsplit_once('/').map(|(dir,_)|dir)).unwrap_or("");
                let refs=doc.items.iter().filter_map(|item|match item{framexml::TopLevel::Include(p)|framexml::TopLevel::Script(framexml::ScriptRef::File(p))=>Some(loader::join_ref(base,p)),_=>None}).collect::<Vec<_>>();
                Ok(json!(refs))
            },
            "eval"=>{let values:mlua::MultiValue=self.ui.eval(string(&v,"source")?).map_err(err)?;Ok(json!(values.into_iter().map(lua_value).collect::<Vec<_>>()))},
            "clock"=>{self.ui.set_now(number(&v,"seconds",0.)?.max(0.));Ok(Value::Null)},
            "xml"=>{
                let bytes=source_bytes(&v["source"])?;let doc=framexml::parse(&engine_ui_core::source::decode(&bytes)).map_err(err)?;
                let files=source_map(&v["files"])?;
                let provider=|path:&str|files.get(&path.replace('\\',"/").to_ascii_lowercase()).cloned();
                let report=loader::load_in(&self.ui,&doc,v["path"].as_str().unwrap_or(""),&provider);
                Ok(json!({"frames":report.frames,"errors":report.errors,"warnings":report.warnings,"missing_files":report.missing_files}))
            },
            "size"=>{self.width=number(&v,"width",1280.)? as f32;self.height=number(&v,"height",720.)? as f32;
                if self.width<1.||self.height<1.||self.width>16384.||self.height>16384.{return Err("invalid viewport".into());}
                self.ui.set_screen_size(self.width,self.height);Ok(Value::Null)},
            "event"=>{let args=v["args"].as_array().cloned().unwrap_or_default();if args.len()>32{return Err("too many event arguments".into());}
                self.ui.fire_event(string(&v,"event")?,args.iter().map(script_value).collect::<Result<_,_>>()?);Ok(Value::Null)},
            "tick"=>{let dt=number(&v,"elapsed",0.)?;if !(0. ..=1.).contains(&dt){return Err("invalid tick".into());}self.ui.tick(dt as f32);self.draw()},
            "draw"=>self.draw(),
            "links"=>{
                let items=v["spans"].as_array().ok_or("hyperlink spans required")?;
                if items.len()>2048{return Err("hyperlink span capacity exceeded".into());}
                let targets:std::collections::HashMap<_,_>=self.ui.live_targets().into_iter().filter_map(|t|self.ui.target_frame(t).map(|f|(format!("{t:?}"),f))).collect();
                let mut spans=Vec::new();let mut text_bytes=0;
                for item in items{
                    let Some(&frame)=targets.get(string(item,"id")?)else{return Err("stale hyperlink target".into());};
                    let r:[f32;4]=serde_json::from_value(item["rect"].clone()).map_err(err)?;
                    if r.iter().any(|n|!n.is_finite()||n.abs()>1e6)||r[2]<=0.||r[3]<=0.{return Err("invalid hyperlink rectangle".into());}
                    let link=string(item,"link")?;let markup=string(item,"markup")?;text_bytes+=link.len()+markup.len();
                    if text_bytes>262144{return Err("hyperlink text capacity exceeded".into());}
                    spans.push((frame,engine_ui_core::layout::Rect::new(self.height-r[1]-r[3],r[0],self.height-r[1],r[0]+r[2]),link.into(),markup.into()));
                }
                self.ui.set_link_spans(spans);Ok(Value::Null)
            },
            "ime_replace"=>{
                let start=v["start_chars"].as_i64().ok_or("IME replacement offset required")?;
                let count=v["length_chars"].as_u64().ok_or("IME replacement length required")?;
                if !(-2048..=2048).contains(&start)||count>2048{return Err("IME replacement capacity exceeded".into());}
                if !self.ui.has_keyboard_focus(){return Ok(json!(false));}
                if v["replace_selection"]==true{self.ui.editbox_action(EditAction::Delete{unit:EditUnit::Char,back:false});}
                for _ in 0..start.unsigned_abs(){self.ui.editbox_action(EditAction::Move{unit:EditUnit::Char,back:start<0,extend:false});}
                for _ in 0..count{self.ui.editbox_action(EditAction::Move{unit:EditUnit::Char,back:false,extend:true});}
                let text=string(&v,"text")?;
                Ok(json!(if text.is_empty()&&count>0{self.ui.editbox_action(EditAction::Delete{unit:EditUnit::Char,back:false})}else{self.ui.char_input(text)}))
            },
            "model_facts"=>{
                let rows=v["facts"]["sequences"].as_array().ok_or("model sequence facts required")?;
                if rows.len()>128{return Err("model sequence fact capacity exceeded".into());}
                let sequences=rows.iter().map(|s|Ok(engine_ui_core::widget::SequenceFacts{anim_id:s["anim_id"].as_u64().ok_or("animation id required")?.try_into().map_err(err)?,duration_ms:s["duration_ms"].as_u64().ok_or("duration required")?.try_into().map_err(err)?,looping:s["looping"].as_bool().ok_or("loop flag required")?})).collect::<Result<Vec<_>,String>>()?;
                let bbox:([f32;3],[f32;3])=serde_json::from_value(v["facts"]["bbox"].clone()).map_err(err)?;
                if bbox.0.iter().chain(bbox.1.iter()).any(|x|!x.is_finite()){return Err("invalid model bounds".into());}
                let cameras=v["facts"]["cameras"].as_u64().ok_or("camera count required")?;
                if cameras>64{return Err("camera count capacity exceeded".into());}
                let path=string(&v,"path")?;let facts=engine_ui_core::widget::ModelFileFacts{sequences,bbox,cameras:cameras as u32};
                if let Some(name)=v["name"].as_str(){
                    if name.is_empty()||name.len()>128{return Err("invalid model frame name".into());}
                    if !self.host_model_facts.contains_key(name)&&self.host_model_facts.len()>=8{
                        let retired=self.host_model_facts.keys().find(|old|!self.visible_model_names.contains(old)).cloned().ok_or("host model fact capacity exceeded")?;
                        self.host_model_facts.remove(&retired);
                    }
                    let seed=self.host_model_facts.get(name).filter(|(old,_,_)|old==path).map_or_else(||self.ui.model_pane(name).map_or(0,|m|m.clock_ms),|(_,_,seed)|*seed);
                    self.host_model_facts.insert(name.into(),(path.into(),facts.clone(),seed));
                }
                self.ui.set_model_facts(path,facts);self.draw()
            },
            "minimap_hover"=>minimap_hover::request(self,&v),
            "mouse"=>{
                let x=number(&v,"x",0.)? as f32;let y=self.height-number(&v,"y",0.)? as f32;
                self.ui.set_modifiers(v["shift"].as_bool().unwrap_or(false),v["ctrl"].as_bool().unwrap_or(false),v["alt"].as_bool().unwrap_or(false));
                let hit=match v["action"].as_str().unwrap_or("move") {
                    "move"=>self.ui.mouse_move(x,y).is_some(),
                    "press"=>self.ui.mouse_button(x,y,v["button"].as_str().unwrap_or("LeftButton"),true),
                    "release"=>self.ui.mouse_button(x,y,v["button"].as_str().unwrap_or("LeftButton"),false),
                    "wheel"=>{self.ui.mouse_wheel(x,y,number(&v,"delta",0.)? as f32);true},
                    "leave"=>{self.ui.mouse_move(-1_000_000.,-1_000_000.);self.ui.pointer_left_window();false},_=>return Err("invalid pointer action".into()),
                };nameplates::hover(self);Ok(json!(hit))
            },
            "key"=>{
                let key=string(&v,"key")?;
                self.ui.set_modifiers(v["shift"].as_bool().unwrap_or(false),v["ctrl"].as_bool().unwrap_or(false),v["alt"].as_bool().unwrap_or(false));
                if self.ui.frame_key_input(key){return Ok(json!(true));}
                if matches!(key,"LEFT"|"RIGHT"|"UP"|"DOWN") && self.ui.editbox_alt_arrow_mode() && !v["alt"].as_bool().unwrap_or(false){return Ok(json!(self.binding(&v,key,false)?));}
                let unit=if v["ctrl"].as_bool().unwrap_or(false){EditUnit::Word}else{EditUnit::Char};
                let extend=v["shift"].as_bool().unwrap_or(false);
                let action=match key{
                    "BACKSPACE"=>Some(EditAction::Delete{unit,back:true}),"DELETE"=>Some(EditAction::Delete{unit,back:false}),
                    "LEFT"=>Some(EditAction::Move{unit,back:true,extend}),"RIGHT"=>Some(EditAction::Move{unit,back:false,extend}),
                    "HOME"=>Some(EditAction::Move{unit:EditUnit::Line,back:true,extend}),"END"=>Some(EditAction::Move{unit:EditUnit::Line,back:false,extend}),
                    "UP"=>Some(EditAction::Move{unit:EditUnit::Row,back:true,extend}),"DOWN"=>Some(EditAction::Move{unit:EditUnit::Row,back:false,extend}),
                    "SELECT_ALL"=>Some(EditAction::SelectAll),_=>None};
                let handled=if let Some(a)=action{self.ui.editbox_action(a)}else{self.ui.key_input(key)};
                Ok(json!(handled||self.binding(&v,key,false)?))
            },
            "key_up"=>{
                self.ui.set_modifiers(v["shift"].as_bool().unwrap_or(false),v["ctrl"].as_bool().unwrap_or(false),v["alt"].as_bool().unwrap_or(false));
                Ok(json!(self.binding(&v,string(&v,"key")?,true)?))
            },
            "bindings_load"=>{
                for (set,key) in [(1,"account"),(2,"character")]{
                    let rows:Option<Vec<(String,String)>>=if v[key].is_null(){None}else{Some(serde_json::from_value(v[key].clone()).map_err(err)?)};
                    if rows.as_ref().is_some_and(|r|r.len()>1024){return Err("binding capacity exceeded".into());}
                    self.ui.seed_binding_set(set,rows);
                }
                self.ui.load_binding_set(if self.ui.character_bindings_exist(){2}else{1});Ok(Value::Null)
            },
            "paste"=>Ok(json!(self.ui.paste(string(&v,"text")?))),
            "copy"=>Ok(json!(self.ui.editbox_copy())),
            "cut"=>Ok(json!(self.ui.editbox_cut())),
            "text"=>Ok(json!(self.ui.char_input(string(&v,"text")?))),
            "runtime_config"=>{
                let rows=v["values"].as_object().ok_or("runtime values required")?;
                if rows.len()>16{return Err("runtime setting capacity exceeded".into());}
                for (name,value) in rows{let value=value.as_str().ok_or("runtime setting string required")?;
                    if name.len()>64||value.len()>64{return Err("runtime setting capacity exceeded".into());}
                    self.ui.set_cvar_host(name,value);
                }Ok(Value::Null)
            },
            "graphics_seed"=>{
                let values=v["values"].as_object().filter(|r|r.len()==2).ok_or("graphics values required")?;
                let mut rows=Vec::new();
                for name in ["gxWindow","gxResolution"] {
                    let value=values.get(name).and_then(Value::as_str).filter(|s|s.len()<=32).ok_or("graphics string required")?;
                    rows.push(engine_ui_core::script::SeededCvar{name:name.into(),value:value.into(),default:value.into(),latched:true});
                }self.ui.seed_cvars(rows);Ok(Value::Null)
            },
            "graphics_mode"=>{
                let width=number(&v,"width",0.)? as u32;let height=number(&v,"height",0.)? as u32;
                if !(320..=7680).contains(&width)||!(200..=4320).contains(&height){return Err("graphics size range".into());}
                let current=engine_ui_core::script::ScreenResolution{width,height};
                self.ui.set_screen_resolutions(vec![current],Some(current));Ok(Value::Null)
            },
            "nameplates"=>nameplates::project(self,&v),
            "snapshot"=>{
                if !v["client_controls"].is_null() && self.views.get("client_controls")!=Some(&v["client_controls"]){
                    local_client::feed(&mut self.ui,&v["client_controls"]["local_client"])?;
                    controls::publish(&mut self.ui,&v["client_controls"])?;self.views.insert("client_controls".into(),v["client_controls"].clone());
                }
                let mut unit=UnitState::default();unit.exists=true;unit.has_object=true;unit.is_player=true;unit.player_controlled=true;
                unit.health=number(&v,"health",100.)?.max(0.) as u32;unit.max_health=number(&v,"max_health",100.)?.max(1.) as u32;
                unit.power=number(&v,"resource",100.)?.max(0.) as u32;unit.max_power=number(&v,"max_resource",100.)?.max(1.) as u32;
                unit.level=number(&v,"level",1.)?.max(1.) as u32;unit.name=Some(v["name"].as_str().unwrap_or("Gold Goblin").into());unit.dead=unit.health==0;
                unit.ghost=v["services"]["lifecycle"]["ghost"]==true;
                unit.in_combat=v["world"]["in_combat"].as_bool().unwrap_or(false);
                unit.guid=1;unit.pvp=v["client_controls"]["local_client"]["pvp"].as_bool().unwrap_or(false);
                unit.raid_target=v["services"]["group"]["mark_guids"]["1"].as_u64().unwrap_or(0).min(8) as u8;
                let mut record=PlayerRecord{name:unit.name.clone().unwrap_or_default(),..Default::default()};
                identity::apply(&mut unit,&mut record,&v["identity"])?;
                combat_stats::feed(&mut self.ui,&v["combat_profile"])?;
                self.ui.set_player_record(record);
                let guild=&v["services"]["guild"];
                if guild["in_guild"]==true{
                    let rank=guild["own_rank"].as_u64().unwrap_or(0) as usize;
                    unit.guild=Some(engine_ui_core::script::UnitGuild{name:guild["name"].as_str().unwrap_or("").into(),
                        rank_name:guild["ranks"][rank]["name"].as_str().unwrap_or("").into(),rank_index:rank as u32});
                }
                self.ui.set_unit_by_guid(1,Some(unit.clone()));
                self.ui.set_unit("player",Some(unit));
                item_info::feed(&mut self.ui,&v["services"]["item_templates"],number(&v,"level",1.)?.max(1.) as u32,&v["services"]["item_requirements"])?;
                item_info::feed_sets(&mut self.ui,&v["services"]["item_sets"])?;
                services::feed(self,&v["services"])?;
                opening_cinematic::feed(self,&v["services"]["cinematic"]);
                skills::feed(self,&v["services"]["skills"])?;
                petitions::feed(self,&v["services"]["petition"])?;
                tabards::feed(self,&v["services"]["tabard"])?;
                inventory::feed(self,&v["services"]["inventory_cursor"],&v["services"]["item_targeting"])?;
                self.views.insert("dressup".into(),v["services"]["dressup"].clone());
                social::feed(self,&v["services"])?;
                lifecycle::feed(self,&v["services"]["lifecycle"])?;
                channels::feed(&mut self.ui,&v["services"]["channels"])?;
                self.unit_guids=inspection::feed(&mut self.ui,&v["services"],&v["target"])?;
                inspection::spell_tooltips(&mut self.ui,&v["spells"],&v["services"]["pet"],&v["services"]["pet_spell_templates"])?;
                travel::feed(self,&v["services"]["travel"])?;
                battlefields::feed(self,&v["services"]["battlefields"])?;
                instance_sessions::feed(self,&v["services"]["instance_sessions"])?;
                nameplates::feed(self,&v)?;
                world_map::feed(self,&v["navigation"])?;
                if let Some(world)=v["world"].as_object(){
                    if world.len()>32||world.keys().any(|k|k.len()>64)||world.values().any(|v|v.is_array()||v.is_object()||v.as_str().is_some_and(|s|s.len()>512)){return Err("invalid world state".into());}
                    let zone=engine_ui_core::script::ZoneTexts{zone:world.get("zone").and_then(Value::as_str).unwrap_or("").into(),real_zone:world.get("real_zone").and_then(Value::as_str).unwrap_or("").into(),subzone:world.get("subzone").and_then(Value::as_str).unwrap_or("").into(),minimap:world.get("minimap").and_then(Value::as_str).unwrap_or("").into(),..Default::default()};
                    let old=self.world.borrow().clone();let current:BTreeMap<_,_>=world.iter().map(|(k,v)|(k.clone(),v.clone())).collect();
                    self.ui.set_zone_texts(zone);*self.world.borrow_mut()=current.clone();
                    for (key,event) in [("real_zone","ZONE_CHANGED_NEW_AREA"),("subzone","ZONE_CHANGED"),("minimap","MINIMAP_ZONE_CHANGED")]{if old.get(key)!=current.get(key){self.ui.fire_event(event,vec![]);}}
                    if old.get("indoors")!=current.get("indoors"){self.ui.fire_event("ZONE_CHANGED_INDOORS",vec![]);}
                }
                let clock:f64=self.ui.eval("return GetTime()").map_err(err)?;
                self.ui.set_player_xp(number(&v,"xp",0.)?.max(0.) as u32,number(&v,"xp_to_next",100.)?.max(1.) as u32);
                self.ui.set_money(v["money_copper"].as_u64().unwrap_or(0).min(20_000_000_000_000));
                if let Some(items)=v["inventory"].as_array(){
                    if items.len()>64{return Err("inventory capacity exceeded".into());}
                    let mut bag=ContainerState{name:Some("GG Backpack".into()),num_slots:64,..Default::default()};
                    for item in items{
                        let id=item["item_id"].as_u64().ok_or("item id required")? as u32;
                        let quality=item["quality"].as_u64().unwrap_or(1) as u32;let name=string(item,"name")?.to_owned();
                        if !v["services"]["item_templates"].is_array(){self.ui.set_item_template(id,ItemTemplateView{name,quality,icon:item["icon"].as_str().map(str::to_owned),item_type:item["kind"].as_str().map(str::to_owned),stackable:item["stack_limit"].as_u64().unwrap_or(1) as u32,..Default::default()});}
                        bag.slots.insert(item["slot"].as_u64().ok_or("item slot required")? as u32,ContainerSlot{item_id:id,count:item["count"].as_u64().unwrap_or(1) as u32,quality:Some(quality),link:item["link"].as_str().map(str::to_owned),texture:item["icon"].as_str().map(str::to_owned),equip_slots:serde_json::from_value(item["equip_slots"].clone()).unwrap_or_default(),durability:serde_json::from_value(item["durability"].clone()).ok(),enchants:item_info::enchants(item),already_bound:item["already_bound"]==true,flags:item["flags"].as_u64().unwrap_or(0).min(u32::MAX as u64) as u32,locked:item_info::locked(item,&v["services"]),bar_placeable:item["usable_on_actionbar"]==true||matches!(item["kind"].as_str(),Some("CONSUMABLE"|"TOOL"|"WEAPON"|"ARMOR")),..Default::default()});
                    }
                    self.ui.set_container(0,Some(bag));
                }
                if let Some(bank)=v["bank"].as_object().map(|b|Value::Object(b.clone())) {
                    if self.views.get("bank")!=Some(&bank) {
                        let opened=bank["open"]==true;
                        let was_open=self.views.get("bank").is_some_and(|b|b["open"]==true);
                        let old_items=self.views.get("bank").and_then(|b|b["items"].as_array()).cloned().unwrap_or_default();
                        let new_items=if opened{bank["items"].as_array().cloned().unwrap_or_default()}else{vec![]};
                        // Preserve the two original producers: identity changes
                        // carry no args; fields of the same instance carry player.
                        // GG extends the vault's capacity to 48, not its ABI shape.
                        let vault_events:Vec<bool>=(1..=48u64).filter_map(|slot|{
                            let old=old_items.iter().find(|i|i["slot"].as_u64()==Some(slot));
                            let new=new_items.iter().find(|i|i["slot"].as_u64()==Some(slot));
                            if old.and_then(|i|i["instance_id"].as_str())!=new.and_then(|i|i["instance_id"].as_str()){Some(false)}
                            else if old!=new{Some(true)}else{None}
                        }).collect();
                        if opened {
                            let capacity=bank["capacity"].as_u64().filter(|&n|n<=48).ok_or("invalid bank capacity")? as u32;
                            let items=bank["items"].as_array().ok_or("bank items required")?;
                            if items.len()>capacity as usize{return Err("bank item capacity exceeded".into());}
                            let mut bag=ContainerState{name:Some(string(&bank,"name")?.into()),num_slots:capacity,..Default::default()};
                            for item in items {
                                if string(item,"instance_id")?.len()>64{return Err("bank instance id capacity exceeded".into());}
                                let slot=item["slot"].as_u64().filter(|&s|s>=1&&s<=capacity as u64).ok_or("invalid bank slot")? as u32;
                                if bag.slots.contains_key(&slot){return Err("duplicate bank slot".into());}
                                let id=item["item_id"].as_u64().ok_or("bank item id required")?.try_into().map_err(err)?;
                                let quality=item["quality"].as_u64().unwrap_or(1).min(6) as u32;
                                if !v["services"]["item_templates"].is_array(){self.ui.set_item_template(id,ItemTemplateView{name:string(item,"name")?.into(),quality,icon:item["icon"].as_str().map(str::to_owned),item_type:item["kind"].as_str().map(str::to_owned),stackable:item["stack_limit"].as_u64().unwrap_or(1).min(999) as u32,..Default::default()});}
                                bag.slots.insert(slot,ContainerSlot{item_id:id,count:item["count"].as_u64().unwrap_or(1).min(999) as u32,quality:Some(quality),link:item["link"].as_str().map(str::to_owned),texture:item["icon"].as_str().map(str::to_owned),equip_slots:serde_json::from_value(item["equip_slots"].clone()).unwrap_or_default(),durability:serde_json::from_value(item["durability"].clone()).ok(),enchants:item_info::enchants(item),already_bound:item["already_bound"]==true,flags:item["flags"].as_u64().unwrap_or(0).min(u32::MAX as u64) as u32,locked:item_info::locked(item,&v["services"]),..Default::default()});
                            }
                            self.ui.set_container(-1,Some(bag));self.ui.set_bank(Some(BankState{num_purchased:0,next_cost:0}));
                        }else{self.ui.set_bank(None);self.ui.set_container(-1,None);}
                        self.views.insert("bank".into(),bank.clone());
                        // The data must exist before the original bank event handlers run.
                        if opened!=was_open{self.ui.fire_event(if opened{"BANKFRAME_OPENED"}else{"BANKFRAME_CLOSED"},vec![]);}
                        for same_item in vault_events{
                            self.ui.fire_event("PLAYERBANKSLOTS_CHANGED",if same_item{vec![ScriptValue::Str("player".into())]}else{vec![]});
                        }
                    }
                }
                if let Some(merchant)=v["merchant"].as_object().map(|m|Value::Object(m.clone())) {
                    if self.views.get("merchant")!=Some(&merchant) {
                        let opened=merchant["open"]==true;
                        let previous=self.views.get("merchant");
                        let was_open=previous.is_some_and(|m|m["open"]==true);
                        let switched=opened&&was_open&&previous.is_some_and(|m|m["vendor_id"]!=merchant["vendor_id"]);
                        if switched{self.ui.set_merchant(None);self.ui.fire_event("MERCHANT_CLOSED",vec![]);}
                        if opened {
                            let items=merchant["items"].as_array().ok_or("merchant items required")?;
                            if items.len()>16{return Err("merchant capacity exceeded".into());}
                            let mut state=MerchantState::default();
                            state.can_repair=merchant["can_repair"]==true;
                            for item in items {
                                let id=item["item_id"].as_u64().ok_or("merchant item id required")?.try_into().map_err(err)?;
                                state.items.push(MerchantItem{name:Some(string(item,"name")?.into()),texture:item["texture"].as_str().map(str::to_owned),price:item["price"].as_u64().ok_or("merchant price required")?.try_into().map_err(err)?,quantity:item["quantity"].as_u64().unwrap_or(1).try_into().map_err(err)?,num_available:item["num_available"].as_i64().unwrap_or(1).try_into().map_err(err)?,item_id:id,link:item["link"].as_str().map(str::to_owned),max_stack:item["max_stack"].as_u64().map(|v|v.min(999) as u32),..Default::default()});
                                if !v["services"]["item_templates"].is_array(){self.ui.set_item_template(id,ItemTemplateView{name:string(item,"name")?.into(),quality:item["quality"].as_u64().unwrap_or(1).min(6) as u32,icon:item["texture"].as_str().map(str::to_owned),item_type:item["kind"].as_str().map(str::to_owned),stackable:item["max_stack"].as_u64().unwrap_or(1).min(999) as u32,..Default::default()});}
                            }
                            if let Some(rows)=merchant["buybacks"].as_array(){
                                if rows.len()>12{return Err("buyback capacity exceeded".into());}
                                for item in rows{state.buyback.push(MerchantItem{name:Some(string(item,"name")?.into()),texture:item["texture"].as_str().map(str::to_owned),price:item["price"].as_u64().ok_or("buyback price required")?.try_into().map_err(err)?,quantity:item["quantity"].as_u64().unwrap_or(1).try_into().map_err(err)?,item_id:item["item_id"].as_u64().ok_or("buyback item id required")?.try_into().map_err(err)?,max_stack:item["max_stack"].as_u64().map(|v|v.min(999) as u32),..Default::default()});}
                            }
                            self.ui.set_repair_all_cost(merchant["repair_cost"].as_u64().unwrap_or(0).try_into().map_err(err)?);
                            let mut costs=RepairCosts::default();
                            if let Some(rows)=merchant["repair_bags"].as_array(){if rows.len()>64{return Err("repair bag capacity exceeded".into());}for row in rows{costs.bags.insert((row[0].as_i64().ok_or("repair bag required")?,row[1].as_u64().ok_or("repair slot required")?.try_into().map_err(err)?),row[2].as_u64().ok_or("repair cost required")?.try_into().map_err(err)?);}}
                            if let Some(rows)=merchant["repair_equipped"].as_array(){if rows.len()>24{return Err("repair equipment capacity exceeded".into());}for row in rows{costs.equipped.insert(row[0].as_u64().ok_or("repair slot required")?.try_into().map_err(err)?,row[1].as_u64().ok_or("repair cost required")?.try_into().map_err(err)?);}}
                            self.ui.set_repair_costs(costs);
                            self.ui.set_merchant(Some(state));
                        }else{self.ui.set_merchant(None);self.ui.set_repair_all_cost(0);self.ui.set_repair_costs(RepairCosts::default());}
                        self.views.insert("merchant".into(),merchant);
                        if opened!=was_open||switched{self.ui.fire_event(if opened{"MERCHANT_SHOW"}else{"MERCHANT_CLOSED"},vec![]);}
                        else if opened{self.ui.fire_event("MERCHANT_UPDATE",vec![]);}
                    }
                }
                if let Some(items)=v["equipment"].as_array().filter(|_|self.views.get("equipment")!=Some(&v["equipment"])){
                    if items.len()>23{return Err("equipment capacity exceeded".into());}
                    let mut slots:engine_ui_core::script::InventorySlots=Default::default();
                    for item in items{
                        let slot=item["slot"].as_u64().filter(|&s|(1..=23).contains(&s)).ok_or("invalid equipment slot")? as usize;
                        if slots[slot].is_some(){return Err("duplicate equipment slot".into());}
                        let id=item["item_id"].as_u64().ok_or("equipment item id required")?.try_into().map_err(err)?;
                        let name=string(item,"name")?.to_owned();let quality=item["quality"].as_u64().unwrap_or(1).min(6) as u32;
                        if !v["services"]["item_templates"].is_array(){self.ui.set_item_template(id,ItemTemplateView{name:name.clone(),quality,icon:item["icon"].as_str().map(str::to_owned),item_type:item["kind"].as_str().map(str::to_owned),stackable:1,..Default::default()});}
                        slots[slot]=Some(engine_ui_core::script::InvSlotView{item_id:id,name:Some(name),quality:quality as i32,count:item["count"].as_u64().unwrap_or(1).min(u32::MAX as u64) as u32,icon:item["icon"].as_str().map(str::to_owned),link:item["link"].as_str().map(str::to_owned),equip_slots:serde_json::from_value(item["equip_slots"].clone()).unwrap_or_default(),durability:serde_json::from_value(item["durability"].clone()).ok(),enchants:item_info::enchants(item),already_bound:item["already_bound"]==true,flags:item["flags"].as_u64().unwrap_or(0).min(u32::MAX as u64) as u32,locked:item_info::locked(item,&v["services"]),bar_placeable:true,..Default::default()});
                    }
                    self.ui.set_inventory_slots(slots);self.ui.fire_event("UNIT_INVENTORY_CHANGED",vec![ScriptValue::Str("player".into())]);self.views.insert("equipment".into(),v["equipment"].clone());
                }
                if let Some(spells)=v["spells"].as_array(){
                    if spells.len()>128{return Err("spellbook capacity exceeded".into());}
                    let mut book=SpellBookState::default();
                    for spell in spells{
                        let remaining=number(spell,"cooldown_s",0.)?.max(0.);let duration=number(spell,"cooldown_duration_s",remaining)?.max(remaining);
                        book.slots.push(SpellSlotView{spell_id:spell["spell_id"].as_u64().ok_or("spell id required")? as u32,name:string(spell,"name")?.to_owned(),current:spell["current"]==true,cooldown:if remaining>0.{Some((((clock+remaining-duration)*1000.).max(0.) as i64,(duration*1000.) as u32,true))}else{None},..Default::default()});}
                    if !book.slots.is_empty(){book.tabs.push(SpellTabView{name:"GG Abilities".into(),num_spells:book.slots.len() as u32,..Default::default()});}
                    self.ui.set_spellbook(book);
                }
                quests::feed(self,&v)?;
                client_tools::feed(&mut self.ui);
                talents::feed(self,&v)?;
                local_actions::feed(self,&v)?;
                self.ui.set_casting(v["services"]["travel"]["stuck_remaining"].as_f64().unwrap_or(0.)>0.||(v["craft_book"]["open"]==true&&v["craft_book"]["repeat_count"].as_u64().unwrap_or(0)>0));
                if let Some(target)=v["target"].as_object().filter(|t|!t.is_empty()){
                    let target=Value::Object(target.clone());
                    let mut state=UnitState::default();state.exists=true;state.has_object=true;
                    state.name=target["name"].as_str().map(str::to_owned);state.health=number(&target,"health",0.)?.max(0.) as u32;
                    state.max_health=number(&target,"max_health",1.)?.max(1.) as u32;state.level=number(&target,"level",0.)?.max(0.) as u32;
                    state.dead=state.health==0;state.can_attack=target["can_attack"].as_bool().unwrap_or(true);
                    state.reaction=if target["friend"]==true{5}else{3};
                    state.is_player=target["is_player"].as_bool().unwrap_or(false);state.player_controlled=state.is_player;
                    state.guid=target["guid"].as_u64().unwrap_or(if state.is_player{1}else{2});
                    state.raid_target=v["services"]["group"]["mark_guids"][state.guid.to_string()].as_u64().unwrap_or(0).min(8) as u8;
                    self.ui.set_unit("target",Some(state));
                }else{self.ui.set_unit("target",None);}
                for index in 0..120u32 {
                    let a=v["actions"].as_array().and_then(|xs|xs.iter().find(|a|a["index"].as_u64()==Some(index as u64)));
                    if let Some(a)=a.filter(|a|a["kind"].as_str().is_some_and(|k|k!="EMPTY")){
                        let remaining=number(a,"cooldown_s",0.)?.max(0.);let duration=number(a,"cooldown_duration_s",remaining)?.max(remaining);
                        self.ui.set_action(index+1,Some(ActionSlot{texture:a["texture"].as_str().map(str::to_owned),kind:a["action_kind"].as_u64().unwrap_or(if a["kind"]=="ITEM"{128}else{0}) as u8,action:a["action_id"].as_u64().unwrap_or(index as u64+1) as u32,count:a["count"].as_u64().unwrap_or(0) as u32,consumable:a["kind"]=="ITEM"}));
                        self.ui.set_action_state(index+1,Some(ActionState{usable:a["usable"].as_bool().unwrap_or(false),not_enough_mana:a["not_enough_resource"].as_bool().unwrap_or(false),in_range:a["in_range"].as_bool(),has_range:a["in_range"].is_boolean(),current:a["current"].as_bool().unwrap_or(false),is_attack:a["ref"]=="ATTACK",equipped:a["equipped"].as_bool().unwrap_or(false),cooldown:if remaining>0.{Some((((clock+remaining-duration)*1000.).max(0.) as i64,(duration*1000.) as u32,true))}else{None},..Default::default()}));
                    }else{self.ui.set_action(index+1,None);self.ui.set_action_state(index+1,None);}
                }
                snapshot::publish(&self.ui,&v)?;
                // Publish all current getters and the public packet before
                // lifecycle callbacks inspect the new cast or its target.
                spells::feed(self,&v,clock)?;
                self.ui.fire_event("SNAPSHOT",vec![]);
                let mut changes=v.clone();
                changes["armor"]=v["combat_profile"]["armor"].clone();
                changes["spell_names"]=json!(v["spells"].as_array().into_iter().flatten().map(|s|json!([s["spell_id"],s["name"]])).collect::<Vec<_>>());
                for (field,event,args) in [("armor","UNIT_RESISTANCES",vec![ScriptValue::Str("player".into())]),("health","UNIT_HEALTH",vec![ScriptValue::Str("player".into())]),("max_health","UNIT_MAXHEALTH",vec![ScriptValue::Str("player".into())]),("resource","UNIT_MANA",vec![ScriptValue::Str("player".into())]),("max_resource","UNIT_MAXMANA",vec![ScriptValue::Str("player".into())]),("target","PLAYER_TARGET_CHANGED",vec![]),("inventory","BAG_UPDATE",vec![ScriptValue::Number(0.)]),("quests","QUEST_LOG_UPDATE",vec![]),("spell_names","SPELLS_CHANGED",vec![]),("spells","SPELL_UPDATE_COOLDOWN",vec![]),("actions","ACTIONBAR_UPDATE_COOLDOWN",vec![]),("money_copper","PLAYER_MONEY",vec![]),("xp","PLAYER_XP_UPDATE",vec![ScriptValue::Str("player".into())])]{
                    if self.views.get(field)!=Some(&changes[field]){self.views.insert(field.into(),changes[field].clone());self.ui.fire_event(event,args);}
                }
                Ok(Value::Null)
            },
            "registry"=>{
                let mut addons=Vec::new();
                for a in v["addons"].as_array().ok_or("addons array required")? {
                    let texts=|k:&str|a[k].as_array().map(|xs|xs.iter().filter_map(|x|x.as_str().map(str::to_owned)).collect()).unwrap_or_default();
                    addons.push(AddOnInfo{name:string(a,"name")?.into(),title:a["title"].as_str().map(str::to_owned),notes:a["notes"].as_str().map(str::to_owned),url:a["url"].as_str().map(str::to_owned),secure:a["secure"].as_bool().unwrap_or(false),directives:serde_json::from_value(a["directives"].clone()).unwrap_or_default(),enabled:a["enabled"].as_bool().unwrap_or(true),chain:true,
                        interface:a["interface"].as_u64().unwrap_or(11200) as u32,load_on_demand:a["load_on_demand"].as_bool().unwrap_or(false),
                        dependencies:texts("dependencies"),files:texts("files"),saved_variables:texts("saved_variables"),saved_variables_per_character:texts("saved_variables_per_character"),..Default::default()});
                }
                let files=source_map(&v["files"])?;
                self.ui.set_addon_chain_reader(Box::new(move|p|files.get(&p.replace('\\',"/").to_ascii_lowercase()).cloned()));
                self.saved_dirs=[v["saved_account"].as_str().map(std::path::PathBuf::from),v["saved_character"].as_str().map(std::path::PathBuf::from)];
                let rows:Vec<(String,bool)>=serde_json::from_value(v["addon_enable"].clone()).unwrap_or_default();
                self.ui.set_addon_enable_hash(engine_ui_core::script::EnableHash::from_rows(rows));
                self.views.insert("_addon_registry".into(),v["addons"].clone());
                self.ui.register_addons(addons,None,self.saved_dirs[0].clone(),self.saved_dirs[1].clone());self.ui.note_addon_info_reply(&[]);Ok(Value::Null)
            },
            "addon_startup"=>{
                use engine_ui_core::script::addon_gate::{GateRow,can_load};
                let addons=self.views.get("_addon_registry").and_then(Value::as_array).ok_or("No addon registry")?;
                let info:mlua::Function=self.ui.lua().globals().get("GetAddOnInfo").map_err(err)?;
                let loaded:mlua::Function=self.ui.lua().globals().get("IsAddOnLoaded").map_err(err)?;
                let mut gates=Vec::new();
                for addon in addons{
                    let name=string(addon,"name")?;
                    let values:mlua::MultiValue=info.call(name).map_err(err)?;
                    let values:Vec<Value>=values.into_iter().map(lua_value).collect();
                    let is_loaded:mlua::Value=loaded.call(name).map_err(err)?;
                    gates.push(GateRow{name,enabled:!values[3].is_null(),
                        interface:addon["interface"].as_u64().unwrap_or(11200) as u32,
                        load_on_demand:addon["load_on_demand"].as_bool().unwrap_or(false),
                        loaded:!matches!(is_loaded,mlua::Value::Nil),
                        dependencies:addon["dependencies"].as_array().into_iter().flatten().filter_map(Value::as_str).collect()});
                }
                let name=string(&v,"name")?;
                let index=gates.iter().position(|a|a.name.eq_ignore_ascii_case(name)).ok_or("Unknown addon")?;
                let verdict=can_load(&gates,index,false,true);
                Ok(json!({"loadable":verdict.loadable(),"reason":verdict.token()}))
            },
            "addon_status"=>{
                let globals=self.ui.lua().globals();
                let count:mlua::Function=globals.get("GetNumAddOns").map_err(err)?;
                let count:usize=count.call(()).map_err(err)?;
                let info:mlua::Function=globals.get("GetAddOnInfo").map_err(err)?;
                let loaded:mlua::Function=globals.get("IsAddOnLoaded").map_err(err)?;
                let demand:mlua::Function=globals.get("IsAddOnLoadOnDemand").map_err(err)?;
                let mut rows=Vec::new();
                for index in 1..=count.min(128){
                    let values:mlua::MultiValue=info.call(index).map_err(err)?;
                    let values:Vec<Value>=values.into_iter().map(lua_value).collect();
                    let is_loaded:mlua::Value=loaded.call(index).map_err(err)?;
                    let is_demand:mlua::Value=demand.call(index).map_err(err)?;
                    rows.push(json!({"id":values[0],"title":values[1],"notes":values[2],
                        "enabled":!values[3].is_null(),"loadable":!values[4].is_null(),
                        "reason":values[5],"security":values[6],
                        "loaded":!matches!(is_loaded,mlua::Value::Nil),
                        "load_on_demand":!matches!(is_demand,mlua::Value::Nil)}));
                }
                Ok(json!(rows))
            },
            "addon_toggle"=>{
                let name=string(&v,"name")?;
                let enabled=v["enabled"].as_bool().ok_or("enabled boolean required")?;
                let toggle:mlua::Function=self.ui.lua().globals().get(if enabled{"EnableAddOn"}else{"DisableAddOn"}).map_err(err)?;
                toggle.call::<()>(name).map_err(err)?;Ok(Value::Null)
            },
            "addon_load"=>{let load:mlua::Function=self.ui.lua().globals().get("LoadAddOn").map_err(err)?;
                let result:mlua::MultiValue=load.call(string(&v,"name")?).map_err(err)?;
                Ok(json!(result.into_iter().map(lua_value).collect::<Vec<_>>()))},
            "loaded"=>{self.ui.mark_addon_loaded(string(&v,"name")?);Ok(Value::Null)},
            "addon_finish"=>{let name=string(&v,"name")?;self.ui.load_addon_saved_variables(name);self.ui.fire_event("ADDON_LOADED",vec![ScriptValue::Str(name.into())]);Ok(Value::Null)},
            "addon_bindings"=>{let bytes=source_bytes(&v["source"])?;let bindings=engine_ui_core::bindings_xml::parse(&engine_ui_core::source::decode(&bytes)).map_err(err)?;self.ui.register_addon_bindings(string(&v,"name")?,&bindings);Ok(Value::Null)},
            "saved"=>{
                let mut out=BTreeMap::new();
                for (name,account,character) in self.ui.addon_saved_variable_sets(){
                    let held:Vec<bool>=self.saved_dirs.iter().map(|dir|dir.as_ref().map(|d|self.ui.saved_file_held(&d.join(format!("{name}.lua")))).unwrap_or(false)).collect();
                    out.insert(name,json!({"account":String::from_utf8_lossy(&self.ui.saved_variables_bytes_for(&account)),"character":String::from_utf8_lossy(&self.ui.saved_variables_bytes_for(&character)),"held":held}));}
                let bindings:Vec<Value>=self.ui.take_keybind_requests().iter().map(|req|match req{engine_ui_core::script::keybind::KeybindRequest::Save(set)=>json!({"set":set,"keys":self.ui.binding_keys()})}).collect();
                Ok(json!({"addons":out,"registered":String::from_utf8_lossy(&self.ui.saved_variables_bytes()),"bindings":bindings,"macros":macros::saved(&self.ui),"addon_enable":self.ui.take_addon_enable_rows()}))
            },
            "cursor_source"=>Ok(match self.ui.cursor_payload(){
                Some(engine_ui_core::script::CursorPayload::Item(item))=>json!({"kind":"item","bag":item.bag,"slot":item.slot,"count":item.count}),
                Some(engine_ui_core::script::CursorPayload::Merchant(item))=>json!({"kind":"merchant","row":item.row.saturating_add(1)}),
                _=>Value::Null,
            }),
            "cursor_clear"=>{self.ui.clear_cursor_payload();Ok(Value::Null)},
            "merchant_sale_finish"=>{
                let index=v["index"].as_u64().and_then(|n|usize::try_from(n).ok()).ok_or("merchant sale index required")?;
                let restore=v["restore"].as_bool().ok_or("merchant sale restore boolean required")?;
                let item=self.sale_cursors.get_mut(index).and_then(Option::take);
                Ok(json!({"restored":item.is_some_and(|item|restore && self.ui.restore_merchant_cursor_sale(item))}))
            },
            "cursor_sale_commit"=>{
                let item=self.ui.cursor_item().ok_or("cursor sale source changed")?;
                if v["bag"].as_i64()!=Some(item.bag)||v["slot"].as_u64()!=Some(item.slot as u64){return Err("cursor sale source changed".into());}
                self.ui.take_cursor_item_for_sale();Ok(Value::Null)
            },
            "chat_input"=>{
                let line=string(&v,"line")?;
                if line.chars().count()>255 || line.contains(['\0','\r','\n']){return Err("chat input capacity or line format".into());}
                self.ui.push_chat_input(line.into());Ok(Value::Null)
            },
            "requests"=>{
                let registrations=self.ui.take_cvar_registrations();
                if registrations.len()>1024{return Err("CVar registration capacity exceeded".into());}
                self.ui.register_cvars(registrations.iter().map(|(name,value)|(name.as_str(),value.as_str())));
                let macros=macros::rows(&mut self.ui,true);
                let sounds:Vec<Value>=self.ui.take_sounds().into_iter().map(|s|match s{SoundRequest::KitName(n)=>json!({"kit":n}),SoundRequest::File(p)=>json!({"file":p})}).collect();
                let music:Vec<Value>=self.ui.take_music().into_iter().map(|m|match m{MusicRequest::Play(p)=>json!({"play":p}),MusicRequest::Stop=>json!({"stop":true})}).collect();
                let calls:Vec<Value>=self.ui.take_script_calls().into_iter().map(|call|match call{
                    ScriptCall::UseAction(a)=>json!({"op":"action","index":a.action.saturating_sub(1),"on_self":a.on_self}),
                    ScriptCall::TargetNearest{mode,reverse}=>json!({"op":"nearest","mode":format!("{:?}",mode),"reverse":reverse}),
                    ScriptCall::ClearTarget=>json!({"op":"clear"}),ScriptCall::AttackTarget=>json!({"op":"attack"}),
                    ScriptCall::SpellStopCasting=>json!({"op":"stop_cast"}),
                    ScriptCall::CastSpell{spell_id,on_self}=>json!({"op":"spell","spell_id":spell_id,"on_self":on_self}),
                    ScriptCall::UseContainerItem{bag,slot}=>json!({"op":"container","bag":bag,"slot":slot}),
                    ScriptCall::Select(SelectionRequest::Unit(token))=>json!({"op":"select","unit":token}),
                    ScriptCall::Select(SelectionRequest::Assist(token))=>json!({"op":"assist","unit":token}),
                    ScriptCall::Select(SelectionRequest::AssistByName(name))=>json!({"op":"assist_name","name":name}),
                    ScriptCall::Select(SelectionRequest::LastEnemy)=>json!({"op":"last_enemy"}),
                    ScriptCall::TargetByName{name,exact}=>json!({"op":"by_name","name":name,"exact":exact}),
                    ScriptCall::TargetLastTarget=>json!({"op":"last_target"}),
                    ScriptCall::SpellTargetUnit(unit)=>json!({"op":"spell_target","unit":unit}),
                    ScriptCall::SpellStopTargeting=>json!({"op":"stop_targeting"}),
                    ScriptCall::UseInventoryItem(slot)=>json!({"op":"inventory","slot":slot}),
                    ScriptCall::CastPetSpell{spell_id,on_self}=>json!({"op":"pet_spell","spell_id":spell_id,"on_self":on_self}),
                    ScriptCall::CastShapeshiftForm(spell)=>json!({"op":"form","spell_id":spell}),
                    ScriptCall::PetAction(slot)=>json!({"op":"pet_action","slot":slot}),
                    ScriptCall::PetOrder(word)=>json!({"op":"pet_order","word":word})}).collect();
                let item_moves:Vec<Value>=self.ui.take_container_moves().into_iter().map(|m|json!({"src_bag":m.src_bag,"src_slot":m.src_slot,"dst_bag":m.dst_bag,"dst_slot":m.dst_slot,"count":m.count})).collect();
                let autoequips=self.ui.take_container_autoequips();
                self.sale_cursors=self.ui.take_merchant_cursor_sales().into_iter().take(65).map(Some).collect();
                let sales:Vec<Value>=self.sale_cursors.iter().flatten().map(|item|json!([item.bag,item.slot])).collect();
                let sale_counts:Vec<Value>=self.sale_cursors.iter().flatten().map(|item|json!([item.bag,item.slot,item.count.unwrap_or(0)])).collect();
                let mut result=json!({"sounds":sounds,"music":music,"calls":calls,"cvars":self.ui.take_cvar_changes(),
                    "item_moves":item_moves,"autoequips":autoequips,"action_sets":self.ui.take_action_sets(),"macros":macros,
                    "bank_close":self.ui.take_bank_close(),"bank_purchase":self.ui.take_bank_purchase(),
                    "merchant_buys":self.ui.take_merchant_buys(),"merchant_sells":sales,"merchant_sale_counts":sale_counts,
                    "merchant_slot_buys":self.ui.take_merchant_slot_buys(),"merchant_close":self.ui.take_merchant_close(),
                    "merchant_buybacks":self.ui.take_merchant_buybacks(),"repair_all":self.ui.take_repair_all(),
                    "container_repairs":self.ui.take_container_repairs(),"inventory_repairs":self.ui.take_inventory_repairs(),
                    "session":self.ui.take_session_requests().iter().map(|s|format!("{:?}",s)).collect::<Vec<_>>(),
                    "chat_input":self.ui.take_chat_input()});
                if let Value::Object(extra)=quests::requests(&mut self.ui){for (key,value) in extra{result[key]=value;}}
                if let Value::Object(extra)=local_actions::requests(&mut self.ui){for (key,value) in extra{result[key]=value;}}
                if let Value::Object(extra)=controls::requests(&mut self.ui){for (key,value) in extra{result[key]=value;}}
                if let Value::Object(extra)=local_client::requests(&mut self.ui){for (key,value) in extra{result[key]=value;}}
                if let Value::Object(extra)=services::requests(&mut self.ui){for (key,value) in extra{result[key]=value;}}
                if let Some(extra)=social::requests(&mut self.ui).as_array(){
                    if let Some(services)=result["services"].as_array_mut(){services.extend(extra.iter().cloned());}
                }
                if let Some(services)=result["services"].as_array_mut(){services.extend(lifecycle::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(channels::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(inventory::requests(self));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(dressup::requests(self));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(opening_cinematic::requests(self));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(inspection::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(item_info::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(travel::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(battlefields::requests(self));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(instance_sessions::requests(self));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(skills::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(petitions::requests(&mut self.ui));}
                if let Some(services)=result["services"].as_array_mut(){services.extend(tabards::requests(self));}
                let extra=client_tools::requests(&mut self.ui);
                if let Some(services)=result["services"].as_array_mut(){services.extend(extra["services"].as_array().cloned().unwrap_or_default());}
                result["client_tools"]=extra["client_tools"].clone();
                result["nameplates"]=nameplates::requests(self);
                result["ui_cache"]=json!(ui_cache::requests(&mut self.ui));
                self.ui.take_cursor_write();
                result["cursor"]=json!({"override":self.ui.ui_cursor().map(|m|format!("{:?}",m)),"repair":self.ui.repair_mode()});
                result["unimplemented"]=json!(pending::requests(&mut self.ui));
                result["talent_learns"]=json!(self.ui.take_talent_learns());
                result["talent_wipes"]=json!(self.ui.take_talent_wipe_confirms());
                result["ui_errors"]=json!(self.ui.take_ui_errors().into_iter().map(|key|
                    self.ui.lua().globals().get::<String>(key).unwrap_or_else(|_|key.into())).collect::<Vec<_>>());
                Ok(result)
            },
            "auction_sell_clear"=>{self.ui.clear_auction_sell_item();self.ui.fire_event("NEW_AUCTION_UPDATE",vec![]);Ok(json!({"ok":true}))},
            "mail_compose_clear"=>{self.ui.drop_send_mail_item();self.ui.reset_compose_tab();self.ui.eval::<()>("SelectStationery(1)").map_err(err)?;Ok(json!({"ok":true}))},
            "census"=>{
                let ui=UiScript::new().map_err(err)?;
                let globals:Vec<Vec<String>>=ui.eval("local out={} for k,v in pairs(getfenv(0)) do if type(k)=='string' then table.insert(out,{k,type(v)}) end end return out").map_err(err)?;
                let widgets=widget_method_census(&ui).map_err(err)?;
                Ok(json!({"globals":globals,"widget_methods":widgets}))
            },
            _=>Err("unknown operation".into()),
        }
    }
}
#[no_mangle] pub extern "C" fn ggbu_abi_version()->u32{1}
#[no_mangle] pub unsafe extern "C" fn ggbu_text_measurer(p:*mut std::ffi::c_void,callback:MeasureCallback,user:*mut std::ffi::c_void)->i32{
    if p.is_null(){return -1;}let h=&mut *p.cast::<Host>();h.measurer=Some((callback,user));h.ui.set_text_measurer(Box::new(Measurer{callback,user}));0
}
#[no_mangle] pub extern "C" fn ggbu_create()->*mut std::ffi::c_void{
    match catch_unwind(Host::new){Ok(Ok(h))=>Box::into_raw(Box::new(h)).cast(),_=>std::ptr::null_mut()}
}
#[no_mangle] pub unsafe extern "C" fn ggbu_destroy(p:*mut std::ffi::c_void){if !p.is_null(){drop(Box::from_raw(p.cast::<Host>()));}}
#[no_mangle] pub unsafe extern "C" fn ggbu_request(p:*mut std::ffi::c_void,data:*const u8,n:usize)->i32{
    if p.is_null()||data.is_null()||n>MAX_MESSAGE{return -1;}
    let h=&mut *p.cast::<Host>();
    let result=catch_unwind(AssertUnwindSafe(||serde_json::from_slice::<Value>(slice::from_raw_parts(data,n)).map_err(err).and_then(|v|h.command(v))));
    let response=match result{Ok(Ok(v))=>json!({"ok":true,"result":v}),Ok(Err(e))=>json!({"ok":false,"error":e}),Err(_)=>json!({"ok":false,"error":"native UI panic"})};
    h.response=serde_json::to_vec(&response).unwrap_or_default();
    if h.response.len()>MAX_MESSAGE{h.response=br#"{"ok":false,"error":"response capacity exceeded"}"#.to_vec();}
    0
}
#[no_mangle] pub unsafe extern "C" fn ggbu_response(p:*mut std::ffi::c_void,n:*mut usize)->*const u8{
    if p.is_null()||n.is_null(){return std::ptr::null();}let h=&*p.cast::<Host>();*n=h.response.len();h.response.as_ptr()
}
