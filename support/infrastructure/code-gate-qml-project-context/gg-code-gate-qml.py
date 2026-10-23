#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
from typing import Any

VERSION = "1.0.0-candidate.1"
SCHEMA = "gg-code-gate-report-v1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
QML_TIMEOUT_SECONDS = 10

FOUNDATION_TOOL = pathlib.Path("/opt/gg-code-gate/gg-code-gate.py")
RULES_PATH = pathlib.Path("/opt/gg-code-gate-qml/secret-rules.json")
QMLLINT = pathlib.Path("/opt/gg-code-gate-qml/runtime/PySide6/qmllint")
QML_ROOT = pathlib.Path("/opt/gg-code-gate-qml/runtime/PySide6/Qt/qml")
EXPECTED_TARGET = pathlib.Path("/input/source")
EXPECTED_OUTPUT = pathlib.Path("/output/report.json")

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_HARNESS = 2


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_foundation() -> Any:
    spec = importlib.util.spec_from_file_location(
        "gg_foundation_code_gate",
        FOUNDATION_TOOL,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Foundation Code Gate kunde inte laddas")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_secret_findings(findings: Any) -> list[dict[str, Any]]:
    if not isinstance(findings, list):
        raise RuntimeError("Foundation secret scan gav oväntat format")

    allowed = {
        "id",
        "rule",
        "rule_id",
        "rule_name",
        "name",
        "line",
        "line_number",
        "column",
        "kind",
        "type",
    }
    result: list[dict[str, Any]] = []

    for finding in findings:
        if not isinstance(finding, dict):
            result.append({"finding": "REDACTED"})
            continue

        safe: dict[str, Any] = {}
        for key, value in finding.items():
            if str(key).lower() not in allowed:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[str(key)] = value

        result.append(safe or {"finding": "REDACTED"})

    return result


def runtime_facts() -> dict[str, Any]:
    cap_eff = None
    no_new_privileges = None

    status = pathlib.Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("CapEff:"):
                cap_eff = line.split(":", 1)[1].strip()
            elif line.startswith("NoNewPrivs:"):
                raw = line.split(":", 1)[1].strip()
                no_new_privileges = raw == "1"

    default_routes = 0
    route = pathlib.Path("/proc/net/route")
    if route.is_file():
        for index, line in enumerate(
            route.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            if index == 0:
                continue
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "00000000":
                default_routes += 1

    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "cap_eff": cap_eff,
        "no_new_privileges": no_new_privileges,
        "default_route_count": default_routes,
    }


def _safe_diagnostics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    result: list[dict[str, Any]] = []
    allowed = {
        "id",
        "type",
        "line",
        "column",
        "charOffset",
        "length",
        "message",
    }

    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        safe: dict[str, Any] = {}
        for key in allowed:
            if key not in item:
                continue
            field = item[key]
            if isinstance(field, str):
                safe[key] = field[:512]
            elif isinstance(field, (int, float, bool)) or field is None:
                safe[key] = field
        result.append(safe)

    return result


def evaluate_qmllint_json(
    stdout_text: str,
    expected_target: str,
    return_code: int | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "json_valid": False,
        "file_identity_ok": False,
        "files_count": None,
        "success": None,
        "diagnostics": [],
        "harness_error": None,
        "gate_pass": False,
    }

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError:
        result["harness_error"] = "invalid_json"
        return result

    result["json_valid"] = True

    if not isinstance(payload, dict):
        result["harness_error"] = "json_root_not_object"
        return result

    files = payload.get("files")
    if not isinstance(files, list):
        result["harness_error"] = "files_not_list"
        return result

    result["files_count"] = len(files)
    if len(files) != 1:
        result["harness_error"] = "file_count_mismatch"
        return result

    entry = files[0]
    if not isinstance(entry, dict):
        result["harness_error"] = "file_entry_not_object"
        return result

    filename = entry.get("filename")
    result["file_identity_ok"] = filename == expected_target
    if not result["file_identity_ok"]:
        result["harness_error"] = "file_identity_mismatch"
        return result

    success = entry.get("success")
    if not isinstance(success, bool):
        result["harness_error"] = "success_not_boolean"
        return result

    diagnostics = _safe_diagnostics(entry.get("warnings"))
    result["success"] = success
    result["diagnostics"] = diagnostics

    result["gate_pass"] = (
        return_code == 0
        and success
        and not diagnostics
    )
    return result


def run_qmllint(target: pathlib.Path) -> dict[str, Any]:
    argv = [
        str(QMLLINT),
        "--bare",
        "--ignore-settings",
        "-I",
        str(QML_ROOT),
        "--json",
        "-",
        str(target),
    ]

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/nonexistent",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "QML_DISABLE_DISK_CACHE": "1",
    }

    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=env,
            cwd="/work",
            timeout=QML_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "argv": argv,
            "return_code": None,
            "timed_out": True,
            "stdout": "",
            "stderr": "",
        }

    return {
        "argv": argv,
        "return_code": completed.returncode,
        "timed_out": False,
        "stdout": completed.stdout[:1024 * 1024],
        "stderr": completed.stderr[:1024 * 1024],
    }


