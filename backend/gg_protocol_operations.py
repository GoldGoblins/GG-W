"""Exact protocol intents, protected authorizations and native-certified outcomes.

Account authorizations are immutable originals. Registration work and SDK
envelopes may be refreshed without another account signature. No function in
this module opens a profile, listener or wallet on import.
"""
import base64
from copy import deepcopy
import hashlib
import secrets
from contextlib import nullcontext

from backend.gg_node_store import pack,unpack
from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_dag_checkpoint import certificate_tip

DOCUMENT='gg.financial.protocol-authorization.v1'
OPERATION='gg.financial.protocol-operation.v1'
FEE='gg.financial.protocol-fee.v1'
MAX_OPERATION=128*1024
MAX_COUNTER=2**64-1


def _digest(domain,value):return hashlib.sha256(domain+pack(value)).hexdigest()


def intent_root(intent,trust):
    """Check public intent structure and derive its fee-signature binding."""
    if not isinstance(intent,dict) or len(intent)!=1 or len(pack(intent))>MAX_OPERATION-2048:raise ValueError('GG_PROTOCOL_INTENT')
    if 'producer' in intent:
        invite=protocol.validate_invite(intent['producer'],trust['genesis'])
        return _digest(b'GG-FINANCIAL-PRODUCER-ADMISSION-v1\0',invite)
    if 'committee' in intent:
        change=intent['committee']
        if not isinstance(change,dict) or set(change)!={'body','ballots','consents'}:raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
        body=change['body']
        fields={'expires_height','from_root','genesis_hash','next','schema','unused_key_policy'}
        if (not isinstance(body,dict) or set(body)!=fields or body['schema']!='gg.financial.committee-proposal.v1'
                or body['genesis_hash']!=trust['genesis_hash'] or body['unused_key_policy']!=protocol.UNUSED_KEY_POLICY):raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
        protocol._hash(body['from_root']);wire.counter(body['expires_height'],positive=True,maximum=MAX_COUNTER)
        next_committee=economy.validate_committee(body['next'])
        if len(next_committee['members'])>64:raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
        root=_digest(b'GG-FINANCIAL-COMMITTEE-PROPOSAL-v1\0',body)
        for kind,fields in (('ballots',{'validator_key','signature'}),('consents',{'validator_key','account_signature','node_signature','owner_signature','validator_signature'})):
            rows=change[kind]
            if not isinstance(rows,list) or len(rows)>64:raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
            previous=''
            for row in rows:
                if not isinstance(row,dict) or set(row)!=fields or financial.account_address(row['validator_key'])<=previous:raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
                if any(type(row[name]) is not str or not wire.SIGNATURE.fullmatch(row[name]) for name in fields-{'validator_key'}):raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
                previous=row['validator_key']
        return root
    if 'cancel' in intent:
        body=intent['cancel']
        if (not isinstance(body,dict) or set(body)!={'genesis_hash','nonce','replaces','schema','sender'}
                or body['schema']!='gg.financial.nonce-cancel.v1' or body['genesis_hash']!=trust['genesis_hash']):raise ValueError('GG_PROTOCOL_CANCEL_INTENT')
        financial.account_address(body['sender']);wire.counter(body['nonce'],maximum=MAX_COUNTER-1);protocol._hash(body['replaces'])
        return _digest(b'GG-FINANCIAL-NONCE-CANCEL-v1\0',body)
    raise ValueError('GG_PROTOCOL_INTENT')


