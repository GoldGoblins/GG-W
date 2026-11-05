"""Deterministic economic/work rules for the integrated protocol under build.

These pure functions calculate allocations and verify exact work intent. They
do not create balances, vote power, network membership or durable pool claims.
The versioned native commit path must bind fee debits, credits, accepted work,
economic state and receipts before CLI/Desktop may report actual rewards.
"""
from copy import deepcopy
import hashlib
import re
from threading import RLock

from backend.gg_parallel_dag import pack
from backend.gg_ed25519 import Keypair,verify_signature
from backend.gg_financial_dag import account_address

MAX_MONEY=2**64-1
MAX_RECIPIENTS=65536
HASH=re.compile(r'[0-9a-f]{64}')
DECIMAL=re.compile(r'0|[1-9][0-9]*')
POLICY_FIELDS={'epoch_reward_atomic','epoch_seconds','fee_per_byte_atomic','halving_epochs','initial_supply_atomic',
               'max_supply_atomic','min_fee_atomic','schema','tail_reward_atomic','treasury_account','treasury_bps'}
JOB_FIELDS={'epoch','expires_height','genesis_hash','job_nonce','network_target','payload_root','reward_account',
            'schema','share_target','state_height','state_root','worker_key'}
_WORK_TOKEN=object()


def _number(value,maximum=MAX_MONEY,*,positive=False):
    if type(value) is not str or len(value)>len(str(maximum)) or not DECIMAL.fullmatch(value):raise ValueError('GG_ECONOMIC_INTEGER')
    number=int(value)
    if not int(positive)<=number<=maximum:raise ValueError('GG_ECONOMIC_INTEGER')
    return number


def _integer(value,maximum=MAX_MONEY,*,positive=False):
    if type(value) is not int or not int(positive)<=value<=maximum:raise ValueError('GG_ECONOMIC_INTEGER')
    return value


def validate_policy(value):
    if not isinstance(value,dict) or set(value)!=POLICY_FIELDS or value['schema']!='gg.financial.economic-policy.v1':raise ValueError('GG_ECONOMIC_POLICY_INVALID')
    maximum=_number(value['max_supply_atomic'],positive=True);initial=_number(value['initial_supply_atomic'],maximum)
    reward=_number(value['epoch_reward_atomic'],maximum);_number(value['tail_reward_atomic'],reward)
    _number(value['epoch_seconds'],positive=True);_number(value['halving_epochs'],positive=True)
    _number(value['min_fee_atomic']);_number(value['fee_per_byte_atomic'])
    bps=_integer(value['treasury_bps'],10000)
    if bps:account_address(value['treasury_account'])
    elif value['treasury_account']!='':raise ValueError('GG_ECONOMIC_POLICY_INVALID')
    return deepcopy(value)


def rules_hash(policy,genesis_hash):
    policy=validate_policy(policy)
    if type(genesis_hash) is not str or not HASH.fullmatch(genesis_hash):raise ValueError('GG_ECONOMIC_POLICY_INVALID')
    return hashlib.sha256(b'GG-FINANCIAL-ECONOMY-v1\0'+genesis_hash.encode('ascii')+b'\0'+pack(policy)).hexdigest()


def initial_state(policy,genesis_hash):
    return {'issued_atomic':validate_policy(policy)['initial_supply_atomic'],'next_epoch':'0',
            'rules_hash':rules_hash(policy,genesis_hash),'schema':'gg.financial.economic-state.v1'}


def epoch_at(policy,genesis_time,certified_time):
    policy=validate_policy(policy);_integer(genesis_time);_integer(certified_time)
    if certified_time<genesis_time:raise ValueError('GG_ECONOMIC_POLICY_INVALID')
    return (certified_time-genesis_time)//int(policy['epoch_seconds'])


def minimum_fee(policy,wire_bytes):
    policy=validate_policy(policy);_integer(wire_bytes,32*1024*1024,positive=True)
    fee=int(policy['min_fee_atomic'])+wire_bytes*int(policy['fee_per_byte_atomic'])
    if fee>MAX_MONEY:raise ValueError('GG_ECONOMIC_POLICY_INVALID')
    return str(fee)


