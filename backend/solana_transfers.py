"""Explicit, reviewed Solana transfers; separate from legacy read-only RPC.

Preparation is unsigned. Broadcast requires task approval, a backed-up local
signer and the exact reviewed draft. An ambiguous send is never re-signed.
"""
import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
import psutil
from backend import omni_assets as store,omni_rpc,wallet_vault
from backend import crypto_pump_accounts as spl

SOL=wallet_vault.SOL
MAINNET_GENESIS='5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d'
_PROCESS_CREATED=psutil.Process(os.getpid()).create_time()
_ACTIVE=set()
_ACTIVE_LOCK=threading.RLock()
READS={'getGenesisHash','getBalance','getAccountInfo','getTokenAccountsByOwner','getLatestBlockhash','getFeeForMessage','getMinimumBalanceForRentExemption','simulateTransaction','isBlockhashValid','getSignatureStatuses','getSlot','getBlockHeight'}


def _table(db):
    db.execute('CREATE TABLE IF NOT EXISTS wallet_transfers(id TEXT PRIMARY KEY,state TEXT NOT NULL,body TEXT NOT NULL,txid TEXT NOT NULL,error TEXT NOT NULL,updated_at REAL NOT NULL)')
    columns={r[1] for r in db.execute('PRAGMA table_info(wallet_transfers)')}
    for name,definition in (('worker_pid','INTEGER NOT NULL DEFAULT 0'),('worker_created','REAL NOT NULL DEFAULT 0')):
        if name not in columns:
            try:db.execute('ALTER TABLE wallet_transfers ADD COLUMN '+name+' '+definition)
            except sqlite3.OperationalError:
                if name not in {r[1] for r in db.execute('PRAGMA table_info(wallet_transfers)')}:raise


def _worker_alive(row):
    pid=row['worker_pid'];created=row['worker_created']
    if not pid or not created:return True  # Unknown legacy worker: never assume it is safe to retry.
    if pid==os.getpid() and abs(created-_PROCESS_CREATED)<.001:
        with _ACTIVE_LOCK:return row['id'] in _ACTIVE
    try:return abs(psutil.Process(pid).create_time()-created)<.001
    except psutil.NoSuchProcess:return False
    except (psutil.AccessDenied,OSError):return True


def _recover_interrupted():
    with store.db(True) as db:
        _table(db)
        for row in db.execute("SELECT * FROM wallet_transfers WHERE state IN ('SIGNING','SUBMITTING')").fetchall():
            if _worker_alive(row):continue
            if row['state']=='SIGNING' and not row['txid']:
                state,error='FAILED','WALLET_INTERRUPTED_BEFORE_BROADCAST'
            else:state,error='UNCERTAIN','WALLET_BROADCAST_NOT_CONFIRMED'
            db.execute('UPDATE wallet_transfers SET state=?,error=?,updated_at=? WHERE id=? AND state=?',
                (state,error,time.time(),row['id'],row['state']))


def _rpc(method,params):
    return _rpc_at(store.network(SOL)['endpoint'],method,params)


def _rpc_at(endpoint,method,params):
    if method not in READS:raise ValueError('WALLET_READ_ONLY_METHOD')
    reply=omni_rpc._json(endpoint,{'jsonrpc':'2.0','id':1,'method':method,'params':params})
    if not isinstance(reply,dict) or reply.get('jsonrpc')!='2.0' or type(reply.get('id')) is not int or reply['id']!=1 or 'error' in reply or 'result' not in reply:raise ValueError('WALLET_RPC_ERROR')
    return reply['result']


def _identity(endpoint=None):
    value=_rpc('getGenesisHash',[]) if endpoint is None else _rpc_at(endpoint,'getGenesisHash',[])
    if value!=MAINNET_GENESIS:raise ValueError('WALLET_WRONG_NETWORK')


def _number(value):
    if type(value) is not int or not 0<=value<2**64:raise ValueError('WALLET_RPC_AMOUNT')
    return value


def _info(address):
    return _rpc('getAccountInfo',[address,{'encoding':'base64','commitment':'confirmed'}]).get('value')


