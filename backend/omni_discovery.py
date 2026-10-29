"""Bounded public asset discovery. A ticker never grants an asset identity."""
import time
from backend import omni_assets as store,omni_rpc

TOKEN_PROGRAM='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
MAX_MINTS=128


def _table(db):
    db.execute('CREATE TABLE IF NOT EXISTS wallet_discovery(account_id TEXT PRIMARY KEY,body TEXT NOT NULL)')


def reports():
    import json
    with store.db() as db:
        _table(db)
        return {r['account_id']:json.loads(r['body']) for r in db.execute('SELECT * FROM wallet_discovery')}


def discover(account_id):
    state=store.snapshot();account=next((a for a in state['accounts'] if a['id']==account_id),None)
    if not account:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
    network=store.network(account['chain_id'])
    if network['family']!='solana':
        return {'state':'INDEXER_REQUIRED' if network['family']=='evm' else 'REGISTERED_ASSETS_ONLY','asset_ids':[]}
    store.event('wallet','DISCOVERY_STARTED','',network['name']+' · läser båda Solana-tokenprogrammen')
    try:
        result=_solana(network,account)
        result.update(state='PARTIAL' if result['truncated'] else 'READY',observed_at=time.time())
        with store.db(True) as db:
            _table(db);db.execute('INSERT OR REPLACE INTO wallet_discovery VALUES(?,?)',(account_id,store.pack(result)))
        store.event('wallet','DISCOVERY_PARTIAL' if result['truncated'] else 'DISCOVERY_COMPLETED','',str(len(result['asset_ids']))+' tokenmintar lästa · '+str(result['token_accounts'])+' tokenkonton')
        return result
    except Exception:
        previous=reports().get(account_id,{})
        previous.update(state='READ_FAILED',attempted_at=time.time())
        with store.db(True) as db:
            _table(db);db.execute('INSERT OR REPLACE INTO wallet_discovery VALUES(?,?)',(account_id,store.pack(previous)))
            import json
            token_ids={a['id'] for a in state['assets'] if a['chain_id']==account['chain_id'] and a['namespace']=='token'}
            for row in db.execute('SELECT asset_id,body FROM observations WHERE account_id=?',(account_id,)).fetchall():
                if row['asset_id'] not in token_ids:continue
                observation=json.loads(row['body']);observation['state']='READ_FAILED';observation['attempted_at']=time.time()
                db.execute('UPDATE observations SET body=? WHERE asset_id=? AND account_id=?',(store.pack(observation),row['asset_id'],account_id))
        store.event('wallet','DISCOVERY_FAILED','','Tokenläsning misslyckades; tidigare saldon bevaras')
        raise


