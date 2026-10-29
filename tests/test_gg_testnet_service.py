"""Owned loopback devnet lifecycle, exact transfers and irreversible-send guards.

One integration test uses fresh disposable Hardhat accounts. Everything else
is mocked before I/O. No mainnet endpoint, user state or remembered key is used.
"""
from collections import deque
from contextlib import ExitStack
import copy
import hashlib
import json
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import psutil

from backend import gg_testnet as node


class OwnedDevnetIntegrationTests(unittest.TestCase):
    def test_real_owned_session_deployment_exact_transfers_fees_and_shutdown(self):
        self.assertTrue(node.available(),'Install the pinned GG testnet toolchain before this integration check')
        process=None;port=0
        try:
            initial=node.start();process=node._process;port=node._port
            self.assertEqual(initial['state'],'RUNNING')
            self.assertEqual(initial['binding'],'LOOPBACK_ONLY')
            self.assertFalse(initial['production'])
            self.assertEqual(initial['chain_id'],'eip155:31337')
            self.assertEqual(initial['peer_count'],0)
            self.assertEqual(len(initial['accounts']),4)
            self.assertTrue(node._owns_listener())
            listeners=[c for c in psutil.Process(process.pid).net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN]
            self.assertTrue(listeners)
            self.assertTrue(all(c.laddr.ip=='127.0.0.1' for c in listeners))
            self.assertTrue(all(a['native']=='10000' and a['token'] is None for a in initial['accounts']))
            self.assertEqual(node.start()['session'],initial['session'])
            self.assertIs(node._process,process)
            deployed=node.deploy_token()
            self.assertEqual(node._rpc('eth_getCode',[deployed['contract'],'latest']).lower(),node._artifact()['deployedBytecode'].lower())
            self.assertEqual(node._quantity(node._rpc('eth_call',[{'to':deployed['contract'],'data':'0x18160ddd'},'latest'])),node.SUPPLY)
            self.assertEqual(sum(node.amounts.amount_atomic(a['token'],6) for a in deployed['accounts']),node.SUPPLY)
            self.assertEqual(deployed['accounts'][0]['token'],'1000000')
            prepared=node.prepare(0,deployed['accounts'][1]['address'],'1.000001')
            review=prepared['review'];self.assertNotIn('transaction',review)
            self.assertEqual(review['atomic'],'1000001')
            with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(review['id'],'incorrect-fixture-digest')
            sent=node.send(review['id'],review['review_digest'])
            self.assertEqual(sent['accounts'][0]['token'],'999998.999999')
            self.assertEqual(sent['accounts'][1]['token'],'1.000001')
            self.assertEqual(sent['transactions'][0]['state'],'CONFIRMED')
            self.assertGreater(int(sent['transactions'][0]['gas_used']),0)
            with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(review['id'],review['review_digest'])
            back=node.prepare(1,sent['accounts'][0]['address'],'1.000001')['review'];node.send(back['id'],back['review_digest'])
            before=[node._balance(a) for a in node._accounts]
            native=node.prepare(0,node._accounts[1],'0.000000000000000001','NATIVE')['review']
            self.assertEqual(native['atomic'],'1')
            native_sent=node.send(native['id'],native['review_digest'])
            after=[node._balance(a) for a in node._accounts]
            receipt=node._receipt(native_sent['transactions'][0]['txid'])
            actual_fee=node._quantity(receipt['gasUsed'])*node._quantity(receipt['effectiveGasPrice'])
            self.assertEqual(before[0]-after[0],1+actual_fee)
            self.assertEqual(after[1]-before[1],1)
            self.assertGreater(actual_fee,0)
            result=node.self_test()
            self.assertEqual(result['last_test']['state'],'PASS')
            self.assertEqual(len(result['last_test']['checks']),4)
            self.assertTrue(result['last_test']['token_balances_restored'])
            self.assertTrue(result['last_test']['supply_verified'])
            self.assertTrue(all(c['state']=='PASS' for c in result['last_test']['checks']))
            self.assertGreaterEqual(result['height'],8)
            self.assertLessEqual(len(result['transactions']),64)
            self.assertLessEqual(len(result['measurements']),32)
            self.assertLessEqual(len(result['events']),48)
            self.assertNotIn('privateKey',json.dumps(result))
            first_session=result['session'];first_accounts=[a['address'] for a in result['accounts']]
            self.assertEqual(node.stop(),{'state':'STOPPED'})
            self.assertIsNotNone(process.poll())
            self.assertFalse(node._owns_listener())
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
                probe.settimeout(.5);self.assertNotEqual(probe.connect_ex(('127.0.0.1',port)),0)
            stopped=node.snapshot()
            self.assertEqual(stopped['accounts'],[])
            self.assertEqual(stopped['contract'],'')
            self.assertIsNone(stopped['review'])
            restarted=node.start();process=node._process
            self.assertNotEqual(restarted['session'],first_session)
            self.assertTrue(set(first_accounts).isdisjoint(a['address'] for a in restarted['accounts']))
            self.assertEqual(restarted['session_transactions'],0)
            self.assertEqual(restarted['transactions'],[])
            self.assertEqual(restarted['contract'],'')
        finally:
            node.stop()
            if process is not None:self.assertIsNotNone(process.poll())


class TestnetGuardsTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        values={'_process':None,'_process_lease':None,'_closed':False,'_port':39876,'_session':'fixture-session','_genesis':'0x'+'a'*64,
                '_accounts':['0x'+str(i)*40 for i in range(1,5)],'_contract':'0x'+'c'*40,'_review':None,
                '_transactions':deque(maxlen=64),'_measurements':deque(maxlen=32),'_events':deque(maxlen=48),
                '_count':0,'_last_test':None,'_last_error':'','_cached':{},'_request_id':0,
                '_connection':None,'_connection_owner':None,'_rpc_stats':{'requests':0,'members':0,'batches':0}}
        for name,value in values.items():self.stack.enter_context(patch.object(node,name,value))

    def tearDown(self):node._disconnect_rpc();self.stack.close()

    def review(self,**changes):
        review={'id':'review-fixture','session':node._session,'chain_id':node.CHAIN,'sender_index':0,
                'sender':node._accounts[0],'recipient':node._accounts[1],'asset':'NATIVE','symbol':'DEV',
                'amount':'1','atomic':str(10**18),'contract':'','nonce':0,'gas_limit':26200,
                'gas_price_atomic':'1000000000','max_fee':'0.0000262','expires_at':time.time()+120,
                'transaction':{'from':node._accounts[0],'to':node._accounts[1],'value':hex(10**18),
                               'gas':hex(26200),'gasPrice':hex(10**9),'nonce':'0x0','chainId':hex(node.CHAIN_ID)}}
        review.update(changes)
        review['review_digest']=hashlib.sha256(node.amounts.pack(review).encode()).hexdigest()
        node._review=review;return copy.deepcopy(review)

    def send_mocks(self):
        self.stack.enter_context(patch.object(node,'_identity'))
        rpc=self.stack.enter_context(patch.object(node,'_rpc',return_value='0x0'))
        self.stack.enter_context(patch.object(node,'_balance',return_value=10000*10**18))
        broadcast=self.stack.enter_context(patch.object(node,'_broadcast',return_value={'status':'0x1'}))
        self.stack.enter_context(patch.object(node,'snapshot',return_value={}))
        return rpc,broadcast

    def test_review_id_digest_and_single_use(self):
        _,broadcast=self.send_mocks();review=self.review()
        for identifier,digest in [('wrong',review['review_digest']),(review['id'],'wrong')]:
            with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(identifier,digest)
            self.assertIsNotNone(node._review)
        node.send(review['id'],review['review_digest']);broadcast.assert_called_once()
        self.assertIsNone(node._review)
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(review['id'],review['review_digest'])

    def test_review_content_and_nested_transaction_are_bound_to_digest(self):
        _,broadcast=self.send_mocks()
        mutations=[lambda r:r.update(amount='2'),lambda r:r.update(recipient=node._accounts[2]),
                   lambda r:r.update(chain_id='eip155:1'),lambda r:r['transaction'].update(to=node._accounts[2]),
                   lambda r:r['transaction'].update(value='0x2')]
        for mutate in mutations:
            with self.subTest(change=mutations.index(mutate)):
                review=self.review();mutate(node._review)
                with self.assertRaisesRegex(ValueError,'REVIEW|CONTEXT'):node.send(review['id'],review['review_digest'])
                self.assertIsNone(node._review);broadcast.assert_not_called()

    def test_expiry_session_change_and_cancellation_invalidate_review(self):
        _,broadcast=self.send_mocks()
        review=self.review(expires_at=time.time()-1)
        with self.assertRaisesRegex(ValueError,'EXPIRED'):node.send(review['id'],review['review_digest'])
        self.assertIsNone(node._review)
        review=self.review();node._session='another-fixture-session'
        with self.assertRaisesRegex(ValueError,'EXPIRED|SESSION'):node.send(review['id'],review['review_digest'])
        self.assertIsNone(node._review)
        review=self.review();node.cancel_review()
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(review['id'],review['review_digest'])
        broadcast.assert_not_called()

    def test_nonce_and_identity_failure_consume_review_before_send(self):
        rpc,broadcast=self.send_mocks();review=self.review();rpc.return_value='0x1'
        with self.assertRaisesRegex(ValueError,'NONCE_CHANGED'):node.send(review['id'],review['review_digest'])
        self.assertIsNone(node._review);broadcast.assert_not_called()
        review=self.review()
        with patch.object(node,'_identity',side_effect=ValueError('GG_TESTNET_WRONG_CHAIN')):
            with self.assertRaisesRegex(ValueError,'WRONG_CHAIN'):node.send(review['id'],review['review_digest'])
        self.assertIsNone(node._review);broadcast.assert_not_called()

    def test_changed_balances_cannot_use_old_review(self):
        _,broadcast=self.send_mocks();review=self.review()
        with patch.object(node,'_balance',return_value=0):
            with self.assertRaisesRegex(ValueError,'GAS_FUNDS'):node.send(review['id'],review['review_digest'])
        self.assertIsNone(node._review)
        review=self.review(asset='GG-TEST',symbol='GG-TEST',atomic='1000000',contract=node._contract)
        with patch.object(node,'_balance',side_effect=lambda account,token=False:0 if token else 10**22):
            with self.assertRaisesRegex(ValueError,'INSUFFICIENT_FUNDS'):node.send(review['id'],review['review_digest'])
        broadcast.assert_not_called()

    def test_prepare_rejects_foreign_senders_zero_self_and_inexact_amounts(self):
        with patch.object(node,'_identity'),patch.object(node,'_rpc') as rpc:
            contexts=[(True,node._accounts[1],'1','NATIVE'),(4,node._accounts[1],'1','NATIVE'),
                      (node._accounts[0],node._accounts[1],'1','NATIVE'),(0,node._accounts[1],'1','OTHER'),
                      (0,node._accounts[0],'1','NATIVE'),(0,'0x'+'0'*40,'1','NATIVE'),
                      (0,node._accounts[1],'0','NATIVE'),(0,node._accounts[1],1.5,'NATIVE'),
                      (0,node._accounts[1],'1e3','NATIVE'),(0,node._accounts[1],'0.0000001','GG-TEST')]
            for args in contexts:
                with self.subTest(args=args),self.assertRaises(ValueError):node.prepare(*args)
                self.assertIsNone(node._review)
            rpc.assert_not_called()
        with self.assertRaises(TypeError):node.start(endpoint='https://invalid.example')
        with self.assertRaises(TypeError):node.start(private_key='synthetic-not-a-key')
        with self.assertRaises(TypeError):node.prepare(0,node._accounts[1],'1',endpoint='https://invalid.example')

    def test_prepare_balance_gas_and_price_limits_and_external_test_recipient(self):
        def response(method,params=None):
            return {'eth_getTransactionCount':'0x0','eth_estimateGas':hex(21000),'eth_gasPrice':hex(10**9)}[method]
        with patch.object(node,'_identity'),patch.object(node,'snapshot',return_value={}),patch.object(node,'_rpc',side_effect=response):
            with patch.object(node,'_balance',return_value=0),self.assertRaisesRegex(ValueError,'INSUFFICIENT_FUNDS'):
                node.prepare(0,node._accounts[1],'1','NATIVE')
            with patch.object(node,'_balance',return_value=10**22):
                external='0x'+'9'*40;node.prepare(0,external,'1','NATIVE')
                self.assertEqual(node._review['recipient'],external)
                with patch.object(node,'_rpc',side_effect=lambda method,params=None:hex(400000) if method=='eth_estimateGas' else response(method,params)):
                    with self.assertRaisesRegex(ValueError,'GAS_LIMIT'):node.prepare(0,external,'1','NATIVE')
                with patch.object(node,'_rpc',side_effect=lambda method,params=None:hex(10**12+1) if method=='eth_gasPrice' else response(method,params)):
                    with self.assertRaisesRegex(ValueError,'GAS_PRICE_LIMIT'):node.prepare(0,external,'1','NATIVE')
            with patch.object(node,'_balance',return_value=10**18),self.assertRaisesRegex(ValueError,'GAS_FUNDS'):
                node.prepare(0,node._accounts[1],'1','NATIVE')

    def test_launch_environment_excludes_credentials_and_node_injection_options(self):
        captured={}
        def intercept(*args,**kwargs):
            captured.update(kwargs['env'])
            raise RuntimeError('fixture-stops-before-process-launch')
        fake_socket=MagicMock()
        fake_socket.__enter__.return_value.getsockname.return_value=('127.0.0.1',43210)
        fixture_environment={'PATH':'fixture-path','SYSTEMROOT':'fixture-system','TEMP':'fixture-temp',
                             'OPENAI_API_KEY':'synthetic-secret','AWS_ACCESS_KEY_ID':'synthetic-secret',
                             'AUTHORIZATION':'synthetic-secret','COOKIE':'synthetic-secret','DATABASE_URL':'synthetic-secret',
                             'NODE_OPTIONS':'--require synthetic-injected-module','GG_TESTNET_ACCOUNTS':'synthetic-remembered-key'}
        try:
            with patch.dict(node.os.environ,fixture_environment,clear=True),patch.object(node,'available',return_value=True),\
                    patch.object(node.shutil,'copyfile'),patch.object(node.shutil,'which',return_value='node'),\
                    patch.object(node.socket,'socket',return_value=fake_socket),patch.object(node.subprocess,'Popen',side_effect=intercept):
                with self.assertRaisesRegex(RuntimeError,'before-process-launch'):node.start()
            self.assertEqual(set(captured),{'PATH','SYSTEMROOT','TEMP','GG_TESTNET_ACCOUNTS',
                                            'HARDHAT_DISABLE_TELEMETRY_PROMPT','HARDHAT_TELEMETRY_DISABLED'})
            generated=json.loads(captured['GG_TESTNET_ACCOUNTS'])
            self.assertEqual(len(generated),4)
            self.assertTrue(all(set(account)=={'privateKey','balance'} for account in generated))
            self.assertTrue(all(account['balance']==str(10000*10**18) for account in generated))
            self.assertNotEqual(captured['GG_TESTNET_ACCOUNTS'],fixture_environment['GG_TESTNET_ACCOUNTS'])
            self.assertEqual(node._port,0)
            self.assertIsNone(node._process)
        finally:
            captured.clear()

    def test_omni_actions_never_forward_endpoints_keys_or_arbitrary_rpc(self):
        from backend import omni_service
        extra={'endpoint':'https://invalid.example','chain_id':'eip155:1',
               'privateKey':'synthetic-not-a-key','method':'eth_sendRawTransaction','transaction':{'to':'untrusted'}}
        with patch.object(omni_service.store,'event'),patch.object(node,'start',return_value={}) as start,\
                patch.object(node,'prepare',return_value={}) as prepare,patch.object(node,'send',return_value={}) as send,\
                patch.object(node,'_rpc') as rpc:
            for name,args in [('testnet_start',extra),
                              ('testnet_prepare',dict(extra,sender=0,recipient=node._accounts[1],amount='1',asset='NATIVE')),
                              ('testnet_send',dict(extra,id='fixture-id',review_digest='fixture-digest'))]:
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'ACTION_ARGUMENTS'):
                    omni_service.action(name,json.dumps(args))
            start.assert_not_called();prepare.assert_not_called();send.assert_not_called()
            self.assertEqual(omni_service.action('testnet_start','{}'),{'status':'COMPLETE'})
            start.assert_called_once_with()
            args={'sender':0,'recipient':node._accounts[1],'amount':'1','asset':'NATIVE'}
            omni_service.action('testnet_prepare',json.dumps(args))
            prepare.assert_called_once_with(0,node._accounts[1],'1','NATIVE')
            omni_service.action('testnet_send',json.dumps({'id':'fixture-id','review_digest':'fixture-digest'}))
            send.assert_called_once_with('fixture-id','fixture-digest')
            for name in ('testnet_rpc','testnet_register_network','testnet_import_key','testnet_eth_sendRawTransaction'):
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'ACTION_ARGUMENTS'):
                    omni_service.action(name,json.dumps(extra))
            with self.assertRaisesRegex(ValueError,'REQUEST_OBJECT'):omni_service.action('testnet_start','[]')
            rpc.assert_not_called()

    def test_ambiguous_broadcast_is_recorded_once_and_never_retried(self):
        transaction={'from':node._accounts[0],'to':node._accounts[1],'value':'0x1'}
        description={'kind':'TRANSFER','amount':'1','symbol':'DEV'}
        with patch.object(node,'_rpc',side_effect=TimeoutError('synthetic timeout')) as rpc:
            with self.assertRaises(TimeoutError):node._broadcast(transaction,description)
            self.assertEqual(rpc.call_count,1)
            self.assertEqual(node._count,1)
            self.assertEqual(node._transactions[0]['state'],'BROADCAST_UNKNOWN')
            with self.assertRaisesRegex(ValueError,'UNRESOLVED_TRANSACTION'):node._broadcast(transaction,description)
            self.assertEqual(rpc.call_count,1)
            self.assertEqual(node._count,1)
            self.assertEqual(node._measurements[-1]['state'],'BROADCAST_UNKNOWN')

    def test_transaction_limit_and_pending_lock_prevent_rpc(self):
        with patch.object(node,'_rpc') as rpc:
            node._count=node.MAX_TRANSACTIONS
            with self.assertRaisesRegex(ValueError,'TRANSACTION_LIMIT'):node._broadcast({}, {'kind':'TRANSFER'})
            node._count=0;node._transactions.append({'state':'PENDING'})
            with self.assertRaisesRegex(ValueError,'UNRESOLVED_TRANSACTION'):node._broadcast({}, {'kind':'TRANSFER'})
            rpc.assert_not_called()

    def test_rpc_is_loopback_bounded_allowlisted_and_sanitizes_errors(self):
        class Connection:
            response_kind='success'
            def __init__(self):self.payload={};self.closed=False;self.limit=None
            def request(self,method,path,body,headers):self.payload=json.loads(body)
            def getresponse(self):return SimpleNamespace(status=200,read=self.read)
            def read(self,limit):
                self.limit=limit
                if self.response_kind=='large':return b'x'*(1024*1024+1)
                if self.response_kind=='wrong-id':return json.dumps({'jsonrpc':'2.0','id':-1,'result':'0x1'}).encode()
                if self.response_kind=='error':return json.dumps({'jsonrpc':'2.0','id':self.payload['id'],'error':{'message':'do-not-echo-fixture'}}).encode()
                return json.dumps({'jsonrpc':'2.0','id':self.payload['id'],'result':hex(node.CHAIN_ID)}).encode()
            def close(self):self.closed=True
        connection=Connection()
        with patch.object(node,'_alive',return_value=True),patch.object(node.http.client,'HTTPConnection',return_value=connection) as constructor:
            self.assertEqual(node._rpc('eth_chainId'),hex(node.CHAIN_ID))
            constructor.assert_called_with('127.0.0.1',node._port,timeout=3)
            self.assertEqual(connection.limit,1024*1024+1)
            self.assertFalse(connection.closed,'A successful read retains its session-owned connection')
            self.assertEqual(node._rpc('eth_chainId'),hex(node.CHAIN_ID))
            self.assertEqual(constructor.call_count,1)
            for kind in ('large','wrong-id','error'):
                connection.response_kind=kind
                with self.subTest(kind=kind),self.assertRaises(ValueError) as error:node._rpc('eth_chainId')
                self.assertNotIn('do-not-echo-fixture',str(error.exception))
            for method in ('hardhat_reset','hardhat_setBalance','evm_mine','personal_importRawKey','https://invalid.example'):
                with self.subTest(method=method),self.assertRaisesRegex(ValueError,'METHOD|CAPABILITY|RPC'):node._rpc(method,[])
            with self.assertRaisesRegex(ValueError,'REQUEST_LIMIT'):node._rpc('eth_call',['x'*65536])

    def test_identity_rejects_wrong_owner_chain_accounts_genesis_and_bytecode(self):
        def rpc(method,params=None):
            return {'eth_chainId':hex(node.CHAIN_ID),'eth_getBlockByNumber':{'hash':node._genesis},
                    'eth_accounts':node._accounts,'eth_getCode':'0x6000'}[method]
        with patch.object(node,'_owns_listener',return_value=False),patch.object(node,'_rpc') as call:
            with self.assertRaisesRegex(ValueError,'LISTENER_NOT_OWNED'):node._identity()
            call.assert_not_called()
        with patch.object(node,'_owns_listener',return_value=True),patch.object(node,'_artifact',return_value={'deployedBytecode':'0x6000'}):
            for method,replacement,code in [('eth_chainId','0x1','WRONG_CHAIN'),('eth_accounts',list(reversed(node._accounts)),'SESSION_CHANGED'),
                                             ('eth_getBlockByNumber',{'hash':'0x'+'b'*64},'SESSION_CHANGED'),('eth_getCode','0x6001','CONTRACT_CHANGED')]:
                with self.subTest(method=method),patch.object(node,'_rpc_batch',side_effect=lambda calls,replacement=replacement,method=method:[replacement if m==method else rpc(m,p) for m,p in calls]):
                    with self.assertRaisesRegex(ValueError,code):node._identity()
            with patch.object(node,'_rpc_batch',side_effect=lambda calls:[rpc(m,p) for m,p in calls]):node._identity()

    def test_listener_pid_and_shutdown_are_owned_and_bounded(self):
        process=MagicMock();process.pid=87654;process.poll.return_value=None
        connection=SimpleNamespace(status=psutil.CONN_LISTEN,laddr=SimpleNamespace(ip='127.0.0.1',port=node._port))
        with patch.object(node,'_process',process),patch.object(node.psutil,'Process') as lookup:
            lookup.return_value.net_connections.return_value=[connection]
            self.assertTrue(node._owns_listener());lookup.assert_called_with(process.pid)
            connection.laddr.ip='0.0.0.0';self.assertFalse(node._owns_listener())
            process.wait.side_effect=[subprocess.TimeoutExpired('fixture',5),None]
            self.review();self.assertEqual(node.stop(),{'state':'STOPPED'})
            process.terminate.assert_called_once();process.kill.assert_called_once()
            self.assertEqual(process.wait.call_args_list[0].kwargs,{'timeout':5})
            self.assertEqual(process.wait.call_args_list[1].kwargs,{'timeout':3})
            self.assertIsNone(node._process);self.assertEqual(node._port,0);self.assertIsNone(node._review)

    def test_terminal_shutdown_blocks_already_dequeued_start_and_rpc(self):
        dequeued=threading.Event();resume=threading.Event();finished=threading.Event();outcomes=[]
        def queued_start():
            dequeued.set()
            try:
                if not resume.wait(2):
                    outcomes.append('FIXTURE_RESUME_TIMEOUT');return
                node.start()
                outcomes.append('UNEXPECTED_START')
            except Exception as error:
                outcomes.append(str(error))
            finally:
                finished.set()
        with patch.object(node.subprocess,'Popen') as launch,patch.object(node.http.client,'HTTPConnection') as connection:
            worker=threading.Thread(target=queued_start,name='test-queued-devnet-start',daemon=True)
            worker.start()
            try:
                self.assertTrue(dequeued.wait(1),'The worker must take the task before shutdown')
                self.assertEqual(node.shutdown(),{'state':'STOPPED'})
                self.assertTrue(node._closed)
                resume.set()
                self.assertTrue(finished.wait(2))
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcomes,['GG_TESTNET_SHUTTING_DOWN'])
                with self.assertRaisesRegex(ValueError,'SHUTTING_DOWN'):node._rpc('eth_chainId')
                # Normal stop is reversible during use, but cannot reopen the
                # terminal app-exit fence for work already held by a worker.
                node.stop()
                with self.assertRaisesRegex(ValueError,'SHUTTING_DOWN'):node.start()
                launch.assert_not_called();connection.assert_not_called()
                self.assertIsNone(node._process);self.assertEqual(node._port,0)
            finally:
                resume.set();worker.join(timeout=2)
        # setUp's patch restores _closed even if an assertion fails.

    def test_read_failure_clears_review_and_marks_last_known_balances_stale(self):
        self.review()
        cached=[{'index':0,'address':node._accounts[0],'native':'9999.9','token':'1000000','nonce':1}]
        node._cached={'accounts':cached,'height':7,'contract':node._contract,'gas_used':'21000','gas_limit':'30000000','base_fee_atomic':'1000000000'}
        with patch.object(node,'available',return_value=True),patch.object(node,'_alive',return_value=True),\
                patch.object(node,'_identity',side_effect=ValueError('GG_TESTNET_SESSION_CHANGED')):
            failed=node.snapshot()
        self.assertEqual(failed['state'],'READ_FAILED')
        self.assertEqual(failed['error'],'GG_TESTNET_READ_FAILED')
        self.assertEqual(failed['accounts'],cached)
        self.assertEqual(failed['height'],7)
        self.assertIsNone(failed['review']);self.assertIsNone(node._review)
        self.assertEqual(failed['measurements'][-1]['state'],'FAIL')

    def test_receipt_is_bound_to_transaction_and_canonical_block(self):
        txid='0x'+'1'*64;block_hash='0x'+'2'*64
        receipt={'transactionHash':txid,'blockHash':block_hash,'blockNumber':'0x1','status':'0x1','gasUsed':'0x5208'}
        block={'hash':block_hash,'transactions':[txid]}
        with patch.object(node,'_rpc',side_effect=[receipt,block]):self.assertEqual(node._receipt(txid),receipt)
        for changed_receipt,changed_block,code in [(dict(receipt,transactionHash='0x'+'3'*64),block,'RECEIPT_IDENTITY'),
                                                   (receipt,dict(block,hash='0x'+'4'*64),'RECEIPT_BLOCK'),
                                                   (receipt,dict(block,transactions=[]),'RECEIPT_BLOCK')]:
            with self.subTest(code=code),patch.object(node,'_rpc',side_effect=[changed_receipt,changed_block]):
                with self.assertRaisesRegex(ValueError,code):node._receipt(txid)
        with patch.object(node,'_rpc') as rpc:
            with self.assertRaisesRegex(ValueError,'TX_ID'):node._receipt('not-a-transaction')
            rpc.assert_not_called()


if __name__=='__main__':unittest.main()
