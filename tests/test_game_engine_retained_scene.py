"""Retained scene lifetime, instance ABI and metadata/transform separation."""
import copy,json,math,os,random,struct,sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QCoreApplication,QEvent
from PySide6.QtGui import QGuiApplication,QColor,QVector3D,QVector4D
from PySide6.QtQuick3D import QQuick3DInstancing
from backend.game_engine_ecology_render import FloraInstances,instance_bytes
from backend.game_engine_render_transport import RenderTransport
from backend.game_engine_scene_driver import SceneDriver

def main():
    app=QGuiApplication([]);rng=random.Random(617)
    for _ in range(160):
        row={k:rng.uniform(-1000,1000) for k in ('x','y','z')}
        row.update({k:rng.uniform(-180,180) for k in ('pitch','yaw','roll')})
        row.update(scale=rng.uniform(.01,12),tint=rng.random(),id='probe')
        tint=row['tint'];qt=QQuick3DInstancing.calculateTableEntry(
            QVector3D(row['x'],row['y'],row['z']),QVector3D(row['scale'],row['scale'],row['scale']),
            QVector3D(row['pitch'],row['yaw'],row['roll']),QColor.fromRgbF(tint,tint,tint,1),QVector4D())
        expected=[v for name in ('row0','row1','row2','color','instanceData') for v in getattr(qt,name).toTuple()]
        actual=struct.unpack('<20f',instance_bytes(row))
        assert all(abs(a-b)<max(.0002,abs(b)*.000003) for a,b in zip(actual,expected)),(actual,expected)
    table=FloraInstances();table.replace([row],1);before=bytes(table.getInstanceBuffer()[0])
    table.replace([{**row,'tint':0}],2)
    assert bytes(table.getInstanceBuffer()[0])!=before and table.identities==('probe',)
    table.replace([],3);assert table.getInstanceBuffer()[1]==0 and table.identities==()

    transport=RenderTransport()
    row={'id':'e-0001','kind':'NPC','x':1,'y':2,'z':3,'asset':{'source':'crew.glb','clip':'Walk'}}
    frame={'schema':'gg.game-engine.render-snapshot.v1','render':{'entities':[row]}}
    original=copy.deepcopy(frame)
    assert transport.prepare(frame)['render']['entities_delta']==[row] and frame==original
    row['x']=999
    assert transport.prepare(frame)['render']['entities_delta']==[]
    row['asset']['clip']='Idle'
    assert len(transport.prepare(frame)['render']['entities_delta'])==1
    frame['render']['entities']=[]
    assert transport.prepare(frame)['render']['entity_ids']==[]
    full={'render':{'entities':[row]}}
    assert transport.prepare(full) is full
    frame['render']['entities']=[row]
    assert len(transport.prepare(frame)['render']['entities_delta'])==1
    frame['render']['presentation']={'mode':'DOS_2D'}
    assert transport.prepare(frame) is frame

    scene=SceneDriver();node=QObject();scene.register(node,'npc')
    camera=dict(x=0,y=1,z=0,heading=0,pitch=0,fov=45,aspect=1.6,far=100)
    assert scene.set_view(json.dumps(camera))
    assert scene.in_view(0,0,10) and not scene.in_view(0,0,-10)
    assert not scene.set_view(json.dumps({**camera,'fov':0}))
    assert not scene.set_view(json.dumps({**camera,'x':float('nan')}))
    class ClipProbe:
        def __init__(self):self.paused=None
        def set_paused(self,loader,paused):self.paused=paused
    clip=ClipProbe();loader=QObject();scene.register_rig(loader,'npc',clip)
    def update(x,z,time,kind='NPC'):
        scene.update({'player':{'time_s':time},'render':{'entities':[dict(id='npc',kind=kind,x=x,y=2,z=z,yaw=.5)]}})
    update(0,10,0);assert node.property('nativeVisible') is True and not clip.paused
    update(0,-10,1);assert node.property('nativeVisible') is True
    update(0,-10,1.51);assert node.property('nativeVisible') is False and clip.paused
    update(0,10,1.52);assert node.property('nativeVisible') is True and not clip.paused
    assert scene.set_view(json.dumps({**camera,'far':1000}))
    assert scene.in_view(0,2,350)
    update(0,350,2);update(0,350,2.51)
    assert node.property('nativeVisible') is False and clip.paused
    update(0,10,2.52);assert node.property('nativeVisible') is True and not clip.paused
    scene.update({'player':{'time_s':2.53},'render':{'entities':[dict(
        id='npc',kind='ACTOR',x=0,y=0,z=10,yaw=.5,hidden=True)]}})
    assert node.property('nativeVisible') is False and clip.paused,'unloaded actor showed its placeholder height'
    update(0,10,2.54);assert node.property('nativeVisible') is True and not clip.paused
    # A visible retained rig must freeze when physics pauses; culling is not
    # the only reason to pause its imported animation job.
    visible_row=dict(id='npc',kind='NPC',x=0,y=2,z=10,yaw=.5)
    scene.update({'state':'PAUSED','player':{'time_s':2.54},'render':{'entities':[visible_row]}})
    assert node.property('nativeVisible') is True and clip.paused
    scene.update({'state':'RUNNING','player':{'time_s':2.55},'render':{'entities':[visible_row]}})
    assert node.property('nativeVisible') is True and not clip.paused
    update(200,50,2,'PLAYER');assert node.property('nativeVisible') is True
    position=node.property('position');assert abs(position.x()-200)<.001
    assert 1.9<position.y()<2 and abs(node.property('eulerRotation').y()-math.degrees(.5))<.001
    node.deleteLater();loader.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    assert 'npc' not in scene.nodes and 'npc' not in scene.rigs
    print('GAME_ENGINE_RETAINED_SCENE_TEST=PASS (Qt instance parity, tint/removal, retained metadata, real transforms, camera bounds, parked rig lifetime)')

if __name__=='__main__':main()
