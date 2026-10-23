"""The original dual render seed, independent from the player's area claim."""
import os,struct,unittest
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from backend.game_engine_adapter_streaming import Surface
from backend.game_engine_adapter_rooms import camera_seeds
from backend.game_engine_adapter_portals import visibility,PortalCamera

def floor(y,group,blob):
    at=len(blob)
    for x,z in ((-2,-2),(2,-2),(2,2),(-2,2)):blob.extend(struct.pack('<8f',x,y,z,0,1,0,0,0))
    return {'offset':at,'stride':32,'vertices':4,'indices':[0,1,2,0,2,3],'group':group,'bounds':[[-2,y,-2],[2,y,2]]}
def building(*,portal=True,detail=False,vertical=False):
    blob=bytearray();rows=[] if detail else [floor(2,0,blob),floor(12,1,blob)]
    corners=[[x,y,z] for x in (-2,2) for y in (0,14) for z in (-2,2)]
    groups=[{'id':i,'flags':0,'corners':corners,'portal_start':i,'portal_count':1 if portal else 0} for i in range(2)]
    points=[[0,y,z] for y,z in ((2,-2),(8,-2),(8,2),(2,2))] if vertical else [[x,10,z] for x,z in ((-2,-2),(2,-2),(2,2),(-2,2))]
    plane=[1,0,0,0] if vertical else [0,1,0,-10]
    metadata={'rows':[],'collision':rows,'groups':groups,'portals':{'infos':[{'plane':plane,'points':points}],'refs':[{'portal':0,'group':1,'side':-1},{'portal':0,'group':0,'side':1}]}}
    surface=Surface(metadata,bytes(blob));camera=None
    if detail:
        extra=bytearray();row=floor(2,0,extra);camera=Surface({**metadata,'collision':[row]},bytes(extra))
    return SimpleNamespace(metadata=metadata,surface=surface,camera_only=camera)
class Rooms(unittest.TestCase):
    def test_floor_hole_seeds_both_sides_and_flips_primary(self):
        p=building();self.assertEqual(camera_seeds(p,(0,9,0)),(0,(0,)))
        self.assertEqual(camera_seeds(p,(0,11,0)),(1,(1,0)))
    def test_portal_on_the_same_height_wins_face_tie(self):
        p=building();self.assertEqual(camera_seeds(p,(0,12,0)),(1,(1,)))
        p.metadata['portals']['infos'][0]['plane']=[0,1,0,-12]
        p.metadata['portals']['infos'][0]['points']=[[x,12,z] for x,z in ((-2,-2),(2,-2),(2,2),(-2,2))]
        self.assertEqual(camera_seeds(p,(0,12,0)),(1,(1,0)))
    def test_terrain_only_wins_when_strictly_nearer_and_below_eye(self):
        p=building();self.assertEqual(camera_seeds(p,(0,11,0),10),(1,(1,0)))
        self.assertEqual(camera_seeds(p,(0,11,0),10.5),(None,()))
        self.assertEqual(camera_seeds(p,(0,11,0),20),(1,(1,0)))
    def test_vertical_doorway_snaps_within_original_point_one_yard(self):
        p=building(vertical=True);self.assertEqual(camera_seeds(p,(.05,5,0)),(1,(1,0)))
        self.assertEqual(camera_seeds(p,(.2,5,0)),(0,(0,)))
        self.assertEqual(camera_seeds(p,(-.05,5,0)),(0,(0,1)))
    def test_exterior_winner_has_no_render_seeds(self):
        p=building();p.metadata['groups'][1]['flags']=8;self.assertEqual(camera_seeds(p,(0,11,0)),(None,()))
    def test_DETAIL_retry_only_when_terrain_and_walking_legs_miss(self):
        p=building(portal=False,detail=True);self.assertEqual(camera_seeds(p,(0,4,0)),(0,(0,)))
        self.assertEqual(camera_seeds(p,(0,4,0),1),(None,()))
    def test_ray_drop_and_column_are_bounded(self):
        p=building(portal=False);self.assertEqual(camera_seeds(p,(0,2000,0)),(None,()))
        self.assertEqual(camera_seeds(p,(3,5,0)),(None,()))
    def test_both_roots_render_even_when_camera_faces_away_from_hole(self):
        p=building();view=PortalCamera({'eye':[0,11,0],'forward':[1,0,0],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':100})
        single,_=visibility(p.metadata,view,1);dual,_=visibility(p.metadata,view,1,(1,0))
        self.assertIn(1,single);self.assertEqual(dual,{0,1})
if __name__=='__main__':unittest.main()
