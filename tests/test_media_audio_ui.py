"""Real MEDIA lists for unprobed local music, artist filtering and radio."""
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
from test_media_library_ui import LibraryBridge, MediaScene, QTest, Signal, Slot, QTimer, Qt


class AudioBridge(LibraryBridge):
    mediaLibraryChunkReady = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.music = [dict(id=f"track-{number}", title=f"{'ABÅ'[number % 3]} song {number:04}",
            kind="MUSIC", content_type="music", artist=f"Artist {number % 318:03}",
            album=f"Album {number // 318}", category=f"Artist {number % 318:03}",
            media="file", local=True, source_label="LOKAL", provider="Local", availability="metadata")
            for number in range(1500)]
        self.stations = [dict(id=f"radio-{number}", title=f"Radio {number:03}", kind="RADIO",
            content_type="music", media="stream", provider="Saved stations", availability="unknown")
            for number in range(83)]
        self.requests, self.chunks = [], []
        self.view = ("music", "all", "all", "all", "all", "", 0)
        self.revision = "view:audio"
        self.payload.update(library_loading_id="", library_selection_error="")

    def page(self, page, letter, category, language, season, query, offset):
        rows = self.music if page == "music" else self.stations if page == "radio" else []
        artists = sorted({row["artist"] for row in self.music}) if page == "music" else []
        rows = sorted(rows, key=lambda row: (row.get("artist", ""), row["title"], row["id"]))
        if letter != "all":
            rows = [row for row in rows if row["title"].startswith(letter)]
        if category != "all":
            rows = [row for row in rows if row.get("artist") == category]
        if query:
            rows = [row for row in rows if query.casefold() in (row["title"] + " " + row.get("artist", "")).casefold()]
        return dict(mode="MUSIC" if page == "music" else "RADIO" if page == "radio" else "TV",
            library_page=page, library_letter=letter, library_category=category,
            library_language=language, library_season=season, library_query=query, library_offset=offset,
            library_page_size=80, library_total=len(rows), library_has_more=offset + 80 < len(rows),
            library_collection="", library_collection_key="", library_catalog_revision=self.revision,
            library_background_refresh=False, library_requires_reset=False, library_indexing=False,
            library_busy=False, library_error="", library_categories=[dict(value=a, label=a) for a in artists],
            library_languages=[], library_seasons=[], items=rows[offset:offset + 80])

    @Slot(str, str, str, str, str, str, int, result=str)
    def mediaLibraryBrowse(self, page, letter, category, language, season, query, offset):
        self.view = (page, letter, category, language, season, query, offset)
        self.requests.append(self.view)
        self.payload.update(self.page(*self.view))
        self.payload["library_revision"] += 1
        return self.raw()

    @Slot(str, str, str, str, str, str, int, int)
    def mediaLibraryChunk(self, page, letter, category, language, season, query, offset, ticket):
        self.chunks.append((page, offset))
        response = self.page(page, letter, category, language, season, query, offset)
        QTimer.singleShot(15, lambda: self.mediaLibraryChunkReady.emit(ticket, json.dumps(response)))

    @Slot(str, result=str)
    def mediaLibrarySearch(self, query):
        self.calls.append(("search", query))
        return self.raw()

    @Slot(str, result=str)
    def mediaPlay(self, identifier):
        self.calls.append(("play", identifier))
        row = next(row for row in self.music + self.stations if row["id"] == identifier)
        self.payload.update(now=row, library_loading_id="")
        return self.raw()


