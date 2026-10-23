"""Format adapters report their actual coverage; game names never select a decoder.

RenderWare chunk inspection intentionally does not decode native PS2 geometry,
swizzled rasters, title-specific containers, collision or skeleton plugins.
"""
from __future__ import annotations

import io
import struct

from backend import game_workflow_common as common
from backend import game_workflow_meshes as meshes

MAX_CHUNKS = 4096
MAX_PIXELS = 16 * 1024 * 1024
RW_NAMES = {1: "STRUCT", 2: "STRING", 3: "EXTENSION", 6: "TEXTURE", 7: "MATERIAL", 8: "MATERIAL_LIST",
            11: "WORLD", 14: "FRAME_LIST", 15: "GEOMETRY", 16: "CLUMP", 20: "ATOMIC",
            21: "TEXTURE_NATIVE", 22: "TEXTURE_DICTIONARY", 26: "GEOMETRY_LIST"}
RW_CONTAINERS = {3, 6, 7, 8, 11, 14, 15, 16, 20, 21, 22, 26}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".dds"}


def renderware(data: bytes) -> dict:
    rows, names = [], []
    def scan(start, end, depth=0):
        if depth > 16:
            raise ValueError("RENDERWARE_DEPTH_LIMIT")
        cursor = start
        while cursor < end:
            if len(rows) >= MAX_CHUNKS or end - cursor < 12:
                raise ValueError("RENDERWARE_CHUNK_LIMIT_OR_TRUNCATION")
            kind, length, library = struct.unpack_from("<III", data, cursor)
            tail = cursor + 12 + length
            if tail > end:
                raise ValueError("RENDERWARE_CHUNK_OUT_OF_RANGE")
            rows.append({"offset": cursor, "type": kind, "name": RW_NAMES.get(kind, "PLUGIN_OR_UNKNOWN"),
                         "bytes": length, "library_id": library, "depth": depth})
            if kind == 2 and length <= 4096:
                text = data[cursor + 12:tail].split(b"\0", 1)[0].decode("utf-8", "replace")
                if text and len(names) < 128:
                    names.append(text[:256])
            if kind in RW_CONTAINERS and length:
                scan(cursor + 12, tail, depth + 1)
            cursor = tail
    scan(0, len(data))
    if not rows or rows[0]["type"] not in RW_NAMES:
        raise ValueError("UNRECOGNIZED_RENDERWARE_ROOT")
    return {"format": "RENDERWARE_STREAM", "kind": "texture" if rows[0]["type"] == 22 else "model",
            "coverage": "CHUNK_STRUCTURE", "metadata": {"chunk_count": len(rows), "names": names,
                "chunks": rows[:128], "chunks_clipped": len(rows) > 128},
            "limits": ["Native geometry, raster pixels and game-specific plugins need a version/platform adapter."]}


def _gltf(data: bytes, glb: bool) -> dict:
    if glb:
        if len(data) < 20:
            raise ValueError("TRUNCATED_GLB")
        _, version, size, length, kind = struct.unpack_from("<IIIII", data)
        if version != 2 or size != len(data) or kind != 0x4e4f534a or length > common.MAX_JSON or length % 4:
            raise ValueError("INVALID_GLB_HEADER")
        if 20 + length > len(data):
            raise ValueError("TRUNCATED_GLB_JSON")
        payload = data[20:20 + length].rstrip(b" \0")
        cursor = 20 + length
        while cursor < size:
            if cursor + 8 > size:
                raise ValueError("TRUNCATED_GLB_CHUNK")
            chunk_size, _ = struct.unpack_from("<II", data, cursor)
            if chunk_size % 4 or cursor + 8 + chunk_size > size:
                raise ValueError("INVALID_GLB_CHUNK")
            cursor += 8 + chunk_size
    else:
        if len(data) > common.MAX_JSON:
            raise ValueError("GLTF_JSON_TOO_LARGE")
        payload = data
    # Actual packaged characters have ~144k JSON nodes in authored extras.
    # Keep the 4 MiB/depth bounds, with a measured format-specific node budget.
    document = common.parse_json(payload, max_nodes=250000)
    if not isinstance(document.get("asset"), dict) or str(document["asset"].get("version", "")) != "2.0":
        raise ValueError("GLTF_VERSION_UNSUPPORTED")
    keys = ("nodes", "meshes", "materials", "skins", "animations", "images", "buffers")
    if any(not isinstance(document.get(k, []), list) for k in keys):
        raise ValueError("INVALID_GLTF_COLLECTION")
    metadata = {k: len(document.get(k, [])) for k in keys}
    metadata["names"] = [str(row.get("name", ""))[:160] for k in keys for row in document.get(k, [])
                         if isinstance(row, dict) and row.get("name")][:128]
    metadata["external_resources"] = [str(row["uri"])[:256] for k in ("buffers", "images")
                                      for row in document.get(k, []) if isinstance(row, dict) and row.get("uri")
                                      and not str(row["uri"]).startswith("data:")][:128]
    return {"format": "GLB" if glb else "GLTF", "kind": "model", "coverage": "DOCUMENT_METADATA",
            "metadata": metadata, "limits": ["Catalog identity covers the document bytes; external buffers and images retain separate identities.",
                "Catalog metadata does not validate vertex buffers or external resources; GG's asset inspector performs runtime validation."]}


