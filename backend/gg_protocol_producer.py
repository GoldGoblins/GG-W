"""Protected producer originals for the versioned public native application.

One signature per creator sequence, bounded unresolved cores and replaceable
work wrappers. Selected preimages move to the same owner's synchronous native
journal; compact immutable signing records and certified creator floors stay
in the protected profile. Nonce consumption never substitutes for a receipt.
"""
import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
import time

from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_node_store import NodeProfile,SCHEMA_V7,PROTOCOL_ACTIVE_INDEX,pack,unpack
from backend.gg_dag_checkpoint import certificate_tip

SCHEMA='gg.protocol.own-producer.v1'
DOMAIN=b'GG-PROTOCOL-OWN-PRODUCER-v1\0'
MAX_PENDING_BYTES=48*1024*1024
MAX_ACTIVE_BYTES=512*1024*1024
FIELDS={'schema','anchor','owner_key','producer_keys','head','selected','work','floor','fault'}


def _hash(raw):return hashlib.sha256(raw).hexdigest()
def core_id(core):return _hash(financial.DOMAIN+b'DAG-BLOCK-CORE-v2\0'+pack(core))
def _empty(anchor,owner):return {'records':0,'wire_bytes':0,'digest':_hash(DOMAIN+b'EMPTY\0'+bytes.fromhex(anchor)+bytes.fromhex(owner))}
def _context_id(context):return _hash(DOMAIN+b'CONTEXT\0'+pack(context))


def _work_context_changed(job,packet,record,sequence):
    """Compare authenticated work with a separately certified live view.

    This predicate grants no trust. Callers verify the exact issued job and
    worker signature before reporting stale work from its result.
    """
    state=packet['state'];current=state['protocol'];height=state['height']
    return (int(record['sequence'])>=sequence or not int(job['state_height'])<=height<=int(job['expires_height'])
        or current['economics']['next_epoch']!=job['epoch'] or current['work_anchor_height']!=job['state_height']
        or current['work_anchor_root']!=job['state_root'] or current['work_target']!=job['network_target'])


def decode_core(raw,trust,*,authenticate_accounts=False,check=lambda:None):
    if not isinstance(raw,bytes) or not 0<len(raw)<=wire.MAX_RAW:raise ValueError('GG_PROTOCOL_CORE_SIZE')
    core=unpack(raw)
    if pack(core)!=raw or not isinstance(core,dict) or set(core)!={'body','signature'}:raise ValueError('GG_PROTOCOL_CORE')
    body=core['body'];fields={'created_at_ns','epoch','genesis_hash','parents','payment_root','payments','producer_key','rank','schema','sequence','source_hash'}
    if (not isinstance(body,dict) or set(body)!=fields or body['schema']!='gg.financial-dag.block.v2' or body['genesis_hash']!=trust['genesis_hash']
            or body['source_hash']!=financial.source_hash(trust['genesis']['financial_dag']) or not isinstance(body['payments'],list)
            or len(body['payments'])>wire.MAX_PAYMENTS or not isinstance(body['parents'],list) or len(body['parents'])!=1):raise ValueError('GG_PROTOCOL_CORE')
    protocol._hash(body['parents'][0]);financial.account_address(body['producer_key'])
    for name in ('epoch','sequence','rank'):wire.counter(body[name],positive=True)
    created=wire.counter(body['created_at_ns'],maximum=financial.MAX_COUNTER-5_000_000_000)
    if created<int(trust['genesis']['financial_dag']['started_at_ns']) or body['payment_root']!=wire.payment_root(body['payments']):raise ValueError('GG_PROTOCOL_CORE')
    protocol._signature(body['producer_key'],core['signature'],financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(body))
    if authenticate_accounts and body['payments']:wire.authenticate_payments(body['payments'],trust,check=check)
    check();return core


