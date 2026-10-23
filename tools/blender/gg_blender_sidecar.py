"""Localhost sidecar that runs *inside* a visible Blender GUI.

Grok talks to this process through the gg-blender MCP.  It binds only to
127.0.0.1 and never opens a network port on other interfaces.  Blender's
timer runs the accept loop so the UI stays interactive.
"""

from __future__ import annotations

import io
import json
import os
import socket
import sys
import traceback
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

import bpy


HOST = "127.0.0.1"
PORT = int(os.environ.get("GG_BLENDER_SIDECAR_PORT", "19876"))
MAX_CODE = 48 * 1024
SCREENSHOT_DEFAULT = Path(tempfile.gettempdir()) / "gg-blender-view.png"

_SERVER: socket.socket | None = None
_CLIENTS: dict = {}


def _hide_splash() -> None:
    prefs = getattr(bpy.context, "preferences", None)
    view = getattr(prefs, "view", None) if prefs is not None else None
    if view is not None:
        view.show_splash = False


def _ok(**fields):
    payload = {"ok": True}
    payload.update(fields)
    return payload


def _err(code: str, **fields):
    payload = {"ok": False, "error": code}
    payload.update(fields)
    return payload


def _scene_info() -> dict:
    objects = []
    for obj in list(bpy.data.objects)[:64]:
        objects.append(
            {
                "name": obj.name,
                "type": obj.type,
                "visible": bool(obj.visible_get()) if hasattr(obj, "visible_get") else True,
            }
        )
    mode = "OBJECT"
    try:
        mode = str(bpy.context.mode or "OBJECT")
    except Exception:
        pass
    return _ok(
        blender=bpy.app.version_string,
        objects=objects,
        object_count=len(bpy.data.objects),
        mode=mode,
        filepath=str(bpy.data.filepath or ""),
    )


def _exec_code(code: str) -> dict:
    source = str(code or "")
    if not source.strip():
        return _err("BLENDER_CODE_EMPTY")
    if len(source) > MAX_CODE:
        return _err("BLENDER_CODE_TOO_LARGE")
    stdout = io.StringIO()
    env = {"bpy": bpy, "__name__": "gg_blender_exec"}
    try:
        with redirect_stdout(stdout):
            exec(compile(source, "<gg-blender-mcp>", "exec"), env, env)
    except Exception as exc:
        return _err(
            "BLENDER_EXEC_FAILED",
            detail=type(exc).__name__,
            message=str(exc)[:400],
            traceback="".join(traceback.format_exception_only(type(exc), exc))[:800],
            stdout=stdout.getvalue()[-2000:],
        )
    return _ok(stdout=stdout.getvalue()[-8000:])


def _screenshot(path_value: str) -> dict:
    target = Path(path_value or SCREENSHOT_DEFAULT).expanduser()
    if target.suffix.lower() != ".png":
        target = target.with_suffix(".png")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        bpy.ops.screen.screenshot(filepath=str(target))
    except Exception:
        try:
            bpy.context.scene.render.image_settings.file_format = "PNG"
            bpy.context.scene.render.filepath = str(target)
            bpy.ops.render.opengl(write_still=True, view_context=True)
        except Exception as exc:
            return _err("BLENDER_SCREENSHOT_FAILED", detail=type(exc).__name__)
    if not target.is_file():
        return _err("BLENDER_SCREENSHOT_MISSING", path=str(target))
    size = target.stat().st_size
    # Embedded GL windows often give a tiny black screen.screenshot;
    # the OpenGL viewport capture is the one that actually sees the mesh.
    if size < 20000:
        try:
            bpy.context.scene.render.image_settings.file_format = "PNG"
            bpy.context.scene.render.filepath = str(target)
            bpy.ops.render.opengl(write_still=True, view_context=True)
        except Exception:
            pass
        if target.is_file():
            size = target.stat().st_size
    return _ok(path=str(target), bytes=size)


def _export_glb(path_value: str) -> dict:
    target = Path(path_value or "").expanduser()
    if not str(target):
        return _err("BLENDER_EXPORT_PATH_EMPTY")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        bpy.ops.export_scene.gltf(filepath=str(target), export_format="GLB")
    except Exception as exc:
        return _err("BLENDER_EXPORT_FAILED", detail=type(exc).__name__, message=str(exc)[:400])
    return _ok(path=str(target), bytes=target.stat().st_size if target.is_file() else 0)


