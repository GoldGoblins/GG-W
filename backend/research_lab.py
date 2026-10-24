"""Bounded local inspection and evidence handoff for the shared Research desk.

Selected artifacts are read, never executed. External reports remain attributed
to their producer. Saving a lesson creates a proposed method, not verified truth.
"""
from __future__ import annotations

from backend.platform_files import (
    NOFOLLOW,
    NONBLOCK,
    secure_open,
)


from backend.application_paths import DATA_HOME, STATE_ROOT

from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import threading
import uuid
from urllib.parse import unquote, urlparse

from backend import qip_lab, research_desk
from backend.platform_support import local_file_path

SCHEMA = "gg.research-lab.v1"
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_STRINGS = 96
SAMPLE_BYTES = 2 * 1024 * 1024
_DEFAULT_TOOLS_ROOT = STATE_ROOT.parent / 'research-tools' if os.name == 'nt' else DATA_HOME / 'goldgoblins/gg-ai-desktop/research-tools'
TOOLS_ROOT = Path(os.environ.get("GG_RESEARCH_TOOLS_ROOT", str(_DEFAULT_TOOLS_ROOT)))
_REPORTS: OrderedDict[str, dict] = OrderedDict()
_LOCK = threading.RLock()

REFERENCES = [
    {"name": "Ghidra", "url": "https://github.com/NationalSecurityAgency/ghidra",
     "use": "Decompilation, function graphs, references and headless scripts."},
    {"name": "REA", "url": "https://github.com/morluto/rea",
     "use": "Application graphs and evidence with observations, inferences and unknowns."},
    {"name": "REA CLI / Evidence", "url": "https://github.com/morluto/rea/blob/main/docs/cli.md",
     "use": "Local analysis, canonical evidence, snapshots and comparisons."},
    {"name": "Interrupted state review", "url": "https://calif.io/php2shell/",
     "use": "Original GG review method inspired by published PHP2Shell lifetime research; proposals require independent tests.",
     "review_steps": ["Trace the input to parsing, decoding and shared-state boundaries.",
                      "Locate state published before allocation, I/O or another fallible step.",
                      "Identify who can consume that state after failure or cancellation.",
                      "Use a synthetic fixture to interrupt each stage under bounded resources.",
                      "Check rollback, cleanup and the next clean operation.",
                      "Record the exact build, expected and observed result and independent regression test."]},
]


def _path(raw: str) -> Path:
    value = str(raw or "")
    if value.startswith("file:"):
        parsed = urlparse(value)
        if parsed.netloc not in {"", "localhost"} or parsed.query or parsed.fragment:
            raise ValueError("LOCAL_FILE_REQUIRED")
        value = str(local_file_path(value))
    elif "://" in value:
        raise ValueError("LOCAL_FILE_REQUIRED")
    if os.name == 'nt' and value.startswith(('\\\\', '//')):
        raise ValueError('LOCAL_FILE_REQUIRED')
    if not value:
        raise ValueError("SELECT_A_FILE")
    return Path(value).expanduser().resolve(strict=True)


