"""Actual parent topology, bounded history, truthful clocks and owned fixtures."""
from copy import deepcopy
import hashlib
import time
import unittest
from unittest.mock import patch

from backend.gg_block_graph import BlockHistory, LIMIT, LIVE_HISTORY_LIMIT, FETCH_LIMIT, comet_block, evm_block


def identifier(height):
    return hashlib.sha256(('public-block-'+str(height)).encode()).hexdigest()


def row(height,tx_count=1):
    return {'hash':identifier(height),'parent_hash':identifier(height-1) if height else '',
            'height':height,'timestamp':1700000000+height,'transaction_count':tx_count,
            'state':'OBSERVED','certificate_verified':False,'proposer':''}


class PublicHistoryTests(unittest.TestCase):
    def test_live_tail_keeps_more_real_blocks_with_same_incremental_fetch_budget(self):
        history=BlockHistory('live fixture',history_limit=LIVE_HISTORY_LIMIT)
        history.reset('owned-live-session')
        observed={}
        # Every additional point must first exist in an actual decoded reply.
        # Backfill remains at most eight headers per call, even for this tail.
        for _ in range(LIVE_HISTORY_LIMIT//FETCH_LIMIT):
            wanted=history.wanted(240)
            self.assertLessEqual(len(wanted),FETCH_LIMIT)
            values=[row(height) for height in wanted]
            observed.update((value['hash'],deepcopy(value)) for value in values)
            history.ingest(values,240,identifier(240))
        graph=history.snapshot()
        self.assertEqual(LIVE_HISTORY_LIMIT,128)
        self.assertEqual(len(graph['blocks']),128)
        self.assertGreater(len(graph['blocks']),48)
        self.assertEqual(graph['history_limit'],128)
        self.assertEqual(history.wanted(240),[])
        self.assertEqual(graph['blocks'],[observed[identifier(height)] for height in range(113,241)])
        self.assertEqual(len(graph['edges']),127)
        by_hash={value['hash']:value for value in graph['blocks']}
        for link in graph['edges']:
            child=by_hash[link['to']];parent=by_hash[link['from']]
            self.assertEqual(child['parent_hash'],parent['hash'])
            self.assertEqual(child['height'],parent['height']+1)
        for height in range(241,601):
            history.ingest([row(height)],height,identifier(height))
        final=history.snapshot()
        self.assertEqual(len(history.rows),128)
        self.assertEqual(len(final['blocks']),128)
        self.assertEqual(final['blocks'][0]['height'],473)
        self.assertEqual(final['blocks'][-1]['height'],600)
        self.assertEqual(len(final['edges']),127)
        history.reset('different-session')
        self.assertEqual(history.snapshot()['blocks'],[])

    def test_live_tail_does_not_fill_an_unknown_hole_with_points_or_an_edge(self):
        history=BlockHistory('live fixture',history_limit=LIVE_HISTORY_LIMIT)
        history.ingest([row(height) for height in range(113,121)],120,identifier(120))
        history.ingest([row(124),row(123)],124,identifier(124))
        graph=history.snapshot()
        self.assertEqual([value['height'] for value in graph['blocks']],[123,124])
        self.assertTrue(graph['partial_history'])
        self.assertEqual(graph['edges'],[{'from':identifier(123),'to':identifier(124)}])
        # A matching, actually fetched parent may extend the displayed tail.
        history.ingest([row(122),row(121)],124,identifier(124))
        graph=history.snapshot()
        self.assertEqual([value['height'] for value in graph['blocks']],list(range(113,125)))
        self.assertEqual(len(graph['edges']),11)

    def test_bounded_incremental_catchup_only_publishes_adjacent_actual_edges(self):
        history=BlockHistory('fixture');history.reset('one')
        for _ in range(6):
            wanted=history.wanted(99)
            self.assertLessEqual(len(wanted),FETCH_LIMIT)
            history.ingest([row(h) for h in wanted],99,identifier(99))
            graph=history.snapshot()
            self.assertLessEqual(len(graph['blocks']),LIMIT)
            self.assertEqual(len(graph['edges']),len(graph['blocks'])-1)
            hashes={r['hash']:r for r in graph['blocks']}
            for edge in graph['edges']:
                self.assertEqual(hashes[edge['to']]['parent_hash'],edge['from'])
                self.assertEqual(hashes[edge['to']]['height'],hashes[edge['from']]['height']+1)
        self.assertEqual(len(graph['blocks']),48)
        self.assertEqual(graph['blocks'][0]['height'],52)
        self.assertFalse(graph['partial_history']);self.assertEqual(history.wanted(99),[])
        history.ingest([row(100)],100,identifier(100))
        self.assertEqual(len(history.rows),48);self.assertEqual(len(history.snapshot()['blocks']),48)
        history.reset('two');self.assertEqual(history.snapshot()['blocks'],[])

    def test_missing_parent_stays_partial_and_invalid_adjacent_parent_is_atomic(self):
        history=BlockHistory('fixture')
        history.ingest([row(5),row(3)],5,identifier(5))
        graph=history.snapshot();self.assertEqual([r['height'] for r in graph['blocks']],[5])
        self.assertTrue(graph['partial_history']);self.assertEqual(graph['edges'],[])
        before=deepcopy(history.rows)
        wrong=row(4);wrong['hash']=identifier(50)
        with self.assertRaisesRegex(ValueError,'PARENT_MISMATCH'):
            history.ingest([wrong],5,identifier(5))
        self.assertEqual(history.rows,before)
        history.ingest([row(4)],5,identifier(5))
        self.assertEqual(len(history.snapshot()['edges']),2)
        with self.assertRaisesRegex(ValueError,'CHECKPOINT_CHANGED'):
            history.ingest([dict(row(4),hash=identifier(40))],5,identifier(5))

    def test_observation_rate_never_counts_backfill_or_uses_synthetic_header_clock(self):
        tick=[100.0];history=BlockHistory('fixture',clock=lambda:tick[0])
        history.ingest([row(h,3) for h in range(5,13)],12,identifier(12))
        initial=history.snapshot()['metrics']
        self.assertIsNone(initial['bps']);self.assertIsNone(initial['tps'])
        self.assertEqual(initial['header_bps'],1)
        tick[0]+=2
        history.ingest([row(13,5),row(14,7)],14,identifier(14))
        observed=history.snapshot()['metrics']
        self.assertEqual(observed['bps'],1)
        self.assertEqual(observed['tps'],6)
        self.assertEqual(observed['observed_transactions'],12)
        tick[0]+=2;history.ingest([],14,identifier(14))
        self.assertEqual(history.snapshot()['metrics']['bps'],.5)
        self.assertEqual(history.snapshot()['metrics']['header_bps'],1)

    def test_missing_transaction_window_cannot_fabricate_tps_and_staleness_is_explicit(self):
        tick=[0.0];history=BlockHistory('fixture',clock=lambda:tick[0])
        history.ingest([row(1)],1,identifier(1));tick[0]=2
        history.ingest([row(50,17)],50,identifier(50))
        metrics=history.snapshot()['metrics']
        self.assertEqual(metrics['bps'],24.5);self.assertIsNone(metrics['tps'])
        history.fail();graph=history.snapshot()
        self.assertTrue(graph['stale']);self.assertEqual(graph['error'],'GG_BLOCK_GRAPH_READ_FAILED')
        self.assertEqual(len(graph['blocks']),1)

    def test_api_finality_samples_remain_separate_from_header_interval(self):
        history=BlockHistory('fixture');history.ingest([row(0),row(1,12)],1,identifier(1))
        graph=history.snapshot([{'state':'FINALIZED','elapsed_ms':500},
                                {'state':'FINALIZED','elapsed_ms':700},
                                {'state':'SUBMITTED','elapsed_ms':0}],ttf_basis='API_SUBMISSION_TO_EXECUTION_PROOF')
        metrics=graph['metrics'];self.assertEqual(metrics['ttf_basis'],'API_SUBMISSION_TO_EXECUTION_PROOF')
        self.assertEqual((metrics['ttf_ms'],metrics['ttf_p50_ms'],metrics['ttf_p95_ms'],metrics['ttf_samples']),(500,500,700,2))
        self.assertEqual(metrics['block_interval_ms'],1000)
        self.assertEqual(graph['blocks'][-1]['transaction_count'],12)
        self.assertEqual(graph['topology'],'CHAIN')

    def test_fast_complete_observations_keep_exact_tx_rate_after_header_pruning(self):
        tick=[0.0];history=BlockHistory('fixture',clock=lambda:tick[0])
        history.ingest([row(0,0)],0,identifier(0))
        for height in range(1,151):
            tick[0]=height/60
            history.ingest([row(height,2)],height,identifier(height))
        graph=history.snapshot();metrics=graph['metrics']
        self.assertEqual(len(history.rows),48)
        self.assertLessEqual(len(history._tx_observations),256)
        self.assertAlmostEqual(metrics['bps'],60)
        self.assertAlmostEqual(metrics['tps'],120)
        self.assertGreater(metrics['observed_blocks'],48)
        # A gap invalidates this rate window even if later reads are complete.
        tick[0]+=1;history.ingest([row(211,9)],211,identifier(211))
        self.assertIsNone(history.snapshot()['metrics']['tps'])

    def test_backfill_never_counts_as_new_transactions(self):
        tick=[0.0];history=BlockHistory('fixture',clock=lambda:tick[0])
        history.ingest([row(50,99)],50,identifier(50))
        for height in range(49,42,-1):
            tick[0]+=.2;history.ingest([row(height,99)],50,identifier(50))
        metrics=history.snapshot()['metrics']
        self.assertEqual(metrics['bps'],0)
        self.assertEqual(metrics['tps'],0)

    def test_decoders_validate_chain_parent_transaction_count_and_no_secret_fields(self):
        evm={'number':'0x2','hash':'0x'+identifier(2),'parentHash':'0x'+identifier(1),
             'timestamp':'0x65','transactions':['0x'+identifier(10),'0x'+identifier(11)]}
        normalized=evm_block(evm)
        self.assertEqual(normalized['transaction_count'],2);self.assertEqual(normalized['parent_hash'],identifier(1))
        comet={'block_id':{'hash':identifier(2).upper()},'block':{
            'header':{'height':'2','chain_id':'gg-fixture','last_block_id':{'hash':identifier(1)},
                      'time':'2026-10-29T04:00:00.123456789Z','proposer_address':'ab'*20},
            'data':{'txs':['public-encoded-fixture']*3}}}
        self.assertEqual(comet_block(comet,'gg-fixture')['transaction_count'],3)
        with self.assertRaisesRegex(ValueError,'CHAIN'):comet_block(comet,'foreign')
        with self.assertRaises(ValueError):evm_block(dict(evm,hash='not-a-hash'))
        with self.assertRaises(ValueError):evm_block(dict(evm,transactions=[{}]))
        with self.assertRaises(ValueError):comet_block(dict(comet,block={'header':{}}),'gg-fixture')
        self.assertFalse(set(normalized)&{'private_key','seed','transactions','txs','raw'})


class EngineGraphGuards(unittest.TestCase):
    def test_live_hardhat_tail_uses_128_real_replies_without_larger_rpc_batches(self):
        from backend import gg_testnet as node
        history=BlockHistory('Hardhat 3',history_limit=LIVE_HISTORY_LIMIT)
        def block(height):
            return {'number':hex(height),'hash':'0x'+identifier(height),'parentHash':'0x'+identifier(height-1),
                    'timestamp':hex(1700000000+height),'transactions':[]}
        seen=set()
        def batch(calls):
            self.assertLessEqual(len(calls),FETCH_LIMIT-1)
            self.assertTrue(all(name=='eth_getBlockByNumber' for name,_ in calls))
            heights=[int(params[0],16) for _,params in calls]
            seen.update(heights)
            return [block(height) for height in heights]
        with patch.object(node,'_block_history',history),patch.object(node,'_session','owned-fixture'),\
                patch.object(node,'_rpc_batch',side_effect=batch) as reads:
            for _ in range(19):graph=node._block_graph(block(240))
            self.assertEqual(len(graph['blocks']),128)
            self.assertEqual({value['height'] for value in graph['blocks']},seen|{240})
            self.assertEqual(len(graph['edges']),127)
            self.assertFalse(graph['stale'])
            calls=reads.call_count
            node._block_graph(block(240))
            self.assertEqual(reads.call_count,calls)
            self.assertTrue(all(len(call.args[0])<=7 for call in reads.call_args_list))

    def test_hardhat_backfill_is_one_bounded_read_batch_and_unchanged_tip_stops_reading(self):
        from backend import gg_testnet as node
        history=BlockHistory('Hardhat 3')
        def block(height):
            return {'number':hex(height),'hash':'0x'+identifier(height),'parentHash':'0x'+identifier(height-1),
                    'timestamp':hex(1700000000+height),'transactions':[]}
        def batch(calls):
            self.assertLessEqual(len(calls),7)
            self.assertTrue(all(name=='eth_getBlockByNumber' for name,_ in calls))
            return [block(int(params[0],16)) for _,params in calls]
        with patch.object(node,'_block_history',history),patch.object(node,'_session','owned-fixture'),\
                patch.object(node,'_rpc_batch',side_effect=batch) as reads:
            for _ in range(7):graph=node._block_graph(block(60))
            self.assertEqual(len(graph['blocks']),48);self.assertFalse(graph['stale'])
            previous=reads.call_count;node._block_graph(block(60));self.assertEqual(reads.call_count,previous)
            self.assertTrue(all(len(call.args[0])<=7 for call in reads.call_args_list))
            bad=block(61);bad['parentHash']='0x'+identifier(500)
            failed=node._block_graph(bad);self.assertTrue(failed['stale'])
            self.assertEqual(failed['tip_height'],60)

    def test_comet_certificate_marker_requires_exact_sdk_verified_tip_hash(self):
        from backend import gg_consensus as node
        history=BlockHistory('CometBFT v0.40.0',first_height=1)
        def rpc(index,method,params):
            self.assertEqual(method,'block');height=int(params['height'])
            return {'block_id':{'hash':identifier(height)},'block':{
                'header':{'height':str(height),'chain_id':'gg-fixture','last_block_id':{'hash':identifier(height-1) if height>1 else ''},
                          'time':'2026-10-29T04:00:00Z','proposer_address':'ab'*20},'data':{'txs':[]}}}
        with patch.object(node,'_block_history',history),patch.object(node,'_genesis_hash','fixture-genesis'),\
                patch.object(node,'_genesis',{'chain_id':'gg-fixture'}),\
                patch.object(node,'_certified_tip',(5,identifier(5))),patch.object(node,'_rpc',side_effect=rpc) as calls:
            graph=node._block_graph(0,5)
            self.assertFalse(graph['stale']);self.assertEqual(len(graph['blocks']),5)
            self.assertTrue(graph['blocks'][-1]['certificate_verified'])
            self.assertFalse(any(b['certificate_verified'] for b in graph['blocks'][:-1]))
            before=calls.call_count;node._block_graph(0,5);self.assertEqual(calls.call_count,before)
            with patch.object(node,'_certified_tip',(6,identifier(600))):
                bad=node._block_graph(0,6)
            self.assertTrue(bad['stale']);self.assertEqual(bad['tip_height'],5)


class OwnedEngineTelemetryTests(unittest.TestCase):
    def test_real_hardhat_receipts_map_to_actual_parent_hashes_and_stop_clears_graph(self):
        from backend import gg_testnet as node
        if not node.available():self.skipTest('Optional pinned Hardhat engine not installed')
        processes=[]
        try:
            initial=node.start();processes.append(node._process)
            self.assertEqual(initial['state'],'RUNNING')
            node.deploy_token();result=node.self_test();graph=result['block_graph']
            self.assertFalse(graph['stale'],graph['error'])
            self.assertEqual(graph['tip_height'],result['height'])
            self.assertEqual(len(graph['edges']),len(graph['blocks'])-1)
            for block in graph['blocks']:
                actual=node._rpc('eth_getBlockByNumber',[hex(block['height']),False])
                self.assertEqual(block['hash'],actual['hash'][2:].lower())
                self.assertEqual(block['transaction_count'],len(actual['transactions']))
            for measurement in result['measurements']:
                if measurement['operation']=='transaction' and measurement['state']=='CONFIRMED':
                    self.assertIsInstance(measurement['block_height'],int)
                    self.assertTrue(measurement['block_hash'].startswith('0x'))
            self.assertGreaterEqual(graph['metrics']['ttf_samples'],5)
            self.assertEqual(graph['metrics']['ttf_basis'],'API_SUBMISSION_TO_RECEIPT')
        finally:
            node.stop()
            self.assertEqual(node.snapshot()['block_graph']['blocks'],[])
            for process in processes:self.assertIsNotNone(process.poll())

    def test_real_four_validator_batched_transactions_are_not_one_transaction_per_block(self):
        from backend import gg_consensus as node
        if not node.available():self.skipTest('Optional pinned consensus engine not installed')
        processes=[]
        try:
            initial=node.start();processes=[n['process'] for n in node._nodes]
            self.assertEqual(initial['online'],4)
            result=node.benchmark(16);graph=result['block_graph']
            self.assertFalse(graph['stale'],graph['error'])
            self.assertEqual(graph['tip_height'],result['proof']['certificate_height'])
            self.assertTrue(graph['blocks'][-1]['certificate_verified'])
            self.assertEqual(len(graph['edges']),len(graph['blocks'])-1)
            self.assertEqual(result['benchmark']['unique_finalized'],16)
            self.assertTrue(any(b['transaction_count']>1 for b in graph['blocks']))
            self.assertGreaterEqual(sum(b['transaction_count'] for b in graph['blocks']),16)
            self.assertEqual(graph['metrics']['ttf_samples'],16)
            self.assertEqual(graph['metrics']['ttf_basis'],'API_SUBMISSION_TO_EXECUTION_PROOF')
        finally:
            node.stop()
            self.assertEqual(node.snapshot()['block_graph']['blocks'],[])
            for process in processes:self.assertIsNotNone(process.poll())


if __name__=='__main__':unittest.main()
