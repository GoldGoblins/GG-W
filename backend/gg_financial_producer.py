"""Exclusive protected journal for actual account-signed financial proposals.

Originals and their exact certified signing contexts commit before return.
The bounded production lane permits eight unresolved originals per creator.
It never manufactures payments, asserts mempool finality or discards signatures.
The active window retires into authenticated own-original chunks. Disk space
and compact-index limits remain physical storage constraints.
"""
from copy import deepcopy
import hashlib
import struct
import secrets

from backend import gg_consensus as native,gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_financial_session import validate_bundle
from backend.gg_node_store import NodeProfile,SCHEMA_V6,pack,unpack
from backend import gg_financial_own_archive as archives
from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence

SCHEMA='gg.financial.own-producer.v1'
MAX_RECORDS=8191
MAX_BYTES=512*1024*1024
FIELDS={'schema','genesis_hash','owner_key','indices','head','floor','packet','fault'}
SCHEMA_V2='gg.financial.own-producer.v2'
FIELDS_V2=FIELDS|{'archive','archive_count','archived_head','pending_archive'}
INDEX_COLUMNS='position,producer,epoch,sequence,identifier,context_hash,wire_hash,wire_bytes,archive,wire_offset,context_offset,context_bytes,rank,parent'
FAULTS=('', 'GG_CONSENSUS_CONFLICTING_CERTIFICATE','GG_FINANCIAL_UNKNOWN_OWN_SELECTED_BLOCK','GG_FINANCIAL_STATE_REWIND')


def _core(packet):return {key:deepcopy(packet[key]) for key in ('schema','genesis','genesis_hash','state','signed_header')}
_PUBLIC_CONTEXT={'schema','genesis','genesis_hash','state','signed_header','financial_producer'}


def _derived_signing_context(packet,earlier):
    """Structural own-journal derivation, never a public finality proof.

    The SDK base was natively verified before signing and is retained unchanged.
    Each extension references an earlier exact, authenticated own original.
    Cold-store validation authenticates those producer signatures separately.
    """
    if not isinstance(packet,dict) or set(packet) not in (_PUBLIC_CONTEXT,_PUBLIC_CONTEXT|{'own_prefix'}):
        raise ValueError('GG_FINANCIAL_OWN_CONTEXT')
    proof=deepcopy(packet['financial_producer']);prefix=packet.get('own_prefix',[])
    index=proof['producer_index'];epoch=wire.counter(proof['epoch'],positive=True)
    if (type(index) is not int or not 0<=index<6 or not isinstance(prefix,list) or len(prefix)>=wire.MAX_OWN_PIPELINE
            or any(type(key) is not str or not wire.HASH.fullmatch(key) for key in prefix) or len(prefix)!=len(set(prefix))):
        raise ValueError('GG_FINANCIAL_OWN_CONTEXT')
    value=packet['state']['financial_dag']
    lineage=packet['genesis']['financial_dag']['schema'] in financial.LINEAGE_SOURCE_SCHEMAS
    if (proof['schema']!='gg.financial-dag.producer-context.v1' or proof['genesis_hash']!=packet['genesis_hash']
            or proof['height']!=packet['state']['height'] or proof['state_root']!=packet['state']['state_root']
            or proof['source_hash']!=value['source_hash'] or proof['epoch']!=value['epoch']
            or wire.counter(proof['sequence'],positive=True)!=wire.counter(value['authors'][index]['sequence'])+1):
        raise ValueError('GG_FINANCIAL_OWN_CONTEXT')
    for key in prefix:
        row=earlier.get(key)
        if (row is None or row['producer']!=index or (row['epoch']>epoch if lineage else row['epoch']!=epoch)
                or row['sequence']!=wire.counter(proof['sequence'],positive=True)
                or row['parents']!=[proof['parent']] or row['rank']!=wire.counter(proof['parent_rank'])+1):
            raise ValueError('GG_FINANCIAL_OWN_CONTEXT')
        proof.update(parent=key,parent_rank=str(row['rank']),sequence=str(row['sequence']+1))
    return proof


def _same_creator_context(before,after,index):
    """Only immutable creator/epoch facts authorize reuse of an older proof.

    Account balances/nonces and other creators may advance independently. The
    SDK decides the ordered monetary outcome of each already-signed payment.
    This predicate never authenticates either certificate itself.
    """
    fields=('anchor','source_hash','epoch','last_cut','epoch_base_rank')
    if isinstance(before,dict) and isinstance(after,dict) and before.get('schema')==after.get('schema') and before.get('schema') in ('gg.financial-dag.commitment.v3','gg.financial-dag.commitment.v4'):
        fields=('anchor','source_hash')
    if (not isinstance(before,dict) or not isinstance(after,dict)
            or any(name not in before or name not in after or before[name]!=after[name] for name in fields)
            or type(index) is not int or not 0<=index<6):return False
    a,b=before.get('authors'),after.get('authors')
    return isinstance(a,list) and isinstance(b,list) and len(a)==len(b)==6 and a[index]==b[index]


