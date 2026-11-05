"""Owned stopped-validator storage maintenance; no keys/network/SDK startup.

Only a protected session/profile supplies the public pin and native root. The
native tool fully replays original DAG provenance and resumes atomic additive
index batches. The receipt is local storage evidence, never network finality.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import time

from backend import gg_consensus as native,gg_dag_segmented as segmented
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_segmented_authority import OwnedSegmentedSession
from backend.gg_testnet_process import contain
from backend.gg_native_start import native_pipe_creation_flags
from backend import gg_native_pipe_lifecycle as native_pipes
from backend.platform_files import is_link

SCOPE='ORIGINAL_DAG_REPLAY_AND_ADDITIVE_INDEX_TRANSITION_NOT_NATIVE_TRANSFER_HISTORY_OR_NETWORK_FRESHNESS'
HASH=re.compile(r'[0-9a-f]{64}')


def _request_bytes(value):
    # Match encoding/json.Marshal for this local public request, including a
    # user's Unicode path and Go's HTML/line-separator string escaping. DAG
    # signature-domain encoders remain unchanged.
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    for old,new in ((b'&',b'\\u0026'),(b'<',b'\\u003c'),(b'>',b'\\u003e'),
                    (b'\xe2\x80\xa8',b'\\u2028'),(b'\xe2\x80\xa9',b'\\u2029')):
        raw=raw.replace(old,new)
    return raw


def _receipt(value,anchor):
    expected={'schema','state','verified','verification_scope','genesis_hash','source_hash','commitment','indexed_epochs','history_sha256',
        'native_state_height','native_state_root','original_history_replayed','native_transfer_history_replayed','signers_opened','consensus_started','network_started'}
    if (not isinstance(value,dict) or set(value)!=expected or value['schema']!='gg.dag.index-transition-result.v1'
            or value['state'] not in ('INDEX_TRANSITION_COMPLETE','ALREADY_CURRENT') or value['verified'] is not True
            or value['verification_scope']!=SCOPE or value['genesis_hash']!=anchor['genesis_hash']
            or value['original_history_replayed'] is not True or any(value[field] is not False for field in ('native_transfer_history_replayed','signers_opened','consensus_started','network_started'))
            or type(value['native_state_height']) is not int or not 0<=value['native_state_height']<segmented.MAX_COUNTER
            or type(value['native_state_root']) is not str or not HASH.fullmatch(value['native_state_root'])
            or type(value['history_sha256']) is not str or not HASH.fullmatch(value['history_sha256'])):
        raise ValueError('GG_INDEX_TRANSITION_RECEIPT')
    state=segmented.validate_state(value['commitment'],anchor['genesis']['dag_segmented'],anchor['genesis_hash'])
    if value['source_hash']!=state['source_hash'] or type(value['indexed_epochs']) is not str or value['indexed_epochs']!=str(int(state['epoch'])-1):
        raise ValueError('GG_INDEX_TRANSITION_RECEIPT')
    return deepcopy(value)


def transition(profile,session,*,tools=None,timeout=1800,check=None):
    """Finite foreground action with owned-child cleanup and no signing call.

    Runtime serialization and the real DB lease enforce stopped-validator
    access. A concurrent foreign process cannot be displaced by this command.
    """
    if not isinstance(profile,ValidatorProfile) or not isinstance(session,OwnedSegmentedSession):raise ValueError('GG_INDEX_TRANSITION_OWNED_PROFILE_REQUIRED')
    if type(timeout) not in (int,float) or not 1<=timeout<=1800:raise ValueError('GG_INDEX_TRANSITION_TIMEOUT')
    if check is not None and not callable(check):raise ValueError('GG_INDEX_TRANSITION_CHECK')
    session.check();anchor=session.anchor()
    if session.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
    invite=profile.public_invite()
    if (profile.anchor()!=anchor or invite['body']['owner_peer_key']!=session.public_key
            or invite not in anchor['genesis']['membership']['validators']):raise ValueError('GG_INDEX_TRANSITION_SESSION_PIN')
    directory=Path(native.TOOLS if tools is None else tools);binary=native._installed_binary(directory);stamp=native._validate_binary_at(directory,binary)
    root=profile.root/'native';deadline=time.monotonic()+timeout
    def permitted():
        session.check()
        if session.stopped() or profile._closed or profile._failed or getattr(profile,'_native_pipe_closing',False) or profile._body['fault']:raise ValueError('GG_INDEX_TRANSITION_OWNER_STOPPED')
        if profile.anchor()!=anchor or profile.public_invite()!=invite:raise ValueError('GG_INDEX_TRANSITION_SESSION_PIN')
        if profile._body['native_started'] is not True or not root.is_dir() or any(is_link(path) for path in (root,*root.parents)):
            raise ValueError('GG_INDEX_TRANSITION_NATIVE_HISTORY_REQUIRED')
        if (binary.stat().st_size,binary.stat().st_mtime_ns)!=stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
        if time.monotonic()>=deadline:raise ValueError('GG_INDEX_TRANSITION_TIMEOUT')
        if check is not None:check()
    process=None;lease=None
    with profile._lock:
        with native_pipes.INDEX_TRANSITION.operation((profile,session.owner)) as retirement:
            try:
                permitted()
                request={'schema':'gg.dag.index-transition-request.v1',**anchor,'root':str(root)};raw=_request_bytes(request)
                if len(raw)>65536:raise ValueError('GG_INDEX_TRANSITION_REQUEST_LIMIT')
                environment=native._environment();environment.update(GOMAXPROCS='2',GOMEMLIMIT='384MiB')
                flags=native_pipe_creation_flags()
                process=subprocess.Popen([str(binary),'index-transition'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    cwd=profile.root,env=environment,creationflags=flags)
                retirement.attach(process)
                lease=contain(process);retirement.lease=lease;pending=raw
                while True:
                    permitted()
                    try:output,_=process.communicate(input=pending,timeout=min(.2,max(.001,deadline-time.monotonic())));break
                    except subprocess.TimeoutExpired:pending=None
                permitted()
                if len(output)>8192:raise ValueError('GG_INDEX_TRANSITION_RECEIPT')
                try:value=json.loads(output)
                except (ValueError,UnicodeError):raise ValueError('GG_INDEX_TRANSITION_RECEIPT') from None
                if process.returncode:
                    code=value.get('error') if isinstance(value,dict) else None
                    raise ValueError(code if type(code) is str and re.fullmatch(r'GG_[A-Z0-9_]{1,96}',code) else 'GG_INDEX_TRANSITION_NATIVE_REJECTED')
                return _receipt(value,anchor)
            except OSError:raise ValueError('GG_INDEX_TRANSITION_NATIVE_UNAVAILABLE') from None
