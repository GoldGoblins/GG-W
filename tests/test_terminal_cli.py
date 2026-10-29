"""Native terminal input/output, exact command routing and public text safety.

Services in this file are deterministic fixtures; no wallet database, live node,
external RPC, approval store or remembered user state is opened.
"""
from copy import deepcopy
from contextlib import redirect_stderr,redirect_stdout
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from backend.terminal_cli import (TerminalApp,TerminalModel,cell_width,clip,main,
                                  parse_command,public_value,safe_text,selected_transfer_review,public_transfer_review)


def fixture():
    return {'wallet':{'summary':{'known_value_usd':'125.40','account_count':2,'network_count':2,'unpriced_count':1},
        'accounts':[{'id':'watch-1','address':'public-address','chain_id':'solana:mainnet'}],
        'positions':[{'id':'asset-1','account_id':'watch-1','asset_id':'solana:mainnet/slip44:501','symbol':'SOL',
            'network':'Solana','quantity':'1.000000001','value_usd':'102.00','address':'public-address'},
            {'id':'asset-2','account_id':'watch-1','symbol':'TST','network':'Solana',
             'quantity':'31529284.463525','value_usd':None}], 'transfers':[]},
        'marketplace':{'listings':[{'id':'chair','title':'Björkstol','category':'ITEM','material':'WOOD'},
                                   {'id':'hammer','title':'Snickarhammare','category':'TOOL','material':'STEEL'}],
                       'source':'LOCAL','selected':'chair'},
        'consensus':{'state':'RUNNING','online':4,'height':3,'state_height':2,'physical_hosts':1,'operator_count':1,
            'chain_id':'gg-native-fixture','review':None,'validators':[],
            'measurements':[{'elapsed_ms':10},{'elapsed_ms':30},{'elapsed_ms':20}],
            'accounts':[{'index':i,'address':format(i+1,'064x'),'quantity':'1000000' if not i else '0'} for i in range(4)]},
        'activity':[]}


class FakeService:
    def __init__(self):
        self.state=fixture();self.calls=[];self.closed=0;self.confirm=None;self.secret=None

    def snapshot(self):return deepcopy(self.state)

    def dispatch(self,command,args):
        self.calls.append((command,deepcopy(args)))
        if command=='status':return self.snapshot()
        if command=='help':return {'commands':{'network.start':[],'wallet.watch':['chain_id','address','label']}}
        if command=='wallet.create':
            password=self.secret('Fixture password:')
            if password!='synthetic-only-phrase':raise ValueError('FIXTURE_SECRET_MISMATCH')
            if not self.confirm('Create the fixture wallet only'):raise ValueError('TERMINAL_APPROVAL_REJECTED')
            return {'state':'CREATED','public_key':'fixture-public'}
        return {'state':'OK','command':command,'args':args}

    def close(self):self.closed+=1