def _contract(profile):
    descriptor=profile.descriptor();contract=validate_bundle(profile.session(),descriptor['trusted_coordinator'])
    matches=[entry for entry in contract['roster'] if entry['invite']['body']['peer_key']==descriptor['public_keys'][0]]
    if len(matches)!=1 or descriptor.get('node_role','producer')!='producer':raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
    row=matches[0]['invite']['body'];indices=matches[0]['producer_indices']
    if (row.get('node_role','producer')!='producer' or row['producer_keys']!=descriptor['public_keys'][1:]
            or [contract['source']['producers'][index] for index in indices]!=descriptor['public_keys'][1:]):raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
    return contract,indices


def _empty(anchor,owner):
    return {'records':0,'bytes':0,'context_bytes':0,'digest':hashlib.sha256(financial.DOMAIN+b'OWN-JOURNAL\0'+bytes.fromhex(anchor)+bytes.fromhex(owner)).hexdigest()}


def _context_id(raw):return hashlib.sha256(financial.DOMAIN+b'OWN-CONTEXT\0'+raw).hexdigest()


def _advance(head,row,size):
    position,producer,epoch,sequence,identifier,context_hash,wire_hash=row
    if (position!=head['records']+1 or not 1<=position<=financial.MAX_COUNTER or head['bytes']+size>financial.MAX_COUNTER
            or not 0<=producer<6 or not 1<=epoch<=financial.MAX_COUNTER or not 1<=sequence<=financial.MAX_COUNTER
            or any(type(value) is not str or not wire.HASH.fullmatch(value) for value in (identifier,context_hash,wire_hash))
            or not 0<size<=wire.MAX_RAW):raise ValueError('GG_FINANCIAL_JOURNAL_RECORD')
    digest=hashlib.sha256(financial.DOMAIN+b'OWN-RECORD\0'+bytes.fromhex(head['digest'])+struct.pack('>QBQQQ',position,producer,epoch,sequence,size)
            +bytes.fromhex(identifier)+bytes.fromhex(context_hash)+bytes.fromhex(wire_hash)).hexdigest()
    return {**head,'records':position,'bytes':head['bytes']+size,'digest':digest}


def _check_head(head):
    if (not isinstance(head,dict) or set(head)!={'records','bytes','context_bytes','digest'}
            or any(type(head[key]) is not int or not 0<=head[key]<=financial.MAX_COUNTER for key in ('records','bytes','context_bytes'))
            or type(head['digest']) is not str or not wire.HASH.fullmatch(head['digest'])):raise ValueError('GG_FINANCIAL_JOURNAL_HEAD')


def _active_rows(profile,check):
    for data in profile._db.execute('SELECT position,producer,epoch,sequence,identifier,context_hash,wire_hash,length(wire),typeof(wire) FROM financial_proposals ORDER BY position LIMIT ?', (MAX_RECORDS+1,)):
        check();row=data[:7];size,kind=data[7:]
        if kind!='blob' or type(size) is not int or not 0<size<=wire.MAX_RAW:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        shape=profile._db.execute('SELECT length(packet),typeof(packet) FROM financial_contexts WHERE identifier=?',(row[5],)).fetchone()
        if shape is None or shape[1]!='blob' or type(shape[0]) is not int or not 0<shape[0]<=archives.MAX_CONTEXT:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        raw=bytes(profile._db.execute('SELECT wire FROM financial_proposals WHERE position=?',(row[0],)).fetchone()[0])
        packet=bytes(profile._db.execute('SELECT packet FROM financial_contexts WHERE identifier=?',(row[5],)).fetchone()[0])
        if len(raw)!=size or len(packet)!=shape[0]:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        yield row,raw,packet


def _find_original(profile,index,epoch,sequence):
    values=list(profile._db.execute('SELECT identifier FROM financial_proposals WHERE producer=? AND epoch=? AND sequence=?',(index,epoch,sequence)))
    if profile._schema_version==6:
        values+=list(profile._db.execute('SELECT identifier FROM financial_archived WHERE producer=? AND epoch=? AND sequence=?',(index,epoch,sequence)))
    if len(values)>1:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
    return values[0][0] if values else None


class _EarlierFacts:
    """Disk lookups only into positions already authenticated by cold replay."""
    def __init__(self,profile,contract):self.profile=profile;self.contract=contract;self.position=0

    def get(self,identifier):
        if type(identifier) is not str or not wire.HASH.fullmatch(identifier):return None
        if self.profile._schema_version==6:
            row=self.profile._db.execute('SELECT producer,epoch,sequence,rank,parent FROM financial_archived WHERE identifier=? AND position<?',(identifier,self.position)).fetchone()
            if row is not None:return dict(zip(('producer','epoch','sequence','rank','parents'),(*row[:4],[row[4]])))
        shape=self.profile._db.execute('SELECT length(wire),typeof(wire) FROM financial_proposals WHERE identifier=? AND position<?',(identifier,self.position)).fetchone()
        if shape is None:return None
        if shape[1]!='blob' or type(shape[0]) is not int or not 0<shape[0]<=wire.MAX_RAW:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        raw=bytes(self.profile._db.execute('SELECT wire FROM financial_proposals WHERE identifier=?',(identifier,)).fetchone()[0])
        epoch=wire.counter(wire.unpack(raw)['body']['epoch'],positive=True)
        record=wire.decode_block(raw,self.contract['source'],self.contract['anchor']['genesis_hash'],epoch)
        return {'producer':record['producer_index'],'epoch':epoch,'sequence':record['sequence'],'rank':record['rank'],'parents':record['body']['parents']}


