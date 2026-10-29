"""Bounded real LAN-protocol tests on owned loopback processes only.

No GUI, GPU, public listener, wallet seed, physical-device claim or throughput
benchmark. Production intervals are low and the three-process exchange is
limited to under two seconds before pause/cleanup.
"""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import gg_lan_dag as lan
from backend import gg_parallel_dag as dag


def peer_worker(label):
    peer=lan.LanDagPeer(label)
    try:
        print(json.dumps({'invite':peer.start_pairing()}),flush=True)
        for line in sys.stdin:
            request=json.loads(line);operation=request['op']
            if operation=='pin':peer.pin_coordinator(request['public_key']);result={'state':'PINNED'}
            elif operation=='announce':result=peer.announce_invite(request['coordinator'])
            elif operation=='candidates':result=peer.candidate_invites()
            elif operation=='create':result=peer.create_session(request['invites'])
            elif operation=='distribute':result=peer.distribute_session(request['bundle'])
            elif operation=='produce':peer.start_producing(interval_ms=1000);result={'state':'PRODUCING'}
            elif operation=='pause':peer.stop_producing();result={'state':'PAUSED'}
            elif operation=='status':
                body=peer.snapshot();result={'pid':os.getpid(),'network_id':body['lan']['network_id'],
                    'producer_count':body['producer_count'],'worker_count':body['worker_count'],
                    'producer_ids':sorted({row['proposer_index'] for row in body['block_graph']['blocks'] if row['rank']}),
                    'hashes':[row['hash'] for row in body['block_graph']['blocks']],
                    'local_indices':body['lan']['local_producer_indices'],
                    'local_signers':sum(key is not None for key in peer._engine._producer_keys),
                    'account_signers':len(peer._engine._account_keys),
                    'authenticated_peers':len(body['lan']['authenticated_peers']),
                    'canonical_finalized':body['canonical_finalized'],'physical_hosts_verified':body['lan']['physical_hosts_verified']}
            elif operation=='wires':
                records=[];cursor=0
                while True:
                    page=peer._engine.public_proposals(cursor,8)
                    if not page['records']:break
                    records.extend(base64.b64encode(row['wire']).decode('ascii') for row in page['records']);cursor=page['cursor']
                result={'wires':records}
            elif operation=='stop':
                peer.stop();result={'state':'STOPPED','remaining_owned_threads':sum(thread.name.startswith(('gg-lan-','gg-dag-')) for thread in threading.enumerate())}
                print(json.dumps(result),flush=True);break
            else:raise ValueError('GG_LAN_TEST_OPERATION')
            print(json.dumps(result),flush=True)
    finally:peer.stop()


