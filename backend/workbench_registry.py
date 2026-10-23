"""Code-owned workbench contributions and their local enabled state.

The GG desktop already has several real surfaces, but they used to be known
only by individual QML files.  This registry gives those surfaces the same
stable identity that a VS Code contribution/extension has: a manifest row,
activation metadata and a small, explicit contribution list.

This is deliberately a built-in registry.  It does not import arbitrary
Python/QML from disk and it does not grant execution, network or file-write
authority.  Future third-party extensions will need an isolated host and a
separate approval contract; toggling a built-in contribution only changes
presentation availability.
"""

from __future__ import annotations

from backend.application_paths import STATE_ROOT

import copy
from contextlib import contextmanager
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from backend.platform_support import file_locks as fcntl


STATE = Path(str(STATE_ROOT))
REGISTRY_PATH = STATE / "workbench-registry-v1.json"
SCHEMA = "gg.ai-desktop.workbench-registry.v1"


def _contribution(
    extension_id: str,
    name: str,
    *,
    kind: str,
    group: str,
    description: str,
    activation: str,
    host_kind: str = "",
    surface_id: str = "",
    required: bool = False,
    commands: tuple[str, ...] = (),
    views: tuple[str, ...] = (),
    settings: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": extension_id,
        "name": name,
        "version": "1.0.0",
        "kind": kind,
        "group": group,
        "description": description,
        "activation": activation,
        "hostKind": host_kind,
        "surfaceId": surface_id,
        "builtIn": True,
        "required": required,
        "status": "BUILT-IN",
        "commands": list(commands),
        "views": list(views),
        "settings": list(settings),
    }


