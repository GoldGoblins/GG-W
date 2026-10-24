"""SITE failure/recovery tests use only owned temporary trees and synthetic SQL."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile
import io
import struct

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import web_surface as web, site_database as database, site_jobs


class SiteResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-site-resilience-')
        self.folder = Path(self.temporary.name)
        self.root = self.folder / 'site'
        self.root.mkdir()
        (self.root / 'index.html').write_text('previous working site', encoding='utf-8')
        self.patches = [patch.object(web, 'SITE_ROOT', self.root),
                        patch.object(database, 'SITE_ROOT', self.root),
                        patch.object(database, 'WP_CONFIG', self.root / 'wp-config.php'),
                        patch.object(database, 'DATA_DIR', self.folder / 'database'),
                        patch.object(database, 'PID', self.folder / 'server.pid')]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temporary.cleanup)
        for item in self.patches:
            self.addCleanup(item.stop)

    def archive(self, entries):
        path = self.folder / ('source-' + str(time.monotonic_ns()) + '.zip')
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for name, body in entries:
                output.writestr(name, body)
        return path

    def unchanged(self):
        self.assertEqual((self.root / 'index.html').read_text(encoding='utf-8'), 'previous working site')
        self.assertFalse(list(self.folder.glob('.site-stage-*')))
        self.assertFalse(web._import_journal().exists())

    def config(self, prefix='custom_'):
        (self.root / 'wp-config.php').write_text("<?php\ndefine('DB_NAME', 'testdb');\ndefine('DB_USER', 'localuser');\ndefine('DB_PASSWORD', 'synthetic-only');\ndefine('DB_HOST', 'old.invalid');\n$table_prefix = '" + prefix + "';\n", encoding='utf-8')
        path = self.folder / 'owned.sql'
        path.write_text('SELECT 1;\n', encoding='utf-8')
        return path

    def test_invalid_filtered_and_interrupted_import_preserve_previous_site(self):
        broken = self.folder / 'broken.zip'; broken.write_bytes(b'not a zip')
        self.assertTrue(web.import_site_tree(str(broken)).startswith('FAIL'))
        self.unchanged()
        filtered = self.archive([('wp-config.php', 'excluded'), ('../escape', 'excluded')])
        self.assertTrue(web.import_site_tree(str(filtered)).startswith('FAIL'))
        self.unchanged()
        archive = self.archive([('index.html', 'replacement'), ('other.txt', 'second')])
        original = web._copy_imported_stream
        def fail_after_copy(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('synthetic write failure')
        with patch.object(web, '_copy_imported_stream', side_effect=fail_after_copy):
            self.assertTrue(web.import_site_tree(archive.as_uri()).startswith('FAIL'))
        self.unchanged()
        self.assertTrue(web.import_site_tree(archive.as_uri()).startswith('PASS'))
        self.assertEqual((self.root / 'index.html').read_text(), 'replacement')
        backups = list(self.folder.glob('site.bak.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'index.html').read_text(), 'previous working site')

    def test_expanded_limits_duplicate_paths_and_cancel_do_not_commit(self):
        archive = self.archive([('index.html', 'a' * 1000), ('second.txt', 'b')])
        for name, value in [('MAX_IMPORT_BYTES', 500), ('MAX_IMPORT_FILES', 1), ('MAX_IMPORT_ENTRIES', 1), ('IMPORT_TIMEOUT_SECONDS', 0)]:
            with self.subTest(name=name), patch.object(web, name, value):
                self.assertTrue(web.import_site_tree(str(archive)).startswith('FAIL'))
                self.unchanged()
        duplicate = self.archive([('index.html', 'one'), ('INDEX.HTML', 'two')])
        self.assertIn('DUPLICATE', web.import_site_tree(str(duplicate)))
        self.unchanged()
        stop = threading.Event()
        def progress(phase, current, total, extra):
            if phase == 'WRITE': stop.set()
        self.assertIn('CANCELLED', web.import_site_tree(str(archive), progress=progress, cancelled=stop.is_set))
        self.unchanged()

    def test_zip64_locator_cannot_override_prechecked_classic_directory(self):
        packet = io.BytesIO()
        with zipfile.ZipFile(packet, 'w') as archive:
            for index in range(3):
                archive.writestr(str(index) + '.txt', 'owned fixture')
        data = packet.getvalue()
        end = data.rfind(b'PK\x05\x06')
        classic = bytearray(data[end:])
        fields = struct.unpack('<4s4H2LH', classic)
        actual_size, offset = fields[5:7]
        zip64 = struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, 3, 3, actual_size, offset)
        locator = struct.pack('<4sLQL', b'PK\x06\x07', 0, end, 1)
        struct.pack_into('<HHLL', classic, 8, 1, 1, 1, offset)
        misleading = data[:end] + zip64 + locator + classic
        for comment in (b'', b'x' * 65535):
            with self.subTest(comment_bytes=len(comment)):
                candidate = bytearray(misleading)
                struct.pack_into('<H', candidate, len(candidate) - 2, len(comment))
                candidate.extend(comment)
                with patch.object(web, 'MAX_IMPORT_DIRECTORY_BYTES', 32):
                    with self.assertRaisesRegex(ValueError, 'ZIP64_OR_MULTIDISK'):
                        web._validated_site_zip(io.BytesIO(candidate))

    def test_journal_cleanup_failure_rolls_back_before_reporting_failure(self):
        archive = self.archive([('index.html', 'replacement')])
        original = Path.unlink
        def locked_journal(path, *args, **kwargs):
            if path == web._import_journal():
                raise PermissionError('synthetic sharing lock')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', locked_journal):
            result = web.import_site_tree(str(archive))
        self.assertTrue(result.startswith('FAIL'), result)
        self.assertEqual((self.root / 'index.html').read_text(encoding='utf-8'), 'previous working site')
        web._recover_site_import()
        self.unchanged()

    def test_commented_settings_cannot_satisfy_config_postconditions(self):
        from backend.php_config_literals import settings
        self.config()
        path = self.root / 'wp-config.php'
        text = path.read_text(encoding='utf-8')
        text = text.replace('<?php', "<?php\n// define('DB_HOST','comment.invalid');\n/* $table_prefix='wrong_'; */")
        path.write_text(text, encoding='utf-8')
        self.assertEqual(database._define('DB_HOST'), 'old.invalid')
        self.assertEqual(database._table_prefix(), 'custom_')
        self.assertTrue(database._point_wp_config_local())
        changed = path.read_text(encoding='utf-8')
        self.assertEqual(settings(changed)['DB_HOST'].value, '127.0.0.1:3307')
        self.assertIn("// define('DB_HOST','comment.invalid');", changed)
        for prefix in ("if (true) ", "if (true) { ", "include 'dynamic.php'; "):
            with self.subTest(prefix=prefix):
                uncertain = text.replace("define('DB_HOST',", prefix + "define('DB_HOST',")
                with self.assertRaisesRegex(ValueError, 'LITERAL_CONFIG_REQUIRED'):
                    settings(uncertain)
        with self.assertRaises(ValueError):
            settings(text + "\ndefine('DB_HOST','another.invalid');")

    def test_unsupported_executable_config_cannot_predefine_literal_bindings(self):
        from backend.php_config_literals import settings, replace_host
        for prefix in ("const DB_HOST='remote.invalid';", "$f='define'; ($f)('DB_HOST','remote.invalid');",
                       "$f='define'; ${'f'}('DB_HOST','remote.invalid');"):
            text = "<?php " + prefix + " define('DB_HOST','placeholder.invalid'); $table_prefix='wp_';"
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, 'LITERAL_CONFIG_REQUIRED'):
                replace_host(text, '127.0.0.1:3307')
        for prefix in ("false && $table_prefix='wp_';", "$$table_prefix='wp_';"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                settings("<?php define('DB_HOST','placeholder.invalid'); " + prefix)

    def test_canonical_wordpress_bootstrap_and_literal_punctuation_remain_supported(self):
        from backend.php_config_literals import settings, replace_host
        text = """<?php
