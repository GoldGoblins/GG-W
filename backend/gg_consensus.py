"""Owned local CometBFT cluster with fixed test validators and RAM-only keys.

The application never chooses a remote target or a production wallet. CometBFT
orders blocks; its SDK verifies certificates and both sides of each demonstrated
state transition. Four processes on one machine remain one operator/fault domain.
"""
from __future__ import annotations

import atexit
import base64
from collections import deque, OrderedDict
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlencode

import psutil
from backend.gg_ed25519 import Keypair

from backend.application_paths import PROJECT_ROOT, TOOLS_ROOT
from backend.gg_testnet_process import contain
from backend.omni_assets import amount_atomic, format_atomic
from backend.gg_block_graph import BlockHistory, block_hash, comet_block

SYMBOL='GG-NET-TEST'
DECIMALS=6
SUPPLY=1_000_000*10**DECIMALS
QUORUM=3
COUNT=4
MAX_TRANSFERS=4096
SOURCES=PROJECT_ROOT/'support/gg-consensus'
TOOLS=TOOLS_ROOT/'gg-consensus'


def _installed_binary(tools):
    """Resolve only a receipt-bound native basename inside this toolchain."""
    tools=Path(tools)
    suffix='.exe' if os.name=='nt' else ''
    fallback=tools/('gg-consensus-node'+suffix)
    receipt=tools/'build-manifest.json'
    try:
        if not receipt.is_file() or receipt.stat().st_size>16384:return fallback
        record=json.loads(receipt.read_text(encoding='utf-8'))
        name=record.get('binary','');fingerprint=record.get('source_sha256','')
        if name!=fallback.name:
            if (not isinstance(fingerprint,str) or not re.fullmatch(r'[0-9a-f]{64}',fingerprint)
                or name!='gg-consensus-node-'+fingerprint[:16]+suffix):return fallback
        candidate=tools/name
        if candidate.is_symlink() or candidate.resolve().parent!=tools.resolve():return fallback
        return candidate
    except (ValueError,TypeError,AttributeError,OSError):return fallback


BINARY=_installed_binary(TOOLS)
BLOCK_INTERVAL_MS=2000
LOCK=threading.RLock()
_closed=False
_temporary=None
_genesis=None
_genesis_hash=''
_accounts=[]
_validator_keys=[]
_node_keys=[]
_nodes=[]
_review=None
_transactions=deque(maxlen=64)
_measurements=deque(maxlen=32)
_events=deque(maxlen=48)
_certificate_cache={}
_execution_cache=OrderedDict()
_last_state=None
_last_proof=None
_last_test=None
_benchmark=None
_submitted=0
_binary_stamp=None
_connections={}
_block_history=BlockHistory('CometBFT v0.40.0',first_height=1)
_certified_tip=None


class RpcUnavailable(ValueError):
    """A bounded, well-formed RPC error; the HTTP connection remains usable."""


def _pack(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_pack(value)).hexdigest()


def _public(key):
    return bytes(key.pubkey()).hex()


def _event(kind,message):
    _events.appendleft({'ts':time.time(),'kind':kind,'message':message})


def _measure(operation,started,state):
    _measurements.append({'operation':operation,'elapsed_ms':round((time.perf_counter()-started)*1000,3),
                          'state':state,'observed_at':time.time()})


