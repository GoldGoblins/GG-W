"""Source-preserving DAE/SMD trials; semantic GG retargeting needs review."""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct

from backend import game_workflow_common as common, game_workflow_meshes as meshes
from backend import game_workflow_dependencies as deps, game_asset_resources as resources

IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
BASES = {"SMD_LOCAL", "SMD_ROOT_X90"}


def mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def transpose(a):
    return [a[r * 4 + c] for c in range(4) for r in range(4)]


def axis_rotation(axis, angle):
    length = math.sqrt(sum(x * x for x in axis))
    if length <= 1e-12:
        raise ValueError("ZERO_ROTATION_AXIS")
    x, y, z = [v / length for v in axis]
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return [t*x*x+c, t*x*y-s*z, t*x*z+s*y, 0,
            t*x*y+s*z, t*y*y+c, t*y*z-s*x, 0,
            t*x*z-s*y, t*y*z+s*x, t*z*z+c, 0, 0, 0, 0, 1]


def local_matrix(node):
    result = IDENTITY[:]
    for kind, values in node["transforms"]:
        if kind == "matrix" and len(values) == 16:
            matrix = values
        elif kind == "translate" and len(values) == 3:
            matrix = IDENTITY[:]
            matrix[3], matrix[7], matrix[11] = values
        elif kind == "scale" and len(values) == 3:
            matrix = IDENTITY[:]
            matrix[0], matrix[5], matrix[10] = values
        elif kind == "rotate" and len(values) == 4:
            matrix = axis_rotation(values[:3], math.radians(values[3]))
        else:
            raise ValueError("DAE_TRANSFORM_DIMENSION")
        result = mul(result, matrix)
    return result


def quaternion(matrix):
    # Row-major rotation matrix to glTF XYZW. Stable near 180 degrees.
    trace = matrix[0] + matrix[5] + matrix[10]
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [(matrix[9] - matrix[6]) / s, (matrix[2] - matrix[8]) / s, (matrix[4] - matrix[1]) / s, .25 * s]
    else:
        i = max(range(3), key=lambda j: matrix[j * 5])
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(max(0, 1 + matrix[i * 5] - matrix[j * 5] - matrix[k * 5])) * 2
        if s < 1e-12:
            raise ValueError("RIG_ROTATION_INVALID")
        q = [0., 0., 0., (matrix[k * 4 + j] - matrix[j * 4 + k]) / s]
        q[i] = .25 * s
        q[j] = (matrix[j * 4 + i] + matrix[i * 4 + j]) / s
        q[k] = (matrix[k * 4 + i] + matrix[i * 4 + k]) / s
    length = math.sqrt(sum(x * x for x in q))
    return [x / length for x in q]


def trs(matrix):
    scale = [math.sqrt(sum(matrix[r * 4 + c] ** 2 for r in range(3))) for c in range(3)]
    if min(scale) < 1e-12:
        raise ValueError("RIG_SINGULAR_SCALE")
    rotation = [matrix[r * 4 + c] / scale[c] if r < 3 and c < 3 else IDENTITY[r * 4 + c] for r in range(4) for c in range(4)]
    det = rotation[0]*(rotation[5]*rotation[10]-rotation[6]*rotation[9])-rotation[1]*(rotation[4]*rotation[10]-rotation[6]*rotation[8])+rotation[2]*(rotation[4]*rotation[9]-rotation[5]*rotation[8])
    if abs(det - 1) > 1e-5 or any(abs(sum(rotation[r*4+c] * rotation[r*4+d] for r in range(3)) - (c == d)) > 1e-5 for c in range(3) for d in range(3)):
        raise ValueError("RIG_SHEAR_OR_REFLECTION_REQUIRES_ADAPTER")
    return {"translation": [matrix[3], matrix[7], matrix[11]], "rotation": quaternion(rotation), "scale": scale}


def world_matrices(nodes, local):
    result = []
    for i, node in enumerate(nodes):
        parent = node["parent"]
        if parent is not None and not 0 <= parent < i:
            raise ValueError("RIG_PARENT_ORDER")
        result.append(mul(result[parent], local[i]) if parent is not None else local[i])
    return result


def aliases(nodes):
    result = {}
    for i, node in enumerate(nodes):
        for name in node["aliases"]:
            if name in result and result[name] != i:
                raise ValueError("AMBIGUOUS_JOINT_ALIAS:" + name)
            result[name] = i
    return result


