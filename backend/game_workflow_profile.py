"""Small reproducible scene experiments; distinguish source counts and GPU data."""
from __future__ import annotations

import math
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

from backend import game_engine_assets as runtime, game_workflow_common as common
from backend import game_workflow_formats as formats, game_workflow_dependencies as deps
from backend.platform_process import run_bounded

SCHEMA = "gg.game-workflow.scene-profile.v1"
STAGES = ("FULL", "VISIBILITY", "LOD")


def _source(raw):
    path, data = common.read_file(raw)
    if not path.is_relative_to(runtime.ASSET_ROOT) or path.suffix.lower() not in (".glb", ".gltf"):
        raise ValueError("PROFILE_REQUIRES_PACKAGED_GLTF_ASSET")
    checked = runtime.inspect_asset(str(path))
    if checked.get("status") != "READY":
        raise ValueError("PROFILE_RUNTIME_ADMISSION_FAILED")
    observed = formats.inspect(data, path.suffix)
    dependency = deps.observe(path, data, observed, runtime.ASSET_ROOT)
    deps.fresh(dependency)
    document = deps.gltf_document(data, path.suffix)
    accessors, materials = document.get("accessors", []), document.get("materials", [])
    groups, triangles = [], 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            count = accessors[primitive.get("indices", primitive["attributes"]["POSITION"])]["count"]
            mode = primitive.get("mode", 4)
            if mode not in (4, 5, 6):
                raise ValueError("PROFILE_TRIANGLE_PRIMITIVES_REQUIRED")
            triangles += count // 3 if mode == 4 else max(0, count - 2)
            material = materials[primitive["material"]] if "material" in primitive else {}
            alpha = material.get("alphaMode", "OPAQUE")
            groups.append({"material": primitive.get("material"), "alpha_mode": alpha,
                           "double_sided": material.get("doubleSided", False),
                           "static_batch_candidate": not document.get("skins") and alpha in ("OPAQUE", "MASK"),
                           "constraints": ["Same material, spatial cell and visibility owner required; keep original fragment identities."] if alpha in ("OPAQUE", "MASK") else ["Order-sensitive transparency: retain separate draws."]})
    return {"path": str(path), "sha256": common.digest(data), "identity": dependency["identity"],
            "dependencies": dependency, "source_counts": {"triangles": triangles, "material_groups": len(groups),
                     "materials": len(materials), "joints": checked.get("skeleton", {}).get("joints", 0)},
            "material_policy": groups}


def plan(assets):
    if not isinstance(assets, list) or not 1 <= len(assets) <= 8:
        raise ValueError("PROFILE_SELECT_1_TO_8_ASSETS")
    rows = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise ValueError("PROFILE_ASSET_OBJECT_REQUIRED")
        full = _source(str(asset.get("path", "")))
        lod = _source(str(asset["lod_path"])) if asset.get("lod_path") else full
        rows.append({"id": "asset" + str(index), "full": full, "lod": lod, "has_lod": full["identity"] != lod["identity"]})
    value = {"schema": SCHEMA, "status": "READY", "summary": f"{len(rows)} admitted assets prepared for full / visibility / LOD measurement",
             "assets": rows, "stages": list(STAGES), "window": {"width": 800, "height": 600},
             "preservation_policy": "NO_FACE_CLEANUP_NO_MATERIAL_MERGE_NO_ANIMATION_CLOCK_RESET",
             "limits": ["Source material/triangle counts are not GPU draw calls. The Qt scene profiler records separate measured counters.",
                        "LOD is an explicitly selected existing model. A missing alternative is reported as unchanged; no new simplification is inferred.",
                        "This small controlled View3D scene does not establish production world performance or semantic equivalence of LOD rigs."]}
    packet = common.packet("scene-profile-plan", value)
    return {**value, "packet_path": str(packet)}


def load(raw):
    path, value, _ = common.read_json(raw)
    if not path.is_relative_to(common.ROOT.resolve()) or value.get("schema") != SCHEMA or value.get("stages") != list(STAGES):
        raise ValueError("INVALID_PROFILE_PLAN")
    if not isinstance(value.get("assets"), list) or not 1 <= len(value["assets"]) <= 8:
        raise ValueError("PROFILE_ASSET_LIMIT")
    for row in value["assets"]:
        for variant in ("full", "lod"):
            current = _source(row[variant]["path"])
            if current["identity"] != row[variant]["identity"]:
                raise ValueError("PROFILE_ASSET_CHANGED")
    return value