def _build(account_id,asset_id,recipient,amount,blockhash=None):
    from solders.pubkey import Pubkey
    from solders.hash import Hash
    from solders.instruction import Instruction,AccountMeta
    from solders.message import Message
    from solders.transaction import Transaction
    from solders.system_program import transfer,TransferParams
    endpoint=store.network(SOL)['endpoint']
    def rpc(method,params):return _rpc_at(endpoint,method,params)
    def info(address):return rpc('getAccountInfo',[address,{'encoding':'base64','commitment':'confirmed'}]).get('value')
    state=store.snapshot();account=next((a for a in state['accounts'] if a['id']==account_id),None);asset=store.asset(asset_id)
    if not account or account['chain_id']!=SOL or asset['chain_id']!=SOL:raise ValueError('WALLET_ACCOUNT_NETWORK_MISMATCH')
    owner=account['address'];recipient=store.address_for(store.network(SOL),recipient)
    if not Pubkey.from_string(recipient).is_on_curve() or recipient==owner:raise ValueError('WALLET_RECIPIENT')
    atomic=store.amount_atomic(amount,asset['decimals'])
    if not 0<atomic<2**64:raise ValueError('WALLET_TRANSFER_AMOUNT')
    _identity(endpoint);owner_key=Pubkey.from_string(owner);recipient_key=Pubkey.from_string(recipient)
    lamports=_number(rpc('getBalance',[owner,{'commitment':'confirmed'}]).get('value'))
    instructions=[];rent=0;source='';sources=[];ata=''
    if asset['namespace']=='native':
        instructions.append(transfer(TransferParams(from_pubkey=owner_key,to_pubkey=recipient_key,lamports=atomic)))
    elif asset['namespace']=='token':
        mint=spl.decode_mint(info(asset['reference']))
        if mint['token_program']!=spl.TOKEN_PROGRAM or mint['decimals']!=asset['decimals']:raise ValueError('WALLET_TOKEN_TRANSFER_ADAPTER_REQUIRED')
        rows=rpc('getTokenAccountsByOwner',[owner,{'mint':asset['reference']},{'encoding':'base64','commitment':'confirmed'}]).get('value')
        if not isinstance(rows,list) or len(rows)>512:raise ValueError('WALLET_TOKEN_ACCOUNTS')
        candidates=[];seen=set()
        for row in rows:
            address=store.address_for(store.network(SOL),row.get('pubkey'))
            if address in seen:raise ValueError('WALLET_TOKEN_ACCOUNTS')
            seen.add(address)
            token=spl.decode_token_account(row.get('account'),expected_mint=asset['reference'],expected_owner=owner,expected_program=spl.TOKEN_PROGRAM)
            if not token['frozen'] and token['amount']>0:candidates.append((token['amount'],address))
        available=sum(balance for balance,_ in candidates)
        if available>=2**64:raise ValueError('WALLET_TOKEN_BALANCE_SCHEMA')
        if available<atomic:raise ValueError('WALLET_INSUFFICIENT_TOKEN_BALANCE')
        sufficient=sorted((balance,address) for balance,address in candidates if balance>=atomic)
        remaining=atomic
        for balance,address in sufficient[:1] if sufficient else sorted(candidates,key=lambda item:(-item[0],item[1])):
            part=min(balance,remaining);sources.append({'address':address,'atomic':str(part)});remaining-=part
            if remaining==0:break
        if len(sources)>8:raise ValueError('WALLET_FRAGMENTED_BALANCE_LIMIT')
        source=sources[0]['address'] if len(sources)==1 else '';ata=spl.derive_ata(recipient,asset['reference'],spl.TOKEN_PROGRAM)
        destination=info(ata)
        if destination is None:
            rent=_number(rpc('getMinimumBalanceForRentExemption',[165,{'commitment':'confirmed'}]))
            keys=[(owner,True,True),(ata,False,True),(recipient,False,False),(asset['reference'],False,False),('11111111111111111111111111111111',False,False),(spl.TOKEN_PROGRAM,False,False)]
            instructions.append(Instruction(Pubkey.from_string(spl.ASSOCIATED_TOKEN_PROGRAM),b'\x01',[AccountMeta(Pubkey.from_string(k),signer,writable) for k,signer,writable in keys]))
        else:
            token=spl.decode_token_account(destination,expected_mint=asset['reference'],expected_owner=recipient,expected_program=spl.TOKEN_PROGRAM)
            if token['frozen']:raise ValueError('WALLET_RECIPIENT_FROZEN')
        for part in sources:
            keys=[(part['address'],False,True),(asset['reference'],False,False),(ata,False,True),(owner,True,False)]
            instructions.append(Instruction(Pubkey.from_string(spl.TOKEN_PROGRAM),b'\x0c'+int(part['atomic']).to_bytes(8,'little')+bytes([asset['decimals']]),[AccountMeta(Pubkey.from_string(k),signer,writable) for k,signer,writable in keys]))
    else:raise ValueError('WALLET_TRANSFER_ADAPTER_REQUIRED')
    latest=rpc('getLatestBlockhash',[{'commitment':'confirmed'}]).get('value') or {}
    last_height=_number(latest.get('lastValidBlockHeight'));recent=blockhash or latest.get('blockhash')
    if blockhash and rpc('isBlockhashValid',[blockhash,{'commitment':'confirmed'}]).get('value') is not True:raise ValueError('WALLET_DRAFT_EXPIRED')
    message=Message.new_with_blockhash(instructions,owner_key,Hash.from_string(recent))
    encoded=base64.b64encode(bytes(message)).decode('ascii')
    fee=_number(rpc('getFeeForMessage',[encoded,{'commitment':'confirmed'}]).get('value'))
    if lamports<fee+rent+(atomic if asset['namespace']=='native' else 0):raise ValueError('WALLET_INSUFFICIENT_SOL_FOR_FEE')
    unsigned=Transaction.new_unsigned(message)
    if len(bytes(unsigned))>1232:raise ValueError('WALLET_TRANSACTION_SIZE')
    simulation=rpc('simulateTransaction',[base64.b64encode(bytes(unsigned)).decode('ascii'),{'encoding':'base64','sigVerify':False,'commitment':'confirmed'}]).get('value')
    if not isinstance(simulation,dict) or simulation.get('err') is not None:raise ValueError('WALLET_SIMULATION_FAILED')
    if store.network(SOL)['endpoint']!=endpoint:raise ValueError('WALLET_RPC_ENDPOINT_CHANGED')
    return {'chain_id':SOL,'account_id':account_id,'asset_id':asset_id,'symbol':asset['symbol'],'mint':asset['reference'] if asset['namespace']=='token' else '',
        'from':owner,'to':recipient,'amount':store.format_atomic(atomic,asset['decimals']),'atomic':str(atomic),'decimals':asset['decimals'],
        'fee_lamports':str(fee),'rent_lamports':str(rent),'cost_sol':store.format_atomic(fee+rent,9),'source_token_account':source,'source_token_accounts':sources,'recipient_token_account':ata,
        'blockhash':recent,'last_valid_block_height':last_height,'message':encoded,'simulation':'PASSED',
        'rpc_endpoint':endpoint,'genesis_hash':MAINNET_GENESIS}


