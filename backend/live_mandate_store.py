from __future__ import annotations
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


SCHEMA = "gg.live-mandate-record.v1"
GENERAL_ACTION_AUTHORITY = "NONE"
ACTION_AUTHORITY = "NONE"
TASK_SCOPED_GENERAL_ACTION_AUTHORITY = "TASK_SCOPED"
TASK_SCOPED_SCOPE_AUTHORITY = "ALL_TASK_SCOPED_EFFECTS"

STATES = (
    "PENDING",
    "APPROVED",
    "CONSUMED",
    "REJECTED",
    "REVOKED",
)

# These are control-plane invariants, not effect classes.  Every concrete
# effect (including network, production, one.com, credentials, deploy and
# sudo) can be named by the current mandate and carried by its single-use
# TASK_SCOPED grant.  Only authority bypass, scope drift/reuse and unbounded
# background execution stay impossible.
HARD_FORBIDDEN = (
    "approval bypass",
    "approval scope drift",
    "target scope drift",
    "cross-task grant reuse",
    "grant replay",
    "unbounded background autonomy",
    "automatic authority expansion",
)

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_RECORD_FIELDS = frozenset(
    {
        "schema",
        "seq",
        "status",
        "pending_id",
        "task_id",
        "origin_id",
        "request_capture_sha256",
        "approval_scope_revision",
        "mandate_requirement",
        "risk_class",
        "capability_human_id",
        "target_object_id",
        "target_source_revision",
        "action_intent_binding_sha256",
        "approver_id",
        "mandate_assertion_sha256",
        "evaluation_receipt",
        "general_action_authority",
        "action_authority",
        "record_sha256",
    }
)


class LiveMandateStoreError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LiveMandateStoreError("CANONICAL_JSON_INVALID") from exc
    return (rendered + "\n").encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise LiveMandateStoreError(label + "_INVALID")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise LiveMandateStoreError(label + "_INVALID")
    return value


def _text(value: Any, label: str, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\x00" in value
    ):
        raise LiveMandateStoreError(label + "_INVALID")
    return value.strip()


