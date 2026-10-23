"""Isolated reference/model workspaces in the visible Blender EXT process.

Called through the existing MCP exec tool. No daemon, provider credentials,
automatic mesh generation or edits to an existing game scene.
"""
from __future__ import annotations

from array import array
import hashlib
import importlib
import json
import math
from pathlib import Path
import re

import bpy


VIEWS = ("front", "side", "back", "three_quarter")


def _names(job: str) -> tuple[str, str, str]:
    if not re.fullmatch(r"[a-z0-9_-]{1,48}", job):
        raise ValueError("Invalid modeling job")
    base = "GG_Model_" + job
    return base, base + "_Geometry", base + "_References"


def _workspace(job: str):
    scene_name, model_name, _ = _names(job)
    scene = bpy.data.scenes.get(scene_name)
    group = bpy.data.collections.get(model_name)
    if scene is None or group is None or group.name not in scene.collection.children:
        raise ValueError("Create the isolated workspace first")
    objects = list(group.all_objects)
    if any(any(owner != scene for owner in obj.users_scene) for obj in objects):
        raise ValueError("Model objects must belong only to this job scene")
    owned_data = {obj.data for obj in objects if obj.data is not None}
    if any(obj not in objects and obj.data in owned_data for obj in bpy.data.objects):
        raise ValueError("Make geometry/rig data independent before using the job workspace")
    return scene, group, objects


