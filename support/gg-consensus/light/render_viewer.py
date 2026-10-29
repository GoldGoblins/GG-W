"""Bounded visual test in a fresh, isolated headless Chromium profile.

Uses public synthetic certificate data unless --packet names an explicit public
export. Never opens Firefox, the user's browser profile, or a remote site.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

import websocket
from backend import gg_consensus_web as web
from tests.test_gg_consensus_light import fixture,pack


class CDP:
    def __init__(self,url):
        self.socket=websocket.create_connection(url,timeout=5,suppress_origin=True)
        self.sequence=0

    def call(self,method,params=None,session=None):
        self.sequence+=1;identity=self.sequence
        message={'id':identity,'method':method,'params':params or {}}
        if session:message['sessionId']=session
        self.socket.send(json.dumps(message))
        while True:
            value=json.loads(self.socket.recv())
            if value.get('id')==identity:
                if 'error' in value:raise RuntimeError('GG_ISOLATED_RENDER_COMMAND_FAILED')
                return value.get('result',{})

    def evaluate(self,expression,session):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True},session)
        if result.get('exceptionDetails'):raise RuntimeError('GG_ISOLATED_RENDER_SCRIPT_FAILED')
        return result.get('result',{}).get('value')


def browser_binary():
    for item in [Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),
                 Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),
                 Path(shutil.which('chromium') or '/missing-chromium'),
                 Path(shutil.which('google-chrome') or '/missing-google-chrome')]:
        if item.is_file():return item
    raise RuntimeError('GG_ISOLATED_CHROMIUM_REQUIRED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--width',type=int,default=1180);parser.add_argument('--height',type=int,default=820)
    options=parser.parse_args()
    if not 320<=options.width<=2000 or not 400<=options.height<=1600:raise ValueError('GG_RENDER_DIMENSIONS')
    if options.packet:
        raw=options.packet.read_bytes()
        if len(raw)>262144:raise ValueError('GG_PUBLIC_PACKET_LIMIT')
        packet=json.loads(raw)
    else:packet,_=fixture()
    opened=web.start({'genesis':packet['genesis'],'genesis_hash':packet['genesis_hash']})
    output=options.output or Path(tempfile.mkdtemp(prefix='gg-public-light-view-'))
    output.mkdir(parents=True,exist_ok=True)
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    started=time.monotonic();process=None;cdp=None;status='LOAD_FAILED'
    with tempfile.TemporaryDirectory(prefix='gg-isolated-chromium-') as profile:
        try:
            process=subprocess.Popen([str(browser_binary()),'--headless=new','--disable-gpu','--disable-background-networking',
                '--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check','--disable-extensions',
                '--disable-features=MediaRouter,Translate','--no-proxy-server','--remote-debugging-address=127.0.0.1',
                '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
            descriptor=Path(profile)/'DevToolsActivePort';deadline=time.monotonic()+8
            while not descriptor.is_file():
                if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('GG_ISOLATED_CHROMIUM_START_FAILED')
                time.sleep(.05)
            rows=descriptor.read_text().splitlines();port=int(rows[0])
            cdp=CDP(f'ws://127.0.0.1:{port}'+rows[1])
            target=cdp.call('Target.createTarget',{'url':'about:blank'})['targetId']
            session=cdp.call('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
            cdp.call('Page.enable',session=session)
            cdp.call('Emulation.setDeviceMetricsOverride',{'width':options.width,'height':options.height,'deviceScaleFactor':1,'mobile':False},session)
            cdp.call('Page.navigate',{'url':opened['url']},session)
            deadline=time.monotonic()+8
            while cdp.evaluate("document.getElementById('verify')?.disabled === false",session) is not True:
                if time.monotonic()>deadline:raise RuntimeError('GG_ISOLATED_TRUST_LOAD_TIMEOUT')
                time.sleep(.05)
            script="document.getElementById('packet').value="+json.dumps(pack(packet).decode())+";document.getElementById('packet').dispatchEvent(new Event('input'));document.getElementById('verify').click();"
            cdp.evaluate(script,session);deadline=time.monotonic()+5
            while True:
                status=cdp.evaluate("document.getElementById('result-status').textContent",session)
                if status in ('Godkänd','Avvisad'):break
                if time.monotonic()>deadline:raise RuntimeError('GG_ISOLATED_VERIFY_TIMEOUT')
                time.sleep(.05)
            details=cdp.evaluate("({title:document.getElementById('result-title').textContent,elapsed:document.getElementById('elapsed').textContent,details:document.getElementById('result-details').innerText})",session)
            image=cdp.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False},session)['data']
            filename=output/f'viewer-verified-{options.width}.png';filename.write_bytes(base64.b64decode(image,validate=True))
            print(json.dumps({'status':status,'screenshot':str(filename),'result':details,'elapsed_seconds':round(time.monotonic()-started,3)},ensure_ascii=False),flush=True)
        finally:
            if cdp:
                try:cdp.call('Browser.close')
                except Exception:pass
                cdp.socket.close()
            if process:
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
            web.stop()
    return 0 if status=='Godkänd' else 1


if __name__=='__main__':raise SystemExit(main())
