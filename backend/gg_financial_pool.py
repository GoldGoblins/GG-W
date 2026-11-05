"""Bounded durable mining shares, actual income and protected payout originals.

No service, key, database or network starts at import. The caller supplies an
owned book-signing key and an independently pinned network. Shares create no
money. Only a natively certified epoch credit creates distributable income;
only an APPLIED receipt for an exact protected original discharges a liability.
"""
import base64
from copy import deepcopy
from contextlib import closing,contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading

from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_protected_journal as journals
from backend import gg_financial_wire as wire,gg_financial_dag as financial
from backend.gg_ed25519 import Keypair,verify_signature
from backend.gg_node_store import pack,unpack,_private_path
from backend.platform_files import secure_open,set_private_mode,is_link,sync_directory
from backend.platform_support import file_locks

DOMAIN=b'GG-FINANCIAL-POOL-BOOK-v1\0'
MAX_FILE=2*1024**3
MAX_EVENTS=1000000
MAX_RECORD=48*1024*1024
KINDS={'JOB','SHARE','INCOME','PREPARED','ORIGINAL','PAID'}
SQL={
 'head':"CREATE TABLE head(id INTEGER PRIMARY KEY CHECK(id=1),record BLOB NOT NULL CHECK(typeof(record)='blob'))",
 'events':"CREATE TABLE events(position INTEGER PRIMARY KEY CHECK(position>0),kind TEXT NOT NULL,identifier TEXT NOT NULL,epoch TEXT NOT NULL,record BLOB NOT NULL CHECK(typeof(record)='blob'),UNIQUE(kind,identifier))",
 'pool_epoch':"CREATE INDEX pool_epoch ON events(kind,epoch,position)"}
SQL_ARCHIVE={**SQL,**journals.CATALOG_SQL}
_REVIEW_TOKEN=object()
_COLD_TOKEN=object()


