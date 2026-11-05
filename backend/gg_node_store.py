"""Explicit owned node profiles and signed, bounded durable admission journals.

Only encrypted key bytes enter SQLite. Validated public records and their
signed integrity head commit in one synchronous transaction BEFORE exposure
to gossip. Recovery verifies the complete journal and replays protocol checks;
it never repairs, truncates or silently replaces an existing profile.

This protects process-crash recovery and detects altered/partial state. A whole
older valid disk image still requires an external trusted checkpoint to detect.
No local journal is a canonical financial-finality certificate.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading

from backend.application_paths import DATA_HOME
from backend.gg_ed25519 import Keypair,SIGNATURE_PROFILE,require_public_key,verify_signature
from backend.platform_files import is_link,mode_matches,owned_by_current_user,secure_open,set_private_mode,sync_directory
from backend.platform_support import file_locks
from backend import gg_node_vault as vault
from backend import gg_peer_scan as peer_scan

def default_root(data_home):
    # OS/user data roots may themselves be aliases (including Android's
    # /data/data). Resolve that trusted anchor once; links inside the private
    # application/profile subtree are still rejected by profile_path/_acquire.
    return Path(data_home).expanduser().resolve()/'goldgoblins/dag-nodes'


ROOT=default_root(DATA_HOME)
NAME=re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,31}$')
HEX=re.compile(r'^[0-9a-f]{64}$')
MAX_WIRE=32*1024*1024
MAX_BYTES=512*1024*1024
MAX_ENTRIES=8191
APPLICATION_ID=0x47474E31
ROLES=('transport','producer0','producer1')
FAULTS=('', 'GG_DAG_PRODUCER_EQUIVOCATION')
HEAD_DOMAIN=b'GG-NODE-DURABLE-HEAD-v1\0'
EMPTY=hashlib.sha256(b'GG-NODE-JOURNAL-v1\0').hexdigest()
SCHEMA={
 'metadata':"CREATE TABLE metadata(name TEXT PRIMARY KEY,value BLOB NOT NULL CHECK(typeof(value)='blob')) WITHOUT ROWID",
 'entries':"CREATE TABLE entries(position INTEGER PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('dag','token')),wire BLOB NOT NULL CHECK(typeof(wire)='blob'),wire_hash TEXT NOT NULL UNIQUE)"
}
LEGACY_SCHEMA=dict(SCHEMA)
SCHEMA['peer_scans']="CREATE TABLE peer_scans(peer TEXT NOT NULL,sequence INTEGER NOT NULL,event BLOB NOT NULL CHECK(typeof(event)='blob'),PRIMARY KEY(peer,sequence)) WITHOUT ROWID"
SCHEMA_V2=dict(SCHEMA)
SCHEMA['orders']="CREATE TABLE orders(position INTEGER PRIMARY KEY,leaf BLOB NOT NULL CHECK(typeof(leaf)='blob'),hash TEXT NOT NULL UNIQUE)"
SCHEMA_V4=dict(SCHEMA)
SCHEMA_V4['own_proposals']="CREATE TABLE own_proposals(position INTEGER PRIMARY KEY,producer INTEGER NOT NULL,sequence INTEGER NOT NULL,identifier TEXT NOT NULL UNIQUE,wire_hash TEXT NOT NULL,wire BLOB NOT NULL CHECK(typeof(wire)='blob'),UNIQUE(producer,sequence))"
SCHEMA_V5=dict(SCHEMA)
SCHEMA_V5['financial_contexts']="CREATE TABLE financial_contexts(identifier TEXT PRIMARY KEY,packet BLOB NOT NULL CHECK(typeof(packet)='blob')) WITHOUT ROWID"
SCHEMA_V5['financial_proposals']="CREATE TABLE financial_proposals(position INTEGER PRIMARY KEY,producer INTEGER NOT NULL,epoch INTEGER NOT NULL,sequence INTEGER NOT NULL,identifier TEXT NOT NULL UNIQUE,context_hash TEXT NOT NULL,wire_hash TEXT NOT NULL,wire BLOB NOT NULL CHECK(typeof(wire)='blob'),UNIQUE(producer,epoch,sequence))"
SCHEMA_V6=dict(SCHEMA_V5)
SCHEMA_V6['financial_archives']="CREATE TABLE financial_archives(number INTEGER PRIMARY KEY,identifier TEXT NOT NULL UNIQUE)"
SCHEMA_V6['financial_archived']="CREATE TABLE financial_archived(position INTEGER PRIMARY KEY,producer INTEGER NOT NULL,epoch INTEGER NOT NULL,sequence INTEGER NOT NULL,identifier TEXT NOT NULL UNIQUE,context_hash TEXT NOT NULL,wire_hash TEXT NOT NULL,wire_bytes INTEGER NOT NULL,archive TEXT NOT NULL,wire_offset INTEGER NOT NULL,context_offset INTEGER NOT NULL,context_bytes INTEGER NOT NULL,rank INTEGER NOT NULL,parent TEXT NOT NULL,UNIQUE(producer,epoch,sequence))"
SCHEMA_V7=dict(SCHEMA)
SCHEMA_V7['protocol_contexts']="CREATE TABLE protocol_contexts(identifier TEXT PRIMARY KEY,packet BLOB NOT NULL CHECK(typeof(packet)='blob')) WITHOUT ROWID"
SCHEMA_V7['protocol_cores']="CREATE TABLE protocol_cores(position INTEGER PRIMARY KEY,producer TEXT NOT NULL,epoch INTEGER NOT NULL,sequence INTEGER NOT NULL,identifier TEXT NOT NULL UNIQUE,context_hash TEXT NOT NULL,wire_hash TEXT NOT NULL,wire_bytes INTEGER NOT NULL,rank INTEGER NOT NULL,parent TEXT NOT NULL,core BLOB CHECK(core IS NULL OR typeof(core)='blob'),UNIQUE(producer,sequence))"
SCHEMA_V7['protocol_work']="CREATE TABLE protocol_work(identifier TEXT PRIMARY KEY,packet BLOB NOT NULL CHECK(typeof(packet)='blob'),wire BLOB NOT NULL CHECK(typeof(wire)='blob')) WITHOUT ROWID"
PROTOCOL_ACTIVE_INDEX="CREATE INDEX protocol_active ON protocol_cores(producer,sequence) WHERE core IS NOT NULL"
META_LIMITS={'descriptor':48*1024,'protected_keys':16384,'session':256*1024,'cursors':1024,'fault':128,'controls':600*1024,'head':4096}
OPTIONAL_META_LIMITS={'consensus':544*1024,'peer_scans':8*1024,'order_index':272*1024,'segmented_producer':2*1024*1024,
    'financial_producer':2*1024*1024,
    'protocol_producer':2*1024*1024,
    'network_transition_pending':384*1024,'network_transition':384*1024}


def pack(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def unpack(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('GG_NODE_STORE_ENCODING')
            result[key]=value
        return result
    try:
        value=json.loads(raw,object_pairs_hook=unique)
        if pack(value)!=raw:raise ValueError('GG_NODE_STORE_ENCODING')
        return value
    except (ValueError,TypeError,UnicodeError,RecursionError):raise ValueError('GG_NODE_STORE_ENCODING') from None


def _number(value,maximum):
    return type(value) is int and 0<=value<=maximum


def _raw_metadata_binding(values):
    """Same canonical metadata digest, before decoding large private values."""
    digest=hashlib.sha256(b'GG-NODE-METADATA-v1\0{')
    for index,name in enumerate(sorted(key for key in values if key!='head')):
        if index:digest.update(b',')
        digest.update(pack(name));digest.update(b':');digest.update(values[name])
    digest.update(b'}');return digest.hexdigest()


def _private_path(path,mode):
    if is_link(path) or not owned_by_current_user(path) or not mode_matches(path,mode):
        raise ValueError('GG_NODE_PROFILE_PATH')


def profile_path(name):
    if not isinstance(name,str) or NAME.fullmatch(name) is None:raise ValueError('GG_NODE_PROFILE_NAME')
    base=Path(ROOT).absolute()
    if str(base).startswith(('\\\\','//')) or any(is_link(p) for p in (base,*base.parents)):
        raise ValueError('GG_NODE_PROFILE_PATH')
    return base/name


class NodeProfile:
    def __init__(self,name):
        self.name=name;self.root=profile_path(name);self._lock=threading.RLock()
        self._lease=None;self._db=None;self._keys=[];self._meta={};self._head=None
        self._failed=False;self._closed=False;self._restored=False
        self._schema_version=3;self._scan_states={};self._dag_bodies=set();self._dag_index={};self._durable_order=None
        self._segmented_writer=None

    def __repr__(self):return '<GG protected node profile>'

    @classmethod
    def create(cls,name,configuration):
        profile=cls(name)
        try:
            if vault.provider()=='SCRYPT_AES256_GCM':
                from backend.portable_wallet_vault import require_unlocked
                require_unlocked()  # No partial profile after a missing unlock.
            # The parent becomes private before any key/file is published.
            profile.root.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            set_private_mode(profile.root.parent,0o700);_private_path(profile.root.parent,0o700)
            try:profile.root.mkdir(mode=0o700)
            except FileExistsError:raise ValueError('GG_NODE_PROFILE_EXISTS_USE_RESUME') from None
            set_private_mode(profile.root,0o700);profile._acquire(create=True)
            profile._keys=[Keypair() for _ in ROLES]
            descriptor=deepcopy(configuration)
            descriptor.setdefault('bootstrap',None)
            descriptor.setdefault('node_role','producer')
            descriptor.update(schema='gg.node.profile.v1',signature_profile=SIGNATURE_PROFILE,
                public_keys=[key.pubkey().hex() for key in profile._keys],pair_nonce=secrets.token_hex(32),key_storage=vault.provider())
            if descriptor.get('trusted_coordinator') is None:descriptor['trusted_coordinator']=descriptor['public_keys'][0]
            profile._validate_descriptor(descriptor)
            protected=[]
            for role,key in zip(ROLES,profile._keys):
                public=key.pubkey().hex()
                cipher=vault.crypt(bytes(key),public,role,profile.root,storage=descriptor['key_storage'])
                protected.append({'public':public,'ciphertext':base64.b64encode(cipher).decode('ascii')})
            profile._meta={'descriptor':descriptor,'protected_keys':protected,'session':None,'cursors':{},'fault':'','controls':{'dag':[],'circle':[]}}
            profile._connect(create=True)
            profile._db.execute('BEGIN IMMEDIATE')
            for sql in SCHEMA.values():profile._db.execute(sql)
            for key,value in profile._meta.items():profile._put(key,value)
            profile._head={'entries':0,'digest':EMPTY,'bytes':0,'counts':{'dag':0,'token':0}}
            profile._seal();profile._commit()
            sync_directory(profile.root)
            return profile
        except BaseException:
            profile.close();raise

    @classmethod
    def open(cls,name,*,check=None,migrate=True):
        profile=cls(name)
        try:
            if check is not None and not callable(check):raise ValueError('GG_NODE_RECOVERY_CHECK')
            permitted=check if check is not None else lambda:None
            permitted()
            profile._acquire(create=False);profile._connect(create=False)
            if type(migrate) is not bool or not migrate and profile._schema_version<3:
                raise ValueError('GG_NODE_STORE_EXPLICIT_SCHEMA_UPGRADE_REQUIRED')
            expected={1:LEGACY_SCHEMA,2:SCHEMA_V2,3:SCHEMA,4:SCHEMA_V4,5:SCHEMA_V5,6:SCHEMA_V6,7:SCHEMA_V7}[profile._schema_version]
            if (dict(profile._db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))!=expected
                    or profile._db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]):
                raise ValueError('GG_NODE_STORE_SCHEMA')
            if profile._db.execute('PRAGMA quick_check(1)').fetchone()!=('ok',):raise ValueError('GG_NODE_STORE_CORRUPT')
            rows=list(profile._db.execute('SELECT name,length(value),typeof(value) FROM metadata'))
            limits={**META_LIMITS,**OPTIONAL_META_LIMITS};names={row[0] for row in rows}
            if (not set(META_LIMITS)<=names or names-set(limits) or any(row[2]!='blob' or not 0<row[1]<=limits.get(row[0],0) for row in rows)):
                raise ValueError('GG_NODE_STORE_METADATA')
            encoded={key:bytes(profile._db.execute('SELECT value FROM metadata WHERE name=?',(key,)).fetchone()[0]) for key in names}
            values={key:unpack(encoded[key]) for key in ('descriptor','protected_keys','head')}
            profile._meta={key:value for key,value in values.items() if key!='head'}
            descriptor=profile._meta['descriptor'];profile._validate_descriptor(descriptor)
            protected=profile._meta['protected_keys']
            if not isinstance(protected,list) or len(protected)!=3:raise ValueError('GG_NODE_VAULT_INVALID')
            for role,public,row in zip(ROLES,descriptor['public_keys'],protected):
                if not isinstance(row,dict) or set(row)!={'public','ciphertext'} or row['public']!=public:
                    raise ValueError('GG_NODE_VAULT_INVALID')
                try:cipher=base64.b64decode(row['ciphertext'],validate=True)
                except (ValueError,TypeError):raise ValueError('GG_NODE_VAULT_INVALID') from None
                raw=vault.crypt(cipher,public,role,profile.root,decrypt=True,storage=descriptor['key_storage'])
                if len(raw)!=64 or raw[32:].hex()!=public:raise ValueError('GG_NODE_VAULT_INVALID')
                key=Keypair.from_seed(raw[:32]);del raw
                if key.pubkey().hex()!=public:raise ValueError('GG_NODE_VAULT_INVALID')
                profile._keys.append(key)
            envelope=values['head']
            if not isinstance(envelope,dict) or set(envelope)!={'body','signature'}:raise ValueError('GG_NODE_STORE_HEAD')
            head=envelope['body']
            if (not isinstance(head,dict) or set(head)!={'schema','binding','entries','digest','bytes','counts'}
                    or head['schema']!='gg.node.durable-head.v1' or head['binding']!=_raw_metadata_binding(encoded)
                    or not _number(head['entries'],MAX_ENTRIES) or not _number(head['bytes'],MAX_BYTES)
                    or not isinstance(head['digest'],str) or not HEX.fullmatch(head['digest'])
                    or not isinstance(head['counts'],dict) or set(head['counts'])!={'dag','token'}
                    or any(not _number(v,4096) for v in head['counts'].values())):raise ValueError('GG_NODE_STORE_HEAD')
            try:verify_signature(bytes.fromhex(descriptor['public_keys'][0]),HEAD_DOMAIN+pack(head),bytes.fromhex(envelope['signature']))
            except (ValueError,TypeError):raise ValueError('GG_NODE_STORE_HEAD') from None
            # Authenticate the raw metadata and its seal before parsing larger
            # session/proof collections. Recomputed unsigned bindings still fail.
            values.update({key:unpack(encoded[key]) for key in names-set(values)})
            profile._meta={key:value for key,value in values.items() if key!='head'}
            cursors=profile._meta['cursors'];session=profile._meta['session'];fault=profile._meta['fault']
            if (not isinstance(cursors,dict) or len(cursors)>2 or any(not isinstance(k,str) or not HEX.fullmatch(k) or not _number(v,4095) for k,v in cursors.items())
                    or session is not None and not isinstance(session,dict) or fault not in FAULTS):raise ValueError('GG_NODE_STORE_METADATA')
            controls=profile._meta['controls']
            if (not isinstance(controls,dict) or set(controls)!={'dag','circle'} or any(
                    not isinstance(ids,list) or len(ids)>4096 or any(not isinstance(v,str) or not HEX.fullmatch(v) for v in ids)
                    or len(ids)!=len(set(ids)) for ids in controls.values())):raise ValueError('GG_NODE_STORE_METADATA')
            profile._head={key:head[key] for key in ('entries','digest','bytes','counts')}
            actual={'entries':0,'digest':EMPTY,'bytes':0,'counts':{'dag':0,'token':0}}
            for position,(kind,wire) in enumerate(profile.records(),1):
                permitted()
                profile._advance(actual,kind,wire)
                if kind=='dag':
                    identifier=profile._dag_body_hash(wire)
                    if identifier is not None:
                        profile._dag_bodies.add(identifier)
                        profile._dag_index[identifier]=(position,hashlib.sha256(b'dag'+wire).hexdigest(),len(wire))
            if actual!=profile._head:raise ValueError('GG_NODE_STORE_HISTORY_MISMATCH')
            if session is None and actual['entries']:raise ValueError('GG_NODE_STORE_SESSION_REQUIRED')
            if 'consensus' in profile._meta:profile._consensus_tip(profile._meta['consensus'])
            if descriptor.get('node_role')=='light' and actual['entries']:raise ValueError('GG_NODE_LIGHT_GLOBAL_HISTORY_FORBIDDEN')
            if profile._schema_version>=2:profile._load_peer_scans()
            elif 'peer_scans' in profile._meta:raise ValueError('GG_NODE_PEER_SCAN_SCHEMA')
            if profile._schema_version<3:
                if 'order_index' in profile._meta:raise ValueError('GG_NODE_ORDER_CACHE_SCHEMA')
                def migrate():
                    if profile._schema_version==1:profile._db.execute(SCHEMA['peer_scans'])
                    profile._db.execute(SCHEMA['orders']);profile._db.execute('PRAGMA user_version=3')
                profile._write(migrate);profile._schema_version=3
            profile._load_order_index()
            if 'network_transition_pending' in profile._meta or 'network_transition' in profile._meta:
                from backend.gg_network_transition import validate_pending,validate_completed
                validate_pending(profile);validate_completed(profile,check=permitted)
            if profile._schema_version!=7 and 'protocol_producer' in profile._meta:raise ValueError('GG_PRODUCER_JOURNAL_VERSION')
            if profile._schema_version==4:
                if 'financial_producer' in profile._meta:raise ValueError('GG_PRODUCER_JOURNAL_VERSION')
                from backend.gg_dag_producer_journal import validate_stored_profile
                validate_stored_profile(profile,check=permitted)
            elif profile._schema_version in (5,6):
                if 'segmented_producer' in profile._meta:raise ValueError('GG_PRODUCER_JOURNAL_VERSION')
                from backend.gg_financial_producer import validate_stored_profile
                validate_stored_profile(profile,check=permitted)
            elif profile._schema_version==7:
                if 'segmented_producer' in profile._meta or 'financial_producer' in profile._meta:raise ValueError('GG_PRODUCER_JOURNAL_VERSION')
                if list(profile._db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"))!=[('protocol_active',PROTOCOL_ACTIVE_INDEX)]:raise ValueError('GG_PROTOCOL_ACTIVE_INDEX')
                from backend.gg_protocol_producer import validate_stored_profile
                validate_stored_profile(profile,check=permitted)
            elif 'segmented_producer' in profile._meta or 'financial_producer' in profile._meta or 'protocol_producer' in profile._meta:raise ValueError('GG_PRODUCER_JOURNAL_VERSION')
            profile._restored=True
            return profile
        except sqlite3.Error as error:
            profile.close()
            code=getattr(error,'sqlite_errorcode',0)&255
            raise ValueError('GG_NODE_PROFILE_IN_USE' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'GG_NODE_STORE_CORRUPT') from None
        except BaseException:
            profile.close();raise

    @staticmethod
    def _validate_descriptor(value):
        fields={'schema','signature_profile','public_keys','pair_nonce','key_storage','label','host','port','allowed_cidr','trusted_coordinator','allow_test_tokens','allow_dag_transactions','bootstrap'}
        if (not isinstance(value,dict) or not fields<=set(value) or set(value)-fields-{'node_role','validator_invites'} or value['schema']!='gg.node.profile.v1'
                or value.get('node_role','producer') not in ('producer','replica','light')
                or value['signature_profile']!=SIGNATURE_PROFILE or value['key_storage'] not in {'WINDOWS_DPAPI','SCRYPT_AES256_GCM'}
                or not isinstance(value['public_keys'],list) or len(value['public_keys'])!=3
                or any(not isinstance(key,str) for key in value['public_keys']) or len(set(value['public_keys']))!=3
                or value['bootstrap'] is not None and not isinstance(value['bootstrap'],dict)
                or not isinstance(value['pair_nonce'],str) or not HEX.fullmatch(value['pair_nonce'])
                or any(type(value[key]) is not bool for key in ('allow_test_tokens','allow_dag_transactions'))
                or not _number(value['port'],65535) or value['port'] and value['port']<1024):raise ValueError('GG_NODE_PROFILE_DESCRIPTOR')
        for public in [*value['public_keys'],value['trusted_coordinator']]:
            if not isinstance(public,str) or not HEX.fullmatch(public):raise ValueError('GG_NODE_PROFILE_DESCRIPTOR')
            require_public_key(bytes.fromhex(public))
        if value.get('node_role')=='light' and (value['allow_test_tokens'] or not value['allow_dag_transactions'] or value.get('validator_invites')):
            raise ValueError('GG_NODE_PROFILE_LIGHT_POLICY')
        # Network-address and label validation stays in the shared LAN API.
        if any(not isinstance(value[key],str) or not 1<=len(value[key])<=128 for key in ('label','host','allowed_cidr')):
            raise ValueError('GG_NODE_PROFILE_DESCRIPTOR')
        if 'validator_invites' in value:
            from backend.gg_consensus_membership import validate_invite
            invites=value['validator_invites']
            if not isinstance(invites,list) or not 1<=len(invites)<=4 or value['allow_dag_transactions'] is not True or value['allow_test_tokens'] is not False:
                raise ValueError('GG_NODE_PROFILE_VALIDATOR_INVITES')
            members=[validate_invite(invite) for invite in invites]
            keys=[row[name] for row in members for name in ('validator_key','node_key','account_key')]
            if (len(set(keys))!=len(keys) or set(keys)&set(value['public_keys'])
                    or any(row['owner_peer_key']!=value['public_keys'][0] or row['host']!=value['host'] or row['p2p_port']==value['port'] for row in members)
                    or len({row['p2p_port'] for row in members})!=len(members)):
                raise ValueError('GG_NODE_PROFILE_VALIDATOR_INVITES')

    def _acquire(self,*,create):
        if not self.root.is_dir() or any(is_link(p) for p in (self.root,*self.root.parents)):raise ValueError('GG_NODE_PROFILE_MISSING_OR_LINK')
        _private_path(self.root.parent,0o700);_private_path(self.root,0o700)
        path=self.root/'owner.lock'
        flags=os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0)
        try:self._lease=secure_open(path,flags,0o600)
        except FileNotFoundError:raise ValueError('GG_NODE_PROFILE_LOCK_MISSING') from None
        if create:
            os.write(self._lease,b'0');os.fsync(self._lease)
        _private_path(path,0o600)
        try:file_locks.flock(self._lease,file_locks.LOCK_EX|file_locks.LOCK_NB)
        except BlockingIOError:
            os.close(self._lease);self._lease=None;raise ValueError('GG_NODE_PROFILE_IN_USE') from None

    def _connect(self,*,create):
        path=self.root/'node.sqlite3'
        flags=os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0)
        try:descriptor=secure_open(path,flags,0o600)
        except FileNotFoundError:raise ValueError('GG_NODE_STORE_MISSING') from None
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>1024*1024*1024:raise ValueError('GG_NODE_STORE_FILE')
        finally:os.close(descriptor)
        _private_path(path,0o600)
        self._db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None,check_same_thread=False)
        self._db.execute('PRAGMA trusted_schema=OFF');self._db.execute('PRAGMA temp_store=MEMORY')
        self._db.execute('PRAGMA cache_size=-16384')
        if self._db.execute('PRAGMA journal_mode=DELETE').fetchone()!=('delete',):raise ValueError('GG_NODE_STORE_DURABILITY')
        self._db.execute('PRAGMA synchronous=EXTRA')
        if self._db.execute('PRAGMA synchronous').fetchone()!=(3,):raise ValueError('GG_NODE_STORE_DURABILITY')
        if self._db.execute('PRAGMA locking_mode=EXCLUSIVE').fetchone()!=('exclusive',):raise ValueError('GG_NODE_STORE_LOCKING')
        # Keep a second OS-backed ownership boundary on the database itself,
        # including between commits and throughout semantic recovery.
        self._db.execute('BEGIN EXCLUSIVE');self._db.execute('COMMIT')
        self._db.execute('PRAGMA max_page_count=262144')
        if create:
            self._db.execute('PRAGMA application_id='+str(APPLICATION_ID));self._db.execute('PRAGMA user_version=3')
        else:
            version=self._db.execute('PRAGMA user_version').fetchone()[0]
            if self._db.execute('PRAGMA application_id').fetchone()!=(APPLICATION_ID,) or version not in (1,2,3,4,5,6,7):raise ValueError('GG_NODE_STORE_VERSION')
            self._schema_version=version

    def _put(self,name,value):
        raw=pack(value)
        if len(raw)>{**META_LIMITS,**OPTIONAL_META_LIMITS}[name]:raise ValueError('GG_NODE_STORE_METADATA_SIZE')
        self._db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(name,raw))

    def _binding(self):return hashlib.sha256(b'GG-NODE-METADATA-v1\0'+pack(self._meta)).hexdigest()

    def _seal(self):
        body={'schema':'gg.node.durable-head.v1','binding':self._binding(),**self._head}
        self._put('head',{'body':body,'signature':self._keys[0].sign_message(HEAD_DOMAIN+pack(body)).hex()})

    def _commit(self):self._db.execute('COMMIT')

    def _write(self,operation):
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_NODE_STORE_NOT_WRITABLE')
            previous_meta=deepcopy(self._meta);previous_head=deepcopy(self._head)
            try:
                self._db.execute('BEGIN IMMEDIATE');operation();self._seal();self._commit()
            except BaseException as error:
                self._meta=previous_meta;self._head=previous_head;self._failed=True
                try:
                    if self._db.in_transaction:self._db.execute('ROLLBACK')
                except (sqlite3.Error,OSError):pass
                if not isinstance(error,Exception):raise
                raise ValueError('GG_NODE_STORE_WRITE_FAILED') from None

    @staticmethod
    def _advance(head,kind,wire):
        if kind not in ('dag','token') or not isinstance(wire,bytes) or not 0<len(wire)<=(MAX_WIRE if kind=='dag' else 4096):raise ValueError('GG_NODE_STORE_RECORD')
        head['entries']+=1;head['counts'][kind]+=1;head['bytes']+=len(wire)
        if head['entries']>MAX_ENTRIES or head['bytes']>MAX_BYTES or head['counts'][kind]>(4095 if kind=='dag' else 4096):raise ValueError('GG_NODE_STORE_LIMIT')
        head['digest']=hashlib.sha256(b'GG-NODE-ENTRY-v1\0'+bytes.fromhex(head['digest'])+head['entries'].to_bytes(8,'big')+kind.encode()+hashlib.sha256(wire).digest()).hexdigest()

    def append(self,kind,wires):
        if not isinstance(wires,(list,tuple)) or not 1<=len(wires)<=16:raise ValueError('GG_NODE_STORE_BATCH')
        with self._lock:
            if self._schema_version>=4:raise ValueError('GG_PRODUCER_USE_OWN_JOURNAL')
            if self._meta['session'] is None:raise ValueError('GG_NODE_STORE_SESSION_REQUIRED')
            def update():
                for wire in wires:
                    self._advance(self._head,kind,wire)
                    identifier=hashlib.sha256(kind.encode()+wire).hexdigest()
                    self._db.execute('INSERT INTO entries VALUES(?,?,?,?)',(self._head['entries'],kind,wire,identifier))
            self._write(update)
            if kind=='dag':
                for offset,wire in enumerate(wires):
                    identifier=self._dag_body_hash(wire)
                    if identifier is not None:
                        self._dag_bodies.add(identifier)
                        self._dag_index[identifier]=(self._head['entries']-len(wires)+offset+1,
                            hashlib.sha256(b'dag'+wire).hexdigest(),len(wire))

    def _require_archive_import(self):
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_NODE_STORE_NOT_WRITABLE')
            if (self._meta['descriptor'].get('node_role')!='replica'
                    or self._meta['descriptor']['allow_dag_transactions'] is not True):
                raise ValueError('GG_DAG_ARCHIVE_REPLICA_REQUIRED')
            if self._meta['session'] is None:raise ValueError('GG_NODE_STORE_SESSION_REQUIRED')
            if self._head['entries'] or self._dag_index or self._db.in_transaction:
                raise ValueError('GG_DAG_ARCHIVE_EMPTY_JOURNAL_REQUIRED')
            if self._meta['fault']:raise ValueError(self._meta['fault'])
            previous=self._meta.get('consensus')
            if previous is not None and previous['fault']:raise ValueError(previous['fault'])

    def _import_dag_archive(self,archive,check):
        """One sealed transaction for a complete native-verified public archive.

        The engine is private to this operation, holds no producer key, and is
        discarded afterwards. The caller owns an offline profile lease. An
        ambiguous Sync error leaves this handle faulted; reopen proves old/new.
        """
        from backend.gg_dag_archive import PublicDagArchive
        from backend.gg_dag_hardware import WorkGovernor,hardware_info
        from backend.gg_dag_order_history import OrderHistory
        from backend.gg_parallel_dag import ParallelDag
        if not isinstance(archive,PublicDagArchive):raise ValueError('GG_DAG_ARCHIVE_REQUIRED')
        with self._lock:
            self._require_archive_import()
            packet=archive.packet;source=self._order_packet(packet)
            tip=self._consensus_tip({'schema':'gg.dag.replica-floor.v1','packet':packet,'fault':''})
            previous=self._meta.get('consensus')
            if previous is not None:
                old=self._consensus_tip(previous)
                if tip[0]<old[0] or tip[0]==old[0] and tip!=old:raise ValueError('GG_NODE_CONSENSUS_REWIND')
            engine=ParallelDag.from_public_genesis(self._meta['session']['body']['public_genesis'])
            index={};order=[];candidate=None
            def governor():
                value=WorkGovernor(info=hardware_info(),stored_bytes=engine.memory_basis_bytes)
                if value.memory_headroom() is None:raise ValueError('GG_DAG_RESOURCE_NEEDS_MEMORY_MEASUREMENT')
                return value
            def read(identifier):
                entry=index.get(identifier)
                if entry is None:return None
                raw=bytes(self._db.execute('SELECT wire FROM entries WHERE position=?',(entry[0],)).fetchone()[0])
                if len(raw)!=entry[2] or hashlib.sha256(b'dag'+raw).hexdigest()!=entry[1]:raise ValueError('GG_NODE_STORE_RECORD_HASH')
                return raw
            try:
                engine.configure_lan_capacity();engine.configure_lan_roles(source['allowed_producers'])
                engine.configure_payload_archive(read,hot_bytes=0);engine.begin_history_replay()
                governor()
                def update():
                    nonlocal candidate
                    for raw in archive.payloads(lambda size:governor().reserve_memory(size*16)):
                        check()
                        result=engine.admit_relayed(raw,0,check=check)
                        if result.get('state')=='DUPLICATE':raise ValueError('GG_DAG_ARCHIVE_DUPLICATE')
                        row=engine._records[result['hash']]
                        self._advance(self._head,'dag',raw)
                        wire_hash=hashlib.sha256(b'dag'+raw).hexdigest();position=self._head['entries']
                        self._db.execute('INSERT INTO entries VALUES(?,?,?,?)',(position,'dag',raw,wire_hash))
                        index[result['hash']]=(position,wire_hash,len(raw))
                        order.append({'hash':result['hash'],'index':len(order)+1,'producer_index':row['producer_index'],
                            'sequence':row['producer_sequence'],'transactions':row['transaction_count']})
                    if not archive.complete:raise ValueError('GG_DAG_ARCHIVE_INCOMPLETE')
                    check();engine.finish_history_replay('')
                    if previous is not None:
                        old_state=previous['packet']['state'];prefix=order[:old_state['dag']['blocks']]
                        OrderHistory(source).extend(old_state,prefix)
                        engine.apply_certified_order(old_state,prefix,source)
                    candidate=(self._durable_order or OrderHistory(source)).extend(packet['state'],order)
                    engine.apply_certified_order(packet['state'],order,source)
                    start=len(self._durable_order) if self._durable_order is not None else 0
                    fresh=[pack(leaf) for leaf in order[start:]]
                    size=self._meta.get('order_index',{}).get('bytes',0)+sum(map(len,fresh))
                    if size>2*1024*1024 or any(len(raw)>512 for raw in fresh):raise ValueError('GG_NODE_ORDER_CACHE_LIMIT')
                    for offset,raw in enumerate(fresh,start+1):
                        self._db.execute('INSERT INTO orders VALUES(?,?,?)',(offset,raw,order[offset-1]['hash']))
                    self._meta['order_index']={'schema':'gg.dag.order-cache.v1','packet':deepcopy(packet),'bytes':size}
                    self._meta['consensus']={'schema':'gg.dag.replica-floor.v1','packet':deepcopy(packet),'fault':''}
                    self._put('order_index',self._meta['order_index']);self._put('consensus',self._meta['consensus'])
                    check()
                self._write(update)
                self._dag_index=index;self._dag_bodies=set(index);self._durable_order=candidate
                return {'schema':'gg.dag.archive-import-result.v1','state':'PUBLIC_DAG_HISTORY_IMPORTED',
                    'profile':self.name,'node_role':'replica','blocks_imported':len(order),
                    'transactions_imported':packet['state']['dag']['transactions'],'raw_payload_bytes':self._head['bytes'],
                    'certificate_height':tip[0],'native_transfer_history_restored':False,
                    'validator_state_restored':False,'identity_replaced':False,'production_started':False}
            finally:engine.stop()

    @staticmethod
    def _dag_body_hash(wire):
        # This indexes public bodies for scan-integrity checks. Full protocol
        # and every signature are STILL verified by keyless engine replay.
        try:
            value=unpack(wire);body=value.get('body') if isinstance(value,dict) else None
            if isinstance(body,dict):return hashlib.sha256(b'GG-DAG-BLOCK-v1\0'+pack(body)).hexdigest()
        except (ValueError,UnicodeError,TypeError,RecursionError):pass
        return None

    def _load_peer_scans(self):
        heads=self._meta.get('peer_scans',{})
        if not isinstance(heads,dict) or len(heads)>2 or set(heads)-set(self._meta['cursors']):raise ValueError('GG_NODE_PEER_SCAN_HEAD')
        rows=list(self._db.execute('SELECT peer,sequence,length(event),typeof(event) FROM peer_scans ORDER BY peer,sequence LIMIT ?',
            (2*peer_scan.MAX_EVENTS+1,)))
        if len(rows)>2*peer_scan.MAX_EVENTS or any(row[0] not in heads or row[3]!='blob' or not 0<row[2]<=peer_scan.MAX_EVENT_BYTES for row in rows):
            raise ValueError('GG_NODE_PEER_SCAN_RECORD')
        if self._meta['descriptor'].get('node_role')=='light' and rows:raise ValueError('GG_NODE_LIGHT_GLOBAL_HISTORY_FORBIDDEN')
        states={}
        for peer,head in heads.items():
            if not isinstance(peer,str) or not HEX.fullmatch(peer) or not isinstance(head,dict):raise ValueError('GG_NODE_PEER_SCAN_HEAD')
            state=peer_scan.initial(head.get('base'));states[peer]=state
        for peer,sequence,_,_ in rows:
            state=states[peer]
            if sequence!=state['events']+1:raise ValueError('GG_NODE_PEER_SCAN_SEQUENCE')
            raw=bytes(self._db.execute('SELECT event FROM peer_scans WHERE peer=? AND sequence=?',(peer,sequence)).fetchone()[0])
            value=unpack(raw)
            if pack(value)!=raw:raise ValueError('GG_NODE_PEER_SCAN_RECORD')
            peer_scan.advance(state,value,self._dag_bodies)
        for peer,state in states.items():
            if peer_scan.head(state)!=heads[peer] or state['prefix']!=self._meta['cursors'][peer]:raise ValueError('GG_NODE_PEER_SCAN_HEAD')
        self._scan_states=states

    def scan_progress(self):
        with self._lock:
            return {peer:peer_scan.summary(state) for peer,state in self._scan_states.items()}

    def save_scan_page(self,peer,observed):
        """Only a verified authenticated END can commit these observations.

        REFUSED/DEFERRED explicitly do not acknowledge block admission. A scan
        event claiming ADMITTED requires its body in the durable DAG journal.
        """
        if (not isinstance(peer,str) or not HEX.fullmatch(peer) or not isinstance(observed,list) or not 1<=len(observed)<=8):
            raise ValueError('GG_NODE_PEER_SCAN_PAGE')
        with self._lock:
            if self._meta['session'] is None or self._meta['descriptor'].get('node_role')=='light':raise ValueError('GG_NODE_PEER_SCAN_SESSION')
            state=deepcopy(self._scan_states.get(peer,peer_scan.initial(self._meta['cursors'].get(peer,0))))
            events=[]
            for value in observed:
                if value.get('kind')!='OBSERVED':raise ValueError('GG_NODE_PEER_SCAN_PAGE')
                peer_scan.advance(state,value,self._dag_bodies);events.append((state['events'],pack(value)))
            self._save_scan_state(peer,state,events)

    def deferred_payloads(self,peer,after=0,limit=8):
        """Bounded rotating retry of deferred data, including after RAM loss.

        Quota-refused branches are excluded: only SDK-selected recovery may
        request those beyond the local fork quota. These are fetch hints,
        never an admission or availability certificate.
        """
        if not isinstance(peer,str) or not HEX.fullmatch(peer) or not _number(after,4095) or type(limit) is not int or not 1<=limit<=8:
            raise ValueError('GG_NODE_PEER_SCAN_RETRY')
        with self._lock:
            rows=sorted(self._scan_states.get(peer,{}).get('deferred',{}).items())
            following=[row for row in rows if row[0]>after]+[row for row in rows if row[0]<=after]
            selected=following[:limit]
            return {'hashes':[identifier for _,identifier in selected],'after':selected[-1][0] if selected else 0}

    def _save_scan_state(self,peer,state,events):
        if len(set(self._meta.get('peer_scans',{}))|{peer})>2:raise ValueError('GG_NODE_PEER_SCAN_PEER')
        def update():
            for sequence,raw in events:self._db.execute('INSERT INTO peer_scans VALUES(?,?,?)',(peer,sequence,raw))
            heads=deepcopy(self._meta.get('peer_scans',{}));heads[peer]=peer_scan.head(state)
            self._meta['peer_scans']=heads;self._put('peer_scans',heads)
            self._meta['cursors'][peer]=state['prefix'];self._put('cursors',self._meta['cursors'])
        self._write(update);self._scan_states[peer]=state

    def resolve_peer_scans(self):
        with self._lock:
            remaining=16
            for peer,current in tuple(self._scan_states.items()):
                state=deepcopy(current);events=[]
                for position,(identifier,validated) in sorted(state['pending'].items()):
                    if not remaining:break
                    if not validated and identifier in self._dag_bodies:
                        value=peer_scan.event('VALIDATED',position,identifier)
                        peer_scan.advance(state,value,self._dag_bodies);events.append((state['events'],pack(value)));remaining-=1
                if events:self._save_scan_state(peer,state,events)
                if not remaining:break

    def records(self):
        with self._lock:
            rows=list(self._db.execute('SELECT position,kind,length(wire),typeof(wire),wire_hash FROM entries ORDER BY position LIMIT ?',(MAX_ENTRIES+1,)))
        if len(rows)>MAX_ENTRIES:raise ValueError('GG_NODE_STORE_LIMIT')
        for expected,(position,kind,size,wire_type,identifier) in enumerate(rows,1):
            if (position!=expected or kind not in ('dag','token') or wire_type!='blob' or not 0<size<=(MAX_WIRE if kind=='dag' else 4096)):
                raise ValueError('GG_NODE_STORE_RECORD')
            with self._lock:wire=bytes(self._db.execute('SELECT wire FROM entries WHERE position=?',(position,)).fetchone()[0])
            if hashlib.sha256(kind.encode()+wire).hexdigest()!=identifier:raise ValueError('GG_NODE_STORE_RECORD_HASH')
            yield kind,wire

    def read_dag(self,identifier):
        """Retrieve one indexed public wire without rescanning/decoding history.

        This index is derived from the signed journal on open and AFTER Sync
        on append. It grants no protocol/finality authority. The engine still
        compares this wire with its fully verified admission digest and size.
        """
        if not isinstance(identifier,str) or not HEX.fullmatch(identifier):raise ValueError('GG_NODE_STORE_DAG_HASH')
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_NODE_STORE_NOT_READABLE')
            entry=self._dag_index.get(identifier)
            if entry is None:return None
            position,wire_hash,size=entry
            row=self._db.execute('SELECT kind,length(wire),typeof(wire),wire_hash FROM entries WHERE position=?',(position,)).fetchone()
            if row!=('dag',size,'blob',wire_hash) or not 0<size<=MAX_WIRE:raise ValueError('GG_NODE_STORE_RECORD_HASH')
            wire=bytes(self._db.execute('SELECT wire FROM entries WHERE position=?',(position,)).fetchone()[0])
        if hashlib.sha256(b'dag'+wire).hexdigest()!=wire_hash:raise ValueError('GG_NODE_STORE_RECORD_HASH')
        return wire

    def bind_session(self,bundle):
        if self._meta.get('protocol_producer') is not None:raise ValueError('GG_PROTOCOL_PROFILE_USE_PROTOCOL_RUNTIME')
        with self._lock:
            if self._meta['session'] is not None:
                if self._meta['session']!=bundle:raise ValueError('GG_NODE_STORE_NETWORK_ALREADY_BOUND')
                return
            def update():
                self._meta['session']=deepcopy(bundle);self._put('session',bundle)
            self._write(update)

    def save_validator_invites(self,invites):
        """Commit append-only public pairing ads before advertising them."""
        with self._lock:
            previous=self._meta['descriptor'].get('validator_invites',[])
            if invites==previous:return
            if self._meta['session'] is not None:raise ValueError('GG_NODE_PROFILE_ALREADY_BOUND')
            if not isinstance(invites,list) or invites[:len(previous)]!=previous or len(invites)<len(previous):
                raise ValueError('GG_NODE_PROFILE_VALIDATOR_INVITES')
            desired={**self._meta['descriptor'],'validator_invites':deepcopy(invites)}
            self._validate_descriptor(desired)
            def update():self._meta['descriptor']=desired;self._put('descriptor',desired)
            self._write(update)

    def _consensus_tip(self,value):
        from backend.gg_consensus_membership import anchor_from_bundle
        from backend.gg_dag_checkpoint import certificate_tip,validate_conflict_evidence,CONFLICT
        if (self._meta['session'] is None or not isinstance(value,dict)
                or value.get('fault') not in ('',CONFLICT)):
            raise ValueError('GG_NODE_CONSENSUS_RECORD')
        if value.get('schema')=='gg.dag.replica-floor.v1':
            if set(value)!={'schema','packet','fault'}:raise ValueError('GG_NODE_CONSENSUS_RECORD')
        elif value.get('schema')=='gg.dag.replica-floor.v2':
            if set(value)!={'schema','packet','fault','evidence'} or value['fault']!=CONFLICT:raise ValueError('GG_NODE_CONSENSUS_RECORD')
        else:raise ValueError('GG_NODE_CONSENSUS_RECORD')
        anchor=anchor_from_bundle(self._meta['session'],self._meta['descriptor']['trusted_coordinator'])
        tip=certificate_tip(value['packet'],anchor)
        if 'evidence' in value:
            validate_conflict_evidence(value['evidence'],anchor)
            if value['evidence']['height']>tip[0]:raise ValueError('GG_NODE_CONSENSUS_RECORD')
        return tip

    def _order_packet(self,packet):
        # Structural/session binding only. Caller MUST run the SDK verifier
        # before restoring or using this cache as public fetch authority.
        self._consensus_tip({'schema':'gg.dag.replica-floor.v1','packet':packet,'fault':''})
        source=packet['genesis']['dag']
        from backend.gg_dag_checkpoint import validate_source
        validate_source(source)
        return source

    def _load_order_index(self):
        from backend.gg_dag_order_history import OrderHistory
        rows=list(self._db.execute('SELECT position,length(leaf),typeof(leaf),hash FROM orders ORDER BY position LIMIT 4096'))
        meta=self._meta.get('order_index')
        if meta is None:
            if rows:raise ValueError('GG_NODE_ORDER_CACHE_UNBOUND')
            return
        if self._meta['descriptor'].get('node_role')=='light':raise ValueError('GG_NODE_LIGHT_GLOBAL_HISTORY_FORBIDDEN')
        if (not isinstance(meta,dict) or set(meta)!={'schema','packet','bytes'} or meta['schema']!='gg.dag.order-cache.v1'
                or not _number(meta['bytes'],2*1024*1024)):raise ValueError('GG_NODE_ORDER_CACHE_RECORD')
        source=self._order_packet(meta['packet']);order=[];size=0
        for expected,(position,length,kind,identifier) in enumerate(rows,1):
            if position!=expected or kind!='blob' or not 0<length<=512:raise ValueError('GG_NODE_ORDER_CACHE_RECORD')
            raw=bytes(self._db.execute('SELECT leaf FROM orders WHERE position=?',(position,)).fetchone()[0]);leaf=unpack(raw)
            if not isinstance(leaf,dict) or leaf.get('hash')!=identifier:raise ValueError('GG_NODE_ORDER_CACHE_RECORD')
            order.append(leaf);size+=length
        if len(rows)>4095 or size!=meta['bytes']:raise ValueError('GG_NODE_ORDER_CACHE_RECORD')
        self._durable_order=OrderHistory.restore(source,meta['packet']['state'],order)

    def verified_order(self):
        """Signed local cache only; returns no SDK-verification assertion."""
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_NODE_STORE_NOT_READABLE')
            if self._durable_order is None:return None
            return {'packet':deepcopy(self._meta['order_index']['packet']),'order':self._durable_order.order()}

    def save_verified_order(self,packet,order):
        from backend.gg_dag_order_history import OrderHistory
        with self._lock:
            if self._meta['descriptor'].get('node_role')=='light':raise ValueError('GG_NODE_LIGHT_GLOBAL_HISTORY_FORBIDDEN')
            source=self._order_packet(packet);previous=self._durable_order
            if previous is not None and previous.source!=source:raise ValueError('GG_NODE_ORDER_CACHE_SOURCE')
            if previous is not None and len(order)<len(previous):
                # An independently owned SDK may be catching up. It cannot
                # rewind the shared cache or turn old data into new activity.
                candidate=OrderHistory.restore(source,packet['state'],order)
                if previous.order()[:len(order)]!=candidate.order():raise ValueError('GG_NODE_ORDER_CACHE_REWRITE')
                return False
            candidate=(previous or OrderHistory(source)).extend(packet['state'],order)
            start=len(previous) if previous is not None else 0
            if previous is not None and len(candidate)==start:return False
            fresh=[pack(leaf) for leaf in order[start:]]
            if any(not 0<len(raw)<=512 for raw in fresh):raise ValueError('GG_NODE_ORDER_CACHE_RECORD')
            size=self._meta.get('order_index',{}).get('bytes',0)+sum(map(len,fresh))
            if size>2*1024*1024:raise ValueError('GG_NODE_ORDER_CACHE_LIMIT')
            meta={'schema':'gg.dag.order-cache.v1','packet':deepcopy(packet),'bytes':size}
            def update():
                for index,raw in enumerate(fresh,start+1):self._db.execute('INSERT INTO orders VALUES(?,?,?)',(index,raw,order[index-1]['hash']))
                self._meta['order_index']=meta;self._put('order_index',meta)
            self._write(update);self._durable_order=candidate
            return True

    def consensus_observation(self):
        with self._lock:return deepcopy(self._meta.get('consensus'))

    def save_consensus_certificate(self,packet):
        """SDK verification is required by the caller BEFORE this durable gate."""
        with self._lock:
            value={'schema':'gg.dag.replica-floor.v1','packet':deepcopy(packet),'fault':''};tip=self._consensus_tip(value)
            previous=self._meta.get('consensus')
            if previous is not None:
                if previous['fault']:raise ValueError(previous['fault'])
                old=self._consensus_tip(previous)
                if tip[0]<old[0]:raise ValueError('GG_NODE_CONSENSUS_REWIND')
                if tip[0]==old[0]:
                    if tip==old:return
                    from backend.gg_consensus_membership import anchor_from_bundle
                    from backend.gg_dag_checkpoint import make_conflict_evidence
                    anchor=anchor_from_bundle(self._meta['session'],self._meta['descriptor']['trusted_coordinator'])
                    self.save_consensus_conflict(make_conflict_evidence(previous['packet'],packet,anchor))
                    raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            def update():self._meta['consensus']=value;self._put('consensus',value)
            self._write(update)
            if value['fault']:raise ValueError(value['fault'])

    def save_consensus_conflict(self,evidence):
        """The caller MUST SDK-verify both certificates before this durable gate."""
        from backend.gg_consensus_membership import anchor_from_bundle
        from backend.gg_dag_checkpoint import validate_conflict_evidence,certificate_tip,CONFLICT
        with self._lock:
            anchor=anchor_from_bundle(self._meta['session'],self._meta['descriptor']['trusted_coordinator'])
            validate_conflict_evidence(evidence,anchor)
            previous=self._meta.get('consensus')
            if previous is not None:
                self._consensus_tip(previous)
                if previous.get('evidence') is not None:return
            candidates=([previous['packet']] if previous is not None else [])+[evidence['certificates'][0]]
            packet=max(candidates,key=lambda packet:certificate_tip(packet,anchor)[0])
            value={'schema':'gg.dag.replica-floor.v2','packet':deepcopy(packet),'fault':CONFLICT,'evidence':deepcopy(evidence)}
            self._consensus_tip(value)
            def update():self._meta['consensus']=value;self._put('consensus',value)
            self._write(update)

    def configure_pairing(self,**changes):
        if set(changes)-{'host','port','trusted_coordinator'}:raise ValueError('GG_NODE_PROFILE_CONFIGURATION')
        with self._lock:
            desired={**self._meta['descriptor'],**changes};self._validate_descriptor(desired)
            if desired['trusted_coordinator']!=self._meta['descriptor']['trusted_coordinator']:desired['bootstrap']=None
            if desired==self._meta['descriptor']:return
            if self._meta['session'] is not None:raise ValueError('GG_NODE_PROFILE_ALREADY_BOUND')
            def update():self._meta['descriptor']=desired;self._put('descriptor',desired)
            self._write(update)

    def claim_control(self,kind,identifier):
        """Persist a consumed plan before it can authorize any local work."""
        if kind not in ('dag','circle') or not isinstance(identifier,str) or not HEX.fullmatch(identifier):
            raise ValueError('GG_NODE_STORE_CONTROL')
        with self._lock:
            ids=self._meta['controls'][kind]
            if identifier in ids:raise ValueError('GG_NODE_STORE_CONTROL_REPLAY')
            if len(ids)>=4096:raise ValueError('GG_NODE_STORE_CONTROL_LIMIT')
            def update():ids.append(identifier);self._put('controls',self._meta['controls'])
            self._write(update)

    def used_controls(self):return deepcopy(self._meta['controls'])

    def save_cursor(self,peer,cursor):
        with self._lock:
            if not isinstance(peer,str) or not HEX.fullmatch(peer) or not _number(cursor,4095):raise ValueError('GG_NODE_STORE_CURSOR')
            if self._meta['cursors'].get(peer,0)==cursor:return
            if peer in self._scan_states:raise ValueError('GG_NODE_STORE_CURSOR_SCAN_REQUIRED')
            if cursor<self._meta['cursors'].get(peer,0) or peer not in self._meta['cursors'] and len(self._meta['cursors'])>=2:raise ValueError('GG_NODE_STORE_CURSOR')
            def update():self._meta['cursors'][peer]=cursor;self._put('cursors',self._meta['cursors'])
            self._write(update)

    def latch_fault(self,code):
        if code not in FAULTS[1:]:raise ValueError('GG_NODE_STORE_FAULT')
        with self._lock:
            if self._meta['fault']==code:return
            def update():self._meta['fault']=code;self._put('fault',code)
            self._write(update)

    def descriptor(self):return deepcopy(self._meta['descriptor'])
    def session(self):return deepcopy(self._meta['session'])
    def cursors(self):return dict(self._meta['cursors'])
    def fault(self):return self._meta['fault']
    def signers(self):
        from backend.gg_native_process_policy import owner_ended
        with self._lock:
            if self._closed or getattr(self,'_native_pipe_closing',False) or owner_ended(self) or len(self._keys)!=3:
                raise ValueError('GG_NODE_VAULT_CLOSED')
            if self._failed:raise ValueError('GG_NODE_STORE_NOT_WRITABLE')
            if 'network_transition_pending' in self._meta:raise ValueError('GG_NETWORK_TRANSITION_PENDING')
            result=self._keys[0],list(self._keys[1:])
            # Close publishes its lifetime before waiting for this journal lock.
            if getattr(self,'_native_pipe_closing',False) or owner_ended(self):raise ValueError('GG_NODE_VAULT_CLOSED')
            return result

    def snapshot(self):
        with self._lock:
            result={'enabled':True,'profile':self.name,'state':'CLOSED' if self._closed else 'FAULT' if self._failed else 'NETWORK_TRANSITION_PENDING' if 'network_transition_pending' in self._meta else 'READY',
                'keys_encrypted_at_rest':True,'restored':self._restored,'records':self._head['entries'] if self._head else 0,
                'bytes':self._head['bytes'] if self._head else 0,'counts':dict(self._head['counts']) if self._head else {'dag':0,'token':0},
                'record_limit':MAX_ENTRIES,'byte_limit':MAX_BYTES,'kind_limits':{'dag':4095,'token':4096},
                'canonical_finality':False,'whole_disk_rollback_protection':False}
            segmented=self._meta.get('segmented_producer')
            if segmented is not None:
                result['segmented_producer']={'scope':'LAST_STORED_SDK_OBSERVATION_NOT_NETWORK_LIVENESS',
                    'epoch':segmented['packet']['state']['dag_segmented']['epoch'],'own_records':segmented['head']['records'],
                    'own_raw_bytes':segmented['head']['bytes'],'archived_own_epochs':segmented['archive_count'],'certificate_height':segmented['floor'][0]}
            financial=self._meta.get('financial_producer')
            if financial is not None:
                result['financial_producer']={'scope':'DURABLE_OWN_SIGNATURES_AND_LAST_STORED_SDK_FLOOR_NOT_NETWORK_LIVENESS',
                    'own_records':financial['head']['records'],'own_raw_bytes':financial['head']['bytes'],
                    'active_records':financial['head']['records']-financial.get('archived_head',{}).get('records',0),
                    'active_raw_bytes':financial['head']['bytes']-financial.get('archived_head',{}).get('bytes',0),
                    'archived_own_chunks':financial.get('archive_count',0),
                    'archive_state':'RECOVERY_PENDING' if financial.get('pending_archive') else 'READY',
                    'certificate_height':financial['floor'][0],'last_error':financial['fault']}
            return result

    def close(self):
        from backend.gg_native_process_policy import close_owner
        close_owner(self)
        writer=self._segmented_writer
        if writer is not None:writer.close()
        with self._lock:
            if self._db is not None:self._db.close();self._db=None
            self._dag_index.clear();self._dag_bodies.clear()
            self._durable_order=None
            self._keys.clear();self._closed=True
            if self._lease is not None:
                try:file_locks.flock(self._lease,file_locks.LOCK_UN)
                finally:os.close(self._lease);self._lease=None
