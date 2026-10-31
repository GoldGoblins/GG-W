"""Finite RAM-only parallel signed-proposal DAG, not a new money consensus.

Manual waves retain four producers by default. An explicit asynchronous mode
uses independently scheduled local workers, not synchronized synthetic waves.
Admission verifies real Ed25519 signatures and checkpoint-membership witnesses.
Deterministic execution is explicitly a LOCAL PREVIEW. No proposal, signature
or graph edge supplies Byzantine consensus, data availability or finality.
An explicitly started, finite live runner can create signed empty proposals.
It stops at the same session credits as manual waves and never queues work.
There is no network listener, wallet or persistent state here.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import re
import secrets
import threading
import time

from Crypto.Signature import eddsa
from backend.gg_ed25519 import Keypair
from backend.gg_block_graph import LIVE_HISTORY_LIMIT

PRODUCERS=4
MAX_PRODUCERS=16
ASYNC_LIVE_PRODUCERS=8
ACCOUNT_COUNT=512
INITIAL_BALANCE=1_000_000_000
MAX_PARENTS=7
MAX_WAVE_BLOCKS=32
MAX_TX_PER_BLOCK=128
MAX_WAVE_TRANSACTIONS=512
MAX_BLOCK_BYTES=262144
MAX_SESSION_BYTES=8*1024*1024
LAN_MAX_TX_PER_BLOCK=50000
LAN_MAX_BLOCK_BYTES=32*1024*1024
LAN_MAX_SESSION_BYTES=512*1024*1024
MAX_RECORDS=4096
MAX_ATTEMPTS=4096
MAX_ROOTS=8
GRAPH_BLOCKS=LIVE_HISTORY_LIMIT
MEASUREMENT_COUNT=32
LIVE_BLOCKS=8
LIVE_TX_PER_BLOCK=0
LIVE_INTERVAL_MS=125
MIN_LIVE_INTERVAL_MS=10
MAX_LIVE_INTERVAL_MS=60000
RATE_WINDOW_SECONDS=5.0
FINALITY='EXPLICIT_CHECKPOINT_REQUIRED'
_HASH=re.compile(r'^[0-9a-f]{64}$')
_SIGNATURE=re.compile(r'^[0-9a-f]{128}$')


def pack(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def digest(value,domain=b'GG-DAG-DATA-v1\0'):
    return hashlib.sha256(domain+pack(value)).hexdigest()


def _integer(value,low,high,code):
    if type(value) is not int or not low<=value<=high:raise ValueError(code)
    return value


def _hash(value):return isinstance(value,str) and _HASH.fullmatch(value) is not None


def _tree(leaves,domain):
    level=[digest(leaf,domain+b'L\0') for leaf in leaves]
    if not level:level=[hashlib.sha256(domain+b'EMPTY\0').hexdigest()]
    levels=[level]
    while len(level)>1:
        level=[hashlib.sha256(domain+b'N\0'+bytes.fromhex(level[i])+bytes.fromhex(level[min(i+1,len(level)-1)])).hexdigest() for i in range(0,len(level),2)]
        levels.append(level)
    return levels


def _proof(leaves,levels,index):
    path=[];cursor=index
    for level in levels[:-1]:
        sibling=min(cursor^1,len(level)-1)
        path.append({'side':'left' if cursor%2 else 'right','hash':level[sibling]});cursor//=2
    return {'leaf':dict(leaves[index]),'path':path}


def _verify_proof(root,proof):
    if not isinstance(proof,dict) or set(proof)!={'leaf','path'}:return False
    leaf=proof['leaf'];path=proof['path']
    if not isinstance(leaf,dict) or set(leaf)!={'address','balance_atomic','nonce'}:return False
    if not isinstance(path,list) or len(path)!=9:return False
    value=digest(leaf,b'GG-DAG-ACCOUNT-v1\0L\0')
    for item in path:
        if not isinstance(item,dict) or set(item)!={'side','hash'} or item['side'] not in ('left','right') or not _hash(item['hash']):return False
        left,right=(item['hash'],value) if item['side']=='left' else (value,item['hash'])
        value=hashlib.sha256(b'GG-DAG-ACCOUNT-v1\0N\0'+bytes.fromhex(left)+bytes.fromhex(right)).hexdigest()
    return value==root


def _verify(key,message,signature):
    try:
        eddsa.new(eddsa.import_public_key(bytes.fromhex(key)),'rfc8032').verify(message,bytes.fromhex(signature))
    except (ValueError,TypeError):raise ValueError('GG_DAG_SIGNATURE') from None


def make_public_genesis(producer_public_keys,*,enable_dag_transactions=False):
    """Create public disposable test state for independently owned producers.

    Producer keys are supplied as public keys only. Generated account keys are
    immediately discarded; this bootstrap enables empty proposals, not funded
    wallets or a final financial ledger.
    """
    if (not isinstance(producer_public_keys,list) or not 1<=len(producer_public_keys)<=MAX_PRODUCERS
            or any(not _hash(value) for value in producer_public_keys)
            or len(set(producer_public_keys))!=len(producer_public_keys)):raise ValueError('GG_DAG_PUBLIC_PRODUCERS')
    if type(enable_dag_transactions) is not bool:raise ValueError('GG_DAG_PUBLIC_MODE')
    accounts=sorted(producer_public_keys) if enable_dag_transactions else sorted(Keypair().pubkey().hex() for _ in range(ACCOUNT_COUNT))
    leaves=[{'address':address,'balance_atomic':str(INITIAL_BALANCE),'nonce':0} for address in accounts]
    genesis={'schema':'gg.parallel-dag.genesis.v1','chain_id':'ggdag:'+secrets.token_hex(12),
        'producers':list(producer_public_keys),'precheck_root':_tree(leaves,b'GG-DAG-ACCOUNT-v1\0')[-1][0],
        'account_count':len(accounts),'allocation_atomic':str(INITIAL_BALANCE)}
    if enable_dag_transactions:genesis.update(schema='gg.parallel-dag.genesis.v2',test_mode='PRODUCER_OWNED_NONFINANCIAL')
    return {'schema':'gg.parallel-dag.public-genesis.v2' if enable_dag_transactions else 'gg.parallel-dag.public-genesis.v1','genesis':genesis,'genesis_hash':digest(genesis),
        'started_at_ns':time.time_ns(),'accounts':accounts}


class ParallelDag:
    """One explicit local experiment with fixed identities and bounded memory."""
    def __init__(self,producer_count=PRODUCERS,*,random_source=None):
        _integer(producer_count,1,MAX_PRODUCERS,'GG_DAG_PRODUCER_COUNT')
        self._configured_producers=producer_count;self._producer_count=producer_count
        self._random=random_source if random_source is not None else secrets.SystemRandom()
        if any(not callable(getattr(self._random,name,None)) for name in ('uniform','randint','sample')):raise ValueError('GG_DAG_RANDOM_SOURCE')
        self._lock=threading.RLock();self._wave_lock=threading.Lock()
        self._capacity=None;self._lan_producer_locks={};self._lan_work_count=0
        self._active=False;self._events=deque(maxlen=32)
        self._lan_test_mode=False;self._lan_fault='';self._lan_heads={};self._lan_counts={}
        self._live_control=threading.RLock();self._live_thread=None;self._live_cancel=threading.Event()
        self._async_threads=[];self._async_reserved=0;self._async_transactions=0
        self._live={'state':'STOPPED','enabled':False,'blocks':LIVE_BLOCKS,'transactions_per_block':LIVE_TX_PER_BLOCK,
            'interval_ms':LIVE_INTERVAL_MS,'target_proposal_bps':LIVE_BLOCKS*1000/LIVE_INTERVAL_MS,
            'stop_reason':'','waves_completed':0,'in_flight':False,'mode':'WAVE_COMPATIBILITY',
            'producer_count':producer_count,'active_workers':0,'jobs_completed':0}
        self._measurements=deque(maxlen=MEASUREMENT_COUNT);self._rate_samples=deque(maxlen=MAX_RECORDS)
        self._relay_measurement=None

    def start(self):
        """Manual compatibility session; its default remains four producers."""
        return self._start_session(self._configured_producers)

    def export_public_genesis(self):
        """Public bootstrap only: no producer/account signing key is exported."""
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            genesis=next(iter(self._records.values()))['body']
            return {'schema':'gg.parallel-dag.public-genesis.v2' if self._lan_test_mode else 'gg.parallel-dag.public-genesis.v1','genesis':deepcopy(genesis),
                'genesis_hash':digest(genesis),'started_at_ns':self._started_ns,'accounts':list(self._addresses)}

    @classmethod
    def from_public_genesis(cls,bundle):
        """Import an explicitly trusted public session as a keyless verifier."""
        if not isinstance(bundle,dict) or set(bundle)!={'schema','genesis','genesis_hash','started_at_ns','accounts'}:raise ValueError('GG_DAG_PUBLIC_GENESIS')
        if len(pack(bundle))>256*1024 or bundle['schema'] not in ('gg.parallel-dag.public-genesis.v1','gg.parallel-dag.public-genesis.v2'):raise ValueError('GG_DAG_PUBLIC_GENESIS')
        lan_mode=bundle['schema']=='gg.parallel-dag.public-genesis.v2'
        genesis=bundle['genesis'];accounts=bundle['accounts']
        public_count=len(genesis.get('producers',[])) if isinstance(genesis,dict) and isinstance(genesis.get('producers'),list) else -1
        expected={'schema','chain_id','producers','precheck_root','account_count','allocation_atomic'}
        if lan_mode:expected.add('test_mode')
        if (not isinstance(genesis,dict) or set(genesis)!=expected or genesis.get('schema')!=('gg.parallel-dag.genesis.v2' if lan_mode else 'gg.parallel-dag.genesis.v1')
                or not isinstance(genesis.get('chain_id'),str) or not re.fullmatch(r'ggdag:[0-9a-f]{24}',genesis['chain_id'])
                or genesis.get('account_count')!=(public_count if lan_mode else ACCOUNT_COUNT) or type(genesis.get('account_count')) is not int
                or lan_mode and genesis.get('test_mode')!='PRODUCER_OWNED_NONFINANCIAL'
                or genesis.get('allocation_atomic')!=str(INITIAL_BALANCE) or not _hash(genesis.get('precheck_root'))
                or bundle.get('genesis_hash')!=digest(genesis)):raise ValueError('GG_DAG_PUBLIC_GENESIS')
        public=genesis.get('producers')
        if (not isinstance(public,list) or not 1<=len(public)<=MAX_PRODUCERS or any(not _hash(value) for value in public)
                or len(set(public))!=len(public)):raise ValueError('GG_DAG_PUBLIC_PRODUCERS')
        if (not isinstance(accounts,list) or len(accounts)!=(len(public) if lan_mode else ACCOUNT_COUNT) or any(not _hash(value) for value in accounts)
                or accounts!=sorted(accounts) or len(set(accounts))!=len(accounts) or lan_mode and accounts!=sorted(public)):raise ValueError('GG_DAG_PUBLIC_ACCOUNTS')
        _integer(bundle['started_at_ns'],1,time.time_ns()+5_000_000_000,'GG_DAG_PUBLIC_TIME')
        node=cls(len(public))
        with node._lock:
            node._chain=genesis['chain_id'];node._started=time.monotonic();node._started_ns=bundle['started_at_ns']
            node._lan_test_mode=lan_mode;node._lan_checkpoint=genesis['precheck_root']
            node._can_produce=False;node._producer_keys=[None]*len(public);node._producer_public=list(public)
            node._account_keys={};node._addresses=list(accounts)
            node._preview_state={address:{'balance_atomic':str(INITIAL_BALANCE),'nonce':0} for address in accounts}
            node._genesis_state=deepcopy(node._preview_state);node._roots=OrderedDict();node._set_root()
            if node._preview_root!=genesis['precheck_root']:raise ValueError('GG_DAG_PUBLIC_ROOT')
            identifier=bundle['genesis_hash']
            node._records=OrderedDict({identifier:{'body':deepcopy(genesis),'hash':identifier,'rank':0,
                'timestamp':bundle['started_at_ns']/1e9,'parents':[],'producer_index':-1,'producer_sequence':0,
                'transaction_count':0,'signature_verified':False,'wire':b'','admission_index':0}})
            node._frontier={identifier};node._recent_hashes=deque([identifier],maxlen=GRAPH_BLOCKS)
            node._max_rank=0;node._highest_hash=identifier;node._producer_sequences=set();node._next_sequences=[0]*len(public)
            node._resolved=set();node._executed=set();node._stored_bytes=0;node._wave_count=0;node._cursor=0
            node._last_wave={};node._preview_counts={'accepted':0,'conflicts':0,'duplicates':0}
            node._stats={'attempts':0,'accepted':0,'rejected':0,'duplicates':0,'signature_checks':0,'charged_bytes':0,'transactions_validated':0}
            node._peer_bytes=[0]*len(public);node._first_admission=None;node._last_admission=None
            node._producer_stats=[{'index':index,'proposals':0,'transactions':0,'last_created_at_ns':None,
                'last_created_at':None,'last_admitted_at':None,'configured_interval_ms':None,'stale_prechecks':0} for index in range(len(public))]
            node._active=True;node._live.update(state='PAUSED',producer_count=len(public))
            node._event('PUBLIC_GENESIS_IMPORTED','Nyckellös lokal verifierare · uttryckligen betrodd offentlig testsession')
        return node

    def capacity_limits(self):
        with self._lock:
            return dict(self._capacity or {'transactions_per_block':MAX_TX_PER_BLOCK,
                'block_bytes':MAX_BLOCK_BYTES,'session_bytes':MAX_SESSION_BYTES,
                'peer_bytes':MAX_SESSION_BYTES//self._producer_count})

    def stored_wire_bytes(self):
        with self._lock:return self._stored_bytes

    def configure_lan_capacity(self,*,transactions_per_block=LAN_MAX_TX_PER_BLOCK,
                               block_bytes=LAN_MAX_BLOCK_BYTES,session_bytes=LAN_MAX_SESSION_BYTES):
        """An explicit RAM-workload envelope; legacy/manual limits stay intact."""
        _integer(transactions_per_block,1,LAN_MAX_TX_PER_BLOCK,'GG_DAG_TX_LIMIT')
        _integer(block_bytes,1,LAN_MAX_BLOCK_BYTES,'GG_DAG_WIRE_SIZE')
        _integer(session_bytes,block_bytes,LAN_MAX_SESSION_BYTES,'GG_DAG_SESSION_CREDIT')
        with self._lock:
            if not self._active or not self._lan_test_mode:raise ValueError('GG_DAG_LAN_TEST_MODE_REQUIRED')
            if self._lan_work_count:raise ValueError('GG_DAG_RESOURCE_BUSY')
            if self._stored_bytes>session_bytes:raise ValueError('GG_DAG_RESOURCE_MEMORY')
            self._capacity={'transactions_per_block':transactions_per_block,'block_bytes':block_bytes,
                'session_bytes':session_bytes,'peer_bytes':session_bytes}
            return dict(self._capacity)

    def _lan_producer_lock(self,producer):
        with self._lock:
            _integer(producer,0,self._producer_count-1,'GG_DAG_PRODUCER')
            return self._lan_producer_locks.setdefault(producer,threading.RLock())

    @contextmanager
    def _lan_work(self):
        with self._lock:self._lan_work_count+=1
        try:yield
        finally:
            with self._lock:self._lan_work_count-=1

    def attach_local_producers(self,keys):
        """Attach only caller-owned RAM signers matching this public genesis."""
        with self._lock:
            if not self._active or self._live.get('enabled'):raise ValueError('GG_DAG_LOCAL_SIGNER_STATE')
            if not isinstance(keys,dict) or not 1<=len(keys)<=self._producer_count:raise ValueError('GG_DAG_LOCAL_SIGNERS')
            checked={}
            for index,key in keys.items():
                _integer(index,0,self._producer_count-1,'GG_DAG_PRODUCER')
                try:matches=key.pubkey().hex()==self._producer_public[index]
                except (AttributeError,TypeError):matches=False
                if not matches:raise ValueError('GG_DAG_LOCAL_SIGNER_IDENTITY')
                checked[index]=key
            self._producer_keys=[checked.get(index) for index in range(self._producer_count)]
            self._can_produce=True
            self._live.update(mode='ASYNC_INDEPENDENT_PRODUCERS',local_producer_indices=sorted(checked),
                local_worker_count=len(checked),active_workers=0)

    def has_proposal(self,identifier):
        with self._lock:return _hash(identifier) and identifier in getattr(self,'_records',{})

    def public_proposal(self,identifier):
        if not _hash(identifier):raise ValueError('GG_DAG_PROPOSAL_HASH')
        with self._lock:
            row=getattr(self,'_records',{}).get(identifier)
            return row['wire'] if row and row['rank'] else None

    def public_proposals(self,after=0,limit=8):
        _integer(after,0,MAX_RECORDS,'GG_DAG_PROPOSAL_CURSOR');_integer(limit,1,8,'GG_DAG_PROPOSAL_PAGE')
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            records=[]
            for row in self._records.values():
                if row['admission_index']>after:
                    records.append({'admission_index':row['admission_index'],'hash':row['hash'],'wire':row['wire']})
                    if len(records)>=limit:break
            return {'records':records,'cursor':records[-1]['admission_index'] if records else after,'tip':self._stats['accepted']}

    def inspect_empty_proposal(self,raw):
        """Check signed empty wire data before a bounded orphan buffer holds it."""
        if self._lan_test_mode and self._capacity is not None:
            with self._lan_work():body,identifier,producer=self._decode_large_lan(raw)
            return {'hash':identifier,'producer_index':producer,'parents':list(body['parents'])}
        if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BLOCK_BYTES:raise ValueError('GG_DAG_WIRE_SIZE')
        try:value=json.loads(raw)
        except (ValueError,UnicodeError):raise ValueError('GG_DAG_WIRE_JSON') from None
        if not isinstance(value,dict) or set(value)!={'body','signature'} or pack(value)!=raw:raise ValueError('GG_DAG_WIRE_CANONICAL')
        body=value['body']
        expected={'schema','chain_id','producer_index','sequence','rank','parents','precheck_root','transactions','payload_root','created_at_ns'}
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            if not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.parallel-dag.block.v1' or body.get('chain_id')!=self._chain:raise ValueError('GG_DAG_BLOCK_DOMAIN')
            producer=_integer(body['producer_index'],0,self._producer_count-1,'GG_DAG_PRODUCER')
            _integer(body['sequence'],1,MAX_ATTEMPTS,'GG_DAG_SEQUENCE');_integer(body['rank'],1,MAX_RECORDS,'GG_DAG_RANK')
            _integer(body['created_at_ns'],self._started_ns-1_000_000_000,time.time_ns()+5_000_000_000,'GG_DAG_TIMESTAMP')
            parents=body['parents']
            if not isinstance(parents,list) or not 1<=len(parents)<=MAX_PARENTS or any(not _hash(parent) for parent in parents) or len(set(parents))!=len(parents):raise ValueError('GG_DAG_PARENTS')
            transactions=body['transactions']
            if not self._lan_test_mode and transactions!=[]:raise ValueError('GG_DAG_LAN_TRANSACTIONS_DISABLED')
            if not isinstance(transactions,list) or len(transactions)>MAX_TX_PER_BLOCK:raise ValueError('GG_DAG_TX_LIMIT')
            root=self._lan_checkpoint if self._lan_test_mode else next(iter(self._roots))
            if body['precheck_root']!=root or body['payload_root']!=_tree(transactions,b'GG-DAG-PAYLOAD-v1\0')[-1][0]:raise ValueError('GG_DAG_LAN_ROOT')
            if not isinstance(value['signature'],str) or not _SIGNATURE.fullmatch(value['signature']):raise ValueError('GG_DAG_BLOCK_SIGNATURE')
            _verify(self._producer_public[producer],b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body),value['signature'])
            return {'hash':digest(body,b'GG-DAG-BLOCK-v1\0'),'producer_index':producer,'parents':list(parents)}

    def _start_session(self,producer_count):
        _integer(producer_count,1,MAX_PRODUCERS,'GG_DAG_PRODUCER_COUNT')
        with self._lock:
            if self._lan_work_count:raise ValueError('GG_DAG_RESOURCE_BUSY')
            if self._active:
                if self._producer_count!=producer_count:raise ValueError('GG_DAG_PRODUCER_COUNT_SESSION')
                return self.snapshot()
            self._producer_count=producer_count
            self._lan_test_mode=False;self._lan_fault='';self._lan_heads={};self._lan_counts={};self._capacity=None
            self._chain='ggdag:'+secrets.token_hex(12);self._started=time.monotonic();self._started_ns=time.time_ns()
            self._can_produce=True
            self._producer_keys=[Keypair() for _ in range(producer_count)]
            self._producer_public=[key.pubkey().hex() for key in self._producer_keys]
            keys=[Keypair() for _ in range(ACCOUNT_COUNT)]
            self._account_keys={key.pubkey().hex():key for key in keys};self._addresses=sorted(self._account_keys)
            self._preview_state={address:{'balance_atomic':str(INITIAL_BALANCE),'nonce':0} for address in self._addresses}
            self._genesis_state=deepcopy(self._preview_state)
            self._roots=OrderedDict();self._set_root()
            self._records=OrderedDict();self._frontier=set();self._producer_sequences=set();self._next_sequences=[0]*producer_count
            self._recent_hashes=deque(maxlen=GRAPH_BLOCKS);self._max_rank=0;self._highest_hash=''
            self._resolved=set();self._executed=set();self._stored_bytes=0;self._wave_count=0;self._cursor=0
            self._last_wave={};self._preview_counts={'accepted':0,'conflicts':0,'duplicates':0}
            self._measurements.clear();self._rate_samples.clear();self._relay_measurement=None
            self._live.update(state='PAUSED',enabled=False,stop_reason='',waves_completed=0,in_flight=False,
                producer_count=producer_count,active_workers=0,jobs_completed=0,mode='WAVE_COMPATIBILITY')
            self._stats={'attempts':0,'accepted':0,'rejected':0,'duplicates':0,'signature_checks':0,'charged_bytes':0,'transactions_validated':0}
            self._peer_bytes=[0]*producer_count;self._first_admission=None;self._last_admission=None
            self._producer_stats=[{'index':index,'proposals':0,'transactions':0,'last_created_at_ns':None,
                'last_created_at':None,'last_admitted_at':None,'configured_interval_ms':None,'stale_prechecks':0} for index in range(producer_count)]
            genesis={'schema':'gg.parallel-dag.genesis.v1','chain_id':self._chain,'producers':list(self._producer_public),'precheck_root':self._preview_root,'account_count':ACCOUNT_COUNT,'allocation_atomic':str(INITIAL_BALANCE)}
            identifier=digest(genesis)
            self._records[identifier]={'body':genesis,'hash':identifier,'rank':0,'timestamp':time.time(),'parents':[],
                'producer_index':-1,'producer_sequence':0,'transaction_count':0,'signature_verified':False,'wire':b'','admission_index':0}
            self._recent_hashes.append(identifier);self._highest_hash=identifier
            self._frontier.add(identifier);self._active=True;self._events.clear();self._event('STARTED',str(producer_count)+' lokala producenter · endast disponibla testidentiteter')
            return self.snapshot()

    def _event(self,kind,message):self._events.appendleft({'ts':time.time(),'kind':kind,'message':message})

    def _set_root(self):
        leaves=[{'address':address,**self._preview_state[address]} for address in sorted(self._preview_state)]
        levels=_tree(leaves,b'GG-DAG-ACCOUNT-v1\0');root=levels[-1][0]
        self._roots[root]={'state':deepcopy(self._preview_state),'leaves':leaves,'levels':levels,'indices':{leaf['address']:i for i,leaf in enumerate(leaves)}}
        self._roots.move_to_end(root)
        while len(self._roots)>MAX_ROOTS:self._roots.popitem(last=False)
        self._preview_root=root

    def _charge(self,peer,size):
        self._stats['attempts']+=1
        # Invalid traffic consumes the same finite session work/byte allowance.
        limits=self.capacity_limits()
        charge=min(max(1,size),limits['block_bytes']+1)
        self._stats['charged_bytes']+=charge
        if self._stats['attempts']>MAX_ATTEMPTS or self._stats['charged_bytes']>limits['session_bytes']:raise ValueError('GG_DAG_SESSION_CREDIT')
        _integer(peer,0,self._producer_count-1,'GG_DAG_UNKNOWN_PEER')
        self._peer_bytes[peer]+=charge
        if self._peer_bytes[peer]>limits['peer_bytes']:raise ValueError('GG_DAG_PEER_CREDIT')

    def _validate_transaction(self,transaction,root):
        if not isinstance(transaction,dict) or set(transaction)!={'body','signature','witness'}:raise ValueError('GG_DAG_TX_SCHEMA')
        body=transaction['body'];signature=transaction['signature']
        expected={'schema','chain_id','from','to','amount_atomic','nonce','precheck_root'}
        if not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.parallel-dag.tx.v1' or body.get('chain_id')!=self._chain or body.get('precheck_root')!=root:raise ValueError('GG_DAG_TX_DOMAIN')
        source,target=body['from'],body['to'];state=self._roots[root]['state']
        if not isinstance(source,str) or not isinstance(target,str) or source not in state or target not in state or source==target:raise ValueError('GG_DAG_TX_ACCOUNT')
        amount=body['amount_atomic']
        if not isinstance(amount,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',amount) or int(amount)>2**64-1:raise ValueError('GG_DAG_TX_AMOUNT')
        _integer(body['nonce'],0,2**32-1,'GG_DAG_TX_NONCE')
        if body['nonce']!=state[source]['nonce'] or int(amount)>int(state[source]['balance_atomic']):raise ValueError('GG_DAG_TX_PRECHECK')
        proof=transaction['witness'];expected_leaf={'address':source,**state[source]}
        if not isinstance(proof,dict) or proof.get('leaf')!=expected_leaf or not _verify_proof(root,proof):raise ValueError('GG_DAG_TX_WITNESS')
        if not isinstance(signature,str) or not _SIGNATURE.fullmatch(signature):raise ValueError('GG_DAG_TX_SIGNATURE')
        self._stats['signature_checks']+=1
        _verify(source,b'GG-DAG-TX-SIGN-v1\0'+pack(body),signature)

    def _validate_lan_transactions(self,body,check=None):
        """Causal author-owned test debits, independent of other arrival order.

        Incoming credit is deliberately never spend authorization. The immutable
        initial allocation bounds every author's whole sequence; this is a
        disposable test workload, not a financial or fork-consensus rule.
        """
        producer=body['producer_index'];sequence=body['sequence']
        previous=self._lan_heads.get(producer)
        expected_sequence=self._next_sequences[producer]+1
        if sequence!=expected_sequence:raise ValueError('GG_DAG_LAN_CAUSAL_SEQUENCE')
        if previous is not None and previous not in body['parents']:raise ValueError('GG_DAG_LAN_OWN_PARENT')
        nonce=self._lan_counts.get(producer,0);source=self._producer_public[producer]
        for transaction in body['transactions']:
            if check is not None:check()
            if not isinstance(transaction,dict) or set(transaction)!={'body','signature'}:raise ValueError('GG_DAG_TX_SCHEMA')
            tx=transaction['body'];signature=transaction['signature']
            if (not isinstance(tx,dict) or set(tx)!={'schema','chain_id','from','to','amount_atomic','nonce','precheck_root'}
                    or tx.get('schema')!='gg.parallel-dag.tx.v2' or tx.get('chain_id')!=self._chain
                    or tx.get('precheck_root')!=self._lan_checkpoint):raise ValueError('GG_DAG_TX_DOMAIN')
            if (not isinstance(tx['from'],str) or not isinstance(tx['to'],str)
                    or tx['from']!=source or tx['to'] not in self._genesis_state or tx['to']==source):raise ValueError('GG_DAG_TX_ACCOUNT')
            if tx['amount_atomic']!='1':raise ValueError('GG_DAG_TX_AMOUNT')
            if type(tx['nonce']) is not int or tx['nonce']!=nonce:raise ValueError('GG_DAG_TX_NONCE')
            if nonce>=INITIAL_BALANCE:raise ValueError('GG_DAG_PRODUCER_BALANCE')
            if not isinstance(signature,str) or not _SIGNATURE.fullmatch(signature):raise ValueError('GG_DAG_TX_SIGNATURE')
            self._stats['signature_checks']+=1
            _verify(source,b'GG-DAG-LAN-TEST-TX-SIGN-v2\0'+pack(tx),signature);nonce+=1

    def preflight_lan_test_block(self,transactions,max_wire):
        """Exact worst-width envelope bound, before any worker or signing starts."""
        limits=self.capacity_limits()
        _integer(transactions,0,limits['transactions_per_block'],'GG_DAG_TX_LIMIT')
        _integer(max_wire,1,limits['block_bytes'],'GG_DAG_WIRE_SIZE')
        with self._lock:
            if not self._active or not self._lan_test_mode:raise ValueError('GG_DAG_LAN_TEST_MODE_REQUIRED')
            tx={'schema':'gg.parallel-dag.tx.v2','chain_id':self._chain,'from':'f'*64,'to':'e'*64,
                'amount_atomic':'1','nonce':2**32-1,'precheck_root':self._lan_checkpoint}
            body={'schema':'gg.parallel-dag.block.v1','chain_id':self._chain,'producer_index':MAX_PRODUCERS-1,
                'sequence':MAX_ATTEMPTS,'rank':MAX_RECORDS,'parents':['f'*64]*MAX_PARENTS,
                'precheck_root':self._lan_checkpoint,'transactions':[],
                'payload_root':'f'*64,'created_at_ns':2**63-1}
            size=len(pack({'body':body,'signature':'f'*128}))
            if transactions:
                size+=transactions*len(pack({'body':tx,'signature':'f'*128}))+transactions-1
            if size>max_wire:raise ValueError('GG_DAG_LAN_WIRE_PROFILE_LIMIT')
            return size

    def produce_lan_test_block(self,producer,transactions,max_wire=MAX_BLOCK_BYTES,*,check=None):
        """Sign and admit one real owned proposal; no receipt-circle side path."""
        if self._lan_test_mode and self._capacity is not None:
            with self._lan_work():return self._produce_large_lan(producer,transactions,max_wire,check=check)
        self.preflight_lan_test_block(transactions,max_wire)
        with self._lock:
            began=time.perf_counter()
            if check is not None:check()
            if self._lan_fault:raise ValueError(self._lan_fault)
            _integer(producer,0,self._producer_count-1,'GG_DAG_PRODUCER')
            key=self._producer_keys[producer]
            if key is None:raise ValueError('GG_DAG_PRODUCER_NOT_OWNED')
            previous=self._lan_heads.get(producer);parents=[] if previous is None else [previous]
            for identifier in sorted(self._frontier):
                if identifier not in parents:parents.append(identifier)
                if len(parents)>=MAX_PARENTS:break
            if not parents:parents=[next(iter(self._records))]
            nonce=self._lan_counts.get(producer,0);items=[]
            for offset in range(transactions):
                if check is not None:check()
                tx={'schema':'gg.parallel-dag.tx.v2','chain_id':self._chain,'from':self._producer_public[producer],
                    'to':self._producer_public[(producer+1)%self._producer_count],'amount_atomic':'1',
                    'nonce':nonce+offset,'precheck_root':self._lan_checkpoint}
                items.append({'body':tx,'signature':key.sign_message(b'GG-DAG-LAN-TEST-TX-SIGN-v2\0'+pack(tx)).hex()})
            body={'schema':'gg.parallel-dag.block.v1','chain_id':self._chain,'producer_index':producer,
                'sequence':self._next_sequences[producer]+1,'rank':1+max(self._records[parent]['rank'] for parent in parents),
                'parents':parents,'precheck_root':self._lan_checkpoint,'transactions':items,
                'payload_root':_tree(items,b'GG-DAG-PAYLOAD-v1\0')[-1][0],'created_at_ns':time.time_ns()}
            raw=pack({'body':body,'signature':key.sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body)).hex()})
            producer_ms=(time.perf_counter()-began)*1000
            if len(raw)>max_wire:raise ValueError('GG_DAG_LAN_WIRE_PROFILE_LIMIT')
            if check is not None:check()
            validation_began=time.perf_counter()
            result=self.admit(raw,producer,_check=check);self.reconcile();self._wave_count+=1
            self._last_wave={'kind':'lan_test_proposal','blocks':1,'transactions':transactions,'producer_index':producer,
                'parents':len(parents),'producer_ms':round(producer_ms,3),
                'validation_ms':round((time.perf_counter()-validation_began)*1000,3),
                'total_ms':round((time.perf_counter()-began)*1000,3),'workers_used':1,'parallel':False,
                'worker_overlap_ms':0,'sequence':self._wave_count,'timestamp':time.time()}
            self._measurements.append(dict(self._last_wave))
            self._event('PROPOSAL_ADMITTED','LAN DAG test-TX '+str(transactions)+'; independently signed and validated; no finality')
            return {**result,'wire':raw,'transactions':transactions}

    def lan_test_accounts(self):
        """Public test-account observations, never private signers or finality."""
        with self._lock:
            if not self._active or not self._lan_test_mode:return []
            return [{'producer_index':index,'address':public,
                     'balance_atomic':self._preview_state[public]['balance_atomic'],
                     'nonce':self._preview_state[public]['nonce'],
                     'basis':'LOCAL_TEST_PREVIEW_NOT_CANONICAL','canonical':False}
                    for index,public in enumerate(self._producer_public)]

    def lan_evidence(self):
        """A public observation of the entire admitted set, never a certificate."""
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            self.reconcile()
            return {'chain_id':self._chain,'blocks':self._stats['accepted'],'transactions':self._stats['transactions_validated'],
                'blockset_digest':digest(sorted(self._records),b'GG-DAG-BLOCKSET-v1\0'),
                'state_root':self._preview_root,'protocol_fault':self._lan_fault,
                'producer_blocks':[row['proposals'] for row in self._producer_stats],
                'producer_transactions':[row['transactions'] for row in self._producer_stats],
                'canonical':False,'finality':FINALITY}

    def workload_observation(self):
        """Last actual jobs; elapsed/CPU work samples are not capacity claims."""
        with self._lock:
            local=None;last=self._last_wave
            if type(last.get('transactions')) is int and last.get('timestamp'):
                local={'transactions':last['transactions'],'sign_ms':last.get('producer_ms'),
                    'verify_ms':last.get('validation_ms'),'wall_ms':last.get('total_ms'),
                    'age_seconds':round(max(0,time.time()-last['timestamp']),3)}
            relay=deepcopy(self._relay_measurement)
            if relay is not None:
                relay['age_seconds']=round(max(0,time.monotonic()-relay.pop('observed_monotonic')),3)
            return {'basis':'RECENT_JOBS_NOT_CAPACITY','local':local,'relay':relay}

    def _decode_large_lan(self,raw,*,count_signature=False):
        """Validate the same canonical envelope outside the shared state lock."""
        limits=self.capacity_limits()
        if not isinstance(raw,bytes) or not 1<=len(raw)<=limits['block_bytes']:raise ValueError('GG_DAG_WIRE_SIZE')
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('GG_DAG_DUPLICATE_JSON_KEY')
                result[key]=value
            return result
        try:envelope=json.loads(raw,object_pairs_hook=unique)
        except (ValueError,UnicodeError,RecursionError):raise ValueError('GG_DAG_WIRE_JSON') from None
        if not isinstance(envelope,dict) or set(envelope)!={'body','signature'} or pack(envelope)!=raw:raise ValueError('GG_DAG_WIRE_CANONICAL')
        body=envelope['body'];signature=envelope['signature']
        expected={'schema','chain_id','producer_index','sequence','rank','parents','precheck_root','transactions','payload_root','created_at_ns'}
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            if not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.parallel-dag.block.v1' or body.get('chain_id')!=self._chain:raise ValueError('GG_DAG_BLOCK_DOMAIN')
            producer=_integer(body['producer_index'],0,self._producer_count-1,'GG_DAG_PRODUCER')
            public=self._producer_public[producer];checkpoint=self._lan_checkpoint;started=self._started_ns
        _integer(body['sequence'],1,MAX_ATTEMPTS,'GG_DAG_SEQUENCE');_integer(body['rank'],1,MAX_RECORDS,'GG_DAG_RANK')
        _integer(body['created_at_ns'],started-1_000_000_000,time.time_ns()+5_000_000_000,'GG_DAG_TIMESTAMP')
        parents=body['parents']
        if not isinstance(parents,list) or not 1<=len(parents)<=MAX_PARENTS or any(not _hash(parent) for parent in parents) or len(set(parents))!=len(parents):raise ValueError('GG_DAG_PARENTS')
        transactions=body['transactions']
        if not isinstance(transactions,list) or len(transactions)>limits['transactions_per_block']:raise ValueError('GG_DAG_TX_LIMIT')
        if body['precheck_root']!=checkpoint:raise ValueError('GG_DAG_PRECHECK_ROOT')
        if not _hash(body['payload_root']) or _tree(transactions,b'GG-DAG-PAYLOAD-v1\0')[-1][0]!=body['payload_root']:raise ValueError('GG_DAG_PAYLOAD_ROOT')
        if not isinstance(signature,str) or not _SIGNATURE.fullmatch(signature):raise ValueError('GG_DAG_BLOCK_SIGNATURE')
        if count_signature:
            with self._lock:self._stats['signature_checks']+=1
        _verify(public,b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body),signature)
        return body,digest(body,b'GG-DAG-BLOCK-v1\0'),producer

    def _admit_large_lan(self,raw,peer,*,relayed=False,check=None):
        """Serialize each author chain, not unrelated cryptographic work.

        Every signature is verified. Only the final state transition holds the
        shared lock; control/status reads remain available during large blocks.
        """
        began=time.monotonic()
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
        try:
            with self._lock:self._charge(peer,len(raw) if isinstance(raw,bytes) else 1)
            if check is not None:check()
            body,identifier,producer=self._decode_large_lan(raw,count_signature=True)
            if not relayed and producer!=peer:raise ValueError('GG_DAG_PRODUCER_PEER')
            with self._lan_producer_lock(producer):
                sequence=body['sequence'];parents=body['parents'];transactions=body['transactions']
                with self._lock:
                    if not self._active or body['chain_id']!=self._chain:raise ValueError('GG_DAG_NOT_RUNNING')
                    if identifier in self._records:
                        if self._records[identifier]['wire']!=raw:raise ValueError('GG_DAG_DUPLICATE_CHANGED')
                        self._stats['duplicates']+=1;return {'state':'DUPLICATE','hash':identifier,'finality':FINALITY}
                    if len(self._records)>=MAX_RECORDS:raise ValueError('GG_DAG_RECORD_LIMIT')
                    if any(parent not in self._records for parent in parents):raise ValueError('GG_DAG_UNKNOWN_PARENT')
                    if body['rank']!=1+max(self._records[parent]['rank'] for parent in parents):raise ValueError('GG_DAG_RANK')
                    if (producer,sequence) in self._producer_sequences:
                        self._lan_fault='GG_DAG_PRODUCER_EQUIVOCATION';raise ValueError(self._lan_fault)
                    previous=self._lan_heads.get(producer);expected=self._next_sequences[producer]+1
                    nonce=self._lan_counts.get(producer,0);initial_nonce=nonce
                    source=self._producer_public[producer];accounts=frozenset(self._genesis_state)
                    checkpoint=self._lan_checkpoint;chain=self._chain
                if sequence!=expected:raise ValueError('GG_DAG_LAN_CAUSAL_SEQUENCE')
                if previous is not None and previous not in parents:raise ValueError('GG_DAG_LAN_OWN_PARENT')
                identifiers=set()
                for transaction in transactions:
                    if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
                    if check is not None:check()
                    if not isinstance(transaction,dict) or set(transaction)!={'body','signature'}:raise ValueError('GG_DAG_TX_SCHEMA')
                    tx=transaction['body'];signature=transaction['signature']
                    if (not isinstance(tx,dict) or set(tx)!={'schema','chain_id','from','to','amount_atomic','nonce','precheck_root'}
                            or tx.get('schema')!='gg.parallel-dag.tx.v2' or tx.get('chain_id')!=chain or tx.get('precheck_root')!=checkpoint):raise ValueError('GG_DAG_TX_DOMAIN')
                    if not isinstance(tx['from'],str) or not isinstance(tx['to'],str) or tx['from']!=source or tx['to'] not in accounts or tx['to']==source:raise ValueError('GG_DAG_TX_ACCOUNT')
                    if tx['amount_atomic']!='1':raise ValueError('GG_DAG_TX_AMOUNT')
                    if type(tx['nonce']) is not int or tx['nonce']!=nonce:raise ValueError('GG_DAG_TX_NONCE')
                    if nonce>=INITIAL_BALANCE:raise ValueError('GG_DAG_PRODUCER_BALANCE')
                    if not isinstance(signature,str) or not _SIGNATURE.fullmatch(signature):raise ValueError('GG_DAG_TX_SIGNATURE')
                    with self._lock:self._stats['signature_checks']+=1
                    _verify(source,b'GG-DAG-LAN-TEST-TX-SIGN-v2\0'+pack(tx),signature)
                    tx_id=digest(tx,b'GG-DAG-TX-ID-v1\0')
                    if tx_id in identifiers:raise ValueError('GG_DAG_DUPLICATE_TX_IN_BLOCK')
                    identifiers.add(tx_id);nonce+=1
                if check is not None:check()
                with self._lock:
                    if not self._active or self._chain!=chain:raise ValueError('GG_DAG_NOT_RUNNING')
                    if self._next_sequences[producer]+1!=sequence or self._lan_counts.get(producer,0)!=initial_nonce or self._lan_heads.get(producer)!=previous:raise ValueError('GG_DAG_LAN_CAUSAL_SEQUENCE')
                    if self._stored_bytes+len(raw)>self.capacity_limits()['session_bytes']:raise ValueError('GG_DAG_STORAGE_LIMIT')
                    rank=body['rank'];created=body['created_at_ns']
                    self._records[identifier]={'body':body,'hash':identifier,'rank':rank,'timestamp':created/1e9,
                        'parents':list(parents),'producer_index':producer,'producer_sequence':sequence,
                        'transaction_count':len(transactions),'signature_verified':True,'wire':raw,'admission_index':self._stats['accepted']+1}
                    self._recent_hashes.append(identifier)
                    if rank>=self._max_rank:self._max_rank=rank;self._highest_hash=identifier
                    self._producer_sequences.add((producer,sequence));self._frontier.difference_update(parents);self._frontier.add(identifier)
                    self._next_sequences[producer]=sequence;self._lan_heads[producer]=identifier;self._lan_counts[producer]=nonce
                    self._stored_bytes+=len(raw);self._stats['accepted']+=1;self._stats['transactions_validated']+=len(transactions)
                    observed=time.monotonic();self._first_admission=self._first_admission or began;self._last_admission=observed
                    self._rate_samples.append((observed,len(transactions),producer))
                    self._producer_stats[producer].update(proposals=self._producer_stats[producer]['proposals']+1,
                        transactions=self._producer_stats[producer]['transactions']+len(transactions),
                        last_created_at_ns=str(created),last_created_at=created/1e9,last_admitted_at=time.time())
                    return {'state':'ADMITTED_UNFINALIZED','hash':identifier,'rank':rank,'finality':FINALITY}
        except Exception:
            with self._lock:self._stats['rejected']+=1
            raise

    def _produce_large_lan(self,producer,transactions,max_wire,*,check=None):
        self.preflight_lan_test_block(transactions,max_wire)
        with self._lan_producer_lock(producer):
            began=time.perf_counter()
            if check is not None:check()
            with self._lock:
                if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
                if self._lan_fault:raise ValueError(self._lan_fault)
                key=self._producer_keys[producer]
                if key is None:raise ValueError('GG_DAG_PRODUCER_NOT_OWNED')
                previous=self._lan_heads.get(producer);parents=[] if previous is None else [previous]
                for identifier in sorted(self._frontier):
                    if identifier not in parents:parents.append(identifier)
                    if len(parents)>=MAX_PARENTS:break
                if not parents:parents=[next(iter(self._records))]
                nonce=self._lan_counts.get(producer,0);chain=self._chain;checkpoint=self._lan_checkpoint
                source=self._producer_public[producer];target=self._producer_public[(producer+1)%self._producer_count]
                sequence=self._next_sequences[producer]+1;rank=1+max(self._records[parent]['rank'] for parent in parents)
            items=[]
            for offset in range(transactions):
                if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
                if check is not None:check()
                tx={'schema':'gg.parallel-dag.tx.v2','chain_id':chain,'from':source,'to':target,
                    'amount_atomic':'1','nonce':nonce+offset,'precheck_root':checkpoint}
                items.append({'body':tx,'signature':key.sign_message(b'GG-DAG-LAN-TEST-TX-SIGN-v2\0'+pack(tx)).hex()})
            body={'schema':'gg.parallel-dag.block.v1','chain_id':chain,'producer_index':producer,'sequence':sequence,
                'rank':rank,'parents':parents,'precheck_root':checkpoint,'transactions':items,
                'payload_root':_tree(items,b'GG-DAG-PAYLOAD-v1\0')[-1][0],'created_at_ns':time.time_ns()}
            raw=pack({'body':body,'signature':key.sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body)).hex()})
            producer_ms=(time.perf_counter()-began)*1000
            if len(raw)>max_wire:raise ValueError('GG_DAG_LAN_WIRE_PROFILE_LIMIT')
            if check is not None:check()
            validation_began=time.perf_counter();result=self.admit(raw,producer,_check=check);self.reconcile()
            with self._lock:
                self._wave_count+=1
                self._last_wave={'kind':'lan_test_proposal','blocks':1,'transactions':transactions,'producer_index':producer,
                    'parents':len(parents),'producer_ms':round(producer_ms,3),'validation_ms':round((time.perf_counter()-validation_began)*1000,3),
                    'total_ms':round((time.perf_counter()-began)*1000,3),'workers_used':1,'parallel':False,'worker_overlap_ms':0,
                    'sequence':self._wave_count,'timestamp':time.time()}
                self._measurements.append(dict(self._last_wave))
                self._event('PROPOSAL_ADMITTED','LAN DAG test-TX '+str(transactions)+'; independently signed and validated; no finality')
            return {**result,'wire':raw,'transactions':transactions}

    def admit(self,raw,peer,*,_relayed=False,_check=None):
        """Admit a complete canonical wire proposal; no execution/finality here."""
        if self._lan_test_mode and self._capacity is not None:
            with self._lan_work():return self._admit_large_lan(raw,peer,relayed=_relayed,check=_check)
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            admission_started=time.monotonic()
            size=len(raw) if isinstance(raw,bytes) else 1
            try:
                self._charge(peer,size)
                if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BLOCK_BYTES:raise ValueError('GG_DAG_WIRE_SIZE')
                if len(self._records)>=MAX_RECORDS:raise ValueError('GG_DAG_RECORD_LIMIT')
                def unique(pairs):
                    result={}
                    for key,value in pairs:
                        if key in result:raise ValueError('GG_DAG_DUPLICATE_JSON_KEY')
                        result[key]=value
                    return result
                try:envelope=json.loads(raw,object_pairs_hook=unique)
                except (ValueError,UnicodeError,RecursionError):raise ValueError('GG_DAG_WIRE_JSON') from None
                if not isinstance(envelope,dict) or set(envelope)!={'body','signature'} or pack(envelope)!=raw:raise ValueError('GG_DAG_WIRE_CANONICAL')
                body=envelope['body'];signature=envelope['signature']
                expected={'schema','chain_id','producer_index','sequence','rank','parents','precheck_root','transactions','payload_root','created_at_ns'}
                if not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.parallel-dag.block.v1' or body.get('chain_id')!=self._chain:raise ValueError('GG_DAG_BLOCK_DOMAIN')
                identifier=digest(body,b'GG-DAG-BLOCK-v1\0')
                if identifier in self._records:
                    if self._records[identifier]['wire']!=raw:raise ValueError('GG_DAG_DUPLICATE_CHANGED')
                    self._stats['duplicates']+=1;return {'state':'DUPLICATE','hash':identifier,'finality':FINALITY}
                producer=_integer(body['producer_index'],0,self._producer_count-1,'GG_DAG_PRODUCER')
                if not _relayed and producer!=peer:raise ValueError('GG_DAG_PRODUCER_PEER')
                sequence=_integer(body['sequence'],1,MAX_ATTEMPTS,'GG_DAG_SEQUENCE')
                if not self._lan_test_mode and (producer,sequence) in self._producer_sequences:raise ValueError('GG_DAG_PRODUCER_EQUIVOCATION')
                parents=body['parents']
                if not isinstance(parents,list) or not 1<=len(parents)<=MAX_PARENTS or any(not _hash(parent) for parent in parents) or len(set(parents))!=len(parents):raise ValueError('GG_DAG_PARENTS')
                if any(parent not in self._records for parent in parents):raise ValueError('GG_DAG_UNKNOWN_PARENT')
                rank=_integer(body['rank'],1,MAX_RECORDS,'GG_DAG_RANK')
                if rank!=1+max(self._records[parent]['rank'] for parent in parents):raise ValueError('GG_DAG_RANK')
                created=_integer(body['created_at_ns'],self._started_ns-1_000_000_000,time.time_ns()+5_000_000_000,'GG_DAG_TIMESTAMP')
                root=body['precheck_root']
                if not _hash(root) or (root!=self._lan_checkpoint if self._lan_test_mode else root not in self._roots):raise ValueError('GG_DAG_PRECHECK_ROOT')
                transactions=body['transactions']
                if not isinstance(transactions,list) or len(transactions)>MAX_TX_PER_BLOCK:raise ValueError('GG_DAG_TX_LIMIT')
                if not _hash(body['payload_root']) or _tree(transactions,b'GG-DAG-PAYLOAD-v1\0')[-1][0]!=body['payload_root']:raise ValueError('GG_DAG_PAYLOAD_ROOT')
                if not isinstance(signature,str) or not _SIGNATURE.fullmatch(signature):raise ValueError('GG_DAG_BLOCK_SIGNATURE')
                # All bounded envelope, parent, identity and Merkle checks above
                # precede expensive signature work.
                self._stats['signature_checks']+=1
                _verify(self._producer_public[producer],b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body),signature)
                if self._lan_test_mode:
                    if (producer,sequence) in self._producer_sequences:
                        self._lan_fault='GG_DAG_PRODUCER_EQUIVOCATION';raise ValueError(self._lan_fault)
                    self._validate_lan_transactions(body,_check)
                tx_ids=set()
                for transaction in transactions:
                    if not self._lan_test_mode:self._validate_transaction(transaction,root)
                    tx_id=digest(transaction['body'],b'GG-DAG-TX-ID-v1\0')
                    if tx_id in tx_ids:raise ValueError('GG_DAG_DUPLICATE_TX_IN_BLOCK')
                    tx_ids.add(tx_id)
                if self._stored_bytes+len(raw)>MAX_SESSION_BYTES:raise ValueError('GG_DAG_STORAGE_LIMIT')
                if _check is not None:_check()
                self._records[identifier]={'body':body,'hash':identifier,'rank':rank,'timestamp':created/1e9,
                    'parents':list(parents),'producer_index':producer,'producer_sequence':sequence,
                    'transaction_count':len(transactions),'signature_verified':True,'wire':raw,
                    'admission_index':self._stats['accepted']+1}
                self._recent_hashes.append(identifier)
                if rank>=self._max_rank:self._max_rank=rank;self._highest_hash=identifier
                self._producer_sequences.add((producer,sequence));self._frontier.difference_update(parents);self._frontier.add(identifier)
                self._next_sequences[producer]=max(self._next_sequences[producer],sequence)
                if self._lan_test_mode:
                    self._lan_heads[producer]=identifier;self._lan_counts[producer]=self._lan_counts.get(producer,0)+len(transactions)
                self._stored_bytes+=len(raw);self._stats['accepted']+=1;self._stats['transactions_validated']+=len(transactions)
                observed=time.monotonic();self._first_admission=self._first_admission or admission_started;self._last_admission=observed
                self._rate_samples.append((observed,len(transactions),producer))
                self._producer_stats[producer].update(proposals=self._producer_stats[producer]['proposals']+1,
                    transactions=self._producer_stats[producer]['transactions']+len(transactions),
                    last_created_at_ns=str(created),last_created_at=created/1e9,last_admitted_at=time.time())
                return {'state':'ADMITTED_UNFINALIZED','hash':identifier,'rank':rank,'finality':FINALITY}
            except Exception:
                self._stats['rejected']+=1
                raise

    def admit_relayed(self,raw,authenticated_ingress,*,check=None):
        """A pinned transport charges its authenticated sender, not an alleged
        producer. The actual producer signature still uses the public genesis.
        This method alone is not transport authentication.
        """
        began=time.perf_counter_ns();cpu_began=time.thread_time_ns();result=None
        try:
            result=self.admit(raw,authenticated_ingress,_relayed=True,_check=check)
            return result
        finally:
            wall_ms=(time.perf_counter_ns()-began)/1e6;cpu_ms=(time.thread_time_ns()-cpu_began)/1e6
            if isinstance(result,dict) and result.get('state')=='ADMITTED_UNFINALIZED':
                with self._lock:
                    row=self._records.get(result['hash'])
                    if row is not None:
                        resolved=0<cpu_ms<=wall_ms
                        self._relay_measurement={'transactions':row['transaction_count'],
                            'wall_ms':round(wall_ms,3),'cpu_ms':round(cpu_ms,3) if resolved else None,
                            'cpu_sample_resolved':resolved,
                            'observed_monotonic':time.monotonic()}

    def _candidate(self,producer,sequence,parents,root,indices,*,_context=None):
        context=self._roots[root] if _context is None else _context['checkpoint'];transactions=[]
        chain=self._chain if _context is None else _context['chain']
        addresses=self._addresses if _context is None else _context['addresses']
        account_keys=self._account_keys if _context is None else _context['account_keys']
        producer_key=self._producer_keys[producer] if _context is None else _context['producer_key']
        if producer_key is None:raise ValueError('GG_DAG_PRODUCER_NOT_OWNED')
        for index in indices:
            source=addresses[index];target=addresses[(index+1)%ACCOUNT_COUNT]
            leaf=context['state'][source]
            body={'schema':'gg.parallel-dag.tx.v1','chain_id':chain,'from':source,'to':target,
                'amount_atomic':'1','nonce':leaf['nonce'],'precheck_root':root}
            # Producer checks its own state/witness before signing. Validators
            # independently repeat membership, signature and execution checks.
            if int(leaf['balance_atomic'])<1:raise ValueError('GG_DAG_PRODUCER_BALANCE')
            transactions.append({'body':body,'signature':account_keys[source].sign_message(b'GG-DAG-TX-SIGN-v1\0'+pack(body)).hex(),
                'witness':_proof(context['leaves'],context['levels'],context['indices'][source])})
        rank=1+max(self._records[parent]['rank'] for parent in parents) if _context is None else _context['rank']
        body={'schema':'gg.parallel-dag.block.v1','chain_id':chain,'producer_index':producer,'sequence':sequence,
            'rank':rank,'parents':list(parents),'precheck_root':root,
            'transactions':transactions,'payload_root':_tree(transactions,b'GG-DAG-PAYLOAD-v1\0')[-1][0],'created_at_ns':time.time_ns()}
        raw=pack({'body':body,'signature':producer_key.sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(body)).hex()})
        if len(raw)>MAX_BLOCK_BYTES:raise ValueError('GG_DAG_WIRE_SIZE')
        return raw

    def reconcile(self):
        """Deterministic local preview only; it never issues a finality certificate."""
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            pending=sorted((row for row in self._records.values() if row['rank'] and row['hash'] not in self._resolved),key=lambda row:(row['rank'],row['hash']))
            if not pending:return {**self._preview_counts,'state_root':self._preview_root,'canonical':False,'finality':FINALITY}
            if self._lan_test_mode:
                # Each admitted author chain is contiguous and owns its source.
                # Debits never rely on concurrent incoming credits, so integer
                # balance deltas commute across authors. Incremental replay is
                # equivalent to rank/hash replay of the same complete blockset.
                for row in pending:
                    for transaction in row['body']['transactions']:
                        tx=transaction['body'];source=self._preview_state[tx['from']];target=self._preview_state[tx['to']]
                        if source['nonce']!=tx['nonce']:raise ValueError('GG_DAG_LAN_REPLAY_NONCE')
                        source['balance_atomic']=str(int(source['balance_atomic'])-1);source['nonce']+=1
                        target['balance_atomic']=str(int(target['balance_atomic'])+1)
                    count=len(row['body']['transactions']);self._preview_counts['accepted']+=count
                    row.update(preview_accepted_count=count,preview_conflict_count=0,preview_duplicate_count=0)
                    self._resolved.add(row['hash'])
                self._set_root()
                return {**self._preview_counts,'state_root':self._preview_root,'canonical':False,'finality':FINALITY}
            # Empty signed headers cannot change transaction execution. Avoid
            # rebuilding the complete account Merkle tree for a heartbeat.
            # Parent and producer signatures were independently admitted above.
            if all(not row['body']['transactions'] for row in pending):
                for row in pending:
                    row.update(preview_accepted_count=0,preview_conflict_count=0,preview_duplicate_count=0)
                    self._resolved.add(row['hash'])
                return {**self._preview_counts,'state_root':self._preview_root,'canonical':False,'finality':FINALITY}
            # Recompute the bounded whole admitted DAG, not arrival-order
            # increments. An unfinalized preview may change when a previously
            # unseen sibling arrives; it is never treated as a money receipt.
            self._preview_state=deepcopy(self._genesis_state);self._executed.clear()
            self._preview_counts={'accepted':0,'conflicts':0,'duplicates':0}
            ordered=sorted((row for row in self._records.values() if row['rank']),key=lambda row:(row['rank'],row['hash']))
            for row in ordered:
                accepted=conflicts=duplicates=0
                for transaction in row['body']['transactions']:
                    body=transaction['body'];identifier=digest(body,b'GG-DAG-TX-ID-v1\0')
                    if identifier in self._executed:duplicates+=1;continue
                    source=self._preview_state[body['from']];target=self._preview_state[body['to']];amount=int(body['amount_atomic'])
                    if body['nonce']!=source['nonce'] or int(source['balance_atomic'])<amount:conflicts+=1;continue
                    source['balance_atomic']=str(int(source['balance_atomic'])-amount);source['nonce']+=1
                    target['balance_atomic']=str(int(target['balance_atomic'])+amount);self._executed.add(identifier);accepted+=1
                row['preview_accepted_count']=accepted;row['preview_conflict_count']=conflicts;row['preview_duplicate_count']=duplicates
                self._preview_counts['accepted']+=accepted;self._preview_counts['conflicts']+=conflicts;self._preview_counts['duplicates']+=duplicates
                self._resolved.add(row['hash'])
            if pending:self._set_root()
            return {**self._preview_counts,'state_root':self._preview_root,'canonical':False,'finality':FINALITY}

    def build_wave(self,blocks=24,transactions_per_block=8,*,_cancel=None):
        _integer(blocks,1,MAX_WAVE_BLOCKS,'GG_DAG_WAVE_BLOCKS')
        _integer(transactions_per_block,0,MAX_TX_PER_BLOCK,'GG_DAG_WAVE_TX')
        if blocks*transactions_per_block>MAX_WAVE_TRANSACTIONS:raise ValueError('GG_DAG_WAVE_TX_LIMIT')
        with self._lock:
            if self._live.get('enabled') and threading.current_thread() is not self._live_thread:raise ValueError('GG_DAG_LIVE_RUNNING')
        if not self._wave_lock.acquire(blocking=False):raise ValueError('GG_DAG_WAVE_BUSY')
        started=time.perf_counter()
        try:
            with self._lock:
                if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
                if not self._can_produce:raise ValueError('GG_DAG_VERIFIER_ONLY')
                if any(key is None for key in self._producer_keys):raise ValueError('GG_DAG_LOCAL_PRODUCER_ONLY')
                if len(self._records)+blocks>MAX_RECORDS:raise ValueError('GG_DAG_RECORD_LIMIT')
                self.reconcile();chain=self._chain;root=self._preview_root
                frontier=sorted(self._frontier,key=lambda key:(self._records[key]['rank'],key))
                jobs=[[] for _ in range(min(self._producer_count,blocks))]
                for slot in range(blocks):
                    producer=slot%len(jobs);self._next_sequences[producer]+=1
                    parents=[frontier[(slot*MAX_PARENTS+i)%len(frontier)] for i in range(min(MAX_PARENTS,len(frontier)))]
                    indices=[(self._cursor+slot*transactions_per_block+i)%ACCOUNT_COUNT for i in range(transactions_per_block)]
                    jobs[producer].append((producer,self._next_sequences[producer],parents,root,indices))
            barrier=threading.Barrier(len(jobs));intervals=[];interval_lock=threading.Lock()
            def produce(group):
                barrier.wait(timeout=5);begin=time.perf_counter()
                values=[]
                for job in group:
                    if _cancel is not None and _cancel.is_set():raise ValueError('GG_DAG_LIVE_CANCELLED')
                    values.append(self._candidate(*job))
                with interval_lock:intervals.append((begin,time.perf_counter()))
                return values
            producer_started=time.perf_counter()
            with ThreadPoolExecutor(max_workers=len(jobs),thread_name_prefix='gg-dag-producer') as pool:
                futures=[pool.submit(produce,group) for group in jobs]
                candidates=[value for future in futures for value in future.result(timeout=20)]
            producer_ms=(time.perf_counter()-producer_started)*1000
            validation_started=time.perf_counter()
            with self._lock:
                if not self._active or self._chain!=chain:raise ValueError('GG_DAG_SESSION_CHANGED')
                if _cancel is not None and _cancel.is_set():raise ValueError('GG_DAG_LIVE_CANCELLED')
                # Budget the WHOLE wave before admission; there is no partial
                # queued job left behind when remaining credits are too small.
                total=sum(map(len,candidates))
                peer_sizes=[sum(len(raw) for raw in candidates if json.loads(raw)['body']['producer_index']==p) for p in range(self._producer_count)]
                if self._stats['attempts']+blocks>MAX_ATTEMPTS or self._stats['charged_bytes']+total>MAX_SESSION_BYTES or any(self._peer_bytes[p]+peer_sizes[p]>MAX_SESSION_BYTES//self._producer_count for p in range(self._producer_count)):raise ValueError('GG_DAG_SESSION_CREDIT')
                for raw in candidates:self.admit(raw,json.loads(raw)['body']['producer_index'])
                self._cursor=(self._cursor+blocks*transactions_per_block)%ACCOUNT_COUNT;self._wave_count+=1
                self.reconcile()
                validation_ms=(time.perf_counter()-validation_started)*1000
                overlap=max(0,min(end for begin,end in intervals)-max(begin for begin,end in intervals))*1000
                self._last_wave={'blocks':blocks,'transactions':blocks*transactions_per_block,'producer_ms':round(producer_ms,3),
                    'validation_ms':round(validation_ms,3),'total_ms':round((time.perf_counter()-started)*1000,3),
                    'workers_used':len(jobs),'parallel':len(jobs)>1,'worker_overlap_ms':round(overlap,3),
                    'sequence':self._wave_count,'timestamp':time.time()}
                self._measurements.append({'kind':'wave',**self._last_wave})
                self._event('WAVE_ADMITTED',str(blocks)+' parallella signerade förslag · '+str(blocks*transactions_per_block)+' validerade testtransaktioner · ingen finalitet')
                return self.snapshot()
        finally:self._wave_lock.release()

    def start_live(self,blocks=LIVE_BLOCKS,transactions_per_block=LIVE_TX_PER_BLOCK,interval_ms=LIVE_INTERVAL_MS):
        """Start one finite producer loop. Time is cadence, never fabricated data.

        The first real wave runs immediately. Cadence is measured start-to-start;
        missed periods are skipped, so slow devices accumulate no timer backlog.
        Record/byte/attempt budgets stop the loop without discarding its history.
        """
        _integer(blocks,1,MAX_WAVE_BLOCKS,'GG_DAG_WAVE_BLOCKS')
        _integer(transactions_per_block,0,MAX_TX_PER_BLOCK,'GG_DAG_WAVE_TX')
        _integer(interval_ms,MIN_LIVE_INTERVAL_MS,MAX_LIVE_INTERVAL_MS,'GG_DAG_LIVE_INTERVAL')
        if blocks*transactions_per_block>MAX_WAVE_TRANSACTIONS:raise ValueError('GG_DAG_WAVE_TX_LIMIT')
        with self._live_control:
            with self._lock:
                if self._live_thread is not None and self._live_thread.is_alive():
                    if self._live['enabled'] and (blocks,transactions_per_block,interval_ms)==(self._live['blocks'],self._live['transactions_per_block'],self._live['interval_ms']):return self.snapshot()
                    raise ValueError('GG_DAG_LIVE_ALREADY_RUNNING')
                if self._wave_lock.locked():raise ValueError('GG_DAG_WAVE_BUSY')
                self.start()
                if not self._can_produce:raise ValueError('GG_DAG_VERIFIER_ONLY')
                self._live_cancel=threading.Event();cancel=self._live_cancel;chain=self._chain
                self._live.update(state='RUNNING',enabled=True,blocks=blocks,transactions_per_block=transactions_per_block,
                    interval_ms=interval_ms,target_proposal_bps=blocks*1000/interval_ms,stop_reason='',in_flight=False,
                    mode='WAVE_COMPATIBILITY',producer_count=self._producer_count,active_workers=0)
                self._event('LIVE_STARTED',str(blocks)+' signerade förslag / våg · '+str(transactions_per_block)+' test-TX / förslag · minst '+str(interval_ms)+' ms mellan jobb')
                def run():
                    reason='';state='PAUSED'
                    try:
                        next_start=time.monotonic()
                        while not cancel.is_set():
                            with self._lock:
                                if not self._active or self._chain!=chain:break
                                if len(self._records)+blocks>MAX_RECORDS:
                                    reason='GG_DAG_RECORD_LIMIT';state='LIMIT_REACHED';break
                                self._live['in_flight']=True
                            self.build_wave(blocks,transactions_per_block,_cancel=cancel)
                            with self._lock:
                                self._live['in_flight']=False;self._live['waves_completed']+=1
                            next_start+=interval_ms/1000
                            now=time.monotonic()
                            if next_start<now:next_start=now+interval_ms/1000
                            if cancel.wait(max(0,next_start-time.monotonic())):break
                    except Exception as error:
                        code=str(error)
                        if code not in {'GG_DAG_LIVE_CANCELLED','GG_DAG_SESSION_CHANGED','GG_DAG_NOT_RUNNING'}:
                            reason=code if re.fullmatch(r'GG_DAG_[A-Z0-9_]{1,64}',code) else 'GG_DAG_LIVE_FAILED'
                            state='LIMIT_REACHED' if code in {'GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_STORAGE_LIMIT','GG_DAG_RECORD_LIMIT'} else 'ERROR'
                    finally:
                        with self._lock:
                            if self._chain==chain:
                                self._live.update(state=state if self._active else 'STOPPED',enabled=False,in_flight=False,stop_reason=reason)
                                self._event('LIVE_LIMIT' if state=='LIMIT_REACHED' else 'LIVE_ERROR' if state=='ERROR' else 'LIVE_PAUSED',reason or 'Löpande förslag pausade; godtagna förslag finns kvar')
                self._live_thread=threading.Thread(target=run,name='gg-dag-live',daemon=True)
                self._live_thread.start()
                return self.snapshot()

    def _async_prepare(self,producer,transactions,chain,cancel):
        """Reserve one bounded job and capture its immutable signing inputs."""
        with self._lock:
            if cancel.is_set() or not self._active or self._chain!=chain:return None
            if len(self._records)>=MAX_RECORDS:raise ValueError('GG_DAG_RECORD_LIMIT')
            if self._stats['attempts']>=MAX_ATTEMPTS:raise ValueError('GG_DAG_SESSION_CREDIT')
            # A busy local signer skips this period. There is no queued job or
            # synchronized barrier, and reserved work cannot exceed the caps.
            if (len(self._records)+self._async_reserved>=MAX_RECORDS
                    or self._stats['attempts']+self._async_reserved>=MAX_ATTEMPTS
                    or self._async_transactions+transactions>MAX_WAVE_TRANSACTIONS):return None
            root=self._preview_root
            choices=[identifier for identifier in self._recent_hashes
                     if self._records[identifier]['rank']>=max(0,self._max_rank-7)]
            if not choices:choices=[self._highest_hash]
            parents=self._random.sample(choices,self._random.randint(1,min(MAX_PARENTS,len(choices))))
            self._next_sequences[producer]+=1
            indices=[(self._cursor+index)%ACCOUNT_COUNT for index in range(transactions)]
            self._cursor=(self._cursor+transactions)%ACCOUNT_COUNT
            context={'chain':chain,'checkpoint':self._roots[root],
                'addresses':self._addresses,'account_keys':self._account_keys,
                'producer_key':self._producer_keys[producer],
                'rank':1+max(self._records[parent]['rank'] for parent in parents)}
            self._async_reserved+=1;self._async_transactions+=transactions
            self._live['in_flight']=True
            self._live['max_in_flight_proposals']=max(self._live.get('max_in_flight_proposals',0),self._async_reserved)
            return (producer,self._next_sequences[producer],parents,root,indices),context

    def _async_release(self,transactions):
        with self._lock:
            self._async_reserved-=1;self._async_transactions-=transactions
            self._live['in_flight']=self._async_reserved>0

    def start_async_live(self,blocks=LIVE_BLOCKS,transactions_per_block=LIVE_TX_PER_BLOCK,
                         interval_ms=LIVE_INTERVAL_MS,*,producer_count=ASYNC_LIVE_PRODUCERS,local_producers=None):
        """Run independent local producers with actual, uneven admission times.

        `blocks/interval_ms` is an aggregate requested rate, not a wave size.
        Workers have distinct configured rates and bounded timing jitter. Each
        signs one real proposal and independently admits its actual known
        parents. This remains a local experiment, not peers or finality.
        """
        _integer(blocks,1,MAX_WAVE_BLOCKS,'GG_DAG_WAVE_BLOCKS')
        _integer(transactions_per_block,0,MAX_TX_PER_BLOCK,'GG_DAG_WAVE_TX')
        _integer(interval_ms,MIN_LIVE_INTERVAL_MS,MAX_LIVE_INTERVAL_MS,'GG_DAG_LIVE_INTERVAL')
        _integer(producer_count,1,MAX_PRODUCERS,'GG_DAG_PRODUCER_COUNT')
        if local_producers is not None:
            if not isinstance(local_producers,(list,tuple)) or not 1<=len(local_producers)<=producer_count:raise ValueError('GG_DAG_LOCAL_SIGNERS')
            for index in local_producers:_integer(index,0,producer_count-1,'GG_DAG_PRODUCER')
            if len(set(local_producers))!=len(local_producers):raise ValueError('GG_DAG_LOCAL_SIGNERS')
        if blocks*transactions_per_block>MAX_WAVE_TRANSACTIONS:raise ValueError('GG_DAG_WAVE_TX_LIMIT')
        with self._live_control:
            with self._lock:
                available=tuple(index for index,key in enumerate(self._producer_keys) if key is not None) if self._active else tuple(range(producer_count))
                selected=tuple(sorted(local_producers)) if local_producers is not None else available
                if not selected or not set(selected)<=set(available):raise ValueError('GG_DAG_PRODUCER_NOT_OWNED')
                requested=(blocks,transactions_per_block,interval_ms,producer_count,selected)
                if self._live_thread is not None and self._live_thread.is_alive():
                    current=(self._live['blocks'],self._live['transactions_per_block'],self._live['interval_ms'],self._producer_count,tuple(self._live.get('local_producer_indices',range(self._producer_count))))
                    if self._live['enabled'] and self._live.get('mode')=='ASYNC_INDEPENDENT_PRODUCERS' and current==requested:return self.snapshot()
                    raise ValueError('GG_DAG_LIVE_ALREADY_RUNNING')
                if self._wave_lock.locked():raise ValueError('GG_DAG_WAVE_BUSY')
                if self._active and not self._can_produce:raise ValueError('GG_DAG_VERIFIER_ONLY')
                self._start_session(producer_count)
                if transactions_per_block and not self._account_keys:raise ValueError('GG_DAG_ACCOUNT_SIGNER_UNAVAILABLE')
                self._live_cancel=threading.Event();cancel=self._live_cancel;chain=self._chain
                self._async_reserved=0;self._async_transactions=0;self._async_threads=[]
                weights=list(range(1,producer_count+1));weight_total=sum(weights)
                periods=[max(MIN_LIVE_INTERVAL_MS/1000,interval_ms/1000*weight_total/(blocks*weight)) for weight in weights]
                delays=[0.0 if index==0 else self._random.uniform(0,min(.2,period)) for index,period in enumerate(periods)]
                for index in selected:self._producer_stats[index]['configured_interval_ms']=round(periods[index]*1000,3)
                self._live.update(state='RUNNING',enabled=True,blocks=blocks,transactions_per_block=transactions_per_block,
                    interval_ms=interval_ms,requested_proposal_bps=blocks*1000/interval_ms,
                    target_proposal_bps=round(sum(1/periods[index] for index in selected),6),stop_reason='',in_flight=False,
                    mode='ASYNC_INDEPENDENT_PRODUCERS',producer_count=producer_count,active_workers=0,
                    max_in_flight_proposals=0,cadence_origin='LOCAL_CONFIGURED_WORKERS',local_producer_indices=list(selected),local_worker_count=len(selected))
                self._event('LIVE_STARTED',str(len(selected))+' oberoende lokala producenter · varierad verklig takt · inga synkroniserade vågor')

                def fail(error):
                    code=str(error)
                    if code in {'GG_DAG_LIVE_CANCELLED','GG_DAG_SESSION_CHANGED','GG_DAG_NOT_RUNNING'}:return
                    code=code if re.fullmatch(r'GG_DAG_[A-Z0-9_]{1,64}',code) else 'GG_DAG_LIVE_FAILED'
                    with self._lock:
                        if self._chain==chain and not self._live.get('stop_reason'):
                            state='LIMIT_REACHED' if code in {'GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_STORAGE_LIMIT','GG_DAG_RECORD_LIMIT'} else 'ERROR'
                            self._live.update(state=state,stop_reason=code)
                    cancel.set()

                def produce(producer):
                    period=periods[producer];deadline=time.monotonic()+delays[producer]
                    with self._lock:self._live['active_workers']+=1
                    try:
                        while not cancel.is_set():
                            if cancel.wait(max(0,deadline-time.monotonic())):break
                            prepared=self._async_prepare(producer,transactions_per_block,chain,cancel)
                            if prepared is not None:
                                job,context=prepared;began=time.perf_counter()
                                try:
                                    raw=self._candidate(*job,_context=context)
                                    producer_ms=(time.perf_counter()-began)*1000
                                    validation_began=time.perf_counter()
                                    with self._lock:
                                        if cancel.is_set() or not self._active or self._chain!=chain:break
                                        if len(self._records)>=MAX_RECORDS:raise ValueError('GG_DAG_RECORD_LIMIT')
                                        if self._stats['attempts']>=MAX_ATTEMPTS or self._stats['charged_bytes']+len(raw)>MAX_SESSION_BYTES:raise ValueError('GG_DAG_SESSION_CREDIT')
                                        if self._peer_bytes[producer]+len(raw)>MAX_SESSION_BYTES//producer_count:raise ValueError('GG_DAG_PEER_CREDIT')
                                        self.admit(raw,producer);self.reconcile();self._wave_count+=1
                                        self._live['jobs_completed']+=1;self._live['waves_completed']+=1
                                        self._last_wave={'kind':'async_proposal','blocks':1,'transactions':transactions_per_block,
                                            'producer_index':producer,'parents':len(job[2]),
                                            'producer_ms':round(producer_ms,3),'validation_ms':round((time.perf_counter()-validation_began)*1000,3),
                                            'total_ms':round((time.perf_counter()-began)*1000,3),'workers_used':1,'parallel':False,
                                            'worker_overlap_ms':0,'sequence':self._wave_count,'timestamp':time.time()}
                                        self._measurements.append(dict(self._last_wave))
                                        self._event('PROPOSAL_ADMITTED','Producent '+str(producer+1)+' · '+str(len(job[2]))+' verkliga föräldrar · '+str(transactions_per_block)+' verifierade test-TX · ingen finalitet')
                                except ValueError as error:
                                    if str(error)=='GG_DAG_PRECHECK_ROOT':
                                        with self._lock:
                                            self._producer_stats[producer]['stale_prechecks']+=1
                                            self._event('PRECHECK_STALE','Ett lokalt förslag hann förlora sin förhandsrot; ingen automatisk transaktionsomsändning')
                                    else:raise
                                finally:self._async_release(transactions_per_block)
                            with self._lock:jitter=self._random.uniform(.85,1.15)
                            deadline+=period*jitter
                            now=time.monotonic()
                            if deadline<now:deadline=now+period*jitter
                    except Exception as error:fail(error)
                    finally:
                        with self._lock:self._live['active_workers']-=1

                def supervise():
                    workers=[]
                    try:
                        workers=[threading.Thread(target=produce,args=(index,),name='gg-dag-producer-async-'+str(index),daemon=True) for index in selected]
                        with self._lock:self._async_threads=workers
                        for worker in workers:
                            if cancel.is_set():break
                            worker.start()
                        for worker in workers:
                            if worker.ident is not None:worker.join()
                    except Exception as error:fail(error)
                    finally:
                        cancel.set()
                        for worker in workers:
                            if worker.ident is not None and worker.is_alive():worker.join()
                        with self._lock:
                            if self._chain==chain:
                                state=self._live['state']
                                if state=='RUNNING':state='PAUSED'
                                self._live.update(state=state if self._active else 'STOPPED',enabled=False,in_flight=False,active_workers=0)
                                self._async_threads=[]
                                self._event('LIVE_LIMIT' if state=='LIMIT_REACHED' else 'LIVE_ERROR' if state=='ERROR' else 'LIVE_PAUSED',self._live.get('stop_reason') or 'Oberoende lokala producenter pausade; verkliga förslag finns kvar')

                self._live_thread=threading.Thread(target=supervise,name='gg-dag-live',daemon=True)
                self._live_thread.start()
                return self.snapshot()

    def stop_live(self):
        """Cancel future waves and join owned work before reporting PAUSED."""
        with self._live_control:
            self._live_cancel.set()
            worker=self._live_thread
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=20)
                if worker.is_alive():raise ValueError('GG_DAG_LIVE_STOP_TIMEOUT')
            with self._lock:
                self._live_thread=None
                self._live.update(enabled=False,in_flight=False)
                if self._live['state']=='RUNNING':self._live['state']='PAUSED' if self._active else 'STOPPED'
                return self.snapshot()

    def request_stop(self):
        """Signal cancellation immediately, without waiting for a DAG lock."""
        self._live_cancel.set()

    def telemetry_revision(self):
        """Cheap observation identity; do not rebuild unchanged graph payloads."""
        with self._lock:
            return (self._chain if self._active else '', 'RUNNING' if self._active else 'STOPPED',
                    self._wave_count if self._active else 0,
                    self._stats['accepted'] if self._active else 0,
                    self._live.get('state'), self._live.get('stop_reason'), int(time.monotonic()))

    def snapshot(self):
        with self._lock:
            limits={'max_parents':MAX_PARENTS,'max_wave_blocks':MAX_WAVE_BLOCKS,'max_tx_per_block':MAX_TX_PER_BLOCK,
                'max_wave_transactions':MAX_WAVE_TRANSACTIONS,'max_block_bytes':MAX_BLOCK_BYTES,'max_session_bytes':MAX_SESSION_BYTES,'max_records':MAX_RECORDS,'max_attempts':MAX_ATTEMPTS,
                'min_live_interval_ms':MIN_LIVE_INTERVAL_MS,'max_live_interval_ms':MAX_LIVE_INTERVAL_MS,'measurement_count':MEASUREMENT_COUNT,
                'max_producers':MAX_PRODUCERS,'producer_byte_credit':MAX_SESSION_BYTES//self._producer_count}
            capacity=self.capacity_limits()
            limits.update(max_tx_per_block=capacity['transactions_per_block'],max_block_bytes=capacity['block_bytes'],
                max_session_bytes=capacity['session_bytes'],producer_byte_credit=capacity['peer_bytes'])
            if not self._active:return {'state':'STOPPED','mode':'LOCAL_PARALLEL_PROPOSAL_DAG','chain_id':'','finality':FINALITY,'canonical_finalized':0,'producer_count':self._producer_count,'worker_count':0,'producers':[],'blocks_admitted':0,'transactions_validated':0,'frontier_size':0,'wave_count':0,'limits':limits,
                'last_wave':{},'live':dict(self._live),'measurements':[],'preview':{'accepted':0,'conflicts':0,'duplicates':0,'state_root':'','canonical':False},
                'admission':{'attempts':0,'accepted':0,'rejected':0,'duplicates':0,'signature_checks':0,'charged_bytes':0,'transactions_validated':0,'remaining_bytes':MAX_SESSION_BYTES,'stored_bytes':0},
                'block_graph':{'schema':'gg.block-graph.v1','topology':'MULTIPARENT_DAG','source':'LOCAL_SIGNED_PROPOSAL_DAG','finality':FINALITY,'producer_count':self._producer_count,'history_limit':GRAPH_BLOCKS,'blocks':[],'edges':[],'metrics':{}},'events':list(self._events)}
            visible=list(self._records.values())[-GRAPH_BLOCKS:];ids={row['hash'] for row in visible}
            blocks=[{'hash':row['hash'],'parent_hashes':list(row['parents']),'height':row['rank'],'rank':row['rank'],
                'timestamp':row['timestamp'],'transaction_count':row['transaction_count'],'proposer_index':row['producer_index'],
                'producer_sequence':row['producer_sequence'],'signature_verified':row['signature_verified'],'certificate_verified':False,
                'admission_index':row['admission_index'],
                'state':'GENESIS' if not row['rank'] else 'ADMITTED_UNFINALIZED',
                'preview_accepted_count':row.get('preview_accepted_count',0),'preview_conflict_count':row.get('preview_conflict_count',0)} for row in visible]
            edges=[{'from':parent,'to':row['hash']} for row in visible for parent in row['parents'] if parent in ids]
            now=time.monotonic();recent=[sample for sample in self._rate_samples if now-RATE_WINDOW_SECONDS<sample[0]<=now]
            metrics={'bps':round(len(recent)/RATE_WINDOW_SECONDS,3),
                'tps':round(sum(sample[1] for sample in recent)/RATE_WINDOW_SECONDS,3),
                'window_seconds':RATE_WINDOW_SECONDS,'rate_basis':'ROLLING_LOCAL_PROPOSAL_ADMISSION_NOT_FINALITY','ttf_p95_ms':None,'canonical_finalized':0}
            metrics['proposal_bps']=metrics['bps'];metrics['tx_validation_rate']=metrics['tps']
            graph={'schema':'gg.block-graph.v1','topology':'MULTIPARENT_DAG','source':'LOCAL_SIGNED_PROPOSAL_DAG','finality':FINALITY,
                'blocks':blocks,'edges':edges,'metrics':metrics,'tip_height':max(row['rank'] for row in visible),'producer_count':self._producer_count,
                'retained_blocks':len(self._records),'history_limit':GRAPH_BLOCKS,'partial_history':any(parent not in ids for row in visible for parent in row['parents']),
                'stale':False,'error':'','observed_at':time.time()}
            producers=[{**value,'observed_proposal_bps':round(sum(sample[2]==value['index'] for sample in recent)/RATE_WINDOW_SECONDS,3)} for value in self._producer_stats]
            workers=self._live.get('active_workers',0) if self._live.get('mode')=='ASYNC_INDEPENDENT_PRODUCERS' else self._producer_count if self._can_produce else 0
            return {'state':'RUNNING','mode':'LOCAL_PARALLEL_PROPOSAL_DAG','chain_id':self._chain,'producer_count':self._producer_count,'worker_count':workers,'producers':producers,
                'finality':FINALITY,'canonical_finalized':0,'lan_test_mode':self._lan_test_mode,'protocol_fault':self._lan_fault,'blocks_admitted':self._stats['accepted'],'transactions_validated':self._stats['transactions_validated'],
                'frontier_size':len(self._frontier),'wave_count':self._wave_count,'last_wave':dict(self._last_wave),
                'live':dict(self._live),'measurements':[dict(sample) for sample in self._measurements],
                'preview':{**self._preview_counts,'state_root':self._preview_root,'canonical':False},'limits':limits,
                'admission':{**self._stats,'remaining_bytes':max(0,capacity['session_bytes']-self._stats['charged_bytes']),'stored_bytes':self._stored_bytes},
                'block_graph':graph,'events':list(self._events)}

    def fork_verifier(self):
        """Independent local verifier from this explicitly trusted test session.

        Only public genesis/state, signed proposals and counters are copied.
        This is a test transport boundary, not remote peer authentication.
        """
        with self._lock:
            if not self._active:raise ValueError('GG_DAG_NOT_RUNNING')
            fields=('_active','_chain','_started','_started_ns','_producer_public','_addresses','_producer_count',
                '_preview_state','_genesis_state','_roots','_preview_root','_records','_frontier',
                '_producer_sequences','_next_sequences','_resolved','_executed','_stored_bytes',
                '_wave_count','_cursor','_last_wave','_preview_counts','_stats','_peer_bytes',
                '_first_admission','_last_admission','_events','_measurements','_rate_samples','_producer_stats','_recent_hashes','_max_rank','_highest_hash',
                '_lan_test_mode','_lan_fault','_lan_heads','_lan_counts','_capacity')
            verifier=ParallelDag(self._producer_count)
            for key in fields:setattr(verifier,key,deepcopy(getattr(self,key)))
            if self._lan_test_mode:verifier._lan_checkpoint=self._lan_checkpoint
            verifier._producer_keys=[];verifier._account_keys={};verifier._can_produce=False
            return verifier

    def stop(self):
        with self._live_control:
            self.stop_live()
            with self._lock:
                self._active=False
                self._live.update(state='STOPPED',enabled=False,in_flight=False,stop_reason='',active_workers=0)
                self._measurements.clear();self._rate_samples.clear();self._relay_measurement=None
                for name in ('_producer_keys','_producer_public','_account_keys','_addresses','_preview_state','_genesis_state','_roots','_records','_frontier','_producer_sequences','_resolved','_executed','_producer_stats','_recent_hashes'):
                    value=getattr(self,name,None)
                    if hasattr(value,'clear'):value.clear()
                self._event('STOPPED','Lokala förslag och testnyckelreferenser släppta')
                return self.snapshot()


_ENGINE=ParallelDag(ASYNC_LIVE_PRODUCERS)
def start():return _ENGINE.start_async_live()
def start_live(blocks=LIVE_BLOCKS,transactions_per_block=LIVE_TX_PER_BLOCK,interval_ms=LIVE_INTERVAL_MS,*,producer_count=ASYNC_LIVE_PRODUCERS):return _ENGINE.start_async_live(blocks,transactions_per_block,interval_ms,producer_count=producer_count)
def start_async_live(blocks=LIVE_BLOCKS,transactions_per_block=LIVE_TX_PER_BLOCK,interval_ms=LIVE_INTERVAL_MS,*,producer_count=ASYNC_LIVE_PRODUCERS):return _ENGINE.start_async_live(blocks,transactions_per_block,interval_ms,producer_count=producer_count)
def stop_live():return _ENGINE.stop_live()
def request_stop():_ENGINE.request_stop()
def build_wave(blocks=24,transactions_per_block=8):return _ENGINE.build_wave(blocks,transactions_per_block)
def snapshot():return _ENGINE.snapshot()
def telemetry_revision():return _ENGINE.telemetry_revision()
def stop():return _ENGINE.stop()
