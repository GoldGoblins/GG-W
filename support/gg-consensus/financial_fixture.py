"""Independent monetary test vectors. Public synthetic seeds; no network or user keys."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.gg_ed25519 import Keypair

DOMAIN=b'GG-ORDERED-MONETARY-v1\0'


def pack(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
def digest(value):return hashlib.sha256(value).hexdigest()


def account_root(accounts):
    row=[hashlib.sha256(b'\0'+pack(item)).digest() for item in accounts]
    while len(row)>1:row=[hashlib.sha256(b'\1'+row[index]+row[index+1]).digest() for index in range(0,len(row),2)]
    return row[0].hex()


def receipt_root(receipts):
    row=[hashlib.sha256(DOMAIN+b'RECEIPT\0'+pack(item)).digest() for item in receipts]
    while len(row)>1:
        if len(row)%2:row.append(row[-1])
        row=[hashlib.sha256(DOMAIN+b'RECEIPT-NODE\0'+row[index]+row[index+1]).digest() for index in range(0,len(row),2)]
    return row[0]


def make(destination):
    keys=[Keypair.from_seed(hashlib.sha256(('GG PUBLIC monetary reference account '+str(index)).encode()).digest()) for index in range(4)]
    validators=[Keypair.from_seed(hashlib.sha256(('GG PUBLIC monetary reference validator '+str(index)).encode()).digest()).pubkey().hex() for index in range(4)]
    addresses=[key.pubkey().hex() for key in keys]
    genesis={'accounts':addresses,'chain_id':'ggnet:'+'e'*24,'decimals':6,'genesis_time_unix':1700000000,
        'schema':'gg.native.genesis.v1','supply_atomic':'1000000000000','symbol':'GG-NET-TEST','validators':validators}
    anchor=digest(pack(genesis))
    binding={'block_hash':digest(b'public monetary reference block'),'checkpoint':'1','epoch':'1','genesis_hash':anchor,
        'order_index':'1','schema':'gg.financial.execution-context.v1','source_hash':digest(b'public monetary reference source')}
    context=digest(DOMAIN+b'CONTEXT\0'+pack(binding))
    states={address:{'address':address,'balance_atomic':'250000000000','nonce':0} for address in addresses}
    before=account_root([states[name] for name in sorted(states)])
    inputs=[];receipts=[];previous=before
    for index in range(5000):
        source=index%4;target=(source+1)%4;amount=index%7+1;sender=states[addresses[source]];recipient=states[addresses[target]]
        body={'amount_atomic':str(amount),'chain_id':genesis['chain_id'],'genesis_hash':anchor,'nonce':sender['nonce'],
            'recipient':addresses[target],'sender':addresses[source],'version':1}
        raw=pack({'body':body,'signature':keys[source].sign_message(pack(body)).hex()});inputs.append(raw)
        sender['balance_atomic']=str(int(sender['balance_atomic'])-amount);sender['nonce']+=1
        recipient['balance_atomic']=str(int(recipient['balance_atomic'])+amount)
        after=account_root([states[name] for name in sorted(states)])
        receipts.append({'account_root_after':after,'account_root_before':previous,'context_hash':context,'index':index,
            'outcome':'APPLIED','schema':'gg.financial.receipt.v1','transaction_id':digest(DOMAIN+b'INTENT\0'+raw)})
        previous=after
    inputs_hash=hashlib.sha256(DOMAIN+b'INPUT\0'+context.encode('ascii')+struct.pack('>Q',len(inputs)))
    for raw in inputs:inputs_hash.update(struct.pack('>Q',len(raw)));inputs_hash.update(raw)
    summary={'account_root_after':previous,'account_root_before':before,'applied':5000,'context_hash':context,
        'input_hash':inputs_hash.hexdigest(),'receipts_root':'','rejected':0,'schema':'gg.financial.summary.v1','transactions':5000}
    summary['receipts_root']=digest(DOMAIN+b'RECEIPT-COMMITMENT\0'+pack(summary)+b'\0'+receipt_root(receipts))
    accounts=[states[name] for name in sorted(states)]
    assert sum(int(item['balance_atomic']) for item in accounts)==1000000000000 and all(item['nonce']==1250 for item in accounts)
    output=pack({'accounts':accounts,'anchor':anchor,'binding':binding,'genesis':genesis,
        'inputs':[base64.b64encode(item).decode('ascii') for item in inputs],'summary':summary})
    destination=Path(destination)
    with destination.open('xb') as stream:stream.write(output)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New output file for public test data; existing files are refused.')
    args=parser.parse_args();target=make(args.output)
    print(json.dumps({'scope':'PUBLIC_TEST_SEEDS_NOT_USER_KEYS','signed_monetary_transfers':5000,'fixture_bytes':target.stat().st_size}))
