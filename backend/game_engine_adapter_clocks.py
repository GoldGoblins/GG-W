"""The original doodad watchdog and its shared MSVC animation random stream.

GgEngine re-arms every placement, including parked ones, with a weighted
variation and replay window. Global tracks keep their separate attach epoch.
Adapted from engine-formats/anim_rng.rs and engine-world/doodad_anim/mod.rs.
"""
import time

class AnimationRandom:
    def __init__(self,seed=None):self.state=(int(time.time()*1000) if seed is None else seed)&0xffffffff
    def draw(self):
        self.state=(self.state*214013+2531011)&0xffffffff
        return (self.state>>16)&32767
    def replays(self,lo,hi):return max(1,lo+((self.draw()*max(0,hi-lo))>>15))

class PlacementClock:
    def __init__(self,facts,now,rng):
        self.attached=now;self.armed=now;self.window=now;self.sequence=None;self.chain=[]
        clips=facts.get('sequences',[])
        idle=next((c for c in clips if c['sequence_index']==facts.get('idle_sequence')),None)
        if idle:self.chain=[c for c in clips if c['anim_id']==idle['anim_id']]
        self.tick(now,rng)
    def tick(self,now,rng):
        if not self.chain or now<self.window:return
        roll=rng.draw();clip=self.chain[0]
        for candidate in self.chain:
            if roll<candidate['frequency']:clip=candidate;break
            roll-=candidate['frequency']
        replay=rng.replays(clip['min_replay'],clip['max_replay'])
        self.sequence=clip;self.armed=now;self.window=now+max(.001,clip['duration_ms']*replay)
    def request(self,now):
        out={'clock_ms':max(0,int(now-self.attached)),'cursor_ms':max(0,int(now-self.armed)),'repeat':True}
        if self.sequence:out.update(anim_id=self.sequence['anim_id'],sequence_index=self.sequence['sequence_index'])
        return out
