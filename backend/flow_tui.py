"""FLOW TUI — a shared, sequential task ledger for GROK TUI and GPTUI."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from backend import agent_flow, long_memory


SCHEMA = "gg.flow-tui.v1"
ENGINE = "FLOW_TUI"
ACTION_AUTHORITY = "NONE"
PARALLEL_AGENT_BRAIN = "FORBIDDEN"
EXECUTION_MODEL = "SEQUENTIAL_OWNED_HANDOFF"
MAX_TRANSCRIPT = 64
MAX_REQUEST_CHARS = 64000
MAX_REPLY_CHARS = 24000
MAX_SHARED_CONTEXT_CHARS = 6000
WAITING = "…"
SEQUENTIAL_STAGES = (
    "GROK_PLAN",
    "GPT_BUILD",
    "GROK_REVIEW",
    "GPT_REPAIR",
    "GROK_FINAL_REVIEW",
)

_STATE: dict[str, Any] | None = None


def empty() -> dict[str, Any]:
    graph = agent_flow.empty()
    graph["parallel_execution"] = EXECUTION_MODEL
    graph["execution_model"] = EXECUTION_MODEL
    return {
        "schema": SCHEMA,
        "engine": ENGINE,
        "ask": "",
        "graph": graph,
        "grok": {
            "motor": "GROK_TUI",
            "title": "GROK TUI",
            "packet": "intent · constraints · scope · handoff",
            "status": "IDLE",
            "jobs": [],
        },
        "gpt": {
            "motor": "GPT_TUI",
            "title": "GPTUI",
            "packet": "assigned task · implementation · evidence",
            "status": "IDLE",
            "jobs": [],
        },
        "merge": {
            "status": "IDLE",
            "note": "One owner works at a time. Both motors use the shared task ledger.",
            "ready": False,
            "light": "HOLD",
        },
        "execution_model": EXECUTION_MODEL,
        "parallel_execution": EXECUTION_MODEL,
        "shared_memory": {
            "recent_chat": "",
            "lessons": [],
            "work": {
                "original_request": "",
                "phase": "IDLE",
                "owner": "",
                "grok_handoff": "",
                "gpt_work": "",
                "grok_review": "",
                "gpt_repair": "",
                "grok_final_review": "",
                "completed": [],
                "open": [],
            },
        },
        "transcript": [],
        "baselines": {"GROK TUI": "", "GPTUI": ""},
        "dispatched": {"grok": False, "gpt": False},
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "action_authority": ACTION_AUTHORITY,
        "hint": "One shared task ledger. GROK TUI and GPTUI take distinct sequential stages in this chat.",
    }


def _packet_text(title: str, ask: str, jobs: list[str]) -> str:
    lines = [
        "[FLOW TUI] " + title,
        "Shared ask: " + ask,
        "Your jobs:",
    ]
    for job in jobs:
        lines.append("- " + job)
    lines.append("Wait for the named handoff before your stage. Do not duplicate the other motor's work.")
    return "\n".join(lines)


def _compact_context(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:].lstrip()


def _recent_chat(transcript: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for row in transcript[-16:]:
        role = str(row.get("role") or "").strip()
        body = str(row.get("text") or "").strip()
        if not role or not body or body == WAITING:
            continue
        stage = str(row.get("stage") or "").strip()
        label = role + (" / " + stage if stage else "")
        rows.append(label + ": " + body)
    return _compact_context("\n\n".join(rows), MAX_SHARED_CONTEXT_CHARS)


def _shared_memory_text(
    state: dict[str, Any],
    *,
    exclude: tuple[str, ...] = (),
) -> str:
    memory = state.get("shared_memory") or {}
    sections: list[str] = []
    history = str(memory.get("recent_chat") or "").strip()
    if history:
        sections.append("Recent shared chat memory:\n" + history)
    lessons = memory.get("lessons") or []
    if lessons:
        lines = [
            "- " + str(row.get("statement") or "")
            for row in lessons
            if isinstance(row, dict) and str(row.get("statement") or "").strip()
        ]
        if lines:
            sections.append("Shared long-memory lessons:\n" + "\n".join(lines))
    work = memory.get("work") or {}
    if work:
        ledger = [
            "Shared task ledger:",
            "Phase: " + str(work.get("phase") or "IDLE"),
            "Owner: " + str(work.get("owner") or "none"),
        ]
        for key, label in (
            ("grok_handoff", "GROK TUI handoff"),
            ("gpt_work", "GPTUI work"),
            ("grok_review", "GROK TUI review"),
            ("gpt_repair", "GPTUI repair"),
            ("grok_final_review", "GROK TUI final review"),
        ):
            if key in exclude:
                continue
            value = str(work.get(key) or "").strip()
            if value:
                ledger.append(label + ":\n" + _compact_context(value, 2400))
        completed = [str(item).strip() for item in (work.get("completed") or [])]
        if completed:
            ledger.append("Completed stages: " + "; ".join(completed))
        open_items = [str(item).strip() for item in (work.get("open") or [])]
        if open_items:
            ledger.append("Open items: " + "; ".join(open_items))
        sections.append("\n".join(ledger))
    return _compact_context("\n\n".join(sections), MAX_SHARED_CONTEXT_CHARS)


def grok_plan_prompt() -> str:
    state = snapshot()
    ask = str(state.get("ask") or "").strip()
    grok = state.get("grok") or {}
    shared = _shared_memory_text(state)
    jobs = "\n".join("- " + str(item) for item in (grok.get("jobs") or []))
    return "\n".join(
        [
            "[FLOW TUI · GROK TUI · STAGE 1/5: SCOPE AND HANDOFF]",
            "Original user request: " + ask,
            "You own project context, intent, constraints, and a bounded plan.",
            "GPTUI owns the later implementation/detail and verification stage. "
            "Do not duplicate that work or claim it is done.",
            "Assign distinct concrete work to GPTUI. Preserve user decisions; "
            "mark facts, assumptions, completed work, open items, and the next owner.",
            "Your planning focus:\n" + (jobs or "- identify the task scope and handoff"),
            "Return a compact handoff with headings: FACTS, DECISIONS, "
            "ASSUMPTIONS, GPTUI_TASK, OPEN.",
            "The handoff is shared working memory; GPTUI will receive it verbatim.",
            shared,
        ]
    ).strip()


def gpt_build_prompt(grok_handoff: str) -> str:
    state = snapshot()
    ask = str(state.get("ask") or "").strip()
    gpt = state.get("gpt") or {}
    shared = _shared_memory_text(state, exclude=("grok_handoff",))
    jobs = "\n".join("- " + str(item) for item in (gpt.get("jobs") or []))
    return "\n".join(
        [
            "[FLOW TUI · GPTUI · STAGE 2/5: OWNED WORK]",
            "Original user request: " + ask,
            "GROK TUI completed the context and planning stage. Use its "
            "handoff as the source of task scope and ownership:",
            str(grok_handoff or "(GROK TUI produced no handoff.)"),
            "You own only the GPTUI_TASK and the bounded technical/detail "
            "work assigned to you. Continue the same task, do not redo Grok's "
            "planning, and do not broaden the scope.",
            "The GPTUI_TASK assignment in the handoff is authoritative; any "
            "generic focus hints are subordinate to it.",
            "Your focus:\n" + (jobs or "- complete the assigned implementation or analysis"),
            "Report concrete work completed, evidence or checks performed, "
            "open items, and what GROK TUI should review.",
            "This is one shared task ledger; keep ownership explicit and avoid duplicate work.",
            shared,
        ]
    ).strip()


def grok_review_prompt(
    grok_handoff: str,
    gpt_work: str,
    *,
    final_after_repair: bool = False,
) -> str:
    state = snapshot()
    ask = str(state.get("ask") or "").strip()
    excluded = ("grok_handoff", "gpt_work")
    if final_after_repair:
        excluded = excluded + ("grok_review", "gpt_repair")
    shared = _shared_memory_text(state, exclude=excluded)
    return "\n".join(
        [
            "[FLOW TUI · GROK TUI · "
            + ("STAGE 5/5: FINAL REVIEW AFTER REPAIR]" if final_after_repair
               else "STAGE 3/5: INTEGRATION REVIEW]"),
            "Original user request: " + ask,
            "Your scope/constraint handoff:",
            str(grok_handoff or "(empty handoff)"),
            "GPTUI's completed work and evidence:",
            str(gpt_work or "(no GPTUI work report)"),
            ("Review the repaired result against the original request and your prior findings. "
             "Do not start another repair loop. Check for missed items, unsupported claims, "
             "and unresolved blockers."
             if final_after_repair else
             "Review the shared task against the original request. Do not repeat the implementation. "
             "Check ownership for duplicate work, missed items, unsupported claims, and blockers."),
            "Start with exactly one marker: FLOW_STATUS: COMPLETE or "
            "FLOW_STATUS: NEEDS_WORK. Then state completed items, remaining "
            "items, and the precise next owner. Use NEEDS_WORK if any required "
            "item is unverified or missing.",
            shared,
        ]
    ).strip()


def gpt_repair_prompt(grok_handoff: str, gpt_work: str, grok_review: str) -> str:
    state = snapshot()
    ask = str(state.get("ask") or "").strip()
    shared = _shared_memory_text(
        state,
        exclude=("grok_handoff", "gpt_work", "grok_review"),
    )
    return "\n".join(
        [
            "[FLOW TUI · GPTUI · BOUNDED REPAIR PASS]",
            "Original user request: " + ask,
            "GROK TUI handoff:\n" + str(grok_handoff or "(empty)"),
            "Your previous work:\n" + str(gpt_work or "(empty)"),
            "GROK TUI review:\n" + str(grok_review or "(empty)"),
            "Address only the concrete missing or incorrect items in the review. "
            "Do not repeat completed work or widen the task. If the review "
            "conflicts with the original request or evidence, explain that "
            "instead of applying an unsafe change.",
            "Finish with completed items and any remaining blocker. This is "
            "the single bounded repair pass. GROK TUI will do one final check; "
            "do not start another review or repair loop.",
            shared,
        ]
    ).strip()


def review_is_complete(text: str) -> bool:
    first = str(text or "").strip().splitlines()
    return bool(first and first[0].strip() == "FLOW_STATUS: COMPLETE")


def handoff_has_gpt_assignment(text: str) -> bool:
    active = False
    headings = {
        "FACTS", "DECISIONS", "ASSUMPTIONS", "GPTUI_TASK", "OPEN",
        "OPEN_ITEMS", "COMPLETED", "COMPLETED_ITEMS",
    }
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        content = line.lstrip("# ").lstrip("-*• ").strip()
        name, separator, inline = content.partition(":")
        heading = name.rstrip("* `_ ").upper().replace(" ", "_")
        if heading == "GPTUI_TASK":
            active = True
            value = inline.strip() if separator else ""
            if value.lower() not in {"", "none", "n/a", "tbd", "-"}:
                return True
            continue
        if heading in headings:
            active = False
            continue
        if active:
            value = line.lstrip("-*• ").strip()
            if value.lower() not in {"", "none", "n/a", "tbd", "-"}:
                return True
    return False


def _chrome_char(ch: str) -> bool:
    if ch.isspace():
        return False
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return name.startswith(
        ("BOX DRAWINGS", "BLOCK", "SHADE", "BRAILLE", "LIGHT SHADE", "FULL BLOCK")
    )


def clean_plain(text: str) -> str:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        body = "".join(ch for ch in raw if not _chrome_char(ch))
        body = " ".join(body.split())
        if not body:
            continue
        if set(body) <= set(".:-_/\\|•·+=~*"):
            continue
        lines.append(body)
    return "\n".join(lines)


def delta_plain(before: str, after: str) -> str:
    after_text = str(after or "")
    before_text = str(before or "")
    if not after_text or after_text == before_text:
        return ""
    if before_text and after_text.startswith(before_text):
        return after_text[len(before_text) :].lstrip("\n")
    old_lines = before_text.splitlines()
    new_lines = after_text.splitlines()
    index = 0
    limit = min(len(old_lines), len(new_lines))
    while index < limit and old_lines[index] == new_lines[index]:
        index += 1
    return "\n".join(new_lines[index:]).strip()


def reply_from_dump(baseline: str, dump: str, ask: str) -> str:
    body = delta_plain(clean_plain(baseline), clean_plain(dump))
    needle = " ".join(str(ask or "").split())
    if not body:
        return ""
    lines = body.splitlines()
    if needle:
        last_ask = -1
        for index, line in enumerate(lines):
            if needle in line:
                last_ask = index
        if last_ask >= 0:
            lines = lines[last_ask + 1 :]
    out: list[str] = []
    for line in lines:
        bit = " ".join(line.split())
        if not bit or bit == needle:
            continue
        out.append(bit)
    return "\n".join(out).strip()


def is_chrome_reply(text: str) -> bool:
    compact = " ".join(str(text or "").split())
    if not compact:
        return True
    lower = compact.lower()
    if "enter:send" in lower or "alt+enter:newline" in lower:
        return True
    if "shift+tab:mode" in lower or "ctrl+x:" in lower:
        return True
    if "max fast" in lower and "goldgoblins" in lower:
        return True
    return False


def extract_assistant_events(blob: str, *, role: str) -> tuple[str, bool]:
    """Return assistant text plus the motor's explicit end-of-turn event."""
    parts: list[str] = []
    final_message = ""
    done = False
    motor = str(role or "")
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if motor == "GROK TUI":
            params = row.get("params")
            update = params.get("update") if isinstance(params, dict) else None
            if not isinstance(update, dict):
                continue
            event = str(update.get("sessionUpdate") or "")
            if event in {"end", "turn_completed"}:
                done = True
                continue
            if event != "agent_message_chunk":
                continue
            content = update.get("content")
            text = content.get("text") if isinstance(content, dict) else None
            if text:
                parts.append(str(text))
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            for item in payload.get("content") or []:
                if isinstance(item, dict) and item.get("type") in ("output_text", "text"):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
        elif payload.get("type") in {
            "task_complete",
            "turn_complete",
            "turn_completed",
            "response.completed",
        }:
            done = True
            text = payload.get("last_agent_message")
            if text:
                final_message = str(text)
    if not parts and final_message:
        parts.append(final_message)
    body = "".join(parts) if motor == "GROK TUI" else "\n".join(parts)
    body = body.strip()
    if not body or is_chrome_reply(body):
        return "", done
    return body[:MAX_REPLY_CHARS], done


