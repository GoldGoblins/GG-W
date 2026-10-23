"""Lightweight Qt bridge for the standalone GG game client.

The player reuses the authoritative local game simulation and the same cached
Quick3D geometry as the GAME ENGINE preview.  It deliberately does not create
the desktop workbench's chat, browser, wallet, or editor services.
"""

from __future__ import annotations

import json
import math
from typing import Any

from PySide6.QtCore import QObject, Slot, Signal, QCoreApplication

from backend import game_engine_host


class GameClientHost(QObject):
    """Expose only the game runtime and render assets to the player window."""
    gameClientCloseRequested=Signal()

    @Slot(result=bool)
    def gameEngineRequestClose(self):
        self.gameClientCloseRequested.emit();return True

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._terrain_cells: dict[str, dict[str, Any]] = {}
        self._terrain_revision: int | None = None
        self._terrain_geometry_cache: Any = None
        self._character_geometry: QObject | None = None
        self._character_geometry_roles: dict[str, QObject] = {}
        self._character_geometry_poses: dict[tuple[str, int], QObject] = {}
        self._sphere_geometry: QObject | None = None
        self._asset_geometry_cache: Any = None
        self._flora_cache: Any = None
        self._water_wave_geometry: Any = None
        self._planet_water_geometry: Any = None
        self._particle_batch_geometry: Any = None
        self._runtime_clip_driver: Any = None
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._close_runtime_clips)

    @Slot()
    def _close_runtime_clips(self) -> None:
        if self._runtime_clip_driver is not None:
            self._runtime_clip_driver.close()

    def _remember_terrain(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        terrain = value.get("terrain")
        cells = terrain.get("cells") if isinstance(terrain, dict) else None
        if not isinstance(cells, list):
            return
        editor = value.get("terrain_editor")
        if not isinstance(editor, dict) and isinstance(terrain, dict):
            editor = terrain.get("authoring")
        try:
            revision = int(editor.get("revision", 0)) if isinstance(editor, dict) else None
        except (TypeError, ValueError):
            revision = None
        revision_changed = revision != self._terrain_revision
        self._terrain_revision = revision
        remembered = {
            str(cell.get("key", "")): cell
            for cell in cells
            if isinstance(cell, dict) and str(cell.get("key", ""))
        }
        self._terrain_cells = remembered
        cache = self._terrain_geometry_cache
        if cache is not None:
            cache.retain(set(remembered))
            if revision_changed:
                cache.update_cells(remembered)

    def _json(self, value: object) -> str:
        editor = getattr(self, "_game_asset_editor", None)
        if editor is not None:
            value = editor.decorate(value)
        self._publish_game_scene(value)
        if isinstance(value, dict) and '_qt_nature' in value:
            value = {key: row for key,row in value.items() if key != '_qt_nature'}
        self._remember_terrain(value)
        try:
            if hasattr(self, '_scene_driver'):
                if not hasattr(self, '_render_transport'):
                    from backend.game_engine_render_transport import RenderTransport
                    self._render_transport = RenderTransport()
                value = self._render_transport.prepare(value)
            return json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            return json.dumps({
                "schema": game_engine_host.SCHEMA,
                "error": type(exc).__name__ + ":" + str(exc),
            })

    def _own_geometry(self, geometry: QObject | None) -> QObject | None:
        if geometry is None:
            return None
        try:
            if geometry.parent() is None:
                geometry.setParent(self)
        except (AttributeError, RuntimeError, TypeError):
            pass
        try:
            from PySide6.QtQml import QQmlEngine

            QQmlEngine.setObjectOwnership(geometry, QQmlEngine.CppOwnership)
        except (AttributeError, RuntimeError, TypeError):
            pass
        return geometry

    @Slot(result=str)
    def gameEngineStatus(self) -> str:
        return self._json(game_engine_host.status_payload())

    @Slot(str, result=str)
    def gameEngineCharacterCreate(self, raw: str) -> str:
        return json.dumps(game_engine_host.character_create(raw),separators=(",", ":"))

    @Slot(result=QObject)
    def gameEnginePresentation(self):
        from backend.game_engine_presentation import presentation_for
        return presentation_for(self)

    @Slot(result=QObject)
    def gameEngineImportedClient(self):
        from backend.game_engine_adapter_client import client_for
        return self._own_geometry(client_for(self))

    @Slot(result=QObject)
    def gameEngineLocalCharacters(self):
        from backend.game_engine_local_characters import characters_for
        return self._own_geometry(characters_for(self))

    @Slot(result=QObject)
    def gameEngineImportedWaveTexture(self):
        from backend.game_engine_adapter_ffx import wave_for
        return self._own_geometry(wave_for(self))

    @Slot(result=QObject)
    def gameEngineImportedWorld(self):
        from backend.game_engine_adapter_streaming import world_for
        return self._own_geometry(world_for(self))

    @Slot(str,result=str)
    def gameEngineLoadImportedWorld(self,manifest):
        from backend.game_engine_adapter_streaming import load_world
        return json.dumps(load_world(self,manifest),separators=(',',':'))

    @Slot('QVariantMap',result=bool)
    def gameEngineImportedWeather(self,value):
        stream=getattr(self,'_engine_world_stream',None)
        return bool(stream and stream.setWeather(value))
    @Slot('QByteArray',result=bool)
    def gameEngineImportedWeatherPacket(self,payload):
        stream=getattr(self,'_engine_world_stream',None)
        return bool(stream and stream.weatherPacket(payload))
    @Slot('QByteArray',result=bool)
    def gameEngineImportedMusicPacket(self,payload):
        presentation=getattr(self,'_game_presentation',None)
        return bool(presentation and presentation.world_music_packet(payload))

    @Slot(result=str)
    def gameEngineImportedWorldStatus(self):
        from backend.game_engine_adapter_streaming import world_for
        return json.dumps(world_for(self).status(),separators=(',',':'))

    @Slot(QObject,str,result=bool)
    def gameEngineRegisterEntityNode(self, node: QObject, identity: str) -> bool:
        if not hasattr(self,'_scene_driver'):
            from backend.game_engine_scene_driver import SceneDriver
            self._scene_driver=SceneDriver()
        return self._scene_driver.register(node,identity)

    @Slot(str,result=bool)
    def gameEngineSetView(self,raw):
        if not hasattr(self,'_scene_driver'):
            from backend.game_engine_scene_driver import SceneDriver
            self._scene_driver=SceneDriver()
        accepted=self._scene_driver.set_view(raw)
        if getattr(game_engine_host._RUNTIME,'_engine_world',None) is not None:return accepted
        if accepted:
            from backend.game_engine_world_trees import update_world_trees
            update_world_trees(self,self._scene_driver.view)
            from backend.game_engine_world_places_render import update_world_places
            update_world_places(self,self._scene_driver.view)
            from backend.game_engine_ground_cover import update_ground_cover
            update_ground_cover(self,self._scene_driver.view)
            from backend.game_engine_landscape_render import update_landscape
            update_landscape(self,self._scene_driver.view)
        return accepted

    @Slot(result=QObject)
    def gameEngineWorldTrees(self):
        if not hasattr(self,'_world_tree_model'):
            from backend.game_engine_world_trees import WorldTreeModel
            self._world_tree_model=WorldTreeModel(self)
        return self._own_geometry(self._world_tree_model)

    @Slot(result=str)
    def gameEngineWorldTreeMeasurements(self):
        model=getattr(self,'_world_tree_model',None)
        return json.dumps(model.measurements() if model is not None else {})

    @Slot(result=QObject)
    def gameEngineGroundCover(self) -> QObject | None:
        if not hasattr(self, '_ground_cover_model'):
            from backend.game_engine_ground_cover import GroundCoverModel
            self._ground_cover_model = GroundCoverModel(self)
        return self._own_geometry(self._ground_cover_model)

    @Slot(result=QObject)
    def gameEngineWorldPlaces(self):
        if not hasattr(self,'_world_places_model'):
            from backend.game_engine_world_places_render import WorldPlacesModel
            self._world_places_model=WorldPlacesModel(self)
        return self._own_geometry(self._world_places_model)

    @Slot(result=QObject)
    def gameEngineLandscape(self):
        if not hasattr(self,'_landscape_model'):
            from backend.game_engine_landscape_render import LandscapeModel
            self._landscape_model=LandscapeModel(self)
        return self._own_geometry(self._landscape_model)

    @Slot(result=str)
    def gameEngineWorldPlaceMeasurements(self):
        model=getattr(self,'_world_places_model',None)
        return json.dumps(model.measurements() if model is not None else {})

    @Slot(QObject,str,result=bool)
    def gameEngineRegisterRig(self,loader,identity):
        if not hasattr(self,'_scene_driver'):
            from backend.game_engine_scene_driver import SceneDriver
            self._scene_driver=SceneDriver()
        if self._runtime_clip_driver is None:
            from backend.game_engine_runtime import RuntimeClipDriver
            self._runtime_clip_driver=RuntimeClipDriver()
        return self._scene_driver.register_rig(loader,identity,self._runtime_clip_driver)

    def _publish_game_scene(self,value):
        from backend.game_engine_adapter_streaming import update_world
        update_world(self)
        presentation=getattr(self,'_game_presentation',None)
        if presentation is not None:presentation.update(value)
        if not isinstance(value,dict) or not value.get('render',{}).get('entities'):return
        if hasattr(self,'_scene_driver'):self._scene_driver.update(value)
        cache=getattr(self,'_nature_cache',None)
        if cache is not None:
            r=game_engine_host._RUNTIME
            published=value.get('_qt_nature')
            if published is not None and r._running:
                groups,revision=published
            else:
                with r._lock:
                    groups=r._nature.groups;revision=r._nature.revision
            for key,table in tuple(cache.tables.items()):table.replace(groups.get(key,[]),revision)

    @Slot(result=str)
    def gameEngineRenderStatus(self) -> str:
        return self._json(game_engine_host.presentation_payload())

    @Slot(result=str)
    def gameEngineUiStatus(self) -> str:
        return self._json(game_engine_host.ui_status_payload())

    @Slot(str, result=QObject)
    def gameEngineTerrainGeometry(self, cell_key: str) -> QObject | None:
        key = str(cell_key or "")
        cell = self._terrain_cells.get(key)
        if cell is None:
            self._remember_terrain(game_engine_host.status_payload())
            cell = self._terrain_cells.get(key)
        if cell is None:
            return None
        if self._terrain_geometry_cache is None:
            from backend.game_engine_geometry import TerrainGeometryCache

            self._terrain_geometry_cache = TerrainGeometryCache(self)
        return self._own_geometry(self._terrain_geometry_cache.geometry_for_cell(cell))

    @Slot(result=QObject)
    def gameEngineWaterGeometry(self) -> QObject | None:
        if self._water_wave_geometry is None:
            from backend.game_engine_geometry import WaterWaveGeometry

            self._water_wave_geometry = WaterWaveGeometry()
        return self._own_geometry(self._water_wave_geometry.geometry)

    @Slot(result=QObject)
    def gameEnginePlanetWaterGeometry(self) -> QObject | None:
        if self._planet_water_geometry is None:
            from backend.game_engine_geometry import PlanetWaterGeometry

            self._planet_water_geometry = PlanetWaterGeometry()
        return self._own_geometry(self._planet_water_geometry.geometry)

    @Slot(float, result=bool)
    def gameEnginePrepareWaterGpu(self, span_m: float) -> bool:
        self.gameEngineWaterGeometry()
        self.gameEnginePlanetWaterGeometry()
        self._water_wave_geometry.prepare_gpu(span_m)
        self._planet_water_geometry.prepare_gpu(span_m * .5)
        return True

    @Slot(result=QObject)
    def gameEngineSeaBedField(self) -> QObject | None:
        self.gameEngineWaterGeometry()
        field = getattr(self._water_wave_geometry, "seabed", None)
        return self._own_geometry(field)

    @Slot(float, float, float, result=bool)
    @Slot(float, float, float, int, result=bool)
    def gameEngineWaterUpdate(
        self,
        center_x: float,
        center_z: float,
        span_m: float,
        grid_size: int = 49,
    ) -> bool:
        if self._water_wave_geometry is None:
            self.gameEngineWaterGeometry()
        if self._water_wave_geometry is None:
            return False
        clock = game_engine_host.mobility_water_clock()
        self._water_wave_geometry.update(
            center_x,
            center_z,
            clock["time_s"],
            clock["sea_level_m"],
            span_m,
            grid_size,
        )
        if self._planet_water_geometry is not None:
            self._planet_water_geometry.update(
                center_x,
                center_z,
                clock["time_s"],
                clock["sea_level_m"],
                span_m * 0.5,
            )
        return True

    @Slot(result=QObject)
    def gameEngineParticleGeometry(self) -> QObject | None:
        if self._particle_batch_geometry is None:
            from backend.game_engine_geometry import ParticleBatchGeometry

            self._particle_batch_geometry = ParticleBatchGeometry()
        return self._own_geometry(self._particle_batch_geometry.geometry)

    @Slot("QVariantList", result=int)
    def gameEngineParticleUpdate(self, rows: list[Any]) -> int:
        if self._particle_batch_geometry is None:
            self.gameEngineParticleGeometry()
        if self._particle_batch_geometry is None:
            return 0
        return self._particle_batch_geometry.update(rows)

    @Slot(result=QObject)
    def gameEngineAdditiveParticleGeometry(self) -> QObject | None:
        if getattr(self, '_additive_particle_batch_geometry', None) is None:
            from backend.game_engine_geometry import ParticleBatchGeometry
            self._additive_particle_batch_geometry = ParticleBatchGeometry()
        return self._own_geometry(self._additive_particle_batch_geometry.geometry)

    @Slot("QVariantList", result=int)
    def gameEngineAdditiveParticleUpdate(self, rows: list[Any]) -> int:
        self.gameEngineAdditiveParticleGeometry()
        return self._additive_particle_batch_geometry.update(rows)

    @Slot(float, float, result="QVariantList")
    def gameEngineWorldFxAnchors(self, x: float, z: float) -> list[dict]:
        from backend.game_engine_world_effects import lamp_anchors
        runtime = game_engine_host._RUNTIME
        with runtime._lock:
            return lamp_anchors(x, z, runtime._terrain_height_locked)

    @Slot(float, float, result="QVariantList")
    def gameEngineEnvironmentFxAnchors(self, x: float, z: float) -> list[dict]:
        from backend.game_engine_world_effects import environment_anchors
        runtime = game_engine_host._RUNTIME
        with runtime._lock:
            return environment_anchors(x, z, runtime._terrain_height_locked)

    @Slot(float, result="QVariantList")
    def gameEngineLightBeacons(self, range_m: float) -> list[dict]:
        from backend.game_engine_world_effects import lamp_beacons
        from backend.game_engine_render import PROFILES
        runtime=game_engine_host._RUNTIME
        view=getattr(getattr(self,'_scene_driver',None),'view',None)
        if view is None:return []
        with runtime._lock:
            policy=PROFILES[runtime._render_profile]
            revision=(id(runtime._terrain_overrides),runtime._terrain_overrides.get('revision',0))
            if getattr(self,'_beacon_terrain_revision',None)!=revision:
                self._beacon_heights={};self._beacon_terrain_revision=revision
            return lamp_beacons(view,min(float(range_m),policy['world_view_distance_m']*1.18),
                runtime._terrain_height_locked,policy['max_light_beacons'],self._beacon_heights)

    @Slot(result=QObject)
    def gameEngineCharacterGeometry(self) -> QObject | None:
        if self._character_geometry is None:
            from backend.game_engine_geometry import build_character_geometry

            self._character_geometry = self._own_geometry(build_character_geometry())
        return self._character_geometry

    @Slot(str, result=QObject)
    def gameEngineCharacterGeometryForRole(self, role: str) -> QObject | None:
        from backend.game_engine_geometry import (
            build_character_geometry,
            character_variant_key,
        )

        key = character_variant_key(role)
        if key == "CROWD":
            return self.gameEngineCharacterGeometry()
        geometry = self._character_geometry_roles.get(key)
        if geometry is None:
            geometry = self._own_geometry(build_character_geometry(variant=key))
            if geometry is not None:
                self._character_geometry_roles[key] = geometry
        return geometry

    @Slot(result=QObject)
    def gameEngineLowPolySphereGeometry(self) -> QObject | None:
        if self._sphere_geometry is None:
            from backend.game_engine_geometry import build_low_poly_sphere_geometry

            self._sphere_geometry = self._own_geometry(build_low_poly_sphere_geometry())
        return self._sphere_geometry

    @Slot(str, str, result=QObject)
    def gameEngineItemGeometry(self, asset_id: str, item_kind: str) -> QObject | None:
        if self._asset_geometry_cache is None:
            from backend.game_engine_geometry import AssetGeometryCache

            self._asset_geometry_cache = AssetGeometryCache(self)
        geometry = self._asset_geometry_cache.geometry_for_item(asset_id, item_kind)
        return self._own_geometry(geometry)

    @Slot(str,str,QObject,result=QObject)
    def gameEnginePreviewItemGeometry(self,asset_id,item_kind,owner):
        from backend.game_engine_geometry import preview_item_geometry
        return preview_item_geometry(self,asset_id,item_kind,owner)

    @Slot(str, str, result=QObject)
    def gameEngineWorldPropGeometry(
        self, entity_kind: str, variant: str
    ) -> QObject | None:
        if self._asset_geometry_cache is None:
            from backend.game_engine_geometry import AssetGeometryCache

            self._asset_geometry_cache = AssetGeometryCache(self)
        geometry = self._asset_geometry_cache.geometry_for_world_prop(
            entity_kind, variant
        )
        return self._own_geometry(geometry)

    def _flora_render_cache(self):
        if self._flora_cache is None:
            from backend.game_engine_ecology_render import FloraRenderCache
            self._flora_cache = FloraRenderCache(self)
        return self._flora_cache

    @Slot(str, result=QObject)
    def gameEngineFloraGeometry(self, key: str) -> QObject | None:
        return self._own_geometry(self._flora_render_cache().geometry(key))

    @Slot(str, result=QObject)
    def gameEngineFloraInstances(self, key: str) -> QObject | None:
        rows, revision = game_engine_host._RUNTIME.ecology_batch(key)
        editor = getattr(self, "_game_asset_editor", None)
        if editor is not None:
            rows, revision = editor.batch(rows, revision)
        return self._own_geometry(self._flora_render_cache().table(key, rows, revision))

    def _nature_render_cache(self):
        if not hasattr(self,"_nature_cache"):
            from pathlib import Path
            from backend.game_engine_ecology_render import FloraRenderCache
            from backend.game_engine_nature import GROUP_KEYS
            self._nature_cache=FloraRenderCache(self,assets=Path(__file__).resolve().parents[1]/"qml/assets/authored/nature",keys=GROUP_KEYS)
        return self._nature_cache

    @Slot(str, result=QObject)
    def gameEngineNatureGeometry(self, key: str) -> QObject | None:
        return self._own_geometry(self._nature_render_cache().geometry(key))

    @Slot(str, result=QObject)
    def gameEngineNatureInstances(self, key: str) -> QObject | None:
        rows,revision=game_engine_host._RUNTIME.nature_batch(key)
        editor = getattr(self, "_game_asset_editor", None)
        if editor is not None:
            rows, revision = editor.batch(rows, revision)
        return self._own_geometry(self._nature_render_cache().table(key,rows,revision))

    @Slot(QObject, str, result=int)
    def gameEngineEnablePicking(self, loader: QObject, entity_id: str) -> int:
        if not isinstance(loader,QObject):return 0
        identity=entity_id
        if entity_id.startswith('e-'):
            identity=self.gameEngineEntityIdentity(entity_id)
        count=0
        from backend.game_engine_runtime import scene_models
        for node in scene_models(loader):
            if node.inherits('QQuick3DModel'):
                node.setProperty('pickable',True)
                node.setObjectName('ggPick:'+identity)
                count+=1
        return count

    @Slot(str, result=str)
    def gameEngineWorldHover(self, identity: str) -> str:
        return self._json(game_engine_host._RUNTIME.world_hover(identity))

    @Slot(QObject, QObject, str, result=str)
    def gameEngineAssetEditor(self, context: QObject, loader: QObject, raw: str) -> str:
        from backend.game_engine_asset_editor import dispatch
        return dispatch(self, context, loader, raw)

    @Slot(str, result=str)
    def gameEngineWorldSelect(self, identity: str) -> str:
        return self._json(game_engine_host._RUNTIME.world_select(identity))

    @Slot(str, result=str)
    def gameEngineWorldContext(self, identity: str) -> str:
        presentation=getattr(self,'_game_presentation',None);runtime=game_engine_host._RUNTIME
        result=presentation.context_world(identity,runtime.world_context,runtime.merchant_sell) if presentation else runtime.world_context(identity)
        return self._json(result)

    @Slot(str, bool, result=str)
    def gameEngineWorldTargetCycle(self, camera: str, reverse: bool) -> str:
        return self._json(game_engine_host._RUNTIME.world_target_cycle(camera,reverse))

    @Slot(str, result=str)
    def gameEngineActionBarEdit(self, raw: str) -> str:
        return self._json(game_engine_host._RUNTIME.action_bar_edit(raw))

    @Slot(int, result=str)
    def gameEngineActionUse(self, index: int) -> str:
        from backend.game_engine_presentation import use_action_for
        return self._json(use_action_for(self,game_engine_host._RUNTIME,index))

    @Slot(str,result=str)
    def gameEngineMacroState(self,raw: str) -> str:
        return self._json(game_engine_host._RUNTIME.set_client_macros(raw))

    @Slot(str, result=str)
    def gameEngineActionCommand(self, command: str) -> str:
        return self._json(game_engine_host._RUNTIME.action_command(command))

    @Slot(str, result=str)
    def gameEngineActionUseItem(self, definition: str) -> str:
        return self._json(game_engine_host._RUNTIME.action_use_item(definition))

    @Slot(str, str, result=str)
    def gameEngineContainerUseItem(self, definition: str, instance_id: str) -> str:
        return self._json(game_engine_host._RUNTIME.action_use_item(definition,instance_id))

    @Slot(str, int, bool, result=str)
    def gameEngineInstanceIdentity(self, key: str, index: int, animal: bool) -> str:
        cache=self._nature_render_cache() if animal else self._flora_render_cache()
        table=cache.tables.get(key)
        identities=getattr(table,'identities',())
        return identities[index] if 0<=index<len(identities) else ''

    @Slot(str, result=str)
    def gameEngineEntityIdentity(self, entity_id: str) -> str:
        r=game_engine_host._RUNTIME
        with r._lock:
            if entity_id.startswith('e-'):
                try:index=int(entity_id[2:])
                except ValueError:return ''
                return str(r._npc_ids[index] or '') if 0<=index<len(r._npc_ids) else ''
            if entity_id.startswith('item-'):
                identity=entity_id[5:]
                return identity if identity in r._item_instances else ''
            return entity_id if any(row['id']==entity_id for row in r._world_interaction_rows_locked()) else ''

    @Slot(str,str,result=str)
    def gameEngineNatureAction(self, target_id: str, action: str) -> str:
        return self._json(game_engine_host._RUNTIME.nature_action(target_id,action))

    @Slot(QObject, str, result=QObject)
    def gameEngineFindNamedNode(self, loader: QObject, name: str) -> QObject | None:
        from backend.game_engine_runtime import imported_named_node
        return imported_named_node(loader, name)

    @Slot(str, QObject, result=QObject)
    def gameEngineEmblemTexture(self, uri: str, owner: QObject) -> QObject | None:
        from backend.game_engine_adapter_materials import emblem_texture_data
        return emblem_texture_data(self,uri,owner)

    @Slot('QQuaternion','QQuaternion','QVector3D',result='QVariantMap')
    def gameEngineAlignedAttachment(self, socket_rotation, actor_rotation, offset):
        from backend.game_engine_adapter_materials import aligned_attachment
        return aligned_attachment(socket_rotation,actor_rotation,offset)

    @Slot(QObject, str, float, result=bool)
    @Slot(QObject, str, float, str, result=bool)
    def gameEngineRuntimeClip(
        self, loader: QObject, clip: str, cadence_hz: float = 0.0, trigger_id: str = ""
    ) -> bool:
        if self._runtime_clip_driver is None:
            from backend.game_engine_runtime import RuntimeClipDriver

            self._runtime_clip_driver = RuntimeClipDriver()
        return self._runtime_clip_driver.apply(loader, clip, cadence_hz, trigger_id)

    @Slot(QObject, result=bool)
    def gameEngineReleaseRuntimeClip(self, loader: QObject) -> bool:
        driver=self._runtime_clip_driver
        return bool(driver and driver.release(loader))

    @Slot(str, float, result=QObject)
    def gameEngineCharacterGeometryForPose(
        self, motion_state: str, phase: float
    ) -> QObject | None:
        from backend.game_engine_geometry import (
            CHARACTER_POSE_BUCKETS,
            build_character_geometry,
            character_pose_key,
        )

        key = character_pose_key(motion_state, phase)
        geometry = self._character_geometry_poses.get(key)
        if geometry is None:
            geometry = self._own_geometry(
                build_character_geometry(
                    key[0], key[1] / float(CHARACTER_POSE_BUCKETS) * math.tau
                )
            )
            if geometry is not None:
                self._character_geometry_poses[key] = geometry
        return geometry

    def _call(self, function: Any, *args: Any) -> str:
        return self._json(function(*args))

    def _start_local(self,method):
        characters=getattr(self,'_local_characters',None)
        if characters and (characters.phase!='WORLD' or not characters.active_id):
            snapshot=game_engine_host._RUNTIME.ui_snapshot()
            snapshot['error']='LOCAL_CHARACTER_REQUIRED'
            return self._json(snapshot)
        return self._call(method)

    @Slot(result=str)
    def gameEngineStart(self) -> str:
        return self._start_local(game_engine_host.start)

    @Slot(result=str)
    def gameEngineStartRender(self) -> str:
        return self._start_local(game_engine_host.start_render)

    @Slot(result=str)
    def gameEnginePause(self) -> str:
        return self._call(game_engine_host.pause)

    @Slot(result=str)
    def gameEnginePauseRender(self) -> str:
        return self._call(game_engine_host.pause_render)

    @Slot(result=str)
    def gameEngineReset(self) -> str:
        return self._call(game_engine_host.reset)

    @Slot(result=str)
    def gameEngineStep(self) -> str:
        return self._call(game_engine_host.step)

    @Slot(result=str)
    def gameEngineBurst(self) -> str:
        return self._call(game_engine_host.burst)

    @Slot(bool, result=str)
    def gameEngineStress(self, enabled: bool) -> str:
        return self._call(game_engine_host.set_stress, bool(enabled))

    @Slot(str, result=str)
    def gameEngineMovementMode(self, mode: str) -> str:
        return self._call(game_engine_host.set_movement_mode, str(mode or "GROUND"))

    @Slot(str, result=str)
    def gameEngineMobilityAction(self, action: str) -> str:
        return self._call(game_engine_host.mobility_action, str(action or ""))

    @Slot(str, result=str)
    def gameEngineExploreRegion(self, region_id: str) -> str:
        return self._call(game_engine_host.explore_region, str(region_id or ""))

    @Slot(str, result=str)
    def gameEngineAbility(self, ability_id: str) -> str:
        return self._call(
            game_engine_host.activate_ability, str(ability_id or "ability.surge")
        )

    @Slot(str, result=str)
    @Slot(str,str, result=str)
    def gameEngineAttack(self, target_id: str, action_id: str = 'basic_attack') -> str:
        return self._call(game_engine_host.attack, str(target_id or ""),str(action_id or 'basic_attack'))

    @Slot(bool, result=str)
    def gameEngineTargetNext(self, reverse: bool) -> str:
        return self._call(game_engine_host.cycle_target, reverse)

    @Slot(result=str)
    def gameEngineTargetClear(self) -> str:
        return self._call(game_engine_host.clear_target)

    @Slot(str,str, result=str)
    def gameEngineNpcTalk(self, npc_id: str, choice_id: str) -> str:
        return self._call(game_engine_host.talk_npc, str(npc_id or ""), str(choice_id or ""))

    @Slot(result=str)
    def gameEngineNpcInteract(self) -> str:
        return self._call(game_engine_host.npc_interact)

    @Slot(result=str)
    def gameEngineNpcDialogueClose(self) -> str:
        return self._call(game_engine_host._RUNTIME.close_dialogue)

    @Slot(result=str)
    def gameEngineItemInteract(self) -> str:
        return self._call(game_engine_host.interact_item)

    @Slot(str, result=str)
    def gameEngineContainerOpen(self, instance_id: str) -> str:
        return self._call(game_engine_host.open_container, str(instance_id or ""))

    @Slot(str, result=str)
    def gameEngineContainerLoot(self, instance_id: str) -> str:
        return self._call(game_engine_host.loot_container, str(instance_id or ""))

    @Slot(str, result=str)
    def gameEngineTalent(self, talent_id: str) -> str:
        return self._call(game_engine_host.add_talent, str(talent_id or ''))

    @Slot(str, result=str)
    def gameEngineCraft(self, recipe_id: str) -> str:
        return self._call(game_engine_host.craft_recipe, str(recipe_id or ''))

    @Slot(str, str, result=str)
    def gameEngineCraftingOpen(self, book: str, station_id: str) -> str:
        return self._call(game_engine_host._RUNTIME.open_crafting, book, station_id)

    @Slot(int, result=str)
    def gameEngineCraftingClose(self, session: int) -> str:
        return self._call(game_engine_host._RUNTIME.close_crafting, session)

    @Slot(result=str)
    def gameEngineCraftingStop(self) -> str:
        return self._call(game_engine_host._RUNTIME.stop_crafting)

    @Slot(int, str, int, result=str)
    def gameEngineCraftBookRecipe(self, session: int, recipe_id: str, count: int) -> str:
        return self._call(game_engine_host._RUNTIME.craft_book_recipe, session, recipe_id, count)

    @Slot(int, str, str, result=str)
    def gameEngineLootSlot(self, session: int, source: str, instance_id: str) -> str:
        return self._call(game_engine_host._RUNTIME.loot_slot, session, source, instance_id)

    @Slot(int, result=str)
    def gameEngineLootClose(self, session: int) -> str:
        return self._call(game_engine_host._RUNTIME.close_loot, session)

    @Slot(str, str, result=str)
    def gameEngineGearCraft(self, recipe_id: str, station_id: str) -> str:
        return self._call(game_engine_host.craft_gear, str(recipe_id or ""), str(station_id or ""))

    @Slot(str, str, result=str)
    def gameEngineGearEnchant(self, instance_id: str, enchant_id: str) -> str:
        return self._call(game_engine_host.enchant_gear, str(instance_id or ""), str(enchant_id or ""))

    @Slot(str, str, result=str)
    def gameEngineItemSocket(self, instance_id: str, insertable_id: str) -> str:
        return self._call(game_engine_host.socket_item, str(instance_id or ""), str(insertable_id or ""))

    @Slot(str, result=str)
    def gameEngineItemPickup(self, instance_id: str) -> str:
        return self._call(game_engine_host.pickup_item, str(instance_id or ""))

    @Slot(str, result=str)
    @Slot(str, str, result=str)
    def gameEngineItemEquip(self, instance_id: str, slot: str = "") -> str:
        return self._call(game_engine_host.equip_item, str(instance_id or ""),str(slot or ""))

    @Slot(str, result=str)
    def gameEngineItemUnequip(self, instance_id: str) -> str:
        return self._call(game_engine_host.unequip_item, str(instance_id or ""))

    @Slot(str, int, result=str)
    def gameEngineEquipmentMove(self, instance_id: str, slot_index: int) -> str:
        return self._call(game_engine_host.move_equipment_to_inventory,str(instance_id or ""),int(slot_index))

    @Slot(result=str)
    def gameEngineFirearmReload(self) -> str:
        return self._call(game_engine_host.reload_firearms)

    @Slot(str, int, result=str)
    def gameEngineInventoryMove(self, instance_id: str, slot_index: int) -> str:
        return self._call(game_engine_host.move_inventory_slot, str(instance_id or ""), slot_index)

    @Slot(str, int, int, result=str)
    def gameEngineInventoryStack(self, instance_id: str, slot_index: int, count: int) -> str:
        return self._call(game_engine_host.transfer_inventory_stack,str(instance_id or ""),slot_index,count)

    @Slot(str, result=str)
    def gameEngineItemDrop(self, instance_id: str) -> str:
        return self._call(game_engine_host.drop_item, str(instance_id or ""))

    @Slot(str, result=str)
    def gameEngineBankDeposit(self, instance_id: str) -> str:
        return self._call(game_engine_host.deposit_to_stash, str(instance_id or ""))

    @Slot(str, result=str)
    def gameEngineBankWithdraw(self, instance_id: str) -> str:
        return self._call(game_engine_host.withdraw_from_stash, str(instance_id or ""))

    @Slot(str, int, result=str)
    def gameEngineBankDepositAt(self, instance_id: str, slot_index: int) -> str:
        return self._call(game_engine_host.deposit_to_stash, str(instance_id or ""), slot_index)

    @Slot(str, int, result=str)
    def gameEngineBankWithdrawAt(self, instance_id: str, slot_index: int) -> str:
        return self._call(game_engine_host.withdraw_from_stash, str(instance_id or ""), slot_index)

    @Slot(str, int, result=str)
    def gameEngineBankMove(self, instance_id: str, slot_index: int) -> str:
        return self._call(game_engine_host.move_stash_slot, str(instance_id or ""), slot_index)

    @Slot(result=str)
    def gameEngineBankClose(self) -> str:
        return self._call(game_engine_host._RUNTIME.close_bank)

    @Slot(str, result=str)
    def gameEngineMerchantOpen(self, vendor_id: str) -> str:
        return self._call(game_engine_host._RUNTIME.open_merchant, str(vendor_id or ""))

    @Slot(result=str)
    def gameEngineMerchantClose(self) -> str:
        return self._call(game_engine_host._RUNTIME.close_merchant)

    @Slot(str, str, result=str)
    def gameEngineMerchantBuy(self, vendor_id: str, instance_id: str) -> str:
        return self._call(game_engine_host._RUNTIME.merchant_buy, vendor_id, instance_id)

    @Slot(str, str, result=str)
    def gameEngineMerchantSell(self, vendor_id: str, instance_id: str) -> str:
        return self._call(game_engine_host._RUNTIME.merchant_sell, vendor_id, instance_id)

    @Slot(str, str, int, result=str)
    def gameEngineMerchantSellCount(self, vendor_id, instance_id, quantity):
        return self._call(game_engine_host._RUNTIME.merchant_sell, vendor_id, instance_id, quantity)

    @Slot(str,str,int,result=str)
    def gameEngineMerchantBuyAt(self,vendor_id,instance_id,slot):
        return self._call(game_engine_host._RUNTIME.merchant_buy_at,vendor_id,instance_id,slot)

    @Slot(str,str,result=str)
    def gameEngineMerchantBuyBundles(self,vendor_id,requests):
        return self._call(game_engine_host._RUNTIME.merchant_buy_bundles,vendor_id,requests)

    @Slot(str,str,result=str)
    def gameEngineMerchantBuyback(self,vendor_id,instance_id):
        return self._call(game_engine_host._RUNTIME.merchant_buyback,vendor_id,instance_id)

    @Slot(str,str,result=str)
    def gameEngineMerchantRepair(self,vendor_id,instance_id):
        return self._call(game_engine_host._RUNTIME.merchant_repair,vendor_id,instance_id)

    @Slot(str, str, result=str)
    def gameEngineVendorBuy(self, vendor_id: str, instance_id: str) -> str:
        return self._call(game_engine_host.vendor_buy, str(vendor_id or ""), str(instance_id or ""))

    @Slot(str, str, result=str)
    def gameEngineVendorSell(self, vendor_id: str, instance_id: str) -> str:
        return self._call(game_engine_host.vendor_sell, str(vendor_id or ""), str(instance_id or ""))

    @Slot(str, result=str)
    def gameEngineQuestAccept(self, quest_id: str) -> str:
        return self._call(game_engine_host.accept_quest, str(quest_id or ""))

    @Slot(str, result=str)
    def gameEngineQuestClaim(self, quest_id: str) -> str:
        return self._call(game_engine_host.claim_quest, str(quest_id or ""))

    @Slot(str,str,result=str)
    def gameEngineQuestDialogSelect(self,npc_id,quest_id):
        return self._call(game_engine_host._RUNTIME.quest_dialog_select,str(npc_id),str(quest_id))

    @Slot(str,str,str,str,int,result=str)
    def gameEngineQuestDialogAction(self,npc_id,quest_id,panel,action,choice):
        return self._call(game_engine_host._RUNTIME.quest_dialog_action,str(npc_id),str(quest_id),str(panel),str(action),choice)

    @Slot(str,result=str)
    def gameEngineQuestAbandon(self,quest_id):
        return self._call(game_engine_host._RUNTIME.abandon_quest,str(quest_id))

    @Slot(result=str)
    def gameEngineGossipClose(self):
        return self._call(game_engine_host._RUNTIME.gossip_close)

    @Slot(result=str)
    def gameEngineLoot(self) -> str:
        return self._call(game_engine_host.claim_loot)

    @Slot(int, result=str)
    def gameEngineXp(self, amount: int) -> str:
        return self._call(game_engine_host.grant_experience, int(amount))

    @Slot(str, result=str)
    def gameEngineRenderProfile(self, profile: str) -> str:
        return self._call(game_engine_host.set_render_profile, str(profile or "BALANCED"))

    @Slot(str, result=str)
    def gameEnginePresentationMode(self, mode: str) -> str:
        return self._call(game_engine_host.set_presentation_mode, str(mode or "RICH_3D"))

    @Slot(str, result=str)
    def gameEngineGraphicsFailure(self, reason: str) -> str:
        return self._call(
            game_engine_host.report_graphics_failure,
            str(reason or "GRAPHICS_STAGE_FAILURE"),
        )

    @Slot(str, result=str)
    def gameEngineCinematic(self, preset: str) -> str:
        return self._call(
            game_engine_host.set_cinematic_preset,
            str(preset or "FIRST_ISLAND_DIORAMA"),
        )

    @Slot(str, result=str)
    def gameEngineInput(self, raw: str) -> str:
        return self._call(game_engine_host.set_input, str(raw or "{}"))

    @Slot(str, result=str)
    def gameEngineClientControl(self, raw: str) -> str:
        return self._call(game_engine_host.client_control, str(raw or "{}"))

    @Slot(str, result=str)
    def gameEngineClientControls(self, raw: str) -> str:
        return self._call(game_engine_host.client_controls_batch, str(raw or "[]"))

    @Slot(str, result=str)
    def gameEngineInputRender(self, raw: str) -> str:
        return self._call(game_engine_host.set_input_render, str(raw or "{}"))

    @Slot(str, str, result=str)
    def gameEngineKeybinding(self, action: str, key: str) -> str:
        return self._call(
            game_engine_host.set_keybinding, str(action or ""), str(key or "")
        )

    @Slot(result=str)
    def gameEngineKeybindingsReset(self) -> str:
        return self._call(game_engine_host.reset_keybindings)

    @Slot(str, bool, result=str)
    def gameEngineAddon(self, addon_id: str, enabled: bool) -> str:
        return self._call(
            game_engine_host.set_addon, str(addon_id or ""), bool(enabled)
        )

    @Slot(result=str)
    def gameEngineSave(self) -> str:
        return self._call(game_engine_host.save_state)

    @Slot(result=str)
    def gameEngineLoad(self) -> str:
        return self._call(game_engine_host.load_state)


__all__ = ["GameClientHost"]
