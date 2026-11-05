"""Bounded canonical monetary DAG wire and independently verified signing input.

No key generation, activation, wallet access, durable journal or network at import.
Producing a signature here does not by itself supply anti-equivocation storage.
The owned producer journal must retain the exact original before transmission.
"""
import base64
from copy import deepcopy
import hashlib
import re
import struct
import time

from backend.gg_ed25519 import Keypair,verify_signature
from backend.gg_dag_json import preflight_lan_block
from backend.gg_node_store import unpack
from backend.gg_parallel_dag import pack,_tree
from backend import gg_financial_dag as financial

MAX_PAYMENTS=50000
MAX_RAW=32*1024*1024
MAX_BATCH=48*1024*1024
HASH=re.compile(r'[0-9a-f]{64}')
SIGNATURE=re.compile(r'[0-9a-f]{128}')
DOMAIN=financial.DOMAIN
PAYMENT_DOCUMENT='gg.financial.signed-payments.v1'
OWN_PREFIX='gg.financial.own-prefix.v1'
MAX_OWN_PIPELINE=8
MAX_PIPELINE_RAW=(MAX_RAW-4096)*3//4
_INPUT_TOKEN=object()


class _AuthenticatedPayments:
    """Immutable local account-authentication result, never a network proof.

    It contains original canonical public envelope bytes. Funds/nonce outcomes
    and selection are deliberately absent; native SDK admission rechecks all
    account signatures independently. JSON cannot construct this local object.
    """
    __slots__=('_anchor','_genesis','_raws')
    def __init__(self,anchor,genesis,raws,*,token=None):
        if token is not _INPUT_TOKEN:raise ValueError('GG_FINANCIAL_LOCAL_AUTHENTICATION_REQUIRED')
        object.__setattr__(self,'_anchor',anchor);object.__setattr__(self,'_genesis',genesis);object.__setattr__(self,'_raws',tuple(raws))
    def __setattr__(self,name,value):raise AttributeError('immutable account-signed inputs')
    def __len__(self):return len(self._raws)
    def __deepcopy__(self,memo):return self
    def __repr__(self):return '<AuthenticatedPayments count='+str(len(self))+'>'
    def rows(self,start=0,end=None):
        end=len(self) if end is None else end
        if type(start) is not int or type(end) is not int or not 0<=start<=end<=len(self):raise ValueError('GG_FINANCIAL_INPUT_RANGE')
        return [unpack(raw) for raw in self._raws[start:end]]
    def suffix(self,start):
        if type(start) is not int or not 0<=start<len(self):raise ValueError('GG_FINANCIAL_INPUT_RANGE')
        return _AuthenticatedPayments(self._anchor,self._genesis,self._raws[start:],token=_INPUT_TOKEN)

    def segment(self,start,end):
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(self):raise ValueError('GG_FINANCIAL_INPUT_RANGE')
        return _AuthenticatedPayments(self._anchor,self._genesis,self._raws[start:end],token=_INPUT_TOKEN)


def counter(value,*,positive=False,maximum=financial.MAX_COUNTER):
    if (type(value) is not str or not re.fullmatch(r'0|[1-9][0-9]{0,19}',value)
            or not int(positive)<=int(value)<=maximum):raise ValueError('GG_FINANCIAL_COUNTER')
    return int(value)


def intent_id(raw):
    return hashlib.sha256(DOMAIN+b'INTENT\0'+raw).hexdigest()