def extract_assistant_jsonl(blob: str, *, role: str) -> str:
    """Compatibility helper returning assistant text without TUI chrome."""
    text, _done = extract_assistant_events(blob, role=role)
    return text


def append_assistant_text(current: str, piece: str, *, role: str) -> str:
    """Append live chunks while avoiding repeated full-response snapshots."""
    before = str(current or "").strip()
    after = str(piece or "").strip()
    if not after:
        return before[:MAX_REPLY_CHARS]
    if not before:
        return after[:MAX_REPLY_CHARS]
    if role != "GROK TUI":
        if after == before or before.endswith(after):
            return before[:MAX_REPLY_CHARS]
        if after.startswith(before):
            return after[:MAX_REPLY_CHARS]
        if before.startswith(after):
            return before[:MAX_REPLY_CHARS]
        return (before + "\n" + after)[:MAX_REPLY_CHARS]
    return (before + after)[:MAX_REPLY_CHARS]


def _motor_row(role: str, kind: str, text: str, *, stage: str = "") -> dict[str, str]:
    row = {
        "role": role,
        "kind": kind,
        "text": text[:MAX_REQUEST_CHARS if role == "YOU" else MAX_REPLY_CHARS],
    }
    if stage:
        row["stage"] = stage
    return row


def _open_items(text: str) -> list[str]:
    active = False
    out: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        heading = line.rstrip(":#* ").upper()
        if heading in {"OPEN", "OPEN ITEMS", "REMAINING", "REMAINING ITEMS"}:
            active = True
            continue
        if active and heading in {
            "FACTS", "DECISIONS", "ASSUMPTIONS", "GPTUI_TASK", "COMPLETED",
            "COMPLETED ITEMS", "EVIDENCE", "NEXT OWNER",
        }:
            active = False
        if active and line:
            item = line.lstrip("-*• ").strip()
            if item and item not in out:
                out.append(item[:240])
        if len(out) >= 8:
            break
    return out


