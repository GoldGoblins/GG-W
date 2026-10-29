"""One private, cancellable recovery reveal through the existing chat gate.

Only request ids and fixed state codes return to public callers. Passwords live
only in the existing private approval ticket/callback; words are emitted solely
on the dedicated local Qt signal after that exact operation is approved.
"""
from dataclasses import dataclass
import json
import re
import threading
import time
import uuid
import weakref

from PySide6.QtCore import QCoreApplication,QMetaObject,QObject,QThread,QTimer,Qt

_lock=threading.RLock()
_records=weakref.WeakKeyDictionary()
MAX_SECONDS=600
MAX_RECORDS=8


@dataclass(repr=False)
class _Record:
    request_id:str
    owner:str
    host_ref:object=None
    ticket_id:str=''
    active:bool=True
    expires_at:float=0
    monotonic_deadline:float=0
    timer:object=None
    state:str='WAITING'
    destroyed_handler:object=None


def _public(request_id='',state='ERROR',error=''):
    body={'request_id':request_id,'state':state}
    if error:body['error']=error
    return json.dumps(body,separators=(',',':'))


def _host(record):
    value=record.host_ref() if record.host_ref else None
    if value is None or getattr(value,'_shutdown_in_progress',False):return None
    try:
        from shiboken6 import isValid
        if not isValid(value):return None
    except (ImportError,RuntimeError,TypeError):return None
    return value


def _valid(record):
    return (record.active and _host(record) is not None and time.time()<record.expires_at
            and time.monotonic()<record.monotonic_deadline)


def _dispose_timer(timer):
    if timer is None:return
    try:
        if timer.thread()==QThread.currentThread():timer.stop()
        else:QMetaObject.invokeMethod(timer,'stop',Qt.QueuedConnection)
        timer.deleteLater()
    except RuntimeError:pass  # Parent destruction already removed the timer.


def _discard(record):
    """Invalidate before the authority layer/capture guard can be released."""
    from backend import sensitive_ui_guard,wallet_approval
    with _lock:
        record.active=False;record.state='CANCELLED'
        host=record.host_ref() if record.host_ref else None
        if host is not None and _records.get(host) is record:_records.pop(host,None)
        identifier=record.ticket_id;record.ticket_id=''
        timer=record.timer;record.timer=None
        destroyed=record.destroyed_handler;record.destroyed_handler=None
    try:
        if identifier:wallet_approval.cancel(identifier)
    except Exception:pass
    finally:
        try:sensitive_ui_guard.leave(record.owner)
        except Exception:pass  # A failed interlock remains fail-closed.
        _dispose_timer(timer)
        if host is not None and destroyed is not None:
            try:host.destroyed.disconnect(destroyed)
            except (RuntimeError,TypeError):pass


def _expired(record):
    _discard(record)


