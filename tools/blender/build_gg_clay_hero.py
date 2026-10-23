"""Build the first original GG clay/low-poly character with Blender.

This is deliberately a small authored-content generator rather than a runtime
fallback.  The output is a real glTF 2.0/GLB asset with:

* one armature and a bounded, readable bone vocabulary;
* separately authored low-poly mesh pieces, each skinned to one bone;
* four deterministic clips matching the GAME ENGINE motion contract;
* named attachment sockets carried as bone-parented empties;
* matte, textureless clay materials that keep the asset cheap on a low-end GPU.

Run through Blender's bundled Python, for example:

    blender --factory-startup --background \
      --python build_gg_clay_hero.py -- \
      --out ../../qml/assets/authored/gg-clay-hero-a.glb \
      --preview /tmp/gg-clay-hero-a.png

The script intentionally generates original geometry.  External games and
reference images are style references only; no third-party mesh or texture is
copied into the project.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


SCHEMA = "gg.authored.asset.v1"
STYLE_ID = "GG_CLAY_LOW_POLY"
BLENDER_COORDINATE_UP = "Z"
EXPECTED_CLIPS = ("Idle", "Walk", "Sprint", "Air")


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    custom = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output GLB path, normally inside qml/assets.",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Optional PNG turntable-style preview rendered before export.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Optional JSON manifest path. Defaults to <out>.asset.json.",
    )
    parser.add_argument(
        "--variant",
        default="hero-a",
        help="hero-a, fisher, guard or critter.",
    )
    return parser.parse_args(custom)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def point(x: float, vertical: float, depth: float) -> tuple[float, float, float]:
    """Convert the generator's gameplay coordinates to Blender XYZ.

    The model description stays readable as (x, height, depth), while Blender
    itself is (x, depth, height).  The glTF exporter later converts Blender Z
    up to glTF Y up for the Qt runtime.
    """
    return (float(x), float(depth), float(vertical))


def scale_xyz(x: float, vertical: float, depth: float) -> tuple[float, float, float]:
    return (float(x), float(depth), float(vertical))


def set_input(node: bpy.types.Node, name: str, value) -> None:
    socket = node.inputs.get(name)
    if socket is not None:
        socket.default_value = value


def material(name: str, color: tuple[float, float, float, float], *, metallic=0.0, roughness=0.56):
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


def build_materials() -> dict[str, bpy.types.Material]:
    return {
        "skin": material("GG_Skin_Clay", (0.78, 0.42, 0.18, 1.0), roughness=0.58),
        "skin_light": material("GG_Skin_Highlight", (0.92, 0.58, 0.28, 1.0), roughness=0.54),
        # Saturated gold-orange reads at 18 m the way Crash orange / Ratchet fur does.
        "goblin": material("GG_Goblin_Gold", (1.0, 0.55, 0.10, 1.0), roughness=0.46),
        "goblin_dark": material("GG_Goblin_Shade", (0.82, 0.32, 0.06, 1.0), roughness=0.54),
        "belly": material("GG_Goblin_Belly", (0.99, 0.90, 0.55, 1.0), roughness=0.50),
        "sclera": material("GG_Sclera", (1.0, 0.98, 0.92, 1.0), roughness=0.28),
        "pupil": material("GG_Pupil", (0.04, 0.18, 0.20, 1.0), roughness=0.22),
        "cloth": material("GG_Cloth_Teal", (0.10, 0.58, 0.62, 1.0), roughness=0.54),
        "cloth_light": material("GG_Cloth_Moss", (0.18, 0.68, 0.66, 1.0), roughness=0.52),
        "leather": material("GG_Leather", (0.22, 0.08, 0.03, 1.0), roughness=0.70),
        "straw": material("GG_Straw", (0.82, 0.62, 0.22, 1.0), roughness=0.68),
        "iron": material("GG_Iron", (0.38, 0.44, 0.50, 1.0), metallic=0.28, roughness=0.42),
        "ear": material("GG_Ear", (0.88, 0.50, 0.28, 1.0), roughness=0.58),
        "metal": material("GG_Metal_Dull", (0.42, 0.50, 0.52, 1.0), metallic=0.18, roughness=0.48),
        "gold": material("GG_Gold", (1.0, 0.74, 0.12, 1.0), metallic=0.34, roughness=0.36),
        "hair": material("GG_Hair_Clay", (0.10, 0.04, 0.02, 1.0), roughness=0.74),
        "brow": material("GG_Brow_Clay", (0.08, 0.03, 0.02, 1.0), roughness=0.70),
        "eye": material("GG_Eye", (0.06, 0.04, 0.03, 1.0), roughness=0.45),
        "eye_glint": material("GG_Eye_Glint", (0.9, 0.96, 0.88, 1.0), roughness=0.28),
    }


def apply_object_transform(obj: bpy.types.Object) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.select_set(False)


def bind_to_bone(obj: bpy.types.Object, armature: bpy.types.Object, bone_name: str) -> None:
    # Parenting is part of the glTF skin export contract.  The armature and
    # all mesh pieces are identity-transformed at this point, so an identity
    # parent inverse preserves their authored positions exactly.
    obj.parent = armature
    obj.matrix_parent_inverse = Matrix.Identity(4)
    group = obj.vertex_groups.new(name=bone_name)
    group.add([vertex.index for vertex in obj.data.vertices], 1.0, "REPLACE")
    modifier = obj.modifiers.new(name="GG_ArmatureDeform", type="ARMATURE")
    modifier.object = armature
    obj["gg_bone"] = bone_name
    obj["gg_style"] = STYLE_ID


def finish_mesh(obj: bpy.types.Object, mat, armature: bpy.types.Object, bone_name: str) -> bpy.types.Object:
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    apply_object_transform(obj)
    bind_to_bone(obj, armature, bone_name)
    return obj


def add_ico(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat,
    armature: bpy.types.Object,
    bone_name: str,
    *,
    subdivisions: int = 2,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=subdivisions,
        radius=1.0,
        location=point(*location),
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale_xyz(*scale)
    return finish_mesh(obj, mat, armature, bone_name)


def add_cube(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat,
    armature: bpy.types.Object,
    bone_name: str,
    *,
    bevel: float = 0.0,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=point(*location))
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale_xyz(*scale)
    apply_object_transform(obj)
    if bevel > 0.0:
        modifier = obj.modifiers.new(name="GG_Soft_Facet", type="BEVEL")
        modifier.width = bevel
        modifier.segments = 1
        modifier.limit_method = "ANGLE"
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.select_set(False)
    return finish_mesh(obj, mat, armature, bone_name)


def add_segment(
    name: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    radius_start: float,
    radius_end: float,
    mat,
    armature: bpy.types.Object,
    bone_name: str,
    *,
    vertices: int = 7,
) -> bpy.types.Object:
    start_vec = Vector(point(*start))
    end_vec = Vector(point(*end))
    direction = end_vec - start_vec
    length = direction.length
    if length <= 1e-5:
        raise ValueError(f"segment {name} has zero length")
    middle = (start_vec + end_vec) * 0.5
    rotation = Vector((0.0, 0.0, 1.0)).rotation_difference(direction.normalized())
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices,
        radius1=radius_start,
        radius2=radius_end,
        depth=length,
        location=middle,
        rotation=rotation.to_euler(),
    )
    obj = bpy.context.object
    obj.name = name
    return finish_mesh(obj, mat, armature, bone_name)


TALL_HERO_BONES = {
    "root": ((0.0, 0.0, 0.0), (0.0, 0.16, 0.0), None),
    "hips": ((0.0, 0.16, 0.0), (0.0, 0.78, 0.0), "root"),
    "spine": ((0.0, 0.67, 0.0), (0.0, 1.08, 0.0), "hips"),
    "chest": ((0.0, 1.00, 0.0), (0.0, 1.35, 0.0), "spine"),
    "neck": ((0.0, 1.31, 0.0), (0.0, 1.49, 0.0), "chest"),
    "head": ((0.0, 1.43, 0.0), (0.0, 1.72, 0.0), "neck"),
    "upper_arm.L": ((0.28, 1.25, 0.0), (0.49, 0.98, 0.0), "chest"),
    "forearm.L": ((0.49, 0.98, 0.0), (0.56, 0.68, -0.015), "upper_arm.L"),
    "hand.L": ((0.56, 0.68, -0.015), (0.56, 0.54, -0.08), "forearm.L"),
    "upper_arm.R": ((-0.28, 1.25, 0.0), (-0.49, 0.98, 0.0), "chest"),
    "forearm.R": ((-0.49, 0.98, 0.0), (-0.56, 0.68, -0.015), "upper_arm.R"),
    "hand.R": ((-0.56, 0.68, -0.015), (-0.56, 0.54, -0.08), "forearm.R"),
    "thigh.L": ((0.15, 0.75, 0.0), (0.18, 0.42, 0.0), "hips"),
    "calf.L": ((0.18, 0.42, 0.0), (0.16, 0.10, -0.01), "thigh.L"),
    "foot.L": ((0.16, 0.10, -0.01), (0.16, 0.05, -0.23), "calf.L"),
    "thigh.R": ((-0.15, 0.75, 0.0), (-0.18, 0.42, 0.0), "hips"),
    "calf.R": ((-0.18, 0.42, 0.0), (-0.16, 0.10, -0.01), "thigh.R"),
    "foot.R": ((-0.16, 0.10, -0.01), (-0.16, 0.05, -0.23), "calf.R"),
}

# Compact 3.5-heads goblin.  Bone pivots must sit inside the mesh pieces or
# Walk/Sprint orbits the arms around empty air above the shoulders.
COMPACT_GOBLIN_BONES = {
    "root": ((0.0, 0.0, 0.0), (0.0, 0.12, 0.0), None),
    "hips": ((0.0, 0.12, 0.0), (0.0, 0.50, 0.0), "root"),
    "spine": ((0.0, 0.44, 0.0), (0.0, 0.72, 0.0), "hips"),
    "chest": ((0.0, 0.68, 0.0), (0.0, 0.92, 0.0), "spine"),
    "neck": ((0.0, 0.90, 0.0), (0.0, 1.02, 0.0), "chest"),
    "head": ((0.0, 1.00, 0.0), (0.0, 1.38, 0.0), "neck"),
    "upper_arm.L": ((0.24, 0.88, 0.0), (0.38, 0.62, 0.02), "chest"),
    "forearm.L": ((0.38, 0.62, 0.02), (0.46, 0.40, -0.02), "upper_arm.L"),
    "hand.L": ((0.46, 0.40, -0.02), (0.48, 0.28, -0.08), "forearm.L"),
    "upper_arm.R": ((-0.24, 0.88, 0.0), (-0.38, 0.62, 0.02), "chest"),
    "forearm.R": ((-0.38, 0.62, 0.02), (-0.46, 0.40, -0.02), "upper_arm.R"),
    "hand.R": ((-0.46, 0.40, -0.02), (-0.48, 0.28, -0.08), "forearm.R"),
    "thigh.L": ((0.12, 0.46, 0.0), (0.14, 0.26, 0.02), "hips"),
    "calf.L": ((0.14, 0.26, 0.02), (0.13, 0.10, 0.0), "thigh.L"),
    "foot.L": ((0.13, 0.10, 0.0), (0.14, 0.04, -0.26), "calf.L"),
    "thigh.R": ((-0.12, 0.46, 0.0), (-0.14, 0.26, 0.02), "hips"),
    "calf.R": ((-0.14, 0.26, 0.02), (-0.13, 0.10, 0.0), "thigh.R"),
    "foot.R": ((-0.13, 0.10, 0.0), (-0.14, 0.04, -0.26), "calf.R"),
}


def build_armature(variant: str = "hero-a") -> bpy.types.Object:
    data = bpy.data.armatures.new("GG_Clay_Hero_Armature")
    armature = bpy.data.objects.new("GG_Clay_Hero_Armature", data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    wanted = str(variant or "hero-a").strip().lower()
    definitions = (
        COMPACT_GOBLIN_BONES
        if wanted in {"hero-a", "hero", "goblin"}
        else TALL_HERO_BONES
    )
    for name, (head, tail, parent_name) in definitions.items():
        bone = data.edit_bones.new(name)
        bone.head = point(*head)
        bone.tail = point(*tail)
        if parent_name:
            bone.parent = data.edit_bones[parent_name]
            bone.use_connect = False

    bpy.ops.object.mode_set(mode="POSE")
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    armature["gg_schema"] = SCHEMA
    armature["gg_style_id"] = STYLE_ID
    armature["gg_coordinate_up"] = BLENDER_COORDINATE_UP
    armature["gg_asset_variant"] = "hero-a"
    armature["gg_root_anchor"] = "feet_at_y_0"
    armature["gg_sockets"] = "HEAD,CHEST,MAIN_HAND,OFF_HAND,BACK,FEET"
    return armature


def add_socket(armature: bpy.types.Object, name: str, bone_name: str, location: tuple[float, float, float]) -> None:
    socket = bpy.data.objects.new(f"SOCKET_{name}", None)
    socket.empty_display_type = "PLAIN_AXES"
    socket.empty_display_size = 0.06
    socket.parent = armature
    socket.parent_type = "BONE"
    socket.parent_bone = bone_name
    socket.location = point(*location)
    socket.hide_render = True
    # Keep the node exportable.  It is non-rendering and can be hidden by the
    # game-side attachment system, but hiding it in Blender would make the
    # glTF exporter omit the socket node entirely.
    socket.hide_viewport = False
    socket["gg_socket"] = name
    socket["gg_style"] = STYLE_ID
    armature.users_collection[0].objects.link(socket)


def build_icon_goblin(
    armature: bpy.types.Object,
    mats: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    """Gold Goblin hero: Crash/Jak/Ratchet silhouette rules, original forms.

    About 3.5 heads tall, no neck, ears as long as the head, Crash-scale
    eyes with brows, cream belly vs dark back mark, teal tunic, bare gold
    calves, oversized gold-striped boots.  Thirty-two pieces: brows instead
    of separate shoulders so the face still reads at gameplay camera distance.
    """
    pieces: list[bpy.types.Object] = []
    pieces.append(add_ico("Goblin_Torso", (0.0, 0.72, 0.0), (0.34, 0.24, 0.30), mats["cloth"], armature, "chest", subdivisions=2))
    pieces.append(add_ico("Goblin_Hips", (0.0, 0.46, 0.0), (0.28, 0.14, 0.20), mats["cloth"], armature, "hips", subdivisions=1))
    pieces.append(add_torus("Goblin_Belt", (0.0, 0.54, 0.0), (0.30, 0.04, 0.22), mats["gold"], armature, "hips"))
    pieces.append(add_ico("Goblin_Belly", (0.0, 0.66, -0.22), (0.18, 0.16, 0.14), mats["belly"], armature, "chest", subdivisions=1))
    pieces.append(add_ico("Goblin_BackMark", (0.0, 0.80, 0.22), (0.14, 0.10, 0.10), mats["goblin_dark"], armature, "chest", subdivisions=1))
    pieces.append(add_ico("Goblin_Head", (0.0, 1.22, 0.02), (0.44, 0.36, 0.40), mats["goblin"], armature, "head", subdivisions=2))
    pieces.append(add_ico("Goblin_Tail", (0.0, 0.42, 0.28), (0.08, 0.10, 0.22), mats["goblin"], armature, "hips", subdivisions=1))
    pieces.append(add_segment("Goblin_Ear.L", (0.32, 1.22, 0.04), (0.62, 1.72, 0.10), 0.10, 0.02, mats["goblin"], armature, "head", vertices=7))
    pieces.append(add_segment("Goblin_Ear.R", (-0.32, 1.22, 0.04), (-0.62, 1.72, 0.10), 0.10, 0.02, mats["goblin"], armature, "head", vertices=7))
    pieces.append(add_torus("Goblin_Hoop", (-0.52, 1.34, 0.08), (0.07, 0.014, 0.07), mats["gold"], armature, "head"))
    pieces.append(add_ico("Goblin_Sclera.L", (0.16, 1.24, -0.36), (0.18, 0.16, 0.09), mats["sclera"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Goblin_Sclera.R", (-0.16, 1.24, -0.36), (0.18, 0.16, 0.09), mats["sclera"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Goblin_Pupil.L", (0.16, 1.23, -0.44), (0.09, 0.10, 0.05), mats["pupil"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Goblin_Pupil.R", (-0.16, 1.23, -0.44), (0.09, 0.10, 0.05), mats["pupil"], armature, "head", subdivisions=1))
    pieces.append(add_cube("Goblin_Brow.L", (0.16, 1.40, -0.34), (0.16, 0.045, 0.05), mats["brow"], armature, "head", bevel=0.012))
    pieces.append(add_cube("Goblin_Brow.R", (-0.16, 1.40, -0.34), (0.16, 0.045, 0.05), mats["brow"], armature, "head", bevel=0.012))
    pieces.append(add_ico("Goblin_Nose", (0.0, 1.10, -0.40), (0.09, 0.07, 0.09), mats["goblin_dark"], armature, "head", subdivisions=1))
    pieces.append(add_cube("Goblin_Grin", (0.0, 1.00, -0.38), (0.22, 0.04, 0.05), mats["hair"], armature, "head", bevel=0.014))
    for side, sign in (("L", 1.0), ("R", -1.0)):
        shoulder = (0.24 * sign, 0.88, 0.0)
        elbow = (0.38 * sign, 0.62, 0.02)
        wrist = (0.46 * sign, 0.40, -0.02)
        hand = (0.48 * sign, 0.34, -0.04)
        thigh = (0.12 * sign, 0.46, 0.0)
        knee = (0.14 * sign, 0.26, 0.02)
        ankle = (0.13 * sign, 0.10, 0.0)
        pieces.append(add_segment(f"Goblin_UpperArm.{side}", shoulder, elbow, 0.12, 0.09, mats["goblin"], armature, f"upper_arm.{side}"))
        pieces.append(add_segment(f"Goblin_Forearm.{side}", elbow, wrist, 0.09, 0.08, mats["goblin"], armature, f"forearm.{side}"))
        pieces.append(add_ico(f"Goblin_Hand.{side}", hand, (0.15, 0.13, 0.16), mats["belly"], armature, f"hand.{side}", subdivisions=1))
        pieces.append(add_segment(f"Goblin_Thigh.{side}", thigh, knee, 0.12, 0.10, mats["cloth"], armature, f"thigh.{side}"))
        pieces.append(add_segment(f"Goblin_Calf.{side}", knee, ankle, 0.09, 0.08, mats["goblin"], armature, f"calf.{side}"))
        pieces.append(add_cube(f"Goblin_Boot.{side}", (0.14 * sign, 0.10, -0.12), (0.18, 0.18, 0.28), mats["gold"], armature, f"foot.{side}", bevel=0.02))
        pieces.append(add_ico(f"Goblin_BootToe.{side}", (0.14 * sign, 0.08, -0.28), (0.13, 0.10, 0.14), mats["leather"], armature, f"foot.{side}", subdivisions=1))
    return pieces


def build_character(
    armature: bpy.types.Object,
    mats: dict[str, bpy.types.Material],
    variant: str = "hero-a",
) -> list[bpy.types.Object]:
    pieces: list[bpy.types.Object] = []
    wanted = str(variant or "hero-a").strip().lower()
    if wanted in {"hero-a", "hero", "goblin"}:
        return build_icon_goblin(armature, mats)

    # Silhouette: broad chest, compact hips, readable hands/feet and an
    # oversized head.  Variants swap hat/helm/ears inside the 32-mesh budget.
    torso_mat = mats["cloth"]
    if wanted == "fisher":
        torso_mat = mats["straw"]
    elif wanted == "guard":
        torso_mat = mats["iron"]
    elif wanted == "critter":
        torso_mat = mats["cloth_light"]
    pieces.append(add_ico("Hero_Torso", (0.0, 0.96, 0.0), (0.34, 0.235, 0.43), torso_mat, armature, "chest", subdivisions=2))
    pieces.append(add_ico("Hero_BeltBody", (0.0, 0.68, 0.0), (0.30, 0.22, 0.20), mats["leather"], armature, "hips", subdivisions=1))
    pieces.append(add_segment("Hero_TunicSkirt", (-0.0, 0.58, 0.0), (0.0, 0.86, 0.0), 0.34, 0.28, mats["cloth_light"], armature, "hips", vertices=8))
    pieces.append(add_torus("Hero_Belt", (0.0, 0.76, 0.0), (0.31, 0.035, 0.23), mats["gold"], armature, "hips"))
    if wanted == "fisher":
        pieces.append(add_ico("Fisher_Basket", (0.0, 0.20, 0.16), (0.22, 0.16, 0.18), mats["straw"], armature, "chest", subdivisions=1))
    elif wanted == "guard":
        pieces.append(add_ico("Guard_Plate", (0.0, 0.22, -0.02), (0.28, 0.08, 0.32), mats["iron"], armature, "chest", subdivisions=1))
    elif wanted == "critter":
        pieces.append(add_ico("Critter_Tail", (0.0, 0.12, 0.28), (0.08, 0.22, 0.10), mats["ear"], armature, "hips", subdivisions=1))
    else:
        pieces.append(add_ico("Hero_Backpack", (0.0, 0.18, 0.0), (0.24, 0.105, 0.30), mats["leather"], armature, "chest", subdivisions=1))

    pieces.append(add_segment("Hero_Neck", (0.0, 1.35, 0.0), (0.0, 1.49, 0.0), 0.115, 0.10, mats["skin"], armature, "neck", vertices=7))
    head_scale = (0.22, 0.20, 0.24) if wanted == "critter" else (0.255, 0.235, 0.285)
    pieces.append(add_ico("Hero_Head", (0.0, 1.60, 0.0), head_scale, mats["skin"], armature, "head", subdivisions=2))
    if wanted == "fisher":
        pieces.append(add_ico("Fisher_HatBrim", (0.0, 1.78, 0.0), (0.42, 0.42, 0.07), mats["straw"], armature, "head", subdivisions=1))
        pieces.append(add_ico("Fisher_HatCrown", (0.0, 1.90, 0.0), (0.18, 0.18, 0.12), mats["straw"], armature, "head", subdivisions=1))
        pieces.append(add_ico("Fisher_HatBand", (0.0, 1.82, 0.0), (0.20, 0.20, 0.04), mats["cloth"], armature, "head", subdivisions=1))
    elif wanted == "guard":
        pieces.append(add_ico("Guard_Helm", (0.0, 1.78, 0.02), (0.28, 0.24, 0.18), mats["iron"], armature, "head", subdivisions=1))
        pieces.append(add_cube("Guard_Crest", (0.0, 1.96, 0.0), (0.04, 0.04, 0.16), mats["gold"], armature, "head", bevel=0.01))
        pieces.append(add_ico("Guard_Visor", (0.0, 1.64, -0.20), (0.18, 0.06, 0.05), mats["iron"], armature, "head", subdivisions=1))
    elif wanted == "critter":
        pieces.append(add_ico("Critter_Tuft", (0.0, 1.82, 0.02), (0.16, 0.16, 0.12), mats["hair"], armature, "head", subdivisions=1))
        pieces.append(add_ico("Critter_Ear.L", (0.22, 1.78, 0.04), (0.07, 0.16, 0.12), mats["ear"], armature, "head", subdivisions=1))
        pieces.append(add_ico("Critter_Ear.R", (-0.22, 1.78, 0.04), (0.07, 0.16, 0.12), mats["ear"], armature, "head", subdivisions=1))
    else:
        pieces.append(add_ico("Hero_HairCap", (0.0, 1.77, 0.015), (0.265, 0.225, 0.145), mats["hair"], armature, "head", subdivisions=1))
        pieces.append(add_ico("Hero_HairSide.L", (0.225, 1.66, 0.01), (0.075, 0.17, 0.15), mats["hair"], armature, "head", subdivisions=1))
        pieces.append(add_ico("Hero_HairSide.R", (-0.225, 1.66, 0.01), (0.075, 0.17, 0.15), mats["hair"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Hero_Eye.L", (0.092, 1.66, -0.218), (0.043, 0.035, 0.043), mats["eye"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Hero_Eye.R", (-0.092, 1.66, -0.218), (0.043, 0.035, 0.043), mats["eye"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Hero_EyeGlint.L", (0.101, 1.675, -0.248), (0.012, 0.008, 0.012), mats["eye_glint"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Hero_EyeGlint.R", (-0.083, 1.675, -0.248), (0.012, 0.008, 0.012), mats["eye_glint"], armature, "head", subdivisions=1))
    pieces.append(add_ico("Hero_Nose", (0.0, 1.575, -0.25), (0.045, 0.055, 0.055), mats["skin_light"], armature, "head", subdivisions=1))
    pieces.append(add_cube("Hero_Mouth", (0.0, 1.515, -0.236), (0.085, 0.018, 0.018), mats["hair"], armature, "head", bevel=0.012))

    for side, sign in (("L", 1.0), ("R", -1.0)):
        shoulder = (0.32 * sign, 1.24, 0.0)
        elbow = (0.49 * sign, 0.98, 0.0)
        wrist = (0.56 * sign, 0.68, -0.015)
        hand = (0.56 * sign, 0.62, -0.02)
        thigh = (0.15 * sign, 0.75, 0.0)
        knee = (0.18 * sign, 0.42, 0.0)
        ankle = (0.16 * sign, 0.10, -0.01)
        foot = (0.16 * sign, 0.05, -0.23)
        pieces.append(add_ico(f"Hero_Shoulder.{side}", shoulder, (0.14, 0.14, 0.14), mats["cloth_light"], armature, f"upper_arm.{side}", subdivisions=1))
        pieces.append(add_segment(f"Hero_UpperArm.{side}", shoulder, elbow, 0.105, 0.085, mats["cloth"], armature, f"upper_arm.{side}"))
        pieces.append(add_segment(f"Hero_Forearm.{side}", elbow, wrist, 0.085, 0.068, mats["skin"], armature, f"forearm.{side}"))
        pieces.append(add_ico(f"Hero_Hand.{side}", hand, (0.09, 0.075, 0.10), mats["skin"], armature, f"hand.{side}", subdivisions=1))
        pieces.append(add_segment(f"Hero_Thigh.{side}", thigh, knee, 0.13, 0.105, mats["cloth"], armature, f"thigh.{side}"))
        pieces.append(add_segment(f"Hero_Calf.{side}", knee, ankle, 0.105, 0.075, mats["skin"], armature, f"calf.{side}"))
        pieces.append(add_ico(f"Hero_Boot.{side}", foot, (0.13, 0.22, 0.09), mats["leather"], armature, f"foot.{side}", subdivisions=1))
        pieces.append(add_cube(f"Hero_BootTrim.{side}", (0.16 * sign, 0.105, -0.095), (0.13, 0.05, 0.035), mats["gold"], armature, f"foot.{side}", bevel=0.015))

    # Keep the authored hero inside the current 32-mesh admission budget.
    # The chest badge belongs in the next merged-material pass, not as a
    # thirty-third runtime primitive.
    return pieces


def add_torus(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat,
    armature: bpy.types.Object,
    bone_name: str,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_torus_add(
        major_segments=10,
        minor_segments=4,
        major_radius=1.0,
        minor_radius=0.12,
        location=point(*location),
    )
    obj = bpy.context.object
    obj.name = name
    # A belt is a horizontal ring: x radius, depth radius, vertical tube.
    obj.scale = scale_xyz(*scale)
    return finish_mesh(obj, mat, armature, bone_name)


def pose_values(action_name: str, frame: int, frame_count: int) -> dict[str, tuple[float, float, float]]:
    phase = (frame - 1) / float(max(1, frame_count - 1)) * math.tau
    sine = math.sin(phase)
    cosine = math.cos(phase)
    values: dict[str, tuple[float, float, float]] = {}
    if action_name == "Idle":
        values.update(
            {
                "chest": (0.028 * sine, 0.0, 0.0),
                "head": (-0.045 * sine, 0.0, 0.03 * sine),
                "upper_arm.L": (0.05 * sine, 0.0, -0.03),
                "upper_arm.R": (-0.05 * sine, 0.0, 0.03),
            }
        )
    elif action_name in {"Walk", "Sprint"}:
        strength = 0.42 if action_name == "Walk" else 0.72
        arm_strength = 0.28 if action_name == "Walk" else 0.46
        values.update(
            {
                "thigh.L": (strength * sine, 0.0, 0.0),
                "thigh.R": (-strength * sine, 0.0, 0.0),
                "calf.L": (-max(0.0, strength * sine) * 0.34, 0.0, 0.0),
                "calf.R": (-max(0.0, -strength * sine) * 0.34, 0.0, 0.0),
                "upper_arm.L": (-arm_strength * sine, 0.0, -0.02),
                "upper_arm.R": (arm_strength * sine, 0.0, 0.02),
                "forearm.L": (0.16 * max(0.0, -sine), 0.0, 0.0),
                "forearm.R": (0.16 * max(0.0, sine), 0.0, 0.0),
                "chest": (0.03 * sine, 0.0, 0.025 * cosine),
                "head": (-0.02 * sine, 0.0, -0.015 * cosine),
            }
        )
    elif action_name == "Air":
        values.update(
            {
                "thigh.L": (-0.52, 0.0, 0.0),
                "thigh.R": (-0.52, 0.0, 0.0),
                "calf.L": (0.72, 0.0, 0.0),
                "calf.R": (0.72, 0.0, 0.0),
                "upper_arm.L": (-0.55, 0.0, -0.18),
                "upper_arm.R": (-0.55, 0.0, 0.18),
                "forearm.L": (-0.35, 0.0, 0.0),
                "forearm.R": (-0.35, 0.0, 0.0),
                "chest": (-0.12, 0.0, 0.0),
                "head": (0.08, 0.0, 0.0),
            }
        )
    return values


def build_actions(armature: bpy.types.Object) -> dict[str, float]:
    durations: dict[str, float] = {}
    frame_counts = {"Idle": 36, "Walk": 24, "Sprint": 18, "Air": 18}
    for action_name, frame_count in frame_counts.items():
        # The public clip names are part of the GAME ENGINE contract.  The
        # asset may carry GG metadata elsewhere, but RuntimeLoader must see
        # exactly Idle/Walk/Sprint/Air.
        action = bpy.data.actions.new(action_name)
        action.use_fake_user = True
        action["gg_clip_name"] = action_name
        action["gg_motion_contract"] = "IDLE/WALK/SPRINT/AIR"
        armature.animation_data_create()
        armature.animation_data.action = action
        for frame in (1, max(1, frame_count // 2), frame_count):
            values = pose_values(action_name, frame, frame_count)
            for pose_bone in armature.pose.bones:
                pose_bone.rotation_mode = "XYZ"
                pose_bone.rotation_euler = values.get(pose_bone.name, (0.0, 0.0, 0.0))
                pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=pose_bone.name)
        action.frame_range = (1.0, float(frame_count))
        durations[action_name] = round((frame_count - 1) / 24.0, 3)
    armature.animation_data.action = bpy.data.actions.get("Idle")
    return durations


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_preview_scene(armature: bpy.types.Object, pieces: list[bpy.types.Object], output: Path) -> None:
    scene = bpy.context.scene
    # Blender 5.2 exposes the real-time engine as BLENDER_EEVEE; some older
    # 4.x builds called the same engine BLENDER_EEVEE_NEXT.
    available_engines = {item.identifier for item in scene.bl_rna.properties["render"].fixed_type.properties["engine"].enum_items}
    scene.render.engine = (
        "BLENDER_EEVEE"
        if "BLENDER_EEVEE" in available_engines
        else "BLENDER_EEVEE_NEXT"
    )
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(output)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("GG_Preview_World")
    scene.world.color = (0.42, 0.62, 0.78)
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background is not None:
        set_input(background, "Color", (0.42, 0.62, 0.78, 1.0))
        set_input(background, "Strength", 1.15)
    scene.render.image_settings.color_mode = "RGBA"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except (TypeError, ValueError):
        pass

    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, -0.015))
    ground = bpy.context.object
    ground.name = "GG_PREVIEW_GROUND"
    ground.data.materials.append(material("GG_Preview_Ground", (0.28, 0.46, 0.14, 1.0), roughness=0.92))

    bpy.ops.object.camera_add(location=(1.7, -2.9, 1.15))
    camera = bpy.context.object
    camera.name = "GG_PREVIEW_CAMERA"
    camera.data.lens = 50
    look_at(camera, (0.0, 0.0, 0.72))
    scene.camera = camera

    for name, location, energy, size, color in (
        ("GG_Key", (2.0, -2.4, 3.4), 1100.0, 2.6, (1.0, 0.86, 0.62)),
        ("GG_Fill", (-2.6, -1.2, 1.8), 640.0, 2.4, (0.55, 0.72, 1.0)),
        ("GG_Rim", (0.2, 2.4, 2.8), 820.0, 1.8, (0.70, 0.92, 0.78)),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.data.color = color
        look_at(light, (0.0, 0.0, 0.9))

    scene.frame_set(1)
    ensure_parent(output)
    bpy.ops.render.render(write_still=True)

    for obj in list(bpy.data.objects):
        if obj.name.startswith("GG_PREVIEW_") or obj.name.startswith("GG_Key") or obj.name.startswith("GG_Fill") or obj.name.startswith("GG_Rim"):
            bpy.data.objects.remove(obj, do_unlink=True)


def export_glb(armature: bpy.types.Object, pieces: list[bpy.types.Object], sockets: list[bpy.types.Object], output: Path) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in pieces + sockets:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature

    props = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
    # The canonical build is a self-contained GLB.  A few already-running
    # desktop hosts can still hold the historical ``gg-authored-hero.gltf``
    # URI in their in-memory asset catalog, so the same generator also emits
    # a separate JSON glTF plus a sibling .bin when the compatibility alias
    # is requested.  Both files contain the same authored model; this is not
    # a second gameplay model or a fallback body.
    export_format = "GLTF_SEPARATE" if output.suffix.lower() == ".gltf" else "GLB"
    options = {
        "filepath": str(output),
        "check_existing": False,
        "export_format": export_format,
        "use_selection": True,
        "export_animations": True,
        "export_animation_mode": "ACTIONS",
        "export_frame_range": True,
        "export_force_sampling": True,
        "export_skins": True,
        "export_materials": "EXPORT",
        "export_vertex_color": "MATERIAL",
        "export_extras": True,
        "export_yup": True,
        "export_apply": True,
        "export_all_influences": False,
        "export_nla_strips": False,
    }
    bpy.ops.export_scene.gltf(**{key: value for key, value in options.items() if key in props})


def write_metadata(output: Path, variant: str, durations: dict[str, float], pieces: list[bpy.types.Object]) -> None:
    metadata_path = output.with_suffix(".asset.json")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": SCHEMA,
        "asset_id": f"gg-clay-{variant}",
        "variant": variant,
        "style_id": STYLE_ID,
        "source_policy": "ORIGINAL_GEOMETRY_REFERENCE_INSPIRED_NO_SOURCE_COPY",
        "coordinate_up": BLENDER_COORDINATE_UP,
        "root_anchor": "feet_at_y_0",
        "sockets": ["HEAD", "CHEST", "MAIN_HAND", "OFF_HAND", "BACK", "FEET"],
        "clips": [
            {"name": name, "duration_s": duration}
            for name, duration in durations.items()
        ],
        "mesh_objects": len(pieces),
        "triangle_budget_target": 2600,
        "crowd_lod_policy": "LOD0_HERO_LOD1_NPC_LOD2_CROWD",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    ensure_parent(args.out)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    mats = build_materials()
    armature = build_armature(args.variant)
    pieces = build_character(armature, mats, args.variant)

    add_socket(armature, "HEAD", "head", (0.0, 0.0, 0.26))
    add_socket(armature, "CHEST", "chest", (0.0, -0.20, 0.05))
    add_socket(armature, "MAIN_HAND", "hand.R", (0.0, -0.04, -0.08))
    add_socket(armature, "OFF_HAND", "hand.L", (0.0, -0.04, -0.08))
    add_socket(armature, "BACK", "chest", (0.0, 0.18, 0.0))
    add_socket(armature, "FEET", "root", (0.0, 0.0, 0.0))
    sockets = [obj for obj in bpy.data.objects if obj.name.startswith("SOCKET_")]

    durations = build_actions(armature)
    if args.preview:
        setup_preview_scene(armature, pieces, args.preview)
    export_glb(armature, pieces, sockets, args.out)
    write_metadata(args.out, args.variant, durations, pieces)

    print(f"GG_BLENDER_ASSET_OK output={args.out}")
    print(f"GG_BLENDER_ASSET_CLIPS clips={','.join(EXPECTED_CLIPS)}")
    print(f"GG_BLENDER_ASSET_PIECES mesh_objects={len(pieces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
