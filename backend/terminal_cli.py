"""Portable GG terminal UI, one-shot CLI and explicit owned foreground labs.

The terminal renders public service data and forwards explicit operations to
TerminalService. It never constructs a transaction or chooses an RPC endpoint.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys
import time
import unicodedata

VIEWS=('WALLET','MARKETPLACE','NETWORK')
FOREGROUND_COMMANDS=frozenset({'network.start','dag.live_start','lan.start','lan.join_file'})
SENSITIVE={'password','passphrase','mnemonic','words','answers','privatekey','private_key','secret','seed','seed_phrase',
           'validator_seed','node_seed','signing_key'}
_ESCAPE=re.compile(r'\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[PX^_][^\x1b]*(?:\x1b\\)|[@-_])')


def terminal_styles():
    """Use the same source palette as native GG controls, without importing Qt."""
    source = Path(__file__).resolve().parents[1] / 'config/gg-palette.json'
    palette = json.loads(source.read_text(encoding='utf-8'))
    roles = palette['roles']
    required = ('canvas', 'text', 'bright', 'accent', 'line', 'muted', 'selected',
                'positive', 'negative', 'warning', 'cyan', 'purple')
    if palette.get('schema') != 'gg.palette.v1' or any(
            not isinstance(roles.get(name), str) or not re.fullmatch(r'#[0-9a-f]{6}', roles[name])
            for name in required):
        raise ValueError('GG_TERMINAL_PALETTE_INVALID')
    return {'': 'bg:' + roles['canvas'] + ' ' + roles['text'],
            'title': roles['bright'] + ' bold', 'accent': roles['accent'] + ' bold',
            'rule': roles['line'], 'muted': roles['muted'],
            'currentrow': 'bg:' + roles['selected'] + ' ' + roles['accent'] + ' noreverse',
            **{name: roles[name] for name in ('positive', 'negative', 'warning', 'cyan', 'purple')}}


def safe_text(value,limit=8192):
    """Remove terminal controls, OSC/CSI and bidi controls from untrusted data."""
    text=_ESCAPE.sub('',str(value if value is not None else '—')[:limit])
    return ''.join(c for c in text if unicodedata.category(c) not in {'Cc','Cf','Cs'} or c in '\n\t').replace('\t',' ')


def public_value(value,depth=0):
    if depth>16:return '[depth limit]'
    if isinstance(value,dict):
        return {safe_text(k,160):('[redacted]' if str(k).lower().replace('-','_') in SENSITIVE
                else public_value(v,depth+1)) for k,v in list(value.items())[:4096]}
    if isinstance(value,(list,tuple)):return [public_value(v,depth+1) for v in value[:4096]]
    if isinstance(value,str):return safe_text(value)
    if type(value) is float and not math.isfinite(value):return None
    if value is None or type(value) in {int,float,bool}:return value
    return safe_text(value)


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {'W','F'} else 1 for c in text)


def clip(value,width):
    text=safe_text(value).replace('\n',' ')
    if width<=0:return ''
    if cell_width(text)<=width:return text
    result='';remaining=max(0,width-1)
    for char in text:
        size=cell_width(char)
        if size>remaining:break
        result+=char;remaining-=size
    return result+'…'


def pad(value,width):
    text=clip(value,width)
    return text+' '*max(0,width-cell_width(text))


def pair(left,right,width):
    right=clip(right,max(0,width//2))
    return pad(left,max(0,width-cell_width(right)))+right


def wrap(value,width):
    result=[]
    for paragraph in safe_text(value).splitlines() or ['']:
        line='';used=0
        for char in paragraph:
            size=cell_width(char)
            if used+size>width and line:result.append(line);line='';used=0
            line+=char;used+=size
        result.append(line)
    return result


def _secret_arguments(args):
    if isinstance(args,dict):
        return any(str(k).lower().replace('-','_') in SENSITIVE or _secret_arguments(v) for k,v in args.items())
    return isinstance(args,list) and any(_secret_arguments(v) for v in args)


def parse_command(text,extra=None):
    text=text.strip().lstrip(':').strip()
    if not text:raise ValueError('TERMINAL_COMMAND_REQUIRED')
    command,_,tail=text.partition(' ')
    if not re.fullmatch(r'[a-z][a-z0-9_.]{0,63}',command):raise ValueError('TERMINAL_COMMAND_INVALID')
    args={}
    if tail.strip().startswith('{'):
        args=json.loads(tail)
        if not isinstance(args,dict):raise ValueError('TERMINAL_ARGUMENT_OBJECT_REQUIRED')
    elif tail.strip():
        for token in shlex.split(tail):
            key,separator,value=token.partition('=')
            if not separator or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',key) or key in args:
                raise ValueError('TERMINAL_ARGUMENT_INVALID')
            # Financial values remain exact strings, never binary floats.
            if key in {'sender','index','count','blocks','transactions_per_block','max_transactions_per_block','interval_ms','producer_count','port','duration_ms','batch'} and re.fullmatch(r'-?\d+',value):args[key]=int(value)
            elif key in {'auto_produce','distribute','allow_test_tokens','enable_test_tokens','allow_dag_transactions','enable_dag_transactions'} and value in {'true','false'}:args[key]=value=='true'
            else:args[key]=value
    if extra:
        for key,value in extra.items():
            if key in args:raise ValueError('TERMINAL_DUPLICATE_ARGUMENT')
            args[key]=value
    if _secret_arguments(args):raise ValueError('TERMINAL_SECRET_REQUIRES_INTERACTIVE_INPUT')
    return command,args


def _error(error):
    code=str(error)
    return code if re.fullmatch(r'[A-Z][A-Z0-9_]{1,95}',code) else 'TERMINAL_OPERATION_FAILED'


def _object(value):return value if isinstance(value,dict) else {}


def selected_transfer_review(state,selection,network_view=False):
    """Keep the selected account's frozen draft and its exact send binding."""
    local=network_view or selection.get('scope')=='LOCAL_TEST' or str(selection.get('account_id','')).startswith('gg-test-')
    if local:return _object(_object(state.get('consensus')).get('review'))
    account=selection.get('account_id')
    drafts=_object(state.get('wallet')).get('transfers',[])
    if isinstance(drafts,dict):drafts=drafts.get('transfers',[])
    for draft in drafts:
        body=_object(draft.get('body'))
        if draft.get('state')=='PREPARED' and body and account and body.get('account_id')==account:
            return dict(body,id=draft.get('id'),review_digest=draft.get('review_digest'))
    return {}


