"""Worker/transport faults with actual signed payload and durable profiles.

Quorum verification is explicitly MOCKED here. Separate process acceptance
uses genuine four-SDK certificates, owned RPC and authenticated LAN transport.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from backend import gg_dag_payloads as candidate
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend.gg_dag_payloads import PayloadRecovery,CHUNK_BYTES
from backend.gg_dag_checkpoint import source_from_owned_peer
from tests import test_owned_ingress as fixtures,test_producer_branches as branches


class PayloadWorkerTests(unittest.TestCase):
    setUp=fixtures.OwnedIngressTests.setUp
    cleanup=fixtures.OwnedIngressTests.cleanup
    peer=fixtures.OwnedIngressTests.peer
    network=fixtures.OwnedIngressTests.network
    block=fixtures.OwnedIngressTests.block
    resume=fixtures.OwnedIngressTests.resume

    def wait(self,predicate,seconds=4):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        self.fail('owned payload worker timeout')

    def provider(self,owner,observer,blocks):
        self.public=owner._engine.export_public_genesis()
        state,order,accounts=branches.ProducerBranchTests.view(self,blocks)
        packet={'state':state};wires={block['hash']:block['wire'] for block in blocks};epoch=object()
        def reference(identifier):
            index=next((row['index'] for row in order if row['hash']==identifier),None)
            return None if index is None else {'certificate':deepcopy(packet),'order':deepcopy(order),'index':index}
        def chunk(packet,identifier,index,offset,**kwargs):
            raw=wires[identifier]
            return {'total':len(raw),'wire_hash':hashlib.sha256(raw).hexdigest(),'offset':offset,'data':raw[offset:offset+CHUNK_BYTES]}
        node=SimpleNamespace(payload_reference=reference,_check_proof_epoch=Mock(return_value=epoch),export_payload_chunk=Mock(side_effect=chunk))
        @contextmanager
        def reader(packet):yield epoch,lambda identifier,index,offset:node.export_payload_chunk(packet,identifier,index,offset,epoch=epoch)
        node.payload_reader=reader
        exchange=SimpleNamespace(peer=observer,sources=lambda:[node],anchor={'genesis':{'dag':source_from_owned_peer(owner)}},
            verifier=SimpleNamespace(verify=Mock()),_remember=Mock(),_fault='')
        worker=PayloadRecovery(exchange);self.addCleanup(worker.close)
        exchange.request_payloads=worker.request;exchange.request_stop=worker.request_stop;exchange.close=worker.close
        observer._proof_service=exchange
        return worker,node,exchange,chunk

    def test_authentic_get_enqueues_then_relays_fully_admitted_sdk_source_bytes(self):
        owner,provider,receiver=self.network();block=self.block(owner,count=128)
        worker,node,exchange,_=self.provider(owner,provider,[block])
        receiver._pull(provider.public_key,'GET',{'hashes':[block['hash']]})
        self.wait(lambda:provider._engine.has_proposal(block['hash']))
        receiver._pull(provider.public_key,'GET',{'hashes':[block['hash']]})
        self.assertTrue(receiver._engine.has_proposal(block['hash']))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],1);self.assertEqual(receiver._profile.snapshot()['counts']['dag'],1)
        self.assertGreater(node.export_payload_chunk.call_count,1);self.assertEqual(provider._engine._certified_order,())
        self.assertEqual(worker.snapshot()['recovered_blocks'],1);exchange.verifier.verify.assert_called()

    def test_parent_ordered_materialization_has_bounded_jobs_and_durable_progress(self):
        owner,provider,receiver=self.network();blocks=[self.block(owner) for _ in range(10)]
        worker,node,_,_=self.provider(owner,provider,blocks)
        worker.request(provider.public_key,[blocks[-1]['hash']])
        self.wait(lambda:provider._engine.has_proposal(blocks[-1]['hash']) and worker.snapshot()['recovered_blocks']==10)
        self.assertEqual(worker.snapshot()['recovered_blocks'],10);self.assertEqual(provider._profile.snapshot()['counts']['dag'],10)
        worker.close();provider=self.resume(provider)
        self.assertTrue(provider._engine.has_proposal(blocks[-1]['hash']));self.assertEqual(provider._engine._certified_order,())

    def test_corrupt_wire_digest_never_enters_journal_or_graph(self):
        owner,provider,receiver=self.network();block=self.block(owner,count=128)
        worker,node,_,chunk=self.provider(owner,provider,[block])
        def damaged(*args,**kwargs):
            result=chunk(*args,**kwargs);result['data']=bytes([result['data'][0]^1])+result['data'][1:];return result
        node.export_payload_chunk.side_effect=damaged
        worker.request(receiver.public_key,[block['hash']])
        self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_WIRE_DIGEST')
        self.assertFalse(provider._engine.has_proposal(block['hash']));self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_changed_chunk_size_offset_or_wire_identity_cannot_publish_partial_data(self):
        for field in ('total','offset','wire_hash'):
            owner,provider,receiver=self.network();block=self.block(owner,count=128)
            worker,node,_,chunk=self.provider(owner,provider,[block])
            def changed(*args,**kwargs):
                result=chunk(*args,**kwargs)
                if args[3]:result[field]='f'*64 if field=='wire_hash' else result[field]+1
                return result
            node.export_payload_chunk.side_effect=changed;worker.request(receiver.public_key,[block['hash']])
            self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_CHUNK_CHANGED')
            self.assertEqual(provider._profile.snapshot()['counts']['dag'],0);self.assertFalse(provider._engine.has_proposal(block['hash']))
            worker.close()

    def test_invalid_quorum_boundary_cannot_authorize_payloads(self):
        owner,provider,receiver=self.network();block=self.block(owner)
        worker,node,exchange,_=self.provider(owner,provider,[block])
        exchange.verifier.verify.side_effect=ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')
        worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:bool(worker.snapshot()['last_error']))
        node.export_payload_chunk.assert_not_called();self.assertFalse(provider._engine._recovery_hashes)
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_cancellation_before_admission_never_publishes_a_partial_record(self):
        owner,provider,receiver=self.network();block=self.block(owner,count=128)
        worker,node,_,chunk=self.provider(owner,provider,[block]);entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):entered.set();release.wait(3);return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=blocked;worker.request(receiver.public_key,[block['hash']])
        self.assertTrue(entered.wait(1));worker.request_stop();release.set();worker.close()
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0);self.assertFalse(provider._engine.has_proposal(block['hash']))

    def test_per_actor_queue_is_bounded_and_rotates_to_another_actor(self):
        owner,provider,receiver=self.network();worker,_,_,_=self.provider(owner,provider,[])
        entered=threading.Event();release=threading.Event();calls=[]
        def work(identifier):
            calls.append(identifier)
            if len(calls)==1:entered.set();release.wait(3)
            return False
        bad=[format(i+1,'064x') for i in range(16)];good=[format(i+100,'064x') for i in range(8)]
        with patch.object(worker,'_recover',side_effect=work):
            worker.request(owner.public_key,bad[:8]);self.assertTrue(entered.wait(1))
            worker.request(owner.public_key,bad[8:]);worker.request(receiver.public_key,good)
            self.assertLessEqual(worker.snapshot()['pending'],16);release.set();self.wait(lambda:good[0] in calls)
            self.assertLessEqual(calls.index(good[0]),2)
        worker.close()

    def test_cli_reports_bounded_payload_progress_without_untrusted_error_text(self):
        from backend.terminal_cli import foreground_summary
        payload={'enabled':True,'state':'IDLE','pending':0,'recovered_blocks':1,'recovered_bytes':2464461,'last_error':'private/path/or/untrusted/text'}
        result=foreground_summary('lan.resume',{'dag_proofs':{'payload_recovery':payload}})['proofs']['payload_recovery']
        self.assertEqual(result['recovered_blocks'],1);self.assertEqual(result['last_error'],'')
        for change in ({'pending':25},{'recovered_blocks':True},{'recovered_bytes':-1}):
            result=foreground_summary('lan.resume',{'dag_proofs':{'payload_recovery':{**payload,**change}}})['proofs']['payload_recovery']
            self.assertIsNone(result[next(iter(change))])

    def test_cli_partial_progress_is_bounded_and_never_becomes_verified_counts(self):
        from backend.terminal_cli import foreground_summary
        payload={'enabled':True,'state':'RECOVERING','phase':'DOWNLOADING','pending':1,'recovered_blocks':0,'recovered_bytes':0,
            'partial_records':1,'partial_downloaded_bytes':32768,'partial_reserved_bytes':2464461,'last_error':''}
        def summary(value):return foreground_summary('lan.resume',{'dag_proofs':{'payload_recovery':value}})['proofs']['payload_recovery']
        result=summary(payload)
        self.assertEqual(result['phase'],'DOWNLOADING');self.assertEqual(result['partial_downloaded_bytes'],32768)
        self.assertEqual(result['recovered_blocks'],0);self.assertEqual(result['recovered_bytes'],0)
        for change in ({'partial_records':9},{'partial_downloaded_bytes':True},{'partial_reserved_bytes':-1}):
            self.assertIsNone(summary({**payload,**change})[next(iter(change))])
        result=summary({**payload,'partial_downloaded_bytes':2464462})
        self.assertIsNone(result['partial_downloaded_bytes'])
        self.assertEqual(summary({**payload,'phase':'untrusted text'})['phase'],'UNOBSERVED')


class ResumablePayloadTests(unittest.TestCase):
    setUp=PayloadWorkerTests.setUp
    cleanup=PayloadWorkerTests.cleanup
    peer=PayloadWorkerTests.peer
    network=PayloadWorkerTests.network
    block=PayloadWorkerTests.block
    resume=PayloadWorkerTests.resume
    provider=PayloadWorkerTests.provider
    wait=PayloadWorkerTests.wait

    def large(self,count=512):
        owner,provider,receiver=self.network()
        for peer in (owner,provider,receiver):
            peer._wire_limit=2*1024*1024
            peer._engine.configure_lan_capacity(block_bytes=2*1024*1024,session_bytes=32*1024*1024)
        block=self.block(owner,count=count)
        worker,node,exchange,chunk=self.provider(owner,provider,[block])
        return owner,provider,receiver,block,worker,node,exchange,chunk

    def reserved(self,peer):
        account=peer.resources.governor()._memory_account
        with account['lock']:return account['reserved']

    def test_short_slices_continue_offsets_without_partial_journal_or_graph(self):
        owner,provider,receiver,block,worker,node,_,chunk=self.large()
        offsets=[];files=[]
        def slow(*args,**kwargs):
            offsets.append(args[3]);time.sleep(.012);return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=slow
        with patch.object(candidate,'JOB_SECONDS',.025):
            worker.request(receiver.public_key,[block['hash']])
            self.wait(lambda:worker.snapshot()['partial_downloaded_bytes']>0)
            self.assertFalse(provider._engine.has_proposal(block['hash']))
            self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
            self.assertEqual(worker.snapshot()['recovered_blocks'],0)
            with worker.lock:files=[row['file'] for row in worker.partials.values()]
            self.wait(lambda:provider._engine.has_proposal(block['hash']) and worker.snapshot()['recovered_blocks']==1)
        self.assertEqual(offsets,list(range(0,len(block['wire']),candidate.CHUNK_BYTES)))
        self.assertEqual(worker.snapshot()['partial_records'],0)
        self.assertTrue(files and all(file.closed for file in files));worker.close()
        self.assertEqual(self.reserved(provider),0)

    def test_completed_download_validation_has_fresh_cancellable_governed_work(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large(128)
        calls=[];original=provider._ingest_sdk_payload
        def delayed(raw,identifier,*,deadline,check=None):
            calls.append(deadline);time.sleep(.03);check()
            return original(raw,identifier,deadline=deadline,check=check)
        def slow(*args,**kwargs):time.sleep(.006);return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=slow
        with patch.object(candidate,'JOB_SECONDS',.004),patch.object(provider,'_ingest_sdk_payload',side_effect=delayed):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:provider._engine.has_proposal(block['hash']) and worker.snapshot()['recovered_blocks']==1)
        self.assertEqual(calls,[None]);self.assertEqual(worker.snapshot()['recovered_blocks'],1)

    def test_close_interrupts_validation_without_admission_and_releases_spool(self):
        _,provider,receiver,block,worker,_,_,_=self.large(128)
        entered=threading.Event()
        def validating(raw,identifier,*,deadline,check=None):
            entered.set()
            while True:check();time.sleep(.005)
        with patch.object(provider,'_ingest_sdk_payload',side_effect=validating):
            worker.request(receiver.public_key,[block['hash']]);self.assertTrue(entered.wait(2))
            with worker.lock:files=[row['file'] for row in worker.partials.values()]
            started=time.monotonic();worker.close();self.assertLess(time.monotonic()-started,1)
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        self.assertFalse(provider._engine.has_proposal(block['hash']))
        self.assertEqual(worker.snapshot()['partial_records'],0);self.assertEqual(self.reserved(provider),0)
        self.assertTrue(files and all(file.closed for file in files))

    def test_changed_descriptor_after_slice_cannot_mix_or_publish_bytes(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large()
        def changed(*args,**kwargs):
            time.sleep(.006);value=chunk(*args,**kwargs)
            if args[3]:value['wire_hash']='f'*64
            return value
        node.export_payload_chunk.side_effect=changed
        with patch.object(candidate,'JOB_SECONDS',.004):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_CHUNK_CHANGED')
        self.assertEqual(worker.snapshot()['partial_records'],0)
        self.assertFalse(provider._engine.has_proposal(block['hash']));self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_changed_chunk_error_is_published_after_confirmed_spool_cleanup(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large()
        entered=threading.Event();release=threading.Event();drop=worker._drop
        def changed(*args,**kwargs):
            value=chunk(*args,**kwargs)
            if args[3]:value['wire_hash']='f'*64
            return value
        def closing(identifier):
            if identifier==block['hash'] and not entered.is_set():entered.set();release.wait(3)
            return drop(identifier)
        node.export_payload_chunk.side_effect=changed
        with patch.object(worker,'_drop',side_effect=closing):
            try:
                worker.request(receiver.public_key,[block['hash']]);self.assertTrue(entered.wait(3))
                observed=worker.snapshot();self.assertEqual(observed['partial_records'],1)
                self.assertNotEqual(observed['last_error'],'GG_PAYLOAD_CHUNK_CHANGED')
                self.assertFalse(provider._engine.has_proposal(block['hash']))
            finally:release.set()
            self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_CHUNK_CHANGED' and worker.snapshot()['partial_records']==0)
        self.assertEqual(self.reserved(provider),0)

    def test_corrupt_provider_fallback_resumes_good_source_without_mixing_identity(self):
        _,provider,receiver,block,worker,node,exchange,chunk=self.large()
        first=[];second=[]
        def damaged(*args,**kwargs):
            first.append(args[3]);time.sleep(.005);value=chunk(*args,**kwargs)
            if args[3]==0:value['data']=bytes([value['data'][0]^1])+value['data'][1:]
            return value
        node.export_payload_chunk.side_effect=damaged
        other=SimpleNamespace(payload_reference=node.payload_reference,_check_proof_epoch=Mock())
        @contextmanager
        def reader(packet):
            def read(identifier,index,offset):
                second.append(offset);time.sleep(.005);return chunk(packet,identifier,index,offset)
            yield object(),read
        other.payload_reader=reader;exchange.sources=lambda:[node,other]
        with patch.object(candidate,'JOB_SECONDS',.012):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_WIRE_DIGEST')
            self.assertFalse(provider._engine.has_proposal(block['hash']))
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:provider._engine.has_proposal(block['hash']) and worker.snapshot()['recovered_blocks']==1)
        self.assertEqual(first,list(range(0,len(block['wire']),candidate.CHUNK_BYTES)))
        self.assertEqual(second,list(range(0,len(block['wire']),candidate.CHUNK_BYTES)))
        self.assertEqual(worker.snapshot()['recovered_blocks'],1)

    def test_changed_spooled_bytes_are_rehashed_before_any_admission(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large()
        entered=threading.Event();release=threading.Event()
        def paused(*args,**kwargs):
            if args[3]:entered.set();release.wait(2)
            return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=paused
        worker.request(receiver.public_key,[block['hash']]);self.assertTrue(entered.wait(2))
        with worker.lock:row=next(iter(worker.partials.values()));spool=row['file'];offset=row['offset']
        spool.seek(0);spool.write(b'!');spool.seek(offset);release.set()
        self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_WIRE_DIGEST')
        self.assertTrue(spool.closed);self.assertFalse(provider._engine.has_proposal(block['hash']))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_new_invalid_certificate_cannot_resume_old_partial_bytes(self):
        _,provider,receiver,block,worker,node,exchange,chunk=self.large()
        def slow(*args,**kwargs):time.sleep(.006);return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=slow
        with patch.object(candidate,'JOB_SECONDS',.004):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:worker.snapshot()['partial_downloaded_bytes']>0)
            exchange.verifier.verify.side_effect=ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')
            self.wait(lambda:worker.snapshot()['last_error']=='GG_CONSENSUS_CERTIFICATE_INVALID')
        self.assertFalse(provider._engine.has_proposal(block['hash']));self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        worker.close();self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)

    def test_disconnected_partial_expires_and_closes_without_false_history(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large()
        def disconnected(*args,**kwargs):
            if args[3]:raise OSError('owned unavailable fixture')
            return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=disconnected
        files=[]
        def captured_prefix():
            with worker.lock:
                current=[row['file'] for row in worker.partials.values() if row['offset']>0]
                if current:files[:]=current
                return bool(current)
        with patch.object(candidate,'PARTIAL_IDLE_SECONDS',.08):
            worker.request(receiver.public_key,[block['hash']]);self.wait(captured_prefix)
            self.wait(lambda:worker.snapshot()['partial_records']==0)
        self.assertTrue(files and all(file.closed for file in files));self.assertEqual(self.reserved(provider),0)
        self.assertFalse(provider._engine.has_proposal(block['hash']));self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_SDK_partial_close_keeps_row_and_credit_until_actual_handle_closes(self):
        _,provider,receiver,block,worker,node,_,_=self.large(128)
        row=worker._new_partial({'hash':block['hash'],'index':1},'owned close-order fixture',len(block['wire']),
            hashlib.sha256(block['wire']).hexdigest(),node)
        file=row['file'];entered=threading.Event();release=threading.Event();errors=[]
        class SlowClose:
            def close(self):entered.set();release.wait(2);return file.close()
        row['file']=SlowClose()
        def closing():
            try:worker._drop(block['hash'])
            except BaseException as error:errors.append(error)
        thread=threading.Thread(target=closing);thread.start()
        try:
            self.assertTrue(entered.wait(1));state=worker.snapshot()
            self.assertEqual(state['partial_records'],1);self.assertEqual(state['partial_reserved_bytes'],len(block['wire']))
            self.assertFalse(file.closed);self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertFalse(errors);self.assertTrue(file.closed)
        self.assertEqual(worker.snapshot()['partial_records'],0);self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)

    def test_SDK_failed_spool_close_retains_credit_and_retries_on_stop(self):
        _,provider,receiver,block,worker,node,_,_=self.large(128)
        row=worker._new_partial({'hash':block['hash'],'index':1},'owned failed-close fixture',len(block['wire']),
            hashlib.sha256(block['wire']).hexdigest(),node)
        file=row['file'];fail=[True]
        class FailedClose:
            def close(self):
                if fail[0]:raise OSError('owned local close failure')
                return file.close()
        row['file']=FailedClose()
        try:
            worker._drop(block['hash']);self.wait(lambda:not worker.worker.is_alive())
            self.assertEqual(worker.snapshot()['partial_records'],1)
            self.assertEqual(worker.snapshot()['partial_reserved_bytes'],len(block['wire']))
            self.assertEqual(worker.snapshot()['last_error'],'GG_PAYLOAD_SPOOL_CLOSE_FAILED')
            self.assertFalse(file.closed);self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        finally:fail[0]=False;worker.close()
        self.assertTrue(file.closed);self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)

    def test_one_signed_prefix_partial_is_shared_across_actor_queue_pressure(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large()
        entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):
            if args[3]:entered.set();release.wait(2)
            return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=blocked
        with patch.object(candidate,'PARTIAL_RECORDS',1),patch.object(candidate,'PARTIAL_BYTES',len(block['wire'])):
            worker.request(receiver.public_key,[block['hash']]);self.assertTrue(entered.wait(2))
            for _ in range(10):worker.request(provider.public_key,[block['hash']])
            state=worker.snapshot();self.assertEqual(state['partial_records'],1)
            self.assertEqual(state['partial_reserved_bytes'],len(block['wire']))
            self.assertLessEqual(state['pending'],24);release.set();self.wait(lambda:provider._engine.has_proposal(block['hash']))
        worker.close();self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)

    def test_fully_downloaded_record_waits_for_memory_credit_without_refetch(self):
        _,provider,receiver,block,worker,node,_,_=self.large()
        governor=provider.resources.governor();original=governor.reserve_memory
        @contextmanager
        def limited(size):
            if size>2*1024*1024:raise ValueError('GG_DAG_RESOURCE_MEMORY')
            with original(size):yield
        with patch.object(governor,'reserve_memory',side_effect=limited):
            worker.request(receiver.public_key,[block['hash']])
            self.wait(lambda:worker.snapshot()['last_error']=='GG_DAG_RESOURCE_MEMORY')
            self.assertEqual(worker.snapshot()['partial_downloaded_bytes'],len(block['wire']))
            self.assertEqual(worker.snapshot()['recovered_blocks'],0)
            self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
            calls=node.export_payload_chunk.call_count
        worker.request(receiver.public_key,[block['hash']])
        self.wait(lambda:worker.snapshot()['recovered_blocks']==1)
        self.assertEqual(node.export_payload_chunk.call_count,calls)
        worker.close();self.assertEqual(self.reserved(provider),0)

    def test_matching_wire_digest_and_block_signature_still_require_all_TX_signatures(self):
        from backend.gg_parallel_dag import _tree,pack,digest
        owner,provider,receiver=self.network();valid=self.block(owner,count=128)
        envelope=json.loads(valid['wire']);body=envelope['body']
        body['transactions'][60]['signature']='00'*64
        body['payload_root']=_tree(body['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        key=owner._engine._producer_keys[body['producer_index']]
        envelope['signature']=key.sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body)).hex()
        bad={'hash':digest(body,b'GG-DAG-BLOCK-v1\0'),'wire':pack(envelope)}
        worker,_,_,_=self.provider(owner,provider,[bad])
        worker.request(receiver.public_key,[bad['hash']]);self.wait(lambda:'SIGNATURE' in worker.snapshot()['last_error'])
        self.assertFalse(provider._engine.has_proposal(bad['hash']))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(worker.snapshot()['recovered_blocks'],0)
        self.assertEqual(worker.snapshot()['partial_records'],0)

    def test_actual_engine_governor_check_receives_recovery_cancellation(self):
        _,provider,receiver,block,worker,_,_,_=self.large(128)
        entered=threading.Event();release=threading.Event();original=provider._engine.admit_relayed
        def guarded(raw,index,*,check=None):
            self.assertIsNotNone(check)
            def wait_and_check():
                entered.set()
                while not release.wait(.005):check()
                check()
            return original(raw,index,check=wait_and_check)
        with patch.object(provider._engine,'admit_relayed',side_effect=guarded):
            worker.request(receiver.public_key,[block['hash']]);self.assertTrue(entered.wait(2))
            try:
                started=time.monotonic();worker.close();self.assertLess(time.monotonic()-started,1)
            finally:release.set()
        self.assertFalse(provider._engine.has_proposal(block['hash']))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(self.reserved(provider),0)

    def test_consensus_fault_during_partial_download_closes_untrusted_spool(self):
        _,provider,receiver,block,worker,node,exchange,chunk=self.large()
        entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):
            if args[3]:entered.set();release.wait(2)
            return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=blocked
        worker.request(receiver.public_key,[block['hash']]);self.assertTrue(entered.wait(2))
        with worker.lock:files=[row['file'] for row in worker.partials.values()]
        exchange._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE';release.set()
        self.wait(lambda:not worker.worker.is_alive())
        self.assertFalse(provider._engine.has_proposal(block['hash']))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)
        self.assertTrue(files and all(file.closed for file in files))

    def test_authenticated_bulk_GET_closes_transport_before_slow_full_validation(self):
        owner,_,receiver,block,worker,_,_,_=self.large()
        worker.close();original=receiver._ingest;deadline=time.monotonic()+1;calls=[]
        def slow(raw,peer,identifier=None,*,deadline=None):
            calls.append(deadline)
            with receiver._lock:self.assertFalse(receiver._sockets)
            self.assertGreaterEqual(self.reserved(receiver),2*len(raw))
            while time.monotonic()<transport_deadline+.01:time.sleep(.005)
            return original(raw,peer,identifier,deadline=deadline)
        transport_deadline=deadline
        with patch.object(receiver,'_ingest',side_effect=slow):
            result=receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]},deadline=deadline)
        self.assertEqual(result,1);self.assertEqual(calls,[None])
        self.assertTrue(receiver._engine.has_proposal(block['hash']))
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],1)
        self.assertEqual(self.reserved(receiver),0)

    def test_authenticated_bad_GET_END_does_not_publish_deferred_record(self):
        owner,_,receiver,block,worker,_,_,_=self.large()
        worker.close();original=owner._frame
        def bad_end(session,sequence,kind,payload):
            if kind=='END':payload={'records':2}
            return original(session,sequence,kind,payload)
        with patch.object(owner,'_frame',side_effect=bad_end):
            with self.assertRaisesRegex(ValueError,'GG_LAN_PAGE_END'):
                receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertFalse(receiver._engine.has_proposal(block['hash']))
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(self.reserved(receiver),0)

    def test_authenticated_GET_enforces_total_deferred_byte_credit_before_allocation(self):
        owner,_,receiver,block,worker,_,_,_=self.large()
        worker.close();namespace=receiver._pull.__func__.__globals__
        with patch.dict(namespace,MAX_GET_BUFFER_BYTES=len(block['wire'])-1):
            with self.assertRaisesRegex(ValueError,'GG_LAN_GET_CREDIT'):
                receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertFalse(receiver._engine.has_proposal(block['hash']))
        self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)
        self.assertEqual(self.reserved(receiver),0)

    def test_concurrent_LAN_admission_does_not_inflate_SDK_recovered_count(self):
        _,provider,receiver,block,worker,_,_,_=self.large(128)
        original=provider._engine.inspect_empty_proposal;once=[False]
        def raced(raw):
            result=original(raw)
            if not once[0]:
                once[0]=True
                provider._engine.admit_relayed(raw,provider._roster[receiver.public_key]['credit_index'])
            return result
        with patch.object(provider._engine,'inspect_empty_proposal',side_effect=raced):
            worker.request(receiver.public_key,[block['hash']])
            self.wait(lambda:provider._engine.has_proposal(block['hash']) and worker.snapshot()['partial_records']==0)
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],1)
        self.assertEqual(provider._engine.lan_evidence()['transactions'],128)
        self.assertEqual(worker.snapshot()['recovered_blocks'],0)
        self.assertEqual(worker.snapshot()['recovered_bytes'],0)

    def test_new_valid_selected_suffix_preserves_partial_prefix_download(self):
        from tests.test_producer_branches import ProducerBranchTests
        owner,provider,receiver,block,worker,node,_,chunk=self.large()
        later=self.block(owner,count=1);state,order,_=ProducerBranchTests.view(self,[block,later])
        original=node.payload_reference;advanced=[False];offsets=[]
        def reference(identifier):
            return {'certificate':{'state':deepcopy(state)},'order':deepcopy(order),'index':1} if advanced[0] else original(identifier)
        def slow(*args,**kwargs):offsets.append(args[3]);time.sleep(.006);return chunk(*args,**kwargs)
        node.payload_reference=reference;node.export_payload_chunk.side_effect=slow
        with patch.object(candidate,'JOB_SECONDS',.004):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:worker.snapshot()['partial_downloaded_bytes']>0)
            advanced[0]=True;self.wait(lambda:worker.snapshot()['recovered_blocks']==1)
        self.assertEqual(offsets,list(range(0,len(block['wire']),candidate.CHUNK_BYTES)))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],1)
        self.assertFalse(provider._engine.has_proposal(later['hash']))

    def test_local_spool_creation_failure_is_safe_and_does_not_accuse_source(self):
        _,provider,receiver,block,worker,_,_,_=self.large(128)
        with patch.object(candidate.tempfile,'TemporaryFile',side_effect=OSError('owned local disk fixture')):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_SPOOL_UNAVAILABLE')
        self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)
        self.assertFalse(worker.failed);self.assertFalse(provider._engine.has_proposal(block['hash']))
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_short_local_spool_write_cannot_publish_or_blacklist_valid_source(self):
        _,provider,receiver,block,worker,_,_,_=self.large(128)
        real=candidate.tempfile.TemporaryFile;files=[]
        class ShortWrite:
            def __init__(self):self.file=real(mode='w+b');files.append(self.file)
            def write(self,data):return len(data)-1
            def close(self):self.file.close()
        with patch.object(candidate.tempfile,'TemporaryFile',side_effect=lambda **kwargs:ShortWrite()):
            worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:worker.snapshot()['last_error']=='GG_PAYLOAD_SPOOL_WRITE')
        self.assertFalse(worker.failed);self.assertTrue(files and all(file.closed for file in files))
        self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)

    def test_local_spool_IO_failures_release_credit_without_accusing_source(self):
        for operation in ('write','seek','read'):
            with self.subTest(operation=operation):
                _,provider,receiver,block,worker,_,_,_=self.large(128)
                real=candidate.tempfile.TemporaryFile;files=[]
                class DiskError:
                    def __init__(self):self.file=real(mode='w+b');files.append(self.file)
                    def write(self,data):
                        if operation=='write':raise OSError(28,'owned disk fixture')
                        return self.file.write(data)
                    def seek(self,offset):
                        if operation=='seek':raise OSError(5,'owned disk fixture')
                        return self.file.seek(offset)
                    def read(self,size):
                        if operation=='read':raise OSError(5,'owned disk fixture')
                        return self.file.read(size)
                    def close(self):self.file.close()
                code='GG_PAYLOAD_SPOOL_WRITE' if operation=='write' else 'GG_PAYLOAD_SPOOL_READ'
                with patch.object(candidate.tempfile,'TemporaryFile',side_effect=lambda **kwargs:DiskError()):
                    worker.request(receiver.public_key,[block['hash']]);self.wait(lambda:bool(worker.snapshot()['last_error']))
                    self.assertEqual(worker.snapshot()['last_error'],code)
                    self.assertFalse(worker.failed)
                    self.assertTrue(files and all(file.closed for file in files))
                    self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)
                    self.assertFalse(provider._engine.has_proposal(block['hash']))
                    self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
                worker.close()

    def test_spool_close_failure_stops_recovery_and_reports_local_fault(self):
        _,provider,receiver,block,worker,node,_,chunk=self.large(128)
        entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):
            if args[3]:entered.set();release.wait(2)
            return chunk(*args,**kwargs)
        node.export_payload_chunk.side_effect=blocked;worker.request(receiver.public_key,[block['hash']])
        self.assertTrue(entered.wait(2))
        with worker.lock:row=next(iter(worker.partials.values()));real=row['file']
        class CloseFailure:
            @property
            def closed(self):return real.closed
            def close(self):real.close();raise OSError('owned cleanup fixture')
        row['file']=CloseFailure();worker.request_stop();release.set();worker.close()
        self.assertTrue(real.closed);self.assertFalse(worker.worker.is_alive())
        self.assertEqual(worker.snapshot()['partial_reserved_bytes'],0)
        self.assertEqual(worker.snapshot()['state'],'FAULT')
        self.assertEqual(worker.snapshot()['last_error'],'GG_PAYLOAD_SPOOL_CLOSE_FAILED')
        self.assertEqual(provider._profile.snapshot()['counts']['dag'],0)
