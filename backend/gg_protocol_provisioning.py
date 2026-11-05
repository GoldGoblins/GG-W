"""Explicit TESTNET genesis ceremony using owned keys and public documents.

Import/read creates no account, key, file, listener or node. Public role proofs
are separate from every initial voter's durable acceptance of the exact final
genesis. Native validation is mandatory before assembly/acceptance/export.
"""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_financial_dag as financial,gg_consensus as native
from backend import gg_consensus_membership as membership
from backend.gg_node_store import NodeProfile,pack
from backend.gg_native_start import native_pipe_creation_flags
from backend import gg_native_pipe_lifecycle as native_pipes
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_financial_account import AccountProfile
from backend.gg_ed25519 import SIGNATURE_PROFILE
from backend.gg_protocol_operations import make_producer_invite

CONTEXT_SPEC='gg.protocol.context-spec.v1'
CONTEXT='gg.protocol.network-context.v1'
SPEC='gg.protocol.genesis-spec.v1'
ACCEPTANCE='gg.protocol.genesis-acceptance.v1'
BOOTSTRAP='gg.protocol.testnet-bootstrap.v1'
ACCEPT_DOMAIN=b'GG-PROTOCOL-GENESIS-ACCEPT-v1\0'
MAX_BUNDLE=512*1024
CONTEXT_FIELDS={'schema','chain_id','network_id','genesis_time_unix','environment'}
SPEC_FIELDS={'schema','context','financial_accounts','economics','voting_powers','protocol'}
LIMIT_FIELDS={'expected_blocks_per_epoch','initial_work_target','min_work_target','max_work_target','registration_work_target',
              'max_committee_change_bps','max_epoch_participants','max_producer_entries','max_work_heights'}
ACCEPT_BODY={'schema','genesis_hash','validator_key','node_key','account_key','owner_peer_key'}
SIG_FIELDS={role+'_signature' for role in ('validator','node','account','owner')}
NATIVE_FIELDS={'schema','verified','genesis_hash','chain_id','initial_state_root','voter_count','producer_count','environment','certificate_asserted'}


def _bounded(value,maximum,code):
    try:
        if len(pack(value))>maximum:raise ValueError(code)
    except (TypeError,OverflowError,RecursionError,UnicodeError):raise ValueError(code) from None


