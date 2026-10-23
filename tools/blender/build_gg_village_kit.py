"""Build the live EXT village kit: stilt hut + pier.

Run inside the visible Blender GUI (sidecar exec), never a second process.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Vector


KEEP_TYPES = {"CAMERA", "LIGHT"}
WOOD = (0.42, 0.22, 0.10, 1.0)
WOOD_LIGHT = (0.66, 0.38, 0.16, 1.0)
WOOD_DARK = (0.28, 0.14, 0.07, 1.0)
THATCH = (0.82, 0.38, 0.16, 1.0)
THATCH_DARK = (0.55, 0.24, 0.10, 1.0)
PLASTER = (0.92, 0.78, 0.55, 1.0)
DOOR = (0.18, 0.08, 0.04, 1.0)
GLOW = (1.0, 0.82, 0.35, 1.0)
GOLD = (0.86, 0.58, 0.18, 1.0)
TRUNK = (0.46, 0.28, 0.12, 1.0)
LEAF = (0.18, 0.46, 0.16, 1.0)
LEAF_DARK = (0.10, 0.32, 0.10, 1.0)
LEAF_LIGHT = (0.28, 0.58, 0.20, 1.0)
HULL = (0.34, 0.18, 0.08, 1.0)
STRAW = (0.78, 0.52, 0.22, 1.0)


def _mat(name: str, color: tuple[float, float, float, float], emit: float = 0.0):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.86
        if emit and "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = emit
    return material


def _add_mesh(name: str, verts, faces, material):
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(list(verts), [], list(faces))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def _box(name, cx, cy, cz, hx, hy, hz, material):
    verts = [
        (cx - hx, cy - hy, cz - hz),
        (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz),
        (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz),
        (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz),
        (cx - hx, cy + hy, cz + hz),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (0, 3, 7, 4),
    ]
    return _add_mesh(name, verts, faces, material)


def _cyl_z(name, cx, cy, z0, z1, r0, r1, segs, material):
    verts = []
    faces = []
    for index in range(segs):
        angle = math.tau * index / segs
        verts.append((cx + r0 * math.cos(angle), cy + r0 * math.sin(angle), z0))
    for index in range(segs):
        angle = math.tau * index / segs
        verts.append((cx + r1 * math.cos(angle), cy + r1 * math.sin(angle), z1))
    verts.append((cx, cy, z0))
    verts.append((cx, cy, z1))
    for index in range(segs):
        nxt = (index + 1) % segs
        faces.append((index, nxt, segs + nxt, segs + index))
        faces.append((segs * 2, nxt, index))
        faces.append((segs * 2 + 1, segs + index, segs + nxt))
    return _add_mesh(name, verts, faces, material)


def _cone_z(name, cx, cy, z0, z1, radius, segs, material):
    return _cyl_z(name, cx, cy, z0, z1, radius, 0.02, segs, material)


HUT_PREFIXES = (
    "Stilt",
    "Deck",
    "Wall",
    "Roof",
    "RoofBrim",
    "Door",
    "Window",
    "Rail_",
    "Rung_",
    "Thatch",
    "Eave",
    "Ridge",
    "PostCap",
    "DeckPlank",
    "CornerPost",
    "Interior",
    "Mat",
    "Threshold",
)


def _clear_kit() -> None:
    for obj in list(bpy.data.objects):
        if obj.type in KEEP_TYPES:
            continue
        bpy.data.objects.remove(obj, do_unlink=True)


def _clear_hut() -> None:
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        if obj.name.startswith("Dock"):
            continue
        if any(obj.name.startswith(prefix) for prefix in HUT_PREFIXES):
            bpy.data.objects.remove(obj, do_unlink=True)


def _build_hut() -> None:
    """Enterable stilt house: deck matches the roof, posts on the edge, door is a hole."""
    wood = _mat("HutWood", WOOD)
    wood_light = _mat("HutWoodLight", WOOD_LIGHT)
    wood_dark = _mat("DockWoodDark", WOOD_DARK)
    plaster = _mat("HutPlaster", PLASTER)
    thatch = _mat("HutThatch", THATCH)
    thatch_dark = _mat("HutThatchDark", THATCH_DARK)
    thatch_tip = _mat("HutThatchTip", (0.90, 0.48, 0.20, 1.0))
    glow = _mat("HutGlow", GLOW, emit=2.4)
    mat_col = _mat("HutMat", (0.55, 0.22, 0.16, 1.0))
    # Metres.  Deck under the eaves, posts on the perimeter, room you walk into.
    deck_hx, deck_hy, deck_z = 1.85, 1.60, 1.18
    room_hx, room_hy = 1.15, 0.95
    wall_t = 0.07
    door_half = 0.48
    wall_z0, wall_z1 = 1.20, 2.72
    posts = (
        (-deck_hx + 0.12, -deck_hy + 0.12),
        (0.0, -deck_hy + 0.12),
        (deck_hx - 0.12, -deck_hy + 0.12),
        (-deck_hx + 0.12, 0.0),
        (deck_hx - 0.12, 0.0),
        (-deck_hx + 0.12, deck_hy - 0.12),
        (0.0, deck_hy - 0.12),
        (deck_hx - 0.12, deck_hy - 0.12),
    )
    for index, (x, y) in enumerate(posts):
        _cyl_z("Stilt.%03d" % index, x, y, 0.0, deck_z, 0.10, 0.085, 10, wood)
        _box("PostCap.%03d" % index, x, y, deck_z + 0.04, 0.12, 0.12, 0.04, wood_dark)
    plank_count = 9
    span = deck_hy * 2.0
    for index in range(plank_count):
        y = -deck_hy + 0.16 + index * (span - 0.32) / (plank_count - 1)
        _box(
            "DeckPlank_%d" % index,
            0.0, y, deck_z,
            deck_hx - 0.04, 0.14, 0.035,
            wood_light if index % 2 == 0 else wood,
        )
    wall_mid = (wall_z0 + wall_z1) * 0.5
    wall_hz = (wall_z1 - wall_z0) * 0.5
    # Back, left, right — solid.  Front is two wings with a door hole.
    _box("WallBack", 0.0, room_hy, wall_mid, room_hx + wall_t, wall_t, wall_hz, plaster)
    _box("WallLeft", -room_hx, 0.0, wall_mid, wall_t, room_hy, wall_hz, plaster)
    _box("WallRight", room_hx, 0.0, wall_mid, wall_t, room_hy, wall_hz, plaster)
    wing = (room_hx - door_half) * 0.5
    _box(
        "WallFrontL",
        -door_half - wing, -room_hy, wall_mid,
        wing + wall_t, wall_t, wall_hz, plaster,
    )
    _box(
        "WallFrontR",
        door_half + wing, -room_hy, wall_mid,
        wing + wall_t, wall_t, wall_hz, plaster,
    )
    _box("DoorFrameL", -door_half, -room_hy, wall_mid, 0.04, 0.05, wall_hz, wood)
    _box("DoorFrameR", door_half, -room_hy, wall_mid, 0.04, 0.05, wall_hz, wood)
    _box(
        "DoorFrameTop",
        0.0, -room_hy, wall_z1 - 0.06,
        door_half + 0.04, 0.05, 0.06, wood,
    )
    _box("Threshold", 0.0, -room_hy - 0.08, deck_z + 0.03, door_half + 0.06, 0.10, 0.03, wood_dark)
    # Window hole in the right wall: split is visual via a glow inset, opening kept.
    _box("Window", room_hx + 0.02, 0.35, 2.05, 0.03, 0.16, 0.14, glow)
    _box("InteriorMat", 0.15, 0.10, deck_z + 0.04, 0.55, 0.40, 0.02, mat_col)
    _box("EaveBeam", 0.0, 0.0, wall_z1 + 0.04, room_hx + 0.12, room_hy + 0.12, 0.05, wood_dark)
    # Thatch covers the whole deck, small overhang past the posts.
    layers = (
        ("ThatchEave", 2.55, 2.82, 2.28, 1.95, thatch_dark, 16),
        ("ThatchLow", 2.72, 3.05, 1.98, 1.35, thatch, 16),
        ("ThatchMid", 2.95, 3.32, 1.38, 0.72, thatch_dark, 14),
        ("ThatchHigh", 3.22, 3.55, 0.78, 0.12, thatch, 12),
    )
    for name, z0, z1, r0, r1, material, segs in layers:
        _cyl_z(name, 0.0, 0.0, z0, z1, r0, r1, segs, material)
    _cyl_z("Ridge", 0.0, 0.0, 3.48, 3.68, 0.14, 0.05, 8, thatch_tip)
    # Deck rails except the ladder bay on -Y.
    for label, y in (("L", -deck_hy + 0.04), ("R", deck_hy - 0.04)):
        if label == "L":
            _box("Rail_FrontL", -1.05, y, deck_z + 0.42, 0.72, 0.03, 0.035, wood)
            _box("Rail_FrontR", 1.05, y, deck_z + 0.42, 0.72, 0.03, 0.035, wood)
        else:
            _box("Rail_%s" % label, 0.0, y, deck_z + 0.42, deck_hx - 0.15, 0.03, 0.035, wood)
    _box("Rail_SideL", -deck_hx + 0.04, 0.15, deck_z + 0.42, 0.03, deck_hy - 0.35, 0.035, wood)
    _box("Rail_SideR", deck_hx - 0.04, 0.15, deck_z + 0.42, 0.03, deck_hy - 0.35, 0.035, wood)
    _cyl_z("Rail_L", -0.16, -deck_hy - 0.18, 0.20, deck_z + 0.04, 0.025, 0.025, 6, wood)
    _cyl_z("Rail_R", 0.16, -deck_hy - 0.18, 0.20, deck_z + 0.04, 0.025, 0.025, 6, wood)
    for index, z in enumerate((0.18, 0.42, 0.66, 0.90, 1.12)):
        _box("Rung_%d" % index, 0.0, -deck_hy - 0.18, z, 0.18, 0.025, 0.02, wood_light)


def _build_dock() -> None:
    wood = _mat("HutWood", WOOD)
    wood_light = _mat("HutWoodLight", WOOD_LIGHT)
    wood_dark = _mat("DockWoodDark", WOOD_DARK)
    gold = _mat("DockGold", GOLD)
    ox, oy = 4.15, 0.0
    for index in range(9):
        px = ox - 2.0 + index * 0.50
        _box(
            "DockPlank_%d" % index,
            px, oy, 0.42, 0.22, 0.72, 0.045,
            wood_light if index % 2 == 0 else wood,
        )
    for index, px in enumerate((ox - 1.85, ox - 0.55, ox + 0.75, ox + 1.95)):
        for side, sy in enumerate((-0.58, 0.58)):
            _cyl_z(
                "DockPiling_%d" % (index * 2 + side),
                px, oy + sy, 0.0, 0.50, 0.09, 0.08, 8, wood_dark,
            )
    for index, px in enumerate((ox - 1.2, ox + 0.2, ox + 1.4)):
        _box("DockBeam_%d" % index, px, oy, 0.30, 0.07, 0.62, 0.05, wood)
    for label, sy in (("L", -0.70), ("R", 0.70)):
        _box("DockRail_%s" % label, ox - 0.55, oy + sy, 0.72, 1.35, 0.035, 0.04, wood)
        for px in (ox - 1.7, ox - 0.55, ox + 0.60):
            _cyl_z(
                "DockPost_%s_%d" % (label, int(px * 10)),
                px, oy + sy, 0.42, 1.02, 0.04, 0.04, 6, wood,
            )
    _cyl_z("DockBollard", ox + 2.15, oy, 0.0, 1.35, 0.11, 0.09, 10, wood)
    _cyl_z("DockRing", ox + 2.15, oy - 0.18, 0.92, 1.02, 0.16, 0.16, 10, gold)
    _box("DockCrate", ox - 1.55, oy + 0.28, 0.62, 0.22, 0.18, 0.16, wood_dark)
    _box("DockCrateLid", ox - 1.55, oy + 0.28, 0.80, 0.24, 0.20, 0.03, wood_light)


def _build_palm(name: str, x: float, y: float, height: float = 4.6) -> None:
    """Jak/Sandover palm: trunk first, umbrella crown, walkable under it."""
    trunk = _mat("PalmTrunk", TRUNK)
    leaf = _mat("PalmLeaf", LEAF)
    leaf_dark = _mat("PalmLeafDark", LEAF_DARK)
    leaf_light = _mat("PalmLeafLight", LEAF_LIGHT)
    gold = _mat("DockGold", GOLD)
    crown_z = height * 0.78
    _cyl_z(name + "_Base", x, y, 0.0, 0.18, 0.22, 0.16, 10, trunk)
    _cyl_z(name + "_Trunk", x, y, 0.12, crown_z, 0.13, 0.08, 10, trunk)
    _cyl_z(name + "_Neck", x, y, crown_z - 0.12, crown_z + 0.22, 0.08, 0.06, 8, trunk)
    _cyl_z(name + "_Heart", x, y, crown_z + 0.18, crown_z + 0.42, 0.16, 0.10, 8, leaf_dark)
    for index in range(7):
        angle = math.tau * index / 7.0
        dx, dy = math.cos(angle), math.sin(angle)
        nx, ny = -dy, dx
        length, width, thick = 1.15, 0.22, 0.03
        cx = x + dx * (length * 0.55)
        cy = y + dy * (length * 0.55)
        cz = crown_z + 0.22
        hx, hy = dx * length * 0.5, dy * length * 0.5
        wx, wy = nx * width, ny * width
        verts = [
            (cx - hx - wx, cy - hy - wy, cz - thick),
            (cx + hx - wx, cy + hy - wy, cz - thick),
            (cx + hx + wx, cy + hy + wy, cz - thick),
            (cx - hx + wx, cy - hy + wy, cz - thick),
            (cx - hx - wx, cy - hy - wy, cz + thick),
            (cx + hx - wx, cy + hy - wy, cz + thick),
            (cx + hx + wx, cy + hy + wy, cz + thick),
            (cx - hx + wx, cy - hy + wy, cz + thick),
        ]
        faces = [
            (0, 1, 2, 3), (4, 7, 6, 5),
            (0, 4, 5, 1), (1, 5, 6, 2),
            (2, 6, 7, 3), (0, 3, 7, 4),
        ]
        _add_mesh(
            name + "_Frond_%d" % index,
            verts,
            faces,
            leaf if index % 2 == 0 else leaf_light,
        )
    _cyl_z(name + "_NutA", x + 0.12, y + 0.08, crown_z + 0.02, crown_z + 0.16, 0.07, 0.06, 6, gold)
    _cyl_z(name + "_NutB", x - 0.10, y + 0.06, crown_z, crown_z + 0.14, 0.06, 0.05, 6, trunk)


def _build_canoe() -> None:
    hull = _mat("CanoeHull", HULL)
    wood = _mat("HutWoodLight", WOOD_LIGHT)
    straw = _mat("PalmStraw", STRAW)
    cx, cy, z = 6.35, -1.55, 0.22
    _box("CanoeHull", cx, cy, z, 1.15, 0.28, 0.12, hull)
    _box("CanoeBow", cx + 1.28, cy, z + 0.04, 0.22, 0.16, 0.10, hull)
    _box("CanoeStern", cx - 1.28, cy, z + 0.04, 0.22, 0.16, 0.10, hull)
    _box("CanoeRib", cx, cy, z + 0.14, 0.55, 0.22, 0.03, wood)
    _box("CanoePaddle", cx + 0.35, cy + 0.42, z + 0.22, 0.04, 0.55, 0.03, wood)
    _cyl_z("BasketA", 4.55, 0.42, 0.46, 0.78, 0.16, 0.14, 8, straw)
    _cyl_z("BasketB", 4.85, 0.55, 0.46, 0.70, 0.12, 0.11, 8, straw)


def _shade_material() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.shading.type = "MATERIAL"
            space.shading.use_scene_lights = True
            space.shading.use_scene_world = False


def _frame_view() -> None:
    cam = bpy.data.objects.get("Camera")
    if cam is not None:
        cam.location = (8.2, -7.4, 5.1)
        cam.hide_set(False)
        cam.hide_viewport = True
    light = bpy.data.objects.get("Light")
    if light is not None:
        light.location = (3.4, -3.0, 6.2)
    target = Vector((2.4, -0.4, 1.4))
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.overlay.show_extras = False
            r3d = space.region_3d
            r3d.view_perspective = "PERSP"
            r3d.view_location = target
            r3d.view_distance = 14.5
            r3d.view_rotation = Euler((1.08, 0.0, 0.78)).to_quaternion()
    _shade_material()


def rebuild_hut() -> str:
    _clear_hut()
    _build_hut()
    _frame_view()
    return "hut_rebuilt"


def build() -> str:
    _clear_kit()
    _build_hut()
    _build_dock()
    _build_palm("PalmA", -2.6, -2.4, 4.8)
    _build_palm("PalmB", 2.8, 2.6, 4.3)
    _build_palm("PalmC", 6.8, 1.8, 5.1)
    _build_canoe()
    _frame_view()
    return "sandover_kit"


if __name__ == "__gg_blender_exec__" or __name__ == "__main__":
    print(build())