def _work(state: dict[str, Any]) -> dict[str, Any]:
    memory = state.setdefault("shared_memory", {})
    if not isinstance(memory, dict):
        memory = {}
        state["shared_memory"] = memory
    work = memory.setdefault("work", {})
    if not isinstance(work, dict):
        work = {}
        memory["work"] = work
    work.setdefault("completed", [])
    work.setdefault("open", [])
    return work


def _replace_motor(
    transcript: list[dict[str, Any]],
    role: str,
    kind: str,
    text: str,
    *,
    stage: str = "",
) -> None:
    index = None
    for pos in range(len(transcript) - 1, -1, -1):
        row = transcript[pos]
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "") == "YOU":
            break
        if str(row.get("role") or "") == role:
            if stage and str(row.get("stage") or "") != stage:
                continue
            index = pos
            break
    body = str(text or "").strip()
    if index is None:
        if body:
            transcript.append(_motor_row(role, kind, body, stage=stage))
        return
    if body:
        transcript[index] = _motor_row(role, kind, body, stage=stage)
    elif kind == "REPLY" and str(transcript[index].get("text") or "") == WAITING:
        transcript[index] = _motor_row(role, "REPLY", "no reply yet", stage=stage)


def submit(text: str) -> dict[str, Any]:
    global _STATE
    ask = str(text or "").strip()
    if not ask:
        return snapshot()
    if len(ask) > MAX_REQUEST_CHARS:
        raise ValueError("FLOW_REQUEST_TOO_LARGE")
    graph = agent_flow.run(ask)
    graph = dict(graph)
    graph["parallel_execution"] = EXECUTION_MODEL
    graph["execution_model"] = EXECUTION_MODEL
    graph["execution"] = {
        "model": EXECUTION_MODEL,
        "stages": list(SEQUENTIAL_STAGES),
        "max_repair_passes": 1,
        "max_review_passes": 2,
    }
    grok_jobs = ["scope the request, preserve constraints, and assign GPTUI a distinct task"]
    gpt_jobs = ["complete only the concrete GPTUI_TASK in GROK TUI's handoff"]
    man = graph.get("front_man") or {}
    state = empty()
    prev = _STATE or empty()
    transcript = list(prev.get("transcript") or [])
    transcript.append(_motor_row("YOU", "REQUEST", ask))
    transcript.append(_motor_row("GROK TUI", "STREAM", WAITING, stage="PLAN"))
    try:
        lessons = long_memory.recall(ask, limit=4)
    except Exception:
        lessons = []
    lesson_rows = [
        {"statement": str(row.get("statement") or "")[:500]}
        for row in lessons
        if isinstance(row, dict) and str(row.get("statement") or "").strip()
    ]
    prior_transcript = list(prev.get("transcript") or [])
    prior_memory = _recent_chat(prior_transcript)
    work = {
        "original_request": ask,
        "phase": "GROK_PLAN",
        "owner": "GROK TUI",
        "grok_handoff": "",
        "gpt_work": "",
        "grok_review": "",
        "gpt_repair": "",
        "grok_final_review": "",
        "completed": [],
        "open": ["GROK TUI scopes the task and assigns GPTUI a distinct part."],
    }
    state.update(
        {
            "ask": ask,
            "graph": graph,
            "grok": {
                "motor": "GROK_TUI",
                "title": "GROK TUI",
                "packet": _packet_text("GROK TUI", ask, grok_jobs),
                "status": "RUNNING",
                "jobs": grok_jobs,
            },
            "gpt": {
                "motor": "GPT_TUI",
                "title": "GPTUI",
                "packet": _packet_text("GPTUI", ask, gpt_jobs),
                "status": "WAITING",
                "jobs": gpt_jobs,
            },
            "merge": {
                "status": "RUNNING",
                "note": "GROK TUI owns PLAN. GPTUI waits for the explicit handoff.",
                "ready": False,
                "light": "HOLD",
            },
            "transcript": transcript[-MAX_TRANSCRIPT:],
            "baselines": {"GROK TUI": "", "GPTUI": ""},
            "dispatched": {"grok": False, "gpt": False},
            "front_man": man,
            "reviewer_is_author": False,
            "shared_memory": {
                "recent_chat": prior_memory,
                "lessons": lesson_rows,
                "work": work,
            },
        }
    )
    _STATE = state
    return snapshot()


