from __future__ import annotations
from backend.platform_support import runtime_root
from backend.platform_files import secure_open, NOFOLLOW

import argparse
import json
import os
import re
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
) -> dict[str, Any]:
    view = ROOT / VIEW_NAME
    if not image and view.is_file():
        image = str(view)
    authority = _authority_fields(command)
    return {
        "schema": SCHEMA_RESULT,
        "command_id": command.get("command_id"),
        "ok": bool(ok),
        "reason_code": str(reason_code),
        "risk_class": command.get("risk_class") or "GREEN",
        "action": command.get("action"),
        "url": url,
        "title": title,
        "text": text[:8000],
        "links": list(links or [])[:40],
        "image": image,
        **authority,
        "visible_web_tab": True,
        "visible_cursor": True,
    }


def take_command() -> dict[str, Any] | None:
    ensure_root()
    path = ROOT / COMMAND_NAME
    active = ROOT / ACTIVE_NAME
    if active.is_file():
        try:
            return validate_command(json.loads(active.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, WebOperatorError):
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
    except (OSError, json.JSONDecodeError, WebOperatorError):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    if (
        command.get("risk_class") == "RED"
        and command.get("task_scoped_authorization") is None
    ):
        try:
            path.unlink()
        except OSError:
            pass
        write_result(
            make_result(
                command,
                ok=False,
                reason_code="TASK_SCOPED_AUTHORIZATION_REQUIRED",
            )
        )
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
    ensure_root()
    command_path = ROOT / COMMAND_NAME
    result_path = ROOT / RESULT_NAME
    if command_path.exists() or (ROOT / ACTIVE_NAME).exists():
        raise WebOperatorError("OPERATOR_BUSY")
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
                if (
                    value.get("reason_code") == "OPERATOR_BUSY"
                    and time.monotonic() + 0.5 < deadline
                ):
                    time.sleep(0.4)
                    if command_path.exists() or (ROOT / ACTIVE_NAME).exists():
                        continue
                    try:
                        result_path.unlink()
                    except OSError:
                        pass
                    try:
                        _write_exclusive(command_path, _canonical(validated))
                    except WebOperatorError:
                        continue
                    continue
                return value
        time.sleep(0.05)
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
