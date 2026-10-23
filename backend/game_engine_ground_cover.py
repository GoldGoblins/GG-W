"""Saved cosmetic cutout cards; no gameplay entities, colliders or pickups."""
from pathlib import Path
from copy import deepcopy
import math
from backend.game_engine_world_trees import WorldTreeModel

ASSETS=Path(__file__).resolve().parents[1]/'qml/assets/authored/world/ground-cover'
RANGES={'POTATO':64.,'PS2_CLASSIC':128.,'BALANCED':160.,'MODERN':192.,'CINEMATIC':224.}

class GroundCoverModel(WorldTreeModel):
    def __init__(self,parent=None):
        super().__init__(parent,assets=ASSETS,catalog_name='ground-cover.catalog.json',schema='gg.ground-cover-catalog.v1')
    def set_view(self,view,profile='PS2_CLASSIC'):
        far=min(view[-1],RANGES.get(profile,160.));origin=view[0]
        anchor=getattr(self,'_cover_anchor',None)
        # Camera-boom rotation stays within the resident neighbourhood.
        if anchor is None or math.dist(anchor,origin)>24:self._cover_anchor=origin
        origin=self._cover_anchor
        radius=far*math.sqrt(1+view[4]**2*(1+view[5]**2))+88
        full=self.catalog['sectors'];local={};cell=self.catalog['sector_m']
        for cx in range(math.floor((origin[0]-radius)/cell),math.floor((origin[0]+radius)/cell)+1):
            for cz in range(math.floor((origin[2]-radius)/cell),math.floor((origin[2]+radius)/cell)+1):
                key=f'{cx}:{cz}'
                if key in full:local[key]=full[key]
        # Select by the local spatial index rather than scanning all world
        # saved sectors on every movement update.
        self.catalog['sectors']=local
        try:super().set_view((origin,*view[1:-1],far),profile)
        finally:self.catalog['sectors']=full
    def measurements(self):
        result=super().measurements()
        result['decorative_cards']=result.pop('map_trees')
        result.update(range_policy='SHORT_RANGE_COSMETIC_ONLY',interactive=False,collision=False)
        return result

def update_ground_cover(bridge,view):
    from backend import game_engine_host
    model=getattr(bridge,'_ground_cover_model',None)
    if model is None:return
    runtime=game_engine_host._RUNTIME;doc=runtime._terrain_overrides
    signature=(id(doc),doc.get('revision',0))
    if signature!=getattr(bridge,'_ground_cover_terrain_signature',None):
        with runtime._lock:document=deepcopy(doc)
        model.set_terrain(document);bridge._ground_cover_terrain_signature=signature
    model.set_view(view,runtime._render_profile)
