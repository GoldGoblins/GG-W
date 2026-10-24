"""A trusted per-user MSVC runtime for the isolated candidate syntax check."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from backend.platform_files import is_link


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare() -> tuple[Path, Path]:
    """Copy only installed compiler binaries, never candidate code or user config."""
    if os.name != 'nt':
        raise ValueError('WINDOWS_COMPILER_REQUIRED')
    from backend.platform_build import build_environment, build_tool
    from backend.research_lab import TOOLS_ROOT
    installed = Path(build_tool('cl.exe', build_environment())).resolve()
    source = installed.parent
    files = sorted(path for path in source.rglob('*')
                   if path.is_file() and path.suffix.lower() in ('.exe', '.dll') and not path.is_symlink())
    if not files or len(files) > 256 or sum(path.stat().st_size for path in files) > 256 * 1024 * 1024:
        raise ValueError('COMPILER_RUNTIME_LIMIT')
    records = {}
    for path in files:
        if not path.resolve().is_relative_to(source):
            raise ValueError('COMPILER_SOURCE_CHANGED')
        records[path.relative_to(source).as_posix()] = _digest(path)
    identity = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:24]
    parent = (TOOLS_ROOT / 'compiler').resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / ('msvc-' + identity)
    if is_link(target):
        raise ValueError('COMPILER_CACHE_CHANGED')
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix='msvc-stage-', dir=parent) as raw:
            staging = Path(raw)
            runtime = staging / 'runtime'
            runtime.mkdir()
            for name, digest in records.items():
                destination = runtime / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, destination)
                if _digest(destination) != digest:
                    raise ValueError('COMPILER_SOURCE_CHANGED')
            (runtime / 'provenance.json').write_text(json.dumps({
                'schema': 'gg.research-msvc-runtime.v1', 'source': str(source),
                'files': records, 'scope': 'C11_SYNTAX_ONLY_NO_TARGET_EXECUTION'}, indent=2) + '\n', encoding='utf-8')
            if not runtime.resolve().is_relative_to(parent) or not target.resolve().is_relative_to(parent):
                raise ValueError('COMPILER_CACHE_OUTSIDE_TOOLS')
            runtime.rename(target)
    for name, digest in records.items():
        candidate = target / name
        if not candidate.resolve().is_relative_to(target) or _digest(candidate) != digest:
            raise ValueError('COMPILER_CACHE_CHANGED')
    return target, target / installed.name


def syntax(code: str) -> dict:
    """The compiler parses a copied C function inside AppContainer; never links."""
    from backend.windows_research_sandbox import run
    try:
        tools, compiler = prepare()
        with tempfile.TemporaryDirectory(prefix='gg-candidate-syntax-') as raw:
            scratch = Path(raw)
            candidate = scratch / 'candidate.c'
            candidate.write_text(code, encoding='utf-8')
            command = [str(compiler), '/nologo', '/TC', '/std:c11', '/Zs', '/X',
                       '/utf-8', '/we4013', str(candidate)]
            returncode, output, errors, trigger = run(command, scratch=scratch, tools=tools,
                                                     timeout=15, max_output_bytes=16384)
        diagnostics = (output + errors).decode('utf-8', 'replace')[:8192]
        if trigger != 'NONE':
            return {'state': 'FAIL', 'reason': 'COMPILER_' + trigger}
        return {'state': 'PASS' if returncode == 0 else 'FAIL', 'scope': 'C11_SYNTAX_ONLY',
                'diagnostics': diagnostics,
                'limits': ['No linking or target execution. Header search paths, runtime ABI, behavior and C++ equivalence are outside this syntax check.']}
    except (OSError, ValueError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return {'state': 'UNKNOWN', 'reason': 'WINDOWS_COMPILER_SANDBOX_UNAVAILABLE', 'detail': reason}
