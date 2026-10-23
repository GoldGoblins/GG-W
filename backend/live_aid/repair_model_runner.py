#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.platform_support import (
    private_runtime_root,
)


import contextlib
import hashlib
import importlib
import io
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

semantic_transport = importlib.import_module(
    "autonomy_model_runner"
)
repair_broker = importlib.import_module(
    "live_aid.repair_broker"
)

REQUEST_SCHEMA = "gg.live-aid.repair-model-request.v1"
RESPONSE_SCHEMA = "gg.live-aid.repair-model-response.v1"

MAX_SOURCE_BYTES = 24000
MAX_DIAGNOSTICS = 32
MAX_DIAGNOSTIC_MESSAGE = 2000

REQUEST_ID_RE = re.compile(
    r"repair-model-[0-9a-f]{32}\Z"
)
PROPOSAL_ID_RE = re.compile(
    r"repair-proposal-[0-9a-f]{32}\Z"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class RepairModelError(RuntimeError):
    pass


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _text(
    value: Any,
    label: str,
    maximum: int,
) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or "\x00" in value
    ):
        raise RepairModelError(label)
    return value


def _sha(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or SHA256_RE.fullmatch(value) is None
    ):
        raise RepairModelError(label)
    return value


def _normalize_diagnostics(
    value: Any,
) -> list[dict[str, Any]]:
    if (
        type(value) is not list
        or not value
        or len(value) > MAX_DIAGNOSTICS
    ):
        raise RepairModelError(
            "DIAGNOSTICS"
        )

    normalized: list[dict[str, Any]] = []
    proven_fail = False

    for raw in value:
        if type(raw) is not dict:
            raise RepairModelError(
                "DIAGNOSTIC_TYPE"
            )

        status = _text(
            raw.get("status"),
            "DIAGNOSTIC_STATUS",
            32,
        )

        code = _text(
            str(raw.get(
                "code",
                "QML_GATE_DIAGNOSTIC",
            )),
            "DIAGNOSTIC_CODE",
            160,
        )

        message = _text(
            str(raw.get("message", "")),
            "DIAGNOSTIC_MESSAGE",
            MAX_DIAGNOSTIC_MESSAGE,
        )

        line = raw.get("line", -1)

        if type(line) is not int:
            line = -1

        blocking = raw.get("blocking") is True

        suggestion = str(
            raw.get("suggestion", "")
        )[:1000]

        normalized.append(
            {
                "status": status,
                "code": code,
                "message": message,
                "line": line,
                "blocking": blocking,
                "suggestion": suggestion,
            }
        )

        if status == "FAIL" and blocking:
            proven_fail = True

    if not proven_fail:
        raise RepairModelError(
            "NO_PROVEN_BLOCKING_FAIL"
        )

    return normalized


def validate_request(
    value: Any,
) -> dict[str, Any]:
    fields = {
        "schema",
        "request_id",
        "object_id",
        "source_name",
        "language",
        "source",
        "source_sha256",
        "preflight_report_sha256",
        "diagnostics",
    }

    if type(value) is not dict or set(value) != fields:
        raise RepairModelError(
            "REQUEST_FIELDS"
        )

    if value["schema"] != REQUEST_SCHEMA:
        raise RepairModelError(
            "REQUEST_SCHEMA"
        )

    request_id = _text(
        value["request_id"],
        "REQUEST_ID",
        80,
    )

    if REQUEST_ID_RE.fullmatch(request_id) is None:
        raise RepairModelError(
            "REQUEST_ID_FORMAT"
        )

    object_id = _text(
        value["object_id"],
        "OBJECT_ID",
        160,
    )

    source_name = _text(
        value["source_name"],
        "SOURCE_NAME",
        300,
    )

    if value["language"] != "qml":
        raise RepairModelError(
            "LANGUAGE"
        )

    source = _text(
        value["source"],
        "SOURCE",
        MAX_SOURCE_BYTES,
    )

    encoded = source.encode("utf-8")

    if len(encoded) > MAX_SOURCE_BYTES:
        raise RepairModelError(
            "SOURCE_BYTES"
        )

    source_sha = _sha(
        value["source_sha256"],
        "SOURCE_SHA256",
    )

    if source_sha != _sha_bytes(encoded):
        raise RepairModelError(
            "SOURCE_SHA_BINDING"
        )

    preflight_sha = _sha(
        value["preflight_report_sha256"],
        "PREFLIGHT_REPORT_SHA256",
    )

    diagnostics = _normalize_diagnostics(
        value["diagnostics"]
    )

    return {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "object_id": object_id,
        "source_name": source_name,
        "language": "qml",
        "source": source,
        "source_sha256": source_sha,
        "preflight_report_sha256": preflight_sha,
        "diagnostics": diagnostics,
    }


