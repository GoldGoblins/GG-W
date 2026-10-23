"""Offscreen regression for authored RuntimeLoader takeover and fallback."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine
from PySide6.QtQuick import QQuickWindow

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _snapshot_with_source(runtime, source: str) -> str:
    snapshot = copy.deepcopy(runtime.snapshot())
    snapshot["render"]["entities"][0]["asset"]["source"] = source
    return json.dumps(snapshot)


class AssetHost(QObject):
    """Expose the same shared low-poly sphere seam as the desktop host."""

    def __init__(self) -> None:
        super().__init__()
        self.sphere_geometry = None
        self.character_geometry = None
        self.asset_geometry = None

    def _keep_geometry(self, geometry):
        if geometry is None:
            return None
        geometry.setParent(self)
        QQmlEngine.setObjectOwnership(geometry, QQmlEngine.CppOwnership)
        return geometry

    @Slot(result=QObject)
    def gameEngineLowPolySphereGeometry(self) -> QObject:
        if self.sphere_geometry is None:
            from backend.game_engine_geometry import build_low_poly_sphere_geometry

            self.sphere_geometry = build_low_poly_sphere_geometry()
            self._keep_geometry(self.sphere_geometry)
        return self.sphere_geometry

    @Slot(result=QObject)
    def gameEngineCharacterGeometry(self) -> QObject:
        if self.character_geometry is None:
            from backend.game_engine_geometry import build_character_geometry

            self.character_geometry = build_character_geometry()
            self._keep_geometry(self.character_geometry)
        return self.character_geometry

    @Slot(str, str, result=QObject)
    def gameEngineItemGeometry(self, asset_id: str, item_kind: str) -> QObject:
        if self.asset_geometry is None:
            from backend.game_engine_geometry import AssetGeometryCache

            self.asset_geometry = AssetGeometryCache(self)
        return self._keep_geometry(
            self.asset_geometry.geometry_for_item(asset_id, item_kind)
        )

    @Slot(str, str, result=QObject)
    def gameEngineWorldPropGeometry(self, entity_kind: str, variant: str) -> QObject:
        if self.asset_geometry is None:
            from backend.game_engine_geometry import AssetGeometryCache

            self.asset_geometry = AssetGeometryCache(self)
        return self._keep_geometry(
            self.asset_geometry.geometry_for_world_prop(entity_kind, variant)
        )

    @Slot(QObject, str, result=QObject)
    def gameEngineFindNamedNode(self, loader: QObject, name: str) -> QObject | None:
        from backend.chat_surface_host import ChatSurfaceHost

        return ChatSurfaceHost.gameEngineFindNamedNode(self, loader, name)


def main() -> int:
    from backend.game_engine_host import GameEngineRuntime

    app = QGuiApplication.instance() or QGuiApplication([])
    runtime = GameEngineRuntime()
    host = AssetHost()
    engine = QQmlEngine()
    component = QQmlComponent(
        engine,
        QUrl.fromLocalFile(
            str(PROJECT / "qml" / "components" / "GameEngineSurface.qml")
        ),
    )
    root = component.create(QQmlContext(engine.rootContext()))
    errors = component.errors()
    if root is None or errors:
        raise AssertionError([error.toString() for error in errors])

    window = QQuickWindow()
    window.resize(640, 480)
    root.setParentItem(window.contentItem())
    root.setWidth(640)
    root.setHeight(480)
    root.setProperty("surfaceHost", host)
    window.show()

    missing_source = QUrl.fromLocalFile(
        str(PROJECT / "qml" / "assets" / "does-not-exist.gltf")
    ).toString()
    valid_source = QUrl.fromLocalFile(
        str(PROJECT / "qml" / "assets" / "authored" / "gg-clay-hero-a.glb")
    ).toString()
    legacy_source = QUrl.fromLocalFile(
        str(PROJECT / "qml" / "assets" / "gg-authored-hero.gltf")
    ).toString()
    try:
        root.setProperty("statusJson", _snapshot_with_source(runtime, missing_source))
        for _ in range(40):
            app.processEvents()
        figures = root.findChildren(QObject, "gameEntityFigure")
        assert figures
        sphere_geometry = root.property("lowPolySphereGeometry")
        assert sphere_geometry is not None
        assert len(sphere_geometry.indexData()) // 2 // 3 == 120
        figure = figures[0]
        assert figure.property("authoredAssetEligible") is True
        assert figure.property("authoredAssetVisible") is False
        preview = figure.findChildren(QObject, "gameCharacterBodyModel")
        assert preview and preview[0].property("visible") is True
        assert preview[0].property("source") == ""
        assert preview[0].property("geometry") is not None
        loader = figure.findChildren(QObject, "gameAuthoredAssetLoader")
        assert loader and loader[0].metaObject().className() == (
            "QQuick3DRuntimeLoader"
        )

        root.setProperty("statusJson", _snapshot_with_source(runtime, valid_source))
        for _ in range(120):
            app.processEvents()
        assert figure.property("authoredAssetVisible") is True
        preview = figure.findChildren(QObject, "gameCharacterBodyModel")
        assert not any(model.property("visible") is True for model in preview)
        assert str(loader[0].property("errorString")).startswith("Success")
        # RuntimeLoader currently exposes clip names, not SOCKET_* empties.
        # Equipment therefore uses the snapshot attachment rest pose; named
        # parenting is used only when Qt actually publishes the node.
        worn = figure.findChildren(QObject, "gameEquippedItemModel")
        assert worn
        assert {str(item.property("slot") or "") for item in worn} >= {
            "MAIN_HAND",
            "OFF_HAND",
            "BACK",
            "FEET",
        }
        saber = next(
            item for item in worn if str(item.property("slot") or "") == "MAIN_HAND"
        )
        rest = saber.property("rest") or []
        assert list(rest)[:2] == [0.48, -0.29]

        # A desktop process opened before the authored hero promotion can
        # still publish the historical URI.  GameEngineSurface must migrate
        # that URI to the same canonical Blender asset without creating a
        # second body or changing the simulation contract.
        root.setProperty("statusJson", _snapshot_with_source(runtime, legacy_source))
        for _ in range(120):
            app.processEvents()
        assert figure.property("authoredAssetVisible") is True
        assert str(loader[0].property("errorString")).startswith("Success")

        # The bundled hero now contains the complete authored motion contract.
        # Once a fixed step moves an authored character into WALK, RuntimeLoader
        # must select the real Walk action without hiding the authored model.
        moving_snapshot = runtime.step()
        root.setProperty("statusJson", json.dumps(moving_snapshot))
        for _ in range(40):
            app.processEvents()
        moving_npcs = [
            candidate
            for candidate in root.findChildren(QObject, "gameEntityFigure")
            if candidate.property("entityKind") == "NPC"
        ]
        assert moving_npcs
        for candidate in moving_npcs:
            pose = candidate.property("entityPose") or {}
            if pose.get("state") != "WALK":
                continue
            if str((candidate.property("entityAssetMotion") or {}).get("mode", "")) == (
                "PROCEDURAL_GEOMETRY"
            ):
                assert candidate.property("authoredAssetVisible") is False
                assert candidate.property("authoredAssetClipStatus") == (
                    "PROCEDURAL_POSE"
                )
                body = candidate.findChildren(QObject, "gameCharacterBodyModel")
                assert body and body[0].property("visible") is True
                continue
            if str((candidate.property("entityAssetMotion") or {}).get("mode", "")) in {
                "AUTHORED_NODE_ANIMATED",
                "AUTHORED_SKINNED",
            }:
                assert candidate.property("authoredAssetClipStatus") == "READY"
                assert candidate.property("authoredAssetClip") == "Walk"
                continue
            assert candidate.property("authoredAssetVisible") is True
            assert candidate.property("authoredAssetClipStatus") == (
                "ROOT_POSE_ONLY"
            )
            body = candidate.findChildren(QObject, "gameCharacterBodyModel")
            assert not any(model.property("visible") is True for model in body)
            assert candidate.property("entityAssetMotion").get("clip_status") == (
                "ROOT_POSE_ONLY"
            )

        # Keep the UI seam defensive if an older producer or a reconnect
        # briefly repeats the previous Idle binding alongside a new pose.
        stale_moving_snapshot = copy.deepcopy(moving_snapshot)
        for row in stale_moving_snapshot["render"]["entities"]:
            if row.get("kind") != "NPC" or not isinstance(row.get("asset"), dict):
                continue
            row["asset"]["clip"] = "Idle"
            row["asset"]["clip_status"] = "READY"
        root.setProperty("statusJson", json.dumps(stale_moving_snapshot))
        for _ in range(40):
            app.processEvents()
        for candidate in moving_npcs:
            pose = candidate.property("entityPose") or {}
            if pose.get("state") != "WALK":
                continue
            assert candidate.property("authoredAssetVisible") is False
            body = candidate.findChildren(QObject, "gameCharacterBodyModel")
            assert body and body[0].property("visible") is True

        world_item_models = root.findChildren(QObject, "gameWorldItemModel")
        assert len(world_item_models) == 47
        assert sum(model.property("visible") is True for model in world_item_models) == 4
        native_item_models = [
            model for model in world_item_models
            if model.property("visible") is True
        ]
        assert all(model.property("source") == "" for model in native_item_models)
        assert all(model.property("geometry") is not None for model in native_item_models)
        assert all(
            material.property("vertexColorsEnabled") is True
            for model in native_item_models
            for material in model.findChildren(QObject)
            if material.metaObject().className() == "QQuick3DPrincipledMaterial"
        )
        # Native asset-kit geometry is authored in gameplay metres.  It must
        # not inherit sceneScale, which is reserved for Qt's built-in 100-unit
        # primitive meshes.  This catches the async-binding regression where
        # a valid mesh remained present but was rendered at roughly 1% size.
        assert all(
            float(model.property("scale").x()) > 0.05
            for model in native_item_models
        )
        native_prop_models = [
            model
            for model in root.findChildren(QObject, "gameEntityProxyModel")
            if model.property("visible") is True
        ]
        assert native_prop_models
        assert all(model.property("source") == "" for model in native_prop_models)
        assert all(model.property("geometry") is not None for model in native_prop_models)
        assert all(
            material.property("vertexColorsEnabled") is True
            for model in native_prop_models
            for material in model.findChildren(QObject)
            if material.metaObject().className() == "QQuick3DPrincipledMaterial"
        )
        assert all(
            float(model.property("scale").x()) > 0.25
            for model in native_prop_models
        )
        world_loaders = root.findChildren(QObject, "gameAuthoredWorldLoader")
        palm_count = sum(
            str((row.get("asset") or {}).get("asset_id") or "") == "gg-clay-palm"
            for row in runtime.snapshot()["render"]["entities"]
        )
        assert palm_count > 0
        # The Blender GLB is imported once into the shared native mesh cache.
        # Play must not pay a RuntimeLoader per tree.
        assert len(world_loaders) == 0
        item_loaders = root.findChildren(QObject, "gameAuthoredItemLoader")
        expected_item_loaders = sum(
            isinstance(row.get("item"), dict)
            and isinstance(row["item"].get("asset"), dict)
            and row["item"]["asset"].get("mode") == "AUTHORED_STATIC"
            and bool(row["item"]["asset"].get("source"))
            for row in runtime.snapshot()["render"]["entities"]
        )
        assert len(item_loaders) == expected_item_loaders
        assert sum(
            str(item_loader.property("errorString")).startswith("Success")
            for item_loader in item_loaders
        ) == expected_item_loaders
        assert sum(
            item_loader.property("visible") is True for item_loader in item_loaders
        ) == expected_item_loaders
        equipped_models = root.findChildren(QObject, "gameEquippedItemModel")
        assert equipped_models
        assert any(model.property("visible") is True for model in equipped_models)
        equipped_native_models = root.findChildren(
            QObject, "gameEquippedItemPrimitive"
        )
        assert equipped_native_models
        assert all(model.property("source") == "" for model in equipped_native_models)
        assert all(model.property("geometry") is not None for model in equipped_native_models)
        assert all(
            float(model.property("scale").x()) > 0.05
            for model in equipped_native_models
        )
        equipped_loaders = root.findChildren(
            QObject, "gameAuthoredEquippedItemLoader"
        )
        player_equipment = runtime.snapshot()["render"]["entities"][0]["equipment"]
        assert len(equipped_loaders) == len(player_equipment)
        assert len(player_equipment) == 4
        assert sum(
            str(item_loader.property("errorString")).startswith("Success")
            for item_loader in equipped_loaders
        ) == 0

        # Every character-like figure must have exactly one active visual
        # model.  The authored model is preferred even in ROOT_POSE_ONLY; the
        # shared low-poly fallback exists only while its loader is unavailable.
        character_figures = [
            candidate
            for candidate in figures
            if candidate.property("characterLike") is True
        ]
        assert len(character_figures) == 11
        for candidate in character_figures:
            body = candidate.findChildren(QObject, "gameCharacterBodyModel")
            visible_fallbacks = [
                model for model in body if model.property("visible") is True
            ]
            if candidate.property("authoredAssetVisible") is True:
                assert not visible_fallbacks, candidate.property("entityKind")
            else:
                assert len(visible_fallbacks) == 1, candidate.property("entityKind")

        # A fixed-step pose update must not replace the live body geometry.
        # All procedural figures share the one native mesh; motion is carried
        # by their deterministic transform properties instead.  This catches
        # the QtQuick3D render-pass detachment that previously made bodies
        # disappear as soon as PLAY entered WALK.
        fallback_geometries = [
            model.property("geometry")
            for candidate in character_figures
            for model in candidate.findChildren(QObject, "gameCharacterBodyModel")
            if model.property("visible") is True
        ]
        assert fallback_geometries
        assert all(geometry is fallback_geometries[0] for geometry in fallback_geometries)

        # ORBIT keeps a cheap proxy instead of treating roughly eight metres
        # as a hard vanish distance.  The actual camera frustum/clip plane is
        # responsible for removing it from the horizon.
        render_rows = runtime.snapshot()["render"]["entities"]
        proxy_models = root.findChildren(QObject, "gameEntityProxyModel")
        assert len(proxy_models) == len(render_rows)
        expected_proxy_visible = sum(
            row.get("kind") not in {
                "PLAYER", "NPC", "ACTOR", "GROUND_ITEM", "CHEST"
            }
            for row in render_rows
        )
        world_loader_hosts = root.findChildren(QObject, "gameAuthoredWorldLoaderHost")
        authored_world_visible = sum(
            host.property("visible") is True for host in world_loader_hosts
        )
        assert sum(model.property("visible") is True for model in proxy_models) == (
            expected_proxy_visible - authored_world_visible
        )

        # Play only instantiates nearby heightfield cells.  ORBIT coverage is
        # the sea plane, not one QQuick3D node per streamed cell.
        terrain_cells = runtime.snapshot()["terrain"]["cells"]
        dense_cells = [
            cell
            for cell in terrain_cells
            if int((cell.get("geometry") or {}).get("vertex_grid", 1)) > 1
        ]
        terrain_patches = root.findChildren(QObject, "terrainPatchModel")
        assert dense_cells
        assert len(dense_cells) < len(terrain_cells)
        assert len(terrain_patches) == len(dense_cells)
        assert sum(
            patch.property("visible") is True for patch in terrain_patches
        ) == len(dense_cells)
        hlod_tiles = root.findChildren(QObject, "terrainHlodTileModel")
        assert len(hlod_tiles) == len(dense_cells)
        assert sum(tile.property("visible") is True for tile in hlod_tiles) == 0

        runtime.open_container()
        runtime.loot_container()
        runtime.equip_item("crate-tideguard-jacket-01")
        runtime.equip_item("crate-sunken-crown-01")
        root.setProperty("statusJson", json.dumps(runtime.snapshot()))
        for _ in range(40):
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        equipped_models = root.findChildren(QObject, "gameEquippedItemModel")
        assert len(equipped_models) == 6
        assert {model.property("slot") for model in equipped_models} == {
            "MAIN_HAND", "OFF_HAND", "BACK", "FEET", "CHEST", "HEAD"
        }
    finally:
        window.close()
        root.setParentItem(None)
        root.deleteLater()
        runtime.shutdown()
        host.deleteLater()
        app.processEvents()

    print("GAME_ENGINE_QML_ASSET_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
