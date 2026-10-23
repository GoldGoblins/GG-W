#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT / "backend/autonomy_contract.py"


def load():
    spec = importlib.util.spec_from_file_location("gg_autonomy_contract_test", CONTRACT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("contract import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(value, message):
    if not value:
        raise RuntimeError(message)


def grant(c):
    return {
        "schema": c.GRANT_SCHEMA,
        "task_id": "task-" + ("a" * 32),
        "session_id": "session-" + ("b" * 32),
        "base_head": "c" * 40,
        "context_reference": c.TARGET_CONTEXT_REFERENCE,
        "workspace_object_id": c.TARGET_WORKSPACE_OBJECT_ID,
        "target_relative_path": c.TARGET_RELATIVE_PATH,
        "goal": "Ändra en avgränsad detalj och verifiera.",
        "done_when": "Verifierad kandidat och separat host-effect verification.",
        "allowed_green_tools": list(c.ALLOWED_GREEN_TOOLS),
        "max_steps": 24,
        "max_model_calls": 3,
        "max_candidate_writes": 3,
        "max_candidate_bytes": c.TARGET_MAX_BYTES,
        "network_authority": "NONE",
        "general_action_authority": "NONE",
        "host_write_authority": c.HOST_WRITE_AUTHORITY,
        "git_mutation_authority": "NONE",
        "shell_authority": "NONE",
        "self_authorization": "FORBIDDEN",
        "authority_file_mutation": "FORBIDDEN",
        "model_output_authority": "UNTRUSTED_MODEL_OUTPUT",
        "candidate_workspace": "RUNTIME_TASK_BOUND",
        "session_bound": True,
        "replay_protection": "RUNTIME_SINGLE_USE_RECEIPT",
        "monotonic_step_sequence": True,
        "persistent_apply_boundary": c.PERSISTENT_APPLY_BOUNDARY,
        "test_mode": "NONE",
    }


def main():
    c = load()
    g = c.validate_grant(grant(c))
    digest = c.grant_sha256(g)
    require(len(digest) == 64, "grant hash invalid")

    bad = copy.deepcopy(g)
    bad["network_authority"] = "ANY"
    try:
        c.validate_grant(bad)
    except ValueError:
        pass
    else:
        raise RuntimeError("network expansion accepted")

    bad = copy.deepcopy(g)
    bad["host_write_authority"] = "YES"
    try:
        c.validate_grant(bad)
    except ValueError:
        pass
    else:
        raise RuntimeError("host write expansion accepted")

    proposal = c.validate_semantic_proposal(
        {
            "schema": c.SEMANTIC_PROPOSAL_SCHEMA,
            "hypothesis": "En minimal textändring är relevant.",
            "old_text": "implicitHeight: 92",
            "new_text": "implicitHeight: 93",
            "why": "Minsta avgränsade kandidat.",
        }
    )
    require(set(proposal) == {"schema", "hypothesis", "old_text", "new_text", "why"},
            "semantic proposal surface drift")

    for forbidden in ("path", "argv", "command", "execute", "authority"):
        require(forbidden not in proposal, "forbidden semantic field present")

    canonical = c.canonical_json(g)
    require(hashlib.sha256(canonical).hexdigest() == digest, "canonical grant mismatch")

    print("AUTONOMY_CONTRACT_TEST=PASS")
    print("TASK_GRANT=SESSION_BOUND_SINGLE_USE_RUNTIME_RECEIPT")
    print("MODEL_OUTPUT_AUTHORITY=UNTRUSTED_MODEL_OUTPUT")
    print("HOST_WRITE_AUTHORITY=NONE_BEFORE_SEPARATE_APPROVAL")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
