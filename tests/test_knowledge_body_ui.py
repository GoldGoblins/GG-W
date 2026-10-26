"""Exercise the body explorer's real native interactions and source navigation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPoint, Qt, QUrl, Signal, Slot
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def variant(value):
    return value.toVariant() if hasattr(value, "toVariant") else value


def visual_item(item: QQuickItem, name: str):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = visual_item(child, name)
        if found is not None:
            return found
    return None


class BodyHost(QObject):
    knowledgeUpdated = Signal(str)
    knowledgeImportFinished = Signal(str)
    knowledgePageReady = Signal(str)

    def __init__(self):
        super().__init__()
        self.evaluations = []
        self.pages = []
        image = (PROJECT / "qml/assets/knowledge-cell.png").as_uri()
        self.bundle = {
            "schema": "gg.west-body.v1", "title": "Test material",
            "age_groups": [{"id": "adult", "label": "Vuxen", "figure_id": "adult-inside"}, {"id": "child", "label": "Barn"},
                           {"id": "infant", "label": "Spädbarn"}],
            "figures": [{"id": "adult-surface", "label": "Yta", "age_group": "adult", "image_url": image},
                        {"id": "adult-inside", "label": "Inre", "age_group": "adult", "image_url": image},
                        {"id": "child-inside", "label": "Inre", "age_groups": ["child", "infant"], "image_url": image}],
            "regions": [{"id": "chest", "label": "Bröstkorg", "x": 0.5, "y": 0.4},
                        {"id": "head", "label": "Huvud", "x": 0.5, "y": 0.2}],
            "topics": [{"id": "breath", "label": "Andning", "regions": ["chest"],
                        "summary": "Test topic", "review_notes": ["Granskningspunkt: kontrollera källan."],
                        "steps": [{"id": "observe", "text": "Läs originalsidans tabell."}],
                        "illustrations": [{"label": "Provtagningsmoment", "image_url": image, "summary": "Testillustration."}],
                        "citations": [{"source_id": "WEST", "page": 21, "quote": "Test citation"}]},
                       {"id": "child-head", "label": "Huvud barn", "age_groups": ["child", "infant"],
                        "regions": ["head"], "steps": [], "citations": []}],
            "parameters": [{"id": "pulse", "label": "Puls", "unit": "/min", "kind": "number"},
                           {"id": "oxygen", "label": "Syrgas", "kind": "enum",
                            "options": [{"value": "yes", "label": "Ja"}, {"value": "no", "label": "Nej"}]}],
            "scenarios": [{"id": "example", "label": "Fiktivt exempel", "age_group": "child", "topic_id": "breath",
                           "region_id": "chest", "parameters": {"pulse": 100}, "severity": "unassessed"}],
        }

    @Slot(result=str)
    def knowledgeBody(self):
        return json.dumps({"status": "BODY_READY", "bundle": self.bundle})

    @Slot(str, result=str)
    def knowledgeBodyEvaluate(self, raw):
        payload = json.loads(raw)
        self.evaluations.append(payload)
        return json.dumps({"status": "EVALUATED", "values": payload["parameters"], "errors": [],
                           "missing": [], "notice": "Fiktiv övning."})

    @Slot(str, str, result=str)
    def knowledgeSnapshot(self, query, kind):
        return json.dumps({"status": "READY", "nodes": [], "sources": [], "scenes": [], "hits": [], "edges": [], "counts": {}})

    @Slot(str, int, result=bool)
    def knowledgePage(self, source, page):
        self.pages.append((source, page))
        return True


class KnowledgeBodyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = BodyHost()
        self.warnings = []
        self.view = QQuickView()
        self.view.engine().warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.view.setSource(QUrl.fromLocalFile(str(PROJECT / "qml/components/KnowledgeSurface.qml")))
        self.assertEqual(self.view.status(), QQuickView.Ready, [error.toString() for error in self.view.errors()])
        self.surface = self.view.rootObject()
        self.surface.setProperty("surfaceHost", self.host)
        self.view.resize(1280, 800)
        self.view.show()
        QTest.qWait(30)
        self.click("knowledgeBodyButton")
        self.root = visual_item(self.surface, "knowledgeBodyView")
        self.assertIsNotNone(self.root)

    def tearDown(self):
        self.view.close()
        self.assertEqual(self.warnings, [])
        self.view.setSource(QUrl())
        self.app.processEvents()

    def click(self, name):
        QTest.qWait(20)
        item = visual_item(self.surface, name)
        if item is None:
            item = visual_item(self.view.contentItem(), name)
        self.assertIsNotNone(item, name)
        self.assertTrue(item.isVisible(), name)
        center = item.mapToScene(item.boundingRect().center())
        QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier, QPoint(round(center.x()), round(center.y())))
        self.app.processEvents()

    def test_age_region_zoom_and_source_roundtrip_preserves_case(self):
        raster = visual_item(self.root, "knowledgeBodyRaster")
        for _ in range(50):
            if raster.property("imageReady"):
                break
            QTest.qWait(20)
        self.assertTrue(raster.property("imageReady"))
        self.assertEqual(variant(self.root.property("currentFigure"))["id"], "adult-inside")
        self.click("knowledgeBodyZoomIn")
        self.assertGreater(raster.property("zoom"), 1)
        self.click("knowledgeBodyZoomReset")
        self.assertEqual(raster.property("zoom"), 1)
        self.click("knowledgeBodyAge_child")
        self.assertEqual(self.root.property("ageGroup"), "child")
        self.root.selectRegion("chest")
        self.app.processEvents()
        self.assertEqual([row["id"] for row in variant(self.root.property("topics"))], ["breath"])
        self.click("knowledgeBodyTopic_breath")
        review = visual_item(self.root, "knowledgeBodyReviewNote")
        self.assertTrue(review.isVisible())
        self.assertIn("Granskningspunkt", review.property("text"))
        self.click("knowledgeBodyStep0")
        self.assertTrue(variant(self.root.property("checkedSteps"))["observe"])
        self.root.setParameter("pulse", "105")
        self.root.evaluate()
        self.root.openCitation({"source_id": "WEST", "page": 21})
        self.app.processEvents()
        self.assertEqual(self.host.pages, [("WEST", 21)])
        self.host.knowledgePageReady.emit(json.dumps({"status": "TEXT_READY", "source_id": "WEST", "page": 21, "pages": 119, "text": "Source text"}))
        self.app.processEvents()
        self.assertEqual(self.surface.property("mode"), "BILD")
        self.click("knowledgeBodyButton")
        self.assertEqual(self.surface.property("mode"), "KROPP")
        self.assertEqual(variant(self.root.property("parameters"))["pulse"], "105")
        self.assertTrue(variant(self.root.property("checkedSteps"))["observe"])

    def test_entered_values_injuries_and_missing_state_are_explicit(self):
        self.click("knowledgeBodyTabParametrar")
        QTest.qWait(30)
        field = visual_item(self.root, "knowledgeBodyParameter_pulse")
        center = field.mapToScene(field.boundingRect().center())
        QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier, QPoint(round(center.x()), round(center.y())))
        QTest.qWait(20)
        QTest.keyClick(self.view, Qt.Key_8)
        QTest.keyClick(self.view, Qt.Key_5)
        QTest.qWait(210)
        self.assertEqual(self.host.evaluations[-1]["parameters"]["pulse"], "85")
        self.assertEqual(variant(self.root.property("enteredValues"))[0]["value"], "85")
        self.assertEqual(self.root.property("manualSeverity"), "unassessed")
        self.click("knowledgeBodyInjuryMode")
        self.root.selectRegion("chest")
        self.assertEqual(variant(self.root.property("injuries")), ["chest"])
        self.click("knowledgeBodyReset")
        self.assertEqual(variant(self.root.property("parameters")), {})
        self.assertEqual(variant(self.root.property("injuries")), [])
        self.assertEqual(self.root.property("manualSeverity"), "unassessed")

    def test_narrow_layout_keeps_body_and_scrollable_details_inside_surface(self):
        for width, height in ((1280, 800), (900, 600), (360, 740), (320, 650)):
            with self.subTest(width=width, height=height):
                self.view.resize(width, height)
                self.app.processEvents()
                stage = visual_item(self.root, "knowledgeBodyStage")
                detail = visual_item(self.root, "knowledgeBodyDetailPanel")
                self.assertGreater(stage.width(), 0)
                self.assertGreater(stage.height(), 0)
                self.assertGreater(detail.height(), 0)
                for item in (stage, detail):
                    self.assertGreaterEqual(item.x(), 0)
                    self.assertLessEqual(item.x() + item.width(), self.root.width() + 1)
                self.assertEqual(self.root.property("stacked"), width < 768)
                if width < 768:
                    self.click("knowledgeBodyMobileDetails")
                    self.assertTrue(detail.isVisible())
                    self.assertFalse(stage.isVisible())
                    self.click("knowledgeBodyMobileBody")
                    self.assertTrue(stage.isVisible())

    def test_news_context_requires_explicit_opt_in_and_resets_with_age(self):
        self.click("knowledgeBodyTabParametrar")
        self.assertNotIn("educational_score", self.host.evaluations[-1])
        self.click("knowledgeBodyNewsEnabled")
        self.assertEqual(self.host.evaluations[-1]["educational_score"], "news2_scale1")
        self.assertEqual(self.host.evaluations[-1]["context"], "adult_nonpregnant_scale1")
        self.click("knowledgeBodyAge_child")
        self.assertFalse(self.root.property("newsEnabled"))
        self.assertNotIn("educational_score", self.host.evaluations[-1])

    def test_body_hotspot_drills_into_region_and_whole_body_resets_zoom(self):
        raster = visual_item(self.root, "knowledgeBodyRaster")
        for _ in range(50):
            if raster.property("imageReady"):
                break
            QTest.qWait(20)
        point = visual_item(self.root, "knowledgeHotspot0")
        self.assertIsNotNone(point)
        center = point.mapToScene(point.boundingRect().center())
        QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier, QPoint(round(center.x()), round(center.y())))
        self.app.processEvents()
        self.assertEqual(self.root.property("selectedRegionId"), "chest")
        self.assertGreater(raster.property("zoom"), 1)
        self.click("knowledgeBodyZoomReset")
        self.assertEqual(raster.property("zoom"), 1)

    def test_injury_click_adds_visible_cross_and_reset_clears_marker(self):
        raster = visual_item(self.root, "knowledgeBodyRaster")
        for _ in range(50):
            if raster.property("imageReady"):
                break
            QTest.qWait(20)
        self.click("knowledgeBodyInjuryMode")
        point = visual_item(self.root, "knowledgeHotspot0")
        center = point.mapToScene(point.boundingRect().center())
        QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier, QPoint(round(center.x()), round(center.y())))
        QTest.qWait(30)
        self.assertTrue(variant(self.root.property("hotspots"))[0]["injury"])
        self.assertTrue(visual_item(self.root, "knowledgeInjuryMarker0").isVisible())
        self.assertTrue(visual_item(self.root, "knowledgeBodyInjuryLegend").isVisible())
        self.assertEqual(self.root.property("manualSeverity"), "unassessed")
        self.click("knowledgeBodyReset")
        QTest.qWait(30)
        self.assertFalse(variant(self.root.property("hotspots"))[0]["injury"])
        self.assertFalse(visual_item(self.root, "knowledgeInjuryMarker0").isVisible())
        self.assertFalse(visual_item(self.root, "knowledgeBodyInjuryLegend").isVisible())

    def test_procedure_picture_enlarges_zooms_and_closes_without_losing_case(self):
        self.root.selectTopic("breath")
        self.root.setParameter("pulse", "88")
        self.root.setStep("observe", True)
        QTest.qWait(40)
        scroll = visual_item(self.root, "knowledgeBodyScroll")
        flickable = scroll.property("contentItem")
        flickable.setProperty("contentY", max(0, flickable.property("contentHeight") - flickable.height()))
        QTest.qWait(30)
        self.click("knowledgeBodyOpenIllustration0")
        popup = self.root.findChild(QObject, "knowledgeBodyIllustrationDialog")
        self.assertTrue(popup.property("visible"))
        raster = visual_item(self.view.contentItem(), "knowledgeBodyIllustrationRaster")
        self.assertIsNotNone(raster)
        for _ in range(50):
            if raster.property("imageReady"):
                break
            QTest.qWait(20)
        self.assertTrue(raster.property("imageReady"))
        self.click("knowledgeBodyIllustrationZoomIn")
        self.assertGreater(raster.property("zoom"), 1)
        self.click("knowledgeBodyIllustrationClose")
        self.assertFalse(popup.property("visible"))
        self.assertEqual(self.root.property("selectedTopicId"), "breath")
        self.assertEqual(variant(self.root.property("parameters"))["pulse"], "88")
        self.assertTrue(variant(self.root.property("checkedSteps"))["observe"])


if __name__ == "__main__":
    unittest.main()
