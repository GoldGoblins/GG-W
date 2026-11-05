"""Lossless transport tests; SDK/work lookups are explicit policy seams.

The LAN cases use real signed TCP and normal original admission. Account inbox
cases retain real public original signatures and private durable inbox writes;
the mocked SDK/work results make no execution or consensus-acceptance claim.
"""
import base64
from contextlib import contextmanager
from copy import deepcopy
import errno
import hashlib
import io
import struct
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import zlib

from backend import gg_lossless_wire as codec,gg_lan_dag as lan
from backend.gg_dag_wire import RecordAssembler,record_frames
from backend.gg_node_store import pack,unpack
from backend import gg_protocol_runtime as runtime
from tests import test_lan_get_resume as lan_fixture
from tests import test_protocol_integrated_profiles as account_fixture


class LosslessChunkTests(unittest.TestCase):
    def context(self,raw):
        digest=hashlib.sha256(raw).hexdigest()
        return digest,len(raw),digest,0

    def test_compressible_and_identity_chunks_roundtrip_exact_original_bytes(self):
        random=b''.join(hashlib.sha256(str(index).encode()).digest() for index in range(1024))
        for raw,expected in ((b'original canonical JSON bytes '*1170+b'x'*8,'gzip'),(random,'identity')):
            raw=raw[:codec.CHUNK_BYTES];context=self.context(raw);charged=[]
            value=codec.encode(raw,*context,charge=charged.append)
            self.assertEqual(value['codec'],expected)
            self.assertEqual(codec.decode(value,*context,charge=charged.append),raw)
            self.assertEqual(charged,[len(raw),len(raw)])
            self.assertLessEqual(len(base64.b64decode(value['data'])),codec.CHUNK_BYTES)

    def test_unknown_codec_and_every_context_binding_fail_before_returning_bytes(self):
        raw=b'x'*codec.CHUNK_BYTES;context=self.context(raw);value=codec.encode(raw,*context)
        changes=({'schema':'foreign'},{'codec':'zstd'},{'hash':'b'*64},{'total':len(raw)-1},
                 {'wire_sha256':'b'*64},{'index':True},{'offset':1},{'raw_size':len(raw)-1},
                 {'raw_sha256':'b'*64},{'data':value['data']+'\n'},{'extra':True})
        for change in changes:
            with self.subTest(change=tuple(change)),self.assertRaises(ValueError):
                codec.decode({**value,**change},*context)
        for selection in ({'schema':codec.SCHEMA,'codec':'unknown','chunk_bytes':codec.CHUNK_BYTES},
                          {**codec.select(codec.offer()),'chunk_bytes':True}):
            with self.assertRaisesRegex(ValueError,'SELECTION'):codec.selection(selection)

    def test_offer_rejects_equal_but_noninteger_chunk_size_and_nonexact_shape(self):
        offered=codec.offer()
        for changed in ({**offered,'chunk_bytes':32768.0},{**offered,'chunk_bytes':True},
                        {**offered,'codecs':('identity','gzip')},{**offered,'codecs':['identity','gzip',1]},
                        {**offered,'schema':'unknown'},{**offered,'extra':True},
                        {key:value for key,value in offered.items() if key!='chunk_bytes'}):
            with self.subTest(offer=changed),self.assertRaisesRegex(ValueError,'CODEC_OFFER'):codec.select(changed)
        self.assertEqual(codec.selection(codec.select(offered)),'gzip')

    def test_crc_truncation_members_trailing_and_expansion_bombs_fail_closed(self):
        raw=b'x'*codec.CHUNK_BYTES;context=self.context(raw);value=codec.encode(raw,*context)
        good=base64.b64decode(value['data']);bad_crc=bytearray(good);bad_crc[-8]^=1
        bomb=zlib.compressobj(1,zlib.DEFLATED,16+zlib.MAX_WBITS)
        oversized=bomb.compress(b'x'*(codec.CHUNK_BYTES+1))+bomb.flush()
        for malformed in (good[:-1],bytes(bad_crc),good+good,good+b'junk',oversized,b'x'*(codec.CHUNK_BYTES+1)):
            with self.subTest(size=len(malformed)),self.assertRaises(ValueError):
                codec.decode({**value,'data':base64.b64encode(malformed).decode()},*context)

    def test_checks_between_four_kib_steps_and_denies_credit_before_inflation(self):
        prefix=b''.join(hashlib.sha256(str(index).encode()).digest() for index in range(940))
        raw=prefix+b'x'*(codec.CHUNK_BYTES-len(prefix));context=self.context(raw);value=codec.encode(raw,*context)
        self.assertEqual(value['codec'],'gzip');checks=[]
        def stopped():
            checks.append(None)
            if len(checks)==4:raise ValueError('PUBLIC_CANCELLED')
        with self.assertRaisesRegex(ValueError,'PUBLIC_CANCELLED'):codec.decode(value,*context,check=stopped)
        self.assertEqual(len(checks),4)
        with patch.object(codec.zlib,'decompressobj',side_effect=AssertionError('inflater allocated before credit')):
            with self.assertRaisesRegex(ValueError,'PUBLIC_CREDIT'):
                codec.decode(value,*context,charge=lambda size:(_ for _ in ()).throw(ValueError('PUBLIC_CREDIT')))
        with self.assertRaisesRegex(ValueError,'DEADLINE'):codec.decode(value,*context,deadline=time.monotonic()-1)

    def test_legacy_forms_remain_exact_and_negotiated_assembler_requires_codec_parts(self):
        raw=b'x'*(codec.CHUNK_BYTES*2+7);record={'wire':raw,'hash':'a'*64,'admission_index':1}
        legacy=list(record_frames(record));encoded=list(record_frames(record,codec='gzip'))
        self.assertEqual(legacy[0],encoded[0]);self.assertEqual(legacy[-1],encoded[-1])
        self.assertEqual(set(legacy[1][1]),{'hash','offset','data'})
        assembler=RecordAssembler(codec='gzip');complete=None
        for kind,value in encoded:
            result=assembler.feed(kind,value)
            if result is not None:complete=result
        self.assertEqual(complete,record)
        for stream,selected in ((encoded,None),(legacy,'gzip')):
            assembler=RecordAssembler(codec=selected)
            with self.assertRaises(ValueError):
                for kind,value in stream:assembler.feed(kind,value)
            self.assertFalse(assembler.pending);self.assertEqual(assembler.buffered_bytes,0)

    def test_workspace_refusal_cannot_append_a_chunk_or_leak_partial_assembly(self):
        record={'wire':b'x'*100000,'hash':'a'*64,'admission_index':1};frames=list(record_frames(record,codec='gzip'))
        @contextmanager
        def refused():
            raise ValueError('PUBLIC_RAM_LIMIT')
            yield
        assembler=RecordAssembler(codec='gzip',workspace=refused);assembler.feed(*frames[0])
        with self.assertRaisesRegex(ValueError,'PUBLIC_RAM_LIMIT'):assembler.feed(*frames[1])
        self.assertFalse(assembler.pending);self.assertEqual(assembler.buffered_bytes,0)

    def test_negotiation_never_retries_an_error_after_original_transfer_begins(self):
        attempts=[];deadline=time.monotonic()+2
        @contextmanager
        def connection(*args,**kwargs):
            attempts.append(kwargs['deadline']);yield object()
        peer=SimpleNamespace(_connection=connection,_client_auth=lambda *args,**kwargs:'PUBLIC session',
            _frame=lambda *args:{},_credit=lambda *args:None,_read=lambda *args,**kwargs:({},1),
            _check_frame=lambda *args:{'kind':codec.ACK,'payload':codec.select(codec.offer())})
        with patch.object(lan,'_send',return_value=1):
            with self.assertRaisesRegex(ValueError,'PUBLIC_CORRUPT_DATA'):
                with codec.lan_connection(peer,'a'*64,deadline):raise ValueError('PUBLIC_CORRUPT_DATA')
        self.assertEqual(attempts,[deadline])

    def test_partial_ack_header_body_eof_and_reset_never_trigger_legacy_authentication(self):
        class PartialSocket:
            def __init__(self,prefix,reset):self.data=io.BytesIO(prefix);self.reset=reset
            def settimeout(self,seconds):pass
            def recv(self,size):
                part=self.data.read(size)
                if part:return part
                if self.reset:raise OSError(errno.ECONNRESET,'PUBLIC partial ACK reset')
                return b''
        body=b'{"PUBLIC":"partial acknowledgement"}';header=struct.pack('!I',len(body))
        for prefix in (header[:1],header[:3],header,header+body[:5]):
            for reset in (False,True):
                with self.subTest(prefix=len(prefix),reset=reset):
                    attempts=[];received=[];sock=PartialSocket(prefix,reset);deadline=time.monotonic()+2
                    @contextmanager
                    def connection(*args,**kwargs):attempts.append(kwargs['deadline']);yield sock
                    def read(socket,limit,**kwargs):
                        def account(size):received.append(size);kwargs['on_bytes'](size)
                        return lan._receive(socket,limit,account=account,deadline=kwargs['deadline'])
                    peer=SimpleNamespace(_connection=connection,_client_auth=Mock(return_value='PUBLIC session'),
                        _frame=lambda *args:{},_credit=lambda *args:None,_read=read,_pace_connection=Mock(),
                        _check_frame=Mock(side_effect=AssertionError('partial ACK decoded')))
                    with patch.object(lan,'_send',return_value=1),self.assertRaises((ValueError,OSError)):
                        with codec.lan_connection(peer,'a'*64,deadline):self.fail('partial ACK yielded data connection')
                    self.assertEqual(sum(received),len(prefix));self.assertEqual(attempts,[deadline])
                    peer._client_auth.assert_called_once();peer._pace_connection.assert_not_called()

    def test_zero_byte_old_peer_eof_or_reset_alone_can_select_legacy_with_same_deadline(self):
        for reset in (False,True):
            with self.subTest(reset=reset):
                attempts=[];deadline=time.monotonic()+2
                @contextmanager
                def connection(*args,**kwargs):attempts.append(kwargs['deadline']);yield object()
                def old_peer(*args,**kwargs):
                    self.assertIn('on_bytes',kwargs)
                    if reset:raise OSError(errno.ECONNRESET,'PUBLIC empty old-peer reset')
                    raise ValueError('GG_LAN_EOF')
                peer=SimpleNamespace(_connection=connection,_client_auth=Mock(return_value='PUBLIC session'),
                    _frame=lambda *args:{},_credit=lambda *args:None,_read=old_peer,_pace_connection=Mock())
                with patch.object(lan,'_send',return_value=1):
                    with codec.lan_connection(peer,'a'*64,deadline) as (_,_,selected,base):
                        self.assertIsNone(selected);self.assertEqual(base,0)
                self.assertEqual(attempts,[deadline,deadline]);self.assertEqual(peer._client_auth.call_count,2)
                peer._pace_connection.assert_called_once()