def _repair_target(
    request: dict[str, Any],
) -> tuple[int, str]:
    lines = request["source"].splitlines()

    target_lines = sorted(
        {
            item["line"]
            for item in request["diagnostics"]
            if (
                item["status"] == "FAIL"
                and item["blocking"] is True
                and type(item["line"]) is int
                and item["line"] > 0
            )
        }
    )

    if not target_lines:
        raise RepairModelError(
            "REPAIR_TARGET_LINE_COUNT:0"
        )

    # Parsers may emit recovery diagnostics on later lines for one
    # earlier syntax defect. Repair exactly one host-attested line per
    # iteration; revalidation decides whether another repair is needed.
    line_number = target_lines[0]

    if line_number > len(lines):
        raise RepairModelError(
            "REPAIR_TARGET_LINE_OUT_OF_RANGE"
        )

    old_text = lines[
        line_number - 1
    ].strip()

    if not old_text:
        raise RepairModelError(
            "REPAIR_TARGET_LINE_EMPTY"
        )

    return line_number, old_text


def _gbnf_literal(
    value: str,
) -> str:
    if (
        "\n" in value
        or "\r" in value
        or "\x00" in value
    ):
        raise RepairModelError(
            "GBNF_LITERAL_MULTILINE"
        )

    return json.dumps(
        value,
        ensure_ascii=False,
    )


def build_repair_grammar(
    request: dict[str, Any],
) -> str:
    request = validate_request(request)

    _, old_text = _repair_target(
        request
    )

    old_literal = _gbnf_literal(
        old_text
    )

    rules = (
        (
            'root ::= "HYPOTHESIS:" reason '
            '"|OLD:" old '
            '"|NEW:" replacement '
            '"|WHY:" reason '
            '"|GG_MODEL_RUNNER_OK"'
        ),
        'reason ::= reason-char{1,160}',
        'reason-char ::= [A-Za-z0-9 _.,:;!?()+/@#%-]',
        'old ::= ' + old_literal,
        'replacement ::= replacement-char{1,240}',
        r'replacement-char ::= [^|\r\n]',
    )

    grammar = "\n".join(
        rules
    ) + "\n"

    if grammar.splitlines() != list(rules):
        raise RepairModelError(
            "REPAIR_GRAMMAR_LINE_SERIALIZATION"
        )

    if "\\nreason ::=" in grammar:
        raise RepairModelError(
            "REPAIR_GRAMMAR_LITERAL_BACKSLASH_N"
        )

    if not grammar.endswith("\n"):
        raise RepairModelError(
            "REPAIR_GRAMMAR_FINAL_NEWLINE"
        )

    return grammar


