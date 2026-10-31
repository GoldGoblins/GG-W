"""Foreground diagnostics with synthetic snapshots; no node, GUI or sockets."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

from backend import terminal_cli as cli


def snapshot():
    return {'lan':{'state':'READY','configured_peers':3,'authenticated_peers':[{},{}],
        'last_error':'','last_error_at':0,'last_error_details':{},
        'transport':{'state':'ACTIVE','exhausted_reason':'','connections_admitted':4,'active_handlers':0,
            'counters':{'failures':0,'expected_closures':0,'successes':4,
                'admission_drops':{'RATE':0,'HANDLERS':0,'SESSION':0,'BYTES':0}},'history':[]}},
        'lan_setup':{'invite_count':3},'producer_count':6,'blocks_admitted':0,
        'transactions_validated':0,'dag_stress':{'state':'IDLE','enabled':True}}


class ForegroundDiagnosticsTests(unittest.TestCase):
    def test_observation_age_does_not_create_idle_output_but_job_time_changes_do(self):
        before=snapshot()
        work={'local':{'transactions':32,'sign_ms':10.0,'verify_ms':44.0,'wall_ms':55.0,'age_seconds':1.0},
              'relay':{'transactions':32,'cpu_ms':40.0,'wall_ms':70.0,'age_seconds':1.0}}
        before['dag_stress'].update(workload=work,participants=[{'label':'Linux','workload':deepcopy(work)}])
        after=deepcopy(before)
        for sample in (after['dag_stress']['workload'],after['dag_stress']['participants'][0]['workload']):
            for row in sample.values():row['age_seconds']=100.0
        self.assertEqual(cli.foreground_summary('lan.start',before),cli.foreground_summary('lan.start',after))
        after['dag_stress']['workload']['relay']['wall_ms']=90.0
        self.assertNotEqual(cli.foreground_summary('lan.start',before),cli.foreground_summary('lan.start',after))

    def test_exact_local_failure_and_limits_are_visible_without_remote_health_claim(self):
        body=snapshot();lan=body['lan']
        lan.update(last_error='GG_LAN_READ_DEADLINE',last_error_at=1793411138.409,
            last_error_details={'operation':'PAGE','stage':'RECEIVE','error_class':'ValueError'})
        lan['transport'].update(state='EXHAUSTED',exhausted_reason='SESSION')
        lan['transport']['counters'].update(failures=8,expected_closures=2)
        lan['transport']['counters']['admission_drops']['SESSION']=1
        for command in ('lan.start','lan.join_file'):
            with self.subTest(command=command):
                summary=cli.foreground_summary(command,body);local=summary['local_transport']
                self.assertEqual(local,{'scope':'LOCAL_PEER_ONLY','state':'EXHAUSTED','exhausted_reason':'SESSION',
                    'counters':{'failures':8,'expected_closures':2,
                        'admission_drops':{'RATE':0,'HANDLERS':0,'SESSION':1,'BYTES':0}},
                    'last_failure':{'code':'GG_LAN_READ_DEADLINE','at':1793411138.409,
                        'transport':{'operation':'PAGE','stage':'RECEIVE','error_class':'ValueError'}}})
                self.assertFalse(summary['physical_hosts_verified'])
                self.assertNotIn('acknowledgement',local)

    def test_expected_closures_do_not_erase_a_genuine_sticky_failure(self):
        body=snapshot();lan=body['lan']
        lan.update(last_error='GG_LAN_CONNECTION_RESET',last_error_at=100,
            last_error_details={'operation':'GET','stage':'RECEIVE','error_class':'ConnectionResetError'})
        lan['transport']['counters']['failures']=1
        before=cli.foreground_summary('lan.start',body)['local_transport']
        lan['transport']['counters']['expected_closures']=3
        lan['transport']['history']=[{'code':'GG_LAN_EOF','expected':True}]
        after=cli.foreground_summary('lan.start',body)['local_transport']
        self.assertEqual(after['counters']['failures'],1)
        self.assertEqual(after['counters']['expected_closures'],3)
        self.assertEqual(after['last_failure'],before['last_failure'])
        self.assertNotIn('history',after)

    def test_malicious_diagnostics_are_filtered_to_fixed_enums_and_bounded_numbers(self):
        body=snapshot();lan=body['lan']
        lan.update(last_error='GG_LAN_EOF\nPRIVATE_SENTINEL',last_error_at=float('nan'),
            last_error_details={'operation':'PRIVATE_SENTINEL','stage':['RECEIVE'],
                'error_class':'PRIVATE_SENTINEL','endpoint':'PRIVATE_SENTINEL'})
        transport=lan['transport']
        transport.update(state=['ACTIVE'],exhausted_reason='PRIVATE_SENTINEL',
            endpoint='PRIVATE_SENTINEL',public_key='a'*64,history=[{'secret':'PRIVATE_SENTINEL'}])
        transport['counters'].update(failures=True,expected_closures=-1,
            admission_drops={'RATE':'4','HANDLERS':1.5,'SESSION':2**53,'BYTES':0})
        local=cli.foreground_summary('lan.start',body)['local_transport']
        self.assertIsNone(local['state']);self.assertIsNone(local['exhausted_reason'])
        self.assertEqual(local['counters'],{'failures':None,'expected_closures':None,
            'admission_drops':{'RATE':None,'HANDLERS':None,'SESSION':None,'BYTES':0}})
        self.assertEqual(local['last_failure'],{'code':None,'at':None,
            'transport':{'operation':None,'stage':None,'error_class':None}})
        for value in ('PRIVATE_SENTINEL','endpoint','public_key','a'*64,'history','secret'):
            self.assertNotIn(value,json.dumps(local))
        for code in ('GG_'+'A'*64,'GG_'+('X'*81),'GG_LAN_EOF\x1b[31m'):
            lan['last_error']=code
            self.assertIsNone(cli.foreground_summary('lan.start',body)['local_transport']['last_failure']['code'])
        for stamp in (-1,float('inf'),True,4102444801):
            lan['last_error_at']=stamp
            self.assertIsNone(cli.foreground_summary('lan.start',body)['local_transport']['last_failure']['at'])

    def test_healthy_gossip_does_not_change_foreground_fingerprint(self):
        before=snapshot();after=deepcopy(before)
        after['lan']['transport'].update(connections_admitted=900,active_handlers=4)
        after['lan']['transport']['counters']['successes']=1800
        after['lan']['transport']['history']=[{'at':1793411138,'code':'GG_LAN_EOF','expected':True}]
        self.assertEqual(cli.foreground_summary('lan.start',before),cli.foreground_summary('lan.start',after))
        local=cli.foreground_summary('lan.start',after)['local_transport']
        for key in ('connections_admitted','active_handlers','successes','history','age'):
            self.assertNotIn('"'+key+'":',json.dumps(local))

    def test_periodic_output_changes_for_failure_count_but_not_healthy_poll_activity(self):
        start=snapshot();healthy=deepcopy(start)
        healthy['lan']['transport'].update(connections_admitted=40,active_handlers=2)
        healthy['lan']['transport']['counters']['successes']=80
        failed=deepcopy(healthy)
        failed['lan'].update(last_error='GG_LAN_IO_TIMEOUT',last_error_at=100,
            last_error_details={'operation':'PAGE','stage':'CONNECT','error_class':'TimeoutError'})
        failed['lan']['transport']['counters']['failures']=1
        repeated=deepcopy(failed);repeated['lan']['transport']['counters']['failures']=2
        class Service:
            def __init__(self):self.next=iter((healthy,failed,repeated));self.commands=[]
            def dispatch(self,command,args):
                self.commands.append((command,args))
                try:return next(self.next)
                except StopIteration:raise KeyboardInterrupt
        service=Service();output=io.StringIO()
        with redirect_stdout(output),patch.object(cli.time,'sleep',return_value=None) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                cli.foreground_session(service,'lan.join_file',start,json_output=True)
        rows=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row['local_transport']['counters']['failures'] for row in rows],[0,1,2])
        self.assertEqual(len(rows),3)
        self.assertEqual(service.commands,[('lan.status',{})]*4)
        self.assertEqual(sleep.call_count,4)

    def test_absent_transport_preserves_legacy_shape(self):
        body=snapshot();body['lan'].pop('transport')
        old=cli.foreground_summary('lan.start',body)
        self.assertNotIn('local_transport',old)
        for value in (None,[], 'PRIVATE_SENTINEL'):
            body['lan']['transport']=value
            self.assertEqual(cli.foreground_summary('lan.start',body),old)
        body=snapshot();new=cli.foreground_summary('lan.start',body)
        new.pop('local_transport')
        self.assertEqual(new,old)


if __name__=='__main__':unittest.main()
