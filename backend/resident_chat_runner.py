from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.platform_files import (
    mode_matches,
    owned_by_current_user,
)
from backend.platform_support import (
    private_runtime_root,
)


from backend.application_paths import HOME

import codecs
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from backend import local_ai_contract as contract

EVENT_SCHEMA = "gg.workbench.resident-chat-event.v1"
MODEL_DIR = Path(str(HOME / 'models/qwen25-coder-7b-instruct-q4_k_m'))
MODEL_PATH = MODEL_DIR / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
MODEL_SHA256 = (
    "1664fccab734674a50763490a8c6931b70e3f2f8ec10031b54806d30e5f956b6"
)
RUNTIME_IMAGE = "localhost/gg-llama-cpp-vulkan:b10182"
RUNTIME_IMAGE_ID = "0a4db391fe04f0a5370ccc04bf2b9c3960180e569092a1e51a48d30ab425d178"
RUNTIME_IMAGE_DIGEST = (
    "sha256:"
    "61f81360fdf2d10c069cf183d1a8671f19977015d8fd42ef9868654c44697e44"
)
PODMAN = "/usr/bin/podman"
PROMPT_DELIMITER = b"\n\n> "
STARTUP_TIMEOUT_SECONDS = 45.0
TURN_TIMEOUT_SECONDS = 180.0
MAX_TURN_BYTES = 131072

SYSTEM_PROMPT = (
    "GG local Qwen2.5-Coder. Du är en kollega i en levande dator. "
    "Chatten är universell: vagt språk är ok, gissa avsikten. "
    "Hälsning får hälsning tillbaka. Öppen fil är inte uppdraget "
    "förrän de ber om kod, ändring eller en namngiven fil. "
    "Ingen tool-rad på hej/hejsan. Kopiera aldrig RELATIV. "
    "Hosten kör bara det du skriver, under användarens authority. "
    "Allowlistad terminal: ```bash med echo, pwd, date, ls, true, false. "
    "Skriv inte låtsas-stdout; hosten visar riktig output. "
    "Kod till öppna bufferten: ```javascript / ```qml / ```python "
    "eller ```diff med +rader. Sparar inte till disk. "
    "GG_TOOL_REQUEST= "
    '{"profile":"CURRENT_READ"} eller '
    '{"profile":"CURRENT_WRITE","text":"function hello(){return 1}"} eller '
    '{"profile":"TERMINAL_RUN","argv":["echo","hello","world"]} '
    "gäller också. "
    "Sök/test: "
    '{"profile":"SEARCH","literal":"TEXT"} '
    'eller {"profile":"TEST"} eller {"profile":"RUN"}. '
    "WRITE och GIT till repo förbjudna. Patch som GG_EDIT_PROPOSAL=. "
    "Ingen öppen shell. "
    "Inget modell-nät. Inget rm. Användaren sparar själv. "
    "När användaren ber om flera delar: svara på alla. "
    "Skriv aldrig blankrad följt av '> '."
)


class ResidentChatError(RuntimeError):
    pass


def classify_runtime_failure(stdout_text: str, stderr_text: str = "") -> str:
    blob = (stdout_text or "") + "\n" + (stderr_text or "")
    lower = blob.lower()
    compact = lower.replace(" ", "")
    if "erroroutofdevicememory" in compact:
        return "VULKAN_OUT_OF_DEVICE_MEMORY"
    if "vk::commandbuffer" in lower:
        return "VULKAN_COMMAND_BUFFER"
    if "decode() failed" in lower:
        return "MODEL_DECODE_FAILED"
    if "exceeds the available context size" in lower:
        return "CONTEXT_OVERFLOW"
    if "n_ctx" in compact and "exceed" in lower:
        return "CONTEXT_OVERFLOW"
    if "permission denied" in lower and "gguf" in lower:
        return "MODEL_FILE_PERMISSION_DENIED"
    return ""


