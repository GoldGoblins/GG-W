"""Transport frame boundaries and real GG vehicle particle integration."""
import math
import unittest

from backend.game_engine_adapter_rides import RideFrame, RidesMixin, retarget
import test_game_engine_adapter_private_world as private_tests


class Frames(unittest.TestCase):
    def near(self,a,b):
        for actual,expected in zip(a,b):self.assertAlmostEqual(actual,expected,places=8)

    def test_birth_draw_inverse_even_at_large_world_coordinates(self):
        frame=RideFrame('boat',(120000.,350.,-160000.),1.1)
        point=(120004.,351.7,-160008.)
        self.near(frame.to_world(frame.to_stored(point)),point)
        direction=(-5.,2.,7.)
        self.near(frame.direction_to_world(frame.direction_to_stored(direction)),direction)

    def test_boarding_and_leaving_preserve_world_position_velocity(self):
        frame=RideFrame('boat',(100.,5.,-40.),.75)
        point=(102.,7.,-42.);velocity=(1.,3.,-2.)
        stored,direction=retarget(None,frame,point,velocity)
        self.near(frame.to_world(stored),point);self.near(frame.direction_to_world(direction),velocity)
        world,speed=retarget(frame,None,stored,direction)
        self.near(world,point);self.near(speed,velocity)

    def test_same_deck_motion_does_not_fold_stored_points_twice(self):
        old=RideFrame('boat',(10.,4.,20.),.3);new=RideFrame('boat',(19.,8.,21.),.7)
        point=(2.,3.,-1.);velocity=(1.,2.,3.)
        stored,direction=retarget(old,new,point,velocity)
        self.near(stored,point);self.near(direction,velocity)
        self.assertNotEqual(old.to_world(point),new.to_world(point))

    def test_transport_to_transport_handoff_keeps_effects_in_place(self):
        old=RideFrame('boat-a',(10.,4.,20.),.3);new=RideFrame('boat-b',(19.,8.,21.),.7)
        point=(2.,3.,-1.);velocity=(1.,2.,3.)
        stored,direction=retarget(old,new,point,velocity)
        self.near(new.to_world(stored),old.to_world(point))
        self.near(new.direction_to_world(direction),old.direction_to_world(velocity))

    def test_invalid_frame_and_nonfinite_state_rejected(self):
        for frame in (('',(0,0,0),0),('boat',(0,float('nan'),0),0),('boat',(0,0,0),float('inf'))):
            with self.subTest(frame=frame),self.assertRaises(ValueError):RideFrame(*frame)
        with self.assertRaisesRegex(ValueError,'RIDE_VECTOR_INVALID'):retarget(None,None,(0,0,float('nan')),(0,0,0))


class RuntimeRides(unittest.TestCase):
    setUp=private_tests.PrivateWorld.setUp

    def point(self,index):return tuple(self.runtime._ride_particle_world_locked(index))

    def assertPoint(self,actual,expected):
        for a,b in zip(actual,expected):self.assertAlmostEqual(a,b,places=7)

    def particle(self,owner='player'):
        self.runtime._spawn_particle_locked(20.,8.,30.,2.,3.,4.,2.,'#ffee11',owner=owner)
        return self.runtime._active_particle_indices[-1]

    def board(self):
        index=self.runtime._ride_boat_index_locked()
        self.assertIsNotNone(index)
        self.runtime._x[index]=10.;self.runtime._y[index]=5.;self.runtime._z[index]=20.;self.runtime._yaw[index]=.25
        self.runtime._vehicle_kind='BOAT'
        self.runtime._sync_ride_particles_locked()
        return index

    def test_player_effect_follows_live_existing_hull_world_dust_stays_fixed_and_leave_has_no_jump(self):
        rider=self.particle('player');dust=self.particle('')
        before=self.point(rider);boat=self.board()
        self.assertPoint(self.point(rider),before);self.assertPoint(self.point(dust),before)
        frame=self.runtime._ride_frame_locked();stored=(self.runtime._px[rider],self.runtime._py[rider],self.runtime._pz[rider])
        self.runtime._x[boat]+=7.;self.runtime._y[boat]+=1.;self.runtime._yaw[boat]+=.5
        after=self.runtime._ride_frame_locked().to_world(stored)
        self.assertPoint(self.point(rider),after);self.assertPoint(self.point(dust),before)
        self.runtime._vehicle_kind='NONE';self.runtime._sync_ride_particles_locked()
        self.assertPoint(self.point(rider),after)

    def test_particle_birth_on_boat_and_rendered_snapshot_share_the_live_ride_frame(self):
        self.board();index=self.particle()
        self.assertPoint(self.point(index),(20.,8.,30.))
        frame=self.runtime._ride_frame_locked();self.assertEqual(self.runtime._ride_particle_floor_locked(index),.08-frame.position[1])
        snapshot=self.runtime.snapshot()
        matches=[row for row in snapshot['render']['particles'] if row['color']=='#ffee11']
        self.assertEqual(len(matches),1);self.assertPoint((matches[0]['x'],matches[0]['y'],matches[0]['z']),(20.,8.,30.))
        self.assertEqual(snapshot['player']['ride_frame']['kind'],'BOAT')

    def test_travel_cleared_attachment_resolves_same_boat_and_does_not_spawn_another(self):
        boat=self.runtime._ride_boat_index_locked();registry=list(self.runtime._active_entity_indices)
        self.runtime._lifecycle_move_locked(dict(x=0.,y=1.,z=0.))
        self.assertIsNone(self.runtime._boat_entity_index)
        self.assertEqual(self.runtime._ride_boat_index_locked(),boat)
        self.assertEqual(self.runtime._active_entity_indices,registry)

    def test_hoverboard_uses_actual_character_pose_without_creating_a_vehicle_actor(self):
        registry=list(self.runtime._active_entity_indices)
        self.runtime._vehicle_kind='HOVERBOARD';self.runtime._x[0]=10.;self.runtime._y[0]=4.;self.runtime._z[0]=20.
        index=self.particle();stored=(self.runtime._px[index],self.runtime._py[index],self.runtime._pz[index])
        self.runtime._x[0]+=12.;self.runtime._yaw[0]+=math.pi/2
        self.assertPoint(self.point(index),self.runtime._ride_frame_locked().to_world(stored))
        self.assertEqual(self.runtime._active_entity_indices,registry)

    def test_dead_or_removed_hull_releases_last_finite_effect_frame(self):
        boat=self.board();index=self.particle();before=self.point(index)
        self.runtime._alive[boat]=False
        self.assertIsNone(self.runtime._ride_frame_locked())
        self.assertPoint(self.point(index),before)


if __name__=='__main__':unittest.main()
