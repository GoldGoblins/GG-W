//! Original CreatureDisplayInfo/ModelData/Extra resolution into the GG host asset contract.
use engine_formats_core::{Chain,CreatureCatalog};
use serde_json::{json,Value};
pub fn load(chain:&mut Chain)->Result<CreatureCatalog,String>{
    for name in ["CreatureModelData","CreatureDisplayInfo","CreatureDisplayInfoExtra"]{
        let path=format!("DBFilesClient\\{name}.dbc");
        if name!="CreatureDisplayInfoExtra"||chain.archive_for(&path).is_ok(){crate::character::bounded(chain,&path).map_err(|e|e.to_string())?;}
    }
    engine_formats_core::load_creature_catalog(chain).map_err(|e|e.to_string())
}
pub fn display(catalog:&CreatureCatalog,id:u32)->Result<Value,String>{
    let model=catalog.model(id).ok_or("unknown creature display")?;
    if !model.scale.is_finite()||model.scale<=0.||model.scale>64.||!model.collision_height.is_finite(){return Err("invalid creature display dimensions".into());}
    let raw=model.model_path.replace('/',"\\");
    if raw.is_empty()||raw.len()>1024{return Err("invalid creature model path".into());}
    let source=if raw.to_ascii_lowercase().ends_with(".mdx"){format!("{}.m2",&raw[..raw.len()-4])}else{raw.clone()};
    let dir=raw.rsplit_once('\\').map_or("",|(dir,_)|dir);
    let mut appearance=json!({"skins":model.textures.map(|name|name.map(|name|format!("{dir}\\{name}.blp")))});
    if let Some(npc)=model.npc_appearance{
        if npc.race==0||npc.sex>1{return Err("invalid creature character appearance".into());}
        // Original char_skin.rs: NPC body slots 2..9, head 0, shoulders 1; no cloak column.
        let mut character=json!({"race":npc.race,"sex":npc.sex,"skin":npc.skin,"face":npc.face,"hair_style":npc.hair_style,"hair_color":npc.hair_color,"facial_hair":npc.facial_hair,"equipment":&npc.equipment[2..],"helmet":npc.equipment[0],"shoulders":npc.equipment[1]});
        if let Some(name)=npc.bake_name{character["baked"]=json!(format!("Textures\\BakedNpcTextures\\{name}"));}
        appearance=json!({"character":character}); // NPCs never consume the Monster skin slots.
    }
    Ok(json!({"format":"CREATURE_DISPLAY","display_id":id,"source":source,"appearance":appearance,"scale":model.scale,"alpha":catalog.display_base_alpha(id).unwrap_or(1.),"collision_height":model.collision_height,"breathes":catalog.breathes(id),"foley_material":catalog.foley_material(id),"size_class":catalog.size_class(id)}))
}
