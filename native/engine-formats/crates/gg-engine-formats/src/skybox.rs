//! Authored sky M2s: bind meshes and the original rotation-only BoneSpin sampler.
//! The Qt host supplies camera anchoring and the shared MFOG crossfade.
use engine_formats_core::{BoneSpin,ModelBlend};
use glam::{Quat,Vec3};
use serde_json::{json,Value};
pub struct Skybox {rows:Value,blob:Vec<u8>,spins:Vec<Option<BoneSpin>>,pub bytes:usize}
fn qt(p:[f32;3])->[f32;3]{[p[0],p[2],-p[1]]}
impl Skybox {
 pub fn new(bytes:Vec<u8>,dir:&str)->Result<Self,String>{
  let spins=engine_formats_core::m2_bone_spins(&bytes);
  let model=crate::runtime::Model::new(bytes,dir)?;let (meshes,raw)=model.particle_forms();
  if meshes.is_empty()||meshes.len()>512{return Err("skybox batch capacity exceeded".into());}
  let mut blob=Vec::new();let mut rows=Vec::new();let mut rigid=Vec::new();
  for (index,m) in meshes.iter().enumerate(){
   if m.positions.is_empty()||m.positions.len()>65536||m.indices.len()>393216||m.indices.len()%3!=0||m.indices.iter().any(|&i|i as usize>=m.positions.len()){return Err("invalid skybox geometry".into());}
   if blob.len()+m.positions.len()*32>8*1024*1024{return Err("skybox geometry capacity exceeded".into());}
   let offset=blob.len();let mut lo=Vec3::splat(f32::INFINITY);let mut hi=Vec3::splat(f32::NEG_INFINITY);
   for (i,&p) in m.positions.iter().enumerate(){
    let p=qt(p);lo=lo.min(Vec3::from_array(p));hi=hi.max(Vec3::from_array(p));
    let n=qt(m.normals.get(i).copied().unwrap_or([0.,0.,1.]));let uv=m.uvs.get(i).copied().unwrap_or([0.;2]);
    for v in p.into_iter().chain(n).chain(uv){if !v.is_finite(){return Err("non-finite skybox vertex".into());}blob.extend_from_slice(&v.to_le_bytes());}
   }
   let blend=raw.get(index).copied().unwrap_or(match m.blend{ModelBlend::Opaque=>0,ModelBlend::AlphaTest=>1,ModelBlend::Mod=>5,ModelBlend::Mod2x=>6,_=>2});
   // Exactly the whole-weight test used by skybox::sole_bone upstream.
   let spin=m.joints.first().and_then(|j|{
    (m.weights.len()==m.joints.len()&&m.joints.iter().zip(&m.weights).all(|(b,w)|b[0]==j[0]&&w[0]>0.999)).then(||spins.get(&j[0]).cloned()).flatten()
   });
   rows.push(json!({"offset":offset,"vertices":m.positions.len(),"indices":m.indices,"bounds":[lo.to_array(),hi.to_array()],"stride":32,"dynamic":false,"texture":m.texture,"blend":blend,"unlit":m.emissive,"two_sided":m.two_sided,"wrap_u":m.wrap_x,"wrap_v":m.wrap_y,"environment_map":m.env_map,"no_fog":matches!(m.fog_policy,engine_formats_core::FogPolicy::Off),"spinning":spin.is_some(),"order":index+1}));
   rigid.push(spin);
  }
  let rows=json!(rows);let bytes=blob.len()+rows.to_string().len()+rigid.iter().flatten().map(|s|std::mem::size_of::<BoneSpin>()+s.keys.len()*std::mem::size_of::<(f32,[f32;4])>()).sum::<usize>();
  Ok(Self{rows,blob,spins:rigid,bytes})
 }
 pub fn sample(&self,v:&Value,out:&mut Vec<u8>)->Result<Value,String>{
  let seconds=if v["clock_ms"].is_null(){0.}else{v["clock_ms"].as_f64().ok_or("invalid skybox clock")?/1000.};if !seconds.is_finite()||seconds<0.||seconds>1e12{return Err("invalid skybox clock".into());}
  let basis=Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2);
  let transforms:Vec<_>=self.spins.iter().map(|spin|{
   let (q,p)=spin.as_ref().map_or((Quat::IDENTITY,Vec3::ZERO),|s|{let q=basis*Quat::from_array(s.sample(seconds as f32))*basis.conjugate();let pivot=Vec3::from_array(qt(s.pivot));(q,pivot-q*pivot)});
   json!({"rotation":q.to_array(),"translation":p.to_array()})
  }).collect();
  let geometry=v["geometry"]!=false;if geometry{out.extend_from_slice(&self.blob);}
  Ok(json!({"format":"SKYBOX","rows":if geometry{self.rows.clone()}else{Value::Null},"transforms":transforms,"native_bytes":self.bytes,"blob_kind":"skybox","blob_bytes":out.len()}))
 }
}
