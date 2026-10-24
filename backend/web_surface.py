from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory, atomic_replace, is_link
from backend.platform_support import local_file_path, find_executable

import json
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import re
import stat
import struct
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

SITE_ROOT = Path(str(STATE_ROOT / 'site'))
IMPORT_DROP = Path(str(STATE_ROOT / 'site-import'))
PROFILE_ROOT = Path(
    str(STATE_ROOT / 'web-profile')
)
SKIP_IMPORT_NAMES = {
    "wp-config.php",
    "wp-config-sample.php",
    "wp-config.one.com.bak",
    ".env",
    ".htpasswd",
}
ALLOWED_ORIGINS = (
    "https://goldgoblins.se",
    "https://www.goldgoblins.se",
)
SEED_INDEX = """<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <title>GoldGoblins site</title>
  <style>
    body { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #121212; color: #e6e6e6; margin: 2rem; }
    code { color: #c8a97e; }
  </style>
</head>
<body>
  <h1>Blank slate</h1>
  <p>Local SITE root. Prompts edit snippets here. Live one.com deploy is a later user-approved step.</p>
  <!-- gg-snippet:header -->
</body>
</html>
"""
SEED_SNIPPET = """<!-- gg-snippet:header -->
<header>GoldGoblins</header>
"""


def ensure_webengine() -> bool:
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick

        QtWebEngineQuick.initialize()
        ensure_web_profile_root()
        return True
    except Exception:
        return False


def ensure_web_profile_root() -> Path:
    PROFILE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache = PROFILE_ROOT / "cache"
    cache.mkdir(mode=0o700, exist_ok=True)
    return PROFILE_ROOT


def _is_seed_index(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:800]
    except OSError:
        return False
    return "Local SITE root. Prompts edit snippets here." in head


def _site_file_count(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file())


def _has_imported_tree(root: Path) -> bool:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == "index.html" and _is_seed_index(path):
            continue
        if rel == "snippets/header.html":
            continue
        return True
    return False


def ensure_site_root() -> Path:
    if _IMPORT_LOCK.locked():
        return SITE_ROOT
    _recover_site_import()
    SITE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _has_imported_tree(SITE_ROOT):
        index = SITE_ROOT / "index.html"
        if index.is_file() and _is_seed_index(index):
            index.unlink()
        return SITE_ROOT
    snippets = SITE_ROOT / "snippets"
    snippets.mkdir(mode=0o700, exist_ok=True)
    index = SITE_ROOT / "index.html"
    if not index.is_file():
        index.write_text(SEED_INDEX, encoding="utf-8")
        os.chmod(index, 0o600)
    header = snippets / "header.html"
    if not header.is_file():
        header.write_text(SEED_SNIPPET, encoding="utf-8")
        os.chmod(header, 0o600)
    return SITE_ROOT


def _safe_rel(relative: str) -> Path | None:
    name = str(relative or "").strip().replace("\\", "/")
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return None
    root = SITE_ROOT.resolve()
    candidate = (SITE_ROOT / name).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


SOURCE_LIST_SUFFIXES = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".php",
    ".json",
    ".md",
    ".txt",
}


