"""Action slots and TAB history adapted from samwhosung/engine (MIT).

Copyright (c) 2026 Sam. See backend/licenses/engine-MIT.txt.
Reference: engine-ui-core/src/script/{action,cursor/bar}.rs and
engine-app/src/target/scan.rs. Slot content and live state are separate;
item shortcuts refer to item definitions and never move bag instances.
"""
from __future__ import annotations
import copy,math
SCHEMA='gg.game-engine.actions.v1'
SLOTS_PER_PAGE=12
PAGES=10
KEYS=('1','2','3','4','5','6','7','8','9','0','-','=')
COMMANDS={'ATTACK':'Attack','INTERACT':'Interact','TOGGLE_FLIGHT':'Flight',
          'TOGGLE_HOVERBOARD':'Hoverboard','MOUNT_BOAT':'Skiff'}

def click_gesture(elapsed_ms,yaw_delta,pitch_delta):
    return 0<=elapsed_ms<200 or (elapsed_ms<800 and abs(yaw_delta)<2.25 and abs(pitch_delta)<2.)

class ActionBars:
    def __init__(self):
        self.page=0;self.locked=False;self.revision=0;self.auto_attack=False
        self.slots=[{} for _ in range(SLOTS_PER_PAGE*PAGES)]
        defaults=[('COMMAND','ATTACK'),('ABILITY','ability.surge'),('ABILITY','ability.undertow'),
                  ('ABILITY','ability.sky_leap'),('COMMAND','INTERACT'),('COMMAND','TOGGLE_FLIGHT'),
                  ('COMMAND','TOGGLE_HOVERBOARD'),('COMMAND','MOUNT_BOAT')]
        defaults += [('ITEM','item.nature.tool_'+t) for t in ('rod','net','shears','bucket','brush','knife')]
        for i,(kind,ref) in enumerate(defaults):self.slots[i]={'kind':kind,'ref':ref}
        self.history=[];self.history_at=0.

    def assign(self,index,kind,ref,abilities,items):
        if self.locked:return {'error':'ACTION_BAR_LOCKED'}
        if not isinstance(index,int) or not 0<=index<len(self.slots):return {'error':'ACTION_SLOT_INVALID'}
        kind=str(kind).upper();ref=str(ref)
        if kind not in {'EMPTY','COMMAND','ABILITY','ITEM','MACRO'}:return {'error':'ACTION_KIND_INVALID'}
        if (kind=='COMMAND' and ref not in COMMANDS or kind=='ABILITY' and ref not in abilities
                or kind=='ITEM' and ref not in items
                or kind=='MACRO' and (not ref.isascii() or not ref.isdecimal() or not 1<=int(ref)<=36)):
            return {'error':'ACTION_REFERENCE_INVALID'}
        self.slots[index]={} if kind=='EMPTY' else {'kind':kind,'ref':ref}
        self.revision+=1;return {'ok':True}

    def move(self,source,destination):
        if self.locked:return {'error':'ACTION_BAR_LOCKED'}
        if not all(isinstance(i,int) and 0<=i<len(self.slots) for i in (source,destination)):return {'error':'ACTION_SLOT_INVALID'}
        # Atomic swap is the UI equivalent of GgEngine's displaced cursor action.
        self.slots[source],self.slots[destination]=self.slots[destination],self.slots[source]
        self.revision+=1;return {'ok':True}

    def cycle(self,rows,current,now,reverse=False):
        # GgEngine: on-screen tier, distance + off-centre priority, attacker bonus,
        # history for four seconds, reverse restores the previous candidate.
        rows=[r for r in rows if r.get('attackable',True) and not r.get('dead') and not r.get('no_tab')]
        if not rows:return ''
        if any(r.get('on_screen') for r in rows):rows=[r for r in rows if r.get('on_screen')]
        rows.sort(key=lambda r:(float(r.get('off_center',0))+float(r.get('distance_m',0))/64
                               -(3 if r.get('combat_with_me') else 0),r['id']))
        ids=[r['id'] for r in rows]
        if now-self.history_at>4:self.history=[]
        if reverse:
            wanted=next((i for i in reversed(self.history) if i!=current and i in ids),None)
            if wanted:
                self.history=self.history[:self.history.index(wanted)];self.history_at=now
                return wanted
        if current and (not self.history or self.history[-1]!=current):self.history.append(current)
        wanted=next((i for i in ids if i!=current and i not in self.history),None)
        if wanted is None:
            self.history=[];wanted=next((i for i in ids if i!=current),ids[0])
        self.history_at=now;self.history=self.history[-128:]
        return wanted

    def save(self):return {'slots':copy.deepcopy(self.slots),'page':self.page,'locked':self.locked}

    def restore(self,payload,abilities,items):
        if not isinstance(payload,dict):return
        self.locked=False
        if isinstance(payload.get('slots'),list):
            for i,row in enumerate(payload['slots'][:len(self.slots)]):
                if isinstance(row,dict):self.assign(i,row.get('kind','EMPTY'),row.get('ref',''),abilities,items)
        page=payload.get('page',0)
        self.page=max(0,min(PAGES-1,page)) if type(page) is int else 0;self.locked=bool(payload.get('locked',False))
        self.auto_attack=False;self.history=[];self.revision+=1
