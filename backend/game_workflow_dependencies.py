"""Content identity of a document and its bounded local dependency graph."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import struct

from backend import game_asset_resources as resources, game_workflow_common as common

MAX_DEPENDENCIES = 256
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
ADAPTER_REVISION = 2


def selected_root(path: Path, root: Path | None = None) -> Path:
    # A packaged variant may use the same shared rig as its base model.
    from backend.game_engine_assets import ASSET_ROOT
    return ASSET_ROOT if path.is_relative_to(ASSET_ROOT) else root.resolve() if root is not None else path.parent


def gltf_document(data, suffix):
    if data.startswith(b"glTF"):
        if len(data) < 20:
            raise ValueError("TRUNCATED_GLB")
        length, kind = struct.unpack_from("<II", data, 12)
        if kind != 0x4e4f534a or length > common.MAX_JSON or 20 + length > len(data):
            raise ValueError("INVALID_GLB_JSON")
        return common.parse_json(data[20:20 + length].rstrip(b" \0"), max_nodes=250000)
    if suffix.lower() == ".gltf":
        return common.parse_json(data, max_nodes=250000)
    return None


def mtl_references(data):
    found = []
    option_sizes = {"-blendu": 1, "-blendv": 1, "-boost": 1, "-mm": 2, "-texres": 1,
                    "-clamp": 1, "-bm": 1, "-imfchan": 1, "-type": 1}
    for line in data.decode("utf-8-sig", "strict").splitlines():
        words = shlex.split(line, comments=True)
        if not words or not (words[0].startswith("map_") or words[0] in ("bump", "disp", "decal", "norm")):
            continue
        index = 1
        while index < len(words) and words[index].startswith("-"):
            option = words[index]
            index += 1
            if option in ("-o", "-s", "-t"):
                consumed = 0
                while index < len(words) and consumed < 3:
                    try:
                        float(words[index])
                    except ValueError:
                        break
                    index += 1
                    consumed += 1
                if not consumed:
                    raise ValueError("MTL_OPTION_ARGUMENT_REQUIRED")
            elif option in option_sizes:
                index += option_sizes[option]
            else:
                raise ValueError("MTL_OPTION_REQUIRES_ADAPTER:" + option)
        if index >= len(words):
            raise ValueError("MTL_TEXTURE_PATH_REQUIRED")
        found.append((" ".join(words[index:]), "texture:" + words[0]))
    return found


def references(data, path, observation):
    document = gltf_document(data, path.suffix) if observation["format"] in ("GLB", "GLTF") else None
    if document is not None:
        uses = {}
        for skin in document.get("skins", []):
            if "inverseBindMatrices" in skin:
                accessor = document.get("accessors", [])[skin["inverseBindMatrices"]]
                if "bufferView" in accessor:
                    b = document.get("bufferViews", [])[accessor["bufferView"]].get("buffer", 0)
                    uses.setdefault(b, set()).add("inverse_bind_matrices")
        for animation in document.get("animations", []):
            for sampler in animation.get("samplers", []):
                for attr in ("input", "output"):
                    accessor = document.get("accessors", [])[sampler[attr]]
                    if "bufferView" in accessor:
                        b = document.get("bufferViews", [])[accessor["bufferView"]].get("buffer", 0)
                        uses.setdefault(b, set()).add("animation_samples")
        return [(r["uri"], "buffer:" + ",".join(sorted(uses.get(i, {"geometry_or_other"}))))
                for i, r in enumerate(document.get("buffers", [])) if r.get("uri") and not r["uri"].startswith("data:")] + [
                (r["uri"], "image") for r in document.get("images", []) if r.get("uri") and not r["uri"].startswith("data:")]
    return [(uri, "material_library" if observation["format"] == "OBJ" else "image")
            for uri in observation.get("metadata", {}).get("external_resources", [])]


def observe(path: Path, data: bytes, observation: dict, root: Path, cache=None) -> dict:
    cache = cache if cache is not None else {}
    deps, edges, total = {}, [], len(data)
    pending = [(path, uri, role, 0) for uri, role in references(data, path, observation)]
    while pending:
        parent, uri, role, depth = pending.pop(0)
        if len(edges) >= MAX_DEPENDENCIES or depth > 2:
            raise ValueError("DEPENDENCY_GRAPH_LIMIT")
        edge = {"from": str(parent), "uri": uri, "role": role}
        try:
            candidate = resources.reference(parent, uri, root, common.MAX_FILE)
            key = str(candidate)
            if key not in deps:
                if key not in cache:
                    _, contents = common.read_file(candidate, min(common.MAX_FILE, MAX_BUNDLE_BYTES - total), root=root)
                    cache[key] = (common.digest(contents), len(contents), contents if role == "material_library" else None)
                fingerprint, size, contents = cache[key]
                total += size
                if total > MAX_BUNDLE_BYTES:
                    raise ValueError("DEPENDENCY_BYTE_LIMIT")
                info = candidate.stat()
                deps[key] = {"path": key, "hash": fingerprint, "bytes": size,
                             "stamp": [info.st_size, info.st_mtime_ns, info.st_ctime_ns]}
                if role == "material_library":
                    if contents is None:
                        _, contents = common.read_file(candidate, root=root)
                    pending.extend((candidate, child, child_role, depth + 1) for child, child_role in mtl_references(contents))
            edge.update(path=key, status="LOCAL", hash=deps[key]["hash"])
        except (OSError, ValueError) as exc:
            if "LIMIT" in str(exc):
                raise
            edge.update(status="UNRESOLVED", reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        edges.append(edge)
    fingerprint = common.digest(data)
    if edges:
        fingerprint = common.digest(json.dumps({"document": fingerprint, "edges": edges}, sort_keys=True, separators=(",", ":")).encode())
    family = re.sub(r"(?:-animated)?-v\d+$", "", path.stem)
    return {"adapter_revision": ADAPTER_REVISION, "identity": fingerprint, "reference_root": str(root),
            "dependencies": list(deps.values()), "dependency_edges": edges, "bundle_bytes": total,
            "dependency_status": "COMPLETE" if all(e["status"] == "LOCAL" for e in edges) else "INCOMPLETE",
            "variant_family": {"name": family, "basis": "FILENAME_CANDIDATE", "directory": str(path.parent)}}


def fresh(observation, *, cache=None, budget=None, require_complete=True):
    cache = cache if cache is not None else {}
    root = Path(observation["reference_root"])
    if require_complete and observation.get("dependency_status") != "COMPLETE":
        raise ValueError("ASSET_DEPENDENCY_UNRESOLVED_REINDEX_REQUIRED")
    for row in observation.get("dependencies", []):
        key = row["path"]
        if key not in cache:
            _, contents = common.read_file(key, root=root)
            if budget is not None:
                budget[0] += len(contents)
                if budget[0] > budget[1]:
                    raise ValueError("FRESHNESS_BYTE_LIMIT")
            cache[key] = common.digest(contents)
        if cache[key] != row["hash"]:
            raise ValueError("ASSET_DEPENDENCY_CHANGED_REINDEX_REQUIRED")
    for edge in observation.get("dependency_edges", []):
        if edge["status"] == "UNRESOLVED" and edge.get("reason") == "FileNotFoundError":
            try:
                resources.reference(Path(edge["from"]), edge["uri"], root, common.MAX_FILE)
            except (OSError, ValueError):
                continue
            raise ValueError("ASSET_DEPENDENCY_APPEARED_REINDEX_REQUIRED")
