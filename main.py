#!/usr/bin/env python3
"""GG AI Desktop Workbench with local-only Chat Bridge."""

from __future__ import annotations

from backend.platform_files import (
    NOFOLLOW,
    mode_matches,
    owned_by_current_user,
    secure_open,
    set_private_mode,
)
from backend.platform_support import (
    desktop_relative_path,
    executable_path,
    host_environment,
    platform_path,
    private_runtime_root,
    workspace_root,
)


import copy
import hashlib
import json
import os
import sys
from collections.abc import Callable
# EXT hosts Blender as a native child of this window.  That only works when
# the desktop itself is X11/XWayland, same as a QML pane — not a Tool overlay.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
if sys.platform == "win32":
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-extensions --disable-background-networking --disable-sync "
    "--ignore-gpu-blocklist --enable-webgl --enable-webgl2 "
    "--enable-unsafe-swiftshader --renderer-process-limit=4",
)
import stat
import subprocess
import shutil
import time
import uuid
from pathlib import Path

_HEADLESS_ENTRY_FLAGS = {
    "--selfdev-controller",
    "--selfdev-controller-synthetic",
    "--selfdev-selftest",
}

if (
    __name__ == "__main__"
    and (len(sys.argv) < 2 or sys.argv[1] not in _HEADLESS_ENTRY_FLAGS)
):
    # Start the QML window before importing the desktop's large service graph.
    # startup.py imports this module after the first in-app loading frame lands.
    from startup import launch

    raise SystemExit(launch(sys.argv))