def _advance(head,row):
    position,producer,epoch,sequence,identifier,context_hash,wire_hash,size,rank,parent=row
    if (position!=head['records']+1 or position>financial.MAX_COUNTER or not 0<size<=wire.MAX_RAW
            or head['wire_bytes']>financial.MAX_COUNTER-size):raise ValueError('GG_PROTOCOL_SIGNING_INDEX')
    for value in (producer,identifier,context_hash,wire_hash,parent):protocol._hash(value)
    if not 1<=epoch<=financial.MAX_COUNTER or not 1<=sequence<=financial.MAX_COUNTER or not 1<=rank<=financial.MAX_COUNTER:raise ValueError('GG_PROTOCOL_SIGNING_INDEX')
    return {'records':position,'wire_bytes':head['wire_bytes']+size,'digest':_hash(DOMAIN+b'RECORD\0'+bytes.fromhex(head['digest'])+pack(list(row)))}


def _registry(packet,trust,key,*,binary=None,stamp=None):
    result=protocol.verify_selected(packet,trust,registry={'namespace':'producers','key':key},binary=binary,stamp=stamp)
    if result['financial_registry_exists'] is not True:raise ValueError('GG_PROTOCOL_PRODUCER_NOT_REGISTERED')
    raw=base64.b64decode(result['financial_registry_value'],validate=True);record=unpack(raw)
    if pack(record)!=raw:raise ValueError('GG_PROTOCOL_PRODUCER_RECORD')
    return record


