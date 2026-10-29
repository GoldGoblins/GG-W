"""Game row diagnostics use real isolated ROM resources and existing guards."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import media_contract as contract, media_diagnostics as diagnostics
from backend.media_index import MediaIndex, view_request


class GameDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gg-game-diagnostic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.enterContext(patch.object(contract, "library_roots", return_value=[self.library]))
        self.enterContext(patch.object(diagnostics.quick, "quick_check",
                                       side_effect=AssertionError("Game diagnostics used an audio/video check")))
        self.index = MediaIndex(self.root / "catalog.sqlite3")
        self.index.initialize()

    def game(self, filename="sample.nes", *, title="Sample game"):
        path = self.library / filename
        path.write_bytes(b"NES\x1a" + bytes(32))
        rows = contract.game_catalog()
        row = next(row for row in rows if row["source"] == str(path))
        row.update(title=title, language="en")
        self.index.ingest([row])
        return row, path

    def test_readable_catalog_rom_is_available_without_claiming_emulator_playback(self):
        row, _ = self.game()
        report = diagnostics.diagnose(self.index, row["id"])
        self.assertEqual(report["status"], "verified")
        self.assertTrue(self.index.is_verified(row["id"]))
        self.assertIn("Spelfilen är tillgänglig", report["message"])
        self.assertIn("verifierar inte", report["message"])
        self.assertFalse(report["replacement_id"])

    def test_missing_rom_can_use_a_saved_alternative_and_hide_undo_still_applies(self):
        broken, path = self.game("missing.nes")
        replacement, _ = self.game("alternative.nes")
        path.unlink()
        report = diagnostics.diagnose(self.index, broken["id"])
        self.assertEqual(report["status"], "failed")
        self.assertIn("Filen finns inte längre", report["message"])
        self.assertEqual(report["replacement_id"], replacement["id"])
        self.assertTrue(self.index.is_verified(replacement["id"]))
        self.index.hide_source(broken["id"])
        self.assertEqual(self.index.browse(view_request("games"))["library_total"], 0)
        self.index.hide_source(broken["id"], hidden=False)
        self.assertEqual(self.index.browse(view_request("games"))["library_total"], 1)

    def test_path_outside_the_library_never_reaches_the_resource_checker(self):
        row, _ = self.game()
        outside = self.root / "outside.nes"
        outside.write_bytes(b"NES\x1a" + bytes(32))
        self.index.ingest([dict(row, source=str(outside))])
        with patch.object(diagnostics.existing, "_game_check", side_effect=AssertionError("Read outside library")):
            report = diagnostics.diagnose(self.index, row["id"])
        self.assertEqual(report["status"], "unknown")
        self.assertFalse(self.index.is_verified(row["id"]))

    def test_wrong_extension_for_the_declared_system_is_not_verified(self):
        row, _ = self.game()
        wrong = self.library / "sample.exe"
        wrong.write_bytes(b"not a ROM")
        self.index.ingest([dict(row, source=str(wrong))])
        with patch.object(diagnostics.existing, "_game_check", side_effect=AssertionError("Read unsupported game format")):
            report = diagnostics.diagnose(self.index, row["id"])
        self.assertEqual(report["status"], "failed")
        self.assertIn("Spelfilens format", report["message"])
        self.assertFalse(self.index.is_verified(row["id"]))

    def test_a_changed_game_source_cannot_inherit_the_diagnostic_result(self):
        row, _ = self.game()
        check = diagnostics.existing._game_check

        def replace_during_check(candidate, cancel):
            report = check(candidate, cancel)
            self.index.ingest([dict(candidate, source=str(self.library / "new.nes"))])
            return report

        with patch.object(diagnostics.existing, "_game_check", side_effect=replace_during_check):
            report = diagnostics.diagnose(self.index, row["id"])
        self.assertEqual(report["status"], "unknown")
        self.assertIn("Källan ändrades", report["message"])
        self.assertFalse(self.index.is_verified(row["id"]))


if __name__ == "__main__":
    unittest.main()
