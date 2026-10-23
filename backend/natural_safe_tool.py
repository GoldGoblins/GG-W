from __future__ import annotations

import re
from pathlib import Path

from backend import safe_tool_contract as tool_contract

_READ_PREFIX = re.compile(
    r"^(?:läs|read|öppna|open)\s+(.+)$",
    re.IGNORECASE,
)
_SEARCH_PREFIX = re.compile(
    r"^(?:sök|search|hitta|find)\s+(.+)$",
    re.IGNORECASE,
)
_GIT_EXACT = re.compile(
    r"^git\s+(status|diff|log|show-head)$",
    re.IGNORECASE,
)
_TEST_EXACT = re.compile(
    r"^(?:kör testerna|kör testsviten|run tests|run the tests|kör test)$",
    re.IGNORECASE,
)
_CURRENT_ALIASES = {
    "@current",
    "current",
    "den här filen",
    "denna fil",
    "this file",
    "the current file",
}


def _clean_path(raw: str) -> str | None:
    value = raw.strip().strip("\"'")
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        return None
    if len(value) > 240:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return value


def parse_natural_safe_tool_command(
    text: str,
    current_repo_relative_path: str = "",
) -> dict[str, object] | None:
    value = " ".join(text.strip().split())
    if not value or value.startswith("/"):
        return None

    read = _READ_PREFIX.fullmatch(value)
    if read is not None:
        target = read.group(1).strip()
        if target.lower() in _CURRENT_ALIASES:
            path = _clean_path(current_repo_relative_path)
        else:
            path = _clean_path(target)
        if path is None:
            return None
        return {
            "profile": tool_contract.PROFILE_READ,
            "arguments": {"path": path},
        }

    search = _SEARCH_PREFIX.fullmatch(value)
    if search is not None:
        literal = search.group(1).strip().strip("\"'")
        if not (3 <= len(literal) <= 240):
            return None
        if "\x00" in literal or "\n" in literal or "\r" in literal:
            return None
        return {
            "profile": tool_contract.PROFILE_SEARCH,
            "arguments": {"literal": literal},
        }

    git = _GIT_EXACT.fullmatch(value)
    if git is not None:
        return {
            "profile": tool_contract.PROFILE_GIT,
            "arguments": {"operation": git.group(1).lower()},
        }

    if _TEST_EXACT.fullmatch(value) is not None:
        return {
            "profile": tool_contract.PROFILE_TEST,
            "arguments": {},
        }

    return None
