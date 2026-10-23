"""Portable function context from GG engine jobs or explicit Ghidra exports.

The offline export workflow is inspired by Dryxio/ghidra-bridge (MIT). Address
spaces are preserved, names must resolve unambiguously, and all inputs are bound
to exact artifact bytes. Imported analysis remains externally unverified.
"""
from __future__ import annotations

import re
from pathlib import Path

from backend import game_workflow_common as common, game_workflow_formats as formats

SCHEMA = "gg.game-workflows.context.v1"
MAX_EXPORTS = 256
MAX_EXPORT_BYTES = 16 * 1024 * 1024


def address(value: str) -> str:
    match = re.fullmatch(r"(?:(?P<space>[A-Za-z_][A-Za-z0-9_]{0,31}):)?(?:0[xX])?(?P<hex>[0-9a-fA-F]{1,16})", str(value).strip())
    if not match:
        raise ValueError("INVALID_ADDRESS")
    prefix = (match["space"] + ":") if match["space"] else ""
    return prefix + hex(int(match["hex"], 16))


def _artifact(raw):
    path, data = common.read_file(raw)
    try:
        observation = formats.inspect(data, path.suffix)
    except (ValueError, OSError):
        observation = {"format": "OPAQUE", "metadata": {}}
    return {"path": str(path), "sha256": common.digest(data), "bytes": len(data),
            "format": observation["format"], "architecture": observation.get("metadata", {}).get("architecture", "UNKNOWN")}


def _function(value: dict, query: str = "") -> dict:
    if not isinstance(value, dict):
        raise ValueError("FUNCTION_OBJECT_REQUIRED")
    nested = value.get("function") if isinstance(value.get("function"), dict) else value
    procedure = value.get("procedure") if isinstance(value.get("procedure"), dict) else nested
    raw_address = procedure.get("address", procedure.get("entry", ""))
    code = value.get("pseudocode", value.get("decompiled", value.get("decompiled_code", value.get("code", ""))))
    if not isinstance(code, str) or len(code) > 128 * 1024:
        raise ValueError("PSEUDOCODE_LIMIT")
    result = {"name": str(procedure.get("full_name", procedure.get("name", query)))[:256],
              "address": address(str(raw_address)) if raw_address else "",
              "signature": str(procedure.get("signature", ""))[:4096], "pseudocode": code}
    for field in ("callers", "callees", "strings", "globals", "types", "pcode", "cfg", "asm"):
        item = value.get(field)
        if item is not None:
            # The input JSON has already passed the common size/depth limits.
            result[field] = item
    return result


def _save(artifact, function, provenance, sources, *, evidence_binding: str):
    value = {"schema": SCHEMA, "artifact": artifact, "function": function, "provenance": provenance,
             "evidence_binding": evidence_binding, "sources": sources,
             "limits": ["Pseudocode and structural IR are analysis evidence, not proof of equivalent behavior.",
                        "Missing P-code, CFG, types or dependencies remain missing; no game-specific values are invented."]}
    path = common.packet("context", value)
    return {"status": "READY", "summary": (function["name"] or function["address"] or "Function context") + " · " + provenance,
            "packet_path": str(path), "context": value}


