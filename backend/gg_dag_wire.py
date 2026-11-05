"""Bounded record fragments inside existing authenticated LAN frames.

Reassembly only proves byte transport integrity. The DAG still verifies the
complete canonical block and every transaction signature before admission.
"""
import base64
import hashlib
import re
from contextlib import nullcontext
from backend import gg_lossless_wire as lossless

SMALL_WIRE_BYTES = 44*1024
CHUNK_BYTES = 32*1024
MAX_BLOCK_WIRE_BYTES = 32*1024*1024
_HASH = re.compile(r'^[0-9a-f]{64}$')


def record_frames(record, *, maximum=MAX_BLOCK_WIRE_BYTES, resume_offset=0, codec=None, check=lambda:None, deadline=None, charge=lambda size:None, workspace=nullcontext):
    raw = record.get('wire')
    identifier = record.get('hash')
    cursor = record.get('admission_index')
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= maximum:
        raise ValueError('GG_LAN_WIRE_SIZE')
    if not isinstance(identifier, str) or not _HASH.fullmatch(identifier) or type(cursor) is not int or not 0 <= cursor <= 4095:
        raise ValueError('GG_LAN_DATA')
    if (type(resume_offset) is not int or not 0<=resume_offset<=len(raw)
            or resume_offset%CHUNK_BYTES and resume_offset!=len(raw) or resume_offset and len(raw)<=SMALL_WIRE_BYTES):
        raise ValueError('GG_LAN_CHUNK_RESUME')
    if codec not in (None,'gzip'):raise ValueError('GG_WIRE_CODEC_SELECTION')
    lossless.guard(check,deadline)
    if len(raw) <= SMALL_WIRE_BYTES:
        yield 'DATA', {'hash': identifier, 'admission_index': cursor, 'wire': base64.b64encode(raw).decode('ascii')}
        return
    wire_digest = hashlib.sha256(raw).hexdigest()
    parts = (len(raw)+CHUNK_BYTES-1)//CHUNK_BYTES
    start={'hash': identifier, 'admission_index': cursor, 'size': len(raw),'wire_sha256': wire_digest, 'parts': parts}
    if resume_offset:start['offset']=resume_offset
    yield 'DATA_START',start
    for offset in range(resume_offset, len(raw), CHUNK_BYTES):
        lossless.guard(check,deadline)
        if codec is not None:
            with workspace():
                data=lossless.encode(raw[offset:offset+CHUNK_BYTES],identifier,len(raw),wire_digest,offset,
                                     check=check,deadline=deadline,charge=charge)
        else:data={'hash': identifier, 'offset': offset,'data': base64.b64encode(raw[offset:offset+CHUNK_BYTES]).decode('ascii')}
        yield 'DATA_PART', data
    yield 'DATA_END', {'hash': identifier, 'size': len(raw), 'wire_sha256': wire_digest}


class RecordAssembler:
    def __init__(self, *, maximum=MAX_BLOCK_WIRE_BYTES, resume=None, codec=None, check=lambda:None, deadline=None, charge=lambda size:None, workspace=nullcontext):
        if type(maximum) is not int or not 1 <= maximum <= MAX_BLOCK_WIRE_BYTES:
            raise ValueError('GG_LAN_WIRE_SIZE')
        self.maximum = maximum
        self.resume=resume
        if codec not in (None,'gzip'):raise ValueError('GG_WIRE_CODEC_SELECTION')
        self.codec=codec;self.check=check;self.deadline=deadline;self.charge=charge;self.workspace=workspace
        self._meta = None
        self._data = bytearray()

    @property
    def pending(self):
        return self._meta is not None

    @property
    def buffered_bytes(self):
        return self.resume.offset if self.resume is not None and self.pending else len(self._data)

    def close(self, *, preserve=False):
        if self.resume is not None and not preserve:self.resume.discard_current()
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
            keys={'hash', 'admission_index', 'size', 'wire_sha256', 'parts'}
            if self.pending or set(payload) not in (keys,keys|{'offset'}) or 'offset' in payload and self.resume is None:
                raise ValueError('GG_LAN_CHUNK_START')
            identifier, cursor, size, digest, parts = (payload[k] for k in ('hash', 'admission_index', 'size', 'wire_sha256', 'parts'))
            if not isinstance(identifier, str) or not _HASH.fullmatch(identifier) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
                raise ValueError('GG_LAN_CHUNK_START')
            if type(cursor) is not int or not 0 <= cursor <= 4095 or type(size) is not int or not SMALL_WIRE_BYTES < size <= self.maximum:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            if type(parts) is not int or parts != (size+CHUNK_BYTES-1)//CHUNK_BYTES:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            offset=payload.get('offset',0)
            if type(offset) is not int or not 0<=offset<=size or offset%CHUNK_BYTES and offset!=size:
                raise ValueError('GG_LAN_CHUNK_RESUME')
            self._meta = {key:payload[key] for key in keys}
            if self.resume is not None:self.resume.start(self._meta,offset)
            return None
        if kind == 'DATA_PART':
            if self.codec is not None:
                if not self.pending:raise ValueError('GG_LAN_CHUNK_PART')
                with self.workspace():
                    raw=lossless.decode(payload,self._meta['hash'],self._meta['size'],self._meta['wire_sha256'],self.buffered_bytes,
                                        check=self.check,deadline=self.deadline,charge=self.charge)
                if self.resume is not None:self.resume.append(raw)
                else:self._data.extend(raw)
                return None
            if not self.pending or set(payload) != {'hash', 'offset', 'data'}:
                raise ValueError('GG_LAN_CHUNK_PART')
            if payload['hash'] != self._meta['hash'] or type(payload['offset']) is not int or payload['offset'] != self.buffered_bytes:
                raise ValueError('GG_LAN_CHUNK_ORDER')
            expected = min(CHUNK_BYTES, self._meta['size']-self.buffered_bytes)
            if expected <= 0:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            raw = self._decode(payload['data'], CHUNK_BYTES)
            if len(raw) != expected:
                raise ValueError('GG_LAN_CHUNK_SIZE')
            if self.resume is not None:self.resume.append(raw)
            else:self._data.extend(raw)
            return None
        if kind == 'DATA_END':
            if not self.pending or set(payload) != {'hash', 'size', 'wire_sha256'}:
                raise ValueError('GG_LAN_CHUNK_END')
            meta = self._meta
            if payload != {k: meta[k] for k in ('hash', 'size', 'wire_sha256')} or self.buffered_bytes != meta['size']:
                raise ValueError('GG_LAN_CHUNK_END')
            if self.resume is not None:raw=self.resume.finish()
            else:
                if hashlib.sha256(self._data).hexdigest() != meta['wire_sha256']:raise ValueError('GG_LAN_CHUNK_HASH')
                raw=bytes(self._data)
            record = {'hash': meta['hash'], 'admission_index': meta['admission_index'], 'wire': raw}
            self.close(preserve=True)
            return record
        raise ValueError('GG_LAN_DATA')
