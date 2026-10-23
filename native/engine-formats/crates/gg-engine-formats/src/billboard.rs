//! Original billboard palette law in raw model/WoW axes, shared by art and effects.
//! See engine-world/src/billboard.rs and rig_anim/compose.rs (MIT/Apache-2.0).
use engine_formats_core::BillboardKind;
use glam::{Mat3,Mat4,Quat,Vec3};
use serde_json::Value;

pub fn camera(v:&Value)->Result<Option<(Vec3,Vec3,Vec3)>,String>{
    if v["view"].is_null(){return Ok(None);}
    let read=|key:&str|->Result<Vec3,String>{
        let a=v["view"][key].as_array().filter(|a|a.len()==3).ok_or("invalid pose camera basis")?;
        let mut p=[0.;3];for (out,x) in p.iter_mut().zip(a){*out=x.as_f64().ok_or("invalid pose camera basis")? as f32;}
        let p=Vec3::new(p[0],-p[2],p[1]);
        if !p.is_finite()||p.length_squared()<1e-12{return Err("invalid pose camera basis".into());}Ok(p.normalize())
    };
    let f=read("forward")?;let u=read("up")?;let r=f.cross(u);
    if r.length_squared()<1e-12{return Err("degenerate pose camera basis".into());}
    let r=r.normalize();Ok(Some((f,r,r.cross(f))))
}

pub fn replace(kind:BillboardKind,matrix:Mat4,pivot:Vec3,cam:(Vec3,Vec3,Vec3))->Mat4{
    let (scale,rot,_)=matrix.to_scale_rotation_translation();let (f,r,u)=cam;
    let (x,y,z)=match kind{
        BillboardKind::Spherical=>(-f,r,u),
        BillboardKind::LockZ=>{let z=(rot*Vec3::Z).normalize_or(Vec3::Z);let y=f.cross(z).normalize_or(r);(y.cross(z),y,z)},
        BillboardKind::LockX=>{let x=(rot*Vec3::X).normalize_or(-f);let z=f.cross(x).normalize_or(u);(x,z.cross(x),z)},
        BillboardKind::LockY=>{let y=(rot*Vec3::Y).normalize_or(r);let x=f.cross(y).normalize_or(-f);(x,y,x.cross(y))},
    };
    let rot=Quat::from_mat3(&Mat3::from_cols(x,y,z));
    let mut out=Mat4::from_scale_rotation_translation(scale,rot,Vec3::ZERO);
    out.w_axis=(matrix.transform_point3(pivot)-out.transform_vector3(pivot)).extend(1.);out
}
