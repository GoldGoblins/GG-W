"""Protected protocol profile/inbox boundaries, using real local signatures.

SDK lookup is an explicitly incomplete policy seam here. These tests never
claim that such a seam is a certificate, execution, balance or live network;
the combined native/owned-node suite must independently verify those facts.
All files and keys belong to disposable test roots.
"""
import base64
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import threading
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import gg_consensus_profile as validators,gg_financial_account as accounts
from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_financial_dag as financial,gg_financial_wire as wire
from backend import gg_protocol_inbox as inbox,gg_protocol_operations as operations
from backend import gg_observer_profile as observers
from backend import gg_protocol_runtime as runtime
from backend import gg_consensus as native
from backend.gg_financial_pool import PoolBook
from backend import gg_node_store as nodes,portable_wallet_vault as vault
from backend.gg_ed25519 import SIGNATURE_PROFILE,verify_signature
from backend.gg_node_store import pack,unpack
from tests.test_durable_node_store import configuration
from tests.test_financial_general_clients import public_key
from tests.test_financial_account import policy_packet,account_policy


def public_protocol_pin(member=None,*,reward_account=None):
    """Reproducible public TESTNET fixture, with explicit easy test-only work."""
    committee=[]
    for index in range(4):
        fields=('validator_key','node_key','account_key','owner_peer_key')
        row={name:public_key(200+index*4+offset).pubkey().hex() for offset,name in enumerate(fields)}
        row['power']='1';committee.append(row)
    if member is not None:committee[0]={name:member[name] for name in committee[0]}
    committee.sort(key=lambda row:row['validator_key'])
    owner,node,producer,reward=[public_key(300+index) for index in range(4)]
    source={'allowed_producers':[],'native_chain_id':'ggnet:'+'c'*24,'network_id':'d'*64,
            'policy':financial.policy(protocol.SOURCE),'producers':[producer.pubkey().hex()],
            'schema':protocol.SOURCE,'signature_profile':SIGNATURE_PROFILE,'started_at_ns':'1700000000000000000'}
    genesis={'accounts':None,'chain_id':source['native_chain_id'],'decimals':6,
             'financial_accounts':{'allocations':[{'address':public_key(0).pubkey().hex(),'balance_atomic':'1000000000000'}],
                                   'max_accounts':'4294967296','schema':'gg.financial.account-genesis.v1'},
             'financial_dag':source,'genesis_time_unix':1700000000,'schema':protocol.GENESIS,
             'supply_atomic':'1000000000000','symbol':'GG-TEST','validators':[row['validator_key'] for row in committee]}
    body={'chain_id':genesis['chain_id'],'label_utf8':base64.b64encode(b'Public test producer').decode(),
          'network_id':source['network_id'],'node_key':node.pubkey().hex(),'nonce':'e'*64,
          'owner_peer_key':owner.pubkey().hex(),'platform':'linux','producer_key':producer.pubkey().hex(),
          'reward_account':reward.pubkey().hex() if reward_account is None else reward_account,
          'schema':'gg.financial.producer-registration.v1','unused_key_policy':protocol.UNUSED_KEY_POLICY}
    message=b'GG-FINANCIAL-PRODUCER-REGISTRATION-v1\0'+pack(body)
    invite={'body':body,'node_signature':node.sign_message(message).hex(),'owner_signature':owner.sign_message(message).hex(),
            'producer_signature':producer.sign_message(message).hex()}
    genesis['protocol']={'committee':{'epoch':'0','members':committee,'schema':'gg.financial.public-committee.v1'},
        'economics':{'epoch_reward_atomic':'64000','epoch_seconds':'10','fee_per_byte_atomic':'1','halving_epochs':'100',
                     'initial_supply_atomic':genesis['supply_atomic'],'max_supply_atomic':'2000000000000','min_fee_atomic':'10',
                     'schema':'gg.financial.economic-policy.v1','tail_reward_atomic':'1','treasury_account':'','treasury_bps':0},
        'environment':'TESTNET','expected_blocks_per_epoch':'1000','initial_producers':[invite],'initial_work_target':'f'*64,
        'max_committee_change_bps':3333,'max_epoch_participants':'65536','max_producer_entries':'4294967296',
        'max_work_heights':'64','max_work_target':'f'*64,'min_work_target':'0'*63+'1','registration_work_target':'f'*64,
        'schema':'gg.financial.protocol-genesis.v1'}
    return protocol.validate_pin({'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()})


def originals(trust,*,start=0,count=3,signer=None):
    signer=public_key(0) if signer is None else signer;rows=[]
    for nonce in range(start,start+count):
        body=protocol.quote_payment(trust['genesis'],trust['genesis_hash'],signer.pubkey().hex(),public_key(50).pubkey().hex(),'1',nonce)
        rows.append({'body':body,'signature':signer.sign_message(pack(body)).hex()})
    return pack({'schema':wire.PAYMENT_DOCUMENT,'genesis_hash':trust['genesis_hash'],'payments':rows})


class ProtocolProfileInboxTests(unittest.TestCase):
    def test_public_light_certificate_floor_survives_without_claiming_local_sdk_history(self):
        self.stack.enter_context(patch.object(observers,'ROOT',Path(self.temp.name)/'observers'))
        pin=public_protocol_pin()
        profile=observers.ObserverProfile.create_for_protocol('Light',self.owner,pin,label='Light profile')
        self.profiles.append(profile)
        # This is solely a structural journal policy seam, not an SDK proof.
        # The real four-SDK/light integration verifies cryptography separately.
        packet={'schema':'gg.consensus.proof.v1',**deepcopy(pin),
                'state':{'height':1,'state_root':'a'*64},
                'signed_header':{'header':{'height':'2'},'commit':{'block_id':{'hash':'b'*64}}}}
        self.assertFalse(profile.snapshot()['native_started'])
        profile.remember_certificate(packet)
        profile.close()
        profile=observers.ObserverProfile.open('Light');self.profiles.append(profile)
        self.assertEqual(profile.public_certificate(),packet)
        self.assertFalse(profile.snapshot()['native_started'])
        self.assertFalse((profile.root/'native').exists())
        older=deepcopy(packet);older['state']['height']=0;older['signed_header']['header']['height']='1'
        with self.assertRaisesRegex(ValueError,'CERTIFICATE_REWIND'):profile.remember_certificate(older)
        # Claiming a future full replica's first bootstrap remains fresh.
        self.assertTrue(profile.claim_native_start())

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-public-profiles-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close);root=Path(self.temp.name)
        self.stack.enter_context(patch.object(nodes,'ROOT',root/'nodes'))
        self.stack.enter_context(patch.object(validators,'ROOT',root/'validators'))
        self.stack.enter_context(patch.object(accounts,'ROOT',root/'accounts'))
        self.stack.enter_context(vault.session('PUBLIC disposable protocol profile test password'))
        self.profiles=[];self.addCleanup(self.close_profiles)
        self.owner=nodes.NodeProfile.create('Owner',configuration());self.profiles.append(self.owner)
        self.pin=public_protocol_pin()

    def close_profiles(self):
        for item in reversed(self.profiles):item.close()

    def account(self,name='Gov'):
        item=accounts.AccountProfile.create(name,label='Public governance wallet');self.profiles.append(item);return item

    def validator(self,account,name='Validator'):
        item=validators.ValidatorProfile.create_for_protocol(name,self.owner,label='Public validator',p2p_port=22101,account=account)
        self.profiles.append(item);return item

    def bound_validator(self):
        wallet=self.account();profile=self.validator(wallet)
        member={**profile.public_invite()['body'],'power':'1'};pin=public_protocol_pin(member)
        profile.bind_protocol(pin,account=wallet);return profile,wallet,pin

    def book(self):return inbox.ProtocolInbox(self.owner,self.pin)

    def packet(self,nonce=0,*,height=1):return policy_packet(self.pin,public_key(0).pubkey().hex(),nonce=nonce,height=height)

    def test_validator_references_one_independent_wallet_and_preserves_it_cold(self):
        wallet=self.account();profile=self.validator(wallet);invite=profile.public_invite()
        self.assertEqual(len(profile._keys),2);self.assertEqual(len(profile._body['protected_keys']),2)
        self.assertEqual(profile.account_reference(),{'profile':'Gov','public_key':wallet.public_address()})
        self.assertEqual(invite['body']['account_key'],wallet.public_address())
        self.assertNotIn(wallet.public_address(),[row['public'] for row in profile._body['protected_keys']])
        public=[key.pubkey().hex() for key in profile.native_signers()]
        profile.close();reopened=validators.ValidatorProfile.open('Validator');self.profiles.append(reopened)
        self.assertEqual(reopened.public_invite(),invite);self.assertEqual(reopened.account_reference()['profile'],'Gov')
        self.assertEqual([key.pubkey().hex() for key in reopened.native_signers()],public)
        with self.assertRaisesRegex(ValueError,'PROFILE_IN_USE'):accounts.AccountProfile.open('Gov')
        self.assertEqual(wallet.snapshot()['signed_batches'],0)

    def test_invalid_validator_membership_cannot_bind_its_wallet(self):
        wallet=self.account();profile=self.validator(wallet)
        with self.assertRaisesRegex(ValueError,'NOT_A_MEMBER'):profile.bind_protocol(self.pin,account=wallet)
        self.assertIsNone(wallet.anchor());self.assertIsNone(profile.anchor())

    def test_bound_validator_requires_the_actual_leased_referenced_wallet(self):
        profile,wallet,pin=self.bound_validator();other=self.account('Other')
        self.assertEqual(wallet.anchor(),pin)
        with self.assertRaisesRegex(ValueError,'OWNED_ACCOUNT_REQUIRED'):profile.bind_protocol(pin,account=other)
        wallet.close()
        with self.assertRaisesRegex(ValueError,'OWNED_ACCOUNT_REQUIRED'):profile.bind_protocol(pin,account=wallet)
        self.assertEqual(profile.anchor(),pin)

    def test_unopened_validator_has_no_signer(self):
        with self.assertRaisesRegex(ValueError,'KEYS_UNAVAILABLE'):validators.ValidatorProfile('Unopened').native_signers()

    def test_governance_ballot_uses_referenced_wallet_without_allocating_money_nonce(self):
        profile,wallet,pin=self.bound_validator();current=pin['genesis']['protocol']['committee'];next_committee=deepcopy(current);next_committee['epoch']='1'
        body={'expires_height':'20','from_root':economy.committee_root(current,pin['genesis_hash']),'genesis_hash':pin['genesis_hash'],
              'next':next_committee,'schema':'gg.financial.committee-proposal.v1','unused_key_policy':protocol.UNUSED_KEY_POLICY}
        intent={'committee':{'body':body,'ballots':[],'consents':[]}}
        packet=policy_packet(pin,wallet.public_address());packet.pop('expected_financial_account');packet.pop('financial_account')
        packet['state']['protocol']={'committee':current,'pending_committee':None}
        # Only the SDK lookup is a seam. Intent/role checks, real Ed25519
        # signatures, private SQLite and cold journal validation remain real.
        with patch.object(protocol,'verify_selected',return_value={'verified':True}):
            signed=operations.sign_committee(profile,self.owner,intent,packet,pin,account_profile=wallet)
            root=operations.intent_root(intent,pin);message=b'GG-FINANCIAL-COMMITTEE-BALLOT-v1\0'+root.encode()+b'\0'+signed['validator_key'].encode()
            verify_signature(bytes.fromhex(wallet.public_address()),message,bytes.fromhex(signed['signature']))
            with patch.object(wallet._key,'sign_message',side_effect=AssertionError('original ballot resigned')):
                self.assertEqual(operations.sign_committee(profile,self.owner,intent,packet,pin,account_profile=wallet),signed)
                newer=deepcopy(packet);newer['state']['height']=2;newer['state']['state_root']='b'*64;newer['signed_header']['header']['height']='3'
                self.assertEqual(operations.sign_committee(profile,self.owner,intent,newer,pin,account_profile=wallet),signed)
            with self.assertRaisesRegex(ValueError,'CERTIFICATE_REWIND_OR_CONFLICT'):
                operations.sign_committee(profile,self.owner,intent,packet,pin,account_profile=wallet)
            conflicting=deepcopy(intent);conflicting['committee']['body']['expires_height']='21'
            with self.assertRaisesRegex(ValueError,'PENDING_ORIGINAL_REQUIRED'):
                operations.sign_committee(profile,self.owner,conflicting,newer,pin,account_profile=wallet)
        self.assertEqual(wallet.snapshot()['next_signing_nonce'],'0');self.assertEqual(wallet.snapshot()['signed_batches'],0)
        profile.close();reopened=validators.ValidatorProfile.open(profile.name);self.profiles.append(reopened)
        self.assertEqual(reopened._body['protocol_governance']['ballot']['signed'],signed)
        self.assertEqual(len(reopened._body['protocol_governance']['floor']),3)

    def test_inbox_ack_retains_exact_signed_originals_and_window_across_cold_load(self):
        raw=originals(self.pin);book=self.book();key=self.owner.descriptor()['public_keys'][1]
        entry=book.accept(raw,key);entry.remember_window({'floor_sequence':'0','first_nonce':'0','count':1,'size':5000});entry.pause(0)
        recovered=self.book();same=recovered.entries[hashlib.sha256(raw).hexdigest()]
        self.assertEqual(same.raw,raw);self.assertEqual(same._body['window'],entry._body['window']);self.assertEqual(same._body['paused_nonce'],'0')
        self.assertFalse(same.snapshot()['payments_executed_asserted']);self.assertEqual(len(recovered.accept(raw,key)._payments),3)
        self.assertEqual(recovered.snapshot()['retained_documents'],1)

    def test_inbox_gap_suffix_and_terminal_nonce_do_not_invent_payment_outcomes(self):
        raw=originals(self.pin,start=2);book=self.book();entry=book.accept(raw,self.owner.descriptor()['public_keys'][1])
        with patch.object(financial,'verify_account',side_effect=account_policy):
            self.assertIsNone(entry.pending(self.packet(0)))
            self.assertEqual(entry.snapshot()['state'],'WAITING_FOR_EARLIER_NONCE')
            suffix=unpack(entry.pending(self.packet(3,height=2)))
            self.assertEqual([row['body']['nonce'] for row in suffix['payments']],['3','4'])
            self.assertIsNone(entry.pending(self.packet(5,height=3)))
            self.assertEqual(entry.snapshot()['state'],'NONCES_CONSUMED_OUTCOME_UNRESOLVED')
            self.assertFalse(entry.snapshot()['payments_executed_asserted']);self.assertEqual(book.snapshot()['retained_documents'],0)
            self.assertEqual(self.book().snapshot()['retained_documents'],0)

    def test_inbox_checks_real_signatures_before_durable_ack(self):
        raw=originals(self.pin);value=unpack(raw);value['payments'][0]['body']['amount_atomic']='2'
        book=self.book()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_PAYMENT_DOCUMENT_INVALID'):book.accept(pack(value),self.owner.descriptor()['public_keys'][1])
        self.assertEqual(list(book.root.iterdir()),[])

    def test_inbox_write_failure_has_no_ack_and_reclaims_only_its_pending_file(self):
        raw=originals(self.pin);book=self.book();target=book.root/'unrelated.keep';target.write_bytes(b'keep')
        with patch.object(inbox.os,'replace',side_effect=OSError('PUBLIC injected local disk failure')):
            with self.assertRaises(OSError):book.accept(raw,self.owner.descriptor()['public_keys'][1])
        self.assertEqual(book.snapshot()['retained_documents'],0)
        self.assertEqual(sorted(path.name for path in book.root.iterdir()),['unrelated.keep'])

    def test_inbox_cold_recovery_reclaims_unacknowledged_documents_and_partial_staging(self):
        raw=originals(self.pin);book=self.book();identifier=hashlib.sha256(raw).hexdigest()
        book._write(book._path(identifier,'.document'),raw)
        partial=book.root/('.pending-'+'a'*32);partial.write_bytes(b'{partial')
        unrelated=book.root/'unrelated.keep';unrelated.write_bytes(b'keep')
        resumed=self.book();self.assertEqual(resumed.snapshot()['retained_documents'],0)
        self.assertEqual(sorted(path.name for path in book.root.iterdir()),['unrelated.keep'])

    def test_inbox_foreign_owner_or_changed_admission_never_becomes_a_new_original(self):
        raw=originals(self.pin);book=self.book();entry=book.accept(raw,self.owner.descriptor()['public_keys'][1])
        path=book._path(entry._body['document_hash'],'.admission.json');record=unpack(path.read_bytes())
        record['body']['paused_nonce']='1';path.write_bytes(pack(record))
        with self.assertRaises(ValueError):self.book()

    def test_stop_reopens_exact_pool_history_after_workers_join_and_old_relay_is_invalid(self):
        wallet=self.account('PoolReward');pin=public_protocol_pin(reward_account=wallet.public_address());wallet.bind(pin)
        owner=self.owner
        class NativeLifecycleSeam:
            def __init__(self):self.closed=False
            def request_stop(self):pass
            def process_ready(self):return not self.closed
            def close(self):self.closed=True
        class Controller(runtime.ProtocolRuntime):
            def dispatch(self,command,args):
                if command=='protocol.node_start':
                    self.node=NativeLifecycleSeam();self.node.anchor=pin;self.node.binary=None;self.node._stamp=None;self._cancel.clear()
                    self._bind_operator_start(self.node);self._operator_process_started(self.node,self._operator_start_record);return {}
                return super().dispatch(command,args)
            def snapshot(self):return {'active':self.active}
        controller=Controller();controller.owner=owner;controller.accounts[wallet.name]=wallet
        controller.replicas['Replica']=SimpleNamespace(anchor=lambda:pin,snapshot=lambda:{})
        controller.dispatch('protocol.node_start',{})
        args={'pool':'Pool','account_profile':wallet.name,'operator':public_key(800).pubkey().hex(),'commission_bps':25}
        with patch.object(runtime,'DATA_HOME',Path(self.temp.name)/'pool-data'):
            controller.dispatch('protocol.pool_create',args);book=controller.pools['Pool'];self.addCleanup(book.close)
            # SDK registry lookup is the seam; creator signature, hash work,
            # share verification, signed journal and cold replay remain real.
            creator=public_key(302);worker=public_key(801);identifier='7'*64;invite=pin['genesis']['protocol']['initial_producers'][0]
            job={'epoch':'0','expires_height':'65','genesis_hash':pin['genesis_hash'],
                 'job_nonce':hashlib.sha256(b'GG-FINANCIAL-WORK-NONCE-v1\0'+(identifier+invite['body']['nonce']).encode()).hexdigest(),
                 'network_target':'f'*64,'payload_root':identifier,'reward_account':wallet.public_address(),'schema':'gg.financial.mining-job.v1',
                 'share_target':'f'*64,'state_height':'1','state_root':'a'*64,'worker_key':worker.pubkey().hex()}
            body={'block':identifier,'genesis_hash':pin['genesis_hash'],'job':job,'producer_key':creator.pubkey().hex(),
                  'schema':'gg.financial.work-manifest.v1','sequence':'1'}
            manifest={'body':body,'signature':creator.sign_message(b'GG-FINANCIAL-WORK-MANIFEST-v1\0'+pack(body)).hex()}
            selected={'financial_registry_exists':True,'financial_registry_value':base64.b64encode(pack({'invite':invite,'sequence':'0'})).decode()}
            packet={'state':{'protocol':{'work_anchor_height':'1','economics':{'next_epoch':'0'},'work_target':'f'*64,'work_anchor_root':'a'*64}}}
            with patch.object(protocol,'verify_selected',return_value=selected):certified=protocol.derive_manifest_job(manifest,packet,pin,worker.pubkey().hex())
            assignment=book.register_job(certified,public_key(802).pubkey().hex());solution,_,_=economy.mine_work(job,worker,0,1)
            self.assertIsNotNone(solution);book.accept_share(assignment['body']['assignment'],solution,1)
            before=deepcopy(book._head);root=book.root;session=object();controller._relay_session=session;old_node=controller.node
            controller._pool_reviews['OldReview']=object();worker_saw_open=[]
            def finishing_worker():
                controller._cancel.wait(2);worker_saw_open.append(book._db is not None)
            thread=threading.Thread(target=finishing_worker);controller._mine_thread=thread;thread.start()
            controller.stop_node()
            self.assertFalse(thread.is_alive());self.assertEqual(worker_saw_open,[True]);self.assertTrue(old_node.closed)
            self.assertIsNone(book._db);self.assertIsNone(book._lease);self.assertEqual(controller.pools,{});self.assertEqual(controller._pool_reviews,{})
            with self.assertRaisesRegex(ValueError,'TARGET_STOPPED'):controller._relay_request(old_node,worker.pubkey().hex(),{'method':'pool_job'},session)
            config={'schema':'gg.protocol.local-start.v2','owner_profile':owner.name,'native_profile':'Replica','role':'REPLICA',
                    'settings_path':'settings.json','account_profiles':[wallet.name],'producer':False,'mining':None,
                    'pools':[{**args,'create':False}],'relay':None,'account_submissions':[],'pool_work':None}
            with patch.object(runtime,'read_public',side_effect=lambda path,*args:deepcopy(config) if str(path)=='start.json' else {}),\
                    patch.object(runtime,'local_acceptance',side_effect=lambda value,*args:protocol.validate_pin(value)):
                for _ in range(2):
                    self.assertTrue(controller.dispatch('protocol.run',{'path':'start.json'})['active'])
                    controller._advance_operator_start(False);self.assertNotIn('Pool',controller.pools)
                    controller._advance_operator_start(True)
                    reopened=controller.pools['Pool'];self.addCleanup(reopened.close)
                    self.assertEqual(reopened.root,root);self.assertEqual(reopened._head,before);self.assertEqual(reopened._head['events'],2)
                    self.assertEqual(reopened._get('JOB',assignment['body']['assignment'])['data']['job'],job)
                    controller.stop_node()


class NativeProofDispatchBoundaryTests(unittest.TestCase):
    def test_missing_genesis_schema_still_requires_native_rejection(self):
        # Missing schema selects no public committee history. Neither a failed
        # native verifier nor an unverified response may turn it into success.
        payload={'genesis':{},'state':{'height':1,'state_root':'b'*64}}
        for code,stdout in ((1,b''),(0,b'{}')):
            result=subprocess.CompletedProcess(['PUBLIC verifier'],code,stdout)
            with self.subTest(code=code),patch.object(native.native_pipes.LEGACY_VERIFY,'run',return_value=result) as launched,\
                    patch('backend.gg_committee_history.history',side_effect=AssertionError('missing schema opened public history')):
                with self.assertRaisesRegex(ValueError,'GG_CONSENSUS_CERTIFICATE_INVALID'):native._verify_public(payload,Path('PUBLIC-verifier'),None)
                self.assertEqual(launched.call_args.args[0][-1],'verify')

    def test_nonobject_genesis_is_rejected_before_verifier_dispatch(self):
        with patch.object(native.native_pipes.LEGACY_VERIFY,'run',side_effect=AssertionError('bad shape launched verifier')):
            for payload in (None,[],{'genesis':None},{'genesis':[]}):
                with self.subTest(payload=payload),self.assertRaisesRegex(ValueError,'GG_CONSENSUS_CERTIFICATE_INVALID'):
                    native._verify_public(payload,Path('PUBLIC-verifier'),None)


class ProtocolStartOrchestrationTests(unittest.TestCase):
    """Child lifecycle seams only; no mock is presented as an actual node."""
    def config(self):
        return {'schema':'gg.protocol.local-start.v2','owner_profile':'Owner','native_profile':'Native','role':'VALIDATOR',
                'settings_path':'settings.json','account_profiles':['Pay'],'producer':True,
                'mining':{'producer_slot':0,'duration_seconds':60},'pools':[],'relay':None,'account_submissions':[],'pool_work':None}

    def controller(self,*,fail=None,reference='Gov'):
        class LifecycleSeam(runtime.ProtocolRuntime):
            def __init__(self):super().__init__();self.calls=[];self.stopped=False;self.bound=[]
            def dispatch(self,command,args):
                if command=='protocol.run':return super().dispatch(command,args)
                self.calls.append((command,deepcopy(args)))
                if command==fail:raise ValueError('PUBLIC child startup failure')
                if command=='protocol.owner_open':self.owner=SimpleNamespace(name=args['profile'])
                elif command in ('protocol.validator_open','protocol.replica_open'):
                    profile=SimpleNamespace(anchor=lambda:{'test_pin':True},account_reference=lambda:{'profile':reference} if reference else None)
                    (self.validators if command=='protocol.validator_open' else self.replicas)[args['profile']]=profile
                elif command=='protocol.account_open':self.accounts[args['profile']]=SimpleNamespace(bind=lambda pin:self.bound.append((args['profile'],deepcopy(pin))))
                elif command in ('protocol.node_start','protocol.light_start'):
                    self.node=SimpleNamespace(process_ready=lambda:True,request_stop=lambda:setattr(self,'stop_requested',True))
                    self._bind_operator_start(self.node);self._operator_process_started(self.node,self._operator_start_record)
                return {}
            def snapshot(self):return {'active':self.active}
            def stop_node(self):self.stopped=True;self.node=None
        return LifecycleSeam()

    def run_config(self,controller,config):
        with patch.object(runtime,'read_public',side_effect=lambda path,*args:deepcopy(config) if str(path)=='start.json' else {'test_settings':True}),\
                patch.object(runtime,'local_acceptance',side_effect=lambda pin,*args:pin),patch.object(runtime,'endpoint',return_value=None):
            return controller.dispatch('protocol.run',{'path':'start.json'})

    def test_start_opens_governance_wallet_once_before_node_and_runs_whole_configuration(self):
        controller=self.controller();config=self.config();config['account_profiles'].append('Gov')
        config['pools']=[{'pool':'Pool','account_profile':'Pay','operator':public_key(700).pubkey().hex(),'commission_bps':25,'create':False}]
        config['relay']={'host':'127.0.0.1','port':22109,'allowed_peer_keys':[public_key(701).pubkey().hex()]}
        config['account_submissions']=[{'profile':'Pay'}]
        self.assertTrue(self.run_config(controller,config)['active'])
        self.assertNotIn('protocol.producer_open',[command for command,args in controller.calls])
        controller._advance_operator_start(False)
        self.assertNotIn('protocol.producer_open',[command for command,args in controller.calls])
        controller._advance_operator_start(True)
        calls=[command for command,args in controller.calls]
        self.assertEqual([args['profile'] for command,args in controller.calls if command=='protocol.account_open'],['Pay','Gov'])
        self.assertLess(calls.index('protocol.account_open'),calls.index('protocol.node_start'))
        self.assertLess(calls.index('protocol.pool_open'),calls.index('protocol.relay_start'))
        self.assertLess(calls.index('protocol.submit_account'),calls.index('protocol.mine_start'))
        self.assertEqual([name for name,pin in controller.bound],['Pay','Gov'])

    def test_auto_governance_wallet_counts_towards_bounded_start(self):
        controller=self.controller();config=self.config();config['account_profiles']=['Account'+str(index) for index in range(16)]
        with self.assertRaisesRegex(ValueError,'ACCOUNT_PROFILE_LIMIT'):self.run_config(controller,config)
        self.assertNotIn('protocol.node_start',[command for command,args in controller.calls])

    def test_bad_start_inputs_fail_before_any_profile_or_node_is_opened(self):
        cases=[lambda cfg:cfg['account_profiles'].append([]),lambda cfg:cfg.update(owner_profile='../outside'),
               lambda cfg:cfg.update(settings_path=None),lambda cfg:cfg['mining'].update(duration_seconds=0),
               lambda cfg:cfg.update(producer=False),lambda cfg:cfg.update(pool_work={'account_profile':'Pay'})]
        for mutate in cases:
            controller=self.controller();config=self.config();mutate(config)
            with self.subTest(config=config),self.assertRaises(ValueError):self.run_config(controller,config)
            self.assertEqual(controller.calls,[])

    def test_partial_child_start_failure_stops_native_lifecycle(self):
        controller=self.controller(fail='protocol.relay_start');config=self.config();config['relay']={}
        self.assertTrue(self.run_config(controller,config)['active'])
        controller._advance_operator_start(False)
        self.assertIsNotNone(controller._operator_pending)
        controller._advance_operator_start(True)
        self.assertEqual(controller._operator_start_state,'FAILED');self.assertIsNone(controller._operator_pending)
        self.assertEqual(controller._operator_start_error,'GG_PROTOCOL_OPERATION_UNAVAILABLE')
        self.assertTrue(controller.stop_requested)
        controller.stop_node()
        self.assertTrue(controller.stopped);self.assertFalse(controller.active)
        self.assertNotIn('protocol.mine_start',[command for command,args in controller.calls])

    def test_light_worker_start_can_receive_originals_without_hosting_or_voting(self):
        controller=self.controller(reference=None);config=self.config()
        config.update(role='LIGHT',producer=False,mining=None,pool_work={'account_profile':'Pay','duration_seconds':20,'attempts':64})
        self.assertTrue(self.run_config(controller,config)['active'])
        self.assertNotIn('protocol.pool_work_start',[command for command,args in controller.calls])
        controller._advance_operator_start(True)
        calls=[command for command,args in controller.calls]
        self.assertIn('protocol.light_start',calls);self.assertIn('protocol.pool_work_start',calls)
        self.assertNotIn('protocol.node_start',calls);self.assertNotIn('protocol.producer_open',calls)


if __name__=='__main__':unittest.main()
