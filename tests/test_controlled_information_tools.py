from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def main() -> int:
    from backend.controlled_information_tools import (
        extract_edit_proposal,
        extract_tool_request,
        InformationToolError,
        validate_information_tool_request,
    )
    from backend import safe_tool_contract as tool_contract

    visible, request = extract_tool_request(
        "GG_TOOL_REQUEST="
        + '{"profile":"READ","path":"projects/gg-ai-desktop/main.py"}'
    )
    require(visible == "", "tool-only turn left visible residue")
    require(
        request
        == {
            "profile": tool_contract.PROFILE_READ,
            "arguments": {"path": "projects/gg-ai-desktop/main.py"},
        },
        "READ request parse failed",
    )

    visible, request = extract_tool_request(
        "Kort svar.\n"
        "GG_TOOL_REQUEST="
        + '{"profile":"SEARCH","literal":"parse_safe_tool"}'
    )
    require(visible == "Kort svar.", "visible text strip failed")
    require(request["profile"] == tool_contract.PROFILE_SEARCH, "SEARCH parse failed")

    visible, request = extract_tool_request("Hej, hur mår du?")
    require(visible == "Hej, hur mår du?", "plain answer mutated")
    require(request is None, "plain answer became a tool")

    visible, request = extract_tool_request(
        "`GG_TOOL_REQUEST = "
        + '{"profile":"READ","path":"projects/gg-ai-desktop/qml/Main.qml"}`'
    )
    require(visible == "", "spaced marker left visible residue")
    require(
        request
        == {
            "profile": tool_contract.PROFILE_READ,
            "arguments": {"path": "projects/gg-ai-desktop/qml/Main.qml"},
        },
        "spaced/fenced READ request parse failed",
    )

    try:
        extract_tool_request(
            "GG_TOOL_REQUEST="
            + '{"profile":"READ","path":"projects/gg-ai-desktop/main.py"}\n'
            "GG_TOOL_REQUEST="
            + '{"profile":"SEARCH","literal":"beginStreamingResponse"}'
        )
        raise RuntimeError("ambiguous tool requests were accepted")
    except InformationToolError as exc:
        require("TOOL_REQUEST_AMBIGUOUS" in str(exc), str(exc))

    try:
        validate_information_tool_request(
            {"profile": "READ", "path": "projects/gg-ai-desktop/RELATIV"}
        )
        raise RuntimeError("template READ path was accepted")
    except InformationToolError as exc:
        require("READ_PATH_TEMPLATE" in str(exc), str(exc))

    try:
        validate_information_tool_request(
            {"profile": "WRITE", "path": "main.py"}
        )
        raise RuntimeError("WRITE was accepted")
    except InformationToolError as exc:
        require("TOOL_PROFILE_NOT_ALLOWED" in str(exc), str(exc))

    visible, request = extract_tool_request(
        'GG_TOOL_REQUEST={"profile":"CURRENT_READ"}'
    )
    require(request["profile"] == "CURRENT_READ", "CURRENT_READ parse failed")
    visible, request = extract_tool_request(
        'GG_TOOL_REQUEST={"profile":"TERMINAL_RUN","argv":["echo","hello","world"]}'
    )
    require(request["profile"] == "TERMINAL_RUN", "TERMINAL_RUN parse failed")
    require(
        request["arguments"]["argv"][0].endswith("echo"),
        "TERMINAL_RUN argv not resolved to host echo",
    )
    try:
        validate_information_tool_request(
            {"profile": "TERMINAL_RUN", "argv": ["rm", "-rf", "/"]}
        )
        raise RuntimeError("rm was accepted")
    except InformationToolError as exc:
        require("TERMINAL_RUN_BIN_NOT_ALLOWED" in str(exc), str(exc))
    visible, request = extract_tool_request(
        'GG_TOOL_REQUEST={"profile":"TEST"}'
    )
    require(visible == "", "TEST tool-only turn left residue")
    require(
        request == {"profile": tool_contract.PROFILE_TEST, "arguments": {}},
        "TEST request parse failed",
    )
    visible, request = extract_tool_request(
        'GG_TOOL_REQUEST={"profile":"RUN"}'
    )
    require(
        request == {"profile": tool_contract.PROFILE_RUN, "arguments": {}},
        "RUN request parse failed",
    )
    try:
        validate_information_tool_request(
            {"profile": "GIT", "operation": "status"}
        )
        raise RuntimeError("GIT was accepted")
    except InformationToolError as exc:
        require("TOOL_PROFILE_NOT_ALLOWED" in str(exc), str(exc))

    try:
        validate_information_tool_request(
            {"profile": "READ", "path": "../secret"}
        )
        raise RuntimeError("traversal was accepted")
    except InformationToolError as exc:
        require("READ_PATH_POLICY" in str(exc), str(exc))

    visible, proposal = extract_edit_proposal(
        'GG_EDIT_PROPOSAL={"old_text":"alpha","new_text":"beta"}'
    )
    require(visible == "", "edit proposal left residue")
    require(
        proposal == {"old_text": "alpha", "new_text": "beta"},
        "edit proposal parse failed",
    )
    visible, proposal = extract_edit_proposal(
        r'GG_EDIT_PROPOSAL={"old_text":"has \"inner\" quotes","new_text":"other"}'
    )
    require(
        proposal == {"old_text": 'has "inner" quotes', "new_text": "other"},
        "valid escaped quotes were not preserved",
    )
    visible, proposal = extract_edit_proposal(
        r'GG_EDIT_PROPOSAL={"old_text":"foo \", bar","new_text":"baz"}'
    )
    require(
        proposal == {"old_text": 'foo ", bar', "new_text": "baz"},
        "valid \\\", inside a string was rewritten",
    )
    try:
        extract_edit_proposal(
            r'GG_EDIT_PROPOSAL={"old_text":"signal submitRequested(\","new_text":"signal submitRequested( "}'
        )
        raise RuntimeError("malformed wrapping-quote escape was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_JSON_INVALID" in str(exc), str(exc))
    try:
        extract_edit_proposal(
            'GG_EDIT_PROPOSAL={"old_text":"alpha","new_text":"beta"} extra'
        )
        raise RuntimeError("trailing text after JSON was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_JSON_INVALID" in str(exc), str(exc))
    try:
        extract_edit_proposal(
            'GG_EDIT_PROPOSAL=nope{"old_text":"alpha","new_text":"beta"}'
        )
        raise RuntimeError("prefix garbage was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_JSON_INVALID" in str(exc), str(exc))
    try:
        extract_edit_proposal(
            'GG_EDIT_PROPOSAL={"old_text":"a","new_text":"b"}'
            '{"old_text":"c","new_text":"d"}'
        )
        raise RuntimeError("second JSON object was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_JSON_INVALID" in str(exc), str(exc))
    try:
        extract_edit_proposal(
            'GG_EDIT_PROPOSAL={"old_text":{"x":1},"new_text":"b"}'
        )
        raise RuntimeError("nested old_text object was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_OLD_MISSING" in str(exc), str(exc))
    visible, proposal = extract_edit_proposal(
        'GG_EDIT_PROPOSAL={"old_text":"åäö","new_text":"ÅÄÖ"}'
    )
    require(
        proposal == {"old_text": "åäö", "new_text": "ÅÄÖ"},
        "unicode edit parse failed",
    )
    try:
        extract_edit_proposal(
            'GG_EDIT_PROPOSAL={"old_text":"","new_text":"x"}'
        )
        raise RuntimeError("empty old_text was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_OLD_MISSING" in str(exc), str(exc))
    try:
        extract_edit_proposal(
            "GG_EDIT_PROPOSAL="
            + '{"old_text":"a","new_text":"b"}\n'
            + "GG_EDIT_PROPOSAL="
            + '{"old_text":"c","new_text":"d"}'
        )
        raise RuntimeError("ambiguous edit markers were accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_AMBIGUOUS" in str(exc), str(exc))
    try:
        extract_edit_proposal(
            'GG_EDIT_PROPOSAL={"old_text":"same","new_text":"same"}'
        )
        raise RuntimeError("no-change edit was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_NO_CHANGE" in str(exc), str(exc))
    try:
        extract_edit_proposal("GG_EDIT_PROPOSAL={not json}")
        raise RuntimeError("garbage edit JSON was accepted")
    except InformationToolError as exc:
        require("EDIT_PROPOSAL_JSON_INVALID" in str(exc), str(exc))

    qt = (PROJECT / "backend" / "resident_chat_qt.py").read_text(encoding="utf-8")
    require("_continue_with_information_tool(" in qt, "qt continue seam missing")
    require("_surface_edit_proposal(" in qt, "edit proposal seam missing")
    require("_bounce_structured_output(" in qt, "edit no-change bounce missing")
    require("ACTION_PROPOSE" in qt, "edit must use existing Limited Write propose")
    require("ACTION_APPROVE" not in qt, "model must not approve writes")
    require("_focus_workspace_current(" in qt, "workspace focus seam missing")
    workspace = (PROJECT / "qml" / "components" / "WorkspaceSurface.qml").read_text(
        encoding="utf-8"
    )
    require("function focusObject(" in workspace, "workspace focusObject missing")
    require("self._request_id," in qt, "TOOL node not bound to active request")
    runner = (PROJECT / "backend" / "resident_chat_runner.py").read_text(
        encoding="utf-8"
    )
    require("GG_TOOL_REQUEST=" in runner, "runner protocol missing")
    print("CONTROLLED_INFORMATION_TOOLS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
