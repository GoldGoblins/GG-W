"""Offline ceremony boundaries with real disposable encrypted profiles/signatures.

The native oracle is explicitly a unit seam here, never certificate/network
evidence. The combined native/CLI acceptance owns the actual oracle execution.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import gg_protocol_provisioning as ceremony
from backend import gg_financial_protocol as protocol
from backend import gg_node_store as nodes,gg_consensus_profile as validators
from backend import gg_financial_account as accounts,portable_wallet_vault as vault
from backend.gg_node_store import pack
from tests.test_durable_node_store import configuration
from tests.test_protocol_integrated_profiles import public_protocol_pin


def report(pin, **options):
    return {'schema':'gg.protocol.genesis-validation.v1','verified':True,'genesis_hash':pin['genesis_hash'],
            'chain_id':pin['genesis']['chain_id'],'initial_state_root':'a'*64,
            'voter_count':len(pin['genesis']['validators']),'producer_count':len(pin['genesis']['financial_dag']['producers']),
            'environment':'TESTNET','certificate_asserted':False}


def changed(pin,mutate):
    result=deepcopy(pin);mutate(result['genesis'])
    result['genesis_hash']=hashlib.sha256(pack(result['genesis'])).hexdigest()
    return protocol.validate_pin(result)


class PublicCeremonyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='gg-offline-ceremony-');cls.addClassCleanup(cls.temp.cleanup)
        cls.stack=ExitStack();cls.addClassCleanup(cls.stack.close);root=Path(cls.temp.name)
        for module,name in ((nodes,'nodes'),(validators,'validators'),(accounts,'accounts')):
            cls.stack.enter_context(patch.object(module,'ROOT',root/name))
        cls.stack.enter_context(vault.session('PUBLIC disposable offline ceremony test password'))
        cls.profiles=[];cls.addClassCleanup(cls.close_profiles)
        cls.context=ceremony.create_context({'schema':ceremony.CONTEXT_SPEC,'chain_id':'ggnet:'+'1'*24,
            'network_id':'2'*64,'genesis_time_unix':1700000100,'environment':'TESTNET'})
        cls.actors=[cls.actor('Member'+str(index),23000+index) for index in range(4)]
        cls.invites=[validator.public_invite() for owner,validator,account in cls.actors]
        cls.before=[(owner._head['entries'],account.snapshot()['next_signing_nonce'],account.snapshot()['signed_batches'])
                    for owner,validator,account in cls.actors]
        cls.producers=[ceremony.initial_producer_invite(owner,validator,account,cls.context,0,'Producer '+str(index),
                        ('windows','linux','termux','other')[index]) for index,(owner,validator,account) in enumerate(cls.actors)]
        cls.after=[(owner._head['entries'],account.snapshot()['next_signing_nonce'],account.snapshot()['signed_batches'])
                   for owner,validator,account in cls.actors]
        fixture=public_protocol_pin()['genesis'];cls.spec={'schema':ceremony.SPEC,'context':cls.context,
            'financial_accounts':{'schema':'gg.financial.account-genesis.v1','max_accounts':'4294967296',
                'allocations':[{'address':cls.actors[0][2].public_address(),'balance_atomic':fixture['supply_atomic']}]},
            'economics':fixture['protocol']['economics'],
            'voting_powers':[{'validator_key':value['body']['validator_key'],'power':'1'} for value in cls.invites],
            'protocol':{name:fixture['protocol'][name] for name in ceremony.LIMIT_FIELDS}}
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            cls.pin=ceremony.assemble(cls.spec,cls.invites,cls.producers)
            cls.endorsements=[ceremony.sign_bootstrap(*actor,cls.pin) for actor in cls.actors]
            cls.bundle=ceremony.assemble_bootstrap(cls.pin,cls.invites,cls.endorsements)

    @classmethod
    def actor(cls,name,port):
        owner=nodes.NodeProfile.create(name+'Owner',configuration());cls.profiles.append(owner)
        account=accounts.AccountProfile.create(name+'Gov',label='Disposable governance account');cls.profiles.append(account)
        validator=validators.ValidatorProfile.create_for_protocol(name+'Validator',owner,label=name,p2p_port=port,account=account)
        cls.profiles.append(validator);return owner,validator,account

    @classmethod
    def close_profiles(cls):
        for profile in reversed(cls.profiles):profile.close()

    def test_fresh_initial_role_proofs_do_not_create_network_or_spend_nonce(self):
        self.assertEqual(self.before,self.after)
        self.assertEqual(self.before,[(0,'0',0)]*4)
        for (owner,validator,account),invite in zip(self.actors,self.producers):
            self.assertEqual(protocol.validate_invite(invite,self.pin['genesis']),invite)
            self.assertEqual(invite['body']['reward_account'],account.public_address())
            self.assertEqual(invite['body']['node_key'],validator.public_invite()['body']['node_key'])
            self.assertIsNone(owner.session())
            self.assertFalse((validator.root/'native').exists())
            self.assertEqual(len(validator._keys),2)
            self.assertEqual(validator.account_reference(),{'profile':account.name,'public_key':account.public_address()})

    def test_public_assembly_is_order_independent_and_has_no_private_defaults(self):
        with patch.object(ceremony,'validate_pin_native',side_effect=report) as oracle:
            self.assertEqual(ceremony.assemble(self.spec,list(reversed(self.invites)),list(reversed(self.producers))),self.pin)
            oracle.assert_called_once()
        for field in ('economics','protocol','voting_powers','financial_accounts'):
            value=deepcopy(self.spec);value.pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):ceremony.assemble(value,self.invites,self.producers)
        value=deepcopy(self.spec);value['private_seed']='FORBIDDEN'
        with self.assertRaises(ValueError):ceremony.assemble(value,self.invites,self.producers)

    def test_power_invite_endpoint_and_producer_conflicts_fail_before_native(self):
        cases=[]
        spec=deepcopy(self.spec);spec['voting_powers'].append(spec['voting_powers'][0]);cases.append((spec,self.invites,self.producers))
        spec=deepcopy(self.spec);spec['voting_powers'].pop();cases.append((spec,self.invites,self.producers))
        cases.append((self.spec,self.invites[:-1]+self.invites[:1],self.producers))
        cases.append((self.spec,self.invites,self.producers+self.producers[:1]))
        value=deepcopy(self.producers);value[0]['body']['network_id']='3'*64;cases.append((self.spec,self.invites,value))
        value=deepcopy(self.invites);value[0]['body']['account_key']=value[1]['body']['account_key'];cases.append((self.spec,value,self.producers))
        with patch.object(ceremony,'validate_pin_native',side_effect=AssertionError('invalid public input reached native')):
            for index,args in enumerate(cases):
                with self.subTest(case=index),self.assertRaises(ValueError):ceremony.assemble(*args)

    def test_context_is_strict_public_testnet_only_and_copied(self):
        value=ceremony.validate_context(self.context);value['network_id']='f'*64
        self.assertEqual(self.context['network_id'],'2'*64)
        for field,bad in (('environment','MAINNET'),('genesis_time_unix',True),('chain_id','anything'),('network_id','F'*64),('seed','hidden')):
            value=deepcopy(self.context);value[field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):ceremony.validate_context(value)
        with self.assertRaises(ValueError):ceremony.create_context(self.context)
        with self.assertRaises(ValueError):ceremony.initial_producer_invite(None,None,None,self.context,0,'label','linux')

    def test_all_initial_voters_and_exact_four_role_signatures_are_required(self):
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            self.assertEqual(ceremony.validate_bootstrap(self.bundle),self.bundle)
            with self.assertRaises(ValueError):ceremony.assemble_bootstrap(self.pin,self.invites,self.endorsements[:3])
            with self.assertRaises(ValueError):ceremony.assemble_bootstrap(self.pin,self.invites,self.endorsements[:3]+self.endorsements[:1])
            for role in ('validator','node','account','owner'):
                values=deepcopy(self.endorsements);values[0][role+'_signature']=values[1][role+'_signature']
                with self.subTest(role=role),self.assertRaises(ValueError):ceremony.assemble_bootstrap(self.pin,self.invites,values)
            values=deepcopy(self.endorsements);values[0]['node_signature'],values[0]['owner_signature']=values[0]['owner_signature'],values[0]['node_signature']
            with self.assertRaises(ValueError):ceremony.assemble_bootstrap(self.pin,self.invites,values)
            for field in ('verified','trusted','certificate_asserted','private_key'):
                value=deepcopy(self.bundle);value[field]=True
                with self.subTest(extra=field),self.assertRaises(ValueError):ceremony.validate_bootstrap(value)

    def test_other_valid_economics_allocation_power_and_time_need_new_final_consent(self):
        mutations=[lambda g:g['protocol']['economics'].__setitem__('min_fee_atomic','11'),
            lambda g:g['financial_accounts']['allocations'][0].__setitem__('address',self.actors[1][2].public_address()),
            lambda g:g['protocol']['committee']['members'][0].__setitem__('power','2'),
            lambda g:g['protocol']['economics'].__setitem__('tail_reward_atomic','2'),
            lambda g:(g.__setitem__('genesis_time_unix',g['genesis_time_unix']+1),g['financial_dag'].__setitem__('started_at_ns',str(g['genesis_time_unix']*10**9)))]
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            for index,mutate in enumerate(mutations):
                alternative=changed(self.pin,mutate)
                self.assertNotEqual(alternative['genesis_hash'],self.pin['genesis_hash'])
                with self.subTest(change=index),self.assertRaises(ValueError):
                    ceremony.assemble_bootstrap(alternative,self.invites,self.endorsements)
            # A hash-field-only comparison is insufficient: even an attacker
            # replacing the body hash still lacks signatures over the new pin.
            values=deepcopy(self.endorsements)
            for value in values:value['body']['genesis_hash']=alternative['genesis_hash']
            with self.assertRaises(ValueError):ceremony.assemble_bootstrap(alternative,self.invites,values)

    def test_same_pin_retry_is_exact_and_conflicting_pin_is_durably_refused(self):
        actor=self.actors[0]
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            self.assertEqual(ceremony.sign_bootstrap(*actor,self.pin),self.endorsements[0])
            alternative=changed(self.pin,lambda g:g['protocol']['economics'].__setitem__('min_fee_atomic','12'))
            with self.assertRaisesRegex(ValueError,'ALREADY_BOUND'):ceremony.sign_bootstrap(*actor,alternative)
        self.assertEqual(actor[1].anchor(),self.pin);self.assertEqual(actor[2].anchor(),self.pin)

    def test_bound_initial_invite_reexports_exact_nonce_and_refuses_changed_identity(self):
        actor=self.actors[0]
        self.assertEqual(ceremony.initial_producer_invite(*actor,self.context,0,'Producer 0','windows'),self.producers[0])
        for slot,label,platform in ((0,'Other name','windows'),(0,'Producer 0','linux'),(1,'Producer 0','windows'),(True,'Producer 0','windows'),(0,'x\n','windows')):
            with self.subTest(slot=slot,label=label,platform=platform),self.assertRaises(ValueError):
                ceremony.initial_producer_invite(*actor,self.context,slot,label,platform)
        context=deepcopy(self.context);context['network_id']='3'*64
        with self.assertRaises(ValueError):ceremony.initial_producer_invite(*actor,context,0,'Producer 0','windows')

    def test_wrong_owner_or_governance_wallet_cannot_accept(self):
        owner,validator,account=self.actors[0]
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            with self.assertRaisesRegex(ValueError,'OWNER_MISMATCH'):ceremony.sign_bootstrap(self.actors[1][0],validator,account,self.pin)
            with self.assertRaisesRegex(ValueError,'OWNED_ACCOUNT_REQUIRED'):ceremony.sign_bootstrap(owner,validator,self.actors[1][2],self.pin)
        with self.assertRaises(ValueError):ceremony.sign_bootstrap(None,validator,account,self.pin)

    def test_native_rejection_precedes_any_account_or_validator_bind(self):
        actor=self.actor('Rejected',23010)
        with patch.object(ceremony,'validate_pin_native',side_effect=ValueError('PUBLIC native rejection')):
            with self.assertRaisesRegex(ValueError,'native rejection'):ceremony.sign_bootstrap(*actor,self.pin)
        self.assertIsNone(actor[1].anchor());self.assertIsNone(actor[2].anchor())

    def test_partial_bind_returns_no_acceptance_and_resumes_only_same_pin(self):
        owner,validator,account=self.actor('Partial',23011)
        spec=deepcopy(self.spec);invites=self.invites[:3]+[validator.public_invite()]
        spec['voting_powers']=[{'validator_key':value['body']['validator_key'],'power':'1'} for value in invites]
        producers=self.producers[:3]+[ceremony.initial_producer_invite(owner,validator,account,self.context,0,'Partial','linux')]
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            pin=ceremony.assemble(spec,invites,producers)
            def partial(*args,**kwargs):
                account.bind(args[0]);raise OSError('PUBLIC injected after account commit')
            with patch.object(validator,'bind_protocol',side_effect=partial):
                with self.assertRaisesRegex(OSError,'after account commit'):ceremony.sign_bootstrap(owner,validator,account,pin)
            self.assertEqual(account.anchor(),pin);self.assertIsNone(validator.anchor())
            alternative=changed(pin,lambda g:g['protocol']['economics'].__setitem__('min_fee_atomic','13'))
            with self.assertRaisesRegex(ValueError,'ALREADY_BOUND'):ceremony.sign_bootstrap(owner,validator,account,alternative)
            signed=ceremony.sign_bootstrap(owner,validator,account,pin)
            self.assertEqual(ceremony.sign_bootstrap(owner,validator,account,pin),signed)
            self.assertEqual(validator.anchor(),pin)
        account.close();reopened=accounts.AccountProfile.open(account.name);self.profiles.append(reopened)
        self.assertEqual(reopened.anchor(),pin)

    def test_unavailable_lease_and_noninitial_member_cannot_sign(self):
        owner,validator,account=self.actor('Unavailable',23012)
        with patch.object(ceremony,'validate_pin_native',side_effect=report):
            with self.assertRaisesRegex(ValueError,'INITIAL_MEMBER_REQUIRED'):ceremony.sign_bootstrap(owner,validator,account,self.pin)
            self.assertIsNone(account.anchor());self.assertIsNone(validator.anchor())
            account.close()
            with self.assertRaisesRegex(ValueError,'OWNED_PROFILES_REQUIRED'):ceremony.sign_bootstrap(owner,validator,account,self.pin)


class NativeGenesisAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-public-genesis-adapter-');self.addCleanup(self.temp.cleanup)
        self.binary=Path(self.temp.name)/'public-native-fixture';self.binary.write_bytes(b'PUBLIC unit-only placeholder')
        info=self.binary.stat();self.stamp=(info.st_size,info.st_mtime_ns);self.pin=public_protocol_pin()

    def response(self,value=None,**kwargs):
        return SimpleNamespace(returncode=0,stdout=pack(report(self.pin) if value is None else value),**kwargs)

    def test_native_adapter_uses_only_canonical_public_stdin_and_finite_limits(self):
        with patch.object(ceremony.native_pipes.GENESIS_VALIDATE,'run',return_value=self.response()) as run:
            self.assertEqual(ceremony.validate_pin_native(self.pin,binary=self.binary,stamp=self.stamp),report(self.pin))
        args,kwargs=run.call_args
        self.assertEqual(args[0],[str(self.binary),'validate-protocol-genesis'])
        self.assertEqual(kwargs['input'],pack(self.pin));self.assertEqual(kwargs['timeout'],6)
        self.assertEqual(kwargs['env']['GOMEMLIMIT'],'96MiB');self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)
        self.assertNotIn('cwd',kwargs)

    def test_default_adapter_requires_existing_checked_native_binary(self):
        with patch.object(ceremony.native,'_installed_binary',return_value=self.binary) as installed,patch.object(ceremony.native,'_validate_binary_at',return_value=self.stamp) as validate,patch.object(ceremony.native_pipes.GENESIS_VALIDATE,'run',return_value=self.response()):
            ceremony.validate_pin_native(self.pin)
        installed.assert_called_once_with(ceremony.native.TOOLS);validate.assert_called_once_with(self.binary.parent,self.binary)

    def test_native_adapter_rejects_changed_binary_and_invalid_or_ambiguous_output(self):
        with patch.object(ceremony.native_pipes.GENESIS_VALIDATE,'run') as run:
            with self.assertRaisesRegex(ValueError,'BINARY_CHANGED'):ceremony.validate_pin_native(self.pin,binary=self.binary,stamp=(0,0))
            run.assert_not_called()
        responses=[SimpleNamespace(returncode=1,stdout=pack({'error':'GG_PROTOCOL_GENESIS_INVALID','verified':False})),
            SimpleNamespace(returncode=0,stdout=b' '*8193),SimpleNamespace(returncode=0,stdout=pack(report(self.pin))+b'\n')]
        for field,value in (('verified',False),('certificate_asserted',True),('voter_count',True),('environment','MAINNET'),('private','anything'),('genesis_hash','f'*64)):
            answer=report(self.pin);answer[field]=value;responses.append(self.response(answer))
        for index,response in enumerate(responses):
            with self.subTest(response=index),patch.object(ceremony.native_pipes.GENESIS_VALIDATE,'run',return_value=response),self.assertRaises(ValueError):
                ceremony.validate_pin_native(self.pin,binary=self.binary,stamp=self.stamp)
        def change(*args,**kwargs):
            self.binary.write_bytes(b'PUBLIC changed binary fixture');return self.response()
        with patch.object(ceremony.native_pipes.GENESIS_VALIDATE,'run',side_effect=change),self.assertRaisesRegex(ValueError,'BINARY_CHANGED'):
            ceremony.validate_pin_native(self.pin,binary=self.binary,stamp=self.stamp)


if __name__=='__main__':unittest.main()
