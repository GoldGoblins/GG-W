"""Native containment checks affect only children created by each test."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import psutil

from backend import gg_testnet_process as limits


class TestnetProcessTests(unittest.TestCase):
    def child(self, source="import time; time.sleep(30)"):
        # A Windows venv launcher starts a second Python executable. Test the
        # actual interpreter, like the native node.exe used by the service.
        executable = getattr(sys, "_base_executable", sys.executable)
        child = subprocess.Popen([executable, "-I", "-c", source], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.addCleanup(limits._stop_owned, child)
        return child

    @unittest.skipUnless(os.name == "nt", "Native Windows Job Object check")
    def test_native_limits_are_queried_and_lease_close_kills_only_child(self):
        child = self.child()
        lease = limits.contain(child)
        self.addCleanup(lease.close)
        self.assertEqual(lease.facts, {"provider": "WINDOWS_JOB_OBJECT", "verified": True,
            "memory_bytes": 512 * 1024 * 1024, "cpu_seconds": 300,
            "active_process_limit": 1, "kill_on_close": True})
        self.assertIsNone(child.poll())
        # Facts are copied, never a mutable authority/control object.
        facts = lease.facts
        facts["memory_bytes"] = 1
        self.assertEqual(lease.facts["memory_bytes"], limits.MEMORY_BYTES)
        lease.close()
        child.wait(timeout=5)
        self.assertTrue(lease.closed)
        lease.close()
        self.assertNotEqual(os.getpid(), child.pid)

    @unittest.skipUnless(os.name == "nt", "Native Windows memory cap check")
    def test_real_memory_allocations_hit_the_os_limit(self):
        # Give the caller time to attach before deliberately requesting more
        # committed memory than the job permits. No shared/user process touched.
        source = "import time;time.sleep(.4); chunks=[]\ntry:\n for _ in range(80): chunks.append(bytearray(8*1024*1024))\nexcept MemoryError: raise SystemExit(73)\nraise SystemExit(74)"
        child = self.child(source)
        lease = limits.contain(child)
        self.addCleanup(lease.close)
        self.assertEqual(child.wait(timeout=12), 73, "OS memory cap did not reject allocation")

    @unittest.skipUnless(os.name == "nt", "Native Windows child limit check")
    def test_active_process_limit_blocks_descendant(self):
        source = "import subprocess,sys,time;time.sleep(.4)\ntry: child=subprocess.Popen([sys.executable,'-I','-c','pass'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); result=child.wait()\nexcept OSError: raise SystemExit(73)\nraise SystemExit(73 if result else 74)"
        child = self.child(source)
        lease = limits.contain(child)
        self.addCleanup(lease.close)
        self.assertEqual(child.wait(timeout=8), 73, "OS process limit permitted descendant")

    @unittest.skipUnless(os.name == "nt", "Native Windows parent-death cleanup check")
    def test_parent_death_closes_job_and_kills_child(self):
        # os._exit bypasses Python destructors: the OS must close the job's
        # non-inheritable handle when this disposable parent process exits.
        source = "\n".join([
            "import os,subprocess,sys",
            "from backend.gg_testnet_process import contain",
            "child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)",
            "lease=contain(child)",
            "print(child.pid,flush=True)",
            "os._exit(0)",
        ])
        executable = getattr(sys, "_base_executable", sys.executable)
        parent = subprocess.Popen([executable, "-c", source], cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(limits._stop_owned, parent)
        output, _ = parent.communicate(timeout=8)
        self.assertEqual(parent.returncode, 0)
        child_pid = int(output.strip())
        deadline = time.monotonic() + 3
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(psutil.pid_exists(child_pid), "Owned child survived parent/job-handle death")

    def test_query_failure_closes_handles_and_kills_owned_child(self):
        if os.name != "nt":
            self.skipTest("Failure path uses native Popen handle")
        child = self.child()
        actual_kernel = limits._kernel()
        closed = []

        class FailedQuery:
            def __getattr__(self, name):
                return getattr(actual_kernel, name)

            def QueryInformationJobObject(self, *_args):
                return False

            def CloseHandle(self, handle):
                closed.append(handle.value if isinstance(handle, wintypes.HANDLE) else handle)
                return actual_kernel.CloseHandle(handle)

        with patch.object(limits, "_kernel", return_value=FailedQuery()), self.assertRaisesRegex(RuntimeError, "CONTAINMENT_FAILED"):
            limits.contain(child)
        child.wait(timeout=5)
        self.assertEqual(len(closed), 2, "Child duplicate and job handles must both close")
        self.assertEqual(len(set(closed)), 2)

    def test_rejects_non_owned_or_exited_process(self):
        with self.assertRaisesRegex(ValueError, "OWNED_CHILD_REQUIRED"):
            limits.contain(object())
        child = self.child("pass")
        child.wait(timeout=5)
        with self.assertRaisesRegex(ValueError, "NOT_RUNNING"):
            limits.contain(child)

    @unittest.skipIf(os.name == "nt", "Truthful unsupported-platform facts")
    def test_nonwindows_does_not_claim_windows_bounds(self):
        child = self.child()
        lease = limits.contain(child)
        self.assertFalse(lease.facts["verified"])
        self.assertEqual(lease.facts["provider"], "UNAVAILABLE")
        self.assertIsNone(lease.facts["memory_bytes"])
        lease.close()
        self.assertIsNone(child.poll())


if __name__ == "__main__":
    unittest.main()
