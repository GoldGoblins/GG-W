from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import stat
from typing import Any

SCHEMA_ID = "gg.belief-view.v1"
SOURCE_LEDGER_SCHEMA_ID = "gg.epistemic-ledger-record.v1"
SOURCE_LEDGER_RUNTIME_PATH = "cognitive-core/gg_epistemic_ledger.py"
SOURCE_LEDGER_RUNTIME_FILENAME = "gg_epistemic_ledger.py"
SOURCE_LEDGER_RUNTIME_SHA256 = (
    "dd9b28b78bc6bff0770c544807dc56ab2791fee78eb5eb6aa14eb316a5a80be7"
)
SOURCE_LEDGER_BINDING = "CONTENT_BOUND_EXACT_SIBLING_AUTHORITY"
SOURCE_LEDGER_REQUIRED_PRIMITIVES = (
    "canonical_json",
    "verify_chain",
    "provenance_roots",
    "support_cycles",
)
SOURCE_LEDGER_ERROR_HANDLING = "FAIL_CLOSED_TRANSLATION"
AMBIENT_PYTHONPATH_AUTHORITY = "FORBIDDEN"
SYS_PATH_DISCOVERY = "FORBIDDEN"
IMPORT_BY_MODULE_NAME_WITHOUT_CONTENT_BINDING = "FORBIDDEN"
FALLBACK_LEDGER_LOADER = None
CONTEXT_SELECTION = "EXPLICIT_CLAIM_KEYS_ONLY"
SEMANTIC_RETRIEVAL = "NOT_THIS_SLICE"
MODEL_CONTEXT_RENDERING = "NOT_THIS_SLICE"
LEDGER_MUTATION = "FORBIDDEN"
LIVE_PERSISTENCE = "NO"

VIEW_STATES = ("ABSENT", "UNCONTESTED", "CONFLICT")
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

