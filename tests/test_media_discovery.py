"""Candidate keyset import conformance, cancellation and honest group counts."""
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import media_discovery as discovery
from backend.media_index import MediaIndex


def document(identifier, title="A Film", **metadata):
    return dict(identifier=identifier, title=title, year=1940, mediatype="movies", language="eng", **metadata)


def response(query, docs, total=100000):
    return {"responseHeader": {"params": {"qin": query}}, "response": {"start": 0, "numFound": total, "docs": docs}}


def query_of(url):
    return parse_qs(urlsplit(url).query)["q"][0]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.index = MediaIndex(Path(self.temporary.name) / "index.sqlite3")
        self.index.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def checkpoint(self, page="movies"):
        import hashlib
        from backend.media_languages import archive_clause
        signature = hashlib.sha256((discovery.QUERIES[page] + " AND " + archive_clause()).encode()).hexdigest()[:16]
        return self.index.meta("discovery_last_" + page + "_" + signature)

    def test_keyset_advances_with_zero_offset_past_deep_paging_boundary(self):
        calls = []
        def provider(url, validate):
            query = query_of(url)
            calls.append(query)
            docs = [document("z10001", "Film One")] if len(calls) == 1 else [document("z10002", "Film Two")]
            payload = response(query, docs)
            self.assertTrue(validate(payload))
            return payload
        with patch.object(discovery.library, "_cached_json", side_effect=provider):
            result = discovery.discover(self.index, "movies", max_pages=2)
        self.assertIn('identifier:{"z10001" TO *}', calls[1])
        self.assertEqual(self.checkpoint(), "z10002")
        self.assertEqual((result["candidates_imported"], result["provider_calls"]), (2, 2))
        with self.index.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items WHERE status='verified'").fetchone()[0], 0)

    def test_wrong_query_cache_response_never_ingests_or_advances(self):
        payload = response("wrong provider query", [document("a001")])
        with patch.object(discovery.library, "_cached_json", return_value=payload):
            result = discovery.discover(self.index, "movies", max_pages=1)
        self.assertEqual(result["error"], "provider_page_mismatch")
        self.assertEqual(result["candidates_imported"], 0)
        self.assertEqual(self.checkpoint(), "")

    def test_rediscovery_does_not_downgrade_a_checked_resolved_movie_to_a_descriptor(self):
        doc = document("a001", "A Film")
        row = discovery._candidate(doc, "movies")
        row.update(source="https://archive.org/download/a001/A%20Film.mp4", archive_file="A Film.mp4")
        self.index.ingest([row])
        now = time.time()
        self.index.record(row["id"], dict(status="verified", checked_at=now, expires_at=now + 600))
        with patch.object(discovery.library, "_cached_json", side_effect=lambda url, validate:
                          response(query_of(url), [doc], total=1)):
            discovery.discover(self.index, "movies", max_pages=1)
        self.assertEqual(self.index.get(row["id"])["source"], row["source"])
        self.assertTrue(self.index.is_verified(row["id"]))

    def test_failure_keeps_successful_checkpoint_and_retry_budget_is_bounded(self):
        count = 0
        def provider(url, validate):
            nonlocal count
            count += 1
            if count > 1:
                raise TimeoutError("provider diagnostic")
            return response(query_of(url), [document("a001")])
        with patch.object(discovery.library, "_cached_json", side_effect=provider):
            result = discovery.discover(self.index, "movies", max_pages=64)
        self.assertEqual(self.checkpoint(), "a001")
        self.assertEqual((count, result["provider_calls"]), (3, 3))
        self.assertEqual(result["error"], "provider_unavailable")

    def test_cancel_before_and_after_response_preserves_cursor(self):
        event = threading.Event()
        event.set()
        with patch.object(discovery.library, "_cached_json") as provider:
            result = discovery.discover(self.index, "series", cancel=event)
        provider.assert_not_called()
        self.assertTrue(result["cancelled"])
        event.clear()
        def late_cancel(url, validate):
            event.set()
            return response(query_of(url), [document("a001", "A Show Complete Series")])
        with patch.object(discovery.library, "_cached_json", side_effect=late_cancel):
            discovery.discover(self.index, "series", cancel=event)
        self.assertEqual(self.checkpoint("series"), "")

    def test_duplicate_encodes_and_seasons_do_not_count_as_new_groups(self):
        def movies(url, validate):
            return response(query_of(url), [document("a001", "A Film HD"), document("a002", "A Film (1080p)")], total=2)
        with patch.object(discovery.library, "_cached_json", side_effect=movies):
            result = discovery.discover(self.index, "movies", max_pages=1)
        self.assertEqual((result["candidates_imported"], result["staged_uploads"]), (1, 2))
        def series(url, validate):
            return response(query_of(url), [document("s001", "A Show Season 1"), document("s002", "A Show Season 2"),
                document("s003", "A Show S01E01 - The Pilot"), document("s004", "Twitch gameplay Season 1")], total=4)
        with patch.object(discovery.library, "_cached_json", side_effect=series):
            result = discovery.discover(self.index, "series", max_pages=1)
        self.assertEqual(result["candidates_imported"], 1)
        self.assertEqual(result["staged_uploads"], 3)

    def test_real_tv_title_forms_are_grouped_without_losing_literal_provider_identity(self):
        cases = [
            ("Blue's Clues - Full Series", "Blue's Clues"),
            ("My Little Pony: Friendship is Magic - Full Series", "My Little Pony: Friendship is Magic"),
            ("Masterchef India Season 6", "Masterchef India"),
            ("Kera Sakti Season 2 - Bahasa Indonesia", "Kera Sakti"),
            ("RWBY (S01 - S09 / 1080p)", "RWBY"),
            ("The Boondocks S01 S02 1080p DVD Upscale", "The Boondocks"),
            ("Rederiet Säsong 3", "Rederiet"),
            ("Rederiet Säsonger 1-3", "Rederiet"),
            ("Get Smart", "Get Smart"),
        ]
        for number, (title, expected) in enumerate(cases):
            with self.subTest(title=title):
                row = discovery._candidate(document("tv-" + str(number), title), "series")
                self.assertIsNotNone(row)
                self.assertEqual((row["content_type"], row["title"], row["series_title"]),
                                 ("series", expected, expected))
                self.assertEqual(row["archive_title"], title)
                self.assertFalse(row["playable"])

    def test_valid_tv_collections_and_anthology_shows_are_not_rejected_by_generic_words(self):
        for title, subject, expected in [
            ("Digimon Tamers - The Complete Collection", ["Anime", "TV series"], "Digimon Tamers"),
            ("Tom and Jerry Cartoons Complete Collection (1940-2007)", ["Cartoons"], "Tom and Jerry Cartoons"),
            ("Disney anthology television series", ["Television"], "Disney anthology"),
        ]:
            with self.subTest(title=title):
                row = discovery._candidate(document("tv-collection", title, subject=subject), "series")
                self.assertIsNotNone(row)
                self.assertEqual((row["content_type"], row["title"]), ("series", expected))
                self.assertEqual(row["archive_title"], title)

    def test_bare_episode_uploads_unrelated_film_batches_and_gameplay_do_not_inflate_tv_groups(self):
        for title in ("s01e01_360", "s01e03_360", "Episode 2", "James Bond Complete Collection",
                      "A horror anthology collection", "Twitch gameplay Season 2", "Season of the Witch"):
            with self.subTest(title=title):
                self.assertIsNone(discovery._candidate(document("not-series", title), "series"))
        named = discovery._candidate(document("named-episode", "S01E03 - Pilot", series="The actual show"), "series")
        self.assertEqual((named["content_type"], named["series_title"]), ("episode", "The actual show"))

    def test_named_recorded_episodes_survive_format_labels_without_admitting_loose_tapes_or_ads(self):
        recorded = discovery._candidate(document("recorded-show", "Actual Show S01E01 WOC VHS recording"), "series")
        self.assertIsNotNone(recorded)
        self.assertEqual((recorded["content_type"], recorded["series_title"], recorded["season"], recorded["episode"]),
                         ("episode", "Actual Show", 1, 1))
        complete = discovery._candidate(document("recorded-series", "Actual Show Full Series VHS tapes"), "series")
        self.assertEqual((complete["content_type"], complete["title"]), ("series", "Actual Show"))
        known = discovery._candidate(document("recorded-metadata", "Old WOC recording", series="Actual Show"), "series")
        self.assertEqual((known["content_type"], known["title"]), ("series", "Actual Show"))
        for title in ("Saturday Morning VHS Tape", "Saturday Morning VHS Tape Season 1", "VHS S01E01",
                      "Actual Show S01E01 commercials compilation", "Saturday Morning S01E01 continuity", "TV Show gameplay S01E01"):
            with self.subTest(title=title):
                self.assertIsNone(discovery._candidate(document("loose-recording", title), "series"))

    def test_repeated_cursor_or_wrong_offset_and_duplicate_ids_are_rejected(self):
        query = discovery.QUERIES["movies"]
        self.assertFalse(discovery._valid(response(query, [document("a001")]), query=query, after="a001"))
        self.assertFalse(discovery._valid(response(query, [document("a001"), document("a001")]), query=query))
        payload = response(query, [document("a001")])
        payload["response"]["start"] = 10000
        self.assertFalse(discovery._valid(payload, query=query))

    def test_source_exhaustion_is_reported_without_an_arbitrary_title_target(self):
        with patch.object(discovery.library, "_cached_json", side_effect=lambda url, validate: response(query_of(url), [], total=0)):
            result = discovery.discover(self.index, "series", max_pages=1)
        self.assertTrue(result["source_exhausted"])
        self.assertFalse(result["more_sources"])
        self.assertIsNone(result["catalog_limit"])
        self.assertNotIn("target_reached", result)

    def test_discovery_continues_past_the_former_movie_and_series_limits(self):
        # Large existing inventories must not prevent requesting the next page.
        self.index.ingest([dict(id=f"existing-{kind}-{number}", kind="TV", content_type=kind,
                                title=f"Existing {kind} {number}", source="https://example.invalid/media.mp4")
                           for kind in ("movie", "series") for number in range(12000)])
        for page in ("movies", "series"):
            title = "Another film" if page == "movies" else "Another show Complete Series"
            with patch.object(discovery.library, "_cached_json", side_effect=lambda url, validate:
                              response(query_of(url), [document("next-" + page, title)])) as provider:
                result = discovery.discover(self.index, page, max_pages=1)
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(result["provider_calls"], 1)
            self.assertEqual(result["candidates_imported"], 12001)
            self.assertIsNone(result["catalog_limit"])

    def test_absolute_request_cap_includes_retries_and_zero_does_no_work(self):
        count = 0
        def provider(url, validate):
            nonlocal count
            count += 1
            return response(query_of(url), [document(f"a{count:05d}", f"Film {count}")])
        with patch.object(discovery.library, "_cached_json", side_effect=provider):
            discovery.discover(self.index, "movies", max_pages=0)
            result = discovery.discover(self.index, "movies", max_pages=100000)
        self.assertEqual(count, 64)
        self.assertEqual(result["provider_calls"], 64)


if __name__ == "__main__":
    unittest.main()
