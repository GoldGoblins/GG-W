"""Owned immutable account/pool journal segments; no global-state authority.

Full cold verification streams every retained segment. Warm operations compare
the complete file-identity inventory and authenticate records on use. This is
neither snapshot-trusting startup nor whole-disk rollback protection. No import
creates a file/key/process, and no archived object contains vault ciphertext.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat

from backend import gg_financial_own_archive as producer_files
from backend.gg_ed25519 import verify_signature
from backend.gg_node_store import pack,unpack,_private_path
from backend.platform_files import secure_open,is_link,set_private_mode,sync_directory

DOMAIN=b'GG-PROTECTED-JOURNAL-SEGMENT-v1\0'
ZERO='0'*64
MAX_POSITION=2**63-1
MAX_SAFE_NUMBER=2**53-1
MAX_ACTIVE_RECORDS=8191
MAX_ACTIVE_BYTES=96*1024**2
MAX_SEGMENT_BYTES=128*1024**2
MAX_SEGMENT_RECORDS=8191
MAX_DOCUMENT=48*1024**2
MAX_READERS=8
HASH=re.compile(r'[0-9a-f]{64}')
SCHEMA='gg.protected.journal-head.v1'
HEADER_SCHEMA='gg.protected.journal-segment.v1'
TABLE="CREATE TABLE journal_archives(number INTEGER PRIMARY KEY CHECK(number>0),first_position INTEGER NOT NULL,last_position INTEGER NOT NULL,digest TEXT NOT NULL UNIQUE,header BLOB NOT NULL CHECK(typeof(header)='blob'))"
INDEX="CREATE INDEX journal_range ON journal_archives(first_position,last_position)"
CATALOG_SQL={'journal_archives':TABLE,'journal_range':INDEX}
_PUBLISH_TOKEN=object()
SEGMENT_SQL={
 'header':"CREATE TABLE header(id INTEGER PRIMARY KEY CHECK(id=1),record BLOB NOT NULL CHECK(typeof(record)='blob'))",
 'records':"CREATE TABLE records(position INTEGER PRIMARY KEY CHECK(position>0),selector TEXT NOT NULL,epoch TEXT NOT NULL,metadata BLOB NOT NULL CHECK(typeof(metadata)='blob'),document BLOB NOT NULL CHECK(typeof(document)='blob'))",
 'record_selector':"CREATE INDEX record_selector ON records(selector,position)",
 'record_epoch':"CREATE INDEX record_epoch ON records(epoch,position)"}


def _stat_stamp(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_nlink,stat.S_IMODE(info.st_mode))


def _windows_change_time(descriptor):
    """Real Windows mutation marker, not creation time or a crypto witness."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    class BasicInfo(ctypes.Structure):
        _fields_=[('created',ctypes.c_longlong),('accessed',ctypes.c_longlong),
                  ('written',ctypes.c_longlong),('changed',ctypes.c_longlong),('attributes',wintypes.DWORD)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    query=kernel.GetFileInformationByHandleEx
    query.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];query.restype=wintypes.BOOL
    basic=BasicInfo()
    if not query(msvcrt.get_osfhandle(descriptor),0,ctypes.byref(basic),ctypes.sizeof(basic)):
        raise ctypes.WinError(ctypes.get_last_error())
    if basic.changed<=0:raise OSError('GG_OWN_JOURNAL_CHANGE_TIME_UNAVAILABLE')
    return basic.changed


class _PublishedSegment:
    """Owned readback fact only, never constructible from a public document."""
    __slots__=('owner','digest','raw','body','stamp','base')
    def __init__(self,owner,digest,raw,body,stamp,base,*,token=None):
        if token is not _PUBLISH_TOKEN:raise ValueError('GG_OWN_JOURNAL_READBACK_REQUIRED')
        for name,value in zip(self.__slots__,(owner,digest,raw,pack(body),stamp,base)):object.__setattr__(self,name,value)
    def __setattr__(self,name,value):raise AttributeError('immutable owned segment publication')


def number(value,*,positive=False,allow_int=True):
    if type(value) is int and allow_int:
        if 0<=value<=MAX_POSITION and (value>0 or not positive):return value
    elif type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,18}',value):
        result=int(value)
        if result<=MAX_POSITION and (result>0 or not positive):return result
    raise ValueError('GG_OWN_JOURNAL_POSITION')


def public_number(value):return value if value<=MAX_SAFE_NUMBER else None


