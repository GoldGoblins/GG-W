from __future__ import annotations

from backend.application_paths import DATA_HOME, STATE_HOME, STATE_ROOT, WORKSPACE_ROOT
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

ENGINE_LOCAL_QWEN = "LOCAL_QWEN"
ENGINE_GROK_WORKER = "GROK_WORKER"
ENGINE_GROK_TUI = "GROK_TUI"
ENGINE_GPT_TUI = "GPT_TUI"
ENGINE_FLOW_TUI = "FLOW_TUI"
ENGINE_TARGETS = (
    ENGINE_LOCAL_QWEN,
    ENGINE_GROK_WORKER,
    ENGINE_GROK_TUI,
    ENGINE_GPT_TUI,
    ENGINE_FLOW_TUI,
)
GROK_TUI_TERMINAL_ID = "ws.tui.grok"
GPT_TUI_TERMINAL_ID = "ws.tui.gpt"

SESSION_SCHEMA = "gg.workbench.grok-worker-session.v1"
SESSION_STATE_PATH = Path(
    str(STATE_ROOT / 'grok-worker-session.json')
)

def _desktop_grok_bin() -> Path:
    """The binary `grok update` replaces, then the old pinned copy."""
    override = os.environ.get("GG_GROK_BIN", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        from backend.platform_support import find_executable
        return Path(find_executable("grok") or (Path.home() / ".grok/bin/grok.exe"))
    candidates = (
        Path.home() / ".grok" / "bin" / "grok",
        Path(str(DATA_HOME / 'goldgoblins/tools/grok-build/1.0.5/grok')),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return candidates[0]


GROK_BIN = _desktop_grok_bin()
DEV_GROK_HOME = Path(
    os.environ.get(
        "GG_GROK_HOME",
        str(STATE_HOME / 'goldgoblins/grok-cloud-worker'),
    )
)
GROK_HOME = Path(
    os.environ.get(
        "GG_GROK_PRODUCT_HOME",
        str(STATE_ROOT / 'grok-home'),
    )
)
GROK_CWD = Path(
    os.environ.get("GG_WORKSPACE", str(WORKSPACE_ROOT))
)
MAX_WORKER_TURNS = 32
PRODUCT_GROK_CONFIG = (
    "[cli]\n"
    "auto_update = false\n"
    "\n"
    "[ui]\n"
    "permission_mode = \"always-approve\"\n"
    "remember_tool_approvals = true\n"
    "\n"
    "[features]\n"
    "telemetry = false\n"
    "feedback = false\n"
    "\n"
    "[memory]\n"
    "enabled = false\n"
)
DESKTOP_PROJECT = Path(__file__).resolve().parents[1]
REPO_SOURCE_PREFIX = "projects/gg-ai-desktop/"
WORKSPACE_TURN_SCHEMA = "gg.workbench.grok-workspace-turn.v1"
USER_TURN_MARKER = "----- USER -----"
WORKER_DUTY = "WORK_ON_BOUND_CURRENT"
WORKER_DUTY_TALK = "CONVERSE_CURRENT_IS_BACKGROUND"
WORKER_POLICY = "NO_FAKE_PROGRESS"
WORKSPACE_IDENTITY_MAX_BYTES = 16384
GROK_WORKSPACE_ALLOWLIST: dict[str, dict[str, str]] = {
    "ws.file.context-composer": {
        "title": "ContextComposer.qml",
        "object_type": "CODE_FILE",
        "provenance": "REAL_LOCAL_FILE",
        "relative_path": "qml/components/ContextComposer.qml",
    },
    "ws.file.grok-work-stream": {
        "title": "GrokWorkStream.qml",
        "object_type": "CODE_FILE",
        "provenance": "REAL_LOCAL_FILE",
        "relative_path": "qml/components/GrokWorkStream.qml",
    },
    "ws.file.chat-node": {
        "title": "ChatNode.qml",
        "object_type": "CODE_FILE",
        "provenance": "REAL_LOCAL_FILE",
        "relative_path": "qml/components/ChatNode.qml",
    },
    "ws.file.workspace-object-node": {
        "title": "WorkspaceObjectNode.qml",
        "object_type": "CODE_FILE",
        "provenance": "REAL_LOCAL_FILE",
        "relative_path": "qml/components/WorkspaceObjectNode.qml",
    },
    "ws.file.scratch.1": {
        "title": "untitled",
        "object_type": "CODE_FILE",
        "provenance": "REAL_UI_STATE",
        "relative_path": "",
    },
    "ws.terminal.user": {
        "title": "Terminal",
        "object_type": "USER_TERMINAL",
        "provenance": "REAL_UI_STATE",
        "relative_path": "",
    },
    "ws.app.external": {
        "title": "External app",
        "object_type": "EXTERNAL_APP",
        "provenance": "REAL_UI_STATE",
        "relative_path": "",
    },
    "ws.web.stub": {
        "title": "Web",
        "object_type": "WEBSITE",
        "provenance": "REAL_UI_STATE",
        "relative_path": "",
    },
    "ws.site.current": {
        "title": "Site",
        "object_type": "SITE_PROJECT",
        "provenance": "REAL_UI_STATE",
        "relative_path": "",
    },
}

# Extra top-tab instances share the same host kind as the seed object.
# They are not static allowlist entries; identity is still laser-only.
_SPAWNED_PREFIXES = (
    ("ws.terminal.user.", "USER_TERMINAL", "Terminal"),
    ("ws.app.external.", "EXTERNAL_APP", "External app"),
    ("ws.web.stub.", "WEBSITE", "Web"),
    ("ws.file.scratch.", "CODE_FILE", "untitled"),
    ("ws.site.current.", "SITE_PROJECT", "Site"),
)


def workspace_surface_spec(workspace_object_id: str) -> dict[str, str] | None:
    object_id = str(workspace_object_id or "").strip()
    spec = GROK_WORKSPACE_ALLOWLIST.get(object_id)
    if spec is not None:
        return spec
    for prefix, object_type, title in _SPAWNED_PREFIXES:
        if not object_id.startswith(prefix):
            continue
        rest = object_id[len(prefix) :]
        if not rest.isdigit() or int(rest) < 2:
            continue
        return {
            "title": title + " " + rest,
            "object_type": object_type,
            "provenance": "REAL_UI_STATE",
            "relative_path": "",
        }
    if object_id.startswith("ws.site.file."):
        rel = object_id[len("ws.site.file.") :]
        if rel and ".." not in rel.split("/"):
            return {
                "title": rel,
                "object_type": "CODE_FILE",
                "provenance": "REAL_UI_STATE",
                "relative_path": "",
            }
    return None

# Same deny list as the controlled TUI launcher. Not a generic shell.
DENY_RULES = (
    "Bash(sudo*)",
    "Bash(pkexec*)",
    "Bash(git push*)",
    "Bash(git commit*)",
    "Bash(git reset --hard*)",
    "Bash(git clean*)",
    "Bash(git restore*)",
    "Bash(git checkout --*)",
    "Bash(ssh *)",
    "Bash(scp *)",
    "Bash(sftp *)",
    "Bash(rsync *)",
    "Bash(curl *)",
    "Bash(wget *)",
    "Bash(nc *)",
    "Bash(ncat *)",
    "Bash(socat *)",
    "WebSearch",
    "WebFetch",
)

# Thought content is visible in the chat stream, in event order.
# Line limits are Unicode character counts, not UTF-8 byte counts.
THOUGHT_EVENT_TYPES = ("thought", "agent_thought_chunk")
TEXT_EVENT_TYPES = ("text", "agent_message_chunk")
END_EVENT_TYPES = ("end", "turn_completed")
MAX_EVENT_LINE_CHARS = 65536
MAX_STDOUT_BUFFER_CHARS = 262144
MAX_RESPONSE_CHARS = 200000
MAX_WORK_CARDS = 200
MAX_TOOL_TITLE_CHARS = 240
MAX_TOOL_FIELD_CHARS = 120
MAX_TERMINAL_BODY_CHARS = 4000
TERMINAL_TOOL_NAMES = (
    "run_terminal_cmd",
    "run_terminal_command",
    "bash",
)
MAX_SESSION_ID_CHARS = 36
OVERSIZED_TOOL_EVENT_TYPES = ("tool_call", "tool_call_update")


class GrokWorkerContractError(ValueError):
    pass


def normalize_engine_target(value: object) -> str:
    if value is None:
        return ENGINE_LOCAL_QWEN
    text = str(value).strip()
    if text == "":
        return ENGINE_LOCAL_QWEN
    if text in ENGINE_TARGETS:
        return text
    raise GrokWorkerContractError("ENGINE_TARGET_UNKNOWN:" + text)


def new_session_id() -> str:
    return str(uuid.uuid4())


def _unbound_identity(object_id: str) -> dict[str, str]:
    return {
        "object_id": object_id,
        "title": "",
        "object_type": "",
        "provenance": "UNBOUND",
        "source_path": "",
        "sha256": "",
        "bytes": "",
    }


def hash_workspace_identity(
    workspace_object_id: str,
    *,
    project: Path | None = None,
) -> dict[str, str]:
    object_id = str(workspace_object_id or "").strip()
    spec = workspace_surface_spec(object_id)
    if spec is None:
        return _unbound_identity(object_id)

    if object_id.startswith("ws.site.file."):
        from backend import web_surface

        site_rel = object_id[len("ws.site.file.") :]
        body = web_surface.read_site_file(site_rel)
        data = body.encode("utf-8") if body else b""
        return {
            "object_id": object_id,
            "title": spec["title"],
            "object_type": spec["object_type"],
            "provenance": spec["provenance"],
            "source_path": "site:" + site_rel,
            "sha256": hashlib.sha256(data).hexdigest() if data else "",
            "bytes": str(len(data)),
        }

    rel = str(spec.get("relative_path") or "").strip()
    if not rel:
        return {
            "object_id": object_id,
            "title": spec["title"],
            "object_type": spec["object_type"],
            "provenance": spec["provenance"],
            "source_path": "",
            "sha256": "",
            "bytes": "0",
        }

    relative = Path(rel)
    if relative.is_absolute() or ".." in relative.parts:
        raise GrokWorkerContractError("GROK_WORKSPACE_PATH_POLICY")

    root = (project or DESKTOP_PROJECT).resolve(strict=True)
    candidate = root / relative
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise GrokWorkerContractError("GROK_WORKSPACE_PATH_MISSING") from exc
    if not parent.is_relative_to(root):
        raise GrokWorkerContractError("GROK_WORKSPACE_PATH_ESCAPE")

    source_path = REPO_SOURCE_PREFIX + relative.as_posix()
    flags = os.O_RDONLY | NOFOLLOW
    try:
        fd = secure_open(candidate, flags)
    except OSError:
        return _unbound_identity(object_id)

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 1:
            return _unbound_identity(object_id)
        if info.st_size > WORKSPACE_IDENTITY_MAX_BYTES:
            return {
                "object_id": object_id,
                "title": spec["title"],
                "object_type": spec["object_type"],
                "provenance": spec["provenance"],
                "source_path": source_path,
                "sha256": "",
                "bytes": str(info.st_size),
            }
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(WORKSPACE_IDENTITY_MAX_BYTES + 1)
    finally:
        os.close(fd)

    if len(data) > WORKSPACE_IDENTITY_MAX_BYTES:
        return {
            "object_id": object_id,
            "title": spec["title"],
            "object_type": spec["object_type"],
            "provenance": spec["provenance"],
            "source_path": source_path,
            "sha256": "",
            "bytes": str(len(data)),
        }

    return {
        "object_id": object_id,
        "title": spec["title"],
        "object_type": spec["object_type"],
        "provenance": spec["provenance"],
        "source_path": source_path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": str(len(data)),
    }


def resolve_workspace_surface(workspace_object_id: str) -> dict[str, object]:
    spec = workspace_surface_spec(workspace_object_id)
    if spec is None:
        raise GrokWorkerContractError(
            "Selected Workspace object has no real local context source."
        )
    site_rel = ""
    if workspace_object_id == "ws.site.current":
        from backend import web_surface

        site_rel = web_surface.preferred_site_file() or "index.php"
    elif workspace_object_id.startswith("ws.site.file."):
        site_rel = workspace_object_id[len("ws.site.file.") :]
    if site_rel:
        from backend import web_surface

        body = web_surface.read_site_file(site_rel)
        if not body:
            kind = spec["object_type"]
            return {
                "object_id": workspace_object_id,
                "title": spec["title"],
                "object_type": kind,
                "provenance": spec["provenance"],
                "source_path": "site:" + site_rel,
                "sha256": "",
                "bytes": 0,
                "body": "LASER_IDENTITY · SITE · no file bytes",
            }
        data = body.encode("utf-8")
        return {
            "object_id": workspace_object_id,
            "title": spec["title"],
            "object_type": spec["object_type"],
            "provenance": spec["provenance"],
            "source_path": "site:" + site_rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "body": body,
        }
    rel = str(spec.get("relative_path") or "").strip()
    if not rel:
        kind = spec["object_type"]
        return {
            "object_id": workspace_object_id,
            "title": spec["title"],
            "object_type": kind,
            "provenance": spec["provenance"],
            "source_path": "",
            "sha256": "",
            "bytes": 0,
            "body": "LASER_IDENTITY · " + kind + " · no file bytes",
        }
    relative = Path(rel)
    if relative.is_absolute() or ".." in relative.parts:
        raise GrokWorkerContractError("Workspace context path policy violation.")
    root = DESKTOP_PROJECT.resolve(strict=True)
    candidate = DESKTOP_PROJECT / relative
    parent = candidate.parent.resolve(strict=True)
    if not parent.is_relative_to(root):
        raise GrokWorkerContractError("Workspace context escaped project root.")
    flags = os.O_RDONLY | NOFOLLOW
    try:
        fd = secure_open(candidate, flags)
    except OSError as exc:
        raise GrokWorkerContractError(
            "Workspace context source could not be opened safely: " + str(exc)
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise GrokWorkerContractError(
                "Workspace context source is not a regular file."
            )
        if info.st_size < 1:
            raise GrokWorkerContractError("Workspace context source is empty.")
        if info.st_size > WORKSPACE_IDENTITY_MAX_BYTES:
            raise GrokWorkerContractError(
                "Workspace context source exceeds the bootstrap byte limit."
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(WORKSPACE_IDENTITY_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > WORKSPACE_IDENTITY_MAX_BYTES:
        raise GrokWorkerContractError(
            "Workspace context source exceeded the bootstrap byte limit while reading."
        )
    try:
        body = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GrokWorkerContractError(
            "Workspace context source is not UTF-8."
        ) from exc
    return {
        "object_id": workspace_object_id,
        "title": spec["title"],
        "object_type": spec["object_type"],
        "provenance": spec["provenance"],
        "source_path": relative.as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "body": body,
    }


def compose_worker_prompt(
    user_text: str,
    *,
    context_reference: str = "@current",
    identity: dict[str, str] | None = None,
) -> str:
    text = user_text if isinstance(user_text, str) else str(user_text)
    if text.strip() == "":
        raise GrokWorkerContractError("GROK_PROMPT_EMPTY")
    ident = identity if isinstance(identity, dict) else {}
    digest = ident.get("sha256", "")
    if not (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    ):
        digest = ""
    bytes_text = ident.get("bytes", "")
    if bytes_text is None:
        bytes_text = ""
    else:
        bytes_text = str(bytes_text)
    reference = str(context_reference or "").strip() or "@current"
    user = text if text.endswith("\n") else text + "\n"
    from backend.chat_context_compiler import work_intent
    from backend.omni_gpt_profiles import build_context as build_omni_context

    duty = WORKER_DUTY if work_intent(text) else WORKER_DUTY_TALK
    object_id = str(ident.get("object_id", ""))
    untitled = (
        "scratch" in object_id
        or str(ident.get("title", "")).lower() in {"untitled", "scratch"}
    )
    buffer_rule = ""
    if untitled:
        buffer_rule = (
            "buffer=IN_MEMORY_UNTITLED. If the user asks for a function or "
            "code, write it as a markdown code fence or a +diff. The host "
            "copies that into the untitled buffer. The user saves as a "
            "filename they choose. Do not grep, glob, "
            "or read GoldGoblins QML/Python. Do not search SCRATCH_ROOT.\n"
        )
    try:
        omni_context = build_omni_context(text)
    except Exception:
        # A missing or malformed optional profile package must not take the
        # resident chat offline. AGENTS.md still supplies the shared rules.
        omni_context = (
            "[GG OMNIGPT PROFILE LAYER]\n"
            "Profile source unavailable; follow AGENTS.md and Idékompassen.\n"
            "[/GG OMNIGPT PROFILE LAYER]"
        )
    system_one_block = ""
    if "[GG SYSTEM ONE]" not in omni_context:
        try:
            from backend.system_one_contract import decide_turn, format_compact

            system_one_block = format_compact(decide_turn(text)) + "\n"
        except Exception:
            system_one_block = ""
    return (
        "GG_WORKSPACE schema="
        + WORKSPACE_TURN_SCHEMA
        + "\nreference="
        + _bounded_text(reference, MAX_TOOL_FIELD_CHARS)
        + "\nobject_id="
        + _bounded_text(ident.get("object_id", ""), MAX_TOOL_FIELD_CHARS)
        + "\ntitle="
        + _bounded_text(ident.get("title", ""), MAX_TOOL_TITLE_CHARS)
        + "\nobject_type="
        + _bounded_text(ident.get("object_type", ""), MAX_TOOL_FIELD_CHARS)
        + "\nprovenance="
        + _bounded_text(ident.get("provenance", ""), MAX_TOOL_FIELD_CHARS)
        + "\npath="
        + _bounded_text(ident.get("source_path", ""), MAX_TOOL_TITLE_CHARS)
        + "\nsha256="
        + digest
        + "\nbytes="
        + _bounded_text(bytes_text, MAX_TOOL_FIELD_CHARS)
        + "\nduty="
        + duty
        + "\npolicy="
        + WORKER_POLICY
        + "\n"
        + system_one_block
        + omni_context
        + "\nchat=UNIVERSAL. If the user greets, greet back. "
        "Bound current is background until they ask to code or change it.\n"
        + buffer_rule
        + "\n"
        + USER_TURN_MARKER
        + "\n"
        + user
    )


def split_worker_prompt(composed: str) -> tuple[str, str]:
    marker = USER_TURN_MARKER + "\n"
    at = composed.find(marker)
    if at < 0:
        raise GrokWorkerContractError("GROK_PROMPT_USER_MARKER_MISSING")
    return composed[:at], composed[at + len(marker) :]


def load_session_id(path: Path = SESSION_STATE_PATH) -> str:
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GrokWorkerContractError(
            "GROK_SESSION_STATE_INVALID:" + type(exc).__name__
        ) from exc
    if not isinstance(payload, dict):
        raise GrokWorkerContractError("GROK_SESSION_STATE_NOT_OBJECT")
    if payload.get("schema") != SESSION_SCHEMA:
        raise GrokWorkerContractError("GROK_SESSION_SCHEMA_MISMATCH")
    if payload.get("engine") != ENGINE_GROK_WORKER:
        raise GrokWorkerContractError("GROK_SESSION_ENGINE_MISMATCH")
    session_id = payload.get("session_id")
    bound = _valid_session_id(session_id)
    if not bound:
        raise GrokWorkerContractError("GROK_SESSION_ID_INVALID")
    stored_home = payload.get("grok_home")
    if stored_home != str(GROK_HOME):
        return ""
    return bound


def local_session_path(
    session_id: str,
    *,
    home: Path = GROK_HOME,
    cwd: Path = GROK_CWD,
) -> Path:
    bound = _valid_session_id(session_id)
    if not bound:
        raise GrokWorkerContractError("GROK_SESSION_ID_INVALID")
    encoded_cwd = quote(str(cwd), safe="")
    return home / "sessions" / encoded_cwd / bound


def session_exists_locally(
    session_id: str,
    *,
    home: Path = GROK_HOME,
    cwd: Path = GROK_CWD,
) -> bool:
    bound = _valid_session_id(session_id)
    if not bound:
        return False
    return local_session_path(bound, home=home, cwd=cwd).is_dir()


def dump_session_state(session_id: str, path: Path = SESSION_STATE_PATH) -> str:
    bound = _valid_session_id(session_id)
    if not bound:
        raise GrokWorkerContractError("GROK_SESSION_ID_INVALID")
    payload = {
        "schema": SESSION_SCHEMA,
        "engine": ENGINE_GROK_WORKER,
        "session_id": bound,
        "grok_home": str(GROK_HOME),
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(encoded + "\n", encoding="utf-8")
    return encoded


def ensure_product_grok_home(
    home: Path = GROK_HOME,
    auth_source: Path = DEV_GROK_HOME / "auth.json",
) -> Path:
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = home / "config.toml"
    encoded = PRODUCT_GROK_CONFIG
    if "mcp" in encoded.lower():
        raise GrokWorkerContractError("GROK_HOME_MCP_FORBIDDEN")
    current = ""
    if config_path.is_file():
        current = config_path.read_text(encoding="utf-8")
    if current != encoded:
        config_path.write_text(encoded, encoding="utf-8")
        os.chmod(config_path, 0o600)
    auth_dest = home / "auth.json"
    if auth_source.is_file() and not auth_dest.exists():
        try:
            os.link(auth_source, auth_dest)
        except OSError:
            data = auth_source.read_bytes()
            auth_dest.write_bytes(data)
            os.chmod(auth_dest, 0o600)
    return home


def build_grok_argv(
    prompt_path: Path,
    session_id: str,
    *,
    resume: bool,
    grok_bin: Path = GROK_BIN,
    cwd: Path = GROK_CWD,
) -> list[str]:
    if grok_bin.name == "bash" or grok_bin.name == "sh":
        raise GrokWorkerContractError("GENERIC_HOST_SHELL=NO")
    identity = _valid_session_id(session_id)
    if not identity:
        raise GrokWorkerContractError("GROK_SESSION_ID_INVALID")
    argv = [
        str(grok_bin),
        "--cwd",
        str(cwd),
        "--sandbox",
        "strict",
        "--always-approve",
        "--max-turns",
        str(MAX_WORKER_TURNS),
        "--output-format",
        "streaming-json",
        "--prompt-file",
        str(prompt_path),
        "--verbatim",
        "--no-auto-update",
    ]
    for rule in DENY_RULES:
        argv.extend(["--deny", rule])
    if resume:
        argv.extend(["--resume", identity])
    else:
        argv.extend(["--session-id", identity])
    if argv[0].endswith("/bash") or argv[0].endswith("/sh"):
        raise GrokWorkerContractError("GENERIC_HOST_SHELL=NO")
    if "-c" in argv:
        raise GrokWorkerContractError("GENERIC_HOST_SHELL=NO")
    return argv


def build_grok_tui_argv(
    *,
    grok_bin: Path = GROK_BIN,
    cwd: Path = GROK_CWD,
    full_screen_tui: bool = False,
    resume: str | None = None,
) -> list[str]:
    if grok_bin.name == "bash" or grok_bin.name == "sh":
        raise GrokWorkerContractError("GENERIC_HOST_SHELL=NO")
    argv = [
        str(grok_bin),
        "--cwd",
        str(cwd),
        "--sandbox",
        "off",
        "--no-auto-update",
    ]
    sid = str(resume or "").strip()
    if sid:
        argv.extend(["--resume", sid])
    if full_screen_tui:
        argv.append("--fullscreen")
    else:
        argv.extend(["--no-alt-screen", "--minimal"])
    for rule in DENY_RULES:
        argv.extend(["--deny", rule])
    if argv[0].endswith("/bash") or argv[0].endswith("/sh"):
        raise GrokWorkerContractError("GENERIC_HOST_SHELL=NO")
    if "-c" in argv:
        raise GrokWorkerContractError("GENERIC_HOST_SHELL=NO")
    return argv


def _bounded_text(value: object, limit: int) -> str:
    text = str(value) if value is not None else ""
    if len(text) > limit:
        return text[:limit]
    return text


def _event_text(event: dict[str, Any]) -> str:
    data = event.get("data")
    if isinstance(data, str) and data:
        return data
    content = event.get("content")
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    if isinstance(content, str):
        return content
    return ""


def _normalize_event_type(event_type: str) -> str:
    if event_type in THOUGHT_EVENT_TYPES:
        return "thought"
    if event_type in TEXT_EVENT_TYPES:
        return "text"
    if event_type in END_EVENT_TYPES:
        return "end"
    return event_type


def _raw_input(event: dict[str, Any]) -> dict[str, Any]:
    raw_in = event.get("rawInput")
    return raw_in if isinstance(raw_in, dict) else {}


def _tool_path(event: dict[str, Any]) -> str:
    raw_in = _raw_input(event)
    for key in ("target_file", "path"):
        value = raw_in.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    locations = event.get("locations")
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, dict):
            path = first.get("path")
            if isinstance(path, str) and path.strip():
                return path.strip()
    return ""


def _tool_pattern(event: dict[str, Any]) -> str:
    value = _raw_input(event).get("pattern")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _meta_tool_name(event: dict[str, Any]) -> str:
    meta = event.get("_meta")
    if not isinstance(meta, dict):
        return ""
    tool = meta.get("x.ai/tool")
    if not isinstance(tool, dict):
        return ""
    name = tool.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _tool_title(event: dict[str, Any]) -> str:
    raw = event.get("rawOutput")
    path = _tool_path(event)
    pattern = _tool_pattern(event)
    if isinstance(raw, dict):
        raw_type = str(raw.get("type") or "")
        if raw_type == "Bash":
            return "terminal"
        if raw_type in ("StrReplace", "ApplyPatch", "Edit", "search_replace"):
            return "code"
        if raw_type == "ReadFile":
            return _bounded_text(
                ("Read " + path).strip() if path else "Read",
                MAX_TOOL_TITLE_CHARS,
            )
        if raw_type == "Grep":
            return _bounded_text(
                ("grep " + pattern).strip() if pattern else "grep",
                MAX_TOOL_TITLE_CHARS,
            )
    kind = str(event.get("kind") or "").strip().lower()
    if kind in ("execute", "bash", "terminal"):
        return "terminal"
    if kind in ("edit", "write", "apply_patch"):
        return "code"
    if kind in ("read", "read_file"):
        return _bounded_text(
            ("Read " + path).strip() if path else "Read",
            MAX_TOOL_TITLE_CHARS,
        )
    if kind in ("search", "grep"):
        return _bounded_text(
            ("grep " + pattern).strip() if pattern else "grep",
            MAX_TOOL_TITLE_CHARS,
        )
    name = event.get("toolName")
    if not isinstance(name, str) or not name.strip():
        name = _meta_tool_name(event)
    if isinstance(name, str) and name.strip() in TERMINAL_TOOL_NAMES:
        return "terminal"
    title = event.get("title")
    if isinstance(title, str) and title.strip():
        lowered = title.strip().lower()
        if "run_terminal" in lowered or lowered.startswith("execute"):
            return "terminal"
        if lowered.startswith("edit") or "search_replace" in lowered:
            return "code"
        if lowered in ("read", "read_file") or lowered.startswith("read "):
            return _bounded_text(
                ("Read " + path).strip() if path else "Read",
                MAX_TOOL_TITLE_CHARS,
            )
        if lowered in ("grep", "search", "found") or lowered.startswith("grep "):
            return _bounded_text(
                ("grep " + pattern).strip() if pattern else title.strip(),
                MAX_TOOL_TITLE_CHARS,
            )
        if lowered != "tool":
            return _bounded_text(title.strip(), MAX_TOOL_TITLE_CHARS)
    if isinstance(name, str) and name.strip():
        if name.strip() in ("read_file", "Read"):
            return _bounded_text(
                ("Read " + path).strip() if path else "Read",
                MAX_TOOL_TITLE_CHARS,
            )
        if name.strip() in ("grep", "search"):
            return _bounded_text(
                ("grep " + pattern).strip() if pattern else "grep",
                MAX_TOOL_TITLE_CHARS,
            )
        return _bounded_text(name.strip(), MAX_TOOL_TITLE_CHARS)
    return "tool"


def _content_list_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    chunks: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        inner = item.get("content")
        if isinstance(inner, dict):
            text = inner.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
        elif isinstance(item.get("text"), str) and item["text"].strip():
            chunks.append(item["text"])
    return "\n".join(chunks)


def _tool_output(event: dict[str, Any]) -> str:
    for key in ("rawOutput", "content", "output"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return _bounded_text(value, MAX_TERMINAL_BODY_CHARS)
    raw = event.get("rawOutput")
    if isinstance(raw, dict):
        raw_type = str(raw.get("type") or "")
        if raw_type == "Bash":
            command = raw.get("command")
            prompt_out = raw.get("output_for_prompt")
            parts: list[str] = []
            if isinstance(command, str) and command.strip():
                parts.append("$ " + command.strip())
            if isinstance(prompt_out, str) and prompt_out.strip():
                parts.append(prompt_out)
            elif isinstance(raw.get("output"), list):
                try:
                    parts.append(
                        bytes(raw["output"]).decode("utf-8", errors="replace")
                    )
                except (TypeError, ValueError):
                    pass
            if parts:
                return _bounded_text("\n".join(parts), MAX_TERMINAL_BODY_CHARS)
        if raw_type in ("StrReplace", "ApplyPatch", "Edit", "search_replace"):
            listed = _content_list_text(event.get("content"))
            if listed:
                return _bounded_text(listed, MAX_TERMINAL_BODY_CHARS)
        if raw_type == "ReadFile":
            file_content = raw.get("FileContent")
            if isinstance(file_content, dict):
                body = file_content.get("content")
                if isinstance(body, str) and body.strip():
                    return _bounded_text(body, MAX_TERMINAL_BODY_CHARS)
            listed = _content_list_text(event.get("content"))
            if listed:
                return _bounded_text(listed, MAX_TERMINAL_BODY_CHARS)
            return ""
    listed = _content_list_text(event.get("content"))
    if listed:
        return _bounded_text(listed, MAX_TERMINAL_BODY_CHARS)
    return ""


def _tool_line(event: dict[str, Any], *, update: bool) -> str:
    prefix = "tool_call_update" if update else "tool_call"
    return (
        prefix
        + " id="
        + _bounded_text(event.get("toolCallId", ""), MAX_TOOL_FIELD_CHARS)
        + " name="
        + _bounded_text(event.get("toolName", ""), MAX_TOOL_FIELD_CHARS)
        + " kind="
        + _bounded_text(event.get("kind", ""), MAX_TOOL_FIELD_CHARS)
        + " status="
        + _bounded_text(event.get("status", ""), MAX_TOOL_FIELD_CHARS)
    )


def _project_tool_event(
    event: dict[str, Any],
    event_type: str,
    *,
    include_output: bool = True,
) -> dict[str, str]:
    card_id = _bounded_text(
        str(event.get("toolCallId", "")).strip() or "tool",
        MAX_TOOL_FIELD_CHARS,
    )
    header = _tool_line(event, update=(event_type == "tool_call_update"))
    output = _tool_output(event) if include_output else ""
    text = header if output == "" else header + "\n" + output
    return {
        "kind": event_type,
        "title": _tool_title(event),
        "text": text,
        "state": _tool_state(event),
        "session_id": extract_session_id(event),
        "card_id": card_id,
    }


def _tool_state(event: dict[str, Any]) -> str:
    status = str(event.get("status") or "").strip().lower()
    if status in ("completed", "complete", "success", "pass"):
        return "PASS"
    if status in ("failed", "error", "cancelled", "canceled", "blocked"):
        return "FAIL"
    return "RUNNING"


def _valid_session_id(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > MAX_SESSION_ID_CHARS:
        return ""
    if any(ch.isspace() for ch in text):
        return ""
    return text


def extract_session_id(event: dict[str, Any]) -> str:
    for key in ("sessionId", "session_id"):
        bound = _valid_session_id(event.get(key))
        if bound:
            return bound
    return ""


def reject_oversized_line(raw_line: str) -> None:
    if len(raw_line) > MAX_EVENT_LINE_CHARS:
        raise GrokWorkerContractError("GROK_EVENT_LINE_TOO_LARGE")


def reject_oversized_buffer(buffer: str) -> None:
    if len(buffer) > MAX_STDOUT_BUFFER_CHARS:
        raise GrokWorkerContractError("GROK_STDOUT_BUFFER_TOO_LARGE")


def reject_oversized_response(text: str) -> None:
    if len(text) > MAX_RESPONSE_CHARS:
        raise GrokWorkerContractError("GROK_RESPONSE_TOO_LARGE")


def reject_card_flood(count: int) -> None:
    if count > MAX_WORK_CARDS:
        raise GrokWorkerContractError("GROK_WORK_CARDS_TOO_MANY")


def project_worker_line(raw_line: str) -> dict[str, str] | None:
    if raw_line == "":
        return None
    line_chars = len(raw_line)
    if line_chars > MAX_STDOUT_BUFFER_CHARS:
        raise GrokWorkerContractError("GROK_EVENT_LINE_TOO_LARGE")
    oversized = line_chars > MAX_EVENT_LINE_CHARS
    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        if oversized:
            raise GrokWorkerContractError("GROK_EVENT_JSON_INVALID")
        return {
            "kind": "stdout",
            "title": "stdout",
            "text": raw_line,
            "state": "STREAMING",
            "card_id": "stdout",
        }
    if not isinstance(event, dict):
        raise GrokWorkerContractError("GROK_EVENT_NOT_OBJECT")
    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type:
        event_type = event.get("sessionUpdate")
    if not isinstance(event_type, str) or not event_type:
        raise GrokWorkerContractError("GROK_EVENT_TYPE_MISSING")
    if oversized:
        if event_type not in OVERSIZED_TOOL_EVENT_TYPES:
            raise GrokWorkerContractError("GROK_EVENT_LINE_TOO_LARGE")
        return _project_tool_event(event, event_type, include_output=False)
    kind = _normalize_event_type(event_type)
    if kind == "thought":
        return {
            "kind": "thought",
            "title": "Thought",
            "text": _bounded_text(_event_text(event), MAX_TERMINAL_BODY_CHARS),
            "state": "STREAMING",
            "session_id": extract_session_id(event),
            "card_id": "thought",
        }
    if kind == "text":
        data = _event_text(event)
        if event_type == "text" and not isinstance(event.get("data"), str):
            raise GrokWorkerContractError("GROK_TEXT_NOT_STRING")
        return {
            "kind": "text",
            "title": "",
            "text": data,
            "state": "STREAMING",
            "session_id": extract_session_id(event),
            "card_id": "text",
        }
    if event_type in OVERSIZED_TOOL_EVENT_TYPES:
        return _project_tool_event(event, event_type)
    if kind == "end":
        return {
            "kind": "end",
            "title": "end",
            "text": (
                "end stop="
                + str(event.get("stopReason", ""))
                + " session="
                + extract_session_id(event)
            ),
            "state": "PASS",
            "session_id": extract_session_id(event),
            "card_id": "end",
        }
    if event_type == "error":
        message = event.get("message")
        if not isinstance(message, str) or not message:
            message = "grok worker error"
        return {
            "kind": "error",
            "title": "error",
            "text": "error " + message,
            "state": "FAIL",
            "session_id": extract_session_id(event),
            "card_id": "error",
        }
    return {
        "kind": event_type,
        "title": event_type,
        "text": "event type=" + event_type,
        "state": "STREAMING",
        "session_id": extract_session_id(event),
        "card_id": event_type,
    }