def _digest(body):return hashlib.sha256(store.pack(body).encode()).hexdigest()


def _pending(db,account_id,excluding=''):
    return any(row['id']!=excluding and json.loads(row['body']).get('account_id')==account_id for row in db.execute("SELECT id,body FROM wallet_transfers WHERE state IN ('SIGNING','SUBMITTING','SUBMITTED','UNCERTAIN')"))


def prepare(account_id,asset_id,recipient,amount):
    _recover_interrupted()
    with store.db() as db:
        _table(db)
        if _pending(db,account_id):raise ValueError('WALLET_PENDING_TRANSFER_CHECK_REQUIRED')
        if db.execute("SELECT COUNT(*) FROM wallet_transfers WHERE state IN ('SIGNING','SUBMITTING','SUBMITTED','UNCERTAIN')").fetchone()[0]>=64:raise ValueError('WALLET_PENDING_TRANSFER_LIMIT')
    state=wallet_vault.status();key=next((k for k in state if k['account_id']==account_id and k['vault_available']),None)
    if not key:raise ValueError('WALLET_LOCAL_SIGNER_REQUIRED')
    if not key['backed_up']:raise ValueError('WALLET_BACKUP_REQUIRED')
    body=_build(account_id,asset_id,recipient,amount);body['expires_at']=time.time()+90
    body['review_digest']=_digest(body);identifier=uuid.uuid4().hex
    with store.db(True) as db:
        _table(db)
        db.execute('DELETE FROM wallet_transfers WHERE id IN (SELECT id FROM wallet_transfers WHERE state IN (\'PREPARED\',\'CANCELLED\',\'FAILED\') ORDER BY updated_at DESC LIMIT -1 OFFSET 64)')
        db.execute("DELETE FROM wallet_transfers WHERE id IN (SELECT id FROM wallet_transfers WHERE state IN ('CONFIRMED','FINALIZED') ORDER BY updated_at DESC LIMIT -1 OFFSET 512)")
        db.execute('INSERT INTO wallet_transfers(id,state,body,txid,error,updated_at) VALUES(?,?,?,?,?,?)',(identifier,'PREPARED',store.pack(body),'','',time.time()))
    store.preference('selected_transfer',identifier)
    store.event('wallet','TRANSFER_PREPARED',asset_id,body['amount']+' '+body['symbol']+' · osignerat · simulering klar')
    return snapshot(identifier)


