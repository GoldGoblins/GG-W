from __future__ import annotations

from backend.application_paths import DATA_HOME

import ctypes
from ctypes import CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_int16, c_size_t, c_uint, c_void_p
from pathlib import Path
from typing import Any


CORE_DIR = Path(str(DATA_HOME / 'goldgoblins/tools/emu/usr/lib64/libretro'))
CORE_FILES = {
    "nes": "nestopia_libretro.so",
    "snes": "bsnes_mercury_performance_libretro.so",
    "gb": "gambatte_libretro.so",
    "gba": "mgba_libretro.so",
    "ps1": "pcsx_rearmed_libretro.so",
}

RETRO_ENVIRONMENT_GET_CAN_DUPE = 3
RETRO_ENVIRONMENT_SET_MESSAGE = 6
RETRO_ENVIRONMENT_SHUTDOWN = 7
RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL = 8
RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY = 9
RETRO_ENVIRONMENT_SET_PIXEL_FORMAT = 10
RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS = 11
RETRO_ENVIRONMENT_GET_VARIABLE = 15
RETRO_ENVIRONMENT_SET_VARIABLES = 16
RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE = 17
RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME = 18
RETRO_ENVIRONMENT_GET_LIBRETRO_PATH = 19
RETRO_ENVIRONMENT_GET_LOG_INTERFACE = 27
RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY = 30
RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY = 31
RETRO_ENVIRONMENT_SET_GEOMETRY = 37
RETRO_ENVIRONMENT_GET_LANGUAGE = 39
RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS = 42
RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE = 47
RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION = 52

RETRO_DEVICE_JOYPAD = 1
RETRO_PIXEL_XRGB8888 = 1
RETRO_PIXEL_RGB565 = 2

_Joy = CFUNCTYPE(None)
_Video = CFUNCTYPE(None, c_void_p, c_uint, c_uint, c_size_t)
_Audio = CFUNCTYPE(None, c_int16, c_int16)
_AudioBatch = CFUNCTYPE(c_size_t, POINTER(c_int16), c_size_t)
_Poll = CFUNCTYPE(None)
_Input = CFUNCTYPE(c_int16, c_uint, c_uint, c_uint, c_uint)
_Env = CFUNCTYPE(c_bool, c_uint, c_void_p)


class _SystemInfo(Structure):
    _fields_ = [
        ("library_name", c_char_p),
        ("library_version", c_char_p),
        ("valid_extensions", c_char_p),
        ("need_fullpath", c_bool),
        ("block_extract", c_bool),
    ]


class _GameGeometry(Structure):
    _fields_ = [
        ("base_width", c_uint),
        ("base_height", c_uint),
        ("max_width", c_uint),
        ("max_height", c_uint),
        ("aspect_ratio", ctypes.c_float),
    ]


class _SystemTiming(Structure):
    _fields_ = [
        ("fps", ctypes.c_double),
        ("sample_rate", ctypes.c_double),
    ]


class _SystemAvInfo(Structure):
    _fields_ = [("geometry", _GameGeometry), ("timing", _SystemTiming)]


class _GameInfo(Structure):
    _fields_ = [
        ("path", c_char_p),
        ("data", c_void_p),
        ("size", c_size_t),
        ("meta", c_char_p),
    ]


class _Variable(Structure):
    _fields_ = [("key", c_char_p), ("value", c_char_p)]


