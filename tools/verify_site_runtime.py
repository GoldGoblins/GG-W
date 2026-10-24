"""Exercise installed SITE runtimes with an owned synthetic PHP/database site.

No live SITE, imported user database, credentials or production origin is used.
--serve exposes only the fixture on loopback for a visible browser check.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import site_database as database, web_surface
from backend.platform_process import background_options, run_bounded
from backend.platform_support import host_environment, terminate_process_tree


MARKER = 'GG SITE PHP MYSQLI OK'
_PHP = r'''<?php
require __DIR__ . '/wp-config.php';
mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
try {
    [$host, $port] = explode(':', DB_HOST, 2);
    $connection = new mysqli($host, DB_USER, DB_PASSWORD, DB_NAME, (int)$port);
    $connection->set_charset('utf8mb4');
    $rows = $connection->query("SELECT option_name, option_value FROM gg_fixture_options WHERE option_name IN ('siteurl','home','gg_fixture_marker')");
    $values = [];
    while ($row = $rows->fetch_assoc()) { $values[$row['option_name']] = $row['option_value']; }
    $connection->close();
    $answer = ['status'=>'PASS', 'php_version'=>PHP_VERSION, 'mysqli'=>extension_loaded('mysqli'),
        'managed_ini'=>realpath(php_ini_loaded_file() ?: '') === realpath(dirname(PHP_BINARY).'/gg-php.ini'),
        'no_extra_ini'=>!php_ini_scanned_files(),
        'memory_hard_limit_correct'=>ini_get('memory_hard_limit_percent') === '125',
        'marker'=>$values['gg_fixture_marker'] ?? '', 'siteurl'=>$values['siteurl'] ?? '', 'home'=>$values['home'] ?? ''];
    if (PHP_SAPI === 'cli') { echo json_encode($answer); }
    else {
        header('Content-Type: text/html; charset=utf-8');
        header('Cache-Control: no-store');
        echo '<!doctype html><html lang="sv"><meta charset="utf-8"><title>GG SITE runtime verification</title>';
        echo '<style>body{background:#161616;color:#e8e8e8;font:18px monospace;padding:3rem}h1{color:#c8a97e}p{max-width:60ch}</style>';
        echo '<h1>GG SITE · WINDOWS RUNTIME</h1><p id="marker">'.htmlspecialchars($answer['marker']).'</p>';
        echo '<p>PHP '.htmlspecialchars(PHP_VERSION).' · mysqli · MariaDB</p>';
        echo '<p id="config">Managed INI: '.($answer['managed_ini'] && $answer['no_extra_ini'] && $answer['memory_hard_limit_correct'] ? 'PASS' : 'FAIL').'</p>';
        echo '<p id="scope">Separat syntetisk testwebbplats. Inga användardata eller produktionssystem.</p></html>';
    }
} catch (Throwable $error) {
    http_response_code(500);
    echo json_encode(['status'=>'ERROR','reason'=>'FIXTURE_DATABASE_READ_FAILED']);
}
'''


def unused_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def installed_runtime():
    from backend.site_runtime_setup import runtime_executable, php_arguments, php_environment
    php = runtime_executable('php')
    server = runtime_executable('mariadb', ('mariadbd', 'mysqld'))
    client = runtime_executable('mariadb', ('mariadb', 'mysql'))
    initialize = runtime_executable('mariadb', ('mariadb-install-db', 'mysql_install_db'))
    if not all((php, server, client, initialize)):
        raise RuntimeError('SITE_RUNTIME_NOT_INSTALLED')
    return {'php': php, 'server': server, 'client': client, 'initialize': initialize,
            'php_arguments': php_arguments(php), 'php_environment': php_environment(php)}


class RuntimeFixture:
    def __init__(self):
        self.temporary = None
        self.stack = ExitStack()
        self.php_process = None
        self.checks = {}
        self.diagnostics = {}
        self.phase = 'NEW'
        self.port = unused_port()
        self.web_port = unused_port()
        self.url = 'http://127.0.0.1:' + str(self.web_port) + '/'

    def __enter__(self):
        self.runtime = installed_runtime()
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-site-runtime-proof-')
        self.root = Path(self.temporary.name).resolve()
        control = os.environ.get('GG_SITE_RUNTIME_TEST_CONTROL')
        if control:
            target = Path(control)
            if target.parent.resolve() == (PROJECT / '.runtime').resolve() and target.name.startswith('site-runtime-test-control-'):
                with target.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps({'fixture': str(self.root)}) + '\n')
        self.site = self.root / 'site'
        self.site.mkdir()
        self.datadir = self.root / 'database'
        self.config = self.site / 'wp-config.php'
        self.config.write_text("<?php\ndefine('DB_NAME','gg_runtime_fixture');\ndefine('DB_USER','gg_fixture');\ndefine('DB_PASSWORD','');\ndefine('DB_HOST','old.invalid');\n$table_prefix='gg_fixture_';\n", encoding='utf-8')
        (self.site / 'index.php').write_text(_PHP, encoding='utf-8')
        self.dump = self.root / 'fixture.sql'
        self.dump.write_text("DROP TABLE IF EXISTS gg_fixture_options;\nCREATE TABLE gg_fixture_options (option_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,option_name VARCHAR(64) UNIQUE NOT NULL,option_value TEXT NOT NULL,autoload VARCHAR(20) NOT NULL DEFAULT 'yes');\nINSERT INTO gg_fixture_options(option_name,option_value) VALUES ('siteurl','https://old.invalid'),('home','https://old.invalid'),('gg_fixture_marker','" + MARKER + "');\n", encoding='utf-8')
        for module, key, value in (
            (database, 'SITE_ROOT', self.site), (database, 'WP_CONFIG', self.config),
            (database, 'DATA_DIR', self.datadir), (database, 'PID', self.root / 'server.pid'),
            (database, 'SOCK', self.root / 'server.sock'), (database, 'PORT', self.port),
            (database, '_SERVER_PROCESS', None), (web_surface, 'SITE_ROOT', self.site),
        ):
            self.stack.enter_context(patch.object(module, key, value))
        try:
            return self
        except BaseException:
            self.close()
            raise

    def verify(self):
        self.phase = 'SERVER_START'
        started = database.start_mysqld()
        if not started.startswith('PASS'):
            self.fail(started)
        self.checks['owned_loopback_server'] = database._owned_server()
        self.checks['server_reuse_verified'] = database.start_mysqld().startswith('PASS')
        denied, _out, _error, _trigger = run_bounded([self.runtime['client'], '--no-defaults',
            '--protocol=TCP', '--host=127.0.0.1', '--port=' + str(self.port), '--user=root',
            '--batch', '--binary-mode', '--local-infile=0', '-e', 'SELECT 1'],
            env={'PATH': str(Path(self.runtime['client']).parent)}, timeout=5, max_output_bytes=4096)
        self.checks['blank_root_authentication_rejected'] = denied != 0
        self.phase = 'FIRST_IMPORT'
        imported = database.import_sql_dump(self.dump.as_uri())
        if not imported.startswith('PASS'):
            self.fail(imported)
        self.checks['sql_import_and_postconditions'] = True
        result = self.php_result()
        self.checks['actual_php_mysqli_readback'] = (result.get('status') == 'PASS' and
            result.get('marker') == MARKER and result.get('mysqli') is True and
            result.get('siteurl') == 'http://127.0.0.1:8765' and result.get('home') == result.get('siteurl'))
        self.checks['actual_php_serving_configuration'] = all(result.get(key) is True for key in
            ('managed_ini', 'no_extra_ini', 'memory_hard_limit_correct', 'mysqli'))
        self.php_version = result.get('php_version', '')
        began = time.monotonic()
        interrupted = database._mysql(['-N', '-e', 'SELECT SLEEP(5)'], cancelled=lambda: time.monotonic() - began > .15)
        self.checks['actual_sql_cancel_bounded'] = interrupted.returncode != 0 and b'CANCELLED' in interrupted.stderr and time.monotonic() - began < 2
        next_result = database._mysql(['-N', '-e', 'SELECT 42'])
        self.checks['clean_query_after_cancel'] = next_result.returncode == 0 and next_result.stdout.strip() == b'42'
        bad = self.root / 'broken.sql'
        bad.write_text('INSERT INTO missing_fixture_table VALUES (1);\n', encoding='utf-8')
        self.checks['actual_sql_failure_is_partial'] = database.import_sql_dump(bad.as_uri()).startswith('PARTIAL')
        self.checks['valid_import_after_failure'] = database.import_sql_dump(self.dump.as_uri()).startswith('PASS')
        previous_pid = database._SERVER_PROCESS.pid
        stopped = database.stop_mysqld(only_started=True)
        restarted = database.start_mysqld()
        self.checks['authenticated_restart_preserves_data'] = (stopped.startswith('PASS') and restarted.startswith('PASS')
            and database._SERVER_PROCESS.pid != previous_pid and self.php_result().get('marker') == MARKER)
        from backend.site_database_vault import get_secret
        secret = get_secret(self.datadir)
        if secret is None:
            raise RuntimeError('SITE_RUNTIME_ADMIN_VAULT_MISSING')
        from backend.platform_process import process_arguments
        self.checks['admin_secret_not_in_arguments_or_config'] = (secret not in self.config.read_text(encoding='utf-8')
            and secret not in ' '.join(process_arguments(database._SERVER_PROCESS.pid)))
        self.checks['admin_secret_not_written_to_fixture_files'] = not self._secret_in_fixture(secret.encode('utf-8'))
        if not all(self.checks.values()):
            self.fail('SITE_RUNTIME_KNOWN_ANSWER_FAILED')
        self.phase = 'VERIFIED'
        return self.report()

    def fail(self, reason):
        import re
        self.diagnostics = {'phase': self.phase, 'client': database.last_client_status()}
        match = re.match(r'(?:(?:FAIL|PARTIAL): )?(SITE_[A-Z_]+)', reason)
        safe = match[1] if match else 'SITE_RUNTIME_KNOWN_ANSWER_FAILED'
        raise RuntimeError(safe + ' ' + json.dumps(self.diagnostics, sort_keys=True))

    def _secret_in_fixture(self, value):
        for path in self.root.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            tail = b''
            with path.open('rb') as handle:
                while block := handle.read(1024 * 1024):
                    packet = tail + block
                    if value in packet:
                        return True
                    tail = packet[-len(value):]
        return False

    def php_result(self):
        code, output, _error, trigger = run_bounded(self.runtime['php_arguments'] + [str(self.site / 'index.php')],
            env=self.runtime['php_environment'], timeout=8, max_output_bytes=16384)
        if code or trigger != 'NONE':
            raise RuntimeError('SITE_RUNTIME_PHP_QUERY_FAILED')
        try:
            return json.loads(output)
        except (ValueError, UnicodeError):
            raise RuntimeError('SITE_RUNTIME_PHP_RESPONSE_INVALID') from None

    def start_preview(self):
        argv = self.runtime['php_arguments'] + ['-S', '127.0.0.1:' + str(self.web_port), '-t', str(self.site), str(PROJECT / 'backend/site_php_router.php')]
        self.php_process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=self.runtime['php_environment'], **background_options())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.php_process.poll() is not None:
                raise RuntimeError('SITE_RUNTIME_PHP_SERVER_EXITED')
            try:
                with socket.create_connection(('127.0.0.1', self.web_port), .1):
                    self.checks['php_loopback_preview_started'] = True
                    return self.url
            except OSError:
                time.sleep(.02)
        raise RuntimeError('SITE_RUNTIME_PHP_SERVER_TIMEOUT')

    def report(self):
        return {'schema': 'gg.site-runtime-verification.v1', 'status': 'PASS' if all(self.checks.values()) else 'FAIL',
                'checks': dict(self.checks), 'php_version': getattr(self, 'php_version', ''),
                'diagnostics': dict(self.diagnostics),
                'scope': 'Owned synthetic PHP/WordPress-shaped options fixture only; no live SITE, user database or production verified.'}

    def close(self):
        if self.php_process is not None and self.php_process.poll() is None:
            terminate_process_tree(self.php_process.pid, force=True)
            self.php_process.wait(timeout=3)
        if self.temporary is not None:
            stopped = database.stop_mysqld(only_started=True)
            self.checks['database_stopped'] = stopped.startswith('PASS') and not database._listening()
            if not self.checks['database_stopped']:
                self.stack.close()
                raise RuntimeError('SITE_RUNTIME_DATABASE_STOP_FAILED')
            from backend.site_database_vault import delete_secret
            if self.datadir.is_dir():
                delete_secret(self.datadir)
        self.stack.close()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help='Keep the synthetic preview available for a visible browser check')
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('--seconds must be between 1 and 300')
    if os.name == 'nt':
        from backend.platform_process import apply_windows_worker_limits
        apply_windows_worker_limits(memory_bytes=1024 * 1024 * 1024, cpu_seconds=120)
    fixture = RuntimeFixture()
    try:
        with fixture:
            fixture.verify()
            if args.serve:
                print(json.dumps({**fixture.report(), 'status': 'READY', 'url': fixture.start_preview()}), flush=True)
                stop = threading.Event()
                def listen():
                    for line in sys.stdin:
                        if line.strip().lower() == 'stop':
                            stop.set(); return
                threading.Thread(target=listen, daemon=True).start()
                stop.wait(args.seconds)
        report = fixture.report()
        print(json.dumps(report), flush=True)
        return 0 if report['status'] == 'PASS' else 1
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        reason = str(exc)
        if not re_safe_reason(reason):
            reason = 'SITE_RUNTIME_VERIFICATION_FAILED'
        print(json.dumps({'schema': 'gg.site-runtime-verification.v1', 'status': 'FAIL', 'reason': reason,
                          'diagnostics': fixture.diagnostics}), flush=True)
        return 1


def re_safe_reason(value):
    import re
    return bool(re.fullmatch(r'(?:FAIL: )?SITE_[A-Z_]+', value))


if __name__ == '__main__':
    raise SystemExit(main())
