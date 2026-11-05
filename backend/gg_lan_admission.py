"""Constant-size replenishing credits, isolated by authenticated ingress lane.

Counters are diagnostics; credit denial never exhausts another lane. No I/O or
waiting occurs under this lock. Memory/handler/data-storage ceilings stay separate.
"""
import math
import threading
import time


class RefillBudget:
    def __init__(self,byte_burst,work_burst,*,maximum_actors,period=1.0,clock=None):
        if (type(byte_burst) is not int or byte_burst<1 or type(work_burst) is not int or work_burst<1
                or type(maximum_actors) is not int or not 1<=maximum_actors<=128
                or not isinstance(period,(int,float)) or not math.isfinite(period) or period<=0):
            raise ValueError('GG_INGRESS_BUDGET')
        self.byte_burst=byte_burst;self.work_burst=work_burst;self.maximum_actors=maximum_actors
        self.period=float(period);self.clock=clock or time.monotonic;self.lock=threading.Lock()
        self.actors={};self.accepted=0;self.denied=0

    def set_limits(self,byte_burst,work_burst):
        if type(byte_burst) is not int or byte_burst<1 or type(work_burst) is not int or work_burst<1:raise ValueError('GG_INGRESS_BUDGET')
        with self.lock:
            # Reconfiguration does not refill a depleted peer by replaying the
            # same configuration, or erase usage when the burst is reduced.
            now=self.clock()
            for state in self.actors.values():
                elapsed=max(0,now-state[2]);state[2]=max(now,state[2])
                state[0]=min(byte_burst,self.byte_burst,state[0]+elapsed*self.byte_burst/self.period)
                state[1]=min(work_burst,self.work_burst,state[1]+elapsed*self.work_burst/self.period)
            self.byte_burst=byte_burst;self.work_burst=work_burst

    def take(self,actor,size=0,work=1):
        if type(size) is not int or size<0 or type(work) is not int or work<0:raise ValueError('GG_INGRESS_CHARGE')
        with self.lock:
            now=self.clock()
            if not isinstance(now,(int,float)) or not math.isfinite(now):raise ValueError('GG_INGRESS_CLOCK')
            state=self.actors.get(actor)
            if state is None:
                if len(self.actors)>=self.maximum_actors:
                    stale=next((key for key,value in self.actors.items() if now-value[2]>=self.period),None)
                    if stale is None:self.denied+=1;return False
                    self.actors.pop(stale)
                state=[float(self.byte_burst),float(self.work_burst),now];self.actors[actor]=state
            elapsed=max(0,now-state[2]);state[2]=max(now,state[2])
            state[0]=min(self.byte_burst,state[0]+elapsed*self.byte_burst/self.period)
            state[1]=min(self.work_burst,state[1]+elapsed*self.work_burst/self.period)
            allowed=size<=state[0] and work<=state[1]
            state[0]=max(0,state[0]-size);state[1]=max(0,state[1]-work)
            if allowed:self.accepted+=1
            else:self.denied+=1
            return allowed

    def fresh(self):
        return RefillBudget(self.byte_burst,self.work_burst,maximum_actors=self.maximum_actors,period=self.period,clock=self.clock)

    def snapshot(self):
        with self.lock:return {'mode':'REFILLING_PER_INGRESS','period_seconds':self.period,'byte_burst':self.byte_burst,
            'work_burst':self.work_burst,'actors':len(self.actors),'maximum_actors':self.maximum_actors,'accepted':self.accepted,'denied':self.denied}
