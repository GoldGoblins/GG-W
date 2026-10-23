from __future__ import annotations
import importlib
import tempfile
import unittest
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

AuthoringSession = importlib.import_module(
    "live_aid.authoring_session"
).AuthoringSession
_contract = importlib.import_module("live_aid.contract")
Fact = _contract.Fact
Status = _contract.Status
DiagnosticEngine = importlib.import_module(
    "live_aid.diagnostic_engine"
).DiagnosticEngine
FactStore = importlib.import_module("live_aid.fact_store").FactStore
_forensic_resolver = importlib.import_module("live_aid.forensic_resolver")
ForensicResolver = _forensic_resolver.ForensicResolver
ProbeRequest = _forensic_resolver.ProbeRequest
preflight = importlib.import_module("live_aid.preflight").preflight
SourceIndex = importlib.import_module("live_aid.source_index").SourceIndex
_adapters = importlib.import_module("live_aid.adapters")
safe_tool_request = _adapters.safe_tool_request
validate_safe_tool_response = _adapters.validate_safe_tool_response
propose_learning = importlib.import_module(
    "live_aid.learning"
).propose_learning
LiveAidFeedbackLoop = importlib.import_module(
    "live_aid.feedback_loop"
).LiveAidFeedbackLoop
LiveAidService = importlib.import_module("live_aid.bridge").LiveAidService
QmlPreflightRunner = importlib.import_module(
    "live_aid.qml_preflight_runner"
)
RepairModelRunner = importlib.import_module(
    "live_aid.repair_model_runner"
)

