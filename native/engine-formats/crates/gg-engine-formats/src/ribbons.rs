//! GG Qt adaptation of engine-world/src/ribbons.rs (MIT OR Apache-2.0).
//! Original parser and track/gate samplers; per-instance bounded retained strips.
use std::collections::VecDeque;
use engine_formats_core::RibbonEmitterDef;
use glam::{Mat4,Vec3};
use serde_json::{json,Value};
const MAX_EDGES:usize=512;
struct Edge {top:Vec3,bottom:Vec3,born:f64,age:f32}
struct Trail {edges:VecDeque<Edge>,phase:f32,age:f32}
pub struct System {trails:Vec<Trail>,clock:Option<u64>,animation:Option<u64>,cursor:u64,parent:Option<Mat4>}
impl System {
 pub fn new(count:usize)->Self {Self{trails:(0..count).map(|_|Trail{edges:VecDeque::new(),phase:0.,age:0.}).collect(),clock:None,animation:None,cursor:0,parent:None}}
 pub fn sample(&mut self,defs:&[RibbonEmitterDef],matrices:&[Mat4],v:&Value,clip_time:f32,blob:&mut Vec<u8>)->Result<Value,String>{
    let parent=crate::effect_rebase::parent(v)?;
    let clock=v["clock_ms"].as_u64().unwrap_or(0);let animation=v["anim_id"].as_u64();let cursor=v["cursor_ms"].as_u64().unwrap_or(0);
    let reset=self.clock.is_some_and(|last|clock<last||clock-last>1000)||(v["world_instance"]!=true&&(self.animation!=animation||cursor<self.cursor));
    if reset{*self=Self::new(defs.len());}
    let rebase=crate::effect_rebase::delta(&mut self.parent,parent);
    if rebase!=Mat4::IDENTITY{for trail in &mut self.trails{for edge in &mut trail.edges{edge.top=rebase.transform_point3(edge.top);edge.bottom=rebase.transform_point3(edge.bottom);}}}
    let dt=self.clock.map_or(0.,|last|(clock-last) as f32/1000.).min(0.1);let now=clock as f64/1000.;
    self.clock=Some(clock);self.animation=animation;self.cursor=cursor;
    let mut rows=Vec::new();let mut live=0;let mut limitations=Vec::new();
    for (index,(def,trail)) in defs.iter().zip(&mut self.trails).enumerate(){
        let matrix=matrices.get(def.bone as usize).copied().unwrap_or(Mat4::IDENTITY);
        trail.age+=dt;let ms=trail.age*1000.;let above=def.height_above.sample_ms(ms).max(0.);let below=def.height_below.sample_ms(ms).max(0.);
        let rgb=def.color.sample_ms(ms);let color=[rgb[0],rgb[1],rgb[2],def.alpha.sample_ms(ms).max(0.)];
        if !matrix.is_finite() || [above,below,def.edges_per_second,def.edge_lifetime,def.gravity].iter().chain(color.iter()).any(|x|!x.is_finite()||x.abs()>1e6){return Err("invalid ribbon parameter".into());}
        let life=def.edge_lifetime.clamp(0.25,60.);let lit=def.visible.as_ref().is_none_or(|vis|vis.at(animation.unwrap_or(0).min(u16::MAX as u64) as u16,clip_time));
        let node=matrix.transform_point3(Vec3::from(def.position));let axis=matrix.transform_vector3(Vec3::Y).normalize_or(Vec3::Y);
        while trail.edges.front().is_some_and(|e|now-e.born>=life as f64){trail.edges.pop_front();}
        for e in &mut trail.edges {let rise=def.gravity*(2.*e.age+dt)*dt;e.top.z+=rise;e.bottom.z+=rise;e.age+=dt;}
        let emitting=lit&&def.texture.is_some()&&def.edges_per_second>0.&&(def.height_above.peak().max(0.)+def.height_below.peak().max(0.))>0.;
        if emitting{
            trail.phase+=def.edges_per_second.min(16384.)*dt;let births=trail.phase.floor().max(0.);trail.phase-=births;
            let n=(births as usize).min(MAX_EDGES.saturating_sub(trail.edges.len()));
            for k in 0..n{let back=dt*(n-1-k) as f32/n as f32;trail.edges.push_back(Edge{top:node+axis*above,bottom:node-axis*below,born:now-back as f64,age:back});}
        }
        live+=trail.edges.len();let mut pairs=Vec::new();
        if emitting {pairs.push((node+axis*above,node-axis*below,0.));for e in trail.edges.iter().rev(){pairs.push((e.top,e.bottom,((now-e.born)/life as f64).clamp(0.,1.) as f32));}}
        let rows_n=def.tile_rows.max(1) as u32;let cols=def.tile_cols.max(1) as u32;let cell=(def.tex_slot as u32).min(rows_n*cols-1);
        let (u0,du,v0,dv)=((cell%cols) as f32/cols as f32,1./cols as f32,(cell/cols) as f32/rows_n as f32,1./rows_n as f32);
        let offset=blob.len();let mut indices=Vec::new();let mut count=0u32;let mut lo=Vec3::splat(f32::INFINITY);let mut hi=Vec3::splat(f32::NEG_INFINITY);
        for pair in pairs.windows(2){let ((t0,b0,a0),(t1,b1,a1))=(pair[0],pair[1]);
            for (p,uv) in [(b0,[u0+du*a0,v0+dv]),(b1,[u0+du*a1,v0+dv]),(t1,[u0+du*a1,v0]),(t0,[u0+du*a0,v0])]{
                let p=Vec3::new(p.x,p.z,-p.y);if !p.is_finite(){return Err("non-finite ribbon vertex".into());}lo=lo.min(p);hi=hi.max(p);
                for x in p.to_array().into_iter().chain([0.,0.,1.]).chain(uv).chain(color){blob.extend_from_slice(&x.to_le_bytes());}
            }
            indices.extend([count,count+1,count+2,count,count+2,count+3]);count+=4;
        }
        let visible=count>0;
        if !visible{lo=Vec3::ZERO;hi=Vec3::ZERO;blob.extend_from_slice(&[0;192]);indices.extend([0,1,2,0,2,3]);count=4;}
        if def.texture.is_none(){limitations.push("Ribbon texture is unresolved");}
        rows.push(json!({"offset":offset,"vertices":count,"indices":indices,"bounds":[lo.to_array(),hi.to_array()],"stride":48,"capacity":MAX_EDGES*4,"texture":def.texture,"blend":def.blend_mode.filter(|&b|b<=6).unwrap_or(4),"unlit":true,"two_sided":true,"vertex_colors":true,"alpha":if visible{1.}else{0.},"visible":visible,"tint":[1.,1.,1.],"uv_offset":[0.,0.],"uv_scale":[1.,1.],"uv_rotation":[1.,0.],"wrap_u":true,"wrap_v":true,"no_fog":false,"ribbon":index}));
    }
    if !defs.is_empty()&&v["world_instance"]!=true&&v["pane_anchor"].is_null(){limitations.push("Pane ribbon needs a layout anchor");}
    limitations.sort();limitations.dedup();if blob.len()>8*1024*1024{return Err("ribbon output capacity exceeded".into());}
    Ok(json!({"rows":rows,"live_edges":live,"reset":reset,"limitations":limitations}))
 }
}
