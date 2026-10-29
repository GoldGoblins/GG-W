"""Owned, ephemeral Hardhat devnet. Never accepts a remote endpoint or real key.

This is an EVM development chain, not GG production consensus. Every node
account is generated for this process and destroyed on stop. Raw Hardhat
output (which can contain development keys) is discarded at its source.
"""
from __future__ import annotations

import atexit
from collections import deque
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import psutil

from backend.application_paths import PROJECT_ROOT, TOOLS_ROOT
from backend import omni_assets as amounts
from backend.gg_block_graph import BlockHistory, FETCH_LIMIT, LIVE_HISTORY_LIMIT, evm_block

CHAIN_ID = 31337
CHAIN = 'eip155:31337'
SYMBOL = 'GG-TEST'
GAS_SYMBOL = 'DEV'
SUPPLY = 1_000_000 * 10**6
ACCOUNT_COUNT = 4
MAX_TRANSACTIONS = 256
BLOCK_INTERVAL_MS = 10
OBSERVATION_INTERVAL_MS = 1000 / 75
TOOLCHAIN = TOOLS_ROOT / 'gg-testnet'
SOURCES = PROJECT_ROOT / 'support/gg-testnet'
LOCK = threading.RLock()
_process = None
_process_lease = None
_port = 0
_session = ''
_genesis = ''
_accounts = []
_contract = ''
_review = None
_transactions = deque(maxlen=64)
_measurements = deque(maxlen=32)
_events = deque(maxlen=48)
_count = 0
_last_test = None
_last_error = ''
_cached = {}
_request_id = 0
_closed = False
_stop_requested = threading.Event()
_identity_valid = False
_connection = None
_connection_owner = None
_rpc_stats = {'requests':0,'members':0,'batches':0}
_block_history = BlockHistory('Hardhat 3', history_limit=LIVE_HISTORY_LIMIT)
RPC_METHODS = frozenset({'eth_chainId','eth_accounts','eth_getBlockByNumber','eth_getCode','eth_getBalance',
                         'eth_call','eth_getTransactionReceipt','eth_estimateGas','eth_sendTransaction',
                         'eth_getTransactionCount','eth_gasPrice'})
RPC_READ_METHODS = RPC_METHODS - {'eth_sendTransaction'}
MAX_RPC_BATCH = 32


def _event(kind, message):
    _events.appendleft({'ts': time.time(), 'kind': kind, 'message': message})


def _probe_start():
    return time.perf_counter(),dict(_rpc_stats)


def _measurement(operation, started, state, block_height=None, block_hash=None):
    began,counters=started
    _measurements.append({'operation': operation, 'elapsed_ms': round((time.perf_counter()-began)*1000, 3),
                          'observed_at': time.time(), 'state': state,
                          **{'rpc_'+name:_rpc_stats[name]-counters[name] for name in counters},
                          'block_height':block_height,'block_hash':block_hash})


def _alive():
    return _process is not None and _process.poll() is None


def _disconnect_rpc():
    global _connection,_connection_owner
    connection=_connection;_connection=None;_connection_owner=None
    if connection is not None:
        try:connection.close()
        except OSError:pass


def _next_request(method,params):
    global _request_id
    if _closed:
        raise ValueError('GG_TESTNET_SHUTTING_DOWN')
    if not isinstance(method,str) or method not in RPC_METHODS:
        raise ValueError('GG_TESTNET_RPC_METHOD_FORBIDDEN')
    if params is not None and not isinstance(params,list):
        raise ValueError('GG_TESTNET_RPC_PARAMS')
    if not _alive() or not _port:
        raise ValueError('GG_TESTNET_STOPPED')
    _request_id += 1
    return {'jsonrpc':'2.0','id':_request_id,'method':method,'params':params or []}


