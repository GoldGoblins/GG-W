"""Explicit read-only public probes and temporary local CRYPTO integration checks.

Run from the app environment. No real wallet, imported key, trade or mainnet
transaction is used. A lab that was already running is not stopped.
"""
from pathlib import Path
import base64
import json
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import crypto_connections as connections, crypto_svm as vm
from backend import crypto_contract as C, kaspa_contract as K, kaspa_node, kaspa_covenant, kaspa_address


def verify():
    sol=connections._probe('SOL','mainnet','')
    kas=connections._probe('KAS','mainnet',kaspa_address.encode('kaspa',bytes(32)))
    assert sol['healthy'] and kas['healthy'] and 'balance_sompi' in kas
    was_running=kaspa_node.running_pid() is not None
    try:
        lab=kaspa_node.start()
        assert lab['healthy'],lab.get('diagnostic')
        dag=kaspa_node.rpc('getBlockDagInfo')
        assert dag['network']=='simnet'
        balance=kaspa_node.rpc('getBalanceByAddress',{'address':kaspa_address.encode('kaspasim',bytes(32))})
        assert int(balance['balance'])>=0
    finally:
        if not was_running: kaspa_node.stop()
    with tempfile.TemporaryDirectory(prefix='gg-crypto-integration-') as raw,patch.object(C,'STATE_DIR',Path(raw)/'sol'),patch.object(K,'STATE_DIR',Path(raw)/'kas'):
        compiled=kaspa_covenant.compile_counter()
        assert compiled['compiled'] and compiled['bytecode_bytes']>0
        from solders.keypair import Keypair
        from solders.hash import Hash
        from solders.system_program import transfer
        from solders.message import Message
        from solders.transaction import VersionedTransaction
        try:
            vm.start()
            payer,recipient=Keypair(),Keypair()
            assert 'result' in vm.rpc('requestAirdrop',[str(payer.pubkey()),100*10**9])
            blockhash=vm.rpc('getLatestBlockhash',[])['result']['value']['blockhash']
            tx=VersionedTransaction(Message.new_with_blockhash([transfer({'from_pubkey':payer.pubkey(),'to_pubkey':recipient.pubkey(),'lamports':10**9})],payer.pubkey(),Hash.from_string(blockhash)),[payer])
            encoded=base64.b64encode(bytes(tx)).decode()
            assert vm.rpc('simulateTransaction',[encoded])['result']['value']['err'] is None
            assert vm.rpc('getBalance',[str(recipient.pubkey())])['result']['value']==0
            sent=vm.rpc('sendTransaction',[encoded]); assert 'result' in sent
            assert vm.rpc('getBalance',[str(recipient.pubkey())])['result']['value']==10**9
            vm.stop(); vm.start()
            assert vm.rpc('getBalance',[str(recipient.pubkey())])['result']['value']==10**9
        finally: vm.stop()
    return dict(status='PASS', sol_live=dict(healthy=True,endpoint=sol['endpoint'],latency_ms=sol['latency_ms']),
                kas_live=dict(healthy=True,endpoint=kas['endpoint'],watch_balance_read=True,latency_ms=kas['latency_ms']),
                kas_local=dict(node_version=kaspa_node.VERSION,network='simnet',healthy=True,balance_read=True,compiler_bytes=compiled['bytecode_bytes']),
                sol_local=dict(backend='LiteSVM 0.29.0',signed_transfer=True,simulation_non_mutating=True,persisted_after_restart=True),
                mainnet_transactions=0, real_wallets_used=False, covenant_execution='PAPER_ONLY')


if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=True))