def _read(raw: str, limit: int) -> tuple[Path, bytes]:
    path = _path(raw)
    fd = secure_open(path, os.O_RDONLY | NOFOLLOW | NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("REGULAR_FILE_REQUIRED")
        if before.st_size > limit:
            raise ValueError("FILE_TOO_LARGE")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(data) > limit:
            raise ValueError("FILE_TOO_LARGE")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("FILE_CHANGED_DURING_INSPECTION")
    return path, data


def _error(exc: Exception) -> dict:
    reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    return {"schema": SCHEMA, "status": "ERROR", "reason": reason}


def _cache(report: dict) -> dict:
    with _LOCK:
        key = uuid.uuid4().hex
        report = {"schema": SCHEMA, "report_id": key, "observed_at": research_desk._now(), **report}
        _REPORTS[key] = report
        while len(_REPORTS) > 32:
            _REPORTS.popitem(last=False)
    return report


def tool_inventory() -> dict:
    bundled = TOOLS_ROOT / "rea/node_modules/rea-agents/scripts/rea.mjs"
    rea = str(bundled) if bundled.is_file() else shutil.which("rea")
    candidates = [Path(os.environ["GG_GHIDRA_HOME"])] if os.environ.get("GG_GHIDRA_HOME") else []
    candidates += [TOOLS_ROOT / "ghidra", Path("/opt/ghidra"), Path("/usr/share/ghidra")]
    launcher = 'support/analyzeHeadless.bat' if os.name == 'nt' else 'support/analyzeHeadless'
    ghidra = next((str(p) for p in candidates if (p / launcher).is_file()), "")
    tested = {}
    try:
        verification = json.loads((TOOLS_ROOT / 'verification.json').read_text())
        tested = {row['name']: row.get('status') == 'PASS' for row in verification.get('results', [])}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    rea_state = 'READY' if rea == str(bundled) and tested.get('JavaScript dependency inspection') else ('DETECTED' if rea else 'NOT_INSTALLED')
    ghidra_state = 'READY' if ghidra == str(TOOLS_ROOT / 'ghidra') and tested.get('Native function inspection') and tested.get('Native pseudocode inspection') else ('DETECTED' if ghidra else 'NOT_INSTALLED')
    return {"schema": SCHEMA, "status": "READY", "references": REFERENCES,
            "engines": [
                {"name": "Static inspection", "state": "READY", "detail": "Local file headers, strings with offsets and WASM structure."},
                {"name": "PHP source review", "state": "READY", "detail": "Bounded lexical PHP inventory and call references; no target execution or PHP runtime required."},
                {"name": "REA", "state": rea_state, "path": rea or "",
                 "detail": "JavaScript/Electron graphs; native queries use an analysis provider."},
                {"name": "Ghidra", "state": ghidra_state, "path": ghidra,
                 "detail": "Local function, pseudocode and reference queries through an offline bridge." if os.name == 'nt'
                           else "Local function, pseudocode and reference queries through REA."},
            ]}


def _format(path: Path, data: bytes) -> tuple[str, list[str]]:
    facts: list[str] = []
    if data.startswith(b"\x7fELF"):
        if len(data) < 20 or data[4] not in (1, 2) or data[5] not in (1, 2):
            raise ValueError("INVALID_ELF_HEADER")
        byte_order = "<" if data[5] == 1 else ">"
        machine = struct.unpack_from(byte_order + "H", data, 18)[0]
        facts += [f"ELF {32 if data[4] == 1 else 64}-bit header",
                  f"{'Little' if data[5] == 1 else 'Big'} endian; machine field {machine}"]
        return "ELF", facts
    if data.startswith(b"MZ"):
        if len(data) >= 64:
            offset = struct.unpack_from("<I", data, 60)[0]
            if offset + 6 <= len(data) and data[offset:offset + 4] == b"PE\0\0":
                facts.append(f"PE header at byte {offset}; machine field {struct.unpack_from('<H', data, offset + 4)[0]}")
                return "PE", facts
        return "DOS / MZ", ["MZ header; no validated PE header in this file"]
    if data.startswith(b"\xca\xfe\xba\xbe") and len(data) >= 8:
        architectures = struct.unpack_from(">I", data, 4)[0]
        if 0 < architectures <= 32 and len(data) >= 8 + architectures * 20:
            return "MACH-O FAT CANDIDATE", [f"Universal-binary magic; {architectures} architecture records fit the file"]
        major = struct.unpack_from(">H", data, 6)[0]
        if 45 <= major <= 100:
            return "JAVA CLASS CANDIDATE", [f"Java class magic; major-version field {major}"]
        return "UNKNOWN", ["Shared Java / Mach-O magic; header is inconclusive"]
    if data[:4] in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
        return "MACH-O / FAT", ["Mach-O or universal-binary magic at byte 0"]
    if data.startswith(b"\0asm"):
        return "WASM", ["WebAssembly magic at byte 0"]
    if path.suffix.lower() in {".js", ".mjs", ".cjs", ".jsx", ".tsx", ".php", ".py", ".qml", ".ts"}:
        data.decode("utf-8", errors="strict")
        return "SOURCE", [f"UTF-8 source candidate ({path.suffix}); language inferred from extension"]
    if path.suffix.lower() == ".asar":
        return "ASAR CANDIDATE", ["ASAR filename; use REA to validate the container"]
    return "UNKNOWN", ["No supported file signature; printable bytes are not proof of behavior"]


def inspect_file(raw: str) -> dict:
    try:
        path, data = _read(raw, MAX_ARTIFACT_BYTES)
        if re.search(rb"-----BEGIN (?:(?:RSA|EC|OPENSSH) )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{64,}", data):
            raise ValueError("PRIVATE_KEY_MATERIAL_NOT_ANALYZED")
        kind, facts = _format(path, data)
        strings = []
        for match in re.finditer(rb"[\x20-\x7e]{6,}", data[:SAMPLE_BYTES]):
            strings.append({"offset": match.start(), "text": _redact_text(match.group().decode("ascii"), 160)})
            if len(strings) == MAX_STRINGS:
                break
        wasm = qip_lab.inspect_bytes(data, name=path.name) if kind == "WASM" else {}
        if wasm:
            facts += [f"WASM inspection: {wasm.get('state', 'UNKNOWN')}"]
            if "function_count" in wasm:
                facts += [f"{wasm['function_count']} functions; {len(wasm.get('imports', []))} imports; {len(wasm.get('exports', []))} exports"]
        limits = [f"Strings sampled from the first {min(len(data), SAMPLE_BYTES)} bytes; at most {MAX_STRINGS} entries.",
                  "Headers and strings do not establish runtime behavior or recover source code."]
        return _cache({"status": "INSPECTED", "engine": "Static inspection", "provenance": "LOCAL_STATIC_OBSERVATION",
                       "name": path.name, "path": str(path), "bytes": len(data), "format": kind,
                       "artifact_sha256": hashlib.sha256(data).hexdigest(), "facts": facts,
                       "strings": strings, "limits": limits, "wasm": wasm,
                       "summary": f"{kind} · {len(data)} bytes · {len(strings)} sampled strings"})
    except (OSError, ValueError, UnicodeError) as exc:
        return _error(exc)


def _redact_text(value: str, limit: int = 4000) -> str:
    value = re.sub(r'''(?i)(\bdefine\s*\(\s*['"][^'"\r\n]*(?:password|passwd|secret|token|api.?key|private.?key)[^'"\r\n]*['"]\s*,)[^\r\n]*''',
                   r'\1 [REDACTED]', value)
    value = re.sub(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)",
                   "[PRIVATE KEY REDACTED]", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"(?i)((?:proxy-)?authorization)\s*[:=]\s*(?:bearer|basic)\s+[^\s,;]+",
                   r"\1=[REDACTED]", value)
    value = research_desk._SECRET_RE.sub(r"\1=[REDACTED]", value)
    value = research_desk._LONG_HEX_RE.sub("[ID]", value)
    return value[:limit]


