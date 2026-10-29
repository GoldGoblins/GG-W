"""Prepared multi-network wallet view; public watch balances and local GG lab.

No symbol-based price matching, no implied custody, no missing-balance zeroes.
"""
from decimal import Decimal,InvalidOperation,localcontext
import json
import time
from backend import omni_assets as store,crypto_explorer as markets
MAX_POSITIONS=2048


def _summary(rows,accounts):
    with localcontext() as context:
        context.prec=420
        total=sum((Decimal(r['value_usd']) for r in rows if r['value_usd'] is not None),Decimal(0))
    priced=sum(r['value_usd'] is not None for r in rows)
    return {'known_value_usd':format(total,'f') if priced else None,'priced_count':priced,
        'position_count':len(rows),'unpriced_count':len(rows)-priced,'account_count':len(accounts),
        'network_count':len({a['chain_id'] for a in accounts}),
        'nonzero_count':sum(r.get('atomic') is not None and int(r['atomic'])>0 for r in rows),
        'zero_count':sum(r.get('atomic') is not None and int(r['atomic'])==0 for r in rows),
        'unread_count':sum(r['balance_state']=='NOT_FETCHED' for r in rows),
        'failed_count':sum(r['balance_state']=='READ_FAILED' for r in rows),
        'stale_count':sum(r['balance_state']=='VERIFIED_READ' and not r.get('balance_current') for r in rows),
        'last_read_at':max((r.get('observed_at') or 0 for r in rows if r['balance_state']=='VERIFIED_READ'),default=0)}


def _valuation(atomic,decimals,market):
    if atomic is None or not market or market.get('price_usd') is None:return None
    try:
        with localcontext() as context:
            context.prec=420
            value=Decimal(atomic)/(Decimal(10)**decimals)*Decimal(str(market['price_usd']))
            if not value.is_finite() or value<0 or value>Decimal('1e100'):return None
            return format(value.quantize(Decimal('.01')),'f')
    except (InvalidOperation,ValueError,OverflowError):return None


