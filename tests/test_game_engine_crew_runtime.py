"""Import all promoted crew skins and play clips using the real Qt bridge."""
import os, sys, json
from functools import lru_cache
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from PySide6.QtCore import QByteArray, QObject, QUrl
from PySide6.QtGui import QGuiApplication, QMatrix4x4, QQuaternion, QVector3D
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from backend.game_client_host import GameClientHost
from backend.game_engine_assets import BLENDER_CHARACTER_SOURCES
from backend.game_engine_animation import CLIP_FRAMES
from tools.blender.compile_gg_crew_action_variants import read_glb


@lru_cache(maxsize=16)
def animation_document(path):
    return read_glb(path)


def expected_socket(path, clip, name):
    """Forward kinematics of the serialized first pose, independent of Qt."""
    import struct
    document, binary = animation_document(path)
    nodes = document['nodes']
    values = {i: dict(node) for i, node in enumerate(nodes)}
    animation = next(a for a in document['animations'] if a['name'] == clip)
    for channel in animation['channels']:
        target = channel['target']; accessor = document['accessors'][animation['samplers'][channel['sampler']]['output']]
        view = document['bufferViews'][accessor['bufferView']]
        size = 4 if target['path'] == 'rotation' else 3
        values[target['node']][target['path']] = struct.unpack_from('<' + 'f' * size, binary,
            view.get('byteOffset',0)+accessor.get('byteOffset',0))
    parents = {child: i for i, node in enumerate(nodes) for child in node.get('children', [])}
    index = next(i for i,node in enumerate(nodes) if node.get('name') == name)
    chain = []
    while True:
        chain.append(index)
        if index not in parents: break
        index = parents[index]
    matrix = QMatrix4x4()
    for index in reversed(chain):
        spec = values[index]
        matrix.translate(QVector3D(*spec.get('translation',(0,0,0))))
        x,y,z,w = spec.get('rotation',(0,0,0,1))
        matrix.rotate(QQuaternion(w,x,y,z))
        matrix.scale(QVector3D(*spec.get('scale',(1,1,1))))
    accessor = document['accessors'][animation['samplers'][0]['input']]
    view = document['bufferViews'][accessor['bufferView']]
    first_time = struct.unpack_from('<f',binary,view.get('byteOffset',0)+accessor.get('byteOffset',0))[0]
    return matrix.map(QVector3D()), first_time * 1000.

