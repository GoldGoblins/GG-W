"""Swedish curation has real file descriptors and usable series identities."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import media_library
from backend.media_index import MediaIndex, view_request


class SwedishLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = json.loads((PROJECT / "config/media-library-sv.json").read_text(encoding="utf-8"))
        cls.rows = cls.pack["items"]

    def test_cached_video_files_resolve_without_metadata_network_requests(self):
        identifiers = [row["id"] for row in self.rows]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        videos = [row for row in self.rows if row["content_type"] in ("episode", "movie")]
        self.assertTrue(videos)
        with patch.object(media_library, "expand_item", side_effect=AssertionError("Bundled file fetched metadata")):
            for row in videos:
                with self.subTest(identifier=row["id"]):
                    self.assertEqual(row["language"], "sv")
                    self.assertGreater(row["duration"], 300)
                    self.assertTrue(row["archive_file"].endswith(".mp4"))
                    self.assertEqual(row["source_page"], "https://archive.org/details/" + row["archive_id"])
                    resolved = media_library.resolve_item(row)
                    self.assertEqual(resolved["source"], row["source"])

    def test_segemyhr_seasons_are_one_series_with_numbered_cached_episodes(self):
        with tempfile.TemporaryDirectory(prefix="gg-svenskt-index-") as temporary:
            index = MediaIndex(Path(temporary) / "media.sqlite3")
            index.initialize()
            index.ingest(self.rows)
            # These are candidate metadata, so inspect their saved identities
            # without manufacturing playback proofs to bypass browse health.
            with index.connection() as db:
                series = db.execute("SELECT group_key,title FROM items WHERE type='series' "
                                    "AND title='c/o Segemyhr' GROUP BY group_key").fetchall()
                self.assertEqual(len(series), 1)
                collection = series[0]["group_key"]
                episodes = db.execute("SELECT season,episode FROM items WHERE type='episode' "
                                      "AND parent_key=? GROUP BY group_key ORDER BY season,episode",
                                      (collection,)).fetchall()
            self.assertEqual(len(episodes), 58)
            self.assertEqual(sorted({row["season"] for row in episodes}), [1, 2, 3, 4, 5])
            numbered = [(row["season"], row["episode"]) for row in episodes]
            self.assertEqual(numbered, sorted(set(numbered)))
            self.assertEqual(sum(row["season"] == 3 for row in episodes), 12)

    def test_unknown_seasons_remain_explicit_and_pistvakt_order_has_a_source(self):
        for row in self.rows:
            if row["content_type"] != "episode":
                continue
            if row.get("series_title") in ("Hipp hipp!", "Kvarteret Skatan"):
                self.assertEqual(row["season"], 0)
                self.assertTrue(row.get("source_note"))
            if row.get("series_title") == "Pistvakt":
                self.assertTrue(row["episode_metadata_source"].startswith("https://www.svtplay.se/pistvakt"))
                self.assertIn(row["season"], (1, 2))
                self.assertIn(row["episode"], range(1, 7))


if __name__ == "__main__":
    unittest.main()
