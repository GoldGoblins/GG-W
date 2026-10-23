"""Read-only measurements of the local corpus; never load or rewrite a game asset.

glTF counts are document metadata, OBJ counts are exported topology, and GG mesh
counts are checked headers. None certify rendering, gameplay or original rigs.
Default output is stdout. --output writes new evidence under this project's docs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import struct
import time
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[2]
ASSETS = PROJECT / "qml/assets"
REFERENCES = ASSETS / "authored/concept/refs/ps2-models"
MAX_FILES = 50_000
MAX_DOCUMENT = 8 * 1024 * 1024


def stamp(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def percentile(values, fraction):
    values = sorted(values)
    return values[round((len(values) - 1) * fraction)] if values else None


def gltf_document(path):
    with path.open("rb") as stream:
        if path.suffix == ".glb":
            header = stream.read(20)
            if len(header) != 20:
                raise ValueError("TRUNCATED_GLB")
            magic, version, length, count, kind = struct.unpack("<5I", header)
            if magic != 0x46546C67 or version != 2 or length != path.stat().st_size or kind != 0x4E4F534A:
                raise ValueError("INVALID_GLB_HEADER")
            if count > MAX_DOCUMENT or count + 20 > length:
                raise ValueError("GLB_DOCUMENT_LIMIT")
            data = stream.read(count)
        else:
            data = stream.read(MAX_DOCUMENT + 1)
            if len(data) > MAX_DOCUMENT:
                raise ValueError("GLTF_DOCUMENT_LIMIT")
    return json.loads(data)


def dependency(path, uri):
    if not isinstance(uri, str) or uri.startswith("data:"):
        return None
    parsed = urlparse(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in uri:
        return {"uri": uri, "status": "NOT_LOCAL_REFERENCE"}
    candidate = path.parent / unquote(parsed.path)
    resolved = candidate.resolve()
    if candidate.is_symlink() or not resolved.is_relative_to(ASSETS):
        return {"uri": uri, "status": "OUTSIDE_ASSET_ROOT_OR_SYMLINK"}
    if not resolved.is_file():
        return {"uri": uri, "status": "MISSING"}
    return {"uri": uri, "path": resolved.relative_to(ASSETS).as_posix(),
            "status": "LOCAL", "bytes": resolved.stat().st_size}


def gltf_facts(path):
    doc = gltf_document(path)
    accessors = doc.get("accessors", [])
    primitives = [p for mesh in doc.get("meshes", []) for p in mesh.get("primitives", [])]
    positions = {p["attributes"]["POSITION"] for p in primitives if "POSITION" in p.get("attributes", {})}
    triangles = 0
    for primitive in primitives:
        count = accessors[primitive.get("indices", primitive["attributes"]["POSITION"])]["count"]
        mode = primitive.get("mode", 4)
        triangles += count // 3 if mode == 4 else max(0, count - 2) if mode in (5, 6) else 0
    deps = [dependency(path, row["uri"]) for collection in ("buffers", "images")
            for row in doc.get(collection, []) if row.get("uri")]
    deps = [row for row in deps if row]
    return {"path": path.relative_to(ASSETS).as_posix(), "format": path.suffix[1:].upper(),
            "file_bytes": path.stat().st_size, "meshes": len(doc.get("meshes", [])),
            "primitives": len(primitives), "materials": len(doc.get("materials", [])),
            "position_records": sum(accessors[i]["count"] for i in positions),
            "primitive_position_records": sum(accessors[p["attributes"]["POSITION"]]["count"] for p in primitives),
            "triangles_from_accessor_counts": triangles,
            "max_skin_joints": max((len(s["joints"]) for s in doc.get("skins", [])), default=0),
            "animations": [a.get("name", "") for a in doc.get("animations", [])],
            "morph_target_primitives": sum(bool(p.get("targets")) for p in primitives),
            "alpha_modes": dict(Counter(m.get("alphaMode", "OPAQUE") for m in doc.get("materials", []))),
            "double_sided_materials": sum(bool(m.get("doubleSided")) for m in doc.get("materials", [])),
            "external_dependencies": deps, "sha256": digest(path)}


def obj_facts(path):
    vertices, used, materials, libraries = [], Counter(), set(), []
    face_ids, face_positions, layered_materials = Counter(), Counter(), defaultdict(list)
    faces, corners, triangles, uv, normals, quads, ngons = 0, 0, 0, 0, 0, 0, 0
    current = "UNASSIGNED"
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        token = fields[0]
        if token == "v":
            point = tuple(float(x) for x in fields[1:4])
            if len(point) != 3 or not all(math.isfinite(x) for x in point):
                raise ValueError("INVALID_OBJ_VERTEX")
            vertices.append(point)
        elif token == "vt":
            uv += 1
        elif token == "vn":
            normals += 1
        elif token == "usemtl":
            current = " ".join(fields[1:]); materials.add(current)
        elif token == "mtllib":
            libraries.append(" ".join(fields[1:]))
        elif token == "f":
            count = len(fields) - 1
            if count < 3:
                raise ValueError("INVALID_OBJ_FACE")
            ids = []
            for item in fields[1:]:
                index = int(item.split("/")[0])
                if index == 0 or not -len(vertices) <= index <= len(vertices):
                    raise ValueError("INVALID_OBJ_POSITION_INDEX")
                ids.append(index - 1 if index > 0 else len(vertices) + index)
            face_ids[tuple(sorted(ids))] += 1
            position_key = tuple(sorted(vertices[i] for i in ids))
            face_positions[position_key] += 1
            layered_materials[position_key].append(current)
            faces += 1; corners += count; triangles += count - 2
            quads += count == 4; ngons += count > 4; used[current] += count - 2
    bounds = [[min(p[i] for p in vertices), max(p[i] for p in vertices)] for i in range(3)] if vertices else []
    deps = [dependency(path, name) for name in libraries]
    return {"path": path.relative_to(ASSETS).as_posix(), "vertices": len(vertices),
            "distinct_position_tuples": len(set(vertices)), "uv_records": uv, "normal_records": normals,
            "faces": faces, "face_corners": corners, "triangles_after_fan_triangulation": triangles,
            "quads": quads, "ngons": ngons, "used_materials": len(materials),
            "triangles_by_material": dict(used), "local_bounds": bounds, "material_libraries": deps,
            "duplicate_position_index_faces": sum(count - 1 for count in face_ids.values()),
            "geometric_coincident_faces": sum(count - 1 for count in face_positions.values()),
            "coincident_face_material_examples": [names for names in layered_materials.values()
                                                  if len(names) > 1 and len(set(names)) > 1][:5],
            "rig_and_animation": "NOT_ENCODED_BY_OBJ", "sha256": digest(path)}


def dae_facts(path):
    data = path.read_bytes()
    if len(data) > MAX_DOCUMENT or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("XML_LIMIT_OR_DTD")
    root = ET.fromstring(data)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    controllers = []
    for skin in root.findall(".//skin"):
        sources = {s.get("id"): s for s in skin.findall("source")}
        joints = skin.find("joints/input[@semantic='JOINT']")
        joint_array = sources[joints.get("source").lstrip("#")].find("Name_array") if joints is not None else None
        if joint_array is None and joints is not None:
            joint_array = sources[joints.get("source").lstrip("#")].find("IDREF_array")
        weights = skin.find("vertex_weights")
        counts = [int(x) for x in weights.findtext("vcount", "").split()] if weights is not None else []
        controllers.append({"joints": len((joint_array.text or "").split()) if joint_array is not None else 0,
                            "weighted_vertices": len(counts), "influences_histogram": dict(Counter(counts)),
                            "max_influences": max(counts, default=0)})
    unit = root.find("asset/unit")
    return {"path": path.relative_to(ASSETS).as_posix(),
            "up_axis": root.findtext("asset/up_axis", "UNDECLARED"),
            "declared_meters_per_unit": float(unit.get("meter", "1")) if unit is not None else None,
            "geometry_count": len(root.findall(".//geometry")), "skin_controllers": controllers,
            "animation_channels": len(root.findall(".//animation/channel")),
            "joint_nodes": len(root.findall(".//node[@type='JOINT']")),
            "image_references": [dependency(path, e.text.strip()) for e in root.findall(".//image/init_from") if e.text],
            "authoring_tool": root.findtext("asset/contributor/authoring_tool", ""), "sha256": digest(path)}


def mesh_header(path):
    with path.open("rb") as stream:
        data = stream.read(20)
    if len(data) != 20:
        raise ValueError("TRUNCATED_GGMESH")
    magic, stride, vertices, indices = struct.unpack("<8sIII", data)
    if magic != b"GGFLORA1" or stride != 40 or path.stat().st_size != 20 + vertices * stride + indices * 4 or indices % 3:
        raise ValueError("INVALID_GGMESH_HEADER")
    return {"vertices": vertices, "triangles": indices // 3}


def smd_facts(path):
    section, bones, times, pose_rows = "", {}, [], 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if line in ("nodes", "skeleton", "triangles"):
            section = line; continue
        if line == "end":
            section = ""; continue
        if section == "nodes":
            fields = shlex.split(line)
            bones[int(fields[0])] = {"name": fields[1], "parent": int(fields[2])}
        elif section == "skeleton":
            if line.startswith("time "):
                times.append(int(line.split()[1]))
            elif line:
                pose_rows += 1
    matches = []
    for candidate in sorted(path.parent.parent.glob("*.dae")):
        root = ET.fromstring(candidate.read_bytes())
        for element in root.iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        ids, parents = {}, {}
        def visit(element, parent=None):
            if element.tag == "node" and element.get("type") == "JOINT":
                name = element.get("name") or element.get("id") or element.get("sid")
                parents[name] = parent
                for attribute in ("id", "name", "sid"):
                    if element.get(attribute):
                        ids[element.get(attribute)] = name
                parent = name
            for child in element:
                visit(child, parent)
        visit(root)
        mapped = {key: ids[row["name"]] for key, row in bones.items() if row["name"] in ids}
        disagreements = []
        for key, name in mapped.items():
            parent_key = bones[key]["parent"]
            if parents[name] != mapped.get(parent_key):
                disagreements.append(name)
        matches.append({"dae": candidate.relative_to(ASSETS).as_posix(), "dae_joints": len(parents),
                        "matching_id_name_sid_aliases": len(mapped), "parent_disagreements": disagreements,
                        "unmapped_smd_nodes": [row["name"] for key, row in bones.items() if key not in mapped]})
    return {"path": path.relative_to(ASSETS).as_posix(), "nodes": len(bones), "time_samples": len(times),
            "first_sample": min(times, default=None), "last_sample": max(times, default=None),
            "pose_rows": pose_rows, "declared_fps": "ABSENT", "candidate_rig_matches": matches,
            "coverage": "NAME_AND_PARENT_TOPOLOGY_ONLY_NOT_BIND_POSE_OR_PLAYBACK", "sha256": digest(path)}


def original_readers():
    upstream = Path('/home/GG/.local/share/goldgoblins/gg-ai-desktop/game-engine/engine-reference-upstream')
    rows = []
    for name in ("engine-formats", "engine-ui-core"):
        root = PROJECT / "native" / name
        source_files = json.loads((root / "upstream-provenance.json").read_text())["source_files"]
        changed = [key for key, expected in source_files.items() if not (root / key).is_file() or digest(root / key) != expected]
        comparable = [key for key in source_files if (upstream / key).is_file()]
        different = [key for key in comparable if digest(root / key) != digest(upstream / key)]
        rows.append({"package": name, "preserved_files": len(source_files), "receipt_matches": len(source_files) - len(changed),
                     "missing_or_changed": changed, "current_local_upstream_comparable": len(comparable),
                     "different_from_local_upstream": different})
    return rows


def study():
    started = time.monotonic()
    initial, groups, gltfs, objs, daes, smds, errors = {}, {}, [], [], [], [], []
    mesh_groups = defaultdict(list)
    for directory, dirs, files in os.walk(ASSETS, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink():
                continue
            if len(initial) >= MAX_FILES:
                raise ValueError("ASSET_INVENTORY_LIMIT")
            initial[path] = stamp(path)
            rel = path.relative_to(ASSETS)
            group = "/".join(rel.parts[:min(3, len(rel.parts) - 1)])
            row = groups.setdefault(group, {"files": 0, "bytes": 0, "extensions": Counter()})
            row["files"] += 1; row["bytes"] += initial[path][2]; row["extensions"][path.suffix.lower()] += 1
    for path in initial:
        try:
            if path.suffix in (".glb", ".gltf"):
                gltfs.append(gltf_facts(path))
            elif path.is_relative_to(REFERENCES) and path.suffix == ".obj":
                objs.append(obj_facts(path))
            elif path.is_relative_to(REFERENCES) and path.suffix == ".dae":
                daes.append(dae_facts(path))
            elif path.is_relative_to(REFERENCES) and path.suffix == ".smd":
                smds.append(smd_facts(path))
            elif path.suffix == ".ggmesh":
                parts = path.relative_to(ASSETS).parts
                group = "/".join(parts[:min(3, len(parts) - 1)])
                mesh_groups[group].append(mesh_header(path))
        except (ValueError, OSError, KeyError, IndexError, struct.error, ET.ParseError) as exc:
            errors.append({"path": path.relative_to(ASSETS).as_posix(), "reason": str(exc)[:300]})
    dependencies = Counter(row["path"] for asset in gltfs for row in asset["external_dependencies"] if row["status"] == "LOCAL")
    broken = [{"asset": a["path"], **d} for a in gltfs for d in a["external_dependencies"] if d["status"] != "LOCAL"]
    model_groups = {}
    for group in groups:
        selected = [a for a in gltfs if "/".join(Path(a["path"]).parts[:min(3, len(Path(a["path"]).parts) - 1)]) == group]
        if selected:
            model_groups[group] = {"documents": len(selected), "unique_document_bytes": len({a["sha256"] for a in selected}),
                "skinned": sum(a["max_skin_joints"] > 0 for a in selected), "animated": sum(bool(a["animations"]) for a in selected),
                "max_skin_joints": max(a["max_skin_joints"] for a in selected),
                "triangle_min": min(a["triangles_from_accessor_counts"] for a in selected),
                "triangle_median": percentile([a["triangles_from_accessor_counts"] for a in selected], .5),
                "triangle_max": max(a["triangles_from_accessor_counts"] for a in selected),
                "with_external_dependencies": sum(bool(a["external_dependencies"]) for a in selected)}
    textures = []
    from PIL import Image
    for path in initial:
        if path.is_relative_to(REFERENCES) and path.suffix.lower() in (".png", ".jpg", ".tga"):
            try:
                with Image.open(path) as image:
                    textures.append({"path": path.relative_to(ASSETS).as_posix(), "width": image.width,
                                     "height": image.height, "mode": image.mode})
            except (ValueError, OSError) as exc:
                errors.append({"path": path.relative_to(ASSETS).as_posix(), "reason": str(exc)[:300]})
    changed = [str(path.relative_to(ASSETS)) for path, before in initial.items() if not path.is_file() or stamp(path) != before]
    if changed:
        raise ValueError("ASSETS_CHANGED_DURING_STUDY: " + ", ".join(changed[:8]))
    return {"schema": "gg.local-game-asset-study.v1", "status": "MEASURED", "asset_root": str(ASSETS),
            "scope": "Local corpus metadata and exported topology, not complete game compatibility",
            "original_intent": "Learn from upstream, GG adapters and already available game assets; preserve the game-independent working steps.",
            "asset_files": len(initial), "asset_bytes": sum(v[2] for v in initial.values()),
            "source_stamps_unchanged": True, "groups": groups, "gltf_groups": model_groups,
            "gltf_documents": gltfs, "obj_references": objs, "dae_references": daes,
            "smd_animation_references": smds,
            "compiled_meshes": {key: {"files": len(rows), "vertices_total": sum(r["vertices"] for r in rows),
                "triangle_min": min(r["triangles"] for r in rows), "triangle_median": percentile([r["triangles"] for r in rows], .5),
                "triangle_max": max(r["triangles"] for r in rows)} for key, rows in mesh_groups.items()},
            "external_dependency_occurrences": sum(dependencies.values()), "distinct_external_dependencies": len(dependencies),
            "most_shared_dependencies": [{"path": key, "documents": count} for key, count in dependencies.most_common(20)],
            "broken_external_dependencies": broken, "reference_textures": textures,
            "original_reader_integrity": original_readers(), "errors": errors,
            "limits": ["glTF accessor counts do not verify binary vertex contents or visible draw calls.",
                       "OBJ triangulation counts describe exported polygons, not an original game renderer.",
                       "DAE exporter unit labels do not prove original game scale or original rig provenance.",
                       "GG mesh headers do not verify vertex/index contents or visual quality.",
                       "Unchanged source stamps corroborate this read-only pass; they are not full-corpus byte attestation."],
            "elapsed_seconds": round(time.monotonic() - started, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = study()
    if args.output:
        destination = args.output.resolve()
        if not destination.is_relative_to(PROJECT / "docs"):
            parser.error("Evidence output must be a new file under project docs")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    summary = {key: result[key] for key in ("status", "asset_files", "asset_bytes", "source_stamps_unchanged",
        "external_dependency_occurrences", "distinct_external_dependencies", "elapsed_seconds")}
    summary.update({"obj_references": len(result["obj_references"]), "dae_references": len(result["dae_references"]),
                    "smd_animation_references": len(result["smd_animation_references"]),
                    "gltf_documents": len(result["gltf_documents"]),
                    "compiled_meshes": sum(row["files"] for row in result["compiled_meshes"].values()),
                    "errors": len(result["errors"]), "broken_dependencies": len(result["broken_external_dependencies"])})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
