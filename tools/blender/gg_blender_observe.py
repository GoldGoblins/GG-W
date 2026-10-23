"""Measurements and deformation setup for the live Blender sidecar.

Screenshots of one User Perspective view hide holes. These commands return
boundary-loop counts, a four-view turnaround, a 90-joint deform armature,
and an explicit clean pass. Clean does nothing unless apply is true.
"""

from __future__ import annotations

from pathlib import Path
import math

import bmesh
import bpy
from mathutils import Vector

from gg_deform_rig import ENGINE_JOINT_CAP, SCHEMA, anatomy_names, deform_bones


TURNAROUND_VIEWS = ("front", "side", "back", "three_quarter")
_CLEAN_MODES = {"fill", "voxel"}


def _ok(**fields) -> dict:
    payload = {"ok": True}
    payload.update(fields)
    return payload


def _err(code: str, **fields) -> dict:
    payload = {"ok": False, "error": code}
    payload.update(fields)
    return payload


def _view3d_override() -> dict:
    manager = getattr(bpy.context, "window_manager", None)
    if manager is None:
        return {}
    for window in list(manager.windows):
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is None:
                continue
            return {"window": window, "screen": screen, "area": area, "region": region}
    return {}


def _run_ops(fn):
    """Operators from the sidecar timer have no area unless one is supplied."""
    override = _view3d_override()
    if override:
        with bpy.context.temp_override(**override):
            return fn()
    return fn()


def _object_mode() -> None:
    active = bpy.context.view_layer.objects.active
    if active is None or getattr(active, "mode", "OBJECT") == "OBJECT":
        return

    def leave() -> None:
        bpy.ops.object.mode_set(mode="OBJECT")

    _run_ops(leave)


def _activate(obj: bpy.types.Object) -> None:
    view_layer = bpy.context.view_layer
    for other in view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj


def _meshes(name: str) -> list[bpy.types.Object]:
    wanted = str(name or "").strip()
    if wanted:
        obj = bpy.data.objects.get(wanted)
        if obj is None or obj.type != "MESH":
            return []
        return [obj]
    return [obj for obj in bpy.data.objects if obj.type == "MESH"]


def _one_mesh(name: str) -> bpy.types.Object | None:
    wanted = str(name or "").strip()
    if wanted:
        found = _meshes(wanted)
        return found[0] if found else None
    active = bpy.context.view_layer.objects.active
    if active is not None and active.type == "MESH":
        return active
    meshes = _meshes("")
    if len(meshes) == 1:
        return meshes[0]
    return None


def _world_bounds(meshes: list[bpy.types.Object]) -> tuple[Vector, Vector] | None:
    if not meshes:
        return None
    low = Vector((1.0e9, 1.0e9, 1.0e9))
    high = Vector((-1.0e9, -1.0e9, -1.0e9))
    found = False
    for obj in meshes:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            low.x, low.y, low.z = min(low.x, world.x), min(low.y, world.y), min(low.z, world.z)
            high.x, high.y, high.z = max(high.x, world.x), max(high.y, world.y), max(high.z, world.z)
            found = True
    if not found:
        return None
    return low, high


def _boundary_loops(mesh_bmesh: bmesh.types.BMesh, matrix) -> list[dict]:
    edges = [edge for edge in mesh_bmesh.edges if edge.is_boundary]
    if not edges:
        return []
    neighbors: dict = {}
    for edge in edges:
        for vert in edge.verts:
            neighbors.setdefault(vert, []).append(edge)
    unused = set(edges)
    loops = []
    while unused:
        current = next(iter(unused))
        start = current.verts[0]
        vert = start
        walked = []
        loop_verts = []
        for _ in range(len(edges) + 2):
            unused.discard(current)
            walked.append(current)
            nxt = current.other_vert(vert)
            loop_verts.append(nxt)
            if nxt == start:
                break
            choices = [item for item in neighbors.get(nxt, []) if item in unused]
            if not choices:
                break
            current = choices[0]
            vert = nxt
        coords = [matrix @ item.co for item in loop_verts]
        if not coords:
            continue
        center = sum(coords, Vector()) / len(coords)
        loops.append(
            {
                "edges": len(walked),
                "centroid": [round(center.x, 4), round(center.y, 4), round(center.z, 4)],
            }
        )
    loops.sort(key=lambda row: (-row["edges"], row["centroid"][0]))
    return loops


