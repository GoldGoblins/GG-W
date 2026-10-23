"""Durable saved-character groups; no offline world actors or invented loot."""
import copy
import json
import unittest
from unittest.mock import patch

from backend.game_engine_local_custody import LocalCustodyStore,RecoveryRequired,GROUP_CHAT_SECONDS
from backend.game_engine_local_characters import CharacterStore,atomic
import test_game_engine_local_custody as custody_fixture
import test_game_engine_local_custody_services as service_fixture
A,B,C,ProcessCrash=custody_fixture.A,custody_fixture.B,custody_fixture.C,custody_fixture.ProcessCrash


class Groups(unittest.TestCase):
    setUp=custody_fixture.Custody.setUp
    seed=custody_fixture.Custody.seed
    files=custody_fixture.Custody.files
    payload=custody_fixture.Custody.payload

    def action(self,owner,sequence,op,**fields):
        return self.store.group_action(owner,sequence,dict(op=op,**fields),now=100)

    def join(self):
        self.action(A,1,'GroupInvite',target=B)
        self.action(B,1,'GroupAccept')

    def group(self):return next(iter(self.store.snapshot()['shared']['groups'].values()))

    def test_offer_is_persisted_without_forcing_membership_and_only_recipient_can_accept(self):
        before=self.store.snapshot()['characters']
        self.action(A,1,'GroupInvite',target=B)
        value=LocalCustodyStore(self.root).snapshot()
        self.assertEqual(value['characters'],before)
        self.assertEqual(self.group()['members'],[A])
        self.assertIn(B,value['shared']['group_invites'])
        with self.assertRaisesRegex(ValueError,'INVITATION_EXPIRED'):self.action(C,1,'GroupAccept')
        self.action(B,1,'GroupAccept')
        self.assertEqual(self.group()['members'],[A,B])
        self.assertFalse(self.store.snapshot()['shared']['group_invites'])

    def test_offer_decline_and_expiry_remove_singleton_placeholder(self):
        self.action(A,1,'GroupInvite',target=B);self.action(B,1,'GroupDecline')
        self.assertEqual(self.store.snapshot()['shared']['groups'],{})
        self.action(A,2,'GroupInvite',target=B)
        with self.assertRaisesRegex(ValueError,'INVITATION_EXPIRED'):
            self.store.group_action(B,2,dict(op='GroupAccept'),now=160)
        self.store.settle(C,1,now=160)
        self.assertEqual(self.store.snapshot()['shared']['groups'],{})

    def test_inviter_can_leave_and_cancel_unaccepted_offer_without_dangling_group(self):
        self.action(A,1,'GroupInvite',target=B);self.action(A,2,'GroupLeave')
        value=self.store.snapshot()['shared']
        self.assertEqual(value['groups'],{});self.assertEqual(value['group_invites'],{})
        self.assertTrue(self.store.can_delete(B,include_history=False)['allowed'])

    def test_exact_replay_and_changed_request_cannot_invite_or_join_twice(self):
        self.join();before=self.files()
        self.assertTrue(self.action(B,1,'GroupAccept')['replayed'])
        self.assertTrue(self.action(A,1,'GroupInvite',target=B)['replayed'])
        self.assertEqual(before,self.files())
        with self.assertRaisesRegex(ValueError,'REPLAY_CHANGED'):self.action(A,1,'GroupInvite',target=C)

    def test_nonleader_cannot_invite_kick_promote_or_change_raid(self):
        self.join();before=self.files()
        for op,fields in [('GroupInvite',dict(target=C)),('GroupKick',dict(target=A)),('GroupLeader',dict(target=B)),('GroupRaid',{})]:
            with self.subTest(op=op),self.assertRaisesRegex(ValueError,'LEADER_REQUIRED'):self.action(B,2,op,**fields)
        self.assertEqual(before,self.files())

    def test_leave_preserves_other_members_transfers_leadership_and_reloads(self):
        self.join();self.action(A,2,'GroupInvite',target=C);self.action(C,1,'GroupAccept')
        self.action(A,3,'GroupLeave')
        self.assertEqual(self.group()['members'],[B,C]);self.assertEqual(self.group()['leader'],B)
        self.action(B,2,'GroupKick',target=C)
        self.assertEqual(LocalCustodyStore(self.root).snapshot()['shared']['groups'],{})

    def test_party_capacity_uses_only_real_profiles_and_raid_can_accept_sixth(self):
        roster=self.store.roster();template=self.payload(C)
        others=[f'{n:032x}' for n in (4,5,6)]
        for number,key in enumerate(others):
            CharacterStore(self.root).save(key,copy.deepcopy(template))
            roster.append(dict(id=key,name='Actual '+str(number),selection={},level=1))
        atomic(self.root/'characters.json',dict(schema='gg.local-characters.v1',characters=roster))
        self.join()
        for sequence,member in enumerate([C]+others[:2],2):
            self.action(A,sequence,'GroupInvite',target=member);self.action(member,1,'GroupAccept')
        with self.assertRaisesRegex(ValueError,'GROUP_FULL'):self.action(A,5,'GroupInvite',target=others[2])
        self.action(A,5,'GroupRaid');self.action(A,6,'GroupInvite',target=others[2]);self.action(others[2],1,'GroupAccept')
        self.assertEqual(len(self.group()['members']),6)
        self.assertEqual(self.group()['subgroups'][others[2]],2)
        with self.assertRaisesRegex(ValueError,'SUBGROUP_FULL'):self.action(A,7,'GroupSubgroup',target=others[2],subgroup=1)

    def test_raid_ranks_subgroup_swap_marks_and_leadership_are_bounded(self):
        self.join();self.action(A,2,'GroupRaid');self.action(A,3,'GroupAssistant',target=B,grant=True)
        self.action(A,4,'GroupSubgroup',target=B,subgroup=2)
        self.action(A,5,'GroupSwap',target=A,other_target=B)
        self.assertEqual(self.group()['subgroups'],{A:2,B:1})
        self.action(A,6,'GroupMark',target=A,index=3);self.action(B,2,'GroupMark',target=B,index=3)
        self.assertEqual(self.group()['marks'],{B:3})
        self.action(A,7,'GroupLeader',target=B)
        self.assertEqual(self.group()['leader'],B);self.assertEqual(self.group()['assistants'],[])
        with self.assertRaisesRegex(ValueError,'BOOLEAN'):self.action(B,3,'GroupAssistant',target=A,grant=1)

    def test_original_loot_settings_persist_all_methods_without_awarding_offline_characters(self):
        self.join();before=self.store.snapshot()['characters']
        for sequence,method in enumerate(('freeforall','roundrobin','master','group','needbeforegreed'),2):
            with self.subTest(method=method):
                self.action(A,sequence,'GroupLoot',method=method,master=B,threshold=4)
                restored=LocalCustodyStore(self.root).snapshot()
                group=next(iter(restored['shared']['groups'].values()))
                self.assertEqual((group['loot_method'],group['master'],group['threshold']),(method,B,4))
                self.assertEqual(restored['characters'],before)
        unchanged=self.files()
        for invalid in ('unsupported',None,True):
            with self.subTest(invalid=invalid),self.assertRaisesRegex(ValueError,'LOOT_METHOD_INVALID'):
                self.action(A,7,'GroupLoot',method=invalid)
        with self.assertRaisesRegex(ValueError,'INTEGER'):
            self.action(A,7,'GroupThreshold',threshold=True)
        with self.assertRaisesRegex(ValueError,'LEADER_REQUIRED'):
            self.action(B,2,'GroupLoot',method='master',master=B)
        with self.assertRaisesRegex(ValueError,'REPLAY_CHANGED'):
            self.action(A,6,'GroupLoot',method='group',master=B,threshold=4)
        self.assertEqual(self.files(),unchanged)

    def test_ready_answers_require_explicit_recipient_response_and_timeout_is_not_ready(self):
        self.join();self.action(A,2,'GroupReady')
        self.assertEqual(self.group()['ready']['answers'],{A:True,B:None})
        self.action(B,2,'GroupReadyAnswer',ready=False)
        self.assertEqual(self.group()['ready']['answers'][B],False)
        self.assertTrue(self.group()['ready']['finished'])
        self.action(A,3,'GroupReady');self.store.settle(C,1,now=130)
        self.assertTrue(self.group()['ready']['finished']);self.assertIsNone(self.group()['ready']['answers'][B])
        with self.assertRaisesRegex(ValueError,'NO_READY_CHECK'):self.action(B,3,'GroupReadyAnswer',ready=True)

    def test_party_and_raid_delivery_preserve_conservation_and_ack_only_actual_recipient(self):
        self.join();before=self.store.snapshot()['characters']
        self.store.send_chat(A,2,'PARTY','actual party',now=100)
        after=self.store.snapshot()
        self.assertEqual(before[B],after['characters'][B])
        self.assertEqual(before[A]['payload'],after['characters'][A]['payload'])
        message=after['shared']['chat'][B][0]
        self.assertEqual(message['expires'],100+GROUP_CHAT_SECONDS)
        self.assertTrue(self.store.send_chat(A,2,'PARTY','actual party',now=999)['replayed'])
        with self.assertRaisesRegex(ValueError,'MESSAGE_CHANGED'):self.store.acknowledge_chat(C,1,[message['id']])
        self.store.acknowledge_chat(B,2,[message['id']]);self.assertFalse(self.store.snapshot()['shared']['chat'])
        with self.assertRaisesRegex(ValueError,'RAID_REQUIRED'):self.store.send_chat(A,3,'RAID','raid',now=100)
        self.action(A,3,'GroupRaid');self.store.send_chat(A,4,'RAID','raid',now=100)
        self.assertEqual(self.store.snapshot()['shared']['chat'][B][0]['kind'],'RAID')

    def test_ignore_expiry_and_addon_replay_use_existing_bounded_inbox(self):
        self.join()
        payload=self.payload(B);payload.setdefault('player',{})['client_controls']={'local_client':{'ignores':['Hero 0']}}
        CharacterStore(self.root).save(B,payload)
        sent=self.store.send_chat(A,2,'PARTY','ignored',now=100)
        self.assertEqual(sent['result']['recipients'],[])
        payload['player']['client_controls']['local_client']['ignores']=[];CharacterStore(self.root).save(B,payload)
        self.store.send_chat(A,3,'ADDON','real payload',prefix='REAL',distribution='PARTY',now=100)
        self.assertTrue(self.store.send_chat(A,3,'ADDON','real payload',prefix='REAL',distribution='PARTY',now=100)['replayed'])
        message=self.store.snapshot()['shared']['chat'][B][0]
        self.assertEqual((message['kind'],message['prefix'],message['distribution']),('ADDON','REAL','PARTY'))
        self.store.settle(C,1,now=100+GROUP_CHAT_SECONDS)
        self.assertEqual(self.store.snapshot()['shared']['chat'],{})

    def test_deletion_blocks_pending_offer_membership_and_unacked_chat(self):
        self.action(A,1,'GroupInvite',target=B)
        self.assertIn('GROUP_INVITATION',self.store.can_delete(B,include_history=False)['blockers'])
        self.action(B,1,'GroupAccept')
        self.assertIn('GROUP',self.store.can_delete(B,include_history=False)['blockers'])
        self.store.send_chat(A,2,'PARTY','queued',now=100);self.action(B,2,'GroupLeave')
        self.assertIn('CHAT',self.store.can_delete(B,include_history=False)['blockers'])

    def test_crash_after_durable_intent_recovers_offer_once_without_asset_mutation(self):
        before=self.store.snapshot()['characters']
        def fault(stage,name):
            if stage=='replaced' and name=='shared-custody.pending.json':raise ProcessCrash()
        self.store.fault=fault
        with self.assertRaises(ProcessCrash):self.action(A,1,'GroupInvite',target=B)
        store=LocalCustodyStore(self.root);value=store.snapshot()
        self.assertEqual(value['characters'],before)
        self.assertEqual(len(value['shared']['group_invites']),1)
        self.assertTrue(store.group_action(A,1,dict(op='GroupInvite',target=B),now=100)['replayed'])

    def test_original_npc_group_cannot_become_parallel_shared_membership(self):
        self.action(A,1,'GroupInvite',target=B)
        payload=self.payload(B);payload.setdefault('player',{})['client_controls']={'services':{'group':{'members':['real-npc']}}}
        CharacterStore(self.root).save(B,payload)
        before=self.files()
        with self.assertRaisesRegex(ValueError,'ALREADY_MEMBER'):self.action(B,1,'GroupAccept')
        self.assertEqual(before,self.files())

    def test_party_chat_and_addon_only_deliver_to_actual_raid_subgroup(self):
        self.join();self.action(A,2,'GroupInvite',target=C);self.action(C,1,'GroupAccept')
        self.action(A,3,'GroupRaid');self.action(A,4,'GroupSubgroup',target=C,subgroup=2)
        self.assertEqual(self.store.send_chat(A,5,'PARTY','subgroup',now=100)['result']['recipients'],[B])
        self.assertEqual(self.store.send_chat(A,6,'ADDON',' payload ',prefix='REAL',distribution='PARTY',now=100)['result']['recipients'],[B])
        self.assertEqual(self.store.snapshot()['shared']['chat'][B][1]['text'],' payload ')
        self.assertEqual(self.store.send_chat(A,7,'RAID','all real members',now=100)['result']['recipients'],[B,C])

    def test_original_addon_empty_body_empty_prefix_tabs_and_exact_utf8_bound(self):
        self.join()
        for sequence,prefix,message in [(2,'LOOT_OPENED',''),(3,'','payload'),(4,'REAL',' \tbytes '),(5,'R','x'*2045)]:
            self.store.send_chat(A,sequence,'ADDON',message,prefix=prefix,distribution='PARTY',now=100)
            self.assertEqual(self.store.snapshot()['shared']['chat'][B][-1]['text'],message)
        before=self.files()
        for prefix,message in [('R','x'*2046),('R','é'*1023),('','')]:
            with self.subTest(prefix=prefix,length=len(message)),self.assertRaisesRegex(ValueError,'CHAT_INVALID'):
                self.store.send_chat(A,6,'ADDON',message,prefix=prefix,distribution='PARTY',now=100)
        self.assertEqual(before,self.files())

    def test_actual_saved_ignore_prevents_invitation_without_any_pending_reference(self):
        payload=self.payload(B);payload.setdefault('player',{})['client_controls']={'local_client':{'ignores':['hERO 0']}}
        CharacterStore(self.root).save(B,payload);before=self.files()
        with self.assertRaisesRegex(ValueError,'IGNORES_PLAYER'):self.action(A,1,'GroupInvite',target=B)
        self.assertEqual(before,self.files())

    def test_uncertain_directory_sync_commits_offer_and_replay_recovers_forward(self):
        before=self.store.snapshot()['characters']
        def fault(stage,name):
            if (stage,name)==('directory_synced','shared-custody.pending.json'):raise OSError('uncertain fsync')
        self.store.fault=fault
        with self.assertRaises(RecoveryRequired):self.action(A,1,'GroupInvite',target=B)
        store=LocalCustodyStore(self.root)
        self.assertTrue(store.group_action(A,1,dict(op='GroupInvite',target=B),now=100)['replayed'])
        value=store.snapshot();self.assertEqual(value['characters'],before)
        self.assertEqual(list(value['shared']['group_invites']),[B])


