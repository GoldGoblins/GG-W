"""Real local import/search/raster tests; no model, network or user-state writes."""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from backend import knowledge_atlas as atlas


def make_pdf(path: Path, texts: list[str]) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QPainter, QPageSize, QPdfWriter
    app = QGuiApplication.instance() or QGuiApplication(["GG knowledge test"])
    # Offscreen Windows does not enumerate the system font database.
    if not QFontDatabase.families():
        for candidate in (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf",
                          Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
            if candidate.is_file():
                QFontDatabase.addApplicationFont(str(candidate))
                break
    families = QFontDatabase.families()
    if not families:
        raise RuntimeError("A local font is required for the PDF integration test")
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.setFont(QFont(families[0], 14))
    painter.setPen(Qt.black)
    for index, text in enumerate(texts):
        if index:
            writer.newPage()
        painter.drawText(QRectF(40, 40, 470, 700), Qt.TextWordWrap, text)
    painter.end()
    del painter, writer
    gc.collect()
    app.processEvents()


class KnowledgeAtlasTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-knowledge-test-")
        self.directory = Path(self.temporary.name)
        self.state = self.directory / "state"
        self.inputs = self.directory / "inputs"
        self.inputs.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def import_one(self, path: Path) -> dict:
        result = atlas.import_paths([str(path)], root=self.state)
        self.assertEqual(result["status"], "IMPORTED", result)
        self.assertEqual(result["model_calls"], 0)
        return result["results"][0]

    def test_full_text_beyond_old_excerpt_limit_and_persistence(self):
        path = self.inputs / "manual.txt"
        text = ("Materialets grundtext. " * 180) + "Helikopterskruvens tolerans är 0,04 mm."
        path.write_text(text, encoding="utf-8")
        source = self.import_one(path)
        result = atlas.snapshot("Helikopterskruvens", root=self.state)
        self.assertEqual(len(result["hits"]), 1)
        hit = result["hits"][0]
        self.assertEqual(hit["source_id"], source["source_id"])
        self.assertEqual(hit["page"], 1)
        self.assertIn("0,04 mm", hit["text"])
        full = atlas.source_page(source["source_id"], 1, root=self.state)
        self.assertEqual(full["text"], text)
        self.assertEqual(full["status"], "PAGE_TEXT")
        self.assertEqual(atlas.snapshot(root=self.state)["counts"]["sources"], 1)

    def test_real_pdf_text_page_provenance_and_raster_cache(self):
        path = self.inputs / "biology.pdf"
        make_pdf(path, ["Mitochondria generate ATP.", "Cell nuclei contain genetic material."])
        source = self.import_one(path)
        self.assertEqual(source["pages"], 2)
        self.assertEqual(source["needs_ocr"], [])
        result = atlas.snapshot("genetic", root=self.state)
        self.assertEqual(result["hits"][0]["page"], 2)
        self.assertEqual(result["hits"][0]["source_title"], "biology")
        image = atlas.page_image(source["source_id"], 2, root=self.state)
        self.assertEqual(image["status"], "PAGE_READY", image)
        self.assertFalse(image["cached"])
        from backend.platform_support import local_file_path
        from PIL import Image
        with Image.open(local_file_path(image["image_url"])) as raster:
            self.assertGreater(raster.width, 500)
            self.assertLessEqual(raster.height, 2200)
        second = atlas.page_image(source["source_id"], 2, root=self.state)
        self.assertTrue(second["cached"])
        self.assertEqual(second["image_url"], image["image_url"])
        detail = atlas.detail(source["source_id"], root=self.state)
        self.assertEqual(detail["status"], "DETAIL")
        self.assertIn("genetic", detail["passages"][1]["text"])
        self.assertEqual(atlas.page_image(source["source_id"], 3, root=self.state)["reason"], "INVALID_PAGE")

    def test_blank_pdf_page_is_explicit_ocr_gap(self):
        path = self.inputs / "scan.pdf"
        make_pdf(path, ["Readable first page.", ""])
        source = self.import_one(path)
        self.assertEqual(source["needs_ocr"], [2])
        self.assertTrue(atlas.snapshot(root=self.state)["notices"])
        page = atlas.source_page(source["source_id"], 2, root=self.state)
        self.assertTrue(page["needs_ocr"])
        self.assertEqual(page["text"], "")
        self.assertEqual(atlas.page_image(source["source_id"], 2, root=self.state)["status"], "PAGE_READY")

    def test_duplicate_and_changed_file_remove_stale_terms_and_rasters(self):
        path = self.inputs / "changing.txt"
        path.write_text("DeprecatedRotor alpha.", encoding="utf-8")
        first = self.import_one(path)
        original_revision = atlas.source_page(first["source_id"], root=self.state)["revision"]
        cached = self.import_one(path)
        self.assertEqual(cached["status"], "CACHED")
        self.assertEqual(cached["source_id"], first["source_id"])
        self.assertEqual(atlas.source_page(first["source_id"], root=self.state)["revision"], original_revision)
        path.write_text("ReplacementBearing beta.", encoding="utf-8")
        changed = self.import_one(path)
        self.assertEqual(changed["source_id"], first["source_id"])
        self.assertNotEqual(atlas.source_page(first["source_id"], root=self.state)["revision"], original_revision)
        self.assertEqual(atlas.snapshot("DeprecatedRotor", root=self.state)["hits"], [])
        self.assertEqual(len(atlas.snapshot("ReplacementBearing", root=self.state)["hits"]), 1)
        self.assertEqual(atlas.snapshot(root=self.state)["counts"]["sources"], 1)
        labels = [node["label"] for node in atlas.snapshot(root=self.state)["nodes"]]
        self.assertNotIn("deprecatedrotor", labels)

    def test_images_are_objects_without_invented_captions(self):
        from PIL import Image
        path = self.inputs / "metal-bearing.png"
        Image.new("RGB", (120, 80), "#254358").save(path)
        source = self.import_one(path)
        snapshot = atlas.snapshot(kind="OBJECT", root=self.state)
        self.assertEqual(snapshot["counts"]["objects"], 1)
        self.assertEqual(snapshot["nodes"][0]["kind"], "OBJECT")
        self.assertIn("utan automatisk tolkning", snapshot["nodes"][0]["summary"])
        raster = atlas.page_image(source["source_id"], root=self.state)
        self.assertEqual(raster["status"], "PAGE_READY")
        self.assertEqual(raster["width"], 120)

    def test_text_form_feed_pages_and_safe_query(self):
        path = self.inputs / "parts.md"
        path.write_text("Motor \fTransmission bearings", encoding="utf-8")
        source = self.import_one(path)
        self.assertEqual(source["pages"], 2)
        self.assertEqual(atlas.snapshot('"bearings"', root=self.state)["hits"][0]["page"], 2)
        self.assertEqual(atlas.page_image(source["source_id"], 2, root=self.state)["status"], "TEXT_READY")
        self.assertEqual(atlas.source_page(source["source_id"], 3, root=self.state)["status"], "ERROR")
        self.assertEqual(atlas.snapshot(kind="BROKEN", root=self.state)["status"], "ERROR")

    def test_kind_filters_cover_search_hits_source_lists_and_nodes(self):
        from PIL import Image
        document = self.inputs / "memo.txt"
        document.write_text("Rotor maintenance procedure.", encoding="utf-8")
        document_source = self.import_one(document)["source_id"]
        picture = self.inputs / "Rotor.png"
        Image.new("RGB", (80, 60), "#254358").save(picture)
        object_source = self.import_one(picture)["source_id"]
        for query in ("", "Rotor"):
            for kind, source_id in (("SOURCE", document_source), ("OBJECT", object_source)):
                result = atlas.snapshot(query, kind=kind, root=self.state)
                self.assertEqual({s["id"] for s in result["sources"]}, {source_id})
                self.assertEqual({n["id"] for n in result["nodes"]}, {source_id})
                self.assertTrue(all(n["kind"] == kind for n in result["nodes"]))
                if query:
                    self.assertEqual({h["source_id"] for h in result["hits"]}, {source_id})
        all_hits = atlas.snapshot("Rotor", root=self.state)["hits"]
        self.assertEqual({h["source_id"] for h in all_hits}, {document_source, object_source})

    def test_search_includes_short_acronyms_and_numeric_measurements(self):
        path = self.inputs / "measurements.txt"
        path.write_text("AI calibration: rotor tolerance is 0.04 mm. Part AX-12.", encoding="utf-8")
        self.import_one(path)
        for query in ("AI", "0.04", "AX-12"):
            self.assertEqual(len(atlas.snapshot(query, root=self.state)["hits"]), 1, query)

    def test_graph_edges_are_only_literal_mentions(self):
        path = self.inputs / "concepts.txt"
        path.write_text("Rotor bearings appear together. Rotor tolerances.", encoding="utf-8")
        self.import_one(path)
        snapshot = atlas.snapshot(root=self.state)
        self.assertTrue(snapshot["edges"])
        self.assertTrue(all(e["label"] == "nämns i" and e["provenance"] == "EXTRACTED"
                            for e in snapshot["edges"]))
        rotor = next(n for n in snapshot["nodes"] if n["label"] == "rotor")
        detail = atlas.detail(rotor["id"], root=self.state)
        self.assertIn("Rotor bearings", detail["passages"][0]["text"])

    def test_bad_inputs_do_not_replace_valid_source(self):
        path = self.inputs / "safe.txt"
        path.write_text("Original readable contents", encoding="utf-8")
        source = self.import_one(path)
        path.write_bytes(b"bad\0binary")
        failed = atlas.import_paths([str(path)], root=self.state)
        self.assertEqual(failed["status"], "ERROR")
        self.assertEqual(atlas.source_page(source["source_id"], root=self.state)["text"], "Original readable contents")
        malformed = self.inputs / "broken.pdf"
        malformed.write_bytes(b"not a PDF")
        self.assertEqual(atlas.import_paths([str(malformed)], root=self.state)["status"], "ERROR")
        self.assertEqual(atlas.import_paths(["https://example.com/anything.pdf"], root=self.state)["reason"], "LOCAL_PATH_REQUIRED")
        self.assertEqual(atlas.import_paths([], root=self.state)["status"], "ERROR")

    def test_limits_refuse_whole_file_without_silent_truncation(self):
        path = self.inputs / "large.txt"
        path.write_text("x" * 101, encoding="utf-8")
        with patch.object(atlas, "MAX_TEXT_CHARS", 100):
            failed = atlas.import_paths([str(path)], root=self.state)
        self.assertEqual(failed["results"][0]["reason"], "TEXT_CHARACTER_LIMIT")
        self.assertEqual(atlas.snapshot(root=self.state)["counts"]["sources"], 0)

    def test_folder_is_bounded_and_skips_private_files(self):
        (self.inputs / "memo.txt").write_text("A rotor report.", encoding="utf-8")
        private = self.inputs / ".ssh"
        private.mkdir()
        (private / "secret.txt").write_text("Must never be imported.", encoding="utf-8")
        result = atlas.import_paths([str(self.inputs)], root=self.state)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(atlas.import_paths([str(private / "secret.txt")], root=self.state)["reason"], "PRIVATE_INPUT_NOT_ALLOWED")
        for index in range(32):
            (self.inputs / f"extra{index}.txt").write_text("Text.", encoding="utf-8")
        result = atlas.import_paths([str(self.inputs)], root=self.state)
        self.assertEqual(result["reason"], "SELECT_A_SMALLER_FOLDER_MAX_32_FILES")

    def test_cancelled_import_has_no_side_effects(self):
        path = self.inputs / "memo.txt"
        path.write_text("Cancel before reading.", encoding="utf-8")
        result = atlas.import_paths([str(path)], root=self.state, cancelled=lambda: True)
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(atlas.snapshot(root=self.state)["counts"]["sources"], 0)

    def test_cancellation_during_extraction_discards_staged_input(self):
        path = self.inputs / "memo.txt"
        path.write_text("Cancel during reading.", encoding="utf-8")
        stop = [False]

        def extract(*args, **kwargs):
            stop[0] = True
            return [{"page": 1, "text": "Cancel during reading.", "width": 0, "height": 0}], []

        with patch.object(atlas, "_extract", side_effect=extract):
            result = atlas.import_paths([str(path)], root=self.state, cancelled=lambda: stop[0])
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(atlas.snapshot(root=self.state)["counts"]["sources"], 0)
        self.assertEqual(list((self.state / "blobs").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
