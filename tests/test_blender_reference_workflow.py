#!/usr/bin/env python3
"""State/evidence regressions; mock renders are not artistic quality tests."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import blender_reference_workflow as workflow

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6n0cAAAAASUVORK5CYII=")


class BlenderStub:
    def __init__(self):
        self.current = "mesh-v1"
        self.failed_capture = False

    def __call__(self, operation, payload):
        if operation == "setup":
            return {"scene": "isolated", "collection": "own-geometry"}
        if operation == "fingerprint":
            return {"fingerprint": self.current}
        directory = Path(payload["directory"])
        directory.mkdir(parents=True)
        if operation == "capture":
            if self.failed_capture:
                raise RuntimeError("Simulated render failure after creating directory")
            views = {}
            for style in ("clay", "silhouette", "appearance"):
                views[style] = {}
                for view in workflow.VIEWS:
                    path = directory / (style + "-" + view + ".png")
                    path.write_bytes(PNG)
                    views[style][view] = {"path": str(path)}
            checkpoint = directory / "model.blend"
            checkpoint.write_text(self.current)
            report = directory / "mesh-report.json"
            report.write_text(json.dumps({"verts": 8, "boundary_edges": 0}))
            return {"framing": {"center": [0, 0, 0], "distance": 4, "ortho_scale": 3},
                    "views": views, "mesh_reports": {"summary": {"boundary_edges": 0}, "path": str(report)},
                    "fingerprint": self.current, "checkpoint": str(checkpoint)}
        if operation == "export":
            if self.current != payload["expected"]:
                raise ValueError("Changed model")
            paths = {}
            for kind in ("blend", "glb"):
                path = directory / ("model." + kind)
                path.write_text(self.current)
                paths[kind] = str(path)
            return paths
        raise AssertionError(operation)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / "reference.png"
        self.image.write_bytes(PNG)
        self.blender = BlenderStub()
        self.job = self.call("create", {"brief": "Reference-based calibration sculpture", "criteria": ["silhouette", "materials"]})["job"]

    def call(self, operation, payload=None):
        return workflow.execute(operation, {"job": getattr(self, "job", ""), **(payload or {})},
                                root=self.root, blender=self.blender)

    def refs(self):
        return self.call("references", {"views": {view: {"path": str(self.image), "source": "synthetic-test", "inferred": False}
                                                   for view in workflow.VIEWS},
                                        "consistency_review": "Known synthetic fixtures; not an artistic evaluation"})

    def capture(self):
        self.refs()
        self.call("setup")
        return self.call("capture", {"changes": "Initial blockout"})

    def review_payload(self, state, verdict="PASS"):
        return {"viewed": list(state["captures"][-1]["images"]),
                "comparisons": {view: {criterion: "Mock comparison for evidence-gate regression"
                                       for criterion in state["criteria"]} for view in workflow.VIEWS},
                "technical_review": "Mock boundary measurement for state regression",
                "verdict": verdict, "issues": [] if verdict == "PASS" else [
                    {"view": "side", "severity": "major", "observation": "Depth differs",
                     "change": "Correct affected mesh region depth"}]}

    def test_input_image_is_preserved_and_model_is_unknown(self):
        state = self.call("create", {"brief": "Infer the shape from this supplied image", "image": str(self.image)})
        self.assertEqual(Path(state["input"]["path"]).read_bytes(), PNG)
        self.assertEqual(state["requested_image_model"], "gpt-image-2.5-sunburst")
        self.assertIsNone(state["reported_image_model"])

    def test_setup_needs_consistent_complete_references(self):
        with self.assertRaises(ValueError):
            self.call("setup")
        with self.assertRaises(ValueError):
            self.call("references", {"views": {}, "consistency_review": "No complete reference pack"})
        state = self.refs()
        self.assertEqual(state["phase"], "REFERENCES_READY")
        self.assertEqual(len({row["path"] for row in state["references"].values()}), 1)

    def test_references_are_frozen_and_region_is_checked(self):
        views = {view: {"path": str(self.image), "source": "synthetic-test"} for view in workflow.VIEWS}
        views["front"]["region"] = [0, 0, 2, 1]
        with self.assertRaisesRegex(ValueError, "region"):
            self.call("references", {"views": views, "consistency_review": "Reject out-of-range reference crop"})
        self.refs()
        with self.assertRaises(ValueError):
            self.refs()
        state = self.call("status")
        Path(state["references"]["front"]["path"]).write_bytes(PNG + b"tampered")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.call("setup")

    def test_cannot_pass_without_all_views_and_criteria(self):
        state = self.capture()
        self.assertEqual(len(state["captures"][0]["images"]), 12)
        review = self.review_payload(state)
        review["viewed"].pop()
        with self.assertRaisesRegex(ValueError, "every captured"):
            self.call("review", review)
        review = self.review_payload(state)
        del review["comparisons"]["back"]["materials"]
        with self.assertRaisesRegex(ValueError, "every brief"):
            self.call("review", review)

    def test_stale_mesh_review_is_rejected_and_recapture_recovers(self):
        state = self.capture()
        self.blender.current = "changed-after-capture"
        with self.assertRaisesRegex(ValueError, "changed after capture"):
            self.call("review", self.review_payload(state))
        state = self.call("capture", {"changes": "Recapture changed geometry", "discard_unreviewed": True})
        self.assertEqual(len(state["captures"]), 2)
        self.assertIsNone(state["captures"][0]["review"])
        self.assertEqual(self.call("review", self.review_payload(state))["phase"], "ACCEPTED")

    def test_tampered_capture_and_metrics_cannot_be_reviewed(self):
        state = self.capture()
        report = Path(state["captures"][-1]["mesh_report_artifact"]["path"])
        report.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.call("review", self.review_payload(state))

    def test_failure_can_retry_without_overwriting_failed_capture(self):
        self.refs()
        self.call("setup")
        self.blender.failed_capture = True
        with self.assertRaises(RuntimeError):
            self.call("capture", {"changes": "Failing render"})
        failed_dirs = list((self.root / "jobs" / self.job).glob("round-*"))
        self.blender.failed_capture = False
        state = self.call("capture", {"changes": "Retry recovered render"})
        self.assertEqual(state["phase"], "NEEDS_REVIEW")
        self.assertTrue(failed_dirs[0].exists())
        self.assertNotEqual(Path(state["captures"][-1]["checkpoint"]["path"]).parent, failed_dirs[0])

    def test_specific_edit_and_changed_evidence_are_required_for_learning(self):
        first = self.capture()
        self.call("review", self.review_payload(first, "REPAIR"))
        self.blender.current = "mesh-v2-depth-corrected"
        second = self.call("capture", {"changes": "Corrected side depth"})
        self.call("review", self.review_payload(second))
        self.call("export")
        lesson = {"before": 1, "after": 2, "trigger": "depth mismatch", "technique": "Local depth correction",
                  "limits": "Synthetic regression evidence only"}
        finished = self.call("finish", {"delivery_checks": "Mock artifact check", "lessons": [lesson]})
        self.assertEqual(finished["phase"], "COMPLETE")
        lessons = self.call("lessons", {"query": "depth"})["lessons"]
        self.assertEqual(lessons[0]["status"], "OBSERVED_ON_ONE_TASK")
        self.assertEqual(len(lessons[0]["evidence"]), 1)
        with self.assertRaises(ValueError):
            self.call("capture", {"changes": "Task already finished"})

    def test_a_pass_alone_cannot_be_promoted_to_a_tested_lesson(self):
        state = self.capture()
        self.call("review", self.review_payload(state))
        self.call("export")
        with self.assertRaisesRegex(ValueError, "before/after"):
            self.call("finish", {"delivery_checks": "Mock export inspected", "lessons": [
                {"before": 1, "after": 1, "trigger": "Any shape", "technique": "Untested guess", "limits": "Unknown"}]})
        self.assertEqual(self.call("status")["phase"], "ACCEPTED")
        self.assertFalse((self.root / "lessons.json").exists())

    def test_a_changed_unreviewed_export_file_cannot_finish(self):
        state = self.capture()
        self.call("review", self.review_payload(state))
        state = self.call("export")
        Path(state["exports"]["glb"]["path"]).write_text("Unreviewed replacement")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.call("finish", {"delivery_checks": "Claiming delivery is complete"})
        self.assertEqual(self.call("status")["phase"], "ACCEPTED")

    def test_self_scoring_and_pass_with_issues_are_not_acceptance(self):
        state = self.capture()
        review = self.review_payload(state, "REPAIR")
        review["verdict"] = "PASS"
        with self.assertRaisesRegex(ValueError, "no unresolved"):
            self.call("review", review)
        with self.assertRaises(ValueError):
            self.call("export")

    def test_unchanged_repair_stops_without_claiming_success(self):
        first = self.capture()
        self.call("review", self.review_payload(first, "REPAIR"))
        second = self.call("capture", {"changes": "Ineffective correction"})
        state = self.call("review", self.review_payload(second, "REPAIR"))
        self.assertEqual(state["phase"], "LIMIT_REACHED")
        self.assertNotEqual(state["phase"], "COMPLETE")
        self.assertEqual(len(state["captures"]), 2)

    def test_iteration_limit_does_not_claim_success(self):
        self.job = self.call("create", {"brief": "Bounded task", "max_rounds": 1})["job"]
        state = self.capture()
        state = self.call("review", self.review_payload(state, "REPAIR"))
        self.assertEqual(state["phase"], "LIMIT_REACHED")
        with self.assertRaises(ValueError):
            self.call("export")

    def test_export_rejects_later_edits(self):
        state = self.capture()
        self.call("review", self.review_payload(state))
        self.blender.current = "new-unreviewed-model"
        with self.assertRaisesRegex(ValueError, "Changed model"):
            self.call("export")

    def test_routing_is_bounded_and_does_not_select_ai_weight_training(self):
        self.assertFalse(workflow.matches("Träna vår språkmodell och se OSINT-anomalier"))
        self.assertFalse(workflow.matches("Box3D fysik i GAME ENGINE"))
        for text in ("Modellera från bilden", "Blender EXT", "Skapa en 3Dmodell", "3D modeling workflow"):
            context = workflow.render_context(text, budget=600)
            self.assertLessEqual(len(context), 600)
            self.assertIn("SKILL.md", context)
            self.assertTrue(context.endswith("[/GG BLENDER WORKFLOW]"))
        with self.assertRaises(ValueError):
            self.call("status", {"job": "../../another-project"})


if __name__ == "__main__":
    unittest.main()
