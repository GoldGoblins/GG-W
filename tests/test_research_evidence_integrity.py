"""Evidence commits, tested-method binding and clean recovery use real SQLite."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import research_desk as desk, research_lab as lab, research_learning as learning


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-evidence-integrity-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(desk, 'ROOT', self.root / 'desk'))
        with lab._LOCK:
            lab._REPORTS.clear()

    def report(self):
        path = self.root / 'source.js'
        path.write_text('export function next(value) { return value + 7; }', encoding='utf-8')
        return lab.inspect_file(str(path))

    def test_middle_write_failure_rolls_back_entire_finding_and_retry_succeeds(self):
        report = self.report()
        with patch.object(desk, 'add_method', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):
                lab.save_finding(report['report_id'], 'Observation', 'A function is present', 'Inspect syntax')
        snapshot = desk.snapshot()
        self.assertFalse(snapshot['sources'])
        self.assertFalse(snapshot['evidence'])
        self.assertFalse(snapshot['methods'])
        saved = lab.save_finding(report['report_id'], 'Observation', 'A function is present', 'Inspect syntax')
        retained = desk.finding_snapshot(saved['evidence_id'])
        self.assertEqual(retained['artifact_sha256'], report['artifact_sha256'])
        self.assertEqual(retained['strings'], report['strings'])
        self.assertEqual(len(desk.snapshot()['evidence']), 1)

    def test_retention_quota_failure_rolls_back_all_index_rows(self):
        report = self.report()
        with patch.object(desk, 'MAX_FINDING_STORAGE', 1):
            with self.assertRaisesRegex(ValueError, 'FINDING_STORAGE_LIMIT'):
                lab.save_finding(report['report_id'], 'Observation', 'A function exists', 'Review')
        snapshot = desk.snapshot()
        self.assertFalse(snapshot['sources'] or snapshot['methods'] or snapshot['evidence'])

    def test_retained_snapshot_survives_report_cache_eviction_and_detects_damage(self):
        report = self.report()
        saved = lab.save_finding(report['report_id'], 'Observation', 'A function exists')
        lab._REPORTS.clear()
        self.assertIsNotNone(desk.finding_snapshot(saved['evidence_id']))
        reopened = lab.load_finding(saved['evidence_id'])
        self.assertEqual(reopened['status'], 'FINDING_REPORT_READY')
        self.assertEqual(reopened['report']['artifact_sha256'], report['artifact_sha256'])
        self.assertTrue(desk.snapshot()['evidence'][0]['has_snapshot'])
        with desk._LOCK, desk._db() as db:
            db.execute("UPDATE finding_snapshots SET content_json='{}'")
        self.assertIsNone(desk.finding_snapshot(saved['evidence_id']))

    def test_caller_cannot_self_assert_verified_method(self):
        result = desk.add_method({'name': 'Unproved claim', 'status': 'VERIFIED',
            'steps': ['Claim success'], 'proof': json.dumps({'test_schema': 'gg.research-known-answer.v1'})})
        self.assertEqual(result['method_status'], 'PROPOSED')
        self.assertEqual(learning.verify_method(result['method_id'])['status'], 'INDEPENDENT_TEST_REQUIRED')

    def test_real_test_receipt_is_bound_to_unchanged_method(self):
        payload = {'name': 'Synthetic workflow', 'trigger': 'fixture', 'steps': ['Check known value'], 'proof': 'Synthetic regression fixture'}
        proof = {'test_schema': 'gg.research-known-answer.v1', 'checks': {'known_value': True},
                 'scope': 'Synthetic fixture only', 'engine': 'Test fixture'}
        result = desk._record_tested_method(payload, proof)
        self.assertEqual(learning.verify_method(result['method_id'])['status'], 'TESTED_WORKFLOW')
        with desk._LOCK, desk._db() as db:
            db.execute("UPDATE methods SET proof='changed claim' WHERE id=?", (result['method_id'],))
        self.assertEqual(learning.verify_method(result['method_id'])['status'], 'INDEPENDENT_TEST_REQUIRED')
        self.assertEqual(desk.snapshot()['methods'][0]['status'], 'PROPOSED')

    def test_failed_fixture_never_gets_test_receipt(self):
        with self.assertRaises(ValueError):
            desk._record_tested_method({'name': 'Fails'}, {'test_schema': 'gg.research-known-answer.v1',
                'checks': {'value': False}, 'scope': 'Fixture', 'engine': 'Test'})
        self.assertFalse(desk.snapshot()['methods'])

    def test_legacy_unbound_verified_flags_are_not_replayed_as_tested_memory(self):
        result = desk.add_method({'name': 'Legacy fixture', 'trigger': 'legacy', 'steps': ['Review']})
        with desk._LOCK, desk._db() as db:
            db.execute("UPDATE methods SET status='VERIFIED' WHERE id=?", (result['method_id'],))
        self.assertEqual(desk.match_methods('legacy')[0]['status'], 'PROPOSED')
        self.assertEqual(desk.snapshot()['methods'][0]['verification_level'], 'INDEPENDENT_TEST_REQUIRED')

    def test_web_shape_check_never_claims_behavioral_execution(self):
        skill = desk.add_web_skill({'name': 'Shape', 'script': 'await page.goto(url); // evidence',
                                   'template': 'evidence', 'verify': True})
        self.assertEqual(skill['status'], 'WEB_SKILL_STRUCTURE_CHECKED')
        self.assertEqual(skill['verification_level'], 'STRUCTURE_ONLY')
        self.assertEqual(skill['execution'], 'NOT_EXECUTED')
        self.assertEqual(desk.verify_web_skill(skill['skill_id'])['execution'], 'NOT_EXECUTED')


if __name__ == '__main__':
    unittest.main()
