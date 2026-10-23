from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import stat
from typing import Any

SCHEMA_ID = "gg.goal-why-chain.v1"
SOURCE_TASK_SCHEMA_ID = "gg.cognitive-task-envelope.v1"
SOURCE_TASK_RUNTIME_FILENAME = "gg_cognitive_contract.py"
SOURCE_TASK_RUNTIME_PATH = "cognitive-core/gg_cognitive_contract.py"
SOURCE_TASK_RUNTIME_SHA256 = "e8824222fdb8f638f12c57f21a9b060f577e3a5ef5db8e034c9595677e03d79d"
SOURCE_TASK_SCHEMA_PATH = "cognitive-core/schemas/cognitive-task-envelope.schema.json"
SOURCE_TASK_SCHEMA_SHA256 = "e4ff0a920c8bce486253a7a4bfa7b3b24650d9d8747156a9d214f83f0283c6c9"
JSON_SCHEMA_DRAFT = "2020-12"
JSON_SCHEMA_ROLE = "DETERMINISTIC_INTEROPERABILITY_PROJECTION"
SCHEMA_ADDITIONAL_PROPERTIES = "FALSE_AT_ALL_OBJECT_LEVELS"
SOURCE_TASK_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
AMBIENT_PYTHONPATH_AUTHORITY = "FORBIDDEN"
SYS_PATH_DISCOVERY = "FORBIDDEN"
IMPORT_BY_MODULE_NAME_WITHOUT_CONTENT_BINDING = "FORBIDDEN"
FALLBACK_SOURCE_TASK_LOADER = None

ORIGINAL_INTENT_INPUT = "EXPLICIT_CALLER_ASSERTION"
ORIGINAL_INTENT_AUTOMATIC_DERIVATION = "FORBIDDEN"
ORIGINAL_INTENT_SEMANTIC_TRUTH = "NOT_VERIFIED_BY_K7-G"
CROSS_SESSION_INTENT_CONTINUITY = "NOT_THIS_SLICE"
GOAL_SUPERSESSION_HISTORY = "NOT_THIS_SLICE"
ACTIVE_SUPERSEDED_STATUS = "NOT_THIS_SLICE"
GOAL_HISTORY_PERSISTENCE = "NO"
MULTISESSION_GOAL_RECONSTRUCTION = "LATER_LAYER"
WHY_SEMANTIC_TRUTH = "NOT_INFERRED"
WHY_SEMANTIC_QUALITY = "NOT_SCORED"
TRACEABILITY_PASS_IS_MANDATE_PASS = False
ACTION_NODE_PRESENT_IS_ACTION_APPROVED = False
ACTION_AUTHORITY = "NONE"
LIVE_PERSISTENCE = "NO"

NODE_TYPES = frozenset(("ORIGINAL_INTENT", "CURRENT_TARGET", "GOAL", "SUBGOAL", "TASK", "ACTION"))
_NODE_FIELDS = frozenset({"node_id", "node_type", "parent_node_id", "why", "body"})
_NODE_SEMANTIC_FIELDS = frozenset({"node_type", "parent_node_id", "why", "body"})
_CHAIN_FIELDS = frozenset({
    "schema", "source_task_schema", "source_task_sha256",
    "source_original_expression_sha256", "task_id", "origin_id",
    "original_intent_node_id", "current_target_node_id", "task_node_id",
    "nodes",
})
_STATEMENT_BODY_FIELDS = frozenset({"statement"})
_TASK_BODY_FIELDS = frozenset({"task_id", "source_task_sha256"})
_ACTION_BODY_FIELDS = frozenset({"action_id", "description"})
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NODE_HASH_DOMAIN = b"gg.goal-why.node.v1\n"

