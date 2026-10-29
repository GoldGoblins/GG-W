"""Public market discovery: provider entities, canonical assets and DEX pools.

Discovery does not mint assets or imply an executable trade. Missing data stays
missing. All network work is explicit and runs outside Qt's GUI thread.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
import threading
import time
from urllib.parse import urlencode,quote
from backend import omni_assets as store,omni_rpc

LOCK=threading.RLock()
SOL='solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp'
CHAINS={'ethereum':'eip155:1','bsc':'eip155:56','polygon':'eip155:137','arbitrum':'eip155:42161',
        'optimism':'eip155:10','base':'eip155:8453','avalanche':'eip155:43114','solana':SOL,'tron':'tron:mainnet'}
PLATFORMS={'ethereum':'eip155:1','binance-smart-chain':'eip155:56','polygon-pos':'eip155:137','arbitrum-one':'eip155:42161',
           'optimistic-ethereum':'eip155:10','base':'eip155:8453','avalanche':'eip155:43114','solana':SOL,'tron':'tron:mainnet'}
NATIVES={'bitcoin':'bip122:000000000019d6689c085ae165831e93','ethereum':'eip155:1','binancecoin':'eip155:56',
         'solana':SOL,'kaspa':'kaspa:mainnet','tron':'tron:mainnet','cardano':'cardano:mainnet',
         'polygon-ecosystem-token':'eip155:137','avalanche-2':'eip155:43114'}
PROVIDERS={'coingecko':{'name':'CoinGecko','ttl':120,'spacing':3},'dexscreener':{'name':'DEX Screener','ttl':30,'spacing':1}}
_last_request={}


def _tables(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS explorer_cache(key TEXT PRIMARY KEY,body TEXT NOT NULL,ts REAL NOT NULL,attempt REAL NOT NULL,error TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS explorer_rows(id TEXT PRIMARY KEY,body TEXT NOT NULL,ts REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS explorer_prefs(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS explorer_stars(id TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS explorer_bindings(asset_id TEXT PRIMARY KEY,market_id TEXT NOT NULL,verified TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS explorer_prices(id TEXT NOT NULL,ts INTEGER NOT NULL,price REAL NOT NULL,PRIMARY KEY(id,ts));
      CREATE TABLE IF NOT EXISTS wallet_quotes(asset_id TEXT PRIMARY KEY,body TEXT NOT NULL,ts REAL NOT NULL);
    ''')


def _db(write=False):
    # Schema work completes before a transaction; executescript would commit it.
    with store.db() as db:_tables(db)
    return store.db(write)


def pref(key,value=None):
    if key not in {'view','query','chain','sort','page','selected','paused','min_liquidity','hide_unpriced'}:raise ValueError('EXPLORER_PREFERENCE')
    with _db(value is not None) as db:
        if value is not None:db.execute('INSERT OR REPLACE INTO explorer_prefs VALUES(?,?)',(key,store.pack(value)))
        row=db.execute('SELECT value FROM explorer_prefs WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def number(value,negative=False):
    if isinstance(value,bool) or value is None:return None
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return None
    return value if math.isfinite(value) and abs(value)<=1e100 and (negative or value>=0) else None


def _id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[-\w.]{1,128}',value):raise ValueError('EXPLORER_PROVIDER_ID')
    return value


def _known_native(coin):
    chain=NATIVES.get(coin)
    if not chain:return ''
    try:net=store.network(chain)
    except ValueError:return ''
    return chain+'/native:'+net['symbol']


def sparkline(value):
    """Bound a provider week without inventing points or dropping real spikes."""
    prices=value.get('price') if isinstance(value,dict) else None
    if not isinstance(prices,list) or not 2<=len(prices)<=512:return []
    values=[number(n) for n in prices]
    if any(n is None for n in values):return []
    if len(values)<=128:return values
    result=[values[0]]
    # Preserve chronological extrema in each bucket, plus both endpoints.
    for bucket in range(62):
        start=1+(len(values)-2)*bucket//62;end=1+(len(values)-2)*(bucket+1)//62
        indices=range(start,end)
        if not indices:continue
        for index in sorted({min(indices,key=values.__getitem__),max(indices,key=values.__getitem__)}):result.append(values[index])
    return result+[values[-1]]


def parse_coins(raw):
    if not isinstance(raw,list) or len(raw)>250:raise ValueError('EXPLORER_COINS_RESPONSE')
    rows=[];seen=set()
    for item in raw:
        if not isinstance(item,dict):raise ValueError('EXPLORER_COINS_ROW')
        coin=_id(item.get('id'));identifier='coingecko:'+coin
        if identifier in seen:continue
        seen.add(identifier);asset_id=_known_native(coin)
        rows.append({'id':identifier,'provider':'coingecko','provider_id':coin,'source':'CoinGecko','kind':'NATIVE' if coin in NATIVES else 'COIN_OR_TOKEN',
            'asset_id':asset_id,'chain_id':NATIVES.get(coin,''),'symbol':store.text(item.get('symbol'),24).upper(),
            'name':store.text(item.get('name'),96),'rank':number(item.get('market_cap_rank')),
            'price_usd':number(item.get('current_price')),'change_24h':number(item.get('price_change_percentage_24h'),True),
            'market_cap':number(item.get('market_cap')),'volume_24h':number(item.get('total_volume')),'liquidity_usd':None,
            'updated_at':store.text(item.get('last_updated'),64),'observed_at':time.time(),'valuation':'AGGREGATE_MARKET_ESTIMATE',
            'identity':'CONFIGURED_NATIVE' if asset_id else 'PROVIDER_ENTITY_UNRESOLVED','safety':'NOT_ASSESSED','pools':[],
            'sparkline':{'prices':sparkline(item.get('sparkline_in_7d')),'period':'7D','source':'CoinGecko'}})
    return rows


def parse_pairs(raw):
    values=raw.get('pairs') if isinstance(raw,dict) else raw
    if not isinstance(values,list) or len(values)>1000:raise ValueError('EXPLORER_PAIRS_RESPONSE')
    groups={}
    for pair in values:
        if not isinstance(pair,dict):raise ValueError('EXPLORER_PAIRS_ROW')
        network=_id(pair.get('chainId'));chain=CHAINS.get(network,'');base=pair.get('baseToken') or {};reference=str(base.get('address') or '')
        if not reference or len(reference)>160:continue
        namespace='asset';asset_id=''
        if chain:
            try:
                net=store.network(chain);reference=store.address_for(net,reference)
                namespace='erc20' if net['family']=='evm' else 'token' if net['family']=='solana' else 'asset'
                asset_id=chain+'/'+namespace+':'+reference
            except ValueError:continue
        # Keep unknown chains visible as discovery; no adapter identity invented.
        identifier='dex:'+network+':'+reference
        pool_ref=str(pair.get('pairAddress') or '')
        if not pool_ref or len(pool_ref)>160:continue
        price=number(pair.get('priceUsd'));liquidity=number((pair.get('liquidity') or {}).get('usd'))
        pool={'id':network+':'+pool_ref,'address':pool_ref,'dex':store.text(pair.get('dexId'),40),
              'quote_symbol':store.text((pair.get('quoteToken') or {}).get('symbol'),24),'price_usd':price,
              'liquidity_usd':liquidity,'volume_24h':number((pair.get('volume') or {}).get('h24')),
              'base_address':reference,'price_side':'BASE_ONLY'}
        if identifier not in groups:
            groups[identifier]={'id':identifier,'provider':'dexscreener','source':'DEX Screener','kind':'TOKEN','provider_id':reference,'reference':reference,
                'chain_id':chain,'provider_chain':network,'asset_id':asset_id,'symbol':store.text(base.get('symbol'),24),'name':store.text(base.get('name'),96),
                'rank':None,'price_usd':None,'change_24h':None,'market_cap':None,'volume_24h':None,'liquidity_usd':None,
                'observed_at':time.time(),'updated_at':'','identity':'CHAIN_ADDRESS' if asset_id else 'UNSUPPORTED_CHAIN_DISCOVERY',
                'valuation':'SINGLE_POOL_ESTIMATE','safety':'NOT_ASSESSED','pools':[],'promotion':False}
        row=groups[identifier]
        if any(old['id']==pool['id'] for old in row['pools']):continue
        row['pools'].append(pool)
        best=not row.get('representative_pool') or (liquidity or 0)>(row['liquidity_usd'] or 0)
        if best:
            row.update(price_usd=price,liquidity_usd=liquidity,volume_24h=pool['volume_24h'],representative_pool=pool['id'],
                change_24h=number((pair.get('priceChange') or {}).get('h24'),True),market_cap=number(pair.get('marketCap')),
                promotion=bool((pair.get('boosts') or {}).get('active')))
    for row in groups.values():row['pools'].sort(key=lambda p:p['liquidity_usd'] or 0,reverse=True)
    return list(groups.values())


def _cache_get(key):
    with _db() as db:row=db.execute('SELECT * FROM explorer_cache WHERE key=?',(key,)).fetchone()
    if not row:return None
    result=dict(row)
    try:
        value=json.loads(result['body'])
        if not isinstance(value,(list,dict)):raise ValueError('EXPLORER_CACHE_SCHEMA')
    except (ValueError,TypeError):result.update(body='[]',ts=0,attempt=0,error='EXPLORER_CACHE_CORRUPT')
    return result


def _resource(provider,key,url,parser,force=False,ttl=None,max_bytes=None):
    with LOCK:
        cached=_cache_get(key);now=time.time();ttl=PROVIDERS[provider]['ttl'] if ttl is None else ttl
        if cached and cached['error'] and 0<=now-cached['attempt']<15:raise ValueError('EXPLORER_SOURCE_COOLDOWN')
        if cached and ((0<=now-cached['ts']<ttl and not force) or 0<=now-cached['attempt']<15):return json.loads(cached['body'])
        wait=PROVIDERS[provider]['spacing']-(now-_last_request.get(provider,0))
        if wait>0:time.sleep(min(wait,3))
        _last_request[provider]=time.time()
        store.event('market','REQUEST_STARTED','',PROVIDERS[provider]['name']+' · '+key.split(':',1)[0])
        try:
            body=parser(omni_rpc._json(url,max_bytes=max_bytes) if max_bytes is not None else omni_rpc._json(url))
            encoded=store.pack(body)
            with _db(True) as db:
                db.execute('INSERT OR REPLACE INTO explorer_cache VALUES(?,?,?,?,?)',(key,encoded,now,now,''))
                db.execute('DELETE FROM explorer_cache WHERE key NOT IN (SELECT key FROM explorer_cache ORDER BY attempt DESC LIMIT 128)')
            store.event('market','REQUEST_COMPLETED','',PROVIDERS[provider]['name']+' · svar validerat'+(' · '+str(len(body))+' poster' if isinstance(body,list) else ''))
            return body
        except Exception as exc:
            error=str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}',str(exc)) else type(exc).__name__
            with _db(True) as db:
                db.execute('INSERT OR REPLACE INTO explorer_cache VALUES(?,?,?,?,?)',(key,cached['body'] if cached else '[]',cached['ts'] if cached else 0,now,error))
            store.event('market','REQUEST_FAILED','',PROVIDERS[provider]['name']+' · '+error)
            raise ValueError('EXPLORER_SOURCE_UNAVAILABLE') from None


def _save_rows(rows,preserve_search_quotes=False):
    with _db(True) as db:
        for row in rows:
            if preserve_search_quotes and row.get('provider')=='coingecko' and row.get('price_usd') is None:
                # CoinGecko search has no quote observation. Keep the existing
                # canonical market row and its original freshness timestamp;
                # the search cache still contains the unpriced search entity.
                previous=db.execute('SELECT body FROM explorer_rows WHERE id=?',(row['id'],)).fetchone()
                previous=json.loads(previous['body']) if previous else None
                if previous and previous.get('provider')=='coingecko' and previous.get('provider_id')==row.get('provider_id') and previous.get('price_usd') is not None:
                    continue
            db.execute('INSERT OR REPLACE INTO explorer_rows VALUES(?,?,?)',(row['id'],store.pack(row),time.time()))
            if row.get('asset_id') and row.get('identity')=='CONFIGURED_NATIVE':
                db.execute('INSERT OR IGNORE INTO explorer_bindings VALUES(?,?,?)',(row['asset_id'],row['id'],'CONFIGURED_NATIVE_IDENTITY'))
            if row.get('price_usd') is not None:
                ts=int(row.get('observed_at') or time.time())
                db.execute('INSERT OR IGNORE INTO explorer_prices VALUES(?,?,?)',(row['id'],ts,row['price_usd']))
        db.execute('DELETE FROM explorer_prices WHERE rowid NOT IN (SELECT rowid FROM explorer_prices ORDER BY ts DESC LIMIT 25000)')
        db.execute('DELETE FROM explorer_rows WHERE id NOT IN (SELECT id FROM explorer_rows ORDER BY ts DESC LIMIT 5000) AND id NOT IN (SELECT id FROM explorer_stars)')


def row(identifier):
    with _db() as db:value=db.execute('SELECT body FROM explorer_rows WHERE id=?',(identifier,)).fetchone()
    if not value:raise ValueError('EXPLORER_ROW_NOT_FOUND')
    return json.loads(value[0])


def _targeted_coins(coins):
    """Reuse per-entity fresh quotes across wallet/favourites before batching."""
    from backend import token_market_prices as prices
    coins=set(coins);cached={};now=time.time()
    with _db() as db:
        for coin in coins:
            saved=db.execute('SELECT body FROM explorer_rows WHERE id=?',('coingecko:'+coin,)).fetchone()
            value=json.loads(saved[0]) if saved else None
            if value and value.get('provider_id')==coin and prices.decimal(value.get('price_usd'),positive=True) is not None and prices.fresh(value,prices.TTL):cached[coin]=value
    needed=coins-set(cached)
    if needed:
        identifiers=','.join(sorted(_id(coin) for coin in needed))
        def parser(value):
            rows=parse_coins(value)
            if any(r['provider_id'] not in needed for r in rows):raise ValueError('EXPLORER_WALLET_QUOTE_IDENTITY')
            return rows
        rows=_resource('coingecko','cg-wallet:'+identifiers,'https://api.coingecko.com/api/v3/coins/markets?'+urlencode({'vs_currency':'usd','ids':identifiers,'per_page':100,'sparkline':'true'}),parser)
        valid=[row for row in rows if prices.decimal(row.get('price_usd'),positive=True) is not None and prices.fresh(row)]
        _save_rows(valid);cached.update({r['provider_id']:r for r in valid})
    return list(cached.values())


def _curve_conversion_anchors(rows):
    """Known SOL/USDC quote mints only; never a ticker/address search or peg."""
    from backend import crypto_pump_accounts as pump,token_market_prices as prices
    mappings={'solana':pump.WSOL_MINT,'usd-coin':pump.USDC_MINT};result={}
    for row in rows:
        mint=mappings.get(row.get('provider_id'))
        if mint and prices.decimal(row.get('price_usd'),positive=True) is not None and prices.fresh(row):
            result[(SOL,mint)]=dict(row,quality='AGGREGATE_MARKET_ESTIMATE',
                source_timestamp=row.get('updated_at') or None)
    return result


def refresh_wallet_quotes(asset_ids):
    """Refresh public quotes without changing the explorer's view/selection."""
    from backend import token_market_prices as prices
    wanted=set(asset_ids)
    if len(wanted)>64:raise ValueError('EXPLORER_WALLET_QUOTE_LIMIT')
    registered={identifier:store.asset(identifier) for identifier in wanted}
    with _db() as db:
        bindings={r['asset_id']:json.loads(r['body']) for r in db.execute('SELECT b.asset_id,r.body FROM explorer_bindings b JOIN explorer_rows r ON b.market_id=r.id') if r['asset_id'] in wanted}
        saved={r['asset_id']:json.loads(r['body']) for r in db.execute('SELECT asset_id,body FROM wallet_quotes')}
    native_ids={_known_native(coin):coin for coin in NATIVES}
    native_ids.update({'eip155:8453/native:ETH':'ethereum','eip155:10/native:ETH':'ethereum','eip155:42161/native:ETH':'ethereum'})
    coins={r['provider_id'] for r in bindings.values() if r.get('provider')=='coingecko'}
    coins.update(native_ids[identifier] for identifier in wanted if identifier in native_ids)
    curve_quote_needed=any(a['chain_id']==SOL and a['namespace']=='token'
        and bindings.get(identifier,{}).get('provider')!='coingecko' for identifier,a in registered.items())
    if curve_quote_needed:coins.update(('solana','usd-coin'))
    errors=[];native_quotes={};conversion_anchors={}
    if coins:
        try:
            valid=_targeted_coins(coins)
            if curve_quote_needed:conversion_anchors=_curve_conversion_anchors(valid)
            by_coin={row['provider_id']:row for row in valid}
            for identifier in wanted:
                provider_id=native_ids.get(identifier)
                if not provider_id and bindings.get(identifier,{}).get('provider')=='coingecko':provider_id=bindings[identifier].get('provider_id')
                if provider_id in by_coin:native_quotes[identifier]=by_coin[provider_id]
        except ValueError:errors.append('COINGECKO_UNAVAILABLE')
    now=time.time();anchors=conversion_anchors;updates={}
    for identifier,asset in registered.items():
        market=native_quotes.get(identifier)
        if market is None:
            previous=bindings.get(identifier)
            if previous and previous.get('provider')=='coingecko' and prices.decimal(previous.get('price_usd'),positive=True) is not None and prices.fresh(previous):market=previous
        if market is not None:
            data=dict(market,asset_id=identifier,chain_id=asset['chain_id'],reference=asset['reference'],
                      quality='AGGREGATE_MARKET_ESTIMATE',price_basis='PROVIDER_ASSET_ID',source_timestamp=market.get('updated_at') or None,
                      state='CURRENT',auto_policy='MANUAL_ONLY',max_age_seconds=prices.MAX_AGE)
            updates[identifier]=data
            if identifier==SOL+'/native:SOL':
                from backend.crypto_pump_accounts import WSOL_MINT
                anchors[(SOL,WSOL_MINT)]=data
    for identifier,data in saved.items():
        asset=registered.get(identifier)
        if asset and asset['chain_id']==SOL and asset['namespace']=='token':anchors.setdefault((SOL,asset['reference']),data)
    # Native SOL's canonical wrapped mint is an explicit conversion fallback,
    # never a ticker search or a sweep of other tokens/networks.
    sol_native=SOL+'/native:SOL'
    tokens=[asset for identifier,asset in registered.items() if asset['namespace'] in ('erc20','token','asset') and identifier not in updates]
    identities=[(a['chain_id'],a['reference']) for a in tokens]
    needs_wrapped=sol_native in registered and sol_native not in updates
    if needs_wrapped:
        from backend.crypto_pump_accounts import WSOL_MINT
        identities.append((SOL,WSOL_MINT))
    quotes=prices.quotes(identities,anchors=anchors) if identities else {}
    if needs_wrapped:
        wrapped=quotes.get((SOL,WSOL_MINT))
        if wrapped and wrapped.get('price_usd') is not None:
            updates[sol_native]=dict(wrapped,asset_id=sol_native,reference='SOL',price_basis='CANONICAL_WRAPPED_NATIVE_REFERENCE')
    for asset in tokens:
        data=quotes.get(prices.identity(asset['chain_id'],asset['reference']))
        if data and data.get('price_usd') is not None:
            updates[asset['id']]=dict(data,asset_id=asset['id'],symbol=asset['symbol'],name=asset['name'])
        elif data and not saved.get(asset['id'],{}).get('price_usd'):
            updates[asset['id']]=dict(data,asset_id=asset['id'],symbol=asset['symbol'],name=asset['name'])
    with _db(True) as db:
        for identifier,data in updates.items():
            previous=saved.get(identifier)
            # Neither a failed provider nor an old cache can erase a fresher quote.
            if previous and (previous.get('observed_at') or 0)>(data.get('observed_at') or 0):continue
            db.execute('INSERT OR REPLACE INTO wallet_quotes VALUES(?,?,?)',(identifier,store.pack(data),data.get('observed_at') or 0))
        db.execute('DELETE FROM wallet_quotes WHERE asset_id NOT IN (SELECT asset_id FROM wallet_quotes ORDER BY ts DESC LIMIT 512)')
    if errors:raise ValueError('EXPLORER_SOURCE_UNAVAILABLE')
    return {'state':'COMPLETE','requested_assets':len(wanted),'quotes':sum(r.get('price_usd') is not None for r in updates.values()),
            'unpriced_assets':[identifier for identifier,data in updates.items() if data.get('price_usd') is None],
            'auto_policy':'MANUAL_ONLY','minimum_refresh_seconds':prices.TTL}


