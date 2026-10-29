"""Finite user-driven operations for the shared CRYPTO / MP / wallet hub."""
import json
import time
from backend import omni_assets as store,omni_lab,omni_rpc
_web_sample=None
_consensus_sample=None


def snapshot():
    result=store.snapshot(); result['lab']=omni_lab.snapshot()
    from backend import network_profiles
    result['network_readiness']=network_profiles.snapshot()
    from backend import omni_bots
    result['bots']=omni_bots.snapshot(result['selected_asset'])
    result['mode']='PUBLIC_READ_AND_LOCAL_LAB'
    result['web_sample']=_web_sample
    from backend import marketplace_protocols
    result['marketplace']=marketplace_protocols.snapshot()
    from backend import omni_web
    result['web_node']=omni_web.snapshot()
    from backend import gg_testnet
    result['testnet']=gg_testnet.snapshot()
    from backend import gg_consensus,gg_consensus_web
    result['consensus']=gg_consensus.snapshot()
    result['consensus_web']=gg_consensus_web.snapshot()
    from backend import gg_parallel_dag,lan_dag_runtime
    result['lan_dag']=lan_dag_runtime.snapshot()
    result['parallel_dag']=result['lan_dag'] if lan_dag_runtime.active_manager() is not None else gg_parallel_dag.snapshot()
    result['consensus_sample']=_consensus_sample if _consensus_sample and _consensus_sample['genesis']['chain_id']==result['consensus']['chain_id'] else None
    from backend import omni_wallet
    result['wallet_overview']=omni_wallet.snapshot(result,result['lab'])
    from backend import solana_transfers
    result['wallet_transfer']=solana_transfers.snapshot(store.preference('selected_transfer') or '')
    result['wallet_transfers']=solana_transfers.list_snapshot()
    return result


def action(name,raw='{}'):
    import re
    try:
        return _action(name,raw,refresh_price=name=='refresh_balance')
    except Exception as exc:
        code=str(exc)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}',code): code=type(exc).__name__
        store.event('operations','FAILED','',store.text(name,40)+' · '+code)
        raise


