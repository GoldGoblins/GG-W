#!/usr/bin/env python3
"""Closed-history cleanup and paginated resume regression tests, fully local."""
from __future__ import annotations

import argparse
import ast
from contextlib import closing
import fcntl
import gzip
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import codex_image_storage as storage

TABLES = ("thread_turns", "thread_items", "thread_realtime_items",
          "thread_history_projection_state")


class HistoryFixture:
    def __init__(self, home: Path, *, image: bool = False, error: bool = False,
                 aborted: bool = False):
        self.home = home
        self.root = home / "sessions"
        self.sid, self.tid = str(uuid.uuid4()), str(uuid.uuid4())
        self.path = self.root / "2026/10/08" / (
            "rollout-2026-10-08T08-00-00-" + self.sid + ".jsonl")
        self.path.parent.mkdir(parents=True)
        self.database = home / "thread_history_1.sqlite"
        self.rows = []
        now = "2026-10-08T08:00:00Z"

        def add(kind, payload):
            self.rows.append(dict(timestamp=now, ordinal=len(self.rows),
                                  type=kind, payload=payload))

        add("session_meta", dict(id=self.sid, session_id=self.sid,
            timestamp=now, cwd=str(home / "workspace"), originator="codex-tui",
            cli_version="0.161.0", source="cli", thread_source="user",
            model_provider="offline", base_instructions={"text": "Offline test."},
            history_mode="paginated"))
        add("event_msg", dict(type="task_started", turn_id=self.tid,
            root_turn_id=self.tid, started_at=1791446400,
            model_context_window=200000, collaboration_mode_kind="default"))
        add("event_msg", dict(type="item_completed", thread_id=self.sid,
            turn_id=self.tid, item=dict(type="UserMessage", id=str(uuid.uuid4()),
                client_id=None, content=[dict(type="text", text="Probe question.",
                                             text_elements=[])]),
            started_at_ms=1791446400000, completed_at_ms=1791446400000))
        content = [dict(type="input_text", text="Probe question.")]
        if image:
            content.append(dict(type="input_image",
                image_url="data:image/png;base64," + "A" * 65536))
        add("response_item", dict(type="message", id=str(uuid.uuid4()),
                                  role="user", content=content))
        if not error and not aborted:
            add("response_item", dict(type="message", id=str(uuid.uuid4()),
                role="assistant", phase="final_answer",
                content=[dict(type="output_text", text="SUCCESS_MARKER_FINAL")]))
            add("event_msg", dict(type="item_completed", thread_id=self.sid,
                turn_id=self.tid, item=dict(type="AgentMessage", id=str(uuid.uuid4()),
                    content=[dict(type="Text", text="SUCCESS_MARKER_FINAL")],
                    phase="final_answer"), started_at_ms=1791446460000,
                completed_at_ms=1791446460000))
        if aborted:
            add("event_msg", dict(type="turn_aborted", turn_id=self.tid,
                                  reason="interrupted"))
        else:
            completion = dict(type="task_complete", turn_id=self.tid,
                last_agent_message=None if error else "SUCCESS_MARKER_FINAL",
                started_at=1791446400, completed_at=1791446460,
                duration_ms=60000, time_to_first_token_ms=100)
            if error:
                completion["error"] = dict(message="Offline usage limit fixture.",
                                          codex_error_info="usage_limit_exceeded")
            add("event_msg", completion)
        self.status = "interrupted" if aborted else "failed" if error else "completed"
        self.write()

    def encoded(self, rows=None):
        return b"".join((json.dumps(row) + "\n").encode()
                        for row in (self.rows if rows is None else rows))

    def write(self, rows=None):
        self.path.write_bytes(self.encoded(rows))

    def create_projection(self, *, prefix=None, status=None):
        rows = self.rows if prefix is None else self.rows[:prefix]
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE thread_turns (
                    thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER,
                    status TEXT, rollout_byte_offset INTEGER,
                    rollout_end_ordinal INTEGER, rollout_end_byte_offset INTEGER);
                CREATE TABLE thread_items (thread_id TEXT, item_json TEXT);
                CREATE TABLE thread_realtime_items (thread_id TEXT, item_json TEXT);
                CREATE TABLE thread_history_projection_state (
                    thread_id TEXT, next_rollout_byte_offset INTEGER,
                    next_rollout_ordinal INTEGER);
            """)
            done = prefix is None
            connection.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)",
                (self.sid, self.tid, 1, status or (self.status if done else "inProgress"),
                 len(self.encoded(self.rows[:1])),
                 len(rows) - 1 if done and self.status != "interrupted" else None,
                 len(self.encoded(rows)) if done and self.status != "interrupted" else None))
            for table in ("thread_items", "thread_realtime_items"):
                connection.execute(f"INSERT INTO {table} VALUES (?,?)",
                                   (self.sid, "fixture cached item"))
                connection.execute(f"INSERT INTO {table} VALUES (?,?)",
                                   ("other-thread", "other item"))
            connection.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)",
                               (self.sid, len(self.encoded(rows)), len(rows)))
            connection.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)",
                               ("other-thread", "other-turn", 1, "completed", 0, 2, 10))
            connection.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)",
                               ("other-thread", 10, 3))

    def counts(self, sid=None):
        with closing(sqlite3.connect(self.database)) as connection:
            return [connection.execute(f"SELECT count(*) FROM {table} WHERE thread_id=?",
                    (sid or self.sid,)).fetchone()[0] for table in TABLES]


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-history-test-")
        self.home = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_writer_lock_prevents_live_cleanup_and_cache_repair(self):
        fixture = HistoryFixture(self.home, image=True)
        fixture.create_projection(status="inProgress")
        original = fixture.path.read_bytes()
        gate = storage._writer_gate(fixture.path)
        try:
            self.assertEqual(storage.clean_session(fixture.path, live=True)["status"], "busy")
            self.assertEqual(fixture.path.read_bytes(), original)
            self.assertEqual(fixture.counts(), [1] * 4)
        finally:
            gate.close()

    def test_append_writer_without_codex_lock_is_also_untouched(self):
        fixture = HistoryFixture(self.home, image=True)
        original = fixture.path.read_bytes()
        with fixture.path.open("ab"):
            self.assertEqual(storage.clean_session(fixture.path, live=True)["status"], "busy")
        self.assertEqual(fixture.path.read_bytes(), original)

    def test_allowed_codex_writer_is_not_paused_or_rewritten(self):
        fixture = HistoryFixture(self.home, image=True)
        original = fixture.path.read_bytes()
        with patch.object(storage, "writers", return_value=[(123, "fixture", True)]), \
                patch.object(storage.os, "kill") as kill:
            self.assertEqual(storage.clean_session(fixture.path, live=True)["status"], "busy")
            kill.assert_not_called()
        self.assertEqual(fixture.path.read_bytes(), original)

    def test_closed_cleanup_preserves_final_and_invalidates_only_selected_thread(self):
        fixture = HistoryFixture(self.home, image=True)
        fixture.create_projection()
        result = storage.clean_session(fixture.path)
        self.assertEqual(result["status"], "cleaned")
        self.assertGreater(result["saved"], 60000)
        rows = [json.loads(line) for line in fixture.path.read_bytes().splitlines()]
        self.assertEqual([row["ordinal"] for row in rows], list(range(len(fixture.rows))))
        self.assertEqual(rows[0], fixture.rows[0])
        self.assertEqual(rows[4:], fixture.rows[4:])
        self.assertNotIn(b"data:image/", fixture.path.read_bytes())
        self.assertEqual(fixture.counts(), [0] * 4)
        self.assertEqual(fixture.counts("other-thread"), [1] * 4)

    def test_healthy_history_is_not_rebuilt(self):
        fixture = HistoryFixture(self.home)
        fixture.create_projection()
        original = fixture.path.read_bytes()
        self.assertEqual(storage.prepare_resume(fixture.path)["repaired"], 0)
        self.assertEqual(fixture.counts(), [1] * 4)
        self.assertEqual(fixture.path.read_bytes(), original)

    def test_completed_turn_with_in_progress_cache_is_repaired(self):
        fixture = HistoryFixture(self.home)
        fixture.create_projection(status="inProgress")
        result = storage.prepare_resume(fixture.path)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["repaired"], 1)
        self.assertEqual(fixture.counts(), [0] * 4)

    def test_correct_projection_prefix_can_read_new_completion_normally(self):
        fixture = HistoryFixture(self.home)
        fixture.create_projection(prefix=4)
        self.assertEqual(storage.prepare_resume(fixture.path)["repaired"], 0)
        self.assertEqual(fixture.counts(), [1] * 4)

    def test_daemon_held_history_repairs_only_the_transactional_cache(self):
        fixture = HistoryFixture(self.home, image=True)
        fixture.create_projection(prefix=4)
        fixture.rows[3]["payload"]["content"][1] = dict(type="input_text", text="Image omitted.")
        fixture.write()
        original = fixture.path.read_bytes()
        gate = storage._writer_gate(fixture.path)
        try:
            result = storage.prepare_resume(fixture.path)
            self.assertEqual(result, dict(status="unchanged", repaired=1, active_history=True))
            self.assertEqual(fixture.path.read_bytes(), original)
            self.assertEqual(fixture.counts(), [0] * 4)
        finally:
            gate.close()

    def test_image_shrink_and_saved_completion_repair_stale_checkpoint(self):
        fixture = HistoryFixture(self.home, image=True)
        fixture.create_projection(prefix=4)
        fixture.rows[3]["payload"]["content"][1] = dict(type="input_text", text="Image omitted.")
        fixture.write()
        original = fixture.path.read_bytes()
        self.assertEqual(storage.prepare_resume(fixture.path)["repaired"], 1)
        self.assertEqual(fixture.path.read_bytes(), original)
        self.assertEqual(fixture.counts(), [0] * 4)

    def test_wrong_ordinal_at_valid_byte_boundary_is_repaired(self):
        fixture = HistoryFixture(self.home)
        fixture.create_projection()
        with closing(sqlite3.connect(fixture.database)) as connection, connection:
            connection.execute("UPDATE thread_history_projection_state SET next_rollout_ordinal=1 WHERE thread_id=?", (fixture.sid,))
        self.assertEqual(storage.prepare_resume(fixture.path)["repaired"], 1)

    def test_genuine_failures_and_interruptions_are_preserved(self):
        for kind in ("error", "aborted"):
            with self.subTest(kind=kind):
                home = self.home / kind
                fixture = HistoryFixture(home, **{kind: True})
                fixture.create_projection()
                original = fixture.path.read_bytes()
                self.assertEqual(storage.prepare_resume(fixture.path)["repaired"], 0)
                self.assertEqual(fixture.path.read_bytes(), original)
                self.assertEqual(fixture.counts(), [1] * 4)

    def test_partial_file_never_changes_history_or_index(self):
        fixture = HistoryFixture(self.home, image=True)
        fixture.create_projection()
        fixture.path.write_bytes(fixture.path.read_bytes() + b'{"unfinished":')
        original = fixture.path.read_bytes()
        self.assertEqual(storage.clean_session(fixture.path)["status"], "partial")
        self.assertEqual(fixture.path.read_bytes(), original)
        self.assertEqual(fixture.counts(), [1] * 4)
        self.assertFalse(fixture.path.with_name("." + fixture.path.name + ".image-stage").exists())

    def test_unsupported_schema_never_publishes_modified_history(self):
        fixture = HistoryFixture(self.home, image=True)
        with closing(sqlite3.connect(fixture.database)) as connection, connection:
            connection.execute("CREATE TABLE future_schema (value TEXT)")
        original = fixture.path.read_bytes()
        with self.assertRaises(RuntimeError):
            storage.clean_session(fixture.path)
        self.assertEqual(fixture.path.read_bytes(), original)

    def test_failed_publication_leaves_complete_original_for_cache_replay(self):
        fixture = HistoryFixture(self.home, image=True)
        fixture.create_projection()
        original = fixture.path.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("Fixture publication failure")):
            with self.assertRaises(OSError):
                storage.clean_session(fixture.path)
        self.assertEqual(fixture.path.read_bytes(), original)
        self.assertEqual(fixture.counts(), [0] * 4)

    def test_legacy_recovery_restores_log_and_discards_shifted_projection(self):
        fixture = HistoryFixture(self.home)
        fixture.create_projection(status="inProgress")
        original = fixture.path.read_bytes()
        backup = fixture.path.with_name("." + fixture.path.name + ".image-recovery.gz")
        marker = fixture.path.with_name("." + fixture.path.name + ".image-commit")
        with gzip.open(backup, "wb") as output:
            output.write(original)
        marker.write_text(json.dumps(dict(inode=fixture.path.stat().st_ino)))
        fixture.path.write_bytes(original[:20])
        storage.prepare_resume(fixture.path)
        self.assertEqual(fixture.path.read_bytes(), original)
        self.assertFalse(marker.exists())
        self.assertFalse(backup.exists())
        self.assertEqual(fixture.counts(), [0] * 4)

    def test_legacy_recovery_does_not_overwrite_an_open_log(self):
        fixture = HistoryFixture(self.home)
        original = fixture.path.read_bytes()
        backup = fixture.path.with_name("." + fixture.path.name + ".image-recovery.gz")
        marker = fixture.path.with_name("." + fixture.path.name + ".image-commit")
        with gzip.open(backup, "wb") as output:
            output.write(original)
        marker.write_text(json.dumps(dict(inode=fixture.path.stat().st_ino)))
        with fixture.path.open("ab"):
            with self.assertRaises(RuntimeError):
                storage._recover_pending(fixture.root)
        self.assertEqual(fixture.path.read_bytes(), original)
        self.assertTrue(marker.exists())
        self.assertTrue(backup.exists())


class StartupTests(unittest.TestCase):
    """Exercise the actual host start method without Qt/app state or timers."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-history-startup-")
        self.fixture = HistoryFixture(Path(self.temporary.name))
        self.fixture.create_projection(status="inProgress")
        self.events = []
        source = Path(__file__).resolve().parents[1] / "backend/chat_surface_host.py"
        tree = ast.parse(source.read_text())
        host_class = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                          and node.name == "ChatSurfaceHost")
        method = next(node for node in host_class.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_start_gpt_tui")

        def prepare(path):
            self.events.append("prepare")
            return storage.prepare_resume(path)

        def guard(root, owner):
            self.events.append("guard")
            return SimpleNamespace(poll=lambda: None)

        namespace = dict(os=os, pty=pty, shutil=shutil, json=json, time=time,
            fcntl=fcntl, termios=termios, struct=struct, subprocess=subprocess,
            sqlite3=sqlite3, DESKTOP_CODEX_HOME=self.fixture.home,
            DESKTOP_CODEX_SESSIONS=self.fixture.root, CODEX_SESSIONS=self.fixture.root,
            GROK_CWD=self.fixture.home, prepare_codex_resume=prepare,
            start_codex_image_guard=guard,
            codex_session_path=lambda sid, **kwargs: self.fixture.path)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        self.start = namespace["_start_gpt_tui"]
        self.namespace = namespace
        self.output = []
        self.open_masters = []

        def watch(terminal, proc, master):
            self.open_masters.append(master)

        self.host = SimpleNamespace(_sessions={}, _gpt_size=(80, 24),
            _gpt_grid=SimpleNamespace(feed_bytes=self.output.append),
            _gpt_session_id=self.fixture.sid, _gpt_storage_guard=None,
            _gpt_session_location=lambda sid: (self.fixture.home, self.fixture.root),
            _gpt_session_capture_roots=lambda root: (root,),
            _session_files=lambda root: set(root.rglob("*.jsonl")),
            _gptui_developer_instructions=lambda: "Offline fixture.", _watch_pty=watch)

    def tearDown(self):
        for descriptor in self.open_masters:
            os.close(descriptor)
        self.temporary.cleanup()

    def test_cache_is_prepared_before_host_spawns_codex(self):
        def spawn(*args, **kwargs):
            self.events.append("spawn")
            self.assertEqual(self.fixture.counts(), [0] * 4)
            self.assertEqual(kwargs["env"]["CODEX_HOME"], str(self.fixture.home))
            self.assertIn("resume", args[0])
            return SimpleNamespace()

        with patch.object(shutil, "which", return_value="/fake/offline-codex"), \
                patch.object(subprocess, "Popen", side_effect=spawn):
            self.assertTrue(self.start(self.host))
        self.assertEqual(self.events, ["prepare", "guard", "spawn"])

    def test_busy_history_does_not_launch_a_second_writer(self):
        self.namespace["prepare_codex_resume"] = lambda path: dict(status="busy")
        with patch.object(shutil, "which", return_value="/fake/offline-codex"), \
                patch.object(subprocess, "Popen") as spawn:
            self.assertFalse(self.start(self.host))
            spawn.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertTrue(self.output)
        self.assertEqual(self.fixture.counts(), [1] * 4)

    def test_running_chat_is_reused_without_cache_repair(self):
        self.host._sessions["ws.tui.gpt"] = {"proc": "fixture running process"}
        with patch.object(subprocess, "Popen") as spawn:
            self.assertTrue(self.start(self.host))
            spawn.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertEqual(self.fixture.counts(), [1] * 4)


def resume_cli(binary: Path, fixture: HistoryFixture, during=None) -> str:
    """Run the real TUI in an isolated, unauthenticated, offline Codex home."""
    workspace = fixture.home / "workspace"
    workspace.mkdir(exist_ok=True)
    (fixture.home / "config.toml").write_text(
        'model_provider = "offline"\nmodel = "offline-fixture"\n'
        '[model_providers.offline]\nname = "Offline fixture"\n'
        'base_url = "http://127.0.0.1:1/v1"\nwire_api = "responses"\n'
        'requires_openai_auth = false\n')
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "LANG", "USER", "LOGNAME"}}
    env.update(CODEX_HOME=str(fixture.home), TERM="xterm-256color")
    proc = subprocess.Popen([str(binary), "--no-alt-screen", "resume", fixture.sid],
        cwd=workspace, env=env, stdin=slave, stdout=slave, stderr=slave,
        start_new_session=True)
    os.close(slave)
    output = b""
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and proc.poll() is None:
            if select.select([master], [], [], .1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                output += chunk
                if b"\x1b[6n" in chunk:
                    os.write(master, b"\x1b[1;1R")
        if during is not None:
            during()
        if proc.poll() is None:
            os.write(master, b"\x04")
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
    finally:
        if proc.poll() is None:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        os.close(master)
    return re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", output).decode("utf-8", "replace")


def stop_test_daemon(binary: Path, fixture: HistoryFixture):
    # Daemons outlive the TUI. Bound cleanup strictly to this disposable home;
    # never signal the desktop's server or depend on its grace-period shutdown.
    assert fixture.home.parent == Path(tempfile.gettempdir())
    assert fixture.home.name.startswith("gg-codex-")
    owners = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if (proc / "comm").read_text().strip() != "codex":
                continue
            if b"app-server" not in (proc / "cmdline").read_bytes().split(b"\0"):
                continue
            environment = (proc / "environ").read_bytes().split(b"\0")
            if ("CODEX_HOME=" + str(fixture.home)).encode() not in environment:
                continue
            pid = int(proc.name)
            owners.append((pid, storage._identity(pid), True))
        except OSError:
            continue

    def alive(owner):
        pid, start, _ = owner
        try:
            return (storage._identity(pid) == start and
                Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z")
        except OSError:
            return False

    for owner in owners:
        if alive(owner):
            os.kill(owner[0], signal.SIGTERM)
    deadline = time.monotonic() + 2
    while any(alive(owner) for owner in owners) and time.monotonic() < deadline:
        time.sleep(.02)
    for owner in owners:
        if alive(owner):
            os.kill(owner[0], signal.SIGKILL)
    deadline = time.monotonic() + 2
    while any(alive(owner) for owner in owners) and time.monotonic() < deadline:
        time.sleep(.02)
    assert not any(alive(owner) for owner in owners)


def verify_real_cli(binary: Path):
    with tempfile.TemporaryDirectory(prefix="gg-codex-resume-test-") as folder:
        fixture = HistoryFixture(Path(folder), image=True)
        fixture.write(fixture.rows[:4])
        def check_active():
            active_original = fixture.path.read_bytes()
            result = storage.clean_session(fixture.path, live=True)
            assert result["status"] == "busy", result
            assert fixture.path.read_bytes() == active_original

        try:
            output = resume_cli(binary, fixture, check_active)
            assert "Conversation interrupted" in output
            # Reproduce the former live rewrite: shorten indexed input and
            # append a valid final answer plus task_complete event.
            fixture.rows[3]["payload"]["content"][1] = dict(type="input_text", text="Image omitted.")
            fixture.write()
            output = resume_cli(binary, fixture)
            assert "Conversation interrupted" in output
            assert "SUCCESS_MARKER_FINAL" not in output
            original = fixture.path.read_bytes()
            result = storage.prepare_resume(fixture.path)
            assert result.get("repaired") == 1, result
            assert fixture.path.read_bytes() == original
            output = resume_cli(binary, fixture)
            assert "SUCCESS_MARKER_FINAL" in output
            assert "Conversation interrupted" not in output
            assert storage.prepare_resume(fixture.path)["repaired"] == 0
            print("REAL_CODEX_RESUME_REGRESSION=PASS (active history preserved; saved final restored)")
        finally:
            stop_test_daemon(binary, fixture)
    for kind in ("error", "aborted"):
        with tempfile.TemporaryDirectory(prefix="gg-codex-error-test-") as folder:
            fixture = HistoryFixture(Path(folder), image=True, **{kind: True})
            try:
                resume_cli(binary, fixture)
                stop_test_daemon(binary, fixture)
                assert storage.prepare_resume(fixture.path)["status"] == "cleaned"
                output = resume_cli(binary, fixture)
                expected = ("Offline usage limit fixture." if kind == "error"
                            else "Conversation interrupted")
                assert expected in output
                assert "SUCCESS_MARKER_FINAL" not in output
                assert storage.prepare_resume(fixture.path)["repaired"] == 0
            finally:
                stop_test_daemon(binary, fixture)
        print(f"REAL_CODEX_{kind.upper()}_PRESERVED=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, help="Optional installed CLI for offline PTY verification")
    args, remaining = parser.parse_known_args()
    result = unittest.main(argv=[sys.argv[0], *remaining], exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.codex:
        verify_real_cli(args.codex.resolve())
