"""Short, bounded media checks using real source bytes and decoded frames.

``verified`` means this check decoded frames, not that a remote provider will
remain available or that an entire programme was watched. No HEAD-only checks,
remote decoder URLs, credentials or unrestricted downloads are used. Standard
public AES-128 HLS keys are used only in memory/process input and never written
to files or reports; SAMPLE-AES and non-identity key formats remain unsupported.
VOD decoding goes through a byte-limited localhost range bridge so MP4
metadata at the end of a large file can be inspected without downloading it.

Call ``verify`` in a caller-owned bounded worker pool, never on the Qt thread.
``deadline`` is an optional absolute time.monotonic() value; ``cancel`` accepts
a threading.Event or zero-argument predicate. Reports contain source URLs for
the caller's playback routing, and must not be written to public logs.
"""
from __future__ import annotations

from functools import lru_cache
import http.client
import http.server
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
import urllib.request
import zlib

MAX_SECONDS = 12.0
MAX_BYTES = 4 * 1024 * 1024
MAX_CHECK_SECONDS = 30.0
MAX_CHECK_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MASTER_DEPTH = 3
LIVE_TTL_SECONDS = 900
VOD_TTL_SECONDS = 86400
_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


class _Unknown(Exception):
    pass


class _Failed(Exception):
    pass


def _url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 6000 or any(c in value for c in "\r\n\x00"):
        raise _Unknown("invalid_source")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise _Unknown("unsupported_source")
    return value


def _cancelled(cancel) -> bool:
    return bool(cancel and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()))


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 4
    max_repeats = 2

    def __init__(self, budget):
        self.budget = budget

    def http_error_302(self, request, response, code, message, headers):
        response.close()
        self.budget.check()
        target = urljoin(request.full_url, headers.get("Location") or headers.get("URI") or "")
        _url(target)
        if urlsplit(request.full_url).scheme == "https" and urlsplit(target).scheme != "https":
            raise _Unknown("insecure_redirect")
        redirects = int(getattr(request, "_gg_redirects", 0)) + 1
        if redirects > self.max_redirections:
            raise _Unknown("redirect_limit")
        # urllib's default redirect handler drains the entire redirect body.
        # Closing instead avoids uncounted/unbounded provider payloads.
        redirected = urllib.request.Request(target, headers=dict(request.headers), method="GET")
        redirected._gg_redirects = redirects
        self.budget.requests += 1
        return self.parent.open(redirected, timeout=min(4.0, self.budget.remaining()))

    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302