def record(raw, samples, screenshots=None):
    plan = load(raw)
    if not isinstance(samples, list) or not 9 <= len(samples) <= 720:
        raise ValueError("PROFILE_SAMPLE_LIMIT")
    if screenshots is not None:
        if not isinstance(screenshots, dict) or set(screenshots) != set(STAGES):
            raise ValueError("PROFILE_SCREENSHOT_SET_REQUIRED")
        for row in screenshots.values():
            path, data = common.read_file(row["path"], root=common.ROOT)
            if common.digest(data) != row["sha256"]:
                raise ValueError("PROFILE_SCREENSHOT_CHANGED")
    counters = ("frame_ms", "sync_cpu_ms", "render_cpu_ms", "gpu_window_ms", "draw_calls", "render_passes")
    stages = {}
    for stage in STAGES:
        rows = [row for row in samples if row.get("stage") == stage]
        if not 3 <= len(rows) <= 240:
            raise ValueError("PROFILE_STAGE_SAMPLE_LIMIT")
        expected = len(plan["assets"]) if stage != "VISIBILITY" else (len(plan["assets"]) + 1) // 2 if len(plan["assets"]) > 1 else 0
        if any(row.get("loaded_models") != len(plan["assets"]) or row.get("visible_models") != expected for row in rows):
            raise ValueError("PROFILE_SCENE_NOT_READY")
        stats = {}
        for counter in counters:
            values = [r.get(counter) for r in rows if r.get(counter) is not None]
            if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in values):
                raise ValueError("PROFILE_COUNTER_INVALID")
            stats[counter] = {"count": len(values), "median": statistics.median(values), "min": min(values), "max": max(values)} if values else {"count": 0, "state": "UNAVAILABLE"}
        stages[stage] = {"samples": len(rows), "visible_models": expected, "counters": stats}
    value = {"schema": SCHEMA, "status": "MEASURED", "summary": "Full, visibility and LOD stages measured in a controlled Qt scene",
             "plan": str(common.local_path(raw)), "coverage": "CONTROLLED_QT_VIEW3D_SAMPLE",
             "assets": plan["assets"], "stages": stages, "samples": samples, "screenshots": screenshots or {},
             "graphics_apis": sorted({str(r.get("graphics_api", "UNKNOWN")) for r in samples}),
             "limits": plan["limits"] + ["GPU window timing is reported only when Qt supplies it. Frame/CPU counters never substitute for missing GPU measurements."]}
    packet = common.packet("scene-profile-result", value)
    return {**value, "packet_path": str(packet)}


def measure(raw, samples=24):
    load(raw)
    samples = int(samples)
    if not 3 <= samples <= 120:
        raise ValueError("PROFILE_SAMPLE_LIMIT")
    project = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GG_GAME_WORKFLOWS_ROOT=str(common.ROOT))
    # Bound software-driver worker count; keep the real graphics API visible.
    env["LP_NUM_THREADS"] = "2"
    try:
        returncode, output, errors, trigger = run_bounded(
            [sys.executable, "-B", str(project / "tools/research/profile_game_asset_scene.py"),
             str(common.local_path(raw)), "--store", str(common.ROOT), "--samples", str(samples)],
            cwd=project, env=env, timeout=56, max_output_bytes=65536)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("QT_SCENE_MEASUREMENT_TIMEOUT") from exc
    if trigger == 'TIMEOUT':
        raise TimeoutError('QT_SCENE_MEASUREMENT_TIMEOUT')
    if trigger != 'NONE':
        raise ValueError('QT_SCENE_MEASUREMENT_' + trigger)
    if returncode:
        diagnostic = errors.decode('utf-8', 'replace').strip().splitlines()
        raise ValueError("QT_SCENE_MEASUREMENT_FAILED" + (":" + diagnostic[-1][:200] if diagnostic else ""))
    try:
        metadata = json.loads(output)
        path, value, _ = common.read_json(metadata["packet_path"])
    except (ValueError, KeyError) as exc:
        raise ValueError("INVALID_SCENE_MEASUREMENT_OUTPUT") from exc
    if not path.is_relative_to(common.ROOT.resolve()) or value.get("schema") != SCHEMA or value.get("status") != "MEASURED":
        raise ValueError("INVALID_SCENE_MEASUREMENT_OUTPUT")
    return {**value, "packet_path": str(path), "image": Path(value["screenshots"]["FULL"]["path"]).as_uri()}