def list_site_files() -> str:
    root = ensure_site_root()
    sources: list[dict[str, str]] = []
    other: list[dict[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        row = {"path": rel, "bytes": str(path.stat().st_size)}
        if path.suffix.lower() in SOURCE_LIST_SUFFIXES:
            sources.append(row)
        else:
            other.append(row)
    sources.sort(key=lambda row: row["path"])
    other.sort(key=lambda row: row["path"])
    listed = sources[:1500]
    if len(listed) < 400:
        listed.extend(other[: 400 - len(listed)])
    return json.dumps(listed)


def preferred_site_file() -> str:
    root = ensure_site_root()
    php = root / "index.php"
    if php.is_file():
        return "index.php"
    index = root / "index.html"
    if index.is_file() and not _is_seed_index(index):
        return "index.html"
    htmls = sorted(
        path
        for path in root.rglob("*.html")
        if path.is_file() and not _is_seed_index(path)
    )
    if htmls:
        return htmls[0].relative_to(root).as_posix()
    return ""


def site_file_url(relative: str) -> str:
    path = _safe_rel(relative)
    if path is None or not path.is_file():
        return ""
    return path.as_uri()


def read_site_file(relative: str) -> str:
    path = _safe_rel(relative)
    if path is None or not path.is_file():
        return ""
    if path.stat().st_size > 262144:
        return ""
    return path.read_text(encoding="utf-8")


def write_site_file(relative: str, text: str) -> str:
    if not _IMPORT_LOCK.acquire(blocking=False):
        return ''
    try:
        return _write_site_file_unlocked(relative, text)
    finally:
        _IMPORT_LOCK.release()


def _write_site_file_unlocked(relative: str, text: str) -> str:
    path = _safe_rel(relative)
    if path is None:
        return ""
    if path.suffix.lower() not in {
        ".html",
        ".htm",
        ".css",
        ".js",
        ".txt",
        ".md",
        ".php",
        ".json",
    }:
        return ""
    body = text if isinstance(text, str) else str(text)
    data = body.encode("utf-8")
    if len(data) > 262144:
        return ""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name('.gg-save-' + uuid.uuid4().hex)
    fd = secure_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return path.as_posix()


def url_allowed(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme == "about" and parsed.path in {"blank", ""}:
        return True
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            return False
        try:
            local = Path(url2pathname(parsed.path)).resolve()
        except OSError:
            return False
        return local.is_relative_to(SITE_ROOT.resolve())
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        return True
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    origin = parsed.scheme + "://" + parsed.hostname.lower()
    if parsed.port:
        origin += ":" + str(parsed.port)
    return origin in ALLOWED_ORIGINS


def default_web_url() -> str:
    ensure_site_root()
    return (SITE_ROOT / "index.html").as_uri()


def browse_url_allowed(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme == "about" and parsed.path in {"blank", ""}:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    host = str(parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1"}:
        return True
    return "." in host


def normalize_browse_url(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    if not browse_url_allowed(text):
        return ""
    return text


def default_browse_url() -> str:
    return "about:blank"


def preview_bind_host() -> str:
    return "127.0.0.1"


def pick_preview_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((preview_bind_host(), 0))
        return int(sock.getsockname()[1])


PHP_IMAGE = "localhost/gg-site-php:1"
PHP_ROUTER = Path(__file__).resolve().parent / "site_php_router.php"
PODMAN = "/usr/bin/podman"
PHP_FIXES_DATE = '2026-10-21'
PHP_FIXED_RELEASES = {'8.2': 35, '8.3': 36, '8.4': 27, '8.5': 12}
_PHP_HEALTH_LOCK = threading.RLock()
_PHP_HEALTH = {}


def _php_executable() -> str:
    configured = os.environ.get('GG_PHP_BINARY', '')
    if configured and Path(configured).is_absolute() and not configured.startswith(('\\\\', '//')):
        if Path(configured).is_file() and not is_link(configured):
            return configured
    if os.name == 'nt':
        from backend.site_runtime_setup import runtime_executable, tools_root
        try:
            managed = runtime_executable('php')
            if managed:
                return managed
        except (OSError, ValueError):
            # A damaged managed installation must not silently select another
            # executable from PATH instead of reporting its failed check.
            return ''
    found = shutil.which('php')
    if found:
        return found
    if os.name == 'nt':
        # Inspect known per-user/system installations without scanning drives.
        roots = [Path(value) for value in (os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')) if value]
        for root in roots:
            for relative in ('PHP/php.exe', 'Programs/PHP/php.exe'):
                candidate = root / relative
                if candidate.is_file() and not is_link(candidate):
                    return str(candidate)
        drive = Path(os.environ.get('SystemDrive', 'C:') + '/')
        for relative in ('php/php.exe', 'xampp/php/php.exe'):
            candidate = drive / relative
            if candidate.is_file() and not is_link(candidate):
                return str(candidate)
    return ''


def _podman_executable() -> str:
    return find_executable('podman') or (PODMAN if Path(PODMAN).is_file() else '')


def php_version_assessment(version: str) -> dict:
    """Offline upstream comparison; package suffixes need vendor evidence."""
    value = str(version or '')[:200].strip()
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(.*)', value)
    result = {'rules_date': PHP_FIXES_DATE, 'version': value[:100], 'status': 'UNKNOWN',
              'detail': 'PHP build and applicable vendor patch evidence are not verified.'}
    if not match:
        return result
    branch = match[1] + '.' + match[2]
    suffix = match[4]
    fixed = PHP_FIXED_RELEASES.get(branch)
    if suffix or fixed is None:
        result['detail'] = 'Vendor suffix, prerelease or unrecognized branch requires provider-specific patch evidence.'
        return result
    result['first_fixed'] = branch + '.' + str(fixed)
    result['status'] = 'UPSTREAM_FIXED_VERSION' if int(match[3]) >= fixed else 'POTENTIALLY_VULNERABLE'
    result['detail'] = ('Reported upstream version meets the fixed release; installed build provenance is not verified.'
                        if result['status'] == 'UPSTREAM_FIXED_VERSION' else
                        'Reported version predates the upstream fix; vendor backports may change this assessment.')
    return result


def php_runtime_health(*, refresh: bool = False, cancelled=None) -> dict:
    """Probe only local runtime metadata without user php.ini or network access.

    Called by the SITE job worker. A bounded cache keeps UI status reads cheap.
    Container contents are deliberately UNKNOWN until inspected separately.
    """
    with _PHP_HEALTH_LOCK:
        if _PHP_HEALTH and not refresh:
            return dict(_PHP_HEALTH)
    php = _php_executable()
    result = {'schema': 'gg.site-php-health.v1', 'runtime': 'STATIC', 'status': 'NOT_INSTALLED',
              'rules_date': PHP_FIXES_DATE, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'detail': 'PHP is unavailable; static preview cannot execute WordPress.', 'fingerprint': ''}
    if php:
        result.update(runtime='PHP', executable=php, status='UNKNOWN')
        try:
            metadata = Path(php).stat()
            # Version only: no target script, php.ini, extensions or server.
            from backend.platform_process import run_bounded
            from backend.site_runtime_setup import tools_root, php_arguments, php_environment, PHP_EXTENSIONS
            managed = os.name == 'nt' and Path(php).resolve() == (tools_root() / 'php/php.exe').resolve()
            command = php_arguments(php) + ['-r', 'echo json_encode([PHP_VERSION,get_loaded_extensions(),php_ini_loaded_file(),php_ini_scanned_files(),ini_get("memory_hard_limit_percent")]);'] if managed else [php, '-n', '-r', 'echo PHP_VERSION;']
            code, out, _, trigger = run_bounded(command,
                timeout=5, max_output_bytes=8192, env=php_environment(php) if managed else {'PATH': str(Path(php).parent)}, cancelled=cancelled)
            details = json.loads(out) if managed and code == 0 and trigger in ('', 'NONE') else None
            version = str(details[0]) if details else out.decode('ascii', errors='replace').strip()
            result.update(php_version_assessment(version) if code == 0 and trigger in ('', 'NONE') else
                          {'status': 'UNKNOWN', 'detail': 'Local PHP version probe failed.'})
            if details:
                configured_ini = tools_root() / 'php/gg-php.ini'
                configured = (set(PHP_EXTENSIONS).issubset(details[1]) and Path(details[2]).resolve() == configured_ini.resolve()
                              and not details[3] and details[4] == '125')
                result.update(build_verified=True, provenance='OFFICIAL_ARCHIVE_VERIFIED',
                              configuration_verified=configured, loaded_extensions=details[1])
                if configured:
                    result.update(status='READY', detail='Official PHP build, managed configuration and SITE database/image extensions verified locally.')
                else:
                    result.update(status='CONFIGURATION_INCOMPLETE', detail='Managed PHP did not load its required configuration and extensions.')
            result['fingerprint'] = php_runtime_identity()
        except (OSError, ValueError):
            result.update(status='UNKNOWN', detail='Local PHP executable could not be inspected.')
    elif os.name == 'nt':
        from backend.site_runtime_setup import runtime_executable, tools_root
        try:
            if (tools_root() / 'php').exists():
                runtime_executable('php')
        except (OSError, ValueError):
            result.update(status='INTEGRITY_FAILED', detail='Managed PHP installation failed verification; rerun its reviewed installer.')
    if not php and result['status'] == 'NOT_INSTALLED' and _php_image_present():
        result.update(runtime='PHP_CONTAINER', status='UNKNOWN', image=PHP_IMAGE,
                      detail='Cached local PHP container exists; serving build and vendor patch status are unverified.')
    with _PHP_HEALTH_LOCK:
        _PHP_HEALTH.clear()
        _PHP_HEALTH.update(result)
    return dict(result)


def php_runtime_identity() -> str:
    """Cheap identity marker for restart advice, not build verification."""
    php = _php_executable()
    if not php:
        return ''
    try:
        info = Path(php).stat()
        identity = str(Path(php).resolve()) + ':' + str(info.st_mtime_ns) + ':' + str(info.st_size)
        if os.name == 'nt':
            from backend.site_runtime_setup import tools_root
            ini = tools_root() / 'php/gg-php.ini'
            if Path(php).resolve() == ini.parent.joinpath('php.exe').resolve():
                identity += ':' + hashlib.sha256(ini.read_bytes()).hexdigest()
        return identity
    except OSError:
        return ''


def _php_bind(port: int) -> str:
    return preview_bind_host() + ":" + str(int(port))


def _host_php_argv(php: str, port: int) -> list[str]:
    from backend.site_runtime_setup import php_arguments
    argv = php_arguments(php) + ["-S", _php_bind(port), "-t", str(SITE_ROOT)]
    if PHP_ROUTER.is_file():
        argv.append(str(PHP_ROUTER))
    return argv


def _php_image_present() -> bool:
    inspect = _podman_executable()
    if not inspect:
        return False
    try:
        proc = subprocess.run([inspect, 'image', 'exists', PHP_IMAGE], capture_output=True,
                              check=False, timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _install_site_router() -> None:
    if not PHP_ROUTER.is_file():
        return
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    dest = SITE_ROOT / ".gg-router.php"
    dest.write_bytes(PHP_ROUTER.read_bytes())
    dest.chmod(0o644)


def _podman_php_argv(port: int) -> list[str]:
    bind = _php_bind(port)
    _install_site_router()
    return [
        _podman_executable(),
        "run",
        "--rm",
        "--network=host",
        "-v",
        str(SITE_ROOT) + ":/var/www/html:z",
        PHP_IMAGE,
        "php",
        "-S",
        bind,
        "-t",
        "/var/www/html",
        "/var/www/html/.gg-router.php",
    ]


def preview_argv(port: int) -> list[str]:
    script = Path(__file__).resolve().parent / "site_preview_server.py"
    php = _php_executable()
    if php:
        return _host_php_argv(php, port)
    if _php_image_present():
        return _podman_php_argv(port)
    return [
        sys.executable,
        str(script),
        preview_bind_host(),
        str(int(port)),
        str(SITE_ROOT),
    ]


def preview_origin(port: int) -> str:
    return "http://" + preview_bind_host() + ":" + str(int(port)) + "/"


def preview_kind() -> str:
    if _php_executable() or _php_image_present():
        return "PHP"
    return "STATIC"


IMPORT_PROGRESS_BATCH = 25


def _local_import_path(raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        path = local_file_path(text)
        if os.name == 'nt' and str(path).startswith(('\\\\', '//')):
            return None
        if is_link(path):
            return None
        return path.absolute()
    except (OSError, ValueError):
        return None


def _safe_import_rel(name: str) -> str | None:
    rel = str(name or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/") or ':' in rel or '\x00' in rel:
        return None
    parts = Path(rel).parts
    if '..' in parts or any(part.endswith((' ', '.')) or
            re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part) for part in parts):
        return None
    posix = Path(*parts).as_posix()
    base = Path(posix).name.lower()
    private_directories = {'.git', '.ssh', '.aws', '.azure', '.kube', '.gnupg'}
    if any(part.casefold() in private_directories for part in parts):
        return None
    if base.startswith('.env.') or base in {'.npmrc', '.pypirc', '.netrc', '.git-credentials'}:
        return None
    if base in {item.lower() for item in SKIP_IMPORT_NAMES}:
        return None
    if base.startswith("wp-config") and base.endswith(".php"):
        return None
    return posix


def ensure_import_drop() -> Path:
    IMPORT_DROP.mkdir(mode=0o700, parents=True, exist_ok=True)
    return IMPORT_DROP


def pending_import_zips() -> list[Path]:
    root = ensure_import_drop()
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".zip"
    )


MAX_IMPORT_FILES = 50_000
MAX_IMPORT_ENTRIES = 100_000
MAX_IMPORT_FILE_BYTES = 256 * 1024 * 1024
MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMPORT_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_IMPORT_DIRECTORY_BYTES = 16 * 1024 * 1024
IMPORT_TIMEOUT_SECONDS = 180
_IMPORT_LOCK = threading.Lock()


class _ImportBudget:
    def __init__(self, cancelled=None):
        self.cancelled = cancelled
        self.deadline = time.monotonic() + IMPORT_TIMEOUT_SECONDS
        self.bytes = 0
        self.files = 0
        self.entries = 0

    def check(self):
        if self.cancelled and self.cancelled():
            raise ValueError('SITE_IMPORT_CANCELLED')
        if time.monotonic() >= self.deadline:
            raise ValueError('SITE_IMPORT_TIMEOUT')

    def entry(self):
        self.check()
        self.entries += 1
        if self.entries > MAX_IMPORT_ENTRIES:
            raise ValueError('SITE_IMPORT_ENTRY_LIMIT')

    def file(self):
        self.check()
        self.files += 1
        if self.files > MAX_IMPORT_FILES:
            raise ValueError('SITE_IMPORT_FILE_LIMIT')

    def consume(self, amount, file_bytes):
        self.check()
        self.bytes += amount
        if file_bytes > MAX_IMPORT_FILE_BYTES or self.bytes > MAX_IMPORT_BYTES:
            raise ValueError('SITE_IMPORT_SIZE_LIMIT')


def _assert_no_links(path: Path) -> None:
    for item in (path, *path.parents):
        if is_link(item):
            raise ValueError('SITE_IMPORT_LINK_NOT_ALLOWED')


def _walk_import_source(root: Path, budget: _ImportBudget):
    pending = [root]
    while pending:
        budget.check()
        directory = pending.pop()
        _assert_no_links(directory)
        with os.scandir(directory) as entries:
            for item in entries:
                budget.entry()
                path = Path(item.path)
                metadata = item.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('SITE_IMPORT_LINK_NOT_ALLOWED')
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    yield path
                else:
                    raise ValueError('SITE_IMPORT_SPECIAL_FILE_NOT_ALLOWED')


def _copy_imported_stream(relative: str, reader, *, root: Path, budget: _ImportBudget) -> None:
    rel = _safe_import_rel(relative)
    if rel is None:
        raise ValueError('SITE_IMPORT_PATH_NOT_ALLOWED')
    dest = root / rel
    if len(dest.parts) - len(root.parts) > 64:
        raise ValueError('SITE_IMPORT_DEPTH_LIMIT')
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_no_links(dest.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW
    fd = secure_open(dest, flags, 0o600)
    copied = 0
    with os.fdopen(fd, 'wb') as handle:
        while True:
            budget.check()
            block = reader.read(256 * 1024)
            if not block:
                break
            copied += len(block)
            budget.consume(len(block), copied)
            handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())


def _remove_import_stage(stage: Path):
    parent = SITE_ROOT.parent.resolve()
    if stage.parent.resolve() != parent or not stage.name.startswith('.site-stage-') or is_link(stage):
        raise ValueError('SITE_IMPORT_CLEANUP_SCOPE')
    if stage.exists():
        shutil.rmtree(stage)


def _check_zip_directory(handle):
    """Bound central-directory allocation before ZipFile builds its file list."""
    handle.seek(0, os.SEEK_END)
    length = handle.tell()
    handle.seek(max(0, length - 65557))
    tail = handle.read(65557)
    marker = tail.rfind(b'PK\x05\x06')
    if marker < 0 or len(tail) - marker < 22:
        raise ValueError('SITE_IMPORT_ZIP_INVALID')
    _, disk, start_disk, disk_count, count, size, offset, comment = struct.unpack_from('<4s4H2LH', tail, marker)
    absolute_marker = length - len(tail) + marker
    if absolute_marker >= 20:
        handle.seek(absolute_marker - 20)
        if handle.read(4) == b'PK\x06\x07':
            raise ValueError('SITE_IMPORT_ZIP64_OR_MULTIDISK_UNSUPPORTED')
    if disk or start_disk or disk_count != count or count == 65535 or size == 0xffffffff or offset == 0xffffffff:
        raise ValueError('SITE_IMPORT_ZIP64_OR_MULTIDISK_UNSUPPORTED')
    if count > MAX_IMPORT_ENTRIES or size > MAX_IMPORT_DIRECTORY_BYTES:
        raise ValueError('SITE_IMPORT_ENTRY_LIMIT')
    if marker + 22 + comment != len(tail) or offset + size > length - len(tail) + marker:
        raise ValueError('SITE_IMPORT_ZIP_INVALID')
    handle.seek(0)


def _validated_site_zip(handle):
    _check_zip_directory(handle)
    return zipfile.ZipFile(handle)


def _import_journal() -> Path:
    return SITE_ROOT.with_name('.site-import-recovery.json')


def _write_import_journal(stage, backup):
    destination = _import_journal()
    temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex)
    try:
        fd = secure_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(json.dumps({'stage': stage.name, 'backup': backup.name}).encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(temporary, destination)
        sync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _recover_site_import():
    """Recover a crashed directory switch before generating any seed files."""
    journal = _import_journal()
    if not journal.exists() or not _IMPORT_LOCK.acquire(blocking=False):
        return
    try:
        _assert_no_links(journal)
        if journal.stat().st_size > 4096:
            raise ValueError('SITE_IMPORT_RECOVERY_INVALID')
        fd = secure_open(journal, os.O_RDONLY | NOFOLLOW)
        with os.fdopen(fd, 'r', encoding='utf-8') as handle:
            record = json.load(handle)
        stage_name, backup_name = record.get('stage', ''), record.get('backup', '')
        if not re.fullmatch(r'\.site-stage-[a-z0-9_]+', stage_name) or not re.fullmatch(r'site\.bak\.[0-9T]+\.[a-f0-9]{12}', backup_name):
            raise ValueError('SITE_IMPORT_RECOVERY_INVALID')
        stage, backup = SITE_ROOT.parent / stage_name, SITE_ROOT.parent / backup_name
        for candidate in (stage, backup, SITE_ROOT):
            _assert_no_links(candidate)
        if not SITE_ROOT.exists() and backup.exists():
            atomic_replace(backup, SITE_ROOT)
        elif not SITE_ROOT.exists() and not stage.exists():
            raise ValueError('SITE_IMPORT_RECOVERY_REQUIRED')
        if stage.exists():
            _remove_import_stage(stage)
        journal.unlink()
        sync_directory(journal.parent)
    finally:
        _IMPORT_LOCK.release()


def _commit_import(stage: Path, budget: _ImportBudget) -> Path | None:
    budget.check()
    _assert_no_links(SITE_ROOT)
    backup = SITE_ROOT.with_name('site.bak.' + time.strftime('%Y%m%dT%H%M%S') + '.' + uuid.uuid4().hex[:12])
    moved_old = False
    moved_new = False
    _write_import_journal(stage, backup)
    try:
        if SITE_ROOT.exists():
            atomic_replace(SITE_ROOT, backup)
            moved_old = True
        # Cancellation after moving the old tree is still a rollback.
        budget.check()
        atomic_replace(stage, SITE_ROOT)
        moved_new = True
        sync_directory(SITE_ROOT.parent)
        _import_journal().unlink(missing_ok=True)
    except BaseException:
        try:
            if moved_new:
                atomic_replace(SITE_ROOT, stage)
            if moved_old:
                atomic_replace(backup, SITE_ROOT)
            _import_journal().unlink(missing_ok=True)
        except OSError:
            raise ValueError('SITE_IMPORT_RECOVERY_REQUIRED') from None
        raise
    return backup if moved_old else None


def import_site_tree(source: str, progress=None, *, cancelled=None) -> str:
    def note(phase: str, current: int, total: int, extra: str = "") -> None:
        if progress is not None:
            progress(phase, current, total, extra)

    path = _local_import_path(source)
    if path is None or not path.exists():
        return "FAIL: import source missing"
    _recover_site_import()
    if not _IMPORT_LOCK.acquire(blocking=False):
        return 'FAIL: SITE_IMPORT_ALREADY_RUNNING'
    stage = None
    try:
        budget = _ImportBudget(cancelled)
        _assert_no_links(path)
        _assert_no_links(SITE_ROOT)
        if path.is_dir() and SITE_ROOT.parent.resolve().is_relative_to(path.resolve()):
            raise ValueError('SITE_IMPORT_SOURCE_OVERLAP')
        SITE_ROOT.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        note('BACKUP', 0, 1, 'Current site remains active until validated import is committed')
        stage = Path(tempfile.mkdtemp(prefix='.site-stage-', dir=SITE_ROOT.parent))
        kept: list[str] = []
        seen = set()
        skipped = 0

        def mark(index: int, total: int, rel: str, phase: str) -> None:
            if (
                index == 1
                or index == total
                or index % IMPORT_PROGRESS_BATCH == 0
            ):
                note(phase, index, total, rel)

        if path.is_file() and path.suffix.lower() == ".zip":
            if path.stat().st_size > MAX_IMPORT_ARCHIVE_BYTES:
                raise ValueError('SITE_IMPORT_ARCHIVE_LIMIT')
            fd = secure_open(path, os.O_RDONLY | NOFOLLOW | CLOEXEC | NONBLOCK)
            with os.fdopen(fd, 'rb') as handle, _validated_site_zip(handle) as archive:
                total = len(archive.filelist)
                if total > MAX_IMPORT_ENTRIES:
                    raise ValueError('SITE_IMPORT_ENTRY_LIMIT')
                note("UNPACK", 0, total, path.name)
                for index, info in enumerate(archive.filelist, start=1):
                    budget.entry()
                    mode = info.external_attr >> 16
                    if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise ValueError('SITE_IMPORT_LINK_NOT_ALLOWED')
                    if info.is_dir():
                        continue
                    rel = _safe_import_rel(info.filename)
                    if rel is None:
                        skipped += 1
                        mark(index, total, info.filename, "SKIP")
                        continue
                    budget.file()
                    if info.file_size > MAX_IMPORT_FILE_BYTES or budget.bytes + info.file_size > MAX_IMPORT_BYTES:
                        raise ValueError('SITE_IMPORT_SIZE_LIMIT')
                    key = rel.casefold()
                    if key in seen:
                        raise ValueError('SITE_IMPORT_DUPLICATE_PATH')
                    seen.add(key)
                    with archive.open(info) as reader:
                        _copy_imported_stream(rel, reader, root=stage, budget=budget)
                    kept.append(rel)
                    mark(index, total, rel, "WRITE")
        elif path.is_dir():
            note('COPY', 0, 0, path.name)
            for index, item in enumerate(_walk_import_source(path, budget), start=1):
                rel = _safe_import_rel(item.relative_to(path).as_posix())
                if rel is None:
                    skipped += 1
                    mark(index, 0, item.name, "SKIP")
                    continue
                budget.file()
                _assert_no_links(item)
                key = rel.casefold()
                if key in seen:
                    raise ValueError('SITE_IMPORT_DUPLICATE_PATH')
                seen.add(key)
                fd = secure_open(item, os.O_RDONLY | NOFOLLOW | CLOEXEC | NONBLOCK)
                with os.fdopen(fd, 'rb') as reader:
                    if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                        raise ValueError('SITE_IMPORT_SPECIAL_FILE_NOT_ALLOWED')
                    _copy_imported_stream(rel, reader, root=stage, budget=budget)
                kept.append(rel)
                mark(index, 0, rel, "COPY")
        else:
            raise RuntimeError("import must be a zip or folder")
        if len(kept) < 1:
            note("FAIL", 0, 0, "no allowed files")
            return "FAIL: no allowed files in import"
        note('COMMIT', len(kept), len(kept), 'Validated import; switching local site')
        _commit_import(stage, budget)
        stage = None
        sample = ", ".join(kept[:8])
        if len(kept) > 8:
            sample += ", …"
        summary = (
            "PASS · "
            + str(len(kept))
            + " files · skipped "
            + str(skipped)
            + " · "
            + sample
        )
        note("PASS", len(kept), len(kept) + skipped, sample)
        return summary
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('SITE_IMPORT_') else 'SITE_IMPORT_IO_ERROR'
        note('FAIL', 0, 0, reason)
        return 'FAIL: ' + reason
    finally:
        try:
            if stage is not None:
                _remove_import_stage(stage)
        finally:
            _IMPORT_LOCK.release()
