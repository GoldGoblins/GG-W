"""Explicit financial source codec and pinned native receipt verification.

No activation, key creation, transaction submission, process or I/O at import.
Shape checks never claim replay, mining, rewards, pool solvency or finality.
"""
from copy import deepcopy
import hashlib
import json
import re

from backend.gg_ed25519 import SIGNATURE_PROFILE, require_public_key

SOURCE_SCHEMA='gg.financial-dag.source.v1'
SESSION_SOURCE_SCHEMA='gg.financial-dag.source.v2'
LINEAGE_SOURCE_SCHEMA='gg.financial-dag.source.v3'
GENERAL_SOURCE_SCHEMA='gg.financial-dag.source.v4'
PROTOCOL_SOURCE_SCHEMA='gg.financial-dag.source.v5'
LINEAGE_SOURCE_SCHEMAS=(LINEAGE_SOURCE_SCHEMA,GENERAL_SOURCE_SCHEMA)
SESSION_SOURCE_SCHEMAS=(SESSION_SOURCE_SCHEMA,*LINEAGE_SOURCE_SCHEMAS)
MAX_COUNTER=2**63-1
DOMAIN=b'GG-ORDERED-MONETARY-v1\0'


def _pack(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def policy(schema=SOURCE_SCHEMA):
    value={'account_model':'FIXED_NATIVE_FOUR_ACCOUNT_TEST_ALLOCATION','active_max_blocks':4095,
            'active_max_wire_bytes':512*1024*1024,'block_max_parents':7,'block_max_payments':50000,
            'block_max_wire_bytes':32*1024*1024,'execution':'NATIVE_SIGNED_PAYMENTS_ORDERED_REJECTIONS_NO_FEES_OR_ISSUANCE',
            'history':'ORIGINAL_SIGNED_SEGMENTS_AND_SDK_CERTIFIED_CUTS','schema':'gg.financial-dag.policy.v1'}
    if schema in (*LINEAGE_SOURCE_SCHEMAS,PROTOCOL_SOURCE_SCHEMA):
        value.update(history='PERMANENT_AUTHENTICATED_TOPOLOGY_AND_SDK_CERTIFIED_CUTS',schema='gg.financial-dag.policy.v2')
    if schema in (GENERAL_SOURCE_SCHEMA,PROTOCOL_SOURCE_SCHEMA):
        value.update(account_model='GENERAL_NATIVE_ACCOUNT_TREE_TEST_ALLOCATION',schema='gg.financial-dag.policy.v3')
    if schema==PROTOCOL_SOURCE_SCHEMA:
        value.update(account_model='GENERAL_NATIVE_ACCOUNT_TREE_CAPPED_ECONOMY',execution='NATIVE_ACCOUNT_PAYMENTS_FEES_WORK_AND_CAPPED_EPOCH_REWARDS',schema='gg.financial-dag.policy.v4')
    return value


def account_address(address):
    """Canonical prime-order public address; this grants no balance or role."""
    if type(address) is not str or not re.fullmatch(r'[0-9a-f]{64}',address):raise ValueError('GG_FINANCIAL_ACCOUNT_ADDRESS')
    require_public_key(bytes.fromhex(address))
    return address


def reserved_account_keys(genesis,*,producers=None):
    keys=set(genesis['validators'])|set(genesis['financial_dag']['producers'] if producers is None else producers)
    for invite in genesis.get('membership',{}).get('validators',[]):
        keys.update(invite['body'][name] for name in ('validator_key','node_key','owner_peer_key'))
    if genesis.get('schema')=='gg.native.genesis.v7':
        for member in genesis['protocol']['committee']['members']:keys.update(member[name] for name in ('validator_key','node_key','owner_peer_key'))
        for invite in genesis['protocol']['initial_producers']:keys.update(invite['body'][name] for name in ('producer_key','node_key','owner_peer_key'))
    return keys


def validate_account_genesis(genesis,*,producers=None):
    """Validate explicit private-test allocation, never infer a public economy."""
    try:
        value=genesis['financial_accounts']
        if (genesis['schema']!='gg.native.genesis.v6' or genesis['accounts'] is not None or not isinstance(value,dict)
                or set(value)!={'allocations','max_accounts','schema'} or value['schema']!='gg.financial.account-genesis.v1'
                or type(value['max_accounts']) is not str or not re.fullmatch(r'[1-9][0-9]{0,9}',value['max_accounts'])
                or not 1<=int(value['max_accounts'])<=2**32 or not isinstance(value['allocations'],list)
                or not 1<=len(value['allocations'])<=min(128,int(value['max_accounts']))):raise ValueError()
        previous='';total=0;reserved=reserved_account_keys(genesis,producers=producers)
        for row in value['allocations']:
            if not isinstance(row,dict) or set(row)!={'address','balance_atomic'}:raise ValueError()
            address=account_address(row['address']);balance=row['balance_atomic']
            if (address<=previous or address in reserved or type(balance) is not str
                    or not re.fullmatch(r'[1-9][0-9]{0,12}',balance) or not 0<int(balance)<=10**12):raise ValueError()
            previous=address;total+=int(balance)
        if total!=10**12:raise ValueError()
        return deepcopy(value)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,AttributeError):raise ValueError('GG_FINANCIAL_ACCOUNT_GENESIS_INVALID') from None


