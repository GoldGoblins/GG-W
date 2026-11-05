"""Ed25519 signing adapter and explicit cross-runtime admission profile.

The native GG development ledger only needs RFC8032 signing, public bytes and
bootstrap seed bytes. It does not need a Solana/Rust SDK or any GUI library.
"""
from functools import lru_cache

SIGNATURE_PROFILE='GG-Ed25519-PrimeOrder-v1'
GROUP_ORDER=2**252+27742317777372353535851937790883648493


@lru_cache(maxsize=256)
def _canonical_prime_point(encoded):
    if not isinstance(encoded,bytes) or len(encoded)!=32:raise ValueError('GG_ED25519_PUBLIC')
    check,_open,_bad=_native_verifier()
    if not check(encoded):raise ValueError('GG_ED25519_PUBLIC')
    return encoded


@lru_cache(maxsize=1)
def _native_verifier():
    # Use the maintained point-validation primitive, not scalar multiplication
    # APIs which may already assume prime-order points or reduce the scalar.
    try:
        import nacl
        from nacl.bindings import crypto_core_ed25519_is_valid_point,crypto_sign_open
        from nacl.exceptions import BadSignatureError
    except (ImportError,OSError):raise ValueError('GG_ED25519_PROVIDER_REQUIRED') from None
    if nacl.__version__!='1.6.2':raise ValueError('GG_ED25519_PROVIDER_VERSION')
    base=b'\x58'+b'\x66'*31;prime=2**255-19
    mixed=(((-int.from_bytes(base,'little'))%prime)|(1<<255)).to_bytes(32,'little')
    if (not crypto_core_ed25519_is_valid_point(base)
            or crypto_core_ed25519_is_valid_point(b'\x01'+bytes(31))
            or crypto_core_ed25519_is_valid_point(mixed)):
        raise ValueError('GG_ED25519_PROVIDER_INCOMPATIBLE')
    # RFC8032 section7.1 TEST1: public known-answer data, not a signer seed.
    public=bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
    signature=bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f'
                            'b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
    try:valid=crypto_sign_open(signature,public)==b''
    except BadSignatureError:valid=False
    if not valid:raise ValueError('GG_ED25519_PROVIDER_INCOMPATIBLE')
    # Pin native uncofactored verification, including low-order R rejection.
    # These deliberately nonce-broken public fixtures contain no secrets.
    edge_public=bytes.fromhex('03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8')
    edge_message=b'GG-PUBLIC-APPLICATION-PROFILE-EDGE'
    for encoded in (
        '0100000000000000000000000000000000000000000000000000000000000000a7df2c4c305c70e54d444bb998cf3872064b659747c64fed77e8c820c58f2a0b',
        '959999999999999999999999999999999999999999999999999999999999999918be3329772377f5455dfe34fdb1ed5f9e877474f8df0b3add78f89f3350070e',
    ):
        try:crypto_sign_open(bytes.fromhex(encoded)+edge_message,edge_public)
        except BadSignatureError:pass
        else:raise ValueError('GG_ED25519_PROVIDER_INCOMPATIBLE')
    return crypto_core_ed25519_is_valid_point,crypto_sign_open,BadSignatureError


def verification_backend():
    _native_verifier()
    return {'provider':'PyNaCl','version':'1.6.2','profile':SIGNATURE_PROFILE}


def require_public_key(encoded):
    """Canonical nonidentity prime-order key; bounded public-data cache only."""
    if not isinstance(encoded,bytes) or len(encoded)!=32:raise ValueError('GG_ED25519_PUBLIC')
    _canonical_prime_point(encoded)


def verify_signature(public,message,signature):
    """Explicit common admission profile; never rely on provider edge defaults.

    Normal generated Ed25519 signatures are unchanged. Public keys must be
    nonidentity prime-order points; S must be strictly below L. The pinned
    native verifier reconstructs R=[S]B-[h]A, compares its canonical encoding,
    and rejects small-order R. With prime A this enforces canonical nonidentity
    prime-order R without a second subgroup multiplication per signature.
    No private input is cached. CometBFT vote verification
    remains governed by its pinned SDK rather than this transaction profile.
    """
    if not isinstance(message,bytes) or not isinstance(signature,bytes) or len(signature)!=64:
        raise ValueError('GG_ED25519_SIGNATURE')
    if int.from_bytes(signature[32:],'little')>=GROUP_ORDER:raise ValueError('GG_ED25519_SIGNATURE')
    require_public_key(public)
    _check,open_signature,bad_signature=_native_verifier()
    try:open_signature(signature+message,public)
    except bad_signature:raise ValueError('GG_ED25519_SIGNATURE') from None


class Keypair:
    def __init__(self):
        _native_verifier()
        from nacl.signing import SigningKey
        self._key=SigningKey.generate()

    @classmethod
    def from_seed(cls,seed):
        if not isinstance(seed,bytes) or len(seed)!=32:raise ValueError('GG_ED25519_SEED')
        _native_verifier()
        from nacl.signing import SigningKey
        pair=cls.__new__(cls)
        pair._key=SigningKey(seed)
        return pair

    def pubkey(self):
        return bytes(self._key.verify_key)

    def sign_message(self,message):
        if not isinstance(message,bytes):raise ValueError('GG_ED25519_MESSAGE')
        return self._key.sign(message).signature

    def __bytes__(self):
        return bytes(self._key)+self.pubkey()

    def __repr__(self):
        return '<GG Ed25519 key in RAM>'
