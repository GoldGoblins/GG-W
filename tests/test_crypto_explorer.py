"""Offline market identity, data failure, Bitcoin and multi-wallet invariants."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from backend import crypto_explorer as market,omni_assets as assets,omni_rpc,omni_wallet,omni_lab

SOL=market.SOL


def coin(identifier='bitcoin',price=100):
    return {'id':identifier,'name':identifier.title(),'symbol':'SAME','market_cap_rank':1,'current_price':price,'market_cap':1000000,'total_volume':1000,'price_change_percentage_24h':-2}


def pair(chain='ethereum',address=None,price='2',liquidity=10000,pool='pool-1'):
    return {'chainId':chain,'dexId':'fixture','pairAddress':pool,'baseToken':{'address':address or '0x'+'1'*40,'symbol':'SAME','name':'Fixture'},
            'quoteToken':{'address':'0x'+'2'*40,'symbol':'USDT'},'priceUsd':price,'liquidity':{'usd':liquidity},'volume':{'h24':200},'priceChange':{'h24':3}}


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=patch.object(assets,'ROOT',Path(self.tmp.name));self.root.start();assets.bootstrap()
        self.rates=patch.object(market,'_last_request',{});self.rates.start()
        self.sleep=patch.object(market.time,'sleep');self.sleep.start()
    def tearDown(self):self.sleep.stop();self.rates.stop();self.root.stop();self.tmp.cleanup()

    def test_week_sparklines_keep_extrema_and_do_not_fetch_per_row(self):
        prices=[100+i/10 for i in range(512)];prices[101]=100000;prices[220]=1
        history=market.sparkline({'price':prices})
        self.assertLessEqual(len(history),128);self.assertEqual((history[0],history[-1]),(prices[0],prices[-1]))
        self.assertIn(100000,history);self.assertIn(1,history)
        for bad in ([1,float('nan')],[1,True],[1,None],[1,-2],[1]*513):self.assertEqual(market.sparkline({'price':bad}),[])
        row=dict(coin(),sparkline_in_7d={'price':prices})
        with patch.object(omni_rpc,'_json',return_value=[row]) as fetch:
            market.refresh();snapshot=market.snapshot()
        self.assertEqual(fetch.call_count,1);self.assertIn('sparkline=true',fetch.call_args.args[0])
        self.assertEqual(snapshot['rows'][0]['sparkline']['period'],'7D');self.assertEqual(snapshot['rows'][0]['sparkline']['prices'],history)

    def test_coins_not_bound_by_symbol_and_missing_price_is_not_zero(self):
        rows=market.parse_coins([coin(),coin('other-coin',True),coin('solana',float('nan'))])
        self.assertNotEqual(rows[0]['id'],rows[1]['id']);self.assertTrue(rows[0]['asset_id'].endswith('native:BTC'))
        self.assertEqual(rows[1]['asset_id'],'');self.assertIsNone(rows[1]['price_usd']);self.assertIsNone(rows[2]['price_usd'])

    def test_same_ticker_different_chain_and_pool_price_provenance(self):
        values=[pair(),pair('bsc',price='4'),pair(price='3',liquidity=20000,pool='pool-2'),pair()]
        rows=market.parse_pairs({'pairs':values});self.assertEqual(len(rows),2)
        eth=next(r for r in rows if r['chain_id']=='eip155:1');bsc=next(r for r in rows if r['chain_id']=='eip155:56')
        self.assertNotEqual(eth['asset_id'],bsc['asset_id']);self.assertEqual(eth['price_usd'],3)
        self.assertEqual(len(eth['pools']),2);self.assertEqual(eth['liquidity_usd'],20000)
        self.assertEqual(eth['valuation'],'SINGLE_POOL_ESTIMATE')

    def test_quote_token_price_is_never_misrepresented_as_requested_base(self):
        rows=market.parse_pairs([pair()]);market._save_rows(rows)
        source=rows[0];source.update(reference='0x'+'2'*40,id='dex:ethereum:quote-only');market._save_rows([source])
        with patch.object(omni_rpc,'_json',return_value=[pair()]):selected=market.select(source['id'])
        self.assertEqual(selected['pools'],[]);self.assertIn('INGA_POOLER',selected['quote_note'])
        self.assertIsNone(selected['price_usd'])

    def test_dex_selection_never_binds_a_same_address_quote_from_another_chain(self):
        asset=assets.register_asset('eip155:1','erc20','0x'+'1'*40,'FIX','Fixture',18,metadata='RPC_METADATA')
        account=assets.account('eip155:1','0x'+'2'*40,'Fixture')
        original=market.parse_pairs([pair(price='2')])[0];market._save_rows([original])
        observation={'asset_id':asset['id'],'account_id':account,'atomic':str(10**18),'quantity':'1','state':'VERIFIED_READ','observed_at':time.time()}
        with market._db(True) as db:
            db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(asset['id'],original['id'],'RPC_AND_PROVIDER_REFERENCE'))
            db.execute('INSERT INTO observations VALUES(?,?,?)',(asset['id'],account,assets.pack(observation)))
        with patch.object(omni_rpc,'_json',return_value=[pair('bsc',price='999'),pair(price='3')]):selected=market.select(original['id'])
        self.assertEqual(selected['chain_id'],'eip155:1');self.assertEqual(selected['asset_id'],asset['id'])
        self.assertEqual(omni_wallet.snapshot(lab={})['known_value_usd'],'3.00')
        with market._db(True) as db:db.execute('DELETE FROM explorer_cache')
        with patch.object(omni_rpc,'_json',return_value=[pair('bsc',price='999')]):selected=market.select(original['id'])
        self.assertEqual(selected['chain_id'],'eip155:1');self.assertEqual(selected['asset_id'],asset['id'])
        self.assertIsNone(selected['price_usd']);self.assertIsNone(omni_wallet.snapshot(lab={})['known_value_usd'])

    def test_refresh_failure_keeps_last_good_data_and_source_age(self):
        url='https://example.invalid/public';key='cg-markets-7d:1'
        with patch.object(omni_rpc,'_json',return_value=[coin()]):market._resource('coingecko',key,url,market.parse_coins)
        saved=market._cache_get(key);past=time.time()-200
        with market._db(True) as db:db.execute('UPDATE explorer_cache SET ts=?,attempt=? WHERE key=?',(past,past,key))
        with patch.object(omni_rpc,'_json',side_effect=OSError('offline')),self.assertRaises(ValueError):market._resource('coingecko',key,url,market.parse_coins)
        failed=market._cache_get(key);self.assertEqual(failed['body'],saved['body']);self.assertEqual(failed['ts'],past)
        snapshot=market.snapshot();self.assertEqual(snapshot['sources'][0]['state'],'STALE');self.assertEqual(snapshot['rows'][0]['price_usd'],100)

    def test_no_duplicate_fetch_within_cache_and_pause_is_absolute(self):
        with patch.object(omni_rpc,'_json',return_value=[coin()]) as request:
            market.refresh();market.refresh();self.assertEqual(request.call_count,1)
            market.configure({'paused':True});market.refresh(force=True);self.assertEqual(request.call_count,1)

    def test_corrupt_or_future_cache_recovers_without_reseeding_wallet(self):
        key='cg-markets-7d:1'
        with patch.object(omni_rpc,'_json',return_value=[coin()]):market.refresh()
        with market._db(True) as db:db.execute('UPDATE explorer_cache SET body=? WHERE key=?',('{bad',key))
        self.assertEqual(market.snapshot()['sources'][0]['state'],'FAILED')
        with patch.object(omni_rpc,'_json',return_value=[coin(price=22)]):market.refresh()
        self.assertEqual(market.snapshot()['rows'][0]['price_usd'],22)
        with market._db(True) as db:db.execute('UPDATE explorer_cache SET ts=?,attempt=? WHERE key=?',(time.time()+36000,time.time()+36000,key))
        self.assertEqual(market.snapshot()['sources'][0]['state'],'STALE')
        with patch.object(omni_rpc,'_json',return_value=[coin(price=33)]):market.refresh()
        self.assertEqual(market.snapshot()['rows'][0]['price_usd'],33)

    def test_native_filter_uses_provider_ids_not_fixed_symbols(self):
        def response(url,**kwargs):
            if '/coins/list?' in url:return [{'id':'bitcoin','platforms':{}},{'id':'another-native-chain','platforms':{}},{'id':'token-on-chain','platforms':{'ethereum':'0x'+'1'*40}}]
            return [coin(),coin('another-native-chain'),coin('token-on-chain')]
        market.configure({'view':'native'})
        with patch.object(omni_rpc,'_json',side_effect=response):market.refresh()
        ids={r['provider_id'] for r in market.snapshot()['rows']}
        self.assertEqual(ids,{'bitcoin','another-native-chain'})

    def test_query_rejects_accidental_key_material_before_network_or_storage(self):
        for value in ('a'*64,'0x'+'a'*64,'one two three four five six seven eight nine ten eleven twelve','password=do-not-send'):
            with patch.object(omni_rpc,'_json') as request,self.assertRaises(ValueError):market.action('search',json.dumps({'query':value}))
            request.assert_not_called();self.assertIsNone(market.pref('query'))
        self.assertEqual(market.public_query('0x'+'1'*40),'0x'+'1'*40)

    def test_case_sensitive_address_queries_do_not_share_cache(self):
        with patch.object(omni_rpc,'_json',return_value={'coins':[],'pairs':[]}) as request:
            market.action('search',json.dumps({'query':'AbCdAddress'}));market.action('search',json.dumps({'query':'aBcDAddress'}))
            self.assertEqual(request.call_count,4)
        self.assertIsNotNone(market._cache_get('dex-search:AbCdAddress'));self.assertIsNotNone(market._cache_get('dex-search:aBcDAddress'))

    def test_search_without_market_data_does_not_erase_an_existing_wallet_quote(self):
        account=assets.account('eip155:1','0x'+'2'*40,'Fixture')
        asset_id='eip155:1/native:ETH';observed=time.time()-60
        original=market.parse_coins([coin('ethereum',20)])[0];original['observed_at']=observed
        market._save_rows([original])
        observation={'asset_id':asset_id,'account_id':account,'atomic':str(10**18),'quantity':'1','state':'VERIFIED_READ','observed_at':time.time()}
        with assets.db(True) as db:db.execute('INSERT INTO observations VALUES(?,?,?)',(asset_id,account,assets.pack(observation)))
        def response(url,**kwargs):return {'pairs':[]} if 'dexscreener' in url else {'coins':[coin('ethereum')]}
        with patch.object(omni_rpc,'_json',side_effect=response):market.action('search',json.dumps({'query':'ethereum'}))
        self.assertEqual(market.row('coingecko:ethereum')['price_usd'],20)
        self.assertEqual(market.row('coingecko:ethereum')['observed_at'],observed)
        self.assertEqual(omni_wallet.snapshot(lab={})['known_value_usd'],'20.00')
        search_coin=next(r for r in market.snapshot()['rows'] if r['provider']=='coingecko')
        self.assertIsNone(search_coin['price_usd'])
        stale=dict(original,observed_at=time.time()-600);market._save_rows([stale])
        with patch.object(omni_rpc,'_json') as request:market.refresh()
        request.assert_not_called()
        self.assertEqual(market.row('coingecko:ethereum')['observed_at'],stale['observed_at'])
        self.assertIsNone(omni_wallet.snapshot(lab={})['known_value_usd'])
        # An actual markets response with no price must still clear the quote.
        market._save_rows(market.parse_coins([coin('ethereum',None)]))
        self.assertIsNone(market.row('coingecko:ethereum')['price_usd'])
        wallet=omni_wallet.snapshot(lab={});self.assertIsNone(wallet['known_value_usd'])
        self.assertEqual(wallet['rows'][0]['price_state'],'STALE_OR_MISSING')

    def test_watchlist_toggle_and_registered_selection_stay_consistent(self):
        rows=market.parse_coins([coin()]);market._save_rows(rows);market.star(rows[0]['id'],True);market.pref('selected',rows[0]['id'])
        self.assertTrue(market.snapshot()['selected']['starred']);market.star(rows[0]['id'],False)
        self.assertFalse(market.snapshot()['selected']['starred'])
        market.action('select',json.dumps({'id':'registered:eip155:1/native:ETH'}))
        selected=market.snapshot()['selected'];self.assertEqual(selected['symbol'],'ETH');self.assertTrue(selected['registered'])

    def test_token_import_requires_provider_reference_and_rpc_metadata(self):
        row=market.parse_pairs([pair()])[0];market._save_rows([row])
        with patch.object(omni_rpc,'import_token') as importer,self.assertRaises(ValueError):market.add_asset(row['id'],'eip155:56',row['reference'])
        importer.assert_not_called()
        imported=assets.register_asset('eip155:1','erc20',row['reference'],'REAL','RPC token',18,metadata='RPC_METADATA')
        with patch.object(omni_rpc,'import_token',return_value=imported):market.add_asset(row['id'],'eip155:1',row['reference'])
        self.assertEqual(assets.preference('selected_asset'),imported['id'])

    def test_chart_rejects_conflicting_and_future_points(self):
        rows=market.parse_coins([coin()]);market._save_rows(rows)
        now=time.time()*1000
        with patch.object(omni_rpc,'_json',return_value={'prices':[[now-1000,10],[now-1000,20]]}),self.assertRaises(ValueError):market.chart(rows[0]['id'])
        with market._db(True) as db:db.execute('DELETE FROM explorer_cache')
        with patch.object(omni_rpc,'_json',return_value={'prices':[[now-1000,10],[now,20]]}):market.chart(rows[0]['id'])
        self.assertEqual(market.snapshot()['selected']['chart']['prices'],[10,20])

    def test_wallet_exact_balances_and_no_cross_symbol_valuation(self):
        account=assets.account('eip155:1','0x'+'2'*40,'Fixture')
        token=assets.register_asset('eip155:1','erc20','0x'+'1'*40,'SAME','No quote',9)
        obs={'asset_id':token['id'],'account_id':account,'atomic':'18446744073709551615000000001','quantity':'18446744073709551615.000000001','state':'VERIFIED_READ','observed_at':time.time()}
        with assets.db(True) as db:db.execute('INSERT INTO observations VALUES(?,?,?)',(token['id'],account,assets.pack(obs)))
        market._save_rows(market.parse_coins([coin('ethereum',100)]))
        wallet=omni_wallet.snapshot(lab={});position=next(r for r in wallet['rows'] if r['asset_id']==token['id'])
        self.assertEqual(position['quantity'],obs['quantity']);self.assertIsNone(position['value_usd']);self.assertTrue(wallet['incomplete'])
        self.assertIsNone(wallet['known_value_usd'])

    def test_lab_wallet_is_separate_from_public_value(self):
        omni_lab.create();wallet=omni_wallet.snapshot()
        self.assertEqual(len(wallet['lab_rows']),4);self.assertTrue(all(r['scope']=='LOCAL_LAB' for r in wallet['lab_rows']))
        self.assertIsNone(wallet['known_value_usd'])

    def test_large_wallet_snapshot_is_bounded_and_reports_omitted_positions(self):
        chain='eip155:1';net=assets.network(chain)
        state={'assets':[{'id':str(i),'chain_id':chain,'symbol':'TEST','name':'Test','decimals':18} for i in range(64)],
            'accounts':[{'id':str(i),'chain_id':chain,'address':'0x'+'1'*40,'label':'Public fixture'} for i in range(64)],'networks':[net],'events':[]}
        wallet=omni_wallet.snapshot(state=state,lab={})
        self.assertEqual(len(wallet['rows']),2048);self.assertEqual(wallet['position_count'],4096)
        self.assertEqual(wallet['unpriced_count'],4096);self.assertTrue(wallet['truncated']);self.assertTrue(wallet['incomplete'])

    def test_independent_sender_transactions_can_share_a_precomputed_root(self):
        omni_lab.create();first=omni_lab.prepare(0,1,'1');second=omni_lab.prepare(2,3,'2')
        self.assertEqual(first['body']['account_root'],second['body']['account_root'])
        omni_lab.submit(first);omni_lab.submit(second)
        self.assertEqual(omni_lab.commit()['state'],'FINALIZED');self.assertEqual(omni_lab.commit()['state'],'FINALIZED')
        self.assertEqual(omni_lab.verify()['state'],'VERIFIED')
        with self.assertRaises(ValueError):omni_lab.submit(first)
        self.assertNotIn('_trusted_roots',omni_lab._load())

    def test_tampered_persisted_lab_is_never_signed(self):
        omni_lab.create();value=omni_lab._load();keys=list(value['balances'])
        value['balances'][keys[0]]-=1;value['balances'][keys[1]]+=1;omni_lab._save(value)
        with self.assertRaisesRegex(ValueError,'HISTORY_INVALID'):omni_lab.prepare()

    def test_expired_precomputed_root_cannot_reenter_the_validation_window(self):
        omni_lab.create();old=omni_lab.prepare(2,3,'1')
        for _ in range(64):
            omni_lab.submit(omni_lab.prepare(0,1,'1'));omni_lab.commit()
        with self.assertRaisesRegex(ValueError,'STALE_STATE_WITNESS'):omni_lab.submit(old)

    def test_nft_binding_is_independent_of_payment_chain_and_integrity_is_checked(self):
        from backend import marketplace_contract as mp
        with patch.object(mp,'STATE_DIR',Path(self.tmp.name)/'mp'):
            item=mp.list_item({'title':'Linked object','kind':'OBJECT','category':'ITEM','material':'UNKNOWN',
                'settlement_asset_id':'eip155:56/native:BNB','price':'1','nft_binding':{'chain_id':'eip155:1','standard':'erc721','collection':'0x'+'1'*40,'token_id':str(2**200)}})
            self.assertEqual(item['nft_binding']['chain_id'],'eip155:1');self.assertEqual(item['network'],'eip155:56')
            self.assertEqual(item['nft_binding']['verification'],'DECLARED_REFERENCE_NOT_OWNERSHIP_PROOF')
            self.assertEqual(mp.hash_identity(item),item['identity_sha256'])
            raw=json.loads(mp.catalog_path().read_text(encoding='utf-8'));raw['listings'][0]['origin']='Changed without receipt update'
            mp.catalog_path().write_text(json.dumps(raw),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'INTEGRITY'):mp.load_catalog()

    def test_marketplace_js_compares_atomic_prices_exactly_with_currency_filter(self):
        import subprocess,shutil
        node=shutil.which('node');self.assertIsNotNone(node)
        path=Path(__file__).resolve().parents[1]/'qml/components/MarketplaceBrowse.js'
        script="""const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),c={};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
