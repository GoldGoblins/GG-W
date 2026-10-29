"""Headless packaging probes. No installation, real signing or node start."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

SOURCE=Path(__file__).resolve().parent
PROJECT=SOURCE.parents[1]


def load(name):
    spec=importlib.util.spec_from_file_location('gg_terminal_'+name,SOURCE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


release=load('build_release');bootstrap=load('bootstrap')


class ReleaseTests(unittest.TestCase):
    def test_platform_archives_have_same_code_and_only_reviewed_sources(self):
        with tempfile.TemporaryDirectory(prefix='gg-terminal-release-test-') as temporary:
            by_platform=[]
            for target in ('windows','linux','termux'):
                path=release.build(target,temporary)
                with zipfile.ZipFile(path) as archive:
                    entries={name:archive.read(name) for name in archive.namelist()}
                    manifest=json.loads(entries.pop('GG-TERMINAL/TERMINAL-MANIFEST.json'))
                    self.assertFalse(manifest['remote_publish_performed'])
                    self.assertEqual(manifest['platform'],target)
                    self.assertEqual(manifest['source_repository_declared_by_project'],'https://github.com/GoldGoblins/GG-CLI')
                    self.assertEqual(manifest['upstream_source_repository'],'https://github.com/GoldGoblins/GG')
                    self.assertEqual(entries['GG-TERMINAL/install.py'],entries['GG-TERMINAL/support/gg-cli/install.py'])
                    self.assertEqual(entries['GG-TERMINAL/README.md'],entries['GG-TERMINAL/support/gg-cli/repository-README.md'])
                    for wrapper in ('windows.cmd','linux.sh','termux.sh'):
                        self.assertEqual(entries['GG-TERMINAL/install/'+wrapper],entries['GG-TERMINAL/support/gg-cli/install/'+wrapper])
                    for name,raw in entries.items():
                        self.assertNotIn('..',Path(name).parts)
                        self.assertFalse(any(token in name for token in ('.runtime/','.venv','wallet-vault/','sqlite3','.ggwallet','PySide6/')))
                        recorded=manifest['files'][name.removeprefix('GG-TERMINAL/')]
                        self.assertEqual(recorded['sha256'],hashlib.sha256(raw).hexdigest())
                by_platform.append(entries)
            self.assertEqual(by_platform[0],by_platform[1]);self.assertEqual(by_platform[1],by_platform[2])
            with self.assertRaises(FileExistsError):release.build('windows',temporary)

    def test_extracted_package_actual_status_without_qt_pillow_or_solders_imports(self):
        with tempfile.TemporaryDirectory(prefix='gg-terminal-headless-probe-') as temporary:
            root=Path(temporary)
            path=release.build('windows',root/'out')
            with zipfile.ZipFile(path) as archive:archive.extractall(root/'extracted')
            launcher=root/'extracted/GG-TERMINAL/gg-cli.py'
            code="""import builtins,runpy,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.split('.')[0] in {'PySide6','PyQt5','PyQt6','PIL','solders'}:raise AssertionError('HEADLESS_IMPORT_FORBIDDEN')
 return original(name,*args,**kwargs)
builtins.__import__=guarded
sys.argv=[sys.argv[1],'--once','--json']
runpy.run_path(sys.argv[0],run_name='__main__')
"""
            env=os.environ.copy();env['GG_TERMINAL_STATE_ROOT']=str(root/'private-state');env['GG_TERMINAL_DATA_ROOT']=str(root/'private-data')
            env['GG_DESKTOP_STATE_ROOT']=str(root/'desktop-must-stay-untouched')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(launcher)],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            body=json.loads(result.stdout);self.assertEqual(body['schema'],'gg.terminal.status.v1')
            self.assertEqual(body['consensus']['state'],'STOPPED')
            self.assertEqual(body['wallet']['accounts'],[])
            self.assertFalse((root/'desktop-must-stay-untouched').exists())
            self.assertTrue((root/'private-state').is_dir())
            for platform in ('windows','linux','termux'):
                checked=subprocess.run([sys.executable,'-X','utf8','-B',str(launcher.parent/'install.py'),
                    '--platform',platform,'--check'],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
                self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
                plan=json.loads(checked.stdout)
                self.assertEqual(plan['platform'],platform)
                self.assertFalse(plan['network_requested'])
                self.assertFalse(plan['node_start'])
            for command in ('network.readiness','lan.status'):
                probe=code.replace("sys.argv=[sys.argv[1],'--once','--json']",
                                   "sys.argv=[sys.argv[1],'--json','--command',"+repr(command)+"]")
                check=subprocess.run([sys.executable,'-X','utf8','-B','-c',probe,str(launcher)],
                    cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
                self.assertEqual(check.returncode,0,check.stdout+check.stderr)
                status=json.loads(check.stdout)
                if command=='lan.status':
                    self.assertEqual(status['state'],'STOPPED')
                    self.assertFalse(status['lan_setup']['active'])
                else:
                    self.assertEqual([row['profile'] for row in status['profiles']],['TESTNET','MAINNET'])
                    self.assertFalse(any(row['mainnet_enabled'] or row['deployment_ready'] for row in status['profiles']))
            # The distributed capacity tool must run without the desktop or
            # repository checkout, using only public numeric parameters.
            planner=launcher.parent/'support/dagoblin/analyze.py'
            request={'operation':'link_bytes_per_second','parameters':{'value':1,'unit':'GiB/s'}}
            calculation=subprocess.run([sys.executable,'-X','utf8','-B',str(planner),'--input','-'],
                input=json.dumps(request),cwd=root,env=env,capture_output=True,text=True,
                encoding='utf-8',timeout=10)
            self.assertEqual(calculation.returncode,0,calculation.stdout+calculation.stderr)
            self.assertEqual(json.loads(calculation.stdout),'1073741824')

    def test_bootstrap_explicit_pins_no_resolver_or_global_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'venv';target.mkdir();(target/'pyvenv.cfg').write_text('fixture')
            executable=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python');executable.parent.mkdir();executable.touch()
            with patch.object(bootstrap.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(bootstrap.install(target,True),executable)
            command=run.call_args.args[0]
            self.assertIn('--isolated',command);self.assertIn('--require-virtualenv',command);self.assertIn('--no-deps',command)
            self.assertIn('https://pypi.org/simple',command)
            self.assertEqual(command.count('-r'),2)
            self.assertNotIn('--user',command)
            self.assertNotIn('solders',(SOURCE/'requirements.txt').read_text())
            self.assertIn('solders==0.29.0',(SOURCE/'requirements-wallet.txt').read_text())


if __name__=='__main__':unittest.main()
