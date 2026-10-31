"""Actual per-user public CLI/Desktop observation boundaries, without a GUI."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from backend import local_node_observation as observation


def body(label='Linux'):
    return {'state':'RUNNING','chain_id':'fixture-chain','producer_count':6,
            'blocks_admitted':3,'transactions_validated':48,
            'lan':{'scope':'PRIVATE_LAN_SESSION_EXPERIMENT','label':label,
                   'connection_state':'CONNECTED','authenticated_peers':[{'label':'Windows'}]},
            'lan_setup':{'active':True,'coordinator':False,'invites':[],
                         'allow_dag_transactions':True,'bootstrap':{'unneeded':'public'}},
            'block_graph':{'source':'LAN_SIGNED_PROPOSAL_DAG','blocks':[],
                           'producer_identities':[{'index':0,'display_name':label+' · 1'}],
                           'metrics':{'bps':2,'tps':32},'stale':False},
            'test_accounts':[{'address':'public-test-account','balance_atomic':'999999999999999999','nonce':7}]}


class LocalObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/'observations'

    def publisher(self):
        value=observation.Publisher(self.root);self.addCleanup(value.close);return value

    def test_idle_reader_creates_no_directory_or_node(self):
        reader=observation.Reader(self.root)
        self.assertIsNone(reader.snapshot());self.assertEqual(reader.telemetry_revision(),())
        self.assertFalse(self.root.exists())

    def test_real_public_status_roundtrip_keeps_account_and_graph_from_one_node(self):
        publisher=self.publisher();source=body();publisher.publish(source)
        reader=observation.Reader(self.root);result=reader.snapshot()
        self.assertEqual(result['chain_id'],source['chain_id'])
        self.assertEqual(result['test_accounts'],source['test_accounts'])
        self.assertEqual(result['block_graph'],source['block_graph'])
        self.assertEqual(result['transactions_validated'],48)
        self.assertTrue(result['observation']['read_only'])
        self.assertFalse(result['observation']['stale'])
        self.assertEqual(result['observation']['source'],'LOCAL_CLI')
        self.assertNotIn('bootstrap',result['lan_setup'])
        self.assertFalse(any(self.root.glob('*.tmp')))
        if os.name!='nt':self.assertEqual(publisher.path.stat().st_mode&0o777,0o600)

    def test_no_wallet_or_secret_material_can_enter_published_node_status(self):
        publisher=self.publisher();value=body()
        value['wallet']={'mnemonic':'excluded fixture words'}
        publisher.publish(value)
        self.assertNotIn('wallet',json.loads(publisher.path.read_bytes())['body'])
        publisher.close();value=body();value['test_accounts'][0]['private_key']='fixture-only'
        with self.assertRaisesRegex(ValueError,'PRIVATE_FIELD'):publisher.publish(value)
        self.assertFalse(publisher.path.exists())

    def test_stale_data_is_explicit_and_never_still_reports_connected(self):
        publisher=self.publisher();publisher.publish(body());packet=json.loads(publisher.path.read_bytes())
        with patch.object(observation.time,'monotonic',return_value=packet['published_monotonic']+6):
            reader=observation.Reader(self.root)
            # A reader that was already attached retains its exact source only.
            reader._packet=packet
            result=reader.snapshot()
        self.assertTrue(result['observation']['stale'])
        self.assertTrue(result['block_graph']['stale'])
        self.assertEqual(result['lan']['connection_state'],'STALE')
        self.assertEqual(result['lan']['authenticated_peers'],[])

    def test_dead_or_reused_pid_is_not_a_live_node(self):
        publisher=self.publisher();publisher.publish(body())
        packet=json.loads(publisher.path.read_bytes());packet['process_started']-=100
        publisher.path.write_text(json.dumps(packet),encoding='utf-8')
        self.assertIsNone(observation.Reader(self.root).snapshot())

    def test_two_active_nodes_never_select_the_wrong_account_implicitly(self):
        first=self.publisher();second=self.publisher()
        first.publish(body('First'));second.publish(body('Second'))
        self.assertIsNone(observation.Reader(self.root).snapshot())
        first.close()
        self.assertEqual(observation.Reader(self.root).snapshot()['lan']['label'],'Second')

    def test_cleanup_does_not_remove_another_owners_status(self):
        first=self.publisher();second=self.publisher()
        first.publish(body('First'));second.publish(body('Second'));first.close()
        self.assertFalse(first.path.exists());self.assertTrue(second.path.exists())

    def test_oversized_and_invalid_status_is_not_read(self):
        publisher=self.publisher();publisher.publish(body());publisher.path.write_bytes(b'x'*(observation.MAX_BYTES+1))
        self.assertIsNone(observation.Reader(self.root).snapshot())
        publisher.path.write_text('{broken',encoding='utf-8')
        self.assertIsNone(observation.Reader(self.root).snapshot())

    def test_observation_stops_when_cli_explicitly_stops_its_peer(self):
        publisher=self.publisher();publisher.publish(body());value=body();value['lan_setup']['active']=False
        publisher.publish(value)
        self.assertFalse(publisher.path.exists());self.assertIsNone(observation.Reader(self.root).snapshot())

    def test_status_publishing_is_bounded_and_does_not_mutate_original(self):
        publisher=self.publisher();value=body();original=deepcopy(value)
        publisher.publish(value);first=publisher.path.read_bytes();publisher.publish(value)
        self.assertEqual(publisher.path.read_bytes(),first);self.assertEqual(value,original)
        value['events']=['x'*observation.MAX_BYTES]
        with patch.object(observation.time,'monotonic',return_value=publisher._last_publish+1):
            with self.assertRaisesRegex(ValueError,'SIZE'):publisher.publish(value)
        self.assertEqual(publisher.path.read_bytes(),first)

    def test_desktop_telemetry_uses_the_existing_cli_source_without_starting_node(self):
        from backend import network_telemetry,lan_dag_runtime,local_node_observation
        publisher=self.publisher();publisher.publish(body());reader=observation.Reader(self.root)
        with patch.object(lan_dag_runtime,'active_manager',return_value=None), \
             patch.object(local_node_observation,'active_source',return_value=reader):
            source=network_telemetry.dag_source();packet=network_telemetry.observe('DAG')
        self.assertIs(source,reader)
        self.assertEqual(packet['parallel_dag']['transactions_validated'],48)
        self.assertTrue(packet['parallel_dag']['observation']['read_only'])

    def test_actual_foreground_cli_publishes_its_owned_node_for_desktop(self):
        base=Path(self.temporary.name)
        env=dict(os.environ,GG_TERMINAL_STATE_ROOT=str(base/'state'),
                 GG_TERMINAL_DATA_ROOT=str(base/'data'),XDG_DATA_HOME=str(base/'shared'),
                 GG_DATA_HOME=str(base/'windows'),PYTHONDONTWRITEBYTECODE='1')
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        process=subprocess.Popen([sys.executable,'-X','utf8','-B','gg-cli.py','--foreground','--command',
            'lan.start label=CLI-bridge-fixture bind_host=127.0.0.1 port=0 allow_dag_transactions=true auto_produce=false'],
            cwd=Path(__file__).resolve().parents[1],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,**options)
        result=None
        try:
            reader=observation.Reader(base/'shared/goldgoblins/node-observations')
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                result=reader.snapshot()
                if result is not None:break
                if process.poll() is not None:
                    self.fail('Owned CLI exited: '+process.stderr.read(2048).decode('utf-8',errors='replace'))
                time.sleep(.1)
            self.assertIsNotNone(result,'CLI did not publish its own public node status')
            self.assertEqual(result['lan']['label'],'CLI-bridge-fixture')
            self.assertEqual(result['observation']['source'],'LOCAL_CLI')
            self.assertTrue(result['observation']['read_only'])
            self.assertEqual(result['lan']['state'],'PAIRING')
            self.assertEqual(result['transactions_validated'] if 'transactions_validated' in result else 0,0)
        finally:
            import psutil
            try:children=psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:children=[]
            for child in reversed(children):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=4)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
            _,alive=psutil.wait_procs(children,timeout=2)
            for child in alive:
                try:child.kill()
                except psutil.NoSuchProcess:pass
            process.stderr.close()
        self.assertIsNone(observation.Reader(base/'shared/goldgoblins/node-observations').snapshot())


if __name__=='__main__':unittest.main()
