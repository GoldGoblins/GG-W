"""Public local history reports, separate from SDK proofs and peer contact.

Only the exact owned native process supplies a report. A light client cannot
inherit the server's history as its own. Cold audit height and current retained
height remain separate; no report grants signing or checkpoint authority.
"""
from copy import deepcopy
import math
import re
import time

SCHEMA = 'gg.financial.local-history-status.v1'
VIEW_SCHEMA = 'gg.protocol.local-history-observation.v1'
SCOPE = 'LOCAL_NATIVE_RUNTIME_REPORT_NOT_SDK_CERTIFICATE_OR_CONTACT'
FRESH_SECONDS = 5.0
COUNTERS = frozenset(('verified_through retained_through originals_first_height '
    'active_original_first_height active_original_last_height active_original_count '
    'active_bytes archive_segments archive_bytes archived_original_count disk_reserve_bytes').split())
BYTE_COUNTERS = frozenset(('active_bytes', 'archive_bytes'))
FIELDS = COUNTERS | {'schema', 'scope', 'genesis_hash', 'mode', 'state',
    'missing_archive_ranges', 'archive_fault', 'full_replay_required_on_cold_start', 'checkpoint_trusted'}
VIEW_FIELDS = frozenset(('schema scope state observed_at report last_error '
    'is_sdk_certificate is_peer_contact archive_health_basis').split())


def validate_report(value, genesis_hash):
    """Check the fixed, path-free contract without promoting it to a proof."""
    if (not isinstance(value, dict) or set(value) != FIELDS
            or value['schema'] != SCHEMA or value['scope'] != SCOPE
            or not isinstance(genesis_hash, str) or re.fullmatch('[0-9a-f]{64}', genesis_hash) is None
            or value['genesis_hash'] != genesis_hash or value['mode'] != 'FULL_REPLAY'
            or value['state'] not in ('READY', 'UNAVAILABLE')
            or value['missing_archive_ranges'] != []
            or value['archive_fault'] not in (None, 'GG_FINANCIAL_HISTORY_UNAVAILABLE')
            or value['full_replay_required_on_cold_start'] is not True
            or value['checkpoint_trusted'] is not False):
        raise ValueError('GG_PROTOCOL_LOCAL_HISTORY_REPORT')
    numbers = {}
    for key in COUNTERS:
        number = value[key]
        maximum = 2**64 - 1 if key in BYTE_COUNTERS else 2**63 - 1
        if (type(number) is not str or re.fullmatch('0|[1-9][0-9]{0,19}', number) is None
                or int(number) > maximum):
            raise ValueError('GG_PROTOCOL_LOCAL_HISTORY_REPORT')
        numbers[key] = int(number)
    retained = numbers['retained_through']
    active = numbers['active_original_count']
    archived = numbers['archived_original_count']
    if (numbers['verified_through'] > retained or active + archived != retained
            or numbers['originals_first_height'] != (1 if retained else 0)
            or numbers['active_original_first_height'] != (archived + 1 if active else 0)
            or numbers['active_original_last_height'] != (retained if active else 0)
            or value['disk_reserve_bytes'] != '8388608'
            or (value['state'] == 'READY') != (value['archive_fault'] is None)):
        raise ValueError('GG_PROTOCOL_LOCAL_HISTORY_REPORT')
    return deepcopy(value)


def observation(report, genesis_hash, role, *, running, observed_at=None, error=False, now=None):
    """Project only this process epoch, with explicit absence/staleness."""
    result = {'schema': VIEW_SCHEMA, 'scope': SCOPE, 'state': 'UNOBSERVED',
        'observed_at': None, 'report': None, 'last_error': '',
        'is_sdk_certificate': False, 'is_peer_contact': False,
        'archive_health_basis': 'LAST_FULL_REPLAY_AND_READ_TIME_CHECKS'}
    if role == 'LIGHT':
        result['state'] = 'NOT_APPLICABLE'
        return result
    if role not in ('VALIDATOR', 'REPLICA') or not running:
        result['state'] = 'UNAVAILABLE'
        return result
    if error:
        result.update(state='UNAVAILABLE', last_error='GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE')
        return result
    if report is None:
        return result
    try:
        checked = validate_report(report, genesis_hash)
    except (TypeError, ValueError):
        result.update(state='UNAVAILABLE', last_error='GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE')
        return result
    now = time.time() if now is None else now
    if (type(observed_at) not in (int, float) or not 0 <= observed_at <= 2**53 - 1 or not math.isfinite(observed_at)
            or type(now) not in (int, float) or not 0 <= now <= 2**53 - 1 or not math.isfinite(now)
            or observed_at > now):
        result.update(state='UNAVAILABLE', last_error='GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE')
        return result
    result.update(report=checked, observed_at=observed_at,
        state='UNAVAILABLE' if checked['state'] == 'UNAVAILABLE' else
            'READY' if now - observed_at <= FRESH_SECONDS else 'STALE',
        last_error=checked['archive_fault'] or '')
    return result


def normalize_observation(value, genesis_hash, role, *, running, now=None):
    """Recheck a public observation at the CLI/Desktop JSON boundary."""
    def unavailable():
        return observation(None, genesis_hash, role, running=running, error=True, now=now)
    if role == 'LIGHT':
        return observation(None, genesis_hash, role, running=running, now=now)
    if (not isinstance(value, dict) or set(value) != VIEW_FIELDS
            or value['schema'] != VIEW_SCHEMA or value['scope'] != SCOPE
            or value['is_sdk_certificate'] is not False or value['is_peer_contact'] is not False
            or value['archive_health_basis'] != 'LAST_FULL_REPLAY_AND_READ_TIME_CHECKS'
            or value['state'] not in ('READY', 'STALE', 'UNAVAILABLE', 'UNOBSERVED')
            or value['last_error'] not in ('', 'GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE', 'GG_FINANCIAL_HISTORY_UNAVAILABLE')):
        return unavailable()
    if value['report'] is None:
        if value['state'] not in ('UNAVAILABLE', 'UNOBSERVED') or value['observed_at'] is not None:
            return unavailable()
        return observation(None, genesis_hash, role, running=running,
            error=value['state'] == 'UNAVAILABLE' or bool(value['last_error']), now=now)
    if value['state'] == 'UNOBSERVED':
        return unavailable()
    if not isinstance(value['report'], dict) or value['last_error'] != (value['report'].get('archive_fault') or ''):
        return unavailable()
    result = observation(value['report'], genesis_hash, role, running=running,
        observed_at=value['observed_at'], now=now)
    if value['state'] == 'STALE' and result['state'] == 'READY':
        result['state'] = 'STALE'
    if value['state'] == 'UNAVAILABLE' and result['state'] in ('READY', 'STALE'):
        return unavailable()
    return result
