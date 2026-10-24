"""Actual installed Windows PHP + MariaDB integration, isolated from live SITE."""
from pathlib import Path
import os
import sys
import unittest
import tempfile
import time
import json
import subprocess
import shutil
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'tools'))
from verify_site_runtime import RuntimeFixture, installed_runtime
from backend import site_database as database


@unittest.skipUnless(os.name == 'nt', 'Native Windows runtime verification')
class SiteRuntimeWindowsTests(unittest.TestCase):
    def test_actual_host_preview_uses_managed_ini_and_recovers_after_server_exit(self):
        from PySide6.QtCore import QCoreApplication, QObject, QProcess
        from backend.chat_surface_host import ChatSurfaceHost
        from backend import web_surface
        class PreviewHost(QObject):
            def __init__(self):
                super().__init__()
                self._preview = None
                self._preview_origin = ''
                self._site_preview_fingerprint = ''
            def stopSitePreview(self):
                return ChatSurfaceHost.stopSitePreview(self)
        app = QCoreApplication.instance() or QCoreApplication([])
        host = PreviewHost()
        fixture = RuntimeFixture()
        with fixture:
            fixture.verify()
            try:
                with patch.object(web_surface, 'pick_preview_port', return_value=fixture.web_port), patch.dict(os.environ, {'GG_SYNTHETIC_PRIVATE_ENV': 'owned-test-value', 'PHPRC': 'untrusted.ini'}):
                    first = ChatSurfaceHost.startSitePreview(host)
                    self.assertTrue(first.startswith(fixture.url), first)
                    process = host._preview
                    self.assertEqual(process.state(), QProcess.ProcessState.Running)
                    self.assertIn('-c', process.arguments())
                    environment = process.processEnvironment()
                    self.assertFalse(environment.contains('GG_SYNTHETIC_PRIVATE_ENV'))
                    self.assertFalse(environment.contains('PHPRC'))
                    self.assertTrue(environment.value('PHP_INI_SCAN_DIR').endswith('empty-ini-scan'))
                    same = ChatSurfaceHost.startSitePreview(host)
                    self.assertEqual(first, same)
                    self.assertIs(host._preview, process)
                    process.kill(); process.waitForFinished(2000)
                    deadline = time.monotonic() + 2
                    while host._preview is not None and time.monotonic() < deadline:
                        app.processEvents(); time.sleep(.01)
                    self.assertIsNone(host._preview)
                    self.assertEqual(host._preview_origin, '')
                    self.assertEqual(ChatSurfaceHost.startSitePreview(host), first)
                    self.assertIsNotNone(host._preview)
            finally:
                host.stopSitePreview()
                app.processEvents()

    def test_shutdown_never_controls_a_database_started_by_another_instance(self):
        with patch.object(database, '_SERVER_PROCESS', None), patch.object(database, '_listening', return_value=True), patch.object(database, '_owned_server', return_value=True), patch.object(database, '_mysql', side_effect=AssertionError('Foreign shutdown forbidden')):
            self.assertIn('no current-instance', database.stop_mysqld(only_started=True))

    def test_existing_unmarked_database_is_not_automatically_rekeyed(self):
        with tempfile.TemporaryDirectory(prefix='gg-existing-db-policy-') as raw:
            datadir = Path(raw) / 'existing'
            (datadir / 'mysql').mkdir(parents=True)
            with patch.object(database, 'DATA_DIR', datadir), patch.object(database, '_tool', side_effect=AssertionError('Existing database tools must not run')):
                self.assertIn('EXISTING_DATADIR_REQUIRES_REVIEW', database.ensure_datadir())
                with patch.object(database, '_listening', return_value=True), patch.object(database, '_owned_server', return_value=True):
                    self.assertIn('EXISTING_DATADIR_REQUIRES_REVIEW', database.start_mysqld())
            self.assertFalse((datadir / '.gg-admin-auth-ready').exists())

    def test_real_php_database_import_recovery_and_shutdown(self):
        try:
            installed_runtime()
        except (ImportError, RuntimeError):
            self.skipTest('Optional managed SITE runtimes are not installed')
        fixture = RuntimeFixture()
        with fixture:
            report = fixture.verify()
            self.assertEqual(report['status'], 'PASS')
            self.assertTrue(report['checks']['actual_php_mysqli_readback'])
            self.assertTrue(report['checks']['actual_sql_cancel_bounded'])
            self.assertTrue(report['checks']['valid_import_after_failure'])
            url = fixture.start_preview()
            self.assertTrue(url.startswith('http://127.0.0.1:'))
        self.assertTrue(fixture.checks['database_stopped'])


if __name__ == '__main__':
    if os.environ.get('GG_SITE_RUNTIME_TEST_CHILD') == '1':
        if os.name == 'nt':
            from backend.platform_process import apply_windows_worker_limits
            apply_windows_worker_limits(memory_bytes=1024 * 1024 * 1024, cpu_seconds=120)
        unittest.main()
    else:
        # The controller has no Qt state. Its wall-clock watchdog remains
        # independent of both test callbacks and the owned database server.
        from backend.platform_process import background_options
        from backend.platform_support import terminate_process_tree
        runtime = PROJECT / '.runtime'
        runtime.mkdir(exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='site-runtime-test-control-', suffix='.jsonl', dir=runtime)
        os.close(descriptor)
        control = Path(name)
        env = os.environ.copy()
        env.update(GG_SITE_RUNTIME_TEST_CHILD='1', GG_SITE_RUNTIME_TEST_CONTROL=str(control))
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **background_options())
        try:
            stdout, stderr = child.communicate(timeout=120)
            sys.stdout.buffer.write(stdout)
            sys.stderr.buffer.write(stderr)
            code = child.returncode
        except subprocess.TimeoutExpired:
            terminate_process_tree(child.pid, force=True)
            child.communicate(timeout=5)
            # Job Object closure kills descendants; this removes only targets
            # explicitly recorded by this child, never other runtime fixtures.
            from backend.site_database_vault import delete_secret
            from backend.platform_files import is_link
            temp_parent = Path(tempfile.gettempdir()).resolve()
            for line in control.read_text(encoding='utf-8').splitlines()[:8]:
                try:
                    root = Path(json.loads(line)['fixture'])
                    if (root.parent.resolve() != temp_parent or not root.name.startswith('gg-site-runtime-proof-')
                            or is_link(root) or not root.is_dir()):
                        continue
                    resolved = root.resolve()
                    if resolved.parent != temp_parent:
                        continue
                    delete_secret(resolved / 'database')
                    shutil.rmtree(resolved)
                except (OSError, ValueError, KeyError, RuntimeError):
                    pass
            print('SITE_RUNTIME_TEST_SUITE_TIMEOUT', file=sys.stderr)
            code = 124
        finally:
            control.unlink(missing_ok=True)
        raise SystemExit(code)
