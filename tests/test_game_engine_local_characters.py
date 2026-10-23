"""Real GG runtimes, isolated durable profiles and failure rollback."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QObject,Signal
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
from backend import game_engine_items as items
from backend.game_engine_local_characters import LocalCharacters,CharacterStore,atomic
APP=QGuiApplication.instance() or QGuiApplication([])

class LocalProfiles(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)/'characters'
        env=patch.dict(os.environ,{key:self.directory.name+'/'+key for key in ('XDG_STATE_HOME','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME')});env.start();self.addCleanup(env.stop)
        stash=patch.object(mmo,'DEFAULT_STASH_PATH',Path(self.directory.name)/'stash.json');stash.start();self.addCleanup(stash.stop)
        selection=patch.object(appearance,'STATE_PATH',Path(self.directory.name)/'appearance.json');selection.start();self.addCleanup(selection.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.Runtime=GameEngineRuntime;self.runtime=self.new_runtime()
        self.session=self.new_session(self.runtime)
        self.default=copy.deepcopy(appearance.catalog()['defaults'])

    def new_runtime(self):
        runtime=self.Runtime();self.addCleanup(runtime.shutdown);return runtime
    def new_session(self,runtime):
        session=LocalCharacters(root=self.root,runtime=runtime);self.addCleanup(session.close);return session
    def seeded_progress(self):
        self.runtime._x[0]=37.;self.runtime._z[0]=-42.
        self.runtime._progression['level']=7;self.runtime._progression['xp']=73
        self.runtime._progression['talents']['trailblazer']=4
        self.runtime._economy_state['wallet']['gold']=67890
        item=items.make_instance(self.runtime._item_catalog,'profile-test-salt','item.sea_salt',quantity=6)
        item['slot_index']=60;self.runtime._item_instances[item['instance_id']]=item
        self.runtime._inventory=items.inventory_counts(self.runtime._item_instances.values())

    def test_migrates_existing_progress_once_and_survives_a_new_runtime(self):
        self.seeded_progress();self.assertTrue(self.session.open(),self.session.error)
        identity=self.session.rows[0]['id'];self.assertEqual(self.session.rows[0]['level'],7)
        self.assertTrue(self.session.enter(identity),self.session.error)
        self.assertEqual(self.runtime._progression['xp'],73)
        connected=self.runtime.ui_snapshot()['network']
        self.assertEqual(connected['mode'],'LOCAL_SINGLE_PLAYER')
        self.assertEqual(connected['transport'],'IN_PROCESS')
        self.assertFalse(connected['authoritative_server'])
        self.assertEqual(connected['persistence']['mode'],'LOCAL_FILE')
        self.assertEqual(connected['persistence']['filesystem'],'CONNECTED')
        self.runtime._economy_state['wallet']['gold']=12345
        self.runtime._character_creation=self.default
        self.assertTrue(self.session.logout(),self.session.error)
        self.assertIs(self.runtime._state_store,self.session._base_store)
        self.assertEqual(self.runtime.ui_snapshot()['network']['persistence']['mode'],'MEMORY_ONLY')
        self.session.close();restarted=self.new_session(self.new_runtime())
        self.assertTrue(restarted.open(),restarted.error);self.assertEqual(len(restarted.rows),1)
        self.assertTrue(restarted.enter(identity),restarted.error)
        loaded=restarted.runtime
        self.assertEqual(loaded._economy_state['wallet']['gold'],12345)
        self.assertEqual(loaded._item_instances['profile-test-salt']['quantity'],6)
        self.assertEqual(loaded._progression['talents']['trailblazer'],4)
        self.assertEqual((loaded._x[0],loaded._z[0]),(37.,-42.))
        self.assertEqual(loaded._character_creation,self.default)
        self.assertEqual(loaded.load_state()['persistence_result']['mode'],'LOCAL_FILE')

    def test_fresh_character_does_not_inherit_gold_items_or_appearance(self):
        self.seeded_progress();self.assertTrue(self.session.open());first=self.session.rows[0]['id']
        alternate=dict(self.default,class_id=next(c['id'] for c in appearance.catalog()['classes'] if c.get('ready') and c['id']!=self.default['class_id']))
        self.assertTrue(self.session.create('Ny hjälte',alternate),self.session.error);second=self.session.rows[1]['id']
        self.assertTrue(self.session.enter(second),self.session.error)
        self.assertEqual(self.runtime.ui_snapshot()['player']['name'],'Ny hjälte')
        self.assertEqual(self.runtime._progression['level'],1)
        self.assertNotIn('profile-test-salt',self.runtime._item_instances)
        self.assertNotEqual(self.runtime._economy_state['wallet']['gold'],67890)
        self.assertEqual(self.runtime._character_creation,alternate)
        self.assertTrue(self.session.open());self.assertEqual(self.session.active_id,'')
        self.assertTrue(self.session.enter(first),self.session.error)
        self.assertEqual(self.runtime.ui_snapshot()['player']['name'],'Äventyrare')
        self.assertEqual(self.runtime._economy_state['wallet']['gold'],67890)
        self.assertEqual(self.runtime._progression['level'],7)
        self.assertEqual(self.runtime._character_creation,self.default)

    def test_deleting_last_character_does_not_automatically_recreate_it(self):
        self.assertTrue(self.session.open());row=self.session.rows[0]
        self.assertFalse(self.session.delete(row['id'],'fel namn'))
        self.assertTrue(self.session.enter(row['id']))
        self.assertFalse(self.session.delete(row['id'],row['name']))
        self.assertTrue(self.session.logout());self.assertTrue(self.session.delete(row['id'],row['name']))
        self.assertFalse(self.session.store.path(row['id']).exists())
        self.assertEqual(set(self.root.glob('*.json')),{self.root/'characters.json',self.root/'shared-custody.json'})
        self.session.close()
        restarted=self.new_session(self.new_runtime());self.assertTrue(restarted.open())
        self.assertEqual(restarted.rows,[])

    def test_corrupt_registry_and_saves_are_preserved_without_reset(self):
        self.root.mkdir();registry=self.root/'characters.json';registry.write_text('{broken')
        broken=self.new_session(self.new_runtime());self.assertEqual(broken.phase,'ERROR')
        self.assertFalse(broken.open());self.assertFalse(broken.create('x',self.default))
        self.assertEqual(registry.read_text(),'{broken');registry.unlink()
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id']
        path=self.session.store.path(identity);saved=path.read_bytes()
        self.runtime._x[0]=18.
        value=json.loads(saved);value['payload']['schema']='unknown';path.write_text(json.dumps(value))
        self.assertFalse(self.session.enter(identity));self.assertEqual(self.runtime._x[0],18.)
        self.assertIs(self.runtime._state_store,self.session._base_store)
        self.assertEqual(json.loads(path.read_text())['payload']['schema'],'unknown')

    def test_partial_runtime_restore_failure_rolls_back_player_and_store(self):
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id'];self.runtime._x[0]=21.
        old=self.runtime.load_state;attempts=[]
        def fail_once():
            attempts.append(1)
            if len(attempts)==1:self.runtime._x[0]=999.;raise ValueError('injected partial restore')
            return old()
        with patch.object(self.runtime,'load_state',side_effect=fail_once):
            self.assertFalse(self.session.enter(identity))
        self.assertEqual(self.runtime._x[0],21.);self.assertEqual(self.session.active_id,'')
        self.assertIs(self.runtime._state_store,self.session._base_store)
        self.assertTrue(self.session.enter(identity),self.session.error)

    def test_create_and_delete_registry_failure_restore_existing_files(self):
        self.assertTrue(self.session.open());row=copy.deepcopy(self.session.rows[0]);path=self.session.store.path(row['id']);saved=path.read_bytes()
        with patch.object(self.session,'_registry',side_effect=OSError('injected disk error')):
            self.assertFalse(self.session.create('rollback',self.default))
        def fail_intent(stage,name):
            if stage=='before_write' and name=='shared-custody.pending.json':
                raise OSError('injected disk error')
        with patch.object(self.session._custody,'fault',fail_intent):
            self.assertFalse(self.session.delete(row['id'],row['name']))
        self.assertEqual(self.session.rows,[row]);self.assertEqual(path.read_bytes(),saved)
        self.assertEqual(len(list(self.root.glob('*.json'))),2)

    def test_autosaves_replace_files_and_failed_write_does_not_advance_revision(self):
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id'];self.assertTrue(self.session.enter(identity))
        revision=self.session.store.revision
        with patch('backend.game_engine_local_characters.atomic',side_effect=OSError('injected disk error')):
            self.session._autosave()
        self.assertEqual(self.session.store.revision,revision);self.assertIn('disk error',self.session.error)
        for i in range(12):self.runtime._progression['xp']=i;self.session._autosave()
        self.assertEqual(self.session.store.load(identity)['progression']['xp'],11)
        self.assertEqual(len(list(self.root.glob('*.json'))),2)
        self.assertLess(sum(p.stat().st_size for p in self.root.iterdir()),8*1024*1024)

    def test_links_duplicate_names_and_unknown_models_cannot_overwrite_a_save(self):
        self.assertTrue(self.session.open());row=self.session.rows[0]
        self.assertFalse(self.session.create(row['name'].upper(),self.default))
        self.assertFalse(self.session.create('missing',dict(self.default,class_id='missing')))
        external=Path(self.directory.name)/'external.json';external.write_text('keep')
        link=self.root/('a'*32+'.json');link.symlink_to(external)
        with self.assertRaises(ValueError):self.session.store.load('a'*32)
        with self.assertRaises(ValueError):self.session.store.path('a'*32)
        self.assertEqual(external.read_text(),'keep')

    def test_restart_recovers_a_deletion_interrupted_before_registry_commit(self):
        self.assertTrue(self.session.open());row=self.session.rows[0];path=self.session.store.path(row['id']);saved=path.read_bytes()
        tombstone=self.root/('.deleted-'+row['id']);path.rename(tombstone)
        self.session.close()
        restarted=self.new_session(self.new_runtime());self.assertTrue(restarted.open(),restarted.error)
        self.assertEqual(path.read_bytes(),saved);self.assertFalse(tombstone.exists())
        self.assertTrue(restarted.enter(row['id']),restarted.error)

    def test_two_clients_cannot_overwrite_profiles_and_retry_refreshes_roster(self):
        # Construct the second client before migration to expose a stale roster.
        second=self.new_session(self.new_runtime())
        self.assertTrue(self.session.open());first=self.session.rows[0]['id']
        self.assertTrue(self.session.create('Ny karaktär',self.default),self.session.error)
        self.assertTrue(self.session.enter(first));self.runtime._progression['xp']=123
        paths={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        self.assertFalse(second.open());self.assertIn('annan lokal spelklient',second.error)
        self.assertFalse(second.create('Överskrivning',self.default))
        self.assertEqual(paths,{p.name:p.read_bytes() for p in self.root.glob('*.json')})
        self.session.close()
        self.assertTrue(second.open(),second.error);self.assertEqual(len(second.rows),2)
        self.assertTrue(second.enter(first),second.error)
        self.assertEqual(second.runtime._progression['xp'],123)

    def test_failed_close_retains_session_and_allows_save_retry(self):
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id'];self.assertTrue(self.session.enter(identity))
        with patch('backend.game_engine_local_characters.atomic',side_effect=OSError('disk full')):self.session.close()
        self.assertEqual(self.session.active_id,identity);self.assertFalse(self.session._closed)
        second=self.new_session(self.new_runtime());self.assertFalse(second.open())
        self.session.close();self.assertTrue(second.open(),second.error)

    def test_logout_announces_after_the_closing_stack_returns(self):
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id']
        self.assertTrue(self.session.enter(identity))
        notes=[]
        self.session.changed.connect(lambda:notes.append('changed'))
        self.session.loggedOut.connect(lambda:notes.append('logout'))
        self.assertTrue(self.session.logout())
        self.assertEqual(self.session.phase,'CHARACTERS');self.assertFalse(self.session.active_id)
        self.assertEqual(notes,[])
        APP.processEvents()
        self.assertEqual(notes,['changed','logout'])

    def test_deferred_logout_cannot_reopen_a_new_entry_or_closed_client(self):
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id']
        self.assertTrue(self.session.enter(identity))
        notes=[];self.session.loggedOut.connect(lambda:notes.append('logout'))
        self.assertTrue(self.session.logout());self.assertTrue(self.session.enter(identity))
        APP.processEvents();self.assertEqual(notes,[])
        self.assertEqual(self.session.phase,'WORLD');self.assertEqual(self.session.active_id,identity)
        self.assertTrue(self.session.close());APP.processEvents()
        self.assertEqual(notes,[]);self.assertTrue(self.session._closed)

    def test_original_lua_logout_saves_and_cancel_cannot_bypass_local_selection(self):
        from backend.game_engine_presentation import Presentation
        class Bridge(QObject):
            snapshotPublished=Signal(object)
            def __init__(self,runtime,session):super().__init__();self.runtime=runtime;self._local_characters=session
            def gameEnginePause(self):return json.dumps(self.runtime.pause())
            def gameEngineStart(self):return json.dumps(self.runtime.start())
        self.assertTrue(self.session.open());identity=self.session.rows[0]['id'];self.assertTrue(self.session.enter(identity))
        self.bridge=Bridge(self.runtime,self.session);presentation=Presentation(self.bridge,device=False);self.addCleanup(presentation.close)
        self.runtime._economy_state['wallet']['gold']=6543
        presentation.update(self.runtime.ui_snapshot())
        presentation.lua.execute('Logout()');presentation._ui_requests(presentation.lua.request('requests'))
        self.assertEqual(self.session.phase,'CHARACTERS');self.assertEqual(self.session.active_id,'')
        self.assertEqual(self.session.store.load(identity)['economy_state']['wallet']['gold'],6543)
        presentation.lua.execute('CancelLogout()');presentation._ui_requests(presentation.lua.request('requests'))
        self.assertFalse(self.runtime._running);self.assertEqual(self.session.phase,'CHARACTERS')
        self.assertTrue(self.session.enter(identity))
        with patch('backend.game_engine_local_characters.atomic',side_effect=OSError('disk full')):
            presentation.lua.execute('ForceLogout()');presentation._ui_requests(presentation.lua.request('requests'))
        self.assertEqual(self.session.active_id,identity);self.assertEqual(self.session.phase,'WORLD')
        self.assertIn('disk full',self.session.error)
        self.assertFalse(presentation.errors,presentation.errors)

if __name__=='__main__':unittest.main()