def public_transfer_review(review):
    return {'Från':review.get('from',review.get('sender')),'Till':review.get('to',review.get('recipient')),
            'Belopp':str(review.get('amount','—'))+' '+str(review.get('symbol','')),
            'Nätverk':review.get('chain_id'),'Mint':review.get('mint') or review.get('symbol'),
            'Avgift och kontohyra SOL':review.get('cost_sol')}


def detail_lines(value,width,depth=0):
    """Small native text tree. No HTML, textures, overlays or escape markup."""
    lines=[]
    prefix=' '*min(depth*2,12)
    if isinstance(value,dict):
        for key,item in value.items():
            label=safe_text(key).replace('_',' ')
            if isinstance(item,(dict,list)):
                lines.append(clip(prefix+label.upper(),width))
                lines.extend(detail_lines(item,width,depth+1))
            else:lines.extend(wrap(prefix+label+': '+safe_text(item),width))
    elif isinstance(value,list):
        for index,item in enumerate(value):
            if isinstance(item,(dict,list)):
                lines.append(clip(prefix+'['+str(index+1)+']',width));lines.extend(detail_lines(item,width,depth+1))
            else:lines.extend(wrap(prefix+'- '+safe_text(item),width))
    else:lines.extend(wrap(prefix+safe_text(value),width))
    return lines


