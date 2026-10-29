"""Exact old ABI fixture, cached aliases and concurrent reads; no user files."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt','Windows ABI compatibility repair')
class RuntimeMemoryMaintenanceTests(unittest.TestCase):
    def test_repairs_cached_function_alias_and_releases_only_legacy_types(self):
        script=r'''
import ctypes,json,os,threading,time,types
from pathlib import Path
from backend import platform_files as files
from backend import runtime_memory_maintenance as maintenance
root=Path(os.environ['GG_DESKTOP_STATE_ROOT']);root.mkdir(parents=True,exist_ok=True)
fixture=root/'fixture.txt';fixture.write_bytes(b'only synthetic fixture')
import inspect,textwrap
body=inspect.getsource(files.secure_open)
fields=inspect.getsource(files._FileInformation).replace('class _FileInformation','class FileInformation')
security=inspect.getsource(files._SecurityAttributes).replace('class _SecurityAttributes','class SecurityAttributes')
body=body.replace('    kernel = ctypes.WinDLL',textwrap.indent(textwrap.dedent(fields),'    ')+'\n'+textwrap.indent(textwrap.dedent(security),'    ')+'\n    kernel = ctypes.WinDLL',1).replace('_FileInformation','FileInformation').replace('_SecurityAttributes','SecurityAttributes')
exec(compile(body,str(Path(files.__file__).resolve()),'exec'),files.__dict__)
alias=files.secure_open
def read():
 fd=alias(fixture,os.O_RDONLY)
 with os.fdopen(fd,'rb') as stream:assert stream.read()==b'only synthetic fixture'
for _ in range(1000):read()
before=sum(maintenance._legacy_type(key) for key in ctypes._pointer_type_cache)
assert before==1000,before
unrelated=ctypes.POINTER(ctypes.c_int)
errors=[]
def worker():
 try:
  for _ in range(1000):read()
 except Exception as error:errors.append(type(error).__name__)
thread=threading.Thread(target=worker);thread.start()
report=maintenance.repair_legacy_windows_file_types();thread.join()
assert report['state']=='REPAIRED',report
assert alias is files.secure_open and '_FileInformation' in alias.__code__.co_names
maintenance._cleanup()
assert not any(maintenance._legacy_type(key) for key in ctypes._pointer_type_cache)
assert ctypes.POINTER(ctypes.c_int) is unrelated
assert not errors,errors
cache=len(ctypes._pointer_type_cache)
for _ in range(1000):read()
assert len(ctypes._pointer_type_cache)==cache
try:alias(root,os.O_RDONLY)
except OSError:pass
else:raise AssertionError('directory policy weakened')
try:alias(fixture,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
except FileExistsError:pass
else:raise AssertionError('exclusive policy weakened')
assert maintenance.repair_legacy_windows_file_types()['state']=='REPAIRED'
from backend.runtime_heap_reclaim import finish_repaired_heap
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlEngine
app=QApplication([]);engine=QQmlEngine();app._gg_qml_engine=engine
engine.evaluate('var retainedPublicValue = {answer:42}')
finish_repaired_heap()
assert maintenance._report['unused_heap_decommit_succeeded'] is True
assert maintenance._report['allocated_python_blocks_after_repair']>0
assert maintenance._report['qml_gc_completed'] is True
assert engine.evaluate('retainedPublicValue.answer').toInt()==42
print('LIVE_COMPATIBILITY_FIXTURE=PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-memory-compat-') as temporary:
            env=os.environ.copy();env['GG_DESKTOP_STATE_ROOT']=temporary
            env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script],cwd=ROOT,env=env,
                                  capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('LIVE_COMPATIBILITY_FIXTURE=PASS',result.stdout)


if __name__=='__main__':unittest.main()
