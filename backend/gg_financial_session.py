"""Explicit signed financial LAN contract; no pairing, signing-key creation or activation.

The namespace is derived before embedding the financial source in native genesis.
Existing nonfinancial sessions and financial source v1 bytes are unchanged.
"""
from copy import deepcopy
import hashlib
import re

from backend.gg_parallel_dag import digest,pack
from backend import gg_financial_dag as financial

SCHEMA='gg.lan-dag.session.v6'
MODE='NATIVE_ACCOUNT_SIGNED_PAYMENTS_FIXED_TEST_ALLOCATION'
GENERAL_SCHEMA='gg.lan-dag.session.v7'
GENERAL_MODE='NATIVE_ACCOUNT_SIGNED_PAYMENTS_GENERAL_TEST_ALLOCATION'
SESSION_SCHEMAS=(SCHEMA,GENERAL_SCHEMA)
FIELDS={'schema','label','coordinator','roster','financial_source','transactions_enabled','dag_test_mode','consensus','network_nonce'}
HASH=re.compile(r'[0-9a-f]{64}')


def _namespace(body,started):
    if type(body['network_nonce']) is not str or not HASH.fullmatch(body['network_nonce']):raise ValueError()
    value={key:deepcopy(body[key]) for key in ('label','coordinator','roster','consensus','network_nonce','transactions_enabled','dag_test_mode')}
    value.update(schema='gg.lan-dag.financial-namespace.v1',started_at_ns=str(started))
    if body['schema']==GENERAL_SCHEMA:
        value.update(schema='gg.lan-dag.financial-namespace.v2',financial_accounts=deepcopy(body['financial_accounts']))
    return digest(value,b'GG-LAN-FINANCIAL-NAMESPACE-v1\0')


def _native_genesis(membership,financial_accounts=None):
    members=[invite['body'] for invite in membership['validators']]
    genesis={'schema':'gg.native.genesis.v5','chain_id':membership['chain_id'],'genesis_time_unix':membership['genesis_time_unix'],
            'membership':deepcopy(membership),'accounts':[row['account_key'] for row in members],
            'validators':[row['validator_key'] for row in members],'supply_atomic':'1000000000000','decimals':6,'symbol':'GG-NET-TEST'}
    if financial_accounts is not None:
        genesis.update(schema='gg.native.genesis.v6',accounts=None,financial_accounts=deepcopy(financial_accounts))
    return genesis


def validate_bundle(bundle,coordinator):
    from backend.gg_lan_dag import _checked,_BUNDLE
    from backend.gg_dag_segmented_session import _roster
    from backend.gg_consensus_membership import label_wire,validate_membership
    from backend.gg_dag_segmented import validate_native_pin
    try:
        if type(coordinator) is not str or not HASH.fullmatch(coordinator) or len(pack(bundle))>256*1024:raise ValueError()
        body=_checked(bundle,_BUNDLE,coordinator)
        general=isinstance(body,dict) and body.get('schema')==GENERAL_SCHEMA
        fields=FIELDS|{'financial_accounts'} if general else FIELDS
        if (not isinstance(body,dict) or set(body)!=fields or body['schema'] not in SESSION_SCHEMAS or body['coordinator']!=coordinator
                or body['transactions_enabled'] is not True or body['dag_test_mode']!=(GENERAL_MODE if general else MODE)):raise ValueError()
        label_wire(body['label'])
        owners,producers,allowed=_roster(body['roster'],coordinator)
        membership=validate_membership(body['consensus'],owners=owners,forbidden_keys=[*owners,*producers])
        if general and not isinstance(body['financial_accounts'],dict):raise ValueError()
        genesis=_native_genesis(membership,body.get('financial_accounts'))
        source=financial.validate_source(body['financial_source'],genesis)
        if (source['schema'] not in financial.SESSION_SOURCE_SCHEMAS
                or (source['schema']==financial.GENERAL_SOURCE_SCHEMA)!=general):raise ValueError()
        network=_namespace(body,source['started_at_ns'])
        expected=financial.make_session_source(genesis,producers,allowed,network,source['started_at_ns'],schema=source['schema'])
        if source!=expected:raise ValueError()
        genesis['financial_dag']=source
        anchor=validate_native_pin({'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()})
        return {'anchor':anchor,'source':deepcopy(source),'network_id':network,'roster':deepcopy(body['roster'])}
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):raise ValueError('GG_LAN_FINANCIAL_SESSION_INVALID') from None


def make_bundle(coordinator,invites,membership,*,label,network_nonce,started_at_ns=None,source_schema=financial.LINEAGE_SOURCE_SCHEMA,financial_accounts=None):
    from backend.gg_lan_dag import validate_invite,_signed,_BUNDLE
    from backend.gg_dag_segmented_session import _roster
    from backend.gg_consensus_membership import label_wire,validate_membership
    try:
        label_wire(label)
        if not isinstance(invites,list) or len(invites)!=3:raise ValueError()
        checked=[(validate_invite(invite),invite) for invite in invites];checked.sort(key=lambda pair:pair[0]['peer_key'])
        roster=[{'invite':deepcopy(invite),'producer_indices':[2*index,2*index+1]} for index,(_,invite) in enumerate(checked)]
        owner=coordinator.pubkey().hex();owners,producers,allowed=_roster(roster,owner)
        membership=validate_membership(membership,owners=owners,forbidden_keys=[*owners,*producers])
        started=membership['genesis_time_unix']*10**9 if started_at_ns is None else started_at_ns
        if type(started) is not int:raise ValueError()
        general=source_schema==financial.GENERAL_SOURCE_SCHEMA
        if general!=(financial_accounts is not None):raise ValueError()
        body={'schema':SCHEMA,'label':label,'coordinator':owner,'roster':roster,'financial_source':None,
              'transactions_enabled':True,'dag_test_mode':MODE,'consensus':membership,'network_nonce':network_nonce}
        if general:body.update(schema=GENERAL_SCHEMA,dag_test_mode=GENERAL_MODE,financial_accounts=deepcopy(financial_accounts))
        network=_namespace(body,started)
        body['financial_source']=financial.make_session_source(_native_genesis(membership,financial_accounts),producers,allowed,network,started,schema=source_schema)
        bundle=_signed(coordinator,_BUNDLE,body);validate_bundle(bundle,owner);return bundle
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OverflowError,RecursionError):raise ValueError('GG_LAN_FINANCIAL_SESSION_INVALID') from None