def inspect(data: bytes, suffix: str) -> dict:
    suffix = suffix.lower()
    if suffix == ".obj":
        return meshes.obj(data)
    if suffix == ".dae":
        return meshes.dae(data)
    if suffix == ".smd":
        return meshes.smd(data)
    if suffix == ".ggmesh" or data.startswith(b"GGFLORA1"):
        return meshes.ggmesh(data)
    if data.startswith(b"glTF") or suffix == ".gltf":
        return _gltf(data, data.startswith(b"glTF"))
    if data.startswith(b"\x7fELF"):
        if len(data) < 52 or data[4] not in (1, 2) or data[5] not in (1, 2):
            raise ValueError("INVALID_ELF_HEADER")
        if data[4] == 2 and len(data) < 64:
            raise ValueError("TRUNCATED_ELF64")
        endian = "<" if data[5] == 1 else ">"
        machine = struct.unpack_from(endian + "H", data, 18)[0]
        entry = struct.unpack_from(endian + ("I" if data[4] == 1 else "Q"), data, 24)[0]
        return {"format": "ELF", "kind": "program", "coverage": "HEADER",
                "metadata": {"bits": 32 if data[4] == 1 else 64, "endian": "little" if data[5] == 1 else "big",
                    "machine_id": machine, "architecture": {8: "MIPS", 3: "x86", 62: "x86_64", 40: "ARM", 183: "AARCH64"}.get(machine, "UNKNOWN"), "entry": hex(entry)},
                "limits": ["MIPS ELF alone does not identify a PS2 game or validate its CPU/vector-unit semantics."]}
    if data[:4] in (b"MD20", b"MD21"):
        if len(data) < 8:
            raise ValueError("TRUNCATED_M2_HEADER")
        version = struct.unpack_from("<I", data, 4)[0] if data[:4] == b"MD20" else None
        metadata = {"magic": data[:4].decode(), "version": version}
        if version is not None and 256 <= version <= 263:
            if len(data) < 96:
                raise ValueError("TRUNCATED_M2_HEADER")
            for name, offset in (("animations", 28), ("bones", 52), ("vertices", 68), ("textures", 92)):
                count, position = struct.unpack_from("<II", data, offset)
                if count and (position < 8 or position >= len(data)):
                    raise ValueError("M2_ARRAY_OUT_OF_RANGE")
                metadata[name] = count
        return {"format": "WOW_M2", "kind": "model", "coverage": "HEADER", "metadata": metadata,
                "limits": ["Use the installed GgEngine adapter for supported pre-Wrath MD20 geometry; later M2 variants need their own adapter."]}
    if data[:4] in (b"BLP1", b"BLP2"):
        if len(data) < 148:
            raise ValueError("TRUNCATED_BLP_HEADER")
        width, height = struct.unpack_from("<II", data, 12)
        if not width or not height or width * height > MAX_PIXELS:
            raise ValueError("BLP_DIMENSIONS_OUT_OF_RANGE")
        return {"format": "WOW_BLP", "kind": "texture", "coverage": "HEADER",
                "metadata": {"width": width, "height": height, "magic": data[:4].decode()},
                "limits": ["Pixel decoding uses GG's installed GgEngine adapter; catalog header inspection does not decode pixels."]}
    if data[:4] == b"MPQ\x1a" or suffix == ".mpq":
        return {"format": "WOW_MPQ_CANDIDATE", "kind": "archive", "coverage": "SIGNATURE" if data[:4] == b"MPQ\x1a" else "EXTENSION_ONLY",
                "metadata": {}, "limits": ["The bounded WoW archive reader is separate; indexing does not extract archive entries."]}
    if suffix in (".dff", ".txd", ".rws") or (len(data) >= 12 and struct.unpack_from("<I", data)[0] in (16, 22)):
        return renderware(data)
    if suffix in IMAGE_SUFFIXES:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("IMAGE_PIXEL_LIMIT")
                return {"format": image.format or suffix[1:].upper(), "kind": "texture", "coverage": "IMAGE_HEADER",
                        "metadata": {"width": image.width, "height": image.height, "mode": image.mode},
                        "limits": ["Header inspection does not verify every encoded pixel."]}
        except Image.DecompressionBombError as exc:
            raise ValueError("IMAGE_PIXEL_LIMIT") from exc
    return {"format": "OPAQUE", "kind": "archive" if suffix in (".pak", ".wad", ".iso", ".irx") else "unknown",
            "coverage": "IDENTITY_ONLY", "metadata": {},
            "limits": ["No decoder is inferred from the game label. Select an extracted asset or supply a format adapter."]}