def _environment():
    allowed={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOME','LANG','LC_ALL'}
    result={k:v for k,v in os.environ.items() if k.upper() in allowed}
    result.update(GOMAXPROCS='2',GOMEMLIMIT='256MiB')
    return result


def available():
    return BINARY.is_file()


def _validate_binary():
    """Bind the optional executable to its public, reproducible source build."""
    global _binary_stamp
    path=TOOLS/'build-manifest.json'
    if not path.is_file() or path.stat().st_size>16384:raise ValueError('GG_CONSENSUS_BUILD_RECEIPT_REQUIRED')
    record=json.loads(path.read_text(encoding='utf-8'))
    if (BINARY.is_symlink() or BINARY.resolve().parent!=TOOLS.resolve()
        or record.get('binary')!=BINARY.name or _installed_binary(TOOLS)!=BINARY):
        raise ValueError('GG_CONSENSUS_BINARY_PATH')
    files=sorted([SOURCES/'go.mod',SOURCES/'go.sum',SOURCES/'toolchain.json',*SOURCES.glob('*.go')],key=lambda p:p.name)
    entries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    expected=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if record.get('schema')!='gg.consensus.build.v1' or record.get('source_sha256')!=expected or record.get('cometbft')!='v0.40.0':
        raise ValueError('GG_CONSENSUS_REBUILD_REQUIRED')
    digest=hashlib.sha256()
    with BINARY.open('rb') as binary:
        for chunk in iter(lambda:binary.read(1024*1024),b''):digest.update(chunk)
    if digest.hexdigest()!=record.get('binary_sha256'):raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
    stat=BINARY.stat();_binary_stamp=(stat.st_size,stat.st_mtime_ns)


def _alive(index):
    return 0<=index<len(_nodes) and _nodes[index].get('process') is not None and _nodes[index]['process'].poll() is None


def _index(index):
    if type(index) is not int or not 0<=index<COUNT:
        raise ValueError('GG_CONSENSUS_NODE_INDEX')
    return index


def _owned(index):
    if not _alive(index):return False
    node=_nodes[index]
    process=node['process']
    try:
        listeners=[c for c in psutil.Process(process.pid).net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN]
        verified=(all(c.laddr.ip=='127.0.0.1' for c in listeners)
                  and {node['rpc_port'],node['p2p_port']}<={c.laddr.port for c in listeners})
        if verified:node['ownership_provider']='KERNEL_LISTENERS'
        return verified
    except (psutil.AccessDenied,PermissionError):
        # Android 10+ restricts /proc/net. A bounded readiness message comes
        # directly from this exact Popen stdout, after the verified native
        # binary bound both fixed loopback listeners. All state/receipts still
        # require SDK certificates; this never accepts a user-selected target.
        ready=node.get('_ready')
        try:
            stat=BINARY.stat()
            unchanged=_binary_stamp is not None and (stat.st_size,stat.st_mtime_ns)==_binary_stamp
        except OSError:unchanged=False
        verified=(os.name!='nt' and _alive(index) and node['process'] is process and unchanged
                  and ready is not None and ready['process'] is process)
        if verified:node['ownership_provider']='OWNED_CHILD_READY_PIPE'
        return verified
    except (psutil.Error,OSError):return False


def _read_ready(node,process,expected):
    try:
        raw=process.stdout.readline(1025)
        if not raw.endswith(b'\n') or len(raw)>1024:return
        def pairs(entries):
            result={}
            for key,value in entries:
                if key in result:raise ValueError('GG_CONSENSUS_READY_DUPLICATE')
                result[key]=value
            return result
        value=json.loads(raw,object_pairs_hook=pairs)
        if (not isinstance(value,dict) or value!=expected
            or any(type(value.get(k)) is not int for k in ('pid','rpc_port','p2p_port'))):return
        if node.get('process') is process:node['_ready']={'process':process}
    except (OSError,ValueError,TypeError):pass
    finally:
        try:process.stdout.close()
        except OSError:pass


def _rpc(index,method,params=None,timeout=3):
    if _closed:raise ValueError('GG_CONSENSUS_SHUTTING_DOWN')
    if method not in {'status','net_info','abci_query','commit','tx','block','broadcast_tx_sync'}:
        raise ValueError('GG_CONSENSUS_RPC_METHOD')
    _index(index)
    if not _alive(index):raise ValueError('GG_CONSENSUS_NODE_STOPPED')
    path='/'+method
    if params:path+='?'+urlencode(params)
    if len(path)>8192:raise ValueError('GG_CONSENSUS_REQUEST_LIMIT')
    owner=(id(_nodes[index]['process']),_nodes[index]['rpc_port'],_genesis_hash)
    existing=_connections.get(index)
    if existing is not None and existing[0]!=owner:
        _drop_connection(index);existing=None
    if existing is None:
        if not _owned(index):raise ValueError('GG_CONSENSUS_LISTENER_NOT_OWNED')
        connection=http.client.HTTPConnection('127.0.0.1',_nodes[index]['rpc_port'],timeout=timeout)
        _connections[index]=(owner,connection)
    else:connection=existing[1]
    try:
        connection.request('GET',path)
        response=connection.getresponse();body=response.read(512*1024+1)
        if len(body)>512*1024:raise ValueError('GG_CONSENSUS_RPC_RESPONSE')
        value=json.loads(body)
        if not isinstance(value,dict):raise ValueError('GG_CONSENSUS_RPC_RESPONSE')
        if 'error' in value:
            if response.will_close:_drop_connection(index)
            raise RpcUnavailable('GG_CONSENSUS_RPC_UNAVAILABLE')
        if response.status!=200 or 'result' not in value:
            raise ValueError('GG_CONSENSUS_RPC_UNAVAILABLE')
        if response.will_close:_drop_connection(index)
        return value['result']
    except RpcUnavailable:raise
    except Exception:
        # A failed write is never retried on a replacement connection.
        _drop_connection(index)
        raise


def _drop_connection(index):
    existing=_connections.pop(index,None)
    if existing is not None:
        try:existing[1].close()
        except (OSError,http.client.HTTPException):pass


def _status(index):
    if not _owned(index):raise ValueError('GG_CONSENSUS_LISTENER_NOT_OWNED')
    result=_rpc(index,'status')
    info=result['node_info']
    address=hashlib.sha256(bytes.fromhex(_genesis['validators'][index])).digest()[:20].hex()
    if (info['network']!=_genesis['chain_id'] or info['id'].lower()!=_nodes[index]['node_id']
            or result['validator_info']['address'].lower()!=address):
        raise ValueError('GG_CONSENSUS_NODE_IDENTITY')
    return result


def _query(index,path,height=None,data=None):
    params={'path':json.dumps(path),'prove':'false'}
    if height is not None:params['height']=str(height)
    if data is not None:params['data']='0x'+data.hex()
    response=_rpc(index,'abci_query',params)['response']
    if int(response.get('code',0))!=0:raise ValueError('GG_CONSENSUS_QUERY_REJECTED')
    raw=base64.b64decode(response['value'],validate=True)
    if len(raw)>65536:raise ValueError('GG_CONSENSUS_STATE_LIMIT')
    state=json.loads(raw)
    if not isinstance(state,dict):raise ValueError('GG_CONSENSUS_STATE_SCHEMA')
    return state


def _read_state_at(index,height):
    return _query(index,'/gg/genesis' if height==0 else '/gg/state',height if height else None)


def _verify(payload):
    if _binary_stamp is not None:
        stat=BINARY.stat()
        if (stat.st_size,stat.st_mtime_ns)!=_binary_stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
    raw=_pack(payload)
    if len(raw)>256*1024:raise ValueError('GG_CONSENSUS_PROOF_LIMIT')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    try:
        result=subprocess.run([str(BINARY),'verify'],input=raw,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              env=_environment(),timeout=6,creationflags=flags)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('GG_CONSENSUS_VERIFY_UNAVAILABLE') from None
    if result.returncode or len(result.stdout)>8192:raise ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')
    verified=json.loads(result.stdout)
    if (not isinstance(verified,dict) or verified.get('verified') is not True
        or verified.get('schema')!='gg.consensus.proof-result.v1'
        or verified.get('validator_count')!=COUNT or verified.get('quorum_required')!=QUORUM
        or verified.get('chain_id')!=payload['genesis']['chain_id']
        or verified.get('state_height')!=payload['state']['height']
        or verified.get('certificate_height')!=payload['state']['height']+1
        or verified.get('state_root')!=payload['state']['state_root']):
        raise ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')
    return verified


def _proof_payload(state,header):
    return {'schema':'gg.consensus.proof.v1','genesis':_genesis,'genesis_hash':_genesis_hash,
            'signed_header':header,'state':state}


def _verified_state():
    global _last_state,_last_proof,_certified_tip
    candidates=[]
    for index in range(COUNT):
        if not _alive(index):continue
        try:
            status=_status(index)
            height=int(status['sync_info']['latest_block_height'])
            if height>0:candidates.append((height,index))
        except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):continue
    if not candidates:raise ValueError('GG_CONSENSUS_NO_CERTIFIED_STATE')
    for height,index in sorted(candidates,reverse=True):
        try:
            commit=_rpc(index,'commit',{'height':str(height)})['signed_header']
            state=_read_state_at(index,height-1)
            if state.get('chain_id')!=_genesis['chain_id'] or state.get('genesis_hash')!=_genesis_hash or state.get('height')!=height-1:
                raise ValueError('GG_CONSENSUS_STATE_IDENTITY')
            payload=_proof_payload(state,commit)
            if height>1:
                payload['account_proof']=_query(index,'/gg/proof',height-1,bytes.fromhex(_genesis['accounts'][0]))
            cache_key=(height,_digest(payload))
            verified=_certificate_cache.get(cache_key)
            if verified is None:
                verified=_verify(payload)
                if len(_certificate_cache)>=32:_certificate_cache.clear()
                _certificate_cache[cache_key]=dict(verified)
            _last_state=state;_last_proof=verified
            _certified_tip=(height,block_hash(commit['commit']['block_id']['hash']))
            return index,state,verified
        except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):continue
    raise ValueError('GG_CONSENSUS_NO_CERTIFIED_STATE')


