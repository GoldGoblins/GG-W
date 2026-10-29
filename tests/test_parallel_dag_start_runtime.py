"""The real desktop action lane starts and retains its owned live DAG.

Run in a fresh private-state process: no existing app, wallet or test node is
attached. The hub's separate QML telemetry ordering is exercised elsewhere.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def fixture():
    import threading
    import time
    from PySide6.QtCore import QCoreApplication
    from backend import gg_parallel_dag as dag, omni_assets as store, omni_service
    from backend.crypto_ui_runtime import CryptoUiRuntime

    app=QCoreApplication([])
    store.bootstrap()
    updates=[]
    runtime=CryptoUiRuntime(snapshot=omni_service.snapshot,ttl=0)
    runtime.updated.connect(lambda raw:updates.append(json.loads(raw)))

    def wait(condition,timeout=6):
        end=time.monotonic()+timeout
        while not condition() and time.monotonic()<end:
            app.processEvents();time.sleep(.002)
        app.processEvents()
        assert condition(),'OWNED_DAG_RUNTIME_FIXTURE_TIMEOUT'

    try:
        runtime.snapshot()
        wait(lambda:not runtime._running)
        assert runtime._payload['parallel_dag']['state']=='STOPPED'
        stopped=runtime._payload['parallel_dag']
        runtime.submit('dag_start',lambda:omni_service.action('dag_start'))
        wait(lambda:not runtime._running)
        started=json.loads(runtime.snapshot())
        wait(lambda:not runtime._running)
        assert started['ui_operation']=={'name':'dag_start','state':'done','error':''}
        assert started['parallel_dag']['state']=='RUNNING'
        assert started['parallel_dag']['live']['enabled']
        chain=started['parallel_dag']['chain_id']
        wait(lambda:dag.snapshot()['wave_count']>=3)
        before=dag.snapshot()['blocks_admitted']

        # Refreshing and the idempotent Start action never create a second
        # runner, clear history or stop this one. Real signatures/parents must
        # already exist before the status is delivered to the view.
        for _ in range(4):
            runtime.snapshot();wait(lambda:not runtime._running)
            body=runtime._payload['parallel_dag']
            assert body['state']=='RUNNING' and body['chain_id']==chain
            assert body['blocks_admitted']>=before
            assert body['admission']['signature_checks']==body['blocks_admitted']
        runtime.submit('dag_start',lambda:omni_service.action('dag_start'))
        wait(lambda:not runtime._running)
        body=runtime._payload['parallel_dag']
        assert body['chain_id']==chain and body['blocks_admitted']>=before
        assert len([worker for worker in threading.enumerate() if worker.name=='gg-dag-live'])==1
        assert any(len(block['parent_hashes'])>1 for block in body['block_graph']['blocks'])
        assert stopped['state']=='STOPPED' and not stopped['chain_id']
        assert any(value.get('parallel_dag',{}).get('state')=='RUNNING' for value in updates)

        runtime.submit('dag_stop',lambda:omni_service.action('dag_stop'))
        wait(lambda:not runtime._running)
        assert runtime._payload['parallel_dag']['state']=='STOPPED'
        assert not any(worker.name.startswith(('gg-dag-live','gg-dag-producer')) for worker in threading.enumerate())
        print(json.dumps({'desktop_service_start':'PASS','real_signed_proposals':body['blocks_admitted'],
            'same_session_after_repeated_start':True,'explicit_stop_only':True,'owned_threads_stopped':True}))
    finally:
        runtime.close();dag.stop()


class DagStartRuntimeTests(unittest.TestCase):
    def test_real_desktop_service_start_refresh_and_explicit_stop(self):
        with tempfile.TemporaryDirectory(prefix='gg-dag-start-runtime-') as folder:
            env=os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(Path(folder)/'state'),
                       GG_DESKTOP_DATA_ROOT=str(Path(folder)/'data'))
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture'],
                cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('"desktop_service_start": "PASS"',result.stdout)


if __name__=='__main__':
    if sys.argv[1:]==['--fixture']:fixture()
    else:unittest.main()
