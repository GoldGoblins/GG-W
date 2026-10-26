from __future__ import annotations

from backend.application_paths import DATA_HOME, HOME

import json
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend import libretro_host
from backend.media_contract import (
    MODES,
    SCHEMA,
    STATE_DIR,
    SYSTEMS,
    VIDEO_EXT,
    catalog_for,
    confined,
    ensure_state_dir,
    fetch_download_dir,
    fetch_terminal,
    FETCH_TUI_TITLE,
    format_clock,
    freq_for_now,
    item_id,
    library_roots,
    load_prefs,
    looks_like_url,
    materialize_homebrew,
    nearest_radio_preset,
    EQ_PRESETS,
    SPECTRUM_BARS,
    normalize_eq,
    normalize_spectrum,
    player_bin,
    probe_rf_frontend,
    probe_tools,
    radio_tuner_marks,
    save_prefs,
    search_items,
    stream_allowed,
    which_first,
)


_proc: subprocess.Popen[bytes] | None = None
_cliamp_proc: subprocess.Popen[bytes] | None = None
_files_proc: subprocess.Popen[bytes] | None = None
_fetch_proc: subprocess.Popen[bytes] | None = None
_kind = "audio"
_item: dict[str, Any] | None = None
_paused = False
_embed_tokens: tuple[str, ...] = ()
_rc_sock: Path | None = None
_extra_items: list[dict[str, Any]] = []
_search_mode = ""
_search_query = ""
_search_active = False
_library_busy = False
_library_error = ""
_library_collection = ""
_library_revision = 0
_library_items: dict[str, dict[str, Any]] = {}
_library_children: dict[str, list[dict[str, Any]]] = {}
_library_page_state: dict[str, Any] = {}
_library_page_items: list[dict[str, Any]] = []
_library_fetch_info: dict[str, Any] = {"present": False}
_backend = ""
_catalog_memo: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CATALOG_MEMO_TTL = 45.0
_CLIAMP_POLL_TIMEOUT = 0.04
# Radio streams get the maximum buffer supported by cliamp.  This absorbs
# short network jitter instead of making the listener hear a dropout every
# few seconds.
_CLIAMP_BUFFER_MS = 5000
_CLIAMP_RESUME_GAP = 6.0
_LIVE_TTL = 0.016
_LIVE_PUMP_INTERVAL = 0.016
_want_source = ""
_resume_at = 0.0
_spectrum: list[float] = []
_spectrum_proc: subprocess.Popen[bytes] | None = None
_spectrum_reader: threading.Thread | None = None
_spectrum_start_at = 0.0
_spectrum_frame_at = 0.0
_SPECTRUM_SEGMENTS = 18
_SPECTRUM_FRAME_BYTES = SPECTRUM_BARS * _SPECTRUM_SEGMENTS
_SPECTRUM_FPS = 60
_SPECTRUM_NOISE_FLOOR = 32
# FFmpeg's logarithmic FFT is useful for the low end, but its first half can
# consume too much of the 120-column strip.  A sub-linear source warp keeps
# the bass together on the left and gives the upper bands more room on screen.
_SPECTRUM_FREQ_WARP = 0.50
_last_live_state: dict[str, Any] = {}
_last_live_at = 0.0
_qml_position = 0.0
_qml_duration = 0.0
_qml_playing = False
_qml_buffering = False
_qml_generation = 0
_live_json = ""
_live_payload: dict[str, Any] = {}
_live_lock = threading.Lock()
_cliamp_boot_lock = threading.Lock()
_pump_thread: threading.Thread | None = None
_RF_TTL = 5.0
_rf_cache: tuple[float, dict[str, str]] | None = None
_TUNER_MARKS = radio_tuner_marks()


def _cached_rf() -> dict[str, str]:
    global _rf_cache
    now = time.monotonic()
    hit = _rf_cache
    if hit is not None and now - hit[0] < _RF_TTL:
        return hit[1]
    row = probe_rf_frontend()
    _rf_cache = (now, row)
    return row


def _rc_path() -> Path:
    return ensure_state_dir() / "vlc.sock"


def _cliamp_sock() -> Path:
    return Path.home() / ".config/cliamp/cliamp.sock"


def _clear_socket() -> None:
    path = _rc_path()
    try:
        path.unlink()
    except OSError:
        pass


def _fetch_alive() -> bool:
    return _fetch_proc is not None and _fetch_proc.poll() is None


def _running() -> bool:
    if _backend == "qt_audio":
        from backend import media_qt_audio
        state = media_qt_audio.status()
        return state["playing"] or state["buffering"] or _paused
    if _backend == "cliamp":
        return _cliamp_alive()
    if _backend == "qml":
        return _item is not None
    if _backend == "libretro":
        return libretro_host.loaded()
    if _backend == "torlink":
        return _fetch_alive()
    return _proc is not None and _proc.poll() is None


def player_pid() -> int:
    if _backend == "cliamp" and _cliamp_proc is not None and _cliamp_proc.poll() is None:
        return int(_cliamp_proc.pid)
    if _backend == "torlink" and _fetch_alive() and _fetch_proc is not None:
        return int(_fetch_proc.pid)
    if _proc is None or not _running():
        return 0
    return int(_proc.pid)


def embed_tokens() -> tuple[str, ...]:
    return _embed_tokens


def _stop_proc() -> None:
    global _proc, _paused, _embed_tokens, _rc_sock
    proc = _proc
    _proc = None
    _paused = False
    _embed_tokens = ()
    _rc_sock = None
    if _backend == "qt_audio":
        from backend import media_qt_audio
        media_qt_audio.stop()
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    _clear_socket()


def _spawn_env() -> dict[str, str]:
    env = os.environ.copy()
    extra = [
        str(HOME / '.local/bin'),
        str(Path.home() / ".local/bin"),
        str(DATA_HOME / 'goldgoblins/tools/emu/usr/bin'),
        str(DATA_HOME / 'goldgoblins/tools/node/bin'),
        str(DATA_HOME / 'pnpm'),
        str(DATA_HOME / 'pnpm/bin'),
    ]
    path = str(env.get("PATH") or "")
    env["PATH"] = os.pathsep.join(extra + ([path] if path else []))
    lib = Path(str(DATA_HOME / 'goldgoblins/tools/emu/usr/lib64'))
    if lib.is_dir():
        current = str(env.get("LD_LIBRARY_PATH") or "")
        env["LD_LIBRARY_PATH"] = str(lib) + ((os.pathsep + current) if current else "")
    env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM") or "xcb"
    return env


