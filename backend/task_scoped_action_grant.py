from __future__ import annotations

from backend.platform_files import (
    NOFOLLOW,
    secure_open,
)


from backend.application_paths import STATE_ROOT

import copy
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from backend import live_mandate_store


SCHEMA = "gg.task-scoped-action-grant.v2"
GENERAL_ACTION_AUTHORITY = "TASK_SCOPED"
ACTION_AUTHORITY = "TASK_SCOPED"
SCOPE_AUTHORITY = live_mandate_store.TASK_SCOPED_SCOPE_AUTHORITY
AUTHORIZATION_SCHEMA = "gg.task-scoped-effect-authorization.v1"
RUNTIME_SCHEMA = "gg.task-scoped-runtime-authorization.v1"
DEFAULT_MANDATE_ROOT = Path(
    str(STATE_ROOT / 'mandate-store')
)
RUNTIME_NAME = "active-chat-task.json"

THIS_TASK = {
    "task_id": "task-live-mandate-store-task-scoped-action",
    "owner": "GG",
    "goal": (
        "After explicit in-chat human approval of a new YELLOW or RED task, grant "
        "TASK_SCOPED action for every explicitly named effect inside the "
        "hash-bound Idékompass scope. GENERAL_ACTION_AUTHORITY is "
        "TASK_SCOPED for this grant."
    ),
    "expected_value": (
        "A durable single-use mandate store plus a task-scoped grant that "
        "lets approved work continue across local, network, production, "
        "one.com, credentials, deploy, write and sudo effects without "
        "creating standing authority."
    ),
    "scope": [
        "live mandate store for EXPLICIT_REQUIRED YELLOW/RED tasks",
        "task-scoped grant after MANDATE_VALID",
        "all explicitly requested task-scoped effect classes",
        "local and external targets bound by sha256",
        "operator/capability paths carrying the authorization token",
    ],
    "forbidden_scope": [
        "approval bypass",
        "approval scope drift",
        "target scope drift",
        "cross-task grant reuse",
        "grant replay",
        "unbounded background autonomy",
        "automatic authority expansion",
        "GENERAL_ACTION_AUTHORITY other than TASK_SCOPED",
    ],
    "risk_class": "RED",
    "stop_conditions": [
        "approval_scope_revision drift",
        "target source sha256 drift",
        "replay of a consumed or approved request_capture",
        "attempt to inherit a previous mandate",
        "attempt to use an effect outside the approved hash-bound scope",
        "attempt to use the grant as standing or background authority",
    ],
    "expected_artifacts": [
        "backend/live_mandate_store.py",
        "backend/task_scoped_action_grant.py",
        "tests proving GREEN needs no grant",
        "tests proving YELLOW/RED require explicit mandate",
        "tests proving every explicit effect receives TASK_SCOPED authority only after approval",
    ],
    "acceptance_criteria": [
        "GREEN continues without extra approval",
        "YELLOW and RED stay EXPLICIT_REQUIRED",
        "MANDATE_VALID issues TASK_SCOPED for ALL_TASK_SCOPED_EFFECTS",
        "replay and hash drift fail closed",
        "network, production, one.com, credentials, deploy, write and sudo are task-scoped when explicitly approved",
        "K7-K ACTION_AUTHORITY remains NONE",
    ],
}

