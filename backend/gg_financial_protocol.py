"""Public protocol codecs and native-certified selected observations.

These functions do not activate a network or grant monetary/producer/voter
authority. Pin validation is shape and proof-of-possession checking; the owned
native SDK verifier authenticates certificates and every requested record.
"""
import base64
from copy import deepcopy
import hashlib
import re

from backend.gg_parallel_dag import pack
from backend.gg_ed25519 import SIGNATURE_PROFILE,verify_signature
from backend import gg_financial_economy as economy
from backend import gg_financial_dag as financial

SOURCE='gg.financial-dag.source.v5'
GENESIS='gg.native.genesis.v7'
PROTOCOL_FIELDS={'committee','economics','environment','expected_blocks_per_epoch','initial_producers','initial_work_target',
 'max_committee_change_bps','max_epoch_participants','max_producer_entries','max_work_heights','max_work_target','min_work_target',
 'registration_work_target','schema'}
UNUSED_KEY_POLICY='SWEEP_NEVER_SPENT_BALANCE_TO_DECLARED_ACCOUNT'
INVITE_FIELDS={'chain_id','label_utf8','network_id','node_key','nonce','owner_peer_key','platform','producer_key','reward_account','schema','unused_key_policy'}
BASE={'schema','genesis','genesis_hash','state','signed_header'}
_JOB_TOKEN=object()


class CertifiedMiningJob:
    __slots__=('_job',)
    def __init__(self,job,*,token=None):
        if token is not _JOB_TOKEN:raise ValueError('GG_MINING_CERTIFIED_CONTEXT_REQUIRED')
        object.__setattr__(self,'_job',pack(economy.validate_job(job)))
    def __setattr__(self,name,value):raise AttributeError('immutable certified mining context')
    def document(self):
        from backend.gg_node_store import unpack
        return unpack(self._job)


def _hash(value):
    if type(value) is not str or not economy.HASH.fullmatch(value):raise ValueError('GG_FINANCIAL_PROTOCOL_HASH')
    return value


def _signature(key,signature,message):
    financial.account_address(key)
    if type(signature) is not str or not re.fullmatch(r'[0-9a-f]{128}',signature):raise ValueError('GG_FINANCIAL_PROTOCOL_SIGNATURE')
    verify_signature(bytes.fromhex(key),message,bytes.fromhex(signature))


def validate_invite(value,genesis):
    if not isinstance(value,dict) or set(value)!={'body','node_signature','owner_signature','producer_signature'} or len(pack(value))>4096:
        raise ValueError('GG_FINANCIAL_PRODUCER_INVITE')
    body=value['body']
    if (not isinstance(body,dict) or set(body)!=INVITE_FIELDS or body['schema']!='gg.financial.producer-registration.v1'
            or body['chain_id']!=genesis['chain_id'] or body['network_id']!=genesis['financial_dag']['network_id']
            or body['platform'] not in ('windows','linux','termux','other') or body['unused_key_policy']!=UNUSED_KEY_POLICY):raise ValueError('GG_FINANCIAL_PRODUCER_INVITE')
    _hash(body['nonce'])
    label=base64.b64decode(body['label_utf8'],validate=True)
    if base64.b64encode(label).decode()!=body['label_utf8'] or not 1<=len(label)<=96:raise ValueError('GG_FINANCIAL_PRODUCER_LABEL')
    text=label.decode('utf-8')
    if any(ord(char)<32 or ord(char)==127 for char in text):raise ValueError('GG_FINANCIAL_PRODUCER_LABEL')
    keys=[financial.account_address(body[name]) for name in ('node_key','owner_peer_key','producer_key','reward_account')]
    if len(set(keys))!=4:raise ValueError('GG_FINANCIAL_PRODUCER_KEYS')
    message=b'GG-FINANCIAL-PRODUCER-REGISTRATION-v1\0'+pack(body)
    for role in ('node','owner','producer'):_signature(body['owner_peer_key' if role=='owner' else role+'_key'],value[role+'_signature'],message)
    return deepcopy(value)


