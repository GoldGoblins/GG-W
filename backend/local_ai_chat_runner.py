#!/usr/bin/env python3
"""Local-only CHAT adapter around the frozen published GG model runner."""

from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.platform_files import (
    mode_matches,
    owned_by_current_user,
    set_private_mode,
)
from backend.platform_support import (
    private_runtime_root,
)


import json
import os
import stat
import sys
from pathlib import Path

from backend import local_ai_model_runner as base
from backend.local_ai_platform import adapt_model_runner

base = adapt_model_runner(base)


# Chat output must satisfy the frozen runner's marker invariant
# deterministically. The model is not merely asked to emit the marker;
# the local GBNF grammar requires it as the final part of text.
CHAT_MODEL_GBNF = (
    'char ::= [^"\\\\\\x7F\\x00-\\x1F] | [\\\\] (["\\\\bfnrt] | "u" [0-9a-fA-F]{4})\n'
    'root ::= "{" space text-kv space "}"\n'
    'space ::= | " " | "\\n"{1,2} [ \\t]{0,20}\n'
    'text ::= "\\"" char{1,1024} "GG_MODEL_RUNNER_OK" "\\""\n'
    'text-kv ::= "\\"text\\"" space ":" space text\n'
)


def execute_chat(
    evidence_arg: str,
    render_arg: str,
    request_arg: str,
) -> int:
    request_path = Path(request_arg)

    if request_path.is_symlink() or not request_path.is_file():
        raise base.RunnerStop("chat_request_file_unsafe")

    resolved = request_path.resolve(strict=True)
    runtime_parent = private_runtime_root()

    if resolved.parent != runtime_parent:
        raise base.RunnerStop("chat_request_parent_invalid")

    if not resolved.name.startswith("gg-workbench-chat-request."):
        raise base.RunnerStop("chat_request_name_invalid")

    info = resolved.stat()

    if not owned_by_current_user(resolved):
        raise base.RunnerStop("chat_request_owner_invalid")

    if not mode_matches(resolved, 0o600):
        raise base.RunnerStop("chat_request_mode_invalid")

    try:
        raw = json.loads(
            resolved.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise base.RunnerStop("chat_request_json_invalid") from exc

    contract = base.load_contract()
    request = contract.validate_request(raw)

    old_request_id = base.REQUEST_ID
    old_prompt = base.PROMPT
    old_grammar = base.MODEL_GBNF

    try:
        base.REQUEST_ID = request["request_id"]
        base.PROMPT = (
            request["prompt"]
            + "\n\n"
            + "Svara naturligt, hjälpsamt och konkret på användarens meddelande. Följ användarens språk."
        )
        base.MODEL_GBNF = CHAT_MODEL_GBNF

        return base.execute_synthetic(
            evidence_arg,
            render_arg,
        )
    finally:
        base.REQUEST_ID = old_request_id
        base.PROMPT = old_prompt
        base.MODEL_GBNF = old_grammar


def main() -> int:
    args = sys.argv[1:]

    if len(args) == 4 and args[0] == "--execute-chat":
        return execute_chat(
            args[1],
            args[2],
            args[3],
        )

    print(
        "usage: local_ai_chat_runner.py "
        "--execute-chat EVIDENCE_DIR RENDER_NODE REQUEST_JSON",
        file=sys.stderr,
    )
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