class Core:
    def __init__(self) -> None:
        self._dll = None
        self._rom = b""
        self._path = ""
        self._loaded = False
        self._pixel = RETRO_PIXEL_RGB565
        self.frame: bytes = b""
        self.width = 0
        self.height = 0
        self.pitch = 0
        self.fps = 60.0
        self.sample_rate = 44100.0
        self.audio = bytearray()
        self.buttons = [0] * 16
        self._sysdir = ctypes.create_string_buffer(b".")
        self._savedir = ctypes.create_string_buffer(b".")
        self._corepath = ctypes.create_string_buffer(b"")
        self._cb_env = _Env(self._env)
        self._cb_video = _Video(self._video)
        self._cb_audio = _Audio(self._sample)
        self._cb_batch = _AudioBatch(self._batch)
        self._cb_poll = _Poll(self._poll)
        self._cb_input = _Input(self._state)

    def loaded(self) -> bool:
        return self._loaded

    def load(self, core_path: Path, rom_path: Path, system_dir: Path, save_dir: Path) -> None:
        self.unload()
        dll = ctypes.CDLL(str(core_path))
        dll.retro_set_environment.argtypes = [_Env]
        dll.retro_set_video_refresh.argtypes = [_Video]
        dll.retro_set_audio_sample.argtypes = [_Audio]
        dll.retro_set_audio_sample_batch.argtypes = [_AudioBatch]
        dll.retro_set_input_poll.argtypes = [_Poll]
        dll.retro_set_input_state.argtypes = [_Input]
        dll.retro_init.argtypes = []
        dll.retro_deinit.argtypes = []
        dll.retro_load_game.argtypes = [POINTER(_GameInfo)]
        dll.retro_load_game.restype = c_bool
        dll.retro_unload_game.argtypes = []
        dll.retro_run.argtypes = []
        dll.retro_get_system_info.argtypes = [POINTER(_SystemInfo)]
        dll.retro_get_system_av_info.argtypes = [POINTER(_SystemAvInfo)]
        dll.retro_reset.argtypes = []
        self._sysdir = ctypes.create_string_buffer(str(system_dir).encode("utf-8"))
        self._savedir = ctypes.create_string_buffer(str(save_dir).encode("utf-8"))
        self._corepath = ctypes.create_string_buffer(str(core_path).encode("utf-8"))
        system_dir.mkdir(parents=True, exist_ok=True)
        save_dir.mkdir(parents=True, exist_ok=True)
        dll.retro_set_environment(self._cb_env)
        dll.retro_set_video_refresh(self._cb_video)
        dll.retro_set_audio_sample(self._cb_audio)
        dll.retro_set_audio_sample_batch(self._cb_batch)
        dll.retro_set_input_poll(self._cb_poll)
        dll.retro_set_input_state(self._cb_input)
        dll.retro_init()
        info = _SystemInfo()
        dll.retro_get_system_info(ctypes.byref(info))
        rom = Path(rom_path)
        raw = rom.read_bytes()
        self._rom = raw
        self._path = str(rom)
        game = _GameInfo()
        path_buf = ctypes.create_string_buffer(self._path.encode("utf-8"))
        self._path_buf = path_buf
        game.path = ctypes.cast(path_buf, c_char_p)
        if info.need_fullpath:
            game.data = None
            game.size = 0
        else:
            buf = ctypes.create_string_buffer(raw, len(raw))
            self._rom_buf = buf
            game.data = ctypes.cast(buf, c_void_p)
            game.size = len(raw)
        if not dll.retro_load_game(ctypes.byref(game)):
            dll.retro_deinit()
            raise RuntimeError("MEDIA_LIBRETRO_LOAD")
        av = _SystemAvInfo()
        dll.retro_get_system_av_info(ctypes.byref(av))
        if av.timing.fps > 1:
            self.fps = float(av.timing.fps)
        if av.timing.sample_rate > 1000:
            self.sample_rate = float(av.timing.sample_rate)
        self._dll = dll
        self._loaded = True

    def run(self) -> None:
        if self._dll is None or not self._loaded:
            return
        self.audio.clear()
        self._dll.retro_run()

    def reset(self) -> None:
        if self._dll is not None and self._loaded:
            self._dll.retro_reset()

    def unload(self) -> None:
        dll = self._dll
        self._dll = None
        loaded = self._loaded
        self._loaded = False
        self.frame = b""
        self.audio = bytearray()
        if dll is None:
            return
        try:
            if loaded:
                dll.retro_unload_game()
            dll.retro_deinit()
        except Exception:
            pass

    def set_button(self, button: int, down: bool) -> None:
        index = int(button)
        if 0 <= index < 16:
            self.buttons[index] = 1 if down else 0

    def _env(self, cmd: int, data: int | None) -> bool:
        if not data:
            return cmd in (
                RETRO_ENVIRONMENT_SET_MESSAGE,
                RETRO_ENVIRONMENT_SHUTDOWN,
                RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL,
                RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS,
                RETRO_ENVIRONMENT_SET_VARIABLES,
                RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME,
                RETRO_ENVIRONMENT_SET_GEOMETRY,
                RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS,
            )
        ptr = data
        if cmd == RETRO_ENVIRONMENT_GET_CAN_DUPE:
            ctypes.cast(ptr, POINTER(c_bool))[0] = True
            return True
        if cmd == RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
            self._pixel = int(ctypes.cast(ptr, POINTER(c_uint))[0])
            return True
        if cmd in (
            RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY,
            RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY,
        ):
            ctypes.cast(ptr, POINTER(c_char_p))[0] = ctypes.cast(self._sysdir, c_char_p)
            return True
        if cmd == RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
            ctypes.cast(ptr, POINTER(c_char_p))[0] = ctypes.cast(self._savedir, c_char_p)
            return True
        if cmd == RETRO_ENVIRONMENT_GET_LIBRETRO_PATH:
            ctypes.cast(ptr, POINTER(c_char_p))[0] = ctypes.cast(self._corepath, c_char_p)
            return True
        if cmd == RETRO_ENVIRONMENT_GET_VARIABLE:
            ctypes.cast(ptr, POINTER(_Variable)).contents.value = None
            return True
        if cmd == RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
            ctypes.cast(ptr, POINTER(c_bool))[0] = False
            return True
        if cmd == RETRO_ENVIRONMENT_GET_LANGUAGE:
            ctypes.cast(ptr, POINTER(c_uint))[0] = 0
            return True
        if cmd == RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
            ctypes.cast(ptr, POINTER(c_uint))[0] = 0
            return True
        if cmd == RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE:
            ctypes.cast(ptr, POINTER(c_uint))[0] = 3
            return True
        if cmd in (
            RETRO_ENVIRONMENT_SET_MESSAGE,
            RETRO_ENVIRONMENT_SHUTDOWN,
            RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL,
            RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS,
            RETRO_ENVIRONMENT_SET_VARIABLES,
            RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME,
            RETRO_ENVIRONMENT_SET_GEOMETRY,
            RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS,
        ):
            return True
        return False

    def _video(self, data: int | None, width: int, height: int, pitch: int) -> None:
        if not data or width < 8 or height < 8 or pitch < width:
            return
        self.width = int(width)
        self.height = int(height)
        self.pitch = int(pitch)
        self.frame = ctypes.string_at(data, int(pitch) * int(height))

    def _sample(self, left: int, right: int) -> None:
        self.audio += int(left).to_bytes(2, "little", signed=True) + int(right).to_bytes(
            2, "little", signed=True
        )

    def _batch(self, data: Any, frames: int) -> int:
        count = int(frames)
        if count <= 0 or not data:
            return 0
        self.audio += ctypes.string_at(data, count * 4)
        return count

    def _poll(self) -> None:
        return

    def _state(self, port: int, device: int, index: int, ident: int) -> int:
        if int(port) != 0 or int(device) != RETRO_DEVICE_JOYPAD:
            return 0
        button = int(ident)
        if 0 <= button < 16:
            return self.buttons[button]
        return 0


