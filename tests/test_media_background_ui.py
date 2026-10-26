"""Actual MEDIA toggle controls, isolated from all source and audit workers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from test_media_library_ui import LibraryBridge, MediaScene, QPointF, QTest, Slot


def scenario(project):
    class BackgroundBridge(LibraryBridge):
        def __init__(self):
            super().__init__()
            self.toggles = []
            self.payload["library_background"] = dict(running=False, pausing=False, paused=True,
                phase="paused", new_movies=0, new_series=0, new_episodes=0,
                discovered_movies=0, discovered_series=0)

        @Slot(bool, result=str)
        def mediaLibraryBackground(self, enabled):
            self.toggles.append(enabled)
            self.payload["library_background"].update(running=enabled, pausing=False,
                paused=not enabled, phase="checking" if enabled else "paused")
            return self.raw()

    scene = MediaScene(project / "qml/components")
    bridge = BackgroundBridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.applyStatus(bridge.raw())
    QTest.qWait(40)
    toggle = scene.find("mediaBackgroundToggle")
    search = scene.find("workspaceMediaSearch")
    assert toggle.isVisible() and toggle.isEnabled()
    assert toggle.property("text") == "UTÖKA · AV"
    assert not bridge.toggles, "Opening MEDIA started background source work"
    # The control shares the original navigation row above Search. The player
    # retains its exact pre-control rectangle, also on narrow windows.
    geometry = []
    for width, height in [(1100, 780), (800, 600), (430, 650)]:
        scene.resize(width, height)
        player = scene.find("workspaceMediaHole")
        with_button = (player.x(), player.y(), player.width(), player.height())
        assert toggle.mapToScene(QPointF()).y() < search.mapToScene(QPointF()).y()
        scene.root.setProperty("surfaceHost", scene.bridge)
        QTest.qWait(20)
        assert (player.x(), player.y(), player.width(), player.height()) == with_button
        scene.root.setProperty("surfaceHost", bridge)
        QTest.qWait(20)
        geometry.append(with_button[2:])
    scene.resize(1100, 780)
    scene.click(toggle)
    assert bridge.toggles == [True]
    assert toggle.property("text") == "UTÖKA · PÅ"
    # Candidate discoveries are distinct from independently checked additions.
    work = dict(bridge.payload["library_background"], new_movies=3, new_series=2,
        new_episodes=17, discovered_movies=40, discovered_series=8)
    bridge.publish(library_background=work)
    QTest.qWait(20)
    assert scene.find("mediaBackgroundCounts").property("text") == "Film +3 · Serier +2 · Avsnitt +17"
    assert "Film +3" in scene.find("mediaLibraryLoadState").property("text")
    assert "40 filmer" in toggle.property("tip") and "8 serier" in toggle.property("tip")
    scene.click(toggle)
    assert bridge.toggles == [True, False]
    assert toggle.property("text") == "UTÖKA · AV"
    assert "Film +3" in scene.find("mediaLibraryLoadState").property("text")
    bridge.publish(library_background=dict(work, running=True, pausing=True, phase="pausing"))
    QTest.qWait(20)
    assert not toggle.isEnabled() and toggle.property("text") == "PAUSAR…"
    bridge.publish(library_background=dict(work, running=True, pausing=False, external=True))
    QTest.qWait(20)
    assert toggle.isEnabled() and toggle.property("text") == "UTÖKA · PÅ"
    scene.click(toggle)
    assert bridge.toggles == [True, False, False], "Existing detached work was not pausable"
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(toggle=True, explicit_only=True, candidate_counts_separate=True,
        existing_work_pause=True, geometry=geometry, warnings=0)))
    scene.close()


class MediaBackgroundUiTests(unittest.TestCase):
    def test_explicit_toggle_progress_pause_and_original_video_geometry(self):
        with tempfile.TemporaryDirectory(prefix="gg-media-background-ui-") as temporary:
            env = os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                       GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--scenario"],
                cwd=temporary, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--scenario" in sys.argv:
        scenario(PROJECT)
    else:
        unittest.main()
