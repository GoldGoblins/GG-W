"""Bounded, RAM-only screen observations for Codex and the desktop UI.

Capture is separate from inference: fps describes received frames, never
model reasoning. Nothing in this module records a movie or runs actions.
"""
from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from backend.platform_support import find_executable

PROJECT = Path(__file__).resolve().parents[1]
TARGET_FPS = 25
RING_SECONDS = 6.0
MAX_RING_BYTES = 32 * 1024 * 1024
MAX_DETAIL_BYTES = 32 * 1024 * 1024
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_REPLY_BYTES = 48 * 1024 * 1024
IDLE_SECONDS = 15 * 60
SESSION_SECONDS = 4 * 60 * 60


def ram_root() -> Path:
    """Refuse a disk fallback; the socket, status and view files use tmpfs."""
    if os.name == "nt":
        raise RuntimeError("RAM-only screen capture is not available on Windows.")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    candidates = [runtime / "gg-eyes", Path(f"/dev/shm/gg-eyes-{os.getuid()}")]
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        mounts.append((Path(left.split()[4].replace("\\040", " ")), right.split()[0]))
    for root in candidates:
        parent = root.parent.resolve()
        matches = [(mount, kind) for mount, kind in mounts if parent.is_relative_to(mount)]
        if not matches or max(matches, key=lambda item: len(str(item[0])))[1] != "tmpfs":
            continue
        if not parent.is_dir() or root.is_symlink():
            continue
        root.mkdir(mode=0o700, exist_ok=True)
        if root.stat().st_uid != os.getuid():
            continue
        root.chmod(0o700)
        return root
    raise RuntimeError("Ingen RAM-baserad körningskatalog finns; disk används inte som reserv.")


def atomic_ram_file(name: str, data: bytes) -> Path:
    if Path(name).name != name or not name.endswith((".json", ".jpg")):
        raise ValueError("Invalid observation filename")
    root = ram_root()
    path = root / name
    temporary = root / (name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)
    return path


@dataclass(frozen=True)
class Frame:
    seq: int
    captured: float
    pts: float | None
    data: bytes
    width: int
    height: int

    def wire(self, now: float) -> dict:
        return {"seq": self.seq, "age_ms": round((now - self.captured) * 1000),
                "pts_seconds": self.pts, "width": self.width, "height": self.height,
                "jpeg": base64.b64encode(self.data).decode("ascii")}


