"""User account purpose, kept separate from custody and signing capability.

STORAGE is a purpose, not a hardware connection, an ownership proof or a
guarantee that its private key has stayed offline. Both purposes may have local
keys; those are explicitly reported as online. No key or network is touched.
"""
from __future__ import annotations

from backend import omni_assets as store, wallet_vault

SCHEMA='gg.wallet-account-roles.v1'
ROLES=frozenset({'TRADING','STORAGE'})
MAX_ROLES=128


def _table(connection):
    # No FK cascade: registry metadata updates use INSERT OR REPLACE.
    connection.execute('''CREATE TABLE IF NOT EXISTS wallet_account_roles(
        account_id TEXT PRIMARY KEY,role TEXT NOT NULL)''')


def _is_local(account, keys):
    return any(key.get('account_id')==account['id'] or
        (key.get('chain_id')==account['chain_id'] and key.get('pubkey')==account['address'])
        for key in keys)


def _snapshot(connection,keys):
    stored={row['account_id']:row['role'] for row in connection.execute(
        'SELECT account_id,role FROM wallet_account_roles LIMIT ?',(MAX_ROLES,)) if row['role'] in ROLES}
    roles={};accounts=[]
    for account in connection.execute('SELECT id,chain_id,address FROM accounts ORDER BY rowid LIMIT 128'):
        local=_is_local(account,keys);requested=stored.get(account['id'],'UNASSIGNED')
        available=_is_local(account,[key for key in keys if key.get('vault_available') is True])
        role=requested
        if role in ROLES:roles[account['id']]=role
        accounts.append({'account_id':account['id'],'role':role,'requested_role':requested,
            'signer_state':'LOCAL_ENCRYPTED' if available else 'LOCAL_KEY_UNAVAILABLE' if local else 'EXTERNAL_OR_WATCH_ONLY',
            'storage_state':'LOCAL_KEY_ONLINE' if role=='STORAGE' and available else
                'LOCAL_KEY_KNOWN_UNAVAILABLE' if role=='STORAGE' and local else
                'EXTERNAL_KEY_NOT_VERIFIED' if role=='STORAGE' else 'NOT_STORAGE'})
    return {'schema':SCHEMA,'roles':roles,'accounts':accounts,
            'storage_guarantee':'PURPOSE_ONLY_KEY_STORAGE_IS_SEPARATE'}


def snapshot():
    with store._LOCK:
        # Failure to inspect known local keys must not produce a cold label.
        keys=wallet_vault.status()
        with store.db() as connection:
            _table(connection)
            return _snapshot(connection,keys)


def set_role(account_id,role):
    if (not isinstance(account_id,str) or not 1<=len(account_id)<=128 or
            not isinstance(role,str) or role not in ROLES):
        raise ValueError('WALLET_ACCOUNT_ROLE_INVALID')
    with store._LOCK:
        keys=wallet_vault.status()
        with store.db(True) as connection:
            _table(connection)
            account=connection.execute('SELECT id,chain_id,address FROM accounts WHERE id=?',(account_id,)).fetchone()
            if account is None:raise ValueError('WALLET_ACCOUNT_ROLE_ACCOUNT_UNKNOWN')
            if (connection.execute('SELECT COUNT(*) FROM wallet_account_roles').fetchone()[0]>=MAX_ROLES and
                    not connection.execute('SELECT 1 FROM wallet_account_roles WHERE account_id=?',(account_id,)).fetchone()):
                raise ValueError('WALLET_ACCOUNT_ROLE_LIMIT')
            connection.execute('INSERT OR REPLACE INTO wallet_account_roles VALUES(?,?)',(account_id,role))
            return _snapshot(connection,keys)


