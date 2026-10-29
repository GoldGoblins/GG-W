"""Bounded public collection directory. No listings, ownership or trading claims."""
import html
import json
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import quote,urlsplit
from backend import omni_assets as store,omni_rpc,crypto_explorer as markets,marketplace_media

LOCK=threading.RLock()
_PREVIEW_LOCK=threading.RLock()
_preview_thread=None
_preview_job=None
_IDENTITY_FIELDS=('id','provider','provider_id','platform','chain_id','collection')
_DETAIL_FIELDS=('description','floor_usd','volume_24h_usd','total_supply','image_url','image_error')

class _PreviewCancelled(Exception):
    pass

def _same_identity(first,second):
    return isinstance(first,dict) and isinstance(second,dict) and all(first.get(key)==second.get(key) for key in _IDENTITY_FIELDS)

def _cache_value(cached):
    if not cached:return None
    try:return json.loads(cached['body'])
    except (TypeError,ValueError):return None

def _preview_current(job):
    if (_preview_job is not job or job['cancel'].is_set() or str(store.ROOT)!=job['root']
        or (_pref('provider') or 'coingecko')!=job['provider'] or (_pref('page') or 1)!=job['page']):return False
    page=_cached(job['provider']+':page:'+str(job['page']))
    return bool(page and page['ts']==job['page_observed_at'])

def preview_status():
    with _PREVIEW_LOCK:
        if not _preview_job or _preview_job['root']!=str(store.ROOT):
            return {'state':'idle','total':0,'completed':0,'failed':0,'images':0,'ids':[],'active_id':'','error':'','worker_active':False}
        return {key:_preview_job[key] for key in ('state','provider','page','ids','total','completed','failed','images','active_id','error')} | {'worker_active':_preview_thread is not None and _preview_thread.is_alive()}

def stop_previews():
    with _PREVIEW_LOCK:
        if _preview_job and _preview_job['state']=='running':
            _preview_job['cancel'].set();_preview_job['state']='cancelled';_preview_job['active_id']=''

def _cancel_incompatible_previews(provider,page):
    with _PREVIEW_LOCK:
        if _preview_job and (_preview_job['provider']!=provider or _preview_job['page']!=page or _preview_job['root']!=str(store.ROOT)):
            stop_previews()

def _cg_json(url,guard=None):
    # Share the market provider's real request budget across both surfaces.
    with markets.LOCK:
        wait=markets.PROVIDERS['coingecko']['spacing']-(time.time()-markets._last_request.get('coingecko',0))
        if wait>0:
            store.event('marketplace','SOURCE_WAIT','','CoinGecko · väntar på anropsbudget')
            time.sleep(min(wait,3))
        if guard is not None:guard()
        markets._last_request['coingecko']=time.time()
        return omni_rpc._json(url)

def _db(write=False):
    with store.db() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS mp_discovery(key TEXT PRIMARY KEY,body TEXT NOT NULL,ts REAL NOT NULL,error TEXT NOT NULL); CREATE TABLE IF NOT EXISTS mp_discovery_prefs(key TEXT PRIMARY KEY,value TEXT NOT NULL);')
    return store.db(write)

def _pref(key,value=None):
    with _db(value is not None) as db:
        if value is not None:db.execute('INSERT OR REPLACE INTO mp_discovery_prefs VALUES(?,?)',(key,store.pack(value)))
        row=db.execute('SELECT value FROM mp_discovery_prefs WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None

def _cached(key):
    with _db() as db:row=db.execute('SELECT * FROM mp_discovery WHERE key=?',(key,)).fetchone()
    if not row:return None
    result=dict(row)
    try:
        if len(result['body'])>1024*1024:raise ValueError('CACHE_SIZE')
        body=json.loads(result['body'])
        if key.startswith('detail:'):
            if not isinstance(body,dict) or not isinstance(body.get('id'),str):raise ValueError('CACHE_SCHEMA')
        elif not isinstance(body,list) or len(body)>250 or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in body):raise ValueError('CACHE_SCHEMA')
    except (ValueError,TypeError):result.update(body='{}' if key.startswith('detail:') else '[]',ts=0,error='MP_DISCOVERY_CACHE_CORRUPT')
    return result

def _save(key,body,stamp=None,error=''):
    with _db(True) as db:
        db.execute('INSERT OR REPLACE INTO mp_discovery VALUES(?,?,?,?)',(key,store.pack(body),time.time() if stamp is None else stamp,error))
        db.execute('DELETE FROM mp_discovery WHERE key NOT IN (SELECT key FROM mp_discovery ORDER BY ts DESC LIMIT 128)')

