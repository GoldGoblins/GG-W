"""Isolated Windows key vault and actual signed SPL round trip in LiteSVM.

Only isolated fixture keys are used. No cluster writes or user's
wallet reads. RPC responses below come from the local SVM, not a live cluster.
"""
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from backend import omni_assets as store,omni_rpc,wallet_vault as vault,wallet_approval as approval,solana_transfers as tx,omni_discovery as discovery,solana_metadata
from backend import crypto_pump_accounts as spl


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-sol-wallet-test-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);p=patch.object(store,'ROOT',self.root/'state');p.start();self.addCleanup(p.stop);store.bootstrap()


@unittest.skipUnless(os.name=='nt','Current-user Windows DPAPI storage')
class VaultTests(Isolated):
    def test_approval_precedes_key_generation_and_no_plaintext_fallback(self):
        with patch('backend.task_scoped_action_grant.runtime_authorize_effect',return_value=None):
            with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):vault.create()
        self.assertFalse((store.ROOT/'wallet-vault').exists())

    def test_real_dpapi_encrypted_backup_restore_and_tamper_rejection(self):
        with patch.object(approval,'require_operation'):
            public=vault.create('Fixture');pubkey=public['pubkey'];pair=vault._keypair(pubkey)
            secret=bytes(pair);encoded=vault._path(pubkey).read_bytes()
            self.assertTrue(secret not in encoded);self.assertTrue(secret[:32] not in encoded)
            from backend.platform_files import mode_matches
            self.assertTrue(mode_matches(vault._path(pubkey),0o600))
            self.assertEqual(str(vault._keypair(pubkey).pubkey()),pubkey)
            backup=self.root/'backup.ggwallet';vault.export_backup(pubkey,backup.as_uri(),'public-fixture-passphrase')
            self.assertTrue(secret not in backup.read_bytes());self.assertTrue(vault.status()[0]['backed_up'])
            self.assertEqual(vault.restore_backup(backup,'public-fixture-passphrase')['pubkey'],pubkey)
            for password in ('wrong-but-long-enough','short'):
                with self.assertRaisesRegex(ValueError,'INVALID_OR_WRONG_PASSWORD'):vault.restore_backup(backup,password)
            data=json.loads(backup.read_text());data['tag']=base64.b64encode(bytes(16)).decode();backup.write_text(json.dumps(data))
            before=vault._path(pubkey).read_bytes()
            with self.assertRaisesRegex(ValueError,'INVALID_OR_WRONG_PASSWORD'):vault.restore_backup(backup,'public-fixture-passphrase')
            self.assertEqual(vault._path(pubkey).read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'BACKUP_PATH'):vault.export_backup(pubkey,store.PROJECT/'bad-backup.ggwallet','public-fixture-passphrase')


