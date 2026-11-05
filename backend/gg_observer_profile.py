"""Exclusive protected P2P identity for a native full observer.

This is deliberately not a ValidatorProfile: there is no consensus/account
private key, validator index or API that can return a consensus signer.
Stored certificates are historical observations until independently reverified
against the native SDK and freshly executed local state by the controller.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading

from backend.application_paths import DATA_HOME
from backend import gg_node_vault as vault
from backend.gg_ed25519 import Keypair,verify_signature
from backend.gg_node_store import pack,unpack,_private_path
from backend.gg_consensus_membership import anchor_from_bundle,SIG
from backend.gg_native_observer import make_grant,validate_grant
from backend.gg_dag_checkpoint import certificate_tip,validate_conflict_evidence,CONFLICT
from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory
from backend.platform_support import file_locks

ROOT=Path(DATA_HOME).expanduser().resolve()/'goldgoblins/consensus-observers'
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')
HEAD=b'GG-NATIVE-OBSERVER-PROFILE-STATE-v1\0'
ROLE='consensus_observer_node'
SCHEMA='gg.native.observer-profile.v1'
RECOVERY_SCHEMA='gg.native.observer-profile.v2'
PUBLIC_SCHEMA='gg.native.protocol-replica-profile.v1'
PUBLIC_RECOVERY_SCHEMA='gg.native.protocol-replica-profile.v2'
PUBLIC_SCHEMAS=(PUBLIC_SCHEMA,PUBLIC_RECOVERY_SCHEMA)
HASH=re.compile(r'[0-9a-f]{64}')
APP_ID=0x47474f31
MAX_RECORD=1024*1024
SQL="CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1),record BLOB NOT NULL CHECK(typeof(record)='blob'))"


def profile_path(name):
    if not isinstance(name,str) or not NAME.fullmatch(name):raise ValueError('GG_OBSERVER_PROFILE_NAME')
    root=Path(ROOT).absolute()
    if str(root).startswith(('\\\\','//')) or any(is_link(path) for path in (root,*root.parents)):
        raise ValueError('GG_OBSERVER_PROFILE_PATH')
    return root/name


class ObserverProfile:
    def __init__(self,name):
        self.name=name;self.root=profile_path(name);self._lock=threading.RLock()
        self._db=None;self._lease=None;self._key=None;self._body=None;self._failed=False;self._closed=False

    def __repr__(self):return '<GG protected native observer profile>'

    @classmethod
    def create_for_protocol(cls,name,owner,pin,*,label):
        from backend.gg_node_store import NodeProfile
        from backend.gg_consensus_membership import label_wire
        from backend.gg_financial_protocol import validate_pin
        if type(owner) is not NodeProfile or owner._closed or owner._failed or owner._lease is None:raise ValueError('GG_OBSERVER_OWNED_PROFILE_REQUIRED')
        pin=validate_pin(pin);label_utf8=label_wire(label);profile=cls(name)
        try:
            if vault.provider()=='SCRYPT_AES256_GCM':
                from backend.portable_wallet_vault import require_unlocked
                require_unlocked()
            profile.root.parent.mkdir(mode=0o700,parents=True,exist_ok=True);set_private_mode(profile.root.parent,0o700);_private_path(profile.root.parent,0o700)
            try:profile.root.mkdir(mode=0o700)
            except FileExistsError:raise ValueError('GG_OBSERVER_PROFILE_EXISTS_USE_RESUME') from None
            set_private_mode(profile.root,0o700);profile._acquire(create=True);profile._key=Keypair()
            public=profile._key.pubkey().hex();cipher=vault.crypt(bytes(profile._key),public,ROLE,profile.root)
            profile._body={'schema':PUBLIC_SCHEMA,'key_storage':vault.provider(),'protected_key':{'public':public,'ciphertext':base64.b64encode(cipher).decode('ascii')},
                           'pin':pin,'label_utf8':label_utf8,'owner_key':owner.descriptor()['public_keys'][0],
                           'native_started':False,'certificate':None,'fault':'','conflict_evidence':None}
            profile._connect(create=True);profile._db.execute('BEGIN IMMEDIATE');profile._db.execute(SQL);profile._put();profile._commit();sync_directory(profile.root)
            return profile
        except BaseException:profile.close();raise

    @classmethod
    def create(cls,name,peer,*,label,p2p_port,producer_slot=0):
        from backend.gg_lan_dag import LanDagPeer
        if not isinstance(peer,LanDagPeer):raise ValueError('GG_OBSERVER_OWNED_PEER_REQUIRED')
        with peer._configuration,peer._lock:
            if peer._cancel.is_set() or peer._bundle is None or peer._engine is None:
                raise ValueError('GG_OBSERVER_ACTIVE_LAN_REQUIRED')
            if peer.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
            return cls._create(name,peer._identity,peer._local_keys,peer._bundle,peer._trusted,
                host=peer.host,label=label,p2p_port=p2p_port,producer_slot=producer_slot)

    @classmethod
    def create_for_owned_profile(cls,name,owner,*,label,p2p_port,producer_slot=0):
        from backend.gg_node_store import NodeProfile
        if not isinstance(owner,NodeProfile) or owner._lease is None or owner._db is None:
            raise ValueError('GG_OBSERVER_OWNED_PROFILE_REQUIRED')
        with owner._lock:
            if owner.descriptor().get('node_role')=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
            identity,producers=owner.signers();bundle=owner.session()
            return cls._create(name,identity,producers,bundle,owner.descriptor()['trusted_coordinator'],
                host=owner.descriptor()['host'],label=label,p2p_port=p2p_port,producer_slot=producer_slot)

    @classmethod
    def _create(cls,name,identity,producers,bundle,coordinator,*,host,label,p2p_port,producer_slot):
        if type(producer_slot) is not int or producer_slot not in (0,1):raise ValueError('GG_OBSERVER_PRODUCER_SLOT')
        # Validate all public policy before creating any persistent directory.
        key=Keypair()
        grant=make_grant(key,identity,producers[producer_slot],bundle,coordinator,
            label=label,host=host,p2p_port=p2p_port)
        profile=cls(name)
        try:
            if vault.provider()=='SCRYPT_AES256_GCM':
                from backend.portable_wallet_vault import require_unlocked
                require_unlocked()
            profile.root.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            set_private_mode(profile.root.parent,0o700);_private_path(profile.root.parent,0o700)
            try:profile.root.mkdir(mode=0o700)
            except FileExistsError:raise ValueError('GG_OBSERVER_PROFILE_EXISTS_USE_RESUME') from None
            set_private_mode(profile.root,0o700);profile._acquire(create=True);profile._key=key
            public=key.pubkey().hex();cipher=vault.crypt(bytes(key),public,ROLE,profile.root)
            profile._body={'schema':SCHEMA,'key_storage':vault.provider(),
                'protected_key':{'public':public,'ciphertext':base64.b64encode(cipher).decode('ascii')},
                'bundle':deepcopy(bundle),'coordinator':coordinator,'grant':grant,
                'native_started':False,'certificate':None,'fault':'','conflict_evidence':None}
            profile._connect(create=True);profile._db.execute('BEGIN IMMEDIATE')
            profile._db.execute(SQL);profile._put();profile._commit();sync_directory(profile.root)
            return profile
        except BaseException:
            profile.close();raise

    @classmethod
    def open(cls,name):
        profile=cls(name)
        try:
            profile._acquire(create=False);profile._connect(create=False)
            if profile._db.execute('PRAGMA quick_check(1)').fetchone()!=('ok',):raise ValueError('GG_OBSERVER_STORE_CORRUPT')
            rows=list(profile._db.execute('SELECT id,length(record),typeof(record) FROM state'))
            if len(rows)!=1 or rows[0][0]!=1 or rows[0][2]!='blob' or not 0<rows[0][1]<=MAX_RECORD:
                raise ValueError('GG_OBSERVER_STORE_RECORD')
            envelope=unpack(bytes(profile._db.execute('SELECT record FROM state WHERE id=1').fetchone()[0]))
            if (not isinstance(envelope,dict) or set(envelope)!={'body','signature'} or
                    not isinstance(envelope['signature'],str) or not SIG.fullmatch(envelope['signature'])):
                raise ValueError('GG_OBSERVER_STORE_HEAD')
            body=envelope['body']
            fields={'schema','key_storage','protected_key','bundle','coordinator','grant','native_started','certificate','fault','conflict_evidence'}
            public=isinstance(body,dict) and body.get('schema') in PUBLIC_SCHEMAS
            if public:fields={'schema','key_storage','protected_key','pin','label_utf8','owner_key','native_started','certificate','fault','conflict_evidence'}
            if isinstance(body,dict) and body.get('schema') in (RECOVERY_SCHEMA,PUBLIC_RECOVERY_SCHEMA):fields.add('recovery')
            if (not isinstance(body,dict) or set(body)!=fields or body['schema'] not in (SCHEMA,RECOVERY_SCHEMA,*PUBLIC_SCHEMAS) or type(body['native_started']) is not bool
                    or body['fault'] not in ('',CONFLICT)
                    or body['key_storage'] not in ('WINDOWS_DPAPI','SCRYPT_AES256_GCM')):raise ValueError('GG_OBSERVER_STORE_RECORD')
            if public:
                from backend.gg_financial_protocol import validate_pin
                from backend.gg_financial_dag import account_address
                from backend.gg_consensus_membership import label_wire
                validate_pin(body['pin']);account_address(body['owner_key']);account_address(body['protected_key']['public'])
                if label_wire(base64.b64decode(body['label_utf8'],validate=True).decode('utf-8'))!=body['label_utf8']:raise ValueError('GG_OBSERVER_STORE_LABEL')
                checked={'node_key':body['protected_key']['public']}
            else:checked=validate_grant(body['grant'],body['bundle'],body['coordinator'])
            row=body['protected_key']
            if not isinstance(row,dict) or set(row)!={'public','ciphertext'} or row['public']!=checked['node_key']:
                raise ValueError('GG_OBSERVER_VAULT_INVALID')
            verify_signature(bytes.fromhex(row['public']),HEAD+pack(body),bytes.fromhex(envelope['signature']))
            cipher=base64.b64decode(row['ciphertext'],validate=True)
            raw=vault.crypt(cipher,row['public'],ROLE,profile.root,decrypt=True,storage=body['key_storage'])
            if len(raw)!=64 or raw[32:].hex()!=row['public']:raise ValueError('GG_OBSERVER_VAULT_INVALID')
            key=Keypair.from_seed(raw[:32]);del raw
            if key.pubkey().hex()!=row['public']:raise ValueError('GG_OBSERVER_VAULT_INVALID')
            profile._body=body;profile._key=key
            if body['certificate'] is not None:
                if not public and not body['native_started']:raise ValueError('GG_OBSERVER_CERTIFICATE_CONTEXT')
                certificate_tip(body['certificate'],profile.anchor())
            if body['conflict_evidence'] is not None:
                validate_conflict_evidence(body['conflict_evidence'],profile.anchor())
                if body['fault']!=CONFLICT or body['certificate'] not in body['conflict_evidence']['certificates']:
                    raise ValueError('GG_OBSERVER_CONFLICT_CONTEXT')
            elif body['fault']:raise ValueError('GG_OBSERVER_CONFLICT_CONTEXT')
            if body['schema'] in (RECOVERY_SCHEMA,PUBLIC_RECOVERY_SCHEMA):profile._recovery_intent()
            return profile
        except sqlite3.Error as error:
            profile.close();code=getattr(error,'sqlite_errorcode',0)&255
            raise ValueError('GG_OBSERVER_PROFILE_IN_USE' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'GG_OBSERVER_STORE_CORRUPT') from None
        except (ValueError,KeyError,TypeError,UnicodeError) as error:
            profile.close()
            if str(error)=='GG_OBSERVER_PROFILE_IN_USE':raise ValueError('GG_OBSERVER_PROFILE_IN_USE') from None
            raise ValueError('GG_OBSERVER_PROFILE_INVALID_OR_UNAVAILABLE') from None
        except BaseException:
            profile.close();raise

    def _acquire(self,*,create):
        if not self.root.is_dir() or any(is_link(path) for path in (self.root,*self.root.parents)):
            raise ValueError('GG_OBSERVER_PROFILE_MISSING_OR_LINK')
        _private_path(self.root.parent,0o700);_private_path(self.root,0o700)
        path=self.root/'owner.lock';flags=os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0)
        try:self._lease=secure_open(path,flags,0o600)
        except FileNotFoundError:raise ValueError('GG_OBSERVER_PROFILE_LOCK_MISSING') from None
        if create:os.write(self._lease,b'0');os.fsync(self._lease)
        info=os.fstat(self._lease)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=1:raise ValueError('GG_OBSERVER_PROFILE_LOCK_INVALID')
        _private_path(path,0o600)
        try:file_locks.flock(self._lease,file_locks.LOCK_EX|file_locks.LOCK_NB)
        except BlockingIOError:
            os.close(self._lease);self._lease=None;raise ValueError('GG_OBSERVER_PROFILE_IN_USE') from None

    def _connect(self,*,create):
        path=self.root/'observer.sqlite3'
        descriptor=secure_open(path,os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0),0o600)
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>4*1024*1024:raise ValueError('GG_OBSERVER_STORE_FILE')
        finally:os.close(descriptor)
        _private_path(path,0o600)
        self._db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None,check_same_thread=False)
        if self._db.execute('PRAGMA page_size').fetchone()!=(4096,):raise ValueError('GG_OBSERVER_STORE_PAGE_SIZE')
        self._db.execute('PRAGMA trusted_schema=OFF');self._db.execute('PRAGMA temp_store=MEMORY');self._db.execute('PRAGMA cache_size=-2048')
        if self._db.execute('PRAGMA journal_mode=DELETE').fetchone()!=('delete',):raise ValueError('GG_OBSERVER_STORE_DURABILITY')
        self._db.execute('PRAGMA synchronous=EXTRA')
        if self._db.execute('PRAGMA synchronous').fetchone()!=(3,):raise ValueError('GG_OBSERVER_STORE_DURABILITY')
        if self._db.execute('PRAGMA locking_mode=EXCLUSIVE').fetchone()!=('exclusive',):raise ValueError('GG_OBSERVER_STORE_LOCKING')
        self._db.execute('BEGIN EXCLUSIVE');self._db.execute('COMMIT');self._db.execute('PRAGMA max_page_count=1024')
        if create:self._db.execute('PRAGMA application_id='+str(APP_ID));self._db.execute('PRAGMA user_version=1')
        elif (self._db.execute('PRAGMA application_id').fetchone()!=(APP_ID,) or self._db.execute('PRAGMA user_version').fetchone()!=(1,)):
            raise ValueError('GG_OBSERVER_STORE_VERSION')

    def _put(self):
        raw=pack({'body':self._body,'signature':self._key.sign_message(HEAD+pack(self._body)).hex()})
        if len(raw)>MAX_RECORD:raise ValueError('GG_OBSERVER_STORE_SIZE')
        self._db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(raw,))

    def _commit(self):self._db.execute('COMMIT')

    def _write(self,changes):
        with self._lock:
            if self._closed or self._failed or self._body['fault']:raise ValueError(self._body['fault'] or 'GG_OBSERVER_STORE_NOT_WRITABLE')
            old=deepcopy(self._body)
            try:
                self._db.execute('BEGIN IMMEDIATE');self._body.update(deepcopy(changes));self._put();self._commit()
            except BaseException as error:
                self._body=old;self._failed=True
                try:
                    if self._db.in_transaction:self._db.execute('ROLLBACK')
                except sqlite3.Error:pass
                if not isinstance(error,Exception):raise
                raise ValueError('GG_OBSERVER_STORE_WRITE_FAILED') from None

    def claim_native_start(self):
        with self._lock:
            if self._closed or self._failed or getattr(self,'_native_pipe_closing',False) or self._body['fault']:raise ValueError(self._body['fault'] or 'GG_OBSERVER_STORE_NOT_WRITABLE')
            recovery=self._recovery_intent()
            if recovery is not None and not recovery['complete']:raise ValueError('GG_OBSERVER_RECOVERY_INCOMPLETE')
            root=self.root/'native'
            if any(is_link(path) for path in (root,*root.parents)):raise ValueError('GG_OBSERVER_NATIVE_PATH')
            if self._body['native_started']:
                if not root.is_dir():raise ValueError('GG_OBSERVER_NATIVE_HISTORY_MISSING')
                return False
            if root.exists():raise ValueError('GG_OBSERVER_NATIVE_FRESH_ROOT_REQUIRED')
            self._write({'native_started':True});return True

    def _recovery_intent(self):
        """Signed exact public intent; this never imports a consensus signer."""
        if self._body['schema'] in (SCHEMA,PUBLIC_SCHEMA):return None
        recovery=self._body.get('recovery')
        if (self._body['schema'] not in (RECOVERY_SCHEMA,PUBLIC_RECOVERY_SCHEMA) or not isinstance(recovery,dict)
                or set(recovery)!={'archive_sha256','certificate','complete'} or type(recovery['complete']) is not bool
                or type(recovery['archive_sha256']) is not str or not HASH.fullmatch(recovery['archive_sha256'])
                or self._body['native_started'] is not True):raise ValueError('GG_OBSERVER_RECOVERY_INTENT')
        floor=certificate_tip(recovery['certificate'],self.anchor())
        saved=self._body['certificate']
        if recovery['complete']:
            if saved is None:raise ValueError('GG_OBSERVER_RECOVERY_INTENT')
            tip=certificate_tip(saved,self.anchor())
            if tip[0]<floor[0] or tip[0]==floor[0] and tip!=floor:raise ValueError('GG_OBSERVER_RECOVERY_INTENT')
        elif saved is not None:
            tip=certificate_tip(saved,self.anchor())
            if tip[0]>floor[0] or tip[0]==floor[0] and tip!=floor:raise ValueError('GG_OBSERVER_RECOVERY_INTENT')
        return deepcopy(recovery)

    def prepare_recovery(self,archive,certificate):
        """Caller verified the exact archive and certificate in the native kernel."""
        with self._lock:
            if self._closed or self._failed or self._body['fault']:raise ValueError(self._body['fault'] or 'GG_OBSERVER_STORE_NOT_WRITABLE')
            if type(archive) is not str or not HASH.fullmatch(archive):raise ValueError('GG_OBSERVER_RECOVERY_INTENT')
            target=certificate_tip(certificate,self.anchor())
            if self._body['certificate'] is not None:
                floor=certificate_tip(self._body['certificate'],self.anchor())
                if target[0]<floor[0] or target[0]==floor[0] and target!=floor:raise ValueError('GG_OBSERVER_RECOVERY_CERTIFICATE_REWIND')
            root=self.root/'native'
            if any(is_link(path) for path in (root,*root.parents)):raise ValueError('GG_OBSERVER_NATIVE_PATH')
            previous=self._recovery_intent()
            if previous is not None:
                if not previous['complete'] or root.exists():
                    if previous['archive_sha256']!=archive or previous['certificate']!=certificate:
                        raise ValueError('GG_OBSERVER_RECOVERY_INTENT_CHANGED')
                    if previous['complete'] and self._body['certificate']!=certificate:
                        raise ValueError('GG_OBSERVER_RECOVERY_NODE_ALREADY_ADVANCED')
                    return previous
                # A lost public SDK store may be restored explicitly with the
                # same protected P2P identity and a non-rewinding certificate.
            if root.exists():
                raise ValueError('GG_OBSERVER_RECOVERY_FRESH_PROFILE_REQUIRED')
            intent={'archive_sha256':archive,'certificate':deepcopy(certificate),'complete':False}
            schema=PUBLIC_RECOVERY_SCHEMA if self._body['schema'] in PUBLIC_SCHEMAS else RECOVERY_SCHEMA
            self._write({'schema':schema,'native_started':True,'recovery':intent})
            return deepcopy(intent)

    def finish_recovery(self,archive,certificate):
        with self._lock:
            if self._closed or self._failed or self._body['fault']:raise ValueError(self._body['fault'] or 'GG_OBSERVER_STORE_NOT_WRITABLE')
            intent=self._recovery_intent()
            if intent is None or intent['archive_sha256']!=archive or intent['certificate']!=certificate:
                raise ValueError('GG_OBSERVER_RECOVERY_INTENT_CHANGED')
            if intent['complete']:
                if self._body['certificate']!=certificate:raise ValueError('GG_OBSERVER_RECOVERY_NODE_ALREADY_ADVANCED')
                return
            intent['complete']=True
            self._write({'recovery':intent,'certificate':deepcopy(certificate)})

    def remember_certificate(self,packet):
        """Structural monotonic floor only; SDK verification belongs to caller."""
        with self._lock:
            # A public light client independently verifies remote certificates
            # without creating a local SDK store. Preserve that distinction so
            # a later full replica can still reserve a genuinely fresh store.
            if self._body['schema'] not in PUBLIC_SCHEMAS and not self._body['native_started']:raise ValueError('GG_OBSERVER_CERTIFICATE_CONTEXT')
            recovery=self._recovery_intent()
            if recovery is not None and not recovery['complete']:raise ValueError('GG_OBSERVER_RECOVERY_INCOMPLETE')
            tip=certificate_tip(packet,self.anchor());old=self._body['certificate']
            if old is not None:
                previous=certificate_tip(old,self.anchor())
                if tip[0]<previous[0]:raise ValueError('GG_OBSERVER_CERTIFICATE_REWIND')
                if tip[0]==previous[0] and tip!=previous:raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            self._write({'certificate':packet})

    def remember_conflict(self,evidence):
        """Persist evidence only after the controller verifies BOTH SDK proofs."""
        with self._lock:
            validate_conflict_evidence(evidence,self.anchor())
            if self._body['certificate'] not in evidence['certificates']:raise ValueError('GG_OBSERVER_CONFLICT_CONTEXT')
            self._write({'fault':CONFLICT,'conflict_evidence':evidence})

    def native_node_signer(self):
        with self._lock:
            if self._closed or self._failed or getattr(self,'_native_pipe_closing',False) or self._key is None or self._body['fault']:raise ValueError('GG_OBSERVER_KEY_UNAVAILABLE')
            return self._key

    def anchor(self):
        if self._body['schema'] in PUBLIC_SCHEMAS:
            from backend.gg_financial_protocol import validate_pin
            return validate_pin(self._body['pin'])
        return anchor_from_bundle(self._body['bundle'],self._body['coordinator'])
    def public_grant(self):return deepcopy(self._body['grant'])
    def public_bundle(self):return deepcopy(self._body['bundle']),self._body['coordinator']
    def public_certificate(self):return deepcopy(self._body['certificate'])
    def public_conflict(self):return deepcopy(self._body['conflict_evidence'])

    def snapshot(self):
        public=self._body and self._body['schema'] in PUBLIC_SCHEMAS
        result={'profile':self.name,'role':'replica' if public else 'native_full_observer','scope':self._body['pin']['genesis']['protocol']['environment'] if public else 'PRIVATE_LAN_EXPERIMENT',
            'state':'CLOSED' if self._closed else 'FAULT' if self._failed or self._body and self._body['fault'] else 'BOUND',
            'keys_encrypted_at_rest':True,'consensus_signing':False,'voting_power':0,
            'native_started':bool(self._body and self._body['native_started']),
            'canonical_finality':False,'whole_disk_rollback_protection':False,'last_error':self._body['fault'] if self._body else ''}
        if self._body and self._body['schema'] in (RECOVERY_SCHEMA,PUBLIC_RECOVERY_SCHEMA):result['recovery_pending']=not self._body['recovery']['complete']
        return result

    def close(self):
        from backend.gg_native_pipe_lifecycle import fence_owner_close
        fence_owner_close(self)
        with self._lock:
            if self._db is not None:self._db.close();self._db=None
            self._key=None;self._closed=True
            if self._lease is not None:
                try:file_locks.flock(self._lease,file_locks.LOCK_UN)
                finally:os.close(self._lease);self._lease=None
