"""Owned loopback page for public CometBFT certificate verification in WASM.

An active GG controller supplies the trust anchor. Nothing is installed, fetched
or started at import. The page cannot choose a wallet, remote node or trust set.
"""
from __future__ import annotations

import atexit
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import threading

from backend.application_paths import PROJECT_ROOT, TOOLS_ROOT

ASSETS=PROJECT_ROOT/'knowledge/gg-consensus-web'
SOURCES=PROJECT_ROOT/'support/gg-consensus'
TOOLS=TOOLS_ROOT/'gg-consensus'
MAX_PACKET_BYTES=256*1024
MAX_CONNECTIONS=4
VERIFY_TIMEOUT_MS=3000
_LOCK=threading.RLock()
_server=None
_thread=None
_trust=None

_PUBLIC_FILES={
    '/':('index.html','text/html; charset=utf-8'),
    '/index.html':('index.html','text/html; charset=utf-8'),
    '/style.css':('style.css','text/css; charset=utf-8'),
    '/viewer.js':('viewer.js','text/javascript; charset=utf-8'),
    '/proof-policy.js':('proof-policy.js','text/javascript; charset=utf-8'),
    '/verify-worker.js':('verify-worker.js','text/javascript; charset=utf-8'),
}
_TOOL_FILES={
    '/verifier.wasm':('verifier.wasm','application/wasm'),
    '/wasm_exec.js':('wasm_exec.js','text/javascript; charset=utf-8'),
}
CSP=("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
     "connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; "
     "frame-ancestors 'none'; form-action 'none'")


