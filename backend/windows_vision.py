"""Short, on-demand Windows screen observations over bounded RAM pipes.

Pillow uses Win32 screen capture here, not Qt or a call into the desktop app.
Each observation owns one hidden child process and ends when it is delivered.
There is no capture daemon, image file, shared-memory file or TCP listener.
"""
from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend.live_vision import (FrameRing, MAX_DETAIL_BYTES, MAX_REPLY_BYTES,
                                RING_SECONDS, TARGET_FPS)

PREVIEW_SIZE = (960, 540)
DETAIL_SIZE = (4096, 2160)


def status() -> dict:
    # This getter is also used on the app's UI thread. Never capture or spawn
    # from it, and never report "live" merely because a provider is installed.
    return {"state": "off", "provider": "windows-gdi", "capture_mode": "on_demand",
            "storage": "RAM", "buffer_bytes": 0, "received_fps": 0,
            "frame_age_ms": None, "target_fps": TARGET_FPS,
            "reason": "Windows fångar bilder på begäran; ingen bakgrundsfångst körs."}


def validate(command: dict) -> dict:
    if not isinstance(command, dict) or command.get("op") not in {"frame", "clip"}:
        raise ValueError("Invalid Windows screen operation")
    if set(command) - {"op", "seconds", "fps", "age", "region"}:
        raise ValueError("Unknown Windows screen parameter")
    seconds = float(command.get("seconds", 2) if command["op"] == "clip" else 0)
    fps = float(command.get("fps", TARGET_FPS))
    age = float(command.get("age", 0))
    if not all(math.isfinite(value) for value in (seconds, fps, age)):
        raise ValueError("Invalid time or frame rate")
    if (not 0 <= seconds <= RING_SECONDS or not 1 <= fps <= TARGET_FPS
            or (command["op"] == "clip" and seconds == 0)):
        raise ValueError("Observation must fit six seconds and 25 fps")
    if age != 0:
        raise ValueError("Windows on-demand capture retains no past frames; use clip instead of age.")
    region = command.get("region")
    if region is not None:
        if (not isinstance(region, (list, tuple)) or len(region) != 4
                or any(type(value) is not int for value in region)
                or min(region[:2]) < 0 or min(region[2:]) <= 0):
            raise ValueError("Invalid screen region")
        region = list(region)
    return {"op": command["op"], "seconds": seconds, "fps": fps, "region": region}


def request(op: str, *, timeout: float = 8, **parameters) -> dict:
    if op == "status":
        return status()
    if op == "stop":
        return status()
    if op == "start":
        return {**status(), "state": "ready", "requires_selection": False,
                "message": "Windows är redo för frame eller clip på begäran."}
    command = validate({"op": op, **parameters})
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid capture deadline")
    from backend.platform_process import run_bounded
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    # The existing process runner bounds both output and wall time, and kills
    # the helper's entire process tree if a driver stalls. No app process is
    # signalled or asked to render a screenshot.
    code, output, _, trigger = run_bounded(
        [str(executable), "-X", "utf8", "-B", str(Path(__file__).resolve()),
         json.dumps(command, allow_nan=False)], cwd=PROJECT,
        timeout=min(timeout, 8), max_output_bytes=MAX_REPLY_BYTES)
    if trigger != "NONE":
        raise RuntimeError("Windows screen capture stopped: " + trigger)
    if code != 0:
        raise RuntimeError("Windows screen capture helper failed")
    answer = json.loads(output)
    if not answer.get("ok"):
        raise RuntimeError(answer.get("error", "Windows screen capture failed"))
    return answer["result"]


def _screen_size() -> tuple[int, int]:
    import ctypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    try:
        user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        user.SetProcessDPIAware()
    return user.GetSystemMetrics(0), user.GetSystemMetrics(1)


def capture(command: dict, *, grab=None, screen_size=None) -> dict:
    """Capture one bounded interval; injectable source permits headless tests."""
    from PIL import Image, ImageGrab
    command = validate(command)
    if grab is None:
        grab = ImageGrab.grab
    width, height = screen_size if screen_size is not None else _screen_size()
    if width <= 0 or height <= 0 or width * height * 3 > MAX_DETAIL_BYTES:
        raise RuntimeError("Primary screen exceeds the bounded capture size")
    region = command["region"] or [0, 0, width, height]
    x, y, w, h = region
    if x + w > width or y + h > height:
        raise ValueError("Screen region is outside the primary display")
    bbox = (x, y, x + w, y + h)
    ring = FrameRing()
    first = None
    next_at = time.monotonic()
    period = 1 / command["fps"]
    limit = min(150, int(command["seconds"] * command["fps"]) + 1)
    capture_costs = []
    for _ in range(limit):
        remaining = next_at - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        began = time.monotonic()
        with grab(bbox=bbox) as frame:
            captured = time.monotonic()
            capture_costs.append((captured - began) * 1000)
            if first is None:
                first = captured
            if frame.mode != "RGB":
                frame = frame.convert("RGB")
            frame.thumbnail(DETAIL_SIZE if command["op"] == "frame" else PREVIEW_SIZE,
                            Image.Resampling.BILINEAR)
            stream = io.BytesIO()
            frame.save(stream, "JPEG", quality=88 if command["op"] == "frame" else 70)
            ring.append(stream.getvalue(), frame.width, frame.height, None, captured=captured)
        if captured - first >= command["seconds"]:
            break
        next_at = max(next_at + period, time.monotonic())
    result = ring.observation(seconds=command["seconds"], fps=command["fps"])
    measured = ring.status()
    result.update(provider="windows-gdi", capture_mode="on_demand",
                  image_kind="native_detail" if command["op"] == "frame" else "motion_preview",
                  timestamp_kind="capture_completed_monotonic", source_size=[w, h],
                  source_position=[x, y], source_pixel_size=[width, height],
                  source_coordinate_space="primary-screen physical pixels; convert DPI before app-local input",
                  storage="RAM", retained_after_request=False,
                  received_fps=measured["received_fps"], buffer_bytes=measured["buffer_bytes"],
                  buffer_limit_bytes=measured["buffer_limit_bytes"],
                  capture_max_ms=round(max(capture_costs), 2))
    ring.clear()
    return result


def main() -> None:
    try:
        if os.name != "nt":
            raise RuntimeError("Windows capture requires Windows")
        from backend.platform_process import apply_windows_worker_limits
        apply_windows_worker_limits(memory_bytes=256 * 1024**2, cpu_seconds=12)
        result = capture(json.loads(sys.argv[1]))
        packet = json.dumps({"ok": True, "result": result}, allow_nan=False).encode()
        if len(packet) > MAX_REPLY_BYTES:
            raise RuntimeError("Observation exceeds transport limit")
    except (OSError, ValueError, RuntimeError, IndexError) as exc:
        packet = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True).encode()
    sys.stdout.buffer.write(packet)


if __name__ == "__main__":
    main()
