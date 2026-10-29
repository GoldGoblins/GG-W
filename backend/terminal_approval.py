"""Human terminal adapter for the existing exact, one-shot wallet gate.

Only the public operation summary reaches ``confirm``. Secret arguments and the
callback stay in wallet_approval's RAM ticket. Each operation has a separate
private mandate store; desktop runtime task pointers are never replaced.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import unicodedata
import uuid

from backend.application_paths import STATE_ROOT
from backend import live_mandate_store as mandates
from backend import task_scoped_action_grant as grants
from backend import wallet_approval as wallet

_lock = threading.Lock()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _summary(value):
    # Public labels and selected paths may contain terminal control characters.
    return ' '.join(''.join(('<U+%04X>' % ord(c)) if unicodedata.category(c) in {'Cc', 'Cf', 'Cs'}
                            and not c.isspace() else c for c in str(value)).split())[:4096]


def execute(name, args, callback, confirm):
    """Execute one exact wallet operation after literal human confirmation.

    ``confirm(public_summary: str) -> bool`` must be the caller's interactive
    terminal prompt, requiring an explicit ja/yes. There is no automatic approval
    flag, reusable ticket, or generic grant. A missing/nonboolean answer rejects.
    The function is synchronous: caller ContextVars (e.g. unlocked vault session)
    remain on the same worker through the approved callback.
    """
    if not callable(confirm) or not callable(callback):
        raise ValueError('TERMINAL_APPROVAL_REQUIRED')
    if not _lock.acquire(blocking=False):
        raise ValueError('TERMINAL_APPROVAL_BUSY')
    identifier = ''; store = None; capture = ''; scope = ''
    try:
        identifier = wallet.stage(name, args, callback)
        request = wallet.request(identifier)
        context = request['context']
        nonce = uuid.uuid4().hex
        # Only public descriptors/integrity material enter the durable store.
        public = {'schema': 'gg.terminal-wallet-request.v1', 'nonce': nonce,
                  'operation': request['name'], 'summary': _summary(request['summary']),
                  'target': context, 'allowed_hosts': request['allowed_hosts'],
                  'expires_at': request['expires_at']}
        capture = _digest(public)
        ready = {'risk_class': 'RED', 'operation': request['name'], 'target': context,
                 'allowed_hosts': request['allowed_hosts'], 'expires_at': request['expires_at']}
        scope = _digest(ready)
        pending = {'pending_id': 'terminal-' + nonce, 'request_capture_sha256': capture,
            'approval_scope_revision': scope,
            'action_intent': {'capability_human_id': 'wallet.' + request['name'],
                'target_object_id': context['object_id'], 'target_source_revision': context['sha256'],
                'binding_sha256': _digest({'request': capture, 'scope': scope, 'target': context})},
            'mandate_result': {'task_id': 'terminal-wallet-' + nonce,
                'mandate_requirement': 'EXPLICIT_REQUIRED',
                'approval_request': {'origin_id': 'terminal-' + nonce,
                    'task_id': 'terminal-wallet-' + nonce, 'approval_scope': {'ready_core': ready}}}}
        store = mandates.MandateStore(Path(STATE_ROOT) / 'terminal-approvals' / nonce)
        store.initialize(); mandates.put_pending(store, pending)
        if confirm(public['summary']) is not True:
            mandates.reject(store, request_capture_sha256=capture, approval_scope_revision=scope)
            raise ValueError('TERMINAL_APPROVAL_REJECTED')
        # Human input authorizes exactly the previously displayed operation.
        # Changed files, state roots, endpoint, message or expiry fail here.
        if wallet.context(identifier) != context:
            raise ValueError('WALLET_OPERATION_CHANGED')
        assertion = _digest({'schema': 'gg.terminal-human-decision.v1', 'request': capture,
                             'scope': scope, 'decision': 'APPROVE', 'approver': 'human:terminal'})
        receipt = {'schema': 'gg.mandate-evaluation-result.v1', 'request_capture_sha256': capture,
            'approval_scope_revision': scope, 'current_approval_scope_revision': scope,
            'mandate_assertion_sha256': assertion, 'result': 'MANDATE_VALID',
            'reason_code': 'APPROVAL_SCOPE_MATCH'}
        record = mandates.approve(store, request_capture_sha256=capture, approval_scope_revision=scope,
            approver_id='human:terminal', mandate_assertion_sha256=assertion, evaluation_receipt=receipt)
        grants.publish_runtime_scope(grants.issue_from_approved_record(record), store_root=store.root,
                                     allowed_hosts=request['allowed_hosts'])
        wallet.bind_approval(identifier, record, store_root=store.root)
        return wallet.execute(identifier)
    finally:
        try:
            if identifier:
                wallet.cancel(identifier)
            # Also close a grant if binding/execution failed after approval.
            if store is not None and capture:
                record = store.get(capture)
                if record and record['status'] == 'PENDING':
                    mandates.reject(store, request_capture_sha256=capture, approval_scope_revision=scope)
                elif record and record['status'] == 'APPROVED':
                    mandates.consume(store, request_capture_sha256=capture, approval_scope_revision=scope)
        finally:
            _lock.release()
