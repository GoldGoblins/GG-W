"""Bounded authenticated source2 original window, never full ledger replay.

Each displayed body is bound to an actual pinned SDK membership proof and its
creator signature. Wire descriptors/chunks alone authorize no graph publication.
Temporary untrusted bytes are deleted on close, never installed as node history.
"""
import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
import http.client
import json
import re
import tempfile
import threading
import time

from backend import gg_dag_segmented as segmented
from backend.gg_dag_json import preflight_lan_block
from backend.gg_ed25519 import verify_signature
from backend.gg_parallel_dag import pack

MAX_BYTES=32*1024*1024
CHUNK_BYTES=32*1024
WINDOW=128
HASH=re.compile(r'[0-9a-f]{64}')
SIGNATURE=re.compile(r'[0-9a-f]{128}')
SELECTOR=re.compile(r'([0-9a-f]{64})/([1-9][0-9]{0,3})/(0|[1-9][0-9]{0,7})')
FAILURES=(ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException)


def parse_selector(value):
    match=SELECTOR.fullmatch(value) if type(value) is str else None
    if match is None:raise ValueError('GG_PAYLOAD_SELECTOR')
    identifier,index,offset=match.groups();index=int(index);offset=int(offset)
    if index>4095 or offset>=MAX_BYTES or offset%CHUNK_BYTES:raise ValueError('GG_PAYLOAD_SELECTOR')
    return identifier,index,offset


def parse_closed_selector(value,*,payload=False):
    if type(value) is not str or '/' not in value:raise ValueError('GG_PAYLOAD_CLOSED_SELECTOR')
    epoch,rest=value.split('/',1)
    if not re.fullmatch(r'[1-9][0-9]{0,18}',epoch) or int(epoch)>segmented.MAX_COUNTER:raise ValueError('GG_PAYLOAD_CLOSED_SELECTOR')
    if payload:return (epoch,*parse_selector(rest))
    if not re.fullmatch(r'0|[1-9][0-9]{0,3}',rest) or int(rest)>=4095 or int(rest)%32:raise ValueError('GG_PAYLOAD_CLOSED_SELECTOR')
    return epoch,int(rest)


def decode_chunk(value,packet,identifier,index,offset,*,epoch=None):
    expected={'data','genesis_hash','hash','height','index','offset','schema','state_root','total','wire_hash'}
    if epoch is not None:expected.add('epoch')
    if (not isinstance(value,dict) or set(value)!=expected or value['schema']!=('gg.dag.closed-payload-chunk.v1' if epoch is not None else 'gg.dag.payload-chunk.v1')
            or epoch is not None and (type(value['epoch']) is not str or value['epoch']!=epoch)
            or value['genesis_hash']!=packet['genesis_hash'] or value['state_root']!=packet['state']['state_root']
            or type(value['height']) is not int or value['height']!=packet['state']['height']
            or value['hash']!=identifier or type(value['index']) is not int or value['index']!=index
            or type(value['offset']) is not int or value['offset']!=offset
            or type(value['total']) is not int or not 0<value['total']<=MAX_BYTES or offset>=value['total']
            or type(value['wire_hash']) is not str or not HASH.fullmatch(value['wire_hash'])
            or type(value['data']) is not str or len(value['data'])>43692):raise ValueError('GG_PAYLOAD_CHUNK_CONTEXT')
    try:data=base64.b64decode(value['data'],validate=True)
    except ValueError:raise ValueError('GG_PAYLOAD_CHUNK_ENCODING') from None
    if base64.b64encode(data).decode('ascii')!=value['data'] or len(data)!=min(CHUNK_BYTES,value['total']-offset):
        raise ValueError('GG_PAYLOAD_CHUNK_ENCODING')
    return value['total'],value['wire_hash'],data


