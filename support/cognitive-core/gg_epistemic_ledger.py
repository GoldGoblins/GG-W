from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import stat
from typing import Any

SCHEMA_ID = "gg.epistemic-ledger-record.v1"
RECORD_TYPES = ("CLAIM", "RELATION")
EPISTEMIC_CLASSES = (
    "ASSUMPTION",
    "UNTRUSTED_MODEL_OUTPUT",
    "OBSERVED",
    "VERIFIED",
    "DERIVED",
)
SOURCE_KINDS = (
    "HUMAN_INPUT",
    "LOCAL_OBSERVATION",
    "DETERMINISTIC_TOOL",
    "MODEL_OUTPUT",
    "HISTORICAL_ARTIFACT",
    "DERIVATION",
)
RELATION_TYPES = ("SUPPORTS", "CONTRADICTS")
CLAIM_HASH_DOMAIN = b"gg.epistemic.claim.v1\n"
CONTENT_HASH_DOMAIN = b"gg.epistemic.content.v1\n"
ENTRY_HASH_DOMAIN = b"gg.epistemic.entry.v1\n"
EMPTY_LEDGER_HEAD = None
CONCURRENT_MULTI_WRITER_SAFETY = "NOT_CLAIMED_IN_K7-E"
MULTIAGENT_RECONCILIATION = "LATER_LAYER"

_SCHEMA_JSON = '{"$defs":{"claim_body":{"additionalProperties":false,"allOf":[{"if":{"properties":{"source_kind":{"const":"MODEL_OUTPUT"}},"required":["source_kind"]},"then":{"properties":{"epistemic_class":{"const":"UNTRUSTED_MODEL_OUTPUT"}}}},{"if":{"properties":{"source_kind":{"const":"DERIVATION"}},"required":["source_kind"]},"then":{"properties":{"epistemic_class":{"const":"DERIVED"},"parent_entry_sha256s":{"minItems":1}}}},{"if":{"properties":{"epistemic_class":{"const":"DERIVED"}},"required":["epistemic_class"]},"then":{"properties":{"parent_entry_sha256s":{"minItems":1},"source_kind":{"const":"DERIVATION"}}}}],"properties":{"claim_id":{"$ref":"#/$defs/sha256"},"claim_key":{"$ref":"#/$defs/nonblank"},"epistemic_class":{"$ref":"#/$defs/epistemic_class"},"parent_entry_sha256s":{"items":{"$ref":"#/$defs/sha256"},"type":"array","uniqueItems":true},"source_fingerprint":{"$ref":"#/$defs/nonblank"},"source_id":{"$ref":"#/$defs/nonblank"},"source_kind":{"$ref":"#/$defs/source_kind"},"statement":{"$ref":"#/$defs/nonblank"}},"required":["claim_id","claim_key","statement","epistemic_class","source_kind","source_id","source_fingerprint","parent_entry_sha256s"],"type":"object"},"epistemic_class":{"enum":["ASSUMPTION","UNTRUSTED_MODEL_OUTPUT","OBSERVED","VERIFIED","DERIVED"],"type":"string"},"nonblank":{"minLength":1,"pattern":".*\\\\S.*","type":"string"},"relation_body":{"additionalProperties":false,"allOf":[{"if":{"properties":{"source_kind":{"const":"MODEL_OUTPUT"}},"required":["source_kind"]},"then":{"properties":{"epistemic_class":{"const":"UNTRUSTED_MODEL_OUTPUT"}}}}],"properties":{"epistemic_class":{"$ref":"#/$defs/epistemic_class"},"object_entry_sha256":{"$ref":"#/$defs/sha256"},"relation_type":{"enum":["SUPPORTS","CONTRADICTS"],"type":"string"},"source_fingerprint":{"$ref":"#/$defs/nonblank"},"source_id":{"$ref":"#/$defs/nonblank"},"source_kind":{"$ref":"#/$defs/source_kind"},"subject_entry_sha256":{"$ref":"#/$defs/sha256"}},"required":["relation_type","subject_entry_sha256","object_entry_sha256","epistemic_class","source_kind","source_id","source_fingerprint"],"type":"object"},"sha256":{"pattern":"^[0-9a-f]{64}$","type":"string"},"source_kind":{"enum":["HUMAN_INPUT","LOCAL_OBSERVATION","DETERMINISTIC_TOOL","MODEL_OUTPUT","HISTORICAL_ARTIFACT","DERIVATION"],"type":"string"}},"$id":"gg.epistemic-ledger-record.v1","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"allOf":[{"if":{"properties":{"sequence":{"const":0}},"required":["sequence"]},"then":{"properties":{"previous_entry_sha256":{"type":"null"}}}},{"if":{"properties":{"sequence":{"minimum":1}},"required":["sequence"]},"then":{"properties":{"previous_entry_sha256":{"$ref":"#/$defs/sha256"}}}},{"if":{"properties":{"record_type":{"const":"CLAIM"}},"required":["record_type"]},"then":{"properties":{"body":{"$ref":"#/$defs/claim_body"}}}},{"if":{"properties":{"record_type":{"const":"RELATION"}},"required":["record_type"]},"then":{"properties":{"body":{"$ref":"#/$defs/relation_body"}}}}],"properties":{"body":{"oneOf":[{"$ref":"#/$defs/claim_body"},{"$ref":"#/$defs/relation_body"}]},"content_sha256":{"$ref":"#/$defs/sha256"},"entry_sha256":{"$ref":"#/$defs/sha256"},"origin_id":{"$ref":"#/$defs/nonblank"},"previous_entry_sha256":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/sha256"}]},"record_type":{"enum":["CLAIM","RELATION"],"type":"string"},"schema":{"const":"gg.epistemic-ledger-record.v1","type":"string"},"sequence":{"minimum":0,"type":"integer"},"task_id":{"$ref":"#/$defs/nonblank"}},"required":["schema","sequence","record_type","task_id","origin_id","body","content_sha256","previous_entry_sha256","entry_sha256"],"title":"GG Epistemic Ledger Record v1","type":"object"}'
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_COMMON_RECORD_FIELDS = frozenset({
    "schema",
    "sequence",
    "record_type",
    "task_id",
    "origin_id",
    "body",
    "content_sha256",
    "previous_entry_sha256",
    "entry_sha256",
})
_CANDIDATE_FIELDS = frozenset({
    "schema",
    "record_type",
    "task_id",
    "origin_id",
    "body",
})
_CLAIM_BODY_FIELDS = frozenset({
    "claim_id",
    "claim_key",
    "statement",
    "epistemic_class",
    "source_kind",
    "source_id",
    "source_fingerprint",
    "parent_entry_sha256s",
})
_RELATION_BODY_FIELDS = frozenset({
    "relation_type",
    "subject_entry_sha256",
    "object_entry_sha256",
    "epistemic_class",
    "source_kind",
    "source_id",
    "source_fingerprint",
})


