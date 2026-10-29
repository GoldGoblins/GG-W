"""Adversarial local checks for canonical assets, admission and signed lab state."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import shutil
import unittest
from unittest.mock import patch
from backend import omni_assets as assets,omni_rpc,omni_lab as lab,omni_service as service
from backend.omni_transport import Receiver,fragment,HEADER


class OmniTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=patch.object(assets,'ROOT',Path(self.tmp.name)); self.root.start()
        assets.bootstrap(); lab._keys.clear(); lab._participating=False; lab._receiver=None

    def tearDown(self): self.root.stop(); self.tmp.cleanup()

    def test_identity_is_network_and_address_not_ticker(self):
        a=assets.register_asset('eip155:1','erc20','0x'+'1'*40,'SAME','A',18)
        b=assets.register_asset('eip155:56','erc20','0x'+'1'*40,'SAME','B',6)
        self.assertNotEqual(a['id'],b['id'])
        with self.assertRaisesRegex(ValueError,'DECIMALS_CONFLICT'): assets.register_asset('eip155:1','erc20','0x'+'1'*40,'SAME','A',6)
        with self.assertRaisesRegex(ValueError,'NATIVE_IDENTITY'): assets.register_asset('eip155:1','native','ETH','ETH','Fake',6)
        with self.assertRaisesRegex(ValueError,'CHAIN_ID'): assets.register_network({'id':'wrong:abc','family':'evm'})

    def test_exact_amounts_preserve_uint256_and_reject_loss(self):
        self.assertEqual(assets.amount_atomic('18446744073709551615.000000001',9),18446744073709551615000000001)
        self.assertEqual(assets.format_atomic(100001,4),'10.0001')
        for value in (True,1.2,'1e3','-1','0.0000000001','NaN'):
            with self.subTest(value=value),self.assertRaises(ValueError): assets.amount_atomic(value,9)

    def test_eip55_and_long_cardano_address(self):
        self.assertEqual(assets.evm_address('0x52908400098527886E0F7030069857D2E4169EE7'),'0x52908400098527886e0f7030069857d2e4169ee7')
        with self.assertRaisesRegex(ValueError,'CHECKSUM'): assets.evm_address('0x52908400098527886E0F7030069857D2E4169Ee7')
        from bech32 import bech32_encode,convertbits
        address=bech32_encode('addr',convertbits(bytes([1])+bytes(56),8,5))
        self.assertGreater(len(address),90)
        self.assertEqual(assets.address_for(assets.network('cardano:mainnet'),address),address)

    def test_read_only_rpc_identity_and_exact_balance(self):
        account=assets.account('eip155:1','0x'+'2'*40)
        with patch.object(omni_rpc,'rpc',side_effect=['0x1','0x10000000000000001']):
            result=omni_rpc.balance('eip155:1/native:ETH',account)
        self.assertEqual(result['atomic'],str(2**64+1)); self.assertEqual(result['identity_level'],'RPC_CHAIN_ID')
        with patch.object(omni_rpc,'rpc',return_value='0x38'),self.assertRaisesRegex(ValueError,'WRONG_CHAIN'):
            omni_rpc.balance('eip155:1/native:ETH',account)
        with self.assertRaisesRegex(ValueError,'READ_ONLY'): omni_rpc.rpc({},'eth_sendRawTransaction',[])

    def test_failed_refresh_preserves_last_value_and_marks_stale(self):
        account=assets.account('eip155:1','0x'+'2'*40); args=json.dumps({'asset_id':'eip155:1/native:ETH','account_id':account})
        with patch.object(omni_rpc,'balance',return_value={'asset_id':'eip155:1/native:ETH','account_id':account,'quantity':'4','atomic':'4000000000000000000','state':'VERIFIED_READ','identity_level':'RPC_CHAIN_ID'}),patch('backend.crypto_explorer.refresh_wallet_quotes') as price:
            service.action('refresh_balance',args)
            price.assert_called_once_with(['eip155:1/native:ETH'])
        with patch.object(omni_rpc,'balance',side_effect=ValueError('OFFLINE')),self.assertRaises(ValueError): service.action('refresh_balance',args)
        observation=assets.snapshot()['observations'][0]
        self.assertEqual(observation['quantity'],'4'); self.assertEqual(observation['state'],'READ_FAILED')

    def test_detail_refresh_keeps_good_exact_balance_when_price_provider_fails(self):
        account=assets.account('eip155:1','0x'+'2'*40)
        args=json.dumps({'asset_id':'eip155:1/native:ETH','account_id':account})
        with patch.object(omni_rpc,'balance',return_value={'asset_id':'eip155:1/native:ETH','account_id':account,'quantity':'4.000000000000000001','atomic':'4000000000000000001','state':'VERIFIED_READ','identity_level':'RPC_CHAIN_ID'}),patch('backend.crypto_explorer.refresh_wallet_quotes',side_effect=ValueError('PUBLIC_QUOTE_UNAVAILABLE')) as price:
            service.action('refresh_balance',args)
            price.assert_called_once_with(['eip155:1/native:ETH'])
        observation=assets.snapshot()['observations'][0]
        self.assertEqual(observation['quantity'],'4.000000000000000001')
        self.assertEqual(observation['state'],'VERIFIED_READ')
        with patch.object(omni_rpc,'balance',side_effect=ValueError('OFFLINE')),patch('backend.crypto_explorer.refresh_wallet_quotes') as price:
            with self.assertRaises(ValueError):service.action('refresh_balance',args)
            price.assert_not_called()

    def test_packet_loss_reorder_retry_duplicates_and_expiry(self):
        now=[1000.0]; receiver=Receiver(bytes_per_minute=65536,clock=lambda:now[0]); data=b'public-payload'*120
        packets=fragment(data,128,now=1000); results=[receiver.receive('a',p) for p in reversed(packets[1:])]
        self.assertTrue(all(r['state']=='PARTIAL' for r in results)); self.assertEqual(receiver.snapshot()['delivered'],0)
        result=receiver.receive('a',packets[0]); self.assertEqual(result['data'],data)
        self.assertEqual(receiver.receive('a',packets[0])['state'],'DUPLICATE')
        receiver.receive('a',fragment(b'x'*200,128,now=1000)[0]); now[0]=1400
        self.assertEqual(receiver.snapshot()['queued'],0); self.assertEqual(receiver.snapshot()['expired'],1)

    def test_flood_and_sybil_inputs_cannot_grow_queues_without_bound(self):
        receiver=Receiver(bytes_per_minute=8192,max_messages=2)
        for i in range(500): receiver.receive('peer-'+str(i),fragment(str(i).encode()*100,128)[0])
        status=receiver.snapshot()
        self.assertLessEqual(status['queued'],2); self.assertLessEqual(status['peers'],32)
        self.assertLessEqual(status['storage_used'],status['storage_limit']); self.assertGreater(status['rejected'],400)
        self.assertEqual(status['signature_checks'],0)

    def test_bad_checksum_and_fragment_conflict(self):
        receiver=Receiver(bytes_per_minute=65536); p=fragment(b'x'*200,128)[0]
        self.assertEqual(receiver.receive('a',p[:-1]+b'y')['state'],'BAD_CHECKSUM')
        self.assertEqual(receiver.receive('a',p)['state'],'PARTIAL')
        fields=list(HEADER.unpack(p[:HEADER.size])); fields[4]+=1
        self.assertEqual(receiver.receive('a',HEADER.pack(*fields)+p[HEADER.size:])['state'],'CONFLICT')

    def test_lab_quorum_and_history_replay_conservation(self):
        lab.create(); tx=lab.prepare(); lab.submit(tx); before=lab.snapshot()['balances']
        lab.configure({'enabled':[True,True,False,False]}); self.assertEqual(lab.commit()['state'],'WAITING_QUORUM')
        self.assertEqual(lab.snapshot()['balances'],before)
        lab.configure({'enabled':[True,True,True,False],'economics':{'burn_bps':1000,'holder_bps':2000,'contributor_bps':7000}})
        self.assertEqual(lab.commit()['state'],'FINALIZED'); state=lab.snapshot()
        self.assertEqual(sum(state['balances'].values())+state['burned']+state['contributor_pool'],lab.SUPPLY)
        self.assertEqual(lab.verify()['state'],'VERIFIED')
        with self.assertRaises(ValueError): lab.submit(tx)
        tampered=lab._load(); tampered['balances'][tx['body']['sender']]+=1
        self.assertEqual(lab.verify(tampered)['state'],'INVALID')
        tampered=lab._load(); tampered['blocks'][0]['signatures'][1]=tampered['blocks'][0]['signatures'][0]
        self.assertEqual(lab.verify(tampered)['state'],'INVALID')

    def test_sender_witness_and_signature_tampering_rejected(self):
        lab.create(); tx=lab.prepare()
        self.assertTrue(lab.verify_witness(tx['body']['account_root'],tx['sender_witness']))
        wrong=copy.deepcopy(tx); wrong['sender_witness']['leaf']['balance']='999999999999'
        with self.assertRaisesRegex(ValueError,'WITNESS'): lab.submit(wrong)
        wrong=copy.deepcopy(tx); wrong['body']['amount']='1000001'
        with self.assertRaisesRegex(ValueError,'SIGNATURE'): lab.submit(wrong)
        wrong=copy.deepcopy(tx); wrong['body']['chain_id']='gglab:other'
        with self.assertRaisesRegex(ValueError,'WRONG_CHAIN'): lab.submit(wrong)

    def test_restart_seals_keys_and_never_autostarts_node(self):
        lab.create(); lab.configure({'participating':True}); chain=lab.snapshot()['chain_id']
        lab._keys.clear(); lab._participating=False
        self.assertEqual(lab.snapshot()['state'],'SEALED_SESSION'); self.assertFalse(lab.snapshot()['participating'])
        with self.assertRaisesRegex(ValueError,'SEALED'): lab.prepare()
        lab.create(); self.assertNotEqual(lab.snapshot()['chain_id'],chain)

    def test_failed_new_lab_keeps_previous_session_usable(self):
        lab.create();chain=lab.snapshot()['chain_id']
        with patch.object(assets,'register_network',side_effect=ValueError('OMNI_NETWORK_LIMIT')),self.assertRaises(ValueError):lab.create()
        self.assertEqual(lab.snapshot()['chain_id'],chain)
        self.assertEqual(lab.snapshot()['state'],'ACTIVE_SESSION')
        self.assertEqual(lab.submit(lab.prepare())['state'],'QUEUED')

    def test_local_web_view_has_owned_start_stop_and_file_allowlist(self):
        from backend import omni_web as web
        import threading
        class FakeServer:
            def __init__(self,address,handler):self.address=address;self.server_port=18874;self.done=threading.Event();self.closed=False
            def serve_forever(self):self.done.wait(3)
            def shutdown(self):self.done.set()
            def server_close(self):self.closed=True
        with patch.object(web,'Server',FakeServer):
            try:
                first=web.start();server=web._server
                self.assertEqual(server.address,('127.0.0.1',0))
                self.assertEqual(web.start(),first);self.assertIs(web._server,server)
            finally:web.stop()
            self.assertTrue(server.closed);self.assertEqual(web.snapshot()['state'],'STOPPED')
        handler=object.__new__(web.Handler);handler.path='/../backend/omni_web.py';handler.send_error=lambda code:setattr(handler,'rejected',code)
        self.assertIsNone(handler.send_head());self.assertEqual(handler.rejected,404)

    def test_mobile_transport_retries_only_missing_packet(self):
        lab.create()
        with self.assertRaisesRegex(ValueError,'PAUSED'): lab.transport_test()
        lab.configure({'participating':True})
        result=lab.transport_test(loss=True); self.assertEqual(result['state'],'RETRY_REQUIRED')
        self.assertEqual(lab.snapshot()['retry_packets'],1)
        self.assertEqual(lab.retry_transport()['state'],'QUEUED')
        self.assertEqual(lab.snapshot()['pending'],1); self.assertEqual(lab.snapshot()['transport']['signature_checks'],1)

    def test_marketplace_exact_generic_currency_bound_into_receipt(self):
        from backend import marketplace_contract as mp
        with patch.object(mp,'STATE_DIR',Path(self.tmp.name)/'mp'):
            asset='eip155:56/native:BNB'
            item=mp.list_item({'title':'Generic paper object','category':'ITEM','material':'UNKNOWN','settlement_asset_id':asset,'price':'1.000000000000000001'})
            self.assertEqual(item['settlement']['price_atomic'],'1000000000000000001')
            self.assertEqual(item['price_label'],'1.000000000000000001 BNB')
            original=mp.hash_identity(item); modified=copy.deepcopy(item); modified['settlement']['asset_id']='eip155:1/native:ETH'
            self.assertNotEqual(mp.hash_identity(modified),original)
            self.assertEqual(mp.paper_buy(item['id'])['status'],'SOLD')
            mp.catalog_path().write_text('{broken',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'CORRUPT'): mp.load_catalog()
            for price in ('0.0000000001',True,float('nan')):
                with self.assertRaises(ValueError): mp.parse_sol_price(price)

    def test_bots_same_ticker_on_two_networks_have_isolated_checkpoints(self):
        from backend import omni_bots as bots,crypto_contract as contract,crypto_paper as paper
        from tests.test_crypto_paper import frame
        with patch.object(contract,'STATE_DIR',Path(self.tmp.name)/'paper'):
            first=assets.register_asset('eip155:1','erc20','0x'+'1'*40,'SOL','First',9)['id']
            second=assets.register_asset('eip155:56','erc20','0x'+'1'*40,'SOL','Other',9)['id']
            bots.bind(first,'SOLUSDT'); bots.bind(second,'SOLUSDT'); bots.enabled(first,'dca',True)
            self.assertFalse(any(a['enabled'] for a in bots.snapshot(second)['accounts']))
            raw=frame(96)
            with paper.asset_scope(first):
                paper.advance('SOLUSDT',{'1h':raw},now=raw['times'][-1]+3600)
                first_path=paper._path('SOLUSDT')
            with paper.asset_scope(second):
                self.assertNotEqual(first_path,paper._path('SOLUSDT'))
                self.assertIsNone(paper.snapshot('SOLUSDT')['updated_at'])
            self.assertIsNotNone(bots.snapshot(first)['updated_at'])
            self.assertIsNone(paper.snapshot('SOLUSDT')['updated_at'])

    def test_generic_market_symbol_requires_public_tradable_spot_record(self):
        from backend import omni_bots as bots
        identifier=assets.register_asset('eip155:1','erc20','0x'+'3'*40,'BTC','Example',8)['id']
        result={'symbols':[{'symbol':'BTCUSDT','quoteAsset':'USDT','isSpotTradingAllowed':True,'status':'TRADING'}]}
        with patch.object(omni_rpc,'_json',return_value=result): bots.bind(identifier,'BTCUSDT')
        self.assertEqual(bots.snapshot(identifier)['pair'],'BTCUSDT')
        result['symbols'][0]['status']='BREAK'
        with patch.object(omni_rpc,'_json',return_value=result),self.assertRaisesRegex(ValueError,'UNAVAILABLE'): bots.bind(identifier,'BTCUSDT')

    def test_browser_webcrypto_checks_python_signature_and_witness(self):
        node=shutil.which('node')
        if not node: self.fail('Node is required for the browser cryptography integration check')
        lab.create(); envelope=lab.prepare(); body=envelope['body']
        bundle={'envelope':envelope,'checkpoint':{'chain_id':body['chain_id'],'account_root':body['account_root']}}
        fixture=Path(self.tmp.name)/'public.json'; fixture.write_text(json.dumps(bundle),encoding='utf-8')
        module=(Path(__file__).resolve().parents[1]/'knowledge/gg-node-web/core.mjs').as_uri()
        script='''
import fs from 'node:fs';import assert from 'node:assert/strict';import {webcrypto} from 'node:crypto';if(!globalThis.crypto)globalThis.crypto=webcrypto;
const {PublicQueue,verifyEnvelope}=await import(MODULE);
const bundle=JSON.parse(fs.readFileSync(process.argv[1],'utf8')),raw=JSON.stringify(bundle.envelope),queue=new PublicQueue();
await assert.rejects(queue.add(raw,bundle.checkpoint),/PAUSED/);queue.paused=false;
assert.equal((await queue.add(raw,bundle.checkpoint)).state,'WITNESS_AND_SIGNATURE_VERIFIED');
assert.equal((await queue.add(raw,bundle.checkpoint)).state,'DUPLICATE');assert.equal(queue.items.length,1);
const wrong=structuredClone(bundle.envelope);wrong.body.amount='1000001';await assert.rejects(verifyEnvelope(wrong,bundle.checkpoint),/SIGNATURE/);
const stale={...bundle.checkpoint,account_root:'0'.repeat(64)};await assert.rejects(queue.add(raw,stale),/CHECKPOINT/);
queue.spent=1048576;await assert.rejects(queue.add(raw,bundle.checkpoint),/BUDGET/);
console.log('WEB_CRYPTO_PROOFS=PASS');
'''.replace('MODULE',json.dumps(module))
        result=subprocess.run([node,'--input-type=module','-e',script,str(fixture)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_nft_modules_semantics_and_uint_ids_are_chain_qualified(self):
        from backend import marketplace_protocols as mp,omni_intents
        contract='0x'+'1'*40
        a=mp.identity('eip155:1','erc721',contract,str(2**255))
        b=mp.identity('eip155:56','erc721',contract,str(2**255))
        self.assertNotEqual(a['id'],b['id']);self.assertEqual(a['kind'],'UNIQUE')
        for invalid in (2,2.0,True,'1e3',str(2**256)):
            with self.assertRaises(ValueError):mp.identity('eip155:1','erc721',contract,invalid)
        mp.toggle('erc721',False)
        with self.assertRaisesRegex(ValueError,'PAUSED'):mp.identity('eip155:1','erc721',contract,'1')
        with self.assertRaisesRegex(ValueError,'CORE'):mp.toggle('gg721',False)
        intent={'schema':'gg.intent.v1','operation':'asset.transfer','asset_kind':'UNIQUE','chain_id':'eip155:1','destination_chain_id':'eip155:56'}
        self.assertEqual(omni_intents.plan(intent)['state'],'NO_VERIFIED_BRIDGE_ROUTE')
        intent.update(operation='owner.read',destination_chain_id='eip155:1')
        self.assertEqual(omni_intents.plan(intent)['state'],'NFT_READ_ADAPTER')

    def test_real_nft_adapter_interface_ownership_and_metadata_rules(self):
        from backend import marketplace_protocols as mp
        owner='0x'+'2'*40;contract='0x'+'1'*40
        uri='ipfs://example/{id}.json';data=uri.encode();abi='0x'+format(32,'064x')+format(len(data),'064x')+data.hex().ljust(128,'0')
        with patch.object(omni_rpc,'rpc',side_effect=['0x1','0x1','0x0','0x1','0x'+owner[2:].zfill(64),abi]):
            item=mp.inspect('eip155:1','erc721',contract,'1')
        self.assertEqual(item['owner'],owner);self.assertEqual(item['settlement'],'NOT_CONNECTED')
        self.assertEqual(mp.snapshot()['watched_count'],1)
        with patch.object(omni_rpc,'rpc',side_effect=['0x1','0x1','0x1']),self.assertRaisesRegex(ValueError,'INTERFACE'):
            mp.inspect('eip155:1','erc721',contract,'1')
        self.assertEqual(mp.safe_uri(uri,'15'),'ipfs://example/'+format(15,'064x')+'.json')
        for bad in ('javascript:alert(1)','data:text/html,abc','https://name:password@example.com/a'):
            with self.assertRaises(ValueError):mp.safe_uri(bad)

    def test_royalties_quote_is_in_sale_units_and_not_enforcement(self):
        from backend import marketplace_protocols as mp
        response='0x'+'2'*40
        with patch.object(omni_rpc,'rpc',side_effect=['0x1','0x1','0x'+response[2:].zfill(64)+format(250,'064x')]):
            result=mp.royalty_quote('eip155:1','0x'+'1'*40,'9','10000')
        self.assertEqual(result['amount_atomic'],'250');self.assertFalse(result['enforced'])
        self.assertEqual(result['unit'],'SAME_AS_SALE_PRICE')

    def test_krc721_indexer_requires_sync_and_exact_token_identity(self):
        from backend import marketplace_protocols as mp
        status={'result':{'network':'mainnet','isNodeConnected':True,'isNodeSynced':True,'isIndexerSynced':True}}
        result={'result':{'tick':'KSPR','tokenId':'1','owner':'test-owner','buri':'ipfs://example'}}
        with patch.object(omni_rpc,'_json',side_effect=[status,result]),patch.object(assets,'address_for',return_value='test-owner'):
            item=mp.inspect('kaspa:mainnet','krc721','KSPR','1')
        self.assertEqual(item['trust'],'THIRD_PARTY_INDEXER');self.assertEqual(item['metadata_uri'],'ipfs://example/1')
        status['result']['isIndexerSynced']=False
        with patch.object(omni_rpc,'_json',return_value=status),self.assertRaisesRegex(ValueError,'UNSYNCED'):
            mp.inspect('kaspa:mainnet','krc721','KSPR','1')

    def test_visual_reference_and_transaction_receipt_are_bound_to_object(self):
        from backend import marketplace_contract as mp,marketplace_media as media
        from PIL import Image
        path=Path(self.tmp.name)/'reference.png';Image.new('RGB',(20,20),(42,81,100)).save(path)
        with patch.object(mp,'STATE_DIR',Path(self.tmp.name)/'mp'):
            attachment=media.import_image(path.as_uri(),mp.ensure_state_dir())
            item=mp.list_item({'title':'Teaching model','category':'ITEM','material':'MIXED','image_id':attachment['id'],'collection_name':'Teaching tools',
                              'settlement_asset_id':'eip155:1/native:ETH','price':'0.02'})
            self.assertEqual(mp.hash_identity(item),item['identity_sha256'])
            self.assertTrue(item['image_url'].startswith('file:'))
            modified=dict(item,image_id='0'*64+'.png');self.assertNotEqual(mp.hash_identity(modified),mp.hash_identity(item))
            sold=mp.paper_buy(item['id']);receipt=sold['transaction_receipt']
            self.assertEqual(receipt['body']['settlement_state'],'SIMULATED_NO_FUNDS_MOVED')
            self.assertEqual(receipt['digest'],mp.digest_json(receipt['body']))
            modified=copy.deepcopy(sold);modified['transaction_receipt']['body']['buyer']='other'
            self.assertNotEqual(mp.hash_state(modified),mp.hash_state(sold))
            service=mp.parse_listing({'title':'Repair service','kind':'SERVICE','category':'SERVICE','material':'UNKNOWN','price_sol':'1'})
            self.assertEqual(service['mass_g'],0)
            with self.assertRaisesRegex(ValueError,'NO_MASS'):mp.parse_listing(dict(service,mass_g=1))
            path.write_text('<svg></svg>',encoding='utf-8')
            with self.assertRaises(ValueError):media.import_image(path.as_uri(),mp.ensure_state_dir())


if __name__=='__main__': unittest.main()