def snapshot(identifier=''):
    _recover_interrupted()
    with store.db() as db:
        _table(db)
        row=db.execute('SELECT * FROM wallet_transfers WHERE id=?',(identifier,)).fetchone() if identifier else db.execute('SELECT * FROM wallet_transfers ORDER BY updated_at DESC LIMIT 1').fetchone()
    if not row:return {}
    value=dict(row);value.pop('worker_pid',None);value.pop('worker_created',None);value['body']=json.loads(value['body'])
    value['expired']=value['state']=='PREPARED' and value['body']['expires_at']<time.time()
    return value


def list_snapshot(account_id=''):
    _recover_interrupted()
    with store.db() as db:
        _table(db)
        rows=db.execute("SELECT id,state,body,txid,error,updated_at FROM wallet_transfers ORDER BY updated_at DESC").fetchall()
    pending=[];recent=[]
    for row in rows:
        value=dict(row);value['body']=json.loads(value['body'])
        if account_id and value['body'].get('account_id')!=account_id:continue
        value['expired']=value['state']=='PREPARED' and value['body']['expires_at']<time.time()
        if value['state'] in {'SIGNING','SUBMITTING','SUBMITTED','UNCERTAIN'}:
            if len(pending)<64:pending.append(value)
        elif len(recent)<16:recent.append(value)
    return pending+recent


def _update(identifier,state,txid='',error=''):
    allowed={'SIGNING':{'SUBMITTING','FAILED'},'SUBMITTING':{'SUBMITTED','UNCERTAIN','CONFIRMED','FINALIZED','FAILED'},
        'SUBMITTED':{'UNCERTAIN','CONFIRMED','FINALIZED','FAILED'},'UNCERTAIN':{'SUBMITTED','CONFIRMED','FINALIZED','FAILED'},
        'CONFIRMED':{'FINALIZED','FAILED'}}
    with store.db(True) as db:
        row=db.execute('SELECT state,txid FROM wallet_transfers WHERE id=?',(identifier,)).fetchone()
        if not row or state not in allowed.get(row['state'],set()):return False
        if row['txid'] and txid!=row['txid']:raise ValueError('WALLET_SIGNATURE_MISMATCH')
        db.execute('UPDATE wallet_transfers SET state=?,txid=?,error=?,updated_at=? WHERE id=?',(state,txid,error,time.time(),identifier))
    return True


def cancel(identifier):
    with store.db(True) as db:
        _table(db)
        db.execute("UPDATE wallet_transfers SET state='CANCELLED',updated_at=? WHERE id=? AND state='PREPARED'",(time.time(),identifier))


