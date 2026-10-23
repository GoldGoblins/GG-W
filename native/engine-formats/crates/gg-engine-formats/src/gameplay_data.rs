//! Read-only, bounded gameplay metadata over the unchanged original typed DBC readers.
//! Parsing an effect never grants authority to cast, learn, train, or create its assets in GG.
use super::{error, json, Reader, Value};
use std::collections::{HashMap, HashSet};

const MIB: usize = 1024 * 1024;
const MAX_SOURCE: usize = 64 * MIB;
const MAX_TEXT: usize = 64 * MIB;
const MAX_CACHE: usize = 128 * MIB;
const MAX_RESPONSE: usize = MIB;

struct Spec {
    name: &'static str,
    fields: usize,
    rows: usize,
    strings: &'static [(usize, usize)],
    floats: &'static [usize],
    key: usize,
    refs: &'static [usize],
}
const CLASSES: Spec = Spec { name: "ChrClasses", fields: 17, rows: 64, strings: &[(4, 32)], floats: &[], key: 0, refs: &[] };
const ICONS: Spec = Spec { name: "SpellIcon", fields: 2, rows: 16384, strings: &[(1, 1024)], floats: &[], key: 0, refs: &[] };
const LINES: Spec = Spec { name: "SkillLine", fields: 22, rows: 4096, strings: &[(3, 512), (12, 4096)], floats: &[], key: 0, refs: &[21] };
const ABILITIES: Spec = Spec { name: "SkillLineAbility", fields: 15, rows: 32768, strings: &[], floats: &[], key: 2, refs: &[] };
const CATEGORIES: Spec = Spec { name: "SkillLineCategory", fields: 11, rows: 4096, strings: &[(1, 512)], floats: &[], key: 0, refs: &[] };
const RACE_CLASS: Spec = Spec { name: "SkillRaceClassInfo", fields: 8, rows: 4096, strings: &[], floats: &[], key: 0, refs: &[] };
const TABS: Spec = Spec { name: "TalentTab", fields: 15, rows: 64, strings: &[(1, 512), (14, 1024)], floats: &[], key: 0, refs: &[] };
const TALENTS: Spec = Spec { name: "Talent", fields: 21, rows: 4096, strings: &[], floats: &[], key: 0, refs: &[] };
const DISPELS: Spec = Spec { name: "SpellDispelType", fields: 12, rows: 4096, strings: &[(1, 512),(2, 512),(3, 512),(4, 512),(5, 512),(6, 512),(7, 512),(8, 512),(11, 512)], floats: &[], key: 0, refs: &[10] };
const SPELL_CATEGORIES: Spec = Spec { name: "SpellCategory", fields: 2, rows: 4096, strings: &[], floats: &[], key: 0, refs: &[] };
const SPELLS: Spec = Spec { name: "Spell", fields: 173, rows: 32768, strings: &[(120, 512), (129, 256), (138, 4096), (147, 4096)], floats: &[37,73,74,75,97,98,99,112,113,114,167,168,169], key: 0, refs: &[117,118] };
const CAST_TIMES: Spec = Spec { name: "SpellCastTimes", fields: 4, rows: 4096, strings: &[], floats: &[], key: 0, refs: &[] };
const DURATIONS: Spec = Spec { name: "SpellDuration", fields: 4, rows: 4096, strings: &[], floats: &[], key: 0, refs: &[] };
const RANGES: Spec = Spec { name: "SpellRange", fields: 22, rows: 4096, strings: &[], floats: &[1,2], key: 0, refs: &[] };
const RADII: Spec = Spec { name: "SpellRadius", fields: 4, rows: 4096, strings: &[], floats: &[1,2,3], key: 0, refs: &[] };
const VISUALS: Spec = Spec { name: "SpellVisual", fields: 16, rows: 16384, strings: &[], floats: &[], key: 0, refs: &[] };
const VISUAL_KITS: Spec = Spec { name: "SpellVisualKit", fields: 35, rows: 16384, strings: &[], floats: &[19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34], key: 0, refs: &[] };
const EFFECT_NAMES: Spec = Spec { name: "SpellVisualEffectName", fields: 5, rows: 16384, strings: &[(1,1024),(2,1024)], floats: &[], key: 0, refs: &[] };
const CHAINS: Spec = Spec { name: "SpellChainEffects", fields: 8, rows: 4096, strings: &[(7,1024)], floats: &[1,2,3,4], key: 0, refs: &[] };
const TRIGGERS: Spec = Spec { name: "AreaTrigger", fields: 10, rows: 32768, strings: &[], floats: &[2,3,4,5,6,7,8,9], key: 0, refs: &[] };

