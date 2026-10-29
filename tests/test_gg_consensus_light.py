"""Real public-certificate WASM verification and bounded loopback viewer tests."""
from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import urlsplit

from backend import gg_consensus_web as web

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'support/gg-consensus'
FLAGS=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
_FIXTURE=None
_FOREIGN_FIXTURE=None


def pack(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def fixture():
    """Generate only public data in a scratch module, using the native Go tests."""
    global _FIXTURE,_FOREIGN_FIXTURE
    if _FIXTURE is not None:return copy.deepcopy(_FIXTURE[0]),_FIXTURE[1]
    spec=importlib.util.spec_from_file_location('gg_light_installer',SOURCE/'install_toolchain.py')
    installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
    executable=installer.TARGET/'go/bin/go.exe'
    if os.name!='nt':executable=Path(shutil.which('go') or '/missing-go')
    if not executable.is_file() or not (installer.TARGET/'verifier.wasm').is_file():
        raise unittest.SkipTest('Explicitly install the pinned GG consensus tools and light verifier first')
    with tempfile.TemporaryDirectory(prefix='gg-public-wasm-fixture-') as directory:
        scratch=Path(directory)
        for path in [SOURCE/'go.mod',SOURCE/'go.sum',*SOURCE.glob('*.go'),SOURCE/'light/fixture_export_test.go']:
            shutil.copyfile(path,scratch/path.name)
        result=subprocess.run([str(executable),'test','-p','2','-mod=readonly','-tags=gg_public_fixture','-run','^TestExportWasmFixture$','-v','.'],
            cwd=scratch,env=installer.build_environment(),capture_output=True,timeout=90,creationflags=FLAGS)
    if result.returncode:raise AssertionError('GG_PUBLIC_FIXTURE_BUILD_FAILED')
    rows=[line.split(b' ',1)[1] for line in result.stdout.splitlines() if line.startswith(b'GG_PUBLIC_FIXTURE ')]
    if len(rows)!=1:raise AssertionError('GG_PUBLIC_FIXTURE_OUTPUT_FAILED')
    _FIXTURE=(json.loads(base64.b64decode(rows[0],validate=True)),installer)
    foreign=[line.split(b' ',1)[1] for line in result.stdout.splitlines() if line.startswith(b'GG_FOREIGN_FIXTURE ')]
    if len(foreign)!=1:raise AssertionError('GG_FOREIGN_FIXTURE_OUTPUT_FAILED')
    _FOREIGN_FIXTURE=json.loads(base64.b64decode(foreign[0],validate=True))
    return copy.deepcopy(_FIXTURE[0]),installer


class PublicFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet,cls.installer=fixture()
        cls.trust={'genesis':cls.packet['genesis'],'genesis_hash':cls.packet['genesis_hash']}


class WasmVerificationTests(PublicFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node=shutil.which('node')
        if not cls.node:raise unittest.SkipTest('Node is required for the real WASM integration tests')

    def verify(self,packet=None,trust=None,raw=None):
        value={'packet':raw if raw is not None else pack(self.packet if packet is None else packet).decode(),
               'trust':self.trust if trust is None else trust}
        result=subprocess.run([self.node,str(SOURCE/'light/node_verify.cjs'),str(self.installer.TARGET),str(web.ASSETS)],
            input=pack(value),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=7,creationflags=FLAGS)
        try:output=json.loads(result.stdout)
        except (ValueError,UnicodeError):raise AssertionError('GG_WASM_TEST_OUTPUT_INVALID') from None
        self.assertEqual(result.returncode,0 if output.get('verified') is True else 1)
        return output

    def test_valid_sdk_certificates_account_witness_and_execution_replay(self):
        output=self.verify()
        self.assertTrue(output['verified'])
        self.assertTrue(output['account_proof_verified'])
        self.assertTrue(output['transaction_inclusion_verified'])
        self.assertTrue(output['execution_status_verified'])
        self.assertEqual((output['state_height'],output['certificate_height']),(1,2))
        self.assertGreater(output['wasm_linear_memory_bytes'],0)
        self.assertEqual(output['verified_account']['balance_atomic'],self.packet['account_proof']['leaf']['balance_atomic'])

    def test_rejects_changed_balance_header_and_merkle_path(self):
        for change in ('balance','header','path'):
            with self.subTest(change=change):
                packet=copy.deepcopy(self.packet)
                if change=='balance':packet['state']['accounts'][0]['balance_atomic']='0'
                if change=='header':packet['signed_header']['header']['height']='9'
                if change=='path':packet['account_proof']['path'][0]['hash']='0'*64
                self.assertFalse(self.verify(packet)['verified'])

    def test_rejects_packet_choosing_its_own_genesis_and_validators(self):
        packet=copy.deepcopy(_FOREIGN_FIXTURE)
        # This really is a valid independently signed four-validator chain.
        # The SDK accepts it when that different genesis is explicitly trusted.
        own={'genesis':packet['genesis'],'genesis_hash':packet['genesis_hash']}
        self.assertTrue(self.verify(packet,trust=own)['verified'])
        result=self.verify(packet)
        self.assertFalse(result['verified'])
        self.assertEqual(result['error'],'GG_PROOF_PIN_MISMATCH')

    def test_old_page_pin_rejects_a_new_session_anchor(self):
        trust=copy.deepcopy(self.trust)
        trust['genesis']['chain_id']='ggnet:'+'c'*24
        trust['genesis_hash']=hashlib.sha256(pack(trust['genesis'])).hexdigest()
        result=self.verify(trust=trust)
        self.assertFalse(result['verified'])
        self.assertEqual(result['error'],'GG_PROOF_PIN_MISMATCH')

    def test_rejects_oversize_duplicate_keys_and_excess_depth_before_wasm(self):
        for raw in (' '*262145, '{"genesis":{},"genesis":{}}', '['*14+'0'+']'*14):
            with self.subTest(case='oversize' if len(raw)>262144 else 'encoding'):
                self.assertFalse(self.verify(raw=raw)['verified'])

    def test_worker_deadline_is_three_seconds_and_always_terminates(self):
        browser=(web.ASSETS/'viewer.js').read_text()
        harness=(SOURCE/'light/node_verify.cjs').read_text()
        self.assertIn('3000)',browser)
        self.assertIn('worker.terminate()',browser)
        self.assertIn('3000)',harness)
        # Execute the real deadline/termination path with a deliberately stalled
        # test worker. No production asset or verifier binary is changed.
        with tempfile.TemporaryDirectory(prefix='gg-wasm-deadline-') as directory:
            scratch=Path(directory)
            shutil.copyfile(SOURCE/'light/node_verify.cjs',scratch/'node_verify.cjs')
            (scratch/'node_worker.cjs').write_text('setInterval(() => {}, 1000);',encoding='utf-8')
            started=time.monotonic()
            result=subprocess.run([self.node,str(scratch/'node_verify.cjs'),'unused','unused'],input=pack({'packet':'{}','trust':{}}),
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,creationflags=FLAGS)
            elapsed=time.monotonic()-started
        self.assertEqual(json.loads(result.stdout)['error'],'GG_PROOF_TIMEOUT')
        self.assertGreaterEqual(elapsed,2.8)
        self.assertLess(elapsed,4.5)


class LoopbackViewerTests(PublicFixture):
    def tearDown(self):
        web.stop()

    def request(self,url,path,method='GET',headers=None):
        parts=urlsplit(url);connection=http.client.HTTPConnection(parts.hostname,parts.port,timeout=3)
        try:
            connection.request(method,path,headers=headers or {})
            response=connection.getresponse();body=response.read(40*1024*1024)
            return response.status,dict(response.getheaders()),body
        finally:connection.close()

    def test_server_pins_public_trust_and_serves_only_allowlisted_resources(self):
        opened=web.start(self.trust)
        self.assertEqual(opened['state'],'RUNNING')
        self.assertTrue(opened['url'].startswith('http://127.0.0.1:'))
        status,headers,body=self.request(opened['url'],'/trust.json')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['genesis_hash'],self.trust['genesis_hash'])
        self.assertIn("'wasm-unsafe-eval'",headers['Content-Security-Policy'])
        self.assertNotIn("'unsafe-inline'",headers['Content-Security-Policy'])
        for path in ('/../AGENTS.md','/%2e%2e/AGENTS.md','/light-manifest.json','/build-manifest.json','/config','/index.html?file=AGENTS.md'):
            with self.subTest(path=path):self.assertEqual(self.request(opened['url'],path)[0],404)
        self.assertEqual(self.request(opened['url'],'/trust.json','POST')[0],405)
        self.assertEqual(self.request(opened['url'],'/trust.json',headers={'Host':'evil.invalid'})[0],403)
        self.assertEqual(self.request(opened['url'],'/trust.json',headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.request(opened['url'],'/verifier.wasm','HEAD')[0],200)

    def test_new_open_uses_new_listener_and_old_trust_copy_stays_unchanged(self):
        first=web.start(self.trust);old=json.loads(self.request(first['url'],'/trust.json')[2])
        changed=copy.deepcopy(self.trust)
        changed['genesis']['chain_id']='ggnet:'+'d'*24
        changed['genesis_hash']=hashlib.sha256(pack(changed['genesis'])).hexdigest()
        second=web.start(changed)
        self.assertNotEqual(first['url'],second['url'])
        self.assertEqual(old['genesis_hash'],self.trust['genesis_hash'])
        self.assertEqual(json.loads(self.request(second['url'],'/trust.json')[2])['genesis_hash'],changed['genesis_hash'])
        stopped=web.stop();self.assertEqual(stopped['state'],'STOPPED')

    def test_rejects_weak_or_modified_session_trust(self):
        for changed in ({}, {'genesis':self.trust['genesis'],'genesis_hash':'0'*64}, {'genesis':{},'genesis_hash':''}):
            with self.subTest(case='invalid'):
                with self.assertRaises(ValueError):web.start(changed)
        self.assertEqual(web.snapshot()['state'],'STOPPED')

    def test_four_connection_cap_rejects_fifth_without_creating_a_worker(self):
        opened=web.start(self.trust);parts=urlsplit(opened['url']);sockets=[]
        try:
            for _ in range(4):
                current=socket.create_connection((parts.hostname,parts.port),timeout=2)
                current.sendall(b'GET / HTTP/1.0\r\n');sockets.append(current)
            deadline=time.monotonic()+1
            while web._server.slots._value and time.monotonic()<deadline:time.sleep(.01)
            extra=socket.create_connection((parts.hostname,parts.port),timeout=2)
            try:self.assertIn(b'503',extra.recv(128))
            finally:extra.close()
        finally:
            for current in sockets:current.close()


if __name__=='__main__':unittest.main()