def write_report(path: pathlib.Path, report: dict[str, Any]) -> None:
    if path != EXPECTED_OUTPUT:
        raise RuntimeError("Rapportmålet avviker från /output/report.json")
    if path.parent.is_symlink():
        raise RuntimeError("Rapportkatalogen får inte vara symlänk")

    data = (
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    temporary = path.with_name(".report.json.tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def base_report(name: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "tool_version": VERSION,
        "status": "FAIL",
        "source": {
            "original_name": name,
            "container_path": str(EXPECTED_TARGET),
            "sha256": None,
            "size_bytes": None,
            "language": "qml",
        },
        "secret_findings": [],
        "static_checks": [],
        "execution_requested": False,
        "execution": None,
        "runtime": runtime_facts(),
        "policy": {
            "network_expected": "none",
            "rootfs_expected": "read-only",
            "source_expected": "read-only",
            "capabilities_expected": "none",
            "no_new_privileges_expected": True,
            "qml_flags": [
                "--bare",
                "--ignore-settings",
                "-I",
                "LOCKED_QML_ROOT",
                "--json",
                "-",
            ],
            "external_plugin_paths_allowed": False,
            "uid_gid_expected": "1000:1000",
        },
        "qml": {
            "qml_invoked": False,
            "qmllint_sha256": None,
            "argv": None,
            "return_code": None,
            "timed_out": False,
            "json_valid": False,
            "file_identity_ok": False,
            "files_count": None,
            "success": None,
            "diagnostics": [],
            "harness_error": None,
        },
        "messages": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    target = pathlib.Path(args.target)
    output = pathlib.Path(args.output)
    report = base_report(args.name)

    try:
        if target != EXPECTED_TARGET:
            raise RuntimeError("Målfilen måste vara /input/source")
        if output != EXPECTED_OUTPUT:
            raise RuntimeError("Rapportmålet måste vara /output/report.json")
        if pathlib.Path(args.name).name != args.name:
            raise RuntimeError("Originalnamnet får inte innehålla sökväg")
        if target.is_symlink():
            raise RuntimeError("Målfilen får inte vara symlänk")
        if not target.is_file():
            raise RuntimeError("Målfilen saknas eller är inte vanlig fil")

        size = target.stat().st_size
        if size > MAX_SOURCE_BYTES:
            raise RuntimeError("Målfilen är större än 2 MiB")

        if not FOUNDATION_TOOL.is_file():
            raise RuntimeError("Foundation Code Gate saknas i basimagen")
        if not RULES_PATH.is_file():
            raise RuntimeError("Låsta secret-rules saknas")
        if not QMLLINT.is_file():
            raise RuntimeError("qmllint saknas")
        if not QML_ROOT.is_dir():
            raise RuntimeError("Låst QML-root saknas")

        report["source"]["sha256"] = sha256_file(target)
        report["source"]["size_bytes"] = size

        runtime = report["runtime"]
        if runtime.get("uid") != 1000 or runtime.get("gid") != 1000:
            report["messages"].append("Sandbox UID/GID avviker från låst policy.")
            write_report(output, report)
            return EXIT_FAIL
        if str(runtime.get("cap_eff") or "") not in {"0", "0000000000000000"}:
            report["messages"].append("Effektiva capabilities är inte noll.")
            write_report(output, report)
            return EXIT_FAIL
        if runtime.get("no_new_privileges") is not True:
            report["messages"].append("NoNewPrivs är inte aktivt.")
            write_report(output, report)
            return EXIT_FAIL
        if runtime.get("default_route_count") != 0:
            report["messages"].append("En default route upptäcktes i sandboxen.")
            write_report(output, report)
            return EXIT_FAIL

        source_text = target.read_text(
            encoding="utf-8",
            errors="strict",
        )

        foundation = load_foundation()
        rules = foundation.load_rules(RULES_PATH)
        findings = foundation.scan_secrets(source_text, rules)
        safe_findings = safe_secret_findings(findings)
        report["secret_findings"] = safe_findings

        if safe_findings:
            report["messages"].append(
                "Hemlighetsmönster upptäcktes. qmllint kördes inte."
            )
            report["status"] = "FAIL"
            write_report(output, report)
            return EXIT_FAIL

        qmllint_sha = sha256_file(QMLLINT)
        qml_result = run_qmllint(target)
        report["qml"]["qml_invoked"] = True
        report["qml"]["qmllint_sha256"] = qmllint_sha
        report["qml"]["argv"] = qml_result["argv"]
        report["qml"]["return_code"] = qml_result["return_code"]
        report["qml"]["timed_out"] = qml_result["timed_out"]

        if qml_result["timed_out"]:
            report["messages"].append("qmllint timeout")
            report["static_checks"].append(
                {
                    "name": "qmllint",
                    "status": "FAIL",
                    "reason": "timeout",
                }
            )
            write_report(output, report)
            return EXIT_FAIL

        evaluation = evaluate_qmllint_json(
            qml_result["stdout"],
            str(target),
            qml_result["return_code"],
        )

        for key in (
            "json_valid",
            "file_identity_ok",
            "files_count",
            "success",
            "diagnostics",
            "harness_error",
        ):
            report["qml"][key] = evaluation[key]

        if qml_result["stderr"]:
            report["messages"].append(
                "qmllint skrev till stderr; innehållet lagras inte i rapporten."
            )

        if evaluation["gate_pass"]:
            report["static_checks"].append(
                {
                    "name": "qmllint",
                    "status": "PASS",
                    "return_code": qml_result["return_code"],
                }
            )
            report["status"] = "PASS"
            report["messages"].append("QML-kontraktet passerade.")
            write_report(output, report)
            return EXIT_PASS

        report["static_checks"].append(
            {
                "name": "qmllint",
                "status": "FAIL",
                "return_code": qml_result["return_code"],
                "harness_error": evaluation["harness_error"],
            }
        )

        if evaluation["harness_error"]:
            report["messages"].append(
                "qmllint JSON bröt Gate-kontraktet."
            )
        elif evaluation["success"] is False:
            report["messages"].append(
                "QML avvisades av qmllint."
            )
        else:
            report["messages"].append(
                "QML uppfyllde inte det låsta Gate-kontraktet."
            )

        report["status"] = "FAIL"
        write_report(output, report)
        return EXIT_FAIL

    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        report["status"] = "FAIL"
        report["messages"].append(
            "Harnessfel: " + str(exc)[:512]
        )
        try:
            write_report(output, report)
        except (OSError, RuntimeError):
            return EXIT_HARNESS
        return EXIT_HARNESS


if __name__ == "__main__":
    raise SystemExit(main())
