//! GG world-object adapter. Placement, MODR ownership, cap96/floor112 and
//! SH equations follow GgEngine coords.rs, wmo.rs and lighting/sh.rs (MIT/Apache-2.0).
use engine_formats_core::{WmoRoot,WmoLight,wmo_group_doodad_refs,wmo_group_light_refs};
use glam::{Mat4,Quat,Vec3,Vec4};
use serde_json::{json,Value};

pub fn placement(rotation:[f32;3])->Quat {
    let r=rotation.map(f32::to_radians);
    Quat::from_rotation_x(std::f32::consts::FRAC_PI_2)*Quat::from_rotation_y(r[1]-std::f32::consts::PI)*Quat::from_rotation_z(-r[0])*Quat::from_rotation_x(r[2]-std::f32::consts::FRAC_PI_2)
}
pub fn matrix(v:&Value)->Result<Mat4,String> {
    let a=v.as_array().filter(|a|a.len()==16).ok_or("invalid world prop transform")?;
    let mut values=[0.;16];for (out,n) in values.iter_mut().zip(a){*out=n.as_f64().ok_or("invalid world prop number")? as f32;}
    let m=Mat4::from_cols_array(&values);
    if !m.is_finite()||values.iter().any(|x|x.abs()>1e6)||m.determinant().abs()<1e-8||values[3].abs()>1e-6||values[7].abs()>1e-6||values[11].abs()>1e-6||(values[15]-1.).abs()>1e-6{return Err("invalid world prop transform".into());}Ok(m)
}
pub fn prop(model:&str,id:String,m:Mat4,groups:Vec<u16>,light:Value)->Result<Value,String> {
    if model.is_empty()||model.len()>1024||!m.is_finite(){return Err("invalid world prop placement".into());}
    let mut path=model.replace('\\',"/");
    if path.to_ascii_lowercase().ends_with(".mdx")||path.to_ascii_lowercase().ends_with(".mdl"){path.truncate(path.len()-4);path.push_str(".m2");}
    matrix(&json!(m.to_cols_array()))?;
    Ok(json!({"model":path,"prop_key":id,"anchor":m.to_cols_array(),"owning_groups":groups,"light":light}))
}
fn qt(v:Vec3)->Vec3 {Vec3::new(v.x,v.z,-v.y)}
fn base(c:[u8;3])->([f32;3],[f32;3]) {
    let max=*c.iter().max().unwrap();
    let scale=if max>96{(96.*255./max as f32-0.5).round_ties_even() as u32}else{0};
    let ambient=c.map(|v|if max>96{((v as u32*scale+255)>>8) as f32/255.}else{v as f32/255.});
    let diffuse=c.map(|v|if max>0&&max<112{(v as u32*112/max as u32) as f32/255.}else{v as f32/255.});
    (ambient,diffuse)
}
fn probe(ambient:[f32;3],lobes:&[(Vec3,[f32;3])])->[[f32;4];7] {
    let mut c=[Vec4::ZERO;7];for ch in 0..3{c[ch].w=ambient[ch];}c[6].w=1.;
    let k=4./17.;
    for (u,color) in lobes {
        let u=u.normalize_or_zero();let (x,y,z)=(u.x,u.y,u.z);
        for ch in 0..3 {let s=color[ch];
            c[ch]+=Vec4::new(2.*k*s*x,2.*k*s*y,2.*k*s*z,s*k*(0.375+0.9375*(x*x+y*y)));
            c[ch+3]+=Vec4::new(3.75*k*s*x*y,3.75*k*s*y*z,1.875*k*s*(z*z-0.5*(x*x+y*y)),3.75*k*s*x*z);
            c[6][ch]+=s*0.9375*k*(x*x-y*y);
        }
    }c.map(|v|v.to_array())
}
pub struct WmoProps {refs:Vec<Vec<u16>>,light_refs:Vec<Vec<u16>>}
impl WmoProps {
    pub fn new(count:usize)->Result<Self,String>{if count>4096{return Err("WMO prop capacity exceeded".into());}Ok(Self{refs:vec![Vec::new();count],light_refs:Vec::new()})}
    pub fn group(&mut self,gi:u16,bytes:&[u8],lights:&[WmoLight])->Result<(),String>{
        let refs=wmo_group_doodad_refs(bytes);let lr=wmo_group_light_refs(bytes);
        if refs.len()>8192||lr.len()>64{return Err("WMO prop/light reference capacity exceeded".into());}
        for di in refs{let groups=self.refs.get_mut(di as usize).ok_or("invalid MODR prop index")?;if groups.last()!=Some(&gi){groups.push(gi);}}
        if lr.iter().any(|&i|i as usize>=lights.len()){return Err("invalid MOLR light index".into());}
        self.light_refs.resize_with(self.light_refs.len().max(gi as usize+1),Vec::new);self.light_refs[gi as usize]=lr;Ok(())
    }
    pub fn finish(self,root:&WmoRoot,set:u16,world:Mat4,lights:&[WmoLight])->Result<Vec<Value>,String>{
        self.finish_limited(root,set,world,lights,128)
    }
    pub fn finish_limited(self,root:&WmoRoot,set:u16,world:Mat4,lights:&[WmoLight],limit:usize)->Result<Vec<Value>,String>{
        let mut selected=std::collections::BTreeSet::new();
        for si in [0,set]{
            if si==0&&set==0&&!selected.is_empty(){continue;}
            if let Some(s)=root.doodad_sets().get(si as usize){
                let end=s.start.checked_add(s.count).ok_or("invalid MODS range")? as usize;
                if end>root.doodads().len(){return Err("invalid MODS range".into());}
                selected.extend(s.start as usize..end);
            }
        }
        let mut out=Vec::new();
        for di in selected{
            let d=&root.doodads()[di];let groups=&self.refs[di];
            if d.model.is_empty()||groups.is_empty(){continue;}
            if out.len()>=limit{return Err(format!("selected WMO prop capacity exceeded ({limit})"));}
            let q=Quat::from_array(d.orientation);
            if !q.is_finite()||q.length_squared()<1e-12||!d.scale.is_finite()||d.scale<=0.||d.scale>64.{return Err("invalid MODD orientation/scale".into());}
            let local=Mat4::from_scale_rotation_translation(Vec3::splat(d.scale),q.normalize(),Vec3::from_array(d.position));let m=world*local;
            let interior=groups.iter().all(|&g|root.group_infos().get(g as usize).is_some_and(|g|g.interior));
            let light=if interior {
                let (ambient,diffuse)=base([d.color[0],d.color[1],d.color[2]]);let origin=qt(m.w_axis.truncate());
                let mut lobes=vec![(qt(Vec3::new(0.30822,0.30822,0.9)),diffuse)];let mut used=0;
                for &li in &self.light_refs[groups[0] as usize]{let l=&lights[li as usize];if !l.is_omni(){continue;}
                    if l.position.iter().chain(l.color.iter()).chain([&l.intensity,&l.attenuation_start,&l.attenuation_end]).any(|v|!v.is_finite()){return Err("non-finite MOLT light".into());}
                    let dv=qt(world.transform_point3(Vec3::from_array(l.position)))-origin;let dist=dv.length();
                    let gain=if dist<=l.attenuation_start{1.}else if dist>=l.attenuation_end||l.attenuation_end<=l.attenuation_start{0.}else{1.-(dist-l.attenuation_start)/(l.attenuation_end-l.attenuation_start)};
                    if gain>0.{lobes.push((dv/dist.max(1e-4),l.color.map(|c|c*l.intensity.max(0.)*gain)));used+=1;}
                }
                json!({"interior":true,"ambient":ambient,"diffuse":diffuse,"probe":probe(ambient,&lobes),"MOLR_lobes":used})
            }else{json!({"interior":false})};
            out.push(prop(&d.model,format!("modd:{di}"),m,groups.clone(),light)?);
        }Ok(out)
    }
}
