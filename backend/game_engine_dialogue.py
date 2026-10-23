"""Bounded authored dialogue trees for the authoritative GAME ENGINE.

Dialogue is a small state machine, not a text decoration.  The selected NPC,
current node and choices are persisted, while effects are returned to the host
for atomic application to quests, reputation, memories and other simulation
contracts.  This keeps prose data-driven without allowing a renderer to mutate
the world by itself.
"""

from __future__ import annotations

import copy
import math
from typing import Any


SCHEMA = "gg.game-engine.dialogue.v1"
VERSION = 1
MAX_TREES = 32
MAX_NODES = 16
MAX_CHOICES = 6
MAX_HISTORY = 24
MAX_TEXT = 240


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, default: str = "", limit: int = 96) -> str:
    return str(value or default).strip()[:limit]


def catalog() -> dict[str, dict[str, Any]]:
    """Return the starter island's authored conversations."""
    return {
        "npc-guardian-01": {
            "id": "npc-guardian-01",
            "speaker": "Brann Tidewatch",
            "start": "start",
            "nodes": {
                "start": {
                    "id": "start",
                    "text": "The tide left more than shells on this shore. Something hungry is moving between the rocks.",
                    "choices": [
                        {
                            "id": "shoreline-duty",
                            "label": "Ask what needs doing",
                            "text": "I will secure the shoreline.",
                            "next": "shoreline-duty",
                            "effects": [
                                {
                                    "kind": "ACCEPT_QUEST",
                                    "quest_id": "quest.shoreline-first",
                                },
                                {"kind": "RELATIONSHIP", "amount": 0.08},
                            ],
                        },
                        {
                            "id": "shoreline-report",
                            "label": "Report the shoreline",
                            "text": "I have news from the shoreline.",
                            "next": "shoreline-report",
                            "effects": [
                                {
                                    "kind": "ACCEPT_QUEST",
                                    "quest_id": "quest.shoreline-report",
                                },
                                {
                                    "kind": "QUEST_EVENT",
                                    "event_kind": "TALK",
                                    "choice_id": "shoreline-report",
                                },
                            ],
                        },
                        {
                            "id": "leave",
                            "label": "Leave",
                            "text": "Keep your eyes open, traveler.",
                            "next": "end",
                        },
                    ],
                },
                "shoreline-duty": {
                    "id": "shoreline-duty",
                    "text": "Good. Bring proof, not promises. The island remembers who protects it.",
                    "choices": [
                        {
                            "id": "leave",
                            "label": "Go",
                            "text": "I am on my way.",
                            "next": "end",
                        },
                    ],
                },
                "shoreline-report": {
                    "id": "shoreline-report",
                    "text": "A report is worth more than a rumor. I will mark this in the watch ledger.",
                    "choices": [
                        {
                            "id": "leave",
                            "label": "Close the ledger",
                            "text": "Until next time.",
                            "next": "end",
                        },
                    ],
                },
                "end": {
                    "id": "end",
                    "text": "The guardian returns to the watch.",
                    "choices": [],
                },
            },
        },
        "npc-wanderer-01": {
            "id": "npc-wanderer-01",
            "speaker": "Mira Saltwake",
            "start": "start",
            "nodes": {
                "start": {
                    "id": "start",
                    "text": "I have seen better gear turn a frightened scavenger into a survivor. What are you carrying?",
                    "choices": [
                        {
                            "id": "better-kit",
                            "label": "Show me the better kit",
                            "text": "I will find or make something rare.",
                            "next": "better-kit",
                            "effects": [
                                {
                                    "kind": "ACCEPT_QUEST",
                                    "quest_id": "quest.better-kit",
                                },
                                {"kind": "RELATIONSHIP", "amount": 0.06},
                            ],
                        },
                        {
                            "id": "runes",
                            "label": "Ask about runes",
                            "text": "How do you make gear grow with you?",
                            "next": "runes",
                        },
                        {
                            "id": "leave",
                            "label": "Leave",
                            "text": "Safe roads.",
                            "next": "end",
                        },
                    ],
                },
                "better-kit": {
                    "id": "better-kit",
                    "text": "Find a piece with a story. Socket it carefully; a rushed enchantment is just expensive scrap.",
                    "choices": [
                        {
                            "id": "leave",
                            "label": "Search the island",
                            "text": "I will return with something worth keeping.",
                            "next": "end",
                        },
                    ],
                },
                "runes": {
                    "id": "runes",
                    "text": "A socket is a promise. The item, the order and the material all matter.",
                    "choices": [
                        {
                            "id": "leave",
                            "label": "Remember that",
                            "text": "I will not waste the next socket.",
                            "next": "end",
                        },
                    ],
                },
                "end": {
                    "id": "end",
                    "text": "Mira turns back toward the next glint in the sand.",
                    "choices": [],
                },
            },
        },
        "generic": {
            "id": "generic",
            "speaker": "Island resident",
            "start": "start",
            "nodes": {
                "start": {
                    "id": "start",
                    "text": "The island is busy today. Everyone is carrying a plan, even when they call it wandering.",
                    "choices": [
                        {
                            "id": "ask-life",
                            "label": "Ask about the day",
                            "text": "What are you working on?",
                            "next": "day",
                            "effects": [{"kind": "RELATIONSHIP", "amount": 0.03}],
                        },
                        {
                            "id": "leave",
                            "label": "Leave",
                            "text": "Good luck out there.",
                            "next": "end",
                        },
                    ],
                },
                "day": {
                    "id": "day",
                    "text": "Food, shelter, a little luck. The simple things keep a world alive.",
                    "choices": [
                        {
                            "id": "leave",
                            "label": "Continue",
                            "text": "I will remember that.",
                            "next": "end",
                        },
                    ],
                },
                "end": {
                    "id": "end",
                    "text": "The resident returns to the day's work.",
                    "choices": [],
                },
            },
        },
    }


