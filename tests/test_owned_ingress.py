"""Real authenticated TCP and durable profiles; no operator state or devices."""
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from backend import gg_lan_dag as lan,gg_node_store as store,portable_wallet_vault as vault,gg_peer_scan as scan
from backend.gg_lan_admission import RefillBudget
from backend.gg_parallel_dag import ParallelDag,pack


class OwnedIngressTests(unittest.TestCase):
    def setUp(self):
        unlock=vault.session('disposable ingress fixture password');unlock.__enter__();self.addCleanup(unlock.__exit__,None,None,None)
        temp=tempfile.TemporaryDirectory(prefix='gg-owned-ingress-');self.addCleanup(temp.cleanup)
        scope=patch.object(store,'ROOT',Path(temp.name)/'nodes');scope.start();self.addCleanup(scope.stop)
        self.nodes=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for node in reversed(self.nodes):node.stop()

    def peer(self,profile):
        config=profile.descriptor()
        node=lan.LanDagPeer(config['label'],config['host'],config['port'],config['trusted_coordinator'],False,
            allowed_cidr=config['allowed_cidr'],allow_dag_transactions=True,node_profile=profile)
        node._start_gossip=Mock();self.nodes.append(node);node.start_pairing();return node

    def network(self):
        nodes=[]
        for index in range(3):
            profile=store.NodeProfile.create('Lane'+str(len(self.nodes)),{'label':'Lane '+str(index),'host':'127.0.0.'+str(index+1),
                'port':0,'allowed_cidr':'127.0.0.0/8','trusted_coordinator':None,'allow_test_tokens':False,'allow_dag_transactions':True})
            nodes.append(self.peer(profile))
        for node in nodes[1:]:node.pin_coordinator(nodes[0].public_key)
        bundle=nodes[0].create_session([node.public_invite() for node in nodes],enable_dag_transactions=True)
        for node in nodes:node.install_session(bundle)
        return nodes

    def resume(self,node):
        name=node._profile.name;node.stop();return self.peer(store.NodeProfile.open(name))

    def block(self,node,producer=None,count=1):
        return node._engine.produce_lan_test_block(node._local_indices[0] if producer is None else producer,count,node._wire_limit)

    def test_exhausted_authenticated_lane_does_not_stop_other_lane_or_local_production(self):
        a,b,c=self.network();clock=[0.0]
        a._raw_auth_budget=RefillBudget(100,1,maximum_actors=3,clock=lambda:clock[0])
        bad=object();good=object();a._socket_peers.update({bad:b.public_key,good:c.public_key})
        a._account_received(100,bad)
        for _ in range(20):
            with self.assertRaisesRegex(ValueError,'PEER_CREDIT'):a._account_received(1,bad)
        a._account_received(100,good);self.assertEqual(a._transport_exhausted,'')
        self.block(a);self.block(c)
        clock[0]=1.0;a._account_received(100,bad)
        a._raw_auth_budget=RefillBudget(10**7,100,maximum_actors=3)
        a._connections_admitted=lan.MAX_REQUESTS+1;a._raw_received=a._total_bytes_limit+1;a._total_bytes=a._total_bytes_limit+1
        b._pull(a.public_key,'PAGE',{'after':0});self.assertEqual(b._cursors[a.public_key],1)
        a._pull(c.public_key,'PAGE',{'after':0});self.assertEqual(a._cursors[c.public_key],1)
        self.assertEqual(a._transport_exhausted,'');self.assertEqual(a.snapshot()['lan']['transport']['credit_mode'],'REFILLING_PER_INGRESS')

    def test_engine_work_denial_is_per_ingress_and_refills_without_lifetime_reset(self):
        a,b,c=self.network();clock=[0.0]
        a._engine._fair_ingress=RefillBudget(1000000,2,maximum_actors=3,clock=lambda:clock[0])
        lane=a._local_indices[0]
        a._engine._charge(lane,1000000,relayed=True)
        with self.assertRaisesRegex(ValueError,'PEER_CREDIT'):a._engine._charge(lane,1,relayed=True)
        a._engine._charge((lane+1)%6,1000000,relayed=True);self.block(a)
        a._engine._stats['attempts']=1000000
        clock[0]=1.0;a._engine._charge(lane,1000000,relayed=True);self.assertGreater(a._engine._stats['attempts'],1000000)

    def test_frame_denial_does_not_spend_another_peer_or_output_lane(self):
        a,b,c=self.network();now=[0.0]
        a._frame_budget=RefillBudget(100,2,maximum_actors=6,clock=lambda:now[0])
        a._credit(b.public_key,10);a._credit(b.public_key,10)
        with self.assertRaisesRegex(ValueError,'PEER_CREDIT'):a._credit(b.public_key,1)
        a._credit(c.public_key,10);a._credit('out:'+c.public_key,100)
        self.assertEqual(a._transport_exhausted,'')
        now[0]=1.0;a._credit(b.public_key,10)

    def refused_fixture(self):
        owner,observer,other=self.network();producer=owner._local_indices[0]
        for count in (1,2):
            clone=ParallelDag.from_public_genesis(owner._engine.export_public_genesis());self.addCleanup(clone.stop)
            clone.attach_local_producers({producer:owner._local_keys[0]});fork=clone.produce_lan_test_block(producer,count)
            observer._ingest(fork['wire'],owner.public_key,fork['hash'])
        selected=self.block(owner,count=3);honest=self.block(owner,owner._local_indices[1])
        return owner,observer,selected,honest

    def test_page_scans_past_refused_variant_and_preserves_unvalidated_hole_on_restart(self):
        owner,observer,selected,honest=self.refused_fixture()
        observer._pull(owner.public_key,'PAGE',{'after':0})
        self.assertFalse(observer._engine.has_proposal(selected['hash']));self.assertTrue(observer._engine.has_proposal(honest['hash']))
        self.assertEqual((observer._cursors[owner.public_key],observer._scan_cursors[owner.public_key]),(0,2))
        progress=observer._profile.scan_progress()[owner.public_key]
        self.assertEqual((progress['unresolved_records'],progress['declined_records']),(1,1))
        self.assertEqual(observer._peer_sync[owner.public_key]['state'],'SCANNED_WITH_REFUSALS')
        from backend.terminal_cli import foreground_summary
        summary=foreground_summary('lan.resume',observer.snapshot())
        row=next(row for row in summary['peer_sync'] if row['label']==owner.label)
        self.assertEqual((row['state'],row['validated_prefix'],row['unresolved_records']),('SCANNED_WITH_REFUSALS',0,1))
        observer=self.resume(observer)
        self.assertEqual((observer._cursors[owner.public_key],observer._scan_cursors[owner.public_key]),(0,2))
        observer._pull(owner.public_key,'PAGE',{'after':2})
        self.assertEqual(observer._peer_sync[owner.public_key]['state'],'SCANNED_WITH_REFUSALS')
        self.block(observer)

    def test_invalid_authenticated_end_does_not_commit_scan_progress(self):
        owner,observer,other=self.network();block=self.block(owner);frame=owner._frame
        def changed(session,sequence,kind,payload):
            return frame(session,sequence,kind,{**payload,'records':99} if kind=='END' else payload)
        with patch.object(owner,'_frame',side_effect=changed),self.assertRaisesRegex(ValueError,'PAGE_END'):
            observer._pull(owner.public_key,'PAGE',{'after':0})
        self.assertTrue(observer._engine.has_proposal(block['hash']))
        self.assertEqual(observer._cursors[owner.public_key],0);self.assertEqual(observer._profile.scan_progress(),{})
        observer._pull(owner.public_key,'PAGE',{'after':0});self.assertEqual(observer._cursors[owner.public_key],1)

    def test_one_source_cannot_occupy_all_handlers(self):
        owner,observer,other=self.network();held=[];self.addCleanup(lambda:[sock.close() for sock in held])
        for _ in range(2):
            sock=socket.socket();sock.bind((observer.host,0));sock.connect((owner.host,owner.port));held.append(sock)
        deadline=time.monotonic()+2
        while owner._active_addresses.get(observer.host,0)<2 and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(owner._active_addresses.get(observer.host),2)
        self.block(owner);other._pull(owner.public_key,'PAGE',{'after':0})
        self.assertEqual(other._cursors[owner.public_key],1);self.assertLessEqual(len(owner._handlers),3)

    def test_missing_parent_buffer_is_partitioned_and_deferred_rows_are_not_acknowledged(self):
        owner,observer,other=self.network();parent=self.block(owner);child=self.block(owner)
        observer._orphan_limit=len(child['wire'])*2
        self.assertEqual(observer._ingest(child['wire'],owner.public_key,child['hash']),'PENDING_PARENTS')
        before=observer._orphan_bytes
        third=self.block(owner)
        self.assertEqual(observer._ingest(third['wire'],owner.public_key,third['hash']),'PENDING_PARENTS')
        self.assertEqual(observer._orphan_bytes,before);self.assertFalse(observer._engine.has_proposal(third['hash']))
        observer._ingest(parent['wire'],owner.public_key,parent['hash']);self.assertTrue(observer._engine.has_proposal(child['hash']))

    def test_scan_commit_lost_return_recovers_exact_outcome_without_false_admission(self):
        for after in (False,True):
            owner,observer,other=self.network();block=self.block(owner);observer._ingest(block['wire'],owner.public_key,block['hash'])
            commit=observer._profile._commit
            def failed():
                if after:commit()
                raise OSError('disposable scan commit outcome')
            events=[scan.event('OBSERVED',1,block['hash'])]
            with patch.object(observer._profile,'_commit',side_effect=failed),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
                observer._profile.save_scan_page(owner.public_key,events)
            self.assertEqual(observer._profile.scan_progress(),{})
            resumed=self.resume(observer)
            self.assertEqual(resumed._profile.scan_progress().get(owner.public_key,{}).get('position',0),int(after))
            for node in (owner,resumed,other):node.stop()

    def test_resolution_requires_actual_durable_payload_and_survives_reopen(self):
        owner,observer,other=self.network();block=self.block(owner)
        observer._profile.save_scan_page(owner.public_key,[scan.event('OBSERVED',1,block['hash'],'DEFERRED',scan.REASONS['DEFERRED'])])
        observer._resolve_scan_progress();self.assertEqual(observer._cursors[owner.public_key],0)
        observer._pull(owner.public_key,'GET',{'hashes':[block['hash']]})
        self.assertEqual(observer._cursors[owner.public_key],1);self.assertEqual(observer._profile.scan_progress()[owner.public_key]['unresolved_records'],0)
        with self.assertRaisesRegex(ValueError,'SCAN_REQUIRED'):observer._profile.save_cursor(owner.public_key,2)
        observer=self.resume(observer);self.assertEqual(observer._cursors[owner.public_key],1)

    def test_deferred_page_hole_survives_lost_ram_and_retries_actual_authenticated_payload(self):
        owner,observer,other=self.network();delayed=self.block(owner);later=self.block(owner,owner._local_indices[1]);ingest=observer._ingest_new
        def delay(raw,peer,claimed_hash,deadline):
            return 'PENDING_PARENTS' if claimed_hash==delayed['hash'] else ingest(raw,peer,claimed_hash,deadline)
        # Fault injection models temporary local admission deferral. Transport,
        # signatures, persisted scan events and subsequent GET are actual.
        with patch.object(observer,'_ingest_new',side_effect=delay):observer._pull(owner.public_key,'PAGE',{'after':0})
        self.assertEqual(observer._cursors[owner.public_key],0);self.assertTrue(observer._engine.has_proposal(later['hash']))
        observer=self.resume(observer);self.assertFalse(observer._orphans)
        hashes=observer._pending_fetches(owner.public_key);self.assertEqual(hashes,[delayed['hash']])
        observer._pull(owner.public_key,'GET',{'hashes':hashes})
        self.assertEqual(observer._cursors[owner.public_key],2);self.assertEqual(observer._pending_fetches(owner.public_key),[])
        self.assertEqual(observer._profile.scan_progress()[owner.public_key]['unresolved_records'],0)

    def test_deferred_retry_rotates_past_unresolvable_hashes_and_excludes_quota_refusals(self):
        owner,observer,other=self.network();events=[]
        for index in range(1,10):events.append(scan.event('OBSERVED',index,format(index,'064x'),'DEFERRED',scan.REASONS['DEFERRED']))
        observer._profile.save_scan_page(owner.public_key,events[:8]);observer._profile.save_scan_page(owner.public_key,events[8:])
        first=observer._pending_fetches(owner.public_key);second=observer._pending_fetches(owner.public_key)
        self.assertEqual(len(first),8);self.assertIn(format(9,'064x'),second)
        observer._profile.save_scan_page(owner.public_key,[scan.event('OBSERVED',10,'f'*64,'REFUSED',scan.REASONS['REFUSED'])])
        for _ in range(3):self.assertNotIn('f'*64,observer._pending_fetches(owner.public_key))

    def test_migration_unknown_commit_outcome_never_resets_identity_or_history(self):
        for after in (False,True):
            owner,observer,other=self.network();block=self.block(owner);profile=owner._profile
            name=profile.name;root=profile.root;keys=profile.descriptor()['public_keys'];owner.stop()
            with closing(sqlite3.connect(root/'node.sqlite3')) as db,db:
                db.execute('DROP TABLE peer_scans');db.execute('DROP TABLE orders');db.execute('PRAGMA user_version=1')
            commit=store.NodeProfile._commit
            def failed(instance):
                if after:commit(instance)
                raise OSError('disposable migration outcome')
            with patch.object(store.NodeProfile,'_commit',failed),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):store.NodeProfile.open(name)
            with closing(sqlite3.connect(root/'node.sqlite3')) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3 if after else 1)
            profile=store.NodeProfile.open(name);self.addCleanup(profile.close)
            self.assertEqual(profile.descriptor()['public_keys'],keys);self.assertEqual(list(profile.records()),[('dag',block['wire'])]);profile.close()
            observer.stop();other.stop()

    def test_schema_migration_preserves_identity_history_and_refuses_tampered_scan(self):
        owner,observer,other=self.network();block=self.block(owner);observer._pull(owner.public_key,'PAGE',{'after':0})
        profile=observer._profile;name=profile.name;root=profile.root;keys=profile.descriptor()['public_keys'];observer.stop()
        with closing(sqlite3.connect(root/'node.sqlite3')) as db,db:db.execute('DELETE FROM peer_scans')
        before=(root/'node.sqlite3').read_bytes()
        with self.assertRaisesRegex(ValueError,'PEER_SCAN_HEAD'):store.NodeProfile.open(name)
        self.assertEqual((root/'node.sqlite3').read_bytes(),before)
        # A schema-1 container contains no scan metadata or rows.
        name=owner._profile.name;root=owner._profile.root;keys=owner._profile.descriptor()['public_keys'];owner.stop()
        with closing(sqlite3.connect(root/'node.sqlite3')) as db,db:
            db.execute('DROP TABLE peer_scans');db.execute('DROP TABLE orders');db.execute('PRAGMA user_version=1')
        profile=store.NodeProfile.open(name);self.addCleanup(profile.close)
        self.assertEqual(profile.descriptor()['public_keys'],keys);self.assertEqual(list(profile.records()),[('dag',block['wire'])])
        self.assertEqual(profile._schema_version,3)