def validate_source(value,genesis):
    if (not isinstance(value,dict) or set(value)!={'allowed_producers','native_chain_id','network_id','policy','producers','schema','signature_profile','started_at_ns'}
            or value['schema']!=SOURCE or value['native_chain_id']!=genesis['chain_id'] or value['signature_profile']!=SIGNATURE_PROFILE
            or value['policy']!=financial.policy(SOURCE) or len(pack(value))>32768):raise ValueError('GG_FINANCIAL_PROTOCOL_SOURCE')
    _hash(value['network_id'])
    keys=value['producers'];allowed=value['allowed_producers']
    if not isinstance(keys,list) or not 1<=len(keys)<=128 or keys!=sorted(set(keys)):raise ValueError('GG_FINANCIAL_PROTOCOL_SOURCE')
    for key in keys:financial.account_address(key)
    if (not isinstance(allowed,list) or len(allowed)!=0 or any(type(index) is not int or not 0<=index<len(keys) for index in allowed)
            or allowed!=sorted(set(allowed)) or value['started_at_ns']!=str(genesis['genesis_time_unix']*10**9)):
        raise ValueError('GG_FINANCIAL_PROTOCOL_SOURCE')
    return deepcopy(value)


def validate_pin(trust):
    """Strict pin codec; a matching hash does not supply an SDK certificate."""
    try:
        if not isinstance(trust,dict) or set(trust)!={'genesis','genesis_hash'} or len(pack(trust))>256*1024:raise ValueError()
        genesis=trust['genesis'];expected={'accounts','chain_id','decimals','financial_accounts','financial_dag','genesis_time_unix','protocol','schema','supply_atomic','symbol','validators'}
        if (not isinstance(genesis,dict) or set(genesis)!=expected or genesis['schema']!=GENESIS or genesis['accounts'] is not None
                or type(genesis['decimals']) is not int or genesis['decimals']!=6 or type(genesis['chain_id']) is not str
                or not re.fullmatch(r'ggnet:[0-9a-f]{24}',genesis['chain_id'])):raise ValueError()
        start=economy._integer(genesis['genesis_time_unix'],(financial.MAX_COUNTER-5_000_000_000)//10**9,positive=True)
        if len(pack(genesis))>64*1024:raise ValueError()
        policy=genesis['protocol']
        if not isinstance(policy,dict) or set(policy)!=PROTOCOL_FIELDS or policy['schema']!='gg.financial.protocol-genesis.v1':raise ValueError()
        economics=economy.validate_policy(policy['economics']);committee=economy.validate_committee(policy['committee'])
        if int(economy.minimum_fee(economics,128*1024))>=int(economics['max_supply_atomic']) or economics['initial_supply_atomic']=='0' and economics['epoch_reward_atomic']=='0':raise ValueError()
        if (committee['epoch']!='0' or len(committee['members'])>64 or genesis['validators']!=[row['validator_key'] for row in committee['members']]
                or policy['environment'] not in ('TESTNET','MAINNET') or genesis['symbol']!=('GG-TEST' if policy['environment']=='TESTNET' else 'GG')
                or genesis['supply_atomic']!=economics['initial_supply_atomic']):raise ValueError()
        economy._integer(policy['max_committee_change_bps'],3333,positive=True)
        economy._number(policy['expected_blocks_per_epoch'],10**9,positive=True)
        maximum=economy._number(policy['max_producer_entries'],2**32,positive=True)
        participants=economy._number(policy['max_epoch_participants'],65536,positive=True)
        if participants==65536 and economics['treasury_bps']:raise ValueError()
        if economy._number(policy['max_work_heights'],65536)<8:raise ValueError()
        for name in ('initial_work_target','min_work_target','max_work_target','registration_work_target'):
            if int(_hash(policy[name]),16)==0:raise ValueError()
        if not policy['min_work_target']<=policy['initial_work_target']<=policy['max_work_target'] or policy['registration_work_target']>policy['max_work_target']:raise ValueError()
        source=validate_source(genesis['financial_dag'],genesis)
        invites=policy['initial_producers']
        if not isinstance(invites,list) or not 1<=len(invites)<=min(128,maximum) or len(invites)!=len(source['producers']):raise ValueError()
        roles={};wallets=set()
        def reserve(key,owner,role):
            prior=roles.get(key)
            if prior is not None and prior!=(owner,role):raise ValueError()
            roles[key]=(owner,role)
        for member in committee['members']:
            for key,role in ((member['validator_key'],'VALIDATOR'),(member['node_key'],'NODE'),(member['owner_peer_key'],'OWNER')):reserve(key,member['owner_peer_key'],role)
            reserve(member['account_key'],member['owner_peer_key'],'GOVERNANCE')
            wallets.add(member['account_key'])
        for index,invite in enumerate(invites):
            body=validate_invite(invite,genesis)['body']
            if body['producer_key']!=source['producers'][index]:raise ValueError()
            for key,role in ((body['producer_key'],'PRODUCER'),(body['node_key'],'NODE'),(body['owner_peer_key'],'OWNER')):reserve(key,body['owner_peer_key'],role)
            wallets.add(body['reward_account'])
        if economics['treasury_bps']:wallets.add(economics['treasury_account'])
        allocation=genesis['financial_accounts']
        if not isinstance(allocation,dict) or set(allocation)!={'allocations','max_accounts','schema'} or allocation['schema']!='gg.financial.account-genesis.v1':raise ValueError()
        limit=economy._number(allocation['max_accounts'],2**32,positive=True);rows=allocation['allocations']
        if limit<2:raise ValueError()
        if not isinstance(rows,list) or not int(int(economics['initial_supply_atomic'])>0)<=len(rows)<=min(128,limit):raise ValueError()
        previous='';total=0
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'address','balance_atomic'}:raise ValueError()
            address=financial.account_address(row['address']);balance=economy._number(row['balance_atomic'],int(economics['max_supply_atomic']),positive=True)
            if address<=previous:raise ValueError()
            wallets.add(address);previous=address;total+=balance
        if total!=int(economics['initial_supply_atomic']) or any(roles[address][1]!='GOVERNANCE' for address in wallets&set(roles)) or len(wallets)>limit:raise ValueError()
        if _hash(trust['genesis_hash'])!=hashlib.sha256(pack(genesis)).hexdigest():raise ValueError()
        return deepcopy(trust)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,AttributeError,UnicodeError):
        raise ValueError('GG_FINANCIAL_PROTOCOL_PIN_INVALID') from None


