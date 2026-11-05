"""Explicit, exclusive and encrypted ownership of one native validator.

Only protected key bytes and signed public metadata reach SQLite. One profile
binds one immutable LAN anchor before native startup. Missing signing history
must never be replaced by a fresh validator state on resume.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading

from backend.application_paths import DATA_HOME
from backend.gg_ed25519 import Keypair,verify_signature
from backend.gg_node_store import pack,unpack,_private_path
from backend import gg_node_vault as vault
from backend.gg_consensus_membership import make_invite,validate_invite,anchor_from_bundle,SIG
from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory
from backend.platform_support import file_locks

ROOT=Path(DATA_HOME).expanduser().resolve()/'goldgoblins/consensus-validators'
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')
ROLES=('consensus_validator','consensus_node','consensus_account')
HEAD=b'GG-CONSENSUS-PROFILE-STATE-v1\0'
SQL="CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1),record BLOB NOT NULL CHECK(typeof(record)='blob'))"
MAX_RECORD=1024*1024
APP_ID=0x47474331


def profile_path(name):
    if not isinstance(name,str) or not NAME.fullmatch(name):raise ValueError('GG_VALIDATOR_PROFILE_NAME')
    root=Path(ROOT).absolute()
    if str(root).startswith(('\\\\','//')) or any(is_link(path) for path in (root,*root.parents)):
        raise ValueError('GG_VALIDATOR_PROFILE_PATH')
    return root/name


class ValidatorProfile:
    def __init__(self,name):
        self.name=name;self.root=profile_path(name);self._lock=threading.RLock()
        self._db=None;self._lease=None;self._keys=[];self._body=None;self._failed=False;self._closed=False

    def __repr__(self):return '<GG protected validator profile>'

    @classmethod
    def create_for_protocol(cls,name,owner,*,label,p2p_port,account):
        from backend.gg_node_store import NodeProfile
        from backend.gg_financial_account import AccountProfile
        if type(owner) is not NodeProfile or owner._lease is None or owner._db is None or owner._closed or owner._failed:raise ValueError('GG_VALIDATOR_OWNED_PROFILE_REQUIRED')
        if type(account) is not AccountProfile or account._lease is None or account._closed or account._failed:raise ValueError('GG_VALIDATOR_OWNED_ACCOUNT_REQUIRED')
        with account._lock,owner._lock:
            account._check()
            identity,_=owner.signers();descriptor=owner.descriptor()
            return cls._create_owned(name,identity,descriptor['host'],descriptor['port'],label,p2p_port,account=account)

    @classmethod
    def create(cls,name,peer,*,label,p2p_port):
        from backend.gg_lan_dag import LanDagPeer
        if not isinstance(peer,LanDagPeer):raise ValueError('GG_VALIDATOR_OWNER_REQUIRED')
        if peer.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        with peer._configuration,peer._lock:
            if peer._cancel.is_set() or peer._invite is None:raise ValueError('GG_VALIDATOR_PAIRED_OWNER_REQUIRED')
            return cls._create_owned(name,peer._identity,peer.host,peer.port,label,p2p_port)

    @classmethod
    def create_for_owned_profile(cls,name,owner,*,label,p2p_port):
        """Prepare fresh unbound keys offline; no peer/listener is fabricated."""
        from backend.gg_node_store import NodeProfile
        if not isinstance(owner,NodeProfile) or owner._lease is None or owner._db is None:
            raise ValueError('GG_VALIDATOR_OWNED_PROFILE_REQUIRED')
        with owner._lock:
            config=owner.descriptor();session=owner.session()
            if config.get('node_role')=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
            if session is None or session['body']['schema']!='gg.lan-dag.session.v4':
                raise ValueError('GG_NETWORK_TRANSITION_LEGACY_REQUIRED')
            identity,_=owner.signers()
            return cls._create_owned(name,identity,config['host'],config['port'],label,p2p_port)

    @classmethod
    def _create_owned(cls,name,identity,host,owner_port,label,p2p_port,*,account=None):
        if p2p_port==owner_port:raise ValueError('GG_VALIDATOR_PORT_CONFLICT')
        from backend.gg_consensus_membership import private_endpoint,label_wire
        private_endpoint(host,p2p_port);label_wire(label)
        profile=cls(name)
        try:
            if vault.provider()=='SCRYPT_AES256_GCM':
                from backend.portable_wallet_vault import require_unlocked
                require_unlocked()
            profile.root.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            set_private_mode(profile.root.parent,0o700);_private_path(profile.root.parent,0o700)
            try:profile.root.mkdir(mode=0o700)
            except FileExistsError:raise ValueError('GG_VALIDATOR_PROFILE_EXISTS_USE_RESUME') from None
            set_private_mode(profile.root,0o700);profile._acquire(create=True)
            profile._keys=[Keypair() for _ in (ROLES if account is None else ROLES[:2])]
            signers=profile._keys if account is None else [*profile._keys,account._key]
            invite=make_invite(*signers,identity,label=label,host=host,p2p_port=p2p_port,nonce=secrets.token_hex(32))
            protected=[]
            for role,key in zip(ROLES,profile._keys):
                public=key.pubkey().hex()
                cipher=vault.crypt(bytes(key),public,role,profile.root)
                protected.append({'public':public,'ciphertext':base64.b64encode(cipher).decode('ascii')})
            profile._body={'schema':'gg.consensus.profile.v1' if account is None else 'gg.consensus.profile.v2','key_storage':vault.provider(),'invite':invite,
                'protected_keys':protected,'anchor':None,'native_started':False,'certificate':None,'fault':''}
            if account is not None:profile._body['account_reference']={'profile':account.name,'public_key':account.public_address()}
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
            if (dict(profile._db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))!={'state':SQL}
                    or profile._db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()!=(0,)):
                raise ValueError('GG_VALIDATOR_STORE_SCHEMA')
            if profile._db.execute('PRAGMA quick_check(1)').fetchone()!=('ok',):raise ValueError('GG_VALIDATOR_STORE_CORRUPT')
            rows=list(profile._db.execute('SELECT id,length(record),typeof(record) FROM state'))
            if len(rows)!=1 or rows[0][0]!=1 or rows[0][2]!='blob' or not 0<rows[0][1]<=MAX_RECORD:
                raise ValueError('GG_VALIDATOR_STORE_RECORD')
            envelope=unpack(bytes(profile._db.execute('SELECT record FROM state WHERE id=1').fetchone()[0]))
            if not isinstance(envelope,dict) or set(envelope)!={'body','signature'}:raise ValueError('GG_VALIDATOR_STORE_HEAD')
            if not isinstance(envelope['signature'],str) or not SIG.fullmatch(envelope['signature']):raise ValueError('GG_VALIDATOR_STORE_HEAD')
            body=envelope['body']
            required={'schema','key_storage','invite','protected_keys','anchor','native_started','certificate','fault'}
            version=body.get('schema') if isinstance(body,dict) else None
            if version=='gg.consensus.profile.v2':required.add('account_reference')
            if (not isinstance(body,dict) or not required<=set(body) or set(body)-required-{'pending_checkpoint','last_checkpoint','conflict_evidence','admitted_observers','protocol_governance'}
                    or version not in ('gg.consensus.profile.v1','gg.consensus.profile.v2') or type(body['native_started']) is not bool
                    or body['key_storage'] not in ('WINDOWS_DPAPI','SCRYPT_AES256_GCM')
                    or not isinstance(body['protected_keys'],list) or len(body['protected_keys'])!=(2 if version=='gg.consensus.profile.v2' else 3)
                    or body['fault'] not in ('','GG_CONSENSUS_CONFLICTING_CERTIFICATE')):raise ValueError('GG_VALIDATOR_STORE_RECORD')
            public=validate_invite(body['invite'])
            if version=='gg.consensus.profile.v2':
                from backend.gg_financial_account import NAME as ACCOUNT_NAME
                reference=body['account_reference']
                if (not isinstance(reference,dict) or set(reference)!={'profile','public_key'} or type(reference['profile']) is not str
                        or not ACCOUNT_NAME.fullmatch(reference['profile']) or reference['public_key']!=public['account_key']):raise ValueError('GG_VALIDATOR_ACCOUNT_REFERENCE')
            verify_signature(bytes.fromhex(public['validator_key']),HEAD+pack(body),bytes.fromhex(envelope['signature']))
            for role,name,row in zip(ROLES,('validator_key','node_key','account_key'),body['protected_keys']):
                if not isinstance(row,dict) or set(row)!={'public','ciphertext'} or row['public']!=public[name]:raise ValueError('GG_VALIDATOR_VAULT_INVALID')
                cipher=base64.b64decode(row['ciphertext'],validate=True)
                raw=vault.crypt(cipher,row['public'],role,profile.root,decrypt=True,storage=body['key_storage'])
                if len(raw)!=64 or raw[32:].hex()!=row['public']:raise ValueError('GG_VALIDATOR_VAULT_INVALID')
                key=Keypair.from_seed(raw[:32]);del raw
                if key.pubkey().hex()!=row['public']:raise ValueError('GG_VALIDATOR_VAULT_INVALID')
                profile._keys.append(key)
            profile._body=body
            if body['anchor'] is not None:profile._validate_anchor(body['anchor'])
            elif body['native_started']:raise ValueError('GG_VALIDATOR_ANCHOR_REQUIRED')
            if 'admitted_observers' in body:profile._observer_document(body['admitted_observers'])
            if 'protocol_governance' in body:
                from backend.gg_protocol_operations import validate_governance_record
                validate_governance_record(body['protocol_governance'],profile.public_invite()['body'])
            if body['certificate'] is not None:
                if not body['native_started'] and body.get('conflict_evidence') is None:raise ValueError('GG_VALIDATOR_CERTIFICATE_CONTEXT')
                profile._certificate_tip(body['certificate'])
            if body.get('conflict_evidence') is not None:profile._validate_conflict(body['conflict_evidence'])
            if body.get('pending_checkpoint') is not None:profile._validate_pending(body['pending_checkpoint'])
            previous=body.get('last_checkpoint')
            if previous is not None and (not isinstance(previous,dict) or set(previous)!={'state','blocks','certificate_height'}
                    or previous['state'] not in ('DAG_BLOCKS_CERTIFIED','SUPERSEDED') or type(previous['blocks']) is not int or not 1<=previous['blocks']<=128
                    or type(previous['certificate_height']) is not int or not 1<=previous['certificate_height']<2**63):raise ValueError('GG_VALIDATOR_CHECKPOINT_RECORD')
            return profile
        except sqlite3.Error as error:
            profile.close();code=getattr(error,'sqlite_errorcode',0)&255
            raise ValueError('GG_VALIDATOR_PROFILE_IN_USE' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'GG_VALIDATOR_STORE_CORRUPT') from None
        except (ValueError,KeyError,TypeError,UnicodeError) as error:
            profile.close()
            if isinstance(error,ValueError) and str(error)=='GG_VALIDATOR_PROFILE_IN_USE':
                raise ValueError('GG_VALIDATOR_PROFILE_IN_USE') from None
            raise ValueError('GG_VALIDATOR_PROFILE_INVALID_OR_UNAVAILABLE') from None
        except BaseException:
            profile.close();raise

    def _acquire(self,*,create):
        if not self.root.is_dir() or any(is_link(path) for path in (self.root,*self.root.parents)):
            raise ValueError('GG_VALIDATOR_PROFILE_MISSING_OR_LINK')
        _private_path(self.root.parent,0o700);_private_path(self.root,0o700)
        path=self.root/'owner.lock';flags=os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0)
        try:self._lease=secure_open(path,flags,0o600)
        except FileNotFoundError:raise ValueError('GG_VALIDATOR_PROFILE_LOCK_MISSING') from None
        if create:os.write(self._lease,b'0');os.fsync(self._lease)
        info=os.fstat(self._lease)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=1:raise ValueError('GG_VALIDATOR_PROFILE_LOCK_INVALID')
        _private_path(path,0o600)
        try:file_locks.flock(self._lease,file_locks.LOCK_EX|file_locks.LOCK_NB)
        except BlockingIOError:
            os.close(self._lease);self._lease=None
            raise ValueError('GG_VALIDATOR_PROFILE_IN_USE') from None

    def _connect(self,*,create):
        path=self.root/'validator.sqlite3'
        try:descriptor=secure_open(path,os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0),0o600)
        except FileNotFoundError:raise ValueError('GG_VALIDATOR_STORE_MISSING') from None
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>4*1024*1024:raise ValueError('GG_VALIDATOR_STORE_FILE')
        finally:os.close(descriptor)
        _private_path(path,0o600)
        self._db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None,check_same_thread=False)
        if self._db.execute('PRAGMA page_size').fetchone()!=(4096,):raise ValueError('GG_VALIDATOR_STORE_PAGE_SIZE')
        self._db.execute('PRAGMA trusted_schema=OFF');self._db.execute('PRAGMA temp_store=MEMORY');self._db.execute('PRAGMA cache_size=-2048')
        if self._db.execute('PRAGMA journal_mode=DELETE').fetchone()!=('delete',):raise ValueError('GG_VALIDATOR_STORE_DURABILITY')
        self._db.execute('PRAGMA synchronous=EXTRA')
        if self._db.execute('PRAGMA synchronous').fetchone()!=(3,):raise ValueError('GG_VALIDATOR_STORE_DURABILITY')
        if self._db.execute('PRAGMA locking_mode=EXCLUSIVE').fetchone()!=('exclusive',):raise ValueError('GG_VALIDATOR_STORE_LOCKING')
        self._db.execute('BEGIN EXCLUSIVE');self._db.execute('COMMIT');self._db.execute('PRAGMA max_page_count=1024')
        if create:self._db.execute('PRAGMA application_id='+str(APP_ID));self._db.execute('PRAGMA user_version=1')
        elif (self._db.execute('PRAGMA application_id').fetchone()!=(APP_ID,) or self._db.execute('PRAGMA user_version').fetchone()!=(1,)):
            raise ValueError('GG_VALIDATOR_STORE_VERSION')

    def _put(self):
        raw=pack({'body':self._body,'signature':self._keys[0].sign_message(HEAD+pack(self._body)).hex()})
        if len(raw)>MAX_RECORD:raise ValueError('GG_VALIDATOR_STORE_SIZE')
        self._db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(raw,))

    def _commit(self):self._db.execute('COMMIT')

    def _write(self,changes):
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_VALIDATOR_STORE_NOT_WRITABLE')
            old=deepcopy(self._body)
            try:
                self._db.execute('BEGIN IMMEDIATE');self._body.update(deepcopy(changes));self._put();self._commit()
            except BaseException as error:
                self._body=old;self._failed=True
                try:
                    if self._db.in_transaction:self._db.execute('ROLLBACK')
                except sqlite3.Error:pass
                if not isinstance(error,Exception):raise
                raise ValueError('GG_VALIDATOR_STORE_WRITE_FAILED') from None

    def _validate_anchor(self,anchor):
        if isinstance(anchor,dict) and anchor.get('schema')=='gg.native.protocol-profile-anchor.v1':
            from backend import gg_financial_protocol as protocol
            if set(anchor)!={'schema','pin','membership_context'}:raise ValueError('GG_VALIDATOR_PROTOCOL_ANCHOR')
            pin=protocol.validate_pin(anchor['pin']);committee=pin['genesis']['protocol']['committee']
            if anchor['membership_context'] is not None:
                context=anchor['membership_context'];packet={**deepcopy(context),**pin,'schema':'gg.consensus.proof.v1'}
                protocol.verify_selected(packet,pin);committee=context['state']['protocol']['committee']
                if context['state']['protocol'].get('pending_committee'):committee=context['state']['protocol']['pending_committee']['next']
            own=self._body['invite']['body']
            if not any(all(member[key]==own[key] for key in ('validator_key','node_key','account_key','owner_peer_key')) for member in committee['members']):
                raise ValueError('GG_VALIDATOR_NOT_A_MEMBER')
            return pin
        if not isinstance(anchor,dict) or set(anchor)!={'bundle','coordinator','genesis_hash'}:raise ValueError('GG_VALIDATOR_ANCHOR')
        if self._body['schema']=='gg.consensus.profile.v2':raise ValueError('GG_VALIDATOR_PROTOCOL_ANCHOR_REQUIRED')
        derived=anchor_from_bundle(anchor['bundle'],anchor['coordinator'])
        if derived['genesis_hash']!=anchor['genesis_hash']:raise ValueError('GG_VALIDATOR_ANCHOR')
        matches=[invite for invite in derived['genesis']['membership']['validators'] if invite==self._body['invite']]
        if len(matches)!=1:raise ValueError('GG_VALIDATOR_NOT_A_MEMBER')
        return derived

    def bind_protocol(self,pin,*,membership_context=None,account=None):
        reference=self.account_reference()
        if reference is not None:
            from backend.gg_financial_account import AccountProfile
            if (type(account) is not AccountProfile or account._lease is None or account.name!=reference['profile']
                    or account.public_address()!=reference['public_key']):raise ValueError('GG_VALIDATOR_OWNED_ACCOUNT_REQUIRED')
        from contextlib import nullcontext
        with (account._lock if reference is not None else nullcontext()),self._lock:
            if reference is not None:account._check()
            if self._closed or self._failed or self._body['fault']:raise ValueError('GG_VALIDATOR_STORE_NOT_WRITABLE')
            if self._body.get('protocol_governance') is not None and self._body['protocol_governance']['pin']!=pin:raise ValueError('GG_VALIDATOR_NETWORK_ALREADY_BOUND')
            desired={'schema':'gg.native.protocol-profile-anchor.v1','pin':deepcopy(pin),'membership_context':deepcopy(membership_context)}
            derived=self._validate_anchor(desired)
            if self._body['anchor'] is not None and self._body['anchor']!=desired:raise ValueError('GG_VALIDATOR_ANCHOR_ALREADY_BOUND')
            # Reject an invalid membership/anchor before irreversibly binding
            # the independently owned account journal to that network.
            if reference is not None:account.bind(derived)
            if self._body['anchor'] is None:self._write({'anchor':desired})
            return derived

    def bind_anchor(self,bundle,coordinator):
        with self._lock:
            if self._body['schema']=='gg.consensus.profile.v2':raise ValueError('GG_VALIDATOR_PROTOCOL_ANCHOR_REQUIRED')
            if self._closed or self._failed:raise ValueError('GG_VALIDATOR_STORE_NOT_WRITABLE')
            derived=anchor_from_bundle(bundle,coordinator)
            desired={'bundle':deepcopy(bundle),'coordinator':coordinator,'genesis_hash':derived['genesis_hash']}
            self._validate_anchor(desired)
            if self._body['anchor'] is not None:
                if desired!=self._body['anchor']:raise ValueError('GG_VALIDATOR_ANCHOR_ALREADY_BOUND')
                return deepcopy(derived)
            self._write({'anchor':desired});return deepcopy(derived)

    def claim_native_start(self):
        """Commit startup intent before handing a signer to a child process."""
        with self._lock:
            if self._closed or self._failed or getattr(self,'_native_pipe_closing',False) or self._body['fault']:raise ValueError(self._body['fault'] or 'GG_VALIDATOR_STORE_NOT_WRITABLE')
            if self._body['anchor'] is None:raise ValueError('GG_VALIDATOR_ANCHOR_REQUIRED')
            root=self.root/'native'
            if any(is_link(path) for path in (root,*root.parents)):raise ValueError('GG_VALIDATOR_NATIVE_PATH')
            if self._body['native_started']:
                if not root.is_dir():raise ValueError('GG_VALIDATOR_NATIVE_HISTORY_MISSING')
                return False
            if root.exists():raise ValueError('GG_VALIDATOR_NATIVE_FRESH_ROOT_REQUIRED')
            self._write({'native_started':True});return True

    def _observer_document(self,grants):
        from backend.gg_native_observer import admission_document
        anchor=self._body['anchor']
        if anchor is None:raise ValueError('GG_VALIDATOR_ANCHOR_REQUIRED')
        return admission_document(grants,anchor['bundle'],anchor['coordinator'])

    def admit_observer(self,grant):
        """Durable, bounded optional peer admission; no membership/vote change."""
        with self._lock:
            if self._closed or self._failed or self._body['fault']:raise ValueError('GG_VALIDATOR_STORE_NOT_WRITABLE')
            current=deepcopy(self._body.get('admitted_observers',[]))
            candidate=current if grant in current else [*current,deepcopy(grant)]
            document=self._observer_document(candidate)
            if document['grants']!=current:self._write({'admitted_observers':document['grants']})
            if self._body['native_started']:self.publish_native_admissions()
            return deepcopy(document)

    def publish_native_admissions(self):
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_VALIDATOR_STORE_NOT_WRITABLE')
            if not self._body.get('admitted_observers'):return
            from backend.gg_native_observer import publish_admissions
            anchor=self._body['anchor']
            publish_admissions(self.root/'native',self._body['admitted_observers'],anchor['bundle'],anchor['coordinator'])

    def _certificate_tip(self,packet):
        """Structural pin only; the controller MUST also run the SDK verifier."""
        anchor=self.anchor()
        if anchor is not None and anchor['genesis']['schema']=='gg.native.genesis.v7':
            from backend.gg_dag_checkpoint import certificate_tip
            return certificate_tip(packet,anchor)
        if (anchor is None or not isinstance(packet,dict) or len(pack(packet))>256*1024
                or set(packet)!={'schema','genesis','genesis_hash','state','signed_header'} or packet['schema']!='gg.consensus.proof.v1'
                or packet['genesis']!=anchor['genesis'] or packet['genesis_hash']!=anchor['genesis_hash']):raise ValueError('GG_VALIDATOR_CERTIFICATE_CONTEXT')
        try:
            height=packet['state']['height'];root=packet['state']['state_root'];block=packet['signed_header']['commit']['block_id']['hash']
            certificate_height=packet['signed_header']['header']['height']
            if (type(height) is not int or not 0<=height<2**63-1 or not isinstance(root,str) or not re.fullmatch(r'[0-9a-f]{64}',root)
                    or not isinstance(block,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',block)
                    or not isinstance(certificate_height,str) or certificate_height!=str(height+1)):
                raise ValueError()
            return height+1,block.lower()
        except (KeyError,TypeError,ValueError):raise ValueError('GG_VALIDATOR_CERTIFICATE_CONTEXT') from None

    def remember_certificate(self,packet):
        """Persist an SDK-verified controller observation before publishing it."""
        with self._lock:
            if self._closed or self._failed or self._body['fault']:raise ValueError(self._body['fault'] or 'GG_VALIDATOR_STORE_NOT_WRITABLE')
            if not self._body['native_started']:raise ValueError('GG_VALIDATOR_NATIVE_START_REQUIRED')
            tip=self._certificate_tip(packet);previous=self._body['certificate']
            if previous is not None:
                old=self._certificate_tip(previous)
                if tip[0]<old[0]:raise ValueError('GG_VALIDATOR_CERTIFICATE_REWIND')
                if tip[0]==old[0]:
                    if tip!=old:
                        from backend.gg_dag_checkpoint import make_conflict_evidence
                        self.remember_conflict(make_conflict_evidence(previous,packet,self.anchor()))
                        raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
                    return
            self._write({'certificate':deepcopy(packet)})

    def _validate_conflict(self,evidence):
        from backend.gg_dag_checkpoint import validate_conflict_evidence,CONFLICT
        validate_conflict_evidence(evidence,self.anchor())
        certificate=self._body['certificate']
        if (self._body['fault']!=CONFLICT or certificate is None
                or evidence['height']>self._certificate_tip(certificate)[0]):raise ValueError('GG_VALIDATOR_CONFLICT_CONTEXT')

    def remember_conflict(self,evidence):
        """Both packets must be SDK-verified by the controller BEFORE this write."""
        from backend.gg_dag_checkpoint import validate_conflict_evidence,CONFLICT
        with self._lock:
            if self._closed or self._failed:raise ValueError('GG_VALIDATOR_STORE_NOT_WRITABLE')
            validate_conflict_evidence(evidence,self.anchor())
            if self._body.get('conflict_evidence') is not None:return
            previous=self._body['certificate']
            candidates=([previous] if previous is not None else [])+[evidence['certificates'][0]]
            packet=max(candidates,key=lambda packet:self._certificate_tip(packet)[0])
            self._write({'certificate':deepcopy(packet),'fault':CONFLICT,'conflict_evidence':deepcopy(evidence)})

    def public_conflict(self):return deepcopy(self._body.get('conflict_evidence'))

    def _validate_pending(self,value):
        anchor=self.anchor()
        if (anchor is None or not self._body['native_started'] or not isinstance(value,dict)
                or set(value)!={'schema','genesis_hash','previous','sequence','block_ids','hash','state'}
                or value['schema']!='gg.dag.pending-checkpoint.v1' or value['genesis_hash']!=anchor['genesis_hash']
                or any(not isinstance(value[key],str) or not re.fullmatch(r'[0-9a-f]{64}',value[key]) for key in ('previous','hash'))
                or type(value['sequence']) is not int or not 1<=value['sequence']<=4095
                or value['state'] not in ('PREPARED','MEMPOOL_ACCEPTED','REJECTED','BROADCAST_UNKNOWN')
                or not isinstance(value['block_ids'],list) or not 1<=len(value['block_ids'])<=128
                or any(not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key) for key in value['block_ids'])
                or len(set(value['block_ids']))!=len(value['block_ids'])):raise ValueError('GG_VALIDATOR_PENDING_CHECKPOINT')

    def prepare_checkpoint(self,value):
        with self._lock:
            self._validate_pending(value)
            certificate=self._body['certificate'];dag=certificate['state'].get('dag') if certificate else None
            if (self._body['fault'] or dag is None or value['state']!='PREPARED' or value['previous']!=dag['manifest_hash']
                    or value['sequence']!=dag['checkpoint']+1):raise ValueError('GG_VALIDATOR_PENDING_CERTIFICATE_CONTEXT')
            if self._body.get('pending_checkpoint') is not None:raise ValueError('GG_VALIDATOR_PENDING_UNRESOLVED')
            self._write({'pending_checkpoint':value})

    def checkpoint_outcome(self,identifier,state):
        with self._lock:
            pending=self._body.get('pending_checkpoint')
            if pending is None or pending['hash']!=identifier or state not in ('MEMPOOL_ACCEPTED','REJECTED','BROADCAST_UNKNOWN'):
                raise ValueError('GG_VALIDATOR_CHECKPOINT_OUTCOME')
            if pending['state']!=state:self._write({'pending_checkpoint':{**pending,'state':state}})

    def resolve_checkpoint(self,certified_ids,certificate_height):
        # The controller has SDK-verified complete order pages, and its
        # certificate is durably stored before calling this structural gate.
        with self._lock:
            pending=self._body.get('pending_checkpoint');certificate=self._body['certificate']
            if pending is None:return
            if (certificate is None or self._certificate_tip(certificate)[0]!=certificate_height
                    or certificate['state']['dag']['manifest_hash']==pending['previous']):raise ValueError('GG_VALIDATOR_PENDING_UNRESOLVED')
            result='DAG_BLOCKS_CERTIFIED' if all(key in certified_ids for key in pending['block_ids']) else 'SUPERSEDED'
            self._write({'pending_checkpoint':None,'last_checkpoint':{'state':result,'blocks':len(pending['block_ids']),'certificate_height':certificate_height}})

    def pending_checkpoint(self):return deepcopy(self._body.get('pending_checkpoint'))

    def public_certificate(self):return deepcopy(self._body['certificate'])

    def public_invite(self):return deepcopy(self._body['invite'])
    def account_reference(self):return deepcopy(self._body.get('account_reference'))
    def anchor(self):return self._validate_anchor(self._body['anchor']) if self._body['anchor'] is not None else None
    def native_signers(self):
        with self._lock:
            expected=2 if self._body and self._body.get('schema')=='gg.consensus.profile.v2' else 3
            if self._closed or self._failed or getattr(self,'_native_pipe_closing',False) or self._body is None or self._body['fault'] or len(self._keys)!=expected:raise ValueError('GG_VALIDATOR_KEYS_UNAVAILABLE')
            return self._keys[0],self._keys[1]

    def snapshot(self):
        stored=self._body.get('anchor') if self._body else None
        scope=stored['pin']['genesis']['protocol']['environment'] if stored and stored.get('schema')=='gg.native.protocol-profile-anchor.v1' else 'PRIVATE_LAN_EXPERIMENT'
        return {'profile':self.name,'role':'validator','scope':scope,
            'state':'CLOSED' if self._closed else 'FAULT' if self._failed or self._body and self._body['fault'] else 'BOUND' if self._body and self._body['anchor'] is not None else 'UNBOUND',
            'keys_encrypted_at_rest':True,'native_started':bool(self._body and self._body['native_started']),
            'whole_disk_rollback_protection':False,'canonical_finality':False,'last_error':self._body['fault'] if self._body else '',
            'checkpoint':{'state':self._body['pending_checkpoint']['state'],'blocks':len(self._body['pending_checkpoint']['block_ids'])}
                if self._body and self._body.get('pending_checkpoint') else deepcopy(self._body.get('last_checkpoint')) if self._body else None}

    def close(self):
        from backend.gg_native_pipe_lifecycle import fence_owner_close
        fence_owner_close(self)
        with self._lock:
            if self._db is not None:self._db.close();self._db=None
            self._keys.clear();self._closed=True
            if self._lease is not None:
                try:file_locks.flock(self._lease,file_locks.LOCK_UN)
                finally:os.close(self._lease);self._lease=None
