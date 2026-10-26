"""Swedish nostalgia rows stage actual programme files without claiming health."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import media_library
from backend.media_health_audit import prepare_identity
from backend.media_index import MediaIndex, view_request


class SwedishNostalgiaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = PROJECT / "config/media-library-nostalgia-sv.json"
        cls.pack = json.loads(cls.path.read_text(encoding="utf-8"))
        cls.rows = cls.pack["items"]

    def test_direct_files_match_saved_provider_evidence_and_resolve_without_network(self):
        self.assertEqual(self.pack["schema"], "gg.media.library.v1")
        self.assertNotIn("\ufffd", self.path.read_text(encoding="utf-8"))
        identifiers = [row["id"] for row in self.rows]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        sources = [row["source"] for row in self.rows]
        self.assertEqual(len(sources), len(set(sources)))
        with patch.object(media_library, "_download_json", side_effect=AssertionError("Unexpected network")):
            for row in self.rows:
                if not row.get("archive_file"):
                    continue
                with self.subTest(title=row["title"]):
                    evidence = self.pack["metadata_evidence"][row["archive_id"]]
                    entry = next(file for file in evidence["files"] if file["name"] == row["archive_file"])
                    self.assertTrue(media_library._file_allowed(entry))
                    self.assertEqual(row["bytes"], int(entry["size"]))
                    self.assertEqual(row["duration"], float(entry["length"]))
                    expected = "https://archive.org/download/" + quote(row["archive_id"], safe="") + "/" + quote(row["archive_file"], safe="/")
                    self.assertEqual(row["source"], expected)
                    self.assertEqual(media_library.resolve_item(row)["source"], expected)
                    self.assertGreater(row["duration"], 600)

    def test_identity_checker_accepts_actual_provider_snapshots_without_fabricated_fields(self):
        def metadata(url, validate):
            identifier = url.rsplit("/", 1)[1]
            payload = self.pack["metadata_evidence"][identifier]
            self.assertTrue(validate(payload))
            return payload
        with patch.object(media_library, "_cached_json", side_effect=metadata):
            for row in self.rows:
                with self.subTest(title=row["title"]):
                    prepared, result = prepare_identity(row)
                    self.assertEqual(result["status"], "consistent")
                    self.assertEqual(prepared["source"], row["source"])

    def test_numbered_series_have_one_encoding_per_episode_and_unknown_parts_stay_unknown(self):
        episodes = [row for row in self.rows if row.get("series_title") == "Tusenbr\u00f6der" and row["content_type"] == "episode"]
        self.assertEqual(len(episodes), 10)
        self.assertEqual({(row["season"], row["episode"]) for row in episodes},
                         {(season, episode) for season in (1, 2) for episode in range(1, 6)})
        for row in self.rows:
            if row.get("series_title", "").startswith("Wallander:") or row.get("series_title") == "Bj\u00f6rnes magasin":
                self.assertEqual((row["season"], row["episode"]), (0, 0))
            if row.get("series_title") == "Trazan och Banarne":
                self.assertEqual(row["season"], 0)

    def test_full_features_exclude_split_discs_archives_clips_and_out_of_period_titles(self):
        movies = [row for row in self.rows if row["content_type"] == "movie"]
        self.assertEqual(len(movies), 16)
        self.assertGreaterEqual(len({row["category"] for row in movies}), 5)
        for row in movies:
            with self.subTest(title=row["title"]):
                self.assertTrue(1980 <= row["year"] <= 2009)
                self.assertFalse(re.search(r"(?i)\b(?:cd0?[12]|part[ ._-]*[12]|trailer|teaser|preview)\b", row["archive_file"]))
        excluded = {row["title"] for row in self.pack["excluded_candidates"]}
        self.assertIn("Svensson, Svensson - filmen", excluded)
        self.assertIn("Mio min Mio", excluded)
        self.assertFalse(any(row["title"] in excluded for row in self.rows))

    def test_metadata_import_never_counts_as_approved_playback(self):
        self.assertTrue(all(row.get("availability") == "metadata" and row.get("playable") is False for row in self.rows))
        with tempfile.TemporaryDirectory(prefix="gg-nostalgia-sv-test-") as temporary:
            index = MediaIndex(Path(temporary) / "library.sqlite3")
            index.initialize()
            index.ingest(self.rows)
            for page in ("movies", "series", "live"):
                self.assertEqual(index.browse(view_request(page))["library_total"], 0)
            with index.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM items WHERE status='verified'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
