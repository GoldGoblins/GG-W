"""Pinned archive admission, retry and configuration isolation use owned files."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import site_runtime_setup as setup


@unittest.skipUnless(os.name == 'nt', 'Windows managed runtime setup')
class SiteRuntimeSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-site-tool-proof-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'tools'
        (self.root / 'archives').mkdir(parents=True)
        packages = {}
        for component, required in (('php', ['php.exe']), ('mariadb', ['bin/mariadbd.exe', 'bin/mariadb.exe', 'bin/mariadb-install-db.exe'])):
            version = '8.5.12' if component == 'php' else '12.3.3'
            archive = self.root / 'archives' / (component + '-' + version + '.zip')
            with zipfile.ZipFile(archive, 'w') as bundle:
                for name in required:
                    bundle.writestr(name, 'Owned inert fixture ' + name)
            packages[component] = {'version': version, 'url': 'https://fixture.invalid/' + component + '.zip',
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'prefix': '', 'executables': required}
        self.enterContext(patch.object(setup, 'PACKAGES', packages))
        self.enterContext(patch.dict(os.environ, GG_SITE_TOOLS_ROOT=str(self.root)))
        setup._EXPECTED.clear(); setup._VERIFIED.clear()
        self.addCleanup(setup._EXPECTED.clear); self.addCleanup(setup._VERIFIED.clear)
        def probe(command, **_):
            if '-r' in command:
                return 0, json.dumps(['8.5.12', setup.PHP_EXTENSIONS, '125', False]).encode(), b'', 'NONE'
            return 0, b'MariaDB 12.3.3', b'', 'NONE'
        self.probes = self.enterContext(patch.object(setup, 'run_bounded', side_effect=probe))

    def test_interrupted_publication_without_receipt_can_resume_only_after_archive_checks(self):
        with zipfile.ZipFile(setup._archive(self.root, 'php')) as bundle:
            bundle.extractall(self.root / 'php')
        (self.root / 'php/gg-php.ini').write_text(setup.managed_ini(self.root), encoding='utf-8')
        (self.root / 'php/empty-ini-scan').mkdir()
        with self.assertRaisesRegex(ValueError, 'RECEIPT_REQUIRED'):
            setup.runtime_executable('php')
        self.assertEqual(setup.install()['status'], 'PASS')
        self.assertEqual(Path(setup.runtime_executable('php')), self.root / 'php/php.exe')
        self.assertEqual(setup.install()['status'], 'PASS')

    def test_changed_installed_file_is_rejected_even_if_modification_time_is_restored(self):
        setup.install()
        executable = Path(setup.runtime_executable('php'))
        before = executable.stat()
        executable.write_bytes(b'x' * before.st_size)
        os.utime(executable, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'INSTALLED_FILE_CHANGED'):
            setup.runtime_executable('php')

    def test_managed_ini_and_scan_directory_cannot_add_unverified_code(self):
        setup.install()
        ini = self.root / 'php/gg-php.ini'
        original = ini.read_text(encoding='utf-8')
        ini.write_text(original + '\nauto_prepend_file=untrusted.php\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CONFIGURATION_CHANGED'):
            setup.php_arguments()
        ini.write_text(original, encoding='utf-8')
        (self.root / 'php/empty-ini-scan/untrusted.ini').write_text('owned inert fixture', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CONFIGURATION_CHANGED'):
            setup.php_arguments()

    def test_receipt_cannot_replace_pinned_archive_authentication(self):
        setup.install()
        archive = setup._archive(self.root, 'php')
        archive.write_bytes(b'not the official pinned archive')
        with self.assertRaisesRegex(ValueError, 'ARCHIVE_CHECKSUM_FAILED'):
            setup.runtime_executable('php')

    def test_runtime_environment_omits_inherited_secret_and_ini_overrides(self):
        setup.install()
        with patch.dict(os.environ, {'PHPRC': 'untrusted.ini', 'PHP_INI_SCAN_DIR': 'untrusted-dir', 'GG_SYNTHETIC_SECRET': 'inert-test-value'}):
            environment = setup.php_environment()
        self.assertNotIn('PHPRC', environment)
        self.assertNotIn('GG_SYNTHETIC_SECRET', environment)
        self.assertEqual(environment['PHP_INI_SCAN_DIR'], str(self.root / 'php/empty-ini-scan'))
        self.assertEqual(setup.php_arguments()[1:3], ['-c', str(self.root / 'php/gg-php.ini')])

    def test_unsafe_archive_layout_is_rejected_before_publication(self):
        archive = setup._archive(self.root, 'php')
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('../outside.txt', 'owned fixture')
        setup.PACKAGES['php']['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'UNSAFE_ARCHIVE'):
            setup.install()
        self.assertFalse((self.root.parent / 'outside.txt').exists())
        self.assertFalse((self.root / 'php').exists())
        self.probes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
