"""One explicit per-user installer for GG CLI's three supported recipes.

--check only reads the public install recipe. Actual installation delegates to
the pinned bootstrap; --launch uses that bootstrap's exact Python executable.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def project_root():
    here = Path(__file__).resolve().parent
    return here if (here/'gg-cli.py').is_file() else here.parents[1]


def host_platform(environ=None):
    environ = os.environ if environ is None else environ
    if sys.platform == 'win32':
        return 'windows'
    if sys.platform == 'linux':
        prefix = str(environ.get('PREFIX', '')).replace('\\', '/')
        return 'termux' if environ.get('TERMUX_VERSION') or '/com.termux/' in prefix else 'linux'
    return 'unsupported'


def bootstrap_module(root):
    path = root/'support/gg-cli/bootstrap.py'
    spec = importlib.util.spec_from_file_location('gg_cli_explicit_bootstrap', path)
    if spec is None or spec.loader is None:
        raise ValueError('GG_CLI_BOOTSTRAP_MISSING')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_plan(root, platform, wallet_signing=False):
    files = [root/'support/gg-cli/requirements.txt']
    if wallet_signing:
        files.append(root/'support/gg-cli/requirements-wallet.txt')
    pins = []
    for path in files:
        pins.extend(line.strip() for line in path.read_text(encoding='utf-8').splitlines()
                    if line.strip() and not line.lstrip().startswith('#'))
    return {'schema': 'gg.cli.install-plan.v1', 'platform': platform,
            'host_platform': host_platform(), 'host_supported': platform == host_platform(),
            'python': '>=3.10', 'environment': 'PRIVATE_PER_USER_VENV',
            'dependencies': pins, 'wallet_signing': wallet_signing,
            'network_requested': False, 'node_start': False, 'system_packages_installed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install the pinned headless GG CLI environment for Windows, Linux or Termux. No node starts automatically.')
    parser.add_argument('--platform', choices=('windows', 'linux', 'termux'), default=None)
    parser.add_argument('--check', action='store_true', help='Show the public install plan without installation, network, keys or application startup.')
    parser.add_argument('--wallet-signing', action='store_true', help='Also install the separately pinned optional Solana signing SDK; physical Termux support is unverified.')
    parser.add_argument('--launch', action='store_true', help='After installation, run the CLI with the exact Python interpreter returned by bootstrap.')
    args = parser.parse_args(argv)
    if args.check and args.launch:
        parser.error('--check and --launch cannot be combined')
    if sys.version_info < (3, 10):
        print('GG CLI requires Python 3.10 or newer.', file=sys.stderr)
        return 2
    platform = args.platform or host_platform()
    if platform == 'unsupported':
        print('Use the Windows, Linux or Termux installation recipe.', file=sys.stderr)
        return 2
    root = project_root()
    try:
        if args.check:
            print(json.dumps(install_plan(root, platform, args.wallet_signing), indent=2))
            return 0
        if platform != host_platform():
            print('The selected installation recipe does not match this device. Use --check to inspect a recipe.', file=sys.stderr)
            return 2
        bootstrap = bootstrap_module(root)
        executable = bootstrap.install(bootstrap.default_home()/'venv', args.wallet_signing)
        if args.launch:
            return subprocess.call([str(executable), '-B', str(root/'gg-cli.py')])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print('GG CLI installation failed. Check Python/venv, connectivity and the platform build prerequisites in README.md.', file=sys.stderr)
        return 1
    print('GG CLI environment installed. Run python gg-cli.py from this repository, or rerun this installer with --launch to use the installed interpreter explicitly.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
