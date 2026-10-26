"""Real QML row actions and separate language controls with offline fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from test_media_library_ui import LibraryBridge, MediaScene, QTest, Slot, QPoint, QPointF
from backend.media_languages import options


def scenario(output=None):
    class Bridge(LibraryBridge):
        def __init__(self):
            super().__init__()
            self.hidden = set()
            self.payload.update(library_discovery_languages=["sv", "en"],
                                library_discovery_types=["live", "movies", "series", "music", "radio", "downloads", "games"],
                                library_discovery_language_options=options(discovery=True))

        @Slot(bool, result=str)
        def mediaLibraryBackground(self, enabled):
            return self.raw()

        @Slot(bool, result=str)
        def mediaLibraryCheck(self, enabled):
            self.calls.append(("check", enabled))
            self.payload["library_background"] = dict(operation="check", running=enabled, pausing=False,
                phase="checking" if enabled else "paused", checked_existing=42)
            return self.raw()

        @Slot(str, result=str)
        def mediaLibraryLanguages(self, selected):
            self.calls.append(("languages", selected))
            self.payload["library_discovery_languages"] = selected.split("; ")
            return self.raw()

        @Slot(str, result=str)
        def mediaLibraryTypes(self, selected):
            self.calls.append(("types", selected))
            self.payload["library_discovery_types"] = selected.split("; ")
            return self.raw()

        @Slot(str, result=str)
        def mediaLibraryDiagnose(self, identifier):
            self.calls.append(("diagnose", identifier))
            self.payload["library_diagnostic"] = dict(running=False, message="Länken har tagits bort (404). En ersättningskälla finns.",
                replacement_id="movie-z")
            return self.raw()

        @Slot(str, bool, result=str)
        def mediaLibraryHideSource(self, identifier, hidden):
            self.calls.append(("hide", identifier, hidden))
            if hidden:
                self.hidden.add(identifier)
            else:
                self.hidden.discard(identifier)
            self.payload.update(items=[row for row in self.mode_rows(self.payload["mode"]) if row["id"] not in self.hidden])
            self.payload["library_revision"] += 1
            return self.raw()

    scene = MediaScene(PROJECT / "qml/components")
    bridge = Bridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.applyStatus(bridge.raw())
    scene.root.selectPage("live")
    QTest.qWait(60)
    listing = scene.find("workspaceMediaCatalog")
    for page, identifier in [("live", "live-a"), ("movies", "movie-a"), ("series", "series-one"),
                             ("radio", "radio-one"), ("music", "music-one"), ("games", "game-one")]:
        scene.root.selectPage(page)
        QTest.qWait(30)
        assert scene.find("mediaDiagnose_" + identifier).isVisible(), page
        assert scene.find("mediaRemove_" + identifier).isVisible(), page
    scene.root.selectPage("movies")
    QTest.qWait(40)
    QTest.mouseMove(scene.window, QPoint(600, 400))
    QTest.qWait(160)
    action = scene.find("mediaDiagnose_movie-a")
    assert abs(action.property("contentItem").opacity() - .2) < .01
    QTest.mouseMove(scene.window, action.mapToScene(QPointF(10, 10)).toPoint())
    QTest.qWait(160)
    assert action.property("contentItem").opacity() > .99, "Hover did not brighten the row icon"
    before = len(bridge.calls)
    scene.click("mediaDiagnose_movie-a")
    QTest.qWait(30)
    assert bridge.calls[before:] == [("diagnose", "movie-a")], "Row diagnostic also triggered playback"
    assert "404" in scene.find("mediaDiagnosticMessage").property("text")
    scene.find("mediaDiagnosticPopup").close()
    scene.click("mediaRemove_movie-a")
    QTest.qWait(30)
    assert bridge.calls[-1] == ("hide", "movie-a", True)
    assert listing.property("count") == 3
    scene.click("mediaUndoRemove")
    QTest.qWait(30)
    assert bridge.calls[-1] == ("hide", "movie-a", False)
    assert listing.property("count") == 4
    assert scene.root.property("languageFilter") == "sv; en"
    scene.click("mediaDiscoveryFilterButton")
    QTest.qWait(30)
    scene.click("mediaDiscoveryType_games")
    QTest.qWait(30)
    assert bridge.calls[-1] == ("types", "live; movies; series; music; radio; downloads")
    scene.click("mediaDiscoveryTypesAll")
    QTest.qWait(30)
    assert len(bridge.payload["library_discovery_types"]) == 7
    assert scene.find("mediaBackgroundCounts").property("text").startswith("Alla medier")
    scene.click("mediaDiscoveryLanguage_en")
    QTest.qWait(20)
    assert bridge.calls[-1] == ("languages", "sv")
    assert scene.root.property("languageFilter") == "sv; en", "Discovery selection changed the display filter"
    assert not scene.find("mediaDiscoveryLanguage_sv").isEnabled(), str(scene.evaluate("JSON.stringify(discoveryLanguages)")) + " " + str(scene.find("mediaDiscoveryLanguage_sv").property("checked"))
    scene.find("mediaDiscoveryFilterPopup").close()
    scene.root.setDiscoveryTypes(["music"])
    QTest.qWait(20)
    scene.root.selectPage("music")
    QTest.qWait(30)
    assert scene.find("mediaDiscoveryFilterButton").isVisible(), "Search scope was hidden outside video tabs"
    assert scene.find("mediaBackgroundCounts").property("text").startswith("Musik")
    scene.root.setDiscoveryTypes(["live", "movies", "series", "music", "radio", "downloads", "games"])
    scene.root.selectPage("movies")
    QTest.qWait(30)
    source_check = scene.find("mediaSourceCheckToggle")
    assert source_check.isVisible()
    scene.click(source_check)
    QTest.qWait(30)
    assert bridge.calls[-1] == ("check", True)
    assert "Pausa" in source_check.property("text")
    assert not scene.find("mediaBackgroundToggle").isEnabled(), "Two source workers could be started together"
    scene.click(source_check)
    QTest.qWait(30)
    assert bridge.calls[-1] == ("check", False)
    assert "Starta" in source_check.property("text")
    assert "42" in scene.find("mediaLibraryLoadState").property("text")
    if output:
        output.mkdir(parents=True, exist_ok=True)
        for width, height in [(1100, 780), (430, 650)]:
            scene.resize(width, height)
            QTest.qWait(30)
            scene.window.grabWindow().save(str(output / ("media-" + str(width) + ".png")))
        scene.resize(800, 650)
        scene.click("mediaDiscoveryFilterButton")
        QTest.qWait(30)
        scene.window.grabWindow().save(str(output / "search-languages.png"))
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(row_actions=True, all_media_types=True, undo=True, independent_search_languages=True, warnings=0)))
    scene.close()


class MediaFilterActionsUiTests(unittest.TestCase):
    def test_row_buttons_do_not_play_and_language_selection_is_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, GG_DESKTOP_STATE_ROOT=temporary + "/state", GG_DESKTOP_DATA_ROOT=temporary + "/data")
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--scenario"],
                cwd=temporary, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--scenario" in sys.argv:
        scenario(Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    else:
        unittest.main()
