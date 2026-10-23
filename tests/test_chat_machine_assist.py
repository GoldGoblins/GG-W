#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.chat_machine_assist import (
        extract_model_host_actions,
        harvest_model_host_actions,
        parse_echo_argv,
        plan_machine_work,
        propose_comment_diff,
        run_allowed_argv,
    )

    argv = parse_echo_argv(
        "Kör echo hello world i terminalen. Visa resultatet."
    )
    if argv != ["/bin/echo", "hello", "world"]:
        raise AssertionError("echo argv parse failed: " + repr(argv))
    if parse_echo_argv("echo hello; rm -rf /") is not None:
        raise AssertionError("unsafe echo accepted")
    ran = run_allowed_argv(argv)
    if ran["status"] != "PASS":
        raise AssertionError("echo run failed")
    if "hello world" not in ran["text"]:
        raise AssertionError("echo stdout missing")
    if "exit: 0" not in ran["text"]:
        raise AssertionError("echo exit missing")
    from backend.chat_machine_assist import echo_shell_line

    if echo_shell_line(argv) != "echo hello world\n":
        raise AssertionError("pty line mismatch")
    diff = propose_comment_diff("untitled", "// hello")
    if "+// hello" not in diff:
        raise AssertionError("comment diff missing")
    planned = plan_machine_work(
        "Terminalruta Kör echo hello world i terminalen.\n\n"
        "Kodblock Föreslå en kommentar // hello överst.\n\n"
        "Bara text Hej.",
        title="untitled",
    )
    if len(planned["cards"]) != 2:
        raise AssertionError("expected terminal+diff cards")
    if planned["cards"][0]["title"] != "terminal":
        raise AssertionError("terminal card missing")
    if planned.get("terminal_line") != "echo hello world\n":
        raise AssertionError("machine must hand a real pty line")
    if planned["cards"][1]["title"] != "diff":
        raise AssertionError("diff card missing")
    if "No fences" not in str(planned["remainder"]):
        raise AssertionError("qwen remainder missing machine note")
    if "echo hello world" not in planned["cards"][0]["text"]:
        raise AssertionError("terminal card missing real echo output")
    parens = parse_echo_argv(
        "Kodblock (ändring, inte bara läsning) Kör echo hello world i terminalen."
    )
    if parens != ["/bin/echo", "hello", "world"]:
        raise AssertionError("parentheses in the ask blocked real echo")
    hello = plan_machine_work("hejsan", title="untitled")
    if hello["cards"]:
        raise AssertionError("greeting should not run the machine")
    leaked = plan_machine_work(
        "----- USER -----\n"
        "gör en enkel funktion i untitled\n"
        "----- GG RESOLVED CONTEXT V1 -----\n"
        "Kör echo hello world. // hello\n",
        title="untitled",
    )
    if leaked["cards"]:
        raise AssertionError("recent-chat echo leaked into the next turn")
    from backend.chat_machine_assist import execute_host_tool, validate_host_tool

    parsed = validate_host_tool(
        {"profile": "TERMINAL_RUN", "argv": ["echo", "hello", "world"]}
    )
    ran = execute_host_tool(parsed, workspace=None)
    if ran["status"] != "PASS" or "hello world" not in ran["output"]:
        raise AssertionError("host TERMINAL_RUN did not execute echo")
    sample = (
        "Hej. Den öppna filen är en tom fil.\n\n"
        "Terminalruta:\n"
        "```\n"
        "echo hello world\n"
        "```\n"
        "Resultat:\n"
        "```\n"
        "hello world\n"
        "```\n"
        "Kodblock:\n"
        "```diff\n"
        "+// hello\n"
        "```\n"
        "Bara text:\n"
        "Hej. Den öppna filen är en tom fil.\n"
    )
    harvested_visible, harvested = harvest_model_host_actions(sample)
    if len(harvested) != 2:
        raise AssertionError("expected echo+write from model fences: " + repr(harvested))
    if harvested[0]["profile"] != "TERMINAL_RUN":
        raise AssertionError("first fence was not terminal")
    if harvested[0]["argv"] != ["echo", "hello", "world"]:
        raise AssertionError("echo argv from fence: " + repr(harvested[0]))
    if harvested[1]["profile"] != "CURRENT_WRITE":
        raise AssertionError("diff fence was not write")
    if "// hello" not in str(harvested[1]["text"]):
        raise AssertionError("diff write missing comment")
    if "echo hello world" in harvested_visible:
        raise AssertionError("executed fence leaked into visible text")
    if "hello world" in harvested_visible:
        raise AssertionError("fake stdout leaked into visible text")
    hi_visible, hi_actions = harvest_model_host_actions("Hej, hur mår du?")
    if hi_actions:
        raise AssertionError("greeting harvested host actions")
    if hi_visible != "Hej, hur mår du?":
        raise AssertionError("greeting text mutated")
    marker_visible, marker_actions = extract_model_host_actions(
        'Kort.\nGG_TOOL_REQUEST={"profile":"TERMINAL_RUN","argv":["echo","hello","world"]}'
    )
    if marker_visible != "Kort.":
        raise AssertionError("GG_TOOL_REQUEST visible strip failed")
    if len(marker_actions) != 1 or marker_actions[0]["profile"] != "TERMINAL_RUN":
        raise AssertionError("GG_TOOL_REQUEST lost to fence harvest")
    if harvest_model_host_actions("```\nrm -rf /\n```")[1]:
        raise AssertionError("rm fence was accepted")
    print("CHAT_MACHINE_ASSIST_TEST=PASS")
    print("MACHINE=MODEL_FENCE_THEN_ALLOWLISTED_HOST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
