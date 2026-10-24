"""Pinned per-user Windows SITE tools, with no service or global PATH changes."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import tempfile
import threading
import time
import urllib.request
import zipfile

from backend.platform_files import is_link, secure_open, NOFOLLOW, atomic_replace, set_private_mode
from backend.platform_process import run_bounded
from backend.platform_support import host_environment

PACKAGES = {
    'php': {'version': '8.5.12', 'url': 'https://downloads.php.net/~windows/releases/archives/php-8.5.12-nts-Win32-vs17-x64.zip',
            'sha256': '2ab242af38d76bdf417cde5ec048b1bcd76a5a40f39a3d15d5f046f38571c477',
            'prefix': '', 'executables': ['php.exe']},
    'mariadb': {'version': '12.3.3', 'url': 'https://archive.mariadb.org/mariadb-12.3.3/winx64-packages/mariadb-12.3.3-winx64.zip',
                'sha256': '4b5706b47148b47c8f36963c8352d1ddee37a1287b4690428f631a74b09b85a0',
                'prefix': 'mariadb-12.3.3-winx64/',
                'executables': ['bin/mariadbd.exe', 'bin/mariadb.exe', 'bin/mariadb-install-db.exe']},
}
PHP_EXTENSIONS = ['mbstring', 'mysqli', 'pdo_mysql', 'curl', 'openssl', 'fileinfo', 'gd', 'intl', 'zip', 'exif', 'sodium']
_LOCK = threading.RLock()
_EXPECTED = {}
_VERIFIED = {}
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024


def tools_root() -> Path:
    from backend.application_paths import HOME
    value = os.environ.get('GG_SITE_TOOLS_ROOT')
    root = Path(value) if value else Path(os.environ.get('LOCALAPPDATA', str(HOME / 'AppData/Local'))) / 'GoldGoblins/site-tools'
    if not root.is_absolute() or str(root).startswith(('\\\\', '//')):
        raise ValueError('SITE_TOOLS_LOCAL_ROOT_REQUIRED')
    _no_links(root)
    return root


def _no_links(path: Path):
    if any(is_link(item) for item in (path, *path.parents)):
        raise ValueError('SITE_TOOL_LINK_NOT_ALLOWED')


def _signature(path: Path):
    _no_links(path)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError('SITE_TOOL_REGULAR_FILE_REQUIRED')
    changed = metadata.st_ctime_ns
    if os.name == 'nt':
        import msvcrt
        class Basic(ctypes.Structure):
            _fields_ = [('creation', ctypes.c_longlong), ('access', ctypes.c_longlong),
                        ('write', ctypes.c_longlong), ('change', ctypes.c_longlong), ('attributes', ctypes.c_uint32)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        api.GetFileInformationByHandleEx.restype = ctypes.c_int
        fd = secure_open(path, os.O_RDONLY | NOFOLLOW)
        try:
            info = Basic()
            if not api.GetFileInformationByHandleEx(msvcrt.get_osfhandle(fd), 0, ctypes.byref(info), ctypes.sizeof(info)):
                raise ValueError('SITE_TOOL_METADATA_UNAVAILABLE')
            changed = info.change
        finally:
            os.close(fd)
    return (metadata.st_size, metadata.st_mtime_ns, changed, metadata.st_ino)


def _digest(path: Path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _archive(root, component):
    package = PACKAGES[component]
    return root / 'archives' / (component + '-' + package['version'] + '.zip')


def _relative(row, package):
    value = row.filename
    path = PurePosixPath(value)
    if (not value or '\\' in value or ':' in value or '\0' in value or path.is_absolute() or '..' in path.parts
            or (row.external_attr >> 16) & 0o170000 == 0o120000
            or any(part.endswith(('.', ' ')) for part in path.parts)):
        raise ValueError('SITE_TOOL_UNSAFE_ARCHIVE')
    prefix = package['prefix']
    if prefix:
        if value.rstrip('/') == prefix.rstrip('/'):
            return None
        if not value.startswith(prefix):
            raise ValueError('SITE_TOOL_ARCHIVE_LAYOUT')
        value = value[len(prefix):]
    return Path(*PurePosixPath(value).parts)


def _expected_files(root, component):
    package = PACKAGES[component]
    archive = _archive(root, component)
    signature = _signature(archive)
    if signature[0] > MAX_DOWNLOAD:
        raise ValueError('SITE_TOOL_ARCHIVE_LIMIT')
    key = (str(archive), signature, package['sha256'])
    with _LOCK:
        cached = _EXPECTED.get(key)
        if cached is not None:
            return cached
    if _digest(archive) != package['sha256']:
        raise ValueError('SITE_TOOL_ARCHIVE_CHECKSUM_FAILED')
    expected = {}
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 20000:
            raise ValueError('SITE_TOOL_ARCHIVE_LIMIT')
        for row in bundle.infolist():
            relative = _relative(row, package)
            if row.is_dir() or relative is None:
                continue
            total += row.file_size
            if row.file_size > MAX_DOWNLOAD or total > MAX_EXPANDED or relative.as_posix().casefold() in expected:
                raise ValueError('SITE_TOOL_ARCHIVE_LIMIT')
            with bundle.open(row) as stream:
                expected[relative.as_posix().casefold()] = (relative.as_posix(), hashlib.file_digest(stream, 'sha256').hexdigest())
    with _LOCK:
        if len(_EXPECTED) >= 8:
            _EXPECTED.clear()
        _EXPECTED[key] = expected
    return expected


def managed_ini(root: Path) -> str:
    folder = (root / 'php').as_posix()
    return ('; GG local SITE configuration; contains no credentials.\n'
            'date.timezone=Europe/Stockholm\nexpose_php=Off\ndisplay_errors=Off\nlog_errors=Off\n'
            'memory_limit=256M\nmax_memory_limit=512M\nmemory_hard_limit_percent=125\n'
            'max_execution_time=30\npost_max_size=64M\nupload_max_filesize=32M\n'
            'max_input_vars=2000\nmax_input_nesting_level=64\n'
            'mysqli.allow_local_infile=Off\n'
            'extension_dir="' + folder + '/ext"\n' + ''.join('extension=' + name + '\n' for name in PHP_EXTENSIONS))


def _verify(component, root, *, require_receipt=True):
    folder = root / component
    if not folder.exists():
        return False
    _no_links(folder)
    record_path = root / 'installation.json'
    if require_receipt:
        if not record_path.is_file() or _signature(record_path)[0] > 65536:
            raise ValueError('SITE_TOOL_RECEIPT_REQUIRED')
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if record.get('packages', {}).get(component) != PACKAGES[component]:
            raise ValueError('SITE_TOOL_RECEIPT_MISMATCH')
    expected = _expected_files(root, component)
    signatures = tuple((relative, _signature(folder / relative)) for relative, _ in expected.values())
    key = (str(folder), signatures)
    with _LOCK:
        known = _VERIFIED.get(component) == key
    if not known:
        for relative, digest in expected.values():
            if _digest(folder / relative) != digest:
                raise ValueError('SITE_TOOL_INSTALLED_FILE_CHANGED')
        with _LOCK:
            _VERIFIED[component] = key
    if component == 'php':
        ini = folder / 'gg-php.ini'
        scan = folder / 'empty-ini-scan'
        _no_links(ini)
        _no_links(scan)
        if ini.read_text(encoding='utf-8') != managed_ini(root) or not scan.is_dir() or any(scan.iterdir()):
            raise ValueError('SITE_TOOL_CONFIGURATION_CHANGED')
    return True


def runtime_executable(component: str, names=()) -> str:
    if os.name != 'nt' or component not in PACKAGES:
        return ''
    root = tools_root()
    if not _verify(component, root):
        return ''
    candidates = [str(name) for name in names] if names else PACKAGES[component]['executables']
    for name in candidates:
        path = PurePosixPath(name.replace('\\', '/'))
        if path.is_absolute() or '..' in path.parts or ':' in name:
            raise ValueError('SITE_TOOL_NAME_INVALID')
        relative = '/'.join(path.parts)
        if not relative.endswith('.exe'):
            relative += '.exe'
        if component == 'mariadb' and not relative.startswith('bin/'):
            relative = 'bin/' + relative
        candidate = root / component / relative
        if candidate.is_file() and candidate.relative_to(root / component).as_posix().casefold() in _expected_files(root, component):
            return str(candidate)
    return ''


def php_arguments(executable=None) -> list[str]:
    selected = str(executable or runtime_executable('php'))
    if not selected:
        raise ValueError('SITE_PHP_NOT_INSTALLED')
    root = tools_root()
    if Path(selected).resolve() == (root / 'php/php.exe').resolve():
        runtime_executable('php')
        return [selected, '-c', str(root / 'php/gg-php.ini')]
    return [selected]


def php_environment(executable=None) -> dict[str, str]:
    selected = str(executable or runtime_executable('php'))
    if not selected:
        raise ValueError('SITE_PHP_NOT_INSTALLED')
    scan = tools_root() / 'php/empty-ini-scan'
    return host_environment({'PATH': str(Path(selected).parent), 'PHP_INI_SCAN_DIR': str(scan)})


def _download(url, target, checksum):
    request = urllib.request.Request(url, headers={'User-Agent': 'GG-SITE-Windows-Setup'})
    began = time.monotonic()
    count = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=30) as response, target.open('xb') as output:
        if not response.geturl().startswith('https://'):
            raise ValueError('SITE_TOOL_HTTPS_REQUIRED')
        while data := response.read(1024 * 1024):
            count += len(data)
            if count > MAX_DOWNLOAD or time.monotonic() - began > 600:
                raise ValueError('SITE_TOOL_DOWNLOAD_LIMIT')
            digest.update(data)
            output.write(data)
    if digest.hexdigest() != checksum:
        raise ValueError('SITE_TOOL_ARCHIVE_CHECKSUM_FAILED')


def install() -> dict:
    if os.name != 'nt' or platform.machine().casefold() not in {'amd64', 'x86_64'}:
        raise ValueError('SITE_TOOLS_WINDOWS_X64_REQUIRED')
    root = tools_root()
    root.mkdir(parents=True, exist_ok=True)
    set_private_mode(root, 0o700)
    if shutil.disk_usage(root).free < 2 * 1024 * 1024 * 1024:
        raise ValueError('SITE_TOOLS_FREE_SPACE_REQUIRED')
    archives = root / 'archives'
    archives.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.site-setup-', dir=root.parent) as directory:
        staging = Path(directory)
        for component, package in PACKAGES.items():
            archive = _archive(root, component)
            if not archive.exists():
                download = staging / (component + '.zip')
                _download(package['url'], download, package['sha256'])
                atomic_replace(download, archive)
            expected = _expected_files(root, component)
            folder = root / component
            if folder.exists():
                # Explicit installation can recover a crash between publishing
                # complete components and publishing the final receipt. Reuse
                # only byte-for-byte pinned vendor files and our exact config;
                # runtime discovery continues to require the complete receipt.
                _verify(component, root, require_receipt=False)
                continue
            expanded = staging / component
            expanded.mkdir()
            total = 0
            with zipfile.ZipFile(archive) as bundle:
                for row in bundle.infolist():
                    relative = _relative(row, package)
                    if relative is None:
                        continue
                    destination = expanded / relative
                    if row.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(row) as source, destination.open('xb') as output:
                        while data := source.read(1024 * 1024):
                            total += len(data)
                            if total > MAX_EXPANDED:
                                raise ValueError('SITE_TOOL_ARCHIVE_LIMIT')
                            output.write(data)
                    if _digest(destination) != expected[relative.as_posix().casefold()][1]:
                        raise ValueError('SITE_TOOL_EXTRACTION_FAILED')
            if component == 'php':
                (expanded / 'gg-php.ini').write_text(managed_ini(root), encoding='utf-8', newline='\n')
                (expanded / 'empty-ini-scan').mkdir()
            for relative in package['executables']:
                if not (expanded / relative).is_file():
                    raise ValueError('SITE_TOOL_EXECUTABLE_MISSING')
            expanded.rename(folder)
        record = {'schema': 'gg.site-tools-install.v1', 'packages': PACKAGES,
                  'installed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'scope': 'Per-user tools only; no service registration, PATH modification or database initialization'}
        pending = root / ('installation-' + str(os.getpid()) + '.json')
        pending.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        atomic_replace(pending, root / 'installation.json')
    php = runtime_executable('php')
    command = php_arguments(php) + ['-r', 'echo json_encode([PHP_VERSION,get_loaded_extensions(),ini_get("memory_hard_limit_percent"),php_ini_scanned_files()]);']
    code, out, _, reason = run_bounded(command, env=php_environment(php), timeout=15, max_output_bytes=8192)
    if code or reason != 'NONE':
        raise ValueError('SITE_PHP_RUNTIME_PROBE_FAILED')
    version, modules, hard_limit, scanned = json.loads(out)
    if version != PACKAGES['php']['version'] or not set(PHP_EXTENSIONS).issubset(modules) or hard_limit != '125' or scanned:
        raise ValueError('SITE_PHP_CONFIGURATION_PROBE_FAILED')
    server = runtime_executable('mariadb', ['mariadbd'])
    code, out, _, reason = run_bounded([server, '--no-defaults', '--version'], timeout=15, max_output_bytes=2048)
    if code or reason != 'NONE' or PACKAGES['mariadb']['version'].encode() not in out:
        raise ValueError('SITE_MARIADB_RUNTIME_PROBE_FAILED')
    return {'status': 'PASS', 'php': version, 'mariadb': PACKAGES['mariadb']['version'],
            'extensions_checked': len(PHP_EXTENSIONS), 'scope': record['scope']}
