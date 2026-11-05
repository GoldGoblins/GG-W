"""Abrupt owned-process failures with real encrypted SQLite and TCP recovery.

Loopback only. No user node, GUI process, public service or wallet is touched.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def worker(root,name,resume,node_role='producer'):
    from backend import gg_node_store as store,lan_dag_runtime as runtime,portable_wallet_vault as vault
    store.ROOT=Path(root);manager=runtime.LanDagRuntime()
    # Synthetic test protection only; real POSIX use obtains a private prompt.
    with vault.session('disposable-process-fixture-password'):
        try:
            if resume:manager.dispatch('lan.resume',{'profile':name})
            else:manager.dispatch('lan.start',{'profile':name,'label':name,'bind_host':'127.0.0.1','port':0,'allow_dag_transactions':True,'node_role':node_role})
            print(json.dumps({'invite':manager.dispatch('lan.invite')}),flush=True)
            for line in sys.stdin:
                request=json.loads(line);op=request['op']
                try:
                    peer=manager._owned()
                    if op=='command':result=manager.dispatch(request['command'],request.get('args',{}))
                    elif op=='block':
                        value=peer._engine.produce_lan_test_block(peer._local_indices[0],2,peer._wire_limit)
                        result={'sequence':json.loads(value['wire'])['body']['sequence']}
                    elif op=='crash':
                        commit=peer._profile._commit
                        crash_thread=threading.get_ident()
                        def interrupted_commit():
                            if threading.get_ident()!=crash_thread:return commit()
                            if request['after_commit']:commit()
                            os._exit(29)
                        peer._profile._commit=interrupted_commit
                        peer._engine.produce_lan_test_block(peer._local_indices[0],2,peer._wire_limit)
                        raise AssertionError('Crash fixture unexpectedly returned')
                    elif op=='status':
                        evidence=peer._engine.lan_evidence()
                        result={'evidence':evidence,'storage':peer._profile.snapshot(),
                            'local_indices':peer._local_indices,'cursors':peer._profile.cursors(),
                            'participation':peer.snapshot()['lan']['participation'],
                            'owned_slots':peer._roster[peer.public_key]['producer_indices'],
                            'owned_producer_signers':sum(key is not None for key in peer._engine._producer_keys),
                            'state':peer._node_snapshot()['state'],'canonical_finalized':peer.snapshot()['canonical_finalized']}
                    elif op=='stop':
                        manager.stop();print(json.dumps({'state':'STOPPED'}),flush=True);break
                    else:raise ValueError('GG_TEST_OPERATION')
                except Exception as error:
                    code=str(error);result={'error':code if code.startswith('GG_') and len(code)<=100 else type(error).__name__}
                # Keep command results bounded and public.
                if op=='command' and 'error' not in result:result={'state':'COMPLETE'}
                print(json.dumps(result),flush=True)
        finally:manager.stop()


class OwnedNode:
    def __init__(self,root,name,resume=False,node_role='producer'):
        self.name=name
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process=subprocess.Popen([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),
            '--worker',str(root),name,str(int(resume)),node_role],cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1,**options)
        self.messages=queue.Queue()
        def read():
            for line in self.process.stdout:
                try:self.messages.put(json.loads(line))
                except ValueError:self.messages.put({'error':'Non-JSON owned fixture output'})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:self.invite=self.receive()['invite']
        except BaseException:self.close();raise

    def send(self,op,**args):
        self.process.stdin.write(json.dumps({'op':op,**args})+'\n');self.process.stdin.flush()

    def receive(self):
        try:value=self.messages.get(timeout=15)
        except queue.Empty:raise AssertionError('Owned durable node did not reply') from None
        if 'error' in value:raise AssertionError('Owned durable node: '+value['error'])
        return value

    def call(self,op,**args):self.send(op,**args);return self.receive()

    def command(self,command,**args):return self.call('command',command=command,args=args)

    def close(self):
        if self.process.poll() is None:
            try:self.call('stop');self.process.wait(timeout=8)
            except (OSError,AssertionError,subprocess.TimeoutExpired):self.process.kill();self.process.wait(timeout=5)
        self.reader.join(2)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):stream.close()


class DurableProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-durable-process-');self.addCleanup(self.temp.cleanup)
        self.nodes=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for node in reversed(self.nodes):node.close()

    def node(self,name,resume=False,node_role='producer'):
        node=OwnedNode(Path(self.temp.name)/'nodes',name,resume,node_role);self.nodes.append(node);return node

    def converge(self,nodes,minimum):
        deadline=time.monotonic()+18
        while True:
            states=[node.call('status') for node in nodes]
            evidence=[state['evidence'] for state in states]
            if (min(row['blocks'] for row in evidence)>=minimum and
                    len({row['blockset_digest'] for row in evidence})==1 and len({row['state_root'] for row in evidence})==1):return states
            if time.monotonic()>=deadline:raise AssertionError('Owned durable nodes did not converge')
            time.sleep(.1)

    def test_coordinator_crash_on_each_side_of_commit_preserves_ownership_and_other_nodes_progress(self):
        nodes=[self.node('Node'+str(index)) for index in range(3)];coordinator=nodes[0]
        public=coordinator.invite['body']['peer_key'];original=coordinator.invite
        for node in nodes[1:]:
            node.command('lan.pin',public_key=public);coordinator.command('lan.peer_add',invite=node.invite)
        coordinator.command('lan.session_create',enable_dag_transactions=True,distribute=True)
        for node in nodes:node.call('block')
        first=self.converge(nodes,3)
        owner_index=first[0]['local_indices'][0]
        for after_commit in (False,True):
            prior=coordinator.call('status')['evidence']['producer_blocks'][owner_index]
            coordinator.send('crash',after_commit=after_commit)
            self.assertEqual(coordinator.process.wait(timeout=8),29)
            # No coordinator is alive. The other two actual local signers
            # continue producing and verifying through their real TCP lane.
            for node in nodes[1:]:node.call('block')
            other=self.converge(nodes[1:],3)
            coordinator=self.node('Node0',resume=True);nodes[0]=coordinator
            self.assertEqual(coordinator.invite,original)
            restored=coordinator.call('status')
            self.assertEqual(restored['evidence']['producer_blocks'][owner_index],prior+int(after_commit))
            self.assertEqual(restored['state'],'IDLE');self.assertTrue(restored['storage']['restored'])
            next_block=coordinator.call('block')
            self.assertEqual(next_block['sequence'],prior+int(after_commit)+1)
            all_states=self.converge(nodes,other[0]['evidence']['blocks']+1+int(after_commit))
            self.assertTrue(all(state['canonical_finalized']==0 for state in all_states))
            self.assertTrue(any(state['cursors'] for state in all_states))

    def test_real_full_replica_receives_without_a_producer_and_keeps_its_role_on_resume(self):
        a,b,replica=self.node('A'),self.node('B'),self.node('Replica',node_role='replica')
        for node in (b,replica):
            node.command('lan.pin',public_key=a.invite['body']['peer_key']);a.command('lan.peer_add',invite=node.invite)
        a.command('lan.session_create',enable_dag_transactions=True,distribute=True)
        a.call('block');b.call('block');states=self.converge([a,b,replica],2)
        state=states[2];self.assertEqual(state['owned_producer_signers'],0)
        self.assertFalse(state['participation']['producer']);self.assertTrue(state['participation']['replica'])
        self.assertFalse(state['participation']['light_client'])
        self.assertTrue(all(state['evidence']['producer_blocks'][i]==0 for i in state['owned_slots']))
        with self.assertRaisesRegex(AssertionError,'REPLICA_READ_ONLY'):replica.command('lan.dag_produce_start')
        replica.close();a.call('block');b.call('block')
        replica=self.node('Replica',resume=True);state=self.converge([a,b,replica],4)[2]
        self.assertEqual(state['owned_producer_signers'],0);self.assertEqual(state['participation']['role'],'replica')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(sys.argv[2],sys.argv[3],bool(int(sys.argv[4])),sys.argv[5])
    else:unittest.main()
