//! Original celestial frames and the assetless star mesh from engine-world/src/sun.
//! Pure math adapted from follow.rs and mesh.rs; MIT/Apache-2.0.
use glam::{Vec3,Quat};
use serde_json::{Value,json};
fn qt(p:Vec3)->[f32;3]{[-p.z,p.y,p.x]}
fn bevy(v:&Value)->Vec3{Vec3::new(v[2].as_f64().unwrap_or(0.) as f32,v[1].as_f64().unwrap_or(0.) as f32,-(v[0].as_f64().unwrap_or(0.) as f32))}
fn hash01(n:u32)->f32{let mut x=n.wrapping_mul(747796405).wrapping_add(2891336453);x=(x^(x>>16)).wrapping_mul(2246822519);x^=x>>13;(x&0xffffff) as f32/16777216.}
pub fn stars(model:Option<&crate::runtime::Model>,blob:&mut Vec<u8>)->Result<Value,String>{
 let mut rows=Vec::new();
 if let Some(model)=model{
  let (meshes,_)=model.particle_forms();let radius=meshes.iter().flat_map(|m|&m.positions).map(|p|Vec3::from_array(*p).length()).fold(0.,f32::max).max(1e-3);
  for mesh in meshes{
   let offset=blob.len();let mut lo=Vec3::splat(f32::INFINITY);let mut hi=Vec3::splat(f32::NEG_INFINITY);
   for (i,p) in mesh.positions.iter().enumerate(){let p=Vec3::from_array(*p)/radius;let p=Vec3::new(p.x,p.z,-p.y);lo=lo.min(p);hi=hi.max(p);let uv=mesh.uvs.get(i).copied().unwrap_or([0.,0.]);for v in p.to_array().into_iter().chain((-p).to_array()).chain(uv){blob.extend_from_slice(&v.to_le_bytes());}}
   let weight=mesh.alpha_anim.as_ref().map_or(1.,|a|a.sample(None,0.,0.));
   let blue=mesh.texture.as_deref().is_some_and(|s|s.to_lowercase().contains("stars2"));
   rows.push(json!({"offset":offset,"vertices":mesh.positions.len(),"indices":mesh.indices,"bounds":[lo.to_array(),hi.to_array()],"stride":32,"texture":if blue{"Environments/Stars/Stars2.blp"}else{"Environments/Stars/Stars.blp"},"weight":weight}));
  }
 }
 if rows.is_empty(){
  let offset=blob.len();let mut indices=Vec::new();
  for i in 0..350u32{
   let az=hash01(i*3)*std::f32::consts::TAU;let y=0.04+0.95*hash01(i*3+1);let size=0.0022*(0.6+0.9*hash01(i*3+2));let h=(1.-y*y).max(0.).sqrt();let dir=Vec3::new(h*az.cos(),y,h*az.sin());let mut r=dir.cross(Vec3::Y);if r.length_squared()<1e-6{r=dir.cross(Vec3::X);}let r=r.normalize();let up=dir.cross(r).normalize();
   for (x,y,uv) in [(-1.,-1.,[0.,1.]),(1.,-1.,[1.,1.]),(1.,1.,[1.,0.]),(-1.,1.,[0.,0.])]{let p=qt(dir+(r*x+up*y)*size);for v in p.into_iter().chain(qt(-dir)).chain(uv){blob.extend_from_slice(&v.to_le_bytes());}}
   let base=i*4;indices.extend([base,base+1,base+2,base,base+2,base+3]);
  }
  rows.push(json!({"offset":offset,"vertices":1400,"indices":indices,"bounds":[[-1.,0.,-1.],[1.,1.,1.]],"stride":32,"texture":null,"weight":1.}));
 }
 if blob.len()>8*1024*1024{return Err("star geometry capacity exceeded".into());}
 Ok(json!({"format":"SKY_STARS","authored":model.is_some(),"rows":rows,"blob_kind":"vertices","blob_bytes":blob.len()}))
}
#[derive(Default)]
pub struct Celestial {clock:Option<u64>,envelopes:[f32;2]}
impl Celestial {
 pub fn sample(&mut self,light:&mut Value,v:&Value)->Result<(),String>{
  let clock=v["clock_ms"].as_u64().unwrap_or(0);let reset=self.clock.is_some_and(|last|clock<last);if reset{self.envelopes=[0.;2];}
  let dt=self.clock.filter(|_|!reset).map_or(0.,|last|((clock-last) as f32/1000.).min(0.25));self.clock=Some(clock);
  let forward=bevy(&v["view_forward"]).normalize_or(Vec3::Z);let depth=v["submersion_depth"].as_f64().unwrap_or(0.) as f32;
  if !depth.is_finite()||depth<0.{return Err("invalid celestial submersion depth".into());}
  let storm=light["storm_blend"].as_f64().unwrap_or(0.) as f32;let seed=if storm>0.{Some((255.*(1.-storm.min(1.))).floor()/255.)}else{None};let mut sprites=Vec::new();
  for (i,name) in ["sun","moon","moon02"].into_iter().enumerate(){
   let body=&light["bodies"][name];let dir=bevy(&body["direction"]).normalize_or(Vec3::Y);let rotation=Quat::from_rotation_arc(Vec3::Z,-dir);let scale=body["scale"].as_f64().unwrap_or(1.) as f32;let size=0.0833*scale*if i==1{1.75}else{1.};let elev=dir.y.clamp(-1.,1.).asin();let half=(0.5*size).atan();let span=[((elev-half).sin()*4096.).round()/4096.,((elev+half).sin()*4096.).round()/4096.];
   let tint=if i==2{[0.;3]}else{std::array::from_fn(|j|(light["sun_color"][j].as_f64().unwrap_or(1.) as f32*255.).round()/255.)};
   sprites.push(json!({"name":name,"direction":qt(dir),"right":qt(rotation*Vec3::X),"up":qt(rotation*Vec3::Y),"size":size,"span":span,"alpha":seed.unwrap_or(if i==2{0.}else{1.}),"tint":tint,"glare":false}));
   if i<2{
    let f=((forward.dot(dir)-0.7)/0.3).clamp(0.,1.);let h=(dir.y/0.035).clamp(0.,1.);let dn=body["flare"].as_f64().unwrap_or(0.) as f32;let occ=light["clouds"][if i==0{"occlusion_sun"}else{"occlusion_moon"}].as_f64().unwrap_or(if i==0{1.}else{0.}) as f32;
    let visibility=v["flare_visibility"][i].as_f64().unwrap_or(1.) as f32;if !visibility.is_finite()||!(0.0..=1.0).contains(&visibility){return Err("invalid flare visibility".into());}
    let target=if v["interior"]==true{0.}else{dn*h*h*(3.-2.*h)*occ*(1.-(depth*0.1).clamp(0.,1.))*visibility};let rise=if i==0{4.}else{f32::from_bits(0x4041f07c)};let fall=f32::from_bits(0x3fc1f07c);self.envelopes[i]+=(target-self.envelopes[i]).clamp(-fall*dt,rise*dt);
    let alpha=((if i==0{0.5+0.5*f}else{0.1+0.9*f})*self.envelopes[i]*seed.unwrap_or(1.)*255.).round()/255.;
    sprites.push(json!({"name":format!("{name}_glare"),"direction":qt(dir),"right":qt(rotation*Vec3::X),"up":qt(rotation*Vec3::Y),"size":if i==0{(3.+17.*f)/12.}else{(2.*scale)/12.},"span":[0.,0.],"alpha":alpha,"tint":tint,"glare":true}));
   }
  }
  light["celestial_sprites"]=json!(sprites);Ok(())
 }
}