def request(host,pubkey,password):
    """Stage on Qt's thread; never decrypt or expose words in the response."""
    from backend import wallet_approval
    record=None;private=None
    try:
        if not isinstance(host,QObject) or getattr(host,'_shutdown_in_progress',False):
            raise ValueError('WALLET_RECOVERY_CLOSED')
        if QCoreApplication.instance() is None or host.thread()!=QThread.currentThread():
            raise ValueError('WALLET_RECOVERY_UI_THREAD')
        handler=getattr(host,'_wallet_action_approval_handler',None)
        if not callable(handler):raise ValueError('WALLET_APPROVAL_REQUIRED')
        if not isinstance(pubkey,str) or not isinstance(password,str) or not 12<=len(password)<=256:
            raise ValueError('WALLET_RECOVERY_INPUT')
        from backend.crypto_pump_accounts import pubkey_bytes
        pubkey_bytes(pubkey)
        runtime=host._omni_runtime()
        with runtime._lock:
            if runtime._closed or runtime._pending is not None or runtime._active:
                raise ValueError('WALLET_OPERATION_BUSY')
        with _lock:
            if host in _records and _records[host].active:raise ValueError('WALLET_RECOVERY_BUSY')
            if len(_records)>=MAX_RECORDS:raise ValueError('WALLET_RECOVERY_BUSY')
            identifier=uuid.uuid4().hex
            record=_Record(identifier,'wallet-recovery:'+identifier)
            record.host_ref=weakref.ref(host,lambda ignored,r=record:_discard(r))
            record.monotonic_deadline=time.monotonic()+MAX_SECONDS
            record.expires_at=time.time()+MAX_SECONDS
            _records[host]=record
        private={'pubkey':pubkey,'password':password}
        def reveal():
            from backend import sensitive_ui_guard,wallet_mnemonic
            secret=None;raw=None;guard_entered=False
            try:
                with _lock:
                    if not _valid(record):
                        _discard(record)
                        return None
                secret=wallet_mnemonic.reveal(private['pubkey'],private['password'])
                words=secret.get('words') if isinstance(secret,dict) else None
                if (not isinstance(words,list) or len(words) not in (12,24)
                        or any(not isinstance(w,str) or not re.fullmatch(r'[a-z]{2,16}',w) for w in words)
                        or secret.get('pubkey')!=pubkey or secret.get('address')!=pubkey
                        or secret.get('word_count')!=len(words)):
                    raise ValueError('WALLET_RECOVERY_RESULT')
                # Enter may stop a capture worker. Do not hold the request lock
                # through that work; cancellation is rechecked before emission.
                sensitive_ui_guard.enter(record.owner);guard_entered=True
                wallet_approval.require_operation('reveal_mnemonic',private,'credentials.read')
                with _lock:
                    if not _valid(record):
                        _discard(record)
                        return None
                    target=_host(record)
                    payload={'request_id':record.request_id,'state':'REVEALED','words':list(words),
                             'address':pubkey,'pubkey':pubkey,'word_count':len(words),
                             'chain_id':str(secret.get('chain_id',''))[:80],
                             'derivation_path':str(secret.get('derivation_path',''))[:80]}
                    raw=json.dumps(payload,separators=(',',':'))
                    target.walletMnemonicSecretReady.emit(raw)
                    record.state='REVEALED'
                # Keep the capture guard until the local widget clears/closes.
                guard_entered=False
            except Exception:
                with _lock:
                    if _valid(record):
                        try:_host(record).walletMnemonicSecretReady.emit(_public(record.request_id,'ERROR','WALLET_MNEMONIC_REVEAL_FAILED'))
                        except Exception:pass
                _discard(record)
            finally:
                private.clear()
                if isinstance(secret,dict):
                    if isinstance(secret.get('words'),list):secret['words'].clear()
                    secret.clear()
                raw=None;secret=None
                if guard_entered:
                    try:sensitive_ui_guard.leave(record.owner)
                    except Exception:pass
            return None
        ticket=wallet_approval.stage('reveal_mnemonic',private,reveal)
        with _lock:
            record.ticket_id=ticket
            if not _valid(record):raise ValueError('WALLET_RECOVERY_CLOSED')
        info=wallet_approval.request(ticket)
        record.expires_at=min(record.expires_at,float(info['expires_at']))
        timer=QTimer(host);timer.setSingleShot(True);timer.timeout.connect(lambda r=record:_expired(r))
        record.timer=timer;timer.start(max(1,min(MAX_SECONDS*1000,int((record.expires_at-time.time())*1000)+1)))
        record.destroyed_handler=lambda *ignored,r=record:_discard(r)
        host.destroyed.connect(record.destroyed_handler)
        handler(ticket)
        notice=getattr(host,'_wallet_operation_notice',None)
        if callable(notice):notice('reveal_mnemonic','approval_required','WALLET_APPROVAL_REQUIRED')
        return _public(record.request_id,'approval_required')
    except Exception as error:
        if record is not None:_discard(record)
        if private is not None:private.clear()
        code=error.args[0] if isinstance(error,ValueError) and error.args and isinstance(error.args[0],str) else ''
        if code not in {'WALLET_APPROVAL_REQUIRED','WALLET_OPERATION_BUSY','WALLET_RECOVERY_BUSY',
                        'WALLET_RECOVERY_CLOSED','WALLET_RECOVERY_UI_THREAD','WALLET_RECOVERY_INPUT'}:
            code='WALLET_MNEMONIC_REVEAL_FAILED'
        return _public(error=code)
    finally:
        password=None


def cancel(host,request_id):
    with _lock:record=_records.get(host)
    if record is not None and isinstance(request_id,str) and request_id==record.request_id:
        _discard(record)
        return _public(request_id,'CANCELLED')
    return _public(state='CANCELLED')


def cancel_all(host):
    with _lock:record=_records.get(host)
    if record is not None:_discard(record)
