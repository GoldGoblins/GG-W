"""Versioned C ABI for C++ world calculations; Qt owns all scene objects.

No downloads/builds occur at runtime. Missing or stale builds select the Python
reference path; GG_GAME_WORLD_NATIVE=required makes that an explicit error.
"""
from __future__ import annotations
from backend.platform_support import native_directory, native_library_name
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import struct
import threading
import weakref

PROJECT=Path(__file__).resolve().parents[1]
MAX_ROWS=65536
class View(C.Structure):
    _fields_=[('origin',C.c_double*3),('forward',C.c_double*3),('right',C.c_double*3),('up',C.c_double*3),('tangent',C.c_double),('aspect',C.c_double),('far_clip',C.c_double)]
class Box(C.Structure):
    _fields_=[('low',C.c_double*3),('high',C.c_double*3)]
class Sphere(C.Structure):
    _fields_=[('center',C.c_double*3),('radius',C.c_double)]
class Window(C.Structure):
    _fields_=[('x',C.c_int64),('z',C.c_int64),('inner',C.c_int32),('outer',C.c_int32)]
class Cell(C.Structure):
    _fields_=[('x',C.c_int64),('z',C.c_int64)]
class Stamp(C.Structure):
    _fields_=[('id',C.c_uint64),('x',C.c_double),('z',C.c_double),('time',C.c_double),('stamped',C.c_uint8)]

def _digest():
    d=hashlib.sha256()
    for name in ('gg_world.h','gg_world.cpp'):
        d.update(name.encode());d.update((PROJECT/'native/world'/name).read_bytes())
    return d.hexdigest()

_lib=None;_reason='NOT_LOADED';_attempted=False
_load_lock=threading.RLock()
def _load_unlocked():
    global _lib,_reason,_attempted
    mode=os.environ.get('GG_GAME_WORLD_NATIVE','auto')
    if mode=='0':return None
    if not _attempted:
        _attempted=True
        try:
            if os.name!='nt' and (platform.system()!='Linux' or platform.machine()!='x86_64'):raise ValueError('unsupported native platform')
            root=native_directory(PROJECT);path=root/native_library_name('gg_world')
            manifest=json.loads((root/'build.json').read_text())
            if manifest.get('abi')!=1 or manifest.get('source_sha256')!=_digest():raise ValueError('native source/build mismatch')
            if manifest.get('binary_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('native binary/build mismatch')
            lib=C.CDLL(str(path))
            definitions={
                'ggw_abi_version':([],C.c_uint32),
                'ggw_window':([C.c_double]*4+[C.POINTER(Window)],C.c_int),
                'ggw_grid_candidates':([C.c_double]*3+[C.c_uint32,C.POINTER(Cell),C.c_uint32],C.c_int),
                'ggw_cull_spheres':([C.POINTER(View),C.POINTER(Sphere),C.c_uint32,C.POINTER(C.c_uint8)],C.c_int),
                'ggw_index_create':([C.POINTER(Box),C.c_uint32],C.c_void_p),
                'ggw_index_destroy':([C.c_void_p],None),
                'ggw_index_select':([C.c_void_p,C.POINTER(View),C.c_double,C.POINTER(C.c_uint32),C.POINTER(C.c_double),C.c_uint32],C.c_int),
                'ggw_index_select_subset':([C.c_void_p,C.POINTER(View),C.c_double,C.POINTER(C.c_uint32),C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_double),C.c_uint32],C.c_int),
                'ggw_cache_create':([C.c_uint32],C.c_void_p),
                'ggw_cache_destroy':([C.c_void_p],None),
                'ggw_cache_put':([C.c_void_p,C.c_uint64,C.POINTER(C.c_uint64)],C.c_int),
                'ggw_cache_touch':([C.c_void_p,C.c_uint64],C.c_int),
                'ggw_cache_touch_many':([C.c_void_p,C.POINTER(C.c_uint64),C.c_uint32],C.c_int),
                'ggw_cache_move':([C.c_void_p,C.c_uint64,C.c_uint8],C.c_int),
                'ggw_cache_erase':([C.c_void_p,C.c_uint64],C.c_int),
                'ggw_cache_clear':([C.c_void_p],None),
                'ggw_cache_scope':([C.c_void_p]+[C.c_double]*4+[C.POINTER(C.c_uint64),C.c_uint32],C.c_int),
                'ggw_cache_stamps':([C.c_void_p,C.POINTER(Stamp),C.c_uint32],C.c_int),
            }
            for name,(args,result) in definitions.items():
                function=getattr(lib,name);function.argtypes=args;function.restype=result
            if lib.ggw_abi_version()!=1:raise ValueError('unsupported native ABI')
            _lib=lib;_reason='READY'
        except (OSError,ValueError,KeyError,AttributeError) as exc:
            _reason=type(exc).__name__+': '+str(exc)[:160]
    if _lib is None and mode=='required':raise RuntimeError('native world core required: '+_reason)
    return _lib

