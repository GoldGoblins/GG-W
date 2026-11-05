"""Signed LAN v5 source contract; pure derivation, no pairing or activation.

The namespace binds roster/committee inputs before deriving the DAG genesis.
No complete-genesis digest is fed back into its own signing domain. Existing
LAN sessions are never converted and existing controllers do not auto-enable v5.
"""
from copy import deepcopy
import hashlib
import re

from backend.gg_parallel_dag import digest,pack
from backend import gg_dag_segmented as segmented

SCHEMA='gg.lan-dag.session.v5'
NAMESPACE_SCHEMA='gg.lan-dag.segmented-namespace.v1'
_HASH=re.compile(r'[0-9a-f]{64}')
_FIELDS={'schema','label','coordinator','roster','public_genesis','transactions_enabled','dag_test_mode','consensus','network_nonce'}


def _roster(roster,coordinator):
    from backend.gg_lan_dag import validate_invite
    if not isinstance(roster,list) or len(roster)!=3:raise ValueError()
    owners={};producers=[];allowed=[];order=[]
    for index,entry in enumerate(roster):
        if (not isinstance(entry,dict) or set(entry)!={'invite','producer_indices'}
                or not isinstance(entry['producer_indices'],list) or any(type(i) is not int for i in entry['producer_indices'])
                or entry['producer_indices']!=[2*index,2*index+1]):raise ValueError()
        owner=validate_invite(entry['invite']);key=owner['peer_key'];role=owner.get('node_role','producer')
        if key in owners or owner.get('allow_dag_transactions') is not True or role not in ('producer','replica','light'):raise ValueError()
        owners[key]=owner;order.append(key);producers.extend(owner['producer_keys'])
        if role=='producer':allowed.extend(entry['producer_indices'])
    if (order!=sorted(order) or coordinator not in owners or len(set(producers))!=6 or set(producers)&set(owners)
            or len({(row['host'],row['port']) for row in owners.values()})!=3):raise ValueError()
    return owners,producers,allowed


def _namespace(body,started):
    if type(body['network_nonce']) is not str or not _HASH.fullmatch(body['network_nonce']):raise ValueError()
    fields={key:deepcopy(body[key]) for key in ('label','coordinator','roster','consensus','network_nonce','dag_test_mode','transactions_enabled')}
    fields.update(schema=NAMESPACE_SCHEMA,started_at_ns=str(started))
    return digest(fields,b'GG-LAN-DAG-SEGMENTED-NAMESPACE-v1\0')


def validate_bundle(bundle,coordinator):
    """Verify the pinned signature and independently derive both public geneses.

    This proves signed session/source binding, not a running SDK quorum,
    reachable peer, durable local signing journal or full history replay.
    """
    from backend.gg_lan_dag import _checked,_BUNDLE
    from backend.gg_consensus_membership import label_wire,validate_membership
    try:
        if type(coordinator) is not str or not _HASH.fullmatch(coordinator) or len(pack(bundle))>256*1024:raise ValueError()
        body=_checked(bundle,_BUNDLE,coordinator)
        if (not isinstance(body,dict) or set(body)!=_FIELDS or body['schema']!=SCHEMA or body['coordinator']!=coordinator
                or body['transactions_enabled'] is not True or body['dag_test_mode']!='PRODUCER_OWNED_NONFINANCIAL'):raise ValueError()
        label_wire(body['label'])
        owners,producers,allowed=_roster(body['roster'],coordinator)
        membership=validate_membership(body['consensus'],owners=owners,forbidden_keys=[*owners,*producers])
        public=body['public_genesis']
        if (not isinstance(public,dict) or set(public)!={'schema','genesis','genesis_hash','accounts','started_at_ns'}
                or public['schema']!=segmented.PUBLIC_GENESIS_SCHEMA or type(public['started_at_ns']) is not int
                or not 10**9<=public['started_at_ns']<=membership['genesis_time_unix']*10**9+5_000_000_000):raise ValueError()
        network=_namespace(body,public['started_at_ns'])
        source=segmented.make_source(producers,allowed,network,started_at_ns=public['started_at_ns'])
        if public!=segmented.public_genesis(source):raise ValueError()
        members=[invite['body'] for invite in membership['validators']]
        genesis={'schema':'gg.native.genesis.v4','chain_id':membership['chain_id'],'genesis_time_unix':membership['genesis_time_unix'],
            'membership':membership,'accounts':[row['account_key'] for row in members],'validators':[row['validator_key'] for row in members],
            'dag_segmented':source,'supply_atomic':'1000000000000','decimals':6,'symbol':'GG-NET-TEST'}
        anchor=segmented.validate_native_pin({'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()})
        return {'anchor':anchor,'source':deepcopy(source),'network_id':network,'roster':deepcopy(body['roster'])}
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):
        raise ValueError('GG_LAN_SEGMENTED_SESSION_INVALID') from None


def make_bundle(coordinator,invites,membership,*,label,network_nonce,started_at_ns=None):
    """Construct an explicit v5 contract without installing it or generating keys.

    network_nonce is a new public 256-bit session nonce supplied by the caller.
    Repeating identical inputs is deterministic. Activation remains a separate
    owned runtime operation with its own persistent signer requirements.
    """
    from backend.gg_lan_dag import validate_invite,_signed,_BUNDLE
    from backend.gg_consensus_membership import label_wire,validate_membership
    try:
        label_wire(label)
        if not isinstance(invites,list) or len(invites)!=3:raise ValueError()
        checked=[(validate_invite(invite),invite) for invite in invites]
        checked.sort(key=lambda pair:pair[0]['peer_key'])
        roster=[{'invite':deepcopy(invite),'producer_indices':[2*i,2*i+1]} for i,(row,invite) in enumerate(checked)]
        owner=coordinator.pubkey().hex();owners,producers,allowed=_roster(roster,owner)
        membership=validate_membership(membership,owners=owners,forbidden_keys=[*owners,*producers])
        started=membership['genesis_time_unix']*10**9 if started_at_ns is None else started_at_ns
        body={'schema':SCHEMA,'label':label,'coordinator':owner,'roster':roster,'public_genesis':None,
            'transactions_enabled':True,'dag_test_mode':'PRODUCER_OWNED_NONFINANCIAL','consensus':membership,'network_nonce':network_nonce}
        network=_namespace(body,started)
        body['public_genesis']=segmented.public_genesis(segmented.make_source(producers,allowed,network,started_at_ns=started))
        bundle=_signed(coordinator,_BUNDLE,body);validate_bundle(bundle,owner)
        return bundle
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OverflowError,RecursionError):
        raise ValueError('GG_LAN_SEGMENTED_SESSION_INVALID') from None