def main():
    app=QGuiApplication([]);engine=QQmlEngine();host=GameClientHost()
    window=QQuickWindow();window.resize(320,240);window.show()
    roots=[]
    sources=dict(BLENDER_CHARACTER_SOURCES)
    for name,variant in (("brinekip",1),("mossjaw",18),("reefrunner",35)):
        sources[f'{name}-variant-{variant}']=PROJECT/'qml/assets/authored/variants/characters'/f'gg-crew-{name}-articulated-v{variant}.glb'
    for name in ('brinekip','mossjaw'):
        sources[f'{name}-compact']=PROJECT/'qml/assets/authored/characters'/f'gg-crew-{name}-compact.glb'
    for asset_id,path in sources.items():
        component=QQmlComponent(engine)
        qml='''import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils
Item { width: 320; height: 240
View3D { anchors.fill: parent
RuntimeLoader { objectName: "crewProbe"; source: SOURCE }
} }'''.replace('SOURCE',json.dumps(QUrl.fromLocalFile(str(path)).toString()))
        component.setData(QByteArray(qml.encode()),QUrl.fromLocalFile(str(PROJECT/'crew-runtime-probe.qml')))
        root=component.create();assert root is not None,[e.toString() for e in component.errors()]
        roots.append(root);root.setParentItem(window.contentItem())
        loader=root.findChild(QObject,'crewProbe')
        for _ in range(300):app.processEvents()
        assert loader.property('errorString')=='Success!',(asset_id,loader.property('errorString'))
        animations=[o for o in loader.findChildren(QObject) if o.metaObject().className()=='QQuickTimelineAnimation']
        assert {o.objectName().casefold() for o in animations}=={name.casefold() for name in CLIP_FRAMES},(asset_id,len(animations))
        palms = {name: host.gameEngineFindNamedNode(loader,name) for name in ('SOCKET_MAIN_HAND','SOCKET_OFF_HAND')}
        assert all(palms.values()), (asset_id, 'missing real palm sockets')
        for clip in CLIP_FRAMES:
            assert host.gameEngineRuntimeClip(loader,clip)
            active=[o.objectName().casefold() for o in animations if o.property('running')]
            assert active==[clip.casefold()],(asset_id,clip,active)
            # Qt omits constant channels that equal the imported defaults.
            # Verify that a preceding attack cannot leave its wrist rotation
            # behind when another clip starts without a rotation key group.
            playing = next(o for o in animations if o.objectName().casefold() == clip.casefold())
            playing.setProperty('running',False)
            timeline = playing.parent()
            timeline.setProperty('enabled',True)
            _, first_time = expected_socket(path,clip,'SOCKET_MAIN_HAND')
            timeline.setProperty('currentFrame',first_time)
            app.processEvents()
            inverse, valid = loader.property('sceneTransform').inverted()
            assert valid
            for name, palm in palms.items():
                actual = inverse.map(palm.property('scenePosition'))
                expected, _ = expected_socket(path,clip,name)
                assert (actual-expected).length() < .002, (asset_id,clip,name,actual,expected)
            if clip=='Idle':
                document,_=animation_document(path)
                for index in document['skins'][0]['joints']:
                    name=document['nodes'][index]['name']
                    joint=host.gameEngineFindNamedNode(loader,name)
                    assert joint is not None,(asset_id,'missing native joint',name)
                    actual=inverse.map(joint.property('scenePosition'))
                    expected,_=expected_socket(path,clip,name)
                    assert (actual-expected).length()<.002,(asset_id,'misidentified joint',name,actual,expected)
        # The compact stream can resend a completed action. The same event
        # must hold its last pose; a new event must replay the same clip.
        assert host.gameEngineRuntimeClip(loader,'OneHandSlash',0,'shot-1')
        slash=next(o for o in animations if o.objectName().casefold()=='onehandslash')
        assert slash.property('loops')==1
        slash.setProperty('running',False)
        assert host.gameEngineRuntimeClip(loader,'OneHandSlash',0,'shot-1')
        assert not slash.property('running')
        assert host.gameEngineRuntimeClip(loader,'OneHandSlash',0,'shot-2')
        assert slash.property('running')
        assert host.gameEngineRuntimeClip(loader,'Idle')
        assert not slash.property('running')
        # Imported Qt names must refer to the correct hand, not a similar
        # branch in the skeleton. Compare both palms with GLB forward kinematics.
        idle = next(o for o in animations if o.objectName().casefold() == 'idle')
        idle.setProperty('running',False)
        timeline = idle.parent()
        timeline.setProperty('enabled',True)
        _, first_time = expected_socket(path,'Idle','SOCKET_MAIN_HAND')
        timeline.setProperty('currentFrame',first_time)
        app.processEvents()
        inverse, valid = loader.property('sceneTransform').inverted()
        assert valid
        for name, palm in palms.items():
            actual = inverse.map(palm.property('scenePosition'))
            expected, _ = expected_socket(path,'Idle',name)
            assert (actual-expected).length() < .002, (asset_id,name,actual,expected)
        before = palms['SOCKET_MAIN_HAND'].property('scenePosition')
        assert host.gameEngineRuntimeClip(loader,'OneHandSlash',0,'grip-motion')
        slash.setProperty('running',False)
        timeline = slash.parent()
        timeline.setProperty('enabled',True)
        timeline.setProperty('currentFrame',timeline.property('endFrame')*.4)
        app.processEvents()
        assert (palms['SOCKET_MAIN_HAND'].property('scenePosition')-before).length() > .05, (asset_id,'palm did not follow the action')
        if asset_id=='gg-codex-original':
            # Streaming can retain a loader while changing its crew source.
            # Animation handles from its previous scene must be refreshed.
            loader.setProperty('source',QUrl.fromLocalFile(str(BLENDER_CHARACTER_SOURCES['gg-codex-riftclaw'])))
            for _ in range(300):app.processEvents()
            assert loader.property('errorString')=='Success!'
            assert host.gameEngineRuntimeClip(loader,'WandCast',0,'new-source')
            new_animations=[o for o in loader.findChildren(QObject) if o.metaObject().className()=='QQuickTimelineAnimation']
            assert [o.objectName().casefold() for o in new_animations if o.property('running')]==['wandcast']
        root.setVisible(False)
    window.close()
    print(f'GAME_ENGINE_CREW_RUNTIME_TEST=PASS (9 skins + 3 silhouette variants + 2 compact skins, {len(CLIP_FRAMES)} clips, one-shot event replay, real Qt clip switching)')
    return 0
if __name__=='__main__':raise SystemExit(main())