def _emit(kind: str, **fields: object) -> None:
    payload: dict[str, object] = {
        "schema": EVENT_SCHEMA,
        "event": kind,
        **fields,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def _run_text(argv: list[str], timeout: float = 20.0) -> str:
    completed = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise ResidentChatError(
            "COMMAND_FAILED:"
            + repr(argv)
            + ":rc="
            + str(completed.returncode)
            + ":stderr="
            + completed.stderr[-2000:]
        )
    return completed.stdout


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


ALLOWED_PODMAN_IMAGE_PREFIXES = (
    "localhost/gg-site-php",
)
ALLOWED_PODMAN_NAME_PREFIXES = (
    "gg-resident-chat-",
)


def blocking_podman_containers(lines: list[str] | None = None) -> list[str]:
    if lines is None:
        output = _run_text(
            [PODMAN, "ps", "--format", "{{.Names}}\t{{.Image}}"]
        )
        lines = [line for line in output.splitlines() if line.strip()]
    blocked: list[str] = []
    for line in lines:
        name, _, image = line.partition("\t")
        name = name.strip()
        image = image.strip()
        if any(name.startswith(prefix) for prefix in ALLOWED_PODMAN_NAME_PREFIXES):
            continue
        if any(image.startswith(prefix) for prefix in ALLOWED_PODMAN_IMAGE_PREFIXES):
            continue
        blocked.append(name or image)
    return blocked


def _find_nvidia_render_node() -> Path:
    candidates: list[Path] = []
    for path in sorted(Path("/dev/dri").glob("renderD*")):
        if not stat.S_ISCHR(path.stat().st_mode):
            continue
        vendor = Path("/sys/class/drm") / path.name / "device/vendor"
        if not vendor.is_file():
            continue
        if vendor.read_text(encoding="ascii", errors="strict").strip().lower() == "0x10de":
            candidates.append(path)
    if len(candidates) != 1:
        raise ResidentChatError("NVIDIA_RENDER_NODE_CARDINALITY:" + repr(candidates))
    return candidates[0]


def transport_encode(prompt: str) -> bytes:
    if not isinstance(prompt, str) or not prompt:
        raise ResidentChatError("PROMPT_INVALID")
    line = json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))
    encoded = line.encode("utf-8")
    if b"\n" in encoded or b"\r" in encoded:
        raise ResidentChatError("PROMPT_TRANSPORT_NOT_SINGLE_LINE")
    if json.loads(encoded.decode("utf-8")) != prompt:
        raise ResidentChatError("PROMPT_TRANSPORT_ROUNDTRIP_FAILED")
    return encoded + b"\n"