def collections(raw,provider):
    values=raw if provider=='coingecko' else raw.get('result') if isinstance(raw,dict) else None
    if not isinstance(values,list) or len(values)>250:raise ValueError('MP_DISCOVERY_SCHEMA')
    rows=[];seen=set()
    for item in values:
        if not isinstance(item,dict):raise ValueError('MP_DISCOVERY_SCHEMA')
        if provider=='coingecko':
            key=markets._id(item.get('id'));chain=markets.PLATFORMS.get(item.get('asset_platform_id'),'');ref=item.get('contract_address','');name=item.get('name');symbol=item.get('symbol');standard=''
        else:
            key=str(item.get('tick',''))
            if not re.fullmatch(r'[A-Z0-9]{1,12}',key):raise ValueError('MP_DISCOVERY_TICK')
            chain='kaspa:mainnet';ref=key;name=key;symbol=key;standard='krc721'
        if ref is None:ref=''
        can_inspect=bool(chain and ref)
        if chain and provider=='coingecko':
            try:ref=store.address_for(store.network(chain),ref)
            except ValueError:can_inspect=False
        if not isinstance(ref,str) or len(ref)>160:continue
        identifier=provider+':'+key
        if identifier in seen:continue
        seen.add(identifier)
        rows.append({'id':identifier,'provider_id':key,'provider':provider,'name':store.text(name,100),'symbol':store.text(symbol,24),
            'chain_id':chain,'platform':store.text('Kaspa' if provider=='kat' else item.get('asset_platform_id') or 'Okänt nätverk',60),'collection':ref,'standard':standard,'can_inspect':can_inspect,
            'kind':'COLLECTION','status':'DIRECTORY_REFERENCE','tradable':False,'image_url':'','observed_at':time.time(),
            'description':'','floor_usd':None,'volume_24h_usd':None,'total_supply':str(item.get('minted','')) if provider=='kat' else '',
            'source':'CoinGecko NFT-katalog' if provider=='coingecko' else 'KAT KRC-721 indexer'})
    return rows

def refresh(provider='coingecko',page=1):
    if provider not in {'coingecko','kat'} or type(page) is not int or not 1<=page<=50:raise ValueError('MP_DISCOVERY_PAGE')
    if provider=='kat' and page!=1:raise ValueError('MP_DISCOVERY_CURSOR_REQUIRED')
    _cancel_incompatible_previews(provider,page)
    store.bootstrap();_pref('provider',provider);_pref('page',page);key=provider+':page:'+str(page)
    with LOCK:
        cached=_cached(key)
        if cached and 0<=time.time()-cached['ts']<300:return
        cooldown=_pref('attempt:'+provider) or 0
        if 0<=time.time()-cooldown<15:raise ValueError('MP_DISCOVERY_COOLDOWN')
        _pref('attempt:'+provider,time.time())
        store.event('marketplace','DIRECTORY_REQUEST_STARTED','','Publik samlingskatalog · '+provider)
        try:
            if provider=='coingecko':url='https://api.coingecko.com/api/v3/nfts/list?per_page=100&page='+str(page)
            else:
                base='https://krc721.kat.foundation/api/v1/krc721/mainnet'
                health=omni_rpc._json(base+'/status').get('result') or {}
                if health.get('network')!='mainnet' or not all(health.get(k) is True for k in ('isNodeConnected','isNodeSynced','isIndexerSynced')):raise ValueError('MP_INDEXER_UNSYNCED_OR_WRONG_CHAIN')
                url=base+'/nfts?limit=50'
            rows=collections(_cg_json(url) if provider=='coingecko' else omni_rpc._json(url),provider);_save(key,rows)
            store.event('marketplace','PUBLIC_DIRECTORY_READ','',str(len(rows))+' publika samlingsreferenser · '+provider)
        except Exception:
            _save(key,json.loads(cached['body']) if cached else [],cached['ts'] if cached else 0,'MP_DISCOVERY_SOURCE_UNAVAILABLE')
            store.event('marketplace','DIRECTORY_REQUEST_FAILED','',provider+' · källan kunde inte läsas')
            raise ValueError('MP_DISCOVERY_SOURCE_UNAVAILABLE') from None

def _image(url):
    if not isinstance(url,str):return ''
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='coin-images.coingecko.com' or parsed.port not in {None,443} or parsed.username or parsed.password or not parsed.path.startswith('/nft_contracts/images/'):return ''
    data=omni_rpc._response(url,max_bytes=2*1024*1024);directory=store.ROOT/'public-nft';directory.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory,suffix='.image',delete=False) as handle:handle.write(data);temporary=Path(handle.name)
    try:return marketplace_media.import_image(str(temporary),directory)['url']
    finally:temporary.unlink(missing_ok=True)

