#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.platform_files import (
    NOFOLLOW,
    secure_open,
)
from backend.platform_support import (
    private_runtime_root,
)


import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.application_paths import HOME, SUPPORT_ROOT, WORKSPACE_ROOT

PROJECT = Path(__file__).resolve().parents[2]
REPO_ROOT = SUPPORT_ROOT if SUPPORT_ROOT.is_dir() else WORKSPACE_ROOT
QML_GATE = REPO_ROOT / "infrastructure/scripts/gg-code-gate-qml"

REQUEST_SCHEMA = "gg.live-aid.qml-preflight-request.v1"
RESPONSE_SCHEMA = "gg.live-aid.qml-preflight-response.v1"

EXPECTED_QML_GATE_SHA256 = (
    "43bbb965df22d975c97957ef17dce84c"
    "941dc9dfc16aff250ba2a2361f3f1aa5"
)

MAX_SOURCE_BYTES = 65536
MAX_CONTEXT_FILES = 128
MAX_CONTEXT_FILE_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_TOTAL_BYTES = 8 * 1024 * 1024

_REQUEST_ID = re.compile(r"preflight-[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class QmlPreflightError(RuntimeError):
    pass


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def validate_request(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "request_id",
        "object_id",
        "source_name",
        "source_relative_path",
        "language",
        "source",
        "source_sha256",
    }

    if set(value) != required:
        raise QmlPreflightError("REQUEST_FIELDS")

    if value["schema"] != REQUEST_SCHEMA:
        raise QmlPreflightError("REQUEST_SCHEMA")

    request_id = value["request_id"]

    if (
        not isinstance(request_id, str)
        or _REQUEST_ID.fullmatch(request_id) is None
    ):
        raise QmlPreflightError("REQUEST_ID")

    object_id = value["object_id"]

    if (
        not isinstance(object_id, str)
        or not object_id
        or len(object_id) > 160
    ):
        raise QmlPreflightError("OBJECT_ID")

    source_name = value["source_name"]

    if (
        not isinstance(source_name, str)
        or not source_name
        or len(source_name) > 300
    ):
        raise QmlPreflightError("SOURCE_NAME")

    relative_raw = value["source_relative_path"]

    if not isinstance(relative_raw, str) or not relative_raw:
        raise QmlPreflightError("SOURCE_RELATIVE_PATH")

    relative = Path(relative_raw)

    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix.lower() != ".qml"
    ):
        raise QmlPreflightError("SOURCE_RELATIVE_PATH_POLICY")

    if relative.name != source_name:
        raise QmlPreflightError("SOURCE_NAME_BINDING")

    if value["language"] != "qml":
        raise QmlPreflightError("LANGUAGE")

    source = value["source"]

    if not isinstance(source, str):
        raise QmlPreflightError("SOURCE_TYPE")

    encoded = source.encode("utf-8")

    if len(encoded) > MAX_SOURCE_BYTES:
        raise QmlPreflightError("SOURCE_TOO_LARGE")

    source_sha = value["source_sha256"]

    if (
        not isinstance(source_sha, str)
        or _SHA256.fullmatch(source_sha) is None
        or source_sha != _sha_bytes(encoded)
    ):
        raise QmlPreflightError("SOURCE_SHA256")

    return value


