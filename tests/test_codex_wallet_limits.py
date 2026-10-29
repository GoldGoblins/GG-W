"""Usage-only disposable records; no CLI, credentials, user log or network IO."""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import codex_wallet as wallet


class CodexWalletLimits(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-model-limit-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "usage.jsonl"
        self.reset_at = int(datetime(2026, 11, 4, 10, 16).astimezone().timestamp())
        wallet._SNAPSHOT_CACHE.clear()
        self.addCleanup(wallet._SNAPSHOT_CACHE.clear)

    def append(self, payload):
        with self.path.open("a", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps({"payload": payload}) + "\n")

    def initial(self):
        self.append({"type": "token_count", "info": {
            "total_token_usage": {"total_tokens": 600000},
            "last_token_usage": {"input_tokens": 152000, "total_tokens": 153000},
            "model_context_window": 475000}, "rate_limits": {
                "limit_id": "codex", "primary": {"used_percent": 82.4,
                "resets_at": self.reset_at, "window_minutes": 300},
                "secondary": {"used_percent": 12}}})
        return wallet.snapshot(self.path)

    def test_exact_provider_percent_and_local_swedish_date(self):
        result = self.initial()
        self.assertEqual(result["limit_percent"], 82.4)
        self.assertEqual(result["limit_label"], "82%")
        self.assertEqual(result["limit_reset_at"], self.reset_at)
        self.assertEqual(result["limit_reset_label"], "10:16 · 4 nov")
        self.assertEqual(result["live_reset_label"], result["limit_reset_label"])
        self.assertEqual(result["context_label"], "152K/475K")

    def test_sparse_or_malformed_limits_keep_last_known_window(self):
        self.initial()
        for limits in ({}, {"primary": None}, {"primary": []},
                       {"secondary": {"used_percent": 13}},
                       {"primary": {"used_percent": None, "resets_at": None}},
                       {"primary": {"used_percent": "NaN", "resets_at": -1}},
                       {"primary": {"used_percent": True, "resets_at": True}}):
            with self.subTest(limits=limits):
                self.append({"type": "token_count", "info": [], "rate_limits": limits})
                result = wallet.snapshot(self.path)
                self.assertEqual(result["limit_percent"], 82.4)
                self.assertEqual(result["limit_reset_at"], self.reset_at)
                self.assertEqual(result["limit_reset_label"], "10:16 · 4 nov")

    def test_provider_reset_changes_are_accepted_before_old_deadline(self):
        self.initial()
        newer = self.reset_at + 7200
        self.append({"rate_limits": {"primary": {"used_percent": 83.25, "resets_at": newer}}})
        result = wallet.snapshot(self.path)
        self.assertEqual(result["limit_percent"], 83.25)
        self.assertEqual(result["limit_reset_at"], newer)
        self.assertEqual(result["limit_reset_label"], "12:16 · 4 nov")
        self.append({"rate_limits": {"primary": {"used_percent": 0}}})
        result = wallet.snapshot(self.path)
        self.assertEqual(result["limit_percent"], 0)
        self.assertEqual(result["limit_label"], "0%")
        self.assertEqual(result["limit_reset_at"], newer)

    def test_unknown_usage_is_not_fabricated_zero(self):
        result = wallet.snapshot(self.path)
        self.assertIsNone(result["limit_percent"])
        self.assertIsNone(result["live_tokens"])
        self.assertEqual(result["limit_label"], "—")
        self.assertEqual(result["limit_reset_label"], "—")

    def test_explicit_new_period_without_usage_does_not_reuse_old_percent(self):
        self.initial()
        self.append({"rate_limits": {"primary": {"resets_at": self.reset_at + 86400}}})
        result = wallet.snapshot(self.path)
        self.assertEqual(result["limit_reset_label"], "10:16 · 5 nov")
        self.assertIsNone(result["limit_percent"])
        self.assertEqual(result["limit_label"], "—")

    def test_unchanged_file_has_no_jsonl_read_and_append_only_consumes_new_row(self):
        first = self.initial()
        with patch.object(Path, "open", side_effect=AssertionError("Unchanged JSONL reread")):
            self.assertEqual(wallet.snapshot(self.path), first)
        self.append({"rate_limits": {"primary": {"used_percent": 84}}})
        with patch.object(wallet, "_consume", wraps=wallet._consume) as consume:
            self.assertEqual(wallet.snapshot(self.path)["limit_percent"], 84)
            self.assertEqual(consume.call_count, 1)

    def test_partial_appended_line_is_retried_only_after_completion(self):
        self.initial()
        row = json.dumps({"payload": {"rate_limits": {"primary": {"used_percent": 85}}}}).encode()
        split = len(row) // 2
        with self.path.open("ab") as target:
            target.write(row[:split])
        with patch.object(wallet, "_consume", wraps=wallet._consume) as consume:
            self.assertEqual(wallet.snapshot(self.path)["limit_percent"], 82.4)
            self.assertEqual(consume.call_count, 0)
            with self.path.open("ab") as target:
                target.write(row[split:] + b"\n")
            self.assertEqual(wallet.snapshot(self.path)["limit_percent"], 85)
            self.assertEqual(consume.call_count, 1)

    def test_truncation_replacement_and_larger_rewrite_discard_old_values(self):
        for mode in ("truncate", "replace", "larger"):
            with self.subTest(mode=mode):
                self.path.unlink(missing_ok=True)
                self.initial()
                row = json.dumps({"payload": {"type": "token_count", "info": {
                    "total_token_usage": {"total_tokens": 20}}}}) + "\n"
                if mode == "larger":
                    row += json.dumps({"payload": {"type": "fixture", "text": "x" * 2000}}) + "\n"
                if mode == "replace":
                    replacement = self.path.with_suffix(".replacement")
                    replacement.write_text(row, encoding="utf-8")
                    replacement.replace(self.path)
                else:
                    self.path.write_text(row, encoding="utf-8")
                result = wallet.snapshot(self.path)
                self.assertIsNone(result["limit_percent"])
                self.assertEqual(result["limit_reset_label"], "—")
                self.assertEqual(result["session_total"], 20)

    def test_same_size_rewrite_reparses_changed_limits(self):
        self.initial()
        row = self.path.read_text(encoding="utf-8").replace('82.4', '55.5')
        previous = self.path.stat().st_mtime_ns
        self.path.write_text(row, encoding="utf-8")
        os.utime(self.path, ns=(previous + 1000000, previous + 1000000))
        self.assertEqual(wallet.snapshot(self.path)["limit_percent"], 55.5)

    def test_other_window_or_limit_bucket_cannot_inherit_wrong_reset(self):
        self.initial()
        self.append({"rate_limits": {"primary": {"window_minutes": 10080, "used_percent": 15}}})
        result = wallet.snapshot(self.path)
        self.assertEqual(result["limit_percent"], 15)
        self.assertIsNone(result["limit_reset_at"])
        self.append({"rate_limits": {"limit_id": "separate-model"}})
        result = wallet.snapshot(self.path)
        self.assertIsNone(result["limit_percent"])
        self.assertEqual(result["limit_reset_label"], "—")

    def test_missing_selected_session_never_falls_back_to_unrelated_newest(self):
        self.initial()
        with patch.object(wallet, "_latest_session", side_effect=AssertionError("Unrelated session lookup")):
            empty = wallet.snapshot(None, self.path.parent, allow_latest=False)
        self.assertIsNone(empty["limit_percent"])
        self.assertEqual(empty["session"], "")

    def test_file_cache_is_bounded_and_preserves_early_valid_limits(self):
        self.initial()
        with self.path.open("a", encoding="utf-8") as target:
            line = json.dumps({"payload": {"type": "fixture", "message": "x" * 4096}}) + "\n"
            target.write(line * 270)
        wallet._SNAPSHOT_CACHE.clear()
        self.assertEqual(wallet.snapshot(self.path)["limit_percent"], 82.4)
        for index in range(9):
            other = self.path.parent / f"other-{index}.jsonl"
            other.write_text('{"payload":{}}\n', encoding="utf-8")
            wallet.snapshot(other)
        self.assertEqual(len(wallet._SNAPSHOT_CACHE), 8)


if __name__ == "__main__":
    unittest.main()
