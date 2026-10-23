//! Exact birth-time downward queries against resident walking triangles.
//! World collision vertices already carry the placement and origin transform.
use glam::Vec3;
use serde_json::Value;
use std::collections::HashMap;
const CELL:f32=32.;
pub struct Page {triangles:Vec<[Vec3;3]>,grid:HashMap<(i32,i32),Vec<usize>>,pub bytes:usize}
impl Page {
 pub fn new(metadata:&Value,blob:&[u8])->Result<Self,String>{
  let mut page=Self{triangles:Vec::new(),grid:HashMap::new(),bytes:0};
  let mut rows:Vec<&Value>=metadata["collision"].as_array().ok_or("missing walking collision")?.iter().collect();
  if metadata["groups"].as_array().is_some_and(|groups|groups.is_empty()){rows.extend(metadata["rows"].as_array().ok_or("missing world geometry")?.iter().filter(|row|row["kind"]=="terrain"));}
  for row in rows{
   let start=row["offset"].as_u64().ok_or("invalid collision offset")? as usize;
   let count=row["vertices"].as_u64().ok_or("invalid collision vertices")? as usize;
   let stride=row["stride"].as_u64().unwrap_or(32) as usize;
   if count>65536||!matches!(stride,32|48)||start.checked_add(count*stride).is_none_or(|end|end>blob.len()){return Err("invalid collision buffer".into());}
   let indices=row["indices"].as_array().ok_or("missing collision indices")?;
   if indices.len()%3!=0||indices.len()>393216{return Err("invalid collision triangle count".into());}
   for ids in indices.chunks_exact(3){
    let mut points=[Vec3::ZERO;3];
    for (p,id) in points.iter_mut().zip(ids){
     let index=id.as_u64().ok_or("invalid collision index")? as usize;if index>=count{return Err("invalid collision index".into());}
     let at=start+index*stride;let f=|o|f32::from_le_bytes(blob[at+o..at+o+4].try_into().unwrap());
     *p=Vec3::new(f(0),-f(8),f(4));if !p.is_finite(){return Err("non-finite collision triangle".into());}
    }
    page.push(points)?;
   }
  }
  Ok(page)
 }
 pub fn empty()->Self{Self{triangles:Vec::new(),grid:HashMap::new(),bytes:0}}
 pub fn count(&self)->usize{self.triangles.len()}
 fn push(&mut self,points:[Vec3;3])->Result<(),String>{
    let lo=points[0].min(points[1]).min(points[2]);let hi=points[0].max(points[1]).max(points[2]);
    let x0=(lo.x/CELL).floor() as i32;let x1=(hi.x/CELL).floor() as i32;let y0=(lo.y/CELL).floor() as i32;let y1=(hi.y/CELL).floor() as i32;
    let nx=i64::from(x1)-i64::from(x0)+1;let ny=i64::from(y1)-i64::from(y0)+1;
    if nx>4096||ny>4096||nx*ny>4096{return Err("collision triangle spans too many cells".into());}
    let id=self.triangles.len();self.triangles.push(points);self.bytes+=std::mem::size_of::<[Vec3;3]>();
    for x in x0..=x1{for y in y0..=y1{
     let bucket=self.grid.entry((x,y)).or_insert_with(||{self.bytes+=64;Vec::new()});bucket.push(id);self.bytes+=std::mem::size_of::<usize>();
    }}
    if self.bytes>64*1024*1024{return Err("native walking collision capacity exceeded".into());}
  Ok(())
 }
 pub fn append(&mut self,rows:&Value)->Result<(),String>{
  let rows=rows.as_array().filter(|a|a.len()<=256).ok_or("collision restore packet capacity exceeded")?;
  for triangle in rows{
   let triangle=triangle.as_array().filter(|a|a.len()==3).ok_or("invalid restored triangle")?;let mut points=[Vec3::ZERO;3];
   for (p,row) in points.iter_mut().zip(triangle){
    let row=row.as_array().filter(|a|a.len()==3).ok_or("invalid restored point")?;let mut xyz=[0.;3];
    for (v,n) in xyz.iter_mut().zip(row){*v=n.as_f64().ok_or("invalid restored coordinate")? as f32;}
    *p=Vec3::new(xyz[0],-xyz[2],xyz[1]);if !p.is_finite(){return Err("non-finite restored collision triangle".into());}
   }
   self.push(points)?;
  }
  Ok(())
 }
 pub fn down(&self,position:Vec3)->Option<f32>{self.down_to(position,20.)}
 pub fn down_to(&self,position:Vec3,max_depth:f32)->Option<f32>{
  let bucket=self.grid.get(&((position.x/CELL).floor() as i32,(position.y/CELL).floor() as i32))?;let mut hit=None;
  for id in bucket{
   let [a,b,c]=self.triangles[*id];let u=b-a;let v=c-a;let p=position-a;let d=u.x*v.y-v.x*u.y;if d.abs()<1e-8{continue;}
   let s=(p.x*v.y-v.x*p.y)/d;let t=(u.x*p.y-p.x*u.y)/d;
   if s< -1e-5||t< -1e-5||s+t>1.00001{continue;}
   let z=a.z+s*u.z+t*v.z;let distance=position.z-z;
   if distance>= -1e-5&&distance<=max_depth&&hit.is_none_or(|old|z>old){hit=Some(z);}
  }
  hit
 }
}
pub fn down(pages:&HashMap<String,Page>,position:Vec3)->Option<f32>{pages.values().filter_map(|p|p.down(position)).max_by(f32::total_cmp)}
