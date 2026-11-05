"""Signed public membership for a fixed private-LAN test committee.

All four invites prove possession of validator, P2P, account and LAN-owner
keys. This is explicit membership, not Sybil resistance or host attestation.
No key generation, I/O, socket or process runs at import.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import ipaddress
import re
import secrets
import time

from backend.gg_ed25519 import SIGNATURE_PROFILE,require_public_key,verify_signature
from backend.gg_parallel_dag import pack,digest
from backend.gg_dag_checkpoint import validate_source

SCOPE='PRIVATE_LAN_EXPERIMENT'
INVITE_SCHEMA='gg.consensus.validator.invite.v1'
MEMBERSHIP_SCHEMA='gg.lan.consensus.membership.v1'
DOMAINS={role:('GG-CONSENSUS-'+role.upper()+'-INVITE-v1\0').encode('ascii') for role in ('validator','node','account','owner')}
HEX=re.compile(r'[0-9a-f]{64}')
SIG=re.compile(r'[0-9a-f]{128}')
PRIVATE=tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8'))


def label_wire(label):
    if not isinstance(label,str) or not 1<=len(label)<=64 or any(ord(c)<32 or ord(c)==127 for c in label):
        raise ValueError('GG_CONSENSUS_MEMBER_LABEL')
    return base64.b64encode(label.encode('utf-8')).decode('ascii')


def public_label(body):
    try:
        raw=base64.b64decode(body['label_utf8'],validate=True)
        label=raw.decode('utf-8')
        if label_wire(label)!=body['label_utf8']:raise ValueError()
        return label
    except (KeyError,UnicodeError,ValueError,TypeError):raise ValueError('GG_CONSENSUS_MEMBER_LABEL') from None


def private_endpoint(host,port):
    try:
        address=ipaddress.IPv4Address(host)
        if str(address)!=host or not any(address in net for net in PRIVATE):raise ValueError()
        if type(port) is not int or not 1024<=port<=65535:raise ValueError()
        return host,port
    except (ValueError,TypeError):raise ValueError('GG_CONSENSUS_MEMBER_ENDPOINT') from None


def make_invite(validator,node,account,owner,*,label,host,p2p_port,nonce):
    private_endpoint(host,p2p_port)
    body={'schema':INVITE_SCHEMA,'signature_profile':SIGNATURE_PROFILE,'validator_key':validator.pubkey().hex(),
        'node_key':node.pubkey().hex(),'account_key':account.pubkey().hex(),'owner_peer_key':owner.pubkey().hex(),
        'label_utf8':label_wire(label),'host':host,'p2p_port':p2p_port,'nonce':nonce}
    invite={'body':body}
    for role,key in zip(('validator','node','account','owner'),(validator,node,account,owner)):
        invite[role+'_signature']=key.sign_message(DOMAINS[role]+pack(body)).hex()
    validate_invite(invite)
    return invite


def validate_invite(invite):
    try:
        if (not isinstance(invite,dict) or set(invite)!={'body','validator_signature','node_signature','account_signature','owner_signature'}
                or len(pack(invite))>4096):raise ValueError()
        body=invite['body']
        if (not isinstance(body,dict) or set(body)!={'schema','signature_profile','validator_key','node_key','account_key',
                'owner_peer_key','label_utf8','host','p2p_port','nonce'} or body['schema']!=INVITE_SCHEMA
                or body['signature_profile']!=SIGNATURE_PROFILE or not isinstance(body['nonce'],str) or not HEX.fullmatch(body['nonce'])):raise ValueError()
        public_label(body);private_endpoint(body['host'],body['p2p_port'])
        keys=[body[name] for name in ('validator_key','node_key','account_key','owner_peer_key')]
        if any(not isinstance(key,str) or not HEX.fullmatch(key) for key in keys) or len(set(keys))!=4:raise ValueError()
        for role,public in zip(('validator','node','account','owner'),keys):
            require_public_key(bytes.fromhex(public))
            signature=invite[role+'_signature']
            if not isinstance(signature,str) or not SIG.fullmatch(signature):raise ValueError()
            verify_signature(bytes.fromhex(public),DOMAINS[role]+pack(body),bytes.fromhex(signature))
        return deepcopy(body)
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):
        raise ValueError('GG_CONSENSUS_MEMBER_INVITE') from None


def validate_membership(value,*,owners=None,forbidden_keys=()):
    try:
        if (not isinstance(value,dict) or set(value)!={'schema','scope','chain_id','genesis_time_unix','validators'}
                or len(pack(value))>20*1024 or value['schema']!=MEMBERSHIP_SCHEMA or value['scope']!=SCOPE
                or not isinstance(value['chain_id'],str) or not re.fullmatch(r'ggnet:[0-9a-f]{24}',value['chain_id'])
                or type(value['genesis_time_unix']) is not int or not 0<value['genesis_time_unix']<=(2**63-1-5_000_000_000)//1_000_000_000
                or not isinstance(value['validators'],list) or len(value['validators'])!=4):raise ValueError()
        checked=[validate_invite(invite) for invite in value['validators']]
        order=[row['validator_key'] for row in checked]
        keys=[row[role+'_key'] for row in checked for role in ('validator','node','account')]
        if (order!=sorted(order) or len(set(keys))!=12 or set(keys)&set(forbidden_keys)
                or set(keys)&{row['owner_peer_key'] for row in checked}
                or len({(row['host'],row['p2p_port']) for row in checked})!=4):raise ValueError()
        if owners is not None:
            for row in checked:
                owner=owners.get(row['owner_peer_key'])
                if (owner is None or owner.get('node_role')=='light' or row['host']!=owner['host'] or row['p2p_port']==owner['port']):raise ValueError()
        return deepcopy(value)
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):
        raise ValueError('GG_CONSENSUS_MEMBERSHIP_INVALID') from None


def make_membership(invites,*,owners,forbidden_keys,chain_id=None,genesis_time_unix=None):
    if not isinstance(invites,list) or len(invites)!=4:raise ValueError('GG_CONSENSUS_FOUR_MEMBER_INVITES_REQUIRED')
    for invite in invites:validate_invite(invite)
    membership={'schema':MEMBERSHIP_SCHEMA,'scope':SCOPE,'chain_id':chain_id or 'ggnet:'+secrets.token_hex(12),
        'genesis_time_unix':int(time.time()) if genesis_time_unix is None else genesis_time_unix,
        'validators':sorted(deepcopy(invites),key=lambda value:value['body']['validator_key'])}
    return validate_membership(membership,owners=owners,forbidden_keys=forbidden_keys)


def anchor_from_bundle(bundle,coordinator):
    """Verify the pinned LAN signature and derive its single native genesis."""
    if isinstance(bundle,dict) and isinstance(bundle.get('body'),dict) and bundle['body'].get('schema') in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
        from backend.gg_financial_session import validate_bundle
        return validate_bundle(bundle,coordinator)['anchor']
    if isinstance(bundle,dict) and isinstance(bundle.get('body'),dict) and bundle['body'].get('schema')=='gg.lan-dag.session.v5':
        from backend.gg_dag_segmented_session import validate_bundle
        return validate_bundle(bundle,coordinator)['anchor']
    from backend.gg_lan_dag import _checked,_BUNDLE,validate_invite as lan_invite
    try:
        if len(pack(bundle))>256*1024:raise ValueError()
        body=_checked(bundle,_BUNDLE,coordinator)
        if (not isinstance(body,dict) or set(body)!={'schema','label','coordinator','roster','public_genesis',
                'transactions_enabled','dag_test_mode','consensus'} or body['schema']!='gg.lan-dag.session.v4'
                or body['coordinator']!=coordinator or body['transactions_enabled'] is not True
                or body['dag_test_mode']!='PRODUCER_OWNED_NONFINANCIAL' or not isinstance(body['roster'],list) or len(body['roster'])!=3):raise ValueError()
        label_wire(body['label'])
        owners={};producers=[];allowed=[]
        for index,entry in enumerate(body['roster']):
            if (not isinstance(entry,dict) or set(entry)!={'invite','producer_indices'}
                    or entry['producer_indices']!=[2*index,2*index+1] or any(type(i) is not int for i in entry['producer_indices'])):raise ValueError()
            owner=lan_invite(entry['invite'])
            if owner['peer_key'] in owners or owner.get('allow_dag_transactions') is not True:raise ValueError()
            owners[owner['peer_key']]=owner;producers.extend(owner['producer_keys'])
            if owner.get('node_role','producer')=='producer':allowed.extend(entry['producer_indices'])
        public=body['public_genesis']
        if (coordinator not in owners or len(set(producers))!=6 or set(producers)&set(owners)
                or len({(row['host'],row['port']) for row in owners.values()})!=3
                or not isinstance(public,dict) or set(public)!={'schema','genesis','genesis_hash','accounts','started_at_ns'}
                or public['schema'] not in ('gg.parallel-dag.public-genesis.v2','gg.parallel-dag.public-genesis.v3')
                or type(public['started_at_ns']) is not int):raise ValueError()
        if (public['schema']=='gg.parallel-dag.public-genesis.v3')!=(isinstance(public['genesis'],dict) and public['genesis'].get('schema')=='gg.parallel-dag.genesis.v3'):
            raise ValueError()
        source=validate_source({'schema':'gg.dag.consensus.source.v1','signature_profile':SIGNATURE_PROFILE,
            'genesis':public['genesis'],'genesis_hash':public['genesis_hash'],'accounts':public['accounts'],
            'started_at_ns':str(public['started_at_ns']),'allowed_producers':allowed,'network_id':digest(body,b'GG-LAN-DAG-NETWORK-v1\0')})
        if source['genesis']['producers']!=producers:raise ValueError()
        membership=validate_membership(body['consensus'],owners=owners,forbidden_keys=[*producers,*owners])
        if int(source['started_at_ns'])>membership['genesis_time_unix']*10**9+5_000_000_000:raise ValueError()
        members=[invite['body'] for invite in membership['validators']]
        genesis={'schema':'gg.native.genesis.v3','chain_id':membership['chain_id'],'genesis_time_unix':membership['genesis_time_unix'],
            'membership':membership,'accounts':[row['account_key'] for row in members],'validators':[row['validator_key'] for row in members],
            'dag':source,'supply_atomic':'1000000000000','decimals':6,'symbol':'GG-NET-TEST'}
        return {'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()}
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):
        raise ValueError('GG_CONSENSUS_LAN_ANCHOR_INVALID') from None


def anchor_from_owned_peer(peer):
    from backend.gg_lan_dag import LanDagPeer
    if not isinstance(peer,LanDagPeer):raise ValueError('GG_CONSENSUS_OWNED_PEER_REQUIRED')
    with peer._configuration,peer._lock:
        if peer._cancel.is_set() or peer._bundle is None or peer._engine is None:raise ValueError('GG_CONSENSUS_ACTIVE_LAN_REQUIRED')
        result=anchor_from_bundle(peer._bundle,peer._trusted)
        if result['genesis']['dag']['network_id']!=peer._network:raise ValueError('GG_CONSENSUS_LAN_ANCHOR_CHANGED')
        return result
