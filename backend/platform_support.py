"""Platform paths and file locks used by the desktop's existing services.

Linux keeps its published paths. Windows stores application data below
LOCALAPPDATA and resolves the exported desktop repository as its workspace.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import weakref
from urllib.parse import urlparse
from urllib.request import url2pathname

IS_WINDOWS = os.name == "nt"
PROJECT = Path(__file__).resolve().parents[1]


def local_file_path(value: str) -> Path:
    """Decode local file URLs, including percent-escaped Windows drive paths."""
    raw = str(value)
    if raw.lower().startswith('file:'):
        url = urlparse(raw)
        if url.netloc not in ('', 'localhost'):
            raise ValueError('REMOTE_FILE_URL_NOT_ALLOWED')
        return Path(url2pathname(url.path))
    return Path(raw)


def workspace_root() -> Path:
    from backend.application_paths import WORKSPACE_ROOT
    return WORKSPACE_ROOT.expanduser().resolve()


def desktop_relative_path(name: str) -> str:
    return (PROJECT / name).relative_to(workspace_root()).as_posix()


def runtime_root() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("GG_RUNTIME_DIR") or
                    platform_path("/home/GG/.local/state/goldgoblins/gg-ai-desktop/runtime"))
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def private_runtime_root() -> Path:
    """Return the actual user's canonical runtime, creating it on Windows."""
    from backend.platform_files import owned_by_current_user, is_link, mode_matches, set_private_mode
    root = runtime_root()
    if not root.is_absolute() or is_link(root):
        raise RuntimeError("RUNTIME_DIRECTORY_INVALID")
    if IS_WINDOWS:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve(strict=True)
    if not root.is_dir() or not owned_by_current_user(root):
        raise RuntimeError("RUNTIME_DIRECTORY_OWNER_INVALID")
    if IS_WINDOWS and not mode_matches(root, 0o700):
        set_private_mode(root, 0o700)
    return root


