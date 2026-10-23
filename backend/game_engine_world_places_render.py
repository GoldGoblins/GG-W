"""World structures reuse the tested retained, paced tree-sector renderer."""
from copy import deepcopy
from backend.game_engine_world_trees import WorldTreeModel
from backend.game_engine_world_places import ASSETS


class WorldPlacesModel(WorldTreeModel):
    def __init__(self,parent=None):
        super().__init__(parent,assets=ASSETS,catalog_name='world-places.catalog.json',schema='gg.world-places-catalog.v1')
    def measurements(self):
        result=super().measurements()
        result['map_objects']=result.pop('map_trees')
        result.update(places=self.catalog['place_count'],structures=self.catalog['object_count'])
        return result


def update_world_places(bridge,view):
    from backend import game_engine_host
    model=getattr(bridge,'_world_places_model',None)
    if model is None:return
    runtime=game_engine_host._RUNTIME;doc=runtime._terrain_overrides
    signature=(id(doc),doc.get('revision',0))
    if signature!=getattr(bridge,'_world_places_terrain_signature',None):
        with runtime._lock:document=deepcopy(doc)
        model.set_terrain(document);bridge._world_places_terrain_signature=signature
    model.set_view(view,runtime._render_profile)
