"""Solana keys protected by Windows DPAPI or an explicitly unlocked POSIX vault.

Public status exposes addresses and metadata or an authenticated encrypted backup.
Owner recovery words use a separate approved local UI, never public status,
shell arguments, chat, logs or a plaintext file fallback.
"""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import time
from backend import omni_assets as store
from backend.platform_files import secure_open,atomic_replace,set_private_mode,is_link

SOL=store.NATIVE_SOL.rsplit('/native:',1)[0]
MAGIC=b'GG-WALLET-DPAPI-1\0'
if os.name=='nt':
    from ctypes import wintypes
    class _Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]


def require(effect):
    from backend import task_scoped_action_grant
    authorization=task_scoped_action_grant.runtime_authorize_effect(effect)
    if authorization is None:raise ValueError('WALLET_APPROVAL_REQUIRED')
    return authorization


def _table(db):
    db.execute('CREATE TABLE IF NOT EXISTS wallet_keys(pubkey TEXT PRIMARY KEY,account_id TEXT NOT NULL,chain_id TEXT NOT NULL,backed_up INTEGER NOT NULL,created_at REAL NOT NULL)')


def status():
    with store.db() as db:
        _table(db)
        rows=[dict(r) for r in db.execute('SELECT * FROM wallet_keys ORDER BY created_at')]
    for row in rows:
        row['vault_available']=_path(row['pubkey']).is_file()
        row['storage']='WINDOWS_DPAPI' if os.name=='nt' else 'SCRYPT_AES256_GCM';row['backed_up']=bool(row['backed_up'])
        from backend import wallet_mnemonic
        row['recovery_available']=wallet_mnemonic.recovery_path(row['pubkey']).is_file()
    return rows


def _path(pubkey):
    from solders.pubkey import Pubkey
    try:
        key=Pubkey.from_string(pubkey)
        if not key.is_on_curve():raise ValueError()
    except Exception:raise ValueError('WALLET_PUBLIC_KEY') from None
    path=store.ROOT/'wallet-vault'/(str(key)+'.vault')
    if any(is_link(p) for p in (path,*path.parents)):raise ValueError('WALLET_VAULT_PATH')
    return path


def _crypt(data,pubkey,decrypt=False):
    if os.name!='nt':
        from backend import portable_wallet_vault
        return portable_wallet_vault.crypt(data,pubkey,store.ROOT,decrypt)
    from ctypes import wintypes
    raw=ctypes.create_string_buffer(data)
    entropy=ctypes.create_string_buffer(hashlib.sha256(('GG-wallet-v1\0'+os.path.normcase(str(store.ROOT.resolve()))+'\0'+pubkey).encode()).digest())
    source=_Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)))
    extra=_Blob(32,ctypes.cast(entropy,ctypes.POINTER(ctypes.c_ubyte)));output=_Blob()
    api=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=api.CryptUnprotectData if decrypt else api.CryptProtectData
    function.argtypes=[ctypes.POINTER(_Blob),ctypes.c_void_p,ctypes.POINTER(_Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_Blob)]
    function.restype=wintypes.BOOL;kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    try:
        if not function(ctypes.byref(source),None,ctypes.byref(extra),None,None,1,ctypes.byref(output)):raise ValueError('WALLET_VAULT_CRYPTO_FAILED')
        if not output.data or not 0<output.size<=4096:raise ValueError('WALLET_VAULT_SIZE')
        return ctypes.string_at(output.data,output.size)
    finally:
        ctypes.memset(raw,0,len(raw));ctypes.memset(entropy,0,len(entropy))
        if output.data:
            if 0<output.size<=4096:ctypes.memset(output.data,0,output.size)
            kernel.LocalFree(output.data)


