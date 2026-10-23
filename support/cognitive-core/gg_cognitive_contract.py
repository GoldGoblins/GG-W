from __future__ import annotations

import json
import re

SCHEMA_ID = "gg.cognitive-task-envelope.v1"
FIELDS = frozenset({
    "schema", "task_id", "origin_id", "state", "original_expression",
    "current_interpretation", "ready_core",
})
READY_FIELDS = frozenset({
    "owner", "goal", "expected_value", "scope", "forbidden_scope",
    "risk_class", "stop_conditions", "expected_artifacts",
    "acceptance_criteria",
})
LIST_FIELDS = frozenset({
    "scope", "forbidden_scope", "stop_conditions", "expected_artifacts",
    "acceptance_criteria",
})
STATES = ("INTAKE", "CLARIFYING", "READY_FOR_CONTROL", "BLOCKED")
RISK_CLASSES = ("GREEN", "YELLOW", "RED")
ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
ID_RE = re.compile(ID_PATTERN)
EDGES = frozenset({
    ("INTAKE", "CLARIFYING"),
    ("INTAKE", "READY_FOR_CONTROL"),
    ("INTAKE", "BLOCKED"),
    ("CLARIFYING", "CLARIFYING"),
    ("CLARIFYING", "READY_FOR_CONTROL"),
    ("CLARIFYING", "BLOCKED"),
    ("BLOCKED", "BLOCKED"),
    ("READY_FOR_CONTROL", "READY_FOR_CONTROL"),
})


class ContractError(ValueError):
    pass


def _exact(value, fields, label):
    if type(value) is not dict or frozenset(value) != fields:
        raise ContractError(label + " fields/type invalid")
    return value


def _text(value, label, maximum):
    if type(value) is not str:
        raise ContractError(label + " must be string")
    if not 1 <= len(value) <= maximum or value.strip() == "":
        raise ContractError(label + " text invalid")
    return value


def _identifier(value, label):
    if type(value) is not str or ID_RE.fullmatch(value) is None:
        raise ContractError(label + " invalid")
    return value


def _items(value, label):
    if type(value) is not list or len(value) > 64:
        raise ContractError(label + " list invalid")
    seen = set()
    for index, item in enumerate(value):
        item = _text(item, f"{label}[{index}]", 1024)
        if item in seen:
            raise ContractError(label + " duplicates")
        seen.add(item)


def _ready(value):
    value = _exact(value, READY_FIELDS, "ready_core")
    _text(value["owner"], "owner", 128)
    _text(value["goal"], "goal", 4096)
    _text(value["expected_value"], "expected_value", 4096)
    if value["risk_class"] not in RISK_CLASSES:
        raise ContractError("risk_class invalid")
    for field in LIST_FIELDS:
        _items(value[field], field)


def validate_envelope(value):
    value = _exact(value, FIELDS, "envelope")
    if value["schema"] != SCHEMA_ID:
        raise ContractError("schema invalid")
    _identifier(value["task_id"], "task_id")
    _identifier(value["origin_id"], "origin_id")
    _text(value["original_expression"], "original_expression", 32768)

    state = value["state"]
    if state not in STATES:
        raise ContractError("state invalid")

    current = value["current_interpretation"]
    ready = value["ready_core"]
    if current is not None:
        _text(current, "current_interpretation", 32768)

    if state in {"INTAKE", "BLOCKED"}:
        if ready is not None:
            raise ContractError(state + " requires ready_core=null")
    elif state == "CLARIFYING":
        if current is None or ready is not None:
            raise ContractError("CLARIFYING state invalid")
    elif state == "READY_FOR_CONTROL":
        if current is None:
            raise ContractError("READY_FOR_CONTROL needs interpretation")
        _ready(ready)
    return value


def canonicalize_envelope(value):
    validate_envelope(value)
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def validate_transition(previous, current):
    validate_envelope(previous)
    validate_envelope(current)
    for field in ("schema", "task_id", "origin_id", "original_expression"):
        if previous[field] != current[field]:
            raise ContractError(field + " immutable")
    edge = (previous["state"], current["state"])
    if edge not in EDGES:
        raise ContractError("transition forbidden")
    if previous["state"] in {"BLOCKED", "READY_FOR_CONTROL"}:
        if canonicalize_envelope(previous) != canonicalize_envelope(current):
            raise ContractError("terminal state permits identical no-op only")


def _s(maximum):
    return {
        "type": "string", "minLength": 1, "maxLength": maximum,
        "pattern": r".*\S.*",
    }


def _array():
    return {
        "type": "array", "minItems": 0, "maxItems": 64,
        "uniqueItems": True, "items": _s(1024),
    }


def _ready_schema():
    properties = {
        "owner": _s(128),
        "goal": _s(4096),
        "expected_value": _s(4096),
        "risk_class": {"type": "string", "enum": list(RISK_CLASSES)},
    }
    properties.update({field: _array() for field in LIST_FIELDS})
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(READY_FIELDS),
        "properties": properties,
    }


def schema_document():
    nullable_text = {"anyOf": [{"type": "null"}, _s(32768)]}
    state_rules = []
    for state in ("INTAKE", "BLOCKED"):
        state_rules.append({
            "if": {"properties": {"state": {"const": state}}},
            "then": {"properties": {"ready_core": {"type": "null"}}},
        })
    state_rules.extend([
        {
            "if": {"properties": {"state": {"const": "CLARIFYING"}}},
            "then": {"properties": {
                "current_interpretation": _s(32768),
                "ready_core": {"type": "null"},
            }},
        },
        {
            "if": {"properties": {"state": {"const": "READY_FOR_CONTROL"}}},
            "then": {"properties": {
                "current_interpretation": _s(32768),
                "ready_core": {"$ref": "#/$defs/ready_core"},
            }},
        },
    ])
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "GG Cognitive Task Envelope v1",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(FIELDS),
        "properties": {
            "schema": {"type": "string", "const": SCHEMA_ID},
            "task_id": {
                "type": "string", "minLength": 1, "maxLength": 128,
                "pattern": ID_PATTERN,
            },
            "origin_id": {
                "type": "string", "minLength": 1, "maxLength": 128,
                "pattern": ID_PATTERN,
            },
            "state": {"type": "string", "enum": list(STATES)},
            "original_expression": _s(32768),
            "current_interpretation": nullable_text,
            "ready_core": {
                "anyOf": [
                    {"type": "null"},
                    {"$ref": "#/$defs/ready_core"},
                ]
            },
        },
        "$defs": {"ready_core": _ready_schema()},
        "allOf": state_rules,
    }
