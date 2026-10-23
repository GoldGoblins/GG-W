#!/usr/bin/env python3
"Deterministic tests for the pure local AI adapter data contract."

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Callable

PROJECT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT / "backend/local_ai_contract.py"
REQUEST_SCHEMA_PATH = PROJECT / "schemas/local-ai-request.schema.json"
RESPONSE_SCHEMA_PATH = PROJECT / "schemas/local-ai-response.schema.json"

FORBIDDEN_REQUEST_FIELDS = (
    "command",
    "argv",
    "executable",
    "path",
    "mount",
    "device",
    "environment",
    "network",
    "image",
    "model_path",
    "podman_args",
    "shell",
    "working_directory",
    "approval",
    "write_target",
)

FORBIDDEN_IMPORT_ROOTS = {
    "subprocess",
    "socket",
    "requests",
    "httpx",
    "urllib",
    "pty",
    "os",
    "PySide6",
    "gg_agent_core",
    "gg_orchestrator",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def load_contract() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gg_local_ai_contract",
        CONTRACT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load local AI contract module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_contract_error(
    contract: ModuleType,
    action: Callable[[], object],
    marker: str,
) -> None:
    try:
        action()
    except contract.ContractError:
        return
    raise RuntimeError("Expected ContractError: " + marker)


def main() -> int:
    contract = load_contract()

    request = {
        "schema": contract.REQUEST_SCHEMA,
        "request_id": "req-001",
        "mode": "CHAT",
        "prompt": "Förklara skillnaden mellan syntax och målmiljötest.",
    }
    validated = contract.validate_request(request)
    require(validated == request, "Valid CHAT request changed unexpectedly.")

    expect_contract_error(
        contract,
        lambda: contract.validate_request({**request, "prompt": ""}),
        "empty_prompt",
    )

    expect_contract_error(
        contract,
        lambda: contract.validate_request({**request, "unknown": True}),
        "unknown_field",
    )

    for field in FORBIDDEN_REQUEST_FIELDS:
        expect_contract_error(
            contract,
            lambda field=field: contract.validate_request(
                {**request, field: "blocked"}
            ),
            "forbidden_field_" + field,
        )

    expect_contract_error(
        contract,
        lambda: contract.validate_request(
            {
                **request,
                "prompt": "x" * (contract.MAX_PROMPT_CHARS + 1),
            }
        ),
        "oversized_prompt",
    )

    response = {
        "schema": contract.RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "status": "PASS",
        "text": "Syntetiskt kontraktssvar.",
        "evidence": {},
    }
    require(
        contract.validate_response(response, request["request_id"]) == response,
        "Valid response changed unexpectedly.",
    )

    expect_contract_error(
        contract,
        lambda: contract.validate_response(response, "req-other"),
        "response_request_id_mismatch",
    )

    expect_contract_error(
        contract,
        lambda: contract.validate_response(
            {**response, "status": "UNKNOWN"},
            request["request_id"],
        ),
        "invalid_response_status",
    )

    expect_contract_error(
        contract,
        lambda: contract.validate_response(
            {**response, "hidden_reasoning": "forbidden"},
            request["request_id"],
        ),
        "extra_response_field",
    )

    first = {
        "schema": contract.REQUEST_SCHEMA,
        "request_id": "req-canonical",
        "mode": "CHAT",
        "prompt": "Deterministisk JSON.",
    }
    second = {
        "prompt": "Deterministisk JSON.",
        "mode": "CHAT",
        "request_id": "req-canonical",
        "schema": contract.REQUEST_SCHEMA,
    }
    canonical_a = contract.canonical_request_json(first)
    canonical_b = contract.canonical_request_json(second)
    require(canonical_a == canonical_b, "Canonical JSON is not deterministic.")
    require(
        json.loads(canonical_a) == first,
        "Canonical JSON changed request semantics.",
    )

    tree = ast.parse(
        CONTRACT_PATH.read_text(encoding="utf-8"),
        filename=str(CONTRACT_PATH),
    )
    roots = import_roots(tree)
    require(
        roots == {"__future__", "json", "typing"},
        "Unexpected contract import roots: " + repr(sorted(roots)),
    )
    require(
        not (roots & FORBIDDEN_IMPORT_ROOTS),
        "Execution/network import found.",
    )

    request_schema = json.loads(
        REQUEST_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    response_schema = json.loads(
        RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    require(
        request_schema["$id"] == contract.REQUEST_SCHEMA,
        "Request schema ID mismatch.",
    )
    require(
        response_schema["$id"] == contract.RESPONSE_SCHEMA,
        "Response schema ID mismatch.",
    )
    require(
        request_schema["additionalProperties"] is False,
        "Request schema is not fail closed.",
    )
    require(
        response_schema["additionalProperties"] is False,
        "Response schema is not fail closed.",
    )
    require(
        set(request_schema["properties"]) == {
            "schema",
            "request_id",
            "mode",
            "prompt",
        },
        "Request schema field set mismatch.",
    )
    require(
        set(response_schema["properties"]) == {
            "schema",
            "request_id",
            "status",
            "text",
            "evidence",
        },
        "Response schema field set mismatch.",
    )

    print("LOCAL_AI_CONTRACT_TEST=PASS")
    print("FORBIDDEN_REQUEST_FIELDS_NEGATIVE_TEST=PASS")
    print("CANONICAL_JSON_DETERMINISM=PASS")
    print("FORBIDDEN_EXECUTION_IMPORTS=ABSENT")
    print("MODEL_EXECUTION=NO")
    print("ORCHESTRATOR_EXECUTION=NO")
    print("NETWORK_EXECUTION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
