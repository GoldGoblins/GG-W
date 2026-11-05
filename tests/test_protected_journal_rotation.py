"""Real vault/keys/signatures/SQLite/files; SDK lookups are explicit unit seams.

No incomplete policy packet is sent to a native verifier. The combined owned
operator/native gates must separately test real certificates and execution.
Threshold reductions here exercise real rotation without allocating GiB or
fabricating global journal positions. No production/security limit is raised.
"""
import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from backend import gg_financial_account as accounts,gg_financial_pool as pools
from backend import gg_protected_journal as journals,gg_financial_protocol as protocol
from backend import gg_financial_economy as economy,gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_node_store import pack,unpack
from tests import test_financial_account as account_fixtures
from tests.test_financial_account import policy_packet,account_policy
from tests.test_financial_general_clients import public_key
from tests.test_protocol_integrated_profiles import public_protocol_pin


@unittest.skipUnless(os.name=='nt','real Windows public-file identity regression')
class WindowsJournalIdentityTests(unittest.TestCase):
    """Only new public tempfile bytes, real ACLs/fds and kernel metadata.

    These cases require neither protected profiles nor keys/native processes.
    The existing account/pool cases separately exercise the owning authority.
    """
    def setUp(self):
        import tempfile
        self.temporary=tempfile.TemporaryDirectory(prefix='gg-public-journal-identity-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.path=self.public_file('PUBLIC.ggjournal')
        self.segments=journals.Segments.__new__(journals.Segments)

    def public_file(self,name):
        path=self.root/name;path.write_bytes(b'PUBLIC journal identity regression\n')
        journals.set_private_mode(path,0o600)
        return path

    def rewrite_preserving_length_and_mtime(self,path):
        before=path.stat();raw=bytearray(path.read_bytes());raw[-1]^=1
        path.write_bytes(raw);os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        after=path.stat()
        self.assertEqual(after.st_size,before.st_size);self.assertEqual(after.st_mtime_ns,before.st_mtime_ns)

    def assert_closed(self,descriptors):
        self.assertTrue(descriptors)
        for descriptor in descriptors:
            with self.assertRaises(OSError):os.fstat(descriptor)

    def test_real_secure_file_identity_and_repeated_stamp_are_stable(self):
        descriptor=journals.secure_open(self.path,os.O_RDONLY,0o600)
        try:
            by_path=journals.producer_files.regular(self.path);by_fd=os.fstat(descriptor)
            self.assertTrue(os.path.samestat(by_path,by_fd))
            path_stamp=journals._stat_stamp(by_path);fd_stamp=journals._stat_stamp(by_fd)
            self.assertEqual(path_stamp[:4]+path_stamp[5:],fd_stamp[:4]+fd_stamp[5:])
            changed=journals._windows_change_time(descriptor)
        finally:os.close(descriptor)
        descriptors=[];query=journals._windows_change_time
        def observed(descriptor):descriptors.append(descriptor);return query(descriptor)
        with patch.object(journals,'_windows_change_time',side_effect=observed),\
                patch.object(journals.producer_files,'file_hash',side_effect=AssertionError('metadata read hashed payload')):
            first=self.segments._stamp(self.path);second=self.segments._stamp(self.path)
        self.assertEqual(first,second);self.assertEqual(first[-1],changed)
        self.assertEqual(len(descriptors),4);self.assert_closed(descriptors)

    def test_wrong_real_descriptor_is_rejected_and_closed(self):
        other=self.public_file('PUBLIC-other.ggjournal');stamp=self.path.stat()
        os.utime(other,ns=(stamp.st_atime_ns,stamp.st_mtime_ns));descriptors=[]
        secure_open=journals.secure_open
        def wrong(path,*args):
            descriptor=secure_open(other,*args);descriptors.append(descriptor);return descriptor
        with patch.object(journals,'secure_open',side_effect=wrong),self.assertRaisesRegex(ValueError,'OWN_JOURNAL_CHANGED'):
            self.segments._stamp(self.path)
        self.assert_closed(descriptors)

    def test_path_retarget_after_real_open_is_rejected_and_closed(self):
        other=self.public_file('PUBLIC-replacement.ggjournal');stamp=self.path.stat()
        os.utime(other,ns=(stamp.st_atime_ns,stamp.st_mtime_ns));descriptors=[]
        secure_open=journals.secure_open
        def retarget(path,*args):
            descriptor=secure_open(path,*args);descriptors.append(descriptor)
            try:
                # MoveFileEx(REPLACE_EXISTING) can refuse an open destination;
                # two real renames exercise a successful path retarget.
                os.rename(path,self.root/'PUBLIC-retired.ggjournal');os.rename(other,path)
                return descriptor
            except BaseException:os.close(descriptor);raise
        with patch.object(journals,'secure_open',side_effect=retarget),self.assertRaisesRegex(ValueError,'OWN_JOURNAL_CHANGED'):
            self.segments._stamp(self.path)
        self.assert_closed(descriptors)

    def test_real_change_time_api_error_closes_descriptor(self):
        import ctypes
        load=ctypes.WinDLL;query=journals._windows_change_time;descriptors=[];queries=[]
        class FailedQuery:
            def __call__(self,*args):
                queries.append(args[0]);ctypes.set_last_error(5);return 0
        class KernelFacade:
            def __init__(self,library):self.library=library;self.GetFileInformationByHandleEx=FailedQuery()
            def __getattr__(self,name):return getattr(self.library,name)
        def failed_library(name,*args,**options):
            library=load(name,*args,**options)
            return KernelFacade(library) if str(name).lower()=='kernel32' else library
        def observed(descriptor):descriptors.append(descriptor);return query(descriptor)
        with patch.object(ctypes,'WinDLL',side_effect=failed_library),\
                patch.object(journals,'_windows_change_time',side_effect=observed),self.assertRaises(OSError):
            self.segments._stamp(self.path)
        self.assertTrue(queries);self.assert_closed(descriptors)

    def test_mutation_during_change_time_query_is_rejected_and_closed(self):
        query=journals._windows_change_time;descriptors=[]
        def observed(descriptor):
            changed=query(descriptor);descriptors.append(descriptor)
            if len(descriptors)==1:self.rewrite_preserving_length_and_mtime(self.path)
            return changed
        with patch.object(journals,'_windows_change_time',side_effect=observed),self.assertRaisesRegex(ValueError,'OWN_JOURNAL_CHANGED'):
            self.segments._stamp(self.path)
        self.assertEqual(len(descriptors),2);self.assert_closed(descriptors)

    def test_preserved_length_and_mtime_edit_changes_real_stamp(self):
        before=self.segments._stamp(self.path);self.rewrite_preserving_length_and_mtime(self.path)
        after=self.segments._stamp(self.path)
        self.assertEqual(before[:4]+before[5:-1],after[:4]+after[5:-1])
        self.assertNotEqual(before[-1],after[-1]);self.assertNotEqual(before,after)

    def test_metadata_size_mtime_and_link_changes_during_query_are_rejected(self):
        query=journals._windows_change_time
        for mode in ('size','mtime','links'):
            with self.subTest(mode=mode):
                path=self.public_file('PUBLIC-'+mode+'.ggjournal');descriptors=[]
                def observed(descriptor):
                    changed=query(descriptor);descriptors.append(descriptor)
                    if len(descriptors)==1:
                        if mode=='size':
                            with path.open('ab') as output:output.write(b'PUBLIC extra')
                        elif mode=='mtime':
                            stamp=path.stat();os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+10_000_000))
                        else:os.link(path,self.root/'PUBLIC-link.ggjournal')
                    return changed
                with patch.object(journals,'_windows_change_time',side_effect=observed),self.assertRaisesRegex(ValueError,'OWN_JOURNAL_CHANGED'):
                    self.segments._stamp(path)
                self.assert_closed(descriptors)

    def test_changed_during_real_sqlite_read_fails_owner_closed(self):
        from types import SimpleNamespace
        root=self.root/'journal-segments';root.mkdir();journals.set_private_mode(root,0o700)
        digest='a'*64;path=root/(digest+'.ggjournal')
        db=sqlite3.connect(path)
        try:
            for statement in journals.SEGMENT_SQL.values():db.execute(statement)
            db.execute('INSERT INTO header VALUES(1,?)',(b'PUBLIC benign header',));db.commit()
        finally:db.close()
        journals.set_private_mode(path,0o600)
        owner=SimpleNamespace(root=self.root,_lease=object(),_db=object(),_key=object(),_failed=False)
        segments=journals.Segments(owner,'PUBLIC',{},'0'*64)
        with self.assertRaisesRegex(ValueError,'OWN_JOURNAL_CHANGED'):
            with segments._open(digest) as reader:
                self.assertEqual(reader.execute('SELECT record FROM header').fetchone()[0],b'PUBLIC benign header')
                self.rewrite_preserving_length_and_mtime(path)
        self.assertTrue(owner._failed);self.assertEqual(segments._readers,0);self.assertFalse(segments._pending_readers)


