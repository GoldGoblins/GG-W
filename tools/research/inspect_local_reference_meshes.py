"""Run in Blender with --factory-startup --disable-autoexec.

Independently import six OBJ references, cross-check exported triangle counts,
and render normalized diagnostic geometry. Source art is never saved/exported.
"""
from pathlib import Path
import json
import math
import sys

import bpy
from mathutils import Vector

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "tools/research"))
from study_local_game_assets import ASSETS, obj_facts, digest

OUTPUT = PROJECT / "docs/local-asset-study-2026-10-10"
REFERENCES = ASSETS / "authored/concept/refs/ps2-models"
STUDIES = [
    ("Crash PS1 export", "crash-ps1/crashbandicoot.obj", 0),
    ("Crash WOC export", "crash-woc/crash.obj", 0),
    ("Daxter export", "daxter/Daxter.obj", 0),
    ("Ratchet RC1 export", "ratchet-rc1/Ratchet/Ratchet.obj", 270),
    ("Jak PL appearance export", "jak-pl/JDJak/jak.obj", 0),
    ("Vexx export", "vexx/Vexx/Vexx.obj", 0),
]


def material(name, colour):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*colour, 1)
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*colour, 1)
    shader.inputs["Roughness"].default_value = .9
    return value


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    neutral = material("Diagnostic neutral surface", (.40, .61, .66))
    nodes = neutral.node_tree.nodes
    wire = nodes.new("ShaderNodeWireframe"); wire.use_pixel_size = True
    wire.inputs["Size"].default_value = .65
    mix = nodes.new("ShaderNodeMixRGB")
    mix.inputs[1].default_value = (.4, .61, .66, 1)
    mix.inputs[2].default_value = (.035, .045, .05, 1)
    neutral.node_tree.links.new(wire.outputs["Fac"], mix.inputs[0])
    neutral.node_tree.links.new(mix.outputs[0], nodes.get("Principled BSDF").inputs["Base Color"])
    text_material = material("Diagnostic labels", (.8, .87, .89))
    records = []
    for index, (label, relative, yaw) in enumerate(STUDIES):
        path = REFERENCES / relative
        before = digest(path)
        expected = obj_facts(path)
        cleanup_probe = None
        if relative == "daxter/Daxter.obj":
            old = set(bpy.context.scene.objects)
            bpy.ops.wm.obj_import(filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y", validate_meshes=True)
            cleaned = [o for o in bpy.context.scene.objects if o not in old and o.type == "MESH"]
            validated_triangles = 0
            for obj in cleaned:
                obj.data.calc_loop_triangles()
                validated_triangles += len(obj.data.loop_triangles)
                bpy.data.objects.remove(obj, do_unlink=True)
            removed = expected["triangles_after_fan_triangulation"] - validated_triangles
            assert removed == expected["duplicate_position_index_faces"], (removed, expected)
            cleanup_probe = {"validate_meshes": True, "blender_triangles": validated_triangles,
                             "removed_source_triangles": removed}
        existing = set(bpy.context.scene.objects)
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y", validate_meshes=False)
        objects = [o for o in bpy.context.scene.objects if o not in existing and o.type == "MESH"]
        triangles = 0
        for obj in objects:
            obj.data.calc_loop_triangles()
            triangles += len(obj.data.loop_triangles)
        assert triangles == expected["triangles_after_fan_triangulation"], (label, triangles, expected)
        points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
        low = Vector([min(v[i] for v in points) for i in range(3)])
        high = Vector([max(v[i] for v in points) for i in range(3)])
        scale = 2.1 / (high.z - low.z)
        centre = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
        root = bpy.data.objects.new(label, None)
        bpy.context.scene.collection.objects.link(root)
        root.rotation_euler.z = math.radians(yaw + 18)
        root.location = (index % 3 * 3.1, 0, -(index // 3) * 3.1)
        for obj in objects:
            world = obj.matrix_world.copy()
            world.translation = (world.translation - centre) * scale
            for column in range(3):
                world.col[column] *= scale
            obj.parent = root
            obj.matrix_parent_inverse.identity()
            obj.matrix_basis = world
            obj.data.materials.clear(); obj.data.materials.append(neutral)
            for polygon in obj.data.polygons:
                polygon.material_index = 0
        curve = bpy.data.curves.new("Label", "FONT")
        curve.body = f"{label}\n{triangles:,} triangles | {expected['used_materials']} materials"
        curve.align_x = "CENTER"; curve.size = .135
        text = bpy.data.objects.new("Label " + label, curve)
        bpy.context.scene.collection.objects.link(text)
        text.location = (root.location.x, -.2, root.location.z - .22)
        text.rotation_euler.x = math.pi / 2
        curve.materials.append(text_material)
        assert digest(path) == before
        records.append({"source": path.relative_to(ASSETS).as_posix(), "blender_triangle_count": triangles,
            "independent_obj_count": expected["triangles_after_fan_triangulation"], "source_bytes_unchanged": True,
            "original_materials_used": expected["used_materials"], "exported_vertices": expected["vertices"],
            "validate_meshes": False,
            "duplicate_position_index_faces": expected["duplicate_position_index_faces"],
            "geometric_coincident_faces": expected["geometric_coincident_faces"],
            "default_cleanup_probe": cleanup_probe,
            "blender_vertex_records": sum(len(o.data.vertices) for o in objects), "view_yaw_degrees": yaw + 18})
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    scene.render.threads_mode = "FIXED"; scene.render.threads = 8
    scene.render.resolution_x = 1500; scene.render.resolution_y = 1050
    scene.render.resolution_percentage = 100
    scene.world.color = (.10, .12, .14)
    for location, energy, size in [((0, -5, 7), 1600, 8), ((8, -2, 3), 950, 6)]:
        light = bpy.data.lights.new("Diagnostic light", "AREA")
        light.energy = energy; light.shape = "DISK"; light.size = size
        obj = bpy.data.objects.new("Diagnostic light", light)
        scene.collection.objects.link(obj); obj.location = location
        obj.rotation_euler = (Vector((3.1, 0, -.5)) - obj.location).to_track_quat("-Z", "Y").to_euler()
    camera = bpy.data.cameras.new("Diagnostic camera"); camera.type = "ORTHO"; camera.ortho_scale = 9.6
    obj = bpy.data.objects.new("Diagnostic camera", camera)
    scene.collection.objects.link(obj); obj.location = (3.1, -15, -.5)
    obj.rotation_euler = (Vector((3.1, 0, -.5)) - obj.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = obj
    scene.render.filepath = str(OUTPUT / "mesh-study.png")
    bpy.ops.render.render(write_still=True)
    with (OUTPUT / "blender-verification.json").open("w") as stream:
        json.dump({"status": "PASS", "blender_version": bpy.app.version_string, "sources": records,
                   "visual_scope": "Uniform height, neutral materials and wire overlay; export references, not original game scale or animation."},
                  stream, ensure_ascii=False, indent=2)
    print("LOCAL_REFERENCE_BLENDER_CHECK=PASS")


if __name__ == "__main__":
    main()
