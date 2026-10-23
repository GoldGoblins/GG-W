"""Select the installed Windows browser runtime before creating any window."""
from __future__ import annotations

import os

_ready = False
_filtering_ready = False


def native_webview_ready() -> bool:
    return _ready


def native_webview_filtering_ready() -> bool:
    return _filtering_ready


def initialize_native_webview() -> bool:
    global _ready, _filtering_ready
    if os.name != "nt":
        return False
    from backend.application_paths import STATE_ROOT
    # Keep website cookies and logins in this user's app data, never beside
    # python.exe or in the distributable source tree.
    profile = STATE_ROOT / "webview2-profile"
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["QTWEBVIEW_PLUGIN"] = "webview2"
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(profile)
    from PySide6.QtWebView import QtWebView
    QtWebView.initialize()
    from backend.windows_webview import register
    _filtering_ready = register()
    _ready = True
    return True
