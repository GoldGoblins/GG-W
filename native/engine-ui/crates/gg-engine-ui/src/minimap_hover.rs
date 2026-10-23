//! The painted minimap's names enter the retained original tooltip channel.
use crate::Host;
use serde_json::{json, Value};

#[derive(Default)]
pub(super) struct State {
    generation: u64,
    owner: u64,
    frame: String,
    subject: String,
    text: String,
    grey: bool,
}

fn text<'a>(v: &'a Value, key: &str, maximum: usize) -> Result<&'a str, String> {
    let s = v[key].as_str().ok_or_else(|| format!("minimap {key} required"))?;
    if s.is_empty() || s.len() > maximum || s.chars().any(char::is_control) {
        return Err(format!("invalid minimap {key}"));
    }
    Ok(s)
}

fn captures(h: &Host, frame: &str, x: f32, y: f32) -> bool {
    if h.ui.widget_kind(frame) != Some("Minimap") || !h.ui.frame_visible(frame) {
        return false;
    }
    let mut hit = h.ui.hit_test_frame(x, y);
    for _ in 0..64 {
        let Some(handle) = hit else { return false; };
        if h.ui.frame_name(handle).as_deref() == Some(frame) { return true; }
        hit = h.ui.frame_parent(handle);
    }
    false
}

pub(super) fn request(h: &mut Host, v: &Value) -> Result<Value, String> {
    let owner = v["owner"].as_u64().filter(|n| *n > 0 && *n <= 9_007_199_254_740_991)
        .ok_or("invalid minimap owner")?;
    let action = text(v, "action", 8)?;
    if action == "fade" {
        if h.minimap_hover.owner != owner { return Ok(json!(false)); }
        // The retained gate refuses to fade a plate Lua SetOwner/Set*/Hide took.
        h.ui.world_tooltip_fade();
        h.minimap_hover = State { generation: h.minimap_hover.generation, ..State::default() };
        return Ok(json!(true));
    }
    if action != "show" && action != "move" { return Err("invalid minimap action".into()); }
    let frame = text(v, "frame", 128)?;
    let subject = text(v, "subject", 256)?;
    let name = text(v, "text", 512)?;
    let grey = v["grey"].as_bool().ok_or("minimap grey flag required")?;
    let coord = |key: &str| -> Result<f32, String> {
        let n = v[key].as_f64().filter(|n| n.is_finite() && n.abs() <= 1_000_000.)
            .ok_or_else(|| format!("invalid minimap {key}"))?;
        Ok(n as f32)
    };
    let x = coord("x")?;
    let y = h.height - coord("y")?;
    if owner < h.minimap_hover.generation { return Ok(json!(false)); }
    h.ui.resolve();
    if !captures(h, frame, x, y) { return Ok(json!(false)); }
    let same = h.minimap_hover.owner == owner && h.minimap_hover.frame == frame
        && h.minimap_hover.subject == subject && h.minimap_hover.text == name
        && h.minimap_hover.grey == grey;
    if action == "move" && !same { return Ok(json!(false)); }
    if same {
        // Keep the subject memo even if Lua has since taken the plate. A move
        // must not re-render it and steal ownership back from an addon.
        if h.ui.world_tooltip_up() { h.ui.world_tooltip_move(x, y); }
        return Ok(json!(true));
    }
    if !h.ui.minimap_tooltip(name, x, y, grey) { return Ok(json!(false)); }
    h.minimap_hover = State { generation: owner, owner, frame: frame.into(), subject: subject.into(),
        text: name.into(), grey };
    Ok(json!(true))
}
