"""Saved list neighbours across pages and season-safe automatic episode order."""
from pathlib import Path
import tempfile
import time
import unittest

from backend.media_index import MediaIndex, view_request


class PlaybackQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.index = MediaIndex(Path(self.temp.name) / "catalog.sqlite3")
        self.index.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_neighbours_cross_page_edges_and_skip_withdrawn_or_removed_rows(self):
        self.index.ingest([dict(id=str(n), kind="TV", content_type="movie", title=f"Film {n:03}",
                               language="en", source=f"https://example.invalid/{n}.mp4") for n in range(200)])
        view = view_request("movies")
        groups = self.index.snapshot_groups(view)
        self.assertEqual(self.index.playback_neighbor(view, "79", 1, groups=groups)["item"]["id"], "80")
        self.index.record("80", dict(status="failed", checked_at=time.time()))
        self.index.hide_source("82")
        self.assertEqual(self.index.playback_neighbor(view, "79", 1, groups=groups)["item"]["id"], "81")
        self.assertEqual(self.index.playback_neighbor(view, "81", 1, groups=groups)["item"]["id"], "83")
        self.assertEqual(self.index.playback_neighbor(view, "83", -1, groups=groups)["item"]["id"], "81")
        self.assertIsNone(self.index.playback_neighbor(view, "0", -1, groups=groups))
        self.assertIsNone(self.index.playback_neighbor(view, "199", 1, groups=groups))

    def test_auto_next_uses_episode_numbers_same_series_and_respects_season_filter(self):
        rows = [dict(id=f"{show}-{season}-{episode}", kind="TV", content_type="episode", series_title=show,
                     season=season, episode=episode, title=f"{show} S{season:02}E{episode:02}", language="sv",
                     source=f"https://example.invalid/{show}-{season}-{episode}.mp4")
                for show, season, episode in [("Show", 1, 1), ("Show", 1, 2), ("Show", 1, 10), ("Show", 2, 1), ("Other", 1, 3)]]
        self.index.ingest(rows)
        collection = self.index.get("Show-1-1")["collection_key"]
        view = view_request("series", collection_key=collection, season="1", query="S01E01")
        following = self.index.playback_neighbor(view, "Show-1-1", 1, episodes_only=True)
        self.assertEqual(following["item"]["id"], "Show-1-2")
        self.assertEqual(self.index.playback_neighbor(view, "Show-1-2", 1, episodes_only=True)["item"]["id"], "Show-1-10")
        self.assertIsNone(self.index.playback_neighbor(view, "Show-1-10", 1, episodes_only=True))
        self.assertEqual(self.index.playback_neighbor(dict(view, season="all"), "Show-1-10", 1, episodes_only=True)["item"]["id"], "Show-2-1")


if __name__ == "__main__":
    unittest.main()