def send(identifier,review_digest):
    from backend import wallet_approval
    from urllib.parse import urlsplit
    endpoint=store.network(SOL)['endpoint'];host=urlsplit(endpoint).hostname or ''
    args={'id':identifier,'review_digest':review_digest}
    wallet_approval.require_operation('send_transfer',args,'crypto.solana.transfer',host=host)
    draft=snapshot(identifier);body=draft.get('body') or {};original=dict(body);digest=original.pop('review_digest','')
    if draft.get('state')!='PREPARED' or digest!=review_digest or _digest(original)!=digest:raise ValueError('WALLET_REVIEW_MISMATCH')
    if body.get('rpc_endpoint')!=endpoint or body.get('genesis_hash')!=MAINNET_GENESIS:raise ValueError('WALLET_RPC_ENDPOINT_CHANGED')
    if draft['expired']:raise ValueError('WALLET_DRAFT_EXPIRED')
    key=next((k for k in wallet_vault.status() if k['account_id']==body['account_id'] and k['backed_up'] and k['vault_available']),None)
    if not key or key['pubkey']!=body['from']:raise ValueError('WALLET_SIGNER_MISMATCH')
    current=_build(body['account_id'],body['asset_id'],body['to'],body['amount'],body['blockhash'])
    if any(current[k]!=body[k] for k in ('message','fee_lamports','rent_lamports')):raise ValueError('WALLET_DRAFT_CHANGED')
    if time.time()>body['expires_at']:raise ValueError('WALLET_DRAFT_EXPIRED')
    txid='';broadcast_started=False;claimed=False
    try:
        with store.db(True) as db:
            if _pending(db,body['account_id'],identifier):raise ValueError('WALLET_PENDING_TRANSFER_CHECK_REQUIRED')
            changed=db.execute("UPDATE wallet_transfers SET state='SIGNING',worker_pid=?,worker_created=?,updated_at=? WHERE id=? AND state='PREPARED'",(os.getpid(),_PROCESS_CREATED,time.time(),identifier)).rowcount
            if changed==1:
                with _ACTIVE_LOCK:_ACTIVE.add(identifier)
                claimed=True
        if not claimed:raise ValueError('WALLET_ALREADY_SUBMITTED')
        wallet_approval.require_operation('send_transfer',args,'crypto.solana.transfer',host=host)
        from solders.message import Message
        from solders.transaction import Transaction
        from solders.hash import Hash
        pair=wallet_vault._keypair(body['from'])
        tx=Transaction([pair],Message.from_bytes(base64.b64decode(body['message'],validate=True)),Hash.from_string(body['blockhash']));del pair
        txid=str(tx.signatures[0])
        wallet_approval.require_operation('send_transfer',args,'crypto.solana.transfer',host=host)
        if time.time()>body['expires_at']:raise ValueError('WALLET_DRAFT_EXPIRED')
        if not _update(identifier,'SUBMITTING',txid):raise ValueError('WALLET_ALREADY_SUBMITTED')
        # One broadcast only. Timeouts remain uncertain and are checked by signature.
        broadcast_started=True
        reply=omni_rpc._json(endpoint,{'jsonrpc':'2.0','id':1,'method':'sendTransaction','params':[base64.b64encode(bytes(tx)).decode('ascii'),{'encoding':'base64','skipPreflight':False,'maxRetries':0,'preflightCommitment':'confirmed'}]})
        if not isinstance(reply,dict) or reply.get('id')!=1 or reply.get('result')!=txid:
            _update(identifier,'UNCERTAIN',txid,'WALLET_BROADCAST_NOT_CONFIRMED')
        else:_update(identifier,'SUBMITTED',txid)
    except Exception as exc:
        if claimed:
            _update(identifier,'UNCERTAIN' if broadcast_started else 'FAILED',txid,'WALLET_BROADCAST_NOT_CONFIRMED' if broadcast_started else 'WALLET_SIGNING_FAILED')
            if snapshot(identifier).get('state') in {'CONFIRMED','FINALIZED'}:return snapshot(identifier)
        code=str(exc)
        if not broadcast_started and isinstance(exc,ValueError) and code.startswith('WALLET_'):raise
        raise ValueError('WALLET_BROADCAST_NOT_CONFIRMED' if broadcast_started else 'WALLET_SIGNING_FAILED') from None
    finally:
        if claimed:
            with _ACTIVE_LOCK:_ACTIVE.discard(identifier)
    current=snapshot(identifier)
    if current['state'] in {'SUBMITTED','UNCERTAIN'}:store.event('wallet','TRANSFER_SUBMITTED' if current['state']=='SUBMITTED' else 'TRANSFER_UNCERTAIN',body['asset_id'],'Signatur skapad; kontrollera faktisk nätverksstatus')
    return snapshot(identifier)


def _signature_status(endpoint,txid):
    result=_rpc_at(endpoint,'getSignatureStatuses',[[txid],{'searchTransactionHistory':True}]);values=result.get('value') if isinstance(result,dict) else None
    if not isinstance(values,list) or len(values)!=1:raise ValueError('WALLET_RPC_ERROR')
    context=result.get('context')
    if not isinstance(context,dict):raise ValueError('WALLET_RPC_ERROR')
    slot=_number(context.get('slot'))
    value=values[0]
    if value is not None:
        if not isinstance(value,dict) or 'err' not in value or type(value.get('slot')) is not int or not 0<=value['slot']<2**64:raise ValueError('WALLET_RPC_ERROR')
        if value['err'] is not None and (not isinstance(value['err'],(str,dict)) or not value['err']):raise ValueError('WALLET_RPC_ERROR')
        confirmations=value.get('confirmations');status=value.get('confirmationStatus')
        if 'confirmations' not in value or 'confirmationStatus' not in value or status not in {None,'processed','confirmed','finalized'}:raise ValueError('WALLET_RPC_ERROR')
        if confirmations is not None and (type(confirmations) is not int or not 0<=confirmations<2**64):raise ValueError('WALLET_RPC_ERROR')
        if status=='finalized' and confirmations is not None or status in {'processed','confirmed'} and confirmations is None:raise ValueError('WALLET_RPC_ERROR')
        if status=='confirmed' and confirmations==0 or status=='processed' and confirmations!=0:raise ValueError('WALLET_RPC_ERROR')
        if value['slot']>slot:raise ValueError('WALLET_RPC_ERROR')
    return value,slot