def quote_payment(genesis,anchor,sender,recipient,amount,nonce):
    """Compute an exact reviewed fee cap without creating a signature."""
    if genesis['schema']!=GENESIS:raise ValueError('GG_FINANCIAL_PROTOCOL_REQUIRED')
    financial.account_address(sender);financial.account_address(recipient);_hash(anchor)
    economy._number(amount,int(genesis['protocol']['economics']['max_supply_atomic']),positive=True)
    economy._integer(nonce)
    body={'amount_atomic':amount,'chain_id':genesis['chain_id'],'genesis_hash':anchor,'max_fee_atomic':'0',
          'nonce':str(nonce),'recipient':recipient,'sender':sender,'version':2}
    for _ in range(24):
        fee=economy.minimum_fee(genesis['protocol']['economics'],len(pack({'body':body,'signature':'0'*128})))
        if fee==body['max_fee_atomic']:return body
        body['max_fee_atomic']=fee
    raise ValueError('GG_FINANCIAL_FEE_QUOTE_DID_NOT_CONVERGE')


def verify_selected(packet,trust,*,registry=None,block=None,reward=None,binary=None,stamp=None):
    from backend import gg_consensus as native
    anchor=validate_pin(trust)
    if (not isinstance(packet,dict) or packet.get('genesis')!=anchor['genesis'] or packet.get('genesis_hash')!=anchor['genesis_hash']
            or 'committee_trust_path' in packet or len(pack(packet))>256*1024):raise ValueError('GG_FINANCIAL_PROTOCOL_PROOF')
    request=deepcopy(packet)
    if registry is not None:request['expected_financial_registry']=deepcopy(registry)
    if block is not None:request['expected_financial_block']=_hash(block)
    if reward is not None:request['expected_financial_reward']=deepcopy(reward)
    selected=native._installed_binary(native.TOOLS) if binary is None else binary
    selected_stamp=native._validate_binary_at(native.TOOLS,selected) if binary is None else stamp
    result=native._verify_public(request,selected,selected_stamp)
    if registry is not None and (result.get('financial_registry_verified') is not True or result.get('financial_registry_namespace')!=registry['namespace'] or result.get('financial_registry_key')!=registry['key']):raise ValueError('GG_FINANCIAL_REGISTRY_PROOF')
    if block is not None and (result.get('financial_block_verified') is not True or result.get('financial_block',{}).get('context',{}).get('block_hash')!=block):raise ValueError('GG_FINANCIAL_BLOCK_PROOF')
    if reward is not None and (result.get('financial_reward_verified') is not True or result.get('financial_reward_credit',{}).get('address')!=reward['address'] or result.get('financial_reward_index')!=reward['index']):raise ValueError('GG_FINANCIAL_REWARD_PROOF')
    return result


