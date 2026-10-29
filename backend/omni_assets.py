"""Network-qualified public assets, exact amounts and a local activity ledger.

Ticker text is presentation, never identity. This registry grants no wallet,
exchange, bridge, signing or mainnet execution authority.
"""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from backend.application_paths import STATE_ROOT
from backend.research_workbench import _redact

ROOT=STATE_ROOT/'omni'
PROJECT=Path(__file__).resolve().parents[1]
_LOCK=threading.RLock()
CHAIN_RE=re.compile(r'^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}$')
NATIVE_SOL='solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp/native:SOL'


@contextmanager
def db(write=False):
    with _LOCK:
        ROOT.mkdir(parents=True,exist_ok=True)
        connection=sqlite3.connect(ROOT/'omni.sqlite3',timeout=5)
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.executescript('''
          CREATE TABLE IF NOT EXISTS networks(id TEXT PRIMARY KEY,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,chain_id TEXT NOT NULL REFERENCES networks(id),body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,chain_id TEXT NOT NULL,address TEXT NOT NULL,label TEXT NOT NULL,provider TEXT NOT NULL,UNIQUE(chain_id,address));
          CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS observations(asset_id TEXT NOT NULL,account_id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(asset_id,account_id));
          CREATE TABLE IF NOT EXISTS activity(seq INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL NOT NULL,scope TEXT NOT NULL,kind TEXT NOT NULL,asset_id TEXT NOT NULL,message TEXT NOT NULL,dedupe TEXT UNIQUE);
          CREATE TABLE IF NOT EXISTS bot_markets(asset_id TEXT PRIMARY KEY,pair TEXT NOT NULL,provider TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_states(asset_id TEXT PRIMARY KEY,body TEXT NOT NULL);
        ''')
        if write: connection.execute('BEGIN IMMEDIATE')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback(); raise
        finally: connection.close()


def text(value,limit=160):
    return _redact(' '.join(str(value or '').split()))[:limit]


def pack(value): return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def chain_id(value):
    value=str(value or '')
    if not CHAIN_RE.fullmatch(value): raise ValueError('OMNI_CHAIN_ID')
    return value


def amount_atomic(value,decimals):
    if type(decimals) is not int or not 0<=decimals<=255 or isinstance(value,(bool,float)):
        raise ValueError('OMNI_EXACT_AMOUNT_REQUIRED')
    value=str(value).strip()
    if len(value)>340 or not re.fullmatch(r'\d+(?:\.\d+)?',value): raise ValueError('OMNI_AMOUNT')
    whole,_,fraction=value.partition('.')
    if len(fraction)>decimals: raise ValueError('OMNI_AMOUNT_PRECISION')
    result=int(whole)*10**decimals+int((fraction+'0'*decimals)[:decimals] or '0')
    if result>=2**256: raise ValueError('OMNI_AMOUNT_RANGE')
    return result


def format_atomic(value,decimals):
    if type(value) is not int or value<0 or type(decimals) is not int or not 0<=decimals<=255: raise ValueError('OMNI_AMOUNT')
    if not decimals: return str(value)
    whole,fraction=divmod(value,10**decimals)
    return (str(whole)+'.'+str(fraction).zfill(decimals)).rstrip('0').rstrip('.')


def evm_address(value):
    value=str(value or '').strip()
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}',value): raise ValueError('OMNI_EVM_ADDRESS')
    body=value[2:]
    if body!=body.lower() and body!=body.upper():
        from Crypto.Hash import keccak
        digest=keccak.new(digest_bits=256,data=body.lower().encode()).hexdigest()
        if any(c.isalpha() and c.isupper()!=(int(digest[i],16)>=8) for i,c in enumerate(body)):
            raise ValueError('OMNI_ADDRESS_CHECKSUM')
    return value.lower()


def address_for(network,value):
    value=str(value or '').strip(); family=network['family']
    if family=='evm': return evm_address(value)
    if family=='solana':
        from backend.crypto_contract import validate_pubkey
        return validate_pubkey(value)
    if family=='bitcoin':
        from backend.bitcoin_address import validate
        return validate(value)
    if family=='kaspa':
        from backend.kaspa_address import validate
        value=validate(value)
        if not value.startswith('kaspa:'): raise ValueError('OMNI_ADDRESS_NETWORK')
        return value
    if family=='tron':
        from backend.crypto_keys import b58decode,b58encode
        data=b58decode(value)
        if len(data)!=25 or data[0]!=0x41 or hashlib.sha256(hashlib.sha256(data[:-4]).digest()).digest()[:4]!=data[-4:] or b58encode(data)!=value:
            raise ValueError('OMNI_TRON_ADDRESS')
        return value
    if family=='cardano':
        from bech32 import bech32_decode,convertbits
        hrp,data=bech32_decode(value)
        raw=convertbits(data or [],5,8,False)
        if hrp!='addr' or raw is None or len(raw) not in {29,57} or raw[0]&15!=1:
            raise ValueError('OMNI_CARDANO_ADDRESS')
        if (raw[0]>>4 not in {0,1,2,3} or len(raw)!=57) and (raw[0]>>4 not in {6,7} or len(raw)!=29):
            raise ValueError('OMNI_CARDANO_ADDRESS_TYPE_UNAVAILABLE')
        return value.lower()
    if family=='gglab' and re.fullmatch('[1-9A-HJ-NP-Za-km-z]{32,44}',value): return value
    raise ValueError('OMNI_ADDRESS_ADAPTER_UNAVAILABLE')


