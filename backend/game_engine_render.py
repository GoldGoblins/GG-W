"""Render-budget contracts for the low-cost-first GAME ENGINE pipeline.

The contract separates policy from the active QtQuick3D renderer. Flora uses
native instancing; optional upscalers remain separate so the potato profile
does not depend on a vendor driver or a heavyweight engine runtime.
"""

from __future__ import annotations

from copy import deepcopy
import os
from typing import Any


SCHEMA = "gg.game-engine.render.v1"
RICH_3D = "RICH_3D"
DOS_2D = "DOS_2D"
PRESENTATION_MODES = (RICH_3D, DOS_2D)
PROFILES = {
    "POTATO": {
        # At the normal third-person distance the host uses a 4-cell render
        # radius (81 terrain cells), expanding to this cap only as the editor
        # camera zooms out.
        "resolution_scale": 0.67,
        "anti_aliasing": "NONE",
        "upscaler": "NONE",
        "shadow_policy": "BLOB_AND_BAKED",
        "max_visible_instances": 48,
        "max_visible_particles": 32,
        "max_render_radius": 5,
        "world_view_distance_m": 1400,
        "max_dynamic_lights": 2,
        "max_light_beacons": 12,
        "texture_budget_mb": 128,
    },
    "PS2_CLASSIC": {
        # A deliberately restrained console-era pass: native vertex color,
        # shared key/fill and a capped local-light pool, no temporal history,
        # AO or filmic post-processing.
        # Qt still selects its normal RHI backend; this is a render policy,
        # not a second engine or a claim of hardware-level PS2 emulation.
        "resolution_scale": 0.82,
        "anti_aliasing": "NONE",
        "upscaler": "NONE",
        "shadow_policy": "BAKED_AND_BLOB",
        "ambient_occlusion": False,
        "temporal_aa": False,
        "tonemap": "LINEAR",
        "point_light": True,
        "max_visible_instances": 128,
        "max_visible_particles": 256,
        "max_render_radius": 7,
        "world_view_distance_m": 3200,
        "max_dynamic_lights": 6,
        "max_light_beacons": 24,
        "water_vertex_grid": 33,
        "texture_budget_mb": 256,
    },
    "BALANCED": {
        "resolution_scale": 1.0,
        "anti_aliasing": "MSAA",
        "upscaler": "NONE",
        "shadow_policy": "BAKED_PLUS_ONE_DYNAMIC",
        "max_visible_instances": 96,
        "max_visible_particles": 128,
        "max_render_radius": 10,
        "world_view_distance_m": 4000,
        "max_dynamic_lights": 8,
        "max_light_beacons": 32,
        "texture_budget_mb": 512,
    },
    "MODERN": {
        "resolution_scale": 1.0,
        "anti_aliasing": "MSAA_PLUS_TEMPORAL_AA",
        "upscaler": "FSR_XESS_DLSS_OPTIONAL",
        "shadow_policy": "CACHED_CASCADES",
        "max_visible_instances": 160,
        "max_visible_particles": 256,
        "max_render_radius": 10,
        "world_view_distance_m": 6000,
        "max_dynamic_lights": 10,
        "max_light_beacons": 40,
        "texture_budget_mb": 1024,
    },
    "CINEMATIC": {
        "resolution_scale": 1.25,
        "anti_aliasing": "SSAA_PLUS_TEMPORAL_AA",
        "upscaler": "DLSS_OR_FSR_OPTIONAL",
        "shadow_policy": "BAKED_CINEMATIC_PLUS_CONTACT",
        "max_visible_instances": 192,
        "max_visible_particles": 512,
        "max_render_radius": 10,
        "world_view_distance_m": 9000,
        "max_dynamic_lights": 10,
        "max_light_beacons": 48,
        "texture_budget_mb": 2048,
    },
}
PROFILE_NAMES = tuple(PROFILES)


def optional_layers() -> list[dict[str, str]]:
    """Describe vendor layers without silently pretending they are linked."""
    return [
        {
            "name": "DLSS",
            "status": "NOT_LINKED",
            "activation": "NATIVE_RENDER_PLUGIN_AND_VENDOR_RUNTIME",
        },
        {
            "name": "FSR",
            "status": "NOT_LINKED",
            "activation": "NATIVE_RENDER_PLUGIN_OR_SHADER_PASS",
        },
        {
            "name": "XeSS",
            "status": "NOT_LINKED",
            "activation": "NATIVE_RENDER_PLUGIN_AND_VENDOR_RUNTIME",
        },
        {
            "name": "GPU_TIMESTAMPS",
            "status": "QT_WINDOW_OPTIONAL_NOT_ENABLED_BY_DEFAULT",
            "activation": "QQUICK_GRAPHICS_CONFIGURATION_SET_TIMESTAMPS",
        },
    ]