_core = Core()


def core_path(system: str) -> Path | None:
    name = CORE_FILES.get(str(system or ""))
    if not name:
        return None
    path = CORE_DIR / name
    if path.is_file():
        return path
    return None


def loaded() -> bool:
    return _core.loaded()


def load(system: str, rom: Path, state_dir: Path) -> dict[str, Any]:
    path = core_path(system)
    if path is None:
        raise RuntimeError("MEDIA_LIBRETRO_CORE:" + str(system))
    system_dir = state_dir / "libretro" / str(system)
    save_dir = state_dir / "saves" / str(system)
    _core.load(path, Path(rom), system_dir, save_dir)
    return {
        "fps": _core.fps,
        "sample_rate": _core.sample_rate,
        "core": path.name,
    }


def run() -> None:
    _core.run()


def unload() -> None:
    _core.unload()


def set_button(button: int, down: bool) -> None:
    _core.set_button(button, down)


def frame() -> tuple[bytes, int, int, int, int]:
    return (_core.frame, _core.width, _core.height, _core.pitch, _core._pixel)


def audio_bytes() -> bytes:
    return bytes(_core.audio)


def fps() -> float:
    return float(_core.fps or 60.0)


def sample_rate() -> float:
    return float(_core.sample_rate or 44100.0)
