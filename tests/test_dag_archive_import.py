"""Real profile/SQL/signature tests; SDK verifier mocked only in this unit layer.

The public packet here is a structural certificate fixture, not SDK evidence.
Private acceptance separately runs the actual native verifier and SDK committee.
"""
from contextlib import closing,contextmanager
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from backend import gg_dag_archive as archive, gg_node_store as store
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_parallel_dag import ParallelDag,pack,_tree
from tests import test_lan_validator_runtime as fixtures


class AtomicPublicHistoryImportTests(unittest.TestCase):
    setUp=fixtures.ValidatorRuntimeTests.setUp
    cleanup=fixtures.ValidatorRuntimeTests.cleanup
    manager=fixtures.ValidatorRuntimeTests.manager
    network=fixtures.ValidatorRuntimeTests.network

    def prepare(self,counts=(2,3)):
        first,second,phone,_=self.network();owner=first._peer;observer=phone._peer
        anchor=anchor_from_owned_peer(owner);source=anchor['genesis']['dag'];raws=[]
        for count in counts:
            block=owner._engine.produce_lan_test_block(owner._local_indices[0],count,32*1024*1024)
            raws.append(block['wire'])
        engine=ParallelDag.from_public_genesis(owner._engine.export_public_genesis())
        engine.configure_lan_capacity();engine.configure_lan_roles(source['allowed_producers'])
        order=[]
        try:
            for raw in raws:
                result=engine.admit_relayed(raw,0);body=json.loads(raw)['body']
                order.append({'hash':result['hash'],'index':len(order)+1,'producer_index':body['producer_index'],
                    'sequence':body['sequence'],'transactions':len(body['transactions'])})
            engine.reconcile()
            accounts=[{'address':address,**engine._preview_state[address]} for address in sorted(engine._preview_state)]
            state={'height':1,'state_root':'a'*64,'dag':{'checkpoint':1 if raws else 0,'blocks':len(raws),
                'transactions':sum(counts),'account_root':_tree(accounts,b'GG-DAG-ACCOUNT-v1\0')[-1][0],
                'order_root':_tree(order,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0]}}
        finally:engine.stop()
        packet={'schema':'gg.consensus.proof.v1',**anchor,'state':state,
            'signed_header':{'header':{'height':'2'},'commit':{'block_id':{'hash':'b'*64}}}}
        def frame(kind,raw):return kind+len(raw).to_bytes(4,'big')+raw
        # Keep this header's actual field order, including header-before-commit
        # within signed_header. Python sorted-key canonicalization is not SDK encoding.
        wire=archive.MAGIC+frame(b'H',json.dumps({'certificate':packet,'schema':'gg.dag.public-archive.v1'},separators=(',',':')).encode('ascii'))
        if raws:
            manifest={'checkpoint':1,'blocks':[hashlib.sha256(raw).hexdigest() for raw in raws]}
            wire+=frame(b'M',pack(manifest))
            for raw in raws:wire+=frame(b'R',raw)
        content=hashlib.sha256(wire).hexdigest();raw_bytes=sum(map(len,raws))
        wire+=frame(b'F',pack({'schema':'gg.dag.archive.footer.v1','blocks':len(raws),
            'checkpoints':state['dag']['checkpoint'],'raw_bytes':raw_bytes,'content_sha256':content}))
        verified={'schema':'gg.dag.archive.result.v1','verified':True,'verification_scope':archive.SCOPE,
            'genesis_hash':anchor['genesis_hash'],'snapshot_trust_used':False,'signing_keys_exported':False,
            'archive_sha256':hashlib.sha256(wire).hexdigest(),'content_sha256':content,'blocks_replayed':len(raws),
            'raw_payload_bytes':raw_bytes,'certificate_height':2}
        path=Path(self.temp.name)/'history.ggdag';path.write_bytes(wire)
        profile=observer._profile;identity=profile.descriptor();protected=deepcopy(profile._meta['protected_keys'])
        session=profile.session();name=profile.name;phone.stop()
        return name,path,verified,packet,order,raws,identity,protected,session

    def assert_reopened(self,name,expected,identity,protected):
        with closing(store.NodeProfile.open(name)) as profile:
            self.assertEqual(profile.snapshot()['counts']['dag'],expected)
            self.assertEqual(profile.descriptor(),identity)
            self.assertEqual(profile._meta['protected_keys'],protected)
            return profile.verified_order()

    def test_full_import_reopens_same_identity_order_and_original_signed_payloads(self):
        name,path,verified,packet,order,raws,identity,protected,session=self.prepare()
        with patch.object(archive,'_native_verify',return_value=verified) as native:
            result=archive.import_profile_archive(name,str(path))
        self.assertEqual(result['state'],'PUBLIC_DAG_HISTORY_IMPORTED')
        self.assertEqual(result['blocks_imported'],2);self.assertEqual(result['transactions_imported'],5)
        self.assertFalse(result['identity_replaced']);self.assertFalse(result['production_started'])
        self.assertFalse(result['validator_state_restored']);self.assertFalse(result['native_transfer_history_restored'])
        self.assertEqual(native.call_args.args[2],{'genesis':packet['genesis'],'genesis_hash':packet['genesis_hash']})
        self.assertIsNone(native.call_args.args[3])
        self.assertEqual(self.assert_reopened(name,2,identity,protected),{'packet':packet,'order':order})
        with closing(store.NodeProfile.open(name)) as profile:
            self.assertEqual(list(profile.records()),[('dag',raw) for raw in raws])
            self.assertEqual(profile.session(),session)
            self.assertEqual(profile.consensus_observation()['packet'],packet)
        phone=self.managers[2];phone.dispatch('lan.resume',{'profile':name})
        self.assertEqual(phone._peer._engine.lan_evidence()['transactions'],5)
        self.assertEqual(phone._peer._engine._certified_order,())  # full SDK activation still runs its own checks
        self.assertEqual(phone._peer._profile.verified_order()['order'],order)

    def test_file_changed_after_native_pass_rolls_back_every_staged_block(self):
        name,path,verified,_,_,_,identity,protected,_=self.prepare()
        def change(*args,**kwargs):
            data=path.read_bytes();path.write_bytes(data.replace(b'"raw_bytes":',b'"raw_bytez":'))
            return verified
        with patch.object(archive,'_native_verify',side_effect=change),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
            archive.import_profile_archive(name,str(path))
        self.assertIsNone(self.assert_reopened(name,0,identity,protected))

    def test_cancel_after_first_staged_insert_has_no_committed_prefix(self):
        name,path,verified,_,_,_,identity,protected,_=self.prepare();cancelled=threading.Event()
        original=store.NodeProfile._advance
        def advance(head,kind,raw):original(head,kind,raw);cancelled.set()
        def check():
            if cancelled.is_set():raise ValueError('OWNED_IMPORT_CANCEL')
        with patch.object(archive,'_native_verify',return_value=verified),patch.object(store.NodeProfile,'_advance',side_effect=advance):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):archive.import_profile_archive(name,str(path),check=check)
        self.assertIsNone(self.assert_reopened(name,0,identity,protected))

    def test_commit_failure_before_or_after_sync_is_exact_old_or_complete_new(self):
        for after in (False,True):
            with self.subTest(after=after),patch.object(store,'ROOT',Path(self.temp.name)/str(after)/'nodes'),patch.object(fixtures.validators,'ROOT',Path(self.temp.name)/str(after)/'validators'):
                name,path,verified,packet,order,_,identity,protected,_=self.prepare()
                original=store.NodeProfile._commit
                def fail(profile):
                    if after:original(profile)
                    raise OSError('owned ambiguous archive commit completion')
                with patch.object(archive,'_native_verify',return_value=verified),patch.object(store.NodeProfile,'_commit',fail):
                    with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):archive.import_profile_archive(name,str(path))
                restored=self.assert_reopened(name,2 if after else 0,identity,protected)
                self.assertEqual(restored,{'packet':packet,'order':order} if after else None)
                for manager in self.managers:manager.stop()

    def test_nonempty_profile_and_active_runtime_are_rejected_before_verification(self):
        name,path,verified,*_=self.prepare()
        first=self.managers[0]
        with patch.object(archive,'_native_verify',side_effect=AssertionError('must not invoke native')):
            with self.assertRaisesRegex(ValueError,'STOP_BEFORE_ARCHIVE_IMPORT'):
                first.dispatch('lan.archive_import',{'profile':name,'path':str(path)})
        with patch.object(archive,'_native_verify',return_value=verified):archive.import_profile_archive(name,str(path))
        with patch.object(archive,'_native_verify',side_effect=AssertionError('must not invoke native')):
            with self.assertRaisesRegex(ValueError,'EMPTY_JOURNAL_REQUIRED'):archive.import_profile_archive(name,str(path))

    def test_complete_old_certificate_floor_is_passed_to_verifier_and_remains_exact(self):
        name,path,verified,packet,order,_,identity,protected,_=self.prepare()
        with closing(store.NodeProfile.open(name)) as profile:profile.save_consensus_certificate(packet)
        with patch.object(archive,'_native_verify',return_value=verified) as native:
            archive.import_profile_archive(name,str(path))
        self.assertEqual(native.call_args.args[3],(2,'b'*64))
        self.assertEqual(self.assert_reopened(name,2,identity,protected),{'packet':packet,'order':order})

    def test_producer_profile_and_foreign_pin_fail_before_any_history_write(self):
        name,path,verified,*_=self.prepare();first=self.managers[0];first.stop()
        with patch.object(archive,'_native_verify',side_effect=AssertionError('must not invoke native')):
            with self.assertRaisesRegex(ValueError,'REPLICA_REQUIRED'):archive.import_profile_archive('Windows',str(path))
        verified=deepcopy(verified);verified['certificate_height']=3
        with patch.object(archive,'_native_verify',return_value=verified),self.assertRaisesRegex(ValueError,'ARCHIVE_CONTEXT'):
            archive.import_profile_archive(name,str(path))
        with closing(store.NodeProfile.open(name)) as profile:self.assertEqual(profile.snapshot()['records'],0)

    def test_frame_size_rejected_before_reading_any_declared_payload(self):
        for size in (archive.HEADER_LIMIT+1,2**32-1):
            file=io.BytesIO(archive.MAGIC+b'H'+size.to_bytes(4,'big'))
            with self.subTest(size=size),self.assertRaisesRegex(ValueError,'ARCHIVE_FRAME'):
                archive.PublicDagArchive(file,{}, {},lambda:None)

    def test_native_verification_failure_preserves_empty_profile_and_identity(self):
        name,path,_,_,_,_,identity,protected,_=self.prepare()
        with patch.object(archive,'_native_verify',side_effect=ValueError('GG_DAG_ARCHIVE_VERIFY_FAILED')):
            with self.assertRaisesRegex(ValueError,'VERIFY_FAILED'):archive.import_profile_archive(name,str(path))
        self.assertIsNone(self.assert_reopened(name,0,identity,protected))

    def test_truncated_final_frame_rolls_back_all_original_valid_blocks(self):
        name,path,verified,_,_,_,identity,protected,_=self.prepare()
        def truncate(*args,**kwargs):path.write_bytes(path.read_bytes()[:-50]);return verified
        with patch.object(archive,'_native_verify',side_effect=truncate),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
            archive.import_profile_archive(name,str(path))
        self.assertIsNone(self.assert_reopened(name,0,identity,protected))

    def test_import_must_extend_previously_observed_certified_order(self):
        name,path,verified,packet,order,_,identity,protected,_=self.prepare()
        older=deepcopy(packet);older['state']['height']=0;older['signed_header']['header']['height']='1'
        older_order=[{**order[0],'hash':'c'*64}]
        older['state']['dag'].update(blocks=1,transactions=order[0]['transactions'],
            order_root=_tree(older_order,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0])
        with closing(store.NodeProfile.open(name)) as profile:
            profile.save_consensus_certificate(older);profile.save_verified_order(older,older_order)
        with patch.object(archive,'_native_verify',return_value=verified),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
            archive.import_profile_archive(name,str(path))
        self.assertEqual(self.assert_reopened(name,0,identity,protected),{'packet':older,'order':older_order})

    def test_unknown_or_insufficient_memory_never_publishes_an_import(self):
        name,path,verified,_,_,_,identity,protected,_=self.prepare()
        for info,code in (({'memory_total_bytes':None,'memory_available_bytes':None},'MEMORY_MEASUREMENT'),
                          ({'memory_total_bytes':64*1024,'memory_available_bytes':1},'WRITE_FAILED')):
            with self.subTest(info=info),patch.object(archive,'_native_verify',return_value=verified),patch('backend.gg_dag_hardware.hardware_info',return_value=info):
                with self.assertRaisesRegex(ValueError,code):archive.import_profile_archive(name,str(path))
            self.assertIsNone(self.assert_reopened(name,0,identity,protected))

    def test_payload_reservation_precedes_allocation_and_covers_consumer_work(self):
        _,path,verified,packet,_,raws,*_=self.prepare()
        anchor={key:packet[key] for key in ('genesis','genesis_hash')};data=path.read_bytes()
        offset=8
        for kind in (b'H',b'M'):
            self.assertEqual(data[offset:offset+1],kind)
            offset+=5+int.from_bytes(data[offset+1:offset+5],'big')
        self.assertEqual(data[offset:offset+1],b'R');start=offset+5
        file=io.BytesIO(data);reader=archive.PublicDagArchive(file,anchor,verified,lambda:None)
        def denied(size):raise ValueError('OWNED_RESERVATION_DENIED')
        with self.assertRaisesRegex(ValueError,'RESERVATION_DENIED'):next(reader.payloads(denied))
        self.assertEqual(file.tell(),start)
        active=[]
        @contextmanager
        def reserve(size):
            active.append(size)
            try:yield
            finally:active.pop()
        reader=archive.PublicDagArchive(io.BytesIO(data),anchor,verified,lambda:None)
        stream=reader.payloads(reserve)
        self.assertEqual(next(stream),raws[0]);self.assertEqual(active,[len(raws[0])])
        stream.close();self.assertEqual(active,[]);self.assertFalse(reader.complete)


if __name__=='__main__':unittest.main()
