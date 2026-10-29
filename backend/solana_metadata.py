"""Bounded on-chain display metadata; names never identify a token or price."""
import base64
from backend import omni_assets as store
PROGRAM='metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s'


def address(mint):
    from solders.pubkey import Pubkey
    program=Pubkey.from_string(PROGRAM)
    return str(Pubkey.find_program_address([b'metadata',bytes(program),bytes(Pubkey.from_string(mint))],program)[0])


def decode(account,mint):
    from solders.pubkey import Pubkey
    try:
        if not account or account.get('owner')!=PROGRAM or account.get('executable') is True:return {}
        data=account['data']
        if not isinstance(data,list) or len(data)!=2 or data[1]!='base64' or not isinstance(data[0],str) or len(data[0])>5500:return {}
        raw=base64.b64decode(data[0],validate=True)
        if not 77<=len(raw)<=4096 or raw[0]!=4 or raw[33:65]!=bytes(Pubkey.from_string(mint)):return {}
        offset=65;fields=[]
        for limit in (32,10,200):
            size=int.from_bytes(raw[offset:offset+4],'little');offset+=4
            if size>limit or offset+size>len(raw):return {}
            fields.append(raw[offset:offset+size].decode('utf-8').rstrip('\0').strip());offset+=size
        return {'name':store.text(fields[0],96),'symbol':store.text(fields[1],24),'source':'METAPLEX_ONCHAIN'}
    except (ValueError,TypeError,KeyError,UnicodeError):return {}


def batch(network,mints):
    from backend import omni_rpc
    if len(mints)>128:raise ValueError('OMNI_METADATA_LIMIT')
    result={}
    for offset in range(0,len(mints),64):
        selected=mints[offset:offset+64]
        values=omni_rpc.rpc(network,'getMultipleAccounts',[[address(m) for m in selected],{'encoding':'base64','commitment':'confirmed'}]).get('value')
        if not isinstance(values,list) or len(values)!=len(selected):raise ValueError('OMNI_METADATA_RESPONSE')
        result.update({m:decode(value,m) for m,value in zip(selected,values)})
    return result
