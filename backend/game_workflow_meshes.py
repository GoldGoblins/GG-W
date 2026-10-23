"""Bounded exported-mesh readers. No welding, face removal or rig inference."""
from __future__ import annotations

from collections import Counter
import math
import re
import shlex
import struct
import xml.etree.ElementTree as ET

MAX_VERTICES = 200_000
MAX_CORNERS = 600_000
MAX_VALUES = 2_000_000
MAX_JOINTS = 256
MAX_FRAMES = 4096


def numbers(text, integer=False):
    words = (text or "").split()
    if len(words) > MAX_VALUES:
        raise ValueError("MESH_ARRAY_LIMIT")
    values = [int(x) if integer else float(x) for x in words]
    if not integer and any(not math.isfinite(x) for x in values):
        raise ValueError("MESH_NON_FINITE")
    return values


def obj(data: bytes, *, full=False):
    vertices, uvs, normals, faces, materials, libraries = [], [], [], [], [], []
    material = "default"
    for line in data.decode("utf-8-sig", "strict").splitlines():
        if len(line) > 65536:
            raise ValueError("OBJ_LINE_LIMIT")
        words = line.partition("#")[0].split()
        if not words:
            continue
        tag = words[0]
        if tag in ("v", "vt", "vn"):
            array, dimension = {"v": (vertices, 3), "vt": (uvs, 2), "vn": (normals, 3)}[tag]
            record = numbers(" ".join(words[1:]))
            if len(record) < dimension or len(array) >= MAX_VERTICES:
                raise ValueError("OBJ_VERTEX_LIMIT_OR_DIMENSION")
            array.append(record[:dimension])
        elif tag == "usemtl":
            material = " ".join(words[1:])[:256]
            if material not in materials:
                materials.append(material)
            if len(materials) > 256:
                raise ValueError("OBJ_MATERIAL_LIMIT")
        elif tag == "mtllib":
            libraries.extend(shlex.split(line.partition(" ")[2], posix=True))
            if len(libraries) > 128:
                raise ValueError("OBJ_LIBRARY_LIMIT")
        elif tag == "f":
            if len(words) < 4 or len(words) > 257:
                raise ValueError("OBJ_FACE_DIMENSION")
            corners = []
            for word in words[1:]:
                parts = word.split("/")
                if len(parts) > 3:
                    raise ValueError("OBJ_CORNER_INVALID")
                indices = []
                for part, array in zip(parts + [""] * (3 - len(parts)), (vertices, uvs, normals)):
                    if not part:
                        indices.append(None)
                        continue
                    index = int(part)
                    index = index - 1 if index > 0 else len(array) + index if index < 0 else -1
                    if not 0 <= index < len(array):
                        raise ValueError("OBJ_INDEX_OUT_OF_RANGE")
                    indices.append(index)
                if indices[0] is None:
                    raise ValueError("OBJ_POSITION_REQUIRED")
                corners.append(indices)
            faces.append((material, corners))
            if len(faces) > MAX_CORNERS // 3:
                raise ValueError("OBJ_FACE_LIMIT")
    if sum(len(c) for _, c in faces) > MAX_CORNERS:
        raise ValueError("OBJ_CORNER_LIMIT")
    by_index, by_position, layers, counts = Counter(), Counter(), {}, Counter()
    for mat, corners in faces:
        ids = tuple(sorted(c[0] for c in corners))
        geometry = tuple(sorted(tuple(vertices[c[0]]) for c in corners))
        by_index[ids] += 1
        by_position[geometry] += 1
        layers.setdefault(geometry, set()).add(mat)
        counts[mat] += len(corners) - 2
    metadata = {"vertices": len(vertices), "uv_records": len(uvs), "normal_records": len(normals),
                "faces": len(faces), "triangles": sum(counts.values()), "materials": len(counts),
                "triangles_by_material": dict(counts), "names": list(counts),
                "duplicate_position_index_faces": sum(v - 1 for v in by_index.values()),
                "geometric_coincident_faces": sum(v - 1 for v in by_position.values()),
                "coincident_material_layers": sum(len(v) > 1 for v in layers.values()),
                "external_resources": libraries, "rig": "NOT_ENCODED_BY_OBJ"}
    result = {"format": "OBJ", "kind": "model", "coverage": "EXPORTED_TOPOLOGY",
              "metadata": metadata, "limits": ["Coincident faces are observations, never cleanup instructions. Polygon triangulation and shaders need visual review."]}
    if full:
        result["geometry"] = {"vertices": vertices, "uvs": uvs, "normals": normals, "faces": faces}
    return result


