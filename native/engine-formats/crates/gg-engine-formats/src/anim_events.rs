//! Original (prev, cur] event windows over a retained Qt model instance.
//! The original parser owns tags and timestamps. This adapter bounds catch-up
//! after pauses and reports discarded windows instead of playing stale audio.
use engine_formats_core::ModelAnimation;
use glam::{Mat4,Vec3};
use serde_json::{json,Value};

#[derive(Default)]
pub struct Track {last:Option<(usize,u64,u64,f32,bool)>}
impl Track {
 pub fn sample(&mut self,clip:Option<&ModelAnimation>,matrices:&[Mat4],root:Mat4,v:&Value)->Result<Value,String>{
    let Some(clip)=clip else{self.last=None;return Ok(json!({"keys":[]}));};
    let raw=v["cursor_ms"].as_u64().unwrap_or(0);let clock=v["clock_ms"].as_u64().unwrap_or(raw);
    let repeat=clip.looping||v["repeat"]==true;
    // M2 bands are integral milliseconds. Dividing a double cursor by a
    // rounded f32 duration shifts e.g. the 333 ms wrap to 334 ms.
    let duration_ms=u64::from(clip.end_ms-clip.start_ms);
    if duration_ms==0{return Err("invalid M2 event duration".into());}
    let cur=if repeat{(raw%duration_ms) as f32/1000.}else{raw.min(duration_ms) as f32/1000.};
    let previous=self.last.replace((clip.seq_index,raw,clock,cur,false));
    let Some((seq,was_raw,was_clock,was_seek,armed))=previous else{
        self.last=Some((clip.seq_index,raw,clock,cur,true));return Ok(json!({"keys":[],"reset":"ARM"}));
    };
    if seq!=clip.seq_index||raw<was_raw||clock<was_clock{
        self.last=Some((clip.seq_index,raw,clock,cur,true));return Ok(json!({"keys":[],"reset":"SEEK"}));
    }
    if raw==was_raw{self.last=Some((clip.seq_index,raw,clock,cur,armed));return Ok(json!({"keys":[]}));}
    if clock-was_clock>1000||raw-was_raw>2000{
        return Ok(json!({"keys":[],"reset":"GAP","discarded_window":true}));
    }
    let first_cycle=if repeat{was_raw/duration_ms}else{0};
    let last_cycle=if repeat{raw/duration_ms}else{0};
    if last_cycle-first_cycle>4{return Ok(json!({"keys":[],"reset":"GAP","discarded_window":true}));}
    let mut keys=Vec::new();let mut dropped=0;
    for cycle in first_cycle..=last_cycle{
        let lo=if cycle==first_cycle{if armed&&was_seek<=0.25{-1.}else{was_seek}}else{-1.};
        let hi=if cycle==last_cycle{cur}else{clip.duration+1.};
        for e in &clip.events{
            if e.time<=lo||e.time>hi{continue;}
            if keys.len()>=64{dropped+=1;continue;}
            let at=matrices.get(e.bone as usize).copied().unwrap_or(root).transform_point3(Vec3::from_array(e.position));
            if !at.is_finite(){return Err("non-finite M2 event position".into());}
            keys.push(json!({"tag":String::from_utf8_lossy(&e.ident),"data":e.data,"anim_id":clip.anim_id,"bone":e.bone,"time_ms":(e.time as f64*1000.).round() as u64,"position":[at.x,at.z,-at.y]}));
        }
    }
    Ok(json!({"keys":keys,"dropped":dropped}))
 }
}
