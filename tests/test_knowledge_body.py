"""Source freshness, fictional case validation and local-only body assets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtGui import QGuiApplication
from backend import knowledge_atlas as atlas
from backend.knowledge_body import BodyExplorer, NEWS2_SCALE1_RULES, SCHEMA
from backend.knowledge_host import KnowledgeHost

APP = QGuiApplication.instance() or QGuiApplication([])


class BodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-body-test-")
        self.folder = Path(self.temporary.name)
        self.root = self.folder / "store"
        self.source = self.folder / "teaching.txt"
        self.source.write_text("Adult head section.\nChild chest section.\nReview the original page.", encoding="utf-8")
        imported = atlas.import_paths([self.source], root=self.root)
        self.source_id = imported["results"][0]["source_id"]
        page = atlas.source_page(self.source_id, 1, root=self.root)
        citation = {"source_id": self.source_id, "page": 1, "quote": "Review the original page.",
                    "revision": page["revision"]}
        self.bundle = self.root / "west-body"
        self.bundle.mkdir()
        Image.new("RGB", (64, 128), "#202020").save(self.bundle / "body.png")
        self.manifest = {
            "schema": SCHEMA, "title": "Fictional training atlas", "manual_state": "review",
            "age_groups": [{"id": "adult", "label": "Adult", "figure_id": "adult-front"},
                           {"id": "child", "label": "Child"}],
            "regions": [{"id": "head", "label": "Head", "x": .5, "y": .1},
                        {"id": "chest", "label": "Chest", "x": .5, "y": .3}],
            "figures": [{"id": "adult-front", "label": "Illustrative adult", "image_path": "body.png",
                         "age_groups": ["adult"], "layer": "surface"}],
            "topics": [{"id": "adult-head", "label": "Adult head", "age_groups": ["adult"],
                        "regions": ["head"], "citations": [citation],
                        "steps": [{"id": "review", "text": "Open the exact source page."}]},
                       {"id": "child-chest", "label": "Child chest", "age_groups": ["child"],
                        "regions": ["chest"], "citations": [citation]}],
            "parameters": [{"id": "pulse", "label": "Pulse", "unit": "/min", "min": 0, "max": 350},
                           {"id": "temperature", "label": "Temperature", "unit": "C", "min": 10, "max": 50},
                           {"id": "oxygen", "label": "Oxygen", "kind": "enum",
                            "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}],
            "scenarios": [{"id": "example", "label": "Fictional example", "age_group": "adult",
                           "topic_id": "adult-head", "severity": "orange", "parameters": {"pulse": 120}}],
        }
        self.write_manifest()
        self.explorer = BodyExplorer(root=self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self):
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")

    def evaluate(self, **request):
        return self.explorer.evaluate(json.dumps(request))

    def prepare_score(self):
        self.source.write_text(self.source.read_text(encoding="utf-8") +
            "\nAndningsfrekvens Syremättnad 1 Tillförd syrgas Systoliskt blodtryck "
            "Pulsfrekvens Medvetandegrad Temperatur.", encoding="utf-8")
        atlas.import_paths([self.source], root=self.root)
        revision = atlas.source_page(self.source_id, 1, root=self.root)["revision"]
        for topic in self.manifest["topics"]:
            topic["citations"][0]["revision"] = revision
        self.manifest["age_groups"].append({"id": "older", "label": "Older adult"})
        self.manifest["parameters"].extend([
            {"id": "rr", "label": "Respiratory rate", "min": 0, "max": 100},
            {"id": "spo2", "label": "SpO2", "min": 0, "max": 100},
            {"id": "sbp", "label": "Systolic pressure", "min": 0, "max": 350},
            {"id": "consciousness", "label": "Consciousness", "kind": "enum", "options": ["A", "C", "V", "P", "U"]},
        ])
        self.manifest["educational_scores"] = [{
            "id": "news2_scale1", "label": "NEWS2 Scale 1 exercise", "age_groups": ["adult", "older"],
            "citations": [{"source_id": self.source_id, "page": 1, "quote": "Review the original page.", "revision": revision}],
            "rules": NEWS2_SCALE1_RULES,
        }]
        self.write_manifest()
        return {"rr": 12, "spo2": 96, "oxygen": "no", "sbp": 111, "pulse": 51,
                "consciousness": "A", "temperature": 36.1}

    def score(self, parameters, **request):
        return self.evaluate(educational_score="news2_scale1", context="adult_nonpregnant_scale1",
                             age_group=request.pop("age_group", "adult"), parameters=parameters, **request)

    def test_snapshot_contains_local_illustration_and_verified_citations(self):
        result = self.explorer.snapshot()
        self.assertEqual(result["status"], "BODY_READY")
        self.assertFalse(result["stale"])
        bundle = result["bundle"]
        self.assertEqual(bundle["figures"][0]["image_url"], (self.bundle / "body.png").as_uri())
        self.assertEqual(bundle["figures"][0]["layer"], "surface")
        self.assertEqual(bundle["manual_state"], "review")
        self.assertTrue(bundle["topics"][0]["citations"][0]["valid"])
        self.assertTrue(bundle["learning_only"])
        self.assertFalse(bundle["clinical_use"])

    def test_source_change_is_visible_even_when_quote_stays_identical(self):
        self.assertFalse(self.explorer.snapshot()["stale"])
        self.source.write_text(self.source.read_text(encoding="utf-8") + "\nChanged surrounding context.", encoding="utf-8")
        atlas.import_paths([self.source], root=self.root)
        result = self.explorer.snapshot()
        self.assertTrue(result["stale"])
        self.assertTrue(result["bundle"]["topics"][0]["stale"])
        self.assertIn("ändrats", result["issues"][0])

    def test_missing_or_unbound_quote_does_not_become_a_verified_fact(self):
        citation = self.manifest["topics"][0]["citations"][0]
        citation["quote"] = "Not present in the teaching source."
        self.write_manifest()
        self.assertTrue(self.explorer.snapshot()["stale"])
        citation["quote"] = "Review the original page."
        citation.pop("revision")
        self.write_manifest()
        self.assertTrue(self.explorer.snapshot()["stale"])

    def test_case_echo_does_not_treat_missing_as_zero_or_infer_severity(self):
        result = self.evaluate(age_group="adult", parameters={"pulse": "0", "temperature": "37,4"},
                               region_id="head", injuries=["head"])
        self.assertEqual(result["status"], "BODY_EVALUATED")
        self.assertEqual(result["values"]["pulse"], 0)
        self.assertEqual(result["values"]["temperature"], 37.4)
        self.assertIsNone(result["values"]["oxygen"])
        self.assertIn("oxygen", result["missing"])
        self.assertEqual(result["manual_severity"], "unassessed")
        self.assertEqual(result["markers"][0]["region_id"], "head")
        self.assertEqual([row["id"] for row in result["matched_topics"]], ["adult-head"])
        self.assertFalse(result["complete"])
        self.assertNotIn("score", result)

    def test_unrealistic_and_nonfinite_values_are_validation_errors(self):
        for value in ("NaN", "Infinity", "1e309", 351, -1, True, {"nested": 1}):
            with self.subTest(value=value):
                result = self.evaluate(age_group="adult", parameters={"pulse": value})
                self.assertIsNone(result["values"]["pulse"])
                self.assertIn("pulse", [row["field"] for row in result["errors"]])
        self.assertEqual(self.explorer.evaluate('{"parameters":{"pulse":NaN}}')["status"], "ERROR")

    def test_age_group_filters_topics_and_case_selection_has_no_storage(self):
        before = (self.bundle / "manifest.json").read_bytes()
        result = self.evaluate(age_group="child", injuries=["head", "chest"], topic_id="adult-head")
        self.assertEqual([row["id"] for row in result["matched_topics"]], ["child-chest"])
        self.assertIn("topic_id", [row["field"] for row in result["errors"]])
        self.assertFalse(result["case_storage"])
        self.assertEqual((self.bundle / "manifest.json").read_bytes(), before)
        self.assertEqual(list(self.bundle.glob("*.json")), [self.bundle / "manifest.json"])

    def test_scenario_inputs_can_be_overridden_without_mutating_saved_example(self):
        result = self.evaluate(scenario_id="example", parameters={"pulse": 85, "temperature": 36.8, "oxygen": "no"})
        self.assertEqual(result["values"]["pulse"], 85)
        self.assertEqual(result["manual_severity"], "orange")
        self.assertTrue(result["input_complete"])
        self.assertEqual(self.explorer.snapshot()["bundle"]["scenarios"][0]["parameters"]["pulse"], 120)

    def test_assets_cannot_escape_bundle_and_late_asset_arrival_refreshes(self):
        self.manifest["figures"][0]["image_path"] = "../outside.png"
        self.write_manifest()
        self.assertEqual(self.explorer.snapshot()["bundle"]["figures"][0]["image_url"], "")
        self.manifest["figures"][0]["image_path"] = "late.png"
        self.write_manifest()
        self.assertTrue(self.explorer.snapshot()["stale"])
        Image.new("RGB", (64, 128), "#333333").save(self.bundle / "late.png")
        result = self.explorer.snapshot()
        self.assertFalse(result["stale"])
        self.assertEqual(result["bundle"]["figures"][0]["image_url"], (self.bundle / "late.png").as_uri())

    def test_wrong_input_types_return_errors_instead_of_crashing(self):
        result = self.evaluate(age_group={}, severity=[], region_id=[], injuries=[{"region_id": []}, []],
                               topic_id={}, topic_ids=[{}, []])
        self.assertEqual(result["status"], "BODY_EVALUATED")
        self.assertGreater(len(result["errors"]), 4)
        self.assertEqual(self.explorer.evaluate('[]')["status"], "ERROR")
        self.assertEqual(self.explorer.evaluate('{"__proto__":{}}')["status"], "ERROR")

    def test_host_bridge_returns_serializable_learning_state_and_honors_shutdown(self):
        host = KnowledgeHost(root=self.root)
        try:
            self.assertEqual(json.loads(host.body())["status"], "BODY_READY")
            response = json.loads(host.body_evaluate('{"age_group":"adult","parameters":{"pulse":100}}'))
            self.assertEqual(response["values"]["pulse"], 100)
            host.shutdown()
            self.assertEqual(json.loads(host.body())["status"], "CLOSED")
            self.assertEqual(json.loads(host.body_evaluate('{}'))["status"], "CLOSED")
        finally:
            host.shutdown()

    def test_optional_news2_has_known_reference_totals_without_final_triage(self):
        parameters = self.prepare_score()
        self.assertNotIn("score", self.evaluate(age_group="adult", parameters=parameters))
        zero = self.score(parameters)
        self.assertEqual(zero["score"]["total"], 0)
        self.assertTrue(zero["score"]["complete"])
        self.assertFalse(zero["complete"])
        self.assertEqual(zero["manual_severity"], "unassessed")
        worst = self.score({"rr": 25, "spo2": 91, "oxygen": "yes", "sbp": 90,
                            "pulse": 131, "consciousness": "U", "temperature": 35.0})
        self.assertEqual(worst["score"]["total"], 20)
        self.assertEqual(worst["manual_severity"], "unassessed")
        self.assertNotIn("priority", worst["score"])
        self.assertNotIn("treatment", worst["score"])
        self.assertEqual(self.score({"rr": 25, "spo2": 92, "oxygen": "yes", "sbp": 100,
                                    "pulse": 110, "consciousness": "C", "temperature": 39.1})["score"]["total"], 15)

    def test_news2_component_boundaries_match_visually_reviewed_source_table(self):
        baseline = self.prepare_score()
        # Independent expected points at each printed boundary and its next
        # permitted reading. In particular 111 pulse is 2, and 39.1 C is 2.
        expected = {
            "rr": [(8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3)],
            "spo2": [(91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0)],
            "sbp": [(90, 3), (91, 2), (100, 2), (101, 1), (110, 1), (111, 0), (219, 0), (220, 3)],
            "pulse": [(40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2), (130, 2), (131, 3)],
            "temperature": [(35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0), (38.1, 1), (39.0, 1), (39.1, 2)],
            "oxygen": [("no", 0), ("yes", 2)],
            "consciousness": [("A", 0), ("C", 3), ("V", 3), ("P", 3), ("U", 3)],
        }
        for field, cases in expected.items():
            for value, points in cases:
                with self.subTest(field=field, value=value):
                    result = self.score({**baseline, field: value})["score"]
                    component = next(row for row in result["components"] if row["id"] == field)
                    self.assertEqual(component["points"], points)
                    self.assertEqual(result["total"], points)

    def test_news2_missing_precision_or_invalid_choice_never_becomes_zero(self):
        baseline = self.prepare_score()
        for field in baseline:
            with self.subTest(missing=field):
                missing = self.score({**baseline, field: None})["score"]
                self.assertFalse(missing["complete"])
                self.assertIsNone(missing["total"])
                self.assertIn(field, missing["missing"])
        for field, value in (("rr", 11.5), ("spo2", 93.5), ("sbp", 110.5), ("pulse", 50.5), ("temperature", 35.05)):
            with self.subTest(field=field):
                result = self.score({**baseline, field: value})
                self.assertIsNone(result["score"]["total"])
                self.assertIn(field, result["score"]["missing"])
                self.assertIn(field, [row["field"] for row in result["errors"]])
        self.assertIsNone(self.score({**baseline, "consciousness": "chronic_confusion"})["score"]["total"])

    def test_news2_requires_eligible_explicit_adult_context_and_excludes_obstetric_topic(self):
        baseline = self.prepare_score()
        self.assertIsNone(self.evaluate(age_group="adult", parameters=baseline,
                                        educational_score="news2_scale1")["score"]["total"])
        for flags in ({"age_group": "child"}, {"pregnant": True}, {"postpartum": True}, {"spo2_scale": 2}):
            with self.subTest(flags=flags):
                result = self.score(baseline, **flags)
                self.assertIsNone(result["score"]["total"])
                self.assertFalse(result["score"]["complete"])
        self.manifest["topics"][0]["excludes_scores"] = ["news2_scale1"]
        self.write_manifest()
        self.assertIsNone(self.score(baseline, topic_id="adult-head")["score"]["total"])

    def test_news2_unverified_changed_rules_or_stale_source_disable_arithmetic(self):
        baseline = self.prepare_score()
        self.assertEqual(self.score(baseline)["score"]["total"], 0)
        self.source.write_text(self.source.read_text(encoding="utf-8") + "\nChanged score context.", encoding="utf-8")
        atlas.import_paths([self.source], root=self.root)
        self.assertIsNone(self.score(baseline)["score"]["total"])
        definition = self.manifest["educational_scores"][0]
        definition["citations"][0]["revision"] = atlas.source_page(self.source_id, 1, root=self.root)["revision"]
        definition["rules"] = json.loads(json.dumps(NEWS2_SCALE1_RULES))
        definition["rules"]["pulse"]["bands"][2][1] = 3
        self.write_manifest()
        self.assertIsNone(self.score(baseline)["score"]["total"])

    def test_entered_child_age_blocks_news2_despite_selected_adult_illustration(self):
        baseline = self.prepare_score()
        self.manifest["parameters"].append({"id": "age_years", "label": "Illustration age", "min": 0, "max": 130,
                                             "required": False})
        self.write_manifest()
        for age in (0, 6, 17, 17.99, "6", "17,9", -1, 131, True):
            with self.subTest(age=age):
                self.assertIsNone(self.score({**baseline, "age_years": age})["score"]["total"])
        for age in (18, 74, 75, 100, 130):
            with self.subTest(age=age):
                self.assertEqual(self.score({**baseline, "age_years": age})["score"]["total"], 0)
        self.assertEqual(self.score(baseline)["score"]["total"], 0)
        self.assertIsNone(self.score(baseline, age_years=6)["score"]["total"])

    def test_news2_accepts_actual_west_systolikt_table_heading(self):
        baseline = self.prepare_score()
        # WEST PDF page 10 uses "Systolikt blodtryck". Both this original
        # spelling and the conventional "Systoliskt" identify the component.
        self.source.write_text(self.source.read_text(encoding="utf-8").replace(
            "Systoliskt blodtryck", "Systolikt blodtryck"), encoding="utf-8")
        atlas.import_paths([self.source], root=self.root)
        revision = atlas.source_page(self.source_id, 1, root=self.root)["revision"]
        for topic in self.manifest["topics"]:
            topic["citations"][0]["revision"] = revision
        self.manifest["educational_scores"][0]["citations"][0]["revision"] = revision
        self.write_manifest()
        self.assertFalse(self.explorer.snapshot()["stale"])
        self.assertEqual(self.score(baseline)["score"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
