//! Original procedural cloud coverage and color, consumed by retained Qt data.
mod kernel;
mod tables;
use kernel::{CloudKernel,CloudFrame,COLS};
use serde_json::{Value,json};
#[derive(Default)]
pub struct Clouds {kernel:CloudKernel,clock:Option<u64>,submerged:bool}
fn rgb(v:&Value)->[f32;3]{std::array::from_fn(|i|v[i].as_f64().unwrap_or(0.) as f32)}
fn bevy(v:&Value)->glam::Vec3 {let p=rgb(v);glam::Vec3::new(p[2],p[1],-p[0])}
impl Clouds {
    pub fn sample(&mut self,light:&mut Value,v:&Value,blob:&mut Vec<u8>)->Result<(),String>{
        let clock=v["clock_ms"].as_u64().unwrap_or(0);let wet=light["submersion"]!="DRY";
        let colors=&light["cloud_colors"];let sun=light["cloud_glow"]["sun"]==true;
        let frame=CloudFrame{sun:rgb(&colors[0]),slope:rgb(&colors[1]),gbase:rgb(&colors[2]),bcc:light["storm_blend"].as_f64().unwrap_or(0.) as f32,glow_dir:bevy(&light["bodies"][if sun{"sun"}else{"moon"}]["direction"]),glow_track:light["cloud_glow"]["strength"].as_f64().unwrap_or(0.) as f32};
        let density=light["cloud_density"].as_f64().unwrap_or(0.) as f32;
        if self.clock.is_none()||self.clock.is_some_and(|last|clock<last)||(self.submerged&&!wet){self.kernel.rebuild(density,&frame);}
        else {let dt=(clock-self.clock.unwrap()) as f32/1000.;if !self.kernel.tick(dt,density,&frame){self.kernel.recolor(&frame);}}
        self.clock=Some(clock);self.submerged=wet;let offset=blob.len();blob.extend_from_slice(self.kernel.rgba().as_flattened());
        let sun_cover=self.kernel.coverage(bevy(&light["bodies"]["sun"]["direction"])*12.);let moon_cover=self.kernel.coverage(bevy(&light["bodies"]["moon"]["direction"])*12.);
        light["clouds"]=json!({"width":COLS,"height":COLS,"offset":offset,"visible":!wet,"occlusion_sun":kernel::occ1_sun(sun_cover),"occlusion_moon":kernel::occ1_moon(moon_cover),"coverage_sun":self.kernel.coverage(bevy(&light["bodies"]["sun"]["direction"])*12.),"coverage_moon":self.kernel.coverage(bevy(&light["bodies"]["moon"]["direction"])*12.)});
        light["blob_bytes"]=json!(blob.len());light["blob_kind"]=json!("cloud_rgba");Ok(())
    }
}
