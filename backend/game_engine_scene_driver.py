"""Retained Qt scene handles: publish transforms without rebinding mesh metadata.

Like GgEngine's retained scene, static identity and live transforms have separate
update paths. This adapter runs on the Qt thread, never the simulation thread.
"""
from __future__ import annotations
import math
import json
from PySide6.QtCore import QObject
from PySide6.QtGui import QVector3D, QQuaternion
from shiboken6 import isValid
from backend.game_engine_life import RENDER_RADIUS_M
from backend.game_engine_native_world import cull_spheres, sphere_visible, status as native_status

class SceneDriver:
    def __init__(self):
        self.nodes={};self.transforms={};self.view=None;self.rigs={};self.out_since={};self.visible={};self.clock=0;self.paused=False
        self.culling_backend=native_status()['backend'];self.culling_batches=0;self.culling_count=0

    def set_view(self,raw):
        try:
            v=json.loads(raw)
            if not all(math.isfinite(float(v[k])) for k in ('x','y','z','heading','pitch','fov','aspect','far')):return False
            if not 1 <= float(v['fov']) <= 170 or not 0<float(v['aspect'])<=100 or not 0<float(v['far'])<=1e12:return False
            if any(abs(float(v[k]))>1e12 for k in ('x','y','z')):return False
            heading=math.radians(float(v['heading']));pitch=math.radians(float(v['pitch']))
            self.view=(tuple(float(v[k]) for k in ('x','y','z')),
                (math.sin(heading)*math.cos(pitch),math.sin(pitch),math.cos(heading)*math.cos(pitch)),
                (-math.cos(heading),0,math.sin(heading)),
                (-math.sin(heading)*math.sin(pitch),math.cos(pitch),-math.cos(heading)*math.sin(pitch)),
                math.tan(math.radians(float(v['fov']))*.5),max(.2,float(v['aspect'])),float(v['far']))
            return True
        except (ValueError,KeyError,TypeError,OverflowError):return False

    def register_rig(self,loader,identity,driver):
        self.rigs[identity]=(loader,driver)
        def forget():
            if self.rigs.get(identity,(None,))[0] is loader:self.rigs.pop(identity,None)
        loader.destroyed.connect(forget)
        driver.set_paused(loader,self.paused or not self.visible.get(identity,True))
        return True

    def in_view(self,x,y,z,radius=1.5):
        if self.view is None:return True
        return sphere_visible(self.view,(x,y+.9,z),radius)

    def register(self,node,identity):
        if not isinstance(node,QObject) or not identity:return False
        self.nodes[identity]=node;self.transforms.pop(identity,None)
        def forget():
            if self.nodes.get(identity) is node:
                self.nodes.pop(identity,None);self.transforms.pop(identity,None)
                self.visible.pop(identity,None);self.out_since.pop(identity,None)
        node.destroyed.connect(forget)
        return True

    def update(self,snapshot):
        if not isinstance(snapshot,dict):return
        if snapshot.get('state') in ('RUNNING','PAUSED','STOPPED','READY'):
            self.paused=snapshot['state']!='RUNNING'
        rows=snapshot.get('render',{}).get('entities',[])
        radius=1_000_000.
        now=float(snapshot.get('player',{}).get('time_s',0))
        if now < self.clock:self.out_since.clear()
        self.clock=now
        # Explicitly registered physics nodes consume native transforms on
        # the Qt thread. Their namespace cannot overwrite gameplay bindings.
        physics_nodes=set()
        for body in snapshot.get('rigid_physics',{}).get('bodies',[]):
            identity=body.get('scene_node','')
            if not identity.startswith('physics:'):continue
            physics_nodes.add(identity)
            node=self.nodes.get(identity)
            if node is None or not isValid(node):continue
            position=body.get('position',[]);rotation=body.get('rotation',[])
            if len(position)!=3 or len(rotation)!=4:continue
            if not all(type(x) in (int,float) and math.isfinite(x) for x in (*position,*rotation)):continue
            node.setProperty('position',QVector3D(*position))
            node.setProperty('rotation',QQuaternion(rotation[3],*rotation[:3]))
            node.setProperty('nativeVisible',True)
        if 'rigid_physics' in snapshot:
            for identity,node in self.nodes.items():
                if identity.startswith('physics:') and identity not in physics_nodes and isValid(node):
                    node.setProperty('nativeVisible',False)
        prepared=[];centers=[]
        for row in rows:
            identity=row.get('id','');node=self.nodes.get(identity)
            if node is None or not isValid(node):continue
            x=float(row.get('x',0));y=float(row.get('y',0));z=float(row.get('z',0))
            radial=radius+y
            curved=y-(x*x+z*z)/(math.sqrt(max(1,radial*radial-x*x-z*z))+radial)
            transform=(x,curved,z,math.degrees(float(row.get('yaw',0))),float(row.get('pitch',0)),float(row.get('roll',0)))
            old=self.transforms.get(identity)
            if old is None or old[:3]!=transform[:3]:node.setProperty('position',QVector3D(*transform[:3]))
            if old is None or old[3:]!=transform[3:]:node.setProperty('eulerRotation',QVector3D(transform[4],transform[3],transform[5]))
            self.transforms[identity]=transform
            prepared.append((row,node,identity,x,curved,z))
            if row.get('kind') in {'NPC','ACTOR'}:centers.append((x,curved+.9,z))
        flags=iter(cull_spheres(self.view,centers))
        self.culling_batches+=bool(centers);self.culling_count=len(centers)
        for row,node,identity,x,curved,z in prepared:
            in_frustum=next(flags) if row.get('kind') in {'NPC','ACTOR'} else True
            if row.get('kind') in {'PLAYER','NPC','ACTOR'} or identity in self.visible:
                nearby=(self.view is None or sum((a-b)**2 for a,b in zip((x,curved,z),self.view[0]))<=RENDER_RADIUS_M**2)
                shown=row.get('kind') not in {'NPC','ACTOR'} or (not row.get('hidden') and nearby and in_frustum)
                if shown:self.out_since.pop(identity,None)
                else:self.out_since.setdefault(identity,now)
                # Explicitly unloaded proxies have no sampled ground height.
                # Hide them immediately; the frustum grace period would show
                # their placeholder height for half a second on range exit.
                shown=shown or (not row.get('hidden') and now-self.out_since.get(identity,now)<.5)
                if self.visible.get(identity)!=shown:
                    self.visible[identity]=shown;node.setProperty('nativeVisible',shown)
                loader,driver=self.rigs.get(identity,(None,None))
                if loader is not None and isValid(loader):driver.set_paused(loader,self.paused or not shown)
