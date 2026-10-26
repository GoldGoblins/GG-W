"""Exercise the native raster explorer without a live desktop or network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPoint, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase
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


class AtlasHost(QObject):
    knowledgeUpdated = Signal(str)
    knowledgeImportFinished = Signal(str)
    knowledgePageReady = Signal(str)

    def __init__(self):
        super().__init__()
        self.pages = []
        self.imports = []
        self.scene = None

    @Slot(str, result=str)
    def knowledgeScene(self, scene_id):
        return json.dumps({"status": "SCENE_READY", "scene": self.scene})

    @Slot(str, str, result=str)
    def knowledgeSnapshot(self, query, kind):
        return json.dumps({
            "status": "READY", "nodes": [
                {"id": "A", "label": "First manual", "kind": "SOURCE"},
                {"id": "B", "label": "Second manual", "kind": "SOURCE"},
            ],
            "sources": [], "scenes": [], "hits": [], "edges": [],
            "counts": {"sources": 2, "pages": 6},
        })

    @Slot(str, result=str)
    def knowledgeDetail(self, node_id):
        return json.dumps({"status": "DETAIL", "source_id": node_id,
                           "node": {"id": node_id, "label": node_id, "kind": "SOURCE"},
                           "passages": []})

    @Slot(str, int, result=bool)
    def knowledgePage(self, source_id, page):
        self.pages.append((source_id, page))
        return True

    @Slot(str, result=bool)
    def knowledgeImport(self, paths):
        self.imports.append(json.loads(paths))
        return True


class KnowledgeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
            for name in ("consola.ttf", "consolab.ttf"):
                if (fonts / name).is_file():
                    QFontDatabase.addApplicationFont(str(fonts / name))
            cls.app.setFont(QFont("Consolas"))

    def setUp(self):
        self.host = AtlasHost()
        self.warnings = []
        self.view = QQuickView()
        self.view.engine().warnings.connect(
            lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.view.setSource(QUrl.fromLocalFile(str(PROJECT / "qml/components/KnowledgeSurface.qml")))
        self.assertEqual(self.view.status(), QQuickView.Ready,
                         [error.toString() for error in self.view.errors()])
        self.root = self.view.rootObject()
        self.root.setProperty("surfaceHost", self.host)
        self.view.resize(1280, 800)
        self.view.show()
        QTest.qWait(30)

    def tearDown(self):
        self.view.close()
        self.assertEqual(self.warnings, [])
        self.view.setSource(QUrl())
        self.app.processEvents()

    def click(self, name):
        item = visual_item(self.root, name)
        self.assertIsNotNone(item, name)
        center = item.mapToScene(item.boundingRect().center())
        QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(center.x()), round(center.y())))
        self.app.processEvents()

    def test_raster_navigation_at_desktop_sizes(self):
        raster = visual_item(self.root, "knowledgeRasterView")
        for _ in range(100):
            if raster.property("imageReady"):
                break
            QTest.qWait(20)
        self.assertTrue(raster.property("imageReady"), "Bundled example raster did not load")
        for width, height in ((1280, 800), (900, 600)):
            with self.subTest(width=width, height=height):
                self.view.resize(width, height)
                self.app.processEvents()
                self.click("knowledgeHotspot0")
                self.assertEqual(variant(self.root.property("selectedHotspot"))["id"], "nucleus")
                self.click("knowledgeZoomIn")
                self.assertGreater(raster.property("zoom"), 1)
                self.click("knowledgeZoomReset")
                self.assertEqual(raster.property("zoom"), 1)
                self.root.back()

    def test_source_navigation_uses_latest_request_and_full_text(self):
        self.root.selectNode("A", True, 1)
        self.root.selectNode("B", True, 2)
        self.assertEqual(self.host.pages, [("A", 1)])
        self.host.knowledgePageReady.emit(json.dumps({
            "status": "TEXT_READY", "source_id": "A", "page": 1,
            "pages": 3, "text": "Older response must not replace the current selection.",
        }))
        self.app.processEvents()
        self.assertEqual(self.host.pages, [("A", 1), ("B", 2)])
        self.assertIsNone(variant(self.root.property("pageView")))
        full_text = "<Untrusted markup is plain source text>\n" + "A complete source page. " * 150
        self.host.knowledgePageReady.emit(json.dumps({
            "status": "TEXT_READY", "source_id": "B", "page": 2,
            "pages": 3, "text": full_text,
        }))
        self.app.processEvents()
        self.assertTrue(self.root.property("showingText"))
        self.assertEqual(variant(self.root.property("pageView"))["source_id"], "B")
        text = visual_item(self.root, "knowledgeSourceText")
        self.assertEqual(text.property("text"), full_text)

    def test_partial_import_and_stale_scene_are_visible(self):
        paths = ["file:///selected/manual.pdf", "file:///selected/broken.pdf"]
        self.root.importFiles(paths)
        self.assertEqual(self.host.imports, [paths])
        self.host.knowledgeImportFinished.emit(json.dumps({
            "status": "IMPORTED", "imported": 1, "cached": 0, "errors": 1,
            "results": [{"status": "IMPORTED", "title": "Manual"},
                        {"status": "ERROR", "title": "Broken", "reason": "INVALID_PDF"}],
        }))
        self.app.processEvents()
        self.assertFalse(self.root.property("importBusy"))
        self.assertEqual(len(variant(self.root.property("importMessages"))), 1)
        self.assertIn("Broken", variant(self.root.property("importMessages"))[0])
        report = self.root.findChild(QObject, "knowledgeImportReport")
        self.assertIsNotNone(report)
        self.assertTrue(report.property("visible"))
        report.close()
        image_url = (PROJECT / "qml/assets/knowledge-cell.png").as_uri()
        self.root.loadScene({"id": "older-view", "title": "Earlier illustration", "image_url": image_url,
                             "illustrative": False, "stale": True, "notice": "The source was changed.",
                             "hotspots": []})
        self.app.processEvents()
        self.assertFalse(self.root.property("canPrepareQuestion"))
        warning = visual_item(self.root, "knowledgeStaleNotice")
        self.assertTrue(warning.isVisible())
        self.assertEqual(warning.property("text"), "The source was changed.")

    def test_active_scene_is_revalidated_after_material_update(self):
        self.host.scene = {"id": "saved-scene", "title": "Published object",
                           "image_url": (PROJECT / "qml/assets/knowledge-cell.png").as_uri(),
                           "illustrative": False, "hotspots": [], "stale": False}
        self.root.openScene("saved-scene")
        self.app.processEvents()
        self.assertFalse(self.root.property("sceneStale"))
        self.host.scene["stale"] = True
        self.host.scene["notice"] = "The document context was revised."
        self.host.knowledgeUpdated.emit(self.host.knowledgeSnapshot("", "ALL"))
        self.app.processEvents()
        self.assertTrue(self.root.property("sceneStale"))
        self.assertFalse(self.root.property("canPrepareQuestion"))


if __name__ == "__main__":
    unittest.main()
