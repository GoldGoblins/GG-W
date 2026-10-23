from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

# Fixed prompt heap for resident Qwen (ctx-size 2048). Identity in,
# file bytes out-of-band via READ. Do not dump source into the KV.
PRIMARY_PROMPT_MAX_CHARS = 3600
LASER_STRATEGY = "LASER_IDENTITY"
USER_TURN_MARKER = "----- USER -----"
PROJECT = Path(__file__).resolve().parents[1]
REPO_SOURCE_PREFIX = "projects/gg-ai-desktop/"
TOOL_MARKER = "GG_TOOL_REQUEST="
EDIT_MARKER = "GG_EDIT_PROPOSAL="

_NAMED_SOURCE_RE = re.compile(
    r"\b((?:[\w.-]+/)*[\w.-]+\.(?:qml|py|json))\b",
    re.IGNORECASE,
)
_VERIFY_RE = re.compile(
    r"\b(verifiera|verify|testa|kontrollera att|fortfarande håller|still holds)\b",
    re.IGNORECASE,
)
_EDIT_RE = re.compile(
    r"\b(föreslå|propose|textändring|ändring i den öppna|"
    r"applicera den inte|do not apply)\b",
    re.IGNORECASE,
)
_SITE_EDIT_RE = re.compile(
    r"\b(ändra|byt ut|uppdatera|change|edit|replace)\b",
    re.IGNORECASE,
)
_WORK_RE = re.compile(
    r"\b("
    r"koda|kod|ändra|skriv|skapa|fixa|lägg till|ta bort|radera|"
    r"edit|patch|implement|snippet|filen|filerna|öppna fil|"
    r"propose|föreslå|textändring|kör|terminal|kodblock|diff|kommentar|"
    r"funktion|function"
    r")\b",
    re.IGNORECASE,
)
WORKER_DUTY_TALK = "CONVERSE_CURRENT_IS_BACKGROUND"
_SOURCE_LOOKUP_DIRS = (
    Path("."),
    Path("qml"),
    Path("qml/components"),
    Path("backend"),
    Path("tests"),
    Path("tests/controllers/live"),
    Path("config"),
)


class ChatContextCompileError(RuntimeError):
    pass


def estimate_prompt_tokens(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 2) // 3


def bound_read_path(source_path: str) -> str:
    rel = str(source_path).strip().lstrip("./")
    if not rel:
        return ""
    if rel.startswith(REPO_SOURCE_PREFIX):
        return rel
    return REPO_SOURCE_PREFIX + rel


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 32:
        return text[:limit]
    return text[: limit - 24] + "\n… [context clipped]"