def host_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Keep explicit child environments usable without copying secret values."""
    env = dict(overrides or {})
    if IS_WINDOWS:
        for name in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                     "USERPROFILE", "LOCALAPPDATA", "APPDATA", "SYSTEMDRIVE",
                     "USERNAME", "COMPUTERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH",
                     "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "ALLUSERSPROFILE"):
            if name in os.environ:
                env.setdefault(name, os.environ[name])
        if not env.get("PATH") or env["PATH"].startswith("/usr/bin"):
            env["PATH"] = os.environ.get("PATH", "")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def executable_path(name: str) -> str:
    """Resolve a native host tool; container paths must not use this helper."""
    if name in ("python", "python3"):
        return sys.executable
    found = find_executable(name)
    if found:
        return found
    if IS_WINDOWS:
        candidates = []
        if name == "git":
            for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
                base = os.environ.get(variable)
                if base:
                    candidates.extend((Path(base) / "Git/cmd/git.exe",
                                       Path(base) / "Programs/Git/cmd/git.exe"))
        elif name in ("ssh", "sftp", "scp"):
            candidates.append(Path(os.environ.get("SystemRoot", "C:/Windows"))
                              / "System32/OpenSSH" / (name + ".exe"))
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return name + ".exe" if not Path(name).suffix else name
    return "/usr/bin/" + name


def find_executable(name: str) -> str:
    """Find installed Windows applications even when installers omit PATH."""
    found = shutil.which(name)
    if found:
        return found
    if not IS_WINDOWS:
        return ""
    patterns = {
        "blender": ("Blender Foundation/Blender */blender.exe",),
        "gimp": ("GIMP*/bin/gimp.exe", "GIMP*/bin/gimp-3.exe", "GIMP*/bin/gimp-2.10.exe"),
        "krita": ("Krita*/bin/krita.exe",),
        "inkscape": ("Inkscape/bin/inkscape.exe",),
        "darktable": ("darktable/bin/darktable.exe",),
        "vlc": ("VideoLAN/VLC/vlc.exe",),
        "cvlc": ("VideoLAN/VLC/vlc.exe",),
        "git": ("Git/cmd/git.exe",),
        "node": ("nodejs/node.exe",),
        "ffmpeg": ("ffmpeg/bin/ffmpeg.exe", "ffmpeg/ffmpeg.exe"),
        "ffprobe": ("ffmpeg/bin/ffprobe.exe", "ffmpeg/ffprobe.exe"),
        "mpv": ("mpv/mpv.exe",),
        "podman": ("RedHat/Podman/podman.exe",),
        "msvc": ("Microsoft Visual Studio/*/*/VC/Tools/MSVC/*/bin/Hostx64/x64/cl.exe",),
    }
    roots = [Path(value) for value in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
             str(Path(os.environ["LOCALAPPDATA"]) / "Programs") if os.environ.get("LOCALAPPDATA") else None) if value]
    for root in roots:
        for pattern in patterns.get(name, ()):
            for candidate in sorted(root.glob(pattern), reverse=True):
                if candidate.is_file():
                    return str(candidate)
    extra = {
        "cargo": (Path.home() / ".cargo/bin/cargo.exe",),
        "rustc": (Path.home() / ".cargo/bin/rustc.exe",),
        "rustup": (Path.home() / ".cargo/bin/rustup.exe",),
        "grok": (Path.home() / ".grok/bin/grok.exe",),
        "yt-dlp": (Path(sys.executable).parent / "yt-dlp.exe",),
    }
    for candidate in extra.get(name, ()):
        if candidate.is_file():
            return str(candidate)
    local = os.environ.get("LOCALAPPDATA")
    if local and name in ("ffmpeg", "ffprobe"):
        packages = Path(local) / "Microsoft/WinGet/Packages"
        for package in sorted(packages.glob("Gyan.FFmpeg*"), reverse=True):
            for candidate in sorted(package.glob("*/bin/" + name + ".exe"), reverse=True):
                if candidate.is_file():
                    return str(candidate)
    if name in ("ssh", "scp", "sftp"):
        candidate = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/OpenSSH" / (name + ".exe")
        if candidate.is_file():
            return str(candidate)
    return ""


def native_directory(project: Path | None = None) -> Path:
    root = project or PROJECT
    if IS_WINDOWS:
        architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
        return root / "backend/native" / ("windows-" + architecture)
    return root / "backend/native/linux-x86_64"


def native_library_name(name: str) -> str:
    return name + ".dll" if IS_WINDOWS else "lib" + name + ".so"


def configure_stdio() -> None:
    """Keep Swedish text and desktop symbols usable in Windows CLI helpers."""
    if IS_WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure:
                reconfigure(encoding="utf-8", errors="backslashreplace")


def terminate_process_tree(pid: int, *, force: bool = False) -> None:
    """Stop only the requested worker and its children on the current OS."""
    if pid <= 0 or pid == os.getpid():
        raise ValueError("INVALID_CHILD_PROCESS")
    if not IS_WINDOWS:
        os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
        return
    import psutil
    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for child in reversed(children):
        try:
            child.kill() if force else child.terminate()
        except psutil.NoSuchProcess:
            pass
    try:
        process.kill() if force else process.terminate()
    except psutil.NoSuchProcess:
        pass


def windows_codex_binary() -> str | None:
    """Find an existing native CLI; never run a shell wrapper as an executable."""
    if not IS_WINDOWS:
        return None
    found = os.environ.get("GG_CODEX_BINARY") or shutil.which("codex.exe")
    if found and Path(found).is_file() and Path(found).suffix.lower() == ".exe":
        return str(Path(found))
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    candidate = local / "Programs/OpenAI/Codex/bin/codex.exe"
    if candidate.is_file():
        return str(candidate)
    releases = Path.home() / ".codex/packages/app-server-daemon/releases"
    if releases.is_dir():
        for candidate in sorted(releases.glob("*/bin/codex.exe"), reverse=True):
            if candidate.is_file():
                return str(candidate)
    return None


def platform_path(value: str) -> str:
    """Translate published Fedora defaults without changing caller overrides."""
    if not IS_WINDOWS:
        return value
    from backend.application_paths import DATA_HOME, HOME, STATE_ROOT, USER_CODEX_HOME
    home = HOME
    mappings = (
        ("/home/GG/GoldGoblins", workspace_root()),
        ("/home/GG/.local/state/goldgoblins/gg-ai-desktop", STATE_ROOT),
        ("/home/GG/.local/state/goldgoblins", STATE_ROOT.parent),
        ("/home/GG/.local/share/goldgoblins", DATA_HOME / "goldgoblins"),
        ("/home/GG/.codex", USER_CODEX_HOME),
        ("/home/GG/Hämtningar", home / "Downloads"),
        ("/home/GG", home),
        ("/tmp", Path(tempfile.gettempdir())),
    )
    for prefix, target in mappings:
        if value == prefix or value.startswith(prefix + "/"):
            suffix = value[len(prefix):].lstrip("/")
            return str(target / suffix) if suffix else str(target)
    return value


if not IS_WINDOWS:
    import fcntl as file_locks
else:
    import msvcrt

    class _WindowsFileLocks:
        LOCK_SH = 1
        LOCK_EX = 2
        LOCK_NB = 4
        LOCK_UN = 8
        _held = {}

        @staticmethod
        def fd_opened(fd):
            _WindowsFileLocks._held.pop(fd, None)

        @staticmethod
        def flock(file_or_fd, operation: int) -> None:
            """Serialize the same lock file across Windows processes.

            Preserve the stream position; some callers append state after
            acquiring a lock. A nonblocking conflict has flock's exception type.
            """
            fd = file_or_fd if isinstance(file_or_fd, int) else file_or_fd.fileno()
            identity = (msvcrt.get_osfhandle(fd), os.fstat(fd).st_ino)
            held = _WindowsFileLocks._held.get(fd)
            if not operation & _WindowsFileLocks.LOCK_UN and held and held[0] == identity:
                owner = held[1]() if held[1] else None
                if held[1] is None or (owner is not None and not owner.closed):
                    return
            position = os.lseek(fd, 0, os.SEEK_CUR)
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if operation & _WindowsFileLocks.LOCK_UN:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    _WindowsFileLocks._held.pop(fd, None)
                    return
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        owner = None if isinstance(file_or_fd, int) else weakref.ref(file_or_fd)
                        _WindowsFileLocks._held[fd] = (identity, owner)
                        return
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if operation & _WindowsFileLocks.LOCK_NB:
                            raise BlockingIOError(errno.EAGAIN, "File is locked") from exc
                        time.sleep(0.05)
            finally:
                os.lseek(fd, position, os.SEEK_SET)

    file_locks = _WindowsFileLocks()
