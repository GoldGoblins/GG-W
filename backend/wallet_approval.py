"""Exact wallet operations approved through the existing ordinary-chat gate.

Only public operation descriptors reach the mandate store. Passwords and the
original callback live in a bounded, process-local ticket until ja/nej; neither
is forwarded to a model. A generic active task never authorizes a wallet ticket.
"""
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from urllib.parse import urlsplit

from backend import omni_assets as store, task_scoped_action_grant as grants
from backend.platform_files import is_link, secure_open

OPERATIONS = frozenset({'create_wallet', 'backup_wallet', 'restore_wallet', 'send_transfer',
                        'reveal_mnemonic', 'export_mnemonic'})
_EFFECTS = {
    'create_wallet': ('credentials.write',),
    'backup_wallet': ('credentials.read', 'filesystem.write'),
    'restore_wallet': ('credentials.write',),
    'send_transfer': ('crypto.solana.transfer', 'credentials.read', 'network'),
    'reveal_mnemonic': ('credentials.read',),
    'export_mnemonic': ('credentials.read', 'filesystem.write'),
}
_lock = threading.RLock()
_current = ContextVar('gg_wallet_operation', default=None)
_tickets = {}


@dataclass(repr=False)
class _Ticket:
    identifier: str
    name: str
    descriptor: dict
    args: dict
    callback: object
    expires_at: float
    state: str = 'WAITING'
    approval: dict | None = None


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def local_path(value):
    """Reject network paths before resolve/stat can initiate Windows SMB I/O."""
    from backend.wallet_vault import _backup_path
    path = _backup_path(value)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')) or path.drive.startswith('\\\\'):
        raise ValueError('WALLET_BACKUP_PATH')
    if any(is_link(p) for p in (path, *path.parents)):
        raise ValueError('WALLET_BACKUP_PATH')
    return path.resolve()


def read_public_file(path):
    """Read bounded ciphertext only, refusing links and reparse points."""
    with os.fdopen(secure_open(path, os.O_RDONLY), 'rb') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('WALLET_BACKUP_PATH')
    return raw


def _descriptor(name, args):
    from backend import wallet_vault as vault
    if name not in OPERATIONS or not isinstance(args, dict):
        raise ValueError('WALLET_OPERATION_INVALID')
    body = {'schema': 'gg.wallet-operation.v1', 'operation': name,
        'chain_id': vault.SOL, 'state_root': str(store.ROOT.resolve())}
    if name == 'create_wallet':
        body['label'] = store.text(args.get('label', ''), 64)
        if args.get('mnemonic_session'):
            from backend import wallet_mnemonic
            body['mnemonic']=wallet_mnemonic.descriptor(args['mnemonic_session'],body['label'])
    elif name in {'reveal_mnemonic','export_mnemonic'}:
        from backend import wallet_mnemonic
        pubkey=str(args['pubkey']);source=wallet_mnemonic.recovery_path(pubkey)
        encoded=read_public_file(source)
        wallet_mnemonic.public_recovery_metadata(encoded,pubkey)
        body.update(pubkey=pubkey,derivation_path=wallet_mnemonic.DERIVATION_PATH,
            recovery_sha256=hashlib.sha256(encoded).hexdigest())
        if name=='export_mnemonic':
            destination=local_path(args['path'])
            if destination.is_relative_to(store.PROJECT) or destination.exists():
                raise ValueError('WALLET_BACKUP_PATH')
            body.update(path=str(destination),expected_absent=True)
    elif name == 'backup_wallet':
        pubkey = str(args['pubkey'])
        source = vault._path(pubkey)
        destination = local_path(args['path'])
        if destination.is_relative_to(store.PROJECT):
            raise ValueError('WALLET_BACKUP_PATH')
        if destination.exists():
            raise ValueError('WALLET_BACKUP_ALREADY_EXISTS')
        body.update(pubkey=pubkey, path=str(destination), expected_absent=True,
            vault_sha256=hashlib.sha256(read_public_file(source)).hexdigest())
    elif name == 'restore_wallet':
        path = local_path(args['path'])
        raw = read_public_file(path)
        # The encrypted bytes, path and label are the approved input. Do not
        # decrypt here, or persist a password/password-derived commitment.
        body.update(path=str(path), ciphertext_sha256=hashlib.sha256(raw).hexdigest(),
            label=store.text(args.get('label', ''), 64))
    else:
        from backend import solana_transfers
        identifier = str(args['id'])
        draft = solana_transfers.snapshot(identifier)
        if not draft:
            raise ValueError('WALLET_REVIEW_MISMATCH')
        endpoint = store.network(vault.SOL)['endpoint']
        body.update(id=identifier, review_digest=str(args['review_digest']),
            draft=draft['body'], endpoint=endpoint, rpc_host=urlsplit(endpoint).hostname or '')
    return body


