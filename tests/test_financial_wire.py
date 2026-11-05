"""Real financial signatures/wire bounds; no SDK finality is asserted here."""
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from backend import gg_financial_wire as wire,gg_financial_session as session,gg_financial_dag as financial
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import pack
from tests.test_lan_segmented_session import public_fixture


def public_financial_wire():
    fixture=public_fixture();bundle=session.make_bundle(fixture['owners'][0],fixture['invites'],fixture['membership'],label='Public wire test',network_nonce='b'*64)
    view=session.validate_bundle(bundle,bundle['body']['coordinator']);anchor=view['anchor'];source=view['source']
    accounts={}
    for index in range(4):
        key=Keypair.from_seed(hashlib.sha256(('public-segmented-session-fixture-account-'+str(index)).encode()).digest());accounts[key.pubkey().hex()]=key
    body={'amount_atomic':'3','chain_id':anchor['genesis']['chain_id'],'genesis_hash':anchor['genesis_hash'],'nonce':0,
          'recipient':anchor['genesis']['accounts'][1],'sender':anchor['genesis']['accounts'][0],'version':1}
    payment={'body':body,'signature':accounts[body['sender']].sign_message(pack(body)).hex()}
    producers={key.pubkey().hex():key for pair in fixture['producers'] for key in pair}
    index=source['allowed_producers'][0];signer=producers[source['producers'][index]]
    parent=hashlib.sha256(financial.DOMAIN+b'DAG-GENESIS\0'+pack({'anchor':anchor['genesis_hash'],'source':financial.source_hash(source)})).hexdigest()
    body={'created_at_ns':source['started_at_ns'],'epoch':'1','genesis_hash':anchor['genesis_hash'],'parents':[parent],
          'payment_root':wire.payment_root([payment]),'payments':[payment],'producer_index':index,'rank':'1',
          'schema':'gg.financial-dag.block.v1','sequence':'1','source_hash':financial.source_hash(source)}
    raw=pack({'body':body,'signature':signer.sign_message(financial.DOMAIN+b'DAG-BLOCK-SIGN\0'+pack(body)).hex()})
    return anchor,source,payment,raw,signer