def library():
    # Simulation and Qt may request the first load at the same time. Neither
    # should observe a temporary missing backend while the other loads it.
    if os.environ.get('GG_GAME_WORLD_NATIVE','auto')=='0':return None
    with _load_lock:return _load_unlocked()

def status():
    lib=library()
    return {'backend':'CPP' if lib else 'PYTHON','abi':1 if lib else None,
            'reason':'DISABLED' if os.environ.get('GG_GAME_WORLD_NATIVE')=='0' else _reason}

def _check(count):
    if count<0:raise ValueError('native world input or output capacity rejected')
    return count

def view_buffer(view):
    origin,forward,right,up,tangent,aspect,far=view
    return View(*( (C.c_double*3)(*axis) for axis in (origin,forward,right,up)),tangent,aspect,far)

def window_at(x,z,far,cell):
    lib=library()
    if lib is None:return None
    out=Window();_check(lib.ggw_window(x,z,far,cell,C.byref(out)))
    return out.x,out.z,out.inner,out.outer

def prioritized_cells(x,z,cell_m,radius=3):
    if not isinstance(radius,int) or not 0<=radius<=32:raise ValueError('grid radius out of bounds')
    lib=library()
    if lib is None:
        cx,cz=math.floor(x/cell_m),math.floor(z/cell_m)
        rows=[(cx+dx,cz+dz) for dx in range(-radius,radius+1) for dz in range(-radius,radius+1)]
        rows.sort(key=lambda c:((c[0]+.5)*cell_m-x)**2+((c[1]+.5)*cell_m-z)**2)
        return rows
    count=(radius*2+1)**2;out=(Cell*count)()
    _check(lib.ggw_grid_candidates(x,z,cell_m,radius,out,count))
    coordinates=memoryview(out).cast('B').cast('q')
    return list(zip(coordinates[::2],coordinates[1::2]))

def sphere_visible(view,center,radius):
    origin,forward,right,up,tangent,aspect,far=view
    delta=tuple(a-b for a,b in zip(center,origin));depth=sum(a*b for a,b in zip(delta,forward))
    tx=tangent*aspect
    return (depth>=-radius and depth<=far+radius
            and abs(sum(a*b for a,b in zip(delta,right)))<=depth*tx+radius*math.sqrt(1+tx*tx)
            and abs(sum(a*b for a,b in zip(delta,up)))<=depth*tangent+radius*math.sqrt(1+tangent*tangent))

def cull_spheres(view,centers,radius=1.5):
    if len(centers)>MAX_ROWS:raise ValueError('sphere count out of bounds')
    if view is None:return [True]*len(centers)
    lib=library()
    if lib is None:return [sphere_visible(view,p,radius) for p in centers]
    # One owned contiguous buffer avoids allocating two ctypes wrappers per
    # actor. Its 4-double stride is the checked GgwSphere ABI on x86_64.
    data=bytearray(32*len(centers))
    for i,center in enumerate(centers):struct.pack_into('=4d',data,i*32,*center,radius)
    spheres=(Sphere*len(centers)).from_buffer(data)
    visible=(C.c_uint8*len(centers))();v=view_buffer(view)
    _check(lib.ggw_cull_spheres(C.byref(v),spheres,len(spheres),visible))
    return [bool(v) for v in visible]

