"""Private local BIP39 sessions and password-portable mnemonic recovery.

No session, word, answer, seed or password enters an OMNI snapshot or event.
Python/Qt immutable copies cannot promise physical RAM erasure; owned mutable
buffers are wiped and references dropped as soon as their step is complete.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from functools import lru_cache
import base64
import hashlib
import hmac
import importlib.metadata
import json
import os
import secrets
import struct
import threading
import unicodedata
import uuid

from backend import omni_assets as store

SOL=store.NATIVE_SOL.split('/')[0]
DERIVATION_PATH="m/44'/501'/0'/0'"
SCHEMA='gg.mnemonic-recovery.v1'
MAX_SESSIONS=2
_lock=threading.RLock()
_sessions={}


def wipe(value):
    if isinstance(value,bytearray):value[:]=b'\0'*len(value);value.clear()


@lru_cache(maxsize=1)
def _bip39():
    if importlib.metadata.version('mnemonic')!='0.21':raise ValueError('WALLET_MNEMONIC_DEPENDENCY')
    from mnemonic import Mnemonic
    return Mnemonic('english')


def _phrase(value):
    if not isinstance(value,str) or len(value)>1024:raise ValueError('WALLET_MNEMONIC_INVALID')
    text=' '.join(unicodedata.normalize('NFKD',value).lower().split())
    if len(text.split()) not in (12,24) or not _bip39().check(text):raise ValueError('WALLET_MNEMONIC_INVALID')
    return bytearray(text.encode('ascii'))


def derive_child(seed,path=DERIVATION_PATH):
    """SLIP-0010 hardened Ed25519 CKD, verified against published vectors."""
    if not isinstance(seed,(bytes,bytearray)) or not 16<=len(seed)<=64:raise ValueError('WALLET_MNEMONIC_DERIVATION')
    if not isinstance(path,str) or len(path)>80 or not path.startswith('m'):raise ValueError('WALLET_MNEMONIC_DERIVATION')
    parts=path.split('/')
    if parts[0]!='m':raise ValueError('WALLET_MNEMONIC_DERIVATION')
    indices=[]
    for part in parts[1:]:
        if not part.endswith("'") or not part[:-1].isdigit() or len(part)>11 or int(part[:-1])>=2**31:raise ValueError('WALLET_MNEMONIC_DERIVATION')
        indices.append(int(part[:-1])|0x80000000)
    material=bytearray(hmac.new(b'ed25519 seed',seed,hashlib.sha512).digest())
    try:
        for index in indices:
            old=material
            material=bytearray(hmac.new(bytes(old[32:]),b'\0'+bytes(old[:32])+struct.pack('>I',index),hashlib.sha512).digest())
            wipe(old)
        return bytearray(material[:32]),bytes(material[32:])
    finally:wipe(material)


def derive(phrase):
    """Return the child seed and public address; caller must wipe the seed."""
    from Crypto.Signature import eddsa
    from backend.crypto_keys import b58encode
    seed=bytearray();child=bytearray()
    try:
        seed=bytearray(_bip39().to_seed(bytes(phrase).decode('ascii'),passphrase=''))
        child,_=derive_child(seed)
        key=eddsa.import_private_key(bytes(child))
        address=b58encode(key.public_key().export_key(format='raw'))
        del key
        return child,address
    except Exception:wipe(child);raise
    finally:wipe(seed)


@dataclass(repr=False)
class _Session:
    public:dict
    phrase:bytearray=field(default_factory=bytearray)
    password:bytearray=field(default_factory=bytearray)
    commitments:list=field(default_factory=list)
    state:str='DISPLAY'
    attempts:int=0
    def clear(self):wipe(self.phrase);wipe(self.password);self.commitments.clear()


def _session(identifier):
    if not isinstance(identifier,str) or len(identifier)!=32 or identifier not in _sessions:raise ValueError('WALLET_MNEMONIC_SESSION')
    return _sessions[identifier]


def _new(label,purpose,count,method,flow,phrase,restoring=False):
    if (not isinstance(purpose,str) or purpose not in {'TRADING','STORAGE'} or type(count) is not int or count not in (12,24)
            or not isinstance(method,str) or method not in {'PAPER','AI'}):
        wipe(phrase);raise ValueError('WALLET_MNEMONIC_OPTIONS')
    flow=flow or ('AI_ASSISTED' if method=='AI' else 'SELF_CUSTODY')
    if not isinstance(flow,str) or flow not in {'SELF_CUSTODY','AI_ASSISTED'}:
        wipe(phrase);raise ValueError('WALLET_MNEMONIC_OPTIONS')
    child=bytearray()
    try:
        with _lock:
            if len(_sessions)>=MAX_SESSIONS:raise ValueError('WALLET_MNEMONIC_SESSION_LIMIT')
            child,address=derive(phrase)
            identifier=uuid.uuid4().hex
            public={'session_id':identifier,'address':address,'pubkey':address,'chain_id':SOL,
                'derivation_path':DERIVATION_PATH,'word_count':count,'purpose':purpose,'method':method,
                'flow':flow,'label':store.text(label,64)}
            session=_Session(public,phrase=phrase)
            _sessions[identifier]=session
            if restoring:
                session.state='VERIFIED' if method=='AI' else 'READY'
                if method=='PAPER':wipe(session.phrase)
                return dict(public,state='VERIFIED_NEEDS_PASSWORD' if method=='AI' else 'READY')
            return dict(public,words=bytes(phrase).decode('ascii').split(),state='DISPLAY')
    except Exception:wipe(phrase);raise
    finally:wipe(child)


def begin(label,purpose,count,method='PAPER',flow=''):
    if type(count) is not int or count not in (12,24):raise ValueError('WALLET_MNEMONIC_OPTIONS')
    with _lock:
        if len(_sessions)>=MAX_SESSIONS:raise ValueError('WALLET_MNEMONIC_SESSION_LIMIT')
        phrase=bytearray(_bip39().generate(strength=128 if count==12 else 256).encode('ascii'))
        return _new(label,purpose,count,method,flow,phrase)


def begin_restore(phrase,label='',purpose='TRADING',method='PAPER',flow=''):
    raw=_phrase(phrase)
    return _new(label,purpose,raw.count(b' ')+1,method,flow,raw,restoring=True)


def _word_commit(index,word,salt):return hmac.new(salt,str(index).encode()+b'\0'+word,hashlib.sha256).digest()


def challenge(identifier):
    with _lock:
        session=_session(identifier)
        if session.state!='DISPLAY':raise ValueError('WALLET_MNEMONIC_PHASE')
        indices=sorted(secrets.SystemRandom().sample(range(1,session.public['word_count']+1),3))
        words=session.phrase.split()
        try:
            session.commitments=[(index,os.urandom(32),b'') for index in indices]
            session.commitments=[(index,salt,_word_commit(index,bytes(words[index-1]),salt)) for index,salt,_ in session.commitments]
        finally:
            for word in words:wipe(word)
            words.clear()
            if session.public['method']=='PAPER':wipe(session.phrase)
        session.state='CHALLENGE'
        return {'session_id':identifier,'indices':indices,'state':'CHALLENGE'}


def verify(identifier,answers):
    with _lock:
        session=_session(identifier)
        if session.state!='CHALLENGE':raise ValueError('WALLET_MNEMONIC_PHASE')
        valid=isinstance(answers,dict) and set(answers)=={str(index) for index,_,_ in session.commitments}
        for index,salt,commitment in session.commitments:
            word=answers.get(str(index)) if isinstance(answers,dict) else None
            good=isinstance(word,str) and len(word)<=16 and word.isascii()
            candidate=word.strip().lower().encode('ascii') if good else b''
            valid=hmac.compare_digest(commitment,_word_commit(index,candidate,salt)) and good and valid
        if not valid:
            session.attempts+=1
            if session.attempts>=3:cancel(identifier)
            raise ValueError('WALLET_MNEMONIC_CHALLENGE_FAILED')
        session.commitments.clear()
        session.state='VERIFIED' if session.public['method']=='AI' else 'READY'
        return dict(session.public,state='VERIFIED_NEEDS_PASSWORD' if session.state=='VERIFIED' else 'READY')


def set_password(identifier,password):
    with _lock:
        session=_session(identifier)
        if session.state!='VERIFIED' or session.public['method']!='AI':raise ValueError('WALLET_MNEMONIC_PHASE')
        if not isinstance(password,str) or not 12<=len(password)<=256:raise ValueError('WALLET_PASSWORD_LENGTH')
        session.password=bytearray(password.encode('utf-8'));session.state='READY'
        return dict(session.public,state='READY')


def descriptor(identifier,label=None):
    with _lock:
        session=_session(identifier)
        if session.state not in {'READY','CONSUMING'}:raise ValueError('WALLET_MNEMONIC_NOT_READY')
        if label is not None and store.text(label,64)!=session.public['label']:raise ValueError('WALLET_MNEMONIC_BINDING')
        return dict(session.public)


def consume(identifier,label):
    from backend import wallet_approval
    wallet_approval.require_operation('create_wallet',{'label':label,'mnemonic_session':identifier},'credentials.write')
    with _lock:
        descriptor(identifier,label)
        session=_session(identifier)
        if session.state!='READY':raise ValueError('WALLET_MNEMONIC_ALREADY_CONSUMED')
        bundle=_Session(dict(session.public),session.phrase,session.password,state='CONSUMING')
        session.phrase=bytearray();session.password=bytearray();session.state='CONSUMING'
        session.commitments.clear()
        # Public metadata stays until finish so approval can be rechecked after
        # an expensive KDF. A second consume is rejected independently.
        return bundle


def cancel(identifier):
    with _lock:
        session=_sessions.pop(identifier,None) if isinstance(identifier,str) else None
        if session:session.clear()
        return {'state':'CANCELLED'}


def cancel_all():
    with _lock:
        for session in _sessions.values():session.clear()
        _sessions.clear()


def _setup_table(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS wallet_setup(
        account_id TEXT PRIMARY KEY,control_mode TEXT NOT NULL,custody_method TEXT NOT NULL,
        derivation_path TEXT NOT NULL,word_count INTEGER NOT NULL)''')


def account_metadata():
    """Public purpose/control metadata only; never loads the BIP39 word list."""
    with store.db() as connection:
        _setup_table(connection)
        rows=connection.execute('''SELECT s.* FROM wallet_setup s JOIN accounts a ON a.id=s.account_id LIMIT 128''').fetchall()
    return {row['account_id']:{key:row[key] for key in ('control_mode','custody_method','derivation_path','word_count')}
        for row in rows if row['control_mode'] in {'SELF_CUSTODY','AI_ASSISTED'} and row['custody_method'] in {'PAPER','AI'}
        and row['derivation_path']==DERIVATION_PATH and row['word_count'] in (12,24)}


def _public_path(pubkey,directory,suffix):
    from backend.crypto_contract import validate_pubkey
    pubkey=validate_pubkey(pubkey)
    path=store.ROOT/directory/(pubkey+suffix)
    from backend.platform_files import is_link
    if any(is_link(item) for item in (path,*path.parents)):raise ValueError('WALLET_MNEMONIC_RECOVERY_PATH')
    return path


def recovery_path(pubkey):return _public_path(pubkey,'wallet-recovery','.ggmnemonic')


def recovery_status(pubkey):
    path=recovery_path(pubkey)
    return {'pubkey':pubkey,'chain_id':SOL,'derivation_path':DERIVATION_PATH,'available':path.is_file()}


def _aad(header):
    return json.dumps({key:header[key] for key in ('schema','chain_id','pubkey','derivation_path','word_count')},sort_keys=True,separators=(',',':')).encode()


def _recovery_header(raw):
    if not isinstance(raw,bytes) or len(raw)>4096:raise ValueError('WALLET_MNEMONIC_RECOVERY_INVALID_OR_PASSWORD')
    def pairs(items):
        result={}
        for name,value in items:
            if name in result:raise ValueError('WALLET_MNEMONIC_RECOVERY_INVALID_OR_PASSWORD')
            result[name]=value
        return result
    header=json.loads(raw,object_pairs_hook=pairs)
    if (not isinstance(header,dict) or set(header)!={'schema','chain_id','pubkey','derivation_path','word_count','kdf','salt','nonce','ciphertext','tag'} or
            header['schema']!=SCHEMA or header['chain_id']!=SOL or header['derivation_path']!=DERIVATION_PATH or
            type(header['word_count']) is not int or header['word_count'] not in (12,24) or header['kdf']!='scrypt-131072-8-1'):
        raise ValueError('WALLET_MNEMONIC_RECOVERY_INVALID_OR_PASSWORD')
    values=[]
    for name in ('salt','nonce','ciphertext','tag'):
        if not isinstance(header[name],str) or len(header[name])>1024:raise ValueError('WALLET_MNEMONIC_RECOVERY_INVALID_OR_PASSWORD')
        values.append(base64.b64decode(header[name],validate=True))
    if len(values[0])!=16 or len(values[1])!=12 or not 16<=len(values[2])<=512 or len(values[3])!=16:
        raise ValueError('WALLET_MNEMONIC_RECOVERY_INVALID_OR_PASSWORD')
    return header


def public_recovery_metadata(raw,pubkey=None):
    header=_recovery_header(raw)
    if pubkey is not None and header['pubkey']!=pubkey:raise ValueError('WALLET_MNEMONIC_BINDING')
    return {name:header[name] for name in ('chain_id','pubkey','derivation_path','word_count')}


def encode_recovery(phrase,password,pubkey):
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import scrypt
    if not isinstance(password,(bytes,bytearray)) or not 12<=len(password)<=1024:raise ValueError('WALLET_PASSWORD_LENGTH')
    salt=os.urandom(16);nonce=os.urandom(12);key=bytearray()
    header={'schema':SCHEMA,'chain_id':SOL,'pubkey':pubkey,'derivation_path':DERIVATION_PATH,'word_count':phrase.count(b' ')+1}
    try:
        key=bytearray(scrypt(bytes(password),salt,32,N=131072,r=8,p=1))
        cipher=AES.new(bytes(key),AES.MODE_GCM,nonce=nonce);cipher.update(_aad(header))
        encoded,tag=cipher.encrypt_and_digest(bytes(phrase))
        b64=lambda value:base64.b64encode(value).decode('ascii')
        return json.dumps(dict(header,kdf='scrypt-131072-8-1',salt=b64(salt),nonce=b64(nonce),ciphertext=b64(encoded),tag=b64(tag)),sort_keys=True,separators=(',',':')).encode()
    finally:wipe(key)


def decode_recovery(raw,password):
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import scrypt
    key=bytearray();plain=bytearray();child=bytearray()
    try:
        if not isinstance(raw,bytes) or len(raw)>4096 or not isinstance(password,str) or not 12<=len(password)<=256:raise ValueError()
        header=_recovery_header(raw)
        values=[base64.b64decode(header[name],validate=True) for name in ('salt','nonce','ciphertext','tag')]
        salt,nonce,encoded,tag=values
        if len(salt)!=16 or len(nonce)!=12 or len(tag)!=16 or not 16<=len(encoded)<=512:raise ValueError()
        key=bytearray(scrypt(password.encode('utf-8'),salt,32,N=131072,r=8,p=1))
        cipher=AES.new(bytes(key),AES.MODE_GCM,nonce=nonce);cipher.update(_aad(header))
        plain=_phrase(cipher.decrypt_and_verify(encoded,tag).decode('ascii'))
        if plain.count(b' ')+1!=header['word_count']:raise ValueError()
        child,address=derive(plain)
        if address!=header['pubkey']:raise ValueError()
        return plain,{name:header[name] for name in ('chain_id','pubkey','derivation_path','word_count')}
    except Exception:
        wipe(plain);raise ValueError('WALLET_MNEMONIC_RECOVERY_INVALID_OR_PASSWORD') from None
    finally:wipe(key);wipe(child)


def reveal(pubkey,password):
    from backend import wallet_approval
    args={'pubkey':pubkey,'password':password}
    wallet_approval.require_operation('reveal_mnemonic',args,'credentials.read')
    raw=wallet_approval.read_public_file(recovery_path(pubkey));phrase=bytearray()
    try:
        phrase,public=decode_recovery(raw,password)
        if public['pubkey']!=pubkey:raise ValueError('WALLET_MNEMONIC_BINDING')
        wallet_approval.require_operation('reveal_mnemonic',args,'credentials.read')
        return dict(public,words=bytes(phrase).decode('ascii').split(),address=public['pubkey'])
    finally:wipe(phrase)


def export(pubkey,path):
    from backend import wallet_approval,wallet_vault
    args={'pubkey':pubkey,'path':path}
    wallet_approval.require_operation('export_mnemonic',args,'credentials.read')
    wallet_approval.require_operation('export_mnemonic',args,'filesystem.write')
    destination=wallet_approval.local_path(path)
    raw=wallet_approval.read_public_file(recovery_path(pubkey))
    public_recovery_metadata(raw,pubkey)
    wallet_approval.require_operation('export_mnemonic',args,'filesystem.write')
    try:wallet_vault._write(destination,raw,overwrite=False)
    except FileExistsError:raise ValueError('WALLET_BACKUP_ALREADY_EXISTS') from None