def stage(name, args, callback):
    """Create a fresh one-shot request; args/callback never leave this module."""
    descriptor = _descriptor(name, args)
    if not callable(callback):
        raise ValueError('WALLET_OPERATION_INVALID')
    expiry = min(time.time() + 600, float(descriptor.get('draft', {}).get('expires_at', time.time() + 600)))
    if expiry <= time.time():
        raise ValueError('WALLET_DRAFT_EXPIRED')
    ticket = _Ticket(uuid.uuid4().hex, name, descriptor, dict(args), callback, expiry)
    with _lock:
        if len(_tickets) >= 8:
            raise ValueError('WALLET_PENDING_OPERATION_LIMIT')
        _tickets[ticket.identifier] = ticket
    return ticket.identifier


def _ticket(identifier):
    with _lock:
        ticket = _tickets.get(identifier)
        if ticket is None:
            raise ValueError('WALLET_APPROVAL_REQUIRED')
        return ticket


def context(identifier):
    ticket = _ticket(identifier)
    if time.time() > ticket.expires_at:
        cancel(identifier)
        raise ValueError('WALLET_DRAFT_EXPIRED')
    descriptor = _descriptor(ticket.name, ticket.args)
    if descriptor != ticket.descriptor:
        raise ValueError('WALLET_OPERATION_CHANGED')
    return {'object_id': 'wallet.operation.' + ticket.name + '.' + identifier,
        'sha256': _sha({'ticket': identifier, 'descriptor': descriptor}),
        'source_path': '(wallet-operation)', 'provenance': 'EXACT_WALLET_OPERATION'}


def request(identifier):
    """Public-only fields used by the existing Bridge approval UI."""
    ticket = _ticket(identifier)
    body = ticket.descriptor
    if ticket.name == 'create_wallet':
        if body.get('mnemonic'):
            public=body['mnemonic']
            mode='AI-assisterat · endast förslag, nytt godkännande per överföring' if public['flow']=='AI_ASSISTED' else 'Självstyrt konto'
            summary=('Registrera din Solana-wallet '+public['address']+' · '+mode+' · '+public['purpose']+' · '+public['method']
                +' · '+str(public['word_count'])+' ord · '+public['derivation_path']
                +('. Endast offentlig bevakning sparas; nyckeln förvaras av dig.' if public['method']=='PAPER'
                  else '. Lokal nyckel och din lösenordskrypterade, flyttbara återställningsfras sparas.'))
        else:summary = 'Skapa en ny krypterad GG-wallet på Solana: ' + (body['label'] or 'GG · Solana')
    elif ticket.name=='reveal_mnemonic':
        summary='Visa återställningsfrasen endast i din lokala walletvy för Solana-adressen '+body['pubkey']+'. Frasen skickas inte till chatten.'
    elif ticket.name=='export_mnemonic':
        summary='Spara din lösenordskrypterade återställningsfras för '+body['pubkey']+' till '+body['path']+'.'
    elif ticket.name == 'backup_wallet':
        summary = 'Spara krypterad backup av wallet ' + body['pubkey'] + ' till ' + body['path']
    elif ticket.name == 'restore_wallet':
        summary = 'Återställ den valda krypterade walletbackupen: ' + body['path']
    else:
        draft = body['draft']
        summary = ('Signera och skicka ' + draft['amount'] + ' ' + draft['symbol']
            + ' på Solana mainnet från ' + draft.get('from', '') + ' till ' + draft['to']
            + '. Mint: ' + (draft.get('mint') or 'SOL native') + '. Avgift och kontohyra: '
            + draft['cost_sol'] + ' SOL.')
    return {'name': ticket.name, 'summary': summary, 'context': context(identifier),
        'expires_at': ticket.expires_at,
        'allowed_hosts': [body['rpc_host']] if body.get('rpc_host') else []}