def refresh_favourites():
    """Refresh only the saved favourite entities, never the global market page."""
    from backend import token_market_prices as prices
    with _db() as db:
        rows=[json.loads(r[0]) for r in db.execute('SELECT r.body FROM explorer_stars s JOIN explorer_rows r ON r.id=s.id')]
    if len(rows)>64:raise ValueError('EXPLORER_WALLET_QUOTE_LIMIT')
    coins={r['provider_id'] for r in rows if r.get('provider')=='coingecko'}
    curve_quote_needed=any(r.get('chain_id')==SOL and r.get('provider')=='dexscreener' for r in rows)
    if curve_quote_needed:coins.update(('solana','usd-coin'))
    anchors=_curve_conversion_anchors(_targeted_coins(coins)) if coins else {}
    targeted=[]
    for item in rows:
        if item.get('provider')=='dexscreener' and item.get('chain_id') and item.get('reference'):
            try:targeted.append((item,prices.identity(item['chain_id'],item['reference'])))
            except ValueError:continue
    quoted=prices.quotes([key for item,key in targeted],anchors=anchors) if targeted else {}
    for item,key in targeted:
        value=quoted.get(key)
        if value and value.get('price_usd') is not None:
            _save_rows([dict(item,**{k:v for k,v in value.items() if k not in ('asset_id','id')})])
    return {'state':'READY','requested_entities':len(rows),'scope':'FAVOURITES_ONLY','auto_policy':'MANUAL_ONLY'}


