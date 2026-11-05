"""Explicit segmented source/state codecs and SDK-backed public observations.

Shape checks below are not consensus or history proofs. verify_membership pins
the caller's owned genesis and invokes the real native SDK verifier itself.
Nothing starts, signs, pairs a device or changes node state at import.
"""
from copy import deepcopy
import hashlib
import re

from backend import gg_dag_execution_policy as rules
from backend.gg_parallel_dag import digest, pack

SOURCE_SCHEMA='gg.dag.consensus.source.v2'
GENESIS_SCHEMA='gg.parallel-dag.genesis.v4'
STATE_SCHEMA='gg.dag.segmented-commitment.v1'
PUBLIC_GENESIS_SCHEMA='gg.parallel-dag.public-genesis.v4'
ARCHIVE_SCOPE='FULL_ORIGINAL_SIGNED_SEGMENT_CHAIN_AND_ACTIVE_REPLAY_WITH_PINNED_SDK_CERTIFICATE_NOT_NATIVE_TRANSFER_HISTORY'
BASE_SCOPE='SDK_CERTIFIED_CUT_PREIMAGE_AND_EPOCH_BASE_NOT_FULL_HISTORY_REPLAY'
CLOSED_SCOPE='SDK_CERTIFIED_CLOSED_CUT_AND_SELECTED_MEMBERSHIP_NOT_FULL_HISTORY_REPLAY'
MAX_COUNTER=2**63-1
_HASH=re.compile(r'[0-9a-f]{64}')
_DECIMAL=re.compile(r'0|[1-9][0-9]{0,19}')
_STATE_KEYS={'active','anchor','authors','blocks','closed_root','epoch','last_cut','last_rank','raw_bytes','schema','source_hash','transactions'}
_ACTIVE_KEYS={'account_root','blocks','chain_id','checkpoint','genesis_hash','manifest_hash','network_id','order_root','previous','schema','time_ns','transactions'}

def history_policy():
    return {'archive_mode':'ORIGINAL_SIGNED_SEGMENTS_REQUIRED','boundary':'SDK_CERTIFIED_CUT','counter_limit':str(MAX_COUNTER),
        'counter_scope':'GLOBAL_WITH_ACTIVE_SEGMENT_OFFSETS','profile':'GG-DAG-SEGMENTED-v1','schema':'gg.dag.history-policy.v1',
        'verification':'FULL_SIGNED_ARCHIVE_CHAIN_REPLAY'}

def _decimal(value,low=0,high=MAX_COUNTER):
    if type(value) is not str or not _DECIMAL.fullmatch(value) or not low<=int(value)<=high:raise ValueError()
    return int(value)

def _integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError()
    return value

def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):raise ValueError()
    return value

def chain_id(source):
    value=deepcopy(source);value['genesis']['chain_id']='';value['genesis_hash']=''
    return 'ggdag:'+digest(value,b'GG-DAG-SEGMENTED-CHAIN-ID-v1\0')

def validate_source(value):
    try:
        if not isinstance(value,dict) or len(pack(value))>16384:raise ValueError()
        source=deepcopy(value);genesis=source['genesis']
        if (set(source)!={'accounts','allowed_producers','genesis','genesis_hash','network_id','schema','signature_profile','started_at_ns'}
                or not isinstance(genesis,dict) or set(genesis)!={'account_count','allocation_atomic','chain_id','execution_policy',
                    'history_policy','precheck_root','producers','schema','test_mode'}
                or source['schema']!=SOURCE_SCHEMA or genesis['schema']!=GENESIS_SCHEMA
                or genesis['history_policy']!=history_policy() or genesis['chain_id']!=chain_id(source)
                or source['genesis_hash']!=digest(genesis)):raise ValueError()
        rules.require_execution_policy(genesis['execution_policy'])
        # Share every legacy account/key/role/initial-root rule without changing
        # legacy acceptance. This is a private validation view, never the pin.
        view=deepcopy(source);view['schema']='gg.dag.consensus.source.v1'
        view['genesis']['schema']=rules.GENESIS_SCHEMA;del view['genesis']['history_policy']
        view['genesis']['chain_id']=view['genesis']['chain_id'][:30]
        view['genesis_hash']=digest(view['genesis'])
        from backend.gg_dag_checkpoint import validate_source as legacy_validate
        legacy_validate(view)
        return source
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_SEGMENTED_SOURCE_INVALID') from None