def _context(value,schemas):
    if not isinstance(value,dict) or set(value)!=CONTEXT_FIELDS or type(value['schema']) is not str or value['schema'] not in schemas:raise ValueError('GG_PROTOCOL_CONTEXT')
    _bounded(value,4096,'GG_PROTOCOL_CONTEXT')
    if value['environment']!='TESTNET' or type(value['chain_id']) is not str or not re.fullmatch(r'ggnet:[0-9a-f]{24}',value['chain_id']):raise ValueError('GG_PROTOCOL_CONTEXT')
    protocol._hash(value['network_id'])
    economy._integer(value['genesis_time_unix'],(financial.MAX_COUNTER-5_000_000_000)//10**9,positive=True)
    return {**deepcopy(value),'schema':CONTEXT}


def create_context(specification):return _context(specification,{CONTEXT_SPEC})
def validate_context(context):return _context(context,{CONTEXT})


def _owned(owner,validator,account,*,governance=False):
    if (type(owner) is not NodeProfile or owner._lease is None or owner._db is None or owner._closed or owner._failed
            or type(validator) is not ValidatorProfile or validator._lease is None or validator._closed or validator._failed
            or type(account) is not AccountProfile or account._lease is None or account._closed or account._failed):raise ValueError('GG_PROTOCOL_OWNED_PROFILES_REQUIRED')
    account._check()
    invite=validator.public_invite();body=membership.validate_invite(invite)
    if body['owner_peer_key']!=owner.descriptor()['public_keys'][0]:raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
    if governance:
        reference=validator.account_reference()
        if reference is None or reference!={'profile':account.name,'public_key':account.public_address()} or body['account_key']!=account.public_address():raise ValueError('GG_VALIDATOR_OWNED_ACCOUNT_REQUIRED')
    return body


def _profile_types(owner,validator,account):
    if type(owner) is not NodeProfile or type(validator) is not ValidatorProfile or type(account) is not AccountProfile:
        raise ValueError('GG_PROTOCOL_OWNED_PROFILES_REQUIRED')


def initial_producer_invite(owner,validator,account,context,slot,label,platform):
    context=validate_context(context)
    _profile_types(owner,validator,account)
    if type(slot) is not int or slot not in (0,1):raise ValueError('GG_PROTOCOL_PRODUCER_SLOT')
    if (type(label) is not str or not 1<=len(label.encode('utf-8'))<=96 or any(ord(char)<32 or ord(char)==127 for char in label)
            or platform not in ('windows','linux','termux','other')):raise ValueError('GG_PROTOCOL_INITIAL_PRODUCER_LABEL')
    with account._lock,owner._lock,validator._lock:
        _owned(owner,validator,account)
        # Initial registration consumes neither a monetary nonce nor a fee.
        # Once bound, re-export only the already accepted original invitation.
        pins=[value for value in (validator.anchor(),account.anchor()) if value is not None]
        if pins:
            pin=protocol.validate_pin(pins[0])
            if any(value!=pin for value in pins):raise ValueError('GG_PROTOCOL_SIGNING_ANCHOR')
            actual={'schema':CONTEXT,'chain_id':pin['genesis']['chain_id'],'network_id':pin['genesis']['financial_dag']['network_id'],
                    'genesis_time_unix':pin['genesis']['genesis_time_unix'],'environment':pin['genesis']['protocol']['environment']}
            if actual!=context or type(slot) is not int or slot not in (0,1):raise ValueError('GG_PROTOCOL_SIGNING_ANCHOR')
            key=owner.descriptor()['public_keys'][slot+1]
            matches=[value for value in pin['genesis']['protocol']['initial_producers'] if value['body']['producer_key']==key]
            if len(matches)!=1:raise ValueError('GG_PROTOCOL_INITIAL_PRODUCER_NOT_FOUND')
            value=protocol.validate_invite(matches[0],pin['genesis']);body=value['body']
            expected={'node_key':validator.public_invite()['body']['node_key'],'owner_peer_key':owner.descriptor()['public_keys'][0],
                      'reward_account':account.public_address(),'label_utf8':base64.b64encode(label.encode('utf-8')).decode(),'platform':platform}
            if any(body[name]!=item for name,item in expected.items()):raise ValueError('GG_PROTOCOL_INITIAL_PRODUCER_CHANGED')
            return value
        if owner._schema_version!=3 or owner.session() is not None or owner._head['entries']:
            raise ValueError('GG_PROTOCOL_FRESH_OWNER_REQUIRED')
        minimal={'genesis':{'chain_id':context['chain_id'],'financial_dag':{'network_id':context['network_id']}}}
        return make_producer_invite(owner,validator,minimal,slot,account.public_address(),label=label,platform=platform)


def validate_pin_native(pin,*,binary=None,stamp=None):
    pin=protocol.validate_pin(pin)
    if pin['genesis']['protocol']['environment']!='TESTNET':raise ValueError('GG_PROTOCOL_LOCAL_TESTNET_REQUIRED')
    raw=pack(pin)
    if len(raw)>256*1024:raise ValueError('GG_PROTOCOL_GENESIS_LIMIT')
    binary=Path(native._installed_binary(native.TOOLS) if binary is None else binary)
    if stamp is None:stamp=native._validate_binary_at(binary.parent,binary)
    info=binary.stat()
    if (info.st_size,info.st_mtime_ns)!=stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
    environment=native._environment();environment['GOMEMLIMIT']='96MiB'
    try:
        result=native_pipes.GENESIS_VALIDATE.run([str(binary),'validate-protocol-genesis'],input=raw,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              env=environment,timeout=6,creationflags=native_pipe_creation_flags())
        info=binary.stat()
        if (info.st_size,info.st_mtime_ns)!=stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
        if result.returncode or not 0<len(result.stdout)<=8192:raise ValueError('GG_PROTOCOL_NATIVE_GENESIS_INVALID')
        answer=json.loads(result.stdout)
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError,UnicodeError):raise ValueError('GG_PROTOCOL_NATIVE_GENESIS_INVALID') from None
    if (not isinstance(answer,dict) or pack(answer)!=result.stdout or set(answer)!=NATIVE_FIELDS or answer['schema']!='gg.protocol.genesis-validation.v1'
            or answer['verified'] is not True or answer['environment']!='TESTNET' or answer['certificate_asserted'] is not False
            or answer['genesis_hash']!=pin['genesis_hash'] or answer['chain_id']!=pin['genesis']['chain_id']
            or type(answer['voter_count']) is not int or answer['voter_count']!=len(pin['genesis']['validators'])
            or type(answer['producer_count']) is not int or answer['producer_count']!=len(pin['genesis']['financial_dag']['producers'])):
        raise ValueError('GG_PROTOCOL_NATIVE_GENESIS_INVALID')
    protocol._hash(answer['initial_state_root'])
    return deepcopy(answer)


