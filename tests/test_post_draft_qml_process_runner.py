from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest import mock


PROJECT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(PROJECT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT),
    )


Runner = importlib.import_module(
    "backend.live_aid.post_draft_qml_process_runner"
)


SOURCE = (
    "import QtQuick\n"
    "Item {\n"
    "    implicitHeight: 93\n"
    "}\n"
)


def sha(
    source: str,
) -> str:
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def request() -> dict:
    return {
        "schema":
            Runner.REQUEST_SCHEMA,
        "request_id":
            "post-draft-"
            + "1" * 32,
        "object_id":
            "ws.file.context-composer",
        "source_name":
            "ContextComposer.qml",
        "source_relative_path":
            "qml/components/"
            "ContextComposer.qml",
        "language":
            "qml",
        "source":
            SOURCE,
        "source_sha256":
            sha(SOURCE),
        "max_repair_attempts":
            1,
        "model_dispatch_budget":
            1,
        "persistent_write_authority":
            "NONE",
        "execution_authority":
            "NONE",
        "network_authority":
            "NONE",
    }


class FakeExecutor:
    def __init__(
        self,
        *,
        event_sink,
        **_kwargs,
    ):
        self.event_sink = (
            event_sink
        )

    def run_complete_draft(
        self,
        source: str,
    ):
        source_sha = sha(
            source
        )

        self.event_sink(
            {
                "sequence": 1,
                "event":
                    "DRAFT_COMPLETE",
                "driver_state":
                    "VALIDATING",
                "source_sha256":
                    source_sha,
                "repair_attempts": 0,
                "model_dispatch_count": 0,
            }
        )

        self.event_sink(
            {
                "sequence": 2,
                "event":
                    "READY_TO_RUN",
                "driver_state":
                    "READY_TO_RUN",
                "source_sha256":
                    source_sha,
                "repair_attempts": 0,
                "model_dispatch_count": 0,
            }
        )

        return SimpleNamespace(
            state="READY_TO_RUN",
            source=source,
            source_sha256=source_sha,
            repair_attempts=0,
            model_dispatch_count=0,
            execution_ready=True,
            blocked_fault_layer="",
            blocked_reason="",
            model_evidence_paths=(),
        )