def validate_source(value,genesis):
    """Validate this exact versioned test policy and separate signing roles."""
    if isinstance(value,dict) and value.get('schema')==PROTOCOL_SOURCE_SCHEMA:
        from backend.gg_financial_protocol import validate_source as public_source
        return public_source(value,genesis)
    try:
        if not isinstance(value,dict) or len(_pack(value))>8192:raise ValueError()
        source=deepcopy(value);expected=policy(source.get('schema'))
        fields={'allowed_producers','native_chain_id','policy','producers','schema','signature_profile','started_at_ns'}
        version=source.get('schema')
        if version in SESSION_SOURCE_SCHEMAS:fields.add('network_id')
        if (set(source)!=fields or version not in (SOURCE_SCHEMA,*SESSION_SOURCE_SCHEMAS) or source['signature_profile']!=SIGNATURE_PROFILE
                or source['native_chain_id']!=genesis['chain_id'] or source['policy']!=expected
                or any(type(source['policy'][key]) is not type(value) for key,value in expected.items())):raise ValueError()
        if (version==GENERAL_SOURCE_SCHEMA)!=(genesis['schema']=='gg.native.genesis.v6'):raise ValueError()
        if version in SESSION_SOURCE_SCHEMAS and (type(source['network_id']) is not str or not re.fullmatch(r'[0-9a-f]{64}',source['network_id'])):raise ValueError()
        producers=source['producers'];allowed=source['allowed_producers']
        if (not isinstance(producers,list) or len(producers)!=6 or len(set(producers))!=6
                or not isinstance(allowed,list) or any(type(index) is not int or not 0<=index<6 for index in allowed)
                or sorted(set(allowed))!=allowed):raise ValueError()
        forbidden=set(genesis['validators'])|set(genesis['accounts'] or [])
        for key in producers:
            if type(key) is not str or not re.fullmatch(r'[0-9a-f]{64}',key) or key in forbidden:raise ValueError()
            require_public_key(bytes.fromhex(key))
        for key in forbidden:require_public_key(bytes.fromhex(key))
        if version==GENERAL_SOURCE_SCHEMA:validate_account_genesis(genesis,producers=producers)
        start=source['started_at_ns'];when=genesis['genesis_time_unix']
        if (type(start) is not str or not re.fullmatch(r'[1-9][0-9]{0,18}',start)
                or type(when) is not int or not 0<when<=(MAX_COUNTER-5_000_000_000)//10**9
                or not when*10**9<=int(start)<=when*10**9+5_000_000_000):raise ValueError()
        return source
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_SOURCE_INVALID') from None


def source_hash(source):
    """Caller validates the source against its owned native genesis first."""
    return hashlib.sha256(DOMAIN+b'DAG-SOURCE\0'+_pack(source)).hexdigest()


def make_session_source(genesis,producers,allowed,network_id,started_at_ns,*,schema=LINEAGE_SOURCE_SCHEMA):
    """Construct an explicitly session-bound source; never upgrade a v1 source."""
    if schema not in SESSION_SOURCE_SCHEMAS:raise ValueError('GG_FINANCIAL_SOURCE_INVALID')
    return validate_source({'schema':schema,'signature_profile':SIGNATURE_PROFILE,'native_chain_id':genesis['chain_id'],
            'producers':deepcopy(producers),'allowed_producers':deepcopy(allowed),'network_id':network_id,
            'started_at_ns':str(started_at_ns),'policy':policy(schema)},genesis)