def authenticate_original(raw,packet,leaf,anchor,*,binary=None,stamp=None):
    """Independent pinned SDK membership and exact original-body authentication.

    This verifies data provenance for display. It does not claim transaction
    execution, balance replay or original availability outside this window.
    """
    if type(raw) is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('GG_PAYLOAD_ORIGINAL_SIZE')
    observation=(segmented.verify_closed_membership if 'dag_segmented_closed_page' in packet else segmented.verify_membership)(packet,anchor,binary=binary,stamp=stamp)
    witnesses=([observation['block']] if observation['block'] is not None else [])
    if observation['order_page'] is not None:witnesses.extend(item['leaf'] for item in observation['order_page']['items'])
    if leaf not in witnesses:raise ValueError('GG_PAYLOAD_MEMBERSHIP_REQUIRED')
    preflight_lan_block(raw)
    def unique(pairs):
        value={}
        for name,item in pairs:
            if name in value:raise ValueError('GG_PAYLOAD_DUPLICATE_KEY')
            value[name]=item
        return value
    try:value=json.loads(raw,object_pairs_hook=unique)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('GG_PAYLOAD_ORIGINAL_ENCODING') from None
    if not isinstance(value,dict) or set(value)!={'body','signature'} or pack(value)!=raw:raise ValueError('GG_PAYLOAD_ORIGINAL_ENCODING')
    body=value['body'];signature=value['signature'];source=anchor['genesis']['dag_segmented']
    fields={'schema','chain_id','producer_index','sequence','rank','parents','precheck_root','transactions','payload_root','created_at_ns'}
    if (not isinstance(body,dict) or set(body)!=fields or body['schema']!='gg.parallel-dag.block.v1'
            or body['chain_id']!=source['genesis']['chain_id']
            or type(body['producer_index']) is not int or body['producer_index']!=leaf['producer_index']
            or type(body['sequence']) is not int or str(body['sequence'])!=leaf['sequence']
            or type(body['rank']) is not int or not 1<=body['rank']<=segmented.MAX_COUNTER
            or type(body['created_at_ns']) is not int or not int(source['started_at_ns'])-10**9<=body['created_at_ns']<=segmented.MAX_COUNTER
            or not isinstance(body['transactions'],list) or len(body['transactions'])!=leaf['transactions']
            or hashlib.sha256(b'GG-DAG-BLOCK-v1\0'+pack(body)).hexdigest()!=leaf['hash']
            or type(signature) is not str or not SIGNATURE.fullmatch(signature)):
        raise ValueError('GG_PAYLOAD_ORIGINAL_CONTEXT')
    parents=body['parents']
    if (not isinstance(parents,list) or not 1<=len(parents)<=7 or len(set(parents))!=len(parents)
            or any(type(parent) is not str or not HASH.fullmatch(parent) or parent==leaf['hash'] for parent in parents)):
        raise ValueError('GG_PAYLOAD_ORIGINAL_PARENTS')
    public=source['genesis']['producers'][leaf['producer_index']]
    if public!=leaf['creator_key']:raise ValueError('GG_PAYLOAD_ORIGINAL_CREATOR')
    verify_signature(bytes.fromhex(public),b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body),bytes.fromhex(signature))
    return {'hash':leaf['hash'],'rank':str(body['rank']),'height':str(body['rank']),
        'parent_hashes':deepcopy(parents),'proposer_index':leaf['producer_index'],'creator_key':public,
        'producer_sequence':leaf['sequence'],'transaction_count':len(body['transactions']),
        'canonical_index':leaf['global_index'],'epoch':observation['epoch'],
        'certificate_height':str(packet['signed_header']['header']['height']),
        'signature_verified':True,'canonical_membership_verified':True,'payload_authenticated':True,
        'state':'SDK_CERTIFIED','verification_scope':'SDK_MEMBERSHIP_AND_CREATOR_SIGNED_BODY_NOT_LOCAL_EXECUTION_REPLAY'}