ONE_COM_MANDATE = {
    "task_id": "task-one-com-named-red",
    "owner": "GG",
    "goal": (
        "Named RED mandate for goldgoblins.se on one.com: local SITE "
        "inventory, network access, production write and deploy steps "
        "inside one hash-bound TASK_SCOPED approval."
    ),
    "expected_value": (
        "After explicit in-chat ja/yes approval, the listed one.com and production "
        "effects are available as TASK_SCOPED actions for this task only. "
        "Secrets are never persisted to chat or logs."
    ),
    "scope": [
        "local SITE copy under gg-ai-desktop/site",
        "local snippets, mu-plugins, and theme files",
        "network access to goldgoblins.se and one.com",
        "one.com login and production read/write/deploy",
        "credentials supplied through the approved visible operator flow",
    ],
    "forbidden_scope": [
        "password in chat",
        "credentials in logs or persisted files",
        "approval bypass",
        "approval scope drift",
        "target scope drift",
        "cross-task grant reuse",
        "grant replay",
        "unbounded background autonomy",
        "automatic authority expansion",
        "GENERAL_ACTION_AUTHORITY other than TASK_SCOPED",
    ],
    "risk_class": "RED",
    "stop_conditions": [
        "credentials appear in chat or files",
        "attempted autonomous login or SFTP with stored secrets",
        "approval_scope_revision drift",
        "mandate inherited from another task",
    ],
    "expected_artifacts": [
        "named RED ready_core for one.com",
        "rail shows TASK_SCOPED and ALL_TASK_SCOPED_EFFECTS after approval",
        "visible one.com operator path carrying the authorization token",
    ],
    "acceptance_criteria": [
        "ONE_COM_MANDATE.risk_class is RED",
        "YELLOW/RED still require explicit in-chat ja/yes approval",
        "GENERAL_ACTION_AUTHORITY is TASK_SCOPED only for the approved grant",
        "one.com and production effects remain bound to the approved task",
    ],
}

HARD_FORBIDDEN = live_mandate_store.HARD_FORBIDDEN

GRANT_STATUSES = ("ACTIVE", "CONSUMED", "DEAD")

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_GRANT_FIELDS = frozenset(
    {
        "schema",
        "general_action_authority",
        "action_authority",
        "scope_authority",
        "grant_status",
        "task_id",
        "pending_id",
        "request_capture_sha256",
        "approval_scope_revision",
        "mandate_assertion_sha256",
        "risk_class",
        "capability_human_id",
        "target_object_id",
        "target_source_revision",
        "forbidden_scope",
        "store_record_sha256",
        "grant_sha256",
    }
)

_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema",
        "authority",
        "general_action_authority",
        "action_authority",
        "scope_authority",
        "grant_status",
        "task_id",
        "pending_id",
        "grant_sha256",
        "effect",
        "target_object_id",
        "target_source_revision",
        "authorization_sha256",
    }
)

_EFFECT_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")


class TaskScopedActionGrantError(ValueError):
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
        raise TaskScopedActionGrantError("CANONICAL_JSON_INVALID") from exc
    return (rendered + "\n").encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise TaskScopedActionGrantError(label + "_INVALID")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise TaskScopedActionGrantError(label + "_INVALID")
    return value


def _effect(value: Any) -> str:
    if not isinstance(value, str) or _EFFECT_RE.fullmatch(value) is None:
        raise TaskScopedActionGrantError("EFFECT_INVALID")
    return value