def _mesh_report(obj: bpy.types.Object) -> dict:
    mesh_bmesh = bmesh.new()
    mesh_bmesh.from_mesh(obj.data)
    mesh_bmesh.verts.ensure_lookup_table()
    mesh_bmesh.edges.ensure_lookup_table()
    mesh_bmesh.faces.ensure_lookup_table()
    tris = quads = ngons = 0
    for face in mesh_bmesh.faces:
        sides = len(face.verts)
        if sides == 3:
            tris += 1
        elif sides == 4:
            quads += 1
        elif sides > 4:
            ngons += 1
    boundary = sum(1 for edge in mesh_bmesh.edges if edge.is_boundary)
    wire = sum(1 for edge in mesh_bmesh.edges if edge.is_wire)
    junction = sum(
        1
        for edge in mesh_bmesh.edges
        if not edge.is_manifold and not edge.is_boundary and not edge.is_wire
    )
    flipped = sum(1 for edge in mesh_bmesh.edges if edge.is_manifold and not edge.is_contiguous)
    loose = sum(1 for vert in mesh_bmesh.verts if not vert.link_edges)
    loops = _boundary_loops(mesh_bmesh, obj.matrix_world)
    mesh_bmesh.free()
    bounds = _world_bounds([obj])
    box = None
    if bounds is not None:
        low, high = bounds
        size = high - low
        box = {
            "min": [round(low.x, 4), round(low.y, 4), round(low.z, 4)],
            "max": [round(high.x, 4), round(high.y, 4), round(high.z, 4)],
            "size": [round(size.x, 4), round(size.y, 4), round(size.z, 4)],
        }
    modifiers = [modifier.type for modifier in obj.modifiers if modifier.type == "ARMATURE"]
    return {
        "name": obj.name,
        "verts": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
        "tris": tris,
        "quads": quads,
        "ngons": ngons,
        "boundary_edges": boundary,
        "hole_loops": len(loops),
        "holes": loops[:8],
        "nonmanifold_junctions": junction,
        "wire_edges": wire,
        "loose_verts": loose,
        "flipped_edges": flipped,
        "armature_modifiers": len(modifiers),
        "vertex_groups": len(obj.vertex_groups),
        "closed": boundary == 0 and junction == 0 and wire == 0 and loose == 0,
        "bbox": box,
    }


def _armature_report(obj: bpy.types.Object) -> dict:
    names = {bone.name for bone in obj.data.bones}
    target = anatomy_names()
    missing = sorted(target - names)
    extra = sorted(names - target)
    return {
        "name": obj.name,
        "bones": len(obj.data.bones),
        "deform_bones": sum(1 for bone in obj.data.bones if bone.use_deform),
        "matches_anatomy": not missing and not extra,
        "missing_from_anatomy": missing[:24],
        "missing_count": len(missing),
        "extra_count": len(extra),
        "schema": str(obj.get("gg_schema") or ""),
    }


def inspect_scene(name: str = "") -> dict:
    _object_mode()
    meshes = _meshes(name)
    if name and not meshes:
        return _err("BLENDER_MESH_MISSING", name=name)
    reports = [_mesh_report(obj) for obj in meshes]
    reports.sort(key=lambda row: (-row["boundary_edges"], row["name"]))
    armatures = [_armature_report(obj) for obj in bpy.data.objects if obj.type == "ARMATURE"]
    closed = all(row["closed"] for row in reports) if reports else False
    return _ok(
        blender=bpy.app.version_string,
        mesh_count=len(reports),
        closed=closed,
        boundary_edges=sum(row["boundary_edges"] for row in reports),
        hole_loops=sum(row["hole_loops"] for row in reports),
        anatomy_joint_target=len(anatomy_names()),
        engine_joint_cap=ENGINE_JOINT_CAP,
        meshes=reports[:16],
        armatures=armatures[:8],
    )


def _place_camera(cam: bpy.types.Object, center: Vector, offset: Vector, distance: float) -> None:
    cam.location = center + offset.normalized() * distance
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()


