//! Original character atlas/geoset selectors behind the bounded GG asset ABI.
use engine_formats_core::{Chain,CharSections,CharacterGeosets,EquipGeosets,ItemDisplayCatalog};
use serde_json::{json,Value};

pub struct Catalog {sections:CharSections,geosets:CharacterGeosets,items:Option<ItemDisplayCatalog>}
pub fn bounded(chain:&Chain,name:&str)->anyhow::Result<()> {
    let size=chain.archive_for(name)?.file_size(name).ok_or_else(||anyhow::anyhow!("missing character asset: {name}"))?;
    anyhow::ensure!(size<=8*1024*1024,"character asset capacity exceeded");Ok(())
}
impl Catalog {
    pub fn load(chain:&mut Chain)->Result<Self,String> {
        for name in ["CharSections","CharHairGeosets","CharacterFacialHairStyles"] {
            bounded(chain,&format!("DBFilesClient\\{name}.dbc")).map_err(|e|e.to_string())?;
        }
        // The original loader permits a missing helmet table. Bound it if present.
        let helm="DBFilesClient\\HelmetGeosetVisData.dbc";
        if chain.archive_for(helm).is_ok(){bounded(chain,helm).map_err(|e|e.to_string())?;}
        Ok(Self{sections:CharSections::load(chain).map_err(|e|e.to_string())?,geosets:CharacterGeosets::load(chain).map_err(|e|e.to_string())?,items:None})
    }
    pub fn compose(&mut self,chain:&mut Chain,v:&Value,blob:&mut Vec<u8>)->Result<Value,String> {
        let byte=|key:&str|->Result<u8,String>{if v[key].is_null(){Ok(0)}else{v[key].as_u64().ok_or_else(||format!("invalid character {key}"))?.try_into().map_err(|_|format!("invalid character {key}"))}};
        let (race,sex,skin,face,facial,hair,color)=(byte("race")?,byte("sex")?,byte("skin")?,byte("face")?,byte("facial_hair")?,byte("hair_style")?,byte("hair_color")?);
        if sex>1 || race==0{return Err("invalid character race/sex".into());}
        let mut ids=[0u32;8];
        if let Some(rows)=v["equipment"].as_array(){
            if rows.len()!=8{return Err("character equipment requires eight display slots".into());}
            for (out,row) in ids.iter_mut().zip(rows){*out=if row.is_null(){0}else{row.as_u64().ok_or("invalid equipment display")?.try_into().map_err(|_|"invalid equipment display")?};}
        }
        let optional_id=|key:&str|->Result<u32,String>{if v[key].is_null(){Ok(0)}else{v[key].as_u64().ok_or_else(||format!("invalid {key} display"))?.try_into().map_err(|_|format!("invalid {key} display"))}};
        let (cloak,helm,shoulders,mainhand,offhand)=(optional_id("cloak")?,optional_id("helmet")?,optional_id("shoulders")?,optional_id("mainhand")?,optional_id("offhand")?);
        let (ranged,ammo,quiver)=(optional_id("ranged")?,optional_id("ammo")?,optional_id("quiver")?);
        let shield=if v["offhand_is_shield"].is_null(){false}else{v["offhand_is_shield"].as_bool().ok_or("invalid offhand kind")?};
        let inventory=|key:&str,default:u32|->Result<u32,String>{let n=if v[key].is_null(){default}else{optional_id(key)?};if n>28{return Err(format!("invalid {key}"));}Ok(n)};
        let main_inv=inventory("mainhand_inv_type",13)?;
        let off_inv=inventory("offhand_inv_type",if shield{14}else{13})?;
        let ranged_inv=inventory("ranged_inv_type",15)?;
        let bounded_byte=|key:&str,default:u8,limit:u8|->Result<u8,String>{let n=if v[key].is_null(){default}else{byte(key)?};if n>limit{return Err(format!("invalid {key}"));}Ok(n)};
        // Legacy appearance calls drew both melee hands. Explicit state uses
        // the original 0=stowed, 1=melee, 2=ranged and per-arm ceremony state.
        let sheath=bounded_byte("sheath",1,2)?;
        let visual=if let Some(rows)=v["visual_sheath"].as_array(){
            if rows.len()!=2{return Err("visual sheath requires two arms".into());}
            let mut state=[0u8;2];for (out,row) in state.iter_mut().zip(rows){*out=row.as_u64().filter(|&n|n<=2).ok_or("invalid visual sheath")? as u8;}state
        }else if v["visual_sheath"].is_null(){[sheath;2]}else{return Err("invalid visual sheath".into());};
        let main_sheath=bounded_byte("mainhand_sheath",0,4)?;
        let off_sheath=bounded_byte("offhand_sheath",if shield{4}else{0},4)?;
        let nocked=if v["nocked"].is_null(){false}else{v["nocked"].as_bool().ok_or("invalid nocked ammo state")?};
        let shown=|key:&str|->Result<bool,String>{if v[key].is_null(){Ok(true)}else{v[key].as_bool().ok_or_else(||format!("invalid {key}"))}};
        let helm=if shown("show_helm")?{helm}else{0};let cloak=if shown("show_cloak")?{cloak}else{0};
        if ids.iter().any(|&i|i!=0)||[cloak,helm,shoulders,mainhand,offhand,ranged,ammo,quiver].iter().any(|&i|i!=0){
            if self.items.is_none(){bounded(chain,"DBFilesClient\\ItemDisplayInfo.dbc").map_err(|e|e.to_string())?;self.items=Some(engine_formats_core::load_item_display_catalog(chain).map_err(|e|e.to_string())?);}
            for id in ids.iter().copied().chain([cloak,helm,shoulders,mainhand,offhand,ranged,ammo,quiver]).filter(|&i|i!=0){if self.items.as_ref().unwrap().get(id).is_none(){return Err(format!("unknown equipment display: {id}"));}}
        }
        let item=|id:u32|self.items.as_ref().and_then(|c|c.get(id));
        let equipment=ids.map(item);let preview=if v["tabard_preview"].is_null(){false}else{v["tabard_preview"].as_bool().ok_or("invalid tabard preview")?};
        let emblem=if v["emblem"].is_object(){
            let e=&v["emblem"];let n=|k:&str|e[k].as_i64().filter(|&n|(-1..=255).contains(&n)).map(|n|n as i32).ok_or_else(||format!("invalid emblem {k}"));
            Some(engine_formats_core::GuildEmblem{emblem_style:n("emblem_style")?,emblem_color:n("emblem_color")?,border_style:n("border_style")?,border_color:n("border_color")?,background_color:n("background_color")?})
        }else{None};
        let mut missing=Vec::new();let mut loaded=Vec::new();let mut total=0usize;
        let mut read_texture=|name:&str|{
            let result=(||{
                bounded(chain,name)?;let data=chain.read(name)?;
                anyhow::ensure!(data.len()>=20,"truncated character texture");
                let w=u32::from_le_bytes(data[12..16].try_into().unwrap());let h=u32::from_le_bytes(data[16..20].try_into().unwrap());
                anyhow::ensure!(w>0&&h>0&&w as u64*h as u64<=2*1024*1024,"character texture pixel capacity exceeded");
                let texture=engine_formats_core::blp_bytes_to_mip_chain(&data)?;
                total+=texture.mips.iter().map(Vec::len).sum::<usize>();anyhow::ensure!(total<=32*1024*1024,"character composition capacity exceeded");Ok(texture)
            })();
            if result.is_err(){missing.push(name.to_owned());}else{loaded.push(name.to_owned());}result
        };
        let atlas=if !v["baked"].is_null(){
            let name=v["baked"].as_str().filter(|s|!s.is_empty()&&s.len()<=1024).ok_or("invalid baked character texture")?;
            read_texture(name).map_err(|e|format!("{e:#}"))?
        }else{
            self.sections.composite_plan(race,sex,skin,face,facial,hair,color,equipment,emblem,preview).ok_or("character skin section unavailable")?.run(read_texture).map_err(|e|format!("{e:#}"))?
        };
        let family=|name:&str|{let mut name=name.replace('\\',"/").to_ascii_lowercase();for sex in ["_u.blp","_m.blp","_f.blp"]{if name.ends_with(sex){name.truncate(name.len()-6);break;}}name};
        missing.retain(|name|!loaded.iter().any(|found|family(found)==family(name)));
        let eq=EquipGeosets{bodyslots:equipment.map(|i|i.map(|i|i.geoset_groups)),cloak:item(cloak).map(|i|i.geoset_groups[0]),helm_vis:item(helm).and_then(|i|i.worn_helm_vis()),forearm_dressed:engine_formats_core::forearm_dressed(&equipment),tabard_preview:preview};
        let visible=self.geosets.visible_geosets(race,sex,hair,facial,&eq);
        let selected:Vec<u16>=(0..=1700).filter(|id|visible.contains(id)).collect();
        let object=item(cloak).and_then(|i|i.model_texture[0].as_ref()).map(|name|format!("Item\\ObjectComponents\\Cape\\{name}.blp"));
        let mut limitations=Vec::new();
        if equipment.into_iter().flatten().any(|i|i.model.iter().any(Option::is_some)){limitations.push("Equipment model attachments require a character attachment renderer");}
        if atlas.mips.len()>1 && v["mip_chain"]!=true{limitations.push("Base-only character atlas was requested");}
        // Path/column selection adapted from upstream entities/equipment/mod.rs,
        // ensure_item_model (MIT OR Apache-2.0). Texture identity is independent.
        let mut attachments=Vec::new();
        let ranged_drawn=visual[crate::equipment::arm(2,ranged_inv)]==2;
        let mut parts=vec![(helm,"Head",0,Some(11),None),(shoulders,"Shoulder",0,Some(6),None),(shoulders,"Shoulder",1,Some(5),None),
            (mainhand,"Weapon",0,crate::equipment::placement(0,main_inv,main_sheath,visual[0]),None),
            (offhand,if off_inv==14{"Shield"}else{"Weapon"},0,crate::equipment::placement(1,off_inv,off_sheath,visual[1]),None),
            (ranged,"Weapon",0,crate::equipment::placement(2,ranged_inv,0,visual[crate::equipment::arm(2,ranged_inv)]),None)];
        if ranged_drawn && ranged!=0 {
            if ranged_inv==15 && nocked{
                let (dir,col)=if item(ammo).is_some_and(|d|d.model[0].is_some()) {("Weapon",0)} else {("Ammo",1)};
                parts.push((ammo,dir,col,Some(35),None));
            }
            // Logical slots can share an authored joint: a stowed two-hander
            // and the private quiver both own attachment 26.
            parts.push((quiver,"Quiver",0,Some(26),Some("quiver")));
        }
        for (display,dir,col,slot,key) in parts{
            let Some(slot)=slot else{continue;};
            if let Some(d)=item(display){if let Some(model)=&d.model[col]{
                let model=if dir=="Head"{let prefixes=["Hu","Or","Dw","Ni","Sc","Ta","Gn","Tr"];format!("{}_{}{}.m2",model.strip_suffix(".m2").unwrap_or(model),prefixes[(race.clamp(1,8)-1) as usize],if sex==1{"F"}else{"M"})}else{model.clone()};
                let root=format!("Item\\ObjectComponents\\{dir}");
                let mut row=json!({"id":slot,"model":format!("{root}\\{model}"),"object":d.model_texture[col].as_ref().map(|t|format!("{root}\\{t}.blp")),"display":display});
                if let Some(key)=key{row["key"]=json!(key);}attachments.push(row);
            }}
        }
        let mut levels=Vec::new();blob.clear();
        for (i,pixels) in atlas.mips.iter().enumerate().take(if v["mip_chain"]==true{16}else{1}){
            let (w,h)=((atlas.width>>i).max(1),(atlas.height>>i).max(1));
            if pixels.len()!=w as usize*h as usize*4||blob.len()+pixels.len()>16*1024*1024{return Err("invalid character atlas pixels".into());}
            levels.push(json!({"mip":i,"width":w,"height":h,"offset":blob.len(),"bytes":pixels.len()}));blob.extend_from_slice(pixels);
        }
        if levels.is_empty(){return Err("empty character atlas".into());}
        Ok(json!({"format":"CHARACTER_ATLAS","blob_kind":if v["mip_chain"]==true{"rgba_mips"}else{"rgba8"},"blob_bytes":blob.len(),"width":atlas.width,"height":atlas.height,"levels":levels,"authored_mips":atlas.mips.len(),"attachments":attachments,"geosets":selected,"hair":self.sections.hair_mesh_texture(race,sex,hair,color),"skin_extra":self.sections.skin_extra_texture(race,sex,skin),"missing_candidates":missing,"object":object,"limitations":limitations}))
    }
}
