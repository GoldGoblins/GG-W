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
    from backend.natural_safe_tool import parse_natural_safe_tool_command
    from backend import safe_tool_contract as tool_contract

    current = "projects/gg-ai-desktop/qml/components/ContextComposer.qml"
    require(
        parse_natural_safe_tool_command("Hej") is None,
        "greeting became a tool",
    )
    require(
        parse_natural_safe_tool_command(
            "Hej, fungerar du som en vanlig assistent i workbenchen?"
        )
        is None,
        "ordinary chat became a tool",
    )
    require(
        parse_natural_safe_tool_command("/read main.py") is None,
        "slash command was re-parsed",
    )

    read = parse_natural_safe_tool_command("läs main.py")
    require(
        read
        == {
            "profile": tool_contract.PROFILE_READ,
            "arguments": {"path": "main.py"},
        },
        "read mapping failed",
    )
    current_read = parse_natural_safe_tool_command(
        "läs @current",
        current,
    )
    require(
        current_read
        == {
            "profile": tool_contract.PROFILE_READ,
            "arguments": {"path": current},
        },
        "@current read mapping failed",
    )
    require(
        parse_natural_safe_tool_command("läs ../secret") is None,
        "parent traversal was accepted",
    )

    search = parse_natural_safe_tool_command('sök parse_safe_tool_command')
    require(
        search
        == {
            "profile": tool_contract.PROFILE_SEARCH,
            "arguments": {"literal": "parse_safe_tool_command"},
        },
        "search mapping failed",
    )
    require(
        parse_natural_safe_tool_command("sök ab") is None,
        "tiny search was accepted",
    )

    git = parse_natural_safe_tool_command("git status")
    require(
        git
        == {
            "profile": tool_contract.PROFILE_GIT,
            "arguments": {"operation": "status"},
        },
        "git mapping failed",
    )
    test = parse_natural_safe_tool_command("kör testerna")
    require(
        test
        == {
            "profile": tool_contract.PROFILE_TEST,
            "arguments": {},
        },
        "test mapping failed",
    )

    main_py = (PROJECT / "main.py").read_text(encoding="utf-8")
    require(
        "parse_natural_safe_tool_command(" in main_py,
        "launcher seam missing",
    )
    print("NATURAL_SAFE_TOOL_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
