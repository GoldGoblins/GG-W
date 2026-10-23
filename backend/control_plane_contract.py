#!/usr/bin/env python3
"""Typed command and runtime-ledger contract for GG Control Plane v1.

The control plane coordinates already bounded Workbench operations.  It does
not add shell, network, arbitrary executable, arbitrary path, or model
self-authorization capability.
"""

from __future__ import annotations

from backend.platform_files import (
    NOFOLLOW,
    is_link,
    mode_matches,
    owned_by_current_user,
    secure_open,
    set_private_mode,
    sync_directory,
)
from backend.platform_support import (
    desktop_relative_path,
)


import hashlib

import json
import os
import re
import stat
from pathlib import Path
from typing import Any


CONTROL_AUTHORITY = "CONTROL_ONLY_NO_NEW_EXECUTION_AUTHORITY_V1"
BOOTSTRAP_APPLY_AUTHORITY = "YELLOW_EXACT_VERIFIED_MAIN_PY_APPLY_V1"
TARGET_RELATIVE_PATH = desktop_relative_path("main.py")

LEGACY_TASK_RECORD_SCHEMA = "gg.workbench.control-task.v1"
TASK_RECORD_SCHEMA = "gg.workbench.control-task.v2"
APPLY_REQUEST_SCHEMA = "gg.workbench.control-apply-request.v1"
APPLY_RESPONSE_SCHEMA = "gg.workbench.control-apply-response.v1"

