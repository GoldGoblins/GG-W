//! Scoped Qt adapter over the unchanged original WDL loader, mesher and height oracle.
use engine_formats_core::{Chain,WdlFile};
use serde_json::{json,Value};

// WdlFile owns 4096 inline Option<MareTile>s, including absent tiles. Account
// conservatively for that allocation, rather than just the present heights.
pub const RESIDENT_BYTES:usize=4096*1096+128;
pub fn load(chain:&mut Chain,map:&str,blob:&mut Vec<u8>)->Result<(WdlFile,Value),String>{
    if map.is_empty()||map.len()>64||!map.bytes().all(|c|c.is_ascii_alphanumeric()||c==b'_'){return Err("invalid WDL map directory".into());}
    let name=format!("World\\Maps\\{map}\\{map}.wdl");
    let archive=chain.archive_for(&name).map_err(|e|e.to_string())?;
    if archive.file_size(&name).ok_or("WDL entry not found")? as usize>8*1024*1024{return Err("WDL source capacity exceeded".into());}
    let wdl=WdlFile::load(chain,map).map_err(|e|e.to_string())?;let mut tiles=Vec::new();
    for (x,y) in wdl.present_tiles(){
        let mesh=wdl.tile_mesh(x,y).ok_or("WDL present tile has no mesh")?;let offset=blob.len();
        // Preserve the original corner/centre ordering in a compact immutable
        // GUI-side oracle; no duplicate f32 positions or Python float arrays.
        for point in mesh.positions{blob.extend_from_slice(&(point[2] as i16).to_le_bytes());}
        tiles.push(json!({"x":x,"y":y,"offset":offset}));
    }
    let result=json!({"format":"WDL","tiles":tiles,"native_bytes":RESIDENT_BYTES,"blob_kind":"wdl_heights_i16","blob_bytes":blob.len()});
    Ok((wdl,result))
}
fn vector(value:&Value)->Result<[f32;3],String>{
    let a=value.as_array().filter(|a|a.len()==3).ok_or("invalid WDL coordinate")?;let mut out=[0.;3];
    for (o,v) in out.iter_mut().zip(a){let n=v.as_f64().ok_or("invalid WDL coordinate")?;if !n.is_finite()||n.abs()>2e6{return Err("invalid WDL coordinate".into());}*o=n as f32;}Ok(out)
}
pub fn sample(wdl:&WdlFile,v:&Value,blob:&mut Vec<u8>)->Result<Value,String>{
    if v["op"]=="wdl_heights"{
        let points=v["points"].as_array().filter(|a|a.len()<=1536).ok_or("WDL height query capacity exceeded")?;
        return Ok(json!(points.iter().map(|p|{let p=vector(p)?;Ok(wdl.height_at(p[0],p[1]))}).collect::<Result<Vec<_>,String>>()?));
    }
    let tiles=v["tiles"].as_array().filter(|a|a.len()<=8).ok_or("WDL tile batch capacity exceeded")?;
    let origin=vector(&v["origin"])?;let mut rows=Vec::new();
    for tile in tiles{
        let xy=tile.as_array().filter(|a|a.len()==2).ok_or("invalid WDL tile")?;
        let x=xy[0].as_u64().filter(|n|*n<64).ok_or("invalid WDL tile")? as u32;let y=xy[1].as_u64().filter(|n|*n<64).ok_or("invalid WDL tile")? as u32;
        let Some(mesh)=wdl.tile_mesh(x,y) else{continue};let offset=blob.len();let mut lo=[f32::INFINITY;3];let mut hi=[f32::NEG_INFINITY;3];
        for p in &mesh.positions{
            let p=[p[0]-origin[0],p[2]-origin[2],origin[1]-p[1]];
            for i in 0..3{lo[i]=lo[i].min(p[i]);hi[i]=hi[i].max(p[i]);}
            for n in [p[0],p[1],p[2],0.,1.,0.,0.,0.]{blob.extend_from_slice(&n.to_le_bytes());}
        }
        rows.push(json!({"kind":"wdl","tile":[x,y],"offset":offset,"stride":32,"vertices":mesh.positions.len(),"indices":mesh.indices,"bounds":[lo,hi],"blend":0,"visible":true}));
    }
    Ok(json!({"format":"WDL_RING","rows":rows,"blob_kind":"vertices","blob_bytes":blob.len()}))
}