def scenario(case):
    scene = MediaScene(PROJECT / "qml/components")
    bridge = AudioBridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.setProperty("statusJson", bridge.raw())
    scene.root.selectPage(case)
    listing = scene.find("workspaceMediaCatalog")

    def until(predicate, message):
        for _ in range(300):
            QTest.qWait(10)
            if predicate():
                return
        raise AssertionError((message, dict(count=listing.property("count"),
            busy=scene.root.property("libraryBusy"), chunk=scene.root.property("chunkBusy"),
            error=scene.root.property("chunkError"), requests=bridge.requests[-3:], warnings=scene.warnings)))

    def idle():
        return (not scene.root.property("libraryBusy") and not scene.root.property("chunkBusy")
            and not scene.root.property("catalogSyncing") and scene.root.property("catalogRowsReady"))

    def ids():
        return scene.evaluate("Array.from({length:catalogModel.count},function(_,i){return catalogModel.get(i).entry.id})")

    if case == "music":
        until(lambda: listing.property("count") >= 160 and idle(), "music initial blocks")
        assert scene.root.property("pageTotal") == 1500, "Unprobed local songs were hidden"
        selector = scene.find("mediaCategorySelector")
        options = scene.evaluate("model.map(function(row){return row.value})", selector)
        assert len(options) == 319 and options[0] == "all" and options[-1] == "Artist 317", "Artist menu was truncated"
        assert scene.evaluate("model[0].label", selector) == "Alla artister"
        first_id = ids()[0]
        first = scene.find("mediaCatalogRow_" + first_id)
        detail = scene.evaluate("contentItem.children[1].text", first)
        assert detail.startswith("LOKAL · Artist ") and "Album " in detail, detail
        scene.evaluate("positionViewAtIndex(95,ListView.Center)", listing)
        until(idle, "scrolled music blocks")
        clicked = ids()[95]
        before_y, prefix = listing.property("contentY"), ids()
        scene.click("mediaCatalogRow_" + clicked)
        assert bridge.calls[-1] == ("play", clicked)
        assert ids()[:len(prefix)] == prefix
        assert listing.property("currentIndex") == 95
        assert abs(listing.property("contentY") - before_y) < 1, "Playing local music moved the list"
        # Real keyboard scrolling reaches every one of the 1,500 catalogue
        # entries through small continuation blocks, without automatic playback.
        for _ in range(24):
            if listing.property("count") == 1500:
                break
            previous = listing.property("count")
            listing.forceActiveFocus()
            QTest.keyClick(scene.window, Qt.Key_End)
            until(lambda: listing.property("count") > previous and idle(), "next music block")
        assert listing.property("count") == 1500
        assert len(ids()) == len(set(ids())) == 1500
        assert set(ids()) == {row["id"] for row in bridge.music}
        assert len([call for call in bridge.calls if call[0] == "play"]) == 1
        assert scene.evaluate("contentItem.children.length", listing) < 60, "Music allocated all visual delegates"
        # The last artist is chosen through the actual popup keyboard route;
        # the letter and text query then remain independent filters.
        scene.click(selector)
        QTest.keyClick(scene.window, Qt.Key_End)
        QTest.keyClick(scene.window, Qt.Key_Return)
        until(lambda: scene.root.property("categoryFilter") == "Artist 317" and idle(), "last artist selection")
        assert scene.root.property("pageTotal") == 4
        scene.root.setProperty("libraryLetter", "Å")
        until(lambda: bridge.requests[-1][1] == "Å" and idle(), "artist plus letter")
        search = scene.find("workspaceMediaSearch")
        scene.click(search)
        for character in "0953":
            QTest.keyClick(scene.window, Qt.Key(ord(character)))
        QTest.keyClick(scene.window, Qt.Key_Return)
        until(lambda: scene.root.property("pageTotal") == 1 and idle(), "artist letter and search")
        assert ids() == ["track-953"]
        assert bridge.requests[-1][1:3] == ("Å", "Artist 317") and bridge.requests[-1][5] == "0953"
        scene.click("mediaClearFilters")
        until(lambda: scene.root.property("pageTotal") == 1500 and idle(), "music filters reset")
        # Other music uses the same row/player flow and is labelled ONLINE.
        online = dict(bridge.music[0], id="online-song", artist="Online artist", category="Online artist",
            title="Online song", album="Remote album", local=False, media="stream", source_label="Archive", provider="Archive")
        bridge.music.append(online)
        bridge.revision = "view:audio-with-online"
        scene.root.setProperty("categoryFilter", "Online artist")
        until(lambda: scene.root.property("pageTotal") == 1 and idle(), "online artist filter")
        item = scene.find("mediaCatalogRow_online-song")
        assert scene.evaluate("contentItem.children[1].text", item) == "ONLINE · Online artist · Remote album"
        scene.click(item)
        assert bridge.calls[-1] == ("play", "online-song")
    else:
        until(lambda: listing.property("count") == 83 and idle(), "radio metadata blocks")
        assert scene.root.property("pageTotal") == 83
        first = scene.find("mediaCatalogRow_radio-0")
        assert first.isEnabled(), "A station without an old decoder proof was disabled"
        scene.click(first)
        assert bridge.calls[-1] == ("play", "radio-0")
        scene.evaluate("positionViewAtIndex(81,ListView.Center)", listing)
        QTest.qWait(30)
        before_y = listing.property("contentY")
        scene.click("mediaCatalogRow_radio-81")
        assert bridge.calls[-1] == ("play", "radio-81")
        assert abs(listing.property("contentY") - before_y) < 1
        assert all(row["availability"] == "unknown" for row in bridge.stations)
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(case=case, real_qml=True, no_decoder_proof_required=True, warnings=0)))
    scene.close()


class MediaAudioUiTests(unittest.TestCase):
    def run_case(self, case):
        with tempfile.TemporaryDirectory(prefix="gg-media-audio-ui-") as temporary:
            env = os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fixture", case],
                cwd=temporary, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_music_artist_menu_filters_local_and_online_rows_and_continuous_scroll(self):
        self.run_case("music")

    def test_radio_metadata_stations_are_visible_and_clickable(self):
        self.run_case("radio")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        scenario(sys.argv[2])
    else:
        unittest.main()
