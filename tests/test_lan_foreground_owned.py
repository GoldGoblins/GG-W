"""Foreground launch can request actual bounded owned work without peer RPC."""
from contextlib import redirect_stdout
from copy import deepcopy
import io,json,unittest
from unittest.mock import patch
from backend import terminal_cli as cli


class ForegroundOwnedTests(unittest.TestCase):
    def test_paired_transition_starts_one_owned_job_once_and_keeps_receiving_after_end(self):
        pairing={'lan':{'state':'PAIRING'},'dag_production':{'state':'IDLE'}}
        ready={'lan':{'state':'READY'},'dag_production':{'state':'IDLE'}}
        complete={'lan':{'state':'READY'},'dag_production':{'state':'COMPLETE','worker_active':False}}
        plan={'duration_ms':1000,'transactions_per_block':32,'interval_ms':100}
        class Service:
            def __init__(self):self.calls=[]
            def dispatch(self,command,args):
                self.calls.append((command,args))
                return deepcopy(ready if command=='lan.status' and len(self.calls)==1 else complete)
        service=Service();output=io.StringIO()
        with redirect_stdout(output),patch.object(cli.time,'sleep',side_effect=[None,None,KeyboardInterrupt]),self.assertRaises(KeyboardInterrupt):
            cli.foreground_session(service,'lan.start',pairing,json_output=True,own_production=plan)
        self.assertEqual(service.calls,[('lan.status',{}),('lan.dag_produce_start',plan),('lan.status',{})])
        rows=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]['requested_own_production']['state'],'WAITING_FOR_PAIRED_SESSION')
        self.assertEqual(rows[-1]['dag_production']['state'],'COMPLETE')
        self.assertEqual(plan['duration_ms'],1000)

    def test_failed_start_is_not_retried(self):
        class Service:
            def __init__(self):self.calls=[]
            def dispatch(self,command,args):
                self.calls.append(command);raise ValueError('GG_LAN_DAG_PRODUCTION_BUSY')
        service=Service()
        with self.assertRaisesRegex(ValueError,'PRODUCTION_BUSY'):
            cli.foreground_session(service,'lan.start',{'lan':{'state':'READY'}},own_production={})
        self.assertEqual(service.calls,['lan.dag_produce_start'])

    def test_cli_validates_plan_before_creating_a_service_or_keys(self):
        for extra in ([ '--own-production','{}'],['--foreground','--command','network.start','--own-production','{}'],
                      ['--foreground','--command','lan.start','--own-production','{"duration_ms":true}'],
                      ['--foreground','--command','lan.start','--own-production','{"peer_key":"a"}'],
                      ['--foreground','--command','lan.start allow_dag_transactions=false','--own-production','{}']):
            calls=[]
            def factory():calls.append(True);raise AssertionError('Validation created service')
            with redirect_stdout(io.StringIO()):code=cli.main(['--json',*extra],factory)
            self.assertEqual(code,1);self.assertFalse(calls)

    def test_cli_flag_binds_explicit_local_plan_and_dag_opt_in(self):
        class Service:
            def __init__(self):self.calls=[];self.closed=False
            def dispatch(self,command,args):self.calls.append((command,args));return {'lan':{'state':'PAIRING'}}
            def close(self):self.closed=True
        service=Service();output=io.StringIO()
        with redirect_stdout(output),patch.object(cli,'foreground_session',side_effect=KeyboardInterrupt) as foreground:
            code=cli.main(['--json','--foreground','--command','lan.start label=Linux','--own-production','{"transactions_per_block":32}'],lambda:service)
        self.assertEqual(code,130);self.assertTrue(service.closed)
        self.assertEqual(service.calls[0],('lan.start',{'label':'Linux','allow_dag_transactions':True}))
        self.assertEqual(foreground.call_args.kwargs['own_production'],{'duration_ms':60000,'transactions_per_block':32,'interval_ms':1000})


if __name__=='__main__':unittest.main()
