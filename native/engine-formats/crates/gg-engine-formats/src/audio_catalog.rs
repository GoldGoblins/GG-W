//! Bounded host access to the unchanged original area and sound-kit catalogs.
use super::*;
impl Reader {
    pub(crate) fn ensure_sound_kits(&mut self)->Result<(),String>{
        if self.sound_kits.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let name="DBFilesClient\\SoundEntries.dbc";
            let archive=chain.archive_for(name).map_err(error)?;
            if archive.file_size(name).ok_or("sound catalog not found")? as usize>MAX_BLOB{return Err("sound catalog capacity exceeded".into());}
            self.sound_kits=Some(engine_formats_core::load_sound_kit_catalog(chain).map_err(error)?);
        }Ok(())
    }
    pub(crate) fn sound_beds(&mut self)->Result<Value,String>{
        self.ensure_sound_kits()?;let catalog=self.sound_kits.as_ref().unwrap();
        Ok(json!({"ghost":catalog.ghost_bed().unwrap_or(0),"underwater":catalog.underwater_bed().unwrap_or(0)}))
    }
    pub(crate) fn audio_provider(&mut self,v:&Value)->Result<Value,String>{
        let id=v["id"].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid sound provider id")?;
        if id==0{return Ok(json!({"id":0,"found":false,"wet":0.,"feedback":0.,"damping":0.}));}
        if self.sound_providers.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;let name="DBFilesClient\\SoundProviderPreferences.dbc";
            let archive=chain.archive_for(name).map_err(error)?;
            if archive.file_size(name).ok_or("sound provider catalog not found")? as usize>MAX_BLOB{return Err("sound provider catalog capacity exceeded".into());}
            self.sound_providers=Some(engine_formats_core::load_sound_provider_catalog(chain).map_err(error)?);
        }
        let Some(p)=self.sound_providers.as_ref().unwrap().get(id) else{return Ok(json!({"id":id,"found":false,"wet":0.,"feedback":0.,"damping":0.}));};
        if !p.decay_time.is_finite()||!p.decay_hf_ratio.is_finite(){return Err("non-finite sound provider".into());}
        // Upstream mixer.rs::freeverb_projection. The original itself
        // maps EAX to Freeverb, rather than emulating the old FMOD backend.
        let feedback=if p.decay_time>0.{10f64.powf(-0.108/f64::from(p.decay_time)).min(0.98)}else{0.};
        let damping=((1.-f64::from(p.decay_hf_ratio)/2.).max(0.)*0.7-f64::from(p.room_hf)/10000.*0.3).clamp(0.,1.);
        let db=((i64::from(p.room)+i64::from(p.reverb)) as f64/100.).min(6.);
        let wet=if db<=-60.{0.}else{10f64.powf(db/20.)};
        Ok(json!({"id":id,"found":true,"name":p.name,"wet":wet,"feedback":feedback,"damping":damping}))
    }
    pub(crate) fn interior_audio(&mut self,v:&Value)->Result<Option<engine_formats_core::WmoArea>,String>{
        if v.is_null(){return Ok(None);}
        let id=|k:&str|v[k].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid interior audio key");
        let (wmo,ns,group)=(id("wmo_id")?,id("name_set")?,id("group_id")?);
        if self.wmo_areas.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;let name="DBFilesClient\\WMOAreaTable.dbc";
            let archive=chain.archive_for(name).map_err(error)?;
            if archive.file_size(name).ok_or("WMO area catalog not found")? as usize>MAX_BLOB{return Err("WMO area catalog capacity exceeded".into());}
            self.wmo_areas=Some(engine_formats_core::load_wmo_area_catalog(chain).map_err(error)?);
        }
        Ok(self.wmo_areas.as_ref().unwrap().resolve(wmo,ns,group))
    }
    pub(crate) fn area_audio(&mut self,v:&Value)->Result<Value,String>{
        let area=v["area_id"].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid audio area id")?;
        if !v["interior"].is_null(){
            let keys=v["interior"].as_object().filter(|m|m.len()==3).ok_or("invalid interior audio key")?;
            for k in ["wmo_id","name_set","group_id"]{if !keys[k].as_u64().is_some_and(|n|n<=u32::MAX as u64){return Err("invalid interior audio key".into());}}
        }
        if self.area_sounds.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;let mut total=0;
            for name in ["AreaTable","ZoneMusic","ZoneIntroMusicTable","SoundAmbience"]{
                let path=format!("DBFilesClient\\{name}.dbc");let archive=chain.archive_for(&path).map_err(error)?;
                let size=archive.file_size(&path).ok_or("area audio table not found")? as usize;
                if size>MAX_BLOB{return Err("area audio table capacity exceeded".into());}total+=size;
            }
            if total>MAX_BLOB{return Err("area audio catalog capacity exceeded".into());}
            self.area_sounds=Some(engine_formats_core::load_area_sound_catalog(chain).map_err(error)?);
        }
        let (inside,note)=match self.interior_audio(&v["interior"]){Ok(i)=>(i,None),Err(e)=>(None,Some(e))};
        let area=inside.as_ref().map(|i|i.area_table_id).filter(|id|*id!=0).unwrap_or(area);
        let cat=self.area_sounds.as_ref().unwrap();let row=cat.resolve(area);
        let music=inside.as_ref().filter(|i|i.zone_music!=0).and_then(|i|cat.zone_music(i.zone_music)).or_else(||row.as_ref().and_then(|r|r.music));
        let intro=inside.as_ref().filter(|i|i.intro_sound!=0).and_then(|i|cat.intro(i.intro_sound)).or_else(||row.as_ref().and_then(|r|r.intro));
        // A zero phase in an interior ambience row falls back to the area phase.
        let mut ambience=row.as_ref().and_then(|r|r.ambience).map(|a|json!({"id":a.id,"kits":a.kits}));
        if let Some(a)=inside.as_ref().filter(|i|i.ambience!=0).and_then(|i|cat.ambience_row(i.ambience)){
            let base=row.as_ref().and_then(|r|r.ambience).map(|a|a.kits).unwrap_or([0;2]);
            ambience=Some(json!({"id":a.id,"kits":std::array::from_fn::<_,2,_>(|n|if a.kits[n]!=0{a.kits[n]}else{base[n]})}));
        }
        let mut provider=row.as_ref().map(|r|r.sound_provider).unwrap_or([0;2]);
        if let Some(i)=&inside{for n in 0..2{if i.sound_provider[n]!=0{provider[n]=i.sound_provider[n];}}}
        Ok(json!({"area_id":area,"found":row.is_some()||inside.is_some(),"name":row.as_ref().map(|r|r.area_name).unwrap_or(""),
            "interior_name":inside.as_ref().map(|i|i.name.as_str()),"interior_note":note,
            "music":music.map(|m|json!({"id":m.id,"name":m.set_name,"silence_min":m.silence_min,"silence_max":m.silence_max,"kits":m.sounds})),
            "intro":intro.map(|i|json!({"id":i.id,"kit":i.sound_id,"priority":i.priority,"delay_minutes":i.min_delay_minutes})),
            "ambience":ambience,"sound_provider":provider}))
    }
}
