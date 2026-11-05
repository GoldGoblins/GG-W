"""Financial routing/presentation seams; no seam is SDK authenticity evidence.

Signatures, protected profiles, file bounds and CLI observation I/O are real.
Actual SDK execution and signed TCP projection use the integration harness.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_node_store as nodes,gg_consensus_profile as validators,portable_wallet_vault as vault
from backend import lan_dag_runtime as runtime,gg_financial_wire as wire,terminal_cli
from backend.gg_parallel_dag import pack
from tests.test_financial_authority import protected_financial_network
from tests.test_financial_wire import public_financial_wire


class FinancialRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-financial-runtime-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('public financial runtime test vault'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.owners,self.peers,self.profiles,self.bundle,self.contexts=protected_financial_network();self.addCleanup(self.cleanup)
        for peer in self.peers:peer.install_session(self.bundle,_start_gossip=False)
        self.manager=runtime.LanDagRuntime();self.manager._peer=self.peers[0];self.manager._bundle=self.bundle
        self.manager._trusted=self.peers[0]._trusted;self.manager._allowed='127.0.0.0/8'

    def cleanup(self):
        for profile in self.profiles:profile.close()
        for peer in self.peers:peer.stop()
        for owner in self.owners:owner.close()

    def test_status_without_certificate_never_uses_legacy_engine_or_account_mapping(self):
        view=self.manager.snapshot()
        self.assertIsNone(self.peers[0]._engine)
        self.assertEqual(view['mode'],'FINANCIAL_SDK_CERTIFIED_VIEW')
        self.assertEqual(view['dag_consensus']['state'],'WAITING_FOR_CERTIFICATE')
        self.assertFalse(view['dag_consensus']['automatic_checkpoint_submission'])
        self.assertEqual(view['certified_test_accounts'],[])

    def test_explicit_financial_resume_routes_without_file_or_implicit_node_resume(self):
        service=self.peers[0]._proof_service
        with patch.object(service,'resume_signed',return_value={'state':'RETRYING'}) as resume:
            self.assertEqual(self.manager.dispatch('lan.financial_resume',{'producer_index':self.peers[0]._local_indices[0]}),{'state':'RETRYING'})
        resume.assert_called_once_with(self.peers[0]._local_indices[0])
        self.assertFalse(service._retry.snapshot()['worker_active'])

    def test_projection_preserves_large_counters_and_uint64_account_nonce(self):
        service=self.peers[0]._proof_service
        account=self.bundle['body']['consensus']['validators'][0]['body']['account_key']
        value={'blocks':'9007199254740993','applied':'9223372036854775807','rejected':'3',
               'authors':[{'sequence':'1','attempts':'5000','head':'a'*64} for _ in range(6)]}
        # Deliberate state-presentation seam: no verifier or persistence receives it.
        service._certificate_info=({'state':{'financial_dag':value,'accounts':[
            {'address':account,'balance_atomic':'250000000000','nonce':2**64-1}]}},(10,'b'*64),123)
        view=self.manager.snapshot();consensus=view['dag_consensus']
        self.assertEqual(consensus['certified_dag_blocks'],value['blocks'])
        self.assertEqual(consensus['certified_dag_transactions'],value['applied'])
        self.assertEqual(view['financial_accounts'][0]['nonce'],'18446744073709551615')
        self.assertEqual(view['certified_test_accounts'],[])
        result=terminal_cli.foreground_summary('lan.start',view)
        self.assertTrue(result['financial_transactions_enabled']);self.assertFalse(result['mainnet_enabled'])
        self.assertEqual(result['financial']['applied_payments'],value['applied'])
        self.assertEqual(result['financial']['rejected_payments'],'3')

    def test_terminal_summary_keeps_certified_absence_and_exact_proof_height(self):
        # Presentation seam only: no certificate is authenticated in this test.
        body={'mode':'FINANCIAL_SDK_CERTIFIED_VIEW','own_financial_accounts':[{
            'address':'a'*64,'balance_atomic':'0','nonce':'0','exists':False,'state_height':41,'certificate_height':42,
            'verification_scope':'SDK_CERTIFIED_ACCOUNT_MEMBERSHIP_OR_ABSENCE_NOT_FULL_HISTORY_REPLAY'}]}
        summary=terminal_cli.foreground_summary('lan.start',body)
        self.assertEqual(summary['financial']['own_accounts'],body['own_financial_accounts'])

    def test_file_command_keeps_small_command_limit_and_submits_exact_public_signatures(self):
        anchor,_,payment,_,_=public_financial_wire();path=Path(self.temp.name)/'payments.json'
        payments=[payment]*100
        raw=pack({'schema':wire.PAYMENT_DOCUMENT,'genesis_hash':anchor['genesis_hash'],'payments':payments})
        self.assertGreater(len(raw),16384);path.write_bytes(raw)
        self.assertEqual(runtime.read_signed_payments(str(path),anchor),payments)
        service=self.peers[0]._proof_service
        with patch.object(service,'anchor',anchor),patch.object(service,'submit_signed',return_value={'state':'QUEUED'}) as submit:
            result=self.manager.dispatch('lan.financial_submit_file',{'path':str(path),'producer_index':0})
        submit.assert_called_once();self.assertEqual(submit.call_args.args[0].rows(),payments)
        self.assertEqual(submit.call_args.args[1],0);self.assertEqual(result,{'state':'QUEUED'})
        with self.assertRaisesRegex(ValueError,'DOCUMENT_SIZE'):
            self.manager.dispatch('lan.financial_submit',{'payments':payments})
        with patch.object(service,'anchor',anchor),patch.object(service,'submit_signed',return_value={'state':'QUEUED'}) as submit:
            self.manager.dispatch('lan.financial_submit_file',{'path':str(path),'producer_index':0,'transactions_per_block':25})
        self.assertEqual(submit.call_args.kwargs,{'transactions_per_block':25})

    def test_file_cannot_substitute_network_signature_or_private_fields(self):
        anchor,_,payment,_,_=public_financial_wire()
        valid={'schema':wire.PAYMENT_DOCUMENT,'genesis_hash':anchor['genesis_hash'],'payments':[payment]}
        variants=[]
        for key,value in (('genesis_hash','0'*64),('private_key','forbidden input')):
            changed=deepcopy(valid);changed[key]=value;variants.append(changed)
        changed=deepcopy(valid);changed['payments'][0]['body']['amount_atomic']='4';variants.append(changed)
        for document in variants:
            with self.assertRaisesRegex(ValueError,'PAYMENT_DOCUMENT_INVALID'):wire.decode_payment_document(pack(document),anchor)
        raw=pack(valid)
        with self.assertRaises(ValueError):wire.decode_payment_document(raw+b'\n',anchor)
        with self.assertRaises(ValueError):wire.decode_payment_document(b'{"schema":0,"schema":1}',anchor)
        with self.assertRaises(ValueError):runtime.read_signed_payments(self.temp.name,anchor)

    def test_valid_proof_cannot_substitute_another_requested_creator_or_receipt(self):
        service=self.peers[0]._proof_service
        receipt={'financial_receipt':{'context':{'block_hash':'a'*64},'receipt':{'leaf':{'index':7}}}}
        with patch.object(service,'_check_proven_base') as base:
            service._check_requested(receipt,{},'receipt','a'*64+':7')
            with self.assertRaisesRegex(ValueError,'SELECTOR_CHANGED'):service._check_requested(receipt,{},'receipt','b'*64+':7')
            with self.assertRaisesRegex(ValueError,'SELECTOR_CHANGED'):service._check_requested(receipt,{},'receipt','a'*64+':8')
            with self.assertRaisesRegex(ValueError,'SELECTOR_CHANGED'):service._check_requested({'financial_producer':{'producer_index':1}},{},'producer',0)
        self.assertEqual(base.call_count,4)

    def test_receipt_projection_passes_only_certificate_core_to_structural_tip_check(self):
        service=self.peers[0]._proof_service
        # Structural presentation seam, already-authenticated input is the
        # caller's contract. No verifier receives this synthetic packet.
        packet={'schema':'gg.consensus.proof.v1',**service.anchor,
            'state':{'height':9,'state_root':'c'*64},
            'signed_header':{'header':{'height':'10'},'commit':{'block_id':{'hash':'b'*64}}},
            'financial_receipt':{'context':{'block_hash':'a'*64,'order_index':'1'},
                'creator':{'key':'d'*64,'producer_index':0,'sequence':'1'},
                'summary':{'transactions':5000,'applied':4999,'rejected':1}}}
        service._remember_receipt(packet);rows=service.snapshot()['proven_blocks']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['certificate_height'],10)
        self.assertEqual(rows[0]['applied'],4999);self.assertEqual(rows[0]['rejected'],1)
        self.assertFalse(rows[0]['original_payload_authenticated'])


if __name__=='__main__':unittest.main()
