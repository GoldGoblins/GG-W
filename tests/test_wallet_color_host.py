"""Actual QObject cosmetic slots, with an isolated real registry/preferences DB."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject
from PySide6.QtTest import QSignalSpy
from backend import omni_assets as assets, wallet_token_colors as preferences
from backend.chat_surface_host import ChatSurfaceHost

PROJECT=Path(__file__).resolve().parents[1]
PALETTE=json.loads((PROJECT/'config/gg-palette.json').read_text(encoding='utf-8'))['colors']


class WalletColorHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='gg-wallet-color-host-')
        self.directory=patch.object(assets,'ROOT',Path(self.temporary.name)/'omni')
        self.directory.start()
        assets.bootstrap()
        self.host=ChatSurfaceHost.__new__(ChatSurfaceHost)
        QObject.__init__(self.host)
        self.signal=QSignalSpy(self.host.walletTokenColorsUpdated)
        self.runtime=patch.object(ChatSurfaceHost,'_omni_runtime',side_effect=AssertionError('COSMETIC_SLOT_STARTED_RUNTIME'))
        self.runtime_mock=self.runtime.start()

    def tearDown(self):
        self.runtime_mock.assert_not_called()
        self.runtime.stop()
        self.directory.stop()
        self.temporary.cleanup()

    def test_read_returns_actual_saved_map_and_never_broadcasts(self):
        expected=preferences.set_color(assets.NATIVE_SOL,PALETTE[1])
        self.assertEqual(json.loads(self.host.walletTokenColors()),expected)
        self.assertEqual(self.signal.count(),0)

    def test_actual_save_commits_and_emits_exactly_one_identical_public_payload(self):
        raw=self.host.walletSetTokenColor(assets.NATIVE_SOL,PALETTE[2].upper())
        self.assertEqual(json.loads(raw),preferences.snapshot())
        self.assertEqual(json.loads(raw)['colors'],{assets.NATIVE_SOL:PALETTE[2]})
        self.assertEqual(self.signal.count(),1)
        self.assertEqual(self.signal.at(0),[raw])
        # An explicitly repeated, idempotent save is still one operation and
        # exactly one notification, rather than a recursive multi-view update.
        repeated=self.host.walletSetTokenColor(assets.NATIVE_SOL,PALETTE[2])
        self.assertEqual(repeated,raw)
        self.assertEqual(self.signal.count(),2)
        self.assertEqual(self.signal.at(1),[raw])

    def test_invalid_colors_unknown_assets_and_database_failure_preserve_prior_value_without_signal(self):
        previous=preferences.set_color(assets.NATIVE_SOL,PALETTE[0])
        for asset_id,color in ((assets.NATIVE_SOL,'#123456'),('SOL',PALETTE[1]),
                               (assets.NATIVE_SOL+'@account',PALETTE[1])):
            with self.subTest(asset_id=asset_id,color=color):
                self.assertEqual(json.loads(self.host.walletSetTokenColor(asset_id,color)),
                                 {'error':'WALLET_TOKEN_COLOR_SAVE_FAILED'})
                self.assertEqual(preferences.snapshot(),previous)
                self.assertEqual(self.signal.count(),0)
        with patch.object(preferences,'set_color',side_effect=sqlite3.OperationalError(
                'Synthetic unavailable database Z:/private-fixture/preferences.sqlite3')):
            raw=self.host.walletSetTokenColor(assets.NATIVE_SOL,PALETTE[3])
        self.assertEqual(json.loads(raw),{'error':'WALLET_TOKEN_COLOR_SAVE_FAILED'})
        self.assertNotIn('private-fixture',raw)
        self.assertNotIn('sqlite3',raw)
        self.assertEqual(preferences.snapshot(),previous)
        self.assertEqual(self.signal.count(),0)

    def test_read_failure_returns_generic_bounded_error_and_never_exposes_paths_or_exception(self):
        previous=preferences.set_color(assets.NATIVE_SOL,PALETTE[0])
        with patch.object(preferences,'snapshot',side_effect=PermissionError(
                'Synthetic denied Z:/private-fixture/preferences.sqlite3')):
            raw=self.host.walletTokenColors()
        self.assertEqual(json.loads(raw),{'schema':preferences.SCHEMA,'colors':{},
                                          'error':'WALLET_TOKEN_COLOR_READ_FAILED'})
        self.assertNotIn('private-fixture',raw)
        self.assertNotIn('PermissionError',raw)
        self.assertEqual(preferences.snapshot(),previous)
        self.assertEqual(self.signal.count(),0)


if __name__=='__main__':unittest.main()