def trust_context():
    """Public anchor captured from this controller, never from an input packet."""
    with LOCK:
        if not _genesis:raise ValueError('GG_CONSENSUS_NOT_STARTED')
        return json.loads(_pack({'genesis':_genesis,'genesis_hash':_genesis_hash}))


def export_proof(account=0):
    """Export a public certified historical balance snapshot, without keys."""
    with LOCK:
        if type(account) is not int or not 0<=account<COUNT:raise ValueError('GG_CONSENSUS_ACCOUNT_INDEX')
        index,state,verified=_verified_state()
        header=_rpc(index,'commit',{'height':str(verified['certificate_height'])})['signed_header']
        payload=_proof_payload(state,header)
        if state['height']>0:
            payload['account_proof']=_query(index,'/gg/proof',state['height'],bytes.fromhex(_genesis['accounts'][account]))
        _verify(payload)
        _event('PUBLIC_PROOF_READY','Certifierad saldobild vid höjd '+str(state['height'])+' · endast offentliga uppgifter')
        return json.loads(_pack(payload))


def _launch(index):
    node=_nodes[index]
    if _alive(index):return
    if _binary_stamp is not None:
        stat=BINARY.stat()
        if (stat.st_size,stat.st_mtime_ns)!=_binary_stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
    if node['started']:
        state_path=Path(node['root'])/'data/priv_validator_state.json'
        if not state_path.is_file() or state_path.stat().st_size>16384:
            raise ValueError('GG_CONSENSUS_SIGN_STATE_REQUIRED')
    bootstrap={'schema':'gg.consensus.bootstrap.v1','genesis':_genesis,'genesis_hash':_genesis_hash,
               'validator_index':index,'validator_seed':bytes(_validator_keys[index])[:32].hex(),
               'node_seed':bytes(_node_keys[index])[:32].hex(),'root':node['root'],
               'rpc_port':node['rpc_port'],'p2p_port':node['p2p_port'],
               'peers':[{'id':other['node_id'],'port':other['p2p_port']} for i,other in enumerate(_nodes) if i!=index]}
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    process=subprocess.Popen([str(BINARY)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                             cwd=node['root'],env=_environment(),creationflags=flags)
    node['process']=process;node['_ready']=None;node['ownership_provider']='UNVERIFIED'
    try:
        node['lease']=contain(process)
        expected={'schema':'gg.consensus.ready.v1','chain_id':_genesis['chain_id'],'node_id':node['node_id'],
                  'pid':process.pid,'rpc_port':node['rpc_port'],'p2p_port':node['p2p_port']}
        threading.Thread(target=_read_ready,args=(node,process,expected),name='GG-owned-node-ready',daemon=True).start()
        raw=_pack(bootstrap)
        if len(raw)>65536:raise ValueError('GG_CONSENSUS_BOOTSTRAP_LIMIT')
        process.stdin.write(raw);process.stdin.close()
        node['started']=True
    except Exception:
        _stop_process(index)
        raise
    finally:
        bootstrap.clear()


def _stop_process(index):
    node=_nodes[index];process=node.get('process');lease=node.get('lease')
    _drop_connection(index)
    errors=[]
    try:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=4)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
    except (OSError,subprocess.TimeoutExpired):errors.append('process')
    try:
        if lease:lease.close()
    except (OSError,RuntimeError):errors.append('lease')
    if process is not None and process.poll() is None:raise ValueError('GG_CONSENSUS_STOP_FAILED')
    node['process']=None;node['lease']=None;node['_ready']=None
    if errors:raise ValueError('GG_CONSENSUS_STOP_CLEANUP_FAILED')


