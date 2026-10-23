//! Original LightCatalog sampling and DayNight curves, without a Bevy dependency.
use engine_formats_core::{Atmosphere,LightCatalog,Submersion,Chain};
use serde_json::{json,Value};
pub fn load(chain:&mut Chain)->Result<LightCatalog,String>{
    let mut total=0;
    for name in ["Light","LightParams","LightIntBand","LightFloatBand","LightSkybox"]{
        let path=format!("DBFilesClient\\{name}.dbc");let archive=chain.archive_for(&path).map_err(|e|e.to_string())?;
        let size=archive.file_size(&path).ok_or("lighting table missing")?;total+=size;
        if size>8*1024*1024||total>32*1024*1024{return Err("lighting table capacity exceeded".into());}
    }
    LightCatalog::load(chain).map_err(|e|e.to_string())
}
fn qt(p:glam::Vec3)->[f32;3]{[-p.z,p.y,p.x]}
pub fn sample(catalog:&LightCatalog,v:&Value)->Result<Value,String>{
    let map=v["map_id"].as_u64().and_then(|i|u32::try_from(i).ok()).ok_or("invalid lighting map")?;
    let a=v["position"].as_array().filter(|a|a.len()==3).ok_or("invalid lighting position")?;let mut pos=[0.;3];
    for (p,x) in pos.iter_mut().zip(a){*p=x.as_f64().ok_or("invalid lighting position")? as f32;}
    if pos.iter().any(|p|!p.is_finite()||p.abs()>2_000_000.){return Err("invalid lighting position".into());}
    let minute=v["minute"].as_f64().ok_or("invalid lighting time")? as f32;
    if !minute.is_finite()||!(0.0..1440.0).contains(&minute){return Err("invalid lighting time".into());}
    let submerged=match v["submersion"].as_str().unwrap_or("DRY"){"DRY"=>Submersion::Dry,"WATER"|"RAPIDS"=>Submersion::Water,"OCEAN"=>Submersion::Ocean,"MAGMA"=>Submersion::Magma,"SLIME"=>Submersion::Slime,_=>return Err("invalid lighting submersion".into())};
    let storm=v["storm_blend"].as_f64().unwrap_or(if v["stormy"]==true{1.}else{0.}) as f32;
    if !storm.is_finite()||!(0.0..=1.0).contains(&storm){return Err("invalid lighting storm blend".into());}
    let clear=catalog.sample_blended(map,pos,(minute*2.) as u32,false,submerged,v["ghost"]==true);
    let atmo=if storm>0.{clear.lerp(&catalog.sample_blended(map,pos,(minute*2.) as u32,true,submerged,v["ghost"]==true),storm)}else{clear};
    use crate::daynight as dn;
    let light=qt(-dn::sun_direction(minute));let night=dn::sidn_night_fraction(minute);
    let mut out=encode(&atmo);if let Some(far)=v["far_clip"].as_f64(){if !far.is_finite()||!(0.0..=10000.0).contains(&far){return Err("invalid lighting far clip".into());}if far>0.{let end=atmo.fog_end.min(far as f32);out["fog"]["far"]=json!(end);out["fog"]["near"]=json!(end*atmo.fog_start_frac);}}out["minute"]=json!(minute);out["to_light"]=json!(light);out["sidn"]=json!(night);out["submersion"]=json!(v["submersion"].as_str().unwrap_or("DRY"));
    out["skybox"]=json!(if v["ghost"]==true{catalog.ghost_skybox(map,pos)}else{None});
    out["ocean_depth_factors"]=json!(submerged.ocean_depth_factors(pos[2]));
    out["sky_warp"]=json!(dn::sky_warp(minute,atmo.highlight_sky));
    out["sun_azimuth"]=json!(light[2].atan2(light[0]));out["stars_alpha"]=json!(dn::star_alpha(minute));
    let days=v["day_count"].as_u64().unwrap_or(0);if days>1_000_000{return Err("lighting day counter exceeded".into());}
    let (moon02,moon02_size)=dn::moon02_state(days as f64+minute as f64/1440.);
    out["bodies"]=json!({"sun":{"direction":qt(dn::celestial_sun_direction(minute)),"scale":dn::sun_disc_scale(minute),"flare":dn::sun_flare_dn(minute)},"moon":{"direction":qt(dn::moon_direction(minute)),"scale":dn::moon_disc_scale(minute),"flare":dn::moon_flare_dn(minute)},"moon02":{"direction":qt(moon02),"scale":moon02_size,"color":[0.,0.,0.]}});
    out["storm_blend"]=json!(storm);out["cloud_glow"]=json!({"strength":dn::cloud_glow_track(minute),"sun":dn::cloud_glow_is_sun(minute)});Ok(out)
}
fn encode(a:&Atmosphere)->Value{
    json!({"source":"ORIGINAL_LIGHT_DBC","fog":{"near":a.fog_end*a.fog_start_frac,"far":a.fog_end,"color":a.fog_color},"ambient":a.ambient,"diffuse":a.sun_diffuse,"sun_color":a.sun_color,"sky":a.sky,"water_river":a.water_river,"water_ocean":a.water_ocean,"water_river_alpha":a.water_river_alpha,"water_ocean_alpha":a.water_ocean_alpha,"glow":a.glow,"highlight_sky":a.highlight_sky,"cloud_density":a.cloud_density,"cloud_colors":a.cloud_colors})
}
