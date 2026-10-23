"""Shared visual layout, theme, profile and source-buffer state.

The visual layer deliberately sits beside ``desktop_settings``.  The latter
contains the small set of legacy, application-wide settings that already have
live bindings.  This module owns presentation state only: which theme/profile
is active, how a surface is presented, and the editable source buffer shown by
the visual editor.

Canonical QML/Python files are read-only through this API.  A source edit is
stored as a profile-local buffer until it is sent through the existing Live
Aid/code-gate path.  This keeps the new editor useful without creating a new
write authority or bypassing the current source-write contracts.
"""

from __future__ import annotations
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

from backend.application_paths import STATE_ROOT

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
STATE = Path(str(STATE_ROOT))
VISUAL_LAYOUT_PATH = STATE / "visual-layout-v1.json"
SCHEMA = "gg.ai-desktop.visual-layout.v1"
SOURCE_SCHEMA = "gg.ai-desktop.visual-source-buffer.v1"
MAX_SOURCE_BYTES = 512 * 1024
MAX_BUFFER_BYTES = 512 * 1024
_ID = re.compile(r"^[a-z][a-z0-9._-]{0,47}$")


# These are presentation surfaces, not new functional modules.  The path is
# intentionally repository-relative and is validated again before every read.
SURFACE_REGISTRY: tuple[dict[str, object], ...] = (
    {
        "id": "chat",
        "title": "Chat",
        "group": "CORE",
        "objectName": "chatSurface",
        "sourcePath": "qml/Main.qml",
        "sourceObject": "chatSurface",
        "geometryMode": "OFFSET_SCALE",
    },
    {
        "id": "workspace",
        "title": "Workspace",
        "group": "CORE",
        "objectName": "workspaceLoader",
        "sourcePath": "qml/components/WorkspaceSurface.qml",
        "sourceObject": "workspaceSurface",
        "geometryMode": "OFFSET_SCALE",
    },
    {
        "id": "utility",
        "title": "Media / Utilities",
        "group": "CORE",
        "objectName": "utilitySurfaceLoader",
        "sourcePath": "qml/components/UtilitySurface.qml",
        "sourceObject": "utilitySurfaceLoader",
        "geometryMode": "OFFSET_SCALE",
    },
    {
        "id": "telemetry",
        "title": "Telemetry",
        "group": "CORE",
        "objectName": "telemetry",
        "sourcePath": "qml/components/TelemetryRail.qml",
        "sourceObject": "telemetry",
        "geometryMode": "OFFSET_SCALE",
    },
    {
        "id": "wallet",
        "title": "Wallet",
        "group": "POPUPS",
        "objectName": "walletPopup",
        "sourcePath": "qml/components/WalletPopup.qml",
        "sourceObject": "walletPopup",
        "geometryMode": "RECT",
    },
    {
        "id": "settings",
        "title": "Settings",
        "group": "POPUPS",
        "objectName": "settingsPopup",
        "sourcePath": "qml/components/SettingsPopup.qml",
        "sourceObject": "settingsPopup",
        "geometryMode": "RECT",
    },
)


def _surface_ids() -> tuple[str, ...]:
    return tuple(str(row["id"]) for row in SURFACE_REGISTRY)


def _clean_id(raw: object, fallback: str) -> str:
    value = str(raw or "").strip().lower().replace(" ", "-")
    if _ID.fullmatch(value):
        return value
    return fallback


def _clean_name(raw: object, fallback: str) -> str:
    value = " ".join(str(raw or "").strip().split())
    return value[:80] if value else fallback


