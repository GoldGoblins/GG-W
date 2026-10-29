"""Published BIP39/SLIP10 vectors, private-session lifecycle and real approvals.

Every phrase/seed in this file is an intentionally public upstream test vector.
No user key, network, real wallet screenshot or live user state is used.
Sources: trezor/python-mnemonic/vectors.json; satoshilabs/slips/slip-0010.md.
"""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from backend import wallet_mnemonic as mnemonic,wallet_vault as vault,wallet_approval as approval
from backend import omni_assets as store,terminal_approval as terminal,wallet_account_roles as roles

PHRASE12=' '.join(['abandon']*11+['about'])
PHRASE24=' '.join(['abandon']*23+['art'])
PASSWORD='public-fixture-recovery-password-only'


class MnemonicVectors(unittest.TestCase):
    def tearDown(self):mnemonic.cancel_all()

    def test_bip39_published_seed_and_slip10_published_hardened_ed25519_vector(self):
        seed=mnemonic._bip39().to_seed(PHRASE12,passphrase='TREZOR')
        self.assertEqual(seed.hex(),'c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e53495531f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04')
        public_seed=bytes.fromhex('000102030405060708090a0b0c0d0e0f')
        for path,key,chain in [('m','2b4be7f19ee27bbf30c667b642d5f4aa69fd169872f8fc3059c08ebae2eb19e7','90046a93de5380a72b5e45010748567d5ea02bbf6522f979e05c0d8d8ca9fffb'),
            ("m/0'",'68e0fe46dfb67e368c75379acec591dad19df3cde26e63b93a8e704f1dade7a3','8b59aa11380b624e81507a27fedda59fea6d0b779a778918a2fd3590e16e9c69')]:
            child,code=mnemonic.derive_child(public_seed,path)
            self.assertEqual(child.hex(),key);self.assertEqual(code.hex(),chain);mnemonic.wipe(child)
        for path in ('m/0','m/-1\'','m/2147483648\'','m/0\'/1'):
            with self.assertRaises(ValueError):mnemonic.derive_child(public_seed,path)

    def test_fixed_solana_path_matches_independent_solders_for_both_word_counts(self):
        from solders.keypair import Keypair
        for phrase in (PHRASE12,PHRASE24):
            raw=bytearray(phrase.encode());child,address=mnemonic.derive(raw)
            pair=Keypair.from_seed_and_derivation_path(mnemonic._bip39().to_seed(phrase),mnemonic.DERIVATION_PATH)
            self.assertEqual(bytes(child),bytes(pair)[:32]);self.assertEqual(address,str(pair.pubkey()))
            mnemonic.wipe(child);mnemonic.wipe(raw);del pair

    def test_paper_next_wipes_full_phrase_and_child_never_remains_in_session_no_time_limit(self):
        for count,phrase in ((12,PHRASE12),(24,PHRASE24)):
            with patch.object(mnemonic._bip39(),'generate',return_value=phrase):public=mnemonic.begin('Fixture','STORAGE',count,'PAPER')
            identifier=public['session_id'];session=mnemonic._sessions[identifier];owned=session.phrase
            self.assertEqual(len(public['words']),count)
            with patch('time.time',return_value=time.time()+86400*365):challenge=mnemonic.challenge(identifier)
            self.assertFalse(owned);self.assertFalse(session.phrase);self.assertFalse(session.password)
            self.assertEqual(len(session.commitments),3);self.assertEqual(len(set(challenge['indices'])),3)
            self.assertTrue(all(1<=i<=count for i in challenge['indices']))
            ready=mnemonic.verify(identifier,{str(i):phrase.split()[i-1] for i in challenge['indices']})
            self.assertEqual(ready['state'],'READY');self.assertNotIn('words',ready);self.assertFalse(session.commitments)
            self.assertEqual(set(vars(session)),{'public','phrase','password','commitments','state','attempts'})
            mnemonic.cancel(identifier)

    def test_attempt_cap_session_cap_cancel_and_restore_checksum_are_bounded(self):
        public=mnemonic.begin_restore(PHRASE12,'Fixture','TRADING','PAPER')
        other=mnemonic.begin_restore(PHRASE24,'Other','STORAGE','PAPER')
        self.assertNotIn('words',public)
        with self.assertRaisesRegex(ValueError,'LIMIT'):mnemonic.begin_restore(PHRASE12)
        mnemonic.cancel(public['session_id']);mnemonic.cancel(other['session_id'])
        with self.assertRaisesRegex(ValueError,'INVALID'):mnemonic.begin_restore(' '.join(['abandon']*12))
        with patch.object(mnemonic._bip39(),'generate',return_value=PHRASE12):public=mnemonic.begin('Fixture','TRADING',12,'PAPER')
        identifier=public['session_id'];session=mnemonic._sessions[identifier];mnemonic.challenge(identifier)
        for _ in range(3):
            with self.assertRaisesRegex(ValueError,'CHALLENGE_FAILED'):mnemonic.verify(identifier,{})
        self.assertNotIn(identifier,mnemonic._sessions);self.assertFalse(session.phrase);self.assertFalse(session.password)

    def test_ai_password_is_private_immutable_after_ready_and_cancel_wipes_owned_buffers(self):
        public=mnemonic.begin_restore(PHRASE12,'Fixture','TRADING','AI')
        identifier=public['session_id'];session=mnemonic._sessions[identifier]
        self.assertEqual(public['state'],'VERIFIED_NEEDS_PASSWORD')
        with self.assertRaisesRegex(ValueError,'NOT_READY'):mnemonic.descriptor(identifier)
        ready=mnemonic.set_password(identifier,PASSWORD);phrase=session.phrase;password=session.password
        self.assertEqual(ready['state'],'READY');self.assertNotIn(PASSWORD,json.dumps(ready))
        with self.assertRaisesRegex(ValueError,'PHASE'):mnemonic.set_password(identifier,'changed-password-not-accepted')
        mnemonic.cancel(identifier);self.assertFalse(phrase);self.assertFalse(password)


