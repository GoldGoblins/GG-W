"""Public DAG source binding for the optional owned native test committee.

This module creates no key, process, listener or vote. It pins the existing
nonfinancial producer-owned DAG; it does not turn its six slots into validators.
"""
from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import re

from backend.gg_ed25519 import SIGNATURE_PROFILE, require_public_key
from backend.gg_parallel_dag import _tree, digest, pack
from backend import gg_dag_execution_policy as execution_rules

_HASH=re.compile(r'[0-9a-f]{64}')
_DECIMAL=re.compile(r'[1-9][0-9]{0,18}')
SOURCE_SCHEMA='gg.dag.consensus.source.v1'
CONFLICT='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
MAX_CONFLICT_BYTES=256*1024-128


def certificate_tip(packet,anchor):
    """Structural pin only. Callers must independently run the SDK verifier."""
    try:
        fields={'schema','genesis','genesis_hash','state','signed_header'}
        if isinstance(packet,dict) and anchor['genesis'].get('schema')=='gg.native.genesis.v7' and 'committee_transitions' in packet:
            if not isinstance(packet['committee_transitions'],list) or len(packet['committee_transitions'])>128:raise ValueError()
            fields.add('committee_transitions')
        if (not isinstance(packet,dict) or set(packet)!=fields
                or len(pack(packet))>256*1024 or packet['schema']!='gg.consensus.proof.v1'
                or packet['genesis']!=anchor['genesis'] or packet['genesis_hash']!=anchor['genesis_hash']):raise ValueError()
        height=packet['state']['height'];root=packet['state']['state_root'];header=packet['signed_header'];identifier=header['commit']['block_id']['hash']
        if (type(height) is not int or not 0<=height<2**63-1 or header['header']['height']!=str(height+1)
                or not isinstance(root,str) or not _HASH.fullmatch(root) or not isinstance(identifier,str)
                or not re.fullmatch(r'[0-9a-fA-F]{64}',identifier)):raise ValueError()
        return height+1,identifier.lower()
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_DAG_CERTIFICATE_CONTEXT') from None


def validate_conflict_evidence(value,anchor):
    """Structural context only; BOTH certificates still require SDK verification."""
    try:
        maximum=512*1024+2048 if anchor['genesis'].get('schema')=='gg.native.genesis.v7' else MAX_CONFLICT_BYTES
        if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','height','certificates'}
                or value['schema']!='gg.dag.certified-conflict.v1' or value['genesis_hash']!=anchor['genesis_hash']
                or type(value['height']) is not int or not isinstance(value['certificates'],list)
                or len(value['certificates'])!=2 or len(pack(value))>maximum):raise ValueError()
        tips=[certificate_tip(packet,anchor) for packet in value['certificates']]
        if tips[0][0]!=value['height'] or tips[1][0]!=value['height'] or tips[0][1]>=tips[1][1]:raise ValueError()
        return value
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_DAG_CONFLICT_EVIDENCE') from None


def make_conflict_evidence(first,second,anchor):
    packets=sorted((first,second),key=lambda packet:certificate_tip(packet,anchor)[1])
    value={'schema':'gg.dag.certified-conflict.v1','genesis_hash':anchor['genesis_hash'],
           'height':certificate_tip(first,anchor)[0],'certificates':deepcopy(packets)}
    return validate_conflict_evidence(value,anchor)


