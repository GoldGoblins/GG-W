"""Cited scene publishing and the asynchronous UI bridge, without model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image
from PySide6.QtGui import QGuiApplication
from backend import knowledge_atlas as atlas, knowledge_scenes as scenes
from backend.knowledge_host import KnowledgeHost

APP = QGuiApplication.instance() or QGuiApplication([])


def events_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.01)
    return predicate()


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-scene-test-")
        self.folder = Path(self.temporary.name)
        self.root = self.folder / "store"
        self.source = self.folder / "motor.txt"
        self.source.write_text("The rotor moves inside the housing.\nThe bearing supports the shaft.", encoding="utf-8")
        imported = atlas.import_paths([self.source], root=self.root)
        self.source_id = imported["results"][0]["source_id"]
        self.image = self.folder / "motor.png"
        Image.new("RGB", (128, 96), "#202020").save(self.image)
        self.payload = {"schema": scenes.SCHEMA, "title": "Motor", "image_path": str(self.image),
                        "illustrative": False, "hotspots": [{"id": "rotor", "label": "Rotor",
                        "x": .4, "y": .5, "summary": "The rotor sits inside the housing.",
                        "citations": [{"source_id": self.source_id, "page": 1,
                                       "quote": "The rotor moves inside the housing."}]}]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_scene_validates_quote_and_keeps_immutable_raster(self):
        result = scenes.publish(self.payload, root=self.root)
        self.assertEqual(result["status"], "SCENE_PUBLISHED")
        scene = scenes.read(result["scene_id"], root=self.root)["scene"]
        self.assertFalse(scene["stale"])
        self.assertEqual(scene["hotspots"][0]["citations"][0]["source_title"], "motor")
        self.assertNotEqual(scene["image_url"], self.image.as_uri())
        self.image.unlink()
        self.assertEqual(len(scenes.list_scenes(root=self.root)), 1)
        self.assertEqual(scenes.read(result["scene_id"], root=self.root)["status"], "SCENE_READY")

    def test_missing_quote_and_missing_citation_are_rejected(self):
        self.payload["hotspots"][0]["citations"][0]["quote"] = "A fabricated fact"
        self.assertEqual(scenes.publish(self.payload, root=self.root)["reason"], "CITATION_QUOTE_NOT_ON_PAGE")
        self.payload["hotspots"][0]["citations"] = []
        self.assertEqual(scenes.publish(self.payload, root=self.root)["reason"], "SOURCED_HOTSPOT_NEEDS_CITATION")
        self.assertEqual(scenes.list_scenes(root=self.root), [])

    def test_context_edit_marks_scene_stale_even_when_quote_survives(self):
        published = scenes.publish(self.payload, root=self.root)
        self.source.write_text(self.source.read_text(encoding="utf-8") + "\nRevised context.", encoding="utf-8")
        atlas.import_paths([self.source], root=self.root)
        self.assertTrue(scenes.read(published["scene_id"], root=self.root)["scene"]["stale"])

    def test_illustrative_scene_has_explicit_flag_and_bounded_coordinates(self):
        self.payload["illustrative"] = True
        self.payload["hotspots"][0]["citations"] = []
        self.payload["hotspots"][0]["x"] = float("nan")
        self.assertEqual(scenes.publish(self.payload, root=self.root)["reason"], "HOTSPOT_POSITION_INVALID")
        self.payload["hotspots"][0]["x"] = .5
        result = scenes.publish(self.payload, root=self.root)
        self.assertTrue(scenes.read(result["scene_id"], root=self.root)["scene"]["illustrative"])

    def test_host_imports_file_urls_and_reads_text_off_thread(self):
        host = KnowledgeHost(root=self.root)
        imports, pages, updates = [], [], []
        host.importFinished.connect(lambda value: imports.append(json.loads(value)))
        host.pageReady.connect(lambda value: pages.append(json.loads(value)))
        host.updated.connect(lambda value: updates.append(json.loads(value)))
        try:
            self.assertFalse(host.import_paths('["https://example.invalid/remote.pdf"]'))
            self.assertTrue(host.import_paths(json.dumps([self.source.as_uri()])))
            self.assertTrue(events_until(lambda: bool(imports)))
            self.assertEqual(imports[0]["cached"], 1)
            self.assertTrue(host.page(self.source_id, 1))
            self.assertTrue(events_until(lambda: bool(pages)))
            self.assertEqual(pages[0]["status"], "TEXT_READY")
            self.assertIn("rotor", pages[0]["text"])
            self.assertEqual(json.loads(host.snapshot("rotor", "ALL"))["model_calls"], 0)
        finally:
            host.shutdown()

    def test_shutdown_does_not_publish_late_worker_result(self):
        host = KnowledgeHost(root=self.root)
        blocker = threading.Event()
        received = []
        host.pageReady.connect(received.append)
        self.assertTrue(host._queue(lambda: blocker.wait(2) or {}, host.pageReady))
        host.shutdown()
        blocker.set()
        events_until(lambda: not host._busy, 3)
        self.assertEqual(received, [])
        self.assertFalse(host.page(self.source_id, 1))

    def test_cli_publishes_relative_image_with_checked_citations(self):
        self.payload["image_path"] = self.image.name
        manifest = self.folder / "scene.json"
        manifest.write_text(json.dumps(self.payload), encoding="utf-8")
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(PROJECT / "gg-knowledge"),
                                 "--root", str(self.root), "publish", str(manifest)],
                                cwd=PROJECT, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        published = json.loads(result.stdout)
        self.assertEqual(published["status"], "SCENE_PUBLISHED")
        self.assertFalse(scenes.read(published["scene_id"], root=self.root)["scene"]["stale"])

    def test_idle_reads_do_not_trigger_background_refresh_loop(self):
        host = KnowledgeHost(root=self.root)
        updates = []
        host.updated.connect(updates.append)
        try:
            host.snapshot()
            events_until(lambda: False, .9)
            self.assertEqual(updates, [])
            self.assertEqual(scenes.publish(self.payload, root=self.root)["status"], "SCENE_PUBLISHED")
            self.assertTrue(events_until(lambda: bool(updates)))
            count = len(updates)
            events_until(lambda: False, .8)
            self.assertEqual(len(updates), count)
        finally:
            host.shutdown()


if __name__ == "__main__":
    unittest.main()
