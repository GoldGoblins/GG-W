"""Reviewed, per-user Windows research dependencies; no elevation or autostart."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
import re

from backend.platform_process import background_options

GHIDRA_URL = 'https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip'
GHIDRA_SHA256 = 'ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db'
JDK_URL = 'https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_windows_hotspot_25.0.4.1_1.zip'
JDK_SHA256 = '00c847d804f4a78e9f04f2683faf14fed898535b177b7fc704486cb0284e9283'


def _download(url: str, destination: Path, checksum: str):
    request = urllib.request.Request(url, headers={'User-Agent': 'GG-Research-Windows-Setup'})
    digest = hashlib.sha256()
    total = 0
    began = time.monotonic()
    last = began
    with urllib.request.urlopen(request, timeout=30) as response, destination.open('xb') as stream:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 800 * 1024 * 1024 or time.monotonic() - began > 600:
                raise ValueError('RESEARCH_DOWNLOAD_LIMIT')
            digest.update(chunk)
            stream.write(chunk)
            if time.monotonic() - last > 20:
                print(f'Downloaded {total // (1024 * 1024)} MiB', flush=True)
                last = time.monotonic()
    if digest.hexdigest() != checksum:
        raise ValueError('RESEARCH_DOWNLOAD_CHECKSUM_MISMATCH')


def _extract(archive: Path, staging: Path, destination: Path):
    assert staging.resolve().is_relative_to(archive.parent.resolve())
    assert destination.parent.is_dir() and not destination.exists()
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        if len(members) > 40000 or sum(row.file_size for row in members) > 2500 * 1024 * 1024:
            raise ValueError('RESEARCH_ARCHIVE_LIMIT')
        for row in members:
            relative = PurePosixPath(row.filename)
            if (relative.is_absolute() or '..' in relative.parts or '\\' in row.filename
                    or ':' in row.filename or (row.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('RESEARCH_UNSAFE_ARCHIVE_MEMBER')
        package.extractall(staging)
        for row in members:
            target = staging / row.filename
            timestamp = time.mktime((*row.date_time, 0, 0, -1))
            os.utime(target, (timestamp, timestamp))
    roots = list(staging.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('RESEARCH_ARCHIVE_LAYOUT')
    assert roots[0].resolve().is_relative_to(staging.resolve())
    roots[0].rename(destination)


def _repair_ghidra_times(root: Path):
    """Migrate an older GG install without allowing tools to modify themselves."""
    print('Restoring verified Ghidra archive timestamps', flush=True)
    with tempfile.TemporaryDirectory(prefix='gg-re-', dir=root.parent) as raw:
        archive = Path(raw) / 'ghidra.zip'
        _download(GHIDRA_URL, archive, GHIDRA_SHA256)
        with zipfile.ZipFile(archive) as package:
            entries = []
            for row in package.infolist():
                relative = PurePosixPath(row.filename)
                if relative.parts[0] != 'ghidra_12.1.4_PUBLIC' or '..' in relative.parts or '\\' in row.filename or ':' in row.filename:
                    raise ValueError('RESEARCH_UNSAFE_ARCHIVE_MEMBER')
                path = root / Path(*relative.parts[1:])
                if row.is_dir():
                    continue
                if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.is_symlink():
                    raise ValueError('GHIDRA_EXISTING_FILE_MISSING_OR_LINKED')
                with package.open(row) as stream, path.open('rb') as installed:
                    if hashlib.file_digest(stream, 'sha256').digest() != hashlib.file_digest(installed, 'sha256').digest():
                        raise ValueError('GHIDRA_EXISTING_FILE_CHANGED')
                entries.append((path, row.date_time))
            for path, date_time in entries:
                timestamp = time.mktime((*date_time, 0, 0, -1))
                os.utime(path, (timestamp, timestamp))


def install(root: Path):
    if os.name != 'nt':
        raise RuntimeError('WINDOWS_SETUP_REQUIRED')
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        prior = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        prior = {}
    verified = {
        'ghidra': bool(prior.get('ghidra_release_checksum_verified') and prior.get('ghidra_source') == GHIDRA_URL
                       and prior.get('ghidra_version') == '12.1.4'),
        'jdk': bool(prior.get('jdk_checksum_verified') and prior.get('jdk_source') == JDK_URL
                    and prior.get('jdk_version') == '25.0.4.1'),
    }
    ghidra_times = bool(prior.get('ghidra_archive_timestamps_preserved'))
    if shutil.disk_usage(root).free < 3_000_000_000:
        raise ValueError('INSUFFICIENT_FREE_SPACE')
    node = shutil.which('node')
    if not node:
        raise ValueError('NODE_NOT_INSTALLED')
    npm = Path(node).parent / 'node_modules/npm/bin/npm-cli.js'
    if not npm.is_file():
        raise ValueError('NPM_NOT_INSTALLED')
    # Keep unpacked debugger package paths below Windows' legacy path limit.
    with tempfile.TemporaryDirectory(prefix='gg-re-', dir=root.parent) as raw:
        temporary = Path(raw)
        packages = [
            ('Ghidra 12.1.4', GHIDRA_URL, GHIDRA_SHA256, 'ghidra', 'support/analyzeHeadless.bat'),
            ('Temurin JDK 25.0.4.1', JDK_URL, JDK_SHA256, 'jdk', 'bin/javac.exe'),
        ]
        for label, url, checksum, name, executable in packages:
            if (root / name / executable).is_file():
                continue
            if (root / name).exists():
                raise ValueError('EXISTING_INCOMPLETE_RESEARCH_INSTALL')
            print('Installing ' + label + ' from its official release', flush=True)
            archive = temporary / (name + '.zip')
            _download(url, archive, checksum)
            _extract(archive, temporary / (name + '-expanded'), root / name)
            verified[name] = True
            if name == 'ghidra':
                ghidra_times = True
        properties = (root / 'ghidra/Ghidra/application.properties').read_text(encoding='utf-8')
        if not re.search(r'^application.version=12\.1\.4\s*$', properties, re.MULTILINE):
            raise ValueError('EXISTING_GHIDRA_VERSION_MISMATCH')
        config = temporary / 'npm-user-config'
        config.write_text('registry=https://registry.npmjs.org/\n', encoding='utf-8')
        global_config = temporary / 'npm-global-config'
        global_config.write_text('', encoding='utf-8')
        env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'COMSPEC', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        env.update(NPM_CONFIG_USERCONFIG=str(config), NPM_CONFIG_GLOBALCONFIG=str(global_config),
                   NPM_CONFIG_CACHE=str(temporary / 'npm-cache'))
        package = root / 'rea/node_modules/rea-agents/package.json'
        if not package.is_file() or json.loads(package.read_text(encoding='utf-8')).get('version') != '6.0.0':
            print('Installing REA 6.0.0 and production dependencies', flush=True)
            result = subprocess.run([node, str(npm), 'install', '--prefix', str(root / 'rea'),
                '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund', '--save-exact', 'rea-agents@6.0.0'],
                env=env, capture_output=True, timeout=300, **background_options())
            if result.returncode:
                raise RuntimeError('RESEARCH_NPM_INSTALL_FAILED')
        runtime = root / 'runtime'
        runtime.mkdir(exist_ok=True)
        shutil.copyfile(node, runtime / 'node.exe')
        critical_names = ['ghidra/Ghidra/application.properties', 'ghidra/support/analyzeHeadless.bat',
            'ghidra/Ghidra/Framework/Utility/lib/Utility.jar', 'jdk/bin/java.exe', 'jdk/bin/javac.exe',
            'jdk/conf/security/java.security', 'rea/node_modules/rea-agents/package.json',
            'rea/node_modules/rea-agents/scripts/rea.mjs']
        critical = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in critical_names}
        for name, digest in prior.get('critical_files', {}).items():
            if name in critical and critical[name] != digest:
                raise ValueError('EXISTING_RESEARCH_TOOL_CHANGED')
        if verified['ghidra'] and not ghidra_times:
            _repair_ghidra_times(root / 'ghidra')
            ghidra_times = True
        java = subprocess.run([str(root / 'jdk/bin/java.exe'), '-version'], capture_output=True,
                              timeout=20, **background_options())
        if java.returncode:
            raise RuntimeError('RESEARCH_JAVA_VERIFICATION_FAILED')
        if not re.search(rb'\b25\.0\.4\.1\b', java.stdout + java.stderr):
            raise ValueError('EXISTING_JDK_VERSION_MISMATCH')
    record = {'schema': 'gg.research-tools-install.v1', 'platform': 'windows',
              'ghidra_version': '12.1.4', 'ghidra_source': GHIDRA_URL,
              'ghidra_release_checksum_verified': verified['ghidra'], 'rea_version': '6.0.0',
              'jdk_version': '25.0.4.1', 'jdk_source': JDK_URL, 'jdk_checksum_verified': verified['jdk'],
              'critical_files': critical, 'existing_versions_checked': True,
              'ghidra_archive_timestamps_preserved': ghidra_times,
              'verification_scope': 'Archive checksum evidence is retained from installation-time downloads; existing critical files and pinned versions are checked on rerun.',
              'mcp_registration_changed': False}
    (root / 'installation.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print('WINDOWS_RESEARCH_TOOLS_INSTALLED=PASS', flush=True)