def _write(path,data,*,overwrite=True):
    import uuid
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
    try:
        fd=secure_open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        set_private_mode(temporary,0o600)
        if overwrite:atomic_replace(temporary,path)
        elif os.name=='nt':os.rename(temporary,path)  # Windows rename never replaces an existing destination.
        else:os.link(temporary,path,follow_symlinks=False)  # Atomic no-replace publication on POSIX.
    finally:temporary.unlink(missing_ok=True)


def _save(keypair,label,backed_up=False):
    pubkey=str(keypair.pubkey());path=_path(pubkey)
    with store.db() as db:
        _table(db)
        if db.execute('SELECT COUNT(*) FROM wallet_keys').fetchone()[0]>=32 and not path.exists():raise ValueError('WALLET_VAULT_LIMIT')
    from backend.portable_wallet_vault import MAGIC as portable_magic
    _write(path,(MAGIC if os.name=='nt' else portable_magic)+_crypt(bytes(keypair),pubkey))
    account=store.account(SOL,pubkey,label or 'GG · Solana')
    with store.db(True) as db:
        _table(db);db.execute('INSERT OR REPLACE INTO wallet_keys VALUES(?,?,?,?,?)',(pubkey,account,SOL,int(backed_up),time.time()))
    store.event('wallet','LOCAL_WALLET_READY','','GG-wallet · Solana · krypterat '+('Windows-valv' if os.name=='nt' else 'lösenordsvalv'))
    return {'pubkey':pubkey,'account_id':account,'chain_id':SOL,'backed_up':backed_up}


def create(label='',mnemonic_session=''):
    from backend import wallet_approval
    args={'label':label}
    if mnemonic_session:args['mnemonic_session']=mnemonic_session
    wallet_approval.require_operation('create_wallet',args,'credentials.write')
    if mnemonic_session:return _create_mnemonic(label,mnemonic_session,args)
    if os.name!='nt':
        from backend import portable_wallet_vault
        portable_wallet_vault.require_unlocked()
    from solders.keypair import Keypair
    return _save(Keypair(),store.text(label,64))