def _load_detail(item,job=None):
    item=dict(item);identifier=item['id'];cached=_cached('detail:'+identifier)
    if cached and not _same_identity(item,_cache_value(cached)):cached=None
    def current():
        if job is not None:
            with _PREVIEW_LOCK:
                if not _preview_current(job):raise _PreviewCancelled()
    def publish(body,stamp=None,error=''):
        if job is None:_save('detail:'+identifier,body,stamp,error)
        else:
            with _PREVIEW_LOCK:
                current();_save('detail:'+identifier,body,stamp,error)
    current()
    if cached and not cached['error'] and 0<=time.time()-cached['ts']<300:return _cache_value(cached)
    with LOCK:
        current()
        # A manual selection can have populated the same identity while this
        # bounded preview was waiting for the shared provider lane.
        latest=_cached('detail:'+identifier)
        if latest and not latest['error'] and _same_identity(item,_cache_value(latest)) and 0<=time.time()-latest['ts']<300:return _cache_value(latest)
        store.event('marketplace','COLLECTION_REQUEST_STARTED','',item['name']+' · samlingsdetaljer')
        try:
            if item['provider']=='coingecko':
                value=_cg_json('https://api.coingecko.com/api/v3/nfts/'+quote(item['provider_id'],safe=''),current)
                if not isinstance(value,dict) or value.get('id')!=item['provider_id'] or value.get('asset_platform_id')!=item['platform']:raise ValueError('MP_DISCOVERY_IDENTITY')
                reference=value.get('contract_address') or ''
                if not isinstance(reference,str):raise ValueError('MP_DISCOVERY_IDENTITY')
                evm=item['chain_id'].startswith('eip155:')
                if (reference.lower() if evm else reference)!=(item['collection'].lower() if evm else item['collection']):raise ValueError('MP_DISCOVERY_IDENTITY')
                item.update(description=store.text(html.unescape(re.sub('<[^>]+>',' ',str(value.get('description') or ''))),2000),
                    floor_usd=markets.number((value.get('floor_price') or {}).get('usd')),volume_24h_usd=markets.number((value.get('volume_24h') or {}).get('usd')),
                    total_supply=str(value.get('total_supply') or ''))
                current()
                item.pop('image_error',None)
                try:item['image_url']=_image((value.get('image') or {}).get('small_2x') or (value.get('image') or {}).get('small'))
                except (ValueError,OSError):item['image_error']='MP_COLLECTION_IMAGE_UNAVAILABLE'
            else:
                value=omni_rpc._json('https://krc721.kat.foundation/api/v1/krc721/mainnet/nfts/'+quote(item['collection'],safe='')).get('result') or {}
                if value.get('tick')!=item['collection']:raise ValueError('MP_DISCOVERY_IDENTITY')
                item.update(description='KRC-721 · '+str(value.get('state','')),total_supply=str(value.get('minted','')))
            current();publish(item)
            store.event('marketplace','COLLECTION_REQUEST_COMPLETED','',item['name']+' · samlingsdetaljer lästa')
            return item
        except _PreviewCancelled:
            raise
        except Exception:
            current();publish(json.loads(cached['body']) if cached else item,cached['ts'] if cached else 0,'MP_DISCOVERY_DETAIL_UNAVAILABLE')
            store.event('marketplace','COLLECTION_REQUEST_FAILED','',item['name']+' · samlingsdetaljer kunde inte läsas')
            raise ValueError('MP_DISCOVERY_DETAIL_UNAVAILABLE') from None

def select(identifier):
    state=snapshot();item=next((r for r in state['rows'] if r['id']==identifier),None)
    if not item:raise ValueError('MP_DISCOVERY_COLLECTION_NOT_IN_PAGE')
    _pref('selected',identifier)
    return _load_detail(item)

def _preview_worker(job,rows):
    global _preview_thread
    try:
        for row in rows:
            with _PREVIEW_LOCK:
                if not _preview_current(job):raise _PreviewCancelled()
                job['active_id']=row['id']
            failed=False;item=None
            try:item=_load_detail(row,job)
            except _PreviewCancelled:raise
            except Exception:failed=True
            with _PREVIEW_LOCK:
                if not _preview_current(job):raise _PreviewCancelled()
                job['completed']+=1;job['failed']+=int(failed or bool((item or {}).get('image_error')))
                job['images']+=int(bool((item or {}).get('image_url')))
                job['active_id']=''
        with _PREVIEW_LOCK:
            if _preview_current(job):job['state']='partial' if job['failed'] else 'done'
    except _PreviewCancelled:
        with _PREVIEW_LOCK:
            if _preview_job is job:job['cancel'].set();job['state']='cancelled';job['active_id']=''
    except Exception:
        with _PREVIEW_LOCK:
            if _preview_job is job:job['state']='failed';job['error']='MP_PREVIEW_UNAVAILABLE';job['active_id']=''
    finally:
        with _PREVIEW_LOCK:
            if _preview_job is job:_preview_thread=None

