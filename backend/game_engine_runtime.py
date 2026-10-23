"""Small bounded adapter for Qt Quick 3D imported animation timelines."""

from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import json
import math
from pathlib import Path
import struct
import weakref
from typing import Any

from PySide6.QtCore import QObject, QRegularExpression, QUrl, QTimer
from PySide6.QtGui import QQuaternion, QVector3D
from shiboken6 import isValid
from backend.game_engine_animation import ONE_SHOT_CLIPS


def named_nodes(loader: QObject, pattern: str):
    """Search scene objects and clip jobs without descending into keyframes."""
    expression = QRegularExpression(pattern)
    expression.setPatternOptions(QRegularExpression.CaseInsensitiveOption)
    rows=[];pending=list(reversed(loader.children()))
    while pending:
        node=pending.pop()
        if node.inherits('QQuickKeyframeGroup') or node.inherits('QQuickKeyframe'):
            continue
        if expression.match(node.objectName()).hasMatch():rows.append(node)
        if node.inherits('QQuickTimeline'):
            # Imported timelines own large keyframe tables alongside their
            # animation jobs. Socket and clip lookup needs only the jobs.
            pending.extend(reversed([child for child in node.children()
                           if child.inherits('QQuickTimelineAnimation')]))
        elif not node.inherits('QQuickTimelineAnimation'):
            pending.extend(reversed(node.children()))
    return rows


def _rig_name_index(loader: QObject):
    """Keep socket lookup on the small scene tree, outside animation tables."""
    source = loader.property('source')
    epoch = source.toString() if isinstance(source, QUrl) else str(source or '')
    cached = getattr(loader, '_gg_rig_names', None)
    if cached is not None and cached['source'] == epoch:
        return cached
    if not getattr(loader, '_gg_rig_name_hooks', False):
        reference = weakref.ref(loader)
        def invalidate(*_):
            current = reference()
            if current is not None and isValid(current):
                current._gg_rig_names = None
        for signal_name in ('sourceChanged', 'statusChanged'):
            signal = getattr(loader, signal_name, None)
            if signal is not None:signal.connect(invalidate)
        loader._gg_rig_name_hooks = True
    cached = dict(source=epoch, nodes={}, resolved=False, children={}, scene=[])
    def scene_children(obj):
        # Keep a single importer snapshot for both named lookup and serialized
        # tree matching. Repeated candidates must not reread QObject children.
        children = tuple(child for child in obj.children() if child.inherits('QQuick3DNode'))
        cached['children'][id(obj)] = children
        return children
    pending = list(scene_children(loader))
    while pending:
        node = pending.pop()
        cached['scene'].append(node)
        label = node.objectName().casefold()
        if label:cached['nodes'].setdefault(label, node)
        pending.extend(scene_children(node))
        # A negative lookup also depends on unnamed nodes remaining alive.
        # Retire it when any node in this scene is deleted, without a hot-path
        # validity walk or keeping deleted wrappers as an accepted result.
        if not getattr(node, '_gg_rig_name_hook', False):
            reference = weakref.ref(loader); node_key = id(node)
            def destroyed(*_, reference=reference, node_key=node_key):
                owner = reference()
                if owner is None or not isValid(owner):return
                current = getattr(owner, '_gg_rig_names', None)
                if current is not None and node_key in current['children']:
                    owner._gg_rig_names = None
            node.destroyed.connect(destroyed)
            node._gg_rig_name_hook = True
    loader._gg_rig_names = cached
    return cached


def scene_models(loader: QObject):
    """Visit the imported scene without descending into animation keyframes."""
    pending = [loader]
    while pending:
        node = pending.pop()
        if node is not loader and not node.inherits("QQuick3DNode"):
            continue
        if node.inherits("QQuick3DModel"):
            yield node
        pending.extend(node.children())


def _imported_node_document(filename: str):
    stat=Path(filename).stat()
    return _cached_node_document(filename,stat.st_mtime_ns,stat.st_size)