def verify_committee_intent(intent,packet,trust,*,require_quorum=True,binary=None,stamp=None):
    root=intent_root(intent,trust)
    if 'committee' not in intent:raise ValueError('GG_PROTOCOL_COMMITTEE_INTENT')
    protocol.verify_selected(packet,trust,binary=binary,stamp=stamp)
    state=packet['state'];current=state['protocol']['committee'];change=intent['committee'];body=change['body']
    if (state['protocol'].get('pending_committee') is not None or body['from_root']!=economy.committee_root(current,trust['genesis_hash'])
            or not state['height']<int(body['expires_height'])<=state['height']+65536):raise ValueError('GG_PROTOCOL_COMMITTEE_CONTEXT')
    economy.committee_change_plan(current,body['next'],trust['genesis_hash'],state['height']+1,trust['genesis']['protocol']['max_committee_change_bps'])
    old={row['validator_key']:row for row in current['members']};approved=0
    for ballot in change['ballots']:
        member=old.get(ballot['validator_key'])
        if member is None:raise ValueError('GG_PROTOCOL_COMMITTEE_BALLOT')
        protocol._signature(member['account_key'],ballot['signature'],b'GG-FINANCIAL-COMMITTEE-BALLOT-v1\0'+root.encode()+b'\0'+ballot['validator_key'].encode())
        approved+=int(member['power'])
    if require_quorum and approved*3<=2*sum(int(row['power']) for row in current['members']):raise ValueError('GG_COMMITTEE_GOVERNANCE_QUORUM')
    additions={row['validator_key']:row for row in body['next']['members'] if row['validator_key'] not in old}
    consents={row['validator_key']:row for row in change['consents']}
    if require_quorum and set(consents)!=set(additions) or not set(consents)<=set(additions):raise ValueError('GG_PROTOCOL_COMMITTEE_CONSENT')
    for key,consent in consents.items():
        member=additions[key];message=b'GG-FINANCIAL-COMMITTEE-MEMBER-CONSENT-v1\0'+root.encode()+b'\0'+key.encode()
        for role,field in (('account','account_key'),('node','node_key'),('owner','owner_peer_key'),('validator','validator_key')):
            protocol._signature(member[field],consent[role+'_signature'],message)
    return root


def authorization_id(fee):return _digest(b'GG-FINANCIAL-PROTOCOL-AUTHORIZATION-v1\0',fee)


def receipt_selector(sender,nonce):
    financial.account_address(sender);wire.counter(str(nonce),maximum=MAX_COUNTER-1)
    key=hashlib.sha256(b'GG-FINANCIAL-OPERATION-RECEIPT-KEY-v1\0'+sender.encode()+b'\0'+str(nonce).encode()).hexdigest()
    return {'namespace':'operations','key':key}


def fee_body(intent,trust,sender,nonce,max_fee=None):
    financial.account_address(sender);wire.counter(str(nonce),maximum=MAX_COUNTER-1)
    body={'chain_id':trust['genesis']['chain_id'],'genesis_hash':trust['genesis_hash'],'max_fee_atomic':'0',
        'nonce':str(nonce),'operation_root':intent_root(intent,trust),'schema':FEE,'sender':sender}
    if 'cancel' in intent and (intent['cancel']['sender']!=sender or intent['cancel']['nonce']!=str(nonce)):raise ValueError('GG_PROTOCOL_CANCEL_INTENT')
    if 'producer' in intent and intent['producer']['body']['reward_account']!=sender:raise ValueError('GG_PROTOCOL_REGISTRATION_REWARD_ACCOUNT')
    # A signed cap is reviewed before work is available. Bound all changing
    # work counters at their maximum decimal length; no invented signature is
    # exposed, submitted, or treated as a valid original.
    template={'fee':{'body':body,'signature':'0'*128},'schema':OPERATION,**deepcopy(intent)}
    if 'producer' in intent:
        template['producer']={'invite':intent['producer'],'work':{'job':{
            'epoch':str(MAX_COUNTER),'expires_height':str(MAX_COUNTER),'genesis_hash':'0'*64,'job_nonce':'0'*64,
            'network_target':'f'*64,'payload_root':'0'*64,'reward_account':sender,'schema':'gg.financial.mining-job.v1',
            'share_target':'f'*64,'state_height':str(MAX_COUNTER),'state_root':'0'*64,'worker_key':'0'*64},
            'nonce':str(MAX_COUNTER),'schema':'gg.financial.mining-solution.v1','signature':'0'*128}}
    if max_fee is not None:body['max_fee_atomic']=str(wire.counter(max_fee,maximum=MAX_COUNTER))
    for _ in range(24):
        size=len(pack(template))
        if size>MAX_OPERATION:raise ValueError('GG_PROTOCOL_OPERATION_LIMIT')
        minimum=economy.minimum_fee(trust['genesis']['protocol']['economics'],size)
        if max_fee is not None:
            if int(body['max_fee_atomic'])<int(minimum):raise ValueError('GG_PROTOCOL_OPERATION_FEE_LIMIT')
            return deepcopy(body)
        if body['max_fee_atomic']==minimum:return deepcopy(body)
        body['max_fee_atomic']=minimum
    raise ValueError('GG_FINANCIAL_FEE_QUOTE_DID_NOT_CONVERGE')


