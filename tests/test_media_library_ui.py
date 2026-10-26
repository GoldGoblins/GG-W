"""Offline interaction and player-size checks against the production MEDIA QML."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtCore import QObject, QPoint, QPointF, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QWheelEvent
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer
from test_media_video import FAKE_PLAYER


def fixtures():
    def row(identifier, title, kind="TV", content_type="movie", **values):
        return dict(id=identifier, title=title, kind=kind, content_type=content_type,
                    source="https://example.invalid/" + identifier + ".mp4",
                    media="stream" if content_type == "live" else "vod",
                    player="qml", play="video", is_live=content_type == "live",
                    category="Animation" if content_type in ("series", "episode") else "Film",
                    language="sv" if content_type in ("series", "episode") else "en",
                    provider="Offline fixture", **values)

    base = [
        row("movie-z", "Zulu film", year="1940"),
        row("live-b", "Beta television", content_type="live"),
        row("movie-a", "Alpha film", year="1925"),
        row("movie-number", "20,000 Leagues", year="1916"),
        row("series-one", "Barnens äventyr", content_type="series", archive_id="fixture-series"),
        row("movie-html", "<b>Literal title</b>", year="1930"),
        row("live-a", "Alpha television", content_type="live"),
        row("music-one", "Alpha song", kind="MUSIC", content_type="music"),
        row("radio-one", "Alpha radio", kind="RADIO", content_type="live"),
        row("download-one", "Alpha download", kind="FETCH", content_type="movie"),
        row("game-one", "Alpha game", kind="GAME", content_type="game"),
    ]
    episodes = [
        row("episode-10", "Barnens äventyr S01E10", content_type="episode", series_title="Barnens äventyr", season=1, episode=10),
        row("episode-2", "Barnens äventyr S01E02", content_type="episode", series_title="Barnens äventyr", season=1, episode=2),
        row("episode-1", "Barnens äventyr S01E01", content_type="episode", series_title="Barnens äventyr", season=1, episode=1),
        row("episode-s2", "Barnens äventyr S02E01", content_type="episode", series_title="Barnens äventyr", season=2, episode=1),
    ]
    return base, episodes


class LibraryBridge(QObject):
    """No real player, network, filesystem library or user state is accessed."""

    mediaStateChanged = Signal()

    def __init__(self):
        super().__init__()
        self.rows, self.episodes = fixtures()
        self.calls = []
        self.payload = dict(mode="TV", backend="", volume=70, paused=False,
                            playing=False, buffering=False, now={}, items=self.mode_rows("TV"),
                            library_busy=False, library_error="", library_query="",
                            library_collection="", library_revision=1, library_count=7,
                            tools={}, fetch={}, screen="", playback_generation=0)

    def mode_rows(self, mode):
        return [row for row in self.rows if row["kind"] == mode]

    def raw(self):
        return json.dumps(self.payload)

    def publish(self, **values):
        self.payload.update(values)
        self.payload["library_revision"] += 1
        self.mediaStateChanged.emit()
        QGuiApplication.processEvents()

    @Slot(result=str)
    def mediaStatus(self):
        return self.raw()

    @Slot(result=str)
    def mediaLiveStatus(self):
        return self.raw()

    @Slot(str, result=str)
    def mediaSetMode(self, mode):
        self.calls.append(("mode", mode))
        self.payload.update(mode=mode, items=self.mode_rows(mode), library_collection="",
                            library_query="", library_error="", library_busy=False)
        return self.raw()

    @Slot(str, result=str)
    def mediaPlay(self, identifier):
        self.calls.append(("play", identifier))
        selected = next(row for row in self.rows + self.episodes if row["id"] == identifier)
        self.payload.update(now=selected, backend="qml", playing=False, buffering=True)
        self.payload["playback_generation"] += 1
        return self.raw()

    @Slot(str, result=str)
    def mediaOpenCollection(self, identifier):
        self.calls.append(("collection", identifier))
        self.payload.update(items=self.episodes, library_collection="Barnens äventyr",
                            library_query="", library_error="", library_busy=False)
        self.payload["library_revision"] += 1
        return self.raw()

    @Slot(result=str)
    def mediaLibraryBack(self):
        self.calls.append(("back",))
        self.payload.update(items=self.mode_rows(self.payload["mode"]), library_collection="",
                            library_query="", library_error="", library_busy=False)
        self.payload["library_revision"] += 1
        return self.raw()

    @Slot(str, result=str)
    def mediaLibrarySearch(self, query):
        self.calls.append(("search", query))
        self.payload.update(items=[row for row in self.mode_rows(self.payload["mode"])
                                   if query.casefold() in row["title"].casefold()],
                            library_query=query, library_busy=False, library_error="")
        self.payload["library_revision"] += 1
        return self.raw()

    @Slot(str, result=str)
    def mediaSearch(self, query):
        return self.mediaLibrarySearch(query)

    @Slot(result=str)
    def mediaLibraryRefresh(self):
        self.calls.append(("refresh",))
        self.payload.update(library_busy=True, library_error="")
        return self.raw()

    @Slot(result=str)
    def mediaStartFetch(self):
        self.calls.append(("torlink",))
        return self.raw()

    @Slot(bool, bool)
    def mediaReportPlayerState(self, playing, buffering):
        self.payload.update(playing=playing, buffering=buffering)

    @Slot(float, float)
    def mediaReportClock(self, position, duration):
        self.payload.update(position=position, duration=duration)

    @Slot()
    def hideMedia(self):
        pass


class MediaScene:
    def __init__(self, components: Path, width=1100, height=780):
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        family = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"
        if os.name == "nt":
            for filename in ("consola.ttf", "consolab.ttf", "seguisym.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / filename))
        QFont.insertSubstitution("monospace", family)
        self.app.setFont(QFont(family))
        self.window = QQuickWindow()
        self.window.setColor("#161616")
        self.window.resize(width, height)
        self.window.show()
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda rows: self.warnings.extend(row.toString() for row in rows))
        self.component = QQmlComponent(self.engine)
        source = (components / "MediaSurface.qml").read_text(encoding="utf-8")
        assert source.count("MediaPlayer {") == 1
        self.component.setData(source.replace("MediaPlayer {", FAKE_PLAYER, 1).encode(),
                               QUrl.fromLocalFile(str(components / "MediaSurface.qml")))
        assert not self.component.isError(), self.component.errors()
        self.root = self.component.create()
        assert self.root is not None, self.component.errors()
        self.root.setParentItem(self.window.contentItem())
        self.bridge = LibraryBridge()
        self.root.setProperty("surfaceHost", self.bridge)
        self.resize(width, height)
        self.root.setProperty("statusJson", self.bridge.raw())
        QTest.qWait(60)

    def resize(self, width, height):
        self.window.resize(width, height)
        self.root.setWidth(width)
        self.root.setHeight(height)
        QTest.qWait(40)

    def find(self, name):
        # Delegates are visual children even when ListView owns their QObject parent.
        found = self.root.findChild(QObject, name)
        if found is not None:
            return found
        pending = [self.root, self.window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        raise AssertionError("Missing QML item: " + name)

    def evaluate(self, expression, target=None):
        target = target or self.root
        value = QQmlExpression(qmlContext(target), target, expression)
        result = value.evaluate()
        assert not value.hasError(), value.error().toString()
        result = result[0] if isinstance(result, tuple) else result
        return result.toVariant() if hasattr(result, "toVariant") else result

    def click(self, target):
        item = self.find(target) if isinstance(target, str) else target
        assert item.isEnabled() and item.isVisible(), item.objectName()
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        assert 0 <= point.x() < self.window.width() and 0 <= point.y() < self.window.height(), point
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(30)

    def close(self):
        self.root.setProperty("surfaceHost", None)
        self.root.setProperty("statusJson", "{}")
        self.window.close()
        self.app.processEvents()


def run_fixture(staging: Path):
    scene = MediaScene(staging / "components")
    scene.click("mediaNav_movies")
    assert scene.root.property("libraryPage") == "movies"
    listing = scene.find("workspaceMediaCatalog")
    assert listing.property("count") == 4, "Films and live television were mixed"
    film_ids = scene.evaluate("filteredItems.map(function(row) { return row.id })")
    assert film_ids.index("movie-a") < film_ids.index("movie-z"), film_ids
    literal = scene.find("mediaCatalogRow_movie-html")
    assert scene.evaluate("contentItem.children[0].textFormat === Text.PlainText", literal)
    assert scene.root.toMediaUrl(r"C:\Media\A film #1.mp4") == "file:///C:/Media/A%20film%20%231.mp4"
    assert not scene.bridge.calls or all(call[0] != "play" for call in scene.bridge.calls)

    # The size constraint is measured against the polished original MEDIA pane,
    # not inferred from source strings or a screenshot's apparent proportions.
    geometry = []
    for width, height, minimum_width, minimum_height in (
        (800, 600, 540, 516), (1100, 780, 840, 696), (430, 650, 270, 554)
    ):
        scene.resize(width, height)
        hole = scene.find("workspaceMediaHole")
        values = dict(window=[width, height], player=[hole.width(), hole.height()])
        assert hole.width() >= minimum_width - 0.01, values
        assert hole.height() >= minimum_height - 0.01, values
        assert hole.isVisible(), values
        geometry.append(values)
    scene.resize(1100, 780)

    # Alphabet and media type are independent constraints, with a clear reset.
    scene.root.setProperty("libraryLetter", "A")
    QTest.qWait(30)
    assert listing.property("count") == 1, "Alphabet filter ignored film type"
    scene.root.setProperty("libraryLetter", "B")
    QTest.qWait(30)
    assert listing.property("count") == 0, "A series leaked into the B film filter"
    scene.root.setProperty("libraryLetter", "all")
    QTest.qWait(30)
    assert listing.property("count") == 4

    alphabet = scene.evaluate("model.map(function(row) { return row.value })", scene.find("mediaLetterSelector"))
    assert all(letter in alphabet for letter in ("Å", "Ä", "Ö")), alphabet
    before_swedish = list(scene.bridge.payload["items"])
    swedish = dict(before_swedish[0], id="movie-swedish", title="Återkomsten")
    scene.bridge.publish(items=before_swedish + [swedish])
    scene.root.setProperty("libraryLetter", "Å")
    QTest.qWait(30)
    assert listing.property("count") == 1, "Swedish alphabet selector cannot find Å"
    scene.root.setProperty("libraryLetter", "all")
    scene.bridge.publish(items=before_swedish)
    QTest.qWait(30)

    scene.click("mediaCatalogRow_movie-a")
    assert scene.bridge.calls[-1] == ("play", "movie-a")
    assert scene.root.property("liveVideo") is False, "On-demand film is treated as a live loop"
    player = scene.find("mediaVideoPlayer")
    player.setProperty("mediaStatus", QMediaPlayer.EndOfMedia.value)
    QTest.qWait(20)
    assert scene.root.property("playerEnded") is True
    assert not scene.find("mediaVideoRetryTimer").property("running"), "Finished film began looping"
    source_loads = player.property("sourceLoads")
    playing = dict(scene.bridge.payload["now"])
    scene.click("mediaNav_live")
    assert listing.property("count") == 2
    assert scene.bridge.payload["now"] == playing, "Filtering interrupted the selected player"
    assert player.property("sourceLoads") == source_loads

    # Series opens its episode library, then a season, then the usual player.
    scene.click("mediaNav_series")
    assert listing.property("count") == 1
    scene.root.setProperty("libraryLetter", "B")
    QTest.qWait(30)
    assert listing.property("count") == 1, "Alphabet filter ignored series type"
    scene.click("mediaNav_movies")
    assert scene.root.property("libraryLetter") == "B", "Changing content type cleared the chosen letter"
    assert listing.property("count") == 0, "B + films included a series"
    scene.click("mediaNav_series")
    assert listing.property("count") == 1, "B + series did not retain the chosen letter"
    scene.root.setProperty("libraryLetter", "A")
    QTest.qWait(30)
    assert listing.property("count") == 0
    scene.root.setProperty("libraryLetter", "all")
    QTest.qWait(30)
    scene.root.setProperty("libraryLetter", "B")
    QTest.qWait(30)
    scene.click("mediaCatalogRow_series-one")
    assert ("collection", "series-one") in scene.bridge.calls
    assert scene.bridge.payload["library_collection"] == "Barnens äventyr"
    season = scene.find("mediaSeasonSelector")
    assert season.isVisible(), "Episodes have no season navigation"
    assert listing.property("count") == 4
    assert not scene.find("mediaLetterSelector").isVisible(), "Episode navigation wastes space on the title alphabet"
    assert not scene.find("mediaCategorySelector").isVisible(), "Episode list repeats global category controls"
    assert scene.evaluate("filteredItems.map(function(row) { return row.id })") == [
        "episode-1", "episode-2", "episode-10", "episode-s2"
    ], "Episode order is lexicographic rather than numeric"
    scene.evaluate("seasonFilter = '1'")
    QTest.qWait(30)
    assert listing.property("count") == 3
    scene.click("mediaCatalogRow_episode-2")
    assert scene.bridge.calls[-1] == ("play", "episode-2")
    scene.click("mediaLibraryBack")
    assert ("back",) in scene.bridge.calls
    assert listing.property("count") == 1
    assert scene.root.property("libraryLetter") == "B", "Back lost the series library's alphabet selection"

    scene.click("mediaNav_downloads")
    assert scene.root.property("libraryLetter") == "all", "A television alphabet filter leaked into downloaded files"
    assert listing.property("count") == 1
    assert not any(call[0] == "torlink" for call in scene.bridge.calls), "Opening downloads launched a terminal"
    scene.click("mediaCatalogRow_download-one")
    assert scene.bridge.calls[-1] == ("play", "download-one")

    # Empty search results stay empty through live status updates.
    scene.click("mediaNav_movies")
    search = scene.find("workspaceMediaSearch")
    search.setProperty("text", "not-present-anywhere")
    scene.click("mediaLibrarySearchButton")
    QTest.qWait(40)
    assert ("search", "not-present-anywhere") in scene.bridge.calls
    assert listing.property("count") == 0
    scene.bridge.publish()
    QTest.qWait(30)
    assert listing.property("count") == 0

    # Background metadata updates must not replace delegates, scroll back to the
    # beginning, or move the keyboard selection to another title.
    scene.root.clearFilters()
    prototype = dict(scene.bridge.rows[0])
    stable_rows = [dict(prototype, id="stable-" + str(index), title="Film " + str(index).zfill(3))
                   for index in range(60)]
    scene.bridge.publish(items=stable_rows, library_busy=False, library_indexing=True,
                         library_error="", library_query="", library_collection="")
    QTest.qWait(40)
    listing.setProperty("contentY", 550)
    listing.setProperty("currentIndex", 12)
    QTest.qWait(30)
    old_delegate = scene.find("mediaCatalogRow_stable-12")
    old_y = listing.property("contentY")
    old_anchor_y = old_delegate.y() - old_y
    old_height = listing.height()
    for number in range(4):
        scene.bridge.publish(library_verified_count=number + 100, position=number + 200)
        QTest.qWait(10)
    assert scene.find("mediaCatalogRow_stable-12") == old_delegate, "Status updates recreated an unchanged list row"
    assert abs(listing.property("contentY") - old_y) < 1, "Background metadata reset the scroll position"
    scene.bridge.publish(items=[dict(prototype, id="new-film", title="A newly checked film")] + stable_rows)
    QTest.qWait(40)
    assert listing.property("currentIndex") == 13, "Insertion changed the selected title"
    new_anchor = scene.find("mediaCatalogRow_stable-12")
    assert abs(new_anchor.y() - listing.property("contentY") - old_anchor_y) < 1, "A new title moved the visible title anchor"
    scene.bridge.publish(library_indexing=False)
    QTest.qWait(25)
    assert abs(listing.height() - old_height) < 1, "Verification status changed the list viewport height"

    # Loading/error signals do not change playback or the display dimensions.
    scene.click("mediaLibraryRefresh")
    assert ("refresh",) in scene.bridge.calls
    scene.bridge.publish(library_busy=False, library_error="Källan svarar inte just nu")
    QTest.qWait(30)
    assert scene.bridge.payload["now"]["id"] == "download-one"
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(status="PASS", real_qml=True, geometry=geometry,
                          navigation=True, playback=True, seasons=True, empty_search=True,
                          no_automatic_terminal=True, stable_list_updates=True, warnings=len(scene.warnings))))
    scene.close()


class MediaLibraryUiTests(unittest.TestCase):
    def test_library_navigation_and_preserved_player_geometry(self):
        with tempfile.TemporaryDirectory(prefix="gg-media-library-ui-") as temporary:
            staging = Path(temporary)
            shutil.copytree(PROJECT / "qml/components", staging / "components",
                            ignore=shutil.ignore_patterns("__pycache__"))
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_QUICK_CONTROLS_STYLE="Basic", QML_DISABLE_DISK_CACHE="1",
                       GG_DESKTOP_STATE_ROOT=str(staging / "state"), GG_DESKTOP_DATA_ROOT=str(staging / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fixture", str(staging)],
                                    cwd=staging, env=env, capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_saved_inventory_pages_immediately_and_loads_only_selected_title(self):
        with tempfile.TemporaryDirectory(prefix="gg-media-page-ui-") as temporary:
            staging = Path(temporary)
            env = os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(staging / "state"), GG_DESKTOP_DATA_ROOT=str(staging / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--paging-fixture", str(PROJECT)],
                                    cwd=staging, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_continuous_scroll_appends_chunks_and_preserves_selection_playback_and_parent_view(self):
        with tempfile.TemporaryDirectory(prefix="gg-media-scroll-ui-") as temporary:
            staging = Path(temporary)
            env = os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(staging / "state"), GG_DESKTOP_DATA_ROOT=str(staging / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--scroll-fixture", str(PROJECT)],
                                    cwd=staging, env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


def run_scroll_fixture(project):
    class ScrollBridge(LibraryBridge):
        mediaLibraryChunkReady = Signal(int, str)

        def __init__(self):
            super().__init__()
            self.requests = []
            self.chunks = []
            self.held = []
            self.hold = False
            self.fail_next = False
            self.chunk_delay = 25
            self.collection = ""
            self.collection_title = ""
            self.acknowledgements = []
            self.invalidate_next = False
            self.catalogue_revision = "1:50000"
            self.removed = set()
            self.payload.update(library_loading_id="", library_selection_error="")

        def page(self, page, letter, category, language, season, query, offset):
            if self.collection:
                numbers = range(240)
            elif letter == "A":
                numbers = range(30000)
            elif letter == "B":
                numbers = range(30000, 50000)
            else:
                numbers = range(50000)
            if query:
                numbers = [number for number in numbers if query in str(number).zfill(5)]
            if self.removed:
                prefix = "episode-" if self.collection else page + "-"
                numbers = [number for number in numbers if prefix + str(number) not in self.removed]
            subset = list(numbers[offset:offset + 80])
            content_type = "episode" if self.collection else {"live": "live", "movies": "movie", "series": "series"}.get(page, "movie")
            rows = [dict(id=("episode-" if self.collection else page + "-") + str(number), kind="TV",
                         content_type=content_type,
                         title=("S01E" + str(number + 1).zfill(2) + " · Avsnitt" if self.collection else
                                ("A " if number < 30000 else "B ") + page + " " + str(number).zfill(5)),
                         season=1 if self.collection else 0, episode=number + 1 if self.collection else 0,
                         language="sv", category="Klassiker", provider="Saved inventory", availability="verified")
                    for number in subset]
            if not self.collection and page == "series":
                for row in rows:
                    row["collection_key"] = row["id"]
            return dict(library_page=page, library_letter=letter, library_category=category, library_language=language,
                        library_season=season, library_query=query, library_offset=offset, library_page_size=80,
                        library_total=len(numbers), library_has_more=offset + len(rows) < len(numbers),
                        library_collection=self.collection_title, library_collection_key=self.collection,
                        library_catalog_revision=self.catalogue_revision, library_indexing=False, library_busy=False,
                        library_background_refresh=False, library_requires_reset=False,
                        library_error="", library_categories=[], library_languages=[], library_seasons=[], items=rows)

        @Slot(str, str, str, str, str, str, int, result=str)
        def mediaLibraryBrowse(self, page, letter, category, language, season, query, offset):
            self.requests.append((page, letter, query, offset))
            self.payload.update(self.page(page, letter, category, language, season, query, offset))
            self.payload["library_revision"] += 1
            return self.raw()

        @Slot(str, str, str, str, str, str, int, int)
        def mediaLibraryChunk(self, page, letter, category, language, season, query, offset, ticket):
            self.chunks.append((page, letter, query, offset, ticket, self.collection))
            payload = self.page(page, letter, category, language, season, query, offset)
            if self.invalidate_next:
                self.invalidate_next = False
                payload["library_snapshot_invalid"] = True
                self.catalogue_revision = "view:after-invalid"
            if self.fail_next:
                self.fail_next = False
                payload["library_chunk_error"] = "Nästa del kunde inte läsas. Försök igen."
            deliver = lambda: self.mediaLibraryChunkReady.emit(ticket, json.dumps(payload))
            if self.hold:
                self.held.append(deliver)
            else:
                QTimer.singleShot(self.chunk_delay, deliver)

        @Slot(str, result=str)
        def mediaPlay(self, identifier):
            self.calls.append(("play", identifier))
            self.payload.update(library_loading_id=identifier)
            return self.raw()

        @Slot(str)
        def mediaLibraryAcceptSnapshot(self, token):
            self.acknowledgements.append(token)

        @Slot(str, result=str)
        def mediaOpenCollection(self, identifier):
            self.calls.append(("collection", identifier))
            old = self.page("series", "all", "all", "all", "all", "", 0)
            old["library_catalog_revision"] = "view:late-parent"
            self.collection = identifier
            self.collection_title = "A series " + identifier.rsplit("-", 1)[-1].zfill(5)
            self.payload.update(library_busy=True)
            def late_parent():
                self.payload.update(old)
                self.payload["library_revision"] += 1
                self.mediaStateChanged.emit()
            def episodes():
                self.mediaLibraryBrowse("series", "all", "all", "all", "all", "", 0)
                self.mediaStateChanged.emit()
            QTimer.singleShot(35, late_parent)
            QTimer.singleShot(140, episodes)
            return self.raw()

        @Slot(result=str)
        def mediaLibraryBack(self):
            self.collection = ""
            self.collection_title = ""
            return self.mediaLibraryBrowse("series", "all", "all", "all", "all", "", 0)

    scene = MediaScene(project / "qml/components")
    bridge = ScrollBridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.setProperty("statusJson", bridge.raw())
    scene.root.selectPage("movies")
    listing = scene.find("workspaceMediaCatalog")

    def until(predicate, message):
        for _ in range(300):
            QTest.qWait(10)
            if predicate():
                return
        raise AssertionError(message + " " + str(dict(warnings=scene.warnings, count=listing.property("count"),
            y=listing.property("contentY"), height=listing.property("height"), content=listing.property("contentHeight"),
            continuous=scene.root.property("continuousLibrary"), busy=scene.root.property("libraryBusy"),
            chunk=scene.root.property("chunkBusy"), error=scene.root.property("chunkError"), requests=bridge.chunks)))

    until(lambda: listing.property("count") == 160 and not scene.root.property("libraryBusy")
          and not scene.root.property("catalogSyncing") and not scene.root.property("chunkBusy"), "initial lookahead")
    assert scene.root.property("pageTotal") == 50000
    assert scene.root.property("catalogStructureRevision") == "1:50000"
    assert not scene.find("mediaLibraryNext").isVisible() and not scene.find("mediaLibraryPrevious").isVisible()
    assert [request[3] for request in bridge.chunks] == [80], "Initial lookahead exceeded one block"
    assert bridge.acknowledgements == ["1:50000"], "The accepted catalogue session was not acknowledged exactly once"

    # A delayed worker must be asked while there is still ample readable
    # content. A real kinetic flick adds velocity lookahead before the boundary.
    bridge.chunk_delay = 350
    listing.setProperty("contentY", listing.property("originY") + 40 * 50)
    requested = len(bridge.chunks)
    scene.evaluate("flick(0, -4000)", listing)
    until(lambda: len(bridge.chunks) > requested, "fast flick did not request early lookahead")
    assert listing.property("count") == 160
    assert listing.property("contentHeight") - listing.property("contentY") - listing.height() > listing.height() * 2
    wait_until = time.monotonic() + 3
    while listing.property("count") < 240 and time.monotonic() < wait_until:
        QTest.qWait(10)
        assert not listing.property("atYEnd"), "Slow block loading stopped the flick at a catalogue boundary"
    assert listing.property("count") >= 240, "Early lookahead block never arrived"
    scene.evaluate("cancelFlick()", listing)
    bridge.chunk_delay = 25
    scene.evaluate("positionViewAtBeginning()", listing)
    QTest.qWait(30)

    # Real wheel events move the Flickable; approaching the end transparently
    # appends the next block, without replacing the first rows or resetting Y.
    wheel_point = listing.mapToScene(QPointF(listing.width() / 2, listing.height() / 2))
    wheel = QWheelEvent(wheel_point, wheel_point, QPoint(), QPoint(0, -120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    listing.forceActiveFocus()
    QTest.qWait(30)
    scene.app.sendEvent(scene.window, wheel)
    QTest.qWait(150)
    assert listing.property("contentY") > 0, ("Mouse wheel did not scroll the list", listing.property("contentY"),
        listing.property("originY"), listing.property("contentHeight"), scene.root.property("catalogRowsReady"),
        listing.isEnabled(), listing.height())
    listing.forceActiveFocus()
    QTest.keyClick(scene.window, Qt.Key_End)
    until(lambda: listing.property("count") >= 320, "scrolling to the end did not load the next block")
    assert bridge.chunks[0][3] == 80, bridge.chunks
    assert listing.property("contentY") > 1000, "Loading a block jumped to the beginning"
    assert scene.evaluate("catalogModel.get(0).entry.id") == "movies-0"
    assert scene.evaluate("catalogModel.get(80).entry.id") == "movies-80"
    assert scene.root.property("pageOffset") == 0
    assert not bridge.calls, "Scrolling started playback or opened provider metadata"

    # Keyboard navigation crosses another block boundary and preserves focus.
    listing.forceActiveFocus()
    QTest.keyClick(scene.window, Qt.Key_End)
    until(lambda: listing.property("count") >= 400, "keyboard did not continue scrolling")
    selected = listing.property("currentIndex")
    assert selected >= 79
    assert scene.evaluate("contentItem.children.length", listing) < 50, "Visited rows created unbounded visual delegates"
    before_y = listing.property("contentY")
    loaded = listing.property("count")
    bridge.publish(position=30, library_loading_id="")
    QTest.qWait(40)
    assert listing.property("count") >= loaded, "Player status discarded visited blocks"
    assert listing.property("currentIndex") == selected
    assert abs(listing.property("contentY") - before_y) < 1

    # A stale block arriving after an alphabet change cannot contaminate it.
    bridge.hold = True
    scene.root.loadMore(False)
    until(lambda: scene.root.property("chunkBusy"), "held request")
    stale = list(bridge.held)
    bridge.held.clear()
    scene.root.setProperty("libraryLetter", "B")
    until(lambda: listing.property("count") == 80 and not scene.root.property("libraryBusy")
          and not scene.root.property("catalogSyncing"), "letter reset")
    for deliver in stale:
        deliver()
    QTest.qWait(40)
    assert listing.property("count") == 80
    assert scene.evaluate("catalogModel.get(0).entry.id") == "movies-30000"
    fresh = list(bridge.held)
    bridge.held.clear()
    bridge.hold = False
    for deliver in fresh:
        deliver()
    until(lambda: listing.property("count") == 160 and not scene.root.property("chunkBusy"), "new filter lookahead")

    # Local block failures leave existing titles usable and retry only on an
    # explicit action, without repeatedly hammering the metadata worker.
    bridge.fail_next = True
    scene.root.loadMore(False)
    until(lambda: bool(scene.root.property("chunkError")), "block error")
    requests_after_error = len(bridge.chunks)
    QTest.qWait(80)
    assert len(bridge.chunks) == requests_after_error
    assert listing.property("count") == 160
    scene.click("mediaLibraryChunkRetry")
    until(lambda: listing.property("count") == 240, "block retry")

    # Retain the parent's actual resident model when entering a series. Back
    # restores the visited prefix/selection/pixel position with no block replay.
    scene.root.selectPage("series")
    until(lambda: listing.property("count") == 160 and not scene.root.property("libraryBusy")
          and not scene.root.property("chunkBusy"), "series")
    scene.root.loadMore(False)
    until(lambda: listing.property("count") == 240, "series next block")
    listing.setProperty("currentIndex", 90)
    scene.evaluate("positionViewAtIndex(90, ListView.Center)", listing)
    QTest.qWait(30)
    selected_series = scene.evaluate("catalogModel.get(90).entry.id")
    parent_y = listing.property("contentY") - listing.property("originY")
    parent_count = listing.property("count")
    parent_ids = scene.evaluate("Array.from({length:catalogModel.count}, function(_,i) { return catalogModel.get(i).entry.id })")
    chunks_before = len(bridge.chunks)
    scene.root.activateItem(scene.evaluate("catalogModel.get(90).entry"))
    assert listing.property("count") == 0, "Entering a series retained parent rows"
    # A stale parent response has the same page and filter echo. It must not
    # paint series names over the new episode view, even for one frame.
    for _ in range(9):
        QTest.qWait(10)
        assert listing.property("count") == 0, "Late parent page contaminated the episode list"
    until(lambda: listing.property("count") >= 80 and bool(scene.root.property("collectionTitle"))
          and not scene.root.property("libraryBusy"), "episodes")
    assert scene.evaluate("catalogModel.get(0).entry.id") == "episode-0"
    assert listing.property("contentY") - listing.property("originY") < 1, ("Episode opening retained parent scroll",
        listing.property("contentY"), listing.property("originY"), scene.root.property("catalogSyncing"),
        scene.evaluate("Array.from(contentItem.children).map(function(item) { return item.objectName })", listing))
    names = scene.evaluate("Array.from(contentItem.children).map(function(item) { return item.objectName })", listing)
    assert "mediaCatalogRow_episode-0" in names, ("Episode delegates needed a layout/scroll", names,
        listing.property("count"), scene.root.property("catalogRowsReady"), scene.root.property("catalogSyncing"))
    visual = scene.find("mediaCatalogRow_episode-0")
    assert scene.evaluate("modelData.content_type", visual) == "episode"
    assert "Avsnitt" in scene.evaluate("contentItem.children[0].text", visual), "Episode delegates needed a scroll repaint"
    assert "view:late-parent" not in bridge.acknowledgements, "A rejected parent snapshot was acknowledged"
    scene.root.goBack()
    until(lambda: listing.property("count") >= parent_count and not scene.root.property("libraryBusy"), "parent model restore")
    assert listing.property("count") <= parent_count + 160, "Back fetched an unbounded prefix"
    assert scene.evaluate("Array.from({length:" + str(parent_count) + "}, function(_,i) { return catalogModel.get(i).entry.id })") == parent_ids
    assert scene.evaluate("catalogModel.get(90).entry.id") == selected_series
    assert listing.property("currentIndex") == 90
    assert abs(listing.property("contentY") - listing.property("originY") - parent_y) < 1
    assert not any(request[3] < parent_count for request in bridge.chunks[chunks_before:]
                   if request[0] == "series" and not request[5]), "Back unnecessarily replayed the parent prefix"
    assert not any(call[0] == "play" for call in bridge.calls)

    # A click on a title fetched through a later block still uses the same ID
    # based playback contract; no source URL is needed in a scroll summary.
    scene.root.selectPage("movies")
    until(lambda: listing.property("count") == 160 and not scene.root.property("libraryBusy")
          and not scene.root.property("chunkBusy"), "movie return")
    scene.root.loadMore(False)
    until(lambda: listing.property("count") == 240, "movie later block")
    listing.setProperty("currentIndex", 90)
    scene.evaluate("positionViewAtIndex(90, ListView.Center)", listing)
    QTest.qWait(30)
    clicked = scene.evaluate("catalogModel.get(90).entry.id")
    scene.click("mediaCatalogRow_" + clicked)
    assert [call for call in bridge.calls if call[0] == "play"] == [("play", clicked)]
    assert scene.root.property("loadingItemId") == clicked

    # Losing a healthy item outside the first block must invalidate the visited
    # tail even when the first80 IDs are identical. A late old block cannot
    # reinsert it; new blocks use the shifted, current catalogue offsets.
    scene.root.loadMore(False)
    until(lambda: listing.property("count") >= 320, "membership initial tail")
    QTest.qWait(40)
    current = bridge.payload
    proposal = bridge.page(current["library_page"], current["library_letter"], current["library_category"],
                           current["library_language"], current["library_season"], current["library_query"], 0)
    proposal.update(library_background_refresh=True, library_catalog_revision="view:pending-admission")
    before_proposal = listing.property("count")
    membership_y = listing.property("contentY") - listing.property("originY")
    bridge.publish(**proposal)
    QTest.qWait(20)
    assert scene.root.property("catalogUpdatePending")
    assert listing.property("count") == before_proposal
    assert "view:pending-admission" not in bridge.acknowledgements, "An ignored deep-scroll proposal became active"
    removed = scene.evaluate("catalogModel.get(120).entry.id")
    first_ids = scene.evaluate("catalogModel.get(0).entry.id")
    bridge.hold = True
    scene.root.loadMore(False)
    old_deliveries = list(bridge.held)
    bridge.held.clear()
    bridge.removed.add(removed)
    bridge.catalogue_revision = "2:49999"
    current = bridge.payload
    withdrawal = bridge.page(current["library_page"], current["library_letter"], current["library_category"],
                             current["library_language"], current["library_season"], current["library_query"], 0)
    withdrawal.update(library_background_refresh=True, library_requires_reset=True)
    bridge.publish(**withdrawal)
    assert listing.property("count") <= 80, "Membership update retained unconfirmed tail rows"
    assert bridge.acknowledgements[-1] == "2:49999", "A withdrawn source did not force a coherent snapshot reset"
    assert scene.evaluate("catalogModel.get(0).entry.id") == first_ids
    for deliver in old_deliveries:
        deliver()
    QTest.qWait(30)
    assert listing.property("count") <= 80, "A stale block restored a withdrawn source"
    if not bridge.held:
        scene.root.loadMore(False)
    new_deliveries = list(bridge.held)
    bridge.held.clear()
    bridge.hold = False
    for deliver in new_deliveries:
        deliver()
    until(lambda: listing.property("count") >= 160, "membership replacement block")
    loaded_ids = scene.evaluate("Array.from({length:catalogModel.count}, function(_,i) { return catalogModel.get(i).entry.id })")
    assert removed not in loaded_ids
    assert len(loaded_ids) == len(set(loaded_ids)), "Shifted offsets duplicated an existing title"
    expected = bridge.page(current["library_page"], current["library_letter"], current["library_category"],
                           current["library_language"], current["library_season"], current["library_query"], 80)["items"]
    assert loaded_ids[80:160] == [row["id"] for row in expected], "Replacement block skipped a shifted title"

    def catalogue_idle():
        return (not scene.root.property("libraryBusy") and not scene.root.property("chunkBusy")
                and not scene.root.property("catalogSyncing")
                and scene.root.property("catalogRowsReady")
                and not scene.root.property("pendingListRestore"))

    # Restoring an offscreen selection can request another prefix block. Wait
    # for that real continuation before changing the worker's next revision;
    # otherwise loadMore correctly coalesces behind the still active request.
    until(catalogue_idle, "membership viewport restoration")
    restored_id = scene.evaluate("catalogModel.get(" + str(listing.property("currentIndex")) + ").entry.id")
    restored_y = listing.property("contentY") - listing.property("originY")
    restored_count = listing.property("count")
    assert restored_id == clicked, "Withdrawal changed the selected healthy programme"
    assert abs(restored_y - membership_y) < 1, "Withdrawal moved the restored viewport"

    # An independently refreshed catalogue cannot splice mismatched offsets
    # into the visited prefix. Its explicit retry reloads the local first block.
    bridge.catalogue_revision = "3:50000"
    scene.root.loadMore(False)
    until(lambda: scene.root.property("chunkNeedsRefresh"), "catalogue revision guard")
    QTest.qWait(30)
    before = len(bridge.requests)
    scene.click("mediaLibraryChunkRetry")
    until(lambda: listing.property("count") >= 160 and catalogue_idle(), "catalogue local reload")
    assert listing.property("count") <= restored_count + 160, "Local retry rebuilt an unbounded prefix"
    assert scene.evaluate("catalogModel.get(" + str(listing.property("currentIndex")) + ").entry.id") == restored_id
    assert abs(listing.property("contentY") - listing.property("originY") - restored_y) < 1, "Local retry moved the viewport"
    assert len(bridge.requests) == before + 1
    assert scene.root.property("catalogStructureRevision") == bridge.catalogue_revision
    assert not any(call[0] == "refresh" for call in bridge.calls), "Local retry unexpectedly refreshed providers"

    # A genuinely invalid backend snapshot resets locally once, without a
    # manual paging action. A broken backend cannot cause a retry loop.
    before = len(bridge.requests)
    bridge.invalidate_next = True
    scene.root.loadMore(False)
    until(lambda: scene.root.property("catalogStructureRevision") == "view:after-invalid"
          and listing.property("count") >= 160 and catalogue_idle(), "automatic session recovery")
    assert listing.property("count") <= restored_count + 160, "Session recovery rebuilt an unbounded prefix"
    assert scene.evaluate("catalogModel.get(" + str(listing.property("currentIndex")) + ").entry.id") == restored_id
    assert abs(listing.property("contentY") - listing.property("originY") - restored_y) < 1, "Session recovery moved the viewport"
    assert len(bridge.requests) == before + 1
    assert bridge.acknowledgements[-1] == "view:after-invalid"
    before = len(bridge.requests)
    bridge.invalidate_next = True
    scene.root.loadMore(False)
    until(lambda: bool(scene.root.property("chunkError")), "repeated invalidation guard")
    QTest.qWait(100)
    assert len(bridge.requests) == before, "Repeated invalid sessions caused an automatic browse loop"
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(continuous_scroll=True, backend_titles=50000, visited_rows=loaded,
                          wheel=True, keyboard=True, stale_rejected=True, retry=True,
                          parent_restored=True, warnings=scene.warnings)))
    scene.close()


def run_paging_fixture(project):
    class PagedBridge(LibraryBridge):
        def __init__(self):
            super().__init__()
            self.catalogues = {}
            for page, content_type, title in (("live", "live", "Kanal"), ("movies", "movie", "Film"),
                                               ("series", "series", "Serie")):
                # Summary rows deliberately contain no source URL or player data.
                self.catalogues[page] = [dict(id=page + "-" + str(number), kind="TV",
                    content_type=content_type, title=("A " if number < 6000 else "B ") + title + " " + str(number).zfill(5),
                    provider="Saved inventory", category=title, language="sv",
                    availability="verified")
                    for number in range(11023)]
            self.requests = []
            self.payload.update(library_loading_id="", library_selection_error="")

        @Slot(str, str, str, str, str, str, int, result=str)
        def mediaLibraryBrowse(self, page, letter, category, language, season, query, offset):
            self.requests.append((page, letter, offset))
            rows = self.catalogues.get(page, [])
            if letter != "all":
                rows = [row for row in rows if row["title"].startswith(letter)]
            if query:
                rows = [row for row in rows if query.casefold() in row["title"].casefold()]
            self.payload.update(library_page=page, library_letter=letter, library_category=category,
                                library_language=language, library_season=season, library_query=query,
                                library_offset=offset, library_page_size=80, library_total=len(rows),
                                library_has_more=offset + 80 < len(rows), library_indexing=False,
                                library_busy=False, library_error="", library_categories=[],
                                library_languages=[], library_seasons=[],
                                items=rows[offset:offset + 80])
            self.payload["library_revision"] += 1
            return self.raw()

        @Slot(str, result=str)
        def mediaPlay(self, identifier):
            self.calls.append(("play", identifier))
            self.payload.update(library_loading_id=identifier, library_selection_error="")
            return self.raw()

        @Slot(str, result=str)
        def mediaOpenCollection(self, identifier):
            self.calls.append(("collection", identifier))
            selected = next(row for row in self.catalogues["series"] if row["id"] == identifier)
            self.payload.update(library_collection=selected["title"], items=[], library_total=0,
                                library_language="all", library_available_only=False,
                                library_has_more=False, library_loading_id=identifier,
                                library_selection_error="", library_busy=False)
            return self.raw()

        @Slot(result=str)
        def mediaLibraryBack(self):
            self.calls.append(("back",))
            self.payload.update(library_collection="", library_loading_id="")
            return self.mediaLibraryBrowse("series", "all", "all", "all", "all", "", 0)

    scene = MediaScene(project / "qml/components")
    bridge = PagedBridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.setProperty("statusJson", bridge.raw())
    scene.root.selectPage("live")
    QTest.qWait(180)
    page_range = scene.find("mediaLibraryPageRange")
    listing = scene.find("workspaceMediaCatalog")
    assert scene.root.property("pageTotal") == 11023
    assert listing.property("count") == 80
    assert not any(call[0] == "play" for call in bridge.calls), bridge.calls
    assert "kontroller" not in scene.find("mediaLibraryLoadState").property("text").casefold()
    assert scene.find("mediaCatalogRow_live-3").isEnabled(), "Checked catalogue entries should be selectable"
    assert scene.find("mediaCatalogRow_live-4").isEnabled()
    assert not scene.find("mediaCatalogRow_live-0").property("rowBuffering")
    assert scene.find("mediaLibraryNext").property("text") == "›"
    scene.click("mediaLibraryNext")
    assert bridge.requests[-1] == ("live", "all", 80), bridge.requests[-1]
    assert scene.root.property("pageOffset") == 80
    assert listing.property("count") == 80
    assert page_range.property("text").startswith("81–160 av ")
    scene.click("mediaLibraryPrevious")
    assert bridge.requests[-1] == ("live", "all", 0)

    # Switching video types reads the same metadata contract, without any play.
    for page in ("movies", "series", "live"):
        scene.click("mediaNav_" + page)
        QTest.qWait(150)
        assert scene.root.property("pageTotal") == 11023, (page, scene.root.property("pageTotal"))
        assert listing.property("count") == 80
        assert not any(call[0] == "play" for call in bridge.calls), bridge.calls

    # Opening a series resolves that series alone. Its episodes can be listed
    # without opening every episode's source, and choosing one is a separate play.
    scene.click("mediaNav_series")
    QTest.qWait(150)
    scene.click("mediaCatalogRow_series-0")
    assert bridge.calls[-1] == ("collection", "series-0")
    assert scene.root.property("loadingItemId") == "series-0"
    assert listing.property("count") == 0
    episode = dict(id="lazy-episode-1", kind="TV", content_type="episode", title="S01E01 - First episode",
                   series_title="A Serie 00000", season=1, episode=1, language="sv", availability="unknown")
    bridge.publish(items=[episode], library_total=1, library_loading_id="", library_has_more=False)
    QTest.qWait(30)
    assert listing.property("count") == 1
    assert not any(call[0] == "play" for call in bridge.calls), bridge.calls
    scene.click("mediaCatalogRow_lazy-episode-1")
    assert bridge.calls[-1] == ("play", "lazy-episode-1")
    assert scene.root.property("loadingItemId") == "lazy-episode-1"
    bridge.publish(library_loading_id="")
    scene.root.goBack()
    QTest.qWait(150)
    scene.click("mediaNav_live")
    QTest.qWait(150)
    scene.root.setProperty("libraryLetter", "B")
    QTest.qWait(150)
    assert scene.root.property("pageTotal") == 5023
    assert all(row["title"].startswith("B") for row in scene.evaluate("filteredItems"))
    scene.root.clearFilters()
    QTest.qWait(150)

    # A previously playing video remains active while only the clicked source
    # loads. Empty source summaries must not make every row show a spinner.
    previous = dict(id="previous-video", kind="TV", title="Previous video", media="vod",
                    is_live=False, source="https://example.invalid/previous.mp4", player="qml", play="video")
    bridge.publish(now=previous, backend="qml", playing=True, buffering=False, playback_generation=1)
    QTest.qWait(40)
    player = scene.find("mediaVideoPlayer")
    loads = player.property("sourceLoads")
    scene.click("mediaCatalogRow_live-2")
    assert bridge.calls[-1] == ("play", "live-2")
    assert scene.root.property("loadingItemId") == "live-2"
    assert scene.find("mediaCatalogRow_live-2").property("rowBuffering")
    assert not scene.find("mediaCatalogRow_live-1").property("rowBuffering")
    assert not scene.root.property("libraryBusy"), "A selected source blocked catalogue navigation"
    assert player.property("sourceLoads") == loads
    assert scene.find("mediaLibraryNext").isEnabled()
    bridge.publish(library_loading_id="", library_selection_error="Kanalen svarar inte just nu")
    QTest.qWait(25)
    assert not scene.find("mediaCatalogRow_live-2").property("rowBuffering")
    assert scene.find("mediaLibraryLoadState").property("text") == "Kanalen svarar inte just nu"
    assert listing.property("count") == 80
    assert bridge.payload["now"]["id"] == "previous-video"

    # The final, partial page is known immediately; there is no check-to-fill
    # '+' action and no advancing beyond the actual saved inventory.
    scene.root.setProperty("pageOffset", 10960)
    QTest.qWait(150)
    assert listing.property("count") == 63
    assert page_range.property("text").startswith("10961–11023 av ")
    assert not scene.find("mediaLibraryNext").isEnabled()
    assert scene.find("mediaLibraryPrevious").isEnabled()
    before = len(bridge.requests)
    scene.root.browsePage(1)
    assert len(bridge.requests) == before
    assert not scene.warnings, scene.warnings
    scene.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        run_fixture(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--paging-fixture":
        run_paging_fixture(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--scroll-fixture":
        run_scroll_fixture(Path(sys.argv[2]))
    else:
        unittest.main()