def make_source(producers,allowed_producers,network_id,*,started_at_ns=None):
    """Construct a new explicit source; never upgrade an existing session."""
    import time
    from backend.gg_ed25519 import SIGNATURE_PROFILE
    from backend.gg_parallel_dag import _tree
    started=time.time_ns() if started_at_ns is None else started_at_ns
    _integer(started,1,MAX_COUNTER)
    if not isinstance(producers,list) or len(producers)!=6 or any(type(key) is not str or not _HASH.fullmatch(key) for key in producers):raise ValueError('GG_DAG_SEGMENTED_SOURCE_INVALID')
    accounts=sorted(producers)
    leaves=[{'address':key,'balance_atomic':'1000000000','nonce':0} for key in accounts]
    source={'schema':SOURCE_SCHEMA,'signature_profile':SIGNATURE_PROFILE,'accounts':accounts,
        'allowed_producers':deepcopy(allowed_producers),'network_id':network_id,'started_at_ns':str(started),
        'genesis_hash':'','genesis':{'account_count':6,'allocation_atomic':'1000000000','chain_id':'',
            'execution_policy':rules.execution_policy(),'history_policy':history_policy(),
            'precheck_root':_tree(leaves,b'GG-DAG-ACCOUNT-v1\0')[-1][0],'producers':deepcopy(producers),
            'schema':GENESIS_SCHEMA,'test_mode':'PRODUCER_OWNED_NONFINANCIAL'}}
    source['genesis']['chain_id']=chain_id(source);source['genesis_hash']=digest(source['genesis'])
    return validate_source(source)


def public_genesis(source):
    source=validate_source(source)
    return {'schema':PUBLIC_GENESIS_SCHEMA,'genesis':source['genesis'],'genesis_hash':source['genesis_hash'],
        'accounts':source['accounts'],'started_at_ns':int(source['started_at_ns'])}


def initial_context(source,anchor):
    """Derived empty genesis context; no certificate/history assertion."""
    from backend.gg_parallel_dag import _tree
    source=validate_source(source);_hash(anchor)
    source_hash=digest(source,b'GG-DAG-CONSENSUS-SOURCE-v2\0')
    manifest={'blocks':[],'checkpoint':0,'genesis_hash':anchor,'previous':'0'*64,
        'schema':'gg.dag.execution.manifest.v1','source_hash':source_hash,'time_ns':'0'}
    state={'schema':STATE_SCHEMA,'anchor':anchor,'source_hash':source_hash,'epoch':'1','blocks':'0','transactions':'0',
        'raw_bytes':'0','last_rank':'0','last_cut':source['genesis_hash'],
        'closed_root':hashlib.sha256(b'GG-DAG-CLOSED-SEGMENTS-v1\0EMPTY\0').hexdigest(),
        'authors':[{'head':source['genesis_hash'],'key':key,'sequence':'0','nonce':'0'} for key in source['genesis']['producers']],
        'active':{'schema':'gg.dag.commitment.v1','account_root':source['genesis']['precheck_root'],
            'blocks':0,'chain_id':source['genesis']['chain_id'],'checkpoint':0,'genesis_hash':source['genesis_hash'],
            'manifest_hash':digest(manifest,b'GG-DAG-CHECKPOINT-MANIFEST-v1\0'),'network_id':source['network_id'],
            'order_root':_tree([],b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0],'previous':'0'*64,'time_ns':'0','transactions':0}}
    return {'commitment':validate_state(state,source,anchor),
        'accounts':[{'address':key,'balance_atomic':'1000000000','nonce':0} for key in source['accounts']]}


