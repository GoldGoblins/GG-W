"""Discover the installed native build tools without changing the user's PATH."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


def build_environment() -> dict[str, str]:
    env = os.environ.copy()
    if os.name != 'nt':
        return env
    if shutil.which('cl.exe', path=env.get('PATH')):
        return env
    installer = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer'
    vswhere = installer / 'vswhere.exe'
    if not vswhere.is_file():
        raise RuntimeError('Install Visual Studio Build Tools with the C++ workload first')
    installation = subprocess.check_output(
        [str(vswhere), '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
         '-property', 'installationPath'], text=True, encoding='utf-8', timeout=15).strip()
    setup = Path(installation) / 'VC/Auxiliary/Build/vcvars64.bat'
    if not installation or not setup.is_file():
        raise RuntimeError('The Visual Studio C++ workload is not installed yet')
    # The only command input is the validated installed Microsoft batch file.
    comspec = env.get('COMSPEC', 'C:/Windows/System32/cmd.exe')
    if any(character in str(setup) + comspec for character in '%!&|<>\r\n"'):
        raise RuntimeError('Unsupported characters in the installed Microsoft build tool path')
    command = '"' + comspec + '" /d /s /c ""' + str(setup) + '" >nul && set"'
    result = subprocess.run(command,
                            capture_output=True, check=True, timeout=30)
    text = result.stdout.decode('mbcs', errors='replace')
    for line in text.splitlines():
        name, separator, value = line.partition('=')
        if separator and name and not name.startswith('='):
            # Windows environment keys are case insensitive; plain dicts are not.
            for old in list(env):
                if old.upper() == name.upper():
                    del env[old]
            env[name.upper()] = value
    return env


def build_tool(name: str, env: dict[str, str]) -> str:
    path = shutil.which(name, path=env.get('PATH'))
    if not path:
        raise RuntimeError('Native build tool is missing: ' + name)
    return path
