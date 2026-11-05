"""Durable public payment originals accepted by an explicitly enabled producer.

No account key is imported. Admission is not execution; even a terminal
account nonce does not attribute a particular payment. Protected creator
cores and the native selected-original journal remain the execution boundary.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import secrets
import stat
import threading
import time
import re

from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_node_store import NodeProfile,pack,unpack,_private_path
from backend.gg_dag_checkpoint import certificate_tip
from backend.platform_files import secure_open,set_private_mode,is_link,sync_directory

DOMAIN=b'GG-PROTOCOL-INBOX-ADMISSION-v1\0'
MAX_ACTIVE=4
MAX_BYTES=128*1024*1024
MAX_TERMINAL=32
MAX_META=512*1024
FIELDS={'schema','genesis_hash','owner_key','producer_key','sender','document_hash','document_bytes','first_nonce','end_nonce','received_at_ns','terminal_proof','window','paused_nonce'}


def document_header(raw,trust):
    """Review public document shape without claiming any signature is valid."""
    if type(raw) is not bytes or not 0<len(raw)<=wire.MAX_RAW:raise ValueError('GG_PROTOCOL_INBOX_DOCUMENT_LIMIT')
    value=unpack(raw)
    if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','payments'} or value['schema']!=wire.PAYMENT_DOCUMENT
            or value['genesis_hash']!=trust['genesis_hash'] or pack(value)!=raw or not isinstance(value['payments'],list)
            or not 1<=len(value['payments'])<=wire.MAX_PAYMENTS):raise ValueError('GG_PROTOCOL_INBOX_DOCUMENT')
    rows=value['payments']
    try:
        sender=financial.account_address(rows[0]['body']['sender']);first=wire.counter(rows[0]['body']['nonce'],maximum=2**64-2)
        for index,row in enumerate(rows):
            if row['body']['sender']!=sender or wire.counter(row['body']['nonce'],maximum=2**64-2)!=first+index:raise ValueError()
    except (ValueError,KeyError,TypeError):raise ValueError('GG_PROTOCOL_INBOX_SINGLE_ACCOUNT_NONCES') from None
    return {'schema':'gg.protocol.relay-document-header.v1','genesis_hash':trust['genesis_hash'],'document_hash':hashlib.sha256(raw).hexdigest(),
            'document_bytes':len(raw),'sender':sender,'first_nonce':str(first),'end_nonce':str(first+len(rows))}


def validate_header(value,trust):
    fields={'schema','genesis_hash','document_hash','document_bytes','sender','first_nonce','end_nonce'}
    if (not isinstance(value,dict) or set(value)!=fields or value['schema']!='gg.protocol.relay-document-header.v1'
            or value['genesis_hash']!=trust['genesis_hash'] or type(value['document_bytes']) is not int or not 0<value['document_bytes']<=wire.MAX_RAW):raise ValueError('GG_PROTOCOL_INBOX_HEADER')
    protocol._hash(value['document_hash']);financial.account_address(value['sender'])
    first=wire.counter(value['first_nonce'],maximum=2**64-2);end=wire.counter(value['end_nonce'],maximum=2**64-1)
    if not first<end<=first+wire.MAX_PAYMENTS:raise ValueError('GG_PROTOCOL_INBOX_HEADER')
    return deepcopy(value)


def admission_job(header,packet,trust,worker_key,receiver_key,*,binary=None,stamp=None):
    """Per-byte local relay work, earning no monetary/network work credit."""
    header=validate_header(header,trust);financial.account_address(worker_key);financial.account_address(receiver_key)
    protocol.verify_selected(packet,trust,binary=binary,stamp=stamp)
    state=packet['state']['protocol'];height=int(state['work_anchor_height']);policy=trust['genesis']['protocol']
    # This is an admission budget, separate from rewarded consensus work:
    # making a larger rejected document must not cost the same as an empty job.
    units=(header['document_bytes']+4095)//4096
    target=max(1,int(policy['registration_work_target'],16)//units)
    nonce=hashlib.sha256(b'GG-PROTOCOL-RELAY-ADMISSION-WORK-v1\0'+pack({'header':header,'receiver_key':receiver_key,'worker_key':worker_key})).hexdigest()
    return {'epoch':state['economics']['next_epoch'],'expires_height':str(height+int(policy['max_work_heights'])),'genesis_hash':trust['genesis_hash'],
            'job_nonce':nonce,'network_target':format(target,'064x'),'payload_root':header['document_hash'],'reward_account':header['sender'],
            'schema':'gg.financial.mining-job.v1','share_target':format(target,'064x'),'state_height':str(height),
            'state_root':state['work_anchor_root'],'worker_key':worker_key}


class InboxEntry:
    def __init__(self,book,body,raw):
        self.book=book;self._body=deepcopy(body);self.raw=raw;self.name='remote_'+body['document_hash'][:24]
        self._lock=threading.RLock();self._account=None;self._tip=None;self._packet=None;self._payments=None

    def anchor(self):return deepcopy(self.book.anchor)
    def public_address(self):return self._body['sender']
    @staticmethod
    def _nonce(result):return int(result['financial_account']['nonce']) if result['financial_account_exists'] else 0

    def remember_account(self,packet):
        result=financial.verify_account(packet,self.book.anchor,self.public_address(),binary=self.book.binary,stamp=self.book.stamp)
        tip=certificate_tip({key:packet[key] for key in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in packet else set())},self.book.anchor)
        if self._tip is not None and (tip[0]<self._tip[0] or tip[0]==self._tip[0] and tip!=self._tip):raise ValueError('GG_PROTOCOL_INBOX_CERTIFICATE_REWIND_OR_CONFLICT')
        self._account=result;self._tip=tip;self._packet=deepcopy(packet)

    def pending(self,packet):
        with self._lock:
            self.remember_account(packet);nonce=self._nonce(self._account)
            if nonce>=int(self._body['end_nonce']):self.book.mark_done(self,packet);return None
            if nonce<int(self._body['first_nonce']):return None
            if self._payments is None:self._payments=wire.decode_payment_document(self.raw,self.book.anchor,authenticated=True)
            offset=nonce-int(self._body['first_nonce']);rows=self._payments.rows(offset)
            return pack({'schema':wire.PAYMENT_DOCUMENT,'genesis_hash':self.book.anchor['genesis_hash'],'payments':rows})

    def snapshot(self):
        nonce=self._nonce(self._account) if self._account is not None else None
        return {'profile':self.name,'role':'relayed_public_originals','public_key':self.public_address(),'next_signing_nonce':self._body['end_nonce'],
                'state':'NONCES_CONSUMED_OUTCOME_UNRESOLVED' if nonce is not None and nonce>=int(self._body['end_nonce']) else 'WAITING_FOR_EARLIER_NONCE' if nonce is not None and nonce<int(self._body['first_nonce']) else 'DURABLE_ORIGINALS',
                'certificate_height':self._tip[0] if self._tip else None,'receiver_paused_nonce':self._body['paused_nonce'],
                'pause_is_local_queue_hint':True,'payments_executed_asserted':False}

    def remember_window(self,window):
        with self.book.owner._lock,self.book._lock:
            body={**deepcopy(self._body),'window':deepcopy(window)}
            self.book._check_window(body);self.book._save(body);self._body=body

    def pause(self,nonce):
        with self.book.owner._lock,self.book._lock:
            value=None if nonce is None else str(nonce)
            if value is not None and not int(self._body['first_nonce'])<=wire.counter(value,maximum=2**64-2)<int(self._body['end_nonce']):raise ValueError('GG_PROTOCOL_INBOX_PAUSE_NONCE')
            body={**deepcopy(self._body),'paused_nonce':value};self.book._save(body);self._body=body


class ProtocolInbox:
    def __init__(self,owner,trust,*,binary=None,stamp=None):
        if type(owner) is not NodeProfile or owner._closed or owner._failed or owner._lease is None:raise ValueError('GG_PROTOCOL_INBOX_OWNED_PROFILE_REQUIRED')
        self.owner=owner;self.anchor=protocol.validate_pin(trust);self.binary=binary;self.stamp=stamp;self._lock=threading.RLock();self.entries={}
        self.root=owner.root/'protocol-inbox';self._check_path();self.root.mkdir(mode=0o700,exist_ok=True);set_private_mode(self.root,0o700);_private_path(self.root,0o700)
        identity,_=owner.signers();self.owner_key=identity.pubkey().hex();self._load()

    def _check_path(self):
        if any(is_link(path) for path in (self.root,*self.root.parents)) or not self.root.absolute().is_relative_to(self.owner.root.absolute()):raise ValueError('GG_PROTOCOL_INBOX_PATH')

    def _path(self,identifier,suffix):
        protocol._hash(identifier);self._check_path()
        return self.root/(identifier+suffix)

    def _read(self,path,maximum):
        self._check_path();fd=secure_open(path,os.O_RDONLY,0o600)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=maximum:raise ValueError('GG_PROTOCOL_INBOX_FILE')
            raw=stream.read(maximum+1)
        if len(raw)>maximum:raise ValueError('GG_PROTOCOL_INBOX_FILE')
        return raw

    def _write(self,path,raw):
        self._check_path();temporary=self.root/('.pending-'+secrets.token_hex(16));fd=secure_open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            set_private_mode(temporary,0o600);os.replace(temporary,path);sync_directory(self.root)
        finally:
            # A failed local write must not accumulate an unbounded staging
            # cache. Only this exact randomly named owned temporary is removed.
            if temporary.exists():self._unlink(temporary)

    def _save(self,body):
        identity,_=self.owner.signers();record={'body':body,'signature':identity.sign_message(DOMAIN+pack(body)).hex()}
        raw=pack(record)
        if len(raw)>MAX_META:raise ValueError('GG_PROTOCOL_INBOX_META_LIMIT')
        self._write(self._path(body['document_hash'],'.admission.json'),raw)

    def _validate(self,record,identifier):
        if not isinstance(record,dict) or set(record)!={'body','signature'}:raise ValueError('GG_PROTOCOL_INBOX_ADMISSION')
        body=record['body']
        if (not isinstance(body,dict) or set(body)!=FIELDS or body['schema']!='gg.protocol.inbox-admission.v1'
                or body['genesis_hash']!=self.anchor['genesis_hash'] or body['owner_key']!=self.owner_key or body['document_hash']!=identifier
                or body['producer_key'] not in self.owner.descriptor()['public_keys'][1:]):raise ValueError('GG_PROTOCOL_INBOX_ADMISSION')
        header={name:body[name] for name in ('genesis_hash','document_hash','document_bytes','sender','first_nonce','end_nonce')}
        validate_header({'schema':'gg.protocol.relay-document-header.v1',**header},self.anchor)
        wire.counter(body['received_at_ns'],positive=True,maximum=2**64-1)
        protocol._signature(self.owner_key,record['signature'],DOMAIN+pack(body))
        self._check_window(body)
        if body['paused_nonce'] is not None and not int(body['first_nonce'])<=wire.counter(body['paused_nonce'],maximum=2**64-2)<int(body['end_nonce']):raise ValueError('GG_PROTOCOL_INBOX_PAUSE_NONCE')
        if body['terminal_proof'] is not None:
            result=financial.verify_account(body['terminal_proof'],self.anchor,body['sender'],binary=self.binary,stamp=self.stamp)
            if InboxEntry._nonce(result)<int(body['end_nonce']):raise ValueError('GG_PROTOCOL_INBOX_TERMINAL_PROOF')
        return body

    def _check_window(self,body):
        window=body['window']
        if window is None:return
        if (not isinstance(window,dict) or set(window)!={'floor_sequence','first_nonce','count','size'}
                or type(window['count']) is not int or not 1<=window['count']<=8
                or type(window['size']) is not int or not 1<=window['size']<=5000):raise ValueError('GG_PROTOCOL_INBOX_SIGNING_WINDOW')
        wire.counter(window['floor_sequence']);first=wire.counter(window['first_nonce'],maximum=2**64-2)
        if not int(body['first_nonce'])<=first<int(body['end_nonce']):raise ValueError('GG_PROTOCOL_INBOX_SIGNING_WINDOW')

    def _load(self):
        with self.owner._lock,self._lock:
            # A killed writer can leave a partial staging file. Such a file
            # was never acknowledged and carries no account/creator authority.
            # Reclaim only our exact staging names in this dedicated directory.
            for path in self.root.glob('.pending-*'):
                if not re.fullmatch(r'\.pending-[0-9a-f]{32}',path.name):raise ValueError('GG_PROTOCOL_INBOX_STAGING_FILE')
                self._check_path()
                fd=secure_open(path,os.O_RDONLY,0o600)
                with os.fdopen(fd,'rb') as stream:
                    info=os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<=info.st_size<=wire.MAX_RAW:raise ValueError('GG_PROTOCOL_INBOX_STAGING_FILE')
                self._unlink(path)
            total=0;count=0
            for path in self.root.glob('*.admission.json'):
                count+=1
                if count>MAX_ACTIVE+MAX_TERMINAL:raise ValueError('GG_PROTOCOL_INBOX_RESOURCE_LIMIT')
                identifier=path.name.removesuffix('.admission.json');body=self._validate(unpack(self._read(path,MAX_META)),identifier)
                if body['terminal_proof'] is not None:
                    self._unlink(self._path(identifier,'.document'));continue
                raw=self._read(self._path(identifier,'.document'),wire.MAX_RAW);total+=len(raw)
                if hashlib.sha256(raw).hexdigest()!=identifier or len(raw)!=body['document_bytes'] or total>MAX_BYTES or len(self.entries)>=MAX_ACTIVE:raise ValueError('GG_PROTOCOL_INBOX_DOCUMENT')
                header=document_header(raw,self.anchor)
                if any(header[name]!=body[name] for name in header if name!='schema'):raise ValueError('GG_PROTOCOL_INBOX_ADMISSION')
                values=wire.decode_payment_document(raw,self.anchor,authenticated=True)
                entry=InboxEntry(self,body,raw);entry._payments=values;self.entries[identifier]=entry
            # Unacknowledged crash leftovers belong only to this dedicated
            # public cache. Validate their exact content-addressed document
            # before reclaiming a single file; never recurse outside the root.
            for path in self.root.glob('*.document'):
                identifier=path.name.removesuffix('.document');protocol._hash(identifier)
                if self._path(identifier,'.admission.json').exists():continue
                raw=self._read(path,wire.MAX_RAW);header=document_header(raw,self.anchor)
                if header['document_hash']!=identifier:raise ValueError('GG_PROTOCOL_INBOX_DOCUMENT')
                wire.decode_payment_document(raw,self.anchor,authenticated=True);self._unlink(path)

    def accept(self,raw,producer_key):
        with self.owner._lock,self._lock:
            header=document_header(raw,self.anchor);identifier=header['document_hash']
            if producer_key not in self.owner.descriptor()['public_keys'][1:]:raise ValueError('GG_PROTOCOL_INBOX_PRODUCER_OWNER')
            if identifier in self.entries:return self.entries[identifier]
            if len(self.entries)>=MAX_ACTIVE or sum(row._body['document_bytes'] for row in self.entries.values())+len(raw)>MAX_BYTES:raise ValueError('GG_PROTOCOL_INBOX_RESOURCE_LIMIT')
            self._prune_terminal()
            values=wire.decode_payment_document(raw,self.anchor,authenticated=True)
            body={name:value for name,value in header.items() if name!='schema'}
            body.update(schema='gg.protocol.inbox-admission.v1',owner_key=self.owner_key,producer_key=producer_key,received_at_ns=str(time.time_ns()),terminal_proof=None,window=None,paused_nonce=None)
            self._write(self._path(identifier,'.document'),raw);self._save(body)
            entry=InboxEntry(self,body,raw);entry._payments=values;self.entries[identifier]=entry;return entry

    def _unlink(self,path):
        self._check_path()
        if path.parent.resolve()!=self.root.resolve() or is_link(path):raise ValueError('GG_PROTOCOL_INBOX_PATH')
        if path.exists():path.unlink();sync_directory(self.root)

    def _prune_terminal(self):
        completed=[]
        for path in self.root.glob('*.admission.json'):
            identifier=path.name.removesuffix('.admission.json');body=self._validate(unpack(self._read(path,MAX_META)),identifier)
            if body['terminal_proof'] is not None:completed.append((int(body['received_at_ns']),identifier))
        completed.sort()
        while len(completed)>=MAX_TERMINAL:
            _,identifier=completed.pop(0)
            self._unlink(self._path(identifier,'.document'));self._unlink(self._path(identifier,'.admission.json'))

    def mark_done(self,entry,packet):
        with self.owner._lock,self._lock:
            result=financial.verify_account(packet,self.anchor,entry.public_address(),binary=self.binary,stamp=self.stamp)
            if InboxEntry._nonce(result)<int(entry._body['end_nonce']):raise ValueError('GG_PROTOCOL_INBOX_TERMINAL_PROOF')
            body={**deepcopy(entry._body),'terminal_proof':deepcopy(packet)};self._save(body);entry._body=body
            self.entries.pop(body['document_hash'],None)
            self._unlink(self._path(body['document_hash'],'.document'))

    def snapshot(self):
        with self._lock:return {'state':'EXPLICIT_RECEIVER_ADMISSION','retained_documents':len(self.entries),
            'retained_bytes':sum(row._body['document_bytes'] for row in self.entries.values()),'limit_bytes':MAX_BYTES,
            'documents':[{'document_hash':identifier,'sender':entry.public_address(),'producer_key':entry._body['producer_key'],**entry.snapshot()} for identifier,entry in self.entries.items()],
            'admission_is_execution':False,'nonce_consumption_is_payment_receipt':False}

    def status(self,identifier):
        with self._lock:
            protocol._hash(identifier);entry=self.entries.get(identifier)
            if entry is not None:return {'state':'DURABLE_RECEIVER_ORIGINALS','document_hash':identifier,'queue':entry.snapshot(),
                'receiver_paused_nonce':entry._body['paused_nonce'],'payments_executed_asserted':False}
            path=self._path(identifier,'.admission.json')
            if not path.exists():return {'state':'NOT_RETAINED_CHECK_ACCOUNT_PROOF_OR_RESUBMIT','payments_executed_asserted':False}
            body=self._validate(unpack(self._read(path,MAX_META)),identifier)
            return {'state':'NONCES_CONSUMED_OUTCOME_UNRESOLVED','document_hash':identifier,'account_proof':deepcopy(body['terminal_proof']),
                    'payments_executed_asserted':False}
