"""Public-network configuration/readiness, independent of Qt, IO and engines.

TESTNET and MAINNET are separate environment descriptors, not launched chains.
No genesis, economic policy, peer, signer or cryptographic domain is generated
here. Syntactically valid proposed configuration cannot turn missing protocol
implementations into a ready public network.
"""
from __future__ import annotations

import ipaddress
import re

SCHEMA = 'gg.network-profiles.v1'
PROFILE_IDS = ('TESTNET', 'MAINNET')
ROLES = ('observer', 'full_node', 'producer')
PUBLIC_FIELDS = frozenset({'profile', 'chain_id', 'genesis_hash', 'transaction_domain',
                           'block_domain', 'role', 'bind_address', 'advertised_address', 'seed_peers'})
_DOMAIN = re.compile(r'^[A-Za-z][A-Za-z0-9_.:/-]{0,95}$')
_HASH = re.compile(r'^[0-9a-fA-F]{64}$')
_ADDRESS = re.compile(r'^(\[[0-9a-fA-F:]{2,64}\]|[A-Za-z0-9][A-Za-z0-9.-]{0,252}):([1-9][0-9]{0,4})$')

# Source-level facts only. Runtime/toolchain discovery is deliberately not an
# import side effect, and no command in this module starts or binds an engine.
LOCAL_ENGINES = (
    ('DAGOBLIN_LOCAL', 'LOCAL_RAM_SIGNED_PROPOSALS', 'Ed25519', False),
    ('EVM_LOCAL', 'OWNED_LOOPBACK_HARDHAT', 'LOCAL_TEST_ACCOUNTS', False),
    ('BFT_LOCAL', 'FIXED_LOCAL_COMETBFT_VALIDATORS', 'SDK_VERIFIED_LOCAL_CERTIFICATES', True),
)
BLOCKERS = (
    'PUBLIC_P2P_TRANSPORT_NOT_IMPLEMENTED',
    'PUBLIC_PEER_IDENTITY_AND_BOOTSTRAP_NOT_IMPLEMENTED',
    'CANONICAL_DAG_ORDERING_AND_FINALITY_NOT_IMPLEMENTED',
    'PERSISTENT_DAG_LEDGER_AND_RECOVERY_NOT_IMPLEMENTED',
    'POST_QUANTUM_SIGNATURES_NOT_IMPLEMENTED',
    'PERMISSIONLESS_ADMISSION_AND_ABUSE_LIMITS_NOT_VERIFIED',
    'PUBLIC_GENESIS_AND_SIGNING_DOMAINS_NOT_APPROVED',
    'MULTI_HOST_SAFETY_LIVENESS_AND_SECURITY_REVIEW_REQUIRED',
)


def profile_id(value):
    if not isinstance(value, str) or value.upper() not in PROFILE_IDS:
        raise ValueError('NETWORK_PROFILE_UNKNOWN')
    return value.upper()


def _address(value):
    if value is None:
        return None
    match = _ADDRESS.fullmatch(value) if isinstance(value, str) else None
    if match is None or int(match[2]) > 65535:
        raise ValueError('NETWORK_PROFILE_PEER_ADDRESS')
    host=match[1]
    try:
        if host.startswith('['):host='['+ipaddress.IPv6Address(host[1:-1]).compressed+']'
        elif re.fullmatch(r'[0-9.]+',host):host=str(ipaddress.IPv4Address(host))
        elif any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in host.split('.')):
            raise ValueError()
    except ValueError:
        raise ValueError('NETWORK_PROFILE_PEER_ADDRESS') from None
    return host.lower()+':'+str(int(match[2]))


