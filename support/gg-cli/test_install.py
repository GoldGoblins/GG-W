"""Install recipes stay explicit and use the returned private-venv Python."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('gg_cli_install_fixture', SOURCE/'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallRecipes(unittest.TestCase):
    def test_all_three_plans_are_read_only_and_exactly_pinned(self):
        for platform in ('windows', 'linux', 'termux'):
            output = io.StringIO()
            with redirect_stdout(output), patch.object(installer, 'bootstrap_module') as bootstrap, \
                 patch.object(installer.subprocess, 'call') as launch:
                self.assertEqual(installer.main(['--platform', platform, '--check']), 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(plan['platform'], platform)
            self.assertFalse(plan['network_requested'])
            self.assertFalse(plan['node_start'])
            self.assertEqual(plan['environment'], 'PRIVATE_PER_USER_VENV')
            self.assertEqual(len(plan['dependencies']), 6)
            self.assertTrue(all('==' in name for name in plan['dependencies']))
            self.assertFalse(any('pyside' in name.lower() for name in plan['dependencies']))
            bootstrap.assert_not_called(); launch.assert_not_called()

    def test_launch_uses_exact_bootstrap_interpreter_even_with_other_python_environments(self):
        executable = Path('/fixture/private venv/Scripts/python.exe')
        bootstrap = SimpleNamespace(install=Mock(return_value=executable), default_home=Mock(return_value=Path('/fixture/user home')))
        with patch.object(installer, 'host_platform', return_value='windows'), \
             patch.object(installer, 'bootstrap_module', return_value=bootstrap), \
             patch.object(installer.subprocess, 'call', return_value=0) as launch:
            self.assertEqual(installer.main(['--platform', 'windows', '--launch']), 0)
        bootstrap.install.assert_called_once_with(Path('/fixture/user home/venv'), False)
        self.assertEqual(launch.call_args.args[0], [str(executable), '-B', str(installer.project_root()/'gg-cli.py')])

    def test_wrong_profile_cannot_install_and_optional_sdk_is_explicit(self):
        with redirect_stderr(io.StringIO()), patch.object(installer, 'host_platform', return_value='linux'), \
             patch.object(installer, 'bootstrap_module') as bootstrap:
            self.assertEqual(installer.main(['--platform', 'windows']), 2)
            bootstrap.assert_not_called()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(installer.main(['--platform', 'termux', '--wallet-signing', '--check']), 0)
        self.assertIn('solders==0.29.0', json.loads(output.getvalue())['dependencies'])

    def test_termux_detection_does_not_mislabel_normal_linux(self):
        with patch.object(installer.sys, 'platform', 'linux'):
            self.assertEqual(installer.host_platform({}), 'linux')
            self.assertEqual(installer.host_platform({'TERMUX_VERSION': 'fixture'}), 'termux')
            self.assertEqual(installer.host_platform({'PREFIX': '/data/data/com.termux/files/usr'}), 'termux')


if __name__ == '__main__':
    unittest.main()