def snapshot(state=None,lab=None):
    from backend import token_market_prices as prices
    from backend import wallet_mnemonic
    state=store.snapshot() if state is None else state
    setup=wallet_mnemonic.account_metadata()
    if lab is None:
        from backend import omni_lab
        lab=omni_lab.snapshot()
    assets={a['id']:a for a in state['assets']};nets={n['id']:n for n in state['networks']};accounts={a['id']:a for a in state['accounts']}
    with markets._db() as db:
        observations=[json.loads(r[0]) for r in db.execute('SELECT body FROM observations ORDER BY rowid DESC LIMIT ?',(MAX_POSITIONS+1,))]
        count=db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        bound={r['asset_id']:json.loads(r['body']) for r in db.execute('SELECT b.asset_id,r.body FROM explorer_bindings b JOIN explorer_rows r ON b.market_id=r.id')}
        token_quotes={r['asset_id']:json.loads(r['body']) for r in db.execute('SELECT asset_id,body FROM wallet_quotes')}
    from backend import wallet_vault,omni_discovery
    local_wallets=wallet_vault.status();discovery=omni_discovery.reports()
    signing={k['account_id']:k for k in local_wallets}
    rows=[];known=set()
    for obs in observations[:MAX_POSITIONS]:
        asset=assets.get(obs['asset_id']);account=accounts.get(obs['account_id'])
        if not asset or not account or asset['chain_id']!=account['chain_id']:continue
        known.add((asset['id'],account['id']));market=bound.get(asset['id'])
        fallback=token_quotes.get(asset['id'])
        aggregate_current=market and market.get('provider')=='coingecko' and market.get('price_usd') is not None and prices.fresh(market)
        if fallback and not aggregate_current and fallback.get('price_usd') is not None and prices.fresh(fallback):market=fallback
        if not market and fallback:market=fallback
        age=time.time()-(market.get('observed_at') or 0) if market else None
        price_current=age is not None and prices.fresh(market) and market.get('price_usd') is not None
        balance_age=time.time()-(obs.get('observed_at') or 0);balance_current=0<=balance_age<=300
        atomic=obs.get('atomic');value=_valuation(atomic,asset['decimals'],market) if price_current and balance_current and obs.get('state')=='VERIFIED_READ' and asset.get('metadata')!='DECIMALS_UNKNOWN' else None
        rows.append({'id':asset['id']+'@'+account['id'],'asset_id':asset['id'],'account_id':account['id'],'chain_id':asset['chain_id'],
            'network':nets[asset['chain_id']]['name'],'symbol':asset['symbol'],'name':asset['name'],'quantity':obs.get('quantity','—'),
            'atomic':atomic,'decimals':asset['decimals'],'balance_state':obs.get('state','UNKNOWN'),'observed_at':obs.get('observed_at'),
            'value_usd':value,'price_state':'CURRENT' if price_current else 'STALE_OR_MISSING','scope':'PUBLIC_WATCH',
            'price_usd':market.get('price_usd') if price_current else None,
            'price_source':market.get('source','') if market else '',
            'price_observed_at':market.get('observed_at') if market else None,
            'price_source_timestamp':market.get('source_timestamp') or market.get('updated_at') or None if market else None,
            'price_quality':market.get('quality') or market.get('valuation') or 'UNKNOWN' if market else 'UNPRICED',
            'liquidity_usd':market.get('liquidity_usd') if market else None,
            'price_basis':market.get('price_basis') or market.get('valuation') or 'UNKNOWN' if market else 'UNKNOWN',
            'price_stale':not price_current or market.get('state') in ('LAST_GOOD','STALE') if market else True,
            'price_reason':market.get('reason','') if market else 'NOT_FETCHED',
            'change_24h':market.get('change_24h') if price_current else None,
            'sparkline':(market.get('sparkline') or {}) if market else {},
            'balance_current':balance_current,
            'address':account['address'],'label':account['label'],'pending_atomic':obs.get('pending_atomic'),
            'signer_state':'LOCAL_ENCRYPTED' if account['id'] in signing else 'WATCH_ONLY'})
    by_chain={}
    for asset in state['assets']:by_chain.setdefault(asset['chain_id'],[]).append(asset)
    position_count=sum(len(by_chain.get(account['chain_id'],[])) for account in accounts.values())
    for account in accounts.values():
        if len(rows)>=MAX_POSITIONS:break
        for asset in by_chain.get(account['chain_id'],[]):
            if len(rows)>=MAX_POSITIONS:break
            if asset['chain_id']!=account['chain_id'] or (asset['id'],account['id']) in known:continue
            if len(rows)>=2048:break
            rows.append({'id':asset['id']+'@'+account['id'],'asset_id':asset['id'],'account_id':account['id'],'chain_id':asset['chain_id'],
                'network':nets[asset['chain_id']]['name'],'symbol':asset['symbol'],'name':asset['name'],'quantity':'—','atomic':None,
                'decimals':asset['decimals'],'balance_state':'NOT_FETCHED','observed_at':None,'value_usd':None,'scope':'PUBLIC_WATCH',
                'address':account['address'],'label':account['label'],
                'signer_state':'LOCAL_ENCRYPTED' if account['id'] in signing else 'WATCH_ONLY'})
    lab_rows=[]
    if (lab.get('verification') or {}).get('state')=='VERIFIED':
        for i,participant in enumerate(lab.get('participants',[])):
            lab_rows.append({'id':lab['chain_id']+'@'+participant['address'],'asset_id':lab['chain_id']+'/native:GG-LAB',
                'lab_index':i,
                'chain_id':lab['chain_id'],'symbol':'GG-LAB','network':'GG lokalt nätverkslabb','quantity':participant['balance'],'address':participant['address'],
                'label':'GG labbkonto '+str(i+1),'balance_state':'LOCAL_LEDGER_VERIFIED','scope':'LOCAL_LAB','value_usd':None})
    with localcontext() as context:
        context.prec=420;total=sum((Decimal(r['value_usd']) for r in rows if r['value_usd'] is not None),Decimal(0))
    priced=sum(r['value_usd'] is not None for r in rows)
    for item in rows:
        if item.get('account_id') in setup: item.update(setup[item['account_id']])
    account_rows=[dict(item,**setup.get(item['id'],{})) for item in accounts.values()]
    return {'rows':rows,'lab_rows':lab_rows,'accounts':account_rows,'account_setup':setup,'networks':state['networks'],
            'discovery_adapters':{n['id']:('SPL_AND_TOKEN_2022' if n['family']=='solana' else 'INDEXER_REQUIRED' if n['family']=='evm' else 'REGISTERED_ASSETS_ONLY') for n in state['networks']},
            'local_wallets':local_wallets,'discovery':discovery,'wallet_creation':'WINDOWS_ENCRYPTED_SOLANA' if __import__('os').name=='nt' else 'SECURE_STORAGE_ADAPTER_REQUIRED',
            'summary':_summary(rows,account_rows),
            'account_summaries':{a['id']:_summary([r for r in rows if r['account_id']==a['id']],[a]) for a in account_rows},
            'network_summaries':{chain:_summary([r for r in rows if r['chain_id']==chain],[a for a in account_rows if a['chain_id']==chain]) for chain in {a['chain_id'] for a in account_rows}},
            'known_value_usd':format(total,'f') if priced else None,'priced_count':priced,'unpriced_count':position_count-priced,
            'incomplete':priced<position_count,'truncated':count>MAX_POSITIONS or position_count>len(rows),
            'position_count':position_count,'displayed_positions':len(rows),'observation_count':count,'events':state['events'],
            'price_policy':{'mode':'MANUAL_ONLY','minimum_refresh_seconds':60,'max_age_seconds':300,
                            'max_tokens_per_job':64,'scope':'ACTUAL_POSITIONS_FAVOURITES_OR_EXPLICIT_SELECTION'},
            'custody':'PUBLIC_WATCH_AND_SESSION_LAB','signing':'EXTERNAL_ADAPTER_REQUIRED','bridge':'NO_VERIFIED_ROUTE'}


