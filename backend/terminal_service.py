"""Headless GG operations shared with desktop backends; no Qt dependency.

Only this service's explicitly started disposable cluster is cleaned up. Public
watch reads and marketplace cataloguing are finite user commands. Real wallet
effects use the existing exact-operation approval and transfer state machine.
"""
from __future__ import annotations
from contextlib import nullcontext
from copy import deepcopy
import getpass
import importlib.util
import json
import os
import threading
import time
import uuid

from backend import omni_assets as assets,omni_rpc,omni_wallet
from backend import lan_dag_runtime

COMMANDS={
    'status':{},'help':{},'activity':{},
    'wallet.status':{},'wallet.watch':{'chain_id','address','label'},
    'wallet.refresh':{'account_id'},'wallet.receive':{'account_id'},
    'wallet.import_token':{'chain_id','reference'},'wallet.create':{'label','method','count','purpose'},
    'wallet.restore_phrase':{'label','method','purpose'},'wallet.recovery':{'pubkey'},
    'wallet.export_recovery':{'pubkey','path'},
    'wallet.backup':{'pubkey','path'},'wallet.restore':{'path','label'},
    'wallet.prepare':{'account_id','asset_id','recipient','amount'},
    'wallet.send':{'id','review_digest'},'wallet.check':{'id'},'wallet.cancel':{'id'},
    'network.status':{},'network.readiness':{'profile'},'network.start':{},'network.stop':{},'network.selftest':{},
    'network.benchmark':{'count'},'network.test':{},'network.measure':{'count'},'network.stop_node':{'index'},'network.restart_node':{'index'},
    'network.prepare':{'sender','recipient','amount'},'network.send':{'id','review_digest'},
    'network.cancel':{},'network.export':{'account'},
    'dag.status':{},'dag.start':{},'dag.wave':{'blocks','transactions_per_block'},'dag.stop':{},
    'dag.live_start':{'blocks','transactions_per_block','interval_ms','producer_count'},'dag.live_stop':{},
    'dag.test':{'blocks','transactions_per_block'},
    'marketplace.status':{},'marketplace.register':{'listing'},'marketplace.select':{'id'},
    'marketplace.filter':{'category'},'marketplace.public':{'operation'},
    'marketplace.delist':{'id'},'marketplace.paper_buy':{'id'},'marketplace.proof':{'id'},
}
COMMANDS.update(lan_dag_runtime.COMMANDS)