class ChildPeer:
    def __init__(self,label):
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process=subprocess.Popen([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--peer',label],
            cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1,**options)
        self.messages=queue.Queue()
        def read():
            for line in self.process.stdout:
                try:self.messages.put(json.loads(line))
                except ValueError:self.messages.put({'error':'NON_JSON_CHILD_OUTPUT'})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        self.invite=self.receive()['invite']
    def receive(self):
        try:return self.messages.get(timeout=4)
        except queue.Empty:raise AssertionError('Owned loopback peer did not reply') from None
    def call(self,operation,**values):
        self.process.stdin.write(json.dumps({'op':operation,**values})+'\n');self.process.stdin.flush()
        return self.receive()
    def close(self):
        if self.process.poll() is None:
            try:self.call('stop')
            except (OSError,AssertionError):pass
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        self.reader.join(1)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
            if stream is not None:stream.close()


class LanDagTests(unittest.TestCase):
    def paired_fixture(self,install_receiver=True):
        peers=[lan.LanDagPeer('owned-'+str(index)) for index in range(3)]
        for peer in peers:self.addCleanup(peer.stop);peer.start_pairing()
        coordinator=peers[0]
        for peer in peers[1:]:peer.pin_coordinator(coordinator.public_key)
        bundle=coordinator.create_session([peer.public_invite() for peer in peers])
        if install_receiver:peers[2].install_session(bundle)
        return peers,bundle

    def test_public_pairing_imports_no_foreign_or_account_private_signers(self):
        peers,bundle=self.paired_fixture()
        receiver=peers[2];engine=receiver._engine
        self.assertLessEqual(len(dag.pack(bundle)),lan.MAX_BUNDLE)
        self.assertEqual(engine.snapshot()['producer_count'],6)
        self.assertEqual(engine.snapshot()['worker_count'],0)
        self.assertEqual(sum(key is not None for key in engine._producer_keys),2)
        self.assertEqual(engine._account_keys,{})
        public=engine.export_public_genesis();keyless=dag.ParallelDag.from_public_genesis(public);self.addCleanup(keyless.stop)
        self.assertFalse(keyless._can_produce);self.assertTrue(all(key is None for key in keyless._producer_keys))
        self.assertEqual(keyless._account_keys,{})
        foreign=next(index for index in range(6) if index not in receiver._local_indices)
        with self.assertRaisesRegex(ValueError,'NOT_OWNED'):
            engine._candidate(foreign,1,[public['genesis_hash']],engine._preview_root,[])
        with self.assertRaisesRegex(ValueError,'ACCOUNT_SIGNER_UNAVAILABLE'):
            engine.start_async_live(1,1,1000,producer_count=6)
        self.assertEqual(receiver.snapshot()['canonical_finalized'],0)

    def test_child_waits_for_actual_parent_and_orphan_credit_is_bounded(self):
        peers,bundle=self.paired_fixture();source_peer=peers[0];receiver=peers[2]
        roster=next(row for row in bundle['body']['roster'] if row['invite']['body']['peer_key']==source_peer.public_key)
        producer=roster['producer_indices'][0]
        source=dag.ParallelDag.from_public_genesis(bundle['body']['public_genesis']);self.addCleanup(source.stop)
        source.attach_local_producers({producer:source_peer._local_keys[0]})
        genesis=bundle['body']['public_genesis']['genesis_hash']
        parent=source._candidate(producer,1,[genesis],source._preview_root,[]);parent_id=source.admit(parent,producer)['hash']
        child=source._candidate(producer,2,[parent_id],source._preview_root,[])
        other=source._candidate(producer,3,[parent_id],source._preview_root,[])
        with patch.object(lan,'MAX_ORPHANS',1):
            self.assertEqual(receiver._ingest(child,source_peer.public_key),'PENDING_PARENTS')
            self.assertEqual(receiver.snapshot()['blocks_admitted'],0)
            self.assertEqual(receiver.snapshot()['lan']['orphan_count'],1)
            with self.assertRaisesRegex(ValueError,'ORPHAN_CREDIT'):receiver._ingest(other,source_peer.public_key)
            self.assertLessEqual(receiver.snapshot()['lan']['orphan_bytes'],lan.MAX_ORPHAN_BYTES)
        self.assertEqual(receiver._ingest(parent,source_peer.public_key),'ADMITTED_UNFINALIZED')
        value=receiver.snapshot();self.assertEqual(value['blocks_admitted'],2);self.assertEqual(value['lan']['orphan_count'],0)
        self.assertEqual(receiver._ingest(child,source_peer.public_key),'DUPLICATE')
        self.assertEqual(receiver.snapshot()['blocks_admitted'],2)
        edges=value['block_graph']['edges'];self.assertTrue(any(edge['from']==parent_id for edge in edges))

    def test_pins_domains_replay_and_oversize_frames_fail_closed(self):
        peers,bundle=self.paired_fixture();sender,unconfigured,receiver=peers
        wrong=deepcopy(bundle);wrong['body']['label']='changed'
        with self.assertRaises(ValueError):unconfigured.install_session(wrong)
        unconfigured.pin_coordinator(receiver.public_key)
        with self.assertRaises(ValueError):unconfigured.install_session(bundle)
        session='a'*64
        body={'schema':'gg.lan-dag.frame.v1','network_id':receiver._network,'session':session,'sequence':0,'kind':'PAGE','payload':{'after':0}}
        frame=lan._signed(sender._identity,lan._FRAME,body)
        self.assertEqual(receiver._check_frame(frame,len(dag.pack(frame)),sender.public_key,session,0)['kind'],'PAGE')
        with self.assertRaisesRegex(ValueError,'REPLAY_OR_DOMAIN'):receiver._check_frame(frame,len(dag.pack(frame)),sender.public_key,session,1)
        wrong_body={**body,'network_id':'0'*64};wrong_frame=lan._signed(sender._identity,lan._FRAME,wrong_body)
        with self.assertRaisesRegex(ValueError,'REPLAY_OR_DOMAIN'):receiver._check_frame(wrong_frame,len(dag.pack(wrong_frame)),sender.public_key,session,0)
        with self.assertRaisesRegex(ValueError,'UNKNOWN_PEER'):receiver._check_frame(frame,100,'f'*64,session,0)
        left,right=socket.socketpair()
        try:
            left.sendall(struct.pack('!I',lan.MAX_FRAME+1));right.settimeout(.1)
            with self.assertRaisesRegex(ValueError,'FRAME_SIZE'):lan._receive(right,lan.MAX_FRAME)
        finally:left.close();right.close()
        self.assertEqual(receiver.snapshot()['blocks_admitted'],0)

    def test_priority_stop_does_not_wait_for_peer_state_lock(self):
        peer=lan.LanDagPeer('held-lock');self.addCleanup(peer.stop);peer.start_pairing()
        entered=threading.Event();release=threading.Event()
        def hold():
            with peer._lock:entered.set();release.wait(1)
        holder=threading.Thread(target=hold);holder.start();self.assertTrue(entered.wait(1))
        began=time.monotonic();peer.request_stop();elapsed=time.monotonic()-began
        release.set();holder.join(1)
        self.assertLess(elapsed,.05)
        self.assertEqual(peer.stop()['lan']['state'],'STOPPED')

    def test_stop_during_public_import_never_commits_or_starts_producers(self):
        peers,bundle=self.paired_fixture(install_receiver=False);receiver=peers[2];receiver.auto_produce=True
        entered=threading.Event();release=threading.Event();errors=[]
        original=dag.ParallelDag.from_public_genesis
        def delayed(value):
            entered.set();release.wait(1);return original(value)
        def install():
            try:receiver.install_session(bundle)
            except ValueError as error:errors.append(str(error))
        with patch.object(dag.ParallelDag,'from_public_genesis',side_effect=delayed):
            worker=threading.Thread(target=install);worker.start();self.assertTrue(entered.wait(1))
            receiver.request_stop();release.set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,['GG_LAN_STOPPED'])
        self.assertIsNone(receiver._engine);self.assertIsNone(receiver._gossip)
        self.assertEqual(receiver.snapshot()['lan']['state'],'STOPPED')

    def test_stop_during_producer_start_cancels_replaced_live_event(self):
        peers,_bundle=self.paired_fixture();receiver=peers[2];engine=receiver._engine
        entered=threading.Event();release=threading.Event();errors=[];original=engine.start_async_live
        def delayed(*args,**kwargs):
            entered.set();release.wait(1);return original(*args,**kwargs)
        def start():
            try:receiver.start_producing(1000)
            except ValueError as error:errors.append(str(error))
        with patch.object(engine,'start_async_live',side_effect=delayed):
            worker=threading.Thread(target=start);worker.start();self.assertTrue(entered.wait(1))
            receiver.request_stop();release.set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,['GG_LAN_STOPPED'])
        self.assertFalse(engine.snapshot()['live']['enabled']);self.assertEqual(engine.snapshot()['live']['active_workers'],0)
        with self.assertRaisesRegex(ValueError,'STOPPED'):receiver.start_producing(1000)

    def test_pinning_cannot_change_trust_during_verified_import(self):
        peers,bundle=self.paired_fixture(install_receiver=False);receiver=peers[2]
        entered=threading.Event();release=threading.Event();pin_entered=threading.Event();errors=[]
        original=dag.ParallelDag.from_public_genesis
        def delayed(value):entered.set();release.wait(1);return original(value)
        def pin():
            pin_entered.set()
            try:receiver.pin_coordinator(peers[1].public_key)
            except ValueError as error:errors.append(str(error))
        with patch.object(dag.ParallelDag,'from_public_genesis',side_effect=delayed):
            installer=threading.Thread(target=receiver.install_session,args=(bundle,));installer.start();self.assertTrue(entered.wait(1))
            pinner=threading.Thread(target=pin);pinner.start();self.assertTrue(pin_entered.wait(1))
            release.set();installer.join(2);pinner.join(2)
        self.assertFalse(installer.is_alive());self.assertFalse(pinner.is_alive())
        self.assertEqual(errors,['GG_LAN_TRUST_ALREADY_BOUND']);self.assertEqual(receiver._trusted,bundle['body']['coordinator'])

    def test_deadlines_raw_credits_and_public_root_fail_closed(self):
        class Trickle:
            calls=0
            def settimeout(self,value):self.timeout=value
            def recv(self,count):self.calls+=1;return b'\0'
        trickle=Trickle();tick=iter(index*.1 for index in range(20))
        with patch.object(lan,'FRAME_SECONDS',.25),patch.object(lan.time,'monotonic',side_effect=lambda:next(tick)):
            with self.assertRaisesRegex(ValueError,'READ_DEADLINE'):lan._receive(trickle,lan.MAX_FRAME)
        self.assertLessEqual(trickle.calls,3)
        peer=lan.LanDagPeer('raw-credit');self.addCleanup(peer.stop)
        left,right=socket.socketpair()
        try:
            left.sendall(struct.pack('!I',lan.MAX_FRAME+1))
            with self.assertRaisesRegex(ValueError,'FRAME_SIZE'):peer._read(right,lan.MAX_FRAME)
            self.assertEqual(peer.snapshot()['lan']['traffic_bytes'],4)
        finally:left.close();right.close()
        peers,bundle=self.paired_fixture(install_receiver=False);changed=deepcopy(bundle['body'])
        changed['public_genesis']['accounts'][0]=dag.Keypair().pubkey().hex()
        changed['public_genesis']['accounts'].sort()
        signed=lan._signed(peers[0]._identity,lan._BUNDLE,changed)
        with self.assertRaisesRegex(ValueError,'PUBLIC_ROOT'):peers[2].install_session(signed)
        with patch.object(peers[2],'snapshot',side_effect=AssertionError('snapshot copied')):
            self.assertIsInstance(peers[2].telemetry_revision(),tuple)

    def test_invalid_orphan_cannot_turn_accepted_parent_into_failure(self):
        peers,bundle=self.paired_fixture();sender,receiver=peers[0],peers[2]
        producer=next(row['producer_indices'][0] for row in bundle['body']['roster'] if row['invite']['body']['peer_key']==sender.public_key)
        source=dag.ParallelDag.from_public_genesis(bundle['body']['public_genesis']);self.addCleanup(source.stop)
        source.attach_local_producers({producer:sender._local_keys[0]})
        parent=source._candidate(producer,1,[bundle['body']['public_genesis']['genesis_hash']],source._preview_root,[])
        parent_id=source.admit(parent,producer)['hash']
        child=json.loads(source._candidate(producer,2,[parent_id],source._preview_root,[]));child['body']['rank']+=3
        child['signature']=sender._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+dag.pack(child['body'])).hex()
        self.assertEqual(receiver._ingest(dag.pack(child),sender.public_key),'PENDING_PARENTS')
        self.assertEqual(receiver._ingest(parent,sender.public_key),'ADMITTED_UNFINALIZED')
        value=receiver.snapshot();self.assertEqual(value['blocks_admitted'],1)
        self.assertEqual(value['lan']['orphan_count'],0);self.assertEqual(value['lan']['rejected_frames'],1)

    def test_public_announcement_is_bounded_endpoint_checked_and_not_trust(self):
        peers,_bundle=self.paired_fixture(install_receiver=False);coordinator=peers[0];candidate=peers[1]
        self.assertEqual(candidate.announce_invite(coordinator.public_invite())['state'],'CANDIDATE')
        self.assertEqual(coordinator.candidate_invites(),[candidate.public_invite()]);self.assertIsNone(coordinator._engine)
        self.assertEqual(coordinator.snapshot()['lan']['configured_peers'],0)
        body={'schema':'gg.lan-dag.announce.v1','coordinator':coordinator.public_key,'invite':candidate.public_invite(),'nonce':'a'*64}
        signed=lan._signed(candidate._identity,lan._ANNOUNCE,body)
        with self.assertRaisesRegex(ValueError,'ANNOUNCE_ENDPOINT'):coordinator._receive_announcement(signed,'127.0.0.2')
        signed['body']['nonce']='b'*64
        with self.assertRaises(ValueError):coordinator._receive_announcement(signed,'127.0.0.1')
        peers[2].announce_invite(coordinator.public_invite());self.assertEqual(len(coordinator.candidate_invites()),2)
        extra=lan.LanDagPeer('extra',trusted_coordinator=coordinator.public_key);self.addCleanup(extra.stop);extra.start_pairing()
        with self.assertRaises((ValueError,OSError)):extra.announce_invite(coordinator.public_invite())
        self.assertEqual(len(coordinator.candidate_invites()),2)

    def test_three_owned_processes_exchange_six_real_producers_and_stop(self):
        children=[]
        try:
            children=[ChildPeer('loopback-'+str(index)) for index in range(3)]
            coordinator=children[0];public=coordinator.invite['body']['peer_key']
            for child in children[1:]:
                child.call('pin',public_key=public)
                self.assertEqual(child.call('announce',coordinator=coordinator.invite)['state'],'CANDIDATE')
            discovered=coordinator.call('candidates');self.assertEqual(len(discovered),2)
            bundle=coordinator.call('create',invites=[coordinator.invite,*discovered])
            result=coordinator.call('distribute',bundle=bundle)
            self.assertEqual([row['state'] for row in result],['READY','READY'])
            started=time.monotonic()
            for child in children:child.call('produce')
            deadline=started+1.4;states=[]
            while time.monotonic()<deadline:
                states=[child.call('status') for child in children]
                if all(value['producer_ids']==list(range(6)) and value['authenticated_peers']==2 for value in states):break
                time.sleep(.015)
            self.assertTrue(all(value['producer_ids']==list(range(6)) for value in states),states)
            for child in children:child.call('pause')
            deadline=started+1.85
            while time.monotonic()<deadline:
                states=[child.call('status') for child in children]
                if len({tuple(sorted(value['hashes'])) for value in states})==1:break
                time.sleep(.015)
            self.assertLess(time.monotonic()-started,2.0)
            self.assertEqual(len({value['pid'] for value in states}),3)
            self.assertEqual(len({value['network_id'] for value in states}),1)
            self.assertEqual(len({tuple(sorted(value['hashes'])) for value in states}),1)
            self.assertTrue(all(value['local_signers']==2 and value['account_signers']==0 for value in states))
            self.assertEqual(set().union(*(set(value['local_indices']) for value in states)),set(range(6)))
            self.assertTrue(all(value['canonical_finalized']==0 and not value['physical_hosts_verified'] for value in states))
            wires=coordinator.call('wires')['wires'];self.assertGreaterEqual(len(wires),6)
            for encoded in wires:
                wire=json.loads(base64.b64decode(encoded));body=wire['body'];producer=body['producer_index']
                dag._verify(bundle['body']['public_genesis']['genesis']['producers'][producer],b'GG-DAG-PROPOSAL-SIGN-v1\0'+dag.pack(body),wire['signature'])
                self.assertEqual(body['transactions'],[])
            for child in children:
                self.assertEqual(child.call('stop'),{'state':'STOPPED','remaining_owned_threads':0})
                child.process.wait(timeout=2);self.assertEqual(child.process.returncode,0)
            print(json.dumps({'status':'PASS','scope':'THREE_OWNED_LOOPBACK_PROCESSES_ONE_HOST','actual_producers':6,
                'local_private_producer_keys_each':2,'shared_real_proposals':len(wires),'canonical_finalized':0,
                'exchange_seconds':round(time.monotonic()-started,3),'physical_devices_validated':False,'owned_processes_stopped':True}))
        finally:
            for child in children:child.close()


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--peer':peer_worker(sys.argv[2])
    else:unittest.main()
