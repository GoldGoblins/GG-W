"""Blender oracle and bind/first/middle/last source-rig study sheet.

blender --background --factory-startup --disable-autoexec --python-exit-code 1
        --python tools/blender/verify_game_rig_trial.py -- PACKET --store STORE
Reports sample playback and attribute retention, never semantic GG retarget.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import bpy
from mathutils import Matrix, Vector

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet")
    parser.add_argument("--store", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    from backend import game_workflow_common as common, game_workflow_dependencies as deps
    common.ROOT = Path(args.store).resolve()
    path, trial, _ = common.read_json(args.packet)
    if not path.is_relative_to(common.ROOT) or trial.get("schema") != "gg.game-workflow.rig-trial.v1":
        raise ValueError("INVALID_RIG_TRIAL_PACKET")

    def unchanged():
        for name, key in (("source", "source_hash"), ("clip", "clip_hash"), ("model_path", "trial_hash")):
            assert common.digest(common.read_file(trial[name])[1]) == trial[key], "Changed trial input"
        deps.fresh(trial["dependency_observation"])
    unchanged()
    # Independent raw-XML bind closure, using Blender's matrix library rather
    # than the converter's matrix or scene parser.
    xml = ET.fromstring(Path(trial["source"]).read_bytes())
    for element in xml.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    worlds, raw_aliases = {}, {}
    def matrix(text):
        a = [float(x) for x in text.split()]
        assert len(a) == 16
        return Matrix([a[i:i+4] for i in range(0, 16, 4)])
    def visit(node, parent=Matrix.Identity(4)):
        local = Matrix.Identity(4)
        for element in node:
            if element.tag == "matrix":
                local = local @ matrix(element.text)
            elif element.tag in ("rotate", "scale", "translate"):
                raise ValueError("BLENDER_XML_ORACLE_MATRIX_ONLY")
        world = parent @ local
        for key in ("id", "sid", "name"):
            if node.get(key):
                worlds[node.get(key)] = world
                raw_aliases[node.get(key)] = node.get("id")
        for child in node.findall("node"):
            visit(child, world)
    for scene in xml.findall("library_visual_scenes/visual_scene"):
        for node in scene.findall("node"):
            visit(node)
    max_error, joints = 0., 0
    for skin in xml.findall("library_controllers/controller/skin"):
        sources = {s.get("id"): s for s in skin.findall("source")}
        joint_input = skin.find("joints/input[@semantic='JOINT']")
        names = sources[joint_input.get("source").lstrip("#")].find("Name_array").text.split()
        inverse_input = skin.find("joints/input[@semantic='INV_BIND_MATRIX']")
        values = [float(x) for x in sources[inverse_input.get("source").lstrip("#")].find("float_array").text.split()]
        for i, name in enumerate(names):
            inverse = Matrix([values[i*16+j:i*16+j+4] for j in range(0, 16, 4)])
            closure = worlds[name] @ inverse
            max_error = max(max_error, max(abs(closure[r][c] - (r == c)) for r in range(4) for c in range(4)))
            joints += 1
    assert max_error < 1e-3, ("Independent bind closure", max_error)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.fps = round(trial["fps"])
    scene.render.fps_base = scene.render.fps / trial["fps"]
    bpy.ops.import_scene.gltf(filepath=trial["model_path"], merge_vertices=False, import_pack_images=True)
    imported_meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    originals = [obj for obj in imported_meshes if any(m.type == "ARMATURE" for m in obj.modifiers)]
    # Blender creates a bone-display Icosphere. It is not source geometry.
    for helper in (obj for obj in imported_meshes if obj not in originals):
        helper.hide_render = True
        helper.hide_set(True)
    rigs = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    actions = [obj.animation_data.action for obj in rigs if obj.animation_data and obj.animation_data.action]
    assert originals and rigs and actions, "Missing mesh/rig/animation after independent import"
    first = min(a.frame_range[0] for a in actions)
    last = max(a.frame_range[1] for a in actions)
    positions, observations, copies = [], [], []
    for label, frame in (("BIND", first), ("FIRST", first), ("MIDDLE", (first + last) / 2), ("LAST", last)):
        for rig in rigs:
            rig.data.pose_position = "REST" if label == "BIND" else "POSE"
        scene.frame_set(int(frame), subframe=frame - int(frame))
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        points, triangles, uv_loops, groups, sample_objects = [], 0, 0, {}, []
        for obj in originals:
            evaluated = obj.evaluated_get(graph)
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
            mesh.calc_loop_triangles()
            triangles += len(mesh.loop_triangles)
            uv_loops += sum(len(layer.data) for layer in mesh.uv_layers)
            for triangle in mesh.loop_triangles:
                material = mesh.materials[triangle.material_index].name if mesh.materials else "none"
                groups[material] = groups.get(material, 0) + 1
            copy = bpy.data.objects.new(label + "_" + obj.name, mesh)
            scene.collection.objects.link(copy)
            copy.matrix_world = obj.matrix_world.copy()
            sample_objects.append(copy)
            points.extend(copy.matrix_world @ v.co for v in mesh.vertices)
        assert triangles == trial["preservation"]["triangles"], (label, triangles, "Topology changed")
        positions.append(points)
        observations.append({"pose": label, "frame": frame, "triangles": triangles, "uv_loops": uv_loops,
                             "triangles_by_material": groups, "vertices": len(points)})
        copies.append(sample_objects)
    for obj in originals + rigs:
        obj.hide_render = True
        obj.hide_set(True)
    # Normalize all four snapshots by the bind bounds, preserving their relative
    # deformation and scale. This normalization is only for the study image.
    low = Vector(tuple(min(p[a] for p in positions[0]) for a in range(3)))
    high = Vector(tuple(max(p[a] for p in positions[0]) for a in range(3)))
    center, scale = (low + high) / 2, 2.4 / max(high - low)
    for i, objects in enumerate(copies):
        offset = Vector(((-1 if i % 2 == 0 else 1) * 1.6, 0, (1 if i < 2 else -1) * 1.55))
        transform = Matrix.Translation(offset) @ Matrix.Diagonal((scale, scale, scale, 1)) @ Matrix.Translation(-center)
        for obj in objects:
            obj.matrix_world = transform @ obj.matrix_world
        text_data = bpy.data.curves.new("label", "FONT")
        text_data.body = observations[i]["pose"]
        text_data.align_x = "CENTER"
        text_data.size = .18
        text = bpy.data.objects.new("label", text_data)
        scene.collection.objects.link(text)
        text.location = (offset.x, -.6, offset.z - 1.35)
        text.rotation_euler = (1.57079632679, 0, 0)
    camera_data = bpy.data.cameras.new("study-camera")
    camera = bpy.data.objects.new("study-camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0, -10, .1)
    camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 6.8
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.world.color = (.04, .04, .04)
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    name = "rig-review-" + trial["trial_hash"][:24]
    import tempfile
    with tempfile.TemporaryDirectory(prefix="gg-rig-review-") as temporary:
        rendered = Path(temporary) / "review.png"
        scene.render.filepath = str(rendered)
        bpy.ops.render.render(write_still=True)
        image = common.artifact(name, rendered.read_bytes())
    delta = max((a - b).length for a, b in zip(positions[1], positions[2]))
    assert delta > 1e-5, "Animation samples did not change geometry"
    unchanged()
    report = {"schema": "gg.game-workflow.rig-review.v1", "status": "SAMPLE_VERIFIED",
              "trial": str(path), "trial_hash": trial["trial_hash"], "blender_version": bpy.app.version_string,
              "independent_bind_max_matrix_error": max_error, "independent_bind_joints": joints,
              "poses": observations, "first_middle_max_vertex_displacement": delta,
              "image": str(image), "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
              "limits": ["Four controlled samples and independent bind closure; not all-frame/native-game or semantic retarget verification.",
                         "Caller FPS/basis remain trial parameters. Source materials/topology retained; Workbench texture preview does not certify original shading."]}
    packet = common.packet("rig-review", report)
    print("RIG_REVIEW=" + json.dumps({"status": report["status"], "packet": str(packet), "image": str(image), "poses": observations, "pose_change": delta}))


if __name__ == "__main__":
    main()