def validate_source(value):
    """Validate public source data; trust still comes from its pinned genesis."""
    if isinstance(value,dict) and value.get('schema')=='gg.dag.consensus.source.v2':
        from backend.gg_dag_segmented import validate_source as segmented_validate
        return segmented_validate(value)
    try:
        if not isinstance(value,dict) or set(value)!={'accounts','allowed_producers','genesis','genesis_hash',
                'network_id','schema','signature_profile','started_at_ns'}:raise ValueError()
        if len(pack(value))>16384:raise ValueError()
        source=deepcopy(value);genesis=source['genesis'];started=source['started_at_ns']
        execution_rules.require_genesis_policy(genesis)
        genesis_keys={'account_count','allocation_atomic','chain_id','precheck_root','producers','schema','test_mode'}
        if genesis['schema']==execution_rules.GENESIS_SCHEMA:genesis_keys.add('execution_policy')
        if (source['schema']!=SOURCE_SCHEMA or source['signature_profile']!=SIGNATURE_PROFILE
                or not isinstance(source['network_id'],str) or not _HASH.fullmatch(source['network_id'])
                or not isinstance(started,str) or not _DECIMAL.fullmatch(started) or not 10**9<=int(started)<=2**63-1
                or set(genesis)!=genesis_keys or genesis['test_mode']!='PRODUCER_OWNED_NONFINANCIAL'
                or type(genesis['account_count']) is not int or genesis['account_count']!=6
                or genesis['allocation_atomic']!='1000000000'
                or not isinstance(genesis['chain_id'],str) or not re.fullmatch(r'ggdag:[0-9a-f]{24}',genesis['chain_id'])
                or source['genesis_hash']!=digest(genesis)):raise ValueError()
        producers=genesis['producers'];accounts=source['accounts'];allowed=source['allowed_producers']
        if (not isinstance(producers,list) or len(producers)!=6
                or any(not isinstance(key,str) or not _HASH.fullmatch(key) for key in producers)
                or len(set(producers))!=6 or not isinstance(accounts,list) or accounts!=sorted(producers)
                or not isinstance(allowed,list) or any(type(index) is not int or not 0<=index<6 for index in allowed)
                or allowed!=sorted(set(allowed))):raise ValueError()
        for public in producers:require_public_key(bytes.fromhex(public))
        leaves=[{'address':address,'balance_atomic':'1000000000','nonce':0} for address in accounts]
        if genesis['precheck_root']!=_tree(leaves,b'GG-DAG-ACCOUNT-v1\0')[-1][0]:raise ValueError()
        return source
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_CHECKPOINT_SOURCE_INVALID') from None


def source_from_owned_peer(peer):
    """Derive policy from an already installed, signed LAN session, never UI labels."""
    from backend.gg_lan_dag import LanDagPeer
    if not isinstance(peer,LanDagPeer):raise ValueError('GG_DAG_CHECKPOINT_OWNED_PEER_REQUIRED')
    with peer._configuration,peer._lock:
        if peer._cancel.is_set() or peer._engine is None or peer._bundle is None or not peer._engine._lan_test_mode:
            raise ValueError('GG_DAG_CHECKPOINT_ACTIVE_SESSION_REQUIRED')
        public=peer._engine.export_public_genesis();body=peer._bundle['body']
        if public!=body['public_genesis'] or peer._network!=digest(body,b'GG-LAN-DAG-NETWORK-v1\0'):
            raise ValueError('GG_DAG_CHECKPOINT_SESSION_CHANGED')
        allowed=sorted(index for row in peer._roster.values() if row.get('node_role','producer')=='producer' for index in row['producer_indices'])
        return validate_source({'schema':SOURCE_SCHEMA,'signature_profile':SIGNATURE_PROFILE,
            'accounts':public['accounts'],'allowed_producers':allowed,'genesis':public['genesis'],
            'genesis_hash':public['genesis_hash'],'network_id':peer._network,'started_at_ns':str(public['started_at_ns'])})


def check_complete_order(state,order,source):
    """Consistency of a complete SDK-proven order; this is not a quorum verifier."""
    try:
        commitment=state['dag']
        if not isinstance(order,list) or not 0<=len(order)<=execution_rules.MAX_HISTORY_BLOCKS or len(order)!=commitment['blocks']:raise ValueError()
        heads={};sequences={};identifiers=set();transactions=0
        for index,leaf in enumerate(order):
            if (not isinstance(leaf,dict) or set(leaf)!={'hash','index','producer_index','sequence','transactions'}
                    or type(leaf['index']) is not int or leaf['index']!=index+1
                    or not isinstance(leaf['hash'],str) or not _HASH.fullmatch(leaf['hash']) or leaf['hash'] in identifiers
                    or type(leaf['producer_index']) is not int or leaf['producer_index'] not in source['allowed_producers']
                    or type(leaf['sequence']) is not int or leaf['sequence']!=sequences.get(leaf['producer_index'],0)+1
                    or type(leaf['transactions']) is not int or not 0<=leaf['transactions']<=execution_rules.MAX_BLOCK_TRANSACTIONS):raise ValueError()
            producer=leaf['producer_index'];identifiers.add(leaf['hash']);heads[producer]=leaf['hash']
            sequences[producer]=leaf['sequence'];transactions+=leaf['transactions']
        if transactions!=commitment['transactions']:raise ValueError()
        return identifiers,heads,sequences
    except (ValueError,TypeError,KeyError):raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT') from None