def start():
    global _temporary,_genesis,_genesis_hash,_accounts,_validator_keys,_node_keys,_nodes
    global _review,_last_state,_last_proof,_last_test,_benchmark,_submitted
    with LOCK:
        if _closed:raise ValueError('GG_CONSENSUS_SHUTTING_DOWN')
        if _genesis is not None:
            # Paused validators retain their chain and RAM signer identities.
            # A new genesis requires an explicit complete stop first.
            for index in range(COUNT):
                if not _alive(index):_launch(index)
            return snapshot()
        stop()
        if not available():raise ValueError('GG_CONSENSUS_TOOLCHAIN_REQUIRED')
        _validate_binary()
        _temporary=tempfile.TemporaryDirectory(prefix='gg-consensus-public-')
        _accounts=[Keypair() for _ in range(COUNT)]
        _validator_keys=[Keypair() for _ in range(COUNT)]
        _node_keys=[Keypair() for _ in range(COUNT)]
        _genesis={'schema':'gg.native.genesis.v1','chain_id':'ggnet:'+secrets.token_hex(12),
                  'genesis_time_unix':int(time.time()),'accounts':[_public(k) for k in _accounts],
                  'validators':[_public(k) for k in _validator_keys],'supply_atomic':str(SUPPLY),
                  'decimals':DECIMALS,'symbol':SYMBOL}
        _genesis_hash=_digest(_genesis)
        _block_history.reset(_genesis_hash)
        reservations=[]
        try:
            for index in range(COUNT):
                ports=[]
                for _ in range(2):
                    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                    listener.bind(('127.0.0.1',0));ports.append(listener.getsockname()[1]);reservations.append(listener)
                directory=Path(_temporary.name)/('validator-'+str(index+1));directory.mkdir()
                _nodes.append({'root':str(directory),'rpc_port':ports[0],'p2p_port':ports[1],
                               'node_id':hashlib.sha256(bytes(_node_keys[index].pubkey())).digest()[:20].hex(),
                               'process':None,'lease':None,'started':False})
            _review=None;_last_state=None;_last_proof=None;_last_test=None;_benchmark=None;_submitted=0
            _transactions.clear();_measurements.clear();_events.clear();_certificate_cache.clear();_execution_cache.clear()
            for index in range(COUNT):
                reservations[index*2].close();reservations[index*2+1].close();_launch(index)
            deadline=time.monotonic()+35
            while True:
                if _closed:raise ValueError('GG_CONSENSUS_SHUTTING_DOWN')
                if any(not _alive(i) for i in range(COUNT)):raise ValueError('GG_CONSENSUS_START_FAILED')
                try:
                    for i in range(COUNT):_status(i)
                    _verified_state()
                    break
                except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):
                    if time.monotonic()>deadline:raise ValueError('GG_CONSENSUS_START_TIMEOUT') from None
                    time.sleep(.1)
            _event('STARTED','Fyra separata CometBFT-processer · en dator · fasta testvalidatorer')
            return snapshot()
        except Exception:
            stop();raise
        finally:
            for listener in reservations:listener.close()


def stop():
    global _temporary,_genesis,_genesis_hash,_accounts,_validator_keys,_node_keys,_nodes,_review,_last_state,_last_proof,_certified_tip
    with LOCK:
        errors=[]
        for index in range(len(_nodes)):
            try:_stop_process(index)
            except (ValueError,OSError):errors.append(index)
        if any(_alive(i) for i in range(len(_nodes))):raise ValueError('GG_CONSENSUS_STOP_FAILED')
        temporary=_temporary;_temporary=None
        _nodes=[];_review=None;_accounts=[];_validator_keys=[];_node_keys=[];_genesis=None;_genesis_hash=''
        _last_state=None;_last_proof=None;_certificate_cache.clear();_execution_cache.clear()
        _certified_tip=None;_block_history.reset('')
        if temporary is not None:temporary.cleanup()
        if errors:raise ValueError('GG_CONSENSUS_STOP_CLEANUP_FAILED')
        return {'state':'STOPPED'}


def shutdown():
    global _closed
    _closed=True
    return stop()


def stop_node(index):
    with LOCK:
        _index(index)
        if len(_nodes)!=COUNT:raise ValueError('GG_CONSENSUS_STOPPED')
        _stop_process(index);_event('NODE_STOPPED','Validator '+str(index+1)+' pausad')
        return snapshot()


def restart_node(index):
    with LOCK:
        _index(index)
        if _closed:raise ValueError('GG_CONSENSUS_SHUTTING_DOWN')
        if len(_nodes)!=COUNT:raise ValueError('GG_CONSENSUS_STOPPED')
        _launch(index);_event('NODE_RESTARTED','Validator '+str(index+1)+' återstartad med bevarad signeringshistorik')
        return snapshot()


def _account_map(state):
    return {account['address']:account for account in state['accounts']}