def arm(dumps: dict[str, str] | None = None) -> dict[str, Any]:
    global _STATE
    state = dict(_STATE) if _STATE is not None else empty()
    baselines = dict(state.get("baselines") or {})
    for role, dump in (dumps or {}).items():
        baselines[str(role)] = clean_plain(dump)
    state["baselines"] = baselines
    _STATE = state
    return snapshot()


def ingest_dump(role: str, dump: str) -> dict[str, Any]:
    global _STATE
    name = str(role or "").strip() or "GROK TUI"
    state = dict(_STATE) if _STATE is not None else empty()
    baselines = dict(state.get("baselines") or {})
    body = reply_from_dump(
        str(baselines.get(name) or ""),
        dump,
        str(state.get("ask") or ""),
    )
    if not body or is_chrome_reply(body):
        return snapshot()
    transcript = list(state.get("transcript") or [])
    _replace_motor(transcript, name, "STREAM", body)
    state["transcript"] = transcript[-MAX_TRANSCRIPT:]
    _STATE = state
    return snapshot()


def set_motor_stream(
    role: str,
    text: str,
    *,
    done: bool = False,
    stage: str = "",
) -> dict[str, Any]:
    global _STATE
    state = dict(_STATE) if _STATE is not None else empty()
    transcript = list(state.get("transcript") or [])
    _replace_motor(
        transcript,
        str(role or "").strip() or "GROK TUI",
        "REPLY" if done else "STREAM",
        text,
        stage=stage,
    )
    state["transcript"] = transcript[-MAX_TRANSCRIPT:]
    _STATE = state
    return snapshot()


