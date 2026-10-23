"""Candidate overlays and conservative review gates inspired by Reagent (MIT).

Structural consistency is never promoted to semantic equivalence. Candidate
source is copied into the workflow store; the original program is never patched
or executed. The optional C syntax gate runs a fixed compiler in bubblewrap.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from backend import game_workflow_common as common, game_workflow_context as context

MAX_CODE = 128 * 1024


def _strip(code):
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda match: " " * len(match[0]), code, flags=re.S)


def _body(code):
    cleaned = _strip(code).strip()
    start, depth, bodies = None, 0, []
    for index, char in enumerate(cleaned):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("UNBALANCED_CANDIDATE_BRACES")
            if depth == 0:
                bodies.append((start, index))
    if depth or len(bodies) != 1:
        raise ValueError("EXACTLY_ONE_FUNCTION_REQUIRED")
    start, end = bodies[0]
    if not re.search(r"\)\s*(?:const\s*)?$", cleaned[:start]) or cleaned[end + 1:].strip(" ;\n\t"):
        raise ValueError("SINGLE_C_OR_CPP_FUNCTION_REQUIRED")
    return cleaned[start + 1:end]


def _constant(body):
    match = re.fullmatch(r"\s*return\s+(-?(?:0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*))\s*;\s*", body)
    if not match:
        return None
    text = match[1]
    digits = text.lstrip("-")
    base = 16 if "x" in digits.lower() else 8 if len(digits) > 1 and digits.startswith("0") else 10
    return int(text, base)


def _plain_int_function(code):
    return bool(re.match(r"\s*int\s+[A-Za-z_]\w*\s*\(", _strip(code)))


def _structure(code):
    cleaned = _strip(code)
    calls = re.findall(r"\b([A-Za-z_]\w*)\s*\(", cleaned)
    ignored = {"if", "for", "while", "switch", "sizeof", "alignof", "return", "catch", "static_cast", "reinterpret_cast"}
    return {"calls": [name for name in calls if name not in ignored],
            "branches": len(re.findall(r"\b(?:if|for|while|switch|case)\b|\?|&&|\|\|", cleaned)),
            "returns": len(re.findall(r"\breturn\b", cleaned))}


def syntax_gate(code: str) -> dict:
    compiler, sandbox, limiter = (shutil.which(name) for name in ("gcc", "bwrap", "prlimit"))
    if not all((compiler, sandbox, limiter)):
        return {"state": "UNKNOWN", "reason": "SANDBOX_OR_C_COMPILER_UNAVAILABLE"}
    with tempfile.TemporaryDirectory(prefix="gg-candidate-syntax-") as temporary:
        root = Path(temporary)
        candidate = root / "candidate.c"
        candidate.write_text(code)
        command = [sandbox, "--unshare-all", "--die-with-parent", "--new-session", "--ro-bind", "/usr", "/usr",
                   "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/input",
                   "--ro-bind", str(candidate), "/input/candidate.c", "--chdir", "/tmp", "--clearenv",
                   "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8"]
        for path in ("/bin", "/lib", "/lib64"):
            if Path(path).is_symlink():
                command += ["--symlink", os.readlink(path), path]
            elif Path(path).is_dir():
                command += ["--ro-bind", path, path]
        command += [limiter, "--as=536870912", "--cpu=8", "--fsize=1048576", "--nofile=128", "--",
                    compiler, "-x", "c", "-std=c11", "-fsyntax-only", "-Werror=implicit-function-declaration", "/input/candidate.c"]
        # A bounded file avoids an unbounded compiler diagnostic pipe.
        with (root / "diagnostics").open("w+b") as output:
            try:
                process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output, timeout=15, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
            except subprocess.TimeoutExpired:
                return {"state": "FAIL", "reason": "COMPILER_TIMEOUT"}
            output.seek(0)
            diagnostics = output.read(8192).decode("utf-8", "replace")
        if process.returncode and ("bwrap:" in diagnostics or "prlimit:" in diagnostics):
            return {"state": "UNKNOWN", "reason": "COMPILER_SANDBOX_UNAVAILABLE", "diagnostics": diagnostics}
        return {"state": "PASS" if process.returncode == 0 else "FAIL", "scope": "C11_SYNTAX_ONLY",
                "diagnostics": diagnostics, "limits": ["The compiler does not test game behavior, linking, runtime ABI or C++ syntax."]}


def verify(context_path: str, candidate_path: str, *, syntax: bool = False) -> dict:
    packet = context.load(context_path)
    path, data = common.read_file(candidate_path, MAX_CODE)
    try:
        code = data.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("UTF8_CANDIDATE_REQUIRED") from exc
    if not code.strip():
        raise ValueError("EMPTY_CANDIDATE")
    gates = {"artifact_freshness": {"state": "PASS", "scope": "EXACT_SOURCE_BYTES"},
             "candidate_structure": {"state": "UNKNOWN"}, "behavior": {"state": "UNKNOWN", "reason": "NO_INDEPENDENT_BEHAVIORAL_TEST"}}
    findings, observations = [], []
    reference = packet["function"].get("pseudocode", "")
    try:
        body = _body(code)
        observed = _structure(body)
        try:
            reference_body = _body(reference)
        except ValueError:
            reference_body = ""
        if reference_body:
            baseline = _structure(reference_body)
            expected, actual = _constant(reference_body), _constant(body)
            if expected is not None and actual is not None and expected != actual:
                # Narrow integers, casts and implementation-defined overflow
                # can make different literals behave identically. Reject only
                # plain int functions and values representable in C's minimum
                # signed int range; keep the other cases for ABI-aware review.
                comparable = _plain_int_function(reference) and _plain_int_function(code) and all(-32767 <= value <= 32767 for value in (expected, actual))
                findings.append({"severity": "FAIL" if comparable else "REVIEW", "kind": "CONSTANT_RETURN_MISMATCH",
                                 "reference": expected, "candidate": actual, "scope": "REPRESENTABLE_INT" if comparable else "RETURN_TYPE_OR_WIDTH_UNMODELED"})
            if baseline["branches"] >= 2 and not observed["branches"]:
                findings.append({"severity": "REVIEW", "kind": "CONTROL_FLOW_DISAPPEARED"})
            if len(baseline["calls"]) >= 4 and not observed["calls"]:
                findings.append({"severity": "REVIEW", "kind": "CALL_STRUCTURE_DISAPPEARED"})
            observations.append({"reference_structure": baseline, "candidate_structure": observed})
            gates["candidate_structure"] = {"state": "FAIL" if any(f["severity"] == "FAIL" for f in findings) else "CONSISTENT",
                                            "scope": "CONSERVATIVE_SOURCE_HEURISTICS"}
        else:
            gates["candidate_structure"] = {"state": "UNKNOWN", "reason": "REFERENCE_BODY_UNAVAILABLE"}
    except ValueError as exc:
        gates["candidate_structure"] = {"state": "FAIL", "reason": str(exc)}
    gates["syntax"] = syntax_gate(code) if syntax else {"state": "UNKNOWN", "reason": "SYNTAX_GATE_NOT_REQUESTED"}
    provenance = packet.get("provenance", "EXTERNAL_EXPORT_UNVERIFIED")
    gates["analysis_provenance"] = {"state": "OBSERVED" if provenance == "LOCAL_ENGINE_STATIC_OBSERVATION" else "UNKNOWN",
                                     "scope": provenance}
    failed = any(gate["state"] == "FAIL" for gate in gates.values())
    value = {"schema": "gg.game-workflows.candidate.v1", "status": "FAIL" if failed else "REVIEW_REQUIRED",
             "acceptance": "REJECTED" if failed else "UNKNOWN", "artifact": packet["artifact"],
             "function": {"name": packet["function"]["name"], "address": packet["function"]["address"]},
             "context_path": str(common.local_path(context_path)), "candidate_source": str(path), "candidate_sha256": common.digest(data),
             "candidate_code": code, "gates": gates, "findings": findings, "observations": observations,
             "limits": ["Structural consistency is not semantic equivalence; no candidate is automatically accepted or patched.",
                        "External exports and pseudocode are unverified behavioral oracles.",
                        "MIPS, vector-unit behavior, calling conventions, memory effects and game integration require separate behavioral tests."]}
    output = common.packet("candidate", value)
    return {**value, "packet_path": str(output), "summary": "Candidate rejected by a concrete check" if failed else "Candidate preserved for review · behavior remains unverified"}