@dataclass
class TerminalModel:
    state:dict=field(default_factory=dict)
    view:int=0
    selected:int=0
    query:str=''
    details:bool=False
    detail_offset:int=0
    notice:str='Läser lokal status…'
    busy:bool=False
    result:object=None
    result_details:bool=False
    public_market:bool=False

    def rows(self):
        if self.view==0:
            wallet=_object(self.state.get('wallet'))
            rows=wallet.get('positions',wallet.get('rows',[])) or []
        elif self.view==1:
            market=_object(self.state.get('marketplace'))
            rows=(_object(market.get('public_catalog')).get('rows',[]) if self.public_market else market.get('listings',[])) or []
        else:rows=_object(self.state.get('consensus')).get('accounts',[]) or []
        query=self.query.casefold()
        return [row for row in rows if isinstance(row,dict) and (not query or query in safe_text(json.dumps(public_value(row),ensure_ascii=False)).casefold())]

    def selection(self):
        rows=self.rows()
        self.selected=min(max(0,self.selected),max(0,len(rows)-1))
        return rows[self.selected] if rows else {}

    def detail(self):
        if self.result_details:return self.result or {}
        selected=self.selection()
        if self.view==2:
            network=_object(self.state.get('consensus'))
            review=network.get('review')
            if review:return {'GRANSKA TESTÖVERFÖRING':public_transfer_review(review),'NÄTVERK':{k:network.get(k) for k in ('state','chain_id','height','state_height','online','quorum_required','operator_count','physical_hosts')}}
            return {'KONTO':selected,'NÄTVERK':{k:network.get(k) for k in ('state','chain_id','height','state_height','online','quorum_required','operator_count','physical_hosts','benchmark','last_test','validators')},'HÄNDELSER':network.get('events',[])[-6:]}
        if self.view==1:
            market=_object(self.state.get('marketplace'))
            return {'SAMLINGSPASS' if self.public_market else 'OBJEKTPASS':selected,'KÄLLA':'Publik katalog · ingen säljorder' if self.public_market else 'Lokalt dokumenterat'}
        return {'TILLGÅNG':selected,'KONTON':_object(self.state.get('wallet')).get('accounts',[])}

    def heading(self,width):
        if self.view==0:
            summary=_object(_object(self.state.get('wallet')).get('summary'))
            value=summary.get('known_value_usd')
            return [pair('VÄRDERAT INNEHAV',('$'+str(value)) if value is not None else '—',width),
                    clip(str(summary.get('account_count',0))+' konton · '+str(summary.get('network_count',0))+' nätverk · '+str(summary.get('unpriced_count',0))+' ej prissatta',width)]
        if self.view==1:
            market=_object(self.state.get('marketplace'))
            return [pair('MARKETPLACE',str(len(self.rows()))+' poster',width),clip('Publika samlingar · katalog, ej säljorder' if self.public_market else 'Lokala objekt · l byter till publik katalog',width)]
        network=_object(self.state.get('consensus'))
        online=network.get('online',0)
        if type(online) is not int:online=0
        lines=[pair('GG NÄTVERK',network.get('state','STOPPED'),width),
                clip('['+'#'*max(0,min(4,online))+'-'*(4-max(0,min(4,online)))+'] '+str(online)+'/4 validatorer · 3 krävs',width),
                clip('Certifierat block '+str(network.get('height') or '—')+' · tillstånd '+str(network.get('state_height') if network.get('state_height') is not None else '—'),width),
                clip(str(network.get('operator_count',1))+' operatör · '+str(network.get('physical_hosts',1))+' maskin · lokalt test',width)]
        benchmark=_object(network.get('benchmark'))
        if benchmark:lines.append(clip(str(benchmark.get('state',''))+' · '+str(benchmark.get('tps','—'))+' verifierade tx/s · p95 '+str(benchmark.get('p95_ms','—'))+' ms',width))
        samples=[v.get('elapsed_ms') for v in network.get('measurements',[]) if isinstance(v,dict) and type(v.get('elapsed_ms')) in {int,float} and math.isfinite(v['elapsed_ms']) and v['elapsed_ms']>=0][-min(40,width-4):]
        if samples:
            maximum=max(samples) or 1
            lines.append(clip('ms '+''.join(' .:-=+*#'[min(7,int(v/maximum*7))] for v in samples)+' '+str(max(samples)),width))
        return lines

    def row_lines(self,row,index,width):
        marker='> ' if index==self.selected else '  '
        available=max(0,width-2)
        if self.view==0:
            value=row.get('value_usd')
            first=pair(str(row.get('symbol','?'))+' · '+str(row.get('network',row.get('chain_id',''))),
                       '$'+str(value) if value is not None else 'Ej prissatt',available)
            second=str(row.get('quantity','—'))
        elif self.view==1:
            first=pair(row.get('title',row.get('name','Namnlöst')),row.get('price_label',row.get('status','')),available)
            second=(str(row.get('chain_id',''))+' · publik samling') if self.public_market else str(row.get('category',''))+' · '+str(row.get('material',row.get('source','Lokalt')))
        else:
            account_index=row.get('index',index)
            if type(account_index) is not int:account_index=index
            first=pair('Konto '+str(account_index+1),str(row.get('quantity','—'))+' GG-NET-TEST',available)
            second=str(row.get('address','—'))
        return [marker+first,'  '+clip(second,available)]

    def frame(self,width=80,height=24):
        width=max(24,min(300,width));height=max(8,min(120,height))
        rows=self.rows();self.selection()
        tab='  '.join(('['+name+']') if index==self.view else name for index,name in enumerate(('WALLET','MP','NÄTVERK')))
        title=pair('GG AI DESKTOP', 'TERMINAL',width)
        lines=[title,clip(tab,width),'-'*width]
        room=max(1,height-6)
        if self.details:
            detail=detail_lines(public_value(self.detail()),width)
            self.detail_offset=min(max(0,self.detail_offset),max(0,len(detail)-room))
            lines.extend(detail[self.detail_offset:self.detail_offset+room])
        else:
            wide=width>=105
            left_width=width if not wide else width-int(width*.31)-3
            content=self.heading(left_width)+['-'*left_width]
            if self.query:content.append(clip('Sök: '+self.query,left_width))
            rows_room=max(1,(room-len(content))//2)
            first=max(0,min(self.selected-rows_room+1,max(0,len(rows)-rows_room)))
            for index in range(first,min(len(rows),first+rows_room)):
                content.extend(self.row_lines(rows[index],index,left_width))
            if not rows:content.append(clip('Inga poster. a: lägg till · ?: hjälp',left_width))
            if wide:
                detail=detail_lines(public_value(self.detail()),width-left_width-3)
                lines.extend(pad(content[i] if i<len(content) else '',left_width)+' | '+clip(detail[i] if i<len(detail) else '',width-left_width-3) for i in range(room))
            else:lines.extend(content[:room])
        while len(lines)<height-3:lines.append('')
        lines.extend(['-'*width,clip(('ARBETAR · ' if self.busy else '')+self.notice,width),
                      clip('1–3 flik  ↑↓ välj  / sök  ? hjälp  q ut' if width<60 else '1–3 flik  ↑↓ välj  / sök  : kommando  ? hjälp  q avsluta',width)])
        return [clip(line,width) for line in lines[:height]]


class TerminalApp:
    def __init__(self,service,*,input=None,output=None):
        # Only fullscreen operation needs this optional terminal dependency.
        from prompt_toolkit.application import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.history import DummyHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import ConditionalContainer,HSplit,Layout,Window
        from prompt_toolkit.layout.controls import BufferControl,FormattedTextControl
        from prompt_toolkit.styles import Style
        self.service=service;self.model=TerminalModel();self.mode='';self._task=None;self._closing=False
        self._form_active=False;self._form_task=None;self._loop=None
        self._private_application=None;self._interactive_prompt=None
        # Dispatch runs on one worker; only the UI loop owns terminal input.
        self.service.confirm=self._confirm_from_worker
        self.service.secret=self._secret_from_worker
        self.service.show_words=self._words_from_worker
        self.render_count=0
        self.command_buffer=Buffer(history=DummyHistory(),multiline=False,accept_handler=self._accept)
        self.body_control=FormattedTextControl(self._fragments,focusable=True)
        self.body_window=Window(self.body_control,always_hide_cursor=True,wrap_lines=False)
        self.editor=Window(BufferControl(self.command_buffer),height=1)
        layout=Layout(HSplit([self.body_window,ConditionalContainer(self.editor,Condition(lambda:bool(self.mode)))]),focused_element=self.body_window)
        keys=KeyBindings();normal=Condition(lambda:not self.mode)
        for key,view in [('1',0),('2',1),('3',2)]:
            def change(event,view=view):self._view(view)
            keys.add(key,filter=normal)(change)
        for key,delta in [('right',1),('left',-1),('tab',1),('s-tab',-1)]:
            def change(event,delta=delta):self._view((self.model.view+delta)%3)
            keys.add(key,filter=normal)(change)
        for key,delta in [('down',1),('up',-1),('pagedown',8),('pageup',-8)]:
            def move(event,delta=delta):
                if self.model.details:self.model.detail_offset=max(0,self.model.detail_offset+delta)
                else:self.model.selected=max(0,min(max(0,len(self.model.rows())-1),self.model.selected+delta))
                self.application.invalidate()
            keys.add(key,filter=normal)(move)
        @keys.add('enter',filter=normal)
        def details(event):
            if self.model.view==1 and not self.model.details and self.model.selection().get('id'):
                if self.model.public_market:self.submit('marketplace.public',{'operation':{'action':'select','id':self.model.selection()['id']}})
                else:self.submit('marketplace.select',{'id':self.model.selection()['id']})
            self.model.details=not self.model.details;self.model.detail_offset=0
            self.application.invalidate()
        @keys.add('/',filter=normal)
        def search(event):self._edit('search')
        @keys.add(':',filter=normal)
        def command(event):self._edit('command')
        @keys.add('escape')
        def escape(event):
            if self.mode:self._end_edit()
            elif self.model.details:self.model.details=False;self.model.result_details=False
            elif self.model.query:self.model.query='';self.model.selected=0
            self.application.invalidate()
        @keys.add('r',filter=normal)
        def refresh(event):self.submit('wallet.refresh' if self.model.view==0 else 'status',{})
        @keys.add('a',filter=normal)
        def add(event):self._form('add')
        @keys.add('t',filter=normal)
        def token(event):self._form('token')
        @keys.add('n',filter=normal)
        def create(event):self._form('create')
        @keys.add('k',filter=normal)
        def backup(event):self._form('backup')
        @keys.add('o',filter=normal)
        def restore(event):self._form('restore')
        @keys.add('m',filter=normal)
        def recovery(event):self._form('recovery')
        @keys.add('g',filter=normal)
        def export_recovery(event):self._form('export_recovery')
        @keys.add('u',filter=normal)
        def public_refresh(event):
            if self.model.view==1:
                self.model.public_market=True;self.model.selected=0
                self.submit('marketplace.public',{'operation':{'action':'refresh'}})
        @keys.add('l',filter=normal)
        def market_source(event):
            if self.model.view==1:
                self.model.public_market=not self.model.public_market;self.model.selected=0
                self.model.details=False;self.model.result_details=False;self.application.invalidate()
        @keys.add('e',filter=normal)
        def receive(event):
            account=self.model.selection().get('account_id')
            if account:self.submit('wallet.receive',{'account_id':account})
            else:self.model.notice='Välj en tillgång med konto först.';self.application.invalidate()
        @keys.add('s',filter=normal)
        def send(event):self._form('send')
        @keys.add('f',filter=normal)
        def prepare(event):self._form('prepare' if self.model.view==0 else 'add')
        @keys.add('b',filter=normal)
        def benchmark(event):
            if self.model.view==2:self.submit('network.benchmark',{'count':32})
        @keys.add('v',filter=normal)
        def verify(event):
            if self.model.view==2:self.submit('network.selftest',{})
        @keys.add('p',filter=normal)
        def start(event):
            if self.model.view==2:self.submit('network.start',{})
        @keys.add('x',filter=normal)
        def stop(event):
            if self.model.view==2:self.submit('network.stop',{})
        @keys.add('?',filter=normal)
        def help_key(event):self.submit('help',{})
        @keys.add('q',filter=normal)
        @keys.add('c-q')
        def quit_key(event):self._closing=True;self.application.exit()
        @keys.add('c-c')
        def interrupt(event):
            if self.mode:self._end_edit()
            else:self._closing=True;self.application.exit()
        self.application=Application(layout=layout,key_bindings=keys,full_screen=True,input=input,output=output,
            refresh_interval=None,terminal_size_polling_interval=None,min_redraw_interval=.02,
            style=Style.from_dict(terminal_styles()),
            before_render=self._rendered)

    def _rendered(self,app):self.render_count+=1

    def _fragments(self):
        size=self.application.output.get_size()
        lines=self.model.frame(size.columns,max(8,size.rows-(1 if self.mode else 0)))
        fragments=[]
        for index,line in enumerate(lines):
            style='class:title' if index==0 else 'class:accent' if index==1 else 'class:rule' if line.startswith('---') else 'class:currentrow' if line.startswith('> ') else ''
            suffix='\n' if index<len(lines)-1 else ''
            if ' | ' in line:
                left,right=line.split(' | ',1);fragments.extend([(style,left),('class:rule',' | '),('',right+suffix)])
            else:fragments.append((style,line+suffix))
        return fragments

    def _view(self,index):
        self.model.view=index;self.model.selected=0;self.model.query='';self.model.details=False;self.model.detail_offset=0;self.model.result_details=False
        self.application.invalidate()

    def _edit(self,mode):
        self.mode=mode;self.command_buffer.text='';self.application.layout.focus(self.editor)
        self.model.notice='Sökfilter, Enter för att använda' if mode=='search' else 'Kommando och JSON eller nyckel=värde; Enter kör'
        self.application.invalidate()

    def _end_edit(self):
        self.mode='';self.command_buffer.text='';self.application.layout.focus(self.body_window)

    def _accept(self,buffer):
        text=buffer.text;mode=self.mode;self._end_edit()
        if mode=='search':self.model.query=safe_text(text,256);self.model.selected=0
        else:
            try:command,args=parse_command(text);self.submit(command,args)
            except (ValueError,TypeError):self.model.notice='Ogiltigt kommando. ? visar tillgängliga kommandon.'
        self.application.invalidate()
        return True

    def submit(self,command,args):
        if self.model.busy or self._closing:return False
        self.model.busy=True;self.model.notice=command;self.application.invalidate()
        # Application cancels its own background tasks on exit. Keep this
        # operation alive until its worker returns before closing its service.
        self._task=asyncio.create_task(self._perform(command,args))
        return True

    async def _perform(self,command,args):
        try:
            if command=='__snapshot__':snapshot=await asyncio.to_thread(self.service.snapshot);result=None
            else:
                result=await asyncio.to_thread(self.service.dispatch,command,args)
                snapshot=await asyncio.to_thread(self.service.snapshot)
            self.model.state=public_value(snapshot);self.model.result=public_value(result)
            if command=='help' and isinstance(self.model.result,dict):
                self.model.result['terminal_keys']={'alla':'1–3 flik, pilar välj, Enter detaljer, / sök, : kommando, r uppdatera, q avsluta',
                    'wallet':'a bevaka, n skapa, e ta emot, f förbered, s skicka granskad, t token, k backup, o återställ, m visa ord privat, g krypterad frasexport',
                    'marketplace':'a registrera, Enter välj, l lokalt/publikt, u uppdatera publik katalog',
                    'nätverk':'p starta, x stoppa, a/f förbered, s skicka granskad, v funktionstest, b mät 32 tx'}
            self.model.notice='Klart · '+command if command!='__snapshot__' else 'Redo · r uppdaterar'
            self.model.result_details=command not in {'__snapshot__','status','wallet.refresh','marketplace.public','marketplace.select','network.start','network.stop'}
            if self.model.result_details:
                self.model.details=True;self.model.detail_offset=0
        except Exception as error:self.model.notice=_error(error)
        finally:
            self.model.busy=False
            if not self._closing:self.application.invalidate()

    def _form(self,kind):
        if self.model.busy or self._closing or self._form_active:return
        self._form_active=True
        self._form_task=self.application.create_background_task(self._run_form(kind))

    def _from_worker(self,prompt,secret=False):
        if self._closing or self._loop is None:raise ValueError('TERMINAL_INTERACTIVE_INPUT_REQUIRED')
        # A synchronous service callback must never block the event loop itself.
        try:
            if asyncio.get_running_loop() is self._loop:raise ValueError('TERMINAL_INPUT_THREAD_REQUIRED')
        except RuntimeError:pass
        return asyncio.run_coroutine_threadsafe(self._prompt_interactive(prompt,secret),self._loop).result()

    def _secret_from_worker(self,prompt):return self._from_worker(prompt,True)

    def _confirm_from_worker(self,summary):return self._from_worker(summary,False)

    def _words_from_worker(self,words):
        if self._closing or self._loop is None:raise ValueError('TERMINAL_INTERACTIVE_INPUT_REQUIRED')
        try:
            if asyncio.get_running_loop() is self._loop:raise ValueError('TERMINAL_INPUT_THREAD_REQUIRED')
        except RuntimeError:pass
        return asyncio.run_coroutine_threadsafe(self._show_words_interactive(words),self._loop).result()

    async def _show_words_interactive(self,words):
        """A temporary private alternate screen; no model, history or stdout."""
        from prompt_toolkit.application import Application,in_terminal
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit,Layout,Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
        if (not isinstance(words,list) or len(words) not in (12,24) or
                any(not isinstance(word,str) or not word.isascii() or not word.isalpha() or len(word)>16 for word in words)):
            raise ValueError('TERMINAL_PRIVATE_WORDS_INVALID')
        fragments=[];control=None;private=None
        try:
          async with in_terminal():
            if self._closing:raise ValueError('TERMINAL_INTERACTIVE_INPUT_REQUIRED')
            size=self.application.output.get_size();rows=(len(words)+1)//2
            if size.columns<38 or size.rows<rows+6:raise ValueError('TERMINAL_PRIVATE_WORDS_ENLARGE_TERMINAL')
            fragments.extend([('class:title','PRIVAT ATERSTALLNINGSFRAS\n'),
                ('class:warning','Skriv av pa papper. Dela aldrig orden.\n\n')])
            for index in range(rows):
                left=str(index+1).rjust(2)+'. '+words[index]
                other=index+rows
                right=str(other+1).rjust(2)+'. '+words[other] if other<len(words) else ''
                fragments.append(('',left.ljust(19)+right+'\n'))
            fragments.append(('class:muted','\nEnter: undanlagt pa papper  Esc: avbryt'))
            control=FormattedTextControl(fragments,focusable=True)
            keys=KeyBindings()
            @keys.add('enter')
            def proceed(event):event.app.exit(result=True)
            @keys.add('escape')
            @keys.add('c-c')
            def cancel(event):event.app.exit(result=False)
            private=Application(layout=Layout(HSplit([Window(control,always_hide_cursor=True)])),
                key_bindings=keys,full_screen=True,erase_when_done=True,
                input=self.application.input,output=self.application.output,
                style=Style.from_dict(terminal_styles()),refresh_interval=None,
                terminal_size_polling_interval=None)
            self._private_application=private
            try:return await private.run_async()
            except (EOFError,KeyboardInterrupt):return False
            finally:
                # Remove private fragments before restoring the public app.
                control.text='';fragments.clear()
                private.renderer.erase()
                private.output.erase_screen();private.output.flush()
                self._private_application=None
        finally:
            if control is not None:control.text=''
            fragments.clear();control=None;private=None;self._private_application=None

    async def _prompt_interactive(self,prompt,secret):
        from prompt_toolkit import PromptSession,print_formatted_text
        from prompt_toolkit.application import in_terminal
        from prompt_toolkit.history import DummyHistory
        async with in_terminal():
            if self._closing:raise ValueError('TERMINAL_INTERACTIVE_INPUT_REQUIRED')
            session=PromptSession(history=DummyHistory(),input=self.application.input,output=self.application.output)
            self._interactive_prompt=session
            try:
                if secret:return await session.prompt_async(safe_text(prompt,512)+' ',is_password=True)
                print_formatted_text(safe_text(prompt,4096),output=self.application.output)
                answer=await session.prompt_async('Godkänn exakt denna åtgärd? Skriv ja: ')
                return answer.strip().casefold() in {'ja','yes'}
            except (EOFError,KeyboardInterrupt):
                if secret:raise ValueError('TERMINAL_SECRET_CANCELLED') from None
                return False
            finally:
                session.default_buffer.reset()
                self._interactive_prompt=None

    async def _run_form(self,kind):
        from prompt_toolkit import PromptSession,print_formatted_text
        from prompt_toolkit.application import in_terminal
        from prompt_toolkit.history import DummyHistory
        command=None;args={}
        try:
          async with in_terminal():
            session=PromptSession(history=DummyHistory(),input=self.application.input,output=self.application.output)
            async def ask(label,default=''):
                return await session.prompt_async(label+': ',default=default)
            try:
                if kind=='send' and self.model.view in {0,2}:
                    review=selected_transfer_review(self.model.state,self.model.selection(),self.model.view==2)
                    if not review:raise ValueError('NETWORK_PREPARE_FIRST')
                    print_formatted_text('\n'.join(detail_lines(public_value(public_transfer_review(review)),max(24,self.application.output.get_size().columns))),output=self.application.output)
                    consent=(await ask('Granska och fortsätt med denna låsta överföring? Skriv ja')).strip().lower()
                    if consent not in {'ja','yes'}:self.model.notice='Avbrutet';return
                    command='network.send' if self.model.view==2 else 'wallet.send';args={'id':review['id'],'review_digest':review['review_digest']}
                elif self.model.view==0 and kind=='create':
                    command='wallet.create';args={'label':await ask('Walletens namn'),
                        'method':(await ask('Forvaring PAPER eller AI','PAPER')).strip().upper(),
                        'count':int(await ask('Antal ord 12 eller 24','24')),
                        'purpose':(await ask('Roll TRADING eller STORAGE','TRADING')).strip().upper()}
                elif self.model.view==0 and kind=='backup':
                    command='wallet.backup';args={'pubkey':await ask('Walletens offentliga adress',self.model.selection().get('address','')),
                        'path':await ask('Sökväg till krypterad backup')}
                elif self.model.view==0 and kind=='restore':
                    mode=(await ask('Aterstall FRAS eller BACKUP','FRAS')).strip().upper()
                    if mode=='FRAS':
                        command='wallet.restore_phrase';args={'label':await ask('Kontonamn'),
                            'method':(await ask('Forvaring PAPER eller AI','PAPER')).strip().upper(),
                            'purpose':(await ask('Roll TRADING eller STORAGE','TRADING')).strip().upper()}
                    elif mode=='BACKUP':
                        command='wallet.restore';args={'path':await ask('Sökväg till krypterad backup'),'label':await ask('Kontonamn')}
                    else:raise ValueError('WALLET_RESTORE_MODE')
                elif self.model.view==0 and kind in {'recovery','export_recovery'}:
                    command='wallet.recovery' if kind=='recovery' else 'wallet.export_recovery'
                    args={'pubkey':await ask('Walletens offentliga adress',self.model.selection().get('address',''))}
                    if kind=='export_recovery':args['path']=await ask('Sokvag till krypterad frasbackup')
                elif self.model.view==0 and kind=='add':
                    command='wallet.watch';args={'chain_id':await ask('Nätverks-ID'),'address':await ask('Offentlig adress'),'label':await ask('Kontonamn (valfritt)')}
                elif self.model.view==0 and kind=='token':
                    command='wallet.import_token';args={'chain_id':await ask('Nätverks-ID'),'reference':await ask('Tokenreferens / kontrakt')}
                elif self.model.view==0 and kind=='prepare':
                    selected=self.model.selection()
                    if not selected.get('account_id'):raise ValueError('WALLET_SELECT_ASSET_FIRST')
                    command='wallet.prepare';args={'account_id':selected['account_id'],
                        'asset_id':selected.get('asset_id',''),
                        'recipient':await ask('Mottagarens offentliga adress'),'amount':await ask('Belopp')}
                elif self.model.view==2 and kind=='add':
                    accounts=self.model.rows();sender=self.model.selected
                    default_recipient=accounts[(sender+1)%len(accounts)].get('address','') if accounts else ''
                    command='network.prepare';args={'sender':int(await ask('Avsändarkonto (1–4)',str(sender+1)))-1,
                        'recipient':await ask('Mottagarens offentliga konto',default_recipient),'amount':await ask('Belopp','1')}
                elif self.model.view==1 and kind=='add':
                    command='marketplace.register';args={'listing':{'title':await ask('Namn'),'category':await ask('Kategori','ITEM'),
                        'material':await ask('Material','UNKNOWN'),'description':await ask('Beskrivning'),
                        'price_sol':await ask('Paperpris SOL (0 för ingen prissättning)','0')}}
                else:self.model.notice='Använd : och ? för fler funktioner.';return
            except (EOFError,KeyboardInterrupt):command=None;self.model.notice='Avbrutet'
            except (ValueError,KeyError):command=None;self.model.notice='Ogiltiga uppgifter; inget har skickats.'
          # The prompt is gone before a service worker can ask for approval.
          if command is not None:self.submit(command,args)
        finally:
            self._form_active=False
            if not self._closing:self.application.invalidate()

    def _close_private_surfaces(self,_future=None):
        self._closing=True
        # PromptToolkit waits for in_terminal before run_async returns. Close
        # our nested app on the main future's completion, before that wait.
        for app in (self._private_application,
                    self._interactive_prompt.app if self._interactive_prompt is not None else None):
            if app is not None and app.is_running and app.future is not None and not app.future.done():
                if app is self._private_application:app.exit(result=False)
                else:app.exit(exception=EOFError)

    def _started(self):
        self.application.future.add_done_callback(self._close_private_surfaces)
        self.submit('__snapshot__',{})

    async def run_async(self):
        self._loop=asyncio.get_running_loop()
        try:
            await self.application.run_async(pre_run=self._started)
        finally:
            self._close_private_surfaces()
            # Close the owned private surface first; its callback returns only
            # after screen cleanup, before the service releases capture guard.
            if self._form_task is not None:
                self._form_task.cancel()
            if self._task is not None:
                try:await self._task
                except asyncio.CancelledError:pass
            await asyncio.to_thread(self.service.close)


def _foreground_lan_transport(lan):
    """Stable local diagnostics, excluding healthy gossip's changing counters."""
    transport=_object(lan.get('transport'));counts=_object(transport.get('counters'))
    drops=_object(counts.get('admission_drops'));details=_object(lan.get('last_error_details'))
    def enum(value,allowed):return value if isinstance(value,str) and value in allowed else None
    def count(value):return value if type(value) is int and 0<=value<=2**53-1 else None
    stamp=lan.get('last_error_at');code=lan.get('last_error')
    if not (type(stamp) in {int,float} and 0<=stamp<=4102444800):stamp=None
    if not (isinstance(code,str) and re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code)
            and not re.search(r'[0-9a-f]{16,}',code,re.I)):code=None
    return {'scope':'LOCAL_PEER_ONLY',
            'state':enum(transport.get('state'),{'ACTIVE','EXHAUSTED','STOPPED'}),
            'exhausted_reason':enum(transport.get('exhausted_reason'),{'','SESSION','BYTES','FRAMES'}),
            'counters':{'failures':count(counts.get('failures')),
                        'expected_closures':count(counts.get('expected_closures')),
                        'admission_drops':{reason:count(drops.get(reason)) for reason in ('RATE','HANDLERS','SESSION','BYTES')}},
            'last_failure':{'code':code,'at':stamp,'transport':{
                'operation':enum(details.get('operation'),{'PAGE','GET','INCOMING','TOKEN_STATUS','TOKEN_SYNC',
                    'TOKEN_SUBMIT','TOKEN_APPLY','CIRCLE_SIGN','CIRCLE_END','DAG_STRESS_PREPARE',
                    'DAG_STRESS_BEGIN','DAG_STRESS_STOP','DAG_STRESS_STATUS'}),
                'stage':enum(details.get('stage'),{'ACCEPT','CHECK','WAIT','CONNECT','AUTH','SEND','RECEIVE','VALIDATE','EXECUTE'}),
                'error_class':enum(details.get('error_class'),{'TimeoutError','ConnectionResetError','ConnectionRefusedError',
                    'BrokenPipeError','OSError','ValueError','TypeError','JSONDecodeError','Exception'})}}}


