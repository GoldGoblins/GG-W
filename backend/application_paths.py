"""Application resources and per-user data, independent of the install path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("GG_USER_HOME", Path.home())) if os.name == "nt" else Path.home()
_WINDOWS_ROOT = Path(os.environ.get("GG_DATA_HOME") or
                     (Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData/Local") / "GoldGoblins"))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", _WINDOWS_ROOT.parent if os.name == "nt" else HOME / ".local/state"))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", _WINDOWS_ROOT / "share" if os.name == "nt" else HOME / ".local/share"))
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", _WINDOWS_ROOT / "cache" if os.name == "nt" else HOME / ".cache"))
_DEFAULT_STATE = (_WINDOWS_ROOT / "gg-ai-desktop" if os.name == "nt" and "XDG_STATE_HOME" not in os.environ
                  else STATE_HOME / "goldgoblins/gg-ai-desktop")
STATE_ROOT = Path(os.environ.get("GG_DESKTOP_STATE_ROOT", _DEFAULT_STATE))
DATA_ROOT = Path(os.environ.get("GG_DESKTOP_DATA_ROOT", DATA_HOME / "goldgoblins/gg-ai-desktop"))
TOOLS_ROOT = DATA_HOME / "goldgoblins/tools"
SUPPORT_ROOT = PROJECT_ROOT / "support"
SKILLS_ROOT = PROJECT_ROOT / "skills"
GPT_KNOWLEDGE_ROOT = Path(os.environ.get("GG_GPT_KNOWLEDGE_ROOT", PROJECT_ROOT / "knowledge/web-gpts"))
USER_CODEX_HOME = Path(os.environ.get("GG_USER_CODEX_HOME", os.environ.get("CODEX_HOME", HOME / ".codex")))


def _default_workspace() -> Path:
    # Retain the shared development workspace when running in its projects/ tree.
    if PROJECT_ROOT.parent.name == "projects" and (PROJECT_ROOT.parent.parent / "AGENTS.md").is_file():
        return PROJECT_ROOT.parent.parent
    return PROJECT_ROOT


WORKSPACE_ROOT = Path(os.environ.get("GG_WORKSPACE", _default_workspace()))


def private_runtime_path(name: str, default: Path) -> Path:
    """Keep migration pointers in private state, outside distributed sources."""
    try:
        value = json.loads((STATE_ROOT / "runtime-paths.json").read_text()).get(name)
        if isinstance(value, str) and "\x00" not in value and Path(value).is_absolute():
            return Path(value)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return default


def resource_path(relative: str, *, workspace: Path | None = None) -> Path:
    """Resolve a canonical source name without weakening its caller's checks."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("RESOURCE_PATH_OUTSIDE_APPLICATION")
    prefix = Path("projects/gg-ai-desktop")
    if path.parts[:2] == prefix.parts:
        return PROJECT_ROOT / Path(*path.parts[2:])
    packaged = SUPPORT_ROOT / path
    if packaged.exists() or packaged.is_symlink():
        return packaged
    # Compatibility for an older development checkout before support is bundled.
    return (workspace or WORKSPACE_ROOT) / path


def bundled_skills() -> tuple[Path, ...]:
    if not SKILLS_ROOT.is_dir():
        return ()
    return tuple(sorted(p.parent for p in SKILLS_ROOT.glob("*/SKILL.md")))


def expose_directory(target: Path, source: Path) -> None:
    """Link one canonical directory, using an unprivileged Windows junction."""
    source = source.resolve(strict=True)
    if target.is_symlink() or (os.name == "nt" and target.is_junction()):
        if target.resolve() == source:
            return
        raise FileExistsError("DIRECTORY_LINK_TARGET_CHANGED")
    if target.exists():
        raise FileExistsError("DIRECTORY_LINK_TARGET_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        target.symlink_to(source, target_is_directory=True)
        return
    env = os.environ.copy()
    env["GG_LINK_TARGET"] = str(target.absolute())
    env["GG_LINK_SOURCE"] = str(source)
    # Paths travel in environment variables, never as PowerShell source text.
    subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:GG_LINK_TARGET -Target $env:GG_LINK_SOURCE | Out-Null",
    ], env=env, check=True, capture_output=True, timeout=20,
       creationflags=subprocess.CREATE_NO_WINDOW)
    if not target.is_junction() or target.resolve() != source:
        raise OSError("DIRECTORY_JUNCTION_NOT_VERIFIED")


def prepare_codex_skills(codex_home: Path) -> None:
    """Expose GG skills while retaining each user's own skills and settings."""
    root = codex_home / "skills"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for source in bundled_skills():
        target = root / source.name
        if target.is_symlink() or (os.name == "nt" and target.is_junction()):
            if target.resolve() == source.resolve():
                continue
            # An installed GG skill may point at an older app installation.
            if source.name.startswith("gg-") and not target.exists():
                target.unlink()
            else:
                continue
        elif target.exists():
            continue
        expose_directory(target, source)


def prepare_application_skills() -> None:
    """Restore the canonical aliases after a Windows checkout or ZIP extract."""
    for relative, destination in (
        ('.agents/skills', '../skills'),
        ('.grok/skills', '../skills'),
        ('tools/skills/gg-live-eyes', '../../skills/gg-live-eyes'),
    ):
        target = PROJECT_ROOT / relative
        source = (target.parent / destination).resolve(strict=True)
        if not source.is_relative_to(PROJECT_ROOT):
            raise ValueError('APPLICATION_SKILL_LINK_OUTSIDE_SOURCE')
        if os.name == 'nt' and target.is_file() and not target.is_symlink():
            # Git can check out a POSIX symlink as its literal target text.
            if target.read_text(encoding='utf-8').strip() != destination:
                raise FileExistsError('APPLICATION_SKILL_ALIAS_MODIFIED')
            target.unlink()
        expose_directory(target, source)