def _signed_transaction(sender,recipient,atomic,nonce):
    body={'version':1,'chain_id':_genesis['chain_id'],'genesis_hash':_genesis_hash,
          'sender':_public(_accounts[sender]),'recipient':recipient,'amount_atomic':str(atomic),'nonce':nonce}
    return _pack({'body':body,'signature':bytes(_accounts[sender].sign_message(_pack(body))).hex()})


def prepare(sender,recipient,amount):
    global _review
    with LOCK:
        _review=None
        if _genesis is None:raise ValueError('GG_CONSENSUS_STOPPED')
        _index(sender)
        if sum(_alive(i) for i in range(COUNT))<QUORUM:raise ValueError('GG_CONSENSUS_NO_QUORUM')
        if any(row['state'] in {'SUBMITTED','BROADCAST_UNKNOWN'} for row in _transactions):
            raise ValueError('GG_CONSENSUS_UNRESOLVED_TRANSACTION')
        if recipient not in _genesis['accounts'] or recipient==_public(_accounts[sender]):
            raise ValueError('GG_CONSENSUS_RECIPIENT')
        atomic=amount_atomic(amount,DECIMALS)
        if atomic<=0:raise ValueError('GG_CONSENSUS_AMOUNT')
        _,state,_=_verified_state();source=_account_map(state)[_public(_accounts[sender])]
        if atomic>int(source['balance_atomic']):raise ValueError('GG_CONSENSUS_INSUFFICIENT_FUNDS')
        review={'id':secrets.token_hex(16),'chain_id':_genesis['chain_id'],'genesis_hash':_genesis_hash,
                'sender_index':sender,'sender':source['address'],'recipient':recipient,'amount':format_atomic(atomic,DECIMALS),
                'atomic':str(atomic),'symbol':SYMBOL,'nonce':source['nonce'],'expires_at':time.time()+120}
        review['review_digest']=_digest(review);_review=review
        return snapshot()


def cancel_review():
    global _review
    with LOCK:_review=None


def _receipt(index,record):
    cached=_execution_cache.get(record['hash'])
    if cached is not None:
        if cached['genesis_hash']!=_genesis_hash or cached['raw']!=record['_raw']:
            raise ValueError('GG_CONSENSUS_CACHED_EXECUTION_CONTEXT')
        record.update(state='FINALIZED',height=cached['height'],certificate_height=cached['certificate_height'],
                      execution_verified=True,elapsed_ms=round((time.perf_counter()-record['_started'])*1000,3))
        return True
    result=_rpc(index,'tx',{'hash':'0x'+record['hash'],'prove':'true'})
    height=int(result['height'])
    if result['hash'].lower()!=record['hash'] or result['tx']!=base64.b64encode(record['_raw']).decode():
        raise ValueError('GG_CONSENSUS_RECEIPT_IDENTITY')
    if int(result['tx_result'].get('code',0))!=0:
        record['state']='REJECTED';return False
    tx_header=_rpc(index,'commit',{'height':str(height)})['signed_header']
    state_header=_rpc(index,'commit',{'height':str(height+1)})['signed_header']
    after=_read_state_at(index,height);before=_read_state_at(index,height-1)
    block=_rpc(index,'block',{'height':str(height)})['block']
    payload=_proof_payload(after,state_header)
    payload.update(tx_header=tx_header,tx_proof=result['proof'],expected_tx_hash=record['hash'],
                   before_state=before,block_txs=block['data'].get('txs') or [])
    verified=_verify(payload)
    if verified.get('transaction_inclusion_verified') is not True or verified.get('execution_status_verified') is not True:
        raise ValueError('GG_CONSENSUS_EXECUTION_PROOF_REQUIRED')
    # The SDK bound and replayed the COMPLETE block against certified before/
    # after states. Amortize that exact verification across its other members.
    for encoded in payload['block_txs']:
        raw=base64.b64decode(encoded,validate=True);digest=hashlib.sha256(raw).hexdigest()
        _execution_cache[digest]={'genesis_hash':_genesis_hash,'raw':raw,'height':height,'certificate_height':height+1}
        _execution_cache.move_to_end(digest)
    while len(_execution_cache)>512:_execution_cache.popitem(last=False)
    record.update(state='FINALIZED',height=height,certificate_height=height+1,execution_verified=True,
                  elapsed_ms=round((time.perf_counter()-record['_started'])*1000,3))
    return True


def _reconcile(record,timeout=0):
    deadline=time.monotonic()+timeout
    while True:
        if _closed:raise ValueError('GG_CONSENSUS_SHUTTING_DOWN')
        if record['hash'] in _execution_cache:
            return _receipt(0,record)
        for index in range(COUNT):
            if not _alive(index):continue
            try:
                # New connections are PID/port-bound in _rpc. The certificate
                # itself binds chain, validators, block and application state.
                if _receipt(index,record):return True
                if record['state']=='REJECTED':return False
            except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):continue
        if time.monotonic()>=deadline:return False
        time.sleep(.05)


def _submit(raw,description,wait=8):
    global _submitted
    if _submitted>=MAX_TRANSFERS:raise ValueError('GG_CONSENSUS_SESSION_LIMIT')
    index,_,_=_verified_state()
    record=dict(description,hash=hashlib.sha256(raw).hexdigest(),state='BROADCAST_UNKNOWN',height=None,
                certificate_height=None,elapsed_ms=None,_raw=raw,_started=time.perf_counter())
    _transactions.appendleft(record);_submitted+=1
    try:
        result=_rpc(index,'broadcast_tx_sync',{'tx':'0x'+raw.hex()})
        if result.get('hash','').lower()!=record['hash']:raise ValueError('GG_CONSENSUS_BROADCAST_IDENTITY')
        record['state']='SUBMITTED' if int(result.get('code',0))==0 else 'REJECTED'
    except (ValueError,OSError,http.client.HTTPException):
        # Hash is known before dispatch: only reconcile this exact request.
        record['state']='BROADCAST_UNKNOWN'
    if record['state']!='REJECTED':_reconcile(record,wait)
    _measure('transfer',record['_started'],record['state'])
    _event(record['state'],'Testöverföring · '+description['amount']+' '+SYMBOL)
    return record


