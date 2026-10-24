"""Archive containment and truthful provenance for offline Windows setup reruns."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import windows_research_setup as setup


class ResearchArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-research-archive-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / 'release.zip'
        self.staging = self.root / 'expanded'
        self.destination = self.root / 'installed'

    def assert_unsafe(self, entry, content=b'untrusted archive fixture'):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            # Validation must finish before even the first safe file is written.
            archive.writestr('package/safe.txt', b'safe fixture')
            archive.writestr(entry, content)
        with self.assertRaisesRegex(ValueError, 'RESEARCH_UNSAFE_ARCHIVE_MEMBER'):
            setup._extract(self.archive, self.staging, self.destination)
        self.assertFalse(self.staging.exists())
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.root / 'escaped.txt').exists())

    def test_parent_traversal_rejected_before_any_extraction(self):
        self.assert_unsafe('package/../../escaped.txt')

    def test_absolute_posix_path_rejected_before_any_extraction(self):
        self.assert_unsafe('/escaped.txt')

    def test_windows_drive_and_alternate_data_stream_names_rejected(self):
        for name in ('C:/escaped.txt', 'C:escaped.txt', 'package/file.txt:stream'):
            with self.subTest(name=name):
                self.assert_unsafe(name)

    def test_backslash_paths_rejected_before_any_extraction(self):
        for name in ('package\\..\\escaped.txt', '\\\\host\\share\\escaped.txt'):
            with self.subTest(name=name):
                self.assert_unsafe(name)

    def test_unix_symlink_member_rejected_before_any_extraction(self):
        link = zipfile.ZipInfo('package/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assert_unsafe(link, b'../../escaped.txt')

    def test_valid_single_root_archive_preserves_content_and_flattens_release_root(self):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('release/support/analyzeHeadless.bat', b'launcher fixture\r\n')
            archive.writestr('release/lib/utility.jar', b'\x00binary fixture\xff')
        setup._extract(self.archive, self.staging, self.destination)
        self.assertEqual((self.destination / 'support/analyzeHeadless.bat').read_bytes(), b'launcher fixture\r\n')
        self.assertEqual((self.destination / 'lib/utility.jar').read_bytes(), b'\x00binary fixture\xff')
        self.assertFalse((self.destination / 'release').exists())
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_extraction_preserves_source_and_compiled_language_archive_timestamps(self):
        source = zipfile.ZipInfo('release/languages/fixture.slaspec', (2001, 2, 3, 4, 5, 6))
        compiled = zipfile.ZipInfo('release/languages/fixture.sla', (2001, 2, 4, 4, 5, 6))
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr(compiled, b'compiled language fixture')
            archive.writestr(source, b'source language fixture')
        setup._extract(self.archive, self.staging, self.destination)
        mtimes = {}
        for entry in (source, compiled):
            path = self.destination / Path(*Path(entry.filename).parts[1:])
            expected = time.mktime((*entry.date_time, 0, 0, -1))
            mtimes[path.suffix] = path.stat().st_mtime
            self.assertAlmostEqual(mtimes[path.suffix], expected, delta=1)
        self.assertLess(mtimes['.slaspec'], mtimes['.sla'])

    def test_multiple_release_roots_are_rejected_without_installing(self):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('first/file.txt', b'first')
            archive.writestr('second/file.txt', b'second')
        with self.assertRaisesRegex(ValueError, 'RESEARCH_ARCHIVE_LAYOUT'):
            setup._extract(self.archive, self.staging, self.destination)
        self.assertFalse(self.destination.exists())


@unittest.skipUnless(os.name == 'nt', 'Windows setup rerun behavior')
class ExistingResearchInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-research-install-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tools = self.root / 'tools'
        self.node = self.root / 'node-runtime/node.exe'
        self.node.parent.mkdir()
        self.node.write_bytes(b'synthetic Node fixture; never executed')
        npm = self.node.parent / 'node_modules/npm/bin/npm-cli.js'
        npm.parent.mkdir(parents=True)
        npm.write_text('// synthetic npm fixture; never executed', encoding='utf-8')
        fixtures = {
            'ghidra/Ghidra/application.properties': b'application.version=12.1.4\n',
            'ghidra/support/analyzeHeadless.bat': b'launcher fixture',
            'ghidra/Ghidra/Framework/Utility/lib/Utility.jar': b'utility fixture',
            'jdk/bin/java.exe': b'java fixture',
            'jdk/bin/javac.exe': b'javac fixture',
            'jdk/conf/security/java.security': b'security fixture',
            'rea/node_modules/rea-agents/package.json': b'{"version":"6.0.0"}',
            'rea/node_modules/rea-agents/scripts/rea.mjs': b'// REA fixture',
        }
        for name, data in fixtures.items():
            destination = self.tools / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        self.hashes = {name: hashlib.sha256(data).hexdigest() for name, data in fixtures.items()}

    def install_offline(self, *, version=b'openjdk version "25.0.4.1"\n'):
        def trusted_version_probe(argv, **kwargs):
            self.assertEqual(argv, [str(self.tools / 'jdk/bin/java.exe'), '-version'])
            return subprocess.CompletedProcess(argv, 0, stdout=b'', stderr=version)

        with ExitStack() as stack:
            stack.enter_context(patch.object(setup.shutil, 'which', return_value=str(self.node)))
            stack.enter_context(patch.object(setup.shutil, 'disk_usage', return_value=SimpleNamespace(free=5_000_000_000)))
            download = stack.enter_context(patch.object(setup, '_download', side_effect=AssertionError('unexpected download')))
            extract = stack.enter_context(patch.object(setup, '_extract', side_effect=AssertionError('unexpected extraction')))
            stack.enter_context(patch.object(setup.urllib.request, 'urlopen', side_effect=AssertionError('unexpected network')))
            self.last_timestamp_repair = stack.enter_context(patch.object(setup, '_repair_ghidra_times'))
            probe = stack.enter_context(patch.object(setup.subprocess, 'run', side_effect=trusted_version_probe))
            self.last_process_probe = probe
            stack.enter_context(redirect_stdout(io.StringIO()))
            setup.install(self.tools)
            download.assert_not_called()
            extract.assert_not_called()
            probe.assert_called_once()
        return json.loads((self.tools / 'installation.json').read_text(encoding='utf-8'))

    def test_untracked_existing_tools_record_versions_and_hashes_without_archive_verification(self):
        self.assertFalse((self.tools / 'installation.json').exists())
        record = self.install_offline()
        self.assertFalse(record['ghidra_release_checksum_verified'])
        self.assertFalse(record['jdk_checksum_verified'])
        self.assertTrue(record['existing_versions_checked'])
        self.assertEqual(record['ghidra_version'], '12.1.4')
        self.assertEqual(record['jdk_version'], '25.0.4.1')
        self.assertEqual(record['critical_files'], self.hashes)
        self.last_timestamp_repair.assert_not_called()

    def test_matching_prior_download_proof_survives_an_offline_rerun(self):
        prior = {
            'ghidra_release_checksum_verified': True, 'ghidra_source': setup.GHIDRA_URL,
            'ghidra_version': '12.1.4', 'jdk_checksum_verified': True,
            'jdk_source': setup.JDK_URL, 'jdk_version': '25.0.4.1', 'critical_files': self.hashes,
            'ghidra_archive_timestamps_preserved': True,
        }
        (self.tools / 'installation.json').write_text(json.dumps(prior), encoding='utf-8')
        record = self.install_offline()
        self.assertTrue(record['ghidra_release_checksum_verified'])
        self.assertTrue(record['jdk_checksum_verified'])
        self.last_timestamp_repair.assert_not_called()

    def test_timestamp_repair_runs_only_once_for_trusted_older_archive_manifest(self):
        prior = {
            'ghidra_release_checksum_verified': True, 'ghidra_source': setup.GHIDRA_URL,
            'ghidra_version': '12.1.4', 'critical_files': self.hashes,
            'ghidra_archive_timestamps_preserved': False,
        }
        (self.tools / 'installation.json').write_text(json.dumps(prior), encoding='utf-8')
        record = self.install_offline()
        self.last_timestamp_repair.assert_called_once_with(self.tools / 'ghidra')
        self.assertTrue(record['ghidra_archive_timestamps_preserved'])
        self.assertTrue(record['ghidra_release_checksum_verified'])
        second = self.install_offline()
        self.last_timestamp_repair.assert_not_called()
        self.assertTrue(second['ghidra_archive_timestamps_preserved'])

    def test_proof_for_different_sources_is_not_reused(self):
        prior = {
            'ghidra_release_checksum_verified': True, 'ghidra_source': 'https://invalid.example/other.zip',
            'ghidra_version': '12.1.4', 'jdk_checksum_verified': True,
            'jdk_source': 'https://invalid.example/other.zip', 'jdk_version': '25.0.4.1',
        }
        (self.tools / 'installation.json').write_text(json.dumps(prior), encoding='utf-8')
        record = self.install_offline()
        self.assertFalse(record['ghidra_release_checksum_verified'])
        self.assertFalse(record['jdk_checksum_verified'])
        self.last_timestamp_repair.assert_not_called()

    def test_existing_critical_file_change_rejects_rerun_without_rewriting_proof(self):
        prior = {'critical_files': self.hashes}
        original = json.dumps(prior)
        (self.tools / 'installation.json').write_text(original, encoding='utf-8')
        (self.tools / 'jdk/conf/security/java.security').write_bytes(b'changed security fixture')
        with self.assertRaisesRegex(ValueError, 'EXISTING_RESEARCH_TOOL_CHANGED'):
            self.install_offline()
        self.assertEqual((self.tools / 'installation.json').read_text(encoding='utf-8'), original)

    def test_modified_recorded_java_is_rejected_before_any_process_invocation(self):
        (self.tools / 'installation.json').write_text(json.dumps({'critical_files': self.hashes}), encoding='utf-8')
        (self.tools / 'jdk/bin/java.exe').write_bytes(b'modified executable fixture; must never run')
        with self.assertRaisesRegex(ValueError, 'EXISTING_RESEARCH_TOOL_CHANGED'):
            self.install_offline()
        self.last_process_probe.assert_not_called()

    def test_existing_wrong_jdk_version_is_not_recorded_as_pinned(self):
        with self.assertRaisesRegex(ValueError, 'EXISTING_JDK_VERSION_MISMATCH'):
            self.install_offline(version=b'openjdk version "24.0.2"\n')
        self.assertFalse((self.tools / 'installation.json').exists())


if __name__ == '__main__':
    unittest.main()