def check_order(value,order,source,base):
    """Complete selected active order consistency, not SDK/signature replay.

    The caller owns the verified epoch base and separately verifies the SDK
    certificate. Actual payload admission is required before local execution.
    """
    from backend.gg_parallel_dag import _tree
    try:
        source=validate_source(source)
        start=validate_state(base['commitment'],source,base['commitment']['anchor'])
        _archive_accounts(base['accounts'],start,source)
        state=validate_state(value,source,start['anchor'])
        if (start['active']['blocks']!=0 or state['epoch']!=start['epoch'] or state['last_cut']!=start['last_cut']
                or state['closed_root']!=start['closed_root'] or not isinstance(order,list) or len(order)!=state['active']['blocks']
                or int(state['blocks'])!=int(start['blocks'])+len(order)):raise ValueError()
        heads=[row['head'] for row in start['authors']];sequences=[int(row['sequence']) for row in start['authors']]
        nonces=[int(row['nonce']) for row in start['authors']];seen=set();internal=[];transactions=int(start['transactions'])
        keys={'creator_key','global_index','hash','index','producer_index','sequence','transactions'}
        for index,leaf in enumerate(order,1):
            if not isinstance(leaf,dict) or set(leaf)!=keys or _integer(leaf['index'],1,rules.MAX_HISTORY_BLOCKS)!=index:raise ValueError()
            producer=_integer(leaf['producer_index'],0,5);identifier=_hash(leaf['hash'])
            sequence=_decimal(leaf['sequence'],1);count=_integer(leaf['transactions'],0,rules.MAX_BLOCK_TRANSACTIONS)
            if (producer not in source['allowed_producers'] or leaf['creator_key']!=source['genesis']['producers'][producer]
                    or _decimal(leaf['global_index'],1)!=int(start['blocks'])+index or identifier in seen
                    or sequence!=sequences[producer]+1):raise ValueError()
            seen.add(identifier);heads[producer]=identifier;sequences[producer]=sequence;nonces[producer]+=count;transactions+=count
            internal.append({'hash':identifier,'index':index,'producer_index':producer,'sequence':sequence,'transactions':count})
        if (transactions!=int(state['transactions']) or _tree(internal,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0]!=state['active']['order_root']
                or any(row['head']!=heads[i] or int(row['sequence'])!=sequences[i] or int(row['nonce'])!=nonces[i] for i,row in enumerate(state['authors']))):raise ValueError()
        return state,internal
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_SEGMENTED_ORDER_INVALID') from None