class _PoolColdAudit:
    """Temporary exact verified-prefix index; never signer/global authority.

    Only verified metadata/hashes/locations are retained, not another copy of
    all payloads or an in-memory history roster. Native receipt/work checks are
    unchanged. No signing/READY/public outcome is permitted from a partial audit.
    """
    def __init__(self,book,check,*,token=None):
        if token is not _COLD_TOKEN:raise ValueError('GG_POOL_COLD_AUDIT_REQUIRED')
        self.book=book;self.check=check;self.db=None;self.root=None;self.parent=None;self.identity=None
        self.count=0;self.digest=hashlib.sha256();self.active=False;self.closed=False
        self.changes=book._db.total_changes;self.version=book._db.execute('PRAGMA data_version').fetchone()[0]
        self.head_hash=book._head_hash

    def __enter__(self):
        self.check();self.parent=Path(tempfile.gettempdir()).resolve(strict=True)
        self.root=Path(tempfile.mkdtemp(prefix='gg-pool-audit-',dir=self.parent)).absolute()
        set_private_mode(self.root,0o700);_private_path(self.root,0o700)
        info=self.root.stat();self.identity=(info.st_dev,info.st_ino)
        path=self.root/'index.sqlite3';descriptor=secure_open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
        try:
            self.db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None)
            for sql in ('PRAGMA trusted_schema=OFF','PRAGMA cache_size=-1024','PRAGMA temp_store=MEMORY','PRAGMA synchronous=OFF','PRAGMA journal_mode=DELETE'):
                self.db.execute(sql)
            self.db.execute('PRAGMA max_page_count='+str(MAX_FILE//4096))
            self.db.execute('CREATE TABLE verified(position INTEGER PRIMARY KEY,kind TEXT NOT NULL,identifier TEXT NOT NULL,epoch TEXT NOT NULL,source TEXT NOT NULL,hash TEXT NOT NULL,UNIQUE(kind,identifier))')
            self.db.execute('CREATE INDEX verified_epoch ON verified(kind,epoch,position)');self.db.execute('BEGIN IMMEDIATE')
            self.active=True;return self
        except BaseException:
            self.close();raise

    def _require(self):
        if not self.active or self.db is None or self.book._cold_audit is not self or self.book._lease is None:
            raise ValueError('GG_POOL_COLD_AUDIT_REQUIRED')

    def add(self,event,raw):
        self._require();self.check();position=event['position']
        if position!=self.count+1:raise ValueError('GG_POOL_BOOK_JOURNAL')
        source=''
        journal=self.book._head.get('journal')
        if journal is not None and position<=int(journal['through']):
            rows=self.book._db.execute('SELECT digest FROM journal_archives WHERE first_position<=? AND last_position>=? LIMIT 2',(position,position)).fetchall()
            if len(rows)!=1:raise ValueError('GG_OWN_JOURNAL_CATALOG')
            source=rows[0][0]
        row=(position,event['kind'],event['identifier'],event['epoch'],source,_digest(raw))
        try:self.db.execute('INSERT INTO verified VALUES(?,?,?,?,?,?)',row)
        except sqlite3.IntegrityError:raise ValueError('GG_POOL_BOOK_DUPLICATE_EVENT') from None
        self.count+=1;self.digest.update(pack([str(position),*row[1:]]))

    def _read(self,row):
        self._require();self.check();position,kind,identifier,epoch,source,digest=row
        if source:
            # This capability exists only inside the full cold audit. The
            # source file is fully hashed before/after the audit; each positive
            # record is additionally checked against its verified-prefix hash.
            with self.book._segments._open(source,verify=False,check=self.check) as db:
                size=db.execute('SELECT length(document),typeof(document) FROM records WHERE position=?',(position,)).fetchone()
                if size is None or size[1]!='blob' or not 0<size[0]<=MAX_RECORD:raise ValueError('GG_POOL_COLD_SOURCE_CHANGED')
                raw=bytes(db.execute('SELECT document FROM records WHERE position=?',(position,)).fetchone()[0])
        else:
            size=self.book._db.execute('SELECT length(record),typeof(record) FROM events WHERE position=?',(position,)).fetchone()
            if size is None or size[1]!='blob' or not 0<size[0]<=MAX_RECORD:raise ValueError('GG_POOL_COLD_SOURCE_CHANGED')
            raw=bytes(self.book._db.execute('SELECT record FROM events WHERE position=?',(position,)).fetchone()[0])
        if _digest(raw)!=digest:raise ValueError('GG_POOL_COLD_SOURCE_CHANGED')
        event=self.book._decode_event(raw)
        if (event['position'],event['kind'],event['identifier'],event['epoch'])!=(position,kind,identifier,epoch):raise ValueError('GG_POOL_BOOK_JOURNAL')
        return event

    def get(self,kind,identifier,before):
        self._require();query='SELECT position,kind,identifier,epoch,source,hash FROM verified WHERE kind=? AND identifier=?';args=[kind,str(identifier)]
        if before is not None:query+=' AND position<?';args.append(before)
        row=self.db.execute(query,args).fetchone()
        return None if row is None else self._read(row)

    def rows(self,kind,epoch,before,maximum):
        self._require();query='SELECT position,kind,identifier,epoch,source,hash FROM verified WHERE kind=? AND epoch=?';args=[kind,str(epoch)]
        if before is not None:query+=' AND position<?';args.append(before)
        query+=' ORDER BY position LIMIT ?';args.append(maximum+1)
        with closing(self.db.execute(query,args)) as cursor:
            for count,row in enumerate(cursor,1):
                if count>maximum:raise ValueError('GG_POOL_EPOCH_RESOURCE_LIMIT')
                yield self._read(row)

    def finish(self):
        self._require();self.check()
        # Independently close the rebuilt metadata/index and every input before
        # this context can be discarded and the owned book published as READY.
        if self.db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('GG_POOL_COLD_INDEX_CORRUPT')
        actual=hashlib.sha256();count=0
        for row in self.db.execute('SELECT position,kind,identifier,epoch,source,hash FROM verified NOT INDEXED ORDER BY position'):
            self.check();count+=1
            if row[0]!=count:raise ValueError('GG_POOL_COLD_INDEX_CORRUPT')
            actual.update(pack([str(row[0]),*row[1:]]))
        if count!=self.count or actual.digest()!=self.digest.digest():raise ValueError('GG_POOL_COLD_INDEX_CORRUPT')
        if self.book._segments is not None:
            journal=self.book._head['journal'];self.book._segments.check_inventory(journal,full=True,pending=journal['pending'] is not None,check=self.check)
        if (self.book._db.total_changes!=self.changes or self.book._db.execute('PRAGMA data_version').fetchone()[0]!=self.version
                or _digest(bytes(self.book._db.execute('SELECT record FROM head WHERE id=1').fetchone()[0]))!=self.head_hash):
            raise ValueError('GG_POOL_COLD_SOURCE_CHANGED')

    def close(self):
        self.active=False
        if self.db is not None:self.db.close();self.db=None
        if self.root is not None:
            info=self.root.lstat();absolute=self.root.absolute();resolved=absolute.resolve(strict=True)
            if (is_link(absolute) or not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino)!=self.identity
                    or resolved!=absolute or absolute.parent!=self.parent or not absolute.name.startswith('gg-pool-audit-')):
                raise ValueError('GG_POOL_COLD_TEMP_OWNERSHIP')
            _private_path(absolute,0o700);files=list(absolute.iterdir())
            for path in files:
                info=path.lstat()
                if (path.name not in ('index.sqlite3','index.sqlite3-journal') or is_link(path) or not stat.S_ISREG(info.st_mode)
                        or info.st_nlink!=1 or info.st_size>MAX_FILE):raise ValueError('GG_POOL_COLD_TEMP_OWNERSHIP')
                _private_path(path,0o600)
            for path in files:path.unlink()
            absolute.rmdir();self.root=None
        self.closed=True

    def __exit__(self,*errors):self.close()


def _digest(raw):return hashlib.sha256(raw).hexdigest()


def verify_assignment(value,pool_key,payout_account,expected_job):
    if type(expected_job) is not protocol.CertifiedMiningJob:raise ValueError('GG_POOL_CERTIFIED_JOB_REQUIRED')
    if not isinstance(value,dict) or set(value)!={'body','signature'}:raise ValueError('GG_POOL_ASSIGNMENT_SIGNATURE')
    body=value['body']
    if (not isinstance(body,dict) or set(body)!={'assignment','job','payout_account','pool_key','schema'}
            or body['schema']!='gg.financial.pool-work-assignment.v1' or body['pool_key']!=pool_key or body['payout_account']!=payout_account
            or body['job']!=expected_job.document() or body['assignment']!=_digest(pack({'job':body['job'],'payout_account':body['payout_account']}))):
        raise ValueError('GG_POOL_ASSIGNMENT_CONTEXT')
    protocol._signature(pool_key,value['signature'],DOMAIN+b'ASSIGNMENT\0'+pack(body))
    return deepcopy(body)


class _PayoutReview:
    __slots__=('book','head','income','offset','end','account_review','prepared')
    def __init__(self,book,head,income,offset,end,account_review,prepared,*,token=None):
        if token is not _REVIEW_TOKEN:raise ValueError('GG_POOL_REVIEW_REQUIRED')
        for name,value in zip(self.__slots__,(book,head,income,offset,end,account_review,pack(prepared))):object.__setattr__(self,name,value)
    def __setattr__(self,name,value):raise AttributeError('immutable pool payout review')
    def summary(self):return {**self.account_review.summary(),'pool_income_index':self.income,'first_allocation':self.offset,'last_allocation_exclusive':self.end}


class PoolBook:
    def __init__(self,root,key,trust,reward_account,operator,commission_bps,*,binary=None,stamp=None):
        if type(key) is not Keypair:raise ValueError('GG_POOL_OWNED_BOOK_KEY_REQUIRED')
        self.root=Path(root).absolute()
        if not Path(root).is_absolute() or str(self.root).startswith(('\\\\','//')) or any(is_link(path) for path in (self.root,*self.root.parents)):
            raise ValueError('GG_POOL_BOOK_PATH')
        self.trust=protocol.validate_pin(trust);self._key=key;self._binary=binary;self._stamp=stamp
        self.config={'commission_bps':economy._integer(commission_bps,10000),'control_key':key.pubkey().hex(),
                     'genesis_hash':self.trust['genesis_hash'],'operator':financial.account_address(operator),
                     'reward_account':financial.account_address(reward_account),'schema':'gg.financial.pool-config.v1'}
        if {operator,reward_account}&financial.reserved_account_keys(self.trust['genesis']):raise ValueError('GG_POOL_ACCOUNT_ROLE_COLLISION')
        self._db=None;self._lease=None;self._failed=False;self._lock=threading.RLock();self._review_owner=object();self._head=None
        self._changes=0;self._version=None;self._head_hash=None;self._segments=None;self._journal_view=None;self._store_version=1;self._journal_check=lambda:None;self._cold_audit=None;self._active_read_depth=0

    @classmethod
    def create(cls,*args,check=lambda:None,**kwargs):
        book=cls(*args,**kwargs)
        book._journal_check=check
        try:
            check()
            book.root.mkdir(mode=0o700);set_private_mode(book.root,0o700);book._connect(create=True)
            book._db.execute('BEGIN IMMEDIATE')
            for sql in SQL.values():book._db.execute(sql)
            book._head={'config':deepcopy(book.config),'events':0,'head':_digest(DOMAIN+b'EMPTY\0'+pack(book.config)),'schema':'gg.financial.pool-head.v1'}
            book._put_head();book._db.execute('COMMIT');book._seal();sync_directory(book.root)
            return book
        except BaseException:book.close();raise

    @classmethod
    def open(cls,*args,check=lambda:None,**kwargs):
        book=cls(*args,**kwargs)
        book._journal_check=check
        try:
            check()
            book._connect(create=False)
            if (dict(book._db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))!=(SQL if book._store_version==1 else SQL_ARCHIVE)
                    or book._db.execute('PRAGMA quick_check(1)').fetchone()!=('ok',)):raise ValueError('GG_POOL_BOOK_SCHEMA')
            rows=list(book._db.execute('SELECT id,length(record),typeof(record) FROM head'))
            if len(rows)!=1 or rows[0][0]!=1 or rows[0][2]!='blob' or not 0<rows[0][1]<=16384:raise ValueError('GG_POOL_BOOK_HEAD')
            head_raw=bytes(book._db.execute('SELECT record FROM head').fetchone()[0]);signed=unpack(head_raw);book._verify_signed(signed,b'HEAD\0')
            if pack(signed)!=head_raw:raise ValueError('GG_POOL_BOOK_HEAD')
            book._head_hash=_digest(head_raw)
            head=signed['body']
            archived=head.get('schema')=='gg.financial.pool-head.v2'
            if (set(head)!=({'config','events','head','schema','journal'} if archived else {'config','events','head','schema'})
                    or head['config']!=book.config or head['schema'] not in ('gg.financial.pool-head.v1','gg.financial.pool-head.v2')
                    or archived!=(book._store_version==2)
                    or (type(head['events']) is not str if archived else type(head['events']) is not int or not 0<=head['events']<=MAX_EVENTS)):
                raise ValueError('GG_POOL_BOOK_HEAD')
            if archived:head['events']=journals.number(head['events'],allow_int=False)
            book._head=head
            if archived:
                journals.validate_head(head['journal'],'POOL_EVENTS',head['events'])
                book._segments=book._new_segments()
            book._replay_events(check)
            book._seal()
            if archived and head['journal']['pending'] is not None:book._archive_prefix(check=check)
            book._head=head;book._seal();return book
        except BaseException:book.close();raise

    def _connect(self,*,create):
        if not self.root.is_dir() or any(is_link(path) for path in (self.root,*self.root.parents)):raise ValueError('GG_POOL_BOOK_PATH')
        _private_path(self.root,0o700)
        lock=self.root/'book.lock';self._lease=secure_open(lock,os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0),0o600)
        if create:os.write(self._lease,b'0');os.fsync(self._lease)
        info=os.fstat(self._lease)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=1:raise ValueError('GG_POOL_BOOK_LOCK')
        _private_path(lock,0o600)
        try:file_locks.flock(self._lease,file_locks.LOCK_EX|file_locks.LOCK_NB)
        except BlockingIOError:raise ValueError('GG_POOL_BOOK_IN_USE') from None
        path=self.root/'pool.sqlite3';fd=secure_open(path,os.O_RDWR|(os.O_CREAT|os.O_EXCL if create else 0),0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_FILE:raise ValueError('GG_POOL_BOOK_FILE')
        finally:os.close(fd)
        _private_path(path,0o600)
        self._db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None,check_same_thread=False)
        for sql in ('PRAGMA trusted_schema=OFF','PRAGMA cache_size=-2048','PRAGMA temp_store=FILE','PRAGMA synchronous=EXTRA'):
            self._db.execute(sql)
        if self._db.execute('PRAGMA journal_mode=DELETE').fetchone()!=('delete',) or self._db.execute('PRAGMA synchronous').fetchone()!=(3,):raise ValueError('GG_POOL_BOOK_DURABILITY')
        self._db.execute('PRAGMA locking_mode=EXCLUSIVE');self._db.execute('BEGIN EXCLUSIVE');self._db.execute('COMMIT')
        self._db.execute('PRAGMA max_page_count='+str(MAX_FILE//4096))
        if create:self._db.execute('PRAGMA application_id=1195855921');self._db.execute('PRAGMA user_version=1')
        else:
            self._store_version=self._db.execute('PRAGMA user_version').fetchone()[0]
            if self._db.execute('PRAGMA application_id').fetchone()!=(1195855921,) or self._store_version not in (1,2):raise ValueError('GG_POOL_BOOK_VERSION')

    def _seal(self):self._changes=self._db.total_changes;self._version=self._db.execute('PRAGMA data_version').fetchone()[0];self._refresh_journal_view()
    def _check(self):
        if self._failed or self._db is None or self._key is None:raise ValueError('GG_POOL_BOOK_UNAVAILABLE')
        if self._cold_audit is not None:raise ValueError('GG_POOL_COLD_AUDIT_ACTIVE')
        if self._changes!=self._db.total_changes or self._version!=self._db.execute('PRAGMA data_version').fetchone()[0]:
            self._failed=True;raise ValueError('GG_POOL_BOOK_CHANGED')
        size=self._db.execute('SELECT length(record) FROM head WHERE id=1').fetchone()
        if size is None or not 0<size[0]<=16384 or _digest(bytes(self._db.execute('SELECT record FROM head WHERE id=1').fetchone()[0]))!=self._head_hash:
            self._failed=True;raise ValueError('GG_POOL_BOOK_CHANGED')
        if self._segments is not None:
            try:self._segments.check_inventory(self._head['journal'],pending=self._head['journal']['pending'] is not None)
            except (ValueError,OSError,sqlite3.Error):
                self._failed=True;raise ValueError('GG_OWN_JOURNAL_UNAVAILABLE') from None

    def _signed(self,body,domain):return {'body':body,'signature':self._key.sign_message(DOMAIN+domain+pack(body)).hex()}
    def _verify_signed(self,value,domain):
        if not isinstance(value,dict) or set(value)!={'body','signature'}:raise ValueError('GG_POOL_BOOK_SIGNATURE')
        protocol._signature(self.config['control_key'],value['signature'],DOMAIN+domain+pack(value['body']))
    def _put_head(self):
        body=deepcopy(self._head)
        if body['schema']=='gg.financial.pool-head.v2':body['events']=str(body['events'])
        raw=pack(self._signed(body,b'HEAD\0'));self._db.execute('INSERT OR REPLACE INTO head VALUES(1,?)',(raw,));self._head_hash=_digest(raw)
    def _decode_event(self,raw):
        signed=unpack(raw);self._verify_signed(signed,b'EVENT\0');event=signed['body']
        if (pack(signed)!=raw or not isinstance(event,dict) or set(event)!={'data','epoch','genesis_hash','identifier','kind','position','previous','schema'}
                or event['schema'] not in ('gg.financial.pool-event.v1','gg.financial.pool-event.v2') or event['genesis_hash']!=self.config['genesis_hash'] or event['kind'] not in KINDS):raise ValueError('GG_POOL_BOOK_JOURNAL')
        economy._number(event['epoch'])
        if event['schema']=='gg.financial.pool-event.v1':
            if type(event['position']) is not int or not 1<=event['position']<=MAX_EVENTS:raise ValueError('GG_POOL_BOOK_JOURNAL')
        else:event['position']=journals.number(event['position'],positive=True,allow_int=False)
        return event

    def _get(self,kind,identifier,*,before=None):
        if before is not None:before=journals.number(before,positive=True)
        if self._cold_audit is not None:return self._cold_audit.get(kind,identifier,before)
        query='SELECT position,length(record) FROM events NOT INDEXED WHERE kind=? AND identifier=?';args=[kind,str(identifier)]
        if before is not None:query+=' AND position<?';args.append(before)
        with self._active_read_scope():
            row=self._db.execute(query,args).fetchone()
            if row is not None:
                if not 0<row[1]<=MAX_RECORD:raise ValueError('GG_POOL_BOOK_JOURNAL')
                raw=bytes(self._db.execute('SELECT record FROM events WHERE position=?',(row[0],)).fetchone()[0])
                event=self._decode_event(raw)
                if event['position']!=row[0] or event['kind']!=kind or event['identifier']!=str(identifier):raise ValueError('GG_POOL_BOOK_JOURNAL')
                return event
        if self._segments is not None:
            with closing(self._segments.rows(self._head['journal'],selector=kind+':'+str(identifier),before=before,reverse=True)) as rows:
                row=next(rows,None)
                if row is not None:
                    index,key,epoch,meta,raw=row;event=self._decode_event(raw)
                    if (event['position']!=index or event['kind']!=kind or event['identifier']!=str(identifier)
                            or event['epoch']!=epoch or meta!={name:event[name] for name in ('kind','identifier','epoch')}):raise ValueError('GG_POOL_BOOK_JOURNAL')
                    return event
        return None

    def _rows(self,kind,epoch,*,before=None,maximum=65536):
        if before is not None:before=journals.number(before,positive=True)
        if self._cold_audit is not None:
            yield from self._cold_audit.rows(kind,epoch,before,maximum);return
        count=0
        if self._segments is not None:
            with closing(self._segments.rows(self._head['journal'],epoch=str(epoch),before=before)) as rows:
                for index,key,ep,meta,raw in rows:
                    event=self._decode_event(raw)
                    if (event['position']!=index or key!=event['kind']+':'+event['identifier'] or ep!=event['epoch']
                            or meta!={name:event[name] for name in ('kind','identifier','epoch')}):raise ValueError('GG_POOL_BOOK_JOURNAL')
                    if event['kind']!=kind:continue
                    count+=1
                    if count>maximum:raise ValueError('GG_POOL_EPOCH_RESOURCE_LIMIT')
                    yield event
        query='SELECT position,length(record) FROM events NOT INDEXED WHERE kind=? AND epoch=?';args=[kind,str(epoch)]
        if before is not None:query+=' AND position<?';args.append(before)
        query+=' ORDER BY position LIMIT ?';args.append(maximum-count+1)
        with self._active_read_scope(),closing(self._db.execute(query,args)) as cursor:
            for position,size in cursor:
                if not 0<size<=MAX_RECORD:raise ValueError('GG_POOL_BOOK_JOURNAL')
                count+=1
                if count>maximum:raise ValueError('GG_POOL_EPOCH_RESOURCE_LIMIT')
                event=self._decode_event(bytes(self._db.execute('SELECT record FROM events WHERE position=?',(position,)).fetchone()[0]))
                if event['position']!=position or event['kind']!=kind or event['epoch']!=str(epoch):raise ValueError('GG_POOL_BOOK_JOURNAL')
                yield event

    def _append(self,kind,identifier,epoch,data):
        self._check()
        if self._active_read_depth:raise ValueError('GG_POOL_READ_SCOPE_PENDING')
        if self._head['events']>=journals.MAX_POSITION:raise ValueError('GG_POOL_BOOK_RESOURCE_LIMIT')
        if self._get(kind,identifier) is not None:raise ValueError('GG_POOL_BOOK_DUPLICATE_EVENT')
        event={'data':deepcopy(data),'epoch':str(epoch),'genesis_hash':self.config['genesis_hash'],'identifier':str(identifier),'kind':kind,
               'position':self._head['events']+1,'previous':self._head['head'],'schema':'gg.financial.pool-event.v2'}
        self._validate_event(event)
        self._prepare_journal(check=self._journal_check)
        stored=deepcopy(event);stored['position']=str(stored['position'])
        raw=pack(self._signed(stored,b'EVENT\0'))
        if len(raw)>MAX_RECORD:raise ValueError('GG_POOL_BOOK_RESOURCE_LIMIT')
        old=deepcopy(self._head)
        try:
            self._db.execute('BEGIN IMMEDIATE');self._db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(event['position'],kind,str(identifier),str(epoch),raw))
            self._head.update(events=event['position'],head=_digest(raw));self._put_head();self._db.execute('COMMIT');self._seal()
        except BaseException:
            self._head=old;self._failed=True
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise
        return event

    def _allocation(self,index,*,before=None):
        income=self._get('INCOME',index,before=before)
        if income is None:raise ValueError('GG_POOL_INCOME_REQUIRED')
        weights={}
        for row in self._rows('SHARE',income['epoch'],before=income['position']):
            address=row['data']['payout_account'];weights[address]=weights.get(address,0)+int(row['data']['weight'])
        if not weights:raise ValueError('GG_POOL_NO_PAYABLE_SHARES')
        return economy.pool_allocation(income['data']['amount_atomic'],self.config['operator'],self.config['commission_bps'],
                                       [{'address':address,'weight':str(weight)} for address,weight in sorted(weights.items())])

    def _validate_event(self,event,*,check=lambda:None):
        kind=event['kind'];data=event['data'];position=event['position'];epoch=event['epoch'];identifier=event['identifier']
        if kind=='JOB':
            if not isinstance(data,dict) or set(data)!={'job','payout_account'} or _digest(pack(data))!=identifier:raise ValueError('GG_POOL_JOB')
            job=economy.validate_job(data['job']);financial.account_address(data['payout_account'])
            if (job['genesis_hash']!=self.config['genesis_hash'] or job['reward_account']!=self.config['reward_account'] or job['epoch']!=epoch
                    or data['payout_account'] in financial.reserved_account_keys(self.trust['genesis'])):raise ValueError('GG_POOL_JOB')
            recipients={row['data']['payout_account'] for row in self._rows('JOB',epoch,before=position)}
            recipients.add(data['payout_account'])
            if len(recipients)>65536-int(self.config['commission_bps']>0):raise ValueError('GG_POOL_EPOCH_RESOURCE_LIMIT')
        elif kind=='SHARE':
            if not isinstance(data,dict) or set(data)!={'assignment','height','payout_account','solution','weight'}:raise ValueError('GG_POOL_SHARE')
            assignment=self._get('JOB',data['assignment'],before=position)
            if assignment is None:raise ValueError('GG_POOL_JOB_REQUIRED')
            share=economy.verify_work(assignment['data']['job'],data['solution'],economy._number(data['height']))
            if (share.identifier!=identifier or str(share.epoch)!=epoch or data['payout_account']!=assignment['data']['payout_account'] or data['weight']!=str(share.weight)
                    or any(True for _ in self._rows('INCOME',epoch,before=position,maximum=1))):raise ValueError('GG_POOL_SHARE')
        elif kind=='INCOME':
            if not isinstance(data,dict) or set(data)!={'amount_atomic','packet'}:raise ValueError('GG_POOL_INCOME')
            result=protocol.verify_selected(data['packet'],self.trust,reward={'index':identifier,'address':self.config['reward_account']},binary=self._binary,stamp=self._stamp)
            if (result['financial_reward_credit']['amount_atomic']!=data['amount_atomic'] or result['financial_reward_epoch']!=epoch
                    or any(True for _ in self._rows('INCOME',epoch,before=position,maximum=1))):raise ValueError('GG_POOL_INCOME')
            if not any(True for _ in self._rows('SHARE',epoch,before=position)):raise ValueError('GG_POOL_INCOME_WITHOUT_RETAINED_SHARES')
        elif kind=='PREPARED':
            if not isinstance(data,dict) or set(data)!={'account_batch','end','income','max_total_fee_atomic','offset','outputs_hash','start_nonce'}:raise ValueError('GG_POOL_PAYOUT_PREPARE')
            rows=self._allocation(data['income'],before=position);offset=data['offset'];end=data['end']
            if (type(offset) is not int or type(end) is not int or not 0<=offset<end<=len(rows) or end-offset>5000 or identifier!=str(data['income'])+':'+str(offset)):
                raise ValueError('GG_POOL_PAYOUT_RANGE')
            outputs=[{'recipient':row['address'],'amount_atomic':row['amount_atomic']} for row in rows[offset:end] if row['address']!=self.config['reward_account']]
            if not outputs or _digest(pack(outputs))!=data['outputs_hash']:raise ValueError('GG_POOL_PAYOUT_PREPARE')
            economy._number(data['start_nonce']);economy._number(data['max_total_fee_atomic'])
            reference=data['account_batch']
            if event['schema']=='gg.financial.pool-event.v1':economy._integer(reference,65535,positive=True)
            elif (not isinstance(reference,dict) or set(reference)!={'schema','account_key','genesis_hash','number','previous_head'}
                    or reference['schema']!='gg.financial.account-batch-ref.v1' or reference['account_key']!=self.config['reward_account']
                    or reference['genesis_hash']!=self.trust['genesis_hash'] or type(reference['previous_head']) is not str or not wire.HASH.fullmatch(reference['previous_head'])):
                raise ValueError('GG_POOL_PAYOUT_PREPARE')
            else:journals.number(reference['number'],positive=True,allow_int=False)
            for previous in self._rows('PREPARED',epoch,before=position):
                prior=previous['data']
                if prior['income']==data['income'] and offset<prior['end'] and end>prior['offset']:raise ValueError('GG_POOL_PAYOUT_ALREADY_RESERVED')
        elif kind=='ORIGINAL':
            prepared=self._get('PREPARED',identifier,before=position)
            if prepared is None or not isinstance(data,dict) or set(data)!={'document'}:raise ValueError('GG_POOL_PAYOUT_PREPARE_REQUIRED')
            raw=base64.b64decode(data['document'],validate=True);payments=wire.decode_payment_document(raw,self.trust)
            draft=prepared['data'];rows=self._allocation(draft['income'],before=position)[draft['offset']:draft['end']]
            expected=[(row['address'],row['amount_atomic']) for row in rows if row['address']!=self.config['reward_account']]
            if ([(row['body']['recipient'],row['body']['amount_atomic']) for row in payments]!=expected or any(row['body']['sender']!=self.config['reward_account']
                    or int(row['body']['nonce'])!=int(draft['start_nonce'])+offset for offset,row in enumerate(payments))
                    or sum(int(row['body']['max_fee_atomic']) for row in payments)>int(draft['max_total_fee_atomic'])):raise ValueError('GG_POOL_PAYOUT_ORIGINAL_MISMATCH')
        elif kind=='PAID':
            if not isinstance(data,dict) or set(data)!={'packet','payment_index','payout'}:raise ValueError('GG_POOL_PAYOUT_RECEIPT')
            original=self._get('ORIGINAL',data['payout'],before=position)
            if original is None:raise ValueError('GG_POOL_PAYOUT_ORIGINAL_REQUIRED')
            payments=wire.decode_payment_document(base64.b64decode(original['data']['document'],validate=True),self.trust)
            index=economy._integer(data['payment_index'],len(payments)-1)
            result=financial.verify_receipt(data['packet'],self.trust,expected_transaction_id=identifier,binary=self._binary,stamp=self._stamp)
            if result['financial_receipt']['transaction_id']!=identifier or identifier!=wire.intent_id(pack(payments[index])) or result['financial_receipt']['outcome']!='APPLIED':
                raise ValueError('GG_POOL_PAYOUT_NOT_APPLIED')
        else:raise ValueError('GG_POOL_BOOK_EVENT')
        check()

    def register_job(self,job,payout_account):
        with self._lock:
            self._check()
            if type(job) is not protocol.CertifiedMiningJob:raise ValueError('GG_POOL_CERTIFIED_JOB_REQUIRED')
            data={'job':job.document(),'payout_account':financial.account_address(payout_account)};identifier=_digest(pack(data))
            # One assignment per exact worker job prevents retargeting a public
            # solution to a second payout account through another assignment.
            for prior in self._rows('JOB',data['job']['epoch'],maximum=65536):
                if prior['data']['job']==data['job']:
                    if prior['identifier']!=identifier:raise ValueError('GG_POOL_JOB_ALREADY_ASSIGNED')
                    return self._public_assignment(identifier,data)
            self._append('JOB',identifier,data['job']['epoch'],data)
            return self._public_assignment(identifier,data)

    def _public_assignment(self,identifier,data):
        body={'assignment':identifier,**deepcopy(data),'pool_key':self.config['control_key'],'schema':'gg.financial.pool-work-assignment.v1'}
        return {'body':body,'signature':self._key.sign_message(DOMAIN+b'ASSIGNMENT\0'+pack(body)).hex()}

    def accept_share(self,assignment,solution,current_height):
        with self._lock:
            self._check();job=self._get('JOB',assignment)
            if job is None:raise ValueError('GG_POOL_JOB_REQUIRED')
            share=economy.verify_work(job['data']['job'],solution,economy._integer(current_height))
            if self._get('SHARE',share.identifier) is not None:raise ValueError('GG_MINING_SHARE_ALREADY_ACCEPTED')
            if sum(1 for _ in self._rows('SHARE',share.epoch))>=65536:raise ValueError('GG_POOL_EPOCH_RESOURCE_LIMIT')
            self._append('SHARE',share.identifier,share.epoch,{'assignment':assignment,'height':str(current_height),'payout_account':job['data']['payout_account'],
                         'solution':deepcopy(solution),'weight':str(share.weight)})
            return {'state':'SHARE_RETAINED','network_work':share.network_work,'money_earned_asserted':False}

    def record_income(self,index,packet):
        with self._lock:
            self._check();index=str(economy._number(index,2**32,positive=True))
            result=protocol.verify_selected(packet,self.trust,reward={'index':index,'address':self.config['reward_account']},binary=self._binary,stamp=self._stamp)
            previous=self._get('INCOME',index)
            if previous is not None:
                if (previous['data']['amount_atomic']!=result['financial_reward_credit']['amount_atomic'] or previous['epoch']!=result['financial_reward_epoch']
                        or previous['data']['packet']['financial_reward']['receipt']!=packet['financial_reward']['receipt']):raise ValueError('GG_POOL_INCOME_CONFLICT')
                return self.liabilities(index)
            self._append('INCOME',index,result['financial_reward_epoch'],{'amount_atomic':result['financial_reward_credit']['amount_atomic'],'packet':deepcopy(packet)})
            return self.liabilities(index)

    def review_payout(self,index,account,packet,*,offset=0,limit=5000):
        # Same order as the runtime/account proof path; hold the actual account
        # through review+global-reference capture, never two separate snapshots.
        with account._lock,self._lock:
            self._check();index=str(economy._number(index,2**32,positive=True));economy._integer(limit,5000,positive=True)
            rows=self._allocation(index);economy._integer(offset,len(rows)-1);end=min(len(rows),offset+limit)
            income=self._get('INCOME',index)
            for prior in self._rows('PREPARED',income['epoch']):
                reservation=prior['data']
                if reservation['income']==index and offset<reservation['end'] and end>reservation['offset']:
                    raise ValueError('GG_POOL_PAYOUT_ALREADY_RESERVED')
            if account.public_address()!=self.config['reward_account'] or account.anchor()!=self.trust:raise ValueError('GG_POOL_OWNED_REWARD_ACCOUNT_REQUIRED')
            outputs=[{'recipient':row['address'],'amount_atomic':row['amount_atomic']} for row in rows[offset:end] if row['address']!=self.config['reward_account']]
            review=account.review(outputs,packet);snapshot=account.snapshot();prepared={'account_batch':account.next_batch_reference(),'end':end,'income':index,
                'max_total_fee_atomic':review.summary()['max_total_fee_atomic'],'offset':offset,'outputs_hash':_digest(pack(outputs)),'start_nonce':snapshot['next_signing_nonce']}
            return _PayoutReview(self._review_owner,self._head['head'],index,offset,end,review,prepared,token=_REVIEW_TOKEN)

    def sign_payout(self,review,account):
        with account._lock,self._lock:
            self._check()
            if type(review) is not _PayoutReview or review.book is not self._review_owner or review.head!=self._head['head'] or account.public_address()!=self.config['reward_account']:
                raise ValueError('GG_POOL_REVIEW_STALE_OR_FOREIGN')
            draft=unpack(review.prepared);identifier=review.income+':'+str(review.offset);income=self._get('INCOME',review.income)
            prior=self._get('PREPARED',identifier)
            if prior is None:self._append('PREPARED',identifier,income['epoch'],draft)
            elif prior['data']!=draft:raise ValueError('GG_POOL_PAYOUT_RESERVATION_CHANGED')
            raw=account.sign(review.account_review,check=self._journal_check)
            self._append('ORIGINAL',identifier,income['epoch'],{'document':base64.b64encode(raw).decode('ascii')})
            return raw

    def resume_original(self,payout,account):
        """Recover an exact committed wallet batch after a cross-store crash."""
        with account._lock,self._lock:
            self._check();prepared=self._get('PREPARED',payout)
            if prepared is None or account.public_address()!=self.config['reward_account'] or account.anchor()!=self.trust:raise ValueError('GG_POOL_PAYOUT_PREPARE_REQUIRED')
            original=self._get('ORIGINAL',payout)
            if original is not None:return base64.b64decode(original['data']['document'],validate=True)
            reference=prepared['data']['account_batch'];number=journals.number(reference['number'],positive=True,allow_int=False) if isinstance(reference,dict) else reference
            if account.batch_count()<number:return None
            raw=account.original(prepared['data']['account_batch'])
            self._append('ORIGINAL',payout,prepared['epoch'],{'document':base64.b64encode(raw).decode('ascii')})
            return raw

    def remember_applied(self,payout,payment_index,packet):
        with self._lock:
            self._check();original=self._get('ORIGINAL',payout)
            if original is None:raise ValueError('GG_POOL_PAYOUT_ORIGINAL_REQUIRED')
            payments=wire.decode_payment_document(base64.b64decode(original['data']['document'],validate=True),self.trust)
            economy._integer(payment_index,len(payments)-1);identifier=wire.intent_id(pack(payments[payment_index]))
            if self._get('PAID',identifier) is None:self._append('PAID',identifier,original['epoch'],{'packet':deepcopy(packet),'payment_index':payment_index,'payout':payout})
            return {'state':'SDK_CERTIFIED_APPLIED','payment_index':payment_index}

    def liabilities(self,index):
        with self._lock:
            self._check();index=str(index);income=self._get('INCOME',index)
            if income is None:raise ValueError('GG_POOL_INCOME_REQUIRED')
            paid=set()
            for row in self._rows('PAID',income['epoch']):
                prepared=self._get('PREPARED',row['data']['payout'])
                if prepared['data']['income']!=index:continue
                original=self._get('ORIGINAL',row['data']['payout']);payments=wire.decode_payment_document(base64.b64decode(original['data']['document'],validate=True),self.trust)
                paid.add(payments[row['data']['payment_index']]['body']['recipient'])
            rows=self._allocation(index)
            return {'income_index':index,'epoch':income['epoch'],'certified_income_atomic':income['data']['amount_atomic'],
                    'unpaid':[row for row in rows if row['address'] not in paid and row['address']!=self.config['reward_account']],
                    'retained_in_reward_account':[row for row in rows if row['address']==self.config['reward_account']],
                    'fees_in_addition_to_worker_amounts':True,'balance_solvency_asserted':False,'whole_disk_rollback_protection':False}

    def _new_segments(self):
        return journals.Segments(self,'POOL_EVENTS',{'owner_key':self.config['control_key'],
            'genesis_hash':self.trust['genesis_hash'],'pool_config_hash':_digest(pack(self.config))},_digest(DOMAIN+b'EMPTY\0'+pack(self.config)))

    def _active_events(self,*,first=None,last=None):
        query='SELECT position,kind,identifier,epoch,length(record) FROM events';clauses=[];args=[]
        if first is not None:clauses.append('position>=?');args.append(first)
        if last is not None:clauses.append('position<=?');args.append(last)
        if clauses:query+=' WHERE '+' AND '.join(clauses)
        query+=' ORDER BY position'
        with closing(self._db.execute(query,args)) as cursor:
            for index,kind,identifier,epoch,size in cursor:
                if not 0<size<=MAX_RECORD:raise ValueError('GG_POOL_BOOK_JOURNAL')
                raw=bytes(self._db.execute('SELECT record FROM events WHERE position=?',(index,)).fetchone()[0])
                yield index,kind+':'+identifier,epoch,{'kind':kind,'identifier':identifier,'epoch':epoch},raw

    def _all_events(self,*,full=False,check=lambda:None):
        if self._segments is not None:
            with closing(self._segments.rows(self._head['journal'],full=full,check=check)) as rows:yield from rows
        with closing(self._active_events()) as rows:yield from rows

    def _replay_events(self,check):
        previous=_digest(DOMAIN+b'EMPTY\0'+pack(self.config));count=0
        if self._cold_audit is not None:raise ValueError('GG_POOL_COLD_AUDIT_ALREADY_ACTIVE')
        audit=_PoolColdAudit(self,check,token=_COLD_TOKEN);self._cold_audit=audit
        try:
            with audit,closing(self._all_events(full=True,check=check)) as rows:
                for index,key,epoch,meta,raw in rows:
                    check();count+=1;event=self._decode_event(raw)
                    if (index!=count or count>journals.MAX_POSITION or event['position']!=count or event['previous']!=previous
                            or key!=event['kind']+':'+event['identifier'] or epoch!=event['epoch']
                            or meta!={name:event[name] for name in ('kind','identifier','epoch')}
                            or self._get(event['kind'],event['identifier'],before=count) is not None):raise ValueError('GG_POOL_BOOK_JOURNAL')
                    self._validate_event(event,check=check);audit.add(event,raw);previous=_digest(raw)
                if count!=self._head['events'] or previous!=self._head['head']:raise ValueError('GG_POOL_BOOK_JOURNAL')
                audit.finish()
        except BaseException:
            self._failed=True;raise
        finally:
            if audit.closed:self._cold_audit=None
            else:self._failed=True

    def _verify_active_events(self,check,cut):
        """Warm exact-byte suffix check; never substitutes for cold semantics."""
        journal=self._head.get('journal',journals.empty('POOL_EVENTS',_digest(DOMAIN+b'EMPTY\0'+pack(self.config))))
        count=int(journal['through']);previous=journal['record_head'];selected=previous if count==cut else None
        with closing(self._active_events()) as rows:
            for index,key,epoch,meta,raw in rows:
                check();count+=1;event=self._decode_event(raw)
                if (index!=count or event['position']!=count or event['previous']!=previous
                        or key!=event['kind']+':'+event['identifier'] or epoch!=event['epoch']
                        or meta!={name:event[name] for name in ('kind','identifier','epoch')}):raise ValueError('GG_POOL_BOOK_JOURNAL')
                previous=_digest(raw)
                if index==cut:selected=previous
        if count!=self._head['events'] or previous!=self._head['head']:raise ValueError('GG_POOL_BOOK_JOURNAL')
        if selected is None:raise ValueError('GG_OWN_JOURNAL_PENDING')
        return selected

    @contextmanager
    def _active_read_scope(self):
        """Authenticate bounded active columns/raws before SQL absence, in one
        local read snapshot. This is not a complete historical replay claim.
        """
        outer=self._active_read_depth==0
        if outer:
            self._db.execute('SAVEPOINT gg_pool_active_read')
            try:self._verify_active_events(self._journal_check,self._head['events'])
            except BaseException:
                self._failed=True
                self._db.execute('ROLLBACK TO gg_pool_active_read');self._db.execute('RELEASE gg_pool_active_read')
                raise
        self._active_read_depth+=1
        try:yield
        finally:
            self._active_read_depth-=1
            if outer:
                try:self._db.execute('RELEASE gg_pool_active_read')
                except BaseException:self._failed=True;raise

    def _ensure_journal(self,check):
        if self._segments is not None:return
        self._check();self._replay_events(check)
        old=deepcopy(self._head);old_hash=self._head_hash;segments=self._new_segments();segments.directory(create=True)
        try:
            self._db.execute('BEGIN IMMEDIATE')
            for sql in journals.CATALOG_SQL.values():self._db.execute(sql)
            self._head.update(schema='gg.financial.pool-head.v2',journal=journals.empty('POOL_EVENTS',_digest(DOMAIN+b'EMPTY\0'+pack(self.config))))
            self._db.execute('PRAGMA user_version=2');self._put_head();self._db.execute('COMMIT');self._seal()
            self._store_version=2;self._segments=segments;self._segments.check_inventory(self._head['journal'],full=True,check=check)
        except BaseException:
            self._head=old;self._head_hash=old_hash;self._failed=True
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise

    def _prepare_journal(self,*,check=lambda:None):
        self._ensure_journal(check);self._check()
        if self._head['journal']['pending'] is not None:self._archive_prefix(check=check)
        while True:
            count,size=self._db.execute('SELECT count(*),coalesce(sum(length(record)),0) FROM events').fetchone()
            if count<journals.MAX_ACTIVE_RECORDS and size+MAX_RECORD<=journals.MAX_ACTIVE_BYTES:return
            self._archive_prefix(check=check,leave_last=True)

    def _archive_prefix(self,*,check=lambda:None,leave_last=False):
        self._check();journal=self._head['journal'];pending=journal['pending']
        if pending is None:
            limit=self._head['events']-int(leave_last);size=0;last=None
            for index,length in self._db.execute('SELECT position,length(record) FROM events WHERE position<=? ORDER BY position',(limit,)):
                if not 0<length<=MAX_RECORD:raise ValueError('GG_POOL_BOOK_JOURNAL')
                if size+length>journals.MAX_ACTIVE_BYTES or index-int(journal['through'])>journals.MAX_SEGMENT_RECORDS:break
                raw=bytes(self._db.execute('SELECT record FROM events WHERE position=?',(index,)).fetchone()[0])
                size+=length;last=(index,_digest(raw))
            if last is None:raise ValueError('GG_OWN_JOURNAL_NO_RETIRABLE_PREFIX')
            pending={'token':journals.secrets.token_hex(32),'first':str(int(journal['through'])+1),'last':str(last[0]),
                     'previous_head':journal['record_head'],'head':last[1]}
            old=deepcopy(self._head);old_hash=self._head_hash
            try:
                self._db.execute('BEGIN IMMEDIATE');self._head['journal']['pending']=pending;self._put_head();self._db.execute('COMMIT');self._seal()
            except BaseException:
                self._head=old;self._head_hash=old_hash;self._failed=True
                if self._db.in_transaction:self._db.execute('ROLLBACK')
                raise
            journal=self._head['journal']
        if self._verify_active_events(check,int(pending['last']))!=pending['head']:raise ValueError('GG_OWN_JOURNAL_PENDING')
        def selected():
            previous=pending['previous_head'];position=int(pending['first'])-1
            with closing(self._active_events(first=int(pending['first']),last=int(pending['last']))) as rows:
                for index,key,epoch,meta,raw in rows:
                    check();position+=1;event=self._decode_event(raw)
                    if (index!=position or event['position']!=index or event['previous']!=previous or key!=event['kind']+':'+event['identifier']
                            or epoch!=event['epoch'] or meta!={name:event[name] for name in ('kind','identifier','epoch')}):raise ValueError('GG_POOL_BOOK_JOURNAL')
                    previous=_digest(raw);yield index,key,epoch,meta,raw
            if position!=int(pending['last']) or previous!=pending['head']:raise ValueError('GG_OWN_JOURNAL_PENDING')
        with closing(selected()) as rows:digest,header,body=self._segments.publish(journal,pending,rows,check=check)
        old=deepcopy(self._head);old_hash=self._head_hash
        try:
            changed=deepcopy(journal);changed.update(archive_count=body['number'],archive_head=digest,through=body['last'],record_head=body['head'],
                archived_bytes=str(int(journal['archived_bytes'])+int(body['bytes'])),pending=None)
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute('INSERT INTO journal_archives VALUES(?,?,?,?,?)',(int(body['number']),int(body['first']),int(body['last']),digest,header))
            self._db.execute('DELETE FROM events WHERE position<=?',(int(body['last']),));self._head['journal']=changed
            self._put_head();self._db.execute('COMMIT');self._seal();self._segments.committed(changed,check=check)
        except BaseException:
            self._head=old;self._head_hash=old_hash;self._failed=True
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise

    def archive(self,*,check=lambda:None):
        with self._lock:
            self._ensure_journal(check)
            while self._db.execute('SELECT 1 FROM events LIMIT 1').fetchone() is not None:self._archive_prefix(check=check)
            return self.snapshot()

    def _refresh_journal_view(self):
        if self._head is None or self._db is None:return
        count,size=self._db.execute('SELECT count(*),coalesce(sum(length(record)),0) FROM events').fetchone()
        journal=self._head.get('journal',journals.empty('POOL_EVENTS',_digest(DOMAIN+b'EMPTY\0'+pack(self.config))))
        view=journals.journal_status('POOL_EVENTS',journal,self._head['events'],count,size)
        view.update(active_database_limit_bytes=str(MAX_FILE),layout='SEGMENTED' if self._head['schema']=='gg.financial.pool-head.v2' else 'LEGACY')
        if view['layout']=='LEGACY':view.update(state='LEGACY_VERIFIED_FULL_REPLAY',active_payload_limit_bytes=str(MAX_FILE),active_record_limit=str(MAX_EVENTS),rotation_state='MIGRATION_ON_NEXT_WRITE')
        self._journal_view=view

    def snapshot(self):
        # Immutable cached projection: observation cannot block on journal I/O.
        view=deepcopy(self._journal_view)
        if view is not None:
            if self._failed:view.update(state='FAULT',last_error='GG_OWN_JOURNAL_UNAVAILABLE')
            elif self._db is None:view['state']='CLOSED'
            elif self._cold_audit is not None:view['state']='VERIFYING_OWN_JOURNAL'
        exact=view['total_records'] if view is not None else None
        total=int(exact) if exact is not None else None
        return {'state':'FAULT' if self._failed else 'CLOSED' if self._db is None else 'VERIFYING_OWN_JOURNAL' if self._cold_audit is not None else 'READY','config':deepcopy(self.config),
                'retained_events':journals.public_number(total) if total is not None else None,'retained_events_exact':exact,'own_journal':view,'money_from_shares_asserted':False}

    def close(self):
        with self._lock:
            if self._active_read_depth:raise ValueError('GG_POOL_READ_SCOPE_PENDING')
            if self._cold_audit is not None:self._cold_audit.close();self._cold_audit=None
            if self._segments is not None:self._segments.close_readers()
            if self._db is not None:self._db.close();self._db=None
            self._key=None;self._review_owner=None
            if self._lease is not None:
                try:file_locks.flock(self._lease,file_locks.LOCK_UN)
                finally:os.close(self._lease);self._lease=None