def public_query(query):
    if not isinstance(query,str) or len(query)>128:raise ValueError('EXPLORER_QUERY')
    if store._redact(query)!=query or re.fullmatch(r'(?:0x)?[a-fA-F0-9]{64}',query) or len(query.split())>=10 or re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{80,90}',query):
        raise ValueError('EXPLORER_PUBLIC_QUERY_REQUIRED')
    return query.strip()


def refresh(force=False):
    store.bootstrap();view=pref('view') or 'overview';page=int(pref('page') or 1);query=pref('query') or '';rows=[];errors=[]
    if pref('paused'):return {'state':'PAUSED'}
    if view=='watchlist':return refresh_favourites()
    if view=='native':
        def taxonomy(value):
            if not isinstance(value,list) or len(value)>100000:raise ValueError('EXPLORER_TAXONOMY_SCHEMA')
            types={}
            for item in value:
                if not isinstance(item,dict):raise ValueError('EXPLORER_TAXONOMY_SCHEMA')
                coin=_id(item.get('id'));platforms=item.get('platforms')
                if isinstance(platforms,dict):types[coin]='TOKEN' if any(isinstance(v,str) and v for v in platforms.values()) else 'NATIVE'
            return types
        try:_resource('coingecko','cg-taxonomy','https://api.coingecko.com/api/v3/coins/list?include_platform=true',taxonomy,ttl=86400,max_bytes=8*1024*1024)
        except ValueError:errors.append('CoinGecko klassificering')
    if view in {'overview','native'} or (view=='search' and query):
        try:
            if view=='search':
                key='cg-search:'+query;url='https://api.coingecko.com/api/v3/search?'+urlencode({'query':query})
                def parser(value):
                    coins=value.get('coins') if isinstance(value,dict) else None
                    if not isinstance(coins,list):raise ValueError('EXPLORER_SEARCH_SCHEMA')
                    return parse_coins([dict(c,current_price=None,market_cap=None,total_volume=None) for c in coins[:100]])
            else:
                key='cg-markets-7d:'+str(page);url='https://api.coingecko.com/api/v3/coins/markets?'+urlencode({'vs_currency':'usd','order':'market_cap_desc','per_page':100,'page':page,'sparkline':'true','price_change_percentage':'24h'})
                parser=parse_coins
            rows+=_resource('coingecko',key,url,parser,force)
        except ValueError:errors.append('CoinGecko')
    if view in {'dex','search'}:
        try:
            if query:
                key='dex-search:'+query;rows+=_resource('dexscreener',key,'https://api.dexscreener.com/latest/dex/search?'+urlencode({'q':query}),parse_pairs,force)
            else:
                # Profiles are a bounded discovery feed, not an organic ranking.
                key='dex-profiles'
                def profiles(value):
                    if not isinstance(value,list):raise ValueError('EXPLORER_PROFILES_SCHEMA')
                    result=[]
                    for p in value[:30]:
                        network=p.get('chainId');address=p.get('tokenAddress')
                        if not isinstance(network,str) or not isinstance(address,str):continue
                        result.append({'id':'profile:'+network+':'+address,'provider':'dexscreener','provider_chain':network,
                            'chain_id':CHAINS.get(network,''),'provider_id':address,'reference':address,'symbol':address[:8],
                            'name':store.text(p.get('description') or 'Tokenprofil',80),'kind':'PROFILE','identity':'PROFILE_NOT_RPC_VERIFIED',
                            'price_usd':None,'change_24h':None,'liquidity_usd':None,'market_cap':None,'volume_24h':None,'rank':None,
                            'observed_at':time.time(),'source':'DEX Screener profiler','safety':'NOT_ASSESSED','pools':[],'asset_id':''})
                    return result
                rows+=_resource('dexscreener',key,'https://api.dexscreener.com/token-profiles/latest/v1',profiles,force)
        except ValueError:errors.append('DEX Screener')
    _save_rows(rows,preserve_search_quotes=view=='search')
    store.event('market','VIEW_PARTIAL' if errors else 'VIEW_READY','',str(len(rows))+' poster lästa · '+(', '.join(errors)+' otillgänglig' if errors else view))
    return {'state':'PARTIAL' if errors else 'READY','errors':errors}