class FrameRing:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.frames: deque[Frame] = deque()
        self.bytes = 0
        self.seq = 0
        self.oversize_drops = 0
        self.delivered_at: float | None = None
        self.delivered_seq: int | None = None

    def clear(self) -> None:
        with self.lock:
            self.frames.clear()
            self.bytes = 0
            self.delivered_at = None
            self.delivered_seq = None

    def append(self, data: bytes, width: int, height: int, pts: float | None,
               *, captured: float | None = None) -> None:
        now = time.monotonic() if captured is None else captured
        with self.lock:
            if len(data) > MAX_FRAME_BYTES:
                self.oversize_drops += 1
                return
            self.seq += 1
            self.frames.append(Frame(self.seq, now, pts, data, width, height))
            self.bytes += len(data)
            while self.frames and (self.bytes > MAX_RING_BYTES or len(self.frames) > 150
                                   or now - self.frames[0].captured > RING_SECONDS):
                self.bytes -= len(self.frames.popleft().data)

    def status(self) -> dict:
        now = time.monotonic()
        with self.lock:
            recent = [f for f in self.frames if now - f.captured <= 2]
            span = recent[-1].captured - recent[0].captured if len(recent) > 1 else 0
            latest = self.frames[-1] if self.frames else None
            return {"target_fps": TARGET_FPS,
                    "received_fps": round((len(recent) - 1) / span, 1) if span > 0 else 0,
                    "buffer_frames": len(self.frames), "buffer_bytes": self.bytes,
                    "buffer_limit_bytes": MAX_RING_BYTES,
                    "buffer_seconds": round(self.frames[-1].captured - self.frames[0].captured, 2) if latest else 0,
                    "frame_age_ms": round((now - latest.captured) * 1000) if latest else None,
                    "last_delivered_age_ms": round((now - self.delivered_at) * 1000) if self.delivered_at else None,
                    "last_delivered_seq": self.delivered_seq,
                    "oversize_drops": self.oversize_drops,
                    "storage": "RAM", "model_analysis_fps": None}

    def observation(self, *, seconds: float = 0, fps: float = 25, age: float = 0) -> dict:
        now = time.monotonic()
        seconds, fps, age = float(seconds), float(fps), float(age)
        if not all(math.isfinite(v) for v in (seconds, fps, age)):
            raise ValueError("Invalid time or frame rate")
        if not 0 <= seconds <= RING_SECONDS or not 1 <= fps <= 25 or not 0 <= age <= RING_SECONDS:
            raise ValueError("Observation must fit the six second, 25 fps buffer")
        with self.lock:
            if not self.frames:
                raise RuntimeError("Ingen bild finns ännu. Välj skärmen i Fedoras delningsruta.")
            latest = self.frames[-1]
            if now - latest.captured > 2:
                raise RuntimeError("Skärmbilden är äldre än två sekunder. Kontrollera fångstens status.")
            if seconds == 0:
                target = latest.captured - age
                if target < self.frames[0].captured - 0.1:
                    raise RuntimeError("Den efterfrågade bilden har lämnat RAM-bufferten.")
                selected = [min(self.frames, key=lambda f: abs(f.captured - target))]
            else:
                available = [f for f in self.frames if latest.captured - f.captured <= seconds]
                # PipeWire's negotiated 25 fps can alternate 33/50 ms on a
                # 60 Hz desktop. Do not discard those frames a second time.
                selected = available if fps == TARGET_FPS else []
                if fps < TARGET_FPS:
                    origin = available[0].captured
                    for index in range(int((latest.captured - origin) * fps) + 1):
                        target = origin + index / fps
                        frame = min(available, key=lambda f: abs(f.captured - target))
                        if not selected or selected[-1].seq != frame.seq:
                            selected.append(frame)
            self.delivered_at = now
            self.delivered_seq = selected[-1].seq
            gaps = [b.captured - a.captured for a, b in zip(selected, selected[1:])]
            return {"source": "screen", "requested_fps": fps, "frames": [f.wire(now) for f in selected],
                    "coverage_seconds": round(selected[-1].captured - selected[0].captured, 3),
                    "largest_gap_ms": round(max(gaps, default=0) * 1000),
                    "requested_seconds": seconds, "frame_count": len(selected),
                    "delivery_means": "Images supplied to a tool; this does not assert that a model analyzed them."}


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(min(65536, length - len(chunks)))
        if not chunk:
            raise RuntimeError("Screen connection closed")
        chunks.extend(chunk)
    return bytes(chunks)


def request(op: str, *, timeout: float = 8, **parameters) -> dict:
    if os.name == "nt":
        from backend.windows_vision import request as windows_request
        return windows_request(op, timeout=timeout, **parameters)
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(timeout)
        sock.connect(str(ram_root() / "capture.sock"))
        body = json.dumps({"op": op, **parameters}, allow_nan=False).encode()
        sock.sendall(struct.pack("!I", len(body)) + body)
        size = struct.unpack("!I", _recv_exact(sock, 4))[0]
        if size > MAX_REPLY_BYTES:
            raise RuntimeError("Observation exceeds transport limit")
        result = json.loads(_recv_exact(sock, size))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Screen request failed"))
    return result["result"]