def _handle(request: dict) -> dict:
    cmd = str(request.get("cmd") or "").strip().lower()
    if cmd in {"ping", "status"}:
        return _ok(blender=bpy.app.version_string, port=PORT, pid=os.getpid(),
                   background=bpy.app.background, windows=len(bpy.context.window_manager.windows), protocol=3,
                   agent_input=bool(bpy.app.use_event_simulate))
    if cmd == "input":
        folder = str(Path(__file__).resolve().parent)
        if folder not in sys.path:
            sys.path.insert(0, folder)
        import gg_blender_virtual_input
        return gg_blender_virtual_input.dispatch(bpy, request)
    if cmd == "scene":
        return _scene_info()
    if cmd == "exec":
        return _exec_code(str(request.get("code") or ""))
    if cmd == "screenshot":
        return _screenshot(str(request.get("path") or ""))
    if cmd == "export_glb":
        return _export_glb(str(request.get("path") or ""))
    if cmd in {"inspect", "turnaround", "deform_rig", "clean"}:
        folder = str(Path(__file__).resolve().parent)
        if folder not in sys.path:
            sys.path.insert(0, folder)
        try:
            import gg_blender_observe as observe
        except Exception as exc:
            return _err("BLENDER_OBSERVE_IMPORT", detail=type(exc).__name__, message=str(exc)[:400])
        try:
            return observe.dispatch(cmd, request)
        except Exception as exc:
            return _err(
                "BLENDER_OBSERVE_FAILED",
                detail=type(exc).__name__,
                message=str(exc)[:400],
                traceback="".join(traceback.format_exception_only(type(exc), exc))[:800],
            )
    return _err("BLENDER_CMD_UNKNOWN", cmd=cmd)


def _bind() -> socket.socket | None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
        server.listen(8)
        server.setblocking(False)
    except OSError as exc:
        server.close()
        print(f"GG_BLENDER_SIDECAR_BIND_FAILED detail={type(exc).__name__}", file=sys.stderr)
        return None
    print(f"GG_BLENDER_SIDECAR_OK host={HOST} port={PORT}")
    return server


def _pump() -> float:
    global _SERVER
    if _SERVER is None:
        _SERVER = _bind()
        return 0.4
    # Never readline/sendall on Blender's UI timer. Partial or idle clients
    # retain a bounded buffer and yield immediately to the viewport.
    for _ in range(4):
        try:
            conn, _addr = _SERVER.accept()
        except BlockingIOError:
            break
        except OSError:
            _SERVER = None
            return 0.4
        if len(_CLIENTS) >= 8:
            conn.close()
            continue
        conn.setblocking(False)
        _CLIENTS[conn] = {"input": bytearray(), "output": None,
                          "deadline": time.monotonic() + 2}
    for conn, state in list(_CLIENTS.items()):
        close = False
        try:
            if time.monotonic() >= state["deadline"]:
                close = True
            elif state["output"] is not None:
                sent = conn.send(state["output"][:65536])
                state["output"] = state["output"][sent:]
                close = not state["output"]
            else:
                chunk = conn.recv(65536)
                if not chunk:
                    close = True
                else:
                    state["input"].extend(chunk)
                    if len(state["input"]) > 64 * 1024 + 1:
                        close = True
                    elif b"\n" in state["input"]:
                        try:
                            request = json.loads(state["input"].split(b"\n", 1)[0])
                            reply = _handle(request) if isinstance(request, dict) else _err("BLENDER_REQUEST_INVALID")
                        except Exception as exc:
                            reply = _err("BLENDER_SIDECAR_FAULT", detail=type(exc).__name__)
                        encoded = (json.dumps(reply) + "\n").encode("utf-8")
                        if len(encoded) > 2 * 1024 * 1024:
                            encoded = (json.dumps(_err("BLENDER_REPLY_TOO_LARGE")) + "\n").encode()
                        state["output"] = encoded
                        state["input"].clear()
                        state["deadline"] = time.monotonic() + 2
        except BlockingIOError:
            continue
        except OSError:
            close = True
        if close:
            _CLIENTS.pop(conn, None)
            conn.close()
    return 0.025


def register() -> None:
    global _SERVER
    _hide_splash()
    _SERVER = _bind()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.05, persistent=True)
    if not bpy.app.timers.is_registered(_hide_splash):
        bpy.app.timers.register(_hide_splash, first_interval=0.05)


register()
