#!/usr/bin/env python3
"""Launch GG's headless terminal without importing the desktop application."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def terminal_home():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'GoldGoblins/gg-terminal'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'goldgoblins/gg-terminal'


def main():
    if sys.version_info < (3, 10):
        print('GG CLI requires Python 3.10 or newer.', file=sys.stderr); return 2
    home = terminal_home()
    # A terminal started inside the desktop must still use its own state.
    os.environ['GG_DESKTOP_STATE_ROOT'] = os.environ.get('GG_TERMINAL_STATE_ROOT', str(home/'state'))
    os.environ['GG_DESKTOP_DATA_ROOT'] = os.environ.get('GG_TERMINAL_DATA_ROOT', str(home/'data'))
    required = ('prompt_toolkit', 'wcwidth', 'psutil', 'Crypto', 'bech32', 'mnemonic')
    if any(importlib.util.find_spec(name) is None for name in required):
        candidates = ([ROOT/'.venv-windows/Scripts/python.exe'] if os.name == 'nt' else [])
        candidates.append(home/'venv'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
        for candidate in candidates:
            if candidate.is_file() and candidate.resolve() != Path(sys.executable).resolve():
                probe = 'import importlib.util,sys;sys.exit(any(importlib.util.find_spec(n) is None for n in '+repr(required)+'))'
                try:
                    checked = subprocess.run([str(candidate), '-B', '-c', probe], capture_output=True, timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if checked.returncode == 0:
                    return subprocess.call([str(candidate), '-B', str(Path(__file__).resolve()), *sys.argv[1:]])
        print('Install the small terminal environment first: python support/gg-cli/bootstrap.py', file=sys.stderr)
        return 2
    if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
    from backend.terminal_cli import main as terminal_main
    return terminal_main()


if __name__ == '__main__': raise SystemExit(main())