def _number(raw: object, fallback: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = fallback
    if value != value:  # NaN
        value = fallback
    return min(high, max(low, value))


def _bool(raw: object, fallback: bool) -> bool:
    return raw if isinstance(raw, bool) else fallback


def _surface_default() -> dict[str, object]:
    return {
        "visible": True,
        "offsetX": 0.0,
        "offsetY": 0.0,
        "scale": 1.0,
        "x": -1.0,
        "y": -1.0,
        "width": -1.0,
        "height": -1.0,
        "sourceBuffer": "",
    }


def _default_profile(name: str = "Standard") -> dict[str, object]:
    return {
        "name": name,
        "locked": True,
        "editorMode": "NORMAL",
        "sourceSurface": "",
        "surfaces": {
            surface_id: _surface_default() for surface_id in _surface_ids()
        },
    }


def _theme(
    theme_id: str,
    name: str,
    *,
    canvas: str,
    surface: str,
    border: str,
    accent: str,
    radius: int = 4,
) -> dict[str, object]:
    return {
        "name": name,
        "tokens": {
            "canvas": canvas,
            "surface": surface,
            "frameBorder": border,
            "accent": accent,
            "frameRadius": radius,
        },
        "profiles": {"standard": _default_profile()},
    }


def default_state() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "activeTheme": "obsidian-ledger",
        "activeProfile": "standard",
        "themes": {
            "obsidian-ledger": _theme(
                "obsidian-ledger",
                "Obsidian / Ledger",
                canvas="#121212",
                surface="#161616",
                border="#6a6a6a",
                accent="#8a8a8a",
            ),
        },
        "surfaceRegistry": copy.deepcopy(list(SURFACE_REGISTRY)),
    }


def _normalize_tokens(raw: object, fallback: dict[str, object]) -> dict[str, object]:
    data = raw if isinstance(raw, dict) else {}
    out = dict(fallback)
    for key in ("canvas", "surface", "frameBorder", "accent"):
        value = str(data.get(key, out[key]) or out[key]).strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            out[key] = value.lower()
    out["frameRadius"] = int(
        _number(data.get("frameRadius"), int(out["frameRadius"]), 0, 8)
    )
    return out


def _normalize_surface(raw: object) -> dict[str, object]:
    data = raw if isinstance(raw, dict) else {}
    default = _surface_default()
    return {
        "visible": _bool(data.get("visible"), True),
        "offsetX": _number(data.get("offsetX"), 0.0, -4096.0, 4096.0),
        "offsetY": _number(data.get("offsetY"), 0.0, -4096.0, 4096.0),
        "scale": _number(data.get("scale"), 1.0, 0.35, 3.0),
        "x": _number(data.get("x"), -1.0, -1.0, 4096.0),
        "y": _number(data.get("y"), -1.0, -1.0, 4096.0),
        "width": _number(data.get("width"), -1.0, -1.0, 4096.0),
        "height": _number(data.get("height"), -1.0, -1.0, 4096.0),
        "sourceBuffer": str(data.get("sourceBuffer", default["sourceBuffer"]) or "")[
            :MAX_BUFFER_BYTES
        ],
    }


def _normalize_profile(raw: object, fallback_name: str) -> dict[str, object]:
    data = raw if isinstance(raw, dict) else {}
    mode = str(data.get("editorMode", "NORMAL") or "NORMAL").upper()
    if mode not in {"NORMAL", "SOURCE"}:
        mode = "NORMAL"
    raw_surfaces = data.get("surfaces")
    surfaces = raw_surfaces if isinstance(raw_surfaces, dict) else {}
    return {
        "name": _clean_name(data.get("name"), fallback_name),
        "locked": _bool(data.get("locked"), True),
        "editorMode": mode,
        "sourceSurface": (
            str(data.get("sourceSurface") or "")
            if str(data.get("sourceSurface") or "") in _surface_ids()
            else ""
        ),
        "surfaces": {
            surface_id: _normalize_surface(surfaces.get(surface_id))
            for surface_id in _surface_ids()
        },
    }


