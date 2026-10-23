"""Placed-model ambient pool adapted from GgEngine's sound/emitter_pool.rs.

One looping channel per kit; 32 kits, 256 owners per kit, four audible kits
in claim order. IO results carry an entry generation and cannot revive a
removed owner. Missing kits remain silent, as in the original adapter.
"""
from collections import OrderedDict
import math

def point(value):
    return isinstance(value,(list,tuple)) and len(value)==3 and all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=2_000_000 for x in value)
def distance(a,b):return sum((x-y)**2 for x,y in zip(a,b))

class AmbientEmitters:
    def __init__(self,short):
        self.short=short;self.entries=[None]*32;self.handles={};self.serial=0;self.listener=(0.,0.,0.);self.errors=[];self.starts=0
    def _error(self,text):
        if text not in self.errors:self.errors=(self.errors+[text])[-16:]
    def register(self,owner,kit,position,*,keep_first=False):
        if not isinstance(owner,str) or not owner or len(owner)>128 or type(kit) is not int or not 0<kit<=0xffffffff or not point(position):return False
        slot=self.handles.get(owner)
        if slot is not None:
            entry=self.entries[slot]
            if keep_first or entry['kit']==kit:entry['records'][owner]=tuple(position);return True
            self.release(owner)
        slot=next((i for i,e in enumerate(self.entries) if e and e['kit']==kit),None)
        if slot is None:slot=next((i for i,e in enumerate(self.entries) if e is None),None)
        if slot is None:self._error('Ambient kit capacity exceeded');return False
        entry=self.entries[slot]
        if entry is None:
            self.serial+=1;entry={'kit':kit,'serial':self.serial,'key':('ambient',self.serial),'records':OrderedDict(),'prepared':None,'failed':False,'attempts':0,'requested':False}
            self.entries[slot]=entry
        records=entry['records']
        if len(records)>=256:
            d=distance(self.listener,position);victim=next((o for o,p in records.items() if distance(self.listener,p)>d),None)
            if victim is None:self._error('Ambient owner capacity exceeded');return False
            del records[victim];self.handles.pop(victim,None)
        records[owner]=tuple(position);self.handles[owner]=slot;return True
    def release(self,owner):
        slot=self.handles.pop(owner,None)
        if slot is None:return
        entry=self.entries[slot];entry['records'].pop(owner,None)
        if not entry['records']:
            self.short.stop(entry['key'],3000);self.entries[slot]=None
    def _nearest(self,entry):return min(entry['records'].values(),key=lambda p:distance(p,self.listener))
    def preparation(self):
        entry=next((e for e in self.entries if e and not e['failed'] and e['prepared'] is None),None)
        return (entry['serial'],entry['kit'],self._nearest(entry)) if entry else None
    def resolve(self,serial,value=None,error=None):
        entry=next((e for e in self.entries if e and e['serial']==serial),None)
        if entry is None:return False
        if error:entry['failed']=True;self._error(str(error)[:200])
        else:entry['prepared']=value
        return True
    def update(self,listener):
        if not point(listener):return
        self.listener=tuple(listener);sounding=0
        for entry in self.entries:
            if not entry or entry['failed'] or entry['prepared'] is None:continue
            path,options,cutoff=entry['prepared'];position=self._nearest(entry)
            audible=cutoff<=0 or distance(position,self.listener)<=cutoff**2
            if not audible or sounding>=4:
                self.short.stop(entry['key'],3000 if audible else 0);entry['requested']=False;entry['attempts']=0;continue
            try:
                if not self.short.has(entry['key']):
                    if entry['attempts']>=2:raise ValueError('Ambient audio decode or voice allocation failed')
                    self.short.play(path,**{**options,'loop':True,'bus':0,'unique':entry['key'],'position':position})
                    entry['requested']=True;entry['attempts']+=1;self.starts+=1
                self.short.move(entry['key'],position)
                if self.short.has(entry['key']):sounding+=1
            except (OSError,ValueError,RuntimeError) as exc:
                entry['failed']=True;self.short.stop(entry['key']);self._error(str(exc)[:200])
    def pinned(self):return {e['prepared'][0] for e in self.entries if e and e['prepared'] is not None}
    def clear(self):
        for entry in self.entries:
            if entry:self.short.stop(entry['key'])
        self.entries=[None]*32;self.handles.clear()
    def diagnostics(self):
        return {'kits':sum(e is not None for e in self.entries),'owners':len(self.handles),'starts':self.starts,'errors':list(self.errors)}