# Every row is a contribution that already exists in the current GG shell.
# They all default to enabled so the Standard profile looks and behaves as it
# does today.  The core shell cannot be disabled; optional surfaces can.
BUILTIN_EXTENSIONS: tuple[dict[str, Any], ...] = (
    _contribution(
        "gg.core.chat",
        "Universal Chat",
        kind="CORE",
        group="CORE",
        description="The shared operational stream for GROK TUI, GPTUI and FLOW TUI.",
        activation="onStartup",
        surface_id="chat",
        required=True,
        commands=("workbench.focusChat", "workbench.switchEngine"),
        views=("CHAT",),
        settings=("chat.engine", "chat.showOpenTabInInput"),
    ),
    _contribution(
        "gg.core.workspace",
        "Workspace",
        kind="CORE",
        group="CORE",
        description="The central multi-object workbench and its host surfaces.",
        activation="onStartup",
        surface_id="workspace",
        required=True,
        commands=("workbench.focusWorkspace", "workspace.newTab"),
        views=("WORKSPACE",),
        settings=("workspace.hostKind", "workspace.innerEditorChrome"),
    ),
    _contribution(
        "gg.core.telemetry",
        "Telemetry Rail",
        kind="CORE",
        group="CORE",
        description="Compact status, wallet, snippets and chat-session rail.",
        activation="onStartup",
        surface_id="telemetry",
        required=True,
        views=("TELEMETRY", "CHATS", "MEMORY"),
    ),
    _contribution(
        "gg.core.settings",
        "Settings Workbench",
        kind="CORE",
        group="CORE",
        description="Profiles, surfaces, editor, layout and extension settings.",
        activation="onStartup",
        surface_id="settings",
        required=True,
        commands=("workbench.openSettings",),
        views=("SETTINGS",),
    ),
    _contribution(
        "gg.surface.code",
        "Code Editor",
        kind="SURFACE",
        group="WORKSPACE",
        description="Local QML/text authoring, source buffers and Live Aid gates.",
        activation="onStartup",
        host_kind="CODE",
        surface_id="workspace",
        required=True,
        commands=("workspace.CODE", "editor.showSource"),
        views=("CODE",),
        settings=("editor.showInnerChrome", "editor.sourceMode"),
    ),
    _contribution(
        "gg.surface.terminal",
        "Terminal",
        kind="SURFACE",
        group="WORKSPACE",
        description="The existing bounded user terminal surface.",
        activation="onCommand",
        host_kind="TERMINAL",
        surface_id="workspace",
        commands=("workspace.TERMINAL",),
        views=("TERMINAL",),
    ),
    _contribution(
        "gg.surface.web",
        "Web",
        kind="SURFACE",
        group="WORKSPACE",
        description="The visible browser surface with the existing URL policy.",
        activation="onCommand",
        host_kind="WEB",
        surface_id="workspace",
        commands=("workspace.WEB",),
        views=("WEB",),
    ),
    _contribution(
        "gg.surface.external",
        "Blender",
        kind="SURFACE",
        group="WORKSPACE",
        description="Hosted Blender window in EXT for authored clay assets, with a localhost MCP sidecar.",
        activation="onCommand",
        host_kind="EXTERNAL",
        surface_id="workspace",
        commands=("workspace.EXTERNAL",),
        views=("EXTERNAL",),
    ),
    _contribution(
        "gg.surface.site",
        "Site",
        kind="SURFACE",
        group="WORKSPACE",
        description="Local site files, preview and the existing import flow.",
        activation="onCommand",
        host_kind="SITE",
        surface_id="workspace",
        commands=("workspace.SITE",),
        views=("SITE",),
        settings=("site.preview",),
    ),
    _contribution(
        "gg.surface.crypto",
        "Crypto Desk",
        kind="SURFACE",
        group="WORKSPACE",
        description="Wallet and local crypto desk surface.",
        activation="onCommand",
        host_kind="CRYPTO",
        surface_id="workspace",
        commands=("workspace.CRYPTO", "workbench.openWallet"),
        views=("CRYPTO", "WALLET"),
    ),
    _contribution(
        "gg.surface.marketplace",
        "Marketplace",
        kind="SURFACE",
        group="WORKSPACE",
        description="The existing marketplace research surface.",
        activation="onCommand",
        host_kind="MARKETPLACE",
        surface_id="workspace",
        commands=("workspace.MARKETPLACE",),
        views=("MARKETPLACE",),
    ),
    _contribution(
        "gg.surface.tmog",
        "TMOG",
        kind="SURFACE",
        group="WORKSPACE",
        description="The existing deterministic TMOG surface.",
        activation="onCommand",
        host_kind="TMOG",
        surface_id="workspace",
        commands=("workspace.TMOG",),
        views=("TMOG",),
    ),
    _contribution(
        "gg.surface.osint",
        "OSINT",
        kind="SURFACE",
        group="WORKSPACE",
        description="Read-only public-feed and OSIRIS surface.",
        activation="onCommand",
        host_kind="OSINT",
        surface_id="workspace",
        commands=("workspace.OSINT",),
        views=("OSINT",),
    ),
    _contribution(
        "gg.surface.research",
        "Research",
        kind="SURFACE",
        group="WORKSPACE",
        description="Shared evidence and method memory, WASM lab, reverse engineering, web-skill checks, SQL previews and eval traces.",
        activation="onCommand",
        host_kind="RESEARCH",
        surface_id="workspace",
        commands=("workspace.RESEARCH",),
        views=("RESEARCH", "BACKLOG", "EVIDENCE", "MEMORY", "WEB SKILLS", "SQL", "EVALS", "WASM LAB", "REVERSE"),
    ),
    _contribution(
        "gg.surface.media",
        "Media / Utilities",
        kind="SURFACE",
        group="WORKSPACE",
        description="The existing media player, radio, TV and game utilities.",
        activation="onStartup",
        host_kind="MEDIA",
        surface_id="utility",
        commands=("workspace.MEDIA",),
        views=("MEDIA", "MUSIC"),
    ),
    _contribution(
        "gg.surface.draw",
        "Draw",
        kind="SURFACE",
        group="WORKSPACE",
        description="The existing bounded draw and creative-tool surface.",
        activation="onCommand",
        host_kind="DRAW",
        surface_id="workspace",
        commands=("workspace.DRAW",),
        views=("DRAW",),
    ),
    _contribution(
        "gg.surface.game-engine",
        "Game Engine",
        kind="SURFACE",
        group="WORKSPACE",
        description="Deterministic local Quick3D playground and replay surface.",
        activation="onCommand",
        host_kind="GAME_ENGINE",
        surface_id="workspace",
        commands=("workspace.GAME_ENGINE",),
        views=("GAME ENGINE",),
    ),
    _contribution(
        "gg.surface.nodes",
        "Nodes",
        kind="SURFACE",
        group="WORKSPACE",
        description="Geometry-Nodes-style local information and agent graph.",
        activation="onCommand",
        host_kind="NODES",
        surface_id="workspace",
        commands=("workspace.NODES",),
        views=("NODES",),
    ),
    _contribution(
        "gg.surface.flow",
        "Agent Flow",
        kind="SURFACE",
        group="WORKSPACE",
        description="The local agent-flow visual surface.",
        activation="onCommand",
        host_kind="FLOW",
        surface_id="workspace",
        commands=("workspace.FLOW",),
        views=("FLOW",),
    ),

)