def _effect(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get("kind"), limit=32).upper()
    if not kind:
        return None
    row: dict[str, Any] = {"kind": kind}
    for key in ("quest_id", "event_kind", "choice_id", "faction_id"):
        value = _text(raw.get(key), limit=96)
        if value:
            row[key] = value
    if "amount" in raw:
        row["amount"] = round(max(-1.0, min(1.0, _safe_float(raw.get("amount")))), 4)
    return row


def _choice(raw: Any, choice_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    wanted = _text(raw.get("id"), choice_id, 48)
    if not wanted:
        return None
    effects = raw.get("effects", [])
    return {
        "id": wanted,
        "label": _text(raw.get("label"), wanted, 96),
        "text": _text(raw.get("text"), "", MAX_TEXT),
        "next": _text(raw.get("next"), "end", 48),
        "effects": [
            value
            for value in (_effect(item) for item in effects[:MAX_CHOICES])
            if isinstance(value, dict)
        ] if isinstance(effects, list) else [],
    }


def _node(raw: Any, node_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    choices = raw.get("choices", [])
    normalized_choices = [
        value
        for value in (_choice(item, f"choice-{index:02d}") for index, item in enumerate(choices[:MAX_CHOICES]))
        if isinstance(value, dict)
    ] if isinstance(choices, list) else []
    return {
        "id": _text(raw.get("id"), node_id, 48),
        "text": _text(raw.get("text"), "", MAX_TEXT),
        "choices": normalized_choices,
    }


def normalized_catalog(raw: Any = None) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else catalog()
    result: dict[str, dict[str, Any]] = {}
    for tree_id, raw_tree in list(source.items())[:MAX_TREES]:
        if not isinstance(raw_tree, dict):
            continue
        wanted = _text(raw_tree.get("id"), tree_id, 64)
        nodes_source = raw_tree.get("nodes", {})
        nodes: dict[str, dict[str, Any]] = {}
        if isinstance(nodes_source, dict):
            for node_id, raw_node in list(nodes_source.items())[:MAX_NODES]:
                normalized = _node(raw_node, _text(node_id, limit=48))
                if normalized is not None and normalized["id"] not in nodes:
                    nodes[normalized["id"]] = normalized
        if not nodes:
            continue
        start = _text(raw_tree.get("start"), "start", 48)
        if start not in nodes:
            start = sorted(nodes)[0]
        result[wanted] = {
            "id": wanted,
            "speaker": _text(raw_tree.get("speaker"), "Island resident", 96),
            "start": start,
            "nodes": nodes,
        }
    if "generic" not in result:
        fallback = normalized_catalog(catalog()) if raw is not None else {}
        if "generic" in fallback:
            result["generic"] = fallback["generic"]
    return dict(list(result.items())[:MAX_TREES])


def new_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "active": {"npc_id": "", "tree_id": "", "node_id": "", "turn": 0},
        "history": [],
        "last_result": {},
        "revision": 0,
    }


def _active(raw: Any) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "npc_id": _text(row.get("npc_id"), limit=64),
        "tree_id": _text(row.get("tree_id"), limit=64),
        "node_id": _text(row.get("node_id"), limit=48),
        "turn": max(0, min(1_000_000, _safe_int(row.get("turn")))),
    }


