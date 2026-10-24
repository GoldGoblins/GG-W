from __future__ import annotations
from backend.platform_support import runtime_root
from backend.platform_files import secure_open, NOFOLLOW

import argparse
from contextlib import contextmanager, closing
import json
import math
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from backend import task_scoped_action_grant
from backend import web_surface
from backend.platform_support import file_locks
from backend.platform_files import atomic_replace, is_link


SCHEMA_COMMAND = "gg.web-operator-command.v1"
SCHEMA_RESULT = "gg.web-operator-result.v1"
GENERAL_ACTION_AUTHORITY = "NONE"


def _runtime_operator_root() -> Path:
    """Return the shared writable IPC directory for the visible WEB pane.

    The model runner can expose the project state as read-only while the
    desktop host still needs to exchange command/result JSON with it.  Keep
    this short-lived transport under the per-user runtime directory instead
    of the persistent home/state tree.  No credentials are stored here.
    """
    if os.name == "nt":
        return runtime_root() / "web-operator"
    raw = str(
        os.environ.get("XDG_RUNTIME_DIR")
        or ("/run/user/" + str(os.getuid()))
    ).strip()
    runtime = Path(raw)
    if not runtime.is_absolute():
        runtime = Path("/run/user/" + str(os.getuid()))
    return runtime / "gg-ai-desktop" / "web-operator"


ROOT = _runtime_operator_root()
COMMAND_NAME = "command.json"
ACTIVE_NAME = "command.active.json"
RESULT_NAME = "result.json"
CANCEL_NAME = "cancelled.json"
HISTORY_NAME = "lifecycle.json"
RECEIPTS_NAME = "receipts.sqlite"
# Preserve the identity across the host's source reload, but never across an
# application restart. A claimed effect from a previous host is not replayed.
_HOST_SESSION = globals().get("_HOST_SESSION") or uuid.uuid4().hex
_MAX_RECORD_BYTES = 131072

ACTIONS = (
    "OPEN",
    "SNAPSHOT",
    "CLICK",
    "TYPE",
    "RELOAD",
    "BACK",
    "MOVE",
    "HOVER",
    "SCROLL",
    "WAIT",
    "STAGE",
    "KEY",
    "TAB_NEW",
    "TAB_CLOSE",
    "TAB_NEXT",
    "TAB_PREV",
    "FORWARD",
    "SELECT",
)
GREEN_ACTIONS = frozenset(
    {
        "SNAPSHOT",
        "RELOAD",
        "BACK",
        "MOVE",
        "WAIT",
        "STAGE",
        "TAB_NEW",
        "TAB_CLOSE",
        "TAB_NEXT",
        "TAB_PREV",
        "FORWARD",
    }
)
YELLOW_ACTIONS = frozenset(
    {"CLICK", "TYPE", "HOVER", "SCROLL", "OPEN", "KEY", "SELECT"}
)
KEYS = frozenset(
    {
        "Enter",
        "Tab",
        "Escape",
        "Space",
        "Backspace",
        "Delete",
        "Home",
        "End",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
    }
)
VIEW_NAME = "view.png"
RED_HOSTS = (
    "one.com",
    "www.one.com",
    "login.one.com",
    "www.login.one.com",
)
_PASSWORD_RE = re.compile(
    r"password|passwd|\bpwd\b|type\s*=\s*['\"]password['\"]",
    re.IGNORECASE,
)
_SHA_LIKE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_COORD_LO = -8000
_COORD_HI = 8000


class WebOperatorError(ValueError):
    pass


