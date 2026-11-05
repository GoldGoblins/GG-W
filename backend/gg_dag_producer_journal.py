"""Owned v5 producer journal: persist before export, replay before signing.

Only own proposals enter this profile version. Global account/creator state
comes from a pinned SDK certificate; the own-chain engine is not a global view.
No key generation, process, listener or work starts at import.
"""
from copy import deepcopy
import hashlib
import secrets
import sqlite3
import threading
import time

from backend import gg_dag_producer_archive as archives,gg_dag_segmented as segmented
from backend.gg_node_store import NodeProfile,SCHEMA_V4,pack,unpack,HEX
from backend.gg_parallel_dag import ParallelDag,HOT_PAYLOAD_BYTES
from backend.gg_dag_json import preflight_lan_block
from backend.gg_dag_segmented_session import validate_bundle
from backend.gg_dag_checkpoint import certificate_tip

SCHEMA='gg.node.segmented-producer.v1'
SCOPE='OWN_DURABLE_SIGNED_PROPOSALS_NOT_GLOBAL_STATE_OR_FULL_HISTORY_REPLAY'
_FIELDS={'schema','genesis_hash','owner_key','indices','base_packet','packet','floor','head','archive','archive_count','pending_cut','fault','conflict'}


def _core(packet):return {key:packet[key] for key in ('schema','genesis','genesis_hash','state','signed_header')}


def _contract(profile,bundle):
    descriptor=profile.descriptor();contract=validate_bundle(bundle,descriptor['trusted_coordinator'])
    own=[entry for entry in contract['roster'] if entry['invite']['body']['peer_key']==descriptor['public_keys'][0]]
    if (descriptor.get('node_role','producer')!='producer' or descriptor['allow_dag_transactions'] is not True or len(own)!=1
            or profile._head['entries'] or profile._meta['cursors'] or profile._meta['fault']
            or profile._meta.get('order_index') or profile._meta.get('peer_scans')):raise ValueError('GG_PRODUCER_EMPTY_OWN_PROFILE_REQUIRED')
    row=own[0]['invite']['body'];indices=own[0]['producer_indices']
    shared=profile._meta.get('consensus')
    if shared is not None:
        profile._consensus_tip(shared)
        if (shared['packet']['genesis']!=contract['anchor']['genesis']
                or shared['packet']['genesis_hash']!=contract['anchor']['genesis_hash']):raise ValueError('GG_PRODUCER_EMPTY_OWN_PROFILE_REQUIRED')
    if (row.get('node_role','producer')!='producer' or row['producer_keys']!=descriptor['public_keys'][1:] or row['nonce']!=descriptor['pair_nonce']
            or (row['host'],row['port'])!=(descriptor['host'],descriptor['port'])
            or any(index not in contract['source']['allowed_producers'] for index in indices)):raise ValueError('GG_PRODUCER_PROFILE_IDENTITY')
    return contract,indices


def _rows(profile,state,check):
    metadata=list(profile._db.execute('SELECT position,typeof(producer),typeof(sequence),length(identifier),typeof(identifier),length(wire_hash),typeof(wire_hash),length(wire),typeof(wire) FROM own_proposals ORDER BY position LIMIT 4096'))
    if len(metadata)!=state['head']['records']:raise ValueError('GG_PRODUCER_JOURNAL_HISTORY')
    for position,row in enumerate(metadata,1):
        check();index,producer_type,sequence_type,id_size,id_type,hash_size,hash_type,size,kind=row
        if (index!=position or producer_type!='integer' or sequence_type!='integer' or id_size!=64 or id_type!='text'
                or hash_size!=64 or hash_type!='text' or kind!='blob' or type(size) is not int or not 0<size<=archives.MAX_WIRE):raise ValueError('GG_PRODUCER_JOURNAL_RECORD')
        producer,sequence,identifier,wire_hash=profile._db.execute('SELECT producer,sequence,identifier,wire_hash FROM own_proposals WHERE position=?',(index,)).fetchone()
        if (producer not in state['indices'] or not 1<=sequence<=segmented.MAX_COUNTER
                or type(identifier) is not str or not HEX.fullmatch(identifier) or type(wire_hash) is not str or not HEX.fullmatch(wire_hash)
                ):raise ValueError('GG_PRODUCER_JOURNAL_RECORD')
        raw=bytes(profile._db.execute('SELECT wire FROM own_proposals WHERE position=?',(index,)).fetchone()[0])
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=wire_hash:raise ValueError('GG_PRODUCER_JOURNAL_WIRE_HASH')
        yield (index,producer,sequence,identifier,wire_hash,size,kind),raw


