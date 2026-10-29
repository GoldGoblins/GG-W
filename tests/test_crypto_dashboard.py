"""Account dashboard totals, bounded refresh and canonical quote identity."""
import json
from collections import OrderedDict
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from backend import omni_assets as store,omni_wallet,omni_rpc,omni_service,omni_discovery,crypto_explorer as market
from backend import token_market_prices as token_prices
from tests.test_crypto_explorer import coin,pair


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=patch.object(store,'ROOT',Path(self.temp.name));self.root.start();store.bootstrap()
        self.rates=patch.object(market,'PROVIDERS',{k:dict(v,spacing=0) for k,v in market.PROVIDERS.items()});self.rates.start()
        self.token_cache=patch.object(token_prices,'_cache',OrderedDict());self.token_cache.start()
        self.token_rates=patch.object(token_prices,'_provider_next',{});self.token_rates.start()

    def tearDown(self):
        self.token_rates.stop();self.token_cache.stop();self.rates.stop();self.root.stop();self.temp.cleanup()

    def account(self,chain='eip155:1',digit='2'):
        return store.account(chain,'0x'+digit*40,'Test account')

    def observation(self,account,asset='eip155:1/native:ETH',quantity=1,state='VERIFIED_READ',age=0):
        row={'asset_id':asset,'account_id':account,'atomic':str(quantity*10**18),'quantity':str(quantity),'state':state,'observed_at':time.time()-age}
        with market._db(True) as db:db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset,account,store.pack(row)))

    def test_scoped_totals_do_not_merge_equal_tickers_or_change_with_ui_search(self):
        first=self.account();second=self.account(digit='3');base=self.account('eip155:8453','4')
        market._save_rows(market.parse_coins([coin('ethereum',20)]))
        self.observation(first);self.observation(second,quantity=2)
        self.observation(base,'eip155:8453/native:ETH',3)
        with patch.object(omni_rpc,'_json') as request:wallet=omni_wallet.snapshot(lab={})
        request.assert_not_called()
        self.assertEqual(wallet['summary']['known_value_usd'],'60.00')
        self.assertEqual(wallet['account_summaries'][first]['known_value_usd'],'20.00')
        self.assertEqual(wallet['account_summaries'][second]['known_value_usd'],'40.00')
        self.assertIsNone(wallet['account_summaries'][base]['known_value_usd'])
        self.assertEqual(wallet['network_summaries']['eip155:1']['known_value_usd'],'60.00')
        self.assertEqual(wallet['summary']['network_count'],2)
        self.assertEqual(wallet['summary']['nonzero_count'],3)
        self.assertEqual(wallet['summary']['unpriced_count'],1)

    def test_failed_stale_unread_and_zero_are_distinct(self):
        account=self.account();market._save_rows(market.parse_coins([coin('ethereum',20)]))
        summary=omni_wallet.snapshot(lab={})['summary']
        self.assertEqual(summary['unread_count'],1);self.assertIsNone(summary['known_value_usd'])
        self.observation(account,quantity=0)
        summary=omni_wallet.snapshot(lab={})['summary']
        self.assertEqual(summary['known_value_usd'],'0.00');self.assertEqual(summary['zero_count'],1)
        self.observation(account,quantity=2,age=600)
        summary=omni_wallet.snapshot(lab={})['summary']
        self.assertIsNone(summary['known_value_usd']);self.assertEqual(summary['stale_count'],1)
        self.observation(account,quantity=2,state='READ_FAILED')
        summary=omni_wallet.snapshot(lab={})['summary']
        self.assertIsNone(summary['known_value_usd']);self.assertEqual(summary['failed_count'],1)

    def test_refresh_reads_only_the_requested_accounts_then_quotes(self):
        first=self.account();second=self.account(digit='3')
        def read(asset,account):
            self.assertEqual(account,first)
            return {'asset_id':asset,'account_id':account,'atomic':str(2*10**18),'quantity':'2','state':'VERIFIED_READ','identity_level':'TEST_SOURCE'}
        with patch.object(omni_rpc,'balance',side_effect=read) as balance,patch.object(market,'refresh_wallet_quotes') as quotes:
            omni_service._action('refresh_wallet',json.dumps({'account_ids':[first]}))
        self.assertEqual(balance.call_count,1);quotes.assert_called_once_with(['eip155:1/native:ETH'])
        wallet=omni_wallet.snapshot(lab={})
        self.assertEqual(wallet['account_summaries'][second]['unread_count'],1)
        self.assertIn('OVERVIEW_READ_COMPLETED',[e['kind'] for e in wallet['events']])

    def test_refresh_validates_all_accounts_and_request_budget_before_rpc(self):
        self.account()
        with patch.object(omni_rpc,'balance') as balance:
            with self.assertRaisesRegex(ValueError,'ACCOUNT_NOT_FOUND'):omni_wallet.refresh_wallet(['missing'])
            for i in range(64):store.register_asset('eip155:1','erc20','0x'+format(i+1,'040x'),'TEST','Test',18,metadata='RPC_METADATA')
            with self.assertRaisesRegex(ValueError,'REFRESH_LIMIT'):omni_wallet.refresh_wallet()
        balance.assert_not_called()

    def test_quote_refresh_uses_provider_ids_and_preserves_explorer_navigation(self):
        account=self.account();self.observation(account)
        market.configure({'view':'dex','query':'saved query','page':2,'paused':True});market.pref('selected','keep-selection')
        with patch.object(omni_rpc,'_json',return_value=[coin('ethereum',20)]) as request:
            market.refresh_wallet_quotes(['eip155:1/native:ETH'])
        self.assertIn('ids=ethereum',request.call_args.args[0]);self.assertNotIn('symbols=',request.call_args.args[0])
        self.assertEqual(market.pref('view'),'dex');self.assertEqual(market.pref('selected'),'keep-selection');self.assertTrue(market.pref('paused'))
        self.assertEqual(omni_wallet.snapshot(lab={})['known_value_usd'],'20.00')
        with patch.object(omni_rpc,'_json',return_value=[coin('wrong-identity',999)]):
            # A different finite asset set bypasses the existing valid cache.
            with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):market.refresh_wallet_quotes(['eip155:1/native:ETH','bip122:000000000019d6689c085ae165831e93/native:BTC'])

    def test_wallet_refresh_updates_bound_discovered_spl_quotes_and_keeps_navigation(self):
        chain=market.SOL;mint='So11111111111111111111111111111111111111112'
        account=store.account(chain,'11111111111111111111111111111111','Solana fixture')
        token=store.register_asset(chain,'token',mint,'FIX','Fixture token',6,metadata='RPC_METADATA')
        token_market=market.parse_pairs([pair('solana',mint,price='1')])[0]
        token_market['observed_at']=time.time()-600;market._save_rows([token_market])
        with market._db(True) as db:db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(token['id'],token_market['id'],'RPC_AND_PROVIDER_REFERENCE'))
        market.configure({'view':'dex','query':'keep query','page':2,'paused':True});market.pref('selected','keep-selection')
        def discover(account_id):
            self.assertEqual(account_id,account)
            observation={'asset_id':token['id'],'account_id':account,'atomic':'2000000','quantity':'2','state':'VERIFIED_READ','observed_at':time.time()}
            with market._db(True) as db:db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(token['id'],account,store.pack(observation)))
            return {'asset_ids':[token['id']]+['unbound:'+str(i) for i in range(100)]}
        def response(url,**kwargs):
            return [pair('solana',mint,price='3')] if 'dexscreener' in url else [coin('solana',100)]
        native={'asset_id':chain+'/native:SOL','account_id':account,'atomic':'1000000000','quantity':'1','state':'VERIFIED_READ','identity_level':'TEST_SOURCE'}
        with patch.object(omni_rpc,'balance',return_value=native),patch.object(omni_discovery,'discover',side_effect=discover),patch.object(omni_rpc,'_json',side_effect=response) as request,patch.object(token_prices,'_json',side_effect=lambda url,provider:response(url)) as token_request:
            omni_wallet.refresh_wallet([account])
        self.assertEqual(request.call_count+token_request.call_count,2)
        position=next(r for r in omni_wallet.snapshot(lab={})['rows'] if r['asset_id']==token['id'])
        self.assertEqual(position['value_usd'],'6.00');self.assertEqual(position['price_state'],'CURRENT')
        self.assertEqual(market.pref('view'),'dex');self.assertEqual(market.pref('query'),'keep query')
        self.assertEqual(market.pref('page'),2);self.assertEqual(market.pref('selected'),'keep-selection');self.assertTrue(market.pref('paused'))

    def test_wallet_refresh_quotes_previous_spl_positions_only_for_requested_accounts(self):
        from backend.crypto_keys import b58encode
        chain=market.SOL;first=store.account(chain,b58encode(b'\x01'*32),'First');second=store.account(chain,b58encode(b'\x02'*32),'Second')
        tokens=[]
        for index,account in enumerate((first,second),3):
            mint=b58encode(bytes([index])*32);token=store.register_asset(chain,'token',mint,'FIX','Fixture token',6,metadata='RPC_METADATA');tokens.append(token)
            token_market=market.parse_pairs([pair('solana',mint)])[0];market._save_rows([token_market])
            self.observation(account,token['id'],quantity=1)
            with market._db(True) as db:db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(token['id'],token_market['id'],'RPC_AND_PROVIDER_REFERENCE'))
        native={'asset_id':chain+'/native:SOL','account_id':first,'atomic':'0','quantity':'0','state':'VERIFIED_READ','identity_level':'TEST_SOURCE'}
        with patch.object(omni_rpc,'balance',return_value=native),patch.object(omni_discovery,'discover',return_value={'asset_ids':[]}) as discovery,patch.object(market,'refresh_wallet_quotes') as quotes:
            omni_wallet.refresh_wallet([first])
        discovery.assert_called_once_with(first)
        self.assertEqual(set(quotes.call_args.args[0]),{chain+'/native:SOL',tokens[0]['id']})
        self.assertNotIn(tokens[1]['id'],quotes.call_args.args[0])

    def test_spl_quote_budget_failure_is_partial_and_does_not_start_provider_reads(self):
        from backend.crypto_keys import b58encode
        chain=market.SOL;account=store.account(chain,b58encode(b'\x01'*32),'Solana fixture')
        for index in range(65):
            mint=b58encode(index.to_bytes(32,'big'));token=store.register_asset(chain,'token',mint,'FIX','Fixture token',6,metadata='RPC_METADATA')
            self.observation(account,token['id'],quantity=1)
            with market._db(True) as db:db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(token['id'],'coingecko:fixture-'+str(index),'RPC_AND_PROVIDER_REFERENCE'))
        native={'asset_id':chain+'/native:SOL','account_id':account,'atomic':'0','quantity':'0','state':'VERIFIED_READ','identity_level':'TEST_SOURCE'}
        with patch.object(omni_rpc,'balance',return_value=native),patch.object(omni_discovery,'discover',return_value={'asset_ids':[]}),patch.object(omni_rpc,'_json') as request:
            with self.assertRaisesRegex(ValueError,'OMNI_WALLET_REFRESH_PARTIAL'):omni_wallet.refresh_wallet([account])
        request.assert_not_called()
        self.assertIn('OVERVIEW_READ_PARTIAL',[e['kind'] for e in store.events()])


if __name__=='__main__':unittest.main()
