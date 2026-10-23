// Adapted from samwhosung/engine, crates/engine-world/src/particles/emit.rs.
// Original MIT/Apache-2.0 licenses retained under native/engine-formats.
//! The emission shape kernel and its RNG: one birth's position and direction, as the reference's
//! three spawn generators make them (`0x7b8890` plane, `0x7b8d70` sphere, `0x7b9500` spline).

use engine_formats_core::ParticleEmitterDef;
use glam::Vec3;

/// xorshift32 for particle jitter: visual only, determinism not required.
pub(crate) fn next_u32(state: &mut u32) -> u32 {
    let mut x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    x
}

/// A uniform random `f32` in `[0, 1)`.
pub(crate) fn rand01(state: &mut u32) -> f32 {
    (next_u32(state) >> 8) as f32 / (1u32 << 24) as f32
}

/// Uniform in (−1, 1): the reference's `S11` draw (`0x7b88dd`), same distribution, not stream.
pub(crate) fn rand_s11(state: &mut u32) -> f32 {
    rand01(state) * 2.0 - 1.0
}

/// One birth's position and unit direction in the emitter's local WoW frame (Z up, origin at the
/// record's `position`), before the caller's speed roll and space mode:
/// - plane (`0x7b8890`): uniform in the ±½·area rectangle, x from `areaLength` (`rt+0x290`) and
///   y from `areaWidth` (`rt+0x294`), in a cone about +Z at θ = S11·verticalRange and
///   φ = S11·horizontalRange;
/// - sphere (`0x7b8d70`): radius uniform in [areaLength, areaWidth], on the shell at those two
///   angles as latitude and longitude, direction radial (`sphere_up`: +Z);
/// - any shape with `zSource ≠ 0`: direction radial from the pivot `(0, 0, zSource)`.
pub(crate) fn emit_local(
    def: &ParticleEmitterDef,
    now: &engine_formats_core::ParamsNow,
    rng: &mut u32,
) -> (Vec3, Vec3) {
    let origin = Vec3::from(def.position);
    // The emitter frame's R(+Z, 90°), applied at every return, spline included: the reference
    // prepends it per emitter, whatever the shape (`0x71907f`).
    let rot90 = |v: Vec3| Vec3::new(-v.y, v.x, v.z);
    // Spline (`0x7b9500`): born on the authored Bézier chain at arc fraction t in [tMin, tMax]
    // (the area fields). Direction: radial from the zSource pivot when authored; else +Z turned
    // about the tangent by S11·spin (`vertical_range`; the reference's −ψ is the same
    // distribution) and jittered along it by U01·scatter (`horizontal_range`); else zero. No
    // parsed chain falls through to the plane kernel.
    if let (engine_formats_core::ParticleShape::Spline, Some(spline)) = (def.shape, &def.spline) {
        let (t0, t1) = (
            now.area_length.clamp(0.0, 1.0),
            now.area_width.clamp(0.0, 1.0),
        );
        let t = t0 + rand01(rng) * (t1 - t0);
        let mut pos = origin + Vec3::from(spline.eval(t));
        let dir = if now.z_source != 0.0 {
            (pos - origin - Vec3::new(0.0, 0.0, now.z_source)).normalize_or(Vec3::Z)
        } else if now.vertical_range != 0.0 {
            let tangent = Vec3::from(spline.tangent(t)).normalize_or(Vec3::Z);
            let (s, c) = (rand_s11(rng) * now.vertical_range).sin_cos();
            let dir = Vec3::Z * c + tangent.cross(Vec3::Z) * s + tangent * (tangent.z * (1.0 - c));
            if now.horizontal_range != 0.0 {
                pos += rand01(rng) * now.horizontal_range * dir;
            }
            dir
        } else {
            Vec3::ZERO
        };
        return (origin + rot90(pos - origin), rot90(dir));
    }
    // A sphere's one lat/lon unit vector is both the shell point and the radial direction (the
    // reference reuses the sincos pair, `0x7b8fba`), so a zero-radius sphere still sprays.
    let (local, shell) = if def.shape == engine_formats_core::ParticleShape::Sphere {
        let r = now.area_length + rand01(rng) * (now.area_width - now.area_length).max(0.0);
        let lat = rand_s11(rng) * now.vertical_range;
        let lon = rand_s11(rng) * now.horizontal_range;
        let (slat, clat) = lat.sin_cos();
        let (slon, clon) = lon.sin_cos();
        let shell = Vec3::new(clat * clon, clat * slon, slat); // unit by construction
        (r * shell, Some(shell))
    } else {
        // x from areaLength, y from areaWidth: swapped, an anisotropic rectangle turns 90°.
        (
            Vec3::new(
                rand_s11(rng) * 0.5 * now.area_length,
                rand_s11(rng) * 0.5 * now.area_width,
                0.0,
            ),
            None,
        )
    };
    let dir = if now.z_source != 0.0 {
        // Radial from the (0, 0, zSource) pivot; +Z at the pivot itself.
        (local - Vec3::new(0.0, 0.0, now.z_source)).normalize_or(Vec3::Z)
    } else if let Some(shell) = shell {
        if def.sphere_up() {
            Vec3::Z
        } else {
            shell // radial: the same unit draw as the birth point
        }
    } else {
        let theta = rand_s11(rng) * now.vertical_range;
        let phi = rand_s11(rng) * now.horizontal_range;
        let (st, ct) = theta.sin_cos();
        let (sp, cp) = phi.sin_cos();
        Vec3::new(st * cp, st * sp, ct)
    };
    // The reference prepends a fixed +90° about local +Z to every M2 particle emitter's matrix
    // (`0x719114`..`0x719142`, into `rt+0x1fc`), on the kernel-relative vectors only, not the
    // record position; applied here at emission, every consumer inherits it.
    (origin + rot90(local), rot90(dir))
}