_SCHEMA_JSON = "{\"$defs\":{\"candidate\":{\"additionalProperties\":false,\"properties\":{\"claim_id\":{\"$ref\":\"#/$defs/sha256\"},\"record_refs\":{\"items\":{\"$ref\":\"#/$defs/record_ref\"},\"minItems\":1,\"type\":\"array\"},\"statement\":{\"$ref\":\"#/$defs/nonblank\"}},\"required\":[\"claim_id\",\"statement\",\"record_refs\"],\"type\":\"object\"},\"claim_view\":{\"additionalProperties\":false,\"allOf\":[{\"if\":{\"properties\":{\"state\":{\"const\":\"ABSENT\"}},\"required\":[\"state\"]},\"then\":{\"properties\":{\"candidates\":{\"maxItems\":0}}}},{\"if\":{\"properties\":{\"state\":{\"const\":\"UNCONTESTED\"}},\"required\":[\"state\"]},\"then\":{\"properties\":{\"candidates\":{\"maxItems\":1,\"minItems\":1}}}},{\"if\":{\"properties\":{\"state\":{\"const\":\"CONFLICT\"}},\"required\":[\"state\"]},\"then\":{\"properties\":{\"candidates\":{\"minItems\":2}}}}],\"properties\":{\"candidates\":{\"items\":{\"$ref\":\"#/$defs/candidate\"},\"type\":\"array\"},\"claim_key\":{\"$ref\":\"#/$defs/nonblank\"},\"state\":{\"enum\":[\"ABSENT\",\"UNCONTESTED\",\"CONFLICT\"],\"type\":\"string\"}},\"required\":[\"claim_key\",\"state\",\"candidates\"],\"type\":\"object\"},\"nonblank\":{\"minLength\":1,\"pattern\":\".*\\\\S.*\",\"type\":\"string\"},\"record_ref\":{\"additionalProperties\":false,\"properties\":{\"entry_sha256\":{\"$ref\":\"#/$defs/sha256\"},\"epistemic_class\":{\"enum\":[\"ASSUMPTION\",\"UNTRUSTED_MODEL_OUTPUT\",\"OBSERVED\",\"VERIFIED\",\"DERIVED\"],\"type\":\"string\"},\"parent_entry_sha256s\":{\"items\":{\"$ref\":\"#/$defs/sha256\"},\"type\":\"array\",\"uniqueItems\":true},\"provenance_root_entry_sha256s\":{\"items\":{\"$ref\":\"#/$defs/sha256\"},\"minItems\":1,\"type\":\"array\",\"uniqueItems\":true},\"sequence\":{\"minimum\":0,\"type\":\"integer\"},\"source_fingerprint\":{\"$ref\":\"#/$defs/nonblank\"},\"source_id\":{\"$ref\":\"#/$defs/nonblank\"},\"source_kind\":{\"enum\":[\"HUMAN_INPUT\",\"LOCAL_OBSERVATION\",\"DETERMINISTIC_TOOL\",\"MODEL_OUTPUT\",\"HISTORICAL_ARTIFACT\",\"DERIVATION\"],\"type\":\"string\"}},\"required\":[\"entry_sha256\",\"sequence\",\"epistemic_class\",\"source_kind\",\"source_id\",\"source_fingerprint\",\"parent_entry_sha256s\",\"provenance_root_entry_sha256s\"],\"type\":\"object\"},\"relevant_relation\":{\"additionalProperties\":false,\"properties\":{\"entry_sha256\":{\"$ref\":\"#/$defs/sha256\"},\"epistemic_class\":{\"enum\":[\"ASSUMPTION\",\"UNTRUSTED_MODEL_OUTPUT\",\"OBSERVED\",\"VERIFIED\",\"DERIVED\"],\"type\":\"string\"},\"object_entry_sha256\":{\"$ref\":\"#/$defs/sha256\"},\"relation_type\":{\"enum\":[\"SUPPORTS\",\"CONTRADICTS\"],\"type\":\"string\"},\"sequence\":{\"minimum\":0,\"type\":\"integer\"},\"source_fingerprint\":{\"$ref\":\"#/$defs/nonblank\"},\"source_id\":{\"$ref\":\"#/$defs/nonblank\"},\"source_kind\":{\"enum\":[\"HUMAN_INPUT\",\"LOCAL_OBSERVATION\",\"DETERMINISTIC_TOOL\",\"MODEL_OUTPUT\",\"HISTORICAL_ARTIFACT\",\"DERIVATION\"],\"type\":\"string\"},\"subject_entry_sha256\":{\"$ref\":\"#/$defs/sha256\"}},\"required\":[\"entry_sha256\",\"sequence\",\"relation_type\",\"subject_entry_sha256\",\"object_entry_sha256\",\"epistemic_class\",\"source_kind\",\"source_id\",\"source_fingerprint\"],\"type\":\"object\"},\"sha256\":{\"pattern\":\"^[0-9a-f]{64}$\",\"type\":\"string\"},\"support_cycle\":{\"items\":{\"$ref\":\"#/$defs/sha256\"},\"minItems\":1,\"type\":\"array\",\"uniqueItems\":true}},\"$id\":\"gg.belief-view.v1\",\"$schema\":\"https://json-schema.org/draft/2020-12/schema\",\"additionalProperties\":false,\"properties\":{\"claim_views\":{\"items\":{\"$ref\":\"#/$defs/claim_view\"},\"minItems\":1,\"type\":\"array\"},\"conflict_present\":{\"type\":\"boolean\"},\"ledger_head_sha256\":{\"oneOf\":[{\"type\":\"null\"},{\"$ref\":\"#/$defs/sha256\"}]},\"ledger_record_count\":{\"minimum\":0,\"type\":\"integer\"},\"relevant_relations\":{\"items\":{\"$ref\":\"#/$defs/relevant_relation\"},\"type\":\"array\"},\"relevant_support_cycles\":{\"items\":{\"$ref\":\"#/$defs/support_cycle\"},\"type\":\"array\"},\"requested_claim_keys\":{\"items\":{\"$ref\":\"#/$defs/nonblank\"},\"minItems\":1,\"type\":\"array\",\"uniqueItems\":true},\"schema\":{\"const\":\"gg.belief-view.v1\",\"type\":\"string\"},\"source_schema\":{\"const\":\"gg.epistemic-ledger-record.v1\",\"type\":\"string\"},\"support_cycle_present\":{\"type\":\"boolean\"}},\"required\":[\"schema\",\"source_schema\",\"ledger_head_sha256\",\"ledger_record_count\",\"requested_claim_keys\",\"claim_views\",\"relevant_relations\",\"relevant_support_cycles\",\"conflict_present\",\"support_cycle_present\"],\"title\":\"GG Belief View v1\",\"type\":\"object\"}"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_TOP_FIELDS = frozenset((
    "schema",
    "source_schema",
    "ledger_head_sha256",
    "ledger_record_count",
    "requested_claim_keys",
    "claim_views",
    "relevant_relations",
    "relevant_support_cycles",
    "conflict_present",
    "support_cycle_present",
))
_CLAIM_VIEW_FIELDS = frozenset(("claim_key", "state", "candidates"))
_CANDIDATE_FIELDS = frozenset(("claim_id", "statement", "record_refs"))
_RECORD_REF_FIELDS = frozenset((
    "entry_sha256",
    "sequence",
    "epistemic_class",
    "source_kind",
    "source_id",
    "source_fingerprint",
    "parent_entry_sha256s",
    "provenance_root_entry_sha256s",
))
_RELATION_FIELDS = frozenset((
    "entry_sha256",
    "sequence",
    "relation_type",
    "subject_entry_sha256",
    "object_entry_sha256",
    "epistemic_class",
    "source_kind",
    "source_id",
    "source_fingerprint",
))


