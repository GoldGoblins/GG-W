"""Known MEDIA metadata is paged without retrieval during browsing."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.media_index import (MediaIndex, view_request, LIVE_CATALOG_RETENTION_SECONDS,
                                 VOD_CATALOG_RETENTION_SECONDS)
from backend.media_browse_session import BrowseSession, SnapshotInvalid


def item(identifier, title, content_type="movie", **values):
    return dict(id=identifier, kind="TV", title=title, content_type=content_type,
                media="vod", source="https://example.invalid/" + identifier + ".mp4", **values)


class SavedCatalogueIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-media-inventory-")
        self.index = MediaIndex(Path(self.temporary.name) / "inventory.sqlite3")
        self.index.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def healthy(self, rows):
        self.index.ingest(rows)
        for row in rows:
            self.index.record(row["id"], dict(status="verified", checked_at=time.time(), expires_at=time.time() + 100,
                                               evidence={"video_frames": 3, "audio_frames": 2}))

    def test_radio_and_local_music_metadata_are_browsable_without_fabricated_proofs(self):
        rows = [dict(id="station", kind="RADIO", title="Alpha radio", media="stream",
                     source="https://example.invalid/radio.mp3"),
                dict(id="track", kind="MUSIC", title="Alpha song", media="file",
                     source="C:/Music/Alpha song.flac", artist="Example artist", album="Example album"),
                item("unchecked-video", "Unchecked video"),
                dict(item("unchecked-download", "Unchecked download"), kind="FETCH")]
        self.index.ingest(rows)
        for page, identifier in (("radio", "station"), ("music", "track")):
            with self.subTest(page=page):
                result = self.index.browse(view_request(page))
                self.assertEqual(result["library_total"], 1)
                self.assertEqual(result["items"][0]["id"], identifier)
                self.assertEqual(result["items"][0]["availability"], "unknown")
                self.assertFalse(result["items"][0]["availability_fresh"])
                self.assertEqual(result["items"][0]["availability_scope"], "metadata")
                self.assertFalse(result["items"][0]["availability_decoded"])
                self.assertNotIn("source", result["items"][0])
                self.assertFalse(self.index.is_verified(identifier))
                self.assertEqual(result["library_verified_count"], 0)
        music = self.index.browse(view_request("music"))["items"][0]
        self.assertEqual((music["artist"], music["album"], music["provider"]),
                         ("Example artist", "Example album", "Local"))
        self.assertEqual({row["id"] for row in self.index.browse(view_request("movies"))["items"]},
                         {"unchecked-video", "unchecked-download"})
        self.assertEqual(self.index.browse(view_request("downloads"))["items"][0]["id"], "unchecked-download")

    def test_all_local_tracks_keep_distinct_files_and_alphabetical_snapshot_paging(self):
        rows = [dict(id=f"track-{n:04}", kind="MUSIC", title=f"Song {n // 2:04}", media="file",
                     source=f"C:/Music/Artist {n % 2}/track-{n:04}.flac", artist=f"Artist {n % 2}",
                     category=f"Artist {n % 2}")
                for n in reversed(range(1500))]
        self.index.ingest(rows)
        session = BrowseSession(self.index, view_request("music"))
        self.assertEqual(len(session.groups), 1500)
        identifiers, titles, offset = [], [], 0
        while True:
            result = session.page(offset)
            identifiers.extend(row["id"] for row in result["items"])
            titles.extend((row["artist"], row["title"]) for row in result["items"])
            self.assertLessEqual(len(result["items"]), 80)
            self.assertTrue(all(row["availability"] == "unknown" for row in result["items"]))
            if not result["library_has_more"]:
                break
            offset += len(result["items"])
        self.assertEqual(len(identifiers), 1500)
        self.assertEqual(len(set(identifiers)), 1500)
        self.assertEqual(titles, sorted(titles))
        self.assertEqual(result["library_total"], 1500)

    def test_failed_audio_is_withdrawn_until_retry_and_invalidates_existing_snapshot(self):
        now = time.time()
        for page, kind, source, media in (("radio", "RADIO", "https://example.invalid/radio.mp3", "stream"),
                                          ("music", "MUSIC", "file:///C:/Music/song.flac", "file")):
            with self.subTest(page=page):
                identifier = "failed-" + page
                self.index.ingest([dict(id=identifier, kind=kind, title="Example " + page,
                                        source=source, media=media)])
                session = BrowseSession(self.index, view_request(page))
                self.assertEqual(session.page(0)["items"][0]["id"], identifier)
                self.index.record(identifier, dict(status="failed", checked_at=now))
                with self.assertRaises(SnapshotInvalid):
                    session.page(0)
                self.assertEqual(self.index.browse(view_request(page))["items"], [])
                with patch("backend.media_index.time.time", return_value=now + 1801):
                    retry = self.index.browse(view_request(page))
                self.assertEqual(retry["items"][0]["id"], identifier)
                self.assertEqual(retry["items"][0]["availability"], "failed")
                self.assertFalse(self.index.is_verified(identifier))

    def test_quick_remote_music_check_is_available_without_claiming_a_decode(self):
        row = dict(id="remote-music", kind="MUSIC", title="Remote song", media="stream",
                   source="https://example.invalid/song.mp3")
        self.index.ingest([row])
        self.assertEqual(self.index.browse(view_request("music"))["items"][0]["availability"], "unknown")
        self.index.record(row["id"], dict(status="verified", scope="http_media", checked_at=time.time(),
                                         expires_at=time.time() + 100, evidence={"decoded": False, "reachable": True}))
        checked = self.index.browse(view_request("music"))["items"][0]
        self.assertEqual((checked["availability"], checked["availability_scope"]), ("available", "http_media"))
        self.assertFalse(checked["availability_decoded"])

    def test_quick_and_decoded_scopes_survive_reopen_and_snapshot_reads(self):
        rows = [item("quick", "A quick check"), item("deep", "B decoded check"), item("legacy", "C old check")]
        self.index.ingest(rows)
        now = time.time()
        self.index.record("quick", dict(status="verified", scope="hls_media", checked_at=now,
            expires_at=now + 60, evidence={"decoded": False, "reachable": True}))
        self.index.record("deep", dict(status="verified", checked_at=now, expires_at=now + 60,
            evidence={"video_frames": 3, "audio_frames": 2}))
        self.index.record("legacy", dict(status="verified", checked_at=now, expires_at=now + 60))
        reopened = MediaIndex(self.index.path)
        reopened.initialize()
        result = BrowseSession(reopened, view_request("movies")).page(0)
        summaries = {row["id"]: row for row in result["items"]}
        self.assertEqual((summaries["quick"]["availability"], summaries["quick"]["availability_scope"],
                          summaries["quick"]["availability_decoded"]), ("available", "hls_media", False))
        self.assertEqual((summaries["deep"]["availability"], summaries["deep"]["availability_scope"],
                          summaries["deep"]["availability_decoded"]), ("verified", "decoded_sample", True))
        self.assertEqual((summaries["legacy"]["availability"], summaries["legacy"]["availability_scope"],
                          summaries["legacy"]["availability_decoded"]), ("available", "previous_check", False))

    def test_old_index_migrates_without_inventing_decoded_evidence(self):
        self.index.ingest([item("legacy", "Existing positive")])
        now = time.time()
        self.index.record("legacy", dict(status="verified", checked_at=now, expires_at=now + 60))
        with self.index.connection() as db:
            db.execute("ALTER TABLE items DROP COLUMN check_scope")
            db.execute("ALTER TABLE items DROP COLUMN check_decoded")
        reopened = MediaIndex(self.index.path)
        reopened.initialize()
        summary = reopened.browse(view_request("movies"))["items"][0]
        self.assertEqual(summary["availability"], "available")
        self.assertEqual(summary["availability_scope"], "previous_check")
        self.assertFalse(summary["availability_decoded"])

    def test_empty_sources_and_orphan_generated_series_do_not_create_titles(self):
        empty = dict(item("empty", "Empty source"), source="")
        orphan = dict(item("orphan", "Orphan series", "series"), source="", media="collection")
        child = item("candidate", "Known series S01E01", "episode", series_title="Known series", season=1, episode=1)
        self.index.ingest([empty, orphan, child])
        self.assertEqual(self.index.browse(view_request("movies"))["items"], [])
        series = self.index.browse(view_request("series"))["items"]
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["title"], "Known series")
        self.assertEqual((series[0]["episode_count"], series[0]["availability_scope"]), (1, "metadata_episodes"))

    def test_fresh_local_scan_reconsiders_old_failure_without_fabricating_a_positive(self):
        path = self.index.path.parent / "song.mp3"
        path.write_bytes(b"ID3-local-fixture")
        row = dict(item("local-rescan", "Song"), kind="MUSIC", content_type="music",
                   media="file", source=str(path), local=True, artist="Artist")
        self.index.ingest([row])
        self.index.record(row["id"], dict(status="failed", scope="local_file", checked_at=time.time()))
        self.assertEqual(self.index.browse(view_request("music"))["items"], [])
        self.index.ingest([dict(row, audio_metadata_version=1)])
        current = self.index.browse(view_request("music"))["items"][0]
        self.assertEqual(current["availability"], "unknown")
        self.assertFalse(self.index.is_verified(row["id"]))

    def test_inconclusive_check_keeps_metadata_visible_without_inventing_a_positive(self):
        now = time.time()
        row = item("candidate", "Candidate")
        self.index.ingest([row])
        session = BrowseSession(self.index, view_request("movies"))
        self.index.record(row["id"], dict(status="unknown", checked_at=now))
        self.assertEqual(session.page(0)["items"][0]["id"], row["id"])
        current = self.index.browse(view_request("movies"))["items"][0]
        self.assertEqual(current["availability"], "unknown")
        self.assertFalse(self.index.is_verified(row["id"]))
        self.index.ingest([dict(row, source="https://example.invalid/replacement.mp4")])
        summary = self.index.browse(view_request("movies"))["items"][0]
        self.assertEqual(summary["availability_checked_at"], 0)
        self.assertEqual(summary["availability_scope"], "metadata")

    def test_artist_options_search_and_order_keep_title_letter_filter(self):
        rows = [dict(id=f"artist-{n:03}", kind="MUSIC", title=f"Track {n:03}", category=f"Artist {n:03}",
                     artist=f"Artist {n:03}", album="Collection", media="file", source=f"C:/Music/{n}.flac")
                for n in range(170)]
        rows.extend([dict(id="zulu", kind="MUSIC", title="Alpha song", category="Zulu", artist="Zulu",
                          album="Återbesök", media="file", source="C:/Music/zulu.flac"),
                     dict(id="alpha", kind="MUSIC", title="Zulu song", category="Alpha", artist="Alpha",
                          album="Example", media="file", source="C:/Music/alpha.flac")])
        self.index.ingest(rows)
        first = self.index.browse(view_request("music"))
        self.assertEqual(first["items"][0]["id"], "alpha")
        self.assertEqual(len(first["library_categories"]), 173)
        self.assertEqual(first["library_categories"][0]["label"], "Alla artister")
        by_artist = self.index.browse(view_request("music", category="Zulu"))
        self.assertEqual([row["id"] for row in by_artist["items"]], ["zulu"])
        by_title_letter = self.index.browse(view_request("music", letter="A"))
        self.assertEqual([row["id"] for row in by_title_letter["items"]], ["zulu"])
        self.assertEqual([row["id"] for row in self.index.browse(view_request("music", query="Zulu"))["items"]],
                         ["alpha", "zulu"])
        self.assertEqual([row["id"] for row in self.index.browse(view_request("music", query="återbesök"))["items"]],
                         ["zulu"])

    def test_public_playback_header_changes_require_new_proof(self):
        row = item("header", "Example", user_agent="Published/1.0", referrer="https://publisher.invalid/")
        self.healthy([row])
        old_identity = self.index.identity_key(row)
        replacement = dict(row, user_agent="Published/2.0")
        self.index.ingest_discovered([replacement])
        self.assertFalse(self.index.is_verified(row["id"]))
        self.assertEqual(self.index.get(row["id"])["user_agent"], "Published/2.0")
        self.index.record(row["id"], dict(status="verified", checked_at=time.time(), expires_at=time.time() + 100),
                          source=row["source"], identity=old_identity)
        self.assertFalse(self.index.is_verified(row["id"]))

    def test_metadata_correction_is_atomic_bound_to_original_source_and_needs_new_proof(self):
        row = item("episode", "Episode without confirmed numbering", content_type="episode", series_title="Example",
                   season=1, episode=2)
        self.healthy([row])
        corrected = self.index.correct_metadata(dict(row, season=0, episode=0), expected=row)
        self.assertEqual((corrected["season"], corrected["episode"]), (0, 0))
        self.assertFalse(self.index.is_verified(row["id"]))
        with self.assertRaisesRegex(ValueError, "MEDIA_SOURCE_CHANGED"):
            self.index.correct_metadata(dict(row, season=3), expected=row)
        self.assertEqual(self.index.get(row["id"])["season"], 0)

    def test_candidates_and_positive_sources_are_listed_without_loading_sources(self):
        self.index.ingest([item("unknown", "A film"), item("failed", "B film"),
                           item("expired", "C film"), item("verified", "D film")])
        now = time.time()
        self.index.record("failed", dict(status="failed", checked_at=now))
        self.index.record("expired", dict(status="verified", checked_at=now - 100,
                                          expires_at=now - 1, evidence={"video_frames": 3}))
        self.index.record("verified", dict(status="verified", checked_at=now,
                                           expires_at=now + 100, evidence={"video_frames": 3}))
        page = self.index.browse(view_request("movies"))
        self.assertEqual(page["library_total"], 3)
        self.assertFalse(page["library_has_more"])
        self.assertEqual({row["id"]: row["availability"] for row in page["items"]},
                         dict(unknown="unknown", expired="verified", verified="verified"))
        summaries = {row["id"]: row for row in page["items"]}
        self.assertFalse(summaries["expired"]["availability_fresh"])
        self.assertEqual(summaries["expired"]["availability_scope"], "previously_decoded")
        self.assertTrue(summaries["verified"]["availability_fresh"])
        self.assertFalse(self.index.is_verified("expired"))
        self.assertTrue(all("source" not in row for row in page["items"]))
        self.assertIn("source", self.index.get("unknown"))

    def test_catalogue_pages_are_bounded_and_heavy_provider_data_stays_in_database(self):
        rows = [item("film-" + str(n), "Film " + str(n).zfill(3),
                     alternate_sources=["https://example.invalid/" + "a" * 300] * 100,
                     description="x" * 10000) for n in range(181)]
        self.healthy(rows)
        first = self.index.browse(view_request("movies"))
        last = self.index.browse(view_request("movies", offset=160))
        self.assertEqual(first["library_total"], 181)
        self.assertEqual(len(first["items"]), 80)
        self.assertTrue(first["library_has_more"])
        self.assertEqual(len(last["items"]), 21)
        self.assertFalse(last["library_has_more"])
        self.assertLess(len(json.dumps(first)), 50000)
        self.assertNotIn("alternate_sources", first["items"][0])
        self.assertNotIn("description", first["items"][0])

    def test_live_channel_variants_have_one_label_and_prefer_a_fresh_source(self):
        rows = [item("dead", "Example TV", "live", channel_id="Example.se"),
                item("unknown", "Example TV", "live", channel_id="Example.se"),
                item("working", "Example TV", "live", channel_id="Example.se")]
        self.index.ingest(rows)
        now = time.time()
        self.index.record("dead", dict(status="failed", checked_at=now))
        self.index.record("working", dict(status="verified", checked_at=now, expires_at=now + 100,
                                           evidence={"video_frames": 3}))
        page = self.index.browse(view_request("live"))
        self.assertEqual(page["library_total"], 1)
        self.assertEqual(page["items"][0]["id"], "working")
        self.assertEqual(page["items"][0]["availability"], "verified")
        sources = self.index.group_sources("dead")
        self.assertEqual([row["id"] for row in sources], ["working", "unknown", "dead"])

    def test_real_series_descriptor_and_known_children_list_without_decoder_proofs(self):
        descriptor = item("descriptor", "Example series", "series", language="sv", archive_id="example-series")
        descriptor["source"] = "https://archive.org/details/example-series"
        self.index.ingest([descriptor])
        page = self.index.browse(view_request("series"))
        self.assertEqual(page["library_total"], 1)
        self.assertEqual(page["items"][0]["availability_scope"], "metadata")
        series = self.index.get("descriptor")
        episodes = self.index.browse(view_request("series", collection_key=series["collection_key"]))
        self.assertEqual(episodes["library_total"], 0)
        self.assertEqual(self.index.collection_descriptor(series["collection_key"])["id"], "descriptor")
        self.index.record("descriptor", dict(status="verified", checked_at=time.time(), expires_at=time.time() + 100))
        self.assertEqual(self.index.browse(view_request("series"))["library_total"], 1)
        child = item("episode", "Example series S01E01", "episode", series_title="Example series", language="sv", season=1, episode=1)
        self.healthy([child])
        checked = self.index.browse(view_request("series"))
        self.assertEqual(checked["library_total"], 1)
        self.assertEqual(checked["items"][0]["availability_scope"], "checked_episodes")
        self.assertEqual(checked["items"][0]["episode_count"], 1)

    def test_episode_generated_parents_do_not_trigger_another_provider_request(self):
        rows = [item("s1e10", "Example S01E10", "episode", series_title="Example", language="sv",
                     season=1, episode=10, archive_id="example"),
                item("s1e2", "Example S01E02", "episode", series_title="Example", language="sv",
                     season=1, episode=2, archive_id="example")]
        self.healthy(rows)
        series = self.index.browse(view_request("series"))["items"][0]
        self.assertEqual(self.index.collection_descriptors(series["collection_key"]), [])
        episodes = self.index.browse(view_request("series", collection_key=series["collection_key"]))
        self.assertEqual([row["id"] for row in episodes["items"]], ["s1e2", "s1e10"])

    def test_letter_type_and_language_filters_apply_to_checked_inventory(self):
        self.healthy([item("a-film", "Alpha film", language="sv"),
                           item("a-series", "Alpha series", "series", language="sv"),
                           item("b-film", "Beta film", language="sv"),
                           item("a-other", "Alpha other", language="en")])
        self.healthy([item("a-episode", "Alpha series S01E01", "episode", series_title="Alpha series", language="sv", season=1, episode=1)])
        movies = self.index.browse(view_request("movies", letter="A", language="sv"))
        series = self.index.browse(view_request("series", letter="A", language="sv"))
        self.assertEqual([row["id"] for row in movies["items"]], ["a-film"])
        self.assertEqual([row["id"] for row in series["items"]], ["a-series"])

    def test_lazy_metadata_enrichment_keeps_open_collection_identity(self):
        self.index.ingest([item("series", "Example series", "series")])
        selected = self.index.get("series")
        collection = selected["collection_key"]
        self.healthy([item("episode", "Example S01E01", "episode", series_title="Example series",
                               language="en", season=1, episode=1, collection_key=collection)])
        self.assertEqual(self.index.browse(view_request("series"))["library_total"], 1)
        episodes = self.index.browse(view_request("series", collection_key=collection))
        self.assertEqual([row["id"] for row in episodes["items"]], ["episode"])
        self.assertEqual(episodes["items"][0]["language"], "en")

    def test_existing_database_reopens_without_reingesting_or_health_gates(self):
        self.healthy([item("persisted", "Persisted film")])
        reopened = MediaIndex(self.index.path)
        reopened.initialize()
        self.assertEqual(reopened.browse(view_request("movies"))["items"][0]["id"], "persisted")

    def test_revisited_page_copies_are_independent_and_refresh_after_external_index_updates(self):
        self.healthy([item("alpha", "Alpha film")])
        view = view_request("movies")
        page = self.index.browse(view)
        page["items"][0]["title"] = "Client changed its copy"
        self.assertEqual(self.index.browse(view)["items"][0]["title"], "Alpha film")
        other = MediaIndex(self.index.path)
        other.ingest([item("beta", "Beta film")])
        other.record("beta", dict(status="verified", checked_at=time.time(), expires_at=time.time() + 100))
        refreshed = self.index.browse(view)
        self.assertEqual(refreshed["library_total"], 2)
        self.assertEqual([row["id"] for row in refreshed["items"]], ["alpha", "beta"])
        other.record("alpha", dict(status="failed", checked_at=time.time()))
        self.assertEqual([row["id"] for row in self.index.browse(view)["items"]], ["beta"])

    def test_revisited_page_retains_checked_source_but_exposes_expired_playback_freshness(self):
        self.index.ingest([item("alpha", "Alpha film")])
        now = time.time()
        self.index.record("alpha", dict(status="verified", checked_at=now, expires_at=now + 1,
                                         evidence={"video_frames": 3}))
        view = view_request("movies")
        self.assertEqual(self.index.browse(view)["items"][0]["availability"], "verified")
        with patch("backend.media_index.time.time", return_value=now + 2):
            result = self.index.browse(view)
        self.assertEqual(result["library_total"], 1)
        self.assertFalse(result["items"][0]["availability_fresh"])
        self.assertEqual(result["items"][0]["availability_scope"], "previously_decoded")

    def test_retention_bounds_positive_claims_without_hiding_saved_metadata(self):
        now = time.time()
        rows = [item("recent-live", "Recent live", "live"), item("old-live", "Old live", "live"),
                item("recent-film", "Recent film"), item("old-film", "Old film"),
                item("unconfirmed", "Unconfirmed", availability="verified"), item("malformed", "Malformed")]
        self.index.ingest(rows)
        for identifier, age in (("recent-live", LIVE_CATALOG_RETENTION_SECONDS - 1),
                                ("old-live", LIVE_CATALOG_RETENTION_SECONDS + 1),
                                ("recent-film", VOD_CATALOG_RETENTION_SECONDS - 1),
                                ("old-film", VOD_CATALOG_RETENTION_SECONDS + 1)):
            checked = now - age
            self.index.record(identifier, dict(status="verified", checked_at=checked, expires_at=checked + 1))
        self.index.record("malformed", dict(status="verified", checked_at=now, expires_at=0))
        self.assertEqual([r["id"] for r in self.index.browse(view_request("live"))["items"]], ["old-live", "recent-live"])
        self.assertEqual({r["id"] for r in self.index.browse(view_request("movies"))["items"]},
                         {"old-film", "recent-film", "unconfirmed", "malformed"})
        self.assertEqual(self.index.browse(view_request("movies"))["library_verified_count"], 2)
        with patch("backend.media_index.time.time", return_value=now + 2):
            self.assertTrue(all(row["availability"] == "expired"
                                for row in self.index.browse(view_request("live"))["items"]))
            self.assertTrue(all(row["availability"] != "available"
                                for row in self.index.browse(view_request("movies"))["items"]))

    def test_source_choices_prefer_fresh_then_retained_and_failures_withdraw_retained_rows(self):
        now = time.time()
        rows = [item(identifier, "Example TV", "live", channel_id="Example.se")
                for identifier in ("a-unknown", "b-retained", "z-fresh")]
        self.index.ingest(rows)
        self.index.record("b-retained", dict(status="verified", checked_at=now - 2000, expires_at=now - 1000))
        self.index.record("z-fresh", dict(status="verified", checked_at=now, expires_at=now + 100))
        self.assertEqual([r["id"] for r in self.index.group_sources("a-unknown")],
                         ["z-fresh", "b-retained", "a-unknown"])
        self.index.record("z-fresh", dict(status="failed", checked_at=now))
        self.assertEqual(self.index.browse(view_request("live"))["items"][0]["id"], "b-retained")
        self.index.record("b-retained", dict(status="unknown", checked_at=now))
        self.assertEqual(self.index.browse(view_request("live"))["items"][0]["id"], "a-unknown")

    def test_series_lists_known_children_with_honest_positive_scope(self):
        now = time.time()
        rows = [item("checked-episode", "Example S01E01", "episode", series_title="Example", season=1, episode=1),
                item("unchecked-episode", "Example S01E02", "episode", series_title="Example", season=1, episode=2)]
        self.index.ingest(rows)
        self.index.record("checked-episode", dict(status="verified", checked_at=now - 2000, expires_at=now - 1000))
        series = self.index.browse(view_request("series"))["items"]
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["episode_count"], 2)
        self.assertEqual(series[0]["availability_scope"], "available_episodes")
        self.assertFalse(series[0]["availability_fresh"])
        episodes = self.index.browse(view_request("series", collection_key=series[0]["collection_key"]))
        self.assertEqual([r["id"] for r in episodes["items"]], ["checked-episode", "unchecked-episode"])

    def test_discovery_merge_preserves_curated_identity_and_existing_positive_proof(self):
        curated = item("episode", "S01E03 - Avsnitt 3", "episode", series_title="Example series",
                       language="sv", season=1, episode=3, collection_key="chosen-series",
                       category="Svenska klassiker", duration=0)
        unrelated = item("unrelated", "Other film")
        self.healthy([curated, unrelated])
        before = self.index.get("episode")
        other_before = self.index.get("unrelated")
        with self.index.connection() as db:
            proof = tuple(db.execute("SELECT status,checked_at,verified_until FROM items WHERE id='episode'").fetchone())
        discovered = dict(curated, title="Example.Series.S01E03.DVDRip", episode_title="raw release name",
                          series_title="Wrong inferred group", season=9, episode=9, language="en",
                          collection_key="inferred-series", category="Archive", duration=1500, bytes=123456)
        canonical = self.index.ingest_discovered([discovered])
        self.assertEqual(canonical, [self.index.get("episode")])
        for key in ("title", "series_title", "language", "season", "episode", "collection_key", "category"):
            self.assertEqual(canonical[0][key], before[key])
        self.assertEqual(canonical[0]["duration"], 1500)
        self.assertEqual(canonical[0]["bytes"], 123456)
        self.assertTrue(self.index.is_verified("episode"))
        with self.index.connection() as db:
            self.assertEqual(tuple(db.execute("SELECT status,checked_at,verified_until FROM items WHERE id='episode'").fetchone()), proof)
        self.assertEqual(self.index.get("unrelated"), other_before)

    def test_discovery_source_replacement_still_withdraws_previous_proof(self):
        original = item("film", "Original film")
        self.healthy([original])
        session = BrowseSession(self.index, view_request("movies"))
        replacement = dict(original, source="https://example.invalid/replacement.mp4", title="Replacement film")
        canonical = self.index.ingest_discovered([replacement])
        self.assertEqual(canonical[0]["source"], replacement["source"])
        self.assertEqual(canonical[0]["title"], replacement["title"])
        self.assertFalse(self.index.is_verified("film"))
        self.assertEqual(self.index.browse(view_request("movies"))["items"][0]["availability"], "unknown")
        with self.assertRaises(SnapshotInvalid):
            session.page(0)

    def test_repeated_discovery_of_identical_row_is_noop_and_returns_canonical_group(self):
        episode = item("episode", "Example S01E01", "episode", series_title="Example", season=1, episode=1)
        self.index.ingest_discovered([episode])
        revision = self.index.meta("inventory_revision")
        canonical = self.index.ingest_discovered([episode, episode])
        self.assertEqual(canonical, [self.index.get("episode")])
        self.assertTrue(canonical[0]["collection_key"])
        self.assertEqual(self.index.meta("inventory_revision"), revision)

    def test_selected_resolution_guard_does_not_restore_a_replaced_source_or_insert_its_children(self):
        original = item("selected", "Original film")
        self.healthy([original])
        snapshot = self.index.get("selected")
        replacement = dict(original, source="https://example.invalid/new.mp4", title="New film")
        self.healthy([replacement])
        before = self.index.get("selected")
        revision = self.index.meta("inventory_revision")
        resolved_child = item("resolved-child", "Old resolved child")
        with self.assertRaisesRegex(ValueError, "MEDIA_SOURCE_CHANGED"):
            self.index.ingest_discovered([original, resolved_child], expected={snapshot["id"]: snapshot})
        self.assertEqual(self.index.get("selected"), before)
        self.assertTrue(self.index.is_verified("selected"))
        self.assertIsNone(self.index.get("resolved-child"))
        self.assertEqual(self.index.meta("inventory_revision"), revision)

    def test_selected_resolution_guard_detects_same_url_identity_change_and_accepts_current_snapshot(self):
        original = item("selected", "Original film", language="sv")
        self.index.ingest([original])
        snapshot = self.index.get("selected")
        self.index.ingest([dict(original, title="Different film", language="en")])
        with self.assertRaisesRegex(ValueError, "MEDIA_SOURCE_CHANGED"):
            self.index.ingest_discovered([original], expected={snapshot["id"]: snapshot})
        current = self.index.get("selected")
        accepted = self.index.ingest_discovered([dict(current, duration=200)], expected={current["id"]: current})
        self.assertEqual(accepted[0]["title"], "Different film")
        self.assertEqual(accepted[0]["duration"], 200)

    def test_selected_descriptor_guard_can_protect_a_different_resolved_child_identifier(self):
        descriptor = item("descriptor", "Example", "series")
        self.index.ingest([descriptor])
        snapshot = self.index.get("descriptor")
        child = item("child", "Example S01E01", "episode", series_title="Example", season=1, episode=1)
        canonical = self.index.ingest_discovered([child], expected={snapshot["id"]: snapshot})
        self.assertEqual([row["id"] for row in canonical], ["child"])
        self.assertEqual(self.index.get("descriptor"), snapshot)

    def test_descriptor_rediscovery_keeps_same_archive_resolved_file_and_proof(self):
        resolved = item("archive:example-film", "Example film", archive_id="example-film",
                        archive_file="Main film.ia.mp4", archive_title="Example film")
        resolved["source"] = "https://archive.org/download/example-film/Main%20film.ia.mp4"
        self.healthy([resolved])
        before = self.index.get(resolved["id"])
        identity = self.index.identity_key(before)
        with self.index.connection() as db:
            proof = tuple(db.execute("SELECT status,checked_at,verified_until FROM items WHERE id=?",
                                     (resolved["id"],)).fetchone())
        descriptor = dict(resolved, source="https://archive.org/details/example-film", title="Example film descriptor",
                          description="New provider description")
        descriptor.pop("archive_file")
        canonical = self.index.ingest_discovered([descriptor])
        self.assertEqual(canonical[0]["source"], before["source"])
        self.assertEqual(canonical[0]["archive_file"], before["archive_file"])
        self.assertEqual(self.index.identity_key(canonical[0]), identity)
        self.assertEqual(canonical[0]["description"], "New provider description")
        self.assertTrue(self.index.is_verified(resolved["id"]))
        with self.index.connection() as db:
            self.assertEqual(tuple(db.execute("SELECT status,checked_at,verified_until FROM items WHERE id=?",
                                              (resolved["id"],)).fetchone()), proof)

    def test_descriptor_preservation_requires_exact_archive_identity_and_canonical_urls(self):
        resolved = item("archive:example-film", "Example film", archive_id="example-film",
                        archive_file="film.mp4")
        resolved["source"] = "https://archive.org/download/example-film/film.mp4"
        descriptor = dict(resolved, source="https://archive.org/details/example-film")
        descriptor.pop("archive_file")
        for changes in (dict(source="https://evil.invalid/details/example-film"),
                        dict(source="https://archive.org/details/example-film?different=1"),
                        dict(source="https://archive.org/details/other-film"),
                        dict(archive_id="other-film"),
                        dict(archive_file="film.mp4")):
            with self.subTest(changes=changes):
                self.healthy([resolved])
                replacement = dict(descriptor, **changes)
                canonical = self.index.ingest_discovered([replacement])
                self.assertEqual(canonical[0]["source"], replacement["source"])
                self.assertFalse(self.index.is_verified(resolved["id"]))
        self.healthy([resolved])
        replacement = dict(resolved, archive_file="new-film.mp4",
                           source="https://archive.org/download/example-film/new-film.mp4")
        canonical = self.index.ingest_discovered([replacement])
        self.assertEqual(canonical[0]["source"], replacement["source"])
        self.assertFalse(self.index.is_verified(resolved["id"]))

    def test_scroll_revision_stays_stable_for_source_checks_but_changes_for_inventory_edits(self):
        original = item("alpha", "Alpha film")
        self.healthy([original])
        view = view_request("movies")
        before = self.index.browse(view)["library_catalog_revision"]
        self.index.record("alpha", dict(status="verified", checked_at=time.time(), expires_at=time.time() + 100))
        self.index.ingest([original])
        self.assertEqual(self.index.browse(view)["library_catalog_revision"], before)
        self.index.ingest([item("beta", "Beta film")])
        added = self.index.browse(view)["library_catalog_revision"]
        self.assertNotEqual(added, before)
        self.index.ingest([dict(original, title="Zulu film")])
        self.assertNotEqual(self.index.browse(view)["library_catalog_revision"], added)

    def test_same_url_with_changed_title_language_or_episode_withdraws_old_proof(self):
        for number, changes in enumerate((dict(title="Different film"), dict(language="en"), dict(season=2), dict(episode=3))):
            row = item("identity-" + str(number), "Original film", language="sv", season=1, episode=1)
            self.healthy([row])
            identity = self.index.identity_key(row)
            self.index.ingest([dict(row, **changes)])
            self.index.record(row["id"], dict(status="verified", checked_at=time.time(), expires_at=time.time() + 100),
                              source=row["source"], identity=identity)
            self.assertFalse(self.index.is_verified(row["id"]))


if __name__ == "__main__":
    unittest.main()