class _Budget:
    def __init__(self, deadline=None, cancel=None, *, headers=None, max_seconds=None, max_bytes=None):
        self.started = time.monotonic()
        seconds = float(MAX_SECONDS if max_seconds is None else max_seconds)
        size = int(MAX_BYTES if max_bytes is None else max_bytes)
        if not math.isfinite(seconds) or seconds <= 0 or size <= 0:
            raise ValueError("MEDIA_CHECK_BUDGET_INVALID")
        self.max_seconds = min(MAX_CHECK_SECONDS, seconds)
        self.max_bytes = min(MAX_CHECK_BYTES, size)
        # Reserve time for terminating a decoder and closing the loopback bridge.
        self.deadline = min(float(deadline) if deadline is not None else math.inf, self.started + self.max_seconds - .35)
        self.cancel = cancel
        self.downloaded = 0
        self.requests = 0
        self.lock = threading.RLock()
        self.hls_keys = {}
        self.headers = dict(headers or {})
        self.opener = urllib.request.build_opener(_Redirects(self))

    def check(self):
        if _cancelled(self.cancel):
            raise _Unknown("cancelled")
        if time.monotonic() >= self.deadline:
            raise _Unknown("timeout")

    def remaining(self):
        self.check()
        return max(.001, self.deadline - time.monotonic())

    def fetch(self, source, *, start=0, count=128 * 1024, manifest=False, ranged=True):
        with self.lock:
            self.check()
            source = _url(source)
            count = min(int(count), self.max_bytes - self.downloaded)
            if count <= 0:
                raise _Unknown("byte_limit")
            headers = {"User-Agent": "GG-AI-Desktop-Media-Check/1.0", "Accept-Encoding": "identity",
                       "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*" if manifest else "*/*"}
            headers.update(self.headers)
            if not manifest and ranged:
                headers["Range"] = f"bytes={int(start)}-{int(start) + count - 1}"
            self.requests += 1
            request = urllib.request.Request(source, headers=headers, method="GET")
            try:
                with self.opener.open(request, timeout=min(4.0, self.remaining())) as response:
                    final_source = _url(response.geturl())
                    status = int(response.status)
                    content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].lower()
                    content_range = str(response.headers.get("Content-Range", ""))
                    declared = response.headers.get("Content-Length")
                    try:
                        declared_length = int(declared) if declared is not None else None
                    except ValueError:
                        declared_length = None
                    chunks, size, wire_size, ended = [], 0, 0, False
                    encoding = str(response.headers.get("Content-Encoding", "")).casefold().strip()
                    if encoding not in ("", "identity", "gzip", "x-gzip"):
                        raise _Unknown("unsupported_content_encoding")
                    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding in ("gzip", "x-gzip") else None
                    read = getattr(response, "read1", response.read)
                    while size < count:
                        self.check()
                        # read1 returns after one socket read, allowing trickle
                        # responses to be stopped by the shared item deadline.
                        raw_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                        if raw_socket is not None:
                            raw_socket.settimeout(min(4.0, self.remaining()))
                        remaining_wire = self.max_bytes - self.downloaded
                        if remaining_wire <= 0:
                            raise _Unknown("byte_limit")
                        block = read(min(32 * 1024, remaining_wire, count - size if inflater is None else 32 * 1024))
                        if not block:
                            ended = True
                            break
                        wire_size += len(block)
                        self.downloaded += len(block)
                        try:
                            decoded = inflater.decompress(block, count - size) if inflater else block
                        except zlib.error:
                            raise _Unknown("invalid_content_encoding") from None
                        chunks.append(decoded)
                        size += len(decoded)
                    self.check()
                    data = b"".join(chunks)
                    return {"data": data, "source": final_source, "status": status,
                            "content_type": content_type, "content_range": "" if inflater else content_range,
                            "complete": bool((ended or declared_length is not None and wire_size >= declared_length)
                                             and (inflater is None or inflater.eof)),
                            "declared_length": None if inflater else declared_length}
            except HTTPError as error:
                code = error.code
                error.close()
                if code in (404, 410):
                    raise _Failed("http_not_found") from None
                if code in (401, 403):
                    raise _Failed("access_denied") from None
                if code == 429:
                    raise _Unknown("rate_limited") from None
                if code >= 500:
                    raise _Unknown("provider_error") from None
                if code in (400, 416) and not manifest and ranged and not start:
                    # A full-object server may reject Range yet still
                    # stream exactly the media that the player can open.
                    return self.fetch(source, start=0, count=count, ranged=False)
                if code == 416:
                    raise _Unknown("range_rejected") from None
                raise _Failed("http_rejected") from None
            except (TimeoutError, socket.timeout):
                raise _Unknown("timeout") from None
            except (URLError, OSError, http.client.HTTPException):
                raise _Unknown("network_error") from None


@lru_cache(maxsize=1)
def decoder_tools() -> dict[str, str]:
    """Resolve installed tools once, never scan application directories per row."""
    from backend.platform_support import find_executable
    return {name: find_executable(name) for name in ("ffprobe", "ffmpeg")}


def _format(data: bytes) -> str:
    if len(data) >= 12 and data[4:8] in (b"ftyp", b"moov", b"wide", b"mdat", b"free"):
        return "mov"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "matroska"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"RIFF") and data[8:12] == b"AVI ":
        return "avi"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    if len(data) > 2 and data[0] == 255 and data[1] & 0xF6 == 0xF0:
        return "aac"
    if data.startswith(b"ID3"):
        # Packed HLS AAC carries Apple's timestamp in an ID3v2 tag. Treating
        # every ID3 prefix as MP3 falsely rejected its separately hosted audio.
        if len(data) >= 10 and all(value < 128 for value in data[6:10]):
            offset = 10 + sum(value << shift for value, shift in zip(data[6:10], (21, 14, 7, 0)))
            if data[3] == 4 and data[5] & 0x10:
                offset += 10
            if len(data) >= offset + 2 and data[offset] == 255 and data[offset + 1] & 0xF6 == 0xF0:
                return "aac"
        return "mp3"
    if len(data) > 2 and data[0] == 255 and data[1] & 0xE0 == 0xE0:
        return "mp3"
    if len(data) >= 3 * 188 and any(all(data[offset + n * 188] == 0x47 for n in range(3)) for offset in range(min(188, len(data) - 376))):
        return "mpegts"
    if data.startswith(b"\x00\x00\x01\xba"):
        return "mpeg"
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(b"FLV"):
        return "flv"
    return ""