def normalize_state(raw: Any) -> dict[str, Any]:
    base = new_state()
    source = raw if isinstance(raw, dict) else {}
    base["active"] = _active(source.get("active"))
    history = source.get("history", [])
    if isinstance(history, list):
        base["history"] = [
            {
                "npc_id": _text(item.get("npc_id"), limit=64),
                "choice_id": _text(item.get("choice_id"), limit=48),
                "node_id": _text(item.get("node_id"), limit=48),
                "time_s": round(max(0.0, _safe_float(item.get("time_s"))), 3),
            }
            for item in history[-MAX_HISTORY:]
            if isinstance(item, dict) and _text(item.get("npc_id"), limit=64)
        ]
    if isinstance(source.get("last_result"), dict):
        base["last_result"] = copy.deepcopy(source["last_result"])
    base["revision"] = max(0, _safe_int(source.get("revision")))
    return base


def _tree_for(definitions: dict[str, dict[str, Any]], npc_id: str) -> dict[str, Any] | None:
    return definitions.get(npc_id) or definitions.get("generic")


def _node_view(tree: dict[str, Any], node_id: str) -> dict[str, Any]:
    nodes = tree.get("nodes", {}) if isinstance(tree.get("nodes"), dict) else {}
    node = nodes.get(node_id) or nodes.get(str(tree.get("start", "start"))) or {}
    return {
        "id": _text(node.get("id"), "start", 48),
        "speaker": _text(tree.get("speaker"), "Island resident", 96),
        "text": _text(node.get("text"), "", MAX_TEXT),
        "choices": [
            {
                "id": _text(choice.get("id"), limit=48),
                "label": _text(choice.get("label"), limit=96),
                "text": _text(choice.get("text"), limit=MAX_TEXT),
            }
            for choice in node.get("choices", [])[:MAX_CHOICES]
            if isinstance(choice, dict)
        ],
    }


def start(
    state: dict[str, Any],
    dialogue_catalog: Any,
    npc_id: Any,
    sim_time: Any,
) -> tuple[bool, dict[str, Any]]:
    definitions = normalized_catalog(dialogue_catalog)
    wanted = _text(npc_id, limit=64)
    tree = _tree_for(definitions, wanted)
    if tree is None:
        return False, {"error": "DIALOGUE_TREE_NOT_FOUND", "npc_id": wanted}
    tree_id = str(tree.get("id", "generic"))
    active = state.setdefault("active", {})
    active.update(
        {
            "npc_id": wanted,
            "tree_id": tree_id,
            "node_id": str(tree.get("start", "start")),
            "turn": 0,
        }
    )
    result = {
        "action": "START",
        "npc_id": wanted,
        "tree_id": tree_id,
        "node": _node_view(tree, active["node_id"]),
        "effects": [],
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
    }
    state["last_result"] = copy.deepcopy(result)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return True, result


