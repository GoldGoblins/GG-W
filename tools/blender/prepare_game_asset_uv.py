"""Prepare one static glTF asset for painting, without changing its geometry.

Called by the local asset editor in a bounded Blender child process. The only
durable output is one GLB with packed UV islands and an embedded colour atlas.
Source files and mesh faces are preserved. Temporary pixels live in RAM.
"""
import json
import math
import sys
from pathlib import Path

import bpy


def progress(stage, percent):
    print("GGUV " + json.dumps({"stage": stage, "percent": percent}), flush=True)


def prepare(source, destination):
    progress("Läser modell och befintliga material", 5)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes or any(obj.type == "ARMATURE" for obj in bpy.context.scene.objects):
        raise ValueError("UV-förberedelsen gäller statiska modeller. Riggade modeller behåller sin befintliga UV och rigg.")
    original_faces = sum(len(obj.data.polygons) for obj in meshes)
    materials = list(dict.fromkeys(mat for obj in meshes for mat in obj.data.materials if mat))
    if any(obj.data.shape_keys for obj in meshes):
        raise ValueError("Modeller med formnycklar behöver sin befintliga UV-layout.")
    # Explicit source coordinates keep texture sampling unchanged while the
    # active destination layer is unwrapped. No geometry operation is used.
    for obj in meshes:
        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name="OriginalUV")
        old_name = obj.data.uv_layers.active.name
        for mat in obj.data.materials:
            if not mat or not mat.use_nodes:
                continue
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            uv = nodes.new("ShaderNodeUVMap"); uv.uv_map = old_name
            for node in list(nodes):
                if node.type == "TEX_IMAGE" and not node.inputs["Vector"].is_linked:
                    links.new(uv.outputs["UV"], node.inputs["Vector"])
        target = obj.data.uv_layers.new(name="PaintUV")
        obj.data.uv_layers.active = target
        target.active_render = True
    progress("Skapar separata UV-öar och packar kartan", 25)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0,
                             area_weight=1, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, scale=True, merge_overlap=False,
                            margin_method="FRACTION", margin=12/1024)
    bpy.ops.object.mode_set(mode="OBJECT")
    atlas = bpy.data.images.new("Paint atlas", width=1024, height=1024, alpha=False)
    atlas.generated_color = (.08, .08, .08, 1)
    atlas.colorspace_settings.name = "sRGB"
    outputs = {}
    for mat in materials:
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        shader = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        output = next((n for n in nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if shader is None or output is None:
            raise ValueError("Materialet saknar en stödd färgkanal: " + mat.name)
        # Preserve material appearance; bake colour only, with no scene light.
        source_input = shader.inputs["Base Color"]
        emission = nodes.new("ShaderNodeEmission")
        if source_input.is_linked:
            links.new(source_input.links[0].from_socket, emission.inputs["Color"])
        else:
            emission.inputs["Color"].default_value = source_input.default_value
        old_surface = output.inputs["Surface"].links[0].from_socket if output.inputs["Surface"].is_linked else shader.outputs[0]
        outputs[mat] = (shader, output, old_surface, emission)
        links.new(emission.outputs[0], output.inputs["Surface"])
        image_node = nodes.new("ShaderNodeTexImage"); image_node.image = atlas
        nodes.active = image_node
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"; scene.cycles.samples = 1
    scene.render.bake.margin = 4; scene.render.bake.use_clear = False
    scene.render.bake.use_selected_to_active = False
    progress("Överför befintliga färger till UV-atlasen", 55)
    bpy.ops.object.bake(type="EMIT")
    progress("Kopplar målningsbar textur till modellen", 85)
    for mat, (shader, output, old_surface, emission) in outputs.items():
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        links.new(old_surface, output.inputs["Surface"])
        nodes.remove(emission)
        uv = nodes.new("ShaderNodeUVMap"); uv.uv_map = "PaintUV"
        image_node = nodes.new("ShaderNodeTexImage"); image_node.image = atlas
        image_node.extension = "EXTEND"
        links.new(uv.outputs["UV"], image_node.inputs["Vector"])
        links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
    atlas.pack()
    # Imported vertex colours have already contributed to the colour bake.
    # Exporting COLOR_0 as well would multiply those colours a second time.
    for obj in meshes:
        for attribute in list(obj.data.color_attributes):
            obj.data.color_attributes.remove(attribute)
    if sum(len(obj.data.polygons) for obj in meshes) != original_faces:
        raise ValueError("UV-arbetet ändrade geometri; exporten avbröts.")
    bpy.ops.export_scene.gltf(filepath=str(destination), export_format="GLB",
                              use_selection=False, export_animations=False,
                              export_extras=True, export_image_format="AUTO")
    progress("UV-atlasen är klar", 100)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--")+1:]
    try:
        prepare(Path(args[0]), Path(args[1]))
    except Exception as exc:
        print("GGUV " + json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)