def ensure_service() -> None:
    if os.name == "nt":
        # Windows observations use short-lived, bounded child processes.
        return
    import fcntl
    root = ram_root()
    with (root / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            request("status", timeout=0.5)
            return
        except (OSError, RuntimeError):
            pass
        script = PROJECT / "gg-eyes"
        native = Path.home()/".local/lib/goldgoblins/gg-eyes-capture"
        command = [str(native)] if native.is_file() else [sys.executable,"-B",str(script),"serve"]
        subprocess.Popen(command, cwd=PROJECT,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                request("status", timeout=0.25)
                return
            except (OSError, RuntimeError):
                time.sleep(0.05)
        raise RuntimeError("Skärmfångstens tjänst kunde inte starta.")


def ui_status() -> str:
    if os.name == "nt":
        from backend.windows_vision import status
        return json.dumps(status(), ensure_ascii=False)
    try:
        path = ram_root() / "status.json"
        value = json.loads(path.read_text()) if path.stat().st_size < 8192 else {}
        if time.time() - float(value.get("updated_at", 0)) > 3:
            return json.dumps({"state": "off", "reason": "Fångsten svarar inte"})
        return json.dumps(value, ensure_ascii=False)
    except (OSError, ValueError, RuntimeError):
        return '{"state":"off"}'


def stop_if_running() -> None:
    try:
        request("stop", timeout=0.3)
    except (OSError, RuntimeError):
        pass


def image_parts(observation: dict, *, sequence: bool = False, crop: list[int] | None = None) -> list[dict]:
    """Return images directly to MCP; contact sheets preserve every selected frame."""
    from PIL import Image, ImageDraw
    frames = observation["frames"]
    meta = {k: v for k, v in observation.items() if k != "frames"}
    meta["timeline"] = [{k: v for k, v in f.items() if k != "jpeg"} for f in frames]
    parts = [{"type": "text", "text": json.dumps(meta, ensure_ascii=False)}]
    if not sequence:
        data = base64.b64decode(frames[0]["jpeg"])
        crop_x, crop_y = 0, 0
        original_width, original_height = frames[0].get("width"), frames[0].get("height")
        if crop is not None:
            image = Image.open(io.BytesIO(data))
            x, y, w, h = (int(v) for v in crop)
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image.width or y + h > image.height:
                raise ValueError("Crop is outside the returned image")
            stream = io.BytesIO()
            image.crop((x, y, x + w, y + h)).save(stream, "JPEG", quality=94, subsampling=0)
            data = stream.getvalue()
            crop_x, crop_y = x, y
            meta["crop_in_frame_pixels"] = [x, y, w, h]
            meta["timeline"][0].update(width=w, height=h)
        source_size = meta.get("source_size")
        position = meta.get("source_position") or [0, 0]
        if source_size and original_width and original_height:
            scale_x, scale_y = source_size[0] / original_width, source_size[1] / original_height
            meta["image_to_monitor"] = {
                "coordinate_space": meta.get("source_coordinate_space",
                    "monitor logical coordinates; subtract the app window origin for app-local clicks"),
                "scale": [scale_x, scale_y],
                "offset": [position[0] + crop_x * scale_x, position[1] + crop_y * scale_y]}
        parts[0]["text"] = json.dumps(meta, ensure_ascii=False)
        parts.append({"type": "image", "mimeType": "image/jpeg", "data": base64.b64encode(data).decode()})
        return parts
    for first in range(0, len(frames), 25):
        group = frames[first:first + 25]
        columns = min(5, len(group))
        board = Image.new("RGB", (columns * 320, math.ceil(len(group) / columns) * 204), "#181818")
        draw = ImageDraw.Draw(board)
        for index, frame in enumerate(group):
            image = Image.open(io.BytesIO(base64.b64decode(frame["jpeg"])))
            image.thumbnail((320, 180))
            x, y = (index % columns) * 320, (index // columns) * 204
            board.paste(image, (x + (320 - image.width) // 2, y))
            label = f"#{frame['seq']}  t={frame['pts_seconds']:.3f}s" if frame["pts_seconds"] is not None else f"#{frame['seq']} age={frame['age_ms']}ms"
            draw.text((x + 5, y + 183), label, fill="white")
        stream = io.BytesIO()
        board.save(stream, "JPEG", quality=90)
        parts.append({"type": "image", "mimeType": "image/jpeg", "data": base64.b64encode(stream.getvalue()).decode()})
    return parts


def export_parts(parts: list[dict]) -> dict:
    """Fixed RAM filenames for this session's file-based image tool."""
    paths = []
    for index, part in enumerate(p for p in parts if p["type"] == "image"):
        path = atomic_ram_file(f"view-{index}.jpg", base64.b64decode(part["data"]))
        paths.append(str(path))
    for path in ram_root().glob("view-*.jpg"):
        if str(path) not in paths:
            path.unlink(missing_ok=True)
    return {"images": paths, "metadata": [json.loads(p["text"]) for p in parts if p["type"] == "text"]}


def video_observation(source: str, *, start: float = 0, seconds: float = 2, fps: float = 25) -> dict:
    """Decode only a requested interval, through pipes, with decoder timestamps.

    URLs resolve to media streams; no browser cookies, recording, model
    weights or paid service are needed. This supplies visual evidence, not
    an automatic claim that an entire video has been watched or understood.
    """
    import re
    import shutil
    start, seconds, fps = float(start), float(seconds), float(fps)
    if not all(math.isfinite(v) for v in (start, seconds, fps)) or start < 0 or not 0 < seconds <= 6 or not 1 <= fps <= 25:
        raise ValueError("Video interval must be 0–6 seconds at 1–25 fps")
    if not source or len(source) > 4096:
        raise ValueError("Invalid video source")
    parsed = urlparse(source)
    title, duration = "", None
    stream_source = source
    headers = {}
    if parsed.scheme in {"http", "https"}:
        downloader = find_executable("yt-dlp")
        if not downloader:
            raise RuntimeError("yt-dlp is not installed")
        try:
            completed = subprocess.run([downloader, "--no-cache-dir", "--no-playlist", "--skip-download",
                                        "--no-warnings", "--dump-single-json", "-f",
                                        "best[height<=720]/bestvideo[height<=720]/best", "--", source],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Videolänken svarade inte inom en minut.") from None
        if completed.returncode:
            raise RuntimeError("Videolänken kunde inte öppnas. Ingen film sparades.")
        metadata = json.loads(completed.stdout)
        stream_source = metadata.get("url", "")
        if urlparse(stream_source).scheme not in {"http", "https"}:
            raise RuntimeError("The link did not resolve to a media stream")
        title, duration = metadata.get("title", ""), metadata.get("duration")
        headers = metadata.get("http_headers", {})
    elif (parsed.scheme and not (os.name == 'nt' and Path(source).is_absolute())) or not Path(source).is_file():
        raise ValueError("Use a public video URL or an existing local video file")
    command = [find_executable("ffmpeg") or "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info"]
    if parsed.scheme in {"http", "https"}:
        command += ["-rw_timeout", "15000000"]
        safe_headers = {k: v for k, v in headers.items() if k.lower() in {"user-agent", "referer", "origin"}
                        and "\r" not in str(v) and "\n" not in str(v)}
        if safe_headers:
            command += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in safe_headers.items())]
    command += ["-ss", str(start), "-i", stream_source, "-t", str(seconds), "-an", "-sn",
                "-vf", f"fps={fps},scale=w='min(1600,iw)':h=-2,showinfo",
                "-c:v", "mjpeg", "-q:v", "3", "-f", "image2pipe", "pipe:1"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames, timestamps = [], {}
    pending = bytearray()
    byte_count = 0
    exceeded = False
    timed_out = threading.Event()
    def expire():
        timed_out.set()
        process.kill()
    timer = threading.Timer(60, expire)
    timer.start()
    def read_timestamps():
        for raw in process.stderr:
            match = re.search(rb"n:\s*(\d+).*?pts_time:([\d.eE+-]+)", raw)
            if match and int(match[1]) < 151:
                timestamps[int(match[1])] = start + float(match[2])
    reader = threading.Thread(target=read_timestamps, daemon=True)
    reader.start()
    try:
        while chunk := process.stdout.read(65536):
            pending.extend(chunk)
            if len(pending) > MAX_FRAME_BYTES:
                exceeded = True
                process.kill()
                break
            while True:
                end = pending.find(b"\xff\xd9")
                if end < 0:
                    break
                data = bytes(pending[:end + 2])
                del pending[:end + 2]
                byte_count += len(data)
                if byte_count > MAX_RING_BYTES or len(frames) >= 150:
                    exceeded = True
                    process.kill()
                    break
                frames.append({"seq": len(frames) + 1, "age_ms": 0, "jpeg": base64.b64encode(data).decode()})
            if exceeded:
                break
        process.wait(timeout=5)
        reader.join(timeout=2)
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    if exceeded or timed_out.is_set():
        raise RuntimeError("Videosekvensen nådde minnes- eller tidsgränsen. Välj ett kortare avsnitt.")
    if process.returncode or not frames:
        raise RuntimeError("Videosekvensen kunde inte avkodas. Ingen film sparades.")
    if any(i not in timestamps for i in range(len(frames))):
        raise RuntimeError("Decoder timestamps were missing; refusing to invent a timeline")
    for index, frame in enumerate(frames):
        frame["pts_seconds"] = timestamps[index]
    return {"source": source, "title": title, "duration_seconds": duration,
            "start_seconds": start, "requested_seconds": seconds, "requested_fps": fps,
            "frame_count": len(frames), "coverage_seconds": timestamps[len(frames) - 1] - timestamps[0],
            "frames": frames, "audio_analyzed": False, "storage": "RAM"}