def validate_state(value,source,anchor):
    """Exact public shape only; no boolean or snapshot can stand in for replay."""
    try:
        source=validate_source(source);_hash(anchor)
        if not isinstance(value,dict) or set(value)!=_STATE_KEYS or len(pack(value))>8192:raise ValueError()
        state=deepcopy(value);active=state['active']
        if (not isinstance(active,dict) or set(active)!=_ACTIVE_KEYS or state['schema']!=STATE_SCHEMA or state['anchor']!=anchor
                or state['source_hash']!=digest(source,b'GG-DAG-CONSENSUS-SOURCE-v2\0')):raise ValueError()
        blocks=_decimal(state['blocks']);epoch=_decimal(state['epoch'],1);rank=_decimal(state['last_rank'])
        raw_bytes=_decimal(state['raw_bytes'],0,2**64-1);transactions=_decimal(state['transactions'],0,6*10**9)
        count=_integer(active['blocks'],0,rules.MAX_HISTORY_BLOCKS)
        checkpoint=_integer(active['checkpoint'],0,count)
        if (not epoch-1<=rank<=blocks or blocks>0 and rank==0 or blocks<epoch-1 or raw_bytes<blocks
                or count>blocks-(epoch-1) or transactions>blocks*rules.MAX_BLOCK_TRANSACTIONS
                or _integer(active['transactions'],0,6*10**9)!=transactions
                or active['schema']!='gg.dag.commitment.v1' or active['chain_id']!=source['genesis']['chain_id']
                or active['genesis_hash']!=source['genesis_hash'] or active['network_id']!=source['network_id']):raise ValueError()
        for root in (state['closed_root'],state['last_cut'],active['account_root'],active['order_root'],active['previous'],active['manifest_hash']):_hash(root)
        authors=state['authors']
        if not isinstance(authors,list) or len(authors)!=6:raise ValueError()
        sequence_total=nonce_total=0
        for index,author in enumerate(authors):
            if not isinstance(author,dict) or set(author)!={'head','key','nonce','sequence'}:raise ValueError()
            sequence=_decimal(author['sequence']);nonce=_decimal(author['nonce'],0,10**9);_hash(author['head'])
            if (author['key']!=source['genesis']['producers'][index] or sequence>rank or sequence>blocks
                    or nonce>sequence*rules.MAX_BLOCK_TRANSACTIONS or sequence==0 and author['head']!=source['genesis_hash']):raise ValueError()
            sequence_total+=sequence;nonce_total+=nonce
        if sequence_total!=blocks or nonce_total!=transactions:raise ValueError()
        if epoch==1:
            empty=hashlib.sha256(b'GG-DAG-CLOSED-SEGMENTS-v1\0EMPTY\0').hexdigest()
            if state['closed_root']!=empty or state['last_cut']!=source['genesis_hash'] or blocks!=count or raw_bytes>rules.MAX_HISTORY_RAW_BYTES:raise ValueError()
        if count==0:
            previous='0'*64 if epoch==1 else state['last_cut']
            if epoch==1:
                if (blocks!=0 or transactions!=0 or rank!=0 or raw_bytes!=0 or active['account_root']!=source['genesis']['precheck_root']
                        or active['time_ns']!='0' or any(a['head']!=source['genesis_hash'] for a in authors)):raise ValueError()
            else:_decimal(active['time_ns'],10**9)
            manifest={'blocks':[],'checkpoint':0,'genesis_hash':anchor,'previous':previous,'schema':'gg.dag.execution.manifest.v1',
                      'source_hash':state['source_hash'],'time_ns':active['time_ns']}
            empty_order=hashlib.sha256(b'GG-DAG-FINALIZED-ORDER-v1\0EMPTY\0').hexdigest()
            if (active['previous']!=previous or active['manifest_hash']!=digest(manifest,b'GG-DAG-CHECKPOINT-MANIFEST-v1\0')
                    or active['order_root']!=empty_order):raise ValueError()
        elif checkpoint==0:raise ValueError()
        else:_decimal(active['time_ns'],10**9)
        return state
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_SEGMENTED_STATE_INVALID') from None