class TransferTests(Isolated):
    def setUp(self, *, mock_authority=True):
        super().setUp()
        from solders.litesvm import LiteSVM
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.account import Account
        self.Pubkey=Pubkey;self.bank=LiteSVM().with_sigverify(True).with_blockhash_check(True)
        self.source=Keypair.from_seed(bytes(range(32)));self.recipient=Keypair.from_seed(bytes(range(32,64)));self.mint=str(Keypair.from_seed(bytes([71])*32).pubkey())
        self.bank.airdrop(self.source.pubkey(),10**9)
        self.source_id=store.account(tx.SOL,str(self.source.pubkey()),'Fixture source')
        self.recipient_id=store.account(tx.SOL,str(self.recipient.pubkey()),'Fixture recipient')
        self.asset=store.register_asset(tx.SOL,'token',self.mint,'TEST','Fixture six-decimal token',6,metadata='RPC_METADATA')
        mint_data=bytes([1,0,0,0])+bytes(self.source.pubkey())+(10**12).to_bytes(8,'little')+bytes([6,1])+bytes(36)
        self.bank.set_account(Pubkey.from_string(self.mint),Account(self.bank.minimum_balance_for_rent_exemption(82),mint_data,Pubkey.from_string(spl.TOKEN_PROGRAM)))
        self.source_ata=spl.derive_ata(str(self.source.pubkey()),self.mint)
        self.recipient_ata=spl.derive_ata(str(self.recipient.pubkey()),self.mint)
        token_data=bytes(Pubkey.from_string(self.mint))+bytes(self.source.pubkey())+(10**9).to_bytes(8,'little')+bytes(36)+b'\x01'+bytes(12)+bytes(8)+bytes(36)
        self.bank.set_account(Pubkey.from_string(self.source_ata),Account(self.bank.minimum_balance_for_rent_exemption(165),token_data,Pubkey.from_string(spl.TOKEN_PROGRAM)))
        self.sent=[];self.status_value='confirmed';self.ambiguous=False
        self.rpc_context_slot=self.bank.get_clock().slot+1000;self.finalized_slot=self.rpc_context_slot-100;self.finalized_height=100
        keys=[{'pubkey':str(k.pubkey()),'account_id':a,'chain_id':tx.SOL,'backed_up':True,'vault_available':True} for k,a in ((self.source,self.source_id),(self.recipient,self.recipient_id))]
        for target,value in [('status',lambda:keys),('_keypair',lambda pub:self.source if pub==str(self.source.pubkey()) else self.recipient)]:
            p=patch.object(vault,target,side_effect=value);p.start();self.addCleanup(p.stop)
        if mock_authority:
            p=patch.object(approval,'require_operation',return_value={'fixture':True});p.start();self.addCleanup(p.stop)
        p=patch.object(omni_rpc,'_json',side_effect=self.rpc);p.start();self.addCleanup(p.stop)

    def account_info(self,address):
        value=self.bank.get_account(self.Pubkey.from_string(address))
        return None if value is None else {'lamports':value.lamports,'owner':str(value.owner),'executable':value.executable,'data':[base64.b64encode(value.data).decode(),'base64']}

    def rpc(self,url,payload=None,**kwargs):
        from solders.transaction import VersionedTransaction
        from solders.transaction_metadata import FailedTransactionMetadata
        method=payload['method'];params=payload['params']
        if method=='getGenesisHash':result=tx.MAINNET_GENESIS
        elif method=='getBalance':result={'value':self.bank.get_balance(self.Pubkey.from_string(params[0])) or 0}
        elif method=='getAccountInfo':result={'value':self.account_info(params[0])}
        elif method=='getTokenAccountsByOwner':
            rows=[]
            for address,account in self.bank.get_program_accounts(self.Pubkey.from_string(spl.TOKEN_PROGRAM)):
                if len(account.data)==165 and account.data[:32]==bytes(self.Pubkey.from_string(params[1]['mint'])) and account.data[32:64]==bytes(self.Pubkey.from_string(params[0])):rows.append({'pubkey':str(address),'account':self.account_info(str(address))})
            result={'value':rows}
        elif method=='getLatestBlockhash':result={'value':{'blockhash':str(self.bank.latest_blockhash()),'lastValidBlockHeight':150}}
        elif method=='isBlockhashValid':result={'value':params[0]==str(self.bank.latest_blockhash())}
        elif method=='getMinimumBalanceForRentExemption':result=self.bank.minimum_balance_for_rent_exemption(params[0])
        elif method=='getFeeForMessage':result={'value':5000}
        elif method in {'simulateTransaction','sendTransaction'}:
            transaction=VersionedTransaction.from_bytes(base64.b64decode(params[0]))
            if method=='simulateTransaction':
                self.bank.with_sigverify(False)
                try:outcome=self.bank.simulate_transaction(transaction)
                finally:self.bank.with_sigverify(True)
                result={'value':{'err':'LOCAL_SVM_FAILED' if isinstance(outcome,FailedTransactionMetadata) else None}}
            else:
                self.assertTrue(all(transaction.verify_with_results()))
                self.sent.append(params[0]);outcome=self.bank.send_transaction(transaction)
                self.assertNotIsInstance(outcome,FailedTransactionMetadata,str(outcome))
                if self.ambiguous:raise TimeoutError('Fixture timeout after actual local acceptance')
                result=str(transaction.signatures[0])
        elif method=='getSignatureStatuses':result={'context':{'slot':self.rpc_context_slot},'value':[{'slot':self.bank.get_clock().slot,'confirmations':None if self.status_value=='finalized' else 1,'err':None,'confirmationStatus':self.status_value}]}
        elif method=='getSlot':result=self.finalized_slot
        elif method=='getBlockHeight':result=self.finalized_height
        else:raise AssertionError('Unexpected fixture RPC '+method)
        return {'jsonrpc':'2.0','id':1,'result':result}

    def prepare(self,amount='1.234567'):
        return tx.prepare(self.source_id,self.asset['id'],str(self.recipient.pubkey()),amount)

    def tokens(self,address):
        return spl.decode_token_account(self.account_info(address))['amount']

    def test_actual_signed_spl_round_trip_with_ata_creation_and_real_svm(self):
        forward=self.prepare();self.assertFalse(self.sent);self.assertEqual(forward['state'],'PREPARED');self.assertGreater(int(forward['body']['rent_lamports']),0)
        result=tx.send(forward['id'],forward['body']['review_digest']);self.assertEqual(result['state'],'SUBMITTED')
        self.assertEqual(self.tokens(self.recipient_ata),1234567);self.assertEqual(self.tokens(self.source_ata),10**9-1234567)
        self.assertEqual(tx.check(forward['id'])['state'],'CONFIRMED');self.status_value='finalized';self.assertEqual(tx.check(forward['id'])['state'],'FINALIZED')
        self.bank.airdrop(self.recipient.pubkey(),10**7);self.bank.expire_blockhash()
        back=tx.prepare(self.recipient_id,self.asset['id'],str(self.source.pubkey()),'0.234567')
        self.assertEqual(back['body']['rent_lamports'],'0')
        tx.send(back['id'],back['body']['review_digest'])
        self.assertEqual(self.tokens(self.recipient_ata),1000000);self.assertEqual(self.tokens(self.source_ata),10**9-1000000)
        self.assertEqual(len(self.sent),2)

    def test_missing_approval_expiry_review_mismatch_and_replay_do_not_send(self):
        draft=self.prepare();digest=draft['body']['review_digest']
        with patch.object(approval,'require_operation',side_effect=ValueError('WALLET_APPROVAL_REQUIRED')):
            with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):tx.send(draft['id'],digest)
        with self.assertRaisesRegex(ValueError,'REVIEW_MISMATCH'):tx.send(draft['id'],'changed')
        with patch.object(tx.time,'time',return_value=draft['body']['expires_at']+1):
            with self.assertRaisesRegex(ValueError,'DRAFT_EXPIRED'):tx.send(draft['id'],digest)
        self.assertFalse(self.sent);tx.send(draft['id'],digest)
        with self.assertRaisesRegex(ValueError,'REVIEW_MISMATCH'):tx.send(draft['id'],digest)
        self.assertEqual(len(self.sent),1)

    def test_accepted_but_timed_out_broadcast_keeps_signature_and_never_resigns(self):
        draft=self.prepare();self.ambiguous=True
        with self.assertRaisesRegex(ValueError,'BROADCAST_NOT_CONFIRMED'):tx.send(draft['id'],draft['body']['review_digest'])
        pending=tx.snapshot(draft['id']);self.assertEqual(pending['state'],'UNCERTAIN');self.assertTrue(pending['txid'])
        with self.assertRaisesRegex(ValueError,'PENDING_TRANSFER_CHECK_REQUIRED'):self.prepare()
        self.assertEqual(self.tokens(self.recipient_ata),1234567)
        self.assertEqual(tx.check(draft['id'])['state'],'CONFIRMED');self.assertEqual(len(self.sent),1)

    def test_precision_and_token_balance_errors_cannot_create_draft(self):
        for value in ('0','1.0000001','18446744073709551616','2000'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.prepare(value)
        self.assertFalse(tx.snapshot());self.assertFalse(self.sent)

    def test_genesis_requires_full_mainnet_hash_before_building_or_signing(self):
        for genesis in (tx.SOL.split(':')[1],tx.MAINNET_GENESIS[:-1]+'x','EtWTRABZaYq6iMfeYKouRu166VU2xqa1'):
            with self.subTest(genesis=genesis):
                with patch.object(omni_rpc,'_json',return_value={'jsonrpc':'2.0','id':1,'result':genesis}):
                    with self.assertRaisesRegex(ValueError,'WRONG_NETWORK'):self.prepare()
        self.assertFalse(tx.snapshot());self.assertFalse(self.sent)

    def test_native_transfer_and_read_only_legacy_boundary(self):
        draft=tx.prepare(self.source_id,tx.SOL+'/native:SOL',str(self.recipient.pubkey()),'0.01')
        self.assertEqual(draft['body']['rent_lamports'],'0');tx.send(draft['id'],draft['body']['review_digest'])
        self.assertEqual(self.bank.get_balance(self.recipient.pubkey()),10**7)
        with self.assertRaisesRegex(ValueError,'READ_ONLY'):omni_rpc.rpc(store.network(tx.SOL),'sendTransaction',[])

    def test_fragmented_spl_balance_transfers_from_two_real_token_accounts(self):
        from solders.account import Account
        from solders.keypair import Keypair
        second=str(Keypair.from_seed(bytes([91])*32).pubkey())
        source=self.bank.get_account(self.Pubkey.from_string(self.source_ata))
        data=source.data[:64]+(600000).to_bytes(8,'little')+source.data[72:]
        for address in (self.source_ata,second):
            self.bank.set_account(self.Pubkey.from_string(address),Account(source.lamports,data,source.owner))
        draft=self.prepare('1')
        self.assertEqual(draft['body']['source_token_account'],'')
        parts=draft['body']['source_token_accounts']
        self.assertEqual({part['address'] for part in parts},{self.source_ata,second})
        self.assertEqual(sorted(int(part['atomic']) for part in parts),[400000,600000])
        result=tx.send(draft['id'],draft['body']['review_digest'])
        self.assertEqual(result['state'],'SUBMITTED');self.assertEqual(len(self.sent),1)
        self.assertEqual(self.tokens(self.recipient_ata),1000000)
        self.assertEqual(self.tokens(self.source_ata)+self.tokens(second),200000)

    def test_fragment_limit_rejects_nine_sources_but_eight_really_execute(self):
        from solders.account import Account
        from solders.keypair import Keypair
        source=self.bank.get_account(self.Pubkey.from_string(self.source_ata))
        data=source.data[:64]+(100000).to_bytes(8,'little')+source.data[72:]
        addresses=[self.source_ata]+[str(Keypair.from_seed(bytes([seed])*32).pubkey()) for seed in range(92,100)]
        for address in addresses:
            self.bank.set_account(self.Pubkey.from_string(address),Account(source.lamports,data,source.owner))
        with self.assertRaisesRegex(ValueError,'FRAGMENTED_BALANCE_LIMIT'):self.prepare('0.9')
        self.assertFalse(tx.snapshot());self.assertFalse(self.sent)
        draft=self.prepare('0.8');self.assertEqual(len(draft['body']['source_token_accounts']),8)
        self.assertEqual(tx.send(draft['id'],draft['body']['review_digest'])['state'],'SUBMITTED')
        self.assertEqual(self.tokens(self.recipient_ata),800000)
        self.assertEqual(sum(self.tokens(address) for address in addresses),100000)

    def test_status_confirmed_during_broadcast_never_regresses_after_response_or_timeout(self):
        # The local SVM actually accepts the signed transaction before an
        # independent status poll wins the race with the send response.
        for delayed_response in ('success','malformed','timeout'):
            with self.subTest(delayed_response=delayed_response):
                self.bank.expire_blockhash();self.ambiguous=False
                draft=self.prepare('0.1');rpc=self.rpc
                def concurrent_check(url,payload=None,**kwargs):
                    if payload['method']!='sendTransaction':return rpc(url,payload,**kwargs)
                    response=rpc(url,payload,**kwargs)
                    self.assertEqual(tx.check(draft['id'])['state'],'CONFIRMED')
                    if delayed_response=='timeout':raise TimeoutError('Fixture delayed response after confirmation')
                    if delayed_response=='malformed':return {'jsonrpc':'2.0','id':1,'result':'wrong-fixture-signature'}
                    return response
                with patch.object(omni_rpc,'_json',side_effect=concurrent_check):
                    self.assertEqual(tx.send(draft['id'],draft['body']['review_digest'])['state'],'CONFIRMED')
                receipt=tx.snapshot(draft['id']);self.assertEqual(receipt['state'],'CONFIRMED');self.assertFalse(receipt['error'])
        self.assertEqual(len(self.sent),3)

    def test_finalized_receipt_cannot_be_downgraded_or_lose_signature(self):
        draft=self.prepare();receipt=tx.send(draft['id'],draft['body']['review_digest'])
        self.status_value='finalized';self.assertEqual(tx.check(draft['id'])['state'],'FINALIZED')
        for state in ('SIGNING','SUBMITTING','SUBMITTED','UNCERTAIN','CONFIRMED','FAILED'):
            with self.subTest(state=state):
                self.assertFalse(tx._update(draft['id'],state,receipt['txid'],'delayed stale result'))
                current=tx.snapshot(draft['id']);self.assertEqual(current['state'],'FINALIZED')
                self.assertEqual(current['txid'],receipt['txid']);self.assertFalse(current['error'])

    def test_interrupted_known_worker_recovers_prebroadcast_and_signed_ambiguity(self):
        first=self.prepare();second=self.prepare('0.2')
        with store.db(True) as db:
            # The process still exists, but neither row has an active sender.
            # This is deterministic and covers a known crashed worker without
            # assuming the operating system will never reuse an arbitrary PID.
            db.execute("UPDATE wallet_transfers SET state='SIGNING',worker_pid=?,worker_created=? WHERE id=?",
                       (os.getpid(),tx._PROCESS_CREATED,first['id']))
            db.execute("UPDATE wallet_transfers SET state='SUBMITTING',worker_pid=?,worker_created=?,txid=? WHERE id=?",
                       (os.getpid(),tx._PROCESS_CREATED,'fixture-public-signature',second['id']))
        before=tx.snapshot(first['id']);self.assertEqual(before['state'],'FAILED')
        self.assertEqual(before['error'],'WALLET_INTERRUPTED_BEFORE_BROADCAST');self.assertFalse(before['txid'])
        after=tx.snapshot(second['id']);self.assertEqual(after['state'],'UNCERTAIN')
        self.assertEqual(after['txid'],'fixture-public-signature');self.assertEqual(after['error'],'WALLET_BROADCAST_NOT_CONFIRMED')
        with self.assertRaisesRegex(ValueError,'PENDING_TRANSFER_CHECK_REQUIRED'):self.prepare()
        self.assertFalse(self.sent)

    def test_live_signing_worker_and_unknown_legacy_worker_are_not_recovered(self):
        live=self.prepare();legacy=self.prepare('0.2')
        with store.db(True) as db:
            db.execute("UPDATE wallet_transfers SET state='SIGNING',worker_pid=?,worker_created=? WHERE id=?",
                       (os.getpid(),tx._PROCESS_CREATED,live['id']))
            db.execute("UPDATE wallet_transfers SET state='SUBMITTING',txid=? WHERE id=?",('fixture-legacy-signature',legacy['id']))
        with tx._ACTIVE_LOCK:tx._ACTIVE.add(live['id'])
        try:
            self.assertEqual(tx.snapshot(live['id'])['state'],'SIGNING')
            self.assertEqual(tx.snapshot(legacy['id'])['state'],'SUBMITTING')
        finally:
            with tx._ACTIVE_LOCK:tx._ACTIVE.discard(live['id'])
        self.assertEqual(tx.snapshot(live['id'])['state'],'FAILED')
        self.assertEqual(tx.snapshot(legacy['id'])['state'],'SUBMITTING')
        self.assertFalse(self.sent)

    def test_malformed_signature_status_cannot_false_confirm(self):
        draft=self.prepare();receipt=tx.send(draft['id'],draft['body']['review_digest']);rpc=self.rpc
        malformed=(
            {'value':[]}, {'value':[None,None]}, {'value':['confirmed']},
            {'value':[{'confirmationStatus':'confirmed'}]},
            {'value':[{'slot':'invalid','confirmations':1,'err':None,'confirmationStatus':'confirmed'}]},
            {'value':[{'slot':1,'confirmations':True,'err':None,'confirmationStatus':'finalized'}]},
        )
        for response in malformed:
            with self.subTest(response=response):
                def invalid_status(url,payload=None,**kwargs):
                    if payload['method']=='getSignatureStatuses':return {'jsonrpc':'2.0','id':1,'result':{'context':{'slot':self.rpc_context_slot},**response}}
                    return rpc(url,payload,**kwargs)
                with patch.object(omni_rpc,'_json',side_effect=invalid_status):
                    with self.assertRaisesRegex(ValueError,'WALLET_RPC_ERROR'):tx.check(draft['id'])
                current=tx.snapshot(draft['id']);self.assertEqual(current['state'],'SUBMITTED')
                self.assertEqual(current['txid'],receipt['txid'])

    def dropped_before_acceptance(self):
        draft=self.prepare();rpc=self.rpc;calls=[]
        def dropped(url,payload=None,**kwargs):
            calls.append((url,payload))
            if payload['method']=='sendTransaction':raise TimeoutError('Fixture timeout before actual local acceptance')
            if payload['method']=='getSignatureStatuses':return {'jsonrpc':'2.0','id':1,'result':{'context':{'slot':self.rpc_context_slot},'value':[None]}}
            return rpc(url,payload,**kwargs)
        p=patch.object(omni_rpc,'_json',side_effect=dropped);p.start();self.addCleanup(p.stop)
        with self.assertRaisesRegex(ValueError,'BROADCAST_NOT_CONFIRMED'):tx.send(draft['id'],draft['body']['review_digest'])
        return draft,dropped,calls

    def test_absent_signature_expires_only_past_finalized_validity_window_with_fresh_history(self):
        draft,rpc,calls=self.dropped_before_acceptance();signed=tx.snapshot(draft['id'])
        self.assertEqual(signed['state'],'UNCERTAIN');self.assertTrue(signed['txid'])
        self.finalized_height=draft['body']['last_valid_block_height']
        self.assertEqual(tx.check(draft['id'])['state'],'UNCERTAIN')
        self.finalized_height+=1;self.bank.expire_blockhash();calls.clear()
        expired=tx.check(draft['id'])
        self.assertEqual(expired['state'],'FAILED');self.assertEqual(expired['error'],'WALLET_TRANSACTION_EXPIRED')
        self.assertEqual(expired['txid'],signed['txid']);self.assertFalse(self.sent)
        methods=[payload['method'] for _,payload in calls]
        self.assertEqual(methods,['getGenesisHash','getSignatureStatuses','getSlot','getBlockHeight','getSlot','getSignatureStatuses','getGenesisHash'])
        for url,payload in calls:
            self.assertEqual(url,draft['body']['rpc_endpoint'])
            if payload['method']=='getSignatureStatuses':self.assertTrue(payload['params'][1]['searchTransactionHistory'])
            if payload['method']=='getBlockHeight':self.assertEqual(payload['params'],[{'commitment':'finalized','minContextSlot':self.finalized_slot}])
        self.assertTrue(self.prepare('0.1'))
        with self.assertRaisesRegex(ValueError,'REVIEW_MISMATCH'):tx.send(draft['id'],draft['body']['review_digest'])

    def test_expiry_requires_valid_height_fresh_context_unchanged_endpoint_and_genesis(self):
        draft,rpc,calls=self.dropped_before_acceptance();signature=tx.snapshot(draft['id'])['txid']
        self.finalized_height=draft['body']['last_valid_block_height']+1
        network=store.network(tx.SOL)
        cases=('height_boundary','height_bool','height_negative','height_string','error_and_result','wrong_rpc_id','slot_bool','slot_regression',
            'stale_status','missing_context','boolean_context','wrong_genesis','rpc_failure','endpoint_drift')
        for case in cases:
            with self.subTest(case=case):
                counts={};current_network=dict(network)
                def invalid(url,payload=None,**kwargs):
                    method=payload['method'];counts[method]=counts.get(method,0)+1
                    if method=='getBlockHeight':
                        if case=='height_boundary':return {'jsonrpc':'2.0','id':1,'result':draft['body']['last_valid_block_height']}
                        if case in {'height_bool','height_negative','height_string'}:
                            return {'jsonrpc':'2.0','id':1,'result':{'height_bool':True,'height_negative':-1,'height_string':'151'}[case]}
                        if case=='error_and_result':return {'jsonrpc':'2.0','id':1,'result':self.finalized_height,'error':{}}
                        if case=='wrong_rpc_id':return {'jsonrpc':'2.0','id':True,'result':self.finalized_height}
                        if case=='rpc_failure':raise TimeoutError('Fixture unavailable finalized height')
                        if case=='endpoint_drift':current_network['endpoint']='https://changed.example/rpc'
                    if method=='getSlot':
                        if case=='slot_bool':return {'jsonrpc':'2.0','id':1,'result':True}
                        if case=='slot_regression' and counts[method]==2:return {'jsonrpc':'2.0','id':1,'result':self.finalized_slot-1}
                    if method=='getGenesisHash' and case=='wrong_genesis' and counts[method]==2:
                        return {'jsonrpc':'2.0','id':1,'result':tx.MAINNET_GENESIS[:-1]+'x'}
                    if method=='getSignatureStatuses' and counts[method]==2:
                        if case=='stale_status':return {'jsonrpc':'2.0','id':1,'result':{'context':{'slot':self.finalized_slot-1},'value':[None]}}
                        if case=='missing_context':return {'jsonrpc':'2.0','id':1,'result':{'value':[None]}}
                        if case=='boolean_context':return {'jsonrpc':'2.0','id':1,'result':{'context':{'slot':True},'value':[None]}}
                    return rpc(url,payload,**kwargs)
                with patch.object(omni_rpc,'_json',side_effect=invalid),patch.object(store,'network',side_effect=lambda *_:dict(current_network)):
                    if case=='height_boundary':self.assertEqual(tx.check(draft['id'])['state'],'UNCERTAIN')
                    else:
                        with self.assertRaises((ValueError,TimeoutError)):tx.check(draft['id'])
                state=tx.snapshot(draft['id']);self.assertEqual(state['state'],'UNCERTAIN');self.assertEqual(state['txid'],signature)
        self.assertFalse(self.sent)

    def test_expiry_cannot_overwrite_a_confirmed_or_finalized_race(self):
        for terminal in ('CONFIRMED','FINALIZED'):
            with self.subTest(terminal=terminal):
                draft,rpc,calls=self.dropped_before_acceptance();self.finalized_height=draft['body']['last_valid_block_height']+1
                signature=tx.snapshot(draft['id'])['txid'];reads=0
                def concurrent_confirmation(url,payload=None,**kwargs):
                    nonlocal reads
                    if payload['method']=='getSignatureStatuses':
                        reads+=1
                        if reads==2:
                            self.assertTrue(tx._update(draft['id'],'CONFIRMED',signature))
                            if terminal=='FINALIZED':self.assertTrue(tx._update(draft['id'],'FINALIZED',signature))
                    return rpc(url,payload,**kwargs)
                with patch.object(omni_rpc,'_json',side_effect=concurrent_confirmation):
                    result=tx.check(draft['id'])
                self.assertEqual(result['state'],terminal);self.assertEqual(result['txid'],signature);self.assertFalse(result['error'])
        self.assertFalse(self.sent)

    def test_fresh_history_confirmation_wins_and_legacy_binding_is_not_inferred(self):
        draft,rpc,calls=self.dropped_before_acceptance();self.finalized_height=draft['body']['last_valid_block_height']+1
        reads=0;signature=tx.snapshot(draft['id'])['txid']
        def found_after_height(url,payload=None,**kwargs):
            nonlocal reads
            if payload['method']=='getSignatureStatuses':
                reads+=1
                if reads==2:return self.rpc(url,payload,**kwargs)
            return rpc(url,payload,**kwargs)
        with patch.object(omni_rpc,'_json',side_effect=found_after_height):
            result=tx.check(draft['id'])
        self.assertEqual(result['state'],'CONFIRMED');self.assertEqual(result['txid'],signature)
        # Existing signed legacy records can still be checked. An absent
        # signature cannot acquire a missing endpoint/genesis binding later.
        legacy=self.prepare('0.1')
        with self.assertRaisesRegex(ValueError,'BROADCAST_NOT_CONFIRMED'):tx.send(legacy['id'],legacy['body']['review_digest'])
        body=dict(legacy['body']);body.pop('rpc_endpoint');body.pop('genesis_hash')
        with store.db(True) as db:db.execute('UPDATE wallet_transfers SET body=? WHERE id=?',(store.pack(body),legacy['id']))
        calls.clear();self.assertEqual(tx.check(legacy['id'])['state'],'UNCERTAIN')
        self.assertEqual([payload['method'] for _,payload in calls],['getGenesisHash','getSignatureStatuses'])
        self.assertFalse(self.sent)


class DiscoveryTests(Isolated):
    def test_both_programs_exact_balance_metadata_and_closed_accounts(self):
        from solders.keypair import Keypair
        owner=str(Keypair.from_seed(bytes([80])*32).pubkey());mint=str(Keypair.from_seed(bytes([81])*32).pubkey());token_account=str(Keypair.from_seed(bytes([82])*32).pubkey())
        account=store.account(tx.SOL,owner)
        def rpc(network,method,params):
            if method=='getGenesisHash':return tx.MAINNET_GENESIS
            if method=='getTokenAccountsByOwner':
                return {'value':[] if params[1]['programId']==discovery.TOKEN_2022 else [{'pubkey':token_account,'account':{'owner':discovery.TOKEN_PROGRAM,'data':{'parsed':{'type':'account','info':{'mint':mint,'owner':owner,'state':'initialized','tokenAmount':{'amount':str(2**53+1),'decimals':6}}}}}}]}
            if method=='getMultipleAccounts':
                if params[1]['encoding']=='base64':return {'value':[None]}
                return {'value':[{'owner':discovery.TOKEN_PROGRAM,'data':{'parsed':{'type':'mint','info':{'isInitialized':True,'decimals':6}}}}]}
            raise AssertionError(method)
        with patch.object(omni_rpc,'rpc',side_effect=rpc) as read:
            report=discovery.discover(account)
        self.assertEqual(len(report['asset_ids']),1)
        self.assertEqual(sum(call.args[1]=='getTokenAccountsByOwner' for call in read.call_args_list),2)
        with store.db() as db:before=json.loads(db.execute('SELECT body FROM observations WHERE account_id=?',(account,)).fetchone()[0])
        self.assertEqual(before['atomic'],str(2**53+1))
        with patch.object(omni_rpc,'rpc',side_effect=ValueError('OFFLINE')):
            with self.assertRaises(ValueError):discovery.discover(account)
        with store.db() as db:failed=json.loads(db.execute('SELECT body FROM observations WHERE account_id=?',(account,)).fetchone()[0])
        self.assertEqual(failed['atomic'],str(2**53+1));self.assertEqual(failed['quantity'],before['quantity'])
        self.assertEqual(failed['state'],'READ_FAILED');self.assertEqual(discovery.reports()[account]['state'],'READ_FAILED')
        def empty(network,method,params):return tx.MAINNET_GENESIS if method=='getGenesisHash' else {'value':[]}
        with patch.object(omni_rpc,'rpc',side_effect=empty):discovery.discover(account)
        with store.db() as db:self.assertEqual(json.loads(db.execute('SELECT body FROM observations WHERE account_id=?',(account,)).fetchone()[0])['atomic'],'0')

    def test_metaplex_name_is_bound_to_mint_and_metadata_program(self):
        from solders.keypair import Keypair
        mint=str(Keypair.from_seed(bytes([83])*32).pubkey())
        from solders.pubkey import Pubkey
        fields=b''.join(len(s).to_bytes(4,'little')+s for s in (b'Fixture',b'TEST',b'https://example.invalid/test'))
        raw=b'\x04'+bytes(32)+bytes(Pubkey.from_string(mint))+fields
        account={'owner':solana_metadata.PROGRAM,'data':[base64.b64encode(raw).decode(),'base64']}
        self.assertEqual(solana_metadata.decode(account,mint)['symbol'],'TEST')
        account['owner']=discovery.TOKEN_PROGRAM;self.assertEqual(solana_metadata.decode(account,mint),{})


if __name__=='__main__':unittest.main()
