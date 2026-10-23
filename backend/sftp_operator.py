from __future__ import annotations

from backend.application_paths import STATE_ROOT

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from backend import task_scoped_action_grant
from backend import web_surface


SCHEMA = "gg.sftp-operator-config.v1"
GENERAL_ACTION_AUTHORITY = "NONE"
from backend.platform_support import executable_path
SFTP_BIN = Path(executable_path("sftp"))
ROOT = Path(str(STATE_ROOT / 'sftp-operator'))
CONFIG_NAME = "config.json"
STAGING_NAME = "staging"
FORBIDDEN_CONFIG_KEYS = {"password", "passphrase", "secret", "token"}
PUT_ALLOWLIST = (
    "robots.txt",
    "wp-content/mu-plugins/gg-site-completion.php",
    "wp-content/mu-plugins/gg-site-local-legal.php",
    "wp-content/uploads/gg-local-site-sync.json",
    "wp-content/debug.log",
    "wp-content/uploads/gg-local-site-sync-status.json",
    "error_log",
    "wp-content/themes/blankslate/header.php",
    "wp-content/themes/blankslate/page.php",
    "wp-content/themes/blankslate/footer.php",
)
GET_ALLOWLIST = PUT_ALLOWLIST
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class SftpOperatorError(ValueError):
    pass