class LedgerError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise LedgerError(code)


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
        raise LedgerError("NON_CANONICAL_JSON_VALUE") from exc
    return text.encode("utf-8") + b"\n"


def schema_document() -> dict[str, Any]:
    value = json.loads(_SCHEMA_JSON)
    if not isinstance(value, dict):
        _fail("SCHEMA_DOCUMENT_INVALID")
    return value


def _domain_hash(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + canonical_json(value)).hexdigest()


def claim_id(claim_key: str, statement: str) -> str:
    _require_nonblank(claim_key, "claim_key")
    _require_nonblank(statement, "statement")
    return _domain_hash(
        CLAIM_HASH_DOMAIN,
        {
            "claim_key": claim_key,
            "statement": statement,
        },
    )


def _require_dict(value: Any, name: str, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(name + "_NOT_OBJECT")
    keys = frozenset(value)
    if keys != fields:
        _fail(name + "_FIELD_SET")
    return value


def _require_nonblank(value: Any, name: str) -> str:
    if not isinstance(value, str):
        _fail(name + "_NOT_STRING")
    if not value or not any(not char.isspace() for char in value):
        _fail(name + "_INVALID")
    return value


def _require_id(value: Any, name: str) -> str:
    return _require_nonblank(value, name)


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(name + "_INVALID")
    return value


def _validate_trust(epistemic_class: str, source_kind: str) -> None:
    if epistemic_class not in EPISTEMIC_CLASSES:
        _fail("EPISTEMIC_CLASS_INVALID")
    if source_kind not in SOURCE_KINDS:
        _fail("SOURCE_KIND_INVALID")
    if source_kind == "MODEL_OUTPUT" and epistemic_class != "UNTRUSTED_MODEL_OUTPUT":
        _fail("MODEL_OUTPUT_TRUST_PROMOTION_FORBIDDEN")
    if source_kind == "DERIVATION" and epistemic_class != "DERIVED":
        _fail("DERIVATION_CLASS_REQUIRED")
    if epistemic_class == "DERIVED" and source_kind != "DERIVATION":
        _fail("DERIVED_SOURCE_REQUIRED")


def _validate_claim_body(
    body: Any,
    previous_claims: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    value = _require_dict(body, "CLAIM_BODY", _CLAIM_BODY_FIELDS)
    key = _require_nonblank(value["claim_key"], "claim_key")
    statement = _require_nonblank(value["statement"], "statement")
    expected_claim_id = claim_id(key, statement)
    if value["claim_id"] != expected_claim_id:
        _fail("CLAIM_ID_MISMATCH")
    epistemic_class = value["epistemic_class"]
    source_kind = value["source_kind"]
    _validate_trust(epistemic_class, source_kind)
    _require_id(value["source_id"], "source_id")
    _require_nonblank(value["source_fingerprint"], "source_fingerprint")

    parents = value["parent_entry_sha256s"]
    if not isinstance(parents, list):
        _fail("PARENTS_NOT_ARRAY")
    if len(set(parents)) != len(parents):
        _fail("PARENTS_DUPLICATE")
    for parent in parents:
        _require_sha(parent, "parent_entry_sha256")
        if parent not in previous_claims:
            _fail("PARENT_NOT_PREVIOUS_CLAIM")

    if source_kind == "DERIVATION" and not parents:
        _fail("DERIVATION_PARENT_REQUIRED")
    return value


def _validate_relation_body(
    body: Any,
    previous_claims: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    value = _require_dict(body, "RELATION_BODY", _RELATION_BODY_FIELDS)
    if value["relation_type"] not in RELATION_TYPES:
        _fail("RELATION_TYPE_INVALID")
    subject = _require_sha(value["subject_entry_sha256"], "subject_entry_sha256")
    object_entry = _require_sha(value["object_entry_sha256"], "object_entry_sha256")
    if subject not in previous_claims:
        _fail("RELATION_SUBJECT_NOT_PREVIOUS_CLAIM")
    if object_entry not in previous_claims:
        _fail("RELATION_OBJECT_NOT_PREVIOUS_CLAIM")
    _validate_trust(value["epistemic_class"], value["source_kind"])
    _require_id(value["source_id"], "source_id")
    _require_nonblank(value["source_fingerprint"], "source_fingerprint")
    return value


def validate_candidate(
    candidate: Any,
    previous_records: list[dict[str, Any]],
) -> dict[str, Any]:
    value = _require_dict(candidate, "CANDIDATE", _CANDIDATE_FIELDS)
    if value["schema"] != SCHEMA_ID:
        _fail("SCHEMA_INVALID")
    if value["record_type"] not in RECORD_TYPES:
        _fail("RECORD_TYPE_INVALID")
    _require_id(value["task_id"], "task_id")
    _require_id(value["origin_id"], "origin_id")

    previous_claims = {
        record["entry_sha256"]: record
        for record in previous_records
        if record.get("record_type") == "CLAIM"
        and isinstance(record.get("entry_sha256"), str)
    }

    if value["record_type"] == "CLAIM":
        _validate_claim_body(value["body"], previous_claims)
    else:
        _validate_relation_body(value["body"], previous_claims)
    return value


def content_sha256(candidate: dict[str, Any]) -> str:
    value = _require_dict(candidate, "CANDIDATE", _CANDIDATE_FIELDS)
    return _domain_hash(
        CONTENT_HASH_DOMAIN,
        {
            "schema": value["schema"],
            "record_type": value["record_type"],
            "task_id": value["task_id"],
            "origin_id": value["origin_id"],
            "body": value["body"],
        },
    )


def entry_sha256(record_without_entry_sha256: dict[str, Any]) -> str:
    fields = _COMMON_RECORD_FIELDS - {"entry_sha256"}
    value = _require_dict(
        record_without_entry_sha256,
        "ENTRY_HASH_INPUT",
        fields,
    )
    return _domain_hash(
        ENTRY_HASH_DOMAIN,
        {
            "schema": value["schema"],
            "sequence": value["sequence"],
            "record_type": value["record_type"],
            "task_id": value["task_id"],
            "origin_id": value["origin_id"],
            "body": value["body"],
            "content_sha256": value["content_sha256"],
            "previous_entry_sha256": value["previous_entry_sha256"],
        },
    )


def make_claim_candidate(
    *,
    task_id: str,
    origin_id: str,
    claim_key: str,
    statement: str,
    epistemic_class: str,
    source_kind: str,
    source_id: str,
    source_fingerprint: str,
    parent_entry_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    parents = list(parent_entry_sha256s or [])
    return {
        "schema": SCHEMA_ID,
        "record_type": "CLAIM",
        "task_id": task_id,
        "origin_id": origin_id,
        "body": {
            "claim_id": claim_id(claim_key, statement),
            "claim_key": claim_key,
            "statement": statement,
            "epistemic_class": epistemic_class,
            "source_kind": source_kind,
            "source_id": source_id,
            "source_fingerprint": source_fingerprint,
            "parent_entry_sha256s": parents,
        },
    }


def make_relation_candidate(
    *,
    task_id: str,
    origin_id: str,
    relation_type: str,
    subject_entry_sha256: str,
    object_entry_sha256: str,
    epistemic_class: str,
    source_kind: str,
    source_id: str,
    source_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "record_type": "RELATION",
        "task_id": task_id,
        "origin_id": origin_id,
        "body": {
            "relation_type": relation_type,
            "subject_entry_sha256": subject_entry_sha256,
            "object_entry_sha256": object_entry_sha256,
            "epistemic_class": epistemic_class,
            "source_kind": source_kind,
            "source_id": source_id,
            "source_fingerprint": source_fingerprint,
        },
    }


def finalize_record(
    candidate: dict[str, Any],
    sequence: int,
    previous_entry_sha256: str | None,
    previous_records: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        _fail("SEQUENCE_INVALID")
    if sequence != len(previous_records):
        _fail("SEQUENCE_NOT_NEXT")
    if sequence == 0:
        if previous_entry_sha256 is not None:
            _fail("GENESIS_PREVIOUS_NOT_NULL")
    else:
        expected = previous_records[-1]["entry_sha256"]
        if previous_entry_sha256 != expected:
            _fail("PREVIOUS_ENTRY_MISMATCH")

    validate_candidate(candidate, previous_records)
    content = content_sha256(candidate)
    base = {
        "schema": candidate["schema"],
        "sequence": sequence,
        "record_type": candidate["record_type"],
        "task_id": candidate["task_id"],
        "origin_id": candidate["origin_id"],
        "body": json.loads(json.dumps(candidate["body"], ensure_ascii=False, allow_nan=False)),
        "content_sha256": content,
        "previous_entry_sha256": previous_entry_sha256,
    }
    record = {
        **base,
        "entry_sha256": entry_sha256(base),
    }
    return record


def verify_chain(records: list[dict[str, Any]]) -> str | None:
    previous: list[dict[str, Any]] = []
    content_seen: set[str] = set()

    for index, record in enumerate(records):
        value = _require_dict(record, "RECORD", _COMMON_RECORD_FIELDS)
        if isinstance(value["sequence"], bool) or value["sequence"] != index:
            _fail("SEQUENCE_CHAIN_INVALID")

        expected_previous = None if index == 0 else previous[-1]["entry_sha256"]
        if value["previous_entry_sha256"] != expected_previous:
            _fail("PREVIOUS_ENTRY_CHAIN_INVALID")

        candidate = {
            "schema": value["schema"],
            "record_type": value["record_type"],
            "task_id": value["task_id"],
            "origin_id": value["origin_id"],
            "body": value["body"],
        }
        validate_candidate(candidate, previous)

        wanted_content = content_sha256(candidate)
        if value["content_sha256"] != wanted_content:
            _fail("CONTENT_SHA256_MISMATCH")
        if wanted_content in content_seen:
            _fail("DUPLICATE_RECORD")
        content_seen.add(wanted_content)

        base = {
            "schema": value["schema"],
            "sequence": value["sequence"],
            "record_type": value["record_type"],
            "task_id": value["task_id"],
            "origin_id": value["origin_id"],
            "body": value["body"],
            "content_sha256": value["content_sha256"],
            "previous_entry_sha256": value["previous_entry_sha256"],
        }
        if value["entry_sha256"] != entry_sha256(base):
            _fail("ENTRY_SHA256_MISMATCH")

        previous.append(value)

    return None if not previous else previous[-1]["entry_sha256"]


def parse_jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    if not isinstance(data, bytes):
        _fail("LEDGER_BYTES_REQUIRED")
    if not data:
        return []
    if b"\x00" in data or not data.endswith(b"\n"):
        _fail("JSONL_FORMAT_INVALID")

    records: list[dict[str, Any]] = []
    for raw in data.splitlines(keepends=True):
        if raw == b"\n":
            _fail("JSONL_BLANK_LINE")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LedgerError("JSONL_PARSE_FAILED") from exc
        if not isinstance(value, dict):
            _fail("JSONL_ROW_NOT_OBJECT")
        if canonical_json(value) != raw:
            _fail("JSONL_ROW_NOT_CANONICAL")
        records.append(value)

    verify_chain(records)
    return records


def _regular_file(path: pathlib.Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and not path.is_symlink()


def _safe_target(path: pathlib.Path) -> None:
    parent = path.parent
    try:
        parent_info = parent.stat(follow_symlinks=False)
    except FileNotFoundError:
        _fail("LEDGER_PARENT_MISSING")
    if not stat.S_ISDIR(parent_info.st_mode) or parent.is_symlink():
        _fail("LEDGER_PARENT_UNSAFE")
    if path.exists() or path.is_symlink():
        if not _regular_file(path):
            _fail("LEDGER_PATH_UNSAFE")


def read_chain(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    target = pathlib.Path(path)
    _safe_target(target)
    if not target.exists():
        return []
    return parse_jsonl_bytes(target.read_bytes())


def append_candidate(
    path: str | os.PathLike[str],
    candidate: dict[str, Any],
    *,
    expected_head_sha256: str | None,
) -> dict[str, Any]:
    target = pathlib.Path(path)
    _safe_target(target)
    old_bytes = target.read_bytes() if target.exists() else b""
    records = parse_jsonl_bytes(old_bytes)
    actual_head = verify_chain(records)

    if expected_head_sha256 != actual_head:
        _fail("STALE_DUE_TO_NEW_EVIDENCE")

    validate_candidate(candidate, records)
    new_content = content_sha256(candidate)
    if any(record["content_sha256"] == new_content for record in records):
        _fail("DUPLICATE_RECORD")

    record = finalize_record(
        candidate,
        len(records),
        actual_head,
        records,
    )
    encoded = canonical_json(record)

    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(target, flags, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                _fail("APPEND_WRITE_FAILED")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)

    new_bytes = target.read_bytes()
    if not new_bytes.startswith(old_bytes):
        _fail("OLD_BYTES_PREFIX_CHANGED")
    if new_bytes != old_bytes + encoded:
        _fail("APPEND_CARDINALITY_OR_BYTES_INVALID")
    parse_jsonl_bytes(new_bytes)
    return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))


def provenance_roots(records: list[dict[str, Any]]) -> dict[str, frozenset[str]]:
    verify_chain(records)
    roots: dict[str, frozenset[str]] = {}

    for record in records:
        if record["record_type"] != "CLAIM":
            continue
        entry = record["entry_sha256"]
        parents = record["body"]["parent_entry_sha256s"]
        if not parents:
            roots[entry] = frozenset((entry,))
        else:
            combined: set[str] = set()
            for parent in parents:
                combined.update(roots[parent])
            roots[entry] = frozenset(combined)

    return roots


def support_cycles(records: list[dict[str, Any]]) -> tuple[tuple[str, ...], ...]:
    verify_chain(records)
    claims = {
        record["entry_sha256"]
        for record in records
        if record["record_type"] == "CLAIM"
    }
    graph = {
        entry: set()
        for entry in claims
    }

    for record in records:
        if record["record_type"] != "RELATION":
            continue
        body = record["body"]
        if body["relation_type"] == "SUPPORTS":
            graph[body["subject_entry_sha256"]].add(
                body["object_entry_sha256"]
            )

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(graph[node]):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] != indices[node]:
            return

        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break

        ordered = tuple(sorted(component))
        if len(ordered) > 1:
            components.append(ordered)
        elif ordered[0] in graph[ordered[0]]:
            components.append(ordered)

    for node in sorted(graph):
        if node not in indices:
            strongconnect(node)

    return tuple(sorted(components))
