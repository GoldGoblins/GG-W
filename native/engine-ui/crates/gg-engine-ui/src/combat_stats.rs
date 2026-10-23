//! Actual GG armor in the original paper doll. Absent original stats stay unset.
use engine_ui_core::script::{UiScript,UnitCombatStats};
use serde_json::Value;

pub(crate) fn feed(ui:&mut UiScript,v:&Value)->Result<(),String>{
    if v.is_null(){ui.set_player_combat_stats(None);return Ok(());}
    let armor=v["armor"].as_f64().filter(|n|n.is_finite()&&*n>=0.&&*n<=100000.)
        .ok_or("GG combat armor invalid")?;
    let mut stats=UnitCombatStats::default();stats.resistances[0]=armor as i32;
    ui.set_player_combat_stats(Some(stats));
    Ok(())
}