class ProtectedJournalRotationTests(unittest.TestCase):
    setUp=account_fixtures.ProtectedFinancialAccountTests.setUp
    close_profiles=account_fixtures.ProtectedFinancialAccountTests.close_profiles
    create=account_fixtures.ProtectedFinancialAccountTests.create
    open=account_fixtures.ProtectedFinancialAccountTests.open
    bound=account_fixtures.ProtectedFinancialAccountTests.bound
    packet=account_fixtures.ProtectedFinancialAccountTests.packet
    outputs=account_fixtures.ProtectedFinancialAccountTests.outputs

    def signed(self,profile,nonce,*,height=None,count=1):
        packet=self.packet(profile,nonce=nonce,height=height or nonce+1,balance=10**12)
        return profile.sign(profile.review(self.outputs(count),packet))

    def segment_paths(self,profile):
        return [profile.root/'journal-segments'/(row[0]+'.ggjournal') for row in profile._db.execute('SELECT digest FROM journal_archives ORDER BY number')]

    def signer_state(self,profile):
        return (profile.public_address(),profile._body['batch_head'],profile._body['next_nonce'],profile.batch_count(),
                hashlib.sha256(profile._body['protected_key'].encode()).digest())

    def test_actual_legacy_v1_lazy_migration_keeps_every_global_original(self):
        profile=self.bound();originals=[]
        # Build the old on-disk layout through the genuine protected signing/
        # commit path; only the newly introduced preparation step is omitted.
        with patch.object(profile,'_prepare_journal',lambda **options:None):
            for nonce in range(3):originals.append(self.signed(profile,nonce))
        self.assertEqual(profile._body['schema'],accounts.SCHEMA)
        before=self.signer_state(profile);profile.close();profile=self.open()
        self.assertEqual(profile._db.execute('PRAGMA user_version').fetchone(),(1,))
        self.assertEqual(self.signer_state(profile),before)
        with patch.object(journals,'MAX_ACTIVE_RECORDS',2):originals.append(self.signed(profile,3))
        self.assertEqual(profile._body['schema'],accounts.ARCHIVE_SCHEMA)
        self.assertEqual(profile._db.execute('PRAGMA user_version').fetchone(),(2,))
        self.assertEqual(profile.snapshot()['signed_batches_exact'],'4')
        for position,raw in enumerate(originals,1):self.assertEqual(profile.original(str(position)),raw)
        profile.close();profile=self.open()
        self.assertEqual(profile.snapshot()['next_signing_nonce'],'4')
        self.assertEqual(profile.snapshot()['own_journal']['verification_scope'],'OWN_SEALED_FULL_STREAMING_COLD_REPLAY')
        self.assertFalse(profile.snapshot()['payments_executed_asserted'])

    def test_many_actual_rollovers_keep_key_nonce_bytes_and_bounded_active_window(self):
        profile=self.bound();address=profile.public_address();key_hash=hashlib.sha256(bytes(profile._key)).digest();originals=[]
        with patch.object(journals,'MAX_ACTIVE_RECORDS',2):
            for nonce in range(8):
                originals.append(self.signed(profile,nonce))
                self.assertLessEqual(int(profile.snapshot()['own_journal']['active_records']),2)
        profile.archive();view=profile.snapshot()
        self.assertEqual(view['signed_batches_exact'],'8');self.assertEqual(view['next_signing_nonce'],'8')
        self.assertEqual(view['own_journal']['active_records'],'0');self.assertEqual(view['own_journal']['archived_records'],'8')
        self.assertEqual(profile.public_address(),address)
        self.assertTrue(hashlib.sha256(bytes(profile._key)).digest()==key_hash,'protected signer changed')
        for position,raw in enumerate(originals,1):self.assertEqual(profile.original(str(position)),raw)
        for path in self.segment_paths(profile):
            data=path.read_bytes();secret=bytes(profile._key)
            self.assertFalse(secret in data or secret[:32] in data,'journal segment leaked a private key')
            self.assertFalse(profile._body['protected_key'].encode() in data,'archive copied vault ciphertext')
            self.assertLessEqual(path.stat().st_size,journals.MAX_SEGMENT_BYTES)
        self.assertEqual(profile._segments._readers,0)

    def test_archived_payment_and_cancellation_recover_exact_pending_originals(self):
        profile=self.create('Protocol');self.anchor=public_protocol_pin();profile.bind(self.anchor)
        raw=self.signed(profile,0,count=2);profile.archive()
        packet=self.packet(profile,nonce=0,height=2,balance=10**12)
        cancelled=profile.sign_operation(profile.review_cancellation(packet));profile.archive()
        self.assertEqual(profile.snapshot()['next_signing_nonce'],'2')
        self.assertEqual(profile.pending_authorization(packet),cancelled)
        consumed=self.packet(profile,nonce=1,height=3,balance=10**12)
        remaining=profile.pending(consumed)
        self.assertEqual(unpack(remaining)['payments'],unpack(raw)['payments'][1:])
        state=self.signer_state(profile);profile.close();profile=self.open('Protocol')
        self.assertEqual(self.signer_state(profile),state)
        self.assertEqual(profile.original('1'),raw);self.assertEqual(profile.original('2'),cancelled)
        self.assertFalse(profile.snapshot()['payments_executed_asserted'])

    def test_publication_faults_preserve_exact_old_or_new_durable_state(self):
        for mode in ('before_file','after_publish','before_catalog_commit','after_catalog_commit'):
            with self.subTest(mode=mode):
                profile=self.bound('Fault'+str(len(self.profiles)));raw=self.signed(profile,0);before=self.signer_state(profile)
                if mode=='before_file':
                    original=journals.secure_open
                    def fail(path,*args,**options):
                        if Path(path).name.startswith('pending-'):raise OSError('PUBLIC_OWNED_FILE_FAULT')
                        return original(path,*args,**options)
                    seam=patch.object(journals,'secure_open',side_effect=fail)
                elif mode=='after_publish':
                    original=journals.Segments.publish
                    def fail(instance,*args,**options):
                        original(instance,*args,**options)
                        raise OSError('PUBLIC_OWNED_PUBLICATION_FAULT')
                    seam=patch.object(journals.Segments,'publish',new=fail)
                else:
                    original=profile._commit
                    def fail():
                        final=profile._body.get('journal',{}).get('archive_count')=='1' and profile._body['journal']['pending'] is None
                        if final and mode=='before_catalog_commit':raise OSError('PUBLIC_OWNED_COMMIT_FAULT')
                        original()
                        if final:raise OSError('PUBLIC_OWNED_COMMIT_ACK_FAULT')
                    seam=patch.object(profile,'_commit',side_effect=fail)
                with seam,self.assertRaises((OSError,ValueError)):profile.archive()
                name=profile.name;profile.close();profile=self.open(name)
                self.assertEqual(self.signer_state(profile),before)
                self.assertEqual(profile.original('1'),raw)
                self.assertIsNone(profile._body['journal']['pending'])
                self.assertEqual(profile._segments._readers,0)
                self.assertEqual(self.signed(profile,1),profile.original('2'))

    def test_cancelled_pending_sqlite_segment_and_rollback_file_recover_without_new_nonce(self):
        profile=self.bound();raw=self.signed(profile,0);before=self.signer_state(profile)
        original=journals.Segments.publish
        def cancelled(instance,journal,pending,rows,**options):
            def stop():raise ValueError('PUBLIC_CANCELLED_ROTATION')
            return original(instance,journal,pending,rows,check=stop)
        with patch.object(journals.Segments,'publish',new=cancelled),self.assertRaisesRegex(ValueError,'PUBLIC_CANCELLED'):
            profile.archive()
        pending=profile._body['journal']['pending'];self.assertIsNotNone(pending)
        # Simulate an actual process-loss leftover at the exact sealed temporary
        # name. This is not an accepted immutable archive or a payload mock.
        sidecar=profile.root/'journal-segments'/('pending-'+pending['token']+'.ggjournal-journal')
        sidecar.write_bytes(b'PUBLIC interrupted SQLite journal')
        journals.set_private_mode(sidecar,0o600)
        self.assertEqual(profile._segments._readers,0)
        profile.close();profile=self.open()
        self.assertEqual(self.signer_state(profile),before);self.assertEqual(profile.original('1'),raw)
        self.assertFalse(sidecar.exists())

    def test_missing_foreign_and_same_size_mtime_corruption_never_allow_signing(self):
        for mode in ('missing','foreign','same_size_mtime'):
            with self.subTest(mode=mode):
                profile=self.bound('Damage'+str(len(self.profiles)));self.signed(profile,0);profile.archive()
                before=self.signer_state(profile);path=self.segment_paths(profile)[0]
                if mode=='missing':path.unlink()
                elif mode=='foreign':
                    other=path.parent/'foreign.ggjournal';other.write_bytes(b'PUBLIC foreign artifact');journals.set_private_mode(other,0o600)
                else:
                    stamp=path.stat();data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
                    os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                    self.assertEqual(path.stat().st_size,stamp.st_size);self.assertEqual(path.stat().st_mtime_ns,stamp.st_mtime_ns)
                with patch.object(profile._key,'sign_message',side_effect=AssertionError('damaged archive reached signing')):
                    with self.assertRaises(ValueError):self.signed(profile,1)
                self.assertEqual(profile._body['next_nonce'],before[2]);self.assertEqual(profile._body['batch_count'],before[3])
                name=profile.name;profile.close()
                with self.assertRaises(ValueError):accounts.AccountProfile.open(name)

    @unittest.skipUnless(os.name=='nt','real Windows file change-time regression')
    def test_windows_preserved_length_and_mtime_mutation_changes_the_warm_inventory(self):
        profile=self.bound();self.signed(profile,0);profile.archive();path=self.segment_paths(profile)[0]
        before=self.signer_state(profile);inventory=profile._segments._inventory;stamp=path.stat()
        data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(path.stat().st_size,stamp.st_size);self.assertEqual(path.stat().st_mtime_ns,stamp.st_mtime_ns)
        self.assertNotEqual(profile._segments._inventory_value(profile._body['journal']),inventory,
                            'Windows creation time was mistaken for a mutation marker')
        with patch.object(profile._key,'sign_message',side_effect=AssertionError('mutated archive reached signing')):
            with self.assertRaisesRegex(ValueError,'OWN_JOURNAL_UNAVAILABLE'):self.signed(profile,1)
        self.assertTrue(profile._failed)
        self.assertEqual((profile._body['next_nonce'],profile._body['batch_count']),(before[2],before[3]))
        name=profile.name;profile.close()
        with self.assertRaises(ValueError):accounts.AccountProfile.open(name)

    @unittest.skipUnless(os.name=='nt','real Windows GetFileInformationByHandleEx error path')
    def test_windows_change_time_query_failure_closes_descriptor_and_prevents_signing(self):
        import ctypes
        profile=self.bound();raw=self.signed(profile,0);profile.archive();before=self.signer_state(profile)
        load=ctypes.WinDLL;changed=journals._windows_change_time;descriptors=[];queries=[]
        class FailedQuery:
            def __call__(self,*args):
                queries.append(args[0]);ctypes.set_last_error(5);return 0
        class KernelFacade:
            def __init__(self,library):self.library=library;self.GetFileInformationByHandleEx=FailedQuery()
            def __getattr__(self,name):return getattr(self.library,name)
        def failed_library(name,*args,**options):
            library=load(name,*args,**options)
            return KernelFacade(library) if str(name).lower()=='kernel32' else library
        def observed(descriptor):descriptors.append(descriptor);return changed(descriptor)
        # All opens, private ACL checks and file handles are real. Only the
        # exact GetFileInformationByHandleEx call returns an OS error.
        with patch.object(ctypes,'WinDLL',side_effect=failed_library),patch.object(journals,'_windows_change_time',side_effect=observed),\
                patch.object(profile._key,'sign_message',side_effect=AssertionError('unreadable identity reached signing')):
            with self.assertRaisesRegex(ValueError,'OWN_JOURNAL_UNAVAILABLE'):self.signed(profile,1)
        self.assertTrue(queries);self.assertTrue(descriptors);self.assertTrue(profile._failed)
        for descriptor in descriptors:
            with self.assertRaises(OSError):os.fstat(descriptor)
        self.assertEqual((profile._body['next_nonce'],profile._body['batch_count']),(before[2],before[3]))
        self.assertEqual(profile._segments._readers,0);self.assertIsNotNone(profile._lease)
        profile.close();profile=self.open()
        self.assertEqual(self.signer_state(profile),before);self.assertEqual(profile.original('1'),raw)

    def test_unchanged_warm_signing_does_not_rehash_retained_payload_history(self):
        profile=self.bound()
        with patch.object(journals,'MAX_ACTIVE_RECORDS',2):
            for nonce in range(8):self.signed(profile,nonce)
        profile.archive();self.assertGreater(len(self.segment_paths(profile)),2)
        # Normal new-record work may inventory segment metadata, but must not
        # add a full-history payload scan to every new intent. No rollover is
        # needed while this new record fits the empty active window.
        with patch.object(journals.producer_files,'file_hash',side_effect=AssertionError('warm sign rehashed history')):
            raw=self.signed(profile,8)
        self.assertEqual(profile.original('9'),raw)
        calls=[];file_hash=journals.producer_files.file_hash
        def observed(path,*args,**options):calls.append(Path(path).name);return file_hash(path,*args,**options)
        with patch.object(journals.producer_files,'file_hash',side_effect=observed):
            self.assertTrue(profile.original('1'))
        self.assertTrue(calls,'historical use skipped actual segment hashing')

    def test_cold_cursor_cannot_claim_a_nonce_or_cancellation_not_derived_from_originals(self):
        profile=self.bound();raw=self.signed(profile,0);profile.archive()
        # A deliberately owner-signed but false checkpoint is not proof that the
        # old originals replayed. Read must derive the cursor independently.
        changed=deepcopy(profile._body['journal']);changed['cursor']['next_nonce']='2'
        profile._write({'journal':changed});name=profile.name;profile.close()
        with self.assertRaises(ValueError):accounts.AccountProfile.open(name)
        self.assertTrue(bool(raw))

    def test_segment_byte_limit_and_owner_lease_fail_closed_with_originals_retained(self):
        profile=self.bound();raw=self.signed(profile,0);before=self.signer_state(profile)
        with self.assertRaisesRegex(ValueError,'PROFILE_IN_USE'):accounts.AccountProfile.open(profile.name)
        with patch.object(journals,'MAX_SEGMENT_BYTES',8192),self.assertRaises((sqlite3.Error,ValueError,OSError)):
            profile.archive()
        name=profile.name;profile.close();profile=self.open(name)
        self.assertEqual(self.signer_state(profile),before);self.assertEqual(profile.original('1'),raw)

    def test_readonly_close_error_retains_owned_reference_until_exact_retry(self):
        profile=self.bound();raw=self.signed(profile,0);profile.archive();before=self.signer_state(profile)
        connect=journals.sqlite3.connect;faulted=[]
        class CloseOutcome:
            def __init__(self,db):self.db=db;self.once=True
            def __getattr__(self,name):return getattr(self.db,name)
            def close(self):
                self.db.close()
                if self.once:self.once=False;faulted.append(True);raise OSError('PUBLIC_AFTER_REAL_READONLY_CLOSE')
        def wrapped(path,*args,**options):
            db=connect(path,*args,**options)
            return CloseOutcome(db) if '.ggjournal?mode=ro' in str(path) else db
        with patch.object(journals.sqlite3,'connect',side_effect=wrapped),self.assertRaises(OSError):profile.original('1')
        self.assertTrue(faulted);self.assertEqual(profile._segments._readers,1);self.assertIsNotNone(profile._lease)
        with self.assertRaisesRegex(ValueError,'PROFILE_IN_USE'):accounts.AccountProfile.open(profile.name)
        profile.close();self.assertEqual(profile._segments._readers,0)
        profile=self.open();self.assertEqual(self.signer_state(profile),before);self.assertEqual(profile.original('1'),raw)


