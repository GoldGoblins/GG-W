"""Kaspa public address checks, including the 40-bit checksum and padding.

Format reference (ISC): kaspanet/rusty-kaspa v2.1.0,
crypto/addresses/src/bech32.rs. No private keys or signing operations.
"""
CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
GENERATORS = (0x98f2bc8e61,0x79b76d99e2,0xf33e5fb3c4,0xae2eabe2a8,0x1e4f43e470)
PREFIXES = {'kaspa','kaspatest','kaspasim'}


def _polymod(values):
    value = 1
    for item in values:
        top, value = value >> 35, ((value & 0x07ffffffff) << 5) ^ item
        for bit, generator in enumerate(GENERATORS):
            if top & (1 << bit): value ^= generator
    return value ^ 1


def _convert(values, source_bits, target_bits, pad):
    accumulator=0; bits=0; result=[]
    for value in values:
        accumulator=(accumulator << source_bits) | value
        bits += source_bits
        while bits >= target_bits:
            bits -= target_bits
            result.append((accumulator >> bits) & ((1 << target_bits)-1))
        accumulator &= (1 << bits)-1
    if pad and bits: result.append(accumulator << (target_bits-bits))
    elif bits and (bits >= source_bits or accumulator): raise ValueError('KASPA_ADDRESS_PADDING')
    return result


def encode(prefix, payload, version=0):
    if prefix not in PREFIXES or version not in {0,1,8} or len(payload) != (33 if version==1 else 32):
        raise ValueError('KASPA_ADDRESS_PAYLOAD')
    body=_convert(bytes([version])+bytes(payload),8,5,True)
    checksum=_polymod([ord(c)&31 for c in prefix]+[0]+body+[0]*8)
    return prefix+':'+''.join(CHARSET[v] for v in body+[(checksum >> shift)&31 for shift in range(35,-1,-5)])


def validate(value):
    text=str(value or '').strip()
    if text != text.lower() and text != text.upper(): raise ValueError('KASPA_ADDRESS_CASE')
    text=text.lower()
    if len(text)>128 or text.count(':')!=1: raise ValueError('KASPA_WATCH_ADDRESS')
    prefix,body=text.split(':')
    if prefix not in PREFIXES or len(body)<9: raise ValueError('KASPA_WATCH_ADDRESS')
    try: values=[CHARSET.index(c) for c in body]
    except ValueError: raise ValueError('KASPA_WATCH_ADDRESS') from None
    if _polymod([ord(c)&31 for c in prefix]+[0]+values)!=0: raise ValueError('KASPA_ADDRESS_CHECKSUM')
    decoded=bytes(_convert(values[:-8],5,8,False))
    if not decoded or encode(prefix,decoded[1:],decoded[0]) != text: raise ValueError('KASPA_WATCH_ADDRESS')
    return text
