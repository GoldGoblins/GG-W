//! Qt particle adapter over the original definitions, spawn, child and model kernels.
//! Adapted from engine-world/src/particles/{sim,model,quads}.rs (MIT/Apache-2.0).
use engine_formats_core::ParticleEmitterDef;
use glam::{Mat4,Quat,Vec3};
use serde_json::{json,Value};
use std::{collections::HashMap,sync::Arc};
use crate::particle_emit::{emit_local,rand01,rand_s11,next_u32};
use crate::runtime::Model;
const MAX_PARTICLES:usize=256;
const MAX_MODELS:usize=128;
struct Particle {pos:Vec3,vel:Vec3,age:f32,life:f32,phase:u32,quat:Quat,angvel:Vec3,fresh:bool}
struct Child {def:ParticleEmitterDef,blend:u8,pool:Pool}
struct Pool {particles:Vec<Particle>,fraction:f32,armed:bool,rng:u32,seed:u32,previous:Option<Vec3>,inherit:Vec3,inherit_time:f32,model:Option<Arc<Model>>,children:Vec<Child>,age:f32}
impl Pool {
 fn new(seed:u32)->Self{Self{particles:Vec::new(),fraction:0.,armed:true,rng:seed,seed,previous:None,inherit:Vec3::ZERO,inherit_time:0.,model:None,children:Vec::new(),age:0.}}
 fn reset(&mut self){self.particles.clear();self.fraction=0.;self.armed=true;self.rng=self.seed;self.previous=None;self.inherit=Vec3::ZERO;self.inherit_time=0.;self.age=0.;for child in &mut self.children{child.pool.reset();}}
}
pub struct System {pools:Vec<Pool>,clock:Option<u64>,animation:Option<u64>,cursor:u64,parent:Option<Mat4>}
fn qt(v:Vec3)->Vec3{Vec3::new(v.x,v.z,-v.y)}
fn wow(v:&Value)->Vec3{Vec3::new(v[0].as_f64().unwrap_or(0.) as f32,-v[2].as_f64().unwrap_or(0.) as f32,v[1].as_f64().unwrap_or(0.) as f32)}
static NOISE:std::sync::LazyLock<[f32;128]>=std::sync::LazyLock::new(||{let mut rng=0xC0FF_EE11;std::array::from_fn(|_|rand01(&mut rng))});
fn births(def:&ParticleEmitterDef,pool:&mut Pool,enabled:bool,rate:f32,dt:f32)->usize{
 if def.burst(){if enabled&&pool.armed{pool.armed=false;rate.min(MAX_PARTICLES as f32) as usize}else{if !enabled{pool.armed=true;}0}}
 else if enabled{pool.fraction=(pool.fraction+rate.min(16384.)*dt).min(MAX_PARTICLES as f32);let n=pool.fraction.floor() as usize;pool.fraction-=n as f32;n}else{0}
}
fn integrate(p:&mut Particle,def:&ParticleEmitterDef,dt:f32,gravity:f32,follow:Vec3,origin:Vec3)->bool{
 p.age+=dt;if p.age>=p.life{return false;}
 if p.fresh{p.fresh=false;}else{p.pos+=follow;}
 let theta=p.angvel.length();if theta>1e-4{p.quat=(p.quat*Quat::from_axis_angle(p.angvel/theta,theta*dt)).normalize();}
 let velocity=p.vel;p.pos+=velocity*dt;p.pos.z-=0.5*gravity*dt*dt;p.vel.z-=gravity*dt;
 p.vel-=p.vel*(dt*def.drag).min(1.);
 !(def.kill_outbound()&&velocity.dot(p.pos-origin)>0.)&&p.pos.is_finite()&&p.vel.is_finite()
}
fn birth_age(def:&ParticleEmitterDef,dt:f32,rng:&mut u32)->f32{if def.burst(){0.}else{rand01(rng)*dt.min(0.1)}}
impl System {
 pub fn new(defs:&[ParticleEmitterDef],dependencies:&HashMap<String,Arc<Model>>)->Self {
  let pools=defs.iter().enumerate().map(|(i,def)|{
   let mut pool=Pool::new(0x1234567+i as u32);
   pool.model=def.geometry_model.as_ref().and_then(|name|dependencies.get(name)).cloned();
   if let Some(model)=def.recursion_model.as_ref().and_then(|name|dependencies.get(name)){
    let mut seed=pool.rng.rotate_left(7)|1;
    for (child,blend) in model.emitters.iter().zip(&model.particle_blends).take(4){
     if child.texture.is_none()||child.params.peak_lifespan()<=0.||child.timing.peak_rate()<=0.{continue;}
     seed=seed.wrapping_mul(0x9E3779B9)|1;pool.children.push(Child{def:child.clone(),blend:*blend,pool:Pool::new(seed)});
    }
   }
   pool
  }).collect();Self{pools,clock:None,animation:None,cursor:0,parent:None}
 }
 pub fn sample(&mut self,defs:&[ParticleEmitterDef],blends:&[u8],seq:Option<usize>,time:f32,matrices:&[Mat4],v:&Value,camera:&Value,collisions:&HashMap<String,crate::collision::Page>,blob:&mut Vec<u8>)->Result<Value,String>{
  let parent=crate::effect_rebase::parent(v)?;
  let clock=v["clock_ms"].as_u64().unwrap_or(0);let animation=v["anim_id"].as_u64();let cursor=v["cursor_ms"].as_u64().unwrap_or(0);
  let reset=self.clock.is_some_and(|last|clock<last||clock-last>1000)||(v["world_instance"]!=true&&(self.animation!=animation||cursor<self.cursor));
  if reset{for pool in &mut self.pools{pool.reset();}self.clock=None;self.parent=None;}
  let rebase=crate::effect_rebase::delta(&mut self.parent,parent);
  let dt=self.clock.map_or(0.,|last|(clock-last) as f32/1000.).min(0.25);self.clock=Some(clock);self.animation=animation;self.cursor=cursor;
  let density=v["particle_density"].as_f64().unwrap_or(1.) as f32;
  if !density.is_finite()||!(0.0..=1.0).contains(&density){return Err("invalid particle density".into());}
  let instance_scale=v["model_scale"].as_f64().unwrap_or(1.) as f32;
  if !instance_scale.is_finite(){return Err("invalid particle model scale".into());}
  let facing=v["facing"].as_f64().unwrap_or(0.) as f32;if !facing.is_finite(){return Err("invalid particle facing".into());}
  let (right,up)=if camera.is_object(){
   let n=(wow(&camera["position"])-wow(&camera["target"])).normalize_or(Vec3::Z);
   let roll=camera["roll"].as_f64().unwrap_or(0.) as f32;let hint=if camera["up"].is_array(){wow(&camera["up"]).normalize_or(Vec3::Z)}else{Vec3::new(0.,-roll.sin(),roll.cos())};
   let r=hint.cross(n).normalize_or(Vec3::X);(r,n.cross(r).normalize_or(Vec3::Y))
  }else{let inverse=Quat::from_rotation_z(-facing);(inverse*Vec3::X,inverse*Vec3::Y)};
  let mut rows=Vec::new();let mut limitations=Vec::new();let mut live=0usize;let mut child_live=0usize;let mut model_live=0usize;
  for (index,(def,pool)) in defs.iter().zip(&mut self.pools).enumerate(){
   if !def.model_space()&&rebase!=Mat4::IDENTITY{rebase_pool(pool,rebase);}
   let matrix=matrices.get(def.bone as usize).copied().unwrap_or(Mat4::IDENTITY);
   if !matrix.is_finite(){return Err("non-finite particle bone".into());}
   if def.geometry_model.is_some()&&pool.model.is_none(){limitations.push("Particle geometry model is not resident");}
   if def.recursion_model.is_some()&&pool.children.is_empty(){limitations.push("Particle recursion model has no resident eligible emitters");}
   if !def.model_space()&&v["world_instance"]!=true&&v["pane_anchor"].is_null(){limitations.push("Pane world-space effect needs a layout anchor");}
   if def.ground_snap()&&!def.model_space()&&collisions.is_empty(){limitations.push("Ground-snap effect has no resident walking collision");}
   let origin=matrix.transform_point3(Vec3::from(def.position));let delta=pool.previous.map_or(Vec3::ZERO,|p|origin-p);pool.previous=Some(origin);
   pool.inherit_time+=dt;
   if pool.inherit_time>1./30.{pool.inherit=if pool.particles.is_empty(){Vec3::ZERO}else{delta*((1./30.)/pool.inherit_time)*def.inherit_scale};pool.inherit_time=0.;}
   let steps=(dt*60.).ceil().max(1.) as usize;let step=dt/steps as f32;
   let follow=def.follow_line().map_or(0.,|(a,b)|(a*delta.length()/dt.max(1e-6)+b).clamp(0.,1.));
   let follow_delta=if def.follow_emitter(){if def.model_space(){matrix.inverse().transform_vector3(delta)*(follow-1.)}else{delta*follow}}else{Vec3::ZERO}/steps as f32;
   for k in 0..steps{
    let elapsed=(time-dt+(k+1) as f32*step).max(0.);let shared=(clock as f64/1000.-dt as f64+(k+1) as f64*step as f64).max(0.);
    let now=def.params.sample(seq,elapsed,shared);pool.age+=step;
    let numbers=[now.emission_speed,now.speed_variation,now.vertical_range,now.horizontal_range,now.gravity,now.lifespan,now.area_length,now.area_width,now.z_source,def.drag];
    if numbers.iter().any(|x|!x.is_finite()||x.abs()>1e6){return Err("non-finite or excessive particle parameter".into());}
    let kill_origin=if def.model_space(){Vec3::from(def.position)}else{origin};
    pool.particles.retain_mut(|p|integrate(p,def,step,now.gravity,follow_delta,kill_origin));
    let rate=def.timing.rate(seq,elapsed,shared)*density;if !rate.is_finite(){return Err("non-finite particle rate".into());}
    let enabled=def.timing.emitting(seq,elapsed,shared)&&rate>0.;let count=births(def,pool,enabled,rate,step);
    for _ in 0..count.min(MAX_PARTICLES.saturating_sub(pool.particles.len())){
     if now.lifespan<=0.{continue;}
     let (mut pos,dir)=emit_local(def,&now,&mut pool.rng);let mut vel=dir*now.emission_speed*(1.+rand_s11(&mut pool.rng)*now.speed_variation);
     if def.inherits_emitter_motion(){let inherit=if def.model_space(){matrix.inverse().transform_vector3(pool.inherit)}else{pool.inherit};let inherit=inherit*(1.+rand_s11(&mut pool.rng)*now.speed_variation);if def.model_space(){vel+=inherit;}else{vel=matrix.transform_vector3(vel)+inherit;}}
     else if !def.model_space(){vel=matrix.transform_vector3(vel);}
     if !def.model_space(){pos=matrix.transform_point3(pos);if def.ground_snap(){if let Some(z)=crate::collision::down(collisions,pos){pos.z=z+def.over_life.sample(0.).size;}}}
     let (quat,angvel)=if def.geometry_model.is_some(){
      let a=def.angular_velocity_min;let b=def.angular_velocity_max;let mut w=Vec3::new(a[0]+rand01(&mut pool.rng)*(b[0]-a[0]),(1.+rand01(&mut pool.rng))*(b[1]-a[1]),(1.+rand01(&mut pool.rng))*(b[2]-a[2]));
      if def.tumble_random_sign(){for axis in 0..3{if next_u32(&mut pool.rng)&1==0{w[axis]=-w[axis];}}}
      let q=Quat::from_rotation_z(std::f32::consts::FRAC_PI_2);(if def.model_space(){q}else{matrix.to_scale_rotation_translation().1*q},w)
     }else{(Quat::IDENTITY,Vec3::ZERO)};
     let phase=next_u32(&mut pool.rng);let age=birth_age(def,step,&mut pool.rng);
     if pos.is_finite()&&vel.is_finite(){pool.particles.push(Particle{pos,vel,age,life:now.lifespan.min(60.),phase,quat,angvel,fresh:true});}
    }
    for child in &mut pool.children{
     let c=&child.def;let t=pool.age;let now=c.params.sample(None,t,f64::from(t));let rate=c.timing.rate(None,t,f64::from(t))*density;
     if !rate.is_finite()||!now.lifespan.is_finite()||now.lifespan>1e6{return Err("invalid child particle parameters".into());}
     let enabled=c.timing.emitting(None,t,f64::from(t))&&rate>0.;
     for parent in &pool.particles{
      let n=births(c,&mut child.pool,enabled,rate,step);
      for _ in 0..n.min(MAX_PARTICLES.saturating_sub(child.pool.particles.len())){
       if now.lifespan<=0.{continue;}
       let (base,dir)=emit_local(c,&now,&mut child.pool.rng);let fold=|p:Vec3|if def.model_space(){p}else{matrix.transform_vector3(p)};
       let local=base-Vec3::from(c.position);let speed=now.emission_speed*(1.+now.speed_variation*rand_s11(&mut child.pool.rng));let mut vel=fold(dir*speed);
       if c.inherits_emitter_motion(){vel+=parent.vel*(1.+now.speed_variation*rand_s11(&mut child.pool.rng));}
       let phase=next_u32(&mut child.pool.rng);let age=birth_age(c,step,&mut child.pool.rng);
       child.pool.particles.push(Particle{pos:parent.pos+fold(local),vel,age,life:now.lifespan.min(60.),phase,quat:Quat::IDENTITY,angvel:Vec3::ZERO,fresh:true});
      }
     }
     child.pool.particles.retain_mut(|p|integrate(p,c,step,now.gravity,Vec3::ZERO,Vec3::ZERO));
    }
   }
   live+=pool.particles.len();
   if def.geometry_model.is_some(){if let Some(model)=&pool.model{model_live+=pool.particles.len().min(MAX_MODELS);rows.extend(draw_models(def,pool,model,matrix,instance_scale,blob)?);}}
   else{rows.extend(draw_quads(def,pool,matrix,right,up,instance_scale,blends[index],blob)?);}
   for child in &pool.children{
    child_live+=child.pool.particles.len();let mut def=child.def.clone();def.flags=(def.flags&!0x10)|(defs[index].flags&0x10);
    rows.extend(draw_quads(&def,&child.pool,matrix,right,up,instance_scale,child.blend,blob)?);
   }
  }
  limitations.sort();limitations.dedup();if blob.len()>8*1024*1024||rows.len()>512{return Err("particle output capacity exceeded".into());}
  Ok(json!({"rows":rows,"live_particles":live+child_live,"parent_particles":live,"child_particles":child_live,"model_particles":model_live,"limitations":limitations,"reset":reset}))
 }
}
fn rebase_pool(pool:&mut Pool,matrix:Mat4){
 let rotation=matrix.to_scale_rotation_translation().1;
 for p in &mut pool.particles{p.pos=matrix.transform_point3(p.pos);p.vel=matrix.transform_vector3(p.vel);p.quat=rotation*p.quat;p.angvel=rotation*p.angvel;}
 pool.previous=pool.previous.map(|p|matrix.transform_point3(p));pool.inherit=matrix.transform_vector3(pool.inherit);
 for child in &mut pool.children{rebase_pool(&mut child.pool,matrix);}
}
fn draw_quads(def:&ParticleEmitterDef,pool:&Pool,matrix:Mat4,right:Vec3,up:Vec3,instance_scale:f32,blend:u8,blob:&mut Vec<u8>)->Result<Vec<Value>,String>{
let offset=blob.len();let mut indices=Vec::new();let mut count=0u32;let mut lo=Vec3::splat(f32::INFINITY);let mut hi=Vec3::splat(f32::NEG_INFINITY);
        let mut quad=|corners:[Vec3;4],uv:[[f32;2];4],color:[f32;4]|->Result<(),String>{
            let normal=qt((corners[1]-corners[0]).cross(corners[3]-corners[0]).normalize_or(Vec3::Z));
            for (position,tex) in corners.into_iter().zip(uv){let p=qt(position);if !p.is_finite()||tex.iter().chain(color.iter()).any(|x|!x.is_finite()){return Err("non-finite particle quad".into());}lo=lo.min(p);hi=hi.max(p);for value in p.to_array().into_iter().chain(normal.to_array()).chain(tex).chain(color){blob.extend_from_slice(&value.to_le_bytes());}}
            indices.extend([count,count+1,count+2,count,count+2,count+3]);count+=4;Ok(())
        };
        for p in &pool.particles {
            let noise=NOISE[((def.twinkle_speed*p.age).clamp(0.,255.) as u32).wrapping_add(p.phase) as usize&127];
            if def.twinkle_percent<1.&&noise>def.twinkle_percent{continue;}
            let ol=def.over_life.sample((p.age/p.life).clamp(0.,1.));let center=if def.model_space(){matrix.transform_point3(p.pos)}else{p.pos};
            let half=ol.size*def.twinkle(noise)*if def.scale_size_by_instance(){matrix.x_axis.truncate().length()}else{1./instance_scale.abs().max(1e-4)};
            let uv=|cell:u16|{let x=(cell&(def.tile_cols-1)) as f32/def.tile_cols as f32;let y=(cell>>def.tile_cols.trailing_zeros()) as f32/def.tile_rows as f32;let u=1./def.tile_cols as f32;let v=1./def.tile_rows as f32;[[x,y+v],[x+u,y+v],[x+u,y],[x,y]]};
            if def.head_tail!=1 {
                let (r,u)=if def.xy_quad(){(matrix.transform_vector3(Vec3::Y),matrix.transform_vector3(-Vec3::X))}else{(right,up)};
                let a=def.spin*p.age;let a=if a<0.&&p.phase&0x20!=0{-a}else{a};let (s,c)=a.sin_cos();let (r,u)=((r*c+u*s)*half,(u*c-r*s)*half);
                quad([center-r-u,center+r-u,center+r+u,center-r+u],uv(ol.head_cell),ol.color)?;
            }
            if def.head_tail>=1 {
                let vel=if def.model_space(){matrix.transform_vector3(p.vel)}else{p.vel};let time=if def.tail_clamps_to_age(){def.tail_time.min(p.age)}else{def.tail_time};let tail=-vel*time;
                let (r,u)=(tail.dot(right),tail.dot(up));let l2=r*r+u*u;
                if l2<7.7e-4{let (r,u)=(right*half,up*half);quad([center-r-u,center+r-u,center+r+u,center-r+u],uv(ol.tail_cell),ol.color)?;}
                else{let perp=(up*r-right*u)*(half/l2.sqrt());let quv=uv(ol.tail_cell);quad([center-perp,center+perp,center+tail+perp,center+tail-perp],[quv[0],quv[3],quv[2],quv[1]],ol.color)?;}
            }
        }
        // A stable empty batch avoids Qt zero-buffer errors; it remains invisible.
        if count==0{lo=Vec3::ZERO;hi=Vec3::ZERO;blob.extend_from_slice(&[0u8;192]);indices.extend([0,1,2,0,2,3]);count=4;}
        let texture=def.texture.clone();
        Ok(vec![json!({"offset":offset,"vertices":count,"indices":indices,"bounds":[lo.to_array(),hi.to_array()],"stride":48,"capacity":MAX_PARTICLES*8,"texture":texture,"blend":blend,"unlit":!def.lit,"vertex_colors":true,"alpha":if pool.particles.is_empty(){0.}else{1.},"visible":!pool.particles.is_empty(),"tint":[1.,1.,1.],"uv_offset":[0.,0.],"uv_scale":[1.,1.],"uv_rotation":[1.,0.],"wrap_u":true,"wrap_v":true,"no_fog":false})])
}
fn draw_models(def:&ParticleEmitterDef,pool:&Pool,model:&Model,matrix:Mat4,instance_scale:f32,blob:&mut Vec<u8>)->Result<Vec<Value>,String>{
 let (meshes,blends)=model.particle_forms();let mut rows=Vec::new();
 let basis=Mat4::from_cols(qt(Vec3::X).extend(0.),qt(Vec3::Y).extend(0.),qt(Vec3::Z).extend(0.),Vec3::ZERO.extend(1.));
 let instance_offset=blob.len();let instance_count=pool.particles.len().min(MAX_MODELS);
 for p in pool.particles.iter().take(MAX_MODELS){
  let ol=def.over_life.sample((p.age/p.life).clamp(0.,1.));let size=ol.size*if def.scale_size_by_instance(){matrix.x_axis.truncate().length()}else{1./instance_scale.abs().max(1e-4)};
  let center=if def.model_space(){matrix.transform_point3(p.pos)}else{p.pos};let rotation=if def.model_space(){matrix.to_scale_rotation_translation().1*p.quat}else{p.quat};
  let frame=basis*Mat4::from_scale_rotation_translation(Vec3::splat(size),rotation,center)*basis.inverse();
  let columns=frame.to_cols_array_2d();
  // Public Qt InstanceTableEntry: three affine rows, RGBA, four custom floats.
  for r in 0..3{for column in &columns{let x=column[r];if !x.is_finite(){return Err("non-finite particle instance transform".into());}blob.extend_from_slice(&x.to_le_bytes());}}
  for x in ol.color.into_iter().chain([0.;4]){if !x.is_finite(){return Err("non-finite particle instance color".into());}blob.extend_from_slice(&x.to_le_bytes());}
 }
 for (mesh,blend) in meshes.iter().zip(blends){
  let count=mesh.positions.len();let index_capacity=mesh.indices.len();
  if count==0||count>65536||index_capacity>393216||blob.len()+count*32>8*1024*1024{return Err("particle model draw capacity exceeded".into());}
  let offset=blob.len();let mut lo=Vec3::splat(f32::INFINITY);let mut hi=Vec3::splat(f32::NEG_INFINITY);
  for (i,position) in mesh.positions.iter().enumerate(){
   let pos=qt(Vec3::from_array(*position));let normal=qt(Vec3::from_array(mesh.normals.get(i).copied().unwrap_or([0.,0.,1.]))).normalize_or(Vec3::Y);let uv=mesh.uvs.get(i).copied().unwrap_or([0.,0.]);
   if !pos.is_finite()||!normal.is_finite()||uv.iter().any(|x|!x.is_finite()){return Err("non-finite particle model vertex".into());}
   lo=lo.min(pos);hi=hi.max(pos);for x in pos.to_array().into_iter().chain(normal.to_array()).chain(uv){blob.extend_from_slice(&x.to_le_bytes());}
  }
  rows.push(json!({"offset":offset,"vertices":count,"indices":mesh.indices,"bounds":[lo.to_array(),hi.to_array()],"stride":32,"dynamic":false,"capacity":count,"index_capacity":index_capacity,"instances_finite":true,"instance_offset":instance_offset,"instance_count":instance_count,"instance_capacity":MAX_MODELS,"texture":mesh.texture,"blend":blend,"unlit":mesh.emissive,"two_sided":mesh.two_sided,"no_depth_test":mesh.no_depth_test,"no_depth_write":mesh.no_depth_write,"env_map":mesh.env_map,"no_fog":matches!(mesh.fog_policy,engine_formats_core::FogPolicy::Off),"vertex_colors":false,"alpha":1.,"visible":instance_count>0,"tint":[1.,1.,1.],"uv_offset":[0.,0.],"uv_scale":[1.,1.],"uv_rotation":[1.,0.],"wrap_u":mesh.wrap_x,"wrap_v":mesh.wrap_y,"model_particle":true}));
 }
 Ok(rows)
}
