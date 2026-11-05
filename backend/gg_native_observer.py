"""Public read-only native peer grants, pinned to an authenticated LAN roster.

Possession of a producer key delegates one observer endpoint. It never changes
genesis, validator voting power, producer ownership or financial allocations.
No I/O, keys, processes or listeners are created by importing this module.
"""
from copy import deepcopy

from backend.gg_consensus_membership import (anchor_from_bundle,private_endpoint,
    label_wire,public_label,HEX,SIG)
from backend.gg_ed25519 import SIGNATURE_PROFILE,require_public_key,verify_signature
from backend.gg_parallel_dag import pack

GRANT='gg.native.observer-grant.v1'
ADMISSIONS='gg.native.observer-admissions.v1'
MAX_GRANTS=6
MAX_DOCUMENT=64*1024
DOMAINS={role:('GG-NATIVE-OBSERVER-'+role.upper()+'-GRANT-v1\0').encode('ascii')
    for role in ('node','owner','producer')}


def validate_grant(grant,bundle,coordinator):
    """Check all three signatures AND the signed transport/producer mapping."""
    try:
        anchor=anchor_from_bundle(bundle,coordinator)
        if (not isinstance(grant,dict) or set(grant)!={'body','node_signature','owner_signature','producer_signature'}
                or len(pack(grant))>4096):raise ValueError()
        body=grant['body']
        if (not isinstance(body,dict) or set(body)!={'schema','signature_profile','genesis_hash','host','label_utf8',
                'node_key','owner_peer_key','producer_key','p2p_port'} or body['schema']!=GRANT
                or body['signature_profile']!=SIGNATURE_PROFILE or body['genesis_hash']!=anchor['genesis_hash']):raise ValueError()
        private_endpoint(body['host'],body['p2p_port']);public_label(body)
        keys=[body[field] for field in ('node_key','owner_peer_key','producer_key')]
        if any(not isinstance(key,str) or not HEX.fullmatch(key) for key in keys) or len(set(keys))!=3:raise ValueError()
        from backend.gg_lan_dag import validate_invite
        owners=[validate_invite(entry['invite']) for entry in bundle['body']['roster']]
        producers=[key for row in owners for key in row['producer_keys']]
        owner=next((row for row in owners if row['peer_key']==body['owner_peer_key']),None)
        if (owner is None or owner.get('node_role','producer')=='light' or body['producer_key'] not in owner['producer_keys']
                or body['host']!=owner['host'] or body['p2p_port']==owner['port']):raise ValueError()
        committee=[row['body'] for row in anchor['genesis']['membership']['validators']]
        forbidden={row[role+'_key'] for row in committee for role in ('validator','node','account')}
        owner_keys={row['peer_key'] for row in owners}
        if (body['node_key'] in set(producers)|forbidden|owner_keys or body['owner_peer_key'] in set(producers)|forbidden
                or any((body['host'],body['p2p_port'])==(row['host'],row['p2p_port']) for row in committee)):
            raise ValueError()
        for role,public in zip(('node','owner','producer'),keys):
            require_public_key(bytes.fromhex(public));signature=grant[role+'_signature']
            if not isinstance(signature,str) or not SIG.fullmatch(signature):raise ValueError()
            verify_signature(bytes.fromhex(public),DOMAINS[role]+pack(body),bytes.fromhex(signature))
        return deepcopy(body)
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError,StopIteration):
        raise ValueError('GG_NATIVE_OBSERVER_GRANT_INVALID') from None


def make_grant(node,owner,producer,bundle,coordinator,*,label,host,p2p_port):
    anchor=anchor_from_bundle(bundle,coordinator)
    body={'schema':GRANT,'signature_profile':SIGNATURE_PROFILE,'genesis_hash':anchor['genesis_hash'],
        'host':host,'p2p_port':p2p_port,'label_utf8':label_wire(label),
        'node_key':node.pubkey().hex(),'owner_peer_key':owner.pubkey().hex(),'producer_key':producer.pubkey().hex()}
    result={'body':body}
    for role,key in zip(('node','owner','producer'),(node,owner,producer)):
        result[role+'_signature']=key.sign_message(DOMAINS[role]+pack(body)).hex()
    validate_grant(result,bundle,coordinator)
    return result


def admission_document(grants,bundle,coordinator):
    if not isinstance(grants,list) or len(grants)>MAX_GRANTS:raise ValueError('GG_NATIVE_OBSERVER_ADMISSIONS_INVALID')
    anchor=anchor_from_bundle(bundle,coordinator)
    bodies=[validate_grant(grant,bundle,coordinator) for grant in grants]
    if any(len({row[field] for row in bodies})!=len(bodies) for field in ('producer_key','node_key')):
        raise ValueError('GG_NATIVE_OBSERVER_ADMISSIONS_DUPLICATE')
    if len({(row['host'],row['p2p_port']) for row in bodies})!=len(bodies):
        raise ValueError('GG_NATIVE_OBSERVER_ADMISSIONS_DUPLICATE')
    result={'schema':ADMISSIONS,'genesis_hash':anchor['genesis_hash'],
        'grants':sorted(deepcopy(grants),key=lambda row:row['body']['producer_key'])}
    if len(pack(result))>MAX_DOCUMENT:raise ValueError('GG_NATIVE_OBSERVER_ADMISSIONS_INVALID')
    return result


def publish_admissions(root,grants,bundle,coordinator):
    """Publish a validated public policy only in its exact owned validator root.

    The owner must hold its profile lease/lock. A crash after the protected
    metadata commit but before this cache write is repaired by republishing.
    """
    import os
    from pathlib import Path
    import secrets
    import stat
    from backend.platform_files import is_link,secure_open,atomic_replace,sync_directory
    from backend.gg_node_store import _private_path
    document=admission_document(grants,bundle,coordinator);anchor=anchor_from_bundle(bundle,coordinator)
    root=Path(root).absolute()
    if not root.is_dir() or any(is_link(path) for path in (root,*root.parents)):
        raise ValueError('GG_OBSERVER_ADMISSION_NATIVE_ROOT')
    _private_path(root,0o700)
    marker=root/'gg-public-genesis.json'
    descriptor=secure_open(marker,os.O_RDONLY)
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=65536
                or stream.read(65537)!=pack(anchor['genesis'])):raise ValueError('GG_OBSERVER_ADMISSION_NATIVE_ROOT')
    if (root/'gg-observer-identity.json').exists():raise ValueError('GG_OBSERVER_ADMISSION_NATIVE_ROOT')
    destination=root/'gg-observer-admissions.json'
    try:
        info=destination.lstat()
        if is_link(destination) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_DOCUMENT:
            raise ValueError('GG_OBSERVER_ADMISSION_FILE')
    except FileNotFoundError:pass
    temporary=root/('.gg-observer-admissions-'+secrets.token_hex(12)+'.tmp')
    try:
        descriptor=secure_open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(pack(document));stream.flush();os.fsync(stream.fileno())
        _private_path(temporary,0o600);atomic_replace(temporary,destination);sync_directory(root)
    finally:
        try:temporary.unlink()
        except FileNotFoundError:pass
    return deepcopy(document)
