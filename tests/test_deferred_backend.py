import importlib.abc
import importlib.util
import sys
import threading
import time
import unittest
import os
import subprocess
from pathlib import Path
import tempfile
from unittest.mock import patch

from backend.deferred_backend import DeferredBackend


class DeferredBackendTests(unittest.TestCase):
    def test_actual_game_service_is_absent_until_requested_then_shared(self):
        script='''import importlib,sys
from backend.chat_surface_host import game_engine_host as facade
assert 'backend.game_engine_host' not in sys.modules
value=facade.status_payload()
actual=importlib.import_module('backend.game_engine_host')
assert facade._RUNTIME is actual._RUNTIME
assert isinstance(value,dict) and value
facade.shutdown()
print('REAL_LAZY_GAME_BACKEND=PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-lazy-backend-') as temporary:
            env=os.environ.copy();env.update(GG_DESKTOP_STATE_ROOT=temporary+'/state',GG_DESKTOP_DATA_ROOT=temporary+'/data')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script],cwd=Path(__file__).resolve().parents[1],
                                  env=env,capture_output=True,text=True,encoding='utf-8',timeout=25)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('REAL_LAZY_GAME_BACKEND=PASS',result.stdout)

    def test_unused_shutdown_does_not_construct_service(self):
        service=DeferredBackend('synthetic_absent_backend')
        with patch('backend.deferred_backend.importlib.import_module') as load:
            self.assertFalse(service.loaded);service.shutdown();load.assert_not_called()

    def test_first_use_is_shared_and_existing_service_is_cleaned_up(self):
        import types
        calls=[];module=types.ModuleType('synthetic_shared_backend')
        module.runtime=object();module.shutdown=lambda:calls.append('stop')
        service=DeferredBackend(module.__name__)
        with patch.dict(sys.modules,{module.__name__:module}):
            results=[];threads=[threading.Thread(target=lambda:results.append(service.runtime)) for _ in range(12)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(1)
            self.assertEqual(len(results),12);self.assertTrue(all(v is module.runtime for v in results))
            service.shutdown();self.assertEqual(calls,['stop'])


if __name__=='__main__':unittest.main()