def render_turnaround(directory: str, size: int = 640, name: str = "", *,
                      collection: str = "", framing: dict | None = None,
                      style: str = "clay", orthographic: bool = False) -> dict:
    _object_mode()
    scene = bpy.context.scene
    meshes = _meshes(name)
    if collection:
        group = bpy.data.collections.get(collection)
        if group is None:
            return _err("BLENDER_COLLECTION_MISSING", name=collection)
        meshes = [obj for obj in group.all_objects if obj.type == "MESH"]
        meshes = [obj for obj in meshes if not obj.hide_render]
    meshes = [obj for obj in meshes if obj.name in scene.objects]
    if name and not meshes:
        return _err("BLENDER_MESH_MISSING", name=name)
    bounds = _world_bounds(meshes)
    if bounds is None:
        return _err("BLENDER_MESH_MISSING")
    low, high = bounds
    center = (low + high) * 0.5
    span = high - low
    distance = max(span.length, 0.2) * 1.7
    ortho = max(span.x, span.y, span.z, 0.2) * 1.45
    if style not in {"clay", "silhouette", "material", "appearance"}:
        return _err("BLENDER_TURNAROUND_STYLE")
    if framing is not None:
        try:
            values = [float(value) for value in framing["center"]]
            distance = float(framing["distance"])
            ortho = float(framing["ortho_scale"])
            if (len(values) != 3 or not all(math.isfinite(v) for v in values + [distance, ortho])
                    or distance <= 0 or ortho <= 0):
                raise ValueError("invalid framing")
            center = Vector(values)
        except (KeyError, TypeError, ValueError, OverflowError):
            return _err("BLENDER_TURNAROUND_FRAMING")
    folder = Path(directory or "/tmp/gg-blender-turn").expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    pixels = max(256, min(int(size or 640), 1024))
    camera_data = bpy.data.cameras.new("GG_Observe_Cam")
    camera = bpy.data.objects.new("GG_Observe_Cam", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = ortho
    previous_camera = scene.camera
    previous_engine = scene.render.engine
    previous_x = scene.render.resolution_x
    previous_y = scene.render.resolution_y
    previous_percent = scene.render.resolution_percentage
    previous_path = scene.render.filepath
    previous_format = scene.render.image_settings.file_format
    shading = scene.display.shading
    shade_fields = ("type", "color_type", "single_color", "light", "background_type", "background_color",
                    "show_shadows", "show_cavity", "show_specular_highlight")
    previous_shading = {key: (tuple(getattr(shading, key)) if key.endswith("color")
                              else getattr(shading, key)) for key in shade_fields}
    visibility = [(obj, obj.hide_render) for obj in scene.objects]
    previous_transparent = scene.render.film_transparent
    previous_world = scene.world
    preview_world = None
    preview_lights = []
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = pixels
    scene.render.resolution_y = pixels
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    offsets = {
        "front": Vector((0.0, -1.0, 0.15)),
        "side": Vector((1.0, 0.0, 0.15)),
        "back": Vector((0.0, 1.0, 0.15)),
        "three_quarter": Vector((0.72, -0.72, 0.38)),
    }
    if orthographic:
        for view in ("front", "side", "back"):
            offsets[view].z = 0.0
    paths: dict[str, str] = {}
    wire_error = ""
    try:
        targets = set(meshes)
        for obj, _hidden in visibility:
            obj.hide_render = obj not in targets
        scene.render.film_transparent = False
        shading.type = "SOLID"
        shading.light = "FLAT" if style == "silhouette" else "STUDIO"
        shading.color_type = "MATERIAL" if style == "material" else "SINGLE"
        shading.single_color = (0.0, 0.0, 0.0) if style == "silhouette" else (0.65, 0.65, 0.65)
        shading.background_type = "VIEWPORT"
        shading.background_color = (1.0, 1.0, 1.0)
        shading.show_shadows = False
        shading.show_cavity = style != "silhouette"
        shading.show_specular_highlight = style != "silhouette"
        if style == "appearance":
            scene.render.engine = "BLENDER_EEVEE"
            preview_world = bpy.data.worlds.new("GG_Observe_World")
            preview_world.use_nodes = True
            preview_world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.18, 0.18, 0.18, 1)
            preview_world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5
            scene.world = preview_world
            for index, offset in enumerate((Vector((3, -4, 5)), Vector((-4, -2, 2)), Vector((0, 4, 4)))):
                data = bpy.data.lights.new("GG_Observe_Light", "AREA")
                light = bpy.data.objects.new(data.name, data)
                scene.collection.objects.link(light)
                light.location = center + offset.normalized() * distance * 1.4
                light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
                data.energy = (1200, 700, 1000)[index] * (ortho / 4) ** 2
                data.shape = "DISK"
                data.size = ortho
                preview_lights.append((light, data))
        for view in TURNAROUND_VIEWS:
            _place_camera(camera, center, offsets[view], distance)
            target = folder / f"{view}.png"
            scene.render.filepath = str(target)
            bpy.ops.render.render(write_still=True)
            paths[view] = str(target)
        if style == "clay":
            try:
                shading.type = "WIREFRAME"
                _place_camera(camera, center, offsets["front"], distance)
                wire = folder / "front_wire.png"
                scene.render.filepath = str(wire)
                bpy.ops.render.render(write_still=True)
                paths["front_wire"] = str(wire)
            except Exception as exc:
                wire_error = type(exc).__name__
    except Exception as exc:
        return _err("BLENDER_TURNAROUND_FAILED", detail=type(exc).__name__, message=str(exc)[:400])
    finally:
        for obj, hidden in visibility:
            obj.hide_render = hidden
        scene.render.film_transparent = previous_transparent
        scene.world = previous_world
        for light, data in preview_lights:
            bpy.data.objects.remove(light, do_unlink=True)
            bpy.data.lights.remove(data)
        if preview_world:
            bpy.data.worlds.remove(preview_world)
        scene.camera = previous_camera
        scene.render.engine = previous_engine
        scene.render.resolution_x = previous_x
        scene.render.resolution_y = previous_y
        scene.render.resolution_percentage = previous_percent
        scene.render.filepath = previous_path
        scene.render.image_settings.file_format = previous_format
        try:
            for key, value in previous_shading.items():
                setattr(shading, key, value)
        except Exception:
            pass
        bpy.data.objects.remove(camera, do_unlink=True)
        if camera_data.users == 0:
            bpy.data.cameras.remove(camera_data)
    missing = [view for view, path in paths.items() if not Path(path).is_file()]
    if missing:
        return _err("BLENDER_TURNAROUND_MISSING", views=missing)
    return _ok(
        directory=str(folder),
        framing={"center": list(center), "distance": distance, "ortho_scale": ortho},
        style=style,
        orthographic=orthographic,
        targets=[obj.name for obj in meshes],
        color_limit=("EEVEE material preview in controlled lighting; not an engine playback test."
                     if style == "appearance" else "Workbench geometry/base-color view."),
        wire_error=wire_error,
        views={view: {"path": path, "bytes": Path(path).stat().st_size} for view, path in paths.items()},
    )


