"""Single bounded SITE background job; Qt polls immutable progress snapshots."""
from __future__ import annotations

from collections import OrderedDict
import threading
import uuid

from backend import web_surface

_LOCK = threading.RLock()
_JOBS = OrderedDict()
BUSY = {'RUNNING', 'CANCELLING'}


def start(kind: str, source: str = '') -> dict:
    mode = str(kind).upper()
    if mode not in {'TREE', 'SQL', 'HEALTH'}:
        return {'state': 'ERROR', 'reason': 'SITE_JOB_KIND_INVALID'}
    with _LOCK:
        if any(item['result']['state'] in BUSY for item in _JOBS.values()):
            return {'state': 'ERROR', 'reason': 'SITE_JOB_ALREADY_RUNNING'}
        while len(_JOBS) >= 8:
            _JOBS.popitem(last=False)
        job_id = uuid.uuid4().hex
        stop = threading.Event()
        entry = {'stop': stop, 'result': {'job_id': job_id, 'kind': mode, 'state': 'RUNNING',
                                         'phase': 'Preparing local operation', 'current': 0, 'total': 0}}
        _JOBS[job_id] = entry

    def progress(phase, current, total, extra):
        with _LOCK:
            entry['result'].update(phase=str(phase)[:40], current=int(current), total=int(total), detail=str(extra)[:200])

    def work():
        try:
            if mode == 'HEALTH':
                health = web_surface.php_runtime_health(refresh=True, cancelled=stop.is_set)
                result = {'state': 'DONE', 'health': health, 'summary': health['detail']}
            else:
                if mode == 'TREE':
                    summary = web_surface.import_site_tree(source, progress=progress, cancelled=stop.is_set)
                else:
                    from backend.site_database import import_sql_dump
                    summary = import_sql_dump(source, progress=progress, cancelled=stop.is_set)
                state = ('DONE' if summary.startswith('PASS') else 'PARTIAL' if summary.startswith('PARTIAL') else
                         'CANCELLED' if stop.is_set() else 'ERROR')
                result = {'state': state, 'summary': summary}
        except Exception:
            result = {'state': 'ERROR', 'summary': 'FAIL: SITE_JOB_FAILED'}
        with _LOCK:
            # Successful commit wins a cancellation that arrived after commit.
            # SQL PARTIAL must stay visible even when interruption was requested.
            if mode == 'HEALTH' and stop.is_set():
                result = {'state': 'CANCELLED', 'summary': 'Local health check cancelled'}
            entry['result'] = {**entry['result'], **result}

    thread = threading.Thread(target=work, name='gg-site-' + mode.lower(), daemon=True)
    entry['thread'] = thread
    thread.start()
    return {'job_id': job_id, 'kind': mode, 'state': 'RUNNING'}


def status(job_id: str = '') -> dict:
    with _LOCK:
        entry = _JOBS.get(str(job_id)) if job_id else next(reversed(_JOBS.values()), None)
        return dict(entry['result']) if entry else {'state': 'IDLE'}


def cancel(job_id: str = '') -> dict:
    with _LOCK:
        entry = _JOBS.get(str(job_id)) if job_id else next(reversed(_JOBS.values()), None)
        if entry and entry['result']['state'] in BUSY:
            entry['stop'].set()
            entry['result']['state'] = 'CANCELLING'
        return dict(entry['result']) if entry else {'state': 'IDLE'}


def cached_health() -> dict:
    with web_surface._PHP_HEALTH_LOCK:
        return dict(web_surface._PHP_HEALTH) if web_surface._PHP_HEALTH else {
            'status': 'NOT_CHECKED', 'detail': 'Check the local PHP runtime', 'rules_date': web_surface.PHP_FIXES_DATE}