def validate_native_pin(trust):
    """Shared headless/browser pin codec; this does not verify a certificate."""
    if not isinstance(trust,dict) or set(trust)!={'genesis','genesis_hash'}:raise ValueError('GG_LIGHT_TRUST_REQUIRED')
    if isinstance(trust['genesis'],dict) and trust['genesis'].get('schema')=='gg.native.genesis.v7':
        from backend.gg_financial_protocol import validate_pin
        return validate_pin(trust)
    try:
        value=deepcopy(trust);genesis=value['genesis']
        if len(pack(value))>256*1024:raise ValueError()
        expected={'accounts','chain_id','decimals','genesis_time_unix','schema','supply_atomic','symbol','validators'}
        version=genesis.get('schema') if isinstance(genesis,dict) else None
        segmented=version=='gg.native.genesis.v4'
        general=version=='gg.native.genesis.v6'
        financial=general or version=='gg.native.genesis.v5'
        member=version=='gg.native.genesis.v3' or (segmented or financial) and 'membership' in genesis
        dag=version in ('gg.native.genesis.v2','gg.native.genesis.v3')
        if dag:expected.add('dag')
        if segmented:expected.add('dag_segmented')
        if financial:expected.add('financial_dag')
        if general:expected.add('financial_accounts')
        if member:expected.add('membership')
        if (not isinstance(genesis,dict) or set(genesis)!=expected
                or version!=('gg.native.genesis.v6' if general else 'gg.native.genesis.v5' if financial else 'gg.native.genesis.v4' if segmented else 'gg.native.genesis.v3' if member else 'gg.native.genesis.v2' if dag else 'gg.native.genesis.v1')
                or not isinstance(genesis['chain_id'],str) or not re.fullmatch(r'ggnet:[0-9a-f]{24}',genesis['chain_id'])
                or type(genesis['decimals']) is not int or genesis['decimals']!=6 or genesis['supply_atomic']!='1000000000000'
                or genesis['symbol']!='GG-NET-TEST' or type(genesis['genesis_time_unix']) is not int or not 0<genesis['genesis_time_unix']<2**53):raise ValueError()
        for name in ('accounts','validators'):
            entries=genesis[name]
            if general and name=='accounts':
                if entries is not None:raise ValueError()
                continue
            if not isinstance(entries,list) or len(entries)!=4 or len(set(entries))!=4 or any(type(entry) is not str or not _HASH.fullmatch(entry) for entry in entries):raise ValueError()
        if set(genesis['accounts'] or [])&set(genesis['validators']):raise ValueError()
        if financial:
            from backend.gg_financial_dag import validate_source as financial_source
            source=financial_source(genesis['financial_dag'],genesis)
        if dag or segmented:
            from backend.gg_dag_checkpoint import validate_source as any_source
            source=any_source(genesis['dag_segmented' if segmented else 'dag'])
            if ((source['schema']==SOURCE_SCHEMA)!=segmented or set(source['genesis']['producers'])&set(genesis['validators'])
                    or genesis['genesis_time_unix']>(MAX_COUNTER-5_000_000_000)//10**9
                    or int(source['started_at_ns'])>genesis['genesis_time_unix']*10**9+5_000_000_000):raise ValueError()
        if member:
            from backend.gg_consensus_membership import validate_membership
            producers=source['producers'] if financial else source['genesis']['producers']
            membership=validate_membership(genesis['membership'],forbidden_keys=producers)
            rows=[invite['body'] for invite in membership['validators']]
            if (genesis['chain_id']!=membership['chain_id'] or genesis['genesis_time_unix']!=membership['genesis_time_unix']
                    or genesis['validators']!=[row['validator_key'] for row in rows] or (not general and genesis['accounts']!=[row['account_key'] for row in rows])
                    or set(producers)&{row['owner_peer_key'] for row in rows}):raise ValueError()
        if value['genesis_hash']!=hashlib.sha256(pack(genesis)).hexdigest():raise ValueError()
        return value
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_LIGHT_TRUST_INVALID') from None

