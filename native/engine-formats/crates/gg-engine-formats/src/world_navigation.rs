//! Bounded atlas catalogs joined by the unchanged original DBC/MPQ readers.
use super::*;
fn preflight(chain:&engine_formats_core::Chain,path:&str)->Result<usize,String>{
    let archive=chain.archive_for(path).map_err(error)?;
    let size=archive.file_size(path).ok_or("navigation table not found")? as usize;
    if size>MAX_BLOB{return Err("navigation source capacity exceeded".into());}Ok(size)
}
fn ids(chain:&mut engine_formats_core::Chain,path:&str,limit:usize)->Result<Vec<u32>,String>{
    let b=chain.read_file(path).map_err(error)?;
    if b.len()<20||&b[..4]!=b"WDBC"{return Err("invalid navigation DBC header".into());}
    let n=u32::from_le_bytes(b[4..8].try_into().unwrap()) as usize;
    let width=u32::from_le_bytes(b[12..16].try_into().unwrap()) as usize;
    if n>limit||width<4||n.checked_mul(width).and_then(|n|n.checked_add(20)).is_none_or(|n|n>b.len()){return Err("navigation DBC row capacity exceeded".into());}
    Ok((0..n).map(|i|u32::from_le_bytes(b[20+i*width..24+i*width].try_into().unwrap())).collect())
}
fn sheet(c:&engine_formats_core::WorldMapContinent)->[f32;4]{
    let xoff=(31.3125-c.scale*32.)+c.offset_x;let yoff=(20.875-c.scale*32.)+c.offset_y;
    [(c.left_boundary as f32*c.scale+xoff)/62.625,(c.top_boundary as f32*c.scale+yoff)/41.75,
     ((c.right_boundary as f32+1.)*c.scale+xoff)/62.625,((c.bottom_boundary as f32+1.)*c.scale+yoff)/41.75]
}
fn zone(wma_id:u32,a:&engine_formats_core::WorldMapArea,name:&str,areas:&engine_formats_core::AreaTableCatalog,overlay:&engine_formats_core::WorldMapOverlayCatalog)->Value{
    json!({"id":wma_id,"map":a.map_id,"name":name,"area_id":a.area_id,"map_file":a.name,
        "rect":[a.loc_left,a.loc_right,a.loc_top,a.loc_bottom],
        "overlays":overlay.for_area(wma_id).iter().map(|o|json!({
            "texture":format!("Interface\\WorldMap\\{}\\{}",a.name,o.texture_name),"width":o.texture_width,"height":o.texture_height,
            "offset_x":o.offset_x,"offset_y":o.offset_y,"hit_rect":[o.hit_rect_top,o.hit_rect_left,o.hit_rect_bottom,o.hit_rect_right],
            "explore_bits":o.area_id.iter().filter(|a|**a!=0).filter_map(|a|areas.get(*a).map(|r|r.explore_flag)).filter(|b|*b<2048).collect::<Vec<_>>(),
            "area_name":areas.name(o.area_id[0])})).collect::<Vec<_>>()})
}
impl Reader{
    pub(crate) fn world_navigation(&mut self,v:&Value)->Result<Value,String>{
        if self.navigation.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let mut total=0;
            for name in ["Map","AreaTable","WorldMapArea","WorldMapContinent","WorldMapOverlay"]{total+=preflight(chain,&format!("DBFilesClient\\{name}.dbc"))?;}
            if total>MAX_BLOB{return Err("navigation catalog source capacity exceeded".into());}
            let maps=engine_formats_core::load_map_catalog(chain).map_err(error)?;
            let areas=engine_formats_core::load_area_table_catalog(chain).map_err(error)?;
            let wma=engine_formats_core::load_world_map_area_catalog(chain).map_err(error)?;
            let wmc=engine_formats_core::load_world_map_continent_catalog(chain).map_err(error)?;
            let wmo=engine_formats_core::load_world_map_overlay_catalog(chain).map_err(error)?;
            if maps.len()>2048||wma.len()>2048||wmc.len()>16||wmo.len()>4096{return Err("navigation catalog row capacity exceeded".into());}
            for (_,a) in wma.iter(){
                if [a.loc_left,a.loc_right,a.loc_top,a.loc_bottom].iter().any(|n|!n.is_finite()||n.abs()>2_000_000.)||a.loc_left<=a.loc_right||a.loc_top<=a.loc_bottom{return Err("invalid original map bounds".into());}
            }
            let map_ids=ids(chain,"DBFilesClient\\Map.dbc",2048)?;
            let area_ids=ids(chain,"DBFilesClient\\AreaTable.dbc",8192)?;
            let map_rows=map_ids.iter().filter_map(|id|maps.directory(*id).map(|dir|json!({"id":id,"directory":dir,"name":maps.name(*id),"instance_type":maps.instance_type(*id).unwrap_or(0),"loading_screen":maps.loading_screen_id(*id)}))).collect::<Vec<_>>();
            let area_rows=area_ids.iter().filter_map(|id|areas.get(*id).map(|a|json!({"id":id,"map":a.map_id,"parent":a.zone_id,"top_zone":areas.top_zone(*id),"explore_bit":a.explore_flag,"exploration_level":a.exploration_level,"name":a.name}))).collect::<Vec<_>>();
            let mut continents=Vec::new();let mut notes=Vec::new();let mut continent_maps=Vec::new();
            for (_,a) in wma.iter().filter(|(_,a)|a.area_id==0){
                let mut zones=wma.iter().filter(|(_,z)|z.map_id==a.map_id&&z.area_id!=0).collect::<Vec<_>>();
                zones.sort_by_key(|(_,z)|areas.name(z.area_id).unwrap_or(&z.name).to_lowercase());
                if zones.len()>128||continents.len()>=16{return Err("navigation continent capacity exceeded".into());}
                let projection=wmc.get(a.map_id).ok_or("world-map continent projection missing")?;
                if !projection.scale.is_finite()||projection.scale<=0.||!projection.offset_x.is_finite()||!projection.offset_y.is_finite(){return Err("invalid continent projection".into());}
                let path=format!("Interface\\WorldMap\\{}.zmp",a.name);
                let grid=match preflight(chain,&path){
                    Ok(size)=>{if size>128*128*4+8{return Err("zone bitmap capacity exceeded".into());}
                        engine_formats_core::load_zone_map(chain,&a.name).map_err(error)?.iter().map(|raw|{
                            let aid=areas.get(*raw).filter(|r|r.zone_id!=0).map(|r|r.zone_id).unwrap_or(*raw);
                            zones.iter().position(|(_,z)|z.area_id==aid).map(|i|i as u16+1).unwrap_or(0)
                        }).collect::<Vec<_>>()},
                    Err(e)=>{if e.contains("capacity"){return Err(e);}notes.push(format!("Zone bitmap {} unavailable: {}",a.name,e));Vec::new()}
                };
                let rect=sheet(projection);
                if rect.iter().any(|n|!n.is_finite()){return Err("invalid continent sheet bounds".into());}
                continents.push(json!({"id":a.map_id,"map":a.map_id,"name":maps.name(a.map_id).unwrap_or(&a.name),"map_file":a.name,
                    "rect":[a.loc_left,a.loc_right,a.loc_top,a.loc_bottom],"world_rect":rect,
                    "projection":[projection.offset_x,projection.offset_y,projection.scale],"zone_grid":grid,
                    "zones":zones.iter().map(|(id,z)|zone(*id,z,areas.name(z.area_id).unwrap_or(&z.name),&areas,&wmo)).collect::<Vec<_>>()}));
                continent_maps.push(a.map_id);
            }
            let direct=wma.iter().filter(|(_,a)|a.area_id!=0&&!continent_maps.contains(&a.map_id)).map(|(id,a)|zone(id,a,areas.name(a.area_id).unwrap_or(&a.name),&areas,&wmo)).collect::<Vec<_>>();
            if direct.len()>128{return Err("direct atlas map capacity exceeded".into());}
            let mut pois=Vec::new();let path="DBFilesClient\\AreaPOI.dbc";
            match preflight(chain,path){
                Ok(size)=>{if size+total>MAX_BLOB{return Err("navigation catalog source capacity exceeded".into());}
                    let poi=engine_formats_core::load_area_poi_catalog(chain).map_err(error)?;
                    if poi.len()>2048{return Err("landmark capacity exceeded".into());}
                    for (id,p) in poi.rows(){if p.pos.iter().any(|n|!n.is_finite()||n.abs()>2_000_000.){return Err("invalid landmark position".into());}pois.push(json!({"id":id,"map":p.continent_id,"position":[p.pos[0],p.pos[1]],"name":p.name,"description":p.description,
                        "icon":p.icon,"flags":p.flags,"area":p.area_id,"world_state":p.world_state_id,"importance":p.importance}));}
                },Err(e)=>{if e.contains("capacity"){return Err(e);}notes.push(format!("AreaPOI unavailable: {e}"));},
            }
            let value=json!({"schema":"gg.engine.imported-navigation.v1","maps":map_rows,"areas":area_rows,"direct":direct,"pois":pois,"notes":notes,
                "catalog":{"source":"ORIGINAL_DBC","coordinate_frame":"WOW","revision":1,"world_rect":[-17066.666,17066.666,17066.666,-17066.666],"continents":continents,"landmarks":[]}});
            if serde_json::to_vec(&value).map_err(error)?.len()>MAX_BLOB{return Err("navigation response capacity exceeded".into());}
            self.navigation=Some(value);
        }
        let mut data=self.navigation.as_ref().unwrap().clone();
        if let Some(name)=v["map_name"].as_str(){
            if name.is_empty()||name.len()>64||!name.bytes().all(|c|c.is_ascii_alphanumeric()||c==b'_'){return Err("invalid map directory name".into());}
            let selected=data["maps"].as_array().unwrap().iter().find(|r|r["directory"].as_str().is_some_and(|d|d.eq_ignore_ascii_case(name))).cloned();
            data["selected_map"]=selected.unwrap_or(Value::Null);
        }Ok(data)
    }
}
