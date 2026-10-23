"""Typed System One decisions for GG AI Desktop.

Jev (TypeSafe) is a System One model: state plus typed questions in,
Choice / Score / Noul out, in tens to hundreds of milliseconds.  It never
writes prose.  This contract gives GROK TUI and GPTUI the same shape so
routing, gates and motor hints do not wait on a chat completion.

The local backend is deterministic and offline.  It never grants authority,
never calls the network, and never logs secrets.  A hosted Jev adapter can
be added later without changing the question schema.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Mapping


SCHEMA = "gg.ai-desktop.system-one.v1"
LOCAL_MODEL = "gg-system-one-local"
MAX_STATE_CHARS = 24_000
MAX_QUESTIONS = 32
MAX_OPTIONS = 32
MAX_INSTRUCTION_CHARS = 480
BACKEND_LOCAL = "LOCAL_DETERMINISTIC"
PRIMITIVES = frozenset({"noul", "choice", "score"})
_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ-]{2,}", re.UNICODE)

_CODE_HINTS = frozenset(
    {
        "koda",
        "kod",
        "fixa",
        "implement",
        "patch",
        "qml",
        "python",
        "test",
        "filen",
        "skriv",
        "ändra",
        "edit",
        "function",
        "diff",
        "bug",
        "krash",
        "crash",
    }
)
_RESEARCH_HINTS = frozenset(
    {
        "research",
        "förklara",
        "jämför",
        "källa",
        "varför",
        "youtube",
        "video",
        "jev",
        "vad är",
        "ta reda",
    }
)
_OPERATE_HINTS = frozenset(
    {
        "öppna",
        "byt",
        "visa",
        "web",
        "webb",
        "blender",
        "terminal",
        "ext",
        "site",
        "sajt",
        "game",
        "spelmotor",
        "media",
        "youtube",
    }
)
_WRITE_HINTS = frozenset(
    {
        "ändra",
        "skriv",
        "fixa",
        "patch",
        "implement",
        "ta bort",
        "lägg till",
        "ersätt",
        "apply",
        "spara",
    }
)
_NETWORK_HINTS = frozenset(
    {
        "nät",
        "nätverk",
        "youtube",
        "http",
        "https",
        "web",
        "webb",
        "api",
        "ladda ner",
        "download",
        "fetch",
        "openrouter",
        "typesafe",
        "jev",
    }
)
_APPROVAL_HINTS = frozenset(
    {"ja", "yes", "nej", "no", "ok", "klar", "fortsätt", "prova"}
)
_GROK_HINTS = frozenset(
    {
        "qml",
        "blender",
        "visual",
        "desktop",
        "game",
        "spel",
        "ext",
        "ui",
        "yta",
        "mus",
    }
)
_GPT_HINTS = frozenset(
    {
        "kontrakt",
        "plan",
        "arkitektur",
        "dokument",
        "resonera",
        "policy",
        "schema",
        "research",
    }
)
_SURFACE_HINTS = {
    "GAME_ENGINE": frozenset({"game", "spelmotor", "hut", "palm", "hydda", "brygga"}),
    "EXTERNAL": frozenset({"blender", "ext"}),
    "WEB": frozenset({"web", "webb", "youtube", "browser"}),
    "SITE": frozenset({"sajt", "site", "wordpress", "hemsida"}),
    "CODE": frozenset({"qml", "python", "kod", "filen", "patch"}),
    "MEDIA": frozenset({"youtube", "media", "video", "musik"}),
    "TERMINAL": frozenset({"terminal", "konsol", "pty"}),
    "TMOG": frozenset({"tmog"}),
    "OSINT": frozenset({"osint"}),
    "RESEARCH": frozenset({"research", "evidens", "källa"}),
    "DRAW": frozenset({"rita", "draw", "canvas"}),
    "NODES": frozenset({"nodes", "noder"}),
}


class SystemOneError(ValueError):
    """Fail-closed System One request error."""


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit]
    return text


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _overlap(state: set[str], probe: str) -> float:
    wanted = _tokens(probe)
    if not wanted:
        return 0.0
    return len(state & wanted) / float(len(wanted))


def _softmax(scores: list[float]) -> list[float]:
    if not scores:
        return []
    peak = max(scores)
    weights = [math.exp(min(12.0, score - peak)) for score in scores]
    total = sum(weights) or 1.0
    return [weight / total for weight in weights]


def _normalize_question(question_id: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    wanted = str(question_id or "").strip()[:48]
    if not wanted:
        raise SystemOneError("SYSTEM_ONE_QUESTION_ID_EMPTY")
    kind = str(raw.get("type") or "").strip().lower()
    if kind not in PRIMITIVES:
        raise SystemOneError("SYSTEM_ONE_TYPE_UNKNOWN:" + wanted)
    instructions = _text(raw.get("instructions"), MAX_INSTRUCTION_CHARS)
    if not instructions:
        raise SystemOneError("SYSTEM_ONE_INSTRUCTIONS_EMPTY:" + wanted)
    criteria = raw.get("criteria")
    options: dict[str, str] = {}
    if isinstance(criteria, Mapping):
        for key, value in list(criteria.items())[:MAX_OPTIONS]:
            label = str(key or "").strip()[:48]
            if label:
                options[label] = _text(value, MAX_INSTRUCTION_CHARS)
    if kind == "choice" and len(options) < 2:
        raise SystemOneError("SYSTEM_ONE_CHOICE_NEEDS_OPTIONS:" + wanted)
    if kind == "score" and len(options) < 2:
        raise SystemOneError("SYSTEM_ONE_SCORE_NEEDS_LEVELS:" + wanted)
    if kind == "score" and len(options) > 10:
        raise SystemOneError("SYSTEM_ONE_SCORE_TOO_MANY_LEVELS:" + wanted)
    return {
        "id": wanted,
        "type": kind,
        "instructions": instructions,
        "criteria": options,
    }


def _noul(state: set[str], question: dict[str, Any], extra: set[str]) -> dict[str, Any]:
    probe = question["instructions"] + " " + " ".join(question["criteria"].values())
    hit = _overlap(state, probe) + (0.55 if state & extra else 0.0)
    yes = min(0.97, 0.06 + hit)
    return {"type": "noul", "noul": round(yes, 4)}


def _choice(state: set[str], question: dict[str, Any]) -> dict[str, Any]:
    labels = list(question["criteria"].items())
    scores = []
    for label, description in labels:
        probe = label.replace("_", " ") + " " + description
        scores.append(_overlap(state, probe) + (0.15 if label.lower() in state else 0.0))
    if max(scores) <= 0.0:
        scores = [0.15 if index == 0 else 0.05 for index in range(len(labels))]
    probs = _softmax([score * 8.0 for score in scores])
    winner = max(range(len(labels)), key=lambda index: probs[index])
    distribution = {
        labels[index][0]: round(probs[index], 4) for index in range(len(labels))
    }
    return {
        "type": "choice",
        "choice": labels[winner][0],
        "confidence": round(probs[winner], 4),
        "probs": distribution,
    }


def _score(state: set[str], question: dict[str, Any]) -> dict[str, Any]:
    labels = list(question["criteria"].items())
    raw = []
    for index, (label, description) in enumerate(labels):
        probe = label.replace("_", " ") + " " + description
        raw.append(_overlap(state, probe) + (index * 0.04))
    probs = _softmax([score * 6.0 for score in raw])
    value = sum(index * probs[index] for index in range(len(labels)))
    winner = min(range(len(labels)), key=lambda index: abs(index - value))
    distribution = {
        labels[index][0]: round(probs[index], 4) for index in range(len(labels))
    }
    return {
        "type": "score",
        "score": round(value, 4),
        "level": labels[winner][0],
        "confidence": round(probs[winner], 4),
        "probs": distribution,
    }


def evaluate(
    state: Any,
    questions: Mapping[str, Any],
    *,
    model: str = LOCAL_MODEL,
) -> dict[str, Any]:
    """Answer typed questions about one state.  Local, parallel, no prose."""
    started = time.perf_counter()
    blob = _text(state, MAX_STATE_CHARS)
    if not blob:
        raise SystemOneError("SYSTEM_ONE_STATE_EMPTY")
    if not isinstance(questions, Mapping) or not questions:
        raise SystemOneError("SYSTEM_ONE_QUESTIONS_EMPTY")
    if len(questions) > MAX_QUESTIONS:
        raise SystemOneError("SYSTEM_ONE_TOO_MANY_QUESTIONS")
    tokens = _tokens(blob)
    answers: dict[str, Any] = {}
    for question_id, raw in questions.items():
        if not isinstance(raw, Mapping):
            raise SystemOneError("SYSTEM_ONE_QUESTION_NOT_OBJECT:" + str(question_id))
        question = _normalize_question(str(question_id), raw)
        kind = question["type"]
        extra = set()
        lowered_id = question["id"].lower()
        if "write" in lowered_id:
            extra = _WRITE_HINTS
        elif "network" in lowered_id or "net" in lowered_id:
            extra = _NETWORK_HINTS
        elif "approv" in lowered_id:
            extra = _APPROVAL_HINTS
        if kind == "noul":
            answers[question["id"]] = _noul(tokens, question, extra)
        elif kind == "choice":
            answers[question["id"]] = _choice(tokens, question)
        else:
            answers[question["id"]] = _score(tokens, question)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "schema": SCHEMA,
        "model": str(model or LOCAL_MODEL),
        "backend": BACKEND_LOCAL,
        "latency_ms": round(elapsed_ms, 3),
        "answers": answers,
        "authority": "NONE",
        "network": "NONE",
    }


TURN_QUESTIONS: dict[str, dict[str, Any]] = {
    "task_kind": {
        "type": "choice",
        "instructions": "What is the user trying to do in this chat turn?",
        "criteria": {
            "chat": "Greeting, status, thanks, small talk",
            "code": "Edit, implement, fix, patch, QML, Python, tests",
            "research": "Look up, explain, compare, watch a video, sources",
            "operate": "Open a surface, drive WEB, Blender, terminal or site",
            "decide": "Yes/no, pick an option, approve or reject",
        },
    },
    "surface": {
        "type": "choice",
        "instructions": "Which GG AI Desktop surface should be in front, if any?",
        "criteria": {
            "none": "Stay on the current surface",
            "CODE": "Code editor",
            "WEB": "Visible web pane",
            "SITE": "Local or production site",
            "GAME_ENGINE": "Game engine playground",
            "EXTERNAL": "Blender / EXT",
            "MEDIA": "YouTube, radio, TV, emulator",
            "TERMINAL": "Terminal grid",
            "RESEARCH": "Research desk",
        },
    },
    "motor_hint": {
        "type": "choice",
        "instructions": "Which motor is the better first worker? Hint only, not a switch command.",
        "criteria": {
            "GROK": "Visual desktop, QML, game, Blender, live UI",
            "GPTUI": "Long reasoning, contracts, docs, planning",
            "EITHER": "Either motor can take the turn",
        },
    },
    "needs_write": {
        "type": "noul",
        "instructions": "Does the user ask to change files or apply a patch?",
    },
    "needs_network": {
        "type": "noul",
        "instructions": "Does the user ask to use the network, YouTube, the web, or a remote API?",
    },
    "is_approval": {
        "type": "noul",
        "instructions": "Is the user answering yes or no to a waiting approval?",
    },
    "is_irreversible": {
        "type": "noul",
        "instructions": "Would acting now change production, credentials, deploy, or live site?",
    },
    "next_worker": {
        "type": "choice",
        "instructions": "Which worker should act next? Hint only. Code still executes.",
        "criteria": {
            "none": "No worker. Just talk.",
            "research": "Gather evidence before writing",
            "write": "Draft or edit from enough evidence",
            "operate": "Drive a live surface the user named",
            "review": "Stop for the user to look",
        },
    },
    "urgency": {
        "type": "score",
        "instructions": "How blocked is the user right now?",
        "criteria": {
            "0": "Casual chat",
            "1": "Normal work",
            "2": "Repeating a failure or waiting on a live pane",
            "3": "Broken live surface, crash, or missing window",
        },
    },
}


def _boost_turn(state: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply GG-specific lexicon so the local judge matches the desktop."""
    tokens = _tokens(state)
    answers = payload["answers"]
    task = answers.get("task_kind")
    if isinstance(task, dict) and task.get("type") == "choice":
        scores = {
            "chat": 0.2,
            "code": 0.15 + (0.8 if tokens & _CODE_HINTS else 0.0),
            "research": 0.15 + (0.8 if tokens & _RESEARCH_HINTS else 0.0),
            "operate": 0.15 + (0.8 if tokens & _OPERATE_HINTS else 0.0),
            "decide": 0.15 + (0.9 if tokens <= _APPROVAL_HINTS and tokens else 0.0),
        }
        probs = _softmax(list(scores.values()))
        labels = list(scores)
        winner = max(range(len(labels)), key=lambda index: probs[index])
        answers["task_kind"] = {
            "type": "choice",
            "choice": labels[winner],
            "confidence": round(probs[winner], 4),
            "probs": {
                labels[index]: round(probs[index], 4) for index in range(len(labels))
            },
        }
    surface = answers.get("surface")
    if isinstance(surface, dict) and surface.get("type") == "choice":
        scores = {"none": 0.25}
        for name, hints in _SURFACE_HINTS.items():
            scores[name] = 0.05 + (1.2 if tokens & hints else 0.0)
        if "youtube" in tokens:
            scores["MEDIA"] = scores.get("MEDIA", 0.0) + 1.0
            scores["WEB"] = scores.get("WEB", 0.0) + 0.4
        labels = list(scores)
        probs = _softmax(list(scores.values()))
        winner = max(range(len(labels)), key=lambda index: probs[index])
        answers["surface"] = {
            "type": "choice",
            "choice": labels[winner],
            "confidence": round(probs[winner], 4),
            "probs": {
                labels[index]: round(probs[index], 4) for index in range(len(labels))
            },
        }
    motor = answers.get("motor_hint")
    if isinstance(motor, dict) and motor.get("type") == "choice":
        scores = {
            "GROK": 0.3 + (0.9 if tokens & _GROK_HINTS else 0.0),
            "GPTUI": 0.3 + (0.9 if tokens & _GPT_HINTS else 0.0),
            "EITHER": 0.35,
        }
        labels = list(scores)
        probs = _softmax(list(scores.values()))
        winner = max(range(len(labels)), key=lambda index: probs[index])
        answers["motor_hint"] = {
            "type": "choice",
            "choice": labels[winner],
            "confidence": round(probs[winner], 4),
            "probs": {
                labels[index]: round(probs[index], 4) for index in range(len(labels))
            },
        }
    task_choice = str((answers.get("task_kind") or {}).get("choice") or "")
    worker_map = {
        "chat": "none",
        "code": "write",
        "research": "research",
        "operate": "operate",
        "decide": "review",
    }
    mapped = worker_map.get(task_choice, "none")
    answers["next_worker"] = {
        "type": "choice",
        "choice": mapped,
        "confidence": float((answers.get("task_kind") or {}).get("confidence") or 0.5),
        "probs": {mapped: 1.0},
    }
    return payload


