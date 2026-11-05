"""Allocation preflight for the fixed canonical LAN block collection shape.

This is not a JSON decoder or an authenticator. The normal strict decoder,
canonical-byte check and every block/transaction signature still run afterwards.
LAN TX-v2 and native financial-payment blocks share these collection bounds.
Their accepted wire strings are fixed ASCII domains, hex or decimal text;
escaped strings and extra collection shapes cannot occur in an accepted block.
Do not apply these limits to the older manual witness-bearing TX-v1 schema.
"""
from __future__ import annotations

import re

from backend.gg_dag_execution_policy import MAX_BLOCK_TRANSACTIONS

# Backslashes are rejected first, so a quoted string contains no escaped quote.
# The simple negated class scans long strings without per-character backtracking.
_TOKENS = re.compile(rb'"[^"]*"|[\[\]{}:,]')


def preflight_lan_block(raw: bytes, transactions: int = MAX_BLOCK_TRANSACTIONS) -> None:
    """Reject impossible collection amplification before json.loads allocates it.

    The caller enforces the raw-byte limit. Stack and match state are bounded;
    matches do not copy a potentially large quoted string out of the input.
    Syntax, duplicate names, types and exact fields remain decoder/protocol work.
    """
    if b'\\' in raw or not raw.isascii():
        raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
    stack = []
    arrays = objects = fields = tokens = 0
    for match in _TOKENS.finditer(raw):
        tokens += 1
        if tokens > 40 * transactions + 128:
            raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
        token = raw[match.start()]
        if token == 34:  # quoted string; punctuation inside it is not structure
            continue
        if token in (91, 123):
            if len(stack) >= 12:
                raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
            if token == 91:
                arrays += 1
                if arrays > 2:  # parents and transactions are the only arrays
                    raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
            else:
                objects += 1
                if objects > 2 * transactions + 2:
                    raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
            stack.append([token, 0])
        elif token in (93, 125):
            if not stack or stack[-1][0] != (91 if token == 93 else 123):
                raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
            stack.pop()
        elif stack and token == 44 and stack[-1][0] == 91:
            stack[-1][1] += 1
            if stack[-1][1] >= transactions:
                raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
        elif stack and token == 58 and stack[-1][0] == 123:
            stack[-1][1] += 1
            fields += 1
            if stack[-1][1] > 64 or fields > 9 * transactions + 64:
                raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
    if stack:
        raise ValueError('GG_DAG_WIRE_JSON_SHAPE')