def select(identifier):
    selected=row(identifier);pref('selected',identifier)
    if selected.get('asset_id') and selected.get('kind')=='NATIVE':store.preference('selected_asset',selected['asset_id'])
    if selected['provider']=='coingecko':
        coin=selected['provider_id'];key='cg-detail:'+coin
        def parser(value):
            if not isinstance(value,dict) or value.get('id')!=coin:raise ValueError('EXPLORER_DETAIL_IDENTITY')
            platforms=value.get('platforms') or {};variants=[]
            for platform,address in list(platforms.items())[:64]:
                chain=PLATFORMS.get(platform)
                if not chain or not address:continue
                try:reference=store.address_for(store.network(chain),address)
                except ValueError:continue
                variants.append({'chain_id':chain,'reference':reference,'provider':'coingecko','market_id':identifier,'metadata':'RPC_REQUIRED'})
            market=value.get('market_data') or {}
            return {'variants':variants,'price_usd':number((market.get('current_price') or {}).get('usd')),
                'observed_at':time.time(),
                'market_cap':number((market.get('market_cap') or {}).get('usd')),'volume_24h':number((market.get('total_volume') or {}).get('usd')),
                'change_24h':number(market.get('price_change_percentage_24h'),True)}
        detail=_resource('coingecko',key,'https://api.coingecko.com/api/v3/coins/'+quote(coin,safe='')+'?'+urlencode({'localization':'false','tickers':'false','community_data':'false','developer_data':'false','sparkline':'false'}),parser)
        selected.update(detail)
    elif selected['provider']=='dexscreener':
        network=_id(selected['provider_chain']);address=selected['reference']
        if not re.fullmatch(r'[a-zA-Z0-9:]{1,160}',address):raise ValueError('EXPLORER_TOKEN_ADDRESS')
        values=_resource('dexscreener','dex-token:'+network+':'+address,'https://api.dexscreener.com/token-pairs/v1/'+quote(network,safe='')+'/'+quote(address,safe=''),parse_pairs)
        # A pool where the requested token is only quote has another base price.
        matching=[v for v in values if v.get('reference')==address and v.get('provider_chain')==network and v.get('chain_id')==selected.get('chain_id')]
        if matching:selected.update(matching[0],id=identifier)
        else:selected.update(pools=[],quote_note='INGA_POOLER_MED_DENNA_TOKEN_SOM_BAS',price_usd=None,liquidity_usd=None,volume_24h=None,market_cap=None,change_24h=None)
    _save_rows([selected]);return selected


