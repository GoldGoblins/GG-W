"""Finite, public, address-qualified token pricing. No timer, trade or scan API.

Prices are indicative observations, never executable liquidation quotes. Calls
must name actual positions/favourites; status rendering only reads saved data.
"""
from collections import OrderedDict,defaultdict
from decimal import Decimal,InvalidOperation,localcontext
from datetime import datetime
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from urllib.parse import quote as urlquote,urlsplit

SOL='solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp'
DEX_CHAINS={'eip155:1':'ethereum','eip155:56':'bsc','eip155:137':'polygon',
    'eip155:8453':'base','eip155:10':'optimism','eip155:43114':'avalanche',
    'eip155:42161':'arbitrum',SOL:'solana','tron:mainnet':'tron'}
GECKO_CHAINS={'eip155:1':'eth','eip155:56':'bsc','eip155:137':'polygon_pos',
    'eip155:8453':'base','eip155:10':'optimism','eip155:43114':'avax',
    'eip155:42161':'arbitrum',SOL:'solana','tron:mainnet':'tron'}
TTL=60
MAX_AGE=300
MAX_TOKENS=64
MAX_REQUESTS=12
MAX_CACHE=256
MAX_BODY=2*1024*1024
_LOCK=threading.RLock()
_cache=OrderedDict()
_provider_next={}
_last_job={}


class ProviderUnavailable(ValueError):
    def __init__(self,code,status=None,retry_after=None):
        super().__init__(code);self.status=status;self.retry_after=retry_after


def identity(chain_id,reference):
    from backend import omni_assets as store
    chain_id=store.chain_id(chain_id)
    if chain_id.startswith('eip155:'):reference=store.evm_address(reference)
    elif chain_id==SOL:
        from backend.crypto_pump_accounts import pubkey_bytes
        pubkey_bytes(reference)
    elif chain_id=='tron:mainnet':
        reference=store.address_for({'family':'tron'},reference)
    elif not isinstance(reference,str) or not re.fullmatch(r'[-a-zA-Z0-9.]{1,128}',reference):
        raise ValueError('TOKEN_PRICE_REFERENCE')
    return chain_id,reference


def decimal(value,*,positive=False,signed=False):
    if isinstance(value,bool) or value is None:return None
    if not isinstance(value,(str,int,float,Decimal)) or len(str(value))>128:return None
    try:result=Decimal(str(value))
    except (InvalidOperation,ValueError):return None
    if (not result.is_finite() or not signed and result<0 or result.copy_abs()>Decimal('1e100')
            or result and result.adjusted() < -300 or positive and result<=0):return None
    return result


def _number(value):
    number=decimal(value)
    return format(number,'f') if number is not None else None


def asof(data):
    """Old or future source timestamps never become fresh just by fetching."""
    stamp=data.get('observed_at') if isinstance(data,dict) else None
    if type(stamp) not in (int,float) or decimal(stamp,positive=True) is None:return None
    source=data.get('source_timestamp') or data.get('updated_at')
    if source:
        try:
            if isinstance(source,str):
                parsed=datetime.fromisoformat(source.replace('Z','+00:00'))
                if parsed.tzinfo is None:return None
                source=parsed.timestamp()
            if type(source) not in (float,int) or decimal(source,positive=True) is None or source>time.time()+300:return None
            stamp=min(stamp,source)
        except (ValueError,TypeError,OverflowError):return None
    return stamp


def fresh(data,max_age=MAX_AGE):
    stamp=asof(data)
    return stamp is not None and 0<=time.time()-stamp<=max_age


