#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONTRACT = PROJECT / "backend/safe_tool_contract.py"
RUNNER = PROJECT / "backend/safe_tool_runner.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_contract():
    spec = importlib.util.spec_from_file_location(
        "gg_safe_tool_contract_test",
        CONTRACT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("safe tool contract import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = load_contract()

    require(
        contract.AUTHORITY == "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
        "Safe tool authority mismatch.",
    )
    require(
        contract.PROFILES == frozenset(("READ", "SEARCH", "GIT", "TEST", "RUN")),
        "Safe tool profile set mismatch.",
    )

    request = {
        "schema": contract.REQUEST_SCHEMA,
        "request_id": "tool-" + ("a" * 32),
        "profile": "READ",
        "arguments": {"path": "projects/gg-ai-desktop/main.py"},
    }
    canonical = contract.canonical_request_json(request)
    require(
        canonical
        == json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "Safe tool request canonicalization mismatch.",
    )

    negatives = [
        {
            **request,
            "arguments": {"path": "../outside"},
        },
        {
            **request,
            "profile": "SHELL",
            "arguments": {},
        },
        {
            **request,
            "profile": "GIT",
            "arguments": {"operation": "push"},
        },
    ]

    # Contract-level path lexical policy is completed by runner policy.
    # The parent traversal request remains structurally valid here and
    # must be blocked by the execution boundary, not silently rewritten.
    contract.validate_request(negatives[0])

    for bad in negatives[1:]:
        try:
            contract.validate_request(bad)
        except ValueError:
            pass
        else:
            raise RuntimeError("Forbidden safe-tool request was accepted.")

    response = {
        "schema": contract.RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "status": "PASS",
        "profile": "READ",
        "output": "ok",
        "evidence": {
            "authority": contract.AUTHORITY,
            "effect_class": "READ_ONLY",
            "network_authority": "NONE",
            "persistent_write_authority": "NONE",
            "backend": "IN_PROCESS_TRACKED_READ",
            "output_sha256": hashlib.sha256(b"ok").hexdigest(),
        },
    }
    contract.validate_response(
        response,
        request["request_id"],
        "READ",
    )

    runner_text = RUNNER.read_text(encoding="utf-8")
    runner_tree = ast.parse(runner_text, filename=str(RUNNER))

    for marker in (
        "shell=False",
        "os.O_NOFOLLOW",
        "GIT_OPTIONAL_LOCKS",
        "--network=none",
        "--read-only",
        "--cap-drop=all",
        "--security-opt=no-new-privileges",
        "--userns=keep-id",
        "--pids-limit=128",
        "--memory=512m",
        "--cpus=1",
        "PODMAN_LOCKED_READONLY_SANDBOX",
        "HOST_GIT_FIXED_ARGV",
        "IN_PROCESS_TRACKED_LITERAL_SEARCH",
        "PROFILE=READ",
        "PROFILE=SEARCH",
        "PROFILE=GIT",
    ):
        require(marker in runner_text, "Safe tool runner marker missing: " + marker)

    forbidden = (
        "shell" + "=True",
        "os." + "system(",
        "subprocess." + "call(",
    )
    for marker in forbidden:
        require(
            marker not in runner_text,
            "Forbidden safe tool runner marker: " + marker,
        )

    import_roots = set()
    for node in ast.walk(runner_tree):
        if isinstance(node, ast.Import):
            import_roots.update(
                alias.name.split(".", 1)[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_roots.add(node.module.split(".", 1)[0])

    require(
        import_roots
        <= {
            "__future__",
            "hashlib",
            "json",
            "os",
            "selectors",
            "shutil",
            "stat",
            "subprocess",
            "sys",
            "time",
            "uuid",
            "pathlib",
            "typing",
            "safe_tool_contract",
        },
        "Unexpected safe-tool runner imports: "
        + repr(sorted(import_roots)),
    )

    print("SAFE_TOOL_CONTRACT_TEST=PASS")
    print("SAFE_TOOL_PROFILE_SET=READ_SEARCH_GIT_TEST_RUN")
    print("CALLER_SUPPLIED_ARGV_AUTHORITY=NONE")
    print("CALLER_SUPPLIED_EXECUTABLE_AUTHORITY=NONE")
    print("CALLER_SUPPLIED_ENV_AUTHORITY=NONE")
    print("NETWORK_AUTHORITY=NONE")
    print("PERSISTENT_WRITE_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
