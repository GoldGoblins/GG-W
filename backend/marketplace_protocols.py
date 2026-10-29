"""Semantic GG asset contracts with explicit, replaceable read adapters.

GG-20 = fungible quantities; GG-721 = individually identified objects;
GG-1155 = editions. These are local interface names, not deployed standards.
No adapter in this module signs, approves, bridges or settles a transaction.
"""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
from backend import omni_assets as store,omni_rpc as rpc

MODULES={
 'gg721':{'name':'GG-721 · kvitton och objekt','kind':'UNIQUE','state':'LOCAL_PAPER','required':True,'families':['*'],'operations':['identity','provenance','paper_list','paper_buy']},
 'gg20':{'name':'GG-20 · delbara tillgångar','kind':'FUNGIBLE','state':'PUBLIC_READ','required':True,'families':['*'],'operations':['identity','exact_amount']},
 'erc721':{'name':'ERC-721 · EVM NFT','kind':'UNIQUE','state':'PUBLIC_READ','required':False,'families':['evm'],'operations':['identity','owner.read','metadata_uri.read']},
 'erc1155':{'name':'ERC-1155 · utgåvor','kind':'EDITION','state':'PUBLIC_READ','required':False,'families':['evm'],'operations':['identity','balance.read','metadata_uri.read']},
 'krc721':{'name':'KRC-721 · Kaspa indexer','kind':'UNIQUE','state':'INDEXER_READ','required':False,'families':['kaspa'],'operations':['identity','owner.read','metadata_uri.read']},
 'royalties':{'name':'ERC-2981 · royaltyinformation','kind':'ROYALTY','state':'PUBLIC_READ','required':False,'families':['evm'],'operations':['royalty.quote']},
}
KRC_INDEXER='https://krc721.kat.foundation'


def _tables(db):
    db.executescript('CREATE TABLE IF NOT EXISTS mp_modules(id TEXT PRIMARY KEY,enabled INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS mp_nfts(id TEXT PRIMARY KEY,body TEXT NOT NULL);')


def modules():
    with store.db() as db:
        _tables(db); flags={r['id']:bool(r['enabled']) for r in db.execute('SELECT * FROM mp_modules')}
    return [dict(body,id=key,enabled=body['required'] or flags.get(key,True)) for key,body in MODULES.items()]


def toggle(name,enabled):
    if name not in MODULES or type(enabled) is not bool: raise ValueError('MP_MODULE')
    if MODULES[name]['required'] and not enabled: raise ValueError('MP_CORE_MODULE_REQUIRED')
    with store.db() as db: _tables(db)
    with store.db(True) as db: db.execute('INSERT OR REPLACE INTO mp_modules VALUES(?,?)',(name,int(enabled)))
    store.event('marketplace','MODULE_ENABLED' if enabled else 'MODULE_PAUSED','',MODULES[name]['name'])


def require(name):
    if not any(m['id']==name and m['enabled'] for m in modules()): raise ValueError('MP_MODULE_PAUSED')


def uint(value,bits=256):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,78}',value): raise ValueError('MP_TOKEN_ID_STRING_REQUIRED')
    number=int(value)
    if number>=2**bits: raise ValueError('MP_TOKEN_ID_RANGE')
    return str(number)


def identity(chain,standard,collection,token_id):
    require(standard)
    net=store.network(chain)
    if standard not in {'erc721','erc1155','krc721','gg721'}: raise ValueError('MP_NFT_STANDARD')
    if standard in {'erc721','erc1155'}:
        if net['family']!='evm': raise ValueError('MP_ADAPTER_FAMILY')
        collection=store.evm_address(collection);token_id=uint(token_id)
    elif standard=='krc721':
        if net['family']!='kaspa': raise ValueError('MP_ADAPTER_FAMILY')
        collection=str(collection).lower()
        if not re.fullmatch(r'[a-z0-9]{1,10}',collection): raise ValueError('MP_KRC_COLLECTION')
        token_id=uint(token_id,64)
    else:
        if not re.fullmatch(r'[-a-zA-Z0-9]{1,96}',str(collection)): raise ValueError('MP_GG_COLLECTION')
        if not isinstance(token_id,str) or not re.fullmatch(r'[-_.a-zA-Z0-9]{1,128}',token_id):raise ValueError('MP_GG_OBJECT_ID')
    return {'id':chain+'/'+standard+':'+collection+'/'+token_id,'chain_id':chain,'standard':standard,
            'collection':collection,'token_id':token_id,'kind':MODULES[standard]['kind']}


def safe_uri(value,token_id=None):
    value=str(value or '')
    if len(value)>2048: raise ValueError('MP_METADATA_URI_SIZE')
    if token_id is not None:value=value.replace('{id}',format(int(token_id),'064x'))
    if not value:return ''
    url=urlsplit(value)
    if url.scheme not in {'https','ipfs','ar'} or url.username or url.password or not url.netloc: raise ValueError('MP_METADATA_URI_SCHEME')
    return value


def _abi_string(raw):
    try:
        data=bytes.fromhex(raw[2:])
        if len(data)>4096 or len(data)<64 or int.from_bytes(data[:32],'big')!=32: return ''
        size=int.from_bytes(data[32:64],'big')
        if size>2048 or 64+size>len(data): return ''
        return data[64:64+size].decode('utf-8')
    except (TypeError,ValueError,UnicodeError):return ''


def _address_word(raw):
    if not isinstance(raw,str) or not re.fullmatch(r'0x0{24}[0-9a-fA-F]{40}',raw): raise ValueError('MP_OWNER_RESPONSE')
    return store.evm_address('0x'+raw[-40:])