def xml(data):
    if len(data) > 8 * 1024 * 1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DAE_XML_LIMIT_OR_DTD")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("DAE_XML_INVALID") from exc
    stack = [(root, 0)]
    count = 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > 100_000 or depth > 128:
            raise ValueError("DAE_STRUCTURE_LIMIT")
        element.tag = element.tag.rsplit("}", 1)[-1]
        stack.extend((c, depth + 1) for c in element)
    if root.tag != "COLLADA":
        raise ValueError("DAE_ROOT_INVALID")
    return root


def sources(parent, issues):
    result = {}
    for source in parent.findall("source"):
        accessor = source.find("technique_common/accessor")
        arrays = [c for c in source if c.tag in ("float_array", "Name_array", "IDREF_array")]
        if accessor is None or len(arrays) != 1:
            raise ValueError("DAE_SOURCE_UNSUPPORTED")
        array = arrays[0]
        values = numbers(array.text) if array.tag == "float_array" else (array.text or "").split()
        if len(values) > MAX_VALUES:
            raise ValueError("DAE_ARRAY_COUNT")
        stride, offset, count = (int(accessor.get(k, str(d))) for k, d in (("stride", 1), ("offset", 0), ("count", 0)))
        if not 1 <= stride <= 16 or offset < 0 or offset > len(values) or not 0 <= count <= MAX_VERTICES:
            raise ValueError("DAE_ACCESSOR_RANGE")
        available = (len(values) - offset) // stride
        if len(values) != int(array.get("count", "0")) or count > available:
            issues.append({"source": source.get("id"), "declared_values": int(array.get("count", "0")),
                           "actual_values": len(values), "declared_records": count, "available_records": available})
            # Exporters sometimes leave stale counts. Only actual complete
            # records are exposed; every use is subsequently checked in range.
            count = min(count, available)
        result[source.get("id")] = [values[offset + i * stride:offset + (i + 1) * stride] for i in range(count)]
    return result