def _decode(source: str, media_format: str, budget: _Budget, *, remote=False) -> dict[str, Any]:
    binary = decoder_tools().get("ffprobe")
    if not binary:
        raise _Unknown("decoder_missing")
    budget.check()
    command = [binary, "-v", "error", "-threads", "1", "-probesize", "65536", "-analyzeduration", "250000",
               "-protocol_whitelist", "http,tcp" if remote else "file,pipe", "-f", media_format,
               # Older containers can place dozens of audio packets before
               # their first video packet. Sixteen packets falsely rejected
               # those playable sources; the shared byte/time budget still
               # bounds this larger decoded sample.
               "-read_intervals", "%+#128", "-show_frames", "-show_streams", "-show_entries",
               "frame=media_type,width,height,nb_samples:stream=codec_type,codec_name,width,height",
               "-of", "json", "-i", source]
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        while True:
            budget.check()
            try:
                output, _ = process.communicate(timeout=min(.1, budget.remaining()))
                break
            except subprocess.TimeoutExpired:
                continue
        budget.check()
        if len(output) > 512 * 1024:
            raise _Unknown("decoder_response_limit")
        try:
            payload = json.loads(output.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise _Unknown("decoder_inconclusive") from None
        frames = payload.get("frames", []) if isinstance(payload, dict) else []
        streams = payload.get("streams", []) if isinstance(payload, dict) else []
        video = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
        audio = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
        video_frames = sum(isinstance(frame, dict) and frame.get("media_type") == "video" and int(frame.get("width") or 0) > 0 and int(frame.get("height") or 0) > 0 for frame in frames)
        audio_frames = sum(isinstance(frame, dict) and frame.get("media_type") == "audio" and int(frame.get("nb_samples") or 0) > 0 for frame in frames)
        return {"video_stream": bool(video), "audio_stream": bool(audio), "video_frames": video_frames,
                "audio_frames": audio_frames, "video_codec": str(video[0].get("codec_name", ""))[:40] if video else "",
                "audio_codec": str(audio[0].get("codec_name", ""))[:40] if audio else "",
                "decoder_exit_ok": process.returncode == 0}
    except OSError:
        raise _Unknown("decoder_unavailable") from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.communicate(timeout=.2)
            except subprocess.TimeoutExpired:
                pass


class _RangeBridge:
    """Expose only one fixed upstream object, enforcing its shared byte budget."""
    def __init__(self, budget, source, total, first, tail):
        self.budget, self.source, self.total = budget, source, total
        self.cache = [(0, first["data"]), (total - len(tail["data"]), tail["data"])]
        self.error = ""
        bridge = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != "/probe":
                    self.send_error(404)
                    return
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", "bytes=0-"))
                if not match:
                    self.send_error(416)
                    return
                start = int(match.group(1))
                requested_end = min(int(match.group(2)) if match.group(2) else bridge.total - 1, bridge.total - 1)
                if start >= bridge.total or requested_end < start:
                    self.send_error(416)
                    return
                try:
                    with bridge.budget.lock:
                        bridge.budget.check()
                        data = None
                        for offset, cached in bridge.cache:
                            if offset <= start < offset + len(cached):
                                data = cached[start - offset:min(len(cached), requested_end - offset + 1)]
                                break
                        if data is None:
                            piece = bridge.budget.fetch(bridge.source, start=start, count=min(1024 * 1024, requested_end - start + 1))
                            parsed = _RANGE.fullmatch(piece["content_range"])
                            if piece["status"] != 206 or not parsed or int(parsed.group(1)) != start:
                                raise _Unknown("range_unsupported")
                            data = piece["data"]
                            bridge.cache.append((start, data))
                    if not data:
                        raise _Unknown("empty_media")
                    self.send_response(206)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{start + len(data) - 1}/{bridge.total}")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                except (_Unknown, _Failed) as error:
                    bridge.error = str(error)
                    try:
                        self.send_error(503)
                    except OSError:
                        pass
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True, name="gg-media-range-check")

    def __enter__(self):
        self.thread.start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/probe"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=.1)