def foreground_summary(command, body):
    """Bounded public observations; no wallet refresh, peer or signing input."""
    body=_object(body)
    if command in {'lan.start','lan.join_file'}:
        lan=_object(body.get('lan'));setup=_object(body.get('lan_setup'))
        tokens=_object(body.get('test_tokens'));circle=_object(body.get('token_circle'))
        stress=_object(body.get('dag_stress'))
        stress_summary={key:stress[key] for key in (
            'state','role','elapsed_ms','duration_ms','transactions_per_block','interval_ms',
            'blocks','transactions','all_peers_synced','acknowledged_blocks','acknowledged_transactions',
            'acknowledged_bps','acknowledged_tps','stop_reason','last_error') if key in stress}
        summary={'schema':'gg.terminal.foreground.v1','engine':'DAGOBLIN_PRIVATE_LAN',
                'scope':'PRIVATE_LAN_SESSION_EXPERIMENT','state':lan.get('state'),
                'endpoint':lan.get('endpoint'),'producer_count':body.get('producer_count',0),
                'local_producer_indices':lan.get('local_producer_indices',[]),
                'candidate_peers':setup.get('invite_count',0),'configured_peers':lan.get('configured_peers',0),
                'authenticated_peers':len(lan.get('authenticated_peers',[])),
                'proposals':body.get('blocks_admitted',0),'canonical_finalized':0,
                'validated_dag_transactions':body.get('transactions_validated',0),
                'dag_test_transactions_enabled':stress.get('enabled') is True,
                'dag_stress':stress_summary,
                'test_tokens':tokens,'token_circle':circle,
                'ephemeral_keys':True,'new_pairing_after_restart':True,
                'physical_hosts_verified':False,'transactions_enabled':lan.get('transactions_enabled') is True,
                'financial_transactions_enabled':False,'mainnet_enabled':False}
        if isinstance(lan.get('transport'),dict):summary['local_transport']=_foreground_lan_transport(lan)
        resources=_object(body.get('dag_resources'))
        if resources:
            test=_object(resources.get('test'));plan=_object(resources.get('plan'))
            profile=_object(test.get('profile'))
            summary['local_resources']={'budget':resources.get('budget'),'test_state':test.get('state'),
                'estimated_tps':plan.get('estimated_tps'),'bottlenecks':plan.get('bottlenecks'),
                'relative_percent':{name:_object(row).get('relative_percent') for name,row in _object(plan.get('resources')).items()},
                'network_basis':profile.get('network_basis'),'last_error':test.get('last_error','') or profile.get('network_error','')}
        return summary
    if command=='dag.live_start':
        live=_object(body.get('live'))
        return {'schema':'gg.terminal.foreground.v1','engine':'DAGOBLIN_LOCAL',
                'scope':'LOCAL_RAM_SIGNED_PROPOSALS_NOT_PUBLIC_NETWORK',
                'state':body.get('state'),'producer_count':body.get('producer_count'),
                'proposals':body.get('blocks_admitted'),'validated_transactions':body.get('transactions_validated'),
                'canonical_finalized':body.get('canonical_finalized',0),
                'live_state':live.get('state'),'stop_reason':live.get('stop_reason','')}
    return {'schema':'gg.terminal.foreground.v1','engine':'BFT_LOCAL',
            'scope':'FIXED_LOCAL_VALIDATORS_NOT_PUBLIC_NETWORK',
            'state':body.get('state'),'online':body.get('online'),
            'height':body.get('height'),'state_height':body.get('state_height'),
            'physical_hosts':body.get('physical_hosts',1)}


