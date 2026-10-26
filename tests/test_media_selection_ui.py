"""Offline real-QML selection and viewport checks for paged channel lists."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))

from test_media_library_ui import LibraryBridge, MediaScene
from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtTest import QTest


class SelectionBridge(LibraryBridge):
    """Only public summary identities cross the bridge; no player is started."""

    mediaLibraryChunkReady = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.channels = [dict(id=f"channel-{number}", kind="TV", content_type="live",
                              title=f"Channel {number:04}", language="sv", category="Classic",
                              provider="Offline catalogue", availability="verified")
                         for number in range(400)]
        self.catalogue_revision = "view:initial"
        self.requests = []
        self.chunks = []
        self.accepted = []
        self.payload.update(library_loading_id="", library_selection_error="")

    def page(self, page, letter, category, language, season, query, offset):
        rows = self.channels[offset:offset + 80]
        return dict(library_page=page, library_letter=letter, library_category=category,
                    library_language=language, library_season=season, library_query=query,
                    library_offset=offset, library_page_size=80, library_total=len(self.channels),
                    library_has_more=offset + len(rows) < len(self.channels),
                    library_collection="", library_collection_key="",
                    library_catalog_revision=self.catalogue_revision,
                    library_indexing=False, library_busy=False, library_error="",
                    library_background_refresh=False, library_requires_reset=False,
                    library_categories=[], library_languages=[], library_seasons=[], items=rows)

    @Slot(str, str, str, str, str, str, int, result=str)
    def mediaLibraryBrowse(self, page, letter, category, language, season, query, offset):
        self.requests.append((page, offset))
        self.payload.update(self.page(page, letter, category, language, season, query, offset))
        self.payload["library_revision"] += 1
        return self.raw()

    @Slot(str, str, str, str, str, str, int, int)
    def mediaLibraryChunk(self, page, letter, category, language, season, query, offset, ticket):
        self.chunks.append((offset, self.catalogue_revision))
        response = self.page(page, letter, category, language, season, query, offset)
        # The real service captures the accepted snapshot when a chunk is
        # requested, rather than looking up the newest proposal on delivery.
        response["library_catalog_revision"] = self.accepted[-1] if self.accepted else ""
        QTimer.singleShot(35, lambda: self.mediaLibraryChunkReady.emit(ticket, json.dumps(response)))

    @Slot(str)
    def mediaLibraryAcceptSnapshot(self, token):
        self.accepted.append(token)

    @Slot(str, result=str)
    def mediaPlay(self, identifier):
        self.calls.append(("play", identifier))
        self.payload.update(library_loading_id=identifier, library_selection_error="")
        return self.raw()

    def complete_play(self, identifier):
        summary = next(row for row in self.channels if row["id"] == identifier)
        self.publish(now=summary, library_loading_id="", playing=False, buffering=False,
                     library_background_refresh=False, library_requires_reset=False)

    def publish_first_page(self, **overrides):
        values = self.page("live", "all", "all", "all", "all", "", 0)
        values.update(overrides)
        self.publish(**values)


def fixture(case):
    scene = MediaScene(PROJECT / "qml/components")
    bridge = SelectionBridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.setProperty("statusJson", bridge.raw())
    scene.root.selectPage("live")
    listing = scene.find("workspaceMediaCatalog")

    def until(predicate, message):
        for _ in range(250):
            QTest.qWait(10)
            if predicate():
                return
        raise AssertionError((message, dict(count=listing.property("count"),
            y=listing.property("contentY"), origin=listing.property("originY"),
            selected=listing.property("currentIndex"), chunk=scene.root.property("chunkBusy"),
            restore=scene.root.property("pendingListRestore"), warnings=scene.warnings)))

    def idle():
        return (not scene.root.property("libraryBusy") and not scene.root.property("chunkBusy")
                and not scene.root.property("catalogSyncing")
                and scene.root.property("catalogRowsReady"))

    def ids():
        return scene.evaluate("Array.from({length:catalogModel.count}, function(_,i) { return catalogModel.get(i).entry.id })")

    def selected_id():
        return scene.evaluate("catalogModel.get(" + str(listing.property("currentIndex")) + ").entry.id")

    def scroll_and_click(index):
        until(lambda: listing.property("count") > index and idle(), "initial channel prefix")
        scene.evaluate(f"positionViewAtIndex({index}, ListView.Center)", listing)
        until(idle, "scrolled lookahead")
        identifier = scene.evaluate(f"catalogModel.get({index}).entry.id")
        before_y = listing.property("contentY")
        scene.click("mediaCatalogRow_" + identifier)
        assert bridge.calls[-1] == ("play", identifier), bridge.calls
        assert selected_id() == identifier, "Click selected a different channel"
        assert abs(listing.property("contentY") - before_y) < 1, "Click jumped to another list block"
        return identifier

    until(lambda: listing.property("count") >= 160 and idle(), "initial lookahead")
    if case == "stable":
        identifier = scroll_and_click(95)
        prefix, before_y = ids(), listing.property("contentY")
        bridge.complete_play(identifier)
        QTest.qWait(80)
        until(idle, "healthy playback completion")
        assert ids()[:len(prefix)] == prefix, "Healthy playback discarded or reordered loaded rows"
        assert selected_id() == identifier
        assert abs(listing.property("contentY") - before_y) < 1, "Healthy playback jumped to the first block"
        assert scene.root.property("catalogStructureRevision") == "view:initial"
        assert bridge.accepted == ["view:initial"]
    elif case in ("withdrawal", "withdraw-first"):
        identifier = scroll_and_click(95)
        bridge.complete_play(identifier)
        until(idle, "playback before source withdrawal")
        first = max(0, int((listing.property("contentY") - listing.property("originY")) // 50))
        anchor_id = ids()[first + (1 if case == "withdraw-first" else 0)]
        anchor_y = scene.find("mediaCatalogRow_" + anchor_id).y() - listing.property("contentY")
        # One revoked source precedes the viewport; another is a visible row.
        # Neither is the anchor or selected programme, which remain healthy.
        revoked = {"channel-20", ids()[first if case == "withdraw-first" else first + 1]}
        assert identifier not in revoked and anchor_id not in revoked
        bridge.channels = [row for row in bridge.channels if row["id"] not in revoked]
        bridge.catalogue_revision = "view:withdrawn"
        bridge.publish_first_page(library_background_refresh=True, library_requires_reset=True)
        assert bridge.accepted[-1] == "view:withdrawn"
        # During prefix reconstruction the old withdrawn delegate may remain
        # pooled, but must not be visible/clickable to the user.
        while not idle():
            for dead in revoked:
                try:
                    item = scene.find("mediaCatalogRow_" + dead)
                except AssertionError:
                    continue
                assert not item.isVisible(), "A withdrawn source stayed visible during reset"
            QTest.qWait(10)
            if scene.root.property("chunkError"):
                raise AssertionError(scene.root.property("chunkError"))
        until(lambda: identifier in ids() and idle(), "withdrawal prefix restoration")
        assert not (set(ids()) & revoked), "Withdrawn source reappeared in rebuilt prefix"
        assert selected_id() == identifier, "Withdrawal changed a healthy selected channel"
        assert abs(scene.find("mediaCatalogRow_" + anchor_id).y()
                   - listing.property("contentY") - anchor_y) < 1, "Withdrawal moved the visible anchor"
        assert listing.property("count") <= 320, "Restoration loaded an unbounded catalogue prefix"
        assert len(ids()) == len(set(ids())), "Withdrawal replay duplicated rows"
    elif case == "admission-top":
        identifier = scroll_and_click(95)
        scene.evaluate("positionViewAtBeginning()", listing)
        until(idle, "top before catalogue admission")
        bridge.channels.insert(0, dict(bridge.channels[0], id="new-channel", title="A new checked channel"))
        bridge.catalogue_revision = "view:admission"
        bridge.publish_first_page(library_background_refresh=True)
        until(idle, "top admission selection restoration")
        assert not scene.root.property("chunkError"), "Restoration requested an unaccepted catalogue cursor"
        assert selected_id() == identifier
        assert scene.root.property("catalogStructureRevision") == "view:admission"
        assert bridge.accepted[-1] == "view:admission"
        assert listing.property("count") <= 320
    elif case == "admission":
        identifier = scroll_and_click(12)
        prefix, before_y = ids(), listing.property("contentY")
        assert 1 < before_y - listing.property("originY") < 80 * 50
        bridge.channels.insert(0, dict(bridge.channels[0], id="new-channel", title="A new checked channel"))
        bridge.catalogue_revision = "view:admission"
        bridge.publish_first_page(library_background_refresh=True)
        QTest.qWait(80)
        assert scene.root.property("catalogUpdatePending"), "First-block scroll accepted a shifting background proposal"
        assert scene.root.property("catalogStructureRevision") == "view:initial"
        assert bridge.accepted == ["view:initial"]
        assert ids() == prefix, "Background admission replaced the browsed prefix"
        assert selected_id() == identifier
        assert abs(listing.property("contentY") - before_y) < 1, "Background admission moved the viewport"
    else:
        raise AssertionError(case)
    assert not scene.warnings, scene.warnings
    print(json.dumps(dict(case=case, real_qml=True, row_click=True, warnings=0)))
    scene.close()


class MediaSelectionUiTests(unittest.TestCase):
    def run_case(self, case):
        with tempfile.TemporaryDirectory(prefix="gg-media-selection-ui-") as temporary:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_QUICK_CONTROLS_STYLE="Basic", QML_DISABLE_DISK_CACHE="1",
                       GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                       GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fixture", case],
                                    cwd=temporary, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_later_block_channel_click_and_healthy_completion_keep_view(self):
        self.run_case("stable")

    def test_withdrawn_channel_is_hidden_and_healthy_anchor_restored(self):
        self.run_case("withdrawal")

    def test_first_block_background_admission_keeps_scrolled_view(self):
        self.run_case("admission")

    def test_withdrawn_first_visible_channel_keeps_next_anchor_at_same_pixel(self):
        self.run_case("withdraw-first")

    def test_admission_accepts_new_snapshot_before_restoring_later_selection(self):
        self.run_case("admission-top")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        fixture(sys.argv[2])
    else:
        unittest.main()
