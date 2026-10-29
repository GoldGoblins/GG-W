"""Owned loopback host for the static, keyless web verifier. Off by default."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import unquote,urlsplit

ROOT=Path(__file__).resolve().parents[1]/'knowledge/gg-node-web'
FILES={'index.html','core.mjs','app.mjs','sw.js','style.css','manifest.webmanifest'}
_lock=threading.RLock();_server=None;_thread=None


class Handler(SimpleHTTPRequestHandler):
    extensions_map=dict(SimpleHTTPRequestHandler.extensions_map,**{'.mjs':'text/javascript','.webmanifest':'application/manifest+json'})
    def setup(self):
        self.request.settimeout(3);super().setup()
    def send_head(self):
        name=unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
        if name not in FILES:self.send_error(404);return None
        return super().send_head()
    def end_headers(self):
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
        self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
    def log_message(self,*args):pass
    def list_directory(self,path):self.send_error(404);return None


class Server(ThreadingHTTPServer):
    daemon_threads=True;block_on_close=False
    def __init__(self,*args,**kwargs):
        self._slots=threading.BoundedSemaphore(4);super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self._slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except Exception:self._slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self._slots.release()


def start():
    global _server,_thread
    with _lock:
        if _server:return snapshot()
        server=Server(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
        thread=threading.Thread(target=server.serve_forever,name='gg-public-node-view',daemon=True)
        try:thread.start()
        except Exception:server.server_close();raise
        _server=server;_thread=thread
        return snapshot()


def stop():
    global _server,_thread
    with _lock:
        server=_server;_server=None;_thread=None
    if server:server.shutdown();server.server_close()
    return snapshot()


def snapshot():
    with _lock:return {'state':'RUNNING' if _server else 'STOPPED','url':'http://127.0.0.1:'+str(_server.server_port)+'/' if _server else '',
                      'binding':'LOOPBACK_ONLY','purpose':'STATIC_PUBLIC_VERIFIER','private_keys':False}
