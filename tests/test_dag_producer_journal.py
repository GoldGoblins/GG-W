"""Real encrypted SQLite/wires/crashes; SDK result seam is mocked in this suite.

Public vectors are genuine loopback SDK certificates. These unit cases exercise
the journal lifecycle without requiring installed native tools. The separate
four-SDK-process test supplies actual certificate/selection/resume evidence.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

from backend import gg_node_store as store,gg_dag_segmented as segmented,portable_wallet_vault as portable
from backend import gg_dag_producer_archive as archives,gg_dag_producer_journal as journal
from tests.test_lan_segmented_session import public_fixture


def vectors():
    data=json.loads((Path(__file__).parent/'data/dag_producer_journal_vectors.json').read_text(encoding='utf-8'))
    assert data['schema']=='gg.public.producer-journal-test-vectors.v1'
    return data


def verified_view(data):
    """Verified-result seam only; never count this as an SDK signature test."""
    def check(packet,trust,**options):
        for name,known in data['packets'].items():
            if packet==known and trust=={key:known[key] for key in ('genesis','genesis_hash')}:
                return {'base':deepcopy(data['bases'][name]),'commitment':deepcopy(known['state']['dag_segmented'])}
        raise ValueError('TEST_VERIFIER_SEAM_REJECTED_UNKNOWN_PACKET')
    return check


def make_profile(data,name,*,used=False):
    entries=[entry for entry in data['session']['body']['roster'] if entry['invite']['body'].get('node_role','producer')=='producer']
    selected=data['packets']['after_cut']['state']['dag_segmented']['authors']
    entry=next(entry for entry in entries if any(int(selected[i]['sequence'])>0 for i in entry['producer_indices']) is used)
    body=entry['invite']['body'];fixture=public_fixture()
    number=next(i for i,key in enumerate(fixture['owners']) if key.pubkey().hex()==body['peer_key'])
    config={key:body[key] for key in ('label','host','port','allow_test_tokens','allow_dag_transactions','node_role')}
    config.update(allowed_cidr='127.0.0.0/8',trusted_coordinator=data['session']['body']['coordinator'])
    with patch.object(store,'Keypair',side_effect=[fixture['owners'][number],*fixture['producers'][number]]),patch.object(store.secrets,'token_hex',return_value=body['nonce']):
        return store.NodeProfile.create(name,config)


class ProducerJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-own-journal-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'nodes';self.paths=patch.object(store,'ROOT',self.root);self.paths.start();self.addCleanup(self.paths.stop)
        self.unlock=portable.session('public producer journal fixture');self.unlock.__enter__();self.addCleanup(self.unlock.__exit__,None,None,None)
        self.data=vectors();self.proof=patch.object(segmented,'verify_epoch_base',side_effect=verified_view(self.data));self.proof.start();self.addCleanup(self.proof.stop)
        self.profiles=[];self.writers=[];self.addCleanup(self.close_all)

    def close_all(self):
        for writer in reversed(self.writers):writer.close()
        for profile in reversed(self.profiles):profile.close()

    def create(self,name='Own',*,used=False):
        profile=make_profile(self.data,name,used=used);self.profiles.append(profile);return profile

    def reopen(self,name='Own'):
        profile=store.NodeProfile.open(name);self.profiles.append(profile);return profile

    def writer(self,profile,packet='initial',**options):
        owner=journal.OwnedSegmentedProducer.open(profile,self.data['session'],self.data['packets'][packet],hot_bytes=0,**options)
        self.writers.append(owner);return owner

    def test_exact_pending_bytes_and_next_nonce_survive_encrypted_profile_reopen(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0]
        first=writer.produce(index,3);public=profile.descriptor()['public_keys'];writer.close();profile.close()
        profile=self.reopen();writer=self.writer(profile)
        self.assertEqual(profile.descriptor()['public_keys'],public)
        self.assertEqual(writer.read_proposal(writer.pending()[0]['hash']),first['wire'])
        next_block=writer.produce(index,2);body=store.unpack(next_block['wire'])['body']
        self.assertEqual(body['sequence'],2);self.assertEqual(body['transactions'][0]['body']['nonce'],3)
        self.assertEqual(writer.snapshot()['pending_count'],2)
        self.assertFalse(writer.snapshot()['local_preview_is_global_state'])
        self.assertFalse(writer.snapshot()['network_liveness_asserted'])

    def test_cut_preserves_original_unselected_wires_and_retires_old_epoch_pending(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0]
        old=writer.produce(index,3);writer.observe(self.data['packets']['after_cut'])
        observed=writer.snapshot();self.assertEqual((observed['archived_own_epochs'],observed['own_records'],observed['pending_count']),('1',0,0))
        archived=next((profile.root/'producer-epochs').glob('*.ggown'))
        self.assertIn(old['wire'],archived.read_bytes())
        new=writer.produce(index,1);body=store.unpack(new['wire'])['body']
        self.assertEqual(body['sequence'],1);self.assertEqual(body['transactions'][0]['body']['nonce'],0)
        self.assertEqual(body['precheck_root'],self.data['packets']['after_cut']['state']['dag_segmented']['last_cut'])
        self.assertNotEqual(body['precheck_root'],store.unpack(old['wire'])['body']['precheck_root'])
        self.assertEqual(writer.snapshot()['certified_global_commitment']['transactions'],'5000')

    def test_epoch_jump_and_two_archive_chain_reopen_preserve_own_identity(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0]
        writer.produce(index,1);writer.observe(self.data['packets']['after_cut']);writer.produce(index,1)
        writer.observe(self.data['packets']['after_second_cut']);writer.close();profile.close()
        profile=self.reopen();writer=self.writer(profile,'after_second_cut')
        self.assertEqual(writer.snapshot()['archived_own_epochs'],'2')
        self.assertEqual(len(list((profile.root/'producer-epochs').glob('*.ggown'))),2)
        self.assertEqual(store.unpack(writer.produce(index,1)['wire'])['body']['sequence'],1)

    def test_offline_owner_can_skip_multiple_global_cuts_without_losing_pending_audit(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];old=writer.produce(index,1)['wire']
        writer.close();profile.close();profile=self.reopen();writer=self.writer(profile,'after_second_cut')
        self.assertEqual((writer.snapshot()['epoch'],writer.snapshot()['archived_own_epochs']),('3','1'))
        self.assertIn(old,next((profile.root/'producer-epochs').glob('*.ggown')).read_bytes())
        self.assertEqual(writer.snapshot()['pending_count'],0)
        self.assertEqual(store.unpack(writer.produce(index,1)['wire'])['body']['transactions'][0]['body']['nonce'],0)

    def test_missing_selected_own_history_never_creates_a_new_signing_journal(self):
        profile=self.create(used=True)
        with self.assertRaisesRegex(ValueError,'OWN_HISTORY_REQUIRED'):self.writer(profile,'after_cut')
        self.assertEqual(profile._schema_version,3);self.assertIsNone(profile.session())
        self.assertIsNone(profile._db.execute("SELECT name FROM sqlite_master WHERE name='own_proposals'").fetchone())

    def test_second_writer_wrong_slot_and_legacy_append_are_rejected(self):
        profile=self.create();writer=self.writer(profile)
        with self.assertRaisesRegex(ValueError,'IN_USE_OR_CLOSED'):self.writer(profile)
        foreign=next(i for i in range(6) if i not in writer.snapshot()['own_indices'])
        with self.assertRaisesRegex(ValueError,'NOT_OWNED'):writer.produce(foreign,1)
        with self.assertRaisesRegex(ValueError,'USE_OWN_JOURNAL'):profile.append('dag',[b'not-a-segmented-proposal'])
        self.assertEqual(writer.snapshot()['own_records'],0)

    def test_ambiguous_append_commit_exposes_nothing_and_reopens_exact_committed_raw(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];commit=profile._commit
        def lost_reply():commit();raise OSError('public injected post-commit failure')
        with patch.object(profile,'_commit',side_effect=lost_reply):
            with self.assertRaises(ValueError):writer.produce(index,2)
        with self.assertRaisesRegex(ValueError,'NOT_WRITABLE'):writer.produce(index,1)
        writer.close();profile.close();profile=self.reopen();writer=self.writer(profile)
        pending=writer.pending();self.assertEqual(len(pending),1)
        self.assertEqual(len(store.unpack(writer.read_proposal(pending[0]['hash']))['body']['transactions']),2)

    def test_real_child_exits_after_commit_before_proposal_publication(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];writer.close();profile.close()
        result=subprocess.run([sys.executable,'-m','tests.test_dag_producer_journal','--producer-commit-exit',str(self.root),'Own',str(index)],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace')[-512:])
        profile=self.reopen();writer=self.writer(profile);pending=writer.pending();self.assertEqual(len(pending),1)
        original=writer.read_proposal(pending[0]['hash']);self.assertEqual(store.unpack(original)['body']['sequence'],1)
        self.assertEqual(store.unpack(writer.produce(index,1)['wire'])['body']['transactions'][0]['body']['nonce'],1)

    def test_rollback_failure_latches_the_parent_profile_before_any_other_write(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];connection=profile._db
        class BrokenRollback:
            def __getattr__(self,name):return getattr(connection,name)
            def execute(self,sql,*args):
                if sql=='ROLLBACK':raise sqlite3.OperationalError('public injected rollback failure')
                result=connection.execute(sql,*args)
                if sql.startswith('INSERT INTO own_proposals'):raise sqlite3.OperationalError('public injected insertion ambiguity')
                return result
        with patch.object(profile,'_db',BrokenRollback()):
            with self.assertRaises(ValueError):writer.produce(index,1)
            self.assertTrue(profile._failed)
            with self.assertRaises(ValueError):profile.save_cursor('a'*64,1)
        writer.close();profile.close();profile=self.reopen();writer=self.writer(profile)
        self.assertEqual(writer.snapshot()['own_records'],0)

    def test_cancelled_observation_never_changes_the_sealed_profile(self):
        profile=self.create();writer=self.writer(profile);before=deepcopy(profile._meta['segmented_producer'])
        def cancel():raise ValueError('PUBLIC_TEST_CANCELLED_BEFORE_OBSERVATION')
        with self.assertRaisesRegex(ValueError,'PUBLIC_TEST_CANCELLED_BEFORE_OBSERVATION'):
            writer.observe(self.data['packets']['after_cut'],check=cancel)
        self.assertEqual(profile._meta['segmented_producer'],before)

    def test_partial_archive_fsync_failure_resumes_only_the_sealed_intent(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];wire=writer.produce(index,2)['wire']
        with patch.object(archives.os,'fsync',side_effect=OSError('public injected fsync failure')):
            with self.assertRaises(OSError):writer.observe(self.data['packets']['after_cut'])
        self.assertIsNotNone(profile._meta['segmented_producer']['pending_cut'])
        with self.assertRaises(ValueError):writer.produce(index,1)
        writer.close();profile.close();profile=self.reopen();writer=self.writer(profile,'after_cut')
        self.assertIsNone(profile._meta['segmented_producer']['pending_cut'])
        self.assertEqual(writer.snapshot()['archived_own_epochs'],'1')
        self.assertIn(wire,next((profile.root/'producer-epochs').glob('*.ggown')).read_bytes())

    def test_ambiguous_cut_intent_and_final_commit_recover_old_or_new_consistent_state(self):
        for boundary in (1,2):
            with self.subTest(boundary=boundary):
                name='Boundary'+str(boundary);profile=self.create(name);writer=self.writer(profile);index=writer.snapshot()['own_indices'][0]
                writer.produce(index,2);commit=profile._commit;calls=0
                def ambiguous():
                    nonlocal calls
                    commit();calls+=1
                    if calls==boundary:raise OSError('public injected cut commit ambiguity')
                with patch.object(profile,'_commit',side_effect=ambiguous):
                    with self.assertRaises(ValueError):writer.observe(self.data['packets']['after_cut'])
                writer.close();profile.close();profile=self.reopen(name);writer=self.writer(profile,'after_cut')
                self.assertEqual((writer.snapshot()['epoch'],writer.snapshot()['archived_own_epochs'],writer.snapshot()['own_records']),('2','1',0))

    def test_archive_write_cancellation_keeps_original_rows_and_resumes(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];writer.produce(index,2)
        def cancel():
            if profile._meta['segmented_producer']['pending_cut'] is not None:raise ValueError('PUBLIC_TEST_CANCELLED')
        with self.assertRaisesRegex(ValueError,'PUBLIC_TEST_CANCELLED'):writer.observe(self.data['packets']['after_cut'],check=cancel)
        self.assertEqual(profile._db.execute('SELECT count(*) FROM own_proposals').fetchone(),(1,))
        writer.close();profile.close();profile=self.reopen();writer=self.writer(profile,'after_cut')
        self.assertEqual(writer.snapshot()['own_records'],0)

    def test_deleted_current_tail_and_modified_wire_fail_without_repair(self):
        for action in ('delete','modify'):
            name=action.capitalize();profile=self.create(name);writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1)
            writer.close();profile.close()
            with closing(sqlite3.connect(profile.root/'node.sqlite3')) as db,db:
                if action=='delete':db.execute('DELETE FROM own_proposals')
                else:db.execute('UPDATE own_proposals SET wire=?',(b'public corrupted raw',))
            before=(profile.root/'node.sqlite3').read_bytes()
            with self.subTest(action=action),self.assertRaises(ValueError):self.reopen(name)
            self.assertEqual(before,(profile.root/'node.sqlite3').read_bytes())

    def test_sealed_hash_rejection_precedes_untrusted_record_json_decoding(self):
        profile=self.create();writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1);writer.close();profile.close()
        bomb=b'['+b'0,'*50000+b'0]'
        with closing(sqlite3.connect(profile.root/'node.sqlite3')) as db,db:
            db.execute('UPDATE own_proposals SET wire=?,wire_hash=?',(bomb,hashlib.sha256(bomb).hexdigest()))
        with patch.object(journal,'_decode',side_effect=AssertionError('untrusted JSON decoded before sealed hash')):
            with self.assertRaises(ValueError):self.reopen()

    def test_corrupt_identifier_length_is_checked_before_large_sqlite_value_allocation(self):
        profile=self.create();writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1);writer.close()
        profile._db.execute('UPDATE own_proposals SET identifier=zeroblob(?)',(8*1024*1024,))
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):journal.validate_stored_profile(profile)
            peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertLess(peak,2*1024*1024,'Corrupt SQLite metadata allocated '+str(peak)+' Python-traced bytes')

    def test_corrupt_private_metadata_collections_are_bounded_before_json_allocation(self):
        for forge_binding in (False,True):
            name='Metadata'+str(forge_binding);profile=self.create(name);writer=self.writer(profile);writer.close();profile.close()
            bomb=b'['+b'{},'*100000+b'{}]'
            with closing(sqlite3.connect(profile.root/'node.sqlite3')) as db,db:
                db.execute("UPDATE metadata SET value=? WHERE name='segmented_producer'",(bomb,))
                if forge_binding:
                    raw={key:bytes(value) for key,value in db.execute('SELECT name,value FROM metadata')};head=store.unpack(raw['head'])
                    head['body']['binding']=store._raw_metadata_binding(raw)  # attacker can recompute a digest, not the seal
                    db.execute("UPDATE metadata SET value=? WHERE name='head'",(store.pack(head),))
            tracemalloc.start()
            try:
                with self.assertRaises(ValueError):self.reopen(name)
                peak=tracemalloc.get_traced_memory()[1]
            finally:tracemalloc.stop()
            self.assertLess(peak,2*1024*1024,'Corrupt private metadata allocated '+str(peak)+' Python-traced bytes')

    def test_archive_collection_corruption_is_rejected_before_json_allocation(self):
        profile=self.create();writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1)
        writer.observe(self.data['packets']['after_cut']);path=next((profile.root/'producer-epochs').glob('*.ggown'))
        writer.close();profile.close();bomb=b'['+b'{},'*100000+b'{}]'
        path.write_bytes(archives.MAGIC+b'H'+struct.pack('>I',len(bomb))+bomb+b'public invalid footer')
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):self.reopen()
            peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertLess(peak,2*1024*1024,'Corrupt archive allocated '+str(peak)+' Python-traced bytes')

    def test_archive_replacement_between_hash_and_decode_cannot_reuse_authentication(self):
        profile=self.create();writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1)
        writer.observe(self.data['packets']['after_cut']);path=next((profile.root/'producer-epochs').glob('*.ggown'))
        writer.close();profile.close();original=archives._file_hash;replaced=False
        def changed(candidate,**options):
            nonlocal replaced
            value=original(candidate,**options)
            if candidate==path and not replaced:
                replaced=True;bomb=b'['+b'{},'*100000+b'{}]';replacement=profile.root/'replacement.ggown'
                replacement.write_bytes(archives.MAGIC+b'H'+struct.pack('>I',len(bomb))+bomb+b'public invalid footer')
                archives.set_private_mode(replacement,0o600)
                assert replacement.resolve().is_relative_to(profile.root.resolve()) and path.resolve().is_relative_to(profile.root.resolve())
                os.replace(replacement,path)
            return value
        with patch.object(archives,'_file_hash',side_effect=changed),patch.object(archives,'unpack',side_effect=AssertionError('replacement JSON decoded')):
            with self.assertRaises(ValueError):self.reopen()
        self.assertTrue(replaced)

    def test_cancelled_parent_profile_archive_recovery_releases_its_exclusive_lease(self):
        profile=self.create();writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1)
        writer.observe(self.data['packets']['after_cut']);writer.close();profile.close();entered=False;original=archives._file_hash
        def reading(path,**options):
            nonlocal entered
            entered=True;return original(path,**options)
        def cancel():
            if entered:raise ValueError('PUBLIC_TEST_PARENT_RECOVERY_CANCELLED')
        with patch.object(archives,'_file_hash',side_effect=reading):
            with self.assertRaisesRegex(ValueError,'PUBLIC_TEST_PARENT_RECOVERY_CANCELLED'):store.NodeProfile.open('Own',check=cancel)
        self.assertTrue(entered)
        profile=self.reopen();self.assertEqual(self.writer(profile,'after_cut').snapshot()['archived_own_epochs'],'1')

    def test_missing_changed_or_linked_archive_cannot_enable_a_signer(self):
        for action in ('delete','change','link'):
            name='Archive'+action;profile=self.create(name);writer=self.writer(profile);writer.produce(writer.snapshot()['own_indices'][0],1)
            writer.observe(self.data['packets']['after_cut']);path=next((profile.root/'producer-epochs').glob('*.ggown'))
            writer.close();profile.close()
            if action=='delete':path.unlink()
            elif action=='change':
                raw=bytearray(path.read_bytes());raw[len(raw)//2]^=1;path.write_bytes(raw)
            else:os.link(path,profile.root/'alias.ggown')
            with self.subTest(action=action),self.assertRaises((ValueError,OSError)):self.reopen(name)

    def test_certificate_rewind_and_unknown_packet_leave_journal_unchanged(self):
        profile=self.create();writer=self.writer(profile,'after_cut');before=deepcopy(profile._meta['segmented_producer'])
        with self.assertRaisesRegex(ValueError,'CERTIFICATE_REWIND'):writer.observe(self.data['packets']['initial'])
        bad=deepcopy(self.data['packets']['after_cut']);bad['dag_segmented_base_proof']['state_root']='0'*64
        with self.assertRaises(ValueError):writer.observe(bad)
        self.assertEqual(profile._meta['segmented_producer'],before)

    def test_observed_cold_payload_corruption_stops_all_further_signing(self):
        profile=self.create();writer=self.writer(profile);index=writer.snapshot()['own_indices'][0];block=writer.produce(index,1)
        profile._db.execute('UPDATE own_proposals SET wire=?',(b'public injected cold-payload corruption',))
        with self.assertRaises(ValueError):writer.read_proposal(block['hash'])
        with self.assertRaises(ValueError):writer.produce(index,1)

    def test_verified_result_conflict_seam_latches_fault_before_further_signing(self):
        profile=self.create();writer=self.writer(profile);bad=deepcopy(self.data['packets']['initial'])
        bad['signed_header']['commit']['block_id']['hash']='f'*64
        view=verified_view(self.data)(self.data['packets']['initial'],writer._anchor)
        with patch.object(writer,'_verify',return_value=view):
            with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):writer.observe(bad)
        with self.assertRaises(ValueError):writer.produce(writer._indices[0],1)
        writer.close();profile.close();profile=self.reopen()
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):self.writer(profile)

    def test_profile_close_stops_its_owned_engine_and_releases_no_fresh_wire(self):
        profile=self.create();writer=self.writer(profile);engine=writer._engine;profile.close()
        self.assertFalse(engine._active)
        with self.assertRaises(ValueError):writer.produce(writer._indices[0],1)

    def test_no_unencrypted_private_key_bytes_enter_own_journal_or_archives(self):
        profile=self.create();secrets=[bytes(key) for key in profile.signers()[1]];writer=self.writer(profile)
        writer.produce(writer.snapshot()['own_indices'][0],2);writer.observe(self.data['packets']['after_cut']);writer.close();profile.close()
        for path in profile.root.rglob('*'):
            if not path.is_file():continue
            raw=path.read_bytes()
            for key in secrets:
                self.assertNotIn(key,raw);self.assertNotIn(key[:32],raw);self.assertNotIn(key.hex().encode(),raw)


def _child_commit_exit():
    root,name,index=Path(sys.argv[2]),sys.argv[3],int(sys.argv[4]);data=vectors()
    with portable.session('public producer journal fixture'),patch.object(store,'ROOT',root),\
            patch.object(segmented,'verify_epoch_base',side_effect=verified_view(data)):
        profile=store.NodeProfile.open(name);writer=journal.OwnedSegmentedProducer.open(profile,data['session'],data['packets']['initial'],hot_bytes=0)
        commit=profile._commit
        def exit_after_commit():commit();os._exit(0)
        profile._commit=exit_after_commit;writer.produce(index,1)
    raise AssertionError('child returned a proposal instead of exiting at the commit boundary')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--producer-commit-exit':_child_commit_exit()
    else:unittest.main()
