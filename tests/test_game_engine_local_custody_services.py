"""Actual runtime/local character adapter without opening a GPU or Lua host."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance,game_engine_items as items
from backend.game_engine_local_characters import LocalCharacters
from backend.game_engine_local_custody import LocalCustodyStore
from backend.game_engine_local_custody_services import SharedLocalServicesMixin

APP=QCoreApplication.instance() or QCoreApplication([])


class SharedServices(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)/'characters'
        env=patch.dict(os.environ,{key:self.directory.name+'/'+key for key in ('XDG_STATE_HOME','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME')})
        env.start();self.addCleanup(env.stop)
        for module,attribute,value in ((mmo,'DEFAULT_STASH_PATH',Path(self.directory.name)/'stash.json'),
                                        (appearance,'STATE_PATH',Path(self.directory.name)/'appearance.json')):
            mocked=patch.object(module,attribute,value);mocked.start();self.addCleanup(mocked.stop)
        from backend.game_engine_host import GameEngineRuntime
        if issubclass(GameEngineRuntime,SharedLocalServicesMixin):runtime_class=GameEngineRuntime
        else:
            class SharedRuntime(SharedLocalServicesMixin,GameEngineRuntime):pass
            runtime_class=SharedRuntime
        self.runtime=runtime_class();self.addCleanup(self.runtime.shutdown)
        self.session=LocalCharacters(root=self.root,runtime=self.runtime);self.addCleanup(self.session.close)
        self.assertTrue(self.session.open(),self.session.error)
        self.first=self.session.rows[0]['id']
        self.assertTrue(self.session.create('Second Hero',appearance.catalog()['defaults']),self.session.error)
        self.second=self.session.rows[1]['id']
        self.assertTrue(self.session.enter(self.first),self.session.error)
        self.bind(self.first)

    def bind(self,character):
        self.runtime._local_custody_store=LocalCustodyStore(self.root,session_lock=self.session._session_lock)
        self.runtime._local_character_id=character
        self.runtime._local_custody_cache=None

    def switch(self,character):
        self.assertTrue(self.session.logout(),self.session.error)
        self.assertTrue(self.session.enter(character),self.session.error)
        self.bind(character)

    def open(self,kind):
        self.runtime._service_command_locked({'op':kind+'Open'})

    def command(self,op,**fields):
        return self.runtime._shared_service_command_locked(dict(op=op,kind='service',session=self.runtime._service_generation,**fields))

    def item(self):
        return next(i for i in self.runtime._item_instances.values() if i['owner_id']=='player' and
                    i['location']=='INVENTORY' and i['definition_id']=='item.sea_salt')

    def view(self):
        value=self.runtime._services_view_locked()
        # Root may already have installed the final overlay hook.
        return value if 'shared_custody' in value else self.runtime._shared_services_view_locked(value)

    def test_cross_local_character_mail_uses_real_items_and_display_names_after_actual_character_switch(self):
        item=self.item();key=item['instance_id'];quantity=item['quantity']
        self.open('Mail')
        emitted=self.command('MailSend',target='Second Hero',subject='Parcel',body='Local message',item=key,money=123,custody_sequence=1)
        self.assertEqual(emitted[0]['event'],'MAIL_SEND_SUCCESS')
        self.assertNotIn(key,self.runtime._item_instances)
        self.switch(self.second);self.open('Mail')
        row=next(m for m in self.view()['mail']['rows'] if isinstance(m['id'],str))
        self.assertEqual(row['sender_name'],self.session.rows[0]['name'])
        self.assertEqual(row['attachment']['quantity'],quantity)
        self.command('MailItem',id=row['id'],custody_sequence=1)
        self.command('MailMoney',id=row['id'],custody_sequence=2)
        held=self.runtime._local_custody_store.snapshot()['shared']['escrow']
        self.assertEqual(held,{})
        self.assertTrue(any(i.get('custody_origin',{}).get('character')==self.first for i in self.runtime._item_instances.values()))

    def test_public_client_service_route_commits_shared_mail_and_ordinary_save_advances_revision(self):
        self.open('Mail');key=self.item()['instance_id']
        result=self.runtime.client_control(json.dumps(dict(kind='service',op='MailSend',
            session=self.runtime._service_generation,target='Second Hero',subject='Public route',
            item=key,money=11,custody_sequence=1)))
        self.assertNotIn('error',result)
        self.assertTrue(any(e['event']=='MAIL_SEND_SUCCESS' for e in result['client_events']))
        committed=self.runtime._local_custody_store.snapshot()['characters'][self.first]['revision']
        self.assertEqual(self.runtime._state_store.revision,committed)
        self.runtime.save_state(snapshot=False)
        saved=self.runtime._local_custody_store.snapshot()['characters'][self.first]['revision']
        self.assertGreater(saved,committed)
        self.assertNotIn(key,self.runtime._item_instances)
        self.command('MailSend',target='Second Hero',subject='Next actual command',custody_sequence=2)
        self.assertGreater(self.runtime._local_custody_store.snapshot()['characters'][self.first]['revision'],saved)

    def test_shared_collection_preserves_active_position_combat_cast_form_and_local_services(self):
        self.open('Mail');self.command('MailSend',target='Second Hero',subject='Parcel',item=self.item()['instance_id'])
        self.switch(self.second);self.open('Mail')
        row=next(m for m in self.view()['mail']['rows'] if isinstance(m['id'],str))
        self.runtime._ensure_combat_actors_locked()
        self.runtime._x[0]=37.
        self.assertNotIn('error',self.runtime.activate_ability('ability.tide_mend'))
        self.assertIsNotNone(self.runtime._spell_state['pending'])
        before={key:copy.deepcopy(getattr(self.runtime,key)) for key in ('_combat_state','_spell_state','_services','_local_client')}
        with patch.object(self.runtime,'load_state',side_effect=AssertionError('ordinary mail cannot full-load')):
            self.command('MailItem',id=row['id'])
        self.assertEqual(self.runtime._x[0],37.)
        for key,value in before.items():self.assertEqual(getattr(self.runtime,key),value,key)

    def test_shared_market_merges_actual_npc_rows_and_shows_other_characters_real_posting(self):
        self.open('Auction')
        self.command('AuctionStart',item=self.item()['instance_id'],min_bid=100,buyout=500,duration=120)
        self.switch(self.second);self.open('Auction')
        view=self.view();rows=view['auction']['lists'][0]['rows']
        shared=next(a for a in rows if isinstance(a['id'],str))
        self.assertEqual(shared['owner_name'],self.session.rows[0]['name'])
        self.assertTrue(any(isinstance(a['id'],int) for a in rows))
        self.command('AuctionBid',id=shared['id'],amount=500)
        self.assertFalse(any(isinstance(a['id'],str) for a in self.view()['auction']['lists'][0]['rows']))
        self.assertTrue(any(m['attachment'] for m in self.view()['mail']['rows'] if isinstance(m['id'],str)))

    def test_shared_guild_invitation_is_real_offline_offer_and_acceptance_updates_same_roster(self):
        self.runtime._economy_state['wallet']['gold']=100
        self.command('GuildCreate',name='Gold Goblins')
        self.command('GuildInvite',target='Second Hero')
        self.assertEqual(len(self.view()['guild']['roster']),1)
        self.switch(self.second)
        view=self.view();self.assertIsNone(view['guild'])
        event=view['shared_pending_events'][0]
        self.assertEqual(event['event'],'GUILD_INVITE_REQUEST')
        self.assertEqual(event['args'],[self.session.rows[0]['name'],'Gold Goblins'])
        self.command('GuildAccept')
        roster=self.view()['guild']['roster']
        self.assertEqual(len(roster),2)
        self.assertEqual(sum(member['online'] for member in roster),1)
        self.assertEqual(next(m for m in roster if m['id']=='player')['name'],'Second Hero')

    def test_shared_row_explicit_sequence_replay_never_spends_again(self):
        self.open('Mail')
        request=dict(target='Second Hero',subject='Parcel',item=self.item()['instance_id'],money=123,custody_sequence=1)
        self.command('MailSend',**request)
        wallet=copy.deepcopy(self.runtime._economy_state['wallet'])
        self.command('MailSend',**request)
        self.assertEqual(self.runtime._economy_state['wallet'],wallet)
        with self.assertRaisesRegex(ValueError,'REPLAY_CHANGED'):
            self.command('MailSend',**dict(request,money=124))

    def test_transient_committed_intent_failure_recovers_and_merges_without_failed_rollback(self):
        self.open('Mail');store=self.runtime._local_custody_store
        failed=False
        def fault(stage,name):
            nonlocal failed
            if not failed and (stage,name)==('replaced','shared-custody.pending.json'):
                failed=True;raise OSError('transient fsync boundary')
        store.fault=fault
        key=self.item()['instance_id']
        emitted=self.command('MailSend',target='Second Hero',subject='Parcel',item=key,custody_sequence=1)
        self.assertEqual(emitted[0]['event'],'MAIL_SEND_SUCCESS')
        self.assertNotIn(key,self.runtime._item_instances)
        self.assertFalse(self.runtime._local_custody_blocked)
        self.assertFalse((self.root/'shared-custody.pending.json').exists())

    def test_persistent_commit_failure_pauses_and_blocks_until_forward_recovery(self):
        self.open('Mail');store=self.runtime._local_custody_store
        def fault(stage,name):
            if (stage,name)==('before_write',self.first+'.json'):raise OSError('disk stays unavailable')
        store.fault=fault
        key=self.item()['instance_id']
        with self.assertRaisesRegex(ValueError,'RECOVERY_REQUIRED'):
            self.command('MailSend',target='Second Hero',subject='Parcel',item=key,custody_sequence=1)
        self.assertTrue(self.runtime._local_custody_blocked)
        self.assertTrue((self.root/'shared-custody.pending.json').exists())
        store.fault=None
        self.command('MailSend',target='Second Hero',subject='Parcel',item=key,custody_sequence=1)
        self.assertNotIn(key,self.runtime._item_instances)
        self.assertFalse(self.runtime._local_custody_blocked)

    def test_dead_or_closed_session_rejects_shared_mail_before_any_transfer(self):
        self.open('Mail');key=self.item()['instance_id']
        self.runtime._ensure_combat_actors_locked();self.runtime._combat_state['actors']['player']['alive']=False
        with self.assertRaisesRegex(ValueError,'PLAYER_DEFEATED'):
            self.command('MailSend',target='Second Hero',subject='Parcel',item=key)
        self.assertIn(key,self.runtime._item_instances)

    def test_npc_and_self_mail_keep_existing_original_local_service_path(self):
        self.open('Mail')
        self.assertIsNone(self.command('MailSend',target='player',subject='Self'))
        npc=next(p['name'] for p in self.runtime._local_people_locked() if p['id']!='player')
        self.assertIsNone(self.command('MailSend',target=npc,subject='NPC'))

    def test_repeated_shared_view_projection_has_no_disk_reads_or_save_events(self):
        self.runtime.client_control(json.dumps(dict(kind='local',op='Chat',chat_type='WHISPER',target='Second Hero',text='Cached pending delivery')))
        self.switch(self.second)
        self.assertEqual(len(self.view()['shared_pending_events']),1)
        self.view();store=self.runtime._local_custody_store
        before=copy.deepcopy(self.runtime._event_journal)
        with patch.object(store,'snapshot',side_effect=AssertionError('no profile IO during cached paints')),\
             patch.object(store,'roster',side_effect=AssertionError('no roster IO during cached paints')),\
             patch.object(self.runtime,'save_state',side_effect=AssertionError('no save during cached paints')):
            for _ in range(20):self.view()
        self.assertEqual(self.runtime._event_journal,before)

    def test_public_shared_guild_chat_delivers_once_on_actual_member_login_and_acknowledges_durably(self):
        self.runtime._economy_state['wallet']['gold']=100
        self.command('GuildCreate',name='Gold Goblins');self.command('GuildInvite',target='Second Hero')
        self.switch(self.second);self.command('GuildAccept')
        result=self.runtime.client_control(json.dumps(dict(kind='local',op='Chat',chat_type='GUILD',text='Actual guild chat')))
        self.assertNotIn('error',result)
        self.assertEqual(result['client_events'][0]['event'],'CHAT_MSG_GUILD')
        self.assertFalse(any(e.get('ack_id') for e in self.view()['shared_pending_events']))
        self.switch(self.first)
        pending=self.view()['shared_pending_events'];self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['event'],'CHAT_MSG_GUILD')
        self.assertEqual(pending[0]['args'][:2],['Actual guild chat','Second Hero'])
        ack=dict(kind='local',op='SharedChatAck',ids=[pending[0]['ack_id']])
        result=self.runtime.client_control(json.dumps(ack));self.assertNotIn('error',result)
        self.assertEqual(self.view()['shared_pending_events'],[])
        files={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        result=self.runtime.client_control(json.dumps(ack));self.assertNotIn('error',result)
        self.assertEqual(files,{p.name:p.read_bytes() for p in self.root.glob('*.json')})
        self.switch(self.second);self.switch(self.first)
        self.assertEqual(self.view()['shared_pending_events'],[])

    def test_shared_whisper_replay_does_not_repeat_sender_echo_or_recipient_delivery(self):
        request=dict(kind='local',op='Chat',chat_type='WHISPER',target='Second Hero',text='Actual whisper',custody_sequence=1)
        result=self.runtime.client_control(json.dumps(request));self.assertNotIn('error',result)
        self.assertEqual(result['client_events'][0]['event'],'CHAT_MSG_WHISPER_INFORM')
        self.assertEqual(result['client_events'][0]['args'][1],'Second Hero')
        self.assertNotIn('client_events',self.runtime.client_control(json.dumps(request)))
        result=self.runtime.client_control(json.dumps(dict(request,text='Changed replay')))
        self.assertIn('REPLAY_CHANGED',result['error'])
        self.switch(self.second)
        pending=self.view()['shared_pending_events'];self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['event'],'CHAT_MSG_WHISPER')
        self.assertEqual(pending[0]['args'][0],'Actual whisper')

    def test_shared_officer_chat_rejects_member_without_rank_send_right(self):
        self.runtime._economy_state['wallet']['gold']=100
        self.command('GuildCreate',name='Gold Goblins');self.command('GuildInvite',target='Second Hero')
        self.switch(self.second);self.command('GuildAccept')
        result=self.runtime.client_control(json.dumps(dict(kind='local',op='Chat',chat_type='OFFICER',text='Unpermitted officer chat')))
        self.assertEqual(result['error'],'GUILD_PERMISSION_DENIED')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['shared']['chat'],{})

    def test_qt_publication_presents_getters_before_one_invite_event_per_lua_epoch(self):
        self.runtime._economy_state['wallet']['gold']=100
        self.command('GuildCreate',name='Gold Goblins');self.command('GuildInvite',target='Second Hero')
        self.switch(self.second)
        from backend.game_engine_presentation import Presentation
        with patch('backend.game_engine_presentation.library',return_value=None):presentation=Presentation(device=False)
        self.addCleanup(presentation.close)
        class PublishedLua:
            def __init__(self):self.calls=[]
            def evaluate(self,source):return [0]
            def publish(self,*args,**kwargs):self.calls.append(('getters',kwargs))
            def event(self,name,*args):self.calls.append((name,args))
        snapshot=self.runtime.snapshot();first=PublishedLua()
        for _ in range(3):presentation._publish_full_ui(first,snapshot,{})
        self.assertEqual(sum(c[0]=='GUILD_INVITE_REQUEST' for c in first.calls),1)
        self.assertEqual(first.calls[0][0],'getters')
        self.assertEqual(first.calls[1],('GUILD_INVITE_REQUEST',(self.session.rows[0]['name'],'Gold Goblins')))
        fresh=PublishedLua();presentation._publish_full_ui(fresh,snapshot,{})
        self.assertEqual(sum(c[0]=='GUILD_INVITE_REQUEST' for c in fresh.calls),1)

    def prepare_history_only_first_character(self):
        request=dict(kind='local',op='Chat',chat_type='WHISPER',target='Second Hero',text='Delivered before deletion')
        self.assertNotIn('error',self.runtime.client_control(json.dumps(request)))
        self.switch(self.second)
        ids=[e['ack_id'] for e in self.view()['shared_pending_events'] if e.get('ack_id')]
        self.assertNotIn('error',self.runtime.client_control(json.dumps(dict(kind='local',op='SharedChatAck',ids=ids))))
        self.assertTrue(self.session.logout(),self.session.error)
        return next(r['name'] for r in self.session.rows if r['id']==self.first)

    def test_actual_character_selection_can_delete_completed_history_without_resurrecting_any_profile(self):
        confirmation=self.prepare_history_only_first_character()
        self.assertTrue(self.session._custody.can_delete(self.first,include_history=False)['allowed'])
        self.assertTrue(self.session.delete(self.first,confirmation),self.session.error)
        self.assertEqual([r['id'] for r in self.session.rows],[self.second])
        self.assertFalse((self.root/(self.first+'.json')).exists())
        self.assertIn(self.first,self.session._custody.snapshot()['shared']['retired'])
        self.assertTrue(self.session.enter(self.second),self.session.error)
        self.assertFalse((self.root/(self.first+'.json')).exists())

    def test_actual_character_delete_recovers_post_journal_clear_uncertainty_and_updates_visible_rows(self):
        confirmation=self.prepare_history_only_first_character()
        store=self.session._custody;failed=False
        def fault(stage,name):
            nonlocal failed
            if not failed and (stage,name)==('journal_removed','shared-custody.pending.json'):
                failed=True;raise OSError('uncertain directory durability after clear')
        store.fault=fault
        self.assertTrue(self.session.delete(self.first,confirmation),self.session.error)
        self.assertTrue(failed)
        self.assertEqual([r['id'] for r in self.session.rows],[self.second])
        self.assertFalse((self.root/(self.first+'.json')).exists())
        self.assertFalse((self.root/'shared-custody.pending.json').exists())
        self.assertTrue(self.session.enter(self.second),self.session.error)

    def test_public_shared_service_precommit_disk_failures_return_error_without_any_custody_transfer(self):
        self.open('Mail');key=self.item()['instance_id']
        request=json.dumps(dict(kind='service',op='MailSend',session=self.runtime._service_generation,
            target='Second Hero',subject='Uncommitted parcel',item=key,money=100,custody_sequence=1))
        wallet=copy.deepcopy(self.runtime._economy_state['wallet'])
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('checkpoint unavailable')):
            result=self.runtime.client_control(request)
        self.assertEqual(result['error'],'LOCAL_CUSTODY_SAVE_FAILED')
        self.assertIn(key,self.runtime._item_instances)
        self.assertEqual(self.runtime._economy_state['wallet'],wallet)
        self.assertFalse((self.root/'shared-custody.pending.json').exists())
        store=self.runtime._local_custody_store
        def fault(stage,name):
            if (stage,name)==('before_write','shared-custody.pending.json'):raise OSError('intent unavailable')
        store.fault=fault
        result=self.runtime.client_control(request)
        self.assertEqual(result['error'],'LOCAL_CUSTODY_SAVE_FAILED')
        self.assertIn(key,self.runtime._item_instances)
        self.assertEqual(self.runtime._economy_state['wallet'],wallet)
        self.assertFalse((self.root/'shared-custody.pending.json').exists())
        self.assertEqual(store.snapshot()['shared']['mail'],{})

    def test_public_repeated_blocked_recovery_returns_error_and_keeps_committed_custody_pending(self):
        self.open('Mail');key=self.item()['instance_id'];store=self.runtime._local_custody_store
        def fault(stage,name):
            if (stage,name)==('before_write',self.first+'.json'):raise OSError('canonical disk stays unavailable')
        store.fault=fault
        request=json.dumps(dict(kind='service',op='MailSend',session=self.runtime._service_generation,
            target='Second Hero',subject='Committed parcel',item=key,custody_sequence=1))
        for _ in range(2):
            result=self.runtime.client_control(request)
            self.assertEqual(result['error'],'LOCAL_CUSTODY_RECOVERY_REQUIRED')
            self.assertTrue(self.runtime._local_custody_recovery_blocked)
            self.assertTrue((self.root/'shared-custody.pending.json').exists())
        store.fault=None
        self.assertNotIn('error',self.runtime.client_control(request))
        self.assertNotIn(key,self.runtime._item_instances)
        self.assertEqual(len(store.snapshot()['shared']['mail']),1)

    def test_actual_mail_collection_relogin_split_merge_resend_preserves_units_and_never_replays_consumed_lineage(self):
        source=self.item();source['quantity']=3
        self.runtime._inventory=items.inventory_counts(list(self.runtime._item_instances.values()))
        self.open('Mail');self.command('MailSend',target='Second Hero',subject='Three actual units',item=source['instance_id'],custody_sequence=1)
        self.switch(self.second);self.open('Mail')
        native=self.item();native_id=native['instance_id'];native_slot=native['slot_index']
        mail=next(m for m in self.view()['mail']['rows'] if isinstance(m['id'],str))
        self.command('MailItem',id=mail['id'],custody_sequence=1)
        received=next(i for i in self.runtime._item_instances.values() if i.get('custody_origin',{}).get('character')==self.first)
        received_id=received['instance_id'];lineage=copy.deepcopy(received['custody_origin'])
        self.switch(self.second);self.open('Mail')
        received=self.runtime._item_instances[received_id]
        self.assertEqual(received['custody_origin'],lineage)
        physical={k:copy.deepcopy(received.get(k)) for k in ('condition','gear','affixes','enchantments','bound_to','craft_quality')}
        used={i.get('slot_index') for i in self.runtime._item_instances.values() if i['location']=='INVENTORY' and i['owner_id']=='player'}
        free=min(set(range(items.MAX_INVENTORY_SLOTS))-used)
        result=self.runtime.transfer_inventory_stack(received_id,free,1);self.assertNotIn('error',result)
        child=next(i for i in self.runtime._item_instances.values() if i['location']=='INVENTORY' and i['owner_id']=='player' and i['slot_index']==free)
        child_id=child['instance_id']
        self.assertEqual(child['custody_origin'],{'character':self.second,'instance':child_id})
        self.assertEqual(received['custody_origin'],lineage)
        self.assertEqual(physical,{k:copy.deepcopy(child.get(k)) for k in physical})
        self.assertEqual(self.runtime._inventory['item.sea_salt'],4)
        self.assertNotIn('error',self.runtime.transfer_inventory_stack(child_id,received['slot_index'],0))
        self.assertNotIn(child_id,self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances[received_id]['custody_origin'],lineage)
        self.assertNotIn('error',self.runtime.transfer_inventory_stack(received_id,native_slot,0))
        self.assertNotIn(received_id,self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances[native_id]['quantity'],4)
        self.command('MailItem',id=mail['id'],custody_sequence=1)
        self.assertNotIn(received_id,self.runtime._item_instances)
        self.assertEqual(self.runtime._inventory['item.sea_salt'],4)
        self.command('MailSend',target=self.first,subject='Four actual units',item=native_id,custody_sequence=2)
        self.assertEqual(self.runtime._inventory.get('item.sea_salt',0),0)
        shared=self.runtime._local_custody_store.snapshot()['shared']
        self.assertEqual([i['quantity'] for i in shared['escrow'].values()],[4])
        self.switch(self.first);self.open('Mail')
        returned=next(m for m in self.view()['mail']['rows'] if m['attachment'] and isinstance(m['id'],str))
        self.command('MailItem',id=returned['id'],custody_sequence=2)
        self.assertEqual(self.runtime._inventory['item.sea_salt'],4)
        self.switch(self.first)
        self.assertEqual(self.runtime._inventory['item.sea_salt'],4)
        self.assertEqual(self.item()['custody_origin'],{'character':self.second,'instance':native_id})
        snapshot=self.runtime._local_custody_store.snapshot()
        self.assertEqual(snapshot['shared']['escrow'],{})
        self.assertEqual(sum(e['payload']['inventory'].get('item.sea_salt',0) for e in snapshot['characters'].values()),4)

    def test_actual_split_escrow_relogin_split_allocates_nonreusable_physical_identity(self):
        source=self.item();source['quantity']=3
        self.runtime._inventory=items.inventory_counts(list(self.runtime._item_instances.values()))
        used={i.get('slot_index') for i in self.runtime._item_instances.values() if i['location']=='INVENTORY' and i['owner_id']=='player'}
        free=min(set(range(items.MAX_INVENTORY_SLOTS))-used)
        self.assertNotIn('error',self.runtime.transfer_inventory_stack(source['instance_id'],free,1))
        first_child=next(i for i in self.runtime._item_instances.values() if i['location']=='INVENTORY' and i['owner_id']=='player' and i['slot_index']==free)
        first_id=first_child['instance_id']
        self.open('Mail')
        request=dict(target='Second Hero',subject='Escrowed split',item=first_id,custody_sequence=1)
        self.command('MailSend',**request)
        self.switch(self.first);self.open('Mail')
        self.assertNotIn(first_id,self.runtime._item_instances)
        self.assertNotIn('error',self.runtime.transfer_inventory_stack(source['instance_id'],free,1))
        second_child=next(i for i in self.runtime._item_instances.values() if i['location']=='INVENTORY' and i['owner_id']=='player' and i['slot_index']==free)
        self.assertNotEqual(first_id,second_child['instance_id'])
        self.assertLessEqual(len(second_child['instance_id']),64)
        self.assertEqual(second_child['custody_origin'],{'character':self.first,'instance':second_child['instance_id']})
        snapshot=self.runtime._local_custody_store.snapshot()
        held=next(iter(snapshot['shared']['escrow'].values()))
        self.assertEqual(held['instance_id'],first_id)
        total=sum(e['payload']['inventory'].get('item.sea_salt',0) for e in snapshot['characters'].values())+sum(i['quantity'] for i in snapshot['shared']['escrow'].values() if i['definition_id']=='item.sea_salt')
        self.assertEqual(total,4)
        self.command('MailSend',**request)
        self.assertNotIn(first_id,self.runtime._item_instances)
        self.assertEqual(self.runtime._inventory['item.sea_salt'],2)
        self.assertEqual(len(self.runtime._local_custody_store.snapshot()['shared']['escrow']),1)


class CustodyOriginNormalization(unittest.TestCase):
    def test_normalization_retains_exact_bounded_origin_binding_and_gear_without_aliasing(self):
        catalog=items.catalog_from_content()
        raw=items.make_instance(catalog,'actual-weapon','item.rusted_hatchet')
        raw.update(custody_origin={'character':'a'*32,'instance':'actual-original'},bound_to='player',condition=.75)
        normalized=items.normalize_instance(catalog,raw)
        self.assertEqual(normalized['custody_origin'],raw['custody_origin'])
        self.assertEqual(normalized['gear'],raw['gear'])
        self.assertEqual(normalized['bound_to'],'player');self.assertEqual(normalized['condition'],.75)
        normalized['custody_origin']['instance']='other'
        self.assertEqual(raw['custody_origin']['instance'],'actual-original')
        for origin in (None,{}, {'character':'A'*32,'instance':'item'}, {'character':'a'*32,'instance':''},
                       {'character':'a'*32,'instance':'x'*65}, {'character':'a'*32,'instance':'bad\nvalue'},
                       {'character':'a'*32,'instance':True}, {'character':'a'*32,'instance':'item','extra':0}):
            with self.subTest(origin=origin),self.assertRaisesRegex(ValueError,'ORIGIN_INVALID'):
                items.normalize_instance(catalog,dict(raw,custody_origin=origin))

    def test_stack_compatibility_allows_distinct_lineage_but_preserves_binding_condition_and_gear(self):
        from backend.game_engine_host import GameEngineRuntime
        catalog=items.catalog_from_content()
        left=items.make_instance(catalog,'actual-left','item.sea_salt',quantity=3)
        right=copy.deepcopy(left);right.update(instance_id='actual-right',quantity=1,custody_origin={'character':'b'*32,'instance':'other'})
        self.assertTrue(GameEngineRuntime._stacks_compatible(left,right))
        for field,value in (('bound_to','player'),('condition',.5),('gear',{'actual_enchantment':1}),('affixes',[{'id':'other'}])):
            with self.subTest(field=field):
                changed=copy.deepcopy(right);changed[field]=value
                self.assertFalse(GameEngineRuntime._stacks_compatible(left,changed))


if __name__=='__main__':unittest.main()
