"""Bounded immutable archives of OWN journal wires, never global DAG history."""
import hashlib
import os
import shutil
import stat
import struct

from backend.gg_node_store import pack,unpack,_private_path,HEX
from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory

MAGIC=b'GGOWNJ1\0'
MAX_BYTES=512*1024*1024
MAX_WIRE=32*1024*1024
MAX_RECORDS=4095
ZERO='0'*64


def empty_head(anchor,epoch):
    return {'records':0,'bytes':0,'digest':hashlib.sha256(b'GG-OWN-PRODUCER-JOURNAL-v1\0'+pack({'anchor':anchor,'epoch':epoch})).hexdigest()}


def advance(head,raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_WIRE:raise ValueError('GG_PRODUCER_JOURNAL_WIRE')
    count=head['records']+1;size=head['bytes']+len(raw)
    if count>MAX_RECORDS or size>MAX_BYTES:raise ValueError('GG_PRODUCER_JOURNAL_LIMIT')
    return {'records':count,'bytes':size,'digest':hashlib.sha256(b'GG-OWN-PRODUCER-ENTRY-v1\0'+bytes.fromhex(head['digest'])+
            count.to_bytes(8,'big')+hashlib.sha256(raw).digest()).hexdigest()}


def directory(profile,*,create=False):
    path=profile.root/'producer-epochs'
    if create and not path.exists():path.mkdir(mode=0o700);set_private_mode(path,0o700);sync_directory(profile.root)
    if not path.is_dir() or is_link(path):raise ValueError('GG_PRODUCER_ARCHIVE_DIRECTORY')
    _private_path(path,0o700)
    return path


def _regular(path,*,links=1):
    info=path.lstat()
    if is_link(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=links or not 8<=info.st_size<=MAX_BYTES+2*1024*1024:
        raise ValueError('GG_PRODUCER_ARCHIVE_FILE')
    _private_path(path,0o600)
    return info


def _file_hash(path,*,links=1,check=lambda:None,info=None):
    if info is None:info=_regular(path,links=links)
    digest=hashlib.sha256()
    with path.open('rb') as file:
        if not os.path.samestat(info,os.fstat(file.fileno())):raise ValueError('GG_PRODUCER_ARCHIVE_CHANGED')
        while True:
            check();raw=file.read(64*1024)
            if not raw:break
            digest.update(raw)
        after=os.fstat(file.fileno())
        if after.st_size!=info.st_size or after.st_mtime_ns!=info.st_mtime_ns:raise ValueError('GG_PRODUCER_ARCHIVE_CHANGED')
    return digest.hexdigest()


def inspect_file(path,anchor,owner,*,expected=None,check=lambda:None,links=1):
    """Rehash every bounded raw frame; no global history/SDK assertion here."""
    info=_regular(path,links=links)
    if type(expected) is not str or not HEX.fullmatch(expected) or _file_hash(path,links=links,check=check,info=info)!=expected:
        raise ValueError('GG_PRODUCER_ARCHIVE_HASH')
    # Authenticate bytes before decoding their collections; still hash the
    # second owned-file pass so a replacement cannot reuse the first result.
    whole=hashlib.sha256();content=hashlib.sha256()
    with path.open('rb') as file:
        opened=os.fstat(file.fileno())
        if not os.path.samestat(info,opened) or opened.st_size!=info.st_size or opened.st_mtime_ns!=info.st_mtime_ns:raise ValueError('GG_PRODUCER_ARCHIVE_CHANGED')
        def read(size,*,body=True):
            check();raw=file.read(size)
            if len(raw)!=size:raise ValueError('GG_PRODUCER_ARCHIVE_TRUNCATED')
            whole.update(raw)
            if body:content.update(raw)
            return raw
        if read(8)!=MAGIC:raise ValueError('GG_PRODUCER_ARCHIVE_FORMAT')
        def frame(kind,limit,*,body=True):
            prefix=read(5,body=body)
            length=struct.unpack('>I',prefix[1:])[0]
            if prefix[:1]!=kind or not 0<length<=limit:raise ValueError('GG_PRODUCER_ARCHIVE_FRAME')
            return read(length,body=body)
        header=unpack(frame(b'H',1024*1024))
        if (not isinstance(header,dict) or set(header)!={'schema','genesis_hash','owner_key','epoch','closing_epoch','previous_archive','base_packet','closing_packet','head'}
                or header['schema']!='gg.node.producer-epoch-archive.v1' or header['genesis_hash']!=anchor or header['owner_key']!=owner
                or any(type(header[name]) is not str or not header[name].isdigit() or str(int(header[name]))!=header[name] for name in ('epoch','closing_epoch'))
                or not 1<=int(header['epoch'])<int(header['closing_epoch'])<=2**63-1
                or type(header['previous_archive']) is not str or not HEX.fullmatch(header['previous_archive'])):raise ValueError('GG_PRODUCER_ARCHIVE_CONTEXT')
        head=empty_head(anchor,header['epoch']);declared=header['head']
        if (not isinstance(declared,dict) or set(declared)!={'records','bytes','digest'} or type(declared['records']) is not int
                or not 0<=declared['records']<=MAX_RECORDS or type(declared['bytes']) is not int or not 0<=declared['bytes']<=MAX_BYTES):
            raise ValueError('GG_PRODUCER_ARCHIVE_HEAD')
        for _ in range(declared['records']):head=advance(head,frame(b'R',min(MAX_WIRE,MAX_BYTES-head['bytes'])))
        digest=content.hexdigest();footer=unpack(frame(b'F',65536,body=False))
        if (head!=declared or footer!={'schema':'gg.node.producer-archive-footer.v1','content_sha256':digest,'head':head}
                or file.read(1) or os.fstat(file.fileno()).st_size!=info.st_size or os.fstat(file.fileno()).st_mtime_ns!=info.st_mtime_ns):raise ValueError('GG_PRODUCER_ARCHIVE_CONTENT')
    result=whole.hexdigest()
    if expected is not None and expected!=result:raise ValueError('GG_PRODUCER_ARCHIVE_HASH')
    return result,header


def inspect_chain(profile,state,*,check=lambda:None):
    identifier=state['archive'];count=int(state['archive_count']);next_epoch=state['base_packet']['state']['dag_segmented']['epoch']
    if count==0:
        if identifier!=ZERO:raise ValueError('GG_PRODUCER_ARCHIVE_CHAIN')
        return
    root=directory(profile)
    while count:
        check()
        if identifier==ZERO or not HEX.fullmatch(identifier):raise ValueError('GG_PRODUCER_ARCHIVE_CHAIN')
        _,header=inspect_file(root/(identifier+'.ggown'),state['genesis_hash'],state['owner_key'],expected=identifier,check=check)
        if header['closing_epoch']!=next_epoch:raise ValueError('GG_PRODUCER_ARCHIVE_CHAIN')
        identifier=header['previous_archive'];next_epoch=header['epoch'];count-=1
    if identifier!=ZERO:raise ValueError('GG_PRODUCER_ARCHIVE_CHAIN')


def write_current(profile,state,rows,closing_packet,token,*,check=lambda:None):
    """Only call after the archive intent is committed in the sealed profile.

    A crash leaves the same declared pending path and original SQLite rows.
    Recovery may rebuild that own path; immutable published files never change.
    """
    if not isinstance(token,str) or not HEX.fullmatch(token):raise ValueError('GG_PRODUCER_ARCHIVE_INTENT')
    root=directory(profile,create=True);pending=root/('pending-'+token+'.ggown')
    if pending.exists() or is_link(pending):
        info=pending.lstat()
        if is_link(pending) or not stat.S_ISREG(info.st_mode) or info.st_nlink not in (1,2):raise ValueError('GG_PRODUCER_ARCHIVE_PENDING')
        _private_path(pending,0o600)
        if info.st_nlink==2:
            digest=_file_hash(pending,check=check,links=2)
            final=root/(digest+'.ggown')
            if is_link(final) or not final.exists() or not os.path.samefile(pending,final):raise ValueError('GG_PRODUCER_ARCHIVE_PENDING')
        pending.unlink()  # exact sealed-intent path, no recursive cleanup
    if shutil.disk_usage(root).free<state['head']['bytes']+66*1024*1024:raise ValueError('GG_PRODUCER_ARCHIVE_DISK_RESERVE')
    header={'schema':'gg.node.producer-epoch-archive.v1','genesis_hash':state['genesis_hash'],'owner_key':state['owner_key'],
        'epoch':state['base_packet']['state']['dag_segmented']['epoch'],'closing_epoch':closing_packet['state']['dag_segmented']['epoch'],
        'previous_archive':state['archive'],'base_packet':state['base_packet'],'closing_packet':closing_packet,'head':state['head']}
    encoded_header=pack(header)
    if len(encoded_header)>1024*1024:raise ValueError('GG_PRODUCER_ARCHIVE_HEADER_LIMIT')
    digest=hashlib.sha256();head=empty_head(state['genesis_hash'],header['epoch'])
    descriptor=secure_open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as file:
        def write(raw):
            check()
            if file.write(raw)!=len(raw):raise OSError('GG_PRODUCER_ARCHIVE_SHORT_WRITE')
            digest.update(raw)
        def frame(kind,raw):write(kind+struct.pack('>I',len(raw)));write(raw)
        write(MAGIC);frame(b'H',encoded_header)
        for raw in rows:head=advance(head,raw);frame(b'R',raw)
        if head!=state['head']:raise ValueError('GG_PRODUCER_ARCHIVE_HEAD')
        content=digest.hexdigest();frame(b'F',pack({'schema':'gg.node.producer-archive-footer.v1','content_sha256':content,'head':head}))
        file.flush();os.fsync(file.fileno())
    full=digest.hexdigest();actual,readback=inspect_file(pending,state['genesis_hash'],state['owner_key'],expected=full,check=check)
    if readback!=header:raise ValueError('GG_PRODUCER_ARCHIVE_READBACK')
    final=root/(full+'.ggown')
    if final.exists() or is_link(final):inspect_file(final,state['genesis_hash'],state['owner_key'],expected=full,check=check)
    else:os.link(pending,final)
    pending.unlink();sync_directory(root)
    inspect_file(final,state['genesis_hash'],state['owner_key'],expected=full,check=check)
    return full