@lru_cache(maxsize=128)
def _cached_node_document(filename: str, modified_ns: int, source_bytes: int):
    """Read glTF scene JSON without loading its textures or geometry buffer."""
    if Path(filename).suffix.lower()=='.gltf':
        if source_bytes>4_194_304:return None
        document=json.loads(Path(filename).read_text(encoding='utf-8'))
    else:
        with Path(filename).open("rb") as stream:
            header = stream.read(20)
            if len(header) != 20:
                return None
            magic, version, _, length, kind = struct.unpack("<5I", header)
            if magic != 0x46546C67 or version != 2 or kind != 0x4E4F534A or length > 4_194_304:
                return None
            document = json.loads(stream.read(length))
    if len(document.get('nodes',()))>256 or len(document.get('animations',()))>60:
        return None
    paths={}
    for animation in document.get('animations',[]):
        for channel in animation.get('channels',[]):
            target=channel.get('target',{})
            if target.get('path') in {'translation','rotation','scale'}:
                paths.setdefault(target['node'],set()).add(target['path'])
    # Cache the small scene tree and animated property names. Thousands of
    # sampler/accessor descriptions must not remain resident per NPC source.
    return dict(nodes=document.get('nodes',[]),scenes=document.get('scenes',[]),
                scene=document.get('scene',0),animated_paths=paths)


def imported_named_node(loader: QObject, name: str) -> QObject | None:
    """Resolve Qt's unnamed GLTF nodes against their real serialized tree.

    RuntimeLoader retains the hierarchy and transforms, but this Qt importer
    leaves objectName empty. Match the complete node tree, including static
    translations and model leaves, before restoring the authored names. No
    joint order, character dimensions or guessed hand positions are used.
    """
    wanted = str(name or "").strip().casefold()
    if not isinstance(loader, QObject) or not wanted:
        return None
    try:
        cached = _rig_name_index(loader)
        node = cached['nodes'].get(wanted)
        if node is not None:
            if isValid(node):return node
            loader._gg_rig_names = None
            cached = _rig_name_index(loader)
            replacement = cached['nodes'].get(wanted)
            if replacement is not None and isValid(replacement):return replacement
        if cached['resolved']:
            return None
        source = loader.property("source")
        path = source.toLocalFile() if isinstance(source, QUrl) else QUrl(str(source)).toLocalFile()
        document = _imported_node_document(path) if path else None
        if not document:
            return None
        nodes = document.get("nodes", [])
        roots = document.get("scenes", [])[int(document.get("scene", 0))].get("nodes", [])
        animated_positions={i for i,paths in document['animated_paths'].items() if 'translation' in paths}
        animated_rotations={i for i,paths in document['animated_paths'].items() if 'rotation' in paths}

        matches = {}
        def match(index, obj):
            key = (index, id(obj))
            if key in matches:return matches[key]
            # Cache failures as well as successes. A serialized descendant can
            # be considered beneath many candidate roots of an ambiguous rig.
            matches[key] = None
            spec = nodes[index]
            if bool("mesh" in spec) != bool(obj.inherits("QQuick3DModel")):
                return None
            real_children = cached['children'][id(obj)]
            expected_children = spec.get("children", [])
            if len(real_children) != len(expected_children):
                return None
            if index not in animated_positions and "matrix" not in spec:
                position = obj.property("position")
                expected = spec.get("translation", (0., 0., 0.))
                if any(abs(a - b) > .0001 for a, b in zip((position.x(), position.y(), position.z()), expected)):
                    return None
            if index not in animated_rotations and "matrix" not in spec:
                rotation = obj.property("rotation")
                expected = spec.get("rotation", (0., 0., 0., 1.))
                actual = (rotation.x(), rotation.y(), rotation.z(), rotation.scalar())
                if abs(sum(a * b for a, b in zip(actual, expected))) < .99999:
                    return None
            pairs = [(index, obj)]
            unused = list(real_children)
            for child_index in expected_children:
                for candidate in unused:
                    branch = match(child_index, candidate)
                    if branch is not None:
                        pairs.extend(branch)
                        unused.remove(candidate)
                        break
                else:
                    return None
            matches[key] = tuple(pairs)
            return matches[key]

        candidates = cached['scene'][:512]
        for index in roots:
            for candidate in candidates:
                pairs = match(index, candidate)
                if pairs is None:
                    continue
                for node_index, obj in pairs:
                    label = str(nodes[node_index].get("name", ""))
                    if label:
                        obj.setObjectName(label)
                        cached['nodes'].setdefault(label.casefold(), obj)
                cached['resolved'] = True
                for _, obj in pairs:
                    if obj.objectName().casefold() == wanted:
                        return obj
        # Loading can expose an incomplete tree; only completed ready imports
        # have a definitive negative result. Empty imports get one deferred
        # owner rescan rather than a persistent per-frame tree walk.
        _, ready = RuntimeClipDriver._source_state(loader)
        if ready and candidates and len(cached['scene']) <= 512:
            cached['resolved'] = True
        return None
    except (OSError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, TypeError):
        return None