def bind_approval(identifier, record, *, store_root):
    """Bind the just-approved store record to the exact queued operation."""
    from backend import live_mandate_store
    record = live_mandate_store.validate_record(record)
    current = context(identifier)
    if (record['status'] != 'APPROVED'
            or record['target_object_id'] != current['object_id']
            or record['target_source_revision'] != current['sha256']):
        raise ValueError('WALLET_OPERATION_CHANGED')
    ticket = _ticket(identifier)
    with _lock:
        if ticket.state != 'WAITING':
            raise ValueError('WALLET_ALREADY_SUBMITTED')
        ticket.approval = {key: record[key] for key in ('request_capture_sha256',
            'approval_scope_revision', 'task_id', 'target_object_id', 'target_source_revision')}
        ticket.approval['store_root'] = str(store_root)
        ticket.state = 'APPROVED'


def require_operation(name, args, effect, host=''):
    """Fail closed unless this effect belongs to the exact approved callback."""
    identifier = _current.get()
    if not identifier:
        raise ValueError('WALLET_APPROVAL_REQUIRED')
    ticket = _ticket(identifier)
    if ticket.state != 'EXECUTING' or ticket.name != name or effect not in _EFFECTS[name]:
        raise ValueError('WALLET_APPROVAL_REQUIRED')
    current = _descriptor(name, args)
    if current != ticket.descriptor:
        raise ValueError('WALLET_OPERATION_CHANGED')
    if (name == 'restore_wallet' and args.get('_ciphertext_sha256') is not None
            and args['_ciphertext_sha256'] != current['ciphertext_sha256']):
        raise ValueError('WALLET_OPERATION_CHANGED')
    target = context(identifier)
    approval = ticket.approval or {}
    expected_host = current.get('rpc_host', '')
    if host and host.lower() != expected_host.lower():
        raise ValueError('WALLET_OPERATION_CHANGED')
    token = grants.runtime_authorize_effect(effect, store_root=Path(approval['store_root']),
        host=expected_host or host)
    if (token is None or token['task_id'] != approval.get('task_id')
            or token['target_object_id'] != target['object_id']
            or token['target_source_revision'] != target['sha256']):
        raise ValueError('WALLET_APPROVAL_REQUIRED')
    return token


def _finish(ticket):
    from backend import live_mandate_store
    approval = ticket.approval
    try:
        if approval:
            mandate_store = live_mandate_store.MandateStore(Path(approval['store_root']))
            record = mandate_store.get(approval['request_capture_sha256'])
            if (record and record['status'] == 'APPROVED'
                    and record['target_object_id'] == approval['target_object_id']
                    and record['target_source_revision'] == approval['target_source_revision']):
                live_mandate_store.consume(mandate_store,
                    request_capture_sha256=approval['request_capture_sha256'],
                    approval_scope_revision=approval['approval_scope_revision'])
    finally:
        mnemonic_session=ticket.args.get('mnemonic_session') if ticket.name=='create_wallet' else None
        with _lock:
            ticket.args.clear()
            ticket.callback = None
            ticket.approval = None
            ticket.state = 'FINISHED'
            _tickets.pop(ticket.identifier, None)
        if mnemonic_session:
            from backend import wallet_mnemonic
            wallet_mnemonic.cancel(mnemonic_session)


def execute(identifier):
    ticket = _ticket(identifier)
    with _lock:
        if ticket.state != 'APPROVED':
            raise ValueError('WALLET_APPROVAL_REQUIRED')
        ticket.state = 'EXECUTING'
    token = _current.set(identifier)
    try:
        # Revalidate before invoking the callback, including revocation or a
        # changed runtime pointer while the approved operation was queued.
        require_operation(ticket.name, ticket.args, _EFFECTS[ticket.name][0])
        return ticket.callback()
    finally:
        _current.reset(token)
        _finish(ticket)


def cancel(identifier):
    with _lock:
        ticket = _tickets.get(identifier)
        if ticket is None:
            return
        if ticket.state == 'EXECUTING':
            # Invalidate the next effect check without deleting the active
            # callback's input until its finally block clears it.
            ticket.state = 'CANCELLED'
            return
    _finish(ticket)


def cancel_all():
    with _lock:
        identifiers = list(_tickets)
    for identifier in identifiers:
        cancel(identifier)
    from backend import wallet_mnemonic
    wallet_mnemonic.cancel_all()


def expire(identifier):
    with _lock:
        ticket = _tickets.get(identifier)
        expired = ticket is not None and time.time() >= ticket.expires_at
    if expired:
        cancel(identifier)
    return expired


def is_available(identifier):
    expire(identifier)
    with _lock:
        return identifier in _tickets