def select_checkpoint(peer,anchor,certified):
    """Choose already admitted payloads against a complete SDK-verified view.

    Only OwnedValidator supplies `certified`; this helper does not accept an
    external JSON command or infer finality from ordinary admission.
    """
    source=source_from_owned_peer(peer)
    if source!=anchor['genesis']['dag'] or certified['certificate']['genesis_hash']!=anchor['genesis_hash']:
        raise ValueError('GG_DAG_CHECKPOINT_ANCHOR_CHANGED')
    state=certified['certificate']['state'];known,heads,sequences=check_complete_order(state,certified['order'],source)
    known.add(source['genesis_hash']);commitment=state['dag']
    with peer._engine._lock:
        if peer._engine._lan_fault:raise ValueError(peer._engine._lan_fault)
        quarantined=frozenset(peer._engine._lan_quarantine)
        candidates=sorted((row for row in peer._engine._records.values() if row.get('signature_verified') is True and row['hash'] not in known),
                          key=lambda row:(row['rank'],row['hash']))
    selected=[];raws=[];size=0
    for row in candidates:
        if peer._cancel.is_set():raise ValueError('GG_DAG_CHECKPOINT_CANCELLED')
        if len(selected)>=min(execution_rules.MAX_CHECKPOINT_BLOCKS,execution_rules.MAX_HISTORY_BLOCKS-commitment['blocks']):break
        producer=row['producer_index'];parents=row['parents']
        if producer in quarantined:continue
        if (producer not in source['allowed_producers'] or row['producer_sequence']!=sequences.get(producer,0)+1
                or any(parent not in known for parent in parents) or producer in heads and heads[producer] not in parents):continue
        wire_size=peer._engine.proposal_wire_size(row['hash'])
        if type(wire_size) is not int or not 0<wire_size<=execution_rules.MAX_BLOCK_WIRE_BYTES:raise ValueError('GG_DAG_CHECKPOINT_STORED_WIRE')
        if size+wire_size>execution_rules.MAX_CHECKPOINT_RAW_BYTES:continue
        wire=peer._engine.public_proposal(row['hash'])
        if not isinstance(wire,bytes) or len(wire)!=wire_size:raise ValueError('GG_DAG_CHECKPOINT_STORED_WIRE')
        size+=len(wire);selected.append(row['hash']);raws.append(base64.b64encode(wire).decode('ascii'))
        known.add(row['hash']);heads[producer]=row['hash'];sequences[producer]=row['producer_sequence']
    if not selected:return None
    body={'schema':'gg.dag.checkpoint.batch.v1','genesis_hash':anchor['genesis_hash'],
          'previous':commitment['manifest_hash'],'sequence':commitment['checkpoint']+1,'blocks':raws}
    wire=pack(body)
    if len(wire)>execution_rules.MAX_CHECKPOINT_ENCODED_BYTES:raise ValueError('GG_DAG_CHECKPOINT_BATCH_LIMIT')
    return {'wire':wire,'descriptor':{'schema':'gg.dag.pending-checkpoint.v1','genesis_hash':anchor['genesis_hash'],
        'previous':body['previous'],'sequence':body['sequence'],'block_ids':selected,'hash':hashlib.sha256(wire).hexdigest(),'state':'PREPARED'}}


def restore_checkpoint(peer,descriptor):
    """Reconstruct exactly the persisted public request; never replace its IDs."""
    sizes=[peer._engine.proposal_wire_size(identifier) for identifier in descriptor['block_ids']]
    if any(size is None for size in sizes):raise ValueError('GG_DAG_PENDING_PAYLOAD_MISSING')
    if sum(sizes)>32*1024*1024:raise ValueError('GG_DAG_CHECKPOINT_BATCH_LIMIT')
    raws=[peer._engine.public_proposal(identifier) for identifier in descriptor['block_ids']]
    if any(not isinstance(raw,bytes) for raw in raws):raise ValueError('GG_DAG_PENDING_PAYLOAD_MISSING')
    wire=pack({'schema':'gg.dag.checkpoint.batch.v1','genesis_hash':descriptor['genesis_hash'],
        'previous':descriptor['previous'],'sequence':descriptor['sequence'],'blocks':[base64.b64encode(raw).decode('ascii') for raw in raws]})
    if len(wire)>48*1024*1024 or hashlib.sha256(wire).hexdigest()!=descriptor['hash']:raise ValueError('GG_DAG_PENDING_PAYLOAD_CHANGED')
    return wire