def decode_authorization(raw,trust):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_OPERATION:raise ValueError('GG_PROTOCOL_AUTHORIZATION_DOCUMENT')
    value=unpack(raw)
    if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','intent','fee'} or value['schema']!=DOCUMENT
            or value['genesis_hash']!=trust['genesis_hash'] or pack(value)!=raw):raise ValueError('GG_PROTOCOL_AUTHORIZATION_DOCUMENT')
    fee=value['fee']
    if not isinstance(fee,dict) or set(fee)!={'body','signature'}:raise ValueError('GG_PROTOCOL_FEE_AUTHORIZATION')
    body=fee['body']
    if (not isinstance(body,dict) or set(body)!={'chain_id','genesis_hash','max_fee_atomic','nonce','operation_root','schema','sender'}
            or body['schema']!=FEE or body['chain_id']!=trust['genesis']['chain_id'] or body['genesis_hash']!=trust['genesis_hash']
            or body['operation_root']!=intent_root(value['intent'],trust)):raise ValueError('GG_PROTOCOL_FEE_AUTHORIZATION')
    wire.counter(body['nonce'],maximum=MAX_COUNTER-1);wire.counter(body['max_fee_atomic'],maximum=MAX_COUNTER)
    protocol._signature(body['sender'],fee['signature'],b'GG-FINANCIAL-PROTOCOL-FEE-v1\0'+pack(body))
    if 'producer' in value['intent'] and value['intent']['producer']['body']['reward_account']!=body['sender']:raise ValueError('GG_PROTOCOL_FEE_AUTHORIZATION')
    if 'cancel' in value['intent'] and (value['intent']['cancel']['sender']!=body['sender'] or value['intent']['cancel']['nonce']!=body['nonce']):raise ValueError('GG_PROTOCOL_FEE_AUTHORIZATION')
    return value


def assemble(raw,packet,trust,*,worker=None,start=0,attempts=65536,check=lambda:None,binary=None,stamp=None):
    value=decode_authorization(raw,trust);protocol.verify_selected(packet,trust,binary=binary,stamp=stamp)
    intent=value['intent'];operation={'schema':OPERATION,'fee':value['fee'],**deepcopy(intent)}
    next_nonce=start
    if 'committee' in intent:verify_committee_intent(intent,packet,trust,binary=binary,stamp=stamp)
    if 'producer' in intent:
        if worker is None:raise ValueError('GG_PROTOCOL_MINING_WORKER_REQUIRED')
        state=packet['state']['protocol'];height=int(state['work_anchor_height']);invite=intent['producer'];policy=trust['genesis']['protocol']
        job={'epoch':state['economics']['next_epoch'],'expires_height':str(height+int(policy['max_work_heights'])),
            'genesis_hash':trust['genesis_hash'],'job_nonce':invite['body']['nonce'],'network_target':policy['registration_work_target'],
            'payload_root':_digest(b'GG-FINANCIAL-REGISTRATION-WORK-v1\0',{'fee':value['fee'],'invite':invite}),
            'reward_account':invite['body']['reward_account'],'schema':'gg.financial.mining-job.v1','share_target':policy['registration_work_target'],
            'state_height':str(height),'state_root':state['work_anchor_root'],'worker_key':worker.pubkey().hex()}
        solution,next_nonce,exhausted=economy.mine_work(job,worker,start,attempts,check=check)
        if solution is None:return None,next_nonce,exhausted
        operation['producer']={'invite':invite,'work':solution}
    if len(pack(operation))>MAX_OPERATION or int(economy.minimum_fee(trust['genesis']['protocol']['economics'],len(pack(operation))))>int(value['fee']['body']['max_fee_atomic']):raise ValueError('GG_PROTOCOL_OPERATION_FEE_LIMIT')
    return operation,next_nonce,False


