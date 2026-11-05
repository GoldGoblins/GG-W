"""Transport framing and durable certificate-journal boundaries.

Native cryptographic verification belongs to the real Go fixture suite. The
explicit stream double below models only accepted/rejected calls so these
tests can inspect storage ordering, cold replay and I/O failures without
pretending that a JSON record is a consensus certificate.
"""
from copy import deepcopy
import base64
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import gg_committee_history as history
from backend import gg_protocol_transport as transport
from backend import gg_process_termination as termination
from backend.gg_ed25519 import Keypair
from backend.gg_node_store import pack


def public_key(name):
    return Keypair.from_seed(hashlib.sha256(('PUBLIC transport history '+name).encode()).digest())


def framed(value):
    raw=pack(value)
    return struct.pack('>I',len(raw))+raw


class FakeProcess:
    def __init__(self,output=b''):
        self.stdin=io.BytesIO();self.stdout=io.BytesIO(output);self.returncode=None
    def poll(self):return self.returncode
    def kill(self):self.returncode=-9
    def wait(self,timeout=None):return self.returncode


class TransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        # Framing doubles have no OS handle. Only their declared fake lifecycle
        # is adapted; an actual Popen must still pass the production kernel wait.
        real_wait=termination.wait_process_terminal;real_terminal=termination.process_terminal
        def wait(child,timeout):
            return child.wait(timeout=timeout) if type(child) is FakeProcess else real_wait(child,timeout)
        def terminal(child):
            return child.poll() is not None if type(child) is FakeProcess else real_terminal(child)
        for name,adapter in (('wait_process_terminal',wait),('process_terminal',terminal)):
            selected=patch.object(termination,name,side_effect=adapter);selected.start();self.addCleanup(selected.stop)

    def test_only_literal_private_test_endpoints_are_accepted(self):
        server=public_key('server').pubkey().hex()
        for host in ('127.0.0.1','192.168.1.5','10.1.2.3','172.31.255.254','::1','fd00::5'):
            wanted={'host':host,'port':12345,'server_key':server}
            self.assertEqual(transport.endpoint(wanted),wanted)
        for host in ('localhost','8.8.8.8','0.0.0.0','100.64.0.1','169.254.0.1','192.0.2.1','::','2001:4860:4860::8888'):
            with self.subTest(host=host),self.assertRaises(ValueError):
                transport.endpoint({'host':host,'port':12345,'server_key':server})
        for port in (True,0,65536,'12345'):
            with self.subTest(port=port),self.assertRaises(ValueError):
                transport.endpoint({'host':'127.0.0.1','port':port,'server_key':server})
        with self.assertRaises(ValueError):
            transport.endpoint({'host':'127.0.0.1','port':12345,'server_key':server,'trusted':True})

    def bare_pipe(self,output):
        pipe=transport._Pipe.__new__(transport._Pipe)
        pipe.process=FakeProcess(output);pipe._closed=False;pipe.stamp=None
        pipe._write_lock=threading.RLock()
        pipe._timer=lambda seconds:SimpleNamespace(cancel=lambda:None)
        return pipe

    def test_pipe_checks_size_truncation_and_canonical_frames(self):
        value={'schema':transport.SCHEMA,'event':'RESPONSE','payload':{'count':'5000'}}
        self.assertEqual(self.bare_pipe(framed(value))._read(),value)
        malformed=[b'',b'\0\0\0',struct.pack('>I',0),struct.pack('>I',transport.MAX_FRAME+1),
                   struct.pack('>I',2)+b'{',framed({'schema':'foreign'}),
                   struct.pack('>I',len(b'{"schema":"x","schema":"y"}'))+b'{"schema":"x","schema":"y"}']
        for raw in malformed:
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):self.bare_pipe(raw)._read()
        pipe=self.bare_pipe(b'');pipe._send_raw(pack(value))
        self.assertEqual(pipe.process.stdin.getvalue(),framed(value))
        for raw in (b'',b'x'*(transport.MAX_FRAME+1),'not-bytes'):
            with self.assertRaisesRegex(ValueError,'FRAME_LIMIT'):pipe._send_raw(raw)

    def test_python_pipe_preserves_maximum_opaque_codec_request_for_native_transport(self):
        # The Go encrypted-peer fixture carries this same identity chunk.
        # Neither IPC layer treats this envelope as execution/authentication.
        raw=b'x'*(32*1024);digest=hashlib.sha256(raw).hexdigest()
        chunk={'schema':'gg.lossless-chunk-codec.v1','codec':'identity','hash':digest,'total':len(raw),'wire_sha256':digest,
               'index':0,'offset':0,'raw_size':len(raw),'raw_sha256':digest,'data':base64.b64encode(raw).decode('ascii')}
        payload={'method':'account_chunk_codec','document_hash':digest,'chunk':chunk}
        self.assertLess(len(pack(payload)),65536)
        value={'schema':transport.SCHEMA,'event':'REQUEST','genesis_hash':'b'*64,'id':2,'payload':payload}
        pipe=self.bare_pipe(framed(value));self.assertEqual(pipe._read(),value)
        pipe.send(value);self.assertEqual(pipe.process.stdin.getvalue(),framed(value))

    def test_client_binds_every_response_to_chain_request_and_known_shape(self):
        anchor='a'*64
        def client(response):
            result=transport.ProofTransportClient.__new__(transport.ProofTransportClient)
            result._control=threading.RLock();result._counter=0;result._last_request=0;result.last_contact=None
            result.anchor={'genesis_hash':anchor};result.sent=[];result.send=result.sent.append
            result._read=lambda **kwargs:deepcopy(response)
            return result
        good={'schema':transport.SCHEMA,'event':'RESPONSE','genesis_hash':anchor,'id':1,'payload':{'queue_only':True}}
        current=client(good)
        self.assertEqual(current.call({'method':'status'}),{'queue_only':True})
        self.assertEqual(current.sent[0]['id'],1)
        self.assertEqual(current.sent[0]['genesis_hash'],anchor)
        for changes in ({'id':2},{'genesis_hash':'b'*64},{'event':'REQUEST'},{'peer_key':'peer'}):
            wrong={**good,**changes}
            with self.subTest(changes=tuple(changes)),self.assertRaisesRegex(ValueError,'RELAY_RESPONSE'):
                client(wrong).call({'method':'status'})
        wrong=deepcopy(good);del wrong['payload']
        with self.assertRaisesRegex(ValueError,'RELAY_RESPONSE'):client(wrong).call({'method':'status'})
        leaked=deepcopy(good);leaked.pop('payload');leaked['error']='private information must not escape'
        with self.assertRaisesRegex(ValueError,'^GG_PROTOCOL_RELAY_REQUEST_FAILED$'):
            client(leaked).call({'method':'status'})

    def test_bootstrap_identity_and_private_material_use_only_child_stdin(self):
        key=public_key('client');expected=public_key('provider').pubkey().hex();anchor='c'*64
        pin={'genesis_hash':anchor,'genesis':{'protocol':{'environment':'TESTNET'}}}
        config={'mode':'CLIENT','host':'127.0.0.1','port':12345,'expected_key':expected,'allowed_keys':[]}
        good={'event':'READY','genesis_hash':anchor,'peer_key':expected,'schema':transport.SCHEMA}
        process=FakeProcess(framed(good))
        with patch.object(transport.protocol,'validate_pin',side_effect=deepcopy),patch.object(transport.native,'_environment',return_value={}),patch.object(transport.subprocess,'Popen',return_value=process) as popen:
            pipe=transport._Pipe(key,pin,config,binary=Path('PUBLIC-test-binary'),stamp=None)
            arguments=popen.call_args.args[0]
            self.assertEqual(arguments,['PUBLIC-test-binary','protocol-transport'])
            stdin=process.stdin.getvalue();length=struct.unpack('>I',stdin[:4])[0]
            self.assertEqual(length,len(stdin)-4)
            self.assertIn(bytes(key).hex().encode(),stdin[4:])
            self.assertNotIn(bytes(key).hex(),repr(popen.call_args))
            pipe.close();self.assertEqual(process.returncode,-9)
        for changes in ({'peer_key':key.pubkey().hex()},{'genesis_hash':'d'*64},{'event':'RESPONSE'},{'trusted':True}):
            rejected=FakeProcess(framed({**good,**changes}))
            with patch.object(transport.protocol,'validate_pin',side_effect=deepcopy),patch.object(transport.native,'_environment',return_value={}),patch.object(transport.subprocess,'Popen',return_value=rejected):
                with self.assertRaisesRegex(ValueError,'RELAY_IDENTITY'):
                    transport._Pipe(key,pin,config,binary=Path('PUBLIC-test-binary'),stamp=None)
            self.assertEqual(rejected.returncode,-9)