struct Table {
    name: &'static str,
    ids: Vec<u32>,
    refs: HashMap<u32, Vec<u32>>,
    ref_rows: Vec<Vec<u32>>,
    icon_lengths: HashMap<u32, usize>,
    bytes: usize,
    text: usize,
    rows: usize,
}
impl Table {
    fn meta(&self) -> Value { json!({"name":self.name,"records":self.rows,"source_bytes":self.bytes}) }
    fn sorted_ids(&self) -> Vec<u32> {
        let mut ids = self.ids.clone(); ids.sort_unstable(); ids.dedup(); ids
    }
}
fn word(bytes: &[u8], at: usize) -> u32 { u32::from_le_bytes(bytes[at..at+4].try_into().unwrap()) }

// Validate before the original reader allocates its record vectors or clones repeated strings.
fn preflight(chain: &engine_formats_core::Chain, spec: &Spec, envelopes: &HashMap<std::path::PathBuf, super::mpq_envelope::Envelope>) -> Result<Table, String> {
    let path = format!("DBFilesClient\\{}.dbc", spec.name);
    let archive = chain.archive_for(&path).map_err(error)?;
    let size = archive.file_size(&path).ok_or("game data table not found")? as usize;
    let ceiling = if spec.name == "Spell" {32*MIB} else {4*MIB};
    if size > ceiling { return Err(format!("game data source capacity exceeded: {}", spec.name)); }
    envelopes.get(archive.path()).ok_or("MPQ winning archive envelope missing")?.guard(archive.path(),&path,size)?;
    let bytes = chain.read(&path).map_err(error)?;
    if bytes.len() != size || bytes.len() < 20 || &bytes[..4] != b"WDBC" { return Err(format!("invalid gameplay DBC header: {}", spec.name)); }
    let rows = word(&bytes,4) as usize;
    let fields = word(&bytes,8) as usize;
    let width = word(&bytes,12) as usize;
    let string_bytes = word(&bytes,16) as usize;
    if rows > spec.rows { return Err(format!("game data row capacity exceeded: {}",spec.name)); }
    if fields != spec.fields || width != spec.fields * 4 { return Err(format!("invalid gameplay DBC shape: {}",spec.name)); }
    let strings_at = rows.checked_mul(width).and_then(|n| n.checked_add(20)).ok_or("game data layout capacity exceeded")?;
    if strings_at.checked_add(string_bytes) != Some(bytes.len()) { return Err(format!("invalid gameplay DBC length: {}",spec.name)); }
    let strings = &bytes[strings_at..];
    let mut ids = Vec::with_capacity(rows);
    let mut refs = HashMap::new();
    let mut ref_rows = Vec::new();
    let mut icon_lengths = HashMap::new();
    let mut text = 0usize;
    // Reused offsets are validated once, while each owning row still charges expanded text.
    let mut lengths: HashMap<usize, usize> = HashMap::new();
    for row in 0..rows {
        let at = 20 + row*width;
        let id = word(&bytes,at+spec.key*4); ids.push(id);
        if !spec.refs.is_empty() { let values=spec.refs.iter().map(|col|word(&bytes,at+col*4)).collect::<Vec<_>>();ref_rows.push(values.clone());refs.insert(id,values); }
        for &(col, cap) in spec.strings {
            let off = word(&bytes,at+col*4) as usize;
            let length = if let Some(n) = lengths.get(&off) {*n} else {
                let tail = strings.get(off..).ok_or_else(||format!("invalid gameplay string offset: {}",spec.name))?;
                let n = tail.iter().position(|&b|b==0).ok_or_else(||format!("unterminated gameplay string: {}",spec.name))?;
                std::str::from_utf8(&tail[..n]).map_err(|_|format!("invalid gameplay string encoding: {}",spec.name))?;
                lengths.insert(off,n); n
            };
            if length > cap { return Err(format!("game data string capacity exceeded: {} field {}",spec.name,col)); }
            if spec.name=="SpellIcon" && col==1 && length!=0 {icon_lengths.insert(id,length);}
            text = text.checked_add(length).ok_or("game data text capacity exceeded")?;
            if text > MAX_TEXT { return Err("game data text capacity exceeded".into()); }
        }
        for &col in spec.floats {
            if !f32::from_bits(word(&bytes,at+col*4)).is_finite() { return Err(format!("non-finite gameplay value: {} field {}",spec.name,col)); }
        }
        if spec.name == "Spell" {
            for i in 0..3 {
                if word(&bytes,at+(61+i)*4)==44 && (word(&bytes,at+(106+i)*4) as i32)>0 && (word(&bytes,at+(76+i)*4) as i32).checked_add(word(&bytes,at+(64+i)*4) as i32).is_none() {
                    return Err("invalid gameplay learn effect arithmetic".into());
                }
            }
        }
    }
    Ok(Table{name:spec.name,ids,refs,ref_rows,icon_lengths,bytes:size,text,rows})
}


// Account paths cloned by the original joins, including two independent clones of one icon.
// Empty duplicate icon rows do not remove a previous path in load_spell_icon_map.
fn joined_icon_text(tables:&mut [Table],target:usize,icons:usize)->Result<(),String>{
    let mut expanded=tables[target].text;
    for refs in &tables[target].ref_rows {
        for id in refs.iter().filter(|&&id|id!=0) {
            expanded=expanded.checked_add(tables[icons].icon_lengths.get(id).copied().unwrap_or(0)).ok_or("game data text capacity exceeded")?;
            if expanded>MAX_TEXT{return Err("game data text capacity exceeded by joined icons".into());}
        }
    }
    tables[target].text=expanded;Ok(())
}