def outcome(raw,packet,trust,*,binary=None,stamp=None):
    original=decode_authorization(raw,trust);fee=original['fee'];body=fee['body'];selector=receipt_selector(body['sender'],body['nonce'])
    verified=protocol.verify_selected(packet,trust,registry=selector,binary=binary,stamp=stamp)
    if not verified['financial_registry_exists']:return {'state':'NO_OPERATION_RECEIPT','payment_execution_asserted':False,'nonce_outcome_resolved':False}
    receipt=unpack(base64.b64decode(verified['financial_registry_value'],validate=True));matches=receipt['authorization_id']==authorization_id(fee)
    return {'state':receipt['kind'] if matches else 'OTHER_AUTHORIZATION_CONSUMED_NONCE','matches_original':matches,'receipt':receipt,
            'certificate_height':packet['state']['height']+1,'payment_execution_asserted':False,'nonce_outcome_resolved':True}


def make_producer_invite(owner,node_profile,trust,slot,reward_account,*,label,platform):
    if type(slot) is not int or slot not in (0,1):raise ValueError('GG_PROTOCOL_PRODUCER_SLOT')
    with owner._lock,node_profile._lock:
        identity,producers=owner.signers()
        if hasattr(node_profile,'native_signers'):
            _,node=node_profile.native_signers();declared=node_profile.public_invite()['body']['owner_peer_key']
        else:node=node_profile.native_node_signer();declared=node_profile._body['owner_key']
        if declared!=identity.pubkey().hex():raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
        body={'chain_id':trust['genesis']['chain_id'],'label_utf8':base64.b64encode(label.encode('utf-8')).decode(),
            'network_id':trust['genesis']['financial_dag']['network_id'],'node_key':node.pubkey().hex(),'nonce':secrets.token_hex(32),
            'owner_peer_key':identity.pubkey().hex(),'platform':platform,'producer_key':producers[slot].pubkey().hex(),
            'reward_account':reward_account,'schema':'gg.financial.producer-registration.v1','unused_key_policy':protocol.UNUSED_KEY_POLICY}
        message=b'GG-FINANCIAL-PRODUCER-REGISTRATION-v1\0'+pack(body)
        invite={'body':body,'node_signature':node.sign_message(message).hex(),'owner_signature':identity.sign_message(message).hex(),
                'producer_signature':producers[slot].sign_message(message).hex()}
        return protocol.validate_invite(invite,trust['genesis'])


def validate_governance_record(value,own):
    if (not isinstance(value,dict) or set(value)!={'schema','pin','floor','ballot','consent'}
            or value['schema']!='gg.protocol.governance-originals.v1' or len(pack(value))>768*1024):raise ValueError('GG_PROTOCOL_GOVERNANCE_RECORD')
    pin=protocol.validate_pin(value['pin']);floor=value['floor']
    if (not isinstance(floor,list) or len(floor)!=3 or type(floor[0]) is not int or not 1<=floor[0]<2**63
            or any(type(part) is not str or not wire.HASH.fullmatch(part) for part in floor[1:])):raise ValueError('GG_PROTOCOL_GOVERNANCE_RECORD')
    for kind in ('ballot','consent'):
        record=value[kind]
        if record is None:continue
        if not isinstance(record,dict) or set(record)!={'body','signed'}:raise ValueError('GG_PROTOCOL_GOVERNANCE_RECORD')
        signed=record['signed'];root=intent_root({'committee':{'body':record['body'],'ballots':[],'consents':[]}},pin)
        key=own['validator_key']
        if not isinstance(signed,dict) or signed.get('validator_key')!=key:raise ValueError('GG_PROTOCOL_GOVERNANCE_RECORD')
        if kind=='ballot':
            if set(signed)!={'validator_key','signature'}:raise ValueError('GG_PROTOCOL_GOVERNANCE_RECORD')
            protocol._signature(own['account_key'],signed['signature'],b'GG-FINANCIAL-COMMITTEE-BALLOT-v1\0'+root.encode()+b'\0'+key.encode())
        else:
            if set(signed)!={'validator_key','account_signature','node_signature','owner_signature','validator_signature'}:raise ValueError('GG_PROTOCOL_GOVERNANCE_RECORD')
            message=b'GG-FINANCIAL-COMMITTEE-MEMBER-CONSENT-v1\0'+root.encode()+b'\0'+key.encode()
            for role,field in (('account','account_key'),('node','node_key'),('owner','owner_peer_key'),('validator','validator_key')):
                protocol._signature(own[field],signed[role+'_signature'],message)
    return value


