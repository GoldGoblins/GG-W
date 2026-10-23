//! Entity audio joins through the unchanged original DBC catalogs.
//! Every table is bounded before the original loader allocates it. Missing rows
//! are silence; no character class, terrain, voice or weapon fallback is invented.
use super::*;

#[derive(Default)]
pub(crate) struct Catalogs {
    voices: Option<engine_formats_core::CreatureVoiceCatalog>,
    objects: Option<engine_formats_core::GameObjectSounds>,
    footsteps: Option<engine_formats_core::FootstepCatalog>,
    materials: Option<engine_formats_core::MaterialCatalog>,
    swings: Option<engine_formats_core::WeaponSwingCatalog>,
    impacts: Option<engine_formats_core::WeaponImpactCatalog>,
}

fn id(v: &Value, key: &str) -> Result<u32, String> {
    v[key].as_u64().and_then(|n| u32::try_from(n).ok()).ok_or_else(|| format!("invalid entity audio {key}"))
}
fn flag(v: &Value, key: &str) -> Result<bool, String> {
    v[key].as_bool().ok_or_else(|| format!("invalid entity audio {key}"))
}

/// Original WMO sound down-ray faces: the hit MOPY material indexes MOMT
/// `ground_type`. Collision/visited faces (0x88) never steal a coplanar
/// rendered floor's material. No MOCV/interior requirement for a sound ray.
pub(crate) fn wmo_sound_faces(bytes: &[u8], ground_types: &[u32]) -> Result<(Vec<[f32; 3]>, Vec<(u32, Vec<u32>)>), String> {
    let engine_wmo::ParsedWmo::Group(group) = engine_wmo::parse_wmo(&mut Cursor::new(bytes)).map_err(error)? else {
        return Err("entity audio surface requires WMO group".into());
    };
    if group.vertex_positions.len() > 65536 || group.vertex_indices.len() > 393216 {
        return Err("entity audio surface capacity exceeded".into());
    }
    let positions: Vec<_> = group.vertex_positions.iter().map(|p| [p.x, p.y, p.z]).collect();
    let mut rows: std::collections::BTreeMap<u32, Vec<u32>> = Default::default();
    for (ti, tri) in group.vertex_indices.chunks_exact(3).enumerate() {
        let Some(material) = group.material_info.get(ti) else { continue; };
        if material.flags & 0x88 != 0 { continue; }
        let Some(&terrain) = ground_types.get(material.material_id as usize) else { continue; };
        if tri.iter().any(|i| *i as usize >= positions.len()) { return Err("invalid entity audio surface index".into()); }
        rows.entry(terrain).or_default().extend(tri.iter().map(|i| u32::from(*i)));
    }
    if rows.len() > 256 { return Err("entity audio material capacity exceeded".into()); }
    Ok((positions, rows.into_iter().collect()))
}

