//! GG C ABI over unmodified GgEngine readers. No Bevy dependency or Lua file access.
use serde_json::{json,Value};
use std::{ffi::CStr,io::Cursor,path::{Path,PathBuf},panic::{catch_unwind,AssertUnwindSafe},slice,sync::Arc};
#[path="../../../upstream/tga.rs"] mod tga;
mod runtime;
mod billboard;
mod lighting;
mod daynight;
mod liquid_shared;
mod clouds;
mod sky_art;
mod character;
mod equipment;
mod anim_events;
mod effects;
mod effect_rebase;
mod collision;
mod particle_emit;
mod ribbons;
mod creatures;
mod scene;
mod world_props;
mod wdl;
mod weather;
mod audio_catalog;
mod entity_audio;
mod world_navigation;
mod gameplay_data;
mod mpq_envelope;
mod skybox;
mod wmo_directory;
struct Effects {particles:effects::System,ribbons:ribbons::System,events:anim_events::Track}
impl Effects {fn new(model:&runtime::Model,dependencies:&std::collections::HashMap<String,Arc<runtime::Model>>)->Self{Self{particles:effects::System::new(&model.emitters,dependencies),ribbons:ribbons::System::new(model.ribbons.len()),events:Default::default()}}}
const MAX_FILE:usize=16*1024*1024;
const MAX_BLOB:usize=8*1024*1024;
// Eight body sources + 64 committed parts + one eight-part staged outfit.
const MAX_MODELS:usize=80;
struct Reader {mpq_envelopes:std::collections::HashMap<PathBuf,mpq_envelope::Envelope>,game_data:gameplay_data::State,navigation:Option<Value>,entity_audio:entity_audio::Catalogs,audio_files:std::collections::HashMap<u32,engine_mpq::ArchiveFile>,next_audio_file:u32,weather_checkpoint:Option<weather::System>,collision_stage:Option<(String,usize,collision::Page)>,skyboxes:std::collections::HashMap<PathBuf,skybox::Skybox>,weather:weather::System,wdl:Option<engine_formats_core::WdlFile>,root:PathBuf,response:Vec<u8>,blob:Vec<u8>,models:std::collections::HashMap<PathBuf,Arc<runtime::Model>>,collisions:std::collections::HashMap<String,collision::Page>,dependency_models:std::collections::HashSet<PathBuf>,bindings:std::collections::HashMap<PathBuf,std::collections::HashMap<String,PathBuf>>,chain:Option<engine_formats_core::Chain>,chain_files:Vec<PathBuf>,sound_kits:Option<engine_formats_core::SoundKitCatalog>,area_sounds:Option<engine_formats_core::AreaSoundCatalog>,wmo_areas:Option<engine_formats_core::WmoAreaCatalog>,sound_providers:Option<engine_formats_core::SoundProviderCatalog>,characters:Option<character::Catalog>,creatures:Option<engine_formats_core::CreatureCatalog>,lights:Option<engine_formats_core::LightCatalog>,clouds:clouds::Clouds,celestial:sky_art::Celestial,effects:std::collections::HashMap<String,(PathBuf,Effects)>}
fn error(e:impl std::fmt::Display)->String{e.to_string()}
fn text<'a>(v:&'a Value,key:&str)->Result<&'a str,String>{v[key].as_str().ok_or_else(||format!("missing string: {key}"))}
fn vec3(v:&engine_m2::C3)->[f32;3]{[v.x,v.z,-v.y]}
fn geometry(positions:Vec<[f32;3]>,normals:Vec<[f32;3]>,uv:Vec<[f32;2]>,indices:Vec<u32>,primitives:Vec<Value>)->Result<Value,String>{
    if positions.len()>65536 || indices.len()>393216 || primitives.len()>512{return Err("model geometry capacity exceeded".into());}
    if positions.iter().chain(normals.iter()).flatten().chain(uv.iter().flatten()).any(|x|!x.is_finite()) {return Err("non-finite model data".into());}
    if indices.len()%3!=0 || indices.iter().any(|&i|i as usize>=positions.len()){return Err("invalid model triangle index".into());}
    Ok(json!({"positions":positions,"normals":normals,"uv":uv,"indices":indices,"primitives":primitives}))
}
impl Reader {
 fn ensure_model(&mut self,path:&Path)->Result<(),String>{
    if self.models.contains_key(path){return Ok(());}
    if self.models.len()>=MAX_MODELS{return Err("M2 model capacity exceeded".into());}
    let size=path.metadata().map_err(error)?.len() as usize;
    if size>MAX_FILE||self.models.values().map(|m|m.source_bytes()).sum::<usize>()+size>64*1024*1024{return Err("M2 source cache capacity exceeded".into());}
    let model=runtime::Model::new(std::fs::read(path).map_err(error)?,path.parent().unwrap().to_str().ok_or("invalid model directory")?)?;
    self.models.insert(path.to_path_buf(),Arc::new(model));Ok(())
 }
 fn dependencies(&mut self,path:&Path)->Result<std::collections::HashMap<String,Arc<runtime::Model>>,String>{
    let names=self.models.get(path).ok_or("M2 runtime model not loaded")?.particle_dependencies();let mut result=std::collections::HashMap::new();
    for name in names{
        let binding=self.bindings.get(path).and_then(|b|b.get(&name)).cloned();
        let raw=PathBuf::from(name.replace('\\',"/"));
        let candidates=if let Some(p)=binding{vec![p]}else if raw.is_absolute(){vec![raw]}else{vec![path.parent().unwrap().join(&raw),self.root.join(raw)]};
        let mut resolved=None;
        for candidate in candidates{for p in [candidate.clone(),candidate.with_extension("m2")]{
            if let Ok(real)=p.canonicalize(){if !real.starts_with(&self.root){return Err("particle model outside permitted root".into());}if real.is_file(){resolved=Some(real);break;}}
        }if resolved.is_some(){break;}}
        if let Some(p)=resolved{self.ensure_model(&p)?;self.dependency_models.insert(p.clone());result.insert(name,self.models[&p].clone());}
    }
    Ok(result)
 }
 fn world_result(&mut self,mut result:Value,v:&Value)->Result<Value,String>{
    if self.chain.is_some(){
        let keys:Vec<Value>=result["groups"].as_array().into_iter().flatten().map(|g|json!({"wmo_id":g["wmo_id"],"name_set":g["name_set"],"group_id":g["group_id"]})).collect();
        let mut note=None;
        for (index,key) in keys.iter().enumerate(){
            match self.interior_audio(key){
                Ok(row)=>{
                    let g=&mut result["groups"][index];g["area_id"]=json!(row.as_ref().map(|r|r.area_table_id).unwrap_or(0));
                    g["area_source"]=json!("ORIGINAL_WMO_DBC");g["area_name"]=json!(row.as_ref().map(|r|r.name.as_str()).unwrap_or(""));
                },
                Err(error)=>{result["groups"][index]["area_id"]=json!(0);note=Some(error);}
            }
        }
        if let Some(error)=note{if let Some(rows)=result["limitations"].as_array_mut(){rows.push(json!(format!("WMO area identity unavailable: {error}")));}}
    }
    if let Some(key)=v["collision_key"].as_str().or_else(||if v["world_instance"]==true{v["instance"].as_str()}else{None}){
        if key.is_empty()||key.len()>128{return Err("invalid collision page key".into());}
        let page=collision::Page::new(&result,&self.blob)?;
        if self.collisions.len()>=512&&!self.collisions.contains_key(key)||self.collisions.iter().filter(|(k,_)|k.as_str()!=key).map(|(_,p)|p.bytes).sum::<usize>()+page.bytes>64*1024*1024{return Err("native walking collision capacity exceeded".into());}
        result["native_collision_bytes"]=json!(page.bytes);self.collisions.insert(key.into(),page);
    }
    Ok(result)
 }
 fn sample_model(&mut self,path:&Path,v:&Value)->Result<Value,String>{
    let dependencies=if v["instance"].is_string(){self.dependencies(path)?}else{Default::default()};
    let model=self.models.get(path).ok_or("M2 runtime model not loaded")?;
    let mut result=model.sample(v,&mut self.blob)?;
    if let Some(instance)=v["instance"].as_str(){
        if instance.is_empty()||instance.len()>128{return Err("invalid model instance".into());}
        let attached=v["attachment_instance"]==true;let world=v["world_instance"]==true;
        if attached&&world||attached!=instance.starts_with("attachment:")||world!=instance.starts_with("world:"){return Err("invalid model instance namespace".into());}
        let count=self.effects.keys().filter(|key|key.starts_with("attachment:")==attached&&key.starts_with("world:")==world).count();
        if !self.effects.contains_key(instance)&&count>=if world{256}else if attached{72}else{8}{return Err("particle instance capacity exceeded".into());}
        if world&&model.emitters.is_empty()&&model.ribbons.is_empty()&&!model.has_events(){return Ok(result);}
        let state=self.effects.entry(instance.into()).or_insert_with(||(path.to_path_buf(),Effects::new(model,&dependencies)));
        if state.0!=path{*state=(path.to_path_buf(),Effects::new(model,&dependencies));}
        let (seq,t,clip_time,matrices)=model.effect_pose(v)?;
        result["events"]=state.1.events.sample(model.selected_clip(v)?,&matrices,runtime::Model::anchor(v)?,v)?;
        let mut camera=result["camera"].clone();
        if !v["view"].is_null(){let eye=&v["view"]["eye"];let forward=&v["view"]["forward"];
            if let (Some(e),Some(f))=(eye.as_array(),forward.as_array()){if e.len()!=3||f.len()!=3{return Err("invalid effect camera".into());}let mut target=[0.;3];for i in 0..3{target[i]=e[i].as_f64().ok_or("invalid effect camera")?+f[i].as_f64().ok_or("invalid effect camera")?;}camera=json!({"position":eye,"target":target,"up":v["view"]["up"],"roll":0.});}
        }
        result["effects"]=state.1.particles.sample(&model.emitters,&model.particle_blends,seq,t,&matrices,v,&camera,&self.collisions,&mut self.blob)?;
        result["ribbons"]=state.1.ribbons.sample(&model.ribbons,&matrices,v,clip_time,&mut self.blob)?;
        result["blob_bytes"]=json!(self.blob.len());
    }
    Ok(result)
 }
 fn path(&self,v:&Value)->Result<PathBuf,String>{
    let p=Path::new(text(v,"path")?);let path=if p.is_absolute(){p.to_path_buf()}else{self.root.join(p)}.canonicalize().map_err(error)?;
    if !path.starts_with(&self.root)||!path.is_file(){return Err("asset path outside permitted root".into());}Ok(path)
 }
 fn request(&mut self,v:Value)->Result<Value,String>{
    self.blob.clear();
    if v["op"]=="collision_begin"{
        let key=text(&v,"key")?;let expected=v["triangles"].as_u64().filter(|&n|n<=1_000_000).ok_or("collision restore capacity exceeded")? as usize;
        if key.is_empty()||key.len()>128{return Err("invalid collision page key".into());}
        self.collision_stage=Some((key.into(),expected,collision::Page::empty()));return Ok(Value::Null);
    }
    if v["op"]=="collision_append"{
        let (key,expected,mut page)=self.collision_stage.take().ok_or("collision restore not begun")?;
        if text(&v,"key")?!=key{return Err("collision restore key changed".into());}page.append(&v["triangles"])?;
        if page.count()>expected||self.collisions.values().map(|p|p.bytes).sum::<usize>()+page.bytes>64*1024*1024{return Err("native walking collision capacity exceeded".into());}
        self.collision_stage=Some((key,expected,page));return Ok(Value::Null);
    }
    if v["op"]=="collision_commit"{
        let (key,expected,page)=self.collision_stage.take().ok_or("collision restore not begun")?;
        if text(&v,"key")?!=key||page.count()!=expected{return Err("incomplete collision restore".into());}
        if self.collisions.len()>=512&&!self.collisions.contains_key(&key){return Err("native collision page capacity exceeded".into());}
        let bytes=page.bytes;self.collisions.insert(key,page);return Ok(json!({"native_collision_bytes":bytes,"triangles":expected}));
    }
    if v["op"]=="collision_abort"{self.collision_stage=None;return Ok(Value::Null);}
    if v["op"]=="collision_query"{
        let row=v["position"].as_array().filter(|a|a.len()==3).ok_or("invalid collision query position")?;let mut xyz=[0.;3];
        for (p,n) in xyz.iter_mut().zip(row){*p=n.as_f64().ok_or("invalid collision query number")? as f32;}
        let p=glam::Vec3::new(xyz[0],-xyz[2],xyz[1]);if !p.is_finite(){return Err("non-finite collision query".into());}
        return Ok(json!({"height":collision::down(&self.collisions,p)}));
    }
    if v["op"]=="weather_checkpoint"{
        if self.weather_checkpoint.is_some(){return Err("weather transaction already active".into());}
        self.weather_checkpoint=Some(self.weather.clone());return Ok(Value::Null);
    }
    if v["op"]=="weather_commit"{self.weather_checkpoint=None;return Ok(Value::Null);}
    if v["op"]=="weather_rollback"{if let Some(old)=self.weather_checkpoint.take(){self.weather=old;}return Ok(Value::Null);}
    if v["op"]=="weather_status"{return Ok(self.weather.snapshot());}
    if v["op"]=="weather_set"{return self.weather.set(&v);}
    if v["op"]=="weather_frame"{return self.weather.frame(&v,&self.collisions);}
    if v["op"]=="weather_draw"{return self.weather.draw(&v,&mut self.blob);}
    if v["op"]=="weather_release"{self.weather_checkpoint=None;self.weather=Default::default();return Ok(Value::Null);}

    if v["op"]=="wdl_load"{
        let (file,result)=wdl::load(self.chain.as_mut().ok_or("WDL requires a mounted asset chain")?,text(&v,"map")?,&mut self.blob)?;
        self.wdl=Some(file);return Ok(result);
    }
    if v["op"]=="wdl_tiles"||v["op"]=="wdl_heights"{return wdl::sample(self.wdl.as_ref().ok_or("WDL not loaded")?,&v,&mut self.blob);}
    if v["op"]=="wdl_release"{self.wdl=None;return Ok(Value::Null);}
    if v["op"]=="stats"{return Ok(json!({"wdl_bytes":if self.wdl.is_some(){wdl::RESIDENT_BYTES}else{0},"models":self.models.len(),"model_source_bytes":self.models.values().map(|m|m.source_bytes()).sum::<usize>(),"effect_instances":self.effects.len(),"archive_audio_handles":self.audio_files.len(),"skybox_bytes":self.skyboxes.values().map(|s|s.bytes).sum::<usize>(),"collision_staged_bytes":self.collision_stage.as_ref().map_or(0,|(_,_,p)|p.bytes),"collision_pages":self.collisions.len(),"collision_bytes":self.collisions.values().map(|p|p.bytes).sum::<usize>()}));}
    if v["op"]=="pose_many"{
        let items=v["items"].as_array().filter(|a|a.len()<=128).ok_or("world pose batch capacity exceeded")?;
        let mut results=Vec::new();
        for item in items{
            let mut options=v["defaults"].as_object().cloned().unwrap_or_default();options.extend(item.as_object().ok_or("invalid world pose item")?.clone());let item=Value::Object(options);
            if item["world_instance"]!=true{return Err("batch pose requires a world instance".into());}
            let path=self.path(&item)?;results.push(self.sample_model(&path,&item)?);
            if self.blob.len()>MAX_BLOB{return Err("world pose output capacity exceeded".into());}
        }
        return Ok(json!({"models":results,"blob_kind":"world_poses","blob_bytes":self.blob.len()}));
    }
    if v["op"]=="mount_chain"{
        let p=Path::new(text(&v,"path")?);let path=if p.is_absolute(){p.to_path_buf()}else{self.root.join(p)}.canonicalize().map_err(error)?;
        if !path.starts_with(&self.root)||!path.is_dir(){return Err("archive chain outside permitted root".into());}
        let mut count=0;let mut size=0u64;let mut files=Vec::new();
        for entry in std::fs::read_dir(&path).map_err(error)?{
            let candidate=entry.map_err(error)?.path();
            if candidate.extension().is_some_and(|x|x.eq_ignore_ascii_case("mpq")){
                let real=candidate.canonicalize().map_err(error)?;
                if !real.starts_with(&self.root)||!real.is_file(){return Err("archive chain file outside permitted root".into());}
                count+=1;size+=real.metadata().map_err(error)?.len();
                if count>32||size>16*1024*1024*1024{return Err("archive chain capacity exceeded".into());}
                files.push(real);
            }
        }
        let mpq_envelopes=mpq_envelope::mount(&files)?;let chain=engine_formats_core::Chain::open(&path).map_err(error)?;let game_data=self.game_data.remounted()?;
        self.navigation=None;self.audio_files.clear();self.weather_checkpoint=None;self.collision_stage=None;self.skyboxes.clear();self.chain=Some(chain);self.mpq_envelopes=mpq_envelopes;self.game_data=game_data;self.chain_files=files;self.wdl=None;self.weather=Default::default();self.entity_audio=Default::default();self.sound_kits=None;self.area_sounds=None;self.wmo_areas=None;self.sound_providers=None;self.characters=None;self.creatures=None;self.lights=None;self.clouds=Default::default();self.celestial=Default::default();
        return Ok(json!({"format":"MPQ_CHAIN","candidate_archives":count,"priority":"original vanilla patch chain"}));
    }
    if v["op"]=="chain_list"{
        let chain=self.chain.as_ref().ok_or("archive chain not mounted")?;let mut total=0usize;
        // The original listing reads each archive's listfile. Bound its inflated input first.
        for path in &self.chain_files{
            if let Ok(archive)=engine_mpq::Archive::open(path){
                let size=archive.file_size("(listfile)").unwrap_or(0) as usize;total+=size;
                if size>1024*1024||total>MAX_BLOB{return Err("archive listing capacity exceeded".into());}
            }
        }
        let entries=chain.list().map_err(error)?;
        if entries.len()>16384||entries.iter().any(|e|e.name.len()>1024){return Err("archive listing capacity exceeded".into());}
        return Ok(json!(entries.into_iter().map(|e|json!({"name":e.name,"size":e.size})).collect::<Vec<_>>()));
    }
    if v["op"]=="chain_read"{
        let chain=self.chain.as_ref().ok_or("archive chain not mounted")?;let name=text(&v,"entry")?;
        let archive=chain.archive_for(name).map_err(error)?;
        if archive.file_size(name).ok_or("MPQ entry not found")? as usize>MAX_BLOB{return Err("archive entry capacity exceeded".into());}
        self.blob=chain.read(name).map_err(error)?;
        return Ok(json!({"format":"MPQ_CHAIN_ENTRY","entry":name,"archive":archive.path().file_name().and_then(|x|x.to_str()),"blob_kind":"archive_entry","blob_bytes":self.blob.len()}));
    }
    if v["op"]=="sound_kit"{
        self.ensure_sound_kits()?;
        let cat=self.sound_kits.as_ref().unwrap();
        let kit=if let Some(id)=v["kit"].as_u64(){cat.get(id.try_into().map_err(error)?)}else{cat.by_name(text(&v,"kit")?)}.ok_or("unknown sound kit")?;
        return Ok(json!({"id":kit.id,"name":kit.name,"files":kit.files,"volume":kit.volume,"flags":kit.flags,"sound_type":kit.sound_type,"near":kit.min_distance,"far":kit.distance_cutoff,"eax":kit.eax_def}));
    }
    if v["op"]=="creature_voice"{return self.creature_voice(&v);}
    if v["op"]=="gameobject_audio"{return self.gameobject_audio(&v);}
    if v["op"]=="footstep_audio"{return self.footstep_audio(&v);}
    if v["op"]=="material_audio"{return self.material_audio(&v);}
    if v["op"]=="combat_audio"{return self.combat_audio(&v);}
    if v["op"]=="world_navigation"{return self.world_navigation(&v);}
    if matches!(v["op"].as_str(),Some("game_data_classes"|"game_data_skills"|"game_data_talents"|"game_data_spells"|"game_data_triggers")){return self.game_data(&v);}
    if v["op"]=="area_audio"{return self.area_audio(&v);}
    if v["op"]=="sound_beds"{return self.sound_beds();}
    if v["op"]=="audio_provider"{return self.audio_provider(&v);}
    if v["op"]=="macro_icons"{
        // Reuse the listing's inflated-size checks before the original loader.
        self.request(json!({"op":"chain_list"}))?;
        let icons=engine_formats_core::load_macro_icons(self.chain.as_mut().ok_or("archive chain not mounted")?).map_err(error)?;
        if icons.len()>4096||icons.iter().any(|s|s.len()>512){return Err("macro icon capacity exceeded".into());}
        return Ok(json!(icons));
    }
    if v["op"]=="archive_audio_probe"||v["op"]=="archive_audio_open"{
        let entry=text(&v,"entry")?;
        if entry.is_empty()||entry.len()>512||!matches!(entry.rsplit('.').next().unwrap_or("").to_ascii_lowercase().as_str(),"wav"|"mp3"|"ogg"){return Err("invalid archive audio entry".into());}
        let file=self.chain.as_ref().ok_or("archive chain not mounted")?.archive_for(entry).map_err(error)?.open_file(entry).map_err(error)?;
        let size=file.size();if size==0||size>512*1024*1024{return Err("archive audio size capacity exceeded".into());}
        if v["op"]=="archive_audio_probe"{return Ok(json!({"size":size}));}
        if self.audio_files.len()>=8{return Err("archive audio handle capacity exceeded".into());}
        let id=self.next_audio_file;self.next_audio_file=id.checked_add(1).ok_or("archive audio generation exhausted")?;
        self.audio_files.insert(id,file);return Ok(json!({"id":id,"size":size}));
    }
    if v["op"]=="archive_audio_close"{let id=v["id"].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid archive audio handle")?;self.audio_files.remove(&id);return Ok(Value::Null);}
    if v["op"]=="archive_audio_read"{
        use std::io::{Read,Seek,SeekFrom};
        let id=v["id"].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid archive audio handle")?;
        let file=self.audio_files.get_mut(&id).ok_or("archive audio handle unavailable")?;
        let position=v["position"].as_u64().filter(|&n|n<=file.size()).ok_or("invalid archive audio position")?;
        let limit=v["limit"].as_u64().filter(|&n|n>0&&n<=65536).ok_or("archive audio read capacity exceeded")? as usize;
        file.seek(SeekFrom::Start(position)).map_err(error)?;self.blob.resize(limit.min((file.size()-position) as usize),0);
        let count=file.read(&mut self.blob).map_err(error)?;self.blob.truncate(count);let next=position+count as u64;
        return Ok(json!({"position":next,"eof":next==file.size(),"blob_kind":"archive_audio","blob_bytes":count}));
    }
    if v["op"]=="skybox_unload"{let path=self.path(&v)?;self.skyboxes.remove(&path);return Ok(Value::Null);}
    if v["op"]=="skybox"{
        let path=self.path(&v)?;
        if !self.skyboxes.contains_key(&path){
            if self.skyboxes.len()>=8||path.metadata().map_err(error)?.len()>MAX_FILE as u64{return Err("skybox source/cache capacity exceeded".into());}
            let sky=skybox::Skybox::new(std::fs::read(&path).map_err(error)?,path.parent().unwrap().to_str().ok_or("invalid skybox directory")?)?;
            if self.skyboxes.values().map(|s|s.bytes).sum::<usize>()+sky.bytes>32*1024*1024{return Err("skybox residency capacity exceeded".into());}
            self.skyboxes.insert(path.clone(),sky);
        }
        return self.skyboxes[&path].sample(&v,&mut self.blob);
    }
    if v["op"]=="sky_stars"{
        let model=if v["path"].is_string(){let path=self.path(&v)?;if path.metadata().map_err(error)?.len()>MAX_FILE as u64{return Err("star source capacity exceeded".into());}Some(runtime::Model::new(std::fs::read(&path).map_err(error)?,path.parent().unwrap().to_str().ok_or("invalid star directory")?)?)}else{None};
        return sky_art::stars(model.as_ref(),&mut self.blob);
    }
    if v["op"]=="atmosphere"{
        if self.lights.is_none(){self.lights=Some(lighting::load(self.chain.as_mut().ok_or("lighting requires a mounted asset chain")?)?);}
        let mut light=lighting::sample(self.lights.as_ref().unwrap(),&v)?;
        if v["clouds"]==true{self.clouds.sample(&mut light,&v,&mut self.blob)?;}self.celestial.sample(&mut light,&v)?;return Ok(light);
    }
    if v["op"]=="creature_display"{
        if self.creatures.is_none(){self.creatures=Some(creatures::load(self.chain.as_mut().ok_or("creature display requires a mounted asset chain")?)?);}
        let id=v["display_id"].as_u64().and_then(|i|u32::try_from(i).ok()).ok_or("invalid creature display id")?;
        return creatures::display(self.creatures.as_ref().unwrap(),id);
    }
    if v["op"]=="character"{
        let chain=self.chain.as_mut().ok_or("character composition requires a mounted asset chain")?;
        if self.characters.is_none(){self.characters=Some(character::Catalog::load(chain)?);}
        return self.characters.as_mut().unwrap().compose(chain,&v["character"],&mut self.blob);
    }
    if v["op"]=="bind_effect_models"{
        let path=self.path(&v)?;let allowed=self.models.get(&path).ok_or("M2 runtime model not loaded")?.particle_dependencies();
        let bindings=v["bindings"].as_object().filter(|b|b.len()<=32).ok_or("particle binding capacity exceeded")?;let mut resolved=std::collections::HashMap::new();
        for (name,target) in bindings{if !allowed.contains(name){return Err("unknown particle dependency".into());}let p=self.path(&json!({"path":target}))?;self.ensure_model(&p)?;self.dependency_models.insert(p.clone());resolved.insert(name.clone(),p);}
        self.bindings.insert(path.clone(),resolved);self.effects.retain(|_,(p,_)|p!=&path);return Ok(Value::Null);
    }
    if v["op"]=="release_collision"{self.collisions.remove(text(&v,"key")?);return Ok(Value::Null);}
    if v["op"]=="collision_move"{
        let from=text(&v,"from")?;let to=text(&v,"to")?;
        if from.is_empty()||to.is_empty()||from.len()>128||to.len()>128{return Err("invalid collision page key".into());}
        let page=self.collisions.remove(from).ok_or("collision source missing")?;self.collisions.insert(to.into(),page);return Ok(Value::Null);
    }
    if v["op"]=="release_instance"{let key=text(&v,"instance")?;self.effects.remove(key);self.collisions.remove(key);return Ok(Value::Null);}
    if v["op"]=="unload"{let p=Path::new(text(&v,"path")?);let key=if p.is_absolute(){p.to_path_buf()}else{self.root.join(p)};if self.models.get(&key).is_none_or(|m|Arc::strong_count(m)==1){self.models.remove(&key);}self.bindings.remove(&key);self.effects.retain(|_,(path,_)|path!=&key);
        self.models.retain(|p,m|!self.dependency_models.contains(p)||Arc::strong_count(m)>1||self.effects.values().any(|(source,_)|source==p)||self.bindings.values().any(|b|b.values().any(|source|source==p)));
        self.dependency_models.retain(|p|self.models.contains_key(p));return Ok(Value::Null);}
    let path=self.path(&v)?;let ext=path.extension().and_then(|x|x.to_str()).unwrap_or("").to_ascii_lowercase();
    if v["op"]=="pose"{
        return self.sample_model(&path,&v);
    }
    if ext=="mpq"{
        let archive=engine_mpq::Archive::open(&path).map_err(error)?;let name=text(&v,"entry")?;
        if archive.is_delete_marker(name){return Ok(json!({"format":"MPQ","deleted":true}));}
        if archive.file_size(name).ok_or("MPQ entry not found")? as usize>MAX_BLOB{return Err("archive entry capacity exceeded".into());}
        self.blob=archive.read_file(name).map_err(error)?;
        return Ok(json!({"format":"MPQ","entry":name,"blob_kind":"archive_entry","blob_bytes":self.blob.len()}));
    }
    if path.metadata().map_err(error)?.len()>MAX_FILE as u64{return Err("asset file capacity exceeded".into());}
    let bytes=std::fs::read(&path).map_err(error)?;let mut cursor=Cursor::new(bytes.as_slice());
    if v["world_scene"]==true||v["op"]=="wmo_directory"{
        if v["runtime"]==true&&matches!(ext.as_str(),"m2"|"mdx"){
            if !self.models.get(&path).is_some_and(|m|m.same_file(&bytes)){
                if !self.models.contains_key(&path)&&self.models.len()>=MAX_MODELS{return Err("M2 runtime model capacity exceeded".into());}
                if self.models.iter().filter(|(p,_)|*p!=&path).map(|(_,m)|m.source_bytes()).sum::<usize>()+bytes.len()>64*1024*1024{return Err("M2 source cache capacity exceeded".into());}
                self.effects.retain(|_,(source,_)|source!=&path);
                self.models.insert(path.clone(),Arc::new(runtime::Model::new(bytes.clone(),path.parent().unwrap().to_str().ok_or("invalid model directory")?)?));
            }
            let options=v.clone();
            let sampled=self.sample_model(&path,&options)?;
            let result=scene::m2_page(&bytes,&v,sampled,&mut self.blob)?;return self.world_result(result,&v);
        }
        let mut options=v.clone();if v["op"]=="wmo_directory"{options["directory_only"]=json!(true);}
        let entry=options["archive_entry"].as_str();let chain=self.chain.as_ref();let root=&self.root;
        let mut headers=|path:&Path,group:u32|wmo_directory::read(root,path,group,entry,chain);
        let result=scene::decode(&self.root,&path,&bytes,&options,&mut self.blob,&mut headers)?;return self.world_result(result,&options);
    }
    match ext.as_str(){
      "blp"=>{
        if bytes.len()<20{return Err("truncated BLP".into());}
        let width=u32::from_le_bytes(bytes[12..16].try_into().unwrap());let height=u32::from_le_bytes(bytes[16..20].try_into().unwrap());
        if width as u64*height as u64*4>MAX_BLOB as u64{return Err("texture pixel capacity exceeded".into());}
        let decoded=engine_blp::decode_native(&bytes).map_err(error)?;let level=v["mip"].as_u64().unwrap_or(0) as usize;
        if v["mip_chain"]==true {
            if decoded.mips.is_empty()||decoded.mips.len()>16{return Err("invalid BLP mip count".into());}
            let mut levels=Vec::new();let mut blob=Vec::new();
            for (index,mip) in decoded.mips.iter().enumerate(){
                let size=mip.width as u64*mip.height as u64*4;
                if size>MAX_BLOB as u64||blob.len() as u64+size>MAX_BLOB as u64{return Err("texture mip capacity exceeded".into());}
                let pixels=engine_blp::decode_level(decoded.texels,mip.width,mip.height,&mip.bytes);
                if pixels.len() as u64!=size{return Err("invalid BLP mip pixels".into());}
                levels.push(json!({"mip":index,"width":mip.width,"height":mip.height,"offset":blob.len(),"bytes":pixels.len()}));blob.extend_from_slice(&pixels);
            }
            self.blob=blob;
            return Ok(json!({"format":"BLP2_MIP_CHAIN","width":decoded.mips[0].width,"height":decoded.mips[0].height,"levels":levels,
                "mip_count":levels.len(),"blob_kind":"rgba_mips","blob_bytes":self.blob.len()}));
        }
        let mip=decoded.mips.get(level).ok_or("missing BLP mip")?;
        if mip.width as u64*mip.height as u64*4>MAX_BLOB as u64{return Err("texture pixel capacity exceeded".into());}
        self.blob=engine_blp::decode_level(decoded.texels,mip.width,mip.height,&mip.bytes);
        Ok(json!({"format":"BLP2","width":mip.width,"height":mip.height,"mip":level,"mip_count":decoded.mips.len(),"encoding":format!("{:?}",decoded.texels),"blob_kind":"rgba","blob_bytes":self.blob.len()}))
      },
      "tga"=>{
        if bytes.len()<18{return Err("truncated TGA".into());}
        let w=u16::from_le_bytes([bytes[12],bytes[13]]) as usize;let h=u16::from_le_bytes([bytes[14],bytes[15]]) as usize;
        if w*h*4>MAX_BLOB{return Err("texture pixel capacity exceeded".into());}
        let (w,h,rgba)=tga::tga_to_rgba(&bytes).map_err(error)?;self.blob=rgba;
        Ok(json!({"format":"TGA","width":w,"height":h,"blob_kind":"rgba","blob_bytes":self.blob.len()}))
      },
      "m2"|"mdx"=>{
        if v["runtime"]==true{
            if self.models.len()>=MAX_MODELS && !self.models.contains_key(&path){return Err("M2 runtime model capacity exceeded".into());}
            if self.models.get(&path).is_some_and(|model|model.same_file(&bytes)){return self.sample_model(&path,&v);}
            if !self.models.contains_key(&path)&&self.models.len()>=MAX_MODELS{return Err("M2 model capacity exceeded".into());}
            self.effects.retain(|_,(source,_)|source!=&path);
            if self.models.iter().filter(|(p,_)|*p!=&path).map(|(_,m)|m.source_bytes()).sum::<usize>()+bytes.len()>64*1024*1024{return Err("M2 source cache capacity exceeded".into());}
            let model=runtime::Model::new(bytes,path.parent().unwrap().to_str().ok_or("invalid model directory")?)?;
            self.models.insert(path.clone(),Arc::new(model));return self.sample_model(&path,&v);
        }
        let parsed=engine_m2::parse_m2(&mut cursor).map_err(error)?;let model=parsed.model();
        let textures:Vec<Value>=model.textures.iter().map(|t|json!({"path":t.filename.string.to_string_lossy(),"wrap_u":t.wrap_x,"wrap_v":t.wrap_y,"replaceable":t.texture_type!=engine_m2::M2TextureType::Hardcoded})).collect();
        let mut out=json!({"format":"M2","textures":textures,"bone_count":model.bones.len(),"camera_count":model.cameras.len(),"attachment_count":model.attachments.len(),"animation_lookup":model.animation_lookup,"geometry":null});
        if v["geometry"]==true{
            let skin=model.parse_embedded_skin(&bytes,v["profile"].as_u64().unwrap_or(0) as usize).map_err(error)?;
            let indices:Vec<u32>=skin.triangles().iter().map(|&i|skin.indices().get(i as usize).copied().map(u32::from).ok_or("invalid skin vertex index")).collect::<Result<_,_>>()?;
            let mut primitives=Vec::new();
            for batch in skin.batches(){
                let section=skin.submeshes().get(batch.skin_section_index as usize).ok_or("invalid M2 section")?;
                let material=model.materials.get(batch.material_index as usize).ok_or("invalid M2 material")?;
                if section.triangle_start as usize+section.triangle_count as usize>indices.len(){return Err("M2 batch outside triangles".into());}
                primitives.push(json!({"start":section.triangle_start,"count":section.triangle_count,"geoset":section.id,"blend":material.blend_mode.bits(),"unlit":material.flags.bits()&1!=0,"two_sided":material.flags.bits()&4!=0,"texture":model.raw_data.texture_lookup_table.get(batch.texture_combo_index as usize),"texture_stages":batch.texture_count}));
            }
            out["geometry"]=geometry(model.vertices.iter().map(|x|vec3(&x.position)).collect(),model.vertices.iter().map(|x|vec3(&x.normal)).collect(),model.vertices.iter().map(|x|[x.tex_coords.x,x.tex_coords.y]).collect(),indices,primitives)?;
        }Ok(out)
      },
      "wmo"=>match engine_wmo::parse_wmo(&mut cursor).map_err(error)?{
          engine_wmo::ParsedWmo::Root(root)=>Ok(json!({"format":"WMO_ROOT","groups":root.n_groups,"textures":root.textures,"materials":root.materials.iter().map(|m|json!({"blend":m.blend_mode,"flags":m.flags,"unlit":m.flags&1!=0,"two_sided":m.flags&4!=0,"texture":m.get_texture1_index(&root.texture_offset_index_map),"ground_type":m.ground_type,"emission":m.sidn_rgb})).collect::<Vec<_>>() })),
          engine_wmo::ParsedWmo::Group(group)=>{
              let mut out=json!({"format":"WMO_GROUP","flags":group.flags,"liquid":group.liquid.is_some(),"geometry":null});
              if v["geometry"]==true{out["geometry"]=geometry(group.vertex_positions.iter().map(|x|[x.x,x.z,-x.y]).collect(),group.vertex_normals.iter().map(|x|[x.x,x.z,-x.y]).collect(),group.texture_coords.iter().map(|x|[x.u,x.v]).collect(),group.vertex_indices.iter().copied().map(u32::from).collect(),group.render_batches.iter().map(|b|json!({"start":b.start_index,"count":b.count,"material":b.material_id})).collect())?;}Ok(out)
          }
      },
      "adt"=>{
          if !bytes.starts_with(b"REVM"){return Err("ADT requires MVER chunk".into());}
          let engine_adt::ParsedAdt::Root(root)=engine_adt::parse_adt(&mut cursor).map_err(error)?;
          Ok(json!({"format":"ADT","textures":root.textures,"models":root.models,"wmos":root.wmos,"doodads":root.doodad_placements.len(),"wmo_placements":root.wmo_placements.len(),"chunks":root.mcnk_chunks.iter().map(|c|json!({"x":c.header.index_x,"y":c.header.index_y,"position":c.header.position,"holes":c.header.holes_low_res,"impassable":c.header.impassable(),"heights":c.heights.as_ref().map(|h|&h.heights),"layer_count":c.layers.as_ref().map(|l|l.layers.len()),"liquids":c.liquids.len()})).collect::<Vec<_>>() }))
      },
      "wdt"=>{
          if !bytes.starts_with(b"REVM"){return Err("WDT requires MVER chunk".into());}
          let file=engine_wdt::WdtReader::new(cursor,engine_wdt::WowVersion::Classic).read().map_err(error)?;
          let tiles:Vec<Value>=(0..64).flat_map(|y|(0..64).map(move|x|(x,y))).filter_map(|(x,y)|file.get_tile(x,y).filter(|t|t.has_adt).map(|_|json!([x,y]))).collect();
          Ok(json!({"format":"WDT","tiles":tiles,"global_wmo":file.global_wmo().map(|w|&w.model),"global_wmo_placement":file.global_wmo().map(|w|json!({"model":w.model,"position":w.position,"rotation":w.rotation,"doodad_set":w.doodad_set,"name_set":w.name_set}))}))
      },
      "dbc"=>{
          let parser=engine_dbc::DbcParser::parse(&mut cursor).map_err(error)?;let h=*parser.header();
          let mut out=json!({"format":"WDBC","records":h.record_count,"fields":h.field_count,"record_bytes":h.record_size,"string_bytes":h.string_block_size});
          if let Some(fields)=v["schema"].as_array(){
              if h.record_count>4096 || h.field_count>64{return Err("DBC record capacity exceeded".into());}
              if fields.len()!=h.field_count as usize{return Err("DBC schema field count mismatch".into());}
              let mut schema=engine_dbc::Schema::new("GG");
              for (i,field) in fields.iter().enumerate(){
                  let kind=match field.as_str(){Some("uint32")=>engine_dbc::FieldType::UInt32,Some("int32")=>engine_dbc::FieldType::Int32,Some("float32")=>engine_dbc::FieldType::Float32,Some("string")=>engine_dbc::FieldType::String,_=>return Err("unknown DBC field type".into())};
                  schema.add_field(engine_dbc::SchemaField::new(i.to_string(),kind));
              }
              let records=parser.with_schema(schema).map_err(error)?.parse_records().map_err(error)?;
              let mut rows=Vec::new();
              for record in records.records(){
                  let mut row=Vec::new();
                  for i in 0..fields.len(){row.push(match record.get_value(i).ok_or("missing DBC value")?{
                      engine_dbc::Value::UInt32(x)=>json!(x),engine_dbc::Value::Int32(x)=>json!(x),
                      engine_dbc::Value::Float32(x)=>{if !x.is_finite(){return Err("non-finite DBC value".into());}json!(x)},
                      engine_dbc::Value::StringRef(x)=>{let s=records.get_string(*x).map_err(error)?;if s.len()>4096{return Err("DBC string capacity exceeded".into());}json!(s)}
                  });}rows.push(row);
              }
              out["rows"]=json!(rows);
          }else if !v["schema"].is_null(){return Err("invalid DBC schema".into());}Ok(out)
      },
      _=>Err("unsupported native asset extension".into())
    }
 }
}
#[no_mangle] pub extern "C" fn gga_abi_version()->u32{1}
#[no_mangle] pub unsafe extern "C" fn gga_create(root:*const std::ffi::c_char)->*mut std::ffi::c_void{
 if root.is_null(){return std::ptr::null_mut();}
 catch_unwind(||{let path=PathBuf::from(CStr::from_ptr(root).to_str().ok()?).canonicalize().ok()?;if !path.is_dir(){return None;}Some(Box::into_raw(Box::new(Reader{mpq_envelopes:Default::default(),game_data:Default::default(),navigation:None,entity_audio:Default::default(),audio_files:Default::default(),next_audio_file:1,weather_checkpoint:None,collision_stage:None,skyboxes:Default::default(),weather:Default::default(),wdl:None,root:path,response:Vec::new(),blob:Vec::new(),models:Default::default(),collisions:Default::default(),dependency_models:Default::default(),bindings:Default::default(),chain:None,chain_files:Vec::new(),sound_kits:None,area_sounds:None,wmo_areas:None,sound_providers:None,characters:None,creatures:None,lights:None,clouds:Default::default(),celestial:Default::default(),effects:std::collections::HashMap::new()})).cast())}).ok().flatten().unwrap_or(std::ptr::null_mut())
}
#[no_mangle] pub unsafe extern "C" fn gga_destroy(handle:*mut std::ffi::c_void){if !handle.is_null(){drop(Box::from_raw(handle.cast::<Reader>()));}}
#[no_mangle] pub unsafe extern "C" fn gga_request(handle:*mut std::ffi::c_void,data:*const u8,size:usize)->i32{
 if handle.is_null()||data.is_null()||size>65536{return -1;}
 let reader=&mut *handle.cast::<Reader>();reader.blob.clear();
 let result=catch_unwind(AssertUnwindSafe(||serde_json::from_slice(slice::from_raw_parts(data,size)).map_err(error).and_then(|v|reader.request(v))));
 let answer=match result{Ok(Ok(v))=>json!({"ok":true,"result":v}),Ok(Err(e))=>{reader.blob.clear();json!({"ok":false,"error":e})},Err(_)=>{reader.blob.clear();json!({"ok":false,"error":"native asset decoder panic"})}};
 reader.response=serde_json::to_vec(&answer).unwrap_or_default();if reader.response.len()>16*1024*1024{reader.blob.clear();reader.response=b"{\"ok\":false,\"error\":\"asset response capacity exceeded\"}".to_vec();}0
}
#[no_mangle] pub unsafe extern "C" fn gga_response(handle:*mut std::ffi::c_void,size:*mut usize)->*const u8{if handle.is_null()||size.is_null(){return std::ptr::null();}let r=&*handle.cast::<Reader>();*size=r.response.len();r.response.as_ptr()}
#[no_mangle] pub unsafe extern "C" fn gga_blob(handle:*mut std::ffi::c_void,size:*mut usize)->*const u8{if handle.is_null()||size.is_null(){return std::ptr::null();}let r=&*handle.cast::<Reader>();*size=r.blob.len();r.blob.as_ptr()}
