"""Independent protected native account and durable exact payment originals.

No import-time key, database, process, listener or network operation. An account
has no node/producer/voter authority. Signing is an explicit finite operation.
Nonce consumption is not attribution of a particular payment's receipt.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading

from backend.application_paths import DATA_HOME
from backend import gg_protected_journal as journals
from backend import gg_financial_dag as financial,gg_financial_wire as wire,gg_node_vault as vault
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_dag_segmented import validate_native_pin
from backend.gg_ed25519 import Keypair,verify_signature
from backend.gg_node_store import pack,unpack,_private_path
from backend.gg_consensus_membership import label_wire
from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory
from backend.platform_support import file_locks

ROOT=Path(DATA_HOME).expanduser().resolve()/'goldgoblins/financial-accounts'
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')
DOMAIN=b'GG-FINANCIAL-ACCOUNT-PROFILE-v1\0'
SCHEMA='gg.financial.account-profile.v1'
PROTOCOL_SCHEMA='gg.financial.account-profile.v2'
ARCHIVE_SCHEMA='gg.financial.account-profile.v3'
ARCHIVE_PROTOCOL_SCHEMA='gg.financial.account-profile.v4'
MAX_RECORD=1024*1024
MAX_FILE=2*1024**3
MAX_BATCHES=65535
MAX_NONCE=2**64-1
APP_ID=0x47474131
BASE={'schema','genesis','genesis_hash','state','signed_header'}
SQL={
 'state':"CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1),record BLOB NOT NULL CHECK(typeof(record)='blob'))",
 'batches':"CREATE TABLE batches(id INTEGER PRIMARY KEY CHECK(id>0),start_nonce TEXT NOT NULL,end_nonce TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL UNIQUE,document BLOB NOT NULL CHECK(typeof(document)='blob'))"
}
FIELDS={'schema','public_key','label','key_storage','protected_key','anchor','next_nonce','batch_count','batch_head','certificate','fault'}
ARCHIVE_FIELDS=FIELDS|{'journal'}
SQL_ARCHIVE={**SQL,**journals.CATALOG_SQL}
FAULTS=('', 'GG_ACCOUNT_CONFLICTING_CERTIFICATE','GG_ACCOUNT_UNEXPECTED_NONCE')
_REVIEW_TOKEN=object()


def _new_key():return Keypair()


def profile_path(name):
    if type(name) is not str or not NAME.fullmatch(name):raise ValueError('GG_ACCOUNT_PROFILE_NAME')
    root=Path(ROOT).absolute()
    if str(root).startswith(('\\\\','//')) or any(is_link(path) for path in (root,*root.parents)):raise ValueError('GG_ACCOUNT_PROFILE_PATH')
    return root/name


def _empty(address):return hashlib.sha256(DOMAIN+b'EMPTY\0'+address.encode('ascii')).hexdigest()


class _AccountReview:
    """Immutable in-process intent; never constructible from peer JSON."""
    __slots__=('_owner','_anchor','_head','_context','_start','_outputs','_fees')
    def __init__(self,owner,anchor,head,context,start,outputs,*,fees=None,token=None):
        if token is not _REVIEW_TOKEN:raise ValueError('GG_ACCOUNT_REVIEW_REQUIRED')
        for name,value in zip(self.__slots__,(owner,anchor,head,context,start,tuple(outputs),tuple(fees or ('0',)*len(outputs)))):object.__setattr__(self,name,value)
    def __setattr__(self,name,value):raise AttributeError('immutable payment review')
    def __repr__(self):return '<GG reviewed public payment intent>'
    def summary(self):
        return {'sender':self._owner[1],'payments':len(self._outputs),'total_atomic':str(sum(int(amount) for _,amount in self._outputs)),
                'max_total_fee_atomic':str(sum(int(fee) for fee in self._fees)),
                'first_nonce':str(self._start),'signatures_created':False,'payments_executed_asserted':False}


class _OperationReview:
    __slots__=('_owner','_head','_context','_intent','_fee','_replacement')
    def __init__(self,owner,head,context,intent,fee,replacement,*,token=None):
        if token is not _REVIEW_TOKEN:raise ValueError('GG_ACCOUNT_REVIEW_REQUIRED')
        for name,value in zip(self.__slots__,(owner,head,context,pack(intent),pack(fee),replacement)):object.__setattr__(self,name,value)
    def __setattr__(self,name,value):raise AttributeError('immutable operation review')
    def summary(self):
        fee=unpack(self._fee);intent=unpack(self._intent)
        return {'kind':next(iter(intent)),'sender':fee['sender'],'nonce':fee['nonce'],'operation_root':fee['operation_root'],
                'max_fee_atomic':fee['max_fee_atomic'],'replaces_pending_nonce':self._replacement,
                'signatures_created':False,'payment_execution_asserted':False}


class AccountProfile:
    def __init__(self,name,*,binary=None,stamp=None):
        self.name=name;self.root=profile_path(name);self._lock=threading.RLock()
        self._db=None;self._lease=None;self._key=None;self._body=None;self._record_hash=None
        self._closed=False;self._failed=False;self._account=None;self._tip=None
        self._db_changes=0;self._db_version=None;self._review_owner=object()
        # Owned verifier configuration only; no serialized peer value sets it.
        self._binary=binary;self._stamp=stamp;self._segments=None;self._journal_view=None;self._store_version=1
        self._latest_nonce_batch=None;self._latest_cancel_batch=None

    def __repr__(self):return '<GG independent protected account profile>'

    @classmethod
    def create(cls,name,*,label,binary=None,stamp=None):
        label_wire(label);profile=cls(name,binary=binary,stamp=stamp)
        try:
            if vault.provider()=='SCRYPT_AES256_GCM':
                from backend.portable_wallet_vault import require_unlocked
                require_unlocked()
            profile.root.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            set_private_mode(profile.root.parent,0o700);_private_path(profile.root.parent,0o700)
            try:profile.root.mkdir(mode=0o700)
            except FileExistsError:raise ValueError('GG_ACCOUNT_PROFILE_EXISTS_USE_OPEN') from None
            set_private_mode(profile.root,0o700);profile._acquire(create=True)
            profile._key=_new_key();address=profile._key.pubkey().hex()
            cipher=vault.crypt(bytes(profile._key),address,'financial_account',profile.root)
            profile._body={'schema':SCHEMA,'public_key':address,'label':label,'key_storage':vault.provider(),
                'protected_key':base64.b64encode(cipher).decode('ascii'),'anchor':None,'next_nonce':'0',
                'batch_count':0,'batch_head':_empty(address),'certificate':None,'fault':''}
            profile._connect(create=True);profile._db.execute('BEGIN IMMEDIATE')
            for sql in SQL.values():profile._db.execute(sql)
            profile._put();profile._commit();sync_directory(profile.root)
            return profile
        except BaseException:profile.close();raise

    @classmethod
    def open(cls,name,*,binary=None,stamp=None,check=lambda:None):
        profile=cls(name,binary=binary,stamp=stamp)
        try:
            profile._acquire(create=False);profile._connect(create=False)
            expected_sql=SQL if profile._store_version==1 else SQL_ARCHIVE
            actual_sql=dict(profile._db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
            if (actual_sql!=expected_sql
                    or profile._db.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()!=(0,)
                    or profile._db.execute('PRAGMA quick_check(1)').fetchone()!=('ok',)):raise ValueError('GG_ACCOUNT_STORE_SCHEMA')
            rows=list(profile._db.execute('SELECT id,length(record),typeof(record) FROM state'))
            if len(rows)!=1 or rows[0][0]!=1 or rows[0][2]!='blob' or not 0<rows[0][1]<=MAX_RECORD:raise ValueError('GG_ACCOUNT_STORE_RECORD')
            raw=bytes(profile._db.execute('SELECT record FROM state WHERE id=1').fetchone()[0]);envelope=unpack(raw)
            if not isinstance(envelope,dict) or set(envelope)!={'body','signature'}:raise ValueError('GG_ACCOUNT_STORE_RECORD')
            body=envelope['body']
            schema=body.get('schema') if isinstance(body,dict) else None
            archived=schema in (ARCHIVE_SCHEMA,ARCHIVE_PROTOCOL_SCHEMA)
            if (not isinstance(body,dict) or set(body)!=(ARCHIVE_FIELDS if archived else FIELDS)
                    or schema not in (SCHEMA,PROTOCOL_SCHEMA,ARCHIVE_SCHEMA,ARCHIVE_PROTOCOL_SCHEMA)
                    or archived!=(profile._store_version==2)
                    or body['key_storage'] not in ('WINDOWS_DPAPI','SCRYPT_AES256_GCM') or body['fault'] not in FAULTS
                    or (type(body['batch_count']) is not str if archived else type(body['batch_count']) is not int or not 0<=body['batch_count']<=MAX_BATCHES)
                    or type(body['protected_key']) is not str or len(body['protected_key'])>8192):raise ValueError('GG_ACCOUNT_STORE_RECORD')
            address=financial.account_address(body['public_key']);label_wire(body['label'])
            wire.counter(body['next_nonce'],maximum=MAX_NONCE)
            if type(body['batch_head']) is not str or not wire.HASH.fullmatch(body['batch_head']):raise ValueError('GG_ACCOUNT_STORE_RECORD')
            signature=envelope['signature']
            if type(signature) is not str or not wire.SIGNATURE.fullmatch(signature):raise ValueError('GG_ACCOUNT_STORE_RECORD')
            verify_signature(bytes.fromhex(address),DOMAIN+b'HEAD\0'+pack(body),bytes.fromhex(signature))
            cipher=base64.b64decode(body['protected_key'],validate=True)
            secret=vault.crypt(cipher,address,'financial_account',profile.root,decrypt=True,storage=body['key_storage'])
            if len(secret)!=64 or secret[32:].hex()!=address:raise ValueError('GG_ACCOUNT_VAULT_INVALID')
            profile._key=Keypair.from_seed(secret[:32]);del secret
            if profile._key.pubkey().hex()!=address:raise ValueError('GG_ACCOUNT_VAULT_INVALID')
            if archived:body['batch_count']=journals.number(body['batch_count'],allow_int=False)
            profile._body=body;profile._record_hash=hashlib.sha256(raw).digest()
            if body['anchor'] is not None:profile._validate_anchor(body['anchor'])
            elif body['certificate'] is not None or body['batch_count'] or body['next_nonce']!='0':raise ValueError('GG_ACCOUNT_ANCHOR_REQUIRED')
            if archived:
                journals.validate_head(body['journal'],'ACCOUNT_ORIGINALS',body['batch_count'])
                profile._segments=profile._new_segments()
            profile._replay_batches(check)
            profile._seal_store()
            if archived and body['journal']['pending'] is not None:profile._archive_prefix(check=check)
            if body['certificate'] is not None:
                result,tip=profile._verify_account(body['certificate']);profile._account=result;profile._tip=tip
                if profile._nonce(result)>int(body['next_nonce']) and body['fault']!='GG_ACCOUNT_UNEXPECTED_NONCE':raise ValueError('GG_ACCOUNT_STORE_NONCE')
            profile._seal_store()
            return profile
        except sqlite3.Error as error:
            profile.close();code=getattr(error,'sqlite_errorcode',0)&255
            raise ValueError('GG_ACCOUNT_PROFILE_IN_USE' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'GG_ACCOUNT_STORE_CORRUPT') from None
        except (ValueError,KeyError,TypeError,UnicodeError,OverflowError,RecursionError) as error:
            profile.close()
            if isinstance(error,ValueError) and str(error)=='GG_ACCOUNT_PROFILE_IN_USE':raise
            raise ValueError('GG_ACCOUNT_PROFILE_INVALID_OR_UNAVAILABLE') from None
        except BaseException:profile.close();raise

    def _acquire(self,*,create):
        if not self.root.is_dir() or any(is_link(path) for path in (self.root,*self.root.parents)):raise ValueError('GG_ACCOUNT_PROFILE_MISSING_OR_LINK')
        _private_path(self.root.parent,0o700);_private_path(self.root,0o700)
        path=self.root/'owner.lock'
        self._lease=secure_open(path,os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0),0o600)
        if create:os.write(self._lease,b'0');os.fsync(self._lease)
        info=os.fstat(self._lease)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=1:raise ValueError('GG_ACCOUNT_PROFILE_LOCK_INVALID')
        _private_path(path,0o600)
        try:file_locks.flock(self._lease,file_locks.LOCK_EX|file_locks.LOCK_NB)
        except BlockingIOError:
            os.close(self._lease);self._lease=None;raise ValueError('GG_ACCOUNT_PROFILE_IN_USE') from None

    def _connect(self,*,create):
        path=self.root/'account.sqlite3';fd=secure_open(path,os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0),0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_FILE:raise ValueError('GG_ACCOUNT_STORE_FILE')
        finally:os.close(fd)
        _private_path(path,0o600)
        self._db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None,check_same_thread=False)
        if self._db.execute('PRAGMA page_size').fetchone()!=(4096,):raise ValueError('GG_ACCOUNT_STORE_PAGE_SIZE')
        for sql in ('PRAGMA trusted_schema=OFF','PRAGMA temp_store=MEMORY','PRAGMA cache_size=-2048'):self._db.execute(sql)
        if self._db.execute('PRAGMA journal_mode=DELETE').fetchone()!=('delete',):raise ValueError('GG_ACCOUNT_STORE_DURABILITY')
        self._db.execute('PRAGMA synchronous=EXTRA')
        if self._db.execute('PRAGMA synchronous').fetchone()!=(3,):raise ValueError('GG_ACCOUNT_STORE_DURABILITY')
        if self._db.execute('PRAGMA locking_mode=EXCLUSIVE').fetchone()!=('exclusive',):raise ValueError('GG_ACCOUNT_STORE_LOCKING')
        self._db.execute('BEGIN EXCLUSIVE');self._db.execute('COMMIT');self._db.execute('PRAGMA max_page_count='+str(MAX_FILE//4096))
        if create:self._db.execute('PRAGMA application_id='+str(APP_ID));self._db.execute('PRAGMA user_version=1')
        else:
            self._store_version=self._db.execute('PRAGMA user_version').fetchone()[0]
            if self._db.execute('PRAGMA application_id').fetchone()!=(APP_ID,) or self._store_version not in (1,2):raise ValueError('GG_ACCOUNT_STORE_VERSION')

    def _put(self):
        body=deepcopy(self._body)
        if body['schema'] in (ARCHIVE_SCHEMA,ARCHIVE_PROTOCOL_SCHEMA):body['batch_count']=str(body['batch_count'])
        raw=pack({'body':body,'signature':self._key.sign_message(DOMAIN+b'HEAD\0'+pack(body)).hex()})
        if len(raw)>MAX_RECORD:raise ValueError('GG_ACCOUNT_STORE_SIZE')
        self._db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(raw,));self._record_hash=hashlib.sha256(raw).digest()

    def _seal_store(self):
        self._db_changes=self._db.total_changes;self._db_version=self._db.execute('PRAGMA data_version').fetchone()[0];self._refresh_journal_view()

    def _commit(self):self._db.execute('COMMIT');self._seal_store()

    def _check(self):
        if self._closed or self._failed or self._db is None or self._key is None:raise ValueError('GG_ACCOUNT_PROFILE_UNAVAILABLE')
        if self._body['fault']:raise ValueError(self._body['fault'])
        if self._db.total_changes!=self._db_changes or self._db.execute('PRAGMA data_version').fetchone()[0]!=self._db_version:
            self._failed=True;raise ValueError('GG_ACCOUNT_STORE_CHANGED')
        rows=self._db.execute('SELECT length(record),typeof(record) FROM state WHERE id=1').fetchone()
        if rows is None or rows[1]!='blob' or not 0<rows[0]<=MAX_RECORD:
            self._failed=True;raise ValueError('GG_ACCOUNT_STORE_CHANGED')
        raw=self._db.execute('SELECT record FROM state WHERE id=1').fetchone()[0]
        if hashlib.sha256(raw).digest()!=self._record_hash:
            self._failed=True;raise ValueError('GG_ACCOUNT_STORE_CHANGED')
        if self._segments is not None:
            try:self._segments.check_inventory(self._body['journal'],pending=self._body['journal']['pending'] is not None)
            except (ValueError,OSError,sqlite3.Error):
                self._failed=True;raise ValueError('GG_OWN_JOURNAL_UNAVAILABLE') from None

    def _write(self,changes,*,batch=None):
        self._check();old=deepcopy(self._body);old_hash=self._record_hash
        try:
            self._db.execute('BEGIN IMMEDIATE')
            if batch is not None:self._db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',batch)
            self._body.update(deepcopy(changes));self._put();self._commit()
        except BaseException as error:
            self._body=old;self._record_hash=old_hash;self._failed=True
            try:
                if self._db.in_transaction:self._db.execute('ROLLBACK')
            except sqlite3.Error:pass
            if not isinstance(error,Exception):raise
            raise ValueError('GG_ACCOUNT_STORE_WRITE_FAILED') from None

    def _validate_anchor(self,anchor):
        value=validate_native_pin(anchor)
        if (value['genesis']['schema'] not in ('gg.native.genesis.v6','gg.native.genesis.v7') or self._body['public_key'] in financial.reserved_account_keys(value['genesis'])
                or self._body['schema'] in (PROTOCOL_SCHEMA,ARCHIVE_PROTOCOL_SCHEMA) and value['genesis']['schema']!='gg.native.genesis.v7'):raise ValueError('GG_ACCOUNT_GENERAL_ANCHOR_REQUIRED')
        return value

    def bind(self,anchor):
        with self._lock:
            self._check();value=self._validate_anchor(anchor)
            if self._body['anchor'] is not None and self._body['anchor']!=value:raise ValueError('GG_ACCOUNT_NETWORK_ALREADY_BOUND')
            if self._body['anchor'] is None:self._write({'anchor':value,'schema':PROTOCOL_SCHEMA if value['genesis']['schema']=='gg.native.genesis.v7' else SCHEMA})
            return self.snapshot()

    @staticmethod
    def _nonce(result):return int(result['financial_account']['nonce']) if result['financial_account_exists'] else 0

    def _verify_account(self,packet):
        if self._body['anchor'] is None:raise ValueError('GG_ACCOUNT_ANCHOR_REQUIRED')
        result=financial.verify_account(packet,self._body['anchor'],self._body['public_key'],binary=self._binary,stamp=self._stamp)
        tip=certificate_tip({key:packet[key] for key in BASE},self._body['anchor'])
        return result,tip

    def remember_account(self,packet):
        """Store a verified floor; a certificate is not current network contact."""
        with self._lock:
            self._check();result,tip=self._verify_account(packet)
            if self._tip is not None:
                if tip[0]<self._tip[0]:raise ValueError('GG_ACCOUNT_CERTIFICATE_REWIND')
                if tip[0]==self._tip[0] and tip!=self._tip:
                    self._write({'fault':'GG_ACCOUNT_CONFLICTING_CERTIFICATE'});raise ValueError('GG_ACCOUNT_CONFLICTING_CERTIFICATE')
            if self._nonce(result)>int(self._body['next_nonce']):
                self._write({'certificate':deepcopy(packet),'fault':'GG_ACCOUNT_UNEXPECTED_NONCE'})
                self._account=result;self._tip=tip;raise ValueError('GG_ACCOUNT_UNEXPECTED_NONCE')
            if self._body['certificate']!=packet:self._write({'certificate':deepcopy(packet)})
            self._account=result;self._tip=tip;return self.snapshot()

    def review(self,outputs,packet,*,check=lambda:None):
        """Review finite recipient/amount intent against the caller's own proof."""
        with self._lock:
            self.remember_account(packet);self._check();result=self._account
            if not result['financial_account_exists']:raise ValueError('GG_ACCOUNT_UNFUNDED')
            start=self._nonce(result)
            if start!=int(self._body['next_nonce']):raise ValueError('GG_ACCOUNT_PENDING_ORIGINAL_REQUIRED')
            if not isinstance(outputs,list) or not 1<=len(outputs)<=wire.MAX_PAYMENTS or start+len(outputs)>MAX_NONCE:raise ValueError('GG_ACCOUNT_PAYMENT_COUNT')
            genesis=self._body['anchor']['genesis'];public=genesis['schema']=='gg.native.genesis.v7'
            maximum=int(genesis['protocol']['economics']['max_supply_atomic']) if public else 10**12
            address=self._body['public_key'];reserved=financial.reserved_account_keys(genesis);values=[];fees=[];total=0
            for row in outputs:
                check()
                if not isinstance(row,dict) or set(row)!={'recipient','amount_atomic'}:raise ValueError('GG_ACCOUNT_PAYMENT_INTENT')
                recipient=financial.account_address(row['recipient']);amount=wire.counter(row['amount_atomic'],positive=True,maximum=maximum)
                if recipient==address or recipient in reserved:raise ValueError('GG_ACCOUNT_PAYMENT_INTENT')
                fee='0'
                if public:
                    from backend.gg_financial_protocol import quote_payment
                    fee=quote_payment(genesis,self._body['anchor']['genesis_hash'],address,recipient,row['amount_atomic'],start+len(values))['max_fee_atomic']
                total+=amount+int(fee)
                if total>int(result['financial_account']['balance_atomic']):raise ValueError('GG_ACCOUNT_REVIEW_FUNDS')
                values.append((recipient,row['amount_atomic']));fees.append(fee)
            context=(start,result['financial_account']['balance_atomic'])
            return _AccountReview((self._review_owner,address),self._body['anchor']['genesis_hash'],self._body['batch_head'],context,start,values,fees=fees,token=_REVIEW_TOKEN)

    def sign(self,review,*,check=lambda:None):
        """Commit exact account-signed originals before exposing their bytes."""
        with self._lock:
            self._check();address=self._body['public_key'];anchor=self._body['anchor']
            context=(self._nonce(self._account),self._account['financial_account']['balance_atomic']) if self._account and self._account['financial_account_exists'] else None
            if (type(review) is not _AccountReview or anchor is None or review._owner!=(self._review_owner,address)
                    or review._anchor!=anchor['genesis_hash'] or review._head!=self._body['batch_head'] or review._context!=context
                    or review._start!=int(self._body['next_nonce'])):raise ValueError('GG_ACCOUNT_REVIEW_STALE_OR_FOREIGN')
            if self._body['batch_count']>=journals.MAX_POSITION:raise ValueError('GG_ACCOUNT_STORAGE_LIMIT')
            self._prepare_journal(check=check)
            payments=[]
            for offset,(recipient,amount) in enumerate(review._outputs):
                check();body={'version':1,'chain_id':anchor['genesis']['chain_id'],'genesis_hash':anchor['genesis_hash'],
                    'sender':address,'recipient':recipient,'amount_atomic':amount,'nonce':review._start+offset}
                if anchor['genesis']['schema']=='gg.native.genesis.v7':
                    from backend.gg_financial_protocol import quote_payment
                    body=quote_payment(anchor['genesis'],anchor['genesis_hash'],address,recipient,amount,review._start+offset)
                    if body['max_fee_atomic']!=review._fees[offset]:raise ValueError('GG_ACCOUNT_FEE_REVIEW_CHANGED')
                payments.append({'body':body,'signature':self._key.sign_message(pack(body)).hex()})
            raw=pack({'schema':wire.PAYMENT_DOCUMENT,'genesis_hash':anchor['genesis_hash'],'payments':payments})
            if len(raw)>wire.MAX_RAW:raise ValueError('GG_ACCOUNT_DOCUMENT_LIMIT')
            number=self._body['batch_count']+1;end=review._start+len(payments);previous=self._body['batch_head']
            link=self._batch_link(number,review._start,end,previous,hashlib.sha256(raw).hexdigest());check()
            self._write({'next_nonce':str(end),'batch_count':number,'batch_head':link},
                        batch=(number,str(review._start),str(end),previous,link,raw))
            self._latest_nonce_batch=(number,review._start,end)
            return raw

    def _original_for_nonce(self,nonce):
        """Find exact retained intent across segments, preferring cancellation."""
        if nonce>=int(self._body['next_nonce']):return None
        # These bounded local facts were derived by full cold replay or by the
        # exact successful protected commit, never by peer-supplied metadata.
        if self._latest_cancel_batch is not None and self._latest_cancel_batch[1]==nonce:
            return self.original(str(self._latest_cancel_batch[0]))
        if self._latest_nonce_batch is not None:
            batch,first,last=self._latest_nonce_batch
            if first<=nonce<last:return self.original(str(batch))
        latest_cancel=None;selected=None
        with closing(self._all_batches(reverse=True)) as rows:
            for index,meta,raw in rows:
                first,last=int(meta['start_nonce']),int(meta['end_nonce'])
                if first==last and latest_cancel is None:
                    from backend import gg_protocol_operations as operations
                    value=operations.decode_authorization(raw,self._body['anchor']);latest_cancel=int(value['fee']['body']['nonce'])
                    if latest_cancel==nonce:return self.original(str(index))
                if first<=nonce<last and selected is None:selected=index
                if selected is not None and latest_cancel is not None:break
        return None if selected is None else self.original(str(selected))

    def review_operation(self,intent,packet,*,max_fee=None,committee_packet=None):
        with self._lock:
            from backend import gg_protocol_operations as operations
            self.remember_account(packet);self._check();anchor=self._body['anchor']
            if anchor['genesis']['schema']!='gg.native.genesis.v7':raise ValueError('GG_FINANCIAL_PROTOCOL_REQUIRED')
            if not self._account['financial_account_exists']:raise ValueError('GG_ACCOUNT_UNFUNDED')
            intent=deepcopy(intent);nonce=self._nonce(self._account);replacement='cancel' in intent
            if replacement:
                if not nonce<int(self._body['next_nonce']):raise ValueError('GG_ACCOUNT_NO_PENDING_NONCE')
                original=self._original_for_nonce(nonce)
                if original is None:raise ValueError('GG_ACCOUNT_PENDING_ORIGINAL_REQUIRED')
                value=unpack(original)
                if value.get('schema')==operations.DOCUMENT:
                    previous=operations.decode_authorization(original,anchor)
                    if 'cancel' in previous['intent']:raise ValueError('GG_ACCOUNT_CANCELLATION_ORIGINAL_REQUIRED')
                    identifier=operations.authorization_id(previous['fee'])
                else:
                    payments=wire.decode_payment_document(original,anchor)
                    matches=[row for row in payments if int(row['body']['nonce'])==nonce]
                    if len(matches)!=1:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                    identifier=wire.intent_id(pack(matches[0]))
                expected={'genesis_hash':anchor['genesis_hash'],'nonce':str(nonce),'replaces':identifier,
                          'schema':'gg.financial.nonce-cancel.v1','sender':self.public_address()}
                if intent['cancel']!=expected:raise ValueError('GG_ACCOUNT_CANCEL_ORIGINAL_MISMATCH')
            elif nonce!=int(self._body['next_nonce']):raise ValueError('GG_ACCOUNT_PENDING_ORIGINAL_REQUIRED')
            if 'committee' in intent:
                if committee_packet is None:raise ValueError('GG_PROTOCOL_COMMITTEE_CONTEXT_REQUIRED')
                operations.verify_committee_intent(intent,committee_packet,anchor,binary=self._binary,stamp=self._stamp)
            fee=operations.fee_body(intent,anchor,self.public_address(),nonce,max_fee)
            if int(fee['max_fee_atomic'])>int(self._account['financial_account']['balance_atomic']):raise ValueError('GG_ACCOUNT_REVIEW_FUNDS')
            context=(nonce,self._account['financial_account']['balance_atomic'],anchor['genesis_hash'])
            return _OperationReview((self._review_owner,self.public_address()),self._body['batch_head'],context,intent,fee,replacement,token=_REVIEW_TOKEN)

    def review_cancellation(self,packet,*,max_fee=None):
        with self._lock:
            from backend import gg_protocol_operations as operations
            self.remember_account(packet);nonce=self._nonce(self._account);raw=self._original_for_nonce(nonce)
            if raw is None:raise ValueError('GG_ACCOUNT_NO_PENDING_NONCE')
            value=unpack(raw)
            if value.get('schema')==operations.DOCUMENT:
                value=operations.decode_authorization(raw,self._body['anchor']);identifier=operations.authorization_id(value['fee'])
            else:
                matches=[row for row in wire.decode_payment_document(raw,self._body['anchor']) if int(row['body']['nonce'])==nonce]
                if len(matches)!=1:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                identifier=wire.intent_id(pack(matches[0]))
            return self.review_operation({'cancel':{'genesis_hash':self._body['anchor']['genesis_hash'],'nonce':str(nonce),
                'replaces':identifier,'schema':'gg.financial.nonce-cancel.v1','sender':self.public_address()}},packet,max_fee=max_fee)

    def sign_operation(self,review,*,check=lambda:None):
        with self._lock:
            from backend import gg_protocol_operations as operations
            self._check();anchor=self._body['anchor'];result=self._account
            context=(self._nonce(result),result['financial_account']['balance_atomic'],anchor['genesis_hash']) if result and result['financial_account_exists'] and anchor else None
            if (type(review) is not _OperationReview or review._owner!=(self._review_owner,self.public_address())
                    or review._head!=self._body['batch_head'] or review._context!=context):raise ValueError('GG_ACCOUNT_REVIEW_STALE_OR_FOREIGN')
            body=unpack(review._fee);intent=unpack(review._intent);start=int(self._body['next_nonce']);end=start if review._replacement else start+1
            if (not review._replacement and int(body['nonce'])!=start or review._replacement and not int(body['nonce'])<start
                    or end>MAX_NONCE or self._body['batch_count']>=journals.MAX_POSITION):raise ValueError('GG_ACCOUNT_STORAGE_OR_NONCE_LIMIT')
            self._prepare_journal(check=check)
            value={'schema':operations.DOCUMENT,'genesis_hash':anchor['genesis_hash'],'intent':intent,
                   'fee':{'body':body,'signature':self._key.sign_message(b'GG-FINANCIAL-PROTOCOL-FEE-v1\0'+pack(body)).hex()}}
            raw=pack(value);operations.decode_authorization(raw,anchor)
            number=self._body['batch_count']+1;previous=self._body['batch_head'];link=self._batch_link(number,start,end,previous,hashlib.sha256(raw).hexdigest())
            self._write({'schema':ARCHIVE_PROTOCOL_SCHEMA if self._segments is not None else PROTOCOL_SCHEMA,'next_nonce':str(end),'batch_count':number,'batch_head':link},
                        batch=(number,str(start),str(end),previous,link,raw))
            if review._replacement:self._latest_cancel_batch=(number,int(body['nonce']))
            else:self._latest_nonce_batch=(number,start,end)
            return raw

    def pending_authorization(self,packet):
        with self._lock:
            from backend import gg_protocol_operations as operations
            self.remember_account(packet);raw=self._original_for_nonce(self._nonce(self._account))
            if raw is None or unpack(raw).get('schema')!=operations.DOCUMENT:return None
            operations.decode_authorization(raw,self._body['anchor']);return raw

    def _batch_link(self,number,start,end,previous,document_hash):
        value={'schema':'gg.financial.account-originals.v1','account':self._body['public_key'],
               'genesis_hash':self._body['anchor']['genesis_hash'],'position':number,'start_nonce':str(start),
               'end_nonce':str(end),'previous':previous,'document_hash':document_hash}
        return hashlib.sha256(DOMAIN+b'BATCH\0'+pack(value)).hexdigest()

    def _new_segments(self):
        if self._body['anchor'] is None:raise ValueError('GG_ACCOUNT_ANCHOR_REQUIRED')
        return journals.Segments(self,'ACCOUNT_ORIGINALS',{'owner_key':self.public_address(),
            'genesis_hash':self._body['anchor']['genesis_hash'],'account_key':self.public_address()},_empty(self.public_address()))

    def _active_batches(self,*,reverse=False,first=None,last=None):
        clauses=[];args=[]
        if first is not None:clauses.append('id>=?');args.append(first)
        if last is not None:clauses.append('id<=?');args.append(last)
        query='SELECT id,start_nonce,end_nonce,previous,hash,length(document),typeof(document) FROM batches'
        if clauses:query+=' WHERE '+' AND '.join(clauses)
        query+=' ORDER BY id '+('DESC' if reverse else 'ASC')
        with closing(self._db.execute(query,args)) as cursor:
            for index,start,end,previous,link,size,kind in cursor:
                if kind!='blob' or not 0<size<=wire.MAX_RAW:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                raw=bytes(self._db.execute('SELECT document FROM batches WHERE id=?',(index,)).fetchone()[0])
                yield index,{'start_nonce':start,'end_nonce':end,'previous':previous,'hash':link},raw

    def _all_batches(self,*,reverse=False,full=False,check=lambda:None):
        if reverse:
            with closing(self._active_batches(reverse=True)) as rows:yield from rows
        if self._segments is not None:
            with closing(self._segments.rows(self._body['journal'],reverse=reverse,full=full,check=check)) as rows:
                for index,key,epoch,meta,raw in rows:
                    if key!=str(index) or epoch!='0' or set(meta)!={'start_nonce','end_nonce','previous','hash'}:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                    yield index,meta,raw
        if not reverse:
            with closing(self._active_batches()) as rows:yield from rows

    def _replay_batches(self,check):
        previous=_empty(self._body['public_key']);end=0;number=0;last_cancel=-1;latest_cancel=None;latest_nonce=None
        with closing(self._all_batches(full=True,check=check)) as rows:
            for index,meta,raw in rows:
                check();number+=1
                start=wire.counter(meta['start_nonce'],maximum=MAX_NONCE);next_end=wire.counter(meta['end_nonce'],maximum=MAX_NONCE)
                if (number>journals.MAX_POSITION or index!=number or start!=end or not start<=next_end<=start+wire.MAX_PAYMENTS
                        or meta['previous']!=previous or not 0<len(raw)<=wire.MAX_RAW
                        or self._batch_link(number,start,next_end,previous,hashlib.sha256(raw).hexdigest())!=meta['hash']):
                    raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                if self._body['schema'] in (PROTOCOL_SCHEMA,ARCHIVE_PROTOCOL_SCHEMA):
                    value=unpack(raw)
                    from backend import gg_protocol_operations as operations
                    if value.get('schema')==operations.DOCUMENT:
                        authorization=operations.decode_authorization(raw,self._body['anchor']);fee=authorization['fee']['body'];cancel='cancel' in authorization['intent']
                        if (fee['sender']!=self.public_address() or (not cancel and (next_end!=start+1 or int(fee['nonce'])!=start))
                                or cancel and (next_end!=start or not last_cancel<int(fee['nonce'])<start)):
                            raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                        if cancel:last_cancel=int(fee['nonce']);latest_cancel=(number,last_cancel)
                    else:self._check_payment_original(raw,start,next_end)
                else:self._check_payment_original(raw,start,next_end)
                previous=meta['hash'];end=next_end
                if next_end>start:latest_nonce=(number,start,next_end)
                if self._segments is not None and number==int(self._body['journal']['through']):
                    if (self._body['journal']['cursor']!={'next_nonce':str(end),'last_cancel_nonce':str(last_cancel)}
                            or previous!=self._body['journal']['record_head']):raise ValueError('GG_OWN_JOURNAL_CURSOR')
        if number!=self._body['batch_count'] or previous!=self._body['batch_head'] or end!=int(self._body['next_nonce']):
            raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
        self._latest_nonce_batch=latest_nonce;self._latest_cancel_batch=latest_cancel

    def _check_payment_original(self,raw,start,end):
        payments=wire.decode_payment_document(raw,self._body['anchor'])
        if (len(payments)!=end-start or any(row['body']['sender']!=self.public_address() or int(row['body']['nonce'])!=start+offset
                for offset,row in enumerate(payments))):raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')

    def _active_cursor_at(self,cut,check):
        """Verify bounded active bytes from the own sealed archived boundary.

        Full historical crypto/semantic verification remains the cold path.
        This warm copy authenticates exact bytes by the whole active hash chain
        ending at the current owner-signed head, without replaying old files.
        """
        journal=self._body['journal'];position=int(journal['through']);previous=journal['record_head']
        nonce=int(journal['cursor']['next_nonce']);last_cancel=int(journal['cursor']['last_cancel_nonce']);selected=None
        with closing(self._active_batches()) as rows:
            for index,meta,raw in rows:
                check();position+=1;start=wire.counter(meta['start_nonce'],maximum=MAX_NONCE);end=wire.counter(meta['end_nonce'],maximum=MAX_NONCE)
                if (index!=position or start!=nonce or not start<=end<=start+wire.MAX_PAYMENTS or meta['previous']!=previous
                        or self._batch_link(index,start,end,previous,hashlib.sha256(raw).hexdigest())!=meta['hash']):
                    raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                if start==end:
                    from backend import gg_protocol_operations as operations
                    value=operations.decode_authorization(raw,self._body['anchor']);fee=value['fee']['body']
                    if ('cancel' not in value['intent'] or fee['sender']!=self.public_address()
                            or not last_cancel<int(fee['nonce'])<start):raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                    last_cancel=int(fee['nonce'])
                nonce=end;previous=meta['hash']
                if index==cut:selected=({'next_nonce':str(nonce),'last_cancel_nonce':str(last_cancel)},previous)
        if (position!=self._body['batch_count'] or previous!=self._body['batch_head'] or nonce!=int(self._body['next_nonce']) or selected is None):
            raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
        return selected

    def _ensure_journal(self,check):
        if self._segments is not None:return
        self._check();self._replay_batches(check)
        old=deepcopy(self._body);old_hash=self._record_hash;old_view=deepcopy(self._journal_view)
        old_version=self._store_version;segments=self._new_segments()
        try:
            segments.directory(create=True)
            self._db.execute('BEGIN IMMEDIATE')
            for sql in journals.CATALOG_SQL.values():self._db.execute(sql)
            self._body.update(schema=ARCHIVE_PROTOCOL_SCHEMA if self._body['schema']==PROTOCOL_SCHEMA else ARCHIVE_SCHEMA,
                journal=journals.empty('ACCOUNT_ORIGINALS',_empty(self.public_address())))
            self._db.execute('PRAGMA user_version=2');self._put();self._commit()
            self._store_version=2;self._segments=segments
            self._segments.check_inventory(self._body['journal'],full=True)
        except BaseException as error:
            # A migration COMMIT can be durable even when its reply is lost.
            # Keep the visible accepted prefix, latch this owner, and let a
            # fresh cold open discover the actual schema/batch boundary. Never
            # continue to payment signing or retry this transaction in place.
            self._body=old;self._record_hash=old_hash;self._journal_view=old_view
            self._store_version=old_version;self._failed=True
            try:
                if self._db.in_transaction:self._db.execute('ROLLBACK')
            except (OSError,sqlite3.Error) as rollback_error:
                if not isinstance(error,Exception):raise error from rollback_error
                raise ValueError('GG_ACCOUNT_STORE_WRITE_FAILED') from rollback_error
            if not isinstance(error,Exception):raise
            raise ValueError('GG_ACCOUNT_STORE_WRITE_FAILED') from error

    def _prepare_journal(self,*,check=lambda:None):
        self._ensure_journal(check);self._check()
        if self._body['journal']['pending'] is not None:self._archive_prefix(check=check)
        while True:
            count,size=self._db.execute('SELECT count(*),coalesce(sum(length(document)),0) FROM batches').fetchone()
            if count<journals.MAX_ACTIVE_RECORDS and size+wire.MAX_RAW<=journals.MAX_ACTIVE_BYTES:return
            self._archive_prefix(check=check,leave_last=True)

    def _archive_prefix(self,*,check=lambda:None,leave_last=False):
        self._check();journal=self._body['journal'];pending=journal['pending']
        if pending is None:
            limit=self._body['batch_count']-int(leave_last);size=0;last=None
            for index,length,link in self._db.execute('SELECT id,length(document),hash FROM batches WHERE id<=? ORDER BY id',(limit,)):
                if length<=0 or length>wire.MAX_RAW:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                if size+length>journals.MAX_ACTIVE_BYTES or index-int(journal['through'])>journals.MAX_SEGMENT_RECORDS:break
                size+=length;last=(index,link)
            if last is None:raise ValueError('GG_OWN_JOURNAL_NO_RETIRABLE_PREFIX')
            pending={'token':journals.secrets.token_hex(32),'first':str(int(journal['through'])+1),'last':str(last[0]),
                     'previous_head':journal['record_head'],'head':last[1]}
            changed=deepcopy(journal);changed['pending']=pending;self._write({'journal':changed});journal=self._body['journal']
        # Authenticate only the bounded active chain; the sealed cursor was
        # independently rederived by full cold replay or prior owned rotation.
        cursor,cut_head=self._active_cursor_at(int(pending['last']),check)
        if cut_head!=pending['head']:raise ValueError('GG_OWN_JOURNAL_PENDING')
        def selected():
            position=int(pending['first'])-1;previous=pending['previous_head'];nonce=int(journal['cursor']['next_nonce'])
            with closing(self._active_batches(first=int(pending['first']),last=int(pending['last']))) as rows:
                for index,meta,raw in rows:
                    check();position+=1;start=wire.counter(meta['start_nonce'],maximum=MAX_NONCE);end=wire.counter(meta['end_nonce'],maximum=MAX_NONCE)
                    if (index!=position or start!=nonce or not start<=end<=start+wire.MAX_PAYMENTS or meta['previous']!=previous
                            or self._batch_link(index,start,end,previous,hashlib.sha256(raw).hexdigest())!=meta['hash']):raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
                    previous=meta['hash'];nonce=end;yield index,str(index),'0',meta,raw
            if position!=int(pending['last']) or previous!=pending['head'] or str(nonce)!=cursor['next_nonce']:
                raise ValueError('GG_OWN_JOURNAL_PENDING')
        with closing(selected()) as rows:digest,header,body=self._segments.publish(journal,pending,rows,check=check)
        old=deepcopy(self._body);old_hash=self._record_hash
        try:
            changed=deepcopy(journal);changed.update(archive_count=body['number'],archive_head=digest,through=body['last'],
                record_head=body['head'],archived_bytes=str(int(journal['archived_bytes'])+int(body['bytes'])),pending=None,cursor=cursor)
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute('INSERT INTO journal_archives VALUES(?,?,?,?,?)',(int(body['number']),int(body['first']),int(body['last']),digest,header))
            self._db.execute('DELETE FROM batches WHERE id<=?',(int(body['last']),))
            self._body['journal']=changed;self._put();self._commit();self._segments.committed(changed,check=check)
        except BaseException:
            self._body=old;self._record_hash=old_hash;self._failed=True
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise

    def archive(self,*,check=lambda:None):
        """Owned maintenance only; never re-sign originals or allocate a nonce."""
        with self._lock:
            self._ensure_journal(check)
            while self._db.execute('SELECT 1 FROM batches LIMIT 1').fetchone() is not None:self._archive_prefix(check=check)
            return self.snapshot()

    def next_batch_reference(self):
        with self._lock:
            self._check()
            if self._body['anchor'] is None or self._body['batch_count']>=journals.MAX_POSITION:raise ValueError('GG_ACCOUNT_BATCH_SELECTOR')
            return {'schema':'gg.financial.account-batch-ref.v1','account_key':self.public_address(),
                    'genesis_hash':self._body['anchor']['genesis_hash'],'number':str(self._body['batch_count']+1),'previous_head':self._body['batch_head']}

    def batch_count(self):
        with self._lock:self._check();return self._body['batch_count']

    def original(self,number=None):
        """Return exact old bytes; references and positions never pass through JS Number."""
        with self._lock:
            self._check();reference=number if isinstance(number,dict) else None
            if reference is not None:
                if (set(reference)!={'schema','account_key','genesis_hash','number','previous_head'}
                        or reference['schema']!='gg.financial.account-batch-ref.v1' or reference['account_key']!=self.public_address()
                        or self._body['anchor'] is None or reference['genesis_hash']!=self._body['anchor']['genesis_hash']
                        or type(reference['previous_head']) is not str or not wire.HASH.fullmatch(reference['previous_head'])):raise ValueError('GG_ACCOUNT_BATCH_SELECTOR')
                journals.number(reference['number'],positive=True,allow_int=False)
                number=reference['number']
            if type(number) is int and number>journals.MAX_SAFE_NUMBER:raise ValueError('GG_ACCOUNT_USE_DECIMAL_BATCH_REFERENCE')
            number=self._body['batch_count'] if number is None else journals.number(number,positive=True)
            if not 1<=number<=self._body['batch_count']:raise ValueError('GG_ACCOUNT_BATCH_SELECTOR')
            if number!=self._body['batch_count']:self._replay_batches(lambda:None)
            found=None
            if self._segments is not None and number<=int(self._body['journal']['through']):
                with closing(self._segments.rows(self._body['journal'],position=number)) as rows:
                    row=next(rows,None)
                    if row is not None:found=(row[3],row[4])
                    if next(rows,None) is not None:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
            else:
                with closing(self._active_batches(first=number,last=number)) as rows:
                    row=next(rows,None)
                    if row is not None:found=(row[1],row[2])
            if found is None:raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
            meta,raw=found;start,end=int(meta['start_nonce']),int(meta['end_nonce'])
            if (self._batch_link(number,start,end,meta['previous'],hashlib.sha256(raw).hexdigest())!=meta['hash']
                    or number==self._body['batch_count'] and meta['hash']!=self._body['batch_head']
                    or reference is not None and reference['previous_head']!=meta['previous']):raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
            return raw

    def _refresh_journal_view(self):
        if self._body is None or self._db is None:return
        count,size=self._db.execute('SELECT count(*),coalesce(sum(length(document)),0) FROM batches').fetchone()
        journal=self._body.get('journal',journals.empty('ACCOUNT_ORIGINALS',_empty(self.public_address())))
        view=journals.journal_status('ACCOUNT_ORIGINALS',journal,self._body['batch_count'],count,size)
        view.update(active_database_limit_bytes=str(MAX_FILE),layout='SEGMENTED' if self._body['schema'] in (ARCHIVE_SCHEMA,ARCHIVE_PROTOCOL_SCHEMA) else 'LEGACY')
        if view['layout']=='LEGACY':view.update(state='LEGACY_VERIFIED_FULL_REPLAY',active_payload_limit_bytes=str(MAX_FILE),active_record_limit=str(MAX_BATCHES),rotation_state='MIGRATION_ON_NEXT_WRITE')
        self._journal_view=view

    def journal_observation(self):
        """Immutable cached local projection; no signer lock or archive scan."""
        view=deepcopy(self._journal_view)
        if view is not None:
            if self._failed:view.update(state='FAULT',last_error='GG_OWN_JOURNAL_UNAVAILABLE')
            elif self._closed:view['state']='CLOSED'
        return {'profile':self.name,'address':self._body['public_key'] if self._body else None,
                'signed_batches_exact':view['total_records'] if view is not None else '0','journal':view}

    def pending(self,packet):
        """Exact unconsumed account envelopes; never re-sign or assert receipts."""
        with self._lock:
            self.remember_account(packet)
            if not self._body['batch_count']:return None
            nonce=self._nonce(self._account);raw=self._original_for_nonce(nonce)
            if raw is None:return None
            document=unpack(raw)
            if document.get('schema')!=wire.PAYMENT_DOCUMENT:
                from backend import gg_protocol_operations as operations
                if document.get('schema')==operations.DOCUMENT:return None
            payments=wire.decode_payment_document(raw,self._body['anchor'])
            if any(row['body']['sender']!=self._body['public_key'] for row in payments):raise ValueError('GG_ACCOUNT_ORIGINALS_CORRUPT')
            remaining=[row for row in payments if int(row['body']['nonce'])>=nonce]
            return pack({**document,'payments':remaining}) if remaining else None

    def public_address(self):return self._body['public_key']

    def anchor(self):return deepcopy(self._body['anchor'])

    def snapshot(self):
        with self._lock:
            body=self._body;proof=self._account;fault=body['fault'] if body else ''
            account=deepcopy(proof['financial_account']) if proof is not None and proof['financial_account_exists'] else None
            consumed=proof is not None and self._nonce(proof)==int(body['next_nonce'])
            scope=body['anchor']['genesis']['protocol']['environment'] if body and body['anchor'] and body['anchor']['genesis']['schema']=='gg.native.genesis.v7' else 'PRIVATE_LAN_EXPERIMENT'
            return {'profile':self.name,'role':'account','scope':scope,'public_key':body['public_key'] if body else None,
                'label':body['label'] if body else None,'state':'CLOSED' if self._closed else 'FAULT' if self._failed or fault else 'BOUND' if body and body['anchor'] else 'UNBOUND',
                'keys_encrypted_at_rest':True,'whole_disk_rollback_protection':False,'hardware_signer':False,
                'signed_batches':journals.public_number(body['batch_count']) if body else 0,'signed_batches_exact':str(body['batch_count']) if body else '0',
                'own_journal':self.journal_observation()['journal'],'next_signing_nonce':body['next_nonce'] if body else '0',
                'account':account if not fault and not self._failed else None,'account_exists':proof['financial_account_exists'] if proof is not None and not fault and not self._failed else None,
                'account_basis':'LAST_PERSISTED_SIGNER_ACCOUNT_PROOF',
                'certificate_height':self._tip[0] if self._tip else None,'certificate_is_network_liveness':False,
                'payment_state':'NO_SIGNED_PAYMENTS' if not body or not body['batch_count'] else 'NONCE_CONSUMED_OUTCOME_UNRESOLVED' if consumed else 'PENDING_ORIGINALS',
                'payments_executed_asserted':False,'last_error':fault or ('GG_ACCOUNT_STORE_UNAVAILABLE' if self._failed else '')}

    def close(self):
        with self._lock:
            if self._segments is not None:self._segments.close_readers()
            if self._db is not None:self._db.close();self._db=None
            self._key=None;self._review_owner=None;self._closed=True
            if self._lease is not None:
                try:file_locks.flock(self._lease,file_locks.LOCK_UN)
                finally:os.close(self._lease);self._lease=None
