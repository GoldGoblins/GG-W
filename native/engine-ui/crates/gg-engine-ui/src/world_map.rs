//! GG geography and live body feeds through the unmodified original map API.
use engine_ui_core::script::{WorldMapContinentView,WorldMapZoneView,WorldMapLandmarkSource,WorldMapOverlayView};
use serde_json::{Value,json};
use crate::Host;

type Rect=(f32,f32,f32,f32);
#[derive(Clone)]
struct Zone { name:String, file:String, area:u32, rect:Rect, overlays:Vec<WorldMapOverlayView> }
#[derive(Clone)]
struct Continent { name:String, file:String, map:u32, rect:Rect, sheet:Rect, zones:Vec<Zone>, projection:Option<[f32;3]>, grid:Option<Vec<u16>> }
#[derive(Clone)]
struct Direct { id:u32, map:u32, zone:Zone }
#[derive(Clone)]
struct Catalog { world:Rect, continents:Vec<Continent>, direct:Vec<Direct>, wow:bool }
fn num(v:&Value)->Result<f32,String>{
    let n=v.as_f64().filter(|n|n.is_finite()&&n.abs()<=2_000_000.).ok_or("invalid map coordinate")?;
    Ok(n as f32)
}
fn id(v:&Value)->Result<u32,String>{v.as_u64().filter(|n|*n<=u32::MAX as u64).map(|n|n as u32).ok_or("invalid map identity".into())}
fn text(v:&Value)->Result<String,String>{v.as_str().filter(|s|s.len()<=128&&!s.chars().any(|c|c.is_control())).map(str::to_owned).ok_or("invalid map label".into())}
fn rect(v:&Value)->Result<Rect,String>{bounds(v,false)}
fn bounds(v:&Value,wow:bool)->Result<Rect,String>{
    let a=v.as_array().filter(|a|a.len()==4).ok_or("four map bounds required")?;
    let r=(num(&a[0])?,num(&a[1])?,num(&a[2])?,num(&a[3])?);
    if (if wow{r.0<=r.1}else{r.0>=r.1})||r.2<=r.3{return Err("empty map bounds".into());}Ok(r)
}
fn point(v:&Value)->Result<Option<(u32,u64,f32,f32)>,String>{
    if v.is_null(){return Ok(None);}
    let p=v["position"].as_array().filter(|a|a.len()==2).ok_or("map position required")?;
    Ok(Some((id(&v["map"])? ,v["instance"].as_u64().ok_or("map instance required")?,num(&p[0])?,num(&p[1])?)))
}
fn zone(v:&Value,wow:bool)->Result<Zone,String>{
    let mut overlays=Vec::new();
    if let Some(rows)=v["overlays"].as_array(){
        if rows.len()>128{return Err("map overlay capacity".into());}
        for row in rows{
            let hit=serde_json::from_value::<[u32;4]>(row["hit_rect"].clone()).map_err(|e|e.to_string())?;
            let bits=serde_json::from_value::<Vec<u32>>(row["explore_bits"].clone()).map_err(|e|e.to_string())?;
            if bits.len()>4||bits.iter().any(|b|*b>=2048){return Err("invalid overlay explore bits".into());}
            let texture=row["texture"].as_str().filter(|s|s.len()<=512).ok_or("invalid map overlay texture")?;
            let width=id(&row["width"])?;let height=id(&row["height"])?;
            if width>2048||height>2048{return Err("map overlay dimensions".into());}
            overlays.push(WorldMapOverlayView{texture:texture.into(),width,height,offset_x:id(&row["offset_x"])? ,offset_y:id(&row["offset_y"])? ,explore_bits:bits,hit_rect:(hit[0],hit[1],hit[2],hit[3]),area_name:row["area_name"].as_str().map(str::to_owned)});
        }
    }
    Ok(Zone{name:text(&v["name"])? ,file:text(&v["map_file"])? ,area:id(&v["area_id"])? ,rect:bounds(&v["rect"],wow)? ,overlays})
}
fn view(z:&Zone)->WorldMapZoneView{WorldMapZoneView{name:z.name.clone(),area_id:z.area,map_file:z.file.clone(),loc_rect:z.rect,overlays:z.overlays.clone()}}
fn uv(r:Rect,x:f32,z:f32)->Option<(f32,f32)>{
    if !x.is_finite()||!z.is_finite()||x<r.0||x>r.1||z>r.2||z<r.3{return None;}
    Some(((x-r.0)/(r.1-r.0),(r.2-z)/(r.2-r.3)))
}
fn selected(cat:&Catalog,s:(u32,u32,Option<u32>))->Option<(Rect,Option<u32>,String)>{
    if let Some(id)=s.2 {return cat.direct.iter().find(|d|d.id==id).map(|d|(d.zone.rect,Some(d.map),d.zone.name.clone()));}
    if s.0==0{return Some((cat.world,None,if cat.wow{"World"}else{"Sandover Prime"}.into()));}
    let c=cat.continents.get(s.0.checked_sub(1)? as usize)?;
    if s.1==0{return Some((c.rect,Some(c.map),c.name.clone()));}
    let z=c.zones.get(s.1.checked_sub(1)? as usize)?;Some((z.rect,Some(c.map),z.name.clone()))
}
fn project(cat:&Catalog,s:(u32,u32,Option<u32>),map:u32,x:f32,z:f32)->Option<(f32,f32)>{
    if cat.wow{
        if !x.is_finite()||!z.is_finite(){return None;}
        if s.0==0&&s.2.is_none(){
            let p=cat.continents.iter().find(|c|c.map==map)?.projection?;
            return Some((p[0]/62.625+0.5-z/(62.625*533.3333)*p[2],p[1]/41.75+0.5-x/(41.75*533.3333)*p[2]));
        }
        let (r,required,_)=selected(cat,s)?;if required!=Some(map){return None;}
        let axis=|input:f32,low:f32,span:f32|if input-low!=0.&&span!=0.{1.-(input-low)/span}else{0.};
        let (u,v)=(axis(z,r.1,r.0-r.1),axis(x,r.3,r.2-r.3));
        return if (0. ..=1.).contains(&u)&&(0. ..=1.).contains(&v){Some((u,v))}else{None};
    }
    let (r,required,_)=selected(cat,s)?;
    if required.is_some_and(|m|m!=map)||required.is_none()&&map!=0{return None;}
    uv(r,x,z)
}
fn zone_grid(c:&Continent)->Vec<u16>{
    // Preserve the original map's 128x128 cell law. GG's x axis increases
    // east; the rect's signed span handles it without changing original code.
    let mut grid=vec![0;128*128];const K:f32=2.929_687_6e-5;
    for row in 0..128 {for col in 0..128 {
        let x=(0.5-(col as f32+0.5)/128.)/K;
        let z=(0.5-(row as f32+0.5)/128.)/K;
        let mut found=if uv(c.rect,x,z).is_some(){1}else{0};
        for (i,zone) in c.zones.iter().enumerate().skip(1){if uv(zone.rect,x,z).is_some(){found=i as u16+1;break;}}
        grid[row*128+col]=found;
    }}grid
}

