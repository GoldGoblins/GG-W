from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _context(body: str) -> dict[str, object]:
    return {
        "object_id": "ws.file.context-composer",
        "title": "ContextComposer.qml",
        "object_type": "QML_SOURCE",
        "provenance": "REAL_LOCAL_FILE",
        "source_path": "qml/components/ContextComposer.qml",
        "sha256": "a" * 64,
        "bytes": len(body.encode("utf-8")),
        "body": body,
    }


def main() -> int:
    from backend.chat_context_compiler import (
        LASER_STRATEGY,
        PRIMARY_PROMPT_MAX_CHARS,
        USER_TURN_MARKER,
        bound_read_path,
        compile_chat_prompt,
        estimate_prompt_tokens,
    )
    from backend.resident_chat_runner import SYSTEM_PROMPT

    small = "Rectangle {\n    id: root\n}\n"
    small_prompt = compile_chat_prompt(
        "Vad gör root?",
        "@current",
        _context(small),
    )
    assert "DEMAND_DRIVEN_PRIMARY_CURRENT" in small_prompt
    assert "Context selection strategy: " + LASER_STRATEGY in small_prompt
    assert "LASER_IDENTITY · body not in prompt" in small_prompt
    assert small not in small_prompt
    assert USER_TURN_MARKER in small_prompt
    assert "Vad gör root?" in small_prompt.split(USER_TURN_MARKER, 1)[1]
    assert "[GG SYSTEM ONE]" in small_prompt
    assert "authority=NONE" in small_prompt
    assert bound_read_path("qml/components/ContextComposer.qml") in small_prompt
    assert len(small_prompt) <= PRIMARY_PROMPT_MAX_CHARS
    assert estimate_prompt_tokens(SYSTEM_PROMPT + small_prompt) < 1800

    omni_prompt = compile_chat_prompt(
        "Jag har en lös idé och vill förstå den innan vi bygger.",
        "@current",
        _context(small),
        omni_context=(
            "[GG OMNIGPT PROFILE LAYER]\n"
            "default_lens=GG Idékompassen (always active)\n"
            "[PROFILE idekompassen]\n"
            "Bevara ursprungsavsikten och skilj gemensamma upptäckter från beslut.\n"
            "[/GG OMNIGPT PROFILE LAYER]"
        ),
        max_chars=4096,
    )
    assert "default_lens=GG Idékompassen (always active)" in omni_prompt
    assert "[PROFILE idekompassen]" in omni_prompt
    assert len(omni_prompt) <= 4096

    lines = [f"line {index}: ordinary value" for index in range(800)]
    lines[417] = "line 417: workspacePreflightButton triggers real preflight"
    large = "\n".join(lines)
    query = "Var används workspacePreflightButton?"
    first = compile_chat_prompt(query, "@current", _context(large))
    second = compile_chat_prompt(query, "@current", _context(large))

    assert first == second
    assert "Context selection strategy: " + LASER_STRATEGY in first
    assert "workspacePreflightButton triggers real preflight" not in first
    assert "line 0: ordinary value" not in first
    assert len(first) < len(large)
    assert len(first) <= PRIMARY_PROMPT_MAX_CHARS

    fallback = compile_chat_prompt("hej", "@current", _context(large))
    assert "Context selection strategy: " + LASER_STRATEGY in fallback
    assert len(fallback) <= PRIMARY_PROMPT_MAX_CHARS
    assert "INFORMATION_OBLIGATION=" not in fallback
    assert "hej" in fallback.split(USER_TURN_MARKER, 1)[1]

    cited = compile_chat_prompt(
        "Vad gör beginStreamingResponse i Main.qml? Citera relevant rad.",
        "@current",
        _context(small),
    )
    assert "INFORMATION_OBLIGATION=READ_NAMED_SOURCE_NOT_IN_CURRENT_CONTEXT" in cited
    assert (
        'GG_TOOL_REQUEST={"profile":"READ","path":"projects/gg-ai-desktop/qml/Main.qml"}'
        in cited
    )
    assert "Citera inte olästa filer ur minnet." in cited
    assert "VERIFICATION_OBLIGATION=" not in cited

    verified = compile_chat_prompt(
        "Kan du verifiera att safe-tool-kontraktet fortfarande håller?",
        "@current",
        _context(small),
    )
    assert "VERIFICATION_OBLIGATION=CONTROLLED_TEST_OR_RUN" in verified
    assert 'GG_TOOL_REQUEST={"profile":"TEST"}' in verified
    assert "Workspace context is not verification evidence." in verified
    assert "Your entire reply must be exactly this one line:" in verified
    assert "If you must verify" not in verified

    host_prompt = compile_chat_prompt(
        "Kan du kontrollera att kontraktet fortfarande håller?",
        "@current",
        _context(small),
    )
    assert "VERIFICATION_OBLIGATION=CONTROLLED_TEST_OR_RUN" in host_prompt
    assert 'GG_TOOL_REQUEST={"profile":"TEST"}' in host_prompt
    assert "Workspace context is not verification evidence." in host_prompt
    assert "EDIT_OBLIGATION=" not in host_prompt

    edited = compile_chat_prompt(
        "Föreslå en exakt liten textändring i den öppna filen, "
        "men applicera den inte.",
        "@current",
        _context(small),
    )
    assert "EDIT_OBLIGATION=PROPOSE_ONLY_NO_APPLY" in edited
    assert "GG_EDIT_PROPOSAL=" in edited
    assert "new_text must differ from old_text" in edited
    assert "backslash-escape the quotes that wrap" in edited
    assert r'\",' in edited or "field terminator" in edited
    assert "VERIFICATION_OBLIGATION=" not in edited
    example_line = [
        line
        for line in edited.splitlines()
        if line.startswith("GG_EDIT_PROPOSAL=")
    ][0]
    example = json.loads(example_line.split("=", 1)[1])
    assert example["old_text"]
    assert example["new_text"] != example["old_text"]

    qml = (PROJECT / "qml/components/ContextComposer.qml").read_text(
        encoding="utf-8"
    )
    qml_edited = compile_chat_prompt(
        "Föreslå en exakt liten textändring i den öppna filen, "
        "men applicera den inte.",
        "@current",
        _context(qml),
    )
    qml_line = [
        line
        for line in qml_edited.splitlines()
        if line.startswith("GG_EDIT_PROPOSAL=")
    ][0]
    qml_example = json.loads(qml_line.split("=", 1)[1])
    assert '"' not in qml_example["old_text"]
    assert "\\" not in qml_example["old_text"]
    assert qml.count(qml_example["old_text"]) == 1
    assert qml_example["new_text"] == qml_example["old_text"] + " "
    assert qml not in qml_edited
    assert "LASER_IDENTITY · body not in prompt" in qml_edited

    mega = ("å" * 8000) + "\nprint hello world\n"
    mega_prompt = compile_chat_prompt(mega, "@current", _context(small))
    assert len(mega_prompt) <= PRIMARY_PROMPT_MAX_CHARS
    assert "… [context clipped]" in mega_prompt
    assert estimate_prompt_tokens(SYSTEM_PROMPT + mega_prompt) < 1800

    site_ctx = {
        "object_id": "ws.site.file.snippets/header.html",
        "title": "snippets/header.html",
        "object_type": "CODE_FILE",
        "provenance": "REAL_UI_STATE",
        "source_path": "site:snippets/header.html",
        "sha256": "b" * 64,
        "bytes": 40,
        "body": "<header>Gold Goblins cookie banner</header>\n",
    }
    site_prompt = compile_chat_prompt(
        "ändra cookie-texten",
        "@current",
        site_ctx,
    )
    assert "LASER_SITE_FILE" in site_prompt
    assert "Gold Goblins cookie banner" in site_prompt
    assert "EDIT_OBLIGATION=PROPOSE_ONLY_NO_APPLY" in site_prompt
    parts = compile_chat_prompt(
        "Kör echo i terminalen.\n\nFöreslå // hello i den öppna filen.",
        "@current",
        site_ctx,
    )
    assert "MULTI_PART=ANSWER_EVERY_PART" in parts
    assert "```bash" in parts
    assert "```diff" in parts
    hello_site = compile_chat_prompt("hej", "@current", site_ctx)
    assert "EDIT_OBLIGATION=" not in hello_site
    assert "Gold Goblins cookie banner" not in hello_site
    assert "CHAT=UNIVERSAL" in hello_site
    assert "open surface is background" in hello_site

    print("CHAT_CONTEXT_COMPILER_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