def normalize_profile(value: Any, default: str = "BALANCED") -> str:
    profile = str(value or default).upper()
    return profile if profile in PROFILES else default


def normalize_presentation_mode(
    value: Any,
    default: str = RICH_3D,
) -> str:
    """Normalize the presentation layer without touching simulation state."""
    mode = str(value or default).upper()
    if mode in PRESENTATION_MODES:
        return mode
    return default if default in PRESENTATION_MODES else ""


def presentation_view(mode: Any, reason: Any = "") -> dict[str, Any]:
    """Describe the two render stages and their shared-data boundary."""
    normalized = normalize_presentation_mode(mode, "")
    if not normalized:
        normalized = RICH_3D
    failure_reason = str(reason or "").strip()[:96]
    if normalized == RICH_3D:
        failure_reason = ""
    return {
        "mode": normalized,
        "rich_3d": normalized == RICH_3D,
        "fallback_available": True,
        "fallback_mode": DOS_2D,
        "reason": failure_reason or "NONE",
        "authority": "SHARED_SIMULATION_SNAPSHOT",
        "simulation_unchanged": True,
        "transition": "PRESENTATION_ONLY_NO_WORLD_RESET",
    }


def build_render_view(
    profile: str,
    *,
    active_entities: int,
    active_particles: int,
    snapshot_build_ms: float = 0.0,
    presentation_mode: str = RICH_3D,
    presentation_reason: str = "",
) -> dict[str, Any]:
    name = normalize_profile(profile)
    policy = deepcopy(PROFILES[name])
    visible_instances = max(0, min(int(active_entities), policy["max_visible_instances"]))
    visible_particles = max(0, min(int(active_particles), policy["max_visible_particles"]))
    return {
        "schema": SCHEMA,
        "profile": name,
        "presentation": presentation_view(
            presentation_mode,
            presentation_reason,
        ),
        "backend": "QT_RHI_AUTO",
        "requested_rhi_backend": str(os.environ.get("QSG_RHI_BACKEND", "AUTO")).upper(),
        "backend_policy": "OPENGL_VULKAN_METAL_D3D_SELECTED_BY_QT_RHI",
        "policy": policy,
        "anti_aliasing": {
            "mode": policy["anti_aliasing"],
            "temporal_history": "OPTIONAL_RENDERER_LAYER",
        },
        "upscaling": {
            "mode": policy["upscaler"],
            "availability": "RUNTIME_PROBE_REQUIRED",
            "fallback": "NATIVE_RESOLUTION_OR_LINEAR_SCALE",
        },
        "optional_layers": optional_layers(),
        "visibility": {
            "strategy": "CELL_PORTAL_HLOD_PROJECTED_ERROR",
            "visible_instances": visible_instances,
            "visible_particles": visible_particles,
        },
        "instancing": {
            "strategy": "BOUNDED_QML_MODELS_FOR_WORLD_ENTITIES",
            "native_bridge": "QQUICK3D_INSTANCING_LINKED_FOR_FLORA",
        },
        "particle_rendering": {
            "strategy": "BOUNDED_ALPHA_AND_ADDITIVE_CROSSED_BILLBOARD_BATCHES",
            "visible_count": visible_particles,
            "geometry_batches": 1 if visible_particles else 0,
            "geometry_batches_status": "HOST_PARTICLES_ONLY;_CLIENT_ADDS_BOUNDED_WORLD_FX",
            "client_geometry_batches_max": 2,
        },
        "measurement": {
            "kind": "CPU_HOST_SNAPSHOT_TIMING",
            "snapshot_build_ms": round(max(0.0, float(snapshot_build_ms)), 4),
            "gpu_timestamp_queries": "NOT_CONNECTED",
            "scene_counters": "QT_VIEW3D_RENDER_STATS_IN_PERF_INSPECTOR",
        },
        "draw_calls": None,
        "draw_calls_status": "CLIENT_QT_VIEW3D_COUNTER_NOT_IN_SERVER_SNAPSHOT",
        "honesty": "HOST_CPU_TIMING;_SCENE_COUNTERS_CLIENT_SIDE;_OPTIONAL_GPU_TIMING_IS_WHOLE_WINDOW",
    }