def validate_stored_profile(profile,*,check=lambda:None):
    """Verify signed-store binding/originals; this alone is not an SDK proof."""
    external=check;interrupted=None
    def check():
        nonlocal interrupted
        try:external()
        except BaseException as error:interrupted=error;raise
    try:
        state=profile._meta.get('financial_producer');contract,indices=_contract(profile);anchor=contract['anchor']
        version=profile._schema_version
        if (version not in (5,6) or not isinstance(state,dict) or set(state)!=(FIELDS if version==5 else FIELDS_V2)
                or state['schema']!=(SCHEMA if version==5 else SCHEMA_V2)
                or state['genesis_hash']!=anchor['genesis_hash'] or state['owner_key']!=profile.descriptor()['public_keys'][0]
                or state['indices']!=indices or state['fault'] not in FAULTS):raise ValueError()
        head=state['head'];expected=_empty(anchor['genesis_hash'],state['owner_key'])
        _check_head(head)
        base=expected if version==5 else state['archived_head'];_check_head(base)
        if (not 0<=head['records']-base['records']<=MAX_RECORDS or not 0<=head['bytes']-base['bytes']
                or not 0<=head['context_bytes']-base['context_bytes']
                or head['bytes']-base['bytes']+head['context_bytes']-base['context_bytes']>MAX_BYTES):raise ValueError()
        core=state['packet'];tip=certificate_tip(core,anchor)
        if not isinstance(state['floor'],list) or state['floor']!=list(tip):raise ValueError()
        current=wire.counter(core['state']['financial_dag']['epoch'],positive=True)
        used=set();seen={};earlier=_EarlierFacts(profile,contract)
        def validate_record(row,raw,context_raw):
            nonlocal expected
            check();position,producer,epoch,sequence,identifier,context_hash,wire_hash=row
            if producer not in indices or epoch>current:raise ValueError()
            expected=_advance(expected,row,len(raw));earlier.position=position
            if hashlib.sha256(raw).hexdigest()!=wire_hash:raise ValueError()
            record=wire.decode_block(raw,contract['source'],anchor['genesis_hash'],epoch)
            if record['hash']!=identifier or record['producer_index']!=producer or record['sequence']!=sequence or record['payments']==0:raise ValueError()
            if _context_id(context_raw)!=context_hash:raise ValueError()
            packet=unpack(context_raw);certificate_tip(_core(packet),anchor);proof=_derived_signing_context(packet,earlier)
            if (proof['producer_index']!=producer or wire.counter(proof['epoch'],positive=True)!=epoch or wire.counter(proof['sequence'],positive=True)!=sequence
                    or record['body']['parents']!=[proof['parent']] or record['rank']!=wire.counter(proof['parent_rank'])+1):raise ValueError()
            previous=seen.get(producer)
            if previous is None and sequence!=1:raise ValueError()
            if previous is not None and (epoch<previous[0] or epoch==previous[0] and sequence!=previous[1]+1
                    or epoch>previous[0] and sequence>previous[1]+1):raise ValueError()
            if contract['source']['schema'] in financial.LINEAGE_SOURCE_SCHEMAS and previous is not None and sequence!=previous[1]+1:raise ValueError()
            seen[producer]=(epoch,sequence)
            if context_hash not in used:expected['context_bytes']+=len(context_raw);used.add(context_hash)
            return record
        if version==6:
            if (type(state['archive']) is not str or not wire.HASH.fullmatch(state['archive']) or type(state['archive_count']) is not int
                    or not 0<=state['archive_count']<=financial.MAX_COUNTER):raise ValueError()
            pending=state['pending_archive']
            if pending is not None and (not isinstance(pending,dict) or set(pending)!={'token'}
                    or type(pending['token']) is not str or not wire.HASH.fullmatch(pending['token'])):raise ValueError()
            previous=archives.ZERO;count=0
            for number,identifier in profile._db.execute('SELECT number,identifier FROM financial_archives ORDER BY number'):
                check();count+=1
                if (type(number) is not int or number!=count or count>state['archive_count']
                        or type(identifier) is not str or not wire.HASH.fullmatch(identifier)):raise ValueError()
                initial=dict(expected);used.clear()
                def archived_record(row,raw,packet,location):
                    record=validate_record(row,raw,packet)
                    found=profile._db.execute('SELECT '+INDEX_COLUMNS+' FROM financial_archived WHERE position=?',(row[0],)).fetchone()
                    if found!=(*row,len(raw),identifier,*location,record['rank'],record['body']['parents'][0]):raise ValueError()
                header=archives.inspect_file(archives.directory(profile)/(identifier+'.ggfin'),anchor['genesis_hash'],state['owner_key'],
                    expected=identifier,check=check,on_record=archived_record)
                if (header['number']!=number or header['previous_archive']!=previous or header['base']!=initial
                        or header['head']!=expected):raise ValueError()
                previous=identifier
            if (count!=state['archive_count'] or previous!=state['archive'] or expected!=base
                    or profile._db.execute('SELECT count(*) FROM financial_archived').fetchone()[0]!=base['records']):raise ValueError()
        used.clear()
        for row,raw,packet in _active_rows(profile,check):validate_record(row,raw,packet)
        if (profile._db.execute('SELECT count(*) FROM financial_proposals').fetchone()[0]!=head['records']-base['records']
                or profile._db.execute('SELECT count(*) FROM financial_contexts').fetchone()[0]!=len(used) or expected!=head):raise ValueError()
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError,OSError):
        if interrupted is not None:raise interrupted
        raise ValueError('GG_FINANCIAL_JOURNAL_INVALID') from None