def normalize_state(raw: object) -> dict[str, object]:
    base = default_state()
    data = raw if isinstance(raw, dict) else {}
    themes_raw = data.get("themes")
    themes_data = themes_raw if isinstance(themes_raw, dict) else {}
    themes: dict[str, dict[str, object]] = {}

    for raw_id, raw_theme in themes_data.items():
        theme_id = _clean_id(raw_id, "")
        if not theme_id or not isinstance(raw_theme, dict):
            continue
        fallback = base["themes"]["obsidian-ledger"]  # type: ignore[index]
        fallback_tokens = fallback["tokens"]  # type: ignore[index]
        tokens = _normalize_tokens(raw_theme.get("tokens"), fallback_tokens)
        profiles_raw = raw_theme.get("profiles")
        profiles_data = profiles_raw if isinstance(profiles_raw, dict) else {}
        profiles: dict[str, dict[str, object]] = {}
        for raw_profile_id, raw_profile in profiles_data.items():
            profile_id = _clean_id(raw_profile_id, "")
            if profile_id:
                profiles[profile_id] = _normalize_profile(
                    raw_profile,
                    _clean_name(raw_profile_id, "Profile"),
                )
        if not profiles:
            profiles = {"standard": _default_profile()}
        themes[theme_id] = {
            "name": _clean_name(raw_theme.get("name"), theme_id),
            "tokens": tokens,
            "profiles": profiles,
        }

    if not themes:
        themes = copy.deepcopy(base["themes"])  # type: ignore[assignment]

    active_theme = _clean_id(data.get("activeTheme"), "obsidian-ledger")
    if active_theme not in themes:
        active_theme = next(iter(themes))
    profiles = themes[active_theme]["profiles"]  # type: ignore[index]
    active_profile = _clean_id(data.get("activeProfile"), "standard")
    if active_profile not in profiles:
        active_profile = next(iter(profiles))

    # Registry metadata is static and code-owned.  Returning a copy prevents a
    # caller from accidentally turning persisted state into an allowlist.
    return {
        "schema": SCHEMA,
        "activeTheme": active_theme,
        "activeProfile": active_profile,
        "themes": themes,
        "surfaceRegistry": copy.deepcopy(list(SURFACE_REGISTRY)),
    }


def load_state(path: Path | None = None) -> dict[str, object]:
    target = path or VISUAL_LAYOUT_PATH
    if not target.is_file():
        return default_state()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    return normalize_state(raw)


def save_state(payload: object, path: Path | None = None) -> str:
    target = path or VISUAL_LAYOUT_PATH
    data = normalize_state(payload)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW
    fd = secure_open(target, flags, 0o600)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)
    return str(target)


def reset_state(path: Path | None = None) -> dict[str, object]:
    data = default_state()
    save_state(data, path)
    return data


def _theme_and_profile(
    state: dict[str, object],
    theme_id: str = "",
    profile_id: str = "",
) -> tuple[str, str, dict[str, object], dict[str, object]]:
    data = normalize_state(state)
    themes = data["themes"]  # type: ignore[assignment]
    selected_theme = _clean_id(theme_id, str(data["activeTheme"]))
    if selected_theme not in themes:
        selected_theme = str(data["activeTheme"])
    theme = themes[selected_theme]
    profiles = theme["profiles"]
    selected_profile = _clean_id(profile_id, str(data["activeProfile"]))
    if selected_profile not in profiles:
        selected_profile = next(iter(profiles))
    return selected_theme, selected_profile, theme, profiles[selected_profile]


def profile_rows(state: object, theme_id: str = "") -> list[dict[str, object]]:
    selected_theme, _, theme, _ = _theme_and_profile(
        normalize_state(state), theme_id=theme_id
    )
    profiles = theme["profiles"]  # type: ignore[index]
    return [
        {
            "id": profile_id,
            "name": str(profile.get("name", profile_id)),
            "theme": selected_theme,
            "locked": bool(profile.get("locked", True)),
        }
        for profile_id, profile in profiles.items()
    ]


def theme_rows(state: object) -> list[dict[str, object]]:
    data = normalize_state(state)
    return [
        {
            "id": theme_id,
            "name": str(theme.get("name", theme_id)),
            "profiles": len(theme.get("profiles", {})),
        }
        for theme_id, theme in data["themes"].items()  # type: ignore[union-attr]
    ]