_SCHEMA_JSON = '{"$defs":{"action_body":{"additionalProperties":false,"properties":{"action_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]{1,128}$","type":"string"},"description":{"minLength":1,"pattern":".*\\\\S.*","type":"string"}},"required":["action_id","description"],"type":"object"},"identifier":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]{1,128}$","type":"string"},"node":{"additionalProperties":false,"allOf":[{"if":{"properties":{"node_type":{"const":"ORIGINAL_INTENT"}},"required":["node_type"]},"then":{"properties":{"body":{"$ref":"#/$defs/statement_body"},"parent_node_id":{"type":"null"},"why":{"type":"null"}}}},{"if":{"properties":{"node_type":{"enum":["CURRENT_TARGET","GOAL"]}},"required":["node_type"]},"then":{"properties":{"body":{"$ref":"#/$defs/statement_body"},"parent_node_id":{"$ref":"#/$defs/sha256"},"why":{"$ref":"#/$defs/nonblank"}}}},{"if":{"properties":{"node_type":{"const":"TASK"}},"required":["node_type"]},"then":{"properties":{"body":{"$ref":"#/$defs/task_body"},"parent_node_id":{"$ref":"#/$defs/sha256"},"why":{"$ref":"#/$defs/nonblank"}}}},{"if":{"properties":{"node_type":{"const":"ACTION"}},"required":["node_type"]},"then":{"properties":{"body":{"$ref":"#/$defs/action_body"},"parent_node_id":{"$ref":"#/$defs/sha256"},"why":{"$ref":"#/$defs/nonblank"}}}}],"properties":{"body":{"oneOf":[{"$ref":"#/$defs/statement_body"},{"$ref":"#/$defs/task_body"},{"$ref":"#/$defs/action_body"}]},"node_id":{"$ref":"#/$defs/sha256"},"node_type":{"enum":["ORIGINAL_INTENT","CURRENT_TARGET","GOAL","TASK","ACTION"],"type":"string"},"parent_node_id":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]},"why":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/nonblank"}]}},"required":["body","node_id","node_type","parent_node_id","why"],"type":"object"},"nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"statement_body":{"additionalProperties":false,"properties":{"statement":{"minLength":1,"pattern":".*\\\\S.*","type":"string"}},"required":["statement"],"type":"object"},"task_body":{"additionalProperties":false,"properties":{"source_task_sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"task_id":{"maxLength":128,"minLength":1,"pattern":"^[A-Za-z0-9._:-]{1,128}$","type":"string"}},"required":["task_id","source_task_sha256"],"type":"object"}},"$id":"gg.goal-why-chain.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"current_target_node_id":{"$ref":"#/$defs/sha256"},"nodes":{"items":{"$ref":"#/$defs/node"},"minItems":4,"type":"array"},"origin_id":{"$ref":"#/$defs/identifier"},"original_intent_node_id":{"$ref":"#/$defs/sha256"},"schema":{"const":"gg.goal-why-chain.v1","type":"string"},"source_original_expression_sha256":{"$ref":"#/$defs/sha256"},"source_task_schema":{"const":"gg.cognitive-task-envelope.v1","type":"string"},"source_task_sha256":{"$ref":"#/$defs/sha256"},"task_id":{"$ref":"#/$defs/identifier"},"task_node_id":{"$ref":"#/$defs/sha256"}},"required":["current_target_node_id","nodes","origin_id","original_intent_node_id","schema","source_original_expression_sha256","source_task_schema","source_task_sha256","task_id","task_node_id"],"title":"GG Goal WHY Chain v1","type":"object"}'


class GoalWhyError(ValueError):
    def __init__(self, code: str, cause_message: str | None = None):
        self.code = code
        self.cause_message = cause_message
        message = code if cause_message is None else code + ": " + cause_message
        super().__init__(message)


def _fail(code: str, cause_message: str | None = None) -> None:
    raise GoalWhyError(code, cause_message)