def _pack(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def _pin(trust):
    if not isinstance(trust,dict) or set(trust)!={'genesis','genesis_hash'}:
        raise ValueError('GG_LIGHT_TRUST_REQUIRED')
    try:
        value=json.loads(_pack(trust))
        genesis=value['genesis']
        expected={'accounts','chain_id','decimals','genesis_time_unix','schema','supply_atomic','symbol','validators'}
        if (not isinstance(genesis,dict) or set(genesis)!=expected
            or genesis['schema']!='gg.native.genesis.v1'
            or not isinstance(genesis['chain_id'],str) or not re.fullmatch(r'ggnet:[0-9a-f]{24}',genesis['chain_id'])
            or type(genesis['decimals']) is not int or genesis['decimals']!=6
            or genesis['supply_atomic']!='1000000000000' or genesis['symbol']!='GG-NET-TEST'
            or type(genesis['genesis_time_unix']) is not int or not 0<genesis['genesis_time_unix']<2**53):
            raise ValueError('invalid')
        for name in ('accounts','validators'):
            entries=genesis[name]
            if (not isinstance(entries,list) or len(entries)!=4
                or any(not isinstance(entry,str) or not re.fullmatch('[0-9a-f]{64}',entry) for entry in entries)
                or len(set(entries))!=4):raise ValueError('invalid')
        if set(genesis['accounts']) & set(genesis['validators']):raise ValueError('invalid')
        if value['genesis_hash']!=hashlib.sha256(_pack(genesis)).hexdigest():raise ValueError('invalid')
        return value
    except (KeyError,ValueError,TypeError,OverflowError,RecursionError):
        raise ValueError('GG_LIGHT_TRUST_INVALID') from None


def _light_fingerprint():
    files=[SOURCES/'go.mod',SOURCES/'go.sum',SOURCES/'toolchain.json',SOURCES/'ledger.go',SOURCES/'verify.go',SOURCES/'light/wasm_main.go']
    entries={path.relative_to(SOURCES).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    return hashlib.sha256(_pack(entries)).hexdigest()


def _checked_artifacts():
    manifest_path=TOOLS/'light-manifest.json'
    if not manifest_path.is_file() or manifest_path.stat().st_size>8192:
        raise ValueError('GG_LIGHT_BUILD_REQUIRED')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('schema')!='gg.consensus.light-build.v1' or manifest.get('source_sha256')!=_light_fingerprint()
        or manifest.get('cometbft')!='v0.40.0' or manifest.get('goos')!='js' or manifest.get('goarch')!='wasm'):
        raise ValueError('GG_LIGHT_REBUILD_REQUIRED')
    for filename,limit,hash_key,size_key in [('verifier.wasm',32*1024*1024,'wasm_sha256','wasm_bytes'),('wasm_exec.js',128*1024,'runtime_sha256','runtime_bytes')]:
        path=TOOLS/filename
        if not path.is_file() or not 0<path.stat().st_size<=limit or path.stat().st_size!=manifest.get(size_key):
            raise ValueError('GG_LIGHT_ARTIFACT_INVALID')
        digest=hashlib.sha256()
        with path.open('rb') as incoming:
            for chunk in iter(lambda:incoming.read(64*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=manifest.get(hash_key):raise ValueError('GG_LIGHT_ARTIFACT_CHANGED')
    for filename,_ in _PUBLIC_FILES.values():
        path=ASSETS/filename
        if not path.is_file() or path.stat().st_size>128*1024:raise ValueError('GG_LIGHT_PAGE_MISSING')
    return manifest


class _Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    request_queue_size=4

    def __init__(self,trust):
        self.slots=threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.trust_json=_pack(trust)
        super().__init__(('127.0.0.1',0),_Handler)

    def get_request(self):
        request,address=super().get_request();request.settimeout(2)
        return request,address

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            try:request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
            except OSError:pass
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except Exception:
            self.slots.release();raise

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()

    def handle_error(self,request,address):
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    server_version='GG-Certificate'
    sys_version=''

    def log_message(self,*args):
        pass

    def _headers(self,status,content_type='text/plain; charset=utf-8',length=0):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(length))
        self.send_header('Content-Security-Policy',CSP)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close')
        self.end_headers();self.close_connection=True

    def _serve(self,head=False):
        expected=f'127.0.0.1:{self.server.server_port}'
        if (self.headers.get('Host')!=expected or self.headers.get('Sec-Fetch-Site')=='cross-site'
            or (self.headers.get('Origin') and self.headers['Origin']!='http://'+expected)
            or sum(len(key)+len(value) for key,value in self.headers.items())>8192):
            self._headers(403);return
        if self.headers.get('Content-Length') not in (None,'0') or self.headers.get('Transfer-Encoding'):
            self._headers(400);return
        if self.path=='/trust.json':
            data=self.server.trust_json;self._headers(200,'application/json; charset=utf-8',len(data))
            if not head:self.wfile.write(data)
            return
        entry=_PUBLIC_FILES.get(self.path)
        folder=ASSETS
        if entry is None:entry=_TOOL_FILES.get(self.path);folder=TOOLS
        if entry is None:self._headers(404);return
        filename,content_type=entry
        # Both path components come only from the fixed map, never from the URL.
        try:
            with (folder/filename).open('rb') as incoming:
                length=(folder/filename).stat().st_size
                self._headers(200,content_type,length)
                if not head:
                    for chunk in iter(lambda:incoming.read(64*1024),b''):self.wfile.write(chunk)
        except (OSError,ConnectionError):
            self.close_connection=True

    def do_GET(self):self._serve()
    def do_HEAD(self):self._serve(head=True)
    def do_POST(self):self._headers(405)
    def do_PUT(self):self._headers(405)
    def do_DELETE(self):self._headers(405)
    def do_OPTIONS(self):self._headers(405)


def _snapshot():
    if _server is None or _trust is None:
        return {'state':'STOPPED','url':'','pinned_chain_id':'','max_packet_bytes':MAX_PACKET_BYTES,'verify_timeout_ms':VERIFY_TIMEOUT_MS}
    return {'state':'RUNNING','url':f'http://127.0.0.1:{_server.server_port}/',
            'pinned_chain_id':_trust['genesis']['chain_id'],'max_packet_bytes':MAX_PACKET_BYTES,
            'verify_timeout_ms':VERIFY_TIMEOUT_MS,'wasm_bytes':_trust['verifier_wasm_bytes']}


def snapshot():
    with _LOCK:return _snapshot()


def start(trust):
    """Explicitly open a fresh public session pin. No browser is launched here."""
    global _server,_thread,_trust
    pinned=_pin(trust);manifest=_checked_artifacts()
    # A fresh listener means an already open page can never silently acquire a
    # different trust anchor by fetching from a reused server endpoint.
    with _LOCK:
        stop()
        pinned['schema']='gg.consensus.web-trust.v1'
        pinned['verifier_wasm_bytes']=manifest['wasm_bytes']
        _server=_Server(pinned);_trust=pinned
        _thread=threading.Thread(target=_server.serve_forever,name='GG-public-certificate-viewer',daemon=True)
        _thread.start()
        return _snapshot()


def stop():
    global _server,_thread,_trust
    with _LOCK:
        previous=_server;thread=_thread
        _server=None;_thread=None;_trust=None
    if previous is not None:
        previous.shutdown();previous.server_close()
        if thread is not None and thread is not threading.current_thread():thread.join(timeout=2)
    with _LOCK:return _snapshot()


atexit.register(stop)