class LosslessLanTests(unittest.TestCase):
    setUp=lan_fixture.LanGetResumeTests.setUp
    cleanup=lan_fixture.LanGetResumeTests.cleanup
    peer=lan_fixture.LanGetResumeTests.peer
    network=lan_fixture.LanGetResumeTests.network
    block=lan_fixture.LanGetResumeTests.block
    large=lan_fixture.LanGetResumeTests.large

    def test_default_auto_negotiates_signed_codec_and_admits_exact_original(self):
        owner,receiver,_,block=self.large();frames=[];original=owner._frame;charges=[]
        charge=receiver._account_codec_raw
        def sent(session,sequence,kind,payload):
            frames.append((kind,deepcopy(payload)));return original(session,sequence,kind,payload)
        def charged(peer,size):charges.append(size);return charge(peer,size)
        with patch.object(owner,'_frame',side_effect=sent),patch.object(receiver,'_account_codec_raw',side_effect=charged):
            self.assertEqual(receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]}),1)
        self.assertEqual(frames[0][0],codec.ACK)
        parts=[value for kind,value in frames if kind=='DATA_PART']
        self.assertTrue(parts);self.assertTrue(all(value['schema']==codec.SCHEMA for value in parts))
        self.assertEqual(sum(charges),len(block['wire']))
        self.assertEqual(receiver._profile.read_dag(block['hash']),block['wire'])
        self.assertEqual(receiver.snapshot()['canonical_finalized'],0)

    def test_authenticated_old_peer_falls_back_before_any_original_and_keeps_v1_parts(self):
        owner,receiver,_,block=self.large();owner._lossless_wire=False;parts=[];original=owner._frame
        def sent(session,sequence,kind,payload):
            if kind=='DATA_PART':parts.append(deepcopy(payload))
            return original(session,sequence,kind,payload)
        with patch.object(owner,'_frame',side_effect=sent):
            self.assertEqual(receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]}),1)
        self.assertTrue(parts);self.assertTrue(all(set(value)=={'hash','offset','data'} for value in parts))
        self.assertEqual(receiver._profile.read_dag(block['hash']),block['wire'])

    def test_bad_signed_selection_never_downgrades_or_ingests(self):
        owner,receiver,_,block=self.large();original=owner._frame
        def changed(session,sequence,kind,payload):
            if kind==codec.ACK:payload={**payload,'codec':'unknown'}
            return original(session,sequence,kind,payload)
        with patch.object(owner,'_frame',side_effect=changed),patch.object(receiver,'_ingest') as ingest:
            with self.assertRaisesRegex(ValueError,'SELECTION'):receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        ingest.assert_not_called();self.assertEqual(receiver._profile.snapshot()['counts']['dag'],0)

    def test_bad_codec_payload_does_not_reauthenticate_or_fall_back(self):
        owner,receiver,_,block=self.large();original=owner._frame;auth=receiver._client_auth;attempts=[]
        def changed(session,sequence,kind,payload):
            if kind=='DATA_PART':payload={**payload,'codec':'unknown'}
            return original(session,sequence,kind,payload)
        def authenticate(*args,**kwargs):attempts.append(None);return auth(*args,**kwargs)
        with patch.object(owner,'_frame',side_effect=changed),patch.object(receiver,'_client_auth',side_effect=authenticate),patch.object(receiver,'_ingest') as ingest:
            with self.assertRaisesRegex(ValueError,'CODEC_CHUNK'):receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(len(attempts),1);ingest.assert_not_called()