pub(super) fn feed(host:&mut Host,v:&Value)->Result<(),String>{
    if v.is_null(){return Ok(());}
    if v["schema"]!="gg.game-engine.navigation.v1"{return Err("unsupported navigation schema".into());}
    let raw=&v["catalog"];
    let wow=raw["coordinate_frame"]=="WOW";
    let mut cat=Catalog{world:rect(&raw["world_rect"])? ,continents:vec![],direct:vec![],wow};
    for c in raw["continents"].as_array().filter(|a|a.len()<=16).ok_or("map continent capacity")?{
        let sheet=c["world_rect"].as_array().filter(|a|a.len()==4).ok_or("map sheet bounds")?;
        let sheet=(num(&sheet[0])?,num(&sheet[1])?,num(&sheet[2])?,num(&sheet[3])?);
        if [sheet.0,sheet.1,sheet.2,sheet.3].iter().any(|n|if wow{n.abs()>8.}else{!(0. ..=1.).contains(n)})||sheet.0>=sheet.2||sheet.1>=sheet.3{return Err("invalid map sheet bounds".into());}
        let zones=c["zones"].as_array().filter(|a|a.len()<=128).ok_or("map zone capacity")?.iter().map(|z|zone(z,wow)).collect::<Result<Vec<_>,_>>()?;
        let projection=if wow{let p=serde_json::from_value::<[f32;3]>(c["projection"].clone()).map_err(|e|e.to_string())?;if p.iter().any(|n|!n.is_finite())||p[2]<=0.{return Err("invalid map projection".into());}Some(p)}else{None};
        let grid=if wow{let g=serde_json::from_value::<Vec<u16>>(c["zone_grid"].clone()).map_err(|e|e.to_string())?;if !g.is_empty()&&g.len()!=16384||g.iter().any(|i|*i as usize>zones.len()){return Err("invalid original zone grid".into());}Some(g)}else{None};
        cat.continents.push(Continent{name:text(&c["name"])? ,file:text(&c["map_file"])? ,map:id(&c["map"])? ,rect:bounds(&c["rect"],wow)? ,sheet,zones,projection,grid});
    }
    for d in v["direct"].as_array().filter(|a|a.len()<=128).ok_or("direct map capacity")?{
        cat.direct.push(Direct{id:id(&d["id"])? ,map:id(&d["map"])? ,zone:zone(d,wow)?});
    }
    let player_zone=serde_json::from_value::<[u32;2]>(v["player_zone"].clone()).map_err(|e|e.to_string())?;
    let player_direct=if v["player_direct"].is_null(){None}else{Some(id(&v["player_direct"])?)};
    let map=id(&v["map"])?;let instance=v["instance"].as_u64().ok_or("invalid instance identity")?;
    let pos=v["player"].as_array().filter(|a|a.len()==2).ok_or("player map position")?;
    let (x,z)=(num(&pos[0])?,num(&pos[1])?);let facing=num(&v["facing"])?;
    let indoors=v["indoors"].as_bool().ok_or("minimap indoor mode required")?;
    let ping=v["ping"].as_array().filter(|a|a.len()==2).ok_or("minimap ping position required")?;
    let ping=(num(&ping[0])?,num(&ping[1])?);
    let corpse=point(&v["corpse"])?;
    let read_points=|key:&str,limit:usize|v[key].as_array().filter(|a|a.len()<=limit).ok_or("map member capacity".to_owned())?.iter().map(point).collect::<Result<Vec<_>,_>>();
    let party=read_points("party",4)?;let raid=read_points("raid",40)?;
    let explored=if v["explored"].is_null(){vec![]}else{let bits=serde_json::from_value::<Vec<u32>>(v["explored"].clone()).map_err(|e|e.to_string())?;if bits.len()>64{return Err("explored word capacity".into());}bits};
    let mut landmarks=Vec::new();
    for p in raw["landmarks"].as_array().filter(|a|a.len()<=2048).ok_or("map landmark capacity")?{
        let q=p["position"].as_array().filter(|a|a.len()==2).ok_or("landmark position")?;
        let icons=serde_json::from_value::<[Option<u32>;3]>(p["icons"].clone()).map_err(|e|e.to_string())?;
        if icons.iter().flatten().any(|i|*i>=64){return Err("invalid landmark icon".into());}
        landmarks.push(WorldMapLandmarkSource{name:text(&p["name"])? ,description:text(&p["description"])? ,map:id(&p["map"])? ,pos:(num(&q[0])?,num(&q[1])?),icons});
    }
    // Parse and bound every input before changing the original UI model.
    if host.views.get("navigation_catalog")!=Some(raw){
        host.ui.set_world_map_catalog(cat.continents.iter().map(|c|WorldMapContinentView{name:c.name.clone(),map_file:c.file.clone(),world_rect:c.sheet,loc_rect:c.rect,zone_grid:c.grid.clone().unwrap_or_else(||zone_grid(c)),zones:c.zones.iter().map(view).collect()}).collect());
        host.views.insert("navigation_catalog".into(),raw.clone());
    }
    if host.views.get("navigation_direct")!=Some(&v["direct"]){
        host.ui.set_world_map_direct_areas(cat.direct.iter().map(|d|(d.id,view(&d.zone))).collect());
        host.views.insert("navigation_direct".into(),v["direct"].clone());
    }
    let projection=cat.clone();host.ui.set_world_loc_projector(Box::new(move |s,map,x,z|project(&projection,s,map,x,z)));
    let location=json!([raw["source"],map,player_zone,player_direct]);
    if host.views.get("navigation_location")!=Some(&location){
        host.ui.sync_world_map_to_player_zone(player_zone[0],player_zone[1],player_direct);
        host.views.insert("navigation_location".into(),location);
    }
    let selection=host.ui.world_map_selection();
    host.ui.set_minimap_inside(indoors);
    host.ui.set_minimap_player_facing(facing);
    host.ui.set_minimap_ping(ping);
    host.ui.set_world_map_explored(explored);
    let member=|p:Option<(u32,u64,f32,f32)>|p.filter(|p|p.1==instance).and_then(|p|project(&cat,selection,p.0,p.2,p.3));
    host.ui.set_world_map_player_direct_area(player_direct);
    host.ui.set_world_map_feed(Some((player_zone[0],player_zone[1])),project(&cat,selection,map,x,z),facing,member(corpse),party.iter().copied().map(member).collect(),raid.iter().copied().map(member).collect());
    host.ui.set_world_map_landmark_sources(landmarks);
    let lua=host.ui.lua();
    lua.globals().set("GG_GetMapView",lua.create_function(move |lua,()|{
        let c:i64=lua.globals().get::<mlua::Function>("GetCurrentMapContinent")?.call(())?;
        let zi:u32=lua.globals().get::<mlua::Function>("GetCurrentMapZone")?.call(())?;
        let selection=(c.max(0) as u32,zi,if c<0{player_direct}else{None});
        let table=lua.create_table()?;
        let Some((r,_,name))=selected(&cat,selection)else{return Ok(table);};
        table.set("name",name)?;table.set("continent",c)?;table.set("zone",zi)?;
        table.set("width",(r.1-r.0).abs())?;table.set("height",r.2-r.3)?;table.set("original",cat.wow)?;
        if cat.wow{
            let file=if let Some(id)=selection.2{cat.direct.iter().find(|d|d.id==id).map(|d|d.zone.file.as_str())}
                else if selection.0==0{Some("World")}else{cat.continents.get(selection.0 as usize-1).and_then(|c|if selection.1==0{Some(c.file.as_str())}else{c.zones.get(selection.1 as usize-1).map(|z|z.file.as_str())})};
            table.set("map_file",file.unwrap_or("World"))?;
        }else{
            let a=uv(cat.world,r.0,r.2).unwrap_or((0.,0.));let b=uv(cat.world,r.1,r.3).unwrap_or((1.,1.));
            table.set("u0",(64.+a.0*840.)/1440.)?;table.set("u1",(64.+b.0*840.)/1440.)?;
            table.set("v0",(82.+a.1*840.)/1020.)?;table.set("v1",(82.+b.1*840.)/1020.)?;
        }
        if let Some((u,v))=project(&cat,selection,map,x,z){table.set("player_x",u)?;table.set("player_y",v)?;table.set("facing",facing)?;}
        if let Some(p)=corpse.filter(|p|p.1==instance){if let Some((u,v))=project(&cat,selection,p.0,p.2,p.3){table.set("corpse_x",u)?;table.set("corpse_y",v)?;}}
        let members=lua.create_table()?;
        for (index,p) in (if raid.is_empty(){&party}else{&raid}).iter().enumerate(){if let Some(p)=p.filter(|p|p.1==instance){if let Some((u,v))=project(&cat,selection,p.0,p.2,p.3){let row=lua.create_table()?;row.set("x",u)?;row.set("y",v)?;members.set(index+1,row)?;}}}
        table.set("members",members)?;Ok(table)
    }).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests{
    use super::*;
    #[test]fn projection_rejects_other_maps_and_off_map_points(){
        let c=Catalog{world:(-100.,100.,100.,-100.),continents:vec![],direct:vec![Direct{id:42,map:42,zone:Zone{name:"Local".into(),file:"GG".into(),area:42,rect:(-10.,10.,10.,-10.),overlays:vec![]}}],wow:false};
        assert_eq!(project(&c,(0,0,None),0,0.,0.),Some((0.5,0.5)));
        assert_eq!(project(&c,(0,0,None),42,0.,0.),None);
        assert_eq!(project(&c,(0,0,Some(42)),0,0.,0.),None);
        assert_eq!(project(&c,(0,0,Some(42)),42,0.,0.),Some((0.5,0.5)));
        assert_eq!(project(&c,(0,0,Some(42)),42,11.,0.),None);
    }
    #[test]fn original_signed_axes_and_world_projection_are_preserved(){
        let z=Zone{name:"Atlas".into(),file:"GGAtlas".into(),area:8,rect:(1000.,-1000.,1000.,-1000.),overlays:vec![]};
        let c=Catalog{world:(-100.,100.,100.,-100.),continents:vec![Continent{name:"Atlas".into(),file:"GGAtlas".into(),map:901,rect:z.rect,sheet:(0.4,0.4,0.6,0.6),zones:vec![z],projection:Some([0.,0.,1.]),grid:Some(vec![])}],direct:vec![],wow:true};
        assert_eq!(project(&c,(1,1,None),901,500.,-500.),Some((0.75,0.25)));
        assert_eq!(project(&c,(1,1,None),0,0.,0.),None);
        assert_eq!(project(&c,(0,0,None),901,0.,0.),Some((0.5,0.5)));
        assert_eq!(project(&c,(1,1,None),901,-1000.,-1000.),Some((0.,0.)));
    }
}