def build_prompt(
    request: dict[str, Any],
) -> str:
    request = validate_request(request)

    target_line, target_old = (
        _repair_target(request)
    )

    broker_request = repair_broker.RepairRequest(
        source_name=request["source_name"],
        source_sha256=request["source_sha256"],
        source=request["source"],
        diagnostics=tuple(
            request["diagnostics"]
        ),
        fact_context=(),
        instruction=(
            "Repair only the attested QML diagnostic line. "
            "OLD is host-selected and grammar-bound. "
            "Propose only a minimal syntactically valid replacement "
            "for NEW. Do not emit JSON, field labels inside fields, "
            "commands, paths, network actions, saves, execution or "
            "authority changes."
        ),
    )

    diagnostic_lines = []

    for item in broker_request.diagnostics:
        diagnostic_lines.append(
            "STATUS="
            + str(item.get("status", ""))
            + " CODE="
            + str(item.get("code", ""))
            + " LINE="
            + str(item.get("line", ""))
            + " MESSAGE="
            + str(item.get("message", ""))
        )

    prompt = (
        "Du är GG Live Aid, en lokal QML-reparationsproposer utan "
        "action-authority. En riktig QML Gate har FAIL på exakt denna "
        "buffer. Hostsystemet har redan valt reparationsraden från den "
        "attesterade diagnostiken. Du får INTE välja en annan OLD-rad.\\n"
        "\\n"
        "Output-formatet är hårt grammar-bundet. Skriv inte JSON och "
        "lägg inte till citattecken eller andra fältnamn runt "
        "HYPOTHESIS/OLD/NEW/WHY.\\n"
        "\\n"
        "OLD är redan låst av grammatiken. Föreslå endast NEW som en "
        "enda komplett QML-källrad utan ledande indrag. NEW måste vara "
        "syntaktiskt giltig QML; behåll inte ett uppenbart ogiltigt "
        "placeholder-uttryck bara genom att lägga till semikolon.\\n"
        "\\n"
        "TARGET_LINE="
        + str(target_line)
        + "\\n"
        "GRAMMAR_BOUND_OLD="
        + target_old
        + "\\n"
        "PREFLIGHT_REPORT_SHA256="
        + request["preflight_report_sha256"]
        + "\\n"
        "SOURCE_SHA256="
        + request["source_sha256"]
        + "\\n"
        "SOURCE_NAME="
        + broker_request.source_name
        + "\\n"
        "DIAGNOSTICS_BEGIN\\n"
        + "\\n".join(diagnostic_lines)
        + "\\nDIAGNOSTICS_END\\n"
        "SOURCE_BEGIN\\n"
        + broker_request.source
        + "\\nSOURCE_END\\n"
    )

    if len(prompt) > 32768:
        raise RepairModelError(
            "PROMPT_TOO_LARGE"
        )

    return prompt


def _line_replacement(
    source: str,
    old_text: str,
    new_text: str,
    *,
    target_line: int,
) -> str:
    old_key = old_text.strip()
    new_key = new_text.strip()

    if not old_key or not new_key:
        raise RepairModelError(
            "MODEL_LINE_EMPTY"
        )

    if (
        "\n" in old_key
        or "\r" in old_key
        or "|" in old_key
    ):
        raise RepairModelError(
            "MODEL_OLD_INVALID"
        )

    if (
        "\n" in new_key
        or "\r" in new_key
        or "|" in new_key
    ):
        raise RepairModelError(
            "MODEL_NEW_INVALID"
        )

    lines = source.splitlines(
        keepends=True
    )

    if (
        target_line < 1
        or target_line > len(lines)
    ):
        raise RepairModelError(
            "MODEL_TARGET_LINE_OUT_OF_RANGE"
        )

    index = target_line - 1

    raw = lines[index]
    body = raw.rstrip("\r\n")

    if body.strip() != old_key:
        raise RepairModelError(
            "MODEL_OLD_TARGET_BINDING"
        )

    ending = raw[len(body):]

    indent_length = (
        len(body)
        - len(body.lstrip(" \t"))
    )

    indent = body[:indent_length]

    lines[index] = (
        indent
        + new_key
        + ending
    )

    candidate = "".join(lines)

    if candidate == source:
        raise RepairModelError(
            "MODEL_PROPOSAL_NO_OP"
        )

    return candidate


def _canonical_bytes(
    value: Any,
) -> bytes:
    if isinstance(value, bytes):
        return value

    if isinstance(value, str):
        return value.encode("utf-8")

    raise RepairModelError(
        "CANONICAL_PROPOSAL_TYPE"
    )


