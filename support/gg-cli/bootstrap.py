"""Explicit per-user terminal dependency installation; no desktop or node start."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

SOURCE = Path(__file__).resolve().parent


def default_home():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'GoldGoblins/gg-terminal'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'goldgoblins/gg-terminal'


def install(target, wallet_signing=False):
    if sys.version_info < (3, 10): raise ValueError('GG_CLI_PYTHON_310_REQUIRED')
    target = Path(target).expanduser().absolute()
    if target.is_symlink(): raise ValueError('GG_CLI_VENV_LINK_REFUSED')
    if target.exists() and not (target/'pyvenv.cfg').is_file():
        raise ValueError('GG_CLI_VENV_TARGET_NOT_EMPTY')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not target.exists(): venv.EnvBuilder(with_pip=True, clear=False, symlinks=os.name!='nt').create(target)
    executable = target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not executable.is_file(): raise ValueError('GG_CLI_VENV_INCOMPLETE')
    files = [SOURCE/'requirements.txt']
    if wallet_signing: files.append(SOURCE/'requirements-wallet.txt')
    command = [str(executable), '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
               '--require-virtualenv', '--index-url', 'https://pypi.org/simple', '--no-deps']
    for path in files: command.extend(['-r', str(path)])
    # Package/build output may contain local paths or proxy configuration. Keep
    # it out of chat/log output; the operator can run pip locally for diagnosis.
    result = subprocess.run(command, capture_output=True, timeout=600,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode: raise ValueError('GG_CLI_DEPENDENCY_INSTALL_FAILED')
    return executable


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install GG terminal dependencies in a private user venv. Explicit PyPI network access; never starts a node or installs Qt.')
    parser.add_argument('--venv', type=Path, default=default_home()/'venv')
    parser.add_argument('--wallet-signing', action='store_true', help='Also install solders 0.29.0 and its two pinned dependencies. Termux may require a Rust source build; that Android build is untested.')
    args = parser.parse_args(argv)
    try:
        install(args.venv, args.wallet_signing)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print('GG CLI installation failed. Check Python/venv, connectivity and platform build prerequisites in support/gg-cli/README.md.', file=sys.stderr)
        return 1
    print('GG terminal environment installed. The default venv is found by python gg-cli.py; a custom --venv must be run with its own Python.')
    return 0


if __name__ == '__main__': raise SystemExit(main())