def set_phase(stage: str, owner: str, note: str = "") -> dict[str, Any]:
    global _STATE
    state = dict(_STATE) if _STATE is not None else empty()
    work = _work(state)
    phase = str(stage or "").strip() or "UNKNOWN"
    motor = str(owner or "").strip() or "FLOW"
    work["phase"] = phase
    work["owner"] = motor
    if motor == "GROK TUI":
        state["grok"] = {**(state.get("grok") or {}), "status": "RUNNING"}
        if str((state.get("gpt") or {}).get("status") or "") == "RUNNING":
            state["gpt"] = {**(state.get("gpt") or {}), "status": "WAITING"}
    elif motor == "GPTUI":
        state["gpt"] = {**(state.get("gpt") or {}), "status": "RUNNING"}
        if str((state.get("grok") or {}).get("status") or "") == "RUNNING":
            state["grok"] = {**(state.get("grok") or {}), "status": "WAITING"}
    label = phase.replace("GROK_", "").replace("GPT_", "").replace("_", " ")
    transcript = list(state.get("transcript") or [])
    _replace_motor(transcript, motor, "STREAM", WAITING, stage=label)
    state["transcript"] = transcript[-MAX_TRANSCRIPT:]
    merge = dict(state.get("merge") or {})
    merge.update({
        "status": "RUNNING",
        "note": note or (motor + " owns " + label + ". The other motor waits."),
        "ready": False,
        "light": "HOLD",
    })
    state["merge"] = merge
    _STATE = state
    return snapshot()