def send(identifier,review_digest):
    global _review
    with LOCK:
        review=_review
        if not review or review.get('id')!=identifier or review.get('review_digest')!=review_digest:
            raise ValueError('GG_CONSENSUS_REVIEW_REQUIRED')
        _review=None
        if not secrets.compare_digest(_digest({k:v for k,v in review.items() if k!='review_digest'}),str(review_digest)):
            raise ValueError('GG_CONSENSUS_REVIEW_CHANGED')
        if not _genesis or review['chain_id']!=_genesis['chain_id'] or review['genesis_hash']!=_genesis_hash or time.time()>review['expires_at']:
            raise ValueError('GG_CONSENSUS_REVIEW_EXPIRED')
        if sum(_alive(i) for i in range(COUNT))<QUORUM:raise ValueError('GG_CONSENSUS_NO_QUORUM')
        _,state,_=_verified_state();source=_account_map(state)[review['sender']]
        if source['nonce']!=review['nonce']:raise ValueError('GG_CONSENSUS_NONCE_CHANGED')
        if int(source['balance_atomic'])<int(review['atomic']):raise ValueError('GG_CONSENSUS_INSUFFICIENT_FUNDS')
        if any(row['state'] in {'SUBMITTED','BROADCAST_UNKNOWN'} for row in _transactions):
            raise ValueError('GG_CONSENSUS_UNRESOLVED_TRANSACTION')
        raw=_signed_transaction(review['sender_index'],review['recipient'],review['atomic'],review['nonce'])
        _submit(raw,{k:review[k] for k in ('sender','recipient','amount')})
        return snapshot()


def self_test():
    global _last_test
    with LOCK:
        if not _genesis:raise ValueError('GG_CONSENSUS_STOPPED')
        if sum(_alive(i) for i in range(COUNT))!=COUNT:raise ValueError('GG_CONSENSUS_ALL_FOUR_REQUIRED')
        started=time.perf_counter();_last_test={'state':'RUNNING','checks':[],'observed_at':time.time()}
        _,before,_=_verified_state();balances={k:v['balance_atomic'] for k,v in _account_map(before).items()}
        try:
            for source,target in ((0,1),(1,0)):
                draft=prepare(source,_genesis['accounts'][target],'1')['review'];send(draft['id'],draft['review_digest'])
                if _transactions[0]['state']!='FINALIZED':raise ValueError('GG_CONSENSUS_SELF_TEST_UNCONFIRMED')
                _last_test['checks'].append({'name':'Överföring '+str(source+1)+' → '+str(target+1),'state':'PASS'})
            stop_node(3)
            draft=prepare(0,_genesis['accounts'][1],'0.000001')['review'];send(draft['id'],draft['review_digest'])
            if _transactions[0]['state']!='FINALIZED':raise ValueError('GG_CONSENSUS_ONE_DOWN_NO_PROGRESS')
            _last_test['checks'].append({'name':'Tre validatorer finaliserar','state':'PASS'})
            restart_node(3)
            deadline=time.monotonic()+12
            while not _owned(3):
                if time.monotonic()>deadline:raise ValueError('GG_CONSENSUS_RESTART_TIMEOUT')
                time.sleep(.05)
            draft=prepare(1,_genesis['accounts'][0],'0.000001')['review'];send(draft['id'],draft['review_digest'])
            if _transactions[0]['state']!='FINALIZED':raise ValueError('GG_CONSENSUS_SELF_TEST_UNCONFIRMED')
            _,after,_=_verified_state()
            if {k:v['balance_atomic'] for k,v in _account_map(after).items()}!=balances:
                raise ValueError('GG_CONSENSUS_SELF_TEST_BALANCE')
            _last_test['checks'].append({'name':'Återstart och återställda saldon','state':'PASS'})
            stop_node(2);stop_node(3)
            time.sleep(.2)
            index,state,_=_verified_state()
            head_before=int(_status(index)['sync_info']['latest_block_height'])
            current=_account_map(state)[_genesis['accounts'][0]]
            raw=_signed_transaction(0,_genesis['accounts'][1],'1',current['nonce'])
            record=_submit(raw,{'sender':_genesis['accounts'][0],'recipient':_genesis['accounts'][1],'amount':'0.000001'},wait=0)
            original_hash=record['hash']
            time.sleep(.8)
            if _reconcile(record) or int(_status(index)['sync_info']['latest_block_height'])!=head_before:
                raise ValueError('GG_CONSENSUS_TWO_DOWN_FINALIZED')
            _,still,_=_verified_state()
            if still['state_root']!=state['state_root']:raise ValueError('GG_CONSENSUS_TWO_DOWN_STATE_CHANGED')
            _last_test['checks'].append({'name':'Två pausade validatorer hindrar finalisering','state':'PASS'})
            restart_node(2);restart_node(3)
            if not _reconcile(record,timeout=18) or record['hash']!=original_hash:
                raise ValueError('GG_CONSENSUS_RECOVERY_UNCONFIRMED')
            _last_test['checks'].append({'name':'Samma transaktion återhämtad utan omsändning','state':'PASS'})
            draft=prepare(1,_genesis['accounts'][0],'0.000001')['review'];send(draft['id'],draft['review_digest'])
            if _transactions[0]['state']!='FINALIZED':raise ValueError('GG_CONSENSUS_SELF_TEST_UNCONFIRMED')
            _,after,_=_verified_state()
            if {k:v['balance_atomic'] for k,v in _account_map(after).items()}!=balances:
                raise ValueError('GG_CONSENSUS_SELF_TEST_BALANCE')
            deadline=time.monotonic()+12
            while True:
                states=[]
                for i in range(COUNT):
                    try:states.append(_read_state_at(i,after['height'])['state_root'])
                    except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):pass
                if len(states)==COUNT and len(set(states))==1:break
                if time.monotonic()>deadline:raise ValueError('GG_CONSENSUS_NODE_STATE_DIVERGENCE')
                time.sleep(.05)
            _last_test['checks'].append({'name':'Alla fyra har samma verifierade tillstånd','state':'PASS'})
            _last_test['state']='PASS';_event('SELF_TEST_PASS','Certifikat, exekvering och återstart kontrollerade')
        except Exception:
            _last_test['state']='FAIL';raise
        finally:
            if not _closed:
                for i in range(len(_nodes)):
                    if not _alive(i):
                        try:_launch(i)
                        except (ValueError,OSError):_event('RESTORE_FAILED','Validator '+str(i+1)+' kunde inte återstartas efter testet')
            _measure('self_test',started,_last_test['state'])
        return snapshot()


