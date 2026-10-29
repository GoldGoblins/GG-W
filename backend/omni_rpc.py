"""Read-only network family adapters. No send, approval, swap or signing API."""
import json
import socket
import ipaddress
import urllib.request
import http.client
import ssl
from urllib.parse import urlsplit,quote
from backend import omni_assets as store
from backend.crypto_pump_accounts import TOKEN_PROGRAM,TOKEN_2022_PROGRAM

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('OMNI_RPC_REDIRECT')


def _response(url,payload=None,max_bytes=1024*1024):
    if type(max_bytes) is not int or not 1<=max_bytes<=8*1024*1024:raise ValueError('OMNI_RPC_SIZE_LIMIT')
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.username or parts.password or not parts.hostname: raise ValueError('OMNI_RPC_ENDPOINT')
    addresses=socket.getaddrinfo(parts.hostname,parts.port or 443,type=socket.SOCK_STREAM)
    if not addresses: raise ValueError('OMNI_RPC_DNS')
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global: raise ValueError('OMNI_PUBLIC_RPC_REQUIRED')
    # Pin the verified public address, keeping TLS certificate/SNI validation
    # against the requested hostname. Do not resolve it again in the request.
    connection=http.client.HTTPSConnection(parts.hostname,parts.port or 443,timeout=5,context=ssl.create_default_context())
    public_ip=addresses[0][4][0]
    connection._create_connection=lambda ignored,timeout=5,source_address=None: socket.create_connection((public_ip,parts.port or 443),timeout,source_address)
    try:
        connection.request('POST' if payload is not None else 'GET',parts.path+('?' + parts.query if parts.query else ''),
            body=store.pack(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json','User-Agent':'GG-Omni/1'})
        response=connection.getresponse()
        if response.status!=200: raise ValueError('OMNI_RPC_HTTP_'+str(response.status))
        data=response.read(max_bytes+1)
    finally: connection.close()
    if len(data)>max_bytes: raise ValueError('OMNI_RPC_SIZE_LIMIT')
    return data


def _json(url,payload=None,*,max_bytes=1024*1024):
    def invalid(value):raise ValueError('OMNI_RPC_NONFINITE_JSON')
    return json.loads(_response(url,payload,max_bytes),parse_constant=invalid)


def _text(url):return _response(url,max_bytes=4096).decode('ascii').strip()


def rpc(network,method,params):
    if method not in {'eth_chainId','eth_getBalance','eth_call','eth_getCode','getGenesisHash','getBalance','getAccountInfo','getTokenAccountsByOwner','getMultipleAccounts'}:
        raise ValueError('OMNI_READ_ONLY_METHOD')
    result=_json(network['endpoint'],{'jsonrpc':'2.0','id':1,'method':method,'params':params})
    if not isinstance(result,dict) or result.get('error') or 'result' not in result or result.get('id')!=1: raise ValueError('OMNI_RPC_ERROR')
    return result['result']


def _uint(value):
    if not isinstance(value,str) or not value.startswith('0x') or len(value)>66 or len(value)<=2: raise ValueError('OMNI_UINT256')
    try: result=int(value,16)
    except ValueError: raise ValueError('OMNI_UINT256') from None
    if not 0<=result<2**256: raise ValueError('OMNI_UINT256')
    return result


def _evm_identity(network):
    if _uint(rpc(network,'eth_chainId',[]))!=int(network['id'].split(':')[1]): raise ValueError('OMNI_WRONG_CHAIN')


def _call(network,contract,data): return rpc(network,'eth_call',[{'to':contract,'data':data},'latest'])


def _abi_text(value):
    if not isinstance(value,str) or len(value)>1026: return ''
    try:
        raw=bytes.fromhex(value[2:])
        if len(raw)==32: return raw.rstrip(b'\0').decode('utf-8')[:96]
        if len(raw)<64 or int.from_bytes(raw[:32],'big')!=32: return ''
        size=int.from_bytes(raw[32:64],'big')
        if size>96 or 64+size>len(raw): return ''
        return raw[64:64+size].decode('utf-8')
    except (ValueError,UnicodeError): return ''


def import_token(chain,reference):
    network=store.network(chain); reference=store.address_for(network,reference)
    if network['family']=='evm':
        _evm_identity(network)
        if rpc(network,'eth_getCode',[reference,'latest']) in {'0x','0x0',''}: raise ValueError('OMNI_NOT_A_CONTRACT')
        decimals=None; symbol=''; name=''
        try:
            decimals=_uint(_call(network,reference,'0x313ce567'))
            if decimals>255: raise ValueError('OMNI_DECIMALS')
        except ValueError: decimals=None
        for key,selector in [('symbol','0x95d89b41'),('name','0x06fdde03')]:
            try: value=_abi_text(_call(network,reference,selector))
            except ValueError: value=''
            if key=='symbol': symbol=value
            else: name=value
        return store.register_asset(chain,'erc20',reference,symbol or reference[:8],name or 'Token '+reference[:8],decimals or 0,
            metadata='RPC_METADATA' if decimals is not None else 'DECIMALS_UNKNOWN')
    if network['family']=='solana':
        _sol_identity(network)
        result=rpc(network,'getAccountInfo',[reference,{'encoding':'jsonParsed','commitment':'confirmed'}]).get('value')
        if not isinstance(result,dict) or result.get('owner') not in {TOKEN_PROGRAM,TOKEN_2022_PROGRAM}: raise ValueError('OMNI_NOT_A_TOKEN_MINT')
        parsed=(result.get('data') or {}).get('parsed') or {}
        decimals=(parsed.get('info') or {}).get('decimals')
        if parsed.get('type')!='mint' or type(decimals) is not int or not 0<=decimals<=255: raise ValueError('OMNI_DECIMALS')
        metadata={}
        try:
            from backend import solana_metadata
            metadata=solana_metadata.batch(network,[reference]).get(reference,{})
        except Exception:pass  # Optional display metadata never blocks mint identity.
        return store.register_asset(chain,'token',reference,metadata.get('symbol') or reference[:6],metadata.get('name') or 'SPL '+reference[:8],decimals,metadata='RPC_METADATA')
    raise ValueError('OMNI_TOKEN_ADAPTER_UNAVAILABLE')


def _sol_identity(network):
    if str(rpc(network,'getGenesisHash',[]))[:32]!=network['id'].split(':',1)[1]: raise ValueError('OMNI_WRONG_CHAIN')


def balance(asset_id,account_id):
    asset=store.asset(asset_id); network=store.network(asset['chain_id'])
    with store.db() as db: account=db.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
    if not account or account['chain_id']!=asset['chain_id']: raise ValueError('OMNI_ACCOUNT_NETWORK_MISMATCH')
    address=account['address']; family=network['family']; namespace=asset['namespace']; reference=asset['reference']
    identity='ENDPOINT_AND_ADDRESS_PREFIX'
    extra={}
    if family=='evm':
        _evm_identity(network); identity='RPC_CHAIN_ID'
        raw=rpc(network,'eth_getBalance',[address,'latest']) if namespace=='native' else _call(network,reference,'0x70a08231'+address[2:].zfill(64))
        atomic=_uint(raw)
    elif family=='solana':
        _sol_identity(network); identity='GENESIS_HASH'
        if namespace=='native': atomic=rpc(network,'getBalance',[address,{'commitment':'confirmed'}]).get('value')
        else:
            values=rpc(network,'getTokenAccountsByOwner',[address,{'mint':reference},{'encoding':'jsonParsed','commitment':'confirmed'}]).get('value')
            if not isinstance(values,list) or len(values)>512: raise ValueError('OMNI_TOKEN_ACCOUNTS')
            atomic=0
            for row in values:
                if (row.get('account') or {}).get('owner') not in {TOKEN_PROGRAM,TOKEN_2022_PROGRAM}: raise ValueError('OMNI_TOKEN_ACCOUNT_PROGRAM')
                info=(((row.get('account') or {}).get('data') or {}).get('parsed') or {}).get('info') or {}
                amount=info.get('tokenAmount') or {}
                if info.get('owner')!=address or info.get('mint')!=reference or amount.get('decimals')!=asset['decimals']: raise ValueError('OMNI_TOKEN_ACCOUNT_IDENTITY')
                value=amount.get('amount')
                if not isinstance(value,str) or not value.isdigit(): raise ValueError('OMNI_BALANCE_SCHEMA')
                atomic+=int(value)
    elif family=='bitcoin' and namespace=='native':
        genesis=_text(network['endpoint']+'/block-height/0')
        if genesis!='000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f':raise ValueError('OMNI_WRONG_CHAIN')
        result=_json(network['endpoint']+'/address/'+quote(address,safe=''))
        if not isinstance(result,dict) or result.get('address')!=address:raise ValueError('OMNI_ADDRESS_RESPONSE')
        chain=result.get('chain_stats') or {};pool=result.get('mempool_stats') or {}
        values=[part.get(key) for part in (chain,pool) for key in ('funded_txo_sum','spent_txo_sum')]
        if any(type(v) is not int or not 0<=v<2**64 for v in values):raise ValueError('OMNI_BALANCE_SCHEMA')
        atomic=values[0]-values[1];identity='GENESIS_HASH'
        extra={'pending_atomic':str(values[2]-values[3]),'balance_scope':'CONFIRMED'}
    elif family=='gglab' and namespace=='native':
        from backend import omni_lab
        ledger=omni_lab.snapshot()
        if ledger.get('chain_id')!=network['id'] or (ledger.get('verification') or {}).get('state')!='VERIFIED' or address not in ledger.get('balances',{}):raise ValueError('OMNI_LAB_ACCOUNT')
        atomic=ledger['balances'][address];identity='LOCAL_LEDGER_REPLAY'
    elif family=='kaspa' and namespace=='native':
        dag=_json(network['endpoint']+'/info/blockdag')
        if dag.get('networkName')!='kaspa-mainnet': raise ValueError('OMNI_WRONG_CHAIN')
        atomic=_json(network['endpoint']+'/addresses/'+quote(address,safe='')+'/balance').get('balance')
        identity='RPC_NETWORK_NAME'
    elif family=='tron' and namespace=='native':
        result=_json(network['endpoint']+'/wallet/getaccount',{'address':address,'visible':True})
        if not isinstance(result,dict) or result.get('Error') or result.get('code'): raise ValueError('OMNI_RPC_ERROR')
        atomic=result.get('balance',0)
    elif family=='cardano' and namespace=='native':
        rows=_json(network['endpoint']+'/address_info',{'_addresses':[address]})
        if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('address')!=address: raise ValueError('OMNI_ADDRESS_NOT_FOUND')
        value=rows[0].get('balance')
        if not isinstance(value,str) or not value.isdigit(): raise ValueError('OMNI_BALANCE_SCHEMA')
        atomic=int(value)
    else: raise ValueError('OMNI_BALANCE_ADAPTER_UNAVAILABLE')
    if type(atomic) is not int or not 0<=atomic<2**256: raise ValueError('OMNI_BALANCE_SCHEMA')
    return {'asset_id':asset_id,'account_id':account_id,'atomic':str(atomic),
            'quantity':str(atomic)+' basenheter' if asset['metadata']=='DECIMALS_UNKNOWN' else store.format_atomic(atomic,asset['decimals']),
            'source':network['endpoint'],'identity_level':identity,'state':'VERIFIED_READ','decimals':asset['decimals'],**extra}
