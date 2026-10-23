"""Finite request transport for the isolated native protocol and login client."""
import ctypes,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.native_worker_limits import apply as apply_worker_limits

def main():
    apply_worker_limits(1024*1024*1024)
    lib=ctypes.CDLL(sys.argv[1]);pointer=ctypes.c_void_p;size=ctypes.c_size_t
    lib.ggc_abi_version.argtypes=[];lib.ggc_abi_version.restype=ctypes.c_uint32
    if lib.ggc_abi_version()!=1:raise RuntimeError('Native client ABI mismatch')
    lib.ggc_create.argtypes=[];lib.ggc_create.restype=pointer
    lib.ggc_destroy.argtypes=[pointer];lib.ggc_destroy.restype=None
    lib.ggc_request.argtypes=[pointer,pointer,size];lib.ggc_request.restype=ctypes.c_int
    lib.ggc_response.argtypes=[pointer,ctypes.POINTER(size)];lib.ggc_response.restype=pointer
    handle=lib.ggc_create()
    if not handle:raise RuntimeError('Native client initialization failed')
    try:
        while line:=sys.stdin.buffer.readline(65538):
            if len(line)>65536 or not line.endswith(b'\n'):raise ValueError('Invalid client request capacity')
            if lib.ggc_request(handle,line,len(line))!=0:raise RuntimeError('Invalid client request')
            length=size();data=lib.ggc_response(handle,ctypes.byref(length))
            if not data or length.value>8*1024*1024:raise RuntimeError('Invalid client response')
            # Do not print the incoming request, credentials, wire payloads or
            # native diagnostics. Stdout carries only the structured response.
            sys.stdout.buffer.write(ctypes.string_at(data,length.value)+b'\n');sys.stdout.buffer.flush()
    finally:lib.ggc_destroy(handle)

if __name__=='__main__':main()
