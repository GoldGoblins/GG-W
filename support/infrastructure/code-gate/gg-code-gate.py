#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time
from typing import Any

VERSION = "1.0.0"
RULES_PATH = pathlib.Path("/opt/gg-code-gate/secret-rules.json")
MAX_OUTPUT_CHARS = 12000
STATIC_TIMEOUT_SECONDS = 25
EXEC_TIMEOUT_SECONDS = 20

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_CONDITIONAL = 2


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rules(path: pathlib.Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = raw.get("rules")
    if not isinstance(rules, list):
        raise RuntimeError("secret-rules.json saknar en giltig rules-lista")

    parsed: list[dict[str, str]] = []
    for item in rules:
        if not isinstance(item, dict):
            raise RuntimeError("Ogiltig hemlighetsregel")
        rule_id = item.get("id")
        description = item.get("description")
        pattern = item.get("pattern")
        if not all(isinstance(value, str) and value for value in (rule_id, description, pattern)):
            raise RuntimeError("Ofullständig hemlighetsregel")
        re.compile(pattern)
        parsed.append(
            {
                "id": rule_id,
                "description": description,
                "pattern": pattern,
            }
        )
    return parsed


def sanitize_text(text: str, rules: list[dict[str, str]]) -> str:
    sanitized = text
    for rule in rules:
        sanitized = re.sub(rule["pattern"], "[REDACTED]", sanitized)
    if len(sanitized) > MAX_OUTPUT_CHARS:
        omitted = len(sanitized) - MAX_OUTPUT_CHARS
        sanitized = sanitized[:MAX_OUTPUT_CHARS] + f"\n...[{omitted} tecken utelämnade]..."
    return sanitized


def command_result(
    command: list[str],
    *,
    cwd: pathlib.Path | None,
    env: dict[str, str],
    timeout_seconds: int,
    rules: list[dict[str, str]],
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        timed_out = False
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr += f"\nTimeout efter {timeout_seconds} sekunder."

    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "command": [str(part) for part in command],
        "command_display": shlex.join(command),
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "stdout": sanitize_text(stdout, rules),
        "stderr": sanitize_text(stderr, rules),
    }


def detect_language(name: str, explicit: str) -> str | None:
    if explicit != "auto":
        return explicit

    lower_name = name.lower()
    if lower_name.endswith((".sh", ".bash")):
        return "bash"
    if lower_name.endswith(".py"):
        return "python"
    if lower_name.endswith(".php"):
        return "php"
    if lower_name.endswith(".json"):
        return "json"
    return None


def scan_secrets(
    source_text: str,
    rules: list[dict[str, str]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = source_text.splitlines()

    for line_number, line in enumerate(lines, start=1):
        for rule in rules:
            for match in re.finditer(rule["pattern"], line):
                findings.append(
                    {
                        "rule_id": rule["id"],
                        "description": rule["description"],
                        "line": line_number,
                        "column": match.start() + 1,
                        "match_length": len(match.group(0)),
                        "value": "[REDACTED]",
                    }
                )
    return findings


def runtime_facts() -> dict[str, Any]:
    status_path = pathlib.Path("/proc/self/status")
    route_path = pathlib.Path("/proc/net/route")
    cap_eff = None
    no_new_privs = None

    if status_path.is_file():
        for line in status_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            if line.startswith("CapEff:"):
                cap_eff = line.split(":", 1)[1].strip()
            elif line.startswith("NoNewPrivs:"):
                no_new_privs = line.split(":", 1)[1].strip()

    default_route_present = False
    if route_path.is_file():
        route_lines = route_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()[1:]
        for line in route_lines:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "00000000":
                default_route_present = True
                break

    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "cap_eff": cap_eff,
        "no_new_privs": no_new_privs,
        "default_route_present": default_route_present,
        "cwd": os.getcwd(),
        "home": os.environ.get("HOME"),
        "tmpdir": os.environ.get("TMPDIR"),
    }


def static_checks(
    language: str,
    target: pathlib.Path,
    *,
    env: dict[str, str],
    rules: list[dict[str, str]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    if language == "bash":
        checks.append(
            {
                "name": "bash-syntax",
                **command_result(
                    ["/usr/bin/bash", "-n", str(target)],
                    cwd=None,
                    env=env,
                    timeout_seconds=STATIC_TIMEOUT_SECONDS,
                    rules=rules,
                ),
            }
        )
        checks.append(
            {
                "name": "shellcheck",
                **command_result(
                    [
                        "/usr/bin/shellcheck",
                        "--norc",
                        "--severity=info",
                        "--format=json",
                        str(target),
                    ],
                    cwd=None,
                    env=env,
                    timeout_seconds=STATIC_TIMEOUT_SECONDS,
                    rules=rules,
                ),
            }
        )
    elif language == "python":
        try:
            source = target.read_text(encoding="utf-8")
            ast.parse(source, filename=str(target))
            ast_check = {
                "name": "python-ast",
                "command": ["python-ast"],
                "command_display": "python-ast",
                "return_code": 0,
                "timed_out": False,
                "duration_ms": 0,
                "stdout": "",
                "stderr": "",
            }
        except (SyntaxError, UnicodeDecodeError) as exc:
            ast_check = {
                "name": "python-ast",
                "command": ["python-ast"],
                "command_display": "python-ast",
                "return_code": 1,
                "timed_out": False,
                "duration_ms": 0,
                "stdout": "",
                "stderr": sanitize_text(str(exc), rules),
            }
        checks.append(ast_check)
        checks.append(
            {
                "name": "ruff",
                **command_result(
                    [
                        "/usr/bin/ruff",
                        "check",
                        "--no-cache",
                        "--output-format=json",
                        str(target),
                    ],
                    cwd=None,
                    env=env,
                    timeout_seconds=STATIC_TIMEOUT_SECONDS,
                    rules=rules,
                ),
            }
        )
    elif language == "php":
        checks.append(
            {
                "name": "php-syntax",
                **command_result(
                    ["/usr/bin/php", "-n", "-l", str(target)],
                    cwd=None,
                    env=env,
                    timeout_seconds=STATIC_TIMEOUT_SECONDS,
                    rules=rules,
                ),
            }
        )
    elif language == "json":
        checks.append(
            {
                "name": "json-parse",
                **command_result(
                    ["/usr/bin/jq", "-e", ".", str(target)],
                    cwd=None,
                    env=env,
                    timeout_seconds=STATIC_TIMEOUT_SECONDS,
                    rules=rules,
                ),
            }
        )
    else:
        raise RuntimeError(f"Stöd saknas för språk: {language}")

    return checks


def execution_command(language: str, target: pathlib.Path) -> list[str] | None:
    if language == "bash":
        return ["/usr/bin/bash", "--noprofile", "--norc", str(target)]
    if language == "python":
        return ["/usr/bin/python3", "-I", "-B", str(target)]
    if language == "php":
        return ["/usr/bin/php", "-n", str(target)]
    if language == "json":
        return None
    return None


def write_report(
    report_path: pathlib.Path,
    report: dict[str, Any],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    report_path.write_bytes(encoded)
    report_path.chmod(0o600)
    digest = hashlib.sha256(encoded).hexdigest()
    checksum_path = report_path.with_suffix(report_path.suffix + ".sha256")
    checksum_path.write_text(
        f"{digest}  {report_path.name}\n",
        encoding="utf-8",
    )
    checksum_path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GG Code Gate deterministic foundation",
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--language",
        choices=("auto", "bash", "python", "php", "json"),
        default="auto",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    target = pathlib.Path(args.target)
    report_path = pathlib.Path(args.output)
    rules = load_rules(RULES_PATH)

    base_report: dict[str, Any] = {
        "schema": "gg-code-gate-report-v1",
        "tool_version": VERSION,
        "status": "FAIL",
        "source": {
            "original_name": args.name,
            "container_path": str(target),
            "sha256": None,
            "size_bytes": None,
            "language": None,
        },
        "secret_findings": [],
        "static_checks": [],
        "execution_requested": bool(args.execute),
        "execution": None,
        "runtime": runtime_facts(),
        "policy": {
            "network_expected": "none",
            "rootfs_expected": "read-only",
            "source_expected": "read-only",
            "capabilities_expected": "none",
            "no_new_privileges_expected": True,
        },
        "messages": [],
    }

    try:
        if target.is_symlink():
            raise RuntimeError("Målfilen får inte vara en symlänk")
        if not target.is_file():
            raise RuntimeError("Målfilen saknas eller är inte en vanlig fil")
        if target.stat().st_size > 2 * 1024 * 1024:
            raise RuntimeError("Målfilen är större än 2 MiB")

        language = detect_language(args.name, args.language)
        base_report["source"]["sha256"] = sha256_file(target)
        base_report["source"]["size_bytes"] = target.stat().st_size
        base_report["source"]["language"] = language

        source_text = target.read_text(
            encoding="utf-8",
            errors="strict",
        )
        findings = scan_secrets(source_text, rules)
        base_report["secret_findings"] = findings

        if findings:
            base_report["status"] = "FAIL"
            base_report["messages"].append(
                "Hemlighetsmönster upptäcktes. Innehållet kördes inte."
            )
            write_report(report_path, base_report)
            return EXIT_FAIL

        if language is None:
            base_report["status"] = "CONDITIONAL"
            base_report["messages"].append(
                "Filtypen stöds inte av foundation-grinden."
            )
            write_report(report_path, base_report)
            return EXIT_CONDITIONAL

        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/nonexistent",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GG_CODE_GATE": "1",
        }

        checks = static_checks(
            language,
            target,
            env=env,
            rules=rules,
        )
        base_report["static_checks"] = checks

        failed_checks = [
            check
            for check in checks
            if check.get("return_code") != 0
        ]
        if failed_checks:
            base_report["status"] = "FAIL"
            base_report["messages"].append(
                "En eller flera statiska kontroller misslyckades."
            )
            write_report(report_path, base_report)
            return EXIT_FAIL

        if args.execute:
            command = execution_command(language, target)
            if command is None:
                base_report["execution"] = {
                    "skipped": True,
                    "reason": "Ingen exekveringsfas definierad för JSON.",
                }
            else:
                execution = command_result(
                    command,
                    cwd=pathlib.Path("/work"),
                    env=env,
                    timeout_seconds=EXEC_TIMEOUT_SECONDS,
                    rules=rules,
                )
                execution["name"] = "sandbox-execution"
                base_report["execution"] = execution
                if execution["return_code"] != 0:
                    base_report["status"] = "FAIL"
                    base_report["messages"].append(
                        "Sandboxexekveringen misslyckades."
                    )
                    write_report(report_path, base_report)
                    return EXIT_FAIL

        runtime = base_report["runtime"]
        if runtime.get("cap_eff") not in ("0000000000000000", "0"):
            base_report["status"] = "FAIL"
            base_report["messages"].append(
                "Effektiva capabilities är inte noll."
            )
            write_report(report_path, base_report)
            return EXIT_FAIL

        if runtime.get("no_new_privs") != "1":
            base_report["status"] = "FAIL"
            base_report["messages"].append(
                "NoNewPrivs är inte aktivt."
            )
            write_report(report_path, base_report)
            return EXIT_FAIL

        if runtime.get("default_route_present"):
            base_report["status"] = "FAIL"
            base_report["messages"].append(
                "En default route upptäcktes i sandboxen."
            )
            write_report(report_path, base_report)
            return EXIT_FAIL

        base_report["status"] = "PASS"
        base_report["messages"].append(
            "Alla definierade foundation-kontroller passerade."
        )
        write_report(report_path, base_report)
        return EXIT_PASS

    except Exception as exc:
        base_report["status"] = "FAIL"
        base_report["messages"].append(
            f"Internt Code Gate-fel: {type(exc).__name__}: {exc}"
        )
        write_report(report_path, base_report)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
