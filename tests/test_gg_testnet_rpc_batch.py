"""Correlated bounded reads, session-owned transport and canonical snapshots."""
from contextlib import ExitStack
from collections import deque
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import gg_testnet as node


class FakeConnection:
    def __init__(self,reply=None,failure=None):
        self.reply=reply;self.failure=failure;self.requests=[];self.closed=False;self.read_limit=None

    def request(self,method,path,body,headers):
        self.requests.append(json.loads(body))
        if self.failure:raise self.failure

    def getresponse(self):return SimpleNamespace(status=200,read=self.read)

    def read(self,limit):
        self.read_limit=limit
        payload=self.requests[-1]
        if self.reply:return self.reply(payload)
        if isinstance(payload,list):
            return json.dumps([{'jsonrpc':'2.0','id':request['id'],'result':request['method']} for request in reversed(payload)]).encode()
        return json.dumps({'jsonrpc':'2.0','id':payload['id'],'result':payload['method']}).encode()

    def close(self):self.closed=True


class RpcBatchTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        for name,value in {'_closed':False,'_port':39876,'_session':'batch-fixture','_process':None,
                           '_connection':None,'_connection_owner':None,'_request_id':0,
                           '_rpc_stats':{'requests':0,'members':0,'batches':0},'_measurements':deque(maxlen=32),
                           '_accounts':['0x'+str(i)*40 for i in range(1,5)],'_contract':'0x'+'c'*40,
                           '_cached':{},'_review':None,'_transactions':deque(maxlen=64)}.items():
            self.stack.enter_context(patch.object(node,name,value))
        self.stack.enter_context(patch.object(node,'_alive',return_value=True))

    def tearDown(self):
        node._disconnect_rpc();self.stack.close()

    def test_out_of_order_results_are_bound_to_ids_and_keepalive_is_session_scoped(self):
        connection=FakeConnection()
        with patch.object(node.http.client,'HTTPConnection',return_value=connection) as create:
            result=node._rpc_batch([('eth_chainId',[]),('eth_accounts',[]),('eth_gasPrice',[])])
            self.assertEqual(result,['eth_chainId','eth_accounts','eth_gasPrice'])
            self.assertEqual(node._rpc('eth_chainId'),'eth_chainId')
            self.assertEqual(create.call_count,1)
            create.assert_called_with('127.0.0.1',39876,timeout=3)
            self.assertFalse(connection.closed)
            self.assertEqual(connection.read_limit,1024*1024+1)
            self.assertEqual(node._rpc_stats,{'requests':2,'members':4,'batches':1})
            self.assertEqual([r['id'] for r in connection.requests[0]],[1,2,3])
            self.assertEqual(connection.requests[1]['id'],4)

    def test_incomplete_duplicate_foreign_and_noninteger_ids_fail_whole_batch(self):
        def good(requests):return [{'jsonrpc':'2.0','id':r['id'],'result':'0x0'} for r in requests]
        mutations=[lambda r:r[:1],lambda r:r+[r[0]],lambda r:[r[0],dict(r[1],id=r[0]['id'])],
                   lambda r:[r[0],dict(r[1],id=999999)],lambda r:[dict(r[0],id=True),r[1]],
                   lambda r:[dict(r[0],id=float(r[0]['id'])),r[1]],
                   lambda r:[dict(r[0],id=str(r[0]['id'])),r[1]],lambda r:None,
                   lambda r:r[0],lambda r:[r[0],None]]
        for mutate in mutations:
            node._disconnect_rpc()
            connection=FakeConnection(reply=lambda requests,mutate=mutate:json.dumps(mutate(good(requests))).encode())
            with self.subTest(mutation=mutations.index(mutate)),patch.object(node.http.client,'HTTPConnection',return_value=connection) as create:
                with self.assertRaisesRegex(ValueError,'BATCH|RPC_RESPONSE'):
                    node._rpc_batch([('eth_chainId',[]),('eth_accounts',[])])
                self.assertTrue(connection.closed);self.assertIsNone(node._connection)
                self.assertEqual(create.call_count,1)
                self.assertEqual(len(connection.requests),1,'Malformed reads are not automatically retried')

    def test_single_rpc_also_rejects_boolean_float_and_string_ids(self):
        for identifier in (True,1.0,'1'):
            connection=FakeConnection(reply=lambda request,identifier=identifier:json.dumps({'jsonrpc':'2.0','id':identifier,'result':'0x1'}).encode())
            node._request_id=0
            with self.subTest(identifier=identifier),patch.object(node.http.client,'HTTPConnection',return_value=connection):
                with self.assertRaisesRegex(ValueError,'RPC_RESPONSE'):node._rpc('eth_chainId')
                self.assertTrue(connection.closed)

    def test_rejected_and_malformed_members_never_publish_partial_results(self):
        def reply(requests,kind):
            values=[{'jsonrpc':'2.0','id':r['id'],'result':'0x1'} for r in requests]
            if kind=='error':values[1]={'jsonrpc':'2.0','id':requests[1]['id'],'error':{'message':'private-fixture-do-not-report'}}
            elif kind=='version':values[1]['jsonrpc']='1.0'
            elif kind=='missing-result':values[1].pop('result')
            elif kind=='extra-field':values[1]['params']=['private-fixture-do-not-report']
            elif kind=='large':return b'x'*(1024*1024+1)
            elif kind=='nan':return b'[{"jsonrpc":"2.0","id":1,"result":NaN},{"jsonrpc":"2.0","id":2,"result":"0x0"}]'
            elif kind=='duplicate-json-key':return b'[{"jsonrpc":"2.0","id":1,"id":1,"result":"0x0"},{"jsonrpc":"2.0","id":2,"result":"0x0"}]'
            return json.dumps(values).encode()
        for kind in ('error','version','missing-result','extra-field','large','nan','duplicate-json-key'):
            node._request_id=0
            connection=FakeConnection(reply=lambda requests,kind=kind:reply(requests,kind))
            with self.subTest(kind=kind),patch.object(node.http.client,'HTTPConnection',return_value=connection):
                with self.assertRaises(ValueError) as error:node._rpc_batch([('eth_chainId',[]),('eth_accounts',[])])
                self.assertNotIn('private-fixture-do-not-report',str(error.exception))
                self.assertTrue(connection.closed);self.assertIsNone(node._connection)

    def test_write_batches_empty_oversized_invalid_params_and_large_requests_never_connect(self):
        invalid=[[],[('eth_chainId',[])]*33,[('eth_sendTransaction',[{}])],
                 [('personal_importRawKey',[])],[('eth_chainId',{})],[('eth_chainId',[],123)],
                 [('eth_call',['x'*65536])],True,'eth_chainId']
        with patch.object(node.http.client,'HTTPConnection') as create:
            for calls in invalid:
                with self.subTest(calls=str(calls)[:60]),self.assertRaises(ValueError):node._rpc_batch(calls)
            create.assert_not_called()
            self.assertEqual(node._rpc_stats,{'requests':0,'members':0,'batches':0})

    def test_transport_failure_never_resends_a_write_and_discards_the_connection(self):
        connection=FakeConnection(failure=TimeoutError('synthetic fixture timeout'))
        with patch.object(node.http.client,'HTTPConnection',return_value=connection) as create:
            with self.assertRaises(TimeoutError):node._rpc('eth_sendTransaction',[{'from':node._accounts[0]}])
            self.assertEqual(len(connection.requests),1);self.assertEqual(create.call_count,1)
            self.assertTrue(connection.closed);self.assertIsNone(node._connection)
            self.assertEqual(node._rpc_stats,{'requests':1,'members':1,'batches':0})

    def test_new_session_and_port_do_not_reuse_old_connections(self):
        connections=[FakeConnection(),FakeConnection(),FakeConnection()]
        with patch.object(node.http.client,'HTTPConnection',side_effect=connections) as create:
            node._rpc('eth_chainId');node._session='different-session';node._rpc('eth_chainId')
            self.assertTrue(connections[0].closed)
            node._port=39877;node._rpc('eth_chainId')
            self.assertTrue(connections[1].closed);self.assertFalse(connections[2].closed)
            self.assertEqual(create.call_count,3)

    def test_operation_counters_measure_actual_requests_and_members(self):
        connection=FakeConnection()
        with patch.object(node.http.client,'HTTPConnection',return_value=connection):
            began=node._probe_start()
            node._rpc_batch([('eth_chainId',[]),('eth_accounts',[]),('eth_gasPrice',[])])
            node._rpc('eth_getBlockByNumber',['0x0',False]);node._measurement('rpc',began,'PASS')
        sample=node._measurements[-1]
        self.assertEqual((sample['rpc_requests'],sample['rpc_members'],sample['rpc_batches']),(2,4,1))
        self.assertGreaterEqual(sample['elapsed_ms'],0)

    def test_account_reads_pin_all_values_to_one_block_and_recheck_canonical_hash(self):
        tip={'number':'0x5','hash':'0x'+'d'*64}
        values=[]
        for index in range(4):values.extend([hex(10**22+index),hex(index),hex(1000000+index)])
        values.append('0x6000')
        with patch.object(node,'_rpc_batch',return_value=values) as batch,\
                patch.object(node,'_rpc',return_value=tip) as rpc,\
                patch.object(node,'_artifact',return_value={'deployedBytecode':'0x6000'}):
            rows=node._account_snapshots(tip)
            self.assertEqual(len(rows),4)
            self.assertEqual(rows[1]['native'],'10000.000000000000000001')
            self.assertEqual(rows[1]['token'],'1.000001')
            self.assertEqual(rows[1]['nonce'],1)
            calls=batch.call_args.args[0]
            self.assertEqual(len(calls),13)
            self.assertTrue(all(params[-1]=='0x5' for method,params in calls))
            rpc.assert_called_once_with('eth_getBlockByNumber',['0x5',False])
            rpc.return_value=dict(tip,hash='0x'+'e'*64)
            with self.assertRaisesRegex(ValueError,'CHECKPOINT_CHANGED'):node._account_snapshots(tip)
            rpc.return_value=tip;values[-1]='0x6001'
            with self.assertRaisesRegex(ValueError,'CONTRACT_CHANGED'):node._account_snapshots(tip)

    def test_snapshot_failure_never_labels_mixed_checkpoint_balances_current(self):
        cached=[{'index':0,'address':node._accounts[0],'native':'10000','token':'1','nonce':0}]
        node._cached={'accounts':cached,'height':4,'contract':node._contract}
        node._review={'id':'public-fixture-review'}
        with patch.object(node,'available',return_value=True),\
                patch.object(node,'_identity',return_value={'number':'0x5','hash':'0x'+'a'*64}),\
                patch.object(node,'_account_snapshots',side_effect=ValueError('GG_TESTNET_CHECKPOINT_CHANGED')):
            snapshot=node.snapshot()
        self.assertEqual(snapshot['state'],'READ_FAILED')
        self.assertEqual(snapshot['accounts'],cached)
        self.assertEqual(snapshot['height'],4)
        self.assertIsNone(snapshot['review']);self.assertIsNone(node._review)

    def test_newly_resolved_receipt_refreshes_snapshot_anchor_before_balances(self):
        first={'number':'0x5','hash':'0x'+'a'*64,'gasUsed':'0x0','gasLimit':'0x1','timestamp':'0x1'}
        second=dict(first,number='0x6',hash='0x'+'b'*64)
        record={'state':'PENDING','txid':'0x'+'c'*64}
        node._transactions.append(record)
        with patch.object(node,'available',return_value=True),\
                patch.object(node,'_identity',side_effect=[first,second]) as identity,\
                patch.object(node,'_receipt',return_value={'status':'0x1','blockNumber':'0x6','gasUsed':'0x5208'}),\
                patch.object(node,'_account_snapshots',return_value=[]) as accounts:
            result=node.snapshot()
        self.assertEqual(result['state'],'RUNNING');self.assertEqual(result['height'],6)
        self.assertEqual(record['state'],'CONFIRMED');self.assertEqual(record['block'],6)
        self.assertEqual(identity.call_count,2)
        accounts.assert_called_once_with(second)


if __name__=='__main__':unittest.main()
