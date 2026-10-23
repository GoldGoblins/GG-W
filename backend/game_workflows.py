"""Finite workflow API shared by GG's desktop, GPT/Grok CLI and Blender."""
from __future__ import annotations

from pathlib import Path
import io
import tempfile

from backend import game_workflow_common as common, game_workflow_formats as formats
from backend import game_workflow_scout as scout, game_workflow_context as context
from backend import game_workflow_verify as verify, game_workflow_flow as flow
from backend import game_workflow_collections as collections, game_workflow_dependencies as dependencies
from backend import game_workflow_rig as rig

OPERATIONS = {"scout_index", "scout_search", "scout_inspect", "scout_annotate", "scout_visual",
              "context_job", "context_export", "verify_candidate", "flow_import", "flow_check", "flow_export",
              "scout_collections", "scout_batch", "scout_batch_cancel", "scout_relations", "rig_trial", "asset_profile", "scene_measure"}


def capabilities() -> dict:
    return {"schema": common.SCHEMA, "status": "READY", "summary": "Shared asset, analysis, candidate and route workflows",
            "workflows": [{"name": "Scout", "source": "https://github.com/Dryxio/gta-scout", "mode": "GG_ADAPTATION"},
                          {"name": "Ghidra Bridge", "source": "https://github.com/Dryxio/ghidra-bridge", "mode": "GG_ADAPTATION"},
                          {"name": "Reagent", "source": "https://github.com/Dryxio/reagent", "mode": "GG_ADAPTATION"},
                          {"name": "GTA Flow", "source": "https://github.com/Dryxio/gta-flow", "mode": "GG_ADAPTATION"}],
            "adapters": [{"format": "glTF / GLB", "coverage": "Catalog metadata; existing GG inspector validates runtime imports"},
                         {"format": "OBJ / DAE / SMD / GGFLORA1", "coverage": "Bounded exported topology, joint aliases, raw weight profiles and pose samples; no automatic cleanup or retarget"},
                         {"format": "RenderWare", "coverage": "Chunk structure and embedded string names; native platform payloads remain opaque"},
                         {"format": "WoW", "coverage": "M2/BLP headers; optional installed GgEngine decoder for supported versions"},
                         {"format": "ELF / MIPS", "coverage": "Header identity; existing Ghidra jobs provide function analysis"},
                         {"format": "Jak / Ratchet / Vexx / Sly / other", "coverage": "Game-independent workflow; proprietary title formats need an adapter or extracted common-format assets"}],
            "store": str(common.ROOT), "operations": sorted(OPERATIONS),
            "limits": {"asset_bytes": common.MAX_FILE, "index_files": scout.MAX_FILES, "collection_rows": scout.MAX_CATALOG,
                       "collections": scout.MAX_COLLECTIONS, "batch_files": collections.MAX_BATCH_FILES,
                       "batch_bytes": collections.MAX_BATCH_BYTES, "catalog_rows": scout.MAX_TOTAL_ROWS,
                       "semantic_search": "NOT_INSTALLED", "automatic_candidate_acceptance": False, "original_asset_writes": False}}