class LosslessAccountRelayTests(unittest.TestCase):
    setUp=account_fixture.ProtocolProfileInboxTests.setUp
    close_profiles=account_fixture.ProtocolProfileInboxTests.close_profiles
    book=account_fixture.ProtocolProfileInboxTests.book
    packet=account_fixture.ProtocolProfileInboxTests.packet

    def endpoints(self,raw,*,legacy=False,mutate=None):
        from tests.test_protocol_codec_resources import attest_codec_fixture
        server=runtime.ProtocolRuntime();client=runtime.ProtocolRuntime();session=object();peer='a'*64
        packet=self.packet();server._inbox=self.book();server.owner=self.owner;server.producer=Mock()
        server._relay_policy={'accept_accounts':True,'producer_slot':0};server._relay_session=session
        server._schedule_inbox=Mock()
        server_node=SimpleNamespace(anchor=self.pin,node_key=account_fixture.public_key(301).pubkey().hex(),binary=None,_stamp=None,
                                    certified_state=lambda:deepcopy(packet),selected_proof=lambda *args:deepcopy(packet))
        server.node=server_node
        # Explicit unit-only native ACK/kernel seam; real native acceptance
        # remains the separate protected SERVER restore/relay fixture.
        attest_codec_fixture(server,server_node,owner=self.owner,session=session)
        requests=[]
        def call(value):
            requests.append(deepcopy(value))
            if legacy and value['method']=='account_codec':raise ValueError('GG_PROTOCOL_RELAY_METHOD')
            if mutate is not None:value=mutate(deepcopy(value))
            return server._relay_account_request(server_node,peer,value,session)
        node=SimpleNamespace(role='LIGHT',anchor=self.pin,endpoint={'server_key':server_node.node_key},binary=None,_stamp=None,
            _check_start=lambda:None,_call=call,selected_proof=lambda *args:deepcopy(packet),
            profile=SimpleNamespace(native_node_signer=lambda:account_fixture.public_key(400)))
        client.node=node;attest_codec_fixture(client,node,client=True,owner=self.owner)
        account=SimpleNamespace(name='PUBLIC lossless account',_lock=threading.RLock(),pending=lambda proof:raw,
                                public_address=lambda:account_fixture.public_key(0).pubkey().hex())
        return server,client,account,requests

    def transfer(self,client,account):
        with patch.object(runtime.inbox,'admission_job',return_value={'PUBLIC':'work policy seam'}),\
             patch.object(runtime.economy,'mine_work',return_value=({'PUBLIC':'work policy seam'},0,0)),\
             patch.object(runtime.economy,'verify_work'),\
             patch.object(runtime.financial,'verify_account',side_effect=account_fixture.account_policy):
            return client._submit_light_account(account)

    def test_auto_codec_and_legacy_both_retain_real_signed_originals_before_ack(self):
        for legacy in (False,True):
            with self.subTest(legacy=legacy):
                raw=account_fixture.originals(self.pin,start=0,count=101 if legacy else 100)
                server,client,account,requests=self.endpoints(raw,legacy=legacy)
                result=self.transfer(client,account)
                self.assertEqual(result['state'],'DURABLE_RECEIVER_ORIGINALS')
                self.assertFalse(result['payments_executed_asserted'])
                self.assertEqual(server._inbox.entries[hashlib.sha256(raw).hexdigest()].raw,raw)
                method='account_chunk' if legacy else 'account_chunk_codec'
                parts=[value for value in requests if value['method']==method]
                self.assertTrue(parts)
                self.assertTrue(all(len(pack(value))<=65536 for value in requests))
                if not legacy:self.assertTrue(all(value['chunk']['schema']==codec.SCHEMA for value in parts))

    def test_original_account_signature_is_still_checked_after_lossless_transport(self):
        value=unpack(account_fixture.originals(self.pin,count=100));value['payments'][0]['body']['amount_atomic']='2';raw=pack(value)
        server,client,account,_=self.endpoints(raw)
        with self.assertRaisesRegex(ValueError,'PAYMENT_DOCUMENT_INVALID'):self.transfer(client,account)
        self.assertEqual(server._inbox.snapshot()['retained_documents'],0)

    def test_corrupt_codec_never_acknowledges_or_silently_retries_legacy(self):
        raw=account_fixture.originals(self.pin,count=100)
        def corrupt(value):
            if value['method']=='account_chunk_codec':value['chunk']['codec']='unknown'
            return value
        server,client,account,requests=self.endpoints(raw,mutate=corrupt)
        with self.assertRaisesRegex(ValueError,'CODEC_CHUNK'):self.transfer(client,account)
        self.assertFalse(any(value['method'] in ('account_chunk','account_finish') for value in requests))
        self.assertEqual(server._inbox.snapshot()['retained_documents'],0)
        self.assertTrue(all(len(upload['data'])==0 for upload in server._uploads.values()))

    def test_raw_and_encoded_credit_denial_precedes_codec_append_and_ack(self):
        raw=account_fixture.originals(self.pin,count=100)
        server,client,account,requests=self.endpoints(raw);calls=[]
        def denied(actor,size,work):calls.append((size,work));return False
        server._codec_server.budget.take=denied
        with self.assertRaisesRegex(ValueError,'UPLOAD_LIMIT'):self.transfer(client,account)
        self.assertTrue(calls);self.assertGreater(calls[0][0],codec.CHUNK_BYTES)
        self.assertFalse(any(value['method']=='account_finish' for value in requests))
        self.assertTrue(all(len(upload['data'])==0 for upload in server._uploads.values()))

    def test_account_workspace_wait_obeys_cancellation_and_releases_own_slot(self):
        from tests.test_protocol_codec_resources import attest_codec_fixture
        controller=runtime.ProtocolRuntime();node=SimpleNamespace(role='LIGHT')
        binding=attest_codec_fixture(controller,node,client=True)
        binding.workspaces.acquire();binding.workspaces.acquire()
        try:
            with self.assertRaisesRegex(ValueError,'PUBLIC_CANCELLED'):
                with controller._codec_workspace(lambda:(_ for _ in ()).throw(ValueError('PUBLIC_CANCELLED')),time.monotonic()+1,binding=binding):pass
        finally:binding.workspaces.release();binding.workspaces.release()
        with self.assertRaisesRegex(ValueError,'PUBLIC_FAILURE'):
            with controller._codec_workspace(lambda:None,time.monotonic()+1,binding=binding):raise ValueError('PUBLIC_FAILURE')
        self.assertTrue(binding.workspaces.acquire(blocking=False));self.assertTrue(binding.workspaces.acquire(blocking=False))
        binding.workspaces.release();binding.workspaces.release()