def derive_block_job(core,packet,trust,producer_key,worker_key,share_target,*,prefix=(),binary=None,stamp=None):
    """Derive work from an actual signed core and certified creator context.

    The core's protected original must already be retained by its owner. This
    function checks authorization/context; it grants no signing permission and
    does not assert that the block or any payment has been selected.
    """
    from backend import gg_financial_wire as wire
    producer_key=financial.account_address(producer_key);worker_key=financial.account_address(worker_key);_hash(share_target)
    if not isinstance(core,dict) or set(core)!={'body','signature'}:raise ValueError('GG_MINING_BLOCK_CORE')
    body=core['body'];fields={'created_at_ns','epoch','genesis_hash','parents','payment_root','payments','producer_key','rank','schema','sequence','source_hash'}
    if not isinstance(body,dict) or set(body)!=fields or body['schema']!='gg.financial-dag.block.v2' or body['producer_key']!=producer_key:raise ValueError('GG_MINING_BLOCK_CORE')
    result=verify_selected(packet,trust,registry={'namespace':'producers','key':producer_key},binary=binary,stamp=stamp)
    if result['financial_registry_exists'] is not True:raise ValueError('GG_MINING_UNREGISTERED_PRODUCER')
    from backend.gg_node_store import unpack
    record=unpack(base64.b64decode(result['financial_registry_value'],validate=True))
    state=packet['state'];source=trust['genesis']['financial_dag'];protocol=state['protocol']
    parent=record['head'];rank=int(record['rank']);sequence=int(record['sequence'])
    if not isinstance(prefix,(list,tuple)) or len(prefix)>7:raise ValueError('GG_MINING_OWN_PREFIX_LIMIT')
    for previous in prefix:
        if not isinstance(previous,dict) or set(previous)!={'body','signature'}:raise ValueError('GG_MINING_OWN_PREFIX')
        earlier=previous['body']
        if (not isinstance(earlier,dict) or set(earlier)!=fields or earlier['producer_key']!=producer_key or earlier['genesis_hash']!=trust['genesis_hash']
                or earlier['source_hash']!=financial.source_hash(source) or earlier['schema']!='gg.financial-dag.block.v2'
                or earlier['parents']!=[parent] or wire.counter(earlier['rank'])!=rank+1 or wire.counter(earlier['sequence'])!=sequence+1
                or not isinstance(earlier['payments'],list) or len(earlier['payments'])>wire.MAX_PAYMENTS or earlier['payment_root']!=wire.payment_root(earlier['payments'])):
            raise ValueError('GG_MINING_OWN_PREFIX')
        _signature(producer_key,previous['signature'],financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(earlier))
        parent=hashlib.sha256(financial.DOMAIN+b'DAG-BLOCK-CORE-v2\0'+pack(previous)).hexdigest();rank+=1;sequence+=1
    if (body['genesis_hash']!=trust['genesis_hash'] or body['source_hash']!=financial.source_hash(source)
            or not 1<=wire.counter(body['epoch'],positive=True)<=int(state['financial_dag']['epoch'])
            or not isinstance(body['parents'],list) or len(body['parents'])!=1 or not economy.HASH.fullmatch(body['parents'][0])
            or wire.counter(body['rank'],positive=True)<1 or wire.counter(body['sequence'],positive=True)<=int(record['sequence'])
            or prefix and (body['parents']!=[parent] or int(body['rank'])!=rank+1 or int(body['sequence'])!=sequence+1)
            or not int(source['started_at_ns'])<=wire.counter(body['created_at_ns'])<=int(protocol['time_ns'])+5_000_000_000
            or not isinstance(body['payments'],list) or len(body['payments'])>wire.MAX_PAYMENTS
            or body['payment_root']!=wire.payment_root(body['payments'])):raise ValueError('GG_MINING_BLOCK_CORE')
    _signature(producer_key,core['signature'],financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(body))
    identifier=hashlib.sha256(financial.DOMAIN+b'DAG-BLOCK-CORE-v2\0'+pack(core)).hexdigest()
    invite=record['invite']['body'];height=int(protocol['work_anchor_height'])
    job={'epoch':protocol['economics']['next_epoch'],'expires_height':str(height+int(trust['genesis']['protocol']['max_work_heights'])),
         'genesis_hash':trust['genesis_hash'],'job_nonce':hashlib.sha256(b'GG-FINANCIAL-WORK-NONCE-v1\0'+(identifier+invite['nonce']).encode('ascii')).hexdigest(),
         'network_target':protocol['work_target'],'payload_root':identifier,'reward_account':invite['reward_account'],'schema':'gg.financial.mining-job.v1',
         'share_target':share_target,'state_height':str(height),'state_root':protocol['work_anchor_root'],'worker_key':worker_key}
    return CertifiedMiningJob(job,token=_JOB_TOKEN)


