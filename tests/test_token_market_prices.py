"""Address-qualified price fixtures, finite HTTP budgets and explicit refresh."""
from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from backend import token_market_prices as prices,crypto_explorer as market,omni_assets as store,omni_wallet,omni_rpc
from backend import crypto_pump_accounts as pump
from tests.test_crypto_pump_accounts import account,fields,mint
from tests.test_crypto_explorer import coin,pair

ETH='eip155:1';ADDRESS='0x'+'1'*40


class PriceParserTests(unittest.TestCase):
    def test_fetching_old_or_future_provider_timestamp_does_not_make_it_fresh(self):
        row={'price_usd':'2','observed_at':time.time(),'updated_at':'2020-01-01T00:00:00Z'}
        self.assertFalse(prices.fresh(row))
        self.assertFalse(prices.fresh(dict(row,updated_at='2099-01-01T00:00:00Z')))
        self.assertTrue(prices.fresh(dict(row,updated_at='')))
    def test_exact_chain_base_identity_and_deepest_pool_ignore_illiquid_outlier(self):
        raw=[pair(price='99999',liquidity=2,pool='tiny'),pair(price='2.125',liquidity=50000,pool='deep'),
             pair('bsc',price='8888',liquidity=90000,pool='wrong-chain'),
             dict(pair(price='3'),baseToken={'address':'0x'+'2'*40})]
        quoted=prices.parse_dex(raw,ETH,[ADDRESS],now=100)
        result=quoted[(ETH,ADDRESS)]
        self.assertEqual(result['price_usd'],'2.125');self.assertEqual(result['pool_ref'],'deep')
        self.assertEqual(result['source'],'DEX Screener');self.assertEqual(result['observed_at'],100)
        self.assertEqual(result['quality'],'DEX_POOL_SPOT')
        self.assertEqual(result['identity'],'EXACT_CHAIN_AND_ADDRESS')
        self.assertIsNone(result['source_timestamp'])
        quote_only=dict(pair(),baseToken={'address':'0x'+'2'*40},quoteToken={'address':ADDRESS})
        self.assertEqual(prices.parse_dex([quote_only],ETH,[ADDRESS]),{})

    def test_finite_positive_quote_unknown_liquidity_and_low_liquidity_remain_distinct(self):
        for value in (None,True,'NaN','Infinity','-1','0','1e101','1e-999999999'):
            self.assertEqual(prices.parse_dex([pair(price=value)],ETH,[ADDRESS]),{},value)
        for liquidity in (-1,float('nan'),True):
            self.assertEqual(prices.parse_dex([pair(liquidity=liquidity)],ETH,[ADDRESS]),{})
        for liquidity,quality in ((0,'UNKNOWN_LIQUIDITY'),(None,'UNKNOWN_LIQUIDITY'),(12,'LOW_LIQUIDITY')):
            result=prices.parse_dex([pair(price='.000000012',liquidity=liquidity)],ETH,[ADDRESS])[(ETH,ADDRESS)]
            self.assertEqual(result['quality'],quality);self.assertEqual(result['price_usd'],'0.000000012')

    def test_gecko_network_record_address_and_liquidity_are_validated(self):
        token={'id':'eth_'+ADDRESS,'type':'token','attributes':{'address':ADDRESS,'price_usd':'2.5','total_reserve_in_usd':'10000'}}
        result=prices.parse_gecko({'data':[token]},ETH,[ADDRESS],now=100)[(ETH,ADDRESS)]
        self.assertEqual(result['source'],'GeckoTerminal');self.assertEqual(result['price_usd'],'2.5')
        for mutation in ({'id':'bsc_'+ADDRESS},{'type':'pool'},{'attributes':dict(token['attributes'],address='0x'+'2'*40)},
                         {'attributes':dict(token['attributes'],price_usd='NaN')}):
            self.assertEqual(prices.parse_gecko({'data':[dict(token,**mutation)]},ETH,[ADDRESS]),{})
        solana={'id':'solana_'+pump.USDC_MINT.lower(),'type':'token','attributes':{'address':pump.USDC_MINT,'price_usd':'1'}}
        self.assertEqual(prices.parse_gecko({'data':[solana]},prices.SOL,[pump.USDC_MINT]),{})


class PriceCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache=patch.object(prices,'_cache',OrderedDict());self.cache.start()
        self.budget=patch.object(prices,'_provider_next',{});self.budget.start()
        self.curves=patch.object(prices,'_pump_curves',return_value={});self.curves.start()
    def tearDown(self):self.curves.stop();self.budget.stop();self.cache.stop()

    def test_same_address_on_two_chains_never_shares_quote_and_panels_reuse_ttl(self):
        def fetch(url,provider):
            if '/ethereum/' in url:return [pair(price='2')]
            if '/bsc/' in url:return [pair('bsc',price='5')]
            self.fail(url)
        with patch.object(prices,'_json',side_effect=fetch) as requests:
            result=prices.quotes([(ETH,ADDRESS),('eip155:56',ADDRESS)])
            again=prices.quote(ETH,ADDRESS)
        self.assertEqual(requests.call_count,2);self.assertEqual(again['price_usd'],'2')
        self.assertEqual(result[('eip155:56',ADDRESS)]['price_usd'],'5')
        self.assertEqual(again['observed_at'],result[(ETH,ADDRESS)]['observed_at'])

    def test_batch30_and_finite_lru_are_not_global_catalogue_fetches(self):
        targets=[(ETH,'0x'+format(i+1,'040x')) for i in range(64)]
        def fetch(url,provider):
            self.assertIn('/tokens/v1/ethereum/',url);addresses=url.rsplit('/',1)[1].split(',')
            self.assertLessEqual(len(addresses),30)
            return [pair(address=a,price='2') for a in addresses]
        with patch.object(prices,'_json',side_effect=fetch) as requests:
            result=prices.quotes(targets)
        self.assertEqual(len(result),64);self.assertEqual(requests.call_count,3)
        with patch.object(prices,'_json') as request:
            with self.assertRaisesRegex(ValueError,'TOKEN_LIMIT'):prices.quotes(targets+[(ETH,'0x'+'f'*40)])
            request.assert_not_called()
        self.assertLessEqual(len(prices._cache),prices.MAX_CACHE)

    def test_429_backoff_preserves_last_good_price_and_original_asof(self):
        now=[1000.0]
        with patch.object(prices.time,'time',side_effect=lambda:now[0]),patch.object(prices.time,'monotonic',side_effect=lambda:now[0]),\
             patch.object(prices,'_json',return_value=[pair(price='3')]):
            original=prices.quote(ETH,ADDRESS)
        now[0]=1061
        def fail(url,provider):raise prices.ProviderUnavailable('TOKEN_PRICE_HTTP_429',429,120)
        with patch.object(prices.time,'time',side_effect=lambda:now[0]),patch.object(prices.time,'monotonic',side_effect=lambda:now[0]),\
             patch.object(prices,'_json',side_effect=fail) as requests:
            retained=prices.quote(ETH,ADDRESS);first_calls=requests.call_count
            again=prices.quote(ETH,ADDRESS)
            self.assertEqual(requests.call_count,first_calls)
            self.assertGreaterEqual(prices._provider_next['dexscreener'],1181)
        self.assertEqual(retained['price_usd'],'3');self.assertEqual(retained['observed_at'],original['observed_at'])
        self.assertEqual(retained['state'],'LAST_GOOD');self.assertEqual(again['observed_at'],1000)

    def test_stale_valid_value_is_not_reset_to_fresh_or_zero_after_invalid_response(self):
        prices._cache[(ETH,ADDRESS)]={'attempt':0,'quote':dict(prices._empty((ETH,ADDRESS)),price_usd='2',observed_at=time.time()-600,state='CURRENT')}
        with patch.object(prices,'_json',return_value=[]):result=prices.quote(ETH,ADDRESS)
        self.assertEqual(result['state'],'STALE');self.assertEqual(result['price_usd'],'2')
        self.assertLess(result['observed_at'],time.time()-500)

    def test_unsupported_network_is_explicit_and_never_requests_another_chain(self):
        with patch.object(prices,'_json') as request:
            result=prices.quote('kaspa:mainnet','GGTEST')
        request.assert_not_called();self.assertIsNone(result['price_usd'])
        self.assertEqual(result['reason'],'NETWORK_ADAPTER_UNAVAILABLE')


