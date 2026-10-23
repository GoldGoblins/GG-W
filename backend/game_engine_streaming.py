"""GgEngine-derived residency primitives adapted to our unbounded local grid.

Algorithm sources: samwhosung/engine, terrain_stream/window.rs and
engine-formats/src/spatial_cache.rs (snapshot in docs/world-scale-review-
2026-10-02/reference-code/engine). Copyright (c) 2026 Sam, MIT licensed;
license preserved in backend/licenses/engine-MIT.txt.

Differences: meter-space cells, negative coordinates, no WoW tile-grid clamp,
and an explicit LRU memory cap overriding the grace interval when full.
"""
from collections import OrderedDict
from dataclasses import dataclass
import math
from backend import game_engine_native_world as native_world

MIN_DWELL_S = 30.0


@dataclass(frozen=True)
class StreamWindow:
    x: int
    z: int
    inner: int
    outer: int

    @classmethod
    def at(cls, x: float, z: float, farclip: float, cell_m: float):
        if not all(math.isfinite(v) and abs(v)<=1e12 for v in (x,z,farclip,cell_m)) or cell_m<1e-6:
            raise ValueError('finite streaming coordinates and positive cell size required')
        result = native_world.window_at(x,z,farclip,cell_m)
        if result is not None:
            return cls(*result)
        inner = 1 + int(max(0, farclip) / cell_m)
        if inner>4096 or max(abs(x/cell_m),abs(z/cell_m))>1e15:
            raise ValueError('streaming window out of bounds')
        return cls(math.floor(x/cell_m), math.floor(z/cell_m), inner, max(inner+2, 8))

    def wanted(self):
        if (2*self.outer+1)**2>native_world.MAX_ROWS:
            raise ValueError('streaming enumeration exceeds cell budget')
        return [(self.x+dx, self.z+dz) for dz in range(-self.outer, self.outer+1)
                for dx in range(-self.outer, self.outer+1)]

    def keeps(self, cell):
        return max(abs(cell[0]-self.x), abs(cell[1]-self.z)) <= self.outer+1


class SpatialResidencyCache(OrderedDict):
    """Python values with C++ residency/LRU metadata, or the reference backend.

    Mapping reads do not refresh residency; use fetch for a counted use.
    The owner serializes operations, as with the original OrderedDict cache.
    """
    def __init__(self, capacity: int, *, native=None):
        super().__init__()
        self.capacity = int(capacity)
        if not 1<=self.capacity<=native_world.MAX_ROWS:
            raise ValueError('cache capacity out of bounds')
        self._native = native_world.Residency(self.capacity) if native is not False and native_world.library() else None
        self._stamps = {}
        self._ids = {}; self._keys = {}; self._next_id = 1

    @property
    def backend(self):
        return 'CPP' if self._native else 'PYTHON'

    @property
    def stamps(self):
        if self._native:
            return {self._keys[i]:s for i,s in self._native.stamps().items()}
        return self._stamps

    def clear(self):
        super().clear()
        self._stamps.clear();self._ids.clear();self._keys.clear()
        if self._native:self._native.clear()

    def put(self, key, value):
        if self._native:
            identity=self._ids.get(key)
            if identity is None:
                identity=self._next_id;self._next_id+=1
            evicted=self._native.put(identity)
            self._ids[key]=identity;self._keys[identity]=key
            if evicted:
                old=self._keys.pop(evicted);self._ids.pop(old)
                OrderedDict.__delitem__(self,old)
        else:
            self._stamps[key]=None
        OrderedDict.__setitem__(self,key,value)
        OrderedDict.move_to_end(self,key)
        while len(self) > self.capacity:
            self.popitem(last=False)

    def __setitem__(self,key,value):
        self.put(key,value)

    def __delitem__(self,key):
        OrderedDict.__delitem__(self,key)
        if self._native:
            identity=self._ids.pop(key);self._native.erase(identity);self._keys.pop(identity)
        else:self._stamps.pop(key,None)

    def popitem(self,last=True):
        if not self:raise KeyError('dictionary is empty')
        key=next(reversed(self)) if last else next(iter(self));value=self[key]
        del self[key];return key,value

    def pop(self,key,*default):
        if len(default)>1:raise TypeError('pop expected at most 2 arguments')
        if key not in self:
            if default:return default[0]
            raise KeyError(key)
        value=self[key];del self[key];return value

    def move_to_end(self,key,last=True):
        if key not in self:raise KeyError(key)
        if self._native:self._native.move(self._ids[key],last)
        OrderedDict.move_to_end(self,key,last)

    def fetch(self, key, default=None):
        if key not in self:
            return default
        if self._native:self._native.touch(self._ids[key])
        else:self._stamps[key]=None
        OrderedDict.move_to_end(self,key)
        return self[key]

    def touch_many(self,keys):
        present=[key for key in keys if key in self]
        if self._native:
            self._native.touch_many([self._ids[key] for key in present])
            for key in present:OrderedDict.move_to_end(self,key)
        else:
            for key in present:self.fetch(key)

    def scope(self, focus, radius: float, now: float):
        if len(focus)!=2 or not all(math.isfinite(v) and abs(v)<=1e12 for v in (*focus,radius,now)) or radius<0:
            raise ValueError('finite residency focus/time and nonnegative radius required')
        if self._native:
            expired=self._native.scope(focus,radius,now)
            for identity in expired:
                key=self._keys.pop(identity);self._ids.pop(key);OrderedDict.__delitem__(self,key)
            return len(expired)
        removed = 0
        for key in list(self):
            stamp = self._stamps.get(key)
            if stamp is None:
                self._stamps[key] = (tuple(focus), now)
            elif math.dist(stamp[0], focus) > radius and now-stamp[1] >= MIN_DWELL_S:
                del self[key]
                removed += 1
        return removed
