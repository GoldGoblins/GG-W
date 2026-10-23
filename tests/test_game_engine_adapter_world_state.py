"""Real local saves, native pages and a new process restore the same map/pet."""
import copy,json,os,subprocess,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_game_engine_adapter_pet_world_transition as fixtures
from backend.game_engine_adapter_streaming import update_world
from backend import game_engine_adapter_world_state as state


class MountedWorldState(unittest.TestCase):
    setUp=fixtures.PetTransitions.setUp
    bind=fixtures.PetTransitions.bind
    service=fixtures.PetTransitions.service
    tame=fixtures.PetTransitions.tame
    configure=fixtures.PetTransitions.configure
    load=fixtures.PetTransitions.load
    unload=fixtures.PetTransitions.unload
    settle=fixtures.PetTransitions.settle
    distinct_floor=fixtures.PetTransitions.distinct_floor

    def saved_world(self):
        self.distinct_floor();self.load();self.settle()
        with self.runtime._lock:
            self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]=-6.,100.65,28.
            self.runtime._yaw[0]=.75
            self.pet.update(x=-7.,y=100.,z=29.,yaw=47.,vx=0.,vz=0.)
            self.pet['xp']=97
            self.runtime.save_state(snapshot=False)
        return self.runtime._state_store.load(self.runtime._persistence_key)

    def reload(self):
        result=self.runtime.load_state()
        self.assertNotIn('error',result)
        update_world(self.bridge);self.settle()
        return self.runtime._active_pet_locked()

    def test_same_character_reload_restores_saved_map_pose_pet_progress_and_exact_gg_return(self):
        saved=self.saved_world();description=saved['content_state']['mounted_world']
        health=self.runtime._combat_state['actors']['pet:'+str(self.pet['number'])]['health']
        pet=self.reload()
        self.assertEqual(self.bridge._engine_world_stream.config['map'],'Test')
        for key in ('x','y','z','yaw'):
            self.assertEqual(getattr(self.runtime,'_'+key)[0],description['mounted_pose'][key])
            self.assertEqual(pet[key],description['pet_return']['mounted_pose'][key])
        self.assertEqual(pet['xp'],97)
        self.assertAlmostEqual(self.runtime._combat_state['actors']['pet:'+str(pet['number'])]['health'],health,places=7)
        self.assertEqual(sum(row['id']==pet['id'] for row in self.runtime._nature.rows),1)
        self.unload()
        for key in state.POSE:self.assertEqual(getattr(self.runtime,'_'+key)[0],description['return_pose'][key])
        for key in ('x','y','z','yaw'):self.assertEqual(pet[key],description['pet_return']['pose'][key])

    def test_pending_autosave_keeps_imported_pose_and_does_not_write_transition_fields_to_pet(self):
        saved=self.saved_world();description=saved['content_state']['mounted_world']
        self.runtime.load_state()
        self.assertIsNone(self.runtime._engine_world)
        self.assertIsNotNone(self.runtime._mounted_world_resume)
        self.assertFalse(any(row['id']==self.pet['id'] for row in self.runtime._nature.rows))
        self.runtime.save_state(snapshot=False)
        after=self.runtime._state_store.load(self.runtime._persistence_key)
        self.assertEqual(after['content_state']['mounted_world'],description)
        stored=after['player']['client_controls']['services']['pets'][0]
        self.assertFalse(any('resume' in key or 'manifest' in key for key in stored))
        update_world(self.bridge);self.settle()
        self.assertEqual(self.runtime._x[0],-6.)

    def test_changed_manifest_is_not_autoapproved_and_single_failure_preserves_retry_descriptor(self):
        saved=self.saved_world();description=saved['content_state']['mounted_world']
        self.configure(spawn=[-1,100.65,20])
        self.runtime.load_state()
        update_world(self.bridge)
        self.assertIsNone(self.runtime._engine_world)
        self.assertIn('changed',self.runtime._mounted_world_resume_error)
        for key in state.POSE:self.assertEqual(getattr(self.runtime,'_'+key)[0],description['return_pose'][key])
        with patch('backend.game_engine_adapter_world_state.verified_manifest',side_effect=AssertionError('No retry loop')):
            update_world(self.bridge)
        self.runtime.save_state(snapshot=False)
        after=self.runtime._state_store.load(self.runtime._persistence_key)
        self.assertEqual(after['content_state']['mounted_world'],description)

    def test_missing_manifest_uses_gg_return_and_explicit_unload_clears_saved_map(self):
        self.saved_world();self.manifest.unlink()
        self.runtime.load_state();update_world(self.bridge)
        self.assertIsNone(self.runtime._engine_world)
        self.assertIn('unavailable',self.runtime._mounted_world_resume_error)
        from backend.game_engine_adapter_streaming import load_world
        load_world(self.bridge,'')
        self.runtime.save_state(snapshot=False)
        after=self.runtime._state_store.load(self.runtime._persistence_key)
        self.assertIsNone(after['content_state']['mounted_world'])

    def test_invalid_descriptor_rejects_before_mutating_character_or_provider(self):
        saved=self.saved_world();before=(self.runtime._x[0],copy.deepcopy(self.runtime._item_instances),self.runtime._engine_world)
        invalid=copy.deepcopy(saved);invalid['content_state']['mounted_world']['mounted_pose']['y']=float('nan')
        with patch.object(self.runtime._state_store,'load',return_value=invalid):
            result=self.runtime.load_state()
        self.assertIn('WORLD_SAVE_POSE_INVALID',result['error'])
        self.assertEqual((self.runtime._x[0],self.runtime._item_instances,self.runtime._engine_world),before)

    def test_character_switch_does_not_mount_previous_characters_map_or_replay_return(self):
        self.saved_world()
        self.assertTrue(self.session.logout(),self.session.error)
        self.assertTrue(self.session.enter(self.second),self.session.error)
        self.bind(self.second)
        second=(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0])
        update_world(self.bridge)
        self.assertIsNone(self.runtime._engine_world)
        self.assertIsNone(getattr(self.runtime,'_mounted_world_resume',None))
        self.assertEqual((self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]),second)

    def test_running_login_cannot_fall_on_partial_terrain_before_saved_wmo_commits(self):
        self.load();self.settle()
        with self.runtime._lock:
            self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]=-6.,3.65,12.
            self.runtime._vx[0]=self.runtime._vy[0]=self.runtime._vz[0]=0.
            self.runtime._active_pet_locked().update(x=-7.,y=3.,z=12.,xp=97)
            self.runtime.save_state(snapshot=False)
        self.runtime.load_state()
        with self.runtime._lock:
            previous=self.runtime._running;self.runtime._running=True
            pose=tuple(getattr(self.runtime,'_'+key)[0] for key in state.POSE)
            clock=self.runtime._sim_time
            for _ in range(12):self.runtime._tick_locked(1/30)
            self.assertEqual(tuple(getattr(self.runtime,'_'+key)[0] for key in state.POSE),pose)
            self.assertEqual(self.runtime._sim_time,clock)
        try:
            update_world(self.bridge);stream=self.runtime._engine_world
            self.assertTrue(stream.initial_collision_pending)
            stream.pending.result(timeout=10)
            update_world(self.bridge)
            self.assertEqual(len(stream.pages),1)
            self.assertTrue(stream.initial_collision_pending)
            with self.runtime._lock:
                saved=tuple(getattr(self.runtime,'_'+key)[0] for key in state.POSE)
                for _ in range(12):self.runtime._tick_locked(1/30)
                self.assertEqual(tuple(getattr(self.runtime,'_'+key)[0] for key in state.POSE),saved)
                self.assertEqual(self.runtime._sim_time,clock)
            self.settle();self.assertFalse(stream.initial_collision_pending)
            self.assertEqual(len(stream.pages),2)
            self.assertEqual(self.runtime._active_pet_locked()['xp'],97)
        finally:
            with self.runtime._lock:self.runtime._running=previous

    def test_new_process_reads_actual_character_file_and_resumes_real_native_pages(self):
        saved=self.saved_world()
        script='''
import os,sys,json,time
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QObject
app=QGuiApplication([])
from backend import game_engine_host as h,game_engine_mmo as m,game_engine_character_creation as a
from backend.game_engine_local_characters import CharacterStore
from backend.game_engine_adapter_streaming import update_world,load_world
m.DEFAULT_STASH_PATH=Path(os.environ['XDG_STATE_HOME'])/'child-stash.json'
a.STATE_PATH=Path(os.environ['XDG_STATE_HOME'])/'child-appearance.json'
h._RUNTIME.shutdown()
r=h.GameEngineRuntime();h._RUNTIME=r
r._state_store=CharacterStore(Path(sys.argv[1]));r._persistence_key=sys.argv[2];r._local_character_id=sys.argv[2]
result=r.load_state();assert 'error' not in result,result.get('error')
b=QObject();deadline=time.monotonic()+12
while time.monotonic()<deadline:
 update_world(b);s=getattr(b,'_engine_world_stream',None)
 if s and s.pages and s.pending is None:break
 time.sleep(.005)
else:raise AssertionError('Native saved map did not resume')
assert r._x[0]==-6 and r._y[0]==100.65 and r._z[0]==28
p=r._active_pet_locked();assert p['xp']==97 and p['x']==-7 and p['y']==100 and p['z']==29
assert sum(row['id']==p['id'] for row in r._nature.rows)==1
receipt={'map':s.config['map'],'native_pages':len(s.pages),'same_saved_animal':True,'progress':p['xp']}
load_world(b,'');r.shutdown();print(json.dumps(receipt))
'''
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.root),self.first],
                              cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        proof=json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(proof,{'map':'Test','native_pages':1,'same_saved_animal':True,'progress':97})


if __name__=='__main__':unittest.main()