def _network_row(row):
    row=dict(row); row['id']=chain_id(row['id'])
    if row.get('family') not in {'evm','solana','bitcoin','kaspa','tron','cardano','gglab','custom'}: raise ValueError('OMNI_NETWORK_FAMILY')
    if row['family']=='bitcoin' and row['id']!='bip122:000000000019d6689c085ae165831e93':raise ValueError('OMNI_BITCOIN_CHAIN_ID')
    if row['family']=='evm' and not re.fullmatch(r'eip155:[1-9][0-9]{0,20}',row['id']): raise ValueError('OMNI_EVM_CHAIN_ID')
    if row['family']=='solana' and not re.fullmatch(r'solana:[1-9A-HJ-NP-Za-km-z]{32}',row['id']): raise ValueError('OMNI_SOLANA_CHAIN_ID')
    if row['family'] in {'kaspa','tron','cardano'} and row['id']!=row['family']+':mainnet': raise ValueError('OMNI_NETWORK_ADAPTER_IDENTITY')
    row['name']=text(row.get('name'),64); row['symbol']=text(row.get('symbol'),16)
    if not row['name'] or not row['symbol'] or type(row.get('decimals')) is not int or not 0<=row['decimals']<=255: raise ValueError('OMNI_NETWORK_METADATA')
    endpoint=str(row.get('endpoint') or '')
    if endpoint:
        url=urlsplit(endpoint)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('OMNI_PUBLIC_ENDPOINT_REQUIRED')
    row['endpoint']=endpoint
    row['execution']='LOCAL_LAB' if row['family']=='gglab' else 'READ_ONLY'
    row['namespace_status']=row.get('namespace_status','GG_PRIVATE_EXTENSION')
    return row


def bootstrap():
    rows=json.loads((PROJECT/'config/omni-networks.json').read_text(encoding='utf-8'))['networks']
    with db(True) as connection:
        for raw in rows:
            row=_network_row(raw)
            connection.execute('INSERT OR IGNORE INTO networks VALUES(?,?)',(row['id'],pack(row)))
            asset={'id':row['id']+'/native:'+row['symbol'],'chain_id':row['id'],'namespace':'native','reference':row['symbol'],
                   'symbol':row['symbol'],'name':row['name'],'decimals':row['decimals'],'metadata':'BUILTIN','behavior':'NATIVE'}
            connection.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?)',(asset['id'],row['id'],pack(asset)))


def register_network(row):
    row=_network_row(row)
    with db(True) as connection:
        if connection.execute('SELECT COUNT(*) FROM networks').fetchone()[0]>=128 and not connection.execute('SELECT 1 FROM networks WHERE id=?',(row['id'],)).fetchone(): raise ValueError('OMNI_NETWORK_LIMIT')
        old=connection.execute('SELECT body FROM networks WHERE id=?',(row['id'],)).fetchone()
        if old and json.loads(old['body'])!=row: raise ValueError('OMNI_NETWORK_ID_ALREADY_BOUND')
        connection.execute('INSERT OR IGNORE INTO networks VALUES(?,?)',(row['id'],pack(row)))
    return row


def network(value):
    with db() as connection: row=connection.execute('SELECT body FROM networks WHERE id=?',(chain_id(value),)).fetchone()
    if not row: raise ValueError('OMNI_NETWORK_NOT_FOUND')
    return json.loads(row[0])