def decide_turn(
    user_text: Any,
    *,
    available_surfaces: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Fast typed snapshot of one Universal Operational Stream turn.

    ``available_surfaces`` rebuilds the Choice menu from the live desktop,
    the Browser Use idea: never decide against yesterday's buttons.
    """
    questions = dict(TURN_QUESTIONS)
    live = [
        str(item).strip()
        for item in (available_surfaces or ())
        if str(item).strip()
    ]
    if live:
        criteria = {"none": "Stay on the current surface"}
        stock = TURN_QUESTIONS["surface"]["criteria"]
        for name in live[:24]:
            criteria[name] = str(stock.get(name) or name)
        questions["surface"] = {
            "type": "choice",
            "instructions": TURN_QUESTIONS["surface"]["instructions"],
            "criteria": criteria,
        }
    payload = evaluate(user_text, questions)
    boosted = _boost_turn(str(user_text or ""), payload)
    boosted["handoff"] = handoff_packet(user_text, boosted)
    boosted["live_menu"] = live
    boosted["split"] = "LLM_WRITES SYSTEM_ONE_DECIDES CODE_EXECUTES"
    boosted["verifier"] = "TEST"
    return boosted


def keep_drop(
    query: Any,
    items: Mapping[str, str] | list[tuple[str, str]],
    *,
    threshold: float = 0.18,
) -> list[str]:
    """Relevance filter, not a summarizer.  Keep or drop; never rewrite."""
    if isinstance(items, Mapping):
        pairs = list(items.items())
    else:
        pairs = list(items)
    wanted = _tokens(str(query or ""))
    kept: list[str] = []
    for key, text in pairs[:MAX_QUESTIONS]:
        label = str(key)
        probe = label.replace("_", " ") + " " + str(text or "")
        hit = _overlap(wanted, probe)
        if label.lower() in wanted or hit >= threshold:
            kept.append(label)
    return kept


def handoff_packet(user_text: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Inspectable next-step packet.  Never an action grant."""
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    goal = " ".join(str(user_text or "").split())
    if len(goal) > 160:
        goal = goal[:157] + "…"
    irreversible = float((answers.get("is_irreversible") or {}).get("noul") or 0.0)
    return {
        "goal": goal,
        "task_kind": str((answers.get("task_kind") or {}).get("choice") or ""),
        "next_worker": str((answers.get("next_worker") or {}).get("choice") or "none"),
        "surface": str((answers.get("surface") or {}).get("choice") or "none"),
        "motor_hint": str((answers.get("motor_hint") or {}).get("choice") or "EITHER"),
        "execute": "MOTOR",
        "verify": "TEST",
        "irreversible": irreversible >= 0.55,
        "authority": "NONE",
    }


def format_compact(payload: Mapping[str, Any]) -> str:
    """One small block both motors can read without parsing prose."""
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}

    def _pick(name: str) -> str:
        row = answers.get(name) if isinstance(answers.get(name), dict) else {}
        return str(row.get("choice") or "")

    def _noul(name: str) -> str:
        row = answers.get(name) if isinstance(answers.get(name), dict) else {}
        return str(row.get("noul") or 0)

    urgency = answers.get("urgency") if isinstance(answers.get("urgency"), dict) else {}
    return "\n".join(
        [
            "[GG SYSTEM ONE]",
            "schema="
            + str(payload.get("schema") or SCHEMA)
            + " backend="
            + str(payload.get("backend") or BACKEND_LOCAL)
            + " authority=NONE",
            "task_kind="
            + _pick("task_kind")
            + " surface="
            + _pick("surface")
            + " motor_hint="
            + _pick("motor_hint")
            + " next_worker="
            + _pick("next_worker"),
            "needs_write="
            + _noul("needs_write")
            + " needs_network="
            + _noul("needs_network")
            + " is_approval="
            + _noul("is_approval")
            + " is_irreversible="
            + _noul("is_irreversible")
            + " urgency="
            + str(urgency.get("score") or 0),
            "split=LLM_WRITES SYSTEM_ONE_DECIDES CODE_EXECUTES verifier=TEST",
            "[/GG SYSTEM ONE]",
        ]
    )
