"""Small cosmetic preferences keyed by canonical network-qualified asset IDs.

This never reads a balance, changes asset identity, or confers signing authority.
The existing per-user registry transaction serializes writes across views.
"""
from __future__ import annotations

import re
import json
from functools import lru_cache
from pathlib import Path
from backend import omni_assets as store

SCHEMA = 'gg.wallet-token-colors.v1'
MAX_COLORS = 2048
_HEX = re.compile(r'#[0-9a-fA-F]{6}\Z')


@lru_cache(maxsize=1)
def _palette():
    body = json.loads((Path(__file__).resolve().parents[1]/'config/gg-palette.json').read_text(encoding='utf-8'))
    colors = body.get('colors')
    legacy = body.get('legacy_colors', [])
    if (body.get('schema') != 'gg.palette.v1' or not isinstance(colors, list) or len(colors) != 64
            or not isinstance(legacy, list) or len(legacy) > 64
            or any(not isinstance(color, str) or not _HEX.fullmatch(color) for color in colors + legacy)):
        raise ValueError('WALLET_TOKEN_COLOR_PALETTE_INVALID')
    # Existing explicit hex choices survive palette curation. Only the64
    # canonical swatches are offered for new choices in the UI.
    return frozenset(color.lower() for color in colors + legacy)


def _table(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS wallet_token_colors(
        asset_id TEXT PRIMARY KEY,
        color TEXT NOT NULL)''')


def _snapshot(connection):
    rows = connection.execute('SELECT asset_id,color FROM wallet_token_colors ORDER BY asset_id LIMIT ?',
                              (MAX_COLORS,)).fetchall()
    return {'schema': SCHEMA, 'colors': {row['asset_id']: row['color'].lower() for row in rows
            if isinstance(row['color'], str) and row['color'].lower() in _palette()}}


def snapshot():
    with store.db() as connection:
        _table(connection)
        return _snapshot(connection)


def set_color(asset_id, color):
    if (not isinstance(asset_id, str) or not 1 <= len(asset_id) <= 240
            or not isinstance(color, str) or not _HEX.fullmatch(color) or color.lower() not in _palette()):
        raise ValueError('WALLET_TOKEN_COLOR_INVALID')
    with store.db(True) as connection:
        _table(connection)
        # A ticker or a position/account key is never a substitute for identity.
        if not connection.execute('SELECT 1 FROM assets WHERE id=?', (asset_id,)).fetchone():
            raise ValueError('WALLET_TOKEN_COLOR_ASSET_UNKNOWN')
        if (connection.execute('SELECT COUNT(*) FROM wallet_token_colors').fetchone()[0] >= MAX_COLORS
                and not connection.execute('SELECT 1 FROM wallet_token_colors WHERE asset_id=?',
                                           (asset_id,)).fetchone()):
            raise ValueError('WALLET_TOKEN_COLOR_LIMIT')
        connection.execute('INSERT OR REPLACE INTO wallet_token_colors(asset_id,color) VALUES(?,?)',
                           (asset_id, color.lower()))
        return _snapshot(connection)