try:
    from PySide6.QtCore import (
        QObject,
        QProcess,
        QTimer,
        QUrl,
        Qt,
        Signal,
        Slot,
    )
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
except Exception:
    if __name__ == "__main__":
        print(
            "FAIL: PySide6/Qt missing. Fedora: dnf install python3-pyside6 qt6-qtwebengine",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise

from backend import shell_load

from backend import local_ai_contract as contract
from backend import autonomy_contract as autonomy_contract
from backend import control_plane_contract as control_contract
from backend import safe_tool_contract as tool_contract
from backend import write_contract as write_contract
from backend import resident_information_state as resident_state
from backend import action_execution_eligibility
from backend import action_execution_safe_tool_adapter
from backend import action_intent_contract
from backend import action_task_continuity
from backend import live_mandate_store
from backend import participant_task_receiver
from backend import idekompass_decision_ingress
from backend import visual_commands
from backend import orchestrator_mandate_evaluation_adapter
from backend import task_scoped_action_grant
from backend import machine_graph
from backend.live_aid.bridge import LiveAidService
from backend.live_aid import qml_preflight_runner
from backend.live_aid import repair_model_runner
from backend.live_aid import post_draft_qml_process_runner
from backend.chat_context_compiler import (
    PRIMARY_PROMPT_MAX_CHARS,
    compile_chat_prompt,
)
from backend.natural_safe_tool import parse_natural_safe_tool_command
from backend.resident_chat_qt import ResidentChatTransport
from backend.grok_worker_contract import (
    ENGINE_GPT_TUI,
    ENGINE_GROK_TUI,
    ENGINE_GROK_WORKER,
    ENGINE_LOCAL_QWEN,
    GROK_WORKSPACE_ALLOWLIST as WORKSPACE_CONTEXTS,
    GrokWorkerContractError,
    normalize_engine_target,
    resolve_workspace_surface,
)


PROJECT = Path(__file__).resolve().parent
REPO_ROOT = workspace_root()

ORCHESTRATOR_PARTICIPANTS = (
    "GG-AI-installator",
    "GG-Agentarkitekt-agentskapare",
    "GG-Content-Studio",
    "GG-Marknadsföring",
    "GG-Metaarkitekt-gptskapare",
    "GG-Webmaster",
    "GG-idekompassen",
)
CONFIG_PATH = PROJECT / "config" / "workbench-v1.2.json"
QML_PATH = PROJECT / "qml" / "Main.qml"
CHAT_RUNNER_PATH = PROJECT / "backend" / "local_ai_chat_runner.py"
SAFE_TOOL_RUNNER_PATH = PROJECT / "backend" / "safe_tool_runner.py"
WRITE_RUNNER_PATH = PROJECT / "backend" / "write_runner.py"
AUTONOMY_CONTROLLER_PATH = PROJECT / "backend" / "autonomy_controller.py"
CONTROL_APPLY_RUNNER_PATH = PROJECT / "backend" / "control_plane_runner.py"
PREFLIGHT_RUNNER_PATH = PROJECT / "backend" / "live_aid" / "qml_preflight_runner.py"
REPAIR_MODEL_RUNNER_PATH = PROJECT / "backend" / "live_aid" / "repair_model_runner.py"

WORKSPACE_CONTEXT_MAX_BYTES = 16384
GPT_TUI_PROMPT_MAX_CHARS = 16384
LOCAL_OMNI_CONTEXT_MAX_CHARS = 2200


def prompt_for_resident_engine(
    user_text: str,
    effective_prompt: str,
    engine_target: str,
) -> str:
    """Choose the prompt representation that is safe for the target UI."""
    if engine_target == ENGINE_GPT_TUI:
        # GPTUI has its shared profile layer in Codex developer instructions;
        # sending the compiled Workbench prompt here would render all of it
        # as an ordinary, visible user message.
        return user_text
    return effective_prompt


def resolve_workspace_context(workspace_object_id: str) -> dict[str, object]:
    # Selected Workspace object has no real local context source.
    try:
        return resolve_workspace_surface(workspace_object_id)
    except GrokWorkerContractError as exc:
        raise RuntimeError(str(exc)) from exc


def build_effective_prompt(
    text: str,
    context_reference: str,
    workspace_object_id: str,
    *,
    engine_target: str = ENGINE_LOCAL_QWEN,
) -> tuple[str, dict[str, object]]:
    if context_reference != "@current":
        raise RuntimeError(
            "Real Workspace context currently requires @current."
        )
    context = resolve_workspace_context(workspace_object_id)
    try:
        from backend.omni_gpt_profiles import build_context as build_omni_context

        full_context = engine_target == ENGINE_GPT_TUI
        omni_context = build_omni_context(
            text,
            max_chars=(14_000 if full_context else LOCAL_OMNI_CONTEXT_MAX_CHARS),
            include_registry=full_context,
        )
    except Exception:
        # The profile package is guidance, not a reason to take ordinary chat
        # offline. AGENTS.md and the executable contracts remain in force.
        omni_context = (
            "[GG OMNIGPT PROFILE LAYER]\n"
            "Profile source unavailable; follow AGENTS.md and Idékompassen.\n"
            "[/GG OMNIGPT PROFILE LAYER]"
        )
    prompt_limit = (
        GPT_TUI_PROMPT_MAX_CHARS
        if engine_target == ENGINE_GPT_TUI
        else PRIMARY_PROMPT_MAX_CHARS
    )
    return (
        compile_chat_prompt(
            text,
            context_reference,
            context,
            omni_context=omni_context,
            max_chars=prompt_limit,
        ),
        context,
    )


def current_clean_head() -> str:
    env = host_environment({
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
    })
    status = subprocess.run(
        [
            executable_path("git"),
            "-C",
            str(workspace_root()),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=10,
        check=False,
    )
    if status.returncode != 0:
        raise RuntimeError("Git status failed during autonomy state lock.")
    if status.stdout:
        raise RuntimeError("Repository must be clean for an autonomy task.")

    head = subprocess.run(
        [
            executable_path("git"),
            "-C",
            str(workspace_root()),
            "rev-parse",
            "HEAD",
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=10,
        check=False,
    )
    if head.returncode != 0:
        raise RuntimeError("Git HEAD read failed during autonomy state lock.")
    value = head.stdout.decode("ascii", errors="strict").strip()
    if len(value) not in (40, 64) or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError("Git HEAD format invalid.")
    return value

SELFDEV_PROFILE_ID = "SELFDEV_MAIN_PY_V1"
SELFDEV_TARGET_REPO_RELATIVE = desktop_relative_path("main.py")
SELFDEV_CONTROLLER_MODE = "--selfdev-controller"
SELFDEV_SYNTHETIC_MODE = "--selfdev-controller-synthetic"
SELFDEV_SELFTEST_MODE = "--selfdev-selftest"

SELFDEV_FOUNDATION_IMAGE = "localhost/gg-code-gate:1.0.0"
SELFDEV_FOUNDATION_IMAGE_ID = (
    "97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174"
)

SELFDEV_MAX_TARGET_BYTES = 327680
SELFDEV_MAX_MODEL_CALLS = 8
SELFDEV_MAX_PATCHES = 8
SELFDEV_MAX_CONTEXT_CHARS = 28000
SELFDEV_MAX_PROMPT_CHARS = 32000

class SelfdevBridgeError(RuntimeError):
    pass

def _selfdev_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()

def _selfdev_canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

def _selfdev_runtime() -> Path:
    runtime = private_runtime_root()

    if not runtime.is_dir():
        raise SelfdevBridgeError("RUNTIME_INVALID")

    return runtime

def _selfdev_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _selfdev_git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        [
            executable_path("git"),
            "-C",
            str(repo),
            *args,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=host_environment({
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "GIT_OPTIONAL_LOCKS": "0",
        }),
    )

    if result.returncode != 0:
        raise SelfdevBridgeError(
            "GIT_READ_FAILED:"
            + ":".join(args)
            + ":"
            + result.stderr.decode(
                "utf-8",
                errors="replace",
            )[-2000:]
        )

    return result.stdout

def _selfdev_state_lock(repo: Path, expected_head: str) -> None:
    actual = _selfdev_git(
        repo,
        "rev-parse",
        "HEAD",
    ).decode("ascii").strip()

    if actual != expected_head:
        raise SelfdevBridgeError("BASE_HEAD_DRIFT")

    dirty = _selfdev_git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )

    if dirty:
        raise SelfdevBridgeError("REPOSITORY_NOT_CLEAN")

def _selfdev_host_target(repo: Path) -> Path:
    repo = repo.resolve(strict=True)

    target = (
        repo / SELFDEV_TARGET_REPO_RELATIVE
    ).resolve(strict=True)

    expected = repo / SELFDEV_TARGET_REPO_RELATIVE

    if target != expected:
        raise SelfdevBridgeError("TARGET_SCOPE_INVALID")

    if target.is_symlink() or not target.is_file():
        raise SelfdevBridgeError("TARGET_IDENTITY_INVALID")

    data = target.read_bytes()

    if not (1 <= len(data) <= SELFDEV_MAX_TARGET_BYTES):
        raise SelfdevBridgeError("TARGET_SIZE_INVALID")

    return target

def _selfdev_validate_request(value: object) -> dict[str, object]:
    import re

    if type(value) is not dict:
        raise SelfdevBridgeError("REQUEST_NOT_OBJECT")

    expected = {
        "schema",
        "task_id",
        "goal",
        "base_head",
        "target_relative_path",
        "target_sha256",
    }

    if set(value) != expected:
        raise SelfdevBridgeError("REQUEST_FIELDS_INVALID")

    if value["schema"] != "gg.workbench.selfdev-request.v1":
        raise SelfdevBridgeError("REQUEST_SCHEMA_INVALID")

    if (
        type(value["task_id"]) is not str
        or re.fullmatch(
            r"task-[0-9a-f]{32}",
            value["task_id"],
        )
        is None
    ):
        raise SelfdevBridgeError("TASK_ID_INVALID")

    if (
        type(value["goal"]) is not str
        or not value["goal"].strip()
        or len(value["goal"]) > 12000
        or "\x00" in value["goal"]
    ):
        raise SelfdevBridgeError("GOAL_INVALID")

    if (
        type(value["base_head"]) is not str
        or re.fullmatch(r"[0-9a-f]{40}", value["base_head"]) is None
    ):
        raise SelfdevBridgeError("BASE_HEAD_INVALID")

    if (
        type(value["target_sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["target_sha256"]) is None
    ):
        raise SelfdevBridgeError("TARGET_SHA_INVALID")

    if value["target_relative_path"] != SELFDEV_TARGET_REPO_RELATIVE:
        raise SelfdevBridgeError("TARGET_PATH_INVALID")

    return dict(value)

def _selfdev_validate_proposal(value: object) -> dict[str, str]:
    if type(value) is not dict:
        raise SelfdevBridgeError("PROPOSAL_NOT_OBJECT")

    expected = {
        "action",
        "summary",
        "old_text",
        "new_text",
    }

    if set(value) != expected:
        raise SelfdevBridgeError("PROPOSAL_FIELDS_INVALID")

    for key in expected:
        if type(value[key]) is not str:
            raise SelfdevBridgeError(
                "PROPOSAL_FIELD_TYPE_INVALID:" + key
            )

    if value["action"] not in ("PATCH", "DONE"):
        raise SelfdevBridgeError("PROPOSAL_ACTION_INVALID")

    if len(value["summary"]) > 4096:
        raise SelfdevBridgeError("PROPOSAL_SUMMARY_TOO_LARGE")

    if value["action"] == "PATCH":
        if not value["old_text"]:
            raise SelfdevBridgeError("PROPOSAL_OLD_EMPTY")

        if len(value["new_text"].encode("utf-8")) > SELFDEV_MAX_TARGET_BYTES:
            raise SelfdevBridgeError("PROPOSAL_NEW_TOO_LARGE")
    else:
        if value["old_text"] or value["new_text"]:
            raise SelfdevBridgeError("DONE_MUST_NOT_PATCH")

    return dict(value)

def parse_selfdev_command(text: str) -> dict[str, str] | None:
    stripped = text.strip()

    if not stripped.startswith("/selfdev"):
        return None

    command, separator, remainder = stripped.partition(" ")

    if command != "/selfdev":
        return None

    if not separator or not remainder.strip():
        raise ValueError("Usage: /selfdev GOAL")

    return {
        "action": "START",
        "goal": remainder.strip(),
    }

def _selfdev_event(
    sequence: int,
    phase: str,
    state: str,
    text: str,
) -> None:
    payload = {
        "schema": "gg.workbench.selfdev-event.v1",
        "step_seq": sequence,
        "phase": phase,
        "state": state,
        "text": text,
    }

    print(
        "GG_SELFDEV_EVENT="
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )

def _selfdev_extract_tree(
    repo: Path,
    base_head: str,
    destination: Path,
) -> None:
    import io
    import tarfile

    archive = _selfdev_git(
        repo,
        "archive",
        "--format=tar",
        base_head,
    )

    if destination.exists():
        raise SelfdevBridgeError("CANDIDATE_TREE_ALREADY_EXISTS")

    destination.mkdir(mode=0o700)

    with tarfile.open(
        fileobj=io.BytesIO(archive),
        mode="r:",
    ) as handle:
        members = handle.getmembers()

        for member in members:
            name = Path(member.name)

            if (
                name.is_absolute()
                or ".." in name.parts
                or member.issym()
                or member.islnk()
            ):
                raise SelfdevBridgeError(
                    "ARCHIVE_MEMBER_INVALID:" + member.name
                )

        handle.extractall(
            path=destination,
            members=members,
            filter="data",
        )

def _selfdev_compile(path: Path) -> None:
    compile(
        path.read_text(encoding="utf-8"),
        str(path),
        "exec",
        dont_inherit=True,
    )

def _selfdev_diff(before: bytes, after: bytes) -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            before.decode("utf-8").splitlines(keepends=True),
            after.decode("utf-8").splitlines(keepends=True),
            fromfile="a/main.py",
            tofile="b/main.py",
            n=3,
        )
    )

def _selfdev_apply_patch(
    candidate: Path,
    proposal: dict[str, str],
) -> None:
    current = candidate.read_text(encoding="utf-8")

    old = proposal["old_text"]
    new = proposal["new_text"]

    count = current.count(old)

    if count != 1:
        raise SelfdevBridgeError(
            "OLD_TEXT_OCCURRENCE_COUNT:" + str(count)
        )

    updated = current.replace(old, new, 1).encode("utf-8")

    if not (1 <= len(updated) <= SELFDEV_MAX_TARGET_BYTES):
        raise SelfdevBridgeError("CANDIDATE_SIZE_INVALID")

    temporary = candidate.with_name(".main.py.selfdev.tmp")

    if temporary.exists():
        temporary.unlink()

    temporary.write_bytes(updated)
    set_private_mode(temporary, 0o600)

    os.replace(temporary, candidate)

def _selfdev_foundation_gate(
    candidate: Path,
    task_root: Path,
) -> str:
    import shutil

    image = 'localhost/gg-code-gate:1.0.0'
    expected_image_id = '97c0e93637396aaba41236514c2db34944969646cf5317ccc6de962de6b96174'

    inspect = subprocess.run(
        [
            "/usr/bin/podman",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            image,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=host_environment({
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
        }),
    )

    if inspect.returncode != 0:
        raise SelfdevBridgeError(
            "FOUNDATION_IMAGE_INSPECT_FAILED:"
            + inspect.stderr.decode(
                "utf-8",
                errors="replace",
            )[-2000:]
        )

    actual_image_id = (
        inspect.stdout.decode(
            "ascii",
            errors="strict",
        )
        .strip()
        .removeprefix("sha256:")
    )

    if actual_image_id != expected_image_id:
        raise SelfdevBridgeError(
            "FOUNDATION_IMAGE_ID_DRIFT"
        )

    gate_root = (
        task_root
        / "foundation-python-gate"
    )

    if gate_root.exists():
        shutil.rmtree(gate_root)

    input_dir = gate_root / "input"
    output_dir = gate_root / "output"
    work_dir = gate_root / "work"

    gate_root.mkdir(mode=0o700)

    for directory in (
        input_dir,
        output_dir,
        work_dir,
    ):
        directory.mkdir(mode=0o700)

    source_path = input_dir / "source"

    source_bytes = candidate.read_bytes()
    candidate_sha = _selfdev_sha256(
        source_bytes
    )

    source_path.write_bytes(
        source_bytes
    )

    if (
        _selfdev_sha256(
            source_path.read_bytes()
        )
        != candidate_sha
    ):
        raise SelfdevBridgeError(
            "FOUNDATION_INPUT_COPY_SHA_MISMATCH"
        )

    def run(
        argv: list[str],
        *,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            argv,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=host_environment({
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
            }),
        )

    ownership = run(
        [
            "/usr/bin/podman",
            "unshare",
            "chown",
            "-R",
            "1000:1000",
            str(input_dir),
            str(output_dir),
            str(work_dir),
        ],
    )

    if ownership.returncode != 0:
        raise SelfdevBridgeError(
            "FOUNDATION_OWNERSHIP_PREP_FAILED:"
            + ownership.stderr.decode(
                "utf-8",
                errors="replace",
            )[-3000:]
        )

    container_name = (
        "gg-selfdev-gate-"
        + uuid.uuid4().hex
    )

    created = False

    try:
        create = run(
            [
                "/usr/bin/podman",
                "create",
                "--name",
                container_name,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "all",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "1000:1000",
                "--pids-limit",
                "128",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--mount",
                (
                    "type=bind,src="
                    + str(input_dir)
                    + ",target=/input,ro=true,relabel=private"
                ),
                "--mount",
                (
                    "type=bind,src="
                    + str(output_dir)
                    + ",target=/output,rw=true,relabel=private"
                ),
                "--mount",
                (
                    "type=bind,src="
                    + str(work_dir)
                    + ",target=/work,rw=true,relabel=private"
                ),
                image,
                "--target",
                "/input/source",
                "--name",
                "selfdev-main-py",
                "--language",
                "python",
                "--output",
                "/output/report.json",
            ],
            timeout=60,
        )

        if create.returncode != 0:
            raise SelfdevBridgeError(
                "FOUNDATION_CONTAINER_CREATE_FAILED:"
                + create.stderr.decode(
                    "utf-8",
                    errors="replace",
                )[-5000:]
            )

        created = True

        start = run(
            [
                "/usr/bin/podman",
                "start",
                container_name,
            ],
            timeout=30,
        )

        if start.returncode != 0:
            raise SelfdevBridgeError(
                "FOUNDATION_CONTAINER_START_FAILED:"
                + start.stderr.decode(
                    "utf-8",
                    errors="replace",
                )[-5000:]
            )

        wait = run(
            [
                "/usr/bin/podman",
                "wait",
                container_name,
            ],
            timeout=180,
        )

        if wait.returncode != 0:
            raise SelfdevBridgeError(
                "FOUNDATION_CONTAINER_WAIT_FAILED:"
                + wait.stderr.decode(
                    "utf-8",
                    errors="replace",
                )[-5000:]
            )

        try:
            tool_rc = int(
                wait.stdout.decode(
                    "ascii",
                    errors="strict",
                ).strip()
            )
        except Exception as exc:
            raise SelfdevBridgeError(
                "FOUNDATION_TOOL_RC_INVALID"
            ) from exc

        logs = run(
            [
                "/usr/bin/podman",
                "logs",
                container_name,
            ],
            timeout=30,
        )

        log_path = (
            task_root
            / "foundation-container.log"
        )

        log_path.write_bytes(
            logs.stdout
            + b"\n"
            + logs.stderr
        )
        set_private_mode(log_path, 0o600)

    finally:
        if created:
            run(
                [
                    "/usr/bin/podman",
                    "rm",
                    "-f",
                    container_name,
                ],
                timeout=30,
            )

        restore = run(
            [
                "/usr/bin/podman",
                "unshare",
                "chown",
                "-R",
                "0:0",
                str(gate_root),
            ],
            timeout=30,
        )

        if restore.returncode != 0:
            raise SelfdevBridgeError(
                "FOUNDATION_OWNERSHIP_RESTORE_FAILED:"
                + restore.stderr.decode(
                    "utf-8",
                    errors="replace",
                )[-3000:]
            )

    report_path = (
        output_dir
        / "report.json"
    )

    if (
        report_path.is_symlink()
        or not report_path.is_file()
        or report_path.stat().st_size == 0
    ):
        raise SelfdevBridgeError(
            "FOUNDATION_REPORT_MISSING"
        )

    report = json.loads(
        report_path.read_text(
            encoding="utf-8"
        )
    )

    if (
        report.get("schema")
        != "gg-code-gate-report-v1"
    ):
        raise SelfdevBridgeError(
            "FOUNDATION_REPORT_SCHEMA_INVALID"
        )

    source_record = report.get(
        "source"
    )

    if (
        not isinstance(
            source_record,
            dict,
        )
        or source_record.get(
            "sha256"
        )
        != candidate_sha
    ):
        raise SelfdevBridgeError(
            "FOUNDATION_SOURCE_SHA_MISMATCH"
        )

    static_checks = (
        report.get(
            "static_checks"
        )
        or []
    )

    failed_checks = [
        check
        for check in static_checks
        if (
            isinstance(
                check,
                dict,
            )
            and check.get(
                "return_code"
            )
            != 0
        )
    ]

    if (
        tool_rc != 0
        or report.get("status")
        != "PASS"
        or failed_checks
    ):
        raise SelfdevBridgeError(
            "FOUNDATION_GATE_NOT_PASS:"
            + json.dumps(
                {
                    "tool_rc":
                        tool_rc,
                    "status":
                        report.get(
                            "status"
                        ),
                    "messages":
                        report.get(
                            "messages"
                        ),
                    "failed_checks":
                        failed_checks,
                },
                ensure_ascii=False,
                sort_keys=True,
            )[-12000:]
        )

    return _selfdev_sha256(
        report_path.read_bytes()
    )

def _selfdev_run_regression(project: Path) -> str:
    tests = (
        "tests/test_autonomy_contract.py",
        "tests/test_autonomy_controller.py",
        "tests/test_write_contract.py",
        "tests/test_ux_baseline_contract.py",
    )

    evidence: list[str] = []

    for relative in tests:
        path = project / relative

        if not path.is_file():
            raise SelfdevBridgeError(
                "REGRESSION_TEST_MISSING:" + relative
            )

        result = subprocess.run(
            [
                executable_path("python3"),
                "-B",
                str(path),
            ],
            cwd=str(project),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            env=host_environment({
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
            }),
        )

        text = (
            result.stdout.decode("utf-8", errors="replace")
            + "\n"
            + result.stderr.decode("utf-8", errors="replace")
        )

        evidence.append(relative + "\n" + text[-8000:])

        if result.returncode != 0:
            raise SelfdevBridgeError(
                "REGRESSION_FAILED:"
                + relative
                + ":"
                + text[-5000:]
            )

    return "\n".join(evidence)

def _selfdev_source_context(
    source: str,
    diagnostic: str,
    maximum: int = SELFDEV_MAX_CONTEXT_CHARS,
) -> str:
    import ast

    if maximum < 2048:
        raise SelfdevBridgeError(
            "SELFDEV_CONTEXT_BUDGET_TOO_SMALL"
        )

    lines = source.splitlines(keepends=True)

    try:
        tree = ast.parse(source)

    except SyntaxError as exc:
        line = exc.lineno or 1
        start = max(0, line - 121)
        end = min(len(lines), line + 120)

        text = (
            "----- DIAGNOSTIC -----\n"
            + diagnostic[-6000:]
            + "\n----- INVALID PYTHON WINDOW -----\n"
            + "".join(lines[start:end])
            + "\n----- PARSE FAILURE -----\n"
            + type(exc).__name__
            + ":"
            + str(exc)
            + "\n"
        )

        return text[:maximum]

    chunks: list[str] = []
    used = 0

    def add(label: str, body: str) -> None:
        nonlocal used

        chunk = (
            "\n----- "
            + label
            + " -----\n"
            + body
        )

        if used + len(chunk) > maximum:
            if label not in {
                "ChatBridge.submit",
                "ChatBridge._submit_selfdev",
                "ChatBridge.__init__",
            }:
                return

            available = maximum - used
            header = (
                "\n----- "
                + label
                + " -----\n"
            )
            body_budget = (
                available
                - len(header)
            )
            truncation = (
                "\n...<FOCUS_TRUNCATED>...\n"
            )

            if (
                body_budget
                <= len(truncation) + 2
            ):
                return

            tail_budget = min(
                max(
                    1,
                    body_budget // 3,
                ),
                2048,
            )
            head_budget = (
                body_budget
                - len(truncation)
                - tail_budget
            )

            if head_budget <= 0:
                return

            body = (
                body[:head_budget]
                + truncation
                + body[-tail_budget:]
            )
            chunk = (
                header
                + body
            )

        chunks.append(chunk)
        used += len(chunk)

    if diagnostic:
        add(
            "DIAGNOSTIC",
            diagnostic[-6000:] + "\n",
        )

    first_definition = min(
        (
            node.lineno
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            )
        ),
        default=min(len(lines) + 1, 80),
    )

    add(
        "MODULE HEADER",
        "".join(
            lines[
                : min(
                    first_definition - 1,
                    120,
                )
            ]
        ),
    )

    top_level = {
        node.name: node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    def add_function(name: str) -> None:
        node = top_level.get(name)

        if node is None:
            return

        segment = ast.get_source_segment(
            source,
            node,
        )

        if segment is not None:
            add(
                "FUNCTION " + name,
                segment + "\n",
            )

    for name in (
        "parse_selfdev_command",
        "parse_autonomy_command",
        "parse_write_command",
        "parse_safe_tool_command",
    ):
        add_function(name)

    dynamic_top_level = sorted(
        name
        for name in top_level
        if (
            "intent" in name.lower()
            or "route" in name.lower()
            or "classif" in name.lower()
            or "dispatch" in name.lower()
        )
    )

    for name in dynamic_top_level:
        add_function(name)

    chat_bridge = next(
        (
            node
            for node in tree.body
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "ChatBridge"
            )
        ),
        None,
    )

    methods: dict[
        str,
        ast.FunctionDef | ast.AsyncFunctionDef,
    ] = {}

    if chat_bridge is not None:
        methods = {
            child.name: child
            for child in chat_bridge.body
            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
        }

        add(
            "ChatBridge METHOD INVENTORY",
            "\n".join(sorted(methods)) + "\n",
        )

        dynamic_methods = sorted(
            name
            for name in methods
            if (
                "intent" in name.lower()
                or "route" in name.lower()
                or "classif" in name.lower()
                or "dispatch" in name.lower()
            )
        )

        for name in (
            "_submit_selfdev",
            "submit",
            "__init__",
        ):
            node = methods.get(name)

            if node is None:
                continue

            segment = ast.get_source_segment(
                source,
                node,
            )

            if segment is not None:
                add(
                    "ChatBridge." + name,
                    segment + "\n",
                )

        for name in dynamic_methods:
            node = methods[name]
            segment = ast.get_source_segment(
                source,
                node,
            )

            if segment is not None:
                add(
                    "ChatBridge." + name,
                    segment + "\n",
                )

    for name in (
        "resolve_workspace_context",
        "build_effective_prompt",
        "_selfdev_validate_request",
        "_selfdev_validate_proposal",
        "_selfdev_apply_patch",
        "_selfdev_should_retry",
    ):
        add_function(name)

    for name in (
        "_selfdev_stdout_ready",
        "_selfdev_finished",
    ):
        node = methods.get(name)

        if node is None:
            continue

        segment = ast.get_source_segment(
            source,
            node,
        )

        if segment is not None:
            add(
                "ChatBridge." + name,
                segment + "\n",
            )

    text = "".join(chunks)

    if not text.strip():
        raise SelfdevBridgeError(
            "SELFDEV_CONTEXT_EMPTY"
        )

    return text[:maximum]

def _selfdev_model_call(
    task_id: str,
    goal: str,
    source: str,
    diagnostic: str,
    attempt: int,
) -> dict[str, str]:
    """Use the proven transport with a dedicated selfdev semantic profile."""
    from backend import autonomy_model_runner as semantic_transport

    done_old = "__GG_SELFDEV_DONE_OLD__"
    done_new = "__GG_SELFDEV_DONE_NEW__"

    prior = (
        diagnostic.strip()
        if diagnostic.strip()
        else "NONE"
    )

    prefix = (
        "Du är GG:s task-bound Python self-development proposer utan "
        "action-authority. TARGET är redan låst till "
        "projects/gg-ai-desktop/main.py. Du får inte välja path, command, "
        "executable, argv, Git, network, approval, authority eller scope. "
        "MODEL_OUTPUT=UNTRUSTED_MODEL_OUTPUT. "
        "Filler som bara skiljetecken, tomma platshållare eller upprepade tecken "
        "är förbjudet. HYPOTHESIS_JSON och WHY_JSON ska beskriva en konkret "
        "kodändring. OLD_JSON måste innehålla verklig Python byte-exakt kopierad "
        "från CURRENT SOURCE CONTEXT och inte ett påhittat exempel. Vid retry ska "
        "PRIOR VERIFIED DIAGNOSTIC repareras; upprepa inte samma avvisade OLD/NEW. "
        "Använd SELFDEV-semantic-profilens fyra obligatoriska JSON-stringfält: "
        "HYPOTHESIS_JSON, OLD_JSON, NEW_JSON och WHY_JSON. Skriv aldrig "
        "OLD:/NEW:-rubriker, sentinel-markörer eller förklaring utanför "
        "fälten. OLD_JSON och NEW_JSON ska representera multiline Python "
        "som JSON-strängar; deras dekodade värden ska kopieras byte-exakt "
        "från CURRENT SOURCE CONTEXT. OLD måste förekomma exakt en gång. "
        "Gör minsta rimliga replacement och använd flera bounded "
        "iterationer när uppgiften kräver flera ändringar. "
        "Om målet redan är uppfyllt utan ändring ska OLD vara exakt "
        + done_old
        + " och NEW exakt "
        + done_new
        + ". HYPOTHESIS och WHY är endast oauktoritativ förklaring.\n\n"
        "TASK_ID:\n"
        + task_id
        + "\nATTEMPT:\n"
        + str(attempt)
        + "\nGOAL:\n"
        + goal
        + "\nPRIOR VERIFIED DIAGNOSTIC:\n"
        + prior[-6000:]
        + "\nCURRENT SOURCE CONTEXT:\n"
    )

    context_budget = min(
        SELFDEV_MAX_CONTEXT_CHARS,
        SELFDEV_MAX_PROMPT_CHARS - len(prefix),
    )

    if context_budget < 4096:
        raise SelfdevBridgeError(
            "SELFDEV_PROMPT_BUDGET_EXHAUSTED"
        )

    context = _selfdev_source_context(
        source,
        diagnostic,
        context_budget,
    )

    prompt = prefix + context

    if len(prompt) > SELFDEV_MAX_PROMPT_CHARS:
        raise SelfdevBridgeError(
            "SELFDEV_PROMPT_TOO_LARGE"
        )

    request_id = (
        "autonomy-model-selfdev-"
        + os.urandom(12).hex()
    )

    try:
        (
            rc,
            semantic,
            _evidence,
            _render,
        ) = (
            semantic_transport
            .run_selfdev_semantic_prompt(
                request_id=request_id,
                prompt=prompt,
            )
        )

    except Exception as exc:
        raise SelfdevBridgeError(
            "SHARED_SEMANTIC_TRANSPORT:"
            + type(exc).__name__
            + ":"
            + str(exc)
        ) from exc

    if rc != 0:
        raise SelfdevBridgeError(
            "SHARED_SEMANTIC_TRANSPORT_RC:"
            + str(rc)
        )

    if semantic is None:
        raise SelfdevBridgeError(
            "SHARED_SEMANTIC_PROPOSAL_MISSING"
        )

    old_text = semantic["old_text"]
    new_text = semantic["new_text"]

    if (
        source.count(old_text) != 1
        and old_text.startswith(" ")
        and new_text.startswith(" ")
        and source.count(old_text[1:]) == 1
    ):
        old_text = old_text[1:]
        new_text = new_text[1:]

    if (
        old_text == done_old
        and new_text == done_new
    ):
        return {
            "action": "DONE",
            "summary": semantic["hypothesis"],
            "old_text": "",
            "new_text": "",
        }

    return {
        "action": "PATCH",
        "summary": semantic["hypothesis"],
        "old_text": old_text,
        "new_text": new_text,
    }

def _selfdev_post_patch_noop_completion(
    exc: Exception,
    patch_count: int,
    synthetic: bool,
) -> dict[str, str] | None:
    if synthetic or patch_count < 1:
        return None

    if not str(exc).endswith(
        "SELFDEV_SEMANTIC_CONTRACT:NO_OP"
    ):
        return None

    return {
        "action": "DONE",
        "summary": (
            "Verifierad candidate-patch är färdig; "
            "modellen föreslog ingen ytterligare ändring."
        ),
        "old_text": "",
        "new_text": "",
    }

def _selfdev_should_retry(
    stage: str,
    exc: Exception,
    synthetic: bool,
) -> bool:
    if synthetic:
        return False

    message = str(exc)

    if stage == "MODEL":
        return (
            "SELFDEV_SEMANTIC_CONTRACT:" in message
            or "SELFDEV_MODEL_FORMAT_" in message
            or "MODEL_SEMANTIC_CONTRACT:" in message
        )

    if not isinstance(exc, SelfdevBridgeError):
        return (
            stage == "COMPILE"
            and isinstance(exc, SyntaxError)
        )

    if stage == "PATCH":
        return (
            message.startswith(
                "OLD_TEXT_OCCURRENCE_COUNT:"
            )
            or message == "CANDIDATE_SIZE_INVALID"
        )

    if stage == "DONE":
        return message == "DONE_WITHOUT_CHANGE"

    if stage == "VERIFY":
        return (
            message.startswith(
                "FOUNDATION_GATE_NOT_PASS:"
            )
            or message.startswith(
                "REGRESSION_FAILED:"
            )
        )

    return False

def _selfdev_controller(
    request_path_raw: str,
    synthetic_proposal_path: str | None = None,
    synthetic_repo_root: str | None = None,
) -> int:
    import stat

    runtime = _selfdev_runtime()
    request_path = Path(request_path_raw)

    if request_path.parent.resolve(strict=True) != runtime:
        raise SelfdevBridgeError("REQUEST_PARENT_INVALID")

    if request_path.is_symlink() or not request_path.is_file():
        raise SelfdevBridgeError("REQUEST_FILE_INVALID")

    info = request_path.stat()

    if (
        not owned_by_current_user(request_path)
        or not mode_matches(request_path, 0o600)
    ):
        raise SelfdevBridgeError("REQUEST_OWNER_MODE_INVALID")

    request = _selfdev_validate_request(
        json.loads(
            request_path.read_text(encoding="utf-8")
        )
    )

    if synthetic_repo_root is not None:
        if synthetic_proposal_path is None:
            raise SelfdevBridgeError(
                "SYNTHETIC_REPO_REQUIRES_SYNTHETIC_PROPOSAL"
            )

        runtime = _selfdev_runtime()

        repo = Path(
            synthetic_repo_root
        ).resolve(strict=True)

        if (
            not repo.is_dir()
            or repo.parent != runtime
            or not repo.name.startswith(
                "gg-selfdev-synthetic-repo."
            )
        ):
            raise SelfdevBridgeError(
                "SYNTHETIC_REPO_INVALID"
            )
    else:
        repo = _selfdev_repo_root()

    _selfdev_state_lock(
        repo,
        str(request["base_head"]),
    )

    host_target = _selfdev_host_target(repo)
    host_before = host_target.read_bytes()

    if (
        _selfdev_sha256(host_before)
        != request["target_sha256"]
    ):
        raise SelfdevBridgeError("HOST_TARGET_STALE")

    task_id = str(request["task_id"])

    task_root = (
        runtime
        / ("gg-selfdev-task." + task_id.removeprefix("task-"))
    )

    if task_root.exists():
        raise SelfdevBridgeError("TASK_ROOT_ALREADY_EXISTS")

    task_root.mkdir(mode=0o700)

    tree = task_root / "tree"

    _selfdev_extract_tree(
        repo,
        str(request["base_head"]),
        tree,
    )

    candidate_project = tree / "projects" / "gg-ai-desktop"
    candidate = candidate_project / "main.py"

    if not candidate.is_file():
        raise SelfdevBridgeError("CANDIDATE_MAIN_MISSING")

    if candidate.read_bytes() != host_before:
        raise SelfdevBridgeError("CANDIDATE_BASE_MISMATCH")

    sequence = 0

    def emit(phase: str, state: str, text: str) -> None:
        nonlocal sequence
        sequence += 1
        _selfdev_event(sequence, phase, state, text)

    emit(
        "INTENT",
        "RUNNING",
        "SELFDEV_MAIN_PY_V1 task låst till main.py.",
    )

    emit(
        "REVALIDATE",
        "PASS",
        "Base HEAD och clean host repo verifierade.",
    )

    emit(
        "CANDIDATE",
        "PASS",
        "Task-bound candidate tree materialiserad under runtime.",
    )

    synthetic: dict[str, str] | None = None

    if synthetic_proposal_path is not None:
        synthetic_path = Path(synthetic_proposal_path)

        if (
            synthetic_path.parent.resolve(strict=True) != runtime
            or synthetic_path.is_symlink()
            or not synthetic_path.is_file()
        ):
            raise SelfdevBridgeError(
                "SYNTHETIC_PROPOSAL_PATH_INVALID"
            )

        synthetic = _selfdev_validate_proposal(
            json.loads(
                synthetic_path.read_text(encoding="utf-8")
            )
        )

    diagnostic = ""
    patch_count = 0
    model_calls = 0
    gate_sha = ""
    regression_text = ""

    while True:
        current_source = candidate.read_text(encoding="utf-8")

        if synthetic is not None:
            if patch_count == 0:
                proposal = synthetic
            else:
                proposal = {
                    "action": "DONE",
                    "summary": "Synthetic deterministic proof complete.",
                    "old_text": "",
                    "new_text": "",
                }
        else:
            model_calls += 1

            if model_calls > SELFDEV_MAX_MODEL_CALLS:
                raise SelfdevBridgeError(
                    "MODEL_CALL_LIMIT_EXCEEDED"
                )

            emit(
                "HYPOTHESIZE",
                "RUNNING",
                "Lokal bounded selfdev-proposer arbetar.",
            )

            try:
                proposal = _selfdev_model_call(
                    str(request["task_id"]),
                    str(request["goal"]),
                    current_source,
                    diagnostic,
                    model_calls,
                )

            except Exception as exc:
                completion = (
                    _selfdev_post_patch_noop_completion(
                        exc,
                        patch_count,
                        synthetic is not None,
                    )
                )

                if completion is not None:
                    proposal = completion

                    emit(
                        "OBSERVE",
                        "PASS",
                        (
                            "Ingen ytterligare candidate-ändring "
                            "föreslogs efter verifierad patch."
                        ),
                    )

                else:
                    if not _selfdev_should_retry(
                        "MODEL",
                        exc,
                        synthetic is not None,
                    ):
                        raise

                    diagnostic = (
                        "MODEL_PROPOSAL_REJECTED:"
                        + type(exc).__name__
                        + ":"
                        + str(exc)
                    )

                    emit(
                        "OBSERVE",
                        "FAIL",
                        diagnostic[-1500:],
                    )

                    emit(
                        "REPLAN",
                        "RUNNING",
                        (
                            "Ogiltigt modellförslag återgår "
                            "till bounded retry."
                        ),
                    )

                    continue

        emit(
            "PLAN",
            "PASS",
            proposal["summary"][:1000],
        )

        if proposal["action"] == "PATCH":
            if patch_count >= SELFDEV_MAX_PATCHES:
                raise SelfdevBridgeError(
                    "PATCH_LIMIT_EXCEEDED"
                )

            try:
                _selfdev_apply_patch(
                    candidate,
                    proposal,
                )

            except Exception as exc:
                if not _selfdev_should_retry(
                    "PATCH",
                    exc,
                    synthetic is not None,
                ):
                    raise

                diagnostic = (
                    "PATCH_REJECTED:"
                    + type(exc).__name__
                    + ":"
                    + str(exc)
                )

                emit(
                    "OBSERVE",
                    "FAIL",
                    diagnostic[-1500:],
                )

                emit(
                    "REPLAN",
                    "RUNNING",
                    "Ogiltig candidate-patch återgår till bounded retry.",
                )

                continue

            patch_count += 1

            emit(
                "ACT",
                "PASS",
                "Candidate main.py ändrad; host main.py orörd.",
            )

            try:
                _selfdev_compile(candidate)

            except Exception as exc:
                if not _selfdev_should_retry(
                    "COMPILE",
                    exc,
                    synthetic is not None,
                ):
                    raise

                diagnostic = (
                    "PYTHON_COMPILE_FAIL:"
                    + type(exc).__name__
                    + ":"
                    + str(exc)
                )

                emit(
                    "OBSERVE",
                    "FAIL",
                    diagnostic[-1500:],
                )

                emit(
                    "REPLAN",
                    "RUNNING",
                    "Compile-failure återgår till candidate repair.",
                )

                continue

            emit(
                "VERIFY",
                "PASS",
                "Python compile PASS.",
            )

            diagnostic = ""
            continue

        if patch_count == 0:
            done_error = SelfdevBridgeError(
                "DONE_WITHOUT_CHANGE"
            )

            if not _selfdev_should_retry(
                "DONE",
                done_error,
                synthetic is not None,
            ):
                raise done_error

            diagnostic = (
                "PREMATURE_DONE:"
                + str(done_error)
            )

            emit(
                "OBSERVE",
                "FAIL",
                diagnostic,
            )

            emit(
                "REPLAN",
                "RUNNING",
                "DONE utan candidate-change återgår till bounded retry.",
            )

            continue

        try:
            gate_sha = _selfdev_foundation_gate(
                candidate,
                task_root,
            )

            emit(
                "TEST",
                "PASS",
                "Foundation Python Gate PASS.",
            )

            regression_text = _selfdev_run_regression(
                candidate_project
            )

            emit(
                "REGRESSION",
                "PASS",
                "Legacy regression PASS.",
            )

            break

        except Exception as exc:
            if not _selfdev_should_retry(
                "VERIFY",
                exc,
                synthetic is not None,
            ):
                raise

            diagnostic = (
                type(exc).__name__
                + ":"
                + str(exc)
            )

            emit(
                "OBSERVE",
                "FAIL",
                diagnostic[-1500:],
            )

            emit(
                "REPLAN",
                "RUNNING",
                "Source Gate/regression-failure återgår till candidate repair.",
            )

    _selfdev_state_lock(
        repo,
        str(request["base_head"]),
    )

    host_after = host_target.read_bytes()

    if host_after != host_before:
        raise SelfdevBridgeError(
            "HOST_MAIN_CHANGED_DURING_SELFDEV"
        )

    candidate_bytes = candidate.read_bytes()
    diff = _selfdev_diff(host_before, candidate_bytes)

    if not diff:
        raise SelfdevBridgeError("VERIFIED_CHANGESET_EMPTY")

    result = {
        "schema": "gg.workbench.selfdev-result.v1",
        "task_id": task_id,
        "base_head": request["base_head"],
        "target_relative_path": SELFDEV_TARGET_REPO_RELATIVE,
        "before_sha256": _selfdev_sha256(host_before),
        "candidate_sha256": _selfdev_sha256(candidate_bytes),
        "diff_sha256": _selfdev_sha256(diff.encode("utf-8")),
        "foundation_gate_report_sha256": gate_sha,
        "candidate_write_count": patch_count,
        "model_call_count": model_calls,
        "host_repo_changed": False,
        "persistent_selfdev_write": "NONE",
        "status": "WAITING_PERSISTENT_APPLY",
    }

    result_path = task_root / "verified-result.json"
    diff_path = task_root / "verified.diff"
    regression_path = task_root / "regression.txt"

    result_path.write_bytes(_selfdev_canonical(result))
    set_private_mode(result_path, 0o600)

    diff_path.write_text(diff, encoding="utf-8")
    set_private_mode(diff_path, 0o600)

    regression_path.write_text(
        regression_text,
        encoding="utf-8",
    )
    set_private_mode(regression_path, 0o600)

    emit(
        "CHANGESET",
        "PASS",
        "VERIFIED CHANGESET fryst i task runtime.",
    )

    emit(
        "BOUNDARY",
        "WAITING_FOR_USER",
        "Persistent selfdev host-write är inte granted.",
    )

    print("SELFDEV_PROFILE_EXACT_MAIN_PY=PASS", flush=True)
    print("MAIN_PY_HOST_READ_ONLY_DURING_SELFDEV=PASS", flush=True)
    print("TASK_BOUND_CANDIDATE_WRITE=PASS", flush=True)
    print("SELFDEV_MODEL_OUTPUT_UNTRUSTED=PASS", flush=True)
    print("SELFDEV_MODEL_CANNOT_SELECT_PATH=PASS", flush=True)
    print("SELFDEV_MODEL_CANNOT_GRANT_AUTHORITY=PASS", flush=True)
    print("FOUNDATION_PYTHON_GATE=PASS", flush=True)
    print("VERIFIED_CHANGESET=PASS", flush=True)
    print("SELFDEV_STATUS=WAITING_PERSISTENT_APPLY", flush=True)
    print("PERSISTENT_SELFDEV_WRITE=NONE", flush=True)
    print("SELFDEV_RESULT_PATH=" + str(result_path), flush=True)

    return 0

def _selfdev_selftest() -> int:
    valid = _selfdev_validate_proposal(
        {
            "action": "PATCH",
            "summary": "bounded",
            "old_text": "alpha",
            "new_text": "beta",
        }
    )

    if valid["old_text"] != "alpha":
        raise SelfdevBridgeError("SELFTEST_VALID_PROPOSAL")

    injected = dict(valid)
    injected["path"] = "/etc/passwd"

    try:
        _selfdev_validate_proposal(injected)
    except SelfdevBridgeError:
        pass
    else:
        raise SelfdevBridgeError(
            "SELFTEST_PATH_INJECTION_ACCEPTED"
        )

    parsed = parse_selfdev_command(
        "/selfdev implementera bounded candidate"
    )

    if parsed is None or parsed["action"] != "START":
        raise SelfdevBridgeError("SELFTEST_PARSE")

    print("SELFDEV_PROFILE_EXACT_MAIN_PY=PASS")
    print("SELFDEV_MODEL_OUTPUT_UNTRUSTED=PASS")
    print("SELFDEV_MODEL_CANNOT_SELECT_PATH=PASS")
    print("SELFDEV_MODEL_CANNOT_GRANT_AUTHORITY=PASS")
    print("SELFDEV_PARSE_ENTRYPOINT=PASS")
    print("SELFDEV_PERSISTENT_APPLY=NOT_GRANTED")
    print("SELFDEV_SELFTEST=PASS")

    return 0

def parse_autonomy_command(text: str) -> dict[str, object] | None:
    value = text.strip()
    if not value.startswith("/"):
        return None

    command, separator, remainder = value.partition(" ")
    command = command.lower()
    argument = remainder.strip() if separator else ""

    if command in ("/autonomy", "/autonomy-selftest"):
        if not argument or len(argument) > 4096 or "\x00" in argument:
            raise ValueError(
                "Usage: /autonomy GOAL or /autonomy-selftest GOAL"
            )
        return {
            "action": "START",
            "goal": argument,
            "test_mode": (
                "INTENTIONAL_FIRST_GATE_FAILURE"
                if command == "/autonomy-selftest"
                else "NONE"
            ),
        }

    if command in ("/approve-autonomy", "/cancel-autonomy"):
        parts = argument.split()
        if len(parts) != 2:
            raise ValueError(
                "Usage: "
                + command
                + " task-<id> <grant_sha256>"
            )
        task_id, grant_sha = parts
        if autonomy_contract.TASK_ID_RE.fullmatch(task_id) is None:
            raise ValueError("Autonomy task id invalid.")
        if autonomy_contract.SHA256_RE.fullmatch(grant_sha) is None:
            raise ValueError("Autonomy grant SHA-256 invalid.")
        return {
            "action": (
                "APPROVE"
                if command == "/approve-autonomy"
                else "CANCEL"
            ),
            "task_id": task_id,
            "grant_sha256": grant_sha,
        }

    return None

def parse_write_command(text: str) -> dict[str, object] | None:
    value = text.strip()

    if not value.startswith("/"):
        return None

    command, separator, remainder = value.partition(" ")
    command = command.lower()
    argument = remainder.strip() if separator else ""

    if command == "/patch-current":
        if argument.count(" => ") != 1:
            raise ValueError(
                "Usage: /patch-current EXACT_OLD_TEXT => EXACT_NEW_TEXT"
            )
        old_text, new_text = argument.split(" => ", 1)
        if not old_text or not new_text:
            raise ValueError(
                "Usage: /patch-current EXACT_OLD_TEXT => EXACT_NEW_TEXT"
            )
        return {
            "action": write_contract.ACTION_PROPOSE,
            "arguments": {
                "old_text": old_text,
                "new_text": new_text,
            },
        }

    if command in ("/approve-write", "/reject-write"):
        parts = argument.split()
        if len(parts) != 2:
            raise ValueError(
                "Usage: "
                + command
                + " proposal-<id> <candidate_sha256>"
            )

        proposal_id, candidate_sha256 = parts
        action = (
            write_contract.ACTION_APPROVE
            if command == "/approve-write"
            else write_contract.ACTION_REJECT
        )
        return {
            "action": action,
            "proposal_id": proposal_id,
            "arguments": {
                "candidate_sha256": candidate_sha256,
            },
        }

    if command == "/rollback-write":
        parts = argument.split()
        if len(parts) != 3:
            raise ValueError(
                "Usage: /rollback-write "
                "proposal-<id> <candidate_sha256> <before_sha256>"
            )

        proposal_id, candidate_sha256, before_sha256 = parts
        return {
            "action": write_contract.ACTION_ROLLBACK,
            "proposal_id": proposal_id,
            "arguments": {
                "candidate_sha256": candidate_sha256,
                "before_sha256": before_sha256,
            },
        }

    return None

def parse_safe_tool_command(text: str) -> dict[str, object] | None:
    value = text.strip()

    if not value.startswith("/"):
        return None

    command, separator, remainder = value.partition(" ")
    command = command.lower()
    argument = remainder.strip() if separator else ""

    if command == "/read":
        if not argument:
            raise ValueError(
                "Usage: /read REPO_RELATIVE_PATH"
            )
        request = {
            "profile": tool_contract.PROFILE_READ,
            "arguments": {"path": argument},
        }

    elif command == "/search":
        if not argument:
            raise ValueError(
                "Usage: /search LITERAL_TEXT"
            )
        request = {
            "profile": tool_contract.PROFILE_SEARCH,
            "arguments": {"literal": argument},
        }

    elif command == "/git":
        if argument not in tool_contract.GIT_OPERATIONS:
            raise ValueError(
                "Usage: /git status|diff|log|show-head"
            )
        request = {
            "profile": tool_contract.PROFILE_GIT,
            "arguments": {"operation": argument},
        }

    elif command == "/test":
        if argument:
            raise ValueError("Usage: /test")
        request = {
            "profile": tool_contract.PROFILE_TEST,
            "arguments": {},
        }

    elif command == "/run":
        if argument:
            raise ValueError("Usage: /run")
        request = {
            "profile": tool_contract.PROFILE_RUN,
            "arguments": {},
        }

    else:
        raise ValueError(
            "Unknown Safe Tool command. "
            "Use /read, /search, /git, /test or /run."
        )

    return request

def load_config() -> dict[str, object]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if PROJECT == REPO_ROOT:
        control = config.get("control_plane", {})
        if control.get("bootstrap_target") == "projects/gg-ai-desktop/main.py":
            control["bootstrap_target"] = desktop_relative_path("main.py")
    return config

def qml_initial_properties(config: dict[str, object]) -> dict[str, object]:
    safety = config["safety"]
    live_aid = config["live_aid"]

    if not isinstance(safety, dict):
        raise RuntimeError("Invalid safety configuration.")
    if not isinstance(live_aid, dict):
        raise RuntimeError("Invalid Live Aid configuration.")

    return {
        "workbenchVersion": config["version"],
        "dataMode": config["data_mode"],
        "interactionModel": config["interaction_model"],
        "visualChangePolicy": safety["visual_change_policy"],
        "operatorTerminalPolicy": safety[
            "operator_terminal_direct_ai_input"
        ],
        "reasoningEvidencePolicy": safety[
            "reasoning_summary_and_evidence_ui"
        ],
        "liveAidDraftBlocking": live_aid["draft_blocking"],
        "shadowVerificationMode": live_aid["real_checker"],
        "shellLoadQueueJson": json.dumps(shell_load.queue()),
    }

def discover_nvidia_render() -> Path:
    matches: list[Path] = []

    for device_link in sorted(
        Path("/sys/class/drm").glob("renderD*/device")
    ):
        try:
            vendor = (device_link / "vendor").read_text(
                encoding="ascii"
            ).strip()
        except OSError:
            continue

        if vendor == "0x10de":
            matches.append(
                Path("/dev/dri") / device_link.parent.name
            )

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one NVIDIA render node; "
            f"found {len(matches)}."
        )

    target = matches[0]

    if not target.exists():
        raise RuntimeError(
            f"NVIDIA render node disappeared: {target}"
        )

    return target

class LiveAidQtBridge(QObject):
    """Read-only Workspace authoring buffer → Live Aid bridge."""

    resultReady = Signal(str, str)
    analysisFailed = Signal(str, str)
    preflightReady = Signal(str, str)
    preflightFailed = Signal(str, str)
    repairReady = Signal(str, str)
    repairFailed = Signal(str, str)
    repairApplied = Signal(str, str, str)
    postDraftEvent = Signal(str, str)
    postDraftReady = Signal(str, str)
    postDraftFailed = Signal(str, str)

    _LANGUAGE_BY_SUFFIX = {
        ".py": "python",
        ".qml": "qml",
        ".json": "json",
        ".sh": "shell",
    }
    _MAX_BUFFER_BYTES = 65536

    def __init__(
        self,
        repo_root: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo_root = repo_root.resolve(strict=True)
        self._service = LiveAidService(self._repo_root)
        self._preflight_process: QProcess | None = None
        self._preflight_state: dict[str, object] | None = None
        self._preflight_results: dict[str, dict[str, object]] = {}
        self._repair_process: QProcess | None = None
        self._repair_state: dict[str, object] | None = None
        self._repair_proposals: dict[str, dict[str, object]] = {}
        self._post_draft_process: QProcess | None = None
        self._post_draft_state: dict[str, object] | None = None
        self._post_draft_stdout_buffer = b""

    def _read_workspace_source(
        self,
        object_id: str,
    ) -> dict[str, object]:
        spec = WORKSPACE_CONTEXTS.get(object_id)

        if spec is None:
            raise RuntimeError(
                "Workspace object is not an allowlisted real source."
            )

        relative = Path(spec["relative_path"])

        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                "Workspace authoring source path policy violation."
            )

        project_root = PROJECT.resolve(strict=True)
        candidate = PROJECT / relative
        parent = candidate.parent.resolve(strict=True)

        if not parent.is_relative_to(project_root):
            raise RuntimeError(
                "Workspace authoring source escaped project root."
            )

        flags = os.O_RDONLY | NOFOLLOW

        try:
            fd = secure_open(candidate, flags)
        except OSError as exc:
            raise RuntimeError(
                "Workspace authoring source could not be opened safely: "
                + str(exc)
            ) from exc

        try:
            info = os.fstat(fd)

            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError(
                    "Workspace authoring source is not a regular file."
                )

            if info.st_size < 1:
                raise RuntimeError(
                    "Workspace authoring source is empty."
                )

            if info.st_size > WORKSPACE_CONTEXT_MAX_BYTES:
                raise RuntimeError(
                    "Workspace authoring source exceeds read limit."
                )

            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(
                    WORKSPACE_CONTEXT_MAX_BYTES + 1
                )
        finally:
            os.close(fd)

        if len(data) > WORKSPACE_CONTEXT_MAX_BYTES:
            raise RuntimeError(
                "Workspace authoring source exceeded bounded read."
            )

        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                "Workspace authoring source is not UTF-8."
            ) from exc

        language = self._LANGUAGE_BY_SUFFIX.get(
            relative.suffix.lower()
        )

        if language is None:
            raise RuntimeError(
                "Workspace authoring source language is unsupported."
            )

        return {
            "schema": "gg.live-aid.source-buffer.v1",
            "status": "PASS",
            "object_id": object_id,
            "source_name": relative.name,
            "relative_path": relative.as_posix(),
            "language": language,
            "source": source,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "source_bytes": len(data),
            "disk_write_authority": "NONE",
        }

    @Slot(str, result=str)
    def loadSource(self, object_id: str) -> str:
        try:
            payload = self._read_workspace_source(object_id)
        except Exception as exc:
            payload = {
                "schema": "gg.live-aid.source-buffer.v1",
                "status": "FAIL",
                "object_id": object_id,
                "message": type(exc).__name__ + ":" + str(exc),
                "disk_write_authority": "NONE",
            }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _validate_authoring_request(
        self,
        object_id: str,
        source_name: str,
        source: str,
        language: str,
    ) -> None:
        spec = WORKSPACE_CONTEXTS.get(object_id)

        if spec is None:
            raise RuntimeError(
                "Live Aid target is not an allowlisted Workspace source."
            )

        relative = Path(spec["relative_path"])
        expected_language = self._LANGUAGE_BY_SUFFIX.get(
            relative.suffix.lower()
        )

        if source_name != relative.name:
            raise RuntimeError(
                "Live Aid source name does not match Workspace target."
            )

        if language != expected_language:
            raise RuntimeError(
                "Live Aid language does not match Workspace target."
            )

        encoded = source.encode("utf-8")

        if len(encoded) > self._MAX_BUFFER_BYTES:
            raise RuntimeError(
                "Live Aid authoring buffer exceeds 64 KiB."
            )

    def _run_analysis(
        self,
        object_id: str,
        source_name: str,
        source: str,
        language: str,
    ) -> None:
        try:
            result = self._service.analyze(
                object_id=object_id,
                source_name=source_name,
                source=source,
                language=language,
            )

            if (
                result.get("schema")
                != "gg.live-aid.bridge-response.v1"
            ):
                raise RuntimeError(
                    "Live Aid backend response schema mismatch."
                )

            if result.get("action_authority") != "NONE":
                raise RuntimeError(
                    "Live Aid unexpectedly gained action authority."
                )

            if result.get("network_authority") != "NONE":
                raise RuntimeError(
                    "Live Aid unexpectedly gained network authority."
                )

            payload = json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except Exception as exc:
            self.analysisFailed.emit(
                object_id,
                type(exc).__name__ + ":" + str(exc),
            )
            return

        self.resultReady.emit(object_id, payload)

    def _preflight_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._preflight_process
        state = self._preflight_state

        if process is None or state is None:
            return

        stdout = bytes(
            process.readAllStandardOutput()
        ).decode("utf-8", "replace").strip()

        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", "replace").strip()

        object_id = str(state["object_id"])
        request_id = str(state["request_id"])
        source_sha256 = str(
            state["source_sha256"]
        )
        request_path = Path(
            str(state["request_path"])
        )

        try:
            request_path.unlink(missing_ok=True)
        except OSError:
            pass

        self._preflight_process = None
        self._preflight_state = None

        process.deleteLater()

        if (
            exit_status
            != QProcess.ExitStatus.NormalExit
            or exit_code != 0
        ):
            message = (
                stderr
                or stdout
                or "QML preflight runner failed."
            )

            self.preflightFailed.emit(
                object_id,
                message,
            )
            return

        try:
            value = json.loads(stdout)

            if not isinstance(value, dict):
                raise RuntimeError(
                    "QML preflight response is not an object."
                )

            validated = (
                qml_preflight_runner.validate_response(
                    value,
                    expected_request_id=request_id,
                    expected_object_id=object_id,
                    expected_source_sha256=source_sha256,
                )
            )

            self._preflight_results[object_id] = validated

            payload = json.dumps(
                validated,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        except Exception as exc:
            self.preflightFailed.emit(
                object_id,
                type(exc).__name__ + ":" + str(exc),
            )
            return

        self.preflightReady.emit(
            object_id,
            payload,
        )

    @Slot(str, str, str, str)
    def preflight(
        self,
        object_id: str,
        source_name: str,
        source: str,
        language: str,
    ) -> None:
        try:
            self._validate_authoring_request(
                object_id,
                source_name,
                source,
                language,
            )

            self._preflight_results.pop(
                object_id,
                None,
            )

            if language != "qml":
                raise RuntimeError(
                    "QML preflight only supports QML."
                )

            if (
                self._preflight_process is not None
                and self._preflight_process.state()
                != QProcess.ProcessState.NotRunning
            ):
                raise RuntimeError(
                    "QML preflight is already running."
                )

            spec = WORKSPACE_CONTEXTS.get(
                object_id
            )

            if spec is None:
                raise RuntimeError(
                    "Workspace preflight target is unavailable."
                )

            relative = Path(
                spec["relative_path"]
            )

            if (
                relative.name != source_name
                or relative.suffix.lower() != ".qml"
            ):
                raise RuntimeError(
                    "Workspace preflight target binding mismatch."
                )

            request_id = (
                "preflight-" + uuid.uuid4().hex
            )

            source_sha256 = hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest()

            request = (
                qml_preflight_runner.validate_request(
                    {
                        "schema": (
                            qml_preflight_runner
                            .REQUEST_SCHEMA
                        ),
                        "request_id": request_id,
                        "object_id": object_id,
                        "source_name": source_name,
                        "source_relative_path": (
                            relative.as_posix()
                        ),
                        "language": language,
                        "source": source,
                        "source_sha256": source_sha256,
                    }
                )
            )

            runtime_root = private_runtime_root()

            run_dir = runtime_root / (
                "gg-live-aid-preflight."
                + uuid.uuid4().hex
            )

            run_dir.mkdir(mode=0o700)

            request_path = (
                run_dir / "request.json"
            )

            encoded_request = (
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")

            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | NOFOLLOW
            )

            fd = secure_open(
                request_path,
                flags,
                0o600,
            )

            try:
                with os.fdopen(
                    fd,
                    "wb",
                    closefd=False,
                ) as handle:
                    handle.write(encoded_request)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                os.close(fd)

            process = QProcess(self)

            process.setProgram(
                executable_path("python3")
            )

            process.setArguments(
                [
                    "-B",
                    str(PREFLIGHT_RUNNER_PATH),
                    str(request_path),
                ]
            )

            process.setWorkingDirectory(
                str(PROJECT)
            )

            process.setProcessChannelMode(
                QProcess.ProcessChannelMode
                .SeparateChannels
            )

            self._preflight_process = process
            self._preflight_state = {
                "object_id": object_id,
                "request_id": request_id,
                "source_sha256": source_sha256,
                "request_path": str(request_path),
            }

            process.finished.connect(
                self._preflight_finished
            )

            process.start()

            if not process.waitForStarted(1500):
                self._preflight_process = None
                self._preflight_state = None

                request_path.unlink(
                    missing_ok=True
                )

                process.deleteLater()

                raise RuntimeError(
                    "QML preflight runner did not start."
                )

        except Exception as exc:
            self.preflightFailed.emit(
                object_id,
                type(exc).__name__ + ":" + str(exc),
            )

    @Slot(int, QProcess.ExitStatus)
    def _repair_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._repair_process
        state = self._repair_state

        if process is None or state is None:
            return

        stdout = bytes(
            process.readAllStandardOutput()
        ).decode("utf-8", "replace").strip()

        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", "replace").strip()

        object_id = str(
            state["object_id"]
        )
        request_id = str(
            state["request_id"]
        )
        source_sha256 = str(
            state["source_sha256"]
        )
        run_dir = Path(
            str(state["run_dir"])
        )

        self._repair_process = None
        self._repair_state = None

        process.deleteLater()

        shutil.rmtree(
            run_dir,
            ignore_errors=True,
        )

        if (
            exit_status
            != QProcess.ExitStatus.NormalExit
            or exit_code != 0
        ):
            self.repairFailed.emit(
                object_id,
                stderr
                or stdout
                or "Local repair model failed.",
            )
            return

        try:
            value = json.loads(stdout)

            validated = (
                repair_model_runner
                .validate_response(
                    value,
                    expected_request_id=request_id,
                    expected_object_id=object_id,
                    expected_source_sha256=
                        source_sha256,
                )
            )

            proposal_id = str(
                validated["proposal_id"]
            )

            self._repair_proposals[
                proposal_id
            ] = validated

            payload = json.dumps(
                validated,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        except Exception as exc:
            self.repairFailed.emit(
                object_id,
                type(exc).__name__
                + ":"
                + str(exc),
            )
            return

        self.repairReady.emit(
            object_id,
            payload,
        )

    @Slot(str, str, str, str)
    def requestRepair(
        self,
        object_id: str,
        source_name: str,
        source: str,
        language: str,
    ) -> None:
        try:
            self._validate_authoring_request(
                object_id,
                source_name,
                source,
                language,
            )

            if language != "qml":
                raise RuntimeError(
                    "AI repair currently supports QML only."
                )

            if (
                self._repair_process is not None
                and self._repair_process.state()
                != QProcess.ProcessState.NotRunning
            ):
                raise RuntimeError(
                    "AI repair proposal is already running."
                )

            source_sha256 = hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest()

            preflight = (
                self._preflight_results.get(
                    object_id
                )
            )

            if preflight is None:
                raise RuntimeError(
                    "AI repair requires a current QML preflight."
                )

            if preflight.get("status") != "FAIL":
                raise RuntimeError(
                    "AI repair requires a proven QML Gate FAIL."
                )

            if (
                preflight.get("source_sha256")
                != source_sha256
            ):
                raise RuntimeError(
                    "AI repair preflight is stale for current buffer."
                )

            diagnostics = preflight.get(
                "diagnostics"
            )

            if (
                not isinstance(
                    diagnostics,
                    list,
                )
                or not diagnostics
            ):
                raise RuntimeError(
                    "AI repair has no proven diagnostics."
                )

            report_sha = preflight.get(
                "gate_report_sha256"
            )

            if not isinstance(
                report_sha,
                str,
            ):
                raise RuntimeError(
                    "AI repair has no attested Gate report."
                )

            request_id = (
                "repair-model-"
                + uuid.uuid4().hex
            )

            request = (
                repair_model_runner
                .validate_request(
                    {
                        "schema":
                            repair_model_runner
                            .REQUEST_SCHEMA,
                        "request_id":
                            request_id,
                        "object_id":
                            object_id,
                        "source_name":
                            source_name,
                        "language":
                            language,
                        "source":
                            source,
                        "source_sha256":
                            source_sha256,
                        "preflight_report_sha256":
                            report_sha,
                        "diagnostics":
                            diagnostics,
                    }
                )
            )

            runtime = private_runtime_root()

            run_dir = runtime / (
                "gg-live-aid-repair-ui."
                + uuid.uuid4().hex
            )

            run_dir.mkdir(
                mode=0o700
            )

            request_path = (
                run_dir / "request.json"
            )

            payload = (
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")

            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | NOFOLLOW
            )

            fd = secure_open(
                request_path,
                flags,
                0o600,
            )

            try:
                with os.fdopen(
                    fd,
                    "wb",
                    closefd=False,
                ) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(
                        handle.fileno()
                    )
            finally:
                os.close(fd)

            process = QProcess(self)

            process.setProgram(
                executable_path("python3")
            )

            process.setArguments(
                [
                    "-B",
                    str(
                        REPAIR_MODEL_RUNNER_PATH
                    ),
                    str(request_path),
                ]
            )

            process.setWorkingDirectory(
                str(PROJECT)
            )

            process.setProcessChannelMode(
                QProcess.ProcessChannelMode
                .SeparateChannels
            )

            self._repair_process = process
            self._repair_state = {
                "object_id":
                    object_id,
                "request_id":
                    request_id,
                "source_sha256":
                    source_sha256,
                "run_dir":
                    str(run_dir),
            }

            process.finished.connect(
                self._repair_finished
            )

            process.start()

            if not process.waitForStarted(
                1500
            ):
                self._repair_process = None
                self._repair_state = None

                shutil.rmtree(
                    run_dir,
                    ignore_errors=True,
                )

                process.deleteLater()

                raise RuntimeError(
                    "AI repair model runner did not start."
                )

        except Exception as exc:
            self.repairFailed.emit(
                object_id,
                type(exc).__name__
                + ":"
                + str(exc),
            )

    @Slot(str, str, str)
    def applyRepair(
        self,
        proposal_id: str,
        object_id: str,
        current_source: str,
    ) -> None:
        try:
            proposal = (
                self._repair_proposals.get(
                    proposal_id
                )
            )

            if proposal is None:
                raise RuntimeError(
                    "Repair proposal is unavailable or consumed."
                )

            if (
                proposal.get("object_id")
                != object_id
            ):
                raise RuntimeError(
                    "Repair proposal object binding mismatch."
                )

            current_sha = hashlib.sha256(
                current_source.encode("utf-8")
            ).hexdigest()

            if (
                proposal.get("source_sha256")
                != current_sha
            ):
                raise RuntimeError(
                    "Repair proposal is stale for current buffer."
                )

            candidate = proposal.get(
                "candidate_source"
            )

            candidate_sha = proposal.get(
                "candidate_sha256"
            )

            if not isinstance(
                candidate,
                str,
            ):
                raise RuntimeError(
                    "Repair candidate is invalid."
                )

            if (
                hashlib.sha256(
                    candidate.encode("utf-8")
                ).hexdigest()
                != candidate_sha
            ):
                raise RuntimeError(
                    "Repair candidate SHA binding mismatch."
                )

            self._repair_proposals.pop(
                proposal_id,
                None,
            )

        except Exception as exc:
            self.repairFailed.emit(
                object_id,
                type(exc).__name__
                + ":"
                + str(exc),
            )
            return

        self.repairApplied.emit(
            object_id,
            proposal_id,
            candidate,
        )

    def _consume_post_draft_stdout(
        self,
        *,
        final: bool,
    ) -> None:
        process = self._post_draft_process
        state = self._post_draft_state

        if process is None or state is None:
            return

        chunk = bytes(
            process.readAllStandardOutput()
        )

        data = (
            self._post_draft_stdout_buffer
            + chunk
        )

        parts = data.split(b"\n")

        if final:
            complete = parts
            self._post_draft_stdout_buffer = b""
        else:
            complete = parts[:-1]
            self._post_draft_stdout_buffer = parts[-1]

        request_id = str(
            state["request_id"]
        )

        object_id = str(
            state["object_id"]
        )

        source_sha256 = str(
            state["source_sha256"]
        )

        for raw in complete:
            raw = raw.strip()

            if not raw:
                continue

            try:
                value = json.loads(
                    raw.decode(
                        "utf-8",
                        "strict",
                    )
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise RuntimeError(
                    "Post-draft runner emitted invalid JSON."
                ) from exc

            if not isinstance(
                value,
                dict,
            ):
                raise RuntimeError(
                    "Post-draft runner response is not an object."
                )

            kind = value.get(
                "kind"
            )

            if kind == "event":
                validated = (
                    post_draft_qml_process_runner
                    .validate_event(
                        value,
                        expected_request_id=
                            request_id,
                        expected_object_id=
                            object_id,
                        expected_initial_source_sha256=
                            source_sha256,
                    )
                )

                event = validated.get(
                    "event"
                )

                if not isinstance(
                    event,
                    dict,
                ):
                    raise RuntimeError(
                        "Post-draft event payload is invalid."
                    )

                events = state.get(
                    "events"
                )

                if not isinstance(
                    events,
                    list,
                ):
                    raise RuntimeError(
                        "Post-draft event transcript is unavailable."
                    )

                events.append(
                    dict(event)
                )

                payload = json.dumps(
                    event,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )

                self.postDraftEvent.emit(
                    object_id,
                    payload,
                )

                continue

            if kind == "result":
                if (
                    state.get("result")
                    is not None
                ):
                    raise RuntimeError(
                        "Post-draft runner emitted multiple results."
                    )

                validated = (
                    post_draft_qml_process_runner
                    .validate_response(
                        value,
                        expected_request_id=
                            request_id,
                        expected_object_id=
                            object_id,
                        expected_initial_source_sha256=
                            source_sha256,
                    )
                )

                state["result"] = (
                    validated
                )

                continue

            raise RuntimeError(
                "Post-draft runner emitted unknown envelope."
            )

    @Slot()
    def _post_draft_ready_read(
        self,
    ) -> None:
        state = self._post_draft_state

        if state is None:
            return

        try:
            self._consume_post_draft_stdout(
                final=False
            )

        except Exception as exc:
            if not state.get(
                "protocol_error"
            ):
                state[
                    "protocol_error"
                ] = (
                    type(exc).__name__
                    + ":"
                    + str(exc)
                )

    @Slot(int, QProcess.ExitStatus)
    def _persist_post_draft_evidence(
        self,
        *,
        state: dict[str, object],
        result: dict[str, object] | None,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
        stderr: str,
        protocol_error: str,
    ) -> tuple[str, str]:
        runtime = private_runtime_root().resolve(
            strict=True
        )

        run_dir = Path(
            str(
                state["run_dir"]
            )
        ).resolve(
            strict=True
        )

        if run_dir.parent != runtime:
            raise RuntimeError(
                "Post-draft scratch directory escaped runtime root."
            )

        request_id = str(
            state["request_id"]
        )

        prefix = "post-draft-"

        if not request_id.startswith(
            prefix
        ):
            raise RuntimeError(
                "Post-draft evidence request id is invalid."
            )

        suffix = request_id.removeprefix(
            prefix
        )

        if (
            len(suffix) != 32
            or any(
                character
                not in "0123456789abcdef"
                for character in suffix
            )
        ):
            raise RuntimeError(
                "Post-draft evidence request suffix is invalid."
            )

        events = state.get(
            "events"
        )

        if not isinstance(
            events,
            list,
        ):
            raise RuntimeError(
                "Post-draft evidence transcript is invalid."
            )

        evidence_dir = runtime / (
            "gg-live-aid-post-draft-evidence."
            + suffix
        )

        if (
            evidence_dir.exists()
            or evidence_dir.is_symlink()
        ):
            raise RuntimeError(
                "Post-draft evidence path already exists."
            )

        evidence_dir.mkdir(
            mode=0o700
        )

        normal_exit = (
            exit_status
            == QProcess.ExitStatus.NormalExit
        )

        evidence_result = None

        if result is not None:
            evidence_result = dict(
                result
            )

            evidence_result.pop(
                "source",
                None,
            )

        record = {
            "schema":
                "gg.workbench.post-draft-evidence.v2",
            "request_id":
                request_id,
            "object_id":
                str(
                    state["object_id"]
                ),
            "initial_source_sha256":
                str(
                    state["source_sha256"]
                ),
            "events":
                events,
            "result":
                evidence_result,
            "raw_source_persisted":
                False,
            "process": {
                "exit_code":
                    int(exit_code),
                "exit_status":
                    (
                        "NORMAL"
                        if normal_exit
                        else "CRASH"
                    ),
                "stderr":
                    stderr,
                "protocol_error":
                    protocol_error,
            },
            "scratch_policy":
                "REMOVE_AFTER_EVIDENCE_PROMOTION",
            "persistent_source_write":
                False,
            "execution_authority":
                "NONE",
            "network_authority":
                "NONE",
        }

        payload = (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode(
            "utf-8"
        )

        evidence_path = (
            evidence_dir
            / "evidence.json"
        )

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | NOFOLLOW
        )

        try:
            fd = secure_open(
                evidence_path,
                flags,
                0o600,
            )

            with os.fdopen(
                fd,
                "wb",
            ) as handle:
                handle.write(
                    payload
                )
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

        except Exception:
            shutil.rmtree(
                evidence_dir,
                ignore_errors=True,
            )
            raise

        return (
            str(
                evidence_path
            ),
            hashlib.sha256(
                payload
            ).hexdigest(),
        )

    def _post_draft_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._post_draft_process
        state = self._post_draft_state

        if process is None or state is None:
            return

        try:
            self._consume_post_draft_stdout(
                final=True
            )

        except Exception as exc:
            if not state.get(
                "protocol_error"
            ):
                state[
                    "protocol_error"
                ] = (
                    type(exc).__name__
                    + ":"
                    + str(exc)
                )

        stderr = bytes(
            process.readAllStandardError()
        ).decode(
            "utf-8",
            "replace",
        ).strip()

        object_id = str(
            state["object_id"]
        )

        run_dir = Path(
            str(
                state["run_dir"]
            )
        )

        protocol_error = str(
            state.get(
                "protocol_error",
                "",
            )
        )

        result = state.get(
            "result"
        )

        evidence_path = ""
        evidence_sha256 = ""

        try:
            (
                evidence_path,
                evidence_sha256,
            ) = self._persist_post_draft_evidence(
                state=state,
                result=(
                    result
                    if isinstance(
                        result,
                        dict,
                    )
                    else None
                ),
                exit_code=exit_code,
                exit_status=exit_status,
                stderr=stderr,
                protocol_error=protocol_error,
            )

        except Exception as exc:
            if not protocol_error:
                protocol_error = (
                    "POST_DRAFT_EVIDENCE:"
                    + type(exc).__name__
                    + ":"
                    + str(exc)
                )

        self._post_draft_process = None
        self._post_draft_state = None
        self._post_draft_stdout_buffer = b""

        process.deleteLater()

        if evidence_path:
            shutil.rmtree(
                run_dir,
                ignore_errors=True,
            )

        if protocol_error:
            self.postDraftFailed.emit(
                object_id,
                protocol_error,
            )
            return

        if (
            exit_status
            != QProcess.ExitStatus.NormalExit
            or exit_code != 0
        ):
            self.postDraftFailed.emit(
                object_id,
                stderr
                or (
                    "Automatic post-draft "
                    "repair runner failed."
                ),
            )
            return

        if not isinstance(
            result,
            dict,
        ):
            self.postDraftFailed.emit(
                object_id,
                (
                    "Automatic post-draft "
                    "repair returned no result."
                ),
            )
            return

        result_with_evidence = dict(
            result
        )

        result_with_evidence[
            "workbench_evidence_path"
        ] = evidence_path

        result_with_evidence[
            "workbench_evidence_sha256"
        ] = evidence_sha256

        payload = json.dumps(
            result_with_evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        self.postDraftReady.emit(
            object_id,
            payload,
        )

    @Slot(str, str, str, str)
    def runPostDraftRepair(
        self,
        object_id: str,
        source_name: str,
        source: str,
        language: str,
    ) -> None:
        try:
            self._validate_authoring_request(
                object_id,
                source_name,
                source,
                language,
            )

            if language != "qml":
                raise RuntimeError(
                    "Automatic post-draft repair supports QML only."
                )

            if (
                self._post_draft_process
                is not None
                and self._post_draft_process.state()
                != QProcess.ProcessState.NotRunning
            ):
                raise RuntimeError(
                    "Automatic post-draft repair is already running."
                )

            if (
                self._preflight_process
                is not None
                and self._preflight_process.state()
                != QProcess.ProcessState.NotRunning
            ):
                raise RuntimeError(
                    "Manual QML preflight is already running."
                )

            if (
                self._repair_process
                is not None
                and self._repair_process.state()
                != QProcess.ProcessState.NotRunning
            ):
                raise RuntimeError(
                    "Manual AI repair is already running."
                )

            spec = WORKSPACE_CONTEXTS.get(
                object_id
            )

            if spec is None:
                raise RuntimeError(
                    "Workspace post-draft target is unavailable."
                )

            relative = Path(
                spec["relative_path"]
            )

            if (
                relative.name != source_name
                or relative.suffix.lower()
                != ".qml"
            ):
                raise RuntimeError(
                    "Workspace post-draft target binding mismatch."
                )

            request_id = (
                "post-draft-"
                + uuid.uuid4().hex
            )

            source_sha256 = hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest()

            request = (
                post_draft_qml_process_runner
                .validate_request(
                    {
                        "schema":
                            post_draft_qml_process_runner
                            .REQUEST_SCHEMA,
                        "request_id":
                            request_id,
                        "object_id":
                            object_id,
                        "source_name":
                            source_name,
                        "source_relative_path":
                            relative.as_posix(),
                        "language":
                            language,
                        "source":
                            source,
                        "source_sha256":
                            source_sha256,
                        "max_repair_attempts":
                            1,
                        "model_dispatch_budget":
                            1,
                        "persistent_write_authority":
                            "NONE",
                        "execution_authority":
                            "NONE",
                        "network_authority":
                            "NONE",
                    }
                )
            )

            runtime = private_runtime_root().resolve(
                strict=True
            )

            run_dir = runtime / (
                "gg-live-aid-post-draft-ui."
                + uuid.uuid4().hex
            )

            run_dir.mkdir(
                mode=0o700
            )

            request_path = (
                run_dir
                / "request.json"
            )

            payload = (
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode(
                "utf-8"
            )

            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | NOFOLLOW
            )

            fd = secure_open(
                request_path,
                flags,
                0o600,
            )

            try:
                with os.fdopen(
                    fd,
                    "wb",
                    closefd=False,
                ) as handle:
                    handle.write(
                        payload
                    )
                    handle.flush()
                    os.fsync(
                        handle.fileno()
                    )
            finally:
                os.close(
                    fd
                )

            process = QProcess(
                self
            )

            runner_path = Path(
                post_draft_qml_process_runner
                .__file__
            ).resolve(
                strict=True
            )

            process.setProgram(
                executable_path("python3")
            )

            process.setArguments(
                [
                    "-B",
                    str(
                        runner_path
                    ),
                    str(
                        request_path
                    ),
                ]
            )

            process.setWorkingDirectory(
                str(
                    PROJECT
                )
            )

            process.setProcessChannelMode(
                QProcess.ProcessChannelMode
                .SeparateChannels
            )

            self._post_draft_process = (
                process
            )

            self._post_draft_state = {
                "object_id":
                    object_id,
                "request_id":
                    request_id,
                "source_sha256":
                    source_sha256,
                "run_dir":
                    str(
                        run_dir
                    ),
                "result":
                    None,
                "protocol_error":
                    "",
                "events":
                    [],
            }

            self._post_draft_stdout_buffer = b""

            process.readyReadStandardOutput.connect(
                self._post_draft_ready_read
            )

            process.finished.connect(
                self._post_draft_finished
            )

            process.start()

            if not process.waitForStarted(
                1500
            ):
                self._post_draft_process = None
                self._post_draft_state = None
                self._post_draft_stdout_buffer = b""

                shutil.rmtree(
                    run_dir,
                    ignore_errors=True,
                )

                process.deleteLater()

                raise RuntimeError(
                    "Automatic post-draft repair runner did not start."
                )

        except Exception as exc:
            self.postDraftFailed.emit(
                object_id,
                type(exc).__name__
                + ":"
                + str(exc),
            )

    @Slot(str, str, str, str)
    def analyze(
        self,
        object_id: str,
        source_name: str,
        source: str,
        language: str,
    ) -> None:
        try:
            self._validate_authoring_request(
                object_id,
                source_name,
                source,
                language,
            )
        except Exception as exc:
            self.analysisFailed.emit(
                object_id,
                type(exc).__name__ + ":" + str(exc),
            )
            return

        QTimer.singleShot(
            0,
            lambda: self._run_analysis(
                object_id,
                source_name,
                source,
                language,
            ),
        )

def _build_workbench_machine_graph() -> machine_graph.MachineGraph:
    call_edges = (
        (
            "call-01",
            "context_resolver.validate_snapshot_json",
            "CHAT_BRIDGE",
            "CONTEXT_RESOLVER",
        ),
        (
            "call-02",
            "context_resolver.resolve_snapshot",
            "CHAT_BRIDGE",
            "CONTEXT_RESOLVER",
        ),
        (
            "call-03",
            "context_resolver.render_extension",
            "CHAT_BRIDGE",
            "CONTEXT_RESOLVER",
        ),
        (
            "call-04",
            "capability_registry.CapabilityRegistry.load",
            "CHAT_BRIDGE",
            "CAPABILITY_REGISTRY",
        ),
        (
            "call-05",
            "solver_router.SolverRouter",
            "CHAT_BRIDGE",
            "SOLVER_ROUTER",
        ),
        (
            "call-06",
            "solver_router.LaserFocusCache",
            "CHAT_BRIDGE",
            "LASER_FOCUS_CACHE",
        ),
        (
            "call-07",
            "self._intent_laser.bind",
            "CHAT_BRIDGE",
            "LASER_FOCUS_CACHE",
        ),
        (
            "call-08",
            "self._intent_laser.lookup",
            "CHAT_BRIDGE",
            "LASER_FOCUS_CACHE",
        ),
        (
            "call-09",
            "self._router.route",
            "LASER_FOCUS_CACHE",
            "SOLVER_ROUTER",
        ),
        (
            "call-10",
            "self._router.route_focus_key",
            "LASER_FOCUS_CACHE",
            "SOLVER_ROUTER",
        ),
        (
            "call-11",
            "self._registry.active_working_set",
            "SOLVER_ROUTER",
            "CAPABILITY_REGISTRY",
        ),
        (
            "call-12",
            "idekompass_decision_ingress.decide",
            "CHAT_BRIDGE",
            "IDEKOMPASS",
        ),
        (
            "call-13",
            "resident_state.WorkbenchResidentInformationState.bootstrap_workbench_sources",
            "CHAT_BRIDGE",
            "RESIDENT_INFORMATION",
        ),
        (
            "call-14",
            "control_contract.parse_control_command",
            "CHAT_BRIDGE",
            "CONTROL_PLANE_CONTRACT",
        ),
        (
            "call-15",
            "post_draft_qml_process_runner.validate_request",
            "LIVE_AID_QT_BRIDGE",
            "POST_DRAFT_PROCESS_RUNNER",
        ),
        (
            "call-16",
            "LiveAidService",
            "LIVE_AID_QT_BRIDGE",
            "LIVE_AID_SERVICE",
        ),
        (
            "call-17",
            "qml_preflight_runner.validate_request",
            "LIVE_AID_QT_BRIDGE",
            "QML_PREFLIGHT_RUNNER",
        ),
        (
            "call-18",
            "qml_preflight_runner.validate_response",
            "LIVE_AID_QT_BRIDGE",
            "QML_PREFLIGHT_RUNNER",
        ),
        (
            "call-19",
            "repair_model_runner.validate_request",
            "LIVE_AID_QT_BRIDGE",
            "REPAIR_MODEL_RUNNER",
        ),
        (
            "call-20",
            "repair_model_runner.validate_response",
            "LIVE_AID_QT_BRIDGE",
            "REPAIR_MODEL_RUNNER",
        ),
        (
            "call-21",
            "contract.validate_request",
            "CHAT_BRIDGE",
            "LOCAL_AI_CONTRACT",
        ),
        (
            "call-22",
            "contract.canonical_request_json",
            "CHAT_BRIDGE",
            "LOCAL_AI_CONTRACT",
        ),
        (
            "call-23",
            "contract.validate_response",
            "CHAT_BRIDGE",
            "LOCAL_AI_CONTRACT",
        ),
        (
            "call-24",
            "tool_contract.validate_request",
            "CHAT_BRIDGE",
            "SAFE_TOOL_CONTRACT",
        ),
        (
            "call-25",
            "tool_contract.canonical_request_json",
            "CHAT_BRIDGE",
            "SAFE_TOOL_CONTRACT",
        ),
        (
            "call-26",
            "tool_contract.validate_response",
            "CHAT_BRIDGE",
            "SAFE_TOOL_CONTRACT",
        ),
        (
            "call-27",
            "write_contract.validate_request",
            "CHAT_BRIDGE",
            "WRITE_CONTRACT",
        ),
        (
            "call-28",
            "write_contract.canonical_request_json",
            "CHAT_BRIDGE",
            "WRITE_CONTRACT",
        ),
        (
            "call-29",
            "write_contract.validate_response",
            "CHAT_BRIDGE",
            "WRITE_CONTRACT",
        ),
        (
            "call-30",
            "autonomy_contract.validate_grant",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTRACT",
        ),
        (
            "call-31",
            "autonomy_contract.grant_sha256",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTRACT",
        ),
        (
            "call-32",
            "autonomy_contract.validate_request",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTRACT",
        ),
        (
            "call-33",
            "autonomy_contract.canonical_json",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTRACT",
        ),
        (
            "call-34",
            "autonomy_contract.validate_result",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTRACT",
        ),
        (
            "call-35",
            "base.execute_synthetic",
            "LOCAL_AI_CHAT_RUNNER",
            "LOCAL_AI_MODEL_RUNNER",
        ),
        (
            "call-36",
            "candidate_runner.initialize",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-37",
            "candidate_runner.write_attempt",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-38",
            "candidate_runner.qml_gate",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-39",
            "candidate_runner.read_before",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-40",
            "candidate_runner.read_candidate",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-41",
            "candidate_runner.diff_text",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-42",
            "candidate_runner.repair_to_intended",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "call-43",
            "cognition.trace_action",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-44",
            "cognition.append_claim",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-45",
            "cognition.read_records",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-46",
            "cognition.make_and_revalidate_state",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-47",
            "cognition.make_claim_candidate",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-48",
            "cognition.make_binary_hypothesis_state",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-49",
            "cognition.append_prebuilt_candidate",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-50",
            "self._resident_information_state.ingest_verified_write_completion",
            "CHAT_BRIDGE",
            "RESIDENT_INFORMATION",
        ),
        (
            "call-51",
            "self._resident_information_state.ingest_verified_write_rollback",
            "CHAT_BRIDGE",
            "RESIDENT_INFORMATION",
        ),
        (
            "call-52",
            "ingest_verified_host_source_change",
            "RESIDENT_INFORMATION",
            "SOURCE_CHANGE_EVENT",
        ),
        (
            "call-53",
            "dag.apply_leaf_change",
            "SOURCE_CHANGE_EVENT",
            "RESIDENT_MERKLE_DAG",
        ),
        (
            "call-54",
            "focus_index.apply_change",
            "RESIDENT_MERKLE_DAG",
            "INCREMENTAL_FOCUS_INDEX",
        ),
        (
            "call-55",
            "self._cache.discard",
            "INCREMENTAL_FOCUS_INDEX",
            "COMPILED_FOCUS_CACHE",
        ),
        (
            "call-56",
            "executor_module.PostDraftQmlExecutor",
            "POST_DRAFT_PROCESS_RUNNER",
            "POST_DRAFT_QML_EXECUTOR",
        ),
        (
            "call-57",
            "executor.run_complete_draft",
            "POST_DRAFT_PROCESS_RUNNER",
            "POST_DRAFT_QML_EXECUTOR",
        ),
        (
            "call-58",
            "post_draft_qml_driver.PostDraftQmlDriver",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-59",
            "self.driver.snapshot",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-60",
            "self.driver.snapshot",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-61",
            "self.driver.accept_external_fault",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-62",
            "self.driver.accept_preflight_response",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-63",
            "self.driver.accept_repair_response",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-64",
            "self.driver.snapshot",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-65",
            "self.driver.update_draft",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-66",
            "self.driver.mark_draft_complete",
            "POST_DRAFT_QML_EXECUTOR",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "call-67",
            "post_draft_coordinator.PostDraftCoordinator",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-68",
            "self._coordinator.snapshot",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-69",
            "self._coordinator.update_draft",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-70",
            "self._coordinator.mark_draft_complete",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-71",
            "self._coordinator.accept_validation",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-72",
            "self._coordinator.promote_ready",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-73",
            "self._coordinator.accept_validation",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-74",
            "self._coordinator.accept_repair_candidate",
            "POST_DRAFT_QML_DRIVER",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "call-75",
            "post_draft_qml_process_runner.validate_event",
            "LIVE_AID_QT_BRIDGE",
            "POST_DRAFT_PROCESS_RUNNER",
        ),
        (
            "call-76",
            "post_draft_qml_process_runner.validate_response",
            "LIVE_AID_QT_BRIDGE",
            "POST_DRAFT_PROCESS_RUNNER",
        ),
        (
            "call-77",
            "cognitive.load_stack",
            "IDEKOMPASS",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-78",
            "cognitive.claim_ref",
            "IDEKOMPASS",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-79",
            "cognitive.claim_ref",
            "IDEKOMPASS",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-80",
            "cognitive.make_and_revalidate_state",
            "IDEKOMPASS",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "call-81",
            "orchestrator_ingress.prepare_or_block",
            "IDEKOMPASS",
            "ORCHESTRATOR_INGRESS",
        ),
        (
            "call-82",
            "orchestrator_policy_adapter.validate_prepared_task",
            "IDEKOMPASS",
            "ORCHESTRATOR_POLICY_ADAPTER",
        ),
        (
            "call-83",
            "orchestrator_handoff_adapter.validate_policy_handoff",
            "IDEKOMPASS",
            "ORCHESTRATOR_HANDOFF_ADAPTER",
        ),
        (
            "call-84",
            "orchestrator_mandate_adapter.prepare_approval_request",
            "IDEKOMPASS",
            "ORCHESTRATOR_MANDATE_ADAPTER",
        ),
        (
            "call-85",
            "orchestrator_mandate_evaluation_adapter.evaluate_not_required",
            "CHAT_BRIDGE",
            "ORCHESTRATOR_MANDATE_EVALUATION_ADAPTER",
        ),
        (
            "call-86",
            "self._intent_capability_registry.get",
            "CHAT_BRIDGE",
            "CAPABILITY_REGISTRY",
        ),
        (
            "call-87",
            "action_intent_contract.make_action_proposal",
            "CHAT_BRIDGE",
            "ACTION_INTENT_CONTRACT",
        ),
        (
            "call-88",
            "orchestrator_mandate_evaluation_adapter.evaluate_explicit_approval",
            "CHAT_BRIDGE",
            "ORCHESTRATOR_MANDATE_EVALUATION_ADAPTER",
        ),
        (
            "call-89",
            "action_execution_eligibility.evaluate_execution_eligibility",
            "CHAT_BRIDGE",
            "ACTION_EXECUTION_ELIGIBILITY",
        ),
        (
            "call-90",
            "action_effect_observer.observe_safe_tool_read_effect",
            "CHAT_BRIDGE",
            "ACTION_EFFECT_OBSERVER",
        ),
        (
            "call-91",
            "action_effect_recovery.classify_action_effect_recovery",
            "CHAT_BRIDGE",
            "ACTION_EFFECT_RECOVERY",
        ),
        (
            "call-92",
            "action_done_when.evaluate_action_done_when",
            "CHAT_BRIDGE",
            "ACTION_DONE_WHEN",
        ),
        (
            "call-93",
            "semantic_closure.evaluate_semantic_closure",
            "ACTION_DONE_WHEN",
            "SEMANTIC_CLOSURE",
        ),
        (
            "call-94",
            "action_task_continuity.capture_action_task",
            "CHAT_BRIDGE",
            "ACTION_TASK_CONTINUITY",
        ),
        (
            "call-95",
            "action_task_continuity.record_action_approval",
            "CHAT_BRIDGE",
            "ACTION_TASK_CONTINUITY",
        ),
        (
            "call-96",
            "action_task_continuity.record_action_dispatch",
            "CHAT_BRIDGE",
            "ACTION_TASK_CONTINUITY",
        ),
        (
            "call-97",
            "action_task_continuity.record_action_completion",
            "CHAT_BRIDGE",
            "ACTION_TASK_CONTINUITY",
        ),
        ('call-98', 'participant_task_receiver.prepare_participant_execution', 'CHAT_BRIDGE', 'PARTICIPANT_TASK_RECEIVER'),
        ('call-99', 'participant_task_receiver.finalize_participant_response', 'CHAT_BRIDGE', 'PARTICIPANT_TASK_RECEIVER'),
        ('call-100', 'initiative_proposal.derive_from_decision', 'IDEKOMPASS', 'INITIATIVE_PROPOSAL'),
        ('call-101', 'learning_memory.build_episodic_experience', 'ACTION_DONE_WHEN', 'LEARNING_MEMORY_PROMOTION'),
        (
            "call-102",
            "live_mandate_store.put_pending",
            "CHAT_BRIDGE",
            "LIVE_MANDATE_STORE",
        ),
        (
            "call-103",
            "live_mandate_store.approve",
            "CHAT_BRIDGE",
            "LIVE_MANDATE_STORE",
        ),
        (
            "call-104",
            "live_mandate_store.reject",
            "CHAT_BRIDGE",
            "LIVE_MANDATE_STORE",
        ),
        (
            "call-105",
            "task_scoped_action_grant.issue_from_approved_record",
            "CHAT_BRIDGE",
            "TASK_SCOPED_ACTION_GRANT",
        ),
    )

    process_edges = (
        (
            "proc-01-request",
            "qprocess:control-plane:apply-selfdev:request",
            "CHAT_BRIDGE",
            "CONTROL_PLANE_RUNNER",
            "gg.qprocess-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:--apply-selfdev",
        ),
        (
            "proc-01-result",
            "qprocess:control-plane:apply-selfdev:result",
            "CONTROL_PLANE_RUNNER",
            "CHAT_BRIDGE",
            "gg.qprocess-result.v1",
            "ACTION_RESULT",
            "qprocess-finished:ChatBridge._control_apply_finished",
        ),
        (
            "proc-02-request",
            "qprocess:local-ai:chat:request",
            "CHAT_BRIDGE",
            "LOCAL_AI_CHAT_RUNNER",
            "gg.qprocess-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:--execute-chat",
        ),
        (
            "proc-02-result",
            "qprocess:local-ai:chat:result",
            "LOCAL_AI_CHAT_RUNNER",
            "CHAT_BRIDGE",
            "gg.qprocess-result.v1",
            "ACTION_RESULT",
            "qprocess-finished:ChatBridge._finished",
        ),
        (
            "proc-03-request",
            "qprocess:write:execute:request",
            "CHAT_BRIDGE",
            "WRITE_RUNNER",
            "gg.qprocess-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:--execute-write",
        ),
        (
            "proc-03-result",
            "qprocess:write:execute:result",
            "WRITE_RUNNER",
            "CHAT_BRIDGE",
            "gg.qprocess-result.v1",
            "ACTION_RESULT",
            "qprocess-finished:ChatBridge._write_finished",
        ),
        (
            "proc-04-request",
            "qprocess:safe-tool:execute:request",
            "CHAT_BRIDGE",
            "SAFE_TOOL_RUNNER",
            "gg.qprocess-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:--execute-tool",
        ),
        (
            "proc-04-result",
            "qprocess:safe-tool:execute:result",
            "SAFE_TOOL_RUNNER",
            "CHAT_BRIDGE",
            "gg.qprocess-result.v1",
            "ACTION_RESULT",
            "qprocess-finished:ChatBridge._tool_finished",
        ),
        (
            "proc-05-request",
            "qprocess:autonomy:execute:request",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTROLLER",
            "gg.qprocess-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:--execute",
        ),
        (
            "proc-05-result",
            "qprocess:autonomy:execute:result",
            "AUTONOMY_CONTROLLER",
            "CHAT_BRIDGE",
            "gg.qprocess-result.v1",
            "ACTION_RESULT",
            "qprocess-finished:ChatBridge._autonomy_finished",
        ),
        (
            "proc-06-request",
            "qprocess:autonomy:verify-host:request",
            "CHAT_BRIDGE",
            "AUTONOMY_CONTROLLER",
            "gg.qprocess-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:--verify-host",
        ),
        (
            "proc-06-result",
            "qprocess:autonomy:verify-host:result",
            "AUTONOMY_CONTROLLER",
            "CHAT_BRIDGE",
            "gg.qprocess-result.v1",
            "ACTION_RESULT",
            "qprocess-finished:ChatBridge._autonomy_verify_finished",
        ),
        (
            "proc-07-request",
            "subprocess:autonomy:model:execute:request",
            "AUTONOMY_CONTROLLER",
            "AUTONOMY_MODEL_RUNNER",
            "gg.subprocess-request.v1",
            "ACTION_REQUEST",
            "subprocess-run:--execute",
        ),
        (
            "proc-07-result",
            "subprocess:autonomy:model:execute:result",
            "AUTONOMY_MODEL_RUNNER",
            "AUTONOMY_CONTROLLER",
            "gg.subprocess-result.v1",
            "ACTION_RESULT",
            "subprocess-completed:_model_proposal",
        ),
        (
            "proc-08-request",
            "subprocess:autonomy:safe-tool-read:request",
            "AUTONOMY_CONTROLLER",
            "SAFE_TOOL_RUNNER",
            "gg.subprocess-request.v1",
            "ACTION_REQUEST",
            "subprocess-run:--execute-tool",
        ),
        (
            "proc-08-result",
            "subprocess:autonomy:safe-tool-read:result",
            "SAFE_TOOL_RUNNER",
            "AUTONOMY_CONTROLLER",
            "gg.subprocess-result.v1",
            "ACTION_RESULT",
            "subprocess-completed:_safe_tool_read",
        ),
        (
            "proc-09-request",
            "subprocess:autonomy:write-proposal:request",
            "AUTONOMY_CONTROLLER",
            "WRITE_RUNNER",
            "gg.subprocess-request.v1",
            "ACTION_REQUEST",
            "subprocess-run:--execute-write",
        ),
        (
            "proc-09-result",
            "subprocess:autonomy:write-proposal:result",
            "WRITE_RUNNER",
            "AUTONOMY_CONTROLLER",
            "gg.subprocess-result.v1",
            "ACTION_RESULT",
            "subprocess-completed:_write_host_proposal",
        ),
        (
            "proc-10-request",
            "qprocess:live-aid:preflight:request",
            "LIVE_AID_QT_BRIDGE",
            "QML_PREFLIGHT_RUNNER",
            "gg.live-aid.qml-preflight-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:LiveAidQtBridge.preflight",
        ),
        (
            "proc-10-result",
            "qprocess:live-aid:preflight:result",
            "QML_PREFLIGHT_RUNNER",
            "LIVE_AID_QT_BRIDGE",
            "gg.live-aid.qml-preflight-response.v1",
            "ACTION_RESULT",
            "qprocess-finished:LiveAidQtBridge._preflight_finished",
        ),
        (
            "proc-11-request",
            "qprocess:live-aid:repair:request",
            "LIVE_AID_QT_BRIDGE",
            "REPAIR_MODEL_RUNNER",
            "gg.live-aid.repair-model-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:LiveAidQtBridge.requestRepair",
        ),
        (
            "proc-11-result",
            "qprocess:live-aid:repair:result",
            "REPAIR_MODEL_RUNNER",
            "LIVE_AID_QT_BRIDGE",
            "gg.live-aid.repair-model-response.v1",
            "ACTION_RESULT",
            "qprocess-finished:LiveAidQtBridge._repair_finished",
        ),
        (
            "proc-12-request",
            "qprocess:live-aid:post-draft:request",
            "LIVE_AID_QT_BRIDGE",
            "POST_DRAFT_PROCESS_RUNNER",
            "gg.live-aid.post-draft-process-request.v1",
            "ACTION_REQUEST",
            "qprocess-launch:LiveAidQtBridge.runPostDraftRepair",
        ),
        (
            "proc-12-event",
            "qprocess:live-aid:post-draft:event",
            "POST_DRAFT_PROCESS_RUNNER",
            "LIVE_AID_QT_BRIDGE",
            "gg.live-aid.post-draft-process-event.v1",
            "EVENT",
            "qprocess-ready-read:LiveAidQtBridge._post_draft_ready_read",
        ),
        (
            "proc-12-result",
            "qprocess:live-aid:post-draft:result",
            "POST_DRAFT_PROCESS_RUNNER",
            "LIVE_AID_QT_BRIDGE",
            "gg.live-aid.post-draft-process-response.v1",
            "ACTION_RESULT",
            "qprocess-finished:LiveAidQtBridge._post_draft_finished",
        ),
        (
            "proc-13-request",
            "subprocess:live-aid:post-draft-preflight:request",
            "POST_DRAFT_QML_EXECUTOR",
            "QML_PREFLIGHT_RUNNER",
            "gg.live-aid.qml-preflight-request.v1",
            "ACTION_REQUEST",
            "subprocess-run:PostDraftQmlExecutor._invoke_runner:preflight",
        ),
        (
            "proc-13-result",
            "subprocess:live-aid:post-draft-preflight:result",
            "QML_PREFLIGHT_RUNNER",
            "POST_DRAFT_QML_EXECUTOR",
            "gg.live-aid.qml-preflight-response.v1",
            "ACTION_RESULT",
            "subprocess-completed:PostDraftQmlExecutor._execute_preflight",
        ),
        (
            "proc-14-request",
            "subprocess:live-aid:post-draft-repair:request",
            "POST_DRAFT_QML_EXECUTOR",
            "REPAIR_MODEL_RUNNER",
            "gg.live-aid.repair-model-request.v1",
            "ACTION_REQUEST",
            "subprocess-run:PostDraftQmlExecutor._invoke_runner:repair",
        ),
        (
            "proc-14-result",
            "subprocess:live-aid:post-draft-repair:result",
            "REPAIR_MODEL_RUNNER",
            "POST_DRAFT_QML_EXECUTOR",
            "gg.live-aid.repair-model-response.v1",
            "ACTION_RESULT",
            "subprocess-completed:PostDraftQmlExecutor._execute_repair",
        ),
    )

    runtime_operations = (
        (
            "runtime-01",
            "local-ai:image-inspect",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-02",
            "local-ai:container-inventory",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-03",
            "local-ai:volume-inventory",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-04",
            "local-ai:container-exists",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-05",
            "local-ai:help-run",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-06",
            "local-ai:inference-run",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-07",
            "local-ai:container-remove",
            "LOCAL_AI_MODEL_RUNNER",
            "PODMAN_LOCAL_AI_RUNTIME",
        ),
        (
            "runtime-08",
            "safe-tool:image-inspect",
            "SAFE_TOOL_RUNNER",
            "PODMAN_SAFE_TOOL_RUNTIME",
        ),
        (
            "runtime-09",
            "safe-tool:container-create",
            "SAFE_TOOL_RUNNER",
            "PODMAN_SAFE_TOOL_RUNTIME",
        ),
        (
            "runtime-10",
            "safe-tool:container-inspect",
            "SAFE_TOOL_RUNNER",
            "PODMAN_SAFE_TOOL_RUNTIME",
        ),
        (
            "runtime-11",
            "safe-tool:container-start-attach",
            "SAFE_TOOL_RUNNER",
            "PODMAN_SAFE_TOOL_RUNTIME",
        ),
        (
            "runtime-12",
            "safe-tool:container-remove",
            "SAFE_TOOL_RUNNER",
            "PODMAN_SAFE_TOOL_RUNTIME",
        ),
        (
            "runtime-13",
            "write-qml:image-inspect",
            "WRITE_RUNNER",
            "PODMAN_QML_GATE_RUNTIME",
        ),
        (
            "runtime-14",
            "write-qml:gate-run",
            "WRITE_RUNNER",
            "PODMAN_QML_GATE_RUNTIME",
        ),
    )

    effect_operations = (
        (
            "effect-01",
            "write:approve-apply",
            "WRITE_RUNNER",
            "WRITE_EFFECT_BOUNDARY",
            "atomic-replace:approve-apply",
            "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        ),
        (
            "effect-02",
            "write:approve-automatic-rollback",
            "WRITE_RUNNER",
            "WRITE_EFFECT_BOUNDARY",
            "atomic-replace:approve-automatic-rollback",
            "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        ),
        (
            "effect-03",
            "write:rollback-restore",
            "WRITE_RUNNER",
            "WRITE_EFFECT_BOUNDARY",
            "atomic-replace:rollback-restore",
            "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        ),
    )

    node_contracts = (
        (
            "CHAT_BRIDGE",
            "main.ChatBridge",
            "CHAT_BRIDGE",
        ),
        (
            "CONTEXT_RESOLVER",
            "backend.context_resolver",
            "STATELESS",
        ),
        (
            "CAPABILITY_REGISTRY",
            "backend.capability_registry.CapabilityRegistry",
            "CAPABILITY_REGISTRY",
        ),
        (
            "SOLVER_ROUTER",
            "backend.solver_router.SolverRouter",
            "SOLVER_ROUTER",
        ),
        (
            "LASER_FOCUS_CACHE",
            "backend.solver_router.LaserFocusCache",
            "LASER_FOCUS_CACHE",
        ),
        (
            "IDEKOMPASS",
            "backend.idekompass_decision_ingress",
            "STATELESS",
        ),
        (
            "ORCHESTRATOR_INGRESS",
            "backend.orchestrator_ingress",
            "STATELESS",
        ),
        (
            "ORCHESTRATOR_POLICY_ADAPTER",
            "backend.orchestrator_policy_adapter",
            "STATELESS",
        ),
        (
            "ORCHESTRATOR_HANDOFF_ADAPTER",
            "backend.orchestrator_handoff_adapter",
            "STATELESS",
        ),
        (
            "ORCHESTRATOR_MANDATE_ADAPTER",
            "backend.orchestrator_mandate_adapter",
            "STATELESS",
        ),
        (
            "ORCHESTRATOR_MANDATE_EVALUATION_ADAPTER",
            "backend.orchestrator_mandate_evaluation_adapter",
            "STATELESS",
        ),
        (
            "RESIDENT_INFORMATION",
            "backend.resident_information_state.WorkbenchResidentInformationState",
            "RESIDENT_INFORMATION",
        ),
        (
            "CONTROL_PLANE_CONTRACT",
            "backend.control_plane_contract",
            "STATELESS",
        ),
        (
            "LIVE_AID_QT_BRIDGE",
            "main.LiveAidQtBridge",
            "LIVE_AID_QT_BRIDGE",
        ),
        (
            "POST_DRAFT_PROCESS_RUNNER",
            "backend.live_aid.post_draft_qml_process_runner",
            "STATELESS",
        ),
        (
            "LIVE_AID_SERVICE",
            "backend.live_aid.bridge.LiveAidService",
            "LIVE_AID_SERVICE",
        ),
        (
            "QML_PREFLIGHT_RUNNER",
            "backend.live_aid.qml_preflight_runner",
            "STATELESS",
        ),
        (
            "REPAIR_MODEL_RUNNER",
            "backend.live_aid.repair_model_runner",
            "STATELESS",
        ),
        (
            "LOCAL_AI_CONTRACT",
            "backend.local_ai_contract",
            "STATELESS",
        ),
        (
            "SAFE_TOOL_CONTRACT",
            "backend.safe_tool_contract",
            "STATELESS",
        ),
        (
            "WRITE_CONTRACT",
            "backend.write_contract",
            "STATELESS",
        ),
        (
            "AUTONOMY_CONTRACT",
            "backend.autonomy_contract",
            "STATELESS",
        ),
        (
            "CONTROL_PLANE_RUNNER",
            "backend.control_plane_runner",
            "PROCESS_RUNTIME",
        ),
        (
            "LOCAL_AI_CHAT_RUNNER",
            "backend.local_ai_chat_runner",
            "PROCESS_RUNTIME",
        ),
        (
            "WRITE_RUNNER",
            "backend.write_runner",
            "PROCESS_RUNTIME",
        ),
        (
            "SAFE_TOOL_RUNNER",
            "backend.safe_tool_runner",
            "PROCESS_RUNTIME",
        ),
        (
            "AUTONOMY_CONTROLLER",
            "backend.autonomy_controller",
            "PROCESS_RUNTIME",
        ),
        (
            "LOCAL_AI_MODEL_RUNNER",
            "backend.local_ai_model_runner",
            "LOCAL_AI_MODEL_RUNNER",
        ),
        (
            "AUTONOMY_CANDIDATE_RUNNER",
            "backend.autonomy_candidate_runner",
            "AUTONOMY_CANDIDATE_RUNNER",
        ),
        (
            "AUTONOMY_COGNITIVE_ADAPTER",
            "backend.autonomy_cognitive_adapter",
            "AUTONOMY_COGNITIVE_ADAPTER",
        ),
        (
            "AUTONOMY_MODEL_RUNNER",
            "backend.autonomy_model_runner",
            "PROCESS_RUNTIME",
        ),
        (
            "PODMAN_LOCAL_AI_RUNTIME",
            "podman.local-ai-model-runtime",
            "PODMAN_RUNTIME",
        ),
        (
            "PODMAN_SAFE_TOOL_RUNTIME",
            "podman.safe-tool-sandbox-runtime",
            "PODMAN_RUNTIME",
        ),
        (
            "PODMAN_QML_GATE_RUNTIME",
            "podman.qml-gate-runtime",
            "PODMAN_RUNTIME",
        ),
        (
            "WRITE_EFFECT_BOUNDARY",
            "backend.write_runner._atomic_replace",
            "WRITE_EFFECT_BOUNDARY",
        ),
        (
            "SOURCE_CHANGE_EVENT",
            "backend.source_change_event.ingest_verified_host_source_change",
            "STATELESS",
        ),
        (
            "RESIDENT_MERKLE_DAG",
            "backend.merkle_propagation.ResidentMerklePropagationDAG",
            "RESIDENT_INFORMATION",
        ),
        (
            "INCREMENTAL_FOCUS_INDEX",
            "backend.incremental_focus.IncrementalFocusIndex",
            "RESIDENT_INFORMATION",
        ),
        (
            "COMPILED_FOCUS_CACHE",
            "backend.compiled_focus.CompiledFocusCache",
            "INCREMENTAL_FOCUS_INDEX",
        ),
        (
            "POST_DRAFT_QML_EXECUTOR",
            "backend.live_aid.post_draft_qml_executor.PostDraftQmlExecutor",
            "POST_DRAFT_QML_EXECUTOR",
        ),
        (
            "POST_DRAFT_QML_DRIVER",
            "backend.live_aid.post_draft_qml_driver.PostDraftQmlDriver",
            "POST_DRAFT_QML_DRIVER",
        ),
        (
            "POST_DRAFT_COORDINATOR",
            "backend.live_aid.post_draft_coordinator.PostDraftCoordinator",
            "POST_DRAFT_COORDINATOR",
        ),
        (
            "ACTION_INTENT_CONTRACT",
            "backend.action_intent_contract",
            "STATELESS",
        ),
        (
            "ACTION_EXECUTION_ELIGIBILITY",
            "backend.action_execution_eligibility",
            "STATELESS",
        ),
        (
            "ACTION_EFFECT_OBSERVER",
            "backend.action_effect_observer",
            "STATELESS",
        ),
        (
            "ACTION_EFFECT_RECOVERY",
            "backend.action_effect_recovery",
            "STATELESS",
        ),
        ('ACTION_DONE_WHEN', 'backend.action_done_when', 'STATELESS'),
        ('ACTION_TASK_CONTINUITY', 'backend.action_task_continuity', 'STATELESS'),
        ('PARTICIPANT_TASK_RECEIVER', 'backend.participant_task_receiver', 'STATELESS'),
        ('SEMANTIC_CLOSURE', 'backend.semantic_closure', 'STATELESS'),
        ('INITIATIVE_PROPOSAL', 'backend.initiative_proposal', 'STATELESS'),
        ('LEARNING_MEMORY_PROMOTION', 'backend.learning_memory_promotion', 'STATELESS'),
        ('LIVE_MANDATE_STORE', 'backend.live_mandate_store', 'LIVE_MANDATE_STORE'),
        ('TASK_SCOPED_ACTION_GRANT', 'backend.task_scoped_action_grant', 'STATELESS'),
    )

    ports_by_node: dict[str, list[machine_graph.PortSpec]] = {
        node_id: []
        for node_id, _implementation_id, _state_owner
        in node_contracts
    }

    edges: list[machine_graph.EdgeSpec] = []

    for call_id, call_name, from_node_id, to_node_id in call_edges:
        semantic_id = "python-call:" + call_name
        output_port_id = call_id + "-out"
        input_port_id = call_id + "-in"

        ports_by_node[from_node_id].append(
            machine_graph.PortSpec(
                port_id=output_port_id,
                direction=machine_graph.OUTPUT,
                schema_id="gg.python-call.v1",
                semantic_id=semantic_id,
                channel_class="EVENT",
                semantics="direct-runtime-call",
                authority_contract="NONE",
                max_connections=1,
            )
        )

        ports_by_node[to_node_id].append(
            machine_graph.PortSpec(
                port_id=input_port_id,
                direction=machine_graph.INPUT,
                schema_id="gg.python-call.v1",
                semantic_id=semantic_id,
                channel_class="EVENT",
                semantics="direct-runtime-call",
                authority_contract="NONE",
                max_connections=1,
            )
        )

        edges.append(
            machine_graph.EdgeSpec(
                edge_id=call_id,
                from_node_id=from_node_id,
                from_port_id=output_port_id,
                to_node_id=to_node_id,
                to_port_id=input_port_id,
            )
        )

    for (
        edge_id,
        semantic_id,
        from_node_id,
        to_node_id,
        schema_id,
        channel_class,
        semantics,
    ) in process_edges:
        output_port_id = edge_id + "-out"
        input_port_id = edge_id + "-in"

        ports_by_node[from_node_id].append(
            machine_graph.PortSpec(
                port_id=output_port_id,
                direction=machine_graph.OUTPUT,
                schema_id=schema_id,
                semantic_id=semantic_id,
                channel_class=channel_class,
                semantics=semantics,
                authority_contract="NONE",
                max_connections=1,
            )
        )

        ports_by_node[to_node_id].append(
            machine_graph.PortSpec(
                port_id=input_port_id,
                direction=machine_graph.INPUT,
                schema_id=schema_id,
                semantic_id=semantic_id,
                channel_class=channel_class,
                semantics=semantics,
                authority_contract="NONE",
                max_connections=1,
            )
        )

        edges.append(
            machine_graph.EdgeSpec(
                edge_id=edge_id,
                from_node_id=from_node_id,
                from_port_id=output_port_id,
                to_node_id=to_node_id,
                to_port_id=input_port_id,
            )
        )

    for (
        operation_id,
        operation_name,
        caller_node_id,
        runtime_node_id,
    ) in runtime_operations:
        operation_semantics = (
            "podman-operation:" + operation_name
        )

        for (
            phase,
            from_node_id,
            to_node_id,
            schema_id,
            channel_class,
        ) in (
            (
                "request",
                caller_node_id,
                runtime_node_id,
                "gg.podman-operation-request.v1",
                "ACTION_REQUEST",
            ),
            (
                "result",
                runtime_node_id,
                caller_node_id,
                "gg.podman-operation-result.v1",
                "ACTION_RESULT",
            ),
        ):
            edge_id = operation_id + "-" + phase
            semantic_id = (
                "podman:"
                + operation_name
                + ":"
                + phase
            )
            output_port_id = edge_id + "-out"
            input_port_id = edge_id + "-in"

            ports_by_node[from_node_id].append(
                machine_graph.PortSpec(
                    port_id=output_port_id,
                    direction=machine_graph.OUTPUT,
                    schema_id=schema_id,
                    semantic_id=semantic_id,
                    channel_class=channel_class,
                    semantics=operation_semantics,
                    authority_contract="NONE",
                    max_connections=1,
                )
            )

            ports_by_node[to_node_id].append(
                machine_graph.PortSpec(
                    port_id=input_port_id,
                    direction=machine_graph.INPUT,
                    schema_id=schema_id,
                    semantic_id=semantic_id,
                    channel_class=channel_class,
                    semantics=operation_semantics,
                    authority_contract="NONE",
                    max_connections=1,
                )
            )

            edges.append(
                machine_graph.EdgeSpec(
                    edge_id=edge_id,
                    from_node_id=from_node_id,
                    from_port_id=output_port_id,
                    to_node_id=to_node_id,
                    to_port_id=input_port_id,
                )
            )

    for (
        edge_id,
        operation_name,
        from_node_id,
        to_node_id,
        semantics,
        authority_contract,
    ) in effect_operations:
        semantic_id = "write-effect:" + operation_name
        output_port_id = edge_id + "-out"
        input_port_id = edge_id + "-in"

        ports_by_node[from_node_id].append(
            machine_graph.PortSpec(
                port_id=output_port_id,
                direction=machine_graph.OUTPUT,
                schema_id="gg.write-effect-request.v1",
                semantic_id=semantic_id,
                channel_class="ACTION_REQUEST",
                semantics=semantics,
                authority_contract=authority_contract,
                max_connections=1,
            )
        )

        ports_by_node[to_node_id].append(
            machine_graph.PortSpec(
                port_id=input_port_id,
                direction=machine_graph.INPUT,
                schema_id="gg.write-effect-request.v1",
                semantic_id=semantic_id,
                channel_class="ACTION_REQUEST",
                semantics=semantics,
                authority_contract=authority_contract,
                max_connections=1,
            )
        )

        edges.append(
            machine_graph.EdgeSpec(
                edge_id=edge_id,
                from_node_id=from_node_id,
                from_port_id=output_port_id,
                to_node_id=to_node_id,
                to_port_id=input_port_id,
            )
        )

    nodes = tuple(
        machine_graph.NodeSpec(
            node_id=node_id,
            implementation_id=implementation_id,
            contract_version=(
                "runtime-effect-v1"
                if node_id == "WRITE_EFFECT_BOUNDARY"
                else (
                    "runtime-podman-v1"
                    if node_id in {
                        "PODMAN_LOCAL_AI_RUNTIME",
                        "PODMAN_SAFE_TOOL_RUNTIME",
                        "PODMAN_QML_GATE_RUNTIME",
                    }
                    else (
                        "runtime-process-v1"
                        if node_id in {
                            "CONTROL_PLANE_RUNNER",
                            "LOCAL_AI_CHAT_RUNNER",
                            "WRITE_RUNNER",
                            "SAFE_TOOL_RUNNER",
                            "AUTONOMY_CONTROLLER",
                            "AUTONOMY_MODEL_RUNNER",
                        }
                        else "runtime-call-v1"
                    )
                )
            ),
            state_owner=state_owner,
            ports=tuple(ports_by_node[node_id]),
            authority_contract=(
                "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1"
                if node_id == "WRITE_EFFECT_BOUNDARY"
                else "NONE"
            ),
        )
        for node_id, implementation_id, state_owner
        in node_contracts
    )

    graph = machine_graph.MachineGraph(
        nodes=nodes,
        edges=tuple(edges),
    )
    graph.validate()
    return graph

def parse_mandate_command(text: str) -> dict[str, object] | None:
    value = text.strip()

    if not value.startswith("/"):
        return None

    command, separator, remainder = value.partition(" ")
    command = command.lower()
    argument = remainder.strip() if separator else ""

    if command not in ("/approve-mandate", "/reject-mandate"):
        return None

    parts = argument.split()
    expected_parts = 3 if command == "/approve-mandate" else 2

    if len(parts) != expected_parts:
        raise ValueError(
            "Usage: "
            + command
            + " mandate-<32hex> <approval_scope_revision_sha256>"
            + (" <approver_id>" if command == "/approve-mandate" else "")
        )

    pending_id = parts[0]
    scope_revision = parts[1]

    if (
        not pending_id.startswith("mandate-")
        or len(pending_id) != 40
        or any(char not in "0123456789abcdef" for char in pending_id[8:])
    ):
        raise ValueError("Pending mandate id invalid.")

    if (
        len(scope_revision) != 64
        or any(char not in "0123456789abcdef" for char in scope_revision)
    ):
        raise ValueError("Approval scope revision SHA-256 invalid.")

    parsed: dict[str, object] = {
        "action": "APPROVE" if command == "/approve-mandate" else "REJECT",
        "pending_id": pending_id,
        "approval_scope_revision": scope_revision,
    }

    if command == "/approve-mandate":
        approver_id = parts[2]
        allowed = (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz"
            "0123456789._:-"
        )
        if (
            not 1 <= len(approver_id) <= 128
            or any(char not in allowed for char in approver_id)
        ):
            raise ValueError("Approver id must match K7-K caller-label syntax.")
        parsed["approver_id"] = approver_id

    return parsed


def parse_chat_approval(text: str) -> str | None:
    """Parse a bare chat approval/rejection for one pending mandate."""
    value = " ".join(str(text or "").strip().casefold().split())
    if value in {"ja", "yes", "godkänn", "godkann", "approve", "ok"}:
        return "APPROVE"
    if value in {"nej", "no", "avvisa", "reject"}:
        return "REJECT"
    return None


_CHAT_RESUME_PHRASES = frozenset(
    {
        "prova igen",
        "försök igen",
        "forsok igen",
        "kör igen",
        "kor igen",
        "fortsätt",
        "fortsatt",
        "fortsätt nu",
        "fortsatt nu",
        "klar",
        "klart",
        "jag är klar",
        "jag ar klar",
        "inloggad",
        "login klar",
        "inloggningen klar",
        "2fa klar",
        "2fa klart",
        "retry",
        "try again",
        "continue",
    }
)


def parse_chat_resume_request(text: str) -> str | None:
    """Recognize a short human handoff/resume message.

    These words never create authority on their own.  They only resume the
    latest already approved chat task, or remind the user that an approval is
    still waiting.  This keeps phrases such as ``klar`` useful after visible
    login/2FA without turning an ambiguous sentence into a new task scope.
    """
    value = " ".join(str(text or "").strip().casefold().split())
    value = value.rstrip(".! ")
    return value if value in _CHAT_RESUME_PHRASES else None


_CHAT_ACTION_WORDS = (
    "publicera",
    "publicering",
    "deploy",
    "driftsätt",
    "driftsatta",
    "ändra",
    "ändras",
    "uppdatera",
    "uppdatering",
    "skriv",
    "skriva",
    "lägg till",
    "ta bort",
    "radera",
    "skapa",
    "kör",
    "genomför",
    "återställ",
    "återställa",
    "backup",
    "säkerhetskopiera",
    "verify",
    "verifiera",
    "login",
    "logga in",
    "gör",
    "do ",
    "change ",
    "update ",
    "publish ",
    "deploy ",
    "run ",
    "restore ",
)

_CHAT_TARGET_WORDS = (
    "webb",
    "webbändring",
    "webbplats",
    "sajt",
    "site",
    "wordpress",
    "wp-admin",
    "wp admin",
    "one.com",
    "goldgoblins",
    "produktion",
    "produktions",
    "live",
    "server",
    "sftp",
    "ssh",
    "nätverk",
    "network",
    "domän",
    "dns",
    "e-post",
    "email",
    "kunddata",
    "orderdata",
    "lösenord",
    "password",
    "credential",
    "behörighet",
    "mandat",
    "scope",
    "fil",
    "kod",
    "app",
    "desktop",
    "qml",
    "main.py",
)

_CHAT_EXTERNAL_TARGET_WORDS = (
    "webb",
    "webbändring",
    "webbplats",
    "sajt",
    "site",
    "wordpress",
    "wp-admin",
    "wp admin",
    "one.com",
    "goldgoblins.se",
    "produktion",
    "produktions",
    "live",
    "server",
    "sftp",
    "ssh",
    "nätverk",
    "network",
    "dns",
    "e-post",
    "email",
    "kunddata",
    "orderdata",
)


def parse_chat_action_request(text: str) -> dict[str, object] | None:
    """Recognize a concrete action request written in ordinary chat.

    This is deliberately a narrow ingress detector, not an authority grant.
    It creates a task-bound approval request for high-impact natural language
    so the user can approve it with ``ja`` or reject it with ``nej``.  A vague
    conversation such as "gör si" is left as ordinary chat until a target or
    effect is named.
    """
    normalized = " ".join(str(text or "").strip().casefold().split())
    if not normalized or len(normalized) > 4096:
        return None
    if normalized.endswith("?") or normalized.startswith(
        ("hur ", "vad ", "vilka ", "varför ", "how ", "what ", "why ")
    ):
        return None
    if not any(word in normalized for word in _CHAT_ACTION_WORDS):
        return None
    if not any(word in normalized for word in _CHAT_TARGET_WORDS):
        return None

    external = any(
        word in normalized for word in _CHAT_EXTERNAL_TARGET_WORDS
    )
    allowed_hosts = [
        host
        for host in ("goldgoblins.se", "one.com")
        if host in normalized
    ]
    return {
        "risk_class": "RED" if external else "YELLOW",
        "capability_human_id": (
            "chat.task-scoped.external"
            if external
            else "chat.task-scoped.local"
        ),
        "effect_class": "TASK_SCOPED_EFFECTS",
        "persistent_write": (
            "TASK_SCOPED_AFTER_CHAT_APPROVAL"
            if external
            else "TASK_SCOPED_LOCAL_WRITE"
        ),
        "network": (
            "TASK_SCOPED_AFTER_CHAT_APPROVAL"
            if external
            else "NONE"
        ),
        "sudo": (
            "TASK_SCOPED_AFTER_CHAT_APPROVAL"
            if external
            else "NO"
        ),
        "external": external,
        "allowed_hosts": allowed_hosts,
        "summary": normalized[:512],
    }


def _chat_mandate_sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _chat_identity_workspace_context(workspace_object_id: str) -> dict[str, object]:
    object_id = str(workspace_object_id or "").strip()
    if not object_id:
        raise RuntimeError("CHAT_MANDATE_WORKSPACE_ID_EMPTY")
    return {
        "object_id": object_id,
        "source_path": "",
        "provenance": "REAL_UI_STATE",
        "sha256": hashlib.sha256(
            ("identity:" + object_id).encode("utf-8")
        ).hexdigest(),
    }


class ChatBridge(QObject):
    def __init__(
        self,
        root: QObject,
        parent: QObject | None = None,
        *,
        defer_startup: bool = False,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._machine_graph = None
        self._process: QProcess | None = None
        self._state: dict[str, str] | None = None
        self._orchestrator_assigned_participant = ""
        self._orchestrator_creator_actor = ""
        self._intent_laser: object | None = None
        self._intent_router_manifest_sha256 = ""
        self._intent_router_error = ""
        self._intent_capability_registry: object | None = None
        self._mandate_session_id = "mandate-session-" + uuid.uuid4().hex
        self._pending_mandates: dict[str, dict[str, object]] = {}
        self._live_mandate_store: live_mandate_store.MandateStore | None = None
        self._autonomy_session_id = "session-" + uuid.uuid4().hex
        self._autonomy_tasks: dict[str, dict[str, object]] = {}
        self._autonomy_stdout_buffer = ""
        self._selfdev_tasks: dict[str, dict[str, object]] = {}
        self._selfdev_stdout_buffer = ""
        self._ledger_error = ""
        self._task_ledger: control_contract.TaskLedger | None = None
        self._resident_information_state = None
        self._context_snapshot_json = ""
        self._context_snapshot_error = "CONTEXT_SNAPSHOT_NOT_SYNCED"
        self._resident_chat = None

        if not defer_startup:
            self.initialize_startup_machine_graph()
            self.initialize_startup_information_state()
            self.initialize_startup_task_state()
            self.initialize_startup_resident_chat()

    def initialize_startup_machine_graph(self) -> None:
        self._machine_graph = _build_workbench_machine_graph()

    def initialize_startup_information_state(self) -> None:
        self._resident_information_state = (
            resident_state.WorkbenchResidentInformationState.bootstrap_workbench_sources(
                repo_root=REPO_ROOT,
                limited_target_relative_path=(
                    write_contract.TARGET_RELATIVE_PATH
                ),
                limited_producer_path=WRITE_RUNNER_PATH,
                limited_producer_contract_path=(
                    PROJECT / "backend" / "write_contract.py"
                ),
                control_target_relative_path=control_contract.TARGET_RELATIVE_PATH,
                control_producer_path=CONTROL_APPLY_RUNNER_PATH,
                control_producer_contract_path=(
                    PROJECT / "backend" / "control_plane_contract.py"
                ),
                project_relative_root=(
                    PROJECT.relative_to(REPO_ROOT).as_posix()
                    if PROJECT != REPO_ROOT else ""
                ),
            )
        )

    def initialize_startup_task_state(self) -> None:
        try:
            runtime = private_runtime_root()
            ledger_parent = Path(platform_path("/home/GG/.local/state/goldgoblins"))
            ledger_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._task_ledger = control_contract.TaskLedger(
                ledger_parent / "workbench-control-v2",
                legacy_root=(runtime / "gg-control-plane-v1"),
            )
            mandate_root = task_scoped_action_grant.DEFAULT_MANDATE_ROOT
            self._live_mandate_store = live_mandate_store.MandateStore(
                mandate_root
            )
            self._live_mandate_store.initialize()
            self._recover_selfdev_records(runtime)
            self._block_unrecoverable_autonomy_records()
        except Exception as exc:
            self._ledger_error = type(exc).__name__ + ":" + str(exc)

    def initialize_startup_resident_chat(self) -> None:
        self._resident_chat = ResidentChatTransport(
            self,
            self._root,
            self._set_bridge_activity,
        )
        surface_host = getattr(self._resident_chat, "_surface_host", None)
        set_tui_handler = getattr(
            surface_host,
            "set_tui_chat_line_handler",
            None,
        )
        if callable(set_tui_handler):
            set_tui_handler(self._handle_tui_chat_line)

    def _native_tui_engine_active(self) -> bool:
        try:
            engine_target = normalize_engine_target(
                self._root.property("engineTarget")
            )
        except GrokWorkerContractError:
            return False
        return engine_target in {ENGINE_GPT_TUI, ENGINE_GROK_TUI}

    def _tui_chat_context(self) -> tuple[str, str]:
        workspace = self._root.findChild(QObject, "workspaceSurface")
        context_reference = "@current"
        workspace_object_id = ""
        if workspace is not None:
            try:
                context_reference = str(
                    workspace.property("currentContextReference") or ""
                ).strip()
                workspace_object_id = str(
                    workspace.property("currentObjectId") or ""
                ).strip()
            except (RuntimeError, TypeError):
                context_reference = "@current"
                workspace_object_id = ""

        # WorkspaceSurface selects the scratch object on startup.  Keep the
        # native TUI ingress usable during the short QML initialization gap
        # as well, without inventing a broad or unbound workspace target.
        if not workspace_object_id:
            workspace_object_id = "ws.file.scratch.1"
        if context_reference not in {"@current", "@workspace"}:
            context_reference = "@current"
        if context_reference == "@workspace":
            context_reference = "@current"
        return context_reference, workspace_object_id

    def _show_tui_notice(self, terminal_id: str, text: str) -> None:
        transport = getattr(self, "_resident_chat", None)
        surface_host = getattr(transport, "_surface_host", None)
        show = getattr(surface_host, "showChatTerminalNotice", None)
        if not callable(show):
            return
        try:
            show(str(terminal_id or ""), str(text or ""))
        except (AttributeError, RuntimeError, TypeError):
            return

    def _dispatch_visual_command(
        self,
        text: str,
        *,
        terminal_id: str = "",
        context_reference: str = "@current",
        workspace_object_id: str = "",
    ) -> bool:
        """Send presentation commands through the one shared visual ingress."""
        parsed = visual_commands.parse_visual_command(text)
        if parsed is None:
            return False
        transport = getattr(self, "_resident_chat", None)
        surface_host = getattr(transport, "_surface_host", None)
        dispatch = getattr(surface_host, "dispatchVisualCommand", None)
        if not callable(dispatch):
            return False
        try:
            message = str(dispatch(str(text)) or "")
        except (AttributeError, RuntimeError, TypeError):
            message = visual_commands.command_message(parsed)
        if terminal_id:
            self._show_tui_notice(terminal_id, message)
        else:
            self._append(
                "GG SETTINGS",
                "VISUAL",
                message,
                str(context_reference or "@current")
                + (" · " + str(workspace_object_id) if workspace_object_id else ""),
                "ROUTED",
                12,
            )
        return True

    def _waiting_chat_native_mandates(self) -> list[dict[str, object]]:
        return [
            pending
            for pending in self._pending_mandates.values()
            if pending.get("status") == "WAITING_APPROVAL"
            and pending.get("approval_mode") == "CHAT_NATIVE_TASK_SCOPED"
        ]

    def _latest_waiting_chat_native_mandate(self) -> dict[str, object] | None:
        waiting = self._waiting_chat_native_mandates()
        return waiting[-1] if waiting else None

    def _supersede_older_chat_native_mandates(
        self,
        keep: dict[str, object] | None = None,
    ) -> None:
        keep_id = str((keep or {}).get("pending_id") or "")
        for pending in self._pending_mandates.values():
            if pending is keep:
                continue
            if keep_id and str(pending.get("pending_id") or "") == keep_id:
                continue
            if pending.get("status") != "WAITING_APPROVAL":
                continue
            if pending.get("approval_mode") != "CHAT_NATIVE_TASK_SCOPED":
                continue
            pending["status"] = "SUPERSEDED"

    def _tui_approval_notice(self, action: str) -> str:
        waiting = self._waiting_chat_native_mandates()
        if not waiting:
            return "GG: Det finns ingen väntande godkännandeuppgift."
        if action == "APPROVE":
            return "GG: Ja mottaget. Godkännandet behandlas för uppgiften."
        return "GG: Nej mottaget. Uppgiften avvisas."

    def _handle_tui_chat_line(self, terminal_id: str, text: str) -> bool:
        """Route GPTUI conversation and GPT/Grok task lines into chat.

        GPTUI's ordinary submitted lines go through the same Workbench
        ingress as the composer. Its shared OmniGPT/Idékompass layer is
        injected into Codex's hidden developer instructions at session start.
        Concrete task requests and the user's ja/nej gate are handled for
        both TUIs.  The finite visual slash commands are shared with the
        composer; all other slash commands remain native.
        """
        terminal_key = str(terminal_id or "").strip()
        if terminal_key not in {
            "ws.tui.gpt",
            "ws.tui.grok",
        }:
            return False
        value = str(text or "").strip()
        if not value:
            return False

        if self._dispatch_visual_command(value, terminal_id=terminal_key):
            return True

        chat_approval = parse_chat_approval(value)
        resume_request = parse_chat_resume_request(value)
        action_request = parse_chat_action_request(value)
        waiting_approval = self._waiting_chat_native_mandates()
        # A bare "ja"/"nej" is special when a native-chat task is waiting.
        # Several stacked requests keep the latest one; older waiting
        # tasks are superseded so the visible answer still works.
        if chat_approval is not None:
            if not waiting_approval:
                return False
            if len(waiting_approval) > 1:
                self._supersede_older_chat_native_mandates(
                    keep=waiting_approval[-1]
                )
        elif action_request is not None:
            # Never eat the native line for a new task.  The TUI keeps the
            # text the user typed.  Only live/external requests also create
            # a ja/nej gate in the background.
            if action_request.get("external") and action_request.get("risk_class") == "RED":
                context_reference, workspace_object_id = self._tui_chat_context()

                def capture_live() -> None:
                    try:
                        self._capture_chat_native_mandate(
                            user_text=value,
                            chat_scope=action_request,
                            workspace_context=_chat_identity_workspace_context(
                                workspace_object_id
                            ),
                            context_reference=context_reference,
                            workspace_object_id=workspace_object_id,
                        )
                        self._show_tui_notice(
                            terminal_key,
                            "GG: Live-uppgift väntar på ja eller nej.",
                        )
                    except Exception:
                        return

                QTimer.singleShot(0, capture_live)
            return False
        if chat_approval is None and resume_request is not None:
            if self._latest_chat_native_pending(
                {"WAITING_APPROVAL", "APPROVED_VALID", "EXECUTION_RUNNING"}
            ) is None:
                return False
        elif (
            chat_approval is None
            and action_request is None
        ):
            # Ordinary GPTUI conversation must remain native. Codex owns its
            # own line editor and Enter key; intercepting every submitted line
            # makes the visible TUI look like it opened a second input and
            # can discard text already typed on the first one.
            return False

        context_reference, workspace_object_id = self._tui_chat_context()

        notice = ""
        if chat_approval is not None:
            notice = self._tui_approval_notice(chat_approval)
        elif action_request is not None:
            notice = (
                "GG: Uppgiften är mottagen. Jag visar godkännandet här när "
                "det är klart."
            )

        # The host clears the native line first. Deferring submit by one
        # event-loop turn means the approved prompt is then written after
        # that clear, never before it.
        def dispatch_line() -> None:
            try:
                self.submit(
                    value,
                    context_reference,
                    workspace_object_id,
                )
            finally:
                if notice:
                    self._show_tui_notice(terminal_key, notice)

        QTimer.singleShot(0, dispatch_line)
        return True

    def _shutdown_resident_idle_for_task(self) -> None:
        if not self._native_tui_engine_active():
            self._resident_chat.shutdown_idle()

    def machine_graph_sha256(self) -> str:
        return self._machine_graph.graph_sha256()

    def machine_graph_snapshot(self) -> dict[str, object]:
        return self._machine_graph.as_dict()

    def preview_machine_graph_patch(
        self,
        patch: machine_graph.GraphPatch,
    ) -> machine_graph.GraphPatchResult:
        result = machine_graph.apply_patch(
            self._machine_graph,
            patch,
        )
        result.validate()

        if (
            result.before_graph_sha256
            != self._machine_graph.graph_sha256()
        ):
            raise machine_graph.MachineGraphError(
                "ACTIVE_GRAPH_IDENTITY_DRIFT"
            )

        if (
            result.action_authority != "NONE"
            or result.persistent_write != "NONE"
            or result.model_inference is not False
        ):
            raise machine_graph.MachineGraphError(
                "PATCH_PREVIEW_AUTHORITY_INVARIANT_FAIL"
            )

        return result

    def _machine_graph_edge_enabled(
        self,
        edge_id: str,
    ) -> bool:
        matches = tuple(
            edge
            for edge in self._machine_graph.edges
            if edge.edge_id == edge_id
        )

        if len(matches) != 1:
            raise machine_graph.MachineGraphError(
                "RUNTIME_GRAPH_EDGE_IDENTITY_INVALID:"
                + edge_id
            )

        return matches[0].enabled

    def apply_machine_graph_patch(
        self,
        patch: machine_graph.GraphPatch,
    ) -> machine_graph.GraphPatchResult:
        patch.validate()

        for operation in patch.operations:
            if (
                operation.op
                not in {
                    machine_graph.OP_ENABLE_EDGE,
                    machine_graph.OP_DISABLE_EDGE,
                }
                or operation.edge_id not in {"call-01", "call-02", "call-03", "call-04", "call-05", "call-06", "call-07", "call-08", "call-09", "call-10", "call-11", "call-12"}
            ):
                raise machine_graph.MachineGraphError(
                    "PATCH_RUNTIME_BINDING_NOT_IMPLEMENTED"
                )

        result = self.preview_machine_graph_patch(
            patch
        )

        self._machine_graph = result.graph

        return result

    def _block_unrecoverable_autonomy_records(self) -> None:
        if self._task_ledger is None:
            return
        for record in self._task_ledger.all():
            if (
                record["kind"] == "AUTONOMY"
                and record["status"] in control_contract.PENDING_STATUSES
            ):
                self._task_ledger.update(
                    str(record["task_id"]),
                    status="BLOCKED",
                    last_reason="SESSION_BOUND_AUTONOMY_STATE_NOT_RECOVERABLE",
                )

    def _recover_selfdev_records(self, runtime: Path) -> None:
        if self._task_ledger is None:
            return
        for request_path in sorted(runtime.glob("gg-selfdev-request.*.json"))[:128]:
            try:
                if request_path.is_symlink() or not request_path.is_file():
                    continue
                if request_path.stat().st_size > 131072:
                    continue
                request = _selfdev_validate_request(
                    json.loads(request_path.read_text(encoding="utf-8"))
                )
                task_id = str(request["task_id"])
                if self._task_ledger.get(task_id) is not None:
                    continue
                root = runtime / (
                    "gg-selfdev-task." + task_id.removeprefix("task-")
                )
                status = "BLOCKED"
                reason = "RECOVERED_INCOMPLETE_SELFDEV_RUNTIME"
                candidate_sha = ""
                diff_sha = ""
                if root.is_dir() and not root.is_symlink():
                    result_path = root / "verified-result.json"
                    if result_path.is_file() and not result_path.is_symlink():
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                        if (
                            type(result) is dict
                            and result.get("task_id") == task_id
                            and result.get("status") == "WAITING_PERSISTENT_APPLY"
                            and control_contract.SHA256_RE.fullmatch(
                                str(result.get("candidate_sha256", ""))
                            )
                            and control_contract.SHA256_RE.fullmatch(
                                str(result.get("diff_sha256", ""))
                            )
                        ):
                            candidate_sha = str(result["candidate_sha256"])
                            diff_sha = str(result["diff_sha256"])
                            status = "WAITING_PERSISTENT_APPLY"
                            reason = "RECOVERED_VERIFIED_RUNTIME"
                    if (root / "rejected.json").is_file():
                        status = "REJECTED"
                        reason = "RECOVERED_REJECTION_RECEIPT"
                    if (root / "apply-receipt.json").is_file():
                        status = "DONE"
                        reason = "RECOVERED_APPLY_RECEIPT"
                self._task_ledger.create(
                    task_id,
                    "SELFDEV",
                    status,
                    str(request["goal"]),
                    "@current",
                    autonomy_contract.TARGET_WORKSPACE_OBJECT_ID,
                    base_head=str(request["base_head"]),
                    candidate_sha256=candidate_sha,
                    diff_sha256=diff_sha,
                    last_reason=reason,
                )
                self._task_ledger.append_log(
                    task_id,
                    "RECOVERY|" + status + "|" + reason,
                )
            except Exception:
                continue

    def _set_bridge_activity(self, busy: bool, task_id: str = "") -> None:
        setter = getattr(self._root, "setBridgeActivity", None)
        if callable(setter):
            setter(busy, task_id)

    @Slot(str)
    def syncContextSnapshot(
        self,
        snapshot_json: str,
    ) -> None:
        from backend import context_resolver

        try:
            if not self._machine_graph_edge_enabled(
                "call-01"
            ):
                raise context_resolver.ContextResolverError(
                    "MACHINE_GRAPH_EDGE_DISABLED:call-01"
                )

            canonical = (
                context_resolver
                .validate_snapshot_json(
                    snapshot_json
                )
            )

        except (
            context_resolver
            .ContextResolverError
        ) as exc:
            self._context_snapshot_json = ""
            self._context_snapshot_error = str(exc)
            return

        self._context_snapshot_json = canonical
        self._context_snapshot_error = ""

    def _resolved_chat_context(
        self,
        value: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> tuple[str, dict[str, object]]:
        from backend import context_resolver

        engine_target = normalize_engine_target(
            self._root.property("engineTarget")
        )

        if not self._context_snapshot_json:
            if context_reference != "@current":
                raise RuntimeError(
                    self._context_snapshot_error
                    or "CONTEXT_SNAPSHOT_REQUIRED"
                )

            return build_effective_prompt(
                value,
                context_reference,
                workspace_object_id,
                engine_target=engine_target,
            )

        if not self._machine_graph_edge_enabled(
            "call-02"
        ):
            raise machine_graph.MachineGraphError(
                "MACHINE_GRAPH_EDGE_DISABLED:call-02"
            )

        plan = context_resolver.resolve_snapshot(
            self._context_snapshot_json,
            context_reference,
            workspace_object_id,
        )

        primary_object_id = str(
            plan["primaryObjectId"]
        )

        (
            effective_prompt,
            primary_context,
        ) = build_effective_prompt(
            value,
            "@current",
            primary_object_id,
            engine_target=engine_target,
        )

        object_ids = plan["objectIds"]

        if not isinstance(object_ids, list):
            raise RuntimeError(
                "RESOLVED_OBJECT_IDS_INVALID"
            )

        verified_contexts = [
            primary_context
        ]

        for object_id in object_ids[1:]:
            verified_contexts.append(
                resolve_workspace_context(
                    str(object_id)
                )
            )

        if not self._machine_graph_edge_enabled(
            "call-03"
        ):
            raise machine_graph.MachineGraphError(
                "MACHINE_GRAPH_EDGE_DISABLED:call-03"
            )

        extension = (
            context_resolver
            .render_extension(
                plan,
                verified_contexts,
            )
        )

        return (
            effective_prompt + extension,
            primary_context,
        )

    def _ensure_natural_intent_laser(self) -> None:
        project_root = Path(__file__).resolve().parent
        repo_root = workspace_root()

        backend_path = (
            project_root
            / "backend"
        )

        manifest_path = (
            project_root
            / "SOURCE-MANIFEST.json"
        )

        import hashlib

        manifest_sha256 = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()

        if (
            self._intent_laser is not None
            and self._intent_capability_registry is not None
            and self._intent_router_manifest_sha256
            == manifest_sha256
        ):
            return

        try:
            backend_text = str(
                backend_path
            )

            if backend_text not in sys.path:
                sys.path.insert(
                    0,
                    backend_text,
                )

            from backend import capability_registry
            from backend import solver_router

            if not self._machine_graph_edge_enabled(
                "call-04"
            ):
                raise machine_graph.MachineGraphError(
                    "MACHINE_GRAPH_EDGE_DISABLED:call-04"
                )

            registry = (
                capability_registry
                .CapabilityRegistry.load(
                    repo_root=repo_root,
                    project_root=project_root,
                    seed_path=(
                        project_root
                        / "config"
                        / "capability-seeds-v1.json"
                    ),
                    manifest_path=manifest_path,
                )
            )

            if not self._machine_graph_edge_enabled(
                "call-05"
            ):
                raise machine_graph.MachineGraphError(
                    "MACHINE_GRAPH_EDGE_DISABLED:call-05"
                )

            router = (
                solver_router.SolverRouter(
                    registry,
                    edge_enabled=(
                        self._machine_graph_edge_enabled
                    ),
                )
            )

            if not self._machine_graph_edge_enabled(
                "call-06"
            ):
                raise machine_graph.MachineGraphError(
                    "MACHINE_GRAPH_EDGE_DISABLED:call-06"
                )

            self._intent_laser = (
                solver_router.LaserFocusCache(
                    router,
                    edge_enabled=(
                        self._machine_graph_edge_enabled
                    ),
                )
            )

            self._intent_capability_registry = registry
            self._intent_router_manifest_sha256 = (
                manifest_sha256
            )

            self._intent_router_error = ""

        except Exception as exc:
            self._intent_laser = None
            self._intent_capability_registry = None
            self._intent_router_manifest_sha256 = ""

            self._intent_router_error = (
                type(exc).__name__
                + ":"
                + str(exc)
            )

    def _natural_action_proposal(
        self,
        route_decision: object | None,
        workspace_context: dict[str, object],
    ) -> dict[str, object] | None:
        if route_decision is None:
            return None

        primary = getattr(route_decision, "primary_capability", None)
        if primary is None:
            return None

        if (
            getattr(route_decision, "automatic_model_dispatch", None) is not False
            or getattr(route_decision, "registered_capability_execution", None)
            is not False
        ):
            raise RuntimeError(
                "ROUTE_AUTHORITY_CONTRACT_INVALID_FOR_ACTION_PROPOSAL"
            )

        if not isinstance(primary, str) or not primary or len(primary) > 128:
            raise RuntimeError("ROUTE_PRIMARY_CAPABILITY_INVALID")

        if self._intent_capability_registry is None:
            raise RuntimeError("CAPABILITY_REGISTRY_NOT_BOUND_TO_LASER")

        record = self._intent_capability_registry.get(primary)
        contract = getattr(record, "contract", None)
        if not isinstance(contract, dict):
            return None
        if contract.get("execution_authority") == "NONE":
            return None

        return action_intent_contract.make_action_proposal(
            route_primary_capability=primary,
            capability_record=record,
            target_object_id=str(workspace_context["object_id"]),
            target_source_revision=str(workspace_context["sha256"]),
        )

    def _build_chat_native_mandate(
        self,
        *,
        user_text: str,
        chat_scope: dict[str, object],
        workspace_context: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build the internal, hash-bound record behind plain chat approval.

        The user-facing ingress is natural language.  The hashes below stay
        internal and bind the approval to this exact instruction, workspace
        target and source revision; they are never required from the user.
        """
        object_id = str(
            workspace_context.get("object_id") or ""
        ).strip()
        source_revision = str(
            workspace_context.get("sha256") or ""
        ).strip()
        source_path = str(
            workspace_context.get("source_path") or "(identity-only)"
        ).strip()
        if not object_id or len(source_revision) != 64:
            raise RuntimeError("CHAT_MANDATE_WORKSPACE_BINDING_INVALID")
        if any(char not in "0123456789abcdef" for char in source_revision):
            raise RuntimeError("CHAT_MANDATE_SOURCE_REVISION_INVALID")

        normalized = " ".join(str(user_text).split())[:4096]
        if not normalized:
            raise RuntimeError("CHAT_MANDATE_USER_TEXT_EMPTY")

        task_id = "chat-" + _chat_mandate_sha(
            {
                "text": normalized,
                "object_id": object_id,
                "source_revision": source_revision,
            }
        )[:32]
        origin_id = "workbench-" + _chat_mandate_sha(object_id)[:32]
        risk_class = str(chat_scope.get("risk_class") or "RED")
        capability_id = str(
            chat_scope.get("capability_human_id")
            or "chat.task-scoped.external"
        )
        effect_class = str(
            chat_scope.get("effect_class") or "TASK_SCOPED_EFFECTS"
        )
        external = bool(chat_scope.get("external"))

        action_material = {
            "task_id": task_id,
            "origin_id": origin_id,
            "capability_human_id": capability_id,
            "target_object_id": object_id,
            "target_source_revision": source_revision,
            "effect_class": effect_class,
            "risk_floor": risk_class,
            "user_text": normalized,
        }
        action_binding = _chat_mandate_sha(action_material)
        state_revision = _chat_mandate_sha(
            {
                "task_id": task_id,
                "object_id": object_id,
                "source_revision": source_revision,
                "state": "READY_FOR_CHAT_APPROVAL",
            }
        )
        action_trace = _chat_mandate_sha(
            {
                "action": "chat-task-scoped-command",
                "action_binding": action_binding,
            }
        )
        selected_action = _chat_mandate_sha(
            {
                "task_id": task_id,
                "action_binding": action_binding,
            }
        )

        forbidden_scope = [
            "all data outside the explicitly named Gold Goblins web changes",
            "GA4/GSC",
            "payment data",
            "customer/order data",
            "DNS",
            "e-mail",
            "other user roles",
            "plugin/theme updates",
            "passwords or secrets in chat, logs or files",
            "approval bypass",
            "approval scope drift",
            "target scope drift",
            "cross-task grant reuse",
            "grant replay",
            "unbounded background autonomy",
            "automatic authority expansion",
            "sudo unless separately named and approved",
        ]
        scope = [
            "the exact user instruction written in this chat",
            "the bound workspace target: " + object_id,
            "the bound source revision: " + source_revision,
            "the explicitly named Gold Goblins changes only",
            "backup before a persistent change",
            "live verification after a change",
            "rollback or restoration when verification fails",
            "TASK_SCOPED authority only after chat approval",
        ]
        if external:
            scope.extend(
                [
                    "visible user-authenticated WordPress path",
                    "goldgoblins.se and one.com only when named by this task",
                    "network/production/deploy/write only as named by this task",
                    "credentials entered by the user in the visible auth flow",
                    "user-controlled login and 2FA",
                ]
            )

        ready_core = {
            "owner": "GG",
            "goal": normalized,
            "expected_value": (
                "Carry out only the explicitly named chat instruction with "
                "task-scoped authority, verification and rollback."
            ),
            "scope": scope,
            "forbidden_scope": forbidden_scope,
            "risk_class": risk_class,
            "stop_conditions": [
                "workspace or source revision drift",
                "scope or target drift",
                "backup unavailable before a persistent change",
                "live verification or rollback unavailable",
                "visible user authentication or 2FA is required",
                "a password or secret is requested in chat, logs or files",
                "an effect is outside the exact user instruction",
            ],
            "expected_artifacts": [
                "task-bound approval record",
                "backup before persistent change",
                "live verification result",
                "rollback result when needed",
            ],
            "acceptance_criteria": [
                "the original chat instruction is preserved",
                "no action starts before ja/yes",
                "ja/yes activates TASK_SCOPED authority for this task only",
                "all explicitly named effects remain target-bound",
                "ordinary chat cannot expand the approved scope",
            ],
        }
        approval_scope = {
            "ready_core": copy.deepcopy(ready_core),
            "selected_action_node_id": selected_action,
            "action_trace_sha256": action_trace,
            "state_base_revision": state_revision,
        }
        scope_revision = _chat_mandate_sha(
            {
                "task_id": task_id,
                "origin_id": origin_id,
                "approval_scope": approval_scope,
            }
        )
        source_binding = {
            "task_envelope_sha256": _chat_mandate_sha(
                {"task_id": task_id, "text": normalized}
            ),
            "goal_chain_sha256": _chat_mandate_sha(
                {"goal": normalized, "object_id": object_id}
            ),
            "action_trace_sha256": action_trace,
            "hypothesis_state_sha256": _chat_mandate_sha(
                {"decision": "CHAT_TASK_SCOPED_APPROVAL"}
            ),
            "state_base_capture_sha256": _chat_mandate_sha(
                {"state_base_revision": state_revision}
            ),
            "revalidation_result_sha256": _chat_mandate_sha(
                {"result": "REVALIDATED", "source_revision": source_revision}
            ),
        }
        request: dict[str, object] = {
            "schema": "gg.mandate-approval-request.v1",
            "task_id": task_id,
            "origin_id": origin_id,
            "approval_scope": approval_scope,
            "source_binding": source_binding,
            "mandate_requirement": "EXPLICIT_REQUIRED",
            "approval_scope_revision": scope_revision,
        }
        request["request_capture_sha256"] = _chat_mandate_sha(request)
        request_capture = str(request["request_capture_sha256"])

        source_envelope = {
            "schema": "gg.chat-native-source.v1",
            "task_id": task_id,
            "origin_id": origin_id,
            "original_expression": normalized,
            "ready_core": copy.deepcopy(ready_core),
            "workspace_object_id": object_id,
            "source_path": source_path,
            "source_revision": source_revision,
        }
        evaluation_context = {
            "source_envelope": source_envelope,
            "goal_chain": {
                "schema": "gg.chat-native-goal-chain.v1",
                "task_id": task_id,
                "goal": normalized,
                "why": "The user named this task directly in chat.",
            },
            "hypothesis_state": {
                "schema": "gg.chat-native-hypothesis.v1",
                "decision": "CHAT_TASK_SCOPED_APPROVAL",
                "source_revision": source_revision,
            },
            "state_base": {
                "schema": "gg.chat-native-state-base.v1",
                "task_id": task_id,
                "origin_id": origin_id,
                "state_base_revision": state_revision,
                "source_revision": source_revision,
            },
            "ledger_records": [],
            "memory_records": [],
        }
        action_intent: dict[str, object] = {
            "schema": "gg.chat-native-action-intent.v1",
            "task_id": task_id,
            "origin_id": origin_id,
            "state_base_revision": state_revision,
            "goal_chain_sha256": source_binding["goal_chain_sha256"],
            "capability_action_node_id": selected_action,
            "action_trace_sha256": action_trace,
            "capability_human_id": capability_id,
            "target_object_id": object_id,
            "target_source_revision": source_revision,
            "effect_class": effect_class,
            "risk_floor": risk_class,
            "persistent_write": str(
                chat_scope.get("persistent_write") or "TASK_SCOPED_LOCAL_WRITE"
            ),
            "model_inference": False,
            "network": str(chat_scope.get("network") or "NONE"),
            "sudo": str(chat_scope.get("sudo") or "NO"),
            "capability_execution_profile_requirement": (
                "TASK_SCOPED_CHAT_APPROVAL"
            ),
            "action_authority": "NONE",
            "proposal_binding_sha256": action_binding,
            "binding_sha256": action_binding,
            "approval_summary": str(
                chat_scope.get("summary") or normalized[:512]
            ),
        }
        mandate_result: dict[str, object] = {
            "schema": "gg.chat-native-mandate-result.v1",
            "status": "VALIDATED",
            "reason_code": "CHAT_TASK_SCOPED_APPROVAL_REQUEST",
            "task_id": task_id,
            "handoff_id": "chat-handoff-" + action_binding[:24],
            "assigned_participant": (
                "GG-Webmaster" if external else "GG-AI-installator"
            ),
            "creator_actor": "human:chat",
            "request_capture_sha256": request_capture,
            "mandate_requirement": "EXPLICIT_REQUIRED",
            "canonical_request_mutated": False,
            "mandate_assertion_created": False,
            "mandate_evaluated": False,
            "capability_execution": False,
            "participant_execution": False,
            "action_authority": "NONE",
            "source_binding": source_binding,
            "approval_request": request,
            "evaluation_context": evaluation_context,
        }
        return mandate_result, action_intent

    def _capture_chat_native_mandate(
        self,
        *,
        user_text: str,
        chat_scope: dict[str, object],
        workspace_context: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> str:
        mandate_result, action_intent = self._build_chat_native_mandate(
            user_text=user_text,
            chat_scope=chat_scope,
            workspace_context=workspace_context,
        )
        pending_id = self._capture_pending_mandate(
            mandate_result=mandate_result,
            action_intent=action_intent,
            user_text=user_text,
            route_decision=None,
            context_reference=context_reference,
            workspace_object_id=workspace_object_id,
            approval_summary=str(
                chat_scope.get("summary") or user_text[:512]
            ),
        )
        pending = self._pending_mandates[pending_id]
        pending["approval_mode"] = "CHAT_NATIVE_TASK_SCOPED"
        pending["chat_scope"] = copy.deepcopy(chat_scope)
        pending["operator_ready"] = False
        self._supersede_older_chat_native_mandates(keep=pending)
        return pending_id

    def _capture_pending_mandate(
        self,
        *,
        mandate_result: dict[str, object],
        action_intent: dict[str, object],
        user_text: str,
        route_decision: object | None,
        context_reference: str,
        workspace_object_id: str,
        approval_summary: str | None = None,
    ) -> str:
        if mandate_result.get("status") != "VALIDATED":
            raise RuntimeError("PENDING_MANDATE_SOURCE_NOT_VALIDATED")
        if mandate_result.get("mandate_requirement") != "EXPLICIT_REQUIRED":
            raise RuntimeError("PENDING_MANDATE_NOT_EXPLICIT_REQUIRED")

        request = mandate_result.get("approval_request")
        evaluation_context = mandate_result.get("evaluation_context")
        if not isinstance(request, dict):
            raise RuntimeError("PENDING_APPROVAL_REQUEST_INVALID")
        if not isinstance(evaluation_context, dict):
            raise RuntimeError("PENDING_EVALUATION_CONTEXT_INVALID")

        request_capture = request.get("request_capture_sha256")
        scope_revision = request.get("approval_scope_revision")
        for label, value in (
            ("REQUEST_CAPTURE", request_capture),
            ("APPROVAL_SCOPE_REVISION", scope_revision),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise RuntimeError("PENDING_" + label + "_INVALID")

        if mandate_result.get("request_capture_sha256") != request_capture:
            raise RuntimeError("PENDING_REQUEST_CAPTURE_CONTINUITY_FAILED")
        if not isinstance(action_intent, dict):
            raise RuntimeError("PENDING_ACTION_INTENT_INVALID")

        for field in (
            "capability_human_id",
            "target_object_id",
            "target_source_revision",
            "effect_class",
            "risk_floor",
            "state_base_revision",
            "binding_sha256",
        ):
            if field not in action_intent:
                raise RuntimeError("PENDING_ACTION_INTENT_FIELD_MISSING:" + field)

        pending_id = "mandate-" + uuid.uuid4().hex
        manifest_sha256 = hashlib.sha256(
            (PROJECT / "SOURCE-MANIFEST.json").read_bytes()
        ).hexdigest()

        pending = {
            "pending_id": pending_id,
            "session_id": self._mandate_session_id,
            "status": "WAITING_APPROVAL",
            "context_reference": context_reference,
            "workspace_object_id": workspace_object_id,
            "manifest_sha256": manifest_sha256,
            "request_capture_sha256": request_capture,
            "approval_scope_revision": scope_revision,
            "user_text": user_text,
            "route_why": str(getattr(route_decision, "why", "")),
            "action_intent": copy.deepcopy(action_intent),
            "mandate_result": copy.deepcopy(mandate_result),
            "evaluation_context": copy.deepcopy(evaluation_context),
            "approval_summary": (
                str(approval_summary).strip()[:512]
                if approval_summary
                else str(
                    action_intent.get("capability_human_id")
                    or "the named chat action"
                )
            ),
            "approval_receipt": None,
            "approver_id": None,
            "mandate_assertion_sha256": None,
            "task_scoped_authorization": None,
            "task_scoped_runtime_scope_path": None,
            "execution_eligibility": None,
            "execution_state": "UNUSED",
            "execution_receipt": None,
            "action_effect_recovery": None,
            "action_done_when": None,
            "execution_eligibility_binding_sha256": None,
            "execution_safe_tool_request_sha256": None,
            "execution_evidence_path": None,
        }
        self._pending_mandates[pending_id] = pending
        try:
            action_task_continuity.capture_action_task(
                self._task_ledger,
                pending,
            )
            if getattr(self, "_live_mandate_store", None) is not None:
                live_mandate_store.put_pending(
                    self._live_mandate_store,
                    pending,
                )
        except Exception:
            self._pending_mandates.pop(
                pending_id,
                None,
            )
            raise

        self._append(
            "GG MANDATE",
            "APPROVAL_REQUIRED",
            (
                "Godkännande krävs innan den här åtgärden kan fortsätta.\n"
                "ÅTGÄRD: "
                + str(pending["approval_summary"])
                + "\nRISK: "
                + str(action_intent["risk_floor"])
                + "\n\nSvara bara `ja` för att godkänna eller `nej` för att avvisa.\n"
                + "Jag kopplar svaret automatiskt till just den här uppgiften."
            ),
            context_reference + " · " + workspace_object_id,
            "WAITING_FOR_USER",
            32,
        )
        return pending_id

    def _approve_chat_native_mandate(
        self,
        *,
        pending_id: str,
        pending: dict[str, object],
        approver_id: str,
        request: dict[str, object],
        action_intent: dict[str, object],
        current_manifest_sha256: str,
        context_reference: str,
        workspace_object_id: str,
        persist_action_approval: object,
    ) -> None:
        """Turn a plain-chat ``ja`` into the task-scoped grant.

        This path intentionally stages the approved task for the existing
        visible operators.  It does not pretend that a browser login, 2FA,
        backup or live verification happened merely because the user said
        ``ja``.
        """
        store = getattr(self, "_live_mandate_store", None)
        if store is None:
            raise RuntimeError("LIVE_MANDATE_STORE_UNAVAILABLE")

        request_capture = str(pending.get("request_capture_sha256") or "")
        scope_revision = str(
            pending.get("approval_scope_revision") or ""
        )
        task_id = str(request.get("task_id") or "")
        assertion_material = {
            "schema": "gg.chat-native-mandate-assertion.v1",
            "decision": "APPROVE",
            "approver_id": approver_id,
            "task_id": task_id,
            "request_capture_sha256": request_capture,
            "approval_scope_revision": scope_revision,
        }
        assertion_sha = _chat_mandate_sha(assertion_material)
        receipt = {
            "schema": "gg.mandate-evaluation-result.v1",
            "request_capture_sha256": request_capture,
            "approval_scope_revision": scope_revision,
            "current_approval_scope_revision": scope_revision,
            "mandate_assertion_sha256": assertion_sha,
            "result": "MANDATE_VALID",
            "reason_code": "APPROVAL_SCOPE_MATCH",
        }
        approved_record = live_mandate_store.approve(
            store,
            request_capture_sha256=request_capture,
            approval_scope_revision=scope_revision,
            approver_id=approver_id,
            mandate_assertion_sha256=assertion_sha,
            evaluation_receipt=copy.deepcopy(receipt),
        )
        grant = task_scoped_action_grant.issue_from_approved_record(
            approved_record
        )
        authorization = task_scoped_action_grant.authorize_effect(
            grant,
            effect=str(
                action_intent.get("effect_class")
                or "TASK_SCOPED_EFFECTS"
            ),
            current_target_object_id=str(
                action_intent["target_object_id"]
            ),
            current_target_source_revision=str(
                action_intent["target_source_revision"]
            ),
        )

        pending["status"] = "APPROVED_VALID"
        pending["approver_id"] = approver_id
        pending["approval_receipt"] = copy.deepcopy(receipt)
        pending["mandate_assertion_sha256"] = assertion_sha
        pending["task_scoped_grant"] = grant
        pending["task_scoped_authorization"] = authorization
        chat_scope = pending.get("chat_scope")
        allowed_hosts = (
            chat_scope.get("allowed_hosts", [])
            if isinstance(chat_scope, dict)
            else []
        )
        runtime_scope_path = task_scoped_action_grant.publish_runtime_scope(
            grant,
            store_root=Path(store.root),
            allowed_hosts=allowed_hosts,
        )
        pending["task_scoped_runtime_scope_path"] = str(runtime_scope_path)
        pending["execution_eligibility"] = {
            "schema": "gg.chat-native-execution-eligibility.v1",
            "result": "TASK_SCOPED_READY",
            "action_authority": "TASK_SCOPED",
            "general_action_authority": "TASK_SCOPED",
            "scope_authority": "ALL_TASK_SCOPED_EFFECTS",
            "capability_execution": False,
            "participant_execution": False,
            "network": action_intent.get("network", "NONE"),
            "sudo": action_intent.get("sudo", "NO"),
            "manifest_sha256": current_manifest_sha256,
        }
        # The continuity ledger uses UNUSED until the approved task is
        # actually dispatched.  Operator readiness is tracked separately so
        # the approval record remains valid before the motor accepts it.
        pending["execution_state"] = "UNUSED"
        pending["operator_ready"] = True

        if callable(persist_action_approval):
            persist_action_approval()

        self._append(
            "GG MANDATE",
            "VALID",
            (
                "Chatmandatet är godkänt och aktivt för den här uppgiften.\n"
                "MANDATE: APPROVED_VALID\n"
                "ACTION_AUTHORITY: TASK_SCOPED\n"
                "GENERAL_ACTION_AUTHORITY: TASK_SCOPED\n"
                "SCOPE_AUTHORITY: ALL_TASK_SCOPED_EFFECTS\n"
                "Den ursprungliga chat-instruktionen är nu bunden till detta "
                "mål och kan fortsätta via synlig användarautentiserad väg. "
                "Login, 2FA, backup, verifiering och rollback görs bara när "
                "den aktuella vägen faktiskt är redo; lösenord skrivs aldrig "
                "i chatten, loggar eller filer."
            ),
            context_reference + " · " + workspace_object_id,
            "PASS",
            30,
        )
        self._dispatch_approved_chat_task(
            pending=pending,
            context_reference=context_reference,
            workspace_object_id=workspace_object_id,
        )

    def _dispatch_approved_chat_task(
        self,
        *,
        pending: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        """Continue the approved instruction through the selected chat motor."""
        transport = getattr(self, "_resident_chat", None)
        submit = getattr(transport, "submit", None)
        if not callable(submit):
            return

        user_text = str(pending.get("user_text") or "").strip()
        if not user_text:
            raise RuntimeError("CHAT_NATIVE_USER_TEXT_LOST")
        engine_target = normalize_engine_target(
            self._root.property("engineTarget")
        )
        if engine_target == ENGINE_GPT_TUI:
            # GPTUI has a hidden developer-instruction layer configured when
            # its Codex session starts. Keep this PTY user turn human-sized;
            # the full Workbench context must never be echoed into the TUI.
            prompt = (
                "GG Workbench: användaren har redan godkänt den här exakta "
                "uppgiften.\n"
                + user_text
            )
        else:
            prompt = (
                "[GG TASK APPROVAL ACTIVE]\n"
                "The human approved this exact task in the same chat with ja. "
                "Carry out only the explicitly named effects for this task. "
                "Use visible user-authenticated paths. The user performs login "
                "and 2FA when needed. Never put passwords or secrets in chat, "
                "logs or files. Keep backup, live verification and rollback with "
                "this task. Do not ask the user for hashes, tokens, mandate "
                "commands or authority fields; the chat ja/nej answer is the "
                "only approval interaction. Do not expose internal binding data "
                "in the user-facing reply.\n\n"
                "[USER TASK]\n"
                + user_text
                + "\n[/USER TASK]"
            )
        if engine_target == ENGINE_LOCAL_QWEN:
            prompt, _ = self._resolved_chat_context(
                prompt,
                context_reference,
                workspace_object_id,
            )
        request = contract.validate_request(
            {
                "schema": contract.REQUEST_SCHEMA,
                "request_id": "chat-task-" + uuid.uuid4().hex,
                "mode": "CHAT",
                "prompt": prompt,
            }
        )
        accepted = submit(
            request,
            context_reference,
            workspace_object_id,
            _chat_identity_workspace_context(workspace_object_id),
        )
        if accepted is False:
            raise RuntimeError("CHAT_NATIVE_TASK_DISPATCH_REJECTED")
        pending["execution_state"] = "DISPATCHED"
        pending["operator_ready"] = True
        action_task_continuity.record_action_dispatch(
            self._task_ledger,
            pending,
        )
        self._append(
            "GG MANDATE",
            "DISPATCHED",
            (
                "Den godkända chat-instruktionen är skickad till den aktiva "
                "motorn. Jag fortsätter bara inom den uttryckliga uppgiften."
            ),
            context_reference + " · " + workspace_object_id,
            "RUNNING",
            30,
        )

    def _submit_mandate(
        self,
        parsed: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        pending_id = str(parsed.get("pending_id", ""))
        pending = self._pending_mandates.get(pending_id)

        def persist_action_approval() -> None:
            action_task_continuity.record_action_approval(
                self._task_ledger,
                pending,
            )

        if pending is None:
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Pending mandate finns inte i denna Workbench-session.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if pending.get("status") != "WAITING_APPROVAL":
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Pending mandate är stale, redan använd eller avslutad.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if pending.get("session_id") != self._mandate_session_id:
            pending["status"] = "BLOCKED_STALE"
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Pending mandate tillhör inte aktuell session.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        command_scope = str(parsed.get("approval_scope_revision", ""))
        if command_scope != pending.get("approval_scope_revision"):
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Approval scope revision mismatch.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if (
            context_reference != pending.get("context_reference")
            or workspace_object_id != pending.get("workspace_object_id")
        ):
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Pending mandate target context mismatch.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        try:
            current_manifest_sha256 = hashlib.sha256(
                (PROJECT / "SOURCE-MANIFEST.json").read_bytes()
            ).hexdigest()
            if current_manifest_sha256 != pending.get("manifest_sha256"):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("MANIFEST_CHANGED_AFTER_MANDATE_REQUEST")

            if pending.get("approval_mode") == "CHAT_NATIVE_TASK_SCOPED":
                workspace = _chat_identity_workspace_context(
                    workspace_object_id
                )
            else:
                workspace = resolve_workspace_context(workspace_object_id)
            action_intent = pending.get("action_intent")
            if not isinstance(action_intent, dict):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("PENDING_ACTION_INTENT_LOST")
            current_target_revision = str(workspace.get("sha256") or "")
            if not current_target_revision and not str(
                workspace.get("source_path") or ""
            ):
                current_target_revision = hashlib.sha256(
                    ("identity:" + workspace_object_id).encode("utf-8")
                ).hexdigest()
            if current_target_revision != action_intent.get(
                "target_source_revision"
            ):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("TARGET_CHANGED_AFTER_MANDATE_REQUEST")

            mandate_result = pending.get("mandate_result")
            if not isinstance(mandate_result, dict):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("PENDING_MANDATE_RESULT_LOST")
            request = mandate_result.get("approval_request")
            if not isinstance(request, dict):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("PENDING_APPROVAL_REQUEST_LOST")
            if (
                request.get("request_capture_sha256")
                != pending.get("request_capture_sha256")
                or request.get("approval_scope_revision")
                != pending.get("approval_scope_revision")
            ):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("PENDING_REQUEST_IDENTITY_DRIFT")
            if mandate_result.get("evaluation_context") != pending.get(
                "evaluation_context"
            ):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("PENDING_EVALUATION_CONTEXT_DRIFT")

            if parsed.get("action") == "REJECT":
                pending["status"] = "REJECTED"
                if getattr(self, "_live_mandate_store", None) is not None:
                    live_mandate_store.reject(
                        self._live_mandate_store,
                        request_capture_sha256=str(
                            pending["request_capture_sha256"]
                        ),
                        approval_scope_revision=str(
                            pending["approval_scope_revision"]
                        ),
                    )
                persist_action_approval()
                self._append(
                    "GG MANDATE",
                    "REJECTED",
                    (
                        "Mandatet avvisades. Assertion skapades inte "
                        "och ingen capability kördes."
                    ),
                    context_reference + " · " + workspace_object_id,
                    "CANCELLED",
                    24,
                )
                return

            if parsed.get("action") != "APPROVE":
                raise RuntimeError("UNSUPPORTED_MANDATE_ACTION")

            approver_id = parsed.get("approver_id")
            if not isinstance(approver_id, str):
                raise RuntimeError("EXPLICIT_HUMAN_APPROVER_ID_MISSING")

            if pending.get("approval_mode") == "CHAT_NATIVE_TASK_SCOPED":
                self._approve_chat_native_mandate(
                    pending_id=pending_id,
                    pending=pending,
                    approver_id=approver_id,
                    request=request,
                    action_intent=action_intent,
                    current_manifest_sha256=current_manifest_sha256,
                    context_reference=context_reference,
                    workspace_object_id=workspace_object_id,
                    persist_action_approval=persist_action_approval,
                )
                return

            evaluation = (
                orchestrator_mandate_evaluation_adapter.evaluate_explicit_approval(
                    copy.deepcopy(mandate_result),
                    approver_id=approver_id,
                    approval_scope_revision_value=command_scope,
                )
            )
            receipt = evaluation.get("evaluation_receipt")

            if (
                evaluation.get("status") != "EVALUATED"
                or evaluation.get("reason_code") != "MANDATE_VALID_VERIFIED"
                or not isinstance(receipt, dict)
                or receipt.get("result") != "MANDATE_VALID"
                or receipt.get("reason_code") != "APPROVAL_SCOPE_MATCH"
                or evaluation.get("mandate_assertion_created") is not True
                or evaluation.get("capability_execution") is not False
                or evaluation.get("participant_execution") is not False
                or evaluation.get("action_authority") != "NONE"
                or evaluation.get("ordinary_chat_blocked") is not True
            ):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("MANDATE_VALID_RECEIPT_CONTRACT_FAILED")

            assertion_sha = receipt.get("mandate_assertion_sha256")
            if (
                not isinstance(assertion_sha, str)
                or len(assertion_sha) != 64
                or any(char not in "0123456789abcdef" for char in assertion_sha)
            ):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("MANDATE_ASSERTION_SHA_INVALID")

            try:
                if self._intent_capability_registry is None:
                    raise RuntimeError(
                        "CAPABILITY_REGISTRY_NOT_BOUND_FOR_ELIGIBILITY"
                    )

                capability_record = self._intent_capability_registry.get(
                    str(action_intent["capability_human_id"])
                )

                execution_eligibility = (
                    action_execution_eligibility.evaluate_execution_eligibility(
                        action_intent=copy.deepcopy(action_intent),
                        capability_record=capability_record,
                        approval_request=copy.deepcopy(request),
                        approval_receipt=copy.deepcopy(receipt),
                        mandate_assertion_sha256=assertion_sha,
                        current_manifest_sha256=current_manifest_sha256,
                        expected_manifest_sha256=str(
                            pending["manifest_sha256"]
                        ),
                        current_target_object_id=workspace_object_id,
                        current_target_source_path=str(
                            workspace.get("source_path", "")
                        ),
                        current_target_source_revision=str(
                            workspace.get("sha256", "")
                        ),
                        replay_state="UNUSED",
                    )
                )
            except Exception:
                pending["status"] = "BLOCKED_ELIGIBILITY"
                raise

            if (
                execution_eligibility.get("result")
                != "EXECUTION_ELIGIBLE"
                or execution_eligibility.get("reason_code")
                != "EXACT_SAFE_TOOL_READ_REFINEMENT"
                or execution_eligibility.get("action_authority") != "NONE"
                or execution_eligibility.get("general_action_authority")
                != "NONE"
                or execution_eligibility.get("capability_execution")
                is not False
                or execution_eligibility.get("k7_l_execution") is not False
                or execution_eligibility.get("participant_execution")
                is not False
                or execution_eligibility.get(
                    "execution_persistent_write_authority"
                )
                != "NONE"
                or execution_eligibility.get("network") != "NONE"
                or execution_eligibility.get("sudo") != "NO"
                or execution_eligibility.get("model_inference") is not False
            ):
                pending["status"] = "BLOCKED_ELIGIBILITY"
                raise RuntimeError(
                    "D67_EXECUTION_ELIGIBILITY_BLOCKED:"
                    + str(execution_eligibility.get("reason_code"))
                )

            pending["execution_eligibility"] = copy.deepcopy(
                execution_eligibility
            )

            pending["status"] = "APPROVED_VALID"
            pending["approver_id"] = approver_id
            pending["approval_receipt"] = copy.deepcopy(receipt)
            pending["mandate_assertion_sha256"] = assertion_sha
            if getattr(self, "_live_mandate_store", None) is not None:
                approved_record = live_mandate_store.approve(
                    self._live_mandate_store,
                    request_capture_sha256=str(
                        pending["request_capture_sha256"]
                    ),
                    approval_scope_revision=str(
                        pending["approval_scope_revision"]
                    ),
                    approver_id=approver_id,
                    mandate_assertion_sha256=assertion_sha,
                    evaluation_receipt=copy.deepcopy(receipt),
                )
                pending["task_scoped_grant"] = (
                    task_scoped_action_grant.issue_from_approved_record(
                        approved_record
                    )
                )
                pending["task_scoped_authorization"] = (
                    task_scoped_action_grant.authorize_effect(
                        pending["task_scoped_grant"],
                        effect=str(action_intent["effect_class"]),
                        current_target_object_id=str(
                            action_intent["target_object_id"]
                        ),
                        current_target_source_revision=str(
                            action_intent["target_source_revision"]
                        ),
                    )
                )
            persist_action_approval()

            grant = pending.get("task_scoped_grant")
            grant_line = (
                "ACTION_AUTHORITY: TASK_SCOPED\n"
                "GENERAL_ACTION_AUTHORITY: TASK_SCOPED\n"
                "SCOPE_AUTHORITY: ALL_TASK_SCOPED_EFFECTS\n"
                "GRANT_SHA256: "
                + str(grant.get("grant_sha256"))
                + "\n"
                if isinstance(grant, dict)
                else "ACTION_AUTHORITY: NONE\n"
            )
            self._append(
                "GG MANDATE",
                "VALID",
                (
                    "Native K7-K mandat verifierat.\n"
                    "RESULT: MANDATE_VALID\n"
                    "REASON: APPROVAL_SCOPE_MATCH\n"
                    "MANDATE_ASSERTION_SHA256: "
                    + assertion_sha
                    + "\n"
                    + grant_line
                    + "K7-L EXECUTION: NO\n"
                    "CAPABILITY EXECUTION: NO\n"
                    "D67 EXECUTION ELIGIBILITY: PASS\nSAFE TOOL PROFILE: READ · request staged only\nD68 EXECUTION: STARTING - exact staged READ"
                ),
                context_reference + " · " + workspace_object_id,
                "PASS",
                30,
            )
            self._submit_eligible_tool(
                pending_id=pending_id,
                pending=pending,
                context_reference=context_reference,
                workspace_object_id=workspace_object_id,
            )
        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Mandate approval blockerad: "
                + type(exc).__name__
                + ":"
                + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                24,
            )
            return

    def _submit_bare_chat_approval(
        self,
        action: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> bool:
        waiting = self._waiting_chat_native_mandates()
        if not waiting:
            return False
        pending = waiting[-1]
        if len(waiting) > 1:
            self._supersede_older_chat_native_mandates(keep=pending)
        pending_id = str(pending.get("pending_id") or "")
        scope_revision = str(pending.get("approval_scope_revision") or "")
        parsed: dict[str, object] = {
            "action": action,
            "pending_id": pending_id,
            "approval_scope_revision": scope_revision,
        }
        if action == "APPROVE":
            parsed["approver_id"] = "GG_CHAT"
        self._shutdown_resident_idle_for_task()
        self._submit_mandate(parsed, context_reference, workspace_object_id)
        return True

    def _latest_chat_native_pending(
        self,
        statuses: set[str],
    ) -> dict[str, object] | None:
        for pending in reversed(list(self._pending_mandates.values())):
            if pending.get("approval_mode") != "CHAT_NATIVE_TASK_SCOPED":
                continue
            if str(pending.get("status") or "") in statuses:
                return pending
        return None

    def _resume_chat_native_task(
        self,
        resume_text: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> bool:
        """Resume the latest task after a visible user handoff.

        ``prova igen``/``klar`` is intentionally narrower than approval: it
        can only continue an existing task that was already approved in this
        Workbench session.  A waiting task is never approved implicitly.
        """
        resume = parse_chat_resume_request(resume_text)
        if resume is None:
            return False

        waiting = self._latest_chat_native_pending({"WAITING_APPROVAL"})
        if waiting is not None:
            self._append(
                "GG MANDATE",
                "APPROVAL_REQUIRED",
                (
                    "Den senaste uppgiften väntar fortfarande på ditt "
                    "godkännande. Svara bara `ja` eller `nej`; `"
                    + resume
                    + "` godkänner inte automatiskt."
                ),
                context_reference + " · " + workspace_object_id,
                "WAITING_FOR_USER",
                32,
            )
            return True

        pending = self._latest_chat_native_pending(
            {"APPROVED_VALID", "EXECUTION_RUNNING"}
        )
        if pending is None:
            self._append(
                "GG SYSTEM",
                "CHAT",
                (
                    "Jag har ingen redan godkänd chat-uppgift att återuppta. "
                    "Skriv bara vad som ska göras i chatten, så skapar jag "
                    "en vanlig ja/nej-begäran automatiskt."
                ),
                context_reference + " · " + workspace_object_id,
                "WAITING",
                28,
            )
            return True

        if (
            context_reference != pending.get("context_reference")
            or workspace_object_id != pending.get("workspace_object_id")
        ):
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Den senaste uppgiften hör till en annan aktiv arbetsyta.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                24,
            )
            return True

        try:
            current_manifest_sha256 = hashlib.sha256(
                (PROJECT / "SOURCE-MANIFEST.json").read_bytes()
            ).hexdigest()
            if current_manifest_sha256 != pending.get("manifest_sha256"):
                pending["status"] = "BLOCKED_STALE"
                raise RuntimeError("MANIFEST_CHANGED_AFTER_MANDATE_REQUEST")

            if self._active():
                accepted = self._resident_chat.accept_followup(
                    (
                        "The user says the visible login/2FA handoff is "
                        "complete ("
                        + resume
                        + "). Resume the already approved task now. Keep "
                        "the same task scope, use the visible WEB path, "
                        "and never request or record a password or secret."
                    ),
                    context_reference,
                    workspace_object_id,
                )
                if not accepted:
                    raise RuntimeError("CHAT_RESUME_FOLLOWUP_REJECTED")
                self._append(
                    "GG MANDATE",
                    "RESUME",
                    (
                        "Jag fortsätter den redan godkända uppgiften efter "
                        "den synliga login/2FA-handofferingen."
                    ),
                    context_reference + " · " + workspace_object_id,
                    "RUNNING",
                    30,
                )
                return True

            self._shutdown_resident_idle_for_task()
            self._dispatch_approved_chat_task(
                pending=pending,
                context_reference=context_reference,
                workspace_object_id=workspace_object_id,
            )
            return True
        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Återupptagning blockerad: "
                + type(exc).__name__
                + ":"
                + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                24,
            )
            return True

    def _natural_intent_route(
        self,
        text: str,
        workspace_context: dict[str, object],
        workspace_object_id: str,
    ) -> tuple[object | None, str]:
        self._ensure_natural_intent_laser()

        if self._intent_laser is None:
            return (
                None,
                (
                    self._intent_router_error
                    or "INTENT_LASER_UNAVAILABLE"
                ),
            )

        try:
            from backend import solver_router

            source_path = Path(
                str(
                    workspace_context[
                        "source_path"
                    ]
                )
            )

            source_revision = str(
                workspace_context[
                    "sha256"
                ]
            )

            resolved_object_id = str(
                workspace_context[
                    "object_id"
                ]
            )

            if (
                not resolved_object_id
                or len(
                    resolved_object_id
                ) > 1024
            ):
                return (
                    None,
                    (
                        "RESOLVED_WORKSPACE_"
                        "OBJECT_ID_INVALID"
                    ),
                )

            language = (
                source_path.suffix
                .lower()
                .removeprefix(".")
                or "text"
            )

            normalized = " ".join(
                text.split()
            )

            if not normalized:
                return (
                    None,
                    "EMPTY_NATURAL_INTENT",
                )

            laser_query = normalized[:1024]

            goal_id = (
                "goal-natural-"
                + uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    (
                        resolved_object_id
                        + "\x1f"
                        + text
                    ),
                ).hex
            )

            context = (
                solver_router.RouteContext(
                    query=laser_query,
                    goal_id=goal_id,
                    object_id=resolved_object_id,
                    source_revision=source_revision,
                    language=language,
                    diagnostic_class=(
                        "NATURAL_INTENT"
                    ),
                )
            )

            if not self._machine_graph_edge_enabled(
                "call-07"
            ):
                return (
                    None,
                    "MACHINE_GRAPH_EDGE_DISABLED:call-07",
                )

            binding = (
                self._intent_laser.bind(
                    context
                )
            )

            if not self._machine_graph_edge_enabled(
                "call-08"
            ):
                return (
                    None,
                    "MACHINE_GRAPH_EDGE_DISABLED:call-08",
                )
            handle = (
                self._intent_laser.lookup(
                    binding.handle_id
                )
            )

            if handle is None:
                return (
                    None,
                    "LASER_FOCUS_HANDLE_MISSING",
                )

            decision = handle.route

            if (
                decision.automatic_model_dispatch
                or decision.registered_capability_execution
            ):
                return (
                    None,
                    (
                        "ROUTER_AUTHORITY_"
                        "CONTRACT_VIOLATION"
                    ),
                )

            return (
                decision,
                "",
            )

        except Exception as exc:
            return (
                None,
                (
                    type(exc).__name__
                    + ":"
                    + str(exc)
                ),
            )
    def _task_create(
        self,
        task_id: str,
        kind: str,
        status: str,
        goal: str,
        context_reference: str,
        workspace_object_id: str,
        **fields: object,
    ) -> None:
        if self._task_ledger is None:
            raise RuntimeError(
                "Control task ledger unavailable: " + self._ledger_error
            )
        self._task_ledger.create(
            task_id,
            kind,
            status,
            goal,
            context_reference,
            workspace_object_id,
            **fields,
        )

    def _task_update(self, task_id: str, **fields: object) -> None:
        if self._task_ledger is None:
            self._ledger_error = "TASK_LEDGER_UNAVAILABLE"
        else:
            try:
                self._task_ledger.update(task_id, **fields)
            except Exception as exc:
                self._ledger_error = type(exc).__name__ + ":" + str(exc)

        status = fields.get("status")
        if type(status) is str:
            if task_id in self._selfdev_tasks:
                self._selfdev_tasks[task_id]["status"] = status
            if task_id in self._autonomy_tasks:
                self._autonomy_tasks[task_id]["status"] = status

    def _task_log(self, task_id: str, line: str) -> None:
        if self._task_ledger is None:
            return
        try:
            self._task_ledger.append_log(task_id, line)
        except Exception as exc:
            self._ledger_error = type(exc).__name__ + ":" + str(exc)

    def _task_record(self, task_id: str) -> dict[str, object] | None:
        if self._task_ledger is None:
            return None
        return self._task_ledger.get(task_id)

    def _active_identifier(self) -> str:
        resident_id = self._resident_chat.active_request_id()
        if resident_id:
            return resident_id
        if self._state is None:
            return ""
        return self._state.get(
            "task_id",
            self._state.get("request_id", ""),
        )

    def _active(self) -> bool:
        if self._resident_chat.busy():
            return True
        return (
            self._process is not None
            and self._process.state()
            != QProcess.ProcessState.NotRunning
        )

    def _mark_stopped(self, state: dict[str, str]) -> None:
        task_id = state.get("task_id", "")
        identity = task_id or state.get("request_id", "ACTIVE_PROCESS")
        if task_id and control_contract.TASK_ID_RE.fullmatch(task_id):
            self._task_update(
                task_id,
                status="STOPPED_BY_USER",
                last_reason="STOPPED_BY_USER",
            )
        self._append(
            "GG SYSTEM",
            "CONTROL",
            "STOPPED_BY_USER=" + identity + "\nEVIDENCE_PRESERVED=YES",
            state.get("context", "@current")
            + " · "
            + state.get("workspace", ""),
            "CANCELLED",
            20,
        )

    def _force_kill(self, process: QProcess) -> None:
        if (
            process is self._process
            and process.state() != QProcess.ProcessState.NotRunning
        ):
            process.kill()

    def _stop_active(
        self,
        requested_task_id: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        resident_id = self._resident_chat.active_request_id()
        if resident_id:
            if requested_task_id and requested_task_id != resident_id:
                self._append(
                    "GG CONTROL",
                    "STOP",
                    "TASK_NOT_ACTIVE=" + requested_task_id + "\nACTIVE=" + resident_id,
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    20,
                )
                return
            self._resident_chat.stop()
            return
        if not self._active() or self._state is None or self._process is None:
            self._append(
                "GG CONTROL",
                "STOP",
                "NO_ACTIVE_TASK · /stop är idempotent.",
                context_reference + " · " + workspace_object_id,
                "PASS",
                20,
            )
            return

        active_id = self._active_identifier()
        if requested_task_id and requested_task_id != active_id:
            self._append(
                "GG CONTROL",
                "STOP",
                "TASK_NOT_ACTIVE=" + requested_task_id + "\nACTIVE=" + active_id,
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if self._state.get("stoppable", "1") != "1":
            self._append(
                "GG CONTROL",
                "STOP",
                "STOP_BLOCKED_CRITICAL_ATOMIC_APPLY=" + active_id,
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if self._state.get("stop_requested") == "1":
            self._append(
                "GG CONTROL",
                "STOP",
                "STOP_ALREADY_REQUESTED=" + active_id,
                context_reference + " · " + workspace_object_id,
                "STOPPING",
                20,
            )
            return

        self._state["stop_requested"] = "1"
        if control_contract.TASK_ID_RE.fullmatch(active_id):
            self._task_update(active_id, status="STOPPING")
        self._append(
            "GG CONTROL",
            "STOP",
            "TERM_REQUESTED=" + active_id + "\nKILL_FALLBACK_MS=3000",
            context_reference + " · " + workspace_object_id,
            "STOPPING",
            20,
        )
        process = self._process
        process.terminate()
        QTimer.singleShot(3000, lambda: self._force_kill(process))

    @Slot(str, str)
    def _setOrchestratorAssignment(
        self,
        participant: str,
        creator_actor: str,
    ) -> None:
        participant_value = participant.strip()
        actor_value = creator_actor.strip()

        if participant_value not in ORCHESTRATOR_PARTICIPANTS:
            self._append(
                "GG SYSTEM",
                "ORCHESTRATOR",
                (
                    "Explicit orchestrator assignment blocked · "
                    "unknown participant."
                ),
                "@orchestrator · session",
                "BLOCKED",
                20,
            )
            return

        if not actor_value:
            self._append(
                "GG SYSTEM",
                "ORCHESTRATOR",
                (
                    "Explicit orchestrator assignment blocked · "
                    "creator actor is required."
                ),
                "@orchestrator · session",
                "BLOCKED",
                20,
            )
            return

        self._orchestrator_assigned_participant = participant_value
        self._orchestrator_creator_actor = actor_value

        self._append(
            "GG SYSTEM",
            "ORCHESTRATOR",
            (
                "Explicit session assignment set · participant="
                + participant_value
                + " · creator_actor="
                + actor_value
                + " · action authority NONE"
            ),
            "@orchestrator · session",
            "PASS",
            20,
        )

    @Slot()
    def _clearOrchestratorAssignment(self) -> None:
        self._orchestrator_assigned_participant = ""
        self._orchestrator_creator_actor = ""

        self._append(
            "GG SYSTEM",
            "ORCHESTRATOR",
            (
                "Explicit session assignment cleared · "
                "ordinary chat remains available · "
                "action authority NONE"
            ),
            "@orchestrator · session",
            "PASS",
            20,
        )

    @Slot()
    def stopActive(self) -> None:
        state = self._state or {}
        self._stop_active(
            "",
            state.get("context", "@current"),
            state.get("workspace", ""),
        )

    def _append(
        self,
        author: str,
        kind: str,
        text: str,
        context: str,
        state: str,
        offset: int,
    ) -> None:
        append = getattr(self._root, "appendRealNode", None)

        if not callable(append):
            raise RuntimeError("QML appendRealNode is unavailable.")

        # The approval protocol is deliberately an implementation detail.
        # Keep its integrity checks and task binding in the runtime, but never
        # make the operator copy internal names, hashes or tokens from chat.
        visible_author = "GG TASK" if author == "GG MANDATE" else author
        visible_kind = "TASK" if kind == "MANDATE" else kind
        visible_text = self._operator_visible_text(text)
        append(
            visible_author,
            visible_kind,
            visible_text,
            context,
            state,
            offset,
            "",
        )

        if self._state is not None:
            task_id = self._state.get("task_id", "")
            if task_id:
                self._task_log(
                    task_id,
                    kind + "|" + state + "|" + text,
                )

    @staticmethod
    def _operator_visible_text(text: str) -> str:
        """Remove protocol plumbing from the operator-facing chat stream."""
        hidden_prefixes = (
            "action_authority:",
            "general_action_authority:",
            "scope_authority:",
            "mandate:",
            "mandate_assertion_sha256:",
            "grant_sha256:",
            "request_capture_sha256:",
            "approval_scope_revision:",
            "task_scoped_authorization:",
        )
        visible_lines: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            folded = line.casefold()
            if any(folded.startswith(prefix) for prefix in hidden_prefixes):
                continue
            if "hash-bound" in folded or "hashbund" in folded:
                line = line.replace("hash-bound", "intern uppgiftsbundet")
                line = line.replace("hashbundna", "interna uppgiftsbundna")
                line = line.replace("hashbundet", "internt uppgiftsbundet")
                line = line.replace("hashbund", "internt uppgiftsbundet")
            line = line.replace("Chatmandatet", "Chat-uppgiften")
            line = line.replace("chatmandatet", "chat-uppgiften")
            line = line.replace("Chatmandat", "Chat-uppgift")
            line = line.replace("chatmandat", "chat-uppgift")
            line = line.replace("Mandatet", "Uppgiften")
            line = line.replace("mandatet", "uppgiften")
            line = line.replace("Mandate", "Task approval")
            line = line.replace("mandate", "task approval")
            line = line.replace("MANDATE", "TASK APPROVAL")
            line = line.replace("action authority NONE", "")
            line = line.replace("action authority TASK_SCOPED", "")
            line = line.replace("ACTION AUTHORITY NONE", "")
            line = line.replace("ACTION AUTHORITY TASK_SCOPED", "")
            if line.strip():
                visible_lines.append(line)
        return "\n".join(visible_lines) or "Uppgiften fortsätter enligt chatten."

    def _task_runtime_root(self, task_id: str, kind: str) -> Path:
        if control_contract.TASK_ID_RE.fullmatch(task_id) is None:
            raise RuntimeError("CONTROL_TASK_ID_INVALID")
        runtime = private_runtime_root()
        suffix = task_id.removeprefix("task-")
        if kind in ("SELFDEV", "BOOTSTRAP"):
            name = "gg-selfdev-task." + suffix
        elif kind == "AUTONOMY":
            name = "gg-autonomy-task." + suffix
        else:
            raise RuntimeError("CONTROL_TASK_KIND_INVALID")
        return runtime / name

    def _verified_selfdev_result(
        self,
        task_id: str,
    ) -> dict[str, object]:
        record = self._task_record(task_id)
        if record is None or record["kind"] not in ("SELFDEV", "BOOTSTRAP"):
            raise RuntimeError("SELFDEV_TASK_NOT_FOUND")
        root = self._task_runtime_root(task_id, str(record["kind"]))
        result_path = root / "verified-result.json"
        if result_path.is_symlink() or not result_path.is_file():
            raise RuntimeError("VERIFIED_RESULT_MISSING")
        if result_path.stat().st_size > 131072:
            raise RuntimeError("VERIFIED_RESULT_TOO_LARGE")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        fields = {
            "schema",
            "task_id",
            "base_head",
            "target_relative_path",
            "before_sha256",
            "candidate_sha256",
            "diff_sha256",
            "foundation_gate_report_sha256",
            "candidate_write_count",
            "model_call_count",
            "host_repo_changed",
            "persistent_selfdev_write",
            "status",
        }
        if type(result) is not dict or set(result) != fields:
            raise RuntimeError("VERIFIED_RESULT_FIELDS_INVALID")
        if (
            result["schema"] != "gg.workbench.selfdev-result.v1"
            or result["task_id"] != task_id
            or result["target_relative_path"] != SELFDEV_TARGET_REPO_RELATIVE
            or result["host_repo_changed"] is not False
            or result["persistent_selfdev_write"] != "NONE"
            or result["status"] != "WAITING_PERSISTENT_APPLY"
        ):
            raise RuntimeError("VERIFIED_RESULT_CONTRACT_INVALID")
        for key in (
            "before_sha256",
            "candidate_sha256",
            "diff_sha256",
            "foundation_gate_report_sha256",
        ):
            if control_contract.SHA256_RE.fullmatch(str(result[key])) is None:
                raise RuntimeError("VERIFIED_RESULT_SHA_INVALID:" + key)
        if control_contract.HEAD_RE.fullmatch(str(result["base_head"])) is None:
            raise RuntimeError("VERIFIED_RESULT_HEAD_INVALID")
        return dict(result)

    def _next_task_step(self, record: dict[str, object]) -> str:
        task_id = str(record["task_id"])
        status = str(record["status"])
        if record.get("kind") == "ACTION":
            if status in ("DONE", "STOPPED"):
                return "NONE"
            return "ACTION_REVALIDATION_REQUIRED"
        if status == "WAITING_PERSISTENT_APPLY":
            return (
                "/approve-task "
                + task_id
                + " "
                + str(record["candidate_sha256"])
                + " "
                + str(record["base_head"])
            )
        if status == "WAITING_GRANT":
            return (
                "/approve-autonomy "
                + task_id
                + " "
                + str(record["grant_sha256"])
            )
        if status == "WAITING_HOST_APPLY" and record["write_proposal_id"]:
            return (
                "/approve-write "
                + str(record["write_proposal_id"])
                + " "
                + str(record["write_candidate_sha256"])
            )
        if status in ("BLOCKED", "STOPPED_BY_USER", "CANCELLED"):
            return "/resume " + task_id
        if status in ("DONE", "REJECTED"):
            return "/cleanup " + task_id
        if status in control_contract.ACTIVE_STATUSES:
            return "/stop " + task_id
        return "NONE"

    def _control_status(self, requested_task_id: str) -> str:
        if requested_task_id:
            record = self._task_record(requested_task_id)
            if record is None:
                return "TASK_NOT_FOUND=" + requested_task_id
            return (
                control_contract.task_summary(record)
                + "\nNEXT_COMMAND="
                + self._next_task_step(record)
            )
        if self._resident_chat.busy():
            return self._resident_chat.status_text()

        if self._active() and self._state is not None:
            return "\n".join(
                (
                    "ACTIVE=YES",
                    "KIND=" + self._state.get("kind", "UNKNOWN"),
                    "ID=" + (self._active_identifier() or "UNBOUND"),
                    "STOPPABLE=" + self._state.get("stoppable", "1"),
                    "STOP_REQUESTED=" + self._state.get("stop_requested", "0"),
                )
            )

        records = self._task_ledger.all() if self._task_ledger is not None else []
        if records:
            latest = records[-1]
            return (
                "ACTIVE=NO\nLATEST_TASK="
                + str(latest["task_id"])
                + "\nLATEST_STATUS="
                + str(latest["status"])
                + "\nNEXT_COMMAND="
                + self._next_task_step(latest)
            )
        return "ACTIVE=NO\nTASKS=NONE\nCONTROL_PLANE=READY"

    def _control_tasks(self) -> str:
        if self._task_ledger is None:
            return "TASK_LEDGER=UNAVAILABLE\nREASON=" + self._ledger_error
        records = self._task_ledger.all()
        if not records:
            return "TASKS=NONE"
        lines = ["TASKS=" + str(len(records))]
        for record in records:
            lines.append(
                str(record["task_id"])
                + " | "
                + str(record["kind"])
                + " | "
                + str(record["status"])
                + " | "
                + str(record["goal"])[:120]
            )
        return "\n".join(lines)

    def _control_diff(self, task_id: str) -> str:
        record = self._task_record(task_id)
        if record is None or record["kind"] not in ("SELFDEV", "BOOTSTRAP"):
            raise RuntimeError("DIFF_UNAVAILABLE_FOR_TASK")
        result = self._verified_selfdev_result(task_id)
        root = self._task_runtime_root(task_id, str(record["kind"]))
        path = root / "verified.diff"
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("VERIFIED_DIFF_MISSING")
        data = path.read_bytes()
        if not data or len(data) > 524288:
            raise RuntimeError("VERIFIED_DIFF_SIZE_INVALID")
        digest = hashlib.sha256(data).hexdigest()
        if digest != result["diff_sha256"]:
            raise RuntimeError("VERIFIED_DIFF_SHA_MISMATCH")
        return (
            "TASK_ID="
            + task_id
            + "\nDIFF_SHA256="
            + digest
            + "\n"
            + data.decode("utf-8", errors="strict")
        )

    def _control_doctor(self) -> str:
        checks: list[str] = []
        repo = workspace_root()
        git_env = host_environment({
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        })
        head = subprocess.run(
            [executable_path("git"), "-C", str(repo), "rev-parse", "HEAD"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            env=git_env,
        )
        if head.returncode == 0:
            checks.append("HEAD=" + head.stdout.decode("ascii", errors="replace").strip())
        else:
            checks.append("HEAD=FAIL")
        status = subprocess.run(
            [
                executable_path("git"),
                "-C",
                str(repo),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            env=git_env,
        )
        if status.returncode != 0:
            checks.append("HOST_REPO_STATUS=FAIL")
        elif status.stdout:
            checks.append("HOST_REPO_CLEAN=NO")
        else:
            checks.append("HOST_REPO_CLEAN=PASS")
        checks.append("PROJECT_TARGET=" + ("PASS" if (PROJECT / "main.py").is_file() else "NO"))
        checks.append(
            "CONTROL_CONTRACT="
            + ("PASS" if (PROJECT / "backend" / "control_plane_contract.py").is_file() else "NO")
        )
        checks.append(
            "CONTROL_APPLY_RUNNER="
            + ("PASS" if CONTROL_APPLY_RUNNER_PATH.is_file() else "NO")
        )
        checks.append("TASK_LEDGER=" + ("PASS" if self._task_ledger is not None else "NO"))
        if self._ledger_error:
            checks.append("TASK_LEDGER_LAST_ERROR=" + self._ledger_error)
        try:
            render = discover_nvidia_render()
            checks.append("NVIDIA_RENDER=" + str(render))
        except Exception as exc:
            checks.append("NVIDIA_RENDER=NO:" + str(exc))
        checks.extend(
            (
                "NETWORK_AUTHORITY=NONE",
                "SHELL_AUTHORITY=NONE",
                "ARBITRARY_EXEC_AUTHORITY=NONE",
                "CONTROL_DOCTOR=PASS",
            )
        )
        return "\n".join(checks)

    def _control_context(
        self,
        context_reference: str,
        workspace_object_id: str,
    ) -> str:
        if context_reference != "@current":
            raise RuntimeError("CONTEXT_REFERENCE_MUST_BE_CURRENT")
        current = resolve_workspace_context(workspace_object_id)
        return "\n".join(
            (
                "CONTEXT_REFERENCE=@current",
                "WORKSPACE_OBJECT_ID=" + str(current["object_id"]),
                "TITLE=" + str(current["title"]),
                "TYPE=" + str(current["object_type"]),
                "PROVENANCE=" + str(current["provenance"]),
                "SOURCE_PATH=" + str(current["source_path"]),
                "BYTES=" + str(current["bytes"]),
                "SHA256=" + str(current["sha256"]),
                "READ_ONLY=YES",
            )
        )

    def _reject_task(self, task_id: str, candidate_sha: str) -> str:
        record = self._task_record(task_id)
        if record is None or record["kind"] not in ("SELFDEV", "BOOTSTRAP"):
            raise RuntimeError("REJECT_TASK_NOT_FOUND")
        if record["status"] != "WAITING_PERSISTENT_APPLY":
            raise RuntimeError("REJECT_TASK_STATUS_INVALID:" + str(record["status"]))
        result = self._verified_selfdev_result(task_id)
        if candidate_sha != result["candidate_sha256"]:
            raise RuntimeError("REJECT_TASK_CANDIDATE_SHA_MISMATCH")
        root = self._task_runtime_root(task_id, str(record["kind"]))
        receipt = root / "rejected.json"
        payload = control_contract.canonical_json(
            {
                "schema": "gg.workbench.control-task-rejection.v1",
                "task_id": task_id,
                "candidate_sha256": candidate_sha,
                "host_write": False,
                "status": "REJECTED",
            }
        )
        fd = secure_open(
            receipt,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self._task_update(task_id, status="REJECTED", last_reason="OPERATOR_REJECTED")
        return "TASK_REJECTED=" + task_id + "\nHOST_WRITE=NO\nEVIDENCE_PRESERVED=YES"

    def _cleanup_task(self, task_id: str) -> str:
        record = self._task_record(task_id)
        if record is None:
            raise RuntimeError("CLEANUP_TASK_NOT_FOUND")
        if record["status"] not in control_contract.TERMINAL_STATUSES:
            raise RuntimeError("CLEANUP_REQUIRES_TERMINAL_TASK:" + str(record["status"]))
        if self._active_identifier() == task_id and self._active():
            raise RuntimeError("CLEANUP_ACTIVE_TASK_FORBIDDEN")
        root = self._task_runtime_root(task_id, str(record["kind"]))
        runtime = private_runtime_root()
        if root.parent != runtime:
            raise RuntimeError("CLEANUP_PATH_POLICY")
        removed = False
        if root.exists() or root.is_symlink():
            if root.is_symlink() or not root.is_dir():
                raise RuntimeError("CLEANUP_RUNTIME_ROOT_INVALID")
            shutil.rmtree(root)
            removed = True
        if record["kind"] in ("SELFDEV", "BOOTSTRAP"):
            request_path = runtime / (
                "gg-selfdev-request." + task_id.removeprefix("task-") + ".json"
            )
            if request_path.is_file() and not request_path.is_symlink():
                request_path.unlink()
        if self._task_ledger is not None:
            self._task_ledger.remove(task_id)
        self._selfdev_tasks.pop(task_id, None)
        self._autonomy_tasks.pop(task_id, None)
        return (
            "TASK_CLEANED="
            + task_id
            + "\nRUNTIME_REMOVED="
            + ("YES" if removed else "ALREADY_ABSENT")
            + "\nRECOVERABLE=NO"
        )

    def _resume_task(
        self,
        task_id: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> str:
        record = self._task_record(task_id)
        if record is None:
            raise RuntimeError("RESUME_TASK_NOT_FOUND")
        if record.get("kind") == "ACTION":
            return (
                "ACTION_REVALIDATION_REQUIRED="
                + task_id
                + "\nREPLAY=FORBIDDEN"
                + "\nNEW_TASK_ID=NONE"
            )
        status = str(record["status"])
        if status in control_contract.PENDING_STATUSES:
            return (
                "TASK_AT_EXPLICIT_BOUNDARY="
                + status
                + "\nNEXT_COMMAND="
                + self._next_task_step(record)
            )
        if status not in ("BLOCKED", "STOPPED_BY_USER", "CANCELLED"):
            return "TASK_NOT_RESUMABLE=" + status + "\nNEXT_COMMAND=" + self._next_task_step(record)
        if self._active():
            raise RuntimeError("ANOTHER_PROCESS_IS_ACTIVE")

        before = {
            str(item["task_id"])
            for item in (self._task_ledger.all() if self._task_ledger is not None else [])
        }
        if record["kind"] in ("SELFDEV", "BOOTSTRAP"):
            self._submit_selfdev(
                {
                    "action": "START",
                    "goal": str(record["goal"]),
                    "origin": str(record["kind"]),
                },
                context_reference,
                workspace_object_id,
            )
        else:
            self._submit_autonomy(
                {
                    "action": "START",
                    "goal": str(record["goal"]),
                    "test_mode": "NONE",
                    "parent_task_id": task_id,
                },
                context_reference,
                workspace_object_id,
            )
        after = {
            str(item["task_id"])
            for item in (self._task_ledger.all() if self._task_ledger is not None else [])
        }
        created = sorted(after - before)
        if len(created) != 1:
            raise RuntimeError("RESUME_DID_NOT_CREATE_EXACTLY_ONE_TASK")
        child = created[0]
        self._task_update(child, parent_task_id=task_id)
        return "RESUMED_FROM=" + task_id + "\nNEW_TASK_ID=" + child

    def _start_control_apply(
        self,
        parsed: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        if self._active():
            raise RuntimeError("ANOTHER_PROCESS_IS_ACTIVE")
        task_id = str(parsed["task_id"])
        record = self._task_record(task_id)
        if record is None or record["kind"] not in ("SELFDEV", "BOOTSTRAP"):
            raise RuntimeError("APPROVE_TASK_NOT_FOUND")
        if record["status"] != "WAITING_PERSISTENT_APPLY":
            raise RuntimeError("APPROVE_TASK_STATUS_INVALID:" + str(record["status"]))
        result = self._verified_selfdev_result(task_id)
        if parsed["candidate_sha256"] != result["candidate_sha256"]:
            raise RuntimeError("APPROVE_TASK_CANDIDATE_SHA_MISMATCH")
        if parsed["base_head"] != result["base_head"]:
            raise RuntimeError("APPROVE_TASK_BASE_HEAD_MISMATCH")

        request = control_contract.validate_apply_request(
            {
                "schema": control_contract.APPLY_REQUEST_SCHEMA,
                "action": "APPLY_SELFDEV",
                "task_id": task_id,
                "base_head": result["base_head"],
                "target_relative_path": SELFDEV_TARGET_REPO_RELATIVE,
                "before_sha256": result["before_sha256"],
                "candidate_sha256": result["candidate_sha256"],
                "diff_sha256": result["diff_sha256"],
            }
        )
        runtime = private_runtime_root()
        nonce = uuid.uuid4().hex[:24]
        evidence = runtime / ("gg-control-apply." + nonce)
        request_path = runtime / ("gg-control-apply-request." + nonce + ".json")
        evidence.mkdir(mode=0o700)
        fd = secure_open(
            request_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(control_contract.canonical_json(request))
            handle.flush()
            os.fsync(handle.fileno())

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-B",
                str(CONTROL_APPLY_RUNNER_PATH),
                "--apply-selfdev",
                str(evidence),
                str(request_path),
            ]
        )
        process.setWorkingDirectory(str(PROJECT))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._state = {
            "kind": "control-apply",
            "task_id": task_id,
            "context": context_reference,
            "workspace": workspace_object_id,
            "evidence": str(evidence),
            "request_path": str(request_path),
            "stoppable": "0",
        }
        self._process = process
        self._task_update(task_id, status="APPLYING", last_reason="")
        self._set_bridge_activity(True, task_id)
        self._append(
            "GG CONTROL",
            "APPLY",
            "EXACT_VERIFIED_MAIN_PY_APPLY startar.\nTASK_ID="
            + task_id
            + "\nATOMIC_CRITICAL_SECTION=NOT_STOPPABLE\nGIT_COMMIT_AUTHORITY=NONE",
            context_reference + " · " + workspace_object_id + " · " + task_id,
            "RUNNING",
            20,
        )
        process.finished.connect(self._control_apply_finished)
        process.start()
        if not process.waitForStarted(5000):
            reason = process.errorString()
            self._task_update(task_id, status="BLOCKED", last_reason=reason)
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")
            raise RuntimeError("CONTROL_APPLY_START_FAILED:" + reason)

    @Slot(int, QProcess.ExitStatus)
    def _control_apply_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state
        if process is None or state is None or state.get("kind") != "control-apply":
            return
        task_id = state["task_id"]
        request_path = Path(state["request_path"])
        evidence = Path(state["evidence"])
        try:
            request = control_contract.validate_apply_request(
                json.loads(request_path.read_text(encoding="utf-8"))
            )
            if exit_code != 0:
                reason = bytes(process.readAllStandardError()).decode(
                    "utf-8", errors="replace"
                )[-5000:]
                failure = evidence / "failure.json"
                if failure.is_file() and not failure.is_symlink():
                    try:
                        reason = str(
                            json.loads(failure.read_text(encoding="utf-8")).get(
                                "reason", reason
                            )
                        )
                    except Exception:
                        pass
                raise RuntimeError("CONTROL_APPLY_EXIT:" + str(exit_code) + ":" + reason)
            response_path = evidence / "response.json"
            if response_path.is_symlink() or not response_path.is_file():
                raise RuntimeError("CONTROL_APPLY_RESPONSE_MISSING")
            response = control_contract.validate_apply_response(
                json.loads(response_path.read_text(encoding="utf-8")),
                request,
            )

            try:
                self._resident_information_state.ingest_verified_control_apply(
                    request,
                    response,
                )
            except Exception as exc:
                raise resident_state.ResidentInformationStateError(
                    "HOST_EFFECT_VERIFIED_BUT_RESIDENT_INFORMATION_STATE_BLOCKED:"
                    + type(exc).__name__
                    + ":"
                    + str(exc)
                ) from exc

            self._task_update(task_id, status="DONE", last_reason="APPLIED_VERIFIED")
            self._append(
                "GG CONTROL",
                "APPLY",
                str(response["output"])
                + "\nTASK_ID="
                + task_id
                + "\nHOST_AFTER_SHA256="
                + str(response["host_after_sha256"])
                + "\nRESTART_REQUIRED=YES",
                state["context"] + " · " + state["workspace"] + " · " + task_id,
                "PASS",
                20,
            )
        except Exception as exc:
            self._task_update(
                task_id,
                status="BLOCKED",
                last_reason=type(exc).__name__ + ":" + str(exc),
            )
            self._append(
                "GG SYSTEM",
                "CONTROL",
                (
                    "Host-effect verifierad, men resident informationsstate blockerades: "
                    + str(exc)
                    if isinstance(
                        exc,
                        resident_state.ResidentInformationStateError,
                    )
                    else (
                        "Verified task apply stoppade säkert: "
                        + str(exc)
                    )
                ),
                state["context"] + " · " + state["workspace"] + " · " + task_id,
                "BLOCKED",
                20,
            )
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass
            process.deleteLater()
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")

    def _submit_control(
        self,
        parsed: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        action = str(parsed["action"])
        try:
            if action == "HELP":
                output = control_contract.help_text()
            elif action == "STATUS":
                output = self._control_status(str(parsed["task_id"]))
            elif action == "TASKS":
                output = self._control_tasks()
            elif action == "STOP":
                self._stop_active(
                    str(parsed["task_id"]),
                    context_reference,
                    workspace_object_id,
                )
                return
            elif action == "INSPECT":
                task_id = str(parsed["task_id"])
                output = self._control_status(task_id)
            elif action == "LOGS":
                task_id = str(parsed["task_id"])
                record = self._task_record(task_id)
                if record is None:
                    raise RuntimeError("LOG_TASK_NOT_FOUND")
                logs = list(record["logs"])[-int(parsed["tail"]):]
                output = (
                    "TASK_ID="
                    + task_id
                    + "\nLOG_LINES="
                    + str(len(logs))
                    + "\n"
                    + ("\n".join(str(line) for line in logs) if logs else "(no ledger lines)")
                )
            elif action == "DIFF":
                output = self._control_diff(str(parsed["task_id"]))
            elif action == "DOCTOR":
                output = self._control_doctor()
            elif action == "CONTEXT":
                output = self._control_context(context_reference, workspace_object_id)
            elif action == "BOOTSTRAP":
                if self._active():
                    raise RuntimeError("ANOTHER_PROCESS_IS_ACTIVE")
                before = {
                    str(item["task_id"])
                    for item in (
                        self._task_ledger.all() if self._task_ledger is not None else []
                    )
                }
                self._submit_selfdev(
                    {
                        "action": "START",
                        "goal": str(parsed["goal"]),
                        "origin": "BOOTSTRAP",
                    },
                    context_reference,
                    workspace_object_id,
                )
                after = {
                    str(item["task_id"])
                    for item in (
                        self._task_ledger.all() if self._task_ledger is not None else []
                    )
                }
                created = sorted(after - before)
                if len(created) != 1:
                    raise RuntimeError("BOOTSTRAP_DID_NOT_CREATE_EXACTLY_ONE_TASK")
                return
            elif action == "RESUME":
                output = self._resume_task(
                    str(parsed["task_id"]),
                    context_reference,
                    workspace_object_id,
                )
            elif action == "REJECT_TASK":
                if self._active():
                    raise RuntimeError("ANOTHER_PROCESS_IS_ACTIVE")
                output = self._reject_task(
                    str(parsed["task_id"]),
                    str(parsed["candidate_sha256"]),
                )
            elif action == "CLEANUP":
                output = self._cleanup_task(str(parsed["task_id"]))
            elif action == "APPROVE_TASK":
                self._start_control_apply(
                    parsed,
                    context_reference,
                    workspace_object_id,
                )
                return
            else:
                raise RuntimeError("CONTROL_ACTION_INVALID:" + action)

            self._append(
                "GG CONTROL",
                action,
                output,
                context_reference + " · " + workspace_object_id,
                "PASS",
                20,
            )
        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "CONTROL",
                "Control command blockerad: " + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )

    def _submit_resident_prompt(self, prompt, context_reference, workspace_object_id, workspace_context):
        request = contract.validate_request({"schema": contract.REQUEST_SCHEMA, "request_id": "chat-" + uuid.uuid4().hex, "mode": "CHAT", "prompt": prompt})
        try:
            self._resident_chat.submit(request, context_reference, workspace_object_id, workspace_context)
        except Exception as exc:
            self._set_bridge_activity(False, "")
            self._append("GG SYSTEM", "RESPONSE", "Resident chat start stoppade säkert: " + type(exc).__name__ + ":" + str(exc), context_reference + " · " + workspace_object_id, "FAIL", 28)

    @Slot(str, str, str)
    def submit(
        self,
        text: str,
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        value = text.strip()

        if not value:
            return

        if self._dispatch_visual_command(
            value,
            context_reference=context_reference,
            workspace_object_id=workspace_object_id,
        ):
            return

        try:
            control_request = control_contract.parse_control_command(value)
        except control_contract.ControlContractError as exc:
            self._append(
                "GG SYSTEM",
                "CONTROL",
                str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if control_request is not None:
            self._submit_control(
                control_request,
                context_reference,
                workspace_object_id,
            )
            return

        chat_approval = parse_chat_approval(value)
        if chat_approval is not None:
            if self._submit_bare_chat_approval(
                chat_approval,
                context_reference,
                workspace_object_id,
            ):
                return
            # Without a matching local approval, this is ordinary
            # conversation. The native TUI normally bypasses this method,
            # but the composer uses it directly and must not silently drop a
            # perfectly valid answer such as "ja".

        if self._resume_chat_native_task(
            value,
            context_reference,
            workspace_object_id,
        ):
            return

        if self._active():
            if self._resident_chat.accept_followup(value, context_reference, workspace_object_id):
                return
            self._append(
                "GG SYSTEM",
                "MODEL",
                "BUSY",
                context_reference,
                "WAITING",
                28,
            )
            return

        # Every concrete action written in ordinary chat is a chat-native
        # task. Capture it before engine dispatch or local source routing so
        # the same ja/nej flow covers local writes as well as production,
        # one.com, network and other external effects.
        early_chat_scope = parse_chat_action_request(value)
        if early_chat_scope is not None:
            self._shutdown_resident_idle_for_task()
            try:
                self._capture_chat_native_mandate(
                    user_text=value,
                    chat_scope=early_chat_scope,
                    workspace_context=_chat_identity_workspace_context(
                        workspace_object_id
                    ),
                    context_reference=context_reference,
                    workspace_object_id=workspace_object_id,
                )
            except Exception as exc:
                self._append(
                    "GG SYSTEM",
                    "MANDATE",
                    "Chatmandat kunde inte skapas: "
                    + type(exc).__name__
                    + ":"
                    + str(exc),
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    26,
                )
            return

        try:
            engine_target = normalize_engine_target(self._root.property("engineTarget"))
        except GrokWorkerContractError as exc:
            self._append("GG SYSTEM", "MODEL", str(exc), context_reference + " · " + workspace_object_id, "FAIL", 20)
            return
        if engine_target == ENGINE_GROK_WORKER or engine_target == ENGINE_GROK_TUI:
            self._submit_resident_prompt(value, context_reference, workspace_object_id, {})
            return

        try:
            selfdev_request = parse_selfdev_command(value)
            if selfdev_request is not None:
                self._resident_chat.shutdown_idle()
                self._submit_selfdev(
                    selfdev_request,
                    context_reference,
                    workspace_object_id,
                )
                return
            autonomy_request = parse_autonomy_command(value)
        except ValueError as exc:
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if autonomy_request is not None:
            self._resident_chat.shutdown_idle()
            self._submit_autonomy(
                autonomy_request,
                context_reference,
                workspace_object_id,
            )
            return

        try:
            write_request = parse_write_command(value)
        except ValueError as exc:
            self._append(
                "GG SYSTEM",
                "WRITE",
                str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if write_request is not None:
            self._resident_chat.shutdown_idle()
            self._submit_write(
                write_request,
                context_reference,
                workspace_object_id,
            )
            return
        try:
            mandate_request = parse_mandate_command(value)
        except ValueError as exc:
            self._append(
                "GG SYSTEM",
                "MANDATE",
                str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if mandate_request is not None:
            self._resident_chat.shutdown_idle()
            self._submit_mandate(
                mandate_request,
                context_reference,
                workspace_object_id,
            )
            return

        try:
            tool_request = parse_safe_tool_command(value)
        except ValueError as exc:
            self._append(
                "GG SYSTEM",
                "TOOL",
                str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if tool_request is None:
            from backend.surface_intent import parse_surface_intent
            if not parse_surface_intent(value):
                spec = WORKSPACE_CONTEXTS.get(workspace_object_id)
                rel = "" if spec is None else str(spec.get("relative_path") or "")
                tool_request = parse_natural_safe_tool_command(
                    value,
                    "" if not rel else "projects/gg-ai-desktop/" + rel,
                )
        if tool_request is not None:
            self._resident_chat.shutdown_idle()
            self._submit_tool(
                tool_request,
                context_reference,
                workspace_object_id,
            )
            return

        try:
            effective_prompt, workspace_context = self._resolved_chat_context(
                value,
                context_reference,
                workspace_object_id,
            )
            (
                route_decision,
                _route_error,
            ) = self._natural_intent_route(
                value,
                workspace_context,
                workspace_object_id,
            )
            action_proposal = self._natural_action_proposal(
                route_decision,
                workspace_context,
            )
            chat_scope = parse_chat_action_request(value)

        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "CONTEXT",
                "@current kunde inte lösas till verifierad lokal data: "
                + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if chat_scope is not None and (
            bool(chat_scope.get("external")) or action_proposal is None
        ):
            try:
                self._shutdown_resident_idle_for_task()
                self._capture_chat_native_mandate(
                    user_text=value,
                    chat_scope=chat_scope,
                    workspace_context=workspace_context,
                    context_reference=context_reference,
                    workspace_object_id=workspace_object_id,
                )
            except Exception as exc:
                self._append(
                    "GG SYSTEM",
                    "MANDATE",
                    "Chatmandat kunde inte skapas: "
                    + type(exc).__name__
                    + ":"
                    + str(exc),
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    26,
                )
            return

        try:
            if not self._machine_graph_edge_enabled(
                "call-12"
            ):
                raise machine_graph.MachineGraphError(
                    "MACHINE_GRAPH_EDGE_DISABLED:call-12"
                )

            idekompass_result = idekompass_decision_ingress.decide(
                user_text=value,
                workspace_context=workspace_context,
                route_decision=route_decision,
                information_available=True,
                assigned_participant=(
                    self._orchestrator_assigned_participant
                    or None
                ),
                creator_actor=(
                    self._orchestrator_creator_actor
                    or None
                ),
                action_proposal=action_proposal,
            )
        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "IDEKOMPASS",
                "Read-only Idékompass blocked · " + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if action_proposal is not None:
            effective_prompt += idekompass_result["prompt_extension"]

        if idekompass_result["decision_kind"] == "STOP_UNCERTAINTY":
            self._append(
                "GG SYSTEM",
                "IDEKOMPASS",
                "Cognitive uncertainty stop · reason="
                + idekompass_result["reason_code"],
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                24,
            )
            return

        if action_proposal is None:
            mandate_evaluation = {
                "status": "NOT_APPLICABLE",
                "ordinary_chat_blocked": False,
            }
        else:
            mandate_evaluation = (
                orchestrator_mandate_evaluation_adapter.evaluate_not_required(
                    idekompass_result["orchestrator_mandate"]
                )
            )
        mandate_status = str(mandate_evaluation["status"])

        if mandate_status == "DEFERRED":
            if (
                mandate_evaluation.get("reason_code")
                != "MANDATE_REQUIRED_VERIFIED"
            ):
                self._append(
                    "GG SYSTEM",
                    "MANDATE",
                    "Unexpected deferred mandate state - "
                    + str(mandate_evaluation.get("reason_code")),
                    context_reference + " - " + workspace_object_id,
                    "BLOCKED",
                    26,
                )
                return

            action_intent = idekompass_result.get("action_intent")
            if not isinstance(action_intent, dict):
                self._append(
                    "GG SYSTEM",
                    "MANDATE",
                    "Explicit mandate required without bound Action Intent.",
                    context_reference + " - " + workspace_object_id,
                    "BLOCKED",
                    26,
                )
                return

            self._capture_pending_mandate(
                mandate_result=idekompass_result["orchestrator_mandate"],
                action_intent=action_intent,
                user_text=value,
                route_decision=route_decision,
                context_reference=context_reference,
                workspace_object_id=workspace_object_id,
            )
            return

        if mandate_status == "BLOCKED":
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "K7-K evaluation blocked - "
                + str(mandate_evaluation["reason_code"])
                + " - action authority NONE"
                + " - controlled tool execution NO",
                context_reference + " - " + workspace_object_id,
                "BLOCKED",
                26,
            )
            return

        if mandate_status == "EVALUATED":
            receipt = mandate_evaluation.get("evaluation_receipt")
            if not isinstance(receipt, dict):
                self._append(
                    "GG SYSTEM",
                    "MANDATE",
                    "K7-K evaluation receipt missing - action authority NONE",
                    context_reference + " - " + workspace_object_id,
                    "BLOCKED",
                    26,
                )
                return
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "K7-K evaluation - result="
                + str(receipt["result"])
                + " - reason="
                + str(receipt["reason_code"])
                + " - action authority NONE"
                + " - controlled tool execution NO",
                context_reference + " - " + workspace_object_id,
                "PASS",
                26,
            )
        elif mandate_status != "NOT_APPLICABLE":
            self._append(
                "GG SYSTEM",
                "MANDATE",
                "Unexpected mandate evaluation status - "
                + mandate_status
                + " - action authority NONE",
                context_reference + " - " + workspace_object_id,
                "BLOCKED",
                26,
            )
            return

        participant_prepared = None

        if self._orchestrator_assigned_participant:
            try:
                participant_prepared = (
                    participant_task_receiver.prepare_participant_execution(
                        idekompass_result=idekompass_result,
                        effective_prompt=effective_prompt,
                        user_text=value,
                        workspace_context=workspace_context,
                    )
                )
                effective_prompt = str(participant_prepared["prompt"])
            except participant_task_receiver.ParticipantTaskError as exc:
                self._append(
                    "GG SYSTEM",
                    "PARTICIPANT",
                    "Blocked: " + str(exc),
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    28,
                )
                return

        if participant_prepared is None:
            self._submit_resident_prompt(
                prompt_for_resident_engine(
                    value,
                    effective_prompt,
                    engine_target,
                ),
                context_reference,
                workspace_object_id,
                workspace_context,
            )
            return

        if engine_target == ENGINE_GPT_TUI:
            # Participant handoff prompts are compiled for the host-side
            # worker path. GPTUI must still receive only a normal-sized user
            # turn because its shared profile is already hidden at session
            # startup.
            effective_prompt = value

        request_id = "chat-" + uuid.uuid4().hex
        request = contract.validate_request({"schema": contract.REQUEST_SCHEMA, "request_id": request_id, "mode": "CHAT", "prompt": effective_prompt})
        self._resident_chat.shutdown_idle()
        runtime_root = private_runtime_root()
        nonce = uuid.uuid4().hex[:24]
        evidence = runtime_root / f"gg-wb3d-model-runner.{nonce}"
        request_path = runtime_root / f"gg-workbench-chat-request.{nonce}.json"
        evidence.mkdir(mode=0o700, exist_ok=False)
        request_bytes = (contract.canonical_request_json(request) + "\n").encode("utf-8")
        fd = secure_open(request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(request_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        render = discover_nvidia_render()
        self._append(
            "GG SYSTEM",
            "MODEL",
            "Lokal modell arbetar med verifierad @current read-only context · "
            + str(workspace_context["source_path"])
            + " · sha256 "
            + str(workspace_context["sha256"])[:12]
            + "… · network none · inga verktyg eller writes.",
            context_reference + " · " + workspace_object_id,
            "GENERATING",
            28,
        )
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-B",
                str(CHAT_RUNNER_PATH),
                "--execute-chat",
                str(evidence),
                str(render),
                str(request_path),
            ]
        )
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

        self._state = {
            "kind": "model",
            "request_id": request_id,
            "context": context_reference,
            "workspace": workspace_object_id,
            "workspace_source": str(workspace_context["source_path"]),
            "workspace_sha256": str(workspace_context["sha256"]),
            "evidence": str(evidence),
            "request_path": str(request_path),
            "stoppable": "1",
        }

        if participant_prepared is not None:
            self._state["participant_task"] = participant_task_receiver.canonical_state_json(participant_prepared["state"])

        self._process = process
        self._set_bridge_activity(True, request_id)
        process.finished.connect(self._finished)
        process.start()

        if not process.waitForStarted(5000):
            reason = process.errorString()

            try:
                request_path.unlink()
            except OSError:
                pass

            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")
            self._append(
                "GG SYSTEM",
                "MODEL",
                "Local Chat Bridge kunde inte starta runnern: " + reason,
                context_reference,
                "FAIL",
                28,
            )

    def _submit_selfdev(
        self,
        parsed: dict[str, str],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        if (
            self._process is not None
            and self._process.state()
            != QProcess.ProcessState.NotRunning
        ):
            self._append(
                "GG SYSTEM",
                "SELFDEV",
                "Workbench har redan ett aktivt lokalt arbete.",
                context_reference + " · " + workspace_object_id,
                "WAITING",
                20,
            )
            return

        process: QProcess | None = None
        task_id = ""
        task_kind = parsed.get("origin", "SELFDEV")

        if task_kind not in ("SELFDEV", "BOOTSTRAP"):
            self._append(
                "GG SYSTEM",
                "SELFDEV",
                "Selfdev origin profile invalid.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        try:
            repo = _selfdev_repo_root()

            head = _selfdev_git(
                repo,
                "rev-parse",
                "HEAD",
            ).decode("ascii").strip()

            _selfdev_state_lock(repo, head)

            target = _selfdev_host_target(repo)
            before = target.read_bytes()

            task_id = "task-" + uuid.uuid4().hex

            request = _selfdev_validate_request(
                {
                    "schema": "gg.workbench.selfdev-request.v1",
                    "task_id": task_id,
                    "goal": parsed["goal"],
                    "base_head": head,
                    "target_relative_path": SELFDEV_TARGET_REPO_RELATIVE,
                    "target_sha256": _selfdev_sha256(before),
                }
            )

            request_path = (
                _selfdev_runtime()
                / (
                    "gg-selfdev-request."
                    + task_id.removeprefix("task-")
                    + ".json"
                )
            )

            if request_path.exists():
                raise SelfdevBridgeError("REQUEST_COLLISION")

            fd = secure_open(
                request_path,
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | NOFOLLOW
                ),
                0o600,
            )

            with os.fdopen(fd, "wb") as handle:
                handle.write(
                    _selfdev_canonical(request)
                )
                handle.flush()
                os.fsync(handle.fileno())

            self._selfdev_tasks[task_id] = {
                "request": request,
                "request_path": str(request_path),
                "status": "RUNNING",
                "last_event_seq": 0,
                "kind": task_kind,
            }
            self._task_create(
                task_id,
                task_kind,
                "RUNNING",
                parsed["goal"],
                context_reference,
                workspace_object_id,
                base_head=head,
            )

            self._append(
                "GG SELFDEV",
                "WORK",
                (
                    "SELFDEV_MAIN_PY_V1 startar.\n"
                    "TARGET: projects/gg-ai-desktop/main.py\n"
                    "CANDIDATE: task-bound runtime\n"
                    "HOST WRITE: NONE\n"
                    "NETWORK: NONE"
                ),
                (
                    context_reference
                    + " · "
                    + workspace_object_id
                    + " · "
                    + task_id
                ),
                "RUNNING",
                0,
            )

            process = QProcess(self)

            process.setProgram(sys.executable)

            process.setArguments(
                [
                    "-B",
                    str(Path(__file__).resolve()),
                    SELFDEV_CONTROLLER_MODE,
                    str(request_path),
                ]
            )

            process.setWorkingDirectory(
                str(Path(__file__).resolve().parent)
            )

            process.setProcessChannelMode(
                QProcess.SeparateChannels
            )

            self._process = process
            self._state = {
                "kind": "selfdev",
                "task_id": task_id,
                "context": context_reference,
                "workspace": workspace_object_id,
                "request_path": str(request_path),
                "stoppable": "1",
            }
            self._set_bridge_activity(True, task_id)

            self._selfdev_stdout_buffer = ""

            process.readyReadStandardOutput.connect(
                self._selfdev_stdout_ready
            )

            process.finished.connect(
                self._selfdev_finished
            )

            process.start()

            if not process.waitForStarted(5000):
                raise RuntimeError(
                    "Selfdev controller kunde inte starta: "
                    + process.errorString()
                )

        except Exception as exc:
            if process is not None:
                try:
                    process.kill()
                except Exception:
                    pass

            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")

            if task_id and self._task_record(task_id) is not None:
                self._task_update(
                    task_id,
                    status="BLOCKED",
                    last_reason=type(exc).__name__ + ":" + str(exc),
                )

            self._append(
                "GG SYSTEM",
                "SELFDEV",
                "Selfdev start stoppade säkert: " + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )

    @Slot()
    def _selfdev_stdout_ready(self) -> None:
        process = self._process
        state = self._state

        if process is None or state is None:
            return

        if state.get("kind") != "selfdev":
            return

        chunk = bytes(
            process.readAllStandardOutput()
        ).decode(
            "utf-8",
            errors="replace",
        )

        self._selfdev_stdout_buffer += chunk

        if (
            len(
                self._selfdev_stdout_buffer.encode("utf-8")
            )
            > 131072
        ):
            self._selfdev_stdout_buffer = ""

            self._append(
                "GG SYSTEM",
                "SELFDEV",
                "Selfdev event stream exceeded buffer.",
                state["context"] + " · " + state["workspace"],
                "BLOCKED",
                20,
            )
            return

        while "\n" in self._selfdev_stdout_buffer:
            line, self._selfdev_stdout_buffer = (
                self._selfdev_stdout_buffer.split("\n", 1)
            )

            prefix = "GG_SELFDEV_EVENT="

            if not line.startswith(prefix):
                continue

            try:
                event = json.loads(line[len(prefix):])

                if set(event) != {
                    "schema",
                    "step_seq",
                    "phase",
                    "state",
                    "text",
                }:
                    raise ValueError("event fields invalid")

                if (
                    event["schema"]
                    != "gg.workbench.selfdev-event.v1"
                ):
                    raise ValueError("event schema invalid")

                if (
                    type(event["step_seq"]) is not int
                    or event["step_seq"] < 1
                ):
                    raise ValueError("event sequence invalid")

                if (
                    type(event["phase"]) is not str
                    or type(event["state"]) is not str
                    or type(event["text"]) is not str
                    or len(event["text"]) > 4096
                ):
                    raise ValueError("event payload invalid")

                task_id = state["task_id"]
                task = self._selfdev_tasks.get(task_id)

                if task is None:
                    raise ValueError("task missing")

                previous = int(task.get("last_event_seq", 0))

                if event["step_seq"] <= previous:
                    raise ValueError("event replay")

                task["last_event_seq"] = event["step_seq"]

                self._append(
                    "GG SELFDEV",
                    str(event["phase"]),
                    str(event["text"]),
                    (
                        state["context"]
                        + " · "
                        + state["workspace"]
                        + " · "
                        + task_id
                    ),
                    str(event["state"]),
                    0,
                )

            except Exception as exc:
                self._append(
                    "GG SYSTEM",
                    "SELFDEV",
                    (
                        "Selfdev event validation failed: "
                        + str(exc)
                    ),
                    state["context"] + " · " + state["workspace"],
                    "BLOCKED",
                    20,
                )

    @Slot(int, QProcess.ExitStatus)
    def _selfdev_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state

        if (
            process is None
            or state is None
            or state.get("kind") != "selfdev"
        ):
            return

        self._selfdev_stdout_ready()

        task_id = state["task_id"]
        task = self._selfdev_tasks.get(task_id)

        try:
            if task is None:
                raise RuntimeError("Selfdev task missing.")

            if state.get("stop_requested") == "1":
                self._mark_stopped(state)
                return

            if exit_code != 0:
                stderr = bytes(
                    process.readAllStandardError()
                ).decode(
                    "utf-8",
                    errors="replace",
                )

                raise RuntimeError(
                    "selfdev controller exit "
                    + str(exit_code)
                    + ": "
                    + stderr[-5000:]
                )

            result_path = (
                _selfdev_runtime()
                / (
                    "gg-selfdev-task."
                    + task_id.removeprefix("task-")
                )
                / "verified-result.json"
            )

            if result_path.is_symlink() or not result_path.is_file():
                raise RuntimeError("Selfdev result missing.")

            result = json.loads(
                result_path.read_text(encoding="utf-8")
            )

            required = {
                "schema",
                "task_id",
                "base_head",
                "target_relative_path",
                "before_sha256",
                "candidate_sha256",
                "diff_sha256",
                "foundation_gate_report_sha256",
                "candidate_write_count",
                "model_call_count",
                "host_repo_changed",
                "persistent_selfdev_write",
                "status",
            }

            if set(result) != required:
                raise RuntimeError("Selfdev result fields invalid.")

            if (
                result["schema"]
                != "gg.workbench.selfdev-result.v1"
                or result["task_id"] != task_id
                or result["target_relative_path"]
                != SELFDEV_TARGET_REPO_RELATIVE
                or result["host_repo_changed"] is not False
                or result["persistent_selfdev_write"] != "NONE"
                or result["status"]
                != "WAITING_PERSISTENT_APPLY"
            ):
                raise RuntimeError("Selfdev result contract invalid.")

            task["status"] = "WAITING_PERSISTENT_APPLY"
            task["candidate_sha256"] = result["candidate_sha256"]
            task["diff_sha256"] = result["diff_sha256"]
            self._task_update(
                task_id,
                status="WAITING_PERSISTENT_APPLY",
                base_head=str(result["base_head"]),
                candidate_sha256=str(result["candidate_sha256"]),
                diff_sha256=str(result["diff_sha256"]),
                last_reason="",
            )

            self._append(
                "GG SELFDEV",
                "RESULT",
                (
                    "VERIFIED CHANGESET klart.\n"
                    "TARGET: projects/gg-ai-desktop/main.py\n"
                    "CANDIDATE_SHA256: "
                    + str(result["candidate_sha256"])
                    + "\nDIFF_SHA256: "
                    + str(result["diff_sha256"])
                    + "\nHOST_REPO_CHANGED: NO\n"
                    "PERSISTENT_SELFDEV_WRITE: NONE\n"
                    "STATUS: WAITING_PERSISTENT_APPLY"
                ),
                (
                    state["context"]
                    + " · "
                    + state["workspace"]
                    + " · "
                    + task_id
                ),
                "WAITING_FOR_USER",
                0,
            )

        except Exception as exc:
            if task is not None:
                task["status"] = "BLOCKED"
            self._task_update(
                task_id,
                status="BLOCKED",
                last_reason=type(exc).__name__ + ":" + str(exc),
            )

            self._append(
                "GG SYSTEM",
                "SELFDEV",
                "Selfdev stoppade säkert: " + str(exc),
                state["context"] + " · " + state["workspace"],
                "BLOCKED",
                20,
            )

        finally:
            process.deleteLater()
            self._process = None
            self._state = None
            self._selfdev_stdout_buffer = ""
            self._set_bridge_activity(False, "")

    def _submit_autonomy(
        self,
        parsed: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        action = str(parsed["action"])

        if (
            context_reference != autonomy_contract.TARGET_CONTEXT_REFERENCE
            or workspace_object_id
            != autonomy_contract.TARGET_WORKSPACE_OBJECT_ID
        ):
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy v1 är endast bunden till verklig @current "
                "ContextComposer.qml. Ingen multi-target authority är aktiverad.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if action == "START":
            try:
                workspace = resolve_workspace_context(workspace_object_id)
                if workspace["source_path"] != autonomy_contract.TARGET_RELATIVE_PATH:
                    raise RuntimeError("Autonomy target path binding mismatch.")
                base_head = current_clean_head()
                task_id = "task-" + uuid.uuid4().hex
                grant = autonomy_contract.validate_grant(
                    {
                        "schema": autonomy_contract.GRANT_SCHEMA,
                        "task_id": task_id,
                        "session_id": self._autonomy_session_id,
                        "base_head": base_head,
                        "context_reference": context_reference,
                        "workspace_object_id": workspace_object_id,
                        "target_relative_path":
                            autonomy_contract.TARGET_RELATIVE_PATH,
                        "goal": str(parsed["goal"]),
                        "done_when": (
                            "Final task candidate must match one exact "
                            "single-occurrence replacement, QML Gate must PASS, "
                            "host repo must remain unchanged until separate "
                            "Limited Write approval, and after that approval the "
                            "real target SHA-256 must match the verified candidate."
                        ),
                        "allowed_green_tools":
                            list(autonomy_contract.ALLOWED_GREEN_TOOLS),
                        "max_steps": 24,
                        "max_model_calls": 3,
                        "max_candidate_writes": 3,
                        "max_candidate_bytes":
                            autonomy_contract.TARGET_MAX_BYTES,
                        "network_authority": "NONE",
                        "general_action_authority": "NONE",
                        "host_write_authority":
                            autonomy_contract.HOST_WRITE_AUTHORITY,
                        "git_mutation_authority": "NONE",
                        "shell_authority": "NONE",
                        "self_authorization": "FORBIDDEN",
                        "authority_file_mutation": "FORBIDDEN",
                        "model_output_authority":
                            "UNTRUSTED_MODEL_OUTPUT",
                        "candidate_workspace": "RUNTIME_TASK_BOUND",
                        "session_bound": True,
                        "replay_protection":
                            "RUNTIME_SINGLE_USE_RECEIPT",
                        "monotonic_step_sequence": True,
                        "persistent_apply_boundary":
                            autonomy_contract.PERSISTENT_APPLY_BOUNDARY,
                        "test_mode": str(parsed["test_mode"]),
                    }
                )
                grant_sha = autonomy_contract.grant_sha256(grant)
            except Exception as exc:
                self._append(
                    "GG SYSTEM",
                    "AUTONOMY",
                    "Autonomy task proposal blockerad: " + str(exc),
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    20,
                )
                return

            self._autonomy_tasks[task_id] = {
                "grant": grant,
                "grant_sha256": grant_sha,
                "status": "WAITING_GRANT",
                "last_event_seq": 0,
                "workspace_sha256": str(workspace["sha256"]),
            }
            try:
                self._task_create(
                    task_id,
                    "AUTONOMY",
                    "WAITING_GRANT",
                    str(parsed["goal"]),
                    context_reference,
                    workspace_object_id,
                    base_head=base_head,
                    grant_sha256=grant_sha,
                    parent_task_id=str(parsed.get("parent_task_id", "")),
                )
            except Exception as exc:
                self._autonomy_tasks.pop(task_id, None)
                self._append(
                    "GG SYSTEM",
                    "AUTONOMY",
                    "Autonomy task ledger blockerad: " + str(exc),
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    20,
                )
                return
            approval_command = (
                "/approve-autonomy "
                + task_id
                + " "
                + grant_sha
            )
            self._append(
                "GG AUTONOMY",
                "GRANT",
                (
                    "Task proposal klar utan write eller model inference.\n"
                    "ORIGINAL_INTENT: "
                    + str(parsed["goal"])
                    + "\n"
                    "TARGET: @current · "
                    + workspace_object_id
                    + " · "
                    + str(workspace["source_path"])
                    + "\n"
                    "BASE_HEAD: "
                    + base_head
                    + "\n"
                    "TASK_AUTHORITY: "
                    + autonomy_contract.AUTHORITY
                    + "\n"
                    "CANDIDATE_WORKSPACE: runtime task-bound\n"
                    "HOST_WRITE: NONE före separat Limited Write approval\n"
                    "NETWORK: NONE · GENERAL ACTION: NONE · SELF-AUTHORIZATION: FORBIDDEN\n"
                    "TEST_MODE: "
                    + str(parsed["test_mode"])
                    + "\n"
                    "GRANT_SHA256: "
                    + grant_sha
                    + "\n\nGodkänn exakt med:\n"
                    + approval_command
                ),
                context_reference + " · " + workspace_object_id,
                "WAITING_FOR_USER",
                28,
            )
            return

        task_id = str(parsed["task_id"])
        grant_sha = str(parsed["grant_sha256"])
        task = self._autonomy_tasks.get(task_id)

        if task is None:
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy task finns inte i denna Workbench-session.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if (
            task.get("status") != "WAITING_GRANT"
            or task.get("grant_sha256") != grant_sha
        ):
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy grant är stale, redan använd eller hash-mismatch.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        grant = autonomy_contract.validate_grant(task["grant"])

        if grant["session_id"] != self._autonomy_session_id:
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy grant är inte bunden till aktuell Workbench-session.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        if action == "CANCEL":
            task["status"] = "CANCELLED"
            self._task_update(
                task_id,
                status="CANCELLED",
                last_reason="OPERATOR_CANCELLED_BEFORE_CANDIDATE_WRITE",
            )
            self._append(
                "GG AUTONOMY",
                "CANCEL",
                "Autonomy task avbruten före candidate write. Host repo orört.",
                context_reference + " · " + workspace_object_id,
                "CANCELLED",
                20,
            )
            return

        if action != "APPROVE":
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Unsupported autonomy action.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        task_root: Path | None = None

        try:
            if current_clean_head() != grant["base_head"]:
                raise RuntimeError("Autonomy base HEAD changed before approval.")

            workspace = resolve_workspace_context(workspace_object_id)
            if workspace["sha256"] != task["workspace_sha256"]:
                raise RuntimeError(
                    "Autonomy target changed after grant proposal; grant is stale."
                )

            runtime_root = private_runtime_root()
            task_root = runtime_root / (
                "gg-autonomy-task."
                + task_id.removeprefix("task-")
            )
            if task_root.exists() or task_root.is_symlink():
                raise RuntimeError("Autonomy task runtime path already exists.")
            task_root.mkdir(mode=0o700)

            render = discover_nvidia_render()
            request = autonomy_contract.validate_request(
                {
                    "schema": autonomy_contract.REQUEST_SCHEMA,
                    "request_id": "autonomy-" + uuid.uuid4().hex,
                    "grant": grant,
                    "grant_sha256": grant_sha,
                    "render_node": str(render),
                }
            )
            request_path = task_root / "request.json"
            fd = secure_open(
                request_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(autonomy_contract.canonical_json(request))
                handle.flush()
                os.fsync(handle.fileno())

            task["status"] = "RUNNING"
            task["task_root"] = str(task_root)
            task["request_path"] = str(request_path)
            task["last_event_seq"] = 0
            self._task_update(task_id, status="RUNNING", last_reason="")

            self._append(
                "GG AUTONOMY",
                "START",
                (
                    "Task grant accepterad · "
                    + autonomy_contract.AUTHORITY
                    + " · candidate writes får endast ske i session-bunden runtime · "
                    "host write kräver separat approval."
                ),
                context_reference + " · " + workspace_object_id + " · " + task_id,
                "RUNNING",
                28,
            )

            process = QProcess(self)
            process.setProgram(sys.executable)
            process.setArguments(
                [
                    "-B",
                    str(AUTONOMY_CONTROLLER_PATH),
                    "--execute",
                    str(task_root),
                    str(request_path),
                ]
            )
            process.setProcessChannelMode(
                QProcess.ProcessChannelMode.SeparateChannels
            )
            self._state = {
                "kind": "autonomy",
                "task_id": task_id,
                "context": context_reference,
                "workspace": workspace_object_id,
                "task_root": str(task_root),
                "stoppable": "1",
            }
            self._process = process
            self._set_bridge_activity(True, task_id)
            self._autonomy_stdout_buffer = ""
            process.readyReadStandardOutput.connect(
                self._autonomy_stdout_ready
            )
            process.finished.connect(self._autonomy_finished)
            process.start()

            if not process.waitForStarted(5000):
                raise RuntimeError(
                    "Autonomy controller kunde inte starta: "
                    + process.errorString()
                )

        except Exception as exc:
            task["status"] = "BLOCKED"
            self._task_update(
                task_id,
                status="BLOCKED",
                last_reason=type(exc).__name__ + ":" + str(exc),
            )
            if (
                task_root is not None
                and task_root.is_dir()
                and not task_root.is_symlink()
            ):
                try:
                    shutil.rmtree(task_root)
                except OSError:
                    pass
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy start stoppade säkert: " + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )

    @Slot()
    def _autonomy_stdout_ready(self) -> None:
        process = self._process
        state = self._state
        if process is None or state is None:
            return
        if state.get("kind") not in ("autonomy", "autonomy-verify"):
            return

        chunk = bytes(
            process.readAllStandardOutput()
        ).decode("utf-8", errors="replace")
        self._autonomy_stdout_buffer += chunk

        if len(self._autonomy_stdout_buffer.encode("utf-8")) > 65536:
            self._autonomy_stdout_buffer = ""
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy event stream exceeded UI buffer limit.",
                state["context"] + " · " + state["workspace"],
                "BLOCKED",
                20,
            )
            return

        while "\n" in self._autonomy_stdout_buffer:
            line, self._autonomy_stdout_buffer = (
                self._autonomy_stdout_buffer.split("\n", 1)
            )
            prefix = "GG_AUTONOMY_EVENT="
            if not line.startswith(prefix):
                continue
            try:
                event = json.loads(line[len(prefix):])
                if set(event) != {
                    "schema",
                    "step_seq",
                    "phase",
                    "state",
                    "text",
                }:
                    raise ValueError("event field set invalid")
                if event["schema"] != "gg.workbench.autonomy-event.v1":
                    raise ValueError("event schema invalid")
                if type(event["step_seq"]) is not int or event["step_seq"] < 1:
                    raise ValueError("event step invalid")
                if (
                    type(event["phase"]) is not str
                    or type(event["state"]) is not str
                    or type(event["text"]) is not str
                    or len(event["text"]) > 4096
                ):
                    raise ValueError("event text invalid")

                task_id = state["task_id"]
                task = self._autonomy_tasks.get(task_id)
                if task is None:
                    raise ValueError("event task no longer exists")
                previous = int(task.get("last_event_seq", 0))
                if event["step_seq"] <= previous:
                    raise ValueError("event sequence replay")
                task["last_event_seq"] = event["step_seq"]
                self._task_log(
                    task_id,
                    str(event["phase"])
                    + "|"
                    + str(event["state"])
                    + "|"
                    + str(event["text"]),
                )

                upsert = getattr(
                    self._root,
                    "upsertAutonomyNode",
                    None,
                )
                if not callable(upsert):
                    raise RuntimeError(
                        "QML upsertAutonomyNode is unavailable."
                    )

                upsert(
                    task_id,
                    str(event["phase"]),
                    str(event["state"]),
                    str(event["text"]),
                    (
                        state["context"]
                        + " · "
                        + state["workspace"]
                        + " · "
                        + task_id
                    ),
                )
            except Exception as exc:
                self._append(
                    "GG SYSTEM",
                    "AUTONOMY",
                    "Autonomy event validation failed: " + str(exc),
                    state["context"] + " · " + state["workspace"],
                    "FAIL",
                    20,
                )

    @Slot(int, QProcess.ExitStatus)
    def _autonomy_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state
        if (
            process is None
            or state is None
            or state.get("kind") != "autonomy"
        ):
            return

        self._autonomy_stdout_ready()
        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", errors="replace")
        task_id = state["task_id"]
        task = self._autonomy_tasks.get(task_id)

        try:
            if task is None:
                raise RuntimeError("Autonomy task state missing.")

            if state.get("stop_requested") == "1":
                self._mark_stopped(state)
                return

            if exit_code != 0:
                lines = [
                    line.strip()
                    for line in stderr.splitlines()
                    if line.strip()
                ]
                reason = (
                    lines[-1]
                    if lines
                    else "autonomy controller exit code " + str(exit_code)
                )
                task["status"] = "BLOCKED"
                self._task_update(
                    task_id,
                    status="BLOCKED",
                    last_reason=reason,
                )
                self._append(
                    "GG SYSTEM",
                    "AUTONOMY",
                    "Autonomy controller stoppade säkert: " + reason,
                    state["context"] + " · " + state["workspace"] + " · " + task_id,
                    "BLOCKED",
                    28,
                )
                return

            root = Path(state["task_root"])
            result_path = root / "result.json"
            result = autonomy_contract.validate_result(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
            if result["task_id"] != task_id:
                raise RuntimeError("Autonomy result task mismatch.")
            if result["grant_sha256"] != task["grant_sha256"]:
                raise RuntimeError("Autonomy result grant mismatch.")

            task["status"] = "WAITING_HOST_APPLY"
            task["write_proposal_id"] = result["write_proposal_id"]
            task["write_candidate_sha256"] = (
                result["write_candidate_sha256"]
            )
            task["write_before_sha256"] = result["write_before_sha256"]
            self._task_update(
                task_id,
                status="WAITING_HOST_APPLY",
                write_proposal_id=str(result["write_proposal_id"]),
                write_candidate_sha256=str(result["write_candidate_sha256"]),
                write_before_sha256=str(result["write_before_sha256"]),
                last_reason="",
            )

            self._append(
                "GG AUTONOMY",
                "BOUNDARY",
                (
                    "VERIFIED CHANGESET är klart. GG stannar korrekt vid "
                    "persistent host-effect boundary.\n"
                    "Godkänn befintlig Limited Write proposal med:\n"
                    + result["write_approval_command"]
                ),
                state["context"] + " · " + state["workspace"] + " · " + task_id,
                "WAITING_FOR_USER",
                28,
            )

        except Exception as exc:
            if task is not None:
                task["status"] = "BLOCKED"
            self._task_update(
                task_id,
                status="BLOCKED",
                last_reason=type(exc).__name__ + ":" + str(exc),
            )
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Autonomy result validation failed: " + str(exc),
                state["context"] + " · " + state["workspace"],
                "FAIL",
                28,
            )
        finally:
            process.deleteLater()
            self._process = None
            self._state = None
            self._autonomy_stdout_buffer = ""
            self._set_bridge_activity(False, "")

    def _resume_autonomy_verify(self, task_id: str) -> None:
        task = self._autonomy_tasks.get(task_id)
        if task is None or task.get("status") != "VERIFYING_HOST":
            return
        if self._process is not None:
            task["status"] = "BLOCKED"
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Host verify kunde inte starta: process slot upptagen.",
                "@current · " + autonomy_contract.TARGET_WORKSPACE_OBJECT_ID,
                "BLOCKED",
                20,
            )
            return

        root = Path(str(task["task_root"]))
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-B",
                str(AUTONOMY_CONTROLLER_PATH),
                "--verify-host",
                str(root),
            ]
        )
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )
        self._state = {
            "kind": "autonomy-verify",
            "task_id": task_id,
            "context": "@current",
            "workspace": autonomy_contract.TARGET_WORKSPACE_OBJECT_ID,
            "task_root": str(root),
            "stoppable": "1",
        }
        self._process = process
        self._task_update(task_id, status="VERIFYING_HOST")
        self._set_bridge_activity(True, task_id)
        self._autonomy_stdout_buffer = ""
        process.readyReadStandardOutput.connect(
            self._autonomy_stdout_ready
        )
        process.finished.connect(
            self._autonomy_verify_finished
        )
        process.start()

        if not process.waitForStarted(5000):
            task["status"] = "BLOCKED"
            reason = process.errorString()
            process.deleteLater()
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Host-effect verifier kunde inte starta: " + reason,
                "@current · " + autonomy_contract.TARGET_WORKSPACE_OBJECT_ID,
                "FAIL",
                20,
            )

    @Slot(int, QProcess.ExitStatus)
    def _autonomy_verify_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state
        if (
            process is None
            or state is None
            or state.get("kind") != "autonomy-verify"
        ):
            return

        self._autonomy_stdout_ready()
        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", errors="replace")
        task_id = state["task_id"]
        task = self._autonomy_tasks.get(task_id)

        try:
            if task is None:
                raise RuntimeError("Autonomy task missing during host verify.")

            if state.get("stop_requested") == "1":
                self._mark_stopped(state)
                return
            if exit_code != 0:
                lines = [
                    line.strip()
                    for line in stderr.splitlines()
                    if line.strip()
                ]
                raise RuntimeError(
                    lines[-1]
                    if lines
                    else "host verifier exit code " + str(exit_code)
                )
            result = autonomy_contract.validate_host_verify(
                json.loads(
                    (
                        Path(state["task_root"])
                        / "host-verify.json"
                    ).read_text(encoding="utf-8")
                )
            )
            if result["task_id"] != task_id:
                raise RuntimeError("Host verify task mismatch.")
            task["status"] = "DONE"
            self._task_update(
                task_id,
                status="DONE",
                last_reason="HOST_EFFECT_VERIFIED",
            )
            self._append(
                "GG AUTONOMY",
                "DONE",
                (
                    "AUTONOMY TASK DONE · real host effect observerad · "
                    "candidate SHA matchar · QML Gate PASS · tekniskt "
                    "DONE_WHEN verifierat."
                ),
                state["context"] + " · " + state["workspace"] + " · " + task_id,
                "PASS",
                28,
            )
        except Exception as exc:
            if task is not None:
                task["status"] = "BLOCKED"
            self._task_update(
                task_id,
                status="BLOCKED",
                last_reason=type(exc).__name__ + ":" + str(exc),
            )
            self._append(
                "GG SYSTEM",
                "AUTONOMY",
                "Host-effect verify stoppade säkert: " + str(exc),
                state["context"] + " · " + state["workspace"] + " · " + task_id,
                "FAIL",
                28,
            )
        finally:
            process.deleteLater()
            self._process = None
            self._state = None
            self._autonomy_stdout_buffer = ""
            self._set_bridge_activity(False, "")

    def _submit_write(
        self,
        parsed: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        action = str(parsed["action"])

        if (
            context_reference != write_contract.TARGET_CONTEXT_REFERENCE
            or workspace_object_id
            != write_contract.TARGET_WORKSPACE_OBJECT_ID
        ):
            self._append(
                "GG SYSTEM",
                "WRITE",
                "Limited Write v1 är endast tillåten för verklig @current "
                "ContextComposer.qml.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        proposal_id = str(
            parsed.get(
                "proposal_id",
                "proposal-" + uuid.uuid4().hex,
            )
        )
        request_id = "write-" + uuid.uuid4().hex

        try:
            request = write_contract.validate_request(
                {
                    "schema": write_contract.REQUEST_SCHEMA,
                    "request_id": request_id,
                    "action": action,
                    "proposal_id": proposal_id,
                    "context_reference": context_reference,
                    "workspace_object_id": workspace_object_id,
                    "arguments": parsed["arguments"],
                }
            )
        except ValueError as exc:
            self._append(
                "GG SYSTEM",
                "WRITE",
                "Limited Write request blockerad: " + str(exc),
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        runtime_root = private_runtime_root()
        proposal_suffix = proposal_id.removeprefix("proposal-")
        evidence = runtime_root / (
            "gg-write-proposal." + proposal_suffix
        )
        nonce = uuid.uuid4().hex[:24]
        request_path = runtime_root / (
            "gg-workbench-write-request." + nonce + ".json"
        )

        if action == write_contract.ACTION_PROPOSE:
            if evidence.exists() or evidence.is_symlink():
                self._append(
                    "GG SYSTEM",
                    "WRITE",
                    "Proposal evidence path already exists.",
                    context_reference + " · " + workspace_object_id,
                    "BLOCKED",
                    20,
                )
                return
        elif evidence.is_symlink() or not evidence.is_dir():
            self._append(
                "GG SYSTEM",
                "WRITE",
                "Bound write proposal does not exist in this local session.",
                context_reference + " · " + workspace_object_id,
                "BLOCKED",
                20,
            )
            return

        request_bytes = (
            write_contract.canonical_request_json(request)
            + "\n"
        ).encode("utf-8")

        fd = secure_open(
            request_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
        )

        with os.fdopen(fd, "wb") as handle:
            handle.write(request_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        self._append(
            "GG SYSTEM",
            "WRITE",
            "Limited Write "
            + action
            + " kör · YELLOW exact proposal-bound authority · "
            + "target @current only · network none · general authority none.",
            context_reference + " · " + workspace_object_id,
            "RUNNING",
            28,
        )

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-B",
                str(WRITE_RUNNER_PATH),
                "--execute-write",
                str(evidence),
                str(request_path),
            ]
        )
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )

        self._state = {
            "kind": "write",
            "request_id": request_id,
            "action": action,
            "proposal_id": proposal_id,
            "context": context_reference,
            "workspace": workspace_object_id,
            "evidence": str(evidence),
            "request_path": str(request_path),
            "stoppable": (
                "0"
                if action
                in (
                    write_contract.ACTION_APPROVE,
                    write_contract.ACTION_ROLLBACK,
                )
                else "1"
            ),
        }
        self._process = process
        self._set_bridge_activity(True, request_id)
        process.finished.connect(self._write_finished)
        process.start()

        if not process.waitForStarted(5000):
            reason = process.errorString()

            try:
                request_path.unlink()
            except OSError:
                pass

            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")
            self._append(
                "GG SYSTEM",
                "WRITE",
                "Limited Write runner kunde inte starta: " + reason,
                context_reference + " · " + workspace_object_id,
                "FAIL",
                28,
            )

    @Slot(int, QProcess.ExitStatus)
    def _write_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state

        if (
            process is None
            or state is None
            or state.get("kind") != "write"
        ):
            return

        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", errors="replace")

        evidence = Path(state["evidence"])
        request_path = Path(state["request_path"])
        request_id = state["request_id"]
        action = state["action"]
        proposal_id = state["proposal_id"]
        context = state["context"]
        workspace = state["workspace"]
        resume_autonomy_task_id: str | None = None

        try:
            if state.get("stop_requested") == "1":
                self._mark_stopped(state)
                return

            if exit_code != 0:
                reason = ""
                failure_path = (
                    evidence
                    / ("failure-" + action.lower() + ".json")
                )

                if failure_path.is_file() and not failure_path.is_symlink():
                    try:
                        failure = json.loads(
                            failure_path.read_text(encoding="utf-8")
                        )
                        reason = str(failure.get("reason", ""))
                    except (
                        OSError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ):
                        pass

                if not reason:
                    lines = [
                        line.strip()
                        for line in stderr.splitlines()
                        if line.strip()
                    ]
                    reason = (
                        lines[-1]
                        if lines
                        else f"write runner exit code {exit_code}"
                    )

                self._append(
                    "GG SYSTEM",
                    "WRITE",
                    "Limited Write stoppade säkert: " + reason,
                    context + " · " + workspace,
                    "FAIL",
                    28,
                )
                return

            response_path = (
                evidence
                / ("response-" + action.lower() + ".json")
            )

            if (
                not response_path.is_file()
                or response_path.is_symlink()
            ):
                raise RuntimeError(
                    "Limited Write returned PASS without bound response."
                )

            response = json.loads(
                response_path.read_text(encoding="utf-8")
            )
            validated = write_contract.validate_response(
                response,
                request_id,
                action,
                proposal_id,
            )

            output = str(validated["output"]).strip()
            status = str(validated["status"])

            state_map = {
                "WAITING_APPROVAL": "WAITING_FOR_USER",
                "APPLIED_VERIFIED": "PASS",
                "REJECTED_NO_WRITE": "CANCELLED",
                "ROLLED_BACK_VERIFIED": "PASS",
                "BLOCKED": "BLOCKED",
            }

            self._append(
                "GG WRITE",
                action,
                output,
                context
                + " · "
                + workspace
                + " · "
                + write_contract.AUTHORITY,
                state_map[status],
                28,
            )

            if (
                action == write_contract.ACTION_APPROVE
                and status == "APPLIED_VERIFIED"
            ):
                matches: list[tuple[str, dict[str, object]]] = []
                for autonomy_task_id, autonomy_task in self._autonomy_tasks.items():
                    if (
                        autonomy_task.get("status") == "WAITING_HOST_APPLY"
                        and autonomy_task.get("write_proposal_id") == proposal_id
                    ):
                        matches.append((autonomy_task_id, autonomy_task))

                if len(matches) > 1:
                    raise RuntimeError(
                        "Multiple autonomy tasks are bound to one write proposal."
                    )

                if len(matches) == 1:
                    autonomy_task_id, autonomy_task = matches[0]
                    response_evidence = validated["evidence"]
                    if (
                        response_evidence["candidate_sha256"]
                        != autonomy_task.get("write_candidate_sha256")
                    ):
                        raise RuntimeError(
                            "Autonomy host apply candidate SHA mismatch."
                        )
                    if (
                        response_evidence["before_sha256"]
                        != autonomy_task.get("write_before_sha256")
                    ):
                        raise RuntimeError(
                            "Autonomy host apply before SHA mismatch."
                        )

                    resume_autonomy_task_id = autonomy_task_id

                try:
                    applied_path = evidence / "applied.json"
                    proposal_path = evidence / "proposal.json"

                    for label, item in (
                        ("APPLIED_RECEIPT", applied_path),
                        ("WRITE_PROPOSAL", proposal_path),
                    ):
                        if item.is_symlink() or not item.is_file():
                            raise RuntimeError(
                                label + "_MISSING_OR_INVALID"
                            )

                    applied_receipt = json.loads(
                        applied_path.read_text(
                            encoding="utf-8"
                        )
                    )

                    write_proposal = json.loads(
                        proposal_path.read_text(
                            encoding="utf-8"
                        )
                    )

                    self._resident_information_state.ingest_verified_write_completion(
                        applied_receipt,
                        write_proposal,
                    )

                except Exception as exc:
                    raise resident_state.ResidentInformationStateError(
                        "HOST_EFFECT_VERIFIED_BUT_RESIDENT_INFORMATION_STATE_BLOCKED:"
                        + type(exc).__name__
                        + ":"
                        + str(exc)
                    ) from exc

                if resume_autonomy_task_id is not None:
                    autonomy_task = self._autonomy_tasks[
                        resume_autonomy_task_id
                    ]
                    autonomy_task["status"] = "VERIFYING_HOST"
                    self._task_update(
                        resume_autonomy_task_id,
                        status="VERIFYING_HOST",
                    )

            elif (
                action == write_contract.ACTION_ROLLBACK
                and status == "ROLLED_BACK_VERIFIED"
            ):
                rollback_path = (
                    evidence
                    / "rollback.json"
                )
                proposal_path = (
                    evidence
                    / "proposal.json"
                )

                for label, item in (
                    (
                        "ROLLBACK_RECEIPT",
                        rollback_path,
                    ),
                    (
                        "WRITE_PROPOSAL",
                        proposal_path,
                    ),
                ):
                    if (
                        item.is_symlink()
                        or not item.is_file()
                    ):
                        raise resident_state.ResidentInformationStateError(
                            "HOST_EFFECT_VERIFIED_BUT_RESIDENT_INFORMATION_STATE_BLOCKED:"
                            + label
                            + "_MISSING_OR_INVALID"
                        )

                rollback_receipt = json.loads(
                    rollback_path.read_text(
                        encoding="utf-8"
                    )
                )

                write_proposal = json.loads(
                    proposal_path.read_text(
                        encoding="utf-8"
                    )
                )

                self._resident_information_state.ingest_verified_write_rollback(
                    rollback_receipt,
                    write_proposal,
                )

        except Exception as exc:
            if resume_autonomy_task_id is not None:
                task = self._autonomy_tasks.get(resume_autonomy_task_id)
                if task is not None:
                    task["status"] = "BLOCKED"
                    self._task_update(
                        resume_autonomy_task_id,
                        status="BLOCKED",
                        last_reason=type(exc).__name__ + ":" + str(exc),
                    )
                resume_autonomy_task_id = None

            message = (
                "Host-write verifierad, men resident informationsstate blockerades: "
                + str(exc)
                if isinstance(
                    exc,
                    resident_state.ResidentInformationStateError,
                )
                else (
                    "Limited Write response validation failed: "
                    + str(exc)
                )
            )

            self._append(
                "GG SYSTEM",
                "WRITE",
                message,
                context + " · " + workspace,
                "BLOCKED"
                if isinstance(
                    exc,
                    resident_state.ResidentInformationStateError,
                )
                else "FAIL",
                28,
            )
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass

            process.deleteLater()
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")

            if resume_autonomy_task_id is not None:
                self._resume_autonomy_verify(resume_autonomy_task_id)

    def _submit_eligible_tool(
        self,
        *,
        pending_id: str,
        pending: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        result = (
            action_execution_safe_tool_adapter
            .submit_eligible_tool(
                self,
                pending_id,
                pending,
                context_reference,
                workspace_object_id,
                project=PROJECT,
                qprocess_type=QProcess,
                safe_tool_runner_path=SAFE_TOOL_RUNNER_PATH,
                resolve_workspace_context_fn=resolve_workspace_context,
            )
        )

        action_task_continuity.record_action_dispatch(
            self._task_ledger,
            pending,
        )

        return result

    def _eligible_tool_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        state = self._state
        pending: dict[str, object] | None = None

        if isinstance(state, dict):
            pending_id = str(
                state.get(
                    "pending_id",
                    "",
                )
            )
            pending = self._pending_mandates.get(
                pending_id
            )

        result = (
            action_execution_safe_tool_adapter
            .eligible_tool_finished(
                self,
                exit_code,
                _exit_status,
                resolve_workspace_context_fn=(
                    resolve_workspace_context
                ),
            )
        )

        if pending is not None:
            action_task_continuity.record_action_completion(
                self._task_ledger,
                pending,
            )

        return result

    def _submit_tool(
        self,
        parsed: dict[str, object],
        context_reference: str,
        workspace_object_id: str,
    ) -> None:
        request_id = "tool-" + uuid.uuid4().hex
        request = tool_contract.validate_request(
            {
                "schema": tool_contract.REQUEST_SCHEMA,
                "request_id": request_id,
                "profile": parsed["profile"],
                "arguments": parsed["arguments"],
            }
        )

        runtime_root = private_runtime_root()
        nonce = uuid.uuid4().hex[:24]
        evidence = runtime_root / f"gg-safe-tool.{nonce}"
        request_path = (
            runtime_root
            / f"gg-workbench-tool-request.{nonce}.json"
        )

        evidence.mkdir(mode=0o700, exist_ok=False)
        request_bytes = (
            tool_contract.canonical_request_json(request)
            + "\n"
        ).encode("utf-8")

        fd = secure_open(
            request_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        with os.fdopen(fd, "wb") as handle:
            handle.write(request_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        profile = str(request["profile"])

        self._append(
            "GG SYSTEM",
            "TOOL",
            "Safe Tool "
            + profile
            + " kör · GREEN typed profile · network authority none · "
            + "persistent write authority none.",
            context_reference + " · " + workspace_object_id,
            "RUNNING",
            28,
        )

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-B",
                str(SAFE_TOOL_RUNNER_PATH),
                "--execute-tool",
                str(evidence),
                str(request_path),
            ]
        )
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )

        self._state = {
            "kind": "tool",
            "request_id": request_id,
            "profile": profile,
            "context": context_reference,
            "workspace": workspace_object_id,
            "evidence": str(evidence),
            "request_path": str(request_path),
            "stoppable": "1",
        }
        self._process = process
        self._set_bridge_activity(True, request_id)
        process.finished.connect(self._tool_finished)
        process.start()

        if not process.waitForStarted(5000):
            reason = process.errorString()

            try:
                request_path.unlink()
            except OSError:
                pass

            try:
                evidence.rmdir()
            except OSError:
                pass

            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")
            self._append(
                "GG SYSTEM",
                "TOOL",
                "Safe Tool runner kunde inte starta: " + reason,
                context_reference + " · " + workspace_object_id,
                "FAIL",
                28,
            )

    @Slot(int, QProcess.ExitStatus)
    def _tool_finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state

        if (
            process is None
            or state is None
            or state.get("kind") != "tool"
        ):
            return

        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", errors="replace")

        evidence = Path(state["evidence"])
        request_path = Path(state["request_path"])
        request_id = state["request_id"]
        profile = state["profile"]
        context = state["context"]
        workspace = state["workspace"]

        try:
            if state.get("stop_requested") == "1":
                self._mark_stopped(state)
                return

            if exit_code != 0:
                reason = ""
                failure_path = evidence / "runner-failure.json"

                if failure_path.is_file() and not failure_path.is_symlink():
                    try:
                        failure = json.loads(
                            failure_path.read_text(encoding="utf-8")
                        )
                        reason = str(failure.get("reason", ""))
                    except (
                        OSError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ):
                        pass

                if not reason:
                    lines = [
                        line.strip()
                        for line in stderr.splitlines()
                        if line.strip()
                    ]
                    reason = (
                        lines[-1]
                        if lines
                        else f"safe tool exit code {exit_code}"
                    )

                self._append(
                    "GG SYSTEM",
                    "TOOL",
                    "Safe Tool stoppade säkert: " + reason,
                    context + " · " + workspace,
                    "FAIL",
                    28,
                )
                return

            response_path = evidence / "response.json"

            if (
                not response_path.is_file()
                or response_path.is_symlink()
            ):
                raise RuntimeError(
                    "Safe Tool returned PASS without response.json."
                )

            response = json.loads(
                response_path.read_text(encoding="utf-8")
            )
            validated = tool_contract.validate_response(
                response,
                request_id,
                profile,
            )

            if validated["status"] != "PASS":
                raise RuntimeError(
                    "Safe Tool response did not report PASS."
                )

            output = str(validated["output"]).strip()

            if not output:
                output = "(empty read-only result)"

            self._append(
                "GG TOOL",
                profile,
                output,
                context
                + " · "
                + workspace
                + " · "
                + tool_contract.AUTHORITY,
                "PASS",
                28,
            )

        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "TOOL",
                "Safe Tool response validation failed: "
                + str(exc),
                context + " · " + workspace,
                "FAIL",
                28,
            )
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass

            process.deleteLater()
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")

    @Slot(int, QProcess.ExitStatus)
    def _finished(
        self,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        state = self._state

        if (
            process is None
            or state is None
            or state.get("kind") != "model"
        ):
            return

        stderr = bytes(
            process.readAllStandardError()
        ).decode("utf-8", errors="replace")

        evidence = Path(state["evidence"])
        request_path = Path(state["request_path"])
        request_id = state["request_id"]
        context = state["context"]
        workspace = state["workspace"]
        workspace_source = state["workspace_source"]
        workspace_sha256 = state["workspace_sha256"]

        try:
            if state.get("stop_requested") == "1":
                self._mark_stopped(state)
                return

            if exit_code != 0:
                reason = ""
                failure_path = evidence / "runner-failure.json"

                if failure_path.is_file() and not failure_path.is_symlink():
                    try:
                        failure = json.loads(
                            failure_path.read_text(encoding="utf-8")
                        )
                        reason = str(failure.get("reason", ""))
                    except (
                        OSError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ):
                        pass

                if not reason:
                    lines = [
                        line.strip()
                        for line in stderr.splitlines()
                        if line.strip()
                    ]
                    reason = (
                        lines[-1]
                        if lines
                        else f"runner exit code {exit_code}"
                    )

                self._append(
                    "GG SYSTEM",
                    "MODEL",
                    "Lokal modell stoppade säkert: " + reason,
                    context + " · " + workspace,
                    "FAIL",
                    28,
                )
                return

            response_path = evidence / "response.json"

            if (
                not response_path.is_file()
                or response_path.is_symlink()
            ):
                raise RuntimeError(
                    "Runner returned PASS without response.json."
                )

            response = json.loads(
                response_path.read_text(encoding="utf-8")
            )
            validated = contract.validate_response(
                response,
                request_id,
            )

            answer = validated["text"].replace(
                "GG_MODEL_RUNNER_OK",
                "",
            ).strip()

            if not answer:
                raise RuntimeError(
                    "Model answer became empty after marker removal."
                )

            response_author = "GG AI"
            participant_state = state.get(
                "participant_task",
                "",
            )

            if participant_state:
                participant_result = (
                    participant_task_receiver
                    .finalize_participant_response(
                        state_json=participant_state,
                        validated_response=validated,
                        answer=answer,
                        evidence_path=evidence,
                    )
                )
                answer = str(
                    participant_result["text"]
                )
                response_author = (
                    "GG PARTICIPANT · "
                    + str(
                        participant_result[
                            "participant_id"
                        ]
                    )
                )

            self._append(
                response_author,
                "RESPONSE",
                answer,
                context
                + " · "
                + workspace
                + " · "
                + workspace_source
                + " · sha256:"
                + workspace_sha256[:12],
                "PASS",
                28,
            )

        except Exception as exc:
            self._append(
                "GG SYSTEM",
                "MODEL",
                "Local Chat Bridge response validation failed: "
                + str(exc),
                context + " · " + workspace,
                "FAIL",
                28,
            )
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass

            process.deleteLater()
            self._process = None
            self._state = None
            self._set_bridge_activity(False, "")

class DesktopStartupCoordinator(QObject):
    """Finish local bridge setup after the desktop loading view is visible."""

    def __init__(
        self,
        root: QObject,
        app: QApplication,
    ) -> None:
        super().__init__(app)
        self._root = root
        self._app = app
        self._frame_swapped = None
        self._first_frame_seen = False
        self._bridge_setup_scheduled = False
        self._workspace_wait_started = 0.0
        self._startup_steps: list[tuple[str, Callable[[], None]]] = []
        self._startup_step_index = 0
        self._chat_bridge: ChatBridge | None = None
        self._live_aid_bridge: LiveAidQtBridge | None = None

    def start(self) -> bool:
        frame_swapped = getattr(self._root, "frameSwapped", None)
        if frame_swapped is None:
            self._fail("Qt did not expose the desktop render signal")
            return False
        try:
            frame_swapped.connect(
                self._on_first_frame,
                Qt.ConnectionType.QueuedConnection,
            )
            self._frame_swapped = frame_swapped
        except (AttributeError, TypeError, RuntimeError) as exc:
            self._fail("Could not connect the desktop render signal: " + str(exc))
            return False
        return True

    @Slot()
    def _on_first_frame(self) -> None:
        if self._first_frame_seen:
            return
        self._first_frame_seen = True
        if self._frame_swapped is not None:
            try:
                self._frame_swapped.disconnect(self._on_first_frame)
            except (AttributeError, TypeError, RuntimeError):
                pass
            self._frame_swapped = None
        self._set_qml_status(
            "LOADING DESKTOP…",
            "Preparing workspace and utility surfaces",
        )
        self._workspace_wait_started = time.monotonic()
        QTimer.singleShot(0, self._wait_for_workspace)

    @Slot()
    def _wait_for_workspace(self) -> None:
        if self._bridge_setup_scheduled:
            return
        workspace_surface = self._root.findChild(QObject, "workspaceSurface")
        workspace_ready = bool(self._root.property("_workspaceLoaderReady"))
        utility_ready = bool(self._root.property("_utilityLoaderReady"))
        if workspace_surface is None or not workspace_ready or not utility_ready:
            if bool(self._root.property("workspaceLoadFailed")):
                self._fail("Workspace surface reported a QML load error")
                return
            if time.monotonic() - self._workspace_wait_started >= 30.0:
                if workspace_surface is None or not workspace_ready:
                    self._fail("Workspace surface did not finish loading")
                else:
                    self._fail("Utility surface did not finish loading")
                return
            QTimer.singleShot(35, self._wait_for_workspace)
            return

        self._bridge_setup_scheduled = True
        self._set_qml_status(
            "STARTING LOCAL SERVICES…",
            "Connecting chat, task ledger and desktop bridges",
        )
        # Give Qt Quick a turn to paint the new stage before bridge setup does
        # its synchronous local store reads and recovery work.
        QTimer.singleShot(100, self._initialize_bridges)

    @Slot()
    def _initialize_bridges(self) -> None:
        workspace_surface = self._root.findChild(QObject, "workspaceSurface")
        if workspace_surface is None:
            self._bridge_setup_scheduled = False
            self._wait_for_workspace()
            return

        self._startup_steps = [
            ("Create Live Aid bridge", self._create_live_aid_bridge),
            ("Create chat bridge", self._create_chat_bridge),
            ("Build workbench command graph", self._initialize_machine_graph),
            (
                "Verify local source and runner fingerprints",
                self._initialize_information_state,
            ),
            (
                "Load task ledger and recover pending work",
                self._initialize_task_state,
            ),
            (
                "Connect saved chat sessions and desktop surfaces",
                self._initialize_resident_chat,
            ),
            ("Wire chat, task and stop signals", self._wire_bridge_signals),
        ]
        self._startup_step_index = 0
        self._run_startup_step()

    def _create_live_aid_bridge(self) -> None:
        self._live_aid_bridge = LiveAidQtBridge(REPO_ROOT, self._app)
        if not self._root.setProperty("liveAidBackend", self._live_aid_bridge):
            raise RuntimeError("Main window rejected Live Aid bridge property")

        workspace_surface = self._root.findChild(QObject, "workspaceSurface")
        if workspace_surface is None:
            raise RuntimeError("WorkspaceSurface disappeared during startup")
        if not workspace_surface.setProperty(
            "liveAidBackend",
            self._live_aid_bridge,
        ):
            raise RuntimeError("WorkspaceSurface rejected Live Aid bridge property")

    def _create_chat_bridge(self) -> None:
        self._chat_bridge = ChatBridge(
            self._root,
            self._app,
            defer_startup=True,
        )

    def _require_chat_bridge(self) -> ChatBridge:
        if self._chat_bridge is None:
            raise RuntimeError("Chat bridge container is not ready")
        return self._chat_bridge

    def _initialize_machine_graph(self) -> None:
        self._require_chat_bridge().initialize_startup_machine_graph()

    def _initialize_information_state(self) -> None:
        self._require_chat_bridge().initialize_startup_information_state()

    def _initialize_task_state(self) -> None:
        self._require_chat_bridge().initialize_startup_task_state()

    def _initialize_resident_chat(self) -> None:
        self._require_chat_bridge().initialize_startup_resident_chat()

    def _wire_bridge_signals(self) -> None:
        bridge = self._require_chat_bridge()
        bridge_signal = getattr(self._root, "bridgeSubmit", None)
        context_snapshot_signal = getattr(
            self._root,
            "contextSnapshotSync",
            None,
        )
        stop_signal = getattr(self._root, "bridgeStop", None)
        assignment_set_signal = getattr(
            self._root,
            "bridgeAssignmentSet",
            None,
        )
        assignment_clear_signal = getattr(
            self._root,
            "bridgeAssignmentClear",
            None,
        )

        if bridge_signal is None:
            raise RuntimeError("QML bridgeSubmit signal is unavailable")
        if context_snapshot_signal is None:
            raise RuntimeError("QML contextSnapshotSync signal is unavailable")
        if stop_signal is None:
            raise RuntimeError("QML bridgeStop signal is unavailable")
        if assignment_set_signal is None:
            raise RuntimeError("QML bridgeAssignmentSet signal is unavailable")
        if assignment_clear_signal is None:
            raise RuntimeError("QML bridgeAssignmentClear signal is unavailable")

        bridge_signal.connect(bridge.submit)
        context_snapshot_signal.connect(bridge.syncContextSnapshot)
        stop_signal.connect(bridge.stopActive)
        assignment_set_signal.connect(bridge._setOrchestratorAssignment)
        assignment_clear_signal.connect(bridge._clearOrchestratorAssignment)
        self._app._gg_chat_bridge = bridge  # type: ignore[attr-defined]
        self._app._gg_live_aid_bridge = self._live_aid_bridge  # type: ignore[attr-defined]

    def _run_startup_step(self) -> None:
        if self._startup_step_index >= len(self._startup_steps):
            self._finish_startup()
            return

        label, callback = self._startup_steps[self._startup_step_index]
        self._root.setProperty(
            "startupStepNumber",
            self._startup_step_index + 1,
        )
        self._root.setProperty("startupStepCount", len(self._startup_steps) + 1)
        self._root.setProperty("startupStepBusy", True)
        self._set_qml_status("STARTING LOCAL SERVICES…", str(label))
        QTimer.singleShot(
            100,
            lambda: self._perform_startup_step(
                self._startup_step_index,
                str(label),
                callback,
            ),
        )

    def _perform_startup_step(
        self,
        step_index: int,
        label: str,
        callback: Callable[[], None],
    ) -> None:
        if step_index != self._startup_step_index:
            return
        started = time.monotonic()
        try:
            callback()
        except Exception as exc:
            elapsed = time.monotonic() - started
            self._root.setProperty("startupStepBusy", False)
            append_log = getattr(self._root, "appendShellLog", None)
            if callable(append_log):
                append_log(
                    "startup · "
                    + label
                    + " · failed after "
                    + f"{elapsed:.2f}s"
                )
            self._fail(type(exc).__name__ + ": " + str(exc))
            return

        elapsed = time.monotonic() - started
        append_log = getattr(self._root, "appendShellLog", None)
        if callable(append_log):
            append_log("startup · " + label + " · " + f"{elapsed:.2f}s")
        self._root.setProperty("startupStepBusy", False)
        self._startup_step_index += 1
        service_progress = round(
            self._startup_step_index
            * 100
            / max(1, len(self._startup_steps) + 1)
        )
        self._root.setProperty("startupServiceProgress", service_progress)
        if self._startup_step_index >= len(self._startup_steps):
            self._finish_startup()
            return
        QTimer.singleShot(100, self._run_startup_step)

    def _finish_startup(self) -> None:
        self._root.setProperty("startupStepNumber", len(self._startup_steps) + 1)
        self._root.setProperty("startupStepCount", len(self._startup_steps) + 1)
        self._root.setProperty("startupStepBusy", True)
        self._set_qml_status(
            "FINISHING STARTUP…",
            "Binding workspace and utility surfaces",
        )
        QTimer.singleShot(100, self._mark_startup_ready)

    @Slot()
    def _mark_startup_ready(self) -> None:
        if not self._root.setProperty("startupReady", True):
            self._fail("Main window rejected startup-ready state")

    def _set_qml_status(self, label: str, current: str) -> None:
        self._root.setProperty("shellLoadLabel", label)
        self._root.setProperty("shellLoadCurrent", current)

    def _fail(self, reason: str) -> None:
        self._root.setProperty("startupStepBusy", False)
        self._root.setProperty("startupFailed", True)
        self._set_qml_status("STARTUP FAILED", reason)
        self._root.setProperty("shellLoading", True)
        append_log = getattr(self._root, "appendShellLog", None)
        if callable(append_log):
            append_log("startup · " + reason)


def initialize_loaded_window(root: QObject, app: QApplication) -> None:
    """Attach desktop configuration and services to the visible QML window."""
    config = load_config()
    integrations = config["integrations"]
    safety = config["safety"]

    if not isinstance(integrations, dict):
        raise RuntimeError("Invalid integration configuration.")
    if not isinstance(safety, dict):
        raise RuntimeError("Invalid safety configuration.")

    if integrations["model"] != "ENABLED_LOCAL_CHAT":
        raise RuntimeError("Local model integration is not enabled.")
    if integrations.get("task_scoped_effects") != (
        "ENABLED_EXPLICIT_HASH_BOUND_MANDATE"
    ):
        raise RuntimeError("Task-scoped effect integration mismatch.")
    if integrations["network"] != "TASK_SCOPED_AFTER_MANDATE":
        raise RuntimeError("Network integration must remain task-scoped.")
    if integrations["orchestrator"] != "DISABLED":
        raise RuntimeError("Orchestrator must remain disabled.")
    if (
        integrations["real_command_execution"]
        != "ENABLED_FIXED_GREEN_SAFE_TOOLS"
    ):
        raise RuntimeError(
            "Only fixed GREEN Safe Tools command execution may be enabled."
        )
    if (
        integrations.get("limited_write_execution")
        != "ENABLED_EXPLICIT_CURRENT_QML_PATCH_V1"
    ):
        raise RuntimeError(
            "Limited Write execution integration mismatch."
        )
    if (
        integrations.get("code_gate_runtime")
        != "ENABLED_LIMITED_WRITE_QML_PREAPPLY"
    ):
        raise RuntimeError(
            "Limited Write runtime Code Gate integration mismatch."
        )
    if (
        integrations.get("autonomy")
        != "ENABLED_TASK_BOUND_CANDIDATE_V1"
    ):
        raise RuntimeError(
            "Autonomy task-bound candidate integration mismatch."
        )
    if (
        integrations.get("control_plane")
        != "ENABLED_TYPED_CONTROL_PLANE_V1"
        or integrations.get("verified_task_apply")
        != "ENABLED_EXPLICIT_VERIFIED_MAIN_PY_V1"
    ):
        raise RuntimeError("Control Plane integration mismatch.")

    control_plane = config.get("control_plane")
    if not isinstance(control_plane, dict):
        raise RuntimeError("Control Plane configuration missing.")
    if control_plane.get("authority") != control_contract.CONTROL_AUTHORITY:
        raise RuntimeError("Control Plane authority mismatch.")
    if (
        control_plane.get("bootstrap_apply_authority")
        != control_contract.BOOTSTRAP_APPLY_AUTHORITY
        or control_plane.get("bootstrap_target")
        != control_contract.TARGET_RELATIVE_PATH
        or control_plane.get("bootstrap_model_semantic_grammar")
        != "FINITE_FIELD_BOUNDS_V1"
    ):
        raise RuntimeError("Control Plane apply boundary mismatch.")
    if control_plane.get("stop_priority") != "PARSED_BEFORE_BUSY_GATE":
        raise RuntimeError("Control Plane stop priority mismatch.")
    if control_plane.get("stop_escalation") != "TERM_THEN_KILL_3000MS":
        raise RuntimeError("Control Plane stop escalation mismatch.")
    if control_plane.get("stop_idempotent") is not True:
        raise RuntimeError("Control Plane idempotence mismatch.")
    for authority_key in (
        "network_authority",
        "general_action_authority",
        "shell_authority",
        "arbitrary_exec_authority",
        "arbitrary_path_authority",
        "git_commit_authority",
    ):
        if control_plane.get(authority_key) != "NONE":
            raise RuntimeError("Control Plane authority expansion: " + authority_key)
    tools = config.get("safe_tools")
    if not isinstance(tools, dict):
        raise RuntimeError("Safe Tools configuration missing.")
    if tools.get("authority") != tool_contract.AUTHORITY:
        raise RuntimeError("Safe Tools authority mismatch.")
    if tools.get("network_authority") != "NONE":
        raise RuntimeError("Safe Tools network authority must remain NONE.")
    if tools.get("persistent_write_authority") != "NONE":
        raise RuntimeError(
            "Safe Tools persistent write authority must remain NONE."
        )

    limited_write = config.get("limited_write")
    if not isinstance(limited_write, dict):
        raise RuntimeError("Limited Write configuration missing.")
    if limited_write.get("authority") != write_contract.AUTHORITY:
        raise RuntimeError("Limited Write authority mismatch.")
    if (
        limited_write.get("target_workspace_object_id")
        != write_contract.TARGET_WORKSPACE_OBJECT_ID
    ):
        raise RuntimeError("Limited Write Workspace target mismatch.")
    if (
        limited_write.get("target_source_path")
        != write_contract.TARGET_RELATIVE_PATH
    ):
        raise RuntimeError("Limited Write source target mismatch.")
    if limited_write.get("network_authority") != "NONE":
        raise RuntimeError("Limited Write network authority must remain NONE.")
    if limited_write.get("general_action_authority") != "NONE":
        raise RuntimeError(
            "Limited Write general action authority must remain NONE."
        )
    if (
        limited_write.get("model_autonomous_write_invocation")
        != "DISABLED_V1"
    ):
        raise RuntimeError(
            "Autonomous model write invocation must remain disabled."
        )

    autonomy = config.get("autonomy")
    if not isinstance(autonomy, dict):
        raise RuntimeError("Autonomy configuration missing.")
    if autonomy.get("authority") != autonomy_contract.AUTHORITY:
        raise RuntimeError("Autonomy candidate authority mismatch.")
    if (
        autonomy.get("architecture")
        != "REUSE_EXISTING_K7_COGNITIVE_HIERARCHY"
    ):
        raise RuntimeError("Autonomy cognitive hierarchy binding mismatch.")
    if autonomy.get("parallel_agent_brain") != "FORBIDDEN":
        raise RuntimeError("Parallel agent brain is forbidden.")
    if autonomy.get("flat_model_command_loop") != "FORBIDDEN":
        raise RuntimeError("Flat model command loop is forbidden.")
    if (
        autonomy.get("target_workspace_object_id")
        != autonomy_contract.TARGET_WORKSPACE_OBJECT_ID
        or autonomy.get("target_source_path")
        != autonomy_contract.TARGET_RELATIVE_PATH
    ):
        raise RuntimeError("Autonomy target binding mismatch.")
    if autonomy.get("allowed_green_tools") != list(
        autonomy_contract.ALLOWED_GREEN_TOOLS
    ):
        raise RuntimeError("Autonomy GREEN tool profile set mismatch.")
    if autonomy.get("network_authority") != "NONE":
        raise RuntimeError("Autonomy network authority must remain NONE.")
    if autonomy.get("general_action_authority") != "NONE":
        raise RuntimeError("Autonomy general action authority must remain NONE.")
    if (
        autonomy.get("host_write_authority")
        != autonomy_contract.HOST_WRITE_AUTHORITY
    ):
        raise RuntimeError("Autonomy host-write boundary mismatch.")
    if autonomy.get("git_mutation_authority") != "NONE":
        raise RuntimeError("Autonomy Git mutation authority must remain NONE.")
    if autonomy.get("shell_authority") != "NONE":
        raise RuntimeError("Autonomy shell authority must remain NONE.")
    if autonomy.get("self_authorization") != "FORBIDDEN":
        raise RuntimeError("Autonomy self-authorization must remain forbidden.")
    if autonomy.get("authority_file_mutation") != "FORBIDDEN":
        raise RuntimeError(
            "Autonomy authority-file mutation must remain forbidden."
        )
    if (
        autonomy.get("persistent_apply_boundary")
        != autonomy_contract.PERSISTENT_APPLY_BOUNDARY
    ):
        raise RuntimeError("Autonomy persistent apply boundary mismatch.")

    if safety["general_action_authority"] != "NONE":
        raise RuntimeError("General action authority must remain NONE.")
    if safety["network_authority"] != "NONE":
        raise RuntimeError("Network authority must remain NONE.")
    if safety.get("task_scoped_general_action_authority") != "TASK_SCOPED":
        raise RuntimeError("Task-scoped general action authority mismatch.")
    if safety.get("task_scoped_network_authority") != "TASK_SCOPED":
        raise RuntimeError("Task-scoped network authority mismatch.")
    if safety.get("task_scoped_scope_authority") != "ALL_TASK_SCOPED_EFFECTS":
        raise RuntimeError("Task-scoped scope authority mismatch.")
    if safety.get("task_scoped_requires") != (
        "MANDATE_VALID_HASH_BOUND_SINGLE_USE"
    ):
        raise RuntimeError("Task-scoped mandate requirement mismatch.")

    for name, value in qml_initial_properties(config).items():
        if not root.setProperty(name, value):
            raise RuntimeError("Main window rejected startup property: " + name)

    root.setProperty("shellLoadLabel", "PREPARING DESKTOP…")
    root.setProperty(
        "shellLoadCurrent",
        "Loading workspace surfaces and local services",
    )
    startup = DesktopStartupCoordinator(root, app)
    app._gg_startup_coordinator = startup  # type: ignore[attr-defined]
    if not startup.start():
        return
    if not root.setProperty("startupModulesReady", True):
        raise RuntimeError("Main window rejected startup module state")


def main() -> int:
    """Compatibility entry for callers that already imported this module."""
    if QApplication.instance() is None:
        from backend.native_webview import initialize_native_webview
        initialize_native_webview()
    app = QApplication.instance() or QApplication(sys.argv)
    desk_font = QFont("monospace")
    desk_font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(desk_font)
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    roots = engine.rootObjects()
    if not roots:
        return 2

    root = roots[0]
    app._gg_qml_engine = engine  # type: ignore[attr-defined]
    root.showMaximized()
    initialize_loaded_window(root, app)

    from startup import run_event_loop
    return run_event_loop(app, engine)

if __name__ == "__main__":
    if (
        len(sys.argv) == 3
        and sys.argv[1] == SELFDEV_CONTROLLER_MODE
    ):
        try:
            raise SystemExit(
                _selfdev_controller(sys.argv[2])
            )
        except Exception as exc:
            print(
                "SELFDEV_CONTROLLER=STOP",
                file=sys.stderr,
            )
            print(
                "SELFDEV_STOP_REASON="
                + type(exc).__name__
                + ":"
                + str(exc),
                file=sys.stderr,
            )
            raise SystemExit(1)

    if (
        len(sys.argv) in (4, 5)
        and sys.argv[1] == SELFDEV_SYNTHETIC_MODE
    ):
        try:
            synthetic_repo = (
                sys.argv[4]
                if len(sys.argv) == 5
                else None
            )

            raise SystemExit(
                _selfdev_controller(
                    sys.argv[2],
                    sys.argv[3],
                    synthetic_repo,
                )
            )
        except Exception as exc:
            print(
                "SELFDEV_CONTROLLER=STOP",
                file=sys.stderr,
            )
            print(
                "SELFDEV_STOP_REASON="
                + type(exc).__name__
                + ":"
                + str(exc),
                file=sys.stderr,
            )
            raise SystemExit(1)

    if (
        len(sys.argv) == 2
        and sys.argv[1] == SELFDEV_SELFTEST_MODE
    ):
        raise SystemExit(_selfdev_selftest())

    raise SystemExit(main())