def _decode(row,raw):
    preflight_lan_block(raw);value=unpack(raw);body=value['body']
    if (set(value)!={'body','signature'} or body['producer_index']!=row[1] or body['sequence']!=row[2]
            or hashlib.sha256(b'GG-DAG-BLOCK-v1\0'+pack(body)).hexdigest()!=row[3]):raise ValueError('GG_PRODUCER_JOURNAL_RECORD')
    return body


def validate_stored_profile(profile,*,check=lambda:None):
    """Sealed metadata + every current raw hash and archived byte, no SDK claim."""
    external=check;interruption=None
    def check():
        nonlocal interruption
        try:external()
        except BaseException as error:interruption=error;raise
    try:
        state=profile._meta.get('segmented_producer')
        if profile._schema_version!=4 or not isinstance(state,dict) or set(state)!=_FIELDS or state['schema']!=SCHEMA:raise ValueError()
        contract,indices=_contract(profile,profile.session());anchor=contract['anchor']
        if (state['genesis_hash']!=anchor['genesis_hash'] or state['owner_key']!=profile.descriptor()['public_keys'][0] or state['indices']!=indices
                or not isinstance(state['floor'],list) or len(state['floor'])!=2 or type(state['floor'][0]) is not int or not 1<=state['floor'][0]<=segmented.MAX_COUNTER
                or type(state['floor'][1]) is not str or not HEX.fullmatch(state['floor'][1])
                or state['fault'] not in ('','GG_CONSENSUS_CONFLICTING_CERTIFICATE') or type(state['archive']) is not str or not HEX.fullmatch(state['archive'])
                or type(state['archive_count']) is not str or not state['archive_count'].isdigit() or str(int(state['archive_count']))!=state['archive_count']
                or not 0<=int(state['archive_count'])<=segmented.MAX_COUNTER):raise ValueError()
        for name in ('base_packet','packet'):
            if (not isinstance(state[name],dict) or len(pack(state[name]))>256*1024 or state[name]['genesis']!=anchor['genesis']
                    or state[name]['genesis_hash']!=anchor['genesis_hash'] or not isinstance(state[name].get('dag_segmented_base_proof'),dict)):raise ValueError()
            segmented.validate_state(state[name]['state']['dag_segmented'],contract['source'],anchor['genesis_hash'])
        if (state['base_packet']['state']['dag_segmented']['epoch']!=state['packet']['state']['dag_segmented']['epoch']
                or list(certificate_tip(_core(state['packet']),anchor))!=state['floor']):raise ValueError()
        expected=archives.empty_head(anchor['genesis_hash'],state['base_packet']['state']['dag_segmented']['epoch'])
        if (not isinstance(state['head'],dict) or set(state['head'])!=set(expected) or type(state['head']['records']) is not int
                or not 0<=state['head']['records']<=archives.MAX_RECORDS or type(state['head']['bytes']) is not int
                or not 0<=state['head']['bytes']<=archives.MAX_BYTES or type(state['head']['digest']) is not str or not HEX.fullmatch(state['head']['digest'])):raise ValueError()
        for row,raw in _rows(profile,state,check):expected=archives.advance(expected,raw)
        if expected!=state['head']:raise ValueError()
        # Hash the complete sealed journal before decoding any record's JSON.
        for row,raw in _rows(profile,state,check):_decode(row,raw)
        intent=state['pending_cut']
        if intent is not None:
            if (not isinstance(intent,dict) or set(intent)!={'packet','token'} or type(intent['token']) is not str or not HEX.fullmatch(intent['token'])
                    or not isinstance(intent['packet'],dict) or len(pack(intent['packet']))>256*1024):raise ValueError()
        conflict=state['conflict']
        if (state['fault']=='')!=(conflict is None):raise ValueError()
        if conflict is not None and (not isinstance(conflict,list) or len(conflict)!=2):raise ValueError()
        archives.inspect_chain(profile,state,check=check)
        return contract
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        if interruption is not None:raise interruption
        raise ValueError('GG_PRODUCER_JOURNAL_INVALID') from None


