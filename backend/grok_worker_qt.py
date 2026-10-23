from __future__ import annotations

from backend.platform_files import (
    secure_open,
)
from backend.platform_support import (
    private_runtime_root,
)


import codecs
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QProcessEnvironment

from backend.grok_worker_contract import (
    ENGINE_GROK_WORKER,
    GROK_BIN,
    GROK_CWD,
    GROK_HOME,
    SESSION_STATE_PATH,
    GrokWorkerContractError,
    build_grok_argv,
    compose_worker_prompt,
    dump_session_state,
    ensure_product_grok_home,
    hash_workspace_identity,
    load_session_id,
    new_session_id,
    session_exists_locally,
    project_worker_line,
    reject_card_flood,
    reject_oversized_buffer,
    reject_oversized_response,
)


class GrokWorkerError(RuntimeError):
    pass


class GrokWorkerTransport(QObject):
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
        self._terminal_text = ""
        self._stop_requested = False
        self._closing = False
        self._session_id = ""
        self._resume = False
        self._prompt_path: Path | None = None
        self._saw_end = False
        self._seen_cards: set[str] = set()
        self._queued_prompts: list[tuple[str, str]] = []
        self._followup_serial = 0
        self._narrative_serial = 0
        self._open_kind = ""
        self._open_id = ""
        self._open_text = ""

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def busy(self) -> bool:
        return self._busy

    def active_request_id(self) -> str:
        return self._request_id if self._busy else ""

    def status_text(self) -> str:
        process_state = (
            "RUNNING"
            if self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
            else "STOPPED"
        )
        return (
            "ACTIVE="
            + ("YES" if self._busy else "NO")
            + "\nKIND=GROK_WORKER"
            + "\nENGINE="
            + ENGINE_GROK_WORKER
            + "\nID="
            + self._request_id
            + "\nSESSION="
            + self._session_id
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
        request_id = str(request["request_id"])
        prompt = str(request["prompt"])
        if not request_id or not prompt:
            raise GrokWorkerError("GROK_WORKER_REQUEST_INVALID")

        if self._busy:
            self._followup_serial += 1
            card_id = "user-" + str(self._followup_serial)
            self._queued_prompts.append((card_id, prompt))
            self._upsert_card(card_id, "user", "YOU", prompt, "QUEUED")
            return True

        begin_stream = getattr(self._root, "beginGrokWorkerStream", None)
        if not callable(begin_stream):
            raise GrokWorkerError("QML grok worker stream is unavailable.")

        begin_stream(request_id, context_reference)

        self._busy = True
        self._request_id = request_id
        self._context_reference = context_reference
        self._workspace_object_id = workspace_object_id
        self._response_text = ""
        self._terminal_text = ""
        self._stop_requested = False
        self._saw_end = False
        self._seen_cards = set()
        self._queued_prompts = []
        self._narrative_serial = 0
        self._open_kind = ""
        self._open_id = ""
        self._open_text = ""
        self._activity_callback(True, request_id)
        self._set_stream_state("STARTING")

        try:
            self._start_turn(prompt)
            return True
        except Exception as exc:
            self._fail_current(
                "Grok worker kunde inte starta turnen: "
                + type(exc).__name__
                + ":"
                + str(exc)
            )
            return False

    def stop(self) -> bool:
        if not self._busy:
            return False
        self._stop_requested = True
        self._queued_prompts = []
        self._set_stream_state("STOPPING")
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
        return True

    def shutdown_idle(self) -> bool:
        if self._busy:
            return False
        self.shutdown()
        return True

    def shutdown(self) -> None:
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
            self._unlink_prompt()
            if self._busy:
                self._busy = False
                self._activity_callback(False, "")
            self._request_id = ""
            self._stop_requested = False
            self._closing = False
            if process is not None and still_owned:
                process.deleteLater()

    def _start_turn(self, prompt: str) -> None:
        if not GROK_BIN.is_file() or not os.access(GROK_BIN, os.X_OK):
            raise GrokWorkerError("GROK_WORKER_BINARY_UNAVAILABLE")
        if self._process is not None:
            raise GrokWorkerError("GROK_WORKER_PROCESS_STILL_LIVE")

        try:
            stored = load_session_id(SESSION_STATE_PATH)
        except GrokWorkerContractError as exc:
            raise GrokWorkerError(str(exc)) from exc

        resume = bool(stored) and session_exists_locally(stored)
        session_id = stored if resume else new_session_id()
        try:
            identity = hash_workspace_identity(self._workspace_object_id)
            composed = compose_worker_prompt(
                prompt,
                context_reference=self._context_reference,
                identity=identity,
            )
        except GrokWorkerContractError as exc:
            raise GrokWorkerError(str(exc)) from exc
        prompt_path = self._write_prompt(composed)
        try:
            ensure_product_grok_home()
        except GrokWorkerContractError as exc:
            raise GrokWorkerError(str(exc)) from exc
        argv = build_grok_argv(
            prompt_path,
            session_id,
            resume=resume,
            grok_bin=GROK_BIN,
            cwd=GROK_CWD,
        )
        self._session_id = session_id
        self._resume = resume
        self._prompt_path = prompt_path

        process = QProcess(self)
        process.setProgram(argv[0])
        process.setArguments(argv[1:])
        process.setWorkingDirectory(str(GROK_CWD))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("GROK_HOME", str(GROK_HOME))
        process.setProcessEnvironment(environment)
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
            raise GrokWorkerError("Grok worker kunde inte starta: " + error)
        dump_session_state(session_id, SESSION_STATE_PATH)

    def _write_prompt(self, prompt: str) -> Path:
        runtime = private_runtime_root()
        path = runtime / ("gg-grok-worker-prompt." + new_session_id()[:12] + ".txt")
        fd = secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(prompt)
            if not prompt.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def _unlink_prompt(self) -> None:
        path = self._prompt_path
        self._prompt_path = None
        if path is None:
            return
        try:
            path.unlink()
        except OSError:
            pass

    def _stdout_ready(self) -> None:
        process = self._process
        if process is None:
            return
        raw = bytes(process.readAllStandardOutput())
        if not raw:
            return
        try:
            self._stdout_buffer += self._decoder.decode(raw, final=False)
            reject_oversized_buffer(self._stdout_buffer)
            while "\n" in self._stdout_buffer:
                line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
                if line:
                    self._consume_line(line)
        except Exception as exc:
            self._fail_current(
                "Grok worker eventström blev ogiltig: "
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

    def _consume_line(self, line: str) -> None:
        projected = project_worker_line(line)
        if projected is None:
            return
        session_id = projected.get("session_id", "")
        if session_id:
            self._session_id = session_id
            dump_session_state(session_id, SESSION_STATE_PATH)

        kind = projected["kind"]
        title = projected.get("title", "")
        text = projected.get("text", "")
        state = projected.get("state", "STREAMING")
        card_id = projected.get("card_id", kind)

        if kind in (
            "tool_call",
            "tool_call_update",
            "stdout",
            "error",
            "end",
            "user",
        ):
            self._open_kind = ""
            self._open_id = ""
            self._open_text = ""

        if kind == "thought":
            title = "Thought"
            card_id, text = self._accumulate_narrative("thought", text)
            state = "STREAMING"
        elif kind == "text":
            delta = text
            self._response_text += delta
            reject_oversized_response(self._response_text)
            card_id, text = self._accumulate_narrative("text", delta)
            state = "STREAMING"
        elif kind == "error":
            self._upsert_card(card_id, kind, title, text, "FAIL")
            self._fail_current(text)
            process = self._process
            if process is not None and process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
            return
        elif kind == "end":
            self._saw_end = True
            self._upsert_card(card_id, kind, title, text, "PASS")
            self._set_stream_state(
                "STREAMING" if self._queued_prompts else "PASS"
            )
            return

        self._upsert_card(card_id, kind, title, text, state)
        self._set_stream_state(state)

    def _accumulate_narrative(self, kind: str, delta: str) -> tuple[str, str]:
        if self._open_kind != kind or not self._open_id:
            self._narrative_serial += 1
            self._open_kind = kind
            self._open_id = kind + "-" + str(self._narrative_serial)
            self._open_text = ""
        self._open_text += delta
        reject_oversized_response(self._open_text)
        return self._open_id, self._open_text

    def _set_stream_state(self, state: str) -> None:
        update = getattr(self._root, "updateGrokWorkerState", None)
        if not callable(update):
            raise GrokWorkerError("QML updateGrokWorkerState is unavailable.")
        if not bool(update(self._request_id, state)):
            raise GrokWorkerError("QML grok worker stream node is missing.")

    def _upsert_card(
        self,
        card_id: str,
        kind: str,
        title: str,
        text: str,
        state: str,
    ) -> None:
        upsert = getattr(self._root, "upsertGrokWorkerCard", None)
        if not callable(upsert):
            raise GrokWorkerError("QML upsertGrokWorkerCard is unavailable.")
        if card_id not in self._seen_cards:
            self._seen_cards.add(card_id)
            reject_card_flood(len(self._seen_cards))
        if not bool(
            upsert(self._request_id, card_id, kind, title, text, state)
        ):
            raise GrokWorkerError("QML grok worker stream node is missing.")

    def _complete_current(self) -> None:
        self._unlink_prompt()
        self._queued_prompts = []
        self._busy = False
        self._request_id = ""
        self._response_text = ""
        self._stop_requested = False
        self._activity_callback(False, "")

    def _fail_current(self, message: str) -> None:
        if self._busy and self._request_id:
            try:
                self._set_stream_state(
                    "CANCELLED" if self._stop_requested else "FAIL"
                )
                self._upsert_card(
                    "error",
                    "error",
                    "error",
                    message,
                    "CANCELLED" if self._stop_requested else "FAIL",
                )
            except Exception:
                pass
        self._unlink_prompt()
        self._queued_prompts = []
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
        remainder = self._stdout_buffer
        self._stdout_buffer = ""
        closing = self._closing
        if remainder.strip() and self._busy:
            try:
                self._consume_line(remainder)
            except Exception as exc:
                if not closing:
                    self._process = None
                    process.deleteLater()
                    self._unlink_prompt()
                    self._fail_current(
                        "Grok worker EOF-remainder ogiltig: "
                        + type(exc).__name__
                        + ":"
                        + str(exc)
                    )
                    return

        was_busy = self._busy
        was_stop = self._stop_requested
        closing = self._closing
        stderr_tail = self._stderr_buffer[-2000:].strip()
        saw_end = self._saw_end

        self._process = None
        process.deleteLater()
        self._unlink_prompt()

        if was_busy and not closing and not saw_end:
            message = (
                "Grok worker stoppades av användaren."
                if was_stop
                else (
                    "Grok worker avslutades utan end-event"
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
            return
        if (
            was_busy
            and not closing
            and saw_end
            and self._queued_prompts
            and not was_stop
        ):
            pending = list(self._queued_prompts)
            self._queued_prompts = []
            follow = "\n\n".join(item[1] for item in pending)
            for card_id, prompt in pending:
                self._upsert_card(card_id, "user", "YOU", prompt, "SUBMITTED")
            self._saw_end = False
            self._set_stream_state("STREAMING")
            try:
                self._start_turn(follow)
            except Exception as exc:
                self._fail_current(
                    "Grok worker kunde inte fortsätta kön: "
                    + type(exc).__name__
                    + ":"
                    + str(exc)
                )
            return
        if was_busy and not closing:
            self._set_stream_state("PASS")
            self._complete_current()
        elif not closing:
            self._activity_callback(False, "")