def verify_receipt(packet,trust,*,expected_transaction_id=None,binary=None,stamp=None):
    """Pin an owned genesis, then invoke the actual SDK/signature verifier.

    binary/stamp are an internal isolated-test seam; no peer field selects them.
    A success proves the historical outcome, never current network contact.
    """
    from backend.gg_dag_segmented import validate_native_pin
    from backend import gg_consensus as native
    try:
        anchor=validate_native_pin(trust)
        if (anchor['genesis']['schema'] not in ('gg.native.genesis.v5','gg.native.genesis.v6','gg.native.genesis.v7') or not isinstance(packet,dict)
                or len(_pack(packet))>256*1024 or packet.get('genesis_hash')!=anchor['genesis_hash']
                or _pack(packet.get('genesis'))!=_pack(anchor['genesis'])
                or not isinstance(packet.get('financial_receipt'),dict)):raise ValueError()
        request=deepcopy(packet)
        if anchor['genesis']['schema']=='gg.native.genesis.v7' and expected_transaction_id is None:raise ValueError()
        if expected_transaction_id is not None:
            if type(expected_transaction_id) is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_transaction_id):raise ValueError()
            expectation=request.get('expected_financial_receipt',{})
            request['expected_financial_receipt']={**expectation,'transaction_id':expected_transaction_id}
        result=native._verify_public(request,native.BINARY if binary is None else binary,
                                     native._binary_stamp if binary is None else stamp)
        if (result.get('financial_receipt_verified') is not True or result.get('financial_receipt')!=packet['financial_receipt']['receipt']['leaf']
                or result.get('financial_creator')!=packet['financial_receipt']['creator']
                or expected_transaction_id is not None and result['financial_receipt']['transaction_id']!=expected_transaction_id):raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_RECEIPT_INVALID') from None


def verify_producer(packet,trust,*,binary=None,stamp=None):
    """Authenticate the next creator context; this is not signing authority."""
    from backend.gg_dag_segmented import validate_native_pin
    from backend import gg_consensus as native
    try:
        anchor=validate_native_pin(trust)
        if (anchor['genesis']['schema'] not in ('gg.native.genesis.v5','gg.native.genesis.v6') or anchor['genesis']['financial_dag']['schema'] not in SESSION_SOURCE_SCHEMAS
                or not isinstance(packet,dict) or len(_pack(packet))>256*1024 or packet.get('genesis_hash')!=anchor['genesis_hash']
                or _pack(packet.get('genesis'))!=_pack(anchor['genesis']) or not isinstance(packet.get('financial_producer'),dict)):raise ValueError()
        result=native._verify_public(deepcopy(packet),native.BINARY if binary is None else binary,
                                     native._binary_stamp if binary is None else stamp)
        proof=packet['financial_producer'];index=proof['producer_index']
        if (type(index) is not int or not 0<=index<6 or result.get('financial_producer_verified') is not True
                or result.get('financial_producer_key')!=anchor['genesis']['financial_dag']['producers'][index]
                or result.get('financial_parent')!=proof['parent'] or result.get('financial_parent_rank')!=proof['parent_rank']
                or result.get('financial_sequence')!=proof['sequence']):raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_PRODUCER_INVALID') from None


def verify_account(packet,trust,address,*,binary=None,stamp=None):
    """Certify the caller's requested account, including authenticated absence.

    The provider cannot choose the address through either proof/request field.
    This is a certified historical view, never evidence of current contact.
    """
    from backend.gg_dag_segmented import validate_native_pin
    from backend import gg_consensus as native
    try:
        anchor=validate_native_pin(trust);address=account_address(address)
        if (anchor['genesis']['schema'] not in ('gg.native.genesis.v6','gg.native.genesis.v7') or not isinstance(packet,dict)
                or len(_pack(packet))>256*1024 or packet.get('genesis_hash')!=anchor['genesis_hash']
                or _pack(packet.get('genesis'))!=_pack(anchor['genesis'])
                or packet.get('expected_financial_account')!=address or packet['financial_account']['proof']['address']!=address):raise ValueError()
        value=deepcopy(packet);value.update(deepcopy(anchor));value['expected_financial_account']=address
        selected=native._installed_binary(native.TOOLS) if binary is None else binary
        selected_stamp=native._validate_binary_at(native.TOOLS,selected) if binary is None else stamp
        result=native._verify_public(value,selected,selected_stamp)
        exists=result.get('financial_account_exists');account=result.get('financial_account')
        if (result.get('financial_account_verified') is not True or result.get('financial_account_address')!=address
                or type(exists) is not bool or result.get('financial_account_scope')!='SDK_CERTIFIED_ACCOUNT_MEMBERSHIP_OR_ABSENCE_NOT_FULL_HISTORY_REPLAY'
                or (not exists and account is not None) or (exists and (not isinstance(account,dict) or account.get('address')!=address))):raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_FINANCIAL_ACCOUNT_INVALID') from None
