"""Real encrypted ownership/signatures/SQLite; SDK verification is a policy seam.

The structural context below is deliberately NOT a real SDK certificate. Only
the native verifier call is mocked; actual SDK financial execution is tested
independently. These tests prove journal/ownership behavior, not finality.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_node_store as nodes,gg_consensus_profile as validators,portable_wallet_vault as vault
from backend import gg_financial_dag as financial,gg_financial_producer as journal
from backend.gg_parallel_dag import pack
from tests.test_financial_authority import protected_financial_network


def structural_context(context,index):
    anchor=context.anchor();source=anchor['genesis']['financial_dag']
    marker=hashlib.sha256(financial.DOMAIN+b'DAG-GENESIS\0'+pack({'anchor':anchor['genesis_hash'],'source':financial.source_hash(source)})).hexdigest()
    value={'schema':'gg.financial-dag.commitment.v2','epoch':'1','checkpoint':'0',
           'anchor':anchor['genesis_hash'],'source_hash':financial.source_hash(source),'last_cut':marker,'epoch_base_rank':'0',
           'authors':[{'attempts':'0','epoch':'0','head':marker,'key':key,'sequence':'0'} for key in source['producers']]}
    return {'schema':'gg.consensus.proof.v1',**anchor,'state':{'height':0,'state_root':'2'*64,'financial_dag':value},
            'signed_header':{'header':{'height':'1'},'commit':{'block_id':{'hash':'1'*64}}},
            'financial_producer':{'schema':'gg.financial-dag.producer-context.v1','epoch':'1','genesis_hash':anchor['genesis_hash'],
                'height':0,'parent':marker,'parent_path':[],'parent_rank':'0','producer_index':index,'sequence':'1',
                'source_hash':financial.source_hash(source),'state_root':'2'*64}}


class FinancialProducerJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-financial-journal-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('public financial journal test vault'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.owners,self.peers,self.validators,self.bundle,self.contexts=protected_financial_network();self.writers=[];self.addCleanup(self.cleanup)
        self.verify=self.stack.enter_context(patch.object(financial,'verify_producer',return_value={'policy_seam':True}))
        self.context=self.contexts[0];self.profile=self.context.owner
        _,self.indices=journal._contract(self.profile);self.packet=structural_context(self.context,self.indices[0])
        member=next(profile for profile in self.validators if profile.public_invite()['body']['owner_peer_key']==self.context.public_key)
        sender=member.public_invite()['body']['account_key'];recipient=next(key for key in self.context.anchor()['genesis']['accounts'] if key!=sender)
        self.body={'amount_atomic':'3','chain_id':self.context.anchor()['genesis']['chain_id'],'genesis_hash':self.context.anchor()['genesis_hash'],
                   'nonce':0,'recipient':recipient,'sender':sender,'version':1}
        self.payment={'body':self.body,'signature':member._keys[2].sign_message(pack(self.body)).hex()}

    def cleanup(self):
        for writer in self.writers:writer.close()
        for profile in self.validators:profile.close()
        for peer in self.peers:peer.stop()
        for profile in self.owners:profile.close()

    def open(self,profile=None):
        writer=journal.OwnedFinancialProducer.open(profile or self.profile,self.bundle,self.packet);self.writers.append(writer);return writer

    def test_commits_original_before_return_and_retry_never_resigns_sequence(self):
        writer=self.open();original=writer.produce(self.packet,[self.payment],created_at_ns=int(writer.source['started_at_ns']))
        self.assertFalse(original['SDK_selected']);self.assertEqual(writer.snapshot()['originals'],1)
        self.assertEqual(writer.original(original['hash']),original['wire'])
        retry=writer.produce(self.packet,[self.payment],created_at_ns=int(writer.source['started_at_ns'])+1)
        self.assertEqual(retry['wire'],original['wire']);self.assertEqual(writer.snapshot()['originals'],1)
        changed=deepcopy(self.payment);changed['body']['amount_atomic']='4'
        member=next(profile for profile in self.validators if profile.public_invite()['body']['account_key']==self.body['sender'])
        changed['signature']=member._keys[2].sign_message(pack(changed['body'])).hex()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_PENDING_ORIGINAL_REQUIRED'):writer.produce(self.packet,[changed])
        with self.assertRaisesRegex(ValueError,'GG_PRODUCER_USE_OWN_JOURNAL'):self.profile.append('dag',[b'cannot bypass journal'])

    def test_cold_profile_replays_exact_original_and_excludes_second_writer(self):
        writer=self.open();original=writer.produce(self.packet,[self.payment],created_at_ns=int(writer.source['started_at_ns']))
        with self.assertRaisesRegex(ValueError,'GG_PRODUCER_WRITER_ALREADY_OWNED'):self.open()
        name=self.profile.name;writer.close();self.profile.close()
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened)
        resumed=self.open(reopened)
        self.assertEqual(resumed.original(original['hash']),original['wire'])
        self.assertEqual(resumed.produce(self.packet,[self.payment])['wire'],original['wire'])

    def test_failed_commit_returns_no_original_and_faults_owned_store(self):
        writer=self.open()
        with patch.object(self.profile,'_commit',side_effect=OSError('owned injected write fault')):
            with self.assertRaises((ValueError,OSError)):writer.produce(self.packet,[self.payment],created_at_ns=int(writer.source['started_at_ns']))
        self.assertTrue(self.profile._failed)
        with self.assertRaises(ValueError):writer.produce(self.packet,[self.payment])

    def test_changed_original_fails_closed_on_cold_open(self):
        writer=self.open();original=writer.produce(self.packet,[self.payment],created_at_ns=int(writer.source['started_at_ns']))
        path=self.profile.root/'node.sqlite3';name=self.profile.name;writer.close();self.profile.close()
        database=sqlite3.connect(path)
        try:database.execute('UPDATE financial_proposals SET wire=?',(original['wire']+b' ',));database.commit()
        finally:database.close()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_JOURNAL_INVALID'):nodes.NodeProfile.open(name)

    def test_recovery_cancellation_keeps_its_original_reason(self):
        writer=self.open();writer.produce(self.packet,[self.payment],created_at_ns=int(writer.source['started_at_ns']))
        def stop():raise ValueError('GG_OWNED_RECOVERY_CANCELLED')
        with self.assertRaisesRegex(ValueError,'GG_OWNED_RECOVERY_CANCELLED'):journal.validate_stored_profile(self.profile,check=stop)

    def test_unknown_selected_signature_cannot_replace_missing_local_history(self):
        writer=self.open();packet=deepcopy(self.packet);packet['state']['height']=1;packet['signed_header']['header']['height']='2'
        author=packet['state']['financial_dag']['authors'][self.indices[0]];author.update(sequence='1',epoch='1',head='3'*64)
        packet['financial_producer'].update(height=1,sequence='2')
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_UNKNOWN_OWN_SELECTED_BLOCK'):writer.observe(packet)
        self.assertEqual(writer.snapshot()['last_error'],'GG_FINANCIAL_UNKNOWN_OWN_SELECTED_BLOCK')

    def later_empty_certificate(self):
        self.packet['state']['accounts']=[{'address':key,'balance_atomic':'250000000000','nonce':0}
            for key in self.context.anchor()['genesis']['accounts']]
        newer=journal._core(self.packet);newer['state'].update(height=1,state_root='4'*64)
        newer['signed_header']['header']['height']='2';newer['signed_header']['commit']['block_id']['hash']='5'*64
        return newer

    def test_empty_SDK_height_advance_keeps_newer_floor_and_exact_old_signing_proof(self):
        newer=self.later_empty_certificate();writer=self.open();self.profile.save_consensus_certificate(newer)
        with patch.object(journal.native,'_verify_public',return_value={'financial_dag_commitment':newer['state']['financial_dag']}) as verify:
            result=writer.produce(self.packet,[self.payment])
        self.assertTrue(verify.called);self.assertEqual(writer.snapshot()['certificate_height'],2)
        self.assertEqual(self.profile.consensus_observation()['packet'],newer)
        raw=bytes(self.profile._db.execute('SELECT packet FROM financial_contexts').fetchone()[0])
        self.assertEqual(nodes.unpack(raw),self.packet)
        self.assertEqual(writer.original(result['hash']),result['wire'])

    def test_account_progress_does_not_block_an_unchanged_creator_context(self):
        newer=self.later_empty_certificate();writer=self.open()
        newer['state']['accounts'][0]['nonce']=1;self.profile.save_consensus_certificate(newer)
        with patch.object(journal.native,'_verify_public',return_value={'financial_dag_commitment':newer['state']['financial_dag']}) as verify:
            original=writer.produce(self.packet,[self.payment])
        verify.assert_called_once();self.assertEqual(writer.original(original['hash']),original['wire'])
        self.assertEqual(writer.snapshot()['certificate_height'],2)

    def test_unverifiable_newer_certificate_never_authorizes_old_context(self):
        newer=self.later_empty_certificate();writer=self.open();self.profile.save_consensus_certificate(newer)
        with patch.object(journal.native,'_verify_public',side_effect=ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')):
            with self.assertRaisesRegex(ValueError,'CERTIFICATE_INVALID'):writer.produce(self.packet,[self.payment])
        self.assertEqual(writer.snapshot()['originals'],0)

    def test_other_creators_can_advance_without_stalling_this_creator(self):
        newer=self.later_empty_certificate();writer=self.open()
        value=newer['state']['financial_dag'];value['checkpoint']='1'
        other=next(index for index in range(6) if index not in self.indices)
        value['authors'][other].update(sequence='1',epoch='1',head='6'*64,attempts='5000')
        self.profile.save_consensus_certificate(newer)
        with patch.object(journal.native,'_verify_public',return_value={'financial_dag_commitment':value}) as verify:
            writer.produce(self.packet,[self.payment])
        verify.assert_called_once();self.assertEqual(writer.snapshot()['originals'],1)

    def test_epoch_cut_or_own_creator_change_still_rejects_old_context_before_signing(self):
        newer=self.later_empty_certificate();writer=self.open()
        newer['state']['financial_dag']['epoch']='2';self.profile.save_consensus_certificate(newer)
        with patch.object(journal.native,'_verify_public') as verify:
            with self.assertRaisesRegex(ValueError,'STALE_CONTEXT'):writer.produce(self.packet,[self.payment])
        verify.assert_not_called();self.assertEqual(writer.snapshot()['originals'],0)

    def test_missing_or_changed_operational_fields_cannot_authorize_an_old_proof(self):
        value=self.packet['state']['financial_dag'];index=self.indices[0]
        self.assertTrue(journal._same_creator_context(value,deepcopy(value),index))
        for field in ('anchor','source_hash','epoch','last_cut','epoch_base_rank'):
            changed=deepcopy(value);changed.pop(field)
            self.assertFalse(journal._same_creator_context(value,changed,index))
        changed=deepcopy(value);changed['authors'][index]['sequence']='1'
        self.assertFalse(journal._same_creator_context(value,changed,index))

    def test_atomic_pipeline_retains_exact_chain_and_cold_recovers_each_context(self):
        writer=self.open();values=[self.payment]*3
        originals=writer.produce_batch(self.packet,values,1,created_at_ns=int(writer.source['started_at_ns']))
        self.assertEqual(len(originals),3);self.assertEqual(writer.snapshot()['originals'],3)
        for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])
        retry=writer.produce_batch(self.packet,values,1,created_at_ns=int(writer.source['started_at_ns'])+1000)
        self.assertEqual([row['wire'] for row in retry],[row['wire'] for row in originals])
        name=self.profile.name;writer.close();self.profile.close()
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened)
        restored=journal.OwnedFinancialProducer.open(reopened,self.bundle,self.packet);self.writers.append(restored)
        self.assertEqual(restored.snapshot()['originals'],3)
        self.assertEqual([restored.original(row['hash']) for row in originals],[row['wire'] for row in originals])

    def test_pipeline_appends_without_resigning_or_changing_existing_intent(self):
        writer=self.open();first=writer.produce_batch(self.packet,[self.payment],1)
        extended=writer.produce_batch(self.packet,[self.payment]*3,1)
        self.assertEqual(extended[0]['wire'],first[0]['wire']);self.assertEqual(writer.snapshot()['originals'],3)
        changed=deepcopy(self.payment);changed['body']['amount_atomic']='4'
        member=next(profile for profile in self.validators if profile.public_invite()['body']['account_key']==self.body['sender'])
        changed['signature']=member._keys[2].sign_message(pack(changed['body'])).hex()
        with self.assertRaisesRegex(ValueError,'PENDING_ORIGINAL_REQUIRED'):writer.produce_batch(self.packet,[changed,self.payment,self.payment],1)
        self.assertEqual(writer.snapshot()['originals'],3)
        with self.assertRaisesRegex(ValueError,'PIPELINE_LIMIT'):writer.produce_batch(self.packet,[self.payment]*9,1)

    def test_failed_pipeline_commit_exposes_no_partial_result(self):
        writer=self.open()
        with patch.object(self.profile,'_commit',side_effect=OSError('owned atomic pipeline write fault')):
            with self.assertRaises((ValueError,OSError)):writer.produce_batch(self.packet,[self.payment]*3,1)
        self.assertTrue(self.profile._failed)
        name=self.profile.name;writer.close();self.profile.close()
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened)
        self.assertEqual(reopened._meta['financial_producer']['head']['records'],0)

    def test_private_prefix_context_cannot_reference_a_missing_or_other_creator_record(self):
        writer=self.open();rows=writer.produce_batch(self.packet,[self.payment]*2,1)
        packets=[nodes.unpack(bytes(row[0])) for row in self.profile._db.execute('SELECT packet FROM financial_contexts')]
        child=next(packet for packet in packets if packet.get('own_prefix'))
        with self.assertRaises(ValueError):journal._derived_signing_context(child,{})
        invalid=deepcopy(child);invalid['verified']=True
        with self.assertRaises(ValueError):journal._derived_signing_context(invalid,{})
        wrong={rows[0]['hash']:{'producer':(self.indices[0]+1)%6,'epoch':1,'sequence':1,'rank':1,'parents':[self.packet['financial_producer']['parent']]}}
        with self.assertRaises(ValueError):journal._derived_signing_context(child,wrong)
        self.assertEqual(len(rows),2)

    def test_partial_selection_and_epoch_cut_can_restart_below_old_unselected_maximum(self):
        writer=self.open();member=next(profile for profile in self.validators if profile.public_invite()['body']['account_key']==self.body['sender'])
        values=[]
        for nonce in range(3):
            body={**self.body,'nonce':nonce};values.append({'body':body,'signature':member._keys[2].sign_message(pack(body)).hex()})
        old=writer.produce_batch(self.packet,values,1)
        cut=deepcopy(self.packet);cut['state'].update(height=2,state_root='4'*64)
        cut['signed_header']['header']['height']='3';cut['signed_header']['commit']['block_id']['hash']='5'*64
        value=cut['state']['financial_dag'];value.update(epoch='2',checkpoint='2',last_cut='6'*64,epoch_base_rank='1')
        value['authors'][self.indices[0]].update(sequence='1',epoch='1',attempts='1',head=old[0]['hash'])
        cut['financial_producer'].update(height=2,state_root='4'*64,epoch='2',sequence='2',parent='6'*64,parent_rank='1')
        remaining=writer.produce_batch(cut,values[1:],1)
        self.assertEqual([journal.wire.decode_block(row['wire'],writer.source,writer.anchor['genesis_hash'],2)['sequence'] for row in remaining],[2,3])
        self.assertEqual(writer.snapshot()['originals'],5)
        for row in old:self.assertEqual(writer.original(row['hash']),row['wire'])
        name=self.profile.name;writer.close();self.profile.close()
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened)
        self.assertEqual(reopened._meta['financial_producer']['head']['records'],5)

    def retry_context(self,originals,selected,epoch=1,height=1):
        packet=deepcopy(self.packet);packet['state'].update(height=height,state_root='4'*64)
        packet['signed_header']['header']['height']=str(height+1);packet['signed_header']['commit']['block_id']['hash']=format(height+4,'064x')
        proof=packet['financial_producer'];proof.update(height=height,state_root='4'*64,epoch=str(epoch),sequence=str(selected+1))
        if selected:
            row=originals[selected-1];record=journal.wire.decode_block(row['wire'],self.open_source,self.context.anchor()['genesis_hash'],1)
            packet['state']['financial_dag']['authors'][self.indices[0]].update(sequence=str(selected),epoch='1',attempts=str(selected),head=row['hash'])
            proof.update(parent=row['hash'],parent_rank=str(record['rank']))
        if epoch>1:
            packet['state']['financial_dag'].update(epoch=str(epoch),checkpoint=str(height),last_cut='6'*64,epoch_base_rank=str(selected))
            proof.update(parent='6'*64,parent_rank=str(selected))
        return packet

    def test_pending_suffix_uses_certified_sequence_and_retains_old_epoch_originals(self):
        writer=self.open();self.open_source=writer.source
        originals=writer.produce_batch(self.packet,[self.payment]*3,1)
        cut=self.retry_context(originals,1,epoch=2)
        plan=writer.pending_batch(cut,self.indices[0])
        self.assertEqual([row['hash'] for row in plan['blocks']],[row['hash'] for row in originals[1:]])
        values=journal.wire.authenticate_payments(plan['payments'],writer.anchor)
        rebased=writer.retry_batch(cut,plan,values)
        self.assertEqual(len(rebased),2);self.assertEqual(writer.snapshot()['originals'],5)
        for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])
        latest=writer.pending_batch(cut,self.indices[0]);self.assertEqual(latest['epoch'],2)
        self.assertEqual([row['hash'] for row in latest['blocks']],[row['hash'] for row in rebased])

    def test_account_authentication_race_trims_only_exact_selected_prefix(self):
        writer=self.open();self.open_source=writer.source
        rows=writer.produce_batch(self.packet,[self.payment]*3,1);plan=writer.pending_batch(self.packet,self.indices[0])
        values=journal.wire.authenticate_payments(plan['payments'],writer.anchor)
        packet=self.retry_context(rows,2)
        retried=writer.retry_batch(packet,plan,values)
        self.assertEqual([row['hash'] for row in retried],[rows[2]['hash']]);self.assertEqual(writer.snapshot()['originals'],3)
        complete=self.retry_context(rows,3,height=2)
        self.assertIsNone(writer.pending_batch(complete,self.indices[0]))
        self.assertEqual(writer.retry_batch(complete,plan,values),[])

    def test_archived_pending_suffix_survives_cold_open_without_payment_file(self):
        writer=self.open();self.open_source=writer.source
        rows=writer.produce_batch(self.packet,[self.payment]*3,1)
        with self.profile._lock:writer._archive()
        packet=self.retry_context(rows,1,epoch=2);name=self.profile.name
        writer.close();self.profile.close();self.packet=packet
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened);writer=self.open(reopened)
        plan=writer.pending_batch(packet,self.indices[0]);self.assertEqual(len(plan['payments']),2)
        self.assertEqual(plan['blocks'][0]['hash'],rows[1]['hash']);self.assertEqual(writer.snapshot()['archive_chunks'],1)

    def test_unselected_prefix_is_not_dropped_for_account_nonce_or_foreign_progress(self):
        writer=self.open();self.open_source=writer.source
        rows=writer.produce_batch(self.packet,[self.payment]*2,1)
        packet=self.retry_context(rows,0)
        packet['state']['accounts']=[{'address':self.body['sender'],'nonce':100,'balance_atomic':'0'}]
        plan=writer.pending_batch(packet,self.indices[0]);self.assertEqual(len(plan['blocks']),2)
        self.assertEqual(plan['payments'],[self.payment]*2)
        with self.assertRaisesRegex(ValueError,'OWN_PRODUCER_REQUIRED'):writer.pending_batch(packet,(self.indices[0]+2)%6)

    def test_retry_cancellation_never_writes_new_originals(self):
        writer=self.open();rows=writer.produce_batch(self.packet,[self.payment],1)
        plan=writer.pending_batch(self.packet,self.indices[0]);values=journal.wire.authenticate_payments(plan['payments'],writer.anchor)
        def stop():raise ValueError('GG_LAN_STOPPED')
        with self.assertRaisesRegex(ValueError,'GG_LAN_STOPPED'):writer.retry_batch(self.packet,plan,values,check=stop)
        self.assertEqual(writer.snapshot()['originals'],1);self.assertEqual(writer.original(rows[0]['hash']),rows[0]['wire'])

    def test_ambiguous_durable_batch_commit_recovers_all_exact_originals(self):
        writer=self.open();commit=self.profile._commit
        def durable_then_error():
            commit();raise OSError('owned batch committed before injected IO uncertainty')
        with patch.object(self.profile,'_commit',side_effect=durable_then_error):
            with self.assertRaises((ValueError,OSError)):writer.produce_batch(self.packet,[self.payment]*3,1)
        self.assertTrue(self.profile._failed)
        name=self.profile.name;writer.close();self.profile.close()
        reopened=nodes.NodeProfile.open(name);self.owners.append(reopened)
        restored=journal.OwnedFinancialProducer.open(reopened,self.bundle,self.packet);self.writers.append(restored)
        self.assertEqual(restored.snapshot()['originals'],3)
        retry=restored.produce_batch(self.packet,[self.payment]*3,1)
        self.assertEqual(len(retry),3);self.assertEqual(restored.snapshot()['originals'],3)

    def test_external_database_write_stops_a_warm_writer_before_new_signatures(self):
        writer=self.open();writer.produce_batch(self.packet,[self.payment],1)
        connection=sqlite3.connect(self.profile.root/'node.sqlite3',timeout=0)
        try:
            with self.assertRaises(sqlite3.OperationalError):connection.execute('UPDATE financial_proposals SET wire=?',(b'forbidden external write',))
        finally:connection.close()
        database=self.profile._db
        class VersionBoundary:
            # Explicit SQLite boundary seam: the real exclusive profile above
            # denied another writer. No fake result is crypto evidence.
            def execute(self,query,*args):
                if query=='PRAGMA data_version':
                    from types import SimpleNamespace
                    return SimpleNamespace(fetchone=lambda:(writer._data_version+1,))
                return database.execute(query,*args)
        with patch.object(self.profile,'_db',VersionBoundary()),patch.object(journal.wire,'_signed_chain',side_effect=AssertionError('signed after journal changed')):
            with self.assertRaisesRegex(ValueError,'JOURNAL_CHANGED'):writer.produce_batch(self.packet,[self.payment]*2,1)
        self.assertTrue(self.profile._failed)


if __name__=='__main__':unittest.main()