def storage_record(epoch,marker='accepted-by-stream-double'):
    return {'schema':'TEST-ONLY-STORAGE-RECORD-NOT-A-CERTIFICATE','test_marker':marker,
            'state':{'protocol':{'pending_committee':{'next':{'epoch':str(epoch)}}}}}


class FakeNativeStream:
    """Explicit acceptance stub; never a signature or quorum verifier."""
    instances=[]
    def __init__(self,pin,binary,stamp):
        self.epoch=0;self.closed=False;self.calls=[];self.process=SimpleNamespace(poll=lambda:-9 if self.closed else None)
        self.instances.append(self)
    def call(self,action,**values):
        if self.closed:raise ValueError('GG_TEST_STREAM_CLOSED')
        self.calls.append((action,deepcopy(values)))
        if action=='transition':
            value=values['transition'];epoch=int(value['state']['protocol']['pending_committee']['next']['epoch'])
            if value.get('test_marker')!='accepted-by-stream-double' or epoch!=self.epoch+1:
                raise ValueError('GG_TEST_NATIVE_REJECTED_RECORD')
            self.epoch=epoch
            return {'ok':True,'epoch':str(epoch)}
        if action=='verify':return {'ok':True,'epoch':str(self.epoch),'result':{'test_stream_epoch':self.epoch}}
        raise AssertionError(action)
    def close(self):self.closed=True


class CommitteeHistoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)/'history'
        self.root_patch=patch.object(history,'ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.stream_patch=patch.object(history,'_NativeStream',FakeNativeStream);self.stream_patch.start();self.addCleanup(self.stream_patch.stop)
        FakeNativeStream.instances=[];self.pin={'genesis_hash':'f'*64};self.opened=[]
        self.addCleanup(lambda:[value.close() for value in self.opened])

    def open(self,anchor=None):
        pin=deepcopy(self.pin)
        if anchor is not None:pin['genesis_hash']=anchor
        value=history.CommitteeHistory(pin,Path('PUBLIC-test-binary'),None);self.opened.append(value);return value

    def proof(self,epoch,pending=None):
        state={'committee':{'epoch':str(epoch)}}
        if pending is not None:state['pending_committee']={'next':{'epoch':str(pending)}}
        return {'state':{'protocol':state}}

    def test_durable_originals_replay_before_any_cold_trust_is_used(self):
        current=self.open();one,two=storage_record(1),storage_record(2)
        current.append(one);current.append(two)
        self.assertEqual(current.epoch,2);self.assertEqual(current.transition(1),one)
        self.assertEqual(current._path(2).read_bytes(),pack(two))
        calls=len(current._stream.calls);current.append(deepcopy(two))
        self.assertEqual(len(current._stream.calls),calls)
        with self.assertRaisesRegex(ValueError,'DIFFERENT_PREDECESSOR_CERTIFICATE'):
            current.append(storage_record(2,'different-original'))
        current.close();reopened=self.open()
        self.assertEqual(reopened.epoch,2)
        self.assertEqual([values['transition'] for action,values in reopened._stream.calls if action=='transition'],[one,two])
        self.assertEqual(reopened.verify(self.proof(2)),{'test_stream_epoch':2})

    def test_corruption_is_rejected_on_cold_replay(self):
        current=self.open();current.append(storage_record(1));path=current._path(1);current.close()
        path.write_bytes(pack(storage_record(1,'corrupted-original')))
        with self.assertRaisesRegex(ValueError,'GG_TEST_NATIVE_REJECTED_RECORD'):self.open()
        self.assertTrue(FakeNativeStream.instances[-1].closed)
        path.write_bytes(pack(storage_record(1))+b' ')
        with self.assertRaisesRegex(ValueError,'ENCODING'):self.open()
        self.assertTrue(FakeNativeStream.instances[-1].closed)

    def test_gap_cannot_establish_later_epoch_and_selector_is_exact(self):
        current=self.open();current._path(2).write_bytes(pack(storage_record(2)))
        self.assertEqual(current.refresh(),0)
        with self.assertRaisesRegex(ValueError,'GAP'):current.verify(self.proof(2))
        with self.assertRaisesRegex(ValueError,'GAP'):current.append(storage_record(2))
        for selector in (True,0,1,'1'):
            with self.subTest(selector=selector),self.assertRaises(ValueError):current.transition(selector)

    def test_failed_replace_closes_advanced_context_and_reopen_starts_at_disk(self):
        current=self.open();stream=current._stream
        with patch.object(history.os,'replace',side_effect=OSError('test-only disk failure')):
            with self.assertRaises(OSError):current.append(storage_record(1))
        self.assertEqual(stream.epoch,1);self.assertTrue(stream.closed);self.assertTrue(current.closed)
        self.assertFalse(current._path(1).exists())
        reopened=self.open();self.assertEqual(reopened.epoch,0)
        self.assertEqual(reopened._stream.epoch,0)
        reopened.append(storage_record(1));self.assertEqual(reopened.epoch,1)

    def test_post_replace_sync_failure_reconstructs_only_persisted_original(self):
        current=self.open()
        with patch.object(history,'sync_directory',side_effect=OSError('test-only sync failure')):
            with self.assertRaises(OSError):current.append(storage_record(1))
        self.assertTrue(current.closed);self.assertTrue(current._path(1).exists())
        reopened=self.open();self.assertEqual(reopened.epoch,1)
        self.assertEqual(reopened.transition(1),storage_record(1))

    def test_old_proofs_use_bounded_separate_context_and_pending_epoch(self):
        current=self.open()
        for epoch in (1,2,3):current.append(storage_record(epoch))
        live=current._stream
        self.assertEqual(current.verify(self.proof(0,pending=1)),{'test_stream_epoch':1})
        historical=current._historical
        self.assertEqual(current.verify(self.proof(2)),{'test_stream_epoch':2})
        self.assertIs(current._historical,historical)
        self.assertEqual(current.verify(self.proof(0)),{'test_stream_epoch':0})
        self.assertTrue(historical.closed);self.assertIsNot(current._historical,historical)
        self.assertEqual(current.verify(self.proof(3)),{'test_stream_epoch':3})
        self.assertIs(current._stream,live);self.assertEqual(live.epoch,3)
        self.assertEqual(current.epoch,3)


if __name__=='__main__':unittest.main()
