"""Versioned byte transport only; original admission and signatures are unchanged.

Each codec invocation has at most 32KiB input/output and 4KiB input steps.
Cancellation/deadlines are checked between finite stdlib calls. This is not an
OS-enforced CPU deadline and does not cache any signature/execution result.
"""
import base64
from contextlib import contextmanager
import errno
import hashlib
import math
import re
import time
import zlib

SCHEMA='gg.lossless-chunk-codec.v1'
CHUNK_BYTES=32*1024
STEP_BYTES=4096
WORKSPACE_BYTES=1024*1024
MAX_RAW=32*1024*1024
HASH=re.compile(r'[0-9a-f]{64}')
PROBE='WIRE_CODEC'
ACK='WIRE_CODEC_ACK'


def offer():return {'schema':SCHEMA,'chunk_bytes':CHUNK_BYTES,'codecs':['identity','gzip']}


def select(value,codec='gzip'):
    if (not isinstance(value,dict) or set(value)!={'schema','chunk_bytes','codecs'}
            or value['schema']!=SCHEMA or type(value['chunk_bytes']) is not int or value['chunk_bytes']!=CHUNK_BYTES
            or type(value['codecs']) is not list or any(type(item) is not str for item in value['codecs'])
            or value['codecs']!=['identity','gzip']):raise ValueError('GG_WIRE_CODEC_OFFER')
    if type(codec) is not str or codec not in ('identity','gzip'):raise ValueError('GG_WIRE_CODEC_SELECTION')
    return {'schema':SCHEMA,'chunk_bytes':CHUNK_BYTES,'codec':codec}


def selection(value):
    if (not isinstance(value,dict) or set(value)!={'schema','chunk_bytes','codec'}
            or value['schema']!=SCHEMA or type(value['chunk_bytes']) is not int
            or value['chunk_bytes']!=CHUNK_BYTES or value['codec'] not in ('identity','gzip')):
        raise ValueError('GG_WIRE_CODEC_SELECTION')
    return None if value['codec']=='identity' else 'gzip'


def guard(check=lambda:None,deadline=None):
    check()
    if deadline is not None:
        if type(deadline) not in (int,float) or not math.isfinite(deadline):raise ValueError('GG_WIRE_CODEC_DEADLINE')
        if time.monotonic()>=deadline:raise ValueError('GG_WIRE_CODEC_DEADLINE')


def _context(identifier,total,digest,offset):
    if (type(identifier) is not str or not HASH.fullmatch(identifier) or type(digest) is not str or not HASH.fullmatch(digest)
            or type(total) is not int or not 0<total<=MAX_RAW or type(offset) is not int
            or not 0<=offset<total or offset%CHUNK_BYTES):raise ValueError('GG_WIRE_CODEC_CONTEXT')
    return min(CHUNK_BYTES,total-offset)


def encode(raw,identifier,total,digest,offset,*,check=lambda:None,deadline=None,charge=lambda size:None):
    expected=_context(identifier,total,digest,offset)
    if type(raw) is not bytes or len(raw)!=expected:raise ValueError('GG_WIRE_CODEC_RAW_SIZE')
    guard(check,deadline);charge(len(raw))
    compressor=zlib.compressobj(1,zlib.DEFLATED,16+zlib.MAX_WBITS,1)
    encoded=[]
    for start in range(0,len(raw),STEP_BYTES):
        guard(check,deadline);encoded.append(compressor.compress(raw[start:start+STEP_BYTES]))
    guard(check,deadline);encoded.append(compressor.flush())
    compressed=b''.join(encoded);guard(check,deadline)
    codec='gzip' if len(compressed)<len(raw) else 'identity'
    data=compressed if codec=='gzip' else raw
    return {'schema':SCHEMA,'codec':codec,'hash':identifier,'total':total,'wire_sha256':digest,
            'index':offset//CHUNK_BYTES,'offset':offset,'raw_size':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest(),
            'data':base64.b64encode(data).decode('ascii')}