def validate_response(
    value: dict[str, Any],
    *,
    expected_request_id: str,
    expected_object_id: str,
    expected_source_sha256: str,
) -> dict[str, Any]:
    if value.get("schema") != RESPONSE_SCHEMA:
        raise QmlPreflightError("RESPONSE_SCHEMA")

    if value.get("request_id") != expected_request_id:
        raise QmlPreflightError("RESPONSE_REQUEST_BINDING")

    if value.get("object_id") != expected_object_id:
        raise QmlPreflightError("RESPONSE_OBJECT_BINDING")

    if value.get("source_sha256") != expected_source_sha256:
        raise QmlPreflightError("RESPONSE_SOURCE_BINDING")

    status = value.get("status")

    if status not in {"PASS", "FAIL"}:
        raise QmlPreflightError("RESPONSE_STATUS")

    if value.get("gate_profile") != "QML":
        raise QmlPreflightError("RESPONSE_GATE_PROFILE")

    if value.get("gate_status") != status:
        raise QmlPreflightError("RESPONSE_GATE_STATUS")

    if value.get("profile_bound_pass") is not (status == "PASS"):
        raise QmlPreflightError("RESPONSE_PROFILE_BOUND_PASS")

    if value.get("gate_pass_is_profile_bound_only") is not True:
        raise QmlPreflightError("RESPONSE_PROFILE_SCOPE")

    if value.get("human_trigger_required") is not True:
        raise QmlPreflightError("RESPONSE_TRIGGER_AUTHORITY")

    if value.get("temporary_repo_intake_removed") is not True:
        raise QmlPreflightError("RESPONSE_TEMP_INTAKE_EFFECT")

    if value.get("persistent_source_write") is not False:
        raise QmlPreflightError("RESPONSE_PERSISTENT_WRITE")

    if value.get("action_authority") != "NONE":
        raise QmlPreflightError("RESPONSE_ACTION_AUTHORITY")

    if value.get("execution_authority") != "NONE":
        raise QmlPreflightError("RESPONSE_EXECUTION_AUTHORITY")

    if value.get("network_authority") != "NONE":
        raise QmlPreflightError("RESPONSE_NETWORK_AUTHORITY")

    if value.get("model_inference") != "NONE":
        raise QmlPreflightError("RESPONSE_MODEL_INFERENCE")

    report_sha = value.get("gate_report_sha256")

    if (
        not isinstance(report_sha, str)
        or _SHA256.fullmatch(report_sha) is None
    ):
        raise QmlPreflightError("RESPONSE_REPORT_SHA")

    wrapper_sha = value.get("gate_wrapper_sha256")

    if wrapper_sha != EXPECTED_QML_GATE_SHA256:
        raise QmlPreflightError("RESPONSE_WRAPPER_SHA")

    diagnostics = value.get("diagnostics")

    if not isinstance(diagnostics, list):
        raise QmlPreflightError("RESPONSE_DIAGNOSTICS")

    return value


def _diagnostic_line(item: dict[str, Any]) -> int:
    line = item.get("line")

    if isinstance(line, int):
        return line

    location = item.get("location")

    if isinstance(location, dict):
        direct = location.get("line")

        if isinstance(direct, int):
            return direct

        start = location.get("start")

        if isinstance(start, dict):
            nested = start.get("line")

            if isinstance(nested, int):
                return nested

    return -1


def _normalize_diagnostic(
    item: dict[str, Any],
    *,
    source_name: str,
) -> dict[str, Any]:
    code = (
        item.get("id")
        or item.get("code")
        or item.get("type")
        or "QML_GATE_DIAGNOSTIC"
    )

    message = item.get("message")

    if not isinstance(message, str) or not message:
        message = json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
        )

    return {
        "status": "FAIL",
        "code": str(code),
        "message": message,
        "source_name": source_name,
        "line": _diagnostic_line(item),
        "suggestion": (
            "Resolve the attested QML Gate diagnostic "
            "before any execution boundary."
        ),
        "blocking": True,
        "evidence": [],
        "probe": None,
    }


