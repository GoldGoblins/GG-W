"""Real signed test-token traffic in owned, short-lived loopback sessions only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import gg_lan_dag as lan
from backend import gg_lan_test_tokens as tokens


def child_worker(label):
    peer=lan.LanDagPeer(label,allow_test_tokens=True)
    try:
        print(json.dumps({'invite':peer.start_pairing()}),flush=True)
        for line in sys.stdin:
            request=json.loads(line);operation=request['op']
            if operation=='pin':peer.pin_coordinator(request['public_key']);result={'state':'PINNED'}
            elif operation=='create':result=peer.create_session(request['invites'],enable_test_tokens=True)
            elif operation=='distribute':result=peer.distribute_session(request['bundle'])
            elif operation=='send':result=peer.token_send(request['recipient'],request['amount'])
            elif operation=='circle':result=peer.start_token_circle(request.get('duration_ms',2000),request.get('batch',2),'1')
            elif operation=='circle_stop':result=peer.stop_token_circle()
            elif operation=='status':
                body=peer.snapshot();result={'pid':os.getpid(),'tokens':body['test_tokens'],'circle':body['token_circle'],
                    'financial_transactions':body['lan']['transactions_enabled'],'dag_finalized':body['canonical_finalized'],
                    'local_signers':sum(key is not None for key in peer._engine._producer_keys),
                    'account_signers':len(peer._engine._account_keys)}
            elif operation=='stop':
                peer.stop();result={'state':'STOPPED','owned_threads':sum(thread.name.startswith(('gg-lan-','gg-dag-')) for thread in threading.enumerate())}
                print(json.dumps(result),flush=True);break
            else:raise ValueError('GG_LAN_TOKEN_TEST_OPERATION')
            print(json.dumps(result),flush=True)
    finally:peer.stop()


class Child:
    def __init__(self,label):
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process=subprocess.Popen([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--peer',label],
            cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1,**options)
        self.messages=queue.Queue()
        def read():
            for line in self.process.stdout:
                try:self.messages.put(json.loads(line))
                except ValueError:self.messages.put({'error':'GG_LAN_TOKEN_TEST_NON_JSON'})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        self.invite=self.receive()['invite']
    def receive(self):
        try:return self.messages.get(timeout=5)
        except queue.Empty:raise AssertionError('Owned test-token child did not reply') from None
    def call(self,op,**values):
        self.process.stdin.write(json.dumps({'op':op,**values})+'\n');self.process.stdin.flush()
        return self.receive()
    def close(self):
        if self.process.poll() is None:
            try:self.call('stop')
            except (OSError,AssertionError):pass
            try:self.process.wait(3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(2)
        self.reader.join(1)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
            if stream is not None:stream.close()


class LanTokenTransportTests(unittest.TestCase):
    def paired(self,consent=(True,True,True),install=True):
        peers=[lan.LanDagPeer('owned-token-'+str(index),allow_test_tokens=value) for index,value in enumerate(consent)]
        for peer in peers:self.addCleanup(peer.stop);peer.start_pairing()
        for peer in peers[1:]:peer.pin_coordinator(peers[0].public_key)
        if install:
            bundle=peers[0].create_session([peer.public_invite() for peer in peers],enable_test_tokens=True)
            for peer in peers:peer.install_session(bundle)
        return peers

    def test_signed_opt_in_required_on_all_three_peers_and_default_stays_disabled(self):
        peers=self.paired((True,True,False),False)
        self.assertEqual(peers[0].public_invite()['body']['schema'],'gg.lan-dag.invite.v2')
        self.assertEqual(peers[2].public_invite()['body']['schema'],'gg.lan-dag.invite.v1')
        with self.assertRaisesRegex(ValueError,'ALL_PEERS_OPT_IN'):
            peers[0].create_session([peer.public_invite() for peer in peers],enable_test_tokens=True)
        bundle=peers[0].create_session([peer.public_invite() for peer in peers])
        for peer in peers:peer.install_session(bundle)
        self.assertFalse(peers[0].token_snapshot()['enabled'])
        with self.assertRaisesRegex(ValueError,'TOKENS_DISABLED'):peers[0].token_send(peers[1].public_key,'1')

    def test_token_session_binds_fixed_genesis_and_owner_only_signers(self):
        peers=self.paired();coordinator=peers[0]
        body=coordinator.snapshot()
        self.assertEqual(body['test_tokens']['symbol'],'GG-LAN(TEST)')
        self.assertEqual(sum(int(row['balance_atomic']) for row in body['test_tokens']['accounts']),3*int(tokens.ALLOCATION_ATOMIC))
        self.assertFalse(body['lan']['transactions_enabled']);self.assertEqual(body['canonical_finalized'],0)
        for peer in peers:
            self.assertEqual(sum(key is not None for key in peer._engine._producer_keys),2)
            self.assertEqual(peer._engine._account_keys,{})
        wrong=deepcopy(coordinator._bundle);wrong['body']['test_tokens']['allocation_atomic']='999999'
        wrong=lan._signed(coordinator._identity,lan._BUNDLE,wrong['body'])
        # Validate the descriptor independently against the signed fixed roster.
        roster=list(coordinator._roster.values())
        with self.assertRaisesRegex(ValueError,'TOKEN_GENESIS'):
            tokens.TestTokenLedger(coordinator._network,wrong['body']['test_tokens'],roster,coordinator.public_key,
                coordinator.public_key,coordinator._local_keys[0],coordinator._identity)

    def test_priority_stop_joins_circle_and_closes_only_owned_work(self):
        peers=self.paired();coordinator=peers[0]
        coordinator.start_token_circle(5000,2,'1')
        began=time.perf_counter();coordinator.request_stop();request_ms=(time.perf_counter()-began)*1000
        self.assertLess(request_ms,100)
        coordinator.stop()
        self.assertFalse(coordinator._circle_thread.is_alive())
        self.assertFalse(any(thread.name=='gg-lan-token-circle' for thread in threading.enumerate()))
        self.assertEqual(coordinator.snapshot()['token_circle']['state'],'STOPPED')

    def test_three_real_processes_send_and_close_actual_token_circles(self):
        peers=[Child(label) for label in ('owned-Windows','owned-Linux','owned-Termux')]
        for peer in peers:self.addCleanup(peer.close)
        coordinator=peers[0];public=coordinator.invite['body']['peer_key']
        for peer in peers[1:]:peer.call('pin',public_key=public)
        bundle=coordinator.call('create',invites=[peer.invite for peer in peers])
        distributed=coordinator.call('distribute',bundle=bundle)
        self.assertTrue(all(row['state']=='READY' for row in distributed),distributed)
        coordinator.call('send',recipient=peers[1].invite['body']['peer_key'],amount='1000000')
        peers[1].call('send',recipient=peers[2].invite['body']['peer_key'],amount='1000000')
        deadline=time.monotonic()+3
        while True:
            before=[peer.call('status') for peer in peers]
            if all(row['tokens']['sequence']==2 for row in before):break
            self.assertLess(time.monotonic(),deadline)
            time.sleep(.04)
        self.assertEqual(len({row['pid'] for row in before}),3)
        initial_balances=before[0]['tokens']['accounts']
        coordinator.call('circle',duration_ms=2200,batch=2)
        deadline=time.monotonic()+4
        while True:
            current=coordinator.call('status')
            if current['circle']['state']!='RUNNING':break
            self.assertLess(time.monotonic(),deadline)
            time.sleep(.04)
        result=current['circle']
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertTrue(result['all_peers_synced'],result)
        self.assertGreaterEqual(result['completed_rounds'],2)
        self.assertEqual(result['transactions'],result['completed_rounds']*3)
        self.assertGreater(result['tps'],0)
        after=[peer.call('status') for peer in peers]
        self.assertEqual(len({row['tokens']['head'] for row in after}),1)
        self.assertEqual(len({row['tokens']['state_root'] for row in after}),1)
        for row in after:
            self.assertEqual(row['local_signers'],2);self.assertEqual(row['account_signers'],0)
            self.assertFalse(row['financial_transactions']);self.assertEqual(row['dag_finalized'],0)
            for first,last in zip(initial_balances,row['tokens']['accounts']):
                self.assertEqual(first['peer_key'],last['peer_key']);self.assertEqual(first['balance_atomic'],last['balance_atomic'])
        self.assertEqual(len({row['sender_peer_key'] for row in after[0]['tokens']['receipts']}),3)
        for peer in peers:
            stopped=peer.call('stop');self.assertEqual(stopped['owned_threads'],0)
        print(json.dumps({'status':'PASS','scope':'THREE_OWNED_LOOPBACK_PROCESSES_ONE_HOST',
            'real_signed_transfers':result['transactions']+2,'closed_circles':result['completed_rounds'],
            'all_three_receipt_roots_match':True,'exact_supply_preserved':True,'dag_finalized':0,
            'physical_devices_validated':False,'work_ms':result['elapsed_ms'],'cleanup_ms':result['cleanup_ms']}))


class ParticipantCircleMetadataTests(unittest.TestCase):
    def test_active_participant_reports_observed_receipts_without_global_round_or_tps_claim(self):
        peers=[lan.LanDagPeer('metadata-'+str(index),allow_test_tokens=True) for index in range(3)]
        for peer in peers:self.addCleanup(peer.stop)
        coordinator,participant,_third=peers
        roster=[{'peer_key':peer.public_key,'producer_keys':[key.pubkey().hex() for key in peer._local_keys],
                 'label':peer.label} for peer in peers]
        descriptor=tokens.genesis(roster,coordinator.public_key)
        for peer in peers:
            peer._network='a'*64;peer._trusted=coordinator.public_key;peer._roster={row['peer_key']:row for row in roster}
            peer._tokens=tokens.TestTokenLedger(peer._network,descriptor,roster,coordinator.public_key,
                peer.public_key,peer._local_keys[0],peer._identity if peer is coordinator else None)
        before_coordinator=coordinator.snapshot()['token_circle']
        body={'schema':'gg.lan-test-token.circle.v1','network_id':participant._network,'run_id':'1'*64,
            'ring':[peer.public_key for peer in peers],'amount_atomic':'1','batch':1,'duration_ms':1000,
            'max_transfers':4096,'initial_sequence':0,'initial_head':participant._tokens.head_at(0)}
        plan=lan._signed(coordinator._identity,lan._CIRCLE,body)
        response=participant._token_command(coordinator.public_key,'CIRCLE_SIGN',{'plan':plan,'records':[],'count':1})
        current=participant.snapshot()['token_circle']
        self.assertEqual(current['state'],'RUNNING');self.assertEqual(current['role'],'PARTICIPANT')
        self.assertEqual(current['transactions'],0)  # Signed is not committed.
        participant._tokens.apply_receipts(coordinator._tokens.commit_batch(response['transactions']))
        current=participant.snapshot()['token_circle']
        self.assertEqual(current['transactions'],1)
        for unobserved in ('completed_rounds','tps','all_peers_synced'):
            self.assertNotIn(unobserved,current)
        self.assertEqual(coordinator.snapshot()['token_circle'],before_coordinator)
        with patch.object(lan.time,'monotonic',return_value=participant._token_plan['deadline']+.01):
            self.assertEqual(participant.snapshot()['token_circle']['state'],'EXPIRED')
        participant.stop_token_circle()
        self.assertNotEqual(participant.snapshot()['token_circle']['state'],'RUNNING')


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--peer':child_worker(sys.argv[2])
    else:unittest.main()