def _action(name,raw='{}',*,refresh_price=False):
    global _web_sample,_consensus_sample
    if len(raw)>(256*1024+2048 if name=='lan_install' else 16384): raise ValueError('OMNI_REQUEST_SIZE')
    args=json.loads(raw or '{}')
    if not isinstance(args,dict): raise ValueError('OMNI_REQUEST_OBJECT')
    if name in {'reveal_mnemonic','export_mnemonic'}:raise ValueError('OMNI_PRIVATE_WALLET_OPERATION_REQUIRED')
    if name.startswith('lan_'):
        from backend import lan_dag_runtime,gg_parallel_dag
        if name=='lan_start' and gg_parallel_dag.snapshot().get('state')!='STOPPED':raise ValueError('GG_LAN_STOP_LOCAL_DAG_FIRST')
        lan_dag_runtime.action(name,args)
    elif name=='select_asset':
        store.asset(args['id']); store.preference('selected_asset',args['id'])
    elif name=='watch': store.account(args['chain_id'],args['address'],args.get('label',''))
    elif name=='connect_watch':
        account_id=store.account(args['chain_id'],args['address'],args.get('label',''))
        from backend import omni_wallet
        if store.network(args['chain_id'])['family']=='solana':
            from backend import omni_discovery
            omni_discovery.discover(account_id)
        candidates=[a for a in store.snapshot()['assets'] if a['chain_id']==args['chain_id']]
        if len(candidates)<=24:omni_wallet.refresh_account(account_id)
        else:
            native=next(a for a in candidates if a['namespace']=='native')
            _action('refresh_balance',store.pack({'asset_id':native['id'],'account_id':account_id}))
            store.event('wallet','ACCOUNT_PARTIAL','', 'Läste native-saldo; välj en token för fler saldon')
    elif name=='remove_watch':
        from backend import wallet_vault
        if any(k['account_id']==args['id'] for k in wallet_vault.status()):raise ValueError('WALLET_OWNED_ACCOUNT_KEEP_BACKUP')
        with store.db(True) as db:
            db.execute('DELETE FROM observations WHERE account_id=?',(args['id'],))
            db.execute('DELETE FROM accounts WHERE id=?',(args['id'],))
            from backend import omni_discovery
            omni_discovery._table(db);db.execute('DELETE FROM wallet_discovery WHERE account_id=?',(args['id'],))
        store.event('wallet','DISCONNECTED','','Bevakningskonto borttaget')
    elif name=='import_token': omni_rpc.import_token(args['chain_id'],args['reference'])
    elif name=='refresh_account':
        from backend import omni_wallet
        omni_wallet.refresh_account(args['account_id'])
    elif name=='refresh_wallet':
        from backend import omni_wallet
        omni_wallet.refresh_wallet(args.get('account_ids'))
    elif name=='discover_assets':
        from backend import omni_discovery
        omni_discovery.discover(args['account_id'])
    elif name=='create_wallet':
        from backend import wallet_vault
        wallet_vault.create(args.get('label',''),args.get('mnemonic_session',''))
    elif name=='backup_wallet':
        from backend import wallet_vault
        wallet_vault.export_backup(args['pubkey'],args['path'],args['password'])
    elif name=='restore_wallet':
        from backend import wallet_vault
        wallet_vault.restore_backup(args['path'],args['password'],args.get('label',''))
    elif name=='prepare_transfer':
        from backend import solana_transfers
        solana_transfers.prepare(args['account_id'],args['asset_id'],args['recipient'],args['amount'])
    elif name=='select_transfer':
        from backend import solana_transfers
        if not solana_transfers.snapshot(args['id']):raise ValueError('WALLET_TRANSFER_NOT_FOUND')
        store.preference('selected_transfer',args['id'])
    elif name=='send_transfer':
        from backend import solana_transfers
        solana_transfers.send(args['id'],args['review_digest'])
    elif name=='check_transfer':
        from backend import solana_transfers
        solana_transfers.check(args['id'])
    elif name=='cancel_transfer':
        from backend import solana_transfers
        solana_transfers.cancel(args['id'])
    elif name=='register_network': store.register_network(args)
    elif name=='refresh_balance':
        asset=store.asset(args['asset_id']); account=args['account_id']
        try:
            result=omni_rpc.balance(asset['id'],account); result['observed_at']=time.time()
            with store.db(True) as db: db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account,store.pack(result)))
            store.event('wallet','BALANCE_READ',asset['id'],result['quantity']+' '+asset['symbol']+' · '+result['identity_level'])
        except Exception:
            # Keep the last value but mark it stale. A failed read is never zero.
            with store.db(True) as db:
                row=db.execute('SELECT body FROM observations WHERE asset_id=? AND account_id=?',(asset['id'],account)).fetchone()
                result=json.loads(row[0]) if row else {'asset_id':asset['id'],'account_id':account,'atomic':None,'quantity':'—'}
                result['state']='READ_FAILED'
                db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account,store.pack(result)))
            raise
        # The explicit token-detail refresh needs the same bounded price path
        # as the overview. A quote failure must never invalidate a good balance.
        if refresh_price:
            try:
                from backend.crypto_explorer import refresh_wallet_quotes
                refresh_wallet_quotes([asset['id']])
            except Exception:
                pass  # Quote status/as-of remains separate from the balance read.
    elif name.startswith('dag_'):
        from backend import gg_parallel_dag,lan_dag_runtime
        keys={'dag_start':set(),'dag_wave':{'blocks','transactions_per_block'},'dag_stop':set(),
              'dag_live_start':{'blocks','transactions_per_block','interval_ms'},'dag_live_stop':set()}
        if name not in keys or set(args)-keys[name]:raise ValueError('GG_DAG_ACTION_ARGUMENTS')
        if name in {'dag_start','dag_live_start','dag_wave'} and lan_dag_runtime.active_manager() is not None:raise ValueError('GG_LAN_STOP_LAN_FIRST')
        if name=='dag_start':gg_parallel_dag.start()
        elif name=='dag_stop':
            if lan_dag_runtime.active_manager() is not None:lan_dag_runtime.stop()
            else:gg_parallel_dag.stop()
        elif name=='dag_live_start':gg_parallel_dag.start_live(args.get('blocks',8),args.get('transactions_per_block',0),args.get('interval_ms',125))
        elif name=='dag_live_stop':gg_parallel_dag.stop_live()
        else:gg_parallel_dag.build_wave(args.get('blocks',24),args.get('transactions_per_block',8))
    elif name.startswith('consensus_'):
        from backend import gg_consensus,gg_consensus_web
        keys={'consensus_start':set(),'consensus_stop':set(),
              'consensus_stop_node':{'index'},'consensus_restart_node':{'index'},
              'consensus_prepare':{'sender','recipient','amount'},
              'consensus_send':{'id','review_digest'},'consensus_cancel':set(),
              'consensus_self_test':set(),'consensus_benchmark':{'count'},
              'consensus_export_proof':{'account'},'consensus_start_web':set(),'consensus_stop_web':set()}
        if name not in keys or set(args)-keys[name]:raise ValueError('GG_CONSENSUS_ACTION_ARGUMENTS')
        if name=='consensus_start':
            gg_consensus_web.stop();_consensus_sample=None;gg_consensus.start()
        elif name=='consensus_stop':
            gg_consensus_web.stop();_consensus_sample=None;gg_consensus.stop()
        elif name=='consensus_stop_node':gg_consensus.stop_node(args['index'])
        elif name=='consensus_restart_node':gg_consensus.restart_node(args['index'])
        elif name=='consensus_prepare':gg_consensus.prepare(args['sender'],args['recipient'],args['amount'])
        elif name=='consensus_send':gg_consensus.send(args['id'],args['review_digest'])
        elif name=='consensus_cancel':gg_consensus.cancel_review()
        elif name=='consensus_self_test':gg_consensus.self_test()
        elif name=='consensus_benchmark':gg_consensus.benchmark(args.get('count',32))
        elif name=='consensus_export_proof':_consensus_sample=gg_consensus.export_proof(args.get('account',0))
        elif name=='consensus_start_web':gg_consensus_web.start(trust=gg_consensus.trust_context())
        elif name=='consensus_stop_web':gg_consensus_web.stop()
    elif name.startswith('testnet_'):
        from backend import gg_testnet
        keys = {'testnet_start':set(),'testnet_stop':set(),'testnet_deploy':set(),
                'testnet_prepare':{'sender','recipient','amount','asset'},
                'testnet_send':{'id','review_digest'},'testnet_cancel':set(),'testnet_self_test':set()}
        if name not in keys or set(args)-keys[name]: raise ValueError('GG_TESTNET_ACTION_ARGUMENTS')
        if name=='testnet_start': gg_testnet.start()
        elif name=='testnet_stop': gg_testnet.stop()
        elif name=='testnet_deploy': gg_testnet.deploy_token()
        elif name=='testnet_prepare': gg_testnet.prepare(args['sender'],args['recipient'],args['amount'],args.get('asset','GG-TEST'))
        elif name=='testnet_send': gg_testnet.send(args['id'],args['review_digest'])
        elif name=='testnet_cancel': gg_testnet.cancel_review()
        elif name=='testnet_self_test': gg_testnet.self_test()
        else: raise ValueError('OMNI_OPERATION_UNKNOWN')
    elif name=='create_lab': omni_lab.create(); _web_sample=None
    elif name=='prepare_web_sample':
        envelope=omni_lab.prepare()
        _web_sample={'checkpoint':{'chain_id':envelope['body']['chain_id'],'account_root':envelope['body']['account_root']},'envelope':envelope}
        store.event('node','PUBLIC_SAMPLE_READY','','Offentligt labbpaket för lokal webbverifiering förberett')
    elif name in {'mp_module','mp_inspect_nft'}:
        from backend import marketplace_protocols as protocols
        if name=='mp_module': protocols.toggle(args['id'],args['enabled'])
        else: protocols.inspect(args['chain_id'],args['standard'],args['collection'],args['token_id'],args.get('holder',''))
    elif name in {'start_web_node','stop_web_node'}:
        from backend import omni_web
        result=omni_web.start() if name=='start_web_node' else omni_web.stop()
        store.event('node',result['state'],'','Lokal webbvy · endast loopback · statisk verifierare')
    elif name=='configure_lab': omni_lab.configure(args)
    elif name=='lab_send': omni_lab.submit(omni_lab.prepare(args.get('sender',0),args.get('recipient',1),args.get('amount','1')))
    elif name=='lab_commit': omni_lab.commit()
    elif name=='transport_test': omni_lab.transport_test(args.get('loss',False))
    elif name=='retry_transport': omni_lab.retry_transport()
    elif name=='cancel_transport': omni_lab.cancel_transport()
    elif name in {'bind_market','bot_enabled','bot_reset','bot_step'}:
        from backend import omni_bots
        if name=='bind_market': omni_bots.bind(args['asset_id'],args['pair'])
        elif name=='bot_enabled': omni_bots.enabled(args['asset_id'],args['book'],args['enabled'])
        elif name=='bot_reset': omni_bots.reset(args['asset_id'],args['book'])
        else: omni_bots.step(args['asset_id'])
    elif name=='verify_lab':
        result=omni_lab.verify(); store.event('lab',result['state'],'','Historik kontrollerad · '+str(result['blocks'])+' block')
    else: raise ValueError('OMNI_OPERATION_UNKNOWN')
    return {'status':'COMPLETE'}
