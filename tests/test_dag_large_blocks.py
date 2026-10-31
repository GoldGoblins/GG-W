"""Real larger signed payloads; no live app, physical host or finality claim."""
import threading
import time
import unittest

from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag, make_public_genesis, LAN_MAX_BLOCK_BYTES
from tests import test_lan_dag_transactions_v2 as legacy


class LargeCapacitySameSemanticsTests(legacy.ProducerOwnedDagTests):
    def setUp(self):
        super().setUp()
        for node in self.nodes:
            node.configure_lan_capacity()


class LargePayloadTests(unittest.TestCase):
    def nodes(self):
        keys = [Keypair() for _ in range(6)]
        genesis = make_public_genesis([key.pubkey().hex() for key in keys], enable_dag_transactions=True)
        nodes = [ParallelDag.from_public_genesis(genesis) for _ in range(3)]
        for index, node in enumerate(nodes):
            node.attach_local_producers({p: keys[p] for p in (index*2, index*2+1)})
            node.configure_lan_capacity()
            self.addCleanup(node.stop)
        return nodes

    def test_5000_real_transactions_keep_identical_verified_preview(self):
        nodes = self.nodes()
        size = nodes[0].preflight_lan_test_block(50000, LAN_MAX_BLOCK_BYTES)
        self.assertGreater(size, 262144)
        block = nodes[0].produce_lan_test_block(0, 5000, LAN_MAX_BLOCK_BYTES)
        self.assertGreater(len(block['wire']), 262144)
        for node in nodes[1:]:
            node.admit_relayed(block['wire'], 0)
            node.reconcile()
        evidence = [node.lan_evidence() for node in nodes]
        self.assertTrue(all(row['transactions'] == 5000 for row in evidence))
        for field in ('blockset_digest', 'state_root', 'producer_blocks', 'producer_transactions'):
            self.assertTrue(all(row[field] == evidence[0][field] for row in evidence), field)
        for node in nodes:
            self.assertGreaterEqual(node._stats['signature_checks'], 5001)
            self.assertEqual(node.snapshot()['canonical_finalized'], 0)

    def test_large_signing_keeps_status_responsive_and_capacity_changes_atomic(self):
        node = self.nodes()[0]
        entered = threading.Event()
        release = threading.Event()
        errors = []
        calls = [0]
        def check():
            calls[0] += 1
            if calls[0] == 5:
                entered.set()
                release.wait(2)
        def produce():
            try:
                node.produce_lan_test_block(0, 32, LAN_MAX_BLOCK_BYTES, check=check)
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=produce)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            began = time.monotonic()
            node.snapshot()
            self.assertLess(time.monotonic()-began, .2)
            with self.assertRaisesRegex(ValueError, 'RESOURCE_BUSY'):
                node.configure_lan_capacity(transactions_per_block=3000)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertEqual(node.configure_lan_capacity(transactions_per_block=3000)['transactions_per_block'], 3000)

    def test_cancelled_large_work_does_not_partially_admit_or_spend_nonce(self):
        node = self.nodes()[0]
        calls = [0]
        def cancel():
            calls[0] += 1
            if calls[0] == 6:
                raise ValueError('GG_DAG_TEST_CANCEL')
        with self.assertRaisesRegex(ValueError, 'GG_DAG_TEST_CANCEL'):
            node.produce_lan_test_block(0, 5000, LAN_MAX_BLOCK_BYTES, check=cancel)
        self.assertEqual(node.lan_evidence()['transactions'], 0)
        self.assertEqual(node._lan_counts.get(0, 0), 0)
        node.produce_lan_test_block(0, 2, LAN_MAX_BLOCK_BYTES)
        self.assertEqual(node.lan_evidence()['transactions'], 2)


if __name__ == '__main__':
    unittest.main()
