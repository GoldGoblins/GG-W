"""Supervised asset decoder. The Rust handle restricts files to one explicit root."""
import base64,ctypes,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.native_worker_limits import apply as apply_worker_limits
MAX_MESSAGE=16*1024*1024

def serve(lib,handle,input_stream,output_stream):
    """Never reuse or destruct a Reader whose Rust panic interrupted mutation.

    The current verified native ABI reports panics as an error string. Promote
    that one fatal outcome to an explicit protocol field, retaining ordinary
    malformed-input errors as recoverable. The OS reclaims a poisoned Reader.
    """
    size=ctypes.c_size_t
    while line:=input_stream.readline(65538):
        if len(line)>65536 or not line.endswith(b'\n'):raise ValueError('Invalid asset request capacity')
        if json.loads(line).get('op')=='ping':answer={'ok':True,'result':{'abi':1}}
        else:
            if lib.gga_request(handle,line,len(line))!=0:raise RuntimeError('Invalid asset request')
            length=size();data=lib.gga_response(handle,ctypes.byref(length))
            if not data or length.value>MAX_MESSAGE:raise RuntimeError('Invalid asset response')
            answer=json.loads(ctypes.string_at(data,length.value))
            if not isinstance(answer,dict) or not isinstance(answer.get('ok'),bool):
                raise RuntimeError('Invalid asset response')
            if not answer['ok'] and answer.get('error')=='native asset decoder panic':
                answer['fatal']=True
            if answer['ok']:
                blob=lib.gga_blob(handle,ctypes.byref(length))
                if length.value>8*1024*1024:raise RuntimeError('Asset blob capacity exceeded')
                if length.value:answer['result']['blob_base64']=base64.b64encode(ctypes.string_at(blob,length.value)).decode('ascii')
        response=json.dumps(answer,separators=(',',':')).encode()+b'\n'
        if len(response)>MAX_MESSAGE:raise RuntimeError('Asset response capacity exceeded')
        output_stream.write(response);output_stream.flush()
        if answer.get('fatal') is True:return False
    return True
def main():
    apply_worker_limits(2*1024*1024*1024)
    lib=ctypes.CDLL(sys.argv[1]);pointer=ctypes.c_void_p;size=ctypes.c_size_t
    lib.gga_abi_version.argtypes=[];lib.gga_abi_version.restype=ctypes.c_uint32
    if lib.gga_abi_version()!=1:raise RuntimeError('Native asset ABI mismatch')
    lib.gga_create.argtypes=[ctypes.c_char_p];lib.gga_create.restype=pointer
    lib.gga_destroy.argtypes=[pointer];lib.gga_destroy.restype=None
    lib.gga_request.argtypes=[pointer,pointer,size];lib.gga_request.restype=ctypes.c_int
    for name in ('gga_response','gga_blob'):
        fn=getattr(lib,name);fn.argtypes=[pointer,ctypes.POINTER(size)];fn.restype=pointer
    handle=lib.gga_create(os.fsencode(sys.argv[2]))
    if not handle:raise RuntimeError('Native asset reader initialization failed')
    reusable=False
    try:
        reusable=serve(lib,handle,sys.stdin.buffer,sys.stdout.buffer)
    finally:
        if reusable:lib.gga_destroy(handle)
if __name__=='__main__':main()