def _create_mnemonic(label,identifier,args):
    """One approved publication; never keep a PAPER private key in the vault."""
    from backend import wallet_mnemonic as mnemonic,wallet_approval,wallet_account_roles
    from contextlib import nullcontext
    session=mnemonic.consume(identifier,label);created=[];child=bytearray()
    try:
        public=session.public;pubkey=public['address'];method=public['method']
        vault_data=None;recovery_data=None
        if method=='AI':
            from solders.keypair import Keypair
            from backend import portable_wallet_vault
            if not session.password or not session.phrase:raise ValueError('WALLET_MNEMONIC_NOT_READY')
            child,address=mnemonic.derive(session.phrase)
            if address!=pubkey:raise ValueError('WALLET_MNEMONIC_BINDING')
            recovery_data=mnemonic.encode_recovery(session.phrase,session.password,pubkey)
            wallet_approval.require_operation('create_wallet',args,'credentials.write')
            pair=Keypair.from_seed(bytes(child))
            context=portable_wallet_vault.session(bytes(session.password).decode('utf-8')) if os.name!='nt' else nullcontext()
            with context:vault_data=(MAGIC if os.name=='nt' else portable_wallet_vault.MAGIC)+_crypt(bytes(pair),pubkey)
            del pair
        wallet_approval.require_operation('create_wallet',args,'credentials.write')
        account='account-'+hashlib.sha256((SOL+'\0'+pubkey).encode()).hexdigest()[:24]
        # File publication and public metadata share one serialized DB commit.
        # Only paths successfully created by this call are removed on rollback.
        with store.db(True) as db:
            _table(db);wallet_account_roles._table(db);mnemonic._setup_table(db)
            if not db.execute('SELECT 1 FROM accounts WHERE id=?',(account,)).fetchone() and db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]>=128:raise ValueError('OMNI_ACCOUNT_LIMIT')
            local=db.execute('SELECT 1 FROM wallet_keys WHERE pubkey=?',(pubkey,)).fetchone()
            if method=='PAPER' and (local or mnemonic._public_path(pubkey,'wallet-vault','.vault').exists()):raise ValueError('WALLET_MNEMONIC_PAPER_LOCAL_KEY_EXISTS')
            if method=='AI':
                if db.execute('SELECT COUNT(*) FROM wallet_keys').fetchone()[0]>=32 and not local:raise ValueError('WALLET_VAULT_LIMIT')
                path=_path(pubkey);recovery=mnemonic.recovery_path(pubkey)
                if path.exists() or recovery.exists():raise ValueError('WALLET_MNEMONIC_ALREADY_REGISTERED')
                _write(path,vault_data,overwrite=False);created.append(path)
                _write(recovery,recovery_data,overwrite=False);created.append(recovery)
                db.execute('INSERT OR REPLACE INTO wallet_keys VALUES(?,?,?,?,?)',(pubkey,account,SOL,1,time.time()))
            wallet_approval.require_operation('create_wallet',args,'credentials.write')
            db.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?)',(account,SOL,pubkey,store.text(label,64) or 'Solana','watch'))
            db.execute('INSERT OR REPLACE INTO wallet_account_roles VALUES(?,?)',(account,public['purpose']))
            db.execute('INSERT OR REPLACE INTO wallet_setup VALUES(?,?,?,?,?)',(account,public['flow'],method,mnemonic.DERIVATION_PATH,public['word_count']))
        try:store.event('wallet','USER_WALLET_READY','','Solana · '+public['purpose']+' · '+method+' · användarägd återställning')
        except Exception:pass
        return {'pubkey':pubkey,'account_id':account,'chain_id':SOL,'method':method,'purpose':public['purpose'],
                'derivation_path':mnemonic.DERIVATION_PATH,'word_count':public['word_count'],
                'control_mode':public['flow'],'custody_method':method,
                'signer_state':'LOCAL_ENCRYPTED' if method=='AI' else 'WATCH_ONLY','backed_up':True,
                'recovery_available':method=='AI'}
    except Exception:
        for path in reversed(created):path.unlink(missing_ok=True)
        raise
    finally:
        mnemonic.wipe(child);session.clear();mnemonic.cancel(identifier)


def _keypair(pubkey):
    from solders.keypair import Keypair
    path=_path(pubkey)
    with path.open('rb') as stream:encoded=stream.read(4097)
    from backend.portable_wallet_vault import MAGIC as portable_magic
    expected_magic=MAGIC if os.name=='nt' else portable_magic
    if not encoded.startswith(expected_magic) or len(encoded)>4096:raise ValueError('WALLET_VAULT_FORMAT')
    raw=bytearray(_crypt(encoded[len(expected_magic):],pubkey,True))
    try:
        if len(raw)!=64:raise ValueError('WALLET_VAULT_FORMAT')
        pair=Keypair.from_bytes(bytes(raw))
        if str(pair.pubkey())!=pubkey:raise ValueError('WALLET_SIGNER_MISMATCH')
        return pair
    finally:raw[:]=b'\0'*len(raw)