def weighted_credits(total_atomic,weights):
    total=_number(total_atomic)
    if not isinstance(weights,list) or not 1<=len(weights)<=MAX_RECIPIENTS:raise ValueError('GG_ECONOMIC_STATE_INVALID')
    rows=[];previous=''
    for row in weights:
        if not isinstance(row,dict) or set(row)!={'address','weight'}:raise ValueError('GG_ECONOMIC_STATE_INVALID')
        address=account_address(row['address']);weight=_number(row['weight'],2**512-1,positive=True)
        if address<=previous:raise ValueError('GG_ECONOMIC_STATE_INVALID')
        rows.append((address,weight));previous=address
    denominator=sum(weight for _,weight in rows)
    allocations=[{'address':address,'amount':total*weight//denominator,'remainder':total*weight%denominator} for address,weight in rows]
    remaining=total-sum(row['amount'] for row in allocations)
    if not 0<=remaining<len(allocations):raise ValueError('GG_ECONOMIC_STATE_INVALID')
    for row in sorted(allocations,key=lambda row:(-row['remainder'],row['address']))[:remaining]:row['amount']+=1
    return [{'address':row['address'],'amount_atomic':str(row['amount'])} for row in allocations if row['amount']]


def _add_credit(credits,address,amount):
    result={row['address']:int(row['amount_atomic']) for row in credits}
    if amount:result[address]=result.get(address,0)+amount
    if any(value>MAX_MONEY for value in result.values()):raise ValueError('GG_ECONOMIC_STATE_INVALID')
    return [{'address':key,'amount_atomic':str(value)} for key,value in sorted(result.items())]


def settle_epoch(policy,genesis_hash,before,epoch,certified_epoch,fees_atomic,weights):
    policy=validate_policy(policy);rules=rules_hash(policy,genesis_hash)
    if (not isinstance(before,dict) or set(before)!={'issued_atomic','next_epoch','rules_hash','schema'}
            or before['schema']!='gg.financial.economic-state.v1' or before['rules_hash']!=rules):raise ValueError('GG_ECONOMIC_STATE_INVALID')
    issued=_number(before['issued_atomic'],int(policy['max_supply_atomic']));next_epoch=_number(before['next_epoch'])
    _integer(epoch);_integer(certified_epoch);fees=_number(fees_atomic,issued)
    if issued<int(policy['initial_supply_atomic']) or epoch!=next_epoch or epoch>=certified_epoch or epoch==MAX_MONEY:
        raise ValueError('GG_ECONOMIC_STATE_INVALID')
    period=epoch//int(policy['halving_epochs'])
    reward=0 if period>=64 else int(policy['epoch_reward_atomic'])>>period
    reward=min(max(reward,int(policy['tail_reward_atomic'])),int(policy['max_supply_atomic'])-issued)
    if not isinstance(weights,list):raise ValueError('GG_ECONOMIC_STATE_INVALID')
    if not weights:
        if fees:raise ValueError('GG_ECONOMIC_STATE_INVALID')
        reward=0
    total=reward+fees;treasury=total*policy['treasury_bps']//10000
    credits=weighted_credits(str(total-treasury),weights) if weights else []
    credits=_add_credit(credits,policy['treasury_account'],treasury)
    after={**before,'next_epoch':str(epoch+1),'issued_atomic':str(issued+reward)}
    return {'credits':credits,'epoch':str(epoch),'fees_atomic':str(fees),'minted_atomic':str(reward),
            'next':after,'schema':'gg.financial.epoch-settlement.v1'}


def pool_allocation(reward_atomic,operator,commission_bps,shares):
    reward=_number(reward_atomic);account_address(operator);_integer(commission_bps,10000)
    commission=reward*commission_bps//10000
    return _add_credit(weighted_credits(str(reward-commission),shares),operator,commission)


def validate_job(value):
    if not isinstance(value,dict) or set(value)!=JOB_FIELDS or value['schema']!='gg.financial.mining-job.v1':raise ValueError('GG_MINING_WORK_INVALID')
    for name in ('genesis_hash','job_nonce','network_target','share_target','payload_root','state_root'):
        if type(value[name]) is not str or not HASH.fullmatch(value[name]):raise ValueError('GG_MINING_WORK_INVALID')
    _number(value['epoch']);height=_number(value['state_height']);expires=_number(value['expires_height'])
    if not height<expires<=height+65536 or not 0<int(value['network_target'],16)<=int(value['share_target'],16):raise ValueError('GG_MINING_WORK_INVALID')
    account_address(value['worker_key']);account_address(value['reward_account'])
    return deepcopy(value)


class VerifiedMiningShare:
    __slots__=('epoch','state_height','expires_height','genesis_hash','identifier','reward_account','weight','network_weight','network_work')
    def __init__(self,job,digest,*,token=None):
        if token is not _WORK_TOKEN:raise ValueError('GG_MINING_LOCAL_VERIFICATION_REQUIRED')
        for name,value in [('epoch',int(job['epoch'])),('state_height',int(job['state_height'])),('expires_height',int(job['expires_height'])),
                           ('genesis_hash',job['genesis_hash']),('identifier',digest.hex()),('reward_account',job['reward_account']),
                           ('weight',2**256//(int(job['share_target'],16)+1)),('network_weight',2**256//(int(job['network_target'],16)+1)),('network_work',int.from_bytes(digest,'big')<=int(job['network_target'],16))]:
            object.__setattr__(self,name,value)
    def __setattr__(self,name,value):raise AttributeError('immutable verified work')


def verify_work(expected,solution,current_height):
    expected=validate_job(expected);_integer(current_height)
    if (not isinstance(solution,dict) or set(solution)!={'job','nonce','schema','signature'}
            or solution['schema']!='gg.financial.mining-solution.v1' or solution['job']!=expected
            or not int(expected['state_height'])<=current_height<=int(expected['expires_height'])):raise ValueError('GG_MINING_WORK_INVALID')
    nonce=_number(solution['nonce']);signature=solution['signature']
    if type(signature) is not str or not re.fullmatch(r'[0-9a-f]{128}',signature):raise ValueError('GG_MINING_WORK_INVALID')
    digest=hashlib.sha256(b'GG-FINANCIAL-MINING-WORK-v1\0'+pack(expected)+nonce.to_bytes(8,'big')).digest()
    if int.from_bytes(digest,'big')>int(expected['share_target'],16):raise ValueError('GG_MINING_WORK_INVALID')
    verify_signature(bytes.fromhex(expected['worker_key']),b'GG-FINANCIAL-MINING-OWNER-v1\0'+digest,bytes.fromhex(signature))
    return VerifiedMiningShare(expected,digest,token=_WORK_TOKEN)


def mine_work(job,key,start,attempts,*,check=lambda:None):
    job=validate_job(job);_integer(start);_integer(attempts,1<<20,positive=True)
    if type(key) is not Keypair or key.pubkey().hex()!=job['worker_key'] or start>MAX_MONEY-(attempts-1):raise ValueError('GG_MINING_WORK_INVALID')
    header=b'GG-FINANCIAL-MINING-WORK-v1\0'+pack(job);target=int(job['share_target'],16)
    for offset in range(attempts):
        nonce=start+offset
        if offset%256==0:check()
        digest=hashlib.sha256(header+nonce.to_bytes(8,'big')).digest()
        if int.from_bytes(digest,'big')<=target:
            solution={'job':job,'nonce':str(nonce),'schema':'gg.financial.mining-solution.v1',
                      'signature':key.sign_message(b'GG-FINANCIAL-MINING-OWNER-v1\0'+digest).hex()}
            return solution,nonce if nonce==MAX_MONEY else nonce+1,nonce==MAX_MONEY
    last=start+attempts-1
    return None,last if last==MAX_MONEY else last+1,last==MAX_MONEY


class PoolShares:
    """Bounded verified share accounting; persistence/crediting belongs to commit."""
    def __init__(self,genesis_hash,epoch):
        if type(genesis_hash) is not str or not HASH.fullmatch(genesis_hash):raise ValueError('GG_MINING_WORK_INVALID')
        self.genesis_hash=genesis_hash;self.epoch=_integer(epoch);self._shares={};self._weights={}
        self._lock=RLock()

    def accept(self,share,current_height):
        _integer(current_height)
        with self._lock:
            if (type(share) is not VerifiedMiningShare or share.genesis_hash!=self.genesis_hash or share.epoch!=self.epoch
                    or not share.state_height<=current_height<=share.expires_height or len(self._shares)>=MAX_RECIPIENTS):raise ValueError('GG_MINING_WORK_INVALID')
            if share.identifier in self._shares:raise ValueError('GG_MINING_SHARE_ALREADY_ACCEPTED')
            total=self._weights.get(share.reward_account,0)+share.weight
            if total>=2**512:raise ValueError('GG_MINING_WORK_INVALID')
            self._shares[share.identifier]=share.reward_account;self._weights[share.reward_account]=total

    def allocation(self,reward_atomic,operator,commission_bps):
        with self._lock:weights=[{'address':address,'weight':str(weight)} for address,weight in sorted(self._weights.items())]
        return pool_allocation(reward_atomic,operator,commission_bps,weights)


def validate_committee(value):
    if (not isinstance(value,dict) or set(value)!={'epoch','members','schema'} or value['schema']!='gg.financial.public-committee.v1'
            or not isinstance(value['members'],list) or not 4<=len(value['members'])<=1024):raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
    _number(value['epoch']);previous='';owners=set();operational=set();accounts=set();total=0
    for member in value['members']:
        if not isinstance(member,dict) or set(member)!={'account_key','node_key','owner_peer_key','power','validator_key'}:raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
        power=_number(member['power'],2**50-1,positive=True);total+=power
        for name in ('account_key','node_key','owner_peer_key','validator_key'):account_address(member[name])
        if (member['validator_key']<=previous or member['node_key']==member['validator_key']
                or member['node_key'] in operational or member['validator_key'] in operational or total>=2**60):raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
        owners.add(member['owner_peer_key']);accounts.add(member['account_key']);operational.update([member['node_key'],member['validator_key']]);previous=member['validator_key']
    if operational&(owners|accounts) or owners&accounts:raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
    return deepcopy(value)


def committee_root(value,genesis_hash):
    value=validate_committee(value)
    if type(genesis_hash) is not str or not HASH.fullmatch(genesis_hash):raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
    return hashlib.sha256(b'GG-FINANCIAL-PUBLIC-COMMITTEE-v1\0'+genesis_hash.encode('ascii')+b'\0'+pack(value)).hexdigest()


def committee_change_plan(before,after,genesis_hash,decided_height,max_change_bps):
    before=validate_committee(before);after=validate_committee(after)
    _integer(decided_height,MAX_MONEY-2,positive=True);_integer(max_change_bps,3333,positive=True)
    if int(before['epoch'])==MAX_MONEY or int(after['epoch'])!=int(before['epoch'])+1:raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
    old={row['validator_key']:row for row in before['members']};updated={row['validator_key']:row for row in after['members']}
    total=sum(int(row['power']) for row in old.values());additions=0;removals=0
    for key,member in updated.items():
        previous=old.get(key)
        if previous is None:additions+=int(member['power']);continue
        if any(previous[name]!=member[name] for name in ('owner_peer_key','node_key','account_key')):raise ValueError('GG_DYNAMIC_COMMITTEE_INVALID')
        difference=int(member['power'])-int(previous['power'])
        additions+=max(0,difference);removals+=max(0,-difference)
    removals+=sum(int(row['power']) for key,row in old.items() if key not in updated)
    if max(additions,removals)*10000>total*max_change_bps:raise ValueError('GG_COMMITTEE_CHANGE_BUDGET')
    return {'decided_height':str(decided_height),'effective_height':str(decided_height+2),'from_root':committee_root(before,genesis_hash),
            'next':after,'next_root':committee_root(after,genesis_hash),'schema':'gg.financial.committee-change-plan.v1'}
