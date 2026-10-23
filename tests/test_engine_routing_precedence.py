#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    from backend.grok_worker_contract import (
        ENGINE_GROK_TUI,
        ENGINE_GROK_WORKER,
        ENGINE_LOCAL_QWEN,
        GrokWorkerContractError,
        normalize_engine_target,
    )
    from backend.natural_safe_tool import parse_natural_safe_tool_command

    main_py = (PROJECT / "main.py").read_text(encoding="utf-8")
    resident = (PROJECT / "backend" / "resident_chat_qt.py").read_text(
        encoding="utf-8"
    )
    worker = (PROJECT / "backend" / "grok_worker_qt.py").read_text(
        encoding="utf-8"
    )
    submit_src = main_py[main_py.index("def submit(") :]
    submit_src = submit_src[: submit_src.index("\n    def ", 1)]

    control_i = submit_src.index("control_contract.parse_control_command(value)")
    active_i = submit_src.index("if self._active():")
    follow_i = submit_src.index("accept_followup(")
    engine_i = submit_src.index(
        "normalize_engine_target(self._root.property(\"engineTarget\"))"
    )
    grok_i = submit_src.index(
        "if engine_target == ENGINE_GROK_WORKER or engine_target == ENGINE_GROK_TUI:"
    )
    grok_dispatch_i = submit_src.index(
        "self._submit_resident_prompt(value, context_reference, workspace_object_id, {})"
    )
    selfdev_i = submit_src.index("parse_selfdev_command(value)")
    autonomy_i = submit_src.index("parse_autonomy_command(value)")
    write_i = submit_src.index("parse_write_command(value)")
    mandate_i = submit_src.index("parse_mandate_command(value)")
    tool_i = submit_src.index("parse_safe_tool_command(value)")
    natural_i = submit_src.index("parse_natural_safe_tool_command(")

    require(control_i < active_i, "STOP/control must precede busy gate")
    require(active_i < follow_i, "busy followup must stay in _active gate")
    require(follow_i < engine_i, "engineTarget must follow STOP and busy followup")
    require(engine_i < grok_i, "engine target must be validated before dispatch")
    require(grok_i < selfdev_i, "GROK_WORKER dispatch must precede selfdev")
    require(grok_i < autonomy_i, "GROK_WORKER dispatch must precede autonomy")
    require(grok_i < write_i, "GROK_WORKER dispatch must precede write")
    require(grok_i < mandate_i, "GROK_WORKER dispatch must precede mandate")
    require(grok_i < tool_i, "GROK_WORKER dispatch must precede /read tools")
    require(grok_i < natural_i, "GROK_WORKER dispatch must precede natural Läs")
    require(grok_dispatch_i > grok_i, "GROK_WORKER must dispatch raw user prompt")
    require(
        grok_dispatch_i < selfdev_i,
        "raw GROK_WORKER dispatch must return before local handlers",
    )
    require(
        "GrokWorkerContractError" in submit_src
        and '"FAIL"' in submit_src[engine_i:grok_i],
        "unknown engineTarget must fail closed",
    )

    read = parse_natural_safe_tool_command(
        "Läs filen projects/gg-ai-desktop/qml/Main.qml och svara kort: 1. x"
    )
    require(read is not None, "LOCAL QWEN Läs parser must still match")
    require(read["profile"] == "READ", "LOCAL QWEN Läs must stay READ")
    require(
        "parse_natural_safe_tool_command(" in submit_src[selfdev_i:],
        "LOCAL QWEN natural safe-tool path missing after GROK branch",
    )
    require(
        "if engine_target == ENGINE_GROK_WORKER or engine_target == ENGINE_GROK_TUI:"
        in submit_src,
        "GROK WORKER/TUI branch missing",
    )
    require(
        normalize_engine_target("GROK_WORKER") == ENGINE_GROK_WORKER,
        "GROK_WORKER normalize failed",
    )
    require(
        normalize_engine_target("GROK_TUI") == ENGINE_GROK_TUI,
        "GROK_TUI normalize failed",
    )
    require("ENGINE_GROK_TUI" in resident, "TUI engine missing in resident")
    require("startGrokTui(" in resident, "TUI PTY start missing")
    require(
        normalize_engine_target("LOCAL_QWEN") == ENGINE_LOCAL_QWEN,
        "LOCAL_QWEN normalize failed",
    )
    try:
        normalize_engine_target("People")
        raise AssertionError("People accepted as engine")
    except GrokWorkerContractError as exc:
        require("ENGINE_TARGET_UNKNOWN" in str(exc), str(exc))

    require("_queued_prompts" in worker, "mid-turn queue missing")
    require("accept_followup(" in resident, "busy followup missing")
    require(
        "self._grok_worker().submit(" in resident,
        "worker dispatch missing",
    )
    require(
        "if target == ENGINE_GROK_WORKER:" in resident,
        "resident grok branch missing",
    )
    require(
        "self._fail_current(" in worker,
        "fail-closed worker path missing",
    )
    require(
        "silent" not in resident.lower()
        or "fallback" not in resident.lower().split("grok")[0],
        "unexpected fallback wording",
    )
    require(
        'if target == ENGINE_GROK_WORKER:' in resident
        and "LOCAL_QWEN" not in resident[
            resident.index("if target == ENGINE_GROK_WORKER:") : resident.index(
                "return self._grok_worker().submit("
            )
        ],
        "Qwen fallback inside grok dispatch",
    )

    none_i = submit_src.index("if participant_prepared is None:")
    require(grok_i < none_i, "participant branch must stay after GROK routing")
    tail = submit_src[none_i:]
    require(
        'request_id = "chat-" + uuid.uuid4().hex' in tail,
        "participant branch missing request_id",
    )
    require("contract.validate_request(" in tail, "participant branch missing request")
    require("canonical_request_json(request)" in tail, "participant branch lost request")
    require('"request_id": request_id' in tail, "participant state lost request_id")
    require(
        "self._set_bridge_activity(True, request_id)" in tail,
        "participant activity lost request_id",
    )
    require(
        "_submit_resident_prompt(effective_prompt" in tail.split("return", 1)[0],
        "ordinary Qwen helper lost",
    )
    require(
        submit_src.index('request_id = "chat-" + uuid.uuid4().hex') > none_i,
        "request_id created before participant branch",
    )

    print("GROK_WORKER_DISPATCH_TEST=PASS")
    print("LOCAL_QWEN_SAFE_TOOL_REGRESSION=PASS")
    print("STOP_CANCEL_REGRESSION=PASS")
    print("BUSY_QUEUE_SESSION_REGRESSION=PASS")
    print("FAIL_CLOSED_REGRESSION=PASS")
    print("ENGINE_ROUTING_PRECEDENCE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
