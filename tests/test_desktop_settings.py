#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import desktop_settings

    saved_path = desktop_settings.SETTINGS_PATH
    scratch = Path(tempfile.mkdtemp(prefix="gg-desktop-settings-"))
    desktop_settings.SETTINGS_PATH = scratch / "settings-v1.json"
    try:
        loaded = desktop_settings.load_settings()
        if loaded["engineTarget"] != "GROK_TUI":
            raise AssertionError("missing defaults")
        if loaded.get("desktopShell") is not False:
            raise AssertionError("desktop shell must default off")
        path = desktop_settings.save_settings(
            {
                "engineTarget": "GROK_WORKER",
                "chatWidthRatio": 0.9,
                "telemetryWidth": 10,
                "utilityHeight": 999,
                "accentColor": "#FF112233",
                "frameBorder": "not-a-color",
                "frameRadius": -3,
                "showInnerEditorChrome": 0,
                "showProductSourceTabs": 1,
                "desktopShell": 1,
                "workspaceFolders": [
                    "/home/GG/GoldGoblins",
                    "/home/GG/GoldGoblins/",
                    "relative-folder",
                    "/",
                ],
                "workspaceTrusted": 0,
            }
        )
        if not Path(path).is_file():
            raise AssertionError("settings file missing")
        again = desktop_settings.load_settings()
        if again["engineTarget"] != "GROK_WORKER":
            raise AssertionError("engine did not persist")
        desktop_settings.save_settings({"engineTarget": "GROK_TUI"})
        tui = desktop_settings.load_settings()
        if tui["engineTarget"] != "GROK_TUI":
            raise AssertionError("GROK_TUI did not persist")
        if again["chatWidthRatio"] != 0.5:
            raise AssertionError("chat width was not clamped")
        if again["telemetryWidth"] != 120:
            raise AssertionError("telemetry width was not clamped")
        if again["utilityHeight"] != 220:
            raise AssertionError("utility height was not clamped")
        if again["accentColor"] != "#112233":
            raise AssertionError("accent color not normalized")
        if again["frameBorder"] != "#6a6a6a":
            raise AssertionError("bad border color was accepted")
        if again["frameRadius"] != 0:
            raise AssertionError("frame radius was not clamped")
        if again["showInnerEditorChrome"] is not False:
            raise AssertionError("bool inner chrome mismatch")
        if again["showProductSourceTabs"] is not True:
            raise AssertionError("bool product tabs mismatch")
        if again["desktopShell"] is not True:
            raise AssertionError("desktop shell did not persist")
        if again["workspaceFolders"] != ["/home/GG/GoldGoblins", "/"]:
            raise AssertionError("workspace roots were not normalized")
        if again["workspaceTrusted"] is not False:
            raise AssertionError("workspace trust did not persist")
        rejected = desktop_settings.normalize_settings(
            {"engineTarget": "OPEN_INTERNET"}
        )
        if rejected["engineTarget"] != "GROK_TUI":
            raise AssertionError("unknown engine was accepted")
        class Root:
            def __init__(self) -> None:
                self.props = {}

            def setProperty(self, name, value) -> None:
                self.props[name] = value

        root = Root()
        desktop_settings.apply_to_root(root, again)
        if root.props.get("engineTarget") != "GROK_WORKER":
            raise AssertionError("apply_to_root missed engine")
        if root.props.get("cyan") != "#112233":
            raise AssertionError("apply_to_root missed accent")
        if root.props.get("desktopShell") is not True:
            raise AssertionError("apply_to_root missed desktop shell")
        if root.props.get("workspaceFolders") != ["/home/GG/GoldGoblins", "/"]:
            raise AssertionError("apply_to_root missed workspace roots")
        if root.props.get("workspaceTrusted") is not False:
            raise AssertionError("apply_to_root missed workspace trust")
        shell_src = (
            Path(__file__).resolve().parents[1] / "backend" / "desktop_shell.py"
        ).read_text(encoding="utf-8")
        if "WindowStaysOnBottomHint" not in shell_src:
            raise AssertionError("desktop shell stacking missing")
        if "/bin/sh" in shell_src or "bash -c" in shell_src:
            raise AssertionError("generic shell in desktop shell")
    finally:
        desktop_settings.SETTINGS_PATH = saved_path
    print("DESKTOP_SETTINGS_TEST=PASS")
    print("SETTINGS=LOCAL_JSON_CLAMPED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
