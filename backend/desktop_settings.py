from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import json
import os
import re
from pathlib import Path

from backend.grok_worker_contract import ENGINE_TARGETS, normalize_engine_target

STATE = Path(str(STATE_ROOT))
SETTINGS_PATH = STATE / "settings-v1.json"
SCHEMA = "gg.ai-desktop.settings.v1"
_COLOR = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

DEFAULTS = {
    "schema": SCHEMA,
    "engineTarget": "GROK_TUI",
    "chatWidthRatio": 0.31,
    "telemetryWidth": 168,
    "utilityHeight": 112,
    "accentColor": "#8a8a8a",
    "frameBorder": "#6a6a6a",
    "frameRadius": 4,
    "showOpenTabInInput": False,
    "showInnerEditorChrome": True,
    "showProductSourceTabs": False,
    "showDemoFixtures": False,
    "desktopShell": False,
    # VS Code-style multi-root metadata.  These paths are presentation/context
    # state only; registering a folder never grants execution or write access.
    "workspaceFolders": [],
    "workspaceTrusted": True,
}

_ROOT_KEYS = {
    "engineTarget": "engineTarget",
    "chatWidthRatio": "alphaChatWidthRatio",
    "telemetryWidth": "alphaTelemetryWidth",
    "utilityHeight": "alphaUtilityHeight",
    "accentColor": "cyan",
    "frameBorder": "frameBorder",
    "frameRadius": "frameRadius",
    "showOpenTabInInput": "showOpenTabInInput",
    "showInnerEditorChrome": "showInnerEditorChrome",
    "showProductSourceTabs": "showProductSourceTabs",
    "showDemoFixtures": "alphaShowDemoFixtures",
    "desktopShell": "desktopShell",
    "workspaceFolders": "workspaceFolders",
    "workspaceTrusted": "workspaceTrusted",
}


def _color(raw: object, fallback: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("#") and len(text) == 9 and text[1:3].lower() == "ff":
        text = "#" + text[3:]
    if not _COLOR.match(text):
        return fallback
    if len(text) == 9:
        text = "#" + text[3:]
    return text.lower()


def normalize_settings(raw: object) -> dict[str, object]:
    data = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    try:
        out["engineTarget"] = normalize_engine_target(
            data.get("engineTarget", DEFAULTS["engineTarget"])
        )
    except Exception:
        out["engineTarget"] = DEFAULTS["engineTarget"]
    if out["engineTarget"] not in ENGINE_TARGETS:
        out["engineTarget"] = DEFAULTS["engineTarget"]
    try:
        ratio = float(data.get("chatWidthRatio", DEFAULTS["chatWidthRatio"]))
    except (TypeError, ValueError):
        ratio = DEFAULTS["chatWidthRatio"]
    out["chatWidthRatio"] = min(0.5, max(0.18, ratio))
    try:
        tele = int(data.get("telemetryWidth", DEFAULTS["telemetryWidth"]))
    except (TypeError, ValueError):
        tele = DEFAULTS["telemetryWidth"]
    out["telemetryWidth"] = min(280, max(120, tele))
    try:
        util = int(data.get("utilityHeight", DEFAULTS["utilityHeight"]))
    except (TypeError, ValueError):
        util = DEFAULTS["utilityHeight"]
    out["utilityHeight"] = min(220, max(64, util))
    try:
        radius = int(data.get("frameRadius", DEFAULTS["frameRadius"]))
    except (TypeError, ValueError):
        radius = DEFAULTS["frameRadius"]
    out["frameRadius"] = min(8, max(0, radius))
    out["accentColor"] = _color(data.get("accentColor"), str(DEFAULTS["accentColor"]))
    out["frameBorder"] = _color(data.get("frameBorder"), str(DEFAULTS["frameBorder"]))
    for key in (
        "showOpenTabInInput",
        "showInnerEditorChrome",
        "showProductSourceTabs",
        "showDemoFixtures",
        "desktopShell",
    ):
        value = data.get(key, DEFAULTS[key])
        out[key] = bool(value)
    folders = data.get("workspaceFolders", DEFAULTS["workspaceFolders"])
    clean_folders: list[str] = []
    if isinstance(folders, (list, tuple)):
        for folder in folders[:8]:
            value = str(folder or "").strip()
            if not value.startswith("/") or len(value) > 256:
                continue
            if value != "/":
                value = value.rstrip("/")
            if value and value not in clean_folders:
                clean_folders.append(value)
    out["workspaceFolders"] = clean_folders
    trusted = data.get("workspaceTrusted", DEFAULTS["workspaceTrusted"])
    out["workspaceTrusted"] = bool(trusted)
    out["schema"] = SCHEMA
    return out


def load_settings(path: Path | None = None) -> dict[str, object]:
    target = path or SETTINGS_PATH
    if not target.is_file():
        return dict(DEFAULTS)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    return normalize_settings(raw)


def save_settings(
    payload: object,
    path: Path | None = None,
) -> str:
    target = path or SETTINGS_PATH
    data = normalize_settings(payload)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    blob = json.dumps(data, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW
    fd = secure_open(target, flags, 0o600)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)
    return str(target)


def apply_to_root(root: object, settings: dict[str, object] | None = None) -> None:
    data = settings or load_settings()
    setter = getattr(root, "setProperty", None)
    if not callable(setter):
        return
    for key, prop in _ROOT_KEYS.items():
        setter(prop, data[key])
