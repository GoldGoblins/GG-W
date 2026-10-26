"""One selected public stream with its published UA/referrer for Qt playback.

Only URLs registered by the selected source and its HLS manifest are served.
Opaque loopback routes keep upstream URLs and public playback hints private.
Bodies stream through fixed buffers; no film, key, or response is persisted.
"""
from __future__ import annotations

import gzip
import math
from collections import OrderedDict
import http.server
import re
import secrets
import socket
import time
from pathlib import PurePosixPath
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit

from backend.media_contract import stream_allowed
from backend.media_request import public_headers

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_RESOURCES = 32768
BUFFER_BYTES = 64 * 1024
_URI = re.compile(r'URI="([^"]*)"')
_RANGE = re.compile(r"bytes=\d+-\d*")


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 4
    max_repeats = 2

    def http_error_302(self, request, response, code, message, headers):
        # urllib's normal redirect path drains an arbitrary response body.
        # This relay only needs the validated Location header.
        response.close()
        target = stream_allowed(urljoin(request.full_url, headers.get("Location") or headers.get("URI") or ""))
        redirects = int(getattr(request, "_gg_redirects", 0)) + 1
        if redirects > self.max_redirections:
            raise ValueError("MEDIA_STREAM_REDIRECT_LIMIT")
        redirected = urllib.request.Request(target, headers=dict(request.headers), method=request.get_method())
        redirected._gg_redirects = redirects
        return self.parent.open(redirected, timeout=8)

    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302


