from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from backend import task_scoped_action_grant


SCHEMA_COMMAND = "gg.desktop-operator-command.v1"
SCHEMA_RESULT = "gg.desktop-operator-result.v1"
GENERAL_ACTION_AUTHORITY = "NONE"
ROOT = Path(str(STATE_ROOT / 'desktop-operator'))
COMMAND_NAME = "command.json"
ACTIVE_NAME = "command.active.json"
RESULT_NAME = "result.json"
VIEW_NAME = "view.png"

ACTIONS = ("MOVE", "CLICK", "HOVER", "TYPE", "KEY", "SNAPSHOT", "FIND")
GREEN_ACTIONS = frozenset({"MOVE", "HOVER", "SNAPSHOT", "FIND"})
YELLOW_ACTIONS = frozenset({"CLICK", "TYPE", "KEY"})
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
        "Ctrl+V",
        "Shift+Insert",
    }
)
BUTTONS = frozenset({"left", "middle", "right"})


class DesktopOperatorError(ValueError):
    pass


def _validate_task_scoped_authorization(
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return task_scoped_action_grant.validate_authorization(value)
    except task_scoped_action_grant.TaskScopedActionGrantError as exc:
        raise DesktopOperatorError(
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
        raise DesktopOperatorError("FILE_EXISTS:" + path.name)
    fd = secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def risk_class_for(action: str) -> str:
    if action in GREEN_ACTIONS:
        return "GREEN"
    return "YELLOW"


def validate_command(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DesktopOperatorError("COMMAND_NOT_OBJECT")
    if value.get("schema") != SCHEMA_COMMAND:
        raise DesktopOperatorError("COMMAND_SCHEMA_INVALID")
    action = str(value.get("action") or "")
    if action not in ACTIONS:
        raise DesktopOperatorError("ACTION_INVALID")
    command_id = str(value.get("command_id") or "")
    if not command_id.startswith("deskop-"):
        raise DesktopOperatorError("COMMAND_ID_INVALID")
    name = str(value.get("name") or "")
    text = value.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise DesktopOperatorError("TEXT_INVALID")
    visual = bool(value.get("visual", False))
    if len(text) > 4000:
        raise DesktopOperatorError("TEXT_TOO_LONG")
    if len(name) > 120:
        raise DesktopOperatorError("NAME_TOO_LONG")
    try:
        coord_x = int(value.get("x") or 0)
        coord_y = int(value.get("y") or 0)
    except (TypeError, ValueError) as exc:
        raise DesktopOperatorError("COORD_INVALID") from exc
    button = str(value.get("button") or "left")
    if button not in BUTTONS:
        raise DesktopOperatorError("BUTTON_INVALID")
    if (
        action in {"CLICK", "HOVER", "MOVE"}
        and not name
        and not text
        and coord_x == 0
        and coord_y == 0
    ):
        raise DesktopOperatorError("TARGET_REQUIRED")
    if action == "TYPE" and not text:
        raise DesktopOperatorError("TEXT_REQUIRED")
    if action == "KEY" and text not in KEYS:
        raise DesktopOperatorError("KEY_INVALID")
    if action == "FIND" and not name and not text:
        raise DesktopOperatorError("FIND_REQUIRED")
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
        "name": name,
        "text": text,
        "x": coord_x,
        "y": coord_y,
        "button": button,
        "risk_class": risk_class_for(action),
        **authority,
        "visible_cursor": True,
        "visual": visual,
    }


def make_command(
    action: str,
    *,
    name: str = "",
    text: str = "",
    x: int = 0,
    y: int = 0,
    button: str = "left",
    visual: bool = False,
    task_scoped_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task_scoped_authorization is None:
        task_scoped_authorization = (
            task_scoped_action_grant.runtime_authorize_effect(
                "desktop." + str(action or "").strip().lower()
            )
        )
    return validate_command(
        {
            "schema": SCHEMA_COMMAND,
            "command_id": "deskop-" + uuid.uuid4().hex[:24],
            "action": action,
            "name": name,
            "text": text,
            "x": x,
            "y": y,
            "button": button,
            "visual": visual,
            "task_scoped_authorization": task_scoped_authorization,
        }
    )


def make_result(
    command: dict[str, Any],
    *,
    ok: bool,
    reason_code: str,
    text: str = "",
    x: int = 0,
    y: int = 0,
    names: list[Any] | None = None,
    image: str = "",
    observation_seq: int = 0,
    stable_frames: int = 0,
) -> dict[str, Any]:
    from backend import sensitive_ui_guard
    blocked=command.get('action') in {'SNAPSHOT','FIND'} and sensitive_ui_guard.active()
    if blocked:
        ok=False;reason_code='SENSITIVE_UI_ACTIVE';text='';names=[];image=''
    view = ROOT / VIEW_NAME
    if not blocked and not image and view.is_file():
        image = str(view)
    authority = _authority_fields(command)
    return {
        "schema": SCHEMA_RESULT,
        "command_id": command.get("command_id"),
        "ok": bool(ok),
        "reason_code": str(reason_code),
        "risk_class": command.get("risk_class") or "GREEN",
        "action": command.get("action"),
        "name": command.get("name") or "",
        "text": text[:8000],
        "x": int(x),
        "y": int(y),
        "names": list(names or [])[:80],
        "image": image,
        **authority,
        "visible_cursor": True,
        "observation_seq": max(0, int(observation_seq)),
        "stable_frames": max(0, int(stable_frames)),
    }


def take_command() -> dict[str, Any] | None:
    ensure_root()
    path = ROOT / COMMAND_NAME
    active = ROOT / ACTIVE_NAME
    if active.is_file():
        try:
            return validate_command(json.loads(active.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, DesktopOperatorError):
            try:
                active.unlink()
            except OSError:
                pass
            return None
    if not path.is_file() or path.is_symlink():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        command = validate_command(json.loads(raw))
    except (OSError, json.JSONDecodeError, DesktopOperatorError):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    try:
        os.replace(path, active)
    except OSError:
        return None
    return command


def write_result(result: dict[str, Any]) -> None:
    ensure_root()
    payload = _canonical(result)
    target = ROOT / RESULT_NAME
    if target.exists() or target.is_symlink():
        target.unlink()
    _write_exclusive(target, payload)
    active = ROOT / ACTIVE_NAME
    if active.exists():
        try:
            active.unlink()
        except OSError:
            pass


def submit(command: dict[str, Any], *, timeout: float = 25.0) -> dict[str, Any]:
    validated = validate_command(command)
    from backend import sensitive_ui_guard
    try:guard_token=sensitive_ui_guard.capture_token() if validated['action'] in {'SNAPSHOT','FIND'} else None
    except RuntimeError:raise DesktopOperatorError('SENSITIVE_UI_ACTIVE') from None
    ensure_root()
    command_path = ROOT / COMMAND_NAME
    result_path = ROOT / RESULT_NAME
    if command_path.exists() or (ROOT / ACTIVE_NAME).exists():
        raise DesktopOperatorError("OPERATOR_BUSY")
    if result_path.exists():
        result_path.unlink()
    _write_exclusive(command_path, _canonical(validated))
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        if result_path.is_file():
            try:
                value = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if value.get("command_id") == validated["command_id"]:
                if guard_token is not None:
                    try:sensitive_ui_guard.require_capture_allowed(guard_token)
                    except RuntimeError:raise DesktopOperatorError('SENSITIVE_UI_ACTIVE') from None
                return value
        time.sleep(0.05)
    raise DesktopOperatorError("OPERATOR_TIMEOUT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gg-desk",
        description=(
            "Drive GG AI Desktop with a visible pointer and real "
            "mouse/key events. Not web-only."
        ),
    )
    parser.add_argument("--timeout", type=float, default=0.0)
    sub = parser.add_subparsers(dest="action", required=True)
    p_move = sub.add_parser("move")
    p_move.add_argument("--name", default="")
    p_move.add_argument("--x", type=int, default=0)
    p_move.add_argument("--y", type=int, default=0)
    p_click = sub.add_parser("click")
    p_click.add_argument("--name", default="")
    p_click.add_argument("--x", type=int, default=0)
    p_click.add_argument("--y", type=int, default=0)
    p_click.add_argument("--button", default="left", choices=sorted(BUTTONS))
    p_click.add_argument("--label", default="")
    p_hover = sub.add_parser("hover")
    p_hover.add_argument("--name", default="")
    p_hover.add_argument("--x", type=int, default=0)
    p_hover.add_argument("--y", type=int, default=0)
    p_hover.add_argument("--label", default="")
    p_move.add_argument("--label", default="")
    p_type = sub.add_parser("type")
    p_type.add_argument("text")
    p_type.add_argument("--name", default="")
    p_key = sub.add_parser("key")
    p_key.add_argument("key")
    sub.add_parser("snapshot")
    sub.choices["snapshot"].add_argument(
        "--visual",
        action="store_true",
        help="capture a screenshot; default is semantic observation only",
    )
    p_find = sub.add_parser("find")
    p_find.add_argument("query")
    args = parser.parse_args(argv)
    timeout = args.timeout or 25.0
    action = str(args.action)
    try:
        if action == "move":
            result = submit(
                make_command(
                    "MOVE",
                    name=args.name,
                    text=args.label,
                    x=args.x,
                    y=args.y,
                ),
                timeout=timeout,
            )
        elif action == "click":
            result = submit(
                make_command(
                    "CLICK",
                    name=args.name,
                    text=args.label,
                    x=args.x,
                    y=args.y,
                    button=args.button,
                ),
                timeout=timeout,
            )
        elif action == "hover":
            result = submit(
                make_command(
                    "HOVER",
                    name=args.name,
                    text=args.label,
                    x=args.x,
                    y=args.y,
                ),
                timeout=timeout,
            )
        elif action == "type":
            result = submit(
                make_command("TYPE", text=args.text, name=args.name),
                timeout=timeout,
            )
        elif action == "key":
            result = submit(make_command("KEY", text=args.key), timeout=timeout)
        elif action == "snapshot":
            result = submit(
                make_command("SNAPSHOT", visual=bool(args.visual)),
                timeout=timeout,
            )
        elif action == "find":
            result = submit(make_command("FIND", text=args.query), timeout=timeout)
        else:
            raise DesktopOperatorError("ACTION_INVALID")
    except DesktopOperatorError as exc:
        sys.stderr.write("DESK_OPERATOR " + str(exc) + "\n")
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[1]
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    raise SystemExit(main())