def _attributes(line):
    return {key: value.strip('"') for key, value in _ATTR.findall(line)}


def _playlist(source, budget, *, depth=0, initial=None):
    if depth > MAX_MASTER_DEPTH:
        raise _Unknown("playlist_depth")
    result = initial if initial is not None else budget.fetch(source, count=MAX_MANIFEST_BYTES, manifest=True)
    try:
        text = result["data"].decode("utf-8-sig")
    except UnicodeError:
        raise _Failed("invalid_playlist") from None
    if not text.lstrip().startswith("#EXTM3U"):
        raise _Failed("invalid_playlist")
    if len(result["data"]) > MAX_MANIFEST_BYTES or len(result["data"]) >= MAX_MANIFEST_BYTES and not result["complete"]:
        raise _Unknown("playlist_too_large")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    variants, audio, active = [], {}, None
    for line in lines:
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = _attributes(line)
            if attrs.get("TYPE") == "AUDIO" and attrs.get("URI"):
                group = attrs.get("GROUP-ID", "")
                if group not in audio or attrs.get("DEFAULT") == "YES":
                    audio[group] = urljoin(result["source"], attrs["URI"])
        elif line.startswith("#EXT-X-STREAM-INF:"):
            active = _attributes(line)
        elif not line.startswith("#") and active is not None:
            codecs = active.get("CODECS", "").lower()
            if "RESOLUTION" in active or not codecs or any(codec in codecs for codec in ("avc", "hev", "hvc", "vp9", "vp0", "av01")):
                try:
                    bitrate = int(active.get("AVERAGE-BANDWIDTH") or active.get("BANDWIDTH") or 0)
                except ValueError:
                    bitrate = 0
                variants.append((bitrate, urljoin(result["source"], line), active.get("AUDIO", "")))
            active = None
    if variants:
        # A smaller valid rendition fits a meaningful decoded sample inside
        # the bounded check. The player may subsequently adapt quality.
        selected = min(variants, key=lambda item: item[0] or math.inf)
        nested = _playlist(selected[1], budget, depth=depth + 1)
        nested["audio_source"] = audio.get(selected[2]) or nested.get("audio_source")
        return nested
    segments, init, byte_range, cipher = [], None, None, None
    offsets = {}
    sequence = 0
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                sequence = int(line.split(":", 1)[1])
                if not 0 <= sequence < 2**128:
                    raise ValueError
            except ValueError:
                raise _Unknown("invalid_media_sequence") from None
        elif line.startswith("#EXT-X-KEY:"):
            attrs = _attributes(line)
            method, keyformat = attrs.get("METHOD"), attrs.get("KEYFORMAT", "identity")
            if method == "NONE":
                cipher = None
            elif method != "AES-128" or keyformat != "identity":
                cipher = {"unsupported": True}
            else:
                key_source = attrs.get("URI")
                if not key_source:
                    raise _Unknown("invalid_hls_key")
                iv = attrs.get("IV")
                if iv is not None:
                    if not re.fullmatch(r"0[xX][0-9a-fA-F]{1,32}", iv):
                        raise _Unknown("invalid_hls_iv")
                    iv = int(iv, 16).to_bytes(16, "big")
                cipher = {"source": _url(urljoin(result["source"], key_source)), "iv": iv}
        elif line.startswith("#EXT-X-MAP:"):
            attrs = _attributes(line)
            if attrs.get("URI"):
                init = (urljoin(result["source"], attrs["URI"]), attrs.get("BYTERANGE"), cipher)
        elif line.startswith("#EXT-X-BYTERANGE:"):
            byte_range = line.split(":", 1)[1]
        elif not line.startswith("#"):
            target = urljoin(result["source"], line)
            start, length = 0, None
            if byte_range:
                match = re.fullmatch(r"(\d+)(?:@(\d+))?", byte_range)
                if not match:
                    raise _Unknown("invalid_segment_range")
                length = int(match.group(1))
                if not match.group(2) and target not in offsets:
                    raise _Unknown("ambiguous_segment_range")
                start = int(match.group(2)) if match.group(2) else offsets[target]
                offsets[target] = start + length
            segment_cipher = dict(cipher, sequence=sequence) if cipher else None
            segments.append((target, start, length, init, segment_cipher))
            sequence += 1
            byte_range = None
    if not segments:
        raise _Unknown("empty_playlist")
    selected = segments[0] if "#EXT-X-ENDLIST" in lines else segments[max(0, len(segments) - 2)]
    if selected[4] and selected[4].get("unsupported"):
        raise _Unknown("encrypted_stream")
    return {"source": result["source"], "segment": selected, "audio_source": None}


