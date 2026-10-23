"""Physical camera contacts, native WMO masks, wet holes and real Qt slot."""
import math,os,struct,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_camera import sphere_triangle,triangle_ray,cast,corridor,CameraBoom,cells,MAX_TRIANGLES
from backend.game_engine_adapter_streaming import Surface,WorldStream
from backend.game_engine_adapter_liquids import LiquidIndex
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from tools.world import engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
TRI=((-1,-1,0),(1,-1,0),(0,1,0))

def page(triangles):
    blob=bytearray();rows=[]
    for points in triangles:
        at=len(blob);blob.extend(struct.pack('<9f',*(n for p in points for n in p)))
        rows.append({'offset':at,'vertices':3,'stride':12,'indices':[0,1,2],'group':0})
    meta={'groups':[{}],'rows':[],'collision':rows}
    return SimpleNamespace(sight=Surface(meta,blob),liquids=LiquidIndex(meta,blob))

class Sweep(unittest.TestCase):
    def test_two_sided_face_contact_stops_radius_before_wall(self):
        for start,end in (((0,0,-2),(0,0,2)),((0,0,2),(0,0,-2))):
            self.assertAlmostEqual(sphere_triangle(start,end,*TRI),.425)
    def test_edge_and_vertex_contacts_hit_when_center_ray_misses(self):
        for x,y,distance in ((0,-1.2,.2),(-1.15,-1.15,math.sqrt(.15**2*2))):
            start,end=(x,y,-2),(x,y,2);self.assertIsNone(triangle_ray(start,end,*TRI))
            self.assertAlmostEqual(sphere_triangle(start,end,*TRI),(2-math.sqrt(.3**2-distance**2))/4)
    def test_grazing_contact_and_origin_penetration(self):
        self.assertAlmostEqual(sphere_triangle((-2,-1.3,0),(2,-1.3,0),*TRI),.25)
        self.assertIsNone(sphere_triangle((0,0,.2),(0,0,2),*TRI))
        self.assertIsNone(sphere_triangle((0,0,.3),(0,0,-2),*TRI))
    def test_corner_and_cell_boundary_do_not_skip_nearby_wall(self):
        self.assertIn((0,1),cells((.1,0,.2),(16.1,0,16.2),8))
        self.assertIn((1,0),cells((.1,0,.2),(16.1,0,16.2),8,.3))
        p=page([((-.1,-1,-1),(-.1,1,-1),(-.1,0,1))])
        hit,count,overflow=cast([p],(.15,0,-2),(.15,0,2),False)
        self.assertIsNotNone(hit);self.assertFalse(overflow);self.assertEqual(count,1)
    def test_shared_cap_clips_safely_and_disabled_placements_are_skipped(self):
        p=page([TRI]);p.sight.active_props=set();triangle=next(iter(p.sight.cells.values()))[0];triangle[3]['prop_key']='mddf:4'
        self.assertEqual(cast([p],(0,0,-2),(0,0,2),False),(None,0,False))
        p.sight.active_props={'mddf:4'};self.assertAlmostEqual(cast([p],(0,0,-2),(0,0,2),False)[0],1.7)
        p=page([TRI]*(MAX_TRIANGLES+1));hit,count,overflow=cast([p],(0,0,-2),(0,0,2),False)
        self.assertEqual(hit,0);self.assertEqual(count,MAX_TRIANGLES+1);self.assertTrue(overflow)
    def test_snap_in_and_frame_rate_independent_eased_return(self):
        p=page([TRI]);c=CameraBoom();self.assertAlmostEqual(c.solve([p],(0,0,-2),(0,0,2),.1,False)[2],-.3)
        distances=[]
        for steps in (10,60):
            c=CameraBoom();c.solve([p],(0,0,-2),(0,0,2),.1,False)
            for _ in range(steps):c.solve([],(0,0,-2),(0,0,2),1/steps,False)
            distances.append(c.distance)
        self.assertAlmostEqual(distances[0],distances[1]);self.assertAlmostEqual(distances[0],4-(4-1.7)*math.exp(-6))
        self.assertEqual(c.solve([],(20,0,0),(20,0,4),.01,False),(20.,0.,4.))
    def test_original_water_corridor_bands_and_clearance(self):
        d=.75*2.031;target=1.512012;pivot,floor,band=corridor(d,0,target,target)
        self.assertEqual(band,'SURFACE');self.assertAlmostEqual(pivot-d,2/9);self.assertEqual(pivot,floor)
        self.assertEqual(corridor(target+2/9,0,target,target)[2],'SUBMERGE')
        self.assertEqual(corridor(target+5/9,0,target,target)[2],'CLEAR')

