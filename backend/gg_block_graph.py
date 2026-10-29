"""Bounded public block observations, separate from consensus verification.

Only known adjacent parent hashes become edges. Header clocks and the local
monotonic observation clock are deliberately different rate measurements.
There is no timer, network client, synthetic block, or consensus implementation.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
import math
import re
import time

LIMIT = 48
# Fast local graphs retain more actual observations so a visual tail can be
# filled with individually identified blocks rather than stretching its edges.
# Slow/compatibility readers retain the smaller default window.
LIVE_HISTORY_LIMIT = 128
FETCH_LIMIT = 8
OBSERVATION_LIMIT = 256
_HASH = re.compile(r'(?:0x)?[0-9a-fA-F]{64}')


def block_hash(value, *, empty=False):
    if empty and value in ('', None):
        return ''
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError('GG_BLOCK_GRAPH_HASH')
    return value.lower().removeprefix('0x')


def evm_block(value):
    def quantity(field):
        raw=value.get(field)
        if not isinstance(raw,str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,64}',raw):
            raise ValueError('GG_BLOCK_GRAPH_HEADER')
        return int(raw,16)
    if not isinstance(value,dict):raise ValueError('GG_BLOCK_GRAPH_HEADER')
    height=quantity('number');transactions=value.get('transactions')
    if not isinstance(transactions,list) or len(transactions)>4096:
        raise ValueError('GG_BLOCK_GRAPH_TRANSACTIONS')
    for identifier in transactions:block_hash(identifier)
    parent=block_hash(value.get('parentHash'))
    return {'hash':block_hash(value.get('hash')),'parent_hash':parent if height else '',
            'height':height,'timestamp':quantity('timestamp'),'transaction_count':len(transactions),
            'state':'OBSERVED','certificate_verified':False,'proposer':''}


def comet_block(value, chain_id):
    if not isinstance(value,dict):raise ValueError('GG_BLOCK_GRAPH_HEADER')
    block=value.get('block');header=block.get('header') if isinstance(block,dict) else None
    if not isinstance(header,dict) or header.get('chain_id')!=chain_id:
        raise ValueError('GG_BLOCK_GRAPH_CHAIN')
    raw=header.get('height')
    if not isinstance(raw,str) or not re.fullmatch(r'[1-9][0-9]{0,17}',raw):
        raise ValueError('GG_BLOCK_GRAPH_HEIGHT')
    height=int(raw)
    try:
        parsed=datetime.fromisoformat(header['time'].replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError()
        timestamp=parsed.timestamp()
    except (KeyError,ValueError,TypeError,AttributeError,OverflowError):
        raise ValueError('GG_BLOCK_GRAPH_TIMESTAMP') from None
    transactions=block.get('data',{}).get('txs') or []
    if not isinstance(transactions,list) or len(transactions)>128:
        raise ValueError('GG_BLOCK_GRAPH_TRANSACTIONS')
    proposer=header.get('proposer_address','')
    if not isinstance(proposer,str) or not re.fullmatch(r'[0-9a-fA-F]{40}',proposer):
        raise ValueError('GG_BLOCK_GRAPH_PROPOSER')
    return {'hash':block_hash(value.get('block_id',{}).get('hash')),
            'parent_hash':block_hash(header.get('last_block_id',{}).get('hash'),empty=height==1),
            'height':height,'timestamp':timestamp,'transaction_count':len(transactions),
            'state':'OBSERVED','certificate_verified':False,'proposer':proposer.lower()}


def _percentile(values,percent):
    if not values:return None
    ordered=sorted(values)
    return round(ordered[min(len(ordered)-1,math.ceil(len(ordered)*percent)-1)],3)


class BlockHistory:
    """A session's bounded contiguous observed suffix, never synthetic history."""
    def __init__(self, engine, first_height=0, clock=time.monotonic, *, history_limit=LIMIT):
        if type(history_limit) is not int or not 2<=history_limit<=LIVE_HISTORY_LIMIT:
            raise ValueError('GG_BLOCK_GRAPH_HISTORY_LIMIT')
        self.engine=engine;self.first_height=first_height;self.clock=clock;self.history_limit=history_limit
        self.reset('')

    def reset(self, session):
        self.session=session;self.rows={};self.tip_height=None;self.tip_hash=''
        self.observations=deque(maxlen=OBSERVATION_LIMIT);self.error='';self.observed_at=None
        self._tx_total=0;self._tx_generation=0;self._tx_observations=deque(maxlen=OBSERVATION_LIMIT)

    def wanted(self, tip_height):
        if type(tip_height) is not int or tip_height<self.first_height:
            raise ValueError('GG_BLOCK_GRAPH_HEIGHT')
        floor=max(self.first_height,tip_height-self.history_limit+1)
        return [height for height in range(tip_height,floor-1,-1)
                if height not in self.rows][:FETCH_LIMIT]

    def ingest(self, blocks, tip_height, tip_hash):
        if not isinstance(blocks,list) or len(blocks)>FETCH_LIMIT:
            raise ValueError('GG_BLOCK_GRAPH_FETCH_LIMIT')
        if type(tip_height) is not int or tip_height<self.first_height:
            raise ValueError('GG_BLOCK_GRAPH_HEIGHT')
        tip_hash=block_hash(tip_hash)
        candidate=dict(self.rows)
        for original in blocks:
            if not isinstance(original,dict):raise ValueError('GG_BLOCK_GRAPH_HEADER')
            row=dict(original);height=row.get('height');timestamp=row.get('timestamp');count=row.get('transaction_count')
            if (type(height) is not int or height<self.first_height or height>tip_height
                    or type(timestamp) not in (float,int) or not math.isfinite(timestamp) or timestamp<0
                    or type(count) is not int or not 0<=count<=4096):
                raise ValueError('GG_BLOCK_GRAPH_HEADER')
            row['hash']=block_hash(row.get('hash'))
            row['parent_hash']=block_hash(row.get('parent_hash'),empty=height==self.first_height)
            if height in candidate and candidate[height]['hash']!=row['hash']:
                raise ValueError('GG_BLOCK_GRAPH_CHECKPOINT_CHANGED')
            if candidate.get(height,{}).get('certificate_verified') is True:row['certificate_verified']=True
            candidate[height]=row
        floor=max(self.first_height,tip_height-self.history_limit+1)
        candidate={h:r for h,r in candidate.items() if floor<=h<=tip_height}
        if tip_height not in candidate or candidate[tip_height]['hash']!=tip_hash:
            raise ValueError('GG_BLOCK_GRAPH_TIP')
        for height,row in candidate.items():
            parent=candidate.get(height-1)
            if parent is not None and row['parent_hash']!=parent['hash']:
                raise ValueError('GG_BLOCK_GRAPH_PARENT_MISMATCH')
        if self.tip_height is not None and tip_height<self.tip_height:
            raise ValueError('GG_BLOCK_GRAPH_CHECKPOINT_REGRESSION')
        previous=self.tip_height
        if previous is not None and tip_height>previous:
            delta=tip_height-previous
            if delta<=self.history_limit and all(h in candidate for h in range(previous+1,tip_height+1)):
                self._tx_total+=sum(candidate[h]['transaction_count'] for h in range(previous+1,tip_height+1))
            else:
                self._tx_generation+=1;self._tx_total=0
        self.rows=candidate;self.tip_height=tip_height;self.tip_hash=tip_hash;self.error=''
        self.observed_at=time.time();now=self.clock()
        if not self.observations or now-self.observations[-1][0]>=.1 or tip_height!=self.observations[-1][1]:
            self.observations.append((now,tip_height))
            self._tx_observations.append((now,self._tx_total,self._tx_generation))
        while len(self.observations)>1 and self.observations[1][0]<now-30:
            self.observations.popleft()
            self._tx_observations.popleft()

    def fail(self):
        self.error='GG_BLOCK_GRAPH_READ_FAILED'

    def snapshot(self, transactions=(), *, ttf_basis='UNKNOWN', stale=False):
        # Never jump across an unknown parent just to make the diagram full.
        descending=[];height=self.tip_height
        while height in self.rows and len(descending)<self.history_limit:
            descending.append(dict(self.rows[height]));height-=1
        blocks=list(reversed(descending));edges=[]
        for parent,child in zip(blocks,blocks[1:]):
            if child['height']==parent['height']+1 and child['parent_hash']==parent['hash']:
                edges.append({'from':parent['hash'],'to':child['hash']})
        metrics={'bps':None,'tps':None,'window_seconds':None,'observed_blocks':None,
                 'observed_transactions':None,'rate_basis':'LOCAL_MONOTONIC_OBSERVATION',
                 'tps_basis':'INCLUDED_BLOCK_TRANSACTIONS',
                 'header_bps':None,'block_interval_ms':None,'header_window_seconds':None,
                 'ttf_ms':None,'ttf_p50_ms':None,'ttf_p95_ms':None,'ttf_samples':0,'ttf_basis':ttf_basis}
        if len(blocks)>1:
            seconds=blocks[-1]['timestamp']-blocks[0]['timestamp']
            if seconds>0:
                metrics.update(header_bps=round((len(blocks)-1)/seconds,6),
                               block_interval_ms=round(seconds*1000/(len(blocks)-1),3),
                               header_window_seconds=round(seconds,6))
        if len(self.observations)>1:
            began,initial=self.observations[0];ended,latest=self.observations[-1];seconds=ended-began
            if seconds>=1 and latest>=initial:
                count=latest-initial
                tx_first=self._tx_observations[0];tx_last=self._tx_observations[-1]
                count_txs=tx_last[1]-tx_first[1] if tx_first[2]==tx_last[2] else None
                metrics.update(bps=round(count/seconds,6),tps=round(count_txs/seconds,6) if count_txs is not None else None,
                               window_seconds=round(seconds,6),observed_blocks=count,observed_transactions=count_txs)
        durations=[row['elapsed_ms'] for row in transactions if isinstance(row,dict)
                   and row.get('state') in ('CONFIRMED','FINALIZED') and type(row.get('elapsed_ms')) in (int,float)
                   and math.isfinite(row['elapsed_ms']) and row['elapsed_ms']>=0]
        if durations:
            metrics.update(ttf_ms=round(durations[0],3),ttf_p50_ms=_percentile(durations,.5),
                           ttf_p95_ms=_percentile(durations,.95),ttf_samples=len(durations))
        floor=max(self.first_height,(self.tip_height or self.first_height)-self.history_limit+1)
        return {'schema':'gg.block-graph.v1','engine':self.engine,'topology':'CHAIN',
                'source':'OWNED_RPC_OBSERVATION','blocks':blocks,'edges':edges,'tip_hash':self.tip_hash,
                'tip_height':self.tip_height,'history_limit':self.history_limit,'display_successors':7,
                'partial_history':bool(blocks and blocks[0]['height']>floor),'metrics':metrics,
                'observed_at':self.observed_at,'stale':bool(stale or self.error),'error':self.error}