def match(scene, animation):
    lookup = aliases(scene["nodes"])
    mapping = {identity: lookup[row["name"]] for identity, row in animation["nodes"].items() if row["name"] in lookup}
    for identity, index in mapping.items():
        parent = animation["nodes"][identity]["parent"]
        expected = mapping.get(parent)
        if parent != -1 and parent not in mapping:
            raise ValueError("SMD_UNMATCHED_PARENT")
        if scene["nodes"][index]["parent"] != expected:
            raise ValueError("SMD_DAE_PARENT_MISMATCH")
    required = {lookup[j] for skin in scene["controllers"] for j in skin["joints"]}
    if not required.issubset(set(mapping.values())):
        raise ValueError("SMD_MISSING_SKIN_JOINTS")
    extra = [row["name"] for i, row in animation["nodes"].items() if i not in mapping]
    if any(name != "blender_implicit" for name in extra):
        raise ValueError("SMD_UNMATCHED_NODES_REQUIRE_REVIEW")
    for identity, row in animation["nodes"].items():
        if identity not in mapping and (row["parent"] != -1 or any(any(abs(v) > 1e-6 for v in pose[identity]) for pose in animation["frames"].values() if identity in pose)):
            raise ValueError("SMD_UNMATCHED_HELPER_TRANSFORM_REQUIRES_REVIEW")
    return mapping, extra


def smd_matrix(pose, root=False, basis="SMD_LOCAL"):
    result = IDENTITY[:]
    # SMD stores XYZ Euler radians; matrix order is Rz Ry Rx.
    for axis, angle in zip(((0, 0, 1), (0, 1, 0), (1, 0, 0)), reversed(pose[3:])):
        result = mul(result, axis_rotation(axis, angle))
    result[3], result[7], result[11] = pose[:3]
    return mul(axis_rotation((1, 0, 0), math.pi / 2), result) if root and basis == "SMD_ROOT_X90" else result


