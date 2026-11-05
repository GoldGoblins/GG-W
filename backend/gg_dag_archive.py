"""Pinned original-signed DAG archive import into an offline replica journal.

The installed native verifier fully replays the archive first. A second bounded
stream is consumed inside one journal transaction; its complete file hash must
match that verified result before commit. No native transfer or validator state
is restored. Importing this module starts no process and opens no profile.
"""
from __future__ import annotations

from contextlib import closing,nullcontext
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

from backend import gg_consensus as native
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_dag_execution_policy import MAX_HISTORY_BLOCKS, MAX_HISTORY_RAW_BYTES, MAX_BLOCK_WIRE_BYTES
from backend.gg_node_store import NodeProfile, pack, unpack
from backend.gg_testnet_process import contain
from backend.gg_native_start import native_pipe_creation_flags
from backend import gg_native_pipe_lifecycle as native_pipes
from backend.platform_files import is_link

MAGIC=b'GGDAGAR1'
HEADER_LIMIT=256*1024
MANIFEST_LIMIT=16*1024
FOOTER_LIMIT=1024
MAX_ARCHIVE_BYTES=MAX_HISTORY_RAW_BYTES+(MAX_HISTORY_BLOCKS+1)*(MANIFEST_LIMIT+5)+HEADER_LIMIT+FOOTER_LIMIT+5*MAX_HISTORY_BLOCKS+32
SCOPE='FULL_ORIGINAL_SIGNED_DAG_REPLAY_AND_PINNED_SDK_CERTIFICATE_NOT_NATIVE_TRANSFER_HISTORY_REPLAY'


def _metadata(raw):
    # The original SDK signed-header uses its SDK field order. Native has
    # already checked the canonical archive encoding; do not reinterpret it as
    # Python's different sorted-key encoding. Duplicate names still fail here.
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('GG_DAG_ARCHIVE_JSON')
            result[key]=value
        return result
    try:return json.loads(raw,object_pairs_hook=unique)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('GG_DAG_ARCHIVE_JSON') from None


