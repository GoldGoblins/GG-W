"""Small Ed25519 key adapter using the existing audited PyCryptodome dependency.

The native GG development ledger only needs RFC8032 signing, public bytes and
bootstrap seed bytes. It does not need a Solana/Rust SDK or any GUI library.
"""
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa


class Keypair:
    def __init__(self):
        self._key=ECC.generate(curve='Ed25519')

    @classmethod
    def from_seed(cls,seed):
        if not isinstance(seed,bytes) or len(seed)!=32:raise ValueError('GG_ED25519_SEED')
        pair=cls.__new__(cls)
        pair._key=eddsa.import_private_key(seed)
        return pair

    def pubkey(self):
        return self._key.public_key().export_key(format='raw')

    def sign_message(self,message):
        if not isinstance(message,bytes):raise ValueError('GG_ED25519_MESSAGE')
        return eddsa.new(self._key,'rfc8032').sign(message)

    def __bytes__(self):
        return self._key.seed+self.pubkey()

    def __repr__(self):
        return '<GG Ed25519 key in RAM>'
