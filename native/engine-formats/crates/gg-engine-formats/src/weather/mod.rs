//! Original weather state, packet pools and wind over the local native collision pages.
#![allow(dead_code)]
use glam::{Vec3,Quat};
use serde_json::{json,Value};
use std::collections::HashMap;
mod state;mod wind;mod pool;mod mist;mod render;mod host;pub use host::System;
use state::{WeatherKind,WeatherState};
use wind::{WeatherWind,wow_azimuth_to_bevy};
use pool::{Pool,HeightCache};
use mist::Mist;
#[derive(Clone,Copy)] struct EffectVertex{pos:[f32;3],uv:[f32;2],color:[f32;4]}
trait Ground {fn down(&self,p:Vec3,depth:f32)->Option<f32>;}
impl Ground for HashMap<String,crate::collision::Page>{
    fn down(&self,p:Vec3,depth:f32)->Option<f32>{self.values().filter_map(|page|page.down_to(Vec3::new(-p.z,-p.x,p.y),depth)).max_by(f32::total_cmp)}
}
// ===== The reference's constants =====

/// The weather leg: the reference runs the shader leg unless `useWeatherShaders` (default 1,
/// `0x67b81d`) is 0 or its ARB programs fail to validate (`0x58b360`); this always runs it.
const SHADER_LEG: bool = true;
/// Per-packet record capacity, 6144 (`0x80ffc8` as a float, which the open stamp divides by the
/// rate). Not a population cap: packets form a growing list, so demand bounds the population.
const PACKET_CAP: usize = 0x1800;
/// The anchor cull, retirement condition 3 of the active-list walk (`0x677ff0`; `0x6780d3`–
/// `0x678110` against `0x810008` = 200): a packet whose open-time anchor is farther than this
/// from the eye, in 3-D (`0x4549f0`), is discarded outright. Only a teleport can trip it.
const RETIRE_DIST: f32 = 200.0;
/// Slack on [`RETIRE_DIST`] for active drops, which keep no packet here and go by their own
/// distance. The reference draws no flake past `200 + box corner + 1.75·W` (≤ ~324 yd), so this
/// cull is strictly weaker than its own and never retires a flake it would still draw.
const RETIRE_DROP_SLACK: f32 = 50.0;
/// Deviation: a spawn ceiling on live plus pending drops, which the reference lacks, because each
/// flake here costs a 4-vertex quad. Demand is `rate · fall_time` plus a packet, and the fall
/// depends on the ground under the spawn plane, so this sits above the worst case measured at
/// the ungained rate; nothing is preallocated. It bites when the state log's pipe count falls
/// below [`PACKET_CAP`].
const fn pool_bound(kind: WeatherKind) -> usize {
    match kind {
        WeatherKind::Snow => {
            if SHADER_LEG {
                0x20000
            } else {
                0x4000
            }
        }
        _ => {
            if SHADER_LEG {
                0xC000
            } else {
                0x4000
            }
        }
    }
}
/// The largest pool bound, the `take(…)` guard on a push.
const POOL: usize = pool_bound(WeatherKind::Snow);
// The density gain `K` in `rate = K·P·grade` is `WeatherState::density_gain()`, the
// `weatherDensity` table (`0x67b870`: 0.1, 0.33, 0.66, 1.0 for settings 0 to 3).
/// Rain population `P`: fixed-function `0x80ffa8` = 6500, shader `0x80ffac` = 35000.
const RAIN_P: f32 = if SHADER_LEG { 35000.0 } else { 6500.0 };
/// Snow population `P`: fixed-function `0x80ffdc` = 1300, shader `0x80ffe0` = 14000.
const SNOW_P: f32 = if SHADER_LEG { 14000.0 } else { 1300.0 };
/// Deviation: the drop rate is scaled to a 30 fps client, the frame rate the reference's look
/// was matched at, because the reference budgets `min(dt, 1/60)·rate` and drops the remainder
/// (`0x67846f`–`0x678480`), so it emits half its nominal rate at 30 fps. 60 is byte-faithful.
const REF_MAXFPS: f32 = 30.0;
/// [`REF_MAXFPS`] as a gain on the drop rate. Never on the mist: its accumulator carries its
/// remainder (`0x67b172`), so it is already frame-rate independent in the reference.
const REF_FPS_GAIN: f32 = if REF_MAXFPS < 60.0 {
    REF_MAXFPS / 60.0
} else {
    1.0
};
/// A patter lives 0.25 s (`0x675280`: `lifetime = now + 0.25`).
const PATTER_LIFE: f32 = 0.25;
/// Per-frame spawn budget uses `min(dt, 1/60)` (`0x80ffcc`).
const DT_CAP: f32 = 1.0 / 60.0;
/// The spawn box leads the camera by `1.75·wind` (`0x8680f8`).
const WIND_LEAD: f32 = 1.75;
/// The drift heading's centre, −1.57 rad (`0x80ffbc`): a fixed world azimuth in the WoW frame
/// for rain and snow, never the wind's heading.
const DRIFT_AZ_CENTER: f32 = -1.57;
/// Rain fall speed `vz = −28 − 4w − 2w·r` (`0x80306c`, `0x80ffb4`).
const RAIN_VZ_BASE: f32 = 28.0;
const RAIN_VZ_W: f32 = 4.0;
const RAIN_VZ_RNG: f32 = 2.0;
/// Rain drift speed `((2r − 1) + 9.49)·w + 0.01`, heading spread `0.209·w + 0.052` rad.
const RAIN_DRIFT_BASE: f32 = 9.49;
const RAIN_DRIFT_EPS: f32 = 0.01;
const RAIN_SPREAD_W: f32 = f32::from_bits(0x3e56_7750); // 0x80ffc4 ≈ 0.20944 (12°)
const RAIN_SPREAD_BIAS: f32 = f32::from_bits(0x3d56_7750); // 0x80ffc0 ≈ 0.05236 (3°)
/// The streak triangle: base `head ∓ 0.05·right` (`0x80ff78`), apex `head + tilt·(2·antiVel̂)`
/// (`0x80ff74`), fixed world sizes, not scaled by speed; no vertex colour.
const STREAK_HALF_W: f32 = 0.05;
const STREAK_TAIL: f32 = 2.0;
/// Rain's forced fog window (render states 0x0a/0x0b): under Mod2x its grey-0.5 colour is
/// neutral, so this is the streak distance fade. `EffectFog::Rain`'s row is written from these.
pub(crate) const RAIN_FOG_START: f32 = 70.0;
pub(crate) const RAIN_FOG_END: f32 = 75.0;
/// Patter triangle half-edges: `view_right/12` and `view_up/6` (`0x80e004`, `0x803568`).
const PATTER_RIGHT: f32 = 1.0 / 12.0;
const PATTER_UP: f32 = 1.0 / 6.0;
/// Spawn-box horizontal half-extents, from the ctor args (`0x67be40`): rain 130×130
/// (`0x43020000`), snow 90×90 (`0x42b40000`).
const RAIN_HALF_XY: f32 = 65.0;
const SNOW_HALF_XY: f32 = 45.0;
/// The slab's lift in slab-local space, half the ctor's vertical extent (rain 75, snow 60): the
/// box's vertical random is dead but this lift is not (`0x674df6`, `T = −37.5/Vz`). Not a world
/// height: the tilt fans spawn heights to `z_off·cos α ∓ half_xy·sin α`.
const RAIN_Z_OFF: f32 = 37.5;
const SNOW_Z_OFF: f32 = 30.0;
/// Snow fall speed `vz = −2 − 3.5m − m·r` (`0x6778bc`–`0x6778ec`), 2 to 6.5 yd/s.
const SNOW_VZ_BASE: f32 = 2.0;
const SNOW_VZ_W: f32 = 3.5;
/// Snow horizontal drift `((r − 0.5) + 5.985)·m + 0.015`.
const SNOW_DRIFT_OFF: f32 = 5.985;
const SNOW_DRIFT_EPS: f32 = 0.015;
/// Snow heading spread `2π − 5.934·m` (`0x80fff4`): any direction calm, ±10° in a blizzard.
const SNOW_SPREAD_W: f32 = f32::from_bits(0x40bd_e44f); // ≈ 5.9341197
/// Snow flake size in pixels, `snowpoint.bls`'s `max(1, 14·clamp01(1 − 0.02·d))`, `d` in yards:
/// not a world size, not `1/d`. The point-sprite pass `0x678610` runs; `0x678960`'s 1/12
/// triangle is the fallback, taken only when `snowpoint.bls` fails, `GL_ARB_point_sprite` is
/// missing or `useWeatherShaders` is 0 (`0x677420`).
const SNOW_PX_AT_EYE: f32 = 14.0;
/// Deviation: flake pixels are pixels of an 800-px-tall screen, the height the look was matched
/// at, converted to an angle, because the reference's literal framebuffer pixels shrink with
/// resolution (2.7× smaller at 4K scale 2). At 800 px tall the reference's pixels are exact.
const SNOW_PX_REF_HEIGHT: f32 = 800.0;
/// The falloff slope: `1 − 0.02·d` reaches the 1 px floor at `d = 13/0.28 ≈ 46.4` yd.
const SNOW_PX_FALLOFF: f32 = 0.02;
/// The 1 px floor the ARB program applies last.
const SNOW_PX_MIN: f32 = 1.0;
/// A settled flake fades over 0.25 s (`0x678dfa`, constant `0x8029b0`: `max(t,0) + 0.25`).
const SNOW_SETTLE_LIFE: f32 = 0.25;
/// A falling flake fades in over its first second, the vertex program's `clamp01(t − f1)`.
const SNOW_FADE_IN: f32 = 1.0;

fn rand01(rng: &mut u32) -> f32 {
    let mut x = *rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *rng = x;
    (x >> 8) as f32 / (1u32 << 24) as f32
}

/// Ground-layer capacity: the reference's patter packet holds 0x1800 (`Packet<Patter,Rain>`).
const GROUND_CAP: usize = 0x1800;

