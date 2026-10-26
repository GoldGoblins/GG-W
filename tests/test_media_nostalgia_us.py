"""Curated US nostalgia contains real programme-file contracts, never proofs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import media_library as library
from backend.media_health_audit import check_identity
from backend.media_index import MediaIndex, view_request

BUNDLE = PROJECT / "config" / "media-library-nostalgia-us.json"


class AmericanNostalgiaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
        cls.rows = cls.payload["items"]

    def test_broad_programme_coverage_stays_within_the_requested_era(self):
        self.assertEqual(self.payload["schema"], "gg.media.library.v1")
        self.assertGreater(len(self.rows), 1200)
        shows = {row["series_title"] for row in self.rows if row["content_type"] == "episode"}
        self.assertGreaterEqual(len(shows), 25)
        self.assertTrue({"Malcolm in the Middle", "Twin Peaks", "Animaniacs", "The Powerpuff Girls",
                         "Buffy", "Darkwing Duck", "Married... with Children"} <= shows)
        films = {row["title"] for row in self.rows if row["content_type"] == "movie"}
        self.assertGreaterEqual(len(films), 20)
        self.assertTrue({"Ghostbusters", "The Terminator", "Goodfellas", "The Shawshank Redemption",
                         "The Breakfast Club", "The Incredibles", "Poltergeist", "Saving Private Ryan"} <= films)
        self.assertGreaterEqual(len({row["category"] for row in self.rows}), 10)
        self.assertTrue(all(1980 <= row["year"] <= 2009 for row in self.rows))
        self.assertLess(BUNDLE.stat().st_size, library.MAX_SEED_BYTES)

    def test_exact_public_files_are_unique_and_do_not_overlap_older_bundles(self):
        self.assertEqual(len({row["id"] for row in self.rows}), len(self.rows))
        self.assertEqual(len({row["source"] for row in self.rows}), len(self.rows))
        earlier = set()
        for name in ("media-library.json", "media-library-sv.json"):
            earlier.update(row.get("source") for row in json.loads((PROJECT / "config" / name).read_text(encoding="utf-8"))["items"])
        for row in self.rows:
            source = "https://archive.org/download/" + quote(row["archive_id"], safe="") + "/" + quote(row["archive_file"], safe="/")
            self.assertEqual(row["source"], source)
            self.assertNotIn(source, earlier)
            self.assertEqual(row["id"], "tv:" + hashlib.sha256(source.encode()).hexdigest()[:16])
            self.assertTrue(library._IDENTIFIER.fullmatch(row["archive_id"]))
            self.assertTrue(library._file_allowed(dict(name=row["archive_file"], size=row["bytes"])))
            self.assertGreater(row["bytes"], 0)
            self.assertEqual(urlsplit(source).netloc, "archive.org")

    def test_clips_bonus_discs_and_unavailable_search_hits_are_not_films(self):
        films = [row for row in self.rows if row["content_type"] == "movie"]
        self.assertTrue(all(3600 <= row["duration"] <= 15000 for row in films))
        self.assertFalse(any(re.search(r"(?i)(?:^|[/_. -])(?:extras?|trailers?|preview|opening|featurettes?)(?:[/_. -]|$)",
                                       row["archive_file"]) for row in films))
        identifiers = {row["archive_id"] for row in self.rows}
        # These actual search hits had only trailers/clips, no full public file,
        # or one long mixed recording with several unrelated programmes.
        self.assertTrue({"jurassic-park-1993_202108", "turner_video_2797", "DirtyDancingHD",
                         "s-01-e-01-the-one-where-monica-gets-a-roommate", "vts-01-1_20240103_1748"}.isdisjoint(identifiers))
        batman = [row for row in self.rows if row.get("series_title") == "Batman: The Animated Series"]
        self.assertEqual(len(batman), 3)  # Upstream says "Full Series" but only three files exist.

    def test_numbering_uses_source_evidence_and_container_originals_do_not_collapse_a_show(self):
        married = [row for row in self.rows if row.get("series_title") == "Married... with Children"]
        self.assertEqual(len(married), 260)
        self.assertEqual({row["season"] for row in married if row["season"]}, set(range(1, 12)))
        powerpuff = [row for row in self.rows if row.get("series_title") == "The Powerpuff Girls"]
        self.assertEqual({row["season"] for row in powerpuff}, set(range(1, 7)))
        first = next(row for row in powerpuff if (row["season"], row["episode"]) == (1, 1))
        self.assertIn("01,01", first["archive_file"])
        self.assertEqual(library._episode_info(first["archive_file"])[:2], (1, 1))
        xmen = [row for row in self.rows if row.get("series_title") == "X-Men: The Animated Series"]
        self.assertTrue(all(row["season"] == 0 for row in xmen))
        self.assertEqual({row["episode"] for row in xmen}, set(range(1, 77)))
        for row in self.rows:
            if row["content_type"] != "episode" or not row["episode"]:
                continue
            season, episode, _, _ = library._episode_info(row["archive_file"])
            self.assertEqual(episode, row["episode"], row["archive_file"])
            if season:
                self.assertEqual(season, row["season"], row["archive_file"])

    def test_representative_identity_contracts_match_literal_provider_file_metadata(self):
        for programme in ("The Powerpuff Girls", "Married... with Children", "Twin Peaks", "Malcolm in the Middle"):
            row = next(row for row in self.rows if row.get("series_title") == programme and row["episode"])
            payload = dict(metadata=dict(identifier=row["archive_id"], title=row["archive_title"], language=row["language"]),
                           files=[dict(name=row["archive_file"], size=str(row["bytes"]), length=str(row["duration"]))])
            with patch.object(library, "_cached_json", return_value=payload):
                result = check_identity(row)
            self.assertEqual(result["status"], "consistent", (programme, result))

    def test_metadata_bundle_cannot_admit_itself_into_the_playable_library(self):
        self.assertFalse(self.payload["source_contract"]["playback_verified"])
        self.assertTrue(all(row["availability"] == "metadata" and row["playable"] is False for row in self.rows))
        with tempfile.TemporaryDirectory(prefix="gg-us-nostalgia-") as temporary:
            index = MediaIndex(Path(temporary) / "library.sqlite3")
            index.initialize()
            with patch.object(library, "_download_json", side_effect=AssertionError("Unexpected source I/O")):
                self.assertEqual(index.ingest(self.rows), len(self.rows))
                self.assertEqual(index.browse(view_request("movies"))["library_total"], 0)
                self.assertEqual(index.browse(view_request("series"))["library_total"], 0)


if __name__ == "__main__":
    unittest.main()
