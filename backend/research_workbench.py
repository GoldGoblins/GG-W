"""Local, bounded research receipts shared by the UI and both AI motors.

This is an index and an explicit queue, not a crawler or an authority grant.
Workers claim a source, use the already approved research tools, then return
attributed material. Opening the desk never runs sources, models or tests.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

from backend import research_desk as desk

SCHEMA = 'gg.research-workbench.v1'
PROJECT = Path(__file__).resolve().parents[1]
MAX_LINKS = 512
MAX_BODY = 512 * 1024
MAX_STORAGE = 64 * 1024 * 1024
SESSION_STORAGE = 16 * 1024 * 1024
LEASE_SECONDS = 120
TEST_TIMEOUT = 90
_SENSITIVE_KEY = re.compile(r'(?i)password|passwd|secret|token|authorization|api.?key|cookie|private.?key')


@contextmanager
def _db(write=False):
    with desk._LOCK, desk._db() as db:
        if write and not db.in_transaction:
            # The two AI motors can use separate processes. Acquire the SQLite
            # writer before checking uniqueness/quotas, not after the read.
            db.execute('BEGIN IMMEDIATE')
        yield db


def _result(status, **values):
    return dict(schema=SCHEMA, status=status, **values)


def _key(value):
    value = str(value or '').strip()
    if not value or len(value) > 180 or '\x00' in value:
        raise ValueError('TASK_OR_SESSION_REQUIRED')
    return value


def _uid(prefix):
    return prefix + '-' + uuid.uuid4().hex


def _redact(text):
    """Preserve line numbers and public versions; redact before any persistence."""
    text = str(text)
    text = re.sub(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)',
                  '[PRIVATE KEY REDACTED]', text, flags=re.I | re.S)
    text = re.sub(r'(?im)((?:proxy-)?authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'''(?im)((?<![\w-])["']?(?:password|passwd|secret|client_secret|secret_key|token|access_token|refresh_token|id_token|api[_-]?key|cookie|set-cookie|private[_-]?key)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)''', r'\1[REDACTED]', text)
    text = re.sub(r'(https?://)[^\s/@:]+:[^\s/@]+@', r'\1[REDACTED]@', text, flags=re.I)
    text = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b', '[REDACTED]', text)
    return text


def _url(raw):
    raw = str(raw).strip().rstrip('.,;)')
    if len(raw) > 2048:
        raise ValueError('URL_TOO_LONG')
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('PUBLIC_URL_REQUIRED')
    if any(_SENSITIVE_KEY.search(k) for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise ValueError('CREDENTIAL_URL_REJECTED')
    host = parts.hostname.lower()
    port = parts.port
    if host in {'www.twitter.com', 'twitter.com', 'www.x.com'}:
        host = 'x.com'
    authority = ('[' + host + ']') if ':' in host else host
    if port and (parts.scheme.lower(), port) not in {('https', 443), ('http', 80)}:
        authority += ':' + str(port)
    path = parts.path or '/'
    if host == 'x.com':
        match = re.fullmatch(r'/([^/]+)/status/(\d+)/?', path)
        if match:
            path = '/' + match[1].lower() + '/status/' + match[2]
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}
                       and not (host == 'x.com' and k in {'s', 't'})])
    return urlunsplit((parts.scheme.lower(), authority, path, query, ''))


def create_batch(title, links):
    if isinstance(links, str):
        if len(links) > 256 * 1024:
            raise ValueError('LINK_INPUT_LIMIT')
        links = re.findall(r'https?://[^\s<>"\x00]+', links)
    if not isinstance(links, list) or not links or len(links) > MAX_LINKS:
        raise ValueError('ONE_TO_512_LINKS_REQUIRED')
    canonical = list(dict.fromkeys(_url(item) for item in links))
    title = desk._scrub(title, 160) or 'Research'
    batch_id = desk._id('batch', title + '\n' + '\n'.join(sorted(canonical)))
    now = desk._now()
    with _db(write=True) as db:
        existing = db.execute('SELECT 1 FROM wb_batches WHERE id=?', (batch_id,)).fetchone()
        if not existing:
            if db.execute('SELECT COUNT(*) FROM wb_batches').fetchone()[0] >= 128:
                raise ValueError('BATCH_STORAGE_LIMIT')
            db.execute('INSERT INTO wb_batches VALUES(?,?,?,?,?)', (batch_id, title, 'PAUSED', now, now))
            db.executemany('INSERT INTO wb_items(id,batch_id,position,url,state) VALUES(?,?,?,?,?)',
                           [(_uid('source'), batch_id, n, url, 'PENDING') for n, url in enumerate(canonical)])
    return _result('BATCH_EXISTS' if existing else 'BATCH_CREATED', batch_id=batch_id,
                   unique=len(canonical), duplicates=len(links)-len(canonical))


def control_batch(batch_id, action):
    state = {'resume': 'RUNNING', 'pause': 'PAUSED', 'cancel': 'CANCELLED'}.get(action)
    if state is None:
        raise ValueError('INVALID_BATCH_ACTION')
    with _db(write=True) as db:
        row = db.execute('SELECT state FROM wb_batches WHERE id=?', (batch_id,)).fetchone()
        if not row:
            raise ValueError('BATCH_NOT_FOUND')
        if row['state'] == 'CANCELLED':
            raise ValueError('BATCH_CANCELLED')
        db.execute('UPDATE wb_batches SET state=?,updated_at=? WHERE id=?', (state, desk._now(), batch_id))
        if action != 'resume':
            db.execute("UPDATE wb_items SET state='PENDING',lease='',lease_until=0,note='Interrupted; available on resume' WHERE batch_id=? AND state='IN_PROGRESS'", (batch_id,))
    return _result(state, batch_id=batch_id)


def _recover(db):
    db.execute("UPDATE wb_items SET state='PENDING',lease='',lease_until=0,note='Worker interrupted; ready to retry' WHERE state='IN_PROGRESS' AND lease_until<=?", (time.time(),))


def claim_source(batch_id):
    with _db(write=True) as db:
        _recover(db)
        batch = db.execute('SELECT state FROM wb_batches WHERE id=?', (batch_id,)).fetchone()
        if not batch:
            raise ValueError('BATCH_NOT_FOUND')
        if batch['state'] != 'RUNNING':
            return _result(batch['state'])
        # One bounded lane per source batch. Lease identity rejects late replies.
        if db.execute("SELECT 1 FROM wb_items WHERE batch_id=? AND state='IN_PROGRESS'", (batch_id,)).fetchone():
            return _result('BUSY')
        item = db.execute("SELECT * FROM wb_items WHERE batch_id=? AND state='PENDING' ORDER BY position LIMIT 1", (batch_id,)).fetchone()
        if not item:
            return _result('QUEUE_FINISHED', **_counts(db, batch_id))
        lease = uuid.uuid4().hex
        db.execute("UPDATE wb_items SET state='IN_PROGRESS',lease=?,lease_until=? WHERE id=?", (lease, time.time()+LEASE_SECONDS, item['id']))
        return _result('CLAIMED', item_id=item['id'], batch_id=batch_id, source=item['url'],
                       lease=lease, lease_seconds=LEASE_SECONDS)


def renew_source(item_id, lease):
    with _db(write=True) as db:
        _recover(db)
        changed = db.execute("UPDATE wb_items SET lease_until=? WHERE id=? AND lease=? AND state='IN_PROGRESS'", (time.time()+LEASE_SECONDS, item_id, lease)).rowcount
        if not changed:
            raise ValueError('SOURCE_LEASE_EXPIRED')
    return _result('LEASE_RENEWED')


def complete_source(item_id, lease, outcome, note, content='', exit_code=None):
    if outcome not in {'READ', 'BLOCKED', 'SKIPPED'} or not str(note).strip():
        raise ValueError('SOURCE_OUTCOME_AND_SCOPE_REQUIRED')
    if outcome == 'READ' and not str(content).strip():
        raise ValueError('SOURCE_MATERIAL_REQUIRED')
    with _db(write=True) as db:
        _recover(db)
        row = db.execute('SELECT i.*,b.state AS batch_state FROM wb_items i JOIN wb_batches b ON b.id=i.batch_id WHERE i.id=?', (item_id,)).fetchone()
        if not row or row['state'] != 'IN_PROGRESS' or row['lease'] != lease or row['batch_state'] != 'RUNNING':
            raise ValueError('SOURCE_LEASE_EXPIRED')
        observation_id = ''
        if outcome == 'READ':
            saved = observe(row['batch_id'], row['url'], content, note, exit_code)
            observation_id = saved['observation_id']
        db.execute("UPDATE wb_items SET state=?,lease='',lease_until=0,note=?,observation_id=? WHERE id=?",
                   (outcome, desk._scrub(note, 2000), observation_id, item_id))
        return _result('SOURCE_RECORDED', outcome=outcome, **_counts(db, row['batch_id']))


def retry_source(item_id):
    with _db(write=True) as db:
        row = db.execute('SELECT i.state,b.state AS batch_state FROM wb_items i JOIN wb_batches b ON b.id=i.batch_id WHERE i.id=?', (item_id,)).fetchone()
        if not row or row['batch_state'] == 'CANCELLED' or row['state'] not in {'BLOCKED', 'SKIPPED'}:
            raise ValueError('SOURCE_NOT_RETRYABLE')
        db.execute("UPDATE wb_items SET state='PENDING',note='' WHERE id=?", (item_id,))
    return _result('SOURCE_REQUEUED')


def _counts(db, batch_id):
    counts = {r[0]: r[1] for r in db.execute('SELECT state,COUNT(*) FROM wb_items WHERE batch_id=? GROUP BY state', (batch_id,))}
    return dict(total=sum(counts.values()), read=counts.get('READ', 0), blocked=counts.get('BLOCKED', 0),
                skipped=counts.get('SKIPPED', 0), pending=counts.get('PENDING', 0), active=counts.get('IN_PROGRESS', 0))


def observe(session, source, content, title='', exit_code=None):
    session = _key(session)
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_BODY:
        raise ValueError('OBSERVATION_SIZE_LIMIT')
    if exit_code is not None and (type(exit_code) is not int or abs(exit_code) > 2**32):
        raise ValueError('INVALID_EXIT_CODE')
    clean = _redact(content)
    source = _redact(str(source))[:2048]
    version = desk._sha(clean)
    observation_id = _uid('observation')
    with _db(write=True) as db:
        used = db.execute('SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM wb_observations').fetchone()[0]
        own = db.execute('SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM wb_observations WHERE session=?', (session,)).fetchone()[0]
        size = len(clean.encode('utf-8'))
        if used + size > MAX_STORAGE or own + size > SESSION_STORAGE:
            raise ValueError('OBSERVATION_STORAGE_LIMIT')
        if db.execute('SELECT COUNT(*) FROM wb_observations').fetchone()[0] >= 8192:
            raise ValueError('OBSERVATION_COUNT_LIMIT')
        db.execute('INSERT INTO wb_observations VALUES(?,?,?,?,?,?,?,?,?)',
                   (observation_id, session, source, version, desk._scrub(title, 200), clean, exit_code, int(clean != content), desk._now()))
    return observation(session, observation_id, compact=True)


def observation(session, observation_id, start=1, count=80, query='', compact=False, expected_version='', offset=None, length=16000):
    session = _key(session)
    if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 100 or len(str(query)) > 200:
        raise ValueError('INVALID_OBSERVATION_RANGE')
    with _db() as db:
        row = db.execute('SELECT * FROM wb_observations WHERE id=? AND session=?', (observation_id, session)).fetchone()
    if not row:
        raise ValueError('OBSERVATION_NOT_FOUND')
    if desk._sha(row['body']) != row['version']:
        raise ValueError('OBSERVATION_CORRUPT')
    if expected_version and expected_version != row['version']:
        raise ValueError('OBSERVATION_VERSION_CHANGED')
    if offset is not None:
        if type(offset) is not int or type(length) is not int or offset < 0 or not 1 <= length <= 48000:
            raise ValueError('INVALID_OBSERVATION_RANGE')
        fragment = row['body'][offset:offset+length]
        return _result('OBSERVATION_FRAGMENT', observation_id=observation_id, version=row['version'], session=session,
                       source=row['source'], title=row['title'], exit_code=row['exit_code'], redacted=bool(row['redacted']),
                       offset=offset, text=fragment, next_offset=offset+len(fragment),
                       total_characters=len(row['body']), complete=offset == 0 and len(fragment) == len(row['body']),
                       eof=offset+len(fragment) >= len(row['body']))
    lines = row['body'].splitlines(keepends=True)
    indexes = list(range(start-1, min(len(lines), start-1+count)))
    if query:
        indexes = [i for i, line in enumerate(lines) if str(query).casefold() in line.casefold()][:count]
    if compact:
        important = [i for i, line in enumerate(lines) if re.search(r'(?i)\b(error|fail(?:ed|ure)?|traceback|exception|assertion|timeout)\b', line)]
        indexes = sorted(set(list(range(min(6, len(lines)))) + important[:24] + list(range(max(0, len(lines)-4), len(lines)))))
    selected = []
    budget = 6000 if compact else 48000
    used = 0
    complete_lines = 0
    for i in indexes:
        remaining = budget-used
        if remaining <= 0:
            break
        text = lines[i][:min(remaining, 512) if compact else remaining]
        clipped = len(text) != len(lines[i])
        selected.append(dict(line=i+1, text=text, clipped=clipped))
        used += len(text)
        complete_lines += int(not clipped)
    return _result('OBSERVATION_READY', observation_id=observation_id, session=session,
                   source=row['source'], title=row['title'], version=row['version'], exit_code=row['exit_code'],
                   redacted=bool(row['redacted']), total_lines=len(lines), lines=selected,
                   omitted_lines=len(lines)-complete_lines, complete=complete_lines == len(lines),
                   retrieval=dict(operation='observation', session=session, observation_id=observation_id,
                                  expected_version=row['version'], start=1, count=80))


def _source_paths(paths, test_module):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
        raise ValueError('ONE_TO_32_SOURCE_FILES_REQUIRED')
    if not re.fullmatch(r'tests\.test_[A-Za-z0-9_]+', test_module):
        raise ValueError('LOCAL_UNITTEST_MODULE_REQUIRED')
    all_paths = list(dict.fromkeys(paths + [test_module.replace('.', '/')+'.py']))
    clean = []
    for raw in all_paths:
        rel = Path(str(raw))
        path = PROJECT / rel
        if rel.is_absolute() or '..' in rel.parts or any(p.startswith('.') for p in rel.parts):
            raise ValueError('WORKSPACE_SOURCE_REQUIRED')
        if _SENSITIVE_KEY.search(rel.name) or rel.suffix.lower() not in {'.py', '.qml', '.json', '.md', '.txt', '.js', '.mjs', '.html', '.css', '.webmanifest', '.ts', '.toml', '.sil'} and rel.as_posix() != 'gg-research':
            raise ValueError('WORKSPACE_SOURCE_REQUIRED')
        if not path.resolve().is_relative_to(PROJECT.resolve()) or any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in [path, *path.parents] if p != PROJECT.parent):
            raise ValueError('WORKSPACE_SOURCE_REQUIRED')
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('SOURCE_MISSING_OR_TOO_LARGE')
        clean.append(rel.as_posix())
    return sorted(clean)


def _version(paths, test_module):
    paths = _source_paths(paths, test_module)
    digest = hashlib.sha256()
    total = 0
    for rel in paths:
        path = PROJECT / rel
        before = path.stat()
        with path.open('rb') as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        after = path.stat()
        total += len(data)
        if len(data) > 2*1024*1024 or total > 16*1024*1024 or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError('SOURCE_CHANGED_OR_TOO_LARGE')
        digest.update(rel.encode('utf-8') + b'\0' + hashlib.sha256(data).digest())
    return digest.hexdigest()


def add_requirement(task, title, paths, test_module):
    task = _key(task)
    title = desk._scrub(title, 500)
    if not title:
        raise ValueError('REQUIREMENT_TITLE_REQUIRED')
    paths = _source_paths(paths, test_module)
    requirement_id = desk._id('requirement', json.dumps([task, title, paths, test_module]))
    with _db(write=True) as db:
        if db.execute('SELECT COUNT(*) FROM wb_requirements').fetchone()[0] >= 4096 and not db.execute('SELECT 1 FROM wb_requirements WHERE id=?', (requirement_id,)).fetchone():
            raise ValueError('REQUIREMENT_STORAGE_LIMIT')
        if not db.execute('SELECT 1 FROM wb_requirements WHERE id=?', (requirement_id,)).fetchone() and db.execute('SELECT COUNT(*) FROM wb_requirements WHERE task=?', (task,)).fetchone()[0] >= 64:
            raise ValueError('REQUIREMENT_LIMIT')
        db.execute('INSERT OR IGNORE INTO wb_requirements VALUES(?,?,?,?,?,?)',
                   (requirement_id, task, title, json.dumps(paths), test_module, desk._now()))
    return _result('REQUIREMENT_RECORDED', requirement_id=requirement_id)


def _capture_test(test_module):
    status = 'ERROR'
    exit_code = None
    # A temporary output file avoids unbounded PIPE memory. Only a bounded
    # prefix is retained; overflow explicitly invalidates the receipt.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([sys.executable, '-B', '-m', 'unittest', test_module],
                                   cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT,
                                   env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
        deadline = time.monotonic() + TEST_TIMEOUT
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline or output.tell() > MAX_BODY:
                    process.kill()
                    status = 'TIMEOUT' if time.monotonic() >= deadline else 'OUTPUT_LIMIT'
                    break
                time.sleep(0.03)
            exit_code = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        output.seek(0)
        raw = output.read(MAX_BODY+1)
        if len(raw) > MAX_BODY:
            status = 'OUTPUT_LIMIT'
        try:
            text = raw[:MAX_BODY].decode('utf-8')
        except UnicodeDecodeError:
            text = raw[:MAX_BODY].decode('utf-8', errors='replace')
            if status != 'OUTPUT_LIMIT':
                status = 'INVALID_OUTPUT'
        if status in {'OUTPUT_LIMIT', 'INVALID_OUTPUT'}:
            text = text[:MAX_BODY//2] + '\n[Output incomplete: ' + status + ']\n'
    if status == 'ERROR':
        tests = re.search(r'Ran ([0-9]+) tests? in ', text)
        status = 'PASS' if exit_code == 0 and tests and int(tests[1]) > 0 and re.search(r'(?m)^OK(?:\s|$)', text) else 'FAIL'
        if not tests or int(tests[1]) == 0:
            status = 'NO_TESTS'
        if re.search(r'\bskipped=|\bexpected failures=', text) and status == 'PASS':
            status = 'INCOMPLETE'
    return status, text, exit_code


def run_requirement(requirement_id):
    """Explicit CLI operation; never dispatched from a UI snapshot or receipt."""
    with _db() as db:
        row = db.execute('SELECT * FROM wb_requirements WHERE id=?', (requirement_id,)).fetchone()
    if not row:
        raise ValueError('REQUIREMENT_NOT_FOUND')
    paths = json.loads(row['paths_json'])
    before = _version(paths, row['test_module'])
    started = time.monotonic()
    receipt_id = _uid('receipt')
    with _db(write=True) as db:
        if db.execute('SELECT COUNT(*) FROM wb_receipts').fetchone()[0] >= 8192:
            raise ValueError('RECEIPT_STORAGE_LIMIT')
        db.execute('INSERT INTO wb_receipts VALUES(?,?,?,?,?,?,?)',
                   (receipt_id, requirement_id, before, 'RUNNING', '', 0, desk._now()))
    observation_id = ''
    try:
        status, text, exit_code = _capture_test(row['test_module'])
        try:
            if before != _version(paths, row['test_module']):
                status = 'STALE'
        except (ValueError, OSError):
            status = 'STALE'
        observation_id = observe(row['task'], row['test_module'], text, row['title'], exit_code)['observation_id']
    except Exception:
        # Even a full cache, process-start failure or interrupted storage must
        # invalidate a previously passing receipt for the same requirement.
        status = 'ERROR'
    with _db(write=True) as db:
        db.execute('UPDATE wb_receipts SET status=?,observation_id=?,duration_ms=? WHERE id=?',
                   (status, observation_id, round((time.monotonic()-started)*1000), receipt_id))
    return _result(status, receipt_id=receipt_id, requirement_id=requirement_id,
                   observation_id=observation_id, session=row['task'])


def requirements(task=''):
    with _db() as db:
        rows = db.execute('SELECT * FROM wb_requirements WHERE task=? ORDER BY rowid DESC LIMIT 64', (task,)).fetchall() if task else db.execute('SELECT * FROM wb_requirements ORDER BY rowid DESC LIMIT 64').fetchall()
        result = []
        for row in rows:
            receipt = db.execute('SELECT * FROM wb_receipts WHERE requirement_id=? ORDER BY rowid DESC LIMIT 1', (row['id'],)).fetchone()
            state = 'UNVERIFIED'
            if receipt:
                state = receipt['status']
                original = db.execute('SELECT * FROM wb_observations WHERE id=? AND session=?', (receipt['observation_id'], row['task'])).fetchone()
                if state == 'RUNNING':
                    started_at = datetime.fromisoformat(receipt['created_at'].replace('Z', '+00:00')).timestamp()
                    if time.time()-started_at > TEST_TIMEOUT+30:
                        state = 'INTERRUPTED'
                elif not original or desk._sha(original['body']) != original['version']:
                    state = 'ERROR'
                elif state == 'PASS' and original['exit_code'] != 0:
                    state = 'ERROR'
                try:
                    if receipt['version'] != _version(json.loads(row['paths_json']), row['test_module']):
                        state = 'STALE'
                except (ValueError, OSError):
                    state = 'STALE'
            result.append(dict(id=row['id'], task=row['task'], title=row['title'], state=state,
                               test_module=row['test_module'], paths=json.loads(row['paths_json']),
                               receipt=dict(receipt) if receipt else None))
    return result


def task_verdict(task):
    task = _key(task)
    checks = requirements(task)
    accepted = bool(checks) and all(r['state'] == 'PASS' for r in checks)
    costs = usage(task)
    return _result('PASS' if accepted else 'UNVERIFIED', task=task, accepted=accepted, checks=checks,
                   scope='Declared files and tests only; informational, no execution authority', usage=costs,
                   accepted_task_costs=costs['buckets'][0]['known_costs'] if accepted and costs['complete_cost'] else None)


def record_usage(task, model, outcome, basis='UNKNOWN', input_tokens=None, output_tokens=None, cost=None, currency=''):
    task = _key(task)
    if basis not in {'PROVIDER_REPORTED', 'ESTIMATED', 'UNKNOWN'} or outcome not in {'SUCCEEDED', 'FAILED', 'CANCELLED'}:
        raise ValueError('INVALID_USAGE_PROVENANCE')
    for value in [input_tokens, output_tokens]:
        if value is not None and (type(value) is not int or not 0 <= value <= 10**12):
            raise ValueError('INVALID_TOKEN_COUNT')
    if cost is not None and (type(cost) not in {int, float} or not math.isfinite(cost) or not 0 <= cost <= 10**9 or not re.fullmatch('[A-Z]{3}', currency)):
        raise ValueError('INVALID_COST')
    if basis == 'UNKNOWN' and any(v is not None for v in [input_tokens, output_tokens, cost]):
        raise ValueError('UNKNOWN_USAGE_MUST_STAY_UNKNOWN')
    with _db(write=True) as db:
        if db.execute('SELECT COUNT(*) FROM wb_usage WHERE task=?', (task,)).fetchone()[0] >= 4096:
            raise ValueError('USAGE_STORAGE_LIMIT')
        db.execute('INSERT INTO wb_usage VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (_uid('attempt'), task, desk._scrub(model, 100), outcome, basis, input_tokens, output_tokens, cost, currency, desk._now()))
    return _result('USAGE_RECORDED')


def usage(task):
    with _db() as db:
        rows = db.execute('SELECT * FROM wb_usage WHERE task=? ORDER BY rowid', (task,)).fetchall()
    buckets = []
    for basis in ['PROVIDER_REPORTED', 'ESTIMATED', 'UNKNOWN']:
        matching = [r for r in rows if r['basis'] == basis]
        costs = {}
        for row in matching:
            if row['cost'] is not None:
                costs[row['currency']] = costs.get(row['currency'], 0) + row['cost']
        buckets.append(dict(basis=basis, attempts=len(matching), failed=sum(r['outcome'] != 'SUCCEEDED' for r in matching),
                            input_tokens=sum(r['input_tokens'] or 0 for r in matching) if matching and all(r['input_tokens'] is not None for r in matching) else None,
                            output_tokens=sum(r['output_tokens'] or 0 for r in matching) if matching and all(r['output_tokens'] is not None for r in matching) else None,
                            known_costs=costs, missing_costs=sum(r['cost'] is None for r in matching)))
    return dict(attempts=len(rows), models=list(dict.fromkeys(r['model'] for r in rows)), buckets=buckets,
                complete_cost=bool(rows) and all(r['cost'] is not None and r['basis'] == 'PROVIDER_REPORTED' for r in rows))


def _date(value):
    if not value:
        return ''
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (ValueError, TypeError):
        raise ValueError('UTC_DATE_REQUIRED') from None


def source_event(source_id, state, note, valid_at='', valid_until=''):
    if state not in {'CURRENT', 'CONTESTED', 'SUPERSEDED', 'STALE'} or not str(note).strip():
        raise ValueError('SOURCE_STATUS_AND_REASON_REQUIRED')
    valid_at, valid_until = _date(valid_at), _date(valid_until)
    if valid_at and valid_until and valid_until <= valid_at:
        raise ValueError('INVALID_VALIDITY_INTERVAL')
    with _db(write=True) as db:
        if not db.execute('SELECT 1 FROM sources WHERE id=?', (source_id,)).fetchone():
            raise ValueError('SOURCE_NOT_FOUND')
        if db.execute('SELECT COUNT(*) FROM wb_source_events').fetchone()[0] >= 8192:
            raise ValueError('SOURCE_HISTORY_STORAGE_LIMIT')
        previous_state = desk.source_freshness(source_id)
        db.execute('INSERT INTO wb_source_events(source_id,state,note,valid_at,valid_until,observed_at) VALUES(?,?,?,?,?,?)',
                   (source_id, state, desk._scrub(note, 1000), valid_at, valid_until, desk._now()))
        # A disputed source cannot continue advertising a verified method.
        # Existing bound receipts are retained; rechecking a source does not
        # silently re-verify an old conclusion.
        if previous_state not in {'CURRENT', 'UNREVIEWED'} or desk.source_freshness(source_id) != 'CURRENT':
            db.execute("UPDATE methods SET status='PROPOSED' WHERE source_id=? AND status='VERIFIED'", (source_id,))
    return _result('SOURCE_STATUS_RECORDED')


def source_states():
    with _db() as db:
        sources = db.execute('SELECT id,title,created_at FROM sources ORDER BY rowid DESC LIMIT 96').fetchall()
        result = []
        for source in sources:
            history = [dict(r) for r in db.execute('SELECT state,note,valid_at,valid_until,observed_at FROM wb_source_events WHERE source_id=? ORDER BY id DESC LIMIT 32', (source['id'],))]
            last = history[0] if history else {}
            state = desk.source_freshness(source['id'])
            count = db.execute('SELECT COUNT(*) FROM wb_source_events WHERE source_id=?', (source['id'],)).fetchone()[0]
            result.append(dict(source, state=state, history=history, history_count=count, history_truncated=count > len(history)))
    return result


def preflight_skill(path, session):
    """Bounded static inspection, with omissions, never a safety certificate."""
    raw = str(path or '').strip()
    if not raw or '://' in raw or raw.startswith(('\\\\', '//')) or '..' in Path(raw).parts:
        raise ValueError('LOCAL_SKILL_DIRECTORY_REQUIRED')
    candidate = Path(raw).absolute()
    for part in reversed([candidate, *candidate.parents]):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('LINKED_SKILL_DIRECTORY_REJECTED')
    root = candidate.resolve(strict=True)
    if not root.is_dir() or not (root / 'SKILL.md').is_file():
        raise ValueError('SKILL_DIRECTORY_REQUIRED')
    from backend import research_lab
    inspected, findings, omitted = [], [], []
    total = 0
    queue = [root]
    visited = 0
    while queue and visited < 64 and len(inspected) < 64 and total < MAX_BODY:
        folder = queue.pop(0)
        visited += 1
        if folder.is_symlink() or (hasattr(folder, 'is_junction') and folder.is_junction()):
            omitted.append('Linked directory')
            continue
        # Limit enumeration as well as reads; huge libraries are incomplete.
        try:
            entries = folder.iterdir()
            # Force only the directory opening here, not an unbounded list.
            first = next(entries, None)
        except OSError:
            omitted.append('Unreadable directory')
            continue
        from itertools import chain
        for index, item in enumerate(chain([first] if first is not None else [], entries)):
            if index >= 128 or len(inspected) >= 64 or total >= MAX_BODY:
                omitted.append('Entry or byte limit')
                break
            rel = item.relative_to(root).as_posix()
            if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                omitted.append('Linked entry')
            elif item.is_dir():
                if len(queue) < 128 and len(item.relative_to(root).parts) <= 4 and not item.name.startswith('.') and item.name != 'node_modules':
                    queue.append(item)
                else:
                    omitted.append('Directory excluded')
            elif item.suffix.lower() in {'.md', '.txt', '.py', '.sh', '.ps1', '.js', '.ts', '.json', '.toml', '.yaml', '.yml', '.cmd', '.bat'} or item.name.upper().startswith('LICENSE'):
                if _SENSITIVE_KEY.search(item.name) or item.name.startswith('.'):
                    omitted.append('Private entry excluded')
                    continue
                try:
                    _, data = research_lab._read(str(item), min(128*1024, MAX_BODY-total))
                    text = data.decode('utf-8', errors='strict')
                except (ValueError, OSError, UnicodeError):
                    omitted.append('Unreadable or oversized entry')
                    continue
                total += len(data)
                inspected.append(dict(path=rel, version=hashlib.sha256(data).hexdigest(), bytes=len(data)))
                for pattern, label in [(r'(?im)^\s*(?:allowed-tools|tools|permissions)\s*:', 'Declared tool access'),
                                       (r'(?i)subprocess|os\.system|\bexec\(|\beval\(|shell\s*=|\bcurl\b|\bwget\b', 'Process or network capability'),
                                       (r'(?i)ignore (?:all |previous )?instructions|disable.{0,30}(?:sandbox|approval)|bypass.{0,30}approval', 'Authority-changing instruction'),
                                       (r'(?i)api[_-]?key|credentials|\.env\b|private.key', 'Credential reference')]:
                    for match in list(re.finditer(pattern, text))[:8]:
                        findings.append(dict(path=rel, line=text.count('\n', 0, match.start())+1, category=label))
            else:
                omitted.append('Uninspected file type')
    if queue:
        omitted.append('Pending directories')
    report = dict(status='INCOMPLETE' if omitted else 'STATIC_REVIEW', inspected=inspected, findings=findings,
                  omissions=dict((reason, omitted.count(reason)) for reason in set(omitted)),
                  license_present=any(Path(x['path']).name.upper().startswith('LICENSE') for x in inspected),
                  behavior_verified=False, authority='NONE', executed=False,
                  scope='Static pattern review only; absence of findings is not proof of safe behavior')
    saved = observe(session, str(root), json.dumps(report, ensure_ascii=False, indent=2), 'Skill preflight')
    return _result(report['status'], report=report, observation_id=saved['observation_id'], session=session)


def snapshot(batch_id='', task=''):
    with _db() as db:
        _recover(db)
        batches = [dict(r, **_counts(db, r['id'])) for r in db.execute('SELECT * FROM wb_batches ORDER BY rowid DESC LIMIT 32')]
        selected = batch_id or (batches[0]['id'] if batches else '')
        # All 512 source statuses fit; bodies stay out of the snapshot.
        items = [dict(r) for r in db.execute('SELECT id,position,url,state,note,observation_id FROM wb_items WHERE batch_id=? ORDER BY position LIMIT 512', (selected,))]
        observations = [dict(r) for r in db.execute('SELECT id,session,source,title,exit_code,redacted,created_at FROM wb_observations ORDER BY rowid DESC LIMIT 32')]
        tasks = [r[0] for r in db.execute('SELECT task FROM wb_requirements UNION SELECT task FROM wb_usage ORDER BY task LIMIT 128')]
    return _result('READY', batches=batches, batch_id=selected, items=items, observations=observations,
                   tasks=tasks, requirements=requirements(task), sources=source_states(), usage=usage(task) if task else None,
                   view_limits=dict(batches=32, observations=32, requirements=64, source_cards=96, source_history=32),
                   execution='AGENT_DRIVEN_EXPLICIT_CLAIMS', automatic_execution=False)


_OPERATIONS = {
    'snapshot': snapshot, 'create_batch': create_batch, 'control_batch': control_batch,
    'claim_source': claim_source, 'renew_source': renew_source, 'complete_source': complete_source,
    'retry_source': retry_source, 'observe': observe, 'observation': observation,
    'add_requirement': add_requirement, 'verdict': task_verdict, 'usage': usage,
    'record_usage': record_usage, 'source_event': source_event, 'preflight_skill': preflight_skill,
}


def command(operation, payload):
    """Finite data-only surface. Test execution is deliberately CLI-only."""
    if operation not in _OPERATIONS or not isinstance(payload, dict):
        raise ValueError('UNKNOWN_WORKBENCH_OPERATION')
    return _OPERATIONS[operation](**payload)