class PostDraftProcessRunnerTests(
    unittest.TestCase
):
    def test_request_contract_is_source_bound(self):
        value = (
            Runner.validate_request(
                request()
            )
        )

        self.assertEqual(
            value["source_sha256"],
            sha(SOURCE),
        )

        self.assertEqual(
            value[
                "persistent_write_authority"
            ],
            "NONE",
        )


    def test_stale_source_sha_is_rejected(self):
        value = request()

        value["source_sha256"] = (
            "0" * 64
        )

        with self.assertRaises(
            Runner.ProcessRunnerError
        ):
            Runner.validate_request(
                value
            )


    def test_run_request_streams_real_state_envelopes(self):
        events = []

        with mock.patch.object(
            Runner.executor_module,
            "PostDraftQmlExecutor",
            FakeExecutor,
        ):
            response = (
                Runner.run_request(
                    request(),
                    event_writer=
                        events.append,
                )
            )

        self.assertEqual(
            len(events),
            2,
        )

        for event in events:
            Runner.validate_event(
                event,
                expected_request_id=
                    request()["request_id"],
                expected_object_id=
                    request()["object_id"],
                expected_initial_source_sha256=
                    request()[
                        "source_sha256"
                    ],
            )

        self.assertEqual(
            events[0]["event"][
                "event"
            ],
            "DRAFT_COMPLETE",
        )

        self.assertEqual(
            events[-1]["event"][
                "event"
            ],
            "READY_TO_RUN",
        )

        validated = (
            Runner.validate_response(
                response,
                expected_request_id=
                    request()["request_id"],
                expected_object_id=
                    request()["object_id"],
                expected_initial_source_sha256=
                    request()[
                        "source_sha256"
                    ],
            )
        )

        self.assertTrue(
            validated[
                "execution_ready"
            ]
        )


    def test_response_never_grants_action_authority(self):
        with mock.patch.object(
            Runner.executor_module,
            "PostDraftQmlExecutor",
            FakeExecutor,
        ):
            response = (
                Runner.run_request(
                    request(),
                    event_writer=
                        lambda _event: None,
                )
            )

        self.assertEqual(
            response[
                "persistent_write_authority"
            ],
            "NONE",
        )

        self.assertEqual(
            response[
                "execution_authority"
            ],
            "NONE",
        )

        self.assertEqual(
            response[
                "network_authority"
            ],
            "NONE",
        )


    def test_workbench_wireup_markers_preserve_manual_stage_d(self):
        main = (
            PROJECT / "main.py"
        ).read_text(
            encoding="utf-8"
        )

        workspace = (
            PROJECT
            / "qml"
            / "components"
            / "WorkspaceSurface.qml"
        ).read_text(
            encoding="utf-8"
        )

        live_aid_chat = (
            PROJECT
            / "qml"
            / "components"
            / "ChatLiveAidWork.qml"
        ).read_text(
            encoding="utf-8"
        )

        for marker in (
            "postDraftEvent = Signal(str, str)",
            "postDraftReady = Signal(str, str)",
            "postDraftFailed = Signal(str, str)",
            "def runPostDraftRepair(",
        ):
            self.assertIn(
                marker,
                main,
            )

        compact_main = "".join(
            main.split()
        )

        for marker in (
            "post_draft_qml_process_runner.validate_request(",
            "post_draft_qml_process_runner.validate_response(",
        ):
            self.assertIn(
                marker,
                compact_main,
            )

        # State and backend routing remain owned by Workspace.
        for marker in (
            'property string postDraftState: "IDLE"',
            "function requestPostDraftAutomaticRepair()",
            "function onPostDraftEvent(",
            "function onPostDraftReady(",
            "function onPostDraftFailed(",
            "function requestLiveAidPreflight()",
            "function requestLiveAidRepair()",
            "function requestApplyRepair()",
            "root.liveAidBackend.applyRepair(",
        ):
            self.assertIn(
                marker,
                workspace,
            )

        # Presentation and controls now live in contextual Chat work.
        for marker in (
            'objectName: "workspacePostDraftAutoRepairButton"',
            'objectName: "workspacePreflightButton"',
            'objectName: "workspaceRepairButton"',
            'objectName: "workspaceApplyRepairButton"',
            "APPLY PROPOSAL · BUFFER ONLY",
        ):
            self.assertIn(
                marker,
                live_aid_chat,
            )
            self.assertNotIn(
                marker,
                workspace,
            )


