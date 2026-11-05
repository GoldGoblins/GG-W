#!/usr/bin/env python3
"""Prepare public TESTNET ceremony file specifications, without opening profiles.

This is an offline recipe writer. The CLI assembly commands separately require
the installed native validator; a prepared recipe is not a genesis certificate.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).absolute().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import gg_consensus_membership as membership
from backend import gg_financial_economy as economy
from backend import gg_financial_protocol as protocol
from backend import gg_protocol_provisioning as provisioning
from backend.gg_protocol_setup import _path, read_public, write_public
from backend.platform_files import secure_open

POLICY_SCHEMA = 'gg.protocol.operator-test-policy.v1'
POLICY_FIELDS = {'schema', 'economics', 'protocol', 'max_accounts',
                 'initial_voting_power', 'allocation_rule'}
INVALID = 'GG_PROTOCOL_CEREMONY_INVALID'


def _argument_path(value):
    """Resolve against the caller's cwd, without following links or junctions."""
    original = _path(value)
    return str(_path(os.path.abspath(original)))


def _unique_paths(values, minimum, maximum):
    if not isinstance(values, list) or not minimum <= len(values) <= maximum:
        raise ValueError(INVALID)
    paths = [_argument_path(value) for value in values]
    if len({os.path.normcase(path) for path in paths}) != len(paths):
        raise ValueError(INVALID)
    return paths


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError(INVALID)
        result[key] = value
    return result


def _constant(_value):
    raise ValueError(INVALID)


def _read_policy(path):
    # The checked-in policy is readable, indented JSON. All signed ceremony
    # inputs use the existing strict canonical public-file reader instead.
    with os.fdopen(secure_open(path, os.O_RDONLY, 0o600), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= 32 * 1024):
            raise ValueError(INVALID)
        raw = stream.read(32 * 1024 + 1)
    if len(raw) > 32 * 1024:
        raise ValueError(INVALID)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                       parse_constant=_constant)
    if (not isinstance(value, dict) or set(value) != POLICY_FIELDS
            or value['schema'] != POLICY_SCHEMA
            or value['max_accounts'] != '4294967296'
            or value['initial_voting_power'] != '1'
            or value['allocation_rule'] != 'EQUAL_INITIAL_GOVERNANCE_ACCOUNTS'):
        raise ValueError(INVALID)
    value = deepcopy(value)
    value['economics'] = economy.validate_policy(value['economics'])
    limits = value['protocol']
    if not isinstance(limits, dict) or set(limits) != provisioning.LIMIT_FIELDS:
        raise ValueError(INVALID)
    economy._number(limits['expected_blocks_per_epoch'], 10**9, positive=True)
    economy._integer(limits['max_committee_change_bps'], 3333, positive=True)
    participants = economy._number(limits['max_epoch_participants'], 65536, positive=True)
    economy._number(limits['max_producer_entries'], 2**32, positive=True)
    if economy._number(limits['max_work_heights'], 65536) < 8:
        raise ValueError(INVALID)
    for name in ('initial_work_target', 'min_work_target', 'max_work_target',
                 'registration_work_target'):
        if int(protocol._hash(limits[name]), 16) == 0:
            raise ValueError(INVALID)
    if (not limits['min_work_target'] <= limits['initial_work_target'] <= limits['max_work_target']
            or limits['registration_work_target'] > limits['max_work_target']
            or participants == 65536 and value['economics']['treasury_bps']):
        raise ValueError(INVALID)
    economics = value['economics']
    if (int(economy.minimum_fee(economics, 128 * 1024)) >= int(economics['max_supply_atomic'])
            or economics['initial_supply_atomic'] == '0' and economics['epoch_reward_atomic'] == '0'):
        raise ValueError(INVALID)
    return value


