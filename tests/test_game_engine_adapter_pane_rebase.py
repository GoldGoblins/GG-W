"""Existing particle/ribbon kernels preserve live trails through pane movement."""
import math
import struct
import tempfile
import unittest
from pathlib import Path
from backend.game_engine_adapter_formats import NativeFormats
from backend.game_engine_adapter_pane_anchor import anchor
from tools.world import engine_format_fixtures as f


def project(matrix, qt_point):
    x, z, negative_y = qt_point
    y = -negative_y
    return tuple(matrix[i] * x + matrix[4+i] * y + matrix[8+i] * z + matrix[12+i] for i in range(3))


class PaneRebase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.reader = NativeFormats(self.root);self.addCleanup(self.reader.close)

    def pose(self, path, matrix, clock=250, **options):
        return self.reader.pose(path, instance='pane', anim_id=7, cursor_ms=clock,
                                clock_ms=clock, pane_anchor=matrix, **options)

    def test_world_space_live_centers_stay_fixed_through_rotation_translation_scale(self):
        path = self.root/'trail.m2';path.write_bytes(f.particle_m2(flags=0, speed=0))
        first = anchor({'model_scale':1, 'position':[0,0,0]})
        second = anchor({'model_scale':2, 'facing':math.pi/2, 'position':[10,2,3]})
        self.reader.decode(path, runtime=True, instance='pane', anim_id=7, clock_ms=0, pane_anchor=first)
        before, blob = self.pose(path, first)
        row = before['effects']['rows'][0]
        points = [struct.unpack_from('<3f', blob, row['offset']+i*48) for i in range(row['vertices'])]
        centers = [tuple(sum(p[j] for p in points[i:i+4])/4 for j in range(3)) for i in range(0,len(points),4)]
        after, packet = self.pose(path, second, particle_density=0)
        self.assertEqual(after['effects']['live_particles'], before['effects']['live_particles'])
        self.assertFalse(after['effects']['reset'])
        result = after['effects']['rows'][0]
        moved = [struct.unpack_from('<3f',packet,result['offset']+i*48) for i in range(result['vertices'])]
        for i, center in enumerate(centers):
            current = tuple(sum(p[j] for p in moved[i*4:i*4+4])/4 for j in range(3))
            for old, new in zip(project(first,center),project(second,current)):
                self.assertAlmostEqual(old,new,places=5)
        self.assertFalse(any('layout anchor' in note for note in after['effects']['limitations']))

    def test_model_space_particles_follow_root_and_bad_affine_does_not_reset(self):
        path = self.root/'local.m2';path.write_bytes(f.particle_m2(flags=0x10,speed=0))
        first = anchor({});second = anchor({'position':[10,0,0]})
        self.reader.decode(path,runtime=True,instance='pane',anim_id=7,clock_ms=0,pane_anchor=first)
        before,blob = self.pose(path,first);after,packet = self.pose(path,second,particle_density=0)
        a=before['effects']['rows'][0];b=after['effects']['rows'][0]
        self.assertEqual(blob[a['offset']:a['offset']+a['vertices']*48],packet[b['offset']:b['offset']+b['vertices']*48])
        with self.assertRaises(ValueError):self.pose(path,[0]*16,clock=500)
        good,_=self.pose(path,second,particle_density=0)
        self.assertEqual(good['effects']['live_particles'],after['effects']['live_particles'])

    def test_retained_ribbon_history_stays_fixed_when_parent_moves(self):
        path=self.root/'ribbon.m2';path.write_bytes(f.ribbon_m2())
        first=anchor({});second=anchor({'position':[10,3,0],'facing':.7,'model_scale':2})
        self.reader.decode(path,runtime=True,instance='pane',anim_id=7,clock_ms=0,pane_anchor=first)
        before,blob=self.pose(path,first,clock=100)
        after,packet=self.pose(path,second,clock=100)
        self.assertEqual(before['ribbons']['live_edges'],after['ribbons']['live_edges'])
        a=before['ribbons']['rows'][0];b=after['ribbons']['rows'][0]
        # The first strip's current node moves; its historical edge stays put.
        for index in (1,2):
            old=struct.unpack_from('<3f',blob,a['offset']+index*48)
            new=struct.unpack_from('<3f',packet,b['offset']+index*48)
            for x,y in zip(project(first,old),project(second,new)):self.assertAlmostEqual(x,y,places=5)


if __name__=='__main__':unittest.main()