def _parse_repair_model_stdout(
    payload: bytes,
) -> str:
    """Extract exactly one complete semantic repair result from llama CLI noise."""

    if not isinstance(payload, bytes):
        raise semantic_transport.base.RunnerStop(
            "repair_model_stdout_type"
        )

    try:
        text = payload.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise semantic_transport.base.RunnerStop(
            "repair_model_stdout_utf8"
        ) from exc

    start_marker = "HYPOTHESIS:"
    end_marker = "GG_MODEL_RUNNER_OK"

    def positions(
        marker: str,
    ) -> list[int]:
        result: list[int] = []
        offset = 0

        while True:
            index = text.find(
                marker,
                offset,
            )

            if index < 0:
                return result

            result.append(index)
            offset = index + 1

    starts = positions(
        start_marker
    )

    ends = positions(
        end_marker
    )

    if (
        not starts
        or not ends
        or len(starts) > 8
        or len(ends) > 8
    ):
        raise semantic_transport.base.RunnerStop(
            "repair_model_stdout_marker_cardinality"
        )

    candidates: list[str] = []

    for start in starts:
        for marker_start in ends:
            if marker_start <= start:
                continue

            marker_end = (
                marker_start
                + len(end_marker)
            )

            candidate = text[
                start:marker_end
            ]

            try:
                semantic_transport.parse_semantic_text(
                    candidate
                )
            except semantic_transport.AutonomyModelError:
                continue

            if candidate not in candidates:
                candidates.append(
                    candidate
                )

    if len(candidates) != 1:
        raise semantic_transport.base.RunnerStop(
            "repair_model_stdout_semantic_candidate_count:"
            + str(len(candidates))
        )

    return candidates[0]


def build_response(
    request: dict[str, Any],
    proposal: dict[str, str],
    *,
    model_evidence_path: str,
    model_response_sha256: str,
) -> dict[str, Any]:
    request = validate_request(request)

    validated_proposal = (
        semantic_transport.contract
        .validate_semantic_proposal(
            proposal
        )
    )

    target_line, target_old = (
        _repair_target(request)
    )

    if (
        validated_proposal["old_text"].strip()
        != target_old
    ):
        raise RepairModelError(
            "MODEL_OLD_TARGET_BINDING"
        )

    candidate = _line_replacement(
        request["source"],
        validated_proposal["old_text"],
        validated_proposal["new_text"],
        target_line=target_line,
    )

    canonical_proposal = (
        semantic_transport.contract
        .canonical_json(
            validated_proposal
        )
    )

    canonical_bytes = _canonical_bytes(
        canonical_proposal
    )

    return {
        "schema": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "proposal_id": (
            "repair-proposal-"
            + uuid.uuid4().hex
        ),
        "object_id": request["object_id"],
        "source_name": request["source_name"],
        "source_sha256": request["source_sha256"],
        "preflight_report_sha256":
            request["preflight_report_sha256"],
        "status": "PROPOSAL",
        "hypothesis":
            validated_proposal["hypothesis"],
        "old_text":
            validated_proposal["old_text"],
        "new_text":
            validated_proposal["new_text"],
        "why":
            validated_proposal["why"],
        "candidate_source": candidate,
        "candidate_sha256": _sha_bytes(
            candidate.encode("utf-8")
        ),
        "semantic_proposal_sha256":
            _sha_bytes(canonical_bytes),
        "model_evidence_path":
            model_evidence_path,
        "model_response_sha256":
            model_response_sha256,
        "model_output_authority":
            "UNTRUSTED_MODEL_OUTPUT",
        "apply_authority":
            "HUMAN_EXPLICIT_IN_MEMORY_ONLY",
        "persistent_write_authority":
            "NONE",
        "execution_authority":
            "NONE",
        "network_authority":
            "NONE",
        "preflight_required_after_apply":
            True,
    }


