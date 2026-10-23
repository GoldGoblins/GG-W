from __future__ import annotations
import shlex
from .contract import Diagnostic, Status

DANGEROUS_TOKENS = {"sudo", "su", "doas"}

def analyze_shell(source: str, source_name: str) -> list[Diagnostic]:
    if not source.strip():
        return [Diagnostic(Status.INCOMPLETE, "SH_EMPTY", "Shell draft is empty.", source_name)]
    findings: list[Diagnostic] = []
    try:
        tokens = shlex.split(source, comments=True, posix=True)
    except ValueError as exc:
        return [Diagnostic(
            Status.INCOMPLETE,
            "SH_AUTHORING_INCOMPLETE",
            str(exc),
            source_name,
            blocking=False,
        )]
    for token in tokens:
        if token in DANGEROUS_TOKENS:
            findings.append(Diagnostic(
                Status.BLOCKED,
                "SH_PRIVILEGE_TOKEN",
                f"Privilege-escalation token {token!r} is outside Live Aid authoring authority.",
                source_name,
                suggestion="Use a separately approved privileged plan if the operation truly requires it.",
                blocking=True,
            ))
    findings.append(Diagnostic(
        Status.UNKNOWN,
        "SH_STATIC_TOOL_NOT_RUN",
        "Tokenization passed; shellcheck/runtime contract has not yet been verified.",
        source_name,
        suggestion="Run the configured shell static checker in preflight.",
        probe={"kind": "SHELL_STATIC_CHECK"},
    ))
    return findings