class RuntimeClipDriver:
    """Cache imported timelines and change only the clip that actually changed."""

    MAX_LOADERS = 128

    def __init__(self) -> None:
        self._loaders: OrderedDict[int, dict[str, Any]] = OrderedDict()
        self._closed = False

    def close(self) -> None:
        """Stop imported animation jobs before their QML keyframes are deleted."""
        if self._closed:
            return
        self._closed = True
        for key in tuple(self._loaders):
            self._release_entry(key)

    @staticmethod
    def _stop_entry(entry) -> None:
        # A deleted animation must not prevent stopping its surviving timeline
        # or another job from the same imported scene.
        for node, property_name in [(job, 'running') for job in entry.get('jobs', ())] + [
                (timeline, 'enabled') for timeline in entry.get('timelines', ())]:
            try:
                if isValid(node):node.setProperty(property_name, False)
            except (AttributeError, RuntimeError, TypeError):
                continue

    def _retire_entry(self, entry) -> None:
        entry['retiring'] = True
        self._stop_entry(entry)
        entry.update(animations={}, jobs=[], timelines=[], defaults=[], active='',
                     active_serial='', played_once=False, scanned=False, retiring=False,
                     empty_retry_done=False)
        entry.pop('static_defaults', None)

    def _release_entry(self, key) -> bool:
        entry = self._loaders.get(key)
        if entry is None:return False
        entry['retiring'] = True
        self._stop_entry(entry)
        self._loaders.pop(key, None)
        if isValid(entry['loader']):
            for signal, callback in entry.get('hooks', ()):
                try:signal.disconnect(callback)
                except (AttributeError, RuntimeError, TypeError):pass
        return True

    def release(self, loader: QObject) -> bool:
        """End ownership while the loader's imported children still exist."""
        entry = self._loaders.get(id(loader))
        if entry is None or entry['loader'] is not loader:return False
        return self._release_entry(id(loader))

    @staticmethod
    def _source_state(loader):
        source = loader.property('source')
        source = source.toString() if isinstance(source, QUrl) else str(source or '')
        try:status = loader.property('status')
        except RuntimeError:
            # RuntimeLoader's private C++ enum has no PySide converter. QML
            # can read the same actual property as a number without guessing
            # its value or treating an unreadable Loading state as Success.
            from PySide6.QtQml import QQmlEngine, QQmlExpression
            context = QQmlEngine.contextForObject(loader)
            if context is None:raise RuntimeError('RuntimeLoader status context unavailable') from None
            expression = QQmlExpression(context, loader, 'Number(status)')
            status, undefined = expression.evaluate()
            if undefined or expression.hasError():
                raise RuntimeError('RuntimeLoader status unavailable')
        status = getattr(status, 'value', status)
        ready = True
        if status is not None:
            meta = loader.metaObject()
            enum_index = meta.indexOfEnumerator('Status')
            if enum_index >= 0:
                success, valid = meta.enumerator(enum_index).keyToValue('Success')
                ready = bool(valid and status == success)
        return (source, status), ready

    def _install_hooks(self, entry) -> None:
        loader = entry['loader'];key = id(loader)
        driver_ref = weakref.ref(self);loader_ref = weakref.ref(loader)
        def changed(*_):
            driver = driver_ref();current_loader = loader_ref()
            if driver is None or current_loader is None or driver._closed:return
            current = driver._loaders.get(key)
            if current is None or current['loader'] is not current_loader:return
            try:epoch, ready = driver._source_state(current_loader)
            except (AttributeError, RuntimeError, TypeError):
                driver._release_entry(key);return
            if epoch != current['epoch'] or not ready:
                driver._retire_entry(current)
                current['epoch'] = epoch
        def destroyed(*_):
            driver = driver_ref();current_loader = loader_ref()
            if driver is None:return
            current = driver._loaders.get(key)
            if current is not None and current['loader'] is current_loader:
                driver._release_entry(key)
        hooks = []
        for name, callback in (('sourceChanged', changed), ('statusChanged', changed), ('destroyed', destroyed)):
            signal = getattr(loader, name, None)
            if signal is not None:
                signal.connect(callback);hooks.append((signal, callback))
        entry['hooks'] = hooks

    @staticmethod
    def _finite(value: Any) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return 0.0
        return result if math.isfinite(result) else 0.0

    @staticmethod
    def _authored_defaults(loader: QObject):
        """Cache the fallback transforms that Qt omits from constant tracks.

        A rotation equal to the GLB node's default can disappear from Qt's
        imported timeline. Disabling the preceding clip leaves its final
        rotation on that node. Restore authored defaults at a clip transition
        before the new timeline applies its animated properties.
        """
        try:
            source = loader.property("source")
            path = source.toLocalFile() if isinstance(source, QUrl) else QUrl(str(source)).toLocalFile()
            document = _imported_node_document(path) if path else None
            if not document:
                return []
            properties=document['animated_paths']
            nodes = document.get("nodes", [])
            first = next((nodes[i].get("name") for i in properties if nodes[i].get("name")), "")
            if not first or imported_named_node(loader, first) is None:
                return []
            named = {node.objectName(): node for node in _rig_name_index(loader)['nodes'].values()
                     if isValid(node)}
            defaults = []
            for index, paths in properties.items():
                spec = nodes[index]
                node = named.get(spec.get("name", ""))
                if node is None or "matrix" in spec:
                    continue
                values = {}
                if "translation" in paths:
                    values["position"] = QVector3D(*spec.get("translation", (0., 0., 0.)))
                if "rotation" in paths:
                    x, y, z, w = spec.get("rotation", (0., 0., 0., 1.))
                    values["rotation"] = QQuaternion(w, x, y, z)
                if "scale" in paths:
                    values["scale"] = QVector3D(*spec.get("scale", (1., 1., 1.)))
                defaults.append((node, values))
            return defaults
        except (OSError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, TypeError):
            return []

    def _loader_entry(self, loader: QObject) -> dict[str, Any] | None:
        if self._closed or not isValid(loader):
            return None
        key = id(loader)
        entry = self._loaders.get(key)
        if entry is not None and entry.get('retiring'):return None
        try:epoch, ready = self._source_state(loader)
        except (AttributeError, RuntimeError, TypeError):
            if entry is not None:self._release_entry(key)
            return None
        if entry is not None and (entry.get('loader') is not loader or entry['epoch'] != epoch):
            self._retire_entry(entry);entry['epoch'] = epoch
        if not ready:return None
        if (entry is not None and entry.get("loader") is loader and entry.get('scanned')
                and all(isValid(job) for job in entry['jobs'])):
            self._loaders.move_to_end(key)
            return entry
        empty_retry_done=bool(entry and entry.get('empty_retry_done'))
        if entry is not None:self._retire_entry(entry)
        try:
            candidates = named_nodes(loader, '.*')
        except (AttributeError, RuntimeError, TypeError):
            return None
        animations: dict[str, QObject] = {};jobs=[];timelines=[]
        for candidate in candidates:
            try:
                if (candidate.metaObject().className() != "QQuickTimelineAnimation"
                        and not candidate.inherits("QQuickTimelineAnimation")):
                    continue
                name = str(candidate.objectName() or "").strip().casefold()
                if name:
                    animations[name] = candidate
                jobs.append(candidate)
                candidate.setProperty("running", False)
                parent = candidate.parent()
                if isinstance(parent, QObject):
                    timelines.append(parent)
                    parent.setProperty("enabled", False)
            except (AttributeError, RuntimeError, TypeError):
                continue
        paused = bool(entry and entry.get("paused"))
        hooks = entry.get('hooks') if entry else None
        entry = {"loader": loader, "animations": animations, "active": "", "active_serial":"",
                 "played_once":False, "paused":paused, 'epoch':epoch, 'scanned':True,
                 'jobs':jobs, 'timelines':timelines, 'retiring':False,
                 'empty_retry_done':empty_retry_done,
                 "defaults":self._authored_defaults(loader)}
        # Stop all imported autoplay jobs, including unnamed/unknown clips,
        # then recover only transforms actually declared by the source file.
        for node,values in entry['defaults']:
            if isValid(node):
                for property_name,value in values.items():
                    if node.property(property_name)!=value:node.setProperty(property_name,value)
        self._loaders[key] = entry
        if hooks is not None:entry['hooks'] = hooks
        else:self._install_hooks(entry)
        self._loaders.move_to_end(key)
        while len(self._loaders) > self.MAX_LOADERS:
            self._release_entry(next(iter(self._loaders)))
        self._defer_empty_scan(entry)
        return entry

    def _defer_empty_scan(self,entry):
        """A ready importer can attach its jobs after its first owner scan.

        Retry once after Qt's current handoff. Static scenes never become a
        per-frame traversal, and stale callbacks cannot reclaim retired owners.
        """
        if entry['jobs'] or entry['empty_retry_done']:return
        entry['empty_retry_done']=True
        driver_ref=weakref.ref(self);loader_ref=weakref.ref(entry['loader'])
        key=id(entry['loader']);epoch=entry['epoch']
        def rescan():
            driver=driver_ref();loader=loader_ref()
            if driver is None or driver._closed or loader is None or not isValid(loader):return
            current=driver._loaders.get(key)
            if current is not entry or current['loader'] is not loader or current['epoch']!=epoch:return
            try:actual,ready=driver._source_state(loader)
            except (AttributeError,RuntimeError,TypeError):return
            if actual!=epoch or not ready:return
            # The initial ready notification may precede the imported scene
            # children as well as its animation jobs. Refresh both snapshots.
            loader._gg_rig_names = None
            current['scanned']=False
            driver._loader_entry(loader)
        QTimer.singleShot(0,rescan)

    def set_paused(self,loader,paused):
        entry=self._loader_entry(loader)
        if entry is None:return False
        entry['paused']=bool(paused)
        active=entry['animations'].get(entry['active'])
        if active is not None:active.setProperty('paused',bool(paused))
        return True

    def _static_pose(self,entry,wanted):
        """Own GG posture on the retained articulated rig, with rest recovery.

        A real authored clip takes priority. These poses do not add timelines,
        duplicate the mesh, or edit the user's Blender scene.
        """
        poses={
            'sit':{'hips':(0,0,0),'spine':(-8,0,0),'thigh.L':(85,0,-8),'thigh.R':(85,0,8),
                   'calf.L':(-95,0,0),'calf.R':(-95,0,0),'upper_arm.L':(16,0,60),'upper_arm.R':(16,0,-60),'forearm.L':(40,0,0),'forearm.R':(40,0,0)},
            'kneel':{'hips':(0,0,0),'spine':(-5,0,0),'thigh.L':(20,0,0),'thigh.R':(20,0,0),'calf.L':(-110,0,0),'calf.R':(-110,0,0),
                     'upper_arm.L':(0,0,55),'upper_arm.R':(0,0,-55),'forearm.L':(20,0,0),'forearm.R':(20,0,0)},
            'sleep':{'hips':(-90,0,0),'spine':(0,0,0),'thigh.L':(0,0,0),'thigh.R':(0,0,0),'calf.L':(0,0,0),'calf.R':(0,0,0),
                     'upper_arm.L':(0,0,65),'upper_arm.R':(0,0,-65),'forearm.L':(10,0,0),'forearm.R':(10,0,0)}}
        pose=poses[wanted];loader=entry['loader']
        nodes={key:imported_named_node(loader,key) for key in pose}
        if any(node is None or not isValid(node) for node in nodes.values()):return False
        if entry.get('active')==wanted:return True
        old=entry['animations'].get(entry.get('active',''))
        if old is not None:
            old.setProperty('running',False)
            if isinstance(old.parent(),QObject):old.parent().setProperty('enabled',False)
        for key,(rotation,position) in entry.get('static_defaults',{}).items():
            node=imported_named_node(loader,key)
            if node is not None and isValid(node):node.setProperty('rotation',rotation);node.setProperty('position',position)
        for node,values in entry['defaults']:
            if isValid(node):
                for key,value in values.items():node.setProperty(key,value)
        if 'static_defaults' not in entry:
            entry['static_defaults']={key:(node.property('rotation'),node.property('position')) for key,node in nodes.items()}
        # Remember every posture joint before first use, including those which
        # have no original animated path. Restore them on the next transition.
        for key,node in nodes.items():
            if key not in entry['static_defaults']:entry['static_defaults'][key]=(node.property('rotation'),node.property('position'))
            rotation,position=entry['static_defaults'][key]
            node.setProperty('rotation',rotation*QQuaternion.fromEulerAngles(*pose[key]))
            if key=='hips':node.setProperty('position',position+QVector3D(0,-.42 if wanted=='sit' else -.28 if wanted=='kneel' else -.58,0))
        entry['active']=wanted;entry['active_serial']='';entry['played_once']=False
        return True

    def apply(self, loader: QObject, clip: str, cadence_hz: Any = 0.0, trigger_id: Any = "") -> bool:
        if not isinstance(loader, QObject):
            return False
        entry = self._loader_entry(loader)
        if entry is None:
            return False
        wanted = str(clip or "").strip().casefold()
        token = str(trigger_id or "")[:48]
        one_shot = wanted in {name.casefold() for name in ONE_SHOT_CLIPS}
        animations: dict[str, QObject] = entry["animations"]
        old_name = str(entry.get("active", ""))
        if wanted in ('sit','sleep','kneel') and wanted not in animations:
            return self._static_pose(entry,wanted)
        if old_name in ('sit','sleep','kneel') and old_name!=wanted:
            for key,(rotation,position) in entry.get('static_defaults',{}).items():
                node=imported_named_node(loader,key)
                if node is not None and isValid(node):node.setProperty('rotation',rotation);node.setProperty('position',position)
        if not wanted:
            old = animations.get(old_name)
            if old is not None:
                try:
                    old.setProperty("running", False)
                    parent = old.parent()
                    if isinstance(parent, QObject):
                        parent.setProperty("enabled", False)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            entry["active"] = ""
            entry["active_serial"] = ""
            entry["played_once"] = False
            return True

        target = animations.get(wanted)
        if target is None:
            return False
        retrigger = one_shot and token != str(entry.get("active_serial", ""))
        if old_name != wanted or retrigger:
            old = animations.get(old_name)
            if old is not None:
                try:
                    old.setProperty("running", False)
                    parent = old.parent()
                    if isinstance(parent, QObject):
                        parent.setProperty("enabled", False)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            entry["active"] = wanted
            entry["active_serial"] = token
            entry["played_once"] = False
            for node, values in entry["defaults"]:
                if isValid(node):
                    for property_name, value in values.items():
                        node.setProperty(property_name, value)

        cadence = self._finite(cadence_hz)
        if cadence > 0.0 and not one_shot:
            duration = max(120, min(4000, round(1000.0 / cadence)))
            try:
                current = int(target.property("duration") or 0)
                if abs(current - duration) >= 24:
                    target.setProperty("duration", duration)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        try:
            if one_shot and bool(entry.get("played_once")):
                return True
            target.setProperty("loops", 1 if one_shot else -1)
            parent = target.parent()
            if isinstance(parent, QObject):
                parent.setProperty("enabled", True)
            if not bool(target.property("running")):
                target.setProperty("running", True)
            if one_shot:
                entry["played_once"] = True
            target.setProperty('paused',entry['paused'])
            return True
        except (AttributeError, RuntimeError, TypeError):
            return False