class PromptFramer:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> tuple[list[bytes], bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while True:
            index = self._buffer.find(PROMPT_DELIMITER)
            if index < 0:
                break
            frames.append(bytes(self._buffer[:index]))
            del self._buffer[: index + len(PROMPT_DELIMITER)]
        return frames, bytes(self._buffer)

    def pop_streamable_prefix(self) -> bytes:
        holdback = len(PROMPT_DELIMITER) - 1
        if len(self._buffer) <= holdback:
            return b""
        count = len(self._buffer) - holdback
        data = bytes(self._buffer[:count])
        del self._buffer[:count]
        return data


def _runtime_root() -> Path:
    root = private_runtime_root()
    if root.is_symlink() or not root.is_dir():
        raise ResidentChatError("EVIDENCE_RUNTIME_INVALID:" + str(root))
    if not owned_by_current_user(root):
        raise ResidentChatError("EVIDENCE_RUNTIME_OWNER_INVALID:" + str(root))
    return root


class ResidentModelSession:
    def __init__(self) -> None:
        self.name = "gg-resident-chat-" + uuid.uuid4().hex[:12]
        self.evidence = _runtime_root() / (
            "gg-resident-chat." + time.strftime("%Y%m%dT%H%M%S") + "." + uuid.uuid4().hex
        )
        self.process: subprocess.Popen[bytes] | None = None
        self.selector = selectors.DefaultSelector()
        self.framer = PromptFramer()
        self.raw_stdout = bytearray()
        self.raw_stderr = bytearray()
        self.evidence_ready = False

    def _persist(self) -> None:
        if not self.evidence_ready or not self.evidence.is_dir():
            return
        (self.evidence / "resident.stdout").write_bytes(bytes(self.raw_stdout))
        (self.evidence / "resident.stderr").write_bytes(bytes(self.raw_stderr))

    def start(self) -> None:
        _emit("SESSION_STARTING", evidence=str(self.evidence))
        try:
            self.evidence.mkdir(mode=0o700, parents=False, exist_ok=False)
        except OSError as exc:
            raise ResidentChatError(
                "EVIDENCE_RUNTIME_UNWRITABLE:"
                + str(self.evidence)
                + ":"
                + type(exc).__name__
            ) from exc
        self.evidence_ready = True
        if not MODEL_PATH.is_file() or MODEL_PATH.is_symlink():
            raise ResidentChatError("MODEL_PATH_INVALID")
        if _sha256_path(MODEL_PATH) != MODEL_SHA256:
            raise ResidentChatError("MODEL_SHA256_DRIFT")

        image_id = _run_text(
            [PODMAN, "image", "inspect", "--format", "{{.Id}}", RUNTIME_IMAGE]
        ).strip()
        if image_id.startswith("sha256:"):
            image_id = image_id[7:]
        if image_id != RUNTIME_IMAGE_ID:
            raise ResidentChatError("RUNTIME_IMAGE_ID_DRIFT:" + image_id)

        digest = _run_text(
            [PODMAN, "image", "inspect", "--format", "{{.Digest}}", RUNTIME_IMAGE]
        ).strip()
        if digest != RUNTIME_IMAGE_DIGEST:
            raise ResidentChatError("RUNTIME_IMAGE_DIGEST_DRIFT:" + digest)
        blocked = blocking_podman_containers()
        if blocked:
            raise ResidentChatError(
                "PODMAN_NOT_EMPTY_BEFORE_RESIDENT_START:"
                + ",".join(blocked[:8])
            )

        render = _find_nvidia_render_node()
        argv = [
            PODMAN,
            "run",
            "--rm",
            "-i",
            "--name",
            self.name,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            "--user=1000:1000",
            "--userns=keep-id",
            "--device",
            f"{render}:{render}:rwm",
            "--pids-limit=256",
            "--memory=8g",
            "--memory-swap=8g",
            "--cpus=6",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=512m",
            "--env",
            "HOME=/tmp",
            "--env",
            "XDG_CACHE_HOME=/tmp/.cache",
            "--mount",
            f"type=bind,src={MODEL_DIR},target=/models,ro,relabel=private",
            RUNTIME_IMAGE,
            "--model",
            "/models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
            "--ctx-size",
            "2048",
            "--predict",
            "1024",
            "--temp",
            "0",
            "--seed",
            "42",
            "--gpu-layers",
            "33",
            "--conversation",
            "--simple-io",
            "--no-display-prompt",
            "--no-show-timings",
            "--color",
            "off",
            "--reasoning",
            "off",
            "--reasoning-budget",
            "0",
            "--no-reasoning-preserve",
            "--system-prompt",
            SYSTEM_PROMPT,
        ]
        (self.evidence / "argv.json").write_text(
            json.dumps(argv, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        if self.process.stdout is None or self.process.stderr is None:
            raise ResidentChatError("RESIDENT_PIPE_SETUP_FAILED")
        self.selector.register(self.process.stdout, selectors.EVENT_READ, data="stdout")
        self.selector.register(self.process.stderr, selectors.EVENT_READ, data="stderr")
        self._wait_for_initial_prompt()
        _emit("SESSION_READY", evidence=str(self.evidence))

    def _read_events(self, timeout: float) -> list[tuple[str, bytes]]:
        events: list[tuple[str, bytes]] = []
        for key, _mask in self.selector.select(timeout=timeout):
            data = os.read(key.fd, 4096)
            if not data:
                try:
                    self.selector.unregister(key.fileobj)
                except KeyError:
                    pass
                continue
            stream = str(key.data)
            if stream == "stdout":
                self.raw_stdout.extend(data)
            else:
                self.raw_stderr.extend(data)
            events.append((stream, data))
        return events

    def _wait_for_initial_prompt(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self.process is None:
                raise ResidentChatError("RESIDENT_PROCESS_MISSING")
            if self.process.poll() is not None:
                self._read_events(0.05)
                self._persist()
                stderr_tail = bytes(self.raw_stderr[-4000:]).decode(
                    "utf-8",
                    errors="replace",
                )
                stdout_tail = bytes(self.raw_stdout[-2000:]).decode(
                    "utf-8",
                    errors="replace",
                )
                failure = classify_runtime_failure(stdout_tail, stderr_tail)
                suffix = ":" + failure if failure else ""
                raise ResidentChatError(
                    "RESIDENT_EXITED_DURING_START:"
                    + str(self.process.returncode)
                    + suffix
                )
            for stream, data in self._read_events(0.05):
                if stream != "stdout":
                    continue
                frames, _remainder = self.framer.feed(data)
                if frames:
                    self._persist()
                    return
        raise ResidentChatError("RESIDENT_START_PROMPT_TIMEOUT")

    def turn(self, request_id: str, prompt: str) -> None:
        if self.process is None or self.process.stdin is None:
            raise ResidentChatError("RESIDENT_NOT_STARTED")
        if self.process.poll() is not None:
            raise ResidentChatError("RESIDENT_NOT_RUNNING")

        payload = transport_encode(prompt)
        written = self.process.stdin.write(payload)
        self.process.stdin.flush()
        if written != len(payload):
            raise ResidentChatError("RESIDENT_STDIN_SHORT_WRITE")

        _emit("TURN_START", request_id=request_id)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        sent_chars = 0
        deadline = time.monotonic() + TURN_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ResidentChatError(
                    "RESIDENT_EXITED_DURING_TURN:" + str(self.process.returncode)
                )
            for stream, data in self._read_events(0.05):
                if stream != "stdout":
                    continue
                frames, remainder = self.framer.feed(data)
                if len(remainder) > MAX_TURN_BYTES:
                    raise ResidentChatError("RESIDENT_TURN_OUTPUT_LIMIT")

                if frames:
                    frame = frames[0]
                    if len(frames) != 1:
                        raise ResidentChatError("RESIDENT_MULTIPLE_PROMPT_FRAMES")
                    text = decoder.decode(frame, final=True)
                    stderr_tail = bytes(self.raw_stderr[-4000:]).decode(
                        "utf-8",
                        errors="replace",
                    )
                    failure = classify_runtime_failure(text, stderr_tail)
                    if failure:
                        raise ResidentChatError(
                            "RESIDENT_RUNTIME_FAILURE:" + failure
                        )
                    if text:
                        _emit("DELTA", request_id=request_id, text=text)
                        sent_chars += len(text)
                    self._persist()
                    _emit(
                        "COMPLETE",
                        request_id=request_id,
                        chars=sent_chars,
                        evidence=str(self.evidence),
                    )
                    return

                emit_bytes = self.framer.pop_streamable_prefix()
                if emit_bytes:
                    text = decoder.decode(emit_bytes, final=False)
                    if text:
                        _emit("DELTA", request_id=request_id, text=text)
                        sent_chars += len(text)

        raise ResidentChatError("RESIDENT_TURN_TIMEOUT")

    def close(self) -> None:
        try:
            if self.process is not None and self.process.poll() is None:
                try:
                    if self.process.stdin is not None:
                        self.process.stdin.write(b"/exit\n")
                        self.process.stdin.flush()
                    self.process.wait(timeout=3.0)
                except Exception:
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=3.0)
                    except Exception:
                        self.process.kill()
                        self.process.wait(timeout=3.0)
        finally:
            try:
                self._persist()
            finally:
                self.selector.close()
                subprocess.run(
                    [PODMAN, "rm", "-f", self.name],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=20.0,
                )


def _term_handler(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def serve() -> int:
    signal.signal(signal.SIGTERM, _term_handler)
    signal.signal(signal.SIGINT, _term_handler)
    session: ResidentModelSession | None = None
    try:
        session = ResidentModelSession()
        session.start()
        for raw_line in sys.stdin:
            payload: object = None
            request_id = ""
            try:
                payload = json.loads(raw_line)
                request = contract.validate_request(payload)
                request_id = str(request["request_id"])
                session.turn(request_id, str(request["prompt"]))
            except Exception as exc:
                message = type(exc).__name__ + ":" + str(exc)
                retryable = (
                    "VULKAN_OUT_OF_DEVICE_MEMORY" in message
                    or "VULKAN_COMMAND_BUFFER" in message
                    or "MODEL_DECODE_FAILED" in message
                    or "CONTEXT_OVERFLOW" in message
                )
                if retryable and session is not None and request_id:
                    try:
                        session.close()
                    except Exception:
                        pass
                    session = ResidentModelSession()
                    session.start()
                    try:
                        session.turn(request_id, str(request["prompt"]))
                        continue
                    except Exception as retry_exc:
                        message = (
                            type(retry_exc).__name__ + ":" + str(retry_exc)
                        )
                _emit(
                    "ERROR",
                    request_id=request_id,
                    message=message,
                )
                return 70
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        _emit(
            "ERROR",
            request_id="",
            message=type(exc).__name__ + ":" + str(exc),
        )
        return 70
    finally:
        if session is not None:
            session.close()
    return 0


def main(argv: list[str]) -> int:
    if argv == []:
        print("SELFTEST=SAFE_NO_HOST_IO")
        return 0
    if argv != ["--serve"]:
        print("STOP_REASON=ARGUMENTS", file=sys.stderr)
        return 64
    return serve()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