def inspect(chain,standard,collection,token_id,holder=''):
    item=identity(chain,standard,collection,token_id);net=store.network(chain);collection=item['collection'];token_id=item['token_id'];metadata_uri=''
    if standard in {'erc721','erc1155'}:
        rpc._evm_identity(net)
        def call(data):return rpc._call(net,collection,data)
        # ERC-165: require 165 itself, reject the reserved invalid interface.
        for interface,expected in [('01ffc9a7',1),('ffffffff',0),('80ac58cd' if standard=='erc721' else 'd9b67a26',1)]:
            if rpc._uint(call('0x01ffc9a7'+interface+'0'*56))!=expected: raise ValueError('MP_INTERFACE_NOT_SUPPORTED')
        word=format(int(token_id),'064x')
        if standard=='erc721':
            owner=_address_word(call('0x6352211e'+word));item.update(owner=owner,quantity='1',ownership='RPC_OWNER_READ')
            if owner=='0x'+'0'*40:raise ValueError('MP_NFT_NOT_MINTED')
            selector='0xc87b56dd'
        else:
            holder=store.evm_address(holder)
            amount=rpc._uint(call('0x00fdd58e'+holder[2:].zfill(64)+word))
            item.update(holder=holder,quantity=str(amount),ownership='RPC_BALANCE_READ');selector='0x0e89341c'
        try: metadata_uri=safe_uri(_abi_string(call(selector+word)),token_id if standard=='erc1155' else None)
        except ValueError: metadata_uri=''
        item.update(source=net['endpoint'],trust='RPC_CHAIN_ID_AND_INTERFACE')
    elif standard=='krc721':
        base=KRC_INDEXER+'/api/v1/krc721/mainnet'
        status=rpc._json(base+'/status');status=status.get('result') or {}
        if status.get('network')!='mainnet' or not all(status.get(k) is True for k in ('isNodeConnected','isNodeSynced','isIndexerSynced')): raise ValueError('MP_INDEXER_UNSYNCED_OR_WRONG_CHAIN')
        response=rpc._json(base+'/nfts/'+collection+'/'+token_id);result=response.get('result')
        if not isinstance(result,dict) or str(result.get('tick','')).lower()!=collection or uint(str(result.get('tokenId','')),64)!=token_id: raise ValueError('MP_INDEXER_TOKEN_IDENTITY')
        owner=store.address_for(net,result.get('owner',''));uri=result.get('buri') or ''
        metadata_uri=safe_uri(str(uri).rstrip('/')+'/'+token_id) if uri else ''
        item.update(owner=owner,quantity='1',ownership='INDEXER_OWNER_READ',source=KRC_INDEXER,trust='THIRD_PARTY_INDEXER')
    else:raise ValueError('MP_GG721_USE_LOCAL_RECEIPTS')
    item.update(metadata_uri=metadata_uri,observed_at=time.time(),state='READ_ONLY',metadata_state='URI_ONLY_NOT_FETCHED',settlement='NOT_CONNECTED')
    with store.db() as db:_tables(db)
    with store.db(True) as db:
        if db.execute('SELECT COUNT(*) FROM mp_nfts').fetchone()[0]>=2000 and not db.execute('SELECT 1 FROM mp_nfts WHERE id=?',(item['id'],)).fetchone():raise ValueError('MP_NFT_WATCH_LIMIT')
        db.execute('INSERT OR REPLACE INTO mp_nfts VALUES(?,?)',(item['id'],store.pack(item)))
    store.event('marketplace','NFT_INSPECTED',item['id'],standard+' · '+collection+' #'+token_id+' · '+item['trust'])
    return item


def royalty_quote(chain,collection,token_id,sale_atomic):
    require('royalties');net=store.network(chain)
    if net['family']!='evm':raise ValueError('MP_ROYALTY_ADAPTER_UNAVAILABLE')
    collection=store.evm_address(collection);token_id=uint(token_id);sale_atomic=uint(sale_atomic)
    rpc._evm_identity(net)
    if rpc._uint(rpc._call(net,collection,'0x01ffc9a7'+'2a55205a'+'0'*56))!=1:raise ValueError('MP_ERC2981_NOT_SUPPORTED')
    result=rpc._call(net,collection,'0x2a55205a'+format(int(token_id),'064x')+format(int(sale_atomic),'064x'))
    if not isinstance(result,str) or not re.fullmatch(r'0x[0-9a-fA-F]{128}',result):raise ValueError('MP_ROYALTY_RESPONSE')
    receiver=_address_word(result[:66]);amount=rpc._uint('0x'+result[66:])
    if amount>int(sale_atomic):raise ValueError('MP_ROYALTY_EXCEEDS_PRICE')
    return {'receiver':receiver,'amount_atomic':str(amount),'sale_atomic':sale_atomic,'state':'QUOTE_ONLY','enforced':False,'unit':'SAME_AS_SALE_PRICE'}


def snapshot():
    with store.db() as db:
        _tables(db);rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM mp_nfts ORDER BY rowid DESC LIMIT 200')]
        total=db.execute('SELECT COUNT(*) FROM mp_nfts').fetchone()[0]
    return {'modules':modules(),'watched_nfts':rows,'watched_count':total,'loaded_count':len(rows),
            'interop':{'schema':'gg.semantic-assets.v1','fungible':'GG-20','unique':'GG-721','editions':'GG-1155',
                       'rule':'PRESERVE_SEMANTICS_PER_ADAPTER','bridge':'NO_VERIFIED_ROUTE','settlement':'LOCAL_PAPER_ONLY'}}