def refresh_wallet(account_ids=None):
    """One finite read job; validate the complete work set before any RPC."""
    from backend import omni_service
    state=store.snapshot();accounts=state['accounts'];assets=state['assets']
    if account_ids is not None:
        if not isinstance(account_ids,list) or not account_ids or len(account_ids)>32 or any(not isinstance(i,str) for i in account_ids):raise ValueError('OMNI_WALLET_ACCOUNT_FILTER')
        requested=set(account_ids)
        if requested-{a['id'] for a in accounts}:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
        accounts=[a for a in accounts if a['id'] in requested]
    families={n['id']:n['family'] for n in state['networks']}
    positions=[(asset,account) for account in accounts for asset in assets if asset['chain_id']==account['chain_id'] and (families[account['chain_id']]!='solana' or asset['namespace']=='native')]
    if len(positions)>64:raise ValueError('OMNI_WALLET_REFRESH_LIMIT')
    store.event('wallet','OVERVIEW_READ_STARTED','',str(len(accounts))+' konton · '+str(len(positions))+' saldon')
    failures=0;quote_assets={asset['id'] for asset,_ in positions};discovered_assets=set();solana_accounts=[]
    for asset,account in positions:
        try:omni_service._action('refresh_balance',store.pack({'asset_id':asset['id'],'account_id':account['id']}))
        except Exception:failures+=1
    for account in accounts:
        if store.network(account['chain_id'])['family']=='solana':
            solana_accounts.append(account['id'])
            try:
                from backend import omni_discovery
                discovered_assets.update(omni_discovery.discover(account['id']).get('asset_ids',[]))
            except Exception:failures+=1
    if solana_accounts:
        # Only actual positions for the selected accounts are price targets.
        # A CoinGecko/explorer listing is no longer a prerequisite for a mint.
        with markets._db() as db:
            observed={r['asset_id'] for r in db.execute('SELECT asset_id,account_id FROM observations') if r['account_id'] in solana_accounts}
            registered={r[0] for r in db.execute('SELECT id FROM assets')}
        quote_assets.update((observed|discovered_assets)&registered)
    if quote_assets:
        try:markets.refresh_wallet_quotes(sorted(quote_assets))
        except Exception:
            failures+=1;store.event('wallet','QUOTES_UNAVAILABLE','','Priser kunde inte uppdateras; senaste observationer finns kvar')
    store.event('wallet','OVERVIEW_READ_PARTIAL' if failures else 'OVERVIEW_READ_COMPLETED','',str(len(positions))+' saldon behandlade · '+str(failures)+' läsfel')
    if failures:raise ValueError('OMNI_WALLET_REFRESH_PARTIAL')


def refresh_account(account_id):
    from backend import omni_service
    state=store.snapshot();account=next((a for a in state['accounts'] if a['id']==account_id),None)
    if not account:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
    assets=[a for a in state['assets'] if a['chain_id']==account['chain_id']]
    if len(assets)>24:raise ValueError('OMNI_REFRESH_SELECT_ASSET_FOR_LARGE_ACCOUNT')
    store.event('wallet','ACCOUNT_READ_STARTED','',account['label']+' · '+str(len(assets))+' registrerade tillgångar')
    failures=[]
    for asset in assets:
        try:omni_service._action('refresh_balance',store.pack({'asset_id':asset['id'],'account_id':account_id}))
        except Exception:failures.append(asset['symbol'])
    store.event('wallet','REFRESH_PARTIAL' if failures else 'REFRESHED','',account['label']+' · '+str(len(assets)-len(failures))+'/'+str(len(assets))+' saldon')
    if failures:raise ValueError('OMNI_ACCOUNT_REFRESH_PARTIAL')
