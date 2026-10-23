//! Keep live world-space trails fixed when their retained pane root moves.
use glam::Mat4;
use serde_json::{Value,json};
use crate::runtime::Model;

pub fn parent(v:&Value)->Result<Mat4,String>{
    if v["world_instance"]==true{return Ok(Mat4::IDENTITY);}
    Model::anchor(&json!({"anchor":v["pane_anchor"]}))
}
pub fn delta(previous:&mut Option<Mat4>,current:Mat4)->Mat4{
    let delta=previous.map_or(Mat4::IDENTITY,|old|current.inverse()*old);
    *previous=Some(current);delta
}
