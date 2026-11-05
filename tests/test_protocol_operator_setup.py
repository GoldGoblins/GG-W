"""Operator public-file workflow with real disposable protected identities.

Only the native genesis-review adapter is an explicit unit policy seam. No
cryptographic signature, protected profile, nonce journal or public schema is
mocked. Actual native genesis/start/network checks belong to the combined
integration suite. These tests must not launch a node, relay or listener.
"""
import ast
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import gg_protocol_setup as setup,gg_protocol_provisioning as provisioning
from backend import gg_protocol_runtime as runtime,gg_financial_protocol as protocol
from backend import gg_node_store as nodes,gg_consensus_profile as validators
from backend import gg_financial_account as accounts,gg_observer_profile as observers
from backend import portable_wallet_vault as vault
from backend.gg_node_store import pack,unpack
from backend.terminal_cli import parse_command


class PublicOperatorFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-operator-files-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_public_export_is_canonical_and_never_overwrites_existing_bytes(self):
        target=self.root/'public.json';document={'schema':'PUBLIC_FILE_TEST','nested':{'value':'1'}}
        result=setup.write_public(str(target),document)
        self.assertTrue(result['public_only']);self.assertFalse(result['private_keys_exported'])
        self.assertEqual(target.read_bytes(),pack(document));self.assertEqual(setup.read_public(str(target)),document)
        original=target.read_bytes();document['nested']['value']='changed'
        with self.assertRaisesRegex(ValueError,'PUBLIC_FILE_EXISTS'):setup.write_public(str(target),document)
        self.assertEqual(target.read_bytes(),original)

    def test_file_created_after_path_review_is_preserved_by_exclusive_create(self):
        target=self.root/'race.json';original_path=setup._path;sentinel=b'PUBLIC RACED FILE MUST STAY'
        def raced(value):
            path=original_path(value)
            if path==target:path.write_bytes(sentinel)
            return path
        with patch.object(setup,'_path',side_effect=raced):
            with self.assertRaisesRegex(ValueError,'PUBLIC_FILE_EXISTS'):setup.write_public(str(target),{'schema':'PUBLIC TEST'})
        self.assertEqual(target.read_bytes(),sentinel)

    def test_hardlinked_public_input_is_not_imported(self):
        target=self.root/'original.json';alias=self.root/'hardlink.json';target.write_bytes(pack({'schema':'PUBLIC TEST'}))
        os.link(target,alias)
        with self.assertRaises((ValueError,OSError)):setup.read_public(str(alias))
        self.assertEqual(target.read_bytes(),pack({'schema':'PUBLIC TEST'}))

    def test_linked_parent_cannot_read_or_export_outside_reviewed_path(self):
        actual=self.root/'actual';actual.mkdir();alias=self.root/'alias'
        original=actual/'input.json';original.write_bytes(pack({'schema':'PUBLIC TEST'}))
        if os.name=='nt':
            result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(alias),str(actual)],
                capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=5)
            self.assertEqual(result.returncode,0,'disposable junction fixture creation failed')
        else:alias.symlink_to(actual,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'PUBLIC_FILE'):setup.read_public(str(alias/'input.json'))
        with self.assertRaisesRegex(ValueError,'PUBLIC_FILE'):setup.write_public(str(alias/'output.json'),{'schema':'PUBLIC TEST'})
        self.assertFalse((actual/'output.json').exists())

    def test_file_limits_duplicate_fields_and_bad_paths_fail_before_import(self):
        target=self.root/'large.json';target.write_bytes(pack({'schema':'PUBLIC TEST','value':'x'*64}))
        with self.assertRaisesRegex(ValueError,'PUBLIC_FILE'):setup.read_public(str(target),8)
        duplicate=self.root/'duplicate.json';duplicate.write_bytes(b'{"schema":"PUBLIC FIRST","schema":"PUBLIC SECOND"}')
        with self.assertRaises(ValueError):setup.read_public(str(duplicate))
        for value in (None,'',12,'x'*4097,'//PUBLIC-NONLOCAL-SERVER/share/input.json'):
            with self.subTest(path_type=type(value).__name__),self.assertRaises(ValueError):setup._path(value)
        with self.assertRaisesRegex(ValueError,'PUBLIC_FILE_LIMIT'):setup.write_public(str(self.root/'oversize.json'),{'value':'x'*(512*1024)})
        self.assertFalse((self.root/'oversize.json').exists())


class ProtectedOperatorWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-operator-workflow-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.files=self.root/'public';self.files.mkdir()
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for module,directory in ((nodes,'owners'),(validators,'validators'),(accounts,'accounts'),(observers,'observers')):
            self.stack.enter_context(patch.object(module,'ROOT',self.root/directory))
        self.stack.enter_context(vault.session('PUBLIC disposable operator workflow fixture password'))
        self.native_reviews=[];self.private_seeds=[]
        self.native=self.stack.enter_context(patch.object(provisioning,'validate_pin_native',side_effect=self.native_review))
        self.stack.enter_context(patch.object(runtime.OwnedProtocolNode,'start',side_effect=AssertionError('operator export launched a native node')))
        self.stack.enter_context(patch.object(runtime.LightProtocolNode,'start',side_effect=AssertionError('operator export launched a light connection')))
        self.stack.enter_context(patch.object(runtime,'ProofTransportServer',side_effect=AssertionError('operator export launched a relay')))

    def native_review(self,pin,**options):
        # This seam is not a native certificate or validation implementation.
        # Public schema/roles/PoPs and every actual Ed25519 operation remain real.
        value=protocol.validate_pin(pin);self.native_reviews.append(deepcopy(value))
        return {'scope':'UNIT_NATIVE_REVIEW_SEAM_ONLY','genesis_hash':value['genesis_hash']}

    def path(self,name):return str(self.files/name)

    def put(self,name,value):
        path=self.files/name;path.write_bytes(pack(value));return str(path)

    def read(self,name):return setup.read_public(self.path(name))

    def step(self,command,**arguments):
        # A fresh controller for every command models the real one-shot CLI;
        # every needed key must reopen its existing exclusive protected store.
        controller=runtime.ProtocolRuntime()
        try:
            result=controller.dispatch(command,arguments)
            self.assertIsNone(controller.node,'offline operator command started a node')
            self.assertIsNone(controller._relay,'offline operator command started a relay')
            if controller.owner is not None:
                identity,producers=controller.owner.signers()
                self.private_seeds.extend(bytes(key)[:32] for key in (identity,*producers))
            for profile in controller.validators.values():self.private_seeds.extend(bytes(key)[:32] for key in profile.native_signers())
            for profile in controller.accounts.values():self.private_seeds.append(bytes(profile._key)[:32])
            return result
        finally:controller.close()

    def member(self,index):
        owner='Owner'+str(index);profile='Validator'+str(index);account='Gov'+str(index)
        self.step('protocol.owner_create',profile=owner,label='Public owner '+str(index),host='127.0.0.1',port=17001+index,allowed_cidr='127.0.0.0/8')
        invite=self.step('protocol.validator_create',owner_profile=owner,profile=profile,account_profile=account,label='Public validator '+str(index),p2p_port=22001+index)
        return {'owner':owner,'profile':profile,'account':account,'invite':invite}

    def prepare_inputs(self):
        self.step('protocol.context_create',path=self.path('context.json'))
        self.members=[self.member(index) for index in range(4)]
        for index,member in enumerate(self.members):
            self.step('protocol.validator_invite_export',profile=member['profile'],path=self.path('validator'+str(index)+'.json'))
            self.step('protocol.account_export',profile=member['account'],path=self.path('account'+str(index)+'.json'))
            self.step('protocol.initial_producer_export',owner_profile=member['owner'],profile=member['profile'],context_path=self.path('context.json'),
                producer_slot=0,label='Public producer '+str(index),platform=('windows','linux','termux','other')[index],path=self.path('producer'+str(index)+'.json'))
        # Deliberately explicit TESTNET policy. Production code selects none of
        # these monetary/target/power/allocation parameters on the user's behalf.
        spec={'schema':'gg.protocol.genesis-file-spec.v1','context_path':'context.json',
              'validators':[{'invite_path':'validator'+str(index)+'.json','power':'1'} for index in range(4)],
              'producer_invite_paths':['producer'+str(index)+'.json' for index in range(4)],
              'allocations':[{'source_path':'account0.json','balance_atomic':'1000000000000'}],
              'max_accounts':'20000',
              'economics':{'schema':'gg.financial.economic-policy.v1','initial_supply_atomic':'1000000000000',
                  'max_supply_atomic':'2000000000000','epoch_reward_atomic':'64000','epoch_seconds':'10','halving_epochs':'100',
                  'tail_reward_atomic':'1','fee_per_byte_atomic':'1','min_fee_atomic':'10','treasury_bps':0,'treasury_account':''},
              'protocol':{'expected_blocks_per_epoch':'1000','initial_work_target':'f'*64,'max_work_target':'f'*64,'min_work_target':'0'*63+'1',
                  'registration_work_target':'f'*64,'max_committee_change_bps':3333,'max_epoch_participants':'64',
                  'max_producer_entries':'128','max_work_heights':'64'}}
        self.put('genesis-spec.json',spec);return spec

    def ceremony(self):
        self.prepare_inputs()
        self.step('protocol.genesis_assemble',spec_path=self.path('genesis-spec.json'),path=self.path('pin.json'))
        for index,member in enumerate(self.members):
            self.step('protocol.genesis_endorse',owner_profile=member['owner'],profile=member['profile'],pin_path=self.path('pin.json'),path=self.path('endorsement'+str(index)+'.json'))
        self.put('bootstrap-spec.json',{'schema':'gg.protocol.bootstrap-file-spec.v1','pin_path':'pin.json',
            'validator_invite_paths':['validator'+str(index)+'.json' for index in range(4)],
            'endorsement_paths':['endorsement'+str(index)+'.json' for index in range(4)]})
        self.step('protocol.bootstrap_assemble',spec_path=self.path('bootstrap-spec.json'),path=self.path('bootstrap.json'))
        return self.read('bootstrap.json')

    def assert_no_private_output(self):
        forbidden={'protected_key','protected_keys','ciphertext','validator_seed','node_seed','private_key','password'}
        def check(value):
            if isinstance(value,dict):
                self.assertFalse(forbidden.intersection(value),'protected material field reached public document')
                for child in value.values():check(child)
            elif isinstance(value,list):
                for child in value:check(child)
        for path in self.files.rglob('*.json'):
            raw=path.read_bytes();check(unpack(raw))
            for seed in self.private_seeds:
                self.assertTrue(seed.hex().encode() not in raw,'private disposable signing seed reached public document')

    def test_random_public_context_needs_no_profiles_or_manually_copied_identifiers(self):
        self.step('protocol.context_create',path=self.path('first.json'))
        self.step('protocol.context_create',path=self.path('second.json'))
        first,second=self.read('first.json'),self.read('second.json')
        self.assertEqual(set(first),provisioning.CONTEXT_FIELDS);self.assertEqual(first['environment'],'TESTNET')
        self.assertNotEqual(first['chain_id'],second['chain_id']);self.assertNotEqual(first['network_id'],second['network_id'])
        self.assertRegex(first['chain_id'],r'^ggnet:[0-9a-f]{24}$')
        for directory in ('owners','validators','accounts','observers'):self.assertFalse((self.root/directory).exists())
        self.native.assert_not_called()

    def test_context_schema_and_environment_errors_create_no_document(self):
        cases=[{'schema':'gg.protocol.context-spec.v1','environment':'MAINNET'},
               {'schema':'gg.protocol.context-spec.v1','private_seed':'FORBIDDEN_PUBLIC_FIELD'}]
        for index,spec in enumerate(cases):
            source=self.put('bad-context'+str(index)+'.json',spec);target=self.path('bad-result'+str(index)+'.json')
            with self.assertRaises(ValueError):self.step('protocol.context_create',spec_path=source,path=target)
            self.assertFalse(Path(target).exists())

    def test_real_cold_profiles_build_endorse_and_export_operator_start_documents(self):
        bundle=self.ceremony();pin=bundle['pin']
        self.assertEqual(provisioning.validate_bootstrap(bundle),bundle)
        review=self.step('protocol.bootstrap_review',path=self.path('bootstrap.json'))
        self.assertTrue(review['all_initial_operators_endorsed']);self.assertFalse(review['certificate_asserted']);self.assertFalse(review['node_started'])
        self.assertEqual(review['validator_count'],4);self.assertEqual(review['producer_count'],4)
        self.assertEqual(review['allocations'][0]['address'],self.members[0]['invite']['body']['account_key'])
        self.assertGreater(len(self.native_reviews),0)
        options=self.put('validator-options.json',{'producer':True,'mining':{'producer_slot':0,'duration_seconds':10}})
        result=self.step('protocol.start_plan',owner_profile='Owner0',profile='Validator0',role='VALIDATOR',bootstrap_path=self.path('bootstrap.json'),
            options_path=options,output_dir=self.path('validator-start'))
        self.assertFalse(result['node_started']);self.assertFalse(result['private_keys_exported'])
        directory=self.files/'validator-start';self.assertEqual({path.name for path in directory.iterdir()},{'bootstrap.json','settings.json','run.json'})
        config=setup.read_public(str(directory/'run.json'));settings=setup.read_public(str(directory/'settings.json'))
        self.assertEqual(config['schema'],'gg.protocol.operator-start.v1');self.assertEqual(config['bootstrap_path'],'bootstrap.json')
        self.assertEqual(config['native_profile'],'Validator0');self.assertEqual(config['role'],'VALIDATOR')
        self.assertEqual(config['account_profiles'],['Gov0'],'generated plan omitted its actual referenced governance wallet')
        self.assertEqual(settings['p2p_port'],22001);self.assertEqual(len(settings['peers']),3)
        expected={hashlib.sha256(bytes.fromhex(member['invite']['body']['node_key'])).digest()[:20].hex() for member in self.members[1:]}
        self.assertEqual({row['id'] for row in settings['peers']},expected)
        for member in self.members:
            wallet=accounts.AccountProfile.open(member['account']);profile=validators.ValidatorProfile.open(member['profile'])
            try:
                self.assertEqual(wallet.anchor(),pin);self.assertEqual(profile.anchor(),pin)
                self.assertEqual(wallet.snapshot()['next_signing_nonce'],'0');self.assertEqual(wallet.snapshot()['signed_batches'],0)
                self.assertFalse(profile.snapshot()['native_started']);self.assertFalse((profile.root/'native').exists())
            finally:profile.close();wallet.close()
        self.assert_no_private_output()

    def test_schema_or_native_review_failure_never_exports_a_genesis(self):
        spec=self.prepare_inputs();bad={**spec,'private_seed':'FORBIDDEN_PUBLIC_FIELD'}
        badpath=self.put('bad-genesis-spec.json',bad);target=self.path('bad-pin.json')
        with self.assertRaisesRegex(ValueError,'GENESIS_FILE_SPEC'):self.step('protocol.genesis_assemble',spec_path=badpath,path=target)
        self.assertFalse(Path(target).exists())
        with patch.object(provisioning,'validate_pin_native',side_effect=ValueError('UNIT_NATIVE_POLICY_REJECT')):
            with self.assertRaisesRegex(ValueError,'UNIT_NATIVE_POLICY_REJECT'):
                self.step('protocol.genesis_assemble',spec_path=self.path('genesis-spec.json'),path=target)
        self.assertFalse(Path(target).exists())
        wallet=accounts.AccountProfile.open('Gov0');profile=validators.ValidatorProfile.open('Validator0')
        try:self.assertIsNone(wallet.anchor());self.assertIsNone(profile.anchor())
        finally:profile.close();wallet.close()

    def test_tampered_signed_allocation_card_is_rejected_before_pin_export(self):
        self.prepare_inputs();card=self.read('account0.json');card['body']['label']='PUBLIC TAMPERED ACCOUNT LABEL'
        self.put('account0.json',card)
        with self.assertRaises(ValueError):self.step('protocol.genesis_assemble',spec_path=self.path('genesis-spec.json'),path=self.path('pin.json'))
        self.assertFalse((self.files/'pin.json').exists())

    def test_missing_or_wrong_owner_profiles_never_create_substitute_identities(self):
        self.step('protocol.context_create',path=self.path('context.json'))
        self.member(0);self.member(1)
        with self.assertRaisesRegex(ValueError,'OWNER_MISMATCH'):
            self.step('protocol.initial_producer_export',owner_profile='Owner1',profile='Validator0',context_path=self.path('context.json'),
                producer_slot=0,label='Wrong owner export',platform='windows',path=self.path('wrong-owner.json'))
        self.assertFalse((self.files/'wrong-owner.json').exists())
        for command,profile,directory in [('protocol.validator_invite_export','MissingValidator','validators'),('protocol.account_export','MissingAccount','accounts')]:
            with self.subTest(command=command),self.assertRaises(ValueError):self.step(command,profile=profile,path=self.path(profile+'.json'))
            self.assertFalse((self.root/directory/profile).exists());self.assertFalse((self.files/(profile+'.json')).exists())

    def test_bound_initial_producer_export_reuses_accepted_public_original(self):
        self.ceremony();original=self.read('producer0.json')
        self.step('protocol.initial_producer_export',owner_profile='Owner0',profile='Validator0',context_path=self.path('context.json'),
            producer_slot=0,label='Public producer 0',platform='windows',path=self.path('same-producer.json'))
        self.assertEqual(self.read('same-producer.json'),original)
        with self.assertRaisesRegex(ValueError,'INITIAL_PRODUCER_CHANGED'):
            self.step('protocol.initial_producer_export',owner_profile='Owner0',profile='Validator0',context_path=self.path('context.json'),
                producer_slot=0,label='Changed declared producer',platform='windows',path=self.path('changed-producer.json'))
        self.assertFalse((self.files/'changed-producer.json').exists())

    def phone(self):
        self.step('protocol.owner_create',profile='PhoneOwner',label='Public phone owner',host='127.0.0.1',port=17009,allowed_cidr='127.0.0.0/8')
        self.step('protocol.account_create',profile='PhoneAccount',label='Public phone payout account')
        self.step('protocol.client_create',owner_profile='PhoneOwner',profile='PhoneClient',role='LIGHT',bootstrap_path=self.path('bootstrap.json'),
            label='Public phone light client',path=self.path('phone-card.json'))
        self.step('protocol.relay_endpoint_export',owner_profile='Owner0',profile='Validator0',bootstrap_path=self.path('bootstrap.json'),
            host='127.0.0.1',port=23100,path=self.path('relay-endpoint.json'))

    def test_actual_light_card_and_relay_endpoint_build_mutually_bound_start_plans(self):
        bundle=self.ceremony();self.phone();card=self.read('phone-card.json');endpoint=self.read('relay-endpoint.json')
        self.assertEqual(setup._client_document(card,bundle['pin']),card['body'])
        self.assertEqual(setup._endpoint_document(endpoint,bundle),endpoint['body']['endpoint'])
        self.step('protocol.client_export',owner_profile='PhoneOwner',profile='PhoneClient',role='LIGHT',path=self.path('phone-card-again.json'))
        self.assertEqual(self.read('phone-card-again.json'),card)
        options=self.put('phone-options.json',{'account_profiles':['PhoneAccount'],'pool_work':{'account_profile':'PhoneAccount','duration_seconds':10,'attempts':64}})
        self.step('protocol.start_plan',owner_profile='PhoneOwner',profile='PhoneClient',role='LIGHT',bootstrap_path=self.path('bootstrap.json'),
            options_path=options,endpoint_path=self.path('relay-endpoint.json'),output_dir=self.path('phone-start'))
        config=self.read('phone-start/run.json');settings=self.read('phone-start/settings.json')
        self.assertEqual(config['role'],'LIGHT');self.assertFalse(config['producer']);self.assertIsNone(config['mining'])
        self.assertEqual(settings,endpoint['body']['endpoint']);self.assertEqual(config['pool_work']['duration_seconds'],10)
        relay_options=self.put('relay-options.json',{'account_profiles':['Gov0'],'producer':True,
            'pools':[{'pool':'PublicPool','account_profile':'Gov0','operator_source_path':'account0.json','commission_bps':25,'create':True}],
            'relay':{
            'endpoint_path':'relay-endpoint.json','client_card_paths':['phone-card.json'],
            'policy':{'accept_operations':False,'accept_accounts':True,'producer_slot':0}}})
        self.step('protocol.start_plan',owner_profile='Owner0',profile='Validator0',role='VALIDATOR',bootstrap_path=self.path('bootstrap.json'),
            options_path=relay_options,output_dir=self.path('relay-start'))
        relay=self.read('relay-start/run.json')['relay']
        self.assertEqual(relay['allowed_peer_keys'],[card['body']['node_key']]);self.assertTrue(relay['accept_accounts'])
        pool=self.read('relay-start/run.json')['pools'][0]
        self.assertNotIn('operator_source_path',pool)
        self.assertEqual(pool['operator'],self.members[0]['invite']['body']['account_key'])
        self.assert_no_private_output()

    def test_bad_light_role_or_options_never_create_start_directory(self):
        self.ceremony();self.phone()
        cases=[{'account_profiles':[{}]}, {'private_seed':'FORBIDDEN_PUBLIC_FIELD'},
               {'producer':True}, {'pools':[{'pool':'FORBIDDEN_LIGHT_HOSTED_POOL'}]}]
        for index,options in enumerate(cases):
            source=self.put('bad-options'+str(index)+'.json',options);directory=self.path('bad-start'+str(index))
            with self.subTest(options=index),self.assertRaises(ValueError):
                self.step('protocol.start_plan',owner_profile='PhoneOwner',profile='PhoneClient',role='LIGHT',bootstrap_path=self.path('bootstrap.json'),
                    options_path=source,endpoint_path=self.path('relay-endpoint.json'),output_dir=directory)
            self.assertFalse(Path(directory).exists())

    def test_tampered_valid_private_endpoint_or_client_card_cannot_authorize_start_plan(self):
        bundle=self.ceremony();self.phone();endpoint=self.read('relay-endpoint.json');endpoint['body']['endpoint']['host']='127.0.0.2'
        with self.assertRaises(ValueError):setup._endpoint_document(endpoint,bundle)
        card=self.read('phone-card.json');card['body']['role']='REPLICA'
        with self.assertRaises(ValueError):setup._client_document(card,bundle['pin'])
        self.put('tampered-endpoint.json',endpoint)
        with self.assertRaises(ValueError):
            self.step('protocol.start_plan',owner_profile='PhoneOwner',profile='PhoneClient',role='LIGHT',bootstrap_path=self.path('bootstrap.json'),
                endpoint_path=self.path('tampered-endpoint.json'),output_dir=self.path('tampered-start'))
        self.assertFalse((self.files/'tampered-start').exists())

    def test_actual_operator_run_checks_all_endorsements_before_opening_any_profile(self):
        bundle=self.ceremony()
        config={'schema':'gg.protocol.operator-start.v1','owner_profile':'Owner0','native_profile':'Validator0','role':'VALIDATOR',
            'settings_path':'unused-settings.json','bootstrap_path':'bad-bootstrap.json','account_profiles':['Gov0'],
            'producer':False,'mining':None,'pools':[],'relay':None,'account_submissions':[],'pool_work':None}
        broken=deepcopy(bundle);broken['endorsements'][0]['owner_signature']='00'*64
        self.put('bad-bootstrap.json',broken);self.put('run-bad-bootstrap.json',config)
        with patch.object(nodes.NodeProfile,'open',side_effect=AssertionError('invalid bootstrap opened owner')) as owner_open,\
                patch.object(validators.ValidatorProfile,'open',side_effect=AssertionError('invalid bootstrap opened voter')) as voter_open,\
                patch.object(accounts.AccountProfile,'open',side_effect=AssertionError('invalid bootstrap opened account')) as account_open:
            with self.assertRaises(ValueError):self.step('protocol.run',path=self.path('run-bad-bootstrap.json'))
            owner_open.assert_not_called();voter_open.assert_not_called();account_open.assert_not_called()
        # The same shared preflight must reject malformed finite work before
        # it could reach a profile, independent of bootstrap validity.
        config['bootstrap_path']='bootstrap.json';config.update(producer=True,mining={'producer_slot':0,'duration_seconds':0})
        self.put('run-bad-duration.json',config)
        with patch.object(nodes.NodeProfile,'open',side_effect=AssertionError('invalid finite policy opened owner')) as owner_open:
            with self.assertRaisesRegex(ValueError,'START_DOCUMENT'):self.step('protocol.run',path=self.path('run-bad-duration.json'))
            owner_open.assert_not_called()

    def test_operator_run_returns_before_quorum_then_consumes_owned_start_config_once(self):
        self.ceremony()
        self.step('protocol.start_plan',owner_profile='Owner0',profile='Validator0',role='VALIDATOR',bootstrap_path=self.path('bootstrap.json'),
            options_path=self.put('deferred-options.json',{'producer':True,'mining':{'producer_slot':0,'duration_seconds':10}}),
            output_dir=self.path('deferred-start'))
        class NativeLifecycleSeam(runtime.ProtocolRuntime):
            def __init__(self):super().__init__();self.effects=[]
            def dispatch(self,command,args):
                if command=='protocol.node_start':
                    self._reset_observation();self.node=SimpleNamespace(ready=False,request_stop=lambda:None,close=lambda:None)
                    self.node.process_ready=lambda:self.node.ready
                    self._cancel.clear();self._bind_operator_start(self.node);return {'scope':'UNIT_NODE_LIFECYCLE_ONLY'}
                if command in ('protocol.producer_open','protocol.mine_start'):
                    self.effects.append((command,deepcopy(args)));return {'scope':'UNIT_EXTRA_EFFECT_LIFECYCLE_ONLY'}
                return super().dispatch(command,args)
            def snapshot(self):return {'operator_state':self._operator_start_state,'pending':self._operator_pending is not None}
        controller=NativeLifecycleSeam();path=self.path('deferred-start/run.json')
        try:
            result=controller.dispatch('protocol.run',{'path':path})
            self.assertEqual(result,{'operator_state':'RECOVERING','pending':True})
            self.assertEqual(controller.effects,[]);self.assertIsNone(controller._thread)
            # A later edit to a public plan cannot mutate this already queued
            # explicit operation. A new run would need its own fresh checks.
            edited=setup.read_public(path);edited['mining']['duration_seconds']=99;Path(path).write_bytes(pack(edited))
            controller._advance_operator_start(False);self.assertEqual(controller.effects,[])
            self.assertEqual(controller._operator_start_state,'RECOVERING')
            controller.node.ready=True
            controller._advance_operator_start(False);self.assertEqual(controller.effects,[])
            self.assertEqual(controller._operator_start_state,'WAITING_FOR_CERTIFICATE')
            self.assertIsNotNone(controller._operator_pending)
            # This boolean is an explicit lifecycle seam, not a fabricated
            # cryptographic certificate. Actual watcher/native proof behavior
            # is independently exercised by the combined real SDK suite.
            controller._advance_operator_start(True)
            self.assertEqual(controller.effects,[('protocol.producer_open',{}),('protocol.mine_start',{'producer_slot':0,'duration_seconds':10})])
            self.assertIsNone(controller._operator_pending);self.assertEqual(controller._operator_start_state,'READY')
            controller._advance_operator_start(True)
            self.assertEqual(len(controller.effects),2,'completed startup was replayed')
        finally:controller.close()

    def test_pool_ensure_reopens_matching_signed_book_and_refuses_changed_configuration(self):
        # A native transport lifecycle seam is sufficient for this test of
        # exclusive journal/configuration ownership. No consensus, certified
        # work, share income or payout is claimed or fabricated by the seam.
        bundle=self.ceremony();pin=bundle['pin'];controller=runtime.ProtocolRuntime()
        controller.owner=nodes.NodeProfile.open('Owner0');controller.accounts['Gov0']=accounts.AccountProfile.open('Gov0')
        def offline_node():return SimpleNamespace(anchor=pin,binary=None,_stamp=None,request_stop=lambda:None,close=lambda:None)
        controller.node=offline_node()
        args={'pool':'OperatorPool','account_profile':'Gov0','operator':controller.accounts['Gov0'].public_address(),'commission_bps':25}
        try:
            with patch.object(runtime,'DATA_HOME',self.root/'pool-data'):
                controller.dispatch('protocol.pool_ensure',args)
                book=controller.pools['OperatorPool'];before=deepcopy(book._head);database=book.root/'pool.sqlite3'
                identity=database.stat().st_ino;head=bytes(book._db.execute('SELECT record FROM head').fetchone()[0])
                controller.stop_node();self.assertIsNone(book._lease);self.assertIsNone(book._db)
                controller.node=offline_node();controller._cancel.clear()
                controller.dispatch('protocol.pool_ensure',args)
                reopened=controller.pools['OperatorPool']
                self.assertEqual(reopened._head,before);self.assertEqual(database.stat().st_ino,identity)
                self.assertEqual(bytes(reopened._db.execute('SELECT record FROM head').fetchone()[0]),head)
                controller.stop_node();controller.node=offline_node();controller._cancel.clear()
                with self.assertRaisesRegex(ValueError,'POOL_BOOK_HEAD'):
                    controller.dispatch('protocol.pool_ensure',{**args,'commission_bps':26})
                self.assertEqual(controller.pools,{})
                self.assertEqual(database.stat().st_ino,identity)
                # Failure must release the rejected open lease so that the
                # exact original configuration remains available to resume.
                controller.dispatch('protocol.pool_ensure',args)
                self.assertEqual(controller.pools['OperatorPool']._head,before)
                self.assertEqual(bytes(controller.pools['OperatorPool']._db.execute('SELECT record FROM head').fetchone()[0]),head)
                controller.stop_node();controller.node=offline_node();controller._cancel.clear()
                # The legacy explicit create command must still refuse the
                # existing journal; only ensure is idempotent on matching data.
                with self.assertRaises((ValueError,OSError)):controller.dispatch('protocol.pool_create',args)
                self.assertEqual(database.stat().st_ino,identity)
        finally:controller.close()

    def test_production_operator_modules_do_not_import_test_fixture_key_generators(self):
        for module in (setup,provisioning):
            tree=ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
            imports=[]
            for item in ast.walk(tree):
                if isinstance(item,ast.ImportFrom):imports.append(item.module or '')
                elif isinstance(item,ast.Import):imports.extend(alias.name for alias in item.names)
            self.assertFalse(any(name=='tests' or name.startswith('tests.') for name in imports),'operator workflow imports a test fixture')


