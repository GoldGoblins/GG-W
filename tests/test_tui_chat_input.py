#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QObject

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


class _RootProbe(QObject):
    def findChild(self, *_args):  # type: ignore[no-untyped-def]
        return None


class _SurfaceProbe:
    def __init__(self) -> None:
        self.notices: list[tuple[str, str]] = []

    def showChatTerminalNotice(self, terminal_id: str, text: str) -> bool:
        self.notices.append((terminal_id, text))
        return True


class _BridgeProbe:
    """Small stand-in that exercises ChatBridge's native-TUI ingress."""

    pass


class _FocusItemProbe:
    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        self._parent = parent

    def parentItem(self):  # type: ignore[no-untyped-def]
        return self._parent


class _FocusWindowProbe:
    def __init__(self, active=None) -> None:  # type: ignore[no-untyped-def]
        self.active = active

    def activeFocusItem(self):  # type: ignore[no-untyped-def]
        return self.active


class _GridProbe:
    def __init__(self) -> None:
        self.window_probe = _FocusWindowProbe()

    def isVisible(self) -> bool:
        return True

    def window(self):  # type: ignore[no-untyped-def]
        return self.window_probe


def main() -> int:
    from backend.chat_surface_host import ChatSurfaceHost
    from main import ChatBridge

    app = QCoreApplication.instance() or QCoreApplication([])

    host = ChatSurfaceHost()
    host._sessions["ws.tui.gpt"] = {}
    notices: list[tuple[str, str]] = []
    focus_requests: list[str] = []
    host.chatTerminalNotice.connect(
        lambda terminal_id, text: notices.append((terminal_id, text))
    )
    host.chatTerminalFocusRequested.connect(focus_requests.append)
    if not host.showChatTerminalNotice(
        "ws.tui.gpt",
        "GG: Ja mottaget. Godkännandet behandlas.",
    ):
        raise AssertionError("terminal notice was not accepted")
    if notices != [
        ("ws.tui.gpt", "GG: Ja mottaget. Godkännandet behandlas.")
    ]:
        raise AssertionError("approval notice was not surfaced")

    host._arm_tui_focus("ws.tui.gpt")
    deadline = time.monotonic() + 1.0
    while not focus_requests and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if focus_requests != ["ws.tui.gpt"]:
        raise AssertionError("quiet PTY did not request focus restoration")
    host._sessions.clear()
    host.shutdown()

    # A quiet PTY must not reclaim focus after the operator has moved to a
    # different control.  A descendant of the terminal grid remains safe to
    # refocus, which preserves the startup/response handoff.
    focus_host = ChatSurfaceHost()
    focus_host._sessions["ws.tui.gpt"] = {}
    focus_grid = _GridProbe()
    focus_host._gpt_grid = focus_grid
    focus_host._gpt_hole = _FocusItemProbe()
    focus_requests = []
    focus_host.chatTerminalFocusRequested.connect(focus_requests.append)
    focus_grid.window_probe.active = _FocusItemProbe()
    focus_host._tui_focus_terminal = "ws.tui.gpt"
    focus_host._emit_tui_focus_request()
    if focus_requests:
        raise AssertionError("PTY focus restoration stole another control's focus")
    focus_grid.window_probe.active = _FocusItemProbe(focus_grid)
    focus_host._tui_focus_terminal = "ws.tui.gpt"
    focus_host._emit_tui_focus_request()
    if focus_requests != ["ws.tui.gpt"]:
        raise AssertionError("terminal-owned focus was not restorable")
    focus_host._gpt_grid = None
    focus_host._gpt_hole = None
    focus_host._sessions.clear()
    focus_host.shutdown()

    # Exercise the real host ingress, not only the bridge callback. The
    # typed characters arrive before Enter, so an intercepted approval must
    # clear the native line without Ctrl-C and must do so on the first try.
    import backend.chat_surface_host as surface_module

    host = ChatSurfaceHost()
    host._sessions["ws.tui.gpt"] = {
        "master": 123,
        "write_queue": bytearray(),
        "write_notifier": None,
    }
    writes: list[bytes] = []
    old_write = surface_module._write_pty
    try:
        surface_module._write_pty = lambda _fd, data: (
            writes.append(bytes(data)) or len(data)
        )
        host.set_tui_chat_line_handler(lambda _id, text: text == "ja")
        if not host._write_chat_terminal(
            "ws.tui.gpt", "j", user_input=True
        ):
            raise AssertionError("first approval character was not accepted")
        if not host._write_chat_terminal(
            "ws.tui.gpt", "a", user_input=True
        ):
            raise AssertionError("second approval character was not accepted")
        if not host._write_chat_terminal(
            "ws.tui.gpt", "\r", user_input=True
        ):
            raise AssertionError("approval Enter was not accepted")
    finally:
        surface_module._write_pty = old_write
    if b"\x03" in b"".join(writes):
        raise AssertionError("approval still cancels the native TUI")
    if b"\x15" not in b"".join(writes):
        raise AssertionError("approval did not clear the native input line")

    paste_writes: list[bytes] = []
    try:
        surface_module._write_pty = lambda _fd, data: (
            paste_writes.append(bytes(data)) or len(data)
        )
        host.set_tui_chat_line_handler(lambda _id, _text: False)
        url = "https://x.com/davepl1968/status/2097312063714729991"
        if not host._write_chat_terminal(
            "ws.tui.gpt", url, user_input=True
        ):
            raise AssertionError("pasted URL was not accepted")
        if not host._write_chat_terminal(
            "ws.tui.gpt", "\r", user_input=True
        ):
            raise AssertionError("Enter after pasted URL was not accepted")
    finally:
        surface_module._write_pty = old_write
    if b"".join(paste_writes) != url.encode("utf-8") + b"\r":
        raise AssertionError("pasted URL or its Enter was truncated")
    host._sessions.clear()
    host.shutdown()

    class ProbeBridge(ChatBridge):
        def __init__(self) -> None:
            QObject.__init__(self)
            self._root = _RootProbe()
            self._pending_mandates = {
                "pending": {
                    "status": "WAITING_APPROVAL",
                    "approval_mode": "CHAT_NATIVE_TASK_SCOPED",
                }
            }
            self._resident_chat = SimpleNamespace(
                _surface_host=_SurfaceProbe()
            )
            self.submissions: list[tuple[str, str, str]] = []

        def submit(
            self,
            text: str,
            context_reference: str,
            workspace_object_id: str,
        ) -> None:
            self.submissions.append(
                (text, context_reference, workspace_object_id)
            )

    bridge = ProbeBridge()
    if not bridge._handle_tui_chat_line("ws.tui.gpt", "ja"):
        raise AssertionError("native approval was not intercepted")
    app.processEvents()
    if bridge.submissions != [("ja", "@current", "ws.file.scratch.1")]:
        raise AssertionError("native approval was not scheduled")
    if bridge._resident_chat._surface_host.notices != [
        (
            "ws.tui.gpt",
            "GG: Ja mottaget. Godkännandet behandlas för uppgiften.",
        )
    ]:
        raise AssertionError("native approval feedback was not visible")
    bridge._pending_mandates.clear()
    if bridge._handle_tui_chat_line("ws.tui.gpt", "ja"):
        raise AssertionError(
            "bare ja without a waiting task was swallowed by the TUI ingress"
        )
    bridge._pending_mandates = {
        "pending-a": {
            "pending_id": "pending-a",
            "status": "WAITING_APPROVAL",
            "approval_mode": "CHAT_NATIVE_TASK_SCOPED",
        },
        "pending-b": {
            "pending_id": "pending-b",
            "status": "WAITING_APPROVAL",
            "approval_mode": "CHAT_NATIVE_TASK_SCOPED",
        },
    }
    if not bridge._handle_tui_chat_line("ws.tui.gpt", "ja"):
        raise AssertionError("latest waiting approval was not intercepted")
    app.processEvents()
    if bridge.submissions[-1] != ("ja", "@current", "ws.file.scratch.1"):
        raise AssertionError("latest waiting approval was not scheduled")
    if bridge._pending_mandates["pending-a"]["status"] != "SUPERSEDED":
        raise AssertionError("older waiting approval was not superseded")
    if not any(
        "Ja mottaget" in text
        for _terminal_id, text in bridge._resident_chat._surface_host.notices
    ):
        raise AssertionError("latest approval feedback was not visible")
    bridge._pending_mandates.clear()
    if bridge._handle_tui_chat_line("ws.tui.gpt", "ändra koden i desktop"):
        raise AssertionError("local chat was swallowed as an approval")
    if bridge._handle_tui_chat_line(
        "ws.tui.gpt", "uppdatera det som är live på one.com"
    ):
        raise AssertionError("live chat line was deleted from the TUI")
    print("TUI_CHAT_INPUT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