def verify_membership(packet,trust,*,binary=None,stamp=None):
    """Verify the owned pin + SDK signatures + every supplied membership proof.

    binary/stamp are an internal owned-tool seam used by isolated regression;
    no peer/UI field supplies either, or an already-'verified' boolean.
    """
    from backend import gg_consensus as native
    try:
        anchor=validate_native_pin(trust)
        fields=('dag_segmented_account_proof','dag_segmented_block_proof','dag_segmented_order_page')
        if (not isinstance(packet,dict) or packet.get('genesis')!=anchor['genesis'] or packet.get('genesis_hash')!=anchor['genesis_hash']
                or anchor['genesis']['schema']!='gg.native.genesis.v4' or not any(packet.get(name) is not None for name in fields)):raise ValueError()
        source=validate_source(anchor['genesis']['dag_segmented'])
        state=validate_state(packet['state']['dag_segmented'],source,anchor['genesis_hash'])
        if binary is None:binary=native.BINARY;stamp=native._validate_binary()
        verified=native._verify_public(packet,binary,stamp)
        if (verified.get('dag_segmented_commitment')!=state or verified.get('dag_history_replay_verified') is not False
                or verified.get('dag_segmented_membership_scope')!='CERTIFIED_ACTIVE_SEGMENT_MEMBERSHIP_NOT_FULL_HISTORY_REPLAY'):raise ValueError()
        proofs={name:packet.get(name) for name in fields}
        for name in fields:
            if verified.get(name+'_verified') is not (proofs[name] is not None):raise ValueError()
        return {'schema':'gg.dag.segmented-observation.v1','network_id':source['network_id'],'epoch':state['epoch'],
            'global_blocks':state['blocks'],'active_blocks':state['active']['blocks'],'transactions':state['transactions'],
            'authors':deepcopy(state['authors']),'account':deepcopy(proofs[fields[0]]['leaf']) if proofs[fields[0]] is not None else None,
            'block':deepcopy(proofs[fields[1]]['leaf']) if proofs[fields[1]] is not None else None,
            'order_page':deepcopy(proofs[fields[2]]) if proofs[fields[2]] is not None else None,
            'account_membership_verified':proofs[fields[0]] is not None,'block_membership_verified':proofs[fields[1]] is not None,
            'order_page_verified':proofs[fields[2]] is not None,'history_replayed':False,'producer_owned_nonfinancial':True,
            'verification_scope':'SDK_CERTIFICATE_AND_REQUESTED_ACTIVE_SEGMENT_MEMBERSHIP_ONLY'}
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_SEGMENTED_OBSERVATION_INVALID') from None


def verify_closed_membership(packet,trust,*,binary=None,stamp=None):
    """Pinned SDK root -> arbitrary closed cut -> selected order witnesses.

    This authenticates old membership without pretending that the client has
    replayed the original archive or obtained a historical SDK certificate.
    """
    from backend import gg_consensus as native
    try:
        anchor=validate_native_pin(trust)
        fields={'schema','genesis','genesis_hash','state','signed_header','dag_segmented_closed_page'}
        if (not isinstance(packet,dict) or set(packet)!=fields or packet['genesis']!=anchor['genesis']
                or packet['genesis_hash']!=anchor['genesis_hash'] or len(pack(packet))>256*1024):raise ValueError()
        source=validate_source(anchor['genesis']['dag_segmented']);state=validate_state(packet['state']['dag_segmented'],source,anchor['genesis_hash'])
        if binary is None:binary=native.BINARY;stamp=native._validate_binary()
        verified=native._verify_public(packet,binary,stamp)
        if (verified.get('dag_segmented_closed_page_verified') is not True or verified.get('dag_segmented_closed_membership_scope')!=CLOSED_SCOPE
                or verified.get('dag_history_replay_verified') is not False or verified.get('dag_segmented_commitment')!=state):raise ValueError()
        page=packet['dag_segmented_closed_page'];cut=page['cut'];before=validate_state(cut['before'],source,anchor['genesis_hash'])
        if not 1<=int(before['epoch'])<int(state['epoch']):raise ValueError()
        _archive_accounts(cut['accounts'],before,source)
        return {'schema':'gg.dag.closed-observation.v1','epoch':before['epoch'],'before_commitment':before,
            'block':None,'order_page':deepcopy(page),'history_replayed':False,'verification_scope':CLOSED_SCOPE}
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_CLOSED_OBSERVATION_INVALID') from None