class LocalGroupLifecycle(unittest.TestCase):
    setUp=service_fixture.SharedServices.setUp
    bind=service_fixture.SharedServices.bind
    switch=service_fixture.SharedServices.switch
    view=service_fixture.SharedServices.view
    command=service_fixture.SharedServices.command
    item=service_fixture.SharedServices.item
    open=service_fixture.SharedServices.open

    def public(self,op,**fields):
        result=self.runtime.client_control(json.dumps(dict(kind='service',op=op,session=self.runtime._service_generation,**fields)))
        self.assertNotIn('error',result,result)
        return result

    def join(self):
        self.public('GroupInvite',target='Second Hero')
        self.switch(self.second)
        self.assertTrue(any(e['event']=='PARTY_INVITE_REQUEST' for e in self.view()['shared_pending_events']))
        self.public('GroupAccept')

    def test_real_switch_accept_chat_delivery_ack_leave_and_reload(self):
        live_before=copy.deepcopy(self.runtime._services['group']);self.join()
        view=self.view();self.assertEqual(len(view['group']['roster']),2)
        self.assertEqual(view['group']['roster'][0]['id'],'player')
        other=view['group']['roster'][1];self.assertFalse(other['online']);self.assertNotIn('x',other)
        self.assertEqual(self.runtime._services['group'],live_before)
        sent=self.runtime.client_control(json.dumps(dict(kind='local',op='Chat',chat_type='PARTY',text='Saved party')))
        self.assertNotIn('error',sent);self.assertTrue(any(e['event']=='CHAT_MSG_PARTY' for e in sent['client_events']))
        self.switch(self.first)
        received=next(e for e in self.view()['shared_pending_events'] if e['event']=='CHAT_MSG_PARTY')
        self.assertEqual(received['args'][:2],['Saved party','Second Hero'])
        ack=self.runtime.client_control(json.dumps(dict(kind='local',op='SharedChatAck',ids=[received['ack_id']])))
        self.assertNotIn('error',ack)
        self.public('GroupLeave');self.switch(self.second)
        self.assertEqual(self.view()['group']['members'],[])
        self.assertEqual(self.runtime._local_custody_store.snapshot()['shared']['groups'],{})

    def test_actual_raid_rank_projection_tokens_and_subgroup_routing(self):
        self.join();self.switch(self.first)
        self.public('GroupRaid');self.public('GroupAssistant',target='party1',grant=True)
        self.public('GroupSubgroup',index=2,subgroup=2)
        group=self.view()['group']
        self.assertEqual(group['assistants'],[self.second]);self.assertEqual(group['subgroups'][self.second],2)
        self.public('GroupLeader',target='raid2');self.switch(self.second)
        self.assertEqual(self.view()['group']['leader'],'player')
        self.assertTrue(self.view()['group']['roster'][1]['class_name'])
        self.assertEqual(self.view()['group']['roster'][1]['zone'],'')

    def test_ready_check_is_actual_pending_login_offer_not_fake_offline_answer(self):
        self.join();self.switch(self.first);self.public('GroupReady')
        group=self.view()['group'];self.assertEqual(group['ready'],{'player':True})
        self.assertFalse(group['ready_check']['finished'])
        self.switch(self.second)
        self.assertTrue(any(e['event']=='READY_CHECK' for e in self.view()['shared_pending_events']))
        self.public('GroupReadyAnswer',ready=False)
        self.assertTrue(self.view()['group']['ready_check']['finished'])
        self.assertFalse(self.view()['group']['ready']['player'])

    def test_real_addon_receipt_delivery_survives_switch_and_preserves_payload(self):
        self.join()
        result=self.runtime.client_control(json.dumps(dict(kind='local',op='Addon',prefix='REAL',message='payload',distribution='PARTY')))
        self.assertNotIn('error',result);self.assertEqual(result['client_events'][0]['event'],'CHAT_MSG_ADDON')
        self.switch(self.first)
        event=next(e for e in self.view()['shared_pending_events'] if e['event']=='CHAT_MSG_ADDON')
        self.assertEqual(event['args'],['REAL','payload','PARTY','Second Hero'])

    def test_replayed_shared_leave_and_chat_cannot_fall_into_later_npc_group(self):
        self.join()
        message=dict(kind='local',op='Chat',chat_type='PARTY',text='one delivery',custody_sequence=2)
        result=self.runtime.client_control(json.dumps(message));self.assertNotIn('error',result)
        self.public('GroupLeave',custody_sequence=3)
        # A separate, later real NPC group remains separate from the old receipt.
        self.runtime._services['group']['members']=['npc-wanderer-01']
        before=copy.deepcopy(self.runtime._services['group'])
        self.public('GroupLeave',custody_sequence=3)
        replay=self.runtime.client_control(json.dumps(message));self.assertNotIn('error',replay)
        self.assertEqual(replay.get('client_events',[]),[])
        self.assertEqual(self.runtime._services['group'],before)

    def test_original_optional_null_loot_args_and_casefold_group_tokens(self):
        self.join();self.switch(self.first)
        self.public('GroupLoot',method='freeforall',master=None,threshold=None)
        result=self.public('GroupLeader',target='Party1')
        self.assertEqual([e['event'] for e in result['client_events']],['PARTY_MEMBERS_CHANGED','RAID_ROSTER_UPDATE','PARTY_LEADER_CHANGED'])
        self.assertEqual(self.view()['group']['leader'],self.second)

    def test_exact_group_receipt_replay_preserves_unsaved_actual_item_consumption_and_wallet(self):
        self.public('GroupInvite',target='Second Hero',custody_sequence=1)
        item=self.item();self.assertTrue(self.runtime._consume_inventory_item_locked(item,1))
        self.runtime._economy_state['wallet']['gold']+=7
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        with patch.object(self.runtime,'save_state',side_effect=AssertionError('replay save')):
            self.public('GroupInvite',target='Second Hero',custody_sequence=1)
        self.assertEqual((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state),before)

    def test_reserved_guid_collision_is_deterministically_resolved_without_fabricating_units(self):
        snapshot=dict(roster=[{'id':f'{number:032x}'} for number in (0x12b6,0x152e)])
        first=self.runtime._shared_group_guids_locked(snapshot)
        self.assertEqual(len(set(first.values())),2)
        self.assertTrue(all(0x50000000<=guid<=0x5fffffff for guid in first.values()))
        self.runtime._local_group_guid_cache=None
        self.assertEqual(first,self.runtime._shared_group_guids_locked(snapshot))
        self.assertTrue(all(member not in self.runtime._combat_state.get('actors',{}) for member in first))

    def test_shared_group_retains_real_world_target_marks_via_existing_physical_ledger(self):
        self.join();self.runtime._combat_target_id='npc-wanderer-01'
        self.public('GroupMark',target='target',index=4)
        group=self.view()['group'];physical=self.runtime._service_unit_locked('npc-wanderer-01')
        self.assertEqual(group['mark_guids'][str(physical['guid'])],4)
        self.assertEqual(self.runtime._services['group']['members'],[])
        self.assertEqual(group['marks']['npc-wanderer-01'],4)

    def test_group_leave_remains_available_for_actual_defeated_character(self):
        self.join();self.runtime._ensure_combat_actors_locked()
        self.runtime._combat_state['actors']['player']['alive']=False
        self.public('GroupLeave')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['shared']['groups'],{})

    def test_original_valid_maximum_addon_passes_public_json_control_bound(self):
        self.join()
        result=self.runtime.client_control(json.dumps(dict(kind='local',op='Addon',prefix='R',message='x'*2045,distribution='PARTY')))
        self.assertNotIn('error',result,result)
        self.assertEqual(result['client_events'][0]['args'][1],'x'*2045)

    def test_existing_mail_receipt_replay_preserves_unsaved_live_inventory_and_wallet(self):
        self.open('Mail');self.command('MailSend',target='Second Hero',subject='one receipt',custody_sequence=1)
        self.assertTrue(self.runtime._consume_inventory_item_locked(self.item(),1))
        self.runtime._economy_state['wallet']['gold']+=3
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        with patch.object(self.runtime,'save_state',side_effect=AssertionError('replay checkpoint')):
            self.command('MailSend',target='Second Hero',subject='one receipt',custody_sequence=1)
        self.assertEqual((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state),before)

    def test_evicted_shared_group_receipts_never_fall_into_later_actual_npc_path(self):
        with patch('backend.game_engine_local_custody.MAX_RECEIPTS',2):
            self.join()
            chat=dict(kind='local',op='Chat',chat_type='PARTY',text='bounded receipt',custody_sequence=2)
            self.assertNotIn('error',self.runtime.client_control(json.dumps(chat)))
            self.public('GroupLeave',custody_sequence=3)
            store=self.runtime._local_custody_store
            moment=store.snapshot()['shared']['clock']
            store.settle(self.first,2,now=moment);store.settle(self.first,3,now=moment)
            self.runtime._local_custody_cache=None
            self.runtime._services['group']['members']=['npc-wanderer-01']
            before=copy.deepcopy(self.runtime._services['group'])
            with patch.object(self.runtime,'save_state',side_effect=AssertionError('expired replay save')):
                replay=self.runtime.client_control(json.dumps(chat))
                self.assertEqual(replay.get('error'),'LOCAL_CUSTODY_RECEIPT_EXPIRED')
                leave=self.runtime.client_control(json.dumps(dict(kind='service',op='GroupLeave',custody_sequence=3)))
                self.assertEqual(leave.get('error'),'LOCAL_CUSTODY_RECEIPT_EXPIRED')
            self.assertEqual(self.runtime._services['group'],before)

    def test_group_paint_and_getters_do_not_read_profile_store_or_save(self):
        self.join();self.view();store=self.runtime._local_custody_store
        with (patch.object(store,'snapshot',side_effect=AssertionError('paint snapshot')),
             patch.object(store,'roster',side_effect=AssertionError('paint roster')),
             patch.object(self.runtime,'save_state',side_effect=AssertionError('paint save'))):
            for _ in range(20):self.assertEqual(len(self.view()['group']['roster']),2)


if __name__=='__main__':unittest.main()
