"""Portable VM execution and failure boundaries for both chain connections."""
import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend import crypto_contract as C, kaspa_contract as K, crypto_svm as vm
from backend import crypto_connections as connections, kaspa_node, crypto_tx, kaspa_covenant, crypto_host


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-crypto-runtime-test-')
        self.root = Path(self.temp.name)
        self.patches = [patch.object(C,'STATE_DIR',self.root/'sol'), patch.object(K,'STATE_DIR',self.root/'kas')]
        for item in self.patches: item.start()
        with connections._LOCK:
            connections._CACHE.clear()
            connections._BUSY.clear()

    def tearDown(self):
        if vm.active(): vm.stop()
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def transfer(self, lamports=1000000000):
        from solders.keypair import Keypair
        from solders.message import Message
        from solders.transaction import VersionedTransaction
        from solders.system_program import transfer
        from solders.hash import Hash
        payer, receiver = Keypair(), Keypair()
        self.assertIn('result',vm.rpc('requestAirdrop',[str(payer.pubkey()),100*10**9]))
        blockhash=vm.rpc('getLatestBlockhash',[])['result']['value']['blockhash']
        tx=VersionedTransaction(Message.new_with_blockhash([transfer({'from_pubkey':payer.pubkey(),'to_pubkey':receiver.pubkey(),'lamports':lamports})],payer.pubkey(),Hash.from_string(blockhash)),[payer])
        return payer,receiver,base64.b64encode(bytes(tx)).decode()

    def test_real_svm_simulation_is_non_mutating_and_transfer_persists(self):
        vm.start()
        payer,receiver,raw=self.transfer()
        initial=vm.rpc('getBalance',[str(payer.pubkey())])['result']['value']
        result=vm.rpc('simulateTransaction',[raw])
        self.assertIsNone(result['result']['value']['err'])
        self.assertEqual(vm.rpc('getBalance',[str(payer.pubkey())])['result']['value'],initial)
        sent=vm.rpc('sendTransaction',[raw])
        self.assertIn('result',sent)
        self.assertEqual(vm.rpc('getBalance',[str(receiver.pubkey())])['result']['value'],10**9)
        status=vm.rpc('getSignatureStatuses',[[sent['result']]])['result']['value'][0]
        self.assertEqual(status['confirmationStatus'],'finalized')
        vm.stop(); vm.start()
        self.assertEqual(vm.rpc('getBalance',[str(receiver.pubkey())])['result']['value'],10**9)

    def test_vm_rejects_invalid_signatures_replay_invalid_requests_and_unknown_methods(self):
        vm.start()
        payer,receiver,raw=self.transfer()
        tampered=bytearray(base64.b64decode(raw)); tampered[1] ^= 1
        self.assertIn('error',vm.rpc('sendTransaction',[base64.b64encode(tampered).decode()]))
        self.assertEqual(vm.rpc('getBalance',[str(receiver.pubkey())])['result']['value'],0)
        self.assertIn('result',vm.rpc('sendTransaction',[raw]))
        self.assertIn('error',vm.rpc('sendTransaction',[raw]))
        self.assertIn('error',vm.rpc('futureUnsupportedMethod',[]))
        for amount in [True,-1,10**20]: self.assertIn('error',vm.rpc('requestAirdrop',[str(payer.pubkey()),amount]))
        self.assertIn('error',vm.rpc('sendTransaction',['x'*2000]))

    def test_corrupt_saved_vm_state_is_not_silently_reseeded(self):
        C.ensure_state_dir().joinpath('svm-accounts.json').write_text('{broken')
        with self.assertRaises(ValueError): vm.start()
        self.assertFalse(vm.active())
        self.assertEqual(C.ensure_state_dir().joinpath('svm-accounts.json').read_text(),'{broken')

    def test_vm_token_accounts_preserve_atomic_precision_and_owner_identity(self):
        from solders.account import Account
        from solders.pubkey import Pubkey
        vm.start()
        owner,mint,ata=Pubkey.new_unique(),Pubkey.new_unique(),Pubkey.new_unique()
        program=Pubkey.from_string(crypto_host.TOKEN_PROGRAM)
        amount=2**63+7
        mint_data=bytearray(82); mint_data[44]=6; mint_data[45]=1
        token_data=bytearray(165); token_data[:32]=bytes(mint); token_data[32:64]=bytes(owner)
        token_data[64:72]=amount.to_bytes(8,'little'); token_data[108]=1
        vm._bank.set_account(mint,Account(10**9,bytes(mint_data),program,False,0))
        vm._bank.set_account(ata,Account(10**9,bytes(token_data),program,False,0))
        rows=vm.rpc('getTokenAccountsByOwner',[str(owner),{'programId':str(program)}])['result']['value']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['account']['data']['parsed']['info']['tokenAmount']['amount'],str(amount))
        other=vm.rpc('getTokenAccountsByOwner',[str(Pubkey.new_unique()),{'programId':str(program)}])['result']['value']
        self.assertEqual(other,[])

    def test_compiler_receipt_is_invalidated_by_source_change(self):
        from types import SimpleNamespace
        source=self.root/'counter.sil'; source.write_text('fixture source one')
        compiler=self.root/'silverc.exe'; compiler.write_text('fixture')
        def compile_fixture(args,**kwargs):
            Path(args[args.index('-o')+1]).write_text(json.dumps({'contracts':{'Counter':{'compiled':{'bytecode':[81]}}}}))
            return SimpleNamespace(returncode=0,stderr='',stdout='')
        with patch.object(kaspa_covenant,'COUNTER_SIL',source),patch.object(kaspa_covenant,'lab_status',return_value={'silverc':True,'silverc_path':str(compiler)}),patch.object(kaspa_covenant.subprocess,'run',side_effect=compile_fixture):
            self.assertTrue(kaspa_covenant.compile_counter()['compiled'])
            self.assertTrue(K.ensure_state_dir().joinpath('counter-compiled.json').is_file())
            source.write_text('fixture source two')
            self.assertFalse(kaspa_covenant.snapshot()['compiled'])

    def test_unmarked_kaspa_ledger_cannot_be_reused(self):
        node_root=self.root/'node-root'; node_root.mkdir(); (node_root/'node').mkdir()
        (node_root/'owner.json').write_text(json.dumps({'unrelated':True}))
        binary=self.root/'kaspad.exe'; binary.write_text('fixture')
        with patch.object(kaspa_node,'ROOT',node_root),patch.object(kaspa_node,'BINARY',binary),patch.object(kaspa_node,'rpc',side_effect=OSError('offline')),patch.object(kaspa_node.subprocess,'Popen',side_effect=AssertionError('Never start over unowned state')):
            with self.assertRaisesRegex(ValueError,'UNOWNED'): kaspa_node.start()

    def test_local_vm_is_never_routed_to_mainnet_write_methods(self):
        vm.start()
        with patch.object(crypto_host,'load_network',return_value='mainnet'), patch.object(vm,'rpc',side_effect=AssertionError('Mainnet must not reach local write route')):
            result=crypto_host.rpc_call('sendTransaction',[],network='testnet')
            self.assertEqual(result['error']['message'],'MAINNET_OBSERVE_ONLY')

    def test_sol_live_requires_correct_genesis_and_health(self):
        with patch.object(connections,'_request',return_value={'result':'wrong-chain'}):
            with self.assertRaisesRegex(ValueError,'WRONG_NETWORK'): connections._probe('SOL','mainnet','')
        for health in [{'result':'bad'}, {'result':'ok','error':{'code':1}}]:
            with patch.object(connections,'_request',side_effect=[{'result':connections.SOL_GENESIS},health]):
                with self.assertRaisesRegex(ValueError,'UNHEALTHY'): connections._probe('SOL','mainnet','')
        with patch.object(connections,'_request',side_effect=[{'result':connections.SOL_GENESIS},{'result':'ok'},{'result':123}]):
            result=connections._probe('SOL','mainnet','')
            self.assertTrue(result['healthy']); self.assertEqual(result['write_authority'],'NONE')

    def test_kaspa_live_requires_correct_network_and_never_uses_paper_balance(self):
        with patch.object(connections,'_request',return_value={'networkName':'simnet','virtualDaaScore':10}):
            with self.assertRaisesRegex(ValueError,'WRONG_NETWORK'): connections._probe('KAS','mainnet','')
        with patch.object(connections,'_request',return_value={'networkName':'kaspa-mainnet','virtualDaaScore':'123'}):
            result=connections._probe('KAS','mainnet','')
            self.assertNotIn('balance_kas',result)
            self.assertTrue(result['healthy'])

    def test_wrong_watch_network_does_not_claim_chain_is_down(self):
        with patch.object(connections,'_request',return_value={'networkName':'kaspa-mainnet','virtualDaaScore':'123'}):
            result=connections._probe('KAS','mainnet','kaspasim:'+'q'*61)
            self.assertTrue(result['healthy'])
            self.assertEqual(result['watch_error'],'KASPA_WATCH_NETWORK_MISMATCH')
            self.assertNotIn('balance_kas',result)

    def test_late_connection_result_is_discarded_after_lab_stop(self):
        entered,release=threading.Event(),threading.Event()
        def probe(*args):
            entered.set(); release.wait(2)
            return {'healthy':True,'observed_at':time.time()}
        with patch.object(connections,'_probe',side_effect=probe):
            connections.snapshot('SOL','testnet'); self.assertTrue(entered.wait(1))
            connections.invalidate('SOL','testnet'); release.set()
            deadline=time.monotonic()+3
            while connections._BUSY and time.monotonic()<deadline: time.sleep(.01)
            self.assertNotIn(('SOL','testnet',''),connections._CACHE)

    def test_covenant_amounts_are_exact_and_bounded(self):
        for value in [True,1.1,'1.2',-1,2**64]:
            with self.assertRaises(ValueError): kaspa_covenant.genesis(value_sompi=value)
        kaspa_covenant.genesis()
        for value in [True,1.1,'1.2',2**63]:
            with self.assertRaises(ValueError): kaspa_covenant.transition('add',value)
        kaspa_covenant.transition('add',2**63-1)
        with self.assertRaises(ValueError): kaspa_covenant.transition('add',1)

    def test_kaspa_address_checksum_payload_and_network_prefix(self):
        from backend import kaspa_address as address
        for prefix in address.PREFIXES:
            for version in [0,1,8]:
                encoded=address.encode(prefix,bytes(33 if version==1 else 32),version)
                self.assertEqual(address.validate(encoded),encoded)
                self.assertEqual(address.validate(encoded.upper()),encoded)
                bad=encoded[:-1]+('q' if encoded[-1]!='q' else 'p')
                with self.assertRaises(ValueError): address.validate(bad)
        with self.assertRaises(ValueError): address.validate('kaspa:'+'q'*61)
        with self.assertRaises(ValueError): address.encode('kaspa',bytes(31))

    def test_diagnostics_are_async_coalesced_and_mark_old_results_stale(self):
        entered, release=threading.Event(),threading.Event()
        def probe(*args):
            entered.set(); release.wait(3)
            return {'healthy':True,'observed_at':time.time()}
        with patch.object(connections,'_probe',side_effect=probe) as worker:
            start=time.perf_counter()
            first=connections.snapshot('SOL','mainnet',True)
            self.assertLess(time.perf_counter()-start,.1)
            self.assertTrue(first['loading']); self.assertTrue(entered.wait(1))
            for _ in range(20): connections.snapshot('SOL','mainnet',True)
            release.set()
            deadline=time.monotonic()+2
            while connections._BUSY and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(worker.call_count,1)
            with connections._LOCK:
                connections._CACHE[('SOL','mainnet','')]['observed_at']=0
            value=connections.snapshot('SOL','mainnet')
            self.assertTrue(value['stale'])
            release.set()
            while connections._BUSY: time.sleep(.01)

    def test_worker_start_failure_can_be_retried(self):
        with patch.object(connections.threading,'Thread',side_effect=RuntimeError('fixture')):
            first=connections.snapshot('SOL','mainnet')
        self.assertEqual(first['error'],'CRYPTO_WORKER_START')
        self.assertFalse(connections._BUSY)

    def test_kaspa_node_refuses_write_methods_and_does_not_stop_unowned_process(self):
        with self.assertRaisesRegex(ValueError,'READ_ONLY'): kaspa_node.rpc('submitTransaction',{})
        with patch.object(kaspa_node,'running_pid',return_value=None),patch.object(kaspa_node,'terminate_process_tree',side_effect=AssertionError('Foreign process')):
            self.assertFalse(kaspa_node.stop()['running'])

    def test_false_sdk_detection_is_corrected(self):
        with patch.dict('sys.modules',{'kaspa':type('Namespace',(),{})()}):
            self.assertFalse(kaspa_covenant.lab_status()['sdk'])

    def test_bad_blockhash_and_foreign_signature_never_confirm(self):
        for value in [bytes(31),bytes(33)]:
            with self.assertRaises(ValueError): crypto_tx._pad32(value)
        def rpc(method,params):
            if method=='getLatestBlockhash': return {'result':{'value':{'blockhash':'1'*32}}}
            if method=='sendTransaction': return {'result':'foreign-signature'}
            raise AssertionError('Foreign signature must not be confirmed')
        with patch.object(crypto_tx,'load_test_pubkey',return_value='1'*32),patch.object(crypto_tx,'signed_transfer_bytes',return_value=b'\x01'+b'x'*64):
            with self.assertRaises(crypto_tx.ConfirmationError) as result: crypto_tx.send_self_transfer(rpc,1)
            self.assertEqual(result.exception.status,'signature_mismatch')


if __name__=='__main__': unittest.main()
