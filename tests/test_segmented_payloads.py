"""Source2 payload policy seams; SDK verification is explicitly mocked here.

Real signed originals/chunks and creator crypto are checked. Separate actual
SDK/LAN experiments cover selection, remote retrieval and native membership.
"""
import base64
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_segmented_payloads as payloads,gg_dag_segmented as segmented
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import pack
from backend.gg_segmented_proof_sync import validate_request


class SegmentedPayloadTests(unittest.TestCase):
    def setUp(self):
        self.keys=[Keypair.from_seed(hashlib.sha256(('public payload policy '+str(i)).encode()).digest()) for i in range(6)]
        self.source=segmented.make_source([key.pubkey().hex() for key in self.keys],list(range(6)),'b'*64,started_at_ns=1700000000000000000)
        self.anchor={'genesis':{'dag_segmented':self.source,'membership':{'validators':[{'body':{'owner_peer_key':'c'*64}}]}},'genesis_hash':'a'*64}
        self.body={'schema':'gg.parallel-dag.block.v1','chain_id':self.source['genesis']['chain_id'],'producer_index':0,
            'sequence':1,'rank':1,'parents':[self.source['genesis_hash']],'precheck_root':self.source['genesis']['precheck_root'],
            'transactions':[],'payload_root':'e'*64,'created_at_ns':1700000001000000000}
        self.raw=self.sign(self.body)
        self.leaf={'hash':hashlib.sha256(b'GG-DAG-BLOCK-v1\0'+pack(self.body)).hexdigest(),'index':1,'global_index':'1',
            'producer_index':0,'creator_key':self.source['genesis']['producers'][0],'sequence':'1','transactions':0}
        self.packet={'genesis_hash':'a'*64,'state':{'height':1,'state_root':'d'*64,'dag_segmented':{'epoch':'1'}},
            'signed_header':{'header':{'height':'2'}}}
        self.observation={'block':deepcopy(self.leaf),'order_page':None,'epoch':'1'}
        self.verify=patch.object(segmented,'verify_membership',return_value=self.observation).start();self.addCleanup(patch.stopall)

    def sign(self,body):return pack({'body':body,'signature':self.keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body)).hex()})

    def chunk(self,raw=None,offset=0,packet=None):
        raw=self.raw if raw is None else raw;packet=self.packet if packet is None else packet
        return {'schema':'gg.dag.payload-chunk.v1','genesis_hash':packet['genesis_hash'],'state_root':packet['state']['state_root'],
            'height':packet['state']['height'],'hash':self.leaf['hash'],'index':1,'offset':offset,'total':len(raw),
            'wire_hash':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(raw[offset:offset+payloads.CHUNK_BYTES]).decode()}

    def service(self):
        peer=SimpleNamespace(_cancel=threading.Event(),_profile=SimpleNamespace(_failed=False),_wire_limit=payloads.MAX_BYTES,
            resources=SimpleNamespace(governor=lambda:SimpleNamespace(reserve_memory=lambda size:nullcontext())),
            _resources_paused=lambda:False,_resource_check=lambda *args,**kwargs:None)
        exchange=SimpleNamespace(peer=peer,cancel=threading.Event(),_fault='',anchor=self.anchor,
            verifier=SimpleNamespace(binary=None,stamp=None),context=SimpleNamespace(check=lambda:None),
            _view={'certificate':self.packet,'order':[self.leaf],'payload_proofs':{self.leaf['hash']:self.packet}},
            _request=lambda kind,height,selector:{'kind':kind,'height':height,'selector':selector},
            _fetch=lambda owner,request,deadline:self.chunk(offset=payloads.parse_selector(request['selector'])[2]))
        service=payloads.SegmentedPayloads(exchange);self.addCleanup(service.close);return service

    def test_original_is_bound_to_independent_pinned_membership_and_creator_signature(self):
        row=payloads.authenticate_original(self.raw,self.packet,self.leaf,self.anchor)
        self.verify.assert_called_once_with(self.packet,self.anchor,binary=None,stamp=None)
        self.assertEqual(row['parent_hashes'],self.body['parents']);self.assertEqual(row['creator_key'],self.leaf['creator_key'])
        self.assertEqual(row['rank'],'1');self.assertTrue(row['payload_authenticated'])
        self.assertEqual(row['verification_scope'],'SDK_MEMBERSHIP_AND_CREATOR_SIGNED_BODY_NOT_LOCAL_EXECUTION_REPLAY')

    def test_failed_SDK_verification_cannot_be_replaced_by_caller_claim(self):
        self.verify.side_effect=ValueError('GG_ACTUAL_NATIVE_REJECTION')
        with self.assertRaises(ValueError):payloads.authenticate_original(self.raw,{**self.packet,'verified':True},self.leaf,self.anchor)

    def test_leaf_must_occur_in_verified_witness(self):
        self.verify.return_value={'block':None,'order_page':{'items':[]},'epoch':'1'}
        with self.assertRaisesRegex(ValueError,'MEMBERSHIP_REQUIRED'):payloads.authenticate_original(self.raw,self.packet,self.leaf,self.anchor)

    def test_changed_signed_parent_or_rank_is_not_published(self):
        for field,value in (('rank',2),('parents',['f'*64]),('chain_id','other chain'),('producer_index',True)):
            body={**self.body,field:value}
            with self.subTest(field=field):
                with self.assertRaises(ValueError):payloads.authenticate_original(self.sign(body),self.packet,self.leaf,self.anchor)

    def test_body_membership_does_not_skip_creator_signature(self):
        import json
        value=json.loads(self.raw);value['signature']='00'*64
        with self.assertRaises(ValueError):payloads.authenticate_original(pack(value),self.packet,self.leaf,self.anchor)

    def test_creator_key_must_match_source_not_only_witness(self):
        leaf={**self.leaf,'creator_key':'f'*64};self.verify.return_value={**self.observation,'block':leaf}
        with self.assertRaisesRegex(ValueError,'CREATOR'):payloads.authenticate_original(self.raw,self.packet,leaf,self.anchor)

    def test_noncanonical_and_duplicate_JSON_is_rejected(self):
        for raw in (self.raw+b' ',self.raw.replace(b'{',b'{"body":{},',1),b'{"body":true,"signature":false}'):
            with self.subTest(raw=raw[:32]):
                with self.assertRaises(ValueError):payloads.authenticate_original(raw,self.packet,self.leaf,self.anchor)

    def test_chunk_reconstructs_bounded_bytes_and_pins_exact_context(self):
        raw=b'x'*(payloads.CHUNK_BYTES+13)
        for offset in (0,payloads.CHUNK_BYTES):
            total,digest,data=payloads.decode_chunk(self.chunk(raw,offset),self.packet,self.leaf['hash'],1,offset)
            self.assertEqual(total,len(raw));self.assertEqual(digest,hashlib.sha256(raw).hexdigest());self.assertEqual(data,raw[offset:offset+payloads.CHUNK_BYTES])

    def test_bool_context_extra_claim_wrong_digest_shape_and_noncanonical_base64_rejected(self):
        valid=self.chunk()
        for field,value in (('height',True),('index',True),('offset',False),('total',True),('genesis_hash','f'*64),
                            ('state_root','f'*64),('hash','f'*64),('wire_hash','G'*64),('verified',True),('data',valid['data']+'=')):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):payloads.decode_chunk({**valid,field:value},self.packet,self.leaf['hash'],1,0)

    def test_typed_payload_request_rejects_unbounded_or_ambiguous_selectors(self):
        request={'kind':'payload','genesis_hash':'a'*64,'height':2,'selector':self.leaf['hash']+'/1/0'}
        self.assertEqual(validate_request(request),request)
        for selector in (True,{},self.leaf['hash']+'/01/0',self.leaf['hash']+'/1/1',self.leaf['hash']+'/4096/0',self.leaf['hash']+'/1/33554432'):
            with self.subTest(selector=selector):
                with self.assertRaises(ValueError):validate_request({**request,'selector':selector})

    def test_complete_download_publishes_only_after_full_original_authentication(self):
        service=self.service();self.assertEqual(service.snapshot()['blocks'],[]);service._step()
        result=service.snapshot();self.assertEqual(len(result['blocks']),1);self.assertEqual(result['reserved_disk_bytes'],0)
        self.assertEqual(result['blocks'][0]['missing_parent_hashes'],self.body['parents']);self.assertEqual(result['edges'],[])

    def test_legacy_whole_record_limit_does_not_disable_fragmented_source2_originals(self):
        service=self.service();service.peer._wire_limit=1;service._step()
        self.assertEqual(len(service.snapshot()['blocks']),1)

    def test_changed_spooled_bytes_cannot_publish_graph(self):
        service=self.service();spool=tempfile.TemporaryFile(mode='w+b');spool.write(self.raw[:-1]+b'x')
        partial={'file':spool,'total':len(self.raw),'wire_hash':hashlib.sha256(self.raw).hexdigest(),'offset':len(self.raw),
            'proof':self.packet,'leaf':self.leaf};service.partial=partial
        with self.assertRaisesRegex(ValueError,'WIRE_DIGEST'):service._finish(partial)
        self.assertEqual(service.snapshot()['blocks'],[]);service._drop();self.assertTrue(spool.closed)

    def test_window_uses_real_parent_links_and_exact_large_rank_labels(self):
        service=self.service();first=payloads.authenticate_original(self.raw,self.packet,self.leaf,self.anchor)
        first.update(rank='9007199254740993',height='9007199254740993',canonical_index='9007199254740993')
        second={**first,'hash':'f'*64,'rank':'9007199254740994','height':'9007199254740994','canonical_index':'9007199254740994','parent_hashes':[first['hash'],'e'*64]}
        service.rows[first['hash']]=first;service.rows[second['hash']]=second
        result=service.snapshot();self.assertEqual([row['layout_rank'] for row in result['blocks']],[0,1])
        self.assertEqual(result['blocks'][0]['rank'],'9007199254740993')
        self.assertEqual(result['edges'],[{'from':first['hash'],'to':second['hash']}])
        self.assertEqual(result['blocks'][1]['missing_parent_hashes'],['e'*64])

    def test_known_conflict_masks_previous_authenticated_window(self):
        service=self.service();service._step();service.exchange._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
        self.assertEqual(service.snapshot()['blocks'],[]);self.assertEqual(service.snapshot()['state'],'FAULT')

    def test_stopped_service_releases_spool_and_does_not_start_from_status(self):
        service=self.service();self.assertIsNone(service.worker.ident);service.snapshot();self.assertIsNone(service.worker.ident)
        service.close();self.assertEqual(service.snapshot()['state'],'STOPPED')

    def test_resumed_spool_uses_fresh_independent_proof_without_rewriting_original_certificate(self):
        service=self.service();spool=tempfile.TemporaryFile(mode='w+b');old=deepcopy(self.packet)
        service.partial={'file':spool,'total':len(self.raw),'wire_hash':hashlib.sha256(self.raw).hexdigest(),'offset':0,
            'proof':self.packet,'leaf':deepcopy(self.leaf)}
        fresh=deepcopy(self.packet);fresh['state'].update(height=2,state_root='f'*64);fresh['signed_header']['header']['height']='3'
        service.exchange._view['certificate']=fresh;service.exchange._view['payload_proofs'][self.leaf['hash']]=fresh
        service.exchange._fetch=lambda *args:self.chunk(packet=fresh)
        service._step()
        self.assertEqual(self.packet,old);self.assertEqual(service.snapshot()['blocks'][0]['certificate_height'],'3')
        self.verify.assert_called_once_with(fresh,self.anchor,binary=None,stamp=None)

    def test_short_disk_write_closes_untrusted_spool_before_retry_credit_is_reused(self):
        service=self.service();spool=Mock(closed=False);spool.write.return_value=0
        spool.close.side_effect=lambda:setattr(spool,'closed',True)
        with patch.object(payloads.tempfile,'TemporaryFile',return_value=spool):
            with self.assertRaisesRegex(ValueError,'SPOOL_WRITE'):service._step()
        self.assertTrue(spool.closed);self.assertIsNone(service.partial);self.assertEqual(service.snapshot()['reserved_disk_bytes'],0)


if __name__=='__main__':unittest.main()
