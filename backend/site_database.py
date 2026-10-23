from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_support import runtime_root, local_file_path

import os
import re
import socket
import subprocess
import time
from pathlib import Path

from backend.web_surface import SITE_ROOT

STATE = Path(str(STATE_ROOT))
DATA_DIR = STATE / "mariadb"
SOCK = runtime_root() / "gg-site-mysql.sock"
PID = runtime_root() / "gg-site-mysql.pid"
PORT = 3307
MYSQLD = "/usr/bin/mysqld"
MYSQL = "/usr/bin/mysql"
INSTALL_DB = "/usr/bin/mariadb-install-db"
WP_CONFIG = SITE_ROOT / "wp-config.php"
WP_CONFIG_BAK = SITE_ROOT / "wp-config.one.com.bak"


def _define(name: str) -> str:
    text = WP_CONFIG.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"define\(\s*'" + re.escape(name) + r"'\s*,\s*'([^']*)'",
        text,
    )
    return match.group(1) if match else ""


def _listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), 0.2):
            return True
    except OSError:
        return SOCK.exists()


def ensure_datadir() -> str:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (DATA_DIR / "mysql").is_dir():
        return "PASS: datadir exists"
    proc = subprocess.run(
        [
            INSTALL_DB,
            "--no-defaults",
            "--datadir=" + str(DATA_DIR),
            "--auth-root-authentication-method=normal",
            "--skip-test-db",
            "--user=" + os.environ.get("USER", "GG"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "FAIL: mariadb-install-db " + (proc.stderr or proc.stdout)[:300]
    return "PASS: datadir created"


def start_mysqld() -> str:
    if _listening():
        return "PASS: mysqld already running"
    ready = ensure_datadir()
    if not ready.startswith("PASS"):
        return ready
    log = STATE / "mariadb.err"
    proc = subprocess.Popen(
        [
            MYSQLD,
            "--no-defaults",
            "--datadir=" + str(DATA_DIR),
            "--socket=" + str(SOCK),
            "--pid-file=" + str(PID),
            "--bind-address=127.0.0.1",
            "--port=" + str(PORT),
            "--skip-networking=0",
        ],
        stdout=open(log, "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    deadline = time.time() + 8
    while time.time() < deadline:
        if proc.poll() is not None:
            return "FAIL: mysqld exited"
        if _listening():
            return "PASS: mysqld started"
        time.sleep(0.15)
    return "FAIL: mysqld did not listen"


def _mysql(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    cmd = [
        MYSQL,
        "--protocol=TCP",
        "--host=127.0.0.1",
        "--port=" + str(PORT),
        "--user=root",
        "--batch",
        "--raw",
    ] + args
    return subprocess.run(cmd, input=stdin, capture_output=True, check=False)


def import_sql_dump(source: str, progress=None) -> str:
    path = Path(source)
    if str(source).startswith("file:"):
        from urllib.parse import unquote, urlparse

        path = local_file_path(source)
    if not path.is_file() or path.suffix.lower() != ".sql":
        return "FAIL: SQL dump missing"
    started = start_mysqld()
    if not started.startswith("PASS"):
        return started
    if progress:
        progress("DB", 0, 3, "create database")
    db = _define("DB_NAME") or "goldgoblins_local"
    user = _define("DB_USER") or "goldgoblins"
    password = _define("DB_PASSWORD")
    create = (
        "CREATE DATABASE IF NOT EXISTS `" + db + "` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
    )
    if user:
        create += (
            "CREATE USER IF NOT EXISTS '" + user.replace("'", "") + "'@'127.0.0.1';\n"
        )
        if password:
            create += (
                "ALTER USER '"
                + user.replace("'", "")
                + "'@'127.0.0.1' IDENTIFIED BY '"
                + password.replace("\\", "\\\\").replace("'", "\\'")
                + "';\n"
            )
        create += (
            "GRANT ALL ON `" + db + "`.* TO '"
            + user.replace("'", "")
            + "'@'127.0.0.1';\nFLUSH PRIVILEGES;\n"
        )
    made = _mysql([], stdin=create.encode("utf-8"))
    if made.returncode != 0:
        return "FAIL: create db " + made.stderr.decode("utf-8", "replace")[:240]
    if progress:
        progress("DB", 1, 3, "import sql")
    dumped = path.read_bytes()
    loaded = _mysql([db], stdin=dumped)
    if loaded.returncode != 0:
        return "FAIL: import sql " + loaded.stderr.decode("utf-8", "replace")[:240]
    if progress:
        progress("DB", 2, 3, "rewrite siteurl")
    rewrite_preview_origin("http://127.0.0.1:8765")
    _point_wp_config_local()
    if progress:
        progress("PASS", 3, 3, db)
    return "PASS: imported " + db


def rewrite_preview_origin(origin: str) -> str:
    url = str(origin or "").strip().rstrip("/")
    if not url.startswith("http://127.0.0.1:") and not url.startswith(
        "http://localhost:"
    ):
        return "FAIL: preview origin not localhost"
    if not WP_CONFIG.is_file():
        return "FAIL: wp-config missing"
    db = _define("DB_NAME") or "goldgoblins_local"
    if not start_mysqld().startswith("PASS"):
        return "FAIL: mysqld not listening"
    sql = (
        "UPDATE www_options SET option_value='"
        + url.replace("'", "")
        + "' WHERE option_name IN ('siteurl','home');\n"
    )
    done = _mysql([db, "-e", sql])
    if done.returncode != 0:
        return "FAIL: rewrite siteurl"
    return "PASS: siteurl " + url


def _point_wp_config_local() -> None:
    if not WP_CONFIG.is_file():
        return
    if not WP_CONFIG_BAK.is_file():
        WP_CONFIG_BAK.write_bytes(WP_CONFIG.read_bytes())
    text = WP_CONFIG.read_text(encoding="utf-8", errors="replace")
    text = re.sub(
        r"define\(\s*'DB_HOST'\s*,\s*'[^']*'\s*\)",
        "define('DB_HOST', '127.0.0.1:3307')",
        text,
        count=1,
    )
    WP_CONFIG.write_text(text, encoding="utf-8")
