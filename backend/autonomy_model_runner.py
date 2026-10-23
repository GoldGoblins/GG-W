#!/usr/bin/env python3
"""Strict local semantic proposer for GG Autonomy Bootstrap v1.

The local model may propose only hypothesis/old_text/new_text/why strings. The
output is always classified UNTRUSTED_MODEL_OUTPUT and cannot name a path,
executable, argv vector, shell command, network target, or authority grant.
"""

from __future__ import annotations

import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.platform_files import (
    mode_matches,
    owned_by_current_user,
    set_private_mode,
)
from backend.platform_support import (
    private_runtime_root,
)


import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

try:
    from . import local_ai_model_runner as base
except ImportError:
    import local_ai_model_runner as base  # type: ignore

try:
    from . import autonomy_contract as contract
except ImportError:
    import autonomy_contract as contract  # type: ignore

MODEL_REQUEST_SCHEMA = "gg.workbench.autonomy-model-request.v1"
from backend.local_ai_platform import adapt_model_runner
base = adapt_model_runner(base)
MODEL_REQUEST_FIELDS = frozenset(
    ("schema", "request_id", "task_id", "goal", "target_text", "diagnostic", "attempt")
)

# Outer JSON is still the frozen runner's {"text":"..."} shape. The inner text
# is grammar-constrained to four semantic fields and the frozen marker.
AUTONOMY_GBNF = (
    'char ::= [^"\\\\|\\x00-\\x1F\\x7F] | "\\\\" ["\\\\/"]\n'
    'segment ::= char{1,180}\n'
    'ws ::= [ \\t\\n]{0,8}\n'
    'root ::= "{" ws "\\"text\\"" ws ":" ws "\\"" '
    '"HYPOTHESIS:" segment "|" '
    '"OLD:" segment "|" '
    '"NEW:" segment "|" '
    '"WHY:" segment "|" '
    '"GG_MODEL_RUNNER_OK" "\\"" ws "}"\n'
)


SELFDEV_SEMANTIC_SCHEMA = (
    "gg.workbench.selfdev-semantic-proposal.v1"
)

SELFDEV_GBNF = (
    'hex ::= [0-9a-fA-F]\n'
    'plain ::= [^"\\\\\\x00-\\x1F\\x7F]\n'
    'iescape ::= "\\\\" "\\\\" [bfnrt] | "\\\\" "\\\\" "u" '
    'hex hex hex hex | "\\\\" "\\\\" "\\\\" "\\\"" | '
    '"\\\\" "\\\\" "\\\\" "\\\\"\n'
    'ijchar ::= plain | iescape\n'
    'lead ::= [A-Za-z0-9_]\n'
    'ijtail ::= ijchar{0,255}\n'
    'ijfull ::= ijchar{255}\n'
    'ijseq2 ::= ijfull ijtail | ijtail\n'
    'ijseq3 ::= ijfull ijseq2 | ijseq2\n'
    'ijseq4 ::= ijfull ijseq3 | ijseq3\n'
    'ijseq5 ::= ijfull ijseq4 | ijseq4\n'
    'ijseq6 ::= ijfull ijseq5 | ijseq5\n'
    'ijseq7 ::= ijfull ijseq6 | ijseq6\n'
    'ijseq8 ::= ijfull ijseq7 | ijseq7\n'
    'ijseq9 ::= ijfull ijseq8 | ijseq8\n'
    'ijseq10 ::= ijfull ijseq9 | ijseq9\n'
    'ijseq11 ::= ijfull ijseq10 | ijseq10\n'
    'ijseq12 ::= ijfull ijseq11 | ijseq11\n'
    'ijseq13 ::= ijfull ijseq12 | ijseq12\n'
    'ijseq14 ::= ijfull ijseq13 | ijseq13\n'
    'ijseq15 ::= ijfull ijseq14 | ijseq14\n'
    'ijseq16 ::= ijfull ijseq15 | ijseq15\n'
    'hjson ::= lead ijtail\n'
    'oldjson ::= ijseq8 lead ijseq8\n'
    'newjson ::= ijseq16\n'
    'whyjson ::= lead ijtail\n'
    'ws ::= [ \\t\\n]{0,8}\n'
    'root ::= "{" ws "\\"text\\"" ws ":" ws "\\"" '
    '"HYPOTHESIS_JSON=" "\\\\" "\\\"" hjson "\\\\" "\\\"" "\\\\" "n" '
    '"OLD_JSON=" "\\\\" "\\\"" oldjson "\\\\" "\\\"" "\\\\" "n" '
    '"NEW_JSON=" "\\\\" "\\\"" newjson "\\\\" "\\\"" "\\\\" "n" '
    '"WHY_JSON=" "\\\\" "\\\"" whyjson "\\\\" "\\\"" "\\\\" "n" '
    '"GG_MODEL_RUNNER_OK" "\\"" ws "}"\n'
)