class DeferredOperatorLifecycleTests(unittest.TestCase):
    """Finite observer/start orchestration seams; no actual certificate claimed."""
    def controller(self,*,fail=None,stop_on=None,retarget_on=None):
        class Controller(runtime.ProtocolRuntime):
            def __init__(self):super().__init__();self.effects=[]
            def dispatch(self,command,args):
                self.effects.append((command,deepcopy(args)))
                if command==stop_on:self.request_stop()
                if command==retarget_on:self.node=SimpleNamespace(request_stop=lambda:None,close=lambda:None)
                if command==fail:raise ValueError('GG_UNIT_EXTRA_START_FAILED')
                return {}
        controller=Controller();controller.node=SimpleNamespace(request_stop=lambda:None,close=lambda:None)
        config={'producer':True,'pools':[],'relay':None,'account_submissions':[],
                'mining':{'producer_slot':0,'duration_seconds':1},'pool_work':None}
        controller._operator_start_state='WAITING_FOR_CERTIFICATE'
        controller._operator_pending={'node':controller.node,'config':config,'deadline':time.monotonic()+120}
        self.addCleanup(controller.close);return controller

    def test_no_effect_before_poll_certificate_and_deadline_is_finite(self):
        controller=self.controller();pending=controller._operator_pending
        controller._advance_operator_start(False)
        self.assertIs(controller._operator_pending,pending);self.assertEqual(controller.effects,[])
        self.assertEqual(controller._operator_start_state,'WAITING_FOR_CERTIFICATE')
        with patch.object(runtime.time,'monotonic',return_value=pending['deadline']):controller._advance_operator_start(True)
        self.assertIsNone(controller._operator_pending);self.assertEqual(controller.effects,[])
        self.assertEqual(controller._operator_start_state,'FAILED')
        self.assertEqual(controller._operator_start_error,'GG_PROTOCOL_START_CERTIFICATE_TIMEOUT')
        controller._advance_operator_start(True);self.assertEqual(controller.effects,[])

    def test_cancel_or_target_change_cannot_start_extras(self):
        for reason in ('cancel','retarget'):
            controller=self.controller()
            if reason=='cancel':controller._cancel.set()
            else:controller.node=SimpleNamespace(request_stop=lambda:None,close=lambda:None)
            controller._advance_operator_start(True)
            self.assertIsNone(controller._operator_pending);self.assertEqual(controller.effects,[])
            self.assertEqual(controller._operator_start_state,'STOPPED')

    def test_partial_service_failure_is_consumed_and_never_replayed(self):
        controller=self.controller(fail='protocol.mine_start');controller._advance_operator_start(True)
        self.assertEqual([command for command,args in controller.effects],['protocol.producer_open','protocol.mine_start'])
        self.assertIsNone(controller._operator_pending);self.assertEqual(controller._operator_start_state,'FAILED')
        self.assertEqual(controller._operator_start_error,'GG_UNIT_EXTRA_START_FAILED')
        controller._advance_operator_start(True);controller._advance_operator_start(False)
        self.assertEqual(len(controller.effects),2,'partial startup was automatically repeated')

    def test_cancel_or_retarget_during_first_effect_prevents_later_effects(self):
        for option in ({'stop_on':'protocol.producer_open'},{'retarget_on':'protocol.producer_open'}):
            controller=self.controller(**option);controller._advance_operator_start(True)
            self.assertEqual(controller.effects,[('protocol.producer_open',{})])
            self.assertIsNone(controller._operator_pending);self.assertEqual(controller._operator_start_state,'STOPPED')
            controller._advance_operator_start(True);self.assertEqual(len(controller.effects),1)

    def test_failed_poll_never_becomes_startup_readiness(self):
        controller=self.controller();ready=[];advance=controller._advance_operator_start
        def failure():raise ValueError('GG_UNIT_NO_CERTIFICATE')
        def once(value):
            ready.append(value);advance(value);controller._cancel.set()
        with patch.object(controller,'_poll',side_effect=failure),patch.object(controller,'_advance_operator_start',side_effect=once):controller._watch()
        self.assertEqual(ready,[False]);self.assertEqual(controller.effects,[])
        self.assertEqual(controller._operator_start_state,'WAITING_FOR_CERTIFICATE')

    def test_observer_trylock_returns_while_stop_caller_holds_command_lock(self):
        controller=self.controller();returned=threading.Event();failures=[]
        def observer():
            try:controller._advance_operator_start(True)
            except BaseException as error:failures.append(type(error).__name__)
            finally:returned.set()
        worker=threading.Thread(target=observer,name='PUBLIC operator trylock fixture')
        try:
            with controller._control:
                worker.start()
                self.assertTrue(returned.wait(2),'observer blocked on a command lock that stop must retain while joining it')
                self.assertEqual(controller.effects,[]);self.assertIsNotNone(controller._operator_pending)
                controller._thread=worker;controller.stop_node()
            self.assertFalse(worker.is_alive());self.assertEqual(failures,[])
        finally:
            controller.request_stop()
            if worker.ident is not None:worker.join(2)

    def test_stop_joins_observer_before_closing_ingress_and_journals(self):
        controller=self.controller();events=[];release=threading.Event();exited=threading.Event()
        def observer():
            if not release.wait(2):return
            events.append('observer_exited');exited.set()
        worker=threading.Thread(target=observer,name='PUBLIC operator shutdown fixture');worker.start()
        class JoinSeam:
            def join(self,timeout):events.append('join_observer');release.set();worker.join(timeout)
            def is_alive(self):return worker.is_alive()
        def close_ingress():
            self.assertTrue(exited.is_set(),'ingress closed before startup observer joined')
            events.append('ingress_closed')
        def close_book():
            self.assertTrue(exited.is_set(),'journal closed before startup observer joined')
            events.append('book_closed')
        controller._thread=JoinSeam()
        controller._relay=SimpleNamespace(request_stop=lambda:events.append('ingress_stop_requested'),close=close_ingress)
        controller.pools['PublicLifecycleOnly']=SimpleNamespace(close=close_book)
        try:
            controller.stop_node()
            self.assertFalse(worker.is_alive());self.assertIsNone(controller.node)
            self.assertLess(events.index('observer_exited'),events.index('ingress_closed'))
            self.assertLess(events.index('ingress_closed'),events.index('book_closed'))
        finally:release.set();worker.join(2)

    def test_waiting_startup_status_is_not_an_execution_receipt(self):
        controller=runtime.ProtocolRuntime();self.addCleanup(controller.close)
        controller._operator_start_state='WAITING_FOR_CERTIFICATE'
        status=controller.snapshot()['protocol_network']['operator_start']
        self.assertEqual(status['state'],'WAITING_FOR_CERTIFICATE')
        self.assertFalse(status['startup_state_is_execution_receipt'])


class OperatorCommandTypingTests(unittest.TestCase):
    def test_ports_slots_and_finite_seconds_are_integers_and_atomic_money_is_exact_text(self):
        command,args=parse_command('protocol.validator_create profile=Validator owner_profile=Owner p2p_port=22001')
        self.assertEqual(command,'protocol.validator_create');self.assertIs(type(args['p2p_port']),int);self.assertEqual(args['p2p_port'],22001)
        command,args=parse_command('protocol.mine_start producer_slot=1 duration_seconds=60')
        self.assertIs(type(args['producer_slot']),int);self.assertIs(type(args['duration_seconds']),int)
        self.assertEqual((args['producer_slot'],args['duration_seconds']),(1,60))
        command,args=parse_command('protocol.operation_review profile=Gov intent_path=public.json max_fee_atomic=18446744073709551615')
        self.assertIs(type(args['max_fee_atomic']),str);self.assertEqual(args['max_fee_atomic'],'18446744073709551615')


if __name__=='__main__':unittest.main()
