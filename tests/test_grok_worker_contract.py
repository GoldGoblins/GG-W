#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.grok_worker_contract import (
        ENGINE_GROK_TUI,
        ENGINE_GROK_WORKER,
        ENGINE_LOCAL_QWEN,
        GROK_BIN,
        GROK_CWD,
        GROK_HOME,
        GROK_WORKSPACE_ALLOWLIST,
        MAX_WORKER_TURNS,
        PRODUCT_GROK_CONFIG,
        MAX_EVENT_LINE_CHARS,
        MAX_SESSION_ID_CHARS,
        MAX_STDOUT_BUFFER_CHARS,
        OVERSIZED_TOOL_EVENT_TYPES,
        REPO_SOURCE_PREFIX,
        SESSION_SCHEMA,
        USER_TURN_MARKER,
        WORKER_DUTY,
        WORKER_DUTY_TALK,
        WORKER_POLICY,
        WORKSPACE_TURN_SCHEMA,
        GrokWorkerContractError,
        build_grok_argv,
        build_grok_tui_argv,
        compose_worker_prompt,
        dump_session_state,
        ensure_product_grok_home,
        hash_workspace_identity,
        resolve_workspace_surface,
        load_session_id,
        normalize_engine_target,
        session_exists_locally,
        project_worker_line,
        reject_oversized_line,
        split_worker_prompt,
    )

    assert normalize_engine_target(None) == ENGINE_LOCAL_QWEN
    assert normalize_engine_target("") == ENGINE_LOCAL_QWEN
    assert normalize_engine_target("LOCAL_QWEN") == ENGINE_LOCAL_QWEN
    assert normalize_engine_target("GROK_WORKER") == ENGINE_GROK_WORKER
    assert normalize_engine_target("GROK_TUI") == ENGINE_GROK_TUI
    tui_argv = build_grok_tui_argv()
    assert tui_argv[0] == str(GROK_BIN)
    assert "--sandbox" in tui_argv
    assert tui_argv[tui_argv.index("--sandbox") + 1] == "off"
    assert "streaming-json" not in tui_argv
    assert "--prompt-file" not in tui_argv
    assert "--always-approve" not in tui_argv
    assert "--no-alt-screen" in tui_argv
    assert "--minimal" in tui_argv
    hole = build_grok_tui_argv(full_screen_tui=True)
    assert "--minimal" not in hole
    assert "--no-alt-screen" not in hole
    assert "--fullscreen" in hole
    resumed = build_grok_tui_argv(
        full_screen_tui=True,
        resume="01a02422-d4f1-7451-a650-b36c19b064a4",
    )
    assert "--resume" in resumed
    assert resumed[resumed.index("--resume") + 1] == (
        "01a02422-d4f1-7451-a650-b36c19b064a4"
    )
    try:
        normalize_engine_target("People")
        raise AssertionError("People accepted as engine target")
    except GrokWorkerContractError as exc:
        assert "ENGINE_TARGET_UNKNOWN" in str(exc)

    prompt = Path("/run/user/0/gg-grok-worker-prompt.test.txt")
    session = "11111111-1111-1111-1111-111111111111"
    created = build_grok_argv(prompt, session, resume=False)
    resumed = build_grok_argv(prompt, session, resume=True)
    assert created[0] == str(GROK_BIN)
    assert created[0].endswith("/grok")
    assert "-c" not in created
    assert "bash" not in created[0]
    assert "--sandbox" in created
    assert created[created.index("--sandbox") + 1] == "strict"
    assert "--always-approve" in created
    assert created[created.index("--max-turns") + 1] == str(MAX_WORKER_TURNS)
    assert MAX_WORKER_TURNS == 32
    assert "off" not in created
    assert str(GROK_HOME).endswith("/gg-ai-desktop/grok-home")
    assert "mcp" not in PRODUCT_GROK_CONFIG.lower()
    assert "--output-format" in created
    assert "streaming-json" in created
    assert "--prompt-file" in created
    assert "--verbatim" in created
    assert "--session-id" in created
    assert session in created
    assert "--resume" in resumed
    assert "--session-id" not in resumed
    assert "Bash(sudo*)" in created

    import hashlib as _hashlib

    spec = GROK_WORKSPACE_ALLOWLIST["ws.file.context-composer"]
    assert spec["relative_path"] == "qml/components/ContextComposer.qml"
    assert spec["provenance"] == "REAL_LOCAL_FILE"
    assert set(GROK_WORKSPACE_ALLOWLIST) == {
        "ws.file.context-composer",
        "ws.file.grok-work-stream",
        "ws.file.chat-node",
        "ws.file.workspace-object-node",
        "ws.file.scratch.1",
        "ws.terminal.user",
        "ws.app.external",
        "ws.web.stub",
        "ws.site.current",
    }
    stream_identity = hash_workspace_identity("ws.file.grok-work-stream")
    assert stream_identity["provenance"] == "REAL_LOCAL_FILE"
    assert stream_identity["title"] == "GrokWorkStream.qml"
    source = PROJECT / spec["relative_path"]
    source_bytes = source.read_bytes()
    identity = hash_workspace_identity("ws.file.context-composer")
    assert identity["object_id"] == "ws.file.context-composer"
    assert identity["provenance"] == "REAL_LOCAL_FILE"
    assert identity["source_path"] == REPO_SOURCE_PREFIX + spec["relative_path"]
    assert identity["sha256"] == _hashlib.sha256(source_bytes).hexdigest()
    assert identity["bytes"] == str(len(source_bytes))
    spawned = hash_workspace_identity("ws.terminal.user.2")
    assert spawned["object_id"] == "ws.terminal.user.2"
    assert spawned["object_type"] == "USER_TERMINAL"
    assert spawned["provenance"] == "REAL_UI_STATE"
    assert spawned["source_path"] == ""
    site_id = hash_workspace_identity("ws.site.file.index.php")
    assert site_id["source_path"] == "site:index.php"
    assert site_id["object_id"] == "ws.site.file.index.php"
    fake_web = resolve_workspace_surface("ws.web.stub.4")
    assert fake_web["object_type"] == "WEBSITE"
    assert fake_web["body"].startswith("LASER_IDENTITY")
    unbound = hash_workspace_identity("ws.website.goldgoblins")
    assert unbound["provenance"] == "UNBOUND"
    assert unbound["sha256"] == ""
    assert unbound["source_path"] == ""
    user = "Vad ligger i den öppna filen?"
    composed = compose_worker_prompt(
        user,
        context_reference="@current",
        identity=identity,
    )
    header, rest = split_worker_prompt(composed)
    assert rest == user + "\n"
    assert WORKSPACE_TURN_SCHEMA in header
    assert USER_TURN_MARKER in composed
    assert "duty=" + WORKER_DUTY in header
    talk = compose_worker_prompt(
        "hejsan",
        context_reference="@current",
        identity=identity,
    )
    scratch_prompt = compose_worker_prompt(
        "gör en enkel funktion i untitled",
        context_reference="@current",
        identity=hash_workspace_identity("ws.file.scratch.1"),
    )
    assert "IN_MEMORY_UNTITLED" in scratch_prompt
    assert "Do not grep" in scratch_prompt
    assert "untitled buffer" in scratch_prompt
    assert "duty=" + WORKER_DUTY_TALK in talk
    assert "duty=" + WORKER_DUTY not in talk.split("----- USER -----", 1)[0]
    assert "policy=" + WORKER_POLICY in header
    assert identity["sha256"] in header
    assert identity["source_path"] in header
    assert "pragma ComponentBehavior" not in header
    assert "----- BEGIN SELECTED WORKSPACE CONTEXT -----" not in composed
    try:
        compose_worker_prompt("   ")
        raise AssertionError("empty grok prompt accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_PROMPT_EMPTY" in str(exc)
    try:
        build_grok_argv(prompt, session, resume=False, grok_bin=Path("/bin/bash"))
        raise AssertionError("bash argv accepted")
    except GrokWorkerContractError as exc:
        assert "GENERIC_HOST_SHELL=NO" in str(exc)

    import os as _os

    runtime = Path(f"/run/user/{_os.getuid()}").resolve(strict=True)
    isolated = runtime / "gg-grok-home-contract"
    if isolated.exists():
        for child in isolated.iterdir():
            child.unlink()
        isolated.rmdir()
    prepared = ensure_product_grok_home(
        home=isolated,
        auth_source=runtime / "gg-grok-home-missing-auth.json",
    )
    assert prepared == isolated
    config_text = (isolated / "config.toml").read_text(encoding="utf-8")
    assert config_text == PRODUCT_GROK_CONFIG
    assert "mcp" not in config_text.lower()
    assert (isolated / "auth.json").exists() is False
    for child in isolated.iterdir():
        child.unlink()
    isolated.rmdir()

    thought = project_worker_line(
        json.dumps({"type": "thought", "data": "SECRET_PRIVATE_REASONING"})
    )
    assert thought is not None
    assert thought["kind"] == "thought"
    assert thought["title"] == "Thought"
    assert thought["text"] == "SECRET_PRIVATE_REASONING"
    assert "Thought ·" not in thought["title"]
    chunk = project_worker_line(
        json.dumps(
            {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": "Jag läser den öppna filen"},
            }
        )
    )
    assert chunk is not None
    assert chunk["kind"] == "thought"
    assert chunk["text"] == "Jag läser den öppna filen"
    speech = project_worker_line(
        json.dumps(
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Här är diffen."},
            }
        )
    )
    assert speech is not None
    assert speech["kind"] == "text"
    assert speech["text"] == "Här är diffen."

    text = project_worker_line(json.dumps({"type": "text", "data": "Hej från worker"}))
    assert text is not None
    assert text["kind"] == "text"
    assert text["text"] == "Hej från worker"

    tool = project_worker_line(
        json.dumps(
            {
                "type": "tool_call",
                "toolCallId": "call_1",
                "title": "Read",
                "toolName": "read_file",
                "kind": "read",
                "status": "in_progress",
            }
        )
    )
    assert tool is not None
    assert tool["kind"] == "tool_call"
    assert tool["title"] == "Read"
    assert tool["card_id"] == "call_1"
    terminal = project_worker_line(
        json.dumps(
            {
                "type": "tool_call_update",
                "toolCallId": "call_term",
                "title": "tool",
                "toolName": "run_terminal_cmd",
                "kind": "execute",
                "status": "completed",
                "rawOutput": "hello world\n",
            }
        )
    )
    assert terminal is not None
    assert terminal["title"] == "terminal"
    assert "hello world" in terminal["text"]
    assert "name=run_terminal_cmd" in terminal["text"]
    assert "status=completed" in terminal["text"]
    bash_done = project_worker_line(
        json.dumps(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_bash",
                "status": "completed",
                "rawOutput": {
                    "type": "Bash",
                    "command": "echo hello world",
                    "output_for_prompt": "exit: 0\nhello world\n",
                    "exit_code": 0,
                },
            }
        )
    )
    assert bash_done is not None
    assert bash_done["title"] == "terminal"
    assert "hello world" in bash_done["text"]
    assert "$ echo hello world" in bash_done["text"]
    read_done = project_worker_line(
        json.dumps(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_read",
                "status": "completed",
                "kind": "read",
                "rawInput": {
                    "variant": "ReadFile",
                    "target_file": "qml/components/ContextComposer.qml",
                },
                "rawOutput": {
                    "type": "ReadFile",
                    "FileContent": {"content": "Item {\n    id: root\n}\n"},
                },
            }
        )
    )
    assert read_done is not None
    assert read_done["title"] == "Read qml/components/ContextComposer.qml"
    assert "id: root" in read_done["text"]
    grep_done = project_worker_line(
        json.dumps(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_grep",
                "title": "found",
                "rawInput": {"pattern": "engineLabel", "glob": "*.qml"},
                "_meta": {"x.ai/tool": {"name": "grep", "kind": "search"}},
            }
        )
    )
    assert grep_done is not None
    assert grep_done["title"] == "grep engineLabel"
    assert tool["state"] == "RUNNING"
    assert "in_progress" in tool["text"]
    completed_small = project_worker_line(
        json.dumps(
            {
                "type": "tool_call_update",
                "toolCallId": "call_1",
                "title": "Read",
                "toolName": "read_file",
                "kind": "read",
                "status": "completed",
            }
        )
    )
    assert completed_small is not None
    assert completed_small["kind"] == "tool_call_update"
    assert completed_small["state"] == "PASS"
    assert "completed" in completed_small["text"]

    raw = project_worker_line("not-json stdout line")
    assert raw is not None
    assert raw["kind"] == "stdout"
    assert raw["text"] == "not-json stdout line"

    ended = project_worker_line(
        json.dumps({"type": "end", "stopReason": "end_turn", "sessionId": session})
    )
    assert ended is not None
    assert ended["kind"] == "end"
    assert ended["session_id"] == session

    failed = project_worker_line(
        json.dumps({"type": "error", "message": "worker missing"})
    )
    assert failed is not None
    assert failed["state"] == "FAIL"

    try:
        project_worker_line("[1, 2]")
        raise AssertionError("array event accepted")
    except GrokWorkerContractError:
        pass

    try:
        reject_oversized_line("x" * (MAX_EVENT_LINE_CHARS + 1))
        raise AssertionError("oversized line accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_LINE_TOO_LARGE" in str(exc)
    try:
        project_worker_line("y" * (MAX_EVENT_LINE_CHARS + 1))
        raise AssertionError("oversized non-json accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_JSON_INVALID" in str(exc)

    marker = "PAYLOAD_MARKER_DO_NOT_PROJECT"
    oversized_tool = json.dumps(
        {
            "type": "tool_call_update",
            "toolCallId": "call-76750a2d-2493-4ce0-80ae-812a65c8dc0a-0",
            "toolName": "read_file",
            "kind": "read",
            "status": "completed",
            "title": "Read",
            "rawOutput": marker + ("Q" * (MAX_EVENT_LINE_CHARS + 64)),
            "content": marker + ("C" * 1024),
        },
        ensure_ascii=False,
    )
    assert len(oversized_tool) > MAX_EVENT_LINE_CHARS
    assert len(oversized_tool) <= MAX_STDOUT_BUFFER_CHARS
    projected_tool = project_worker_line(oversized_tool)
    assert projected_tool is not None
    assert projected_tool["kind"] == "tool_call_update"
    assert projected_tool["card_id"] == "call-76750a2d-2493-4ce0-80ae-812a65c8dc0a-0"
    assert projected_tool["state"] == "PASS"
    assert "completed" in projected_tool["text"]
    assert marker not in json.dumps(projected_tool)
    assert "Q" * 64 not in projected_tool["text"]
    assert "Q" * 64 not in projected_tool["title"]
    follow = project_worker_line(
        json.dumps({"type": "text", "data": "Hej efter oversized tool"})
    )
    assert follow is not None
    assert follow["text"] == "Hej efter oversized tool"

    unknown = json.dumps(
        {"type": "text", "data": "U" * (MAX_EVENT_LINE_CHARS + 8)},
        ensure_ascii=False,
    )
    assert len(unknown) > MAX_EVENT_LINE_CHARS
    try:
        project_worker_line(unknown)
        raise AssertionError("oversized text accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_LINE_TOO_LARGE" in str(exc)

    malformed = (
        '{"type": "tool_call_update", "toolCallId": "call_bad", "raw": "'
        + ("M" * (MAX_EVENT_LINE_CHARS + 8))
    )
    assert len(malformed) > MAX_EVENT_LINE_CHARS
    try:
        project_worker_line(malformed)
        raise AssertionError("oversized malformed tool accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_JSON_INVALID" in str(exc)

    hard = (
        '{"type":"tool_call_update","toolCallId":"call_hard","raw":"'
        + ("H" * (MAX_STDOUT_BUFFER_CHARS + 8))
        + '"}'
    )
    assert len(hard) > MAX_STDOUT_BUFFER_CHARS
    try:
        project_worker_line(hard)
        raise AssertionError("hard buffer oversized tool accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_LINE_TOO_LARGE" in str(exc)

    multi = "ä" * MAX_EVENT_LINE_CHARS
    assert len(multi) == MAX_EVENT_LINE_CHARS
    assert len(multi.encode("utf-8")) > MAX_EVENT_LINE_CHARS
    multi_ok = project_worker_line(multi)
    assert multi_ok is not None
    assert multi_ok["kind"] == "stdout"
    try:
        project_worker_line("ä" * (MAX_EVENT_LINE_CHARS + 1))
        raise AssertionError("multibyte unknown oversized accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_JSON_INVALID" in str(exc)
    multi_tool = json.dumps(
        {
            "type": "tool_call",
            "toolCallId": "call_mb",
            "toolName": "read_file",
            "rawOutput": "ä" * (MAX_EVENT_LINE_CHARS + 32),
        },
        ensure_ascii=False,
    )
    assert len(multi_tool) > MAX_EVENT_LINE_CHARS
    assert len(multi_tool.encode("utf-8")) > len(multi_tool)
    projected_mb = project_worker_line(multi_tool)
    assert projected_mb is not None
    assert projected_mb["kind"] == "tool_call"
    assert "ä" not in projected_mb["text"]
    assert "ä" not in projected_mb["title"]
    assert OVERSIZED_TOOL_EVENT_TYPES == ("tool_call", "tool_call_update")
    assert MAX_SESSION_ID_CHARS == 36
    huge_sid = "S" * (MAX_SESSION_ID_CHARS + 8)
    oversized_sid = json.dumps(
        {
            "type": "tool_call_update",
            "toolCallId": "call_sid",
            "status": "completed",
            "sessionId": huge_sid,
            "rawOutput": "R" * (MAX_EVENT_LINE_CHARS + 8),
        },
        ensure_ascii=False,
    )
    assert len(oversized_sid) > MAX_EVENT_LINE_CHARS
    projected_sid = project_worker_line(oversized_sid)
    assert projected_sid is not None
    assert projected_sid.get("session_id", "") == ""
    assert huge_sid not in json.dumps(projected_sid)
    valid_sid = project_worker_line(
        json.dumps(
            {
                "type": "tool_call_update",
                "toolCallId": "call_sid_ok",
                "sessionId": session,
                "status": "completed",
            }
        )
    )
    assert valid_sid is not None
    assert valid_sid["session_id"] == session
    try:
        dump_session_state(
            huge_sid,
            PROJECT / "tests" / "__pycache__" / "grok-session-reject.json",
        )
        raise AssertionError("huge session dump accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_SESSION_ID_INVALID" in str(exc)
    try:
        build_grok_argv(prompt, huge_sid, resume=True)
        raise AssertionError("huge resume argv accepted")
    except GrokWorkerContractError as exc:
        assert "GROK_SESSION_ID_INVALID" in str(exc)

    spaced = (
        '{ "type" : "tool_call_update" , "toolCallId" : "call_ws" , '
        '"status" : "completed" , "rawOutput" : "'
        + ("W" * (MAX_EVENT_LINE_CHARS + 8))
        + '" }'
    )
    assert len(spaced) > MAX_EVENT_LINE_CHARS
    spaced_out = project_worker_line(spaced)
    assert spaced_out is not None
    assert spaced_out["kind"] == "tool_call_update"
    assert spaced_out["state"] == "PASS"
    assert "W" * 8 not in spaced_out["text"]

    fake = json.dumps(
        {
            "type": "text",
            "data": '"type":"tool_call_update"' + ("F" * (MAX_EVENT_LINE_CHARS + 8)),
        },
        ensure_ascii=False,
    )
    assert len(fake) > MAX_EVENT_LINE_CHARS
    assert "tool_call_update" in fake
    try:
        project_worker_line(fake)
        raise AssertionError("payload type token accepted as tool event")
    except GrokWorkerContractError as exc:
        assert "GROK_EVENT_LINE_TOO_LARGE" in str(exc)

    contract_src = (
        PROJECT / "backend" / "grok_worker_contract.py"
    ).read_text(encoding="utf-8")
    assert "_raw_line_has_allowlisted_tool_type" not in contract_src
    assert '"type":"' not in contract_src
    assert tool["state"] == "RUNNING"
    assert completed_small["state"] == projected_tool["state"] == "PASS"

    qt = (PROJECT / "backend" / "grok_worker_qt.py").read_text(encoding="utf-8")
    composer = (
        PROJECT / "qml" / "components" / "ContextComposer.qml"
    ).read_text(encoding="utf-8")
    main_qml = (PROJECT / "qml" / "Main.qml").read_text(encoding="utf-8")
    stream_qml = (
        PROJECT / "qml" / "components" / "GrokWorkStream.qml"
    ).read_text(encoding="utf-8")
    work_object_qml = (
        PROJECT / "qml" / "components" / "WorkObject.qml"
    ).read_text(encoding="utf-8")
    live_aid_object_qml = (
        PROJECT / "qml" / "components" / "LiveAidObject.qml"
    ).read_text(encoding="utf-8")
    resident = (PROJECT / "backend" / "resident_chat_qt.py").read_text(
        encoding="utf-8"
    )
    main_py = (PROJECT / "main.py").read_text(encoding="utf-8")

    contract_src = (
        PROJECT / "backend" / "grok_worker_contract.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "GENERIC_HOST_SHELL=NO",
        "agent_thought_chunk",
        "streaming-json",
        "thought",
        "--always-approve",
        '"strict"',
        "WORKER_DUTY = \"WORK_ON_BOUND_CURRENT\"",
        "WORKER_POLICY = \"NO_FAKE_PROGRESS\"",
        "ensure_product_grok_home",
        "GROK_HOME_MCP_FORBIDDEN",
        "gg-ai-desktop/grok-home",
        "--max-turns",
        "session_exists_locally",
        "grok_home",
        "TERMINAL_TOOL_NAMES",
        '"terminal"',
        "MAX_TERMINAL_BODY_CHARS",
    ):
        assert marker in contract_src, marker

    for marker in (
        "setProgram(argv[0])",
        "_queued_prompts",
        'kind == "thought"',
        'title = "Thought"',
        "_accumulate_narrative(",
        '_open_id = kind + "-"',
        "GROK_HOME",
        "beginGrokWorkerStream",
        "dump_session_state(session_id, SESSION_STATE_PATH)",
        "avslutades utan end-event",
        "EOF-remainder ogiltig",
        "reject_oversized_buffer",
        "compose_worker_prompt(",
        "hash_workspace_identity(",
        "ensure_product_grok_home()",
        "session_exists_locally(stored)",
    ):
        assert marker in qt, marker

    for marker in (
        'objectName: "engineTargetSelector"',
        '"LOCAL QWEN"',
        '"GROK WORKER"',
        "signal engineTargetRequested(string value)",
        "property string workspaceObjectTitle: \"\"",
        "People · close",
        "GG-AI-installator",
        "id: engineFooter",
        'text: "QWEN"',
        'text: "GROK"',
        'text: "GROK TUI"',
        'id: grokTuiEngineTarget',
        "anchors.bottom: engineFooter.top",
    ):
        assert marker in composer, marker

    for marker in (
        'property string engineTarget: "GROK_TUI"',
        "property string lastSelectedObjectId: \"\"",
        "if (objectId === root.lastSelectedObjectId)",
        "function beginGrokWorkerStream(",
        "function upsertGrokWorkerCard(",
        "function applyChatFenceToScratch(",
        "function diffAddedSource(",
        "function chatFenceLooksLikeShell(",
        "function chatFenceIsEditorCode(",
        "kind === \"code\"",
        'name === "javascript"',
        "first === \"echo\"",
        "previousTitle !== \"tool\"",
        'nodeKind === "GROK_STREAM"',
        'kind === "STREAM"',
        '"nodeKind": "STREAM"',
        "GrokWorkStream {",
        'root.engineTarget === "GROK_WORKER"',
        'id: grokTuiHost',
        'objectName: "grokTuiHost"',
        "GrokTuiHole {",
        "chatBusy: root.bridgeBusy",
        "workspaceObjectTitle: workspace.currentObjectTitle",
        'rightLegend: "BRIDGE · CONNECTED"',
        "id: chatCodeblock",
        "id: codeblockFlick",
        "function activeWorkLabel(",
        'headline: root.activeWorkLabel()',
        '"Thinking"',
        '"Waiting for response"',
        "function stickChatToLatest(",
        "id: chatStatusDock",
        "onContentHeightChanged:",
        "followChatTail",
    ):
        assert marker in main_qml, marker

    activity_qml = (
        PROJECT / "qml" / "components" / "ActivityStrip.qml"
    ).read_text(encoding="utf-8")
    for marker in (
        "function formatElapsed(",
        "function formatSegment(",
        'text: ":: " + root.statusText',
        "interval: 100",
        "hundredths",
        "SequentialAnimation",
    ):
        if marker == "SequentialAnimation":
            assert marker not in activity_qml, marker
            continue
        assert marker in activity_qml, marker

    for marker in (
        "readonly property int workLogMaxHeight: 168",
        "function joinedBoxedText(",
        "function cardsOfNarrative(",
        "function tuiWorkLine(",
        '!== "tool"',
        "function typeShift(",
        "function isTerminalCard(",
        "function isShellLang(",
        "function fenceCard(",
        "function looksLikeDiff(",
        "function looksLikeShellCommand(",
        "function isCodeCard(",
        "function fencesFromText(",
        "function fencesFromCard(",
        "function textWithoutFences(",
        "model: root.cards",
        'objectType: "TERMINAL"',
        'objectType: "CODE"',
        "id: workLogFlick",
        "Flickable {",
        "GgFrame {",
    ):
        assert marker in stream_qml, marker

    for marker in (
        "readonly property int bodyMaxHeight:",
        "property bool fillHost: false",
        "id: bodyFlick",
        '"terminalOutputScroll"',
        '"terminalOutput"',
        '"terminalCommandInput"',
        '"terminalInputRow"',
        "Flickable {",
        "function sendTerminalLine()",
        "startChatTerminal",
        'objectType === "TERMINAL"',
    ):
        assert marker in work_object_qml, marker

    for marker in (
        "readonly property int bodyMaxHeight: 98",
        "id: diagnosticsFlick",
        "Flickable {",
    ):
        assert marker in live_aid_object_qml, marker

    for marker in (
        "ENGINE_GROK_WORKER",
        "accept_followup(",
        "self._grok_worker().submit(",
        "normalize_engine_target(",
    ):
        assert marker in resident, marker

    assert "ResidentChatTransport(" in main_py
    assert "self._resident_chat.submit(" in main_py
    assert "accept_followup(" in main_py
    assert "normalize_engine_target(self._root.property(\"engineTarget\"))" in main_py
    assert (
        "if engine_target == ENGINE_GROK_WORKER or engine_target == ENGINE_GROK_TUI:"
        in main_py
    )
    assert "def _submit_resident_prompt(" in main_py
    submit_src = main_py[main_py.index("def submit("):]
    assert submit_src.index("control_contract.parse_control_command(value)") < submit_src.index("if self._active():")
    assert submit_src.index("if self._active():") < submit_src.index("normalize_engine_target(self._root.property(\"engineTarget\"))")
    grok_branch = (
        "if engine_target == ENGINE_GROK_WORKER or engine_target == ENGINE_GROK_TUI:"
    )
    assert submit_src.index(grok_branch) < submit_src.index("parse_selfdev_command(value)")
    assert submit_src.index(grok_branch) < submit_src.index("parse_natural_safe_tool_command(")
    assert 'self._submit_resident_prompt(value, context_reference, workspace_object_id, {})' in submit_src
    assert 'WORKSPACE_CONTEXTS' in main_py
    assert "GROK_WORKSPACE_ALLOWLIST as WORKSPACE_CONTEXTS" in main_py
    assert spec["relative_path"] in (
        PROJECT / "backend" / "grok_worker_contract.py"
    ).read_text(encoding="utf-8")
    workspace_surface = (
        PROJECT / "qml" / "components" / "WorkspaceSurface.qml"
    ).read_text(encoding="utf-8")
    assert "root.currentObjectId === item.objectId" in workspace_surface
    assert "root.activeObjectChanged(item.objectId, item.title)" in workspace_surface
    assert "if (root.chatBusy)" in workspace_surface
    assert 'property bool chatBusy: false' in workspace_surface
    assert "function applyChatCodeToCurrent(" in workspace_surface
    assert "function saveScratchAs(" in workspace_surface
    assert len(main_py.encode("utf-8")) <= 327680

    scratch = PROJECT / "tests" / "__pycache__" / "grok-session-test.json"
    scratch.parent.mkdir(exist_ok=True)
    dump_session_state(session, scratch)
    assert load_session_id(scratch) == session
    payload = json.loads(scratch.read_text(encoding="utf-8"))
    assert payload["schema"] == SESSION_SCHEMA
    assert payload["engine"] == ENGINE_GROK_WORKER
    assert payload["grok_home"] == str(GROK_HOME)
    stale = {
        "schema": SESSION_SCHEMA,
        "engine": ENGINE_GROK_WORKER,
        "session_id": session,
    }
    scratch.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    assert load_session_id(scratch) == ""
    isolated_sessions = runtime / "gg-grok-home-sessions"
    encoded_cwd = quote(str(GROK_CWD), safe="")
    present = isolated_sessions / "sessions" / encoded_cwd / session
    present.mkdir(parents=True)
    assert session_exists_locally(session, home=isolated_sessions) is True
    assert session_exists_locally(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        home=isolated_sessions,
    ) is False
    for child in reversed(list(isolated_sessions.rglob("*"))):
        if child.is_file() or child.is_symlink():
            child.unlink()
        else:
            child.rmdir()
    isolated_sessions.rmdir()
    scratch.unlink()

    print("GROK_WORKER_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
