from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path
from typing import Any

from .authoring_session import AuthoringSession
from .contract import Status
from .diagnostic_engine import DiagnosticEngine
from .forensic_resolver import ForensicResolver
from .source_index import SourceIndex


class LiveAidBridgeError(RuntimeError):
    pass


class LiveAidService:
    """Read-only authoring analysis service for a candidate repository.

    The service owns no execution or host-write capability.  It accepts draft
    source bytes supplied by a caller, analyzes them against an observed source
    index, and returns structured diagnostics/probe requests.
    """

    def __init__(self, repo_root: Path):
        root = Path(repo_root)
        if root.is_symlink() or not root.is_dir():
            raise LiveAidBridgeError("REPO_ROOT_INVALID")
        self.repo_root = root.resolve(strict=True)
        # Python symbol checks need a repository index, but QML/JSON/shell
        # analysis does not. Building it here walked and parsed the entire
        # workspace on every desktop launch, even when Live Aid was unused.
        self.index: SourceIndex | None = None
        self.engine = DiagnosticEngine(self.index)
        self.resolver = ForensicResolver(self.index)
        self._sessions: dict[tuple[str, str], AuthoringSession] = {}

    def analyze(
        self,
        *,
        object_id: str,
        source_name: str,
        source: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        if not object_id or len(object_id) > 160:
            raise LiveAidBridgeError("OBJECT_ID_INVALID")
        if not source_name or len(source_name) > 300:
            raise LiveAidBridgeError("SOURCE_NAME_INVALID")
        if len(source.encode("utf-8")) > 262_144:
            raise LiveAidBridgeError("DRAFT_TOO_LARGE")

        detected_language = (
            language or DiagnosticEngine.detect_language(source_name)
        ).casefold()
        if detected_language in {"py", "python"} and self.index is None:
            self.index = SourceIndex.build(self.repo_root)
            self.engine.source_index = self.index
            self.resolver = ForensicResolver(self.index)

        key = (object_id, source_name)
        session = self._sessions.get(key)
        if session is None:
            session = AuthoringSession(
                source_name=source_name,
                engine=self.engine,
                resolver=self.resolver,
            )
            self._sessions[key] = session

        snapshot = session.update(source, language)
        diagnostics = [item.as_dict() for item in snapshot.diagnostics]
        probes = [asdict(item) for item in snapshot.probes]

        return {
            "schema": "gg.live-aid.bridge-response.v1",
            "object_id": object_id,
            "source_name": source_name,
            "sequence": snapshot.sequence,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "status": snapshot.status.value,
            "draft_blocking": False,
            "execution_ready": snapshot.status == Status.PASS,
            "diagnostics": diagnostics,
            "probes": probes,
            "action_authority": "NONE",
            "network_authority": "NONE",
        }
