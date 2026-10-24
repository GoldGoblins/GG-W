"""Bounded local SITE database import; DDL failures are honestly PARTIAL."""
from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_support import runtime_root, local_file_path, terminate_process_tree, host_environment
from backend.platform_process import background_options, process_arguments, run_bounded
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, is_link, atomic_replace, sync_directory
import os
import re
import shutil
import socket
import stat
import subprocess
import threading
import time
import uuid
import atexit
import secrets
from pathlib import Path
from backend.web_surface import SITE_ROOT

STATE = Path(str(STATE_ROOT))
DATA_DIR = STATE / 'mariadb'
SOCK = runtime_root() / 'gg-site-mysql.sock'
PID = runtime_root() / 'gg-site-mysql.pid'
PORT = 3307
MYSQLD = '/usr/bin/mysqld'
MYSQL = '/usr/bin/mysql'
INSTALL_DB = '/usr/bin/mariadb-install-db'
WP_CONFIG = SITE_ROOT / 'wp-config.php'
WP_CONFIG_BAK = SITE_ROOT / 'wp-config.one.com.bak'
MAX_SQL_BYTES = 512 * 1024 * 1024
SQL_TIMEOUT_SECONDS = 180
MAX_MYSQL_OUTPUT = 65536
_DB_LOCK = threading.Lock()
_SERVER_LOCK = threading.RLock()
_SERVER_PROCESS = None
_CLIENT_STATUS = threading.local()


def _tool(path, names):
    if Path(path).is_file():
        return path
    if os.name == 'nt':
        from backend.site_runtime_setup import runtime_executable
        managed = runtime_executable('mariadb', names)
        if managed:
            return managed
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    if os.name == 'nt':
        for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            root = os.environ.get(variable)
            if root:
                for pattern in ('MariaDB */bin', 'MariaDB/bin', 'Programs/MariaDB*/bin', 'MySQL/MySQL Server */bin'):
                    for folder in sorted(Path(root).glob(pattern), reverse=True):
                        for name in names:
                            candidate = folder / (name + '.exe' if not name.endswith('.exe') else name)
                            if candidate.is_file() and not is_link(candidate):
                                return str(candidate)
    return ''