def check_payment(payment,genesis,anchor):
    """Account authentication only; current nonce/funds are SDK-order outcomes."""
    try:
        if not isinstance(payment,dict) or set(payment)!={'body','signature'}:raise ValueError()
        body=payment['body'];signature=payment['signature']
        public=genesis['schema']=='gg.native.genesis.v7'
        fields={'amount_atomic','chain_id','genesis_hash','nonce','recipient','sender','version'}|({'max_fee_atomic'} if public else set())
        if (not isinstance(body,dict) or set(body)!=fields
                or type(body['version']) is not int or body['version']!=(2 if public else 1) or body['chain_id']!=genesis['chain_id'] or body['genesis_hash']!=anchor
                or not public and (type(body['nonce']) is not int or not 0<=body['nonce']<=2**64-1) or body['sender']==body['recipient']
                or type(signature) is not str or not SIGNATURE.fullmatch(signature)):raise ValueError()
        if public:
            counter(body['nonce'],maximum=2**64-1);counter(body['max_fee_atomic'],maximum=2**64-1)
        if genesis['schema'] in ('gg.native.genesis.v6','gg.native.genesis.v7'):
            reserved=financial.reserved_account_keys(genesis)
            for name in ('sender','recipient'):
                if financial.account_address(body[name]) in reserved:raise ValueError()
        elif body['sender'] not in genesis['accounts'] or body['recipient'] not in genesis['accounts']:raise ValueError()
        counter(body['amount_atomic'],positive=True,maximum=int(genesis['protocol']['economics']['max_supply_atomic']) if public else 10**12)
        raw=pack(payment)
        if len(raw)>2048:raise ValueError()
        verify_signature(bytes.fromhex(body['sender']),pack(body),bytes.fromhex(signature))
        return deepcopy(payment)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_PAYMENT_INVALID') from None


def authenticate_payments(payments,trust,*,check=lambda:None):
    """Check account authority before obtaining a short-lived creator context."""
    if type(payments) is _AuthenticatedPayments:
        if payments._anchor!=trust['genesis_hash'] or payments._genesis!=hashlib.sha256(pack(trust['genesis'])).digest():raise ValueError('GG_FINANCIAL_INPUT_ANCHOR')
        check();return payments
    if not isinstance(payments,(list,tuple)) or not 1<=len(payments)<=MAX_PAYMENTS:raise ValueError('GG_FINANCIAL_PAYMENT_COUNT')
    raws=[];size=0
    for payment in payments:
        check();row=check_payment(payment,trust['genesis'],trust['genesis_hash']);raw=pack(row);size+=len(raw)
        if size>MAX_RAW:raise ValueError('GG_FINANCIAL_BLOCK_LIMIT')
        raws.append(raw)
    return _AuthenticatedPayments(trust['genesis_hash'],hashlib.sha256(pack(trust['genesis'])).digest(),raws,token=_INPUT_TOKEN)


def decode_payment_document(raw,trust,*,authenticated=False):
    """Bounded canonical public input; this reads no private account key.

    Every original account signature is checked before an owned producer can
    retain or transmit it. Nonce/funds outcomes still belong to SDK execution.
    """
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_RAW:raise ValueError('GG_FINANCIAL_PAYMENT_DOCUMENT_SIZE')
    try:
        preflight_lan_block(raw,MAX_PAYMENTS);value=unpack(raw)
        if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','payments'} or value['schema']!=PAYMENT_DOCUMENT
                or value['genesis_hash']!=trust['genesis_hash'] or not isinstance(value['payments'],list)
                or not 1<=len(value['payments'])<=MAX_PAYMENTS):raise ValueError()
        values=authenticate_payments(value['payments'],trust)
        return values if authenticated else values.rows()
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_PAYMENT_DOCUMENT_INVALID') from None


def payment_root(payments):
    root=bytes.fromhex(_tree(payments,DOMAIN+b'DAG-PAYMENT-TREE\0')[-1][0])
    return hashlib.sha256(DOMAIN+b'DAG-PAYMENT-ROOT\0'+struct.pack('>Q',len(payments))+root).hexdigest()