def dae(data: bytes, *, full=False):
    root = xml(data)
    geometries, controllers, nodes, names, issues = [], [], [], [], []
    for geometry in root.findall("library_geometries/geometry"):
        mesh = geometry.find("mesh")
        if mesh is None:
            raise ValueError("DAE_NON_MESH_GEOMETRY")
        arrays = sources(mesh, issues)
        vertex_refs = {v.get("id"): {i.get("semantic"): i.get("source", "").lstrip("#") for i in v.findall("input")}
                       for v in mesh.findall("vertices")}
        groups = []
        for primitive in mesh:
            if primitive.tag not in ("triangles", "polylist", "polygons", "lines", "trifans", "tristrips"):
                continue
            if primitive.tag != "triangles":
                raise ValueError("DAE_PRIMITIVE_REQUIRES_ADAPTER:" + primitive.tag)
            inputs = []
            for i in primitive.findall("input"):
                semantic, source = i.get("semantic"), i.get("source", "").lstrip("#")
                offset, channel = int(i.get("offset", "0")), int(i.get("set", "0"))
                if semantic == "VERTEX":
                    inputs.extend((s, ref, offset, channel) for s, ref in vertex_refs[source].items())
                else:
                    inputs.append((semantic, source, offset, channel))
            stride = 1 + max((i[2] for i in inputs), default=-1)
            count = int(primitive.get("count", "0"))
            if not 1 <= stride <= 16 or not 0 <= count * 3 <= MAX_CORNERS:
                raise ValueError("DAE_PRIMITIVE_LIMIT")
            indices = numbers(" ".join(p.text or "" for p in primitive.findall("p")), True)
            if len(indices) != count * 3 * stride:
                raise ValueError("DAE_TRIANGLE_COUNT")
            for _, source, offset, _ in inputs:
                if source not in arrays or any(not 0 <= k < len(arrays[source]) for k in indices[offset::stride]):
                    raise ValueError("DAE_INDEX_OUT_OF_RANGE")
            groups.append({"material": primitive.get("material", ""), "inputs": inputs, "stride": stride, "indices": indices, "triangles": count})
        if sum(g["triangles"] * 3 for g in groups) > MAX_CORNERS:
            raise ValueError("DAE_CORNER_LIMIT")
        geometries.append({"id": geometry.get("id"), "sources": arrays, "groups": groups})
    for controller in root.findall("library_controllers/controller"):
        skin = controller.find("skin")
        if skin is None:
            raise ValueError("DAE_CONTROLLER_REQUIRES_ADAPTER")
        arrays = sources(skin, issues)
        joint_inputs = {i.get("semantic"): i.get("source", "").lstrip("#") for i in skin.findall("joints/input")}
        joint_names = [r[0] for r in arrays[joint_inputs["JOINT"]]]
        inverse_bind = arrays[joint_inputs["INV_BIND_MATRIX"]]
        if len(joint_names) > MAX_JOINTS or len(set(joint_names)) != len(joint_names) or len(inverse_bind) != len(joint_names) or any(len(r) != 16 for r in inverse_bind):
            raise ValueError("DAE_JOINT_LIMIT_OR_BIND_COUNT")
        weights = skin.find("vertex_weights")
        if weights is None:
            raise ValueError("DAE_VERTEX_WEIGHTS_REQUIRED")
        inputs = {i.get("semantic"): (i.get("source", "").lstrip("#"), int(i.get("offset", "0"))) for i in weights.findall("input")}
        stride = 1 + max((offset for _, offset in inputs.values()), default=-1)
        counts = numbers(weights.findtext("vcount"), True)
        values = numbers(weights.findtext("v"), True)
        if len(counts) != int(weights.get("count", "0")) or len(counts) > MAX_VERTICES or any(not 0 <= c <= 32 for c in counts) or len(values) != sum(counts) * stride:
            raise ValueError("DAE_WEIGHT_COUNT")
        if not 1 <= stride <= 16 or inputs["JOINT"][0] != joint_inputs["JOINT"]:
            raise ValueError("DAE_WEIGHT_INPUT")
        weight_values = arrays[inputs["WEIGHT"][0]]
        influences, cursor = [], 0
        for count in counts:
            row = []
            for i in range(count):
                j, w = values[cursor + i * stride + inputs["JOINT"][1]], values[cursor + i * stride + inputs["WEIGHT"][1]]
                if not 0 <= j < len(joint_names) or not 0 <= w < len(weight_values) or weight_values[w][0] < 0:
                    raise ValueError("DAE_WEIGHT_RANGE")
                row.append([j, weight_values[w][0]])
            influences.append(row)
            cursor += count * stride
        bind_shape = numbers(skin.findtext("bind_shape_matrix", "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"))
        if len(bind_shape) != 16:
            raise ValueError("DAE_BIND_SHAPE_MATRIX")
        controllers.append({"id": controller.get("id"), "geometry": skin.get("source", "").lstrip("#"), "joints": joint_names,
                            "inverse_bind": inverse_bind, "bind_shape": bind_shape, "weights": influences})
    scenes = root.findall("library_visual_scenes/visual_scene")
    for scene in scenes:
        stack = [(c, None) for c in reversed(scene.findall("node"))]
        while stack:
            node, parent = stack.pop()
            identity = len(nodes)
            transforms = [(c.tag, numbers(c.text)) for c in node if c.tag in ("matrix", "translate", "rotate", "scale")]
            aliases = list(dict.fromkeys(node.get(k) for k in ("id", "name", "sid") if node.get(k)))
            instances = [{"kind": c.tag, "target": c.get("url", "").lstrip("#")}
                         for c in node if c.tag in ("instance_controller", "instance_geometry")]
            nodes.append({"aliases": aliases, "parent": parent, "joint": node.get("type") == "JOINT",
                          "transforms": transforms, "instances": instances})
            names.extend(aliases)
            stack.extend((c, identity) for c in reversed(node.findall("node")))
    if len(nodes) > 4096 or len(controllers) > 64 or len(geometries) > 64:
        raise ValueError("DAE_COLLECTION_LIMIT")
    unit = root.find("asset/unit")
    scale = float(unit.get("meter", "1")) if unit is not None else None
    if scale is not None and (not math.isfinite(scale) or scale <= 0):
        raise ValueError("DAE_UNIT_INVALID")
    resources = [e.text.strip() for e in root.findall("library_images/image/init_from") if e.text]
    metadata = {"geometries": len(geometries), "triangles": sum(g["triangles"] for m in geometries for g in m["groups"]),
                "materials": len(root.findall("library_materials/material")), "skin_controllers": len(controllers),
                "joint_counts": [len(c["joints"]) for c in controllers],
                "weight_profiles": [{"vertices": len(c["weights"]), "max_influences": max(map(len, c["weights"]), default=0),
                                     "histogram": dict(Counter(map(len, c["weights"]))),
                                     "max_sum_error": max((abs(sum(w for _, w in r) - 1) for r in c["weights"]), default=0)} for c in controllers],
                "up_axis": root.findtext("asset/up_axis", "UNDECLARED"), "meters_per_unit": scale,
                "animation_channels": len(root.findall(".//animation/channel")), "names": list(dict.fromkeys(names))[:1024],
                "joint_aliases": [n["aliases"] for n in nodes if n["joint"]], "external_resources": resources,
                "export_array_count_issues": issues}
    result = {"format": "COLLADA_DAE", "kind": "model", "coverage": "EXPORTED_TOPOLOGY_SKIN_METADATA",
              "metadata": metadata, "limits": ["id/name/sid aliases are preserved. Exported units do not establish original game scale. DAE/SMD playback needs explicit FPS and basis review."]}
    if full:
        effects = {e.get("id"): e for e in root.findall("library_effects/effect")}
        image_names = {e.get("id"): e.findtext("init_from", "") for e in root.findall("library_images/image")}
        material_rows = []
        for material in root.findall("library_materials/material"):
            instance = material.find("instance_effect")
            effect = effects.get(instance.get("url", "").lstrip("#")) if instance is not None else None
            diffuse = effect.find(".//diffuse") if effect is not None else None
            color = numbers(diffuse.findtext("color")) if diffuse is not None and diffuse.find("color") is not None else [1, 1, 1, 1]
            uri = None
            if diffuse is not None and diffuse.find("texture") is not None:
                params = {p.get("sid"): p for p in effect.findall(".//newparam")}
                sampler = params.get(diffuse.find("texture").get("texture"))
                surface = params.get(sampler.findtext("sampler2D/source")) if sampler is not None else None
                uri = image_names.get(surface.findtext("surface/init_from")) if surface is not None else None
            material_rows.append({"id": material.get("id"), "name": material.get("name", material.get("id")),
                                  "color": color, "texture": uri,
                                  "effect": ET.tostring(effect, encoding="unicode") if effect is not None else ""})
        bindings = {}
        for binding in root.findall(".//instance_material"):
            symbol, target = binding.get("symbol"), binding.get("target", "").lstrip("#")
            if symbol in bindings and bindings[symbol] != target:
                raise ValueError("DAE_MATERIAL_INSTANCE_VARIANTS_REQUIRE_ADAPTER")
            bindings[symbol] = target
        result["scene"] = {"geometries": geometries, "controllers": controllers, "nodes": nodes,
                           "materials": material_rows, "material_bindings": bindings}
    return result


