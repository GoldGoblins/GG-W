from __future__ import annotations
import json
from .contract import Diagnostic, Status

def analyze_json(source: str, source_name: str) -> list[Diagnostic]:
    if not source.strip():
        return [Diagnostic(Status.INCOMPLETE, "JSON_EMPTY", "JSON draft is empty.", source_name)]
    try:
        json.loads(source)
    except json.JSONDecodeError as exc:
        # Many edit states are transient.  Only final preflight makes this blocking.
        return [Diagnostic(
            Status.WARNING,
            "JSON_PARSE",
            exc.msg,
            source_name,
            line=exc.lineno,
            column=exc.colno,
            suggestion="Complete or repair the JSON structure.",
            blocking=False,
        )]
    return [Diagnostic(Status.PASS, "JSON_PARSE", "JSON parse passed.", source_name)]
