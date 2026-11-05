"""Financial source/pin shape; cryptography and outcomes use native/WASM tests."""
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from backend.gg_ed25519 import Keypair,SIGNATURE_PROFILE
from backend.gg_parallel_dag import pack
from backend.gg_dag_segmented import validate_native_pin
from backend import gg_financial_dag as financial


def public_financial_pin():
    keys=[Keypair.from_seed(hashlib.sha256(('public financial codec '+str(index)).encode()).digest()).pubkey().hex() for index in range(14)]
    genesis={'accounts':keys[:4],'chain_id':'ggnet:'+'a'*24,'decimals':6,'genesis_time_unix':1700000000,
             'schema':'gg.native.genesis.v5','supply_atomic':'1000000000000','symbol':'GG-NET-TEST','validators':keys[4:8]}
    genesis['financial_dag']={'allowed_producers':list(range(6)),'native_chain_id':genesis['chain_id'],'policy':financial.policy(),
        'producers':keys[8:],'schema':financial.SOURCE_SCHEMA,'signature_profile':SIGNATURE_PROFILE,'started_at_ns':'1700000000000000000'}
    return {'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()}


class FinancialDagCodecTests(unittest.TestCase):
    def test_explicit_financial_source_pins_and_copies_inputs(self):
        pin=public_financial_pin();owned=validate_native_pin(pin)
        self.assertEqual(owned,pin)
        pin['genesis']['financial_dag']['producers'][0]='0'*64
        self.assertNotEqual(owned,pin)
        self.assertRegex(financial.source_hash(owned['genesis']['financial_dag']),r'^[0-9a-f]{64}$')

    def test_policy_and_account_validator_producer_roles_cannot_be_substituted(self):
        pin=public_financial_pin();genesis=pin['genesis']
        for mutate in (
                lambda source:source['policy'].__setitem__('block_max_payments',50001),
                lambda source:source['policy'].__setitem__('active_max_blocks',4095.0),
                lambda source:source['producers'].__setitem__(0,genesis['accounts'][0]),
                lambda source:source['producers'].__setitem__(0,genesis['validators'][0]),
                lambda source:source['producers'].__setitem__(0,'0'*64),
                lambda source:source['allowed_producers'].__setitem__(0,True),
                lambda source:source.__setitem__('allowed_producers',[1,0]),
                lambda source:source.__setitem__('native_chain_id','ggnet:'+'b'*24),
                lambda source:source.__setitem__('signature_profile','unchecked'),
                lambda source:source.__setitem__('started_at_ns','01700000000000000000')):
            source=deepcopy(genesis['financial_dag']);mutate(source)
            with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_SOURCE_INVALID'):financial.validate_source(source,genesis)

    def test_legacy_genesis_cannot_silently_gain_financial_mode(self):
        pin=public_financial_pin()
        pin['genesis']['schema']='gg.native.genesis.v4'
        pin['genesis_hash']=hashlib.sha256(pack(pin['genesis'])).hexdigest()
        with self.assertRaisesRegex(ValueError,'GG_LIGHT_TRUST_INVALID'):validate_native_pin(pin)

    def test_mixed_modes_and_wrong_anchor_are_rejected(self):
        pin=public_financial_pin();pin['genesis']['dag_segmented']={}
        pin['genesis_hash']=hashlib.sha256(pack(pin['genesis'])).hexdigest()
        with self.assertRaises(ValueError):validate_native_pin(pin)
        pin=public_financial_pin();pin['genesis_hash']='0'*64
        with self.assertRaises(ValueError):validate_native_pin(pin)

    def test_packet_cannot_choose_its_own_trust_or_supply_a_verified_boolean(self):
        pin=public_financial_pin();packet={**deepcopy(pin),'financial_receipt':{},'verified':True}
        packet['genesis_hash']='0'*64
        with patch('backend.gg_consensus._verify_public',side_effect=AssertionError('untrusted packet reached verifier')):
            with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_RECEIPT_INVALID'):financial.verify_receipt(packet,pin)


if __name__=='__main__':unittest.main()