def _clean_tree(value, depth: int = 0):
    if depth > 12:
        return "[depth limit]"
    if isinstance(value, dict):
        header = str(value.get("name") or "").lower()
        sensitive_header = header in {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
        return {str(k)[:80]: ("[REDACTED]" if re.search(r"(?i)password|passwd|secret|token|authorization|api.?key|cookie|private.?key", str(k))
                             or (sensitive_header and str(k).lower() in {"value", "values"})
                             else _clean_tree(v, depth + 1)) for k, v in list(value.items())[:128]}
    if isinstance(value, list):
        return [_clean_tree(v, depth + 1) for v in value[:128]]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported value]"


def import_report(raw: str, engine: str) -> dict:
    try:
        if engine not in {"Ghidra", "REA"}:
            raise ValueError("CHOOSE_REPORT_PRODUCER")
        path, data = _read(raw, MAX_REPORT_BYTES)
        parsed = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("INVALID_JSON_NUMBER")))
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("JSON_OBJECT_REQUIRED")
        clean = _clean_tree(parsed)
        return _cache({"status": "IMPORTED", "engine": engine, "provenance": "EXTERNAL_REPORT_UNVERIFIED",
                       "name": path.name, "path": str(path), "bytes": len(data), "format": "JSON REPORT",
                       "artifact_sha256": hashlib.sha256(data).hexdigest(), "strings": [],
                       "facts": [f"Imported a local JSON report attributed by the user to {engine}."],
                       "limits": ["Import does not verify the producer, target identity or conclusions.",
                                  "Large collections and deep structures are clipped; sensitive values are redacted."],
                       "content": clean, "summary": f"{engine} report · verify conclusions against the selected artifact"})
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        return _error(exc)