def verify_epoch_base(packet,trust,*,binary=None,stamp=None):
    """Actual pinned SDK verification; derive a certified base, not full replay.

    No caller-supplied account snapshot/verified flag is accepted. The native
    verifier checks the cut preimage, closed-tree append and source context.
    This does not import a profile, attach a signer or activate a producer.
    """
    from backend import gg_consensus as native
    try:
        anchor=validate_native_pin(trust)
        if (not isinstance(packet,dict) or packet.get('genesis')!=anchor['genesis'] or packet.get('genesis_hash')!=anchor['genesis_hash']
                or anchor['genesis']['schema']!='gg.native.genesis.v4' or not isinstance(packet.get('dag_segmented_base_proof'),dict)):raise ValueError()
        source=validate_source(anchor['genesis']['dag_segmented']);current=validate_state(packet['state']['dag_segmented'],source,anchor['genesis_hash'])
        if binary is None:binary=native.BINARY;stamp=native._validate_binary()
        verified=native._verify_public(packet,binary,stamp)
        if (verified.get('dag_segmented_base_proof_verified') is not True or verified.get('dag_segmented_base_scope')!=BASE_SCOPE
                or verified.get('dag_history_replay_verified') is not False or verified.get('dag_segmented_commitment')!=current):raise ValueError()
        base=verified.get('dag_segmented_epoch_base')
        if not isinstance(base,dict) or set(base)!={'accounts','commitment'}:raise ValueError()
        state=validate_state(base['commitment'],source,anchor['genesis_hash']);_archive_accounts(base['accounts'],state,source)
        if (state['active']['blocks']!=0 or state['epoch']!=current['epoch'] or state['last_cut']!=current['last_cut']
                or state['closed_root']!=current['closed_root'] or int(state['blocks'])!=int(current['blocks'])-current['active']['blocks']):raise ValueError()
        return {'schema':'gg.dag.verified-epoch-base.v1','base':deepcopy(base),'commitment':current,'network_id':source['network_id'],
            'history_replayed':False,'verification_scope':BASE_SCOPE,'producer_owned_nonfinancial':True}
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_DAG_SEGMENTED_BASE_INVALID') from None


def _archive_accounts(value,state,source):
    from backend.gg_parallel_dag import _tree
    if not isinstance(value,list) or len(value)!=6:raise ValueError()
    authors={row['key']:row for row in state['authors']}
    total=0
    for index,row in enumerate(value):
        if not isinstance(row,dict) or set(row)!={'address','balance_atomic','nonce'} or row['address']!=source['accounts'][index]:raise ValueError()
        total+=_decimal(row['balance_atomic'],0,6*10**9)
        if _integer(row['nonce'],0,10**9)!=int(authors[row['address']]['nonce']):raise ValueError()
    if total!=6*10**9 or _tree(value,b'GG-DAG-ACCOUNT-v1\0')[-1][0]!=state['active']['account_root']:raise ValueError()


def _checked_archive_result(result,anchor,floor):
    source=validate_source(anchor['genesis']['dag_segmented'])
    expected={'schema','verified','history_replayed','verification_scope','archive_sha256','content_sha256','commitment',
        'accounts','segment_base','certificate_height','genesis_hash','network_id','signing_keys_exported','snapshot_trust_used'}
    if (not isinstance(result,dict) or set(result)!=expected or result['schema']!='gg.dag.archive.result.v2'
            or result['verified'] is not True or result['history_replayed'] is not True
            or result['snapshot_trust_used'] is not False or result['signing_keys_exported'] is not False
            or result['verification_scope']!=ARCHIVE_SCOPE or result['genesis_hash']!=anchor['genesis_hash']
            or result['network_id']!=source['network_id']):raise ValueError()
    _hash(result['archive_sha256']);_hash(result['content_sha256'])
    _integer(result['certificate_height'],1,MAX_COUNTER)
    if floor is not None and result['certificate_height']<floor[0]:raise ValueError()
    state=validate_state(result['commitment'],source,anchor['genesis_hash'])
    base=result['segment_base']
    if not isinstance(base,dict) or set(base)!={'commitment','accounts'}:raise ValueError()
    base_state=validate_state(base['commitment'],source,anchor['genesis_hash'])
    if (base_state['epoch']!=state['epoch'] or base_state['last_cut']!=state['last_cut'] or base_state['closed_root']!=state['closed_root']
            or base_state['active']['blocks']!=0 or int(base_state['blocks'])!=int(state['blocks'])-state['active']['blocks']
            or int(base_state['transactions'])>int(state['transactions']) or int(base_state['raw_bytes'])>int(state['raw_bytes'])):raise ValueError()
    _archive_accounts(result['accounts'],state,source);_archive_accounts(base['accounts'],base_state,source)
    return deepcopy(result)