def add_asset(identifier,chain='',reference=''):
    selected=row(identifier)
    if selected.get('asset_id') and selected['kind']=='NATIVE':asset=store.asset(selected['asset_id'])
    else:
        if selected['provider']=='coingecko':
            if not any(v['chain_id']==chain and v['reference']==reference for v in selected.get('variants',[])):raise ValueError('EXPLORER_VARIANT_NOT_IN_PROVIDER_RECORD')
        else:
            if chain!=selected.get('chain_id') or reference!=selected.get('reference'):raise ValueError('EXPLORER_TOKEN_IDENTITY')
        asset=omni_rpc.import_token(chain,reference)
    with _db(True) as db:db.execute('INSERT OR REPLACE INTO explorer_bindings VALUES(?,?,?)',(asset['id'],identifier,'RPC_AND_PROVIDER_REFERENCE'))
    store.preference('selected_asset',asset['id'])
    store.event('assets','EXPLORER_IMPORTED',asset['id'],asset['symbol']+' · nätverk och referens kontrollerade')
    return asset


def star(identifier,enabled):
    row(identifier)
    if type(enabled) is not bool:raise ValueError('EXPLORER_STAR')
    with _db(True) as db:
        if enabled:
            if not db.execute('SELECT 1 FROM explorer_stars WHERE id=?',(identifier,)).fetchone() and db.execute('SELECT COUNT(*) FROM explorer_stars').fetchone()[0]>=500:raise ValueError('EXPLORER_WATCHLIST_LIMIT')
            db.execute('INSERT OR IGNORE INTO explorer_stars VALUES(?)',(identifier,))
        else:db.execute('DELETE FROM explorer_stars WHERE id=?',(identifier,))