def smd(data: bytes, *, full=False):
    nodes, frames, state, current = {}, {}, "", None
    for line in data.decode("utf-8-sig", "strict").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line in ("nodes", "skeleton", "triangles", "vertexanimation", "end"):
            state = "" if line == "end" else line
            if state in ("triangles", "vertexanimation"):
                raise ValueError("SMD_ANIMATION_ADAPTER_ONLY")
        elif state == "nodes":
            m = re.fullmatch(r'(-?\d+)\s+"([^"\x00]{1,256})"\s+(-?\d+)', line)
            if not m or len(nodes) >= MAX_JOINTS or int(m[1]) in nodes:
                raise ValueError("SMD_NODE_INVALID")
            nodes[int(m[1])] = {"name": m[2], "parent": int(m[3])}
        elif state == "skeleton":
            if line.startswith("time "):
                current = int(line.split()[1])
                if current < 0 or current in frames or len(frames) >= MAX_FRAMES:
                    raise ValueError("SMD_FRAME_INVALID")
                frames[current] = {}
            else:
                words = line.split()
                if len(words) != 7 or current is None:
                    raise ValueError("SMD_POSE_INVALID")
                identity = int(words[0])
                if identity not in nodes or identity in frames[current]:
                    raise ValueError("SMD_POSE_NODE_INVALID")
                frames[current][identity] = numbers(" ".join(words[1:]))
        elif not line.startswith("version 1"):
            raise ValueError("SMD_UNSUPPORTED_SECTION")
    for identity, node in nodes.items():
        seen, parent = {identity}, node["parent"]
        while parent != -1:
            if parent not in nodes or parent in seen:
                raise ValueError("SMD_PARENT_CYCLE_OR_MISSING")
            seen.add(parent)
            parent = nodes[parent]["parent"]
    if not nodes or not frames or len({row["name"] for row in nodes.values()}) != len(nodes):
        raise ValueError("SMD_NODES_AND_FRAMES_REQUIRED")
    result = {"format": "SMD_ANIMATION", "kind": "animation", "coverage": "SKELETON_POSE_SAMPLES",
              "metadata": {"nodes": len(nodes), "time_samples": len(frames), "first_sample": min(frames), "last_sample": max(frames),
                           "names": [n["name"] for n in nodes.values()], "fps": "UNDECLARED", "rotation": "EULER_XYZ_RADIANS"},
              "limits": ["Times are sample indices. FPS and the relation to the mesh bind pose must be supplied/checked separately."]}
    if full:
        result.update(nodes=nodes, frames=frames)
    return result


