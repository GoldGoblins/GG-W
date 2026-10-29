"""Real disposable idle blocks and native receipt path boundaries.

No user node, wallet, public endpoint, synthetic transaction or app restart.
"""
from pathlib import Path
import hashlib,json,os,tempfile,time,unittest
from unittest.mock import patch


class InstalledBinaryTests(unittest.TestCase):
    def fixture(self,directory):
        from backend import gg_consensus as node
        root=Path(directory);tools=root/'tools';sources=root/'sources';tools.mkdir();sources.mkdir()
        for name in ('go.mod','go.sum','toolchain.json','main.go'):(sources/name).write_text('public fixture '+name,encoding='utf-8')
        entries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources.iterdir(),key=lambda p:p.name)}
        fingerprint=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        name='gg-consensus-node-'+fingerprint[:16]+('.exe' if os.name=='nt' else '')
        binary=tools/name;binary.write_bytes(b'public inert binary fixture')
        record={'schema':'gg.consensus.build.v1','binary':name,'source_sha256':fingerprint,
          'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'cometbft':'v0.40.0'}
        (tools/'build-manifest.json').write_text(json.dumps(record),encoding='utf-8')
        return node,tools,sources,binary,record

    def test_only_receipt_fingerprint_native_basename_inside_tool_root_can_resolve(self):
        with tempfile.TemporaryDirectory(prefix='gg-native-path-') as temporary:
            node,tools,sources,binary,record=self.fixture(temporary)
            self.assertEqual(node._installed_binary(tools),binary)
            for name in ('../'+binary.name,str(binary.resolve()),'other.exe','gg-consensus-node-'+'0'*16+('.exe' if os.name=='nt' else '')):
                wrong=dict(record,binary=name)
                (tools/'build-manifest.json').write_text(json.dumps(wrong),encoding='utf-8')
                self.assertNotEqual(node._installed_binary(tools),binary)
            wrong=dict(record,source_sha256='0'*64)
            (tools/'build-manifest.json').write_text(json.dumps(wrong),encoding='utf-8')
            self.assertNotEqual(node._installed_binary(tools),binary)

    def test_wrong_source_or_binary_bytes_never_pass_strict_validation(self):
        with tempfile.TemporaryDirectory(prefix='gg-native-receipt-') as temporary:
            node,tools,sources,binary,record=self.fixture(temporary)
            with patch.object(node,'TOOLS',tools),patch.object(node,'SOURCES',sources),patch.object(node,'BINARY',binary),patch.object(node,'_binary_stamp',None):
                node._validate_binary()
                self.assertIsNotNone(node._binary_stamp)
                wrong=dict(record,source_sha256='f'*64)
                (tools/'build-manifest.json').write_text(json.dumps(wrong),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'BINARY_PATH|REBUILD_REQUIRED'):node._validate_binary()
                (tools/'build-manifest.json').write_text(json.dumps(record),encoding='utf-8')
                binary.write_bytes(b'changed public inert fixture')
                with self.assertRaisesRegex(ValueError,'BINARY_CHANGED'):node._validate_binary()


class RealIdleCadenceTests(unittest.TestCase):
    def record(self,engine,initial,final,seconds,metrics):
        destination=os.environ.get('GG_BLOCK_CADENCE_EVIDENCE')
        if destination:
            root=Path(destination);root.mkdir(parents=True,exist_ok=True)
            (root/(engine+'.json')).write_text(json.dumps({'status':'PASS','engine':engine,
              'owned_disposable_session':True,'synthetic_transactions':False,'user_nodes_changed':False,
              'initial_height':initial,'final_height':final,'observation_seconds':round(seconds,3),
              'metrics':metrics},indent=2)+'\n',encoding='utf-8')

    def test_hardhat_produces_real_parent_linked_empty_blocks_without_transfers(self):
        from backend import gg_testnet as node
        self.assertTrue(node.available(),'Pinned local Hardhat toolchain required')
        process=None
        try:
            initial=node.start();process=node._process;start=time.monotonic()
            time.sleep(2.2);middle=node.snapshot();time.sleep(2.2);final=node.snapshot()
            self.assertGreaterEqual(final['height'],initial['height']+2)
            self.assertEqual(final['session_transactions'],0);self.assertEqual(final['transactions'],[])
            self.assertEqual(final['block_interval_target_ms'],2000)
            graph=final['block_graph'];self.assertFalse(graph['stale']);self.assertTrue(graph['edges'])
            self.assertTrue(all(block['transaction_count']==0 for block in graph['blocks']))
            self.assertTrue(all(account['native']=='10000' for account in final['accounts']))
            for previous,current in zip(graph['blocks'],graph['blocks'][1:]):
                self.assertEqual(current['parent_hash'],previous['hash'])
            self.assertEqual(graph['metrics']['tps'],0)
            self.assertGreater(graph['metrics']['bps'],0)
            self.record('hardhat',initial['height'],final['height'],time.monotonic()-start,graph['metrics'])
        finally:
            node.stop()
            if process is not None:self.assertIsNotNone(process.poll())

    def test_four_validators_sign_real_empty_blocks_and_keep_balances_unchanged(self):
        from backend import gg_consensus as node
        self.assertTrue(node.available(),'Pinned local consensus toolchain required')
        processes=[]
        try:
            initial=node.start();processes=[row['process'] for row in node._nodes];start=time.monotonic()
            time.sleep(2.3);middle=node.snapshot();time.sleep(2.3);final=node.snapshot()
            self.assertGreaterEqual(final['height'],initial['height']+2)
            self.assertEqual(final['state'],'RUNNING');self.assertEqual(final['session_transactions'],0)
            self.assertEqual(final['transactions'],[]);self.assertEqual(final['block_interval_target_ms'],2000)
            self.assertEqual([(a['address'],a['atomic'],a['nonce']) for a in initial['accounts']],
                             [(a['address'],a['atomic'],a['nonce']) for a in final['accounts']])
            graph=final['block_graph'];self.assertFalse(graph['stale']);self.assertTrue(graph['edges'])
            self.assertTrue(all(block['transaction_count']==0 for block in graph['blocks']))
            self.assertTrue(graph['blocks'][-1]['certificate_verified'])
            self.assertEqual(final['proof']['certificate_height'],final['state_height']+1)
            self.assertEqual(graph['metrics']['tps'],0);self.assertGreater(graph['metrics']['bps'],0)
            self.record('cometbft',initial['height'],final['height'],time.monotonic()-start,graph['metrics'])
        finally:
            node.stop()
            for process in processes:self.assertIsNotNone(process.poll())


if __name__=='__main__':unittest.main()
