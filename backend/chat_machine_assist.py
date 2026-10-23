from __future__ import annotations

import re
import subprocess
from pathlib import Path

HOST_PROFILES = frozenset(
    {
        "CURRENT_READ",
        "CURRENT_WRITE",
        "TERMINAL_RUN",
    }
)
ALLOWED_BIN = {
    "echo": "/bin/echo",
    "true": "/bin/true",
    "false": "/bin/false",
    "pwd": "/bin/pwd",
    "date": "/bin/date",
    "ls": "/bin/ls",
}
_SHELL_LANGS = frozenset({"bash", "sh", "zsh", "shell", "terminal"})
_EDITOR_LANGS = frozenset(
    {
        "javascript",
        "js",
        "typescript",
        "ts",
        "qml",
        "python",
        "py",
        "json",
        "css",
        "html",
        "php",
        "c",
        "cpp",
        "h",
        "rs",
        "rust",
        "go",
        "java",
        "xml",
        "yaml",
        "yml",
        "sql",
        "lua",
        "vue",
        "diff",
    }
)
_NOISE_LABEL = re.compile(
    r"(?im)^\s*(Terminalruta|Resultat|Kodblock|Bara text|Output|Command)\s*:?\s*$"
)
_MAX_HOST_ACTIONS = 3
_UNSAFE = re.compile(r"[;|&<>`$(){}\\]|&&|\|\|")
_ECHO = re.compile(
    r"""\becho\s+(?:"([^"]*)"|'([^']*)'|((?:[A-Za-z0-9._-]+)(?:\s+[A-Za-z0-9._-]+)?))""",
    re.IGNORECASE,
)
_COMMENT = re.compile(
    r"(?:kommentar|comment|//)\s*(//\s*[^\n]+)",
    re.IGNORECASE,
)
_TERMINAL_ASK = re.compile(
    r"\b(terminal|echo|kör|run)\b",
    re.IGNORECASE,
)
_PATCH_ASK = re.compile(
    r"\b(kodblock|patch|diff|kommentar|comment|föreslå)\b",
    re.IGNORECASE,
)


def _safe_tokens(raw: str) -> list[str] | None:
    text = str(raw or "").strip()
    if not text or _UNSAFE.search(text):
        return None
    parts = text.split()
    if not parts or len(parts) > 8:
        return None
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", part):
            return None
    return parts


def user_turn_text(text: str) -> str:
    raw = str(text or "")
    marker = "----- USER -----"
    if marker in raw:
        raw = raw.split(marker, 1)[1]
    for stop in (
        "----- END",
        "----- GG",
        "----- BEGIN",
        "\nSYSTEM:",
    ):
        if stop in raw:
            raw = raw.split(stop, 1)[0]
    return raw.strip()


def validate_host_tool(payload: dict[str, object]) -> dict[str, object]:
    profile = str(payload.get("profile") or "")
    if profile == "CURRENT_READ":
        return {"profile": profile, "arguments": {}}
    if profile == "CURRENT_WRITE":
        text = payload.get("text")
        if not isinstance(text, str) or not (1 <= len(text) <= 32000):
            raise ValueError("CURRENT_WRITE_TEXT_INVALID")
        if "\x00" in text:
            raise ValueError("CURRENT_WRITE_FORBIDDEN")
        return {"profile": profile, "arguments": {"text": text}}
    if profile == "TERMINAL_RUN":
        argv = payload.get("argv")
        if not isinstance(argv, list) or not (1 <= len(argv) <= 8):
            raise ValueError("TERMINAL_RUN_ARGV_INVALID")
        tokens: list[str] = []
        for item in argv:
            if not isinstance(item, str) or not item:
                raise ValueError("TERMINAL_RUN_ARGV_INVALID")
            tokens.append(item)
        name = tokens[0]
        if name not in ALLOWED_BIN:
            raise ValueError("TERMINAL_RUN_BIN_NOT_ALLOWED:" + name)
        rest = _safe_tokens(" ".join(tokens[1:])) if len(tokens) > 1 else []
        if rest is None:
            raise ValueError("TERMINAL_RUN_ARGV_UNSAFE")
        return {
            "profile": profile,
            "arguments": {"argv": [ALLOWED_BIN[name], *rest]},
        }
    raise ValueError("HOST_PROFILE_UNKNOWN")