struct Classes { catalog: engine_formats_core::ChrClasses, ids: Vec<u32>, tables: Vec<Table> }
struct Skills { catalog: engine_formats_core::SkillLineCatalog, line_ids: Vec<u32>, ability_ids: Vec<u32>, tables: Vec<Table> }
struct Talents { catalog: engine_formats_core::TalentCatalog, tables: Vec<Table> }
struct Spells { catalog: engine_formats_core::SpellCatalog, ids: Vec<u32>, tables: Vec<Table> }
struct SpellJoins {
    times: engine_formats_core::SpellCastTimeCatalog,
    durations: engine_formats_core::SpellDurationCatalog,
    ranges: engine_formats_core::SpellRangeCatalog,
    radii: engine_formats_core::SpellRadiusCatalog,
    visuals: Option<engine_formats_core::SpellVisualCatalog>,
    tables: Vec<Table>,
    absent: Vec<&'static str>,
}
struct Triggers {catalog:engine_formats_core::AreaTriggerCatalog,table:Table}

#[derive(Default)]
pub(crate) struct State {
    epoch: u64,
    sources: usize,
    text: usize,
    cache: usize,
    classes: Option<Classes>,
    skills: Option<Skills>,
    talents: Option<Talents>,
    spells: Option<Spells>,
    spell_joins: Option<SpellJoins>,
    triggers: Option<Triggers>,
}
impl State {
    pub(crate) fn remounted(&self) -> Result<Self,String> {
        Ok(Self{epoch:self.epoch.checked_add(1).ok_or("game data epoch capacity exceeded")?,..Self::default()})
    }
    fn reserve(&self, tables: &[Table]) -> Result<(usize,usize,usize),String> {
        let sources = tables.iter().map(|t|t.bytes).sum::<usize>();
        let text = tables.iter().map(|t|t.text).sum::<usize>();
        // Conservative retained cache allowance: source bytes + owned strings + 2 KiB per row.
        let cache = sources + text + tables.iter().map(|t|t.rows*2048).sum::<usize>();
        if self.sources+sources>MAX_SOURCE || self.text+text>MAX_TEXT || self.cache+cache>MAX_CACHE { return Err("game data catalog/cache capacity exceeded".into()); }
        Ok((sources,text,cache))
    }
    fn charge(&mut self, cost: (usize,usize,usize)) { self.sources+=cost.0; self.text+=cost.1; self.cache+=cost.2; }
}

struct Selection { ids: Option<Vec<u32>>, offset: usize, limit: usize }
fn integer(v: &Value, key: &str, low: u64, high: u64) -> Result<u64,String> {
    let n = v[key].as_u64().ok_or_else(||format!("invalid game data integer: {key}"))?;
    if !(low..=high).contains(&n) { return Err(format!("invalid game data integer: {key}")); } Ok(n)
}
fn keys(v: &Value, allowed: &[&str]) -> Result<(),String> {
    let object = v.as_object().ok_or("invalid game data request")?;
    if object.keys().any(|key|!allowed.contains(&key.as_str())) { return Err("unknown game data request field".into()); } Ok(())
}
impl Selection {
    fn parse(v: &Value) -> Result<Self,String> {
        if v.get("ids").is_some() {
            if v.get("offset").is_some() || v.get("limit").is_some() { return Err("game data selection and page are mutually exclusive".into()); }
            let input = v["ids"].as_array().ok_or("invalid game data ids")?;
            if input.len()>64 { return Err("game data selected ID capacity exceeded".into()); }
            let mut seen=HashSet::new(); let mut ids=Vec::new();
            for value in input {
                let id=value.as_u64().filter(|n|(1..=u32::MAX as u64).contains(n)).ok_or("invalid game data id")? as u32;
                if !seen.insert(id) { return Err("duplicate game data selected id".into()); } ids.push(id);
            }
            Ok(Self{ids:Some(ids),offset:0,limit:64})
        } else {
            let offset=if v.get("offset").is_some(){integer(v,"offset",0,32768)? as usize}else{0};
            let limit=if v.get("limit").is_some(){integer(v,"limit",1,64)? as usize}else{32};
            Ok(Self{ids:None,offset,limit})
        }
    }
    fn select(&self, index: &[u32]) -> (Vec<u32>,Vec<u32>,Option<usize>) {
        if let Some(ids)=&self.ids {
            let known:HashSet<u32>=index.iter().copied().collect();
            (ids.iter().filter(|id|known.contains(id)).copied().collect(),ids.iter().filter(|id|!known.contains(id)).copied().collect(),None)
        } else {
            let start=self.offset.min(index.len()); let end=(start+self.limit).min(index.len());
            (index[start..end].to_vec(),Vec::new(),(end<index.len()).then_some(end))
        }
    }
}
fn bounded(value: Value) -> Result<Value,String> {
    if serde_json::to_vec(&value).map_err(error)?.len()>MAX_RESPONSE { return Err("game data response capacity exceeded; request fewer rows".into()); } Ok(value)
}
fn response(epoch: u64, tables: &[Table], rows: Vec<Value>, missing: Vec<u32>, total: usize, next: Option<usize>) -> Result<Value,String> {
    let value=json!({"schema":"gg.engine.game-data.v1","source":"MOUNTED_DBC","catalog_epoch":epoch,
        "execution_authority":false,"rows":rows,"missing_ids":missing,"total":total,"next_offset":next,
        "source_tables":tables.iter().map(Table::meta).collect::<Vec<_>>()});
    bounded(value)
}
fn missing(kind: &str, id: u32) -> Value { json!({"table":kind,"id":id}) }

