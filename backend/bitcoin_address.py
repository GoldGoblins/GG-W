"""Bitcoin mainnet Base58Check and BIP173/BIP350 witness address validation."""
import hashlib
from bech32 import convertbits
from backend.crypto_keys import b58decode,b58encode

CHARSET='qpzry9x8gf2tvdw0s3jn54khce6mua7l'


def validate(address):
    if not isinstance(address,str) or not 14<=len(address)<=90:raise ValueError('BTC_ADDRESS')
    if address.lower().startswith('bc1'):
        if address!=address.lower() and address!=address.upper():raise ValueError('BTC_ADDRESS_CASE')
        value=address.lower();hrp,encoded=value.rsplit('1',1)
        if hrp!='bc' or len(encoded)<7 or any(c not in CHARSET for c in encoded):raise ValueError('BTC_WITNESS_ADDRESS')
        words=[CHARSET.index(c) for c in encoded];expanded=[ord(c)>>5 for c in hrp]+[0]+[ord(c)&31 for c in hrp]
        checksum=1
        for word in expanded+words:
            top=checksum>>25;checksum=((checksum&0x1ffffff)<<5)^word
            for i,generator in enumerate((0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3)):
                if (top>>i)&1:checksum^=generator
        version=words[0];program=convertbits(words[1:-6],5,8,False)
        if version>16 or program is None or not 2<=len(program)<=40 or (version==0 and len(program) not in {20,32}) or checksum!=(1 if version==0 else 0x2bc830a3):
            raise ValueError('BTC_ADDRESS_CHECKSUM_OR_PROGRAM')
        return value
    try:raw=b58decode(address)
    except (TypeError,ValueError):raise ValueError('BTC_ADDRESS') from None
    if len(raw)!=25 or raw[0] not in {0,5} or b58encode(raw)!=address or hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4]!=raw[-4:]:raise ValueError('BTC_ADDRESS_CHECKSUM_OR_NETWORK')
    return address
