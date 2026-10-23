from __future__ import annotations

import codecs
import json
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QTimer

from backend.controlled_information_tools import (
    MAX_TOOL_ROUNDS,
    InformationToolError,
    continuation_prompt,
    continue_request,
    execute_information_tool,
    extract_edit_proposal,
    extract_tool_request,
    validate_information_tool_request,
)
from backend.resident_chat_runner import classify_runtime_failure
from backend.grok_worker_contract import (
    ENGINE_FLOW_TUI,
    ENGINE_GPT_TUI,
    ENGINE_GROK_TUI,
    ENGINE_GROK_WORKER,
    GPT_TUI_TERMINAL_ID,
    GROK_TUI_TERMINAL_ID,
    GrokWorkerContractError,
    normalize_engine_target,
)
from backend.grok_worker_qt import GrokWorkerTransport
from backend.chat_surface_host import ChatSurfaceHost

EVENT_SCHEMA = "gg.workbench.resident-chat-event.v1"


def split_think_delta(
    delta: str,
    in_think: bool,
) -> tuple[list[tuple[str, str]], bool]:
    pieces: list[tuple[str, str]] = []
    rest = delta
    lower = rest.lower()
    while rest:
        open_at = lower.find("<think>")
        close_at = lower.find("</think>")
        if open_at < 0 and close_at < 0:
            kind = "thought" if in_think else "text"
            if rest:
                pieces.append((kind, rest))
            break
        cut = (
            close_at
            if close_at >= 0 and (open_at < 0 or close_at < open_at)
            else open_at
        )
        if cut > 0:
            kind = "thought" if in_think else "text"
            pieces.append((kind, rest[:cut]))
        if cut == close_at:
            in_think = False
            rest = rest[cut + len("</think>") :]
        else:
            in_think = True
            rest = rest[cut + len("<think>") :]
        lower = rest.lower()
    return [(kind, text) for kind, text in pieces if text], in_think


class ResidentChatQtError(RuntimeError):
    pass