class AutonomyModelError(RuntimeError):
    pass


def _text(value: Any, label: str, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise AutonomyModelError(label + "_INVALID")
    if "\x00" in value:
        raise AutonomyModelError(label + "_NUL")
    return value


def validate_model_request(value: Any) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != MODEL_REQUEST_FIELDS:
        raise AutonomyModelError("MODEL_REQUEST_FIELDS_INVALID")
    if value["schema"] != MODEL_REQUEST_SCHEMA:
        raise AutonomyModelError("MODEL_REQUEST_SCHEMA_INVALID")
    request_id = _text(value["request_id"], "REQUEST_ID", 128)
    if not request_id.startswith("autonomy-model-"):
        raise AutonomyModelError("MODEL_REQUEST_ID_INVALID")
    task_id = _text(value["task_id"], "TASK_ID", 128)
    if contract.TASK_ID_RE.fullmatch(task_id) is None:
        raise AutonomyModelError("MODEL_TASK_ID_INVALID")
    goal = _text(value["goal"], "GOAL", 4096)
    target_text = _text(value["target_text"], "TARGET_TEXT", contract.TARGET_MAX_BYTES)
    diagnostic = value["diagnostic"]
    if type(diagnostic) is not str or len(diagnostic) > 2048 or "\x00" in diagnostic:
        raise AutonomyModelError("DIAGNOSTIC_INVALID")
    attempt = value["attempt"]
    if type(attempt) is not int or not 1 <= attempt <= 4:
        raise AutonomyModelError("MODEL_ATTEMPT_INVALID")
    return {
        "schema": MODEL_REQUEST_SCHEMA,
        "request_id": request_id,
        "task_id": task_id,
        "goal": goal,
        "target_text": target_text,
        "diagnostic": diagnostic,
        "attempt": attempt,
    }


def _safe_request_path(raw: str) -> Path:
    path = Path(raw)
    runtime = private_runtime_root()
    if path.parent.resolve(strict=True) != runtime:
        raise AutonomyModelError("MODEL_REQUEST_PARENT_INVALID")
    if path.is_symlink() or not path.is_file():
        raise AutonomyModelError("MODEL_REQUEST_FILE_INVALID")
    if not path.name.startswith("gg-autonomy-model-request."):
        raise AutonomyModelError("MODEL_REQUEST_NAME_INVALID")
    info = path.stat()
    if not owned_by_current_user(path) or not mode_matches(path, 0o600):
        raise AutonomyModelError("MODEL_REQUEST_OWNER_MODE_INVALID")
    return path


def parse_semantic_text(text: str) -> dict[str, str]:
    marker = "GG_MODEL_RUNNER_OK"
    if not text.endswith(marker):
        raise AutonomyModelError("MODEL_MARKER_MISSING")
    body = text[: -len(marker)]
    if not body.endswith("|"):
        raise AutonomyModelError("MODEL_FORMAT_TRAILING_DELIMITER_MISSING")
    body = body[:-1]
    parts = body.split("|")
    if len(parts) != 4:
        raise AutonomyModelError("MODEL_FORMAT_FIELD_COUNT")
    prefixes = ("HYPOTHESIS:", "OLD:", "NEW:", "WHY:")
    values: dict[str, str] = {"schema": contract.SEMANTIC_PROPOSAL_SCHEMA}
    keys = ("hypothesis", "old_text", "new_text", "why")
    for part, prefix, key in zip(parts, prefixes, keys, strict=True):
        if not part.startswith(prefix):
            raise AutonomyModelError("MODEL_FORMAT_PREFIX:" + key)
        values[key] = part[len(prefix):]
    try:
        return contract.validate_semantic_proposal(values)
    except ValueError as exc:
        raise AutonomyModelError("MODEL_SEMANTIC_CONTRACT:" + str(exc)) from exc


def _selfdev_field(
    value: str,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise AutonomyModelError(
            "SELFDEV_SEMANTIC_CONTRACT:"
            + label
            + "_TYPE"
        )

    if "\x00" in value or len(value) > maximum:
        raise AutonomyModelError(
            "SELFDEV_SEMANTIC_CONTRACT:"
            + label
            + "_BOUNDS"
        )

    if not allow_empty and not value.strip():
        raise AutonomyModelError(
            "SELFDEV_SEMANTIC_CONTRACT:"
            + label
            + "_EMPTY"
        )

    return value


def _selfdev_json_field(
    line: str,
    prefix: str,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not line.startswith(prefix):
        raise AutonomyModelError(
            "SELFDEV_MODEL_FORMAT_PREFIX:"
            + label
        )

    encoded = line[len(prefix):]

    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise AutonomyModelError(
            "SELFDEV_MODEL_FORMAT_JSON:"
            + label
        ) from exc

    if type(value) is not str:
        raise AutonomyModelError(
            "SELFDEV_MODEL_FORMAT_JSON_TYPE:"
            + label
        )

    return _selfdev_field(
        value,
        label,
        maximum,
        allow_empty=allow_empty,
    )


def parse_selfdev_semantic_text(
    text: str,
) -> dict[str, str]:
    lines = text.splitlines()

    if len(lines) != 5:
        raise AutonomyModelError(
            "SELFDEV_MODEL_FORMAT_LINE_COUNT:"
            + str(len(lines))
        )

    if lines[4] != "GG_MODEL_RUNNER_OK":
        raise AutonomyModelError(
            "SELFDEV_MODEL_FORMAT_MARKER"
        )

    hypothesis = _selfdev_json_field(
        lines[0],
        "HYPOTHESIS_JSON=",
        "HYPOTHESIS",
        512,
    )

    old_text = _selfdev_json_field(
        lines[1],
        "OLD_JSON=",
        "OLD",
        4096,
    )

    new_text = _selfdev_json_field(
        lines[2],
        "NEW_JSON=",
        "NEW",
        4096,
        allow_empty=True,
    )

    why = _selfdev_json_field(
        lines[3],
        "WHY_JSON=",
        "WHY",
        512,
    )

    def require_meaningful(
        value: str,
        label: str,
    ) -> None:
        stripped = value.strip()
        useful = sum(
            char.isalnum() or char == "_"
            for char in stripped
        )

        if useful < 2:
            raise AutonomyModelError(
                "SELFDEV_SEMANTIC_CONTRACT:"
                + label
                + "_FILLER"
            )

    require_meaningful(
        hypothesis,
        "HYPOTHESIS",
    )
    require_meaningful(
        old_text,
        "OLD",
    )
    require_meaningful(
        why,
        "WHY",
    )

    normalized = {
        "schema": SELFDEV_SEMANTIC_SCHEMA,
        "hypothesis": hypothesis,
        "old_text": old_text,
        "new_text": new_text,
        "why": why,
    }

    if normalized["old_text"] == normalized["new_text"]:
        raise AutonomyModelError(
            "SELFDEV_SEMANTIC_CONTRACT:NO_OP"
        )

    return normalized


def execute_selfdev_semantic_transport(
    evidence_arg: str,
    render_arg: str,
    *,
    request_id: str,
    prompt: str,
) -> tuple[int, dict[str, str] | None]:
    """Run selfdev semantics over the proven local model transport."""
    evidence = Path(evidence_arg)

    if (
        evidence.is_symlink()
        or not evidence.is_dir()
    ):
        raise AutonomyModelError(
            "MODEL_EVIDENCE_INVALID"
        )

    request_id = _text(
        request_id,
        "REQUEST_ID",
        128,
    )

    prompt = _text(
        prompt,
        "PROMPT",
        32768,
    )

    old_id = base.REQUEST_ID
    old_prompt = base.PROMPT
    old_grammar = base.MODEL_GBNF

    try:
        base.REQUEST_ID = request_id
        base.PROMPT = prompt
        base.MODEL_GBNF = SELFDEV_GBNF

        rc = base.execute_synthetic(
            evidence_arg,
            render_arg,
        )

    finally:
        base.REQUEST_ID = old_id
        base.PROMPT = old_prompt
        base.MODEL_GBNF = old_grammar

    if rc != 0:
        return rc, None

    response_path = evidence / "response.json"

    if (
        response_path.is_symlink()
        or not response_path.is_file()
    ):
        raise AutonomyModelError(
            "MODEL_RESPONSE_MISSING"
        )

    try:
        response = json.loads(
            response_path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise AutonomyModelError(
            "MODEL_RESPONSE_PARSE_FAILED"
        ) from exc

    text = response.get("text")

    if type(text) is not str:
        raise AutonomyModelError(
            "MODEL_RESPONSE_TEXT_INVALID"
        )

    return (
        0,
        parse_selfdev_semantic_text(text),
    )


def run_selfdev_semantic_prompt(
    *,
    request_id: str,
    prompt: str,
) -> tuple[
    int,
    dict[str, str] | None,
    Path,
    str,
]:
    """Create evidence and run one selfdev semantic inference."""
    runtime = private_runtime_root()

    nonce = os.urandom(12).hex()

    evidence = runtime / (
        "gg-wb3d-model-runner." + nonce
    )

    if (
        evidence.exists()
        or evidence.is_symlink()
    ):
        raise AutonomyModelError(
            "MODEL_EVIDENCE_COLLISION"
        )

    evidence.mkdir(mode=0o700)

    render = base.discover_nvidia_render()

    rc, proposal = (
        execute_selfdev_semantic_transport(
            str(evidence),
            render,
            request_id=request_id,
            prompt=prompt,
        )
    )

    if rc == 0:
        if proposal is None:
            raise AutonomyModelError(
                "MODEL_SEMANTIC_PROPOSAL_MISSING"
            )

        target = (
            evidence
            / "selfdev-semantic-proposal.json"
        )

        payload = (
            json.dumps(
                proposal,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        base.write_new(
            target,
            payload,
            0o600,
        )

    return (
        rc,
        proposal,
        evidence,
        render,
    )


def build_prompt(request: dict[str, Any]) -> str:
    diagnostic = request["diagnostic"] or "NONE"
    return (
        "Du är en lokal semantisk reparationsproposer utan action-authority. "
        "Du får INTE välja sökväg, kommando, executable, nätverk, Git-operation "
        "eller behörighet. Föreslå endast en exakt single-line text replacement "
        "i den redan bundna ContextComposer.qml-kandidaten.\n"
        "Målet är:\n"
        + request["goal"]
        + "\n"
        "Tidigare verifierad diagnostik:\n"
        + diagnostic
        + "\n"
        "Verifierad read-only target:\n"
        "----- BEGIN TARGET -----\n"
        + request["target_text"]
        + "\n----- END TARGET -----\n"
        'Välj OLD som förekommer exakt en gång och NEW som är den minsta \nFör just denna verifiering är replacement-fälten redan bundna. OLD-fältets hela innehåll måste vara exakt: implicitHeight: 92. NEW-fältets hela innehåll måste vara exakt: implicitHeight: 93. HYPOTHESIS och WHY får inte innehålla extra fältetiketter såsom HYPOTHESIS:, OLD:, NEW:, WHY: eller REASON:. Skriv inga extra OLD/NEW/REASON-fält inne i något fält. Använd endast de fyra strukturella fälten HYPOTHESIS, OLD, NEW och WHY och avsluta med GG_MODEL_RUNNER_OK.'
        "rimliga ändringen mot målet. Svara endast i det grammar-bundna formatet."
    )


def execute_semantic_transport(
    evidence_arg: str,
    render_arg: str,
    *,
    request_id: str,
    prompt: str,
) -> tuple[int, dict[str, str] | None]:
    """Run the proven local semantic transport without granting action authority."""
    evidence = Path(evidence_arg)

    if (
        evidence.is_symlink()
        or not evidence.is_dir()
    ):
        raise AutonomyModelError(
            "MODEL_EVIDENCE_INVALID"
        )

    request_id = _text(
        request_id,
        "REQUEST_ID",
        128,
    )

    prompt = _text(
        prompt,
        "PROMPT",
        32768,
    )

    old_id = base.REQUEST_ID
    old_prompt = base.PROMPT
    old_grammar = base.MODEL_GBNF

    try:
        base.REQUEST_ID = (
            request_id
        )

        base.PROMPT = prompt

        base.MODEL_GBNF = (
            AUTONOMY_GBNF
        )

        rc = base.execute_synthetic(
            evidence_arg,
            render_arg,
        )

    finally:
        base.REQUEST_ID = old_id
        base.PROMPT = old_prompt
        base.MODEL_GBNF = (
            old_grammar
        )

    if rc != 0:
        return rc, None

    response_path = (
        evidence
        / "response.json"
    )

    if (
        response_path.is_symlink()
        or not response_path.is_file()
    ):
        raise AutonomyModelError(
            "MODEL_RESPONSE_MISSING"
        )

    try:
        response = json.loads(
            response_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise AutonomyModelError(
            "MODEL_RESPONSE_PARSE_FAILED"
        ) from exc

    text = response.get(
        "text"
    )

    if type(text) is not str:
        raise AutonomyModelError(
            "MODEL_RESPONSE_TEXT_INVALID"
        )

    proposal = (
        parse_semantic_text(text)
    )

    return 0, proposal


def run_semantic_prompt(
    *,
    request_id: str,
    prompt: str,
) -> tuple[
    int,
    dict[str, str] | None,
    Path,
    str,
]:
    """Create canonical evidence/render state and run the shared semantic transport."""
    runtime = private_runtime_root().resolve(
        strict=True
    )

    nonce = (
        os.urandom(12).hex()
    )

    evidence = (
        runtime
        / (
            "gg-wb3d-model-runner."
            + nonce
        )
    )

    if (
        evidence.exists()
        or evidence.is_symlink()
    ):
        raise AutonomyModelError(
            "MODEL_EVIDENCE_COLLISION"
        )

    evidence.mkdir(
        mode=0o700
    )

    render = (
        base.discover_nvidia_render()
    )

    rc, proposal = (
        execute_semantic_transport(
            str(evidence),
            render,
            request_id=request_id,
            prompt=prompt,
        )
    )

    if rc == 0:
        if proposal is None:
            raise AutonomyModelError(
                "MODEL_SEMANTIC_PROPOSAL_MISSING"
            )

        target = (
            evidence
            / "autonomy-semantic-proposal.json"
        )

        base.write_new(
            target,
            contract.canonical_json(
                proposal
            ),
            0o600,
        )

    return (
        rc,
        proposal,
        evidence,
        render,
    )


def execute(
    evidence_arg: str,
    render_arg: str,
    request_arg: str,
) -> int:
    request_path = (
        _safe_request_path(
            request_arg
        )
    )

    try:
        raw = json.loads(
            request_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise AutonomyModelError(
            "MODEL_REQUEST_PARSE_FAILED"
        ) from exc

    request = (
        validate_model_request(
            raw
        )
    )

    rc, proposal = (
        execute_semantic_transport(
            evidence_arg,
            render_arg,
            request_id=request[
                "request_id"
            ],
            prompt=build_prompt(
                request
            ),
        )
    )

    if rc != 0:
        return rc

    if proposal is None:
        raise AutonomyModelError(
            "MODEL_SEMANTIC_PROPOSAL_MISSING"
        )

    proposal_bytes = (
        contract.canonical_json(
            proposal
        )
    )

    target = (
        Path(evidence_arg)
        / "autonomy-semantic-proposal.json"
    )

    base.write_new(
        target,
        proposal_bytes,
        0o600,
    )

    print(
        "AUTONOMY_MODEL_SEMANTIC_PROPOSAL=PASS"
    )

    print(
        "MODEL_OUTPUT_AUTHORITY=UNTRUSTED_MODEL_OUTPUT"
    )

    print(
        "NETWORK_AUTHORITY=NONE"
    )

    print(
        "GENERAL_ACTION_AUTHORITY=NONE"
    )

    return 0


def selftest() -> int:
    sample = (
        "HYPOTHESIS:Detta är en kandidat|"
        "OLD:implicitHeight: 92|"
        "NEW:implicitHeight: 93|"
        "WHY:Minsta exakta ändring|"
        "GG_MODEL_RUNNER_OK"
    )
    parsed = parse_semantic_text(sample)
    if parsed["old_text"] != "implicitHeight: 92":
        raise AutonomyModelError("SELFTEST_PARSE_MISMATCH")
    forbidden = {
        "path", "argv", "executable", "shell", "network",
        "authority", "execute", "command",
    }
    if forbidden & set(parsed):
        raise AutonomyModelError("SELFTEST_FORBIDDEN_FIELD")
    print("AUTONOMY_MODEL_RUNNER_SELFTEST=PASS")
    print("MODEL_INFERENCE=NO")
    print("MODEL_OUTPUT_AUTHORITY=UNTRUSTED_MODEL_OUTPUT")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        return selftest()
    if len(args) == 4 and args[0] == "--execute":
        return execute(args[1], args[2], args[3])
    print(
        "usage: autonomy_model_runner.py [--execute EVIDENCE RENDER REQUEST]",
        file=sys.stderr,
    )
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
