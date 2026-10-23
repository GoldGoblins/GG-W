"""Native Podman CLI and the actual unprivileged Linux container identity."""
from __future__ import annotations

from functools import lru_cache
import os
import subprocess
import ast
import json
from pathlib import Path

from backend.platform_support import executable_path, host_environment
from backend.platform_process import run_bounded


@lru_cache(maxsize=1)
def container_user() -> str:
    if os.name != 'nt':
        return f'{os.getuid()}:{os.getgid()}'
    podman = executable_path('podman')
    values = []
    for flag in ('-u', '-g'):
        result = subprocess.run([podman, 'machine', 'ssh', '--', 'id', flag],
                                env=host_environment(), capture_output=True, timeout=15)
        value = result.stdout.decode('utf-8', errors='strict').strip()
        if result.returncode or not value.isdecimal() or not 0 < int(value) < 2**31:
            raise RuntimeError('PODMAN_UNPRIVILEGED_MACHINE_USER_UNAVAILABLE')
        values.append(str(int(value)))
    return ':'.join(values)


def runtime_status() -> dict:
    """Inspect the running VM and published images; never pull or start one."""
    state = {'running': False, 'rootless': False, 'required_images': {}, 'ready': False}
    try:
        code, output, _, trigger = run_bounded([executable_path('podman'), 'info', '--format', 'json'],
                                             timeout=4, max_output_bytes=256*1024)
        if code or trigger != 'NONE':return state
        info = json.loads(output)
        state.update(running=True, rootless=info['host']['security']['rootless'])
        root = Path(__file__).resolve().parent
        for name, filename, constant in (
                ('safe_tools', 'safe_tool_runner.py', 'IMAGE_ID'),
                ('qml_gate', 'write_runner.py', 'QML_IMAGE_ID'),
                ('local_model', 'local_ai_model_runner.py', 'RUNTIME_IMAGE_ID')):
            tree = ast.parse((root / filename).read_text(encoding='utf-8'))
            value = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == constant for target in node.targets))
            code, _, _, trigger = run_bounded([executable_path('podman'), 'image', 'exists', value],
                                              timeout=3, max_output_bytes=4096)
            state['required_images'][name] = code == 0 and trigger == 'NONE'
        state['ready'] = bool(state['rootless'] and all(state['required_images'].values()))
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        pass
    return state