def chart(identifier,days=7):
    selected=row(identifier)
    if type(days) is not int or days not in {1,7,30}:raise ValueError('EXPLORER_CHART_RANGE')
    if selected['provider']!='coingecko':return
    def parser(value):
        points=value.get('prices') if isinstance(value,dict) else None
        if not isinstance(points,list) or not 2<=len(points)<=5000:raise ValueError('EXPLORER_CHART_SCHEMA')
        seen={}
        for point in points:
            if not isinstance(point,list) or len(point)!=2:raise ValueError('EXPLORER_CHART_POINT')
            stamp=number(point[0]);price=number(point[1])
            if stamp is None or price is None or stamp<=0 or stamp/1000>time.time()+300:raise ValueError('EXPLORER_CHART_POINT')
            if stamp in seen and seen[stamp]!=price:raise ValueError('EXPLORER_CHART_CONFLICT')
            seen[stamp]=price
        stamps=sorted(seen)
        if len(stamps)<2:raise ValueError('EXPLORER_CHART_SCHEMA')
        step=max(1,math.ceil(len(stamps)/599));sample=stamps[::step]
        if sample[-1]!=stamps[-1]:sample.append(stamps[-1])
        return {'times':[s/1000 for s in sample],'prices':[seen[s] for s in sample],'source':'CoinGecko','currency':'USD','kind':'PRICE_SAMPLES_NOT_OHLC','period_days':days,'observed_at':time.time()}
    result=_resource('coingecko','cg-chart:'+identifier+':'+str(days),
        'https://api.coingecko.com/api/v3/coins/'+selected['provider_id']+'/market_chart?'+urlencode({'vs_currency':'usd','days':days}),parser)
    pref('selected',identifier)
    selected['chart']=result;_save_rows([selected])