class TerminalService:
    def __init__(self,*,confirm=None,secret=None,show_words=None):
        self.confirm=confirm
        self.secret=secret or getpass.getpass
        # A separate, private terminal surface is mandatory for mnemonic words.
        # There is deliberately no print/getpass/JSON fallback.
        self.show_words=show_words
        self._lock=threading.RLock()
        self._owns_network=False
        self._owns_dag=False
        self._dag_engine=None
        self._lan_runtime=None
        self._closed=False
        self._portable=os.name!='nt'
        assets.bootstrap()

    def _network(self):
        from backend import gg_consensus
        return gg_consensus

    def _dag(self):
        # A terminal owns a separate RAM experiment, never the desktop/global
        # engine or another terminal's session. No keys are made until start.
        if self._dag_engine is None:
            from backend.gg_parallel_dag import ParallelDag
            self._dag_engine=ParallelDag()
        return self._dag_engine

    def _lan(self):
        # Each terminal owns its peer. Status/construction makes no keys or IO.
        if self._lan_runtime is None:self._lan_runtime=lan_dag_runtime.LanDagRuntime()
        return self._lan_runtime

    def _wallet(self):
        # The optional single-process desktop lab must not import a Rust SDK in
        # the minimal terminal edition. Native GG accounts are added below.
        state=assets.snapshot()
        result=omni_wallet.snapshot(state,{'state':'NOT_CREATED'})
        result['positions']=result['rows']
        network=self._network().snapshot()
        for account in network.get('accounts',[]):
            result['accounts'].append({'id':'gg-test-'+str(account['index']),'chain_id':network['chain_id'],
                'address':account['address'],'label':'Testkonto '+str(account['index']+1),'provider':'LOCAL_TEST'})
            result['positions'].append({'id':'gg-test-'+str(account['index']),'account_id':'gg-test-'+str(account['index']),
                'asset_id':network['chain_id']+'/native:GG-NET-TEST',
                'symbol':'GG-NET-TEST','network':'GG · lokalt testnät','chain_id':network['chain_id'],
                'address':account['address'],'quantity':account['quantity'],'atomic':account['atomic'],
                'value_usd':None,'label':'Testkonto '+str(account['index']+1),
                'balance_state':'CERTIFIED_TEST_STATE','scope':'LOCAL_TEST','signer_state':'SESSION_RAM'})
        extra=len(network.get('accounts',[]))
        for key in ('position_count','unpriced_count','account_count'):
            result['summary'][key]+=extra
        if extra:result['summary']['network_count']+=1
        result['signing_sdk_available']=importlib.util.find_spec('solders') is not None
        result['wallet_creation']='BIP39_PAPER_OR_ENCRYPTED_AI'
        from backend import solana_transfers
        result['transfers']=solana_transfers.list_snapshot()
        return result

    def snapshot(self):
        with self._lock:
            if self._closed:raise ValueError('TERMINAL_CLOSED')
            from backend import marketplace_contract,marketplace_discovery
            market=marketplace_contract.status_payload()
            market['public_catalog']=marketplace_discovery.snapshot()
            from backend import network_profiles
            return {'schema':'gg.terminal.status.v1','wallet':self._wallet(),'marketplace':market,
                    'consensus':self._network().snapshot(),'parallel_dag':self._dag().snapshot(),'activity':assets.events(),
                    'network_readiness':network_profiles.snapshot(),'lan_dag':self._lan().snapshot(),
                    'commands':list(COMMANDS),'platform':os.name}

    def _password(self,prompt,*,repeat=False):
        value=self.secret(prompt)
        if not isinstance(value,str) or not 12<=len(value)<=256:raise ValueError('WALLET_PASSWORD_LENGTH')
        if repeat and value!=self.secret('Upprepa lösenordet: '):raise ValueError('WALLET_PASSWORD_MISMATCH')
        return value

    def _wallet_effect(self,name,args):
        if importlib.util.find_spec('solders') is None:raise ValueError('TERMINAL_WALLET_SIGNING_SDK_REQUIRED')
        from backend import terminal_approval,wallet_vault,portable_wallet_vault,solana_transfers
        operation={'wallet.backup':'backup_wallet','wallet.restore':'restore_wallet','wallet.send':'send_transfer'}[name]
        values=dict(args)
        password=None
        if name in {'wallet.backup','wallet.restore'}:
            values['password']=self._password('Backupens lösenord: ',repeat=name=='wallet.backup')
        if self._portable:
            password=self._password('Walletens lösenord: ',repeat=name=='wallet.restore')
        def callback():
            if name=='wallet.backup':return wallet_vault.export_backup(values['pubkey'],values['path'],values['password'])
            if name=='wallet.restore':return wallet_vault.restore_backup(values['path'],values['password'],values.get('label',''))
            return solana_transfers.send(values['id'],values['review_digest'])
        try:
            with portable_wallet_vault.session(password) if password is not None else nullcontext():
                return terminal_approval.execute(operation,values,callback,self.confirm)
        finally:
            # Python does not guarantee wiping immutable strings; do not retain
            # a password in this service, a command history, logs or state.
            values.clear();password=None

    def _mnemonic_input_ready(self):
        if not callable(self.show_words) or not callable(self.secret) or not callable(self.confirm):
            raise ValueError('TERMINAL_PRIVATE_WORDS_UI_REQUIRED')

    def _show_private_words(self,words):
        from backend import sensitive_ui_guard
        if (not isinstance(words,list) or len(words) not in (12,24) or
                any(not isinstance(word,str) or not word.isascii() or not word.isalpha() or len(word)>16 for word in words)):
            raise ValueError('TERMINAL_PRIVATE_WORDS_INVALID')
        owner='terminal-mnemonic:'+uuid.uuid4().hex
        try:
            sensitive_ui_guard.enter(owner)
            if self.show_words(words) is not True:raise ValueError('TERMINAL_SECRET_CANCELLED')
        finally:
            # The callback must clear its private screen before it returns.
            words.clear()
            sensitive_ui_guard.leave(owner)

    def _mnemonic_create(self,args,*,restore=False):
        self._mnemonic_input_ready()
        method=args.get('method','PAPER');count=args.get('count',24);purpose=args.get('purpose','TRADING')
        if method not in {'PAPER','AI'} or type(count) is not int or count not in (12,24) or purpose not in {'TRADING','STORAGE'}:
            raise ValueError('WALLET_MNEMONIC_OPTIONS')
        if method=='AI' and importlib.util.find_spec('solders') is None:
            raise ValueError('TERMINAL_WALLET_SIGNING_SDK_REQUIRED')
        if method=='PAPER' and self.confirm('PAPER: Skriv orden privat pa papper. GG sparar ingen signerarnyckel eller aterstallningsfras. Fortsatt endast om du kan forvara orden sakert.') is not True:
            raise ValueError('TERMINAL_APPROVAL_REJECTED')
        from backend import wallet_mnemonic as mnemonic,terminal_approval,wallet_vault
        identifier='';private={};answers={};phrase=None;password=None
        try:
            if restore:
                phrase=self.secret('Aterstallningsfras (dold):')
                private=mnemonic.begin_restore(phrase,args.get('label',''),purpose,method)
                phrase=None
            else:
                private=mnemonic.begin(args.get('label',''),purpose,count,method)
            identifier=private['session_id']
            if not restore:
                words=private.pop('words')
                try:self._show_private_words(words)
                finally:words.clear()
                challenge=mnemonic.challenge(identifier)
                try:
                    for index in challenge['indices']:answers[str(index)]=self.secret('Ord #'+str(index)+' (dolt):')
                    mnemonic.verify(identifier,answers)
                finally:answers.clear()
            if method=='AI':
                password=self._password('Krypterat valv och aterstallning, losenord:',repeat=True)
                mnemonic.set_password(identifier,password);password=None
            values={'label':args.get('label',''),'mnemonic_session':identifier}
            return terminal_approval.execute('create_wallet',values,
                lambda:wallet_vault.create(values['label'],identifier),self.confirm)
        finally:
            if identifier:mnemonic.cancel(identifier)
            private.clear();answers.clear();phrase=None;password=None

    def _mnemonic_recovery(self,args):
        self._mnemonic_input_ready()
        from backend import wallet_mnemonic as mnemonic,terminal_approval
        values={'pubkey':args['pubkey'],'password':self._password('Aterstallningens losenord:')}
        def callback():
            private={}
            try:
                private=mnemonic.reveal(values['pubkey'],values['password'])
                self._show_private_words(private.pop('words'))
                # Secret results never return through the service/model/JSON.
                return None
            finally:
                words=private.pop('words',None)
                if isinstance(words,list):words.clear()
                private.clear()
        try:
            terminal_approval.execute('reveal_mnemonic',values,callback,self.confirm)
            return {'state':'DISPLAYED','pubkey':args['pubkey']}
        finally:values.clear()

    def _mnemonic_export(self,args):
        from backend import wallet_mnemonic,terminal_approval
        terminal_approval.execute('export_mnemonic',args,
            lambda:wallet_mnemonic.export(args['pubkey'],args['path']),self.confirm)
        return {'state':'EXPORTED','pubkey':args['pubkey'],'path':args['path']}

    def _refresh(self,account_id=None):
        state=assets.snapshot()
        accounts=state['accounts']
        if account_id is not None:
            accounts=[a for a in accounts if a['id']==account_id]
            if not accounts:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
        if len(accounts)>32:raise ValueError('OMNI_WALLET_REFRESH_LIMIT')
        positions=[(a,t) for a in accounts for t in state['assets'] if a['chain_id']==t['chain_id']]
        if len(positions)>64:raise ValueError('OMNI_WALLET_REFRESH_LIMIT')
        failures=0
        for account,asset in positions:
            try:
                observation=omni_rpc.balance(asset['id'],account['id'])
                observation['observed_at']=time.time()
                with assets.db(True) as db:
                    db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account['id'],assets.pack(observation)))
            except Exception:
                failures+=1
                with assets.db(True) as db:
                    prior=db.execute('SELECT body FROM observations WHERE asset_id=? AND account_id=?',(asset['id'],account['id'])).fetchone()
                    observation=json.loads(prior[0]) if prior else {'asset_id':asset['id'],'account_id':account['id'],'atomic':None,'quantity':'—'}
                    observation['state']='READ_FAILED'
                    db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account['id'],assets.pack(observation)))
        from backend import omni_discovery
        for account in accounts:
            if assets.network(account['chain_id'])['family']=='solana':
                try:omni_discovery.discover(account['id'])
                except Exception:failures+=1
        # The explicit public refresh also prices the selected wallet's native
        # assets and real positive positions, including newly discovered mints.
        # Status/startup never enters this path; no catalogue or chain sweep.
        quote_assets={asset['id'] for _,asset in positions if asset['namespace']=='native'}
        selected=[account['id'] for account in accounts]
        if selected:
            with assets.db() as db:
                rows=db.execute('SELECT o.asset_id,o.body FROM observations o JOIN assets a ON a.id=o.asset_id '
                    'WHERE o.account_id IN ('+','.join('?' for _ in selected)+')',selected)
                for row in rows:
                    atomic=json.loads(row['body']).get('atomic')
                    if isinstance(atomic,str) and 1<=len(atomic)<=78 and atomic.isascii() and atomic.isdigit() and int(atomic)>0:
                        quote_assets.add(row['asset_id'])
                    if len(quote_assets)>64:break
        price_state='NOT_REQUESTED'
        if quote_assets:
            try:
                if len(quote_assets)>64:raise ValueError('OMNI_WALLET_REFRESH_LIMIT')
                from backend import crypto_explorer
                crypto_explorer.refresh_wallet_quotes(sorted(quote_assets))
                price_state='COMPLETE'
            except Exception:
                failures+=1;price_state='PARTIAL'
                assets.event('wallet','QUOTES_UNAVAILABLE','','Priser kunde inte uppdateras; tidigare observationer bevaras')
        assets.event('wallet','TERMINAL_REFRESH','','Läste '+str(len(positions))+' saldon · '+str(failures)+' läsfel')
        return {'state':'PARTIAL' if failures else 'COMPLETE','positions':len(positions),'failures':failures,'price_state':price_state}

    def dispatch(self,command,args=None):
        with self._lock:
            if self._closed:raise ValueError('TERMINAL_CLOSED')
            if args is None:args={}
            if (command not in COMMANDS or not isinstance(args,dict)
                or set(args)-set(COMMANDS[command])):raise ValueError('TERMINAL_COMMAND_ARGUMENTS')
            args=dict(args)
            if len(assets.pack(args))>(lan_dag_runtime.MAX_PUBLIC_DOCUMENT+2048 if command=='lan.install' else 16384):raise ValueError('TERMINAL_COMMAND_SIZE')
            if command=='help':return {'commands':{name:sorted(keys) for name,keys in COMMANDS.items()}}
            if command=='status':return self.snapshot()
            if command=='activity':return {'activity':assets.events()}
            if command.startswith('lan.'):
                if command in {'lan.start','lan.join_file'} and self._dag_engine is not None and self._dag_engine.snapshot().get('state')!='STOPPED':
                    raise ValueError('GG_LAN_STOP_LOCAL_DAG_FIRST')
                return self._lan().dispatch(command,args)
            if command=='network.readiness':
                from backend import network_profiles
                return network_profiles.snapshot(args.get('profile'))
            if command=='wallet.status':return self._wallet()
            if command=='wallet.send' and self._owns_network:
                draft=self._network().snapshot().get('review')
                if draft and draft.get('id')==args.get('id'):
                    return self._network().send(args['id'],args['review_digest'])
            if command in {'wallet.create','wallet.restore_phrase'}:return self._mnemonic_create(args,restore=command=='wallet.restore_phrase')
            if command=='wallet.recovery':return self._mnemonic_recovery(args)
            if command=='wallet.export_recovery':return self._mnemonic_export(args)
            if command in {'wallet.backup','wallet.restore','wallet.send'}:return self._wallet_effect(command,args)
            if command=='wallet.watch':return {'account_id':assets.account(args['chain_id'],args['address'],args.get('label',''))}
            if command=='wallet.refresh':return self._refresh(args.get('account_id'))
            if command=='wallet.receive':
                if str(args['account_id']).startswith('gg-test-'):
                    account=next((a for a in self._network().snapshot()['accounts'] if 'gg-test-'+str(a['index'])==args['account_id']),None)
                    if not account:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
                    return {'chain_id':self._network().snapshot()['chain_id'],'address':account['address'],'scope':'LOCAL_TEST'}
                account=next((a for a in assets.snapshot()['accounts'] if a['id']==args['account_id']),None)
                if not account:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
                return {'chain_id':account['chain_id'],'address':account['address'],'label':account['label']}
            if command=='wallet.import_token':return omni_rpc.import_token(args['chain_id'],args['reference'])
            if command.startswith('wallet.'):
                if command=='wallet.prepare' and str(args.get('account_id','')).startswith('gg-test-'):
                    if not self._owns_network:raise ValueError('TERMINAL_OWNED_NETWORK_REQUIRED')
                    if args.get('asset_id')!=self._network().snapshot()['chain_id']+'/native:GG-NET-TEST':
                        raise ValueError('OMNI_ACCOUNT_NETWORK_MISMATCH')
                    address=str(args['account_id'])[len('gg-test-'):]
                    if address not in {'0','1','2','3'}:raise ValueError('OMNI_ACCOUNT_NOT_FOUND')
                    return self._network().prepare(int(address),args['recipient'],args['amount'])
                from backend import solana_transfers
                if command=='wallet.prepare':return solana_transfers.prepare(args['account_id'],args['asset_id'],args['recipient'],args['amount'])
                if command=='wallet.check':return solana_transfers.check(args['id'])
                if command=='wallet.cancel':return solana_transfers.cancel(args['id'])
            if command.startswith('dag.'):
                if command in {'dag.start','dag.live_start','dag.test','dag.wave'} and self._lan_runtime is not None and self._lan_runtime.active:
                    raise ValueError('GG_LAN_STOP_LAN_FIRST')
                dag=self._dag()
                if command=='dag.status':return dag.snapshot()
                if command=='dag.live_start':
                    if dag.snapshot().get('state')!='STOPPED' and not self._owns_dag:raise ValueError('TERMINAL_DAG_ALREADY_OWNED')
                    self._owns_dag=True
                    return dag.start_async_live(args.get('blocks',8),args.get('transactions_per_block',0),
                        args.get('interval_ms',125),producer_count=args.get('producer_count',8))
                if command in {'dag.start','dag.test'}:
                    if dag.snapshot().get('state')!='STOPPED' and not self._owns_dag:raise ValueError('TERMINAL_DAG_ALREADY_OWNED')
                    if command=='dag.test' and self._owns_dag:raise ValueError('TERMINAL_DAG_ALREADY_OWNED')
                    self._owns_dag=True
                    try:
                        started=dag.start()
                        if command=='dag.start':return started
                        for _ in range(2):dag.build_wave(args.get('blocks',24),args.get('transactions_per_block',8))
                        return {'status':'COMPLETE','report':dag.snapshot(),'stopped_after_test':True}
                    finally:
                        if command=='dag.test':dag.stop();self._owns_dag=False
                if not self._owns_dag:raise ValueError('TERMINAL_OWNED_DAG_REQUIRED')
                if command=='dag.live_stop':return dag.stop_live()
                if command=='dag.stop':
                    result=dag.stop();self._owns_dag=False;return result
                return dag.build_wave(args.get('blocks',24),args.get('transactions_per_block',8))
            if command.startswith('network.'):
                node=self._network()
                if command in {'network.test','network.measure'}:
                    if node._genesis is not None:raise ValueError('TERMINAL_NETWORK_ALREADY_OWNED')
                    self._owns_network=True
                    try:
                        node.start()
                        tested=node.self_test() if command=='network.test' else node.benchmark(args.get('count',32))
                        return {'status':'PASS','report':tested['last_test'] if command=='network.test' else tested['benchmark'],
                                'scope':'LOCAL_FIXED_VALIDATORS','physical_hosts':1,'validators':4,'stopped_after_test':True}
                    finally:
                        node.stop();self._owns_network=False
                if command=='network.start':
                    if node._genesis is not None and not self._owns_network:raise ValueError('TERMINAL_NETWORK_ALREADY_OWNED')
                    self._owns_network=True
                    return node.start()
                if command=='network.status':return node.snapshot()
                if not self._owns_network:raise ValueError('TERMINAL_OWNED_NETWORK_REQUIRED')
                if command=='network.stop':
                    result=node.stop();self._owns_network=False;return result
                if command=='network.selftest':return node.self_test()
                if command=='network.benchmark':return node.benchmark(args.get('count',32))
                if command=='network.stop_node':return node.stop_node(args['index'])
                if command=='network.restart_node':return node.restart_node(args['index'])
                if command=='network.prepare':return node.prepare(args['sender'],args['recipient'],args['amount'])
                if command=='network.send':return node.send(args['id'],args['review_digest'])
                if command=='network.cancel':return node.cancel_review()
                if command=='network.export':return node.export_proof(args.get('account',0))
            if command.startswith('marketplace.'):
                from backend import marketplace_contract as market,marketplace_discovery
                if command=='marketplace.status':return market.status_payload()
                if command=='marketplace.register':return market.list_item(args['listing'])
                if command=='marketplace.select':return market.select_listing(args['id'])
                if command=='marketplace.filter':return market.set_filter(args['category'])
                if command=='marketplace.public':
                    operation=args['operation']
                    if not isinstance(operation,dict) or operation.get('action') not in {'refresh','select','stop_previews'}:
                        raise ValueError('TERMINAL_MARKETPLACE_PUBLIC_ACTION')
                    marketplace_discovery.action(assets.pack(operation));return marketplace_discovery.snapshot()
                if command=='marketplace.delist':return market.delist_item(args['id'])
                if command=='marketplace.paper_buy':return market.paper_buy(args['id'])
                if command=='marketplace.proof':
                    rows=market.load_catalog();return market.listing_proof(rows,args['id'])
            raise ValueError('TERMINAL_COMMAND_UNKNOWN')

    def close(self):
        # Signal the owned sockets/workers before waiting for an ordinary
        # command holding the service lane. Cleanup then joins in this lane.
        if self._lan_runtime is not None:self._lan_runtime.request_stop()
        with self._lock:
            if self._closed:return
            self._closed=True
            if self._lan_runtime is not None:self._lan_runtime.stop()
            if self._owns_dag:
                self._dag().stop();self._owns_dag=False
            if self._owns_network:
                self._network().stop()
                self._owns_network=False