def apply_deform_rig(name: str = "", replace: bool = False) -> dict:
    _object_mode()
    existing = bpy.data.objects.get("GG_Deform")
    if existing is not None and existing.type == "ARMATURE" and not replace:
        return _err("BLENDER_DEFORM_EXISTS", name=existing.name, bones=len(existing.data.bones))
    if existing is not None:
        data = existing.data
        bpy.data.objects.remove(existing, do_unlink=True)
        if data is not None and getattr(data, "users", 1) == 0 and isinstance(data, bpy.types.Armature):
            bpy.data.armatures.remove(data)
    meshes = _meshes(name)
    if name and not meshes:
        return _err("BLENDER_MESH_MISSING", name=name)
    bounds = _world_bounds(meshes)
    if bounds is None:
        origin = Vector((0.0, 0.0, 0.0))
        height = 1.0
    else:
        low, high = bounds
        origin = Vector((((low.x + high.x) * 0.5), ((low.y + high.y) * 0.5), low.z))
        height = max(high.z - low.z, 0.05)
    armature_data = bpy.data.armatures.new("GG_Deform")
    armature = bpy.data.objects.new("GG_Deform", armature_data)
    bpy.context.scene.collection.objects.link(armature)
    armature.location = origin
    _activate(armature)

    def enter_edit() -> None:
        bpy.ops.object.mode_set(mode="EDIT")

    _run_ops(enter_edit)
    created = {}
    front = Vector((0.0, -1.0, 0.0))
    for spec in deform_bones():
        bone = armature_data.edit_bones.new(spec["name"])
        bone.head = (
            spec["head"][0] * height,
            spec["head"][2] * height,
            spec["head"][1] * height,
        )
        bone.tail = (
            spec["tail"][0] * height,
            spec["tail"][2] * height,
            spec["tail"][1] * height,
        )
        bone.use_deform = True
        try:
            bone.align_roll(front)
        except Exception:
            pass
        created[spec["name"]] = bone
    for spec in deform_bones():
        parent_name = spec["parent"]
        if not parent_name:
            continue
        bone = created[spec["name"]]
        bone.parent = created[parent_name]
        bone.use_connect = bool(spec["connect"])

    def leave_edit() -> None:
        bpy.ops.object.mode_set(mode="OBJECT")

    _run_ops(leave_edit)
    for pose_bone in armature.pose.bones:
        pose_bone.rotation_mode = "XYZ"
    armature["gg_schema"] = SCHEMA
    armature["gg_joints"] = len(created)
    armature["gg_fit_height"] = round(height, 4)
    return _ok(
        name=armature.name,
        joints=len(created),
        schema=SCHEMA,
        height=round(height, 4),
        origin=[round(origin.x, 4), round(origin.y, 4), round(origin.z, 4)],
        skinned=False,
    )


