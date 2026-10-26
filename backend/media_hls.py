"""Bounded, asynchronous selection of multiplexed HLS video variants.

Qt's FFmpeg backend can open every rendition of a master playlist. Hand it
one rendition when video and audio share that playlist, keeping the original
master for feeds with separate audio groups, failures and non-HLS sources.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from backend.media_contract import stream_allowed
from backend.media_request import requires_headers

MAX_MANIFEST_BYTES = 256 * 1024
MANIFEST_TIMEOUT_MS = 5000
_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def video_variant(source: str, manifest: str, attempt: int = 0) -> str:
    """Choose a bitrate ladder rung; never drop a separately hosted audio track."""
    if not manifest.lstrip("\ufeff\r\n ").startswith("#EXTM3U"):
        return source
    lines = manifest.splitlines()
    for line in lines:
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = dict((k, v.strip('"')) for k, v in _ATTR.findall(line))
            if attrs.get("TYPE") == "AUDIO" and attrs.get("URI"):
                return source
    variants = []
    attrs = None
    for line in lines:
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = dict((k, v.strip('"')) for k, v in _ATTR.findall(line))
        elif line and not line.startswith("#") and attrs is not None:
            try:
                target = stream_allowed(urljoin(source, line))
                bandwidth = int(attrs.get("AVERAGE-BANDWIDTH") or attrs["BANDWIDTH"])
                codecs = attrs.get("CODECS", "").lower()
                video = "RESOLUTION" in attrs or not codecs or any(
                    codec in codecs for codec in ("avc", "hvc", "hev", "vp0", "vp9", "av01", "mp4v"))
                if video and bandwidth > 0:
                    variants.append((bandwidth, target))
            except (ValueError, KeyError):
                pass
            attrs = None
    # Avoid spending retry rungs on duplicate entries for the same rendition.
    ordered = list(dict.fromkeys(url for _, url in sorted(variants, reverse=True)))
    return ordered[min(max(0, int(attempt)), len(ordered) - 1)] if ordered else source


class HlsVariantResolver(QObject):
    sourceReady = Signal(int, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.proxy = None

    def cancel(self):
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        proxy, self.proxy = self.proxy, None
        if proxy is not None:
            proxy.close()

    def resolve(self, source: str, attempt: int, ticket: int, row=None):
        self.cancel()
        try:
            stream_allowed(source)
        except ValueError:
            self.sourceReady.emit(ticket, source, source)
            return
        original = source
        # The selected player uses the same public request context as its
        # decoded proof. The relay also handles servers rejecting Range:0.
        if row is not None or requires_headers(row):
            try:
                from backend.media_stream_proxy import MediaStreamProxy
                self.proxy = MediaStreamProxy(dict(row, source=source))
                source = self.proxy.url
            except (ValueError, OSError):
                self.sourceReady.emit(ticket, original, original)
                return
        if not urlsplit(source).path.lower().endswith((".m3u8", ".m3u")):
            self.sourceReady.emit(ticket, original, source)
            return
        request = QNetworkRequest(QUrl(source))
        request.setTransferTimeout(MANIFEST_TIMEOUT_MS)
        request.setMaximumRedirectsAllowed(5)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.NoLessSafeRedirectPolicy)
        reply = self.manager.get(request)
        self.reply = reply
        reply.setReadBufferSize(MAX_MANIFEST_BYTES + 1)
        # A hard deadline also bounds a slow response that never finishes.
        deadline = QTimer(reply)
        deadline.setSingleShot(True)
        deadline.timeout.connect(reply.abort)
        deadline.start(MANIFEST_TIMEOUT_MS)

        def limit_response():
            if reply.bytesAvailable() > MAX_MANIFEST_BYTES:
                reply.abort()

        def finished():
            deadline.stop()
            if self.reply is not reply:
                return
            self.reply = None
            selected = source
            if reply.error() == QNetworkReply.NoError:
                try:
                    data = bytes(reply.readAll())
                    if len(data) <= MAX_MANIFEST_BYTES:
                        # Relative variant URLs belong to the final redirect URL.
                        selected = video_variant(reply.url().toString(), data.decode("utf-8-sig"), attempt)
                except (ValueError, UnicodeError):
                    pass
            reply.deleteLater()
            self.sourceReady.emit(ticket, original, selected)

        reply.readyRead.connect(limit_response)
        reply.finished.connect(finished)
