"""Real files/SQLite/owner signatures; SDK verification is an explicit seam.

These cases establish own-original retention, not SDK payment execution or
validator state-sync. Live SDK/certificates are tested separately.
"""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_financial_producer as fixtures
from backend import gg_financial_producer as journal,gg_financial_own_archive as archives,gg_node_store as nodes
from backend.platform_files import secure_open


class FinancialOwnArchiveTests(unittest.TestCase):
    setUp=fixtures.FinancialProducerJournalTests.setUp
    cleanup=fixtures.FinancialProducerJournalTests.cleanup
    open=fixtures.FinancialProducerJournalTests.open

    def reopen(self,writer,packet=None):
        name=self.profile.name;writer.close();self.profile.close()
        self.profile=nodes.NodeProfile.open(name);self.owners.append(self.profile)
        writer=journal.OwnedFinancialProducer.open(self.profile,self.bundle,packet or self.packet);self.writers.append(writer)
        return writer

    def selected(self,writer,original,height=1):
        record=journal.wire.decode_block(original['wire'],writer.source,writer.anchor['genesis_hash'],1)
        packet=deepcopy(self.packet);packet['state']['height']=height;packet['signed_header']['header']['height']=str(height+1)
        packet['state']['financial_dag']['authors'][self.indices[0]].update(sequence=str(record['sequence']),epoch='1',head=record['hash'])
        packet['financial_producer'].update(height=height,sequence=str(record['sequence']+1),parent=record['hash'],parent_rank=str(record['rank']))
        return packet

    def archive(self,writer):
        with self.profile._lock:writer._archive()

    def test_two_chunks_keep_exact_pending_prefix_and_cold_extend_across_archive_boundary(self):
        writer=self.open();originals=writer.produce_batch(self.packet,[self.payment]*3,1)
        self.archive(writer)
        self.assertEqual(writer.snapshot()['active_originals'],0);self.assertEqual(writer.snapshot()['archive_chunks'],1)
        self.assertEqual(self.profile._db.execute('SELECT count(*) FROM financial_contexts').fetchone()[0],0)
        retry=writer.produce_batch(self.packet,[self.payment]*3,1)
        self.assertEqual([row['wire'] for row in retry],[row['wire'] for row in originals])
        extended=writer.produce_batch(self.packet,[self.payment]*5,1)
        self.assertEqual([row['wire'] for row in extended[:3]],[row['wire'] for row in originals])
        self.archive(writer);writer=self.reopen(writer)
        self.assertEqual(writer.snapshot()['originals'],5);self.assertEqual(writer.snapshot()['archive_chunks'],2)
        for row in extended:self.assertEqual(writer.original(row['hash']),row['wire'])
        resumed=writer.produce_batch(self.packet,[self.payment]*6,1)
        self.assertEqual([row['wire'] for row in resumed[:5]],[row['wire'] for row in extended])
        journal.validate_stored_profile(self.profile)

    def test_auto_retirement_exceeds_hot_record_quota_without_resigning_or_faking_selection(self):
        writer=self.open()
        with patch.object(journal,'MAX_RECORDS',8):
            originals=writer.produce_batch(self.packet,[self.payment]*8,1)
            packet=self.selected(writer,originals[-1])
            following=writer.produce_batch(packet,[self.payment],1)
            self.assertEqual(writer.snapshot()['originals'],9);self.assertEqual(writer.snapshot()['active_originals'],1)
            self.assertEqual(writer.snapshot()['archive_chunks'],1);self.assertFalse(following[0]['SDK_selected'])
            writer=self.reopen(writer,packet)
            for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])
            self.assertEqual(writer.original(following[0]['hash']),following[0]['wire'])

    def failed_retirement(self,*,durable):
        writer=self.open();originals=writer.produce_batch(self.packet,[self.payment]*3,1)
        commit=self.profile._commit;calls=0
        def failure():
            nonlocal calls
            calls+=1
            if calls==2:
                if durable:commit()
                raise OSError('owned retirement commit uncertainty')
            commit()
        with patch.object(self.profile,'_commit',side_effect=failure):
            with self.assertRaisesRegex(ValueError,'GG_NODE_STORE_WRITE_FAILED'):self.archive(writer)
        self.assertTrue(writer._failed);writer=self.reopen(writer)
        self.assertEqual(writer.snapshot()['archive_chunks'],1);self.assertEqual(writer.snapshot()['active_originals'],0)
        self.assertIsNone(self.profile._meta['financial_producer']['pending_archive'])
        for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])
        self.assertEqual(self.profile._db.execute('SELECT count(*) FROM financial_archived').fetchone()[0],3)

    def test_published_archive_with_rolled_back_retirement_is_completed_on_cold_open(self):self.failed_retirement(durable=False)

    def test_durable_retirement_followed_by_IO_error_recovers_exactly_once(self):self.failed_retirement(durable=True)

    def partial_file(self,size):
        writer=self.open();originals=writer.produce_batch(self.packet,[self.payment]*2,1)
        def interrupted(profile,state,rows,**options):
            root=archives.directory(profile,create=True);path=root/('pending-'+state['pending_archive']['token']+'.ggfin')
            with os.fdopen(secure_open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as file:file.write(b'GGFINO1'[:size])
            raise ValueError('GG_OWNED_RECOVERY_CANCELLED')
        with patch.object(archives,'write_current',side_effect=interrupted):
            with self.assertRaisesRegex(ValueError,'GG_OWNED_RECOVERY_CANCELLED'):self.archive(writer)
        self.assertTrue(writer._failed);writer=self.reopen(writer)
        for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])
        self.assertEqual(writer.snapshot()['archive_chunks'],1)
        self.assertFalse(list(archives.directory(self.profile).glob('pending-*.ggfin')))

    def test_zero_byte_sealed_pending_file_is_rebuilt_from_retained_SQL_originals(self):self.partial_file(0)

    def test_truncated_sealed_pending_header_is_rebuilt_from_retained_SQL_originals(self):self.partial_file(7)

    def test_same_size_archived_original_corruption_stops_read_and_cold_recovery(self):
        writer=self.open();original=writer.produce_batch(self.packet,[self.payment],1)[0];self.archive(writer)
        identifier,offset,size=self.profile._db.execute('SELECT archive,wire_offset,wire_bytes FROM financial_archived').fetchone()
        path=archives.directory(self.profile)/(identifier+'.ggfin')
        with path.open('r+b') as file:
            file.seek(offset+size//2);value=file.read(1);file.seek(-1,1);file.write(bytes([value[0]^1]))
        with self.assertRaises(ValueError):writer.original(original['hash'])
        self.assertTrue(writer._failed)
        name=self.profile.name;writer.close();self.profile.close()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_JOURNAL_INVALID'):nodes.NodeProfile.open(name)

    def test_compact_index_cannot_substitute_parent_or_offset_on_cold_recovery(self):
        writer=self.open();writer.produce_batch(self.packet,[self.payment],1);self.archive(writer)
        self.profile._db.execute("UPDATE financial_archived SET parent=?",('9'*64,))
        name=self.profile.name;writer.close();self.profile.close()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_JOURNAL_INVALID'):nodes.NodeProfile.open(name)

    def test_archive_is_bound_to_owner_and_extra_hardlinks_are_rejected(self):
        writer=self.open();writer.produce_batch(self.packet,[self.payment],1);self.archive(writer)
        state=self.profile._meta['financial_producer'];path=archives.directory(self.profile)/(state['archive']+'.ggfin')
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_ARCHIVE_HEADER'):
            archives.inspect_file(path,state['genesis_hash'],'0'*64,expected=state['archive'])
        os.link(path,path.with_name('unexpected-hardlink.ggfin'))
        name=self.profile.name;writer.close();self.profile.close()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_JOURNAL_INVALID'):nodes.NodeProfile.open(name)

    def test_existing_v5_originals_upgrade_atomically_without_changing_keys_or_wires(self):
        writer=self.open();originals=writer.produce_batch(self.packet,[self.payment]*3,1);writer.close()
        descriptor=self.profile.descriptor();keys=deepcopy(self.profile._meta['protected_keys'])
        old={key:deepcopy(value) for key,value in self.profile._meta['financial_producer'].items() if key in journal.FIELDS};old['schema']=journal.SCHEMA
        def legacy():
            self.profile._db.execute('DROP TABLE financial_archived');self.profile._db.execute('DROP TABLE financial_archives')
            self.profile._meta['financial_producer']=old;self.profile._put('financial_producer',old);self.profile._db.execute('PRAGMA user_version=5')
        self.profile._write(legacy);self.profile._schema_version=5
        name=self.profile.name;self.profile.close();self.profile=nodes.NodeProfile.open(name);self.owners.append(self.profile)
        self.assertEqual(self.profile._schema_version,5)
        writer=journal.OwnedFinancialProducer.open(self.profile,self.bundle,self.packet);self.writers.append(writer)
        self.assertEqual(self.profile._schema_version,6);self.assertEqual(self.profile.descriptor(),descriptor)
        self.assertEqual(self.profile._meta['protected_keys'],keys)
        for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])
        writer=self.reopen(writer);self.assertEqual(writer.snapshot()['originals'],3)

    def test_archive_validation_cancellation_keeps_original_reason(self):
        writer=self.open();writer.produce_batch(self.packet,[self.payment]*3,1);self.archive(writer);calls=0
        def cancel():
            nonlocal calls
            calls+=1
            if calls>10:raise ValueError('GG_OWNED_RECOVERY_CANCELLED')
        with self.assertRaisesRegex(ValueError,'GG_OWNED_RECOVERY_CANCELLED'):journal.validate_stored_profile(self.profile,check=cancel)

    def test_published_hardlink_before_unlink_failure_recovers_without_replacing_final_file(self):
        writer=self.open();original=writer.produce_batch(self.packet,[self.payment],1)[0];link=os.link
        def failed_publication(*args,**kwargs):link(*args,**kwargs);raise OSError('owned publication interruption')
        with patch.object(archives.os,'link',side_effect=failed_publication):
            with self.assertRaises(OSError):self.archive(writer)
        root=archives.directory(self.profile);final=next(path for path in root.glob('*.ggfin') if not path.name.startswith('pending-'))
        before=final.stat();self.assertEqual(before.st_nlink,2)
        writer=self.reopen(writer);after=final.stat()
        self.assertEqual(after.st_nlink,1);self.assertEqual(after.st_mtime_ns,before.st_mtime_ns)
        self.assertEqual(writer.original(original['hash']),original['wire'])

    def test_partial_selection_then_new_epoch_keeps_old_and_new_same_sequence_originals(self):
        writer=self.open();old=writer.produce_batch(self.packet,[self.payment]*3,1);self.archive(writer)
        cut=self.selected(writer,old[0],height=2);value=cut['state']['financial_dag']
        value.update(epoch='2',checkpoint='2',last_cut='6'*64,epoch_base_rank='1')
        cut['financial_producer'].update(epoch='2',parent='6'*64,parent_rank='1')
        new=writer.produce_batch(cut,[self.payment]*2,1);self.archive(writer);writer=self.reopen(writer,cut)
        self.assertEqual(writer.snapshot()['originals'],5)
        for row in old+new:self.assertEqual(writer.original(row['hash']),row['wire'])
        self.assertEqual(journal.wire.decode_block(new[0]['wire'],writer.source,writer.anchor['genesis_hash'],2)['sequence'],2)

    def test_missing_archive_fails_closed_and_cannot_be_replaced_by_compact_index(self):
        writer=self.open();writer.produce_batch(self.packet,[self.payment],1);self.archive(writer)
        state=self.profile._meta['financial_producer'];(archives.directory(self.profile)/(state['archive']+'.ggfin')).unlink()
        name=self.profile.name;writer.close();self.profile.close()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_JOURNAL_INVALID'):nodes.NodeProfile.open(name)

    def migration_uncertainty(self,*,durable):
        writer=self.open();originals=writer.produce_batch(self.packet,[self.payment]*2,1);writer.close()
        keys=deepcopy(self.profile._meta['protected_keys'])
        old={key:deepcopy(value) for key,value in self.profile._meta['financial_producer'].items() if key in journal.FIELDS};old['schema']=journal.SCHEMA
        def legacy():
            self.profile._db.execute('DROP TABLE financial_archived');self.profile._db.execute('DROP TABLE financial_archives')
            self.profile._meta['financial_producer']=old;self.profile._put('financial_producer',old);self.profile._db.execute('PRAGMA user_version=5')
        self.profile._write(legacy);self.profile._schema_version=5
        commit=self.profile._commit
        def failure():
            if durable:commit()
            raise OSError('owned v5/v6 migration commit uncertainty')
        with patch.object(self.profile,'_commit',side_effect=failure):
            with self.assertRaisesRegex(ValueError,'GG_NODE_STORE_WRITE_FAILED'):
                journal.OwnedFinancialProducer.open(self.profile,self.bundle,self.packet)
        writer=self.reopen(writer)
        self.assertEqual(self.profile._schema_version,6);self.assertEqual(self.profile._meta['protected_keys'],keys)
        for row in originals:self.assertEqual(writer.original(row['hash']),row['wire'])

    def test_v5_to_v6_rollback_keeps_old_schema_and_originals_recoverable(self):self.migration_uncertainty(durable=False)

    def test_v5_to_v6_durable_commit_then_error_reopens_new_schema_without_resigning(self):self.migration_uncertainty(durable=True)


if __name__=='__main__':unittest.main()
