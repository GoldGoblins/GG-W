"""Interrupted real signed LAN GET plus bounded untrusted-cache fault tests.

Transport/admission tests use real TCP and disposable encrypted node profiles.
They make no SDK certificate/finality claim; the separate four-SDK gates do that.
"""
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_lan_dag as lan,gg_lan_resume as resume
from backend.gg_parallel_dag import pack,digest,_tree
from backend.gg_dag_wire import CHUNK_BYTES,MAX_BLOCK_WIRE_BYTES,RecordAssembler,record_frames
from tests import test_owned_ingress as fixtures


class LanGetResumeTests(unittest.TestCase):
    setUp=fixtures.OwnedIngressTests.setUp
    cleanup=fixtures.OwnedIngressTests.cleanup
    peer=fixtures.OwnedIngressTests.peer
    network=fixtures.OwnedIngressTests.network
    block=fixtures.OwnedIngressTests.block

    def large(self,count=128):
        owner,receiver,other=self.network()
        for peer in (owner,receiver,other):
            peer._wire_limit=8*1024*1024
            peer._engine.configure_lan_capacity(block_bytes=8*1024*1024,session_bytes=64*1024*1024)
        return owner,receiver,other,self.block(owner,count=count)

    def interrupt(self,owner,receiver,block,parts=1):
        original=receiver._read;seen=[0]
        def cut(sock,*args,**kwargs):
            packet,size=original(sock,*args,**kwargs)
            if packet.get('body',{}).get('kind')=='DATA_PART':
                seen[0]+=1
                if seen[0]==parts+1:
                    sock.close()
                    raise ValueError('GG_LAN_EOF')
            return packet,size
        with patch.object(receiver,'_read',side_effect=cut):
            with self.assertRaisesRegex(ValueError,'GG_LAN_EOF'):
                receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(receiver._get_resumes.status()['downloaded_bytes'],parts*CHUNK_BYTES)
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        self.assertFalse(receiver._engine.has_proposal(block['hash']))
        self.assertEqual(receiver._get_resumes.status()['active_requests'],0)
        return next(iter(receiver._get_resumes.rows.values()))

    def test_actual_5000_signed_TX_resume_next_offset_after_fresh_authentication(self):
        owner,receiver,_,block=self.large(5000);tokens=[];offsets=[]
        auth=receiver._client_auth;frames=lan.record_frames
        def fresh(*args,**kwargs):
            value=auth(*args,**kwargs);tokens.append(value);return value
        def observed(record,**kwargs):
            if record['hash']==block['hash']:offsets.append(kwargs.get('resume_offset',0))
            yield from frames(record,**kwargs)
        with patch.object(receiver,'_client_auth',side_effect=fresh),patch.object(lan,'record_frames',side_effect=observed):
            row=self.interrupt(owner,receiver,block,parts=4);file=row['file']
            self.assertEqual(receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]}),1)
        self.assertEqual(offsets,[0,4*CHUNK_BYTES]);self.assertEqual(len(tokens),2);self.assertNotEqual(*tokens)
        self.assertTrue(file.closed);self.assertEqual(receiver._get_resumes.status()['partial_records'],0)
        self.assertTrue(receiver._engine.has_proposal(block['hash']))
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],1)
        self.assertEqual(receiver._engine.lan_evidence()['transactions'],5000)
        self.assertEqual(receiver._profile.read_dag(block['hash']),block['wire'])
        self.assertEqual(receiver.snapshot()['canonical_finalized'],0)

    def test_bad_outer_END_keeps_untrusted_complete_prefix_then_reauthenticates_without_redownload(self):
        owner,receiver,_,block=self.large();frame=owner._frame
        def bad(session,sequence,kind,payload):
            return frame(session,sequence,kind,{'records':2} if kind=='END' else payload)
        with patch.object(owner,'_frame',side_effect=bad):
            with self.assertRaisesRegex(ValueError,'GG_LAN_PAGE_END'):
                receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(receiver._get_resumes.status()['downloaded_bytes'],len(block['wire']))
        frames=lan.record_frames;sent=[]
        def observed(record,**kwargs):
            for kind,data in frames(record,**kwargs):sent.append((kind,data));yield kind,data
        with patch.object(lan,'record_frames',side_effect=observed):
            receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual([kind for kind,_ in sent],['DATA_START','DATA_END'])
        self.assertEqual(sent[0][1]['offset'],len(block['wire']))
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],1)

    def test_changed_spooled_bytes_fail_full_rehash_and_never_enter_journal(self):
        owner,receiver,_,block=self.large();row=self.interrupt(owner,receiver,block)
        file=row['file'];file.seek(0);file.write(b'!')
        with self.assertRaisesRegex(ValueError,'GG_LAN_CHUNK_HASH'):
            receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertTrue(file.closed);self.assertEqual(receiver._get_resumes.status()['reserved_disk_bytes'],0)
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        self.assertFalse(receiver._engine.has_proposal(block['hash']))
        receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],1)

    def test_changed_descriptor_restarts_exact_wire_without_mixing_cached_prefix(self):
        owner,receiver,_,block=self.large();row=self.interrupt(owner,receiver,block)
        file=row['file'];row['meta']['wire_sha256']='f'*64
        frames=lan.record_frames;offsets=[]
        def observed(record,**kwargs):
            offsets.append(kwargs.get('resume_offset',0));yield from frames(record,**kwargs)
        with patch.object(lan,'record_frames',side_effect=observed):
            receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(offsets,[0]);self.assertTrue(file.closed)
        self.assertEqual(receiver._profile.read_dag(block['hash']),block['wire'])

    def test_local_spool_creation_failure_does_not_accuse_valid_remote_peer(self):
        owner,receiver,_,block=self.large()
        with patch.object(resume.tempfile,'TemporaryFile',side_effect=OSError('owned local disk fault')):
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_SPOOL_UNAVAILABLE'):
                receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertNotIn(owner.public_key,receiver._peer_failures)
        self.assertEqual(receiver._get_resumes.status()['reserved_disk_bytes'],0)
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(receiver._get_resumes.status()['local_fault'],'')

    def test_short_local_write_closes_spool_and_cannot_admit_or_accuse_remote(self):
        owner,receiver,_,block=self.large();original=resume.tempfile.TemporaryFile;files=[]
        class Short:
            def __init__(self):self.file=original(mode='w+b');files.append(self.file)
            def seek(self,*args):return self.file.seek(*args)
            def write(self,data):return len(data)-1
            def close(self):return self.file.close()
        with patch.object(resume.tempfile,'TemporaryFile',side_effect=lambda **kwargs:Short()):
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_SPOOL_WRITE'):
                receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertTrue(files and all(file.closed for file in files))
        self.assertNotIn(owner.public_key,receiver._peer_failures)
        self.assertEqual(receiver._get_resumes.status()['active_requests'],0)
        self.assertEqual(receiver._get_resumes.status()['partial_records'],0)
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)

    def test_stop_closes_untrusted_prefix_without_admitting_it(self):
        owner,receiver,_,block=self.large();row=self.interrupt(owner,receiver,block);file=row['file']
        receiver.stop();self.assertTrue(file.closed)
        self.assertEqual(receiver._get_resumes.status()['partial_records'],0)

    def test_old_peer_rejecting_hint_falls_back_next_request_without_changing_validation(self):
        owner,receiver,_,block=self.large();row=self.interrupt(owner,receiver,block);file=row['file']
        check=owner._check_frame
        def old(*args,**kwargs):
            value=check(*args,**kwargs)
            if value['kind']=='GET' and 'resume' in value['payload']:raise ValueError('GG_LAN_REQUEST')
            return value
        with patch.object(owner,'_check_frame',side_effect=old):
            with self.assertRaises(ValueError):receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
            self.assertEqual(receiver._get_resumes.status()['hint_fallback_peers'],1)
            self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
            receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertTrue(file.closed);self.assertEqual(receiver._profile.read_dag(block['hash']),block['wire'])

    def test_resumed_wire_digest_and_valid_outer_signature_cannot_bypass_bad_TX_signature(self):
        owner,receiver,_,block=self.large();envelope=json.loads(block['wire'])
        envelope['body']['transactions'][0]['signature']='0'*128
        envelope['body']['payload_root']=_tree(envelope['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        envelope['signature']=owner._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(envelope['body'])).hex()
        bad={'hash':digest(envelope['body'],b'GG-DAG-BLOCK-v1\0'),'wire':pack(envelope)}
        relay=owner._relay_proposal
        with patch.object(owner,'_relay_proposal',side_effect=lambda identifier:bad['wire'] if identifier==bad['hash'] else relay(identifier)):
            row=self.interrupt(owner,receiver,bad);file=row['file']
            with self.assertRaisesRegex(ValueError,'GG_DAG_SIGNATURE'):
                receiver._pull(owner.public_key,'GET',{'hashes':[bad['hash']]})
        self.assertTrue(file.closed);self.assertEqual(receiver._get_resumes.status()['partial_records'],0)
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(receiver._engine.lan_evidence()['transactions'],0)
        self.assertFalse(receiver._engine.has_proposal(bad['hash']))


class ResumeCacheBudgetTests(unittest.TestCase):
    def setUp(self):
        self.cache=resume.GetResumeCache();self.addCleanup(self.cache.close);self.cancel=threading.Event()

    def begin(self,peer,identifier,deadline=None):
        return self.cache.begin(peer,'c'*64,[identifier],MAX_BLOCK_WIRE_BYTES,
            time.monotonic()+1 if deadline is None else deadline,self.cancel)

    @staticmethod
    def meta(identifier,size=16*1024*1024):
        return {'hash':identifier,'admission_index':0,'size':size,'wire_sha256':'d'*64,'parts':(size+CHUNK_BYTES-1)//CHUNK_BYTES}

    def partial(self,peer,identifier):
        session=self.begin(peer,identifier)
        try:session.start(self.meta(identifier),0);session.append(b'x'*CHUNK_BYTES)
        finally:session.close()

    def test_each_peer_keeps_its_own_disk_credit_and_only_evicts_its_own_idle_rows(self):
        peers=['a'*64,'b'*64]
        for peer in peers:
            for index in range(4):self.partial(peer,hashlib.sha256((peer+str(index)).encode()).hexdigest())
        self.assertEqual(self.cache.status()['reserved_disk_bytes'],resume.MAX_BYTES)
        first={key:row['file'] for key,row in self.cache.rows.items() if key[1]==peers[0]}
        self.partial(peers[1],'e'*64)
        self.assertTrue(all(key in self.cache.rows and not file.closed for key,file in first.items()))
        self.assertEqual(self.cache.status()['reserved_disk_bytes'],resume.MAX_BYTES)

    def test_waiting_same_peer_is_cancellable_and_other_peer_still_has_its_lane(self):
        first=self.begin('a'*64,'d'*64)
        try:
            second=self.begin('b'*64,'e'*64);second.close()
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_RESUME_DEADLINE'):
                self.begin('a'*64,'d'*64,time.monotonic()+.02)
            self.cancel.set()
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_RESUME_STOPPED'):
                self.begin('a'*64,'d'*64)
        finally:first.close()

    def test_local_file_write_does_not_hold_shared_lock_or_block_other_peer(self):
        first=self.begin('a'*64,'d'*64);first.start(self.meta('d'*64),0)
        row=first.current[1];original=row['file'];entered=threading.Event();release=threading.Event();errors=[]
        class Slow:
            def seek(self,*args):return original.seek(*args)
            def write(self,data):entered.set();release.wait(2);return original.write(data)
            def close(self):return original.close()
        row['file']=Slow()
        def write():
            try:first.append(b'x'*CHUNK_BYTES)
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=write);worker.start()
        try:
            self.assertTrue(entered.wait(1))
            second=self.begin('b'*64,'e'*64)
            try:second.start(self.meta('e'*64),0);second.append(b'y'*CHUNK_BYTES)
            finally:second.close()
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_RESUME_BUSY'):self.cache.close()
        finally:release.set();worker.join(2);first.close()
        self.assertFalse(worker.is_alive());self.assertFalse(errors)

    def test_inactive_prefix_expires_and_closes_without_retaining_memory(self):
        self.partial('a'*64,'d'*64);row=next(iter(self.cache.rows.values()));file=row['file'];row['touched']=0
        self.cache.expire('a'*64)
        self.assertTrue(file.closed);self.assertEqual(self.cache.status()['reserved_disk_bytes'],0)

    def test_expiry_cannot_close_a_prefix_owned_by_an_active_request(self):
        self.partial('a'*64,'d'*64);key=next(iter(self.cache.rows));row=self.cache.rows[key]
        file=row['file'];session=self.begin('a'*64,'d'*64)
        try:
            row['touched']=0;self.cache.expire('a'*64);self.assertFalse(file.closed)
            session.start(row['meta'],CHUNK_BYTES);session.append(b'y'*CHUNK_BYTES)
            self.assertEqual(session.offset,2*CHUNK_BYTES)
        finally:session.close()

    def test_expiring_slow_file_keeps_credit_and_does_not_hold_other_peer_lane(self):
        self.partial('a'*64,'d'*64);row=next(iter(self.cache.rows.values()));file=row['file'];row['touched']=0
        entered=threading.Event();release=threading.Event();errors=[]
        class SlowClose:
            def close(self):entered.set();release.wait(2);return file.close()
        row['file']=SlowClose()
        def expire():
            try:self.cache.expire('a'*64)
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=expire);worker.start();second=None
        try:
            self.assertTrue(entered.wait(1));self.assertEqual(self.cache.status()['reserved_disk_bytes'],16*1024*1024)
            self.assertEqual(self.cache.status()['closing_files'],1)
            second=self.begin('b'*64,'e'*64);second.start(self.meta('e'*64),0);second.append(b'y'*CHUNK_BYTES)
            self.assertEqual(self.cache.status()['reserved_disk_bytes'],32*1024*1024)
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_RESUME_DEADLINE'):
                self.begin('a'*64,'d'*64,time.monotonic()+.02)
        finally:
            release.set();worker.join(2)
            if second is not None:second.close()
        self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertTrue(file.closed)

    def test_failed_close_retains_disk_credit_and_handle_until_confirmed_cleanup(self):
        self.partial('a'*64,'d'*64);key=next(iter(self.cache.rows));row=self.cache.rows[key];file=row['file'];attempts=[0]
        class FailedClose:
            def close(self):
                attempts[0]+=1
                if attempts[0]==1:raise OSError('owned close failure')
                return file.close()
        row['file']=FailedClose()
        with self.assertRaisesRegex(ValueError,'GG_LAN_GET_SPOOL_CLOSE'):self.cache._drop(key)
        self.assertFalse(file.closed);self.assertEqual(self.cache.status()['reserved_disk_bytes'],16*1024*1024)
        self.assertEqual(self.cache.status()['failed_cleanup_files'],1)
        with self.assertRaisesRegex(ValueError,'GG_LAN_GET_SPOOL_CLOSE'):self.begin('b'*64,'e'*64)
        self.cache.close();self.assertTrue(file.closed);self.assertEqual(self.cache.status()['reserved_disk_bytes'],0)

    def test_reported_error_after_confirmed_close_releases_credit_and_keeps_local_fault(self):
        self.partial('a'*64,'d'*64);key=next(iter(self.cache.rows));row=self.cache.rows[key];file=row['file']
        class ClosedWithError:
            @property
            def closed(self):return file.closed
            def close(self):file.close();raise OSError('owned reported failure after actual close')
        row['file']=ClosedWithError()
        with self.assertRaisesRegex(ValueError,'GG_LAN_GET_SPOOL_CLOSE'):self.cache._drop(key)
        self.assertTrue(file.closed);self.assertEqual(self.cache.status()['reserved_disk_bytes'],0)
        self.assertEqual(self.cache.status()['failed_cleanup_files'],0)
        self.assertEqual(self.cache.status()['local_fault'],'GG_LAN_GET_SPOOL_CLOSE')

    def test_resume_hint_shape_bound_and_complete_offset(self):
        value={'hash':'d'*64,'wire_sha256':'e'*64,'size':100001,'offset':100001}
        self.assertEqual(resume.resume_hints([value],['d'*64],200000)['d'*64],value)
        for field,bad in (('hash',[]),('size',True),('offset',1),('wire_sha256','bad')):
            changed={**value,field:bad}
            with self.assertRaises(ValueError):resume.resume_hints([changed],['d'*64],200000)


if __name__=='__main__':unittest.main()
