"""Language-neutral operation descriptions. Formats never grant capabilities."""
from backend import omni_assets as store

OPERATIONS={'balance.read','owner.read','asset.transfer','asset.bridge','order.create','order.cancel','order.fulfill','proof.verify'}


def plan(intent):
    if not isinstance(intent,dict) or intent.get('schema')!='gg.intent.v1' or intent.get('operation') not in OPERATIONS:
        raise ValueError('OMNI_INTENT_SCHEMA')
    operation=intent['operation'];kind=intent.get('asset_kind')
    if kind not in {'FUNGIBLE','UNIQUE','EDITION'}:raise ValueError('OMNI_INTENT_ASSET_KIND')
    network=store.network(intent['chain_id']);destination=intent.get('destination_chain_id',network['id'])
    store.network(destination)
    route={'schema':'gg.route.v1','operation':operation,'asset_kind':kind,'chain_id':network['id'],'destination_chain_id':destination,
           'authority':'NONE','network_family':network['family'],'execution':'READ_ONLY','state':'ADAPTER_REQUIRED'}
    if destination!=network['id'] or operation=='asset.bridge':route.update(state='NO_VERIFIED_BRIDGE_ROUTE',execution='UNAVAILABLE')
    elif operation=='balance.read' and kind=='FUNGIBLE' and network['family'] in {'evm','solana','kaspa','tron','cardano'}:route['state']='PUBLIC_READ_ADAPTER'
    elif operation in {'owner.read','balance.read'} and kind in {'UNIQUE','EDITION'} and network['family'] in {'evm','kaspa'}:route['state']='NFT_READ_ADAPTER'
    elif operation.startswith('order.'):route.update(state='LOCAL_PAPER_ONLY',execution='LOCAL_PAPER')
    elif operation=='asset.transfer' and network['family']=='gglab' and kind=='FUNGIBLE':route.update(state='SESSION_LAB_ONLY',execution='LOCAL_LAB')
    elif operation=='asset.transfer':route.update(state='SIGNER_AND_EXECUTION_ADAPTER_REQUIRED',execution='UNAVAILABLE')
    elif operation=='proof.verify':route.update(state='EXPLICIT_PROOF_SYSTEM_REQUIRED',execution='UNAVAILABLE')
    return route