class MediaStreamProxy:
    def __init__(self, row):
        self.source = stream_allowed(str(row.get("source") or ""))
        self.headers = public_headers(row)
        self._token = secrets.token_urlsafe(24)
        self._lock = threading.RLock()
        self._resources = OrderedDict()
        self._urls = {}
        self._stopped = threading.Event()
        self._responses = set()
        self._clients = set()
        self._slots = threading.BoundedSemaphore(8)
        self.opener = urllib.request.build_opener(_Redirects())
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                proxy._serve(self)

            def do_HEAD(self):
                proxy._serve(self, head=True)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
            kwargs={"poll_interval": .05}, daemon=True, name="gg-media-public-stream")
        self.thread.start()
        self.url = self.register(self.source)

    def register(self, source):
        source = stream_allowed(source)
        with self._lock:
            if self._stopped.is_set():
                raise ValueError("MEDIA_STREAM_CLOSED")
            key = self._urls.get(source)
            if key is None:
                if len(self._resources) >= MAX_RESOURCES:
                    _, old_source = self._resources.popitem(last=False)
                    self._urls.pop(old_source, None)
                key = secrets.token_urlsafe(18)
                self._urls[source] = key
                self._resources[key] = source
            else:
                self._resources.move_to_end(key)
        extension = PurePosixPath(urlsplit(source).path).suffix.lower()
        suffix = (".m3u8" if extension in (".m3u8", ".m3u") else extension
                  if extension in (".ts", ".m4s", ".mp4", ".m4a", ".aac", ".mp3", ".vtt", ".key", ".cmfv", ".cmfa") else ".ts")
        return f"http://127.0.0.1:{self.server.server_port}/{self._token}/{key}{suffix}"

    def _manifest(self, source, text):
        if not text.lstrip("\ufeff\r\n ").startswith("#EXTM3U"):
            raise ValueError("MEDIA_STREAM_INVALID_MANIFEST")
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                line = _URI.sub(lambda match: 'URI="' + self.register(urljoin(source, match[1])) + '"', line)
            elif stripped:
                line = self.register(urljoin(source, stripped))
            lines.append(line)
        if any(line.startswith("#EXTINF:") for line in lines) and not any(line.startswith("#EXT-X-TARGETDURATION:") for line in lines):
            durations = []
            for line in lines:
                if line.startswith("#EXTINF:"):
                    try:
                        value = float(line[8:].partition(",")[0])
                        if math.isfinite(value) and 0 < value <= 86400:
                            durations.append(value)
                    except ValueError:
                        pass
            if durations:
                lines.insert(1, "#EXT-X-TARGETDURATION:" + str(math.ceil(max(durations))))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _serve(self, handler, head=False):
        prefix = "/" + self._token + "/"
        if (self._stopped.is_set() or not handler.path.startswith(prefix)
                or "?" in handler.path or "#" in handler.path):
            handler.send_error(404)
            return
        key = handler.path[len(prefix):].partition(".")[0]
        with self._lock:
            source = self._resources.get(key)
            if source:
                self._resources.move_to_end(key)
        if not source:
            handler.send_error(404)
            return
        if not self._slots.acquire(blocking=False):
            handler.send_error(503)
            return
        started = False
        response = None
        with self._lock:
            self._clients.add(handler.connection)
        handler.connection.settimeout(8)
        try:
            headers = dict(self.headers, **{"Accept-Encoding": "identity"})
            manifest_hint = urlsplit(source).path.lower().endswith((".m3u8", ".m3u"))
            byte_range = handler.headers.get("Range")
            if byte_range and not manifest_hint:
                if not _RANGE.fullmatch(byte_range):
                    handler.send_error(416)
                    return
                headers["Range"] = byte_range
            request = urllib.request.Request(source, headers=headers, method="HEAD" if head and not manifest_hint else "GET")
            try:
                response = self.opener.open(request, timeout=8)
            except HTTPError as error:
                if error.code not in (400, 416) or not byte_range or not byte_range.startswith("bytes=0-"):
                    raise
                error.close()
                headers.pop("Range", None)
                request = urllib.request.Request(source, headers=headers, method="GET")
                response = self.opener.open(request, timeout=8)
            with response:
                with self._lock:
                    if self._stopped.is_set():
                        return
                    self._responses.add(response)
                content_type = str(response.headers.get("Content-Type") or "application/octet-stream")
                encoding = str(response.headers.get("Content-Encoding") or "").casefold()
                manifest = manifest_hint or "mpegurl" in content_type.casefold()
                if manifest:
                    blocks, received = [], 0
                    deadline = time.monotonic() + 8
                    while received <= MAX_MANIFEST_BYTES:
                        if self._stopped.is_set() or time.monotonic() >= deadline:
                            raise TimeoutError("MEDIA_STREAM_MANIFEST_TIMEOUT")
                        data = response.read1(min(BUFFER_BYTES, MAX_MANIFEST_BYTES + 1 - received))
                        if not data:
                            break
                        blocks.append(data)
                        received += len(data)
                    data = b"".join(blocks)
                    if len(data) > MAX_MANIFEST_BYTES:
                        raise ValueError("MEDIA_STREAM_MANIFEST_LIMIT")
                    if encoding == "gzip":
                        import io
                        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                            data = compressed.read(MAX_MANIFEST_BYTES + 1)
                    if len(data) > MAX_MANIFEST_BYTES:
                        raise ValueError("MEDIA_STREAM_MANIFEST_LIMIT")
                    data = self._manifest(response.geturl(), data.decode("utf-8-sig"))
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    handler.send_header("Content-Length", str(len(data)))
                    handler.send_header("Cache-Control", "no-store")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    started = True
                    if not head:
                        handler.wfile.write(data)
                else:
                    handler.send_response(int(response.status))
                    handler.send_header("Content-Type", content_type)
                    for name in ("Content-Length", "Content-Range", "Accept-Ranges", "Content-Encoding"):
                        value = response.headers.get(name)
                        if value is not None:
                            handler.send_header(name, value)
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    started = True
                    if not head:
                        while not self._stopped.is_set():
                            data = response.read1(BUFFER_BYTES)
                            if not data:
                                break
                            handler.wfile.write(data)
                handler.close_connection = True
        except HTTPError as error:
            code = error.code if error.code in (400, 401, 403, 404, 410, 416, 429) else 502
            error.close()
            if not started:
                handler.send_error(code)
        except (OSError, ValueError, UnicodeError):
            if not started:
                try:
                    handler.send_error(502)
                except OSError:
                    pass
        finally:
            with self._lock:
                self._responses.discard(response)
                self._clients.discard(handler.connection)
            handler.close_connection = True
            self._slots.release()

    def close(self):
        if self._stopped.is_set():
            return
        self._stopped.set()
        with self._lock:
            responses = list(self._responses)
            clients = list(self._clients)
        for response in responses:
            upstream = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if upstream is not None:
                try:
                    upstream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            response.close()
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=.2)
        with self._lock:
            self._resources.clear()
            self._urls.clear()
