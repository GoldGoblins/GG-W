"""Portable local Solana VM. Real SVM execution; no cluster or network writes."""
from __future__ import annotations
import base64
import importlib
import json
import threading
import time
from backend import crypto_contract as C

_LOCK = threading.RLock()
_bank = None
_started = 0.0
_slot = 0
_accounts = set()
_signatures = {}
MAX_ACCOUNTS = 256


def available():
    try:
        return callable(getattr(importlib.import_module('solders.litesvm'),'LiteSVM',None))
    except (ImportError,OSError):
        return False


def active():
    with _LOCK:
        return _bank is not None


def status():
    return dict(running=active(), healthy=active(), owned=active(), available=available(),
                backend='litesvm', label='LOCAL VM ON' if active() else 'LOCAL VM OFF',
                rpc='in-process://litesvm', diagnostic='', persistent_accounts=True,
                hint='Lokal Solana VM. Konton sparas; ingen validator eller nätverkskonsensus.')


def _save():
    from solders.pubkey import Pubkey
    data = {key: json.loads(account.to_json()) for key in sorted(_accounts)
            if (account := _bank.get_account(Pubkey.from_string(key))) is not None and not account.executable}
    if len(json.dumps(data).encode('utf-8')) > 4*1024*1024:
        raise ValueError('CRYPTO_VM_STATE_LIMIT')
    C.write_state_json(C.ensure_state_dir()/'svm-accounts.json', {'schema': 1, 'accounts': data})


def start():
    global _bank, _slot, _started, _accounts, _signatures
    with _LOCK:
        if _bank is not None:
            return status()
        from solders.litesvm import LiteSVM
        from solders.account import Account
        from solders.pubkey import Pubkey
        candidate = LiteSVM().with_sigverify(True).with_blockhash_check(True).with_transaction_history(256)
        path = C.ensure_state_dir()/'svm-accounts.json'
        saved = C.read_state_json(path, max_bytes=4*1024*1024) if path.exists() else {'schema': 1, 'accounts': {}}
        if saved.get('schema') != 1 or not isinstance(saved.get('accounts'), dict) or len(saved['accounts']) > MAX_ACCOUNTS:
            raise ValueError('CRYPTO_VM_STATE_CORRUPT')
        for key, account in saved['accounts'].items():
            candidate.set_account(Pubkey.from_string(key), Account.from_json(json.dumps(account)))
        _accounts = set(saved['accounts'])
        _signatures = {}
        _bank, _started = candidate, time.monotonic()
        _slot = candidate.get_clock().slot
        return status()


def stop():
    global _bank
    with _LOCK:
        if _bank is not None:
            _save()
        _bank = None
        return status()