class PureTerminalTests(unittest.TestCase):
    def test_review_keeps_digest_and_selected_account(self):
        state=fixture();state['consensus']['review']={'id':'gg-review','review_digest':'a'*64,'amount':'1','symbol':'GG-NET-TEST'}
        body={'account_id':'watch-1','amount':'1.000001','symbol':'GGHB','from':'source','to':'recipient','chain_id':'solana:mainnet'}
        state['wallet']['transfers']=[{'id':'sol-review','state':'PREPARED','review_digest':'b'*64,'body':body}]
        review=selected_transfer_review(state,{'account_id':'watch-1'})
        self.assertEqual((review['id'],review['review_digest']),('sol-review','b'*64))
        self.assertEqual(selected_transfer_review(state,{'account_id':'another-watch'}),{})
        self.assertEqual(selected_transfer_review(state,{'account_id':'gg-test-0'})['id'],'gg-review')
        shown=public_transfer_review(review)
        self.assertEqual(shown['Belopp'],'1.000001 GGHB')
        self.assertNotIn('review_digest',shown);self.assertNotIn('id',shown)

    def test_public_catalogue_rows_and_phone_exit_hint(self):
        state=fixture();state['marketplace']['public_catalog']={'rows':[{'id':'collection','name':'Public collection','chain_id':'eip155:1'}]}
        model=TerminalModel(state=state,view=1,public_market=True)
        self.assertEqual(model.rows()[0]['id'],'collection')
        self.assertIn('Public collection','\n'.join(model.frame(80,24)))
        self.assertIn('q ut',model.frame(40,24)[-1])

    def test_phone_desktop_and_wide_fit_cells_keep_exact_quantity_and_unknown_price(self):
        for width,height in [(40,24),(80,24),(120,40)]:
            for view in range(3):
                model=TerminalModel(state=fixture(),view=view)
                frame=model.frame(width,height)
                self.assertEqual(height,len(frame))
                self.assertTrue(all(cell_width(line)<=width for line in frame))
                self.assertIn('[WALLET]' if view==0 else '[MP]' if view==1 else '[NÄTVERK]','\n'.join(frame))
                if not view:
                    self.assertIn('31529284.463525','\n'.join(frame))
                    self.assertIn('Ej prissatt','\n'.join(frame))
                if view==2:
                    self.assertIn('4/4','\n'.join(frame))
                    self.assertIn('lokalt test','\n'.join(frame))
        wide='\n'.join(TerminalModel(state=fixture()).frame(120,40))
        self.assertIn(' | ',wide)
        self.assertNotIn(' | ','\n'.join(TerminalModel(state=fixture()).frame(80,24)))

    def test_terminal_escape_and_bidi_injection_cannot_reach_render_or_json(self):
        attack='ok\x1b[2J\x1b]52;c;stolen\x07\x1bPmalicious\x1b\\\r\u202eevil\x00'
        state=fixture();state['wallet']['positions'][0]['symbol']=attack
        state['wallet']['positions'][0]['private_key']='never-display'
        value=public_value(state)
        rendered='\n'.join(TerminalModel(state=value,details=True).frame(80,24))
        encoded=json.dumps(value)
        for bad in ('\x1b','\x00','\r','\u202e','stolen','malicious','never-display'):
            self.assertNotIn(bad,rendered+encoded)
        self.assertEqual({'v':None},public_value({'v':float('nan')}))
        self.assertEqual(3,cell_width('界e\u0301'))
        self.assertLessEqual(cell_width(clip('界界界',4)),4)

    def test_detail_address_is_complete_and_scrollable_without_horizontal_overflow(self):
        state=fixture();address='0123456789abcdef'*4
        state['wallet']['positions'][0]['address']=address
        model=TerminalModel(state=state,details=True)
        seen=''
        for offset in range(0,100,8):
            model.detail_offset=offset
            frame=model.frame(40,24)
            self.assertTrue(all(cell_width(line)<=40 for line in frame))
            seen+=''.join(line.strip() for line in frame)
        self.assertIn(address,seen)

    def test_parser_keeps_financial_strings_and_never_evaluates_shell(self):
        command,args=parse_command(':network.prepare sender=0 recipient=pub amount=0.000001')
        self.assertEqual('network.prepare',command)
        self.assertEqual({'sender':0,'recipient':'pub','amount':'0.000001'},args)
        self.assertEqual({'count':32},parse_command('network.benchmark {"count":32}')[1])
        self.assertEqual('$(touch bad)',parse_command('wallet.watch label="$(touch bad)"')[1]['label'])
        for text in ('network.start; del /s *','wallet.create password=bad','wallet.create {"nested":{"seed":"bad"}}'):
            with self.assertRaises((ValueError,TypeError)):parse_command(text)
        with self.assertRaises(ValueError):parse_command('network.benchmark count=1',{'count':2})

    def test_json_cli_routes_actual_dispatch_returns_result_and_closes(self):
        service=FakeService();stdout=io.StringIO()
        with redirect_stdout(stdout):
            result=main(['--json','--command','network.prepare','--args','{"sender":0,"recipient":"pub","amount":"1.000001"}'],lambda:service)
        self.assertEqual(0,result)
        self.assertEqual('1.000001',service.calls[0][1]['amount'])
        self.assertEqual('network.prepare',json.loads(stdout.getvalue())['command'])
        self.assertEqual(1,service.closed)

    def test_noninteractive_approval_and_secret_fail_closed_without_getpass(self):
        service=FakeService();stdout=io.StringIO()
        with redirect_stdout(stdout),patch('getpass.getpass',side_effect=AssertionError('must not read redirected stdin')):
            code=main(['--json','--command','wallet.create','--args','{"label":"fixture"}'],lambda:service)
        self.assertEqual(1,code)
        self.assertEqual('TERMINAL_INTERACTIVE_INPUT_REQUIRED',json.loads(stdout.getvalue())['error'])
        self.assertNotIn('synthetic-only-phrase',stdout.getvalue())
        self.assertEqual(1,service.closed)

    def test_one_shot_tty_uses_hidden_password_and_literal_human_confirmation(self):
        class TtyBuffer(io.StringIO):
            def isatty(self):return True
        service=FakeService();out=TtyBuffer()
        with redirect_stdout(out),patch('sys.stdin.isatty',return_value=True),\
             patch('getpass.getpass',return_value='synthetic-only-phrase') as hidden,\
             patch('builtins.input',return_value='yes') as answer:
            code=main(['--once','--command','wallet.create','--args','{"label":"fixture"}'],lambda:service)
        self.assertEqual(0,code);hidden.assert_called_once();answer.assert_called_once()
        self.assertIn('CREATED',out.getvalue());self.assertNotIn('synthetic-only-phrase',out.getvalue())
        self.assertEqual(1,service.closed)

    def test_secret_in_cli_arguments_rejected_before_service_dispatch(self):
        service=FakeService();out=io.StringIO()
        with redirect_stdout(out):code=main(['--json','--command','wallet.create','--args','{"password":"bad"}'],lambda:service)
        self.assertEqual(1,code);self.assertEqual([],service.calls)
        self.assertEqual('TERMINAL_SECRET_REQUIRES_INTERACTIVE_INPUT',json.loads(out.getvalue())['error'])

    def test_frontend_import_is_headless_and_has_no_terminal_dependency_for_once(self):
        script="import sys; import backend.terminal_cli; assert not any(k.startswith(('PySide6','PyQt','solders','prompt_toolkit')) for k in sys.modules)"
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
        self.assertEqual(0,result.returncode,result.stderr)


class NativeTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def until(self,predicate,timeout=5):
        async with asyncio.timeout(timeout):
            while not predicate():await asyncio.sleep(.01)

    def output(self,width=80,height=24):
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        stream=io.StringIO()
        return stream,Vt100_Output(stream,lambda:Size(rows=height,columns=width),term='xterm-256color',enable_cpr=False,enable_bell=False)

    async def test_real_native_input_navigation_command_filter_and_quiescent_redraw(self):
        from prompt_toolkit.input.defaults import create_pipe_input
        for width,height in [(40,24),(80,24),(120,40)]:
            with create_pipe_input() as pipe:
                service=FakeService();stream,output=self.output(width,height)
                app=TerminalApp(service,input=pipe,output=output)
                task=asyncio.create_task(app.run_async())
                try:
                    await self.until(lambda:bool(app.model.state) and not app.model.busy)
                    pipe.send_text('2');await self.until(lambda:app.model.view==1)
                    pipe.send_text('/hammare\r');await self.until(lambda:app.model.query=='hammare')
                    self.assertEqual(['hammer'],[r['id'] for r in app.model.rows()])
                    pipe.send_text(':network.start\r')
                    await self.until(lambda:('network.start',{}) in service.calls and not app.model.busy)
                    await asyncio.sleep(.12)
                    renders=app.render_count
                    await asyncio.sleep(.20)
                    self.assertEqual(renders,app.render_count,'an idle terminal must not repaint on a timer')
                    self.assertIn('GG AI DESKTOP',stream.getvalue())
                    self.assertIn('\x1b[',stream.getvalue(),'must be actual VT100 terminal output')
                finally:
                    pipe.send_text('q');await asyncio.wait_for(task,5)
                self.assertEqual(1,service.closed)

    async def test_slow_operation_leaves_navigation_responsive_and_close_waits_for_worker(self):
        from prompt_toolkit.input.defaults import create_pipe_input
        service=FakeService();started=threading.Event();release=threading.Event()
        original=service.dispatch
        def dispatch(command,args):
            if command=='network.selftest':started.set();release.wait(5)
            return original(command,args)
        service.dispatch=dispatch
        with create_pipe_input() as pipe:
            stream,output=self.output();app=TerminalApp(service,input=pipe,output=output)
            task=asyncio.create_task(app.run_async())
            try:
                await self.until(lambda:bool(app.model.state) and not app.model.busy)
                app.submit('network.selftest',{})
                await self.until(started.is_set)
                self.assertFalse(app.submit('network.start',{}))
                pipe.send_text('3');await self.until(lambda:app.model.view==2)
                pipe.send_text('q');await self.until(lambda:app._closing)
                await asyncio.sleep(.05)
                self.assertEqual(0,service.closed)
                self.assertFalse(task.done())
            finally:
                release.set()
                await asyncio.wait_for(task,5)
            self.assertEqual(1,service.closed)
            self.assertEqual([('network.selftest',{})],service.calls)

    async def test_secret_and_exact_confirmation_are_native_hidden_prompts_on_ui_loop(self):
        from prompt_toolkit.input.defaults import create_pipe_input
        with create_pipe_input() as pipe:
            service=FakeService();stream,output=self.output()
            app=TerminalApp(service,input=pipe,output=output)
            task=asyncio.create_task(app.run_async())
            try:
                await self.until(lambda:bool(app.model.state) and not app.model.busy)
                app.submit('wallet.create',{'label':'fixture'})
                await self.until(lambda:'Fixture password:' in stream.getvalue())
                pipe.send_text('synthetic-only-phrase\r')
                await self.until(lambda:'Godkänn exakt denna' in stream.getvalue())
                pipe.send_text('ja\r')
                await self.until(lambda:not app.model.busy)
                self.assertEqual('CREATED',app.model.result['state'])
                self.assertIn('Create the fixture wallet only',stream.getvalue())
                self.assertNotIn('synthetic-only-phrase',stream.getvalue())
                self.assertNotIn('synthetic-only-phrase',repr(app.model))
            finally:
                pipe.send_text('q');await asyncio.wait_for(task,5)
            self.assertEqual(1,service.closed)

    async def test_wallet_prepare_form_uses_selected_account_and_exact_amount(self):
        from prompt_toolkit.input.defaults import create_pipe_input
        with create_pipe_input() as pipe:
            service=FakeService();stream,output=self.output()
            app=TerminalApp(service,input=pipe,output=output)
            task=asyncio.create_task(app.run_async())
            try:
                await self.until(lambda:bool(app.model.state) and not app.model.busy)
                pipe.send_text('f')
                await self.until(lambda:'Mottagarens offentliga adress:' in stream.getvalue())
                pipe.send_text('fixture-recipient\r')
                await self.until(lambda:'Belopp:' in stream.getvalue())
                pipe.send_text('0.000001\r')
                await self.until(lambda:bool(service.calls) and not app.model.busy)
                self.assertEqual([('wallet.prepare',{'account_id':'watch-1','asset_id':'solana:mainnet/slip44:501',
                    'recipient':'fixture-recipient','amount':'0.000001'})],service.calls)
                self.assertNotIn('Avsändarkontots ID',stream.getvalue())
            finally:
                pipe.send_text('q');await asyncio.wait_for(task,5)
            self.assertEqual(1,service.closed)