impl Reader {
    fn audio_tables(&mut self, names: &[&str]) -> Result<(), String> {
        let chain = self.chain.as_mut().ok_or("archive chain not mounted")?;
        let mut total = 0usize;
        for name in names {
            let path = format!("DBFilesClient\\{name}.dbc");
            let archive = chain.archive_for(&path).map_err(error)?;
            let size = archive.file_size(&path).ok_or_else(|| format!("{name} audio table not found"))? as usize;
            total = total.checked_add(size).ok_or("entity audio table capacity exceeded")?;
            if size > MAX_BLOB || total > MAX_BLOB { return Err("entity audio table capacity exceeded".into()); }
        }
        Ok(())
    }
    fn voice_catalog(&mut self) -> Result<(), String> {
        if self.entity_audio.voices.is_none() {
            self.audio_tables(&["CreatureSoundData", "CreatureModelData", "CreatureDisplayInfo"])?;
            self.entity_audio.voices = Some(engine_formats_core::load_creature_voice_catalog(self.chain.as_mut().unwrap()).map_err(error)?);
        }
        Ok(())
    }
    pub(crate) fn creature_voice(&mut self, v: &Value) -> Result<Value, String> {
        let model = !v["model_id"].is_null();
        if model && !v["display_id"].is_null() { return Err("ambiguous creature voice identity".into()); }
        let ident = id(v, if model { "model_id" } else { "display_id" })?;
        self.voice_catalog()?;
        let cat = self.entity_audio.voices.as_ref().unwrap();
        let voice = if model { cat.for_model(ident) } else { cat.for_display(ident) };
        let Some(voice) = voice else { return Ok(json!({"id": ident, "found": false})); };
        Ok(json!({"id": ident, "found": true, "exertion": voice.exertion, "injury": voice.injury,
            "death": voice.death, "stun": voice.stun, "stand": voice.stand, "footstep_class": voice.footstep_class,
            "aggro": voice.aggro, "wing_flap": voice.wing_flap, "wing_glide": voice.wing_glide,
            "alert": voice.alert, "fidget": voice.fidget, "custom_attack": voice.custom_attack,
            "loop_sound": voice.loop_sound, "impact_type": voice.impact_type,
            "jump_start": voice.jump_start, "jump_end": voice.jump_end,
            "pet_attack": voice.pet_attack, "pet_order": voice.pet_order, "pet_dismiss": voice.pet_dismiss}))
    }
    pub(crate) fn gameobject_audio(&mut self, v: &Value) -> Result<Value, String> {
        let ident = id(v, "display_id")?;
        if self.entity_audio.objects.is_none() {
            self.audio_tables(&["GameObjectDisplayInfo"])?;
            self.entity_audio.objects = Some(engine_formats_core::load_gameobject_sounds(self.chain.as_mut().unwrap()).map_err(error)?);
        }
        let slots = self.entity_audio.objects.as_ref().unwrap().slots(ident);
        Ok(json!({"display_id": ident, "found": slots.is_some(), "slots": slots.copied().unwrap_or([0; 10])}))
    }
    pub(crate) fn footstep_audio(&mut self, v: &Value) -> Result<Value, String> {
        let class = id(v, "footstep_class")?;
        let terrain = if v["terrain_id"].is_null() { None } else { Some(id(v, "terrain_id")?) };
        let effect = if v["ground_effect_id"].is_null() { None } else { Some(id(v, "ground_effect_id")?) };
        if terrain.is_some() && effect.is_some() { return Err("ambiguous footstep surface".into()); }
        if class == 0 || terrain.is_none() && effect.is_none() {
            return Ok(json!({"found": false, "dry": 0, "splash": 0, "footprints": false}));
        }
        if self.entity_audio.footsteps.is_none() {
            self.audio_tables(&["GroundEffectTexture", "TerrainType", "FootstepTerrainLookup"])?;
            self.entity_audio.footsteps = Some(engine_formats_core::load_footstep_catalog(self.chain.as_mut().unwrap()).map_err(error)?);
        }
        let cat = self.entity_audio.footsteps.as_ref().unwrap();
        let (kits, prints) = if let Some(t) = terrain {
            (cat.resolve_terrain(class, t), cat.terrain_leaves_footprints(t))
        } else { (cat.resolve(class, effect), cat.leaves_footprints(effect)) };
        let (dry, splash) = kits.unwrap_or((0, 0));
        Ok(json!({"found": kits.is_some(), "dry": dry, "splash": splash, "footprints": prints}))
    }
    pub(crate) fn material_audio(&mut self, v: &Value) -> Result<Value, String> {
        let material = id(v, "material_id")?;
        if self.entity_audio.materials.is_none() {
            self.audio_tables(&["Material"])?;
            self.entity_audio.materials = Some(engine_formats_core::load_material_catalog(self.chain.as_mut().unwrap()).map_err(error)?);
        }
        let cat = self.entity_audio.materials.as_ref().unwrap();
        Ok(json!({"material_id": material, "foley": cat.foley_kit(material).unwrap_or(0), "metal": cat.is_metal(material), "impact_slot": cat.armor_impact_slot(material)}))
    }
    pub(crate) fn combat_audio(&mut self, v: &Value) -> Result<Value, String> {
        let critical = flag(v, "critical")?;
        if v["kind"] == "swing" {
            let weight = id(v, "swing_type")?;
            if self.entity_audio.swings.is_none() {
                self.audio_tables(&["WeaponSwingSounds2"])?;
                self.entity_audio.swings = Some(engine_formats_core::load_weapon_swing_catalog(self.chain.as_mut().unwrap()).map_err(error)?);
            }
            let kit = self.entity_audio.swings.as_ref().unwrap().kit(weight, critical).unwrap_or(0);
            return Ok(json!({"kit": kit, "found": kit != 0}));
        }
        if v["kind"] != "impact" { return Err("invalid combat audio kind".into()); }
        let subclass = id(v, "weapon_subclass")?;
        let metal = flag(v, "metal")?;
        let slot = id(v, "target_slot")? as usize;
        if slot >= 10 { return Err("invalid weapon impact slot".into()); }
        if self.entity_audio.impacts.is_none() {
            self.audio_tables(&["WeaponImpactSounds"])?;
            self.entity_audio.impacts = Some(engine_formats_core::load_weapon_impact_catalog(self.chain.as_mut().unwrap()).map_err(error)?);
        }
        let kit = self.entity_audio.impacts.as_ref().unwrap().get(subclass, metal)
            .map(|row| if critical { row.crit[slot] } else { row.impact[slot] }).unwrap_or(0);
        Ok(json!({"kit": kit, "found": kit != 0}))
    }
}
