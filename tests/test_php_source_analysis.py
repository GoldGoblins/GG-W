"""PHP input stays data; failures and cancellation cannot contaminate next jobs."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import php_source_analysis as php, research_jobs as jobs, research_desk as desk, research_lab as lab


class PHPSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-php-source-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(jobs, 'ROOT', self.root / 'jobs'))
        self.enterContext(patch.object(desk, 'ROOT', self.root / 'desk'))
        self.enterContext(patch.object(lab, 'TOOLS_ROOT', self.root / 'tools'))

    def source(self, content, name='input.php'):
        path = self.root / name
        path.write_text(content, encoding='utf-8')
        return path

    def wait(self, state):
        deadline = time.monotonic() + 15
        while state.get('status') in jobs.BUSY and time.monotonic() < deadline:
            time.sleep(.03)
            state = jobs.status(state['job_id'])
        if state.get('status') in jobs.BUSY:
            jobs.cancel(state['job_id'])
            self.fail('PHP worker did not finish within bounded deadline')
        return state

    def test_inventory_ignores_markup_comments_strings_and_keeps_real_locations(self):
        path = self.source('''<html>fake_call()</html><?php
// function imaginary() { fake_call(); }
$text = "unserialize($unsafe)";
function real($value) {
    static $cache;
    return unserialize($value);
}
real($_POST['value']);
''')
        report = php.analyze(path)
        self.assertEqual([row['name'] for row in report['functions']], ['real'])
        self.assertEqual([row['name'] for row in report['calls']], ['unserialize', 'real'])
        self.assertEqual(report['functions'][0]['line'], 4)
        self.assertTrue(any(row['name'] == 'static' for row in report['review_points']))
        self.assertTrue(any(row['name'] == '$_POST' for row in report['review_points']))
        self.assertFalse(report['executed'])

    def test_initial_php_inspection_does_not_display_define_secret_values(self):
        import json
        path = self.source("<?php define('DB_PASSWORD', 'synthetic-hidden;tail');\nfunction visible() {}")
        report = lab.inspect_file(str(path))
        self.assertEqual(report['format'], 'SOURCE')
        self.assertNotIn('synthetic-hidden', json.dumps(report))
        self.assertNotIn(';tail', json.dumps(report))

    def test_heredoc_and_nowdoc_content_is_not_scanned_as_php_calls(self):
        path = self.source("<?php\n$value = <<<'TXT'\nfunction pretend() { unserialize('x'); }\nTXT;\nfunction actual() { return 1; }\nactual();")
        result = php.analyze(path)
        self.assertEqual([row['name'] for row in result['functions']], ['actual'])
        self.assertEqual([row['name'] for row in result['calls']], ['actual'])

    def test_closing_tag_ends_line_comment_and_markup_is_not_evidence(self):
        for comment in ('//', '#'):
            with self.subTest(comment=comment):
                path = self.source('<?php ' + comment + ' done ?>\n<div>fake_call()</div><?php function real() {} real();')
                result = php.analyze(path)
                self.assertEqual([row['name'] for row in result['functions']], ['real'])
                self.assertEqual([row['name'] for row in result['calls']], ['real'])

    def test_query_filters_before_clipping_the_inventory(self):
        path = self.source('<?php ' + ' '.join('function f'+str(i)+'() {}' for i in range(140)) + ' f139();')
        self.assertEqual(len(php.analyze(path)['functions']), php.MAX_ROWS)
        self.assertEqual(php.analyze(path, 'function', 'f139')['matches'][0]['name'], 'f139')
        self.assertEqual(php.analyze(path, 'xrefs', 'f139')['matches'][0]['name'], 'f139')

    def test_unbounded_structure_and_unterminated_strings_are_rejected(self):
        for value, error in [('<?php ' + '(' * (php.MAX_DEPTH + 1), 'PHP_NESTING_LIMIT'),
                             ('<?php "unfinished', 'PHP_UNTERMINATED_STRING')]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                php.analyze(self.source(value))

    def test_string_and_heredoc_tokens_share_the_same_admission_budget(self):
        for token in ("'' ", "<<<'TEXT'\nx\nTEXT;\n"):
            with self.subTest(token=token), patch.object(php, 'MAX_TOKENS', 10):
                with self.assertRaisesRegex(ValueError, 'PHP_TOKEN_LIMIT'):
                    php.analyze(self.source('<?php ' + token * 11))

    def test_failure_then_next_real_background_job_is_clean(self):
        failed = self.wait(jobs.start(str(self.source('<?php "unfinished'))))
        self.assertEqual(failed['status'], 'ERROR', failed)
        self.assertFalse((jobs._dir(failed['job_id']) / 'scratch').exists())
        marker = self.root / 'executed'
        path = self.source("<?php file_put_contents('" + marker.as_posix() + "','bad'); function good() { return 7; }", 'good.php')
        success = self.wait(jobs.start(str(path)))
        self.assertEqual(success['status'], 'COMPLETE', success)
        self.assertEqual(success['report']['engine'], 'PHP source review')
        self.assertEqual(success['report']['content']['functions'][0]['name'], 'good')
        self.assertFalse(marker.exists())
        self.assertFalse((jobs._dir(success['job_id']) / 'scratch').exists())

    def test_cancellation_then_next_analysis_is_clean(self):
        with self.assertRaisesRegex(ValueError, 'CANCELLED'):
            php.analyze(self.source('<?php function good() {}'), cancelled=lambda: True)
        self.assertEqual(php.analyze(self.root / 'input.php')['functions'][0]['name'], 'good')

    def test_cancelled_real_worker_cannot_publish_or_affect_next_job(self):
        import subprocess
        original = subprocess.Popen
        def launch_after_cancel(argv, **options):
            (jobs._dir(argv[-1]) / 'cancel').touch()
            return original(argv, **options)
        path = self.source('<?php function after_cancel() {}')
        with patch.object(jobs.subprocess, 'Popen', side_effect=launch_after_cancel):
            cancelled = self.wait(jobs.start(str(path)))
        self.assertEqual(cancelled['status'], 'CANCELLED', cancelled)
        self.assertNotIn('report', cancelled)
        recovered = self.wait(jobs.start(str(path)))
        self.assertEqual(recovered['status'], 'COMPLETE', recovered)
        self.assertEqual(recovered['report']['content']['functions'][0]['name'], 'after_cancel')

    def test_php_project_snapshot_omits_configuration_and_vendor(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'index.php').write_text('<?php function page() {}', encoding='utf-8')
        (project / 'wp-config.php').write_text('<?php $secret="not-retained";', encoding='utf-8')
        (project / 'vendor').mkdir()
        (project / 'vendor/private.php').write_text('<?php function hidden() {}', encoding='utf-8')
        result = self.wait(jobs.start(str(project), 'php_analyze'))
        self.assertEqual(result['status'], 'COMPLETE', result)
        self.assertEqual([row['path'] for row in result['report']['content']['files']], ['index.php'])

    def test_queries_report_lexical_references_without_runtime_claims(self):
        path = self.source('<?php function render() {} render(); $object->render();')
        report = php.analyze(path, 'xrefs', 'render')
        self.assertEqual(len(report['matches']), 2)
        self.assertEqual(report['matches'][1]['resolution'], 'DYNAMIC_OR_MEMBER')
        self.assertEqual(php.analyze(path, 'function', 'render')['matches'][0]['name'], 'render')
        self.assertEqual(jobs.start(str(path), 'decompile', 'render')['reason'], 'PHP_SOURCE_IS_NOT_DECOMPILED')


if __name__ == '__main__':
    unittest.main()