def _bounded_omni_context(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 48:
        return text[:limit]
    suffix = "\n[… GG OmniGPT context clipped …]"
    return text[: limit - len(suffix)].rstrip() + suffix


def resolve_named_source(name: str) -> str | None:
    rel = name.strip().lstrip("./")
    if not rel:
        return None
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    direct = PROJECT / rel
    if direct.is_file():
        return REPO_SOURCE_PREFIX + direct.relative_to(PROJECT).as_posix()
    basename = Path(rel).name
    hits: list[str] = []
    root = PROJECT.resolve()
    for folder in _SOURCE_LOOKUP_DIRS:
        found = (PROJECT / folder / basename).resolve()
        try:
            found.relative_to(root)
        except ValueError:
            continue
        if found.is_file():
            hits.append(
                REPO_SOURCE_PREFIX + found.relative_to(root).as_posix()
            )
    unique = list(dict.fromkeys(hits))
    if len(unique) == 1:
        return unique[0]
    return None


def information_obligation(text: str, source_path: str) -> str:
    current_name = Path(str(source_path)).name.lower()
    named: list[str] = []
    for match in _NAMED_SOURCE_RE.finditer(text):
        raw = match.group(1)
        if Path(raw).name.lower() == current_name:
            continue
        if raw not in named:
            named.append(raw)
    if not named:
        return ""
    lines = [
        "INFORMATION_OBLIGATION=READ_NAMED_SOURCE_NOT_IN_CURRENT_CONTEXT",
    ]
    for name in named[:4]:
        resolved = resolve_named_source(name)
        if resolved is not None:
            lines.append(
                "Named source "
                + name
                + " is not the current workspace object. "
                "Your entire reply must be exactly this one line:\n"
                + TOOL_MARKER
                + '{"profile":"READ","path":"'
                + resolved
                + '"}'
            )
        else:
            lines.append(
                "Named source "
                + name
                + " is not the current workspace object. "
                "Emit exactly one "
                + TOOL_MARKER
                + '{"profile":"READ","path":"REPO_RELATIVE"} '
                "line. Do not answer from memory."
            )
    return "\n".join(lines) + "\n"


def verification_obligation(text: str) -> str:
    if not _VERIFY_RE.search(text):
        return ""
    return (
        "VERIFICATION_OBLIGATION=CONTROLLED_TEST_OR_RUN\n"
        "The user asked to verify. Workspace context is not verification "
        "evidence. Your entire reply must be exactly this one line:\n"
        + TOOL_MARKER
        + '{"profile":"TEST"}\n'
        "Do not answer from memory or from the open file.\n"
    )


def _edit_sample(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not (16 <= len(stripped) <= 96):
            continue
        if stripped.startswith(("//", "import")):
            continue
        if '"' in stripped or "\\" in stripped:
            continue
        if stripped.endswith(("(", ",", "{", "[", "\\")):
            continue
        if body.count(stripped) != 1:
            continue
        return stripped
    compact = " ".join(body.split())
    return compact[:80] if compact else "id: root"


def multi_part_obligation(text: str) -> str:
    parts = [part.strip() for part in str(text or "").split("\n\n") if part.strip()]
    if len(parts) < 2:
        return ""
    return (
        "MULTI_PART=ANSWER_EVERY_PART\n"
        "Svara på varje del. Använd ```bash bara för kommandot, "
        "```diff för patch (t.ex. +// hello), sen två meningar text. "
        "Lägg inte echo-output i code-fence. Du kör inte host-bash.\n"
    )


def work_intent(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _WORK_RE.search(value) or _EDIT_RE.search(value) or _VERIFY_RE.search(value):
        return True
    if _NAMED_SOURCE_RE.search(value):
        return True
    return False


def site_edit_obligation(text: str, body: str) -> str:
    if not _SITE_EDIT_RE.search(text) and not _EDIT_RE.search(text):
        return ""
    return edit_obligation(
        "Föreslå en exakt liten textändring i den öppna filen, "
        "men applicera den inte.",
        body,
    )


def edit_obligation(text: str, body: str) -> str:
    if not _EDIT_RE.search(text):
        return ""
    sample = _edit_sample(body)
    example = json.dumps(
        {"old_text": sample, "new_text": sample + " "},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "EDIT_OBLIGATION=PROPOSE_ONLY_NO_APPLY\n"
        "The user asked to propose an exact small text change in the open "
        "file. Do not apply it. Show the change as a markdown diff fence "
        "in the reply. You may also answer the rest of the user message. "
        "old_text must come from a READ of the bound "
        "path, or from the sample below. new_text must differ from old_text. The bytes "
        "after GG_EDIT_PROPOSAL= must be one valid JSON object. Do not "
        "backslash-escape the quotes that wrap old_text or new_text. Never "
        'write \\", or \\"} as a field terminator.\n'
        + EDIT_MARKER
        + example
        + "\n"
    )


def compile_chat_prompt(
    text: str,
    context_reference: str,
    context: Mapping[str, object],
    *,
    omni_context: str = "",
    max_chars: int = PRIMARY_PROMPT_MAX_CHARS,
) -> str:
    try:
        prompt_limit = int(max_chars)
    except (TypeError, ValueError) as exc:
        raise ChatContextCompileError("Prompt character bound is invalid.") from exc
    if prompt_limit < 512:
        raise ChatContextCompileError("Prompt character bound is too small.")
    if context_reference != "@current":
        raise ChatContextCompileError(
            "Real Workspace context currently requires @current."
        )
    if not text.strip():
        raise ChatContextCompileError("User message is empty.")

    body = str(context.get("body", ""))
    if not body:
        raise ChatContextCompileError("Workspace context body is empty.")

    source_path = str(context.get("source_path", ""))
    site_file = source_path.startswith("site:")
    bound_path = bound_read_path(source_path)
    if site_file:
        bound_path = source_path
    elif not bound_path:
        bound_path = "(identity-only)"

    wants_work = work_intent(text)
    obligation = ""
    if wants_work:
        obligation = (
            ("" if site_file else information_obligation(text, source_path))
            + verification_obligation(text)
            + (
                site_edit_obligation(text, body)
                if site_file
                else edit_obligation(text, body)
            )
            + multi_part_obligation(text)
        )
    if site_file and wants_work:
        laser_body = _bounded(body, 1200)
        laser_block = (
            "LASER_SITE_FILE · local SITE root · production/one.com requires "
            "the user's in-chat approval\n"
            f"bound_path={bound_path}\n"
            + laser_body
            + ("\n" if not laser_body.endswith("\n") else "")
        )
    else:
        laser_block = (
            "LASER_IDENTITY · body not in prompt · miss-closed on sha256 drift\n"
            f"bound_path={bound_path}\n"
            + (
                "fetch=READ bound path when bytes are required\n"
                if wants_work
                else "open surface is background until the user asks to code\n"
            )
        )
    stance = (
        "CHAT=UNIVERSAL. Vanligt prat först. Hälsa tillbaka på hälsning. "
        "Öppen yta är bakgrund tills användaren ber om kod eller ändring. "
        "Vagt språk är ok; gissa avsikten.\n"
        if not wants_work
        else "CHAT=UNIVERSAL. Användaren vill arbeta. @current är uppdraget.\n"
    )
    try:
        from backend.system_one_contract import decide_turn, format_compact

        system_one_block = format_compact(decide_turn(text)) + "\n"
    except Exception:
        system_one_block = ""
    profile_text = str(omni_context or "").strip()
    if "[GG SYSTEM ONE]" in profile_text:
        system_one_block = ""
    header_prefix = (
        stance
        + system_one_block
        + "Task mode: TASK_SCOPED throughout this chat/task. "
        + "If an operation needs approval, ask the user in this same chat "
        + "and accept only a simple ja/yes or nej/no; never ask the user "
        + "to copy hashes or slash approval commands. Internal bindings, "
        + "source hashes and approval records must never be shown to the user.\n"
        + "Citera inte olästa filer ur minnet.\n"
        + obligation
        + "Context selection: DEMAND_DRIVEN_PRIMARY_CURRENT\n"
        f"Context selection strategy: {LASER_STRATEGY}\n"
        f"Workspace context reference: {context_reference}\n"
        f"Workspace object id: {context['object_id']}\n"
        f"Workspace object title: {context['title']}\n"
        f"Workspace object type: {context['object_type']}\n"
        f"Workspace provenance: {context['provenance']}\n"
        f"Workspace source path: {context['source_path']}\n"
        f"Workspace content sha256: {context['sha256']}\n"
        f"Workspace content bytes: {context['bytes']}\n"
        "----- BEGIN SELECTED WORKSPACE CONTEXT -----\n"
        + laser_block
        + "----- END SELECTED WORKSPACE CONTEXT -----\n"
    )
    user = text if text.endswith("\n") else text + "\n"
    if profile_text:
        marker_length = len(USER_TURN_MARKER) + 4
        profile_budget = max(
            0,
            prompt_limit
            - len(header_prefix)
            - marker_length
            - min(len(user), 600),
        )
        if profile_budget:
            header_prefix += (
                "\n"
                + _bounded_omni_context(profile_text, profile_budget)
                + "\n"
            )

    header = header_prefix + "\n" + USER_TURN_MARKER + "\n"
    available = prompt_limit - len(header)
    if available < 64:
        raise ChatContextCompileError(
            "User message leaves no bounded room for laser Workspace identity."
        )
    if len(user) > available:
        user = _bounded(user, available)
        if not user.endswith("\n"):
            user += "\n"
    prompt = header + user
    if len(prompt) > prompt_limit:
        raise ChatContextCompileError("Compiled primary context exceeded its bound.")
    return prompt
