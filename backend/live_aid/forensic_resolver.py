from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import Diagnostic, Fact
from .source_index import SourceIndex

@dataclass(frozen=True)
class ProbeRequest:
    kind: str
    authority: str
    profile: str | None
    arguments: dict[str, Any]
    reason: str

class ForensicResolver:
    """Reduce UNKNOWN using already-observed source facts first.

    Host/runtime unknowns are converted to typed GREEN probe requests.  This
    module never executes those requests itself.
    """

    def __init__(self, index: SourceIndex | None):
        self.index = index

    def resolve_symbol_search(self, symbol: str) -> tuple[list[Fact], list[ProbeRequest]]:
        hits = []
        if self.index is not None:
            for module, rows in self.index.symbols.items():
                for item in rows:
                    leaf = item.name.split(".")[-1]
                    if leaf == symbol:
                        hits.append(item)
        facts = []
        for item in hits:
            facts.append(Fact(
                key="source.symbol." + symbol,
                value={
                    "module": item.module,
                    "name": item.name,
                    "kind": item.kind,
                    "line": item.line,
                    "signature": item.signature,
                    "path": item.source_path,
                },
                epistemic_class="OBSERVED_CONTENT_BOUND",
                source_kind="SOURCE_INDEX",
                source_id=item.source_path,
                source_sha256=item.source_sha256,
                scope="REPOSITORY_SOURCE",
            ))
        probes = []
        if not facts:
            probes.append(ProbeRequest(
                kind="SAFE_TOOL_SEARCH",
                authority="GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
                profile="SEARCH",
                arguments={"literal": symbol},
                reason="No indexed project symbol matched; search tracked repository bytes before guessing.",
            ))
        return facts, probes

    def resolve(self, diagnostic: Diagnostic) -> tuple[list[Fact], list[ProbeRequest]]:
        probe = diagnostic.probe or {}
        kind = probe.get("kind")
        if kind == "SYMBOL_SEARCH":
            return self.resolve_symbol_search(str(probe["symbol"]))
        if kind == "QML_GATE":
            return [], [ProbeRequest(
                "QML_GATE",
                "YELLOW_OR_PROFILE_BOUND_GATE",
                None,
                {},
                "QML syntax requires the existing QML Gate before execution.",
            )]
        if kind == "SHELL_STATIC_CHECK":
            return [], [ProbeRequest(
                "SHELL_STATIC_CHECK",
                "GATE_PROFILE",
                None,
                {},
                "Run the configured shell checker before execution.",
            )]
        return [], []
