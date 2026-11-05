"""Adversarial public vectors for the explicit network signature profile."""
import unittest
from unittest.mock import patch
from backend.gg_ed25519 import Keypair,GROUP_ORDER,require_public_key,verify_signature,_canonical_prime_point
from backend.gg_parallel_dag import _verify,make_public_genesis
from backend import gg_lan_dag as lan


class SignatureAdmissionTests(unittest.TestCase):
    def test_missing_or_incompatible_provider_is_rejected_before_creating_a_signer(self):
        import nacl
        from nacl import bindings
        from nacl.exceptions import BadSignatureError
        from backend.gg_ed25519 import _native_verifier
        try:
            for target,value in ((nacl,'old'),):
                _native_verifier.cache_clear()
                with patch.object(target,'__version__',value),self.assertRaisesRegex(ValueError,'PROVIDER_VERSION'):Keypair()
            for fake in (lambda *args:b'',lambda *args:(_ for _ in ()).throw(BadSignatureError())):
                _native_verifier.cache_clear()
                with patch.object(bindings,'crypto_sign_open',side_effect=fake),self.assertRaisesRegex(ValueError,'PROVIDER_INCOMPATIBLE'):Keypair()
        finally:_native_verifier.cache_clear()

    def test_rfc8032_fixture_and_legacy_seed_and_signature_compatibility(self):
        # RFC8032 section7.1 TEST1: these are published test bytes, not secrets.
        seed=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        public=bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
        signature=bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f'
                                'b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
        pair=Keypair.from_seed(seed)
        self.assertEqual(pair.pubkey(),public);self.assertEqual(pair.sign_message(b''),signature)
        self.assertEqual(bytes(pair),seed+public);verify_signature(public,b'',signature)
        from Crypto.Signature import eddsa
        for message in (b'GG-NODE-PUBLIC-FIXTURE',b'\0'*4096):
            legacy=eddsa.new(eddsa.import_private_key(seed),'rfc8032').sign(message)
            self.assertEqual(pair.sign_message(message),legacy)
            verify_signature(public,message,legacy)

    def test_generated_signatures_and_wrong_message_signature_and_author(self):
        key=Keypair();other=Keypair();message=b'GG-PUBLIC-AUDIT-DOMAIN-A';signature=key.sign_message(message)
        require_public_key(key.pubkey());verify_signature(key.pubkey(),message,signature)
        for public,msg,sig in [(key.pubkey(),message+b'changed',signature),(other.pubkey(),message,signature),
                               (key.pubkey(),message,signature[:-1]),(key.pubkey(),message,signature[:63]+bytes([signature[63]^1]))]:
            with self.subTest(length=len(sig)),self.assertRaises(ValueError):verify_signature(public,msg,sig)

    def test_identity_author_and_noncanonical_scalar_are_rejected(self):
        identity=b'\x01'+bytes(31)
        for scalar in (0,GROUP_ORDER,GROUP_ORDER+1):
            signature=identity+scalar.to_bytes(32,'little')
            with self.subTest(scalar_case=scalar==GROUP_ORDER),self.assertRaisesRegex(ValueError,'GG_DAG_SIGNATURE'):
                _verify(identity.hex(),b'arbitrary public fixture',signature.hex())
        with self.assertRaises(ValueError):require_public_key(identity)

    def test_noncanonical_point_and_mixed_order_key_rejected_before_authorization(self):
        # y=1 with an impossible x-sign is a noncanonical identity encoding;
        # y=p is out of the canonical field range; y=0 is a torsion point.
        for raw in ((1+(1<<255)).to_bytes(32,'little'),((1<<255)-19).to_bytes(32,'little'),bytes(32)):
            with self.subTest(case=raw[-1]),self.assertRaises(ValueError):require_public_key(raw)
        good=Keypair();signature=good.sign_message(b'public')
        with self.assertRaises(ValueError):verify_signature(good.pubkey(),b'public',bytes(32)+signature[32:])
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
        normal=eddsa.import_public_key(good.pubkey()).pointQ;prime=2**255-19
        # Add the order-two point (0,-1): (x,y) -> (-x,-y).
        encoded=ECC.construct(curve='Ed25519',point_x=(-int(normal.x))%prime,point_y=(-int(normal.y))%prime).export_key(format='raw')
        with self.assertRaises(ValueError):require_public_key(encoded)

    def test_weak_peer_invite_and_weak_producer_cannot_be_installed(self):
        identity=b'\x01'+bytes(31);key=Keypair()
        body={'schema':'gg.lan-dag.invite.v1','label':'Public audit fixture','host':'127.0.0.1','port':16120,
            'peer_key':identity.hex(),'producer_keys':[Keypair().pubkey().hex(),Keypair().pubkey().hex()],'nonce':'a'*64}
        with self.assertRaises(ValueError):lan.validate_invite({'body':body,'signature':(identity+bytes(32)).hex()})
        body['peer_key']=key.pubkey().hex();body['producer_keys'][0]=identity.hex()
        with self.assertRaisesRegex(ValueError,'PRODUCERS'):lan.validate_invite(lan._signed(key,lan._INVITE,body))
        with self.assertRaisesRegex(ValueError,'PUBLIC_PRODUCERS'):make_public_genesis([identity.hex(),key.pubkey().hex()],enable_dag_transactions=True)

    def test_only_bounded_public_material_is_cached(self):
        _canonical_prime_point.cache_clear();key=Keypair();message=b'cache public fixture';signature=key.sign_message(message)
        verify_signature(key.pubkey(),message,signature);first=_canonical_prime_point.cache_info()
        verify_signature(key.pubkey(),message,signature);second=_canonical_prime_point.cache_info()
        self.assertEqual(first.currsize,1);self.assertGreater(second.hits,first.hits);self.assertEqual(second.maxsize,256)


if __name__=='__main__':unittest.main()