def save_finding(report_id: str, title: str, claim: str, lesson: str = "") -> dict:
    with _LOCK:
        report = _REPORTS.get(str(report_id or ""))
    if report is None:
        from backend.research_jobs import load_report
        report = load_report(str(report_id or ""))
    if report is None:
        return {"schema": SCHEMA, "status": "REPORT_EXPIRED", "reason": "Inspect or import the artifact again."}
    if not str(title or "").strip() or not str(claim or "").strip():
        return {"schema": SCHEMA, "status": "TITLE_AND_FINDING_REQUIRED"}
    return _save_bound_finding(report, title, claim, lesson)


@research_desk.atomic_operation
def _save_bound_finding(report: dict, title: str, claim: str, lesson: str) -> dict:
    source = research_desk.ingest_source({"title": title, "kind": "REVERSE_ENGINEERING",
        "origin": report["path"], "content": json.dumps({"engine": report["engine"], "provenance": report["provenance"],
            "facts": report["facts"], "limits": report["limits"], "strings": report["strings"], "content": report.get("content", {})}, ensure_ascii=False),
        "remember": False})
    evidence = research_desk.add_evidence({"title": title, "claim": claim, "kind": "REVERSE_ENGINEERING",
        "source_url": report["path"], "provenance": "USER_INTERPRETATION", "confidence": 0.5,
        "observed_at": report["observed_at"],
        "details": {"engine": report["engine"], "observation_provenance": report["provenance"],
                    "source_id": source["source_id"], "artifact_sha256": report["artifact_sha256"],
                    "limits": " ".join(report["limits"])}})
    method = {}
    if str(lesson or "").strip():
        steps = [line.strip() for line in lesson.splitlines() if line.strip()]
        method = research_desk.add_method({"name": title, "trigger": "research reverse engineering " + report["format"],
            "steps": steps, "proof": claim, "source_id": source["source_id"], "status": "PROPOSED"})
    research_desk.retain_finding(evidence['evidence_id'], source['source_id'], report)
    return {"schema": SCHEMA, "status": "FINDING_SAVED", "evidence_id": evidence["evidence_id"],
            "method_id": method.get("method_id", ""),
            "method_saved": bool(method), "method_status": "PROPOSED" if method else ""}


def load_finding(evidence_id: str) -> dict:
    report = research_desk.finding_snapshot(str(evidence_id))
    if report is None:
        return {'schema': SCHEMA, 'status': 'ERROR', 'reason': 'SAVED_REPORT_UNAVAILABLE'}
    # Re-open the recorded observation, keeping its original time and source
    # identity. A fresh cache handle lets it be reviewed/saved after job pruning.
    report.pop('report_id', None)
    return {'schema': SCHEMA, 'status': 'FINDING_REPORT_READY', 'report': _cache(report)}


def seed_references() -> dict:
    """Explicit, idempotent source-backed workflow notes; no external tool launch."""
    steps = ["Identify the selected artifact and its version.",
             "Inspect local structure before choosing Ghidra, REA or the WASM lab.",
             "Record observations with offsets or source locations.",
             "Separate inferences and unknowns from observed facts.",
             "Test an implementation before promoting a lesson to a verified method."]
    for reference in REFERENCES:
        source = research_desk.ingest_source({"title": reference["name"], "origin": reference["url"],
            "content": reference["use"], "kind": "TOOL_DOCUMENTATION", "remember": False})
        research_desk.add_method({"name": reference["name"] + " evidence workflow", "trigger": "research reverse engineering " + reference["name"],
            "steps": reference.get('review_steps', steps), "proof": reference["url"], "source_id": source["source_id"], "status": "PROPOSED"})
    return {"schema": SCHEMA, "status": "REFERENCES_SAVED", "count": len(REFERENCES)}
