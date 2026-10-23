from __future__ import annotations
from pathlib import Path

from .contract import Diagnostic, Status
from .json_analyzer import analyze_json
from .python_analyzer import analyze_python
from .qml_analyzer import analyze_qml
from .shell_analyzer import analyze_shell
from .source_index import SourceIndex

class DiagnosticEngine:
    def __init__(self, source_index: SourceIndex | None = None):
        self.source_index = source_index

    def analyze(self, source: str, source_name: str, language: str | None = None) -> list[Diagnostic]:
        lang = (language or self.detect_language(source_name)).casefold()
        if lang in {"python", "py"}:
            return analyze_python(source, source_name, self.source_index)
        if lang in {"qml"}:
            return analyze_qml(source, source_name)
        if lang in {"json"}:
            return analyze_json(source, source_name)
        if lang in {"shell", "bash", "sh"}:
            return analyze_shell(source, source_name)
        return [Diagnostic(
            Status.UNKNOWN,
            "LANGUAGE_ADAPTER_MISSING",
            f"No Live Aid language adapter is connected for {lang!r}.",
            source_name,
            blocking=False,
        )]

    @staticmethod
    def detect_language(source_name: str) -> str:
        suffix = Path(source_name).suffix.casefold()
        return {
            ".py": "python",
            ".qml": "qml",
            ".json": "json",
            ".sh": "shell",
            ".bash": "shell",
        }.get(suffix, "unknown")
