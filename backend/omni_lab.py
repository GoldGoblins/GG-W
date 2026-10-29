"""Session-local signed four-party ledger and weak-link research harness.

These validators share one process. A 3/4 signature certificate is tested,
not a claim of distributed Byzantine consensus, a SNARK or production money.
Keys stay in RAM; a restart seals the historical session for verification.
"""
import hashlib
from collections import deque
from functools import wraps
import json
import re
import secrets
import threading
import time
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from backend import omni_assets as store
from backend.omni_transport import Receiver,fragment,HEADER

LOCK=threading.RLock()
_keys={}
_receiver=None
_participating=False
_retry=[]
_measurement_chain=None
_measurements=deque(maxlen=32)
ROLES=['light','relay','archive','validator','gateway']
PRESETS={'mobile':{'bytes_per_minute':8192,'storage_bytes':65536},'radio':{'bytes_per_minute':2048,'storage_bytes':16384},
         'desktop':{'bytes_per_minute':65536,'storage_bytes':262144},'server':{'bytes_per_minute':1048576,'storage_bytes':1048576}}
SUPPLY=1_000_000*10**6
MAX_PENDING=64
MAX_BLOCKS=256
RECENT_BLOCKS=16


def _measurement_target(chain,reset=False):
    global _measurement_chain
    if reset or chain!=_measurement_chain:
        _measurements.clear();_measurement_chain=chain


def _measured(operation):
    """Measure completed local work, never fabricate a network time series."""
    def decorate(function):
        @wraps(function)
        def call(*args,**kwargs):
            with LOCK:
                started=time.perf_counter();state='ERROR'
                try:
                    result=function(*args,**kwargs)
                    state=result.get('state','COMPLETE') if isinstance(result,dict) else 'COMPLETE'
                    return result
                finally:
                    if _measurement_chain is not None:
                        _measurements.append({'operation':operation,'elapsed_ms':max(0.0,(time.perf_counter()-started)*1000),
                                              'observed_at':time.time(),'state':state})
        return call
    return decorate


def digest(value): return hashlib.sha256(store.pack(value).encode()).hexdigest()


def _tree(value):
    leaves=[{'address':a,'balance':str(value['balances'][a]),'nonce':value['nonces'][a]} for a in sorted(value['balances'])]
    level=[digest(leaf) for leaf in leaves]; levels=[level]
    while len(level)>1:
        level=[hashlib.sha256(bytes.fromhex(level[i])+bytes.fromhex(level[i+1])).hexdigest() for i in range(0,len(level),2)]
        levels.append(level)
    return leaves,levels


def witness(value,address):
    leaves,levels=_tree(value); index=next(i for i,leaf in enumerate(leaves) if leaf['address']==address); cursor=index; path=[]
    for level in levels[:-1]:
        path.append({'side':'left' if cursor%2 else 'right','hash':level[cursor^1]}); cursor//=2
    return {'leaf':leaves[index],'path':path}


def verify_witness(root,proof):
    """A bounded Merkle membership check, not a proof of arbitrary execution."""
    try:
        leaf=proof['leaf']
        if set(leaf)!={'address','balance','nonce'} or type(leaf['nonce']) is not int or leaf['nonce']<0 or not isinstance(leaf['balance'],str) or not leaf['balance'].isdigit() or len(leaf['balance'])>20: return False
        if len(proof['path'])!=2: return False
        value=digest(leaf)
        for item in proof['path']:
            if item['side'] not in {'left','right'} or len(item['hash'])!=64: return False
            a,b=(item['hash'],value) if item['side']=='left' else (value,item['hash'])
            value=hashlib.sha256(bytes.fromhex(a)+bytes.fromhex(b)).hexdigest()
        return value==root
    except (KeyError,TypeError,ValueError): return False