def inspect_asset(raw: str, *, native: bool = False) -> dict:
    path, data = common.read_file(raw)
    observed = formats.inspect(data, path.suffix)
    result = {"status": "READY", "summary": path.name + " · " + observed["format"] + " · " + observed["coverage"],
              "path": str(path), "sha256": common.digest(data), "bytes": len(data), **observed}
    if not native:
        result.update(dependencies.observe(path, data, observed, dependencies.selected_root(path)))
    if native:
        if path.suffix.lower() not in (".m2", ".mdx", ".blp", ".wmo", ".adt", ".tga"):
            raise ValueError("NO_NATIVE_ADAPTER_FOR_FORMAT")
        from backend.game_engine_adapter_formats import NativeFormats
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("NATIVE_SOURCE_LIMIT_16_MIB")
        # Decode the inspected bytes, not a second mutable read of the source.
        with tempfile.TemporaryDirectory(prefix="gg-game-native-snapshot-") as temporary:
            snapshot = Path(temporary) / path.name
            snapshot.write_bytes(data)
            reader = NativeFormats(root=Path(temporary))
            try:
                metadata, blob = reader.decode(snapshot, timeout=3)
            finally:
                reader.close()
        # Confirm the source did not change while the separate reader used it.
        if common.digest(common.read_file(path)[1]) != result["sha256"]:
            raise ValueError("ASSET_CHANGED_DURING_NATIVE_DECODE")
        result["native_metadata"] = metadata
        result["native_format"] = metadata.get("format", "UNKNOWN")
        result["coverage"] = "GG_ENGINE_DECODED_METADATA"
        result["summary"] = path.name + " · installed GgEngine adapter decoded the selected file"
        if metadata.get("blob_kind") == "rgba":
            from PIL import Image
            width, height = metadata.get("width", 0), metadata.get("height", 0)
            if not isinstance(width, int) or not isinstance(height, int) or not 0 < width * height <= 2 * 1024 * 1024 or len(blob) != width * height * 4:
                raise ValueError("INVALID_NATIVE_TEXTURE_PIXELS")
            pixels = io.BytesIO()
            Image.frombytes("RGBA", (width, height), blob).save(pixels, format="PNG")
            image_data = pixels.getvalue()
            record = common.packet("native-preview", {"source": str(path), "sha256": result["sha256"], "metadata": metadata,
                                  "image_sha256": common.digest(image_data)})
            preview = record.with_suffix(".png")
            if preview.exists() and common.digest(common.read_file(preview)[1]) != common.digest(image_data):
                raise ValueError("VISUAL_EVIDENCE_IMAGE_CHANGED")
            if not preview.exists():
                common.write_bytes(preview, image_data)
            result["image"] = preview.as_uri()
        result["limits"] = ["A successful decode does not prove compatibility with every WoW client, platform or game runtime."]
    elif observed["format"] in ("GLB", "GLTF"):
        from backend import game_engine_assets
        if path.is_relative_to(game_engine_assets.ASSET_ROOT.resolve()):
            result["runtime_validation"] = game_engine_assets.inspect_asset(str(path))
    return result


def execute(operation: str, payload: dict) -> dict:
    try:
        if operation not in OPERATIONS or not isinstance(payload, dict):
            raise ValueError("UNKNOWN_GAME_WORKFLOW_OPERATION")
        if operation == "scout_index":
            result = scout.index(str(payload.get("path", "")), str(payload.get("game", "")))
        elif operation == "scout_collections":
            result = collections.plan(str(payload.get("path", "")))
        elif operation == "scout_batch":
            result = collections.batch(str(payload.get("path", "")), str(payload.get("game", "")), str(payload.get("cursor", "")),
                                       payload.get("batch_files", 128), payload.get("recursive") is not False,
                                       payload.get("partition", 0), payload.get("partitions", 1))
        elif operation == "scout_batch_cancel":
            result = collections.cancel(str(payload.get("cursor", "")))
        elif operation == "scout_relations":
            result = scout.relations(str(payload.get("key", "")))
        elif operation == "rig_trial":
            result = rig.trial(str(payload.get("path", "")), str(payload.get("animation", "")), payload.get("fps", 0), str(payload.get("basis", "")))
        elif operation == "asset_profile":
            from backend import game_workflow_profile
            result = game_workflow_profile.plan(payload.get("assets", []))
        elif operation == "scene_measure":
            from backend import game_workflow_profile
            result = game_workflow_profile.measure(str(payload.get("path", "")), payload.get("samples", 24))
        elif operation == "scout_search":
            result = scout.search(str(payload.get("query", "")), str(payload.get("game", "")), str(payload.get("kind", "")), payload.get("limit", 32))
        elif operation == "scout_inspect":
            result = inspect_asset(str(payload.get("path", "")), native=payload.get("native") is True)
        elif operation == "scout_annotate":
            result = scout.annotate(str(payload.get("key", "")), str(payload.get("tags", "")), str(payload.get("note", "")))
        elif operation == "scout_visual":
            result = scout.contact_sheet(payload.get("keys", []))
        elif operation == "context_job":
            result = context.from_job(str(payload.get("job_id", "")))
        elif operation == "context_export":
            result = context.from_export(str(payload.get("path", "")), str(payload.get("target", "")), str(payload.get("query", "")))
        elif operation == "verify_candidate":
            result = verify.verify(str(payload.get("context", "")), str(payload.get("candidate", "")), syntax=payload.get("syntax") is True)
        elif operation == "flow_import":
            result = flow.import_map(str(payload.get("path", "")), str(payload.get("game", "")))
        elif operation == "flow_check":
            _, document, _ = common.read_json(str(payload.get("path", "")))
            result = flow.save(document)
        else:
            result = flow.export_map(str(payload.get("path", "")))
        return {"schema": common.SCHEMA, **result}
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError, RuntimeError, TimeoutError) as exc:
        return common.error(exc)