def _validator_invites(pin,invites):
    if not isinstance(invites,list) or not 4<=len(invites)<=64:raise ValueError('GG_PROTOCOL_INITIAL_VALIDATORS')
    members={row['validator_key']:row for row in pin['genesis']['protocol']['committee']['members']}
    found={};endpoints=set()
    for invite in invites:
        body=membership.validate_invite(invite);key=body['validator_key'];member=members.get(key)
        if key in found or member is None or any(body[field]!=member[field] for field in ('node_key','owner_peer_key','account_key')):raise ValueError('GG_PROTOCOL_INITIAL_VALIDATORS')
        endpoint=(body['host'],body['p2p_port'])
        if endpoint in endpoints:raise ValueError('GG_PROTOCOL_INITIAL_ENDPOINT_COLLISION')
        endpoints.add(endpoint);found[key]=deepcopy(invite)
    if set(found)!=set(members):raise ValueError('GG_PROTOCOL_INITIAL_VALIDATORS')
    return [found[key] for key in sorted(found)]


def assemble(spec,validator_invites,producer_invites,*,binary=None,stamp=None):
    if not isinstance(spec,dict) or set(spec)!=SPEC_FIELDS or spec['schema']!=SPEC:raise ValueError('GG_PROTOCOL_GENESIS_SPECIFICATION')
    _bounded(spec,256*1024,'GG_PROTOCOL_GENESIS_SPECIFICATION')
    context=validate_context(spec['context']);policy=economy.validate_policy(spec['economics'])
    if not isinstance(spec['protocol'],dict) or set(spec['protocol'])!=LIMIT_FIELDS:raise ValueError('GG_PROTOCOL_GENESIS_SPECIFICATION')
    if not isinstance(validator_invites,list) or not 4<=len(validator_invites)<=64:raise ValueError('GG_PROTOCOL_INITIAL_VALIDATORS')
    if not isinstance(producer_invites,list) or not 1<=len(producer_invites)<=128:raise ValueError('GG_PROTOCOL_INITIAL_PRODUCERS')
    powers={}
    if not isinstance(spec['voting_powers'],list) or not 4<=len(spec['voting_powers'])<=64:raise ValueError('GG_PROTOCOL_INITIAL_POWER')
    for row in spec['voting_powers']:
        if not isinstance(row,dict) or set(row)!={'validator_key','power'}:raise ValueError('GG_PROTOCOL_INITIAL_POWER')
        key=financial.account_address(row['validator_key']);economy._number(row['power'],(1<<50)-1,positive=True)
        if key in powers:raise ValueError('GG_PROTOCOL_INITIAL_POWER')
        powers[key]=row['power']
    members=[]
    for invite in validator_invites:
        body=membership.validate_invite(invite);key=body['validator_key']
        if key not in powers or any(row['validator_key']==key for row in members):raise ValueError('GG_PROTOCOL_INITIAL_POWER')
        members.append({**{field:body[field] for field in ('validator_key','node_key','owner_peer_key','account_key')},'power':powers[key]})
    if set(powers)!={row['validator_key'] for row in members}:raise ValueError('GG_PROTOCOL_INITIAL_POWER')
    members.sort(key=lambda row:row['validator_key'])
    minimal={'chain_id':context['chain_id'],'financial_dag':{'network_id':context['network_id']}}
    producers=[protocol.validate_invite(value,minimal) for value in producer_invites]
    producers.sort(key=lambda value:value['body']['producer_key'])
    if len({value['body']['producer_key'] for value in producers})!=len(producers):raise ValueError('GG_PROTOCOL_INITIAL_PRODUCERS')
    allocation=deepcopy(spec['financial_accounts'])
    if not isinstance(allocation,dict) or set(allocation)!={'schema','allocations','max_accounts'} or not isinstance(allocation['allocations'],list):raise ValueError('GG_PROTOCOL_GENESIS_ALLOCATION')
    try:allocation['allocations'].sort(key=lambda row:row['address'])
    except (KeyError,TypeError):raise ValueError('GG_PROTOCOL_GENESIS_ALLOCATION') from None
    source={'schema':protocol.SOURCE,'allowed_producers':[],'native_chain_id':context['chain_id'],'network_id':context['network_id'],
            'policy':financial.policy(protocol.SOURCE),'producers':[value['body']['producer_key'] for value in producers],
            'signature_profile':SIGNATURE_PROFILE,'started_at_ns':str(context['genesis_time_unix']*10**9)}
    genesis={'schema':protocol.GENESIS,'accounts':None,'chain_id':context['chain_id'],'decimals':6,
             'financial_accounts':allocation,'financial_dag':source,'genesis_time_unix':context['genesis_time_unix'],
             'supply_atomic':policy['initial_supply_atomic'],'symbol':'GG-TEST','validators':[row['validator_key'] for row in members],
             'protocol':{**deepcopy(spec['protocol']),'schema':'gg.financial.protocol-genesis.v1','environment':'TESTNET',
                         'economics':policy,'committee':{'schema':'gg.financial.public-committee.v1','epoch':'0','members':members},'initial_producers':producers}}
    pin=protocol.validate_pin({'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()})
    _validator_invites(pin,validator_invites)
    validate_pin_native(pin,binary=binary,stamp=stamp)
    return pin


def _acceptance_message(body,pin):return ACCEPT_DOMAIN+pack({'body':body,'pin':pin})


def sign_bootstrap(owner,validator,account,pin,*,binary=None,stamp=None):
    _profile_types(owner,validator,account)
    pin=protocol.validate_pin(pin);validate_pin_native(pin,binary=binary,stamp=stamp)
    with account._lock,owner._lock,validator._lock:
        own=_owned(owner,validator,account,governance=True)
        matches=[row for row in pin['genesis']['protocol']['committee']['members'] if row['validator_key']==own['validator_key']]
        if len(matches)!=1 or any(matches[0][name]!=own[name] for name in ('node_key','owner_peer_key','account_key')):raise ValueError('GG_PROTOCOL_INITIAL_MEMBER_REQUIRED')
        body={'schema':ACCEPTANCE,'genesis_hash':pin['genesis_hash'],**{name:own[name] for name in ('validator_key','node_key','account_key','owner_peer_key')}}
        # Both existing journals bind before any acceptance signature escapes.
        # A crash after the account bind remains conservatively pinned and can
        # resume only this exact genesis; no new storage trust flag is added.
        validator.bind_protocol(pin,account=account)
        identity,_=owner.signers();voter,node=validator.native_signers()
        message=_acceptance_message(body,pin)
        return {'body':body,**{role+'_signature':key.sign_message(message).hex()
                              for role,key in (('validator',voter),('node',node),('account',account._key),('owner',identity))}}


def _endorsements(pin,values):
    if not isinstance(values,list) or not 4<=len(values)<=64:raise ValueError('GG_PROTOCOL_INITIAL_ACCEPTANCES')
    members={row['validator_key']:row for row in pin['genesis']['protocol']['committee']['members']};found={}
    for value in values:
        _bounded(value,4096,'GG_PROTOCOL_INITIAL_ACCEPTANCE')
        if not isinstance(value,dict) or set(value)!={'body',*SIG_FIELDS}:raise ValueError('GG_PROTOCOL_INITIAL_ACCEPTANCE')
        body=value['body']
        if not isinstance(body,dict) or set(body)!=ACCEPT_BODY or body['schema']!=ACCEPTANCE or body['genesis_hash']!=pin['genesis_hash']:raise ValueError('GG_PROTOCOL_INITIAL_ACCEPTANCE')
        key=body['validator_key']
        if type(key) is not str:raise ValueError('GG_PROTOCOL_INITIAL_ACCEPTANCE')
        member=members.get(key)
        if key in found or member is None or any(body[name]!=member[name] for name in ('node_key','account_key','owner_peer_key')):raise ValueError('GG_PROTOCOL_INITIAL_ACCEPTANCE')
        message=_acceptance_message(body,pin)
        for role,field in (('validator','validator_key'),('node','node_key'),('account','account_key'),('owner','owner_peer_key')):
            protocol._signature(body[field],value[role+'_signature'],message)
        found[key]=deepcopy(value)
    if set(found)!=set(members):raise ValueError('GG_PROTOCOL_INITIAL_ACCEPTANCES_INCOMPLETE')
    return [found[key] for key in sorted(found)]


def assemble_bootstrap(pin,validator_invites,endorsements,*,binary=None,stamp=None):
    pin=protocol.validate_pin(pin);validate_pin_native(pin,binary=binary,stamp=stamp)
    result={'schema':BOOTSTRAP,'pin':pin,'validator_invites':_validator_invites(pin,validator_invites),'endorsements':_endorsements(pin,endorsements)}
    _bounded(result,MAX_BUNDLE,'GG_PROTOCOL_BOOTSTRAP_LIMIT')
    return result


def validate_bootstrap(document,*,binary=None,stamp=None):
    _bounded(document,MAX_BUNDLE,'GG_PROTOCOL_BOOTSTRAP_LIMIT')
    if not isinstance(document,dict) or set(document)!={'schema','pin','validator_invites','endorsements'} or document['schema']!=BOOTSTRAP:raise ValueError('GG_PROTOCOL_BOOTSTRAP_DOCUMENT')
    result=assemble_bootstrap(document['pin'],document['validator_invites'],document['endorsements'],binary=binary,stamp=stamp)
    if document!=result:raise ValueError('GG_PROTOCOL_BOOTSTRAP_NONCANONICAL_ORDER')
    return result
