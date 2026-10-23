"""Exercise Windows file exclusion, terminal IO and real local metrics."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


@unittest.skipUnless(os.name == "nt", "Windows platform integration")
class WindowsPlatformTests(unittest.TestCase):
    def test_canonical_and_legacy_paths_use_the_same_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            for name in ('XDG_STATE_HOME', 'GG_DESKTOP_STATE_ROOT'):
                env.pop(name, None)
            env['GG_DATA_HOME'] = directory
            command = (
                "from pathlib import Path;from backend.application_paths import STATE_ROOT,WORKSPACE_ROOT;"
                "from backend.platform_support import platform_path,workspace_root;"
                "assert STATE_ROOT==Path(__import__('os').environ['GG_DATA_HOME'])/'gg-ai-desktop';"
                "assert Path(platform_path('/home/GG/.local/state/goldgoblins/gg-ai-desktop/settings-v1.json'))==STATE_ROOT/'settings-v1.json';"
                "assert workspace_root()==WORKSPACE_ROOT.resolve()"
            )
            result = subprocess.run([sys.executable, '-B', '-c', command], cwd=PROJECT,
                                    env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_file_lock_blocks_an_independent_process_and_releases(self):
        from backend.platform_files import secure_open
        from backend.platform_support import file_locks
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared.lock"
            fd = secure_open(path, os.O_RDWR | os.O_CREAT)
            script = (
                "import os,sys;from backend.platform_files import secure_open;"
                "from backend.platform_support import file_locks;"
                "fd=secure_open(sys.argv[1],os.O_RDWR);"
                "file_locks.flock(fd,file_locks.LOCK_EX|file_locks.LOCK_NB);"
                "os.close(fd)"
            )
            try:
                file_locks.flock(fd, file_locks.LOCK_EX | file_locks.LOCK_NB)
                # A borrowed descriptor is used by nested custody transactions.
                file_locks.flock(fd, file_locks.LOCK_EX | file_locks.LOCK_NB)
                result = subprocess.run([sys.executable, "-c", script, str(path)],
                                        cwd=PROJECT, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"BlockingIOError", result.stderr)
                file_locks.flock(fd, file_locks.LOCK_UN)
                result = subprocess.run([sys.executable, "-c", script, str(path)],
                                        cwd=PROJECT, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                os.close(fd)

    def test_existing_file_is_not_overwritten_by_exclusive_creation(self):
        from backend.platform_files import secure_open
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preserved.txt"
            path.write_bytes(b"preserved")
            with self.assertRaises(FileExistsError):
                secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            self.assertEqual(path.read_bytes(), b"preserved")

    def test_secure_open_rejects_a_directory(self):
        from backend.platform_files import secure_open
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                secure_open(directory, os.O_RDONLY)

    def test_file_urls_stay_within_the_site_root(self):
        from backend import web_surface
        with tempfile.TemporaryDirectory(prefix="gg windows åäö ") as directory:
            original = web_surface.SITE_ROOT
            try:
                web_surface.SITE_ROOT = Path(directory) / "site"
                self.assertTrue(web_surface.url_allowed(web_surface.default_web_url()))
                self.assertFalse(web_surface.url_allowed((Path(directory) / "outside.html").as_uri()))
                self.assertFalse(web_surface.url_allowed("file://remote-server/share/file.html"))
            finally:
                web_surface.SITE_ROOT = original

    def test_metrics_use_real_windows_memory_and_processes(self):
        from backend.windows_telemetry import snapshot
        result = snapshot("PROCESSES")
        self.assertGreater(result["mem_total_kb"], 0)
        self.assertGreater(result["process_count"], 0)
        self.assertTrue(result["processes"])
        self.assertIsNone(result["gpu_busy"])
        self.assertIn("gpu_busy", result["unavailable"])

    def test_conpty_roundtrip_resize_and_fragmented_utf8(self):
        from backend.windows_pty import WindowsPty
        command = "import sys; print('READY',flush=True); print('GOT='+sys.stdin.readline().strip(),flush=True)"
        terminal = WindowsPty([sys.executable, "-u", "-c", command],
                              cwd=PROJECT, env=os.environ.copy())
        output = bytearray()
        sent = False
        deadline = time.monotonic() + 10
        try:
            terminal.resize(100, 40)
            while time.monotonic() < deadline:
                try:
                    output.extend(terminal.read(4096))
                except BlockingIOError:
                    pass
                if b"READY" in output and not sent:
                    message = "WINDOWS åäö input\n".encode("utf-8")
                    split = message.index("å".encode("utf-8")) + 1
                    terminal.write(message[:split])
                    terminal.write(message[split:])
                    sent = True
                if "GOT=WINDOWS åäö input".encode("utf-8") in output:
                    break
                time.sleep(0.02)
            self.assertIn("GOT=WINDOWS åäö input".encode("utf-8"), output)
        finally:
            terminal.close()

    def test_windows_history_maintenance_refuses_to_rewrite(self):
        from backend import codex_image_storage
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_bytes(b'{"type":"test"}\n')
            with self.assertRaises(RuntimeError):
                codex_image_storage.writers(path)
            self.assertEqual(path.read_bytes(), b'{"type":"test"}\n')


if __name__ == "__main__":
    unittest.main()