def _validate_task_scoped_authorization(
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return task_scoped_action_grant.validate_authorization(value)
    except task_scoped_action_grant.TaskScopedActionGrantError as exc:
        raise SftpOperatorError(
            "TASK_SCOPED_AUTHORIZATION_INVALID:" + str(exc)
        ) from exc


def ensure_root() -> Path:
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = ROOT / STAGING_NAME
    staging.mkdir(mode=0o700, exist_ok=True)
    return ROOT


def config_path() -> Path:
    return ensure_root() / CONFIG_NAME


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SftpOperatorError("CONFIG_NOT_OBJECT")
    if any(key in value for key in FORBIDDEN_CONFIG_KEYS):
        raise SftpOperatorError("CREDENTIAL_FIELD_FORBIDDEN")
    if value.get("schema") != SCHEMA:
        raise SftpOperatorError("CONFIG_SCHEMA_INVALID")
    host = str(value.get("host") or "")
    user = str(value.get("user") or "")
    remote_root = str(value.get("remote_root") or "").strip()
    identity = str(value.get("identity_file") or "").strip()
    port = value.get("port", 22)
    if not _HOST_RE.fullmatch(host):
        raise SftpOperatorError("HOST_INVALID")
    if not _USER_RE.fullmatch(user):
        raise SftpOperatorError("USER_INVALID")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SftpOperatorError("PORT_INVALID")
    if not remote_root.startswith("/") or ".." in Path(remote_root).parts:
        raise SftpOperatorError("REMOTE_ROOT_INVALID")
    if identity:
        ident = Path(identity).expanduser()
        if ident.is_symlink() or not ident.is_file():
            raise SftpOperatorError("IDENTITY_FILE_INVALID")
        if ident.parent != Path.home() / ".ssh":
            raise SftpOperatorError("IDENTITY_FILE_NOT_IN_SSH")
        identity = str(ident)
    return {
        "schema": SCHEMA,
        "host": host,
        "user": user,
        "port": port,
        "remote_root": remote_root,
        "identity_file": identity,
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "network": "TASK_SCOPED_SFTP",
    }


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file() or path.is_symlink():
        raise SftpOperatorError("CONFIG_MISSING")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SftpOperatorError("CONFIG_UNREADABLE") from exc
    return validate_config(value)


def _safe_rel(relative: str, allow: tuple[str, ...]) -> str:
    rel = str(relative or "").replace("\\", "/").strip()
    if rel not in allow:
        raise SftpOperatorError("PATH_NOT_ALLOWLISTED:" + rel)
    return rel


def batch_script(config: dict[str, Any], action: str, relative: str) -> str:
    cfg = validate_config(config)
    root = cfg["remote_root"].rstrip("/")
    if action == "GET":
        rel = _safe_rel(relative, GET_ALLOWLIST)
        return (
            "lcd "
            + (ROOT / STAGING_NAME).as_posix()
            + "\ncd "
            + root
            + "\nget "
            + rel
            + " "
            + Path(rel).name
            + "\nbye\n"
        )
    if action == "PUT":
        rel = _safe_rel(relative, PUT_ALLOWLIST)
        return (
            "lcd "
            + web_surface.SITE_ROOT.as_posix()
            + "\ncd "
            + root
            + "\nput "
            + rel
            + " "
            + rel
            + "\nbye\n"
        )
    raise SftpOperatorError("ACTION_INVALID")


def argv(config: dict[str, Any]) -> list[str]:
    cfg = validate_config(config)
    if not SFTP_BIN.is_file():
        raise SftpOperatorError("SFTP_BIN_MISSING")
    args = [
        str(SFTP_BIN),
        "-b",
        "-",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "AddressFamily=inet",
        "-P",
        str(cfg["port"]),
    ]
    if cfg["identity_file"]:
        args.extend(["-i", cfg["identity_file"]])
    args.append(cfg["user"] + "@" + cfg["host"])
    return args


def require_agent() -> None:
    sock = str(os.environ.get("SSH_AUTH_SOCK") or "")
    if not sock:
        raise SftpOperatorError("SSH_AGENT_REQUIRED")
    path = Path(sock)
    if path.is_symlink() or not path.exists():
        raise SftpOperatorError("SSH_AGENT_SOCKET_INVALID")


def plan(
    action: str,
    relative: str,
    config: dict[str, Any] | None = None,
    *,
    task_scoped_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = validate_config(config) if config is not None else load_config()
    script = batch_script(cfg, action, relative)
    if task_scoped_authorization is None:
        task_scoped_authorization = (
            task_scoped_action_grant.runtime_authorize_effect(
                "sftp." + str(action or "").strip().lower(),
                host=str(cfg["host"]),
            )
        )
    authorization = _validate_task_scoped_authorization(
        task_scoped_authorization
    )
    return {
        "schema": "gg.sftp-operator-plan.v1",
        "action": action,
        "relative": relative,
        "argv": argv(cfg),
        "batch": script,
        "action_authority": (
            authorization["action_authority"]
            if authorization is not None
            else "NONE"
        ),
        "general_action_authority": (
            authorization["general_action_authority"]
            if authorization is not None
            else GENERAL_ACTION_AUTHORITY
        ),
        "scope_authority": (
            authorization["scope_authority"]
            if authorization is not None
            else "NONE"
        ),
        "network_authority": (
            "TASK_SCOPED" if authorization is not None else "NONE"
        ),
        "task_scoped_authorization": authorization,
        "password": False,
        "risk_class": "RED",
    }


def run(
    action: str,
    relative: str,
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 20.0,
    task_scoped_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_agent()
    planned = plan(
        action,
        relative,
        config,
        task_scoped_authorization=task_scoped_authorization,
    )
    if planned.get("task_scoped_authorization") is None:
        raise SftpOperatorError("TASK_SCOPED_AUTHORIZATION_REQUIRED")
    try:
        proc = subprocess.run(
            list(planned["argv"]),
            input=str(planned["batch"]),
            capture_output=True,
            text=True,
            timeout=max(2.0, float(timeout)),
        )
    except subprocess.TimeoutExpired as exc:
        raise SftpOperatorError("SFTP_TIMEOUT") from exc
    if proc.returncode != 0:
        raise SftpOperatorError("SFTP_FAILED")
    return {
        "schema": "gg.sftp-operator-result.v1",
        "action": action,
        "relative": relative,
        "ok": True,
        "password": False,
        "risk_class": "RED",
    }
