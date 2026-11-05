"""Closed-history adapter policy seams; real SDK/LAN gates are separate.

Public vectors contain actual native application states and valid test quorum
signatures. Mocked native results below exercise policy, not consensus crypto.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend import gg_consensus as native,gg_dag_segmented as segmented,gg_segmented_payloads as payloads
from backend.gg_segmented_proof_sync import validate_request
from tests import test_segmented_payloads as fixture


def vectors():return json.loads((Path(__file__).parent/'data/dag_segmented_closed_vectors.json').read_text(encoding='utf-8'))
def pin(packet):return {name:deepcopy(packet[name]) for name in ('genesis','genesis_hash')}
def reply(packet):return {'dag_segmented_closed_page_verified':True,'dag_segmented_closed_membership_scope':segmented.CLOSED_SCOPE,
    'dag_history_replay_verified':False,'dag_segmented_commitment':deepcopy(packet['state']['dag_segmented'])}


class ClosedMembershipAdapterTests(unittest.TestCase):
    def test_three_closed_epoch_vectors_invoke_owned_native_pin_and_preserve_their_real_epoch(self):
        data=vectors()
        for epoch,packet in data['packets'].items():
            with self.subTest(epoch=epoch),patch.object(native,'_verify_public',return_value=reply(packet)) as verify:
                anchor=pin(packet);result=segmented.verify_closed_membership(packet,anchor,binary=Path('owned-test-binary'),stamp=(1,2))
                verify.assert_called_once_with(packet,Path('owned-test-binary'),(1,2))
                self.assertEqual(result['epoch'],epoch);self.assertEqual(packet['state']['dag_segmented']['epoch'],'4')
                self.assertEqual(result['verification_scope'],segmented.CLOSED_SCOPE);self.assertFalse(result['history_replayed'])
                self.assertEqual(packet['state']['dag_segmented']['blocks'],data['expected']['global_blocks'])
                self.assertEqual(packet['state']['dag_segmented']['transactions'],data['expected']['transactions'])

    def test_wrong_scope_false_flag_or_replay_claim_is_rejected(self):
        packet=vectors()['packets']['1']
        for field,value in (('dag_segmented_closed_page_verified',False),('dag_segmented_closed_membership_scope','ACTIVE_ONLY'),
                            ('dag_history_replay_verified',True),('dag_segmented_commitment',{})):
            with self.subTest(field=field),patch.object(native,'_verify_public',return_value={**reply(packet),field:value}):
                with self.assertRaises(ValueError):segmented.verify_closed_membership(packet,pin(packet),binary=Path('owned-test-binary'))

    def test_caller_verified_claim_and_changed_anchor_cannot_bypass_native(self):
        packet=vectors()['packets']['1']
        with patch.object(native,'_verify_public') as verify:
            with self.assertRaises(ValueError):segmented.verify_closed_membership({**packet,'verified':True},pin(packet))
            wrong=pin(packet);wrong['genesis_hash']='f'*64
            with self.assertRaises(ValueError):segmented.verify_closed_membership(packet,wrong)
            verify.assert_not_called()
        with patch.object(native,'_verify_public',side_effect=ValueError('GG_ACTUAL_NATIVE_REJECTION')):
            with self.assertRaises(ValueError):segmented.verify_closed_membership(packet,pin(packet),binary=Path('owned-test-binary'))

    def test_truncated_cut_accounts_do_not_become_an_epoch_base(self):
        packet=vectors()['packets']['1'];packet['dag_segmented_closed_page']['cut']['accounts'].pop()
        with patch.object(native,'_verify_public',return_value=reply(packet)):
            with self.assertRaises(ValueError):segmented.verify_closed_membership(packet,pin(packet),binary=Path('owned-test-binary'))

    def test_typed_closed_selectors_are_bounded_canonical_and_distinguish_payloads(self):
        for kind,selector in (('closed','1/0'),('closed-payload','9223372036854775807/'+'a'*64+'/4095/32768')):
            request={'kind':kind,'genesis_hash':'a'*64,'height':2,'selector':selector};self.assertEqual(validate_request(request),request)
        for kind,selector in (('closed','0/0'),('closed','01/0'),('closed','1/1'),('closed','1/4096'),('closed',True),
                ('closed','9223372036854775808/0'),('closed-payload','1/'+'a'*64+'/1/1'),('closed-payload','1/'+'a'*64+'/true/0')):
            with self.subTest(selector=selector):
                with self.assertRaises(ValueError):validate_request({'kind':kind,'genesis_hash':'a'*64,'height':2,'selector':selector})


class ClosedOriginalRecoveryPolicyTests(unittest.TestCase):
    setUp=fixture.SegmentedPayloadTests.setUp
    sign=fixture.SegmentedPayloadTests.sign
    chunk=fixture.SegmentedPayloadTests.chunk
    service=fixture.SegmentedPayloadTests.service

    def test_closed_chunk_requires_exact_selected_epoch_and_fresh_SDK_context(self):
        chunk={**self.chunk(),'schema':'gg.dag.closed-payload-chunk.v1','epoch':'1'}
        total,_,data=payloads.decode_chunk(chunk,self.packet,self.leaf['hash'],1,0,epoch='1')
        self.assertEqual(total,len(self.raw));self.assertEqual(data,self.raw)
        for field,value in (('epoch','2'),('epoch',True),('height',2),('schema','gg.dag.payload-chunk.v1'),('verified',True)):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):payloads.decode_chunk({**chunk,field:value},self.packet,self.leaf['hash'],1,0,epoch='1')

    def test_original_closed_membership_uses_cut_epoch_and_actual_creator_signature(self):
        packet={**deepcopy(self.packet),'dag_segmented_closed_page':{'cut':{'before':{'epoch':'1'}}}}
        packet['state']['dag_segmented']['epoch']='4'
        observation={'epoch':'1','block':self.leaf,'order_page':None}
        with patch.object(segmented,'verify_closed_membership',return_value=observation) as verify:
            row=payloads.authenticate_original(self.raw,packet,self.leaf,self.anchor)
        self.assertEqual(row['epoch'],'1');self.assertEqual(row['parent_hashes'],self.body['parents'])
        verify.assert_called_once_with(packet,self.anchor,binary=None,stamp=None)
        self.verify.assert_not_called()

    def test_incomplete_active_original_continues_from_closed_archive_without_discard_or_proof_rewrite(self):
        service=self.service();spool=tempfile.TemporaryFile(mode='w+b');old=deepcopy(self.packet)
        service.partial={'file':spool,'total':len(self.raw),'wire_hash':hashlib.sha256(self.raw).hexdigest(),'offset':0,
            'proof':self.packet,'leaf':deepcopy(self.leaf)}
        fresh=deepcopy(self.packet);fresh['state'].update(height=4,state_root='f'*64);fresh['state']['dag_segmented'].update(epoch='2',closed_root='e'*64,blocks='1')
        fresh['signed_header']['header']['height']='5';service.exchange._certificate_info=(fresh,(5,'f'*64),0)
        service.exchange._view={'certificate':fresh,'order':[],'payload_proofs':{}}
        service._fill_cold=Mock()
        calls=[]
        def fetch(owner,request,deadline):
            calls.append(request);return {**self.chunk(packet=fresh),'schema':'gg.dag.closed-payload-chunk.v1','epoch':'1'}
        service.exchange._fetch=fetch;service._step()
        self.assertEqual(self.packet,old);self.assertTrue(spool.closed);self.assertEqual(len(service.snapshot()['blocks']),1)
        self.assertEqual(calls[0]['kind'],'closed-payload');self.assertTrue(calls[0]['selector'].startswith('1/'))
        self.assertEqual(calls[0]['height'],5);self.assertEqual(service.snapshot()['blocks'][0]['certificate_height'],'2')

    def test_new_query_certificate_does_not_relabel_unchanged_original_membership_height(self):
        service=self.service();fresh=deepcopy(self.packet);fresh['state'].update(height=4,state_root='f'*64);fresh['signed_header']['header']['height']='5'
        service.exchange._certificate_info=(fresh,(5,'f'*64),0);service.exchange._fetch=lambda *args:self.chunk(packet=fresh)
        service._step();self.assertEqual(service.snapshot()['blocks'][0]['certificate_height'],'2')
        self.verify.assert_called_once_with(self.packet,self.anchor,binary=None,stamp=None)

    def test_unavailable_cold_source_does_not_prevent_known_active_original(self):
        service=self.service();service.exchange._view['certificate']['state']['dag_segmented'].update(closed_root='e'*64,blocks='1')
        service._fill_cold=Mock(side_effect=ValueError('GG_PROOF_UNAVAILABLE'));service._step()
        self.assertEqual(len(service.snapshot()['blocks']),1)

    def test_cold_page_discovery_requests_the_tail_then_walks_back_without_whole_history_fetch(self):
        service=self.service();packet=deepcopy(self.packet);packet['state']['dag_segmented'].update(epoch='2',closed_root='e'*64,blocks='96')
        service.exchange._check_proven_base=Mock();service.exchange._key=lambda request:(request['kind'],request['height'],request['selector']);service.exchange._cache=Mock()
        requests=[]
        def fetch(owner,request,deadline):
            requests.append(request['selector']);_,start=payloads.parse_closed_selector(request['selector'])
            items=[{'leaf':{**self.leaf,'hash':format(index+1,'064x'),'global_index':str(index+1),'index':index+1}} for index in range(start,min(start+32,96))]
            return {**packet,'dag_segmented_closed_page':{'cut':{'before':{'epoch':'1','active':{'blocks':96}}},'start':start,'items':items}}
        service.exchange._fetch=fetch
        for _ in range(4):service._fill_cold(packet,0)
        self.assertEqual(requests,['1/0','1/64','1/32','1/0']);self.assertEqual(len(service.cold),96);self.assertEqual(service.cold_epoch,0)
        self.assertEqual(service.exchange._check_proven_base.call_count,4)


if __name__=='__main__':unittest.main()
