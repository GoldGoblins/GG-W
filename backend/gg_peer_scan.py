"""Append-only observations of an authenticated peer log, never block admission.

REFUSED/DEFERRED positions do not advance the validated prefix until a separate
resolution references an actual locally admitted block. Heads are signed by the
owning NodeProfile; these hashes are not a consensus or availability certificate.
"""
import hashlib
import json

MAX_POSITION=4095
MAX_EVENTS=2*MAX_POSITION
MAX_EVENT_BYTES=1024
EMPTY=hashlib.sha256(b'GG-NODE-PEER-SCAN-v1\0').hexdigest()
REASONS={'REFUSED':'GG_DAG_PRODUCER_QUARANTINE_CREDIT','DEFERRED':'GG_DAG_PENDING_PARENTS'}


def pack(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def number(value,limit=MAX_POSITION):return type(value) is int and 0<=value<=limit
def valid_hash(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def initial(base=0):
    if not number(base):raise ValueError('GG_PEER_SCAN_BASE')
    return {'base':base,'position':base,'prefix':base,'declined':0,'events':0,'digest':EMPTY,'pending':{},'deferred':{}}


def event(kind,position,identifier,disposition='ADMITTED',reason=''):
    return {'schema':'gg.node.peer-scan-event.v1','kind':kind,'position':position,'hash':identifier,'disposition':disposition,'reason':reason}


def advance(state,value,known_hashes):
    if (not isinstance(value,dict) or set(value)!={'schema','kind','position','hash','disposition','reason'}
            or value['schema']!='gg.node.peer-scan-event.v1' or not number(value['position']) or value['position']==0
            or not valid_hash(value['hash']) or len(pack(value))>MAX_EVENT_BYTES or state['events']>=MAX_EVENTS):
        raise ValueError('GG_PEER_SCAN_EVENT')
    position=value['position'];identifier=value['hash'];disposition=value['disposition']
    if value['kind']=='OBSERVED':
        if position!=state['position']+1:raise ValueError('GG_PEER_SCAN_SEQUENCE')
        if disposition=='ADMITTED':
            if value['reason'] or identifier not in known_hashes:raise ValueError('GG_PEER_SCAN_NOT_ADMITTED')
        elif disposition not in REASONS or value['reason']!=REASONS[disposition]:raise ValueError('GG_PEER_SCAN_DISPOSITION')
        state['position']=position;state['pending'][position]=(identifier,disposition=='ADMITTED')
        if disposition=='DEFERRED':state['deferred'][position]=identifier
        if disposition!='ADMITTED':state['declined']+=1
    elif value['kind']=='VALIDATED':
        if (disposition!='ADMITTED' or value['reason'] or state['pending'].get(position)!=(identifier,False)
                or identifier not in known_hashes):raise ValueError('GG_PEER_SCAN_RESOLUTION')
        state['pending'][position]=(identifier,True)
        state['deferred'].pop(position,None)
    else:raise ValueError('GG_PEER_SCAN_KIND')
    while state['pending'].get(state['prefix']+1,(None,False))[1]:
        state['prefix']+=1;state['pending'].pop(state['prefix'])
    state['events']+=1
    state['digest']=hashlib.sha256(b'GG-NODE-PEER-SCAN-EVENT-v1\0'+bytes.fromhex(state['digest'])+state['events'].to_bytes(8,'big')+pack(value)).hexdigest()
    return state


def head(state):return {'schema':'gg.node.peer-scan-head.v1',**{key:state[key] for key in ('base','position','prefix','declined','events','digest')}}


def summary(state):return {'position':state['position'],'validated_prefix':state['prefix'],'declined_records':state['declined'],
    'unresolved_records':sum(not value[1] for value in state['pending'].values())}
