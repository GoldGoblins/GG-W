"""Checkpointed audit: real source guards, fake metadata and decoder reports."""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import media_health_audit as audit_module
from backend.media_health_audit import MediaHealthAudit, check_identity, prepare_identity
from backend.media_index import MediaIndex, view_request


def movie(identifier="one", title="Example film", source=None, **values):
    row = dict(id=identifier, kind="TV", content_type="movie", title=title,
               source=source or "https://example.invalid/" + identifier + ".mp4", media="vod")
    row.update(values)
    return row


def archive(identifier="film", title="Example film", filename="Example film.mp4", **values):
    return movie("archive-" + identifier, title,
                 "https://archive.org/download/" + identifier + "/" + filename.replace(" ", "%20"),
                 archive_id=identifier, archive_file=filename, language="sv", **values)


def metadata(title="Example film", filename="Example film.mp4", identifier="film", **values):
    info = dict(identifier=identifier, title=title, language="swe")
    info.update(values)
    return dict(metadata=info,
                files=[dict(name=filename, size="1000000", format="MPEG4", length="5400")])


def proof(*args, **kwargs):
    now = time.time()
    return dict(schema="gg.media.availability.v1", status="verified", checked_at=now, expires_at=now + 600,
                evidence=dict(decoded=True, video_frames=8, audio_stream=True, audio_frames=6),
                original_source="https://example.invalid/private?token=do-not-copy", downloaded_bytes=1500)


class MediaHealthAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-media-health-")
        self.index = MediaIndex(Path(self.temporary.name) / "library.sqlite3")
        self.audit = MediaHealthAudit(self.index)
        self.audit.initialize()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(audit_module.library, "_cached_json", side_effect=AssertionError("Unexpected network")))
        self.verifier = self.stack.enter_context(patch.object(audit_module.availability, "verify", side_effect=proof))

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def health(self, identifier):
        with self.index.connection() as db:
            return tuple(db.execute("SELECT status,checked_at,verified_until FROM items WHERE id=?", (identifier,)).fetchone())

    def member(self, run_id, identifier):
        with self.index.connection() as db:
            return dict(db.execute("SELECT state,identity_report FROM media_audit_members WHERE run_id=? AND item_id=?", (run_id, identifier)).fetchone())

    def test_start_snapshots_without_any_network_and_duplicate_urls_decode_once(self):
        source = "https://example.invalid/shared.mp4"
        self.index.ingest([movie("first", source=source), movie("second", source=source),
                           dict(movie("game"), kind="GAME", content_type="game"),
                           dict(movie("empty"), content_type="series", source="")])
        run_id = self.audit.start()
        self.verifier.assert_not_called()
        self.assertEqual(self.audit.status()["total"], 1)
        result = self.audit.run(run_id)
        self.assertEqual(self.verifier.call_count, 1)
        self.assertEqual((result["status"], result["healthy"], result["done"], result["pending"]), ("complete", 1, 1, 0))
        self.assertEqual(self.health("first")[0], "verified")
        self.assertEqual(self.health("second")[0], "verified")
        with self.index.connection() as db:
            report = db.execute("SELECT report FROM media_audit_jobs").fetchone()[0]
        self.assertNotIn("token", report)
        self.assertNotIn("https:", report)

    def test_same_url_distinct_public_referrers_cannot_borrow_each_others_decoded_proof(self):
        source = "https://example.invalid/shared.mp4"
        self.index.ingest([movie("allowed", source=source, referrer="https://publisher.invalid/allowed"),
                           movie("denied", source=source, referrer="https://publisher.invalid/denied")])
        def check(row, **kwargs):
            if row.get("referrer", "").endswith("/allowed"):
                return proof()
            return dict(status="failed", checked_at=time.time(), error="access_denied", evidence=dict(decoded=False))
        self.verifier.side_effect = check
        result = self.audit.run(self.audit.start())
        self.assertEqual((result["total"], result["healthy"], self.verifier.call_count), (1, 1, 2))
        self.assertTrue(self.index.is_verified("allowed"))
        self.assertEqual(self.health("denied")[0], "failed")
        with self.index.connection() as db:
            report = db.execute("SELECT report FROM media_audit_jobs").fetchone()[0]
        evidence = json.loads(report)["evidence"]
        self.assertEqual((evidence["request_contexts"], evidence["healthy_contexts"], evidence["failed_contexts"]), (2, 1, 1))
        self.assertNotIn("publisher.invalid", report)
        self.assertNotIn("https:", report)

    def test_omitted_and_explicit_default_public_user_agent_share_one_effective_probe(self):
        from backend.media_request import DEFAULT_USER_AGENT
        source = "https://example.invalid/shared.mp4"
        self.index.ingest([movie("implicit", source=source), movie("explicit", source=source, user_agent=DEFAULT_USER_AGENT)])
        result = self.audit.run(self.audit.start())
        self.assertEqual((result["healthy"], self.verifier.call_count), (1, 1))
        self.assertTrue(self.index.is_verified("implicit"))
        self.assertTrue(self.index.is_verified("explicit"))

    def test_mixed_healthy_and_transient_header_contexts_retry_only_within_the_finite_limit(self):
        source = "https://example.invalid/shared.mp4"
        self.index.ingest([movie("available", source=source, user_agent="Available-player/1"),
                           movie("uncertain", source=source, user_agent="Uncertain-player/1")])
        def check(row, **kwargs):
            if row.get("user_agent") == "Available-player/1":
                return proof()
            return dict(status="unknown", checked_at=time.time(), error="timeout", evidence=dict(decoded=False))
        self.verifier.side_effect = check
        result = self.audit.run(self.audit.start())
        self.assertEqual((result["status"], result["healthy"], result["pending"], self.verifier.call_count), ("complete", 1, 0, 4))
        self.assertTrue(self.index.is_verified("available"))
        self.assertFalse(self.index.is_verified("uncertain"))

    def test_repaired_false_negatives_are_claimed_before_new_untouched_titles(self):
        self.index.ingest([movie("retry")])
        run_id = self.audit.start()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_jobs SET state='unknown',attempts=1,report=? WHERE run_id=?",
                       (json.dumps(dict(status="unknown", error="playlist_too_large")), run_id))
            db.execute("UPDATE media_audit_groups SET sampled=1,last_claimed=? WHERE run_id=?", (time.time(), run_id))
        self.index.ingest([movie("untouched-" + str(n), "Film " + str(n)) for n in range(100)])
        self.audit.include(run_id)
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 1)
        with self.index.connection() as db:
            repaired = db.execute("SELECT j.priority,g.sampled,g.last_claimed FROM media_audit_jobs j "
                "JOIN media_audit_groups g ON g.run_id=j.run_id AND g.lane=j.lane AND g.coverage_key=j.coverage_key "
                "WHERE j.run_id=? AND json_extract(j.payload,'$.id')='retry'", (run_id,)).fetchone()
        self.assertEqual(tuple(repaired), (-100, 0, 0))
        self.assertEqual(self.audit._claim(run_id, "movies")[1]["id"], "retry")

    def test_slices_resume_without_rechecking_completed_jobs_or_resnapshotting_new_items(self):
        self.index.ingest([movie(str(n), "Film " + str(n)) for n in range(3)])
        run_id = self.audit.start()
        first = self.audit.run(run_id, workers=1, max_jobs=1)
        self.assertEqual((first["status"], first["done"], first["pending"]), ("paused", 1, 2))
        self.index.ingest([movie("later", "Later film")])
        self.assertEqual(self.audit.start(), run_id)
        self.assertEqual(self.audit.status()["total"], 3)
        result = MediaHealthAudit(MediaIndex(self.index.path)).run(run_id, workers=2)
        self.assertEqual((result["status"], result["healthy"]), ("complete", 3))
        self.assertEqual(self.verifier.call_count, 3)
        next_id = self.audit.start()
        self.assertNotEqual(next_id, run_id)
        self.assertEqual(self.audit.status(next_id)["total"], 4)

    def test_explicit_include_extends_only_with_current_local_sources_without_opening_them(self):
        self.index.ingest([movie("original")])
        run_id = self.audit.start()
        self.assertEqual(self.audit.run(run_id)["healthy"], 1)
        original_health = self.health("original")
        self.index.ingest([movie("later"), movie("another")])
        self.verifier.reset_mock()
        included = self.audit.include(run_id)
        self.assertEqual((included["included_sources"], included["included_members"], included["pending"]), (2, 2, 2))
        self.assertEqual(self.health("original"), original_health)
        self.verifier.assert_not_called()
        self.assertEqual(self.audit.include(run_id)["included_sources"], 0)
        self.assertEqual(self.audit.run(run_id)["healthy"], 3)
        self.assertEqual(self.verifier.call_count, 2)

    def test_include_new_same_url_label_rechecks_identity_instead_of_reusing_the_other_labels_proof(self):
        source = "https://example.invalid/shared.mp4"
        self.index.ingest([movie("original", source=source)])
        run_id = self.audit.start()
        self.audit.run(run_id)
        self.index.ingest([movie("new-label", source=source)])
        included = self.audit.include(run_id)
        self.assertEqual((included["included_sources"], included["included_members"], included["pending"]), (0, 1, 1))
        self.assertFalse(self.index.is_verified("new-label"))
        self.verifier.reset_mock()
        self.assertEqual(self.audit.run(run_id)["healthy"], 1)
        self.verifier.assert_called_once()
        self.assertTrue(self.index.is_verified("new-label"))

    def test_new_same_url_member_arriving_during_decode_gets_its_own_later_identity_check(self):
        source = "https://example.invalid/shared.mp4"
        self.index.ingest([movie("original", source=source)])
        run_id = self.audit.start()
        calls = 0
        def checking(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.index.ingest([movie("later", source=source)])
                with self.audit._connection() as db:
                    self.audit._enqueue(db, run_id, [self.index.get("later")])
            return proof()
        self.verifier.side_effect = checking
        result = self.audit.run(run_id, workers=1)
        self.assertEqual((result["status"], result["healthy"], calls), ("complete", 1, 2))
        self.assertTrue(self.index.is_verified("later"))

    def test_include_cannot_extend_a_run_owned_by_an_active_checker(self):
        self.index.ingest([movie()])
        run_id = self.audit.start()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET owner='active',lease_until=?,status='running' WHERE id=?",
                       (time.time() + 60, run_id))
        self.index.ingest([movie("later")])
        with self.assertRaisesRegex(RuntimeError, "MEDIA_AUDIT_RUNNING"):
            self.audit.include(run_id)
        self.assertEqual(self.audit.status(run_id)["total"], 1)

    def test_wrong_archive_title_file_language_and_episode_never_decode_or_admit(self):
        cases = [
            (archive(title="Wrong programme"), metadata(), "title_mismatch"),
            (archive(filename="Missing.mp4"), metadata(), "file_missing_or_disallowed"),
            (archive(filename="film_trailer.mp4"), metadata(filename="film_trailer.mp4"), "file_missing_or_disallowed"),
            (archive(), metadata(language="eng"), "language_mismatch"),
            (archive(title="Example", filename="Example S01E02.mp4", content_type="episode"),
             metadata(title="Example", filename="Example S01E02.mp4"), "episode_mismatch"),
        ]
        for index, (row, payload, reason) in enumerate(cases):
            if reason == "episode_mismatch":
                row.update(content_type="episode", series_title="Example", season=1, episode=1)
            row["id"] = "case-" + str(index)
            with patch.object(audit_module.library, "_cached_json", return_value=payload):
                identity = check_identity(row)
                self.assertEqual(identity["reason"], reason)
                self.index.ingest([row])
                run_id = self.audit.start()
                self.audit.run(run_id)
            self.assertNotEqual(self.health(row["id"])[0], "verified")
        self.verifier.assert_not_called()

    def test_archive_correct_file_is_admitted_with_metadata_identity_evidence(self):
        row = archive()
        self.index.ingest([row])
        with patch.object(audit_module.library, "_cached_json", return_value=metadata()):
            result = self.audit.run(self.audit.start())
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(self.health(row["id"])[0], "verified")
        member = self.member(self.audit._latest(), row["id"])
        identity = json.loads(member["identity_report"])
        self.assertEqual(identity["scope"], "archive_file")
        self.assertFalse(identity["semantic_identity_verified"])

    def test_generic_title_words_or_matching_original_title_cannot_certify_a_wrong_display_label(self):
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Another Film")):
            self.assertEqual(check_identity(archive(title="A Film"))["reason"], "title_mismatch")
        with patch.object(audit_module.library, "_cached_json", return_value=metadata()):
            row = archive(title="A different programme", archive_title="Example film")
            self.assertEqual(check_identity(row)["reason"], "title_mismatch")

    def test_decoder_missing_or_http_only_positive_is_unknown_not_healthy(self):
        self.index.ingest([movie()])
        self.verifier.side_effect = lambda *a, **k: dict(status="verified", checked_at=time.time(),
            expires_at=time.time() + 100, evidence=dict(decoded=False, http_response=200))
        result = self.audit.run(self.audit.start())
        self.assertEqual((result["healthy"], result["unknown"]), (0, 1))
        self.assertEqual(self.health("one")[0], "unknown")

    def test_source_change_during_probe_cannot_certify_replacement_or_count_as_healthy(self):
        row = movie()
        self.index.ingest([row])
        def change(*args, **kwargs):
            self.index.ingest([dict(row, source="https://example.invalid/replacement.mp4")])
            return proof()
        self.verifier.side_effect = change
        result = self.audit.run(self.audit.start())
        self.assertEqual((result["healthy"], result["changed"]), (0, 1))
        self.assertEqual(self.health("one")[0], "unknown")

    def test_same_url_label_language_and_episode_changes_cannot_reuse_old_identity_check(self):
        original = movie(language="sv")
        for changed in (dict(title="A different programme"), dict(language="en"), dict(season=2, episode=3)):
            with self.subTest(changed=changed):
                self.index.ingest([original])
                def alter_identity(*args, **kwargs):
                    self.index.ingest([dict(original, **changed)])
                    return proof()
                self.verifier.side_effect = alter_identity
                result = self.audit.run(self.audit.start())
                self.assertEqual((result["healthy"], result["changed"]), (0, 1))
                self.assertEqual(self.health("one")[0], "unknown")

    def test_numbered_labels_need_episode_and_season_evidence_from_the_provider(self):
        row = archive(title="Example", filename="programme.mp4", content_type="episode",
                      series_title="Example", season=1, episode=2)
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Example", filename="programme.mp4")):
            self.assertEqual(check_identity(row)["reason"], "missing_episode_evidence")
        episode_only = dict(row, archive_file="Example episode 2.mp4",
                            source="https://archive.org/download/film/Example%20episode%202.mp4")
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Example", filename=episode_only["archive_file"])):
            self.assertEqual(check_identity(episode_only)["reason"], "missing_season_evidence")
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Example S01E02", filename="programme.mp4")):
            identity = check_identity(row)
            self.assertEqual(identity["status"], "consistent")
            self.assertTrue(identity["episode_consistent"])
            self.assertTrue(identity["season_consistent"])
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Example", filename="programme.mp4", season="1", episode="2")):
            self.assertEqual(check_identity(row)["status"], "consistent")

    def test_unicode_subtitles_and_collection_file_evidence_do_not_reject_correct_programmes(self):
        cases = [
            (archive(title="Ο Παραμυθάς", filename="episode.mp4"),
             metadata(title='Ο Παραμυθάς: The Complete Series ("Mr. Storyteller")', filename="episode.mp4")),
            (archive(title="Sällskapsresan II – Snowroller", filename="Snowroller.1985.SWEDiSH.mp4"),
             metadata(title="Snowroller (1985)", filename="Snowroller.1985.SWEDiSH.mp4")),
            (archive(title="Scooby Doo tape", filename="Scooby Doo Tape 3.mp4", content_type="episode",
                     series_title="Cartoon Network Scooby Doo VHS 1998", season=0, episode=0),
             metadata(title="Cartoon Network Tape Recordings April July 1998", filename="Scooby Doo Tape 3.mp4")),
        ]
        for row, payload in cases:
            with self.subTest(title=row["title"]), patch.object(audit_module.library, "_cached_json", return_value=payload):
                self.assertEqual(check_identity(row)["status"], "consistent")

    def test_explicit_filename_or_provider_title_language_is_evidence_but_absence_is_not(self):
        for filename, title in (("Example SWEDiSH.mp4", "Example"), ("Example.mp4", "Example SWEDiSH")):
            payload = metadata(title=title, filename=filename)
            payload["metadata"].pop("language")
            with patch.object(audit_module.library, "_cached_json", return_value=payload):
                row, identity = prepare_identity(archive(title="Example", filename=filename))
                self.assertEqual((identity["status"], row["language"]), ("consistent", "sv"))
        payload = metadata()
        payload["metadata"].pop("language")
        original = archive()
        with patch.object(audit_module.library, "_cached_json", return_value=payload):
            corrected, identity = prepare_identity(original)
        self.assertEqual((identity["status"], corrected["language"], original["language"]), ("consistent", "", "sv"))

    def test_missing_numbering_is_shown_under_true_file_label_after_a_new_decode(self):
        original = archive(title="S01E02 - Chosen label", filename="Example bonus.mp4", content_type="episode",
                           series_title="Example", season=1, episode=2)
        self.index.ingest([original])
        self.index.record(original["id"], proof())
        payload = metadata(title="Example", filename="Example bonus.mp4")
        with patch.object(audit_module.library, "_cached_json", return_value=payload):
            corrected, identity = prepare_identity(original)
            self.assertEqual((corrected["season"], corrected["episode"], corrected["title"]), (0, 0, "Example bonus"))
            self.assertEqual(identity["status"], "consistent")
            result = self.audit.run(self.audit.start())
        self.assertEqual((result["healthy"], result["changed"]), (1, 0))
        self.verifier.assert_called_once()
        decoded_row = self.verifier.call_args.args[0]
        self.assertEqual((decoded_row["season"], decoded_row["episode"]), (0, 0))
        self.assertEqual(self.index.get(original["id"])["title"], "Example bonus")
        self.assertEqual(self.index.get(original["id"])["source"], original["source"])

    def test_explicit_parts_and_youtube_suffixes_are_parsed_without_inventing_seasons(self):
        row = archive(title="Example", filename="Example Del 2 av 4.mp4", content_type="episode",
                      series_title="Example", season=0, episode=2)
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Example", filename=row["archive_file"])):
            self.assertEqual(check_identity(row)["status"], "consistent")
        row = archive(title="Example", filename="Example del 22-S2OXT54afU4.mp4", content_type="episode",
                      series_title="Example", season=1, episode=22)
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(title="Example Season 1", filename=row["archive_file"])):
            self.assertEqual(check_identity(row)["status"], "consistent")
        self.assertEqual(audit_module._season_number("Example-s5FcZ8YQ-VA.mp4"), 0)

    def test_absent_file_size_metadata_does_not_replace_real_decoder_validation(self):
        payload = metadata()
        payload["files"][0].pop("size")
        self.index.ingest([archive()])
        with patch.object(audit_module.library, "_cached_json", return_value=payload):
            identity = check_identity(archive())
            self.assertEqual(identity["status"], "consistent")
            self.assertFalse(identity["file_size_confirmed"])
            self.assertEqual(self.audit.run(self.audit.start())["healthy"], 1)
        self.verifier.assert_called_once()

    def test_prior_metadata_only_rejection_gets_one_recheck_without_reusing_its_old_identity(self):
        original = archive()
        payload = metadata()
        payload["metadata"].pop("language")
        self.index.ingest([original])
        run_id = self.audit.start()
        with patch.object(audit_module, "prepare_identity", return_value=(original,
                  dict(status="unknown", scope="archive_file", reason="language_unconfirmed"))):
            self.assertEqual(self.audit.run(run_id)["unknown"], 1)
        self.verifier.assert_not_called()
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 1)
        with patch.object(audit_module.library, "_cached_json", return_value=payload):
            self.assertEqual(self.audit.run(run_id)["healthy"], 1)
        self.assertEqual(self.verifier.call_args.args[0]["language"], "")
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 0)

    def test_cancelled_probe_is_requeued_without_unavailability_backoff(self):
        self.index.ingest([movie()])
        cancel = threading.Event()
        # The run loop observes caller cancellation and relays it to the worker.
        def wait_for_cancel(*args, **kwargs):
            cancel.set()
            kwargs["cancel"].wait(2)
            return dict(status="unknown", checked_at=time.time(), evidence={})
        self.verifier.side_effect = wait_for_cancel
        result = self.audit.run(self.audit.start(), cancel=cancel)
        self.assertEqual((result["healthy"], result["unknown"], result["pending"]), (0, 0, 1))
        self.assertEqual(self.health("one"), ("unknown", 0, 0))

    def test_descriptor_expansion_queues_only_finite_children_and_preserves_series_identity(self):
        descriptor = movie("series", "Example series", "https://archive.org/details/show", archive_id="show",
                           language="sv", content_type="series")
        self.index.ingest([descriptor])
        child = archive(identifier="show", title="Example series S01E01", filename="Example series S01E01.mp4",
                        content_type="episode")
        child.update(content_type="episode", series_title="Different provider name", season=1, episode=1)
        payload = metadata(identifier="show", title="Example series", filename=child["archive_file"])
        with patch.object(audit_module.library, "_cached_json", return_value=payload), \
             patch.object(audit_module.library, "expand_item", return_value=[child]):
            result = self.audit.run(self.audit.start())
        self.assertEqual((result["expanded"], result["expanded_sources"], result["healthy"]), (1, 1, 1))
        self.assertEqual(result["total"], 2)
        saved = self.index.get(child["id"])
        self.assertEqual(saved["series_title"], descriptor["title"])
        self.assertEqual(saved["collection_key"], self.index.get("series")["collection_key"])
        self.assertEqual(self.verifier.call_count, 1)

    def test_runner_lease_prevents_duplicate_parallel_runner(self):
        self.index.ingest([movie()])
        run_id = self.audit.start()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET owner='other-runner',lease_until=?,status='running' WHERE id=?",
                       (time.time() + 60, run_id))
        result = self.audit.run(run_id)
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["pending"], 1)
        self.verifier.assert_not_called()

    def test_legacy_successes_are_requeued_and_withdrawn_when_identity_policy_changes(self):
        self.index.ingest([movie()])
        run_id = self.audit.start()
        self.assertEqual(self.audit.run(run_id)["healthy"], 1)
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET audit_policy='' WHERE id=?", (run_id,))
        upgraded = MediaHealthAudit(MediaIndex(self.index.path))
        result = upgraded.status(run_id)  # Performs local policy migration only.
        self.assertEqual((result["status"], result["healthy"], result["pending"]), ("paused", 0, 1))
        self.assertEqual(self.health("one"), ("unknown", 0, 0))
        self.assertEqual(upgraded.start(), run_id)
        self.assertEqual(upgraded.run(run_id)["healthy"], 1)
        self.assertEqual(self.verifier.call_count, 2)

    def test_descriptor_identity_changes_do_not_publish_children_of_an_obsolete_mapping(self):
        descriptor = movie("series", "Example series", "https://archive.org/details/show", archive_id="show",
                           content_type="series", language="sv")
        self.index.ingest([descriptor])
        child = archive(identifier="show", title="Example series S01E01", filename="Example series S01E01.mp4",
                        content_type="episode", series_title="Example series", season=1, episode=1)
        def change(*args, **kwargs):
            self.index.ingest([dict(descriptor, title="A different series")])
            return [child]
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(identifier="show", title="Example series")), \
             patch.object(audit_module.library, "expand_item", side_effect=change):
            result = self.audit.run(self.audit.start())
        self.assertEqual((result["changed"], result["expanded_sources"]), (1, 0))
        self.assertIsNone(self.index.get(child["id"]))
        self.verifier.assert_not_called()

    def test_status_contains_counts_not_sources_or_item_identifiers(self):
        self.index.ingest([movie("private-item-id")])
        self.audit.start()
        result = json.dumps(self.audit.status())
        self.assertNotIn("private-item-id", result)
        self.assertNotIn("https:", result)

    def test_old_collapsed_archive_expansion_is_rechecked_once_without_revoking_episode_proofs(self):
        descriptor = movie("series", "Example", "https://archive.org/details/show", archive_id="show", content_type="series")
        child = archive(identifier="show", title="Example S01E01", filename="Example S01E01.mp4",
                        content_type="episode", series_title="Example", season=1, episode=1)
        self.index.ingest([descriptor])
        with patch.object(audit_module.library, "_cached_json", return_value=metadata(identifier="show", title="Example", filename=child["archive_file"])), \
             patch.object(audit_module.library, "expand_item", return_value=[child]) as expand:
            run_id = self.audit.start()
            self.assertEqual(self.audit.run(run_id)["healthy"], 1)
            with self.index.connection() as db:
                db.execute("UPDATE media_audit_jobs SET report=? WHERE run_id=? AND state='expanded'",
                           (json.dumps(dict(status="expanded", evidence={"encoding_groups_version": 1})), run_id))
            self.assertEqual(self.audit.repair(run_id)["retried_sources"], 1)
            self.assertTrue(self.index.is_verified(child["id"]))
            self.audit.run(run_id)
            self.assertEqual(self.audit.repair(run_id)["retried_sources"], 0)
            self.assertEqual(expand.call_count, 2)
            self.assertEqual(self.verifier.call_count, 1)

    def test_film_and_series_focus_leaves_channels_queued_and_preserves_resume(self):
        self.index.ingest([movie("film"), dict(movie("episode"), content_type="episode", series_title="Show"),
                           dict(movie("channel"), content_type="live")])
        run_id = self.audit.start()
        result = self.audit.run(run_id, lanes=("movies", "series"), workers=2)
        self.assertEqual((result["healthy"], result["pending"], result["focus_done"], result["focus_total"]), (2, 1, 2, 2))
        self.assertEqual(result["active_lanes"], ["movies", "series"])
        self.assertEqual({call.args[0]["id"] for call in self.verifier.call_args_list}, {"film", "episode"})
        self.assertEqual(self.audit.run(run_id)["healthy"], 3)

    def test_vod_uses_larger_bounded_probe_while_channels_keep_fast_profile(self):
        self.index.ingest([movie("film"), dict(movie("channel"), content_type="live")])
        self.audit.run(self.audit.start(), workers=1)
        calls = {call.args[0]["id"]: call.kwargs for call in self.verifier.call_args_list}
        self.assertEqual(calls["film"]["max_seconds"], 30)
        self.assertEqual(calls["film"]["max_bytes"], 8 * 1024 * 1024)
        self.assertNotIn("max_seconds", calls["channel"])
        self.assertNotIn("max_bytes", calls["channel"])

    def test_old_vod_budget_failures_get_one_new_profile_check_without_endless_requeue(self):
        self.index.ingest([movie()])
        run_id = self.audit.start()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_jobs SET state='unknown',attempts=2,report=? WHERE run_id=?",
                       (json.dumps(dict(status="unknown", error="timeout", max_bytes=4 * 1024 * 1024)), run_id))
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 1)
        self.verifier.side_effect = lambda *a, **k: dict(status="unknown", checked_at=time.time(),
            error="timeout", max_seconds=30, max_bytes=8 * 1024 * 1024)
        self.audit.run(run_id)
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 0)
        self.assertEqual(self.verifier.call_count, 1)

    def test_content_lanes_and_series_breadth_prevent_catalogue_starvation(self):
        rows = [movie("film-" + str(n), "Film " + str(n)) for n in range(8)]
        rows += [dict(movie("live-" + str(n), "Channel " + str(n)), content_type="live") for n in range(8)]
        for series in ("First show", "Second show", "Third show"):
            rows += [dict(movie(series + str(n), series + " S01E" + str(n)), content_type="episode",
                          series_title=series, season=1, episode=n) for n in range(1, 8)]
        self.index.ingest(rows)
        seen = []
        def checked(row, **kwargs):
            seen.append((row["content_type"], row.get("series_title")))
            return proof()
        self.verifier.side_effect = checked
        self.audit.run(self.audit.start(), workers=1, max_jobs=9)
        self.assertEqual([kind for kind, _ in seen], ["live", "movie", "episode"] * 3)
        self.assertEqual(len({name for kind, name in seen if kind == "episode"}), 3)

    def test_repair_uses_current_identity_with_new_check_and_excludes_unrelated_inventory(self):
        row = movie()
        self.index.ingest([row])
        run_id = self.audit.start()
        def replace(row, **kwargs):
            self.index.ingest([dict(row, title="Corrected title")])
            return proof()
        self.verifier.side_effect = replace
        self.assertEqual(self.audit.run(run_id)["changed"], 1)
        self.index.ingest([movie("not-in-snapshot")])
        self.verifier.side_effect = proof
        repaired = self.audit.repair(run_id)
        self.assertEqual((repaired["repaired_sources"], repaired["total"], repaired["pending"]), (1, 1, 1))
        self.assertEqual(self.health("one")[0], "unknown")
        self.assertEqual(self.audit.run(run_id)["healthy"], 1)
        self.assertEqual(self.verifier.call_count, 2)
        self.assertEqual(self.health("not-in-snapshot")[0], "unknown")
        self.assertEqual(self.audit.repair(run_id)["repaired_sources"], 0)

    def test_transient_retry_is_bounded_and_source_replacement_is_not_requeued_repeatedly(self):
        self.index.ingest([movie()])
        self.verifier.side_effect = lambda *a, **k: dict(status="unknown", checked_at=time.time(), error="timeout",
            max_bytes=k.get("max_bytes", 4 * 1024 * 1024), max_seconds=k.get("max_seconds", 12))
        run_id = self.audit.start()
        first = self.audit.run(run_id, max_jobs=1)
        self.assertEqual(first["pending"], 1)
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 0)  # Already automatically queued.
        self.audit.run(run_id)
        self.assertEqual(self.audit.repair(run_id)["retried_sources"], 0)
        self.assertEqual(self.verifier.call_count, 2)
        self.index.ingest([movie(source="https://example.invalid/new.mp4")])
        self.assertEqual(self.audit.repair(run_id)["repaired_sources"], 1)
        self.verifier.side_effect = proof
        self.audit.run(run_id)
        self.assertEqual(self.audit.repair(run_id)["repaired_sources"], 0)

    def test_metadata_timeout_gets_one_retry_without_retrying_wrong_programme_labels(self):
        descriptor = movie("series", "Example", "https://archive.org/details/show", archive_id="show",
                           content_type="series")
        self.index.ingest([descriptor])
        payload = metadata(identifier="show", title="Example")
        with patch.object(audit_module.library, "_cached_json", return_value=payload), \
             patch.object(audit_module.library, "expand_item", side_effect=TimeoutError) as expansion:
            result = self.audit.run(self.audit.start())
        self.assertEqual((result["status"], result["unknown"], expansion.call_count), ("complete", 1, 2))
        self.assertEqual(self.audit.repair()["retried_sources"], 0)
        self.assertFalse(self.index.is_verified("series"))

    def test_single_worker_exception_does_not_stop_remaining_catalogue_and_never_admits_it(self):
        self.index.ingest([movie(str(n), "Film " + str(n)) for n in range(6)])
        def checked(row, **kwargs):
            if row["id"] == "0":
                raise KeyError("private-provider-diagnostic")
            return proof()
        self.verifier.side_effect = checked
        result = self.audit.run(self.audit.start(), workers=6)
        self.assertEqual((result["status"], result["healthy"], result["unknown"], result["pending"]),
                         ("complete", 5, 1, 0))
        self.assertEqual(result["last_worker_error"], "KeyError")
        self.assertNotIn("private-provider", json.dumps(result))
        self.assertFalse(self.index.is_verified("0"))
        self.assertEqual(self.verifier.call_count, 7)

    def test_parallel_decoders_share_short_serialized_catalogue_writes(self):
        self.index.ingest([movie(str(n), "Film " + str(n),
                               source="https://provider" + str(n % 32) + ".invalid/" + str(n) + ".mp4")
                           for n in range(4000)])
        barrier, lock = threading.Barrier(6), threading.Lock()
        calls = 0
        def checked(row, **kwargs):
            nonlocal calls
            with lock:
                calls += 1
                number = calls
            if number <= 6:
                barrier.wait(timeout=5)
            return proof()
        self.verifier.side_effect = checked
        result = self.audit.run(self.audit.start(), workers=16, max_jobs=80)
        self.assertEqual((result["status"], result["healthy"], result["pending"]), ("paused", 80, 3920))
        self.assertEqual(result["last_worker_error"], "")

    def test_descriptor_refresh_preserves_existing_checked_episode_label(self):
        descriptor = movie("series", "Example", "https://archive.org/details/show", archive_id="show",
                           language="sv", content_type="series")
        child = archive(identifier="show", title="S01E01 - Curated episode", filename="Example S01E01.mp4",
                        content_type="episode", series_title="Example", season=1, episode=1)
        self.index.ingest([descriptor, child])
        self.index.record(child["id"], proof(), source=child["source"], identity=self.index.identity_key(child))
        discovered = dict(child, title="Example S01E01")
        payload = metadata(identifier="show", title="Example", filename=child["archive_file"])
        with patch.object(audit_module.library, "_cached_json", return_value=payload), \
             patch.object(audit_module.library, "expand_item", return_value=[discovered]):
            result = self.audit.run(self.audit.start())
        self.assertEqual(result["changed"], 0)
        self.assertEqual(self.index.get(child["id"])["title"], child["title"])
        self.assertTrue(self.index.is_verified(child["id"]))

    def test_slow_provider_cannot_occupy_reserved_slots_of_other_content_lanes(self):
        # Simulate a slow shared provider, not a network benchmark. At least
        # one channel must still be checked while two movie calls are blocked.
        rows = [movie("film-" + str(n), "Film " + str(n)) for n in range(10)]
        rows += [dict(movie("live-" + str(n), "Channel " + str(n),
                           source="https://channels.invalid/" + str(n) + ".m3u8"),
                      content_type="live") for n in range(10)]
        self.index.ingest(rows)
        movies_active, peak_movies = 0, 0
        lock, channel_seen = threading.Lock(), threading.Event()
        def checked(row, **kwargs):
            nonlocal movies_active, peak_movies
            if row["content_type"] == "live":
                channel_seen.set()
            else:
                with lock:
                    movies_active += 1
                    peak_movies = max(peak_movies, movies_active)
                self.assertTrue(channel_seen.wait(2), "A shared provider starved the channel lane")
                with lock:
                    movies_active -= 1
            return proof()
        self.verifier.side_effect = checked
        result = self.audit.run(self.audit.start(), workers=6)
        self.assertEqual(result["healthy"], 20)
        self.assertLessEqual(peak_movies, 2)


if __name__ == "__main__":
    unittest.main()