class _VerifiedArchiveReader:
    """The second pass owns its hash/EOF gate; no supplied boolean completes it."""
    def __init__(self,file,path,info,result,check):
        self.file=file;self.path=path;self.info=info;self.result=result;self.check=check
        self.position=0;self.complete=False;self._hash=hashlib.sha256();self._expected=result['archive_sha256']
    def read(self,size):
        self.check()
        if type(size) is not int or not 0<size<=rules.MAX_BLOCK_WIRE_BYTES or self.complete:raise ValueError()
        raw=self.file.read(min(size,self.info.st_size-self.position));self.position+=len(raw);self._hash.update(raw)
        return raw
    def finish(self):
        import os
        self.check()
        if (self.complete or self.position!=self.info.st_size or self._hash.hexdigest()!=self._expected
                or self.file.read(1) or os.fstat(self.file.fileno()).st_size!=self.info.st_size):raise ValueError()
        self.complete=True


from contextlib import contextmanager as _contextmanager

@_contextmanager
def _open_verified_archive(path,trust,*,tools=None,check=None,timeout=1800,floor=None,work_root=None):
    """Owned native replay followed by a mandatory bounded caller-file pass."""
    import os
    from pathlib import Path
    import stat
    import time
    from backend.gg_dag_archive import _native_verify
    from backend.platform_files import is_link
    try:
        anchor=validate_native_pin(trust)
        if anchor['genesis']['schema']!='gg.native.genesis.v4':raise ValueError()
        if check is not None and not callable(check):raise ValueError()
        if type(timeout) not in (int,float) or not 1<=timeout<=14400:raise ValueError()
        external_check=check;deadline=time.monotonic()+timeout
        def check():
            if external_check is not None:external_check()
            if time.monotonic()>=deadline:raise ValueError('GG_DAG_ARCHIVE_TIMEOUT')
        if floor is not None:
            if not isinstance(floor,(tuple,list)) or len(floor)!=2:raise ValueError()
            _integer(floor[0],1,MAX_COUNTER);_hash(floor[1])
        if not isinstance(path,(str,os.PathLike)):raise ValueError()
        candidate=Path(path).expanduser()
        if not candidate.is_absolute():raise ValueError()
        candidate=candidate.parent.resolve(strict=True)/candidate.name
        work=candidate.parent if work_root is None else Path(work_root).expanduser()
        if not work.is_absolute() or is_link(work) or not work.is_dir():raise ValueError()
        work=work.resolve(strict=True)
        info=candidate.lstat()
        if is_link(candidate) or not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_COUNTER:raise ValueError()
        check()
        with candidate.open('rb') as file:
            if not os.path.samestat(info,os.fstat(file.fileno())) or file.read(8)!=b'GGDAGAR2':raise ValueError()
            result=_checked_archive_result(_native_verify(candidate,work,anchor,floor,tools=tools,check=check,
                timeout=max(1,deadline-time.monotonic()),format_version=2),anchor,floor)
            file.seek(0);reader=_VerifiedArchiveReader(file,candidate,info,result,check)
            yield reader
            if not reader.complete:raise ValueError()
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise ValueError('GG_DAG_SEGMENTED_ARCHIVE_INVALID') from None


def verify_archive(path,trust,**options):
    """Actual original replay + caller-file hash/EOF; never imports or signs."""
    with _open_verified_archive(path,trust,**options) as reader:
        while reader.read(256*1024):pass
        reader.finish()
        result=deepcopy(reader.result)
    return result
