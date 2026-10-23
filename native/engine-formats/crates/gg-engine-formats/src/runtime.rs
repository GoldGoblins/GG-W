//! GG runtime over the original skeleton, sequence, material and camera parsers.
use engine_bytes::ByteExt;
use engine_formats_core::{ModelAnimation, GlobalSeqBone, RenderSubmesh};
use glam::{Mat4,Vec3,Vec4,Quat};
use serde_json::{json,Value};
pub struct Model {
    pub ribbons:Vec<engine_formats_core::RibbonEmitterDef>,
    pub emitters:Vec<engine_formats_core::ParticleEmitterDef>, pub particle_blends:Vec<u8>,
    file:Vec<u8>, format:engine_m2::M2Format,
    clips:Vec<ModelAnimation>, globals:Vec<GlobalSeqBone>,
    meshes:Vec<RenderSubmesh>, raw_blends:Vec<u16>, cameras:Vec<engine_formats_core::M2PaneCamera>,
}
fn basis(v:[f32;3])->[f32;3]{[v[0],v[2],-v[1]]}
fn interp<const N:usize>(keys:&[(f32,[f32;N])],t:f32,step:bool,default:[f32;N])->[f32;N]{
    if keys.is_empty(){return default;}
    let i=keys.partition_point(|(ts,_)|*ts<=t).saturating_sub(1);let (ta,a)=keys[i];
    if step || i+1==keys.len(){return a;}
    let (tb,b)=keys[i+1];let f=if tb>ta{((t-ta)/(tb-ta)).clamp(0.,1.)}else{0.};
    std::array::from_fn(|i|a[i]+(b[i]-a[i])*f)
}
fn rotation(keys:&[(f32,[f32;4])],t:f32,step:bool,default:[f32;4])->[f32;4]{
    if keys.is_empty(){return default;}
    let i=keys.partition_point(|(ts,_)|*ts<=t).saturating_sub(1);let (ta,a)=keys[i];
    if step || i+1==keys.len(){return a;}
    let (tb,b)=keys[i+1];let f=if tb>ta{((t-ta)/(tb-ta)).clamp(0.,1.)}else{0.};
    let a=Quat::from_array(a);let b=Quat::from_array(b);
    if a.length_squared()<1e-12 || b.length_squared()<1e-12{return default;}
    a.normalize().slerp(b.normalize(),f).to_array()
}
impl Model {
    pub(crate) fn particle_forms(&self)->(&[RenderSubmesh],&[u16]){(&self.meshes,&self.raw_blends)}
    pub(crate) fn particle_dependencies(&self)->Vec<String>{
        let mut names=Vec::new();
        for def in &self.emitters{for name in [&def.geometry_model,&def.recursion_model].into_iter().flatten(){if !names.contains(name){names.push(name.clone());}}}
        names
    }
    pub fn source_bytes(&self)->usize{self.file.len()}
    pub fn same_file(&self,bytes:&[u8])->bool{self.file==bytes}
    pub fn new(bytes:Vec<u8>,dir:&str)->Result<Self,String>{
        let bones=bytes.u32_at(0x34).ok_or("truncated M2 runtime header")?;
        let clips=bytes.u32_at(0x1c).ok_or("truncated M2 sequences")?;
        if bones>256 || clips>128{return Err("M2 runtime bone/sequence capacity exceeded".into());}
        let format=engine_m2::parse_m2(&mut std::io::Cursor::new(bytes.as_slice())).map_err(|e|e.to_string())?;
        if format.model().header.bounding_box_min.iter().chain(format.model().header.bounding_box_max.iter()).any(|v|!v.is_finite()){return Err("non-finite M2 bounds".into());}
        let skin=format.model().parse_embedded_skin(&bytes,0).map_err(|e|e.to_string())?;
        if skin.triangles().iter().any(|&i|skin.indices().get(i as usize).is_none_or(|&j|j as usize>=format.model().vertices.len())){return Err("invalid M2 runtime skin vertex".into());}
        let mut triangles=0usize;
        for batch in skin.batches(){triangles+=skin.submeshes().get(batch.skin_section_index as usize).ok_or("invalid M2 section")?.triangle_count as usize;}
        if triangles>393216{return Err("M2 runtime batch capacity exceeded".into());}
        let meshes=engine_formats_core::parse_m2_render_submeshes(&bytes,dir,&[]).map_err(|e|e.to_string())?;
        if meshes.len()>512 || meshes.iter().map(|m|m.positions.len()).sum::<usize>()>65536{return Err("M2 runtime vertex capacity exceeded".into());}
        // Original geometry can split one batch into rigid cards. Consume its triangle
        // count to keep the original 3/4 additive distinction for every split.
        let mut raw_blends=Vec::new();let mut at=0;
        for batch in skin.batches(){
            let section=&skin.submeshes()[batch.skin_section_index as usize];
            let constant=|track:Option<&engine_m2::M2ScalarTrack>|track.and_then(|t|t.constant()).unwrap_or(1.);
            let m=format.model();let color=constant(m.color_alpha_tracks.get(batch.color_index as usize));
            let weight=if batch.texture_count==0{1.}else{constant(m.transparency_lookup.get(batch.weight_combo_index as usize).and_then(|&i|m.transparency_tracks.get(i as usize)))};
            if color*weight<=0. || section.triangle_count==0{continue;}
            let blend=m.materials.get(batch.material_index as usize).map_or(0,|m|m.blend_mode.bits());
            let mut count=0;
            while at<meshes.len() && count<section.triangle_count as usize{
                if meshes[at].section!=Some(batch.skin_section_index){return Err("M2 batch metadata mismatch".into());}
                count+=meshes[at].indices.len();raw_blends.push(blend);at+=1;
            }
            if count!=section.triangle_count as usize{return Err("M2 batch geometry mismatch".into());}
        }
        if raw_blends.len()!=meshes.len(){return Err("M2 material metadata mismatch".into());}
        let event_count=bytes.u32_at(0x114).unwrap_or(0) as usize;let event_base=bytes.u32_at(0x118).unwrap_or(0) as usize;
        if event_count>256||event_count>0&&event_base.checked_add(event_count*44).is_none_or(|end|end>bytes.len()){return Err("M2 event record capacity/truncation exceeded".into());}
        let mut event_keys=0usize;
        for i in 0..event_count{
            let at=event_base+i*44;let count=bytes.u32_at(at+36).unwrap_or(0) as usize;let offset=bytes.u32_at(at+40).unwrap_or(0) as usize;
            event_keys+=count;
            if event_keys>4096||count>0&&offset.checked_add(count*4).is_none_or(|end|end>bytes.len()){return Err("M2 event timestamp capacity/truncation exceeded".into());}
        }
        let clips=engine_formats_core::parse_m2_animations(&bytes);let globals=engine_formats_core::parse_m2_global_sequence_bones(&bytes);
        if clips.iter().map(|c|c.events.len()).sum::<usize>()>32768{return Err("M2 sequence event capacity exceeded".into());}
        if clips.iter().flat_map(|c|&c.events).any(|e|!e.time.is_finite()||e.position.iter().any(|x|!x.is_finite())){return Err("non-finite M2 event record".into());}
        let count=bytes.u32_at(0x13c).unwrap_or(0) as usize;
        if count>16{return Err("M2 particle emitter capacity exceeded".into());}
        let emitters=engine_formats_core::parse_m2_particle_emitters(&bytes).map_err(|e|e.to_string())?;
        if emitters.len()!=count{return Err("truncated M2 particle emitters".into());}
        let base=bytes.u32_at(0x140).unwrap_or(0) as usize;
        let particle_blends=(0..count).map(|i|{let value=bytes[base+i*0x1f8+0x28];if value<=6{value}else{0}}).collect();
        let count=bytes.u32_at(0x134).unwrap_or(0) as usize;
        if count>16{return Err("M2 ribbon emitter capacity exceeded".into());}
        let ribbons=engine_formats_core::parse_m2_ribbon_emitters(&bytes).map_err(|e|e.to_string())?;
        if ribbons.len()!=count{return Err("truncated M2 ribbon emitters".into());}
        let cameras=engine_formats_core::parse_m2_pane_cameras(&bytes);
        Ok(Self{file:bytes,format,clips,globals,meshes,raw_blends,cameras,emitters,particle_blends,ribbons})
    }
    pub fn effect_pose(&self,v:&Value)->Result<(Option<usize>,f32,f32,Vec<Mat4>),String>{
        let clip=self.selected_clip(v)?;let seq=clip.map(|c|c.seq_index);
        let cursor=v["cursor_ms"].as_u64().unwrap_or(0) as f32/1000.;let time=self.clip_time(clip,cursor,v);
        let anchor=Self::anchor(v)?;let mut palette=self.palette(clip,time,v["clock_ms"].as_u64().unwrap_or(0),anchor,crate::billboard::camera(v)?)?;
        if palette.is_empty(){palette.push(anchor);}else{for m in &mut palette{*m=anchor**m;}}
        Ok((seq,cursor,time,palette))
    }
    fn idle_clip(&self)->Option<&ModelAnimation>{
        let id=self.format.model().playable_animation_lookup.first().map_or(0,|p|p.resolved_id);
        self.clips.iter().find(|c|c.anim_id==id).or(self.clips.first())
    }
    pub(crate) fn selected_clip(&self,v:&Value)->Result<Option<&ModelAnimation>,String>{
        if let Some(index)=v.get("sequence_index"){
            let index=index.as_u64().ok_or("invalid M2 sequence index")?;
            let clip=self.clips.iter().find(|c|c.seq_index as u64==index).ok_or("unknown M2 sequence index")?;
            if v["anim_id"].as_u64().is_some_and(|id|id!=clip.anim_id as u64){return Err("M2 sequence animation mismatch".into());}
            return Ok(Some(clip));
        }
        if let Some(id)=v["anim_id"].as_u64(){return Ok(self.clips.iter().find(|c|c.anim_id as u64==id));}
        Ok(if v["world_instance"]==true{self.idle_clip()}else{None})
    }
    fn clip_time(&self,clip:Option<&ModelAnimation>,cursor:f32,v:&Value)->f32{
        clip.map_or(0.,|c|if c.duration<=0.{0.}else if c.looping||v["repeat"]==true{cursor%c.duration}else{cursor.min(c.duration)})
    }
    pub(crate) fn anchor(v:&Value)->Result<Mat4,String>{
        if v["anchor"].is_null(){return Ok(Mat4::IDENTITY);}
        let values=v["anchor"].as_array().filter(|a|a.len()==16).ok_or("invalid attachment anchor")?;
        let mut a=[0f32;16];for (out,value) in a.iter_mut().zip(values){*out=value.as_f64().ok_or("invalid attachment anchor")? as f32;}
        let m=Mat4::from_cols_array(&a);
        if !m.is_finite()||a.iter().any(|x|x.abs()>1e6)||m.determinant().abs()<1e-8||a[3].abs()>1e-6||a[7].abs()>1e-6||a[11].abs()>1e-6||(a[15]-1.).abs()>1e-6{return Err("invalid attachment anchor".into());}Ok(m)
    }
    pub fn facts(&self)->Value{
        let m=self.format.model();
        let dynamic=!self.clips.is_empty()||!self.globals.is_empty()||!self.emitters.is_empty()||!self.ribbons.is_empty()||m.bones.iter().any(|b|b.is_billboard())||self.meshes.iter().any(|s|s.alpha_anim.is_some()||s.rgb_seq.is_some()||s.rgb_anim.is_some()||s.uv_seq.is_some()||s.uv_anim.is_some()||s.uv_scale_seq.is_some()||s.uv_rot_seq.is_some());
        json!({"sequences":self.clips.iter().map(|s|json!({"anim_id":s.anim_id,"sequence_index":s.seq_index,"duration_ms":s.end_ms-s.start_ms,"looping":s.looping,"frequency":s.frequency,"min_replay":s.min_replay,"max_replay":s.max_replay,"event_keys":s.events.len()})).collect::<Vec<_>>(),"event_tags":self.clips.iter().flat_map(|c|&c.events).map(|e|String::from_utf8_lossy(&e.ident).into_owned()).collect::<std::collections::BTreeSet<_>>(),"particle_models":self.particle_dependencies(),"idle_sequence":self.idle_clip().map(|c|c.seq_index),"bbox":[m.header.bounding_box_min,m.header.bounding_box_max],"cameras":self.cameras.len(),"bones":m.bones.len(),"dynamic":dynamic,"billboards":m.bones.iter().filter(|b|b.is_billboard()).count()})
    }
    pub(crate) fn has_events(&self)->bool{self.clips.iter().any(|c|!c.events.is_empty())}
    fn step(&self,bone:usize,channel:usize)->bool{
        let offset=self.file.u32_at(0x38).unwrap_or(0) as usize+bone*0x6c+[0x0c,0x28,0x44][channel];self.file.u16_at(offset).unwrap_or(0)==0
    }
    fn palette(&self,clip:Option<&ModelAnimation>,t:f32,clock:u64,anchor:Mat4,cam:Option<(Vec3,Vec3,Vec3)>)->Result<Vec<Mat4>,String>{
        let bones=&self.format.model().bones;let mut local=vec![Mat4::IDENTITY;bones.len()];
        for (i,bone) in bones.iter().enumerate(){
            let mut tr=[0.;3];let mut rot=[0.,0.,0.,1.];let mut sc=[1.;3];
            if let Some(keys)=clip.and_then(|c|c.bones.iter().find(|k|k.bone as usize==i)){
                tr=interp(&keys.translation,t,self.step(i,0),tr);rot=rotation(&keys.rotation,t,self.step(i,1),rot);sc=interp(&keys.scale,t,self.step(i,2),sc);
            }
            if let Some(g)=self.globals.iter().find(|g|g.bone as usize==i){
                macro_rules! channel {($name:ident,$value:ident,$idx:expr)=>{if let Some(c)=&g.$name{let keys:Vec<_>=c.keys.iter().map(|(ms,v)|(*ms as f32/1000.,*v)).collect();$value=interp(&keys,(clock%c.period_ms.max(1) as u64) as f32/1000.,self.step(i,$idx),$value);}};}
                channel!(translation,tr,0);channel!(scale,sc,2);
                if let Some(c)=&g.rotation{let keys:Vec<_>=c.keys.iter().map(|(ms,v)|(*ms as f32/1000.,*v)).collect();rot=rotation(&keys,(clock%c.period_ms.max(1) as u64) as f32/1000.,self.step(i,1),rot);}
            }
            if tr.iter().chain(rot.iter()).chain(sc.iter()).any(|v|!v.is_finite()){return Err("non-finite M2 pose".into());}
            let q=Quat::from_array(rot);let q=if q.length_squared()>1e-12{q.normalize()}else{Quat::IDENTITY};let p=Vec3::new(bone.pivot.x,bone.pivot.y,bone.pivot.z);
            local[i]=Mat4::from_translation(p+Vec3::from_array(tr))*Mat4::from_quat(q)*Mat4::from_scale(Vec3::from_array(sc))*Mat4::from_translation(-p);
        }
        fn compose(i:usize,bones:&[engine_m2::M2Bone],local:&[Mat4],state:&mut[u8],world:&mut[Mat4],anchor:Mat4,cam:Option<(Vec3,Vec3,Vec3)>)->Result<(),String>{
            if state[i]==2{return Ok(());}if state[i]==1{return Err("cyclic M2 skeleton".into());}state[i]=1;
            let parent=bones[i].parent;
            let mut matrix=Mat4::IDENTITY;
            if parent>=0{let p=parent as usize;if p>=bones.len(){return Err("invalid M2 parent".into());}compose(p,bones,local,state,world,anchor,cam)?;matrix=world[p];
                if let Some(arm)=engine_formats_core::ParentArm::from_bone_flags(bones[i].flags.bits()){
                    let pivot=Vec3::new(bones[i].pivot.x,bones[i].pivot.y,bones[i].pivot.z);
                    let origin=matrix.transform_point3(pivot);
                    use engine_formats_core::ParentBasis;
                    for axis in 0..3{
                        let v=matrix.col(axis).truncate();let value=match arm.basis{ParentBasis::Keep=>v,ParentBasis::UnitNormalize=>if v.length()>1./4194304.{v.normalize()}else{v},ParentBasis::RootDirection=>Vec3::AXES[axis]*v.length(),ParentBasis::RootBasis=>Vec3::AXES[axis]};
                        match axis{0=>matrix.x_axis=value.extend(0.),1=>matrix.y_axis=value.extend(0.),_=>matrix.z_axis=value.extend(0.)}
                    }
                    matrix.w_axis=if arm.ignore_translate{Vec4::W}else{(origin-matrix.transform_vector3(pivot)).extend(1.)};
                }
            }
            world[i]=matrix*local[i];
            if let (Some(kind),Some(camera))=(engine_formats_core::BillboardKind::from_bone_flags(bones[i].flags.bits()),cam){
                let p=Vec3::new(bones[i].pivot.x,bones[i].pivot.y,bones[i].pivot.z);
                world[i]=anchor.inverse()*crate::billboard::replace(kind,anchor*world[i],p,camera);
                if !world[i].is_finite(){return Err("non-finite billboard pose".into());}
            }
            state[i]=2;Ok(())
        }
        let mut state=vec![0;bones.len()];let mut world=vec![Mat4::IDENTITY;bones.len()];
        for i in 0..bones.len(){compose(i,bones,&local,&mut state,&mut world,anchor,cam)?;}
        Ok(world)
    }
    pub fn sample(&self,v:&Value,blob:&mut Vec<u8>)->Result<Value,String>{
        let clock=v["clock_ms"].as_u64().unwrap_or(0);let clip=self.selected_clip(v)?;
        let cursor=v["cursor_ms"].as_u64().unwrap_or(0) as f32/1000.;let t=self.clip_time(clip,cursor,v);
        let anchor=Self::anchor(v)?;let cam=crate::billboard::camera(v)?;let matrices=self.palette(clip,t,clock,anchor,cam)?;let mut rows=Vec::new();
        let mut attachments=serde_json::Map::new();
        for id in 0..self.format.model().attach_lookup.len().min(256){if let Some(a)=self.format.model().attachment(id as u16){let matrix=matrices.get(a.bone as usize).ok_or("invalid attachment bone")?;let m=anchor**matrix*Mat4::from_translation(Vec3::from(a.position));if !m.is_finite(){return Err("invalid attachment pose".into());}attachments.insert(id.to_string(),json!(m.to_cols_array()));}}
        for (mesh_index,sub) in self.meshes.iter().enumerate(){
            let offset=blob.len();let mut min=Vec3::splat(f32::INFINITY);let mut max=Vec3::splat(f32::NEG_INFINITY);
            for (i,&pos) in sub.positions.iter().enumerate(){
                let source=Vec3::from_array(pos);let normal=Vec3::from_array(sub.normals.get(i).copied().unwrap_or([0.,0.,1.]));let mut p=source;let mut n=normal;
                if let Some(joints)=sub.joints.get(i).filter(|_|!matrices.is_empty()){
                    p=Vec3::ZERO;n=Vec3::ZERO;let weights=sub.weights.get(i).ok_or("missing M2 skin weights")?;
                    for j in 0..4{if weights[j]>0.{let matrix=matrices.get(joints[j] as usize).ok_or("invalid M2 skin bone")?;p+=matrix.transform_point3(source)*weights[j];n+=matrix.transform_vector3(normal)*weights[j];}}
                }
                let p=Vec3::from_array(basis(anchor.transform_point3(p).to_array()));let n=basis(anchor.inverse().transpose().transform_vector3(n).normalize_or_zero().to_array());let uv=sub.uvs.get(i).copied().unwrap_or([0.,0.]);
                min=min.min(p);max=max.max(p);
                for x in [p.x,p.y,p.z,n[0],n[1],n[2],uv[0],uv[1]]{if !x.is_finite(){return Err("non-finite M2 vertex".into());}blob.extend_from_slice(&x.to_le_bytes());}
            }
            let seq=clip.map(|c|c.seq_index);let alpha=sub.alpha_anim.as_ref().map_or(1.,|s|s.sample(seq,t,clock as f64/1000.));
            let rgb=sub.rgb_seq.as_ref().and_then(|s|s.seq(seq)).or(sub.rgb_anim.as_ref()).map_or([1.;3],|a|a.sample(a.clock(t,clock as f64/1000.)));
            let uv=sub.uv_seq.as_ref().and_then(|s|s.seq(seq)).or(sub.uv_anim.as_ref()).map_or([0.;2],|a|a.sample(a.clock(t,clock as f64/1000.)));
            let uv_scale=sub.uv_scale_seq.as_ref().and_then(|s|s.seq(seq)).map_or([1.;2],|a|a.sample(a.clock(t,clock as f64/1000.)));
            let rot=sub.uv_rot_seq.as_ref().and_then(|s|s.seq(seq)).map_or([0.,0.,0.,1.],|a|a.sample(a.clock(t,clock as f64/1000.)));
            if !alpha.is_finite() || rgb.iter().chain(uv.iter()).chain(uv_scale.iter()).chain(rot.iter()).any(|x|!x.is_finite()){return Err("non-finite M2 animated material".into());}
            let uv_rotation=engine_formats_core::rotation_2x2(rot);let blend=self.raw_blends[mesh_index];
            let rgb=if matches!(blend,5|6){[1.;3]}else{sub.vertex_colors.first().map_or(rgb,|c|[c[0],c[1],c[2]])};
            let char_slot=sub.char_slot.map(|slot|match slot{
                engine_formats_core::CharSkinSlot::Body=>"Body",engine_formats_core::CharSkinSlot::Object=>"Object",
                engine_formats_core::CharSkinSlot::Hair=>"Hair",engine_formats_core::CharSkinSlot::SkinExtra=>"SkinExtra",
            });
            let mut row=json!({"offset":offset,"vertices":sub.positions.len(),"bounds":[min.to_array(),max.to_array()],"indices":sub.indices,"texture":sub.texture,"blend":blend,"unlit":sub.emissive,"two_sided":sub.two_sided,"no_depth_test":sub.no_depth_test,"no_depth_write":sub.no_depth_write,"wrap_u":sub.wrap_x,"wrap_v":sub.wrap_y,"alpha":alpha,"tint":rgb,"uv_offset":uv,"uv_scale":uv_scale,"uv_rotation":[uv_rotation.0,uv_rotation.1],"env_map":sub.env_map,"icon_slot":sub.icon_slot,"skin_slot":sub.skin_slot,"char_slot":char_slot,"no_fog":matches!(sub.fog_policy,engine_formats_core::FogPolicy::Off),"geoset":sub.geoset_id});
            if v["compact"]==true{let obj=row.as_object_mut().unwrap();for k in ["indices","texture","blend","unlit","two_sided","no_depth_test","no_depth_write","wrap_u","wrap_v","geoset","no_fog","env_map","icon_slot","skin_slot","char_slot"]{obj.remove(k);}}
            rows.push(row);
        }
        let mut limitations=Vec::new();
        if self.format.model().bones.iter().any(|b|b.is_billboard())&&cam.is_none(){limitations.push("Camera-dependent bone billboards require a camera view");}
        if self.meshes.iter().any(|m|m.no_depth_test){limitations.push("Qt material API does not expose the original no-depth-test flag");}
        // Replaceable slots are filled per Qt model instance, after this file-level
        // sample. The live instance reports only the slots still unresolved.
        if !self.ribbons.is_empty()&&!v["instance"].is_string(){limitations.push("Ribbon effects require a model instance clock");}
        if !self.emitters.is_empty()&&!v["instance"].is_string(){limitations.push("Particle effects require a model instance clock");}
        let skin=self.format.model().parse_embedded_skin(&self.file,0).map_err(|e|e.to_string())?;
        if skin.batches().iter().any(|b|b.texture_count>1){limitations.push("Multi-stage materials require additional shader stages");}
        let camera=v["camera"].as_u64().and_then(|i|self.cameras.get(i as usize)).map(|c|{let view=c.at(clip.map_or(0,|c|c.start_ms)+(t*1000.) as u32);json!({"position":basis(view.position),"target":basis(view.target),"roll":view.roll,"fov":view.fov,"near":view.near_clip,"far":view.far_clip})});
        if camera.as_ref().is_some_and(|c|c["position"].as_array().unwrap().iter().chain(c["target"].as_array().unwrap().iter()).chain([&c["roll"],&c["fov"],&c["near"],&c["far"]]).any(|x|x.as_f64().is_none())){return Err("non-finite M2 camera".into());}
        Ok(json!({"format":"M2_RUNTIME","rows":rows,"attachments":attachments,"camera":camera,"blob_kind":"vertices","blob_bytes":blob.len(),"stride":32,"facts":self.facts(),"limitations":limitations}))
    }
}