class ProtectedPoolJournalTests(unittest.TestCase):
    setUp=account_fixtures.ProtectedFinancialAccountTests.setUp
    close_profiles=account_fixtures.ProtectedFinancialAccountTests.close_profiles
    create=account_fixtures.ProtectedFinancialAccountTests.create
    open=account_fixtures.ProtectedFinancialAccountTests.open
    packet=account_fixtures.ProtectedFinancialAccountTests.packet
    outputs=account_fixtures.ProtectedFinancialAccountTests.outputs
    signed=ProtectedJournalRotationTests.signed
    signer_state=ProtectedJournalRotationTests.signer_state
    segment_paths=ProtectedJournalRotationTests.segment_paths

    def legacy_layout(self,book):
        self.assertEqual(book._db.execute('SELECT count(*) FROM journal_archives').fetchone(),(0,))
        rows=list(book._active_events());previous=pools._digest(pools.DOMAIN+b'EMPTY\0'+pack(book.config));expected=[]
        book._db.execute('BEGIN IMMEDIATE')
        for index,key,epoch,meta,raw in rows:
            event=book._decode_event(raw);event['schema']='gg.financial.pool-event.v1';event['previous']=previous
            if event['kind']=='PREPARED' and isinstance(event['data']['account_batch'],dict):
                event['data']['account_batch']=int(event['data']['account_batch']['number'])
            wire_raw=pack(book._signed(event,b'EVENT\0'));expected.append(wire_raw);previous=pools._digest(wire_raw)
            book._db.execute('UPDATE events SET record=? WHERE position=?',(wire_raw,index))
        book._db.execute('DROP INDEX journal_range');book._db.execute('DROP TABLE journal_archives')
        book._head.pop('journal');book._head.update(schema='gg.financial.pool-head.v1',head=previous)
        book._db.execute('PRAGMA user_version=1');book._put_head();book._db.execute('COMMIT');book._segments=None;book._store_version=1;book._seal()
        return expected,previous
    def pool_fixture(self,*,income=True,suffix=''):
        wallet=self.create('Reward'+suffix);self.anchor=public_protocol_pin(reward_account=wallet.public_address());wallet.bind(self.anchor)
        creator=public_key(302);worker=public_key(901);key=creator.pubkey().hex();source=self.anchor['genesis']['financial_dag']
        # Same canonical initial producer boundary as the working stale-job
        # fixture. There is no financial.producer_origin API. Job/core/worker
        # signatures, work, durable events and receipt policy remain real.
        origin=hashlib.sha256(financial.DOMAIN+b'DAG-GENESIS\0'+pack({'anchor':self.anchor['genesis_hash'],'source':financial.source_hash(source)})).hexdigest()
        body={'created_at_ns':source['started_at_ns'],'epoch':'1','genesis_hash':self.anchor['genesis_hash'],'parents':[origin],
            'payment_root':wire.payment_root([]),'payments':[],'producer_key':key,'rank':'1','schema':'gg.financial-dag.block.v2',
            'sequence':'1','source_hash':financial.source_hash(source)}
        core={'body':body,'signature':creator.sign_message(financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(body)).hex()}
        record={'sequence':'0','rank':'0','head':origin,'invite':deepcopy(self.anchor['genesis']['protocol']['initial_producers'][0])}
        certificate={'state':{'height':10,'financial_dag':{'epoch':'1'},'protocol':{'economics':{'next_epoch':'0'},
            'work_anchor_height':'8','work_anchor_root':'a'*64,'work_target':'f'*64,'time_ns':source['started_at_ns']}}}
        def selected(packet,trust,**options):
            if trust!=self.anchor:raise ValueError('PUBLIC_POLICY_FOREIGN_PIN')
            if 'reward' in options:
                if packet.get('test_only_income')!='income:1':raise ValueError('PUBLIC_POLICY_REWARD_REQUEST')
                return {'financial_reward_credit':{'amount_atomic':'100000'},'financial_reward_epoch':'0'}
            return {'financial_registry_exists':True,'financial_registry_value':base64.b64encode(pack(record)).decode()}
        self.stack.enter_context(patch.object(protocol,'verify_selected',side_effect=selected))
        def receipt(packet,trust,*,expected_transaction_id,**options):
            if trust!=self.anchor or packet.get('test_only_payment')!=expected_transaction_id:raise ValueError('PUBLIC_POLICY_RECEIPT_REQUEST')
            return {'financial_receipt':{'transaction_id':expected_transaction_id,'outcome':packet['test_only_outcome']}}
        self.stack.enter_context(patch.object(financial,'verify_receipt',side_effect=receipt))
        job=protocol.derive_block_job(core,certificate,self.anchor,key,worker.pubkey().hex(),'f'*64)
        solution,_,_=economy.mine_work(job.document(),worker,0,1)
        self.assertIsNotNone(solution)
        signer=public_key(300);operator=public_key(902).pubkey().hex();self.book_args=(Path(self.temp.name)/('pool'+suffix),signer,self.anchor,wallet.public_address(),operator,1000)
        book=pools.PoolBook.create(*self.book_args);self.addCleanup(book.close)
        assignment=book.register_job(job,public_key(903).pubkey().hex())['body']['assignment']
        self.pool_job=job;self.pool_worker=worker;self.pool_assignment=assignment
        book.accept_share(assignment,solution,10)
        if income:book.record_income('1',{'test_only_income':'income:1'})
        return wallet,book

    def test_pending_cross_store_payout_finds_exact_archived_account_and_pool_original(self):
        wallet,book=self.pool_fixture();review=book.review_payout('1',wallet,self.packet(wallet,balance=10**12))
        original=book._append
        def interrupted(kind,*args,**options):
            if kind=='ORIGINAL':raise OSError('PUBLIC_AFTER_ACCOUNT_COMMIT')
            return original(kind,*args,**options)
        with patch.object(book,'_append',side_effect=interrupted),self.assertRaises(OSError):book.sign_payout(review,wallet)
        expected=wallet.original();state=self.signer_state(wallet);book.archive();wallet.archive()
        prepared=book._get('PREPARED','1:0')['data']['account_batch']
        self.assertEqual(prepared['number'],'1');self.assertEqual(prepared['previous_head'],accounts._empty(wallet.public_address()))
        wallet.close();wallet=self.open('Reward');book.close();book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
        recovered=book.resume_original('1:0',wallet)
        self.assertEqual(recovered,expected);self.assertEqual(self.signer_state(wallet),state)
        self.assertEqual(book.resume_original('1:0',wallet),expected)
        self.assertEqual(wallet.snapshot()['signed_batches_exact'],'1')
        self.assertFalse(book.snapshot()['money_from_shares_asserted'])

    def test_old_paid_receipts_cannot_disappear_or_authorize_a_second_payout(self):
        wallet,book=self.pool_fixture();review=book.review_payout('1',wallet,self.packet(wallet,balance=10**12))
        raw=book.sign_payout(review,wallet);payments=wire.decode_payment_document(raw,self.anchor)
        for index,payment in enumerate(payments):
            identifier=wire.intent_id(pack(payment))
            bad={'test_only_payment':identifier,'test_only_outcome':'REJECTED_NONCE'}
            with self.assertRaisesRegex(ValueError,'NOT_APPLIED'):book.remember_applied('1:0',index,bad)
            book.remember_applied('1:0',index,{'test_only_payment':identifier,'test_only_outcome':'APPLIED'})
        expected=book.liabilities('1');self.assertEqual(expected['unpaid'],[])
        head=book._head['head'];book.archive();wallet.archive()
        self.assertEqual(book.liabilities('1'),expected);self.assertEqual(book._head['head'],head)
        book.close();book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
        self.assertEqual(book.liabilities('1'),expected)
        with self.assertRaises(ValueError):book.review_payout('1',wallet,self.packet(wallet,nonce=len(payments),height=2,balance=10**12))
        path=book.root/'journal-segments'/(book._db.execute('SELECT digest FROM journal_archives ORDER BY number').fetchone()[0]+'.ggjournal')
        stamp=path.stat();connection=sqlite3.connect(path)
        try:
            connection.execute("UPDATE records SET selector=replace(selector,'PAID:','NOPE:') WHERE selector LIKE 'PAID:%'");connection.commit()
        finally:connection.close()
        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(path.stat().st_size,stamp.st_size);self.assertEqual(path.stat().st_mtime_ns,stamp.st_mtime_ns)
        # Inject only a metadata-cache collision, never a crypto/native policy
        # acceptance: even this adversarial warm witness cannot bless absence.
        book._segments._inventory=book._segments._inventory_value(book._head['journal'])
        before=wallet.batch_count()
        with self.assertRaises(ValueError):book.liabilities('1')
        self.assertEqual(wallet.batch_count(),before)
        self.assertEqual(book.snapshot()['state'],'FAULT')

    def test_filtered_no_match_performs_real_segment_hash_and_foreign_config_is_rejected(self):
        wallet,book=self.pool_fixture();book.archive()
        original=journals.producer_files.file_hash;calls=[]
        def observed(path,*args,**options):
            calls.append(Path(path).name)
            return original(path,*args,**options)
        with patch.object(journals.producer_files,'file_hash',side_effect=observed):
            self.assertIsNone(book._get('PAID','f'*64))
        self.assertTrue(calls,'no-match trusted SQLite absence without actual file hashing')
        record=book._db.execute('SELECT header FROM journal_archives ORDER BY number').fetchone()[0]
        other=pools.PoolBook.create(Path(self.temp.name)/'different-fee-book',self.book_args[1],self.anchor,wallet.public_address(),self.book_args[4],999)
        self.addCleanup(other.close);other._ensure_journal(lambda:None)
        with self.assertRaises(ValueError):other._segments._header(bytes(record))

    def test_multi_segment_cold_audit_hash_work_scales_by_segments_not_historical_queries(self):
        wallet,book=self.pool_fixture(income=False)
        with patch.object(journals,'MAX_ACTIVE_RECORDS',4):
            for nonce in range(1,25):
                solution,_,_=economy.mine_work(self.pool_job.document(),self.pool_worker,nonce,1)
                self.assertIsNotNone(solution)
                book.accept_share(self.pool_assignment,solution,10)
        book.record_income('1',{'test_only_income':'income:1'});book.archive()
        segments=int(book.snapshot()['own_journal']['archive_segments']);self.assertGreater(segments,3)
        expected=book._head['head'];book.close()
        original=journals.producer_files.file_hash;calls=[]
        def observed(path,*args,**options):
            calls.append(Path(path).name)
            return original(path,*args,**options)
        with patch.object(journals.producer_files,'file_hash',side_effect=observed):
            reopened=pools.PoolBook.open(*self.book_args)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened._head['head'],expected)
        self.assertEqual(reopened.snapshot()['state'],'READY');self.assertIsNone(reopened._cold_audit)
        self.assertLessEqual(len(calls),segments*10,'cold semantic lookups repeatedly full-hashed prior segment payloads')
        self.assertGreaterEqual(len(calls),segments*2,'cold audit did not actually hash every segment')

    def test_actual_legacy_pool_v1_events_read_and_migrate_without_reindexing_identity(self):
        wallet,book=self.pool_fixture(income=False)
        # Produce a genuine historical v1 fixture with real control signatures,
        # exact old event encoding and the original schema, not a native proof.
        expected,previous=self.legacy_layout(book)
        book.close();book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
        self.assertEqual(book._head['schema'],'gg.financial.pool-head.v1');self.assertEqual(book._head['head'],previous)
        self.assertEqual([row[4] for row in book._active_events()],expected)
        book.archive();self.assertEqual(book._head['head'],previous)
        self.assertEqual(book.snapshot()['retained_events_exact'],'2')
        book.close();book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
        with closing(book._all_events(full=True)) as actual:self.assertEqual([row[4] for row in actual],expected)
        self.assertEqual(book.snapshot()['state'],'READY');self.assertIsNone(book._cold_audit)

    def test_legacy_integer_prepared_reference_recovers_after_both_journals_rotate(self):
        wallet,book=self.pool_fixture();review=book.review_payout('1',wallet,self.packet(wallet,balance=10**12))
        book._append('PREPARED','1:0','0',unpack(review.prepared))
        raw=wallet.sign(review.account_review);expected_state=self.signer_state(wallet)
        old_events,head=self.legacy_layout(book);book.close()
        book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
        self.assertEqual(book._get('PREPARED','1:0')['data']['account_batch'],1)
        wallet.archive();book.archive()
        self.assertEqual(book.resume_original('1:0',wallet),raw)
        self.assertEqual(self.signer_state(wallet),expected_state)
        with closing(book._all_events(full=True)) as rows:
            current=[row[4] for row in rows]
        self.assertEqual(current[:len(old_events)],old_events)
        self.assertEqual(book.snapshot()['retained_events_exact'],'5')

    def test_pool_catalog_commit_uncertainty_preserves_liabilities_and_same_head(self):
        for mode in ('before','after'):
            with self.subTest(mode=mode):
                wallet,book=self.pool_fixture(suffix=mode);expected=book.liabilities('1');head=book._head['head'];events=book._head['events']
                connection=book._db
                class CommitOutcome:
                    def __getattr__(self,name):return getattr(connection,name)
                    def execute(self,sql,*args):
                        final=(sql=='COMMIT' and book._head.get('journal',{}).get('archive_count')=='1'
                               and book._head['journal']['pending'] is None)
                        if final and mode=='before':raise OSError('PUBLIC_BEFORE_POOL_COMMIT')
                        result=connection.execute(sql,*args)
                        if final:raise OSError('PUBLIC_AFTER_POOL_COMMIT')
                        return result
                book._db=CommitOutcome()
                with self.assertRaises(OSError):book.archive()
                book.close();book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
                self.assertEqual(book._head['head'],head);self.assertEqual(book._head['events'],events)
                self.assertEqual(book.liabilities('1'),expected);self.assertEqual(wallet.snapshot()['next_signing_nonce'],'0')
                self.assertEqual(book._segments._readers,0);self.assertIsNone(book._cold_audit)

    def test_partial_cold_index_never_reports_ready_or_creates_a_signature(self):
        wallet,book=self.pool_fixture();book.archive();source_head=book._head['head'];book.close()
        original=pools._PoolColdAudit.finish
        def corrupt_prefix(audit):
            self.assertEqual(audit.book.snapshot()['state'],'VERIFYING_OWN_JOURNAL')
            with self.assertRaisesRegex(ValueError,'COLD_AUDIT_ACTIVE'):
                audit.book.register_job(self.pool_job,public_key(903).pubkey().hex())
            audit.db.execute('DELETE FROM verified WHERE position=1')
            return original(audit)
        with patch.object(pools._PoolColdAudit,'finish',new=corrupt_prefix),\
                patch.object(pools.PoolBook,'_signed',side_effect=AssertionError('cold audit attempted a new signature')),\
                self.assertRaisesRegex(ValueError,'COLD_INDEX_CORRUPT'):
            pools.PoolBook.open(*self.book_args)
        # A failed audit cannot mutate the accepted pool or signing nonce.
        book=pools.PoolBook.open(*self.book_args);self.addCleanup(book.close)
        self.assertEqual(book._head['head'],source_head);self.assertEqual(book.snapshot()['state'],'READY')
        self.assertEqual(wallet.snapshot()['next_signing_nonce'],'0')

    def test_active_paid_column_absence_cannot_bypass_the_own_signed_suffix(self):
        wallet,book=self.pool_fixture();review=book.review_payout('1',wallet,self.packet(wallet,balance=10**12))
        raw=book.sign_payout(review,wallet);payments=wire.decode_payment_document(raw,self.anchor)
        for index,payment in enumerate(payments):
            identifier=wire.intent_id(pack(payment))
            book.remember_applied('1:0',index,{'test_only_payment':identifier,'test_only_outcome':'APPLIED'})
        self.assertEqual(book.liabilities('1')['unpaid'],[]);before=wallet.batch_count()
        # Model a corrupted derived column while keeping real signed raw events
        # and the accepted owner head. Refreshing only a change marker is NOT
        # an integrity witness and must never make that absence authoritative.
        book._db.execute("UPDATE events SET kind='NOPE' WHERE kind='PAID'");book._seal()
        with self.assertRaises(ValueError):book.liabilities('1')
        self.assertEqual(wallet.batch_count(),before);self.assertEqual(book.snapshot()['state'],'FAULT')
        self.assertEqual(book._active_read_depth,0)