def _fill(obj: bpy.types.Object, merge: float, sides: int) -> None:
    # bmesh does not need a 3D View, so this works from the sidecar timer
    # and from blender --background.
    _object_mode()
    mesh_bmesh = bmesh.new()
    mesh_bmesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh_bmesh, verts=list(mesh_bmesh.verts), dist=merge)
    edges = [edge for edge in mesh_bmesh.edges if edge.is_boundary]
    if edges:
        bmesh.ops.holes_fill(mesh_bmesh, edges=edges, sides=sides)
    bmesh.ops.recalc_face_normals(mesh_bmesh, faces=list(mesh_bmesh.faces))
    mesh_bmesh.to_mesh(obj.data)
    mesh_bmesh.free()
    obj.data.update()


def _voxel(obj: bpy.types.Object, factor: int) -> float:
    _activate(obj)
    bounds = _world_bounds([obj])
    if bounds is None:
        raise RuntimeError("mesh has no bounds")
    low, high = bounds
    diagonal = max((high - low).length, 0.05)
    voxel_size = max(diagonal / float(factor), 0.001)
    modifier = obj.modifiers.new("GG_Voxel", "REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = voxel_size
    modifier.use_smooth_shade = True

    def apply() -> None:
        _activate(obj)
        bpy.ops.object.modifier_apply(modifier=modifier.name)

    try:
        _run_ops(apply)
    except Exception:
        if modifier.name in obj.modifiers:
            obj.modifiers.remove(modifier)
        raise
    return voxel_size


def clean_mesh(name: str = "", mode: str = "fill", apply: bool = False, merge: float = 0.0001, sides: int = 0, voxel_factor: int = 80) -> dict:
    _object_mode()
    wanted = str(mode or "fill").strip().lower()
    if wanted not in _CLEAN_MODES:
        return _err("BLENDER_CLEAN_MODE", mode=wanted)
    obj = _one_mesh(name)
    if obj is None:
        return _err("BLENDER_MESH_AMBIGUOUS", message="Name the mesh. More than one is in the scene.")
    before = _mesh_report(obj)
    factor = max(8, min(int(voxel_factor or 80), 400))
    distance = max(0.0, float(merge or 0.0))
    hole_sides = max(0, min(int(sides or 0), 256))
    if not apply:
        return _ok(
            dry_run=True,
            mode=wanted,
            name=obj.name,
            before=before,
            note="Pass apply true to merge, fill and recalculate normals, or to voxel-remesh.",
        )
    try:
        if wanted == "fill":
            _fill(obj, distance, hole_sides)
            detail = {"merge": distance, "sides": hole_sides}
        else:
            detail = {"voxel_size": _voxel(obj, factor), "factor": factor}
    except Exception as exc:
        return _err("BLENDER_CLEAN_FAILED", detail=type(exc).__name__, message=str(exc)[:400], name=obj.name)
    after = _mesh_report(obj)
    return _ok(dry_run=False, mode=wanted, name=obj.name, before=before, after=after, **detail)


def dispatch(cmd: str, request: dict) -> dict:
    name = str(request.get("name") or "")
    if cmd == "inspect":
        return inspect_scene(name)
    if cmd == "turnaround":
        return render_turnaround(
            str(request.get("directory") or ""),
            int(request.get("size") or 640),
            name,
            collection=str(request.get("collection") or ""),
            framing=request.get("framing"),
            style=str(request.get("style") or "clay"),
            orthographic=bool(request.get("orthographic")),
        )
    if cmd == "deform_rig":
        return apply_deform_rig(name, bool(request.get("replace")))
    if cmd == "clean":
        merge = request.get("merge", 0.0001)
        factor = request.get("voxel_factor", 80)
        return clean_mesh(
            name,
            str(request.get("mode") or "fill"),
            bool(request.get("apply")),
            float(0.0001 if merge is None else merge),
            int(request.get("sides") or 0),
            int(80 if factor is None else factor),
        )
    return _err("BLENDER_CMD_UNKNOWN", cmd=cmd)
