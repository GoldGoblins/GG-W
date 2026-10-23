"""Original intro/skip drives the real camera, never another actor or save pose."""
import copy
import json
import unittest
import test_game_engine_adapter_services as services


class OpeningCinematic(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view

    def setUp(self):
        services.Services.setUp(self)
        self.ui.execute("CINE_EVENTS={};F=CreateFrame('Frame');F:RegisterEvent('CINEMATIC_START');F:RegisterEvent('CINEMATIC_STOP');F:SetScript('OnEvent',function() table.insert(CINE_EVENTS,event) end)")

    def test_original_start_skip_moves_same_camera_and_restores_pose_without_inventory_or_actor_changes(self):
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        pose=self.runtime._camera_pose_locked();position=(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0])
        self.call('OpeningCinematic()');self.assertEqual(self.ui.evaluate('return InCinematic()'),[1])
        start=self.runtime._camera_pose_locked();self.assertNotEqual(start,pose)
        for _ in range(6):self.runtime._tick_opening_cinematic_locked(.5)
        self.publish();self.assertNotEqual(start,self.runtime._camera_pose_locked())
        row=self.runtime._client_tick_input_locked(dict(forward=1.,turn=1.,jump=True,boost=True))
        self.assertEqual(row['forward'],0.);self.assertFalse(row['jump']);self.assertFalse(row['boost'])
        self.assertEqual(self.runtime._client_controls_save_locked()['pose'],pose)
        self.call('StopCinematic()');self.assertEqual(self.ui.evaluate('return InCinematic()'),[None])
        self.assertEqual(self.runtime._camera_pose_locked(),pose)
        self.assertEqual(self.ui.evaluate('return table.concat(CINE_EVENTS,",")'),['CINEMATIC_START,CINEMATIC_STOP'])
        self.assertEqual(position,(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]))
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))

    def test_complete_and_repeated_start_save_restore_keep_the_pre_intro_camera(self):
        pose=self.runtime._camera_pose_locked();self.call('OpeningCinematic();OpeningCinematic()')
        self.assertEqual(self.runtime._opening_cinematic['restore'],pose)
        for _ in range(12):self.runtime._tick_opening_cinematic_locked(1.)
        self.publish();self.assertIsNone(self.runtime._opening_cinematic)
        self.assertEqual(self.runtime._camera_pose_locked(),pose)
        self.call('OpeningCinematic()');self.runtime._tick_opening_cinematic_locked(1.);self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertIsNone(self.runtime._opening_cinematic);self.assertEqual(self.runtime._camera_pose_locked(),pose)
        self.assertEqual(self.ui.evaluate('return InCinematic()'),[None])

    def test_dead_taxi_vehicle_and_nonfinite_clock_do_not_start_or_corrupt_the_camera(self):
        pose=self.runtime._camera_pose_locked()
        self.runtime._combat_state['actors']['player']['alive']=False
        self.assertEqual(self.service('CinematicStart')['error'],'PLAYER_DEFEATED')
        self.assertIsNone(self.runtime._opening_cinematic);self.assertEqual(self.runtime._camera_pose_locked(),pose)
        self.runtime._combat_state['actors']['player']['alive']=True;self.runtime._vehicle_kind='BOAT'
        self.assertEqual(self.service('CinematicStart')['error'],'EXIT_VEHICLE_FIRST')
        self.runtime._vehicle_kind='NONE';self.call('OpeningCinematic()')
        current=self.runtime._camera_pose_locked()
        with self.assertRaisesRegex(ValueError,'CINEMATIC_CLOCK_INVALID'):self.runtime._tick_opening_cinematic_locked(float('nan'))
        self.assertEqual(self.runtime._camera_pose_locked(),current)
        self.assertEqual(self.control('camera','Save',index=1)['error'],'CINEMATIC_IN_PROGRESS')

    def test_physical_input_travel_and_window_cleanup_preserve_then_restore_the_real_pose(self):
        pose=self.runtime._camera_pose_locked();self.call('OpeningCinematic()')
        intro=self.runtime._camera_pose_locked();yaw=self.runtime._yaw[0]
        self.runtime.set_input(json.dumps(dict(camera_yaw=11.,camera_pitch=-80.,camera_distance=40.,
                                               facing_yaw=75.,mouse_look=True,movement_mode='FLY',ability_1=True)))
        self.assertEqual(self.runtime._camera_pose_locked(),intro);self.assertEqual(self.runtime._yaw[0],yaw)
        self.assertEqual(self.runtime._movement_mode,'GROUND')
        self.assertFalse(self.runtime._client_tick_input_locked(self.runtime._input)['ability_1'])
        self.assertEqual(self.service('TaxiOpen',target='npc-wanderer-01')['error'],'CINEMATIC_IN_PROGRESS')
        self.assertEqual(self.control('input','Fire',key='CameraZoomIn',value=2.)['error'],'CINEMATIC_IN_PROGRESS')
        self.assertEqual(self.control('input','Start',key='MoveForward')['error'],'CINEMATIC_IN_PROGRESS')
        self.runtime._clear_service_windows_locked();self.publish()
        self.assertEqual(self.runtime._camera_pose_locked(),pose);self.assertFalse(self.runtime._legacy_held)
        self.assertEqual(self.ui.evaluate('return InCinematic()'),[None])

if __name__=='__main__':unittest.main()