class SegmentedPayloads:
    def __init__(self,exchange):
        self.exchange=exchange;self.peer=exchange.peer;self.lock=threading.Lock();self.cancel=threading.Event()
        self.rows=OrderedDict();self.partial=None;self.error='';self.phase='IDLE';self.bytes=0;self.turn=0
        self.cold=OrderedDict();self.cold_binding=None;self.cold_epoch=0;self.cold_cursor=None
        self.worker=threading.Thread(target=self._work,name='GG-segmented-original-window',daemon=True)

    def start(self):
        if self.cancel.is_set():raise ValueError('GG_PAYLOAD_RECOVERY_STOPPED')
        if self.worker.ident is None:self.worker.start()

    def request_stop(self):self.cancel.set()

    def _check(self):
        if self.cancel.is_set() or self.exchange.cancel.is_set() or self.peer._cancel.is_set() or self.exchange._fault:
            raise ValueError('GG_PAYLOAD_RECOVERY_STOPPED')
        self.exchange.context.check()

    def _drop(self):
        partial=self.partial
        if partial is None:return
        # Do not claim released disk credit until the owned spool really closed.
        partial['file'].close()
        if not partial['file'].closed:raise ValueError('GG_PAYLOAD_SPOOL_CLOSE_FAILED')
        with self.lock:
            if self.partial is partial:self.partial=None

    def _finish(self,partial):
        self._check();self.phase='VALIDATING';total=partial['total']
        with self.peer.resources.governor().reserve_memory(total*16):
            partial['file'].seek(0);raw=partial['file'].read(total+1)
            if len(raw)!=total or hashlib.sha256(raw).hexdigest()!=partial['wire_hash']:raise ValueError('GG_PAYLOAD_WIRE_DIGEST')
            verifier=self.exchange.verifier
            row=authenticate_original(raw,partial['proof'],partial['leaf'],self.exchange.anchor,binary=verifier.binary,stamp=verifier.stamp)
        self._check()
        self._drop()
        with self.lock:
            self.rows[row['hash']]=row;self.rows.move_to_end(row['hash'])
            self.rows=OrderedDict(sorted(self.rows.items(),key=lambda item:int(item[1]['canonical_index']))[-WINDOW:])
            self.bytes+=total;self.error=''

    def _step(self):
        self._check();view=self.exchange._view
        if view is None:return
        order=view['order'];proofs=dict(view.get('payload_proofs',{}))
        info=getattr(self.exchange,'_certificate_info',None);query_packet=info[0] if info is not None else view['certificate']
        current=query_packet['state']['dag_segmented']
        # Cold metadata work has its own bound and cannot prevent a known
        # active original from progressing when another source is unavailable.
        if 'closed_root' in current and len(order)<WINDOW:
            try:self._fill_cold(query_packet,len(order))
            except FAILURES as error:
                code=str(error);self.error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_PAYLOAD_COLD_SOURCE_UNAVAILABLE'
                self._check()
        combined={leaf['hash']:leaf for leaf in order}
        for identifier,reference in tuple(self.cold.items()):
            combined.setdefault(identifier,reference['leaf']);proofs.setdefault(identifier,reference['proof'])
        order=sorted(combined.values(),key=lambda leaf:int(leaf['global_index']))[-WINDOW:]
        leaves={leaf['hash']:leaf for leaf in order}
        if self.partial is not None:
            identifier=self.partial['leaf']['hash'];candidate=leaves.get(identifier)
            if candidate==self.partial['leaf'] and identifier in proofs:
                # Bytes remain untrusted. A fresh independently verified proof
                # for the same exact leaf can authorize continued reads. Do not
                # rewrite any proof's original certificate or height.
                self.partial['proof']=deepcopy(proofs[identifier])
        partial=self.partial
        if partial is None:
            leaf=next((leaf for leaf in order if leaf['hash'] not in self.rows and leaf['hash'] in proofs),None)
            if leaf is None:return
            proof=deepcopy(proofs[leaf['hash']])
        else:leaf=partial['leaf'];proof=partial['proof']
        if partial is not None and partial['offset']==partial['total']:
            self._finish(partial);return
        owners=sorted({row['body']['owner_peer_key'] for row in self.exchange.anchor['genesis']['membership']['validators']})
        if not owners:return
        owner=owners[self.turn%len(owners)];self.turn+=1
        selected_epoch=(proof['dag_segmented_closed_page']['cut']['before']['epoch'] if 'dag_segmented_closed_page' in proof else proof['state']['dag_segmented']['epoch'])
        if int(current['epoch'])<int(selected_epoch):raise ValueError('GG_PAYLOAD_CERTIFICATE_REWIND')
        closed=int(selected_epoch)<int(current['epoch'])
        deadline=time.monotonic()+8;self.phase='DOWNLOADING'
        while time.monotonic()<deadline:
            self._check();self.peer._resource_check(deadline,check=self._check)
            offset=partial['offset'] if partial is not None else 0
            selector=leaf['hash']+'/'+str(leaf['index'])+'/'+str(offset)
            if closed:selector=selected_epoch+'/'+selector
            value=self.exchange._fetch(owner,self.exchange._request('closed-payload' if closed else 'payload',int(query_packet['signed_header']['header']['height']),selector),deadline)
            total,wire_hash,data=decode_chunk(value,query_packet,leaf['hash'],leaf['index'],offset,epoch=selected_epoch if closed else None)
            # Source2 originals use the consensus 32 MiB bound checked above.
            # The peer's legacy whole-record limit is not the bound of this
            # independently fragmented, governed original-recovery protocol.
            if partial is None:
                partial={'file':tempfile.TemporaryFile(mode='w+b'),'total':total,'wire_hash':wire_hash,'offset':0,
                    'leaf':deepcopy(leaf),'proof':proof}
                with self.lock:self.partial=partial
            elif partial['total']!=total or partial['wire_hash']!=wire_hash:raise ValueError('GG_PAYLOAD_CHUNK_CHANGED')
            try:written=partial['file'].write(data)
            except OSError:
                self._drop();raise ValueError('GG_PAYLOAD_SPOOL_WRITE') from None
            if written!=len(data):
                self._drop();raise ValueError('GG_PAYLOAD_SPOOL_WRITE')
            with self.lock:partial['offset']+=len(data)
            if partial['offset']==total:self._finish(partial);return

    def _fill_cold(self,packet,active_count):
        commitment=packet['state']['dag_segmented'];binding=commitment['closed_root']
        floor=max(1,int(commitment['blocks'])-WINDOW+1)
        self.cold=OrderedDict((identifier,reference) for identifier,reference in self.cold.items() if int(reference['leaf']['global_index'])>=floor)
        if self.cold_binding!=binding:
            self.cold_binding=binding;self.cold_epoch=int(commitment['epoch'])-1;self.cold_cursor=None
        if self.cold_epoch<1 or active_count+len(self.cold)>=WINDOW:return
        owners=sorted({row['body']['owner_peer_key'] for row in self.exchange.anchor['genesis']['membership']['validators']})
        if not owners:return
        owner=owners[self.turn%len(owners)];self.turn+=1
        cursor=0 if self.cold_cursor is None else self.cold_cursor
        selector=str(self.cold_epoch)+'/'+str(cursor)
        request=self.exchange._request('closed',int(packet['signed_header']['header']['height']),selector)
        proven=self.exchange._fetch(owner,request,time.monotonic()+8)
        self.exchange._check_proven_base(proven,packet,'dag_segmented_closed_page')
        page=proven['dag_segmented_closed_page'];before=page['cut']['before']
        if before['epoch']!=str(self.cold_epoch) or page['start']!=cursor:raise ValueError('GG_PAYLOAD_COLD_CURSOR')
        self.exchange._cache(self.exchange._key(request),{'state':'READY','packet':proven})
        if self.cold_cursor is None and before['active']['blocks']>32:
            self.cold_cursor=((before['active']['blocks']-1)//32)*32;return
        for item in page['items']:
            leaf=item['leaf'];self.cold[leaf['hash']]={'leaf':deepcopy(leaf),'proof':proven}
        ordered=sorted(self.cold.items(),key=lambda item:int(item[1]['leaf']['global_index']))[-WINDOW:]
        self.cold=OrderedDict(ordered)
        if cursor==0:self.cold_epoch-=1;self.cold_cursor=None
        else:self.cold_cursor=cursor-32

    def _work(self):
        try:
            while not self.cancel.is_set() and not self.exchange.cancel.is_set() and not self.peer._cancel.is_set():
                if self.peer._resources_paused():self.cancel.wait(.2);continue
                try:self._step()
                except FAILURES as error:
                    code=str(error);self.error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_PAYLOAD_SOURCE_UNAVAILABLE'
                    if code.startswith(('GG_PAYLOAD_CHUNK_','GG_PAYLOAD_WIRE_','GG_PAYLOAD_ORIGINAL_','GG_DAG_SEGMENTED_OBSERVATION_','GG_PAYLOAD_SPOOL_WRITE')):
                        self._drop()
                    elif self.partial is not None and self.partial['offset']==self.partial['total'] and not code.startswith('GG_DAG_RESOURCE_'):
                        self._drop()
                self.phase='IDLE';self.cancel.wait(.2)
        except Exception:
            self.error='GG_PAYLOAD_WORKER_FAILED';self.cancel.set()
        finally:
            try:self._drop()
            except OSError:self.error='GG_PAYLOAD_SPOOL_CLOSE_FAILED'

    def snapshot(self):
        with self.lock:
            rows=deepcopy(list(self.rows.values()));partial=self.partial
            result={'enabled':True,'state':'ERROR' if self.error=='GG_PAYLOAD_WORKER_FAILED' else 'STOPPED' if self.cancel.is_set() else self.phase,'verified_blocks':len(rows),
                'verified_original_bytes':self.bytes,'partial_bytes':partial['offset'] if partial else 0,
                'reserved_disk_bytes':partial['total'] if partial else 0,'last_error':self.error,
                'verification_scope':'BOUNDED_AUTHENTICATED_ORIGINAL_WINDOW_NOT_FULL_HISTORY_REPLAY'}
        if self.exchange._fault or self.peer._profile._failed:return {**result,'state':'FAULT','blocks':[],'edges':[]}
        rows.sort(key=lambda row:int(row['canonical_index']))
        ranks={rank:index for index,rank in enumerate(sorted({int(row['rank']) for row in rows}))}
        identifiers={row['hash'] for row in rows}
        edges=[]
        for index,row in enumerate(rows):
            row['layout_rank']=ranks[int(row['rank'])];row['admission_index']=index
            row['missing_parent_hashes']=[parent for parent in row['parent_hashes'] if parent not in identifiers]
            edges.extend({'from':parent,'to':row['hash']} for parent in row['parent_hashes'] if parent in identifiers)
        return {**result,'blocks':rows,'edges':edges}

    def close(self):
        self.request_stop()
        if self.worker.ident is not None and self.worker is not threading.current_thread():self.worker.join(10)
        if self.worker.is_alive() and self.worker is not threading.current_thread():raise ValueError('GG_PAYLOAD_WORKER_STOP_TIMEOUT')
        self._drop()