def source_for_surface(
    surface_id: str,
    state: object | None = None,
    theme_id: str = "",
    profile_id: str = "",
) -> dict[str, object]:
    surface = next(
        (row for row in SURFACE_REGISTRY if row["id"] == surface_id),
        None,
    )
    if surface is None:
        raise ValueError("Unknown visual surface: " + str(surface_id))
    relative = Path(str(surface["sourcePath"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Visual source path policy violation")
    candidate = (PROJECT / relative).resolve(strict=True)
    project_root = PROJECT.resolve(strict=True)
    if not candidate.is_relative_to(project_root):
        raise ValueError("Visual source escaped project root")
    if not candidate.is_file():
        raise ValueError("Visual source is not a regular file")
    data = candidate.read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Visual source exceeds bounded read")
    source = data.decode("utf-8")

    buffer_text = ""
    if state is not None:
        _, _, _, profile = _theme_and_profile(
            normalize_state(state), theme_id=theme_id, profile_id=profile_id
        )
        profile_surface = profile["surfaces"].get(surface_id, {})  # type: ignore[index]
        if isinstance(profile_surface, dict):
            buffer_text = str(profile_surface.get("sourceBuffer") or "")
    effective = buffer_text or source
    return {
        "schema": SOURCE_SCHEMA,
        "status": "PASS",
        "surfaceId": surface_id,
        "title": surface["title"],
        "relativePath": relative.as_posix(),
        "sourceObject": surface["sourceObject"],
        "language": "qml" if relative.suffix.lower() == ".qml" else "text",
        "source": effective,
        "diskSource": source,
        "sourceSha256": hashlib.sha256(data).hexdigest(),
        "sourceBytes": len(data),
        "isBuffer": bool(buffer_text),
        "writeAuthority": "NONE",
        "bufferAuthority": "PROFILE_LOCAL_BUFFER_ONLY",
    }


def save_source_buffer(
    state: object,
    surface_id: str,
    source: str,
    theme_id: str = "",
    profile_id: str = "",
) -> dict[str, object]:
    value = str(source or "")
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_BUFFER_BYTES:
        raise ValueError("Visual source buffer exceeds bounded write")
    data = normalize_state(state)
    selected_theme, selected_profile, theme, profile = _theme_and_profile(
        data, theme_id=theme_id, profile_id=profile_id
    )
    if surface_id not in _surface_ids():
        raise ValueError("Unknown visual surface: " + str(surface_id))
    profile["surfaces"][surface_id]["sourceBuffer"] = value  # type: ignore[index]
    data["activeTheme"] = selected_theme
    data["activeProfile"] = selected_profile
    source_path = save_state(data)
    return {
        "statePath": source_path,
        "surfaceId": surface_id,
        "themeId": selected_theme,
        "profileId": selected_profile,
        "bytes": len(encoded),
        "status": "BUFFER_SAVED",
        "writeAuthority": "NONE",
    }


def save_profile_as(
    state: object,
    theme_id: str,
    profile_id: str,
    display_name: str = "",
) -> dict[str, object]:
    data = normalize_state(state)
    theme_id, source_profile_id, theme, source_profile = _theme_and_profile(
        data, theme_id=theme_id
    )
    new_id = _clean_id(profile_id, "")
    if not new_id:
        raise ValueError("Profile id must contain lowercase letters, numbers, dots, dashes or underscores")
    profiles = theme["profiles"]  # type: ignore[index]
    cloned = copy.deepcopy(source_profile)
    cloned["name"] = _clean_name(display_name, profile_id)
    profiles[new_id] = cloned
    data["activeTheme"] = theme_id
    data["activeProfile"] = new_id
    save_state(data)
    return data


def set_active(
    state: object,
    theme_id: str = "",
    profile_id: str = "",
) -> dict[str, object]:
    data = normalize_state(state)
    selected_theme, selected_profile, _, _ = _theme_and_profile(
        data, theme_id=theme_id, profile_id=profile_id
    )
    data["activeTheme"] = selected_theme
    data["activeProfile"] = selected_profile
    save_state(data)
    return data