def _write_exclusive(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise LiveMandateStoreError("RECORD_EXISTS:" + path.name)
    fd = secure_open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _record_hash(record_without_hash: dict[str, Any]) -> str:
    if "record_sha256" in record_without_hash:
        raise LiveMandateStoreError("RECORD_HASH_SURFACE_INVALID")
    return _sha(record_without_hash)


def validate_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        raise LiveMandateStoreError("RECORD_SURFACE_INVALID")
    record = copy.deepcopy(value)
    if record["schema"] != SCHEMA:
        raise LiveMandateStoreError("RECORD_SCHEMA_INVALID")
    if record["status"] not in STATES:
        raise LiveMandateStoreError("RECORD_STATUS_INVALID")
    seq = record["seq"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise LiveMandateStoreError("RECORD_SEQ_INVALID")
    _identifier(record["pending_id"], "PENDING_ID")
    _identifier(record["task_id"], "TASK_ID")
    _identifier(record["origin_id"], "ORIGIN_ID")
    _sha_text(record["request_capture_sha256"], "REQUEST_CAPTURE_SHA256")
    _sha_text(record["approval_scope_revision"], "APPROVAL_SCOPE_REVISION")
    if record["mandate_requirement"] != "EXPLICIT_REQUIRED":
        raise LiveMandateStoreError("MANDATE_REQUIREMENT_NOT_EXPLICIT")
    if record["risk_class"] not in {"YELLOW", "RED"}:
        raise LiveMandateStoreError("RISK_CLASS_NOT_RED_OR_YELLOW")
    _identifier(record["capability_human_id"], "CAPABILITY_HUMAN_ID")
    _identifier(record["target_object_id"], "TARGET_OBJECT_ID")
    _sha_text(record["target_source_revision"], "TARGET_SOURCE_REVISION")
    _sha_text(
        record["action_intent_binding_sha256"],
        "ACTION_INTENT_BINDING_SHA256",
    )
    if record["general_action_authority"] != GENERAL_ACTION_AUTHORITY:
        raise LiveMandateStoreError("GENERAL_ACTION_AUTHORITY_DRIFT")
    if record["action_authority"] != ACTION_AUTHORITY:
        raise LiveMandateStoreError("STORE_IS_NOT_ACTION_AUTHORITY")

    if record["status"] == "APPROVED":
        _identifier(record["approver_id"], "APPROVER_ID")
        _sha_text(record["mandate_assertion_sha256"], "MANDATE_ASSERTION_SHA256")
        receipt = record["evaluation_receipt"]
        if not isinstance(receipt, dict):
            raise LiveMandateStoreError("EVALUATION_RECEIPT_INVALID")
        if receipt.get("result") != "MANDATE_VALID":
            raise LiveMandateStoreError("EVALUATION_RECEIPT_NOT_VALID")
    elif record["status"] in {"PENDING", "REJECTED", "REVOKED"}:
        if record["approver_id"] is not None:
            raise LiveMandateStoreError("APPROVER_ID_MUST_BE_NULL")
        if record["mandate_assertion_sha256"] is not None:
            raise LiveMandateStoreError("ASSERTION_MUST_BE_NULL")
        if record["evaluation_receipt"] is not None:
            raise LiveMandateStoreError("RECEIPT_MUST_BE_NULL")
    elif record["status"] == "CONSUMED":
        _identifier(record["approver_id"], "APPROVER_ID")
        _sha_text(record["mandate_assertion_sha256"], "MANDATE_ASSERTION_SHA256")
        if not isinstance(record["evaluation_receipt"], dict):
            raise LiveMandateStoreError("EVALUATION_RECEIPT_INVALID")

    without_hash = {
        key: copy.deepcopy(item)
        for key, item in record.items()
        if key != "record_sha256"
    }
    expected = _record_hash(without_hash)
    if record["record_sha256"] != expected:
        raise LiveMandateStoreError("RECORD_SHA256_MISMATCH")
    return record


def _finalize(record_without_hash: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(record_without_hash)
    value["record_sha256"] = _record_hash(copy.deepcopy(value))
    return validate_record(value)


class MandateStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.index = self.root / "index.jsonl"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.objects.mkdir(exist_ok=True, mode=0o700)
        if not self.index.exists():
            fd = secure_open(self.index, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)

    def _bucket(self, request_capture_sha256: str) -> Path:
        _sha_text(request_capture_sha256, "REQUEST_CAPTURE_SHA256")
        path = self.objects / request_capture_sha256
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _latest(self, request_capture_sha256: str) -> dict[str, Any] | None:
        bucket = self.objects / request_capture_sha256
        if not bucket.is_dir() or bucket.is_symlink():
            return None
        names = sorted(
            name
            for name in os.listdir(bucket)
            if name.endswith(".json") and not name.startswith(".")
        )
        if not names:
            return None
        path = bucket / names[-1]
        if path.is_symlink() or not path.is_file():
            raise LiveMandateStoreError("RECORD_PATH_INVALID")
        value = json.loads(path.read_text(encoding="utf-8"))
        return validate_record(value)

    def _append(self, record: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = validate_record(record)
        capture = validated["request_capture_sha256"]
        bucket = self._bucket(capture)
        name = f"{validated['seq']:04d}-{validated['status']}.json"
        path = bucket / name
        _write_exclusive(path, _canonical(validated))
        line = (
            json.dumps(
                {
                    "request_capture_sha256": capture,
                    "seq": validated["seq"],
                    "status": validated["status"],
                    "record_sha256": validated["record_sha256"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return validated

    def get(self, request_capture_sha256: str) -> dict[str, Any] | None:
        self.initialize()
        return self._latest(request_capture_sha256)

    def active_record(self) -> dict[str, Any] | None:
        self.initialize()
        if not self.index.is_file() or self.index.is_symlink():
            return None
        chosen: dict[str, Any] | None = None
        for raw in self.index.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            capture = row.get("request_capture_sha256")
            if not isinstance(capture, str):
                continue
            latest = self.get(capture)
            if latest is None:
                continue
            if latest["status"] in {"PENDING", "APPROVED"}:
                chosen = latest
        return chosen


def _from_pending(pending: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pending, dict):
        raise LiveMandateStoreError("PENDING_NOT_OBJECT")
    mandate_result = pending.get("mandate_result")
    if not isinstance(mandate_result, dict):
        raise LiveMandateStoreError("PENDING_MANDATE_RESULT_INVALID")
    action_intent = pending.get("action_intent")
    if not isinstance(action_intent, dict):
        raise LiveMandateStoreError("PENDING_ACTION_INTENT_INVALID")
    request = mandate_result.get("approval_request")
    if not isinstance(request, dict):
        raise LiveMandateStoreError("PENDING_APPROVAL_REQUEST_INVALID")
    ready = request.get("approval_scope", {})
    if not isinstance(ready, dict):
        raise LiveMandateStoreError("PENDING_APPROVAL_SCOPE_INVALID")
    ready_core = ready.get("ready_core", {})
    if not isinstance(ready_core, dict):
        raise LiveMandateStoreError("PENDING_READY_CORE_INVALID")
    risk_class = ready_core.get("risk_class")
    origin_id = request.get("origin_id")
    task_id = mandate_result.get("task_id") or request.get("task_id")
    return {
        "schema": SCHEMA,
        "pending_id": _identifier(pending.get("pending_id"), "PENDING_ID"),
        "task_id": _identifier(task_id, "TASK_ID"),
        "origin_id": _identifier(origin_id, "ORIGIN_ID"),
        "request_capture_sha256": _sha_text(
            pending.get("request_capture_sha256"),
            "REQUEST_CAPTURE_SHA256",
        ),
        "approval_scope_revision": _sha_text(
            pending.get("approval_scope_revision"),
            "APPROVAL_SCOPE_REVISION",
        ),
        "mandate_requirement": _text(
            mandate_result.get("mandate_requirement"),
            "MANDATE_REQUIREMENT",
        ),
        "risk_class": _text(risk_class, "RISK_CLASS"),
        "capability_human_id": _identifier(
            action_intent.get("capability_human_id"),
            "CAPABILITY_HUMAN_ID",
        ),
        "target_object_id": _identifier(
            action_intent.get("target_object_id"),
            "TARGET_OBJECT_ID",
        ),
        "target_source_revision": _sha_text(
            action_intent.get("target_source_revision"),
            "TARGET_SOURCE_REVISION",
        ),
        "action_intent_binding_sha256": _sha_text(
            action_intent.get("binding_sha256"),
            "ACTION_INTENT_BINDING_SHA256",
        ),
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "action_authority": ACTION_AUTHORITY,
    }


def put_pending(store: MandateStore, pending: dict[str, Any]) -> dict[str, Any]:
    base = _from_pending(pending)
    existing = store.get(base["request_capture_sha256"])
    if existing is not None:
        raise LiveMandateStoreError("REQUEST_CAPTURE_ALREADY_STORED")
    record = _finalize(
        {
            **base,
            "seq": 1,
            "status": "PENDING",
            "approver_id": None,
            "mandate_assertion_sha256": None,
            "evaluation_receipt": None,
        }
    )
    return store._append(record)


def _require_latest(
    store: MandateStore,
    request_capture_sha256: str,
    approval_scope_revision: str,
    expected_status: str,
) -> dict[str, Any]:
    latest = store.get(request_capture_sha256)
    if latest is None:
        raise LiveMandateStoreError("MANDATE_NOT_FOUND")
    if latest["approval_scope_revision"] != approval_scope_revision:
        raise LiveMandateStoreError("APPROVAL_SCOPE_DRIFT")
    if latest["status"] == "CONSUMED":
        raise LiveMandateStoreError("REPLAY_FORBIDDEN")
    if latest["status"] != expected_status:
        raise LiveMandateStoreError(
            "MANDATE_STATE_INVALID:" + latest["status"]
        )
    return latest


def approve(
    store: MandateStore,
    *,
    request_capture_sha256: str,
    approval_scope_revision: str,
    approver_id: str,
    mandate_assertion_sha256: str,
    evaluation_receipt: dict[str, Any],
) -> dict[str, Any]:
    latest = _require_latest(
        store,
        request_capture_sha256,
        approval_scope_revision,
        "PENDING",
    )
    if not isinstance(evaluation_receipt, dict):
        raise LiveMandateStoreError("EVALUATION_RECEIPT_INVALID")
    if evaluation_receipt.get("result") != "MANDATE_VALID":
        raise LiveMandateStoreError("EVALUATION_RECEIPT_NOT_VALID")
    if (
        evaluation_receipt.get("mandate_assertion_sha256")
        != mandate_assertion_sha256
    ):
        raise LiveMandateStoreError("ASSERTION_RECEIPT_MISMATCH")
    if (
        evaluation_receipt.get("request_capture_sha256")
        != request_capture_sha256
    ):
        raise LiveMandateStoreError("CAPTURE_RECEIPT_MISMATCH")
    if (
        evaluation_receipt.get("approval_scope_revision")
        != approval_scope_revision
    ):
        raise LiveMandateStoreError("SCOPE_RECEIPT_MISMATCH")
    next_record = copy.deepcopy(latest)
    next_record.pop("record_sha256")
    next_record["seq"] = latest["seq"] + 1
    next_record["status"] = "APPROVED"
    next_record["approver_id"] = _identifier(approver_id, "APPROVER_ID")
    next_record["mandate_assertion_sha256"] = _sha_text(
        mandate_assertion_sha256,
        "MANDATE_ASSERTION_SHA256",
    )
    next_record["evaluation_receipt"] = copy.deepcopy(evaluation_receipt)
    return store._append(_finalize(next_record))


def reject(
    store: MandateStore,
    *,
    request_capture_sha256: str,
    approval_scope_revision: str,
) -> dict[str, Any]:
    latest = _require_latest(
        store,
        request_capture_sha256,
        approval_scope_revision,
        "PENDING",
    )
    next_record = copy.deepcopy(latest)
    next_record.pop("record_sha256")
    next_record["seq"] = latest["seq"] + 1
    next_record["status"] = "REJECTED"
    return store._append(_finalize(next_record))


def consume(
    store: MandateStore,
    *,
    request_capture_sha256: str,
    approval_scope_revision: str,
) -> dict[str, Any]:
    latest = _require_latest(
        store,
        request_capture_sha256,
        approval_scope_revision,
        "APPROVED",
    )
    next_record = copy.deepcopy(latest)
    next_record.pop("record_sha256")
    next_record["seq"] = latest["seq"] + 1
    next_record["status"] = "CONSUMED"
    return store._append(_finalize(next_record))


def revoke(
    store: MandateStore,
    *,
    request_capture_sha256: str,
    approval_scope_revision: str,
) -> dict[str, Any]:
    latest = store.get(request_capture_sha256)
    if latest is None:
        raise LiveMandateStoreError("MANDATE_NOT_FOUND")
    if latest["approval_scope_revision"] != approval_scope_revision:
        raise LiveMandateStoreError("APPROVAL_SCOPE_DRIFT")
    if latest["status"] in {"CONSUMED", "REJECTED", "REVOKED"}:
        raise LiveMandateStoreError("MANDATE_STATE_INVALID:" + latest["status"])
    next_record = copy.deepcopy(latest)
    next_record.pop("record_sha256")
    next_record["seq"] = latest["seq"] + 1
    next_record["status"] = "REVOKED"
    next_record["approver_id"] = None
    next_record["mandate_assertion_sha256"] = None
    next_record["evaluation_receipt"] = None
    return store._append(_finalize(next_record))
