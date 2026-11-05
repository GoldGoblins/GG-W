"""Public, read-only original replay for a pinned legacy network journal.

This reader never decrypts keys, returns a writable profile or reclassifies old
source1 originals as source2. A caller's pin must come from protected ownership;
a self-reported file hash is not network authority or an external rollback floor.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

from backend import gg_consensus as native,gg_node_store as store
from backend.gg_consensus_membership import anchor_from_bundle
from backend.gg_dag_hardware import WorkGovernor,hardware_info
from backend.gg_ed25519 import verify_signature,require_public_key
from backend.gg_parallel_dag import ParallelDag
from backend.platform_files import is_link,secure_open

MAX_FILE=1024**3
SCHEMA='gg.node.network-archive-replay.v1'
SCOPE='ORIGINAL_LEGACY_DAG_ADMISSION_AND_STORED_SDK_CERTIFICATES_NOT_COMPLETE_CANONICAL_REPLAY_OR_NETWORK_FRESHNESS'


def _hash_file(descriptor,check):
    os.lseek(descriptor,0,os.SEEK_SET);digest=hashlib.sha256()
    while True:
        check();raw=os.read(descriptor,1024**2)
        if not raw:break
        digest.update(raw)
    return digest.hexdigest()


def _checked_file(path):
    path=Path(path).absolute()
    if str(path).startswith(('\\\\','//')) or any(is_link(part) for part in (path,*path.parents)):
        raise ValueError('GG_NETWORK_ARCHIVE_PATH')
    store._private_path(path.parent,0o700);store._private_path(path,0o600)
    descriptor=secure_open(path,os.O_RDONLY,0o600)
    try:
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=MAX_FILE:
            raise ValueError('GG_NETWORK_ARCHIVE_FILE')
        # Keep this exact checked file handle through both pin checks. The
        # profile owner controls archive publication; no writer mutates a
        # completed archive. A Windows CRT byte lock here would also prevent
        # SQLite's separate read handle from reading its own database header.
        return path,descriptor,info
    except BaseException:os.close(descriptor);raise


def _public_profile(database,root,owner):
    """Reuse public store validation, with no acquire/decrypt/write operation."""
    database.execute('PRAGMA trusted_schema=OFF');database.execute('PRAGMA query_only=ON')
    database.execute('PRAGMA temp_store=MEMORY');database.execute('PRAGMA cache_size=-4096')
    if (database.execute('PRAGMA application_id').fetchone()!=(store.APPLICATION_ID,)
            or database.execute('PRAGMA user_version').fetchone()!=(3,)
            or dict(database.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))!=store.SCHEMA
            or database.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()!=(0,)):
        raise ValueError('GG_NETWORK_ARCHIVE_SCHEMA')
    if database.execute('PRAGMA quick_check(1)').fetchone()!=('ok',):raise ValueError('GG_NETWORK_ARCHIVE_CORRUPT')
    rows=list(database.execute('SELECT name,length(value),typeof(value) FROM metadata'))
    limits={**store.META_LIMITS,**store.OPTIONAL_META_LIMITS};names={row[0] for row in rows}
    if (not set(store.META_LIMITS)<=names or names-set(limits)
            or any(row[2]!='blob' or not 0<row[1]<=limits.get(row[0],0) for row in rows)):
        raise ValueError('GG_NETWORK_ARCHIVE_METADATA')
    encoded={name:bytes(database.execute('SELECT value FROM metadata WHERE name=?',(name,)).fetchone()[0]) for name in names}
    descriptor=store.unpack(encoded['descriptor']);store.NodeProfile._validate_descriptor(descriptor)
    if descriptor['public_keys'][0]!=owner:raise ValueError('GG_NETWORK_ARCHIVE_OWNER')
    envelope=store.unpack(encoded['head'])
    if not isinstance(envelope,dict) or set(envelope)!={'body','signature'}:raise ValueError('GG_NETWORK_ARCHIVE_HEAD')
    head=envelope['body']
    if (not isinstance(head,dict) or set(head)!={'schema','binding','entries','digest','bytes','counts'}
            or head['schema']!='gg.node.durable-head.v1' or head['binding']!=store._raw_metadata_binding(encoded)
            or not store._number(head['entries'],store.MAX_ENTRIES) or not store._number(head['bytes'],store.MAX_BYTES)
            or type(head['digest']) is not str or not store.HEX.fullmatch(head['digest'])
            or not isinstance(head['counts'],dict) or set(head['counts'])!={'dag','token'}
            or any(not store._number(value,4096) for value in head['counts'].values())
            or type(envelope['signature']) is not str or len(envelope['signature'])!=128):
        raise ValueError('GG_NETWORK_ARCHIVE_HEAD')
    verify_signature(bytes.fromhex(owner),store.HEAD_DOMAIN+store.pack(head),bytes.fromhex(envelope['signature']))
    meta={name:store.unpack(raw) for name,raw in encoded.items() if name!='head'}
    protected=meta['protected_keys']
    if (not isinstance(protected,list) or len(protected)!=3 or any(
            not isinstance(row,dict) or set(row)!={'public','ciphertext'} or row['public']!=public or type(row['ciphertext']) is not str
            for row,public in zip(protected,descriptor['public_keys']))):raise ValueError('GG_NETWORK_ARCHIVE_KEY_ENVELOPE')
    if (meta['fault'] not in store.FAULTS or not isinstance(meta['cursors'],dict) or len(meta['cursors'])>2
            or any(type(key) is not str or not store.HEX.fullmatch(key) or not store._number(value,4095) for key,value in meta['cursors'].items())
            or not isinstance(meta['controls'],dict) or set(meta['controls'])!={'dag','circle'} or any(
                not isinstance(ids,list) or len(ids)>4096 or any(type(value) is not str or not store.HEX.fullmatch(value) for value in ids)
                or len(ids)!=len(set(ids)) for ids in meta['controls'].values())):raise ValueError('GG_NETWORK_ARCHIVE_METADATA')
    if meta['fault']:raise ValueError('GG_NETWORK_ARCHIVE_FAULT')
    if 'segmented_producer' in meta:raise ValueError('GG_NETWORK_ARCHIVE_LEGACY_REQUIRED')
    view=store.NodeProfile('ArchiveView');view.root=root;view._db=database;view._meta=meta
    view._head={key:deepcopy(head[key]) for key in ('entries','digest','bytes','counts')}
    return view,envelope


def inspect(path,owner,expected_hash,*,check=None,governor=None,tools=None):
    """Replay exact original admission and verify every stored certificate.

    `tools` is a source-matched native-verifier location, never a peer-provided
    executable. No stored certificate is accepted on structural validation alone.
    Empty certificate collections explicitly make no SDK selection assertion.
    """
    if type(owner) is not str or not store.HEX.fullmatch(owner):raise ValueError('GG_NETWORK_ARCHIVE_OWNER')
    require_public_key(bytes.fromhex(owner))
    if type(expected_hash) is not str or not store.HEX.fullmatch(expected_hash):raise ValueError('GG_NETWORK_ARCHIVE_PIN')
    if check is not None and not callable(check):raise ValueError('GG_NETWORK_ARCHIVE_CHECK')
    check=check or (lambda:None);check()
    if governor is not None and not isinstance(governor,WorkGovernor):raise ValueError('GG_DAG_RESOURCE_BUDGET')
    path,descriptor,identity=_checked_file(path);database=None;engine=None;view=None
    try:
        if _hash_file(descriptor,check)!=expected_hash:raise ValueError('GG_NETWORK_ARCHIVE_HASH')
        database=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,isolation_level=None)
        view,envelope=_public_profile(database,path.parent,owner);session=view.session();config=view.descriptor()
        pending=view._meta.get('network_transition_pending')
        if pending is not None:
            from backend.gg_network_transition import validate_pending
            validate_pending(view)
        if 'network_transition' in view._meta:raise ValueError('GG_NETWORK_ARCHIVE_LEGACY_REQUIRED')
        if not isinstance(session,dict) or session.get('body',{}).get('schema')!='gg.lan-dag.session.v4':raise ValueError('GG_NETWORK_ARCHIVE_LEGACY_REQUIRED')
        anchor=anchor_from_bundle(session,config['trusted_coordinator']);source=anchor['genesis']['dag']
        own=[row for row in session['body']['roster'] if row['invite']['body']['peer_key']==owner]
        if (len(own)!=1 or own[0]['invite']['body']['producer_keys']!=config['public_keys'][1:]
                or own[0]['invite']['body']['nonce']!=config['pair_nonce']
                or own[0]['invite']['body'].get('node_role','producer')!=config.get('node_role','producer')):
            raise ValueError('GG_NETWORK_ARCHIVE_IDENTITY')
        engine=ParallelDag.from_public_genesis(session['body']['public_genesis']);engine.configure_lan_roles(source['allowed_producers'])
        engine.configure_lan_capacity(block_bytes=store.MAX_WIRE,session_bytes=store.MAX_BYTES);engine.configure_owned_ingress()
        engine.configure_payload_archive(view.read_dag,hot_bytes=0);engine.begin_history_replay()
        governor=governor or WorkGovernor(info=hardware_info(),stored_bytes=engine.memory_basis_bytes)
        if governor.memory_headroom() is None:raise ValueError('GG_DAG_RESOURCE_NEEDS_MEMORY_MEASUREMENT')
        def permitted():check();governor.check_cpu()
        rows=list(database.execute('SELECT position,kind,length(wire),typeof(wire),wire_hash FROM entries ORDER BY position LIMIT ?',(store.MAX_ENTRIES+1,)))
        if len(rows)>store.MAX_ENTRIES:raise ValueError('GG_NETWORK_ARCHIVE_LIMIT')
        actual={'entries':0,'digest':store.EMPTY,'bytes':0,'counts':{'dag':0,'token':0}}
        for position,kind,length,wire_type,wire_hash in rows:
            permitted()
            if (position!=actual['entries']+1 or kind!='dag' or wire_type!='blob' or type(length) is not int
                    or not 0<length<=store.MAX_WIRE):raise ValueError('GG_NETWORK_ARCHIVE_RECORD')
            with governor.reserve_memory(length*16):
                raw=bytes(database.execute('SELECT wire FROM entries WHERE position=?',(position,)).fetchone()[0])
                if hashlib.sha256(b'dag'+raw).hexdigest()!=wire_hash:raise ValueError('GG_NETWORK_ARCHIVE_RECORD')
                store.NodeProfile._advance(actual,kind,raw);admitted=engine.admit_relayed(raw,0,check=permitted)
                if admitted['state']!='ADMITTED_UNFINALIZED':raise ValueError('GG_NETWORK_ARCHIVE_ADMISSION')
                identifier=admitted['hash'];view._dag_bodies.add(identifier);view._dag_index[identifier]=(position,wire_hash,length)
        if actual!=view._head:raise ValueError('GG_NETWORK_ARCHIVE_HISTORY')
        if config.get('node_role')=='light' and actual['entries']:raise ValueError('GG_NODE_LIGHT_GLOBAL_HISTORY_FORBIDDEN')
        engine.finish_history_replay();view._load_peer_scans();view._load_order_index()
        certificates=[];shared=view._meta.get('consensus')
        if shared is not None:
            view._consensus_tip(shared)
            if shared['fault']:raise ValueError('GG_NETWORK_ARCHIVE_CONFLICT')
            certificates.append(shared['packet'])
        ordered=view._meta.get('order_index')
        if ordered is not None:certificates.append(ordered['packet'])
        verified=set()
        if certificates:
            directory=native.TOOLS if tools is None else Path(tools);binary=native._installed_binary(directory);stamp=native._validate_binary_at(directory,binary)
            for packet in certificates:
                permitted()
                if {key:packet[key] for key in ('genesis','genesis_hash')}!=anchor:raise ValueError('GG_NETWORK_ARCHIVE_CERTIFICATE_PIN')
                identifier=hashlib.sha256(store.pack(packet)).hexdigest()
                if identifier not in verified:native._verify_public(packet,binary,stamp);verified.add(identifier)
        check()
        current=os.stat(path,follow_symlinks=False)
        if ((current.st_dev,current.st_ino,current.st_size)!=(identity.st_dev,identity.st_ino,identity.st_size)
                or current.st_nlink!=1 or _hash_file(descriptor,check)!=expected_hash):raise ValueError('GG_NETWORK_ARCHIVE_CHANGED')
        return {'schema':SCHEMA,'verification_scope':SCOPE,'archive_sha256':expected_hash,'owner_key':owner,
            'network_id':source['network_id'],'source_genesis_hash':source['genesis_hash'],'native_genesis_hash':anchor['genesis_hash'],
            'original_head':deepcopy(pending['origin_head'] if pending is not None else envelope),'storage_head':deepcopy(envelope),
            'transition_document_sha256':hashlib.sha256(store.pack(pending['document'])).hexdigest() if pending is not None else None,
            'original_records':actual['counts']['dag'],'original_raw_bytes':actual['bytes'],
            'original_admitted_transactions':sum(row['transaction_count'] for row in engine._records.values()),
            'original_DAG_admission_replayed':True,'stored_SDK_certificates_verified':len(verified),
            'complete_canonical_history_replayed':False,'native_transfer_history_replayed':False,
            'network_freshness_asserted':False,'signers_opened':False,'writes_performed':False}
    except (sqlite3.Error,OSError):raise ValueError('GG_NETWORK_ARCHIVE_UNAVAILABLE') from None
    finally:
        if engine is not None:engine.stop()
        if view is not None:view.close();database=None
        if database is not None:database.close()
        os.close(descriptor)
