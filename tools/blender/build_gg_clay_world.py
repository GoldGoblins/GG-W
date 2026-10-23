"""Build original GG clay world props with Blender.

These meshes are style-inspired by readable PS2-era silhouettes
(Jak/Sly/Ratchet/Fable cottages and coastal trees).  Geometry is original.
No third-party mesh or texture is copied.

    blender --factory-startup --background \
      --python build_gg_clay_world.py -- \
      --out-dir ../../qml/assets/authored/world
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


STYLE_ID = "GG_CLAY_LOW_POLY"
SCHEMA = "gg.authored.world-kit.v1"


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    custom = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args(custom)


def set_input(node, name, value) -> None:
    socket = node.inputs.get(name)
    if socket is not None:
        socket.default_value = value


def material(name, color, *, metallic=0.0, roughness=0.52):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        set_input(principled, "Base Color", color)
        set_input(principled, "Roughness", roughness)
        set_input(principled, "Metallic", metallic)
        set_input(principled, "Specular IOR Level", 0.28)
    mat["gg_style"] = STYLE_ID
    return mat


def apply_transform(obj) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.select_set(False)


def finish(obj, mat):
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    apply_transform(obj)
    obj["gg_style"] = STYLE_ID
    return obj


def add_cube(name, location, scale, mat, *, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    apply_transform(obj)
    if bevel > 0.0:
        modifier = obj.modifiers.new(name="GG_Soft_Facet", type="BEVEL")
        modifier.width = bevel
        modifier.segments = 1
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.select_set(False)
    return finish(obj, mat)


def add_ico(name, location, scale, mat, *, subdivisions=1):
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=subdivisions, radius=1.0, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return finish(obj, mat)


def add_cylinder(name, location, scale, mat, *, vertices=8):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=1.0, depth=2.0, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return finish(obj, mat)


def add_cone(name, location, scale, mat, *, vertices=7):
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices, radius1=1.0, radius2=0.0, depth=2.0, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return finish(obj, mat)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def export_glb(path: Path, objects: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    options = {
        "filepath": str(path),
        "export_format": "GLB",
        "use_selection": True,
        "export_materials": "EXPORT",
        "export_yup": True,
        "export_apply": True,
        "export_extras": True,
        "export_skins": False,
        "export_animations": False,
    }
    bpy.ops.export_scene.gltf(**{key: value for key, value in options.items() if key in props})


def write_meta(path: Path, asset_id: str, kind: str, pieces: int) -> None:
    meta = path.with_suffix(".asset.json")
    meta.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "asset_id": asset_id,
                "kind": kind,
                "style_id": STYLE_ID,
                "source_policy": "ORIGINAL_GEOMETRY_REFERENCE_INSPIRED_NO_SOURCE_COPY",
                "mesh_objects": pieces,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_mangrove(mats) -> list:
    pieces = [
        add_cylinder("Mangrove_Trunk", (0.0, 0.0, 1.4), (0.18, 0.18, 1.4), mats["wood"], vertices=16),
        add_cube("Mangrove_Root.A", (-0.35, 0.28, 0.22), (0.08, 0.08, 0.45), mats["wood_light"], bevel=0.02),
        add_cube("Mangrove_Root.B", (0.32, 0.18, 0.18), (0.08, 0.08, 0.4), mats["wood_light"], bevel=0.02),
        add_cube("Mangrove_Root.C", (0.05, -0.38, 0.16), (0.08, 0.08, 0.36), mats["wood"], bevel=0.02),
        add_ico("Mangrove_Canopy.A", (0.0, 0.0, 3.15), (1.15, 1.05, 0.72), mats["leaf"], subdivisions=2),
        add_ico("Mangrove_Canopy.B", (-0.55, 0.35, 2.55), (0.7, 0.62, 0.5), mats["green"], subdivisions=2),
        add_ico("Mangrove_Canopy.C", (0.62, -0.22, 2.7), (0.78, 0.7, 0.52), mats["green_dark"], subdivisions=2),
        add_ico("Mangrove_Canopy.D", (0.1, 0.15, 3.7), (0.5, 0.48, 0.38), mats["leaf"], subdivisions=2),
    ]
    return pieces


def build_cottage(mats) -> list:
    pieces = [
        add_cube("Cottage_Body", (0.0, 0.0, 1.1), (1.15, 1.0, 1.1), mats["wood"], bevel=0.04),
        add_cone("Cottage_Roof", (0.0, 0.0, 2.55), (1.45, 1.25, 0.85), mats["coral"], vertices=4),
        add_cube("Cottage_Chimney", (0.55, -0.2, 2.85), (0.18, 0.18, 0.45), mats["wood_light"], bevel=0.02),
        add_cube("Cottage_Door", (0.0, -1.02, 0.7), (0.28, 0.06, 0.55), mats["gold"]),
        add_cube("Cottage_Window.L", (-0.45, -1.02, 1.35), (0.22, 0.05, 0.22), mats["glow"]),
        add_cube("Cottage_Window.R", (0.45, -1.02, 1.35), (0.22, 0.05, 0.22), mats["glow"]),
    ]
    return pieces


def build_lantern(mats) -> list:
    pieces = [
        add_cube("Lantern_Base", (0.0, 0.0, 0.08), (0.28, 0.28, 0.08), mats["wood_light"], bevel=0.02),
        add_cylinder("Lantern_Post", (0.0, 0.0, 1.15), (0.07, 0.07, 1.15), mats["wood"], vertices=14),
        add_cube("Lantern_Cage", (0.0, 0.0, 2.35), (0.22, 0.22, 0.22), mats["metal"], bevel=0.03),
        add_ico("Lantern_Flame", (0.0, 0.0, 2.35), (0.14, 0.14, 0.16), mats["gold"], subdivisions=2),
    ]
    return pieces


def build_materials():
    return {
        "wood": material("GG_World_Wood", (0.42, 0.22, 0.10, 1.0), roughness=0.94),
        "wood_light": material("GG_World_WoodLight", (0.66, 0.38, 0.16, 1.0), roughness=0.92),
        "leaf": material("GG_World_Leaf", (0.34, 0.72, 0.18, 1.0), roughness=0.9),
        "green": material("GG_World_Green", (0.22, 0.55, 0.16, 1.0), roughness=0.92),
        "green_dark": material("GG_World_GreenDark", (0.12, 0.38, 0.12, 1.0), roughness=0.93),
        "coral": material("GG_World_Roof", (0.82, 0.32, 0.22, 1.0), roughness=0.86),
        "gold": material("GG_World_Gold", (0.95, 0.72, 0.22, 1.0), metallic=0.18, roughness=0.55),
        "glow": material("GG_World_Glow", (0.55, 0.88, 0.95, 1.0), roughness=0.4),
        "metal": material("GG_World_Metal", (0.35, 0.42, 0.48, 1.0), metallic=0.22, roughness=0.7),
    }


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    jobs = (
        ("gg-clay-mangrove", "MANGROVE", build_mangrove),
        ("gg-clay-cottage", "HOUSE", build_cottage),
        ("gg-clay-lantern-post", "LIGHT", build_lantern),
    )
    for asset_id, kind, builder in jobs:
        clear_scene()
        mats = build_materials()
        pieces = builder(mats)
        out = args.out_dir / f"{asset_id}.glb"
        export_glb(out, pieces)
        write_meta(out, asset_id, kind, len(pieces))
        print(f"GG_BLENDER_WORLD_OK asset={asset_id} output={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
