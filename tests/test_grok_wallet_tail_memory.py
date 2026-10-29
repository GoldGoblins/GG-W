"""Tail telemetry reads only its requested bytes, independent of log size."""
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import tracemalloc
import unittest
from unittest.mock import patch

from backend import grok_wallet


class GrokWalletTailMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-wallet-tail-")
        self.directory = Path(self.temporary.name)
        grok_wallet._TAIL_CACHE.clear()

    def tearDown(self):
        grok_wallet._TAIL_CACHE.clear()
        self.temporary.cleanup()

    def test_large_file_read_and_peak_allocation_are_bounded(self):
        path = self.directory / "large.jsonl"
        limit = 256 * 1024
        with path.open("wb") as stream:
            stream.seek(64 * 1024 * 1024)
            stream.write(b"\nlast telemetry fixture\n")
        original_open = Path.open
        reads = []
        seeks = []

        class ObservedFile:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def seek(self, offset):
                seeks.append(offset)
                return self.stream.seek(offset)
            def read(self, size):
                reads.append(size)
                return self.stream.read(size)

        def observed_open(target, *args, **kwargs):
            return ObservedFile(original_open(target, *args, **kwargs))

        tracemalloc.start()
        try:
            before = tracemalloc.get_traced_memory()[0]
            with patch.object(Path, "open", observed_open), patch.object(
                    Path, "read_bytes", side_effect=AssertionError("Whole-file read forbidden")):
                result = grok_wallet._tail_cached(path, limit)
            peak = tracemalloc.get_traced_memory()[1] - before
        finally:
            tracemalloc.stop()
        self.assertEqual(reads, [limit])
        self.assertEqual(seeks, [path.stat().st_size - limit])
        self.assertEqual(len(result), limit)
        self.assertTrue(result.endswith("\nlast telemetry fixture\n"))
        self.assertLess(peak, limit * 4)

    def test_exact_byte_tail_replacement_decode_and_cache_invalidation(self):
        path = self.directory / "unicode.jsonl"
        data = b"prefix\n" + "räv🐺".encode() + b"\xfflast\n"
        path.write_bytes(data)
        for limit in (1, 8, len(data), len(data) + 100):
            self.assertEqual(grok_wallet._tail_cached(path, limit), data[-limit:].decode("utf-8", "replace"))
        with patch.object(Path, "open", side_effect=AssertionError("Unchanged cache reopened")):
            self.assertEqual(grok_wallet._tail_cached(path, 8), data[-8:].decode("utf-8", "replace"))
        # Same size but a new mtime must invalidate as well as growth does.
        old_stamp = path.stat().st_mtime_ns
        changed = b"X" * len(data)
        path.write_bytes(changed)
        os.utime(path, ns=(old_stamp + 1_000_000, old_stamp + 1_000_000))
        self.assertEqual(grok_wallet._tail_cached(path, 8), "X" * 8)
        with path.open("ab") as stream:
            stream.write(b"grown")
        self.assertEqual(grok_wallet._tail_cached(path, 8), "XXXgrown")

    def test_cache_limit_is_part_of_identity_and_recent_entries_are_retained(self):
        paths = []
        for index in range(grok_wallet._TAIL_CACHE_LIMIT):
            path = self.directory / (str(index) + ".jsonl")
            path.write_bytes(b"0123456789")
            paths.append(path)
            self.assertEqual(grok_wallet._tail_cached(path, 3), "789")
        self.assertEqual(grok_wallet._tail_cached(paths[0], 3), "789")
        self.assertEqual(grok_wallet._tail_cached(paths[0], 6), "456789")
        self.assertEqual(len(grok_wallet._TAIL_CACHE), grok_wallet._TAIL_CACHE_LIMIT)
        self.assertIn((str(paths[0]), 3), grok_wallet._TAIL_CACHE)
        self.assertIn((str(paths[0]), 6), grok_wallet._TAIL_CACHE)
        self.assertNotIn((str(paths[1]), 3), grok_wallet._TAIL_CACHE)

    def test_stat_and_read_errors_return_empty_without_publishing_bad_cache(self):
        path = self.directory / "missing.jsonl"
        self.assertEqual(grok_wallet._tail_cached(path, 20), "")
        path.write_bytes(b"fixture")
        with patch.object(Path, "open", side_effect=PermissionError("fixture denied")):
            self.assertEqual(grok_wallet._tail_cached(path, 20), "")
        self.assertFalse(grok_wallet._TAIL_CACHE)
        self.assertEqual(grok_wallet._tail_cached(path, 20), "fixture")
        path.unlink()
        self.assertEqual(grok_wallet._tail_cached(path, 20), "")
        self.assertFalse(grok_wallet._TAIL_CACHE)
        for invalid in (0, -1, True):
            with self.assertRaises(ValueError):
                grok_wallet._tail_cached(path, invalid)

    def test_concurrent_hits_and_evictions_preserve_exact_outputs_and_cache_cap(self):
        paths = []
        for index in range(96):
            path = self.directory / (str(index) + ".jsonl")
            path.write_text("prefix:fixture-" + str(index), encoding="utf-8")
            paths.append(path)

        class YieldingCache(OrderedDict):
            def get(self, key, default=None):
                hit = super().get(key, default)
                if hit is not None:
                    # Exercise the old get→move_to_end eviction window.
                    time.sleep(0.0001)
                return hit

        start = threading.Barrier(8)

        def reader(worker):
            start.wait(timeout=10)
            for step in range(256):
                index = (step + worker) % 16 if worker < 6 else 16 + (step * 17 + worker) % 80
                limit = 9 + step % 3
                result = grok_wallet._tail_cached(paths[index], limit)
                self.assertEqual(result, ("prefix:fixture-" + str(index))[-limit:])
                with grok_wallet._TAIL_CACHE_LOCK:
                    self.assertLessEqual(len(grok_wallet._TAIL_CACHE), grok_wallet._TAIL_CACHE_LIMIT)

        with patch.object(grok_wallet, "_TAIL_CACHE", YieldingCache()):
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(reader, worker) for worker in range(8)]
                for future in futures:
                    future.result(timeout=20)
            self.assertEqual(len(grok_wallet._TAIL_CACHE), grok_wallet._TAIL_CACHE_LIMIT)


if __name__ == "__main__":
    unittest.main()