def record_stage_output(key: str, text: str) -> dict[str, Any]:
    global _STATE
    state = dict(_STATE) if _STATE is not None else empty()
    work = _work(state)
    field = str(key or "").strip()
    value = str(text or "").strip()[:MAX_REPLY_CHARS]
    if field not in {
        "grok_handoff", "gpt_work", "grok_review", "gpt_repair",
        "grok_final_review",
    }:
        return snapshot()
    work[field] = value
    stage_name = {
        "grok_handoff": "GROK PLAN",
        "gpt_work": "GPT BUILD",
        "grok_review": "GROK REVIEW",
        "gpt_repair": "GPT REPAIR",
        "grok_final_review": "GROK FINAL REVIEW",
    }[field]
    completed = list(work.get("completed") or [])
    if stage_name not in completed:
        completed.append(stage_name)
    work["completed"] = completed[-8:]
    if field in {"grok_handoff", "grok_review", "grok_final_review"}:
        work["open"] = _open_items(value)
    state["shared_memory"] = {
        **(state.get("shared_memory") or {}),
        "work": work,
    }
    _STATE = state
    return snapshot()


def set_task_result(status: str, note: str, *, open_items: list[str] | None = None) -> dict[str, Any]:
    global _STATE
    state = dict(_STATE) if _STATE is not None else empty()
    value = str(status or "INCOMPLETE").upper()
    complete = value == "COMPLETE"
    work = _work(state)
    work["phase"] = "COMPLETE" if complete else value
    work["owner"] = ""
    if open_items is not None:
        work["open"] = [str(item)[:240] for item in open_items if str(item).strip()][:8]
    state["grok"] = {**(state.get("grok") or {}), "status": "COMPLETE" if complete else value}
    state["gpt"] = {**(state.get("gpt") or {}), "status": "COMPLETE" if complete else value}
    state["merge"] = {
        "status": "COMPLETE" if complete else value,
        "note": str(note or "")[:500],
        "ready": complete,
        "light": "GO" if complete else "HOLD",
    }
    _STATE = state
    return snapshot()