def execute_host_tool(
    parsed: dict[str, object],
    *,
    workspace: object | None,
) -> dict[str, str]:
    profile = str(parsed.get("profile") or "")
    arguments = parsed.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    if profile == "CURRENT_READ":
        if workspace is None:
            return {"profile": profile, "status": "FAIL", "output": "NO_WORKSPACE"}
        getter = getattr(workspace, "property", None)
        body = getter("editorText") if callable(getter) else ""
        text = "" if body is None else str(body)
        return {
            "profile": profile,
            "status": "PASS",
            "output": text if text else "(empty buffer)",
        }
    if profile == "CURRENT_WRITE":
        if workspace is None:
            return {"profile": profile, "status": "FAIL", "output": "NO_WORKSPACE"}
        text = str(arguments.get("text") or "")
        apply = getattr(workspace, "applyChatCodeToCurrent", None)
        if not callable(apply) or not bool(apply(text)):
            return {
                "profile": profile,
                "status": "FAIL",
                "output": "CURRENT_WRITE_NOT_APPLIED",
            }
        return {
            "profile": profile,
            "status": "PASS",
            "output": "buffer updated, unsaved, " + str(len(text)) + " chars",
        }
    if profile == "TERMINAL_RUN":
        argv = arguments.get("argv")
        if not isinstance(argv, list):
            return {"profile": profile, "status": "FAIL", "output": "NO_ARGV"}
        ran = run_allowed_argv([str(part) for part in argv])
        return {
            "profile": profile,
            "status": ran["status"],
            "output": ran["text"],
        }
    return {"profile": profile, "status": "FAIL", "output": "UNKNOWN"}


def parse_echo_argv(text: str) -> list[str] | None:
    text = user_turn_text(text)
    if not _TERMINAL_ASK.search(text):
        return None
    if re.search(r"[;|&<>`$\\]|&&|\|\|", text):
        return None
    match = _ECHO.search(text)
    if match is None:
        return None
    payload = match.group(1) or match.group(2) or match.group(3) or ""
    if _UNSAFE.search(payload):
        return None
    tokens = _safe_tokens(payload)
    if tokens is None:
        return None
    return [ALLOWED_BIN["echo"], *tokens]


def echo_shell_line(argv: list[str]) -> str:
    if not argv or argv[0] != ALLOWED_BIN["echo"]:
        return ""
    return "echo " + " ".join(argv[1:]) + "\n"


def run_allowed_argv(argv: list[str]) -> dict[str, str]:
    if not argv:
        return {"status": "FAIL", "text": "empty argv"}
    binary = Path(argv[0])
    if binary.as_posix() not in ALLOWED_BIN.values():
        return {"status": "FAIL", "text": "bin not allowed"}
    if not binary.is_file():
        return {"status": "FAIL", "text": "bin missing"}
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "FAIL", "text": type(exc).__name__}
    shown = " ".join(argv[1:]) if argv[0].endswith("echo") else binary.name
    body = (
        "$ "
        + ("echo " + shown if argv[0].endswith("echo") else binary.name)
        + "\n"
        + (proc.stdout or "")
        + ("exit: " + str(proc.returncode) + "\n")
    )
    return {"status": "PASS", "text": body.rstrip() + "\n"}


def _first_command_line(body: str) -> str:
    for line in str(body or "").splitlines():
        stripped = line.strip()
        if stripped:
            if stripped.startswith("$ "):
                return stripped[2:].strip()
            return stripped
    return ""


def parse_allowlisted_command(body: str) -> list[str] | None:
    line = _first_command_line(body)
    if not line or _UNSAFE.search(line):
        return None
    parts = line.split()
    if not parts or parts[0] not in ALLOWED_BIN:
        return None
    rest = _safe_tokens(" ".join(parts[1:])) if len(parts) > 1 else []
    if rest is None:
        return None
    return [parts[0], *rest]


def _diff_added_text(body: str) -> str:
    added: list[str] = []
    for line in str(body or "").splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
    return "\n".join(added).rstrip() + ("\n" if added else "")


def _looks_like_editor_source(body: str) -> bool:
    text = str(body or "").strip()
    if not text:
        return False
    if text.startswith("//") or text.startswith("/*") or text.startswith("+//"):
        return True
    return (
        "function " in text
        or text.startswith("def ")
        or "\ndef " in text
        or text.startswith("class ")
    )


