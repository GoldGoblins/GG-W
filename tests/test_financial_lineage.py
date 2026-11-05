"""Real protected journal/signatures; producer SDK verification is a policy seam.

These are not SDK certificates or finality evidence. Independent native and
real-validator integration tests must establish source-v3 execution separately.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch
from backend import gg_financial_dag as financial,gg_financial_wire as wire,gg_financial_producer as journal,gg_node_store as nodes
from backend.gg_parallel_dag import pack
from tests import test_financial_producer as journal_fixture
from tests.test_financial_authority import protected_financial_network


class FinancialLineageJournalTests(unittest.TestCase):
    cleanup=journal_fixture.FinancialProducerJournalTests.cleanup
    open=journal_fixture.FinancialProducerJournalTests.open

    def setUp(self):
        fixture=patch('tests.test_financial_producer.protected_financial_network',side_effect=lambda:protected_financial_network(source_schema=financial.LINEAGE_SOURCE_SCHEMA))
        fixture.start();self.addCleanup(fixture.stop)
        journal_fixture.FinancialProducerJournalTests.setUp(self)
        self.packet['state']['financial_dag'].update(schema='gg.financial-dag.commitment.v3',lineage_root='0'*64)
        self.height=0

    def payments(self,count):
        signer=next(profile for profile in self.validators if profile.public_invite()['body']['account_key']==self.body['sender'])
        result=[]
        for nonce in range(count):
            body={**self.body,'nonce':nonce};result.append({'body':body,'signature':signer._keys[2].sign_message(pack(body)).hex()})
        return result

    def advanced(self,epoch,originals=(),selected=0):
        self.height+=1;packet=deepcopy(self.packet);root=format(self.height+10,'064x')
        packet['state'].update(height=self.height,state_root=root)
        packet['signed_header']['header']['height']=str(self.height+1);packet['signed_header']['commit']['block_id']['hash']=format(self.height+20,'064x')
        value=packet['state']['financial_dag'];value.update(epoch=str(epoch),checkpoint=str(self.height),last_cut=format(epoch+32,'064x'),epoch_base_rank='5')
        proof=packet['financial_producer'];proof.update(height=self.height,state_root=root,epoch=str(epoch))
        if selected:
            original=originals[selected-1];body=nodes.unpack(original['wire'])['body']
            value['authors'][self.indices[0]].update(sequence=str(selected),epoch=body['epoch'],head=original['hash'],attempts=str(selected))
            value['lineage_root']='6'*64
            proof.update(sequence=str(selected+1),parent=original['hash'],parent_rank=body['rank'])
        return packet

    def test_same_originals_survive_repeated_cuts_without_new_producer_signatures(self):
        writer=self.open();payments=self.payments(3);originals=writer.produce_batch(self.packet,payments,1)
        for epoch in (2,3,4):
            packet=self.advanced(epoch);plan=writer.pending_batch(packet,self.indices[0])
            retried=writer.retry_batch(packet,plan,wire.authenticate_payments(plan['payments'],writer.anchor))
            self.assertEqual([row['wire'] for row in retried],[row['wire'] for row in originals])
            self.assertEqual([row['wire'] for row in writer.produce_batch(packet,payments,1)],[row['wire'] for row in originals])
            self.assertEqual(writer.snapshot()['originals'],3)

    def test_certified_partial_prefix_trims_only_exact_old_originals(self):
        writer=self.open();values=self.payments(3);originals=writer.produce_batch(self.packet,values,1)
        plan=writer.pending_batch(self.packet,self.indices[0]);packet=self.advanced(4,originals,1)
        retried=writer.retry_batch(packet,plan,wire.authenticate_payments(values,writer.anchor))
        self.assertEqual([row['hash'] for row in retried],[row['hash'] for row in originals[1:]])
        self.assertEqual(writer.snapshot()['originals'],3)

    def test_mixed_signing_epochs_extend_the_same_chain_and_prefix_codec(self):
        writer=self.open();values=self.payments(2);first=writer.produce_batch(self.packet,values[:1],1)
        packet=self.advanced(3);mixed=writer.produce_batch(packet,values,1)
        self.assertEqual(mixed[0]['wire'],first[0]['wire'])
        self.assertEqual([nodes.unpack(row['wire'])['body']['epoch'] for row in mixed],['1','3'])
        encoded=wire.encode_own_prefix(writer.anchor,[row['wire'] for row in mixed]);document=nodes.unpack(encoded)
        self.assertEqual(document['epoch'],'3');self.assertEqual(wire.decode_own_prefix(encoded,writer.anchor),[row['wire'] for row in mixed])
        for epoch in ('2','4'):
            invalid={**document,'epoch':epoch}
            with self.assertRaisesRegex(ValueError,'OWN_PREFIX_INVALID'):wire.decode_own_prefix(pack(invalid),writer.anchor)
        future=self.advanced(4);_,records=wire.batch(future,[row['wire'] for row in mixed]);self.assertEqual(len(records),2)
        with self.assertRaises(ValueError):wire.decode_block(first[0]['wire'],writer.source,writer.anchor['genesis_hash'],4)
        self.assertEqual(wire.decode_block(first[0]['wire'],writer.source,writer.anchor['genesis_hash'],4,allow_previous_epoch=True)['hash'],first[0]['hash'])

    def test_archived_pending_and_new_tail_cold_reopen_without_resigning(self):
        writer=self.open();values=self.payments(4);originals=writer.produce_batch(self.packet,values[:3],1)
        with self.profile._lock:writer._archive()
        packet=self.advanced(5,originals,2);tail=writer.produce_batch(packet,values[2:],1)
        self.assertEqual(tail[0]['wire'],originals[2]['wire']);self.assertEqual(writer.snapshot()['originals'],4)
        name=self.profile.name;writer.close();self.profile.close();self.packet=packet
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened);writer=self.open(reopened)
        plan=writer.pending_batch(packet,self.indices[0]);self.assertEqual([row['epoch'] for row in plan['blocks']],[1,5])
        self.assertEqual([row['wire'] for row in writer.retry_batch(packet,plan,wire.authenticate_payments(plan['payments'],writer.anchor))],[row['wire'] for row in tail])
        self.assertEqual(writer.snapshot()['archive_chunks'],1)
        for table in ('financial_proposals','financial_archived'):
            query='SELECT epoch,sequence,identifier FROM '+table+' WHERE producer=? ORDER BY epoch DESC,sequence DESC LIMIT ?'
            facts=' '.join(str(row) for row in reopened._db.execute('EXPLAIN QUERY PLAN '+query,(self.indices[0],9)))
            self.assertIn('SEARCH',facts);self.assertNotIn('TEMP B-TREE',facts)

    def test_unchanged_creator_context_can_cross_a_cut_but_keeps_newer_floor(self):
        writer=self.open();old=writer.produce_batch(self.packet,[self.payment],1)
        newer=self.advanced(3);core=journal._core(newer);self.profile.save_consensus_certificate(core)
        with patch.object(journal.native,'_verify_public',return_value={'financial_dag_commitment':core['state']['financial_dag']}) as verify:
            retried=writer.produce_batch(self.packet,[self.payment],1)
        self.assertTrue(verify.called);self.assertEqual(retried[0]['wire'],old[0]['wire']);self.assertEqual(self.profile.consensus_observation()['packet'],core)

    def test_source_v3_policy_is_explicit_and_never_upgrades_a_v2_source(self):
        anchor=self.context.anchor();source=deepcopy(anchor['genesis']['financial_dag'])
        self.assertEqual(financial.validate_source(source,anchor['genesis']),source)
        source['policy']=financial.policy()
        with self.assertRaisesRegex(ValueError,'SOURCE_INVALID'):financial.validate_source(source,anchor['genesis'])
        self.assertEqual(financial.make_session_source(anchor['genesis'],source['producers'],source['allowed_producers'],source['network_id'],source['started_at_ns'])['schema'],financial.LINEAGE_SOURCE_SCHEMA)
        legacy=financial.make_session_source(anchor['genesis'],source['producers'],source['allowed_producers'],source['network_id'],source['started_at_ns'],schema=financial.SESSION_SOURCE_SCHEMA)
        self.assertEqual(legacy['schema'],financial.SESSION_SOURCE_SCHEMA)
        self.assertEqual(financial.validate_source(legacy,anchor['genesis']),legacy)

    def test_authority_adapter_accepts_native_checked_v3_and_uses_original_creator_parent(self):
        from backend.gg_financial_authority import OwnedFinancialAuthority
        from unittest.mock import Mock
        controller=object.__new__(OwnedFinancialAuthority);controller.anchor=self.context.anchor();controller.binary=None;controller._stamp=None
        packet=self.advanced(4);value=packet['state']['financial_dag']
        controller._check_financial_result(packet,{'financial_dag_commitment':value,'financial_history_replay_verified':False})
        controller._check_proof_epoch=Mock(return_value='owned-test-epoch')
        controller._public_query=Mock(side_effect=AssertionError('zero creator needs no disk witness'))
        with patch.object(journal.native,'_verify_public',return_value={'SDK_policy_seam':True}):
            proof=controller.producer_context(self.indices[0],packet=journal._core(packet))['financial_producer']
        self.assertEqual(proof['parent'],self.packet['financial_producer']['parent']);self.assertEqual(proof['parent_rank'],'0')
        writer=self.open();originals=writer.produce_batch(self.packet,[self.payment],1);selected=self.advanced(5,originals,1)
        expected={**selected['financial_producer'],'parent_path':[]};controller._public_query=Mock(return_value=expected)
        with patch.object(journal.native,'_verify_public',return_value={'SDK_policy_seam':True}):
            self.assertEqual(controller.producer_context(self.indices[0],packet=journal._core(selected))['financial_producer'],expected)
        controller._public_query.assert_called_once()