def _json(url,provider):
    """Fixed public hosts, validated/pinned public DNS, TLS, no redirects."""
    parts=urlsplit(url)
    host={'dexscreener':'api.dexscreener.com','geckoterminal':'api.geckoterminal.com'}[provider]
    if parts.scheme!='https' or parts.hostname!=host or parts.port not in (None,443) or parts.username or parts.password:
        raise ProviderUnavailable('TOKEN_PRICE_ENDPOINT')
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ProviderUnavailable('TOKEN_PRICE_DNS')
    connection=http.client.HTTPSConnection(host,443,timeout=4,context=ssl.create_default_context())
    public_ip=addresses[0][4][0]
    connection._create_connection=lambda ignored,timeout=4,source_address=None:socket.create_connection((public_ip,443),timeout,source_address)
    try:
        connection.request('GET',parts.path+('?' +parts.query if parts.query else ''),headers={
            'Accept':'application/json;version=20230203' if provider=='geckoterminal' else 'application/json',
            'User-Agent':'GG-Token-Prices/1'})
        response=connection.getresponse()
        if response.status!=200:
            retry=response.getheader('Retry-After','')
            seconds=int(retry) if re.fullmatch(r'[0-9]{1,6}',retry) else None
            raise ProviderUnavailable('TOKEN_PRICE_HTTP_'+str(response.status),response.status,seconds)
        raw=response.read(MAX_BODY+1)
    finally:connection.close()
    if len(raw)>MAX_BODY:raise ProviderUnavailable('TOKEN_PRICE_RESPONSE_LIMIT')
    def invalid(_):raise ValueError('TOKEN_PRICE_NONFINITE_JSON')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('TOKEN_PRICE_DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    return json.loads(raw,parse_constant=invalid,object_pairs_hook=unique)


def _empty(key,reason='NO_QUALIFYING_MARKET'):
    return {'chain_id':key[0],'reference':key[1],'price_usd':None,'source':'',
            'observed_at':None,'source_timestamp':None,'timestamp_basis':'FETCH_OBSERVATION',
            'liquidity_usd':None,'quality':'UNPRICED','pool_ref':'','price_basis':'UNKNOWN',
            'state':'UNPRICED','reason':reason,'max_age_seconds':MAX_AGE,'auto_policy':'MANUAL_ONLY'}


def parse_dex(raw,chain_id,references,now=None):
    now=time.time() if now is None else now
    expected=DEX_CHAINS.get(chain_id);wanted=set(references);groups=defaultdict(list)
    if not isinstance(raw,list) or len(raw)>1000:raise ValueError('TOKEN_PRICE_DEX_SCHEMA')
    for pair in raw:
        if not isinstance(pair,dict) or pair.get('chainId')!=expected:continue
        try:key=identity(chain_id,(pair.get('baseToken') or {}).get('address'))
        except (ValueError,TypeError):continue
        if key[1] not in wanted:continue  # priceUsd belongs to the BASE token.
        price=decimal(pair.get('priceUsd'),positive=True)
        liquidity_raw=(pair.get('liquidity') or {}).get('usd')
        liquidity=decimal(liquidity_raw)
        if price is None or liquidity_raw is not None and liquidity is None:continue
        pool=pair.get('pairAddress')
        if not isinstance(pool,str) or not re.fullmatch(r'[-_a-zA-Z0-9]{1,160}',pool):continue
        created=decimal(pair.get('pairCreatedAt'))
        if created is not None and created/1000>Decimal(str(now+300)):continue
        groups[key[1]].append((liquidity or Decimal(0),pair,price))
    result={}
    for reference,pools in groups.items():
        liquidity,pair,price=max(pools,key=lambda item:(item[0],decimal((item[1].get('volume') or {}).get('h24')) or Decimal(0)))
        data=_empty((chain_id,reference));data.update(price_usd=format(price,'f'),source='DEX Screener',observed_at=now,
            liquidity_usd=_number((pair.get('liquidity') or {}).get('usd')),
            quality='DEX_POOL_SPOT' if liquidity>=1000 else 'LOW_LIQUIDITY' if liquidity>0 else 'UNKNOWN_LIQUIDITY',
            pool_ref=pair['pairAddress'],price_basis='BASE_TOKEN_POOL_SPOT',state='CURRENT',reason='',
            change_24h=str(decimal((pair.get('priceChange') or {}).get('h24'),signed=True)) if decimal((pair.get('priceChange') or {}).get('h24'),signed=True) is not None else None,
            provider_chain=expected,provider='dexscreener',identity='EXACT_CHAIN_AND_ADDRESS')
        result[(chain_id,reference)]=data
    return result


def parse_gecko(raw,chain_id,references,now=None):
    now=time.time() if now is None else now
    network=GECKO_CHAINS.get(chain_id);wanted=set(references)
    values=raw.get('data') if isinstance(raw,dict) else None
    if not isinstance(values,list) or len(values)>30:raise ValueError('TOKEN_PRICE_GECKO_SCHEMA')
    result={}
    for item in values:
        if not isinstance(item,dict) or item.get('type')!='token':continue
        attributes=item.get('attributes') or {}
        try:key=identity(chain_id,attributes.get('address'))
        except (ValueError,TypeError):continue
        # Gecko's record id embeds the provider network as well as the address.
        record_id=item.get('id','');expected_id=network+'_'+key[1]
        if not isinstance(record_id,str):continue
        matches=record_id.lower()==expected_id.lower() if chain_id.startswith('eip155:') else record_id==expected_id
        if key[1] not in wanted or not matches:continue
        price=decimal(attributes.get('price_usd'),positive=True)
        liquidity_raw=attributes.get('total_reserve_in_usd');liquidity=decimal(liquidity_raw)
        if price is None or liquidity_raw is not None and liquidity is None:continue
        data=_empty(key);data.update(price_usd=format(price,'f'),source='GeckoTerminal',observed_at=now,
            liquidity_usd=_number(liquidity_raw),quality='AGGREGATE_DEX_SPOT' if liquidity is not None and liquidity>=1000 else 'LOW_LIQUIDITY' if liquidity else 'UNKNOWN_LIQUIDITY',
            price_basis='PROVIDER_TOKEN_PRICE',state='CURRENT',reason='',provider='geckoterminal',provider_chain=network,
            identity='EXACT_CHAIN_AND_ADDRESS')
        result[key]=data
    return result


def _request(provider,url,budget):
    now=time.monotonic()
    if budget[0]<=0:raise ProviderUnavailable('TOKEN_PRICE_REQUEST_BUDGET')
    wait=_provider_next.get(provider,0)-now
    # Coarse source budgets never turn one refresh into a sleeping poll loop.
    if wait>.25:raise ProviderUnavailable('TOKEN_PRICE_PROVIDER_COOLDOWN')
    if wait>0:time.sleep(wait)
    budget[0]-=1
    _provider_next[provider]=time.monotonic()+(6 if provider=='geckoterminal' else .21)
    try:return _json(url,provider)
    except Exception as error:
        delay=min(3600,max(60,getattr(error,'retry_after',None) or 0)) if getattr(error,'status',None)==429 else 15
        _provider_next[provider]=time.monotonic()+delay
        raise


def _anchor(anchors,mint,now):
    data=(anchors or {}).get((SOL,mint))
    if not isinstance(data,dict):return None
    price=decimal(data.get('price_usd'),positive=True);stamp=asof(data)
    if price is None or stamp is None or not 0<=now-stamp<=MAX_AGE or not data.get('source'):return None
    if data.get('quality') in ('LOW_LIQUIDITY','UNKNOWN_LIQUIDITY','UNPRICED'):return None
    return price,data


def _pump_curves(keys,anchors,budget):
    """Only direct SOL/USDC incomplete curves; no mint-suffix assumptions."""
    from backend import crypto_pump_accounts as accounts,omni_assets as store,omni_rpc
    now=time.time();selected=[key for key in keys if key[0]==SOL][:32]
    if not selected or not any(_anchor(anchors,mint,now) for mint in (accounts.WSOL_MINT,accounts.USDC_MINT)):return {}
    if budget[0]<2:return {}
    network=store.network(SOL)
    if network.get('endpoint')!='https://api.mainnet-beta.solana.com':return {}
    budget[0]-=1;omni_rpc._sol_identity(network)
    addresses=[]
    for _,mint in selected:addresses.extend([mint,accounts.derive_curve(mint)])
    quote_mints=[mint for mint in (accounts.WSOL_MINT,accounts.USDC_MINT) if _anchor(anchors,mint,now)]
    addresses.extend(quote_mints)
    budget[0]-=1
    reply=omni_rpc.rpc(network,'getMultipleAccounts',[addresses,{'encoding':'base64','commitment':'confirmed'}])
    values=reply.get('value') if isinstance(reply,dict) else None
    slot=(reply.get('context') or {}).get('slot') if isinstance(reply,dict) else None
    if not isinstance(values,list) or len(values)!=len(addresses) or type(slot) is not int or slot<0:
        raise ValueError('TOKEN_PRICE_PUMP_RPC_SCHEMA')
    result={}
    quote_decimals={}
    for offset,mint in enumerate(quote_mints,len(selected)*2):
        try:
            decoded=accounts.decode_mint(values[offset])
            if decoded['quote_supported'] and decoded['decimals']==(9 if mint==accounts.WSOL_MINT else 6):quote_decimals[mint]=decoded['decimals']
        except (ValueError,KeyError,TypeError):pass
    for index,key in enumerate(selected):
        try:
            token=accounts.decode_mint(values[index*2]);curve=accounts.decode_curve(values[index*2+1])
            fx=_anchor(anchors,curve['quote_mint'],now)
            if (curve['complete'] or curve.get('depth') or curve.get('post_complete_base_out') or not fx
                or curve['quote_mint'] not in (accounts.WSOL_MINT,accounts.USDC_MINT)
                or curve['quote_mint'] not in quote_decimals
                or not token['quote_supported'] or token['decimals']>18
                # Pump's curve stores the creation supply; public SPL burns
                # reduce the mint supply without changing its price reserves.
                # Reject impossible inflation/empty mint and reserves greater
                # than the remaining supply, rather than rejecting all burns.
                or not 0 < token['supply'] <= curve['token_total_supply']
                or curve['real_token_reserves'] > token['supply']
                or curve['real_token_reserves'] > curve['virtual_token_reserves']
                or curve['virtual_token_reserves']<=0 or curve['virtual_quote_reserves']<=0
                or curve['real_token_reserves']<=0):continue
            if curve['quote_mint']==accounts.WSOL_MINT and curve['real_quote_reserves']>values[index*2+1].get('lamports',0):continue
            quote_scale=quote_decimals[curve['quote_mint']]
            with localcontext() as context:
                context.prec=80
                price=Decimal(curve['virtual_quote_reserves'])/Decimal(curve['virtual_token_reserves'])\
                    *Decimal(10)**(token['decimals']-quote_scale)*fx[0]
            if decimal(price,positive=True) is None:continue
            data=_empty(key);data.update(price_usd=format(price,'f'),source='Pump RPC · reserve estimate',
                observed_at=min(now,asof(fx[1])),curve_observed_at=now,
                quality='BONDING_CURVE_SPOT',price_basis='VIRTUAL_RESERVE_SPOT_NOT_EXECUTABLE',
                state='CURRENT',reason='',pool_ref=addresses[index*2+1],slot=slot,
                quote_mint=curve['quote_mint'],quote_price_source=fx[1]['source'],
                quote_price_observed_at=fx[1]['observed_at'],identity='DERIVED_PDA_OWNER_DISCRIMINATOR_MINT',
                provider='pump_rpc',provider_chain='solana')
            result[key]=data
        except (ValueError,KeyError,TypeError,ArithmeticError):continue
    return result


def quotes(identities,*,anchors=None):
    """One explicitly requested <=64-identity job; no global token discovery."""
    if not isinstance(identities,(list,tuple)) or len(identities)>MAX_TOKENS:raise ValueError('TOKEN_PRICE_TOKEN_LIMIT')
    keys=[]
    for pair in identities:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:raise ValueError('TOKEN_PRICE_IDENTITY')
        key=identity(*pair)
        if key not in keys:keys.append(key)
    with _LOCK:
        now=time.time();result={};pending=[];budget=[MAX_REQUESTS];failures={}
        for key in keys:
            cached=_cache.get(key)
            if cached and 0<=now-cached['attempt']<TTL:
                result[key]=dict(cached['quote']);_cache.move_to_end(key)
            else:pending.append(key)
        grouped=defaultdict(list)
        for chain,reference in pending:
            if chain in DEX_CHAINS:grouped[chain].append(reference)
            else:result[(chain,reference)]=_empty((chain,reference),'NETWORK_ADAPTER_UNAVAILABLE')
        for chain,references in grouped.items():
            for offset in range(0,len(references),30):
                selected=references[offset:offset+30]
                try:
                    raw=_request('dexscreener','https://api.dexscreener.com/tokens/v1/'+DEX_CHAINS[chain]+'/'+','.join(urlquote(r,safe='') for r in selected),budget)
                    result.update(parse_dex(raw,chain,selected))
                except Exception as error:
                    reason='SOURCE_RATE_LIMITED' if getattr(error,'status',None)==429 else 'PRICE_SOURCE_UNAVAILABLE'
                    for reference in selected:failures[(chain,reference)]=reason
                missing=[r for r in selected if (chain,r) not in result]
                if missing and chain in GECKO_CHAINS:
                    try:
                        raw=_request('geckoterminal','https://api.geckoterminal.com/api/v2/networks/'+GECKO_CHAINS[chain]+'/tokens/multi/'+','.join(urlquote(r,safe='') for r in missing),budget)
                        result.update(parse_gecko(raw,chain,missing))
                    except Exception as error:
                        reason='SOURCE_RATE_LIMITED' if getattr(error,'status',None)==429 else 'PRICE_SOURCE_UNAVAILABLE'
                        for reference in missing:failures[(chain,reference)]=reason
        missing=[key for key in pending if key not in result or result[key]['price_usd'] is None]
        effective_anchors=dict(anchors or {})
        for key,data in result.items():
            if key[0]==SOL and data.get('price_usd') is not None:effective_anchors.setdefault(key,data)
        try:result.update(_pump_curves(missing,effective_anchors,budget))
        except Exception:pass
        for key in pending:
            value=result.get(key) or _empty(key,failures.get(key,'NO_QUALIFYING_MARKET'))
            previous=_cache.get(key,{}).get('quote')
            if value['price_usd'] is None and previous and previous.get('price_usd') is not None:
                value=dict(previous,state='LAST_GOOD',reason='SOURCE_UNAVAILABLE_OR_NO_VALID_QUOTE')
            if value.get('price_usd') is not None and not fresh(value):
                value=dict(value,state='STALE')
            result[key]=value;_cache[key]={'quote':dict(value),'attempt':now};_cache.move_to_end(key)
        while len(_cache)>MAX_CACHE:_cache.popitem(last=False)
        _last_job.update(requested_tokens=len(keys),cache_hits=len(keys)-len(pending),
                         provider_requests=MAX_REQUESTS-budget[0],priced=sum(r.get('price_usd') is not None for r in result.values()),
                         observed_at=time.time())
        return result


def quote(chain_id,reference,**kwargs):
    key=identity(chain_id,reference)
    return quotes([key],**kwargs)[key]


def policy():
    """Prepared metadata only; inspecting policy never fetches a price."""
    return {'mode':'MANUAL_ONLY','minimum_refresh_seconds':TTL,'max_age_seconds':MAX_AGE,
            'max_tokens_per_job':MAX_TOKENS,'max_provider_requests_per_job':MAX_REQUESTS,
            'scope':'ACTUAL_POSITIONS_FAVOURITES_OR_EXPLICIT_SELECTION',
            'token_chains':sorted(DEX_CHAINS),'curve_chains':[SOL],
            'unavailable_price':'UNPRICED_NOT_ZERO','historical_or_catalogue_scan':False,
            'last_job':dict(_last_job)}
