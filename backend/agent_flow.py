"""One graph for Ng's four agentic patterns. Seats, not four brains.

DarkFactorr / Andrew Ng: Reflection, Tool Use, Planning, Multi-Agent
as one flow with typed handoffs and a user gate at every stage.

0xCodez: hand off a task packet, not a chat paste; the reviewer is never
the author. Raft-style extra companies and extra brains stay out.

PARALLEL_AGENT_BRAIN stays FORBIDDEN. Front Man is code. ja/nej still
gates yellow and red in chat.
"""

from __future__ import annotations

from typing import Any

from backend import thought_desk


SCHEMA = "gg.agent-flow.v1"
ACTION_AUTHORITY = "NONE"
PARALLEL_AGENT_BRAIN = "FORBIDDEN"
FLAT_MODEL_COMMAND_LOOP = "FORBIDDEN"
PARALLEL_EXECUTION = "BOUNDED_ADAPTIVE_DAG"

STAGES = ("ASK", "PLAN", "TOOLS", "BUILD", "REFLECT", "GATE")
ROLES = {
    "ASK": "USER",
    "PLAN": "ARCHITECT",
    "TOOLS": "LEAD",
    "BUILD": "DEV",
    "REFLECT": "CRITIC",
    "GATE": "FRONT_MAN",
}
HANDOFF = {
    "ASK": "PLAN",
    "PLAN": "TOOLS",
    "TOOLS": "BUILD",
    "BUILD": "REFLECT",
    "REFLECT": "GATE",
    "GATE": "USER",
}

_HOUSE_TOOLS = ("READ", "SEARCH", "GIT", "TEST", "RUN")
_STATE: dict[str, Any] | None = None


def empty() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "ask": "",
        "packets": [],
        "stages": [
            {
                "id": stage,
                "role": ROLES[stage],
                "pattern": {
                    "ASK": "user",
                    "PLAN": "planning",
                    "TOOLS": "tool_use",
                    "BUILD": "multi_agent",
                    "REFLECT": "reflection",
                    "GATE": "front_man",
                }[stage],
                "handoff_to": HANDOFF[stage],
            }
            for stage in STAGES
        ],
        "front_man": {
            "id": "FRONT_MAN",
            "light": "HOLD",
            "reasons": ["NO_RUN"],
            "in_code": True,
        },
        "user_gates": [],
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "diamond": {
            "fan_out": "INDEPENDENT_JOBS",
            "reduce": "CODE",
            "verify": "TEST",
            "synthesize": "ONE_MOTOR",
        },
        "verifier_context": "FRESH",
        "fake_edge_test": "Does the next step actually read the previous output?",
        "parallel_execution": PARALLEL_EXECUTION,
        "flat_model_command_loop": FLAT_MODEL_COMMAND_LOOP,
        "model_agents": False,
        "action_authority": ACTION_AUTHORITY,
        "hint": "One task, typed packets, critic is not the author. Not four chat windows.",
    }


def _packet(
    stage: str,
    body: str,
    *,
    author: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "kind": stage,
        "from": author,
        "to": HANDOFF[stage],
        "role": ROLES[stage],
        "body": body,
        "user_sees": True,
    }
    if extra:
        row.update(extra)
    return row


def run(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    board = thought_desk.sit(raw)
    seats = board.get("seats") or {}
    man = board.get("front_man") or {}
    intent = seats.get("intent") or {}
    evidence = seats.get("evidence") or {}
    builder = seats.get("builder") or {}
    critic = seats.get("critic") or {}
    risk = seats.get("risk") or {}

    ask = str(intent.get("ask") or raw or "(empty)")
    moves = [str(item) for item in (builder.get("moves") or []) if str(item).strip()]
    files = [str(item) for item in (evidence.get("named_files") or []) if str(item).strip()]
    flags = [str(item) for item in (critic.get("flags") or []) if str(item).strip()]
    work = bool(intent.get("work"))
    tools = list(_HOUSE_TOOLS) if work else []
    if files and "READ" not in tools:
        tools = ["READ"] + tools

    packets = [
        _packet("ASK", ask, author="USER"),
        _packet(
            "PLAN",
            " · ".join(moves) if moves else "no bounded steps yet",
            author="ARCHITECT",
            extra={"moves": moves[:4], "mode": str(builder.get("mode") or "TALK")},
        ),
        _packet(
            "TOOLS",
            "house tools: " + (", ".join(tools) if tools else "none")
            + ((" · files " + ", ".join(files[:4])) if files else ""),
            author="LEAD",
            extra={"tools": tools, "files": files[:6], "grants": "NONE"},
        ),
        _packet(
            "BUILD",
            " · ".join(moves) if moves else "talk only",
            author="DEV",
            extra={"author_role": "DEV"},
        ),
        _packet(
            "REFLECT",
            (critic.get("falsify") or "What would make this plan wrong?")
            + ((" · flags " + ",".join(flags)) if flags else ""),
            author="CRITIC",
            extra={"author_role": "CRITIC", "author_is_builder": False, "flags": flags},
        ),
        _packet(
            "GATE",
            str(man.get("light") or "HOLD")
            + " · "
            + ", ".join(str(item) for item in (man.get("reasons") or [])[:4]),
            author="FRONT_MAN",
            extra={"light": str(man.get("light") or "HOLD")},
        ),
    ]

    user_gates = [
        {
            "after": packet["kind"],
            "to": packet["to"],
            "note": packet["body"],
            "needs_chat_ja": str(risk.get("light") or "") in {"YELLOW", "RED"},
        }
        for packet in packets
    ]

    state = {
        "schema": SCHEMA,
        "ask": ask,
        "packets": packets,
        "stages": empty()["stages"],
        "front_man": {
            "id": "FRONT_MAN",
            "light": str(man.get("light") or "HOLD"),
            "reasons": list(man.get("reasons") or []),
            "in_code": True,
            "risk": str(risk.get("light") or "GREEN"),
        },
        "user_gates": user_gates,
        "reviewer_is_author": False,
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "parallel_execution": PARALLEL_EXECUTION,
        "execution": dict(board.get("execution") or {}),
        "flat_model_command_loop": FLAT_MODEL_COMMAND_LOOP,
        "model_agents": False,
        "action_authority": ACTION_AUTHORITY,
        "loops": int(board.get("loops") or 1),
        "hint": empty()["hint"],
    }
    global _STATE
    _STATE = state
    return state


def snapshot() -> dict[str, Any]:
    return dict(_STATE) if _STATE is not None else empty()


def reset() -> dict[str, Any]:
    global _STATE
    _STATE = None
    return empty()