class MnemonicPublication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-mnemonic-publication-');self.root=Path(self.temp.name)
        self.directory=patch.object(store,'ROOT',self.root/'state');self.directory.start()
        self.runtime=patch.object(terminal,'STATE_ROOT',self.root/'terminal');self.runtime.start()
        store.bootstrap()

    def tearDown(self):
        approval.cancel_all();self.runtime.stop();self.directory.stop();self.temp.cleanup()

    def ready(self,method='PAPER',purpose='STORAGE'):
        public=mnemonic.begin_restore(PHRASE12,'Fixture',purpose,method)
        if method=='AI':mnemonic.set_password(public['session_id'],PASSWORD)
        return public['session_id']

    def create(self,identifier):
        args={'label':'Fixture','mnemonic_session':identifier}
        return terminal.execute('create_wallet',args,lambda:vault.create(**args),lambda _summary:True)

    def test_no_exact_approval_rejects_before_consuming_session(self):
        identifier=self.ready()
        with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):vault.create('Fixture',identifier)
        with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):mnemonic.consume(identifier,'Fixture')
        self.assertEqual(mnemonic.descriptor(identifier)['method'],'PAPER')
        self.assertFalse(store.snapshot()['accounts'])

    def test_paper_full_flow_does_not_import_optional_solders_or_gui_packages(self):
        import builtins
        original=builtins.__import__
        def headless(name,*args,**kwargs):
            if name.split('.')[0] in {'solders','PySide6','PIL'}:raise AssertionError('PAPER_OPTIONAL_IMPORT')
            return original(name,*args,**kwargs)
        with patch.object(builtins,'__import__',side_effect=headless):
            public=self.create(self.ready('PAPER'))
            self.assertEqual(public['signer_state'],'WATCH_ONLY')
            self.assertFalse(vault.status())

    def test_paper_creation_stores_public_watch_and_role_only_single_use_and_no_secret_in_approval(self):
        identifier=self.ready()
        args={'label':'Fixture','mnemonic_session':identifier};ticket=approval.stage('create_wallet',args,lambda:None)
        request=json.dumps(approval.request(ticket))
        self.assertNotIn(PHRASE12,request);self.assertNotIn('password',request);self.assertNotIn('commitment',request)
        # Cancelling this staged request clears its exact mnemonic session.
        approval.cancel(ticket);self.assertNotIn(identifier,mnemonic._sessions)
        identifier=self.ready()
        with patch.object(vault,'_crypt',side_effect=AssertionError('PAPER_MUST_NOT_ENCRYPT_OR_STORE_KEY')):public=self.create(identifier)
        self.assertEqual(public['signer_state'],'WATCH_ONLY');self.assertFalse(vault.status())
        self.assertEqual(roles.snapshot()['roles'][public['account_id']],'STORAGE')
        with patch.object(mnemonic,'_bip39',side_effect=AssertionError('PUBLIC_METADATA_MUST_NOT_LOAD_WORDS')):
            self.assertEqual(mnemonic.account_metadata()[public['account_id']],{'control_mode':'SELF_CUSTODY',
                'custody_method':'PAPER','derivation_path':mnemonic.DERIVATION_PATH,'word_count':12})
        self.assertFalse((store.ROOT/'wallet-vault').exists());self.assertFalse((store.ROOT/'wallet-recovery').exists())
        self.assertEqual(len(store.snapshot()['accounts']),1);self.assertNotIn(identifier,mnemonic._sessions)
        with self.assertRaisesRegex(ValueError,'SESSION'):self.create(identifier)
        for path in self.root.rglob('*'):
            if path.is_file():
                content=path.read_bytes();self.assertNotIn(PHRASE12.encode(),content);self.assertNotIn(PASSWORD.encode(),content)

    def test_ai_recovery_is_password_portable_with_exact_address_and_reveal_requires_own_approval(self):
        identifier=self.ready('AI','TRADING');public=self.create(identifier);path=mnemonic.recovery_path(public['pubkey'])
        raw=path.read_bytes();self.assertNotIn(PHRASE12.encode(),raw);self.assertNotIn(PASSWORD.encode(),raw)
        self.assertTrue(vault._path(public['pubkey']).is_file());self.assertTrue(vault.status()[0]['backed_up'])
        self.assertEqual(mnemonic.account_metadata()[public['account_id']]['control_mode'],'AI_ASSISTED')
        with patch.object(store,'ROOT',self.root/'another-computer'):
            plain,metadata=mnemonic.decode_recovery(raw,PASSWORD)
            self.assertEqual(bytes(plain).decode(),PHRASE12);self.assertEqual(metadata['pubkey'],public['pubkey']);mnemonic.wipe(plain)
            store.bootstrap()
            recovered=self.create(self.ready('PAPER','STORAGE'))
            self.assertEqual(recovered['pubkey'],public['pubkey'])
            self.assertEqual(recovered['signer_state'],'WATCH_ONLY')
            self.assertEqual(mnemonic.account_metadata()[recovered['account_id']]['control_mode'],'SELF_CUSTODY')
        with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):mnemonic.reveal(public['pubkey'],PASSWORD)
        args={'pubkey':public['pubkey'],'password':PASSWORD}
        secret=terminal.execute('reveal_mnemonic',args,lambda:mnemonic.reveal(**args),lambda _summary:True)
        self.assertEqual(' '.join(secret['words']),PHRASE12)
        target=self.root/'portable.ggmnemonic';args={'pubkey':public['pubkey'],'path':target}
        terminal.execute('export_mnemonic',args,lambda:mnemonic.export(**args),lambda _summary:True)
        self.assertEqual(target.read_bytes(),raw)
        for path in self.root.rglob('*'):
            if path.is_file():self.assertNotIn(PHRASE12.encode(),path.read_bytes());self.assertNotIn(PASSWORD.encode(),path.read_bytes())

    def test_authenticated_recovery_rejects_password_header_duplicate_and_truncation(self):
        public=self.create(self.ready('AI'));raw=mnemonic.recovery_path(public['pubkey']).read_bytes()
        for password in ('wrong-fixture-password',PASSWORD):
            bad=json.loads(raw);bad['derivation_path']="m/44'/501'/1'/0'"
            data=raw if password!=PASSWORD else json.dumps(bad).encode()
            with self.assertRaisesRegex(ValueError,'RECOVERY_INVALID'):mnemonic.decode_recovery(data,password)
        with self.assertRaises(ValueError):mnemonic.decode_recovery(raw[:-1]+b',"schema":"duplicate"}',PASSWORD)
        with self.assertRaises(ValueError):mnemonic.decode_recovery(raw[:-20],PASSWORD)

    def test_second_file_failure_rolls_back_owned_files_and_public_metadata(self):
        identifier=self.ready('AI');write=vault._write
        def fail(path,*args,**kwargs):
            if path.parent.name=='wallet-recovery':raise OSError('synthetic publication failure')
            return write(path,*args,**kwargs)
        with patch.object(vault,'_write',side_effect=fail):
            with self.assertRaises(OSError):self.create(identifier)
        self.assertFalse(vault.status());self.assertFalse(store.snapshot()['accounts'])
        self.assertEqual(mnemonic.account_metadata(),{})
        self.assertEqual(list(store.ROOT.rglob('*.vault')),[]);self.assertEqual(list(store.ROOT.rglob('*.ggmnemonic')),[])
        self.assertFalse(mnemonic._sessions)

    @staticmethod
    def revoke_current():
        from backend import live_mandate_store as mandates
        ticket=approval._ticket(approval._current.get());record=ticket.approval
        mandates.revoke(mandates.MandateStore(Path(record['store_root'])),
            request_capture_sha256=record['request_capture_sha256'],approval_scope_revision=record['approval_scope_revision'])

    def test_revocation_after_ai_kdf_writes_nothing_and_wipes_private_buffers(self):
        identifier=self.ready('AI');session=mnemonic._sessions[identifier]
        phrase=session.phrase;password=session.password;encode=mnemonic.encode_recovery
        def revoked(*args):
            encoded=encode(*args);self.revoke_current();return encoded
        with patch.object(mnemonic,'encode_recovery',side_effect=revoked):
            with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):self.create(identifier)
        self.assertFalse(phrase);self.assertFalse(password);self.assertFalse(mnemonic._sessions)
        self.assertFalse(store.snapshot()['accounts']);self.assertFalse(list(store.ROOT.rglob('*.vault')))

    def test_reveal_revocation_after_decryption_never_returns_words_and_wipes_plaintext(self):
        public=self.create(self.ready('AI'));decode=mnemonic.decode_recovery;buffers=[]
        def revoked(*args):
            phrase,metadata=decode(*args);buffers.append(phrase);self.revoke_current();return phrase,metadata
        args={'pubkey':public['pubkey'],'password':PASSWORD}
        with patch.object(mnemonic,'decode_recovery',side_effect=revoked):
            with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):
                terminal.execute('reveal_mnemonic',args,lambda:mnemonic.reveal(**args),lambda _summary:True)
        self.assertEqual(len(buffers),1);self.assertFalse(buffers[0])

    def test_recovery_file_for_another_address_cannot_be_approved_under_requested_address(self):
        public=self.create(self.ready('AI'));other=mnemonic.begin_restore(PHRASE24,'Other','STORAGE','PAPER')
        target=mnemonic.recovery_path(other['address'])
        vault._write(target,mnemonic.recovery_path(public['pubkey']).read_bytes(),overwrite=False)
        with self.assertRaisesRegex(ValueError,'BINDING'):
            approval.stage('reveal_mnemonic',{'pubkey':other['address'],'password':PASSWORD},lambda:None)
        with self.assertRaisesRegex(ValueError,'BINDING'):
            approval.stage('export_mnemonic',{'pubkey':other['address'],'path':self.root/'wrong.ggmnemonic'},lambda:None)

    def test_generic_omni_cannot_return_private_phrase_operations(self):
        from backend import omni_service
        for name in ('reveal_mnemonic','export_mnemonic'):
            with self.assertRaisesRegex(ValueError,'PRIVATE_WALLET_OPERATION_REQUIRED'):omni_service._action(name,'{}')


if __name__=='__main__':unittest.main()