class FinancialWireTests(unittest.TestCase):
    def test_actual_account_and_producer_signatures_bind_exact_canonical_input(self):
        anchor,source,payment,raw,_=public_financial_wire()
        self.assertEqual(wire.check_payment(payment,anchor['genesis'],anchor['genesis_hash']),payment)
        record=wire.decode_block(raw,source,anchor['genesis_hash'],1)
        self.assertEqual(record['payments'],1)
        self.assertEqual(record['hash'],hashlib.sha256(financial.DOMAIN+b'DAG-BLOCK\0'+raw).hexdigest())
        self.assertEqual(record['body']['payment_root'],wire.payment_root([payment]))
        changed=deepcopy(payment);changed['body']['amount_atomic']='4'
        with self.assertRaises(ValueError):wire.check_payment(changed,anchor['genesis'],anchor['genesis_hash'])
        with self.assertRaises(ValueError):wire.decode_block(raw,source,'0'*64,1)
        with self.assertRaises(ValueError):wire.decode_block(raw,source,anchor['genesis_hash'],2)

    def test_valid_producer_signature_is_not_an_account_authentication_or_execution_receipt(self):
        anchor,source,payment,raw,signer=public_financial_wire()
        body=wire.unpack(raw)['body'];body['payments'][0]['signature']='0'*128
        body['payment_root']=wire.payment_root(body['payments'])
        changed=pack({'body':body,'signature':signer.sign_message(financial.DOMAIN+b'DAG-BLOCK-SIGN\0'+pack(body)).hex()})
        record=wire.decode_block(changed,source,anchor['genesis_hash'],1)
        self.assertNotIn('SDK_selected',record)
        self.assertNotIn('payments_executed',record)
        with self.assertRaises(ValueError):wire.check_payment(record['body']['payments'][0],anchor['genesis'],anchor['genesis_hash'])

    def test_collection_amplification_is_rejected_before_typed_decode(self):
        anchor,source,_,_,_=public_financial_wire()
        cases=[b'{"body":{"payments":['+b'{},'*50000+b'{}]}}',b'['*13+b'0'+b']'*13,b'{"a":[] ,"b":[],"c":[]}']
        for raw in cases:
            with patch.object(wire,'unpack',side_effect=AssertionError('unbounded allocation reached decoder')):
                with self.assertRaises(ValueError):wire.decode_block(raw,source,anchor['genesis_hash'],1)

    def test_batch_candidate_is_sorted_and_does_not_claim_money_or_selection(self):
        anchor,source,_,raw,_=public_financial_wire()
        packet={**anchor,'state':{'financial_dag':{'epoch':'1','checkpoint':'0'}}}
        encoded,records=wire.batch(packet,[raw]);value=wire.unpack(encoded)
        self.assertEqual(value['sequence'],'1');self.assertEqual(value['source_hash'],financial.source_hash(source))
        self.assertEqual(len(records),1);self.assertNotIn('SDK_selected',value)
        with self.assertRaises(ValueError):wire.batch(packet,[raw,raw])
        with self.assertRaises(ValueError):wire.batch(packet,[])

    def test_signing_primitive_requires_real_certificate_verification_first(self):
        anchor,_,payment,_,signer=public_financial_wire()
        with patch.object(financial,'verify_producer',side_effect=ValueError('unverified context')) as verify:
            with self.assertRaises(ValueError):wire._signed_block({'verified':True},anchor,signer,[payment])
            verify.assert_called_once()

    def test_local_authenticated_inputs_are_immutable_and_bound_to_exact_genesis(self):
        anchor,_,payment,_,_=public_financial_wire();original=deepcopy(payment)
        values=wire.authenticate_payments([payment],anchor)
        payment['body']['amount_atomic']='99'
        self.assertEqual(values.rows(),[original])
        rows=values.rows();rows[0]['body']['nonce']=999
        self.assertEqual(values.rows(),[original])
        with self.assertRaises(AttributeError):values._raws=()
        changed=deepcopy(anchor);changed['genesis']['chain_id']='different'
        with self.assertRaisesRegex(ValueError,'INPUT_ANCHOR'):wire.authenticate_payments(values,changed)
        with self.assertRaises(ValueError):wire._AuthenticatedPayments(anchor['genesis_hash'],b'',())
        with self.assertRaises(ValueError):wire.authenticate_payments({'verified':True,'payments':[original]},anchor)
        with patch.object(wire,'check_payment',side_effect=AssertionError('local immutable inputs were reauthenticated')):
            self.assertIs(wire.authenticate_payments(values,anchor),values)

    def test_bounded_chain_signs_actual_parent_and_sequence_without_faking_an_SDK_proof(self):
        anchor,source,payment,raw,signer=public_financial_wire();old=wire.unpack(raw)['body']
        packet={**anchor,'financial_producer':{'producer_index':old['producer_index'],'epoch':'1','sequence':'1',
            'parent':old['parents'][0],'parent_rank':'0'}}
        values=wire.authenticate_payments([payment]*3,anchor)
        with patch.object(financial,'verify_producer',return_value={'SDK_policy_seam':True}):
            wires=wire._signed_chain(packet,anchor,signer,values,1,created_at_ns=int(source['started_at_ns']))
        self.assertEqual(len(wires),3);parent=old['parents'][0]
        for index,item in enumerate(wires):
            record=wire.decode_block(item,source,anchor['genesis_hash'],1)
            self.assertEqual(record['body']['parents'],[parent]);self.assertEqual(record['sequence'],index+1)
            self.assertEqual(record['rank'],index+1);self.assertEqual(record['body']['payments'],[payment])
            parent=record['hash']
        with patch.object(financial,'verify_producer',return_value={'SDK_policy_seam':True}):
            with self.assertRaisesRegex(ValueError,'PIPELINE_LIMIT'):wire._signed_chain(packet,anchor,signer,[payment]*9,1)
        self.assertNotIn('verified',wire.unpack(wires[-1]))

    def test_transport_prefix_preserves_originals_and_rejects_changed_source_or_lineage(self):
        anchor,source,payment,raw,signer=public_financial_wire();body=wire.unpack(raw)['body']
        packet={**anchor,'financial_producer':{'producer_index':body['producer_index'],'epoch':'1','sequence':'1',
            'parent':body['parents'][0],'parent_rank':'0'}}
        with patch.object(financial,'verify_producer',return_value={'SDK_policy_seam':True}):
            originals=wire._signed_chain(packet,anchor,signer,[payment]*3,1,created_at_ns=int(source['started_at_ns']))
        prefix=wire.encode_own_prefix(anchor,originals)
        self.assertEqual(wire.decode_own_prefix(prefix,anchor),originals)
        decoded=wire.unpack(prefix)
        self.assertNotIn('SDK_selected',decoded);self.assertNotIn('verified',decoded)
        for change in ({'genesis_hash':'0'*64},{'source_hash':'0'*64},{'producer_index':(body['producer_index']+1)%6},{'blocks':decoded['blocks'][::-1]}, {'verified':True}):
            with self.assertRaisesRegex(ValueError,'OWN_PREFIX_INVALID'):wire.decode_own_prefix(wire.pack({**decoded,**change}),anchor)


if __name__=='__main__':unittest.main()
