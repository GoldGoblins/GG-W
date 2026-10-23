#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONTRACT = PROJECT / "backend/write_contract.py"
RUNNER = PROJECT / "backend/write_runner.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_contract():
    spec = importlib.util.spec_from_file_location(
        "gg_write_contract_test",
        CONTRACT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("write contract import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module




def load_runner():
    backend = str(CONTRACT.parent)
    sys.path.insert(0, backend)
    try:
        spec = importlib.util.spec_from_file_location(
            "gg_write_runner_test",
            RUNNER,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("write runner import spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(backend)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
    )


def synthetic_write_lifecycle(contract) -> None:
    runner = load_runner()

    with tempfile.TemporaryDirectory(
        prefix="gg-write-contract-test."
    ) as temp_name:
        temp = Path(temp_name)
        repo = temp / "repo"
        project = repo / "projects/gg-ai-desktop"
        target = project / contract.TARGET_RELATIVE_PATH
        runtime = temp / "run"

        target.parent.mkdir(parents=True)
        runtime.mkdir()
        target.write_text(
            "alpha\\nimplicitHeight: 92\\nomega\\n",
            encoding="utf-8",
        )
        os.chmod(target, 0o644)

        for args in (
            ("init", "-q"),
            ("config", "user.email", "synthetic@goldgoblins.invalid"),
            ("config", "user.name", "GG Synthetic Gate"),
            ("add", "."),
            ("commit", "-qm", "synthetic-base"),
        ):
            result = git(repo, *args)
            require(
                result.returncode == 0,
                "Synthetic Git fixture failed: "
                + " ".join(args)
                + " stderr="
                + result.stderr,
            )

        runner.PROJECT = project
        runner.REPO = repo
        runner.RUNTIME = runtime
        runner._qml_gate = (
            lambda candidate, evidence, label:
                hashlib.sha256(
                    label.encode("utf-8") + b"\\0" + candidate
                ).hexdigest()
        )

        proposal_id = "proposal-" + ("b" * 32)
        evidence = runtime / ("gg-write-proposal." + ("b" * 32))
        evidence.mkdir(mode=0o700)

        proposal_request = {
            "schema": contract.REQUEST_SCHEMA,
            "request_id": "write-" + ("c" * 32),
            "action": contract.ACTION_PROPOSE,
            "proposal_id": proposal_id,
            "context_reference": contract.TARGET_CONTEXT_REFERENCE,
            "workspace_object_id":
                contract.TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {
                "old_text": "implicitHeight: 92",
                "new_text": "implicitHeight: 93",
            },
        }

        proposal_response = runner._propose(
            proposal_request,
            evidence,
        )
        require(
            proposal_response["status"] == "WAITING_APPROVAL",
            "Synthetic proposal did not wait for approval.",
        )
        require(
            target.read_text(encoding="utf-8")
            == "alpha\\nimplicitHeight: 92\\nomega\\n",
            "Proposal performed a source write.",
        )

        proposal = json.loads(
            (evidence / "proposal.json").read_text(encoding="utf-8")
        )

        apply_request = {
            "schema": contract.REQUEST_SCHEMA,
            "request_id": "write-" + ("d" * 32),
            "action": contract.ACTION_APPROVE,
            "proposal_id": proposal_id,
            "context_reference": contract.TARGET_CONTEXT_REFERENCE,
            "workspace_object_id":
                contract.TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {
                "candidate_sha256":
                    proposal["candidate_sha256"],
            },
        }
        apply_response = runner._approve(
            apply_request,
            evidence,
        )
        require(
            apply_response["status"] == "APPLIED_VERIFIED",
            "Synthetic apply did not verify.",
        )
        require(
            "implicitHeight: 93"
            in target.read_text(encoding="utf-8"),
            "Synthetic apply effect missing.",
        )

        rollback_request = {
            "schema": contract.REQUEST_SCHEMA,
            "request_id": "write-" + ("e" * 32),
            "action": contract.ACTION_ROLLBACK,
            "proposal_id": proposal_id,
            "context_reference": contract.TARGET_CONTEXT_REFERENCE,
            "workspace_object_id":
                contract.TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {
                "candidate_sha256":
                    proposal["candidate_sha256"],
                "before_sha256":
                    proposal["before_sha256"],
            },
        }
        rollback_response = runner._rollback(
            rollback_request,
            evidence,
        )
        require(
            rollback_response["status"]
            == "ROLLED_BACK_VERIFIED",
            "Synthetic rollback did not verify.",
        )
        require(
            target.read_text(encoding="utf-8")
            == "alpha\\nimplicitHeight: 92\\nomega\\n",
            "Synthetic rollback did not restore original.",
        )
        require(
            git(repo, "status", "--porcelain=v1").stdout == "",
            "Synthetic rollback did not restore clean Git state.",
        )

        reject_id = "proposal-" + ("f" * 32)
        reject_evidence = runtime / (
            "gg-write-proposal." + ("f" * 32)
        )
        reject_evidence.mkdir(mode=0o700)

        reject_proposal_request = {
            "schema": contract.REQUEST_SCHEMA,
            "request_id": "write-" + ("1" * 32),
            "action": contract.ACTION_PROPOSE,
            "proposal_id": reject_id,
            "context_reference": contract.TARGET_CONTEXT_REFERENCE,
            "workspace_object_id":
                contract.TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {
                "old_text": "implicitHeight: 92",
                "new_text": "implicitHeight: 94",
            },
        }
        reject_proposal_response = runner._propose(
            reject_proposal_request,
            reject_evidence,
        )
        require(
            reject_proposal_response["status"]
            == "WAITING_APPROVAL",
            "Synthetic reject proposal failed.",
        )
        reject_proposal = json.loads(
            (reject_evidence / "proposal.json").read_text(
                encoding="utf-8"
            )
        )

        reject_request = {
            "schema": contract.REQUEST_SCHEMA,
            "request_id": "write-" + ("2" * 32),
            "action": contract.ACTION_REJECT,
            "proposal_id": reject_id,
            "context_reference": contract.TARGET_CONTEXT_REFERENCE,
            "workspace_object_id":
                contract.TARGET_WORKSPACE_OBJECT_ID,
            "arguments": {
                "candidate_sha256":
                    reject_proposal["candidate_sha256"],
            },
        }
        reject_response = runner._reject(
            reject_request,
            reject_evidence,
        )
        require(
            reject_response["status"] == "REJECTED_NO_WRITE",
            "Synthetic reject did not verify.",
        )
        require(
            target.read_text(encoding="utf-8")
            == "alpha\\nimplicitHeight: 92\\nomega\\n",
            "Synthetic reject performed a write.",
        )
        require(
            git(repo, "status", "--porcelain=v1").stdout == "",
            "Synthetic reject changed Git state.",
        )


def main() -> int:
    contract = load_contract()

    require(
        contract.AUTHORITY == "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        "Limited Write authority mismatch.",
    )
    require(
        contract.TARGET_CONTEXT_REFERENCE == "@current",
        "Limited Write context target mismatch.",
    )
    require(
        contract.TARGET_WORKSPACE_OBJECT_ID
        == "ws.file.context-composer",
        "Limited Write Workspace target mismatch.",
    )
    require(
        contract.TARGET_RELATIVE_PATH
        == "qml/components/ContextComposer.qml",
        "Limited Write source target mismatch.",
    )
    require(
        contract.NETWORK_AUTHORITY == "NONE",
        "Limited Write network authority changed.",
    )
    require(
        contract.GENERAL_ACTION_AUTHORITY == "NONE",
        "Limited Write general action authority changed.",
    )
    require(
        contract.MODEL_AUTONOMOUS_WRITE_INVOCATION == "DISABLED_V1",
        "Autonomous model write authority changed.",
    )

    proposal = {
        "schema": contract.REQUEST_SCHEMA,
        "request_id": "write-" + ("a" * 32),
        "action": "PROPOSE",
        "proposal_id": "proposal-" + ("b" * 32),
        "context_reference": "@current",
        "workspace_object_id": "ws.file.context-composer",
        "arguments": {
            "old_text": "implicitHeight: 92",
            "new_text": "implicitHeight: 93",
        },
    }

    canonical = contract.canonical_request_json(proposal)
    require(
        canonical
        == json.dumps(
            proposal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "Limited Write canonical request mismatch.",
    )

    negatives = [
        {
            **proposal,
            "workspace_object_id": "ws.fixture.demo",
        },
        {
            **proposal,
            "context_reference": "@other",
        },
        {
            **proposal,
            "arguments": {
                "old_text": "x",
                "new_text": "",
            },
        },
        {
            **proposal,
            "action": "SHELL",
            "arguments": {},
        },
    ]

    for bad in negatives:
        try:
            contract.validate_request(bad)
        except ValueError:
            pass
        else:
            raise RuntimeError("Forbidden Limited Write request was accepted.")

    output = "WRITE_PROPOSAL=WAITING_APPROVAL"
    response = {
        "schema": contract.RESPONSE_SCHEMA,
        "request_id": proposal["request_id"],
        "action": proposal["action"],
        "proposal_id": proposal["proposal_id"],
        "status": "WAITING_APPROVAL",
        "output": output,
        "evidence": {
            "authority": contract.AUTHORITY,
            "effect_class": contract.EFFECT_CLASS,
            "network_authority": "NONE",
            "general_action_authority": "NONE",
            "model_autonomous_write_invocation": "DISABLED_V1",
            "target_relative_path": contract.TARGET_RELATIVE_PATH,
            "before_sha256": "c" * 64,
            "candidate_sha256": "d" * 64,
            "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "gate_status": "PASS",
        },
    }
    contract.validate_response(
        response,
        proposal["request_id"],
        proposal["action"],
        proposal["proposal_id"],
    )

    runner_text = RUNNER.read_text(encoding="utf-8")
    runner_tree = ast.parse(runner_text, filename=str(RUNNER))

    for marker in (
        "os.O_NOFOLLOW",
        "os.O_EXCL",
        "os.replace",
        "os.fsync",
        "shell=False",
        '"--network=none"',
        '"--read-only"',
        '"--cap-drop=all"',
        '"--security-opt=no-new-privileges"',
        "PATCH_MATCH_COUNT_",
        "TARGET_REQUIRED_MODE = 0o644",
        "TARGET_REPO_RELATIVE",
        "PROPOSAL_STALE_BEFORE_APPLY",
        "TARGET_CHANGED_DURING_GATE",
        "ROLLBACK_TARGET_NOT_EXACT_CANDIDATE",
        "GIT_STATUS=CLEAN",
    ):
        require(
            marker in runner_text,
            "Limited Write runner marker missing: " + marker,
        )

    for forbidden in (
        "shell" + "=True",
        "os." + "system(",
        "subprocess." + "call(",
        "git commit",
        "git push",
        "sudo",
    ):
        require(
            forbidden not in runner_text,
            "Forbidden Limited Write marker: " + forbidden,
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
            "difflib",
            "hashlib",
            "json",
            "os",
            "shutil",
            "stat",
            "subprocess",
            "sys",
            "time",
            "pathlib",
            "typing",
            "write_contract",
        },
        "Unexpected Limited Write runner imports: "
        + repr(sorted(import_roots)),
    )

    synthetic_write_lifecycle(contract)

    print("LIMITED_WRITE_CONTRACT_TEST=PASS")
    print("SYNTHETIC_PROPOSE_APPROVE_ROLLBACK=PASS")
    print("SYNTHETIC_REJECT_NO_WRITE=PASS")
    print("WRITE_AUTHORITY=YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1")
    print("WRITE_TARGET=@current:ws.file.context-composer")
    print("PATCH_POLICY=EXACT_SINGLE_OCCURRENCE_REPLACE_ONLY")
    print("APPROVAL_BINDING=PROPOSAL_ID_PLUS_CANDIDATE_SHA256")
    print("QML_GATE_REQUIRED_BEFORE_APPLY=YES")
    print("ATOMIC_REPLACE=YES")
    print("ROLLBACK=BOUND_ORIGINAL_BYTES")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    print("MODEL_AUTONOMOUS_WRITE_INVOCATION=DISABLED_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
