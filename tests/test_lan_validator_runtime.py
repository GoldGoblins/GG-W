"""Public validator commands use the existing signed LAN pairing transport."""
from pathlib import Path
from contextlib import redirect_stdout
from copy import deepcopy
import io
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend import lan_dag_runtime as runtime,gg_node_store as nodes,gg_consensus_profile as validators
from backend import portable_wallet_vault as vault,terminal_service,terminal_cli as cli,gg_lan_dag as transport


class ValidatorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-validator-runtime-');self.addCleanup(self.temp.cleanup)
        self.unlock=vault.session('disposable validator runtime password');self.unlock.__enter__();self.addCleanup(self.unlock.__exit__,None,None,None)
        self.node_scope=patch.object(nodes,'ROOT',Path(self.temp.name)/'nodes');self.node_scope.start();self.addCleanup(self.node_scope.stop)
        self.val_scope=patch.object(validators,'ROOT',Path(self.temp.name)/'validators');self.val_scope.start();self.addCleanup(self.val_scope.stop)
        self.managers=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for manager in reversed(self.managers):manager.stop()

    def manager(self,name,**options):
        manager=runtime.LanDagRuntime();self.managers.append(manager)
        manager.dispatch('lan.start',{'profile':name,'label':name,'bind_host':'127.0.0.1','port':0,'allow_dag_transactions':True,**options})
        manager._peer._start_gossip=Mock()
        return manager

    def network(self):
        first=self.manager('Windows')
        second=self.manager('Linux',bootstrap=first.dispatch('lan.bootstrap'))
        phone=self.manager('Termux',bootstrap=first.dispatch('lan.bootstrap'),node_role='replica')
        for manager,prefix in ((first,'Win'),(second,'Lin')):
            for index in (1,2):manager.dispatch('lan.validator_create',{'profile':prefix+str(index)})
        second.dispatch('lan.announce')
        body=first.dispatch('lan.session_create',{'enable_dag_transactions':True,'enable_consensus':True,'distribute':True})
        return first,second,phone,body

    def test_public_pairing_gathers_four_members_without_manual_validator_file_transfer(self):
        first,second,phone,body=self.network()
        self.assertEqual(first.dispatch('lan.invite')['body']['schema'],'gg.lan-dag.invite.v5')
        self.assertEqual(body['dag_consensus']['validator_count'],4)
        self.assertEqual(body['dag_consensus']['own_running'],0)
        self.assertFalse(body['lan']['participation']['consensus_validator'])
        self.assertEqual(first.dispatch('lan.bundle'),second._peer._bundle)
        self.assertEqual(first.dispatch('lan.bundle'),phone._peer._bundle)
        self.assertEqual(phone.snapshot()['dag_consensus']['validator_count'],4)
        self.assertEqual(phone.snapshot()['dag_consensus']['profiles'],[])
        self.assertIsNone(body['dag_consensus']['certificate_height'])
        self.assertIsNone(body['dag_consensus']['certified_dag_blocks'])

    def test_candidate_upgrade_rejects_replaced_keys_removed_ads_and_changed_identity(self):
        manager=self.manager('Windows');before=manager.dispatch('lan.invite')
        manager.dispatch('lan.validator_create',{'profile':'First'});first=manager.dispatch('lan.invite')
        manager.dispatch('lan.validator_create',{'profile':'Second'});second=manager.dispatch('lan.invite')
        self.assertTrue(transport._consensus_invite_upgrade(before,first))
        self.assertTrue(transport._consensus_invite_upgrade(first,second))
        self.assertFalse(transport._consensus_invite_upgrade(second,first))
        self.assertFalse(transport._consensus_invite_upgrade(first,before))
        for field,value in (('label','Other'),('host','127.0.0.2'),('port',12345),('nonce','0'*32),
                            ('peer_key','1'*64),('producer_keys',['2'*64,'3'*64]),('node_role','replica'),
                            ('allow_test_tokens',True),('allow_dag_transactions',False),
                            ('consensus_invites',list(reversed(second['body']['consensus_invites'])))):
            altered=deepcopy(second);altered['body'][field]=value
            self.assertFalse(transport._consensus_invite_upgrade(first,altered),field)

    def test_unbound_resume_preserves_advertised_order_before_any_profile_is_unlocked(self):
        first=self.manager('Windows');second=self.manager('Linux',bootstrap=first.dispatch('lan.bootstrap'))
        for name in ('First','Second'):second.dispatch('lan.validator_create',{'profile':name})
        second.dispatch('lan.announce');advertised=second.dispatch('lan.invite')
        second.stop();second.dispatch('lan.resume',{'profile':'Linux'})
        self.assertEqual(second.dispatch('lan.invite'),advertised)
        for name in ('Second','First'):second.dispatch('lan.validator_open',{'profile':name})
        self.assertEqual(second.dispatch('lan.invite'),advertised)
        second.dispatch('lan.announce')
        self.assertEqual(first._peer.candidate_invites()[0],advertised)
        with self.assertRaisesRegex(ValueError,'INVITE_REPLACEMENT'):
            second._peer.advertise_consensus_invites(list(reversed(advertised['body']['consensus_invites'])))

    def test_failed_advertisement_commit_publishes_no_new_validator_key(self):
        manager=self.manager('Windows');before=manager.dispatch('lan.invite')
        with patch.object(manager._peer._profile,'_commit',side_effect=OSError('owned public fixture write failure')):
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):
                manager.dispatch('lan.validator_create',{'profile':'Created'})
        self.assertEqual(manager.dispatch('lan.invite'),before)
        self.assertEqual(manager._validator_profiles,{})

    def test_foreground_cli_reopens_profiles_and_waits_for_signed_anchor(self):
        service=Mock();service.dispatch.return_value={'lan':{'state':'PAIRING'},'lan_setup':{'coordinator':False}}
        with redirect_stdout(io.StringIO()),patch.object(cli,'foreground_session',side_effect=KeyboardInterrupt) as foreground:
            code=cli.main(['--json','--foreground','--command','lan.resume profile=Linux',
                          '--validator-profile','Lin1','--validator-profile','Lin2'],lambda:service)
        self.assertEqual(code,130)
        self.assertEqual([call.args for call in service.dispatch.call_args_list],
                         [('lan.resume',{'profile':'Linux'}),('lan.validator_open',{'profile':'Lin1'}),('lan.validator_open',{'profile':'Lin2'})])
        self.assertEqual(foreground.call_args.kwargs['validator_profiles'],['Lin1','Lin2'])
        service.reset_mock()
        with redirect_stdout(io.StringIO()),patch.object(cli.time,'sleep',side_effect=[None,KeyboardInterrupt]):
            cli_state={'dag_consensus':{'anchor_bound':True},'lan':{'state':'READY'}}
            service.dispatch.return_value=cli_state
            with self.assertRaises(KeyboardInterrupt):cli.foreground_session(service,'lan.resume',{'dag_consensus':{'anchor_bound':False}},json_output=True,validator_profiles=['Lin1','Lin2'])
        self.assertEqual([call.args[0] for call in service.dispatch.call_args_list],['lan.status','lan.validator_start','lan.validator_start'])

    def test_signed_advertisements_survive_lan_resume_without_automatic_native_start(self):
        first,second,phone,body=self.network()
        invite=second.dispatch('lan.invite');anchor=body['dag_consensus']['chain_id']
        second.stop();resumed=second.dispatch('lan.resume',{'profile':'Linux'})
        self.assertEqual(second.dispatch('lan.invite'),invite)
        self.assertEqual(resumed['dag_consensus']['chain_id'],anchor)
        self.assertEqual(resumed['dag_consensus']['own_running'],0)
        self.assertEqual(resumed['dag_consensus']['profiles'],[])
        opened=second.dispatch('lan.validator_open',{'profile':'Lin1'})
        self.assertEqual(len(opened['dag_consensus']['profiles']),1)
        self.assertTrue(second.validator_unlocked('Lin1'))

    def test_profiles_require_durable_owner_and_strict_public_arguments(self):
        manager=runtime.LanDagRuntime();self.managers.append(manager)
        manager.dispatch('lan.start',{'label':'Ephemeral','bind_host':'127.0.0.1','port':0,'allow_dag_transactions':True})
        with self.assertRaisesRegex(ValueError,'DURABLE_LAN_OWNER_REQUIRED'):manager.dispatch('lan.validator_create',{'profile':'Wrong'})
        durable=self.manager('Owned')
        for args in ({'profile':'../escape'},{'profile':'Bad','p2p_port':False},{'profile':'Bad','label':''}):
            with self.assertRaises(ValueError):durable.dispatch('lan.validator_create',args)
        self.assertFalse(Path(validators.ROOT).exists())

    def test_membership_is_explicit_and_incomplete_committee_cannot_bind(self):
        first=self.manager('Windows');self.manager('Linux',bootstrap=first.dispatch('lan.bootstrap'))
        self.manager('Termux',bootstrap=first.dispatch('lan.bootstrap'),node_role='replica')
        first.dispatch('lan.validator_create',{'profile':'OnlyOne'})
        with self.assertRaisesRegex(ValueError,'FOUR_MEMBER_INVITES_REQUIRED'):
            first.dispatch('lan.session_create',{'enable_dag_transactions':True,'enable_consensus':True})
        self.assertIsNone(first._peer._engine)
        body=first.dispatch('lan.session_create',{'enable_dag_transactions':True})
        self.assertFalse(body['dag_consensus']['anchor_bound'])

    def test_portable_secret_context_is_not_repeated_for_an_already_open_owned_profile(self):
        with patch.object(terminal_service.assets,'bootstrap'):
            service=terminal_service.TerminalService(secret=Mock(return_value='public fixture validator password'))
        self.addCleanup(service.close);service._portable=True
        fake=Mock();fake.validator_unlocked.return_value=False
        previous=vault._password.get()
        def dispatch(command,args):
            self.assertIsNotNone(vault._password.get())
            self.assertEqual(args,{'profile':'Existing'})
            return {'state':'PROFILE_OPEN'}
        fake.dispatch.side_effect=dispatch
        with patch.object(service,'_lan',return_value=fake):
            service.dispatch('lan.validator_open',{'profile':'Existing'})
            self.assertIs(vault._password.get(),previous);self.assertEqual(service.secret.call_count,1)
            fake.validator_unlocked.return_value=True
            fake.dispatch.side_effect=lambda command,args:{'state':'STARTED'}
            service.dispatch('lan.validator_start',{'profile':'Existing'})
            self.assertEqual(service.secret.call_count,1)

    def test_explicit_reopen_revalidates_unknown_start_commit_without_resetting_it(self):
        first,_,_,_=self.network();profile=first._validator_profiles['Win1']
        profile.bind_anchor(first._peer._bundle,first._peer._trusted);invite=profile.public_invite();commit=profile._commit
        def lost_return():commit();raise OSError('public fixture lost native start acknowledgement')
        with patch.object(profile,'_commit',side_effect=lost_return):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):profile.claim_native_start()
        with self.assertRaisesRegex(ValueError,'REOPEN_REQUIRED'):first.dispatch('lan.validator_start',{'profile':'Win1'})
        first.dispatch('lan.validator_open',{'profile':'Win1'});loaded=first._validator_profiles['Win1']
        self.assertIsNot(loaded,profile);self.assertEqual(loaded.public_invite(),invite)
        self.assertTrue(loaded.snapshot()['native_started']);self.assertTrue(first.validator_unlocked('Win1'))
        with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):loaded.claim_native_start()
        self.assertFalse(first._validator_nodes)

    def test_closed_validator_reopens_same_identity_and_wrong_password_preserves_cached_identity(self):
        from backend import gg_node_vault
        with patch.object(gg_node_vault,'provider',return_value='SCRYPT_AES256_GCM'):
            first,_,_,_=self.network();profile=first._validator_profiles['Win1'];invite=profile.public_invite();profile.close()
            with vault.session('different public fixture password'):
                with self.assertRaises(ValueError):first.dispatch('lan.validator_open',{'profile':'Win1'})
            self.assertIs(first._validator_profiles['Win1'],profile);self.assertEqual(profile.public_invite(),invite)
            self.assertFalse(first.validator_unlocked('Win1'));self.assertFalse(first._validator_nodes)
            first.dispatch('lan.validator_open',{'profile':'Win1'})
            self.assertTrue(first.validator_unlocked('Win1'));self.assertEqual(first._validator_profiles['Win1'].public_invite(),invite)

    def test_valid_other_committee_member_cannot_replace_reopened_profile_identity(self):
        first,_,_,_=self.network();old=first._validator_profiles['Win1'];invite=old.public_invite();old.close()
        loaded=validators.ValidatorProfile.open('Win1');other=first._validator_profiles['Win2'].public_invite()
        # Policy seam after decryption: even another valid member is a different identity.
        with patch.object(validators.ValidatorProfile,'open',return_value=loaded),patch.object(loaded,'public_invite',return_value=other):
            with self.assertRaisesRegex(ValueError,'REOPEN_IDENTITY_OR_ANCHOR_CHANGED'):first.dispatch('lan.validator_open',{'profile':'Win1'})
        self.assertIs(first._validator_profiles['Win1'],old);self.assertEqual(old.public_invite(),invite);self.assertTrue(loaded._closed)

    def test_native_process_exit_is_not_hidden_by_transient_RPC_error_or_mistaken_for_conflicting_finality(self):
        first,_,_,_=self.network();profile=first._validator_profiles['Win1'];key=profile.public_invite()['body']['validator_key']
        index=next(index for index,row in enumerate(first._peer._bundle['body']['consensus']['validators']) if row['body']['validator_key']==key)
        node=Mock();node.canonical_membership.return_value=None;node.snapshot.return_value={'validator_index':index,'state':'FAULT','owned_native_process':False,
            'canonical_finality':False,'last_error':'GG_VALIDATOR_NATIVE_PROCESS_EXITED','native_exit_code':73}
        first._validator_nodes['Win1']=node;first._validator_errors['Win1']='GG_VALIDATOR_RPC_UNAVAILABLE'
        summary=first.snapshot()['dag_consensus'];view=next(row for row in summary['profiles'] if row['profile']=='Win1')
        self.assertEqual(view['last_error'],'GG_VALIDATOR_NATIVE_PROCESS_EXITED');self.assertEqual(view['native_exit_code'],73)
        self.assertEqual(summary['members'][index]['state'],'FAULT');self.assertNotEqual(summary['state'],'FAULT')


if __name__=='__main__':unittest.main()
