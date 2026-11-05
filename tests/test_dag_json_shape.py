"""Actual LAN admission rejects allocation bombs before generic JSON decoding."""
import tracemalloc
import unittest
from unittest.mock import patch

from backend.gg_dag_json import preflight_lan_block
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import (
    LAN_MAX_BLOCK_BYTES, LAN_MAX_TX_PER_BLOCK, ParallelDag, make_public_genesis,
)


class LanJSONAllocationTests(unittest.TestCase):
    def node(self):
        keys = [Keypair() for _ in range(6)]
        genesis = make_public_genesis([key.pubkey().hex() for key in keys], enable_dag_transactions=True)
        node = ParallelDag.from_public_genesis(genesis)
        node.attach_local_producers({0: keys[0], 1: keys[1]})
        node.configure_lan_capacity()
        self.addCleanup(node.stop)
        return node

    def test_real_signed_block_passes_preflight_and_normal_admission(self):
        source = self.node()
        replica = ParallelDag.from_public_genesis(source.export_public_genesis())
        replica.configure_lan_capacity()
        self.addCleanup(replica.stop)
        block = source.produce_lan_test_block(0, 3, LAN_MAX_BLOCK_BYTES)
        replica.admit_relayed(block['wire'], 0)
        self.assertEqual(replica.lan_evidence()['transactions'], 3)

    def test_collection_bombs_are_rejected_before_decoder_with_bounded_peak(self):
        node = self.node()
        cases = {
            'two_million_objects': b'{"body":{"transactions":[' + b'{},' * 1_999_999 + b'{}]}}',
            'half_million_fields': b'{' + b'"unrecognized":{},' * 499_999 + b'"last":{}}',
            'nested_arrays': b'[[[]]]',
            'deep_objects': b'{"a":' * 13 + b'0' + b'}' * 13,
        }
        for name, raw in cases.items():
            self.assertLess(len(raw), LAN_MAX_BLOCK_BYTES)
            with self.subTest(name=name), patch('backend.gg_parallel_dag.json.loads') as decoder:
                decoder.side_effect = AssertionError('generic decoder must not allocate this shape')
                tracemalloc.start()
                try:
                    with self.assertRaisesRegex(ValueError, 'GG_DAG_WIRE_JSON_SHAPE'):
                        node.inspect_empty_proposal(raw)
                    with self.assertRaisesRegex(ValueError, 'GG_DAG_WIRE_JSON_SHAPE'):
                        node.admit_relayed(raw, 0)
                    _, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
                decoder.assert_not_called()
                self.assertLess(peak, 1024 * 1024)
        self.assertEqual(node.lan_evidence()['transactions'], 0)

    def test_exact_array_limit_is_checked_without_decoding_or_crypto_shortcut(self):
        # A shape boundary only: these scalars are not signed valid transactions.
        raw = b'{"parents":[],"transactions":[' + b'0,' * (LAN_MAX_TX_PER_BLOCK - 1) + b'0]}'
        preflight_lan_block(raw)
        with self.assertRaisesRegex(ValueError, 'GG_DAG_WIRE_JSON_SHAPE'):
            preflight_lan_block(raw[:-2] + b',0]}')

    def test_string_contents_do_not_count_as_structure_but_escapes_are_impossible_wire(self):
        preflight_lan_block(b'{"value":"[{,:,:}]"}')
        for raw in (b'{"value":"\\u0061"}', '{"value":"ö"}'.encode()):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'GG_DAG_WIRE_JSON_SHAPE'):
                preflight_lan_block(raw)


if __name__ == '__main__':
    unittest.main()