def validate_response(
    value: Any,
    *,
    expected_request_id: str,
    expected_object_id: str,
    expected_source_sha256: str,
) -> dict[str, Any]:
    fields = {
        "schema",
        "request_id",
        "proposal_id",
        "object_id",
        "source_name",
        "source_sha256",
        "preflight_report_sha256",
        "status",
        "hypothesis",
        "old_text",
        "new_text",
        "why",
        "candidate_source",
        "candidate_sha256",
        "semantic_proposal_sha256",
        "model_evidence_path",
        "model_response_sha256",
        "model_output_authority",
        "apply_authority",
        "persistent_write_authority",
        "execution_authority",
        "network_authority",
        "preflight_required_after_apply",
    }

    if type(value) is not dict or set(value) != fields:
        raise RepairModelError(
            "RESPONSE_FIELDS"
        )

    if value["schema"] != RESPONSE_SCHEMA:
        raise RepairModelError(
            "RESPONSE_SCHEMA"
        )

    if value["request_id"] != expected_request_id:
        raise RepairModelError(
            "RESPONSE_REQUEST_BINDING"
        )

    if value["object_id"] != expected_object_id:
        raise RepairModelError(
            "RESPONSE_OBJECT_BINDING"
        )

    if (
        value["source_sha256"]
        != expected_source_sha256
    ):
        raise RepairModelError(
            "RESPONSE_SOURCE_BINDING"
        )

    proposal_id = _text(
        value["proposal_id"],
        "PROPOSAL_ID",
        80,
    )

    if PROPOSAL_ID_RE.fullmatch(
        proposal_id
    ) is None:
        raise RepairModelError(
            "PROPOSAL_ID_FORMAT"
        )

    if value["status"] != "PROPOSAL":
        raise RepairModelError(
            "RESPONSE_STATUS"
        )

    for field in (
        "hypothesis",
        "old_text",
        "new_text",
        "why",
    ):
        _text(
            value[field],
            "RESPONSE_" + field.upper(),
            512,
        )

    candidate = _text(
        value["candidate_source"],
        "CANDIDATE_SOURCE",
        MAX_SOURCE_BYTES,
    )

    candidate_sha = _sha(
        value["candidate_sha256"],
        "CANDIDATE_SHA256",
    )

    if (
        candidate_sha
        != _sha_bytes(
            candidate.encode("utf-8")
        )
    ):
        raise RepairModelError(
            "CANDIDATE_SHA_BINDING"
        )

    if candidate_sha == expected_source_sha256:
        raise RepairModelError(
            "CANDIDATE_NO_OP"
        )

    _sha(
        value["preflight_report_sha256"],
        "RESPONSE_PREFLIGHT_SHA",
    )

    _sha(
        value["semantic_proposal_sha256"],
        "RESPONSE_SEMANTIC_SHA",
    )

    _sha(
        value["model_response_sha256"],
        "RESPONSE_MODEL_SHA",
    )

    evidence = Path(
        _text(
            value["model_evidence_path"],
            "MODEL_EVIDENCE_PATH",
            600,
        )
    )

    runtime = private_runtime_root()

    if (
        not evidence.is_absolute()
        or not evidence.is_relative_to(runtime)
    ):
        raise RepairModelError(
            "MODEL_EVIDENCE_PATH_POLICY"
        )

    if (
        value["model_output_authority"]
        != "UNTRUSTED_MODEL_OUTPUT"
    ):
        raise RepairModelError(
            "MODEL_OUTPUT_AUTHORITY"
        )

    if (
        value["apply_authority"]
        != "HUMAN_EXPLICIT_IN_MEMORY_ONLY"
    ):
        raise RepairModelError(
            "APPLY_AUTHORITY"
        )

    if (
        value["persistent_write_authority"]
        != "NONE"
    ):
        raise RepairModelError(
            "WRITE_AUTHORITY"
        )

    if value["execution_authority"] != "NONE":
        raise RepairModelError(
            "EXECUTION_AUTHORITY"
        )

    if value["network_authority"] != "NONE":
        raise RepairModelError(
            "NETWORK_AUTHORITY"
        )

    if (
        value["preflight_required_after_apply"]
        is not True
    ):
        raise RepairModelError(
            "PREFLIGHT_REQUIRED"
        )

    return dict(value)