def rpc(method, params):
    """Bounded subset used by GG's local diagnostics. Unsupported is explicit."""
    global _slot
    with _LOCK:
        if _bank is None:
            return {'error': {'code': -32000, 'message': 'LAB_OFF'}}
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        from solders.transaction import VersionedTransaction
        from solders.transaction_metadata import FailedTransactionMetadata
        slot = _slot + int((time.monotonic()-_started)*2)
        _bank.warp_to_slot(slot)
        def context(value):
            return {'context': {'slot': slot}, 'value': value}
        try:
            if method == 'getHealth': result = 'ok'
            elif method == 'getVersion': result = {'solana-core': 'local-litesvm', 'feature-set': 0}
            elif method == 'getGenesisHash': result = 'LOCAL_VM_NO_CLUSTER_GENESIS'
            elif method in {'getSlot', 'getBlockHeight'}: result = slot
            elif method == 'getLatestBlockhash': result = context({'blockhash': str(_bank.latest_blockhash()), 'lastValidBlockHeight': slot+150})
            elif method == 'isBlockhashValid': result = context(str(params[0]) == str(_bank.latest_blockhash()))
            elif method == 'getBalance': result = context(_bank.get_balance(Pubkey.from_string(params[0])) or 0)
            elif method == 'getMinimumBalanceForRentExemption': result = _bank.minimum_balance_for_rent_exemption(int(params[0]))
            elif method == 'getTokenAccountsByOwner':
                owner=Pubkey.from_string(params[0]); program=Pubkey.from_string(params[1]['programId'])
                token_rows=[]
                for address,account in _bank.get_program_accounts(program):
                    data=account.data
                    if len(data)<165 or data[32:64] != bytes(owner): continue
                    mint=Pubkey.from_bytes(data[:32]); mint_account=_bank.get_account(mint)
                    if mint_account is None or mint_account.owner!=program or len(mint_account.data)<82: continue
                    decimals=mint_account.data[44]; amount=int.from_bytes(data[64:72],'little')
                    token_rows.append({'pubkey':str(address),'account':{'owner':str(program),'data':{'parsed':{'info':{'mint':str(mint),'owner':str(owner),
                        'tokenAmount':{'amount':str(amount),'decimals':decimals,'uiAmountString':C.format_units(amount,decimals)}}}}}})
                result = context(token_rows)
            elif method == 'getAccountInfo':
                account = _bank.get_account(Pubkey.from_string(params[0]))
                result = context(None if account is None else dict(lamports=account.lamports, owner=str(account.owner),
                    data=[base64.b64encode(account.data).decode(), 'base64'], executable=account.executable, rentEpoch=account.rent_epoch))
            elif method == 'requestAirdrop':
                address, amount = str(Pubkey.from_string(params[0])), params[1]
                if type(amount) is not int or not 0 < amount <= 1000*10**9 or len(_accounts | {address}) > MAX_ACCOUNTS:
                    raise ValueError('CRYPTO_VM_LIMIT')
                meta = _bank.airdrop(Pubkey.from_string(address), amount)
                if isinstance(meta, FailedTransactionMetadata):
                    raise ValueError('CRYPTO_VM_AIRDROP')
                result = str(meta.signature())
                _accounts.add(address)
                _signatures[result] = {'slot': slot, 'err': None, 'confirmationStatus': 'finalized', 'confirmations': None}
                _save()
                _bank.expire_blockhash()
            elif method in {'sendTransaction', 'simulateTransaction'}:
                encoded = params[0]
                if not isinstance(encoded, str) or len(encoded) > 1800:
                    raise ValueError('CRYPTO_VM_TX_SIZE')
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) > 1232:
                    raise ValueError('CRYPTO_VM_TX_SIZE')
                transaction = VersionedTransaction.from_bytes(raw)
                keys = {str(key) for key in transaction.message.account_keys}
                if len(_accounts | keys) > MAX_ACCOUNTS:
                    raise ValueError('CRYPTO_VM_LIMIT')
                if method == 'simulateTransaction':
                    meta = _bank.simulate_transaction(transaction)
                    failed = isinstance(meta, FailedTransactionMetadata)
                    info = meta.meta() if failed else meta.meta()
                    result = context({'err': str(meta.err()) if failed else None, 'logs': info.logs(), 'unitsConsumed': info.compute_units_consumed()})
                else:
                    meta = _bank.send_transaction(transaction)
                    if isinstance(meta, FailedTransactionMetadata):
                        return {'error': {'code': -32002, 'message': 'CRYPTO_VM_TRANSACTION_FAILED', 'data': {'err': str(meta.err())}}}
                    result = str(meta.signature())
                    _accounts.update(keys - {'11111111111111111111111111111111'})
                    _signatures[result] = {'slot': slot, 'err': None, 'confirmationStatus': 'finalized', 'confirmations': None}
                    _save()
                    _bank.expire_blockhash()
            elif method == 'getSignatureStatuses':
                for signature in params[0]: Signature.from_string(signature)
                result = context([_signatures.get(signature) for signature in params[0]])
            else:
                return {'error': {'code': -32601, 'message': 'CRYPTO_VM_METHOD_UNSUPPORTED'}}
            if len(_signatures) > 256:
                del _signatures[next(iter(_signatures))]
            return {'jsonrpc': '2.0', 'id': 1, 'result': result}
        except (ValueError, TypeError, IndexError, KeyError):
            return {'error': {'code': -32602, 'message': 'CRYPTO_VM_INVALID_REQUEST'}}
