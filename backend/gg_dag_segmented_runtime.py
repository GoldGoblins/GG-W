"""Keyless Python recovery from fully SDK-verified original segment archives.

No node/profile is opened at import. The ordinary recovered view reads its
immutable archive lazily and cannot sign or ingest new traffic before a durable
resume is implemented. An explicit, small RAM experiment can exercise producer
continuation; that is not a persistent NodeProfile activation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
import stat
from types import MappingProxyType

from backend import gg_dag_segmented as segmented,gg_dag_execution_policy as rules
from backend.gg_dag_archive import _metadata
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_parallel_dag import ParallelDag,HOT_PAYLOAD_BYTES,digest
from backend.platform_files import is_link

HEADER_LIMIT=256*1024
MANIFEST_LIMIT=16*1024
SEGMENT_LIMIT=rules.MAX_HISTORY_RAW_BYTES+rules.MAX_HISTORY_BLOCKS*(MANIFEST_LIMIT+10)+2*HEADER_LIMIT+1024+32


def _read(reader,size):
    raw=reader.read(size)
    if len(raw)!=size:raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_TRUNCATED')
    return raw


def _frame_size(reader,kind,limit):
    header=_read(reader,5);size=int.from_bytes(header[1:],'big')
    if header[:1]!=kind or not 0<size<=limit:raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_FRAME')
    return size


def _frame(reader,kind,limit):return _read(reader,_frame_size(reader,kind,limit))


class _ArchivePayloadReader:
    """At most 4095 immutable active payload offsets, no retained file handle."""
    def __init__(self,reader):
        self.path=reader.path;self.info=reader.info;self._index={};self._ready=False
    def register(self,identifier,offset,size,wire_hash):
        if self._ready or identifier in self._index or len(self._index)>=rules.MAX_HISTORY_BLOCKS:
            raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_INDEX')
        self._index[identifier]=(offset,size,wire_hash)
    def seal(self):self._index=MappingProxyType(self._index);self._ready=True
    def __call__(self,identifier):
        if not self._ready or identifier not in self._index:raise ValueError('GG_DAG_ARCHIVE_UNAVAILABLE')
        offset,size,wanted=self._index[identifier]
        current=self.path.lstat()
        if is_link(self.path) or not stat.S_ISREG(current.st_mode) or not os.path.samestat(self.info,current):
            raise ValueError('GG_DAG_ARCHIVE_PAYLOAD_CHANGED')
        with self.path.open('rb') as file:
            if not os.path.samestat(self.info,os.fstat(file.fileno())):raise ValueError('GG_DAG_ARCHIVE_PAYLOAD_CHANGED')
            file.seek(offset);raw=file.read(size)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=wanted:raise ValueError('GG_DAG_ARCHIVE_PAYLOAD_CHANGED')
        return raw


def _active_payloads(reader,pin):
    if _read(reader,8)!=b'GGDAGAR2':raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_MAGIC')
    header=_metadata(_frame(reader,b'H',HEADER_LIMIT))
    if not isinstance(header,dict) or set(header)!={'certificate','schema'} or header['schema']!='gg.dag.public-archive.v2':
        raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_HEADER')
    packet=header['certificate'];tip=certificate_tip(packet,pin)
    result=reader.result;state=result['commitment'];base=result['segment_base']['commitment']
    if packet['state']['dag_segmented']!=state or tip[0]!=result['certificate_height']:
        raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_CONTEXT')
    # The native verifier already replayed ALL signed originals. This caller
    # pass hashes every byte again while streaming closed segment frames past.
    for _ in range(int(state['epoch'])-1):
        remaining=_frame_size(reader,b'S',SEGMENT_LIMIT)
        while remaining:
            size=min(remaining,256*1024);_read(reader,size);remaining-=size
    previous=base['active']['manifest_hash'];blocks=0;raw_bytes=0
    active_bytes=int(state['raw_bytes'])-int(base['raw_bytes'])
    for checkpoint in range(1,state['active']['checkpoint']+1):
        manifest=_metadata(_frame(reader,b'M',MANIFEST_LIMIT))
        if (not isinstance(manifest,dict) or set(manifest)!={'schema','blocks','checkpoint','genesis_hash','previous','source_hash','time_ns'}
                or manifest['schema']!='gg.dag.execution.manifest.v1' or manifest['checkpoint']!=checkpoint
                or manifest['previous']!=previous or manifest['genesis_hash']!=pin['genesis_hash'] or manifest['source_hash']!=state['source_hash']
                or not isinstance(manifest['blocks'],list) or not 1<=len(manifest['blocks'])<=128
                or len(manifest['blocks'])>state['active']['blocks']-blocks):raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_MANIFEST')
        previous=digest(manifest,b'GG-DAG-CHECKPOINT-MANIFEST-v1\0');batch_bytes=0
        for wire_hash in manifest['blocks']:
            limit=min(rules.MAX_BLOCK_WIRE_BYTES-batch_bytes,active_bytes-raw_bytes)
            size=_frame_size(reader,b'R',limit);offset=reader.position;raw=_read(reader,size)
            if hashlib.sha256(raw).hexdigest()!=wire_hash:raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_PAYLOAD')
            blocks+=1;raw_bytes+=size;batch_bytes+=size
            yield packet,raw,offset,size,wire_hash
    footer=_metadata(_frame(reader,b'F',1024))
    if (not isinstance(footer,dict) or footer.get('schema')!='gg.dag.archive.footer.v2'
            or previous!=state['active']['manifest_hash'] or blocks!=state['active']['blocks'] or raw_bytes!=active_bytes):
        raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_FOOTER')
    reader.finish()
    return packet


def restore_engine(path,trust,*,engine_class=ParallelDag,hot_bytes=HOT_PAYLOAD_BYTES,in_memory_bytes=0,**options):
    """Verify/replay before returning a keyless engine, including its real order.

    The default is a bounded, archive-backed read-only view. in_memory_bytes is
    an explicit raw-payload ceiling (at most 16 MiB) for disposable RAM producer
    experiments. It makes no process-crash/durable-resume claim. NodeProfile
    activation must separately import and bind its own protected journal.
    """
    if type(hot_bytes) is not int or not 0<=hot_bytes<=HOT_PAYLOAD_BYTES:raise ValueError('GG_DAG_ARCHIVE_CACHE_LIMIT')
    if type(in_memory_bytes) is not int or not 0<=in_memory_bytes<=HOT_PAYLOAD_BYTES:raise ValueError('GG_DAG_SEGMENTED_RAM_LIMIT')
    pin=segmented.validate_native_pin(trust);node=None
    try:
        with segmented._open_verified_archive(path,pin,**options) as reader:
            result=reader.result;source=pin['genesis']['dag_segmented'];base=result['segment_base']
            active_bytes=int(result['commitment']['raw_bytes'])-int(base['commitment']['raw_bytes'])
            if in_memory_bytes and active_bytes>in_memory_bytes:raise ValueError('GG_DAG_SEGMENTED_RAM_LIMIT')
            node=engine_class.from_segmented_source(source,pin['genesis_hash']);node._install_segment_base(base)
            payload_reader=_ArchivePayloadReader(reader)
            if in_memory_bytes:
                node.configure_lan_capacity(block_bytes=min(in_memory_bytes,rules.MAX_BLOCK_WIRE_BYTES),session_bytes=in_memory_bytes)
            else:node.configure_payload_archive(payload_reader,hot_bytes=hot_bytes)
            node.begin_history_replay();order=[];stream=_active_payloads(reader,pin);packet=None
            while True:
                try:packet,raw,offset,size,wire_hash=next(stream)
                except StopIteration as end:
                    packet=end.value;break
                admitted=node.admit_relayed(raw,0,check=reader.check);identifier=admitted['hash']
                payload_reader.register(identifier,offset,size,wire_hash)
                row=node._records[identifier];producer=row['producer_index'];index=len(order)+1
                order.append({'hash':identifier,'index':index,'producer_index':producer,'sequence':str(row['producer_sequence']),
                    'transactions':row['transaction_count'],'creator_key':source['genesis']['producers'][producer],
                    'global_index':str(int(base['commitment']['blocks'])+index)})
            node.apply_certified_order(packet['state'],order,source);node.finish_history_replay()
            if node._preview_root!=result['commitment']['active']['account_root']:raise ValueError('GG_DAG_CERTIFIED_EXECUTION_ROOT')
            payload_reader.seal()
            node._segment.update(history_replayed=True,read_only_archive=not bool(in_memory_bytes),certificate=deepcopy(packet))
        return node
    except BaseException:
        if node is not None:node.stop()
        raise
