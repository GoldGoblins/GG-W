"""Bounded store/carry/forward experiment, not a radio driver or BPv7 stack.

Admission happens before JSON/signature work. Sender work does not remove a
receiver's bandwidth, storage or verification cost. Both scopes have budgets.
"""
from collections import OrderedDict
import hashlib
import struct
import time
import zlib

HEADER=struct.Struct('!3s32sHHIII')
MAX_MESSAGE=8192
MAX_PARTS=128


def fragment(data,mtu=128,expires=None,now=None):
    now=time.time() if now is None else now
    expires=int(now+300) if expires is None else expires
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_MESSAGE: raise ValueError('OMNI_MESSAGE_SIZE')
    if type(mtu) is not int or not 64<=mtu<=512: raise ValueError('OMNI_MTU')
    if type(expires) is not int or not now<expires<=now+3600: raise ValueError('OMNI_EXPIRY')
    width=mtu-HEADER.size; count=(len(data)+width-1)//width
    if count>MAX_PARTS: raise ValueError('OMNI_FRAGMENT_LIMIT')
    digest=hashlib.sha256(data).digest()
    return [HEADER.pack(b'GG1',digest,i,count,len(data),expires,zlib.crc32(data[i*width:(i+1)*width]))+data[i*width:(i+1)*width] for i in range(count)]


class Receiver:
    def __init__(self,bytes_per_minute=8192,storage_bytes=65536,max_messages=16,clock=time.time):
        if not 512<=bytes_per_minute<=1048576 or not 8192<=storage_bytes<=1048576 or not 1<=max_messages<=64: raise ValueError('OMNI_BUDGET')
        self.rate=bytes_per_minute; self.storage=storage_bytes; self.max_messages=max_messages; self.clock=clock
        self.tokens=float(self.rate); self.last=clock(); self.peers=OrderedDict(); self.messages={}; self.seen=OrderedDict()
        self.stats={'received_bytes':0,'accepted_bytes':0,'rejected':0,'duplicates':0,'delivered':0,'expired':0,'signature_checks':0}

    @property
    def used(self): return sum(sum(len(p) for p in m['parts'].values()) for m in self.messages.values())

    def prune(self):
        now=self.clock()
        for peer in list(self.peers):
            if now-self.peers[peer][1]>120:del self.peers[peer]
        for key in list(self.messages):
            if self.messages[key]['expires']<=now: del self.messages[key]; self.stats['expired']+=1
        for key in list(self.seen):
            if self.seen[key]<=now: del self.seen[key]

    def _admit(self,peer,size):
        now=self.clock(); elapsed=max(0,now-self.last); self.last=now
        self.tokens=min(self.rate,self.tokens+elapsed*self.rate/60)
        if peer not in self.peers:
            if len(self.peers)>=32: return False
            self.peers[peer]=[float(self.rate/2),now]
        allowance,last=self.peers[peer]; allowance=min(self.rate/2,allowance+max(0,now-last)*self.rate/120)
        # Do not spend global tokens for a peer that has already hit its limit.
        if size>allowance or size>self.tokens: return False
        self.peers[peer]=[allowance-size,now]; self.tokens-=size
        return True

    def receive(self,peer,packet):
        self.prune()
        if isinstance(packet,bytes):self.stats['received_bytes']+=len(packet)
        if not isinstance(peer,str) or not 1<=len(peer)<=64 or not isinstance(packet,bytes) or not HEADER.size<len(packet)<=512:
            return self._reject('MALFORMED')
        if not self._admit(peer,len(packet)): return self._reject('BACKPRESSURE')
        magic,digest,index,count,total,expires,crc=HEADER.unpack(packet[:HEADER.size]); payload=packet[HEADER.size:]
        if magic!=b'GG1' or not 1<=count<=MAX_PARTS or index>=count or not 1<=total<=MAX_MESSAGE or count>total or not self.clock()<expires<=self.clock()+3600:
            return self._reject('INVALID_HEADER')
        if zlib.crc32(payload)!=crc: return self._reject('BAD_CHECKSUM')
        key=digest.hex()
        if key in self.seen: self.stats['duplicates']+=1; return {'state':'DUPLICATE','id':key}
        message=self.messages.get(key)
        if message and (message['count'],message['total'],message['expires'])!=(count,total,expires): return self._reject('CONFLICT')
        if not message:
            if len(self.messages)>=self.max_messages: return self._reject('QUEUE_FULL')
            message={'count':count,'total':total,'expires':expires,'parts':{}}
        old=message['parts'].get(index)
        if old is not None:
            if old!=payload: return self._reject('CONFLICT')
            self.stats['duplicates']+=1; return {'state':'DUPLICATE','id':key}
        if self.used+len(payload)>self.storage or sum(map(len,message['parts'].values()))+len(payload)>total: return self._reject('STORAGE_FULL')
        self.messages[key]=message; message['parts'][index]=payload; self.stats['accepted_bytes']+=len(packet)
        if len(message['parts'])<count: return {'state':'PARTIAL','id':key,'received':len(message['parts']),'total':count}
        data=b''.join(message['parts'][i] for i in range(count)); del self.messages[key]
        if len(data)!=total or hashlib.sha256(data).digest()!=digest: return self._reject('BAD_HASH')
        self.seen[key]=expires
        while len(self.seen)>128: self.seen.popitem(last=False)
        self.stats['delivered']+=1
        return {'state':'DELIVERED','id':key,'data':data}

    def _reject(self,state):
        self.stats['rejected']+=1
        return {'state':state}

    def snapshot(self):
        self.prune()
        return dict(self.stats,queued=len(self.messages),storage_used=self.used,storage_limit=self.storage,
                    bytes_per_minute=self.rate,peers=len(self.peers),global_credit=int(self.tokens))