const rows=[{id:'A',settlement_asset_id:'BNB',settlement:{price_atomic:'9007199254740993'},listed_at:3},{id:'B',settlement_asset_id:'BNB',settlement:{price_atomic:'9007199254740992'},listed_at:2},{id:'C',settlement_asset_id:'ETH',settlement:{price_atomic:'1'},listed_at:1}];
assert.deepEqual(Array.from(c.apply(rows,{sort:'price',currency:'BNB'}),r=>r.id),['B','A']);assert.deepEqual(Array.from(c.apply(rows,{sort:'price'}),r=>r.id),['A','B','C']);console.log('EXACT_CURRENCY_PRICE_SORT=PASS');"""
        script+="\nassert.equal(c.apply([{network:'eip155:56',nft_binding:{chain_id:'eip155:1'}}],{network:'eip155:1'}).length,1);assert.equal(c.apply([{network:'eip155:56',nft_binding:{chain_id:'eip155:1'}}],{network:'eip155:56'}).length,0);"
        result=subprocess.run([node,'-e',script,str(path)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_abandoned_transport_expires_and_does_not_pin_peer_slots(self):
        from backend.omni_transport import Receiver,fragment
        clock=[1000.0];receiver=Receiver(bytes_per_minute=65536,clock=lambda:clock[0]);packet=fragment(b'test',128,now=1000)[0]
        for i in range(32):receiver.receive('p-'+str(i),packet)
        clock[0]+=121;receiver.prune();self.assertEqual(receiver.snapshot()['peers'],0)
        self.assertEqual(receiver.snapshot()['received_bytes'],len(packet)*32)
        omni_lab.create();omni_lab.configure({'participating':True});omni_lab.transport_test(loss=True)
        self.assertEqual(omni_lab.snapshot()['retry_packets'],1)
        omni_lab.cancel_transport();self.assertEqual(omni_lab.snapshot()['retry_packets'],0)
        self.assertEqual(omni_lab.snapshot()['transport']['queued'],0)

    def test_bitcoin_standard_vectors_and_read_only_confirmed_balance(self):
        from backend.bitcoin_address import validate
        valid=['1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa','BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4','bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0']
        for address in valid:self.assertEqual(validate(address),address.lower() if address.lower().startswith('bc1') else address)
        for invalid in ['bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqh2y7hd','bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kemeawh','1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb']:
            with self.assertRaises(ValueError):validate(invalid)
        chain='bip122:000000000019d6689c085ae165831e93';account=assets.account(chain,valid[0]);data={'address':valid[0],'chain_stats':{'funded_txo_sum':150000000,'spent_txo_sum':50000000},'mempool_stats':{'funded_txo_sum':0,'spent_txo_sum':100}}
        with patch.object(omni_rpc,'_text',return_value='000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f'),patch.object(omni_rpc,'_json',return_value=data):result=omni_rpc.balance(chain+'/native:BTC',account)
        self.assertEqual(result['quantity'],'1');self.assertEqual(result['pending_atomic'],'-100');self.assertEqual(result['balance_scope'],'CONFIRMED')


if __name__=='__main__':unittest.main()
