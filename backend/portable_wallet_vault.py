"""Explicit password-unlocked POSIX wallet encryption, with no secret files.

Windows continues to use DPAPI. Terminal callers supply a hidden password for
one exact operation; this module keeps no remembered password or unlocked key.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import base64
import hashlib
import json
import os

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt

_password=ContextVar('gg_portable_wallet_password',default=None)
MAGIC=b'GG-WALLET-PASSPHRASE-1\0'


@contextmanager
def session(password):
    if not isinstance(password,str) or not 12<=len(password)<=256:raise ValueError('WALLET_PASSWORD_LENGTH')
    raw=bytearray(password.encode('utf-8'))
    token=_password.set(raw)
    try:yield
    finally:
        _password.reset(token)
        raw[:]=b'\0'*len(raw)


def require_unlocked():
    if not _password.get():raise ValueError('WALLET_UNLOCK_REQUIRED')


def crypt(data,pubkey,root,decrypt=False):
    require_unlocked()
    if not isinstance(data,bytes) or len(data)>4096:raise ValueError('WALLET_VAULT_SIZE')
    aad=('GG-portable-wallet-v1\0'+os.path.normcase(str(root.resolve()))+'\0'+pubkey).encode()
    encode=lambda value:base64.b64encode(value).decode('ascii')
    key=bytearray()
    try:
        if decrypt:
            def pairs(entries):
                result={}
                for name,value in entries:
                    if name in result:raise ValueError('duplicate')
                    result[name]=value
                return result
            value=json.loads(data,object_pairs_hook=pairs)
            if (not isinstance(value,dict) or set(value)!={'schema','kdf','salt','nonce','ciphertext','tag'}
                or value['schema']!='gg.portable-wallet.v1' or value['kdf']!='scrypt-131072-8-1'):
                raise ValueError('schema')
            decode=lambda name:base64.b64decode(value[name],validate=True)
            salt,nonce,ciphertext,tag=(decode(n) for n in ('salt','nonce','ciphertext','tag'))
            if (len(salt),len(nonce),len(ciphertext),len(tag))!=(16,12,64,16):raise ValueError('size')
        else:
            if len(data)!=64:raise ValueError('size')
            salt,nonce=os.urandom(16),os.urandom(12)
        key=bytearray(scrypt(bytes(_password.get()),salt,32,N=131072,r=8,p=1))
        cipher=AES.new(bytes(key),AES.MODE_GCM,nonce=nonce)
        cipher.update(aad)
        if decrypt:return cipher.decrypt_and_verify(ciphertext,tag)
        ciphertext,tag=cipher.encrypt_and_digest(data)
        return json.dumps({'schema':'gg.portable-wallet.v1','kdf':'scrypt-131072-8-1',
                           'salt':encode(salt),'nonce':encode(nonce),'ciphertext':encode(ciphertext),'tag':encode(tag)},
                          sort_keys=True,separators=(',',':')).encode()
    except (ValueError,TypeError,KeyError,UnicodeError):
        raise ValueError('WALLET_VAULT_INVALID_OR_WRONG_PASSWORD') from None
    finally:
        key[:]=b'\0'*len(key)
