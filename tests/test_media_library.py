"""MEDIA catalog behavior without external services or user state."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import media_library as library


def metadata(files, **values):
    return {"metadata": dict(identifier="test-series", title="Test Series", mediatype="movies", **values), "files": files}


def video(name, **values):
    return dict({"name": name, "size": "12345", "source": "original"}, **values)


class AnnotationTests(unittest.TestCase):
    def test_comma_episode_convention_requires_unambiguous_separators(self):
        self.assertEqual(library._episode_info("Powerpuff Girls - 01,01 - Insect Inside")[:2], (1, 1))
        for title in ("Patrik 1,5", "Patrik 1.5", "Movie 2001,01", "Date 01,01"):
            self.assertEqual(library._episode_info(title)[:2], (0, 0))
    def test_windows_and_unix_filenames_have_numeric_episode_metadata(self):
        rows = [library.annotate({"kind": "TV", "media": "file", "source": source}) for source in
                (r"C:\Videos\Example\Example.Show.S02E10.1080p.mp4", "/videos/Example/Example Show 2x3.mp4")]
        self.assertEqual((rows[0]["season"], rows[0]["episode"], rows[0]["series_title"]), (2, 10, "Example Show"))
        self.assertEqual((rows[1]["season"], rows[1]["episode"]), (2, 3))
        self.assertEqual([r["episode"] for r in sorted(rows, key=library._row_key)], [3, 10])

    def test_unknown_season_remains_zero_and_uses_parent_series(self):
        row = library.annotate({"source": "/videos/Example/Season 4/episode_03_Mystery.mp4", "media": "file"})
        self.assertEqual(row["content_type"], "episode")
        self.assertEqual((row["season"], row["episode"]), (0, 3))
        self.assertEqual(row["series_title"], "Example")

    def test_vod_is_not_live_and_explicit_metadata_survives(self):
        row = library.annotate({"title": "Film (1940)", "source": "https://archive.org/download/test/film.mp4",
                                "media": "stream", "content_type": "movie", "language": ["swe", "English"], "year": "1940-10-04"})
        self.assertEqual((row["media"], row["is_live"], row["stream"]), ("vod", False, False))
        self.assertEqual(row["language"], "sv; en")
        self.assertEqual(row["year"], 1940)
        self.assertEqual(library.annotate({"source": "https://example.org/live.m3u8", "media": "stream"})["content_type"], "live")

    def test_radio_and_music_are_not_reclassified_as_movies(self):
        for kind in ("MUSIC", "RADIO"):
            row = library.annotate({"kind": kind, "source": "https://example.org/music", "media": "stream"})
            self.assertEqual(row["content_type"], "music")


class ArchiveExpansionTests(unittest.TestCase):
    def test_shared_torrent_or_zip_origin_does_not_collapse_distinct_episodes(self):
        files = []
        for number in (1, 2, 3):
            name = f"Show S01E{number:02}"
            files.extend([video(name + ".mkv", original="whole-show.torrent"),
                          video(name + ".mp4", original=name + ".mkv")])
        rows = self.expand(metadata(files), content_type="series", series_title="Show")
        self.assertEqual([row["episode"] for row in rows], [1, 2, 3])
        self.assertTrue(all(row["archive_file"].endswith(".mp4") for row in rows))
    def expand(self, payload, **row):
        with patch.object(library, "_cached_json", return_value=payload):
            return library.expand_item(dict(archive_id="test-series", **row))

    def test_preferred_mp4_replaces_duplicate_encodings_and_sorts_episodes(self):
        files = [video("Show S02E10.mkv"), video("Show S02E10.mp4", original="Show S02E10.mkv"),
                 video("Show S02E03.mkv"), video("Show S02E03_512kb.mp4", original="Show S02E03.mkv"),
                 video("Show S02E03.mp4", original="Show S02E03.mkv"),
                 video("Show S02E03.ogv", original="Show S02E03.mkv")]
        rows = self.expand(metadata(files, language="swe"), content_type="series", series_title="Show")
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["episode"] for r in rows], [3, 10])
        self.assertTrue(all(r["archive_file"].endswith(".mp4") and "512kb" not in r["archive_file"] for r in rows))
        self.assertTrue(all(r["media"] == "vod" and not r["is_live"] and r["language"] == "sv" for r in rows))
        self.assertEqual(rows[0]["series_id"], rows[1]["series_id"])
        self.assertIn("%20", rows[0]["source"])

    def test_private_preview_thumbnail_unsafe_and_zero_size_files_are_removed(self):
        rows = self.expand(metadata([video("film.mp4"), video("secret.mp4", private="true"),
            video("restricted.mp4", restricted=True), video("film_preview.mp4"), video("film_thumb.mp4"),
            video("../outside.mp4"), video("/absolute.mp4"), video("zero.mp4", size="0")]))
        self.assertEqual([r["archive_file"] for r in rows], ["film.mp4"])
        self.assertEqual(rows[0]["content_type"], "movie")

    def test_restricted_items_never_become_playable(self):
        with self.assertRaisesRegex(RuntimeError, "MEDIA_ARCHIVE_RESTRICTED"):
            self.expand(metadata([video("film.mp4")], **{"access-restricted-item": "true"}))
        payload = metadata([video("film.mp4")])
        payload["is_dark"] = True
        with self.assertRaisesRegex(RuntimeError, "MEDIA_ARCHIVE_RESTRICTED"):
            self.expand(payload)

    def test_unnumbered_collection_has_no_invented_seasons_or_episodes(self):
        rows = self.expand(metadata([video("Cartoon 10.mp4"), video("Cartoon 2.mp4")]), content_type="series")
        self.assertEqual([r["title"] for r in rows], ["Cartoon 2", "Cartoon 10"])
        self.assertTrue(all(r["season"] == r["episode"] == 0 for r in rows))

    def test_literal_rights_metadata_is_kept_without_inference(self):
        rows = self.expand(metadata([video("film.mp4")], rights="Uploader-supplied statement", licenseurl="https://example.org/license"))
        self.assertEqual(rows[0]["rights"], "Uploader-supplied statement")
        self.assertEqual(rows[0]["licenseurl"], "https://example.org/license")
        self.assertEqual(self.expand(metadata([video("film.mp4")]))[0]["rights"], "")

    def test_direct_file_resolution_is_fast_and_preserves_selection(self):
        row = {"id": "tv:test", "archive_id": "test-series", "archive_file": "Film S01E01.mp4",
               "source": "https://archive.org/download/test-series/Film%20S01E01.mp4", "content_type": "episode"}
        with patch.object(library, "_cached_json", side_effect=AssertionError("network must not run")):
            resolved = library.resolve_item(row)
        self.assertEqual(resolved["id"], "tv:test")
        bad = dict(row, source="https://archive.org/download/other/film.mp4")
        with self.assertRaisesRegex(ValueError, "MEDIA_ARCHIVE_SOURCE_INVALID"):
            library.resolve_item(bad)

    def test_series_resolution_requires_episode_choice(self):
        choices = self.expand(metadata([video("A.mp4"), video("B.mp4")]), content_type="series")
        with patch.object(library, "expand_item", return_value=choices):
            with self.assertRaisesRegex(RuntimeError, "MEDIA_ARCHIVE_CHOOSE_EPISODE"):
                library.resolve_item({"id": "archive:test-series", "archive_id": "test-series", "content_type": "series"})

    def test_ambiguous_descriptor_never_silently_plays_first_episode(self):
        choices = self.expand(metadata([video("Show S01E01.mp4"), video("Show S01E02.mp4")]))
        with patch.object(library, "expand_item", return_value=choices):
            with self.assertRaisesRegex(RuntimeError, "MEDIA_ARCHIVE_CHOOSE_EPISODE"):
                library.resolve_item({"id": "archive:test-series", "archive_id": "test-series", "content_type": "movie"})

    def test_alternate_movie_versions_do_not_become_fictitious_series(self):
        rows = self.expand(metadata([video("Film-restored.mp4", length="5400"),
            video("Film-old.avi", length="5395"), video("Interview.mp4", length="600")]), content_type="movie")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content_type"], "movie")
        self.assertEqual(rows[0]["archive_file"], "Film-restored.mp4")

    def test_nested_archive_folders_do_not_appear_in_episode_titles(self):
        rows = self.expand(metadata([video("Season 2/Show S02E03 - Mystery.mp4")]), content_type="series", series_title="Show")
        self.assertEqual(rows[0]["title"], "Show S02E03 - Mystery")
        self.assertEqual(rows[0]["episode_title"], "Mystery")
        self.assertEqual(rows[0]["season"], 2)

    def test_invalid_identifier_cannot_become_a_metadata_request(self):
        with patch.object(library, "_cached_json", side_effect=AssertionError("request must not run")):
            with self.assertRaisesRegex(ValueError, "MEDIA_ARCHIVE_ID_INVALID"):
                library.expand_item({"archive_id": "../other"})


class ArchiveCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.directory = patch.object(library, "_cache_dir", return_value=self.root)
        self.directory.start()
        self.payload = {"response": {"numFound": 1, "docs": [{"identifier": "found", "title": "Found"}]}}
        self.url = "https://archive.org/advancedsearch.php?test=1"

    def tearDown(self):
        self.directory.stop()
        self.temporary.cleanup()

    def test_valid_cache_is_atomic_and_fresh_cache_avoids_network(self):
        with patch.object(library, "_download_json", return_value=self.payload) as download:
            self.assertEqual(library._cached_json(self.url, library._valid_search), self.payload)
            self.assertEqual(library._cached_json(self.url, library._valid_search), self.payload)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(len(list(self.root.glob("*.json"))), 1)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_timeout_and_malformed_refresh_use_last_valid_stale_catalog(self):
        with patch.object(library, "_download_json", return_value=self.payload):
            library._cached_json(self.url, library._valid_search)
        path = next(self.root.glob("*.json"))
        os.utime(path, (time.time() - library.CACHE_TTL - 20,) * 2)
        for replacement in (TimeoutError("timeout"), {"wrong": "schema"}):
            with patch.object(library, "_download_json", **({"side_effect": replacement} if isinstance(replacement, Exception) else {"return_value": replacement})):
                self.assertEqual(library._cached_json(self.url, library._valid_search), self.payload)
        self.assertEqual(json.loads(path.read_text())["payload"], self.payload)

    def test_invalid_response_without_cache_reports_service_error(self):
        with patch.object(library, "_download_json", return_value={"unexpected": True}):
            with self.assertRaisesRegex(RuntimeError, "MEDIA_ARCHIVE_UNAVAILABLE"):
                library._cached_json(self.url, library._valid_search)
        self.assertFalse(list(self.root.iterdir()))

    def test_search_is_bounded_quoted_and_returns_resolvable_descriptors(self):
        payload = {"response": {"numFound": 3, "docs": [
            {"identifier": "tmht", "title": "Teenage Mutant Hero Turtles Media Dubb", "language": "swe"},
            {"identifier": "tv-show", "title": "Example Complete Series"}, {"identifier": "../bad", "title": "Bad"}]}}
        with patch.object(library, "_cached_json", return_value=payload) as get:
            rows = library.search_archive('TMNT MediaDubb svenska ":*', 99999)
        query = parse_qs(urlsplit(get.call_args.args[0]).query)
        self.assertEqual(query["rows"], [str(library.MAX_SEARCH)])
        self.assertIn('title:"turtles"', query["q"][0])
        self.assertIn('description:"media dubb"', query["q"][0])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["language"], "sv")
        self.assertEqual(rows[1]["content_type"], "series")
        self.assertTrue(all(not row["playable"] and row["source_page"].startswith("https://archive.org/details/") for row in rows))

    def test_provider_rejects_non_archive_and_oversized_responses(self):
        with self.assertRaisesRegex(ValueError, "MEDIA_ARCHIVE_SOURCE_INVALID"):
            library._download_json("https://example.org/metadata/x")
        response = io.BytesIO(b"x" * (library.MAX_RESPONSE_BYTES + 1))
        response.geturl = lambda: "https://archive.org/metadata/x"
        with patch.object(library.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "MEDIA_ARCHIVE_RESPONSE_TOO_LARGE"):
                library._download_json("https://archive.org/metadata/x")


class BundledLibraryTests(unittest.TestCase):
    def test_starter_is_ready_without_network_with_real_episode_metadata(self):
        with patch.object(library, "_download_json", side_effect=AssertionError("network must not run")):
            rows = library.starter_catalog()
        self.assertGreaterEqual(len(rows), 100)
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        self.assertTrue(any(row["content_type"] == "series" for row in rows))
        self.assertTrue(any(row["content_type"] == "movie" for row in rows))
        turtles = [row for row in rows if row.get("archive_id") == "teenage-mutant-hero-turtles-media-dubb" and row.get("playable")]
        self.assertGreater(len(turtles), 10)
        self.assertTrue(all(row["language"] == "sv" and row["season"] > 0 and row["episode"] > 0 and not row["is_live"] for row in turtles))
        for row in rows:
            if row.get("playable"):
                self.assertEqual(library.resolve_item(row)["source"], row["source"])


if __name__ == "__main__":
    unittest.main()