def _apply_signature_status(identifier,draft,value):
    if isinstance(value,dict):
        if value.get('err') is not None and value['confirmationStatus'] in {'confirmed','finalized'}:_update(identifier,'FAILED',draft['txid'],'WALLET_ONCHAIN_FAILED')
        elif value.get('confirmationStatus') in {'confirmed','finalized'}:
            if _update(identifier,value['confirmationStatus'].upper(),draft['txid']):store.event('wallet','TRANSFER_'+value['confirmationStatus'].upper(),draft['body']['asset_id'],'Transaktionen har bekräftad status på Solana')


def _expire_absent_signature(identifier,draft,endpoint):
    """Bounded RPC finality assertion, not an independent consensus proof.

    An absent status alone is insufficient. The original endpoint must assert
    finalized height past the recorded validity window, then provide another
    absent historical status from a context at least as fresh as the finalized
    slot read AFTER that height. Lag, failure, drift and malformed data leave
    the signature unresolved. A concurrent confirmed/finalized result wins.
    """
    body=draft['body']
    if draft['state'] not in {'SUBMITTED','UNCERTAIN'}:return
    # Legacy drafts did not persist the endpoint/genesis. Never infer the
    # missing binding to unlock an ambiguous legacy send.
    if body.get('rpc_endpoint')!=endpoint or body.get('genesis_hash')!=MAINNET_GENESIS:return
    last_height=_number(body.get('last_valid_block_height'))
    before=_number(_rpc_at(endpoint,'getSlot',[{'commitment':'finalized'}]))
    height=_number(_rpc_at(endpoint,'getBlockHeight',[{'commitment':'finalized','minContextSlot':before}]))
    if height<=last_height:return
    after=_number(_rpc_at(endpoint,'getSlot',[{'commitment':'finalized','minContextSlot':before}]))
    if after<before:raise ValueError('WALLET_RPC_ERROR')
    value,context_slot=_signature_status(endpoint,draft['txid'])
    if context_slot<after:raise ValueError('WALLET_RPC_ERROR')
    _identity(endpoint)
    if store.network(SOL)['endpoint']!=endpoint:raise ValueError('WALLET_RPC_ENDPOINT_CHANGED')
    if value is not None:
        _apply_signature_status(identifier,draft,value)
        return
    with store.db(True) as db:
        changed=db.execute("UPDATE wallet_transfers SET state='FAILED',error='WALLET_TRANSACTION_EXPIRED',updated_at=? WHERE id=? AND txid=? AND state IN ('SUBMITTED','UNCERTAIN')",
            (time.time(),identifier,draft['txid'])).rowcount
    if changed:store.event('wallet','TRANSFER_EXPIRED',body['asset_id'],'Signaturen saknas efter giltighetstiden enligt det bundna RPC-nätverkets finaliserade historik; ingen ny signering gjordes')


def check(identifier):
    draft=snapshot(identifier)
    if draft.get('state') not in {'SUBMITTED','SUBMITTING','UNCERTAIN','CONFIRMED'} or not draft.get('txid'):raise ValueError('WALLET_SIGNATURE_REQUIRED')
    endpoint=store.network(SOL)['endpoint'];original=draft['body'].get('rpc_endpoint')
    if original and original!=endpoint:raise ValueError('WALLET_RPC_ENDPOINT_CHANGED')
    if original and draft['body'].get('genesis_hash')!=MAINNET_GENESIS:raise ValueError('WALLET_WRONG_NETWORK')
    _identity(endpoint);value,_=_signature_status(endpoint,draft['txid'])
    if store.network(SOL)['endpoint']!=endpoint:raise ValueError('WALLET_RPC_ENDPOINT_CHANGED')
    _apply_signature_status(identifier,draft,value)
    if value is None:_expire_absent_signature(identifier,draft,endpoint)
    return snapshot(identifier)