def decode(value,identifier,total,digest,offset,*,check=lambda:None,deadline=None,charge=lambda size:None):
    expected=_context(identifier,total,digest,offset)
    fields={'schema','codec','hash','total','wire_sha256','index','offset','raw_size','raw_sha256','data'}
    if (not isinstance(value,dict) or set(value)!=fields or value['schema']!=SCHEMA or value['codec'] not in ('identity','gzip')
            or value['hash']!=identifier or type(value['total']) is not int or value['total']!=total or value['wire_sha256']!=digest
            or type(value['index']) is not int or value['index']!=offset//CHUNK_BYTES or type(value['offset']) is not int or value['offset']!=offset
            or type(value['raw_size']) is not int or value['raw_size']!=expected or type(value['raw_sha256']) is not str
            or not HASH.fullmatch(value['raw_sha256']) or type(value['data']) is not str
            or not 0<len(value['data'])<=4*((CHUNK_BYTES+2)//3)):
        raise ValueError('GG_WIRE_CODEC_CHUNK')
    guard(check,deadline);charge(expected)
    try:data=base64.b64decode(value['data'],validate=True)
    except (ValueError,TypeError):raise ValueError('GG_WIRE_CODEC_ENCODING') from None
    if not 0<len(data)<=CHUNK_BYTES or base64.b64encode(data).decode('ascii')!=value['data']:
        raise ValueError('GG_WIRE_CODEC_ENCODING')
    if value['codec']=='identity':raw=data
    else:
        if len(data)>=expected:raise ValueError('GG_WIRE_CODEC_NOT_SMALLER')
        inflater=zlib.decompressobj(16+zlib.MAX_WBITS);raw=bytearray()
        try:
            for start in range(0,len(data),STEP_BYTES):
                guard(check,deadline)
                part=inflater.decompress(data[start:start+STEP_BYTES],expected+1-len(raw));raw.extend(part)
                if len(raw)>expected or inflater.unconsumed_tail or inflater.unused_data:raise ValueError('GG_WIRE_CODEC_STREAM')
            if not inflater.eof:raise ValueError('GG_WIRE_CODEC_STREAM')
        except zlib.error:raise ValueError('GG_WIRE_CODEC_STREAM') from None
        raw=bytes(raw)
    guard(check,deadline)
    if len(raw)!=expected or hashlib.sha256(raw).hexdigest()!=value['raw_sha256']:raise ValueError('GG_WIRE_CODEC_RAW_HASH')
    return raw


@contextmanager
def lan_connection(peer,owner,deadline,*,bulk=False,cancel=None,check=lambda:None,enabled=True,operation='INCOMING'):
    """Negotiate before any original, retry only an old peer's empty refusal.

    All attempts share the caller's existing deadline. Bad authenticated ACKs
    and errors after yield are terminal; no original submission is replayed.
    """
    from backend.gg_lan_dag import MAX_FRAME,CONNECTION_SECONDS,_send
    for negotiate in ((True,False) if enabled else (False,)):
        guard(check,deadline)
        if enabled and not negotiate:peer._pace_connection(owner,operation,deadline=deadline,cancel=cancel)
        with peer._connection(owner,deadline=deadline,cancel=cancel,bulk=bulk) as sock:
            control=min(deadline,time.monotonic()+CONNECTION_SECONDS)
            session=peer._client_auth(sock,owner,control,check=check)
            if negotiate:
                peer._credit('out:'+owner,_send(sock,peer._frame(session,0,PROBE,offer()),MAX_FRAME,deadline=control))
                ack_bytes=0
                def received_ack(size):
                    nonlocal ack_bytes
                    ack_bytes+=size
                try:value,size=peer._read(sock,MAX_FRAME,deadline=control,check=check,on_bytes=received_ack)
                except ValueError as error:
                    # A legacy implementation closes its authenticated socket
                    # on unknown operation without sending an ACK byte. A
                    # partial prefix/body is a corrupt reply, never fallback.
                    if str(error)=='GG_LAN_EOF' and ack_bytes==0:continue
                    raise
                except OSError as error:
                    if ack_bytes==0 and (error.errno==errno.ECONNRESET or getattr(error,'winerror',None)==10054):continue
                    raise
                frame=peer._check_frame(value,size,owner,session,0)
                if frame['kind']!=ACK:raise ValueError('GG_WIRE_CODEC_ACK')
                codec=selection(frame['payload'])
                yield sock,session,codec,1
            else:yield sock,session,None,0
            return
    raise ValueError('GG_WIRE_CODEC_NEGOTIATION')