def _validate_task_scoped_authorization(
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return task_scoped_action_grant.validate_authorization(value)
    except task_scoped_action_grant.TaskScopedActionGrantError as exc:
        raise WebOperatorError(
            "TASK_SCOPED_AUTHORIZATION_INVALID:" + str(exc)
        ) from exc


def _authority_fields(command: dict[str, Any]) -> dict[str, Any]:
    authorization = _validate_task_scoped_authorization(
        command.get("task_scoped_authorization")
    )
    if authorization is None:
        return {
            "action_authority": "NONE",
            "general_action_authority": GENERAL_ACTION_AUTHORITY,
            "scope_authority": "NONE",
            "task_scoped_authorization": None,
        }
    return {
        "action_authority": authorization["action_authority"],
        "general_action_authority": authorization[
            "general_action_authority"
        ],
        "scope_authority": authorization["scope_authority"],
        "task_scoped_authorization": authorization,
    }


def ensure_root() -> Path:
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    return ROOT


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise WebOperatorError("FILE_EXISTS:" + path.name)
    fd = secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _transport_lock():
    ensure_root()
    fd = secure_open(ROOT / ".transport.lock", os.O_RDWR | os.O_CREAT | NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as handle:
        file_locks.flock(handle, file_locks.LOCK_EX)
        try:
            yield
        finally:
            file_locks.flock(handle, file_locks.LOCK_UN)


def _read_record(path: Path):
    if is_link(path):
        raise WebOperatorError("TRANSPORT_LINK_FORBIDDEN")
    try:
        fd = secure_open(path, os.O_RDONLY | NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(_MAX_RECORD_BYTES + 1)
    if len(raw) > _MAX_RECORD_BYTES:
        raise WebOperatorError("TRANSPORT_RECORD_TOO_LARGE")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise WebOperatorError("TRANSPORT_RECORD_INVALID") from exc


def _replace_record(path: Path, value) -> None:
    if is_link(path):
        raise WebOperatorError("TRANSPORT_LINK_FORBIDDEN")
    temporary = ROOT / (".record-" + uuid.uuid4().hex)
    try:
        _write_exclusive(temporary, _canonical(value))
        atomic_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _history_locked():
    rows = _read_record(ROOT / HISTORY_NAME) or []
    return rows[-63:] if isinstance(rows, list) else []


def _receipt_locked(command_id, state=None):
    """Permanent consumed IDs, separate from the bounded display history.

    Only an opaque command ID and state are retained, never command text or
    authorization. Trimming visible history cannot make an effect replayable.
    """
    path = ROOT / RECEIPTS_NAME
    if is_link(path):
        raise WebOperatorError("TRANSPORT_LINK_FORBIDDEN")
    if not path.exists():
        fd = secure_open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
        os.close(fd)
    with closing(sqlite3.connect(path, timeout=1.0)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS consumed(command_id TEXT PRIMARY KEY,state TEXT NOT NULL)")
        previous = db.execute("SELECT state FROM consumed WHERE command_id=?", (command_id,)).fetchone()
        if state is not None:
            db.execute("INSERT INTO consumed VALUES(?,?) ON CONFLICT(command_id) DO UPDATE SET state=excluded.state",
                       (command_id, state))
        db.commit()
        return previous[0] if previous else None


def _command_record_locked(name):
    path = ROOT / name
    try:
        raw = _read_record(path)
        if raw is not None:
            validate_command(raw)
        return raw
    except WebOperatorError:
        # A legacy/externally interrupted publication may be partial. Never
        # execute it or retain an invalid record as a permanent busy state.
        if is_link(path):
            raise
        path.unlink(missing_ok=True)
        _replace_record(ROOT / RESULT_NAME, {
            "schema": SCHEMA_RESULT, "command_id": "", "ok": False,
            "reason_code": "TRANSPORT_RECORD_INVALID", "transport_state": "INTERRUPTED",
            "completion_uncertain": name == ACTIVE_NAME})
        return None


def _terminal_locked(command, state, reason, *, notify=False, result=None):
    command_id = command["command_id"]
    rows = _history_locked()
    previous_state = _receipt_locked(command_id)
    if previous_state and previous_state != "CLAIMED":
        # A crash may have occurred between recording the tombstone and
        # publishing the result. Complete cleanup without replaying the effect.
        stored = _read_record(ROOT / RESULT_NAME)
        if not isinstance(stored, dict) or stored.get("command_id") != command_id:
            _replace_record(ROOT / RESULT_NAME, {
                **make_result(command, ok=False, reason_code="OPERATOR_INTERRUPTED"),
                "transport_state": "INTERRUPTED"})
        for name in (COMMAND_NAME, ACTIVE_NAME):
            path = ROOT / name
            record = _read_record(path)
            if isinstance(record, dict) and record.get("command_id") == command_id:
                path.unlink(missing_ok=True)
        return False
    _receipt_locked(command_id, state)
    rows.append({"command_id": command_id, "state": state, "finished_at": time.time()})
    # Persist the tombstone before publishing completion or clearing a claim.
    # Recovery never runs a command whose completion was already recorded.
    _replace_record(ROOT / HISTORY_NAME, rows)
    if notify:
        notices = _read_record(ROOT / CANCEL_NAME) or []
        if not isinstance(notices, list):
            notices = []
        notices.append({"command_id": command_id, "reason": reason})
        _replace_record(ROOT / CANCEL_NAME, notices[-64:])
    active = _read_record(ROOT / ACTIVE_NAME)
    uncertain = (isinstance(active, dict) and active.get("command_id") == command_id
                 and command.get("action") not in {"SNAPSHOT", "WAIT", "MOVE"})
    value = result if result is not None else make_result(command, ok=False, reason_code=reason,
                                                         completion_uncertain=uncertain)
    value = {**value, "transport_state": state}
    _replace_record(ROOT / RESULT_NAME, value)
    for name in (COMMAND_NAME, ACTIVE_NAME):
        path = ROOT / name
        record = _read_record(path)
        if isinstance(record, dict) and record.get("command_id") == command_id:
            path.unlink(missing_ok=True)
    return True


def _expire_locked():
    for name in (ACTIVE_NAME, COMMAND_NAME):
        raw = _command_record_locked(name)
        if not isinstance(raw, dict):
            continue
        command = validate_command(raw)
        if command["expires_at"] and command["expires_at"] <= time.time():
            _terminal_locked(command, "EXPIRED", "OPERATOR_TIMEOUT", notify=True)


def take_cancellations() -> list[dict[str, str]]:
    with _transport_lock():
        rows = _read_record(ROOT / CANCEL_NAME) or []
        (ROOT / CANCEL_NAME).unlink(missing_ok=True)
        return [row for row in rows if isinstance(row, dict)
                and isinstance(row.get("command_id"), str)
                and isinstance(row.get("reason"), str)][:64] if isinstance(rows, list) else []


def cancel(command_id: str, reason: str = "OPERATOR_CANCELLED") -> bool:
    """Cancel only the matching pending/claimed effect, never a later command."""
    with _transport_lock():
        for name in (ACTIVE_NAME, COMMAND_NAME):
            raw = _read_record(ROOT / name)
            if isinstance(raw, dict) and raw.get("command_id") == command_id:
                return _terminal_locked(validate_command(raw), "CANCELLED", reason, notify=True)
    return False


def _host(url: str) -> str:
    value = str(url or "").strip()
    if value and "://" not in value and not value.startswith("about:"):
        value = "https://" + value
    return str(urlparse(value).hostname or "").lower()


def _coord(value: Any, label: str) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WebOperatorError(label + "_INVALID")
    number = int(value)
    if number < _COORD_LO or number > _COORD_HI:
        raise WebOperatorError(label + "_RANGE")
    return number


def risk_class_for(action: str, url: str) -> str:
    host = _host(url)
    path = str(urlparse(url).path or "").lower()
    if host.endswith("one.com") or host in RED_HOSTS:
        return "RED"
    if "wp-login.php" in path or "/wp-admin" in path:
        return "RED"
    if action in YELLOW_ACTIONS:
        return "YELLOW"
    if action in GREEN_ACTIONS:
        return "GREEN"
    return "YELLOW"


def password_selector(selector: str) -> bool:
    return bool(_PASSWORD_RE.search(str(selector or "")))


def validate_command(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WebOperatorError("COMMAND_NOT_OBJECT")
    if value.get("schema") != SCHEMA_COMMAND:
        raise WebOperatorError("COMMAND_SCHEMA_INVALID")
    action = str(value.get("action") or "")
    if action not in ACTIONS:
        raise WebOperatorError("ACTION_INVALID")
    command_id = str(value.get("command_id") or "")
    if not command_id.startswith("webop-") or not _SHA_LIKE.fullmatch(command_id):
        raise WebOperatorError("COMMAND_ID_INVALID")
    url = str(value.get("url") or "")
    selector = str(value.get("selector") or "")
    text = value.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise WebOperatorError("TEXT_INVALID")
    if len(text) > 4000:
        raise WebOperatorError("TEXT_TOO_LONG")
    if len(selector) > 240:
        raise WebOperatorError("SELECTOR_TOO_LONG")
    if "javascript:" in selector.lower() or "<" in selector:
        raise WebOperatorError("SELECTOR_FORBIDDEN")
    coord_x = _coord(value.get("x"), "X")
    coord_y = _coord(value.get("y"), "Y")
    coord_dx = _coord(value.get("dx"), "DX")
    coord_dy = _coord(value.get("dy"), "DY")
    if action in {"OPEN", "TAB_NEW"} and url:
        normalized = web_surface.normalize_browse_url(url)
        if not normalized:
            raise WebOperatorError("URL_NOT_ALLOWED")
        url = normalized
    elif url and not web_surface.browse_url_allowed(url) and url != "about:blank":
        raise WebOperatorError("URL_NOT_ALLOWED")
    if action in {"CLICK", "TYPE", "HOVER", "SELECT"} and not selector.strip():
        raise WebOperatorError("SELECTOR_REQUIRED")
    if action == "MOVE" and not selector.strip() and coord_x == 0 and coord_y == 0:
        raise WebOperatorError("MOVE_TARGET_REQUIRED")
    if action == "TYPE" and password_selector(selector):
        raise WebOperatorError("PASSWORD_FIELD_FORBIDDEN")
    if action == "TYPE" and not text:
        raise WebOperatorError("TEXT_REQUIRED")
    if (
        action == "SCROLL"
        and coord_dx == 0
        and coord_dy == 0
        and not selector.strip()
    ):
        raise WebOperatorError("SCROLL_DELTA_REQUIRED")
    if action == "KEY":
        if text not in KEYS:
            raise WebOperatorError("KEY_INVALID")
    if action == "SELECT" and not text:
        raise WebOperatorError("TEXT_REQUIRED")
    risk = risk_class_for(action, url)
    expires_at = value.get("expires_at", 0)
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)) or not math.isfinite(expires_at) or expires_at < 0:
        raise WebOperatorError("COMMAND_DEADLINE_INVALID")
    if action == "TAB_NEW" and (url or selector.strip()):
        risk = "YELLOW"
    authorization = _validate_task_scoped_authorization(
        value.get("task_scoped_authorization")
    )
    authority = (
        _authority_fields({"task_scoped_authorization": authorization})
        if authorization is not None
        else _authority_fields({})
    )
    return {
        "schema": SCHEMA_COMMAND,
        "command_id": command_id,
        "action": action,
        "url": url,
        "selector": selector.strip(),
        "text": text,
        "x": coord_x,
        "y": coord_y,
        "dx": coord_dx,
        "dy": coord_dy,
        "risk_class": risk,
        **authority,
        "visible_cursor": True,
        "expires_at": float(expires_at),
    }


def make_command(
    action: str,
    *,
    url: str = "",
    selector: str = "",
    text: str = "",
    x: int = 0,
    y: int = 0,
    dx: int = 0,
    dy: int = 0,
    task_scoped_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task_scoped_authorization is None:
        task_scoped_authorization = (
            task_scoped_action_grant.runtime_authorize_effect(
                "web." + str(action or "").strip().lower(),
                host=_host(url),
            )
        )
    return validate_command(
        {
            "schema": SCHEMA_COMMAND,
            "command_id": "webop-" + uuid.uuid4().hex[:24],
            "action": action,
            "url": url,
            "selector": selector,
            "text": text,
            "x": x,
            "y": y,
            "dx": dx,
            "dy": dy,
            "task_scoped_authorization": task_scoped_authorization,
        }
    )


def make_result(
    command: dict[str, Any],
    *,
    ok: bool,
    reason_code: str,
    url: str = "",
    title: str = "",
    text: str = "",
    links: list[Any] | None = None,
    image: str = "",
    completion_uncertain: bool = False,
) -> dict[str, Any]:
    authority = _authority_fields(command)
    return {
        "schema": SCHEMA_RESULT,
        "command_id": command.get("command_id"),
        "ok": bool(ok),
        "reason_code": str(reason_code),
        "risk_class": command.get("risk_class") or "GREEN",
        "action": command.get("action"),
        "url": url[:4096],
        "title": title[:400],
        "text": text[:8000],
        "links": [{"t": str(row.get("t") or "")[:160], "h": str(row.get("h") or "")[:2000]}
                  for row in list(links or [])[:40] if isinstance(row, dict)],
        "image": image[:4096],
        **authority,
        "visible_web_tab": True,
        "visible_cursor": True,
        "completion_uncertain": bool(completion_uncertain),
    }


def take_command(*, owner: str | None = None) -> dict[str, Any] | None:
    owner = owner or _HOST_SESSION
    with _transport_lock():
        _expire_locked()
        active = _command_record_locked(ACTIVE_NAME)
        if isinstance(active, dict):
            receipt = _receipt_locked(str(active.get("command_id") or ""))
            if active.get("transport_owner") != owner or receipt not in (None, "CLAIMED"):
                _terminal_locked(validate_command(active), "INTERRUPTED", "OPERATOR_INTERRUPTED", notify=True)
            return None
        path = ROOT / COMMAND_NAME
        raw = _command_record_locked(COMMAND_NAME)
        if raw is None:
            return None
        command = validate_command(raw)
        if _receipt_locked(command["command_id"]):
            _terminal_locked(command, "INTERRUPTED", "OPERATOR_INTERRUPTED", notify=True)
            return None
        if command.get("risk_class") == "RED" and command.get("task_scoped_authorization") is None:
            _terminal_locked(command, "REJECTED", "TASK_SCOPED_AUTHORIZATION_REQUIRED")
            return None
        if not command["expires_at"]:
            command["expires_at"] = time.time() + 120
        claimed = {**command, "transport_state": "CLAIMED", "transport_owner": owner}
        _receipt_locked(command["command_id"], "CLAIMED")
        _replace_record(ROOT / ACTIVE_NAME, claimed)
        path.unlink(missing_ok=True)
        return command


def write_result(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict) or result.get("schema") != SCHEMA_RESULT:
        return False
    with _transport_lock():
        _expire_locked()
        raw = _read_record(ROOT / ACTIVE_NAME)
        if not isinstance(raw, dict) or raw.get("command_id") != result.get("command_id"):
            return False
        command = validate_command(raw)
        # Authority and action fields come from the claimed command, not a
        # page/QML result. Only bounded observations cross back from the view.
        safe = make_result(command, ok=result.get("ok") is True,
            reason_code=str(result.get("reason_code") or "FAIL")[:80],
            url=str(result.get("url") or "")[:4096], title=str(result.get("title") or "")[:400],
            text=str(result.get("text") or ""),
            links=result.get("links") if isinstance(result.get("links"), list) else [],
            image=str(result.get("image") or "")[:4096],
            completion_uncertain=result.get("completion_uncertain") is True)
        return _terminal_locked(command, "COMPLETED", safe["reason_code"], result=safe)


def submit(command: dict[str, Any], *, timeout: float = 25.0) -> dict[str, Any]:
    validated = validate_command(command)
    if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 180:
        raise WebOperatorError("OPERATOR_TIMEOUT_INVALID")
    validated["expires_at"] = time.time() + timeout
    command_path = ROOT / COMMAND_NAME
    result_path = ROOT / RESULT_NAME
    with _transport_lock():
        _expire_locked()
        if command_path.exists() or (ROOT / ACTIVE_NAME).exists():
            raise WebOperatorError("OPERATOR_BUSY")
        if _receipt_locked(validated["command_id"]):
            raise WebOperatorError("COMMAND_ALREADY_FINISHED")
        result_path.unlink(missing_ok=True)
        _replace_record(command_path, {**validated, "transport_state": "PENDING"})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result_path.is_file():
            try:
                value = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if value.get("command_id") == validated["command_id"]:
                return value
        time.sleep(0.05)
    with _transport_lock():
        _expire_locked()
    raise WebOperatorError("OPERATOR_TIMEOUT")


def open_url(url: str, *, timeout: float = 40.0) -> dict[str, Any]:
    return submit(make_command("OPEN", url=url), timeout=timeout)


def snapshot(*, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("SNAPSHOT"), timeout=timeout)


def click(selector: str, *, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("CLICK", selector=selector), timeout=timeout)


def type_text(selector: str, text: str, *, timeout: float = 40.0) -> dict[str, Any]:
    return submit(
        make_command("TYPE", selector=selector, text=text),
        timeout=timeout,
    )


def reload_page(*, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("RELOAD"), timeout=timeout)


def go_back(*, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("BACK"), timeout=timeout)


def move(
    *,
    selector: str = "",
    x: int = 0,
    y: int = 0,
    timeout: float = 25.0,
) -> dict[str, Any]:
    return submit(
        make_command("MOVE", selector=selector, x=x, y=y),
        timeout=timeout,
    )


def hover(selector: str, *, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("HOVER", selector=selector), timeout=timeout)


def scroll(
    *,
    dx: int = 0,
    dy: int = 0,
    selector: str = "",
    timeout: float = 25.0,
) -> dict[str, Any]:
    return submit(
        make_command("SCROLL", dx=dx, dy=dy, selector=selector),
        timeout=timeout,
    )


def wait_load(*, timeout: float = 40.0) -> dict[str, Any]:
    return submit(make_command("WAIT"), timeout=timeout)


def stage(*, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("STAGE"), timeout=timeout)


def press_key(
    key: str,
    *,
    selector: str = "",
    timeout: float = 25.0,
) -> dict[str, Any]:
    return submit(
        make_command("KEY", selector=selector, text=key),
        timeout=timeout,
    )


def tab_new(
    *,
    url: str = "",
    selector: str = "",
    timeout: float = 40.0,
) -> dict[str, Any]:
    return submit(
        make_command("TAB_NEW", url=url, selector=selector),
        timeout=timeout,
    )


def tab_close(*, timeout: float = 15.0) -> dict[str, Any]:
    return submit(make_command("TAB_CLOSE"), timeout=timeout)


def tab_next(*, timeout: float = 15.0) -> dict[str, Any]:
    return submit(make_command("TAB_NEXT"), timeout=timeout)


def tab_prev(*, timeout: float = 15.0) -> dict[str, Any]:
    return submit(make_command("TAB_PREV"), timeout=timeout)


def go_forward(*, timeout: float = 25.0) -> dict[str, Any]:
    return submit(make_command("FORWARD"), timeout=timeout)


def select_option(
    selector: str,
    text: str,
    *,
    timeout: float = 25.0,
) -> dict[str, Any]:
    return submit(
        make_command("SELECT", selector=selector, text=text),
        timeout=timeout,
    )


def _print_result(value: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return 0 if value.get("ok") else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gg-web",
        description=(
            "Drive the GG AI Desktop WEB tab. Actions are visible "
            "(agent cursor). Hidden HTTP is not this path."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.0,
        help="Seconds to wait for the visible pane (default per action).",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    p_open = sub.add_parser("open", help="OPEN url in the WEB tab")
    p_open.add_argument("url")
    sub.add_parser("snapshot", help="SNAPSHOT the visible page")
    p_click = sub.add_parser("click", help="CLICK selector")
    p_click.add_argument("selector")
    p_type = sub.add_parser("type", help="TYPE into selector")
    p_type.add_argument("selector")
    p_type.add_argument("text")
    sub.add_parser("reload", help="RELOAD")
    sub.add_parser("back", help="BACK")
    p_move = sub.add_parser("move", help="MOVE the agent cursor")
    p_move.add_argument("--selector", default="")
    p_move.add_argument("--x", type=int, default=0)
    p_move.add_argument("--y", type=int, default=0)
    p_hover = sub.add_parser("hover", help="HOVER selector")
    p_hover.add_argument("selector")
    p_scroll = sub.add_parser("scroll", help="SCROLL the page")
    p_scroll.add_argument("--dx", type=int, default=0)
    p_scroll.add_argument("--dy", type=int, default=0)
    p_scroll.add_argument("--selector", default="")
    sub.add_parser("wait", help="WAIT for load")
    sub.add_parser("stage", help="Load the local visible-WEB rehearsal page")
    p_key = sub.add_parser("key", help="KEY Enter/Tab/Escape/…")
    p_key.add_argument("key")
    p_key.add_argument("--selector", default="")
    p_tab_new = sub.add_parser("tab-new", help="Open a new WEB tab")
    p_tab_new.add_argument("url", nargs="?", default="")
    p_tab_new.add_argument("--selector", default="")
    sub.add_parser("tab-close", help="Close the current WEB tab")
    sub.add_parser("tab-next", help="Focus the next WEB tab")
    sub.add_parser("tab-prev", help="Focus the previous WEB tab")
    sub.add_parser("forward", help="FORWARD in history")
    p_sel = sub.add_parser("select", help="SELECT a dropdown option")
    p_sel.add_argument("selector")
    p_sel.add_argument("text")
    args = parser.parse_args(argv)
    timeout = args.timeout
    action = str(args.action)
    try:
        if action == "open":
            result = open_url(args.url, timeout=timeout or 40.0)
        elif action == "snapshot":
            result = snapshot(timeout=timeout or 25.0)
        elif action == "click":
            result = click(args.selector, timeout=timeout or 25.0)
        elif action == "type":
            result = type_text(args.selector, args.text, timeout=timeout or 40.0)
        elif action == "reload":
            result = reload_page(timeout=timeout or 25.0)
        elif action == "back":
            result = go_back(timeout=timeout or 25.0)
        elif action == "move":
            result = move(
                selector=args.selector,
                x=args.x,
                y=args.y,
                timeout=timeout or 25.0,
            )
        elif action == "hover":
            result = hover(args.selector, timeout=timeout or 25.0)
        elif action == "scroll":
            result = scroll(
                dx=args.dx,
                dy=args.dy,
                selector=args.selector,
                timeout=timeout or 25.0,
            )
        elif action == "wait":
            result = wait_load(timeout=timeout or 40.0)
        elif action == "stage":
            result = stage(timeout=timeout or 25.0)
        elif action == "key":
            result = press_key(
                args.key,
                selector=args.selector,
                timeout=timeout or 25.0,
            )
        elif action == "tab-new":
            result = tab_new(
                url=args.url,
                selector=args.selector,
                timeout=timeout or 40.0,
            )
        elif action == "tab-close":
            result = tab_close(timeout=timeout or 15.0)
        elif action == "tab-next":
            result = tab_next(timeout=timeout or 15.0)
        elif action == "tab-prev":
            result = tab_prev(timeout=timeout or 15.0)
        elif action == "forward":
            result = go_forward(timeout=timeout or 25.0)
        elif action == "select":
            result = select_option(
                args.selector,
                args.text,
                timeout=timeout or 25.0,
            )
        else:
            raise WebOperatorError("ACTION_INVALID")
    except WebOperatorError as exc:
        sys.stderr.write("WEB_OPERATOR " + str(exc) + "\n")
        return 1
    return _print_result(result)


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[1]
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    raise SystemExit(main())