class GLB:
    def __init__(self):
        self.data = bytearray()
        self.doc = {"asset": {"version": "2.0", "generator": "GG source-preserving rig trial"},
                    "nodes": [], "meshes": [], "skins": [], "materials": [], "bufferViews": [], "accessors": []}

    def view(self, data, target=None):
        self.data.extend(b"\0" * (-len(self.data) % 4))
        value = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(data)}
        if target is not None:
            value["target"] = target
        self.doc["bufferViews"].append(value)
        self.data.extend(data)
        return len(self.doc["bufferViews"]) - 1

    def accessor(self, rows, kind, component=5126, target=None, bounds=False):
        count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[kind]
        fmt = "<" + {5126: "f", 5123: "H", 5125: "I"}[component] * count
        value = {"bufferView": self.view(b"".join(struct.pack(fmt, *row) for row in rows), target),
                 "componentType": component, "count": len(rows), "type": kind}
        if bounds:
            value.update(min=[min(r[i] for r in rows) for i in range(count)], max=[max(r[i] for r in rows) for i in range(count)])
        self.doc["accessors"].append(value)
        return len(self.doc["accessors"]) - 1

    def finish(self):
        self.doc["buffers"] = [{"byteLength": len(self.data)}]
        payload = json.dumps(self.doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        payload += b" " * (-len(payload) % 4)
        self.data.extend(b"\0" * (-len(self.data) % 4))
        length = 12 + 8 + len(payload) + 8 + len(self.data)
        return struct.pack("<III", 0x46546c67, 2, length) + struct.pack("<II", len(payload), 0x4e4f534a) + payload + struct.pack("<II", len(self.data), 0x004e4942) + self.data


def _geometry(glb, geometry, skin, material_map):
    primitives, lookup = [], {name: i for i, name in enumerate(skin["joints"])}
    shape = skin["bind_shape"]
    # Non-identity bind shape needs normal inverse-transpose support. Never
    # silently apply a partial conversion to source UV/normals/weights.
    if max(abs(x - y) for x, y in zip(shape, IDENTITY)) > 1e-6:
        raise ValueError("DAE_BIND_SHAPE_REQUIRES_ADAPTER")
    for group in geometry["groups"]:
        attrs = {}
        stride = group["stride"]
        corner_count = group["triangles"] * 3
        position_indices = None
        for semantic, source, offset, channel in group["inputs"]:
            key = {"POSITION": "POSITION", "NORMAL": "NORMAL", "TEXCOORD": "TEXCOORD_" + str(channel), "COLOR": "COLOR_" + str(channel)}.get(semantic)
            if key is None or key in attrs:
                raise ValueError("DAE_ATTRIBUTE_REQUIRES_ADAPTER:" + str(semantic))
            indices = group["indices"][offset::stride]
            rows = [geometry["sources"][source][i] for i in indices]
            if not rows or len(rows[0]) not in (2, 3, 4):
                raise ValueError("DAE_ATTRIBUTE_DIMENSION")
            attrs[key] = glb.accessor(rows, "VEC" + str(len(rows[0])), target=34962, bounds=key == "POSITION")
            if semantic == "POSITION":
                position_indices = indices
        if position_indices is None or len(position_indices) != corner_count:
            raise ValueError("DAE_POSITION_INPUT_REQUIRED")
        js, ws = [], []
        for index in position_indices:
            if not 0 <= index < len(skin["weights"]):
                raise ValueError("DAE_POSITION_WEIGHT_MISMATCH")
            row = skin["weights"][index]
            if not 1 <= len(row) <= 4:
                raise ValueError("TRIAL_SUPPORTS_1_TO_4_WEIGHTS_NO_TRUNCATION")
            js.append([j for j, _ in row] + [0] * (4 - len(row)))
            ws.append([w for _, w in row] + [0.] * (4 - len(row)))
        attrs["JOINTS_0"] = glb.accessor(js, "VEC4", 5123, target=34962)
        attrs["WEIGHTS_0"] = glb.accessor(ws, "VEC4", target=34962)
        material = material_map.get(group["material"])
        if material is None:
            raise ValueError("DAE_MATERIAL_BINDING_REQUIRED")
        primitives.append({"attributes": attrs, "mode": 4, "material": material,
                           "extras": {"source_material_symbol": group["material"], "source_triangles": group["triangles"]}})
    return {"name": geometry["id"], "primitives": primitives}


def trial(raw, animation_path, fps, basis):
    fps = float(fps)
    if not math.isfinite(fps) or not .1 <= fps <= 240 or basis not in BASES:
        raise ValueError("EXPLICIT_FPS_AND_SMD_BASIS_REQUIRED")
    path, data = common.read_file(raw, 8 * 1024 * 1024)
    clip_path, clip_data = common.read_file(animation_path)
    source = meshes.dae(data, full=True)
    animation = meshes.smd(clip_data, full=True)
    scene, metadata = source["scene"], source["metadata"]
    if metadata["animation_channels"] or not scene["controllers"]:
        raise ValueError("TRIAL_REQUIRES_SKINNED_DAE_WITH_SEPARATE_SMD")
    observation = deps.observe(path, data, source, deps.selected_root(path))
    deps.fresh(observation)
    mapping, extra = match(scene, animation)
    local = [local_matrix(n) for n in scene["nodes"]]
    world = world_matrices(scene["nodes"], local)
    lookup = aliases(scene["nodes"])
    bind_rows = [{"joint": j, "aliases": scene["nodes"][lookup[j]]["aliases"],
                  "max_matrix_error": max(abs(v - IDENTITY[i]) for i, v in enumerate(mul(world[lookup[j]], ib)))}
                 for skin in scene["controllers"] for j, ib in zip(skin["joints"], skin["inverse_bind"])]
    bind_error = max((r["max_matrix_error"] for r in bind_rows), default=0)
    if bind_error > 1e-3:
        failures = [r for r in bind_rows if r["max_matrix_error"] > 1e-3]
        report = {"schema": "gg.game-workflow.rig-preflight.v1", "status": "FAIL", "reason": "DAE_BIND_POSE_CLOSURE_FAILED",
                  "summary": f"{len(failures)} source bind matrices disagree with the DAE hierarchy; trial conversion stopped",
                  "source": str(path), "source_hash": common.digest(data), "clip": str(clip_path), "clip_hash": common.digest(clip_data),
                  "fps": fps, "basis": basis, "source_metadata": metadata, "matched_joints": len(mapping),
                  "bind_pose_max_matrix_error": bind_error, "failed_bind_joints": failures[:128],
                  "gates": {"aliases_and_parents": {"state": "PASS"}, "dae_bind_pose": {"state": "FAIL"}, "semantic_gg_retarget": {"state": "UNKNOWN"}},
                  "limits": ["No inverse matrix, weight, topology or source file was repaired automatically. Name/parent matches do not prove bind-pose compatibility."]}
        if common.digest(common.read_file(path)[1]) != report["source_hash"] or common.digest(common.read_file(clip_path)[1]) != report["clip_hash"]:
            raise ValueError("RIG_SOURCE_CHANGED")
        deps.fresh(observation)
        return {**report, "packet_path": str(common.packet("rig-preflight", report))}
    glb = GLB()
    glb.doc["nodes"] = [{"name": n["aliases"][0] if n["aliases"] else "node" + str(i), **trs(local[i]),
                         "extras": {"source_aliases": n["aliases"]}} for i, n in enumerate(scene["nodes"])]
    for i, node in enumerate(scene["nodes"]):
        if node["parent"] is not None:
            glb.doc["nodes"][node["parent"]].setdefault("children", []).append(i)
    material_map, image_map = {}, {}
    for material in scene["materials"]:
        row = {"name": material["name"], "pbrMetallicRoughness": {"baseColorFactor": material["color"], "metallicFactor": 0, "roughnessFactor": 1},
               "extras": {"source_effect": material["effect"], "shader_equivalence": "UNVERIFIED_PBR_PREVIEW"}}
        if material["texture"]:
            if material["texture"] not in image_map:
                _, pixels = resources.read_reference(path, material["texture"], Path(observation["reference_root"]), common.MAX_FILE)
                if common.digest(pixels) != next(d["hash"] for d in observation["dependencies"] if d["path"] == str(resources.reference(path, material["texture"], Path(observation["reference_root"]), common.MAX_FILE))):
                    raise ValueError("SOURCE_TEXTURE_CHANGED")
                if pixels.startswith(b"\x89PNG"):
                    mime = "image/png"
                elif pixels.startswith(b"\xff\xd8"):
                    mime = "image/jpeg"
                else:
                    raise ValueError("TRIAL_TEXTURE_FORMAT_REQUIRES_ADAPTER")
                image_index = len(glb.doc.setdefault("images", []))
                glb.doc["images"].append({"bufferView": glb.view(pixels), "mimeType": mime, "name": material["texture"]})
                texture_index = len(glb.doc.setdefault("textures", []))
                glb.doc["textures"].append({"source": image_index})
                image_map[material["texture"]] = texture_index
            row["pbrMetallicRoughness"]["baseColorTexture"] = {"index": image_map[material["texture"]]}
        material_map[material["id"]] = len(glb.doc["materials"])
        glb.doc["materials"].append(row)
    for symbol, identity in scene["material_bindings"].items():
        material_map[symbol] = material_map[identity]
    for skin in scene["controllers"]:
        geometry = next(g for g in scene["geometries"] if g["id"] == skin["geometry"])
        mesh_index, skin_index = len(glb.doc["meshes"]), len(glb.doc["skins"])
        glb.doc["meshes"].append(_geometry(glb, geometry, skin, material_map))
        glb.doc["skins"].append({"name": skin["id"], "joints": [lookup[j] for j in skin["joints"]],
                                 "inverseBindMatrices": glb.accessor([transpose(m) for m in skin["inverse_bind"]], "MAT4")})
        targets = [i for i, n in enumerate(scene["nodes"]) if any(a["kind"] == "instance_controller" and a["target"] == skin["id"] for a in n["instances"])]
        if len(targets) != 1:
            raise ValueError("DAE_CONTROLLER_INSTANCE_REQUIRES_ADAPTER")
        glb.doc["nodes"][targets[0]].update(mesh=mesh_index, skin=skin_index)
    times = sorted(animation["frames"])
    time_accessor = glb.accessor([[(t - times[0]) / fps] for t in times], "SCALAR", bounds=True)
    clip = {"name": clip_path.stem, "samplers": [], "channels": [], "extras": {"fps": fps, "fps_source": "CALLER_SUPPLIED", "basis": basis}}
    for identity, index in sorted(mapping.items()):
        poses = []
        for time in times:
            if identity not in animation["frames"][time]:
                raise ValueError("SMD_SPARSE_POSES_REQUIRE_ADAPTER")
            poses.append(trs(smd_matrix(animation["frames"][time][identity], animation["nodes"][identity]["parent"] == -1, basis)))
        # Equivalent quaternions need consistent signs for linear interpolation.
        for previous, current in zip(poses, poses[1:]):
            if sum(a * b for a, b in zip(previous["rotation"], current["rotation"])) < 0:
                current["rotation"] = [-x for x in current["rotation"]]
        for attr, kind in (("translation", "VEC3"), ("rotation", "VEC4")):
            sample_index = len(clip["samplers"])
            clip["samplers"].append({"input": time_accessor, "output": glb.accessor([p[attr] for p in poses], kind), "interpolation": "LINEAR"})
            clip["channels"].append({"sampler": sample_index, "target": {"node": index, "path": attr}})
    glb.doc.update(animations=[clip], scene=0, scenes=[{"nodes": [i for i, n in enumerate(scene["nodes"]) if n["parent"] is None]}])
    # Explicit right-handed DAE up-axis to glTF Y-up, applied to mesh AND rig.
    up = metadata["up_axis"]
    scale = metadata["meters_per_unit"]
    if up not in ("X_UP", "Y_UP", "Z_UP") or scale is None:
        raise ValueError("DAE_DECLARED_BASIS_AND_UNIT_REQUIRED")
    basis_matrix = axis_rotation((1, 0, 0), -math.pi / 2) if up == "Z_UP" else axis_rotation((0, 0, 1), math.pi / 2) if up == "X_UP" else IDENTITY[:]
    wrapper = {"name": "SOURCE_BASIS_TO_GLTF", **trs(basis_matrix), "children": glb.doc["scenes"][0]["nodes"]}
    wrapper["scale"] = [scale] * 3
    glb.doc["scenes"][0]["nodes"] = [len(glb.doc["nodes"])]
    glb.doc["nodes"].append(wrapper)
    glb.doc["extras"] = {"source_sha256": common.digest(data), "source_clip_sha256": common.digest(clip_data),
                           "policy": "REVIEW_TRIAL_PRESERVE_SOURCE_NO_RETARGET", "fps": fps, "basis": basis}
    output = bytes(glb.finish())
    report = {"schema": "gg.game-workflow.rig-trial.v1", "status": "REVIEW_REQUIRED",
              "summary": f"{len(mapping)} joint aliases matched; source topology and weights preserved in a separate GLB trial",
              "source": str(path), "source_hash": common.digest(data), "clip": str(clip_path), "clip_hash": common.digest(clip_data),
              "source_identity": observation["identity"], "dependency_observation": observation,
              "fps": fps, "fps_source": "CALLER_SUPPLIED_NOT_NATIVE_VERIFIED", "basis": basis,
              "matched_joints": len(mapping), "omitted_unmatched_nodes": extra,
              "bind_pose_max_matrix_error": bind_error, "source_metadata": metadata,
              "trial_hash": common.digest(output), "preservation": {"triangles": metadata["triangles"],
                    "material_groups": sum(len(g["groups"]) for g in scene["geometries"]),
                    "uv_normals": "CORNER_ATTRIBUTES_PRESERVED", "weights": "RAW_VALUES_NO_TRUNCATION_NO_NORMALIZATION",
                    "coincident_faces": "PRESERVED_NO_WELD_OR_CLEANUP"},
              "gates": {"aliases_and_parents": {"state": "PASS"}, "dae_bind_pose": {"state": "PASS"},
                        "source_shader_equivalence": {"state": "UNKNOWN"}, "native_fps_and_basis": {"state": "UNKNOWN"},
                        "visual_pose_review": {"state": "UNKNOWN"}, "semantic_gg_retarget": {"state": "UNKNOWN"}},
              "limits": ["Separate study trial, never installed as a GG hero. Materials retain source effects and textures; PBR preview is not proven shader equivalence.",
                         "DAE bind closure and SMD hierarchy are checked; the SMD first frame is an animation pose, not assumed to be the bind pose.",
                         "Blender review must inspect bind/first/middle/last poses before creating an explicit GG joint map. Original FPS and basis remain unverified."]}
    # Re-read exact sources and dependencies before committing any trial.
    if common.digest(common.read_file(path)[1]) != report["source_hash"] or common.digest(common.read_file(clip_path)[1]) != report["clip_hash"]:
        raise ValueError("RIG_SOURCE_CHANGED")
    deps.fresh(observation)
    model_path = common.ROOT / "packets" / ("rig-trial-" + report["trial_hash"][:24] + ".glb")
    if model_path.exists() and common.digest(common.read_file(model_path)[1]) != report["trial_hash"]:
        raise ValueError("RIG_TRIAL_CHANGED")
    if not model_path.exists():
        common.write_bytes(model_path, output)
    report["model_path"] = str(model_path)
    packet = common.packet("rig-trial", report)
    return {**report, "packet_path": str(packet)}