def _summary(samples):
    ordered=sorted(samples)
    def percentile(p):
        position=(len(ordered)-1)*p;low=int(position);high=min(len(ordered)-1,low+1)
        return round(ordered[low]+(ordered[high]-ordered[low])*(position-low),3)
    return {'p50_ms':percentile(.5),'p95_ms':percentile(.95),'p99_ms':percentile(.99)}


def benchmark(count=32):
    global _benchmark,_submitted
    with LOCK:
        if type(count) is not int or not 4<=count<=128:raise ValueError('GG_CONSENSUS_BENCHMARK_LIMIT')
        if not _genesis or sum(_alive(i) for i in range(COUNT))!=COUNT:raise ValueError('GG_CONSENSUS_ALL_FOUR_REQUIRED')
        if _review or any(t['state'] in {'SUBMITTED','BROADCAST_UNKNOWN'} for t in _transactions):
            raise ValueError('GG_CONSENSUS_OPERATION_PENDING')
        if _submitted+count>MAX_TRANSFERS:raise ValueError('GG_CONSENSUS_SESSION_LIMIT')
        _benchmark={'state':'RUNNING','count':count,'successful':0,'scope':'LOCAL_FIXED_VALIDATORS',
                    'validators':COUNT,'physical_hosts':1,'observed_at':time.time()}
        started=time.perf_counter();records=[]
        try:
            node_index,before,_=_verified_state()
            expected={a:dict(row) for a,row in _account_map(before).items()}
            for index in range(count):
                source=index%COUNT;target=source^1
                sender=_genesis['accounts'][source];recipient=_genesis['accounts'][target]
                raw=_signed_transaction(source,recipient,'1',expected[sender]['nonce'])
                expected[sender]['nonce']+=1
                expected[sender]['balance_atomic']=str(int(expected[sender]['balance_atomic'])-1)
                expected[recipient]['balance_atomic']=str(int(expected[recipient]['balance_atomic'])+1)
                record={'hash':hashlib.sha256(raw).hexdigest(),'state':'BROADCAST_UNKNOWN','sender':sender,
                        'recipient':recipient,'amount':'0.000001','height':None,'certificate_height':None,
                        'elapsed_ms':None,'_raw':raw,'_started':time.perf_counter()}
                records.append(record);_transactions.appendleft(record);_submitted+=1
                response=_rpc(node_index,'broadcast_tx_sync',{'tx':'0x'+raw.hex()})
                if response.get('hash','').lower()!=record['hash']:raise ValueError('GG_CONSENSUS_BROADCAST_IDENTITY')
                record['state']='SUBMITTED' if int(response.get('code',0))==0 else 'REJECTED'
                if record['state']=='REJECTED':raise ValueError('GG_CONSENSUS_BENCHMARK_REJECTED')
            deadline=time.monotonic()+30
            while True:
                for record in records:
                    if record['state'] not in {'FINALIZED','REJECTED'}:
                        _reconcile(record)
                        # Wait on one unresolved block frontier. Asking every
                        # pending member for the same not-yet-existing H+1
                        # certificate creates O(batch size) duplicate polling.
                        # Once a block verifies, its exact replay cache covers
                        # the other members without weakening any checks.
                        if record['state'] in {'SUBMITTED','BROADCAST_UNKNOWN'}:break
                _benchmark['successful']=len({r['hash'] for r in records if r['state']=='FINALIZED'})
                if _benchmark['successful']==count:break
                if any(r['state']=='REJECTED' for r in records) or time.monotonic()>deadline:
                    raise ValueError('GG_CONSENSUS_BENCHMARK_UNCONFIRMED')
                time.sleep(.03)
            _,after,_=_verified_state()
            if _account_map(after)!=expected:raise ValueError('GG_CONSENSUS_BENCHMARK_STATE_MISMATCH')
            elapsed=time.perf_counter()-started
            durations=[r['elapsed_ms'] for r in records]
            _benchmark.update(state='PASS',elapsed_seconds=round(elapsed,3),tps=round(count/elapsed,3),
                              mode='PIPELINED_BLOCK_VERIFICATION',independent_senders=COUNT,
                              verified_blocks=len({r['height'] for r in records}),
                              unique_finalized=count,state_matches_expected=True,**_summary(durations))
            _event('BENCHMARK_PASS',str(count)+' unika testöverföringar · hela block verifierade mot certifierat tillstånd')
        except Exception:
            _benchmark['state']='FAIL';raise
        finally:_measure('benchmark',started,_benchmark['state'])
        return snapshot()


