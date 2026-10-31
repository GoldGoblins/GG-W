"""Bounded record fragments inside existing authenticated LAN frames.

Reassembly only proves byte transport integrity. The DAG still verifies the
complete canonical block and every transaction signature before admission.
"""
import base64
import hashlib
import re

SMALL_WIRE_BYTES = 44*1024
CHUNK_BYTES = 32*1024
MAX_BLOCK_WIRE_BYTES = 32*1024*1024
_HASH = re.compile(r'^[0-9a-f]{64}$')


def record_frames(record, *, maximum=MAX_BLOCK_WIRE_BYTES):
    raw = record.get('wire')
    identifier = record.get('hash')
    cursor = record.get('admission_index')
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= maximum:
        raise ValueError('GG_LAN_WIRE_SIZE')
    if not isinstance(identifier, str) or not _HASH.fullmatch(identifier) or type(cursor) is not int or not 0 <= cursor <= 4095:
        raise ValueError('GG_LAN_DATA')
    if len(raw) <= SMALL_WIRE_BYTES:
        yield 'DATA', {'hash': identifier, 'admission_index': cursor, 'wire': base64.b64encode(raw).decode('ascii')}
        return
    wire_digest = hashlib.sha256(raw).hexdigest()
    parts = (len(raw)+CHUNK_BYTES-1)//CHUNK_BYTES
    yield 'DATA_START', {'hash': identifier, 'admission_index': cursor, 'size': len(raw),
                         'wire_sha256': wire_digest, 'parts': parts}
    for offset in range(0, len(raw), CHUNK_BYTES):
        yield 'DATA_PART', {'hash': identifier, 'offset': offset,
                            'data': base64.b64encode(raw[offset:offset+CHUNK_BYTES]).decode('ascii')}
    yield 'DATA_END', {'hash': identifier, 'size': len(raw), 'wire_sha256': wire_digest}


class RecordAssembler:
    def __init__(self, *, maximum=MAX_BLOCK_WIRE_BYTES):
        if type(maximum) is not int or not 1 <= maximum <= MAX_BLOCK_WIRE_BYTES:
            raise ValueError('GG_LAN_WIRE_SIZE')
        self.maximum = maximum
        self._meta = None
        self._data = bytearray()

    @property
    def pending(self):
        return self._meta is not None

    @property
    def buffered_bytes(self):
        return len(self._data)

    def close(self):
        self._meta = None
        self._data = bytearray()

    @staticmethod
    def _decode(value, maximum):
        if not isinstance(value, str) or len(value) > (maximum+2)//3*4:
            raise ValueError('GG_LAN_WIRE_SIZE')
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, TypeError):
            raise ValueError('GG_LAN_WIRE_ENCODING') from None
        if not raw or len(raw) > maximum:
            raise ValueError('GG_LAN_WIRE_SIZE')
        return raw

    def feed(self, kind, payload):
        try:
            return self._feed(kind, payload)
        except Exception:
            self.close()
            raise

    def _feed(self, kind, payload):
        if not isinstance(payload, dict):
            raise ValueError('GG_LAN_DATA')
        if kind == 'DATA':
            if self.pending or set(payload) != {'hash', 'admission_index', 'wire'}:
                raise ValueError('GG_LAN_DATA')
            identifier, cursor = payload['hash'], payload['admission_index']
            if not isinstance(identifier, str) or not _HASH.fullmatch(identifier) or type(cursor) is not int or not 0 <= cursor <= 4095:
                raise ValueError('GG_LAN_DATA')
            raw = self._decode(payload['wire'], min(self.maximum, SMALL_WIRE_BYTES))
            return {'hash': identifier, 'admission_index': cursor, 'wire': raw}
        if kind == 'DATA_START':
            if self.pending or set(payload) != {'hash', 'admission_index', 'size', 'wire_sha256', 'parts'}:
                raise ValueError('GG_LAN_CHUNK_START')
            identifier, cursor, size, digest, parts = (payload[k] for k in ('hash', 'admission_index', 'size', 'wire_sha256', 'parts'))
            if not isinstance(identifier, str) or not _HASH.fullmatch(identifier) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
                raise ValueError('GG_LAN_CHUNK_START')
            if type(cursor) is not int or not 0 <= cursor <= 4095 or type(size) is not int or not SMALL_WIRE_BYTES < size <= self.maximum:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            if type(parts) is not int or parts != (size+CHUNK_BYTES-1)//CHUNK_BYTES:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            self._meta = dict(payload)
            return None
        if kind == 'DATA_PART':
            if not self.pending or set(payload) != {'hash', 'offset', 'data'}:
                raise ValueError('GG_LAN_CHUNK_PART')
            if payload['hash'] != self._meta['hash'] or type(payload['offset']) is not int or payload['offset'] != len(self._data):
                raise ValueError('GG_LAN_CHUNK_ORDER')
            expected = min(CHUNK_BYTES, self._meta['size']-len(self._data))
            if expected <= 0:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            raw = self._decode(payload['data'], CHUNK_BYTES)
            if len(raw) != expected:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            self._data.extend(raw)
            return None
        if kind == 'DATA_END':
            if not self.pending or set(payload) != {'hash', 'size', 'wire_sha256'}:
                raise ValueError('GG_LAN_CHUNK_END')
            meta = self._meta
            if payload != {k: meta[k] for k in ('hash', 'size', 'wire_sha256')} or len(self._data) != meta['size']:
                raise ValueError('GG_LAN_CHUNK_END')
            if hashlib.sha256(self._data).hexdigest() != meta['wire_sha256']:
                raise ValueError('GG_LAN_CHUNK_HASH')
            record = {'hash': meta['hash'], 'admission_index': meta['admission_index'], 'wire': bytes(self._data)}
            self.close()
            return record
        raise ValueError('GG_LAN_DATA')