_BUILTIN_BY_ID = {row["id"]: row for row in BUILTIN_EXTENSIONS}
_HOST_TO_ID = {
    str(row["hostKind"]): str(row["id"])
    for row in BUILTIN_EXTENSIONS
    if row.get("hostKind")
}
# Older saved QIP choices resolve to the single Research contribution.
_HOST_TO_ID["QIP"] = _HOST_TO_ID["RESEARCH"]
_ID = re.compile(r"^[a-z][a-z0-9._-]{0,47}$")
_PROFILE_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,47}/[a-z][a-z0-9._-]{0,47}$")


def _default_enabled() -> dict[str, bool]:
    return {str(row["id"]): True for row in BUILTIN_EXTENSIONS}


def default_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "enabled": _default_enabled(),
        "profiles": {},
    }


@contextmanager
def _registry_lock(target: Path):
    """Serialize toggles from the shared GROK/Codex desktop workspace."""
    handle = None
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = (target.with_name(target.name + ".lock")).open(
            "a+", encoding="utf-8"
        )
    except OSError:
        yield
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass


def normalize_state(raw: object) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    enabled = _default_enabled()
    raw_enabled = data.get("enabled")
    if isinstance(raw_enabled, dict):
        for extension_id in enabled:
            value = raw_enabled.get(extension_id)
            if isinstance(value, bool) and not _BUILTIN_BY_ID[extension_id]["required"]:
                enabled[extension_id] = value
    profile_overrides: dict[str, dict[str, dict[str, bool]]] = {}
    raw_profiles = data.get("profiles")
    if isinstance(raw_profiles, dict):
        for raw_key, raw_profile in list(raw_profiles.items())[:64]:
            profile_key = str(raw_key or "").strip().lower()
            if not _PROFILE_KEY.fullmatch(profile_key):
                continue
            if not isinstance(raw_profile, dict):
                continue
            raw_profile_enabled = raw_profile.get("enabled")
            if not isinstance(raw_profile_enabled, dict):
                continue
            overrides: dict[str, bool] = {}
            for extension_id, value in raw_profile_enabled.items():
                key = str(extension_id or "")
                if (
                    key in _BUILTIN_BY_ID
                    and isinstance(value, bool)
                    and not _BUILTIN_BY_ID[key]["required"]
                ):
                    overrides[key] = value
            if overrides:
                profile_overrides[profile_key] = {"enabled": overrides}
    # Required contributions are always available. Unknown ids are dropped,
    # so a state file can never turn into an extension allowlist by itself.
    return {
        "schema": SCHEMA,
        "enabled": enabled,
        "profiles": profile_overrides,
    }


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or REGISTRY_PATH
    if not target.is_file():
        return default_state()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default_state()
    return normalize_state(raw)