def _block_graph(index,height):
    """Observe real bounded headers; SDK certificates remain separately scoped."""
    if _block_history.session!=_genesis_hash:_block_history.reset(_genesis_hash)
    try:
        if _certified_tip is None or _certified_tip[0]!=height:
            raise ValueError('GG_BLOCK_GRAPH_CERTIFIED_TIP_REQUIRED')
        rows=[]
        for wanted in _block_history.wanted(height):
            row=comet_block(_rpc(index,'block',{'height':str(wanted)}),_genesis['chain_id'])
            if row['height']!=wanted:raise ValueError('GG_BLOCK_GRAPH_HEIGHT')
            for validator_index,public_key in enumerate(_genesis.get('validators',[])):
                if hashlib.sha256(bytes.fromhex(public_key)).digest()[:20].hex()==row['proposer']:
                    row['proposer_index']=validator_index
                    break
            if (wanted,row['hash'])==_certified_tip:row['certificate_verified']=True
            rows.append(row)
        _block_history.ingest(rows,height,_certified_tip[1])
    except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):
        _block_history.fail()
    return _block_history.snapshot(_transactions,ttf_basis='API_SUBMISSION_TO_EXECUTION_PROOF')


def snapshot():
    global _review
    with LOCK:
        result={'state':'STOPPED','available':available(),'engine':'CometBFT v0.40.0','chain_id':_genesis['chain_id'] if _genesis else '',
                'height':None,'state_height':None,'online':0,'quorum_required':QUORUM,'validators':[],
                'accounts':[],'proof':None,'review':None,'transactions':[],
                'measurements':list(_measurements),'last_test':_last_test,'benchmark':_benchmark,
                'events':list(_events),'error':'','unresolved':False,'symbol':SYMBOL,'decimals':DECIMALS,
                'supply':format_atomic(SUPPLY,DECIMALS),'session_transactions':_submitted,'transaction_limit':MAX_TRANSFERS,
                'physical_hosts':1,'operator_count':1,'production':False}
        result.update(block_interval_target_ms=BLOCK_INTERVAL_MS,empty_blocks=True)
        result['block_graph']=_block_history.snapshot(_transactions,ttf_basis='API_SUBMISSION_TO_EXECUTION_PROOF',stale=not _genesis)
        if not _genesis:return result
        for index,node in enumerate(_nodes):
            row={'index':index,'node_id':node['node_id'],'public_key':_genesis['validators'][index],
                 'alive':_alive(index),'identity_verified':False,'peers':None,'height':None,
                 'rpc_url':'http://127.0.0.1:'+str(node['rpc_port']),'memory_private_bytes':None,'cpu_seconds':None}
            if row['alive']:
                try:
                    status=_status(index);row['identity_verified']=True;row['height']=int(status['sync_info']['latest_block_height'])
                    row['peers']=int(_rpc(index,'net_info')['n_peers'])
                    memory=psutil.Process(node['process'].pid).memory_info();cpu=psutil.Process(node['process'].pid).cpu_times()
                    row['memory_private_bytes']=getattr(memory,'private',None);row['cpu_seconds']=round(cpu.user+cpu.system,3)
                except (ValueError,KeyError,TypeError,OSError,psutil.Error,http.client.HTTPException):pass
            result['validators'].append(row)
            row['ownership_provider']=node.get('ownership_provider','UNVERIFIED')
        result['online']=sum(v['identity_verified'] for v in result['validators'])
        try:
            for record in _transactions:
                if record['state'] in {'SUBMITTED','BROADCAST_UNKNOWN'}:_reconcile(record)
            verified_index,state,proof=_verified_state()
            mapping=_account_map(state)
            result.update(state='RUNNING' if result['online']==COUNT else 'DEGRADED' if result['online']>=QUORUM else 'NO_QUORUM',
                          height=proof['certificate_height'],state_height=state['height'],proof=proof,
                          accounts=[{'index':i,'address':a,'quantity':format_atomic(int(mapping[a]['balance_atomic']),DECIMALS),
                                     'atomic':mapping[a]['balance_atomic'],'nonce':mapping[a]['nonce']} for i,a in enumerate(_genesis['accounts'])])
            result['block_graph']=_block_graph(verified_index,proof['certificate_height'])
        except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):
            result.update(state='READ_FAILED' if result['online']>=QUORUM else 'NO_QUORUM',error='GG_CONSENSUS_READ_FAILED')
            result['block_graph']=_block_history.snapshot(_transactions,ttf_basis='API_SUBMISSION_TO_EXECUTION_PROOF',stale=True)
        if _review and time.time()>_review['expires_at']:_review=None
        if result['state'] in {'READ_FAILED','NO_QUORUM'}:_review=None
        result['review']=dict(_review) if _review else None
        result['transactions']=[{k:v for k,v in record.items() if not k.startswith('_')} for record in _transactions]
        result['unresolved']=any(t['state'] in {'SUBMITTED','BROADCAST_UNKNOWN'} for t in _transactions)
        result['measurements']=list(_measurements)
        return result


atexit.register(shutdown)
