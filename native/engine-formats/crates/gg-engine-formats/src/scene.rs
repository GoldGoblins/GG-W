//! Retained world pages over the unchanged original terrain and WMO kernels.
use serde_json::{json,Value};
use std::path::Path;
use glam::{Mat4,Vec3,Vec4};
use engine_formats_core::{adt_to_tile_mesh,parse_wmo_root,wmo_group_submeshes,wmo_group_header,wmo_group_liquid_mesh,accumulate_wmo_group_collision,accumulate_wmo_group_camera_collision,accumulate_wmo_group_camera_only_collision,parse_wmo_lights,parse_m2_collision_hull,mcsh_shadowed_at,WmoBatchClass,ModelBlend,LiquidMesh,LiquidKind};
use crate::world_props;

fn triple(v:&Value,default:[f32;3])->Result<[f32;3],String>{
    if v.is_null(){return Ok(default);}let a=v.as_array().filter(|a|a.len()==3).ok_or("invalid world vector")?;
    let mut out=[0.;3];for (o,n) in out.iter_mut().zip(a){*o=n.as_f64().ok_or("invalid world number")? as f32;}
    if out.iter().any(|x|!x.is_finite()||x.abs()>2_000_000.){return Err("world vector capacity exceeded".into());}Ok(out)
}
fn qt(p:[f32;3])->[f32;3]{[p[0],p[2],-p[1]]}
fn vertices(p:&[[f32;3]],n:&[[f32;3]],uv:&[[f32;2]],colors:&[[f32;4]],matrix:Mat4,blob:&mut Vec<u8>)->Result<Value,String>{
    if p.is_empty()||p.len()>65536{return Err("world vertex capacity exceeded".into());}
    let stride=if colors.is_empty(){32}else{48};let offset=blob.len();let mut lo=Vec3::splat(f32::INFINITY);let mut hi=Vec3::splat(f32::NEG_INFINITY);
    if blob.len()+p.len()*stride>8*1024*1024{return Err("world page capacity exceeded".into());}
    for (i,&p) in p.iter().enumerate(){
        let p=Vec3::from_array(qt(matrix.transform_point3(Vec3::from_array(p)).to_array()));
        let n=qt(matrix.inverse().transpose().transform_vector3(Vec3::from_array(n.get(i).copied().unwrap_or([0.,0.,1.]))).normalize_or_zero().to_array());
        let uv=uv.get(i).copied().unwrap_or([0.,0.]);lo=lo.min(p);hi=hi.max(p);
        for x in [p.x,p.y,p.z,n[0],n[1],n[2],uv[0],uv[1]].into_iter().chain(if stride==48{colors.get(i).copied().unwrap_or([1.;4]).to_vec()}else{vec![]}){
            if !x.is_finite(){return Err("non-finite world vertex".into());}blob.extend_from_slice(&x.to_le_bytes());
        }
    }
    Ok(json!({"offset":offset,"vertices":p.len(),"stride":stride,"dynamic":false,"bounds":[lo.to_array(),hi.to_array()],"alpha":1,"tint":[1,1,1],"uv_offset":[0,0],"uv_scale":[1,1],"uv_rotation":[1,0],"wrap_u":true,"wrap_v":true,"vertex_colors":stride==48,"visible":true}))
}
fn box_corners(lo:[f32;3],hi:[f32;3],matrix:Mat4)->Result<Vec<[f32;3]>,String>{
    if lo.iter().chain(hi.iter()).any(|v|!v.is_finite()) || (0..3).any(|i|lo[i]>hi[i]){return Err("invalid WMO group bounds".into());}
    Ok((0..8).map(|mask|qt(matrix.transform_point3(Vec3::from_array(std::array::from_fn(|i|if mask&(1<<i)==0{lo[i]}else{hi[i]}))).to_array())).collect())
}
fn liquid_row(lq:&LiquidMesh,matrix:Mat4,group:Option<u32>,interior:bool,body:[f32;3],floor:Option<f32>,blob:&mut Vec<u8>)->Result<Value,String>{
    let [cols,rows]=lq.grid;
    if cols<2||rows<2||cols as usize*rows as usize!=lq.positions.len()||lq.wet.len()!=(cols as usize-1)*(rows as usize-1)||lq.depths.len()!=lq.positions.len(){return Err("invalid liquid grid".into());}
    let colors:Vec<_>=lq.depths.iter().map(|&d|[body[0],body[1],body[2],d.clamp(0.,1.)]).collect();
    let mut row=vertices(&lq.positions,&[],&lq.uvs,&colors,matrix,blob)?;
    let kind=match lq.kind{LiquidKind::Still=>"STILL",LiquidKind::Rapids=>"RAPIDS",LiquidKind::Ocean=>"OCEAN",LiquidKind::Magma=>"MAGMA",LiquidKind::Slime=>"SLIME"};
    row["indices"]=json!(lq.indices);row["texture"]=Value::Null;row["kind"]=json!("liquid");row["liquid_kind"]=json!(kind);
    row["grid"]=json!(lq.grid);row["wet"]=json!(lq.wet);row["group"]=json!(group);row["pool_floor"]=json!(floor);
    row["liquid_path"]=json!(if group.is_none(){0}else if interior{2}else{1});row["scroll"]=json!(group.is_some()&&matches!(lq.sound_nibble,6|7));
    row["blend"]=json!(if lq.kind.is_fullbright(){0}else{2});row["fullbright"]=json!(lq.kind.is_fullbright());row["interior"]=json!(interior);row["two_sided"]=json!(true);
    Ok(row)
}
pub fn decode(root:&Path,path:&Path,bytes:&[u8],v:&Value,blob:&mut Vec<u8>,header_read:&mut dyn FnMut(&Path,u32)->Result<Vec<u8>,String>)->Result<Value,String>{
    let origin=Vec3::from_array(triple(&v["origin"],[0.;3])?);let mut rows=Vec::new();let mut collision=Vec::new();let mut audio_surfaces=Vec::new();let mut sight=Vec::new();let mut camera_only=Vec::new();let mut groups=Vec::new();let mut placements=Vec::new();let mut props=Vec::new();let mut portals=Value::Null;let mut skybox=Value::Null;let mut fog_records=Value::Null;let mut total=0usize;let limitations:Vec<String>=Vec::new();
    match path.extension().and_then(|s|s.to_str()).unwrap_or("").to_ascii_lowercase().as_str(){
      "adt"=>{
        let tile=adt_to_tile_mesh(bytes).map_err(|e|e.to_string())?;
        if tile.chunks.len()>256||tile.wmos.len()>256||tile.doodads.len()>4096{return Err("world tile capacity exceeded".into());}
        for c in &tile.chunks{
            if c.layer_textures.len()>4{return Err("terrain layer capacity exceeded (4)".into());}
            let mut row=vertices(&c.positions,&c.normals,&c.uvs,&[],Mat4::from_translation(-origin),blob)?;
            row["indices"]=json!(c.indices);row["texture"]=json!(c.base_texture);row["layers"]=json!(c.layer_textures);row["kind"]=json!("terrain");row["area_id"]=json!(c.area_id);row["impassable"]=json!(c.impassable);row["holes"]=json!(c.holes);row["blend"]=json!(0);row["unlit"]=json!(false);row["two_sided"]=json!(false);
            // Retain the exact predominant MCLY effect in every 8x8 cell.
            // Qt +Z is original -Y; +X remains original +X.
            if let Some(nw)=c.positions.first(){
                row["ground_effect_origin"]=json!(qt((Vec3::from_array(*nw)-origin).to_array()));
                row["ground_effect_span"]=json!(engine_formats_core::TILE_SIZE/16.);
                row["ground_effect_ids"]=json!(c.pred_tex.iter().map(|layer|c.layer_effect_ids.get(*layer as usize).copied().filter(|id|*id!=u32::MAX)).collect::<Vec<_>>());
            }
            row["alpha_offset"]=json!(blob.len());
            let alpha=c.alpha_map.clone().unwrap_or(vec![0;64*64*4]);if alpha.len()!=64*64*4{return Err("invalid terrain alpha map".into());}blob.extend_from_slice(&alpha);
            row["shadow_offset"]=json!(blob.len());
            let shadow=c.shadow.clone().unwrap_or(vec![0;64*64]);if shadow.len()!=64*64{return Err("invalid terrain shadow map".into());}
            blob.extend_from_slice(&shadow);
            total+=c.positions.len();rows.push(row);
            for lq in &c.liquids{
                total+=lq.positions.len();rows.push(liquid_row(lq,Mat4::from_translation(-origin),None,false,[1.;3],None,blob)?);
            }
        }
        if tile.doodads.len()>128{return Err("selected ADT prop capacity exceeded (128)".into());}
        for d in &tile.doodads {
            let pos=triple(&json!(d.position),[0.;3])?;let r=triple(&json!(d.rotation),[0.;3])?;
            if !d.scale.is_finite()||d.scale<=0.||d.scale>64.{return Err("invalid MDDF scale".into());}
            let m=Mat4::from_scale_rotation_translation(Vec3::splat(d.scale),world_props::placement(r),Vec3::from_array(pos)-origin);
            let shade=if mcsh_shadowed_at(&tile.chunks,d.position)==Some(true){0.5}else{1.};
            props.push(world_props::prop(&d.model,format!("mddf:{}",d.unique_id),m,vec![],json!({"interior":false,"shade":shade}))?);
        }
        for w in tile.wmos{placements.push(json!({"model":w.model,"position":w.position,"rotation":w.rotation,"id":w.unique_id,"doodad_set":w.doodad_set,"name_set":w.name_set}));}
      },
      "wmo"=>{
        let parsed=parse_wmo_root(bytes).map_err(|e|e.to_string())?;skybox=json!(parsed.skybox());
        let directory=v["directory_only"]==true;
        if parsed.group_count()>1024{return Err("WMO directory group capacity exceeded (1024)".into());}
        let selected=if v["groups_selected"].is_null(){None}else{
            let ids=v["groups_selected"].as_array().filter(|a|!a.is_empty()&&a.len()<=32).ok_or("invalid WMO group window")?;
            let mut chosen=std::collections::BTreeSet::new();
            for id in ids{let id=id.as_u64().filter(|&id|id<u64::from(parsed.group_count())).ok_or("invalid WMO selected group")? as u32;if !chosen.insert(id){return Err("duplicate WMO selected group".into());}}
            Some(chosen)
        };
        if parsed.group_count()>32&&!directory&&selected.is_none(){return Err("WMO world group capacity exceeded (32); select a group window".into());}
        // Same raw placement rotation as GgEngine's coords::placement_rotation;
        // Qt basis is applied afterwards, without passing through Bevy.
        let pos=Vec3::from_array(triple(&v["position"],[0.;3])?);let r=triple(&v["rotation"],[0.,180.,0.])?;
        let q=world_props::placement(r);
        let matrix=Mat4::from_rotation_translation(q,pos-origin);
        if parsed.fogs().len()>512{return Err("WMO fog capacity exceeded".into());}
        let mut records=Vec::new();
        for f in parsed.fogs(){
            if f.pos.iter().chain([f.radius_inner,f.radius_outer,f.fog_end,f.fog_start_scalar].iter()).any(|v|!v.is_finite()){return Err("invalid WMO fog record".into());}
            records.push(json!({"flags":f.flags,"position":qt(matrix.transform_point3(Vec3::from_array(f.pos)).to_array()),"radius_inner":f.radius_inner,"radius_outer":f.radius_outer,"end":f.fog_end,"start_scalar":f.fog_start_scalar,"color":[((f.color>>16)&255) as f32/255.,((f.color>>8)&255) as f32/255.,(f.color&255) as f32/255.]}));
        }
        fog_records=json!(records);
        let lights=parse_wmo_lights(bytes);if lights.len()>512{return Err("MOLT capacity exceeded".into());}
        let mut prop_refs=world_props::WmoProps::new(parsed.doodads().len())?;
        let p=parsed.portals();
        if p.vertices.len()>8192||p.infos.len()>1024||p.refs.len()>4096{return Err("WMO portal capacity exceeded".into());}
        let mut infos=Vec::new();
        for info in &p.infos{
            let start=info.start_vertex as usize;let count=info.count as usize;
            if !(3..=32).contains(&count)||start+count>p.vertices.len()||info.plane.iter().any(|n|!n.is_finite()){return Err("invalid WMO portal polygon".into());}
            let points:Vec<_>=p.vertices[start..start+count].iter().map(|&p|qt(matrix.transform_point3(Vec3::from_array(p)).to_array())).collect();
            let plane=matrix.inverse().transpose()*Vec4::from_array(info.plane);let normal=qt(plane.truncate().to_array());
            if points.iter().flatten().any(|n|!n.is_finite())||!plane.is_finite()||plane.truncate().length()<1e-8{return Err("non-finite WMO portal".into());}
            infos.push(json!({"points":points,"plane":[normal[0],normal[1],normal[2],plane.w]}));
        }
        portals=json!({"infos":infos,"refs":p.refs.iter().map(|r|json!({"portal":r.portal,"group":r.group,"side":r.side})).collect::<Vec<_>>()});
        let mut source_bytes=bytes.len();let mut liquid_owners=crate::liquid_shared::Owners::default();
        for gi in 0..parsed.group_count(){
            if !directory&&selected.as_ref().is_some_and(|ids|!ids.contains(&gi)){continue;}
            let group=path.with_file_name(format!("{}_{gi:03}.wmo",path.file_stem().unwrap().to_string_lossy()));
            let b=if directory{header_read(&group,gi)?}else{
                let group=group.canonicalize().map_err(|e|e.to_string())?;
                if !group.starts_with(root)||!group.is_file(){return Err("WMO group outside permitted root".into());}
                let size=group.metadata().map_err(|e|e.to_string())?.len() as usize;source_bytes+=size;
                if size>16*1024*1024||source_bytes>64*1024*1024{return Err("WMO source capacity exceeded".into());}
                std::fs::read(&group).map_err(|e|e.to_string())?
            };let h=wmo_group_header(&b).ok_or("invalid WMO group header")?;
            prop_refs.group(gi as u16,&b,&lights)?;
            let fog=h.fog_indices.iter().find_map(|&i|parsed.fogs().get(i as usize).filter(|f|f.fog_end.is_finite()&&f.fog_start_scalar.is_finite()&&f.fog_end>0.&&f.fog_end<100000.&&f.fog_start_scalar>=0.&&f.fog_start_scalar<=1.));
            let corners=parsed.group_infos().get(gi as usize).map(|g|box_corners(g.bbox_min,g.bbox_max,matrix)).transpose()?;
            let floor=corners.as_ref().map(|c|c.iter().map(|p|p[1]).fold(f32::INFINITY,f32::min));
            groups.push(json!({"id":gi,"wmo_id":engine_formats_core::wmo_root_id(bytes),"name_set":v["name_set"].as_u64().unwrap_or(0),"group_id":h.area_table_id,"flags":h.flags,"corners":corners,"interior":h.flags&0x48==0,"area_id":h.area_table_id,"portal_start":h.portal_ref_start,"portal_count":h.portal_ref_count,"group_liquid":h.group_liquid,"fog_indices":h.fog_indices,"fog":fog.map(|f|json!({"near":f.fog_end*f.fog_start_scalar,"far":f.fog_end,"color":[((f.color>>16)&255) as f32/255.,((f.color>>8)&255) as f32/255.,(f.color&255) as f32/255.]}))}));
            groups.last_mut().unwrap()["flooded_kind"]=json!(if h.group_liquid==engine_formats_core::NO_GROUP_LIQUID{None}else{LiquidKind::from_nibble(h.group_liquid as u8).map(|kind|format!("{kind:?}").to_ascii_uppercase())});
            if directory{continue;}
            for m in wmo_group_submeshes(&b,&parsed).map_err(|e|e.to_string())?{
                total+=m.positions.len();let mut row=vertices(&m.positions,&m.normals,&m.uvs,&m.vertex_colors,matrix,blob)?;
                let blend=match m.blend{ModelBlend::Opaque=>0,ModelBlend::AlphaTest=>1,ModelBlend::Mod=>5,ModelBlend::Mod2x=>6,_=>2};
                row["indices"]=json!(m.indices);row["texture"]=json!(m.texture);row["kind"]=json!("wmo");row["group"]=json!(gi);row["blend"]=json!(blend);row["interior"]=json!(m.interior);row["unlit"]=json!(m.emissive);row["two_sided"]=json!(m.two_sided);row["wmo_class"]=json!(match m.wmo_batch{Some(WmoBatchClass::Trans)=>1,Some(WmoBatchClass::Int)=>2,_=>0});row["sidn"]=json!(m.sidn);row["window"]=json!(m.window);rows.push(row);
            }
            if let Some(lq)=wmo_group_liquid_mesh(&b){
                let body=lq.material_id.and_then(|i|parsed.material_diff_colors().get(i as usize).copied()).unwrap_or([0.;3]);
                total+=lq.positions.len();let mut row=liquid_row(&lq,matrix,Some(gi),h.flags&0x48==0,body,floor,blob)?;
                row["indices"]=json!(liquid_owners.draw_indices(&lq,gi));row["shared_cells"]=json!(lq.shared);rows.push(row);
            }
            let (audio_points,audio_materials)=crate::entity_audio::wmo_sound_faces(&b,&parsed.material_ground_types())?;
            if !audio_materials.is_empty(){
                let base=vertices(&audio_points,&[],&[],&[],matrix,blob)?;
                for (terrain,indices) in audio_materials{
                    let mut row=base.clone();row["indices"]=json!(indices);row["group"]=json!(gi);row["terrain_id"]=json!(terrain);audio_surfaces.push(row);
                }
            }
            let mut positions=Vec::new();let mut indices=Vec::new();accumulate_wmo_group_collision(&b,&mut positions,&mut indices);
            if !indices.is_empty(){let mut row=vertices(&positions,&[],&[],&[],matrix,blob)?;row["indices"]=json!(indices);row["group"]=json!(gi);collision.push(row);}
            let mut positions=Vec::new();let mut indices=Vec::new();accumulate_wmo_group_camera_collision(&b,&mut positions,&mut indices);
            if !indices.is_empty(){let mut row=vertices(&positions,&[],&[],&[],matrix,blob)?;row["indices"]=json!(indices);row["group"]=json!(gi);sight.push(row);}
            let mut positions=Vec::new();let mut indices=Vec::new();accumulate_wmo_group_camera_only_collision(&b,&mut positions,&mut indices);
            if !indices.is_empty(){let mut row=vertices(&positions,&[],&[],&[],matrix,blob)?;row["indices"]=json!(indices);row["group"]=json!(gi);camera_only.push(row);}
        }
        let set=if v["doodad_set"].is_null(){0}else{v["doodad_set"].as_u64().ok_or("invalid WMO doodad set")?};if set>65535{return Err("invalid WMO doodad set".into());}
        props=if v["skip_props"]==true{Vec::new()}else if directory{prop_refs.finish_limited(&parsed,set as u16,matrix,&lights,4096)?}else{prop_refs.finish(&parsed,set as u16,matrix,&lights)?};
      },
      "m2"|"mdx"=>{
        let model=crate::runtime::Model::new(bytes.to_vec(),path.parent().unwrap().to_str().ok_or("invalid M2 directory")?)?;
        let mut options=v.clone();options["anim_id"]=json!(0);
        let sampled=model.sample(&options,blob)?;
        return m2_page(bytes,v,sampled,blob);
      },
      _=>return Err("world pages require ADT or WMO".into())
    }
    if total>65536||rows.len()>512||audio_surfaces.len()>512||blob.len()>8*1024*1024{return Err("world page capacity exceeded".into());}
    Ok(json!({"format":"WORLD_PAGE","rows":rows,"collision":collision,"audio_surfaces":audio_surfaces,"sight_collision":sight,"camera_only_collision":camera_only,"groups":groups,"portals":portals,"skybox":skybox,"fog_records":fog_records,"placements":placements,"props":props,"limitations":limitations,"blob_kind":"world_page","blob_bytes":blob.len()}))
}