def decode_block(raw,source,anchor,epoch,*,allow_previous_epoch=False):
    """Authenticate producer and payload commitment, not payment execution.

    The native CheckTx/SDK path still verifies EVERY payment account signature
    and computes actual nonce/funds outcomes. No decoded 'verified' flag exists.
    """
    try:
        if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_RAW:raise ValueError()
        preflight_lan_block(raw,MAX_PAYMENTS);block=unpack(raw)
        if not isinstance(block,dict) or set(block)!={'body','signature'}:raise ValueError()
        body=block['body']
        origin=counter(body['epoch'],positive=True)
        valid_epoch=origin==epoch or allow_previous_epoch and source['schema'] in financial.LINEAGE_SOURCE_SCHEMAS and origin<epoch
        if (not isinstance(body,dict) or set(body)!={'created_at_ns','epoch','genesis_hash','parents','payment_root','payments','producer_index','rank','schema','sequence','source_hash'}
                or body['schema']!='gg.financial-dag.block.v1' or body['genesis_hash']!=anchor or body['source_hash']!=financial.source_hash(source)
                or not valid_epoch or type(body['producer_index']) is not int or body['producer_index'] not in source['allowed_producers']
                or not isinstance(body['payments'],list) or len(body['payments'])>MAX_PAYMENTS or not isinstance(body['parents'],list)
                or not 1<=len(body['parents'])<=7 or any(type(parent) is not str or not HASH.fullmatch(parent) for parent in body['parents'])
                or body['parents']!=sorted(set(body['parents']))):raise ValueError()
        sequence=counter(body['sequence'],positive=True);rank=counter(body['rank'],positive=True)
        created=counter(body['created_at_ns'],positive=True,maximum=financial.MAX_COUNTER-5_000_000_000)
        if (created<int(source['started_at_ns']) or body['payment_root']!=payment_root(body['payments'])
                or type(block['signature']) is not str or not SIGNATURE.fullmatch(block['signature'])):raise ValueError()
        verify_signature(bytes.fromhex(source['producers'][body['producer_index']]),DOMAIN+b'DAG-BLOCK-SIGN\0'+pack(body),bytes.fromhex(block['signature']))
        return {'hash':hashlib.sha256(DOMAIN+b'DAG-BLOCK\0'+raw).hexdigest(),'producer_index':body['producer_index'],
                'sequence':sequence,'rank':rank,'payments':len(body['payments']),'body':body}
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_BLOCK_INVALID') from None


def _signed_block(context_packet,trust,signer,payments,*,created_at_ns=None,binary=None,stamp=None):
    """Private journal primitive: certify context and payments before signing."""
    financial.verify_producer(context_packet,trust,binary=binary,stamp=stamp)
    source=trust['genesis']['financial_dag'];proof=context_packet['financial_producer'];index=proof['producer_index']
    if not isinstance(signer,Keypair) or signer.pubkey().hex()!=source['producers'][index]:raise ValueError('GG_FINANCIAL_PRODUCER_KEY')
    owned=authenticate_payments(payments,trust).rows()
    created=time.time_ns() if created_at_ns is None else created_at_ns
    if type(created) is not int or not int(source['started_at_ns'])<=created<=financial.MAX_COUNTER-5_000_000_000:raise ValueError('GG_FINANCIAL_BLOCK_TIME')
    return _context_block_wire(proof,trust,signer,owned,created)


def _context_block_wire(proof,trust,signer,owned,created):
    """Private primitive, called after real SDK context and key validation."""
    source=trust['genesis']['financial_dag'];index=proof['producer_index']
    body={'created_at_ns':str(created),'epoch':proof['epoch'],'genesis_hash':trust['genesis_hash'],'parents':[proof['parent']],
          'payment_root':payment_root(owned),'payments':owned,'producer_index':index,'rank':str(counter(proof['parent_rank'])+1),
          'schema':'gg.financial-dag.block.v1','sequence':proof['sequence'],'source_hash':financial.source_hash(source)}
    raw=pack({'body':body,'signature':signer.sign_message(DOMAIN+b'DAG-BLOCK-SIGN\0'+pack(body)).hex()})
    if len(raw)>MAX_RAW:raise ValueError('GG_FINANCIAL_BLOCK_LIMIT')
    return raw