def from_job(job_id: str) -> dict:
    from backend import research_jobs
    state = research_jobs.status(job_id)
    report = state.get("report", {})
    if state.get("status") != "COMPLETE" or state.get("operation") not in ("function", "decompile", "xrefs"):
        raise ValueError("COMPLETE_FUNCTION_JOB_REQUIRED")
    artifact = _artifact(report.get("path", ""))
    if artifact["sha256"] != report.get("artifact_sha256"):
        raise ValueError("ARTIFACT_CHANGED_RERUN_ANALYSIS")
    normalized = report.get("content", {}).get("normalized_result")
    query = str(state.get("query", ""))
    if isinstance(normalized, str):
        source = {"name": query, "pseudocode": normalized}
        try:
            source["address"] = address(query)
        except ValueError:
            pass
    elif isinstance(normalized, dict):
        source = dict(normalized)
    elif isinstance(normalized, list) and state["operation"] == "xrefs":
        source = {"name": query, "callers": normalized}
    else:
        raise ValueError("FUNCTION_RESULT_NOT_AVAILABLE")
    sources = [{"job_id": job_id, "operation": state["operation"], "engine": report.get("engine", "")}]
    # Enrich only with completed jobs for exactly the same artifact and query.
    for item in research_jobs.history()["jobs"]:
        if item.get("job_id") == job_id or item.get("status") != "COMPLETE" or item.get("query") != query:
            continue
        peer = research_jobs.status(item["job_id"])
        peer_report = peer.get("report", {})
        if peer_report.get("artifact_sha256") != artifact["sha256"]:
            continue
        result = peer_report.get("content", {}).get("normalized_result")
        if item.get("operation") == "decompile" and isinstance(result, str):
            source.setdefault("pseudocode", result)
        elif item.get("operation") == "function" and isinstance(result, dict):
            for key, val in result.items():
                source.setdefault(key, val)
        elif item.get("operation") == "xrefs" and isinstance(result, list):
            source.setdefault("callers", result)
        else:
            continue
        sources.append({"job_id": item["job_id"], "operation": item["operation"], "engine": peer_report.get("engine", "")})
    return _save(artifact, _function(source, query), "LOCAL_ENGINE_STATIC_OBSERVATION", sources,
                 evidence_binding="ENGINE_JOB_TARGET_DIGEST")


def _export_files(path: Path):
    if path.is_file():
        return [path]
    # No recursive wildcard fallback. Users select the actual export directory.
    files = []
    for index, item in enumerate(path.iterdir()):
        if index >= 1024:
            raise ValueError("EXPORT_DIRECTORY_ENTRY_LIMIT")
        if item.suffix.lower() == ".json" and item.is_file() and not item.is_symlink() and item.name not in ("index.json", "address_map.json"):
            files.append(item)
            if len(files) > MAX_EXPORTS:
                raise ValueError("EXPORT_FILE_LIMIT_SELECT_FUNCTION_FILE")
    return sorted(files)


def from_export(raw: str, target: str, query: str) -> dict:
    path = common.local_path(raw)
    query = str(query).strip()
    if not query or len(query) > 256 or any(c in query for c in ("/", "\\", "\0")):
        raise ValueError("EXACT_FUNCTION_NAME_OR_ADDRESS_REQUIRED")
    artifact = _artifact(target)
    matches, total = [], 0
    try:
        target_address = address(query)
    except ValueError:
        target_address = ""
    for candidate in _export_files(path):
        resolved, data = common.read_file(candidate, common.MAX_JSON, root=path if path.is_dir() else path.parent)
        total += len(data)
        if total > MAX_EXPORT_BYTES:
            raise ValueError("EXPORT_BYTE_LIMIT")
        value = common.parse_json(data)
        claimed_hash = value.get("artifact_sha256", value.get("artifact", {}).get("sha256") if isinstance(value.get("artifact"), dict) else None)
        if claimed_hash and claimed_hash != artifact["sha256"]:
            raise ValueError("EXPORT_TARGET_DIGEST_MISMATCH")
        function = _function(value)
        if (target_address and function["address"] == target_address) or function["name"] == query:
            matches.append((function, {"path": str(resolved), "sha256": common.digest(data)}))
    if not matches:
        raise ValueError("FUNCTION_NOT_FOUND_USE_EXACT_NAME_OR_ADDRESS")
    if len(matches) != 1:
        return {"status": "AMBIGUOUS", "summary": "Multiple functions match. Select a function file or an address with its address space.",
                "matches": [{"name": f["name"], "address": f["address"], "path": s["path"]} for f, s in matches]}
    function, source = matches[0]
    return _save(artifact, function, "EXTERNAL_EXPORT_UNVERIFIED", [source], evidence_binding="USER_SELECTED_TARGET_DIGEST")


def load(raw: str) -> dict:
    _, value, _ = common.read_json(raw)
    if value.get("schema") != SCHEMA or not isinstance(value.get("artifact"), dict):
        raise ValueError("CONTEXT_PACKET_REQUIRED")
    artifact = _artifact(value["artifact"].get("path", ""))
    if artifact["sha256"] != value["artifact"].get("sha256"):
        raise ValueError("ARTIFACT_CHANGED_RERUN_ANALYSIS")
    value["function"] = _function(value.get("function", {}))
    return value