def canonical_json(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_JSON_VALUE", str(exc))
    return (text + "\n").encode("utf-8")


def schema_document() -> dict[str, Any]:
    return json.loads(_SCHEMA_JSON)


def _exact(value: Any, fields: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _nonblank(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code)
    return value


def _identifier(value: Any, code: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _sha256_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _source_runtime_path() -> pathlib.Path:
    here = pathlib.Path(__file__).absolute()
    return here.parent / SOURCE_TASK_RUNTIME_FILENAME


def _read_exact_regular_file(path: pathlib.Path) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "O_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | os.O_CLOEXEC | nofollow
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        _fail("SOURCE_TASK_AUTHORITY_INVALID", f"OPEN_FAILED:{exc.errno}")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _fail("SOURCE_TASK_AUTHORITY_INVALID", "NOT_REGULAR_FILE")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        captured = b"".join(chunks)
        after = os.fstat(fd)
        if (
            info.st_dev != after.st_dev
            or info.st_ino != after.st_ino
            or info.st_size != after.st_size
            or len(captured) != after.st_size
        ):
            _fail("SOURCE_TASK_AUTHORITY_INVALID", "READ_STATE_CHANGED")
        return captured
    finally:
        os.close(fd)


def _load_bound_source(
    path: str | os.PathLike[str],
    expected_sha256: str,
) -> dict[str, Any]:
    source_path = pathlib.Path(path)
    captured = _read_exact_regular_file(source_path)
    actual = hashlib.sha256(captured).hexdigest()
    if actual != expected_sha256:
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "SHA256_MISMATCH")
    try:
        code = compile(captured, str(source_path), "exec")
    except BaseException as exc:
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "COMPILE_FAILED:" + type(exc).__name__)
    namespace: dict[str, Any] = {
        "__name__": "_gg_content_bound_cognitive_contract",
        "__file__": str(source_path),
        "__builtins__": __builtins__,
    }
    try:
        exec(code, namespace, namespace)
    except BaseException as exc:
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "EXEC_FAILED:" + type(exc).__name__)

    if namespace.get("SCHEMA_ID") != SOURCE_TASK_SCHEMA_ID:
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "SCHEMA_ID_MISMATCH")

    contract_error = namespace.get("ContractError")
    validate_envelope = namespace.get("validate_envelope")
    canonicalize_envelope = namespace.get("canonicalize_envelope")

    if not isinstance(contract_error, type) or not issubclass(contract_error, Exception):
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "CONTRACT_ERROR_MISSING")
    if not callable(validate_envelope):
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "VALIDATE_ENVELOPE_MISSING")
    if not callable(canonicalize_envelope):
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "CANONICALIZE_ENVELOPE_MISSING")

    return {
        "ContractError": contract_error,
        "validate_envelope": validate_envelope,
        "canonicalize_envelope": canonicalize_envelope,
        "SCHEMA_ID": namespace["SCHEMA_ID"],
    }


def _source_authority() -> dict[str, Any]:
    return _load_bound_source(_source_runtime_path(), SOURCE_TASK_RUNTIME_SHA256)


def _validated_source(source_envelope: Any) -> dict[str, Any]:
    authority = _source_authority()
    try:
        source = copy.deepcopy(source_envelope)
    except BaseException as exc:
        _fail("SOURCE_TASK_INVALID", "DEEPCOPY_FAILED:" + type(exc).__name__)

    contract_error = authority["ContractError"]
    try:
        authority["validate_envelope"](source)
        if source.get("state") != "READY_FOR_CONTROL" or source.get("ready_core") is None:
            _fail("STOP_GOAL", "SOURCE_TASK_NOT_READY")
        canonical = authority["canonicalize_envelope"](source)
    except GoalWhyError:
        raise
    except contract_error as exc:
        _fail("SOURCE_TASK_INVALID", str(exc))

    if not isinstance(canonical, bytes):
        _fail("SOURCE_TASK_AUTHORITY_INVALID", "CANONICALIZE_ENVELOPE_NOT_BYTES")

    original_expression = source.get("original_expression")
    if not isinstance(original_expression, str):
        _fail("SOURCE_TASK_INVALID", "original_expression invalid")

    ready = source.get("ready_core")
    if not isinstance(ready, dict) or not isinstance(ready.get("goal"), str):
        _fail("SOURCE_TASK_INVALID", "ready_core.goal invalid")

    return {
        "envelope": source,
        "source_task_sha256": hashlib.sha256(canonical).hexdigest(),
        "source_original_expression_sha256": hashlib.sha256(
            original_expression.encode("utf-8")
        ).hexdigest(),
        "task_id": source["task_id"],
        "origin_id": source["origin_id"],
        "goal": ready["goal"],
    }


