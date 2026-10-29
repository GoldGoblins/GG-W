"""Offline profile truth, headless CLI parity and owned foreground lifetime."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from backend import network_profiles as profiles

ROOT=Path(__file__).resolve().parents[1]


def configuration(name):
    return {'profile':name,'chain_id':'fixture-'+name.lower(),
            'genesis_hash':('1' if name=='TESTNET' else '2')*64,
            'transaction_domain':'FIXTURE-'+name+'-TX',
            'block_domain':'FIXTURE-'+name+'-BLOCK','role':'observer',
            'bind_address':'127.0.0.1:16111','seed_peers':['127.0.0.1:16112']}


class NetworkProfileDescriptors(unittest.TestCase):
    def test_unconfigured_testnet_and_mainnet_are_distinct_and_never_fake_ready(self):
        result=profiles.snapshot()
        self.assertEqual(result['schema'],'gg.network-profiles.v1')
        self.assertEqual([row['profile'] for row in result['profiles']],['TESTNET','MAINNET'])
        for row in result['profiles']:
            self.assertEqual(row['environment_domain'],row['profile'])
            self.assertEqual(row['configuration_state'],'UNCONFIGURED')
            self.assertIsNone(row['configuration']['genesis_hash'])
            self.assertIsNone(row['configuration']['chain_id'])
            self.assertIsNone(row['configuration']['transaction_domain'])
            self.assertIsNone(row['configuration']['bind_address'])
            self.assertEqual(row['configuration']['seed_peers'],[])
            self.assertFalse(row['runnable_public']);self.assertFalse(row['deployment_ready'])
            self.assertFalse(row['mainnet_enabled'])
            self.assertIn('PUBLIC_P2P_TRANSPORT_NOT_IMPLEMENTED',row['blockers'])
            self.assertIn('CANONICAL_DAG_ORDERING_AND_FINALITY_NOT_IMPLEMENTED',row['blockers'])
            self.assertIn('POST_QUANTUM_SIGNATURES_NOT_IMPLEMENTED',row['blockers'])
        self.assertFalse(result['genesis_created']);self.assertFalse(result['keys_created'])
        self.assertEqual(result['peer_connections_created'],0)
        self.assertTrue(all(engine['source_available'] and engine['runtime_available'] is None and not engine['public_network']
                            for engine in result['local_engines']))

    def test_valid_public_configuration_is_only_syntax_not_a_deployment_or_approval(self):
        given=configuration('TESTNET')
        result=profiles.readiness('TESTNET',given)
        self.assertEqual(result['configuration_state'],'VALIDATED_PUBLIC_SYNTAX')
        self.assertEqual(result['missing_configuration'],[])
        self.assertEqual(result['configuration']['genesis_hash'],given['genesis_hash'])
        self.assertFalse(result['deployment_ready']);self.assertFalse(result['runnable_public'])
        self.assertIn('PUBLIC_GENESIS_AND_SIGNING_DOMAINS_NOT_APPROVED',result['blockers'])
        self.assertEqual(result['validation_scope'],'PUBLIC_SYNTAX_ONLY_NO_NETWORK_IO_OR_APPROVAL')
        result['configuration']['seed_peers'].append('unrelated.invalid:1')
        self.assertEqual(given['seed_peers'],['127.0.0.1:16112'])
        fresh=profiles.snapshot();fresh['profiles'][0]['configuration']['seed_peers'].append('unrelated.invalid:2')
        self.assertEqual(profiles.snapshot()['profiles'][0]['configuration']['seed_peers'],[])
        self.assertEqual(profiles.snapshot('mainnet')['profiles'][0]['profile'],'MAINNET')

    def test_secret_extra_fields_bad_domains_and_ambiguous_peers_fail_closed(self):
        for bad in ({'private_key':'synthetic-not-a-secret'}, {'password':'synthetic-not-a-secret'},
                    {'endpoint':'http://127.0.0.1:9'}, {'profile':'MAINNET'},
                    {'role':'administrator'}, {'genesis_hash':'not-a-hash'},
                    {'chain_id':'../../somewhere'}, {'transaction_domain':'SAME','block_domain':'SAME'},
                    {'seed_peers':['http://person:password@example.invalid:1']},
                    {'seed_peers':['127.0.0.1:99999']}, {'seed_peers':['999.1.1.1:1']},
                    {'seed_peers':['[:::]:1']}, {'seed_peers':['bad..invalid:1']},
                    {'seed_peers':['127.0.0.1:1']*2}, {'seed_peers':[None]}):
            with self.subTest(fields=list(bad)),self.assertRaises(ValueError):profiles.validate_configuration('TESTNET',bad)
        with self.assertRaisesRegex(ValueError,'UNKNOWN'):profiles.snapshot('DEVNET')

    def test_environment_pairs_reject_reused_chain_genesis_and_cross_purpose_domains(self):
        clean={'TESTNET':configuration('TESTNET'),'MAINNET':configuration('MAINNET')}
        self.assertEqual(set(profiles.validate_profile_pair(clean)),set(profiles.PROFILE_IDS))
        for field in ('chain_id','genesis_hash','transaction_domain','block_domain'):
            bad=deepcopy(clean);bad['MAINNET'][field]=bad['TESTNET'][field]
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'ENVIRONMENTS_MUST_DIFFER'):
                profiles.validate_profile_pair(bad)
        bad=deepcopy(clean);bad['MAINNET']['block_domain']=bad['TESTNET']['transaction_domain']
        with self.assertRaisesRegex(ValueError,'ENVIRONMENTS_MUST_DIFFER'):profiles.validate_profile_pair(bad)

    def test_readiness_module_does_not_import_qt_wallet_engines_or_perform_io(self):
        script='''import builtins,socket,threading,sys
from unittest.mock import patch
from backend import network_profiles
assert not any(name.startswith(('PySide6','PyQt','backend.gg_parallel_dag','backend.gg_consensus','backend.gg_testnet','backend.wallet')) for name in sys.modules)
with patch.object(builtins,'open',side_effect=AssertionError('unexpected IO')), patch.object(socket,'socket',side_effect=AssertionError('unexpected network')), patch.object(threading.Thread,'start',side_effect=AssertionError('unexpected worker')):
 body=network_profiles.snapshot()
 assert len(body['profiles'])==2 and all(not row['deployment_ready'] for row in body['profiles'])
'''
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class TerminalNetworkProfiles(unittest.TestCase):
    def setUp(self):
        from backend import omni_assets
        from backend.terminal_service import TerminalService
        self.temporary=tempfile.TemporaryDirectory(prefix='gg-cli-network-profile-')
        self.addCleanup(self.temporary.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(omni_assets,'ROOT',Path(self.temporary.name)/'registry'))
        self.service=TerminalService();self.addCleanup(self.service.close)

    def test_cli_readiness_has_both_profiles_without_starting_or_adopting_an_engine(self):
        with (patch.object(self.service,'_network',side_effect=AssertionError('unexpected engine')),
              patch.object(self.service,'_dag',side_effect=AssertionError('unexpected engine'))):
            result=self.service.dispatch('network.readiness')
            self.assertEqual(len(result['profiles']),2)
            selected=self.service.dispatch('network.readiness',{'profile':'MAINNET'})
            self.assertEqual([row['profile'] for row in selected['profiles']],['MAINNET'])
        for command,args in (('network.readiness',{'private_key':'synthetic-not-a-secret'}),
                             ('network.start',{'profile':'MAINNET'}),
                             ('dag.live_start',{'endpoint':'http://remote.invalid'})):
            with self.assertRaisesRegex(ValueError,'COMMAND_ARGUMENTS'):self.service.dispatch(command,args)
        self.assertFalse(self.service._owns_network);self.assertFalse(self.service._owns_dag)

    def test_real_async_cli_start_pause_resume_and_close_keep_terminal_ownership(self):
        from backend import gg_parallel_dag
        first=self.service.dispatch('dag.live_start',{'blocks':8,'transactions_per_block':0,'interval_ms':125,'producer_count':8})
        self.assertEqual(first['producer_count'],8)
        end=time.monotonic()+4
        while self.service.dispatch('dag.status')['blocks_admitted']<8 and time.monotonic()<end:time.sleep(.01)
        running=self.service.dispatch('dag.status')
        self.assertGreaterEqual(running['blocks_admitted'],8)
        self.assertEqual(running['canonical_finalized'],0)
        chain=running['chain_id']
        paused=self.service.dispatch('dag.live_stop')
        self.assertEqual(paused['state'],'RUNNING');self.assertFalse(paused['live']['enabled'])
        self.assertEqual(paused['chain_id'],chain)
        count=paused['blocks_admitted'];time.sleep(.04)
        self.assertEqual(self.service.dispatch('dag.status')['blocks_admitted'],count)
        resumed=self.service.dispatch('dag.live_start',{'producer_count':8})
        self.assertEqual(resumed['chain_id'],chain)
        self.service.close()
        self.assertEqual(self.service._dag().snapshot()['state'],'STOPPED')
        self.assertFalse(any(worker.name.startswith(('gg-dag-live','gg-dag-producer')) for worker in threading.enumerate()))
        self.assertEqual(gg_parallel_dag.snapshot()['state'],'STOPPED','Terminal must not adopt the desktop engine')

    def test_real_json_readiness_cli_closes_without_allocating_a_node(self):
        from backend.terminal_cli import main
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--json','--command','network.readiness'],lambda:self.service)
        self.assertEqual(code,0)
        result=json.loads(output.getvalue())
        self.assertEqual([row['profile'] for row in result['profiles']],['TESTNET','MAINNET'])
        self.assertFalse(any(row['deployment_ready'] for row in result['profiles']))
        self.assertIsNone(self.service._dag_engine)
        self.assertFalse(self.service._owns_network)
        self.assertTrue(self.service._closed)


class ForegroundCliLifetime(unittest.TestCase):
    def test_foreground_local_session_waits_until_ctrl_c_and_always_closes(self):
        from backend.terminal_cli import main,parse_command
        self.assertEqual(parse_command('dag.live_start blocks=8 interval_ms=125 producer_count=8')[1],
                         {'blocks':8,'interval_ms':125,'producer_count':8})
        class Service:
            def __init__(self):self.calls=[];self.closed=0
            def dispatch(self,command,args):
                self.calls.append((command,args))
                return {'state':'RUNNING','producer_count':8,'blocks_admitted':8*len(self.calls),
                        'canonical_finalized':0,'live':{'state':'RUNNING'}}
            def close(self):self.closed+=1
        service=Service();output=io.StringIO()
        with redirect_stdout(output),patch('backend.terminal_cli.time.sleep',side_effect=[None,KeyboardInterrupt]):
            code=main(['--json','--foreground','--command','dag.live_start','--args','{"producer_count":8}'],lambda:service)
        self.assertEqual(code,130);self.assertEqual(service.closed,1)
        self.assertEqual([command for command,_ in service.calls],['dag.live_start','dag.status'])
        records=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(any(record.get('scope')=='LOCAL_RAM_SIGNED_PROPOSALS_NOT_PUBLIC_NETWORK' for record in records))
        self.assertTrue(all(record.get('canonical_finalized',0)==0 for record in records))

    def test_foreground_rejects_other_commands_and_mixed_one_shot_before_service_creation(self):
        from backend.terminal_cli import main
        for options in (['--foreground'],['--foreground','--command','wallet.send'],
                        ['--foreground','--once','--command','network.start']):
            factory=Mock(side_effect=AssertionError('must reject before creating any service'))
            output=io.StringIO()
            with self.subTest(options=options),redirect_stdout(output):code=main(['--json',*options],factory)
            self.assertEqual(code,1);factory.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['error'],'TERMINAL_FOREGROUND_LOCAL_START_REQUIRED')


if __name__=='__main__':unittest.main()
