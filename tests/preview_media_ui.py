"""Render MEDIA with offline fixtures; no network, user library or app restart."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_media_library_ui import MediaScene, PROJECT
from PySide6.QtTest import QTest


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="gg-media-preview-"))
    output.mkdir(parents=True, exist_ok=True)
    scene = MediaScene(PROJECT / "qml/components")
    geometry = []
    pages = [
        ("live", 1100, 780), ("movies", 1100, 780), ("series", 1100, 780),
        ("episodes", 1100, 780), ("downloads", 1100, 780),
        ("movies-narrow", 430, 650), ("empty", 800, 600), ("loading", 800, 600),
    ]
    for name, width, height in pages:
        scene.resize(width, height)
        page = name.split("-")[0]
        if page in ("empty", "loading"):
            scene.root.selectPage("movies")
            scene.bridge.publish(items=[], library_busy=page == "loading", library_error="")
        elif page == "episodes":
            scene.root.selectPage("series")
            scene.root.setProperty("statusJson", scene.bridge.mediaOpenCollection("series-one"))
        else:
            scene.root.selectPage(page)
            scene.bridge.publish(items=scene.bridge.mode_rows(scene.bridge.payload["mode"]), library_collection="",
                                 library_busy=False, library_query="", library_error="")
        QTest.qWait(80)
        destination = output / (name + ".png")
        if not scene.window.grabWindow().save(str(destination)):
            raise RuntimeError("Could not save preview " + str(destination))
        hole = scene.find("workspaceMediaHole")
        geometry.append(dict(page=name, window=[width, height],
                             player=[hole.x(), hole.y(), hole.width(), hole.height()]))
    assert not scene.warnings, scene.warnings
    (output / "geometry.json").write_text(json.dumps(geometry, indent=2), encoding="utf-8")
    scene.close()
    print(json.dumps(dict(output=str(output), pages=len(pages), warnings=len(scene.warnings))))


if __name__ == "__main__":
    main()
