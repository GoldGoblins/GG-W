#!/usr/bin/env python3
"""Install the reviewed, pinned local REA/Ghidra pair without sudo or MCP edits."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path('/home/GG/.local/share/goldgoblins/gg-ai-desktop/research-tools')
URL = 'https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip'
CHECKSUM = 'ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db'
JAVA_RPM_VERSION = '25.0.4.1.1-1.1.fc44.x86_64'


def install_jdk(temp: Path):
    if (ROOT / 'jdk/bin/javac').is_file():
        return
    downloads = temp / 'java-rpms'
    downloads.mkdir()
    names = ['java-25-openjdk-headless-' + JAVA_RPM_VERSION, 'java-25-openjdk-devel-' + JAVA_RPM_VERSION]
    subprocess.run(['dnf', '--repo=fedora', '--repo=updates', 'download', '--destdir=' + str(downloads), *names],
                   check=True, timeout=300)
    extracted = temp / 'java-extracted'
    extracted.mkdir()
    for rpm in sorted(downloads.glob('*.rpm')):
        result = subprocess.run(['rpm', '--checksig', str(rpm)], capture_output=True, text=True, check=True)
        if 'signatures OK' not in result.stdout:
            raise SystemExit('RPM_SIGNATURE_NOT_VERIFIED')
        producer = subprocess.Popen(['rpm2cpio', str(rpm)], stdout=subprocess.PIPE)
        consumer = subprocess.run(['cpio', '-idm', '--quiet'], stdin=producer.stdout, cwd=extracted, capture_output=True)
        producer.stdout.close()
        if consumer.returncode or producer.wait():
            raise SystemExit('RPM_EXTRACTION_FAILED')
    staged = ROOT / '.jdk-staging'
    shutil.copytree(extracted / 'usr/lib/jvm/java-25-openjdk', staged, symlinks=True)
    try:
        for _ in range(4):
            changed = False
            for p in list(staged.rglob('*')):
                if not p.is_symlink() or not p.readlink().is_absolute():
                    continue
                link = p.readlink()
                source = extracted / str(link).lstrip('/')
                if not source.exists():
                    if str(link) not in {'/usr/share/javazi-1.8/tzdb.dat', '/etc/pki/java/cacerts',
                                         '/etc/crypto-policies/back-ends/java.config'}:
                        raise SystemExit('UNEXPECTED_EXTERNAL_JDK_LINK')
                    source = link
                p.unlink()
                if source.is_dir():
                    shutil.copytree(source, p, symlinks=True)
                else:
                    shutil.copy2(source, p)
                changed = True
            if not changed:
                break
        subprocess.run([str(staged / 'bin/javac'), '-version'], check=True, timeout=10)
        staged.rename(ROOT / 'jdk')
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def main():
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(ROOT).free < 3_000_000_000:
        raise SystemExit('INSUFFICIENT_FREE_SPACE')
    with tempfile.TemporaryDirectory(prefix='gg-research-install-') as raw:
        temp = Path(raw)
        archive = temp / 'ghidra.zip'
        if not (ROOT / 'ghidra/support/analyzeHeadless').is_file():
            print('Downloading official Ghidra 12.1.4 release', flush=True)
            subprocess.run(['curl', '-fsSL', '--retry', '2', '--connect-timeout', '20', '--max-time', '600',
                            '--output', str(archive), URL], check=True)
            with archive.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            if checksum != CHECKSUM:
                raise SystemExit('RELEASE_CHECKSUM_MISMATCH')
            with zipfile.ZipFile(archive) as z:
                members = z.infolist()
                if sum(m.file_size for m in members) > 2_500_000_000:
                    raise SystemExit('ARCHIVE_EXCEEDS_INSTALL_BUDGET')
                for m in members:
                    rel = Path(m.filename)
                    if rel.is_absolute() or '..' in rel.parts or ((m.external_attr >> 16) & 0o170000) == 0o120000:
                        raise SystemExit('UNSAFE_ARCHIVE_MEMBER')
                staged = ROOT / '.ghidra-staging'
                if staged.exists():
                    raise SystemExit('EXISTING_INSTALL_STAGING')
                staged.mkdir()
                try:
                    z.extractall(staged)
                    for m in members:
                        target = staged / m.filename
                        if target.is_file() and (m.external_attr >> 16) & 0o111:
                            target.chmod(0o755)
                    expanded = staged / 'ghidra_12.1.4_PUBLIC'
                    expanded.rename(ROOT / 'ghidra')
                finally:
                    shutil.rmtree(staged)
        print('Installing pinned REA 6.0.0 with production dependencies', flush=True)
        subprocess.run(['npm', 'install', '--prefix', str(ROOT / 'rea'), '--cache', str(temp / 'npm-cache'),
                        '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund', '--save-exact',
                        'rea-agents@6.0.0'], check=True, timeout=300)
        print('Checking the dedicated, signed Fedora JDK', flush=True)
        install_jdk(temp)
    manifest = {'schema': 'gg.research-tools-install.v1', 'ghidra_version': '12.1.4',
                'rea_version': '6.0.0', 'ghidra_source': URL, 'ghidra_release_checksum_verified': True,
                'mcp_registration_changed': False,
                'jdk_version': '25.0.4.1', 'jdk_rpm_signatures_verified': True,
                'jdk_source': 'Fedora 44 signed headless and devel RPMs',
                'installed_bytes': sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file() and not p.is_symlink())}
    (ROOT / 'installation.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == '__main__':
    main()
