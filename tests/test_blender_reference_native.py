#!/usr/bin/env python3
"""Opt-in regressions in live Blender; original scene/data are restored.

Run with --live while EXT Blender is available. These are tool/state tests,
not visual similarity scores or artistic training examples.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.blender_contract import sidecar_call

SCRIPT = r'''
import bpy, bmesh, importlib, json, sys, uuid
from pathlib import Path
sys.path.insert(0, TOOL_FOLDER)
import gg_blender_reference, gg_blender_observe
modeling = importlib.reload(gg_blender_reference)
observe = importlib.reload(gg_blender_observe)
data_types = ("scenes", "objects", "meshes", "materials", "images", "cameras", "lights", "collections", "armatures", "actions", "worlds", "node_groups", "shape_keys")
before = {key: set(getattr(bpy.data, key).keys()) for key in data_types}
original_window = bpy.context.window or next(iter(bpy.context.window_manager.windows), None)
original_scene = original_window.scene if original_window else bpy.context.scene
original_shading = [(area.spaces.active, area.spaces.active.shading.type, area.spaces.active.shading.color_type)
                    for area in original_window.screen.areas if area.type == "VIEW_3D"] if original_window else []
passed = []
try:
    image = bpy.data.images.new("GG_Native_Test_Reference", width=8, height=8)
    image.pixels = [.5, .5, .5, 1] * 64
    image.filepath_raw = str(Path(TEST_FOLDER) / "ref.png")
    image.file_format = "PNG"
    image.save()
    job = "native_" + uuid.uuid4().hex[:12]
    refs = {view: {"path": image.filepath_raw} for view in modeling.VIEWS}
    workspace = modeling.setup(job, refs)
    scene = bpy.data.scenes[workspace["scene"]]
    group = bpy.data.collections[workspace["collection"]]
    def cube(name, collection):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj
    body = cube("GG_Native_Test_Model", group)
    sentinel = cube("GG_Native_Test_Unrelated", scene.collection)
    sentinel.scale = (10, 10, 10)
    scene.view_layers[0].update()
    previous_render = (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
                       scene.render.resolution_percentage, scene.render.filepath, scene.render.image_settings.file_format,
                       scene.render.film_transparent, scene.world, scene.display.shading.color_type)
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        first = observe.render_turnaround(str(Path(TEST_FOLDER) / "turn-one"), 256, collection=group.name,
                                         style="clay", orthographic=True)
        assert first["ok"], first
        assert first["targets"] == [body.name]
        assert sentinel.hide_render is False and body.hide_render is False
        body.scale.y = .75
        scene.view_layers[0].update()
        second = observe.render_turnaround(str(Path(TEST_FOLDER) / "turn-two"), 256, collection=group.name,
                                          style="silhouette", framing=first["framing"], orthographic=True)
        assert second["ok"] and second["framing"] == first["framing"]
        assert previous_render == (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
                                  scene.render.resolution_percentage, scene.render.filepath, scene.render.image_settings.file_format,
                                  scene.render.film_transparent, scene.world, scene.display.shading.color_type)
    passed += ["unrelated_objects_isolated", "visibility_render_settings_restored", "camera_framing_reused"]
    initial = modeling.fingerprint(job)["fingerprint"]
    assert initial == modeling.fingerprint(job)["fingerprint"]
    vertex_group = body.vertex_groups.new(name="TestWeight")
    vertex_group.add([0], .2, "REPLACE")
    weighted = modeling.fingerprint(job)["fingerprint"]
    assert weighted != initial
    vertex_group.add([0], .9, "REPLACE")
    assert modeling.fingerprint(job)["fingerprint"] != weighted
    passed.append("weight_changes_invalidate_capture")
    body.location.x = 0
    body.keyframe_insert(data_path="location", index=0, frame=1)
    body.location.x = 3
    body.keyframe_insert(data_path="location", index=0, frame=20)
    scene.frame_set(1)
    animated = modeling.fingerprint(job)["fingerprint"]
    body.location.x = 4
    body.keyframe_insert(data_path="location", index=0, frame=20)
    scene.frame_set(1)
    assert abs(body.location.x) < .00001
    assert modeling.fingerprint(job)["fingerprint"] != animated
    passed.append("future_keyframe_changes_invalidate_capture")
    body.shape_key_add(name="Basis")
    shape = body.shape_key_add(name="FutureShape")
    shape.value = 0
    shaped = modeling.fingerprint(job)["fingerprint"]
    shape.data[0].co.x += .2
    assert modeling.fingerprint(job)["fingerprint"] != shaped
    passed.append("inactive_shape_changes_invalidate_capture")
    material = bpy.data.materials.new("GG_Native_Test_Material")
    material.use_nodes = True
    body.data.materials.append(material)
    texture = bpy.data.images.new("GG_Native_Test_Texture", width=8, height=8)
    texture.pixels = [.5, .5, .5, 1] * 64
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = texture
    material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    textured = modeling.fingerprint(job)["fingerprint"]
    texture.pixels[0] = .1
    assert modeling.fingerprint(job)["fingerprint"] != textured
    passed.append("unsaved_texture_changes_invalidate_capture")
    rgb = material.node_tree.nodes.new("ShaderNodeRGB")
    material.node_tree.links.new(rgb.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    colored = modeling.fingerprint(job)["fingerprint"]
    rgb.outputs["Color"].default_value = (.3, .8, .1, 1)
    assert modeling.fingerprint(job)["fingerprint"] != colored
    passed.append("shader_output_changes_invalidate_capture")
    other = bpy.data.scenes.new("GG_Native_Test_Other_Scene")
    duplicate = bpy.data.objects.new("GG_Native_Test_Shared_Data", body.data)
    other.collection.objects.link(duplicate)
    try:
        modeling.fingerprint(job)
        raise AssertionError("Shared geometry escaped isolation guard")
    except ValueError as error:
        assert "independent" in str(error)
    bpy.data.objects.remove(duplicate, do_unlink=True)
    bpy.data.scenes.remove(other)
    scene.collection.objects.link(body)
    original_scene.collection.objects.link(body)
    try:
        modeling.fingerprint(job)
        raise AssertionError("Cross-scene object escaped isolation guard")
    except ValueError as error:
        assert "only" in str(error)
    original_scene.collection.objects.unlink(body)
    passed += ["shared_geometry_rejected", "cross_scene_objects_rejected"]
finally:
    if original_window:
        original_window.scene = original_scene
    for space, style, color in original_shading:
        space.shading.type, space.shading.color_type = style, color
    for key in ("objects", "scenes", *[name for name in data_types if name not in {"objects", "scenes"}]):
        collection = getattr(bpy.data, key)
        for name in set(collection.keys()) - before[key]:
            item = collection.get(name)
            if item is not None:
                if key in {"objects", "scenes"}:
                    collection.remove(item, do_unlink=True)
                elif item.users == 0:
                    collection.remove(item)
print(json.dumps({"ok": True, "passed": passed, "count": len(passed), "original_scene_restored":
                  not original_window or original_window.scene == original_scene}))
'''


def main() -> int:
    if sys.argv[1:] != ["--live"]:
        print("BLENDER_REFERENCE_NATIVE_TEST=SKIP (opt in with --live)")
        return 0
    with tempfile.TemporaryDirectory(prefix="gg-model-native-test-") as folder:
        source = SCRIPT.replace("TOOL_FOLDER", repr(str(PROJECT / "tools/blender"))).replace("TEST_FOLDER", repr(folder))
        result = sidecar_call("exec", code=source)
        if not result.get("ok"):
            print(json.dumps({key: result.get(key) for key in ("ok", "error", "message") if key in result}))
            return 1
        proof = json.loads(result["stdout"].strip().splitlines()[-1])
        print(json.dumps(proof, indent=2))
        return int(proof.get("count") != 10 or not proof.get("original_scene_restored"))


if __name__ == "__main__":
    raise SystemExit(main())