def save_state(payload: object, path: Path | None = None) -> str:
    target = path or REGISTRY_PATH
    data = normalize_state(payload)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    blob = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    # Write a bounded temporary beside the target, then replace it atomically.
    # No arbitrary paths are accepted by the QML-facing API; tests may provide
    # a temporary target explicitly.
    fd, temporary = tempfile.mkstemp(
        prefix=".workbench-registry-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, blob)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return str(target)


def reset_state(path: Path | None = None) -> dict[str, Any]:
    target = path or REGISTRY_PATH
    data = default_state()
    with _registry_lock(target):
        save_state(data, target)
    return data


def profile_key(theme_id: str = "", profile_id: str = "") -> str:
    theme = str(theme_id or "").strip().lower()
    profile = str(profile_id or "").strip().lower()
    value = theme + "/" + profile
    return value if _PROFILE_KEY.fullmatch(value) else ""


def rows(
    state: object | None = None,
    theme_id: str = "",
    profile_id: str = "",
) -> list[dict[str, Any]]:
    data = normalize_state(state if state is not None else load_state())
    enabled = dict(data["enabled"])
    scope = profile_key(theme_id, profile_id)
    profile_data = data["profiles"].get(scope, {})
    overrides = (
        profile_data.get("enabled", {})
        if isinstance(profile_data, dict)
        else {}
    )
    enabled.update(overrides)
    result: list[dict[str, Any]] = []
    for manifest in BUILTIN_EXTENSIONS:
        row = copy.deepcopy(manifest)
        row["enabled"] = bool(enabled.get(str(manifest["id"]), True))
        result.append(row)
    return result


def extension_id_for_host_kind(host_kind: str) -> str:
    return _HOST_TO_ID.get(str(host_kind or "").strip().upper(), "")


def is_enabled(
    host_kind: str,
    state: object | None = None,
    theme_id: str = "",
    profile_id: str = "",
) -> bool:
    extension_id = extension_id_for_host_kind(host_kind)
    if not extension_id:
        return True
    data = normalize_state(state if state is not None else load_state())
    return bool(
        next(
            row["enabled"]
            for row in rows(data, theme_id, profile_id)
            if row["id"] == extension_id
        )
    )


def set_enabled(
    extension_id: str,
    enabled: bool,
    path: Path | None = None,
    *,
    theme_id: str = "",
    profile_id: str = "",
) -> dict[str, Any]:
    key = str(extension_id or "").strip()
    manifest = _BUILTIN_BY_ID.get(key)
    if manifest is None:
        raise ValueError("Unknown workbench contribution: " + key)
    target = path or REGISTRY_PATH
    with _registry_lock(target):
        data = load_state(target)
        # Required rows stay enabled regardless of an incoming UI value.
        value = True if manifest["required"] else bool(enabled)
        scope = profile_key(theme_id, profile_id)
        if scope:
            data.setdefault("profiles", {}).setdefault(
                scope, {"enabled": {}}
            ).setdefault("enabled", {})[key] = value
        else:
            data["enabled"][key] = value
        save_state(data, target)
    return normalize_state(data)


def reset_profile(
    theme_id: str,
    profile_id: str,
    path: Path | None = None,
) -> dict[str, Any]:
    target = path or REGISTRY_PATH
    scope = profile_key(theme_id, profile_id)
    data = load_state(target)
    if scope:
        with _registry_lock(target):
            data = load_state(target)
            data.get("profiles", {}).pop(scope, None)
            save_state(data, target)
    return normalize_state(data)


def copy_profile(
    theme_id: str,
    source_profile_id: str,
    target_profile_id: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """Copy contribution overrides when a visual profile is duplicated."""
    target = path or REGISTRY_PATH
    source = profile_key(theme_id, source_profile_id)
    destination = profile_key(theme_id, target_profile_id)
    data = load_state(target)
    if not destination:
        return data
    with _registry_lock(target):
        data = load_state(target)
        profiles = data.setdefault("profiles", {})
        if source and source in profiles:
            profiles[destination] = copy.deepcopy(profiles[source])
        else:
            profiles.pop(destination, None)
        save_state(data, target)
    return normalize_state(data)


def copy_theme(
    source_theme_id: str,
    target_theme_id: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """Copy all contribution overrides belonging to a duplicated theme."""
    target = path or REGISTRY_PATH
    source = str(source_theme_id or "").strip().lower()
    destination = str(target_theme_id or "").strip().lower()
    data = load_state(target)
    if (
        not _ID.fullmatch(source)
        or not _ID.fullmatch(destination)
        or source == destination
    ):
        return data
    with _registry_lock(target):
        data = load_state(target)
        profiles = data.setdefault("profiles", {})
        destination_prefix = destination + "/"
        for key in list(profiles):
            if str(key).startswith(destination_prefix):
                profiles.pop(key, None)
        source_prefix = source + "/"
        for key, value in list(profiles.items()):
            raw_key = str(key)
            if not raw_key.startswith(source_prefix):
                continue
            profile_id = raw_key[len(source_prefix):]
            new_key = profile_key(destination, profile_id)
            if new_key:
                profiles[new_key] = copy.deepcopy(value)
        save_state(data, target)
    return normalize_state(data)


__all__ = [
    "BUILTIN_EXTENSIONS",
    "REGISTRY_PATH",
    "SCHEMA",
    "copy_theme",
    "default_state",
    "copy_profile",
    "extension_id_for_host_kind",
    "is_enabled",
    "load_state",
    "normalize_state",
    "profile_key",
    "reset_profile",
    "reset_state",
    "rows",
    "save_state",
    "set_enabled",
]