impl Reader {
    pub(crate) fn game_data(&mut self, v: &Value) -> Result<Value,String> {
        match v["op"].as_str() {
            Some("game_data_classes")=>self.game_data_classes(v),
            Some("game_data_skills")=>self.game_data_skills(v),
            Some("game_data_talents")=>self.game_data_talents(v),
            Some("game_data_spells")=>self.game_data_spells(v),
            Some("game_data_triggers")=>self.game_data_triggers(v),
            _=>Err("unsupported game data operation".into()),
        }
    }
    fn game_data_classes(&mut self,v:&Value)->Result<Value,String>{
        keys(v,&["op","ids","offset","limit"])?; let selection=Selection::parse(v)?;
        if self.game_data.classes.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let tables=vec![preflight(chain,&CLASSES,&self.mpq_envelopes)?]; let cost=self.game_data.reserve(&tables)?;
            let catalog=engine_formats_core::load_chr_classes(chain).map_err(error)?;
            let ids=tables[0].sorted_ids(); self.game_data.classes=Some(Classes{catalog,ids,tables}); self.game_data.charge(cost);
        }
        let data=self.game_data.classes.as_ref().unwrap(); let (ids,missing,next)=selection.select(&data.ids);
        let rows=ids.into_iter().map(|id|json!({"id":id,"damage_bonus_stat":data.catalog.damage_bonus_stat(id),
            "pet_name_token":data.catalog.pet_name_token(id),"has_relic_slot":data.catalog.has_relic_slot(id),"spell_family":data.catalog.spell_family(id)})).collect();
        response(self.game_data.epoch,&data.tables,rows,missing,data.ids.len(),next)
    }
    fn game_data_triggers(&mut self,v:&Value)->Result<Value,String>{
        keys(v,&["op","ids","offset","limit"])?;let selection=Selection::parse(v)?;
        if self.game_data.triggers.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let table=preflight(chain,&TRIGGERS,&self.mpq_envelopes)?;
            let cost=self.game_data.reserve(std::slice::from_ref(&table))?;
            let catalog=engine_formats_core::load_area_trigger_catalog(chain).map_err(error)?;
            self.game_data.triggers=Some(Triggers{catalog,table});self.game_data.charge(cost);
        }
        let data=self.game_data.triggers.as_ref().unwrap();let (ids,absent,next)=selection.select(&data.table.ids);
        let rows=ids.into_iter().map(|id|{
            let t=data.catalog.get(id).ok_or("typed area trigger row missing")?;
            Ok(json!({"id":t.id,"ordinal":data.table.ids.iter().position(|key|*key==id),"map_id":t.map_id,"position_yards":t.position,"radius_yards":t.radius,"box_size_yards":t.box_size,"box_yaw_radians":t.box_yaw}))
        }).collect::<Result<Vec<_>,String>>()?;
        response(self.game_data.epoch,std::slice::from_ref(&data.table),rows,absent,data.table.ids.len(),next)
    }
    fn game_data_skills(&mut self,v:&Value)->Result<Value,String>{
        keys(v,&["op","kind","race_id","class_id","level","ids","offset","limit"])?;
        let selection=Selection::parse(v)?; let race=integer(v,"race_id",1,32)? as u8; let class=integer(v,"class_id",1,32)? as u8; let level=integer(v,"level",1,60)? as u32;
        let kind=v["kind"].as_str().ok_or("invalid game data skills kind")?;
        if kind!="lines" && kind!="abilities" { return Err("invalid game data skills kind".into()); }
        if self.game_data.skills.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let mut tables=[&ICONS,&LINES,&ABILITIES,&CATEGORIES,&RACE_CLASS].iter().map(|s|preflight(chain,s,&self.mpq_envelopes)).collect::<Result<Vec<_>,_>>()?;joined_icon_text(&mut tables,1,0)?;
            let cost=self.game_data.reserve(&tables)?; let catalog=engine_formats_core::load_skill_line_catalog(chain).map_err(error)?;
            let line_ids=tables[1].sorted_ids(); let ability_ids=tables[2].sorted_ids();
            self.game_data.skills=Some(Skills{catalog,line_ids,ability_ids,tables}); self.game_data.charge(cost);
        }
        let data=self.game_data.skills.as_ref().unwrap(); let index=if kind=="lines"{&data.line_ids}else{&data.ability_ids};
        let (ids,absent,next)=selection.select(index); let mut rows=Vec::new();
        for id in ids {
            if kind=="lines" {
                let line=data.catalog.line(id).ok_or("typed game data skill row missing")?;
                let rc=data.catalog.race_class(id,race,class); let category=data.catalog.category(line.category_id);
                let icon_id=data.tables[1].refs.get(&id).map_or(0,|r|r[0]); let mut joins=Vec::new();
                if line.category_id!=0 && category.is_none(){joins.push(missing("SkillLineCategory",line.category_id));}
                if icon_id!=0 && line.icon.is_none(){joins.push(missing("SpellIcon",icon_id));}
                rows.push(json!({"id":id,"name":line.name,"description":line.description,"icon_id":icon_id,"icon":line.icon,
                    "category_id":line.category_id,"category":category.map(|(name,order)|json!({"name":name,"order":order})),
                    "race_class":rc.map(|r|json!({"flags":r.flags,"min_level":r.min_level,"cost_index":r.cost_index,"hidden":r.hidden(),"mono":r.mono(),"unlearnable":r.unlearnable(),"displays_untrained":r.displays_untrained(level),"skill_up_silent":r.skill_up_silent()})),
                    "matching_race_class_rule":rc.is_some(),"missing_joins":joins}));
            } else {
                let a=data.catalog.ability(id).ok_or("typed game data ability row missing")?;
                let joins=if data.catalog.line(a.skill_id).is_none(){vec![missing("SkillLine",a.skill_id)]}else{Vec::new()};
                rows.push(json!({"id":id,"skill_id":a.skill_id,"required_skill_value":a.req_skill_value,"forward_spell_id":a.forward_spell_id,
                    "trivial_low":a.trivial_low,"trivial_high":a.trivial_high,"spell_tab":data.catalog.spell_tab(id,race,class),"missing_joins":joins,
                    "unresolved_joins":["Spell"]}));
            }
        }
        let mut result=response(self.game_data.epoch,&data.tables,rows,absent,index.len(),next)?; result["kind"]=json!(kind); result["race_id"]=json!(race); result["class_id"]=json!(class); bounded(result)
    }
    fn game_data_talents(&mut self,v:&Value)->Result<Value,String>{
        keys(v,&["op","race_id","class_id","tab_id","ids","offset","limit"])?;
        let selection=Selection::parse(v)?; let race=integer(v,"race_id",1,32)? as u8; let class=integer(v,"class_id",1,32)? as u8;
        let tab=if v.get("tab_id").is_some(){Some(integer(v,"tab_id",1,u32::MAX as u64)? as u32)}else{None};
        if tab.is_none() && (v.get("ids").is_some()||v.get("offset").is_some()||v.get("limit").is_some()){return Err("game data talent selection requires tab_id".into());}
        if self.game_data.talents.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let tables=vec![preflight(chain,&TABS,&self.mpq_envelopes)?,preflight(chain,&TALENTS,&self.mpq_envelopes)?]; let cost=self.game_data.reserve(&tables)?;
            let catalog=engine_formats_core::load_talent_catalog(chain).map_err(error)?;
            self.game_data.talents=Some(Talents{catalog,tables}); self.game_data.charge(cost);
        }
        let data=self.game_data.talents.as_ref().unwrap(); let tabs=data.catalog.tabs_for_class(race,class);
        if tab.is_some_and(|id|!tabs.iter().any(|t|t.id==id)){return Err("game data talent tab not admitted for race/class".into());}
        let native=tab.map(|id|data.catalog.talents_in_tab(id)).unwrap_or(&[]);
        let index=native.iter().map(|t|t.id).collect::<Vec<_>>();
        let (_,absent,next)=selection.select(&index);
        let picked:Vec<(usize,&engine_formats_core::Talent)>=if let Some(ids)=&selection.ids {
            let mut found=ids.iter().filter_map(|id|native.iter().enumerate().find(|(_,t)|t.id==*id)).collect::<Vec<_>>();
            found.sort_by_key(|(ordinal,_)|*ordinal); found
        }else{native.iter().enumerate().skip(selection.offset).take(selection.limit).collect()};
        // Preserve the native GetTalentInfo ordinal even for a selected-ID request.
        let rows=picked.into_iter().map(|(ordinal,t)|{
            let joins=if t.prereq_talent!=0 && data.catalog.talent(t.tab,t.prereq_talent).is_none(){vec![missing("Talent",t.prereq_talent)]}else{Vec::new()};
            json!({"id":t.id,"tab_id":t.tab,"ordinal":ordinal,"row":t.row,"column":t.col,"rank_spell_ids":t.ranks,"max_rank":t.max_rank(),
                "prerequisite_talent_id":t.prereq_talent,"prerequisite_rank":t.prereq_rank,"required_spell_id":t.required_spell,"exceptional":t.exceptional,
                "missing_joins":joins,"unresolved_joins":["Spell"]})
        }).collect();
        let mut result=response(self.game_data.epoch,&data.tables,rows,absent,index.len(),next)?;
        result["tabs"]=json!(tabs.iter().map(|t|json!({"id":t.id,"name":t.name,"race_mask":t.race_mask,"class_mask":t.class_mask,"background":t.background})).collect::<Vec<_>>());
        result["tab_id"]=json!(tab); result["race_id"]=json!(race); result["class_id"]=json!(class); bounded(result)
    }
    fn game_data_spells(&mut self,v:&Value)->Result<Value,String>{
        keys(v,&["op","ids","offset","limit","joins","level"])?; let selection=Selection::parse(v)?;
        let resolve=if v.get("joins").is_some(){v["joins"].as_bool().ok_or("invalid game data joins flag")?}else{false};
        let level=if v.get("level").is_some(){integer(v,"level",1,60)? as u32}else{1};
        if self.game_data.spells.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let mut tables=[&ICONS,&DISPELS,&SPELL_CATEGORIES,&SPELLS].iter().map(|s|preflight(chain,s,&self.mpq_envelopes)).collect::<Result<Vec<_>,_>>()?;joined_icon_text(&mut tables,3,0)?;
            let cost=self.game_data.reserve(&tables)?; let catalog=engine_formats_core::load_spell_catalog(chain).map_err(error)?;
            let ids=tables[3].sorted_ids(); self.game_data.spells=Some(Spells{catalog,ids,tables}); self.game_data.charge(cost);
        }
        if resolve && self.game_data.spell_joins.is_none(){
            let chain=self.chain.as_mut().ok_or("archive chain not mounted")?;
            let mut tables=Vec::new();let mut absent=Vec::new();
            for spec in [&CAST_TIMES,&DURATIONS,&RANGES,&RADII,&VISUALS,&VISUAL_KITS,&EFFECT_NAMES,&CHAINS] {
                if chain.archive_for(&format!("DBFilesClient\\{}.dbc",spec.name)).is_ok(){tables.push(preflight(chain,spec,&self.mpq_envelopes)?);}
                else{absent.push(spec.name);}
            }
            for table in &mut tables{if table.name=="SpellVisualEffectName"{table.text*=2;}}
            let cost=self.game_data.reserve(&tables)?;
            let times=if absent.contains(&"SpellCastTimes"){Default::default()}else{engine_formats_core::load_spell_cast_times(chain).map_err(error)?};
            let durations=if absent.contains(&"SpellDuration"){Default::default()}else{engine_formats_core::load_spell_durations(chain).map_err(error)?};
            let ranges=if absent.contains(&"SpellRange"){Default::default()}else{engine_formats_core::load_spell_ranges(chain).map_err(error)?};
            let radii=if absent.contains(&"SpellRadius"){Default::default()}else{engine_formats_core::load_spell_radii(chain).map_err(error)?};
            let visuals=if ["SpellVisual","SpellVisualKit","SpellVisualEffectName","SpellChainEffects"].iter().any(|s|absent.contains(s)){None}else{Some(engine_formats_core::load_spell_visual_catalog(chain).map_err(error)?)};
            self.game_data.spell_joins=Some(SpellJoins{times,durations,ranges,radii,visuals,tables,absent});self.game_data.charge(cost);
        }
        let data=self.game_data.spells.as_ref().unwrap(); let (ids,absent,next)=selection.select(&data.ids);
        let icons:HashSet<u32>=data.tables[0].ids.iter().copied().collect(); let dispels:HashSet<u32>=data.tables[1].ids.iter().copied().collect(); let categories:HashSet<u32>=data.tables[2].ids.iter().copied().collect();
        let mut rows=Vec::new();
        for id in ids {
            let s=data.catalog.get(id).ok_or("typed game data spell row missing")?;
            let icon_id=data.tables[3].refs.get(&id).map_or(0,|r|r[0]); let mut joins=Vec::new();
            for (table,key,known) in [("SpellIcon",icon_id,&icons),("SpellIcon",s.active_icon_id,&icons),("SpellDispelType",s.dispel,&dispels),("SpellCategory",s.category,&categories)] {
                if key!=0 && !known.contains(&key){joins.push(missing(table,key));}
            }
            for key in s.effect_trigger_spell.iter().copied().chain(std::iter::once(s.modal_next_spell)) {
                if key!=0 && data.catalog.get(key).is_none(){joins.push(missing("Spell",key));}
            }
            let effects=(0..3).map(|i|json!({"slot":i,"effect":s.effects[i],"base_points":s.effect_base_points[i],"die_sides":s.effect_die_sides[i],
                "base_dice":s.effect_base_dice[i],"dice_per_level":s.effect_dice_per_level[i],"real_points_per_level":s.effect_real_points_per_level[i],
                "mechanic":s.effect_mechanic[i],"implicit_target_a":s.effect_implicit_target_a[i],"implicit_target_b":s.effect_implicit_target_b[i],
                "radius_index":s.effect_radius_index[i],"apply_aura":s.effect_apply_aura[i],"amplitude_ms":s.effect_amplitude[i],
                "multiple_value":s.effect_multiple_value[i],"chain_targets":s.effect_chain_targets[i],"item_type":s.effect_item_type[i],
                "misc_value":s.effect_misc_value[i],"trigger_spell":s.effect_trigger_spell[i],"points_per_combo_point":s.effect_points_per_combo_point[i],"damage_multiplier":s.damage_multiplier[i]})).collect::<Vec<_>>();
            let learn=data.catalog.learn_effects(id).iter().map(|effect|match effect {
                engine_formats_core::LearnEffect::Spell(id)=>json!({"kind":"spell","id":id}),
                engine_formats_core::LearnEffect::PetSpell(id)=>json!({"kind":"pet_spell","id":id}),
                engine_formats_core::LearnEffect::SkillStep{skill,step}=>json!({"kind":"skill_step","skill_id":skill,"step":step}),
            }).collect::<Vec<_>>();
            let mut row=json!({"id":id,"name":s.name,"rank":s.rank,"icon_id":icon_id,"icon":s.icon,"active_icon_id":s.active_icon_id,"active_icon":s.active_icon,
                "description":s.description,"aura_description":s.aura_description,"visual_id":s.visual,"projectile_speed":s.speed,
                "attributes":[s.attributes,s.attributes_ex,s.attributes_ex2,s.attributes_ex3,s.attributes_ex4],"school":s.school,"mechanic":s.mechanic,"prevention_type":s.prevention_type,
                "spell_family":s.spell_family,"family_flags_words":[s.spell_family_flags as u32,(s.spell_family_flags>>32) as u32],"passive":s.passive,"cast_ui":s.cast_ui,
                "base_level":s.base_level,"max_level":s.max_level,"spell_level":s.spell_level,"dispel_id":s.dispel,"dispel_name":data.catalog.dispel_name(s),
                "dispel_label_visible":data.tables[1].refs.get(&s.dispel).is_some_and(|r|r[0]!=0),"category_id":s.category,"category_wildcard":s.category_wildcard});
            let extra=json!({"recovery_ms":s.recovery_ms,"category_recovery_ms":s.category_recovery_ms,"start_recovery_category":s.start_recovery_category,"start_recovery_ms":s.start_recovery_ms,
                "interrupt_flags":s.interrupt_flags,"aura_interrupt_flags":s.aura_interrupt_flags,"channel_interrupt_flags":s.channel_interrupt_flags,
                "power_type":s.power_type,"mana_cost":s.mana_cost,"mana_cost_percent":s.mana_cost_pct,"mana_cost_per_level":s.mana_cost_per_level,"mana_per_second":s.mana_per_second,
                "range_index":s.range_index,"duration_index":s.duration_index,"casting_time_index":s.casting_time_index,"targets":s.targets,"target_creature_type":s.target_creature_type,
                "stances":s.stances,"stances_not":s.stances_not,"caster_aura_state":s.caster_aura_state,"target_aura_state":s.target_aura_state,
                "totems":s.totems,"reagents":s.reagents,"equipped_item_class":s.equipped_item_class,"equipped_item_subclass_mask":s.equipped_item_subclass_mask,
                "equipped_item_inventory_type_mask":s.equipped_item_inventory_type_mask,"requires_spell_focus":s.requires_spell_focus,"shapeshift_form":s.shapeshift_form,"stance_bar_order":s.stance_bar_order});
            if let Value::Object(fields)=extra {row.as_object_mut().unwrap().extend(fields);}
            let extra=json!({"proc_flags":s.proc_flags,"proc_chance":s.proc_chance,"proc_charges":s.proc_charges,"stack_amount":s.stack_amount,"max_target_level":s.max_target_level,"max_affected_targets":s.max_affected_targets,
                "modal_next_spell":s.modal_next_spell,"open_lock":s.open_lock.as_ref().map(|l|json!({"lock_type":l.lock_type,"slot":l.effect})),
                "effects":effects,"learn_effects":learn,"learned_spell_id":data.catalog.learned_spell(id),"declared_language_id":data.catalog.declared_language(id),
                "missing_joins":joins,"unresolved_joins":["SpellCastTimes","SpellDuration","SpellRange","SpellRadius","SpellVisual"],"execution_status":"UNMAPPED"});
            if let Value::Object(fields)=extra {row.as_object_mut().unwrap().extend(fields);}
            if resolve {
                let resolved=self.game_data.spell_joins.as_ref().unwrap();
                let time=resolved.times.get(s.casting_time_index);
                let duration=resolved.durations.get(s.duration_index);
                let range=resolved.ranges.get(s.range_index);
                let mut missing=row["missing_joins"].as_array().unwrap().clone();
                for (table,index,known) in [("SpellCastTimes",s.casting_time_index,time.is_some()),("SpellDuration",s.duration_index,duration.is_some()),("SpellRange",s.range_index,range.is_some())] {
                    if index!=0 && !known{missing.push(super::gameplay_data::missing(table,index));}
                }
                for (i,index) in s.effect_radius_index.iter().copied().enumerate(){
                    let radius=resolved.radii.get(index);
                    if index!=0 && radius.is_none(){missing.push(super::gameplay_data::missing("SpellRadius",index));}
                    row["effects"][i]["radius"]=json!(radius.map(|r|json!({"radius_yards":r.radius,"per_level_yards":r.per_level,"max_yards":r.max})));
                }
                row["casting_time"]=json!(time.map(|t|json!({"base_ms":t.base_ms,"per_level_ms":t.per_level_ms,"minimum_ms":t.minimum_ms,"resolved_ms":t.resolved_ms(level,s.base_level)})));
                row["duration"]=json!(duration.map(|d|json!({"base_ms":d.base_ms,"per_level_ms":d.per_level_ms,"max_ms":d.max_ms,"permanent":d.is_permanent()})));
                row["range"]=json!(range.map(|r|json!({"min_yards":r.min,"max_yards":r.max,"flags":r.flags,"melee":r.is_melee()})));
                row["missing_joins"]=json!(missing);
                let unresolved=resolved.absent.clone();row["unresolved_joins"]=json!(unresolved);
                let visual=resolved.visuals.as_ref().and_then(|v|v.stages(s.visual));
                let mut visual_value=Value::Null;
                if let Some(stages)=visual {
                    let catalog=resolved.visuals.as_ref().unwrap();let mut kits=serde_json::Map::new();
                    for id in [stages.precast,stages.cast,stages.impact,stages.state,stages.channel,stages.area_kit] {
                        if id==0 || kits.contains_key(&id.to_string()){continue;}
                        if let Some(kit)=catalog.kit(id){
                            let effects=kit.effects().map(|(tag,id)|{
                                let path=catalog.effect_path(id);
                                if path.is_none(){missing.push(super::gameplay_data::missing("SpellVisualEffectName",id));}
                                json!({"attachment_tag":tag,"effect_id":id,"path":path})
                            }).collect::<Vec<_>>();
                            let procs=kit.char_procs().map(|p|{
                                let mut value=json!({"type":p.ty,"params":p.params});
                                if let Some(proc)=p.as_chain(){
                                    let chain=catalog.chain_effect(proc.effect_id);
                                    if chain.is_none(){missing.push(super::gameplay_data::missing("SpellChainEffects",proc.effect_id));}
                                    value["chain"]=json!({"effect_id":proc.effect_id,"beams":proc.beams,"channel":proc.flag,
                                        "effect":chain.map(|e|json!({"average_segment_yards":e.avg_seg_len,"half_width_yards":e.half_width,
                                            "noise_scale":e.noise_scale,"scroll_period_s":e.scroll_period_s,"life_ms":e.bolt_life_ms,
                                            "stagger_ms":e.bolt_stagger_ms,"texture":e.texture}))});
                                }
                                value
                            }).collect::<Vec<_>>();
                            kits.insert(id.to_string(),json!({"animation_id":kit.anim_id,"sound_id":kit.sound,"shake_id":kit.shake,"effects":effects,"character_procs":procs}));
                        }else{missing.push(super::gameplay_data::missing("SpellVisualKit",id));}
                    }
                    for id in [stages.missile_model,stages.area_effect]{
                        if id!=0 && id!=u32::MAX && catalog.effect_path(id).is_none(){missing.push(super::gameplay_data::missing("SpellVisualEffectName",id));}
                    }
                    visual_value=json!({"precast":stages.precast,"cast":stages.cast,"impact":stages.impact,"state":stages.state,"channel":stages.channel,
                        "missile_effect_id":stages.missile_model,"missile_path":catalog.effect_path(stages.missile_model),"missile_attach_index":stages.missile_attach,
                        "missile_sound_id":stages.missile_sound,"strike_sound_id":stages.strike_sound,"missile_gate":stages.missile_gate,"area_gate":stages.area_gate,
                        "area_effect_id":stages.area_effect,"area_path":catalog.effect_path(stages.area_effect),"area_kit_id":stages.area_kit,"kits":kits});
                }else if s.visual!=0{missing.push(super::gameplay_data::missing("SpellVisual",s.visual));}
                row["visual"]=visual_value;row["missing_joins"]=json!(missing);
                row["caster_level"]=json!(level);
            }
            rows.push(row);
        }
        let mut result=response(self.game_data.epoch,&data.tables,rows,absent,data.ids.len(),next)?;
        if resolve {for table in &self.game_data.spell_joins.as_ref().unwrap().tables{result["source_tables"].as_array_mut().unwrap().push(table.meta());}}
        bounded(result)
    }
}