def register_asset(chain,namespace,reference,symbol,name,decimals,metadata='USER_SUPPLIED',behavior='UNKNOWN'):
    net=network(chain)
    if namespace not in {'native','erc20','token','asset'}: raise ValueError('OMNI_ASSET_NAMESPACE')
    reference=str(reference or '')
    if namespace=='native' and (reference!=net['symbol'] or decimals!=net['decimals']): raise ValueError('OMNI_NATIVE_IDENTITY')
    if namespace=='erc20':
        if net['family']!='evm': raise ValueError('OMNI_ASSET_FAMILY')
        reference=evm_address(reference)
    elif namespace=='token':
        if net['family']!='solana': raise ValueError('OMNI_ASSET_FAMILY')
        reference=address_for(net,reference)
    elif not re.fullmatch(r'[-.%a-zA-Z0-9]{1,128}',reference): raise ValueError('OMNI_ASSET_REFERENCE')
    if type(decimals) is not int or not 0<=decimals<=255: raise ValueError('OMNI_DECIMALS')
    identifier=chain+'/'+namespace+':'+reference
    row={'id':identifier,'chain_id':chain,'namespace':namespace,'reference':reference,'symbol':text(symbol,24),
         'name':text(name,96),'decimals':decimals,'metadata':metadata,'behavior':behavior}
    if not row['symbol'] or not row['name']: raise ValueError('OMNI_ASSET_METADATA')
    with db(True) as connection:
        old=connection.execute('SELECT body FROM assets WHERE id=?',(identifier,)).fetchone()
        if old:
            previous=json.loads(old[0])
            if previous['metadata']=='DECIMALS_UNKNOWN' and metadata=='RPC_METADATA':
                connection.execute('UPDATE assets SET body=? WHERE id=?',(pack(row),identifier))
                connection.execute('DELETE FROM observations WHERE asset_id=?',(identifier,))
                return row
            if previous['decimals']!=decimals: raise ValueError('OMNI_DECIMALS_CONFLICT')
            if namespace=='token' and metadata=='RPC_METADATA' and previous['symbol']==reference[:6] and row['symbol']!=reference[:6]:
                previous.update(symbol=row['symbol'],name=row['name'])
                connection.execute('UPDATE assets SET body=? WHERE id=?',(pack(previous),identifier))
                return previous
            return previous
        if connection.execute('SELECT COUNT(*) FROM assets').fetchone()[0]>=2000: raise ValueError('OMNI_ASSET_LIMIT')
        connection.execute('INSERT INTO assets VALUES(?,?,?)',(identifier,chain,pack(row)))
    event('assets','REGISTERED',identifier,'Tillgång registrerad · '+row['symbol'])
    return row


def asset(identifier):
    with db() as connection: row=connection.execute('SELECT body FROM assets WHERE id=?',(identifier,)).fetchone()
    if not row: raise ValueError('OMNI_ASSET_NOT_FOUND')
    return json.loads(row[0])


def account(chain,address,label='',provider='watch'):
    if provider!='watch': raise ValueError('OMNI_PROVIDER_CONNECTION_REQUIRED')
    address=address_for(network(chain),address)
    identifier='account-'+hashlib.sha256((chain+'\0'+address).encode()).hexdigest()[:24]
    with db(True) as connection:
        if connection.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]>=128 and not connection.execute('SELECT 1 FROM accounts WHERE id=?',(identifier,)).fetchone(): raise ValueError('OMNI_ACCOUNT_LIMIT')
        connection.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?)',(identifier,chain,address,text(label,64) or 'Bevakningskonto',provider))
    event('wallet','WATCH_CONNECTED','',network(chain)['name']+' · bevakningskonto tillagt')
    return identifier


def event(scope,kind,asset_id,message,dedupe=None):
    with db(True) as connection:
        connection.execute('INSERT OR IGNORE INTO activity(ts,scope,kind,asset_id,message,dedupe) VALUES(?,?,?,?,?,?)',
            (time.time(),text(scope,24),text(kind,40),str(asset_id)[:240],text(message,500),dedupe))
        connection.execute('DELETE FROM activity WHERE seq <= (SELECT COALESCE(MAX(seq),0)-4096 FROM activity)')


def events(after=0,scope='',limit=100):
    if type(after) is not int or after<0 or type(limit) is not int: raise ValueError('OMNI_EVENT_CURSOR')
    with db() as connection:
        rows=connection.execute('SELECT seq,ts,scope,kind,asset_id,message FROM activity WHERE seq>? AND (?=\'\' OR scope=?) ORDER BY seq DESC LIMIT ?',
            (after,scope,scope,max(1,min(256,limit)))).fetchall()
    return [dict(row) for row in reversed(rows)]


def preference(key,value=None):
    if key not in {'selected_asset','selected_transfer','show_events','follow_events','events_paused'}: raise ValueError('OMNI_PREFERENCE')
    with db(value is not None) as connection:
        if value is not None: connection.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)',(key,pack(value)))
        row=connection.execute('SELECT value FROM preferences WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def snapshot():
    bootstrap()
    with db() as connection:
        nets=[json.loads(row[0]) for row in connection.execute('SELECT body FROM networks ORDER BY rowid')]
        assets=[json.loads(row[0]) for row in connection.execute('SELECT body FROM assets ORDER BY rowid')]
        accounts=[dict(row) for row in connection.execute('SELECT * FROM accounts ORDER BY rowid')]
        observations=[json.loads(row[0]) for row in connection.execute('SELECT body FROM observations LIMIT 512')]
    return {'status':'READY','networks':nets,'assets':assets,'accounts':accounts,'observations':observations,
            'events':events(),'selected_asset':preference('selected_asset') or NATIVE_SOL,
            'providers':[{'name':name,'state':state} for name,state in [('Watch','READY'),('Ledger','DEVICE_REQUIRED'),('Tangem','DEVICE_REQUIRED'),
                         ('Binance','ACCOUNT_CONNECTION_REQUIRED'),('Kraken','ACCOUNT_CONNECTION_REQUIRED'),('KuCoin','ACCOUNT_CONNECTION_REQUIRED'),('Pionex','ACCOUNT_CONNECTION_REQUIRED')]],
            'authority':'NONE','bridge_state':'NO_BRIDGE_CONFIGURED'}
