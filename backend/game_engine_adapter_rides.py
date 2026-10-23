"""Yaw-only ride frames for the existing GG boat/hoverboard and effect pool.

The frame rule follows original engine-world/ride_frame.rs: convert stored
points only at a boarding/leaving edge, then read the transport's live frame
when drawing. A moving deck must never get folded into stored points twice.
The actual GG mobility simulation remains the only writer of vehicle motion.
"""
import math
from dataclasses import dataclass


def vector(values):
    if not isinstance(values,(tuple,list)) or len(values)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1_000_000 for v in values):
        raise ValueError('RIDE_VECTOR_INVALID')
    return tuple(float(v) for v in values)


@dataclass(frozen=True)
class RideFrame:
    source: str
    position: tuple
    yaw: float

    def __post_init__(self):
        if not isinstance(self.source,str) or not 1<=len(self.source)<=96 or type(self.yaw) not in (int,float) or not math.isfinite(self.yaw) or abs(self.yaw)>1_000_000:
            raise ValueError('RIDE_FRAME_INVALID')
        object.__setattr__(self,'position',vector(self.position))

    def direction_to_world(self,values):
        x,y,z=vector(values);c,s=math.cos(self.yaw),math.sin(self.yaw)
        return (c*x+s*z,y,-s*x+c*z)

    def direction_to_stored(self,values):
        x,y,z=vector(values);c,s=math.cos(self.yaw),math.sin(self.yaw)
        return (c*x-s*z,y,s*x+c*z)

    def to_world(self,values):
        rotated=self.direction_to_world(values)
        return tuple(rotated[i]+self.position[i] for i in range(3))

    def to_stored(self,values):
        p=vector(values)
        return self.direction_to_stored(tuple(p[i]-self.position[i] for i in range(3)))


def retarget(previous,current,position,velocity):
    """One boundary fold, preserving world position/velocity at that edge."""
    point=vector(position);direction=vector(velocity)
    if previous is None and current is None or previous is not None and current is not None and previous.source==current.source:
        return point,direction
    if previous is not None:
        point=previous.to_world(point);direction=previous.direction_to_world(direction)
    if current is not None:
        point=current.to_stored(point);direction=current.direction_to_stored(direction)
    return point,direction


class RidesMixin:
    def _ride_boat_index_locked(self):
        index=self._boat_entity_index
        if index is not None and 0<=index<len(self._alive) and self._alive[index] and self._kind[index]=='BOAT':return index
        # Travel/respawn clears the control attachment, not the authored hull.
        # Re-resolve that same allocated boat instead of spawning a second one.
        index=next((i for i in self._active_entity_indices if self._alive[i] and self._kind[i]=='BOAT'),None)
        self._boat_entity_index=index
        return index

    def _ride_frame_locked(self):
        descriptor=self._instance_map_descriptor_locked()
        namespace=str(descriptor['instance_id']) if descriptor else '0'
        if self._vehicle_kind=='BOAT':
            index=self._ride_boat_index_locked()
            if index is None:return None
            return RideFrame(namespace+':boat:'+str(index),(self._x[index],self._y[index],self._z[index]),self._yaw[index])
        if self._vehicle_kind=='HOVERBOARD':
            return RideFrame(namespace+':hoverboard:player',(self._x[0],self._y[0],self._z[0]),self._yaw[0])
        return None

    def _reset_ride_particles_locked(self):
        self._particle_owners=['']*len(self._px)
        self._particle_ride_frames=[None]*len(self._px)

    def _ride_particle_birth_locked(self,index,owner=''):
        if not hasattr(self,'_particle_owners') or len(self._particle_owners)!=len(self._px):self._reset_ride_particles_locked()
        if owner not in ('','player'):raise ValueError('RIDE_EFFECT_OWNER_INVALID')
        self._particle_owners[index]=owner
        frame=self._ride_frame_locked() if owner=='player' else None
        position=(self._px[index],self._py[index],self._pz[index])
        velocity=(self._pvx[index],self._pvy[index],self._pvz[index])
        position,velocity=retarget(None,frame,position,velocity)
        self._px[index],self._py[index],self._pz[index]=position
        self._pvx[index],self._pvy[index],self._pvz[index]=velocity
        self._particle_ride_frames[index]=frame

    def _ride_particle_sync_locked(self,index,current):
        previous=self._particle_ride_frames[index]
        position=(self._px[index],self._py[index],self._pz[index])
        velocity=(self._pvx[index],self._pvy[index],self._pvz[index])
        position,velocity=retarget(previous,current,position,velocity)
        self._px[index],self._py[index],self._pz[index]=position
        self._pvx[index],self._pvy[index],self._pvz[index]=velocity
        self._particle_ride_frames[index]=current

    def _sync_ride_particles_locked(self):
        if not hasattr(self,'_particle_owners'):self._reset_ride_particles_locked()
        current=self._ride_frame_locked()
        for index in self._active_particle_indices:
            self._ride_particle_sync_locked(index,current if self._particle_owners[index]=='player' else None)

    def _ride_particle_world_locked(self,index):
        if not hasattr(self,'_particle_owners'):self._reset_ride_particles_locked()
        current=self._ride_frame_locked() if self._particle_owners[index]=='player' else None
        self._ride_particle_sync_locked(index,current)
        position=(self._px[index],self._py[index],self._pz[index])
        return current.to_world(position) if current else position

    def _ride_particle_floor_locked(self,index):
        frame=self._particle_ride_frames[index] if hasattr(self,'_particle_ride_frames') else None
        return .08-frame.position[1] if frame else .08

    def _ride_view_locked(self):
        frame=self._ride_frame_locked()
        if frame is None:return dict(active=False,source='',kind='NONE')
        return dict(active=True,source=frame.source,kind=self._vehicle_kind,
            position=list(frame.position),yaw=frame.yaw,
            orientation='YAW_ONLY',storage='TRANSPORT_FRAME',
            effects=sum(self._particle_owners[i]=='player' for i in self._active_particle_indices) if hasattr(self,'_particle_owners') else 0)