def journal_status(kind,journal,total,active_count,active_bytes):
    over=active_count>MAX_ACTIVE_RECORDS or active_bytes>MAX_ACTIVE_BYTES
    return {'schema':'gg.protected.journal-status.v1','kind':kind,'state':'ROTATION_REQUIRED' if over else 'VERIFIED_LOCAL_JOURNAL','total_records':str(total),
        'active_records':str(active_count),'archived_records':journal['through'],'archive_segments':journal['archive_count'],
        'active_payload_bytes':str(active_bytes),'active_payload_limit_bytes':str(MAX_ACTIVE_BYTES),'active_record_limit':str(MAX_ACTIVE_RECORDS),
        'verification_scope':'OWN_SEALED_FULL_STREAMING_COLD_REPLAY',
        'warm_verification':'FILE_IDENTITY_INVENTORY_AND_AUTHENTICATED_RECORD_AT_USE',
        'snapshot_trust_used':False,'native_global_state_authority':False,'whole_disk_rollback_protection':False,
        'total_history_bounded':False,'segment_catalog_growth':'RETAINED_SEGMENT_COUNT',
        'archive_deletion_enabled':False,'rotation_state':'PENDING_RECOVERY' if journal['pending'] is not None else 'OVER_WINDOW' if over else 'COMPLETE'}


def empty(kind,head):
    return {'schema':SCHEMA,'kind':kind,'archive_count':'0','archive_head':ZERO,
            'through':'0','record_head':head,'archived_bytes':'0','pending':None,
            'cursor':{'next_nonce':'0','last_cancel_nonce':'-1'} if kind=='ACCOUNT_ORIGINALS' else None}


