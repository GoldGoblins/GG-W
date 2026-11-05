"""Bounded per-user, read-only observations of an explicitly started CLI node.

Only the public LAN status is shared. No wallet, signer, command channel, socket
or node is created by a reader. The CLI remains the sole owner of its work.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time

from backend.application_paths import DATA_HOME
from backend.platform_files import secure_open, set_private_mode, NOFOLLOW
from backend import gg_local_history_status as local_history_status

SCHEMA = 'gg.local-node-observation.v1'
MAX_BYTES = 1024 * 1024
MAX_SOURCES = 16
FRESH_SECONDS = 5.0
RETAIN_SECONDS = 60.0
NAME = re.compile(r'^cli-[0-9]+-[0-9a-f]{16}\.json$')
HANDLE = re.compile(r'^observation-[0-9a-f]{32}$')
FIELDS = frozenset(('state mode chain_id producer_count worker_count producers finality '
    'canonical_finalized blocks_admitted transactions_validated certified_blocks certified_transactions local_full_history_replayed local_history frontier_size wave_count '
    'limits last_wave live measurements preview admission block_graph events lan dag_stress '
    'dag_resources dag_production dag_consensus dag_proofs native_observers certified_test_accounts test_tokens token_circle protocol_fault test_accounts '
    'financial_accounts own_financial_accounts financial_account_profiles financial_account_relay rejected_transactions '
    'protocol_network environment economic_state fee_pot_atomic certificate_height certificate_received_at network_contact_at producer_rows_scope connection_state state_root role certified_time_ns last_state_advance_at node_key network_id genesis_hash node_ready consensus_signing').split())
FORBIDDEN = frozenset(('private_key secret_key seed mnemonic password secret signer account_keys').split())


def _valid_recovery(value,role):
    fields=set(('schema phase requested_role work_done processed_height verified_through last_error basis '
        'node_ready full_original_audit_completed snapshot_trust_used certificate_is_network_liveness '
        'network_contact_asserted consensus_signing').split())
    def counter(item):
        return type(item) is str and re.fullmatch(r'0|[1-9][0-9]{0,18}',item) is not None and int(item)<=2**63-1
    if (type(value) is not dict or set(value)!=fields or value['schema']!='gg.owned.recovery-observation.v1'
            or role not in ('VALIDATOR','REPLICA') or value['requested_role']!=role
            or value['basis']!='LOCAL_OWNED_NATIVE_PIPE_REPORT' or not counter(value['work_done'])
            or any(value[key] is not False for key in ('snapshot_trust_used','certificate_is_network_liveness','network_contact_asserted'))
            or any(type(value[key]) is not bool for key in ('node_ready','full_original_audit_completed','consensus_signing'))
            or value['phase'] not in ('STARTING','INVENTORY','ARCHIVE_AUDIT','ARCHIVE_RESTORE','VERIFY_HISTORY',
                'VERIFY_SDK_BINDINGS','SDK_START','READY','FAILED','STOP_PENDING','STOPPED','UNAVAILABLE')
            or type(value['last_error']) is not str or len(value['last_error'])>128
            or any(value[key] is not None and not counter(value[key]) for key in ('processed_height','verified_through'))):return False
    ready=value['phase']=='READY'
    return (value['node_ready']==ready and value['consensus_signing']==(ready and role=='VALIDATOR')
        and (not ready or value['full_original_audit_completed'])
        and (value['verified_through'] is None or ready and value['full_original_audit_completed']))


def observation_root():
    return Path(DATA_HOME) / 'goldgoblins' / 'node-observations'


def _no_secrets(value):
    if isinstance(value, dict):
        if FORBIDDEN.intersection(value):
            raise ValueError('GG_NODE_OBSERVATION_PRIVATE_FIELD')
        for child in value.values():
            _no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _no_secrets(child)


def _process_started(pid):
    import psutil
    process = psutil.Process(pid)
    if os.name == 'nt':
        if process.username().casefold() != psutil.Process().username().casefold():
            raise ValueError('GG_NODE_OBSERVATION_OWNER')
    elif process.uids().real != os.getuid():
        raise ValueError('GG_NODE_OBSERVATION_OWNER')
    return process.create_time()


class Publisher:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else observation_root()
        self.pid = os.getpid()
        self.started = _process_started(self.pid)
        self.name = f'cli-{self.pid}-{secrets.token_hex(8)}.json'
        self.path = self.root / self.name
        self.sequence = 0
        self._last_publish = -math.inf

    def publish(self, body):
        if not body.get('lan_setup', {}).get('active'):
            self.close()
            return
        now = time.monotonic()
        if now - self._last_publish < .25:
            return
        data = {key: deepcopy(body[key]) for key in FIELDS if key in body}
        setup = body.get('lan_setup', {})
        data['lan_setup'] = {'active': True, 'coordinator': setup.get('coordinator') is True,
            'allow_dag_transactions': setup.get('allow_dag_transactions') is True,
            'ephemeral_keys': setup.get('ephemeral_keys',True) is True,
            'new_pairing_after_restart': setup.get('new_pairing_after_restart',True) is True,
            'invites': [{key: row[key] for key in ('label', 'local', 'node_role', 'allow_dag_transactions','validator_invite_count') if key in row}
                        for row in setup.get('invites', [])[:3]]}
        _no_secrets(data)
        self.sequence += 1
        packet = {'schema': SCHEMA, 'pid': self.pid, 'process_started': self.started,
                  'sequence': self.sequence, 'published_monotonic': now,
                  'published_at': time.time(), 'body': data}
        raw = (json.dumps(packet, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')) + '\n').encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise ValueError('GG_NODE_OBSERVATION_SIZE')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('GG_NODE_OBSERVATION_PATH')
        set_private_mode(self.root, 0o700)
        temporary = self.path.with_suffix('.tmp')
        fd = secure_open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
            os.replace(temporary, self.path)
            self._last_publish = now
        finally:
            if temporary.exists():
                temporary.unlink()

    def close(self):
        # Only this process's exact file is removed; other CLI nodes are untouched.
        if self.root.is_symlink():
            return
        if self.path.exists() and not self.path.is_symlink():
            self.path.unlink()
        self._last_publish = -math.inf


class Reader:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else observation_root()
        self._lock = threading.RLock()
        self._packet = None
        self._revision = ()
        self._last_check = -math.inf
        self._body = None
        self._entries = {}
        self._handles = {}
        self._selected_key = None
        self._selected_handle = None
        self._selected_metadata = None
        self._selection_lost = False
        self._selection_generation = 0
        self._reader_handle = 'sources-' + secrets.token_hex(16)
        self._automatic_key = None
        self._sources = {'schema': 'gg.local-node-sources.v1', 'sources': [],
                         'state': 'NONE', 'selection': 'AUTOMATIC',
                         'selected_handle': None, 'selection_revision': 0,
                         'reader_handle': self._reader_handle}

    def _read(self, path, now):
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return None
        if os.name != 'nt' and (st.st_uid != os.getuid() or st.st_mode & 0o077):
            return None
        fd = secure_open(path, os.O_RDONLY | NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        packet = json.loads(raw)
        if (not isinstance(packet, dict) or packet.get('schema') != SCHEMA
                or type(packet.get('pid')) is not int or packet['pid'] <= 0
                or type(packet.get('sequence')) is not int or packet['sequence'] < 1
                or not isinstance(packet.get('body'), dict)):
            return None
        if not path.name.startswith('cli-'+str(packet['pid'])+'-'):
            return None
        stamp = packet.get('published_monotonic')
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not -1 <= now - stamp <= RETAIN_SECONDS:
            return None
        started = packet.get('process_started')
        if type(started) not in (int, float) or not math.isfinite(started):
            return None
        if abs(_process_started(packet['pid']) - started) > .01:
            return None
        body = packet['body']
        if (set(body) - (FIELDS | {'lan_setup'}) or not isinstance(body.get('lan_setup'),dict)
                or not isinstance(body.get('lan'),dict) or not isinstance(body.get('block_graph'),dict)
                or not body['lan_setup'].get('active')):
            return None
        scope=body.get('lan', {}).get('scope')
        source_scopes={'PRIVATE_LAN_SEGMENTED_SDK_EXPERIMENT':'SEGMENTED_SDK_CERTIFIED_VIEW',
                      'PRIVATE_LAN_FINANCIAL_SDK_EXPERIMENT':'FINANCIAL_SDK_CERTIFIED_VIEW',
                      'LOCAL_TESTNET_PROTOCOL_ACCEPTANCE':'FINANCIAL_SDK_CERTIFIED_VIEW'}
        if scope!='PRIVATE_LAN_SESSION_EXPERIMENT' and (scope not in source_scopes or body.get('mode')!=source_scopes[scope]):
            return None
        if scope=='LOCAL_TESTNET_PROTOCOL_ACCEPTANCE' and (body.get('environment')!='TESTNET'
                or not isinstance(body.get('protocol_network'),dict)
                or body['protocol_network'].get('mode')!='LOCAL_ACCEPTANCE'):
            return None
        network=body.get('protocol_network')
        if isinstance(network,dict) and network.get('recovery_startup') is not None:
            if not _valid_recovery(network['recovery_startup'],network.get('node_role')):return None
        _no_secrets(body)
        if 'local_history' in body:
            network = body.get('protocol_network') or {}
            role = network.get('node_role', body.get('role')) if isinstance(network, dict) else None
            if body.get('role') is not None and role != body['role']:
                role = None
            body['local_history'] = local_history_status.normalize_observation(
                body['local_history'], body.get('genesis_hash'), role,
                running=body.get('state') == 'RUNNING')
        return packet

    @staticmethod
    def _identity(body):
        """Only public source identities; balances/counters never form identity."""
        network = body.get('protocol_network') or {}
        lan = body.get('lan') or {}
        storage = lan.get('storage') or {}
        if not isinstance(network, dict) or not isinstance(storage, dict):
            raise ValueError('GG_NODE_OBSERVATION_SOURCE_IDENTITY')
        accounts = network.get('account_sources')
        if accounts is None:
            accounts = []
            for name in ('financial_account_profiles', 'own_financial_accounts'):
                values = body.get(name) or []
                if name == 'financial_account_profiles' and isinstance(values, dict):
                    values = values.get('profiles', [])
                if not isinstance(values, list):
                    raise ValueError('GG_NODE_OBSERVATION_SOURCE_IDENTITY')
                for row in values:
                    if isinstance(row, dict):
                        accounts.append({key: row[key] for key in ('profile', 'address', 'public_key') if key in row})
        if not isinstance(accounts, list) or len(accounts) > 256:
            raise ValueError('GG_NODE_OBSERVATION_SOURCE_IDENTITY')
        # Sort public records by encoding so reordering a profile list alone
        # cannot switch source, while adding/removing an account does require
        # a new explicit choice. The packet's no-secret check already ran.
        encoded = sorted({json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)
                          for row in accounts})
        identity = {'mode': body.get('mode'), 'chain_id': body.get('chain_id'),
                    'network_id': body.get('network_id'), 'genesis_hash': body.get('genesis_hash'),
                    'node_key': body.get('node_key'), 'role': network.get('node_role', body.get('role')),
                    'profile': network.get('source_profile', storage.get('profile')),
                    'native_profile': network.get('native_profile'),
                    'selected_account': (body.get('financial_account_profiles') or {}).get('selected_profile')
                        if isinstance(body.get('financial_account_profiles'), dict) else None,
                    'environment': body.get('environment'), 'accounts': encoded,
                    'owner_keys': storage.get('public_keys')}
        return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode('utf-8')).hexdigest()

    @staticmethod
    def _label(value):
        # Display only; this is neither a file path nor a command argument.
        if not isinstance(value, str):
            return ''
        return ''.join(character for character in value[:160]
                       if character >= ' ' and character != '\x7f'
                       and character not in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')

    def _metadata(self, packet, handle, now):
        body = packet['body']; network = body.get('protocol_network') or {}
        lan = body.get('lan') or {}; storage = lan.get('storage') or {}
        # Legacy PAIRING has an idle/stopped DAG motor while its LAN peer
        # is alive. Only v7 LOCAL_ACCEPTANCE uses outer STOPPED for the
        # actual native node. Availability supplies no finality/contact.
        stopped = (lan.get('state') == 'STOPPED'
                   or network.get('mode') == 'LOCAL_ACCEPTANCE' and body.get('state') == 'STOPPED')
        return {'handle': handle, 'label': self._label(lan.get('label')) or 'CLI',
                'source_profile': self._label(network.get('source_profile', storage.get('profile'))),
                'native_profile': self._label(network.get('native_profile')),
                'node_role': self._label(network.get('node_role', body.get('role', ''))),
                'environment': self._label(body.get('environment', '')),
                'stale': now - packet['published_monotonic'] > FRESH_SECONDS,
                'available': not stopped}

    def _present(self, now):
        entries = self._entries
        rows = [deepcopy(entry['metadata']) for entry in entries.values()]
        rows.sort(key=lambda row: (row['source_profile'], row['label'], row['handle']))
        selected = None
        selected_handle = None
        if self._selected_handle is not None:
            entry = entries.get(self._selected_key)
            if (not self._selection_lost and entry is not None
                    and entry['handle'] == self._selected_handle and entry['metadata']['available']):
                selected = entry['packet']; selected_handle = self._selected_handle
            else:
                self._selection_lost = True
            state = 'SELECTED' if selected is not None else 'UNAVAILABLE'
            selected_handle = self._selected_handle
        else:
            fresh = [(key, entry) for key, entry in entries.items()
                     if entry['metadata']['available'] and not entry['metadata']['stale']]
            if len(fresh) == 1:
                self._automatic_key, entry = fresh[0]
                selected = entry['packet']; selected_handle = entry['handle']
            elif not fresh and self._automatic_key in entries:
                entry = entries[self._automatic_key]
                if entry['metadata']['available']:
                    selected = entry['packet']; selected_handle = entry['handle']
            else:
                self._automatic_key = None
            state = 'SELECTED' if selected is not None else 'CHOICE_REQUIRED' if rows else 'NONE'
        self._sources = {'schema': 'gg.local-node-sources.v1', 'reader_handle': self._reader_handle,
                         'selection_revision': self._selection_generation,
                         'selection': 'EXPLICIT' if self._selected_handle is not None else 'AUTOMATIC',
                         'selected_handle': selected_handle, 'state': state, 'sources': rows,
                         'selected_source': deepcopy(self._selected_metadata) if self._selected_handle is not None else
                             next((deepcopy(row) for row in rows if row['handle'] == selected_handle), None)}
        catalog_revision = tuple((key, row['handle'], row['packet']['sequence'], row['metadata']['stale'],
                                  row['metadata']['available']) for key, row in sorted(entries.items()))
        self._revision = ((self._reader_handle, self._selection_generation, selected_handle, state, catalog_revision)
                          if rows or self._selected_handle is not None else ())
        if selected is None:
            self._body = None; self._packet = None
            return
        self._packet = selected
        age = max(0, now - selected['published_monotonic'])
        body = deepcopy(selected['body'])
        stale = age > FRESH_SECONDS
        body['observation'] = {'source': 'LOCAL_CLI', 'read_only': True, 'stale': stale,
            'age_seconds': round(age, 1), 'node_label': body.get('lan', {}).get('label', ''),
            'source_handle': selected_handle, 'reader_handle': self._reader_handle,
            'selection_revision': self._selection_generation,
            'publication_sequence': selected['sequence'], 'publisher_started_at': selected['process_started'],
            'basis': 'PUBLIC_STATUS_FROM_SAME_USER_OWNED_PROCESS'}
        if stale:
            body['node_ready']=False;body['consensus_signing']=False
            recovery=(body.get('protocol_network') or {}).get('recovery_startup')
            if isinstance(recovery,dict):recovery.update(phase='UNAVAILABLE',node_ready=False,consensus_signing=False,
                verified_through=None,full_original_audit_completed=False)
            body['lan'].update(connection_state='STALE', authenticated_peers=[])
            body['block_graph'].update(stale=True)
            local_history = body.get('local_history')
            if isinstance(local_history, dict) and local_history.get('state') == 'READY':
                local_history['state'] = 'STALE'
            consensus = body.get('dag_consensus', {})
            if 'own_running' in consensus: consensus['own_running'] = None
            for row in consensus.get('profiles', []):
                row['owned_native_process'] = None
                if 'native_rpc_contact_fresh' in row: row['native_rpc_contact_fresh'] = False
            observers = body.get('native_observers', {})
            observers['own_connected'] = 0; observers['own_running'] = None
            for row in observers.get('profiles', []):
                row['owned_native_process'] = None
                row['local_state_read_from_owned_sdk'] = False
                contact = row.get('native_connection')
                if isinstance(contact, dict): contact.update(state='STALE', connected=False, stale=True)
        self._body = body
        self._revision += (int(age),)

    def _refresh(self):
        now = time.monotonic()
        if now - self._last_check < .25:
            return
        self._last_check = now
        packets = []
        if self.root.is_dir() and not self.root.is_symlink():
            try:
                with os.scandir(self.root) as entries:
                    for index, entry in enumerate(entries):
                        if index >= MAX_SOURCES * 2:
                            packets = []
                            break
                        if not NAME.fullmatch(entry.name):
                            continue
                        try:
                            path = Path(entry.path)
                            packet = self._read(path, now)
                            if packet:
                                identity = self._identity(packet['body'])
                        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
                            continue
                        except Exception as error:
                            import psutil
                            if not isinstance(error, psutil.Error):
                                raise
                            continue
                        if packet:
                            packets.append((path.name, packet, identity))
                        if len(packets) > MAX_SOURCES:
                            packets = []
                            break
            except OSError:
                packets = []
        entries = {}; handles = {}
        for name, packet, identity in packets:
            key = (name, packet['pid'], packet['process_started'], identity)
            handle = self._handles.get(key)
            if handle is None or self._selection_lost and handle == self._selected_handle:
                handle = 'observation-' + secrets.token_hex(16)
            handles[key] = handle
            entries[key] = {'packet': packet, 'handle': handle, 'metadata': self._metadata(packet, handle, now)}
        self._entries = entries; self._handles = handles
        self._present(now)

    def snapshot(self):
        with self._lock:
            self._refresh()
            return deepcopy(self._body)

    def telemetry_revision(self):
        with self._lock:
            self._refresh()
            return self._revision

    def view(self):
        """One coherent read: source list and body can never name different nodes."""
        with self._lock:
            self._refresh()
            return {'local_node_sources': deepcopy(self._sources), 'parallel_dag': deepcopy(self._body)}

    def select_source(self, handle):
        with self._lock:
            if type(handle) is not str or not HANDLE.fullmatch(handle):
                raise ValueError('GG_NODE_OBSERVATION_SOURCE')
            self._refresh()
            match = next(((key, row) for key, row in self._entries.items()
                          if row['handle'] == handle and row['metadata']['available']), None)
            if match is None:
                raise ValueError('GG_NODE_OBSERVATION_SOURCE_UNAVAILABLE')
            key, row = match
            self._selected_key = key; self._selected_handle = handle
            self._selected_metadata = deepcopy(row['metadata']); self._selection_lost = False
            self._selection_generation += 1
            self._present(time.monotonic())
            return self.view()


_reader = None
_reader_lock = threading.Lock()


def source_reader():
    global _reader
    root = observation_root()
    with _reader_lock:
        if _reader is None or _reader.root != root:
            _reader = Reader(root)
        return _reader


def active_source():
    reader = source_reader()
    return reader if reader.telemetry_revision() else None


def select_observation_source(handle):
    """Read-only UI choice, independent of wallet or desktop-only imports."""
    from backend import lan_dag_runtime
    if lan_dag_runtime.active_manager() is not None:
        raise ValueError('GG_NODE_OBSERVATION_OWNED_NODE_ACTIVE')
    value = source_reader().select_source(handle)
    value['local_node_sources']['view_available'] = True
    value['lan_dag'] = value['parallel_dag']
    return value