def _load():
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS local_lab(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
        row=db.execute('SELECT body FROM local_lab WHERE id=1').fetchone()
    return json.loads(row[0]) if row else None


def _save(value):
    with store.db(True) as db:
        db.execute('INSERT OR REPLACE INTO local_lab VALUES(1,?)',(store.pack({k:v for k,v in value.items() if k!='_trusted_roots'}),))


def create():
    global _receiver,_participating,_retry
    with LOCK:
        old=_load()
        if isinstance(old,dict) and isinstance(old.get('chain_id'),str) and re.fullmatch('gglab:[0-9a-f]{24}',old['chain_id']):
            # Preserve public history before an explicit new lab session.
            with store.db(True) as db:
                db.execute('CREATE TABLE IF NOT EXISTS lab_history(chain_id TEXT PRIMARY KEY,body TEXT NOT NULL)')
                db.execute('INSERT OR REPLACE INTO lab_history VALUES(?,?)',(old['chain_id'],store.pack(old)))
                db.execute('DELETE FROM lab_history WHERE chain_id NOT IN (SELECT chain_id FROM lab_history ORDER BY rowid DESC LIMIT 16)')
        keys=[Keypair() for _ in range(4)]; chain='gglab:'+secrets.token_hex(12)
        addresses=[str(key.pubkey()) for key in keys]
        genesis={'chain_id':chain,'validators':addresses,'supply_atomic':str(SUPPLY),'allocation_atomic':str(SUPPLY//4),'decimals':6,'symbol':'GG-LAB','quorum':3}
        value={'chain_id':chain,'genesis':genesis,'head':digest(genesis),'height':0,'balances':{a:SUPPLY//4 for a in addresses},
               'nonces':{a:0 for a in addresses},'burned':0,'contributor_pool':0,'blocks':[],'pending':[],'enabled':[True]*4,
               'economics':{'burn_bps':0,'holder_bps':0,'contributor_bps':10000},'config':{'preset':'mobile','role':'light'}}
        store.register_network({'id':chain,'family':'gglab','name':'GG lokalt nätverkslabb','symbol':'GG-LAB','decimals':6,'endpoint':''})
        store.register_asset(chain,'native','GG-LAB','GG-LAB','GG laboratorietoken',6,metadata='LOCAL_GENESIS',behavior='FIXED_LAB_SUPPLY')
        _save(value)
        _keys.clear(); _keys[chain]=keys
        _receiver=None; _participating=False; _retry=[]
        _measurement_target(chain,reset=True)
        store.event('lab','CREATED',chain+'/native:GG-LAB','Nytt lokalt labb · 4 deltagare · lika testtilldelning')
        return snapshot()


def _current():
    value=_load()
    if value is None: raise ValueError('OMNI_CREATE_LAB_FIRST')
    _measurement_target(value.get('chain_id') if isinstance(value,dict) else None)
    proof=verify(value,include_roots=True)
    if proof.get('state')!='VERIFIED':raise ValueError('OMNI_LAB_HISTORY_INVALID')
    value['_trusted_roots']=proof['trusted_roots']
    if value['chain_id'] not in _keys: raise ValueError('OMNI_LAB_SESSION_SEALED')
    return value


def configure(options):
    global _receiver,_participating,_retry
    with LOCK:
        value=_current(); options=dict(options)
        if 'enabled' in options:
            if not isinstance(options['enabled'],list) or len(options['enabled'])!=4 or any(type(x) is not bool for x in options['enabled']): raise ValueError('OMNI_VALIDATORS')
            value['enabled']=options['enabled']
        if 'economics' in options:
            economics=options['economics']
            if set(economics)!={'burn_bps','holder_bps','contributor_bps'} or any(type(x) is not int or not 0<=x<=10000 for x in economics.values()) or sum(economics.values())!=10000:
                raise ValueError('OMNI_FEE_DISTRIBUTION')
            value['economics']=economics
        preset=options.get('preset',value['config']['preset']); role=options.get('role',value['config']['role'])
        if preset not in PRESETS or role not in ROLES: raise ValueError('OMNI_NODE_PROFILE')
        if 'participating' in options and type(options['participating']) is not bool: raise ValueError('OMNI_NODE_TOGGLE')
        value['config']={'preset':preset,'role':role}
        _save(value)
        if 'preset' in options or _receiver is None:
            if _retry:store.event('transport','CANCELLED','','Resursprofil ändrad · pågående paketöverföring avbruten')
            _retry=[];_receiver=Receiver(**PRESETS[preset])
        if 'participating' in options: _participating=options['participating']
        store.event('node','STARTED' if _participating else 'PAUSED','',role+' · '+preset+' · lokalt transporttest')
        return snapshot()


def prepare(sender=0,recipient=1,amount='1'):
    with LOCK:
        value=_current()
        if type(sender) is not int or type(recipient) is not int or sender not in range(4) or recipient not in range(4) or sender==recipient: raise ValueError('OMNI_LAB_PARTICIPANT')
        address=value['genesis']['validators'][sender]
        body={'schema':'gg.lab.tx.v1','chain_id':value['chain_id'],'sender':address,'recipient':value['genesis']['validators'][recipient],
              'amount':str(store.amount_atomic(amount,6)),'fee':'1000','nonce':value['nonces'][address],'account_root':_tree(value)[1][-1][0]}
        # A signature authenticates this request. It is NOT a validity SNARK.
        return {'body':body,'signature':str(_keys[value['chain_id']][sender].sign_message(store.pack(body).encode())),
                'sender_witness':witness(value,address),'recipient_witness':witness(value,body['recipient'])}


def _validate(value,envelope,trusted_roots=None):
    if not isinstance(envelope,dict) or set(envelope)!={'body','signature','sender_witness','recipient_witness'}: raise ValueError('OMNI_TX_SCHEMA')
    if not isinstance(envelope['signature'],str) or not 1<=len(envelope['signature'])<=88:raise ValueError('OMNI_TX_SIGNATURE')
    body=envelope['body']
    if not isinstance(body,dict) or set(body)!={'schema','chain_id','sender','recipient','amount','fee','nonce','account_root'} or body['schema']!='gg.lab.tx.v1': raise ValueError('OMNI_TX_SCHEMA')
    if body['chain_id']!=value['chain_id']: raise ValueError('OMNI_WRONG_CHAIN')
    if trusted_roots is None:
        trusted_roots=set(value.get('_trusted_roots') or [_tree(value)[1][-1][0]])
    if body['account_root'] not in trusted_roots: raise ValueError('OMNI_STALE_STATE_WITNESS')
    for role in ('sender','recipient'):
        proof=envelope[role+'_witness']
        if not verify_witness(body['account_root'],proof) or proof['leaf']['address']!=body[role]: raise ValueError('OMNI_STATE_WITNESS')
    if body['sender'] not in value['balances'] or body['recipient'] not in value['balances'] or body['sender']==body['recipient']: raise ValueError('OMNI_LAB_PARTICIPANT')
    if type(body['nonce']) is not int or body['nonce']!=value['nonces'][body['sender']]: raise ValueError('OMNI_REPLAY_OR_NONCE')
    if any(not isinstance(body[k],str) or not body[k].isdigit() or len(body[k])>20 for k in ('amount','fee')) or body['fee']!='1000': raise ValueError('OMNI_TX_AMOUNT')
    amount=int(body['amount']); fee=int(body['fee'])
    sender_leaf=envelope['sender_witness']['leaf']
    if sender_leaf['nonce']!=body['nonce'] or int(sender_leaf['balance'])<amount+fee:raise ValueError('OMNI_WITNESS_NONCE_OR_BALANCE')
    if amount<=0 or amount+fee>value['balances'][body['sender']]: raise ValueError('OMNI_INSUFFICIENT_LAB_FUNDS')
    try:
        if not Signature.from_string(envelope['signature']).verify(Pubkey.from_string(body['sender']),store.pack(body).encode()): raise ValueError('OMNI_TX_SIGNATURE')
    except (TypeError,ValueError): raise ValueError('OMNI_TX_SIGNATURE') from None
    return body


def submit(envelope):
    with LOCK:
        value=_current(); _validate(value,envelope); txid=digest(envelope)
        if any(digest(e)==txid for e in value['pending']): return {'state':'ALREADY_PENDING'}
        if len(value['pending'])>=MAX_PENDING: raise ValueError('OMNI_LAB_QUEUE_FULL')
        if len(value['blocks'])>=MAX_BLOCKS: raise ValueError('OMNI_LAB_HISTORY_LIMIT')
        value['pending'].append(envelope); _save(value)
        store.event('lab','QUEUED',value['chain_id']+'/native:GG-LAB','Signerad lokal transaktion väntar på quorum',txid)
        return {'state':'QUEUED','txid':txid}


def _apply(value,body,economics):
    amount=int(body['amount']); fee=int(body['fee']); sender=body['sender']; recipient=body['recipient']
    # All distributions are from the paid fee. No mint, hidden transfer tax or APY.
    burn=fee*economics['burn_bps']//10000; holders=fee*economics['holder_bps']//10000
    before=dict(value['balances']); denominator=sum(before.values())
    paid=0
    value['balances'][sender]-=amount+fee; value['balances'][recipient]+=amount
    for address,balance in before.items():
        rebate=holders*balance//denominator; value['balances'][address]+=rebate; paid+=rebate
    value['contributor_pool']+=fee-burn-paid; value['burned']+=burn; value['nonces'][sender]+=1
    if sum(value['balances'].values())+value['burned']+value['contributor_pool']!=SUPPLY: raise ValueError('OMNI_CONSERVATION')


@_measured('commit')
def commit():
    with LOCK:
        value=_current()
        if sum(value['enabled'])<3:
            store.event('lab','WAITING_QUORUM','','Ingen finalisering · minst 3 av 4 lokala signaturer krävs')
            return {'state':'WAITING_QUORUM'}
        if not value['pending']: return {'state':'EMPTY'}
        tx=value['pending'].pop(0)
        try: body=_validate(value,tx)
        except ValueError as exc:
            _save(value)
            store.event('lab','REJECTED',value['chain_id']+'/native:GG-LAB','Väntande transaktion avvisad · '+str(exc))
            raise
        previous=value['head']; economics=dict(value['economics']); _apply(value,body,economics)
        block={'height':value['height']+1,'previous':previous,'tx':tx,'economics':economics,
               'account_root':_tree(value)[1][-1][0],
               'state_root':digest({'balances':value['balances'],'nonces':value['nonces'],'burned':value['burned'],'contributor_pool':value['contributor_pool']})}
        raw=store.pack(block).encode()
        signatures=[{'validator':str(key.pubkey()),'signature':str(key.sign_message(raw))} for key,enabled in zip(_keys[value['chain_id']],value['enabled']) if enabled]
        value['blocks'].append({'block':block,'signatures':signatures}); value['height']=block['height']; value['head']=digest(block); _save(value)
        store.event('lab','FINALIZED',value['chain_id']+'/native:GG-LAB','Block '+str(value['height'])+' · '+str(len(signatures))+'/4 lokala signaturer',value['head'])
        return {'state':'FINALIZED','height':value['height']}


def _unsigned(value,maximum):
    return type(value) is int and 0<=value<=maximum


def _hash(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def _economics(value):
    return (isinstance(value,dict) and set(value)=={'burn_bps','holder_bps','contributor_bps'}
            and all(_unsigned(x,10000) for x in value.values()) and sum(value.values())==10000)


def _session_shape(value):
    """Bound persisted input before replay and bind display identity to genesis."""
    if not isinstance(value,dict):raise ValueError('OMNI_SESSION_SCHEMA')
    fields={'chain_id','genesis','head','height','balances','nonces','burned','contributor_pool',
            'blocks','pending','enabled','economics','config'}
    if not fields<=set(value) or set(value)-fields-{'_trusted_roots'}:raise ValueError('OMNI_SESSION_SCHEMA')
    genesis=value['genesis']
    if not isinstance(genesis,dict) or set(genesis)!={'chain_id','validators','supply_atomic','allocation_atomic','decimals','symbol','quorum'}:
        raise ValueError('OMNI_GENESIS')
    chain=genesis['chain_id'];validators=genesis['validators']
    if (not isinstance(chain,str) or re.fullmatch('gglab:[0-9a-f]{24}',chain) is None or value['chain_id']!=chain
        or type(genesis['decimals']) is not int or genesis['decimals']!=6 or genesis['symbol']!='GG-LAB'
        or type(genesis['quorum']) is not int or genesis['quorum']!=3
        or genesis['supply_atomic']!=str(SUPPLY) or genesis['allocation_atomic']!=str(SUPPLY//4)
        or not isinstance(validators,list) or len(validators)!=4
        or any(not isinstance(a,str) or len(a)>44 or str(Pubkey.from_string(a))!=a for a in validators)
        or len(set(validators))!=4):raise ValueError('OMNI_GENESIS')
    if (not _unsigned(value['height'],MAX_BLOCKS) or not _hash(value['head'])
        or not isinstance(value['blocks'],list) or len(value['blocks'])!=value['height']
        or not isinstance(value['pending'],list) or len(value['pending'])>MAX_PENDING
        or not isinstance(value['enabled'],list) or len(value['enabled'])!=4 or any(type(x) is not bool for x in value['enabled'])
        or not _economics(value['economics'])
        or not isinstance(value['config'],dict) or set(value['config'])!={'preset','role'}
        or value['config']['preset'] not in PRESETS or value['config']['role'] not in ROLES):raise ValueError('OMNI_SESSION_SCHEMA')
    for key,maximum in (('balances',SUPPLY),('nonces',MAX_BLOCKS)):
        if not isinstance(value[key],dict) or set(value[key])!=set(validators) or any(not _unsigned(x,maximum) for x in value[key].values()):
            raise ValueError('OMNI_SESSION_SCHEMA')
    if not _unsigned(value['burned'],SUPPLY) or not _unsigned(value['contributor_pool'],SUPPLY):raise ValueError('OMNI_SESSION_SCHEMA')
    # A queued request may become stale after another block. Its shape is still
    # bounded here; nonce/witness/signature validity is checked when committing.
    for envelope in value['pending']:
        if (not isinstance(envelope,dict) or set(envelope)!={'body','signature','sender_witness','recipient_witness'}
            or len(store.pack(envelope))>8192):raise ValueError('OMNI_TX_SCHEMA')
        body=envelope['body']
        if (not isinstance(body,dict) or set(body)!={'schema','chain_id','sender','recipient','amount','fee','nonce','account_root'}
            or body['schema']!='gg.lab.tx.v1' or body['chain_id']!=chain
            or body['sender'] not in validators or body['recipient'] not in validators or body['sender']==body['recipient']
            or not _unsigned(body['nonce'],MAX_BLOCKS) or not _hash(body['account_root'])
            or not isinstance(body['amount'],str) or re.fullmatch('[0-9]{1,20}',body['amount']) is None
            or not 0<int(body['amount'])<=SUPPLY or body['fee']!='1000'
            or not isinstance(envelope['signature'],str) or not 1<=len(envelope['signature'])<=88
            or not verify_witness(body['account_root'],envelope['sender_witness'])
            or not verify_witness(body['account_root'],envelope['recipient_witness'])):raise ValueError('OMNI_TX_SCHEMA')
    return genesis,validators


@_measured('verify')
def verify(value=None,include_roots=False):
    if value is None:
        value=_load()
    _measurement_target(value.get('chain_id') if isinstance(value,dict) else None)
    if value is None: return {'state':'EMPTY','blocks':0}
    try:
        g,validators=_session_shape(value)
        replay={'chain_id':g['chain_id'],'balances':{a:SUPPLY//4 for a in validators},'nonces':{a:0 for a in validators},'burned':0,'contributor_pool':0}
        head=digest(g)
        trusted_roots=[_tree(replay)[1][-1][0]]
        for i,receipt in enumerate(value['blocks'],1):
            if not isinstance(receipt,dict) or set(receipt)!={'block','signatures'}:raise ValueError('OMNI_BLOCK_SCHEMA')
            block=receipt['block']; raw=store.pack(block).encode(); signed=set()
            if (not isinstance(block,dict) or set(block) not in ({'height','previous','tx','economics','state_root'},
                     {'height','previous','tx','economics','state_root','account_root'})
                or len(raw)>8192 or type(block['height']) is not int or block['height']!=i or block['previous']!=head
                or not _hash(block['state_root']) or ('account_root' in block and not _hash(block['account_root']))
                or not isinstance(receipt['signatures'],list) or not 3<=len(receipt['signatures'])<=4):raise ValueError('OMNI_BLOCK_CHAIN')
            for sig in receipt['signatures']:
                if not isinstance(sig,dict) or set(sig)!={'validator','signature'}:raise ValueError('OMNI_QUORUM_SIGNATURE')
                if not isinstance(sig['signature'],str) or not 1<=len(sig['signature'])<=88:raise ValueError('OMNI_QUORUM_SIGNATURE')
                address=sig['validator']
                if address not in validators or address in signed or not Signature.from_string(sig['signature']).verify(Pubkey.from_string(address),raw): raise ValueError('OMNI_QUORUM_SIGNATURE')
                signed.add(address)
            if len(signed)<3: raise ValueError('OMNI_QUORUM')
            body=_validate(replay,block['tx'],set(trusted_roots[-64:])); economics=block['economics']
            if not _economics(economics): raise ValueError('OMNI_FEE_DISTRIBUTION')
            _apply(replay,body,economics)
            current_root=_tree(replay)[1][-1][0]
            if block.get('account_root',current_root)!=current_root:raise ValueError('OMNI_ACCOUNT_ROOT')
            trusted_roots.append(current_root)
            if digest({k:replay[k] for k in ('balances','nonces','burned','contributor_pool')})!=block['state_root']: raise ValueError('OMNI_STATE_ROOT')
            head=digest(block)
        if head!=value['head'] or value['height']!=len(value['blocks']) or any(replay[k]!=value[k] for k in ('balances','nonces','burned','contributor_pool')): raise ValueError('OMNI_STATE_MISMATCH')
        return {'state':'VERIFIED','blocks':len(value['blocks']),'head':head,**({'trusted_roots':trusted_roots[-64:]} if include_roots else {})}
    except (KeyError,TypeError,ValueError,OverflowError):
        blocks=value.get('blocks') if isinstance(value,dict) else None
        return {'state':'INVALID','blocks':len(blocks) if isinstance(blocks,list) else 0}


@_measured('transport_test')
def transport_test(loss=False):
    global _receiver,_retry
    with LOCK:
        value=_current()
        if not _participating: raise ValueError('OMNI_NODE_PAUSED')
        if _receiver is None: _receiver=Receiver(**PRESETS[value['config']['preset']])
        envelope=prepare(); wire=store.pack({'transfer_id':secrets.token_hex(8),'envelope':envelope}).encode(); parts=fragment(wire,128)
        _retry=[]
        delivered=None; states=[]
        for i,part in enumerate(reversed(parts)):
            if loss and i==0: _retry.append(part); continue
            result=_receiver.receive('local-sender',part); states.append(result['state'])
            if result['state'] not in {'PARTIAL','DELIVERED','DUPLICATE'}: _retry.append(part)
            if result['state']=='DELIVERED': delivered=result['data']
        if delivered:
            _receiver.stats['signature_checks']+=1
            result=submit(json.loads(delivered)['envelope']); state=result['state']
        else: state='RETRY_REQUIRED' if loss else states[-1]
        store.event('transport',state,'',str(len(parts))+' paket · omvänd ordning'+(' · ett paket borttaget' if loss else '')+' · endast lokalt test')
        return {'state':state,'packets':len(parts),'wire_bytes':sum(map(len,parts))}


@_measured('retry_transport')
def retry_transport():
    global _retry
    with LOCK:
        _current()
        _prune_retries()
        if not _participating: raise ValueError('OMNI_NODE_PAUSED')
        if not _receiver or not _retry: raise ValueError('OMNI_NO_PENDING_RETRY')
        remaining=[]; state='PARTIAL'
        for packet in _retry:
            result=_receiver.receive('local-sender',packet); state=result['state']
            if state=='DELIVERED':
                _receiver.stats['signature_checks']+=1; state=submit(json.loads(result['data'])['envelope'])['state']
            elif state not in {'PARTIAL','DUPLICATE'}: remaining.append(packet)
        _retry=remaining
        store.event('transport',state,'','Manuellt återförsök · '+str(len(remaining))+' paket återstår')
        return {'state':state}


def _prune_retries():
    global _retry
    expired=[p for p in _retry if HEADER.unpack(p[:HEADER.size])[5]<=time.time()]
    if not expired:return
    for packet in expired:
        if _receiver:_receiver.messages.pop(HEADER.unpack(packet[:HEADER.size])[1].hex(),None)
    _retry=[p for p in _retry if p not in expired]
    store.event('transport','EXPIRED','',str(len(expired))+' väntande paket löpte ut · ingen transaktion skapad')


def cancel_transport():
    global _retry
    with LOCK:
        for packet in _retry:
            if _receiver:_receiver.messages.pop(HEADER.unpack(packet[:HEADER.size])[1].hex(),None)
        count=len(_retry);_retry=[]
        store.event('transport','CANCELLED','',str(count)+' väntande paket avbrutna på begäran')
        return {'state':'CANCELLED'}


def _dashboard(value=None,verification=None):
    result={'limits':{'pending':MAX_PENDING,'blocks':MAX_BLOCKS,'recent_blocks':RECENT_BLOCKS,'measurements':_measurements.maxlen},
            'quorum':{'enabled':0,'total':4,'required':3,'missing':3,'last_signatures':None},
            'conservation':{'state':'NOT_CREATED','supply_atomic':None,'balances_atomic':None,'burned_atomic':None,
                            'contributor_pool_atomic':None,'accounted_atomic':None,'decimals':6,'symbol':'GG-LAB'},
            'recent_blocks':[],'pending_transactions':[],'measurements':[dict(row) for row in _measurements],
            'last_measurement':dict(_measurements[-1]) if _measurements else None}
    if value is None:return result
    if (verification or {}).get('state')!='VERIFIED':
        result['conservation']['state']='INVALID';return result
    validators=value['genesis']['validators']
    def transaction(envelope):
        body=envelope['body']
        return {'txid':digest(envelope),'sender_index':validators.index(body['sender']),
                'recipient_index':validators.index(body['recipient']),'amount':store.format_atomic(int(body['amount']),6),
                'fee':store.format_atomic(int(body['fee']),6),'nonce':body['nonce']}
    for receipt in reversed(value['blocks'][-RECENT_BLOCKS:]):
        block=receipt['block']
        result['recent_blocks'].append(dict(transaction(block['tx']),height=block['height'],signatures=len(receipt['signatures']),
                                            account_root=block.get('account_root'),block_hash=digest(block)))
    for index,envelope in enumerate(value['pending']):
        result['pending_transactions'].append(dict(transaction(envelope),index=index))
    enabled=sum(value['enabled'])
    result['quorum'].update(enabled=enabled,missing=max(0,3-enabled),
                            last_signatures=len(value['blocks'][-1]['signatures']) if value['blocks'] else None)
    balances=sum(value['balances'].values());accounted=balances+value['burned']+value['contributor_pool']
    result['conservation'].update(state='BALANCED' if accounted==SUPPLY else 'INVALID',supply_atomic=str(SUPPLY),
                                  balances_atomic=str(balances),burned_atomic=str(value['burned']),
                                  contributor_pool_atomic=str(value['contributor_pool']),accounted_atomic=str(accounted))
    return result


def snapshot():
    with LOCK:
        _prune_retries()
        value=_load()
        _measurement_target(value.get('chain_id') if isinstance(value,dict) else None)
        if value is None:return {'state':'NOT_CREATED','roles':ROLES,'presets':list(PRESETS),'participating':False,'dashboard':_dashboard()}
        verification=verify(value)
        if verification['state']!='VERIFIED':
            return {'state':'INVALID_SESSION','roles':ROLES,'presets':list(PRESETS),'participating':False,
                    'verification':verification,'dashboard':_dashboard(value,verification)}
        result={k:v for k,v in value.items() if k not in {'pending','blocks'}}
        result.update(state='ACTIVE_SESSION' if value['chain_id'] in _keys else 'SEALED_SESSION',pending=len(value['pending']),
                      roles=ROLES,presets=list(PRESETS),participating=_participating,retry_packets=len(_retry),transport=_receiver.snapshot() if _receiver else {},
                      verification=verification,consensus='LOCAL_3_OF_4_SIGNATURE_LAB',proof='MERKLE_MEMBERSHIP_AND_ED25519_NOT_VALIDITY_SNARK',
                      dashboard=_dashboard(value,verification))
        result['participants']=[{'address':a,'balance':store.format_atomic(value['balances'][a],6),'enabled':value['enabled'][i]} for i,a in enumerate(value['genesis']['validators'])]
        return result