def derive_manifest_job(manifest,packet,trust,worker_key,*,binary=None,stamp=None):
    """Verify a compact creator authorization for delegated hashing.

    This authenticates the work assignment, never the complete block payload,
    monetary execution or data availability. The native network must admit the
    actual original core before it can earn any certified reward.
    """
    from backend import gg_financial_wire as wire
    if not isinstance(manifest,dict) or set(manifest)!={'body','signature'} or len(pack(manifest))>8192:raise ValueError('GG_MINING_WORK_MANIFEST')
    body=manifest['body'];fields={'block','genesis_hash','job','producer_key','schema','sequence'}
    if not isinstance(body,dict) or set(body)!=fields or body['schema']!='gg.financial.work-manifest.v1' or body['genesis_hash']!=trust['genesis_hash']:raise ValueError('GG_MINING_WORK_MANIFEST')
    key=financial.account_address(body['producer_key']);identifier=_hash(body['block']);worker_key=financial.account_address(worker_key)
    verified=verify_selected(packet,trust,registry={'namespace':'producers','key':key},binary=binary,stamp=stamp)
    if not verified['financial_registry_exists']:raise ValueError('GG_MINING_UNREGISTERED_PRODUCER')
    from backend.gg_node_store import unpack
    record=unpack(base64.b64decode(verified['financial_registry_value'],validate=True));invite=record['invite']['body']
    sequence=wire.counter(body['sequence'],positive=True)
    if not int(record['sequence'])<sequence<=int(record['sequence'])+8:raise ValueError('GG_MINING_WORK_MANIFEST_SEQUENCE')
    _signature(key,manifest['signature'],b'GG-FINANCIAL-WORK-MANIFEST-v1\0'+pack(body))
    state=packet['state']['protocol'];height=int(state['work_anchor_height']);job=economy.validate_job(body['job'])
    expected={'epoch':state['economics']['next_epoch'],'expires_height':str(height+int(trust['genesis']['protocol']['max_work_heights'])),
        'genesis_hash':trust['genesis_hash'],'job_nonce':hashlib.sha256(b'GG-FINANCIAL-WORK-NONCE-v1\0'+(identifier+invite['nonce']).encode()).hexdigest(),
        'network_target':state['work_target'],'payload_root':identifier,'reward_account':invite['reward_account'],'schema':'gg.financial.mining-job.v1',
        'share_target':job['share_target'],'state_height':str(height),'state_root':state['work_anchor_root'],'worker_key':worker_key}
    if job!=expected:raise ValueError('GG_MINING_WORK_MANIFEST_CONTEXT')
    return CertifiedMiningJob(job,token=_JOB_TOKEN)
