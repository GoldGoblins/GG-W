"""Bounded per-user, read-only observations of an explicitly started CLI node.

Only the public LAN status is shared. No wallet, signer, command channel, socket
or node is created by a reader. The CLI remains the sole owner of its work.
"""
from __future__ import annotations

from copy import deepcopy
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

SCHEMA = 'gg.local-node-observation.v1'
MAX_BYTES = 1024 * 1024
MAX_SOURCES = 16
FRESH_SECONDS = 5.0
RETAIN_SECONDS = 60.0
NAME = re.compile(r'^cli-[0-9]+-[0-9a-f]{16}\.json$')
FIELDS = frozenset(('state mode chain_id producer_count worker_count producers finality '
    'canonical_finalized blocks_admitted transactions_validated frontier_size wave_count '
    'limits last_wave live measurements preview admission block_graph events lan dag_stress '
    'dag_resources test_tokens token_circle protocol_fault test_accounts').split())
FORBIDDEN = frozenset(('private_key secret_key seed mnemonic password secret signer account_keys').split())


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
            'invites': [{key: row[key] for key in ('label', 'local', 'allow_dag_transactions') if key in row}
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
        if body.get('lan', {}).get('scope') != 'PRIVATE_LAN_SESSION_EXPERIMENT':
            return None
        _no_secrets(body)
        return packet

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
                            packet = self._read(Path(entry.path), now)
                        except (OSError, ValueError, TypeError, RecursionError):
                            continue
                        except Exception as error:
                            import psutil
                            if not isinstance(error, psutil.Error):
                                raise
                            continue
                        if packet:
                            packets.append(packet)
                        if len(packets) > MAX_SOURCES:
                            packets = []
                            break
            except OSError:
                packets = []
        # Never choose another account/node silently when multiple CLI nodes run.
        fresh = [p for p in packets if now - p['published_monotonic'] <= FRESH_SECONDS]
        selected = fresh[0] if len(fresh) == 1 else None
        if selected is None and not fresh and self._packet is not None:
            selected = next((p for p in packets if p['pid'] == self._packet['pid']
                             and p['process_started'] == self._packet['process_started']), None)
        if selected is None:
            self._body = None; self._revision = (); self._packet = None
            return
        self._packet = selected
        age = max(0, now - selected['published_monotonic'])
        body = deepcopy(selected['body'])
        stale = age > FRESH_SECONDS
        body['observation'] = {'source': 'LOCAL_CLI', 'read_only': True, 'stale': stale,
            'age_seconds': round(age, 1), 'node_label': body.get('lan', {}).get('label', ''),
            'publication_sequence':selected['sequence'],'publisher_started_at':selected['process_started'],
            'basis': 'PUBLIC_STATUS_FROM_SAME_USER_OWNED_PROCESS'}
        if stale:
            body['lan'].update(connection_state='STALE', authenticated_peers=[])
            body['block_graph'].update(stale=True)
        self._body = body
        self._revision = ('LOCAL_CLI', selected['pid'], selected['process_started'],
                          selected['sequence'], stale, int(age))

    def snapshot(self):
        with self._lock:
            self._refresh()
            return deepcopy(self._body)

    def telemetry_revision(self):
        with self._lock:
            self._refresh()
            return self._revision


_reader = None


def active_source():
    global _reader
    root = observation_root()
    if _reader is None or _reader.root != root:
        _reader = Reader(root)
    return _reader if _reader.telemetry_revision() else None
