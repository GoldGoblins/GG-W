"""An otherwise installed CLI must not enter a node without its crypto provider."""
from contextlib import redirect_stderr
import importlib.util
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class SignatureEnvironmentTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('gg_signature_launcher_fixture',ROOT/'gg-cli.py')
        self.launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.launcher)
        self.temp=tempfile.TemporaryDirectory(prefix='gg-cli-provider-');self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.candidate=self.home/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        self.candidate.parent.mkdir(parents=True);self.candidate.write_bytes(b'owned unexecuted launcher fixture')

    def context(self,result):
        from contextlib import ExitStack
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ,{},clear=False))
        stack.enter_context(patch.object(self.launcher,'terminal_home',return_value=self.home))
        stack.enter_context(patch.object(self.launcher,'ROOT',self.home))
        stack.enter_context(patch.object(self.launcher.importlib.util,'find_spec',side_effect=lambda name:None if name=='nacl' else object()))
        stack.enter_context(patch.object(self.launcher.sys,'argv',['gg-cli.py','--json','--once']))
        probe=stack.enter_context(patch.object(self.launcher.subprocess,'run',return_value=SimpleNamespace(returncode=result)))
        start=stack.enter_context(patch.object(self.launcher.subprocess,'call',return_value=7))
        return probe,start

    def test_missing_signature_provider_selects_a_complete_owned_environment(self):
        probe,start=self.context(0)
        self.assertEqual(self.launcher.main(),7)
        self.assertEqual(Path(probe.call_args.args[0][0]),self.candidate)
        self.assertIn('nacl',probe.call_args.args[0][-1])
        self.assertEqual(Path(start.call_args.args[0][0]),self.candidate)

    def test_missing_signature_provider_everywhere_returns_installation_guidance(self):
        _,start=self.context(1);output=io.StringIO()
        with redirect_stderr(output):self.assertEqual(self.launcher.main(),2)
        self.assertIn('bootstrap.py',output.getvalue());start.assert_not_called()


if __name__=='__main__':unittest.main()
