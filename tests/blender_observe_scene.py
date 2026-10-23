"""Headless proof that inspect, clean, deform_rig and turnaround work in Blender.

Run with:
    blender --background --factory-startup --python tests/blender_observe_scene.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "blender"))

from gg_blender_observe import apply_deform_rig, clean_mesh, inspect_scene, render_turnaround  # noqa: E402
from gg_deform_rig import anatomy_names  # noqa: E402


def fail(message: str) -> None:
    print("OBSERVE_SELFTEST_FAIL " + message)
    raise SystemExit(1)


def make_hole() -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.5))
    obj = bpy.context.active_object
    obj.name = "HoleCube"
    mesh_bmesh = bmesh.new()
    mesh_bmesh.from_mesh(obj.data)
    mesh_bmesh.faces.ensure_lookup_table()
    bmesh.ops.delete(mesh_bmesh, geom=[mesh_bmesh.faces[0]], context="FACES")
    mesh_bmesh.to_mesh(obj.data)
    mesh_bmesh.free()
    obj.data.update()
    return obj


def main() -> None:
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    make_hole()
    before = inspect_scene("HoleCube")
    if not before.get("ok") or before.get("closed") or before.get("hole_loops", 0) < 1:
        fail("open cube was not reported as a hole: " + str(before))
    dry = clean_mesh("HoleCube", "fill", apply=False)
    if not dry.get("dry_run") or not dry.get("ok"):
        fail("clean dry-run did not refuse the edit")
    still = inspect_scene("HoleCube")
    if still.get("closed"):
        fail("dry-run edited the mesh")
    filled = clean_mesh("HoleCube", "fill", apply=True)
    if not filled.get("ok") or not filled.get("after", {}).get("closed"):
        fail("fill did not close the hole: " + str(filled))
    rig = apply_deform_rig("HoleCube", replace=False)
    if not rig.get("ok") or rig.get("joints") != 90:
        fail("deform rig: " + str(rig))
    again = apply_deform_rig("HoleCube", replace=False)
    if again.get("error") != "BLENDER_DEFORM_EXISTS":
        fail("second rig should refuse, got " + str(again))
    report = inspect_scene("HoleCube")
    armatures = report.get("armatures") or []
    if len(armatures) != 1 or armatures[0].get("bones") != 90 or not armatures[0].get("matches_anatomy"):
        fail("anatomy report: " + str(armatures))
    if set(bone.name for bone in bpy.data.objects["GG_Deform"].data.bones) != anatomy_names():
        fail("bone names drifted from the deform spec")
    folder = Path(tempfile.mkdtemp(prefix="gg-observe-"))
    views = render_turnaround(str(folder), size=256, name="HoleCube")
    if not views.get("ok"):
        fail("turnaround: " + str(views))
    for view in ("front", "side", "back", "three_quarter"):
        path = Path(views["views"][view]["path"])
        if not path.is_file() or path.stat().st_size < 800:
            fail("view missing or empty: " + view)
    print("OBSERVE_SELFTEST=PASS")
    print("TURNAROUND=" + str(folder))


if __name__ == "__main__":
    main()