def sign_committee(profile,owner,intent,packet,trust,*,consent=False,account_profile=None,binary=None,stamp=None):
    root=verify_committee_intent(intent,packet,trust,require_quorum=False,binary=binary,stamp=stamp)
    reference=profile.account_reference()
    if reference is not None:
        from backend.gg_financial_account import AccountProfile
        if (type(account_profile) is not AccountProfile or account_profile._lease is None or account_profile.name!=reference['profile']
                or account_profile.public_address()!=reference['public_key'] or account_profile.anchor()!=trust):raise ValueError('GG_VALIDATOR_OWNED_ACCOUNT_REQUIRED')
    with (account_profile._lock if reference is not None else nullcontext()),owner._lock,profile._lock:
        if reference is not None:account_profile._check()
        identity,_=owner.signers();voter,node=profile.native_signers();account=account_profile._key if reference is not None else profile._keys[2]
        key=voter.pubkey().hex();own={'validator_key':key,'node_key':node.pubkey().hex(),'account_key':account.pubkey().hex(),'owner_peer_key':identity.pubkey().hex()}
        invite=profile.public_invite()['body']
        if any(invite[name]!=value for name,value in own.items()):raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
        stored=profile._body.get('protocol_governance');bound=profile.anchor()
        if bound is not None and bound!=trust:raise ValueError('GG_VALIDATOR_NETWORK_ALREADY_BOUND')
        tip=[*certificate_tip(packet,trust),packet['state']['state_root']];kind='consent' if consent else 'ballot';body=intent['committee']['body']
        if stored is not None:
            validate_governance_record(stored,invite)
            if stored['pin']!=trust:raise ValueError('GG_VALIDATOR_NETWORK_ALREADY_BOUND')
            floor=stored['floor']
            if tip[0]<floor[0] or tip[0]==floor[0] and tip!=floor:raise ValueError('GG_PROTOCOL_GOVERNANCE_CERTIFICATE_REWIND_OR_CONFLICT')
            previous=stored[kind]
            if previous is not None:
                if previous['body']==body:
                    if tip!=floor:
                        journal=deepcopy(stored);journal['floor']=tip;profile._write({'protocol_governance':journal})
                    return deepcopy(previous['signed'])
                if previous['body']['from_root']==body['from_root'] and packet['state']['height']<=int(previous['body']['expires_height']):raise ValueError('GG_PROTOCOL_GOVERNANCE_PENDING_ORIGINAL_REQUIRED')
        committee=intent['committee']['body']['next'] if consent else packet['state']['protocol']['committee']
        if not any(all(row[name]==value for name,value in own.items()) for row in committee['members']):raise ValueError('GG_PROTOCOL_COMMITTEE_SIGNER')
        if consent:
            if key in {row['validator_key'] for row in packet['state']['protocol']['committee']['members']}:raise ValueError('GG_PROTOCOL_EXISTING_MEMBER_CONSENT')
            message=b'GG-FINANCIAL-COMMITTEE-MEMBER-CONSENT-v1\0'+root.encode()+b'\0'+key.encode()
            signed={'validator_key':key,'account_signature':account.sign_message(message).hex(),'node_signature':node.sign_message(message).hex(),
                    'owner_signature':identity.sign_message(message).hex(),'validator_signature':voter.sign_message(message).hex()}
        else:signed={'validator_key':key,'signature':account.sign_message(b'GG-FINANCIAL-COMMITTEE-BALLOT-v1\0'+root.encode()+b'\0'+key.encode()).hex()}
        journal=deepcopy(stored) if stored is not None else {'schema':'gg.protocol.governance-originals.v1','pin':deepcopy(trust),'floor':tip,'ballot':None,'consent':None}
        journal['floor']=tip;journal[kind]={'body':deepcopy(body),'signed':signed};validate_governance_record(journal,invite)
        profile._write({'protocol_governance':journal})
        return deepcopy(signed)