def choose(
    state: dict[str, Any],
    dialogue_catalog: Any,
    npc_id: Any,
    choice_id: Any,
    sim_time: Any,
) -> tuple[bool, dict[str, Any]]:
    definitions = normalized_catalog(dialogue_catalog)
    wanted_npc = _text(npc_id, limit=64)
    wanted_choice = _text(choice_id, limit=48)
    active = _active(state.get("active"))
    if not active.get("npc_id") or active.get("npc_id") != wanted_npc:
        return False, {
            "error": "DIALOGUE_NOT_STARTED",
            "npc_id": wanted_npc,
        }
    tree = definitions.get(str(active.get("tree_id"))) or _tree_for(definitions, wanted_npc)
    if tree is None:
        return False, {"error": "DIALOGUE_TREE_NOT_FOUND", "npc_id": wanted_npc}
    nodes = tree.get("nodes", {}) if isinstance(tree.get("nodes"), dict) else {}
    node = nodes.get(str(active.get("node_id")), {})
    choices = node.get("choices", []) if isinstance(node, dict) else []
    selected = next(
        (choice for choice in choices if isinstance(choice, dict) and str(choice.get("id")) == wanted_choice),
        None,
    )
    if not isinstance(selected, dict):
        return False, {
            "error": "DIALOGUE_CHOICE_UNKNOWN",
            "npc_id": wanted_npc,
            "node_id": str(active.get("node_id", "")),
            "choice_id": wanted_choice,
        }
    next_node = _text(selected.get("next"), "end", 48)
    if next_node not in nodes:
        next_node = "end" if "end" in nodes else str(active.get("node_id", "start"))
    active["node_id"] = next_node
    active["turn"] = max(0, _safe_int(active.get("turn"))) + 1
    state["active"] = active
    result = {
        "action": "CHOICE",
        "npc_id": wanted_npc,
        "tree_id": str(tree.get("id", "generic")),
        "node": _node_view(tree, next_node),
        "choice_id": wanted_choice,
        "player_text": _text(selected.get("text"), limit=MAX_TEXT),
        "effects": copy.deepcopy(selected.get("effects", [])[:MAX_CHOICES]),
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
    }
    state.setdefault("history", []).append(
        {
            "npc_id": wanted_npc,
            "choice_id": wanted_choice,
            "node_id": next_node,
            "time_s": result["time_s"],
        }
    )
    state["history"] = state["history"][-MAX_HISTORY:]
    state["last_result"] = copy.deepcopy(result)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return True, result


def view(state: Any, dialogue_catalog: Any = None) -> dict[str, Any]:
    definitions = normalized_catalog(dialogue_catalog)
    source = normalize_state(state)
    active = source.get("active", {})
    node = {}
    if isinstance(active, dict) and active.get("npc_id"):
        tree = definitions.get(str(active.get("tree_id"))) or _tree_for(
            definitions,
            str(active.get("npc_id")),
        )
        if isinstance(tree, dict):
            node = _node_view(tree, str(active.get("node_id", tree.get("start", "start"))))
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "open": bool(node),
        "active": copy.deepcopy(active),
        "node": node,
        "history": copy.deepcopy(source.get("history", [])[-MAX_HISTORY:]),
        "last_result": copy.deepcopy(source.get("last_result", {})),
        "revision": max(0, _safe_int(source.get("revision"))),
        "trees": len(definitions),
        "policy": "AUTHORED_CHOICE_GRAPH_EFFECTS_APPLIED_BY_AUTHORITATIVE_HOST",
    }