def fence_to_host_action(lang: str, body: str) -> dict[str, object] | None:
    name = str(lang or "").strip().lower()
    text = str(body or "").strip("\n")
    if not text:
        return None
    argv = parse_allowlisted_command(text)
    if name in _SHELL_LANGS or (
        name in {"", "code"} and argv is not None
    ):
        if argv is None:
            return None
        return {"profile": "TERMINAL_RUN", "argv": argv}
    if name == "diff":
        added = _diff_added_text(text)
        if not added.strip():
            return None
        return {"profile": "CURRENT_WRITE", "text": added}
    if name in _EDITOR_LANGS or (
        name in {"", "code"} and _looks_like_editor_source(text)
    ):
        if argv is not None:
            return None
        return {"profile": "CURRENT_WRITE", "text": text if text.endswith("\n") else text + "\n"}
    return None


def _clean_harvested_visible(text: str) -> str:
    lines = [
        line
        for line in str(text or "").splitlines()
        if not _NOISE_LABEL.match(line)
    ]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def harvest_model_host_actions(
    text: str,
) -> tuple[str, list[dict[str, object]]]:
    rest = str(text or "")
    actions: list[dict[str, object]] = []
    pieces: list[str] = []
    while rest:
        start = rest.find("```")
        if start < 0:
            pieces.append(rest)
            break
        pieces.append(rest[:start])
        after = rest[start + 3 :]
        newline = after.find("\n")
        if newline < 0:
            pieces.append("```" + after)
            break
        lang = after[:newline].strip()
        tail = after[newline + 1 :]
        closer = tail.find("```")
        if closer < 0:
            pieces.append("```" + after)
            break
        body = tail[:closer].replace("\r\n", "\n").rstrip("\n")
        rest = tail[closer + 3 :]
        action = None
        if len(actions) < _MAX_HOST_ACTIONS:
            action = fence_to_host_action(lang, body)
        if action is not None:
            actions.append(action)
            continue
        if lang.strip() == "" or lang.strip().lower() in {"code", "text", "output"}:
            continue
        pieces.append("```" + lang + "\n" + body + "\n```")
    visible = _clean_harvested_visible("".join(pieces))
    return visible, actions


def extract_model_host_actions(
    text: str,
) -> tuple[str, list[dict[str, object]]]:
    from backend.controlled_information_tools import extract_tool_request

    visible, request = extract_tool_request(text)
    if request is not None:
        return visible, [request]
    return harvest_model_host_actions(text)


def propose_comment_diff(title: str, comment: str) -> str:
    name = str(title or "untitled").strip() or "untitled"
    line = str(comment or "// hello").strip()
    if not line.startswith("//"):
        line = "// " + line
    return (
        "--- a/"
        + name
        + "\n+++ b/"
        + name
        + "\n@@\n+"
        + line
        + "\n"
    )


def parse_comment_line(text: str) -> str | None:
    text = user_turn_text(text)
    if not _PATCH_ASK.search(text):
        return None
    if re.search(r"//\s*hello\b", text, re.IGNORECASE):
        return "// hello"
    match = _COMMENT.search(text)
    if match is not None:
        line = match.group(1).strip()
        return line.split(" i ")[0].split(" överst")[0].strip()
    return None


def plan_machine_work(
    user_text: str,
    *,
    title: str = "untitled",
) -> dict[str, object]:
    cards: list[dict[str, str]] = []
    terminal_line = ""
    argv = parse_echo_argv(user_text)
    if argv is not None:
        terminal_line = echo_shell_line(argv)
        ran = run_allowed_argv(argv)
        cards.append(
            {
                "kind": "stdout",
                "title": "terminal",
                "text": ran["text"],
                "state": ran["status"],
            }
        )
    comment = parse_comment_line(user_text)
    if comment is not None:
        cards.append(
            {
                "kind": "tool_call_update",
                "title": "diff",
                "text": propose_comment_diff(title, comment),
                "state": "PASS",
            }
        )
    spoken = user_turn_text(user_text)
    if cards or terminal_line:
        remainder = (
            spoken
            + "\n\nSYSTEM: Computer already ran allowlisted echo and showed "
            "the patch. Do not repeat terminal or diff. Continue any remaining "
            "user ask in ordinary language. No fences. No GG_TOOL_REQUEST.\n"
        )
    else:
        remainder = user_text
    return {
        "cards": cards,
        "terminal_line": terminal_line,
        "remainder": remainder,
    }
