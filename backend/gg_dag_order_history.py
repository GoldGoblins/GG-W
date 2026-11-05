"""Append-only SDK-proven order reuse; this module verifies NO quorum.

Callers must SDK-verify the base certificate and every fetched page. Cached
prefixes are reused only when the combined root matches the new certificate.
This cache authorizes fetching, never payload execution/finality/account UI.
"""
from copy import deepcopy
import hashlib
import re

from backend.gg_dag_checkpoint import check_complete_order
from backend.gg_parallel_dag import pack

DOMAIN=b'GG-DAG-FINALIZED-ORDER-v1\0'
KEYS=('hash','index','producer_index','sequence','transactions')
HASH=re.compile(r'[0-9a-f]{64}')
MAX_ORDER=4095


def join(left,right):return hashlib.sha256(DOMAIN+b'N\0'+bytes.fromhex(left)+bytes.fromhex(right)).hexdigest()


def append_peak(peaks,count,leaf):
    value=hashlib.sha256(DOMAIN+b'L\0'+pack(leaf)).hexdigest();level=0
    while count&(1<<level):value=join(peaks.pop(level),value);level+=1
    peaks[level]=value


def peak_root(peaks):
    value=None;height=0
    for level,peak in sorted(peaks.items()):
        if value is None:value=peak;height=level;continue
        while height<level:value=join(value,value);height+=1
        value=join(peak,value);height=level+1
    return value if value is not None else hashlib.sha256(DOMAIN+b'EMPTY\0').hexdigest()


class OrderHistory:
    def __init__(self,source):
        self.source=deepcopy(source);self._leaves=();self._ids=frozenset();self._sequences={};self._transactions=0;self._peaks={}
        self._root=peak_root({})

    def __len__(self):return len(self._leaves)
    def order(self):return [dict(zip(KEYS,leaf)) for leaf in self._leaves]

    def extend(self,state,order):
        """Stage an immutable candidate. Failed validation cannot poison self."""
        if not isinstance(order,list) or not len(self)<=len(order)<=MAX_ORDER:raise ValueError('GG_DAG_CERTIFIED_ORDER_REWRITE')
        if any(not isinstance(leaf,dict) or set(leaf)!=set(KEYS) for leaf in order):raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT')
        if tuple(tuple(leaf[key] for key in KEYS) for leaf in order[:len(self)])!=self._leaves:
            raise ValueError('GG_DAG_CERTIFIED_ORDER_REWRITE')
        result=OrderHistory(self.source);result._peaks=dict(self._peaks);sequences=dict(self._sequences);ids=set(self._ids)
        transactions=self._transactions;fresh=[]
        for index,leaf in enumerate(order[len(self):],len(self)+1):
            producer=leaf['producer_index'];identifier=leaf['hash']
            if (type(leaf['index']) is not int or leaf['index']!=index or not isinstance(identifier,str) or not HASH.fullmatch(identifier)
                    or identifier in ids or type(producer) is not int or producer not in self.source['allowed_producers']
                    or type(leaf['sequence']) is not int or leaf['sequence']!=sequences.get(producer,0)+1
                    or type(leaf['transactions']) is not int or not 0<=leaf['transactions']<=50000):
                raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT')
            append_peak(result._peaks,index-1,leaf);fresh.append(tuple(leaf[key] for key in KEYS))
            ids.add(identifier);sequences[producer]=leaf['sequence'];transactions+=leaf['transactions']
        commitment=state['dag'];root=peak_root(result._peaks)
        if (type(commitment['blocks']) is not int or commitment['blocks']!=len(order) or type(commitment['transactions']) is not int
                or commitment['transactions']!=transactions or commitment['order_root']!=root):
            raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT')
        result._leaves=self._leaves+tuple(fresh);result._ids=frozenset(ids);result._sequences=sequences
        result._transactions=transactions;result._root=root
        return result

    @classmethod
    def restore(cls,source,state,order):
        check_complete_order(state,order,source)
        return cls(source).extend(state,order)

    def fetch(self,state,fetch_page,check):
        """Fetch only the changed final page plus new pages, never old pages.

        Caller runs the SDK verifier BEFORE returning each page to this method.
        A complete root comparison proves the reused prefix belongs to the new
        root, even if the new certificate skipped multiple checkpoints.
        """
        count=state['dag']['blocks']
        if type(count) is not int or not 0<=count<=MAX_ORDER:raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT')
        if count<len(self):raise ValueError('GG_DAG_CERTIFIED_ORDER_REWRITE')
        order=self.order()
        if count==len(self):return self.extend(state,order)
        cursor=(len(self)//32)*32
        while True:
            check();page=fetch_page(cursor)
            if (not isinstance(page,dict) or type(page.get('start')) is not int or page['start']!=cursor
                    or type(page.get('complete')) is not bool or not isinstance(page.get('items'),list)):
                raise ValueError('GG_DAG_ORDER_PAGE_REQUIRED')
            end=min(cursor+32,count)
            if len(page['items'])!=end-cursor or page['complete']!=(end==count):raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT')
            for index,item in enumerate(page['items'],cursor):
                leaf=deepcopy(item['leaf'])
                if index<len(self):
                    if leaf!=order[index]:raise ValueError('GG_DAG_CERTIFIED_ORDER_REWRITE')
                else:order.append(leaf)
            if page['complete']:break
            cursor=end
        check()
        return self.extend(state,order)