def _native_verify(path,work,anchor,floor,*,tools,check,timeout,format_version=1,owner=None,close_on_pending=()):
    if type(timeout) not in (int,float) or not 1<=timeout<=14400:
        raise ValueError('GG_DAG_ARCHIVE_TIMEOUT')
    if type(format_version) is not int or format_version not in (1,2):raise ValueError('GG_DAG_ARCHIVE_CONTEXT')
    if format_version==2:
        from backend.gg_dag_segmented import ARCHIVE_SCOPE
        scope=ARCHIVE_SCOPE
    else:scope=SCOPE
    directory=native.TOOLS if tools is None else Path(tools)
    binary=native._installed_binary(directory)
    native._validate_binary_at(directory,binary)
    request={'archive_path':str(path),'work_root':str(work),**anchor}
    if floor is not None:
        request.update(minimum_certificate_height=floor[0],minimum_certificate_block=floor[1])
    raw=pack(request)
    if len(raw)>512*1024:raise ValueError('GG_DAG_ARCHIVE_CONTEXT')
    flags=native_pipe_creation_flags()
    environment=native._environment()
    environment.update(GOMAXPROCS='2',GOMEMLIMIT='384MiB')
    process=None;lease=None;deadline=time.monotonic()+timeout
    with native_pipes.DAG_VERIFY.operation((owner,),close_on_pending=close_on_pending) as retirement:
        try:
            check()
            process=subprocess.Popen([str(binary),'archive-verify'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,env=environment,creationflags=flags)
            retirement.attach(process)
            lease=contain(process);retirement.lease=lease
            pending=raw
            while True:
                check()
                if time.monotonic()>=deadline:raise ValueError('GG_DAG_ARCHIVE_TIMEOUT')
                try:
                    output,_=process.communicate(input=pending,timeout=min(.25,max(.001,deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:pending=None
            if process.returncode or len(output)>(16384 if format_version==2 else 8192):raise ValueError('GG_DAG_ARCHIVE_VERIFY_FAILED')
            result=unpack(output.strip())
            if (not isinstance(result,dict) or result.get('schema')!='gg.dag.archive.result.v'+str(format_version) or result.get('verified') is not True
                    or result.get('verification_scope')!=scope or result.get('genesis_hash')!=anchor['genesis_hash']
                    or result.get('snapshot_trust_used') is not False or result.get('signing_keys_exported') is not False):
                raise ValueError('GG_DAG_ARCHIVE_VERIFY_FAILED')
            return result
        except OSError:
            raise ValueError('GG_DAG_ARCHIVE_VERIFY_UNAVAILABLE') from None


class PublicDagArchive:
    """Single-use, bounded second pass; its caller must consume through EOF."""
    def __init__(self,file,anchor,verified,check):
        self._file=file;self._check=check;self._digest=hashlib.sha256();self._bytes=0
        self.verified=verified;self.complete=False;self._iterated=False
        if self._read(8)!=MAGIC:raise ValueError('GG_DAG_ARCHIVE_MAGIC')
        header=_metadata(self._frame(b'H',HEADER_LIMIT))
        if not isinstance(header,dict) or set(header)!={'schema','certificate'} or header['schema']!='gg.dag.public-archive.v1':
            raise ValueError('GG_DAG_ARCHIVE_HEADER')
        self.packet=header['certificate'];tip=certificate_tip(self.packet,anchor)
        commitment=self.packet['state'].get('dag')
        if (not isinstance(commitment,dict) or type(commitment.get('checkpoint')) is not int
                or not 0<=commitment['checkpoint']<=MAX_HISTORY_BLOCKS
                or type(commitment.get('blocks')) is not int or not 0<=commitment['blocks']<=MAX_HISTORY_BLOCKS
                or tip[0]!=verified.get('certificate_height')):
            raise ValueError('GG_DAG_ARCHIVE_CONTEXT')

    def _read(self,size):
        self._check()
        if size<0 or size>MAX_BLOCK_WIRE_BYTES or self._bytes+size>MAX_ARCHIVE_BYTES:
            raise ValueError('GG_DAG_ARCHIVE_SIZE')
        raw=self._file.read(size)
        if len(raw)!=size:raise ValueError('GG_DAG_ARCHIVE_TRUNCATED')
        self._digest.update(raw);self._bytes+=size
        return raw

    def _frame(self,kind,limit):
        return self._read(self._frame_size(kind,limit))

    def _frame_size(self,kind,limit):
        prefix=self._read(5);size=int.from_bytes(prefix[1:],'big')
        if prefix[:1]!=kind or not 0<size<=limit:raise ValueError('GG_DAG_ARCHIVE_FRAME')
        return size

    def __iter__(self):
        return self.payloads(lambda size:nullcontext())

    def payloads(self,reserve):
        if self._iterated:raise ValueError('GG_DAG_ARCHIVE_ALREADY_CONSUMED')
        self._iterated=True;blocks=raw_bytes=0
        for checkpoint in range(1,self.packet['state']['dag']['checkpoint']+1):
            manifest=unpack(self._frame(b'M',MANIFEST_LIMIT))
            if (not isinstance(manifest,dict) or manifest.get('checkpoint')!=checkpoint
                    or not isinstance(manifest.get('blocks'),list) or not 1<=len(manifest['blocks'])<=128):
                raise ValueError('GG_DAG_ARCHIVE_MANIFEST')
            for wanted in manifest['blocks']:
                size=self._frame_size(b'R',MAX_BLOCK_WIRE_BYTES)
                with reserve(size):
                    raw=self._read(size)
                    if hashlib.sha256(raw).hexdigest()!=wanted:raise ValueError('GG_DAG_ARCHIVE_PAYLOAD')
                    blocks+=1;raw_bytes+=len(raw)
                    if blocks>MAX_HISTORY_BLOCKS or raw_bytes>MAX_HISTORY_RAW_BYTES:raise ValueError('GG_DAG_ARCHIVE_SIZE')
                    yield raw
        content=self._digest.hexdigest()
        footer=unpack(self._frame(b'F',FOOTER_LIMIT))
        if (footer!={'schema':'gg.dag.archive.footer.v1','blocks':blocks,
                    'checkpoints':self.packet['state']['dag']['checkpoint'],'raw_bytes':raw_bytes,'content_sha256':content}
                or self._file.read(1) or self._digest.hexdigest()!=self.verified.get('archive_sha256')
                or content!=self.verified.get('content_sha256') or blocks!=self.verified.get('blocks_replayed')
                or raw_bytes!=self.verified.get('raw_payload_bytes')):
            raise ValueError('GG_DAG_ARCHIVE_COMPLETE_HASH')
        self._check();self.complete=True


def import_profile_archive(profile,path,*,tools=None,check=None,timeout=1800):
    """Import only a stopped existing replica; profile lease excludes live users."""
    from backend.gg_consensus_membership import anchor_from_bundle
    if not isinstance(path,(str,os.PathLike)):raise ValueError('GG_DAG_ARCHIVE_FILE')
    if check is not None and not callable(check):raise ValueError('GG_DAG_ARCHIVE_CHECK')
    if type(timeout) not in (int,float) or not 1<=timeout<=14400:raise ValueError('GG_DAG_ARCHIVE_TIMEOUT')
    candidate=Path(path).expanduser()
    if not candidate.is_absolute():raise ValueError('GG_DAG_ARCHIVE_ABSOLUTE_PATH_REQUIRED')
    check=check if check is not None else (lambda:None)
    native_pipes.DAG_VERIFY.retire()
    owned=NodeProfile.open(profile);transferred=False
    try:
        owned._require_archive_import()
        anchor=anchor_from_bundle(owned.session(),owned.descriptor()['trusted_coordinator'])
        previous=owned.consensus_observation()
        floor=owned._consensus_tip(previous) if previous is not None else None
        candidate=candidate.parent.resolve(strict=True)/candidate.name
        info=candidate.lstat()
        if is_link(candidate) or not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_ARCHIVE_BYTES:
            raise ValueError('GG_DAG_ARCHIVE_FILE')
        with candidate.open('rb') as file:
            if not os.path.samestat(info,os.fstat(file.fileno())):raise ValueError('GG_DAG_ARCHIVE_FILE_CHANGED')
            # Native owns one named, leased and bounded scratch namespace below
            # this already exclusively leased profile. A crash cannot accumulate
            # a fresh random work directory on every retry.
            verified=_native_verify(candidate,owned.root,anchor,floor,tools=tools,check=check,timeout=timeout,owner=owned,close_on_pending=(owned,))
            archive=PublicDagArchive(file,anchor,verified,check)
            result=owned._import_dag_archive(archive,check)
        return result
    except native_pipes.NativePipeStopPending as failure:
        transferred=failure.transferred(owned)
        raise
    finally:
        if not transferred:owned.close()
