"""Production transport buttons and opt-in episode autoplay with a fake decoder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from test_media_library_ui import LibraryBridge, MediaScene, QTest, Slot
from PySide6.QtMultimedia import QMediaPlayer


def scenario():
    class Bridge(LibraryBridge):
        def __init__(self):
            super().__init__()
            self.steps = []
            self.payload.update(library_loading_id="", library_auto_next=False)
            self.rows.append(dict(self.rows[7], id="music-two", title="Zulu song"))

        @Slot(str, result=str)
        def mediaPlay(self, identifier):
            super().mediaPlay(identifier)
            self.payload.update(playing=True, buffering=False, library_loading_id="")
            return self.raw()

        @Slot(bool, result=str)
        def mediaLibraryCheck(self, enabled):
            return self.raw()

        @Slot(bool, result=str)
        def mediaLibraryAutoNext(self, enabled):
            self.payload["library_auto_next"] = enabled
            return self.raw()

        @Slot(int, bool, result=str)
        def mediaLibraryStep(self, direction, automatic):
            self.steps.append((direction, automatic))
            now = self.payload["now"]
            if now["content_type"] == "episode":
                queue = sorted(self.episodes, key=lambda row: (row["season"], row["episode"]))
                season = str(scene.root.property("seasonFilter"))
                if automatic and season != "all":
                    queue = [row for row in queue if str(row["season"]) == season]
            else:
                queue = sorted([row for row in self.rows if row["kind"] == now["kind"]
                                and row["content_type"] == now["content_type"]], key=lambda row: row["title"])
            index = next(i for i, row in enumerate(queue) if row["id"] == now["id"]) + direction
            if 0 <= index < len(queue):
                return self.mediaPlay(queue[index]["id"])
            return self.raw()

    scene = MediaScene(PROJECT / "qml/components")
    bridge = Bridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.applyStatus(bridge.raw())
    QTest.qWait(40)
    navigation = scene.find("mediaPlaybackNavigation")
    check = scene.find("mediaSourceCheckToggle")
    assert navigation.y() < check.y(), "Playback controls were not placed above source checking"
    for page, first, second in [("live", "live-a", "live-b"), ("movies", "movie-a", "movie-z"),
                                ("music", "music-one", "music-two")]:
        scene.root.selectPage(page)
        scene.root.playItem(first)
        QTest.qWait(40)
        scene.click("mediaPlayNext")
        QTest.qWait(40)
        assert bridge.payload["now"]["id"] == second, page
        scene.click("mediaPlayPrevious")
        QTest.qWait(40)
        assert bridge.payload["now"]["id"] == first, page

    scene.root.selectPage("series")
    QTest.qWait(30)
    scene.click("mediaCatalogRow_series-one")
    QTest.qWait(30)
    scene.root.setProperty("seasonFilter", "1")
    scene.root.playItem("episode-1")
    QTest.qWait(40)
    player = scene.find("mediaVideoPlayer")

    def end(position=10000, error=QMediaPlayer.NoError):
        player.setProperty("mediaStatus", QMediaPlayer.BufferedMedia.value)
        player.setProperty("duration", 10000)
        player.setProperty("position", position)
        player.setProperty("error", error.value)
        player.setProperty("mediaStatus", QMediaPlayer.EndOfMedia.value)
        QTest.qWait(40)

    before = len(bridge.steps)
    end()
    assert len(bridge.steps) == before, "Episodes advanced without opting in"
    scene.click("mediaAutoNextEpisodes")
    scene.root.playItem("episode-1")
    QTest.qWait(40)
    end(position=1000)
    assert len(bridge.steps) == before, "Premature EOF advanced the episode"
    scene.root.playItem("episode-1")
    QTest.qWait(40)
    end(error=QMediaPlayer.ResourceError)
    assert len(bridge.steps) == before, "A failed episode started another one"
    scene.root.playItem("episode-1")
    QTest.qWait(40)
    end()
    assert bridge.steps[-1] == (1, True)
    assert bridge.payload["now"]["id"] == "episode-2"
    scene.root.finishVideo()
    QTest.qWait(20)
    assert len(bridge.steps) == before + 1, "Duplicate completion advanced two episodes"
    end()
    assert bridge.payload["now"]["id"] == "episode-10", "Episode order was lexicographic"
    end()
    assert bridge.payload["now"]["id"] == "episode-10", "Autoplay wrapped or left the selected season"
    scene.root.goBack()
    scene.root.selectPage("movies")
    scene.root.playItem("movie-a")
    QTest.qWait(40)
    before = len(bridge.steps)
    end()
    assert len(bridge.steps) == before, "Episode autoplay advanced a film"
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(previous_next=True, all_types=True, opt_in=True, same_season=True,
                          natural_episode_order=True, duplicate_eof_guard=True, error_guard=True, warnings=0)))
    scene.close()


class PlaybackNavigationUiTests(unittest.TestCase):
    def test_transport_and_safe_episode_autoplay(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, GG_DESKTOP_STATE_ROOT=temporary + "/state", GG_DESKTOP_DATA_ROOT=temporary + "/data")
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--scenario"],
                cwd=temporary, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    scenario() if "--scenario" in sys.argv else unittest.main()
