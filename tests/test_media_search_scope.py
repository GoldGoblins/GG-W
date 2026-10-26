"""Selected media types govern actual providers, imports and finite workers."""
from pathlib import Path
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import MagicMock, patch

from backend import media_search_scope as scope, media_background_work as background
from backend.media_index import MediaIndex, view_request
from backend import media_quick_availability as quick


def row(identifier, kind="MUSIC", language="en", **values):
    return dict(id=identifier, kind=kind, title=identifier, language=language,
                source="https://example.invalid/" + identifier + ".mp3", **values)


class MediaSearchScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.index = MediaIndex(Path(self.temp.name) / "index.sqlite3")
        self.index.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_single_multiple_and_all_choices_have_stable_order_and_reject_invalid_or_empty(self):
        self.assertEqual(scope.types("games; music; games"), ("music", "games"))
        self.assertEqual(scope.types("all"), scope.DEFAULT_TYPES)
        for value in ("", [], "movies;invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scope.types(value)

    def test_music_and_games_selection_never_calls_video_or_radio_providers(self):
        game = row("one-game", "GAME", media="rom")
        with patch.object(scope.contract, "music_catalog", return_value=[row("one-song")]) as music, \
             patch.object(scope.contract, "game_catalog", return_value=[game]), \
             patch.object(scope.contract, "homebrew_search", return_value=[]) as games, \
             patch.object(scope.contract, "radio_browser_stations", side_effect=AssertionError("Unselected radio provider")), \
             patch.object(background, "discover", side_effect=AssertionError("Unselected video provider")), \
             patch.object(background, "_make_audit", side_effect=AssertionError("No video checks were selected")):
            status = background.MediaBackgroundWork(self.index).run(threading.Event(),
                selected_types=("music", "games"), selected_languages=("sv", "en"), max_seconds=5)
        self.assertEqual(status["phase"], "complete")
        self.assertEqual(status["selected_types"], ["music", "games"])
        self.assertEqual((status["new_music"], status["new_games"]), (1, 1))
        music.assert_called_once()
        self.assertEqual(games.call_args.kwargs["pages"], 1)

    def test_all_types_reach_each_selected_provider_once_with_only_video_audit_lanes(self):
        audit = MagicMock()
        audit.start.return_value = 1
        audit.run.return_value = {"status": "complete"}
        with patch.object(background, "discover", return_value={"new_candidates": 0}) as video, \
             patch.object(scope, "collect", return_value={"new_candidates": 0}) as other, \
             patch.object(background, "_make_audit", return_value=audit):
            status = background.MediaBackgroundWork(self.index).run(threading.Event(), selected_types="all", max_seconds=5)
        self.assertEqual([call.args[1] for call in video.call_args_list], ["movies", "series"])
        self.assertEqual([call.args[1] for call in other.call_args_list], ["live", "music", "radio", "downloads", "games"])
        self.assertEqual(audit.run.call_args.kwargs["lanes"], ("live", "movies", "series"))
        self.assertEqual(status["selected_types"], list(scope.DEFAULT_TYPES))

    def test_one_provider_failure_does_not_cancel_other_selected_types(self):
        with patch.object(scope.contract, "music_catalog", side_effect=OSError), \
             patch.object(scope.contract, "game_catalog", return_value=[row("one-game", "GAME")]), \
             patch.object(scope.contract, "homebrew_search", return_value=[]):
            status = background.MediaBackgroundWork(self.index).run(threading.Event(), selected_types="music;games", max_seconds=5)
        self.assertEqual(status["errors"], 1)
        self.assertEqual(status["new_games"], 1)
        self.assertIn("källfel", status["notice"])

    def test_movie_only_search_restricts_provider_query_and_rejects_unselected_series(self):
        docs = [row("A movie", "TV", content_type="movie"), row("A series", "TV", content_type="series")]
        with patch.object(scope.library, "search_archive", return_value=docs) as archive, \
             patch.object(scope, "collect", side_effect=AssertionError("Unselected provider")):
            scope.search(self.index, "A", selected_types="movies", selected_languages="en")
        self.assertEqual(archive.call_args.kwargs["selected_media_types"], ("movies",))
        self.assertIsNotNone(self.index.get("A movie"))
        self.assertIsNone(self.index.get("A series"))

    def test_mixed_audio_and_game_search_enforces_query_and_language_without_discarding_unknowns(self):
        songs = [row("Alpha English"), row("Beta English"), row("Alpha French", language="fr"), row("Alpha unknown", language="")]
        with patch.object(scope.contract, "music_catalog", return_value=songs), \
             patch.object(scope.contract, "game_catalog", return_value=[]), \
             patch.object(scope.contract, "homebrew_search", return_value=[row("Alpha game", "GAME")]) as games, \
             patch.object(scope.library, "search_archive", side_effect=AssertionError("Unselected archive provider")):
            scope.search(self.index, "Alpha", selected_types="music;games", selected_languages="en")
        self.assertEqual(self.index.browse(view_request("music"))["library_total"], 2)
        self.assertIsNotNone(self.index.get("Alpha unknown"))
        self.assertIsNone(self.index.get("Alpha French"))
        self.assertEqual(games.call_args.kwargs, dict(query="Alpha", pages=1))

    def test_cancelled_slice_never_starts_a_provider(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(scope, "collect") as provider:
            background.MediaBackgroundWork(self.index).run(cancel, selected_types="all")
        provider.assert_not_called()

    @staticmethod
    def available(*args, **kwargs):
        now = time.time()
        return dict(schema=quick.SCHEMA, status="verified", scope="http_media", checked_at=now,
                    expires_at=now + 600, evidence=dict(decoded=False, reachable=True))

    def test_check_only_revisits_saved_healthy_video_without_any_discovery(self):
        self.index.ingest([row("saved-movie", "TV", content_type="movie")])
        self.index.record("saved-movie", self.available())
        work = background.MediaBackgroundWork(self.index)
        with patch.object(background, "discover", side_effect=AssertionError("Check-only performed discovery")), \
             patch.object(scope, "collect", side_effect=AssertionError("Check-only searched a provider")), \
             patch.object(quick, "quick_check", side_effect=self.available) as verify:
            first = work.run(threading.Event(), selected_types="movies", selected_languages="en", check_only=True, max_seconds=5)
            second = work.run(threading.Event(), selected_types="movies", selected_languages="en", check_only=True, max_seconds=5)
        self.assertEqual((first["phase"], second["phase"]), ("complete", "complete"))
        self.assertEqual(first["operation"], "check")
        self.assertEqual(verify.call_count, 2, "A new explicit check reused an old source result")

    def test_radio_check_pauses_at_budget_resumes_saved_progress_and_then_can_start_fresh(self):
        self.index.ingest([row("station-" + str(n), "RADIO") for n in range(5)])
        work = background.MediaBackgroundWork(self.index)
        with patch.object(background, "MAX_JOBS", 2), \
             patch.object(scope, "collect", side_effect=AssertionError("Check fetched new stations")), \
             patch.object(quick, "quick_check", side_effect=self.available) as verify:
            first = work.run(threading.Event(), selected_types="radio", selected_languages="en", check_only=True, max_seconds=5)
            second = work.run(threading.Event(), selected_types="radio", selected_languages="en", check_only=True, max_seconds=5)
            third = work.run(threading.Event(), selected_types="radio", selected_languages="en", check_only=True, max_seconds=5)
            self.assertEqual([first["phase"], second["phase"], third["phase"]], ["paused", "paused", "complete"])
            self.assertEqual([first["checked_existing"], second["checked_existing"], third["checked_existing"]], [2, 4, 5])
            self.assertEqual(len({call.args[0]["id"] for call in verify.call_args_list}), 5)
            self.assertEqual(verify.call_count, 5)
            work.run(threading.Event(), selected_types="radio", selected_languages="en", check_only=True, max_seconds=5)
            self.assertEqual(verify.call_count, 7)

    def test_existing_check_respects_languages_types_and_personal_removals(self):
        self.index.ingest([row("English station", "RADIO"), row("French station", "RADIO", "fr"),
                           row("Hidden station", "RADIO"), row("English song", "MUSIC")])
        self.index.hide_source("Hidden station")
        with patch.object(quick, "quick_check", side_effect=self.available) as verify:
            background.MediaBackgroundWork(self.index).run(threading.Event(), selected_types="radio",
                selected_languages="en", check_only=True, max_seconds=5)
        self.assertEqual([call.args[0]["id"] for call in verify.call_args_list], ["English station"])

    def test_stopping_during_a_check_preserves_the_unchecked_source_for_resume(self):
        self.index.ingest([row("station", "RADIO")])
        entered, cancel = threading.Event(), threading.Event()
        def blocked(row, **kwargs):
            entered.set()
            self.assertTrue(kwargs["cancel"].wait(2))
            return self.available()
        with patch.object(quick, "quick_check", side_effect=blocked), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(background.MediaBackgroundWork(self.index).run, cancel, selected_types="radio",
                                 selected_languages="en", check_only=True, max_seconds=5)
            self.assertTrue(entered.wait(1))
            cancel.set()
            status = future.result(timeout=2)
        self.assertEqual(status["phase"], "paused")
        self.assertFalse(self.index.is_verified("station"))
        self.assertEqual(status["checked_existing"], 0)


if __name__ == "__main__":
    unittest.main()