def _rc_send(command: str) -> str:
    path = _rc_path()
    if not path.exists():
        return ""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.4)
        sock.connect(str(path))
        sock.sendall((command.strip() + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
            if len(b"".join(chunks)) > 8192:
                break
        sock.close()
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _volume_vlc(volume: int) -> int:
    return max(0, min(512, int(round(int(volume) * 5.12))))


def _volume_db(volume: int) -> float:
    return round(-30.0 + 36.0 * (max(0, min(100, int(volume))) / 100.0), 2)


def _cliamp_alive() -> bool:
    if not _cliamp_sock().exists():
        return False
    if _cliamp_proc is not None and _cliamp_proc.poll() is not None:
        return False
    if _last_live_state and time.monotonic() - _last_live_at < 1.0:
        return bool(_last_live_state.get("ok"))
    return bool(_cliamp_call({"cmd": "status"}, timeout=_CLIAMP_POLL_TIMEOUT).get("ok"))


def _cliamp_call(payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    global _last_live_state, _last_live_at
    cmd = str(payload.get("cmd") or "")
    if cmd != "status":
        # Expire the worker's snapshot without blanking the GUI clock/EQ while
        # a command is in flight. Only decoder status replaces the full state.
        _last_live_at = 0.0
    path = _cliamp_sock()
    if not path.exists():
        return {}
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    chunks = b""
    try:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        while True:
            data = sock.recv(16384)
            if not data:
                break
            chunks += data
            if b"\n" in chunks:
                break
    except (OSError, TimeoutError):
        return {}
    finally:
        sock.close()
    text = chunks.decode("utf-8", errors="replace").splitlines()
    if not text:
        return {}
    try:
        parsed = json.loads(text[0])
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    if parsed.get("ok") is True:
        if cmd == "status" and "state" in parsed:
            _last_live_state = dict(parsed)
            _last_live_at = time.monotonic()
        elif cmd != "status":
            live = dict(_last_live_state)
            # Some protocol versions return the changed fields with an ack.
            for key in ("state", "position", "duration", "eq_preset", "eq_bands",
                        "track", "shuffle", "repeat"):
                if key in parsed:
                    live[key] = parsed[key]
            if cmd == "eq":
                if "name" in payload:
                    live["eq_preset"] = str(parsed.get("eq_preset") or payload["name"])
                elif "band" in payload and "eq_bands" not in parsed:
                    bands = normalize_eq(live.get("eq_bands"))
                    index = int(payload["band"])
                    if 0 <= index < len(bands):
                        bands[index] = float(payload.get("value", bands[index]))
                        live["eq_bands"] = bands
            elif cmd == "toggle" and "state" not in parsed:
                state = str(live.get("state") or "")
                if state in ("playing", "paused"):
                    live["state"] = "paused" if state == "playing" else "playing"
            _last_live_state = live
    return parsed


def start_live_pump() -> None:
    global _pump_thread
    # QML video supplies its clock directly.  Only cliamp needs the worker
    # that samples audio bands, so do not leave an idle polling thread behind
    # after changing workspace or stopping media.
    if _backend != "cliamp":
        return
    thread = _pump_thread
    if thread is not None and thread.is_alive():
        return
    thread = threading.Thread(
        target=_live_pump_loop,
        name="gg-media-live",
        daemon=True,
    )
    _pump_thread = thread
    thread.start()


def live_status_json() -> str:
    if _backend == "qt_audio":
        # Qt advances on the desktop thread. The cliamp pump never refreshes
        # this backend, so its initial loading snapshot must not be reused.
        return publish_live()
    start_live_pump()
    with _live_lock:
        raw = _live_json
        spec = list(_spectrum)
        payload = dict(_live_payload)
    if not raw:
        return publish_live(status_payload(live=True))
    if not spec:
        return raw
    if not payload:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
    payload["spectrum"] = spec
    return json.dumps(payload, separators=(",", ":"))


def _store_spectrum_bands(bands: list[Any]) -> None:
    global _spectrum, _spectrum_frame_at
    if not bands:
        return
    now = time.monotonic()
    _spectrum_frame_at = now
    cooked = normalize_spectrum(bands, SPECTRUM_BARS)
    with _live_lock:
        _spectrum = cooked


def _pulse_monitor_source() -> str:
    """Resolve the actual sink monitor, with Pulse's symbolic fallback."""
    pactl = which_first(("pactl",))
    if pactl:
        try:
            raw = subprocess.check_output(
                [pactl, "get-default-sink"],
                env=_spawn_env(),
                stderr=subprocess.DEVNULL,
                timeout=0.4,
            )
            sink = raw.decode("utf-8", errors="replace").strip().splitlines()[0]
            if sink and sink not in {"(none)", "No default sink"}:
                return sink + ".monitor"
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    # pipewire-pulse and PulseAudio both understand this symbolic source.
    return "@DEFAULT_MONITOR@"


def _spectrum_filter() -> str:
    """FFmpeg's established FFT/LED renderer, configured for our meter."""
    return (
        "showspectrum="
        f"size={SPECTRUM_BARS}x{_SPECTRUM_SEGMENTS}:"
        "mode=combined:color=intensity:scale=log:fscale=log:"
        "win_func=hann:overlap=0.5:orientation=horizontal:"
        "slide=fullframe:"
        f"fps={_SPECTRUM_FPS},format=gray"
    )


def _store_spectrum_frame(frame: bytes) -> None:
    """Collapse an FFmpeg grayscale spectrum frame into one LED level/column."""
    if len(frame) != _SPECTRUM_FRAME_BYTES:
        return
    bands: list[float] = []
    for column in range(SPECTRUM_BARS):
        peak = 0
        for row in range(_SPECTRUM_SEGMENTS):
            peak = max(peak, frame[row * SPECTRUM_BARS + column])
        # FFmpeg's dB floor is visible as a faint grey haze.  Remove that
        # floor before handing the levels to the LED renderer so silence and
        # low-level codec noise do not light every frequency equally.
        level = max(
            0.0,
            (peak - _SPECTRUM_NOISE_FLOOR) / (255.0 - _SPECTRUM_NOISE_FLOOR),
        )
        bands.append(level)
    _store_spectrum_bands(_warp_frequency_bands(bands))


def _warp_frequency_bands(bands: list[float]) -> list[float]:
    """Compress the low log-frequency bins without throwing away treble."""
    if len(bands) < 2:
        return bands
    last = len(bands) - 1
    out: list[float] = []
    for index in range(len(bands)):
        position = index / last
        source = position ** _SPECTRUM_FREQ_WARP
        scaled = source * last
        low = int(scaled)
        high = min(last, low + 1)
        fraction = scaled - low
        out.append(bands[low] * (1.0 - fraction) + bands[high] * fraction)
    return out


def _read_spectrum_stream(proc: subprocess.Popen[bytes]) -> None:
    global _spectrum_proc, _spectrum_reader
    stream = proc.stdout
    if stream is None:
        return
    pending = bytearray()
    try:
        while True:
            raw = stream.read(8192)
            if not raw:
                break
            pending.extend(raw)
            while len(pending) >= _SPECTRUM_FRAME_BYTES:
                frame = bytes(pending[:_SPECTRUM_FRAME_BYTES])
                del pending[:_SPECTRUM_FRAME_BYTES]
                _store_spectrum_frame(frame)
    finally:
        try:
            stream.close()
        except OSError:
            pass
        if _spectrum_proc is proc:
            _spectrum_proc = None
        if _spectrum_reader is threading.current_thread():
            _spectrum_reader = None


def _ensure_spectrum_stream() -> None:
    """Keep one real sink-monitor FFT reader beside the cliamp daemon."""
    global _spectrum_proc, _spectrum_reader, _spectrum_start_at
    if _backend != "cliamp" or not _want_source:
        return
    proc = _spectrum_proc
    if proc is not None and proc.poll() is None:
        return
    now = time.monotonic()
    if now - _spectrum_start_at < 1.0:
        return
    binary = which_first(("ffmpeg",))
    if not binary:
        return
    _spectrum_start_at = now
    source = _pulse_monitor_source()
    try:
        proc = subprocess.Popen(
            [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-fflags",
                "nobuffer",
                "-thread_queue_size",
                "64",
                "-f",
                "pulse",
                "-i",
                source,
                "-ac",
                "1",
                "-ar",
                "48000",
                "-filter_complex",
                _spectrum_filter(),
                "-pix_fmt",
                "gray",
                "-f",
                "rawvideo",
                "-",
            ],
            cwd=str(Path.home()),
            env=_spawn_env(),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    _spectrum_proc = proc
    reader = threading.Thread(
        target=_read_spectrum_stream,
        args=(proc,),
        name="gg-media-spectrum",
        daemon=True,
    )
    _spectrum_reader = reader
    reader.start()


def _stop_spectrum_stream() -> None:
    global _spectrum_proc, _spectrum_reader, _spectrum_start_at, _spectrum_frame_at
    proc = _spectrum_proc
    _spectrum_proc = None
    _spectrum_reader = None
    _spectrum_start_at = 0.0
    _spectrum_frame_at = 0.0
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=0.4)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass


def publish_live(payload: dict[str, Any] | None = None) -> str:
    global _live_json, _live_payload
    data = dict(payload) if payload else status_payload(live=True, pump=True)
    data.pop("items", None)
    data.pop("tools", None)
    data.pop("cores", None)
    data.pop("eq_presets", None)
    data.pop("library_roots", None)
    for field in ("library_categories", "library_languages", "library_seasons"):
        data.pop(field, None)
    data["live"] = True
    raw = json.dumps(data, separators=(",", ":"))
    with _live_lock:
        _live_json = raw
        _live_payload = dict(data)
    return raw


def _live_pump_loop() -> None:
    ticks = 0
    while True:
        started = time.monotonic()
        try:
            if _backend != "cliamp":
                return
            _ensure_spectrum_stream()
            ticks += 1
            if ticks == 1 or ticks % 8 == 0:
                publish_live()
        except Exception:
            pass
        delay = _LIVE_PUMP_INTERVAL - (time.monotonic() - started)
        if delay > 0:
            time.sleep(delay)


def _cached_cliamp() -> dict[str, Any]:
    # GUI readers never perform socket IPC. The live-pump worker refreshes this
    # snapshot; its last known state is preferable to blocking paint/input.
    return dict(_last_live_state)


def _cliamp_live(want_bands: bool) -> dict[str, Any]:
    global _last_live_state, _last_live_at
    now = time.monotonic()
    if _last_live_state and now - _last_live_at < _LIVE_TTL:
        live = dict(_last_live_state)
        return live
    live = _cliamp_call({"cmd": "status"}, timeout=_CLIAMP_POLL_TIMEOUT)
    _last_live_state = dict(live) if live else {}
    _last_live_at = now
    if not live.get("ok"):
        return live
    state = str(live.get("state") or "")
    _maybe_resume_stream(state)
    return live


def _maybe_resume_stream(state: str) -> None:
    global _resume_at
    if not _want_source or _paused:
        return
    if state == "playing":
        return
    now = time.monotonic()
    if now < _resume_at:
        return
    _resume_at = now + _CLIAMP_RESUME_GAP
    track = {
        "path": _want_source,
        "stream": True,
        "title": Path(_want_source).name,
    }
    _cliamp_call({"cmd": "track.play", "track": track}, timeout=0.35)


def _catalog_rows(mode: str) -> list[dict[str, Any]]:
    kind = str(mode or "").strip().upper()
    if _search_active and kind == _search_mode:
        return _extra_items[:80]
    if _library_page_state.get("mode") == kind:
        return _library_page_items
    hit = _catalog_memo.get(kind)
    return hit[1][:80] if hit is not None else []


def library_publish_page(payload: dict[str, Any]) -> None:
    global _library_page_state, _library_page_items, _library_revision
    _library_page_state = {key: value for key, value in payload.items() if key != "items"}
    _library_page_items = list(payload.get("items") or [])[:80]
    _library_revision += 1
    # Only visible rows and the current player need GUI-thread lookup state.
    retained = {str(row["id"]): row for row in _library_page_items}
    if _item:
        retained[str(_item["id"])] = _item
    _library_items.clear()
    _library_items.update(retained)


def _group_library(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep every playable ID, presenting series as a single alphabetic entry."""
    from backend.media_library import annotate
    groups: dict[str, list[dict[str, Any]]] = {}
    channels: dict[str, dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    def series_key(row: dict[str, Any]) -> str:
        title = " ".join(str(row.get("series_title") or row.get("title") or "").casefold().split())
        return title + "|" + str(row.get("language") or "").casefold()
    for raw in rows:
        row = annotate(raw)
        _library_items[str(row["id"])] = row
        if row.get("content_type") == "live" and row.get("channel_id"):
            channel_key = str(row["channel_id"]).casefold()
            previous = channels.get(channel_key)
            if previous is not None:
                alternatives = previous.setdefault("alternate_sources", [])
                if row["source"] != previous["source"] and row["source"] not in alternatives:
                    alternatives.append(row["source"])
                continue
            channels[channel_key] = row
        if row.get("content_type") == "episode" and row.get("series_title"):
            key = series_key(row)
            groups.setdefault(key, []).append(row)
        else:
            result.append(row)
    parents = {series_key(row): row
               for row in result if row.get("content_type") == "series"}
    for key, episodes in groups.items():
        episodes.sort(key=lambda row: (int(row.get("season") or 0), int(row.get("episode") or 0), str(row.get("title") or "").casefold()))
        parent = parents.get(key)
        if parent is None:
            parent = dict(episodes[0])
            parent.update(id=item_id("series", key), title=str(parent["series_title"]),
                          content_type="series", media="collection", source="", collection_id=key)
            result.append(parent)
        prior = _library_children.get(str(parent["id"]), [])
        merged = {str(row["id"]): row for row in prior + episodes}
        episodes = sorted(merged.values(), key=lambda row: (int(row.get("season") or 0), int(row.get("episode") or 0), str(row.get("title") or "").casefold()))
        _library_children[str(parent["id"])] = episodes
        parent["episode_count"] = len(episodes)
        _library_items[str(parent["id"])] = parent
    return sorted(result, key=lambda row: str(row.get("title") or "").casefold())


def library_begin() -> None:
    global _library_busy, _library_error
    _library_busy, _library_error = True, ""


def library_finish(rows: list[dict[str, Any]] | None, *, mode: str = "TV", query: str = "", collection: str = "", error: str = "", refresh: bool = False) -> None:
    global _library_busy, _library_error, _library_collection, _library_revision
    global _extra_items, _search_active, _search_mode, _search_query
    _library_busy, _library_error = False, str(error)[:240]
    if rows is not None:
        normalized = _group_library(rows) if not collection else rows
        for row in rows:
            _library_items[str(row["id"])] = row
        if refresh:
            _catalog_memo[mode] = (time.monotonic(), normalized)
        else:
            _extra_items = normalized
            _search_active, _search_mode, _search_query = True, mode, query
            _library_collection = collection
    _library_revision += 1


def library_back() -> dict[str, Any]:
    global _extra_items, _search_active, _search_mode, _search_query, _library_collection, _library_error, _library_busy
    _extra_items = []
    _search_active, _search_mode, _search_query = False, "", ""
    _library_collection, _library_error, _library_busy = "", "", False
    return status_payload()


def library_children(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    return _library_children.get(str(item.get("id") or ""))


def library_store(item: dict[str, Any]) -> None:
    _library_items[str(item["id"])] = item
    for index, row in enumerate(_extra_items):
        if row.get("id") == item["id"]:
            _extra_items[index] = item


def library_state() -> dict[str, Any]:
    state = {"library_busy": _library_busy, "library_error": _library_error,
            "library_query": _search_query, "library_collection": _library_collection,
            "library_revision": _library_revision}
    state.update({key: value for key, value in _library_page_state.items() if key.startswith("library_")})
    state["library_revision"] = _library_revision
    state["library_busy"] = _library_busy
    state["library_error"] = _library_error
    return state


def _cliamp_pid_file() -> Path:
    return _cliamp_sock().parent / "cliamp.sock.pid"


def _cliamp_pid() -> int:
    if _cliamp_proc is not None and _cliamp_proc.poll() is None:
        return int(_cliamp_proc.pid)
    try:
        return int(_cliamp_pid_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _cliamp_buffered() -> bool:
    pid = _cliamp_pid()
    if pid <= 0:
        return False
    try:
        raw = Path("/proc/" + str(pid) + "/cmdline").read_bytes()
    except OSError:
        return False
    marker = b"--buffer-ms\x00" + str(_CLIAMP_BUFFER_MS).encode()
    return marker in raw


def _stop_cliamp_daemon() -> None:
    global _cliamp_proc
    _stop_spectrum_stream()
    _cliamp_call({"cmd": "stop"}, timeout=0.4)
    proc = _cliamp_proc
    _cliamp_proc = None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1.2)
            return
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                pass
            return
    pid = _cliamp_pid()
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(12):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except OSError:
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _ensure_cliamp() -> str:
    global _cliamp_proc
    binary = which_first(("cliamp",))
    if not binary:
        raise RuntimeError("MEDIA_CLIAMP_MISSING")
    with _cliamp_boot_lock:
        if _cliamp_alive() and _cliamp_buffered():
            return binary
        if _cliamp_alive() or (_cliamp_proc is not None and _cliamp_proc.poll() is None):
            _stop_cliamp_daemon()
            time.sleep(0.15)
        _cliamp_sock().parent.mkdir(parents=True, exist_ok=True)
        _cliamp_proc = subprocess.Popen(
            [
                binary,
                "--daemon",
                "--provider",
                "radio",
                "--buffer-ms",
                str(_CLIAMP_BUFFER_MS),
            ],
            cwd=str(Path.home()),
            env=_spawn_env(),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(20):
            time.sleep(0.15)
            if _cliamp_alive():
                return binary
        raise RuntimeError("MEDIA_CLIAMP_DAEMON")


def _halt_audio() -> None:
    global _want_source
    _want_source = ""
    _stop_spectrum_stream()
    if libretro_host.loaded():
        libretro_host.unload()
    if _cliamp_alive():
        _cliamp_call({"cmd": "stop"})
    _stop_proc()


def _is_video_item(item: dict[str, Any]) -> bool:
    kind = str(item.get("kind") or "")
    source = str(item.get("source") or "")
    if kind == "TV":
        return True
    return Path(source).suffix.lower() in VIDEO_EXT


def _play_libretro(item: dict[str, Any]) -> dict[str, Any]:
    global _item, _kind, _backend, _paused
    _halt_audio()
    libretro_host.load(
        str(item.get("system") or ""),
        Path(str(item["source"])),
        ensure_state_dir(),
    )
    _paused = False
    _kind = "game"
    _backend = "libretro"
    _item = item
    save_prefs({"mode": "GAME", "last_id": item["id"]})
    payload = status_payload()
    payload["screen"] = "EMBED"
    return payload


def _play_qml(item: dict[str, Any]) -> dict[str, Any]:
    global _item, _kind, _backend, _paused, _qml_position, _qml_duration
    global _qml_playing, _qml_buffering, _qml_generation
    _halt_audio()
    _qml_position = 0.0
    _qml_duration = 0.0
    _qml_playing = False
    _qml_buffering = True
    # An explicit Play on the same channel must reset an exhausted decoder.
    # Clock/status updates keep this generation unchanged.
    _qml_generation += 1
    _paused = False
    _kind = "video"
    _backend = "qml"
    _item = item
    browse_mode = load_prefs()["mode"]
    target_mode = str(item["kind"])
    if browse_mode in ("TV", "FETCH") and target_mode in ("TV", "FETCH"):
        target_mode = browse_mode
    save_prefs({"mode": target_mode, "last_id": item["id"]})
    payload = status_payload()
    payload["screen"] = "EMBED"
    payload["drawable"] = False
    return payload


def _play_qt_audio(item: dict[str, Any]) -> dict[str, Any]:
    global _item, _kind, _backend, _paused
    from backend import media_qt_audio
    _halt_audio()
    prefs = save_prefs({"mode": str(item["kind"]), "last_id": item["id"]})
    media_qt_audio.play(str(item["source"]), int(prefs["volume"]),
                        live=str(item["kind"]) == "RADIO")
    _item, _kind, _backend, _paused = item, "audio", "qt_audio", False
    return status_payload()


def _play_cliamp(source: str) -> None:
    global _backend, _paused, _kind, _want_source, _resume_at
    wanted = str(source or "")
    _want_source = wanted
    _resume_at = 0.0
    _backend = "cliamp"
    _paused = False
    _kind = "audio"
    start_live_pump()
    threading.Thread(
        target=_play_cliamp_load,
        args=(wanted,),
        name="gg-cliamp-play",
        daemon=True,
    ).start()


def _play_cliamp_load(source: str) -> None:
    if not source or source != _want_source:
        return
    try:
        _ensure_cliamp()
    except RuntimeError:
        return
    if source != _want_source:
        return
    loaded = _cliamp_call({"cmd": "url.load", "path": source}, timeout=20.0)
    if source != _want_source:
        return
    track: dict[str, Any] = {}
    if loaded.get("ok"):
        rows = loaded.get("tracks") or []
        if rows and isinstance(rows[0], dict):
            track = dict(rows[0])
    if not str(track.get("path") or ""):
        track = {"path": source, "stream": True, "title": Path(source).name}
    played = _cliamp_call({"cmd": "track.play", "track": track}, timeout=2.0)
    if source != _want_source:
        return
    if not played.get("ok"):
        queued = _cliamp_call({"cmd": "queue", "path": source}, timeout=2.0)
        if not queued.get("ok") and not loaded.get("ok"):
            return
        status = _cliamp_call({"cmd": "status"}, timeout=0.8)
        total = int(status.get("total") or 0)
        _cliamp_call({"cmd": "queue.play", "index": max(0, total - 1)}, timeout=2.0)
    if source != _want_source:
        return
    prefs = load_prefs()
    _cliamp_call({"cmd": "volume", "value": _volume_db(int(prefs["volume"]))}, timeout=0.4)


def _spawn(argv: list[str], tokens: tuple[str, ...]) -> None:
    global _proc, _paused, _embed_tokens, _rc_sock, _backend
    _stop_proc()
    try:
        _proc = subprocess.Popen(
            argv,
            cwd=str(STATE_DIR),
            env=_spawn_env(),
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _proc = None
        raise RuntimeError("MEDIA_SPAWN_FAILED:" + type(exc).__name__) from exc
    _paused = False
    _embed_tokens = tokens
    _rc_sock = _rc_path() if "--rc-unix" in argv else None
    _backend = "vlc" if any("vlc" in part for part in argv) else "proc"


def _player_argv(source: str, video: bool, drawable_xid: int) -> list[str]:
    binary = player_bin()
    if not binary:
        raise RuntimeError("MEDIA_PLAYER_MISSING")
    name = Path(binary).name
    if video:
        gui = which_first(("vlc", "cvlc"))
        if not gui:
            raise RuntimeError("MEDIA_PLAYER_MISSING")
        argv = [
            gui,
            "--extraintf",
            "rc",
            "--rc-unix",
            str(_rc_path()),
            "--rc-fake-tty",
            "--no-video-title-show",
            "--no-qt-privacy-ask",
            "--no-video-deco",
            "--play-and-stop",
        ]
        if drawable_xid > 0:
            argv.extend(["--drawable-xid", str(int(drawable_xid))])
        argv.append(source)
        return argv
    if name in ("cvlc", "vlc"):
        argv = [
            binary,
            "--intf",
            "rc",
            "--rc-unix",
            str(_rc_path()),
            "--rc-fake-tty",
            "--no-video-title-show",
            "--play-and-stop",
            "--no-video",
            source,
        ]
        return argv
    if name == "ffplay":
        if video:
            return [binary, "-autoexit", "-loglevel", "quiet", source]
        return [binary, "-nodisp", "-autoexit", "-loglevel", "quiet", source]
    return [binary, source]


def _emulator_argv(item: dict[str, Any]) -> tuple[list[str], tuple[str, ...]]:
    system = str(item.get("system") or "")
    spec = SYSTEMS.get(system)
    if spec is None:
        raise RuntimeError("MEDIA_SYSTEM_UNKNOWN")
    binary = which_first(tuple(spec["bins"]))
    if not binary:
        raise RuntimeError("MEDIA_EMULATOR_MISSING:" + system)
    name = Path(binary).name
    source = str(item["source"])
    tokens = tuple(str(token) for token in spec["tokens"])
    if name == "retroarch":
        return [binary, source], tokens
    if name == "dolphin-emu":
        return [binary, "-b", "-e", source], tokens
    if name in ("pcsx2", "pcsx2-qt"):
        return [binary, source], tokens
    return [binary, source], tokens


def ytdlp_resolve(url: str) -> str:
    binary = which_first(("yt-dlp",))
    if not binary:
        return url
    try:
        raw = subprocess.check_output(
            [binary, "-g", "--no-playlist", "--format", "b/best", url],
            timeout=25,
            env=_spawn_env(),
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return url
    line = raw.decode("utf-8", errors="replace").splitlines()
    if not line:
        return url
    try:
        return stream_allowed(line[0].strip())
    except ValueError:
        return url


def set_mode(mode: str) -> dict[str, Any]:
    kind = str(mode or "").strip().upper()
    if kind not in MODES:
        raise ValueError("MEDIA_MODE_INVALID")
    save_prefs({"mode": kind})
    return library_back()


def set_volume(volume: int) -> dict[str, Any]:
    prefs = save_prefs({"volume": int(volume)})
    if _backend == "qt_audio":
        from backend import media_qt_audio
        media_qt_audio.volume(int(prefs["volume"]))
    if _backend == "cliamp" and _cliamp_alive():
        _cliamp_call({"cmd": "volume", "value": _volume_db(int(prefs["volume"]))})
    elif _running() and _rc_sock is not None:
        _rc_send("volume " + str(_volume_vlc(int(prefs["volume"]))))
    return status_payload()


def set_eq_preset(name: str) -> dict[str, Any]:
    preset = str(name or "").strip()
    if preset.lower() == "cycle":
        current = str(status_payload().get("eq_preset") or "Flat")
        names = [item.lower() for item in EQ_PRESETS]
        try:
            index = names.index(current.lower())
        except ValueError:
            index = 0
        preset = EQ_PRESETS[(index + 1) % len(EQ_PRESETS)]
    allowed = {item.lower(): item for item in EQ_PRESETS}
    chosen = allowed.get(preset.lower())
    if chosen is None:
        raise ValueError("MEDIA_EQ_PRESET")
    _ensure_cliamp()
    sent = _cliamp_call({"cmd": "eq", "name": chosen})
    if sent.get("ok") is False:
        raise RuntimeError("MEDIA_EQ_PRESET:" + str(sent.get("error") or "fail"))
    return status_payload()


def set_eq_band(band: int, db: float) -> dict[str, Any]:
    index = int(band)
    if index < 0 or index > 9:
        raise ValueError("MEDIA_EQ_BAND")
    gain = max(-12.0, min(12.0, float(db)))
    _ensure_cliamp()
    sent = _cliamp_call({"cmd": "eq", "band": index, "value": gain})
    if sent.get("ok") is False:
        raise RuntimeError("MEDIA_EQ_BAND:" + str(sent.get("error") or "fail"))
    return status_payload()


def item_by_id(item_id_value: str) -> dict[str, Any] | None:
    wanted = str(item_id_value or "").strip()
    if not wanted:
        return None
    for item in _extra_items:
        if item.get("id") == wanted:
            return item
    if wanted in _library_items:
        return _library_items[wanted]
    return None


def _resolve_item(item: dict[str, Any]) -> dict[str, Any]:
    media = str(item.get("media") or "")
    source = str(item.get("source") or "")
    if media in ("stream", "tool") or looks_like_url(source):
        item = dict(item)
        if media != "tool":
            item["source"] = stream_allowed(source)
        return item
    item = dict(item)
    if str(item.get("kind") or "") == "FETCH":
        item["source"] = str(confined(Path(source), roots=[fetch_download_dir()]))
        return item
    item["source"] = str(confined(Path(source)))
    return item


def play_item(item_id_value: str, drawable_xid: int = 0) -> dict[str, Any]:
    global _item, _kind, _backend
    item = item_by_id(item_id_value)
    if item is None:
        raise ValueError("MEDIA_ITEM_UNKNOWN")
    item = _resolve_item(item)
    kind = str(item["kind"])
    if kind == "FETCH":
        source = str(item["source"])
        video = Path(source).suffix.lower() in VIDEO_EXT or str(item.get("play") or "") == "video"
        if video:
            item = dict(item)
            return _play_qml(item)
        if os.name == "nt":
            return _play_qt_audio(item)
        if which_first(("cliamp",)):
            _item = item
            _play_cliamp(source)
            save_prefs({"mode": "FETCH", "last_id": item["id"]})
            return status_payload()
        raise RuntimeError("MEDIA_CLIAMP_MISSING")
    if kind == "GAME":
        _halt_audio()
        if str(item.get("media") or "") == "homebrew":
            item = materialize_homebrew(item)
        if libretro_host.core_path(str(item.get("system") or "")):
            return _play_libretro(item)
        argv, tokens = _emulator_argv(item)
        _spawn(argv, tokens)
        _kind = "game"
        _backend = "emu"
        _item = item
        save_prefs({"mode": "GAME", "last_id": item["id"]})
        payload = status_payload()
        payload["screen"] = "EMBED"
        return payload
    source = str(item["source"])
    host = (urlparse(source).hostname or "").lower()
    if kind == "TV" and (
        "youtube." in host
        or host.endswith("youtu.be")
        or host.endswith("twitch.tv")
    ):
        source = ytdlp_resolve(source)
        item["source"] = source
    if _is_video_item(item):
        return _play_qml(item)
    if os.name == "nt":
        return _play_qt_audio(item)
    use_cliamp = kind in ("MUSIC", "RADIO") and bool(which_first(("cliamp",)))
    if use_cliamp:
        _stop_proc()
        _item = item
        _play_cliamp(source)
        save_prefs({"mode": kind, "last_id": item["id"]})
        return status_payload()
    video = Path(source).suffix.lower() in VIDEO_EXT
    _clear_socket()
    argv = _player_argv(source, video=video, drawable_xid=drawable_xid)
    tokens = ("vlc", "VLC", "ffplay") if video else ()
    _spawn(argv, tokens)
    time.sleep(0.15)
    prefs = save_prefs({"mode": kind, "last_id": item["id"]})
    if _rc_sock is not None:
        _rc_send("volume " + str(_volume_vlc(int(prefs["volume"]))))
    _kind = "video" if video else "audio"
    _item = item
    payload = status_payload()
    if video:
        payload["screen"] = "EMBED"
        payload["drawable"] = bool(drawable_xid > 0)
    return payload


def tune_mhz(mhz: float) -> dict[str, Any]:
    preset = nearest_radio_preset(mhz)
    if preset is None:
        raise ValueError("MEDIA_TUNE_NO_STATION")
    url = stream_allowed(str(preset["url"]))
    return play_item(item_id("RADIO", url))


def pause() -> dict[str, Any]:
    global _paused, _qml_playing, _qml_buffering
    if _backend == "qt_audio":
        from backend import media_qt_audio
        _paused = not _paused
        media_qt_audio.pause(_paused)
        return status_payload()
    if _backend == "cliamp" and _cliamp_alive():
        _cliamp_call({"cmd": "toggle"})
        status = _cliamp_call({"cmd": "status"})
        _paused = str(status.get("state") or "") == "paused"
        return status_payload()
    if _backend == "qml":
        _paused = not _paused
        if _paused:
            _qml_playing = False
            _qml_buffering = False
        else:
            # The QML player will report Playing/Buffering as soon as its
            # decoder has caught up with the unpause request.
            _qml_playing = False
            _qml_buffering = True
        return status_payload()
    if _backend == "libretro":
        _paused = not _paused
        return status_payload()
    if not _running():
        return status_payload()
    if _rc_sock is not None:
        _rc_send("pause")
        _paused = not _paused
    elif _proc is not None:
        if _paused:
            os.kill(_proc.pid, 18)
            _paused = False
        else:
            os.kill(_proc.pid, 19)
            _paused = True
    return status_payload()


def report_clock(position: float, duration: float) -> None:
    global _qml_position, _qml_duration
    try:
        _qml_position = max(0.0, float(position))
    except (TypeError, ValueError):
        _qml_position = 0.0
    try:
        _qml_duration = max(0.0, float(duration))
    except (TypeError, ValueError):
        _qml_duration = 0.0
    # QML owns the decoder clock.  Publish that inexpensive state directly
    # instead of starting the cliamp spectrum worker for video playback.
    if _backend == "qml":
        publish_live()


def report_player_state(playing: bool, buffering: bool) -> bool:
    """Receive the actual Qt Multimedia state for an in-process TV stream.

    QML owns the decoder, so the subprocess-style ``_running()`` flag cannot
    tell the status surface whether a channel is really playing or waiting for
    network data.  Keep this state tiny and publish it immediately so the
    catalog and utility strip stop showing a false playing state.
    """
    global _qml_playing, _qml_buffering
    if _backend != "qml":
        return False
    next_playing = bool(playing) and not _paused
    next_buffering = bool(buffering) and not _paused and not next_playing
    changed = (_qml_playing, _qml_buffering) != (next_playing, next_buffering)
    _qml_playing = next_playing
    _qml_buffering = next_buffering
    if changed:
        publish_live()
    return changed


def seek(seconds: float) -> dict[str, Any]:
    global _qml_position
    try:
        stamp = max(0.0, float(seconds))
    except (TypeError, ValueError):
        stamp = 0.0
    if _qml_duration > 0:
        stamp = min(stamp, _qml_duration)
    if _backend == "qt_audio":
        from backend import media_qt_audio
        media_qt_audio.seek(stamp)
        return status_payload(live=True)
    if _backend == "qml":
        _qml_position = stamp
        publish_live()
        return status_payload(live=True)
    if _backend == "cliamp" and _cliamp_alive():
        sent = _cliamp_call({"cmd": "seek", "position": stamp}, timeout=0.4)
        if sent.get("ok") is False:
            _cliamp_call({"cmd": "seek", "value": stamp}, timeout=0.4)
        return status_payload(live=True)
    if _running() and _rc_sock is not None:
        _rc_send("seek " + str(int(stamp)))
        return status_payload(live=True)
    return status_payload(live=True)


def stop() -> dict[str, Any]:
    global _item, _kind, _backend, _paused, _want_source
    global _qml_position, _qml_duration, _qml_playing, _qml_buffering
    _want_source = ""
    _qml_position = 0.0
    _qml_duration = 0.0
    _qml_playing = False
    _qml_buffering = False
    _stop_spectrum_stream()
    if _backend == "cliamp" and _cliamp_alive():
        _cliamp_call({"cmd": "stop"})
    if _backend == "libretro" or libretro_host.loaded():
        libretro_host.unload()
    if _backend == "torlink":
        _stop_fetch()
    _stop_proc()
    _item = None
    _kind = "audio"
    _backend = ""
    _paused = False
    return status_payload()


def search(query: str) -> dict[str, Any]:
    global _extra_items, _search_mode, _search_query, _search_active
    prefs = load_prefs()
    cleaned = str(query or "").strip()
    if not cleaned:
        return library_back()
    rows = search_items(prefs["mode"], cleaned)
    _extra_items = rows
    _search_active, _search_mode, _search_query = True, prefs["mode"], cleaned
    payload = status_payload()
    payload["items"] = rows
    payload["query"] = str(query or "")[:80]
    return payload


def next_item_id(delta: int) -> str:
    prefs = load_prefs()
    rows = _catalog_rows(prefs["mode"])
    if not rows:
        return ""
    current = str((_item or {}).get("id") or prefs.get("last_id") or "")
    index = 0
    for i, item in enumerate(rows):
        if item["id"] == current:
            index = i
            break
    return str(rows[(index + int(delta)) % len(rows)]["id"])


def skip(delta: int) -> dict[str, Any]:
    nxt = next_item_id(delta)
    if not nxt:
        return status_payload()
    return play_item(nxt)


def fetch_status() -> dict[str, Any]:
    tools = probe_tools()
    path = tools["torlink"]["path"]
    terminal = fetch_terminal()
    files = "http://127.0.0.1:9160/"
    if not path:
        return {
            "present": False,
            "label": "TORLINK · MISSING",
            "detail": "torlnk is not on PATH.",
            "bin": "",
            "terminal": terminal,
            "files": files,
            "running": _fetch_alive(),
        }
    if not terminal:
        return {
            "present": False,
            "label": "TORLINK · NO TERMINAL",
            "detail": "konsole is missing. The search TUI needs it.",
            "bin": path,
            "terminal": "",
            "files": files,
            "running": _fetch_alive(),
        }
    return {
        "present": True,
        "label": "TORLINK · READY" if not _fetch_alive() else "TORLINK · OPEN",
        "detail": "Search torrents in the workspace. Type a query, Enter to search, d to download. Finished files land on the left.",
        "bin": path,
        "terminal": terminal,
        "files": files,
        "running": _fetch_alive(),
    }


def fetch_argv() -> list[str]:
    tools = probe_tools()
    path = tools["torlink"]["path"]
    if not path:
        raise RuntimeError("MEDIA_TORLINK_MISSING")
    terminal = fetch_terminal()
    if not terminal:
        raise RuntimeError("MEDIA_KONSOLE_MISSING")
    return [
        terminal,
        "--hide-menubar",
        "--hide-tabbar",
        "-p",
        "LocalTabTitleFormat=" + FETCH_TUI_TITLE,
        "-p",
        "RemoteTabTitleFormat=" + FETCH_TUI_TITLE,
        "-e",
        path,
    ]


def bind_fetch_proc(proc: subprocess.Popen[bytes] | None) -> None:
    global _fetch_proc
    _fetch_proc = proc


def start_cliamp() -> dict[str, Any]:
    global _item, _kind, _backend, _cliamp_proc
    binary = which_first(("cliamp",))
    if not binary:
        raise RuntimeError("MEDIA_CLIAMP_MISSING")
    owned = _cliamp_proc
    _cliamp_proc = None
    if owned is not None and owned.poll() is None:
        owned.terminate()
        try:
            owned.wait(timeout=2)
        except subprocess.TimeoutExpired:
            owned.kill()
    argv = [
        binary,
        "--provider",
        "radio",
        "--buffer-ms",
        str(_CLIAMP_BUFFER_MS),
    ]
    _spawn(argv, ("cliamp",))
    _kind = "fetch"
    _backend = "cliamp"
    _item = {
        "id": "music:cliamp",
        "kind": "MUSIC",
        "title": "cliamp",
        "source": binary,
        "media": "tool",
        "system": "",
    }
    save_prefs({"mode": "RADIO", "last_id": "music:cliamp"})
    payload = status_payload()
    payload["screen"] = "EMBED"
    return payload


def _ensure_torlink_files() -> None:
    global _files_proc
    if _files_proc is not None and _files_proc.poll() is None:
        return
    binary = which_first(("torlnk", "torlink"))
    if not binary:
        return
    root = fetch_download_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _files_proc = subprocess.Popen(
        [
            binary,
            "files",
            "--host",
            "127.0.0.1",
            "--port",
            "9160",
            "--dir",
            str(root),
        ],
        cwd=str(Path.home()),
        env=_spawn_env(),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_fetch() -> None:
    global _fetch_proc
    proc = _fetch_proc
    _fetch_proc = None
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def start_fetch() -> dict[str, Any]:
    global _item, _kind, _backend, _paused
    argv = fetch_argv()
    if libretro_host.loaded():
        libretro_host.unload()
    _stop_proc()
    fetch_download_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    _ensure_torlink_files()
    _paused = False
    _kind = "fetch"
    _backend = "torlink"
    _item = {
        "id": "fetch:torlink",
        "kind": "FETCH",
        "title": "torlink",
        "source": argv[-1],
        "media": "tool",
        "system": "",
    }
    save_prefs({"mode": "FETCH", "last_id": "fetch:torlink"})
    payload = status_payload()
    payload["screen"] = "EMBED"
    return payload


def status_payload(live: bool = False, *, pump: bool = False) -> dict[str, Any]:
    prefs = load_prefs()
    mode = prefs["mode"]
    rows: list[dict[str, Any]] = [] if live else _catalog_rows(mode)
    now = dict(_item) if _item else {}
    playing = False
    paused = False
    position = 0.0
    duration = 0.0
    eq_preset = ""
    shuffle = False
    repeat = "off"
    spectrum: list[float] = []
    eq_bands: list[float] = []
    live_state: dict[str, Any] = {}
    audio_state: dict[str, Any] = {}
    if _backend == "cliamp":
        if live:
            start_live_pump()
        live_state = (
            _cliamp_live(want_bands=False)
            if pump
            else _cached_cliamp()
        )
        state = str(live_state.get("state") or "")
        playing = state == "playing"
        paused = state == "paused"
        try:
            position = float(live_state.get("position") or 0)
        except (TypeError, ValueError):
            position = 0.0
        try:
            duration = float(live_state.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        eq_preset = str(live_state.get("eq_preset") or "")
        shuffle = bool(live_state.get("shuffle"))
        repeat = str(live_state.get("repeat") or "off")
        eq_bands = normalize_eq(live_state.get("eq_bands"))
        track = live_state.get("track") if isinstance(live_state.get("track"), dict) else {}
        if track:
            now = {
                "id": now.get("id") or "",
                "kind": now.get("kind") or mode,
                "title": str(track.get("title") or now.get("title") or mode),
                "artist": str(track.get("artist") or ""),
                "album": str(track.get("album") or ""),
                "source": str(track.get("path") or now.get("source") or ""),
                "media": "stream" if track.get("stream") else now.get("media") or "file",
                "system": "",
                "player": "cliamp",
                "stream": bool(track.get("stream")),
            }
        if playing:
            with _live_lock:
                held = list(_spectrum)
            spectrum = held
    else:
        if _backend == "qt_audio":
            from backend import media_qt_audio
            audio_state = media_qt_audio.status()
            playing, paused = audio_state["playing"] and not _paused, _paused
            position, duration = audio_state["position"], audio_state["duration"]
            spectrum = audio_state["spectrum"] if playing else []
        elif _backend == "qml":
            # A QML MediaPlayer is in-process; _running() only means that a
            # channel is selected, not that its network decoder is playing.
            playing = _qml_playing and not _paused
            paused = _paused
            position = _qml_position
            duration = _qml_duration
        else:
            playing = _running() and not _paused
            paused = _paused and _running()
    report_backend = _backend or ("cliamp" if live_state else "")
    if report_backend == "cliamp":
        player = "CLIAMP"
    elif report_backend == "qml":
        player = "QML"
    elif report_backend == "qt_audio":
        player = "QT AUDIO"
    elif report_backend == "libretro":
        player = "LIBRETRO"
    elif report_backend == "torlink":
        player = "TORLINK"
    else:
        player = "NONE"
    legend = mode
    if now:
        legend = str(now.get("title") or mode)
    fetch: dict[str, Any] = {}
    if mode == "FETCH" or not live:
        fetch = dict(_library_fetch_info, running=_fetch_alive())
    screen = ""
    if _backend in ("qml", "libretro"):
        screen = "EMBED"
    elif _kind in ("video", "game", "fetch") and _backend:
        screen = "EMBED"
    buffering = (
        (_backend == "qml" and _qml_buffering and not paused)
        or (bool(_want_source) and not playing and not paused)
    )
    if _backend == "qt_audio":
        buffering = audio_state["buffering"] and not paused
    buffering_item = str((_item or {}).get("id") or "") if buffering else ""
    buffering_source = (
        str((_item or {}).get("source") or "")
        if _backend in ("qml", "qt_audio") and buffering
        else str(_want_source or "") if buffering else ""
    )
    payload = {
        "schema": SCHEMA,
        "mode": mode,
        "modes": list(MODES),
        "volume": int(prefs["volume"]),
        "playing": playing,
        "paused": paused,
        "buffering": buffering,
        "buffering_id": buffering_item,
        "buffering_source": buffering_source,
        "error": audio_state.get("error", ""),
        "reconnecting": bool(audio_state.get("reconnecting")) and not paused,
        "retry_attempt": int(audio_state.get("retry_attempt", 0)),
        "retry_limit": int(audio_state.get("retry_limit", 0)),
        "running": playing or paused or bool(_backend) or buffering,
        "player": player,
        "backend": report_backend or player.lower(),
        "playback_generation": _qml_generation if _backend == "qml" else 0,
        "pid": 0 if live else player_pid(),
        "screen": screen,
        "kind": _kind,
        "legend": legend[:80],
        "now": now,
        "position": position,
        "duration": duration,
        "clock": format_clock(position),
        "length": "LIVE" if now.get("stream") and duration <= 0 else format_clock(duration),
        "eq_preset": eq_preset or "Flat",
        "eq_bands": eq_bands,
        "spectrum": spectrum,
        "shuffle": shuffle,
        "repeat": repeat,
        "last_id": str(prefs.get("last_id") or ""),
        "freq_mhz": freq_for_now(now),
        "rf": dict(_rf_cache[1]) if _rf_cache else {"kind": "NONE", "label": "NO RF"},
        "tuner": list(_TUNER_MARKS),
    }
    payload.update(library_state())
    if not live:
        payload["library_count"] = len(rows)
    if live:
        for field in ("library_categories", "library_languages", "library_seasons"):
            payload.pop(field, None)
        payload["live"] = True
        return payload
    from backend import media_contract as _media_contract
    tools = dict(_media_contract._probe_cache[1]) if _media_contract._probe_cache else {
        key: {"present": False, "path": ""} for key in ("cliamp", "vlc", "ffplay", "torlink", "yt-dlp", "retroarch")
    }
    payload["eq_presets"] = list(EQ_PRESETS)
    payload["items"] = rows
    payload["tools"] = {
        "cliamp": tools["cliamp"],
        "vlc": tools["vlc"],
        "ffplay": tools["ffplay"],
        "torlink": tools["torlink"],
        "yt-dlp": tools.get("yt-dlp") or {"present": False, "path": ""},
        "retroarch": tools["retroarch"],
    }
    payload["cores"] = tools.get("cores", {})
    payload["fetch"] = fetch
    payload["library_roots"] = []
    return payload


def tool_line(payload: dict[str, Any] | None = None) -> str:
    data = payload if payload is not None else status_payload()
    tools = data.get("tools") or {}
    parts = []
    for key in ("vlc", "cliamp", "torlink", "yt-dlp", "retroarch"):
        row = tools.get(key) or {}
        mark = "ON" if row.get("present") else "OFF"
        parts.append(key.upper() + " " + mark)
    return " · ".join(parts)
