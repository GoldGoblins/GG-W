"""Real loopback transport across three owned processes, not three physical hosts."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(label):
    from backend.gg_lan_dag import LanDagPeer
    peer = LanDagPeer(label, '127.0.0.1', 0, allow_dag_transactions=True)
    try:
        print(json.dumps({'invite': peer.start_pairing(), 'pid': os.getpid()}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            try:
                operation = request['op']
                if operation == 'pin':
                    peer.pin_coordinator(request['coordinator'])
                    result = {'state': 'PINNED'}
                elif operation == 'create':
                    result = peer.create_session(request['invites'], enable_dag_transactions=True)
                    peer.install_session(result)
                elif operation == 'distribute':
                    result = peer.distribute_session(request['bundle'])
                elif operation == 'start':
                    peer.start_dag_stress(duration_ms=request.get('duration_ms',5000),
                                          transactions_per_block=request.get('transactions_per_block',2),
                                          interval_ms=request.get('interval_ms',250), remote=True)
                    result = {'state': 'START_REQUESTED'}
                elif operation == 'capacity':
                    peer._large_capacity()
                    result={'state':'CONFIGURED','wire_limit':peer._wire_limit}
                elif operation == 'block':
                    block=peer._engine.produce_lan_test_block(peer._local_indices[0],
                        request['transactions_per_block'],peer._wire_limit)
                    result={'state':'ADMITTED_UNFINALIZED','wire_bytes':len(block['wire'])}
                elif operation == 'hardware_probe':
                    result=peer._hardware_link_probe(time.monotonic()+5,threading.Event())
                elif operation == 'status':
                    body = peer.snapshot()
                    engine = peer._engine
                    result = {'pid': os.getpid(), 'state': body['lan']['state'],
                              'blocks': body['blocks_admitted'],
                              'transactions': body['transactions_validated'],
                              'canonical_finalized': body['canonical_finalized'],
                              'evidence': engine.lan_evidence(),
                              'stress': body['dag_stress'],
                              'transport': body['lan']['transport'],
                              'measurement_count': len(body.get('measurements', [])),
                              'last_measurement': body.get('last_wave', {}),
                              'owned_producer_signers': sum(key is not None for key in engine._producer_keys),
                              'owned_account_signers': sum(
                                  key is not None and key.pubkey().hex() in engine._addresses
                                  for key in engine._producer_keys),
                              'legacy_account_signers': len(engine._account_keys)}
                elif operation == 'stop':
                    peer.stop()
                    result = {'state': 'STOPPED', 'owned_threads': sum(
                        thread.name.startswith(('gg-lan-', 'gg-dag-'))
                        for thread in threading.enumerate())}
                    print(json.dumps(result), flush=True)
                    break
                else:
                    raise ValueError('GG_DAG_STRESS_TEST_OPERATION')
            except Exception as error:
                code = str(error)
                result = {'error': code if code.startswith('GG_') and len(code) <= 100 else type(error).__name__}
            print(json.dumps(result), flush=True)
    finally:
        peer.stop()


class OwnedProcess:
    def __init__(self, label):
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        self.process = subprocess.Popen(
            [sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--peer', label],
            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', bufsize=1, **options)
        self.messages = queue.Queue()

        def read():
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    self.messages.put({'error': 'Non-JSON test worker output'})

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.initial = self.receive()
        self.invite = self.initial['invite']
        self.stop_acknowledged = False

    def receive(self):
        try:
            result = self.messages.get(timeout=12)
        except queue.Empty:
            raise AssertionError('Owned DAG stress test worker did not reply') from None
        if isinstance(result, dict) and 'error' in result:
            raise AssertionError('Owned DAG stress worker: ' + result['error'])
        return result

    def call(self, operation, **values):
        self.process.stdin.write(json.dumps({'op': operation, **values}) + '\n')
        self.process.stdin.flush()
        result = self.receive()
        if operation == 'stop' and result.get('state') == 'STOPPED':
            self.stop_acknowledged = True
        return result

    def close(self):
        if self.process.poll() is None:
            if not self.stop_acknowledged:
                try:
                    self.call('stop')
                except (OSError, AssertionError):
                    pass
            try:
                self.process.wait(4)
            except subprocess.TimeoutExpired:
                # Only descendants of this test's own Popen may be cleaned up.
                # Windows venv launchers can own the actual interpreter child.
                import psutil
                try:
                    children = psutil.Process(self.process.pid).children(recursive=True)
                    for child in reversed(children):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    psutil.wait_procs(children, timeout=2)
                except psutil.NoSuchProcess:
                    pass
                self.process.kill()
                self.process.wait(2)
        self.reader.join(1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


class DagStressProcessTest(unittest.TestCase):
    def test_5000_tx_block_crosses_authenticated_chunks_and_all_three_verify(self):
        peers=[]
        try:
            for label in ('Large block sender','Large block verifier A','Large block verifier B'):
                peers.append(OwnedProcess(label))
            coordinator=peers[0]
            for peer in peers[1:]:peer.call('pin',coordinator=coordinator.invite['body']['peer_key'])
            bundle=coordinator.call('create',invites=[peer.invite for peer in peers])
            self.assertTrue(all(row['state']=='READY' for row in coordinator.call('distribute',bundle=bundle)))
            for peer in peers:peer.call('capacity')
            link=coordinator.call('hardware_probe')
            self.assertGreater(link['bytes_per_second'],0)
            self.assertEqual(link['peer_samples'],2)
            baseline=[peer.call('status')['transport']['counters']['failures'] for peer in peers]
            block=coordinator.call('block',transactions_per_block=5000)
            self.assertGreater(block['wire_bytes'],64*1024)
            until=time.monotonic()+30
            while True:
                states=[peer.call('status') for peer in peers]
                if all(row['transactions']==5000 for row in states):break
                self.assertLess(time.monotonic(),until,'Real chunked block did not converge')
                time.sleep(.1)
            for field in ('blocks','transactions','blockset_digest','state_root','producer_blocks','producer_transactions'):
                self.assertTrue(all(row['evidence'][field]==states[0]['evidence'][field] for row in states),field)
            for index,row in enumerate(states):
                self.assertEqual(row['canonical_finalized'],0)
                self.assertFalse(row['evidence']['protocol_fault'])
                self.assertEqual(row['transport']['counters']['failures'],baseline[index],row['transport'])
            print(json.dumps({'scope':'THREE_OWNED_LOOPBACK_PROCESSES_NOT_PHYSICAL_HOSTS',
                'transactions_per_block':5000,'wire_bytes':block['wire_bytes'],'shared_verified_blocks':1,
                'shared_verified_transactions':5000,'new_transport_failures':0,'canonical_finalized':0}),flush=True)
        finally:
            for peer in reversed(peers):peer.close()

    def test_high_payload_profiles_use_real_transport_and_shared_ack(self):
        for transactions_per_block in (8, 32, 64, 128):
            with self.subTest(transactions_per_block=transactions_per_block):
                peers = []
                try:
                    for label in ('Windows profile fixture', 'Linux profile fixture', 'Termux profile fixture'):
                        peers.append(OwnedProcess(label))
                    coordinator = peers[0]
                    for peer in peers[1:]:
                        peer.call('pin', coordinator=coordinator.invite['body']['peer_key'])
                    bundle = coordinator.call('create', invites=[peer.invite for peer in peers])
                    distribution = coordinator.call('distribute', bundle=bundle)
                    self.assertTrue(all(row['state'] == 'READY' for row in distribution))
                    baseline = [peer.call('status')['transport']['counters']['failures'] for peer in peers]
                    coordinator.call('start', duration_ms=10000,
                                     transactions_per_block=transactions_per_block, interval_ms=1000)
                    deadline = time.monotonic() + 14
                    while True:
                        result = coordinator.call('status')
                        if result['stress']['state'] not in ('STARTING', 'RUNNING', 'STOPPING'):
                            break
                        self.assertLess(time.monotonic(), deadline, 'Owned stress did not terminate')
                        time.sleep(.2)
                    stress = result['stress']
                    diagnostic = {key: stress.get(key) for key in
                                  ('state', 'last_error', 'failure_phase', 'phase_ms', 'status_polls')}
                    self.assertEqual(stress['state'], 'COMPLETE', json.dumps(diagnostic))
                    self.assertTrue(stress['all_peers_synced'])
                    self.assertGreater(stress['acknowledged_transactions'], 0)
                    self.assertEqual(stress['transactions'], stress['blocks'] * transactions_per_block)
                    self.assertEqual(stress['acknowledged_transactions'], stress['transactions'])
                    self.assertEqual(stress['acknowledged_blocks'], stress['blocks'])
                    states = [peer.call('status') for peer in peers]
                    for field in ('chain_id', 'blocks', 'transactions', 'blockset_digest',
                                  'state_root', 'producer_blocks', 'producer_transactions'):
                        self.assertTrue(all(row['evidence'][field] == states[0]['evidence'][field]
                                            for row in states), 'Shared evidence differs: ' + field)
                    for index, row in enumerate(states):
                        self.assertFalse(row['evidence']['protocol_fault'])
                        self.assertEqual(row['canonical_finalized'], 0)
                        self.assertEqual(row['owned_producer_signers'], 2)
                        self.assertTrue(all(count > 0 for count in row['evidence']['producer_blocks']))
                        self.assertEqual(row['last_measurement']['transactions'], transactions_per_block)
                        self.assertEqual(row['transport']['counters']['failures'], baseline[index])
                    print(json.dumps({'scope': 'THREE_OWNED_LOOPBACK_PROCESSES_NOT_PHYSICAL_HOSTS',
                                      'transactions_per_block': transactions_per_block,
                                      'state': stress['state'], 'acknowledged_blocks': stress['acknowledged_blocks'],
                                      'acknowledged_transactions': stress['acknowledged_transactions'],
                                      'new_transport_failures': 0}), flush=True)
                    for peer in peers:
                        self.assertEqual(peer.call('stop')['owned_threads'], 0)
                finally:
                    for peer in reversed(peers):
                        peer.close()

    def test_actual_three_process_dag_payloads_converge_and_stop(self):
        peers = []
        try:
            for label in ('DAG Windows fixture', 'DAG Linux fixture', 'DAG Termux fixture'):
                peers.append(OwnedProcess(label))
            self.assertEqual(len({peer.initial['pid'] for peer in peers}), 3)
            coordinator = peers[0]
            for peer in peers[1:]:
                peer.call('pin', coordinator=coordinator.invite['body']['peer_key'])
            bundle = coordinator.call('create', invites=[peer.invite for peer in peers])
            distribution = coordinator.call('distribute', bundle=bundle)
            self.assertTrue(all(row['state'] == 'READY' for row in distribution))
            for peer in peers:
                status = peer.call('status')
                self.assertEqual(status['owned_producer_signers'], 2)
                self.assertEqual(status['owned_account_signers'], 2)
                self.assertEqual(status['legacy_account_signers'], 0)
                self.assertEqual(status['transactions'], 0)
            coordinator.call('start')
            deadline = time.monotonic() + 12
            while True:
                result = coordinator.call('status')
                if result['stress']['state'] not in ('STARTING', 'RUNNING', 'STOPPING'):
                    break
                if time.monotonic() >= deadline:
                    self.fail('Bounded DAG stress did not terminate')
                time.sleep(.25)
            stress = result['stress']
            self.assertEqual(stress['state'], 'COMPLETE',
                             'DAG stress failed: ' + str(stress.get('last_error', '')))
            self.assertTrue(stress['all_peers_synced'])
            self.assertGreater(stress['acknowledged_transactions'], 0)
            self.assertEqual(stress['transactions'], stress['acknowledged_transactions'])
            states = [peer.call('status') for peer in peers]
            self.assertTrue(len({state['evidence']['blockset_digest'] for state in states}) == 1,
                            'Different real admitted block sets')
            self.assertTrue(len({state['evidence']['state_root'] for state in states}) == 1,
                            'Different deterministic preview states')
            self.assertTrue(len({state['transactions'] for state in states}) == 1)
            self.assertTrue(all(state['canonical_finalized'] == 0 for state in states))
            self.assertTrue(all(not state['evidence']['protocol_fault'] for state in states))
            self.assertTrue(all(count > 0 for count in states[0]['evidence']['producer_blocks']),
                            'All six independently owned producers must contribute real blocks')
            self.assertTrue(all(state['measurement_count'] > 0 for state in states))
            self.assertTrue(all(state['last_measurement']['transactions'] == 2 for state in states))
            self.assertTrue(all(state['last_measurement']['total_ms'] >= 0 for state in states))
            self.integration_report = {
                'scope': 'THREE_SEPARATE_WINDOWS_LOOPBACK_PROCESSES_NOT_PHYSICAL_HOSTS',
                'participants': 3, 'producer_identities_with_real_blocks': 6,
                'requested_duration_ms': 5000, 'transactions_per_block': 2, 'interval_ms': 250,
                'state': stress['state'], 'elapsed_ms': stress['elapsed_ms'],
                'acknowledged_blocks': stress['acknowledged_blocks'],
                'acknowledged_transactions': stress['acknowledged_transactions'],
                'acknowledged_bps': stress['acknowledged_bps'],
                'acknowledged_tps': stress['acknowledged_tps'],
                'all_peers_synced': stress['all_peers_synced'],
                'stop_reason': stress['stop_reason'], 'last_error': stress['last_error'],
                'actual_timing_measurements_present_on_all_peers': True,
                'canonical_finalized': 0, 'hardware_capacity_measured': False,
            }
            for peer in peers:
                stopped = peer.call('stop')
                self.assertEqual(stopped['owned_threads'], 0)
        finally:
            for peer in reversed(peers):
                peer.close()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--peer':
        worker(sys.argv[2])
    else:
        unittest.main()