def prepare_genesis(context_path, validator_paths, producer_paths, policy_path):
    """Return only a public file recipe; never invoke the native subprocess."""
    context_path = _argument_path(context_path)
    policy_path = _argument_path(policy_path)
    context = provisioning.validate_context(read_public(context_path, 4096))
    policy = _read_policy(policy_path)
    validator_paths = _unique_paths(validator_paths, 4, 64)
    producer_paths = _unique_paths(producer_paths, 1, 128)
    validators = [(path, membership.validate_invite(read_public(path, 4096)))
                  for path in validator_paths]
    validators.sort(key=lambda row: row[1]['validator_key'])
    if (len({body['validator_key'] for _, body in validators}) != len(validators)
            or len({(body['host'], body['p2p_port']) for _, body in validators}) != len(validators)):
        raise ValueError(INVALID)
    members = [{**{name: body[name] for name in
                   ('validator_key', 'node_key', 'owner_peer_key', 'account_key')},
                'power': policy['initial_voting_power']} for _, body in validators]
    economy.validate_committee({'schema': 'gg.financial.public-committee.v1',
                                'epoch': '0', 'members': members})
    minimal = {'chain_id': context['chain_id'],
               'financial_dag': {'network_id': context['network_id']}}
    producers = [(path, protocol.validate_invite(read_public(path, 4096), minimal)['body'])
                 for path in producer_paths]
    producers.sort(key=lambda row: row[1]['producer_key'])
    if (len({body['producer_key'] for _, body in producers}) != len(producers)
            or len(producers) > int(policy['protocol']['max_producer_entries'])):
        raise ValueError(INVALID)
    # Match the public genesis role-separation rule. A shared owner or node is
    # permitted only in its same role and under its same owner identity.
    roles = {}

    def reserve(key, owner, role):
        if key in roles and roles[key] != (owner, role):
            raise ValueError(INVALID)
        roles[key] = (owner, role)

    accounts = {}
    for path, body in validators:
        owner = body['owner_peer_key']
        for name, role in (('validator_key', 'VALIDATOR'), ('node_key', 'NODE'),
                           ('owner_peer_key', 'OWNER'), ('account_key', 'GOVERNANCE')):
            reserve(body[name], owner, role)
        accounts.setdefault(body['account_key'], path)
    wallets = set(accounts)
    for _, body in producers:
        for name, role in (('producer_key', 'PRODUCER'), ('node_key', 'NODE'),
                           ('owner_peer_key', 'OWNER')):
            reserve(body[name], body['owner_peer_key'], role)
        wallets.add(body['reward_account'])
    if policy['economics']['treasury_bps']:
        wallets.add(policy['economics']['treasury_account'])
    if any(roles[key][1] != 'GOVERNANCE' for key in wallets & roles.keys()):
        raise ValueError(INVALID)
    initial = int(policy['economics']['initial_supply_atomic'])
    balance, remainder = divmod(initial, len(accounts))
    if remainder:
        raise ValueError(INVALID)
    # Zero initial supply is valid only as no allocations, never zero balances.
    allocations = [{'source_path': accounts[key], 'balance_atomic': str(balance)}
                   for key in sorted(accounts)] if initial else []
    return {'schema': 'gg.protocol.genesis-file-spec.v1',
            'context_path': context_path,
            'validators': [{'invite_path': path, 'power': policy['initial_voting_power']}
                           for path, _ in validators],
            'producer_invite_paths': [path for path, _ in producers],
            'allocations': allocations, 'max_accounts': policy['max_accounts'],
            'economics': policy['economics'], 'protocol': policy['protocol']}


def prepare_bootstrap(pin_path, validator_paths, endorsement_paths):
    """Check public proofs and all initial acceptances; write no certificate."""
    pin_path = _argument_path(pin_path)
    pin = protocol.validate_pin(read_public(pin_path, 256 * 1024))
    if pin['genesis']['protocol']['environment'] != 'TESTNET':
        raise ValueError(INVALID)
    validator_paths = _unique_paths(validator_paths, 4, 64)
    endorsement_paths = _unique_paths(endorsement_paths, 4, 64)
    invites = [read_public(path, 4096) for path in validator_paths]
    endorsements = [read_public(path, 4096) for path in endorsement_paths]
    # Both validators are pure cryptographic checks. Assembly, separately, must
    # repeat these checks and validate the pin with the installed native core.
    provisioning._validator_invites(pin, invites)
    provisioning._endorsements(pin, endorsements)
    validator_paths = [path for _, path in sorted(
        (value['body']['validator_key'], path) for path, value in zip(validator_paths, invites))]
    endorsement_paths = [path for _, path in sorted(
        (value['body']['validator_key'], path) for path, value in zip(endorsement_paths, endorsements))]
    return {'schema': 'gg.protocol.bootstrap-file-spec.v1', 'pin_path': pin_path,
            'validator_invite_paths': validator_paths, 'endorsement_paths': endorsement_paths}


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError(INVALID)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    bootstrap = bool(arguments and arguments[0] == 'bootstrap')
    if bootstrap:
        arguments.pop(0)
    parser = _Parser(description=__doc__)
    if bootstrap:
        parser.add_argument('--pin', required=True)
        parser.add_argument('--endorsement', action='append', required=True)
    else:
        parser.add_argument('--context', required=True)
        parser.add_argument('--producer-invite', action='append', required=True)
        parser.add_argument('--policy', required=True)
    parser.add_argument('--validator-invite', action='append', required=True)
    parser.add_argument('--output', required=True)
    try:
        args = parser.parse_args(arguments)
        document = (prepare_bootstrap(args.pin, args.validator_invite, args.endorsement)
                    if bootstrap else prepare_genesis(args.context, args.validator_invite,
                                                     args.producer_invite, args.policy))
        write_public(_argument_path(args.output), document)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError, UnicodeError):
        print(json.dumps({'error': INVALID, 'prepared': False}, separators=(',', ':')), file=sys.stderr)
        return 1
    print(json.dumps({'prepared': True, 'public_only': True,
                      'native_validation_performed': False, 'node_started': False}, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
