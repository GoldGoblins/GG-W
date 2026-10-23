from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import json
import os
import shutil
import socket
import subprocess
import sys
import time
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
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW
    fd = secure_open(path, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
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


def _php_bind(port: int) -> str:
    return preview_bind_host() + ":" + str(int(port))


def _host_php_argv(php: str, port: int) -> list[str]:
    argv = [php, "-S", _php_bind(port), "-t", str(SITE_ROOT)]
    if PHP_ROUTER.is_file():
        argv.append(str(PHP_ROUTER))
    return argv


def _php_image_present() -> bool:
    if not Path(PODMAN).is_file():
        return False
    inspect = shutil.which("podman") or PODMAN
    proc = subprocess.run(
        [inspect, "image", "exists", PHP_IMAGE],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


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
        PODMAN,
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
    php = shutil.which("php")
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
    if shutil.which("php") or _php_image_present():
        return "PHP"
    return "STATIC"


IMPORT_PROGRESS_BATCH = 25


def _local_import_path(raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("file:"):
        parsed = urlparse(text)
        text = unquote(parsed.path)
    path = Path(text)
    try:
        return path.resolve()
    except OSError:
        return None


def _safe_import_rel(name: str) -> str | None:
    rel = str(name or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/"):
        return None
    parts = Path(rel).parts
    if ".." in parts or parts[:1] == ("/",):
        return None
    posix = Path(*parts).as_posix()
    base = Path(posix).name.lower()
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


def _backup_site_root() -> None:
    if not SITE_ROOT.exists():
        return
    stamp = time.strftime("%Y%m%dT%H%M%S")
    dest = SITE_ROOT.parent / ("site.bak." + stamp)
    shutil.copytree(SITE_ROOT, dest, dirs_exist_ok=False)


def _reset_site_root() -> None:
    if SITE_ROOT.exists():
        shutil.rmtree(SITE_ROOT)
    SITE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)


def _write_imported_file(relative: str, data: bytes) -> None:
    dest = _safe_rel(relative)
    if dest is None:
        return
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW
    fd = secure_open(dest, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _copy_imported_stream(relative: str, reader) -> None:
    dest = _safe_rel(relative)
    if dest is None:
        return
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW
    fd = secure_open(dest, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        shutil.copyfileobj(reader, handle, 1024 * 256)


def import_site_tree(source: str, progress=None) -> str:
    def note(phase: str, current: int, total: int, extra: str = "") -> None:
        if progress is not None:
            progress(phase, current, total, extra)

    path = _local_import_path(source)
    if path is None or not path.exists():
        return "FAIL: import source missing"
    try:
        note("BACKUP", 0, 1, SITE_ROOT.as_posix())
        _backup_site_root()
        note("CLEAR", 1, 1, "")
        _reset_site_root()
        kept: list[str] = []
        skipped = 0

        def mark(index: int, total: int, rel: str, phase: str) -> None:
            if (
                index == 1
                or index == total
                or index % IMPORT_PROGRESS_BATCH == 0
            ):
                note(phase, index, total, rel)

        if path.is_file() and path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                members = [info for info in archive.infolist() if not info.is_dir()]
                total = len(members)
                note("UNPACK", 0, total, path.name)
                for index, info in enumerate(members, start=1):
                    rel = _safe_import_rel(info.filename)
                    if rel is None:
                        skipped += 1
                        mark(index, total, info.filename, "SKIP")
                        continue
                    with archive.open(info) as reader:
                        _copy_imported_stream(rel, reader)
                    kept.append(rel)
                    mark(index, total, rel, "WRITE")
        elif path.is_dir():
            members = [item for item in path.rglob("*") if item.is_file()]
            total = len(members)
            note("COPY", 0, total, path.name)
            for index, item in enumerate(members, start=1):
                rel = _safe_import_rel(item.relative_to(path).as_posix())
                if rel is None:
                    skipped += 1
                    mark(index, total, item.name, "SKIP")
                    continue
                with open(item, "rb") as reader:
                    _copy_imported_stream(rel, reader)
                kept.append(rel)
                mark(index, total, rel, "COPY")
        else:
            raise RuntimeError("import must be a zip or folder")
        if len(kept) < 1:
            ensure_site_root()
            note("FAIL", 0, 0, "no allowed files")
            return "FAIL: no allowed files in import"
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
        ensure_site_root()
        note("FAIL", 0, 0, str(exc))
        return "FAIL: " + str(exc)