define('DB_NAME','testdb');
define('DB_USER','user');
define('DB_PASSWORD','synthetic;only');
define('DB_HOST','old.invalid');
define('WP_DEBUG', false);
$table_prefix='wp_';
if (!defined('ABSPATH')) { define('ABSPATH', __DIR__ . '/'); }
require_once ABSPATH . 'wp-settings.php';
"""
        changed = replace_host(text, '127.0.0.1:3307')
        self.assertEqual(settings(changed)['DB_PASSWORD'].value, 'synthetic;only')
        self.assertEqual(settings(changed)['DB_HOST'].value, '127.0.0.1:3307')
        self.assertIn("require_once ABSPATH . 'wp-settings.php';", changed)

    def test_failed_directory_switch_rolls_back_and_crash_journal_recovers(self):
        archive = self.archive([('index.html', 'new')])
        original = web.atomic_replace
        def failed_switch(source, destination):
            if Path(source).name.startswith('.site-stage-') and Path(destination) == self.root:
                raise PermissionError('synthetic sharing lock')
            return original(source, destination)
        with patch.object(web, 'atomic_replace', side_effect=failed_switch):
            self.assertTrue(web.import_site_tree(str(archive)).startswith('FAIL'))
        self.unchanged()
        stage = self.folder / '.site-stage-owned123'; stage.mkdir()
        (stage / 'index.html').write_text('partial')
        backup = self.folder / 'site.bak.20261023T220000.abcdef123456'
        web._write_import_journal(stage, backup)
        os.replace(self.root, backup)
        web.ensure_site_root()
        self.unchanged()

    def test_links_and_nonlocal_sources_are_rejected(self):
        source = self.folder / 'source'; source.mkdir()
        outside = self.folder / 'outside'; outside.mkdir()
        (outside / 'private.txt').write_text('synthetic private fixture')
        link = source / 'linked'
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0)
        else:
            link.symlink_to(outside, target_is_directory=True)
        self.assertIn('LINK', web.import_site_tree(str(source)))
        self.unchanged()
        archive = self.folder / 'linked.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            info = zipfile.ZipInfo('link'); info.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(info, 'outside')
        self.assertIn('LINK', web.import_site_tree(str(archive)))
        self.unchanged()
        self.assertIsNone(web._local_import_path('file://remote.invalid/share/site.zip'))
        for name in ('C:/escape', 'file:stream', 'NUL.txt', 'folder/name.', '../escape',
                     '.env.production', 'nested/.npmrc', '.git/config', 'nested/.ssh/id_fixture'):
            self.assertIsNone(web._safe_import_rel(name))

    def test_editor_save_failure_keeps_old_file(self):
        with patch.object(web, 'atomic_replace', side_effect=OSError('synthetic replace failure')):
            with self.assertRaises(OSError):
                web.write_site_file('index.html', 'new content')
        self.unchanged()
        self.assertFalse(list(self.root.glob('.gg-save-*')))

    def test_sql_failure_is_partial_and_configuration_stays_intact(self):
        source = self.config()
        old = database.WP_CONFIG.read_bytes()
        ok = subprocess.CompletedProcess([], 0, b'', b'')
        with patch.object(database, 'start_mysqld', return_value='PASS'), patch.object(database, '_mysql', return_value=ok), \
                patch.object(database, 'rewrite_preview_origin', return_value='FAIL: simulated'):
            summary = database.import_sql_dump(source.as_uri())
        self.assertTrue(summary.startswith('PARTIAL'), summary)
        self.assertEqual(database.WP_CONFIG.read_bytes(), old)
        self.assertNotIn('synthetic-only', summary)
        with patch.object(database, 'MAX_SQL_BYTES', 2), patch.object(database, 'start_mysqld') as server:
            self.assertTrue(database.import_sql_dump(str(source)).startswith('FAIL'))
            server.assert_not_called()

    def test_sql_custom_prefix_checked_postconditions_and_atomic_config(self):
        source = self.config('custom_')
        commands = []
        def mysql(args, stdin=None, **kwargs):
            commands.append((args, stdin, kwargs))
            result = (b'home\thttp://127.0.0.1:8765\nsiteurl\thttp://127.0.0.1:8765\n'
                      if '-N' in args else b'')
            return subprocess.CompletedProcess([], 0, result, b'')
        with patch.object(database, 'start_mysqld', return_value='PASS'), patch.object(database, '_mysql', side_effect=mysql):
            summary = database.import_sql_dump(str(source))
        self.assertTrue(summary.startswith('PASS'), summary)
        self.assertTrue(any(b'`custom_options`' in (item[1] or b'') for item in commands))
        self.assertTrue(any(item[2].get('source') == source for item in commands))
        self.assertIn("define('DB_HOST', '127.0.0.1:3307')", database.WP_CONFIG.read_text())
        self.assertFalse(list(self.root.glob('.gg-config-*')))
        old = database.WP_CONFIG.read_bytes()
        with patch.object(database, 'atomic_replace', side_effect=OSError('fixture')):
            with self.assertRaises(OSError): database._point_wp_config_local()
        self.assertEqual(database.WP_CONFIG.read_bytes(), old)
        for origin in ('https://example.invalid', 'http://localhost.evil:12', 'http://localhost:2@evil', 'http://127.0.0.1:12/path'):
            self.assertTrue(database.rewrite_preview_origin(origin).startswith('FAIL'))

    def test_existing_database_port_requires_owned_server(self):
        with patch.object(database, '_listening', return_value=True), patch.object(database, '_owned_server', return_value=False), patch.object(database.subprocess, 'Popen') as spawn:
            self.assertIn('NOT_OWNED', database.start_mysqld())
            spawn.assert_not_called()
        database.PID.write_text('12345', encoding='ascii')
        arguments = ['mysqld.exe', '--datadir=' + str(database.DATA_DIR.resolve())]
        import psutil
        with patch.object(database, 'process_arguments', return_value=arguments), patch.object(psutil, 'Process') as process:
            process.return_value.net_connections.return_value = [SimpleNamespace(status=psutil.CONN_LISTEN,
                laddr=SimpleNamespace(ip='127.0.0.1', port=9999))]
            self.assertFalse(database._owned_server())
            process.return_value.net_connections.return_value[0].laddr.port = database.PORT
            self.assertTrue(database._owned_server())

    def test_application_import_cannot_rekey_admin_or_write_system_schema(self):
        dump = self.config()
        config = self.root / 'wp-config.php'
        original = config.read_text(encoding='utf-8')
        variants = [(original.replace("'DB_USER', 'localuser'", "'DB_USER', 'root'"), 'APPLICATION_ACCOUNT_REQUIRED'),
                    (original.replace("'DB_USER', 'localuser'", "'DB_USER', ''"), 'APPLICATION_ACCOUNT_REQUIRED'),
                    (original.replace("'DB_NAME', 'testdb'", "'DB_NAME', ''"), 'APPLICATION_SCHEMA_REQUIRED'),
                    (original.replace("'DB_NAME', 'testdb'", "'DB_NAME', 'mysql'"), 'APPLICATION_SCHEMA_REQUIRED')]
        for text, reason in variants:
            with self.subTest(reason=reason):
                config.write_text(text, encoding='utf-8')
                with patch.object(database, 'start_mysqld', side_effect=AssertionError('No server mutation permitted')), patch.object(database, '_mysql', side_effect=AssertionError('No admin mutation permitted')):
                    result = database.import_sql_dump(str(dump))
                self.assertIn(reason, result)

    def test_reimport_restores_the_configured_empty_application_password(self):
        dump = self.config()
        config = self.root / 'wp-config.php'
        config.write_text(config.read_text(encoding='utf-8').replace("'DB_PASSWORD', 'synthetic-only'", "'DB_PASSWORD', ''"), encoding='utf-8')
        statements = []
        def mysql(args, stdin=None, **_kwargs):
            if stdin:
                statements.append(stdin)
            return subprocess.CompletedProcess([], 0, b'', b'')
        with patch.object(database, 'start_mysqld', return_value='PASS'), patch.object(database, '_mysql', side_effect=mysql), patch.object(database, 'rewrite_preview_origin', return_value='PASS'), patch.object(database, '_point_wp_config_local', return_value=True):
            self.assertTrue(database.import_sql_dump(str(dump)).startswith('PASS'))
        self.assertIn(b"ALTER USER 'localuser'@'127.0.0.1' IDENTIFIED BY '';", statements[0])

    def test_mysql_stream_output_timeout_cancel_and_next_request(self):
        source = self.folder / 'synthetic.sql'; source.write_bytes(b'SELECT 1;\n' * 20000)
        actual = subprocess.Popen
        def execute(code):
            def launch(argv, **kwargs):
                self.assertIn('--host=127.0.0.1', argv)
                self.assertIn('--no-defaults', argv)
                self.assertIn('--binary-mode', argv)
                self.assertIn('--local-infile=0', argv)
                return actual([sys.executable, '-u', '-c', code], **kwargs)
            return launch
        with patch.object(database, '_tool', return_value=sys.executable):
            with patch.object(database.subprocess, 'Popen', side_effect=execute('import sys; print(len(sys.stdin.buffer.read()))')):
                result = database._mysql([], source=source)
            self.assertEqual(int(result.stdout.strip()), source.stat().st_size)
            self.assertEqual(result.returncode, 0)
            with patch.object(database, 'MAX_MYSQL_OUTPUT', 100), patch.object(database.subprocess, 'Popen', side_effect=execute('import sys;sys.stdout.write("x"*10000)')):
                result = database._mysql([])
            self.assertIn(b'OUTPUT_LIMIT', result.stderr)
            self.assertLessEqual(len(result.stdout), 100)
            with patch.object(database, 'SQL_TIMEOUT_SECONDS', .1), patch.object(database.subprocess, 'Popen', side_effect=execute('import time;time.sleep(5)')):
                result = database._mysql([])
            self.assertIn(b'TIMEOUT', result.stderr)
            with patch.object(database.subprocess, 'Popen', side_effect=execute('import time;time.sleep(5)')):
                result = database._mysql([], cancelled=lambda: True)
            self.assertIn(b'CANCELLED', result.stderr)
            with patch.object(database.subprocess, 'Popen', side_effect=execute('print("next request clean")')):
                self.assertEqual(database._mysql([]).stdout.strip(), b'next request clean')
            with patch.object(database.subprocess, 'Popen', side_effect=execute('import os;os.close(0);print("incomplete input")')):
                result = database._mysql([], source=source)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'INPUT_FAILED', result.stderr)

    def test_php_offline_assessment_and_missing_runtime(self):
        self.assertEqual(web.php_version_assessment('8.4.27')['status'], 'UPSTREAM_FIXED_VERSION')
        self.assertEqual(web.php_version_assessment('8.4.26')['status'], 'POTENTIALLY_VULNERABLE')
        for version in ('8.4.27-vendor1', '8.6.0RC4', 'garbage', '8.1.2-1ubuntu2.28'):
            self.assertEqual(web.php_version_assessment(version)['status'], 'UNKNOWN')
        with patch.object(web, '_php_executable', return_value=''), patch.object(web, '_php_image_present', return_value=False):
            health = web.php_runtime_health(refresh=True)
        self.assertEqual(health['status'], 'NOT_INSTALLED')
        self.assertEqual(health['runtime'], 'STATIC')
        with patch.object(web, '_podman_executable', return_value='owned-podman'), patch.object(web.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as called:
            self.assertTrue(web._php_image_present())
            self.assertEqual(called.call_args.args[0][0], 'owned-podman')


class SiteUiTests(unittest.TestCase):
    def test_qml_jobs_keep_gui_responsive_and_render_health(self):
        from backend.platform_process import run_bounded
        with tempfile.TemporaryDirectory(prefix='gg-site-qt-') as temporary:
            env = {'GG_SITE_QT_TEST_ROOT': temporary, 'GG_DESKTOP_STATE_ROOT': str(Path(temporary) / 'state'),
                   'GG_DESKTOP_DATA_ROOT': str(Path(temporary) / 'data'), 'QT_QPA_PLATFORM': 'offscreen',
                   'QT_QUICK_BACKEND': 'software', 'QT_QUICK_CONTROLS_STYLE': 'Basic', 'PYTHONUTF8': '1'}
            code, out, err, reason = run_bounded([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--qt-probe'],
                cwd=PROJECT, env=env, timeout=35, max_output_bytes=65536)
            detail = (out + err).decode('utf-8', errors='replace')
            self.assertEqual(reason, 'NONE', detail)
            self.assertEqual(code, 0, detail)
            self.assertIn('SITE_QT_ASYNC_HEALTH=PASS', detail)


def qt_probe():
    import json
    from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQuick import QQuickItem
    from backend.chat_surface_host import ChatSurfaceHost

    app = QApplication([])
    folder = Path(os.environ['GG_SITE_QT_TEST_ROOT'])
    web.SITE_ROOT = folder / 'site'; web.SITE_ROOT.mkdir()
    (web.SITE_ROOT / 'index.html').write_text('old')
    archive = folder / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('index.html', '<h1>new owned local site</h1>')

    class Bridge(QObject):
        siteImportProgress = Signal(str, int, int, str)
        nativeWebViewReady = Property(bool, lambda self: False, constant=True)
        def __init__(self):
            super().__init__()
            self._preview_origin = ''
            self._site_preview_fingerprint = ''
        @Slot(str, str, result=str)
        def siteStart(self, kind, source): return ChatSurfaceHost.siteStart(self, kind, source)
        @Slot(str, result=str)
        def siteStatus(self, job): return ChatSurfaceHost.siteStatus(self, job)
        @Slot(str, result=str)
        def siteCancel(self, job): return ChatSurfaceHost.siteCancel(self, job)
        @Slot(str, result=str)
        def sitePhpVersionAssessment(self, value): return ChatSurfaceHost.sitePhpVersionAssessment(self, value)
        @Slot(result=bool)
        def stopSitePreview(self): self._preview_origin = ''; return True
        @Slot(result=str)
        def listSiteFiles(self): return web.list_site_files()
        @Slot(result=str)
        def preferredSiteFile(self): return web.preferred_site_file()
        @Slot(str, result=str)
        def readSiteFile(self, name): return web.read_site_file(name)
        @Slot(str, result=str)
        def siteFileUrl(self, name): return web.site_file_url(name)
        @Slot(result=bool)
        def ensureWebEngine(self): return False
        @Slot(result=str)
        def sitePreviewOrigin(self): return ''
        @Slot(result=str)
        def loadScratchFiles(self): return '[]'
        @Slot(result=str)
        def defaultWebUrl(self): return 'about:blank'
        @Slot(result=str)
        def defaultBrowseUrl(self): return 'about:blank'
        @Slot(str, result=bool)
        def startChatTerminal(self, terminal_id): return True

    bridge, engine = Bridge(), QQmlApplicationEngine()
    engine.rootContext().setContextProperty('testBridge', bridge)
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    source = '''import QtQuick
import QtQuick.Window
import "COMPONENTS"
Window {
    width: 1200; height: 760; visible: false
    property var surfaceHost: testBridge
    function setDeskCursor(item, x, y, shape) {}
    WorkspaceSurface { anchors.fill: parent; hostKind: "SITE" }
}'''.replace('COMPONENTS', QUrl.fromLocalFile(str(PROJECT / 'qml/components')).toString())
    engine.loadData(source.encode('utf-8'), QUrl.fromLocalFile(str(folder / 'fixture.qml')))
    until = time.monotonic() + 10
    while not engine.rootObjects() and time.monotonic() < until:
        app.processEvents(); time.sleep(.001)
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    pane = window.findChild(QQuickItem, 'workspaceSurface')
    assert pane is not None
    js = engine.newQObject(pane)
    def call(name, *args):
        result = js.property(name).callWithInstance(js, [engine.toScriptValue(arg) for arg in args])
        assert not result.isError(), result.toString()
        return result
    def wait(predicate):
        until = time.monotonic() + 10
        while not predicate() and time.monotonic() < until:
            app.processEvents(); time.sleep(.002)
        assert predicate(), ('Timed out', warnings[-8:])
    heartbeats = []
    timer = QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: heartbeats.append(1)); timer.start()
    original = web._copy_imported_stream
    def slow(*args, **kwargs):
        for _ in range(20):
            kwargs['budget'].check(); time.sleep(.01)
        return original(*args, **kwargs)
    with patch.object(web, '_copy_imported_stream', side_effect=slow):
        call('startSiteJob', 'TREE', archive.as_uri())
        wait(lambda: str(pane.property('siteJobState')) not in ('RUNNING', 'CANCELLING'))
    assert pane.property('siteJobState') == 'DONE', pane.property('siteImportStatus')
    assert len(heartbeats) >= 5, 'GUI heartbeat blocked by import'
    assert (web.SITE_ROOT / 'index.html').read_text() == '<h1>new owned local site</h1>'
    previous = (web.SITE_ROOT / 'index.html').read_bytes()
    with patch.object(web, '_copy_imported_stream', side_effect=slow):
        call('startSiteJob', 'TREE', archive.as_uri())
        call('cancelSiteJob')
        wait(lambda: str(pane.property('siteJobState')) not in ('RUNNING', 'CANCELLING'))
    assert pane.property('siteJobState') == 'CANCELLED'
    assert (web.SITE_ROOT / 'index.html').read_bytes() == previous
    executable = folder / 'synthetic-php.exe'; executable.write_bytes(b'fixture-one')
    bridge._preview_origin = 'http://127.0.0.1:8765'
    with patch.object(web, '_php_executable', return_value=str(executable)):
        bridge._site_preview_fingerprint = web.php_runtime_identity()
        executable.write_bytes(b'fixture-two-changed')
        with patch('backend.platform_process.run_bounded', return_value=(0, b'8.4.27', b'', 'NONE')):
            call('startSiteJob', 'HEALTH', '')
            wait(lambda: str(pane.property('siteJobState')) not in ('RUNNING', 'CANCELLING'))
    label = window.findChild(QQuickItem, 'workspaceSiteHealthStatus')
    assert label is not None and '8.4.27' in label.property('text'), pane.property('siteHealthSummary')
    assert 'RESTART PREVIEW REQUIRED' in label.property('text')
    actual_health = pane.property('siteHealthSummary')
    call('assessSitePhpVersion', '8.4.26')
    assessment = window.findChild(QQuickItem, 'workspaceSitePhpVersionResult')
    assert assessment is not None and 'POTENTIALLY_VULNERABLE' in assessment.property('text')
    assert 'running server not verified' in assessment.property('text')
    assert pane.property('siteHealthSummary') == actual_health
    call('assessSitePhpVersion', '8.1.2-1ubuntu2.28')
    assert 'UNKNOWN' in assessment.property('text')
    faults = [message for message in warnings if any(marker in message for marker in
              ('TypeError:', 'ReferenceError:', 'Cannot assign', 'Unable to assign', 'Binding loop', 'is not a type'))]
    assert not faults, faults
    timer.stop(); window.close()
    from shiboken6 import delete
    delete(engine)
    print('SITE_QT_ASYNC_HEALTH=PASS', flush=True)


if __name__ == '__main__':
    if '--qt-probe' in sys.argv:
        qt_probe()
    else:
        unittest.main()