def validate_stored_profile(profile,*,binary=None,stamp=None,check=lambda:None):
    state=profile._meta.get('protocol_producer');descriptor=profile.descriptor()
    if (profile._schema_version!=7 or profile.session() is not None or not isinstance(state,dict) or set(state)!=FIELDS or state['schema']!=SCHEMA
            or state['owner_key']!=descriptor['public_keys'][0] or state['producer_keys']!=descriptor['public_keys'][1:]
            or state['fault'] not in ('','GG_PROTOCOL_UNKNOWN_SELECTED_CORE','GG_PROTOCOL_CREATOR_REWIND')
            or not isinstance(state['selected'],dict) or set(state['selected'])!=set(state['producer_keys']) or not isinstance(state['work'],dict)
            or len(state['work'])>16):raise ValueError('GG_PROTOCOL_SIGNING_STORE')
    trust=protocol.validate_pin(state['anchor']);head=_empty(trust['genesis_hash'],state['owner_key']);tips={};selected={}
    for key,packet in state['selected'].items():
        check()
        if packet is None:selected[key]=0;continue
        record=_registry(packet,trust,key,binary=binary,stamp=stamp)
        if record['invite']['body']['owner_peer_key']!=state['owner_key']:raise ValueError('GG_PROTOCOL_SIGNING_OWNER')
        selected[key]=int(record['sequence']);tips[key]=record
    contexts=OrderedDict();active_bytes=0;counts={key:0 for key in state['producer_keys']};last={}
    for row in profile._db.execute('SELECT position,producer,epoch,sequence,identifier,context_hash,wire_hash,wire_bytes,rank,parent FROM protocol_cores ORDER BY position'):
        check();position,key,epoch,sequence,identifier,context_hash,wire_hash,size,rank,parent=row
        if key not in counts or sequence!=counts[key]+1:raise ValueError('GG_PROTOCOL_SIGNING_SEQUENCE')
        prior=last.get(key)
        origin=financial.DOMAIN+b'DAG-GENESIS\0'+pack({'anchor':trust['genesis_hash'],'source':financial.source_hash(trust['genesis']['financial_dag'])})
        if parent!=(prior[0] if prior else _hash(origin)) or rank!=(prior[1]+1 if prior else 1):raise ValueError('GG_PROTOCOL_SIGNING_PARENT')
        head=_advance(head,row);counts[key]=sequence;last[key]=(identifier,rank)
        shape=profile._db.execute('SELECT length(core),typeof(core) FROM protocol_cores WHERE position=?',(position,)).fetchone()
        if sequence<=selected[key]:
            if shape!=(None,'null'):raise ValueError('GG_PROTOCOL_SELECTED_CORE_DUPLICATE')
        else:
            if sequence-selected[key]>8 or shape!=(size,'blob'):raise ValueError('GG_PROTOCOL_PENDING_CORE_LIMIT')
            raw=bytes(profile._db.execute('SELECT core FROM protocol_cores WHERE position=?',(position,)).fetchone()[0]);core=decode_core(raw,trust,check=check)
            if (core_id(core)!=identifier or _hash(raw)!=wire_hash or core['body']['producer_key']!=key or int(core['body']['sequence'])!=sequence
                    or int(core['body']['epoch'])!=epoch or int(core['body']['rank'])!=rank or core['body']['parents']!=[parent]):raise ValueError('GG_PROTOCOL_SIGNING_CORE')
            context=contexts.get(context_hash)
            if context is None:
                shape=profile._db.execute('SELECT length(packet),typeof(packet) FROM protocol_contexts WHERE identifier=?',(context_hash,)).fetchone()
                if shape is None or shape[1]!='blob' or not 0<shape[0]<=256*1024:raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT')
                context=unpack(bytes(profile._db.execute('SELECT packet FROM protocol_contexts WHERE identifier=?',(context_hash,)).fetchone()[0]))
                if not isinstance(context,dict) or set(context)!={'packet','prefix'} or _context_id(context)!=context_hash:raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT')
                base=_registry(context['packet'],trust,key,binary=binary,stamp=stamp)
                if base['invite']['body']['owner_peer_key']!=state['owner_key']:raise ValueError('GG_PROTOCOL_SIGNING_OWNER')
                number=int(base['sequence']);base_parent=base['head'];base_rank=int(base['rank'])
                if not isinstance(context['prefix'],list) or len(context['prefix'])>7:raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT')
                for prefix in context['prefix']:
                    facts=profile._db.execute('SELECT producer,sequence,rank,parent,position FROM protocol_cores WHERE identifier=?',(prefix,)).fetchone()
                    if facts is None or facts[0]!=key or facts[1]!=number+1 or facts[3]!=base_parent or facts[4]>=position or facts[2]!=base_rank+1:raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT')
                    number,base_parent,base_rank=facts[1],prefix,facts[2]
                context['_derived']=(number+1,base_parent,base_rank+1,key)
                contexts[context_hash]=context
                if len(contexts)>16:contexts.popitem(last=False)
            if context['_derived']!=(sequence,parent,rank,key):raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT')
            active_bytes+=size
    if head!=state['head'] or active_bytes>MAX_ACTIVE_BYTES:raise ValueError('GG_PROTOCOL_SIGNING_HEAD')
    for key,record in tips.items():
        sequence=int(record['sequence'])
        if sequence:
            row=profile._db.execute('SELECT identifier FROM protocol_cores WHERE producer=? AND sequence=?',(key,sequence)).fetchone()
            if row!=(record['head'],):raise ValueError('GG_PROTOCOL_UNKNOWN_SELECTED_CORE')
    used_contexts=profile._db.execute('SELECT count(DISTINCT context_hash) FROM protocol_cores INDEXED BY protocol_active WHERE core IS NOT NULL').fetchone()[0]
    if profile._db.execute('SELECT count(*) FROM protocol_contexts').fetchone()[0]!=used_contexts:raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT')
    if profile._db.execute('SELECT count(*) FROM protocol_work').fetchone()[0]!=len(state['work']):raise ValueError('GG_PROTOCOL_WORK_STORE')
    for identifier,expected in state['work'].items():
        check();row=profile._db.execute('SELECT length(packet),length(wire) FROM protocol_work WHERE identifier=?',(identifier,)).fetchone()
        if row is None or not 0<row[0]<=256*1024 or not 0<row[1]<=wire.MAX_RAW:raise ValueError('GG_PROTOCOL_WORK_STORE')
        packet,raw=profile._db.execute('SELECT packet,wire FROM protocol_work WHERE identifier=?',(identifier,)).fetchone();packet=unpack(bytes(packet));raw=bytes(raw)
        if _hash(raw)!=expected:raise ValueError('GG_PROTOCOL_WORK_STORE')
        value=unpack(raw)
        if not isinstance(value,dict) or set(value)!={'body','signature','work'} or not isinstance(packet,dict) or set(packet)!={'packet','prefix'}:raise ValueError('GG_PROTOCOL_WORK_STORE')
        core={'body':value['body'],'signature':value['signature']}
        if core_id(core)!=identifier:raise ValueError('GG_PROTOCOL_WORK_STORE')
        # Work verification authenticates the exact signed payload and target.
        # Causal admission remains native's job. Prefix preimages may already
        # have retired to that same owner's independently replayed SDK journal.
        job=protocol.derive_block_job(core,packet['packet'],trust,core['body']['producer_key'],value['work']['job']['worker_key'],value['work']['job']['share_target'],binary=binary,stamp=stamp)
        share=economy.verify_work(job.document(),value['work'],int(packet['packet']['state']['height']))
        if not share.network_work:raise ValueError('GG_PROTOCOL_WORK_STORE')
    floor=state['floor']
    if floor is not None and (not isinstance(floor,list) or len(floor)!=2 or any(packet is not None and certificate_tip({key:packet[key] for key in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in packet else set())},trust)[0]>floor[0] for packet in state['selected'].values())):
        raise ValueError('GG_PROTOCOL_SIGNING_FLOOR')
    return True


