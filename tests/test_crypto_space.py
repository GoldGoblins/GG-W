"""Collection discovery, true events and the shared UI's public read contracts."""
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image
from backend import omni_assets as assets,omni_rpc,crypto_explorer as markets,marketplace_discovery as discovery,crypto_activity

def collection(identifier='sample',chain='ethereum',address=None):
    return {'id':identifier,'name':'Sample collection','symbol':'SAME','asset_platform_id':chain,'contract_address':address or '0x'+'1'*40}

class CryptoSpaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(assets,'ROOT',Path(self.temp.name));self.root.start();assets.bootstrap()
        self.provider=patch.object(markets,'PROVIDERS',{k:dict(v,spacing=0) for k,v in markets.PROVIDERS.items()});self.provider.start()
    def tearDown(self):self.provider.stop();self.root.stop();self.temp.cleanup()

    def test_no_fake_activity_or_network_from_snapshots(self):
        with patch.object(omni_rpc,'_json') as request:
            before=crypto_activity.snapshot()
            for _ in range(5):
                self.assertEqual(crypto_activity.snapshot(),before);self.assertEqual(discovery.snapshot()['source_state'],'NOT_FETCHED')
            self.assertFalse(request.called);self.assertEqual(before['events'],[])
        self.assertNotIn('progress',before);self.assertNotIn('percent',before)

    def test_actual_started_event_is_readable_while_request_is_blocked(self):
        entered=threading.Event();release=threading.Event();errors=[]
        def request(*args,**kwargs):entered.set();release.wait(3);return [collection()]
        def run():
            try:discovery.refresh()
            except Exception as exc:errors.append(exc)
        with patch.object(omni_rpc,'_json',side_effect=request):
            thread=threading.Thread(target=run);thread.start()
            try:
                self.assertTrue(entered.wait(2));events=crypto_activity.snapshot()['events'];kinds=[e['kind'] for e in events]
                self.assertIn('DIRECTORY_REQUEST_STARTED',kinds);self.assertNotIn('PUBLIC_DIRECTORY_READ',kinds)
                self.assertEqual(crypto_activity.snapshot()['events'],events)
            finally:release.set();thread.join(4)
        self.assertFalse(errors);self.assertFalse(thread.is_alive());self.assertIn('PUBLIC_DIRECTORY_READ',[e['kind'] for e in crypto_activity.snapshot()['events']])

    def test_same_ticker_different_network_and_no_sale_or_owner_invention(self):
        rows=discovery.collections([collection(),collection('base-copy','base')],'coingecko')
        self.assertEqual({r['chain_id'] for r in rows},{'eip155:1','eip155:8453'})
        self.assertTrue(all(r['tradable'] is False and not r['standard'] for r in rows))
        self.assertTrue(all('owner' not in r and r['floor_usd'] is None for r in rows))
        unresolved=discovery.collections([collection('solana-format','solana','collection-slug')],'coingecko')
        self.assertEqual(len(unresolved),1);self.assertFalse(unresolved[0]['can_inspect'])
        missing=discovery.collections([dict(collection('ordinals','bitcoin'),contract_address=None)],'coingecko')
        self.assertEqual(len(missing),1);self.assertFalse(missing[0]['can_inspect']);self.assertEqual(missing[0]['platform'],'bitcoin')
        with self.assertRaises(ValueError):discovery.collections([collection()]*251,'coingecko')

    def test_failed_refresh_keeps_last_valid_catalog_and_cache_has_no_extra_requests(self):
        with patch.object(omni_rpc,'_json',return_value=[collection()]) as request:
            discovery.refresh();discovery.refresh();self.assertEqual(request.call_count,1)
        first=discovery.snapshot();discovery._save('coingecko:page:1',first['rows'],time.time()-301);discovery._pref('attempt:coingecko',0)
        with patch.object(omni_rpc,'_json',side_effect=OSError('offline')):
            with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):discovery.refresh()
        after=discovery.snapshot();self.assertEqual(after['rows'],first['rows']);self.assertEqual(after['source_state'],'STALE')
        with discovery._db(True) as db:db.execute('UPDATE mp_discovery SET body=? WHERE key=?',('broken-json','coingecko:page:1'))
        self.assertEqual(discovery.snapshot()['source_state'],'FAILED');self.assertEqual(discovery.snapshot()['rows'],[])
        discovery._pref('attempt:coingecko',0)
        with patch.object(omni_rpc,'_json',return_value=[collection()]):discovery.refresh()
        self.assertEqual(discovery.snapshot()['source_state'],'CURRENT')

    def test_wrong_collection_detail_identity_never_replaces_reference(self):
        with patch.object(omni_rpc,'_json',return_value=[collection()]):discovery.refresh()
        value=collection(address='0x'+'2'*40)
        with patch.object(omni_rpc,'_json',return_value=value),patch.object(omni_rpc,'_response') as image:
            with self.assertRaisesRegex(ValueError,'DETAIL_UNAVAILABLE'):discovery.select('coingecko:sample')
            self.assertFalse(image.called)
        selected=discovery.snapshot()['selected'];self.assertEqual(selected['collection'],'0x'+'1'*40)

    def test_public_image_is_pinned_and_validated_before_local_preview(self):
        for url in ('https://127.0.0.1/a.png','http://coin-images.coingecko.com/nft_contracts/images/a.png','https://other.example/nft_contracts/images/a.png'):
            with patch.object(omni_rpc,'_response') as fetch:self.assertEqual(discovery._image(url),'');self.assertFalse(fetch.called)
        data=io.BytesIO();Image.new('RGB',(32,24),(10,10,10)).save(data,format='PNG')
        with patch.object(omni_rpc,'_response',return_value=data.getvalue()):url=discovery._image('https://coin-images.coingecko.com/nft_contracts/images/test.png')
        self.assertTrue(url.startswith('file:'));self.assertEqual(len(list((assets.ROOT/'public-nft/media').glob('*.png'))),1)

    def test_kaspa_directory_checks_sync_before_returning_collection_references(self):
        health={'result':{'network':'mainnet','isNodeConnected':True,'isNodeSynced':True,'isIndexerSynced':False}}
        with patch.object(omni_rpc,'_json',return_value=health):
            with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):discovery.refresh('kat')
        self.assertEqual(discovery.snapshot()['source_state'],'FAILED')

    def test_manual_selection_loads_real_week_history_with_distinct_fetch_events(self):
        rows=markets.parse_coins([dict(id='bitcoin',name='Bitcoin',symbol='BTC',current_price=100,sparkline_in_7d={'price':[90,100]})]);markets._save_rows(rows)
        def response(url,**kwargs):
            if '/market_chart?' in url:return {'prices':[[int((time.time()-1000)*1000),99],[int(time.time()*1000),100]]}
            return {'id':'bitcoin','platforms':{},'market_data':{'current_price':{'usd':100}}}
        with patch.object(omni_rpc,'_json',side_effect=response):markets.action('select',json.dumps({'id':rows[0]['id'],'history':True}))
        state=markets.snapshot();self.assertEqual(state['selected']['chart']['period_days'],7)
        self.assertEqual(sum(e['kind']=='REQUEST_STARTED' for e in state['events']),2)
        self.assertEqual(sum(e['kind']=='REQUEST_COMPLETED' for e in state['events']),2)

    def test_connect_watch_reads_registered_assets_without_claiming_unknown_balances(self):
        from backend import omni_service,omni_wallet
        def balance(asset_id,account_id):return {'asset_id':asset_id,'account_id':account_id,'atomic':'5000000000000000000','quantity':'5','identity_level':'TEST_SOURCE','state':'VERIFIED_READ','decimals':18}
        with patch.object(omni_rpc,'balance',side_effect=balance) as read:
            omni_service._action('connect_watch',json.dumps({'chain_id':'eip155:1','address':'0x'+'2'*40,'label':'Public fixture'}))
        wallet=omni_wallet.snapshot(lab={});self.assertEqual(read.call_count,1);self.assertEqual(wallet['rows'][0]['quantity'],'5')
        self.assertIsNone(wallet['known_value_usd']);self.assertIn('ACCOUNT_READ_STARTED',[e['kind'] for e in wallet['events']])

    def test_wallet_market_link_uses_verified_canonical_binding(self):
        asset=assets.register_asset('eip155:1','erc20','0x'+'1'*40,'SAME','Fixture',18,metadata='RPC_METADATA')
        market_row=markets.parse_coins([{'id':'fixture-token','name':'Fixture','symbol':'SAME'}])[0];markets._save_rows([market_row])
        with markets._db(True) as db:db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(asset['id'],market_row['id'],'RPC_AND_PROVIDER_REFERENCE'))
        def response(url,**kwargs):
            if '/market_chart?' in url:return {'prices':[[int((time.time()-100)*1000),1],[int(time.time()*1000),2]]}
            return {'id':'fixture-token','platforms':{'ethereum':'0x'+'1'*40},'market_data':{'current_price':{'usd':2}}}
        with patch.object(omni_rpc,'_json',side_effect=response):markets.action('open_asset',json.dumps({'asset_id':asset['id']}))
        selected=markets.snapshot()['selected'];self.assertEqual(selected['asset_id'],asset['id']);self.assertEqual(selected['chain_id'],'eip155:1')
        self.assertEqual(selected['reference'],asset['reference']);self.assertTrue(selected['registered'])

    def test_unknown_token_decimals_are_never_valued_as_whole_tokens(self):
        from backend import omni_wallet
        asset=assets.register_asset('eip155:1','erc20','0x'+'3'*40,'RAW','Unknown decimals',0,metadata='DECIMALS_UNKNOWN')
        account=assets.account('eip155:1','0x'+'2'*40)
        quote=markets.parse_coins([{'id':'raw','name':'Raw','symbol':'RAW','current_price':2}])[0];markets._save_rows([quote])
        observation={'asset_id':asset['id'],'account_id':account,'quantity':'1000 basenheter','atomic':'1000','observed_at':time.time(),'state':'VERIFIED_READ'}
        with markets._db(True) as db:
            db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(asset['id'],quote['id'],'RPC_AND_PROVIDER_REFERENCE'))
            db.execute('INSERT INTO observations VALUES(?,?,?)',(asset['id'],account,assets.pack(observation)))
        result=omni_wallet.snapshot(lab={});row=next(r for r in result['rows'] if r['asset_id']==asset['id'])
        self.assertIsNone(row['value_usd']);self.assertEqual(row['quantity'],'1000 basenheter');self.assertIsNone(result['known_value_usd'])

if __name__=='__main__':unittest.main()