def _node_semantics(
    node_type: Any,
    parent_node_id: Any,
    why: Any,
    body: Any,
) -> dict[str, Any]:
    if node_type not in NODE_TYPES:
        _fail("STOP_GOAL_TRACEABILITY", "NODE_TYPE_INVALID")

    if node_type == "ORIGINAL_INTENT":
        if parent_node_id is not None or why is not None:
            _fail("STOP_GOAL_TRACEABILITY", "ORIGINAL_INTENT_ROOT_INVALID")
        body_value = _exact(body, _STATEMENT_BODY_FIELDS, "STOP_GOAL_TRACEABILITY")
        _nonblank(body_value["statement"], "STOP_GOAL_TRACEABILITY")
    else:
        _sha256_text(parent_node_id, "STOP_GOAL_TRACEABILITY")
        _nonblank(why, "STOP_GOAL_TRACEABILITY")

        if node_type in {"CURRENT_TARGET", "GOAL"}:
            body_value = _exact(body, _STATEMENT_BODY_FIELDS, "STOP_GOAL_TRACEABILITY")
            _nonblank(body_value["statement"], "STOP_GOAL_TRACEABILITY")
        elif node_type == "SUBGOAL":
            body_value = _exact(body, _STATEMENT_BODY_FIELDS, "STOP_GOAL_TRACEABILITY")
            _nonblank(body_value["statement"], "STOP_GOAL_TRACEABILITY")
        elif node_type == "TASK":
            body_value = _exact(body, _TASK_BODY_FIELDS, "STOP_GOAL_TRACEABILITY")
            _identifier(body_value["task_id"], "STOP_GOAL_TRACEABILITY")
            _sha256_text(body_value["source_task_sha256"], "STOP_GOAL_TRACEABILITY")
        else:
            body_value = _exact(body, _ACTION_BODY_FIELDS, "STOP_GOAL_TRACEABILITY")
            _identifier(body_value["action_id"], "STOP_GOAL_TRACEABILITY")
            _nonblank(body_value["description"], "STOP_GOAL_TRACEABILITY")

    return {
        "node_type": node_type,
        "parent_node_id": parent_node_id,
        "why": why,
        "body": copy.deepcopy(body),
    }


def node_id(node_semantics: dict[str, Any]) -> str:
    value = _exact(
        node_semantics,
        _NODE_SEMANTIC_FIELDS,
        "STOP_GOAL_TRACEABILITY",
    )
    semantic = _node_semantics(
        value["node_type"],
        value["parent_node_id"],
        value["why"],
        value["body"],
    )
    return hashlib.sha256(NODE_HASH_DOMAIN + canonical_json(semantic)).hexdigest()


