"""Fixed landscape pages use the same bounded residency as trees and buildings."""
from backend.game_engine_world_trees import WorldTreeModel
from backend.game_engine_landscape import ASSETS

class LandscapeModel(WorldTreeModel):
    def __init__(self,parent=None):
        super().__init__(parent,assets=ASSETS,catalog_name='world-landscape.catalog.json',schema='gg.world-landscape-catalog.v1')

def update_landscape(bridge,view):
    model=getattr(bridge,'_landscape_model',None)
    if model is not None:
        from backend.game_engine_host import _RUNTIME
        model.set_view(view,_RUNTIME._render_profile)
