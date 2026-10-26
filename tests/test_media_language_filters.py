"""Language recovery, exact filters, reversible exclusions and source repair."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from backend import media_languages as languages, media_discovery as discovery
from backend import media_sources as sources, media_diagnostics as diagnostics
from backend.media_health_audit import MediaHealthAudit
from backend.media_index import MediaIndex, view_request


def item(identifier, language="en", title=None, **extra):
    return dict(id=identifier, title=title or identifier, language=language, kind="TV", content_type="live",
                source="https://example.invalid/" + identifier + ".m3u8", channel_id=title or identifier, **extra)


def proof(status="verified", error=""):
    now = time.time()
    return dict(status=status, checked_at=now, expires_at=now + 600 if status == "verified" else 0,
                error=error, scope="http_media", evidence={"decoded": False})


class LanguageFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.index = MediaIndex(Path(self.temp.name) / "library.sqlite3")
        self.index.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_codes_and_names_are_normalized_without_substring_matches(self):
        self.assertEqual(languages.codes("swe; en-US; fra; Swedish"), ("sv", "en", "fr"))
        self.assertEqual(languages.label("eng; swe"), "Engelska / Svenska")
        self.assertFalse(languages.matches("Bengali", "en"))
        self.assertTrue(languages.matches(["fre", "eng"], "sv; en"))
        options = languages.options(["fr; en", "swe"])
        self.assertEqual([r["label"] for r in options[:4]], ["Alla språk", "Svenska och engelska", "Svenska", "Engelska"])
        self.assertIn(dict(value="fr", label="Franska"), options)

    def test_explicit_audio_evidence_recovers_unknowns_without_guessing_from_titles_or_subtitles(self):
        for row, expected in [
            (dict(title="Film (English)"), "en"),
            (dict(title="Film", description="Språk: svenska"), "sv"),
            (dict(title="Film", description="Dubbed in English"), "en"),
            (dict(title="Film [EN]"), "en"),
            (dict(title="The English Patient"), ""),
            (dict(title="Swedish subtitles"), ""),
            (dict(title="A Swedish Film with English subtitles"), ""),
            (dict(title="English audio with Swedish subtitles"), "en"),
            (dict(title="Film", description="Textad på svenska"), ""),
        ]:
            with self.subTest(row=row):
                self.assertEqual(languages.classify(row)["language"], expected)
        self.assertEqual(languages.classify(dict(title="Unknown"), dict(audio_language="swe"))["language"], "sv")

    def test_catalogue_matches_individual_languages_in_multilingual_rows_and_checked_only(self):
        self.index.ingest([item("a", "en; fr"), item("b", "swe"), item("c", "de"), item("d", "")])
        self.index.record("a", proof())
        view = view_request("live", language="sv; en")
        self.assertEqual({row["id"] for row in self.index.browse(view)["items"]}, {"a", "b"})
        self.assertEqual([row["id"] for row in self.index.browse(dict(view, available_only=True))["items"]], ["a"])
        self.assertEqual([row["id"] for row in self.index.browse(view_request("live", language="unknown"))["items"]], ["d"])

    def test_unknown_discoveries_are_staged_and_each_search_language_has_its_own_cursor(self):
        queries = []
        def provider(url, validator):
            query = parse_qs(urlsplit(url).query)["q"][0]
            queries.append(query)
            docs = [dict(identifier="a001", title="Film (Swedish)", language="", mediatype="movies"),
                    dict(identifier="a002", title="Unknown film", mediatype="movies"),
                    dict(identifier="a003", title="French film", language="fre", mediatype="movies")]
            result = dict(responseHeader=dict(params=dict(qin=query)), response=dict(start=0, numFound=100, docs=docs))
            self.assertTrue(validator(result))
            return result
        with patch.object(discovery.library, "_cached_json", side_effect=provider):
            discovery.discover(self.index, "movies", max_pages=1, selected_languages="sv; en")
            discovery.discover(self.index, "movies", max_pages=1, selected_languages="fr")
        self.assertIn("-language:[* TO *]", queries[0])
        self.assertNotIn("identifier:{", queries[1])
        self.assertIn('language:"fr"', queries[1])
        self.assertIsNotNone(self.index.get("archive:a002"), "Unclassified candidate was discarded")
        self.assertEqual(self.index.get("archive:a001")["language"], "sv")

    def test_audit_identifies_unknown_before_language_selection_and_never_probes_known_wrong_language(self):
        self.index.ingest([item("english", ""), item("french", "fr"), item("uncertain", "")])
        calls = []
        def identify(row, **kwargs):
            return dict(row, language="en" if row["id"] == "english" else "")
        def verify(row, **kwargs):
            calls.append(row["id"])
            return proof()
        audit = MediaHealthAudit(self.index, verifier=verify)
        with patch.object(languages, "identify_remote", side_effect=identify):
            audit.run(audit.start(), max_seconds=5, selected_languages="sv; en")
        self.assertEqual(calls, ["english"])
        self.assertEqual(self.index.get("english")["language"], "en")
        self.assertIsNotNone(self.index.get("uncertain"))
        self.assertFalse(self.index.is_verified("uncertain"))

    def test_removing_a_title_hides_alternatives_persists_rediscovery_and_can_be_undone(self):
        rows = [item("a", title="One channel"), item("b", title="One channel"), item("c", title="Another channel")]
        self.index.ingest(rows)
        self.index.hide_source("a")
        self.index.ingest_discovered(rows)
        self.assertEqual([row["id"] for row in self.index.browse(view_request("live"))["items"]], ["c"])
        self.index.hide_source("a", hidden=False)
        self.assertEqual(self.index.browse(view_request("live"))["library_total"], 2)

    def test_hidden_title_stays_hidden_after_language_identification_and_undo_restores_it(self):
        row = dict(item("film", ""), content_type="movie")
        self.index.ingest([row])
        self.index.hide_source("film")
        self.index.ingest_discovered([dict(row, language="en")])
        self.assertEqual(self.index.browse(view_request("movies", language="en"))["library_total"], 0)
        self.index.hide_source("film", hidden=False)
        self.assertEqual(self.index.browse(view_request("movies", language="en"))["library_total"], 1)

    def test_diagnostics_explains_failed_link_and_finds_same_channel_substitute(self):
        self.index.ingest([item("bad", title="Same channel"), item("good", title="Same channel"), item("unrelated")])
        def verify(row, **kwargs):
            return proof("failed", "http_not_found") if row["id"] == "bad" else proof()
        with patch.object(diagnostics.quick, "quick_check", side_effect=verify) as check:
            report = diagnostics.diagnose(self.index, "bad")
        self.assertIn("404/410", report["message"])
        self.assertEqual(report["replacement_id"], "good")
        self.assertEqual([call.args[0]["id"] for call in check.call_args_list], ["bad", "good"])
        self.assertFalse(self.index.is_verified("bad"))
        self.assertTrue(self.index.is_verified("good"))

    def test_channel_import_recovers_feed_language_and_retains_unresolved_candidates(self):
        data = dict(
            streams=[dict(channel=code, url="https://example.invalid/" + code + ".m3u8", title=code)
                     for code in ("english", "french", "unknown")],
            channels=[dict(id=code, name=code) for code in ("english", "french", "unknown")],
            feeds=[dict(channel="english", id="main", is_main=True, languages=["eng"]),
                   dict(channel="french", id="main", is_main=True, languages=["fra"])])
        with patch.object(sources, "_fetch_json", side_effect=lambda endpoint, **kw: data[endpoint]):
            report = sources.refresh(self.index)
        self.assertEqual(report["candidate_sources"], 2)
        self.assertEqual(report["filtered_languages"], 1)
        self.assertEqual(self.index.browse(view_request("live", language="en"))["library_total"], 1)
        self.assertEqual(self.index.browse(view_request("live", language="unknown"))["library_total"], 1)

    def test_series_diagnostic_checks_a_real_episode_without_claiming_the_whole_series_works(self):
        episode = dict(item("episode", title="A series S01E01"), content_type="episode",
                       series_title="A series", season=1, episode=1)
        self.index.ingest([episode])
        series = self.index.browse(view_request("series"))["items"][0]
        with patch.object(diagnostics.quick, "quick_check", return_value=proof()):
            report = diagnostics.diagnose(self.index, series["id"])
        self.assertEqual(report["replacement_id"], "episode")
        self.assertIn("övriga avsnitt kontrolleras separat", report["message"])

    def test_a_changed_source_cannot_receive_its_predecessors_diagnostic_result(self):
        self.index.ingest([item("channel")])
        def change(row, **kwargs):
            self.index.ingest([dict(row, source="https://example.invalid/replaced.m3u8")])
            return proof()
        with patch.object(diagnostics.quick, "quick_check", side_effect=change):
            report = diagnostics.diagnose(self.index, "channel")
        self.assertEqual(report["status"], "unknown")
        self.assertFalse(report["replacement_id"])
        self.assertFalse(self.index.is_verified("channel"))


if __name__ == "__main__":
    unittest.main()