def validate_configuration(profile, configuration):
    """Validate public syntax only; return a detached, still-unapproved value."""
    profile = profile_id(profile)
    if not isinstance(configuration, dict) or set(configuration)-PUBLIC_FIELDS:
        raise ValueError('NETWORK_PROFILE_ARGUMENTS')
    if profile_id(configuration.get('profile', profile)) != profile:
        raise ValueError('NETWORK_PROFILE_DOMAIN_MISMATCH')
    clean = {'profile': profile}
    for name in ('chain_id', 'transaction_domain', 'block_domain'):
        value = configuration.get(name)
        if value is not None and (not isinstance(value, str) or not _DOMAIN.fullmatch(value)):
            raise ValueError('NETWORK_PROFILE_DOMAIN')
        clean[name] = value
    if clean['transaction_domain'] is not None and clean['transaction_domain'] == clean['block_domain']:
        raise ValueError('NETWORK_PROFILE_SIGNING_DOMAINS_MUST_DIFFER')
    genesis = configuration.get('genesis_hash')
    if genesis is not None and (not isinstance(genesis, str) or not _HASH.fullmatch(genesis)):
        raise ValueError('NETWORK_PROFILE_GENESIS_HASH')
    clean['genesis_hash'] = genesis.lower() if genesis is not None else None
    role = configuration.get('role', 'observer')
    if role not in ROLES:
        raise ValueError('NETWORK_PROFILE_ROLE')
    clean['role'] = role
    clean['bind_address'] = _address(configuration.get('bind_address'))
    clean['advertised_address'] = _address(configuration.get('advertised_address'))
    peers = configuration.get('seed_peers', [])
    if not isinstance(peers, list) or len(peers) > 32:
        raise ValueError('NETWORK_PROFILE_PEER_LIMIT')
    clean['seed_peers'] = [_address(value) for value in peers]
    if any(value is None for value in clean['seed_peers']) or len(set(clean['seed_peers'])) != len(clean['seed_peers']):
        raise ValueError('NETWORK_PROFILE_PEERS')
    return clean


def validate_profile_pair(configurations):
    """Reject cross-environment replay domains even in proposed configuration."""
    if not isinstance(configurations, dict) or set(configurations) != set(PROFILE_IDS):
        raise ValueError('NETWORK_PROFILE_PAIR_REQUIRED')
    result = {name: validate_configuration(name, configurations[name]) for name in PROFILE_IDS}
    for field in ('chain_id', 'genesis_hash', 'transaction_domain', 'block_domain'):
        first, second = (result[name][field] for name in PROFILE_IDS)
        if first is not None and first == second:
            raise ValueError('NETWORK_PROFILE_ENVIRONMENTS_MUST_DIFFER')
    domains = [result[name][field] for name in PROFILE_IDS for field in ('transaction_domain', 'block_domain')
               if result[name][field] is not None]
    if len(domains) != len(set(domains)):
        raise ValueError('NETWORK_PROFILE_ENVIRONMENTS_MUST_DIFFER')
    return result


def readiness(profile, configuration=None):
    profile = profile_id(profile)
    configured = validate_configuration(profile, {} if configuration is None else configuration)
    required = ('chain_id', 'genesis_hash', 'transaction_domain', 'block_domain')
    missing = [name for name in required if configured[name] is None]
    return {
        'profile': profile,
        'environment_domain': profile,
        'configuration_state': 'UNCONFIGURED' if missing else 'VALIDATED_PUBLIC_SYNTAX',
        'configuration': configured,
        'missing_configuration': missing,
        'role_options': list(ROLES),
        'role_authority': 'DESCRIPTOR_ONLY_NO_NODE_OR_SIGNING_AUTHORITY',
        'public_network_state': 'NOT_IMPLEMENTED',
        'runnable_public': False,
        'deployment_ready': False,
        'mainnet_enabled': False,
        'blockers': list(BLOCKERS),
        'validation_scope': 'PUBLIC_SYNTAX_ONLY_NO_NETWORK_IO_OR_APPROVAL',
    }


def snapshot(profile=None):
    names = PROFILE_IDS if profile is None else (profile_id(profile),)
    return {
        'schema': SCHEMA,
        'profiles': [readiness(name) for name in names],
        'local_engines': [
            {'id': identifier, 'scope': scope, 'source_available': True,
             'runtime_available': None, 'runtime_probe': 'NOT_REQUESTED',
             'signature_or_certificate': signature,
             'local_canonical_certificates': certified,
             'public_network': False, 'quantum_resistant': False}
            for identifier, scope, signature, certified in LOCAL_ENGINES
        ],
        'public_networks_started': 0,
        'genesis_created': False,
        'keys_created': False,
        'peer_connections_created': 0,
    }
