"""Bounded audio tags and a private metadata cache, without media decoding."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time

VERSION = 1
MAX_TAG_BYTES = 512 * 1024
MAX_VALUE_BYTES = 8192
MAX_FRAMES = 256
MAX_CACHE_BYTES = 32 * 1024 * 1024
FIELDS = ("title", "artist", "album", "genre", "track")


def _text(value):
    return " ".join(str(value or "").replace("\x00", " / ").split())[:512]


class _Reader:
    def __init__(self, stream, size):
        self.stream, self.size, self.remaining = stream, size, MAX_TAG_BYTES

    def read(self, count):
        count = min(max(0, int(count)), self.remaining)
        data = self.stream.read(count)
        self.remaining -= len(data)
        return data

    def seek(self, offset):
        self.stream.seek(max(0, min(self.size, int(offset))))

    def tell(self):
        return self.stream.tell()


def _syncsafe(data):
    return sum((byte & 127) << (7 * (len(data) - 1 - index)) for index, byte in enumerate(data))


def _id3_text(data):
    if not data:
        return ""
    encoding = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(data[0], "utf-8")
    return _text(data[1:].decode(encoding, "replace"))


def _id3(reader, result, start=0):
    reader.seek(start)
    header = reader.read(10)
    if len(header) != 10 or header[:3] != b"ID3" or header[3] not in (2, 3, 4):
        return start
    version, flags = header[3], header[5]
    end = min(reader.size, start + 10 + _syncsafe(header[6:10]))
    if flags & 0x40 and version in (3, 4):
        extended = reader.read(4)
        if len(extended) != 4:
            return end
        length = _syncsafe(extended) if version == 4 else int.from_bytes(extended, "big") + 4
        reader.seek(reader.tell() - 4 + max(4, length))
    names = {"TIT2": "title", "TT2": "title", "TPE1": "artist", "TP1": "artist",
             "TALB": "album", "TAL": "album", "TCON": "genre", "TCO": "genre",
             "TRCK": "track", "TRK": "track", "TPE2": "album_artist", "TP2": "album_artist"}
    for _ in range(MAX_FRAMES):
        width = 6 if version == 2 else 10
        if reader.tell() + width > end or reader.remaining < width:
            break
        frame = reader.read(width)
        if len(frame) != width or frame[0] == 0:
            break
        name = frame[:3 if version == 2 else 4].decode("ascii", "replace")
        size = int.from_bytes(frame[3:6], "big") if version == 2 else (
            _syncsafe(frame[4:8]) if version == 4 else int.from_bytes(frame[4:8], "big"))
        position = reader.tell()
        if size <= 0 or position + size > end:
            break
        # Artwork and unrelated frames are skipped by seeking, never loaded.
        if name in names:
            value = reader.read(min(size, MAX_VALUE_BYTES))
            if flags & 0x80:
                value = value.replace(b"\xff\x00", b"\xff")
            text = _id3_text(value)
            if text:
                result[names[name]] = text
        reader.seek(position + size)
    reader.seek(end)
    return end


def _id3v1(reader, result):
    if reader.size < 128:
        return
    reader.seek(reader.size - 128)
    tag = reader.read(128)
    if len(tag) != 128 or tag[:3] != b"TAG":
        return
    for field, value in (("title", tag[3:33]), ("artist", tag[33:63]), ("album", tag[63:93])):
        if not result.get(field):
            result[field] = _text(value.rstrip(b"\x00 ").decode("latin-1", "replace"))
    if tag[125] == 0 and tag[126]:
        result.setdefault("track", str(tag[126]))


def _vorbis(data, result):
    if len(data) < 8:
        return
    position = 4 + int.from_bytes(data[:4], "little")
    if position + 4 > len(data):
        return
    count = min(MAX_FRAMES, int.from_bytes(data[position:position + 4], "little"))
    position += 4
    names = {"TITLE": "title", "ARTIST": "artist", "ALBUMARTIST": "album_artist",
             "ALBUM": "album", "GENRE": "genre", "TRACKNUMBER": "track"}
    for _ in range(count):
        if position + 4 > len(data):
            break
        size = int.from_bytes(data[position:position + 4], "little")
        position += 4
        if size > len(data) - position:
            break
        field, separator, value = data[position:position + min(size, MAX_VALUE_BYTES)].partition(b"=")
        key = names.get(field.decode("ascii", "ignore").upper())
        if separator and key:
            value = _text(value.decode("utf-8", "replace"))
            result[key] = " / ".join(filter(None, (result.get(key), value))) if key in result else value
        position += size


def _flac(reader, result, start):
    reader.seek(start + 4)
    for _ in range(MAX_FRAMES):
        header = reader.read(4)
        if len(header) != 4:
            break
        size, position = int.from_bytes(header[1:4], "big"), reader.tell()
        if position + size > reader.size:
            break
        if header[0] & 127 == 4:
            _vorbis(reader.read(min(size, reader.remaining)), result)
            return
        reader.seek(position + size)
        if header[0] & 128:
            break


def _mp4(reader, result):
    names = {b"\xa9nam": "title", b"\xa9ART": "artist", b"aART": "album_artist",
             b"\xa9alb": "album", b"\xa9gen": "genre", b"trkn": "track"}
    visited = 0

    def boxes(start, end, tag=None, depth=0):
        nonlocal visited
        position = start
        while position + 8 <= end and visited < 1024 and depth <= 8 and reader.remaining >= 8:
            visited += 1
            reader.seek(position)
            header = reader.read(8)
            if len(header) != 8:
                return
            size, name = int.from_bytes(header[:4], "big"), header[4:8]
            payload = position + 8
            if size == 1:
                large = reader.read(8)
                if len(large) != 8:
                    return
                size, payload = int.from_bytes(large, "big"), position + 16
            elif size == 0:
                size = end - position
            boundary = position + size
            if boundary > end or boundary <= payload:
                return
            if name in (b"moov", b"udta", b"ilst", b"meta"):
                boxes(payload + (4 if name == b"meta" else 0), boundary, depth=depth + 1)
            elif name in names:
                boxes(payload, boundary, names[name], depth + 1)
            elif name == b"data" and tag:
                reader.seek(payload)
                value = reader.read(min(boundary - payload, MAX_VALUE_BYTES))
                if len(value) >= 8:
                    if tag == "track":
                        if len(value) >= 12:
                            result[tag] = str(int.from_bytes(value[10:12], "big"))
                    else:
                        encoding = "utf-16-be" if int.from_bytes(value[:4], "big") == 2 else "utf-8"
                        result[tag] = _text(value[8:].decode(encoding, "replace"))
            position = boundary

    boxes(0, reader.size)


def _riff(reader, result):
    position = 12
    names = {b"INAM": "title", b"IART": "artist", b"IPRD": "album", b"IGNR": "genre", b"ITRK": "track"}
    for _ in range(MAX_FRAMES):
        reader.seek(position)
        header = reader.read(8)
        if len(header) != 8:
            return
        size = int.from_bytes(header[4:8], "little")
        end = position + 8 + size
        if end > reader.size:
            return
        if header[:4] == b"LIST" and reader.read(4) == b"INFO":
            while reader.tell() + 8 <= end:
                frame = reader.read(8)
                if len(frame) != 8:
                    return
                length = int.from_bytes(frame[4:8], "little")
                payload = reader.tell()
                if payload + length > end:
                    return
                if frame[:4] in names:
                    result[names[frame[:4]]] = _text(reader.read(min(length, MAX_VALUE_BYTES)).rstrip(b"\x00").decode("utf-8", "replace"))
                reader.seek(payload + length + length % 2)
        position = end + size % 2


def read_audio_metadata(path: Path, *, size=None):
    """Read tags through fixed byte/frame budgets; never starts a decoder."""
    path = Path(path)
    result = {}
    try:
        with path.open("rb") as stream:
            reader = _Reader(stream, path.stat().st_size if size is None else size)
            start = _id3(reader, result)
            reader.seek(start)
            magic = reader.read(16)
            if magic[:4] == b"fLaC":
                _flac(reader, result, start)
            elif magic[:4] == b"OggS":
                reader.seek(start)
                data = reader.read(reader.remaining)
                for signature in (b"OpusTags", b"\x03vorbis"):
                    at = data.find(signature)
                    if at >= 0:
                        _vorbis(data[at + len(signature):], result)
                        break
            elif magic[4:8] in (b"ftyp", b"moov") or path.suffix.casefold() == ".m4a":
                _mp4(reader, result)
            elif magic[:4] == b"RIFF" and magic[8:12] == b"WAVE":
                _riff(reader, result)
            _id3v1(reader, result)
    except (OSError, ValueError, UnicodeError, struct.error):
        pass
    stem = re.sub(r"^\s*\d{1,3}\s*[.)_-]\s*", "", path.stem).strip()
    split = re.split(r"\s+[-–—]\s+", stem, maxsplit=1)
    if len(split) == 2 and all(part.strip() for part in split):
        result.setdefault("artist", _text(split[0]))
        result.setdefault("title", _text(split[1]))
    result["artist"] = _text(result.get("artist") or result.get("album_artist")) or "Okänd artist"
    result["title"] = _text(result.get("title")) or _text(stem.replace("_", " ")) or path.name
    result["album"] = _text(result.get("album"))
    result["genre"] = _text(result.get("genre"))
    track = re.match(r"\d{1,5}", str(result.get("track") or ""))
    result["track"] = int(track[0]) if track else 0
    return {field: result[field] for field in FIELDS}


class AudioMetadataCache:
    """One scan opens one private cache, rather than one process per song."""

    def __init__(self, path: Path):
        self.path, self.previous, self.current = Path(path), {}, {}
        try:
            if self.path.stat().st_size <= MAX_CACHE_BYTES:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if saved.get("version") == VERSION and isinstance(saved.get("items"), dict):
                    self.previous = saved["items"]
        except (OSError, ValueError, TypeError):
            pass

    def get(self, path: Path, stat):
        key = hashlib.sha256(os.path.normcase(str(path)).encode("utf-8")).hexdigest()
        fingerprint = [stat.st_mtime_ns, stat.st_size]
        previous = self.previous.get(key)
        if (isinstance(previous, dict) and previous.get("fingerprint") == fingerprint
                and isinstance(previous.get("metadata"), dict) and all(field in previous["metadata"] for field in FIELDS)):
            metadata = dict(previous["metadata"])
        else:
            metadata = read_audio_metadata(path, size=stat.st_size)
        self.current[key] = dict(fingerprint=fingerprint, metadata=metadata)
        return metadata

    def save(self, *, complete=True):
        items = self.current if complete else dict(self.previous, **self.current)
        data = json.dumps(dict(version=VERSION, items=items), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_CACHE_BYTES:
            return
        temporary = self.path.with_name(self.path.name + ".tmp-" + str(os.getpid()) + "-" + str(time.monotonic_ns()))
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary.write_bytes(data)
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
        except OSError:
            pass
        finally:
            temporary.unlink(missing_ok=True)
