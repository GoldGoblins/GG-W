"""Immutable bounded own-original chunks; no SDK selection or validator backup.

The sealed profile pins the complete file hash and its append-chain position.
Readers authenticate before parsing and keep one original/context in memory.
"""
import hashlib
import os
import shutil
import stat
import struct

from backend.gg_node_store import pack,unpack,_private_path,HEX
from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory

MAGIC=b'GGFINO1\0'
ZERO='0'*64
MAX_RECORDS=8191
MAX_BYTES=512*1024*1024
MAX_WIRE=32*1024*1024
MAX_CONTEXT=256*1024
MAX_FILE=MAX_BYTES+8*1024*1024


def directory(profile,*,create=False):
    path=profile.root/'financial-originals'
    if create and not path.exists():
        path.mkdir(mode=0o700);set_private_mode(path,0o700);sync_directory(profile.root)
    if not path.is_dir() or is_link(path):raise ValueError('GG_FINANCIAL_ARCHIVE_DIRECTORY')
    _private_path(path,0o700);return path


def regular(path,*,links=1):
    info=path.lstat()
    if (is_link(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=links
            or not 8<=info.st_size<=MAX_FILE):raise ValueError('GG_FINANCIAL_ARCHIVE_FILE')
    _private_path(path,0o600);return info


def _opened(path,info):
    file=os.fdopen(secure_open(path,os.O_RDONLY),'rb')
    actual=os.fstat(file.fileno())
    if not os.path.samestat(info,actual) or actual.st_size!=info.st_size or actual.st_mtime_ns!=info.st_mtime_ns:
        file.close();raise ValueError('GG_FINANCIAL_ARCHIVE_CHANGED')
    return file


def file_hash(path,*,links=1,check=lambda:None):
    info=regular(path,links=links);digest=hashlib.sha256()
    with _opened(path,info) as file:
        while True:
            check();raw=file.read(64*1024)
            if not raw:break
            digest.update(raw)
        end=os.fstat(file.fileno())
        if end.st_size!=info.st_size or end.st_mtime_ns!=info.st_mtime_ns:raise ValueError('GG_FINANCIAL_ARCHIVE_CHANGED')
    return digest.hexdigest()


def inspect_file(path,anchor,owner,*,expected,check=lambda:None,on_record=lambda *args:None,links=1):
    from backend import gg_financial_producer as journal
    info=regular(path,links=links)
    if type(expected) is not str or not HEX.fullmatch(expected) or file_hash(path,links=links,check=check)!=expected:
        raise ValueError('GG_FINANCIAL_ARCHIVE_HASH')
    whole=hashlib.sha256();content=hashlib.sha256();contexts={};used=set()
    with _opened(path,info) as file:
        def take(size,*,body=True):
            check();raw=file.read(size)
            if len(raw)!=size:raise ValueError('GG_FINANCIAL_ARCHIVE_TRUNCATED')
            whole.update(raw)
            if body:content.update(raw)
            return raw
        if take(8)!=MAGIC:raise ValueError('GG_FINANCIAL_ARCHIVE_FORMAT')
        prefix=take(5);length=struct.unpack('>I',prefix[1:])[0]
        if prefix[:1]!=b'H' or not 0<length<=4096:raise ValueError('GG_FINANCIAL_ARCHIVE_HEADER')
        header=unpack(take(length));fields={'schema','genesis_hash','owner_key','number','previous_archive','base','head'}
        if (not isinstance(header,dict) or set(header)!=fields or header['schema']!='gg.financial.own-archive.v1'
                or header['genesis_hash']!=anchor or header['owner_key']!=owner or type(header['number']) is not int
                or not 1<=header['number']<=journal.financial.MAX_COUNTER
                or type(header['previous_archive']) is not str or not HEX.fullmatch(header['previous_archive'])):
            raise ValueError('GG_FINANCIAL_ARCHIVE_HEADER')
        base=header['base'];declared=header['head'];journal._check_head(base);journal._check_head(declared)
        if (not 1<=declared['records']-base['records']<=MAX_RECORDS
                or not 0<declared['bytes']-base['bytes']<=MAX_BYTES
                or not 0<=declared['context_bytes']-base['context_bytes']<=MAX_BYTES
                or declared['bytes']-base['bytes']+declared['context_bytes']-base['context_bytes']>MAX_BYTES):
            raise ValueError('GG_FINANCIAL_ARCHIVE_HEAD')
        head=dict(base);finished=False
        for _ in range(2*MAX_RECORDS+1):
            digest=content.hexdigest();prefix=take(5,body=False);kind=prefix[:1];length=struct.unpack('>I',prefix[1:])[0]
            if kind==b'F':
                if not 0<length<=4096:raise ValueError('GG_FINANCIAL_ARCHIVE_FOOTER')
                footer=unpack(take(length,body=False))
                if (footer!={'schema':'gg.financial.own-archive-footer.v1','content_sha256':digest,'head':head}
                        or head!=declared or set(contexts)!=used or file.read(1)):raise ValueError('GG_FINANCIAL_ARCHIVE_CONTENT')
                finished=True;break
            content.update(prefix)
            if kind==b'C':
                if not 32<length<=32+MAX_CONTEXT or len(contexts)>=MAX_RECORDS:raise ValueError('GG_FINANCIAL_ARCHIVE_CONTEXT')
                identifier=take(32).hex();offset=file.tell();raw=take(length-32)
                if identifier in contexts or journal._context_id(raw)!=identifier:raise ValueError('GG_FINANCIAL_ARCHIVE_CONTEXT')
                unpack(raw);contexts[identifier]=(offset,len(raw));head['context_bytes']+=len(raw)
            elif kind==b'R':
                if not 4<length<=MAX_WIRE+1028:raise ValueError('GG_FINANCIAL_ARCHIVE_RECORD')
                size=struct.unpack('>I',take(4))[0]
                if not 0<size<=1024 or not 0<length-4-size<=MAX_WIRE:raise ValueError('GG_FINANCIAL_ARCHIVE_RECORD')
                row=unpack(take(size));offset=file.tell();raw=take(length-4-size)
                if not isinstance(row,list) or len(row)!=7 or any(type(row[i]) is not int for i in range(4)):
                    raise ValueError('GG_FINANCIAL_ARCHIVE_RECORD')
                head=journal._advance(head,row,len(raw));identifier=row[5]
                if hashlib.sha256(raw).hexdigest()!=row[6] or identifier not in contexts:raise ValueError('GG_FINANCIAL_ARCHIVE_RECORD')
                context_offset,context_size=contexts[identifier];resume=file.tell();file.seek(context_offset)
                packet=file.read(context_size);file.seek(resume)
                if journal._context_id(packet)!=identifier:raise ValueError('GG_FINANCIAL_ARCHIVE_CONTEXT')
                used.add(identifier);on_record(tuple(row),raw,packet,(offset,context_offset,context_size))
            else:raise ValueError('GG_FINANCIAL_ARCHIVE_FRAME')
            if (head['records']>declared['records'] or head['bytes']>declared['bytes']
                    or head['context_bytes']>declared['context_bytes']):raise ValueError('GG_FINANCIAL_ARCHIVE_HEAD')
        end=os.fstat(file.fileno())
        if not finished or end.st_size!=info.st_size or end.st_mtime_ns!=info.st_mtime_ns or whole.hexdigest()!=expected:
            raise ValueError('GG_FINANCIAL_ARCHIVE_CHANGED')
    return header


def write_current(profile,state,rows,*,check=lambda:None):
    """Sealed intent must exist before this two-phase immutable publication."""
    from backend import gg_financial_producer as journal
    token=state['pending_archive']['token']
    if type(token) is not str or not HEX.fullmatch(token):raise ValueError('GG_FINANCIAL_ARCHIVE_INTENT')
    root=directory(profile,create=True);pending=root/('pending-'+token+'.ggfin')
    if pending.exists() or is_link(pending):
        info=pending.lstat()
        if (is_link(pending) or not stat.S_ISREG(info.st_mode) or info.st_nlink not in (1,2)
                or not 0<=info.st_size<=MAX_FILE):raise ValueError('GG_FINANCIAL_ARCHIVE_PENDING')
        _private_path(pending,0o600)
        if info.st_nlink==2:
            identifier=file_hash(pending,links=2,check=check);final=root/(identifier+'.ggfin')
            if is_link(final) or not final.exists() or not os.path.samefile(pending,final):raise ValueError('GG_FINANCIAL_ARCHIVE_PENDING')
        pending.unlink()
    active=state['head']['bytes']-state['archived_head']['bytes']+state['head']['context_bytes']-state['archived_head']['context_bytes']
    if shutil.disk_usage(root).free<active+72*1024*1024:raise ValueError('GG_FINANCIAL_ARCHIVE_DISK_RESERVE')
    header={'schema':'gg.financial.own-archive.v1','genesis_hash':state['genesis_hash'],'owner_key':state['owner_key'],
        'number':state['archive_count']+1,'previous_archive':state['archive'],'base':state['archived_head'],'head':state['head']}
    digest=hashlib.sha256();head=dict(header['base']);contexts=set()
    descriptor=secure_open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as file:
        def write(raw):
            check()
            if file.write(raw)!=len(raw):raise OSError('GG_FINANCIAL_ARCHIVE_SHORT_WRITE')
            digest.update(raw)
        def frame(kind,parts):
            write(kind+struct.pack('>I',sum(map(len,parts))))
            for raw in parts:write(raw)
        write(MAGIC);frame(b'H',(pack(header),))
        for row,raw,packet in rows:
            if row[5] not in contexts:
                if journal._context_id(packet)!=row[5] or not 0<len(packet)<=MAX_CONTEXT:raise ValueError('GG_FINANCIAL_ARCHIVE_CONTEXT')
                frame(b'C',(bytes.fromhex(row[5]),packet));head['context_bytes']+=len(packet);contexts.add(row[5])
            metadata=pack(list(row));head=journal._advance(head,row,len(raw))
            if len(metadata)>1024 or hashlib.sha256(raw).hexdigest()!=row[6]:raise ValueError('GG_FINANCIAL_ARCHIVE_RECORD')
            frame(b'R',(struct.pack('>I',len(metadata)),metadata,raw))
            if file.tell()>MAX_FILE-4096:raise ValueError('GG_FINANCIAL_ARCHIVE_LIMIT')
        if head!=state['head']:raise ValueError('GG_FINANCIAL_ARCHIVE_HEAD')
        content=digest.hexdigest();frame(b'F',(pack({'schema':'gg.financial.own-archive-footer.v1','content_sha256':content,'head':head}),))
        file.flush();os.fsync(file.fileno())
    identifier=digest.hexdigest()
    if inspect_file(pending,state['genesis_hash'],state['owner_key'],expected=identifier,check=check)!=header:
        raise ValueError('GG_FINANCIAL_ARCHIVE_READBACK')
    final=root/(identifier+'.ggfin')
    if final.exists() or is_link(final):inspect_file(final,state['genesis_hash'],state['owner_key'],expected=identifier,check=check)
    else:os.link(pending,final)
    pending.unlink();sync_directory(root)
    inspect_file(final,state['genesis_hash'],state['owner_key'],expected=identifier,check=check)
    return identifier


def read_original(profile,location,identifier,wire_hash,*,check=lambda:None):
    archive,offset,size=location
    if (type(archive) is not str or not HEX.fullmatch(archive) or type(offset) is not int or type(size) is not int
            or not 0<=offset<MAX_FILE or not 0<size<=MAX_WIRE or offset+size>MAX_FILE):
        raise ValueError('GG_FINANCIAL_ARCHIVE_INDEX')
    path=directory(profile)/(archive+'.ggfin');info=regular(path)
    if offset+size>info.st_size:raise ValueError('GG_FINANCIAL_ARCHIVE_INDEX')
    with _opened(path,info) as file:
        check();file.seek(offset);raw=file.read(size);end=os.fstat(file.fileno())
        if (len(raw)!=size or end.st_size!=info.st_size or end.st_mtime_ns!=info.st_mtime_ns
                or hashlib.sha256(raw).hexdigest()!=wire_hash):raise ValueError('GG_FINANCIAL_ARCHIVE_CHANGED')
    from backend.gg_financial_dag import DOMAIN
    if hashlib.sha256(DOMAIN+b'DAG-BLOCK\0'+raw).hexdigest()!=identifier:raise ValueError('GG_FINANCIAL_ARCHIVE_CHANGED')
    return raw