def previews(identifiers):
    global _preview_job,_preview_thread
    if not isinstance(identifiers,list) or not 1<=len(identifiers)<=6 or any(not isinstance(i,str) or len(i)>180 for i in identifiers) or len(set(identifiers))!=len(identifiers):raise ValueError('MP_PREVIEW_REQUEST')
    state=snapshot();available={r['id']:r for r in state['rows']}
    if any(i not in available for i in identifiers):raise ValueError('MP_DISCOVERY_COLLECTION_NOT_IN_PAGE')
    with _PREVIEW_LOCK:
        if _preview_thread is not None and _preview_thread.is_alive():
            if _preview_job and _preview_current(_preview_job) and _preview_job['ids']==identifiers:return
            raise ValueError('MP_PREVIEW_BUSY')
        job={'state':'running','provider':state['provider'],'page':state['page'],'page_observed_at':state['observed_at'],'ids':list(identifiers),'total':len(identifiers),'completed':0,'failed':0,'images':0,'active_id':'','error':'','root':str(store.ROOT),'cancel':threading.Event()}
        _preview_job=job
        _preview_thread=threading.Thread(target=_preview_worker,args=(job,[available[i] for i in identifiers]),name='gg-mp-previews',daemon=True)
        try:_preview_thread.start()
        except Exception:
            _preview_thread=None;job['state']='failed';job['error']='MP_PREVIEW_WORKER_UNAVAILABLE';job['cancel'].set();raise ValueError('MP_PREVIEW_WORKER_UNAVAILABLE') from None

def _enrich_rows(rows):
    if not rows:return []
    keys=['detail:'+r['id'] for r in rows]
    with _db() as db:records={r['key']:dict(r) for r in db.execute('SELECT * FROM mp_discovery WHERE key IN ('+','.join('?' for _ in keys)+')',keys)}
    enriched=[]
    for row in rows:
        detail=records.get('detail:'+row['id']);body=_cache_value(detail) if detail and len(detail['body'])<=1024*1024 else None
        result=dict(row)
        if _same_identity(row,body):
            result.update({key:body[key] for key in _DETAIL_FIELDS if key in body})
            result.update(detail_observed_at=detail['ts'],detail_error=detail['error'],detail_state='FAILED' if not detail['ts'] else 'STALE' if detail['error'] or not 0<=time.time()-detail['ts']<300 else 'CURRENT')
        enriched.append(result)
    return enriched

def snapshot():
    provider=_pref('provider') or 'coingecko';page=_pref('page') or 1;cached=_cached(provider+':page:'+str(page));selected_id=_pref('selected') or '';detail=_cached('detail:'+selected_id) if selected_id else None
    rows=_enrich_rows(json.loads(cached['body']) if cached else []);selected=next((r for r in rows if r['id']==selected_id),None)
    if not selected:detail=None
    return {'schema':'gg.mp-discovery.v1','provider':provider,'page':page,'rows':rows,'selected':selected,
        'source_state':'NOT_FETCHED' if not cached else 'FAILED' if not cached['ts'] else 'STALE' if cached['error'] or not 0<=time.time()-cached['ts']<300 else 'CURRENT',
        'observed_at':cached['ts'] if cached else None,'error':cached['error'] if cached else '',
        'detail_error':selected.get('detail_error','') if selected else '', 'events':store.events(limit=80),'preview_job':preview_status(),'authority':'NONE','scope':'PUBLIC_COLLECTION_DIRECTORY_NOT_SALE_LISTINGS'}

def action(raw):
    if not isinstance(raw,str) or len(raw)>2048:raise ValueError('MP_DISCOVERY_REQUEST')
    args=json.loads(raw or '{}')
    if not isinstance(args,dict) or args.get('action') not in {'refresh','select','previews','stop_previews'}:raise ValueError('MP_DISCOVERY_REQUEST')
    if args['action']=='refresh':refresh(args.get('provider','coingecko'),args.get('page',1))
    elif args['action']=='select':select(args.get('id',''))
    elif args['action']=='previews':previews(args.get('ids'))
    else:stop_previews()