def _read_request(
    path: Path,
) -> dict[str, Any]:
    runtime = private_runtime_root()

    if path.is_symlink() or not path.is_file():
        raise RepairModelError(
            "REQUEST_FILE_INVALID"
        )

    resolved = path.resolve(strict=True)

    if not resolved.is_relative_to(runtime):
        raise RepairModelError(
            "REQUEST_FILE_OUTSIDE_RUNTIME"
        )

    if (
        re.fullmatch(
            r"gg-live-aid-repair-ui\.[0-9a-f]{32}",
            resolved.parent.name,
        )
        is None
    ):
        raise RepairModelError(
            "REQUEST_PARENT"
        )

    if resolved.name != "request.json":
        raise RepairModelError(
            "REQUEST_NAME"
        )

    if resolved.stat().st_size > 65536:
        raise RepairModelError(
            "REQUEST_FILE_TOO_LARGE"
        )

    raw = json.loads(
        resolved.read_text(
            encoding="utf-8"
        )
    )

    return validate_request(raw)


def execute(
    request_path: Path,
) -> dict[str, Any]:
    request = _read_request(
        request_path
    )

    prompt = build_prompt(request)

    repair_grammar = (
        build_repair_grammar(request)
    )

    captured_out = io.StringIO()
    captured_err = io.StringIO()

    if not hasattr(
        semantic_transport,
        "AUTONOMY_GBNF",
    ):
        raise RepairModelError(
            "SEMANTIC_GRAMMAR_SEAM_MISSING"
        )

    previous_grammar = (
        semantic_transport.AUTONOMY_GBNF
    )

    base_transport = getattr(
        semantic_transport,
        "base",
        None,
    )

    if (
        base_transport is None
        or not hasattr(
            base_transport,
            "parse_model_stdout",
        )
        or not hasattr(
            base_transport,
            "RunnerStop",
        )
    ):
        raise RepairModelError(
            "SEMANTIC_STDOUT_PARSER_SEAM_MISSING"
        )

    previous_parser = (
        base_transport.parse_model_stdout
    )

    if not callable(
        previous_parser
    ):
        raise RepairModelError(
            "SEMANTIC_STDOUT_PARSER_NOT_CALLABLE"
        )

    try:
        semantic_transport.AUTONOMY_GBNF = (
            repair_grammar
        )

        base_transport.parse_model_stdout = (
            _parse_repair_model_stdout
        )

        with (
            contextlib.redirect_stdout(
                captured_out
            ),
            contextlib.redirect_stderr(
                captured_err
            ),
        ):
            (
                rc,
                proposal,
                evidence,
                _render,
            ) = (
                semantic_transport
                .run_semantic_prompt(
                    request_id=
                        request["request_id"],
                    prompt=prompt,
                )
            )

    finally:
        semantic_transport.AUTONOMY_GBNF = (
            previous_grammar
        )

        base_transport.parse_model_stdout = (
            previous_parser
        )

    if rc != 0:
        raise RepairModelError(
            "MODEL_TRANSPORT_RC:"
            + str(rc)
            + ":"
            + captured_err.getvalue()[-1200:]
        )

    if proposal is None:
        raise RepairModelError(
            "MODEL_PROPOSAL_MISSING"
        )

    response_path = (
        evidence / "response.json"
    )

    if (
        response_path.is_symlink()
        or not response_path.is_file()
    ):
        raise RepairModelError(
            "MODEL_RESPONSE_EVIDENCE_MISSING"
        )

    model_response_sha = _sha_file(
        response_path
    )

    return build_response(
        request,
        proposal,
        model_evidence_path=str(
            evidence.resolve(strict=True)
        ),
        model_response_sha256=
            model_response_sha,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "REPAIR_MODEL_STOP=ARGUMENT_COUNT",
            file=sys.stderr,
        )
        return 2

    try:
        response = execute(
            Path(sys.argv[1])
        )

        validated = validate_response(
            response,
            expected_request_id=
                response["request_id"],
            expected_object_id=
                response["object_id"],
            expected_source_sha256=
                response["source_sha256"],
        )

        print(
            json.dumps(
                validated,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

        return 0

    except Exception as exc:
        print(
            "REPAIR_MODEL_STOP="
            + type(exc).__name__
            + ":"
            + str(exc),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
