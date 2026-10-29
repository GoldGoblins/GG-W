"""Private terminal mnemonic flow with published BIP39 vectors, owned temp state."""
from contextlib import ExitStack,redirect_stdout
import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import omni_assets,terminal_approval,terminal_service,wallet_mnemonic,wallet_vault,sensitive_ui_guard
from backend.terminal_cli import TerminalApp,main,parse_command

# Public BIP39 test vectors; these are never usable user wallets.
VECTOR12='abandon '*11+'about'
VECTOR24='abandon '*23+'art'
PASSWORD='public terminal fixture password'


class TerminalMnemonicTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(omni_assets,'ROOT',self.root/'omni'))
        self.stack.enter_context(patch.object(terminal_approval,'STATE_ROOT',self.root/'approval'))
        self.stack.enter_context(patch.object(wallet_mnemonic._bip39(),'generate',side_effect=lambda strength:VECTOR12 if strength==128 else VECTOR24))
        self.guards=[]
        self.stack.enter_context(patch.object(sensitive_ui_guard,'enter',side_effect=lambda owner:self.guards.append(owner)))
        self.stack.enter_context(patch.object(sensitive_ui_guard,'leave',side_effect=lambda owner:self.guards.remove(owner)))
        wallet_mnemonic.cancel_all();self.addCleanup(wallet_mnemonic.cancel_all)
        self.summaries=[];self.displays=[]
        self.service=terminal_service.TerminalService(confirm=self.confirm,secret=self.secret,show_words=self.display)
        self.addCleanup(self.service.close)

    def confirm(self,summary):self.summaries.append(summary);return True
    def display(self,words):
        self.assertTrue(self.guards)
        self.displays.append(len(words))
        self.assertIn(' '.join(words),(VECTOR12,VECTOR24))
        return True
    def secret(self,prompt):
        if prompt.startswith('Ord #'):
            index=int(prompt.split('#')[1].split()[0])
            return (VECTOR24 if self.displays[-1]==24 else VECTOR12).split()[index-1]
        return PASSWORD

    def test_default_paper24_approval_and_only_public_watch_metadata_persist(self):
        result=self.service.dispatch('wallet.create',{'label':'Public fixture'})
        self.assertEqual((result['method'],result['word_count'],result['purpose']),('PAPER',24,'TRADING'))
        self.assertEqual(result['signer_state'],'WATCH_ONLY');self.assertFalse(result['recovery_available'])
        self.assertEqual(self.displays,[24]);self.assertEqual(len(self.summaries),2)
        self.assertIn('PAPER',self.summaries[0]);self.assertFalse(self.guards);self.assertFalse(wallet_mnemonic._sessions)
        self.assertFalse((omni_assets.ROOT/'wallet-vault').exists())
        self.assertFalse((omni_assets.ROOT/'wallet-recovery').exists())
        combined=json.dumps(result)+''.join(p.read_bytes().decode('utf-8',errors='ignore') for p in self.root.rglob('*') if p.is_file())
        self.assertNotIn(VECTOR24,combined);self.assertNotIn(PASSWORD,combined)

    def test_paper_warning_rejected_before_generation(self):
        self.service.confirm=lambda _:False
        with patch.object(wallet_mnemonic,'begin',side_effect=AssertionError('must not generate')):
            with self.assertRaisesRegex(ValueError,'APPROVAL_REJECTED'):self.service.dispatch('wallet.create')
        self.assertFalse(wallet_mnemonic._sessions);self.assertEqual(self.displays,[])

    def test_no_private_callback_rejects_create_restore_and_reveal_before_any_secret(self):
        self.service.show_words=None;self.service.secret=lambda _:self.fail('must not request secret')
        with patch.object(wallet_mnemonic,'begin',side_effect=AssertionError('must not generate')), \
             patch.object(wallet_mnemonic,'reveal',side_effect=AssertionError('must not decrypt')):
            for command,args in [('wallet.create',{}),('wallet.restore_phrase',{}),('wallet.recovery',{'pubkey':'public'})]:
                with self.assertRaisesRegex(ValueError,'PRIVATE_WORDS_UI_REQUIRED'):self.service.dispatch(command,args)

    def test_cancel_and_wrong_challenge_destroy_session_and_leave_guard(self):
        self.service.show_words=lambda _:False
        with self.assertRaisesRegex(ValueError,'SECRET_CANCELLED'):self.service.dispatch('wallet.create')
        self.assertFalse(self.guards);self.assertFalse(wallet_mnemonic._sessions)
        self.service.show_words=self.display;self.service.secret=lambda _:'wrong'
        with self.assertRaisesRegex(ValueError,'CHALLENGE_FAILED'):self.service.dispatch('wallet.create')
        self.assertFalse(self.guards);self.assertFalse(wallet_mnemonic._sessions)
        self.assertEqual(omni_assets.snapshot()['accounts'],[])

    def test_hidden_restore_never_redisplays_or_accepts_phrase_argument(self):
        self.service.secret=lambda prompt:VECTOR12
        result=self.service.dispatch('wallet.restore_phrase',{'label':'Restored paper','purpose':'STORAGE'})
        self.assertEqual((result['method'],result['word_count'],result['purpose']),('PAPER',12,'STORAGE'))
        self.assertEqual(self.displays,[]);self.assertFalse(wallet_mnemonic._sessions)
        with self.assertRaisesRegex(ValueError,'COMMAND_ARGUMENTS'):
            self.service.dispatch('wallet.restore_phrase',{'phrase':VECTOR12})
        with self.assertRaisesRegex(ValueError,'SECRET_REQUIRES_INTERACTIVE'):
            parse_command('wallet.restore_phrase',{'mnemonic':VECTOR12})

    def test_ai_create_reveal_encrypted_export_and_bad_password_fail_closed(self):
        proxy=SimpleNamespace(**{key:getattr(os,key) for key in dir(os) if key!='name'},name='posix')
        self.stack.enter_context(patch.object(wallet_vault,'os',proxy))
        created=self.service.dispatch('wallet.create',{'label':'AI fixture','method':'AI','count':12})
        self.assertTrue(created['recovery_available']);address=created['pubkey']
        revealed=self.service.dispatch('wallet.recovery',{'pubkey':address})
        self.assertEqual(revealed,{'state':'DISPLAYED','pubkey':address})
        self.assertNotIn('words',revealed);self.assertEqual(self.displays,[12,12])
        exported=self.root/'encrypted.ggmnemonic'
        self.assertEqual(self.service.dispatch('wallet.export_recovery',{'pubkey':address,'path':str(exported)})['state'],'EXPORTED')
        self.assertEqual(exported.read_bytes(),wallet_mnemonic.recovery_path(address).read_bytes())
        self.assertNotIn(VECTOR12.encode(),exported.read_bytes());self.assertNotIn(PASSWORD.encode(),exported.read_bytes())
        self.service.secret=lambda _:'wrong password long enough'
        with self.assertRaisesRegex(ValueError,'INVALID_OR_PASSWORD'):self.service.dispatch('wallet.recovery',{'pubkey':address})
        self.assertFalse(self.guards);self.assertEqual(self.displays,[12,12])
        self.assertNotIn(VECTOR12,json.dumps(omni_assets.snapshot()))

    def test_ai_password_mismatch_and_missing_sdk_leave_no_session(self):
        self.service.secret=lambda prompt:'second password mismatch' if prompt.startswith('Upprepa') else self.secret(prompt)
        with self.assertRaisesRegex(ValueError,'PASSWORD_MISMATCH'):self.service.dispatch('wallet.create',{'method':'AI','count':12})
        self.assertFalse(wallet_mnemonic._sessions);self.assertFalse(self.guards)
        with patch.object(terminal_service.importlib.util,'find_spec',return_value=None),patch.object(wallet_mnemonic,'begin',side_effect=AssertionError('no generation')):
            with self.assertRaisesRegex(ValueError,'SDK_REQUIRED'):self.service.dispatch('wallet.create',{'method':'AI'})

    def test_json_tty_still_has_no_private_word_surface(self):
        class TtyBuffer(io.StringIO):
            def isatty(self):return True
        self.service.show_words=None;output=TtyBuffer()
        with redirect_stdout(output),patch('sys.stdin.isatty',return_value=True),patch.object(wallet_mnemonic,'begin',side_effect=AssertionError('must not generate')):
            self.assertEqual(main(['--json','--command','wallet.create'],lambda:self.service),1)
        self.assertEqual(json.loads(output.getvalue())['error'],'TERMINAL_PRIVATE_WORDS_UI_REQUIRED')

    def test_actual_paper_service_is_qt_solders_and_terminal_library_free(self):
        script=r'''
import builtins,sys,tempfile
from pathlib import Path
from unittest.mock import patch
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {'solders','PySide6','PyQt6','PyQt5','PIL','prompt_toolkit'}:raise AssertionError('optional runtime imported')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from backend import terminal_service,terminal_approval,omni_assets,wallet_mnemonic,sensitive_ui_guard
vector='abandon '*23+'art'
def secret(prompt):return vector.split()[int(prompt.split('#')[1].split()[0])-1]
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    with patch.object(omni_assets,'ROOT',root/'omni'),patch.object(terminal_approval,'STATE_ROOT',root/'approval'),patch.object(wallet_mnemonic._bip39(),'generate',return_value=vector),patch.object(sensitive_ui_guard,'enter'),patch.object(sensitive_ui_guard,'leave'):
        service=terminal_service.TerminalService(confirm=lambda _:True,secret=secret,show_words=lambda words:words==vector.split())
        try:
            result=service.dispatch('wallet.create')
            assert result['method']=='PAPER' and result['word_count']==24 and result['signer_state']=='WATCH_ONLY'
            assert not any(name.split('.')[0] in {'solders','PySide6','PyQt6','PyQt5','PIL','prompt_toolkit'} for name in sys.modules)
        finally:service.close();wallet_mnemonic.cancel_all()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'')


class PrivateTerminalScreenTests(unittest.IsolatedAsyncioTestCase):
    async def until(self,predicate):
        async with asyncio.timeout(5):
            while not predicate():await asyncio.sleep(.01)

    async def exercise(self,accept):
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        class FixtureService:
            def __init__(self):self.closed=0
            def snapshot(self):return {'wallet':{'positions':[],'summary':{}},'consensus':{},'marketplace':{}}
            def dispatch(self,command,args):
                words=VECTOR24.split()
                try:return {'state':'DISPLAYED' if self.show_words(words) is True else 'CANCELLED'}
                finally:words.clear()
            def close(self):self.closed+=1
        service=FixtureService();stream=io.StringIO()
        output=Vt100_Output(stream,lambda:Size(rows=24,columns=40),term='xterm-256color',enable_cpr=False,enable_bell=False)
        with create_pipe_input() as pipe:
            app=TerminalApp(service,input=pipe,output=output);task=asyncio.create_task(app.run_async())
            try:
                await self.until(lambda:bool(app.model.state) and not app.model.busy)
                app.submit('wallet.create',{})
                await self.until(lambda:'PRIVAT ATERSTALLNINGSFRAS' in stream.getvalue())
                # Secret surface is local; main model/fragments remain public.
                self.assertNotIn('abandon',repr(app.model));self.assertNotIn('abandon',repr(app._fragments()))
                if accept is None:
                    app.application.exit()
                    await asyncio.wait_for(task,5)
                else:pipe.send_text('\r' if accept else '\x1b')
                await self.until(lambda:not app.model.busy)
                self.assertEqual(app.model.result,{'state':'DISPLAYED' if accept else 'CANCELLED'})
                self.assertNotIn('abandon',repr(app.model));self.assertNotIn('abandon',repr(app.__dict__))
                self.assertIn('\x1b[2J',stream.getvalue(),'private terminal content must be cleared')
            finally:
                if not task.done():pipe.send_text('q')
                await asyncio.wait_for(task,5)
        self.assertEqual(service.closed,1)

    async def test_private_numbered_screen_enter_restores_public_model(self):await self.exercise(True)
    async def test_private_numbered_screen_escape_cancels_and_close_is_async(self):await self.exercise(False)
    async def test_main_shutdown_closes_private_screen_before_worker_finishes(self):await self.exercise(None)


if __name__=='__main__':unittest.main()
