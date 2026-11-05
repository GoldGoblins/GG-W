"""Explicit old-network/new-network contracts and protected archive bindings.

The old network's originals and validator histories never become a fresh
genesis's history. Preparing a document or invitation does not install it.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import os
import sqlite3
import stat
import time

from backend import gg_node_store as store
from backend.gg_consensus_membership import anchor_from_bundle
from backend.gg_dag_segmented_session import validate_bundle
from backend.gg_ed25519 import verify_signature

DOMAIN=b'GG-LAN-NETWORK-TRANSITION-v1\0'
SCHEMA='gg.lan-dag.network-transition.v1'
PENDING='gg.node.network-transition-pending.v1'
COMPLETE='gg.node.network-transition-complete.v1'
MAX_DOCUMENT=256*1024+4096
IDENTITY=('label','host','port','peer_key','producer_keys','nonce','node_role','allow_test_tokens','allow_dag_transactions')


def _identity(invite):
    body=invite['body']
    return {name:deepcopy(body.get(name,'producer' if name=='node_role' else False)) for name in IDENTITY}


def _target(document,coordinator):
    from backend.gg_lan_dag import _checked
    if not isinstance(document,dict) or len(store.pack(document))>MAX_DOCUMENT:raise ValueError('GG_NETWORK_TRANSITION_DOCUMENT')
    body=_checked(document,DOMAIN,coordinator)
    if (not isinstance(body,dict) or set(body)!={'schema','from_native_genesis_hash','to_native_genesis_hash','bundle'}
            or body['schema']!=SCHEMA or type(body['from_native_genesis_hash']) is not str
            or not store.HEX.fullmatch(body['from_native_genesis_hash'])):raise ValueError('GG_NETWORK_TRANSITION_DOCUMENT')
    contract=validate_bundle(body['bundle'],coordinator)
    if body['to_native_genesis_hash']!=contract['anchor']['genesis_hash'] or body['from_native_genesis_hash']==body['to_native_genesis_hash']:
        raise ValueError('GG_NETWORK_TRANSITION_TARGET')
    return body,contract


def contract(profile,document):
    """Verify both complete signed sessions against the owned old profile."""
    config=profile.descriptor();session=profile.session()
    if (not isinstance(session,dict) or session.get('body',{}).get('schema')!='gg.lan-dag.session.v4'
            or profile.fault() or config['allow_test_tokens'] or not config['allow_dag_transactions']):
        raise ValueError('GG_NETWORK_TRANSITION_LEGACY_REQUIRED')
    old=anchor_from_bundle(session,config['trusted_coordinator']);body,new=_target(document,config['trusted_coordinator'])
    if body['from_native_genesis_hash']!=old['genesis_hash']:raise ValueError('GG_NETWORK_TRANSITION_SOURCE')
    prior={row['invite']['body']['peer_key']:row['invite'] for row in session['body']['roster']}
    target={row['invite']['body']['peer_key']:row['invite'] for row in body['bundle']['body']['roster']}
    if set(prior)!=set(target) or any(_identity(prior[key])!=_identity(target[key]) for key in prior):
        raise ValueError('GG_NETWORK_TRANSITION_OWNER_IDENTITY')
    owner=config['public_keys'][0];own=target.get(owner)
    if own is None or own['body']['producer_keys']!=config['public_keys'][1:] or own['body']['nonce']!=config['pair_nonce']:
        raise ValueError('GG_NETWORK_TRANSITION_OWNER_IDENTITY')
    old_source=old['genesis']['dag'];new_source=new['source']
    if (old_source['network_id']==new['network_id'] or old_source['genesis_hash']==new_source['genesis_hash']
            or old_source['genesis']['producers']!=new_source['genesis']['producers']
            or old['genesis']['chain_id']==new['anchor']['genesis']['chain_id']):
        raise ValueError('GG_NETWORK_TRANSITION_DOMAIN')
    old_keys={row['body'][name] for row in old['genesis']['membership']['validators'] for name in ('validator_key','node_key','account_key')}
    new_keys={row['body'][name] for row in new['anchor']['genesis']['membership']['validators'] for name in ('validator_key','node_key','account_key')}
    if old_keys&new_keys:raise ValueError('GG_NETWORK_TRANSITION_NEW_VALIDATOR_IDENTITIES_REQUIRED')
    return {'old_anchor':old,'target':new,'document':deepcopy(document),'own_invite':deepcopy(own)}


def prepare_invite(peer,profiles):
    """Sign new validator ads without changing the old peer/profile ads."""
    with peer._configuration,peer._lock:
        if peer._cancel.is_set():raise ValueError('GG_NETWORK_TRANSITION_OWNED_LEGACY_REQUIRED')
        return prepare_invite_from_profile(peer._profile,profiles)


def _owned_context(owner):
    if not isinstance(owner,store.NodeProfile) or owner._lease is None or owner._db is None:
        raise ValueError('GG_NETWORK_TRANSITION_OWNED_LEGACY_REQUIRED')
    config=owner.descriptor();session=owner.session()
    if session is None or session['body']['schema']!='gg.lan-dag.session.v4' or owner.fault():
        raise ValueError('GG_NETWORK_TRANSITION_LEGACY_REQUIRED')
    anchor_from_bundle(session,config['trusted_coordinator']);identity,_=owner.signers()
    return config,session,identity


def prepare_invite_from_profile(owner,profiles):
    """Offline public preparation from an exclusively opened protected owner."""
    from backend.gg_consensus_profile import ValidatorProfile
    from backend.gg_lan_dag import _INVITE,_signed,validate_invite
    if not isinstance(owner,store.NodeProfile):raise ValueError('GG_NETWORK_TRANSITION_OWNED_LEGACY_REQUIRED')
    with owner._lock:
        config,session,identity=_owned_context(owner);public=config['public_keys'][0]
        if not isinstance(profiles,(list,tuple)) or len(profiles)>4:raise ValueError('GG_NETWORK_TRANSITION_VALIDATORS')
        old_keys={row['body'][name] for row in session['body']['consensus']['validators'] for name in ('validator_key','node_key','account_key')}
        invites=[]
        for profile in profiles:
            if not isinstance(profile,ValidatorProfile) or profile._closed or profile._failed:
                raise ValueError('GG_NETWORK_TRANSITION_VALIDATORS')
            invite=profile.public_invite()
            if (invite['body']['owner_peer_key']!=public or profile.anchor() is not None
                    or profile._body['native_started'] or profile._body['fault']
                    or any(invite['body'][name] in old_keys for name in ('validator_key','node_key','account_key'))):
                raise ValueError('GG_NETWORK_TRANSITION_NEW_VALIDATOR_IDENTITIES_REQUIRED')
            invites.append(invite)
        body=deepcopy(next(row['invite']['body'] for row in session['body']['roster'] if row['invite']['body']['peer_key']==public));body.pop('consensus_invites',None)
        role=config.get('node_role','producer')
        body.update(node_role=role,schema='gg.lan-dag.invite.v6' if role=='light' else 'gg.lan-dag.invite.v4')
        if invites:body.update(schema='gg.lan-dag.invite.v5',consensus_invites=invites)
        result=_signed(identity,_INVITE,body);validate_invite(result)
        return result


def prepare(peer,invites,*,label='GG segmented LAN'):
    """Prepare the coordinator-signed target; no bind/backup/start/network send."""
    with peer._configuration,peer._lock:
        if peer._profile is None or peer._cancel.is_set() or peer.public_key!=peer._trusted:
            raise ValueError('GG_NETWORK_TRANSITION_OWNED_COORDINATOR_REQUIRED')
        return prepare_from_profile(peer._profile,invites,label=label)


def prepare_from_profile(owner,invites,*,label='GG segmented LAN'):
    from backend.gg_lan_dag import _signed,validate_invite
    from backend.gg_consensus_membership import make_membership
    from backend.gg_dag_segmented_session import make_bundle
    import secrets
    if not isinstance(owner,store.NodeProfile):raise ValueError('GG_NETWORK_TRANSITION_OWNED_LEGACY_REQUIRED')
    with owner._lock:
        config,session,identity=_owned_context(owner);public=config['public_keys'][0]
        if public!=config['trusted_coordinator']:raise ValueError('GG_NETWORK_TRANSITION_OWNED_COORDINATOR_REQUIRED')
        if not isinstance(invites,list) or len(invites)!=3:raise ValueError('GG_NETWORK_TRANSITION_INVITES')
        owners={value['peer_key']:value for value in map(validate_invite,invites)}
        membership=[value for invite in invites for value in invite['body'].get('consensus_invites',[])]
        forbidden=[*owners,*[key for value in owners.values() for key in value['producer_keys']]]
        committee=make_membership(membership,owners=owners,forbidden_keys=forbidden)
        bundle=make_bundle(identity,invites,committee,label=label,network_nonce=secrets.token_hex(32))
        old=anchor_from_bundle(session,public);new=validate_bundle(bundle,public)
        document=_signed(identity,DOMAIN,{'schema':SCHEMA,'from_native_genesis_hash':old['genesis_hash'],
            'to_native_genesis_hash':new['anchor']['genesis_hash'],'bundle':bundle})
        contract(owner,document);return document


def validate_pending(profile):
    record=profile._meta.get('network_transition_pending')
    if record is None:return None
    if (not isinstance(record,dict) or not {'schema','document','origin_head'}<=set(record)
            or set(record)-{'schema','document','origin_head','archive_sha256'} or record['schema']!=PENDING
            or 'network_transition' in profile._meta):raise ValueError('GG_NETWORK_TRANSITION_PENDING')
    checked=contract(profile,record['document']);origin=record['origin_head']
    metadata={name:value for name,value in profile._meta.items() if name!='network_transition_pending'}
    binding=hashlib.sha256(b'GG-NODE-METADATA-v1\0'+store.pack(metadata)).hexdigest()
    expected={'schema':'gg.node.durable-head.v1','binding':binding,**profile._head}
    if (not isinstance(origin,dict) or set(origin)!={'body','signature'} or store.pack(origin['body'])!=store.pack(expected)
            or type(origin['signature']) is not str or len(origin['signature'])!=128):raise ValueError('GG_NETWORK_TRANSITION_ORIGIN')
    verify_signature(bytes.fromhex(profile.descriptor()['public_keys'][0]),store.HEAD_DOMAIN+store.pack(expected),bytes.fromhex(origin['signature']))
    if 'archive_sha256' in record and (type(record['archive_sha256']) is not str or not store.HEX.fullmatch(record['archive_sha256'])):
        raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_PIN')
    return checked


def archive_path(profile,document):
    body,_=_target(document,profile.descriptor()['trusted_coordinator'])
    return profile.root/'network-history'/(body['from_native_genesis_hash']+'.sqlite3')


def validate_completed(profile,*,check=None,tools=None):
    record=profile._meta.get('network_transition')
    if record is None:return None
    from backend.gg_network_archive import inspect
    if (not isinstance(record,dict) or set(record)!={'schema','document','origin_head','archive_sha256'}
            or record['schema']!=COMPLETE or 'network_transition_pending' in profile._meta):raise ValueError('GG_NETWORK_TRANSITION_RECORD')
    config=profile.descriptor();body,target=_target(record['document'],config['trusted_coordinator'])
    if profile.session()!=body['bundle']:raise ValueError('GG_NETWORK_TRANSITION_TARGET')
    own=next((row['invite'] for row in target['roster'] if row['invite']['body']['peer_key']==config['public_keys'][0]),None)
    if own is None or own['body']['producer_keys']!=config['public_keys'][1:] or own['body']['nonce']!=config['pair_nonce']:
        raise ValueError('GG_NETWORK_TRANSITION_OWNER_IDENTITY')
    receipt=inspect(archive_path(profile,record['document']),config['public_keys'][0],record['archive_sha256'],check=check,tools=tools)
    if (store.pack(receipt['original_head'])!=store.pack(record['origin_head']) or receipt['native_genesis_hash']!=body['from_native_genesis_hash']
            or receipt['transition_document_sha256']!=hashlib.sha256(store.pack(record['document'])).hexdigest()):
        raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_CONTEXT')
    return receipt


def _file_pin(path,check):
    from backend.gg_network_archive import _checked_file,_hash_file
    _,descriptor,_=_checked_file(path)
    try:return _hash_file(descriptor,check)
    finally:os.close(descriptor)


def _stage_archive(profile,path,check,barrier):
    """Only the protected pending intent owns these disposable staging files.

    A completed archive and the authoritative active DB are never removed or
    repaired. An interrupted new backup can be recreated from the intact DB.
    """
    from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory
    directory=path.parent
    if any(is_link(part) for part in (directory,*directory.parents)):raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_PATH')
    if not directory.exists():directory.mkdir(mode=0o700);set_private_mode(directory,0o700)
    store._private_path(directory,0o700)
    partial=path.with_suffix('.partial');journal=Path(str(partial)+'-journal')
    if any(value.name not in {path.name,partial.name,journal.name} for value in directory.iterdir()):
        raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_INVENTORY')
    if path.exists():return
    for staging in (journal,partial):
        if staging.exists() or is_link(staging):
            store._private_path(staging,0o600);info=staging.lstat()
            if is_link(staging) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>1024**3:
                raise ValueError('GG_NETWORK_TRANSITION_STAGING')
            staging.unlink()
    check();descriptor=secure_open(partial,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
    set_private_mode(partial,0o600);target=None
    try:
        target=sqlite3.connect(partial.as_uri()+'?mode=rw',uri=True,isolation_level=None)
        target.execute('PRAGMA trusted_schema=OFF');target.execute('PRAGMA cache_size=-4096');target.execute('PRAGMA synchronous=EXTRA')
        def progress(status,remaining,total):
            check()
            if total>262144:raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_LIMIT')
            barrier('BACKUP_PAGE')
        profile._db.backup(target,pages=64,progress=progress,sleep=0)
    finally:
        if target is not None:target.close()
    descriptor=secure_open(partial,os.O_RDWR,0o600)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    check();barrier('BACKUP_SYNCED')
    if path.exists() or is_link(path):raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_EXISTS')
    os.rename(partial,path);sync_directory(directory);barrier('ARCHIVE_PUBLISHED')


def _new_descriptor(profile,checked):
    config=profile.descriptor();body=checked['own_invite']['body'];invites=body.get('consensus_invites',[])
    if invites:config['validator_invites']=deepcopy(invites)
    else:config.pop('validator_invites',None)
    if config['bootstrap'] is not None:
        coordinator=config['trusted_coordinator']
        config['bootstrap']['coordinator_invite']=deepcopy(next(row['invite'] for row in checked['target']['roster'] if row['invite']['body']['peer_key']==coordinator))
    store.NodeProfile._validate_descriptor(config);return config


def _receipt(record,archived,state):
    body=record['document']['body']
    return {'schema':'gg.node.network-transition-result.v1','state':state,
        'from_native_genesis_hash':body['from_native_genesis_hash'],'to_native_genesis_hash':body['to_native_genesis_hash'],
        'archived_original_records':archived['original_records'],'archived_admitted_transactions':archived['original_admitted_transactions'],
        'archived_SDK_certificates_verified':archived['stored_SDK_certificates_verified'],
        'old_network_domains_preserved':True,'protected_owner_keys_preserved':True,'new_journal_initialized_empty':True,
        'old_validator_profiles_changed':False,'native_transfer_history_replayed':False,
        'complete_canonical_history_replayed':False,'signers_duplicated':False,'network_started':False}


def transition(name,document,*,check=None,tools=None,timeout=1800,_barrier=None):
    """Finite stopped-profile action; exclusive lease spans every backup/commit.

    No caller can provide an already-open live profile, signer or trusted flag.
    Unknown commit acknowledgements close/poison the handle; the next owned open
    resolves the actual old/pending/new atomic state before any signing.
    """
    from backend.gg_network_archive import inspect
    if type(timeout) not in (int,float) or not 1<=timeout<=1800:raise ValueError('GG_NETWORK_TRANSITION_TIMEOUT')
    if check is not None and not callable(check):raise ValueError('GG_NETWORK_TRANSITION_CHECK')
    if _barrier is not None and not callable(_barrier):raise ValueError('GG_NETWORK_TRANSITION_CHECK')
    deadline=time.monotonic()+timeout
    def permitted():
        if time.monotonic()>=deadline:raise ValueError('GG_NETWORK_TRANSITION_TIMEOUT')
        if check is not None:check()
    barrier=_barrier or (lambda phase:None);permitted()
    profile=store.NodeProfile.open(name,check=permitted,migrate=False)
    try:
        _target(document,profile.descriptor()['trusted_coordinator'])
        completed=profile._meta.get('network_transition')
        if completed is not None:
            if store.pack(completed['document'])!=store.pack(document):raise ValueError('GG_NETWORK_TRANSITION_TARGET_DRIFT')
            archived=validate_completed(profile,check=permitted,tools=tools)
            return _receipt(completed,archived,'ALREADY_COMPLETE')
        checked=contract(profile,document);owner=profile.descriptor()['public_keys'][0]
        if store.pack(profile._meta.get('network_transition_pending',{}).get('document',document))!=store.pack(document):
            raise ValueError('GG_NETWORK_TRANSITION_TARGET_DRIFT')
        # Complete original admission and native certificate verification before
        # the first transition write, rather than trusting the signed DB seal.
        source=profile.root/'node.sqlite3'
        preflight=inspect(source,owner,_file_pin(source,permitted),check=permitted,tools=tools)
        permitted();barrier('PREFLIGHT_VERIFIED')
        pending=profile._meta.get('network_transition_pending')
        if pending is None:
            pending={'schema':PENDING,'document':deepcopy(document),'origin_head':preflight['original_head']}
            def begin():profile._meta['network_transition_pending']=deepcopy(pending);profile._put('network_transition_pending',pending)
            profile._write(begin)
        validate_pending(profile);permitted();barrier('INTENT_COMMITTED')
        path=archive_path(profile,document);_stage_archive(profile,path,permitted,barrier)
        pin=_file_pin(path,permitted)
        if pending.get('archive_sha256',pin)!=pin:raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_PIN')
        archived=inspect(path,owner,pin,check=permitted,tools=tools)
        if (store.pack(archived['original_head'])!=store.pack(pending['origin_head']) or archived['native_genesis_hash']!=checked['old_anchor']['genesis_hash']
                or archived['transition_document_sha256']!=hashlib.sha256(store.pack(document)).hexdigest()):
            raise ValueError('GG_NETWORK_TRANSITION_ARCHIVE_CONTEXT')
        permitted();barrier('ARCHIVE_VERIFIED')
        if 'archive_sha256' not in pending:
            pending={**pending,'archive_sha256':pin}
            def pin_archive():profile._meta['network_transition_pending']=deepcopy(pending);profile._put('network_transition_pending',pending)
            profile._write(pin_archive)
        barrier('ARCHIVE_PIN_COMMITTED');permitted()
        record={'schema':COMPLETE,'document':deepcopy(document),'origin_head':deepcopy(pending['origin_head']),'archive_sha256':pin}
        metadata={'descriptor':_new_descriptor(profile,checked),'protected_keys':deepcopy(profile._meta['protected_keys']),
            'session':deepcopy(checked['document']['body']['bundle']),'cursors':{},'fault':'','controls':{'dag':[],'circle':[]},'network_transition':record}
        def commit():
            profile._db.execute('DELETE FROM entries');profile._db.execute('DELETE FROM orders');profile._db.execute('DELETE FROM peer_scans')
            profile._db.execute('DELETE FROM metadata');profile._meta=metadata
            profile._head={'entries':0,'digest':store.EMPTY,'bytes':0,'counts':{'dag':0,'token':0}}
            for key,value in metadata.items():profile._put(key,value)
            permitted();barrier('BEFORE_FINAL_COMMIT')
        profile._write(commit);barrier('FINAL_COMMITTED')
        return _receipt(record,archived,'NETWORK_TRANSITION_COMPLETE')
    except (OSError,sqlite3.Error):raise ValueError('GG_NETWORK_TRANSITION_STORAGE') from None
    finally:profile.close()