class OwnedFinancialProducer:
    def __init__(self):self._closed=True;self._failed=False;self._data_version=None

    @classmethod
    def open(cls,profile,bundle,packet,*,binary=None,stamp=None,check=lambda:None):
        if not isinstance(profile,NodeProfile):raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
        from backend.gg_financial_authority import OwnedFinancialSession
        context=OwnedFinancialSession(profile,bundle);contract,indices=_contract(profile)
        financial.verify_producer(packet,contract['anchor'],binary=binary,stamp=stamp);check()
        if binary is None:binary=native.BINARY;stamp=native._binary_stamp
        if packet['financial_producer']['producer_index'] not in indices:raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
        owner=cls();owner.profile=profile;owner.context=context;owner.anchor=contract['anchor'];owner.source=contract['source'];owner.indices=indices
        owner.binary=binary;owner.stamp=stamp
        with profile._lock:
            if profile._segmented_writer is not None:raise ValueError('GG_PRODUCER_WRITER_ALREADY_OWNED')
            if profile._schema_version==3:
                if profile._head['entries'] or profile._meta.get('order_index') or profile._meta.get('segmented_producer'):raise ValueError('GG_SDK_LEGACY_HISTORY_TRANSITION_REQUIRED')
                core=_core(packet);state={'schema':SCHEMA_V2,'genesis_hash':owner.anchor['genesis_hash'],'owner_key':context.public_key,
                    'indices':indices,'head':_empty(owner.anchor['genesis_hash'],context.public_key),'floor':list(certificate_tip(core,owner.anchor)),
                    'packet':core,'fault':'','archive':archives.ZERO,'archive_count':0,
                    'archived_head':_empty(owner.anchor['genesis_hash'],context.public_key),'pending_archive':None}
                def bind():
                    for name in ('financial_contexts','financial_proposals','financial_archives','financial_archived'):profile._db.execute(SCHEMA_V6[name])
                    profile._db.execute('PRAGMA user_version=6');profile._meta['financial_producer']=state;profile._put('financial_producer',state)
                profile._write(bind);profile._schema_version=6
            elif profile._schema_version==5:
                validate_stored_profile(profile,check=check)
                state={**deepcopy(profile._meta['financial_producer']),'schema':SCHEMA_V2,'archive':archives.ZERO,'archive_count':0,
                    'archived_head':_empty(owner.anchor['genesis_hash'],context.public_key),'pending_archive':None}
                def upgrade():
                    for name in ('financial_archives','financial_archived'):profile._db.execute(SCHEMA_V6[name])
                    profile._db.execute('PRAGMA user_version=6');profile._meta['financial_producer']=state;profile._put('financial_producer',state)
                profile._write(upgrade);profile._schema_version=6
            elif profile._schema_version!=6:raise ValueError('GG_PRODUCER_JOURNAL_VERSION')
            validate_stored_profile(profile,check=check)
            owner._closed=False
            owner._data_version=profile._db.execute('PRAGMA data_version').fetchone()[0]
            try:
                if profile._meta['financial_producer']['pending_archive'] is not None:owner._archive(check)
                owner._observe(packet);profile._segmented_writer=owner;return owner
            except BaseException:owner._closed=True;raise

    def _usable(self):
        self.context.check()
        if self._closed or self._failed or self.profile._closed or self.profile._failed:raise ValueError('GG_FINANCIAL_PRODUCER_CLOSED')
        if self.profile._db.execute('PRAGMA data_version').fetchone()[0]!=self._data_version:
            self._failed=True;self.profile._failed=True;raise ValueError('GG_FINANCIAL_JOURNAL_CHANGED')
        fault=self.profile._meta['financial_producer']['fault']
        if fault:raise ValueError(fault)

    def _save(self,state,operation=lambda:None):
        _check_head(state['head'])
        if 'archived_head' in state:_check_head(state['archived_head'])
        def update():operation();self.profile._meta['financial_producer']=deepcopy(state);self.profile._put('financial_producer',state)
        self.profile._write(update)

    def _maybe_archive(self,check):
        state=self.profile._meta['financial_producer'];head=state['head'];base=state['archived_head']
        if head['records']>base['records'] and (head['records']-base['records']>MAX_RECORDS-wire.MAX_OWN_PIPELINE
                or head['bytes']-base['bytes']+head['context_bytes']-base['context_bytes']>MAX_BYTES-wire.MAX_RAW):
            self._archive(check)

    def _archive(self,check=lambda:None):
        self._usable();check();state=self.profile._meta['financial_producer']
        if state['head']['records']==state['archived_head']['records']:raise ValueError('GG_FINANCIAL_ARCHIVE_EMPTY')
        if state['archive_count']==financial.MAX_COUNTER:raise ValueError('GG_FINANCIAL_ARCHIVE_LIMIT')
        try:
            if state['pending_archive'] is None:
                self._save({**state,'pending_archive':{'token':secrets.token_hex(32)}});state=self.profile._meta['financial_producer']
            identifier=archives.write_current(self.profile,state,_active_rows(self.profile,check),check=check)
            index=[]
            def indexed(row,raw,packet,location):
                record=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],row[2])
                if record['hash']!=row[4] or record['producer_index']!=row[1] or record['sequence']!=row[3]:raise ValueError('GG_FINANCIAL_ARCHIVE_INDEX')
                index.append((*row,len(raw),identifier,*location,record['rank'],record['body']['parents'][0]))
            header=archives.inspect_file(archives.directory(self.profile)/(identifier+'.ggfin'),state['genesis_hash'],state['owner_key'],
                expected=identifier,check=check,on_record=indexed)
            if header['head']!=state['head'] or len(index)!=state['head']['records']-state['archived_head']['records']:
                raise ValueError('GG_FINANCIAL_ARCHIVE_HEAD')
            changed={**state,'archive':identifier,'archive_count':state['archive_count']+1,'archived_head':deepcopy(state['head']),'pending_archive':None}
            def retire():
                self.profile._db.execute('INSERT INTO financial_archives(number,identifier) VALUES(?,?)',(changed['archive_count'],identifier))
                self.profile._db.executemany('INSERT INTO financial_archived('+INDEX_COLUMNS+') VALUES('+','.join('?' for _ in range(14))+')',index)
                self.profile._db.execute('DELETE FROM financial_proposals');self.profile._db.execute('DELETE FROM financial_contexts')
            check();self._save(changed,retire)
        except BaseException:
            self._failed=True;raise

    def _observe(self,packet):
        self._usable();state=self.profile._meta['financial_producer'];core=_core(packet);tip=certificate_tip(core,self.anchor);old=tuple(state['floor'])
        shared=self.profile.consensus_observation()
        if shared is not None:
            common=self.profile._consensus_tip(shared)
            if tip[0]<common[0]:
                newer=shared['packet'];before=core['state'];after=newer['state']
                # A different creator may progress while this producer checks
                # account signatures. Reuse only an unchanged own creator head
                # in the same certified epoch/cut. The newer independently
                # verified certificate remains the durable anti-rollback floor.
                if not _same_creator_context(before['financial_dag'],after['financial_dag'],packet['financial_producer']['producer_index']):
                    raise ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT')
                result=native._verify_public(newer,self.binary,self.stamp)
                if result.get('financial_dag_commitment')!=after['financial_dag']:raise ValueError('GG_FINANCIAL_CERTIFIED_STATE_REQUIRED')
                core=deepcopy(newer);tip=common
            if tip[0]==common[0] and tip!=common:
                self.profile.save_consensus_conflict(make_conflict_evidence(shared['packet'],core,self.anchor));raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        if tip[0]<old[0]:raise ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT')
        if wire.counter(core['state']['financial_dag']['epoch'],positive=True)<wire.counter(state['packet']['state']['financial_dag']['epoch'],positive=True):
            self._save({**state,'fault':'GG_FINANCIAL_STATE_REWIND'});raise ValueError('GG_FINANCIAL_STATE_REWIND')
        if tip[0]==old[0] and tip!=old:
            evidence=make_conflict_evidence(state['packet'],core,self.anchor)
            self.profile.save_consensus_conflict(evidence)
            self._save({**state,'fault':'GG_CONSENSUS_CONFLICTING_CERTIFICATE'});raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        # A later selected signature under our creator key must be an exact
        # retained original. Sequence alone never proves our block was selected.
        for index in self.indices:
            author=core['state']['financial_dag']['authors'][index];sequence=wire.counter(author['sequence'])
            if sequence:
                epoch=wire.counter(author['epoch'],positive=True)
                identifier=_find_original(self.profile,index,epoch,sequence)
                if identifier is None or identifier!=author['head']:
                    self._save({**state,'fault':'GG_FINANCIAL_UNKNOWN_OWN_SELECTED_BLOCK'});raise ValueError('GG_FINANCIAL_UNKNOWN_OWN_SELECTED_BLOCK')
        self.profile.save_consensus_certificate(core)
        if tip[0]>old[0]:self._save({**state,'floor':list(tip),'packet':core})

    def observe(self,packet):
        financial.verify_producer(packet,self.anchor,binary=self.binary,stamp=self.stamp)
        with self.profile._lock:self._observe(packet)

    def _pending_rows(self,index,sequence,epoch):
        if self.source['schema'] in financial.LINEAGE_SOURCE_SCHEMAS:
            # Globally increasing sequences and nondecreasing signing epochs
            # make each covering-index tail sufficient, across both stores.
            rows=[]
            for table in ('financial_proposals','financial_archived'):
                rows.extend(self.profile._db.execute('SELECT epoch,sequence,identifier FROM '+table+' WHERE producer=? ORDER BY epoch DESC,sequence DESC LIMIT ?',
                    (index,wire.MAX_OWN_PIPELINE+1)))
            rows=sorted((row for row in rows if row[1]>=sequence),key=lambda row:row[1])
            if any(row[0]>epoch for row in rows):raise ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT')
        else:
            rows=list(self.profile._db.execute('SELECT epoch,sequence,identifier FROM financial_proposals WHERE producer=? AND epoch=? AND sequence>=? UNION ALL SELECT epoch,sequence,identifier FROM financial_archived WHERE producer=? AND epoch=? AND sequence>=? ORDER BY sequence LIMIT ?',
                (index,epoch,sequence,index,epoch,sequence,wire.MAX_OWN_PIPELINE+1)))
        if len(rows)>wire.MAX_OWN_PIPELINE:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        if any(row[1]!=sequence+offset for offset,row in enumerate(rows)):raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        return rows

    def produce(self,packet,payments,*,created_at_ns=None,check=lambda:None):
        financial.verify_producer(packet,self.anchor,binary=self.binary,stamp=self.stamp);check()
        proof=packet['financial_producer'];index=proof['producer_index']
        if index not in self.indices:raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
        if not isinstance(payments,(list,tuple)) or not 1<=len(payments)<=wire.MAX_PAYMENTS:raise ValueError('GG_FINANCIAL_PAYMENT_COUNT')
        owned=[];total=0
        for payment in payments:
            check();row=wire.check_payment(payment,self.anchor['genesis'],self.anchor['genesis_hash']);total+=len(pack(row))
            if total>wire.MAX_RAW:raise ValueError('GG_FINANCIAL_BLOCK_LIMIT')
            owned.append(row)
        with self.profile._lock:
            self._observe(packet);self._maybe_archive(check);state=self.profile._meta['financial_producer']
            epoch=wire.counter(proof['epoch'],positive=True);sequence=wire.counter(proof['sequence'],positive=True)
            previous=_find_original(self.profile,index,epoch,sequence)
            original_epoch=epoch
            if self.source['schema'] in financial.LINEAGE_SOURCE_SCHEMAS:
                pending=self._pending_rows(index,sequence,epoch)
                if pending:original_epoch,_,previous=pending[0]
            if previous is not None:
                raw=self.original(previous);body=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],original_epoch)['body']
                if body['payments']!=owned or body['parents']!=[proof['parent']] or wire.counter(body['rank'])!=wire.counter(proof['parent_rank'])+1:raise ValueError('GG_FINANCIAL_PENDING_ORIGINAL_REQUIRED')
                return {'hash':previous,'wire':raw,'state':'EXISTING_DURABLE_ORIGINAL','SDK_selected':False}
            signer=self.profile.signers()[1][self.indices.index(index)]
            check();raw=wire._signed_block(packet,self.anchor,signer,owned,created_at_ns=created_at_ns,binary=self.binary,stamp=self.stamp);check()
            record=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],epoch);context_raw=pack(packet);context_hash=_context_id(context_raw)
            head=state['head'];base=state['archived_head'];fresh_context=self.profile._db.execute('SELECT 1 FROM financial_contexts WHERE identifier=?',(context_hash,)).fetchone() is None
            context_bytes=len(context_raw) if fresh_context else 0
            if (head['records']-base['records']>=MAX_RECORDS or head['bytes']-base['bytes']+head['context_bytes']-base['context_bytes']+len(raw)+context_bytes>MAX_BYTES):raise ValueError('GG_FINANCIAL_JOURNAL_CAPACITY')
            position=head['records']+1;row=(position,index,epoch,sequence,record['hash'],context_hash,hashlib.sha256(raw).hexdigest())
            next_head=_advance(head,row,len(raw));next_head['context_bytes']+=context_bytes
            def append():
                if fresh_context:self.profile._db.execute('INSERT INTO financial_contexts(identifier,packet) VALUES(?,?)',(context_hash,context_raw))
                self.profile._db.execute('INSERT INTO financial_proposals(position,producer,epoch,sequence,identifier,context_hash,wire_hash,wire) VALUES(?,?,?,?,?,?,?,?)',(*row,raw))
            self._save({**state,'head':next_head},append)
            return {'hash':record['hash'],'wire':raw,'state':'DURABLE_OWN_ORIGINAL','SDK_selected':False}

    def produce_batch(self,packet,payments,transactions_per_block,*,created_at_ns=None,check=lambda:None):
        """Atomically retain up to eight own originals before any exposure.

        Existing unselected originals must match the requested prefix exactly.
        New signatures extend their actual hashes; no existing sequence is ever
        re-signed. Private prefix references are not public SDK certificates.
        """
        financial.verify_producer(packet,self.anchor,binary=self.binary,stamp=self.stamp);check()
        index=packet['financial_producer']['producer_index']
        if index not in self.indices:raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
        values=wire.authenticate_payments(payments,self.anchor,check=check)
        if type(transactions_per_block) is not int or not 1<=transactions_per_block<=wire.MAX_PAYMENTS:
            raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
        count=(len(values)+transactions_per_block-1)//transactions_per_block
        if not 1<=count<=wire.MAX_OWN_PIPELINE:raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
        with self.profile._lock:
            self._observe(packet);self._maybe_archive(check);state=self.profile._meta['financial_producer'];proof=packet['financial_producer']
            epoch=wire.counter(proof['epoch'],positive=True);sequence=wire.counter(proof['sequence'],positive=True)
            pending=self._pending_rows(index,sequence,epoch)
            if len(pending)>count:raise ValueError('GG_FINANCIAL_PENDING_ORIGINAL_REQUIRED')
            originals=[];prefix=[];identifiers=[];parent=proof['parent'];rank=wire.counter(proof['parent_rank']);prefix_bytes=0
            for offset,(original_epoch,number,identifier) in enumerate(pending):
                check()
                if number!=sequence+offset:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
                raw=self.original(identifier);record=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],original_epoch)
                if (record['producer_index']!=index or record['sequence']!=number or record['rank']!=rank+1
                        or record['body']['parents']!=[parent]):raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
                prefix_bytes+=len(raw)
                if prefix_bytes>wire.MAX_PIPELINE_RAW:raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
                rows=values.rows(offset*transactions_per_block,min(len(values),(offset+1)*transactions_per_block))
                if record['body']['payments']!=rows:raise ValueError('GG_FINANCIAL_PENDING_ORIGINAL_REQUIRED')
                prefix.append(raw);identifiers.append(identifier)
                parent=identifier;rank=record['rank']
                originals.append({'hash':identifier,'wire':raw,'state':'EXISTING_DURABLE_ORIGINAL','SDK_selected':False})
            if len(pending)==count:return originals
            signer=self.profile.signers()[1][self.indices.index(index)]
            fresh=wire._signed_chain(packet,self.anchor,signer,values.suffix(len(pending)*transactions_per_block),transactions_per_block,
                prefix=prefix,created_at_ns=created_at_ns,binary=self.binary,stamp=self.stamp,check=check)
            head=deepcopy(state['head']);base=state['archived_head'];contexts={};appends=[]
            for raw in fresh:
                check();record=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],epoch)
                context=deepcopy(packet)
                if identifiers:context['own_prefix']=list(identifiers)
                context_raw=pack(context);context_hash=_context_id(context_raw)
                if len(context_raw)>256*1024:raise ValueError('GG_FINANCIAL_OWN_CONTEXT')
                known=self.profile._db.execute('SELECT 1 FROM financial_contexts WHERE identifier=?',(context_hash,)).fetchone() is not None
                context_bytes=0 if known or context_hash in contexts else len(context_raw)
                if (head['records']-base['records']>=MAX_RECORDS or head['bytes']-base['bytes']+head['context_bytes']-base['context_bytes']+len(raw)+context_bytes>MAX_BYTES):
                    raise ValueError('GG_FINANCIAL_JOURNAL_CAPACITY')
                row=(head['records']+1,index,epoch,record['sequence'],record['hash'],context_hash,hashlib.sha256(raw).hexdigest())
                head=_advance(head,row,len(raw));head['context_bytes']+=context_bytes
                if not known:contexts[context_hash]=context_raw
                appends.append((row,raw));identifiers.append(record['hash'])
                originals.append({'hash':record['hash'],'wire':raw,'state':'DURABLE_OWN_ORIGINAL','SDK_selected':False})
            def append_all():
                for identifier,context_raw in contexts.items():
                    self.profile._db.execute('INSERT INTO financial_contexts(identifier,packet) VALUES(?,?)',(identifier,context_raw))
                for row,raw in appends:
                    self.profile._db.execute('INSERT INTO financial_proposals(position,producer,epoch,sequence,identifier,context_hash,wire_hash,wire) VALUES(?,?,?,?,?,?,?,?)',(*row,raw))
            check();self._save({**state,'head':head},append_all)
            return originals

    def pending_batch(self,packet,index,*,check=lambda:None):
        """Recover the latest unselected own suffix, never infer it from nonces.

        Native creator selection, plus the retained exact signed originals,
        determines this finite plan. Older epoch originals remain immutable.
        This is local recovery input, not a claim that payments were applied.
        """
        financial.verify_producer(packet,self.anchor,binary=self.binary,stamp=self.stamp);check()
        if type(index) is not int or index not in self.indices or packet['financial_producer']['producer_index']!=index:
            raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
        with self.profile._lock:
            self._observe(packet)
            sequence=wire.counter(packet['financial_producer']['sequence'],positive=True)
            current=wire.counter(packet['financial_producer']['epoch'],positive=True)
            if self.source['schema'] in financial.LINEAGE_SOURCE_SCHEMAS:
                rows=self._pending_rows(index,sequence,current)
                if not rows:return None
                epoch=max(row[0] for row in rows)
            else:
                epoch=self.profile._db.execute('SELECT max(epoch) FROM (SELECT epoch FROM financial_proposals WHERE producer=? AND sequence>=? UNION ALL SELECT epoch FROM financial_archived WHERE producer=? AND sequence>=?)',
                    (index,sequence,index,sequence)).fetchone()[0]
                if epoch is None:return None
                if epoch>current:raise ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT')
                rows=self._pending_rows(index,sequence,epoch)
            if not 1<=len(rows)<=wire.MAX_OWN_PIPELINE:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
            blocks=[];payments=[];total=0
            for offset,(original_epoch,number,identifier) in enumerate(rows):
                check()
                if number!=sequence+offset:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
                raw=self.original(identifier);total+=len(raw)
                if total>wire.MAX_PIPELINE_RAW:raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
                record=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],original_epoch)
                if record['producer_index']!=index or record['sequence']!=number:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
                chunk=record['body']['payments'];blocks.append({'hash':identifier,'sequence':number,'epoch':original_epoch,'payments':len(chunk)})
                payments.extend(chunk)
                if len(payments)>wire.MAX_PAYMENTS:raise ValueError('GG_FINANCIAL_PAYMENT_COUNT')
            size=blocks[0]['payments']
            if any(row['payments']!=size for row in blocks[:-1]) or not 1<=blocks[-1]['payments']<=size:
                raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
            return {'producer_index':index,'epoch':epoch,'sequence':sequence,'blocks':blocks,'payments':payments,'transactions_per_block':size}

    def retry_batch(self,packet,plan,values,*,check=lambda:None):
        """Trim only an exactly certified original prefix before re-signing."""
        financial.verify_producer(packet,self.anchor,binary=self.binary,stamp=self.stamp);check()
        values=wire.authenticate_payments(values,self.anchor,check=check)
        with self.profile._lock:
            self._observe(packet);index=plan['producer_index'];proof=packet['financial_producer']
            if proof['producer_index']!=index:raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
            sequence=wire.counter(proof['sequence'],positive=True);skipped=sequence-plan['sequence']
            if skipped<0:raise ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT')
            if skipped:
                author=packet['state']['financial_dag']['authors'][index]
                # Selection might have advanced while account authentication
                # ran. Do not discard a different original or a guessed nonce.
                if skipped>len(plan['blocks']) or wire.counter(author['epoch'])!=plan['blocks'][skipped-1]['epoch'] or author['head']!=plan['blocks'][skipped-1]['hash']:
                    raise ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT')
            if skipped==len(plan['blocks']):return []
            consumed=sum(row['payments'] for row in plan['blocks'][:skipped])
            if self.source['schema'] in financial.LINEAGE_SOURCE_SCHEMAS:
                originals=[];retained=[]
                for row in plan['blocks'][skipped:]:
                    check();raw=self.original(row['hash']);record=wire.decode_block(raw,self.source,self.anchor['genesis_hash'],row['epoch'])
                    if record['sequence']!=row['sequence'] or record['producer_index']!=index:raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
                    retained.extend(record['body']['payments']);originals.append({'hash':row['hash'],'wire':raw,'state':'EXISTING_DURABLE_ORIGINAL','SDK_selected':False})
                if retained!=values.rows(consumed):raise ValueError('GG_FINANCIAL_PENDING_ORIGINAL_REQUIRED')
                return originals
            return self.produce_batch(packet,values.suffix(consumed),plan['blocks'][skipped]['payments'],check=check)

    def original(self,identifier):
        with self.profile._lock:
            self._usable()
            if type(identifier) is not str or not wire.HASH.fullmatch(identifier):raise ValueError('GG_FINANCIAL_ORIGINAL_ID')
            shape=self.profile._db.execute('SELECT length(wire),typeof(wire) FROM financial_proposals WHERE identifier=?',(identifier,)).fetchone()
            if shape is not None and (shape[1]!='blob' or type(shape[0]) is not int or not 0<shape[0]<=wire.MAX_RAW):
                raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
            row=self.profile._db.execute('SELECT wire,wire_hash FROM financial_proposals WHERE identifier=?',(identifier,)).fetchone()
            if row is None:
                record=self.profile._db.execute('SELECT archive,wire_offset,wire_bytes,wire_hash FROM financial_archived WHERE identifier=?',(identifier,)).fetchone()
                if record is None:raise ValueError('GG_FINANCIAL_ORIGINAL_MISSING')
                try:return archives.read_original(self.profile,record[:3],identifier,record[3])
                except (ValueError,OSError):self._failed=True;raise
            raw=bytes(row[0])
            if hashlib.sha256(raw).hexdigest()!=row[1] or hashlib.sha256(financial.DOMAIN+b'DAG-BLOCK\0'+raw).hexdigest()!=identifier:
                self._failed=True;raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
            return raw

    def snapshot(self):
        with self.profile._lock:
            state=self.profile._meta['financial_producer']
            return {'state':'CLOSED' if self._closed else 'FAULT' if self._failed or state['fault'] else 'READY','originals':state['head']['records'],
                    'active_originals':state['head']['records']-state['archived_head']['records'],'archive_chunks':state['archive_count'],
                    'raw_bytes':state['head']['bytes'],'context_bytes':state['head']['context_bytes'],'certificate_height':state['floor'][0],
                    'counts_basis':'DURABLE_OWN_SIGNATURES_NOT_SDK_SELECTION','SDK_selected_asserted':False,'last_error':state['fault']}

    def close(self):
        with self.profile._lock:
            self._closed=True
            if self.profile._segmented_writer is self:self.profile._segmented_writer=None