class BeliefViewError(ValueError):
    def __init__(
        self,
        code: str,
        cause_code: str | None = None,
    ) -> None:
        message = code if cause_code is None else code + ":" + cause_code
        super().__init__(message)
        self.code = code
        self.cause_code = cause_code


def _fail(code: str) -> None:
    raise BeliefViewError(code)


def _authority_fail(cause_code: str) -> None:
    raise BeliefViewError(
        "SOURCE_LEDGER_AUTHORITY_INVALID",
        cause_code,
    )


def _exact_fields(
    value: Any,
    wanted: frozenset[str],
    code: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(code)
    if frozenset(value) != wanted:
        _fail(code)
    return value


def _nonblank(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        _fail(code)
    return value


def _sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _string_array(
    value: Any,
    code: str,
    *,
    allow_empty: bool,
    sha256: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        _fail(code)
    if not allow_empty and not value:
        _fail(code)

    result: list[str] = []
    for item in value:
        if sha256:
            result.append(_sha256(item, code))
        else:
            result.append(_nonblank(item, code))

    if len(result) != len(set(result)):
        _fail(code)
    return result


def _source_path() -> pathlib.Path:
    own = pathlib.Path(os.path.abspath(__file__))
    return own.parent / SOURCE_LEDGER_RUNTIME_FILENAME


def _read_source_bytes() -> tuple[pathlib.Path, bytes]:
    if not hasattr(os, "O_NOFOLLOW"):
        _authority_fail("O_NOFOLLOW_UNAVAILABLE")
    if not hasattr(os, "O_CLOEXEC"):
        _authority_fail("O_CLOEXEC_UNAVAILABLE")

    path = _source_path()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW

    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BeliefViewError(
            "SOURCE_LEDGER_AUTHORITY_INVALID",
            "OPEN_FAILED",
        ) from exc

    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _authority_fail("NOT_REGULAR")

        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(fd)
        data = b"".join(chunks)

        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or len(data) != after.st_size
        ):
            _authority_fail("READ_STATE_CHANGED")
    finally:
        os.close(fd)

    if hashlib.sha256(data).hexdigest() != SOURCE_LEDGER_RUNTIME_SHA256:
        _authority_fail("SHA256_MISMATCH")

    return path, data


def _load_source_authority() -> dict[str, Any]:
    path, captured = _read_source_bytes()

    try:
        code = compile(
            captured,
            str(path),
            "exec",
            dont_inherit=True,
            optimize=0,
        )
    except BaseException as exc:
        raise BeliefViewError(
            "SOURCE_LEDGER_AUTHORITY_INVALID",
            "COMPILE_FAILED",
        ) from exc

    namespace: dict[str, Any] = {
        "__name__": "_gg_epistemic_ledger_bound",
        "__file__": str(path),
        "__package__": None,
    }

    try:
        exec(code, namespace, namespace)
    except BaseException as exc:
        raise BeliefViewError(
            "SOURCE_LEDGER_AUTHORITY_INVALID",
            "EXEC_FAILED",
        ) from exc

    if namespace.get("SCHEMA_ID") != SOURCE_LEDGER_SCHEMA_ID:
        _authority_fail("SCHEMA_ID_MISMATCH")

    for name in SOURCE_LEDGER_REQUIRED_PRIMITIVES:
        if not callable(namespace.get(name)):
            _authority_fail("PRIMITIVE_MISSING:" + name)

    error_type = namespace.get("LedgerError")
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _authority_fail("LEDGER_ERROR_TYPE_MISSING")

    return namespace


def _source_call(
    source: dict[str, Any],
    name: str,
    *args: Any,
) -> Any:
    error_type = source["LedgerError"]
    try:
        return source[name](*args)
    except error_type as exc:
        cause = getattr(exc, "code", None)
        if not isinstance(cause, str) or not cause:
            cause = type(exc).__name__
        raise BeliefViewError(
            "SOURCE_LEDGER_INVALID",
            cause,
        ) from exc


def schema_document() -> dict[str, Any]:
    value = json.loads(_SCHEMA_JSON)
    if not isinstance(value, dict):
        _fail("BELIEF_VIEW_INVALID")
    return value


def validate_view(value: Any) -> dict[str, Any]:
    view = _exact_fields(value, _TOP_FIELDS, "BELIEF_VIEW_INVALID")

    if view["schema"] != SCHEMA_ID:
        _fail("BELIEF_VIEW_INVALID")
    if view["source_schema"] != SOURCE_LEDGER_SCHEMA_ID:
        _fail("BELIEF_VIEW_INVALID")

    head = view["ledger_head_sha256"]
    if head is not None:
        _sha256(head, "BELIEF_VIEW_INVALID")

    count = view["ledger_record_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        _fail("BELIEF_VIEW_INVALID")
    if (count == 0) != (head is None):
        _fail("BELIEF_VIEW_INVALID")

    requested = _string_array(
        view["requested_claim_keys"],
        "BELIEF_VIEW_INVALID",
        allow_empty=False,
    )
    if requested != sorted(requested):
        _fail("BELIEF_VIEW_INVALID")

    claim_views = view["claim_views"]
    if not isinstance(claim_views, list) or len(claim_views) != len(requested):
        _fail("BELIEF_VIEW_INVALID")

    seen_keys: list[str] = []
    any_claim_conflict = False

    for raw_claim_view in claim_views:
        claim_view = _exact_fields(
            raw_claim_view,
            _CLAIM_VIEW_FIELDS,
            "BELIEF_VIEW_INVALID",
        )
        key = _nonblank(claim_view["claim_key"], "BELIEF_VIEW_INVALID")
        seen_keys.append(key)

        state_value = claim_view["state"]
        if state_value not in VIEW_STATES:
            _fail("BELIEF_VIEW_INVALID")

        candidates = claim_view["candidates"]
        if not isinstance(candidates, list):
            _fail("BELIEF_VIEW_INVALID")

        if state_value == "ABSENT" and candidates:
            _fail("BELIEF_VIEW_INVALID")
        if state_value == "UNCONTESTED" and len(candidates) != 1:
            _fail("BELIEF_VIEW_INVALID")
        if state_value == "CONFLICT" and len(candidates) < 2:
            _fail("BELIEF_VIEW_INVALID")
        if state_value == "CONFLICT":
            any_claim_conflict = True

        candidate_ids: list[str] = []
        for raw_candidate in candidates:
            candidate = _exact_fields(
                raw_candidate,
                _CANDIDATE_FIELDS,
                "BELIEF_VIEW_INVALID",
            )
            candidate_id = _sha256(
                candidate["claim_id"],
                "BELIEF_VIEW_INVALID",
            )
            candidate_ids.append(candidate_id)
            _nonblank(candidate["statement"], "BELIEF_VIEW_INVALID")

            refs = candidate["record_refs"]
            if not isinstance(refs, list) or not refs:
                _fail("BELIEF_VIEW_INVALID")

            sequences: list[int] = []
            for raw_ref in refs:
                ref = _exact_fields(
                    raw_ref,
                    _RECORD_REF_FIELDS,
                    "BELIEF_VIEW_INVALID",
                )
                _sha256(ref["entry_sha256"], "BELIEF_VIEW_INVALID")
                sequence = ref["sequence"]
                if (
                    isinstance(sequence, bool)
                    or not isinstance(sequence, int)
                    or sequence < 0
                ):
                    _fail("BELIEF_VIEW_INVALID")
                sequences.append(sequence)

                if ref["epistemic_class"] not in EPISTEMIC_CLASSES:
                    _fail("BELIEF_VIEW_INVALID")
                if ref["source_kind"] not in SOURCE_KINDS:
                    _fail("BELIEF_VIEW_INVALID")
                _nonblank(ref["source_id"], "BELIEF_VIEW_INVALID")
                _nonblank(ref["source_fingerprint"], "BELIEF_VIEW_INVALID")

                parents = _string_array(
                    ref["parent_entry_sha256s"],
                    "BELIEF_VIEW_INVALID",
                    allow_empty=True,
                    sha256=True,
                )
                if parents != list(ref["parent_entry_sha256s"]):
                    _fail("BELIEF_VIEW_INVALID")

                roots = _string_array(
                    ref["provenance_root_entry_sha256s"],
                    "BELIEF_VIEW_INVALID",
                    allow_empty=False,
                    sha256=True,
                )
                if roots != sorted(roots):
                    _fail("BELIEF_VIEW_INVALID")

            if sequences != sorted(sequences):
                _fail("BELIEF_VIEW_INVALID")

        if candidate_ids != sorted(candidate_ids):
            _fail("BELIEF_VIEW_INVALID")

    if seen_keys != requested:
        _fail("BELIEF_VIEW_INVALID")

    relations = view["relevant_relations"]
    if not isinstance(relations, list):
        _fail("BELIEF_VIEW_INVALID")

    relation_sequences: list[int] = []
    contradicts = False
    for raw_relation in relations:
        relation = _exact_fields(
            raw_relation,
            _RELATION_FIELDS,
            "BELIEF_VIEW_INVALID",
        )
        _sha256(relation["entry_sha256"], "BELIEF_VIEW_INVALID")
        sequence = relation["sequence"]
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
        ):
            _fail("BELIEF_VIEW_INVALID")
        relation_sequences.append(sequence)

        relation_type = relation["relation_type"]
        if relation_type not in RELATION_TYPES:
            _fail("BELIEF_VIEW_INVALID")
        if relation_type == "CONTRADICTS":
            contradicts = True

        _sha256(relation["subject_entry_sha256"], "BELIEF_VIEW_INVALID")
        _sha256(relation["object_entry_sha256"], "BELIEF_VIEW_INVALID")
        if relation["epistemic_class"] not in EPISTEMIC_CLASSES:
            _fail("BELIEF_VIEW_INVALID")
        if relation["source_kind"] not in SOURCE_KINDS:
            _fail("BELIEF_VIEW_INVALID")
        _nonblank(relation["source_id"], "BELIEF_VIEW_INVALID")
        _nonblank(relation["source_fingerprint"], "BELIEF_VIEW_INVALID")

    if relation_sequences != sorted(relation_sequences):
        _fail("BELIEF_VIEW_INVALID")

    cycles = view["relevant_support_cycles"]
    if not isinstance(cycles, list):
        _fail("BELIEF_VIEW_INVALID")

    normalized_cycles: list[tuple[str, ...]] = []
    for raw_cycle in cycles:
        cycle = _string_array(
            raw_cycle,
            "BELIEF_VIEW_INVALID",
            allow_empty=False,
            sha256=True,
        )
        if cycle != sorted(cycle):
            _fail("BELIEF_VIEW_INVALID")
        normalized_cycles.append(tuple(cycle))

    if normalized_cycles != sorted(normalized_cycles):
        _fail("BELIEF_VIEW_INVALID")
    if len(normalized_cycles) != len(set(normalized_cycles)):
        _fail("BELIEF_VIEW_INVALID")

    conflict = view["conflict_present"]
    support = view["support_cycle_present"]
    if not isinstance(conflict, bool) or not isinstance(support, bool):
        _fail("BELIEF_VIEW_INVALID")
    if conflict != (any_claim_conflict or contradicts):
        _fail("BELIEF_VIEW_INVALID")
    if support != bool(cycles):
        _fail("BELIEF_VIEW_INVALID")

    return view


def _requested_keys(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail("REQUESTED_CLAIM_KEYS_REQUIRED")

    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or not item.strip():
            _fail("REQUESTED_CLAIM_KEY_INVALID")
        result.append(item)

    if len(result) != len(set(result)):
        _fail("REQUESTED_CLAIM_KEYS_DUPLICATE")

    return sorted(result)


def reconstruct_belief_view(
    records: list[dict[str, Any]],
    requested_claim_keys: list[str],
) -> dict[str, Any]:
    if not isinstance(records, list):
        _fail("BELIEF_VIEW_INPUT_RECORDS_INVALID")

    requested = _requested_keys(requested_claim_keys)
    source = _load_source_authority()

    head = _source_call(source, "verify_chain", records)
    roots = _source_call(source, "provenance_roots", records)
    cycles = _source_call(source, "support_cycles", records)

    claim_records: dict[str, dict[str, Any]] = {
        record["entry_sha256"]: record
        for record in records
        if record["record_type"] == "CLAIM"
    }

    selected_entries = {
        entry
        for entry, record in claim_records.items()
        if record["body"]["claim_key"] in requested
    }

    claim_views: list[dict[str, Any]] = []

    for key in requested:
        groups: dict[str, dict[str, Any]] = {}

        for record in records:
            if record["record_type"] != "CLAIM":
                continue
            body = record["body"]
            if body["claim_key"] != key:
                continue

            claim_id_value = body["claim_id"]
            group = groups.setdefault(
                claim_id_value,
                {
                    "claim_id": claim_id_value,
                    "statement": body["statement"],
                    "record_refs": [],
                },
            )

            if group["statement"] != body["statement"]:
                _fail("BELIEF_VIEW_INVALID")

            group["record_refs"].append({
                "entry_sha256": record["entry_sha256"],
                "sequence": record["sequence"],
                "epistemic_class": body["epistemic_class"],
                "source_kind": body["source_kind"],
                "source_id": body["source_id"],
                "source_fingerprint": body["source_fingerprint"],
                "parent_entry_sha256s": list(body["parent_entry_sha256s"]),
                "provenance_root_entry_sha256s": sorted(
                    roots[record["entry_sha256"]]
                ),
            })

        candidates = [
            groups[claim_id_value]
            for claim_id_value in sorted(groups)
        ]

        for candidate in candidates:
            candidate["record_refs"].sort(
                key=lambda item: item["sequence"]
            )

        if not candidates:
            state_value = "ABSENT"
        elif len(candidates) == 1:
            state_value = "UNCONTESTED"
        else:
            state_value = "CONFLICT"

        claim_views.append({
            "claim_key": key,
            "state": state_value,
            "candidates": candidates,
        })

    relevant_relations: list[dict[str, Any]] = []

    for record in records:
        if record["record_type"] != "RELATION":
            continue
        body = record["body"]
        if (
            body["subject_entry_sha256"] not in selected_entries
            and body["object_entry_sha256"] not in selected_entries
        ):
            continue

        relevant_relations.append({
            "entry_sha256": record["entry_sha256"],
            "sequence": record["sequence"],
            "relation_type": body["relation_type"],
            "subject_entry_sha256": body["subject_entry_sha256"],
            "object_entry_sha256": body["object_entry_sha256"],
            "epistemic_class": body["epistemic_class"],
            "source_kind": body["source_kind"],
            "source_id": body["source_id"],
            "source_fingerprint": body["source_fingerprint"],
        })

    relevant_relations.sort(
        key=lambda item: item["sequence"]
    )

    relevant_cycles = [
        list(cycle)
        for cycle in cycles
        if any(member in selected_entries for member in cycle)
    ]
    relevant_cycles.sort(key=tuple)

    conflict_present = (
        any(view["state"] == "CONFLICT" for view in claim_views)
        or any(
            relation["relation_type"] == "CONTRADICTS"
            for relation in relevant_relations
        )
    )

    result: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "source_schema": SOURCE_LEDGER_SCHEMA_ID,
        "ledger_head_sha256": head,
        "ledger_record_count": len(records),
        "requested_claim_keys": requested,
        "claim_views": claim_views,
        "relevant_relations": relevant_relations,
        "relevant_support_cycles": relevant_cycles,
        "conflict_present": conflict_present,
        "support_cycle_present": bool(relevant_cycles),
    }

    validate_view(result)
    return result