async def render_terminal_previews(directory):
    """Explicit development helper: replay actual VT100 output through pyte.

    pyte/Pillow are preview tools, not runtime terminal dependencies. Fixtures
    are marked as such in the terminal. Normal unit runs never write artifacts.
    """
    import pyte
    from PIL import Image,ImageDraw,ImageFont
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output.vt100 import Vt100_Output
    from prompt_toolkit.data_structures import Size
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    palette={'default':'#d8d9d5','black':'#101110','white':'#d8d9d5','brown':'#c6ac6d',
             'brightwhite':'#eeeae0','brightblack':'#454743','green':'#83bb97','red':'#ce7d78'}
    def color(value,default):
        if value in palette:return palette[value] if value!='default' else default
        if len(value)==6 and all(c in '0123456789abcdefABCDEF' for c in value):return '#'+value
        return default
    font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',14)
    bold=ImageFont.truetype('C:/Windows/Fonts/consolab.ttf',14)
    paths=[]
    for width,height,view in [(40,24,0),(120,40,0),(120,40,1),(120,40,2)]:
        stream=io.StringIO()
        output=Vt100_Output(stream,lambda:Size(rows=height,columns=width),term='xterm-256color',enable_cpr=False,enable_bell=False)
        with create_pipe_input() as pipe:
            app=TerminalApp(FakeService(),input=pipe,output=output)
            task=asyncio.create_task(app.run_async())
            try:
                async with asyncio.timeout(5):
                    while app.model.busy or not app.model.state:await asyncio.sleep(.01)
                app._view(view);app.model.notice='VISUELLT TEST · syntetiska data';app.application.invalidate()
                await asyncio.sleep(.10)
                native_stream=stream.getvalue()
                screen=pyte.Screen(width,height);pyte.Stream(screen).feed(native_stream)
                cell_w=9;cell_h=19
                image=Image.new('RGB',(width*cell_w,height*cell_h),'#101110');draw=ImageDraw.Draw(image)
                for y in range(height):
                    for x in range(width):
                        cell=screen.buffer[y][x]
                        fg=color(cell.fg,'#d8d9d5');bg=color(cell.bg,'#101110')
                        if cell.reverse:fg,bg=bg,fg
                        draw.rectangle((x*cell_w,y*cell_h,(x+1)*cell_w-1,(y+1)*cell_h-1),fill=bg)
                        draw.text((x*cell_w,y*cell_h),cell.data,font=bold if cell.bold else font,fill=fg)
                stem='gg-terminal-'+('wallet','marketplace','network')[view]+'-'+str(width)+'x'+str(height)
                png=directory/(stem+'.png');image.save(png)
                (directory/(stem+'.ansi')).write_text(native_stream,encoding='utf-8')
                (directory/(stem+'.txt')).write_text('\n'.join(screen.display),encoding='utf-8')
                paths.append(str(png))
            finally:
                pipe.send_text('q');await asyncio.wait_for(task,5)
    return paths


if __name__=='__main__':unittest.main()