def _forbidden(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TaskScopedActionGrantError("FORBIDDEN_SCOPE_INVALID")
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise TaskScopedActionGrantError("FORBIDDEN_SCOPE_ITEM_INVALID")
        text = item.strip()
        if text in seen:
            raise TaskScopedActionGrantError("FORBIDDEN_SCOPE_DUPLICATE")
        seen.add(text)
        items.append(text)
    for required in HARD_FORBIDDEN:
        if required not in seen:
            raise TaskScopedActionGrantError(
                "HARD_FORBIDDEN_MISSING:" + required
            )
    return tuple(items)


def validate_grant(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _GRANT_FIELDS:
        raise TaskScopedActionGrantError("GRANT_SURFACE_INVALID")
    grant = copy.deepcopy(value)
    if grant["schema"] != SCHEMA:
        raise TaskScopedActionGrantError("GRANT_SCHEMA_INVALID")
    if grant["general_action_authority"] != GENERAL_ACTION_AUTHORITY:
        raise TaskScopedActionGrantError("GENERAL_ACTION_AUTHORITY_DRIFT")
    if grant["action_authority"] != ACTION_AUTHORITY:
        raise TaskScopedActionGrantError("ACTION_AUTHORITY_NOT_TASK_SCOPED")
    if grant["scope_authority"] != SCOPE_AUTHORITY:
        raise TaskScopedActionGrantError("SCOPE_AUTHORITY_INVALID")
    if grant["grant_status"] not in GRANT_STATUSES:
        raise TaskScopedActionGrantError("GRANT_STATUS_INVALID")
    _identifier(grant["task_id"], "TASK_ID")
    _identifier(grant["pending_id"], "PENDING_ID")
    _sha_text(grant["request_capture_sha256"], "REQUEST_CAPTURE_SHA256")
    _sha_text(grant["approval_scope_revision"], "APPROVAL_SCOPE_REVISION")
    _sha_text(grant["mandate_assertion_sha256"], "MANDATE_ASSERTION_SHA256")
    if grant["risk_class"] not in {"YELLOW", "RED"}:
        raise TaskScopedActionGrantError("RISK_CLASS_NOT_RED_OR_YELLOW")
    _identifier(grant["capability_human_id"], "CAPABILITY_HUMAN_ID")
    _identifier(grant["target_object_id"], "TARGET_OBJECT_ID")
    _sha_text(grant["target_source_revision"], "TARGET_SOURCE_REVISION")
    grant["forbidden_scope"] = list(_forbidden(grant["forbidden_scope"]))
    _sha_text(grant["store_record_sha256"], "STORE_RECORD_SHA256")
    without_hash = {
        key: copy.deepcopy(item)
        for key, item in grant.items()
        if key != "grant_sha256"
    }
    expected = _sha(without_hash)
    if grant["grant_sha256"] != expected:
        raise TaskScopedActionGrantError("GRANT_SHA256_MISMATCH")
    return grant


def green_path_no_grant() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "general_action_authority": "NONE",
        "action_authority": "NONE",
        "scope_authority": "NONE",
        "grant_status": "DEAD",
        "reason_code": "GREEN_RISK_CLASS",
        "mandate_requirement": "NOT_REQUIRED",
    }


def issue_from_approved_record(record: dict[str, Any]) -> dict[str, Any]:
    stored = live_mandate_store.validate_record(record)
    if stored["status"] != "APPROVED":
        raise TaskScopedActionGrantError(
            "GRANT_REQUIRES_APPROVED_RECORD:" + stored["status"]
        )
    grant = {
        "schema": SCHEMA,
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "action_authority": ACTION_AUTHORITY,
        "scope_authority": SCOPE_AUTHORITY,
        "grant_status": "ACTIVE",
        "task_id": stored["task_id"],
        "pending_id": stored["pending_id"],
        "request_capture_sha256": stored["request_capture_sha256"],
        "approval_scope_revision": stored["approval_scope_revision"],
        "mandate_assertion_sha256": stored["mandate_assertion_sha256"],
        "risk_class": stored["risk_class"],
        "capability_human_id": stored["capability_human_id"],
        "target_object_id": stored["target_object_id"],
        "target_source_revision": stored["target_source_revision"],
        "forbidden_scope": list(HARD_FORBIDDEN),
        "store_record_sha256": stored["record_sha256"],
    }
    grant["grant_sha256"] = _sha(
        {
            key: copy.deepcopy(item)
            for key, item in grant.items()
            if key != "grant_sha256"
        }
    )
    return validate_grant(grant)


def authorize_effect(
    grant: dict[str, Any],
    *,
    effect: str,
    current_target_object_id: str,
    current_target_source_revision: str,
) -> dict[str, Any]:
    """Create a hash-bound authorization for one effect in the current task.

    The grant is universal within its approved task scope, but the token still
    carries the concrete effect and target so operators cannot silently reuse
    it for another task or a changed source.
    """
    bound = bind_current_target(
        grant,
        current_target_object_id=current_target_object_id,
        current_target_source_revision=current_target_source_revision,
    )
    authorization = {
        "schema": AUTHORIZATION_SCHEMA,
        "authority": ACTION_AUTHORITY,
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "action_authority": ACTION_AUTHORITY,
        "scope_authority": SCOPE_AUTHORITY,
        "grant_status": bound["grant_status"],
        "task_id": bound["task_id"],
        "pending_id": bound["pending_id"],
        "grant_sha256": bound["grant_sha256"],
        "effect": _effect(effect),
        "target_object_id": bound["target_object_id"],
        "target_source_revision": bound["target_source_revision"],
    }
    authorization["authorization_sha256"] = _sha(
        {
            key: copy.deepcopy(item)
            for key, item in authorization.items()
            if key != "authorization_sha256"
        }
    )
    return validate_authorization(authorization)


def validate_authorization(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _AUTHORIZATION_FIELDS:
        raise TaskScopedActionGrantError("AUTHORIZATION_SURFACE_INVALID")
    authorization = copy.deepcopy(value)
    if authorization["schema"] != AUTHORIZATION_SCHEMA:
        raise TaskScopedActionGrantError("AUTHORIZATION_SCHEMA_INVALID")
    if authorization["authority"] != ACTION_AUTHORITY:
        raise TaskScopedActionGrantError("AUTHORITY_NOT_TASK_SCOPED")
    if authorization["general_action_authority"] != GENERAL_ACTION_AUTHORITY:
        raise TaskScopedActionGrantError("GENERAL_ACTION_AUTHORITY_DRIFT")
    if authorization["action_authority"] != ACTION_AUTHORITY:
        raise TaskScopedActionGrantError("ACTION_AUTHORITY_NOT_TASK_SCOPED")
    if authorization["scope_authority"] != SCOPE_AUTHORITY:
        raise TaskScopedActionGrantError("SCOPE_AUTHORITY_INVALID")
    if authorization["grant_status"] != "ACTIVE":
        raise TaskScopedActionGrantError("AUTHORIZATION_GRANT_NOT_ACTIVE")
    _identifier(authorization["task_id"], "TASK_ID")
    _identifier(authorization["pending_id"], "PENDING_ID")
    _sha_text(authorization["grant_sha256"], "GRANT_SHA256")
    _effect(authorization["effect"])
    _identifier(authorization["target_object_id"], "TARGET_OBJECT_ID")
    _sha_text(
        authorization["target_source_revision"],
        "TARGET_SOURCE_REVISION",
    )
    _sha_text(authorization["authorization_sha256"], "AUTHORIZATION_SHA256")
    expected = _sha(
        {
            key: copy.deepcopy(item)
            for key, item in authorization.items()
            if key != "authorization_sha256"
        }
    )
    if authorization["authorization_sha256"] != expected:
        raise TaskScopedActionGrantError("AUTHORIZATION_SHA256_MISMATCH")
    return authorization


def bind_current_target(
    grant: dict[str, Any],
    *,
    current_target_object_id: str,
    current_target_source_revision: str,
) -> dict[str, Any]:
    validated = validate_grant(grant)
    if validated["grant_status"] != "ACTIVE":
        raise TaskScopedActionGrantError(
            "GRANT_NOT_ACTIVE:" + validated["grant_status"]
        )
    if validated["target_object_id"] != current_target_object_id:
        raise TaskScopedActionGrantError("TARGET_OBJECT_DRIFT")
    if validated["target_source_revision"] != current_target_source_revision:
        raise TaskScopedActionGrantError("TARGET_SOURCE_DRIFT")
    return validated


def publish_runtime_scope(
    grant: dict[str, Any],
    *,
    store_root: Path,
    allowed_hosts: Any = (),
) -> Path:
    """Publish only the active task pointer for local operator helpers.

    The pointer contains no user text or credentials.  Operators re-read the
    approved record from the mandate store before creating an effect token,
    so a stale, consumed or replaced grant cannot be reused silently.
    """
    validated = validate_grant(grant)
    if isinstance(allowed_hosts, str):
        raw_hosts = (allowed_hosts,)
    elif isinstance(allowed_hosts, (list, tuple, set, frozenset)):
        raw_hosts = tuple(allowed_hosts)
    else:
        raw_hosts = ()
    hosts: list[str] = []
    for value in raw_hosts:
        host = str(value or "").strip().lower().strip(".")
        if not host or len(host) > 253 or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host
        ):
            raise TaskScopedActionGrantError("RUNTIME_HOST_INVALID")
        if host not in hosts:
            hosts.append(host)
    payload = {
        "schema": RUNTIME_SCHEMA,
        "request_capture_sha256": validated["request_capture_sha256"],
        "approval_scope_revision": validated["approval_scope_revision"],
        "store_record_sha256": validated["store_record_sha256"],
        "task_id": validated["task_id"],
        "target_object_id": validated["target_object_id"],
        "target_source_revision": validated["target_source_revision"],
        "allowed_hosts": sorted(hosts),
    }
    root = Path(store_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / RUNTIME_NAME
    temporary = root / ("." + RUNTIME_NAME + "." + uuid.uuid4().hex)
    data = (_canonical(payload))
    fd = secure_open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return path


def _runtime_payload(store_root: Path) -> dict[str, Any] | None:
    path = Path(store_root) / RUNTIME_NAME
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fields = {
        "schema",
        "request_capture_sha256",
        "approval_scope_revision",
        "store_record_sha256",
        "task_id",
        "target_object_id",
        "target_source_revision",
        "allowed_hosts",
    }
    if not isinstance(value, dict) or set(value) != fields:
        return None
    try:
        if value["schema"] != RUNTIME_SCHEMA:
            return None
        for key in (
            "request_capture_sha256",
            "approval_scope_revision",
            "store_record_sha256",
            "target_source_revision",
        ):
            _sha_text(value[key], key.upper())
        _identifier(value["task_id"], "TASK_ID")
        _identifier(value["target_object_id"], "TARGET_OBJECT_ID")
        hosts = value["allowed_hosts"]
        if not isinstance(hosts, list) or len(hosts) > 32:
            return None
        normalized_hosts: list[str] = []
        for item in hosts:
            host = str(item or "").strip().lower().strip(".")
            if not host or len(host) > 253 or not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host
            ):
                return None
            if host in normalized_hosts:
                return None
            normalized_hosts.append(host)
    except TaskScopedActionGrantError:
        return None
    value["allowed_hosts"] = normalized_hosts
    return value


def runtime_authorize_effect(
    effect: str,
    *,
    store_root: Path | None = None,
    host: str = "",
) -> dict[str, Any] | None:
    """Resolve an effect token without exposing approval syntax to the user."""
    root = Path(store_root) if store_root is not None else DEFAULT_MANDATE_ROOT
    payload = _runtime_payload(root)
    if payload is None:
        return None
    current_host = str(host or "").strip().lower().strip(".")
    allowed_hosts = list(payload["allowed_hosts"])
    if current_host and (
        not allowed_hosts
        or not any(
            current_host == allowed
            or current_host.endswith("." + allowed)
            for allowed in allowed_hosts
        )
    ):
        return None
    try:
        store = live_mandate_store.MandateStore(root)
        record = store.get(str(payload["request_capture_sha256"]))
        if record is None or record.get("status") != "APPROVED":
            return None
        if (
            record.get("approval_scope_revision")
            != payload["approval_scope_revision"]
            or record.get("record_sha256") != payload["store_record_sha256"]
            or record.get("task_id") != payload["task_id"]
            or record.get("target_object_id") != payload["target_object_id"]
            or record.get("target_source_revision")
            != payload["target_source_revision"]
        ):
            return None
        grant = issue_from_approved_record(record)
        return authorize_effect(
            grant,
            effect=effect,
            current_target_object_id=str(payload["target_object_id"]),
            current_target_source_revision=str(
                payload["target_source_revision"]
            ),
        )
    except (OSError, ValueError, TaskScopedActionGrantError):
        return None
