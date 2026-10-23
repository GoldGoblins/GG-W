"""Exercise artifact identity, bounded reads, attribution and reusable lessons."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import research_lab as lab, research_desk


class ResearchLabTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="gg-research-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.enterContext(patch.object(research_desk, "ROOT", self.root / "desk"))
        self.enterContext(patch.object(lab, "TOOLS_ROOT", self.root / "tools"))
        with lab._LOCK:
            lab._REPORTS.clear()

    def write(self, name, data):
        p = self.root / name
        p.write_bytes(data)
        return p

    def test_inspection_never_executes_selected_file(self):
        marker = self.root / "executed"
        p = self.write("program.py", f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode())
        p.chmod(0o755)
        result = lab.inspect_file(str(p))
        self.assertEqual(result["status"], "INSPECTED")
        self.assertEqual(result["format"], "SOURCE")
        self.assertFalse(marker.exists())
        self.assertEqual(p.read_bytes(), f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode())

    def test_byte_offsets_and_sampling_are_real_and_bounded(self):
        p = self.write("sample.bin", b"\0\0ExampleMarker\0password=not-for-storage\0" + b"large-value\0" * 150)
        result = lab.inspect_file(str(p))
        self.assertEqual(result["strings"][0], {"offset": 2, "text": "ExampleMarker"})
        self.assertLessEqual(len(result["strings"]), lab.MAX_STRINGS)
        self.assertNotIn("not-for-storage", json.dumps(result))

    def test_bad_targets_do_not_launch_tools_or_persist_data(self):
        for raw in ["https://example.invalid/target", "file://remote-host/tmp/target", str(self.root), str(self.root / "missing")]:
            with self.subTest(raw=raw):
                self.assertEqual(lab.inspect_file(raw)["status"], "ERROR")
        self.assertFalse((research_desk.ROOT / research_desk.DB_NAME).exists())

    def test_fifo_is_rejected_without_blocking(self):
        p = self.root / "pipe"
        os.mkfifo(p)
        self.assertEqual(lab.inspect_file(str(p))["reason"], "REGULAR_FILE_REQUIRED")

    def test_file_limit_applies_before_read(self):
        p = self.root / "large"
        with p.open("wb") as f:
            f.truncate(lab.MAX_ARTIFACT_BYTES + 1)
        self.assertEqual(lab.inspect_file(str(p))["reason"], "FILE_TOO_LARGE")

    def test_wasm_uses_existing_structure_inspector(self):
        from test_qip_lab import minimal_qip_module
        p = self.write("component.wasm", minimal_qip_module())
        result = lab.inspect_file(p.as_uri())
        self.assertEqual(result["format"], "WASM")
        self.assertTrue(result["wasm"]["qip_abi"]["render_export"])

    def test_import_is_attributed_and_does_not_verify_claims(self):
        p = self.write("analysis.json", json.dumps({"functions": [{"name": "main", "password": "private-value"}],
            "unknowns": ["runtime behavior"]}).encode())
        result = lab.import_report(str(p), "Ghidra")
        self.assertEqual(result["status"], "IMPORTED")
        self.assertEqual(result["provenance"], "EXTERNAL_REPORT_UNVERIFIED")
        self.assertNotIn("private-value", json.dumps(result))
        self.assertEqual(lab.import_report(str(p), "shell")["status"], "ERROR")
        self.assertFalse((research_desk.ROOT / research_desk.DB_NAME).exists())

    def test_malformed_reports_are_rejected(self):
        for data in [b"[]", b"{}", b"not-json", b'{"number":NaN}']:
            with self.subTest(data=data):
                p = self.write("invalid.json", data)
                self.assertEqual(lab.import_report(str(p), "REA")["status"], "ERROR")

    def test_save_preserves_provenance_and_registers_proposed_method(self):
        p = self.write("source.js", b"export function render() { return 'observed'; }\n")
        report = lab.inspect_file(str(p))
        result = lab.save_finding(report["report_id"], "Renderer structure", "Exported render name is visible in the selected file.",
            "Inspect the exported function\nTest the inferred behavior")
        self.assertEqual(result["status"], "FINDING_SAVED")
        snapshot = research_desk.snapshot()
        self.assertEqual(len(snapshot["evidence"]), 1)
        self.assertEqual(snapshot["evidence"][0]["provenance"], "USER_INTERPRETATION")
        self.assertEqual(snapshot["methods"][0]["status"], "PROPOSED")
        self.assertEqual(snapshot["methods"][0]["source_id"], snapshot["sources"][0]["id"])
        self.assertTrue(research_desk.match_methods("reverse engineering SOURCE"))

    def test_stale_report_cannot_forge_source_evidence(self):
        result = lab.save_finding("unknown", "title", "unbound claim", "step")
        self.assertEqual(result["status"], "REPORT_EXPIRED")
        self.assertFalse((research_desk.ROOT / research_desk.DB_NAME).exists())

    def test_documentation_seeding_is_idempotent(self):
        lab.seed_references()
        lab.seed_references()
        snapshot = research_desk.snapshot()
        self.assertEqual(len(snapshot["sources"]), 3)
        self.assertEqual(len(snapshot["methods"]), 3)
        self.assertTrue(all(m["status"] == "PROPOSED" for m in snapshot["methods"]))

    def test_named_headers_and_long_secrets_are_redacted(self):
        secret = "private-value-" * 40
        p = self.write("secrets.bin", ("password=" + secret + "\0Authorization: Bearer " + secret).encode())
        self.assertNotIn("private-value", json.dumps(lab.inspect_file(str(p))))
        report = self.write("headers.json", json.dumps({"headers": [{"name": "Authorization", "value": secret}]}).encode())
        self.assertNotIn("private-value", json.dumps(lab.import_report(str(report), "REA")))

    def test_methods_reach_future_research_with_steps_and_status(self):
        from backend import thought_desk
        research_desk.add_method({"name": "Retired inspection", "trigger": "reverse engineering",
            "steps": ["obsolete step"], "status": "RETIRED"})
        research_desk.add_method({"name": "Current inspection", "trigger": "reverse engineering",
            "steps": ["Observe first", "Test an inference"], "status": "PROPOSED", "proof": "source-backed"})
        result = thought_desk._research("reverse engineering")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["method_matches"][0]["steps"], ["Observe first", "Test an inference"])
        self.assertEqual(result["method_matches"][0]["status"], "PROPOSED")

    def test_java_magic_is_not_misidentified_as_macho(self):
        p = self.write("Example.class", b"\xca\xfe\xba\xbe\0\0\0\x41\0\x01")
        self.assertEqual(lab.inspect_file(str(p))["format"], "JAVA CLASS CANDIDATE")

    def test_private_key_material_is_not_sampled(self):
        p = self.write("fixture.pem", b"-----BEGIN PRIVATE KEY-----\n" + b"QUJD" * 40 + b"\n-----END PRIVATE KEY-----")
        result = lab.inspect_file(str(p))
        self.assertEqual(result["status"], "ERROR")
        self.assertNotIn("strings", result)


if __name__ == "__main__":
    unittest.main()
