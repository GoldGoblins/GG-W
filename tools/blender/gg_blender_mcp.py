#!/usr/bin/env python3
"""stdio MCP for the live Blender sidecar hosted in GG AI Desktop EXT.

Tools talk to 127.0.0.1 only.  Screenshots are written to a PNG path so the
chat can read the image; they are not inlined (MCP output is size-capped).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend.blender_contract import (  # noqa: E402
    SCREENSHOT_PATH,
    blender_bin,
    sidecar_call,
    status_payload,
)


PROTOCOL = "2024-11-05"
SERVER_NAME = "gg-blender"
SERVER_VERSION = "1.0.0"


def _text(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        body = payload
    else:
        body = json.dumps(payload, indent=2, ensure_ascii=True)
    return {"content": [{"type": "text", "text": body[:18000]}]}


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"{code}: {message}"}],
        "isError": True,
    }


TOOLS = [
    {
        "name": "status",
        "description": (
            "Blender binary, EXT sidecar reachability and screenshot path. "
            "Open EXT and start Blender in GG AI Desktop if sidecar_up is false."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "scene",
        "description": "List objects and mode in the live visible Blender scene.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "screenshot",
        "description": (
            "Capture the live Blender window to a PNG and return the path. "
            "Read that file to see the viewport."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional PNG path. Defaults to /tmp/gg-blender-view.png",
                }
            },
        },
    },
    {
        "name": "exec",
        "description": (
            "Run Python inside the live Blender GUI (bpy is already imported). "
            "Print values you want returned. Original geometry only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to exec in Blender."}
            },
            "required": ["code"],
        },
    },
    {
        "name": "inspect",
        "description": (
            "Measure meshes and armatures in the live Blender scene. "
            "Returns boundary edges, hole loops, non-manifold junctions, "
            "tri/quad/ngon counts, and which anatomy joints are missing. "
            "A picture is not a measurement; call this before and after edits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional mesh name. Empty measures every mesh."}
            },
        },
    },
    {
        "name": "turnaround",
        "description": (
            "Render front, side, back, three-quarter and a front wireframe "
            "with the Workbench engine. Read every PNG before judging the mesh. "
            "One User Perspective screenshot hides holes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional mesh name. Empty frames every mesh."},
                "directory": {"type": "string", "description": "PNG directory. Default /tmp/gg-blender-turn"},
                "size": {"type": "integer", "description": "Square resolution from 256 to 1024. Default 640."},
                "collection": {"type": "string", "description": "Only render meshes in this collection; hide unrelated objects temporarily."},
                "framing": {"type": "object", "description": "Reuse returned center, distance and ortho_scale for comparable iterations."},
                "style": {"type": "string", "enum": ["clay", "silhouette", "material", "appearance"]},
                "orthographic": {"type": "boolean", "description": "True removes tilt from front/side/back reference views."},
            },
        },
    },
    {
        "name": "deform_rig",
        "description": (
            "Create GG_Deform, a 90-joint deformation skeleton fitted to the "
            "mesh bounds: spine, neck, jaw, eyes, ears, clavicles, fingers, "
            "toes and tail. Does not skin the mesh and does not copy a "
            "reference armature. Refuses to replace an existing GG_Deform "
            "unless replace is true. Engine cap is 128 joints."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional mesh to fit. Empty uses every mesh."},
                "replace": {"type": "boolean", "description": "Replace an existing GG_Deform armature."},
            },
        },
    },
    {
        "name": "clean",
        "description": (
            "Dry-run unless apply is true. mode fill merges by distance, "
            "fills boundary holes and points normals outward. mode voxel "
            "rebuilds a closed volume and destroys existing edge flow. "
            "Name the mesh when the scene has more than one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "mode": {"type": "string", "description": "fill or voxel. Default fill."},
                "apply": {"type": "boolean", "description": "Must be true to edit the mesh."},
                "merge": {"type": "number", "description": "Merge distance for fill. Default 0.0001."},
                "sides": {"type": "integer", "description": "Max hole sides. 0 fills every hole."},
                "voxel_factor": {"type": "integer", "description": "Diagonal divided by this is the voxel size."},
            },
        },
    },
    {
        "name": "export_glb",
        "description": "Export the current Blender scene as a GLB to a local path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Destination .glb path."}
            },
            "required": ["path"],
        },
    },
]


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    wanted = str(name or "").strip()
    args = arguments if isinstance(arguments, dict) else {}
    if wanted == "status":
        payload = status_payload()
        payload["bin_ok"] = bool(blender_bin())
        return _text(payload)
    if wanted == "scene":
        return _text(sidecar_call("scene"))
    if wanted == "screenshot":
        path = str(args.get("path") or SCREENSHOT_PATH)
        result = sidecar_call("screenshot", path=path)
        return _text(result)
    if wanted == "exec":
        code = str(args.get("code") or "")
        if not code.strip():
            return _error("BLENDER_CODE_EMPTY", "code is required")
        return _text(sidecar_call("exec", code=code))
    if wanted == "inspect":
        return _text(sidecar_call("inspect", name=str(args.get("name") or "")))
    if wanted == "turnaround":
        return _text(sidecar_call(
            "turnaround",
            name=str(args.get("name") or ""),
            directory=str(args.get("directory") or ""),
            size=int(args.get("size") or 640),
            collection=str(args.get("collection") or ""),
            framing=args.get("framing"),
            style=str(args.get("style") or "clay"),
            orthographic=bool(args.get("orthographic")),
        ))
    if wanted == "deform_rig":
        return _text(sidecar_call(
            "deform_rig",
            name=str(args.get("name") or ""),
            replace=bool(args.get("replace")),
        ))
    if wanted == "clean":
        return _text(sidecar_call(
            "clean",
            name=str(args.get("name") or ""),
            mode=str(args.get("mode") or "fill"),
            apply=bool(args.get("apply")),
            merge=float(args.get("merge") if args.get("merge") is not None else 0.0001),
            sides=int(args.get("sides") or 0),
            voxel_factor=int(args.get("voxel_factor") or 80),
        ))
    if wanted == "export_glb":
        path = str(args.get("path") or "")
        if not path.strip():
            return _error("BLENDER_EXPORT_PATH_EMPTY", "path is required")
        return _text(sidecar_call("export_glb", path=path))
    return _error("BLENDER_TOOL_UNKNOWN", wanted)


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    msg_id = message.get("id")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        result = _call_tool(str(params.get("name") or ""), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        text = line.decode("utf-8")
        if text in ("\r\n", "\n"):
            break
        if ":" in text:
            key, value = text.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        return None
    body = sys.stdin.buffer.read(length)
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + encoded)
    sys.stdout.buffer.flush()


def main() -> int:
    while True:
        message = _read_message()
        if message is None:
            return 0
        reply = _handle(message)
        if reply is not None:
            _write_message(reply)


if __name__ == "__main__":
    raise SystemExit(main())