TASK_ID_RE = re.compile(r"task-[0-9a-f]{32}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
HEAD_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

LEGACY_TASK_KINDS = frozenset(
    ("AUTONOMY", "SELFDEV", "BOOTSTRAP")
)
TASK_KINDS = LEGACY_TASK_KINDS | frozenset(
    ("ACTION",)
)
ACTIVE_STATUSES = frozenset(
    (
        "STARTING",
        "RUNNING",
        "GENERATING",
        "VERIFYING_HOST",
        "APPLYING",
        "STOPPING",
    )
)
TERMINAL_STATUSES = frozenset(
    (
        "DONE",
        "BLOCKED",
        "CANCELLED",
        "REJECTED",
        "STOPPED_BY_USER",
        "CLEANED",
    )
)
PENDING_STATUSES = frozenset(
    (
        "WAITING_GRANT",
        "WAITING_HOST_APPLY",
        "WAITING_PERSISTENT_APPLY",
    )
)
LEGACY_TASK_STATUSES = (
    ACTIVE_STATUSES
    | TERMINAL_STATUSES
    | PENDING_STATUSES
)

ACTION_STATUSES = frozenset(
    (
        "CREATED",
        "PLANNING",
        "GATHERING",
        "WAITING_FOR_USER",
        "APPROVED",
        "RUNNING",
        "VERIFYING",
        "DONE",
        "BLOCKED",
        "STOPPED",
    )
)

ACTION_TERMINAL_STATUSES = frozenset(
    (
        "DONE",
        "BLOCKED",
        "STOPPED",
    )
)

ACTION_REPLAY_STATES = frozenset(
    (
        "",
        "UNUSED",
        "DISPATCHED",
        "CONSUMED_PASS",
        "CONSUMED_FAILED",
        "CONSUMED_START_FAILED",
        "REJECTED",
        "STOPPED",
        "RESTART_BLOCKED",
    )
)

ACTION_TRANSITIONS = {
    "CREATED": frozenset(
        (
            "PLANNING",
            "GATHERING",
            "WAITING_FOR_USER",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "PLANNING": frozenset(
        (
            "GATHERING",
            "WAITING_FOR_USER",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "GATHERING": frozenset(
        (
            "PLANNING",
            "WAITING_FOR_USER",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "WAITING_FOR_USER": frozenset(
        (
            "APPROVED",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "APPROVED": frozenset(
        (
            "RUNNING",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "RUNNING": frozenset(
        (
            "VERIFYING",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "VERIFYING": frozenset(
        (
            "DONE",
            "BLOCKED",
            "STOPPED",
        )
    ),
    "DONE": frozenset(),
    "BLOCKED": frozenset(),
    "STOPPED": frozenset(),
}

TASK_STATUSES = (
    LEGACY_TASK_STATUSES
    | ACTION_STATUSES
)

MAX_GOAL_CHARS = 4096
MAX_LOG_LINES = 200
MAX_LOG_CHARS = 4096
MAX_RECORD_BYTES = 131072

LEGACY_TASK_RECORD_FIELDS = frozenset(
    (
        "schema",
        "task_id",
        "kind",
        "status",
        "goal",
        "context_reference",
        "workspace_object_id",
        "base_head",
        "candidate_sha256",
        "diff_sha256",
        "grant_sha256",
        "write_proposal_id",
        "write_candidate_sha256",
        "write_before_sha256",
        "parent_task_id",
        "last_reason",
        "created_seq",
        "updated_seq",
        "logs",
    )
)

TASK_RECORD_FIELDS = (
    LEGACY_TASK_RECORD_FIELDS
    | frozenset(
        (
            "original_intent",
            "why",
            "source_task_id",
            "action_binding_sha256",
            "state_base_revision",
            "continuity_sha256",
            "mandate_sha256",
            "evidence_sha256",
            "effects_sha256",
            "done_when",
            "action_replay_state",
        )
    )
)

MAX_CONTINUITY_TEXT_CHARS = 32768
MAX_OBJECT_BYTES = 262144


class ControlContractError(ValueError):
    """A fail-closed control-command or task-record contract error."""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _no_argument(command: str, argument: str) -> None:
    if argument:
        raise ControlContractError("Usage: " + command)


def _task_id(value: str) -> str:
    if TASK_ID_RE.fullmatch(value) is None:
        raise ControlContractError("Task id must be task- followed by 32 lowercase hex characters.")
    return value


def parse_control_command(text: str) -> dict[str, object] | None:
    """Parse only Control Plane commands; leave other slash commands alone."""

    value = text.strip()
    if not value.startswith("/"):
        return None

    command, separator, remainder = value.partition(" ")
    command = command.lower()
    argument = remainder.strip() if separator else ""

    if command in ("/help", "/commands"):
        _no_argument(command, argument)
        return {"action": "HELP"}

    if command == "/status":
        if not argument:
            return {"action": "STATUS", "task_id": ""}
        return {"action": "STATUS", "task_id": _task_id(argument)}

    if command == "/tasks":
        _no_argument(command, argument)
        return {"action": "TASKS"}

    if command == "/stop":
        if not argument:
            return {"action": "STOP", "task_id": ""}
        return {"action": "STOP", "task_id": _task_id(argument)}

    if command in ("/inspect", "/diff", "/resume", "/cleanup"):
        parts = argument.split()
        if len(parts) != 1:
            raise ControlContractError("Usage: " + command + " task-<id>")
        return {
            "action": command[1:].upper(),
            "task_id": _task_id(parts[0]),
        }

    if command == "/logs":
        parts = argument.split()
        if len(parts) not in (1, 2):
            raise ControlContractError("Usage: /logs task-<id> [1..200]")
        tail = 40
        if len(parts) == 2:
            try:
                tail = int(parts[1], 10)
            except ValueError as exc:
                raise ControlContractError("Log tail must be an integer from 1 to 200.") from exc
            if not 1 <= tail <= MAX_LOG_LINES:
                raise ControlContractError("Log tail must be an integer from 1 to 200.")
        return {
            "action": "LOGS",
            "task_id": _task_id(parts[0]),
            "tail": tail,
        }

    if command == "/bootstrap":
        if not argument or len(argument) > MAX_GOAL_CHARS or "\x00" in argument:
            raise ControlContractError("Usage: /bootstrap GOAL")
        return {"action": "BOOTSTRAP", "goal": argument}

    if command == "/approve-task":
        parts = argument.split()
        if len(parts) != 3:
            raise ControlContractError(
                "Usage: /approve-task task-<id> <candidate_sha256> <base_head>"
            )
        task_id, candidate_sha, base_head = parts
        _task_id(task_id)
        if SHA256_RE.fullmatch(candidate_sha) is None:
            raise ControlContractError("Candidate SHA-256 is invalid.")
        if HEAD_RE.fullmatch(base_head) is None:
            raise ControlContractError("Base HEAD is invalid.")
        return {
            "action": "APPROVE_TASK",
            "task_id": task_id,
            "candidate_sha256": candidate_sha,
            "base_head": base_head,
        }

    if command == "/reject-task":
        parts = argument.split()
        if len(parts) != 2:
            raise ControlContractError(
                "Usage: /reject-task task-<id> <candidate_sha256>"
            )
        task_id, candidate_sha = parts
        _task_id(task_id)
        if SHA256_RE.fullmatch(candidate_sha) is None:
            raise ControlContractError("Candidate SHA-256 is invalid.")
        return {
            "action": "REJECT_TASK",
            "task_id": task_id,
            "candidate_sha256": candidate_sha,
        }

    if command in ("/doctor", "/context"):
        _no_argument(command, argument)
        return {"action": command[1:].upper()}

    return None


def help_text() -> str:
    return "\n".join(
        (
            "GG CONTROL PLANE v1 · explicit typed commands",
            "",
            "/help | /commands",
            "  Visa denna verifierade kommandolista.",
            "/status [TASK_ID]",
            "  Visa aktiv process eller en exakt task.",
            "/tasks",
            "  Lista task-bundna autonomy/selfdev/bootstrap-arbeten.",
            "/inspect TASK_ID",
            "  Visa säker taskmetadata och nästa tillåtna steg.",
            "/stop [TASK_ID]",
            "  TERM och därefter KILL vid behov; idempotent utan aktiv task.",
            "/logs TASK_ID [TAIL]",
            "  Visa 1–200 senaste ledger-rader (standard 40).",
            "/diff TASK_ID",
            "  Visa en hashverifierad candidate-diff.",
            "/resume TASK_ID",
            "  Fortsätt vid approval-boundary eller skapa ett länkat retry-försök.",
            "/cleanup TASK_ID",
            "  Radera endast avslutad tasks runtime-evidens efter explicit kommando.",
            "/doctor",
            "  Kontrollera repo, runtime, target, runners och lokal render-enhet.",
            "/context",
            "  Visa exakt @current path, bytes och SHA-256 utan att skriva.",
            "",
            "/bootstrap GOAL",
            "  Starta bounded verifierad main.py-kandidat; host-write är NONE.",
            "/approve-task TASK_ID CANDIDATE_SHA BASE_HEAD",
            "  Atomisk apply av exakt verifierad main.py-kandidat.",
            "/reject-task TASK_ID CANDIDATE_SHA",
            "  Avvisa exakt kandidat utan host-write.",
            "",
            "Befintliga GREEN: /read /search /git /test /run",
            "Befintlig YELLOW current-QML: /patch-current /approve-write /reject-write /rollback-write",
            "Befintlig taskmotor: /autonomy /approve-autonomy /cancel-autonomy /selfdev",
            "",
            "SAKNAS AVSIKTLIGT: /shell, /exec och godtycklig argv/path/network-authority.",
        )
    )


def _blank_record(
    task_id: str,
    kind: str,
    status: str,
    goal: str,
    context_reference: str,
    workspace_object_id: str,
    created_seq: int,
) -> dict[str, object]:
    return {
        "schema": TASK_RECORD_SCHEMA,
        "task_id": task_id,
        "kind": kind,
        "status": status,
        "goal": goal,
        "context_reference": context_reference,
        "workspace_object_id": workspace_object_id,
        "base_head": "",
        "candidate_sha256": "",
        "diff_sha256": "",
        "grant_sha256": "",
        "write_proposal_id": "",
        "write_candidate_sha256": "",
        "write_before_sha256": "",
        "parent_task_id": "",
        "last_reason": "",
        "created_seq": created_seq,
        "updated_seq": 0,
        "logs": [],
        "original_intent": "",
        "why": "",
        "source_task_id": "",
        "action_binding_sha256": "",
        "state_base_revision": "",
        "continuity_sha256": "",
        "mandate_sha256": "",
        "evidence_sha256": "",
        "effects_sha256": "",
        "done_when": "",
        "action_replay_state": "",
    }


def validate_task_record(
    value: Any,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != TASK_RECORD_FIELDS
    ):
        raise ControlContractError(
            "Task record fields are invalid."
        )

    if value["schema"] != TASK_RECORD_SCHEMA:
        raise ControlContractError(
            "Task record schema is invalid."
        )

    _task_id(value["task_id"])

    if value["kind"] not in TASK_KINDS:
        raise ControlContractError(
            "Task kind is invalid."
        )

    if value["kind"] == "ACTION":
        if value["status"] not in ACTION_STATUSES:
            raise ControlContractError(
                "Action task status is invalid."
            )
    elif value["status"] not in LEGACY_TASK_STATUSES:
        raise ControlContractError(
            "Legacy task status is invalid."
        )

    for key in (
        "goal",
        "context_reference",
        "workspace_object_id",
        "base_head",
        "candidate_sha256",
        "diff_sha256",
        "grant_sha256",
        "write_proposal_id",
        "write_candidate_sha256",
        "write_before_sha256",
        "parent_task_id",
        "last_reason",
        "source_task_id",
        "action_replay_state",
    ):
        if (
            type(value[key]) is not str
            or len(value[key]) > MAX_GOAL_CHARS
            or "\x00" in value[key]
        ):
            raise ControlContractError(
                "Task string field is invalid: "
                + key
            )

    for key in (
        "original_intent",
        "why",
        "done_when",
    ):
        if (
            type(value[key]) is not str
            or len(value[key])
            > MAX_CONTINUITY_TEXT_CHARS
            or "\x00" in value[key]
        ):
            raise ControlContractError(
                "Task continuity text is invalid: "
                + key
            )

    if not value["goal"]:
        raise ControlContractError(
            "Task goal is invalid."
        )

    if (
        value["base_head"]
        and HEAD_RE.fullmatch(
            value["base_head"]
        )
        is None
    ):
        raise ControlContractError(
            "Task base HEAD is invalid."
        )

    for key in (
        "candidate_sha256",
        "diff_sha256",
        "grant_sha256",
        "write_candidate_sha256",
        "write_before_sha256",
        "action_binding_sha256",
        "state_base_revision",
        "continuity_sha256",
        "mandate_sha256",
        "evidence_sha256",
        "effects_sha256",
    ):
        if (
            value[key]
            and SHA256_RE.fullmatch(
                value[key]
            )
            is None
        ):
            raise ControlContractError(
                "Task SHA field is invalid: "
                + key
            )

    if value["parent_task_id"]:
        _task_id(value["parent_task_id"])

    for key in (
        "created_seq",
        "updated_seq",
    ):
        if (
            type(value[key]) is not int
            or value[key] < 0
        ):
            raise ControlContractError(
                "Task sequence is invalid: "
                + key
            )

    logs = value["logs"]

    if (
        type(logs) is not list
        or len(logs) > MAX_LOG_LINES
    ):
        raise ControlContractError(
            "Task logs are invalid."
        )

    for line in logs:
        if (
            type(line) is not str
            or len(line) > MAX_LOG_CHARS
            or "\x00" in line
        ):
            raise ControlContractError(
                "Task log line is invalid."
            )

    if value["kind"] == "ACTION":
        for key in (
            "original_intent",
            "why",
            "source_task_id",
            "action_binding_sha256",
            "state_base_revision",
            "continuity_sha256",
            "mandate_sha256",
            "evidence_sha256",
            "effects_sha256",
            "action_replay_state",
        ):
            if not value[key]:
                raise ControlContractError(
                    "Action continuity field missing: "
                    + key
                )

        if (
            value["action_replay_state"]
            not in ACTION_REPLAY_STATES
        ):
            raise ControlContractError(
                "Action replay state is invalid."
            )

    return dict(value)


def _validate_legacy_task_record(
    value: Any,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value)
        != LEGACY_TASK_RECORD_FIELDS
    ):
        raise ControlContractError(
            "Legacy task fields are invalid."
        )

    if (
        value["schema"]
        != LEGACY_TASK_RECORD_SCHEMA
    ):
        raise ControlContractError(
            "Legacy task schema is invalid."
        )

    _task_id(value["task_id"])

    if value["kind"] not in LEGACY_TASK_KINDS:
        raise ControlContractError(
            "Legacy task kind is invalid."
        )

    if value["status"] not in LEGACY_TASK_STATUSES:
        raise ControlContractError(
            "Legacy task status is invalid."
        )

    for key in (
        "goal",
        "context_reference",
        "workspace_object_id",
        "base_head",
        "candidate_sha256",
        "diff_sha256",
        "grant_sha256",
        "write_proposal_id",
        "write_candidate_sha256",
        "write_before_sha256",
        "parent_task_id",
        "last_reason",
    ):
        if (
            type(value[key]) is not str
            or len(value[key]) > MAX_GOAL_CHARS
            or "\x00" in value[key]
        ):
            raise ControlContractError(
                "Legacy task string invalid: "
                + key
            )

    if not value["goal"]:
        raise ControlContractError(
            "Legacy task goal is invalid."
        )

    if (
        value["base_head"]
        and HEAD_RE.fullmatch(
            value["base_head"]
        )
        is None
    ):
        raise ControlContractError(
            "Legacy base HEAD is invalid."
        )

    for key in (
        "candidate_sha256",
        "diff_sha256",
        "grant_sha256",
        "write_candidate_sha256",
        "write_before_sha256",
    ):
        if (
            value[key]
            and SHA256_RE.fullmatch(
                value[key]
            )
            is None
        ):
            raise ControlContractError(
                "Legacy SHA invalid: "
                + key
            )

    if value["parent_task_id"]:
        _task_id(value["parent_task_id"])

    for key in (
        "created_seq",
        "updated_seq",
    ):
        if (
            type(value[key]) is not int
            or value[key] < 0
        ):
            raise ControlContractError(
                "Legacy sequence invalid: "
                + key
            )

    logs = value["logs"]

    if (
        type(logs) is not list
        or len(logs) > MAX_LOG_LINES
    ):
        raise ControlContractError(
            "Legacy logs invalid."
        )

    for line in logs:
        if (
            type(line) is not str
            or len(line) > MAX_LOG_CHARS
            or "\x00" in line
        ):
            raise ControlContractError(
                "Legacy log invalid."
            )

    return dict(value)


def _upgrade_legacy_task_record(
    value: dict[str, object],
) -> dict[str, object]:
    legacy = _validate_legacy_task_record(
        value
    )

    upgraded = _blank_record(
        str(legacy["task_id"]),
        str(legacy["kind"]),
        str(legacy["status"]),
        str(legacy["goal"]),
        str(legacy["context_reference"]),
        str(legacy["workspace_object_id"]),
        int(legacy["created_seq"]),
    )

    for key in LEGACY_TASK_RECORD_FIELDS:
        if key == "schema":
            continue
        upgraded[key] = legacy[key]

    upgraded["schema"] = TASK_RECORD_SCHEMA

    return validate_task_record(
        upgraded
    )


class TaskLedger:
    """Owner-only durable task ledger with v1 import."""

    def __init__(
        self,
        root: Path,
        *,
        legacy_root: Path | None = None,
    ) -> None:
        self.root = root
        self.objects_root = (
            self.root / "objects"
        )
        self.legacy_root = legacy_root
        self.records: dict[
            str,
            dict[str, object],
        ] = {}
        self._next_seq = 1
        self._prepare_root()
        self._load()
        self._import_legacy()

    def _prepare_real_dir(
        self,
        path: Path,
    ) -> None:
        if path.exists() or path.is_symlink():
            info = path.lstat()

            if (
                is_link(path)
                or not stat.S_ISDIR(
                    info.st_mode
                )
            ):
                raise ControlContractError(
                    "Ledger directory is invalid."
                )

            if not owned_by_current_user(path):
                raise ControlContractError(
                    "Ledger directory owner mismatch."
                )

            set_private_mode(path, 0o700)
        else:
            path.mkdir(mode=0o700)
            set_private_mode(path, 0o700)

    def _prepare_root(self) -> None:
        parent = self.root.parent.resolve(
            strict=True
        )

        if self.root.parent != parent:
            raise ControlContractError(
                "Ledger parent must be canonical."
            )

        parent_info = parent.stat()

        if not owned_by_current_user(parent):
            raise ControlContractError(
                "Ledger parent owner mismatch."
            )

        self._prepare_real_dir(
            self.root
        )
        self._prepare_real_dir(
            self.objects_root
        )

    def _path(
        self,
        task_id: str,
    ) -> Path:
        _task_id(task_id)
        return self.root / (
            task_id + ".json"
        )

    def _object_path(
        self,
        digest: str,
    ) -> Path:
        if SHA256_RE.fullmatch(digest) is None:
            raise ControlContractError(
                "Object SHA-256 is invalid."
            )
        return self.objects_root / (
            digest + ".json"
        )

    def _canonical_object(
        self,
        value: Any,
    ) -> bytes:
        try:
            data = (
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ControlContractError(
                "Object is not canonical JSON."
            ) from exc

        if len(data) > MAX_OBJECT_BYTES:
            raise ControlContractError(
                "Object exceeds byte limit."
            )

        return data

    def put_object(
        self,
        value: Any,
    ) -> str:
        data = self._canonical_object(
            value
        )
        digest = hashlib.sha256(
            data
        ).hexdigest()
        target = self._object_path(
            digest
        )

        if target.exists() or target.is_symlink():
            if (
                target.is_symlink()
                or not target.is_file()
            ):
                raise ControlContractError(
                    "Object target is invalid."
                )

            info = target.stat()

            if not owned_by_current_user(target):
                raise ControlContractError(
                    "Object owner mismatch."
                )

            if target.read_bytes() != data:
                raise ControlContractError(
                    "Content-addressed object collision."
                )

            if (
                not mode_matches(target, 0o600)
            ):
                raise ControlContractError(
                    "Object mode mismatch."
                )

            return digest

        temporary = self.objects_root / (
            ".object."
            + str(os.getpid())
            + "."
            + os.urandom(8).hex()
        )

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
        )

        if hasattr(os, "O_NOFOLLOW"):
            flags |= NOFOLLOW

        fd = secure_open(
            temporary,
            flags,
            0o600,
        )

        try:
            with os.fdopen(
                fd,
                "wb",
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            set_private_mode(temporary, 0o600)

            try:
                os.link(
                    temporary,
                    target,
                    follow_symlinks=False,
                )
            except FileExistsError:
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or target.read_bytes()
                    != data
                ):
                    raise ControlContractError(
                        "Object race mismatch."
                    )

            sync_directory(self.objects_root)

        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

        if (
            target.is_symlink()
            or not target.is_file()
            or target.read_bytes() != data
        ):
            raise ControlContractError(
                "Object persistence mismatch."
            )

        set_private_mode(target, 0o600)

        return digest

    def get_object(
        self,
        digest: str,
    ) -> Any:
        path = self._object_path(
            digest
        )

        if (
            path.is_symlink()
            or not path.is_file()
        ):
            raise ControlContractError(
                "Object is missing."
            )

        info = path.stat()

        if (
            not owned_by_current_user(path)
            or not mode_matches(path, 0o600)
        ):
            raise ControlContractError(
                "Object metadata mismatch."
            )

        data = path.read_bytes()

        if hashlib.sha256(
            data
        ).hexdigest() != digest:
            raise ControlContractError(
                "Object hash mismatch."
            )

        try:
            return json.loads(
                data.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ControlContractError(
                "Object JSON invalid."
            ) from exc

    def _load_one(
        self,
        path: Path,
    ) -> tuple[
        dict[str, object],
        bool,
    ]:
        if (
            path.is_symlink()
            or not path.is_file()
        ):
            raise ControlContractError(
                "Task path invalid."
            )

        if path.stat().st_size > MAX_RECORD_BYTES:
            raise ControlContractError(
                "Task record too large."
            )

        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ControlContractError(
                "Task JSON invalid."
            ) from exc

        upgraded = False

        if (
            isinstance(raw, dict)
            and raw.get("schema")
            == LEGACY_TASK_RECORD_SCHEMA
        ):
            record = (
                _upgrade_legacy_task_record(
                    raw
                )
            )
            upgraded = True
        else:
            record = validate_task_record(
                raw
            )

        return record, upgraded

    def _restart_block(
        self,
        record: dict[str, object],
    ) -> bool:
        if record["kind"] == "ACTION":
            if (
                record["status"]
                not in ACTION_TERMINAL_STATUSES
            ):
                previous = str(
                    record[
                        "continuity_sha256"
                    ]
                )

                restart_object = {
                    "schema":
                        "gg.workbench."
                        "action-continuity-restart.v1",
                    "task_id":
                        record["task_id"],
                    "previous_status":
                        record["status"],
                    "previous_continuity_sha256":
                        previous,
                    "new_status": "BLOCKED",
                    "last_reason":
                        "WORKBENCH_RESTART_"
                        "REQUIRES_REVALIDATION_"
                        "NO_REPLAY",
                    "action_replay_state":
                        "RESTART_BLOCKED",
                }

                record["status"] = (
                    "BLOCKED"
                )
                record["last_reason"] = (
                    "WORKBENCH_RESTART_"
                    "REQUIRES_REVALIDATION_"
                    "NO_REPLAY"
                )
                record[
                    "action_replay_state"
                ] = "RESTART_BLOCKED"
                record[
                    "continuity_sha256"
                ] = self.put_object(
                    restart_object
                )
                record["updated_seq"] = (
                    int(
                        record[
                            "updated_seq"
                        ]
                    )
                    + 1
                )
                return True

            return False

        if record["status"] in ACTIVE_STATUSES:
            record["status"] = "BLOCKED"
            record["last_reason"] = (
                "WORKBENCH_RESTARTED_"
                "DURING_ACTIVE_TASK"
            )
            record["updated_seq"] = (
                int(record["updated_seq"])
                + 1
            )
            return True

        return False

    def _load(self) -> None:
        changed: list[str] = []

        for path in sorted(
            self.root.glob("task-*.json")
        ):
            try:
                record, upgraded = (
                    self._load_one(path)
                )
            except ControlContractError:
                continue

            if (
                path.name
                != str(record["task_id"])
                + ".json"
            ):
                continue

            restart_changed = (
                self._restart_block(
                    record
                )
            )

            task_id = str(
                record["task_id"]
            )

            self.records[task_id] = (
                validate_task_record(
                    record
                )
            )

            self._next_seq = max(
                self._next_seq,
                int(
                    record["created_seq"]
                )
                + 1,
            )

            if (
                upgraded
                or restart_changed
            ):
                changed.append(task_id)

        for task_id in changed:
            self._persist(task_id)

    def _import_legacy(self) -> None:
        root = self.legacy_root

        if root is None:
            return

        if (
            not root.exists()
            and not root.is_symlink()
        ):
            return

        if (
            root.is_symlink()
            or not root.is_dir()
        ):
            raise ControlContractError(
                "Legacy ledger root invalid."
            )

        if not owned_by_current_user(root):
            raise ControlContractError(
                "Legacy ledger owner mismatch."
            )

        for path in sorted(
            root.glob("task-*.json")
        ):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size
                > MAX_RECORD_BYTES
            ):
                continue

            try:
                raw = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )
                record = (
                    _upgrade_legacy_task_record(
                        raw
                    )
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ControlContractError,
            ):
                continue

            task_id = str(
                record["task_id"]
            )

            if (
                path.name
                != task_id + ".json"
                or task_id in self.records
            ):
                continue

            self._restart_block(record)

            self.records[task_id] = (
                validate_task_record(
                    record
                )
            )

            self._next_seq = max(
                self._next_seq,
                int(
                    record["created_seq"]
                )
                + 1,
            )

            self._persist(task_id)

    def _persist(
        self,
        task_id: str,
    ) -> None:
        record = validate_task_record(
            self.records[task_id]
        )

        data = (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        if len(data) > MAX_RECORD_BYTES:
            raise ControlContractError(
                "Task record exceeds byte limit."
            )

        path = self._path(task_id)
        temporary = self.root / (
            "."
            + task_id
            + ".tmp."
            + str(os.getpid())
            + "."
            + os.urandom(8).hex()
        )

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
        )

        if hasattr(os, "O_NOFOLLOW"):
            flags |= NOFOLLOW

        fd = secure_open(
            temporary,
            flags,
            0o600,
        )

        try:
            with os.fdopen(
                fd,
                "wb",
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            set_private_mode(temporary, 0o600)

            os.replace(
                temporary,
                path,
            )

            set_private_mode(path, 0o600)
            sync_directory(self.root)

        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def create(
        self,
        task_id: str,
        kind: str,
        status: str,
        goal: str,
        context_reference: str,
        workspace_object_id: str,
        **fields: object,
    ) -> dict[str, object]:
        if task_id in self.records:
            raise ControlContractError(
                "Task already exists in ledger."
            )

        record = _blank_record(
            task_id,
            kind,
            status,
            goal,
            context_reference,
            workspace_object_id,
            self._next_seq,
        )

        self._next_seq += 1

        for key, value in fields.items():
            if (
                key not in TASK_RECORD_FIELDS
                or key
                in (
                    "schema",
                    "task_id",
                    "kind",
                    "created_seq",
                    "updated_seq",
                    "logs",
                )
            ):
                raise ControlContractError(
                    "Task create field is invalid: "
                    + key
                )

            record[key] = value

        self.records[task_id] = (
            validate_task_record(
                record
            )
        )
        self._persist(task_id)

        return dict(
            self.records[task_id]
        )

    def get(
        self,
        task_id: str,
    ) -> dict[str, object] | None:
        record = self.records.get(
            task_id
        )

        return (
            dict(record)
            if record is not None
            else None
        )

    def update(
        self,
        task_id: str,
        **fields: object,
    ) -> dict[str, object]:
        if task_id not in self.records:
            raise ControlContractError(
                "Task not found in ledger."
            )

        record = dict(
            self.records[task_id]
        )

        requested_status = fields.get(
            "status"
        )

        if (
            record["kind"] == "ACTION"
            and isinstance(
                requested_status,
                str,
            )
            and requested_status
            != record["status"]
        ):
            allowed = ACTION_TRANSITIONS[
                str(record["status"])
            ]

            if requested_status not in allowed:
                raise ControlContractError(
                    "Action lifecycle transition "
                    "is invalid: "
                    + str(record["status"])
                    + "->"
                    + requested_status
                )

        for key, value in fields.items():
            if (
                key not in TASK_RECORD_FIELDS
                or key
                in (
                    "schema",
                    "task_id",
                    "kind",
                    "created_seq",
                    "updated_seq",
                    "logs",
                )
            ):
                raise ControlContractError(
                    "Task update field is invalid: "
                    + key
                )

            record[key] = value

        record["updated_seq"] = (
            int(record["updated_seq"])
            + 1
        )

        self.records[task_id] = (
            validate_task_record(
                record
            )
        )
        self._persist(task_id)

        return dict(
            self.records[task_id]
        )

    def append_log(
        self,
        task_id: str,
        line: str,
    ) -> None:
        if task_id not in self.records:
            return

        clean = (
            line.replace("\x00", "")
            .strip()
        )

        if not clean:
            return

        clean = clean[:MAX_LOG_CHARS]

        record = dict(
            self.records[task_id]
        )
        logs = list(record["logs"])
        logs.append(clean)

        record["logs"] = logs[
            -MAX_LOG_LINES:
        ]
        record["updated_seq"] = (
            int(record["updated_seq"])
            + 1
        )

        self.records[task_id] = (
            validate_task_record(
                record
            )
        )
        self._persist(task_id)

    def all(
        self,
    ) -> list[dict[str, object]]:
        return [
            dict(item)
            for item in sorted(
                self.records.values(),
                key=lambda record: int(
                    record["created_seq"]
                ),
            )
        ]

    def remove(
        self,
        task_id: str,
    ) -> None:
        path = self._path(task_id)

        try:
            path.unlink()
        except FileNotFoundError:
            pass

        self.records.pop(
            task_id,
            None,
        )


def task_summary(record: dict[str, object]) -> str:
    lines = [
        "TASK_ID=" + str(record["task_id"]),
        "KIND=" + str(record["kind"]),
        "STATUS=" + str(record["status"]),
        "GOAL=" + str(record["goal"]),
        "BASE_HEAD=" + (str(record["base_head"]) or "NONE"),
        "CANDIDATE_SHA256=" + (str(record["candidate_sha256"]) or "NONE"),
        "DIFF_SHA256=" + (str(record["diff_sha256"]) or "NONE"),
        "PARENT_TASK_ID=" + (str(record["parent_task_id"]) or "NONE"),
        "LAST_REASON=" + (str(record["last_reason"]) or "NONE"),
        "LOG_LINES=" + str(len(record["logs"])),
    ]
    if record["grant_sha256"]:
        lines.append("GRANT_SHA256=" + str(record["grant_sha256"]))
    if record["write_proposal_id"]:
        lines.append("WRITE_PROPOSAL_ID=" + str(record["write_proposal_id"]))
    return "\n".join(lines)


def validate_apply_request(value: Any) -> dict[str, str]:
    fields = {
        "schema",
        "action",
        "task_id",
        "base_head",
        "target_relative_path",
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise ControlContractError("Apply request fields are invalid.")
    if value["schema"] != APPLY_REQUEST_SCHEMA or value["action"] != "APPLY_SELFDEV":
        raise ControlContractError("Apply request schema/action is invalid.")
    _task_id(value["task_id"])
    if HEAD_RE.fullmatch(value["base_head"]) is None:
        raise ControlContractError("Apply base HEAD is invalid.")
    if value["target_relative_path"] != TARGET_RELATIVE_PATH:
        raise ControlContractError("Apply target path is invalid.")
    for key in ("before_sha256", "candidate_sha256", "diff_sha256"):
        if SHA256_RE.fullmatch(value[key]) is None:
            raise ControlContractError("Apply SHA field is invalid: " + key)
    return {key: str(value[key]) for key in fields}


def validate_apply_response(value: Any, request: dict[str, str]) -> dict[str, object]:
    fields = {
        "schema",
        "task_id",
        "status",
        "base_head",
        "before_sha256",
        "candidate_sha256",
        "host_after_sha256",
        "host_repo_changed",
        "output",
    }
    if type(value) is not dict or set(value) != fields:
        raise ControlContractError("Apply response fields are invalid.")
    if value["schema"] != APPLY_RESPONSE_SCHEMA:
        raise ControlContractError("Apply response schema is invalid.")
    if value["task_id"] != request["task_id"] or value["base_head"] != request["base_head"]:
        raise ControlContractError("Apply response task binding mismatch.")
    if value["before_sha256"] != request["before_sha256"]:
        raise ControlContractError("Apply response before SHA mismatch.")
    if value["candidate_sha256"] != request["candidate_sha256"]:
        raise ControlContractError("Apply response candidate SHA mismatch.")
    if value["status"] != "APPLIED_VERIFIED" or value["host_repo_changed"] is not True:
        raise ControlContractError("Apply response status is invalid.")
    if value["host_after_sha256"] != request["candidate_sha256"]:
        raise ControlContractError("Apply response posthash mismatch.")
    if type(value["output"]) is not str or not value["output"]:
        raise ControlContractError("Apply response output is invalid.")
    return dict(value)
