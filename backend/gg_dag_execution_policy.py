"""Genesis-bound rules for the current finite, nonfinancial DAG protocol.

These are consensus bounds, not RAM/disk quotas, measured throughput or public
currency policy. Legacy genesis v2 retains precisely its original rules.
Importing this module creates no key, process, file, thread or connection.
"""
from __future__ import annotations

MAX_HISTORY_BLOCKS=4095
MAX_HISTORY_RAW_BYTES=512*1024*1024
MAX_BLOCK_TRANSACTIONS=50000
MAX_BLOCK_WIRE_BYTES=32*1024*1024
MAX_BLOCK_PARENTS=7
MAX_BLOCK_RANK=4096
MAX_BLOCK_SEQUENCE=4096
MAX_CHECKPOINT_BLOCKS=128
MAX_CHECKPOINT_ENCODED_BYTES=48*1024*1024
MAX_CHECKPOINT_RAW_BYTES=32*1024*1024
GENESIS_SCHEMA='gg.parallel-dag.genesis.v3'
PUBLIC_GENESIS_SCHEMA='gg.parallel-dag.public-genesis.v3'


def execution_policy():
    """Fresh public descriptor: callers cannot mutate another network's rules."""
    return {
        'block_max_parents':MAX_BLOCK_PARENTS,
        'block_max_rank':MAX_BLOCK_RANK,
        'block_max_sequence':MAX_BLOCK_SEQUENCE,
        'block_max_transactions':MAX_BLOCK_TRANSACTIONS,
        'block_max_wire_bytes':MAX_BLOCK_WIRE_BYTES,
        'checkpoint_max_blocks':MAX_CHECKPOINT_BLOCKS,
        'checkpoint_max_encoded_bytes':MAX_CHECKPOINT_ENCODED_BYTES,
        'checkpoint_max_raw_bytes':MAX_CHECKPOINT_RAW_BYTES,
        'history_max_blocks':MAX_HISTORY_BLOCKS,
        'history_max_raw_bytes':MAX_HISTORY_RAW_BYTES,
        'history_verification':'FULL_SIGNED_GENESIS_REPLAY',
        'profile':'GG-DAG-FINITE-v1',
        'schema':'gg.dag.execution-policy.v1',
        'transaction_model':'PRODUCER_OWNED_NONFINANCIAL',
    }


def require_execution_policy(value):
    expected=execution_policy()
    if (not isinstance(value,dict) or set(value)!=set(expected)
            or any(type(value[key]) is not type(item) or value[key]!=item for key,item in expected.items())):
        raise ValueError('GG_DAG_EXECUTION_POLICY_UNSUPPORTED')


def require_genesis_policy(genesis):
    """Never infer or silently upgrade the policy of an existing genesis."""
    if not isinstance(genesis,dict):raise ValueError('GG_DAG_EXECUTION_POLICY_UNSUPPORTED')
    if genesis.get('schema')=='gg.parallel-dag.genesis.v2':
        if 'execution_policy' in genesis:raise ValueError('GG_DAG_EXECUTION_POLICY_UNSUPPORTED')
    elif genesis.get('schema')==GENESIS_SCHEMA:
        require_execution_policy(genesis.get('execution_policy'))
    else:raise ValueError('GG_DAG_EXECUTION_POLICY_UNSUPPORTED')