def setup(job: str, references: dict) -> dict:
    scene_name, model_name, ref_name = _names(job)
    if bpy.data.scenes.get(scene_name):
        raise ValueError("Workspace already exists; resume it instead of replacing it")
    scene = bpy.data.scenes.new(scene_name)
    models = bpy.data.collections.new(model_name)
    refs = bpy.data.collections.new(ref_name)
    scene.collection.children.link(models)
    scene.collection.children.link(refs)
    refs.hide_render = True
    # Native UV boards display regions of a shared sheet without rewriting it.
    rotations = {"front": (math.pi / 2, 0, 0), "side": (math.pi / 2, 0, math.pi / 2),
                 "back": (math.pi / 2, 0, math.pi), "three_quarter": (math.pi / 2, 0, 0)}
    positions = {"front": (0, 2, 0), "side": (-2, 0, 0), "back": (0, -2, 0),
                 "three_quarter": (6, 2, 0)}
    for view in VIEWS:
        row = references[view]
        image = bpy.data.images.load(row["path"], check_existing=True)
        u0, v0, u1, v1 = row.get("region", [0, 0, 1, 1])
        aspect = image.size[0] * (u1 - u0) / max(1, image.size[1] * (v1 - v0))
        half_w, half_h = 2 * aspect, 2
        mesh = bpy.data.meshes.new(scene_name + "_Ref_" + view)
        mesh.from_pydata([(-half_w, -half_h, 0), (half_w, -half_h, 0),
                          (half_w, half_h, 0), (-half_w, half_h, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new(name="ReferenceUV")
        for loop, coord in zip(uv.data, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))):
            loop.uv = coord
        material = bpy.data.materials.new(scene_name + "_Ref_" + view)
        material.use_nodes = True
        material.use_backface_culling = True
        nodes = material.node_tree.nodes
        nodes.clear()
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        emit = nodes.new("ShaderNodeEmission")
        output = nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(texture.outputs["Color"], emit.inputs["Color"])
        material.node_tree.links.new(emit.outputs[0], output.inputs["Surface"])
        nodes.active = texture
        mesh.materials.append(material)
        obj = bpy.data.objects.new(mesh.name, mesh)
        refs.objects.link(obj)
        obj.rotation_euler = rotations[view]
        obj.location = positions[view]
        obj.hide_render = True
        obj.hide_select = True
        obj["gg_reference_view"] = view
    window = bpy.context.window or next(iter(bpy.context.window_manager.windows), None)
    if window:
        window.scene = scene
        layer = scene.view_layers[0].layer_collection.children.get(models.name)
        if layer:
            scene.view_layers[0].active_layer_collection = layer
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "SOLID"
                area.spaces.active.shading.color_type = "TEXTURE"
    return {"scene": scene_name, "collection": model_name, "references": ref_name}


def _material(material, visited: frozenset = frozenset()) -> dict:
    if material is None:
        return {}
    tree = material if isinstance(material, bpy.types.NodeTree) else getattr(material, "node_tree", None)
    result = {"name": material.name, "diffuse": list(getattr(material, "diffuse_color", [])),
              "nodes": [], "links": []}
    if tree is None or (hasattr(material, "use_nodes") and not material.use_nodes):
        return result
    if tree.as_pointer() in visited:
        return {"tree": tree.name, "cycle": True}
    visited = visited | {tree.as_pointer()}
    for node in tree.nodes:
        row = {"name": node.name, "type": node.bl_idname, "sockets": []}
        for direction, socket in [("in", socket) for socket in node.inputs] + [("out", socket) for socket in node.outputs]:
            if not hasattr(socket, "default_value"):
                continue
            value = socket.default_value
            if not isinstance(value, (str, bool, int, float)):
                try:
                    value = list(value)
                except TypeError:
                    value = str(value)
            row["sockets"].append([direction, socket.identifier, value])
        if getattr(node, "node_tree", None):
            row["group"] = _material(node.node_tree, visited)
        if hasattr(node, "color_ramp"):
            row["ramp"] = {"interpolation": node.color_ramp.interpolation,
                           "elements": [[element.position, list(element.color)] for element in node.color_ramp.elements]}
        for key in ("operation", "blend_type", "interpolation", "projection", "extension"):
            if hasattr(node, key):
                row[key] = getattr(node, key)
        image = getattr(node, "image", None)
        if image:
            image_path = Path(bpy.path.abspath(image.filepath))
            row["image"] = {"path": str(image_path), "size": list(image.size),
                            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest()
                            if image_path.is_file() else "packed-or-generated"}
            if image.is_dirty or image.source == "GENERATED" or image.packed_file:
                pixels = hashlib.sha256()
                for offset in range(0, len(image.pixels), 65536):
                    pixels.update(array("f", image.pixels[offset:offset + 65536]).tobytes())
                row["image"]["pixel_sha256"] = pixels.hexdigest()
        result["nodes"].append(row)
    result["links"] = sorted([link.from_node.name, link.from_socket.identifier,
                              link.to_node.name, link.to_socket.identifier]
                             for link in tree.links)
    return result


def _rna_scalars(item) -> dict:
    result = {}
    for prop in item.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.type not in {"BOOLEAN", "INT", "FLOAT", "ENUM", "STRING", "POINTER"}:
            continue
        value = getattr(item, prop.identifier)
        if prop.type == "POINTER":
            value = getattr(value, "name_full", None)
        elif getattr(prop, "is_array", False):
            value = list(value)
        elif isinstance(value, set):
            value = sorted(value)
        result[prop.identifier] = value
    return result


def _animation(data) -> dict:
    animation = getattr(data, "animation_data", None)
    if animation is None:
        return {}
    actions = []
    if animation.action:
        actions.append(animation.action)
    tracks = []
    for track in animation.nla_tracks:
        strips = []
        for strip in track.strips:
            strips.append(_rna_scalars(strip))
            if strip.action:
                actions.append(strip.action)
        tracks.append({"name": track.name, "mute": track.mute, "solo": track.is_solo, "strips": strips})
    result = {"actions": [], "tracks": tracks, "drivers": []}
    for action in set(actions):
        curves = list(getattr(action, "fcurves", []))
        for layer in getattr(action, "layers", []):
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", []):
                    curves.extend(bag.fcurves)
        result["actions"].append({"name": action.name,
            "curves": [{"path": curve.data_path, "index": curve.array_index,
                        "keys": [_rna_scalars(key) for key in curve.keyframe_points],
                        "modifiers": [_rna_scalars(modifier) for modifier in curve.modifiers]}
                       for curve in curves]})
    result["actions"].sort(key=lambda row: row["name"])
    for curve in animation.drivers:
        result["drivers"].append({"path": curve.data_path, "index": curve.array_index,
            "type": curve.driver.type, "expression": curve.driver.expression,
            "variables": [{"name": variable.name, "type": variable.type,
                           "targets": [_rna_scalars(target) for target in variable.targets]}
                          for variable in curve.driver.variables]})
    return result


def fingerprint(job: str) -> dict:
    scene, group, objects = _workspace(job)
    rows = []
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        graph = bpy.context.evaluated_depsgraph_get()
        for obj in sorted(objects, key=lambda item: item.name):
            row = {"name": obj.name, "type": obj.type,
                   "matrix": [list(r) for r in obj.matrix_world], "hidden": obj.hide_render,
                   "animation": _animation(obj), "data_animation": _animation(obj.data),
                   "modifiers": [_rna_scalars(modifier) for modifier in obj.modifiers]}
            if obj.type == "MESH":
                evaluated = obj.evaluated_get(graph)
                mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
                try:
                    row["vertices"] = [list(v.co) for v in mesh.vertices]
                    row["faces"] = [list(face.vertices) for face in mesh.polygons]
                    row["smooth"] = [face.use_smooth for face in mesh.polygons]
                    row["face_materials"] = [face.material_index for face in mesh.polygons]
                    row["uv"] = [[list(loop.uv) for loop in layer.data] for layer in mesh.uv_layers]
                    row["colors"] = [[layer.name, layer.domain, [list(value.color) for value in layer.data]]
                                     for layer in mesh.color_attributes]
                    row["normals"] = [list(normal.vector) for normal in mesh.corner_normals]
                    row["groups"] = [group.name for group in obj.vertex_groups]
                    row["weights"] = [[(group.group, group.weight) for group in vertex.groups] for vertex in obj.data.vertices]
                    keys = obj.data.shape_keys
                    if keys:
                        row["shape_keys"] = {"animation": _animation(keys),
                            "blocks": [[key.name, key.value, [list(point.co) for point in key.data]] for key in keys.key_blocks]}
                    row["materials"] = [_material(mat) for mat in obj.data.materials]
                finally:
                    evaluated.to_mesh_clear()
            elif obj.type == "ARMATURE":
                row["pose"] = [[bone.name, [list(r) for r in bone.matrix]] for bone in obj.pose.bones]
            rows.append(row)
    encoded = json.dumps({"frame": scene.frame_current, "objects": rows}, sort_keys=True, allow_nan=False).encode()
    return {"fingerprint": hashlib.sha256(encoded).hexdigest(), "objects": len(objects),
            "meshes": sum(obj.type == "MESH" for obj in objects), "scene": scene.name,
            "collection": group.name}


def _save_scene(scene, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".writing.blend")
    bpy.data.libraries.write(str(temporary), {scene}, path_remap="RELATIVE", fake_user=True)
    temporary.replace(path)


def capture(job: str, directory: str, framing: dict | None = None, size: int = 640) -> dict:
    import gg_blender_observe
    observe = importlib.reload(gg_blender_observe)
    scene, group, objects = _workspace(job)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("Build the model in the job geometry collection before capture")
    folder = Path(directory)
    if folder.exists():
        raise ValueError("A capture directory cannot be reused")
    folder.mkdir(parents=True)
    before = fingerprint(job)["fingerprint"]
    views, reports = {}, []
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        for style in ("clay", "silhouette", "appearance"):
            rendered = observe.render_turnaround(str(folder / style), size, collection=group.name,
                                                framing=framing, style=style, orthographic=True)
            if not rendered.get("ok"):
                raise RuntimeError(rendered.get("error", "Turnaround failed"))
            framing = rendered["framing"]
            views[style] = rendered["views"]
        for mesh in meshes:
            reports.append(observe._mesh_report(mesh))
    after = fingerprint(job)["fingerprint"]
    if before != after:
        raise RuntimeError("Model changed while capturing")
    checkpoint = folder / "model.blend"
    _save_scene(scene, checkpoint)
    metrics_path = folder / "mesh-report.json"
    metrics_path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    summary = {key: sum(row[key] for row in reports) for key in
               ("verts", "faces", "boundary_edges", "nonmanifold_junctions", "wire_edges", "loose_verts", "flipped_edges")}
    return {"framing": framing, "views": views, "mesh_reports": {"summary": summary, "path": str(metrics_path)},
            "fingerprint": after, "checkpoint": str(checkpoint),
            "material_review": "EEVEE appearance pass uses controlled lighting; engine/deformation checks are separate."}


def export(job: str, directory: str, expected: str) -> dict:
    current = fingerprint(job)
    if current["fingerprint"] != expected:
        raise ValueError("Capture and review the current model before exporting")
    scene, _group, objects = _workspace(job)
    if not current["meshes"]:
        raise ValueError("Empty model")
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=False)
    blend, glb = folder / "model.blend", folder / "model.glb"
    _save_scene(scene, blend)
    layer = scene.view_layers[0]
    selected = [obj for obj in layer.objects if obj.select_get(view_layer=layer)]
    active = layer.objects.active
    try:
        with bpy.context.temp_override(scene=scene, view_layer=layer):
            for obj in layer.objects:
                obj.select_set(obj in objects, view_layer=layer)
            bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True,
                                      use_active_scene=True, use_renderable=True, export_cameras=False, export_lights=False)
    finally:
        for obj in layer.objects:
            obj.select_set(obj in selected, view_layer=layer)
        layer.objects.active = active
    return {"blend": str(blend), "glb": str(glb), "fingerprint": current["fingerprint"]}


def dispatch(operation: str, payload: dict) -> dict:
    if operation == "setup":
        return setup(payload["job"], payload["references"])
    if operation == "capture":
        return capture(payload["job"], payload["directory"], payload.get("framing"), payload.get("size", 640))
    if operation == "fingerprint":
        return fingerprint(payload["job"])
    if operation == "export":
        return export(payload["job"], payload["directory"], payload["expected"])
    raise ValueError("Unknown reference workflow operation")
