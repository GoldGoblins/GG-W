"""Per-request wire credits remain valid across concurrent local policy changes."""
import contextlib
import unittest
from unittest.mock import Mock,patch
from backend import gg_lan_dag as lan
from backend.gg_dag_wire import record_frames
from tests.test_lan_dag_transport_health import FakeSocket


class WireCapacityTests(unittest.TestCase):
    def peer(self):
        peer=lan.LanDagPeer('Wire credit fixture');remote='a'*64
        # These are legacy DATA/END frame doubles, with no capability peer.
        peer._lossless_wire=False
        peer._roster={remote:{'label':'Linux','host':'127.0.0.1','port':16555,'producer_indices':[0,1]}}
        peer._cursors={remote:0};self.addCleanup(peer.stop)
        return peer,remote

    def serve(self,peer,remote,payload):
        peer._slots.acquire()
        with (patch.object(peer,'_read',side_effect=(({},10),({},10))),
              patch.object(peer,'_server_auth',return_value=(remote,'fixture-session')),
              patch.object(peer,'_check_frame',return_value={'kind':'PAGE','payload':payload}),
              patch.object(lan,'_send',return_value=10) as sent):
            peer._serve(FakeSocket(),'127.0.0.1')
            return [call.args[1]['body'] for call in sent.call_args_list]

    def test_server_never_sends_a_record_beyond_the_advertised_receive_credit(self):
        peer,remote=self.peer();peer._wire_limit=2*1024*1024
        peer._engine=Mock()
        self.addCleanup(lambda:setattr(peer,'_engine',None))
        peer._engine.public_proposals.return_value={'tip':2,'records':[
            {'hash':'b'*64,'admission_index':1,'wire':b'small'},
            {'hash':'c'*64,'admission_index':2,'wire':b'x'*(lan.MAX_WIRE+1)}]}
        frames=self.serve(peer,remote,{'after':0,'wire_limit':lan.MAX_WIRE})
        self.assertEqual([frame['kind'] for frame in frames],['DATA','END'])
        self.assertEqual(frames[-1]['payload'],{'records':1,'tip':2,'next_wire_bytes':lan.MAX_WIRE+1})
        # Legacy peers receive the original END shape and the safe small cap.
        legacy=self.serve(peer,remote,{'after':0})
        self.assertEqual([frame['kind'] for frame in legacy],['DATA','END'])
        self.assertEqual(legacy[-1]['payload'],{'records':1})
        allowed=self.serve(peer,remote,{'after':0,'wire_limit':2*1024*1024})
        self.assertIn('DATA_START',[frame['kind'] for frame in allowed])
        self.assertEqual(allowed[-1]['payload'],{'records':2,'tip':2,'next_wire_bytes':0})
        self.assertEqual(peer._transport_counts['failures'],0)

    def test_inflight_small_request_stays_small_then_next_request_catches_up(self):
        peer,remote=self.peer();record={'hash':'b'*64,'admission_index':1,'wire':b'x'*(lan.MAX_WIRE+1)}
        @contextlib.contextmanager
        def transition(*args,**kwargs):
            peer._wire_limit=2*1024*1024
            yield FakeSocket()
        with (patch.object(peer,'_pace_connection'),patch.object(peer,'_connection',side_effect=transition),
              patch.object(peer,'_client_auth',return_value='fixture-session'),
              patch.object(peer,'_read',return_value=({},10)),
              patch.object(peer,'_check_frame',return_value={'kind':'END','payload':{'records':0,'tip':1,'next_wire_bytes':len(record['wire'])}}),
              patch.object(lan,'_send',return_value=10) as sent):
            self.assertEqual(peer._pull(remote,'PAGE',{'after':0}),0)
            self.assertEqual(sent.call_args.args[1]['body']['payload']['wire_limit'],lan.MAX_WIRE)
        self.assertEqual(peer._peer_sync[remote]['state'],'BLOCK_EXCEEDS_LOCAL_LIMIT')
        self.assertEqual(peer._peer_sync[remote]['pending_records'],1)
        frames=[{'kind':kind,'payload':payload} for kind,payload in record_frames(record)]
        frames.append({'kind':'END','payload':{'records':1,'tip':1,'next_wire_bytes':0}})
        with (patch.object(peer,'_pace_connection'),patch.object(peer,'_connection',return_value=FakeSocket()),
              patch.object(peer,'_client_auth',return_value='fixture-session'),
              patch.object(peer,'_read',return_value=({},10)),patch.object(peer,'_check_frame',side_effect=frames),
              patch.object(peer,'_ingest',return_value='ADMITTED_UNFINALIZED') as ingest,patch.object(lan,'_send',return_value=10)):
            self.assertEqual(peer._pull(remote,'PAGE',{'after':0}),1)
            self.assertEqual(ingest.call_args.args[0],record['wire'])
        self.assertEqual(peer._peer_sync[remote]['state'],'CAUGHT_UP')
        self.assertEqual(peer._peer_sync[remote]['pending_records'],0)
        self.assertEqual(peer._transport_counts['failures'],0)

    def test_invalid_authenticated_end_cannot_publish_a_catchup_claim(self):
        for end in ({'records':True},{'records':0,'tip':False,'next_wire_bytes':0},
                    {'records':0,'tip':0,'next_wire_bytes':lan.MAX_WIRE+1},
                    {'records':0,'tip':1,'next_wire_bytes':1}):
            peer,remote=self.peer()
            with (patch.object(peer,'_pace_connection'),patch.object(peer,'_connection',return_value=FakeSocket()),
                  patch.object(peer,'_client_auth',return_value='fixture-session'),
                  patch.object(peer,'_read',return_value=({},10)),patch.object(peer,'_check_frame',return_value={'kind':'END','payload':end}),
                  patch.object(lan,'_send',return_value=10),self.assertRaises(ValueError)):
                peer._pull(remote,'PAGE',{'after':0})
            self.assertFalse(peer._peer_sync);self.assertFalse(peer._seen_monotonic)

    def pull_frames(self,peer,remote,frames,results):
        with (patch.object(peer,'_pace_connection'),patch.object(peer,'_connection',return_value=FakeSocket()),
              patch.object(peer,'_client_auth',return_value='fixture-session'),
              patch.object(peer,'_read',return_value=({},10)),patch.object(peer,'_check_frame',side_effect=frames),
              patch.object(peer,'_ingest',side_effect=results),patch.object(lan,'_send',return_value=10)):
            return peer._pull(remote,'PAGE',{'after':peer._cursors[remote]})

    def page(self,indices,end=None):
        frames=[]
        for index in indices:
            frames.extend({'kind':kind,'payload':payload} for kind,payload in record_frames(
                {'hash':'b'*64,'admission_index':index,'wire':b'public-fixture'}))
        frames.append({'kind':'END','payload':end or {'records':len(indices),'tip':max(indices),'next_wire_bytes':0}})
        return frames

    def test_ram_pending_parent_prevents_acknowledging_later_records_and_is_retried(self):
        # RAM-only labs retain their finite-session/prefix retry semantics.
        # Actual durable deferred scan/GET/reopen is tested in owned_ingress.
        peer,remote=self.peer()
        frames=self.page([1,2])
        self.pull_frames(peer,remote,frames,['PENDING_PARENTS','ADMITTED_UNFINALIZED'])
        self.assertEqual(peer._cursors[remote],0)
        self.assertEqual(peer._peer_sync[remote]['pending_records'],2)
        # Simulate lost RAM orphans. The same authenticated PAGE is requested;
        # a later duplicate cannot hide the formerly missing first record.
        peer._orphans.clear()
        self.pull_frames(peer,remote,frames,['ADMITTED_UNFINALIZED','DUPLICATE'])
        self.assertEqual(peer._cursors[remote],2)
        self.assertEqual(peer._peer_sync[remote]['state'],'CAUGHT_UP')

    def test_jumping_page_and_invalid_end_never_save_a_durable_cursor(self):
        for frames,results in ((self.page([2]),[]),
                               (self.page([1],{'records':1,'tip':0,'next_wire_bytes':0}),['ADMITTED_UNFINALIZED'])):
            peer,remote=self.peer();profile=Mock();peer._profile=profile
            self.addCleanup(lambda peer=peer:setattr(peer,'_profile',None))
            with self.assertRaises(ValueError):self.pull_frames(peer,remote,frames,results)
            profile.save_cursor.assert_not_called();profile.save_scan_page.assert_not_called();self.assertFalse(peer._peer_sync)


if __name__=='__main__':unittest.main()