def make_node(
    *,
    node_type: str,
    parent_node_id: str | None,
    why: str | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    semantic = _node_semantics(node_type, parent_node_id, why, body)
    result = dict(semantic)
    result["node_id"] = node_id(semantic)
    return {
        "node_id": result["node_id"],
        "node_type": result["node_type"],
        "parent_node_id": result["parent_node_id"],
        "why": result["why"],
        "body": result["body"],
    }


def _normalize_nodes(nodes: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(nodes, list):
        _fail("STOP_GOAL_TRACEABILITY", "NODES_NOT_LIST")

    normalized: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    action_ids: set[str] = set()

    for raw in nodes:
        value = _exact(raw, _NODE_FIELDS, "STOP_GOAL_TRACEABILITY")
        expected = node_id({
            "node_type": value["node_type"],
            "parent_node_id": value["parent_node_id"],
            "why": value["why"],
            "body": value["body"],
        })
        actual = _sha256_text(value["node_id"], "STOP_GOAL_TRACEABILITY")
        if actual != expected:
            _fail("STOP_GOAL_TRACEABILITY", "NODE_ID_MISMATCH")
        if actual in by_id:
            _fail("STOP_GOAL_TRACEABILITY", "DUPLICATE_NODE_ID")

        clean = {
            "node_id": actual,
            "node_type": value["node_type"],
            "parent_node_id": value["parent_node_id"],
            "why": value["why"],
            "body": copy.deepcopy(value["body"]),
        }
        by_id[actual] = clean
        normalized.append(clean)

        if clean["node_type"] == "ACTION":
            action_id = clean["body"]["action_id"]
            if action_id in action_ids:
                _fail("STOP_GOAL_TRACEABILITY", "DUPLICATE_ACTION_ID")
            action_ids.add(action_id)

    roots = [n for n in normalized if n["node_type"] == "ORIGINAL_INTENT"]
    targets = [n for n in normalized if n["node_type"] == "CURRENT_TARGET"]
    tasks = [n for n in normalized if n["node_type"] == "TASK"]
    goals = [n for n in normalized if n["node_type"] == "GOAL"]
    subgoals = [n for n in normalized if n["node_type"] == "SUBGOAL"]

    if len(roots) != 1:
        _fail("STOP_GOAL_TRACEABILITY", "ORIGINAL_INTENT_CARDINALITY")
    if len(targets) != 1:
        _fail("STOP_GOAL_TRACEABILITY", "CURRENT_TARGET_CARDINALITY")
    if len(tasks) != 1:
        _fail("STOP_GOAL_TRACEABILITY", "TASK_CARDINALITY")
    if not goals:
        _fail("STOP_GOAL_TRACEABILITY", "GOAL_REQUIRED")

    allowed_parent_types = {
        "CURRENT_TARGET": {"ORIGINAL_INTENT"},
        "GOAL": {"CURRENT_TARGET", "GOAL"},
        "SUBGOAL": {"GOAL", "SUBGOAL"},
        "TASK": {"GOAL", "SUBGOAL"},
        "ACTION": {"TASK"},
    }

    for node in normalized:
        kind = node["node_type"]
        if kind == "ORIGINAL_INTENT":
            continue
        parent_id = node["parent_node_id"]
        parent = by_id.get(parent_id)
        if parent is None:
            _fail("STOP_GOAL_TRACEABILITY", "PARENT_MISSING")
        if parent["node_type"] not in allowed_parent_types[kind]:
            _fail("STOP_GOAL_TRACEABILITY", "PARENT_TYPE_INVALID")

    def path_to_root(start_id: str) -> list[str]:
        seen: set[str] = set()
        reverse: list[str] = []
        current = start_id
        while True:
            if current in seen:
                _fail("STOP_GOAL_TRACEABILITY", "CYCLE")
            seen.add(current)
            node = by_id.get(current)
            if node is None:
                _fail("STOP_GOAL_TRACEABILITY", "PARENT_MISSING")
            reverse.append(current)
            parent_id = node["parent_node_id"]
            if parent_id is None:
                break
            current = parent_id
        reverse.reverse()
        if reverse[0] != roots[0]["node_id"]:
            _fail("STOP_GOAL_TRACEABILITY", "DISCONNECTED_NODE")
        return reverse

    for node in normalized:
        path_to_root(node["node_id"])

    task_path = path_to_root(tasks[0]["node_id"])
    task_path_nodes = [by_id[item] for item in task_path]
    expected_prefix = ["ORIGINAL_INTENT", "CURRENT_TARGET"]
    if [n["node_type"] for n in task_path_nodes[:2]] != expected_prefix:
        _fail("STOP_GOAL_TRACEABILITY", "TASK_TRACE_PREFIX_INVALID")
    if task_path_nodes[-1]["node_type"] != "TASK":
        _fail("STOP_GOAL_TRACEABILITY", "TASK_TRACE_SUFFIX_INVALID")
    middle = task_path_nodes[2:-1]
    if not middle or any(
        n["node_type"] not in {"GOAL", "SUBGOAL"}
        for n in middle
    ):
        _fail("STOP_GOAL_TRACEABILITY", "TASK_GOAL_TRACE_INVALID")

    seen_subgoal = False
    for node in middle:
        if node["node_type"] == "SUBGOAL":
            seen_subgoal = True
        elif seen_subgoal:
            _fail("STOP_GOAL_TRACEABILITY", "GOAL_AFTER_SUBGOAL")

    goal_ids = {n["node_id"] for n in goals}
    path_goal_ids = {
        n["node_id"]
        for n in middle
        if n["node_type"] == "GOAL"
    }
    if goal_ids != path_goal_ids:
        _fail("STOP_GOAL_TRACEABILITY", "GOAL_CHAIN_NOT_LINEAR")

    subgoal_ids = {n["node_id"] for n in subgoals}
    path_subgoal_ids = {
        n["node_id"]
        for n in middle
        if n["node_type"] == "SUBGOAL"
    }
    if subgoal_ids != path_subgoal_ids:
        _fail("STOP_GOAL_TRACEABILITY", "SUBGOAL_CHAIN_NOT_LINEAR")

    for node in normalized:
        if node["node_type"] == "ACTION" and node["parent_node_id"] != tasks[0]["node_id"]:
            _fail("STOP_GOAL_TRACEABILITY", "ACTION_NOT_TASK_CHILD")

    return sorted(normalized, key=lambda item: item["node_id"]), by_id


def _normalize_chain_with_source(chain: Any, source: dict[str, Any]) -> dict[str, Any]:
    value = _exact(chain, _CHAIN_FIELDS, "STOP_GOAL_TRACEABILITY")

    if value["schema"] != SCHEMA_ID:
        _fail("STOP_GOAL_TRACEABILITY", "CHAIN_SCHEMA_INVALID")
    if value["source_task_schema"] != SOURCE_TASK_SCHEMA_ID:
        _fail("STOP_GOAL", "SOURCE_TASK_SCHEMA_MISMATCH")

    _sha256_text(value["source_task_sha256"], "STOP_GOAL_TRACEABILITY")
    _sha256_text(value["source_original_expression_sha256"], "STOP_GOAL_TRACEABILITY")
    _identifier(value["task_id"], "STOP_GOAL_TRACEABILITY")
    _identifier(value["origin_id"], "STOP_GOAL_TRACEABILITY")
    _sha256_text(value["original_intent_node_id"], "STOP_GOAL_TRACEABILITY")
    _sha256_text(value["current_target_node_id"], "STOP_GOAL_TRACEABILITY")
    _sha256_text(value["task_node_id"], "STOP_GOAL_TRACEABILITY")

    nodes, by_id = _normalize_nodes(copy.deepcopy(value["nodes"]))

    roots = [n for n in nodes if n["node_type"] == "ORIGINAL_INTENT"]
    targets = [n for n in nodes if n["node_type"] == "CURRENT_TARGET"]
    tasks = [n for n in nodes if n["node_type"] == "TASK"]

    if value["original_intent_node_id"] != roots[0]["node_id"]:
        _fail("STOP_GOAL_TRACEABILITY", "ORIGINAL_INTENT_REFERENCE_MISMATCH")
    if value["current_target_node_id"] != targets[0]["node_id"]:
        _fail("STOP_GOAL_TRACEABILITY", "CURRENT_TARGET_REFERENCE_MISMATCH")
    if value["task_node_id"] != tasks[0]["node_id"]:
        _fail("STOP_GOAL_TRACEABILITY", "TASK_REFERENCE_MISMATCH")

    if value["source_task_sha256"] != source["source_task_sha256"]:
        _fail("STOP_GOAL", "SOURCE_TASK_SHA256_MISMATCH")
    if value["source_original_expression_sha256"] != source["source_original_expression_sha256"]:
        _fail("STOP_GOAL", "SOURCE_ORIGINAL_EXPRESSION_SHA256_MISMATCH")
    if value["task_id"] != source["task_id"]:
        _fail("STOP_GOAL", "TASK_ID_MISMATCH")
    if value["origin_id"] != source["origin_id"]:
        _fail("STOP_GOAL", "ORIGIN_ID_MISMATCH")

    task = tasks[0]
    if task["body"]["task_id"] != source["task_id"]:
        _fail("STOP_GOAL", "TASK_BODY_TASK_ID_MISMATCH")
    if task["body"]["source_task_sha256"] != source["source_task_sha256"]:
        _fail("STOP_GOAL", "TASK_BODY_SOURCE_SHA256_MISMATCH")

    # Reconstruct task ancestry from the normalized graph.
    ancestry: list[dict[str, Any]] = []
    current = task
    while True:
        ancestry.append(current)
        parent_id = current["parent_node_id"]
        if parent_id is None:
            break
        current = by_id[parent_id]
    ancestry.reverse()

    matches = [
        node
        for node in ancestry
        if node["node_type"] == "GOAL"
        and node["body"]["statement"] == source["goal"]
    ]
    if not matches:
        _fail("STOP_GOAL", "SOURCE_TASK_GOAL_NOT_ANCHORED")
    if len(matches) != 1:
        _fail("STOP_GOAL_TRACEABILITY", "AMBIGUOUS_SOURCE_TASK_GOAL_ANCHOR")

    return {
        "schema": SCHEMA_ID,
        "source_task_schema": SOURCE_TASK_SCHEMA_ID,
        "source_task_sha256": source["source_task_sha256"],
        "source_original_expression_sha256": source["source_original_expression_sha256"],
        "task_id": source["task_id"],
        "origin_id": source["origin_id"],
        "original_intent_node_id": roots[0]["node_id"],
        "current_target_node_id": targets[0]["node_id"],
        "task_node_id": tasks[0]["node_id"],
        "nodes": nodes,
    }


def build_goal_why_chain(
    source_envelope: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    source = _validated_source(source_envelope)
    normalized_nodes, _ = _normalize_nodes(copy.deepcopy(nodes))
    roots = [n for n in normalized_nodes if n["node_type"] == "ORIGINAL_INTENT"]
    targets = [n for n in normalized_nodes if n["node_type"] == "CURRENT_TARGET"]
    tasks = [n for n in normalized_nodes if n["node_type"] == "TASK"]

    candidate = {
        "schema": SCHEMA_ID,
        "source_task_schema": SOURCE_TASK_SCHEMA_ID,
        "source_task_sha256": source["source_task_sha256"],
        "source_original_expression_sha256": source["source_original_expression_sha256"],
        "task_id": source["task_id"],
        "origin_id": source["origin_id"],
        "original_intent_node_id": roots[0]["node_id"],
        "current_target_node_id": targets[0]["node_id"],
        "task_node_id": tasks[0]["node_id"],
        "nodes": normalized_nodes,
    }
    return _normalize_chain_with_source(candidate, source)


def validate_chain(
    chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> dict[str, Any]:
    source = _validated_source(source_envelope)
    return _normalize_chain_with_source(copy.deepcopy(chain), source)


def _trace_to(
    normalized_chain: dict[str, Any],
    node_id_value: str,
) -> tuple[str, ...]:
    by_id = {node["node_id"]: node for node in normalized_chain["nodes"]}
    if node_id_value not in by_id:
        _fail("STOP_GOAL_TRACEABILITY", "TRACE_NODE_UNKNOWN")
    seen: set[str] = set()
    reverse: list[str] = []
    current = node_id_value
    while True:
        if current in seen:
            _fail("STOP_GOAL_TRACEABILITY", "CYCLE")
        seen.add(current)
        node = by_id[current]
        reverse.append(current)
        parent = node["parent_node_id"]
        if parent is None:
            break
        if parent not in by_id:
            _fail("STOP_GOAL_TRACEABILITY", "PARENT_MISSING")
        current = parent
    reverse.reverse()
    if reverse[0] != normalized_chain["original_intent_node_id"]:
        _fail("STOP_GOAL_TRACEABILITY", "TRACE_ROOT_MISMATCH")
    return tuple(reverse)


def trace_task(
    chain: dict[str, Any],
    source_envelope: dict[str, Any],
) -> tuple[str, ...]:
    normalized = validate_chain(chain, source_envelope)
    return _trace_to(normalized, normalized["task_node_id"])


def trace_action(
    chain: dict[str, Any],
    source_envelope: dict[str, Any],
    action_node_id: str,
) -> tuple[str, ...]:
    normalized = validate_chain(chain, source_envelope)
    _sha256_text(action_node_id, "STOP_GOAL_TRACEABILITY")
    by_id = {node["node_id"]: node for node in normalized["nodes"]}
    node = by_id.get(action_node_id)
    if node is None or node["node_type"] != "ACTION":
        _fail("STOP_GOAL_TRACEABILITY", "UNKNOWN_ACTION")
    return _trace_to(normalized, action_node_id)
