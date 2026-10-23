"""Read bounded local Wi-Fi/Bluetooth observations already held by the OS.

No discovery requests, connections, service probing or outbound HTTP. Values
are system cache observations, not geolocated devices or verified identities.
"""
from __future__ import annotations
import hashlib
import json
import secrets
import shutil
import subprocess
import time
from typing import Any

_LIMIT = 64
_SALT = secrets.token_bytes(16)


def _identity(kind: str, address: str) -> str:
    return hashlib.blake2s((kind + address).encode(), key=_SALT, digest_size=10).hexdigest()


def _run(args: list[str]) -> str:
    if not shutil.which(args[0]):
        raise OSError('System service tool unavailable')
    result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
    if result.returncode:
        raise OSError('System service unavailable')
    return result.stdout[:2_000_000]


def _fields(line: str) -> list[str]:
    fields, word, escaped = [], [], False
    for char in line:
        if escaped:
            word.append(char); escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(''.join(word)); word = []
        else:
            word.append(char)
    fields.append(''.join(word))
    return fields


def _wifi() -> list[dict[str, Any]]:
    output = _run(['nmcli', '--terse', '--escape', 'yes', '--fields', 'BSSID,SSID,SIGNAL,FREQ,ACTIVE',
                   'device', 'wifi', 'list', '--rescan', 'no'])
    rows, seen = [], set()
    for line in output.splitlines():
        fields = _fields(line)
        if len(fields) != 5 or not fields[0] or fields[0] in seen:
            continue
        seen.add(fields[0])
        try:
            strength = max(0, min(100, int(fields[2])))
        except ValueError:
            continue
        rows.append({'id': _identity('wifi', fields[0]), 'kind': 'wifi', 'name': fields[1][:80] or 'Dolt Wi-Fi-namn',
                     'signal': strength, 'signal_unit': '%', 'channel': fields[3][:24],
                     'connected': fields[4].lower() in ('yes', 'ja', 'true'),
                     'source': 'NetworkManager cache', 'freshness': 'AGE_UNKNOWN', 'classification': 'ACCESS_POINT'})
    return sorted(rows, key=lambda row: row['signal'], reverse=True)[:_LIMIT]


def _value(props: dict, key: str, default: Any = None) -> Any:
    value = props.get(key, default)
    return value.get('data', default) if isinstance(value, dict) else value


def _bluetooth() -> list[dict[str, Any]]:
    payload = json.loads(_run(['busctl', '--system', '--json=short', '--timeout=2', 'call',
                              'org.bluez', '/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects']))
    objects = payload.get('data', [])
    objects = objects[0] if isinstance(objects, list) and objects else objects
    if not isinstance(objects, dict):
        raise ValueError('Invalid Bluetooth response')
    rows = []
    for path, interfaces in objects.items():
        props = interfaces.get('org.bluez.Device1', {}) if isinstance(interfaces, dict) else {}
        signal = _value(props, 'RSSI')
        if not isinstance(signal, (int, float)) or not -127 <= signal <= 20:
            continue
        rows.append({'id': _identity('bluetooth', str(_value(props, 'Address', path))), 'kind': 'bluetooth',
                     'name': str(_value(props, 'Alias') or _value(props, 'Name') or 'Bluetooth-enhet')[:80],
                     'signal': int(signal), 'signal_unit': 'dBm', 'connected': bool(_value(props, 'Connected', False)),
                     'source': 'BlueZ cache', 'freshness': 'AGE_UNKNOWN', 'classification': 'UNCLASSIFIED'})
    return sorted(rows, key=lambda row: row['signal'], reverse=True)[:_LIMIT]


def collect() -> dict[str, Any]:
    rows, sources = [], []
    for kind, reader in (('wifi', _wifi), ('bluetooth', _bluetooth)):
        try:
            values = reader()
            rows.extend(values)
            sources.append({'kind': kind, 'status': 'CACHE', 'count': len(values)})
        except (OSError, ValueError, subprocess.SubprocessError):
            sources.append({'kind': kind, 'status': 'UNAVAILABLE', 'count': 0})
    return {'status': 'SYSTEM_CACHE' if any(row['status'] == 'CACHE' for row in sources) else 'UNAVAILABLE',
            'rows': rows, 'sources': sources, 'read_at': time.time(), 'device_positions': 'UNKNOWN'}