def configure(args):
    allowed={'view','query','chain','sort','page','paused','min_liquidity','hide_unpriced'}
    if not isinstance(args,dict) or set(args)-allowed:raise ValueError('EXPLORER_FILTER')
    if 'view' in args and args['view'] not in {'overview','native','dex','search','watchlist','registered'}:raise ValueError('EXPLORER_VIEW')
    if 'sort' in args and args['sort'] not in {'rank','market_cap','volume_24h','liquidity_usd','change_24h','name','price_usd'}:raise ValueError('EXPLORER_SORT')
    if 'page' in args and (type(args['page']) is not int or not 1<=args['page']<=50):raise ValueError('EXPLORER_PAGE')
    for key in ('paused','hide_unpriced'):
        if key in args and type(args[key]) is not bool:raise ValueError('EXPLORER_TOGGLE')
    if 'min_liquidity' in args and number(args['min_liquidity']) is None:raise ValueError('EXPLORER_LIQUIDITY')
    if 'query' in args:args=dict(args,query=public_query(args['query']))
    if 'chain' in args and (not isinstance(args['chain'],str) or len(args['chain'])>80):raise ValueError('EXPLORER_CHAIN_FILTER')
    for key,value in args.items():pref(key,value)


def snapshot():
    store.bootstrap()
    with _db() as db:saved={r['key']:json.loads(r['value']) for r in db.execute('SELECT key,value FROM explorer_prefs')}
    settings={key:saved.get(key) for key in ('view','query','chain','sort','page','selected','paused','min_liquidity','hide_unpriced')}
    settings.update(view=settings['view'] or 'overview',query=settings['query'] or '',page=settings['page'] or 1,sort=settings['sort'] or 'rank')
    view=settings['view'];query=settings['query'];rows=[];sources=[]
    keys=[]
    if view in {'overview','native'}:keys=['cg-markets-7d:'+str(settings['page'])]
    elif view=='search':keys=['cg-search:'+query,'dex-search:'+query] if query else []
    elif view=='dex':keys=['dex-search:'+query] if query else ['dex-profiles']
    for key in keys:
        cached=_cache_get(key)
        if cached:
            values=json.loads(cached['body']);rows.extend(values if isinstance(values,list) else [])
            ttl=120 if key.startswith('cg-') else 30
            sources.append({'name':'CoinGecko' if key.startswith('cg-') else 'DEX Screener','state':'FAILED' if not cached['ts'] else 'STALE' if cached['error'] or not 0<=time.time()-cached['ts']<=ttl else 'CURRENT',
                            'observed_at':cached['ts'],'error':cached['error'],'retry_after':max(0,15-(time.time()-cached['attempt']))})
        else:sources.append({'name':'CoinGecko' if key.startswith('cg-') else 'DEX Screener','state':'NOT_FETCHED','observed_at':0,'error':''})
    with _db() as db:
        stars={r[0] for r in db.execute('SELECT id FROM explorer_stars')}
        if view=='watchlist':rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM explorer_rows WHERE id IN (SELECT id FROM explorer_stars)')]
        nets=[json.loads(r[0]) for r in db.execute('SELECT body FROM networks')]
        observed={}
        if any(r.get('provider')=='dexscreener' for r in rows):
            for point in db.execute('SELECT id,ts,price FROM explorer_prices WHERE ts>=? ORDER BY ts',(time.time()-7*86400,)):
                observed.setdefault(point['id'],[]).append((point['ts'],point['price']))
    for item in rows:
        if item.get('provider')=='dexscreener':
            points=observed.get(item['id'],[])[-128:]
            item['sparkline']={'prices':[p[1] for p in points],'period':'OBSERVED','source':'GG · sparade observationer',
                'observed_from':points[0][0] if points else None,'observed_to':points[-1][0] if points else None}
    if view=='registered':
        rows=[dict(a,id='registered:'+a['id'],asset_id=a['id'],provider='registered',kind='NATIVE' if a['namespace']=='native' else 'TOKEN',
            price_usd=None,market_cap=None,volume_24h=None,change_24h=None,rank=None,liquidity_usd=None,safety='NOT_ASSESSED',source='GG tillgångsregister',pools=[]) for a in store.snapshot()['assets']]
    taxonomy_cache=_cache_get('cg-taxonomy')
    taxonomy=json.loads(taxonomy_cache['body']) if taxonomy_cache and taxonomy_cache['ts'] else {}
    if isinstance(taxonomy,dict):
        for item in rows:
            if item.get('provider')=='coingecko' and item.get('kind')!='NATIVE' and item.get('provider_id') in taxonomy:
                item['kind']=taxonomy[item['provider_id']];item['classification']='PROVIDER_PLATFORM_METADATA'
    if view=='native':rows=[r for r in rows if r['kind']=='NATIVE']
    if query and view in {'registered','watchlist'}:rows=[r for r in rows if query.casefold() in (' '.join(str(r.get(k,'')) for k in ('symbol','name','id','reference'))).casefold()]
    if settings['chain']:rows=[r for r in rows if settings['chain'] in {r.get('chain_id'),r.get('provider_chain')}]
    if settings['hide_unpriced']:rows=[r for r in rows if r.get('price_usd') is not None]
    if settings['min_liquidity']:rows=[r for r in rows if r.get('liquidity_usd') is not None and r['liquidity_usd']>=float(settings['min_liquidity'])]
    sort=settings['sort']
    rows.sort(key=lambda r:(r.get(sort) is None,(str(r.get(sort,'')).casefold() if sort=='name' else (r.get(sort) or 0)*(1 if sort=='rank' else -1))))
    for r in rows:r['starred']=r['id'] in stars
    selected=None
    if settings['selected']:
        try:
            if settings['selected'].startswith('registered:'):
                a=store.asset(settings['selected'].removeprefix('registered:'))
                selected=dict(a,id=settings['selected'],asset_id=a['id'],provider='registered',kind='NATIVE' if a['namespace']=='native' else 'TOKEN',
                    price_usd=None,change_24h=None,market_cap=None,volume_24h=None,liquidity_usd=None,pools=[],source='GG tillgångsregister')
            else:selected=row(settings['selected'])
        except ValueError:pass
    for item in rows+([selected] if selected else []):
        item['starred']=item['id'] in stars
        item['stale']=not 0<=time.time()-(item.get('observed_at') or 0)<=300
    if selected:
        try:store.asset(selected.get('asset_id',''));selected['registered']=True
        except ValueError:selected['registered']=False
    if selected and not selected.get('chart'):
        with _db() as db:points=db.execute('SELECT ts,price FROM explorer_prices WHERE id=? ORDER BY ts DESC LIMIT 600',(selected['id'],)).fetchall()
        selected['chart']={'times':[p['ts'] for p in reversed(points)],'prices':[p['price'] for p in reversed(points)],'source':'GG · sparade prisobservationer','currency':'USD','kind':'OBSERVED_SAMPLES_NOT_OHLC'}
    if not rows and view=='overview' and not any(s.get('observed_at') for s in sources):
        # Local catalog stays usable when first public source is unavailable.
        rows=[dict(a,id='registered:'+a['id'],asset_id=a['id'],kind='NATIVE' if a['namespace']=='native' else 'TOKEN',provider='registered',
                   price_usd=None,change_24h=None,market_cap=None,volume_24h=None,liquidity_usd=None,rank=None,source='GG register · pris ej hämtat',starred=False) for a in store.snapshot()['assets']]
    return {'schema':'gg.explorer.v1','rows':rows[:1000],'row_count':len(rows),'settings':settings,'sources':sources,'networks':nets,'events':store.events(limit=80),
            'selected':selected,'star_count':len(stars),'authority':'NONE','route_state':'NO_BRIDGE_CONFIGURED','needs_refresh':any(s['state']=='NOT_FETCHED' for s in sources)}


