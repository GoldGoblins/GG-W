"""Financial signed-session/domain tests; no running network or minted rewards."""
from copy import deepcopy
import unittest

from backend import gg_financial_session as financial,gg_financial_dag as source,gg_consensus_membership as member
from backend.gg_lan_dag import _signed,_BUNDLE
from tests.test_lan_segmented_session import public_fixture


def bundle(fixture,**changes):
    options={'label':'Public financial LAN','network_nonce':'b'*64};options.update(changes)
    return financial.make_bundle(fixture['owners'][0],fixture['invites'],fixture['membership'],**options)


class FinancialSessionTests(unittest.TestCase):
    def test_same_owned_inputs_and_reordered_invites_produce_same_pinned_genesis(self):
        fixture=public_fixture();first=bundle(fixture)
        self.assertEqual(first,bundle({**fixture,'invites':list(reversed(fixture['invites']))}))
        view=financial.validate_bundle(first,first['body']['coordinator'])
        self.assertEqual(view['anchor'],member.anchor_from_bundle(first,first['body']['coordinator']))
        self.assertEqual(view['anchor']['genesis']['schema'],'gg.native.genesis.v5')
        self.assertEqual(view['source']['schema'],source.LINEAGE_SOURCE_SCHEMA)
        self.assertEqual(view['source']['network_id'],view['network_id'])
        self.assertNotIn('dag_segmented',view['anchor']['genesis'])
        self.assertEqual(len(view['source']['allowed_producers']),4)

    def test_legacy_source_v2_stays_explicitly_readable_with_distinct_anchor(self):
        fixture=public_fixture();legacy=bundle(fixture,source_schema=source.SESSION_SOURCE_SCHEMA)
        view=financial.validate_bundle(legacy,legacy['body']['coordinator'])
        self.assertEqual(view['source']['schema'],source.SESSION_SOURCE_SCHEMA)
        self.assertEqual(view['source']['policy'],source.policy())
        self.assertEqual(financial.validate_bundle(deepcopy(legacy),legacy['body']['coordinator']),view)
        current=bundle(fixture)
        self.assertNotEqual(financial.validate_bundle(current,current['body']['coordinator'])['anchor']['genesis_hash'],view['anchor']['genesis_hash'])

    def test_nonce_label_time_role_and_committee_bind_distinct_native_anchors(self):
        fixture=public_fixture();first=bundle(fixture);coordinator=first['body']['coordinator']
        original=financial.validate_bundle(first,coordinator)
        variants=[bundle(fixture,network_nonce='c'*64),bundle(fixture,label='A distinct financial LAN'),
                  bundle(fixture,started_at_ns=1700000000000000001),bundle(public_fixture(roles=('producer','producer','producer'))),
                  bundle(public_fixture(p2p_ports=[22001,22002,22003,22004]))]
        for wire in variants:
            view=financial.validate_bundle(wire,coordinator)
            self.assertNotEqual(view['network_id'],original['network_id'])
            self.assertNotEqual(source.source_hash(view['source']),source.source_hash(original['source']))
            self.assertNotEqual(view['anchor']['genesis_hash'],original['anchor']['genesis_hash'])

    def test_resigned_source_substitution_cannot_change_derived_roles_or_network(self):
        fixture=public_fixture();first=bundle(fixture)
        for mutate in (
                lambda body:body['financial_source'].__setitem__('network_id','0'*64),
                lambda body:body['financial_source']['allowed_producers'].append(4),
                lambda body:body['financial_source']['producers'].reverse(),
                lambda body:body.__setitem__('network_nonce','c'*64),
                lambda body:body['financial_source']['policy'].__setitem__('block_max_payments',50001)):
            changed=deepcopy(first['body']);mutate(changed)
            resigned=_signed(fixture['owners'][0],_BUNDLE,changed)
            with self.assertRaisesRegex(ValueError,'GG_LAN_FINANCIAL_SESSION_INVALID'):
                financial.validate_bundle(resigned,first['body']['coordinator'])

    def test_unbound_source_v1_or_nonfinancial_mode_cannot_enter_financial_session(self):
        fixture=public_fixture();first=bundle(fixture)
        for mode in ('source','flag','mode'):
            body=deepcopy(first['body'])
            if mode=='source':body['financial_source']['schema']=source.SOURCE_SCHEMA;del body['financial_source']['network_id']
            elif mode=='flag':body['transactions_enabled']=False
            else:body['dag_test_mode']='PRODUCER_OWNED_NONFINANCIAL'
            with self.assertRaises(ValueError):financial.validate_bundle(_signed(fixture['owners'][0],_BUNDLE,body),first['body']['coordinator'])

    def test_unsigned_changed_coordinator_or_wrong_time_is_rejected(self):
        fixture=public_fixture();first=bundle(fixture);changed=deepcopy(first);changed['body']['label']='not signed'
        with self.assertRaises(ValueError):financial.validate_bundle(changed,first['body']['coordinator'])
        with self.assertRaises(ValueError):financial.validate_bundle(first,fixture['owners'][1].pubkey().hex())
        for started in (True,1700000000000000000.0,1699999999999999999,1700000005000000001):
            with self.assertRaises(ValueError):bundle(fixture,started_at_ns=started)


if __name__=='__main__':unittest.main()
