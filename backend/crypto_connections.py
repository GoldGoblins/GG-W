"""Bounded, cached public chain diagnostics; no signer or mainnet writes."""
from __future__ import annotations
import json
import re
import threading
import time
import urllib.request
from urllib.parse import quote, urlsplit
from backend import crypto_contract as C, kaspa_contract as K

_LOCK = threading.Lock()
_CACHE = {}
_BUSY = set()
_epoch = 0
TTL = 20
SOL_GENESIS = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d'


def _request(url, payload=None):
    request = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={'User-Agent':'GG-crypto-diagnostics/1', 'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        if hasattr(response, 'geturl') and urlsplit(response.geturl()).netloc != urlsplit(url).netloc:
            raise ValueError('CRYPTO_RPC_REDIRECT')
        raw = response.read(256*1024+1)
    if len(raw) > 256*1024:
        raise ValueError('CRYPTO_RPC_RESPONSE_LIMIT')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('CRYPTO_RPC_SCHEMA')
    return result


def watch_address():
    return str(K.load_json('watch.json').get('address') or '')


def set_watch(address):
    from backend.kaspa_address import validate
    address = str(address or '').strip()
    address = validate(address) if address else ''
    K.save_json('watch.json', {'address': address})
    return {'address': address}


def _watch_balance(result, address, mainnet):
    if not address or not result.get('healthy'):
        return
    expected = 'kaspa:' if mainnet else 'kaspasim:'
    if not address.startswith(expected):
        result['watch_error'] = 'KASPA_WATCH_NETWORK_MISMATCH'
        return
    try:
        if mainnet:
            balance = _request('https://api.kaspa.org/addresses/'+quote(address, safe='')+'/balance').get('balance')
        else:
            from backend import kaspa_node
            balance = kaspa_node.rpc('getBalanceByAddress', {'address':address}).get('balance')
        if type(balance) not in {int,str} or not str(balance).isdigit() or not 0 <= int(balance) < 2**64:
            raise ValueError('KASPA_BALANCE_SCHEMA')
        result['balance_sompi'] = int(balance)
    except Exception:
        result['watch_error'] = 'KASPA_BALANCE_UNAVAILABLE'


def _probe(asset, network, address):
    started = time.monotonic()
    if asset == 'SOL':
        if network == 'mainnet':
            endpoint = C.RPC_ALLOWLIST['mainnet']
            genesis = _request(endpoint, {'jsonrpc':'2.0','id':1,'method':'getGenesisHash'})
            if genesis.get('result') != SOL_GENESIS:
                raise ValueError('CRYPTO_WRONG_NETWORK')
            health = _request(endpoint, {'jsonrpc':'2.0','id':2,'method':'getHealth'})
            if health.get('result') != 'ok' or health.get('error'):
                raise ValueError('CRYPTO_NODE_UNHEALTHY')
            slot = _request(endpoint, {'jsonrpc':'2.0','id':3,'method':'getSlot','params':[{'commitment':'confirmed'}]}).get('result')
            if type(slot) is not int or slot <= 0:
                raise ValueError('CRYPTO_RPC_SCHEMA')
            result = dict(healthy=True, endpoint=endpoint, label='Solana mainnet', height=slot, backend='public-rpc', can_stop=False)
        else:
            from backend import crypto_lab
            lab = crypto_lab.lab_status()
            result = dict(healthy=bool(lab.get('healthy')), endpoint=lab.get('rpc'), label=lab.get('label'),
                          height=crypto_lab.current_slot() if lab.get('healthy') else None,
                          backend=lab.get('backend'), error=lab.get('diagnostic') or '', can_stop=lab.get('owned',False))
    elif network == 'mainnet':
        endpoint = 'https://api.kaspa.org'
        dag = _request(endpoint+'/info/blockdag')
        if dag.get('networkName') != 'kaspa-mainnet':
            raise ValueError('KASPA_WRONG_NETWORK')
        height = dag.get('virtualDaaScore', 0)
        if type(height) not in {str,int} or not str(height).isdigit() or not 0 < int(height) < 2**64:
            raise ValueError('KASPA_RPC_SCHEMA')
        result = dict(healthy=True, endpoint=endpoint, label='Kaspa mainnet', height=int(height), backend='public-rest', can_stop=False)
        _watch_balance(result,address,True)
    else:
        from backend import kaspa_node
        lab = kaspa_node.status(force=True)
        result = dict(healthy=lab['healthy'], endpoint=lab['rpc'], label=lab['label'], backend=lab['backend'],
                      height=(lab.get('server') or {}).get('virtualDaaScore'), error=lab.get('diagnostic') or '', can_stop=lab['owned'])
        _watch_balance(result,address,False)
    result.update(asset=asset, network=network, observed_at=time.time(), latency_ms=round((time.monotonic()-started)*1000), address=address,
                  write_authority='NONE' if network == 'mainnet' or asset == 'KAS' else 'LOCAL_VM_OR_VALIDATOR')
    if 'balance_sompi' in result:
        result['balance_kas'] = K.format_kas(result['balance_sompi'])
    return result


def invalidate(asset, network):
    global _epoch
    with _LOCK:
        _epoch += 1
        for key in list(_CACHE):
            if key[:2] == (asset,network): _CACHE.pop(key)


def _run(key, epoch):
    try:
        result = _probe(*key)
    except Exception as exc:
        error = str(exc) if isinstance(exc, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{1,80}', str(exc)) else 'CRYPTO_CONNECTION_UNAVAILABLE'
        result = dict(healthy=False, asset=key[0], network=key[1], address=key[2], error=error, observed_at=time.time())
    with _LOCK:
        if epoch == _epoch:
            _CACHE[key] = result
        _BUSY.discard(key)
        if len(_CACHE)>12:
            _CACHE.pop(next(iter(_CACHE)))


def snapshot(asset, network, force=False):
    if asset not in {'SOL','KAS'} or network not in {'mainnet','testnet','paper'}:
        raise ValueError('CRYPTO_CONNECTION_SELECTION')
    if network == 'paper':
        return dict(asset=asset, network=network, healthy=True, label='Papperssimulering', backend='paper', simulated=True, stale=False, loading=False)
    address = watch_address() if asset == 'KAS' else ''
    key = (asset, network, address)
    launch = False
    with _LOCK:
        epoch = _epoch
        result = dict(_CACHE.get(key, {}))
        stale = time.time()-result.get('observed_at',0) > TTL
        if (force or stale) and key not in _BUSY and len(_BUSY) < 4:
            _BUSY.add(key)
            launch = True
        result.update(asset=asset, network=network, address=address, loading=key in _BUSY, stale=stale)
    if launch:
        try:
            threading.Thread(target=_run,args=(key,epoch),name='gg-crypto-connection',daemon=True).start()
        except Exception:
            with _LOCK:
                _BUSY.discard(key)
            result.update(loading=False,error='CRYPTO_WORKER_START',healthy=False)
    return result