def action(name,raw='{}'):
    if len(raw)>4096:raise ValueError('EXPLORER_REQUEST_SIZE')
    args=json.loads(raw or '{}')
    if not isinstance(args,dict):raise ValueError('EXPLORER_REQUEST')
    if name=='configure':
        configure(args)
        if {'view','page'} & set(args):refresh()
    elif name=='refresh':refresh(args.get('force',False))
    elif name=='search':
        query=public_query(args.get('query',''))
        if not query:raise ValueError('EXPLORER_QUERY_REQUIRED')
        configure({'query':query,'view':'search','page':1});refresh()
    elif name=='select':
        identifier=args['id']
        if identifier.startswith('registered:'):
            asset=store.asset(identifier.removeprefix('registered:'));store.preference('selected_asset',asset['id'])
            pref('selected',identifier)
        else:
            selected=select(identifier)
            if args.get('history') is True and selected['provider']=='coingecko':
                try:chart(identifier,7)
                except ValueError:store.event('market','HISTORY_UNAVAILABLE',selected.get('asset_id',''),'Veckohistorik kunde inte hämtas; befintliga observationer visas')
    elif name=='open_asset':
        asset=store.asset(args['asset_id'])
        with _db() as db:binding=db.execute('SELECT b.market_id FROM explorer_bindings b JOIN explorer_rows r ON r.id=b.market_id WHERE b.asset_id=?',(asset['id'],)).fetchone()
        selected_id=binding['market_id'] if binding else 'registered:'+asset['id']
        result=action('select',store.pack({'id':selected_id,'history':True}))
        if binding:
            chosen=row(selected_id);chosen.update(asset_id=asset['id'],chain_id=asset['chain_id'],reference=asset['reference']);_save_rows([chosen])
        store.preference('selected_asset',asset['id'])
        return result
    elif name=='star':star(args['id'],args['enabled'])
    elif name=='chart':chart(args['id'],args.get('days',7))
    elif name=='add_asset':add_asset(args['id'],args.get('chain_id',''),args.get('reference',''))
    else:raise ValueError('EXPLORER_ACTION')
    return {'status':'COMPLETE'}
