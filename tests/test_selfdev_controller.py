#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = Path(f"/run/user/{os.getuid()}").resolve(strict=True)

sys.path.insert(0, str(PROJECT))

main = importlib.import_module("main")
semantic = importlib.import_module(
    "backend.autonomy_model_runner"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            *args,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )

    if result.returncode != 0:
        raise RuntimeError(
            "git failed: "
            + " ".join(args)
            + ":"
            + result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    return result.stdout.decode(
        "utf-8",
        errors="strict",
    ).strip()


def semantic_profile_contract() -> None:
    require(
        "segment ::= char{1,180}"
        in semantic.AUTONOMY_GBNF,
        "Legacy autonomy grammar drifted.",
    )

    require(
        "<<GG_SELFDEV_OLD>>"
        not in semantic.SELFDEV_GBNF,
        "Ambiguous selfdev sentinel framing survived.",
    )

    for marker in (
        "ijtail ::= ijchar{0,255}",
        "ijfull ::= ijchar{255}",
        "hjson ::= lead ijtail",
        "oldjson ::= ijseq8 lead ijseq8",
        "newjson ::= ijseq16",
        "whyjson ::= lead ijtail",
    ):
        require(
            marker in semantic.SELFDEV_GBNF,
            "Bounded selfdev grammar marker missing: " + marker,
        )

    for width in range(2, 17):
        previous = (
            "ijtail"
            if width == 2
            else "ijseq" + str(width - 1)
        )
        marker = (
            "ijseq"
            + str(width)
            + " ::= ijfull "
            + previous
            + " | "
            + previous
        )
        require(
            marker in semantic.SELFDEV_GBNF,
            "Bounded selfdev grammar chain missing: "
            + marker,
        )

    for forbidden in (
        "hjson ::= lead ijchar*",
        "oldjson ::= ijchar* lead ijchar*",
        "newjson ::= ijchar*",
        "whyjson ::= lead ijchar*",
    ):
        require(
            forbidden not in semantic.SELFDEV_GBNF,
            "Unbounded selfdev grammar survived: " + forbidden,
        )

    repetition_bounds = [
        int(match.group(2) or match.group(1))
        for match in re.finditer(
            r"\{(\d+)(?:,(\d+))?\}",
            semantic.SELFDEV_GBNF,
        )
    ]
    require(
        repetition_bounds and max(repetition_bounds) <= 255,
        "Selfdev grammar exceeds llama.cpp sane repetition bounds.",
    )
    for invalid_marker in (
        "ijchar{0,1023}",
        "ijchar{0,2048}",
        "ijchar{1,6000}",
        "ijchar{0,6000}",
        "inner-char{0,8192}",
    ):
        require(
            invalid_marker not in semantic.SELFDEV_GBNF,
            "Known llama.cpp-crashing grammar survived: " + invalid_marker,
        )

    require(
        8 * 255 + 1 + 8 * 255 == 4081,
        "OLD grammar capacity changed.",
    )
    require(
        16 * 255 == 4080,
        "NEW grammar capacity changed.",
    )

    old_text = (
        "def gg_probe(value: int) -> int:\n"
        "    marker = \"<<GG_SELFDEV_OLD>> | OLD_JSON=\\\"x\\\"\"\n"
        "    path = r\"C:\\\\GG\\\\probe\"\n"
        "    return value | 1"
    )

    new_text = (
        "def gg_probe(value: int) -> int:\n"
        "    marker = \"<<GG_SELFDEV_NEW>> | NEW_JSON=\\\"y\\\"\"\n"
        "    path = r\"C:\\\\GG\\\\probe\"\n"
        "    adjusted = value | 1\n"
        "    return adjusted"
    )

    sample = "\n".join(
        (
            "HYPOTHESIS_JSON="
            + json.dumps(
                "bounded framing | with OLD_JSON= text",
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "OLD_JSON="
            + json.dumps(
                old_text,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "NEW_JSON="
            + json.dumps(
                new_text,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "WHY_JSON="
            + json.dumps(
                "quotes, slashes, pipes and former sentinels stay payload",
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "GG_MODEL_RUNNER_OK",
        )
    )

    parsed = semantic.parse_selfdev_semantic_text(
        sample
    )

    require(
        parsed["old_text"] == old_text,
        "Selfdev OLD JSON decode changed bytes.",
    )

    require(
        parsed["new_text"] == new_text,
        "Selfdev NEW JSON decode changed bytes.",
    )

    require(
        "\n" in parsed["old_text"]
        and "|" in parsed["old_text"]
        and "\\" in parsed["old_text"]
        and "<<GG_SELFDEV_OLD>>"
        in parsed["old_text"],
        "Adversarial selfdev payload lost framing characters.",
    )

    malformed = (
        'HYPOTHESIS_JSON="ok"\n'
        'OLD_JSON="alpha"\n'
        'INJECTED_PROTOCOL_LINE\n'
        'NEW_JSON="beta"\n'
        'WHY_JSON="bad framing"\n'
        'GG_MODEL_RUNNER_OK'
    )

    try:
        semantic.parse_selfdev_semantic_text(
            malformed
        )
    except semantic.AutonomyModelError as exc:
        require(
            "SELFDEV_MODEL_FORMAT_LINE_COUNT:"
            in str(exc),
            "Embedded framing classified incorrectly.",
        )
    else:
        raise RuntimeError(
            "Embedded protocol line was accepted."
        )

    no_op = "\n".join(
        (
            'HYPOTHESIS_JSON="no op"',
            'OLD_JSON="alpha"',
            'NEW_JSON="alpha"',
            'WHY_JSON="no op"',
            "GG_MODEL_RUNNER_OK",
        )
    )

    try:
        semantic.parse_selfdev_semantic_text(
            no_op
        )
    except semantic.AutonomyModelError as exc:
        require(
            "SELFDEV_SEMANTIC_CONTRACT:NO_OP"
            in str(exc),
            "Selfdev no-op classified incorrectly.",
        )
    else:
        raise RuntimeError(
            "Selfdev no-op accepted."
        )



def patch_contract() -> None:
    probe = (
        RUNTIME
        / (
            "gg-selfdev-patch-contract."
            + uuid.uuid4().hex
            + ".py"
        )
    )

    try:
        original = (
            "def alpha(value: int) -> int:\n"
            "    return value | 1\n"
        )

        write_private(
            probe,
            original.encode("utf-8"),
        )

        main._selfdev_apply_patch(
            probe,
            {
                "action": "PATCH",
                "summary": "multiline",
                "old_text": (
                    "def alpha(value: int) -> int:\n"
                    "    return value | 1"
                ),
                "new_text": (
                    "def alpha(value: int) -> int:\n"
                    "    adjusted = value | 1\n"
                    "    return adjusted"
                ),
            },
        )

        main._selfdev_compile(probe)

        before_reject = probe.read_bytes()

        try:
            main._selfdev_apply_patch(
                probe,
                {
                    "action": "PATCH",
                    "summary": "bad old",
                    "old_text": "not present",
                    "new_text": "still not present",
                },
            )
        except main.SelfdevBridgeError as exc:
            require(
                str(exc)
                == "OLD_TEXT_OCCURRENCE_COUNT:0",
                "Bad OLD classification changed.",
            )
        else:
            raise RuntimeError(
                "Bad OLD unexpectedly applied."
            )

        require(
            probe.read_bytes() == before_reject,
            "Rejected patch changed candidate.",
        )

    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def retry_matrix_contract() -> None:
    retry = main._selfdev_should_retry
    error = main.SelfdevBridgeError

    recoverable = (
        (
            "MODEL",
            error(
                "SHARED_SEMANTIC_TRANSPORT:"
                "AutonomyModelError:"
                "SELFDEV_SEMANTIC_CONTRACT:NO_OP"
            ),
        ),
        (
            "MODEL",
            error(
                "SHARED_SEMANTIC_TRANSPORT:"
                "AutonomyModelError:"
                "SELFDEV_MODEL_FORMAT_MARKER"
            ),
        ),
        (
            "PATCH",
            error("OLD_TEXT_OCCURRENCE_COUNT:0"),
        ),
        (
            "PATCH",
            error("CANDIDATE_SIZE_INVALID"),
        ),
        (
            "COMPILE",
            SyntaxError("synthetic syntax"),
        ),
        (
            "DONE",
            error("DONE_WITHOUT_CHANGE"),
        ),
        (
            "VERIFY",
            error(
                "FOUNDATION_GATE_NOT_PASS:"
                '{"status":"FAIL"}'
            ),
        ),
        (
            "VERIFY",
            error(
                "REGRESSION_FAILED:"
                "tests/example.py:boom"
            ),
        ),
    )

    for stage, exc in recoverable:
        require(
            retry(stage, exc, False),
            "Recoverable branch not retryable: "
            + stage
            + ":"
            + str(exc),
        )

        require(
            not retry(stage, exc, True),
            "Synthetic mode did not fail closed: "
            + stage,
        )

    hard = (
        (
            "MODEL",
            error(
                "SHARED_SEMANTIC_TRANSPORT_RC:2"
            ),
        ),
        (
            "MODEL",
            error(
                "SHARED_SEMANTIC_TRANSPORT:"
                "RunnerStop:runtime_image_id_drift"
            ),
        ),
        (
            "PATCH",
            OSError("candidate io"),
        ),
        (
            "COMPILE",
            OSError("candidate io"),
        ),
        (
            "VERIFY",
            error("FOUNDATION_IMAGE_ID_DRIFT"),
        ),
        (
            "VERIFY",
            error("FOUNDATION_REPORT_MISSING"),
        ),
        (
            "VERIFY",
            error("FOUNDATION_SOURCE_SHA_MISMATCH"),
        ),
        (
            "VERIFY",
            error(
                "REGRESSION_TEST_MISSING:"
                "tests/test_autonomy_contract.py"
            ),
        ),
        (
            "STATE",
            error("BASE_HEAD_DRIFT"),
        ),
        (
            "STATE",
            error("HOST_MAIN_CHANGED_DURING_SELFDEV"),
        ),
        (
            "BUDGET",
            error("MODEL_CALL_LIMIT_EXCEEDED"),
        ),
        (
            "BUDGET",
            error("PATCH_LIMIT_EXCEEDED"),
        ),
    )

    for stage, exc in hard:
        require(
            not retry(stage, exc, False),
            "Hard-stop branch became retryable: "
            + stage
            + ":"
            + str(exc),
        )


def context_contract() -> None:
    source = Path(
        main.__file__
    ).read_text(
        encoding="utf-8"
    )

    context = main._selfdev_source_context(
        source,
        "REGRESSION_FAILED:synthetic",
        24000,
    )

    for marker in (
        "DIAGNOSTIC",
        "FUNCTION parse_selfdev_command",
        "FUNCTION parse_autonomy_command",
        "FUNCTION parse_write_command",
        "FUNCTION parse_safe_tool_command",
        "ChatBridge.submit",
        "ChatBridge._submit_selfdev",
    ):
        require(
            marker in context,
            "Focused context marker missing: "
            + marker,
        )

    require(
        "----- ChatBridge._autonomy_finished -----"
        not in context,
        "Large irrelevant autonomy body leaked into focused context.",
    )

    require(
        len(context) <= 24000,
        "Focused context exceeded budget.",
    )


def synthetic_success_contract() -> None:
    nonce = uuid.uuid4().hex
    repo = RUNTIME / (
        "gg-selfdev-synthetic-repo."
        + nonce
    )
    request = RUNTIME / (
        "gg-selfdev-contract-request."
        + nonce
        + ".json"
    )
    proposal = RUNTIME / (
        "gg-selfdev-contract-proposal."
        + nonce
        + ".json"
    )
    task_id = "task-" + uuid.uuid4().hex
    task_root = RUNTIME / (
        "gg-selfdev-task."
        + task_id.removeprefix("task-")
    )

    old_gate = main._selfdev_foundation_gate
    old_regression = main._selfdev_run_regression

    try:
        target = (
            repo
            / "projects"
            / "gg-ai-desktop"
            / "main.py"
        )

        target.parent.mkdir(
            parents=True,
            mode=0o700,
        )

        target.write_bytes(
            Path(main.__file__).read_bytes()
        )
        target.chmod(0o644)

        run_git(repo, "init", "-q")
        run_git(repo, "add", "--", ".")
        run_git(
            repo,
            "-c",
            "user.name=GG Selfdev Test",
            "-c",
            "user.email=gg-selfdev-test@localhost",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-q",
            "-m",
            "synthetic selfdev baseline",
        )

        head = run_git(
            repo,
            "rev-parse",
            "HEAD",
        )

        target_sha = main._selfdev_sha256(
            target.read_bytes()
        )

        request_payload = (
            main._selfdev_validate_request(
                {
                    "schema":
                        "gg.workbench.selfdev-request.v1",
                    "task_id":
                        task_id,
                    "goal":
                        "Synthetic successful VERIFIED_CHANGESET.",
                    "base_head":
                        head,
                    "target_relative_path":
                        main.SELFDEV_TARGET_REPO_RELATIVE,
                    "target_sha256":
                        target_sha,
                }
            )
        )

        write_private(
            request,
            main._selfdev_canonical(
                request_payload
            ),
        )

        old_text = (
            '"""GG AI Desktop Workbench '
            'with local-only Chat Bridge."""'
        )
        new_text = (
            '"""GG AI Desktop Workbench '
            'with local-only Chat Bridge. """'
        )

        write_private(
            proposal,
            (
                json.dumps(
                    {
                        "action": "PATCH",
                        "summary": "Synthetic success path.",
                        "old_text": old_text,
                        "new_text": new_text,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8"),
        )

        main._selfdev_foundation_gate = (
            lambda candidate, task: "a" * 64
        )
        main._selfdev_run_regression = (
            lambda project: "SYNTHETIC_REGRESSION_PASS"
        )

        capture = io.StringIO()

        with contextlib.redirect_stdout(capture):
            rc = main._selfdev_controller(
                str(request),
                str(proposal),
                str(repo),
            )

        require(
            rc == 0,
            "Synthetic selfdev controller did not return 0.",
        )

        result_path = (
            task_root
            / "verified-result.json"
        )

        require(
            result_path.is_file(),
            "Synthetic verified-result missing.",
        )

        result = json.loads(
            result_path.read_text(
                encoding="utf-8"
            )
        )

        require(
            result["status"]
            == "WAITING_PERSISTENT_APPLY",
            "Synthetic result boundary mismatch.",
        )

        require(
            result["candidate_write_count"] == 1,
            "Synthetic successful patch count mismatch.",
        )

        require(
            result["model_call_count"] == 0,
            "Synthetic path unexpectedly used model.",
        )

        events = capture.getvalue()

        require(
            "VERIFIED_CHANGESET=PASS" in events,
            "Synthetic VERIFIED_CHANGESET receipt missing.",
        )

        require(
            "SELFDEV_STATUS=WAITING_PERSISTENT_APPLY"
            in events,
            "Synthetic persistent boundary receipt missing.",
        )

    finally:
        main._selfdev_foundation_gate = old_gate
        main._selfdev_run_regression = old_regression

        for path in (
            request,
            proposal,
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

        for path in (
            task_root,
            repo,
        ):
            if path.exists():
                shutil.rmtree(path)


def static_controller_contract() -> None:
    source = Path(
        main.__file__
    ).read_text(
        encoding="utf-8"
    )

    for marker in (
        "def _selfdev_should_retry(",
        '"MODEL_CALL_LIMIT_EXCEEDED"',
        '"PATCH_LIMIT_EXCEEDED"',
        '"DONE_WITHOUT_CHANGE"',
        '"FOUNDATION_GATE_NOT_PASS:"',
        '"REGRESSION_FAILED:"',
        "run_selfdev_semantic_prompt(",
        "SELFDEV_MAX_PROMPT_CHARS = 32000",
    ):
        require(
            marker in source,
            "Controller hardening marker missing: "
            + marker,
        )


def main_test() -> int:
    semantic_profile_contract()
    patch_contract()
    retry_matrix_contract()
    context_contract()
    static_controller_contract()
    synthetic_success_contract()

    print("SELFDEV_SEMANTIC_MULTILINE=PASS")
    print("SELFDEV_SEMANTIC_GRAMMAR_BOUNDED=PASS")
    print("SELFDEV_FRAMING_ADVERSARIAL=PASS")
    print("LEGACY_AUTONOMY_SEMANTICS=PRESERVED")
    print("SELFDEV_FAILURE_MATRIX=PASS")
    print("SELFDEV_SYNTHETIC_FAIL_CLOSED=PASS")
    print("SELFDEV_VERIFIED_CHANGESET_SUCCESS_PATH=PASS")
    print("MODEL_INFERENCE=NONE")
    print("NETWORK=NONE")
    print("SELFDEV_CONTROLLER_TEST=PASS")
    return 0


def test_post_patch_noop_completion() -> None:
    import main as application

    no_op = application.SelfdevBridgeError(
        "SHARED_SEMANTIC_TRANSPORT:"
        "AutonomyModelError:"
        "SELFDEV_SEMANTIC_CONTRACT:NO_OP"
    )

    expected = {
        "action": "DONE",
        "summary": (
            "Verifierad candidate-patch är färdig; "
            "modellen föreslog ingen ytterligare ändring."
        ),
        "old_text": "",
        "new_text": "",
    }

    actual = application._selfdev_post_patch_noop_completion(
        no_op,
        1,
        False,
    )

    if actual != expected:
        raise RuntimeError(
            "Post-patch NO_OP did not become implicit DONE."
        )

    if (
        application._selfdev_post_patch_noop_completion(
            no_op,
            0,
            False,
        )
        is not None
    ):
        raise RuntimeError(
            "Pre-patch NO_OP must remain retryable."
        )

    if (
        application._selfdev_post_patch_noop_completion(
            no_op,
            1,
            True,
        )
        is not None
    ):
        raise RuntimeError(
            "Synthetic mode must remain fail-closed."
        )

    other = application.SelfdevBridgeError(
        "SHARED_SEMANTIC_TRANSPORT:"
        "AutonomyModelError:"
        "SELFDEV_SEMANTIC_CONTRACT:OLD_FILLER"
    )

    if (
        application._selfdev_post_patch_noop_completion(
            other,
            1,
            False,
        )
        is not None
    ):
        raise RuntimeError(
            "Only exact post-patch NO_OP may complete."
        )

    print("POST_PATCH_NOOP_COMPLETION_TEST=PASS")
    print("PREPATCH_NOOP_RETRY_PRESERVED=PASS")
    print("SYNTHETIC_FAIL_CLOSED=PASS")
    print("OTHER_SEMANTIC_RETRY_PRESERVED=PASS")


if __name__ == "__main__":
    test_post_patch_noop_completion()
    raise SystemExit(main_test())