def _solana(network,account):
    omni_rpc._sol_identity(network)
    address=account['address'];groups={};seen=set()
    for program in (TOKEN_PROGRAM,TOKEN_2022):
        response=omni_rpc.rpc(network,'getTokenAccountsByOwner',[address,{'programId':program},{'encoding':'jsonParsed','commitment':'confirmed'}])
        rows=response.get('value') if isinstance(response,dict) else None
        if not isinstance(rows,list) or len(rows)>512:raise ValueError('OMNI_DISCOVERY_SIZE')
        for row in rows:
            pubkey=store.address_for(network,row.get('pubkey'))
            if pubkey in seen:raise ValueError('OMNI_DISCOVERY_DUPLICATE')
            seen.add(pubkey)
            data=row.get('account') or {};parsed=(data.get('data') or {}).get('parsed') or {};info=parsed.get('info') or {}
            amount=info.get('tokenAmount') or {};atomic=amount.get('amount');decimals=amount.get('decimals')
            if data.get('owner')!=program or parsed.get('type')!='account' or info.get('owner')!=address or info.get('state') not in {'initialized','frozen'}:raise ValueError('OMNI_TOKEN_ACCOUNT_IDENTITY')
            if not isinstance(atomic,str) or not 1<=len(atomic)<=20 or not atomic.isascii() or not atomic.isdigit() or int(atomic)>=2**64 or type(decimals) is not int or not 0<=decimals<=255:raise ValueError('OMNI_BALANCE_SCHEMA')
            mint=store.address_for(network,info.get('mint'));key=(mint,program)
            if key not in groups:groups[key]={'atomic':0,'decimals':decimals}
            if groups[key]['decimals']!=decimals:raise ValueError('OMNI_TOKEN_ACCOUNT_IDENTITY')
            groups[key]['atomic']+=int(atomic)
            if groups[key]['atomic']>=2**64:raise ValueError('OMNI_BALANCE_SCHEMA')
    keys=sorted(groups,key=lambda k:(groups[k]['atomic']==0,k));truncated=len(keys)>MAX_MINTS;keys=keys[:MAX_MINTS];validated=[]
    # Validate every selected mint before publishing any new asset/balance.
    for offset in range(0,len(keys),64):
        batch=keys[offset:offset+64]
        reply=omni_rpc.rpc(network,'getMultipleAccounts',[[mint for mint,_ in batch],{'encoding':'jsonParsed','commitment':'confirmed'}])
        values=reply.get('value') if isinstance(reply,dict) else None
        if not isinstance(values,list) or len(values)!=len(batch):raise ValueError('OMNI_DISCOVERY_MINTS')
        for key,value in zip(batch,values):
            mint,program=key;parsed=((value or {}).get('data') or {}).get('parsed') or {};info=parsed.get('info') or {};balance=groups[key]
            if not value or value.get('owner')!=program or parsed.get('type')!='mint' or info.get('isInitialized') is not True or info.get('decimals')!=balance['decimals']:raise ValueError('OMNI_DISCOVERY_MINT_IDENTITY')
            metadata={}
            for extension in info.get('extensions') or []:
                if isinstance(extension,dict) and extension.get('extension')=='tokenMetadata':
                    candidate=extension.get('state') or {}
                    if candidate.get('mint')==mint:metadata=candidate
            validated.append((mint,balance,metadata))
    from backend import solana_metadata
    try:names=solana_metadata.batch(network,[mint for mint,_,metadata in validated if not metadata.get('symbol')])
    except Exception:names={}  # Optional names do not invalidate verified balances.
    now=time.time();asset_ids=[]
    for mint,balance,metadata in validated:
        metadata=metadata or names.get(mint,{})
        asset=store.register_asset(network['id'],'token',mint,store.text(metadata.get('symbol'),24) or mint[:6],store.text(metadata.get('name'),96) or 'SPL '+mint[:8],balance['decimals'],metadata='RPC_METADATA')
        asset_ids.append(asset['id'])
        observation={'asset_id':asset['id'],'account_id':account['id'],'atomic':str(balance['atomic']),
            'quantity':store.format_atomic(balance['atomic'],balance['decimals']),'observed_at':now,'state':'VERIFIED_READ',
            'source':network['endpoint'],'identity_level':'GENESIS_AND_MINT_ACCOUNT','decimals':balance['decimals']}
        with store.db(True) as db:db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account['id'],store.pack(observation)))
    found={mint for mint,_ in groups}
    for asset in store.snapshot()['assets']:
        if asset['chain_id']!=network['id'] or asset['namespace']!='token' or asset['reference'] in found:continue
        # Both programs were read completely. No account for this mint is a
        # real zero; an RPC failure never reaches this branch.
        observation={'asset_id':asset['id'],'account_id':account['id'],'atomic':'0','quantity':'0','observed_at':now,'state':'VERIFIED_READ',
            'source':network['endpoint'],'identity_level':'GENESIS_AND_COMPLETE_OWNER_SCAN','decimals':asset['decimals']}
        with store.db(True) as db:db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account['id'],store.pack(observation)))
    return {'asset_ids':asset_ids,'token_accounts':len(seen),'truncated':truncated,'programs':[TOKEN_PROGRAM,TOKEN_2022]}