def _hls_key(cipher, budget):
    if not cipher:
        return None
    if cipher.get("unsupported"):
        raise _Unknown("encrypted_stream")
    source = cipher["source"]
    if source not in budget.hls_keys:
        try:
            response = budget.fetch(source, count=17, manifest=True)
        except _Failed:
            raise _Unknown("hls_key_unavailable") from None
        if len(response["data"]) != 16 or not response["complete"]:
            raise _Unknown("invalid_hls_key")
        budget.hls_keys[source] = response["data"]
    return budget.hls_keys[source]


def _decrypt_sample(data, cipher, budget, *, initialization=False):
    """Decode public identity AES-128 without persisting its key or IV.

    FFmpeg's installed crypto protocol decrypts only a bounded local ciphertext
    file. It receives no remote URL and cannot request arbitrary resources.
    """
    if not cipher:
        return data
    if cipher.get("unsupported"):
        raise _Unknown("encrypted_stream")
    if initialization and cipher.get("iv") is None:
        raise _Unknown("encrypted_init_iv_missing")
    iv = cipher.get("iv")
    if iv is None:
        iv = int(cipher["sequence"]).to_bytes(16, "big")
    key = _hls_key(cipher, budget)
    # A partial encrypted segment can still provide a real decoded sample.
    # CBC decryption must end at a cipher-block boundary.
    data = data[:len(data) // 16 * 16]
    if not data:
        raise _Unknown("empty_media")
    binary = decoder_tools().get("ffmpeg")
    if not binary:
        raise _Unknown("decoder_missing")
    process = None
    with tempfile.TemporaryDirectory(prefix="gg-media-cipher-") as directory:
        path = Path(directory) / "sample.bin"
        path.write_bytes(data)
        command = [binary, "-v", "error", "-threads", "1", "-protocol_whitelist", "file,crypto",
                   "-key", key.hex(), "-iv", iv.hex(), "-f", "data", "-i", "crypto:" + str(path),
                   "-map", "0:0", "-c", "copy", "-f", "data", "pipe:1"]
        try:
            budget.check()
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            while True:
                budget.check()
                try:
                    output, _ = process.communicate(timeout=min(.1, budget.remaining()))
                    break
                except subprocess.TimeoutExpired:
                    continue
            budget.check()
            if len(output) > len(data):
                raise _Unknown("decoder_response_limit")
            if not output:
                raise _Unknown("hls_decryption_inconclusive")
            return output
        except OSError:
            raise _Unknown("decoder_unavailable") from None
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                try:
                    process.communicate(timeout=.2)
                except subprocess.TimeoutExpired:
                    pass


def _segment_sample(playlist, budget, *, maximum):
    source, start, length, init, cipher = playlist["segment"]
    _hls_key(cipher, budget)
    if init:
        _hls_key(init[2], budget)
    maximum = max(1, min(maximum, budget.max_bytes - budget.downloaded))
    data = b""
    if init:
        init_source, init_range, init_cipher = init
        init_start, init_count = 0, min(96 * 1024, maximum // 3)
        if init_range:
            match = re.fullmatch(r"(\d+)@(\d+)", init_range)
            if not match:
                raise _Unknown("ambiguous_init_range")
            init_count, init_start = min(int(match.group(1)), init_count), int(match.group(2))
        data = budget.fetch(init_source, start=init_start, count=init_count)["data"]
        data = _decrypt_sample(data, init_cipher, budget, initialization=True)
    count = max(1, min(maximum - len(data), length if length is not None else maximum))
    result = budget.fetch(source, start=start, count=count)
    if start and result["status"] != 206:
        raise _Unknown("range_unsupported")
    data += _decrypt_sample(result["data"], cipher, budget)
    if not data:
        raise _Unknown("empty_media")
    media_format = _format(data)
    if not media_format:
        if result["content_type"] in ("text/html", "application/json"):
            raise _Failed("non_media_response")
        raise _Unknown("unrecognized_media")
    with tempfile.TemporaryDirectory(prefix="gg-media-check-") as directory:
        path = Path(directory) / "sample.bin"
        path.write_bytes(data)
        evidence = _decode(str(path), media_format, budget)
        if cipher:
            evidence["public_aes128_hls"] = True
        return evidence


def _sufficient(evidence, *, audio_only=False):
    if audio_only:
        return evidence.get("audio_frames", 0) > 0
    return evidence.get("video_frames", 0) > 0 and (not evidence.get("audio_stream") or evidence.get("audio_frames", 0) > 0)


def _complete_moov(data):
    offset = 0
    for _ in range(100):
        if offset + 8 > len(data):
            return False
        size = int.from_bytes(data[offset:offset + 4], "big")
        atom = data[offset + 4:offset + 8]
        if size == 1:
            if offset + 16 > len(data):
                return False
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
        if size < 8 or offset + size > len(data):
            return False
        if atom == b"moov":
            return True
        offset += size
    return False


def _decode_sample(data, media_format, budget):
    with tempfile.TemporaryDirectory(prefix="gg-media-check-") as directory:
        path = Path(directory) / "sample.bin"
        path.write_bytes(data)
        return _decode(str(path), media_format, budget)


def _finish(report, budget, live):
    checked_at = time.time()
    ttl = (LIVE_TTL_SECONDS if live else VOD_TTL_SECONDS) if report["status"] == "verified" else 0
    report.update(checked_at=checked_at, expires_at=checked_at + ttl, ttl_seconds=ttl,
                  elapsed_seconds=round(time.monotonic() - budget.started, 3), downloaded_bytes=budget.downloaded,
                  requests=budget.requests, eligible=report["status"] == "verified",
                  max_seconds=budget.max_seconds, max_bytes=budget.max_bytes)
    return report


def verify(row: dict[str, Any], *, deadline=None, cancel=None, max_seconds=None, max_bytes=None) -> dict[str, Any]:
    """Return a short-lived decoded playback proof for a catalogue source.

    Catalogue retention of a successful proof is managed by MediaIndex;
    selecting an older retained entry still requires a fresh playback proof.
    Optional retry budgets are limited to 30 seconds and 8 MiB per check;
    ordinary checks retain the 12-second/4-MiB defaults. An explicit deadline
    and cancellation continue to take precedence over an expanded budget.

    Unknown is deliberately different from failed: a missing decoder, byte
    budget, timeout, encryption or transient response cannot establish that a
    source is broken. ``failed`` is reserved for conclusive HTTP/access or
    content/protocol rejection during this check.
    """
    row = row if isinstance(row, dict) else {}
    source = row.get("source", "")
    report = {"schema": "gg.media.availability.v1", "status": "unknown", "original_source": source,
              "selected_source": source, "error": "", "evidence": {"decoded": False}}
    from backend.media_request import public_headers
    budget = _Budget(deadline, cancel, max_seconds=max_seconds, max_bytes=max_bytes)
    audio_only = str(row.get("kind", "")).upper() in ("RADIO", "MUSIC") or row.get("content_type") == "music"
    live = row.get("is_live") is True or row.get("content_type") == "live" or str(row.get("kind", "")).upper() == "RADIO"
    try:
        budget.headers = public_headers(row)
        if not isinstance(source, str) or not source:
            raise _Unknown("invalid_source")
        if "://" not in source or source.lower().startswith("file:"):
            from backend.platform_support import local_file_path
            path = local_file_path(source)
            if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
                raise _Unknown("unsupported_source")
            budget.check()
            if not path.is_file():
                raise _Failed("local_not_found")
            with path.open("rb") as handle:
                media_format = _format(handle.read(4096))
            if not media_format:
                raise _Unknown("unrecognized_media")
            decoded = _decode(str(path), media_format, budget)
            report["evidence"].update(decoded, transport="local_file", object_bytes=path.stat().st_size,
                                      decoder_input="local_file")
            if not _sufficient(decoded, audio_only=audio_only):
                raise _Unknown("no_decoded_frames")
            report["evidence"]["decoded"] = True
            report["status"] = "verified"
            return _finish(report, budget, False)
        source = _url(source)
        budget.check()
        if not decoder_tools().get("ffprobe"):
            raise _Unknown("decoder_missing")
        known_playlist = urlsplit(source).path.casefold().endswith(".m3u8")
        # Playlist GETs must not require byte-range support. Reuse this first
        # response when following the playlist, avoiding a duplicate request.
        first = budget.fetch(source, count=MAX_MANIFEST_BYTES if known_playlist or audio_only and live else 512 * 1024,
                             manifest=known_playlist)
        report["selected_source"] = first["source"]
        evidence = report["evidence"]
        evidence.update(http_response=first["status"], response_bytes=len(first["data"]))
        hls = first["data"].lstrip(b"\xef\xbb\xbf\r\n ").startswith(b"#EXTM3U")
        if hls:
            playlist = _playlist(first["source"], budget, initial=first)
            report["selected_source"] = playlist["source"]
            evidence["transport"] = "hls_segment"
            reserve = 160 * 1024 if playlist.get("audio_source") else 0
            decoded = _segment_sample(playlist, budget, maximum=max(1, budget.max_bytes - budget.downloaded - reserve))
            evidence.update(decoded)
            if playlist.get("audio_source"):
                alternative = _playlist(playlist["audio_source"], budget)
                decoded_audio = _segment_sample(alternative, budget, maximum=budget.max_bytes - budget.downloaded)
                evidence["separate_audio_frames"] = decoded_audio.get("audio_frames", 0)
                if decoded_audio.get("audio_frames", 0) <= 0:
                    raise _Unknown("audio_unverified")
                # This rendition's audio was decoded from its advertised
                # external audio group, so evaluate the combined rendition.
                decoded["audio_stream"] = True
                decoded["audio_frames"] = max(decoded.get("audio_frames", 0), decoded_audio["audio_frames"])
                decoded["audio_codec"] = decoded_audio.get("audio_codec", "")
                evidence.update(decoded)
            if not _sufficient(decoded, audio_only=audio_only):
                raise _Unknown("no_decoded_frames")
        else:
            media_format = _format(first["data"])
            if not media_format:
                if first["content_type"] in ("text/html", "application/json"):
                    raise _Failed("non_media_response")
                raise _Unknown("unrecognized_media")
            if live:
                evidence["transport"] = "live_media_bytes"
                decoded = _decode_sample(first["data"], media_format, budget)
            else:
                parsed = _RANGE.fullmatch(first["content_range"])
                decoded = {}
                if media_format != "mov" or _complete_moov(first["data"]):
                    decoded = _decode_sample(first["data"], media_format, budget)
                    evidence["decoder_input"] = "bounded_sample"
                # Range support is useful for seeking, but is not a condition
                # of ordinary progressive playback when actual frames decode.
                evidence.update(transport="progressive_media_bytes", range_verified=False)
                if not _sufficient(decoded, audio_only=audio_only):
                    if first["status"] != 206 or not parsed or int(parsed.group(1)) != 0:
                        raise _Unknown("range_unsupported")
                    total = int(parsed.group(3))
                    if total <= 0:
                        raise _Unknown("invalid_media_length")
                    tail = budget.fetch(first["source"], start=max(0, total - 32), count=min(total, 32))
                    tail_range = _RANGE.fullmatch(tail["content_range"])
                    if tail["status"] != 206 or not tail_range or int(tail_range.group(1)) != max(0, total - 32) or int(tail_range.group(3)) != total:
                        raise _Unknown("seek_unverified")
                    evidence.update(transport="seekable_range", range_verified=True, object_bytes=total)
                    with _RangeBridge(budget, first["source"], total, first, tail) as bridge:
                        decoded = _decode(bridge.url, media_format, budget, remote=True)
                        evidence["decoder_input"] = "bounded_range_bridge"
                        if not _sufficient(decoded, audio_only=audio_only) and bridge.error:
                            raise _Unknown(bridge.error)
            evidence.update(decoded)
            if not _sufficient(decoded, audio_only=audio_only):
                raise _Unknown("no_decoded_frames")
        budget.check()
        report["status"] = "verified"
        evidence["decoded"] = True
    except _Failed as error:
        report.update(status="failed", error=str(error))
    except _Unknown as error:
        report.update(status="unknown", error=str(error))
    except (OSError, ValueError, TypeError, OverflowError):
        report.update(status="unknown", error="check_inconclusive")
    return _finish(report, budget, live)


def is_fresh_verified(report: dict[str, Any] | None, *, now=None) -> bool:
    if not isinstance(report, dict) or report.get("status") != "verified" or not (report.get("evidence") or {}).get("decoded"):
        return False
    now = time.time() if now is None else float(now)
    try:
        return float(report["checked_at"]) <= now < float(report["expires_at"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
