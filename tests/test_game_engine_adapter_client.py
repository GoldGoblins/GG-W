"""Complete original command codecs and a bounded, cancellable Qt controller."""
import copy,json,os,re,struct,sys,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_client import NativeClient,GgEngineClient,available
APP=QGuiApplication.instance() or QGuiApplication([])

@unittest.skipUnless(available(),'Verified native client required')
class OriginalCodecs(unittest.TestCase):
    def setUp(self):self.client=NativeClient();self.addCleanup(self.client.close)
    def test_every_original_command_builds_through_the_generated_typed_abi(self):
        catalog=self.client.request('catalog');self.assertEqual(len(catalog['commands']),256)
        records={row['name']:row for row in catalog['records']}
        def shape(fields):
            if isinstance(fields,dict):return {k:value(t) for k,t in fields.items()}
            if isinstance(fields,list):return [value(t) for t in fields]
            return None
        def value(ty):
            ty=re.sub(r'\s+','',ty).removeprefix('&')
            if ty.startswith('Option<'):return None
            if ty.startswith(('Vec<','[')):
                if ';' in ty:
                    inner,count=ty[1:-1].split(';');return [value(inner) for _ in range(int(count))]
                return []
            if ty.startswith('Box<'):return value(ty[4:-1])
            if ty.startswith('('):return [value(t) for t in ty[1:-1].rstrip(',').split(',')]
            if ty in ('String','str'):return 'fixture'
            if ty=='bool':return False
            if ty=='u64':return '1'
            if re.fullmatch(r'[uif]\d+|usize',ty):return 1
            ty=ty.rsplit('::',1)[-1]
            if ty=='ObjectFields':return {'fields':[],'created_as':None}
            record=records[ty]
            if 'variants' in record:
                kind=next(iter(record['variants']));return {'kind':kind,'data':shape(record['variants'][kind])}
            return shape(record['fields'])
        seen=set()
        for command,parameters in catalog['commands']:
            with self.subTest(command=command):
                request={name:value(ty) for name,ty in parameters}
                packets=self.client.request('preview_command',command=command,**request)['packets']
                self.assertTrue(packets)
                for packet in packets:
                    self.assertTrue(0<=packet['opcode']<=65535);self.assertLessEqual(len(packet['body']),65531)
                self.assertNotIn(command,seen);seen.add(command)
        self.assertEqual(len(seen),256)

    def test_packets_match_independent_bytes_including_full_64bit_guids(self):
        guid=2**64-3
        for command,arguments,expected in (
            ('set_active_mover',{'guid':str(guid)},struct.pack('<Q',guid)),
            ('buy_item',{'vendor_guid':str(guid),'entry':42,'count':3},struct.pack('<QIBB',guid,42,3,0)),
            ('repair_item',{'vendor_guid':str(guid),'item_guid':'0'},struct.pack('<QQ',guid,0)),
            ('ping',{'sequence':7,'last_rtt_ms':93},struct.pack('<II',7,93)),
        ):
            with self.subTest(command=command):
                result=self.client.request('preview_command',command=command,**arguments)
                self.assertEqual(bytes(result['packets'][0]['body']),expected)
        with self.assertRaises(ValueError):self.client.request('preview_command',command='set_active_mover',guid=guid)
        with self.assertRaises(ValueError):self.client.request('command',command='logout_request')
        with self.assertRaises(ValueError):self.client.request('preview_command',command='not_an_original_verb')

    def test_original_login_and_weather_packets_decode_with_events_and_tail(self):
        opcode_file=Path(__file__).resolve().parents[1]/'native/engine-formats/crates/engine-protocol/src/messages/opcode.rs'
        source=opcode_file.read_text()
        def opcode(name):return int(re.search(r'pub const '+name+r': u16 = (0x[0-9a-fA-F_]+)',source)[1].replace('_',''),16)
        body=struct.pack('<Iffff',0,1.25,2.5,-3.5,.75)
        decoded=self.client.request('decode_packet',opcode=opcode('SMSG_LOGIN_VERIFY_WORLD'),body=list(body)+[99])
        self.assertEqual(decoded['packet']['kind'],'LoginVerifyWorld');self.assertEqual(decoded['tail_bytes'],1)
        self.assertEqual(decoded['packet']['data']['position']['x'],1.25)
        self.assertTrue(decoded['events'])
        with self.assertRaises(ValueError):self.client.request('decode_packet',opcode=opcode('SMSG_LOGIN_VERIFY_WORLD'),body=[0])
        challenge=bytes(self.client.request('auth_challenge',username='fixture')['bytes'])
        self.assertEqual(challenge[:2],b'\0\3');self.assertTrue(challenge.endswith(b'FIXTURE'))

class Controller(unittest.TestCase):
    def setUp(self):self.client=GgEngineClient();self.addCleanup(self.client.close)
    def test_entity_field_updates_removal_and_byte_limits(self):
        c=self.client;guid=str(2**64-3)
        c._event({'kind':'ObjectCreate','data':{'guid':guid,'fields':{'fields':[[1,2]],'created_as':None}}})
        c._event({'kind':'ObjectValues','data':{'guid':guid,'fields':{'fields':[[1,5],[8,9]]}}})
        self.assertEqual(dict(c.entity(guid)['fields']['fields']),{1:5,8:9})
        self.assertEqual(c.state['entity_bytes'],sum(c._entity_sizes.values()))
        c._event({'kind':'ObjectsRemoved','data':[[guid]]});self.assertEqual(c.state['entity_count'],0)
        blob='x'*700000
        for i in range(32):c._event({'kind':'ObjectCreate','data':{'guid':str(i),'payload':blob}})
        self.assertLessEqual(c.state['entity_bytes'],16*1024*1024);self.assertGreater(c.state['dropped'],0)
        c._event({'kind':'Worldport','data':{}});self.assertEqual(c.state['entity_bytes'],0)
        for i in range(150):c._event({'kind':'view'+str(i),'data':{'payload':'x'*60000}})
        self.assertLessEqual(c.state['view_bytes'],8*1024*1024);self.assertLessEqual(len(c._views),128)

    def test_cancelling_blocked_io_closes_worker_and_invalidates_completion(self):
        arrived=threading.Event();release=threading.Event();workers=[]
        class Worker:
            def __init__(self):self.closed=False;workers.append(self)
            def request(self,op,**kwargs):arrived.set();release.wait(3);return {'phase':'REALMS','realms':[],'characters':[],'queue':None}
            def close(self):self.closed=True;release.set()
        with patch('backend.game_engine_adapter_client.NativeClient',Worker):
            self.assertTrue(self.client.login('127.0.0.1','FIXTURE','SYNTHETIC'))
            self.assertTrue(arrived.wait(2));future=self.client._future;self.client.cancel();future.result(timeout=2)
            self.client._tick();self.assertEqual(self.client.state['phase'],'LOGIN');self.assertTrue(workers[0].closed)
            self.assertIsNone(self.client._future);self.assertIsNone(self.client._queued)

    def test_foreground_action_is_queued_once_while_poll_runs(self):
        from concurrent.futures import Future
        pending=Future();c=self.client;c._future=pending;c._future_op='poll'
        self.assertFalse(c.busy);self.assertTrue(c.command({'command':'query_time'}));self.assertTrue(c.busy)
        self.assertFalse(c.command({'command':'logout_request'}))
        c.cancel();self.assertFalse(c.busy)

if __name__=='__main__':unittest.main()