def _config_text():
    from backend.web_surface import _assert_no_links
    _assert_no_links(WP_CONFIG)
    fd = secure_open(WP_CONFIG, os.O_RDONLY | NOFOLLOW | CLOEXEC | NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        meta = os.fstat(handle.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > 262144:
            raise ValueError('SITE_DATABASE_CONFIG_INVALID')
        return handle.read(262145).decode('utf-8')


def _define(name):
    from backend.php_config_literals import settings
    item = settings(_config_text()).get(name)
    return item.value if item is not None else ''


def _identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', value):
        raise ValueError('SITE_DATABASE_IDENTIFIER_INVALID')
    return value


def _table_prefix():
    from backend.php_config_literals import settings
    item = settings(_config_text()).get('table_prefix')
    if item is None or len(item.value) > 56:
        raise ValueError('SITE_DATABASE_TABLE_PREFIX_UNKNOWN')
    return _identifier(item.value)


def _listening():
    try:
        with socket.create_connection(('127.0.0.1', PORT), 0.2):
            return True
    except OSError:
        return False


def _owned_server():
    try:
        import psutil
        if is_link(PID) or PID.stat().st_size > 32:
            return False
        fd = secure_open(PID, os.O_RDONLY | NOFOLLOW | CLOEXEC | NONBLOCK)
        with os.fdopen(fd, 'r', encoding='ascii') as handle:
            pid = int(handle.read(33).strip())
        arguments = process_arguments(pid)
        wanted = '--datadir=' + str(DATA_DIR.resolve())
        if not (arguments and Path(arguments[0]).stem.lower() in ('mysqld', 'mariadbd')
                and wanted.casefold() in [arg.casefold() for arg in arguments]):
            return False
        return any(connection.status == psutil.CONN_LISTEN and connection.laddr
                   and connection.laddr.ip == '127.0.0.1' and connection.laddr.port == PORT
                   for connection in psutil.Process(pid).net_connections(kind='inet'))
    except (OSError, ValueError, psutil.Error):
        return False


def ensure_datadir():
    from backend.web_surface import _assert_no_links
    _assert_no_links(DATA_DIR)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    initialized = (DATA_DIR / 'mysql').is_dir()
    initializing = DATA_DIR.with_name(DATA_DIR.name + '.gg-initializing')
    authenticated = DATA_DIR / '.gg-admin-auth-ready'
    if is_link(initializing) or is_link(authenticated):
        return 'FAIL: SITE_DATABASE_AUTH_MARKER_INVALID'
    if initialized:
        if os.name == 'nt' and not authenticated.is_file() and not initializing.is_file():
            return 'FAIL: SITE_DATABASE_EXISTING_DATADIR_REQUIRES_REVIEW'
        return 'PASS: datadir exists'
    executable = _tool(INSTALL_DB, ('mariadb-install-db', 'mysql_install_db'))
    if not executable:
        return 'FAIL: SITE_DATABASE_TOOLS_NOT_INSTALLED'
    if os.name == 'nt':
        if not initializing.exists():
            fd = secure_open(initializing, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(b'GG fresh SITE initialization\n')
    arguments = [executable, '--datadir=' + str(DATA_DIR)]
    if os.name != 'nt':
        arguments[1:1] = ['--no-defaults', '--auth-root-authentication-method=normal', '--skip-test-db']
    code, _, _, trigger = run_bounded(arguments, timeout=30, max_output_bytes=MAX_MYSQL_OUTPUT)
    if code != 0 or trigger != 'NONE':
        return 'FAIL: SITE_DATABASE_INITIALIZATION_FAILED'
    return 'PASS: datadir created'


def _secure_datadir():
    """Bootstrap a fresh Windows instance offline; no blank-root TCP server."""
    if os.name != 'nt':
        return 'PASS: platform database authentication unchanged'
    from backend.site_database_vault import get_secret, put_secret
    marker = DATA_DIR / '.gg-admin-auth-ready'
    initializing = DATA_DIR.with_name(DATA_DIR.name + '.gg-initializing')
    if marker.is_file():
        return 'PASS: database authentication ready' if get_secret(DATA_DIR) else 'FAIL: SITE_DATABASE_ADMIN_CREDENTIAL_UNAVAILABLE'
    if not initializing.is_file() or is_link(initializing):
        return 'FAIL: SITE_DATABASE_EXISTING_DATADIR_REQUIRES_REVIEW'
    password = get_secret(DATA_DIR)
    if not password:
        password = secrets.token_hex(32)
        put_secret(DATA_DIR, password)
    if not re.fullmatch(r'[a-f0-9]{64}', password):
        return 'FAIL: SITE_DATABASE_ADMIN_CREDENTIAL_INVALID'
    executable = _tool(MYSQLD, ('mariadbd', 'mysqld'))
    if not executable:
        return 'FAIL: SITE_DATABASE_TOOLS_NOT_INSTALLED'
    # --bootstrap never accepts client connections. Only password hashes enter
    # grant tables; SQL and the secret remain in stdin/current process memory.
    sql = ("FLUSH PRIVILEGES;\n"
        "ALTER USER 'root'@'localhost' IDENTIFIED BY '" + password + "';\n"
        "CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '" + password + "';\n"
        "ALTER USER 'root'@'127.0.0.1' IDENTIFIED BY '" + password + "';\n"
        "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;\n"
        "DELETE FROM mysql.global_priv WHERE User='' OR (User='root' AND Host NOT IN ('localhost','127.0.0.1'));\n"
        "FLUSH PRIVILEGES;\n")
    command = [executable, '--no-defaults', '--bootstrap', '--skip-networking', '--skip-log-bin',
               '--console', '--datadir=' + str(DATA_DIR.resolve())]
    result = _bounded_database_process(command, stdin=sql.encode('ascii'), timeout=30)
    if result.returncode:
        return 'FAIL: SITE_DATABASE_AUTH_BOOTSTRAP_FAILED'
    fd = secure_open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(b'GG vault-backed local database authentication v1\n')
        handle.flush(); os.fsync(handle.fileno())
    initializing.unlink(missing_ok=True)
    return 'PASS: database authentication ready'


def start_mysqld():
    with _SERVER_LOCK:
        try:
            return _start_mysqld_locked()
        except (OSError, ValueError, RuntimeError) as exc:
            reason = str(exc)
            if not re.fullmatch(r'SITE_[A-Z_]+', reason):
                reason = 'SITE_DATABASE_START_FAILED'
            return 'FAIL: ' + reason


def _start_mysqld_locked():
    global _SERVER_PROCESS
    if _listening():
        if not _owned_server():
            return 'FAIL: SITE_DATABASE_PORT_NOT_OWNED'
        if os.name == 'nt':
            from backend.site_database_vault import get_secret
            marker = DATA_DIR / '.gg-admin-auth-ready'
            if not marker.is_file() or is_link(marker) or not get_secret(DATA_DIR):
                return 'FAIL: SITE_DATABASE_EXISTING_DATADIR_REQUIRES_REVIEW'
            verified = _mysql(['-N', '-e', 'SELECT 1'])
            if verified.returncode or verified.stdout.strip() != b'1':
                return 'FAIL: SITE_DATABASE_ADMIN_AUTHENTICATION_FAILED'
        return 'PASS: mysqld already running'
    executable = _tool(MYSQLD, ('mariadbd', 'mysqld'))
    if not executable:
        return 'FAIL: SITE_DATABASE_TOOLS_NOT_INSTALLED'
    ready = ensure_datadir()
    if not ready.startswith('PASS'):
        return ready
    ready = _secure_datadir()
    if not ready.startswith('PASS'):
        return ready
    PID.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    arguments = [executable, '--no-defaults', '--datadir=' + str(DATA_DIR.resolve()),
                 '--pid-file=' + str(PID), '--bind-address=127.0.0.1', '--port=' + str(PORT), '--skip-networking=0',
                 '--skip-log-bin', '--local-infile=0', '--skip-name-resolve', '--max-connections=16',
                 '--max-allowed-packet=64M', '--innodb-buffer-pool-size=64M', '--tmp-table-size=16M', '--max-heap-table-size=16M']
    if os.name != 'nt':
        arguments.append('--socket=' + str(SOCK))
    proc = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True,
                            env=host_environment({'PATH': str(Path(executable).parent)}), **background_options())
    proc._gg_site_target = (str(DATA_DIR.resolve()), PORT)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return 'FAIL: SITE_DATABASE_SERVER_EXITED'
        if _listening() and _owned_server():
            _SERVER_PROCESS = proc
            if os.name == 'nt':
                verified = _mysql(['-N', '-e', 'SELECT 1'])
                if verified.returncode or verified.stdout.strip() != b'1':
                    terminate_process_tree(proc.pid, force=True)
                    proc.wait(timeout=3)
                    _SERVER_PROCESS = None
                    return 'FAIL: SITE_DATABASE_ADMIN_AUTHENTICATION_FAILED'
            return 'PASS: mysqld started'
        time.sleep(0.05)
    terminate_process_tree(proc.pid, force=True)
    proc.wait(timeout=3)
    return 'FAIL: SITE_DATABASE_START_TIMEOUT'


def stop_mysqld(*, timeout=8.0, only_started=False):
    """Stop only the database instance bound to this configured SITE datadir.

    A clean SQL shutdown flushes InnoDB. Forced termination is a final bounded
    fallback and only applies to the child this process actually started.
    """
    global _SERVER_PROCESS
    with _SERVER_LOCK:
        process = _SERVER_PROCESS
        if process is not None and getattr(process, '_gg_site_target', None) != (str(DATA_DIR.resolve()), PORT):
            process = None
        if process is not None and process.poll() is not None:
            _SERVER_PROCESS = None
            process = None
        if only_started and process is None:
            return 'PASS: no current-instance database to stop'
        if not _listening():
            if process is not None and process.poll() is None:
                terminate_process_tree(process.pid, force=True)
                process.wait(timeout=3)
            if _SERVER_PROCESS is process:
                _SERVER_PROCESS = None
            return 'PASS: local database stopped'
        if not _owned_server():
            return 'FAIL: SITE_DATABASE_PORT_NOT_OWNED'
        deadline = time.monotonic() + max(.1, min(float(timeout), 15.0))
        try:
            _mysql(['-e', 'SHUTDOWN'], cancelled=lambda: time.monotonic() >= deadline)
        except (OSError, ValueError, RuntimeError):
            pass
        while time.monotonic() < deadline:
            if process is not None:
                if process.poll() is not None:
                    process.wait(timeout=1)
                    _SERVER_PROCESS = None
                    return 'PASS: local database stopped'
            elif not _listening():
                return 'PASS: local database stopped'
            time.sleep(.02)
        if process is not None and process.poll() is None:
            terminate_process_tree(process.pid, force=True)
            process.wait(timeout=3)
            _SERVER_PROCESS = None
            return 'PASS: local database stopped after shutdown timeout'
        return 'FAIL: SITE_DATABASE_STOP_TIMEOUT'


def _stop_started_server():
    process = _SERVER_PROCESS
    if process is not None and process.poll() is None:
        stop_mysqld(only_started=True)


atexit.register(_stop_started_server)


def _mysql(args, stdin=None, *, source=None, cancelled=None):
    executable = _tool(MYSQL, ('mariadb', 'mysql'))
    if not executable:
        _CLIENT_STATUS.value = {'returncode': 127, 'reason': 'SITE_DATABASE_TOOLS_NOT_INSTALLED', 'mysql_error': 0, 'elapsed_ms': 0}
        return subprocess.CompletedProcess([], 127, b'', b'SITE_DATABASE_TOOLS_NOT_INSTALLED')
    command = [executable, '--no-defaults', '--protocol=TCP', '--host=127.0.0.1',
               '--port=' + str(PORT), '--user=root', '--batch', '--raw',
               '--binary-mode', '--local-infile=0'] + args
    password = None
    if os.name == 'nt':
        from backend.site_database_vault import get_secret
        password = get_secret(DATA_DIR)
    return _bounded_database_process(command, stdin, source=source, cancelled=cancelled, password=password)


def _bounded_database_process(command, stdin=None, *, source=None, cancelled=None, password=None, timeout=None):
    began = time.monotonic()
    input_file = None
    if source is not None:
        fd = secure_open(source, os.O_RDONLY | NOFOLLOW | CLOEXEC | NONBLOCK)
        input_file = os.fdopen(fd, 'rb')
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_SQL_BYTES:
            input_file.close()
            raise ValueError('SITE_DATABASE_SQL_SIZE_LIMIT')
    elif stdin is not None and len(stdin) > MAX_MYSQL_OUTPUT:
        raise ValueError('SITE_DATABASE_COMMAND_SIZE_LIMIT')
    try:
        environment = host_environment({'PATH': str(Path(command[0]).parent)})
        if password is not None:
            environment['MYSQL_PWD'] = password
        process = subprocess.Popen(command, stdin=subprocess.PIPE if input_file or stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            env=environment, **background_options())
        buffers, overflow, mutex = [bytearray(), bytearray()], threading.Event(), threading.Lock()
        def drain(index, pipe):
            try:
                while True:
                    block = os.read(pipe.fileno(), 4096)
                    if not block:
                        return
                    with mutex:
                        room = MAX_MYSQL_OUTPUT - sum(map(len, buffers))
                        buffers[index].extend(block[:room])
                        if len(block) > room:
                            overflow.set()
                            return
            except (OSError, ValueError):
                return
        readers = [threading.Thread(target=drain, args=(i, pipe), daemon=True)
                   for i, pipe in enumerate((process.stdout, process.stderr))]
        for thread in readers:
            thread.start()
        writer, input_error, input_limit = None, threading.Event(), threading.Event()
        if stdin or input_file:
            def send():
                try:
                    consumed = 0
                    while True:
                        block = input_file.read(256 * 1024) if input_file else stdin
                        if not block:
                            break
                        consumed += len(block)
                        if consumed > (MAX_SQL_BYTES if input_file else MAX_MYSQL_OUTPUT):
                            input_limit.set()
                            break
                        remaining = memoryview(block)
                        while remaining:
                            count = process.stdin.write(remaining)
                            if not count:
                                raise BrokenPipeError()
                            remaining = remaining[count:]
                        if input_file is None:
                            break
                except (BrokenPipeError, OSError, ValueError):
                    input_error.set()
                finally:
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        input_error.set()
            writer = threading.Thread(target=send, daemon=True)
            writer.start()
        deadline, reason = time.monotonic() + (SQL_TIMEOUT_SECONDS if timeout is None else timeout), ''
        try:
            while process.poll() is None or any(t.is_alive() for t in readers) or (writer and writer.is_alive()):
                if cancelled and cancelled():
                    reason = 'SITE_DATABASE_CANCELLED'; break
                if overflow.is_set():
                    reason = 'SITE_DATABASE_OUTPUT_LIMIT'; break
                if input_error.is_set():
                    reason = 'SITE_DATABASE_INPUT_FAILED'; break
                if input_limit.is_set():
                    reason = 'SITE_DATABASE_SQL_SIZE_LIMIT'; break
                if time.monotonic() >= deadline:
                    reason = 'SITE_DATABASE_TIMEOUT'; break
                time.sleep(.01)
            if reason or process.poll() is None:
                terminate_process_tree(process.pid, force=True)
            process.wait(timeout=3)
            for thread in readers:
                thread.join(timeout=1)
            if writer:
                writer.join(timeout=1)
            if overflow.is_set() and not reason:
                reason = 'SITE_DATABASE_OUTPUT_LIMIT'
            if input_error.is_set() and not reason:
                reason = 'SITE_DATABASE_INPUT_FAILED'
            if input_limit.is_set() and not reason:
                reason = 'SITE_DATABASE_SQL_SIZE_LIMIT'
            error_number = re.search(rb'\bERROR\s+([0-9]{3,5})\b', bytes(buffers[1]))
            _CLIENT_STATUS.value = {'returncode': int(process.returncode if not reason else 125),
                'reason': reason or 'NONE', 'mysql_error': int(error_number[1]) if error_number else 0,
                'elapsed_ms': round((time.monotonic() - began) * 1000)}
            return subprocess.CompletedProcess(command, _CLIENT_STATUS.value['returncode'],
                bytes(buffers[0]), reason.encode('ascii') if reason else bytes(buffers[1]))
        finally:
            if process.poll() is None:
                terminate_process_tree(process.pid, force=True)
                process.wait(timeout=3)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe:
                    pipe.close()
    finally:
        if input_file:
            input_file.close()


def last_client_status():
    """Safe diagnostic metadata; never raw output, SQL, arguments or credentials."""
    return dict(getattr(_CLIENT_STATUS, 'value', {}))


def _local_origin(origin):
    from urllib.parse import urlparse
    parsed = urlparse(str(origin or '').strip())
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1') or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('SITE_DATABASE_ORIGIN_NOT_LOCAL')
    if parsed.port is None or not 1 <= parsed.port <= 65535:
        raise ValueError('SITE_DATABASE_ORIGIN_NOT_LOCAL')
    return 'http://' + parsed.hostname + ':' + str(parsed.port)


def rewrite_preview_origin(origin, *, cancelled=None):
    try:
        url = _local_origin(origin)
        db, prefix = _identifier(_define('DB_NAME') or 'goldgoblins_local'), _table_prefix()
        if not start_mysqld().startswith('PASS'):
            return 'FAIL: SITE_DATABASE_SERVER_UNAVAILABLE'
        sql = "UPDATE `" + prefix + "options` SET option_value='" + url + "' WHERE option_name IN ('siteurl','home');\n"
        done = _mysql([db], stdin=sql.encode('utf-8'), cancelled=cancelled)
        if done.returncode != 0:
            return 'FAIL: SITE_DATABASE_URL_REWRITE_FAILED'
        verify = _mysql([db, '-N', '-e', "SELECT option_name,option_value FROM `" + prefix + "options` WHERE option_name IN ('siteurl','home');"], cancelled=cancelled)
        values = dict(line.split('\t', 1) for line in verify.stdout.decode('utf-8', errors='replace').splitlines() if '\t' in line)
        if verify.returncode != 0 or values.get('siteurl') != url or values.get('home') != url:
            return 'FAIL: SITE_DATABASE_URL_VERIFY_FAILED'
        return 'PASS: local site URLs verified'
    except (OSError, ValueError, RuntimeError, UnicodeError):
        return 'FAIL: SITE_DATABASE_CONFIG_OR_ORIGIN_INVALID'


def _point_wp_config_local():
    from backend.php_config_literals import replace_host
    text = _config_text()
    updated = replace_host(text, '127.0.0.1:' + str(PORT))
    temporary = WP_CONFIG.with_name('.gg-config-' + uuid.uuid4().hex)
    try:
        fd = secure_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(updated.encode('utf-8')); handle.flush(); os.fsync(handle.fileno())
        atomic_replace(temporary, WP_CONFIG)
        sync_directory(WP_CONFIG.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def import_sql_dump(source, progress=None, *, cancelled=None):
    original_cancelled = cancelled
    deadline = time.monotonic() + SQL_TIMEOUT_SECONDS
    def interrupted():
        return time.monotonic() >= deadline or bool(original_cancelled and original_cancelled())
    cancelled = interrupted
    try:
        path = local_file_path(source)
        if os.name == 'nt' and str(path).startswith(('\\\\', '//')):
            return 'FAIL: SITE_DATABASE_REMOTE_SOURCE_NOT_ALLOWED'
        if not path.is_file() or path.suffix.lower() != '.sql':
            return 'FAIL: SQL dump missing'
        from backend.web_surface import _assert_no_links
        _assert_no_links(path)
        if path.stat().st_size > MAX_SQL_BYTES:
            return 'FAIL: SITE_DATABASE_SQL_SIZE_LIMIT'
    except (OSError, ValueError):
        return 'FAIL: SITE_DATABASE_SOURCE_INVALID'
    if not _DB_LOCK.acquire(blocking=False):
        return 'FAIL: SITE_DATABASE_ALREADY_IMPORTING'
    changed = False
    try:
        def note(phase, current, extra):
            if cancelled and cancelled():
                raise ValueError('SITE_DATABASE_CANCELLED')
            if progress:
                progress(phase, current, 4, extra)
        note('DB', 0, 'Validate local configuration')
        configured_db = _define('DB_NAME')
        if not configured_db:
            return 'FAIL: SITE_DATABASE_APPLICATION_SCHEMA_REQUIRED'
        db = _identifier(configured_db)
        _table_prefix()
        user, password = _define('DB_USER'), _define('DB_PASSWORD')
        if not user or user.casefold() == 'root':
            return 'FAIL: SITE_DATABASE_APPLICATION_ACCOUNT_REQUIRED'
        if db.casefold() in {'mysql', 'information_schema', 'performance_schema', 'sys'}:
            return 'FAIL: SITE_DATABASE_APPLICATION_SCHEMA_REQUIRED'
        started = start_mysqld()
        if not started.startswith('PASS'):
            return started
        create = 'CREATE DATABASE IF NOT EXISTS `' + db + '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n'
        if user:
            _identifier(user)
            create += "CREATE USER IF NOT EXISTS '" + user + "'@'127.0.0.1';\n"
            create += "ALTER USER '" + user + "'@'127.0.0.1' IDENTIFIED BY '" + password.replace('\\', '\\\\').replace("'", "\\'") + "';\n"
            create += "GRANT ALL ON `" + db + "`.* TO '" + user + "'@'127.0.0.1';\n"
        changed = True
        made = _mysql([], stdin=create.encode('utf-8'), cancelled=cancelled)
        if made.returncode != 0:
            return 'PARTIAL: SITE_DATABASE_PREPARATION_FAILED; local database may contain changes'
        note('DB', 1, 'Stream bounded SQL dump')
        loaded = _mysql([db], source=path, cancelled=cancelled)
        if loaded.returncode != 0:
            return 'PARTIAL: SITE_DATABASE_IMPORT_INTERRUPTED; local database may contain changes'
        note('DB', 2, 'Rewrite and verify local URLs')
        if not rewrite_preview_origin('http://127.0.0.1:8765', cancelled=cancelled).startswith('PASS'):
            return 'PARTIAL: SITE_DATABASE_URL_POSTCONDITION_FAILED; SQL imported, configuration unchanged'
        note('DB', 3, 'Commit local configuration')
        if not _point_wp_config_local():
            return 'PARTIAL: SITE_DATABASE_CONFIG_POSTCONDITION_FAILED; SQL imported'
        note('PASS', 4, 'Local database and URL postconditions verified')
        return 'PASS: local SQL imported and postconditions verified'
    except (OSError, ValueError, RuntimeError, UnicodeError):
        return ('PARTIAL: SITE_DATABASE_OPERATION_INTERRUPTED; local database may contain changes'
                if changed else 'FAIL: SITE_DATABASE_CONFIG_OR_SOURCE_INVALID')
    finally:
        _DB_LOCK.release()
