"""Explicit, bounded static REA jobs shared by the Research UI and command line.

Each job uses a disposable read-only target snapshot inside a network-isolated
bubblewrap sandbox. No target code, arbitrary command or user script is run.
Only scrubbed reports survive; scratch and provider projects are removed.
"""
from __future__ import annotations

from backend.application_paths import HOME, STATE_ROOT

import argparse
from backend.platform_support import file_locks as fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid

from backend import research_lab as lab

ROOT = Path(os.environ.get('GG_RESEARCH_JOBS_ROOT', str(STATE_ROOT / 'research-jobs')))
SCHEMA = 'gg.research-job.v1'
PROJECT = Path(__file__).resolve().parents[1]
TIMEOUT = 300
MAX_INPUT = 64 * 1024 * 1024
MAX_SCRATCH = 256 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
MAX_JOBS = 16
MAX_HISTORY_BYTES = 32 * 1024 * 1024
OPERATIONS = {'analyze', 'search', 'function', 'decompile', 'xrefs'}
BUSY = {'QUEUED', 'RUNNING'}
SOURCE_SUFFIXES = {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.json'}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.cache', '.config', '.ssh', '.aws', '.codex', '.local'}


def _dir(job_id: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{32}', str(job_id)):
        raise ValueError('INVALID_JOB')
    path = ROOT / job_id
    if path.is_symlink():
        raise ValueError('INVALID_JOB')
    return path


def _write(path: Path, value: dict):
    temp = path.with_suffix('.new')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
    temp.chmod(0o600)
    temp.replace(path)


def _read(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > lab.MAX_REPORT_BYTES + 16384:
        raise ValueError('INVALID_JOB_RECORD')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('INVALID_JOB_RECORD')
    return value


def _alive(state: dict) -> bool:
    pid = int(state.get('worker_pid') or 0)
    if not pid:
        return state.get('status') == 'QUEUED' and time.time() - state.get('created_epoch', 0) < 20
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return b'backend.research_jobs' in cmd and str(state['job_id']).encode() in cmd
    except OSError:
        return False


def status(job_id: str, include_report: bool = True) -> dict:
    try:
        folder = _dir(job_id)
        state = _read(folder / 'state.json')
        if state['status'] in BUSY and not _alive(state):
            state.update(status='ERROR', reason='WORKER_STOPPED', finished_at=lab.research_desk._now())
            _write(folder / 'state.json', state)
            shutil.rmtree(folder / 'scratch', ignore_errors=True)
        if include_report and state['status'] == 'COMPLETE':
            state['report'] = _read(folder / 'report.json')
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return {'schema': SCHEMA, 'status': 'ERROR', 'reason': 'JOB_NOT_FOUND'}


def history() -> dict:
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    jobs = [status(p.name, False) for p in ROOT.iterdir() if not p.is_symlink() and p.is_dir() and re.fullmatch(r'[0-9a-f]{32}', p.name)]
    jobs.sort(key=lambda j: j.get('created_epoch', 0), reverse=True)
    return {'schema': SCHEMA, 'status': 'READY', 'jobs': jobs[:MAX_JOBS],
            'limits': {'concurrent_jobs': 1, 'seconds': TIMEOUT, 'scratch_bytes': MAX_SCRATCH,
                       'history_bytes': MAX_HISTORY_BYTES, 'retained_jobs': MAX_JOBS}}


def _cleanup():
    # Include overflow records, rather than only the public bounded history.
    folders = sorted((p for p in ROOT.iterdir() if not p.is_symlink() and p.is_dir() and re.fullmatch(r'[0-9a-f]{32}', p.name)),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for index, folder in enumerate(folders):
        state = status(folder.name, False)
        if state.get('status') in BUSY:
            continue
        shutil.rmtree(folder / 'scratch', ignore_errors=True)
        size = sum(p.stat().st_size for p in folder.rglob('*') if p.is_file() and not p.is_symlink())
        if index >= MAX_JOBS or total + size > MAX_HISTORY_BYTES:
            shutil.rmtree(folder)
        else:
            total += size


def start(raw: str, operation: str = 'analyze', query: str = '') -> dict:
    try:
        if operation not in OPERATIONS:
            raise ValueError('UNSUPPORTED_OPERATION')
        query = str(query).strip()
        if operation != 'analyze' and (not query or len(query) > 160 or query.startswith('-') or '\0' in query):
            raise ValueError('QUERY_REQUIRED')
        path = lab._path(raw)
        if not path.is_dir():
            if not path.is_file():
                raise ValueError('REGULAR_FILE_OR_PROJECT_REQUIRED')
            if path.stat().st_size > lab.MAX_ARTIFACT_BYTES:
                raise ValueError('FILE_TOO_LARGE')
        elif operation != 'analyze':
            raise ValueError('PROJECT_SUPPORTS_ANALYZE_ONLY')
        elif path == Path.home() or path in Path.home().parents or str(path) in {'/usr', '/etc', '/var', '/tmp'}:
            raise ValueError('SELECT_A_SPECIFIC_PROJECT')
        if not shutil.which('bwrap'):
            raise ValueError('SANDBOX_UNAVAILABLE')
        tools = lab.tool_inventory()['engines']
        if not any(t['name'] == 'REA' and t['state'] != 'NOT_INSTALLED' for t in tools):
            raise ValueError('REA_NOT_INSTALLED')
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (ROOT / '.admission').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _cleanup()
            if any(j.get('status') in BUSY for j in history()['jobs']):
                raise ValueError('ANALYSIS_ALREADY_RUNNING')
            job_id = uuid.uuid4().hex
            folder = _dir(job_id)
            folder.mkdir(mode=0o700)
            state = {'schema': SCHEMA, 'job_id': job_id, 'status': 'QUEUED', 'operation': operation,
                     'query': query, 'target': str(path), 'created_epoch': time.time(),
                     'created_at': lab.research_desk._now(), 'worker_pid': 0, 'phase': 'Preparing local snapshot'}
            _write(folder / 'state.json', state)
            env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONPATH': str(PROJECT),
                   'GG_RESEARCH_JOBS_ROOT': str(ROOT), 'GG_RESEARCH_DESK_ROOT': str(lab.research_desk.ROOT),
                   'GG_RESEARCH_TOOLS_ROOT': str(lab.TOOLS_ROOT)}
            proc = subprocess.Popen([sys.executable, '-m', 'backend.research_jobs', '--worker', job_id],
                                    cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
            # Worker owns subsequent state updates. PID lives in a separate file,
            # so admission cannot overwrite a fast completion with QUEUED.
            (folder / 'worker.pid').write_text(str(proc.pid))
            state['worker_pid'] = proc.pid
            return state
    except (OSError, ValueError) as exc:
        return {'schema': SCHEMA, 'status': 'ERROR', 'reason': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}


def cancel(job_id: str) -> dict:
    state = status(job_id, False)
    if state.get('status') not in BUSY:
        return state
    (_dir(job_id) / 'cancel').touch(mode=0o600)
    return {'schema': SCHEMA, 'job_id': job_id, 'status': 'CANCELLING'}


def load_report(report_id: str) -> dict | None:
    state = status(report_id)
    return state.get('report') if state.get('status') == 'COMPLETE' else None


def _snapshot(path: Path, scratch: Path) -> tuple[Path, str, str, int]:
    target = scratch / 'target'
    if path.is_dir():
        target.mkdir()
        files = []
        scanned = 0
        began = time.monotonic()
        for directory, dirs, names in os.walk(path, followlinks=False):
            scanned += len(dirs) + len(names)
            if scanned > 20000 or time.monotonic() - began > 15:
                raise ValueError('PROJECT_SCAN_LIMIT')
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                p = Path(directory) / name
                if p.suffix.lower() not in SOURCE_SUFFIXES or p.is_symlink() or name.startswith('.'):
                    continue
                if re.search(r'(?i)credentials|secrets|private.key|service.account', name):
                    continue
                files.append(p)
                if len(files) > 4096:
                    raise ValueError('PROJECT_FILE_LIMIT')
        if not files:
            raise ValueError('NO_JAVASCRIPT_PROJECT_FILES')
        digest = hashlib.sha256()
        total = 0
        for p in files:
            if not p.resolve().is_relative_to(path):
                raise ValueError('PROJECT_TARGET_CHANGED')
            _, data = lab._read(str(p), lab.MAX_ARTIFACT_BYTES)
            total += len(data)
            if total > MAX_INPUT:
                raise ValueError('PROJECT_SIZE_LIMIT')
            if b'PRIVATE KEY-----' in data:
                raise ValueError('PRIVATE_KEY_MATERIAL_NOT_ANALYZED')
            rel = p.relative_to(path)
            digest.update(str(rel).encode() + b'\0' + hashlib.sha256(data).digest())
            destination = target / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        return target, digest.hexdigest(), 'JAVASCRIPT PROJECT', total
    _, data = lab._read(str(path), lab.MAX_ARTIFACT_BYTES)
    if b'PRIVATE KEY-----' in data:
        raise ValueError('PRIVATE_KEY_MATERIAL_NOT_ANALYZED')
    kind, _ = lab._format(path, data)
    if kind == 'SOURCE' and path.suffix.lower() in SOURCE_SUFFIXES:
        target.mkdir()
        (target / path.name).write_bytes(data)
        kind = 'JAVASCRIPT PROJECT'
    elif kind in {'ELF', 'PE', 'MACH-O / FAT', 'MACH-O FAT CANDIDATE', 'ASAR CANDIDATE'}:
        target = scratch / ('target' + path.suffix)
        target.write_bytes(data)
    else:
        raise ValueError('SELECT_NATIVE_BINARY_OR_JAVASCRIPT_PROJECT')
    return target, hashlib.sha256(data).hexdigest(), kind, len(data)


def _sandbox(scratch: Path, target: Path, kind: str, operation: str, query: str) -> list[str]:
    rea = lab.TOOLS_ROOT / 'rea/node_modules/rea-agents/scripts/rea.mjs'
    if not rea.is_file():
        raise ValueError('PINNED_REA_INSTALL_REQUIRED')
    if json.loads((rea.parents[1] / 'package.json').read_text()).get('version') != '6.0.0':
        raise ValueError('REA_VERSION_CHANGED')
    ghidra = lab.TOOLS_ROOT / 'ghidra'
    native = kind != 'JAVASCRIPT PROJECT' and kind != 'ASAR CANDIDATE'
    if native and not (ghidra / 'support/analyzeHeadless').is_file():
        raise ValueError('GHIDRA_NOT_INSTALLED')
    if native:
        properties = (ghidra / 'Ghidra/application.properties').read_text()
        if not re.search(r'^application.version=12\.1\.4\s*$', properties, re.MULTILINE):
            raise ValueError('GHIDRA_VERSION_CHANGED')
    if not native and operation != 'analyze':
        raise ValueError('PROJECT_SUPPORTS_ANALYZE_ONLY')
    for directory in ['home', 'tmp']:
        (scratch / directory).mkdir()
    sandbox_target = '/input/' + target.name
    node = Path(shutil.which('node') or str(HOME / '.local/bin/node')).resolve()
    local_jdk = lab.TOOLS_ROOT / 'jdk'
    java_home = Path('/tools/jdk') if (local_jdk / 'bin/javac').is_file() else Path(shutil.which('java') or '/usr/bin/java').resolve().parent.parent
    if not node.is_file():
        raise ValueError('NODE_NOT_INSTALLED')
    command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--ro-bind', '/usr', '/usr',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64', '--symlink', 'usr/bin', '/bin',
               '--proc', '/proc', '--dev', '/dev', '--dir', '/etc', '--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache',
               '--dir', '/etc/crypto-policies', '--dir', '/etc/crypto-policies/back-ends',
               '--ro-bind', '/etc/crypto-policies/back-ends/java.config', '/etc/crypto-policies/back-ends/java.config',
               '--ro-bind', str(lab.TOOLS_ROOT), '/tools', '--dir', '/runtime', '--ro-bind', str(node), '/runtime/node',
               '--dir', '/input', '--ro-bind', str(target), sandbox_target,
               '--bind', str(scratch / 'home'), '/home/research', '--bind', str(scratch / 'tmp'), '/tmp',
               '--chdir', '/home/research', '--clearenv', '--setenv', 'PATH', '/runtime:' + str(java_home / 'bin') + ':/usr/bin:/bin',
               '--setenv', 'HOME', '/home/research', '--setenv', 'LANG', 'C.UTF-8',
               '--setenv', 'JAVA_HOME', str(java_home),
               '--setenv', 'GHIDRA_INSTALL_DIR', '/tools/ghidra', '--setenv', 'TMPDIR', '/tmp',
               '--setenv', 'GHIDRA_HEADLESS_MAXMEM', '512m',
               '--setenv', 'JAVA_TOOL_OPTIONS', '-Xmx512m -XX:ActiveProcessorCount=2',
               '--setenv', 'NODE_OPTIONS', '--max-old-space-size=512',
               '/usr/bin/prlimit', '--cpu=180', '--fsize=67108864', '--nofile=512', '--',
               '/runtime/node', '/tools/rea/node_modules/rea-agents/scripts/rea.mjs']
    if native:
        command += [operation, sandbox_target]
        if operation != 'analyze':
            command += [query]
        command += ['--provider', 'ghidra', '--json']
    else:
        command += ['analyze-javascript-application', sandbox_target, '--json']
        # Request a bounded structured view at the producer, rather than emit
        # the very large repeated provenance records in a full AST graph.
        paths = ['subject', 'provider', 'predicate_type', 'operation', 'parameters', 'confidence', 'authority',
                 'limitations', 'locations', 'normalized_result.format', 'normalized_result.graph.schema',
                 'normalized_result.graph.coverage', 'normalized_result.graph.limitations',
                 'normalized_result.graph.nodes[0,128].node_id', 'normalized_result.graph.nodes[0,128].kind',
                 'normalized_result.graph.nodes[0,128].observations[0,4].label',
                 'normalized_result.graph.nodes[0,128].observations[0,4].properties',
                 'normalized_result.graph.nodes[0,128].observations[0,4].evidence.location',
                 'normalized_result.graph.edges[0,128]']
        command += ['--filter-output', ','.join(paths)]
    return command


def _stop(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=2)
    except ProcessLookupError:
        pass


def _run(command: list[str], folder: Path) -> tuple[int, bytes, bytes]:
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    buffers = [bytearray(), bytearray()]
    selector = selectors.DefaultSelector()
    for index, stream in enumerate([proc.stdout, proc.stderr]):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, index)
    began = time.monotonic()
    checked = began
    try:
        while selector.get_map() or proc.poll() is None:
            if (folder / 'cancel').exists():
                raise ValueError('CANCELLED')
            if time.monotonic() - began > TIMEOUT:
                raise ValueError('TIME_LIMIT')
            if time.monotonic() - checked > 1:
                size = sum(p.stat().st_size for p in (folder / 'scratch').rglob('*') if p.is_file() and not p.is_symlink())
                checked = time.monotonic()
                if size > MAX_SCRATCH:
                    raise ValueError('SCRATCH_LIMIT')
            for key, _ in selector.select(0.2):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    buffers[key.data].extend(data)
                    if sum(map(len, buffers)) > MAX_OUTPUT:
                        raise ValueError('OUTPUT_LIMIT')
        return proc.wait(), bytes(buffers[0]), bytes(buffers[1])
    finally:
        _stop(proc)
        selector.close()
        proc.stdout.close()
        proc.stderr.close()


def worker(job_id: str):
    os.umask(0o077)
    folder = _dir(job_id)
    state = _read(folder / 'state.json')
    scratch = folder / 'scratch'
    try:
        with (ROOT / '.worker').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state.update(status='RUNNING', worker_pid=os.getpid(), phase='Preparing local snapshot')
            _write(folder / 'state.json', state)
            if (folder / 'cancel').exists():
                raise ValueError('CANCELLED')
            scratch.mkdir(mode=0o700)
            target, digest, kind, size = _snapshot(Path(state['target']), scratch)
            command = _sandbox(scratch, target, kind, state['operation'], state['query'])
            state.update(phase='Analyzing with REA / Ghidra' if kind not in {'JAVASCRIPT PROJECT', 'ASAR CANDIDATE'} else 'Analyzing JavaScript application')
            _write(folder / 'state.json', state)
            code, output, errors = _run(command, folder)
            if code:
                state['diagnostic'] = lab._redact_text(errors.decode('utf-8', 'replace'), 1200)
                # Preserve REA's structured error, without exposing raw output.
                try:
                    state['engine_error'] = lab._clean_tree(json.loads(output))
                except (ValueError, UnicodeError):
                    pass
                raise ValueError('ENGINE_FAILED')
            content = lab._clean_tree(json.loads(output))
            if not isinstance(content, dict) or not content:
                raise ValueError('INVALID_ENGINE_REPORT')
            if content.get('ok') is False or content.get('error'):
                state['engine_error'] = content
                raise ValueError('ENGINE_FAILED')
            report = {'schema': lab.SCHEMA, 'report_id': job_id, 'status': 'ANALYZED',
                      'engine': 'REA / Ghidra' if kind not in {'JAVASCRIPT PROJECT', 'ASAR CANDIDATE'} else 'REA',
                      'provenance': 'LOCAL_ENGINE_STATIC_OBSERVATION', 'observed_at': lab.research_desk._now(),
                      'name': Path(state['target']).name, 'path': state['target'], 'bytes': size,
                      'format': kind, 'artifact_sha256': digest, 'strings': [], 'operation': state['operation'],
                      'facts': ['Selected target snapshot analyzed locally in a network-isolated sandbox.',
                                'REA 6.0.0; Ghidra 12.1.4 for native targets.'],
                      'limits': ['Static analysis describes structure; pseudocode and inferred relationships require validation.',
                                 'JavaScript snapshots omit dependencies, hidden files, credential-named files and non-source assets.',
                                 'JavaScript graph view: first 128 nodes / edges and 4 observations per node; not the full graph.',
                                 'Report collections and long strings are bounded and sensitive values redacted; provider limitations remain in the content.'],
                      'content': content, 'summary': f"{state['operation']} · {kind} · local static analysis"}
            if len(json.dumps(report).encode()) > lab.MAX_REPORT_BYTES:
                raise ValueError('REPORT_LIMIT')
            _write(folder / 'report.json', report)
            state.update(status='COMPLETE', phase='Report ready')
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        state.update(status='CANCELLED' if reason == 'CANCELLED' else 'ERROR', reason=reason, phase='Stopped')
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        state['finished_at'] = lab.research_desk._now()
        _write(folder / 'state.json', state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    args = parser.parse_args()
    worker(args.worker)