class SectorIndex:
    """Immutable bounds copied once; retain catalog insertion order in results."""
    def __init__(self,sectors):
        self.keys=tuple(sectors);self.lib=library();self.native=bool(self.lib)
        self.bounds=tuple((tuple(s['min']),tuple(s['max'])) for s in sectors.values())
        self.positions={key:i for i,key in enumerate(self.keys)}
        if len(self.keys)>MAX_ROWS:raise ValueError('sector count out of bounds')
        self._finalizer=None
        if self.native:
            boxes=(Box*len(self.keys))(*(Box((C.c_double*3)(*lo),(C.c_double*3)(*hi)) for lo,hi in self.bounds))
            self.handle=self.lib.ggw_index_create(boxes,len(boxes))
            if not self.handle:raise ValueError('invalid sector bounds')
            self._finalizer=weakref.finalize(self,self.lib.ggw_index_destroy,self.handle)
            self.rows=(C.c_uint32*len(boxes))();self.distances=(C.c_double*len(boxes))()

    def select(self,view,padding=256,allowed=None):
        if self._finalizer is not None and not self._finalizer.alive:raise RuntimeError('sector index closed')
        if self.native:
            v=view_buffer(view)
            if allowed is None:
                count=_check(self.lib.ggw_index_select(self.handle,C.byref(v),padding,self.rows,self.distances,len(self.keys)))
            else:
                candidates=(C.c_uint32*len(allowed))(*(self.positions[key] for key in allowed))
                count=_check(self.lib.ggw_index_select_subset(self.handle,C.byref(v),padding,candidates,len(candidates),self.rows,self.distances,len(self.keys)))
            return [(self.keys[self.rows[i]],self.distances[i]) for i in range(count)]
        origin,_,_,_,tangent,aspect,far=view
        reach=far*math.sqrt(1+tangent*tangent*(1+aspect*aspect))+padding
        result=[]
        for key in self.keys if allowed is None else allowed:
            lo,hi=self.bounds[self.positions[key]]
            distance=math.sqrt(sum(max(a-o,0,o-b)**2 for o,a,b in zip(origin,lo,hi)))
            if distance<=reach:result.append((key,distance))
        return result

    def close(self):
        if self._finalizer:self._finalizer()

class Residency:
    def __init__(self,capacity):
        if not 1<=capacity<=MAX_ROWS:raise ValueError('cache capacity out of bounds')
        self.lib=library()
        if self.lib is None:raise RuntimeError('native residency requires the built core')
        self.handle=self.lib.ggw_cache_create(capacity)
        if not self.handle:raise MemoryError('native residency allocation failed')
        self._finalizer=weakref.finalize(self,self.lib.ggw_cache_destroy,self.handle)
        self.expired=(C.c_uint64*capacity)();self.stamp_rows=(Stamp*capacity)();self.capacity=capacity

    def _alive(self):
        if not self._finalizer.alive:raise RuntimeError('native residency closed')

    def put(self,identity):
        self._alive();evicted=C.c_uint64();_check(self.lib.ggw_cache_put(self.handle,identity,C.byref(evicted)));return evicted.value
    def touch(self,identity):
        self._alive();_check(self.lib.ggw_cache_touch(self.handle,identity))
    def touch_many(self,identities):
        self._alive()
        if len(identities)>MAX_ROWS:raise ValueError('too many residency touches')
        rows=(C.c_uint64*len(identities))(*identities)
        _check(self.lib.ggw_cache_touch_many(self.handle,rows,len(rows)))
    def move(self,identity,last):
        self._alive();_check(self.lib.ggw_cache_move(self.handle,identity,bool(last)))
    def erase(self,identity):
        self._alive();_check(self.lib.ggw_cache_erase(self.handle,identity))
    def clear(self):
        self._alive();self.lib.ggw_cache_clear(self.handle)
    def scope(self,focus,radius,now):
        self._alive();n=_check(self.lib.ggw_cache_scope(self.handle,*focus,radius,now,self.expired,self.capacity))
        return list(self.expired[:n])
    def stamps(self):
        self._alive();n=_check(self.lib.ggw_cache_stamps(self.handle,self.stamp_rows,self.capacity))
        return {s.id:((s.x,s.z),s.time) if s.stamped else None for s in self.stamp_rows[:n]}
    def close(self):self._finalizer()