class PostDraftEvidenceRetentionTests(unittest.TestCase):
    def test_workbench_retains_validated_post_draft_evidence(self):
        pathlib = __import__(
            "pathlib"
        )

        main_py = (
            pathlib.Path(
                __file__
            ).resolve().parents[1]
            / "main.py"
        ).read_text(
            encoding="utf-8"
        )

        required = (
            "gg.workbench.post-draft-evidence.v2",
            "gg-live-aid-post-draft-evidence.",
            "Post-draft event transcript is unavailable.",
            '"events":',
            "events.append(",
            "_persist_post_draft_evidence(",
            "REMOVE_AFTER_EVIDENCE_PROMOTION",
            "workbench_evidence_path",
            "workbench_evidence_sha256",
            "POST_DRAFT_EVIDENCE:",
        )

        for marker in required:
            self.assertIn(
                marker,
                main_py,
            )

        self.assertIn(
            "if evidence_path:",
            main_py,
        )

        self.assertIn(
            "shutil.rmtree(",
            main_py,
        )


    def test_persistent_evidence_excludes_raw_candidate_source(self):
        hashlib_module = __import__(
            "hashlib"
        )
        importlib_module = __import__(
            "importlib"
        )
        json_module = __import__(
            "json"
        )
        os_module = __import__(
            "os"
        )
        pathlib_module = __import__(
            "pathlib"
        )
        shutil_module = __import__(
            "shutil"
        )
        sys_module = __import__(
            "sys"
        )
        uuid_module = __import__(
            "uuid"
        )

        project = (
            pathlib_module.Path(
                __file__
            ).resolve().parents[1]
        )

        sys_module.path.insert(
            0,
            str(project),
        )

        main_module = (
            importlib_module
            .import_module(
                "main"
            )
        )

        runtime = pathlib_module.Path(
            f"/run/user/{os_module.getuid()}"
        ).resolve(
            strict=True
        )

        suffix = uuid_module.uuid4().hex

        scratch = runtime / (
            "gg-live-aid-post-draft-ui."
            + suffix
        )

        scratch.mkdir(
            mode=0o700
        )

        raw_source = (
            "import QtQuick\n"
            "Item {\n"
            "    implicitHeight: 48;\n"
            "}\n"
        )

        raw_sha = (
            hashlib_module
            .sha256(
                raw_source.encode(
                    "utf-8"
                )
            )
            .hexdigest()
        )

        state = {
            "run_dir":
                str(scratch),
            "request_id":
                "post-draft-" + suffix,
            "object_id":
                "ws.file.context-composer",
            "source_sha256":
                "1" * 64,
            "events": [
                {
                    "event":
                        "PREFLIGHT_RESPONSE",
                    "gate_status":
                        "FAIL",
                    "gate_report_sha256":
                        "2" * 64,
                    "source_sha256":
                        "1" * 64,
                },
                {
                    "event":
                        "PREFLIGHT_RESPONSE",
                    "gate_status":
                        "PASS",
                    "gate_report_sha256":
                        "3" * 64,
                    "source_sha256":
                        raw_sha,
                },
            ],
        }

        result = {
            "state":
                "READY_TO_RUN",
            "source":
                raw_source,
            "source_sha256":
                raw_sha,
            "model_dispatch_count":
                1,
            "model_evidence_paths": [
                "/run/user/1000/"
                "gg-wb3d-model-runner.synthetic"
            ],
            "persistent_write_authority":
                "NONE",
            "execution_authority":
                "NONE",
            "network_authority":
                "NONE",
        }

        evidence_dir = runtime / (
            "gg-live-aid-post-draft-evidence."
            + suffix
        )

        try:
            (
                evidence_raw,
                evidence_sha,
            ) = (
                main_module
                .LiveAidQtBridge
                ._persist_post_draft_evidence(
                    object(),
                    state=state,
                    result=result,
                    exit_code=0,
                    exit_status=(
                        main_module
                        .QProcess
                        .ExitStatus
                        .NormalExit
                    ),
                    stderr="",
                    protocol_error="",
                )
            )

            evidence_path = (
                pathlib_module.Path(
                    evidence_raw
                )
            )

            payload = (
                evidence_path
                .read_bytes()
            )

            self.assertEqual(
                hashlib_module
                .sha256(
                    payload
                )
                .hexdigest(),
                evidence_sha,
            )

            record = (
                json_module.loads(
                    payload.decode(
                        "utf-8"
                    )
                )
            )

            self.assertEqual(
                record["schema"],
                "gg.workbench.post-draft-evidence.v2",
            )

            self.assertIs(
                record[
                    "raw_source_persisted"
                ],
                False,
            )

            persisted_result = (
                record["result"]
            )

            self.assertNotIn(
                "source",
                persisted_result,
            )

            self.assertEqual(
                persisted_result[
                    "source_sha256"
                ],
                raw_sha,
            )

            self.assertEqual(
                persisted_result[
                    "model_evidence_paths"
                ],
                result[
                    "model_evidence_paths"
                ],
            )

            self.assertEqual(
                [
                    item[
                        "gate_status"
                    ]
                    for item
                    in record["events"]
                ],
                [
                    "FAIL",
                    "PASS",
                ],
            )

            self.assertEqual(
                [
                    item[
                        "gate_report_sha256"
                    ]
                    for item
                    in record["events"]
                ],
                [
                    "2" * 64,
                    "3" * 64,
                ],
            )

            self.assertIn(
                "source",
                result,
            )

            self.assertEqual(
                result["source"],
                raw_source,
            )

        finally:
            shutil_module.rmtree(
                evidence_dir,
                ignore_errors=True,
            )

            shutil_module.rmtree(
                scratch,
                ignore_errors=True,
            )


if __name__ == "__main__":
    unittest.main()
