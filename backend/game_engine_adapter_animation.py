"""World animation on the world's existing, bounded native loader lane.

An incoming pose only writes retained Qt buffers on the GUI thread. Page
eviction invalidates its result, and invisible owners never arm another pool.
"""
import math,json,time
from backend.game_engine_adapter_formats import NativeFormats
from backend.game_engine_adapter_models import rows_from
from backend.game_engine_adapter_clocks import AnimationRandom,PlacementClock

class WorldAnimations:
    def __init__(self,stream):
        self.stream=stream;self.future=None;self.refs=[];self.next_ms=0;self.cursor=0;self.frames=0;self.error='';self.notes=set();self.rng=AnimationRandom()
    def attach(self,page):
        for spec in page.metadata.get('props',[]):spec['animation_clock']=PlacementClock(spec['facts'],self.stream.clock_ms,self.rng)
    def finish(self):
        if self.future is None or not self.future.done():return False
        future,self.future=self.future,None
        try:
            metadata,blob=future.result();models=metadata['models']
            if len(models)!=len(self.refs):raise ValueError('World pose result count changed')
            updates=[];events=[]
            for (page,spec,batches),model in zip(self.refs,models):
                if page.closed:continue
                rows=rows_from(model)
                if len(rows)!=len(batches):raise ValueError('World pose batch count changed')
                for batch,row in zip(batches,rows):
                    start=row['offset'];size=row['vertices']*batch.stride
                    if row['vertices']>batch.capacity or start<0 or start+size>len(blob):raise ValueError('Invalid world pose buffer')
                    state={**row,'effect_active':row.get('visible',True)}
                    if 'visible' in state:del state['visible']
                    updates.append((batch,state))
                page.visibility_key=None
                if model.get('events'):events.append((spec['instance'],model['events']))
                for notes in (model.get('limitations',[]),model.get('effects',{}).get('limitations',[]),model.get('ribbons',{}).get('limitations',[])):self.notes.update(notes)
            for batch,row in updates:batch.update(row,blob)
            presentation=getattr(self.stream.parent(),'_game_presentation',None)
            if presentation:
                for owner,rows in events:presentation.world_model_events(owner,rows)
            self.frames+=1;self.error=''
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:self.error=str(exc)[:240]
        finally:self.refs=[]
        return True
    def detach(self,page,preserve=(),*,force=False):
        presentation=getattr(self.stream.parent(),'_game_presentation',None)
        if presentation:
            keep=set(preserve)
            if not force:keep.update(p['instance'] for other in self.stream.pages.values() if other is not page for p in other.metadata.get('props',[]))
            for spec in page.metadata.get('props',[]):
                if spec['instance'] not in keep:presentation.world_model_removed(spec['instance'])
    def schedule(self,clock,view):
        stream=self.stream
        if self.future is not None or stream.pending is not None or stream.horizon.future is not None or stream.weather.future is not None or clock<self.next_ms:return
        if any(key not in stream.pages and time.monotonic()>=stream.errors.get(key,(0,''))[0] for key in stream.desired(stream.position[0],stream.position[2])):return
        candidates=[]
        for page in tuple(stream.pages.values()):
            by_key={}
            for batch in page.batches:
                if batch.row.get('prop_key'):by_key.setdefault(batch.row['prop_key'],[]).append(batch)
            for spec in page.metadata.get('props',[]):
                spec['animation_clock'].tick(clock,self.rng)
                batches=by_key.get(spec['prop_key'],[])
                if spec.get('runtime') and batches and page.surface.enabled(batches[0].row) and any(b.row.get('portal_visible',True) for b in batches):candidates.append((page,spec,batches))
        if not candidates:return
        offset=self.cursor%len(candidates);candidates=candidates[offset:]+candidates[:offset]
        refs=[];items=[];estimate=0;message_bytes=1024+len(json.dumps(view,ensure_ascii=False).encode())
        for page,spec,batches in candidates:
            cost=sum(b.capacity*b.stride+(b.instances.capacity*80 if b.instances is not None else 0) for b in batches)
            if estimate+cost>6*1024*1024:break
            item={'path':spec['source'],'instance':spec['instance'],'world_instance':True,'anchor':spec['anchor'],**spec['animation_clock'].request(clock)}
            size=len(json.dumps(item,ensure_ascii=False,separators=(',',':')).encode())+1
            if message_bytes+size>60000:break
            message_bytes+=size;estimate+=cost;refs.append((page,spec,batches));items.append(item)
            if len(items)>=128:break
        self.cursor+=len(items);self.next_ms=clock+33
        defaults={'view':view,'compact':True}
        if items:self.refs=refs;self.future=stream.pool.submit(self._sample,items,defaults)
    def _sample(self,items,defaults):
        cache=self.stream.cache
        try:return NativeFormats._unpack(cache._reader().request('pose_many',items=items,defaults=defaults,timeout=2))
        except ValueError as exc:
            if 'not loaded' not in str(exc):raise
            for item in items:cache.decode(item['path'],runtime=True,timeout=2,**defaults,**{k:v for k,v in item.items() if k!='path'})
            return NativeFormats._unpack(cache._reader().request('pose_many',items=items,defaults=defaults,timeout=2))
    def advance(self,delta):
        if not isinstance(delta,(float,int)) or not math.isfinite(delta) or not 0<=delta<=10:raise ValueError('Invalid world animation interval')
        stream=self.stream
        if stream.closed or not stream.active:return
        stream.clock_ms+=delta*1000
        changed=self.finish()
        view=stream.view if stream.camera else None
        self.schedule(int(stream.clock_ms),view)
        if changed:stream._visibility(*stream.position)