class ProtocolProducer:
    def __init__(self,profile,node):
        from backend.gg_protocol_node import OwnedProtocolNode
        if type(profile) is not NodeProfile or type(node) is not OwnedProtocolNode or node.owner is not profile:raise ValueError('GG_PROTOCOL_OWNED_NODE_REQUIRED')
        self.profile=profile;self.node=node;self.anchor=node.anchor;self._closed=False;self._mining_cursors={}
        with profile._lock:
            if profile._schema_version==3:
                if profile.session() is not None or profile._head['entries'] or profile._meta.get('consensus') or profile._meta.get('order_index'):raise ValueError('GG_PROTOCOL_FRESH_OWNER_REQUIRED')
                keys=profile.descriptor()['public_keys'];state={'schema':SCHEMA,'anchor':deepcopy(self.anchor),'owner_key':keys[0],'producer_keys':keys[1:],
                    'head':_empty(self.anchor['genesis_hash'],keys[0]),'selected':{key:None for key in keys[1:]},'work':{},'floor':None,'fault':''}
                def bind():
                    for name in ('protocol_contexts','protocol_cores','protocol_work'):profile._db.execute(SCHEMA_V7[name])
                    profile._db.execute(PROTOCOL_ACTIVE_INDEX)
                    profile._db.execute('PRAGMA user_version=7');profile._meta['protocol_producer']=state;profile._put('protocol_producer',state)
                profile._write(bind);profile._schema_version=7
            if profile._schema_version!=7 or profile._meta['protocol_producer']['anchor']!=self.anchor:raise ValueError('GG_PROTOCOL_SIGNING_ANCHOR')
            validate_stored_profile(profile,binary=node.binary,stamp=node._stamp)
            self._version=profile._db.execute('PRAGMA data_version').fetchone()[0]

    def _check(self):
        self.node._check_start()
        if self._closed or self.profile._schema_version!=7 or self.profile._failed or self.profile._closed or self.profile._meta['protocol_producer']['fault']:
            raise ValueError('GG_PROTOCOL_PRODUCER_UNAVAILABLE')
        if self._version!=self.profile._db.execute('PRAGMA data_version').fetchone()[0]:raise ValueError('GG_PROTOCOL_SIGNING_STORE_CHANGED')

    def _save(self,state,operation=lambda:None):
        def update():operation();self.profile._meta['protocol_producer']=deepcopy(state);self.profile._put('protocol_producer',state)
        self.profile._write(update)

    def _proof(self,key):
        packet=self.node.selected_proof('registry',{'namespace':'producers','key':key});record=_registry(packet,self.anchor,key,binary=self.node.binary,stamp=self.node._stamp)
        body=record['invite']['body'];owner=self.profile.descriptor()['public_keys'][0]
        if body['owner_peer_key']!=owner or body['node_key']!=self.node.node_key:raise ValueError('GG_PROTOCOL_PRODUCER_OWNER')
        return packet,record

    def reconcile(self,key):
        with self.profile._lock:
            self._check();state=deepcopy(self.profile._meta['protocol_producer'])
            if key not in state['producer_keys']:raise ValueError('GG_PROTOCOL_PRODUCER_KEY')
            packet,record=self._proof(key);sequence=int(record['sequence']);previous=state['selected'][key]
            if previous is not None:
                old=_registry(previous,self.anchor,key,binary=self.node.binary,stamp=self.node._stamp)
                if sequence<int(old['sequence']):self._save({**state,'fault':'GG_PROTOCOL_CREATOR_REWIND'});raise ValueError('GG_PROTOCOL_CREATOR_REWIND')
            if sequence and self.profile._db.execute('SELECT identifier FROM protocol_cores WHERE producer=? AND sequence=?',(key,sequence)).fetchone()!=(record['head'],):
                self._save({**state,'fault':'GG_PROTOCOL_UNKNOWN_SELECTED_CORE'});raise ValueError('GG_PROTOCOL_UNKNOWN_SELECTED_CORE')
            state['selected'][key]=packet
            core={name:packet[name] for name in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in packet else set())};tip=certificate_tip(core,self.anchor)
            if state['floor'] is not None and tip[0]<state['floor'][0]:raise ValueError('GG_PROTOCOL_CERTIFICATE_REWIND')
            if state['floor'] is not None and tip[0]==state['floor'][0] and list(tip)!=state['floor']:raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            if previous is not None and old==record:return packet,record
            state['floor']=list(tip)
            retired=[row[0] for row in self.profile._db.execute('SELECT identifier FROM protocol_cores INDEXED BY protocol_active WHERE producer=? AND sequence<=? AND core IS NOT NULL',(key,sequence))]
            for identifier in retired:state['work'].pop(identifier,None);self._mining_cursors.pop(identifier,None)
            def retire():
                self.profile._db.execute('UPDATE protocol_cores INDEXED BY protocol_active SET core=NULL WHERE producer=? AND sequence<=? AND core IS NOT NULL',(key,sequence))
                for identifier in retired:self.profile._db.execute('DELETE FROM protocol_work WHERE identifier=?',(identifier,))
                self.profile._db.execute('DELETE FROM protocol_contexts WHERE identifier NOT IN (SELECT DISTINCT context_hash FROM protocol_cores INDEXED BY protocol_active WHERE core IS NOT NULL)')
            self._save(state,retire);return packet,record

    def _pending(self,key,selected):
        rows=list(self.profile._db.execute('SELECT identifier,sequence,length(core) FROM protocol_cores WHERE producer=? AND sequence>? ORDER BY sequence LIMIT 9',(key,selected)))
        if len(rows)>8 or sum(row[2] or 0 for row in rows)>MAX_PENDING_BYTES:raise ValueError('GG_PROTOCOL_PENDING_CORE_LIMIT')
        return rows

    def produce(self,key,payments,*,check=lambda:None):
        with self.profile._lock:
            self._check();packet,record=self.reconcile(key);state=deepcopy(self.profile._meta['protocol_producer']);rows=self._pending(key,int(record['sequence']))
            if len(rows)>=8:raise ValueError('GG_PROTOCOL_PENDING_CORE_LIMIT')
            if not isinstance(payments,(list,tuple)) and type(payments) is not wire._AuthenticatedPayments:raise ValueError('GG_PROTOCOL_PAYMENT_INPUT')
            values=wire.authenticate_payments(payments,self.anchor,check=check).rows() if len(payments) else []
            parent=record['head'];rank=int(record['rank']);sequence=int(record['sequence']);prefix=[]
            for identifier,number,_ in rows:
                earlier=decode_core(self.original(identifier),self.anchor,check=check)
                if number!=sequence+1 or earlier['body']['parents']!=[parent]:raise ValueError('GG_PROTOCOL_SIGNING_SEQUENCE')
                parent=identifier;rank=int(earlier['body']['rank']);sequence=number;prefix.append(identifier)
            created=max(time.time_ns(),int(packet['state']['protocol']['time_ns']))
            body={'created_at_ns':str(created),'epoch':packet['state']['financial_dag']['epoch'],'genesis_hash':self.anchor['genesis_hash'],'parents':[parent],
                  'payment_root':wire.payment_root(values),'payments':values,'producer_key':key,'rank':str(rank+1),'schema':'gg.financial-dag.block.v2',
                  'sequence':str(sequence+1),'source_hash':financial.source_hash(self.anchor['genesis']['financial_dag'])}
            if len(pack({'body':body,'signature':'0'*128}))>wire.MAX_RAW-8192:raise ValueError('GG_PROTOCOL_CORE_WORK_WRAPPER_RESERVE')
            signer=self.profile.signers()[1][state['producer_keys'].index(key)]
            core={'body':body,'signature':signer.sign_message(financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(body)).hex()};raw=pack(core);identifier=core_id(core)
            decode_core(raw,self.anchor,check=check)
            if sum(row[2] for row in rows)+len(raw)>MAX_PENDING_BYTES:raise ValueError('GG_PROTOCOL_PENDING_CORE_LIMIT')
            context={'packet':packet,'prefix':prefix};context_raw=pack(context);context_hash=_context_id(context)
            if len(context_raw)>256*1024:raise ValueError('GG_PROTOCOL_SIGNING_CONTEXT_LIMIT')
            active=self.profile._db.execute('SELECT COALESCE(sum(length(core)),0) FROM protocol_cores INDEXED BY protocol_active WHERE core IS NOT NULL').fetchone()[0]
            if active+len(raw)+len(context_raw)>MAX_ACTIVE_BYTES:raise ValueError('GG_PROTOCOL_SIGNING_STORAGE_LIMIT')
            row=(state['head']['records']+1,key,int(body['epoch']),sequence+1,identifier,context_hash,_hash(raw),len(raw),rank+1,parent)
            state['head']=_advance(state['head'],row)
            state['floor']=list(certificate_tip({name:packet[name] for name in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in packet else set())},self.anchor))
            def append():
                self.profile._db.execute('INSERT OR IGNORE INTO protocol_contexts VALUES(?,?)',(context_hash,context_raw))
                self.profile._db.execute('INSERT INTO protocol_cores VALUES(?,?,?,?,?,?,?,?,?,?,?)',(*row,raw))
            check();self._save(state,append)
            return {'block':identifier,'state':'DURABLE_SIGNED_CORE','SDK_selected':False,'payments_executed_asserted':False}

    def produce_batch(self,key,payments,size,*,check=lambda:None):
        """Reuse a matching pending prefix before signing additional cores."""
        if type(size) is not int or not 1<=size<=5000:raise ValueError('GG_PROTOCOL_PAYMENT_BLOCK_SIZE')
        values=wire.authenticate_payments(payments,self.anchor,check=check)
        count=(len(values)+size-1)//size
        if not 1<=count<=8:raise ValueError('GG_PROTOCOL_PENDING_CORE_LIMIT')
        with self.profile._lock:
            self._check();_,record=self.reconcile(key);pending=self._pending(key,int(record['sequence']))
            if len(pending)>count:raise ValueError('GG_PROTOCOL_PENDING_ORIGINAL_REQUIRED')
            desired=[values.rows(start,min(len(values),start+size)) for start in range(0,len(values),size)]
            result=[]
            for offset,(identifier,_,_) in enumerate(pending):
                if decode_core(self.original(identifier),self.anchor,check=check)['body']['payments']!=desired[offset]:raise ValueError('GG_PROTOCOL_PENDING_ORIGINAL_REQUIRED')
                result.append({'block':identifier,'state':'EXISTING_DURABLE_SIGNED_CORE','SDK_selected':False,'payments_executed_asserted':False})
            for offset in range(len(pending),len(desired)):
                result.append(self.produce(key,values.segment(offset*size,min(len(values),(offset+1)*size)),check=check))
            return result

    def original(self,identifier):
        with self.profile._lock:
            self._check();row=self.profile._db.execute('SELECT wire_hash,wire_bytes,length(core) FROM protocol_cores WHERE identifier=?',(identifier,)).fetchone()
            if row is None:raise ValueError('GG_PROTOCOL_ORIGINAL_UNKNOWN')
            if row[2] is None:raw=self.node.original_core(identifier)
            else:raw=bytes(self.profile._db.execute('SELECT core FROM protocol_cores WHERE identifier=?',(identifier,)).fetchone()[0])
            if len(raw)!=row[1] or _hash(raw)!=row[0] or core_id(decode_core(raw,self.anchor))!=identifier:raise ValueError('GG_PROTOCOL_ORIGINAL_CHANGED')
            return raw

    def mine(self,identifier,*,attempts=65536,start=None,check=lambda:None):
        with self.profile._lock:
            self._check();core=decode_core(self.original(identifier),self.anchor,check=check);key=core['body']['producer_key'];packet,record=self.reconcile(key)
            if int(core['body']['sequence'])<=int(record['sequence']):return {'state':'SDK_SELECTED','block':identifier,'payments_executed_asserted':False}
            rows=self._pending(key,int(record['sequence']));prefix=[];ids=[]
            for previous,_,_ in rows:
                if previous==identifier:break
                prefix.append(decode_core(self.original(previous),self.anchor,check=check));ids.append(previous)
            worker=self.profile.signers()[0];job=protocol.derive_block_job(core,packet,self.anchor,key,worker.pubkey().hex(),packet['state']['protocol']['work_target'],prefix=prefix,binary=self.node.binary,stamp=self.node._stamp)
            retained=self.profile._db.execute('SELECT length(wire) FROM protocol_work WHERE identifier=?',(identifier,)).fetchone()
            if retained is not None:
                if not 0<retained[0]<=wire.MAX_RAW:raise ValueError('GG_PROTOCOL_WORK_STORE')
                old_raw=bytes(self.profile._db.execute('SELECT wire FROM protocol_work WHERE identifier=?',(identifier,)).fetchone()[0])
                if _hash(old_raw)!=self.profile._meta['protocol_producer']['work'].get(identifier):raise ValueError('GG_PROTOCOL_WORK_STORE')
                old=unpack(old_raw)
                # A real pool worker may have solved this same immutable core.
                # Re-derive every job field from certified state before reuse.
                old_target=old['work']['job']['share_target'];expected_old=None
                if type(old_target) is str and wire.HASH.fullmatch(old_target) and old_target>=job.document()['network_target']:
                    expected_old=protocol.derive_block_job(core,packet,self.anchor,key,old['work']['job']['worker_key'],old_target,prefix=prefix,binary=self.node.binary,stamp=self.node._stamp)
                if expected_old is not None and old['work']['job']==expected_old.document():
                    share=economy.verify_work(expected_old.document(),old['work'],int(packet['state']['height']))
                    if share.network_work:return {'state':'DURABLE_NETWORK_WORK','block':identifier,'SDK_selected':False}
            job_hash=_hash(pack(job.document()));cursor=self._mining_cursors.get(identifier)
            if start is None:
                if cursor is not None and cursor[0]==job_hash and cursor[2]:raise ValueError('GG_PROTOCOL_WORK_NONCE_SPACE_EXHAUSTED')
                start=cursor[1] if cursor is not None and cursor[0]==job_hash else 0
            solution,next_nonce,exhausted=economy.mine_work(job.document(),worker,start,attempts,check=check)
            self._mining_cursors[identifier]=(job_hash,next_nonce,exhausted)
            if solution is None:return {'state':'WORK_EXHAUSTED','block':identifier,'next_nonce':str(next_nonce),'nonce_space_exhausted':exhausted}
            raw=pack({**core,'work':solution});state=deepcopy(self.profile._meta['protocol_producer']);state['work'][identifier]=_hash(raw)
            context=pack({'packet':packet,'prefix':ids})
            def retain():self.profile._db.execute('INSERT OR REPLACE INTO protocol_work VALUES(?,?,?)',(identifier,context,raw))
            self._save(state,retain);return {'state':'DURABLE_NETWORK_WORK','block':identifier,'SDK_selected':False}

    def work_manifest(self,identifier,job):
        with self.profile._lock:
            self._check()
            if type(job) is not protocol.CertifiedMiningJob:raise ValueError('GG_MINING_CERTIFIED_CONTEXT_REQUIRED')
            core=decode_core(self.original(identifier),self.anchor);key=core['body']['producer_key'];document=job.document()
            if document['payload_root']!=identifier or document['genesis_hash']!=self.anchor['genesis_hash']:raise ValueError('GG_MINING_WORK_MANIFEST_CONTEXT')
            body={'block':identifier,'genesis_hash':self.anchor['genesis_hash'],'job':document,'producer_key':key,
                'schema':'gg.financial.work-manifest.v1','sequence':core['body']['sequence']}
            signer=self.profile.signers()[1][self.profile._meta['protocol_producer']['producer_keys'].index(key)]
            return {'body':body,'signature':signer.sign_message(b'GG-FINANCIAL-WORK-MANIFEST-v1\0'+pack(body)).hex()}

    def attach_work(self,identifier,solution,*,expected_job=None,check=lambda:None):
        """Retain an independently checked worker solution for an owned core."""
        with self.profile._lock:
            self._check();issued=None
            if expected_job is not None:
                if type(expected_job) is not protocol.CertifiedMiningJob:raise ValueError('GG_MINING_CERTIFIED_CONTEXT_REQUIRED')
                issued=expected_job.document()
                if issued['payload_root']!=identifier:raise ValueError('GG_MINING_WORK_INVALID')
                # Cryptographic validity precedes stale classification. A newer
                # SDK epoch can never turn a forged share into retryable work.
                economy.verify_work(issued,solution,int(issued['state_height']))
            core=decode_core(self.original(identifier),self.anchor,check=check);key=core['body']['producer_key'];packet,record=self.reconcile(key)
            if issued is not None and _work_context_changed(issued,packet,record,int(core['body']['sequence'])):raise ValueError('GG_POOL_JOB_STALE')
            if int(core['body']['sequence'])<=int(record['sequence']):return {'state':'SDK_SELECTED','block':identifier,'payments_executed_asserted':False}
            if not isinstance(solution,dict) or not isinstance(solution.get('job'),dict):raise ValueError('GG_MINING_WORK_INVALID')
            job=protocol.derive_block_job(core,packet,self.anchor,key,solution['job'].get('worker_key'),solution['job'].get('share_target'),binary=self.node.binary,stamp=self.node._stamp)
            share=economy.verify_work(job.document(),solution,int(packet['state']['height']))
            if not share.network_work:raise ValueError('GG_PROTOCOL_NETWORK_WORK_REQUIRED')
            raw=pack({**core,'work':solution})
            if len(raw)>wire.MAX_RAW:raise ValueError('GG_PROTOCOL_WORK_STORE')
            state=deepcopy(self.profile._meta['protocol_producer']);state['work'][identifier]=_hash(raw)
            context=pack({'packet':packet,'prefix':[]})
            def retain():self.profile._db.execute('INSERT OR REPLACE INTO protocol_work VALUES(?,?,?)',(identifier,context,raw))
            check();self._save(state,retain)
            return {'state':'DURABLE_NETWORK_WORK','block':identifier,'SDK_selected':False}

    def submit_pending(self,key):
        with self.profile._lock:
            self._check();packet,record=self.reconcile(key);blocks=[];size=0
            for identifier,_,_ in self._pending(key,int(record['sequence'])):
                row=self.profile._db.execute('SELECT length(wire) FROM protocol_work WHERE identifier=?',(identifier,)).fetchone()
                if row is None:break
                raw=bytes(self.profile._db.execute('SELECT wire FROM protocol_work WHERE identifier=?',(identifier,)).fetchone()[0]);size+=len(raw)
                if size>wire.MAX_RAW:break
                if _hash(raw)!=self.profile._meta['protocol_producer']['work'].get(identifier):raise ValueError('GG_PROTOCOL_WORK_STORE')
                blocks.append(base64.b64encode(raw).decode('ascii'))
            if not blocks:return {'state':'NO_READY_WORK','SDK_selected':False}
            commitment=packet['state']['financial_dag'];batch={'blocks':blocks,'genesis_hash':self.anchor['genesis_hash'],
                'previous':_hash(financial.DOMAIN+b'DAG-COMMITMENT\0'+pack(commitment)),'schema':'gg.financial-dag.batch.v2',
                'sequence':str(int(commitment['checkpoint'])+1),'source_hash':financial.source_hash(self.anchor['genesis']['financial_dag'])}
            response=self.node._rpc('broadcast_tx_sync',pack(batch))
            return {'state':'MEMPOOL_ACCEPTED' if int(response.get('code',1))==0 else 'MEMPOOL_REJECTED','blocks':len(blocks),'SDK_selected':False,'payments_executed_asserted':False}

    def close(self):self._closed=True