def _signed_chain(context_packet,trust,signer,payments,transactions_per_block,*,prefix=(),created_at_ns=None,binary=None,stamp=None,check=lambda:None):
    """Create a bounded own chain from one actual certified creator context.

    Extensions refer to actual originals created in this call, not invented SDK
    certificates. The owned journal must commit ALL returned wires atomically
    before any one of them can be exposed to transport.
    """
    financial.verify_producer(context_packet,trust,binary=binary,stamp=stamp);check()
    source=trust['genesis']['financial_dag'];proof=deepcopy(context_packet['financial_producer']);index=proof['producer_index']
    if not isinstance(signer,Keypair) or signer.pubkey().hex()!=source['producers'][index]:raise ValueError('GG_FINANCIAL_PRODUCER_KEY')
    values=authenticate_payments(payments,trust,check=check)
    if (type(transactions_per_block) is not int or not 1<=transactions_per_block<=MAX_PAYMENTS or not isinstance(prefix,(tuple,list))
            or len(prefix)+(len(values)+transactions_per_block-1)//transactions_per_block>MAX_OWN_PIPELINE):raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
    blocks=len(prefix)+(len(values)+transactions_per_block-1)//transactions_per_block
    if (counter(proof['sequence'],positive=True)+blocks-1>financial.MAX_COUNTER
            or counter(proof['parent_rank'])+blocks>financial.MAX_COUNTER):raise ValueError('GG_FINANCIAL_PIPELINE_COUNTER')
    created=time.time_ns() if created_at_ns is None else created_at_ns
    if type(created) is not int or not int(source['started_at_ns'])<=created<=financial.MAX_COUNTER-5_000_000_000:raise ValueError('GG_FINANCIAL_BLOCK_TIME')
    raws=[];total=0
    for raw in prefix:
        check();record=decode_block(raw,source,trust['genesis_hash'],counter(proof['epoch'],positive=True),allow_previous_epoch=True);body=record['body']
        if (record['producer_index']!=index or record['sequence']!=counter(proof['sequence'],positive=True)
                or body['parents']!=[proof['parent']] or record['rank']!=counter(proof['parent_rank'])+1 or record['payments']==0):
            raise ValueError('GG_FINANCIAL_OWN_PREFIX_INVALID')
        total+=len(raw)
        if total>MAX_PIPELINE_RAW:raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
        proof.update(parent=record['hash'],parent_rank=str(record['rank']),sequence=str(record['sequence']+1))
    for start in range(0,len(values),transactions_per_block):
        check()
        if counter(proof['sequence'],positive=True)>financial.MAX_COUNTER or counter(proof['parent_rank'])>=financial.MAX_COUNTER:
            raise ValueError('GG_FINANCIAL_PIPELINE_COUNTER')
        raw=_context_block_wire(proof,trust,signer,values.rows(start,min(len(values),start+transactions_per_block)),created)
        total+=len(raw)
        if total>MAX_PIPELINE_RAW:raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
        raws.append(raw)
        proof.update(parent=hashlib.sha256(DOMAIN+b'DAG-BLOCK\0'+raw).hexdigest(),
            parent_rank=str(counter(proof['parent_rank'])+1),sequence=str(counter(proof['sequence'],positive=True)+1))
    check();return raws


def batch(packet,raws):
    """Build a candidate from a controller-verified core packet, no selection claim."""
    if (not isinstance(raws,(list,tuple)) or not 1<=len(raws)<=128 or any(not isinstance(raw,bytes) or not raw for raw in raws)
            or sum(map(len,raws))>MAX_RAW):raise ValueError('GG_FINANCIAL_BATCH_LIMIT')
    source=packet['genesis']['financial_dag'];value=packet['state']['financial_dag']
    records=[decode_block(raw,source,packet['genesis_hash'],counter(value['epoch'],positive=True),allow_previous_epoch=True) for raw in raws]
    if any(record['payments']==0 for record in records):raise ValueError('GG_FINANCIAL_EMPTY_PRODUCTION')
    if len({record['hash'] for record in records})!=len(records):raise ValueError('GG_FINANCIAL_DUPLICATE_BLOCK')
    ordered=sorted(zip(records,raws),key=lambda pair:(pair[0]['rank'],pair[0]['hash']))
    checkpoint=counter(value['checkpoint'])
    if checkpoint==financial.MAX_COUNTER:raise ValueError('GG_FINANCIAL_CHECKPOINT_EXHAUSTED')
    previous=hashlib.sha256(DOMAIN+b'DAG-COMMITMENT\0'+pack(value)).hexdigest()
    raw=pack({'blocks':[base64.b64encode(wire).decode('ascii') for _,wire in ordered],'genesis_hash':packet['genesis_hash'],
              'previous':previous,'schema':'gg.financial-dag.batch.v1','sequence':str(checkpoint+1),'source_hash':financial.source_hash(source)})
    if len(raw)>MAX_BATCH:raise ValueError('GG_FINANCIAL_BATCH_LIMIT')
    return raw,[record for record,_ in ordered]


def encode_own_prefix(trust,raws):
    """Authenticated transport container, never an SDK selection assertion."""
    if (not isinstance(raws,(list,tuple)) or not 1<=len(raws)<=MAX_OWN_PIPELINE
            or any(not isinstance(raw,bytes) or not raw for raw in raws) or sum(map(len,raws))>MAX_PIPELINE_RAW):
        raise ValueError('GG_FINANCIAL_PIPELINE_LIMIT')
    first=unpack(raws[0])['body'];epoch=counter(first['epoch'],positive=True);index=first['producer_index']
    if trust['genesis']['financial_dag']['schema'] in financial.LINEAGE_SOURCE_SCHEMAS:
        epoch=max(counter(unpack(raw)['body']['epoch'],positive=True) for raw in raws)
    value={'schema':OWN_PREFIX,'genesis_hash':trust['genesis_hash'],'source_hash':financial.source_hash(trust['genesis']['financial_dag']),
        'epoch':str(epoch),'producer_index':index,'blocks':[base64.b64encode(raw).decode('ascii') for raw in raws]}
    encoded=pack(value)
    # Use the exact same strict container/lineage checks as its receiver.
    decode_own_prefix(encoded,trust)
    return encoded


def decode_own_prefix(raw,trust):
    try:
        if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_RAW:raise ValueError()
        preflight_lan_block(raw,MAX_OWN_PIPELINE);value=unpack(raw)
        source=trust['genesis']['financial_dag']
        if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','source_hash','epoch','producer_index','blocks'}
                or value['schema']!=OWN_PREFIX or value['genesis_hash']!=trust['genesis_hash'] or value['source_hash']!=financial.source_hash(source)
                or type(value['producer_index']) is not int or not 0<=value['producer_index']<6
                or not isinstance(value['blocks'],list) or not 1<=len(value['blocks'])<=MAX_OWN_PIPELINE):raise ValueError()
        epoch=counter(value['epoch'],positive=True);remaining=MAX_PIPELINE_RAW;previous=None;raws=[];maximum_origin=0
        for encoded in value['blocks']:
            if type(encoded) is not str or len(encoded)>(remaining+2)//3*4:raise ValueError()
            original=base64.b64decode(encoded,validate=True)
            if len(original)>remaining or base64.b64encode(original).decode('ascii')!=encoded:raise ValueError()
            remaining-=len(original);record=decode_block(original,source,trust['genesis_hash'],epoch,allow_previous_epoch=True)
            maximum_origin=max(maximum_origin,counter(record['body']['epoch'],positive=True))
            if record['producer_index']!=value['producer_index'] or record['payments']==0:raise ValueError()
            if previous is not None and (record['sequence']!=previous['sequence']+1 or record['rank']!=previous['rank']+1
                    or record['body']['parents']!=[previous['hash']]):raise ValueError()
            previous=record;raws.append(original)
        if source['schema'] in financial.LINEAGE_SOURCE_SCHEMAS and maximum_origin!=epoch:raise ValueError()
        return raws
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_OWN_PREFIX_INVALID') from None
