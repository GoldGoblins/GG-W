"""Protected node key bytes; no plaintext file, remembered password or logging.

POSIX uses the existing explicit scrypt/AES-GCM password context. Windows
uses current-user DPAPI with a separate node/profile/role binding. This is
local at-rest protection, not a hardware signer or a portable key backup.
"""
import ctypes
import hashlib
import os

if os.name=='nt':
    from ctypes import wintypes
    class _Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]


def provider():
    return 'WINDOWS_DPAPI' if os.name=='nt' else 'SCRYPT_AES256_GCM'


def crypt(data,public,role,root,*,decrypt=False,storage=None):
    if not isinstance(data,bytes) or not 1<=len(data)<=4096 or role not in ('transport','producer0','producer1',
            'consensus_validator','consensus_node','consensus_account','consensus_observer_node','financial_account'):
        raise ValueError('GG_NODE_VAULT_INPUT')
    context='GG-DAG-NODE-KEY-v1\0'+role+'\0'+public
    selected=storage or provider()
    if selected=='SCRYPT_AES256_GCM':
        from backend.portable_wallet_vault import crypt as portable
        return portable(data,context,root,decrypt)
    if selected!='WINDOWS_DPAPI' or os.name!='nt':raise ValueError('GG_NODE_VAULT_PLATFORM')
    from ctypes import wintypes
    raw=ctypes.create_string_buffer(data)
    entropy=ctypes.create_string_buffer(hashlib.sha256(('GG-node-vault-v1\0'+os.path.normcase(str(root.resolve()))+'\0'+context).encode()).digest())
    source=_Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)))
    extra=_Blob(32,ctypes.cast(entropy,ctypes.POINTER(ctypes.c_ubyte)));output=_Blob()
    api=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=api.CryptUnprotectData if decrypt else api.CryptProtectData
    function.argtypes=[ctypes.POINTER(_Blob),ctypes.c_void_p,ctypes.POINTER(_Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_Blob)]
    function.restype=wintypes.BOOL;kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    try:
        if not function(ctypes.byref(source),None,ctypes.byref(extra),None,None,1,ctypes.byref(output)):
            raise ValueError('GG_NODE_VAULT_INVALID_OR_UNAVAILABLE')
        if not output.data or not 0<output.size<=4096:raise ValueError('GG_NODE_VAULT_SIZE')
        return ctypes.string_at(output.data,output.size)
    finally:
        ctypes.memset(raw,0,len(raw));ctypes.memset(entropy,0,len(entropy))
        if output.data:
            if 0<output.size<=4096:ctypes.memset(output.data,0,output.size)
            kernel.LocalFree(output.data)
