"""Explicit offline operator ceremony and local start documents.

Only signed public documents leave protected profiles. These commands never
start a node, listener, miner or pool, and never choose monetary policy.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import time

from backend.gg_node_store import pack, unpack
from backend.gg_observer_profile import ObserverProfile
from backend import gg_financial_protocol as protocol
from backend import gg_consensus_membership as membership
from backend.platform_files import is_link, secure_open, set_private_mode, sync_directory

COMMANDS = {
    'protocol.context_create': {'path', 'spec_path'},
    'protocol.validator_invite_export': {'profile', 'path'},
    'protocol.account_export': {'profile', 'path'},
    'protocol.initial_producer_export': {'owner_profile', 'profile', 'context_path', 'producer_slot', 'label', 'platform', 'path'},
    'protocol.genesis_assemble': {'spec_path', 'path'},
    'protocol.genesis_review': {'path'},
    'protocol.genesis_endorse': {'owner_profile', 'profile', 'pin_path', 'path'},
    'protocol.bootstrap_assemble': {'spec_path', 'path'},
    'protocol.bootstrap_review': {'path'},
    'protocol.client_create': {'owner_profile', 'profile', 'bootstrap_path', 'label', 'role', 'path'},
    'protocol.client_export': {'owner_profile', 'profile', 'role', 'path'},
    'protocol.relay_endpoint_export': {'owner_profile', 'profile', 'bootstrap_path', 'host', 'port', 'path'},
    'protocol.start_plan': {'owner_profile', 'profile', 'bootstrap_path', 'role', 'output_dir', 'options_path', 'endpoint_path'},
}
PUBLIC_COMMANDS = frozenset({'protocol.context_create', 'protocol.genesis_assemble', 'protocol.genesis_review',
                             'protocol.bootstrap_assemble', 'protocol.bootstrap_review'})
ACCOUNT_DOMAIN = b'GG-PROTOCOL-ACCOUNT-CARD-v1\0'
CLIENT_DOMAIN = b'GG-PROTOCOL-CLIENT-CARD-v1\0'
ENDPOINT_DOMAIN = b'GG-PROTOCOL-RELAY-ENDPOINT-v1\0'


def _module():
    from backend import gg_protocol_provisioning
    return gg_protocol_provisioning


def _path(value):
    if type(value) is not str or not 0 < len(value) <= 4096:
        raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
    target = Path(value).absolute()
    if str(target).startswith(('\\\\', '//')) or any(is_link(item) for item in (target, *target.parents)):
        raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
    return target


def read_public(value, maximum=512*1024):
    target = _path(value)
    with os.fdopen(secure_open(target, os.O_RDONLY, 0o600), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
            raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
        raw = stream.read(maximum+1)
    if len(raw) > maximum:
        raise ValueError('GG_PROTOCOL_PUBLIC_FILE_LIMIT')
    return unpack(raw)


def write_public(value, document):
    target = _path(value)
    raw = pack(document)
    if not 0 < len(raw) <= 512*1024:
        raise ValueError('GG_PROTOCOL_PUBLIC_FILE_LIMIT')
    try:
        descriptor = secure_open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('GG_PROTOCOL_PUBLIC_FILE_EXISTS') from None
    with os.fdopen(descriptor, 'wb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    sync_directory(target.parent)
    return {'state':'EXPORTED', 'public_only':True, 'private_keys_exported':False, 'bytes':len(raw)}


def _relative(base, value):
    if type(value) is not str or not value:
        raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
    path = Path(value)
    return str(_path(str(path if path.is_absolute() else Path(base).absolute().parent/path)))


def unlocked(controller, command, args):
    if command in PUBLIC_COMMANDS:
        return True
    name = args.get('profile')
    if command == 'protocol.account_export':
        return name in controller.accounts
    if command == 'protocol.validator_invite_export':
        return name in controller.validators
    owner = controller.owner
    if owner is None or owner.name != args.get('owner_profile'):
        return False
    if command == 'protocol.client_create':
        return False
    if command == 'protocol.client_export' or command == 'protocol.start_plan' and args.get('role') != 'VALIDATOR':
        return name in controller.replicas
    profile = controller.validators.get(name)
    if profile is None:
        return False
    reference = profile.account_reference()
    return reference is not None and reference['profile'] in controller.accounts


def _owner(controller, name):
    if controller.owner is None:
        controller.dispatch('protocol.owner_open', {'profile':name})
    if controller.owner.name != name:
        raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
    return controller._owned()


def _validator(controller, name, owner_name):
    owner = _owner(controller, owner_name)
    if name not in controller.validators:
        controller.dispatch('protocol.validator_open', {'profile':name})
    profile = controller.validators[name]
    if profile.public_invite()['body']['owner_peer_key'] != owner.descriptor()['public_keys'][0]:
        raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
    account = controller._governance_account(profile)
    if account is None:
        raise ValueError('GG_VALIDATOR_OWNED_ACCOUNT_REQUIRED')
    return owner, profile, account


def _account_card(account):
    with account._lock:
        account._check()
        body = {'schema':'gg.protocol.account-card.v1', 'account_key':account.public_address(),
                'label':account.snapshot()['label']}
        return {'body':body, 'signature':account._key.sign_message(ACCOUNT_DOMAIN+pack(body)).hex()}


def _card(value, schema, fields, domain, key_field):
    if not isinstance(value, dict) or set(value) != {'body', 'signature'}:
        raise ValueError('GG_PROTOCOL_PUBLIC_CARD')
    body = value['body']
    if not isinstance(body, dict) or set(body) != fields or body.get('schema') != schema:
        raise ValueError('GG_PROTOCOL_PUBLIC_CARD')
    protocol._signature(body[key_field], value['signature'], domain+pack(body))
    return body


def _allocation_address(value):
    if isinstance(value, dict) and isinstance(value.get('body'), dict) and value['body'].get('schema') == membership.INVITE_SCHEMA:
        return membership.validate_invite(value)['account_key']
    body = _card(value, 'gg.protocol.account-card.v1', {'schema','account_key','label'}, ACCOUNT_DOMAIN, 'account_key')
    membership.label_wire(body['label'])
    return body['account_key']


def _summary(pin):
    genesis = pin['genesis']
    return {'environment':'TESTNET', 'validator_count':len(genesis['validators']),
            'producer_count':len(genesis['protocol']['initial_producers']),
            'economics':deepcopy(genesis['protocol']['economics']),
            'allocations':deepcopy(genesis['financial_accounts']['allocations']),
            'certificate_asserted':False, 'node_started':False}


def _assemble_file(path):
    source = read_public(path)
    fields = {'schema','context_path','validators','producer_invite_paths','allocations','max_accounts','economics','protocol'}
    if not isinstance(source, dict) or set(source) != fields or source['schema'] != 'gg.protocol.genesis-file-spec.v1':
        raise ValueError('GG_PROTOCOL_GENESIS_FILE_SPEC')
    validators = source['validators']; producer_paths = source['producer_invite_paths']; allocations = source['allocations']
    if (not isinstance(validators,list) or not 4 <= len(validators) <= 64 or not isinstance(producer_paths,list)
            or not 1 <= len(producer_paths) <= 128 or not isinstance(allocations,list) or len(allocations)>128):
        raise ValueError('GG_PROTOCOL_GENESIS_FILE_SPEC')
    invites=[]; powers=[]
    for row in validators:
        if not isinstance(row,dict) or set(row) != {'invite_path','power'}:
            raise ValueError('GG_PROTOCOL_GENESIS_FILE_SPEC')
        invite=read_public(_relative(path,row['invite_path']),4096)
        member=membership.validate_invite(invite)
        invites.append(invite); powers.append({'validator_key':member['validator_key'],'power':row['power']})
    funded=[]
    for row in allocations:
        if not isinstance(row,dict) or set(row) != {'source_path','balance_atomic'}:
            raise ValueError('GG_PROTOCOL_GENESIS_FILE_SPEC')
        address=_allocation_address(read_public(_relative(path,row['source_path']),4096))
        funded.append({'address':address,'balance_atomic':row['balance_atomic']})
    spec={'schema':'gg.protocol.genesis-spec.v1','context':read_public(_relative(path,source['context_path']),4096),
          'financial_accounts':{'schema':'gg.financial.account-genesis.v1','allocations':sorted(funded,key=lambda row:row['address']),
                                'max_accounts':source['max_accounts']},
          'economics':source['economics'],'protocol':source['protocol'],
          'voting_powers':sorted(powers,key=lambda row:row['validator_key'])}
    producers=[read_public(_relative(path,value),4096) for value in producer_paths]
    return _module().assemble(spec,invites,producers)


def dispatch(controller, command, args):
    provisioning = _module()
    name = args.get('profile')
    if 'path' in args and command not in ('protocol.genesis_review','protocol.bootstrap_review'):
        target=_path(args['path'])
        if target.exists():raise ValueError('GG_PROTOCOL_PUBLIC_FILE_EXISTS')
        if not target.parent.is_dir():raise ValueError('GG_PROTOCOL_PUBLIC_FILE_PARENT')
    if command == 'protocol.context_create':
        spec = read_public(args['spec_path'],4096) if args.get('spec_path') else {
            'schema':'gg.protocol.context-spec.v1', 'chain_id':'ggnet:'+secrets.token_hex(12),
            'network_id':secrets.token_hex(32), 'genesis_time_unix':int(time.time()), 'environment':'TESTNET'}
        return write_public(args['path'],provisioning.create_context(spec))
    if command == 'protocol.validator_invite_export':
        if name not in controller.validators:controller.dispatch('protocol.validator_open',{'profile':name})
        return write_public(args['path'],controller.validators[name].public_invite())
    if command == 'protocol.account_export':
        if name not in controller.accounts:controller.dispatch('protocol.account_open',{'profile':name})
        return write_public(args['path'],_account_card(controller.accounts[name]))
    if command == 'protocol.initial_producer_export':
        owner,profile,account=_validator(controller,name,args['owner_profile'])
        invite=provisioning.initial_producer_invite(owner,profile,account,read_public(args['context_path'],4096),
            args.get('producer_slot',0),label=args['label'],platform=args['platform'])
        return write_public(args['path'],invite)
    if command == 'protocol.genesis_assemble':
        pin=_assemble_file(args['spec_path'])
        return {**write_public(args['path'],pin), 'review':_summary(pin)}
    if command == 'protocol.genesis_review':
        pin=protocol.validate_pin(read_public(args['path']))
        provisioning.validate_pin_native(pin)
        return _summary(pin)
    if command == 'protocol.genesis_endorse':
        pin=protocol.validate_pin(read_public(args['pin_path']))
        owner,profile,account=_validator(controller,name,args['owner_profile'])
        endorsement=provisioning.sign_bootstrap(owner,profile,account,pin)
        return {**write_public(args['path'],endorsement), 'genesis_bound':True, 'certificate_asserted':False}
    if command == 'protocol.bootstrap_assemble':
        source=read_public(args['spec_path'],32768)
        if (not isinstance(source,dict) or set(source)!={'schema','pin_path','validator_invite_paths','endorsement_paths'}
                or source['schema']!='gg.protocol.bootstrap-file-spec.v1'
                or any(not isinstance(source[key],list) or not 4<=len(source[key])<=64
                       for key in ('validator_invite_paths','endorsement_paths'))):
            raise ValueError('GG_PROTOCOL_BOOTSTRAP_FILE_SPEC')
        pin=read_public(_relative(args['spec_path'],source['pin_path']))
        invites=[read_public(_relative(args['spec_path'],value),4096) for value in source['validator_invite_paths']]
        endorsements=[read_public(_relative(args['spec_path'],value),4096) for value in source['endorsement_paths']]
        bundle=provisioning.assemble_bootstrap(pin,invites,endorsements)
        return {**write_public(args['path'],bundle),'review':_summary(bundle['pin']), 'all_initial_operators_endorsed':True}
    if command == 'protocol.bootstrap_review':
        bundle=provisioning.validate_bootstrap(read_public(args['path']))
        return {**_summary(bundle['pin']), 'all_initial_operators_endorsed':True}
    if command in ('protocol.client_create','protocol.client_export','protocol.relay_endpoint_export','protocol.start_plan'):
        return _deployment_command(controller,command,args)
    raise ValueError('GG_PROTOCOL_COMMAND')


def _deployment_command(controller, command, args):
    provisioning=_module();name=args['profile'];role=args.get('role')
    if command in ('protocol.client_create','protocol.client_export'):
        if role not in ('LIGHT','REPLICA'):raise ValueError('GG_PROTOCOL_CLIENT_ROLE')
        bundle=provisioning.validate_bootstrap(read_public(args['bootstrap_path'])) if command=='protocol.client_create' else None
        owner=_owner(controller,args['owner_profile'])
        if command=='protocol.client_create':
            if name in controller.replicas:raise ValueError('GG_PROTOCOL_PROFILE_ALREADY_OPEN')
            controller.replicas[name]=ObserverProfile.create_for_protocol(name,owner,bundle['pin'],label=args['label'])
        elif name not in controller.replicas:
            controller.dispatch('protocol.replica_open',{'profile':name})
        profile=controller.replicas[name]
        with owner._lock,profile._lock:
            identity,_=owner.signers();key=profile.native_node_signer();pin=protocol.validate_pin(profile.anchor())
            if profile._body['owner_key']!=identity.pubkey().hex():raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
            body={'schema':'gg.protocol.client-card.v1','genesis_hash':pin['genesis_hash'],
                  'node_key':key.pubkey().hex(),'owner_peer_key':identity.pubkey().hex(),
                  'label_utf8':profile._body['label_utf8'],'role':role}
            message=CLIENT_DOMAIN+pack(body)
            card={'body':body,'node_signature':key.sign_message(message).hex(),'owner_signature':identity.sign_message(message).hex()}
        return {**write_public(args['path'],card),'node_started':False,'voting_authority':False}
    if command=='protocol.relay_endpoint_export':
        bundle=provisioning.validate_bootstrap(read_public(args['bootstrap_path']))
        owner,profile,account=_validator(controller,name,args['owner_profile'])
        if profile.anchor()!=bundle['pin']:raise ValueError('GG_PROTOCOL_BOOTSTRAP_PROFILE_MISMATCH')
        from backend.gg_protocol_transport import endpoint
        with owner._lock,profile._lock:
            _,key=profile.native_signers()
            settings=endpoint({'host':args['host'],'port':args['port'],'server_key':key.pubkey().hex()})
            if settings['port']==profile.public_invite()['body']['p2p_port']:raise ValueError('GG_PROTOCOL_RELAY_PORT_CONFLICT')
            body={'schema':'gg.protocol.relay-endpoint.v1','genesis_hash':bundle['pin']['genesis_hash'],'endpoint':settings}
            card={'body':body,'signature':key.sign_message(ENDPOINT_DOMAIN+pack(body)).hex()}
        return {**write_public(args['path'],card),'listener_started':False}
    if command!='protocol.start_plan':raise ValueError('GG_PROTOCOL_COMMAND')
    if role not in ('VALIDATOR','REPLICA','LIGHT'):raise ValueError('GG_PROTOCOL_NODE_ROLE')
    bundle=provisioning.validate_bootstrap(read_public(args['bootstrap_path']));pin=bundle['pin']
    root=_path(args['output_dir'])
    if root.exists() or not root.parent.is_dir():raise ValueError('GG_PROTOCOL_START_PLAN_NEW_DIRECTORY_REQUIRED')
    if role=='VALIDATOR':
        owner,profile,account=_validator(controller,name,args['owner_profile'])
    else:
        owner=_owner(controller,args['owner_profile'])
        if name not in controller.replicas:controller.dispatch('protocol.replica_open',{'profile':name})
        profile=controller.replicas[name]
        if profile._body['owner_key']!=owner.descriptor()['public_keys'][0]:raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
    if profile.anchor()!=pin:raise ValueError('GG_PROTOCOL_BOOTSTRAP_PROFILE_MISMATCH')
    options=read_public(args['options_path'],32768) if args.get('options_path') else {}
    option_fields={'account_profiles','producer','mining','pools','relay','account_submissions','pool_work'}
    if not isinstance(options,dict) or set(options)-option_fields:raise ValueError('GG_PROTOCOL_START_PLAN_OPTIONS')
    accounts=options.get('account_profiles',[])
    if (not isinstance(accounts,list) or len(accounts)>16
            or any(type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}',value) for value in accounts)
            or len(set(accounts))!=len(accounts)):
        raise ValueError('GG_PROTOCOL_ACCOUNT_PROFILE_LIMIT')
    accounts=list(accounts)
    if role=='VALIDATOR' and account.name not in accounts:
        accounts.append(account.name)
        if len(accounts)>16:raise ValueError('GG_PROTOCOL_ACCOUNT_PROFILE_LIMIT')
    if type(options.get('producer',False)) is not bool:raise ValueError('GG_PROTOCOL_START_PLAN_OPTIONS')
    if role=='LIGHT':
        if options.get('producer') or options.get('mining') is not None or options.get('relay') is not None:
            raise ValueError('GG_PROTOCOL_LIGHT_WORKER_START_SEPARATELY')
        settings=_endpoint_document(read_public(args['endpoint_path'],4096),bundle)
    else:
        key=profile.native_signers()[1].pubkey().hex() if role=='VALIDATOR' else profile.native_node_signer().pubkey().hex()
        invites=[membership.validate_invite(value) for value in bundle['validator_invites']]
        if role=='VALIDATOR':
            own=next((row for row in invites if row['node_key']==key),None)
            if own is None:raise ValueError('GG_PROTOCOL_BOOTSTRAP_PROFILE_MISMATCH')
            host=own['host'];port=own['p2p_port']
        else:
            descriptor=owner.descriptor();host=descriptor['host'];port=descriptor['port']
        peers=[{'host':row['host'],'port':row['p2p_port'],'id':hashlib.sha256(bytes.fromhex(row['node_key'])).digest()[:20].hex()}
               for row in invites if row['node_key']!=key][:16]
        settings={'listen_host':host,'p2p_port':port,'max_inbound':64,'max_outbound':16,'peers':peers}
        from backend.gg_protocol_runtime import local_acceptance
        local_acceptance(pin,settings)
    producer=options.get('producer',False)
    if producer:
        keys=set(owner.descriptor()['public_keys'][1:])
        node_key=profile.native_signers()[1].pubkey().hex() if role=='VALIDATOR' else profile.native_node_signer().pubkey().hex()
        if not any(row['body']['producer_key'] in keys and row['body']['node_key']==node_key for row in pin['genesis']['protocol']['initial_producers']):
            raise ValueError('GG_PROTOCOL_INITIAL_PRODUCER_REQUIRED')
    relay=options.get('relay')
    if relay is not None:
        if role!='VALIDATOR' or not isinstance(relay,dict) or set(relay)!={'endpoint_path','client_card_paths','policy'}:
            raise ValueError('GG_PROTOCOL_START_PLAN_RELAY')
        base=args['options_path']
        endpoint_doc=_endpoint_document(read_public(_relative(base,relay['endpoint_path']),4096),bundle)
        if endpoint_doc['server_key']!=profile.native_signers()[1].pubkey().hex():raise ValueError('GG_PROTOCOL_RELAY_OWNER_MISMATCH')
        paths=relay['client_card_paths']
        if not isinstance(paths,list) or not 1<=len(paths)<=64:raise ValueError('GG_PROTOCOL_RELAY_ALLOWLIST')
        allowed=[_client_document(read_public(_relative(base,path),4096),pin)['node_key'] for path in paths]
        if len(set(allowed))!=len(allowed):raise ValueError('GG_PROTOCOL_RELAY_ALLOWLIST')
        policy=relay['policy']
        if not isinstance(policy,dict) or set(policy)-{'accept_operations','accept_accounts','pool','producer_slot','share_target'}:
            raise ValueError('GG_PROTOCOL_RELAY_POLICY')
        relay={**policy,'host':endpoint_doc['host'],'port':endpoint_doc['port'],'allowed_peer_keys':allowed}
    pools=deepcopy(options.get('pools',[]))
    if not isinstance(pools,list) or len(pools)>4:raise ValueError('GG_PROTOCOL_START_PLAN_OPTIONS')
    for row in pools:
        if isinstance(row,dict) and 'operator_source_path' in row:
            if 'operator' in row or not args.get('options_path'):raise ValueError('GG_PROTOCOL_START_PLAN_OPTIONS')
            source_path=row.pop('operator_source_path')
            row['operator']=_allocation_address(read_public(_relative(args['options_path'],source_path),4096))
    config={'schema':'gg.protocol.operator-start.v1','owner_profile':args['owner_profile'],'native_profile':name,
            'role':role,'settings_path':'settings.json','bootstrap_path':'bootstrap.json','account_profiles':accounts,
            'producer':producer,'mining':options.get('mining'),'pools':pools,'relay':relay,
            'account_submissions':options.get('account_submissions',[]),'pool_work':options.get('pool_work')}
    validate_operator_start(config)
    root.mkdir(mode=0o700);set_private_mode(root,0o700)
    for filename,document in (('bootstrap.json',bundle),('settings.json',settings),('run.json',config)):
        write_public(str(root/filename),document)
    return {'state':'PREPARED','path':str(root/'run.json'),'public_only':True,'private_keys_exported':False,
            'all_initial_operators_endorsed':True,'node_started':False,'role':role}


def _client_document(value,pin):
    if not isinstance(value,dict) or set(value)!={'body','node_signature','owner_signature'}:
        raise ValueError('GG_PROTOCOL_CLIENT_CARD')
    body=value['body']
    if (not isinstance(body,dict) or set(body)!={'schema','genesis_hash','node_key','owner_peer_key','label_utf8','role'}
            or body['schema']!='gg.protocol.client-card.v1' or body['genesis_hash']!=pin['genesis_hash']
            or body['role'] not in ('LIGHT','REPLICA') or body['node_key']==body['owner_peer_key']):
        raise ValueError('GG_PROTOCOL_CLIENT_CARD')
    membership.public_label(body)
    for role,field in (('node','node_key'),('owner','owner_peer_key')):
        protocol._signature(body[field],value[role+'_signature'],CLIENT_DOMAIN+pack(body))
    return body


def _endpoint_document(value,bundle):
    if not isinstance(value,dict) or set(value)!={'body','signature'}:raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT_CARD')
    body=value['body']
    if (not isinstance(body,dict) or set(body)!={'schema','genesis_hash','endpoint'}
            or body['schema']!='gg.protocol.relay-endpoint.v1' or body['genesis_hash']!=bundle['pin']['genesis_hash']):
        raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT_CARD')
    from backend.gg_protocol_transport import endpoint
    settings=endpoint(body['endpoint'])
    if settings['server_key'] not in {row['node_key'] for row in bundle['pin']['genesis']['protocol']['committee']['members']}:
        raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT_MEMBER')
    protocol._signature(settings['server_key'],value['signature'],ENDPOINT_DOMAIN+pack(body))
    return settings


def validate_operator_start(config):
    """Shared preflight for offline plans and the actual foreground operator."""
    fields={'schema','owner_profile','native_profile','role','settings_path','bootstrap_path','account_profiles',
            'producer','mining','pools','relay','account_submissions','pool_work'}
    if (not isinstance(config,dict) or set(config)!=fields or config['schema']!='gg.protocol.operator-start.v1'
            or config['role'] not in ('VALIDATOR','REPLICA','LIGHT') or type(config['producer']) is not bool):
        raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    accounts=config['account_profiles']
    if (not isinstance(accounts,list) or len(accounts)>16
            or any(type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}',value)
                   for value in [config['owner_profile'],config['native_profile'],*accounts])
            or len(set(accounts))!=len(accounts)
            or any(type(config[field]) is not str or not 0<len(config[field])<=4096 for field in ('settings_path','bootstrap_path'))):
        raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    pools=config['pools'];submissions=config['account_submissions'];relay=config['relay'];work=config['pool_work'];mining=config['mining']
    if not isinstance(pools,list) or len(pools)>4 or not isinstance(submissions,list) or len(submissions)>16:
        raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    for row in pools:
        if (not isinstance(row,dict) or set(row)!={'pool','account_profile','operator','commission_bps','create'}
                or type(row['pool']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}',row['pool'])
                or row['account_profile'] not in accounts or type(row['commission_bps']) is not int
                or not 0<=row['commission_bps']<=10000 or type(row['create']) is not bool):
            raise ValueError('GG_PROTOCOL_START_DOCUMENT')
        protocol.financial.account_address(row['operator'])
    names={row['pool'] for row in pools}
    if len(names)!=len(pools):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    for row in submissions:
        if (not isinstance(row,dict) or set(row)-{'profile','producer_slot','transactions_per_block'}
                or row.get('profile') not in accounts or type(row.get('producer_slot',0)) is not int
                or row.get('producer_slot',0) not in (0,1) or type(row.get('transactions_per_block',5000)) is not int
                or not 1<=row.get('transactions_per_block',5000)<=5000):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    if mining is not None:
        if (not isinstance(mining,dict) or set(mining)!={'producer_slot','duration_seconds'} or not config['producer']
                or type(mining['producer_slot']) is not int or mining['producer_slot'] not in (0,1)
                or type(mining['duration_seconds']) is not int or not 1<=mining['duration_seconds']<=3600):
            raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    if work is not None:
        if (not isinstance(work,dict) or set(work)-{'account_profile','duration_seconds','attempts'}
                or work.get('account_profile') not in accounts or config['role']!='LIGHT' or mining is not None
                or type(work.get('duration_seconds',60)) is not int or not 1<=work.get('duration_seconds',60)<=3600
                or type(work.get('attempts',65536)) is not int or not 1<=work.get('attempts',65536)<=2**20):
            raise ValueError('GG_PROTOCOL_START_DOCUMENT')
    if config['role']=='LIGHT' and (pools or relay is not None or config['producer'] or mining is not None):
        raise ValueError('GG_PROTOCOL_LIGHT_CANNOT_HOST_NATIVE_RELAY_OR_POOL')
    if relay is not None:
        allowed={'host','port','allowed_peer_keys','accept_operations','accept_accounts','pool','producer_slot','share_target'}
        if (not isinstance(relay,dict) or set(relay)-allowed or not {'host','port','allowed_peer_keys'}<=set(relay)
                or type(relay.get('accept_operations',False)) is not bool or type(relay.get('accept_accounts',False)) is not bool
                or type(relay.get('producer_slot',0)) is not int or relay.get('producer_slot',0) not in (0,1)
                or relay.get('accept_accounts',False) and not config['producer']
                or relay.get('pool') is not None and (relay['pool'] not in names or not config['producer'])):
            raise ValueError('GG_PROTOCOL_RELAY_POLICY')
        keys=relay['allowed_peer_keys']
        if (not isinstance(keys,list) or not 1<=len(keys)<=64 or any(type(key) is not str for key in keys)
                or len(set(keys))!=len(keys)):raise ValueError('GG_PROTOCOL_RELAY_ALLOWLIST')
        for key in keys:protocol.financial.account_address(key)
        if relay.get('share_target') is not None:protocol._hash(relay['share_target'])
        from backend.gg_protocol_transport import endpoint
        # Only address/port grammar is relevant here. The node's real key was
        # authenticated by its signed endpoint card during plan generation.
        endpoint({'host':relay['host'],'port':relay['port'],'server_key':keys[0]})
    return deepcopy(config)