def export_backup(pubkey,path,password):
    from backend import wallet_approval
    args={'pubkey':pubkey,'path':path,'password':password}
    wallet_approval.require_operation('backup_wallet',args,'credentials.read')
    wallet_approval.require_operation('backup_wallet',args,'filesystem.write')
    if not isinstance(password,str) or not 12<=len(password)<=256:raise ValueError('WALLET_BACKUP_PASSWORD_LENGTH')
    path=wallet_approval.local_path(path)
    if not path.is_absolute() or path.resolve().is_relative_to(store.PROJECT) or any(is_link(p) for p in (path,*path.parents)):raise ValueError('WALLET_BACKUP_PATH')
    if path.exists():raise ValueError('WALLET_BACKUP_ALREADY_EXISTS')
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import scrypt
    salt=os.urandom(16);nonce=os.urandom(12);key=scrypt(password.encode(),salt,32,N=131072,r=8,p=1)
    cipher=AES.new(key,AES.MODE_GCM,nonce=nonce);aad=('GG-wallet-backup-v1\0'+SOL+'\0'+pubkey).encode();cipher.update(aad)
    wallet_approval.require_operation('backup_wallet',args,'credentials.read')
    pair=_keypair(pubkey);encrypted,tag=cipher.encrypt_and_digest(bytes(pair));del pair
    encode=lambda b:base64.b64encode(b).decode('ascii')
    backup={'schema':'gg.wallet-backup.v1','chain_id':SOL,'pubkey':pubkey,'kdf':'scrypt-131072-8-1','salt':encode(salt),'nonce':encode(nonce),'ciphertext':encode(encrypted),'tag':encode(tag)}
    raw=store.pack(backup).encode();_decode_backup(raw,password)
    wallet_approval.require_operation('backup_wallet',args,'filesystem.write')
    try:_write(path,raw,overwrite=False)
    except FileExistsError:raise ValueError('WALLET_BACKUP_ALREADY_EXISTS') from None
    verified=_decode_backup(wallet_approval.read_public_file(path),password)
    if str(verified.pubkey())!=pubkey:raise ValueError('WALLET_BACKUP_INVALID_OR_WRONG_PASSWORD')
    del verified
    with store.db(True) as db:
        _table(db);db.execute('UPDATE wallet_keys SET backed_up=1 WHERE pubkey=?',(pubkey,))
    store.event('wallet','ENCRYPTED_BACKUP_READY','','Krypterad walletbackup skapad och kontrollerad')


def _decode_backup(raw,password):
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import scrypt
    from solders.keypair import Keypair
    try:
        if len(raw)>4096 or not isinstance(password,str) or not 12<=len(password)<=256:raise ValueError()
        data=json.loads(raw)
        if set(data)!={'schema','chain_id','pubkey','kdf','salt','nonce','ciphertext','tag'} or data['schema']!='gg.wallet-backup.v1' or data['chain_id']!=SOL or data['kdf']!='scrypt-131072-8-1':raise ValueError()
        _path(data['pubkey']);decode=lambda key:base64.b64decode(data[key],validate=True)
        salt,nonce,encrypted,tag=map(decode,('salt','nonce','ciphertext','tag'))
        if (len(salt),len(nonce),len(encrypted),len(tag))!=(16,12,64,16):raise ValueError()
        key=scrypt(password.encode(),salt,32,N=131072,r=8,p=1);cipher=AES.new(key,AES.MODE_GCM,nonce=nonce)
        cipher.update(('GG-wallet-backup-v1\0'+SOL+'\0'+data['pubkey']).encode())
        pair=Keypair.from_bytes(cipher.decrypt_and_verify(encrypted,tag))
        if str(pair.pubkey())!=data['pubkey']:raise ValueError()
        return pair
    except Exception:raise ValueError('WALLET_BACKUP_INVALID_OR_WRONG_PASSWORD') from None


def restore_backup(path,password,label=''):
    from backend import wallet_approval
    args={'path':path,'password':password,'label':label}
    wallet_approval.require_operation('restore_wallet',args,'credentials.write')
    raw=wallet_approval.read_public_file(wallet_approval.local_path(path))
    args['_ciphertext_sha256']=hashlib.sha256(raw).hexdigest()
    pair=_decode_backup(raw,password)
    wallet_approval.require_operation('restore_wallet',args,'credentials.write')
    return _save(pair,store.text(label,64),True)


def _backup_path(value):
    from urllib.parse import urlsplit
    from urllib.request import url2pathname
    raw=str(value)
    if raw.startswith('file:'):
        parts=urlsplit(raw)
        if parts.hostname not in {None,'','localhost'} or parts.query or parts.fragment:raise ValueError('WALLET_BACKUP_PATH')
        raw=url2pathname(parts.path)
    return Path(raw)