class ResidentChatTransport(QObject):
    def __init__(
        self,
        parent: QObject,
        root: QObject,
        activity_callback: Callable[[bool, str], None],
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._activity_callback = activity_callback
        self._process: QProcess | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._busy = False
        self._request_id = ""
        self._context_reference = "@current"
        self._workspace_object_id = ""
        self._response_text = ""
        self._stop_requested = False
        self._closing = False
        self._info_tool_rounds = 0
        self._narrative_serial = 0
        self._open_kind = ""
        self._open_id = ""
        self._open_text = ""
        self._in_think = False
        self._grok: GrokWorkerTransport | None = None
        self._surface_host = ChatSurfaceHost(self)
        self._surface_host.set_qml_root(root)
        root.setProperty("surfaceHost", self._surface_host)
        from backend.desktop_settings import apply_to_root

        apply_to_root(root)
        # Legacy desktop settings hydrate first.  Re-apply the presentation
        # profile on the next event-loop turn so a selected theme/profile is
        # the final shared visual layer after both state stores are available.
        visual_loader = getattr(root, "loadVisualLayoutState", None)
        if callable(visual_loader):
            QTimer.singleShot(0, lambda: visual_loader())

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def _engine_target(self) -> str:
        try:
            return normalize_engine_target(self._root.property("engineTarget"))
        except GrokWorkerContractError as exc:
            raise ResidentChatQtError(str(exc)) from exc

    def _grok_worker(self) -> GrokWorkerTransport:
        if self._grok is None:
            self._grok = GrokWorkerTransport(
                self,
                self._root,
                self._activity_callback,
            )
        return self._grok

    def busy(self) -> bool:
        if self._busy:
            return True
        return self._grok is not None and self._grok.busy()

    def active_request_id(self) -> str:
        if self._busy:
            return self._request_id
        if self._grok is not None:
            return self._grok.active_request_id()
        return ""

    def status_text(self) -> str:
        if self._grok is not None and self._grok.busy():
            return self._grok.status_text()
        process_state = (
            "RUNNING"
            if self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
            else "STOPPED"
        )
        return (
            "ACTIVE="
            + ("YES" if self._busy else "NO")
            + "\nKIND=RESIDENT_CHAT"
            + "\nID="
            + self._request_id
            + "\nSTOPPABLE="
            + ("YES" if self._busy else "NO")
            + "\nSTOP_REQUESTED="
            + ("YES" if self._stop_requested else "NO")
            + "\nSESSION_PROCESS="
            + process_state
        )

    def submit(
        self,
        request: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
        _workspace_context: dict[str, object],
    ) -> bool:
        target = self._engine_target()
        if target == ENGINE_FLOW_TUI:
            prompt = str(request.get("prompt") or "")
            host = self._surface_host
            if host is None or not callable(getattr(host, "flowTuiSubmit", None)):
                raise ResidentChatQtError("FLOW_TUI_HOST_MISSING")
            host.flowTuiSubmit(prompt)
            return True
        if target == ENGINE_GROK_TUI:
            prompt = str(request.get("prompt") or "")
            host = self._surface_host
            if host is None:
                raise ResidentChatQtError("GROK_TUI_HOST_MISSING")
            if not host.startGrokTui(GROK_TUI_TERMINAL_ID):
                raise ResidentChatQtError("GROK_TUI_START_FAILED")
            if prompt and not host.writeChatTerminal(
                GROK_TUI_TERMINAL_ID, prompt + "\n"
            ):
                raise ResidentChatQtError("GROK_TUI_STDIN_FAILED")
            return True
        if target == ENGINE_GPT_TUI:
            prompt = str(request.get("prompt") or "")
            host = self._surface_host
            if host is None:
                raise ResidentChatQtError("GPT_TUI_HOST_MISSING")
            start = getattr(host, "startGptTui", None)
            if not callable(start) or not start():
                raise ResidentChatQtError("GPT_TUI_START_FAILED")
            if prompt and not host.writeChatTerminal(
                GPT_TUI_TERMINAL_ID, prompt + "\n"
            ):
                raise ResidentChatQtError("GPT_TUI_STDIN_FAILED")
            return True
        if target == ENGINE_GROK_WORKER:
            if self._busy:
                raise ResidentChatQtError("RESIDENT_CHAT_BUSY")
            return self._grok_worker().submit(
                request,
                context_reference,
                workspace_object_id,
                _workspace_context,
            )

        if self._busy:
            raise ResidentChatQtError("RESIDENT_CHAT_BUSY")

        request_id = str(request["request_id"])
        prompt = str(request["prompt"])
        if not request_id or not prompt:
            raise ResidentChatQtError("RESIDENT_CHAT_REQUEST_INVALID")

        begin = getattr(self._root, "beginStreamingResponse", None)
        if not callable(begin):
            raise ResidentChatQtError("QML beginStreamingResponse is unavailable.")

        begin(request_id, context_reference)

        self._busy = True
        self._request_id = request_id
        self._context_reference = context_reference
        self._workspace_object_id = workspace_object_id
        self._response_text = ""
        self._stop_requested = False
        self._info_tool_rounds = 0
        self._narrative_serial = 0
        self._open_kind = ""
        self._open_id = ""
        self._open_text = ""
        self._in_think = False
        self._activity_callback(True, request_id)

        try:
            self._ensure_server()
            payload = (
                json.dumps(request, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            process = self._process
            if process is None:
                raise ResidentChatQtError("RESIDENT_CHAT_PROCESS_MISSING")
            written = process.write(payload)
            if written != len(payload):
                raise ResidentChatQtError("RESIDENT_CHAT_OUTER_STDIN_SHORT_WRITE")
            return True
        except Exception as exc:
            self._fail_current(
                "Resident chat transport kunde inte starta turnen: "
                + type(exc).__name__
                + ":"
                + str(exc)
            )
            return False

    def accept_followup(
        self,
        prompt: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> bool:
        if self._busy or self._grok is None or not self._grok.busy():
            return False
        if not prompt.strip():
            return False
        return bool(
            self._grok.submit(
                {
                    "request_id": self._grok.active_request_id() or "followup",
                    "prompt": prompt,
                },
                context_reference,
                workspace_object_id,
                {},
            )
        )

    def stop(self) -> bool:
        if self._grok is not None and self._grok.busy():
            return self._grok.stop()
        if not self._busy:
            return False
        self._stop_requested = True
        self._update_node(self._response_text, "STOPPING")
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
        return True

    def shutdown_idle(self) -> bool:
        if self.busy():
            return False
        if self._grok is not None:
            self._grok.shutdown_idle()
        self.shutdown()
        return True

    def shutdown(self) -> None:
        if self._surface_host is not None:
            self._surface_host.shutdown()
        if self._grok is not None:
            self._grok.shutdown()
        self._closing = True
        process = self._process
        try:
            if process is not None and process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(3500):
                    process.kill()
                    process.waitForFinished(3500)
        finally:
            still_owned = self._process is process
            self._process = None
            self._stdout_buffer = ""
            self._stderr_buffer = ""
            self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
            if self._busy:
                self._busy = False
                self._activity_callback(False, "")
            self._request_id = ""
            self._stop_requested = False
            self._closing = False
            if process is not None and still_owned:
                process.deleteLater()

    def _ensure_server(self) -> None:
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            return

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-B",
                "-m",
                "backend.resident_chat_runner",
                "--serve",
            ]
        )
        project = Path(__file__).resolve().parents[1]
        process.setWorkingDirectory(str(project))
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardOutput.connect(self._stdout_ready)
        process.readyReadStandardError.connect(self._stderr_ready)
        process.finished.connect(self._finished)
        self._process = process
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        process.start()
        if not process.waitForStarted(5000):
            error = process.errorString()
            process.deleteLater()
            self._process = None
            raise ResidentChatQtError(
                "Resident chat runner kunde inte starta: " + error
            )

    def _stdout_ready(self) -> None:
        process = self._process
        if process is None:
            return
        raw = bytes(process.readAllStandardOutput())
        if not raw:
            return
        try:
            self._stdout_buffer += self._decoder.decode(raw, final=False)
            while "\n" in self._stdout_buffer:
                line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
                if line:
                    self._consume_event(line)
        except Exception as exc:
            self._fail_current(
                "Resident chat eventström blev ogiltig: "
                + type(exc).__name__
                + ":"
                + str(exc)
            )
            if process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()

    def _stderr_ready(self) -> None:
        process = self._process
        if process is None:
            return
        raw = bytes(process.readAllStandardError())
        if raw:
            self._stderr_buffer += raw.decode("utf-8", errors="replace")
            if len(self._stderr_buffer) > 12000:
                self._stderr_buffer = self._stderr_buffer[-12000:]

    def _consume_event(self, line: str) -> None:
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ResidentChatQtError("RESIDENT_EVENT_NOT_OBJECT")
        if event.get("schema") != EVENT_SCHEMA:
            raise ResidentChatQtError("RESIDENT_EVENT_SCHEMA_MISMATCH")

        kind = str(event.get("event", ""))
        event_request_id = str(event.get("request_id", ""))

        if kind == "SESSION_STARTING":
            if self._busy:
                self._update_node(self._response_text, "STARTING")
            return

        if kind == "SESSION_READY":
            if self._busy:
                self._update_node(self._response_text, "GENERATING")
            return

        if kind == "TURN_START":
            self._require_active_event(event_request_id)
            self._update_node(self._response_text, "GENERATING")
            return

        if kind == "DELTA":
            self._require_active_event(event_request_id)
            delta = event.get("text")
            if not isinstance(delta, str):
                raise ResidentChatQtError("RESIDENT_DELTA_NOT_STRING")
            for piece_kind, piece in self._split_think_delta(delta):
                if piece_kind == "text":
                    self._response_text += piece
                card_id, text = self._accumulate_narrative(piece_kind, piece)
                self._upsert_stream_card(
                    card_id,
                    piece_kind,
                    "Thought" if piece_kind == "thought" else "",
                    text,
                    "STREAMING",
                )
            self._update_node(self._response_text, "STREAMING")
            return

        if kind == "COMPLETE":
            self._require_active_event(event_request_id)
            original = self._response_text
            try:
                from backend.chat_machine_assist import (
                    HOST_PROFILES,
                    extract_model_host_actions,
                )

                extract_tool_request(original)
                visible, actions = extract_model_host_actions(original)
                edit_visible, edit_proposal = extract_edit_proposal(original)
            except InformationToolError as exc:
                reason = str(exc)
                if reason.startswith("EDIT_PROPOSAL_") or "READ_PATH_TEMPLATE" in reason:
                    self._bounce_structured_output(reason)
                    return
                raise
            tool_request = actions[0] if actions else None
            if tool_request is not None and edit_proposal is not None:
                raise ResidentChatQtError("TOOL_AND_EDIT_AMBIGUOUS")
            host_batch = bool(actions) and all(
                str(item.get("profile")) in HOST_PROFILES for item in actions
            )
            self._response_text = (
                visible
                if tool_request is not None
                else edit_visible
            )
            if (
                host_batch
                and self._info_tool_rounds < MAX_TOOL_ROUNDS
            ):
                self._run_host_action_batch(actions, visible)
                return
            if (
                tool_request is not None
                and self._info_tool_rounds < MAX_TOOL_ROUNDS
            ):
                if self._open_id:
                    self._upsert_stream_card(
                        self._open_id,
                        "text",
                        "",
                        visible,
                        "STREAMING",
                    )
                self._continue_with_information_tool(tool_request)
                return
            if (
                edit_proposal is not None
                and self._info_tool_rounds < MAX_TOOL_ROUNDS
            ):
                self._info_tool_rounds += 1
                if visible and self._open_id:
                    self._upsert_stream_card(
                        self._open_id,
                        "text",
                        "",
                        visible,
                        "STREAMING",
                    )
                self._surface_edit_proposal(edit_proposal)
                return
            if not self._response_text.strip():
                raise ResidentChatQtError("RESIDENT_EMPTY_RESPONSE")
            failure = classify_runtime_failure(
                self._response_text,
                self._stderr_buffer,
            )
            if failure:
                self._fail_current("RESIDENT_RUNTIME_FAILURE:" + failure)
                process = self._process
                if (
                    process is not None
                    and process.state() != QProcess.ProcessState.NotRunning
                ):
                    process.terminate()
                return
            self._update_node(self._response_text, "PASS")
            self._complete_current()
            return

        if kind == "ERROR":
            message = str(event.get("message", "resident chat error"))
            if self._busy and (not event_request_id or event_request_id == self._request_id):
                self._fail_current(message)
            process = self._process
            if process is not None and process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
            return

        raise ResidentChatQtError("RESIDENT_EVENT_UNKNOWN:" + kind)

    def _close_narrative(self) -> None:
        self._open_kind = ""
        self._open_id = ""
        self._open_text = ""

    def _split_think_delta(self, delta: str) -> list[tuple[str, str]]:
        pieces, self._in_think = split_think_delta(delta, self._in_think)
        return pieces

    def _accumulate_narrative(self, kind: str, delta: str) -> tuple[str, str]:
        if self._open_kind != kind or not self._open_id:
            self._narrative_serial += 1
            self._open_kind = kind
            self._open_id = kind + "-" + str(self._narrative_serial)
            self._open_text = ""
        self._open_text += delta
        return self._open_id, self._open_text

    def _upsert_stream_card(
        self,
        card_id: str,
        kind: str,
        title: str,
        text: str,
        state: str,
    ) -> bool:
        upsert = getattr(self._root, "upsertGrokWorkerCard", None)
        if not callable(upsert):
            return False
        return bool(
            upsert(self._request_id, card_id, kind, title, text, state)
        )

    def _append_visible(
        self,
        kind: str,
        text: str,
        state: str,
    ) -> None:
        card_kind = "tool_call_update"
        title = kind
        if kind == "TOOL":
            first = text.split("\n", 1)[0]
            if first.startswith("READ ") or first.startswith("READ"):
                title = first if first.startswith("Read") else "Read"
                card_kind = "tool_call_update"
            elif first.startswith("TEST ") or first.startswith("RUN "):
                title = "terminal"
            elif first.startswith("SEARCH "):
                title = "grep"
            else:
                profile = first.split(" ", 1)[0]
                if profile in {"TEST", "RUN"}:
                    title = "terminal"
                elif profile == "READ":
                    title = "Read"
                elif profile == "SEARCH":
                    title = "grep"
                else:
                    title = profile or "tool"
        elif kind == "APPROVAL":
            card_kind = "text"
            title = ""
        if self._upsert_stream_card(
            kind.lower() + "-" + str(self._info_tool_rounds),
            card_kind,
            title,
            text,
            state,
        ):
            return
        append = getattr(self._root, "appendRealNode", None)
        if not callable(append):
            return
        append(
            "GG SYSTEM",
            kind,
            text,
            self._context_reference + " · " + self._workspace_object_id,
            state,
            28,
            self._request_id,
        )

    def _focus_workspace_current(self) -> None:
        workspace = self._root.findChild(QObject, "workspaceSurface")
        if workspace is None:
            return
        focus = getattr(workspace, "focusObject", None)
        if callable(focus):
            focus(self._workspace_object_id)

    def _bounce_structured_output(self, reason: str) -> None:
        if self._info_tool_rounds >= MAX_TOOL_ROUNDS:
            self._fail_current("Structured output rejected: " + reason)
            return
        self._info_tool_rounds += 1
        self._append_visible(
            "APPROVAL",
            "EDIT proposal rejected · " + reason + " · file unchanged · retrying.",
            "BLOCKED",
        )
        follow = continue_request(
            self._request_id,
            "SYSTEM: Previous GG_EDIT_PROPOSAL was rejected ("
            + reason
            + "). old_text must be copied from the open file and new_text "
            "must differ. Emit exactly one valid JSON object after "
            "GG_EDIT_PROPOSAL=. Wrapping quotes are raw ASCII 0x22, not "
            '\\". Do not write \\", or \\"} as a field terminator. '
            "Do not apply the file.",
        )
        payload = (
            json.dumps(follow, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            raise ResidentChatQtError("RESIDENT_CHAT_PROCESS_MISSING")
        self._response_text = ""
        self._update_node("", "GENERATING")
        written = process.write(payload)
        if written != len(payload):
            raise ResidentChatQtError("RESIDENT_CHAT_OUTER_STDIN_SHORT_WRITE")

    def _surface_edit_proposal(self, proposal: dict[str, str]) -> None:
        # Chat display only. Limited Write ACTION_PROPOSE stays on
        # explicit human /approve-write. The model does not apply.
        self._focus_workspace_current()
        self._close_narrative()
        old_text = proposal["old_text"]
        new_text = proposal["new_text"]
        diff = (
            "--- a/"
            + self._workspace_object_id
            + "\n+++ b/"
            + self._workspace_object_id
            + "\n@@\n- "
            + old_text.replace("\n", "\n- ")
            + "\n+ "
            + new_text.replace("\n", "\n+ ")
            + "\n"
        )
        self._upsert_stream_card(
            "edit-" + str(self._info_tool_rounds),
            "tool_call_update",
            "code",
            diff,
            "PASS",
        )
        visible = self._response_text.strip()
        if not visible:
            visible = "Föreslagen ändring (sparad inte)."
            self._response_text = visible
        self._update_node(visible, "PASS")
        self._complete_current()

    def _run_host_action_batch(
        self,
        actions: list[dict[str, object]],
        visible: str,
    ) -> None:
        from backend.chat_machine_assist import execute_host_tool

        workspace = self._root.findChild(QObject, "workspaceSurface")
        self._focus_workspace_current()
        self._close_narrative()
        spoken = str(visible or "").strip()
        for raw in actions:
            if self._info_tool_rounds >= MAX_TOOL_ROUNDS:
                break
            self._info_tool_rounds += 1
            parsed = validate_information_tool_request(raw)
            profile = str(parsed.get("profile") or "")
            title = "terminal" if profile == "TERMINAL_RUN" else "code"
            card_id = "host-" + str(self._info_tool_rounds)
            self._upsert_stream_card(
                card_id,
                "tool_call",
                title,
                profile + " RUNNING",
                "RUNNING",
            )
            app = QCoreApplication.instance()
            if app is not None:
                app.processEvents()
            try:
                result = execute_host_tool(parsed, workspace=workspace)
            except Exception as exc:
                result = {
                    "profile": profile,
                    "status": "ERROR",
                    "output": type(exc).__name__ + ":" + str(exc),
                }
            output = result["output"][:1200]
            body = output
            if profile == "TERMINAL_RUN" and not output.startswith("$ "):
                body = "$ " + output
            self._upsert_stream_card(
                card_id,
                "tool_call_update",
                title,
                body,
                "PASS" if result["status"] == "PASS" else "FAIL",
            )
        if spoken:
            self._response_text = spoken
        elif not self._response_text.strip():
            self._response_text = "Hosten körde allowlistad handling."
        self._update_node(self._response_text, "PASS")
        self._complete_current()

    def _continue_with_information_tool(
        self,
        tool_request: dict[str, object],
    ) -> None:
        self._info_tool_rounds += 1
        profile = str(tool_request["profile"])
        verifying = profile in {"TEST", "RUN"}
        self._focus_workspace_current()
        self._close_narrative()
        path = ""
        arguments = tool_request.get("arguments")
        if isinstance(arguments, dict):
            raw_path = arguments.get("path")
            if isinstance(raw_path, str):
                path = raw_path
        title = "terminal" if verifying or profile == "TERMINAL_RUN" else (
            "Read " + path if path else profile
        )
        if profile == "CURRENT_WRITE":
            title = "code"
        if profile == "CURRENT_READ":
            title = "Read @current"
        if profile == "SEARCH":
            literal = ""
            if isinstance(arguments, dict):
                raw_lit = arguments.get("literal")
                if isinstance(raw_lit, str):
                    literal = raw_lit
            title = "grep " + literal if literal else "grep"
        self._upsert_stream_card(
            "tool-" + str(self._info_tool_rounds),
            "tool_call",
            title,
            profile + " RUNNING",
            "RUNNING",
        )
        self._update_node(
            self._response_text
            or ("Verifierar med låst suite…" if verifying else "Hämtar source-evidence…"),
            "RUNNING",
        )
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()
        try:
            from backend.chat_machine_assist import HOST_PROFILES, execute_host_tool

            if profile in HOST_PROFILES:
                workspace = self._root.findChild(QObject, "workspaceSurface")
                result = execute_host_tool(tool_request, workspace=workspace)
            else:
                result = execute_information_tool(tool_request)
        except Exception as exc:
            result = {
                "profile": profile,
                "status": "ERROR",
                "output": type(exc).__name__ + ":" + str(exc),
            }
        output = result["output"][:1200]
        body = output
        if verifying or profile == "TERMINAL_RUN":
            body = output if output.startswith("$ ") else ("$ " + output)
        self._upsert_stream_card(
            "tool-" + str(self._info_tool_rounds),
            "tool_call_update",
            title,
            body,
            "PASS" if result["status"] == "PASS" else "FAIL",
        )
        follow = continue_request(
            self._request_id,
            continuation_prompt(result),
        )
        payload = (
            json.dumps(follow, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            raise ResidentChatQtError("RESIDENT_CHAT_PROCESS_MISSING")
        self._response_text = ""
        self._close_narrative()
        self._update_node(self._response_text, "GENERATING")
        written = process.write(payload)
        if written != len(payload):
            raise ResidentChatQtError("RESIDENT_CHAT_OUTER_STDIN_SHORT_WRITE")

    def _require_active_event(self, request_id: str) -> None:
        if not self._busy or request_id != self._request_id:
            raise ResidentChatQtError(
                "RESIDENT_EVENT_REQUEST_MISMATCH:"
                + request_id
                + ":"
                + self._request_id
            )

    def _update_node(self, text: str, state: str) -> None:
        update = getattr(self._root, "updateStreamingResponse", None)
        if not callable(update):
            raise ResidentChatQtError("QML updateStreamingResponse is unavailable.")
        if not bool(update(self._request_id, text, state)):
            raise ResidentChatQtError("QML streaming response node is missing.")

    def _complete_current(self) -> None:
        self._busy = False
        self._request_id = ""
        self._response_text = ""
        self._stop_requested = False
        self._activity_callback(False, "")

    def _fail_current(self, message: str) -> None:
        if self._busy and self._request_id:
            body = self._response_text
            if body and not body.endswith("\n\n"):
                body += "\n\n"
            body += "Resident chat stoppade säkert: " + message
            fail_state = "CANCELLED" if self._stop_requested else "FAIL"
            self._upsert_stream_card(
                "error",
                "error",
                "error",
                body,
                fail_state,
            )
            try:
                self._update_node(
                    body,
                    fail_state,
                )
            except Exception:
                pass
        self._busy = False
        self._request_id = ""
        self._response_text = ""
        self._stop_requested = False
        self._activity_callback(False, "")

    def _finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        if process is None:
            return
        self._stderr_ready()

        was_busy = self._busy
        was_stop = self._stop_requested
        closing = self._closing
        stderr_tail = self._stderr_buffer[-2000:].strip()

        self._process = None
        process.deleteLater()

        if was_busy and not closing:
            message = (
                "Resident chat stoppades av användaren."
                if was_stop
                else (
                    "Resident chat runner avslutades oväntat"
                    + " · rc="
                    + str(exit_code)
                    + (
                        " · stderr=" + stderr_tail
                        if stderr_tail
                        else ""
                    )
                )
            )
            self._fail_current(message)
        elif not closing:
            self._activity_callback(False, "")
