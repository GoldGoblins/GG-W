from __future__ import annotations
from .contract import Diagnostic, Status

def analyze_qml(source: str, source_name: str) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    if not source.strip():
        return [Diagnostic(Status.INCOMPLETE, "QML_EMPTY", "QML draft is empty.", source_name)]
    brace = 0
    quote = None
    escaped = False
    for lineno, line in enumerate(source.splitlines(), 1):
        for char in line:
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in ("'", '"'):
                quote = char
            elif char == "{":
                brace += 1
            elif char == "}":
                brace -= 1
                if brace < 0:
                    findings.append(Diagnostic(
                        Status.FAIL, "QML_BRACE_UNDERFLOW",
                        "Closing brace has no matching opening brace.",
                        source_name, line=lineno, blocking=True,
                    ))
                    brace = 0
    if quote is not None or brace > 0:
        findings.append(Diagnostic(
            Status.INCOMPLETE, "QML_AUTHORING_INCOMPLETE",
            "QML draft appears incomplete while authoring continues.",
            source_name, blocking=False,
        ))
    if not findings:
        findings.append(Diagnostic(
            Status.UNKNOWN,
            "QML_QMLLINT_NOT_RUN",
            "Lightweight authoring scan found no structural error; qmllint/QML Gate has not yet run.",
            source_name,
            suggestion="Run the existing QML Gate during preflight before execution.",
            blocking=False,
            probe={"kind": "QML_GATE"},
        ))
    return findings