def build_response_from_gate_report(
    request: dict[str, Any],
    report: dict[str, Any],
    *,
    gate_report_path: str,
    gate_report_sha256: str,
    wrapper_return_code: int,
) -> dict[str, Any]:
    request = validate_request(request)

    if report.get("schema") != "gg-code-gate-report-v1":
        raise QmlPreflightError("GATE_REPORT_SCHEMA")

    gate_status = report.get("status")

    if gate_status not in {"PASS", "FAIL"}:
        raise QmlPreflightError("GATE_REPORT_STATUS")

    source = report.get("source")

    if not isinstance(source, dict):
        raise QmlPreflightError("GATE_REPORT_SOURCE")

    if source.get("sha256") != request["source_sha256"]:
        raise QmlPreflightError("GATE_REPORT_SOURCE_BINDING")

    qml = report.get("qml")

    if not isinstance(qml, dict):
        raise QmlPreflightError("GATE_REPORT_QML")

    raw_diagnostics = qml.get("diagnostics", [])

    if not isinstance(raw_diagnostics, list):
        raise QmlPreflightError("GATE_REPORT_DIAGNOSTICS")

    diagnostics = [
        _normalize_diagnostic(
            item,
            source_name=request["source_name"],
        )
        for item in raw_diagnostics
        if isinstance(item, dict)
    ]

    if gate_status == "PASS":
        if qml.get("success") is not True:
            raise QmlPreflightError("GATE_PASS_WITHOUT_QML_SUCCESS")

        if wrapper_return_code != 0:
            raise QmlPreflightError("GATE_PASS_WRAPPER_RC")

    else:
        if wrapper_return_code == 0:
            raise QmlPreflightError("GATE_FAIL_WRAPPER_RC")

        if not diagnostics:
            diagnostics = [
                {
                    "status": "FAIL",
                    "code": "QML_GATE_FAILED",
                    "message": (
                        "QML Gate failed without a structured "
                        "diagnostic."
                    ),
                    "source_name": request["source_name"],
                    "line": -1,
                    "suggestion": (
                        "Inspect the attested QML Gate report."
                    ),
                    "blocking": True,
                    "evidence": [],
                    "probe": None,
                }
            ]

    return {
        "schema": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "object_id": request["object_id"],
        "source_name": request["source_name"],
        "source_sha256": request["source_sha256"],
        "status": gate_status,
        "reason": (
            "QML_GATE_PROFILE_PASS"
            if gate_status == "PASS"
            else "QML_GATE_PROFILE_FAIL"
        ),
        "diagnostics": diagnostics,
        "gate_profile": "QML",
        "gate_status": gate_status,
        "profile_bound_pass": gate_status == "PASS",
        "gate_pass_is_profile_bound_only": True,
        "gate_report_path": gate_report_path,
        "gate_report_sha256": gate_report_sha256,
        "gate_wrapper_sha256": EXPECTED_QML_GATE_SHA256,
        "human_trigger_required": True,
        "temporary_repo_intake_removed": True,
        "persistent_source_write": False,
        "action_authority": "NONE",
        "execution_authority": "NONE",
        "network_authority": "NONE",
        "model_inference": "NONE",
    }