def validate_head(value,kind,total):
    fields={'schema','kind','archive_count','archive_head','through','record_head','archived_bytes','pending','cursor'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=SCHEMA or value['kind']!=kind:
        raise ValueError('GG_OWN_JOURNAL_HEAD')
    for field in ('archive_count','through','archived_bytes'):number(value[field],allow_int=False)
    if (not HASH.fullmatch(value['archive_head']) or not HASH.fullmatch(value['record_head'])
            or int(value['through'])>total or (int(value['archive_count'])==0)!=(int(value['through'])==0)
            or (value['archive_head']==ZERO)!=(int(value['archive_count'])==0)):
        raise ValueError('GG_OWN_JOURNAL_HEAD')
    cursor=value['cursor']
    if kind=='ACCOUNT_ORIGINALS':
        if not isinstance(cursor,dict) or set(cursor)!={'next_nonce','last_cancel_nonce'}:raise ValueError('GG_OWN_JOURNAL_CURSOR')
        for field in ('next_nonce','last_cancel_nonce'):
            text=cursor[field]
            if field=='last_cancel_nonce' and text=='-1':continue
            if type(text) is not str or not re.fullmatch(r'0|[1-9][0-9]{0,19}',text) or int(text)>2**64-1:
                raise ValueError('GG_OWN_JOURNAL_CURSOR')
        if int(cursor['last_cancel_nonce'])>=int(cursor['next_nonce']):raise ValueError('GG_OWN_JOURNAL_CURSOR')
        if int(value['through'])==0 and cursor!={'next_nonce':'0','last_cancel_nonce':'-1'}:raise ValueError('GG_OWN_JOURNAL_CURSOR')
    elif cursor is not None:raise ValueError('GG_OWN_JOURNAL_CURSOR')
    pending=value['pending']
    if pending is not None:
        if not isinstance(pending,dict) or set(pending)!={'token','first','last','previous_head','head'}:
            raise ValueError('GG_OWN_JOURNAL_PENDING')
        if (not HASH.fullmatch(pending['token']) or number(pending['first'],positive=True,allow_int=False)!=int(value['through'])+1
                or not number(pending['first'],positive=True)<=number(pending['last'],positive=True)<=total
                or not HASH.fullmatch(pending['previous_head']) or not HASH.fullmatch(pending['head'])
                or pending['previous_head']!=value['record_head']):raise ValueError('GG_OWN_JOURNAL_PENDING')


class Segments:
    """All calls share the owning profile RLock and its exclusive file lease.

    The catalog grows with segment count inside the existing bounded SQLite
    store; the active payload window is bounded, total retained history is not.
    Inventory work grows with retained segment count, not with a RAM roster.
    """
    def __init__(self,owner,kind,context,initial_head):
        self.owner=owner;self.kind=kind;self.context=deepcopy(context)
        self.initial_head=initial_head
        self.root=owner.root/'journal-segments';self._inventory=None;self._readers=0;self._pending_readers=[];self._publication=None

    def _guard(self):
        if self.owner._lease is None or self.owner._db is None or self.owner._key is None or self.owner._failed:
            raise ValueError('GG_OWN_JOURNAL_OWNER_REQUIRED')
        if self._pending_readers:raise ValueError('GG_OWN_JOURNAL_READERS_PENDING')

    def directory(self,*,create=False):
        self._guard()
        if create and not self.root.exists():
            self.root.mkdir(mode=0o700);set_private_mode(self.root,0o700);sync_directory(self.owner.root)
        if is_link(self.root) or not self.root.is_dir():raise ValueError('GG_OWN_JOURNAL_DIRECTORY')
        _private_path(self.root,0o700)
        return self.root

    def _path(self,digest):
        if type(digest) is not str or not HASH.fullmatch(digest):raise ValueError('GG_OWN_JOURNAL_DIGEST')
        return self.directory()/(digest+'.ggjournal')

    def _header(self,raw):
        value=unpack(raw)
        if not isinstance(value,dict) or set(value)!={'body','signature'} or pack(value)!=raw:
            raise ValueError('GG_OWN_JOURNAL_HEADER')
        body=value['body']
        if (not isinstance(body,dict) or set(body)!={'schema','kind','context','number','first','last','previous_archive','previous_head','head','records','bytes','payload_sha256','token'}
                or body['schema']!=HEADER_SCHEMA or body['kind']!=self.kind or body['context']!=self.context):
            raise ValueError('GG_OWN_JOURNAL_CONTEXT')
        for name in ('previous_archive','previous_head','head','payload_sha256','token'):
            if type(body[name]) is not str or not HASH.fullmatch(body[name]):raise ValueError('GG_OWN_JOURNAL_HEADER')
        first=number(body['first'],positive=True,allow_int=False);last=number(body['last'],positive=True,allow_int=False)
        if (first>last or number(body['records'],positive=True,allow_int=False)!=last-first+1 or last-first+1>MAX_SEGMENT_RECORDS
                or number(body['bytes'],positive=True,allow_int=False)>MAX_ACTIVE_BYTES):raise ValueError('GG_OWN_JOURNAL_BOUND')
        number(body['number'],positive=True,allow_int=False)
        signature=value['signature']
        if type(signature) is not str or not re.fullmatch(r'[0-9a-f]{128}',signature):raise ValueError('GG_OWN_JOURNAL_SIGNATURE')
        verify_signature(bytes.fromhex(self.context['owner_key']),DOMAIN+pack(body),bytes.fromhex(signature))
        return body

    def catalog(self,*,reverse=False):
        query='SELECT number,first_position,last_position,digest,length(header),typeof(header) FROM journal_archives ORDER BY number '+('DESC' if reverse else 'ASC')
        for index,first,last,digest,size,kind in self.owner._db.execute(query):
            if kind!='blob' or not 0<size<=16384:raise ValueError('GG_OWN_JOURNAL_HEADER')
            raw=self.owner._db.execute('SELECT header FROM journal_archives WHERE number=?',(index,)).fetchone()[0]
            header=self._header(bytes(raw))
            if (number(header['number'])!=index or number(header['first'])!=first or number(header['last'])!=last):raise ValueError('GG_OWN_JOURNAL_CATALOG')
            yield index,first,last,digest,bytes(raw),header

    def _records(self,db,*,position=None,selector=None,epoch=None,before=None,reverse=False):
        # Do not let a secondary SQLite index define authenticated absence.
        # Consult the canonical record table after the enclosing actual hash.
        query='SELECT position,selector,epoch,length(metadata),typeof(metadata),length(document),typeof(document) FROM records NOT INDEXED'
        clauses=[];args=[]
        for field,value in (('position',position),('selector',selector),('epoch',epoch)):
            if value is not None:clauses.append(field+'=?');args.append(value)
        if before is not None:clauses.append('position<?');args.append(before)
        if clauses:query+=' WHERE '+' AND '.join(clauses)
        query+=' ORDER BY position '+('DESC' if reverse else 'ASC')
        for index,key,ep,meta_size,meta_kind,size,kind in db.execute(query,args):
            if (type(key) is not str or len(key)>256 or type(ep) is not str or len(ep)>20 or meta_kind!='blob' or not 0<meta_size<=4096
                    or kind!='blob' or not 0<size<=MAX_DOCUMENT):raise ValueError('GG_OWN_JOURNAL_RECORD')
            metadata,document=db.execute('SELECT metadata,document FROM records WHERE position=?',(index,)).fetchone()
            meta=unpack(metadata)
            if pack(meta)!=metadata:raise ValueError('GG_OWN_JOURNAL_RECORD')
            yield index,key,ep,meta,document

    def _stamp(self,path):
        info=producer_files.regular(path);_private_path(path,0o600)
        if info.st_size>MAX_SEGMENT_BYTES:raise ValueError('GG_OWN_JOURNAL_BOUND')
        stamp=_stat_stamp(info)
        if os.name=='nt':
            # Windows path stat can expose creation time as st_ctime while
            # fstat exposes ChangeTime. Bind their shared identity/metadata,
            # excluding only that incompatible field. Real kernel ChangeTime
            # is queried twice on this same validated fd: no fallback, no
            # content witness or warm full-history payload hashing.
            reference=stamp[:4]+stamp[5:]
            descriptor=secure_open(path,os.O_RDONLY,0o600)
            try:
                for attempt in range(2):
                    actual=os.fstat(descriptor);opened=_stat_stamp(actual)
                    if not os.path.samestat(info,actual) or opened[:4]+opened[5:]!=reference:
                        raise ValueError('GG_OWN_JOURNAL_CHANGED')
                    observed=_windows_change_time(descriptor)
                    if attempt==0:changed=observed
                    elif observed!=changed:raise ValueError('GG_OWN_JOURNAL_CHANGED')
            finally:os.close(descriptor)
            if _stat_stamp(producer_files.regular(path))!=stamp:raise ValueError('GG_OWN_JOURNAL_CHANGED')
            return stamp+(changed,)
        return stamp

    def _inventory_value(self,journal,*,pending=False,check=lambda:None):
        root=self.directory();aggregate=0;count=0;unknown=0
        with os.scandir(root) as entries:
            for item in entries:
                check()
                path=Path(item.path);name=path.name
                if pending and journal['pending'] and name=='pending-'+journal['pending']['token']+'.ggjournal':
                    info=path.lstat()
                    if is_link(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink not in (1,2) or info.st_size>MAX_SEGMENT_BYTES:
                        raise ValueError('GG_OWN_JOURNAL_PENDING')
                    _private_path(path,0o600);continue
                if not re.fullmatch(r'[0-9a-f]{64}\.ggjournal',name):raise ValueError('GG_OWN_JOURNAL_FOREIGN_FILE')
                digest=name[:64]
                known=self.owner._db.execute('SELECT 1 FROM journal_archives WHERE digest=?',(digest,)).fetchone()
                if known is None:
                    if not pending or journal['pending'] is None or unknown:raise ValueError('GG_OWN_JOURNAL_FOREIGN_FILE')
                    with self._open(digest,verify=True) as db:
                        raw=bytes(db.execute('SELECT record FROM header WHERE id=1').fetchone()[0]);body=self._header(raw)
                        if any(body[key]!=journal['pending'][key] for key in ('token','first','last','previous_head','head')):
                            raise ValueError('GG_OWN_JOURNAL_PENDING')
                    unknown+=1;continue
                stamp=self._stamp(path);aggregate^=int.from_bytes(hashlib.sha256(pack([name,list(stamp)])).digest(),'big');count+=1
        if count!=number(journal['archive_count']):raise ValueError('GG_OWN_JOURNAL_MISSING_SEGMENT')
        info=root.stat()
        return (info.st_dev,info.st_ino,count,aggregate)

    def _discard_pending(self,pending,check):
        # Only these exact temporary names were reserved by the sealed intent.
        # Original rows are still active; published immutable segments remain.
        root=self.directory();path=root/('pending-'+pending['token']+'.ggjournal')
        if path.exists() or is_link(path):
            info=path.lstat()
            if is_link(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink not in (1,2) or info.st_size>MAX_SEGMENT_BYTES:
                raise ValueError('GG_OWN_JOURNAL_PENDING')
            _private_path(path,0o600)
            if info.st_nlink==2:
                digest=producer_files.file_hash(path,links=2,check=check);final=root/(digest+'.ggjournal')
                if is_link(final) or not final.exists() or not os.path.samefile(path,final):raise ValueError('GG_OWN_JOURNAL_PENDING')
            path.unlink()
        rollback=root/(path.name+'-journal')
        if rollback.exists() or is_link(rollback):
            info=rollback.lstat()
            if is_link(rollback) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_SEGMENT_BYTES:
                raise ValueError('GG_OWN_JOURNAL_PENDING')
            _private_path(rollback,0o600);rollback.unlink()
        sync_directory(root)

    def check_inventory(self,journal,*,full=False,pending=False,check=lambda:None):
        if pending and journal['pending']:self._discard_pending(journal['pending'],check)
        self._guard();actual=self._inventory_value(journal,pending=pending,check=check)
        if full or actual!=self._inventory:
            count=0;last=ZERO;through=0;head=self.initial_head;total_bytes=0
            for index,first,end,digest,raw,body in self.catalog():
                check();count+=1
                if (index!=count or first!=through+1 or body['previous_archive']!=last or body['previous_head']!=head):
                    raise ValueError('GG_OWN_JOURNAL_CHAIN')
                with self._open(digest,verify=True,check=check) as db:
                    saved=db.execute('SELECT record FROM header WHERE id=1').fetchone()
                    if saved is None or bytes(saved[0])!=raw:raise ValueError('GG_OWN_JOURNAL_CATALOG')
                last=digest;through=end;head=body['head'];total_bytes+=number(body['bytes'])
            if (count!=number(journal['archive_count']) or through!=number(journal['through']) or last!=journal['archive_head']
                    or head!=journal['record_head'] or total_bytes!=number(journal['archived_bytes'])):
                raise ValueError('GG_OWN_JOURNAL_CHAIN')
            if self._inventory_value(journal,pending=pending,check=check)!=actual:raise ValueError('GG_OWN_JOURNAL_CHANGED')
            self._inventory=actual

    @contextmanager
    def _open(self,digest,*,verify=False,pending_path=None,check=lambda:None):
        self._guard()
        if self._readers>=MAX_READERS:raise ValueError('GG_OWN_JOURNAL_READER_LIMIT')
        path=self._path(digest) if pending_path is None else pending_path
        if path.parent!=self.directory() or pending_path is not None and not re.fullmatch(r'pending-[0-9a-f]{64}\.ggjournal',path.name):
            raise ValueError('GG_OWN_JOURNAL_PENDING')
        before=self._stamp(path);db=None;self._readers+=1;retained=False
        try:
            if verify and producer_files.file_hash(path,check=check)!=digest:raise ValueError('GG_OWN_JOURNAL_CORRUPT')
            db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=0,isolation_level=None)
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA cache_size=-1024');db.execute('PRAGMA query_only=ON')
            if dict(db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL"))!=SEGMENT_SQL:
                raise ValueError('GG_OWN_JOURNAL_SCHEMA')
            yield db
        except (ValueError,OSError,sqlite3.Error,KeyError,TypeError,OverflowError):
            self.owner._failed=True;raise
        finally:
            try:
                if db is not None:
                    try:db.close()
                    except BaseException:
                        self._pending_readers.append(db);retained=True;raise
                if self._stamp(path)!=before or verify and producer_files.file_hash(path,check=check)!=digest:
                    raise ValueError('GG_OWN_JOURNAL_CHANGED')
            except (ValueError,OSError,sqlite3.Error,KeyError,TypeError,OverflowError):
                self.owner._failed=True;raise
            finally:
                if not retained:self._readers-=1

    def close_readers(self):
        remaining=[]
        for reader in self._pending_readers:
            try:reader.close()
            except BaseException:remaining.append(reader)
            else:self._readers-=1
        self._pending_readers=remaining
        if self._readers:raise ValueError('GG_OWN_JOURNAL_READERS_PENDING')

    def rows(self,journal,*,position=None,selector=None,epoch=None,before=None,reverse=False,full=False,check=lambda:None):
        self.check_inventory(journal,full=full,pending=journal['pending'] is not None,check=check)
        # Authenticate the complete catalog closure before either positive or
        # negative queries. A SQLite index miss is not authenticated absence.
        count=0;through=0;previous=ZERO;record_head=self.initial_head;catalog_bytes=0
        for index,first,last,digest,raw,header in self.catalog():
            check();count+=1
            if (index!=count or first!=through+1 or header['previous_archive']!=previous
                    or header['previous_head']!=record_head):raise ValueError('GG_OWN_JOURNAL_CHAIN')
            through=last;previous=digest;record_head=header['head'];catalog_bytes+=number(header['bytes'])
        if (count!=number(journal['archive_count']) or through!=number(journal['through']) or previous!=journal['archive_head']
                or record_head!=journal['record_head'] or catalog_bytes!=number(journal['archived_bytes'])):raise ValueError('GG_OWN_JOURNAL_CHAIN')
        filtered=position is not None or selector is not None or epoch is not None or before is not None
        for index,first,last,digest,raw,header in self.catalog(reverse=reverse):
            check()
            if position is not None and not first<=position<=last or before is not None and first>=before:continue
            count=0;size=0;payload=hashlib.sha256()
            # Every consulted filtered segment is actually hashed even for a
            # no-match, including unchanged-size/mtime corruption of its index.
            with self._open(digest,verify=True,check=check) as db:
                for index,key,ep,metadata,document in self._records(db,position=position,selector=selector,epoch=epoch,before=before,reverse=reverse):
                    check()
                    if not first<=index<=last:raise ValueError('GG_OWN_JOURNAL_RECORD')
                    count+=1;size+=len(document);payload.update(pack([str(index),key,ep,metadata,hashlib.sha256(document).hexdigest()]))
                    yield index,key,ep,metadata,document
            if position is None and selector is None and epoch is None and before is None and not reverse:
                if (count!=number(header['records']) or size!=number(header['bytes']) or payload.hexdigest()!=header['payload_sha256']):
                    raise ValueError('GG_OWN_JOURNAL_CONTENT')

    def publish(self,journal,pending,rows,*,check=lambda:None):
        self.directory(create=True)
        token=pending['token'];path=self.root/('pending-'+token+'.ggjournal')
        self._discard_pending(pending,check)
        if shutil.disk_usage(self.root).free<2*MAX_SEGMENT_BYTES:raise ValueError('GG_OWN_JOURNAL_DISK_RESERVE')
        fd=secure_open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        db=None;count=0;size=0;payload=hashlib.sha256();previous=number(pending['first'])-1
        try:
            db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None)
            for pragma in ('PRAGMA page_size=4096','PRAGMA trusted_schema=OFF','PRAGMA journal_mode=DELETE','PRAGMA synchronous=EXTRA','PRAGMA cache_size=-1024','PRAGMA temp_store=MEMORY'):
                db.execute(pragma)
            if (db.execute('PRAGMA page_size').fetchone()!=(4096,) or db.execute('PRAGMA journal_mode').fetchone()!=('delete',)
                    or db.execute('PRAGMA synchronous').fetchone()!=(3,)):
                raise ValueError('GG_OWN_JOURNAL_DURABILITY')
            pages=MAX_SEGMENT_BYTES//4096
            if db.execute('PRAGMA max_page_count='+str(pages)).fetchone()!=(pages,):raise ValueError('GG_OWN_JOURNAL_BOUND')
            db.execute('BEGIN IMMEDIATE')
            for statement in SEGMENT_SQL.values():db.execute(statement)
            for index,key,epoch,meta,document in rows:
                check()
                if (index!=previous+1 or type(key) is not str or len(key)>256 or type(epoch) is not str or len(epoch)>20
                        or type(document) is not bytes or not 0<len(document)<=MAX_DOCUMENT or not 0<len(pack(meta))<=4096):
                    raise ValueError('GG_OWN_JOURNAL_RECORD')
                previous=index;count+=1;size+=len(document)
                if count>MAX_SEGMENT_RECORDS or size>MAX_ACTIVE_BYTES:raise ValueError('GG_OWN_JOURNAL_BOUND')
                db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(index,key,epoch,pack(meta),document))
                payload.update(pack([str(index),key,epoch,meta,hashlib.sha256(document).hexdigest()]))
            if not count or previous!=number(pending['last']):raise ValueError('GG_OWN_JOURNAL_PENDING')
            body={'schema':HEADER_SCHEMA,'kind':self.kind,'context':deepcopy(self.context),
                  'number':str(number(journal['archive_count'])+1),'previous_archive':journal['archive_head'],
                  'records':str(count),'bytes':str(size),'payload_sha256':payload.hexdigest(),**deepcopy(pending)}
            raw=pack({'body':body,'signature':self.owner._key.sign_message(DOMAIN+pack(body)).hex()})
            self._header(raw);db.execute('INSERT INTO header VALUES(1,?)',(raw,));db.execute('COMMIT')
            db.close();db=None
            self._stamp(path)
            descriptor=secure_open(path,os.O_RDWR,0o600)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
            digest=producer_files.file_hash(path,check=check);final=self.root/(digest+'.ggjournal')
            # Readback authenticates actual file bytes before publication. It
            # does not grant those bytes any native/global consensus authority.
            with self._open(digest,verify=True,pending_path=path,check=check) as reopened:
                saved=reopened.execute('SELECT record FROM header WHERE id=1').fetchone()
                if saved is None or bytes(saved[0])!=raw or reopened.execute('SELECT count(*) FROM records').fetchone()!=(count,):
                    raise ValueError('GG_OWN_JOURNAL_READBACK')
                actual=hashlib.sha256();actual_count=0;actual_size=0;last=number(pending['first'])-1
                for index,key,epoch,meta,document in self._records(reopened):
                    check()
                    if index!=last+1:raise ValueError('GG_OWN_JOURNAL_READBACK')
                    actual.update(pack([str(index),key,epoch,meta,hashlib.sha256(document).hexdigest()]))
                    last=index;actual_count+=1;actual_size+=len(document)
                if actual.hexdigest()!=body['payload_sha256'] or actual_count!=count or actual_size!=size:
                    raise ValueError('GG_OWN_JOURNAL_READBACK')
            if final.exists() or is_link(final):
                self._stamp(final)
                if producer_files.file_hash(final,check=check)!=digest:raise ValueError('GG_OWN_JOURNAL_COLLISION')
            else:os.link(path,final)
            path.unlink();sync_directory(self.root)
            with self._open(digest,verify=True,check=check) as published:
                saved=published.execute('SELECT record FROM header WHERE id=1').fetchone()
                if saved is None or bytes(saved[0])!=raw:raise ValueError('GG_OWN_JOURNAL_READBACK')
            self._publication=_PublishedSegment(self,digest,raw,body,self._stamp(final),self._inventory,token=_PUBLISH_TOKEN)
            return digest,raw,body
        finally:
            if db is not None:
                try:db.close()
                except BaseException:
                    self._pending_readers.append(db);self._readers+=1;raise

    def committed(self,journal,*,check=lambda:None):
        publication=self._publication;self._publication=None
        if type(publication) is not _PublishedSegment or publication.owner is not self or publication.base is None:
            raise ValueError('GG_OWN_JOURNAL_READBACK_REQUIRED')
        body=unpack(publication.body)
        if (journal['archive_head']!=publication.digest or journal['archive_count']!=body['number'] or journal['through']!=body['last']
                or journal['record_head']!=body['head'] or journal['pending'] is not None):raise ValueError('GG_OWN_JOURNAL_CHAIN')
        row=self.owner._db.execute('SELECT header FROM journal_archives WHERE number=?',(int(body['number']),)).fetchone()
        if row is None or bytes(row[0])!=publication.raw:raise ValueError('GG_OWN_JOURNAL_CATALOG')
        path=self._path(publication.digest)
        if self._stamp(path)!=publication.stamp:raise ValueError('GG_OWN_JOURNAL_CHANGED')
        base=publication.base
        added=int.from_bytes(hashlib.sha256(pack([path.name,list(publication.stamp)])).digest(),'big')
        expected=(base[0],base[1],base[2]+1,base[3]^added)
        actual=self._inventory_value(journal,check=check)
        if actual!=expected:raise ValueError('GG_OWN_JOURNAL_CHANGED')
        # Actual new payload was already fully read back. Only the exact owned
        # publication delta may extend the previous verified inventory witness.
        self._inventory=actual
        count=0;through=0;previous=ZERO;record_head=self.initial_head;size=0
        for index,first,last,digest,raw,header in self.catalog():
            check();count+=1
            if index!=count or first!=through+1 or header['previous_archive']!=previous or header['previous_head']!=record_head:
                raise ValueError('GG_OWN_JOURNAL_CHAIN')
            through=last;previous=digest;record_head=header['head'];size+=number(header['bytes'])
        if (count!=number(journal['archive_count']) or through!=number(journal['through']) or previous!=journal['archive_head']
                or record_head!=journal['record_head'] or size!=number(journal['archived_bytes'])):raise ValueError('GG_OWN_JOURNAL_CHAIN')

    def status(self,journal,total,active_count,active_bytes):
        return journal_status(self.kind,journal,total,active_count,active_bytes)