class OwnedSegmentedProducer:
    def __init__(self):
        self._lock=threading.RLock();self.profile=None;self._engine=None;self._closed=False;self._failed=False

    def __repr__(self):return '<GG owned segmented producer>'

    @classmethod
    def open(cls,profile,bundle,packet,*,binary=None,stamp=None,check=None,timeout=300,hot_bytes=HOT_PAYLOAD_BYTES):
        if not isinstance(profile,NodeProfile):raise ValueError('GG_PRODUCER_OWNED_PROFILE_REQUIRED')
        if type(timeout) not in (int,float) or not 1<=timeout<=14400:raise ValueError('GG_PRODUCER_TIMEOUT')
        if type(hot_bytes) is not int or not 0<=hot_bytes<=HOT_PAYLOAD_BYTES or check is not None and not callable(check):raise ValueError('GG_PRODUCER_RECOVERY_OPTIONS')
        owner=cls();owner.profile=profile;owner._binary=binary;owner._stamp=stamp;owner._hot_bytes=hot_bytes
        external=check;deadline=time.monotonic()+timeout
        def permitted():
            if external is not None:external()
            if time.monotonic()>=deadline:raise ValueError('GG_PRODUCER_RECOVERY_TIMEOUT')
        with profile._lock:
            if profile._closed or profile._failed or profile._db is None or profile._segmented_writer is not None:raise ValueError('GG_PRODUCER_PROFILE_IN_USE_OR_CLOSED')
            owner._contract,owner._indices=_contract(profile,bundle);owner._anchor=owner._contract['anchor'];owner._source=owner._contract['source']
            existing=profile.session()
            if existing is not None and existing!=bundle:raise ValueError('GG_NODE_STORE_NETWORK_ALREADY_BOUND')
            shared=profile.consensus_observation()
            if shared is not None and shared['fault']:raise ValueError(shared['fault'])
            try:
                permitted();view=owner._verify(packet);permitted()
                if profile._schema_version<4:
                    if profile._schema_version!=3:raise ValueError('GG_PRODUCER_PROFILE_VERSION')
                    base=view['base']['commitment']
                    # A new journal must not invent missing prior own signatures.
                    for index in owner._indices:
                        if int(base['authors'][index]['sequence'])!=0 or int(view['commitment']['authors'][index]['sequence'])!=0:
                            raise ValueError('GG_PRODUCER_OWN_HISTORY_REQUIRED')
                    state={'schema':SCHEMA,'genesis_hash':owner._anchor['genesis_hash'],'owner_key':profile.descriptor()['public_keys'][0],
                        'indices':list(owner._indices),'base_packet':deepcopy(packet),'packet':deepcopy(packet),
                        'floor':list(certificate_tip(_core(packet),owner._anchor)),
                        'head':archives.empty_head(owner._anchor['genesis_hash'],base['epoch']),'archive':archives.ZERO,'archive_count':'0',
                        'pending_cut':None,'fault':'','conflict':None}
                    def bind():
                        profile._db.execute(SCHEMA_V4['own_proposals']);profile._db.execute('PRAGMA user_version=4')
                        profile._meta['session']=deepcopy(bundle);profile._put('session',bundle)
                        profile._meta['segmented_producer']=state;profile._put('segmented_producer',state)
                    profile._write(bind);profile._schema_version=4
                validate_stored_profile(profile,check=permitted)
                state=owner._state()
                if state['fault']:raise ValueError(state['fault'])
                old_view=owner._verify(state['base_packet']);owner._build(old_view['base'],permitted)
                owner._selected(owner._verify(state['packet'])['commitment'])
                if state['pending_cut'] is not None:owner._rotate(state['pending_cut']['packet'],permitted,recovering=True)
                owner._observe(packet,permitted)
                owner._engine.attach_durable_journal(owner._append,owner._fault)
                owner._engine.attach_local_producers(dict(zip(owner._indices,profile.signers()[1])))
                profile._segmented_writer=owner
                return owner
            except BaseException:
                owner.close();raise

    def _state(self):return self.profile._meta['segmented_producer']

    def _usable(self):
        if self._closed or self._failed or self.profile._closed or self.profile._failed or self.profile._db is None:
            raise ValueError('GG_PRODUCER_NOT_WRITABLE')
        if self._state()['fault']:raise ValueError(self._state()['fault'])
        shared=self.profile._meta.get('consensus')
        if shared is not None and shared['fault']:raise ValueError(shared['fault'])

    def _verify(self,packet):
        if not isinstance(packet,dict) or len(pack(packet))>256*1024:raise ValueError('GG_PRODUCER_PACKET_LIMIT')
        return segmented.verify_epoch_base(packet,self._anchor,binary=self._binary,stamp=self._stamp)

    def _save(self,state,operation=lambda:None):
        def update():
            operation();self.profile._meta['segmented_producer']=deepcopy(state);self.profile._put('segmented_producer',state)
        self.profile._write(update)

    def _build(self,base,check):
        engine=ParallelDag.from_segmented_source(self._source,self._anchor['genesis_hash'])
        try:
            engine._install_segment_base(base)
            engine.configure_lan_capacity(block_bytes=archives.MAX_WIRE,session_bytes=archives.MAX_BYTES)
            engine.configure_owned_ingress();engine.configure_payload_archive(self._read,hot_bytes=self._hot_bytes);engine.begin_history_replay()
            for row,raw in _rows(self.profile,self._state(),check):engine.admit_relayed(raw,0,check=check)
            engine.finish_history_replay()
        except BaseException:engine.stop();raise
        self._engine=engine

    def _selected(self,commitment):
        base=self._engine._segment['base']['commitment'];heads={index:{} for index in self._indices}
        for identifier,row in self._engine._records.items():
            if row['producer_index'] in heads:heads[row['producer_index']][row['producer_sequence']]=(identifier,row['_author_nonce'])
        for index in self._indices:
            before=base['authors'][index];author=commitment['authors'][index]
            sequence=int(author['sequence']);initial=int(before['sequence'])
            expected=(before['head'],int(before['nonce'])) if sequence==initial else heads[index].get(sequence)
            if sequence<initial or expected!=(author['head'],int(author['nonce'])):raise ValueError('GG_PRODUCER_OWN_HISTORY_REQUIRED')

    def _observe(self,packet,check):
        check();view=self._verify(packet);check();tip=list(certificate_tip(_core(packet),self._anchor));state=self._state()
        if tip[0]<state['floor'][0]:raise ValueError('GG_PRODUCER_CERTIFICATE_REWIND')
        if tip[0]==state['floor'][0] and tip!=state['floor']:
            changed=deepcopy(state);changed.update(fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE',conflict=[state['packet'],deepcopy(packet)])
            self._save(changed);self._engine.stop();raise ValueError(changed['fault'])
        epoch=int(view['commitment']['epoch']);old_epoch=int(state['base_packet']['state']['dag_segmented']['epoch'])
        if epoch<old_epoch:raise ValueError('GG_PRODUCER_EPOCH_REWIND')
        if epoch>old_epoch:self._rotate(packet,check)
        else:
            old_base=self._verify(state['base_packet'])['base']
            if view['base']!=old_base:raise ValueError('GG_PRODUCER_EPOCH_BASE_CHANGED')
            self._selected(view['commitment'])
            if state['packet']!=packet:
                changed=deepcopy(state);changed.update(packet=deepcopy(packet),floor=tip);self._save(changed)

    def observe(self,packet,*,check=lambda:None):
        with self._lock,self.profile._lock:
            self._usable()
            try:self._observe(packet,check)
            except BaseException as error:
                if str(error) in ('GG_PRODUCER_OWN_HISTORY_REQUIRED','GG_PRODUCER_EPOCH_BASE_CHANGED','GG_PRODUCER_EPOCH_REWIND'):
                    self._failed=True;self.profile._failed=True
                if self._engine is None or not self._engine._active or self.profile._failed:self._failed=True
                raise
            return self.snapshot()

    def _rotate(self,packet,check,*,recovering=False):
        check();view=self._verify(packet);check();state=self._state();base=view['base']['commitment']
        if int(base['epoch'])<=int(state['base_packet']['state']['dag_segmented']['epoch']):raise ValueError('GG_PRODUCER_CUT_EPOCH')
        self._selected(base)
        for index in self._indices:
            if view['commitment']['authors'][index]!=base['authors'][index]:raise ValueError('GG_PRODUCER_OWN_HISTORY_REQUIRED')
        check()
        reactivate=not recovering and any(self._engine._producer_keys)
        # Freeze the old signer before the sealed intent or any archive write.
        self._engine.stop()
        try:
            if state['pending_cut'] is None:
                changed=deepcopy(state);changed['pending_cut']={'packet':deepcopy(packet),'token':secrets.token_hex(32)}
                self._save(changed);state=self._state()
            elif state['pending_cut']['packet']!=packet:raise ValueError('GG_PRODUCER_CUT_INTENT_CHANGED')
            identifier=archives.write_current(self.profile,state,(raw for row,raw in _rows(self.profile,state,check)),packet,state['pending_cut']['token'],check=check)
            changed=deepcopy(state);changed.update(base_packet=deepcopy(packet),packet=deepcopy(packet),floor=list(certificate_tip(_core(packet),self._anchor)),
                head=archives.empty_head(self._anchor['genesis_hash'],base['epoch']),archive=identifier,archive_count=str(int(state['archive_count'])+1),pending_cut=None)
            if int(changed['archive_count'])>segmented.MAX_COUNTER:raise ValueError('GG_PRODUCER_ARCHIVE_COUNT')
            check()
            self._save(changed,lambda:self.profile._db.execute('DELETE FROM own_proposals'))
            self._build(view['base'],check)
            if reactivate:
                self._engine.attach_durable_journal(self._append,self._fault)
                self._engine.attach_local_producers(dict(zip(self._indices,self.profile.signers()[1])))
        except BaseException:self._failed=True;raise

    def _read(self,identifier):
        with self.profile._lock:
            if self.profile._closed or self.profile._failed:raise ValueError('GG_PRODUCER_NOT_WRITABLE')
            try:
                row=self.profile._db.execute('SELECT length(wire_hash),typeof(wire_hash),length(wire),typeof(wire) FROM own_proposals WHERE identifier=?',(identifier,)).fetchone()
                if row is None or row[:2]!=(64,'text') or type(row[2]) is not int or not 0<row[2]<=archives.MAX_WIRE or row[3]!='blob':raise ValueError()
                wire_hash,value=self.profile._db.execute('SELECT wire_hash,wire FROM own_proposals WHERE identifier=?',(identifier,)).fetchone();raw=bytes(value)
                if len(raw)!=row[2] or hashlib.sha256(raw).hexdigest()!=wire_hash:raise ValueError()
                return raw
            except (ValueError,TypeError,IndexError,sqlite3.Error,OSError):
                self._failed=True;self.profile._failed=True
                raise ValueError('GG_PRODUCER_PAYLOAD_CHANGED_OR_MISSING') from None

    def _append(self,raw):
        self._usable();state=self._state()
        if state['pending_cut'] is not None:raise ValueError('GG_PRODUCER_CUT_IN_PROGRESS')
        preflight_lan_block(raw);body=unpack(raw)['body'];producer=body['producer_index'];sequence=body['sequence']
        if producer not in self._indices:raise ValueError('GG_PRODUCER_FOREIGN_SIGNATURE')
        head=archives.advance(state['head'],raw);identifier=hashlib.sha256(b'GG-DAG-BLOCK-v1\0'+pack(body)).hexdigest()
        changed=deepcopy(state);changed['head']=head
        def append():
            self.profile._db.execute('INSERT INTO own_proposals VALUES(?,?,?,?,?,?)',
                (head['records'],producer,sequence,identifier,hashlib.sha256(raw).hexdigest(),raw))
        self._save(changed,append)

    def _fault(self,code):
        # Own producers never admit foreign relayed proposals. Fail the handle;
        # a later owned recovery replays the sealed originals before signing.
        self._failed=True
        raise ValueError('GG_PRODUCER_LOCAL_ENGINE_FAULT')

    def produce(self,producer,transactions,*,check=None,max_wire=archives.MAX_WIRE):
        with self._lock,self.profile._lock:
            self._usable()
            if type(producer) is not int or producer not in self._indices:raise ValueError('GG_PRODUCER_NOT_OWNED')
            shared=self.profile._meta.get('consensus')
            if (shared is not None and int(shared['packet']['state']['dag_segmented']['epoch'])
                    >int(self._state()['packet']['state']['dag_segmented']['epoch'])):raise ValueError('GG_PRODUCER_LATEST_BASE_REQUIRED')
            try:return self._engine.produce_lan_test_block(producer,transactions,max_wire,check=check)
            except BaseException:
                if self.profile._failed or self._engine._lan_fault:self._failed=True
                raise

    def pending(self):
        """Exact committed own bytes beyond the latest selected owner prefixes."""
        with self._lock,self.profile._lock:
            self._usable();state=self._state();authors=state['packet']['state']['dag_segmented']['authors']
            return tuple({'producer_index':index,'sequence':str(sequence),'hash':identifier}
                         for index,sequence,identifier in self.profile._db.execute('SELECT producer,sequence,identifier FROM own_proposals ORDER BY position')
                         if sequence>int(authors[index]['sequence']))

    def read_proposal(self,identifier):
        if type(identifier) is not str or not HEX.fullmatch(identifier):raise ValueError('GG_PRODUCER_PROPOSAL_ID')
        with self._lock,self.profile._lock:self._usable();return self._read(identifier)

    def snapshot(self):
        with self._lock,self.profile._lock:
            state=self._state();current=state['packet']['state']['dag_segmented']
            pending=self.pending()
            return {'schema':'gg.node.producer-observation.v1','scope':SCOPE,'epoch':current['epoch'],'own_indices':list(self._indices),
                'own_records':state['head']['records'],'own_raw_bytes':state['head']['bytes'],'archived_own_epochs':state['archive_count'],
                'certificate_height':state['floor'][0],'certified_global_commitment':deepcopy(current),
                'pending':list(pending[-128:]),'pending_count':len(pending),'closed':self._closed,'fault':state['fault'],
                'global_history_replayed':False,'local_preview_is_global_state':False,'network_liveness_asserted':False,'whole_disk_rollback_protection':False}

    def close(self):
        with self._lock:
            if self._engine is not None:self._engine.stop();self._engine=None
            self._closed=True
            if self.profile is not None and self.profile._segmented_writer is self:self.profile._segmented_writer=None