def _read_request(path: Path) -> dict[str, Any]:
    runtime_root = private_runtime_root()

    if path.is_symlink() or not path.is_file():
        raise QmlPreflightError("REQUEST_FILE_INVALID")

    resolved = path.resolve(strict=True)

    if not resolved.is_relative_to(runtime_root):
        raise QmlPreflightError("REQUEST_FILE_OUTSIDE_RUNTIME")

    info = resolved.stat()

    if info.st_size < 2 or info.st_size > 131072:
        raise QmlPreflightError("REQUEST_FILE_SIZE")

    value = json.loads(
        resolved.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise QmlPreflightError("REQUEST_JSON_TYPE")

    return validate_request(value)


def _write_new(
    path: Path,
    payload: bytes,
    *,
    mode: int,
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | NOFOLLOW
    )

    fd = secure_open(path, flags, mode)

    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _stage_qml_context(
    request: dict[str, Any],
) -> tuple[Path, Path]:
    relative = Path(request["source_relative_path"])
    original = PROJECT / relative

    if original.is_symlink() or not original.is_file():
        raise QmlPreflightError("ORIGINAL_SOURCE_INVALID")

    project_root = PROJECT.resolve(strict=True)
    original_parent = original.parent.resolve(strict=True)

    if not original_parent.is_relative_to(project_root):
        raise QmlPreflightError("ORIGINAL_SOURCE_ESCAPED_PROJECT")

    token = request["request_id"].removeprefix(
        "preflight-"
    )

    intake = REPO_ROOT / (
        ".gg-live-aid-preflight." + token
    )

    intake.mkdir(mode=0o700)

    count = 0
    total = 0
    target: Path | None = None

    try:
        siblings = sorted(
            original_parent.glob("*.qml")
        )

        for sibling in siblings:
            if sibling.is_symlink() or not sibling.is_file():
                raise QmlPreflightError(
                    "QML_CONTEXT_FILE_INVALID:"
                    + sibling.name
                )

            size = sibling.stat().st_size

            if size > MAX_CONTEXT_FILE_BYTES:
                raise QmlPreflightError(
                    "QML_CONTEXT_FILE_TOO_LARGE:"
                    + sibling.name
                )

            count += 1
            total += size

            if count > MAX_CONTEXT_FILES:
                raise QmlPreflightError(
                    "QML_CONTEXT_FILE_COUNT"
                )

            if total > MAX_CONTEXT_TOTAL_BYTES:
                raise QmlPreflightError(
                    "QML_CONTEXT_TOTAL_BYTES"
                )

            destination = intake / sibling.name

            if sibling.name == request["source_name"]:
                payload = request["source"].encode("utf-8")
                _write_new(
                    destination,
                    payload,
                    mode=0o400,
                )
                target = destination
            else:
                _write_new(
                    destination,
                    sibling.read_bytes(),
                    mode=0o400,
                )

        if target is None:
            raise QmlPreflightError(
                "QML_CONTEXT_TARGET_NOT_FOUND"
            )

        if _sha_file(target) != request["source_sha256"]:
            raise QmlPreflightError(
                "QML_CONTEXT_TARGET_SHA"
            )

        return intake, target

    except BaseException:
        shutil.rmtree(intake, ignore_errors=True)
        raise


def _gate_report_from_output(
    output: str,
) -> tuple[Path, str]:
    report_raw: str | None = None
    sha_raw: str | None = None

    for line in output.splitlines():
        if line.startswith("QML_GATE_REPORT="):
            report_raw = line.split("=", 1)[1]

        elif line.startswith(
            "QML_GATE_REPORT_SHA256="
        ):
            sha_raw = line.split("=", 1)[1]

    if not report_raw or not sha_raw:
        raise QmlPreflightError(
            "QML_GATE_REPORT_NOT_ATTESTED"
        )

    if _SHA256.fullmatch(sha_raw) is None:
        raise QmlPreflightError(
            "QML_GATE_REPORT_SHA_FORMAT"
        )

    report = Path(report_raw)

    if (
        not report.is_absolute()
        or report.is_symlink()
        or not report.is_file()
    ):
        raise QmlPreflightError(
            "QML_GATE_REPORT_PATH"
        )

    actual = _sha_file(report)

    if actual != sha_raw:
        raise QmlPreflightError(
            "QML_GATE_REPORT_SHA_MISMATCH"
        )

    return report, actual


def run_request(
    request_path: Path,
) -> dict[str, Any]:
    request = _read_request(request_path)

    if (
        QML_GATE.is_symlink()
        or not QML_GATE.is_file()
        or _sha_file(QML_GATE)
        != EXPECTED_QML_GATE_SHA256
    ):
        raise QmlPreflightError(
            "QML_GATE_WRAPPER_IDENTITY"
        )

    run_root = request_path.parent
    state = run_root / "state"
    temp = run_root / "tmp"

    state.mkdir(mode=0o700, exist_ok=True)
    temp.mkdir(mode=0o700, exist_ok=True)

    intake, target = _stage_qml_context(request)
    response: dict[str, Any] | None = None

    try:
        env = os.environ.copy()

        env.update(
            {
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin:/bin:" + str(HOME / ".local/bin"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "XDG_STATE_HOME": str(state),
                "TMPDIR": str(temp),
            }
        )

        completed = subprocess.run(
            [
                "/usr/bin/bash",
                str(QML_GATE),
                str(target),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            check=False,
            timeout=90,
        )

        report_path, report_sha = (
            _gate_report_from_output(
                completed.stdout
            )
        )

        report_value = json.loads(
            report_path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(report_value, dict):
            raise QmlPreflightError(
                "QML_GATE_REPORT_JSON_TYPE"
            )

        response = build_response_from_gate_report(
            request,
            report_value,
            gate_report_path=str(report_path),
            gate_report_sha256=report_sha,
            wrapper_return_code=completed.returncode,
        )

    finally:
        shutil.rmtree(intake, ignore_errors=False)

    if intake.exists():
        raise QmlPreflightError(
            "TEMP_REPO_INTAKE_SURVIVED"
        )

    if response is None:
        raise QmlPreflightError(
            "PREFLIGHT_RESPONSE_MISSING"
        )

    return validate_response(
        response,
        expected_request_id=request["request_id"],
        expected_object_id=request["object_id"],
        expected_source_sha256=request["source_sha256"],
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "PREFLIGHT_RUNNER_STOP=ARGUMENT_COUNT",
            file=sys.stderr,
        )
        return 2

    request_path = Path(sys.argv[1])

    try:
        response = run_request(request_path)

        payload = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        response_path = (
            request_path.parent / "response.json"
        )

        _write_new(
            response_path,
            (payload + "\n").encode("utf-8"),
            mode=0o600,
        )

        print(payload)
        return 0

    except Exception as exc:
        print(
            "PREFLIGHT_RUNNER_STOP="
            + type(exc).__name__
            + ":"
            + str(exc),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
