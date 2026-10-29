"""One bounded background lane for Research Workbench database/file reads."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
import uuid

from backend import research_workbench

_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gg-research-desk')
_RESULTS = OrderedDict()
_PENDING = set()
MAX_PENDING = 8


def submit(operation, payload):
    if len(json.dumps(payload, ensure_ascii=True)) > 1024 * 1024:
        return {'status': 'ERROR', 'reason': 'REQUEST_SIZE_LIMIT'}
    # The UI cannot claim work, submit arbitrary receipts, or execute tests.
    if operation not in {'snapshot', 'create_batch', 'control_batch', 'retry_source', 'observation', 'source_event'}:
        return {'status': 'ERROR', 'reason': 'UI_OPERATION_NOT_AVAILABLE'}
    with _LOCK:
        if len(_PENDING) >= MAX_PENDING:
            return {'status': 'BUSY'}
        ticket = uuid.uuid4().hex
        _PENDING.add(ticket)
    try:
        _POOL.submit(_execute, ticket, operation, payload)
    except RuntimeError:
        with _LOCK:
            _PENDING.discard(ticket)
        return {'status': 'ERROR', 'reason': 'SERVICE_STOPPED'}
    return {'status': 'QUEUED', 'ticket': ticket}


def _execute(ticket, operation, payload):
    try:
        result = research_workbench.command(operation, payload)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{1,100}', str(exc)) else type(exc).__name__
        result = {'status': 'ERROR', 'reason': reason}
    with _LOCK:
        _PENDING.discard(ticket)
        _RESULTS[ticket] = result
        while len(_RESULTS) > 32:
            _RESULTS.popitem(last=False)


def result(ticket):
    with _LOCK:
        if ticket in _PENDING:
            return {'status': 'RUNNING', 'ticket': ticket}
        if ticket not in _RESULTS:
            return {'status': 'ERROR', 'reason': 'REQUEST_EXPIRED'}
        return {'status': 'COMPLETE', 'result': _RESULTS[ticket]}