pub fn m2_page(bytes:&[u8],v:&Value,mut sampled:Value,blob:&mut Vec<u8>)->Result<Value,String>{
    let matrix=world_props::matrix(&v["anchor"])?;let mut rows=Vec::new();
    for category in ["rows","effects","ribbons"]{
        let value=if category=="rows"{&mut sampled[category]}else{&mut sampled[category]["rows"]};
        if let Some(array)=value.as_array_mut(){for mut row in array.drain(..){
            row["kind"]=json!("m2");row["stride"]=json!(row["stride"].as_u64().unwrap_or(32));
            row["dynamic"]=json!(row["stride"]==48);if row["visible"].is_null(){row["visible"]=json!(true);}
            row["effect"]=json!(category!="rows");rows.push(row);
        }}
    }
    let hull=parse_m2_collision_hull(bytes).map_err(|e|e.to_string())?;let mut collision=Vec::new();
    if !hull.indices.is_empty(){let mut row=vertices(&hull.positions,&[],&[],&[],matrix,blob)?;row["indices"]=json!(hull.indices);row["kind"]=json!("prop_collision");collision.push(row);}
    let mut limitations=Vec::new();for value in [&sampled["limitations"],&sampled["effects"]["limitations"],&sampled["ribbons"]["limitations"]]{if let Some(array)=value.as_array(){limitations.extend(array.iter().cloned());}}
    if rows.iter().map(|r|r["vertices"].as_u64().unwrap_or(0)).sum::<u64>()>65536||rows.len()>512||blob.len()>8*1024*1024{return Err("world M2 capacity exceeded".into());}
    Ok(json!({"format":"WORLD_PAGE","rows":rows,"collision":collision,"sight_collision":collision,"groups":[],"portals":null,"placements":[],"props":[],"facts":sampled["facts"],"limitations":limitations,"blob_kind":"world_page","blob_bytes":blob.len()}))
}
