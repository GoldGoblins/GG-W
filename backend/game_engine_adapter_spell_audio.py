"""Completed bound spell stages feed owned original sound kits without log replay."""
from __future__ import annotations
import time


class SpellAudio:
    def __init__(self,*,clock=time.monotonic):
        self.clock=clock;self.zone=None;self.scope=None;self.sequence=None;self.owners={};self.played=0

    def close(self):
        if self.zone:
            for owner in self.owners:self.zone.release_model(owner)
        self.zone=None;self.scope=None;self.sequence=None;self.owners.clear()

    def update(self,zone,snapshot,*,scope,running=True):
        if zone is not self.zone or scope!=self.scope:
            self.close();self.zone=zone;self.scope=scope
        if zone is None:return
        now=self.clock()
        for owner,row in list(self.owners.items()):
            if now>=row['until']:zone.release_model(owner);del self.owners[owner]
        journal=snapshot.get('event_journal',{}).get('events',[])
        if not isinstance(journal,list):return
        rows=sorted((row for row in journal[-256:] if isinstance(row,dict) and type(row.get('sequence')) is int),key=lambda row:row['sequence'])
        latest=max((row['sequence'] for row in rows),default=self.sequence or 0)
        if not running:
            for owner in self.owners:zone.release_model(owner)
            self.owners.clear();self.sequence=latest;return
        if self.sequence is None or latest<self.sequence:self.sequence=latest;return
        fresh=[row for row in rows if row['sequence']>self.sequence][-64:];self.sequence=latest
        for event in fresh:
            if event.get('kind')!='SPELL_VISUAL_STAGE':continue
            payload=event.get('payload') or {}
            if not isinstance(payload,dict):continue
            stage=payload.get('stage');ref=event.get('subject_id')
            if stage=='STOP':
                for owner,row in list(self.owners.items()):
                    if row['ref']==ref and row['stage'] in ('precast','channel'):
                        zone.release_model(owner);del self.owners[owner]
                continue
            kit=payload.get('sound_id')
            if type(kit) is not int or not 0<kit<=0xffffffff or stage not in ('precast','cast','impact','channel'):continue
            if len(self.owners)>=64:
                owner=next(iter(self.owners));zone.release_model(owner);del self.owners[owner]
            owner='entity:spell:'+str(event['sequence'])
            if zone.spell_sound(owner,kit,payload.get('position')):
                self.owners[owner]=dict(ref=ref,stage=stage,until=now+(32. if stage in ('precast','channel') else 5.));self.played+=1