def mark_dispatched(role: str) -> dict[str, Any]:
    global _STATE
    state = dict(_STATE) if _STATE is not None else empty()
    key = "gpt" if str(role or "").strip() == "GPTUI" else "grok"
    dispatched = dict(state.get("dispatched") or {})
    dispatched[key] = True
    state["dispatched"] = dispatched
    _STATE = state
    return snapshot()


def snapshot() -> dict[str, Any]:
    return dict(_STATE) if _STATE is not None else empty()


def reset() -> dict[str, Any]:
    global _STATE
    _STATE = None
    agent_flow.reset()
    return empty()


def dispatch_texts() -> dict[str, str]:
    state = snapshot()
    work = ((state.get("shared_memory") or {}).get("work") or {})
    stage = str(work.get("phase") or "")
    grok = ""
    gpt = ""
    if stage == "GROK_PLAN":
        grok = grok_plan_prompt()
    elif stage == "GPT_BUILD":
        gpt = gpt_build_prompt(str(work.get("grok_handoff") or ""))
    elif stage == "GROK_REVIEW":
        grok = grok_review_prompt(
            str(work.get("grok_handoff") or ""),
            str(work.get("gpt_work") or ""),
        )
    elif stage == "GPT_REPAIR":
        gpt = gpt_repair_prompt(
            str(work.get("grok_handoff") or ""),
            str(work.get("gpt_work") or ""),
            str(work.get("grok_review") or ""),
        )
    elif stage == "GROK_FINAL_REVIEW":
        gpt_work = str(work.get("gpt_work") or "") + "\n\nGPTUI repair:\n" + str(
            work.get("gpt_repair") or ""
        )
        grok = grok_review_prompt(
            str(work.get("grok_handoff") or ""),
            gpt_work,
            final_after_repair=True,
        )
    return {"grok": grok, "gpt": gpt}