def ggmesh(data: bytes):
    if len(data) < 20:
        raise ValueError("GGMESH_HEADER_TRUNCATED")
    magic, stride, vertices, indices = struct.unpack_from("<8sIII", data)
    if magic != b"GGFLORA1" or stride != 40 or not 0 < vertices <= MAX_VERTICES or not 0 < indices <= MAX_CORNERS or indices % 3 or len(data) != 20 + vertices * stride + indices * 4:
        raise ValueError("GGMESH_LAYOUT_INVALID")
    bounds = [[math.inf, -math.inf] for _ in range(3)]
    for i in range(vertices):
        record = struct.unpack_from("<10f", data, 20 + i * stride)
        if any(not math.isfinite(x) for x in record):
            raise ValueError("GGMESH_NON_FINITE")
        for axis in range(3):
            bounds[axis][0] = min(bounds[axis][0], record[axis])
            bounds[axis][1] = max(bounds[axis][1], record[axis])
    if any(i[0] >= vertices for i in struct.iter_unpack("<I", data[20 + vertices * stride:])):
        raise ValueError("GGMESH_INDEX_OUT_OF_RANGE")
    return {"format": "GGFLORA1", "kind": "model", "coverage": "VERTEX_INDEX_LAYOUT",
            "metadata": {"vertices": vertices, "indices": indices, "triangles": indices // 3, "stride": stride,
                         "attributes": ["POSITION", "NORMAL", "COLOR_0"], "local_bounds": bounds,
                         "skin": "NOT_ENCODED_BY_GGFLORA1", "names": []},
            "limits": ["GG compiled mesh layout, not a PS2 game decoder; no implicit rig, UV or texture."]}
