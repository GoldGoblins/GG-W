"""Actual headless wallet/catalogue state and guarded owned-node dispatch."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import os
from types import SimpleNamespace

from backend import terminal_service,omni_assets,marketplace_contract,crypto_contract


class TerminalServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for module,name,path in ((omni_assets,'ROOT',root/'omni'),(marketplace_contract,'STATE_DIR',root/'marketplace'),(crypto_contract,'STATE_DIR',root/'crypto')):
            self.stack.enter_context(patch.object(module,name,path))
        self.service=terminal_service.TerminalService()
        self.addCleanup(self.service.close)

    def test_public_watch_receive_catalogue_passport_and_activity(self):
        sol=omni_assets.NATIVE_SOL.rsplit('/native:',1)[0]
        account=self.service.dispatch('wallet.watch',{'chain_id':sol,'address':'11111111111111111111111111111111','label':'Fixture watch'})['account_id']
        self.assertEqual(self.service.dispatch('wallet.receive',{'account_id':account})['chain_id'],sol)
        self.assertEqual(self.service.dispatch('wallet.status')['positions'][0]['balance_state'],'NOT_FETCHED')
        row=self.service.dispatch('marketplace.register',{'listing':{'title':'Fixture catalogue item','category':'ITEM','material':'UNKNOWN','price_sol':'1'}})
        selected=self.service.dispatch('marketplace.select',{'id':row['id']})
        proof=self.service.dispatch('marketplace.proof',{'id':row['id']})
        self.assertIsNotNone(proof)
        snapshot=self.service.snapshot()
        self.assertEqual(snapshot['marketplace']['selected']['id'],row['id'])
        self.assertEqual(snapshot['marketplace']['settlement_mode'],'LOCAL_PAPER_RECEIPTS')
        self.assertEqual(snapshot['consensus']['state'],'STOPPED')
        self.assertTrue(snapshot['activity'])

    def test_wallet_refresh_failure_keeps_unknown_instead_of_zero(self):
        from backend import crypto_explorer
        account=self.service.dispatch('wallet.watch',{'chain_id':'eip155:1','address':'0x'+'1'*40})['account_id']
        with patch.object(terminal_service.omni_rpc,'balance',side_effect=OSError('not printed')), \
             patch.object(crypto_explorer,'refresh_wallet_quotes',return_value={'state':'COMPLETE'}):
            result=self.service.dispatch('wallet.refresh',{'account_id':account})
        self.assertEqual(result['state'],'PARTIAL')
        row=self.service.dispatch('wallet.status')['positions'][0]
        self.assertEqual(row['balance_state'],'READ_FAILED');self.assertIsNone(row['atomic'])

    def test_manual_prices_only_selected_native_and_positive_positions_never_status(self):
        from backend import crypto_explorer
        chain='eip155:1'
        selected=self.service.dispatch('wallet.watch',{'chain_id':chain,'address':'0x'+'1'*40})['account_id']
        self.service.dispatch('wallet.watch',{'chain_id':'eip155:56','address':'0x'+'4'*40})
        held=omni_assets.register_asset(chain,'erc20','0x'+'2'*40,'HELD','Fixture held',6)['id']
        zero=omni_assets.register_asset(chain,'erc20','0x'+'3'*40,'ZERO','Fixture zero',6)['id']
        def balance(asset_id,account_id):
            self.assertEqual(account_id,selected)
            amount='0' if asset_id==zero else '12'
            return {'asset_id':asset_id,'account_id':account_id,'atomic':amount,'quantity':amount,'state':'VERIFIED_READ'}
        with patch.object(terminal_service.omni_rpc,'balance',side_effect=balance) as reads, \
             patch.object(crypto_explorer,'refresh_wallet_quotes',return_value={'state':'COMPLETE'}) as prices:
            self.service.snapshot();self.service.dispatch('wallet.status')
            reads.assert_not_called();prices.assert_not_called()
            result=self.service.dispatch('wallet.refresh',{'account_id':selected})
            self.assertEqual(result['price_state'],'COMPLETE')
            prices.assert_called_once_with(sorted([chain+'/native:ETH',held]))
            self.service.snapshot();self.service.dispatch('wallet.status')
            self.assertEqual(prices.call_count,1);self.assertEqual(reads.call_count,3)

    def test_manual_prices_include_newly_discovered_actual_mint(self):
        from backend import crypto_explorer,omni_discovery
        chain=omni_assets.NATIVE_SOL.split('/')[0]
        selected=self.service.dispatch('wallet.watch',{'chain_id':chain,'address':'11111111111111111111111111111111'})['account_id']
        discovered=[]
        def discover(account_id):
            self.assertEqual(account_id,selected)
            asset=omni_assets.register_asset(chain,'token','So11111111111111111111111111111111111111112','WSOL','Fixture',9)
            discovered.append(asset['id'])
            with omni_assets.db(True) as db:
                db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],selected,omni_assets.pack({'atomic':'7','quantity':'0.000000007','state':'VERIFIED_READ'})))
            return {'asset_ids':discovered}
        with patch.object(terminal_service.omni_rpc,'balance',return_value={'atomic':'0','quantity':'0','state':'VERIFIED_READ'}), \
             patch.object(omni_discovery,'discover',side_effect=discover), \
             patch.object(crypto_explorer,'refresh_wallet_quotes',return_value={'state':'COMPLETE'}) as prices:
            result=self.service.dispatch('wallet.refresh',{'account_id':selected})
        self.assertEqual(result['state'],'COMPLETE')
        prices.assert_called_once_with(sorted([omni_assets.NATIVE_SOL,*discovered]))

    def test_never_adopts_or_stops_another_service_cluster(self):
        node=Mock();node._genesis={'foreign':True}
        with patch.object(self.service,'_network',return_value=node):
            for command in ('network.start','network.stop','network.selftest'):
                with self.assertRaisesRegex(ValueError,'OWNED'):self.service.dispatch(command)
            self.service.close();node.stop.assert_not_called();node.start.assert_not_called()

    def test_secrets_cannot_enter_command_arguments(self):
        for command,args in (('wallet.create',{'password':'must never be accepted'}),('network.send',{'endpoint':'http://remote'}),('unknown',{})):
            with self.assertRaisesRegex(ValueError,'COMMAND_ARGUMENTS'):self.service.dispatch(command,args)
        self.service.close()
        with self.assertRaisesRegex(ValueError,'TERMINAL_CLOSED'):self.service.dispatch('status')

    def test_portable_wallet_real_approved_create_backup_restore_and_secret_cleanup(self):
        from backend import wallet_vault,terminal_approval,portable_wallet_vault
        from solders.keypair import Keypair
        root=Path(self.tmp.name)
        proxy=SimpleNamespace(**{k:getattr(os,k) for k in dir(os) if k!='name'},name='posix')
        self.stack.enter_context(patch.object(wallet_vault,'os',proxy))
        self.stack.enter_context(patch.object(terminal_approval,'STATE_ROOT',root/'approvals'))
        self.service._portable=True
        fixture_password='synthetic terminal fixture 123'
        # Published BIP39 test vector only; never produce/capture a user phrase.
        from backend import wallet_mnemonic
        vector='abandon '*11+'about'
        self.stack.enter_context(patch.object(wallet_mnemonic._bip39(),'generate',return_value=vector))
        self.service.show_words=lambda words:words==vector.split()
        self.service.secret=lambda prompt:vector.split()[int(prompt.split('#')[1].split()[0])-1] if prompt.startswith('Ord #') else fixture_password
        summaries=[];self.service.confirm=lambda summary:summaries.append(summary) or True
        created=self.service.dispatch('wallet.create',{'label':'Portable fixture','method':'AI','count':12})
        address=created['pubkey'];vault_file=wallet_vault._path(address)
        self.assertTrue(vault_file.read_bytes().startswith(portable_wallet_vault.MAGIC))
        self.assertIsNone(portable_wallet_vault._password.get())
        with portable_wallet_vault.session(fixture_password):
            pair=wallet_vault._keypair(address);key_bytes=bytes(pair)
        backup=root/'fixture-backup.ggwallet'
        self.service.dispatch('wallet.backup',{'pubkey':address,'path':str(backup)})
        self.assertTrue(backup.is_file())
        self.service.dispatch('wallet.restore',{'path':str(backup),'label':'Restored fixture'})
        with portable_wallet_vault.session(fixture_password):
            self.assertEqual(bytes(wallet_vault._keypair(address)),key_bytes)
        self.assertTrue(wallet_vault.status()[0]['backed_up'])
        self.assertEqual(len(summaries),3)
        for path in root.rglob('*'):
            if path.is_file():
                data=path.read_bytes()
                self.assertNotIn(key_bytes,data)
                self.assertNotIn(key_bytes[:32].hex().encode(),data)
                self.assertNotIn(fixture_password.encode(),data)
        self.assertIsNone(portable_wallet_vault._password.get())


if __name__=='__main__':unittest.main()