class TransportGuards(unittest.TestCase):
    def transport(self,raw,status=200,retry=''):
        class Reply:
            def __init__(self):self.limit=None
            def getheader(self,name,default=''):return retry if name=='Retry-After' else default
            def read(self,limit):self.limit=limit;return raw
        reply=Reply();reply.status=status
        class Connection:
            def __init__(self):self.calls=[];self.closed=False
            def request(self,*args,**kwargs):self.calls.append((args,kwargs))
            def getresponse(self):return reply
            def close(self):self.closed=True
        return Connection(),reply
    def test_tls_fixed_host_public_dns_accept_version_size_and_get_only(self):
        connection,reply=self.transport(b'{"data":[]}')
        with patch.object(prices.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),\
             patch.object(prices.http.client,'HTTPSConnection',return_value=connection):
            self.assertEqual(prices._json('https://api.geckoterminal.com/api/v2/networks/eth/tokens/multi/'+ADDRESS,'geckoterminal'),{'data':[]})
        self.assertEqual(connection.calls[0][0][0],'GET')
        self.assertEqual(connection.calls[0][1]['headers']['Accept'],'application/json;version=20230203')
        self.assertEqual(reply.limit,prices.MAX_BODY+1);self.assertTrue(connection.closed)
        with patch.object(prices.http.client,'HTTPSConnection') as create:
            with self.assertRaises(ValueError):prices._json('http://api.dexscreener.com/','dexscreener')
            with self.assertRaises(ValueError):prices._json('https://127.0.0.1/','dexscreener')
            with patch.object(prices.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
                with self.assertRaises(ValueError):prices._json('https://api.dexscreener.com/tokens/v1/ethereum/'+ADDRESS,'dexscreener')
            create.assert_not_called()
    def test_redirect_429_duplicate_json_nonfinite_and_oversize_fail_closed(self):
        for raw,status in ((b'{}',301),(b'{}',429),(b'{"x":1,"x":2}',200),(b'{"x":NaN}',200),(b'x'*(prices.MAX_BODY+1),200)):
            connection,reply=self.transport(raw,status,retry='120')
            with patch.object(prices.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),\
                 patch.object(prices.http.client,'HTTPSConnection',return_value=connection):
                with self.assertRaises(ValueError) as error:prices._json('https://api.dexscreener.com/tokens/v1/ethereum/'+ADDRESS,'dexscreener')
            self.assertTrue(connection.closed);self.assertEqual(len(connection.calls),1)
            if status==429:self.assertEqual(error.exception.retry_after,120)


class PumpCurvePriceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(store,'ROOT',Path(self.temp.name));self.root.start();store.bootstrap()
        self.mint=pump.b58encode(b'\x11'*32)
        self.values={'virtual_token_reserves':10**15,'virtual_quote_reserves':30*10**9,
                     'real_token_reserves':8*10**14,'real_quote_reserves':2*10**9,'token_total_supply':10**15}
    def tearDown(self):self.root.stop();self.temp.cleanup()
    def rpc(self,mutate=None):
        raw=pump._DISCRIMINATORS['BondingCurve']+fields(pump._CURVE_FIELDS,self.values)
        quote_mint=bytearray(mint());quote_mint[44]=9
        data=[account(mint(),pump.TOKEN_PROGRAM),account(raw,lamports=3*10**9),account(bytes(quote_mint),pump.TOKEN_PROGRAM)]
        if mutate:mutate(data)
        return {'context':{'slot':12345},'value':data}
    def test_exact_rpc_curve_supply_mint_decimals_and_sol_usd_source(self):
        anchors={(prices.SOL,pump.WSOL_MINT):{'price_usd':'200','source':'CoinGecko','observed_at':time.time()-10}}
        with patch.object(omni_rpc,'_sol_identity') as verify,patch.object(omni_rpc,'rpc',return_value=self.rpc()) as rpc:
            value=prices._pump_curves([(prices.SOL,self.mint)],anchors,[4])[(prices.SOL,self.mint)]
        verify.assert_called_once();self.assertEqual(rpc.call_count,1)
        requested=rpc.call_args.args[2][0]
        self.assertEqual(requested,[self.mint,pump.derive_curve(self.mint),pump.WSOL_MINT])
        self.assertEqual(Decimal(value['price_usd']),Decimal('.000006'))
        self.assertEqual(value['quality'],'BONDING_CURVE_SPOT')
        self.assertEqual(value['price_basis'],'VIRTUAL_RESERVE_SPOT_NOT_EXECUTABLE')
        self.assertEqual(value['slot'],12345);self.assertIsNone(value['liquidity_usd'])
        self.assertEqual(value['observed_at'],anchors[(prices.SOL,pump.WSOL_MINT)]['observed_at'])

    def test_completed_wrong_owner_supply_and_unsupported_quote_do_not_invent_usd(self):
        anchors={(prices.SOL,pump.WSOL_MINT):{'price_usd':'200','source':'CoinGecko','observed_at':time.time()}}
        for key,value in [('complete',1),('depth',1),('token_total_supply',20),('quote_mint',self.mint)]:
            old=dict(self.values);self.values[key]=value
            with patch.object(omni_rpc,'_sol_identity'),patch.object(omni_rpc,'rpc',return_value=self.rpc()):
                self.assertEqual(prices._pump_curves([(prices.SOL,self.mint)],anchors,[4]),{})
            self.values=old
        def wrong_owner(values):values[1]['owner']=pump.TOKEN_PROGRAM
        with patch.object(omni_rpc,'_sol_identity'),patch.object(omni_rpc,'rpc',return_value=self.rpc(wrong_owner)):
            self.assertEqual(prices._pump_curves([(prices.SOL,self.mint)],anchors,[4]),{})
        with patch.object(omni_rpc,'rpc') as request:
            self.assertEqual(prices._pump_curves([(prices.SOL,self.mint)],{},[4]),{})
        request.assert_not_called()

    def test_legacy151_and_burned_supply_price_reserves_without_changing_address(self):
        anchors={(prices.SOL,pump.WSOL_MINT):{'price_usd':'100.04','source':'CoinGecko','observed_at':time.time()}}
        data=self.rpc()
        # Independent historical allocation with the ordinary legacy reserves.
        import base64,struct
        raw=pump._DISCRIMINATORS['BondingCurve']+struct.pack('<QQQQQB',10**15,30*10**9,8*10**14,2*10**9,10**15,0)
        raw+=bytes(151-len(raw));data['value'][1]=account(raw,lamports=3*10**9)
        burned=bytearray(mint());burned[36:44]=(999139998998175).to_bytes(8,'little')
        data['value'][0]=account(bytes(burned),pump.TOKEN_PROGRAM)
        with patch.object(omni_rpc,'_sol_identity'),patch.object(omni_rpc,'rpc',return_value=data):
            result=prices._pump_curves([(prices.SOL,self.mint)],anchors,[4])[(prices.SOL,self.mint)]
        self.assertEqual(Decimal(result['price_usd']),Decimal('0.0000030012'))
        self.assertEqual(result['reference'],self.mint)
        self.assertEqual(result['pool_ref'],pump.derive_curve(self.mint))
        # Supply inflation/empty supply, impossible real reserves and a
        # post-completion leg still cannot create a valid spot observation.
        for supply in (0,10**15+1,8*10**14-1):
            invalid=deepcopy(data);encoded=bytearray(burned);encoded[36:44]=supply.to_bytes(8,'little')
            invalid['value'][0]=account(bytes(encoded),pump.TOKEN_PROGRAM)
            with patch.object(omni_rpc,'_sol_identity'),patch.object(omni_rpc,'rpc',return_value=invalid):
                self.assertEqual(prices._pump_curves([(prices.SOL,self.mint)],anchors,[4]),{})
        invalid=deepcopy(data);invalid['value'][1]=account(raw[:-1]+b'\x01',lamports=3*10**9)
        with patch.object(omni_rpc,'_sol_identity'),patch.object(omni_rpc,'rpc',return_value=invalid):
            self.assertEqual(prices._pump_curves([(prices.SOL,self.mint)],anchors,[4]),{})


class WalletTargetedPriceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(store,'ROOT',Path(self.temp.name));self.root.start();store.bootstrap()
        self.cache=patch.object(prices,'_cache',OrderedDict());self.cache.start()
        self.budget=patch.object(prices,'_provider_next',{});self.budget.start()
        self.rates=patch.object(market,'PROVIDERS',{k:dict(v,spacing=0) for k,v in market.PROVIDERS.items()});self.rates.start()
    def tearDown(self):self.rates.stop();self.budget.stop();self.cache.stop();self.root.stop();self.temp.cleanup()
    def test_unlisted_unbound_token_has_exact_quote_and_snapshot_never_fetches(self):
        asset=store.register_asset(ETH,'erc20',ADDRESS,'SAME','Unlisted fixture',6,metadata='RPC_METADATA')
        account_id=store.account(ETH,'0x'+'2'*40)
        observation={'asset_id':asset['id'],'account_id':account_id,'atomic':'2000000','quantity':'2','observed_at':time.time(),'state':'VERIFIED_READ'}
        with store.db(True) as db:db.execute('INSERT INTO observations VALUES(?,?,?)',(asset['id'],account_id,store.pack(observation)))
        with patch.object(prices,'_json',return_value=[pair(price='2.25')]) as network:
            market.refresh_wallet_quotes([asset['id']]);self.assertEqual(network.call_count,1)
            before=network.call_count
            first=omni_wallet.snapshot(lab={});second=omni_wallet.snapshot(lab={})
            self.assertEqual(network.call_count,before)
            market.refresh_wallet_quotes([asset['id']]);self.assertEqual(network.call_count,before)
        position=next(r for r in first['rows'] if r['asset_id']==asset['id'])
        self.assertEqual(position['value_usd'],'4.50');self.assertEqual(position['price_source'],'DEX Screener')
        self.assertEqual(position['price_quality'],'DEX_POOL_SPOT');self.assertFalse(position['price_stale'])
        self.assertEqual(second['price_policy']['mode'],'MANUAL_ONLY')
        self.assertIsNone(market.pref('view'))

    def test_captured_gg_token_prices_single_selected_asset_without_native_sol_position(self):
        public=json.loads((Path(__file__).with_name('pump-gg-token-public-2026-10-29.json')).read_text())
        asset=store.register_asset(prices.SOL,'token',public['mint'],'GGHB','Gold Goblins',6,metadata='RPC_METADATA')
        account_id=store.account(prices.SOL,pump.b58encode(b'\x19'*32),'Public fixture account')
        quantity='31529284.463525'
        observation={'asset_id':asset['id'],'account_id':account_id,'atomic':'31529284463525','quantity':quantity,'observed_at':time.time(),'state':'VERIFIED_READ'}
        with store.db(True) as db:db.execute('INSERT INTO observations VALUES(?,?,?)',(asset['id'],account_id,store.pack(observation)))
        anchor=market.parse_coins([coin('solana',100)])[0]
        def no_market(url,provider):return [] if provider=='dexscreener' else {'data':[]}
        with patch.object(market,'_targeted_coins',return_value=[anchor]) as conversions,\
             patch.object(prices,'_json',side_effect=no_market),\
             patch.object(omni_rpc,'_sol_identity') as identity,patch.object(omni_rpc,'rpc',return_value=public['batch']) as rpc:
            result=market.refresh_wallet_quotes([asset['id']])
        self.assertEqual(conversions.call_args.args[0],{'solana','usd-coin'})
        self.assertEqual(result['quotes'],1);identity.assert_called_once();self.assertEqual(rpc.call_count,1)
        # No actual account/native holding was required for a selected token's
        # explicit USD conversion. Exact-mint account data reached real totals.
        with patch.object(prices,'_json') as dex,patch.object(omni_rpc,'_json') as network:
            wallet=omni_wallet.snapshot(lab={});again=omni_wallet.snapshot(lab={})
        dex.assert_not_called();network.assert_not_called()
        position=next(r for r in wallet['rows'] if r['asset_id']==asset['id'])
        self.assertEqual(position['quantity'],quantity)
        self.assertGreater(Decimal(position['value_usd']),Decimal('96'))
        self.assertLess(Decimal(position['value_usd']),Decimal('98'))
        self.assertEqual(position['price_source'],'Pump RPC · reserve estimate')
        self.assertEqual(position['price_quality'],'BONDING_CURVE_SPOT')
        self.assertEqual(wallet['summary']['known_value_usd'],again['summary']['known_value_usd'])
        self.assertFalse(position['price_stale'])

    def test_favourite_refresh_queries_only_saved_favourites_and_reuses_wallet_quote(self):
        asset=store.register_asset(ETH,'erc20',ADDRESS,'FIX','Fixture',18,metadata='RPC_METADATA')
        chosen=market.parse_pairs([pair()])[0];other=market.parse_pairs([pair(address='0x'+'3'*40)])[0]
        market._save_rows([chosen,other]);market.star(chosen['id'],True)
        market.configure({'view':'watchlist'})
        with patch.object(prices,'_json',return_value=[pair(price='3')]) as network,patch.object(omni_rpc,'_json') as global_catalogue:
            result=market.refresh();market.refresh_wallet_quotes([asset['id']])
        self.assertEqual(result['scope'],'FAVOURITES_ONLY');self.assertEqual(network.call_count,1)
        self.assertNotIn(other['reference'],network.call_args.args[0]);global_catalogue.assert_not_called()
        self.assertEqual(market.row(chosen['id'])['price_usd'],'3')

    def test_bound_coingecko_failure_falls_back_without_replacing_fresh_aggregate(self):
        asset=store.register_asset(ETH,'erc20',ADDRESS,'FIX','Fixture',6,metadata='RPC_METADATA')
        account_id=store.account(ETH,'0x'+'2'*40)
        observation={'asset_id':asset['id'],'account_id':account_id,'atomic':'2000000','quantity':'2','observed_at':time.time(),'state':'VERIFIED_READ'}
        aggregate=market.parse_coins([coin('fixture-provider-id',2)])[0];aggregate['observed_at']=time.time()-600
        market._save_rows([aggregate])
        with market._db(True) as db:
            db.execute('INSERT INTO explorer_bindings VALUES(?,?,?)',(asset['id'],aggregate['id'],'RPC_AND_PROVIDER_REFERENCE'))
            db.execute('INSERT INTO observations VALUES(?,?,?)',(asset['id'],account_id,store.pack(observation)))
        with patch.object(omni_rpc,'_json',side_effect=OSError('offline-fixture')),patch.object(prices,'_json',return_value=[pair(price='3')]):
            with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):market.refresh_wallet_quotes([asset['id']])
        position=next(r for r in omni_wallet.snapshot(lab={})['rows'] if r['asset_id']==asset['id'])
        self.assertEqual(position['value_usd'],'6.00');self.assertEqual(position['price_source'],'DEX Screener')
        aggregate.update(price_usd=5,observed_at=time.time());market._save_rows([aggregate])
        with patch.object(prices,'_json') as dex,patch.object(omni_rpc,'_json') as cg:
            market.refresh_wallet_quotes([asset['id']])
        dex.assert_not_called();cg.assert_not_called()
        position=next(r for r in omni_wallet.snapshot(lab={})['rows'] if r['asset_id']==asset['id'])
        self.assertEqual(position['value_usd'],'10.00');self.assertEqual(position['price_source'],'CoinGecko')


if __name__=='__main__':unittest.main()