class OriginalWorldCamera(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_native_original_walk_and_camera_masks_remain_independent(self):
        f.make(self.root);native=NativeFormats(self.root);self.addCleanup(native.close)
        for flags,blocks in ((0x22,False),(0x24,True)):
            room=bytearray(f.room());offset=room.index(b'YPOM')+8;room[offset:offset+12]=bytes((flags,0))*6
            (self.root/'rooms_000.wmo').write_bytes(room)
            meta,blob=native.decode(self.root/'rooms.wmo',world_scene=True)
            p=SimpleNamespace(sight=Surface({**meta,'collision':meta['sight_collision']},blob),liquids=LiquidIndex(meta,blob))
            hit,_,_=cast([p],(-6,4,12),(-2,4,12),False)
            self.assertEqual(hit is not None,blocks)
            if blocks:self.assertAlmostEqual(hit,1.7)
    def test_native_liquid_mesh_cast_is_a_ray_and_preserves_wet_holes(self):
        f.make(self.root);(self.root/'Test_32_32.adt').write_bytes(f.terrain(liquid={'wet':[False]+[True]*63}))
        native=NativeFormats(self.root);self.addCleanup(native.close);meta,blob=native.decode(self.root/'Test_32_32.adt',world_scene=True)
        p=SimpleNamespace(sight=Surface({**meta,'rows':[],'collision':[],'groups':[{}]},b''),liquids=LiquidIndex(meta,blob))
        grid=p.liquids.grids[0]
        for cell,wet in ((0,False),(1,True)):
            j,i=divmod(cell,grid.cols-1);a=grid.points[j*grid.cols+i];b=grid.points[(j+1)*grid.cols+i+1]
            x,z=(a[0]+b[0])/2,(a[2]+b[2])/2
            hit,_,_=cast([p],(x,8,z),(x,2,z),True)
            self.assertEqual(hit is not None,wet)
            if wet:self.assertAlmostEqual(hit,3)
            self.assertIsNone(cast([p],(x,8,z),(x,2,z),False)[0])
    def test_world_qt_slot_seats_camera_and_rejects_nan_without_growth(self):
        s=WorldStream();self.addCleanup(s.close);s.configure(str(f.make(self.root)));end=time.monotonic()+6
        while time.monotonic()<end:
            s.update(-8,3.65,12)
            if len(s.pages)==2 and s.pending is None:break
            time.sleep(.005)
        self.assertEqual(s.last_error,'');before=s.bytes
        view={'feet':[-8,3,12],'head_height':1.4,'pivot_height':1.45,'yaw':90,'pitch':0,'distance':6,'delta':1/60,'water_collision':False}
        point=s.solveCamera(view);self.assertAlmostEqual(point.x(),-4.3,places=5);self.assertTrue(s.camera_boom.status['clipped'])
        for _ in range(20):self.assertEqual(s.solveCamera(view),point)
        self.assertEqual(s.bytes,before);view['yaw']=float('nan');point=s.solveCamera(view)
        self.assertTrue(all(math.isfinite(n) for n in (point.x(),point.y(),point.z())));self.assertIn('error',s.camera_boom.status)
        s.close();self.assertEqual(s.bytes,0)

if __name__=='__main__':unittest.main()
