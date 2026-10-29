"""Owned, loopback-only Kaspa simnet node and explicit wRPC JSON reads."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from contextlib import closing
import psutil
from backend.application_paths import STATE_ROOT
from backend.platform_process import background_options, process_arguments
from backend.platform_support import terminate_process_tree
from backend.platform_files import is_link
from backend.crypto_contract import write_state_json, read_state_json

VERSION = 'v2.1.0'
BINARY = Path(os.environ.get('GG_KASPAD_BIN', str(STATE_ROOT.parent/'crypto-tools/kaspa'/VERSION/('kaspad.exe' if os.name == 'nt' else 'kaspad'))))
ROOT = STATE_ROOT / 'kaspa-lab'
RPC = 'ws://127.0.0.1:18510'
_LOCK = threading.RLock()
_cache = (0.0, {})
READ_METHODS = {'getServerInfo', 'getInfo', 'getBlockDagInfo', 'getBalanceByAddress', 'getUtxosByAddresses', 'getFeeEstimate', 'getBlockCount'}


def rpc(method, params=None):
    if method not in READ_METHODS:
        raise ValueError('KASPA_READ_ONLY_RPC')
    import websocket
    request_id = uuid.uuid4().int % (2**53-1)
    with closing(websocket.create_connection(RPC, timeout=3, http_proxy_host=None, enable_multithread=True)) as connection:
        connection.send(json.dumps({'id': request_id, 'method': method, 'params': params or {}}))
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            raw = connection.recv()
            if len(raw) > 1024*1024:
                raise ValueError('KASPA_RPC_RESPONSE_LIMIT')
            result = json.loads(raw)
            if str(result.get('id')) != str(request_id):
                continue
            if result.get('error'):
                raise ValueError('KASPA_RPC_ERROR')
            payload = result.get('params', result.get('result'))
            if not isinstance(payload, dict):
                raise ValueError('KASPA_RPC_SCHEMA')
            return payload
    raise ValueError('KASPA_RPC_TIMEOUT')


def _owner():
    try:
        if is_link(ROOT) or is_link(ROOT/'owner.json'):
            return {}
        receipt = read_state_json(ROOT/'owner.json', max_bytes=16384)
        if (receipt.get('binary') != str(BINARY.resolve()) or receipt.get('appdir') != str((ROOT/'node').resolve())
                or type(receipt.get('pid')) is not int or receipt['pid'] <= 0
                or type(receipt.get('created')) not in {int,float} or receipt['created'] <= 0):
            return {}
        return receipt
    except (OSError, ValueError):
        return {}


def running_pid():
    receipt = _owner()
    pid = receipt.get('pid')
    if type(pid) is not int or pid <= 0 or receipt.get('binary') != str(BINARY.resolve()) or receipt.get('appdir') != str((ROOT/'node').resolve()):
        return None
    try:
        process = psutil.Process(pid)
        args = process_arguments(pid)
        if process.create_time() != receipt.get('created') or not args or os.path.normcase(str(Path(args[0]).resolve())) != os.path.normcase(str(BINARY.resolve())):
            return None
        required = {'--simnet', '--nodnsseed', '--disable-upnp', '--rpclisten-json=127.0.0.1:18510', '--listen=127.0.0.1:16511', '--appdir='+str(ROOT/'node')}
        return pid if required.issubset(set(args)) else None
    except (psutil.Error, OSError, ValueError):
        return None


def status(force=False):
    global _cache
    with _LOCK:
        pid = running_pid()
        base = dict(available=BINARY.is_file(), running=pid is not None, owned=pid is not None,
                    healthy=False, backend='kaspad-simnet', label='KASPA LAB OFF', rpc=RPC,
                    network='simnet', version=VERSION, diagnostic='')
        if pid is None:
            return base
        if not force and time.monotonic()-_cache[0] < 5:
            return dict(base, **_cache[1])
        try:
            server = rpc('getServerInfo')
            network = str(server.get('networkId') or '')
            if network != 'simnet':
                raise ValueError('KASPA_WRONG_NETWORK')
            result = dict(healthy=True, label='KASPA SIMNET ON', diagnostic='', server=server)
        except Exception as exc:
            result = dict(healthy=False, label='KASPA LAB STARTING', diagnostic=str(exc) if isinstance(exc, ValueError) else 'KASPA_RPC_UNAVAILABLE')
        _cache = (time.monotonic(), result)
        return dict(base, **result)


def start():
    with _LOCK:
        if running_pid() is not None:
            return status(force=True)
        if not BINARY.is_file():
            raise ValueError('KASPA_NODE_MISSING')
        if is_link(ROOT) or is_link(ROOT/'node'):
            raise ValueError('KASPA_LAB_PATH')
        try:
            rpc('getServerInfo')
        except (OSError, ValueError, ConnectionError):
            pass
        else:
            raise ValueError('KASPA_FOREIGN_RPC')
        ROOT.mkdir(parents=True, exist_ok=True)
        if (ROOT/'node').exists() and not _owner():
            raise ValueError('KASPA_EXISTING_LEDGER_UNOWNED')
        args = [str(BINARY), '--simnet', '--nodnsseed', '--disable-upnp', '--utxoindex',
                '--rpclisten-json=127.0.0.1:18510', '--rpclisten=127.0.0.1:16510', '--listen=127.0.0.1:16511',
                '--appdir='+str(ROOT/'node'), '--async-threads=2', '--ram-scale=0.3']
        with (ROOT/'node.log').open('ab') as log:
            process = subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, **background_options())
        try:
            created = psutil.Process(process.pid).create_time()
            write_state_json(ROOT/'owner.json', dict(pid=process.pid, created=created, binary=str(BINARY.resolve()), appdir=str((ROOT/'node').resolve())))
            deadline = time.monotonic()+20
            while time.monotonic() < deadline and process.poll() is None:
                result = status(force=True)
                if result['healthy']:
                    return result
                time.sleep(0.2)
        except Exception:
            if process.poll() is None:
                process.terminate()
            raise
        return dict(status(force=True), diagnostic='KASPA_NODE_START_TIMEOUT')


def stop():
    global _cache
    with _LOCK:
        pid = running_pid()
        if pid:
            terminate_process_tree(pid)
            try:
                psutil.Process(pid).wait(6)
            except psutil.NoSuchProcess:
                pass
        _cache = (0.0, {})
        return status()
