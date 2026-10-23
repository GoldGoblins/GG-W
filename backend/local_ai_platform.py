"""OS plumbing for callers of the unchanged, pinned local model runner.

The model, container, grammar, output and request contracts remain the frozen
runner's. Only host paths, file IO and OS ownership metadata are adapted.
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.platform_files import is_link, owned_by_current_user, mode_matches, secure_open, set_private_mode
from backend.platform_support import private_runtime_root, workspace_root, platform_path


def adapt_model_runner(base):
    if os.name != 'nt' or getattr(base, '_gg_windows_platform_adapter', False):
        return base
    project = Path(__file__).resolve().parents[1]
    base.REPO = base.pathlib_repo = workspace_root()
    base.PROJECT = project
    base.CONTRACT_PATH = project / 'backend/local_ai_contract.py'
    base.MODEL_DIR = Path(os.environ.get('GG_MODEL_DIR') or platform_path('/home/GG/models/qwen3-4b-q5_k_m'))
    base.MODEL_PATH = base.MODEL_DIR / base.MODEL_PATH.name

    def validate_evidence_dir(path):
        if is_link(path) or not path.is_dir():
            raise base.RunnerStop('evidence_root_unsafe')
        resolved = path.resolve(strict=True)
        if resolved.parent != private_runtime_root():
            raise base.RunnerStop('evidence_root_parent_invalid')
        if not resolved.name.startswith('gg-wb3d-model-runner.'):
            raise base.RunnerStop('evidence_root_name_invalid')
        if not owned_by_current_user(resolved):
            raise base.RunnerStop('evidence_root_owner_invalid')
        if not mode_matches(resolved, 0o700):
            raise base.RunnerStop('evidence_root_mode_invalid')
        return resolved

    def write_new(path, data, mode=0o600):
        if path.exists() or is_link(path):
            raise base.RunnerStop('evidence_path_exists:' + str(path))
        fd = secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        set_private_mode(path, mode)

    base.validate_evidence_dir = validate_evidence_dir
    base.write_new = write_new
    base._gg_windows_platform_adapter = True
    return base
