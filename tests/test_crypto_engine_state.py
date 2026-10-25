"""Paper-engine persistence and cache tests; all data is synthetic and local."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import crypto_contract as contract, crypto_trader as trader
from backend import crypto_flash_arb as arb, crypto_paper as paper, kaspa_contract as kaspa
from backend.platform_files import mode_matches


class EngineStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gg-crypto-engine-state-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in (contract, kaspa):
            override = patch.object(module, 'STATE_DIR', self.root / module.__name__.split('.')[-1])
            override.start(); self.addCleanup(override.stop)
        trader._bt_mem.clear()

    def test_malformed_saved_balances_are_preserved_with_explicit_diagnostics(self):
        paths = [(trader._state_path(), trader.load_state, 'CRYPTO_TRADER_STATE_CORRUPT'),
                 (arb.pools_path(), arb.load_pools, 'CRYPTO_ARB_STATE_CORRUPT'),
                 (paper._path('SOLUSDT'), lambda: paper.snapshot('SOLUSDT'), 'CRYPTO_PAPER_STATE_CORRUPT'),
                 (kaspa.ensure_state_dir()/'covenant.json', lambda: kaspa.load_json('covenant.json'), 'KASPA_STATE_CORRUPT')]
        for path, load, diagnostic in paths:
            for raw in (b'[{"damaged":true}]', b'{"interrupted":', b'{"balance":NaN}'):
                with self.subTest(component=diagnostic, shape=raw[:1]):
                    path.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, '^' + diagnostic + '$'):
                        load()
                    self.assertEqual(path.read_bytes(), raw)

    def test_missing_balance_reads_do_not_create_seed_files(self):
        self.assertIsInstance(trader.load_state(), dict)
        self.assertIsInstance(arb.load_pools(), dict)
        self.assertFalse(trader._state_path().exists())
        self.assertFalse(arb.pools_path().exists())

    def test_paper_wrong_schema_is_controlled_and_never_reseeded(self):
        path = paper._path('SOLUSDT')
        for value in ({'schema': paper.SCHEMA, 'pair': 'SOLUSDT', 'accounts': [], 'events': []},
                      {'schema': 999, 'pair': 'SOLUSDT', 'accounts': {}, 'events': []}):
            raw = json.dumps(value).encode('utf-8'); path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, '^CRYPTO_PAPER_STATE_'):
                paper.snapshot('SOLUSDT')
            self.assertEqual(path.read_bytes(), raw)

    def test_each_failed_publication_preserves_previous_record(self):
        trader.save_state(trader.default_state())
        arb.reset_pools()
        paper.set_all('SOLUSDT', False)
        kaspa.save_json('covenant.json', {'count': 42})
        operations = [(trader._state_path(), lambda: trader.save_state({**trader.default_state(), 'sol': 1})),
                      (arb.pools_path(), lambda: arb.save_pools({**arb._default_pools(), 'fee_bps': 31})),
                      (paper._path('SOLUSDT'), lambda: paper.set_all('SOLUSDT', True)),
                      (kaspa.ensure_state_dir()/'covenant.json', lambda: kaspa.save_json('covenant.json', {'count': 43}))]
        for path, save in operations:
            previous = path.read_bytes()
            with patch.object(contract, 'atomic_replace', side_effect=PermissionError('owned synthetic publication fault')):
                with self.assertRaises(PermissionError):
                    save()
            self.assertEqual(path.read_bytes(), previous)
            self.assertTrue(mode_matches(path, 0o600))
            self.assertEqual(list(path.parent.glob('*.new')), [])

    def test_backtest_cache_checks_identity_before_reading_report_contents(self):
        trader.save_backtest({'n': 1, 'chart': {}})
        initial = trader.load_backtest()
        path = trader._backtest_path()
        with patch.object(trader, 'read_state_json', side_effect=AssertionError('Cache hit must not read report contents')):
            self.assertEqual(trader._load_backtest_file(path), initial)

    def test_replaced_or_restored_mtime_backtest_invalidates_cache(self):
        trader.save_backtest({'n': 1, 'chart': {}, 'ran_at': 'synthetic'})
        path = trader._backtest_path()
        self.assertEqual(trader.load_backtest()['n'], 1)
        before = path.stat()
        raw = path.read_text(encoding='utf-8')
        self.assertEqual(raw.count('"n": 1'), 1)
        path.write_text(raw.replace('"n": 1', '"n": 2'), encoding='utf-8')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(trader.load_backtest()['n'], 2)

    def test_trader_journal_tail_recovers_after_partial_and_bad_utf8_rows(self):
        path = trader._lots_path()
        path.write_bytes(b'{"ignored":"' + b'x' * (contract._LEDGER_READ_BYTES + 10) + b'"}\n'
                         + b'{"sequence":1}\n\xff\n{"sequence":2}\n{"partial":')
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unbounded journal text read')):
            self.assertEqual(trader.read_lots(4), [{'sequence': 1}, {'sequence': 2}])

    def test_oversized_backtest_is_reported_without_replacing_it(self):
        path = trader._backtest_path()
        with path.open('wb') as stream:
            stream.write(b' ' * (16 * 1024 * 1024 + 1))
        previous_size = path.stat().st_size
        with self.assertRaisesRegex(ValueError, '^CRYPTO_BACKTEST_STATE_CORRUPT$'):
            trader.load_backtest()
        self.assertEqual(path.stat().st_size, previous_size)


if __name__ == '__main__':
    unittest.main(argv=[__file__], verbosity=2)