class LiveAidTests(unittest.TestCase):
    def source_tree(self, root: Path) -> None:
        (root / "main.py").write_text(
            "def existing(path):\n    return path\nVALUE = 1\n",
            encoding="utf-8",
        )
        (root / "helper.py").write_text("ANSWER = 42\n", encoding="utf-8")

    def test_incomplete_does_not_block_authoring(self):
        engine = DiagnosticEngine()
        session = AuthoringSession(source_name="draft.py", engine=engine)
        snap = session.update("def f(")
        self.assertEqual(snap.status, Status.INCOMPLETE)
        self.assertFalse(any(d.blocking for d in snap.diagnostics))

    def test_python_syntax_fail(self):
        engine = DiagnosticEngine()
        snap = AuthoringSession(source_name="draft.py", engine=engine).update("x = )")
        self.assertEqual(snap.status, Status.FAIL)
        self.assertTrue(any(d.code == "PY_SYNTAX" for d in snap.diagnostics))

    def test_verified_missing_module_attribute_is_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.source_tree(root)
            index = SourceIndex.build(root)
            engine = DiagnosticEngine(index)
            source = "import main\nx = main.not_here(1)\n"
            diags = engine.analyze(source, "draft.py")
            self.assertTrue(any(d.code == "PY_MODULE_ATTRIBUTE_MISSING" and d.status == Status.FAIL for d in diags))

    def test_verified_existing_module_attribute_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.source_tree(root)
            index = SourceIndex.build(root)
            engine = DiagnosticEngine(index)
            source = "import main\nx = main.existing(1)\n"
            diags = engine.analyze(source, "draft.py")
            self.assertTrue(any(d.code == "PY_MODULE_ATTRIBUTE_VERIFIED" for d in diags))
            self.assertFalse(any(d.code == "PY_MODULE_ATTRIBUTE_MISSING" for d in diags))

    def test_unknown_symbol_creates_green_search_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.source_tree(root)
            index = SourceIndex.build(root)
            engine = DiagnosticEngine(index)
            resolver = ForensicResolver(index)
            session = AuthoringSession(source_name="draft.py", engine=engine, resolver=resolver)
            snap = session.update("x = mysterious_name\n")
            self.assertTrue(any(p.profile == "SEARCH" for p in snap.probes))

    def test_fact_store_is_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FactStore(Path(tmp))
            fact = Fact(
                key="x", value=1, epistemic_class="OBSERVED",
                source_kind="TEST", source_id="fixture",
                source_sha256="a" * 64, scope="TEST",
            )
            one = store.append(fact)
            two = store.append(fact)
            self.assertEqual(one, two)
            self.assertEqual(len(store.find("x")), 1)

    def test_preflight_unknown_not_pass(self):
        engine = DiagnosticEngine()
        result = preflight(engine, "x = external_name\n", "draft.py")
        self.assertEqual(result.status, Status.UNKNOWN)

    def test_safe_tool_request_is_typed(self):
        probe = ProbeRequest("SAFE_TOOL_SEARCH", "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1", "SEARCH", {"literal":"thing"}, "reason")
        req = safe_tool_request(probe, "tool-" + ("a" * 32))
        self.assertEqual(req["profile"], "SEARCH")
        self.assertEqual(set(req), {"schema","request_id","profile","arguments"})

    def test_safe_tool_response_rejects_write_authority(self):
        value = {
            "schema":"gg.workbench.safe-tool-response.v1",
            "request_id":"tool-" + ("a"*32),
            "status":"PASS",
            "profile":"SEARCH",
            "output":"",
            "evidence":{
                "authority":"GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
                "effect_class":"READ_ONLY",
                "network_authority":"NONE",
                "persistent_write_authority":"YELLOW",
                "backend":"IN_PROCESS_TRACKED_LITERAL_SEARCH",
                "output_sha256":"b"*64,
            },
        }
        with self.assertRaises(ValueError):
            validate_safe_tool_response(value, request_id=value["request_id"], profile="SEARCH")

    def test_learning_never_promotes_itself(self):
        fact = Fact(
            key="x", value=1, epistemic_class="OBSERVED",
            source_kind="TEST", source_id="fixture",
            source_sha256="a"*64, scope="TEST",
        )
        proposal = propose_learning(
            claim_key="lesson.x",
            statement="x is observed in this fixture",
            facts=[fact],
            limitation="fixture only",
        )
        self.assertEqual(proposal.status, "PROPOSAL_ONLY")
        self.assertEqual(proposal.promotion_authority, "NONE")



    def test_invalid_json_cannot_preflight_pass(self):
        engine = DiagnosticEngine()
        result = preflight(engine, '{"x":', "draft.json")
        self.assertNotEqual(result.status, Status.PASS)
        self.assertEqual(
            result.reason,
            "AUTHORING_WARNING_REQUIRES_RESOLUTION",
        )

    def test_read_only_bridge_detects_current_source_missing_symbol(self):
        repo = PROJECT.parents[1]
        service = LiveAidService(repo)
        result = service.analyze(
            object_id="ws.test.live-aid",
            source_name="probe.py",
            source="import main\nx = main._sha256_file(path)\n",
            language="python",
        )
        self.assertEqual(result["action_authority"], "NONE")
        self.assertEqual(result["network_authority"], "NONE")
        self.assertEqual(result["draft_blocking"], False)
        self.assertTrue(
            any(
                item["code"] == "PY_MODULE_ATTRIBUTE_MISSING"
                and item["status"] == "FAIL"
                for item in result["diagnostics"]
            )
        )

    def test_feedback_loop_does_not_request_repair_for_incomplete(self):
        engine = DiagnosticEngine()
        session = AuthoringSession(source_name="draft.py", engine=engine)
        cycle = LiveAidFeedbackLoop(session).cycle("def f(")
        self.assertEqual(cycle.snapshot.status, Status.INCOMPLETE)
        self.assertIsNone(cycle.repair_request)
        self.assertFalse(cycle.execution_ready)

    def test_feedback_loop_requests_repair_for_proven_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.source_tree(root)
            index = SourceIndex.build(root)
            session = AuthoringSession(
                source_name="draft.py",
                engine=DiagnosticEngine(index),
                resolver=ForensicResolver(index),
            )
            cycle = LiveAidFeedbackLoop(session).cycle(
                "import main\nx = main.missing(1)\n"
            )
            self.assertEqual(cycle.snapshot.status, Status.FAIL)
            self.assertIsNotNone(cycle.repair_request)
            self.assertFalse(cycle.execution_ready)

    def test_qml_gate_preflight_is_profile_bound_and_no_authority(self):
        source = "import QtQuick\nItem {}\n"
        source_sha = importlib.import_module(
            "hashlib"
        ).sha256(source.encode("utf-8")).hexdigest()

        request = QmlPreflightRunner.validate_request(
            {
                "schema": QmlPreflightRunner.REQUEST_SCHEMA,
                "request_id": "preflight-" + ("a" * 32),
                "object_id": "ws.file.context-composer",
                "source_name": "ContextComposer.qml",
                "source_relative_path":
                    "qml/components/ContextComposer.qml",
                "language": "qml",
                "source": source,
                "source_sha256": source_sha,
            }
        )

        report = {
            "schema": "gg-code-gate-report-v1",
            "status": "PASS",
            "source": {"sha256": source_sha},
            "qml": {
                "success": True,
                "diagnostics": [],
            },
        }

        response = (
            QmlPreflightRunner
            .build_response_from_gate_report(
                request,
                report,
                gate_report_path="/synthetic/report.json",
                gate_report_sha256="b" * 64,
                wrapper_return_code=0,
            )
        )

        validated = QmlPreflightRunner.validate_response(
            response,
            expected_request_id=request["request_id"],
            expected_object_id=request["object_id"],
            expected_source_sha256=source_sha,
        )

        self.assertEqual(validated["status"], "PASS")
        self.assertTrue(validated["profile_bound_pass"])
        self.assertTrue(
            validated["gate_pass_is_profile_bound_only"]
        )
        self.assertTrue(validated["human_trigger_required"])
        self.assertFalse(
            validated["persistent_source_write"]
        )
        self.assertEqual(
            validated["action_authority"],
            "NONE",
        )
        self.assertEqual(
            validated["execution_authority"],
            "NONE",
        )
        self.assertEqual(
            validated["network_authority"],
            "NONE",
        )

        failed_report = {
            "schema": "gg-code-gate-report-v1",
            "status": "FAIL",
            "source": {"sha256": source_sha},
            "qml": {
                "success": False,
                "diagnostics": [
                    {
                        "id": "synthetic-qml-error",
                        "message": "synthetic failure",
                        "line": 4,
                    }
                ],
            },
        }

        failed = (
            QmlPreflightRunner
            .build_response_from_gate_report(
                request,
                failed_report,
                gate_report_path="/synthetic/report.json",
                gate_report_sha256="c" * 64,
                wrapper_return_code=1,
            )
        )

        self.assertEqual(failed["status"], "FAIL")
        self.assertFalse(failed["profile_bound_pass"])
        self.assertEqual(
            failed["diagnostics"][0]["status"],
            "FAIL",
        )
        self.assertTrue(
            failed["diagnostics"][0]["blocking"]
        )



    def test_repair_proposal_is_untrusted_and_buffer_bound(self):
        source = (
            "import QtQuick\n"
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        source_sha = importlib.import_module(
            "hashlib"
        ).sha256(
            source.encode("utf-8")
        ).hexdigest()

        request = RepairModelRunner.validate_request(
            {
                "schema":
                    RepairModelRunner.REQUEST_SCHEMA,
                "request_id":
                    "repair-model-" + ("a" * 32),
                "object_id":
                    "ws.file.context-composer",
                "source_name":
                    "ContextComposer.qml",
                "language":
                    "qml",
                "source":
                    source,
                "source_sha256":
                    source_sha,
                "preflight_report_sha256":
                    "b" * 64,
                "diagnostics": [
                    {
                        "status": "FAIL",
                        "code": "qml-syntax",
                        "message":
                            "synthetic syntax failure",
                        "line": 3,
                        "blocking": True,
                        "suggestion":
                            "repair the invalid value",
                    }
                ],
            }
        )

        proposal = {
            "schema":
                RepairModelRunner
                .semantic_transport
                .contract
                .SEMANTIC_PROPOSAL_SCHEMA,
            "hypothesis":
                "invalid property value",
            "old_text":
                "implicitHeight: ???",
            "new_text":
                "implicitHeight: 93",
            "why":
                "restore a valid numeric expression",
        }

        response = RepairModelRunner.build_response(
            request,
            proposal,
            model_evidence_path=
                "/run/user/1000/synthetic-model-evidence",
            model_response_sha256="c" * 64,
        )

        validated = RepairModelRunner.validate_response(
            response,
            expected_request_id=
                request["request_id"],
            expected_object_id=
                request["object_id"],
            expected_source_sha256=
                source_sha,
        )

        self.assertEqual(
            validated["status"],
            "PROPOSAL",
        )

        self.assertEqual(
            validated["model_output_authority"],
            "UNTRUSTED_MODEL_OUTPUT",
        )

        self.assertEqual(
            validated["apply_authority"],
            "HUMAN_EXPLICIT_IN_MEMORY_ONLY",
        )

        self.assertEqual(
            validated["persistent_write_authority"],
            "NONE",
        )

        self.assertEqual(
            validated["execution_authority"],
            "NONE",
        )

        self.assertEqual(
            validated["network_authority"],
            "NONE",
        )

        self.assertTrue(
            validated[
                "preflight_required_after_apply"
            ]
        )

        self.assertIn(
            "implicitHeight: 93",
            validated["candidate_source"],
        )

        self.assertEqual(
            source,
            request["source"],
        )



    def test_repair_grammar_binds_old_to_attested_diagnostic_line(self):
        source = (
            "import QtQuick\n"
            "Item {\n"
            "    implicitHeight: ???\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        source_sha = importlib.import_module(
            "hashlib"
        ).sha256(
            source.encode("utf-8")
        ).hexdigest()

        request = RepairModelRunner.validate_request(
            {
                "schema":
                    RepairModelRunner.REQUEST_SCHEMA,
                "request_id":
                    "repair-model-" + ("d" * 32),
                "object_id":
                    "ws.file.context-composer",
                "source_name":
                    "ContextComposer.qml",
                "language":
                    "qml",
                "source":
                    source,
                "source_sha256":
                    source_sha,
                "preflight_report_sha256":
                    "e" * 64,
                "diagnostics": [
                    {
                        "status": "FAIL",
                        "code": "syntax",
                        "message":
                            "Expected token `;'",
                        "line": 4,
                        "blocking": True,
                        "suggestion":
                            "repair attested line",
                    }
                ],
            }
        )

        grammar = (
            RepairModelRunner
            .build_repair_grammar(
                request
            )
        )

        expected_lines = [
            (
                'root ::= "HYPOTHESIS:" reason '
                '"|OLD:" old '
                '"|NEW:" replacement '
                '"|WHY:" reason '
                '"|GG_MODEL_RUNNER_OK"'
            ),
            "reason ::= reason-char{1,160}",
            (
                "reason-char ::= "
                "[A-Za-z0-9 _.,:;!?()+/@#%-]"
            ),
            'old ::= "implicitHeight: ???"',
            "replacement ::= replacement-char{1,240}",
            r"replacement-char ::= [^|\r\n]",
        ]

        self.assertEqual(
            grammar.splitlines(),
            expected_lines,
        )

        self.assertEqual(
            grammar.count("\n"),
            len(expected_lines),
        )

        self.assertTrue(
            grammar.endswith("\n")
        )

        self.assertIn(
            "\nreason ::=",
            grammar,
        )

        self.assertNotIn(
            r"\nreason ::=",
            grammar,
        )

        proposal = {
            "schema":
                RepairModelRunner
                .semantic_transport
                .contract
                .SEMANTIC_PROPOSAL_SCHEMA,
            "hypothesis":
                "invalid expression",
            "old_text":
                "implicitHeight: ???",
            "new_text":
                "implicitHeight: 93",
            "why":
                "use valid QML expression",
        }

        response = RepairModelRunner.build_response(
            request,
            proposal,
            model_evidence_path=
                "/run/user/1000/synthetic-model-evidence",
            model_response_sha256="f" * 64,
        )

        candidate_lines = (
            response["candidate_source"]
            .splitlines()
        )

        self.assertEqual(
            candidate_lines[2].strip(),
            "implicitHeight: ???",
        )

        self.assertEqual(
            candidate_lines[3].strip(),
            "implicitHeight: 93",
        )




    def test_repair_grammar_fields_are_bounded(self):
        source = (
            "import QtQuick\n"
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        source_sha = importlib.import_module(
            "hashlib"
        ).sha256(
            source.encode("utf-8")
        ).hexdigest()

        request = RepairModelRunner.validate_request(
            {
                "schema":
                    RepairModelRunner.REQUEST_SCHEMA,
                "request_id":
                    "repair-model-" + ("e" * 32),
                "object_id":
                    "ws.file.context-composer",
                "source_name":
                    "ContextComposer.qml",
                "language":
                    "qml",
                "source":
                    source,
                "source_sha256":
                    source_sha,
                "preflight_report_sha256":
                    "a" * 64,
                "diagnostics": [
                    {
                        "status": "FAIL",
                        "code": "syntax",
                        "message":
                            "Expected token `;'",
                        "line": 3,
                        "blocking": True,
                        "suggestion":
                            "repair attested line",
                    }
                ],
            }
        )

        grammar = (
            RepairModelRunner
            .build_repair_grammar(
                request
            )
        )

        self.assertIn(
            "reason ::= reason-char{1,160}",
            grammar,
        )

        self.assertIn(
            "replacement ::= replacement-char{1,240}",
            grammar,
        )

        self.assertNotIn(
            "reason ::= reason-char+",
            grammar,
        )

        self.assertNotIn(
            "replacement ::= replacement-char+",
            grammar,
        )


    def test_repair_stdout_parser_extracts_single_semantic_candidate(self):
        candidate = (
            "HYPOTHESIS:invalid expression"
            "|OLD:implicitHeight: ???"
            "|NEW:implicitHeight: 93"
            "|WHY:restore numeric expression"
            "|GG_MODEL_RUNNER_OK"
        )

        payload = (
            "\nLoading model...\n"
            "diagnostic prefix\n"
            + candidate
            + "\n[ Prompt: synthetic ]\n"
            "Exiting...\n"
        ).encode(
            "utf-8"
        )

        parsed = (
            RepairModelRunner
            ._parse_repair_model_stdout(
                payload
            )
        )

        self.assertEqual(
            parsed,
            candidate,
        )

        proposal = (
            RepairModelRunner
            .semantic_transport
            .parse_semantic_text(
                parsed
            )
        )

        self.assertEqual(
            proposal["old_text"],
            "implicitHeight: ???",
        )

        self.assertEqual(
            proposal["new_text"],
            "implicitHeight: 93",
        )


    def test_repair_stdout_parser_rejects_incomplete_output(self):
        payload = (
            "Loading model...\n"
            "HYPOTHESIS:invalid expression"
        ).encode(
            "utf-8"
        )

        stop_type = (
            RepairModelRunner
            .semantic_transport
            .base
            .RunnerStop
        )

        with self.assertRaises(
            stop_type
        ):
            RepairModelRunner._parse_repair_model_stdout(
                payload
            )


    def test_repair_stdout_parser_rejects_ambiguous_output(self):
        first = (
            "HYPOTHESIS:first"
            "|OLD:implicitHeight: ???"
            "|NEW:implicitHeight: 93"
            "|WHY:first repair"
            "|GG_MODEL_RUNNER_OK"
        )

        second = (
            "HYPOTHESIS:second"
            "|OLD:implicitHeight: ???"
            "|NEW:implicitHeight: 94"
            "|WHY:second repair"
            "|GG_MODEL_RUNNER_OK"
        )

        payload = (
            first
            + "\n"
            + second
        ).encode(
            "utf-8"
        )

        stop_type = (
            RepairModelRunner
            .semantic_transport
            .base
            .RunnerStop
        )

        with self.assertRaises(
            stop_type
        ):
            RepairModelRunner._parse_repair_model_stdout(
                payload
            )

    def test_repair_target_selects_earliest_attested_blocking_line(self):
        source = (
            "import QtQuick\n"
            "Item {\n"
            "    implicitHeight: ??\n"
            "    implicitWidth: 720\n"
            "}\n"
        )

        source_sha = importlib.import_module(
            "hashlib"
        ).sha256(
            source.encode("utf-8")
        ).hexdigest()

        request = RepairModelRunner.validate_request(
            {
                "schema":
                    RepairModelRunner.REQUEST_SCHEMA,
                "request_id":
                    "repair-model-" + ("1" * 32),
                "object_id":
                    "ws.file.context-composer",
                "source_name":
                    "ContextComposer.qml",
                "language":
                    "qml",
                "source":
                    source,
                "source_sha256":
                    source_sha,
                "preflight_report_sha256":
                    "2" * 64,
                "diagnostics": [
                    {
                        "status": "FAIL",
                        "code": "syntax",
                        "message":
                            "Expected token `;'",
                        "line": 4,
                        "blocking": True,
                        "suggestion":
                            "repair parser recovery diagnostic",
                    },
                    {
                        "status": "FAIL",
                        "code": "syntax",
                        "message":
                            "Unexpected token `??'",
                        "line": 3,
                        "blocking": True,
                        "suggestion":
                            "repair primary syntax diagnostic",
                    },
                ],
            }
        )

        self.assertEqual(
            RepairModelRunner._repair_target(
                request
            ),
            (
                3,
                "implicitHeight: ??",
            ),
        )

        grammar = (
            RepairModelRunner
            .build_repair_grammar(
                request
            )
        )

        self.assertIn(
            'old ::= "implicitHeight: ??"',
            grammar,
        )


    def test_repair_target_still_rejects_no_blocking_line(self):
        source = (
            "import QtQuick\\n"
            "Item {\\n"
            "    implicitHeight: 93\\n"
            "}\\n"
        )

        source_sha = importlib.import_module(
            "hashlib"
        ).sha256(
            source.encode("utf-8")
        ).hexdigest()

        with self.assertRaisesRegex(
            RepairModelRunner.RepairModelError,
            "^NO_PROVEN_BLOCKING_FAIL$",
        ):
            RepairModelRunner.validate_request(
                {
                    "schema":
                        RepairModelRunner.REQUEST_SCHEMA,
                    "request_id":
                        "repair-model-" + ("3" * 32),
                    "object_id":
                        "ws.file.context-composer",
                    "source_name":
                        "ContextComposer.qml",
                    "language":
                        "qml",
                    "source":
                        source,
                    "source_sha256":
                        source_sha,
                    "preflight_report_sha256":
                        "4" * 64,
                    "diagnostics": [
                        {
                            "status": "FAIL",
                            "code": "syntax",
                            "message":
                                "non-blocking synthetic finding",
                            "line": 3,
                            "blocking": False,
                            "suggestion":
                                "none",
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