def foreground_session(service, command, started, *, json_output=False):
    """Keep an explicitly started owned lab or private LAN peer until Ctrl+C.

    One small status poll per second; unchanged summaries are not printed.
    There is no background daemon or automatic session restart.
    main() retains ownership and always closes the service on exit.
    """
    if command not in FOREGROUND_COMMANDS:
        raise ValueError('TERMINAL_FOREGROUND_LOCAL_START_REQUIRED')
    prior=None
    current=started
    while True:
        summary=foreground_summary(command,current)
        encoded=json.dumps(public_value(summary),ensure_ascii=False,allow_nan=False)
        if encoded!=prior:
            if json_output:print(encoded,flush=True)
            else:print('LOCAL · Ctrl+C stoppar den ägda sessionen · '+encoded,flush=True)
            prior=encoded
        time.sleep(1)
        current=service.dispatch({'dag.live_start':'dag.status','lan.start':'lan.status','lan.join_file':'lan.status'}.get(command,'network.status'),{})


def main(argv=None,service_factory=None):
    parser=argparse.ArgumentParser(description='GG Wallet, Marketplace och Nätverk i en riktig terminal.')
    parser.add_argument('--json',action='store_true',help='Skriv publik JSON; avslutar om --foreground saknas.')
    parser.add_argument('--once',action='store_true',help='Skriv aktuell vy en gång utan helskärm.')
    parser.add_argument('--command',help='Kör ett servicekommando; inget skal används.')
    parser.add_argument('--args',default='{}',help='Publika kommandoargument som JSON-objekt; inga lösenord eller nycklar.')
    parser.add_argument('--foreground',action='store_true',help='Behåll uttryckligt dag.live_start, lan.start, lan.join_file eller lokalt network.start tills Ctrl+C; ingen daemon.')
    parser.add_argument('--bootstrap-file',help='Signerad publik LAN-bootstrap för lan.start; inga privata nycklar.')
    parser.add_argument('--bootstrap-out',help='Skapa en ny publik LAN-bootstrapfil vid --foreground lan.start; skriver inte över.')
    parser.add_argument('--invite-out',help='Skapa en ny signerad publik LAN-inbjudan vid --foreground lan.start; skriver inte över.')
    parser.add_argument('--view',choices=('wallet','marketplace','network'),default='wallet')
    parser.add_argument('--width',type=int,default=80)
    parser.add_argument('--height',type=int,default=24)
    args=parser.parse_args(argv)
    service=None
    try:
        foreground_command=None;foreground_arguments=None
        public_files=bool(args.bootstrap_file or args.bootstrap_out or args.invite_out)
        if args.foreground or public_files:
            if not args.command or args.once:
                raise ValueError('TERMINAL_FOREGROUND_LOCAL_START_REQUIRED')
            extra=json.loads(args.args)
            if not isinstance(extra,dict):raise ValueError('TERMINAL_ARGUMENT_OBJECT_REQUIRED')
            foreground_command,foreground_arguments=parse_command(args.command,extra)
            if args.foreground and foreground_command not in FOREGROUND_COMMANDS:
                raise ValueError('TERMINAL_FOREGROUND_LOCAL_START_REQUIRED')
            if public_files and foreground_command!='lan.start':raise ValueError('GG_LAN_BOOTSTRAP_START_REQUIRED')
            if (args.bootstrap_out or args.invite_out) and not args.foreground:raise ValueError('GG_LAN_EXPORT_FOREGROUND_REQUIRED')
            if args.bootstrap_file:
                from backend.lan_dag_runtime import read_public_document
                if 'bootstrap' in foreground_arguments:raise ValueError('TERMINAL_DUPLICATE_ARGUMENT')
                foreground_arguments['bootstrap']=read_public_document(args.bootstrap_file,'bootstrap')
        if service_factory is None:
            from backend.terminal_service import TerminalService
            service_factory=TerminalService
        service=service_factory()
        interactive=not args.json and sys.stdin.isatty() and sys.stdout.isatty()
        def require_terminal():
            if not interactive:raise ValueError('TERMINAL_INTERACTIVE_INPUT_REQUIRED')
        def confirm(summary):
            require_terminal();print(safe_text(summary,4096))
            return input('Godkänn exakt denna åtgärd? Skriv ja: ').strip().casefold() in {'ja','yes'}
        def secret(prompt):
            require_terminal()
            import getpass
            return getpass.getpass(safe_text(prompt,512)+' ')
        # The service's default getpass must never read from redirected stdin.
        service.confirm=confirm;service.secret=secret
        if args.command or args.once or args.json:
            if args.command:
                if args.foreground or public_files:command,arguments=foreground_command,foreground_arguments
                else:
                    extra=json.loads(args.args)
                    if not isinstance(extra,dict):raise ValueError('TERMINAL_ARGUMENT_OBJECT_REQUIRED')
                    command,arguments=parse_command(args.command,extra)
                result=service.dispatch(command,arguments)
                if args.bootstrap_out:service.dispatch('lan.export_bootstrap',{'path':args.bootstrap_out})
                if args.invite_out:service.dispatch('lan.export_invite',{'path':args.invite_out})
            else:result=service.snapshot()
            if args.json:print(json.dumps(public_value(result),ensure_ascii=False,allow_nan=False))
            elif args.command:print(json.dumps(public_value(result),ensure_ascii=False,indent=2,allow_nan=False))
            else:
                model=TerminalModel(state=public_value(result),view=('wallet','marketplace','network').index(args.view),notice='Lokal status · --command help visar kommandon')
                print('\n'.join(model.frame(args.width,args.height)))
            if args.foreground:foreground_session(service,command,result,json_output=args.json)
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():raise ValueError('TERMINAL_TTY_REQUIRED_USE_ONCE_OR_JSON')
        app=TerminalApp(service);service=None
        asyncio.run(app.run_async())
        return 0
    except (KeyboardInterrupt,EOFError):return 130
    except Exception as error:
        code=_error(error)
        if args.json:print(json.dumps({'status':'ERROR','error':code}))
        else:print('GG: '+code,file=sys.stderr)
        return 1
    finally:
        if service is not None:service.close()


if __name__=='__main__':raise SystemExit(main())