def _exchange_rpc(payload):
    """One attempt on a session-owned connection. Never resends after failure."""
    global _connection,_connection_owner
    raw = json.dumps(payload,
                     separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 65536:
        raise ValueError('GG_TESTNET_REQUEST_LIMIT')
    owner=(id(_process),_port,_session)
    if _connection is None or _connection_owner!=owner:
        _disconnect_rpc()
        _connection=http.client.HTTPConnection('127.0.0.1',_port,timeout=3)
        _connection_owner=owner
    count=len(payload) if isinstance(payload,list) else 1
    _rpc_stats['requests']+=1;_rpc_stats['members']+=count
    if isinstance(payload,list):_rpc_stats['batches']+=1
    try:
        _connection.request('POST', '/', body=raw, headers={'Content-Type': 'application/json', 'Host': '127.0.0.1'})
        response = _connection.getresponse()
        body = response.read(1024*1024+1)
        if response.status != 200 or len(body) > 1024*1024:
            raise ValueError('GG_TESTNET_RPC_RESPONSE')
        def reject_constant(_value):
            raise ValueError('GG_TESTNET_RPC_RESPONSE')
        def unique_object(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('GG_TESTNET_RPC_RESPONSE')
                result[key]=value
            return result
        return json.loads(body,parse_constant=reject_constant,object_pairs_hook=unique_object)
    except Exception:
        _disconnect_rpc()
        raise


def _rpc_result(result,identifier):
    if (not isinstance(result,dict) or type(result.get('id')) is not int or result['id']!=identifier
        or result.get('jsonrpc')!='2.0'):
        raise ValueError('GG_TESTNET_RPC_RESPONSE')
    if 'error' in result:
        # Provider text, requests and credentials never propagate to UI or logs.
        raise ValueError('GG_TESTNET_RPC_REJECTED')
    if set(result)!={'jsonrpc','id','result'}:
        raise ValueError('GG_TESTNET_RPC_RESPONSE')
    return result['result']


def _rpc(method, params=None):
    """One bounded owned-loopback request, including the sole write method."""
    with LOCK:
        request=_next_request(method,params)
        try:
            return _rpc_result(_exchange_rpc(request),request['id'])
        except Exception:
            _disconnect_rpc()
            raise


def _rpc_batch(calls):
    """Correlated read-only batch. Any malformed member fails the whole read."""
    with LOCK:
        if _closed:
            raise ValueError('GG_TESTNET_SHUTTING_DOWN')
        if not isinstance(calls,(list,tuple)) or not 1<=len(calls)<=MAX_RPC_BATCH:
            raise ValueError('GG_TESTNET_BATCH_LIMIT')
        for call in calls:
            if (not isinstance(call,(list,tuple)) or len(call)!=2 or not isinstance(call[0],str)
                or call[0] not in RPC_READ_METHODS):
                raise ValueError('GG_TESTNET_BATCH_READ_ONLY')
        requests=[_next_request(method,params) for method,params in calls]
        try:
            results=_exchange_rpc(requests)
            if not isinstance(results,list) or len(results)!=len(requests):
                raise ValueError('GG_TESTNET_BATCH_RESPONSE')
            expected={request['id'] for request in requests};ordered={}
            for result in results:
                identifier=result.get('id') if isinstance(result,dict) else None
                if type(identifier) is not int or identifier not in expected or identifier in ordered:
                    raise ValueError('GG_TESTNET_BATCH_RESPONSE')
                ordered[identifier]=_rpc_result(result,identifier)
            if set(ordered)!=expected:
                raise ValueError('GG_TESTNET_BATCH_RESPONSE')
            return [ordered[request['id']] for request in requests]
        except Exception:
            _disconnect_rpc()
            raise


def _quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,64}', value):
        raise ValueError('GG_TESTNET_RPC_QUANTITY')
    return int(value, 16)


def _address(value):
    return amounts.evm_address(value)


def _artifact():
    path = SOURCES / 'GGTestToken.json'
    if not path.is_file() or path.stat().st_size > 128*1024:
        raise ValueError('GG_TESTNET_ARTIFACT_MISSING')
    value = json.loads(path.read_text(encoding='utf-8'))
    for name in ('bytecode', 'deployedBytecode'):
        if not isinstance(value.get(name), str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){1,48000}', value[name]):
            raise ValueError('GG_TESTNET_ARTIFACT_INVALID')
    if value.get('contractName') != 'GGTestToken':
        raise ValueError('GG_TESTNET_ARTIFACT_INVALID')
    return value


def available():
    return bool(shutil.which('node') and (TOOLCHAIN/'node_modules/hardhat/dist/src/cli.js').is_file()
                and (SOURCES/'hardhat.config.ts').is_file() and (SOURCES/'GGTestToken.json').is_file())


def _owns_listener():
    if not _alive():
        return False
    try:
        return any(c.status == psutil.CONN_LISTEN and c.laddr.ip == '127.0.0.1' and c.laddr.port == _port
                   for c in psutil.Process(_process.pid).net_connections(kind='tcp'))
    except (psutil.Error, OSError):
        return False


def _identity(include_tip=False):
    if not _owns_listener():
        raise ValueError('GG_TESTNET_LISTENER_NOT_OWNED')
    calls=[('eth_chainId',[]),('eth_getBlockByNumber',['0x0',False]),('eth_accounts',[])]
    if _contract:calls.append(('eth_getCode',[_contract,'latest']))
    if include_tip:calls.append(('eth_getBlockByNumber',['latest',False]))
    results=_rpc_batch(calls)
    if _quantity(results[0]) != CHAIN_ID:
        raise ValueError('GG_TESTNET_WRONG_CHAIN')
    block=results[1]
    if not isinstance(results[2],list):
        raise ValueError('GG_TESTNET_SESSION_CHANGED')
    addresses=[_address(a) for a in results[2]]
    if not isinstance(block, dict) or block.get('hash') != _genesis or addresses != _accounts:
        raise ValueError('GG_TESTNET_SESSION_CHANGED')
    if _contract and (not isinstance(results[3],str) or results[3].lower()!=_artifact()['deployedBytecode'].lower()):
        raise ValueError('GG_TESTNET_CONTRACT_CHANGED')
    if include_tip:
        tip=results[-1]
        if (not isinstance(tip,dict) or not isinstance(tip.get('hash'),str)
            or not re.fullmatch(r'0x[0-9a-fA-F]{64}',tip['hash'])):
            raise ValueError('GG_TESTNET_BLOCK_HEADER')
        _quantity(tip.get('number'))
        return tip


def start():
    global _process, _process_lease, _port, _session, _genesis, _accounts, _contract, _review, _count, _last_test, _last_error, _cached
    with LOCK:
        if _closed:
            raise ValueError('GG_TESTNET_SHUTTING_DOWN')
        _stop_requested.clear()
        if _alive():
            _identity()
            return snapshot()
        stop()
        if not available():
            raise ValueError('GG_TESTNET_TOOLCHAIN_REQUIRED')
        _rpc_stats.update(requests=0,members=0,batches=0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        # Keys exist only in this launch environment and in the owned dev node.
        accounts = [{'privateKey': '0x'+secrets.token_hex(32), 'balance': str(10000*10**18)} for _ in range(ACCOUNT_COUNT)]
        # A new, small environment; application credentials never travel here.
        allowed_environment = {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT','TEMP','TMP',
                               'USERPROFILE','HOME','LOCALAPPDATA','APPDATA','LANG','LC_ALL'}
        environment = {name: value for name, value in os.environ.items() if name.upper() in allowed_environment}
        environment['GG_TESTNET_ACCOUNTS'] = json.dumps(accounts, separators=(',', ':'))
        environment['HARDHAT_DISABLE_TELEMETRY_PROMPT'] = 'true'
        environment['HARDHAT_TELEMETRY_DISABLED'] = 'true'
        # This canonical configuration contains plain JavaScript only. Import
        # the runtime copy as native ESM: a .ts import can spawn TSX/esbuild on
        # a cold cache, which the one-process Windows Job correctly forbids.
        # No compiler child or relaxed process budget is needed for this node.
        shutil.copyfile(SOURCES/'hardhat.config.ts', TOOLCHAIN/'hardhat.config.mjs')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        command = [shutil.which('node'), '--max-old-space-size=256', str(TOOLCHAIN/'node_modules/hardhat/dist/src/cli.js'), 'node',
                   '--config', str(TOOLCHAIN/'hardhat.config.mjs'), '--network', 'ggtest',
                   '--hostname', '127.0.0.1', '--port', str(port)]
        try:
            _process = subprocess.Popen(command, cwd=TOOLCHAIN, env=environment, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            from backend.gg_testnet_process import contain
            _process_lease = contain(_process)
            _port = port
        finally:
            environment.pop('GG_TESTNET_ACCOUNTS', None)
            accounts.clear()
        deadline = time.monotonic()+20
        try:
            while True:
                if _stop_requested.is_set():
                    raise ValueError('GG_TESTNET_START_CANCELLED')
                if not _alive():
                    raise ValueError('GG_TESTNET_START_FAILED')
                if not _owns_listener():
                    if time.monotonic() >= deadline:
                        raise ValueError('GG_TESTNET_START_TIMEOUT')
                    time.sleep(.1)
                    continue
                try:
                    if _quantity(_rpc('eth_chainId')) != CHAIN_ID:
                        raise ValueError('GG_TESTNET_WRONG_CHAIN')
                    break
                except (OSError, http.client.HTTPException):
                    if time.monotonic() >= deadline:
                        raise ValueError('GG_TESTNET_START_TIMEOUT') from None
                    time.sleep(.1)
            addresses = [_address(a) for a in _rpc('eth_accounts')]
            if len(addresses) != ACCOUNT_COUNT or len(set(addresses)) != ACCOUNT_COUNT:
                raise ValueError('GG_TESTNET_ACCOUNTS')
            _accounts = addresses
            _genesis = _rpc('eth_getBlockByNumber', ['0x0', False])['hash']
            _session = secrets.token_hex(16)
            _block_history.reset(_session)
            _contract = ''; _review = None; _count = 0; _last_test = None; _last_error = ''; _cached = {}
            _transactions.clear(); _measurements.clear(); _events.clear()
            _identity()
            if _stop_requested.is_set():
                raise ValueError('GG_TESTNET_START_CANCELLED')
            _event('STARTED', 'Hardhat startad · endast loopback · fyra tillfälliga testkonton')
            return snapshot()
        except Exception:
            stop()
            raise


def request_stop():
    """Interrupt only our owned child without waiting for the busy RPC lock.

    Cleanup remains in stop(). Killing the owned process makes an in-flight
    HTTP read finish/fail, so stop is not starved by repeated observations.
    """
    _stop_requested.set()
    process = _process
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            if process.poll() is None:
                raise ValueError('GG_TESTNET_STOP_INTERRUPT_FAILED') from None


def stop():
    global _process, _process_lease, _port, _review, _last_error, _identity_valid
    with LOCK:
        _identity_valid = False
        process = _process; _process = None; _port = 0; _review = None
        _disconnect_rpc()
        lease = _process_lease; _process_lease = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
                _event('STOPPED', 'Testnoden stoppad · testnycklar och nodtillstånd kastade')
        finally:
            if lease is not None:
                lease.close()
        _last_error = ''
        _block_history.reset('')
        return {'state': 'STOPPED'}


def shutdown():
    """Terminal application exit fence, including already-dequeued UI work."""
    global _closed
    _closed = True
    request_stop()
    return stop()


def _balance(address, token=False):
    if not token:
        return _quantity(_rpc('eth_getBalance', [address, 'latest']))
    if not _contract:
        return None
    data = '0x70a08231'+address[2:].rjust(64, '0')
    return _quantity(_rpc('eth_call', [{'to': _contract, 'data': data}, 'latest']))


def _account_snapshots(tip):
    """Read every account against one canonical block, never mixed `latest`s."""
    tag=tip['number'];calls=[]
    for address in _accounts:
        calls.extend([('eth_getBalance',[address,tag]),('eth_getTransactionCount',[address,tag])])
        if _contract:
            calls.append(('eth_call',[{'to':_contract,'data':'0x70a08231'+address[2:].rjust(64,'0')},tag]))
    if _contract:calls.append(('eth_getCode',[_contract,tag]))
    values=_rpc_batch(calls);step=3 if _contract else 2;rows=[]
    for index,address in enumerate(_accounts):
        start=index*step
        rows.append({'index':index,'address':address,'native':amounts.format_atomic(_quantity(values[start]),18),
                     'nonce':_quantity(values[start+1]),
                     'token':amounts.format_atomic(_quantity(values[start+2]),6) if _contract else None})
    if _contract and (not isinstance(values[-1],str) or values[-1].lower()!=_artifact()['deployedBytecode'].lower()):
        raise ValueError('GG_TESTNET_CONTRACT_CHANGED')
    checkpoint=_rpc('eth_getBlockByNumber',[tag,False])
    if not isinstance(checkpoint,dict) or checkpoint.get('hash')!=tip['hash']:
        raise ValueError('GG_TESTNET_CHECKPOINT_CHANGED')
    return rows


def _resource_metrics():
    result = {'memory_committed_bytes':None,'memory_resident_bytes':None,'cpu_seconds':None}
    if _process is None or not _alive():
        return result
    try:
        process = psutil.Process(_process.pid)
        memory = process.memory_info(); cpu = process.cpu_times()
        result.update(memory_committed_bytes=getattr(memory,'private',None),memory_resident_bytes=memory.rss,
                      cpu_seconds=round(cpu.user+cpu.system,3))
    except (psutil.Error,OSError):
        pass
    return result


def _block_graph(latest):
    """Read at most7 older headers; no RPC timer or external endpoint."""
    if _block_history.session!=_session:_block_history.reset(_session)
    try:
        tip=evm_block(latest)
        missing=[h for h in _block_history.wanted(tip['height']) if h!=tip['height']][:FETCH_LIMIT-1]
        older=_rpc_batch([('eth_getBlockByNumber',[hex(height),False]) for height in missing]) if missing else []
        rows=[tip]+[evm_block(value) for value in older]
        if [row['height'] for row in rows[1:]]!=missing:raise ValueError('GG_BLOCK_GRAPH_HEIGHT')
        _block_history.ingest(rows,tip['height'],tip['hash'])
    except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):
        _block_history.fail()
    return _block_history.snapshot(_transactions,ttf_basis='API_SUBMISSION_TO_RECEIPT')


def _receipt(txid):
    if not isinstance(txid, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', txid):
        raise ValueError('GG_TESTNET_TX_ID')
    result = _rpc('eth_getTransactionReceipt', [txid])
    if result is None:
        return None
    if not isinstance(result, dict) or result.get('transactionHash', '').lower() != txid.lower():
        raise ValueError('GG_TESTNET_RECEIPT_IDENTITY')
    block = _rpc('eth_getBlockByNumber', [result['blockNumber'], False])
    if not block or result.get('blockHash') != block.get('hash') or txid.lower() not in [t.lower() for t in block.get('transactions', [])]:
        raise ValueError('GG_TESTNET_RECEIPT_BLOCK')
    return result


def _broadcast(transaction, description):
    global _count
    if _count >= MAX_TRANSACTIONS:
        raise ValueError('GG_TESTNET_TRANSACTION_LIMIT')
    if any(row['state'] in {'BROADCAST_UNKNOWN', 'PENDING'} for row in _transactions):
        raise ValueError('GG_TESTNET_UNRESOLVED_TRANSACTION')
    # Consume this local operation before the RPC. An ambiguous response never retries.
    _count += 1
    record = dict(description, txid='', state='BROADCAST_UNKNOWN', observed_at=time.time(), block=None, gas_used=None)
    _transactions.appendleft(record)
    started = _probe_start()
    try:
        record['txid'] = _rpc('eth_sendTransaction', [transaction])
        record['state'] = 'PENDING'
        receipt = _receipt(record['txid'])
        if receipt is not None:
            record.update(state='CONFIRMED' if _quantity(receipt['status']) == 1 else 'REVERTED',
                          block=_quantity(receipt['blockNumber']), gas_used=str(_quantity(receipt['gasUsed'])),
                          block_hash=receipt.get('blockHash'),elapsed_ms=round((time.perf_counter()-started[0])*1000,3))
        _event(record['state'], description['kind']+' · '+str(description.get('amount', ''))+' '+description.get('symbol', ''))
        return receipt
    finally:
        _measurement('transaction', started, record['state'],record.get('block'),record.get('block_hash'))


def deploy_token():
    global _contract, _review
    with LOCK:
        _identity()
        if _contract:
            return snapshot()
        _review = None
        artifact = _artifact()
        transaction = {'from': _accounts[0], 'data': artifact['bytecode'], 'value': '0x0'}
        estimate = _quantity(_rpc('eth_estimateGas', [transaction]))
        if estimate > 2_000_000:
            raise ValueError('GG_TESTNET_DEPLOY_GAS_LIMIT')
        transaction['gas'] = hex(estimate+estimate//5+1000)
        receipt = _broadcast(transaction, {'kind': 'DEPLOY', 'amount': '1000000', 'symbol': SYMBOL,
                                          'sender': _accounts[0], 'recipient': '', 'asset': 'GG-TEST'})
        if receipt is None or _quantity(receipt['status']) != 1:
            raise ValueError('GG_TESTNET_DEPLOY_UNCONFIRMED')
        contract = _address(receipt['contractAddress'])
        if _rpc('eth_getCode', [contract, 'latest']).lower() != artifact['deployedBytecode'].lower():
            raise ValueError('GG_TESTNET_BYTECODE_MISMATCH')
        _contract = contract
        if _quantity(_rpc('eth_call', [{'to': contract, 'data': '0x18160ddd'}, 'latest'])) != SUPPLY:
            _contract = ''; raise ValueError('GG_TESTNET_SUPPLY_MISMATCH')
        if _quantity(_rpc('eth_call', [{'to': contract, 'data': '0x313ce567'}, 'latest'])) != 6:
            _contract = ''; raise ValueError('GG_TESTNET_DECIMALS_MISMATCH')
        _event('TOKEN_READY', 'GG-TEST deployad och bytekod kontrollerad · fast testutbud')
        return snapshot()


def prepare(sender, recipient, amount, asset='GG-TEST'):
    global _review
    with LOCK:
        _review = None
        _identity()
        if type(sender) is not int or sender not in range(ACCOUNT_COUNT) or asset not in {'GG-TEST', 'NATIVE'}:
            raise ValueError('GG_TESTNET_TRANSFER_CONTEXT')
        target = _address(recipient)
        source = _accounts[sender]
        if target == source or target == '0x'+'0'*40:
            raise ValueError('GG_TESTNET_RECIPIENT')
        atomic = amounts.amount_atomic(amount, 6 if asset == 'GG-TEST' else 18)
        if atomic <= 0:
            raise ValueError('GG_TESTNET_AMOUNT')
        if asset == 'GG-TEST' and not _contract:
            raise ValueError('GG_TESTNET_DEPLOY_FIRST')
        if atomic > _balance(source, asset == 'GG-TEST'):
            raise ValueError('GG_TESTNET_INSUFFICIENT_FUNDS')
        nonce = _quantity(_rpc('eth_getTransactionCount', [source, 'pending']))
        transaction = {'from': source, 'to': target, 'value': hex(atomic)}
        if asset == 'GG-TEST':
            transaction.update(to=_contract, value='0x0', data='0xa9059cbb'+target[2:].rjust(64, '0')+hex(atomic)[2:].rjust(64, '0'))
        gas = _quantity(_rpc('eth_estimateGas', [transaction]))
        gas = gas+gas//5+1000
        if gas > 300_000:
            raise ValueError('GG_TESTNET_TRANSFER_GAS_LIMIT')
        price = _quantity(_rpc('eth_gasPrice'))
        if price > 10**12:
            raise ValueError('GG_TESTNET_GAS_PRICE_LIMIT')
        if _balance(source) < gas*price+(atomic if asset == 'NATIVE' else 0):
            raise ValueError('GG_TESTNET_GAS_FUNDS')
        transaction.update(gas=hex(gas), gasPrice=hex(price), nonce=hex(nonce), chainId=hex(CHAIN_ID))
        review = {'id': secrets.token_hex(16), 'session': _session, 'chain_id': CHAIN, 'sender_index': sender,
                  'sender': source, 'recipient': target, 'asset': asset, 'symbol': SYMBOL if asset == 'GG-TEST' else GAS_SYMBOL,
                  'amount': amounts.format_atomic(atomic, 6 if asset == 'GG-TEST' else 18), 'atomic': str(atomic),
                  'contract': _contract if asset == 'GG-TEST' else '', 'nonce': nonce, 'gas_limit': gas,
                  'gas_price_atomic': str(price), 'max_fee': amounts.format_atomic(gas*price, 18),
                  'expires_at': time.time()+120, 'transaction': transaction}
        review['review_digest'] = hashlib.sha256(amounts.pack(review).encode()).hexdigest()
        _review = review
        return snapshot()


def cancel_review():
    global _review
    with LOCK:
        _review = None


def send(identifier, review_digest):
    global _review
    with LOCK:
        review = _review
        if not review or review.get('id') != identifier or review.get('review_digest') != review_digest:
            raise ValueError('GG_TESTNET_REVIEW_REQUIRED')
        # One shot even if identity, nonce, transport or receipt checking fails.
        _review = None
        expected = hashlib.sha256(amounts.pack({k:v for k,v in review.items() if k!='review_digest'}).encode()).hexdigest()
        if not secrets.compare_digest(expected, str(review_digest)):
            raise ValueError('GG_TESTNET_REVIEW_CHANGED')
        _identity()
        if review['session'] != _session or time.time() > review['expires_at']:
            raise ValueError('GG_TESTNET_REVIEW_EXPIRED')
        if _quantity(_rpc('eth_getTransactionCount', [review['sender'], 'pending'])) != review['nonce']:
            raise ValueError('GG_TESTNET_NONCE_CHANGED')
        transaction = review['transaction']
        if _balance(review['sender']) < review['gas_limit']*int(review['gas_price_atomic'])+(int(review['atomic']) if review['asset'] == 'NATIVE' else 0):
            raise ValueError('GG_TESTNET_GAS_FUNDS')
        if review['asset'] == 'GG-TEST' and _balance(review['sender'], True) < int(review['atomic']):
            raise ValueError('GG_TESTNET_INSUFFICIENT_FUNDS')
        receipt = _broadcast(transaction, {k: review[k] for k in ('sender', 'recipient', 'asset', 'symbol', 'amount')} | {'kind': 'TRANSFER'})
        if receipt is not None and _quantity(receipt['status']) != 1:
            raise ValueError('GG_TESTNET_TRANSFER_REVERTED')
        return snapshot()


def self_test():
    """Bounded real JSON-RPC round trips, solely between this session's accounts."""
    global _last_test, _review
    with LOCK:
        _identity()
        _review = None
        if _count > MAX_TRANSACTIONS-5:
            raise ValueError('GG_TESTNET_TRANSACTION_LIMIT')
        if not _contract:
            deploy_token()
        before = [_balance(a, True) for a in _accounts]
        started = _probe_start()
        _last_test = {'state': 'RUNNING', 'checks': [], 'observed_at': time.time()}
        try:
            for asset, quantity in [('GG-TEST', '10'), ('NATIVE', '0.01')]:
                for source, target in [(0, 1), (1, 0)]:
                    native_before = [_balance(_accounts[i]) for i in (source, target)]
                    token_before = [_balance(_accounts[i], True) for i in (source, target)]
                    prepare(source, _accounts[target], quantity, asset)
                    review = dict(_review)
                    send(review['id'], review['review_digest'])
                    if not _transactions or _transactions[0]['state'] != 'CONFIRMED':
                        raise ValueError('GG_TESTNET_SELF_TEST_UNCONFIRMED')
                    receipt = _receipt(_transactions[0]['txid'])
                    fee = _quantity(receipt['gasUsed'])*_quantity(receipt['effectiveGasPrice'])
                    native_delta = amounts.amount_atomic(quantity,18) if asset=='NATIVE' else 0
                    if [_balance(_accounts[i]) for i in (source,target)] != [native_before[0]-native_delta-fee,native_before[1]+native_delta]:
                        raise ValueError('GG_TESTNET_SELF_TEST_NATIVE_BALANCE')
                    token_delta = amounts.amount_atomic(quantity,6) if asset=='GG-TEST' else 0
                    if [_balance(_accounts[i],True) for i in (source,target)] != [token_before[0]-token_delta,token_before[1]+token_delta]:
                        raise ValueError('GG_TESTNET_SELF_TEST_TOKEN_BALANCE')
                    _last_test['checks'].append({'asset': asset, 'from': source, 'to': target, 'state': 'PASS',
                                                 'txid': _transactions[0]['txid'], 'gas_used': _transactions[0]['gas_used']})
            if [_balance(a, True) for a in _accounts] != before:
                raise ValueError('GG_TESTNET_SELF_TEST_BALANCE')
            total = _quantity(_rpc('eth_call', [{'to': _contract, 'data': '0x18160ddd'}, 'latest']))
            if total != SUPPLY:
                raise ValueError('GG_TESTNET_SUPPLY_MISMATCH')
            _last_test.update(state='PASS', token_balances_restored=True, supply_verified=True)
            _event('SELF_TEST_PASS', 'Token och native skickade fram och tillbaka · fyra blockkvitton kontrollerade')
        except Exception:
            _last_test['state'] = 'FAIL'
            raise
        finally:
            _measurement('self_test', started, _last_test['state'])
        return snapshot()


def snapshot():
    global _last_error, _cached, _review, _identity_valid
    with LOCK:
        base = {'state': 'STOPPED', 'available': available(), 'engine': 'Hardhat 3', 'chain_id': CHAIN,
                'chain_number': CHAIN_ID, 'binding': 'LOOPBACK_ONLY', 'purpose': 'EPHEMERAL_EVM_DEVELOPMENT',
                'native_symbol': GAS_SYMBOL, 'symbol': SYMBOL, 'decimals': 6, 'production': False,
                'block_interval_target_ms': BLOCK_INTERVAL_MS, 'observation_interval_ms': OBSERVATION_INTERVAL_MS, 'mining_mode':'AUTOMINE_AND_INTERVAL',
                'rpc_url': '', 'accounts': [], 'contract': '', 'height': None, 'peer_count': 0,
                'session_transactions': _count, 'transaction_limit': MAX_TRANSACTIONS, 'review': None,
                'transactions': list(_transactions), 'measurements': list(_measurements),
                'events': list(_events), 'last_test': _last_test, 'error': '',
                'resource_limits': dict(_process_lease.facts) if _process_lease else {},
                'resource_metrics': _resource_metrics(),
                'rpc_totals': dict(_rpc_stats),
                'observation_at':time.time(),
                'block_graph':_block_history.snapshot(_transactions,ttf_basis='API_SUBMISSION_TO_RECEIPT',stale=not _alive()),
                'unresolved': any(t['state'] in {'BROADCAST_UNKNOWN','PENDING'} for t in _transactions)}
        if not _alive():
            _review = None
            return base
        started = _probe_start()
        try:
            latest = _identity(include_tip=True)
            resolved=False
            for record in _transactions:
                if record['state'] == 'PENDING' and record['txid']:
                    receipt = _receipt(record['txid'])
                    if receipt is not None:
                        record.update(state='CONFIRMED' if _quantity(receipt['status']) == 1 else 'REVERTED',
                                      block=_quantity(receipt['blockNumber']), gas_used=str(_quantity(receipt['gasUsed'])))
                        resolved=True
            # A receipt may have landed after the first tip read. Refresh the
            # anchor before reading balances so its block is included too.
            if resolved:latest=_identity(include_tip=True)
            balances = _account_snapshots(latest)
            _identity_valid = True
            if _review and time.time() > _review['expires_at']:
                _review = None
            base.update(state='RUNNING', rpc_url='http://127.0.0.1:'+str(_port), session=_session,
                        accounts=balances, contract=_contract, height=_quantity(latest['number']),
                        gas_used=str(_quantity(latest['gasUsed'])), gas_limit=str(_quantity(latest['gasLimit'])),
                        base_fee_atomic=str(_quantity(latest.get('baseFeePerGas', '0x0'))),
                        block_timestamp=_quantity(latest['timestamp']),
                        review={k: v for k, v in _review.items() if k != 'transaction'} if _review else None)
            base['block_graph']=_block_graph(latest)
            _last_error = ''; _cached = {k: base[k] for k in ('accounts', 'height', 'contract', 'gas_used', 'gas_limit', 'base_fee_atomic')}
            _measurement('rpc', started, 'PASS',_quantity(latest['number']),latest['hash'])
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            _identity_valid = False
            _last_error = 'GG_TESTNET_READ_FAILED'
            _review = None
            base.update(_cached)
            base.update(state='READ_FAILED', rpc_url='http://127.0.0.1:'+str(_port), error=_last_error, review=None)
            base['block_graph']=_block_history.snapshot(_transactions,ttf_basis='API_SUBMISSION_TO_RECEIPT',stale=True)
            _measurement('rpc', started, 'FAIL')
        base['measurements'] = list(_measurements)
        base['rpc_totals'] = dict(_rpc_stats)
        base['unresolved'] = any(t['state'] in {'BROADCAST_UNKNOWN','PENDING'} for t in _transactions)
        return base


def telemetry_snapshot():
    """One actual lightweight loopback read; never starts or transfers anything.

    Ownership/genesis/account identity is checked by start and normal snapshots.
    The already-owned HTTP connection is serialized by LOCK. A changed/malformed
    checkpoint fails closed; only real parent headers enter the bounded graph.
    """
    if not LOCK.acquire(blocking=False):
        return None  # An actual transfer/read already owns the single RPC lane.
    try:
        if not _alive():
            return {'network_page':'TESTNET', 'revision':(_session, 'STOPPED'),
                    'testnet':{'state':'STOPPED','session':_session,'error':'','observation_at':time.time()}}
        if not _identity_valid:
            return {'network_page':'TESTNET', 'revision':(_session, 'IDENTITY_UNVERIFIED'),
                    'testnet':{'state':'READ_FAILED','session':_session,'review':None,'observation_at':time.time(),
                        'block_graph':_block_history.snapshot(_transactions,stale=True),
                        'error':'GG_TESTNET_IDENTITY_UNVERIFIED'}}
        started = _probe_start()
        try:
            latest = _rpc('eth_getBlockByNumber', ['latest', False])
            tip = evm_block(latest)
            graph = _block_graph(latest)
            if graph.get('stale'):
                raise ValueError('GG_BLOCK_GRAPH_READ_FAILED')
            _measurement('rpc', started, 'PASS', tip['height'], tip['hash'])
            body = {'state':'RUNNING','session':_session,'error':'','observation_at':time.time(),'height':tip['height'], 'block_graph':graph,
                    'measurements':list(_measurements), 'rpc_totals':dict(_rpc_stats),
                    'observation_interval_ms':OBSERVATION_INTERVAL_MS}
        except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):
            _block_history.fail()
            _measurement('rpc', started, 'FAIL')
            body = {'state':'READ_FAILED','session':_session,'review':None,'observation_at':time.time(),'block_graph':_block_history.snapshot(_transactions,stale=True),
                    'measurements':list(_measurements),'error':'GG_NETWORK_OBSERVATION_FAILED'}
        return {'network_page':'TESTNET','revision':(_session, _rpc_stats['requests']),
                'testnet':body}
    finally:
        LOCK.release()


atexit.register(shutdown)
