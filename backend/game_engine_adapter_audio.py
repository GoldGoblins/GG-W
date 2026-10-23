"""Area/phase audio transport using the original native DBC and MPQ readers.

One IO lane prepares catalogs/files. The Qt lane alone owns mixer streams.
The selector and clocks follow GgEngine's sound/zone.rs and sound/weather.rs.
"""
from __future__ import annotations
from collections import OrderedDict,deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from random import Random
import math,time
from backend.game_engine_adapter_formats import AssetCache

def phase(minute):return 0 if 330<=minute%1440<1260 else 1

class AudioAssets:
    """Worker-owned extraction cache; active and opening files stay pinned."""
    def __init__(self,directory):
        self.directory=directory;self.cache=AssetCache();self.rng=Random();self.picks=OrderedDict();self.kits=OrderedDict();self.areas=OrderedDict();self.entity_rows=OrderedDict();self.lru=OrderedDict();self.beds=None
    def _reader(self):
        if not self.cache.archive_source:self.cache.mount_chain(self.directory)
        return self.cache._reader()
    def _request(self,op,**args):
        # This bounded IO lane runs away from Qt. Archive/table preparation
        # uses the decoder's one-second budget rather than the UI's 300 ms
        # response budget, including during hardware shader compilation.
        return self._reader().request(op,timeout=1,**args)
    def catalog(self,key):
        notes=[]
        if self.beds is None:
            try:self.beds=self._request('sound_beds')
            except (ValueError,RuntimeError,TimeoutError) as exc:notes.append(str(exc))
        if key not in self.areas:
            area,interior=key
            try:self.areas[key]=self._request('area_audio',area_id=area,interior=dict(interior) if interior else None)
            except (ValueError,RuntimeError,TimeoutError) as exc:
                return {'area_id':area,'found':False,'unavailable':True,'notes':notes+[str(exc)]},self.beds or {'ghost':0,'underwater':0}
            while len(self.areas)>64:self.areas.popitem(last=False)
        self.areas.move_to_end(key)
        return {**self.areas[key],'notes':notes},self.beds or {'ghost':0,'underwater':0}
    def _resolve(self,name,pins):
        # A returned loose file belongs to the author and is never evicted.
        from backend.game_engine_adapter_assets import asset_path
        loose=asset_path(name)
        if loose.is_file():return loose
        while self.cache.archive_bytes>56*1024*1024 or len(self.cache.archive_entries)>=120:
            victim=next((p for p in self.lru if p not in pins),None)
            if victim is None:raise ValueError('Audio cache is full of active files')
            self.lru.pop(victim,None)
            keys=[k for k,p in self.cache.archive_entries.items() if p==victim]
            size=victim.stat().st_size if victim.is_file() else 0
            if victim.is_file():victim.unlink()
            for k in keys:self.cache.archive_entries.pop(k,None)
            self.cache.archive_bytes=max(0,self.cache.archive_bytes-size)
        self._reader();path=self.cache.resolve(name)
        if not path.is_file():raise ValueError('Audio file missing')
        self.lru[path]=None;self.lru.move_to_end(path)
        return path
    def _pick(self,kit):
        if kit not in self.kits:
            self.kits[kit]=self._request('sound_kit',kit=kit)
            while len(self.kits)>128:self.kits.popitem(last=False)
        self.kits.move_to_end(kit);row=self.kits[kit];files=row['files']
        if not files:raise ValueError('Sound kit has no files')
        canonical=row['id'];weights=[max(0,int(w)) for _,w in files];remaining=self.picks.get(canonical)
        if remaining is None or len(remaining)!=len(weights) or not sum(remaining):remaining=weights.copy();self.picks[canonical]=remaining
        self.picks.move_to_end(canonical)
        while len(self.picks)>128:self.picks.popitem(last=False)
        total=sum(remaining);index=0
        if total:
            draw=self.rng.getrandbits(32)%total
            for i,weight in enumerate(remaining):
                if draw<weight:index=i;remaining[i]-=1;break
                draw-=weight
        gain=float(row['volume'])
        if not math.isfinite(gain):raise ValueError('Non-finite sound kit volume')
        # Streaming beds use the base kit gain, as original pick_stream does.
        return row,files[index][0],max(0.,min(1.,gain))
    def prepare(self,kit,pins):
        row,name,gain=self._pick(kit)
        return self._stream_source(name,pins),gain,name
    def effect(self,sound,pins):
        if sound.get('file'):
            return self._resolve(sound['file'],pins),{'gain':1.}
        row,name,gain=self._pick(sound['kit']);flags=row['flags']
        if flags&0x800:gain=max(0.,min(1.,gain+(((self.rng.getrandbits(32)*31)>>32)-15)*.01))
        frequency=(22050*(((self.rng.getrandbits(32)*31)>>32)+85))//100 if flags&0x400 else None
        options={'gain':gain,'frequency':frequency,'loop':bool(flags&0x200),'unique':row['id'] if flags&0x20 else None,
                 'bus':1 if row['sound_type']==28 else 2 if row['sound_type']==50 else 0}
        if sound.get('position') is not None:
            near=float(row['near']);far=float(row['far'])
            if not math.isfinite(near) or not math.isfinite(far) or near<0 or far<0 or near>=1_000_000 or far>1_000_000:raise ValueError('Invalid sound kit distance')
            options.update(position=sound['position'],near=max(.01,near),far=max(max(.01,near)+.01,far) if far else 1_000_000.,reverb=bool(row['eax']))
        return self._resolve(name,pins),options
    def emitter(self,kit,position,pins):
        path,options=self.effect({'kit':kit,'position':position},pins)
        row=self.kits[kit];cutoff=float(row['far'])
        if not math.isfinite(cutoff) or cutoff<0:raise ValueError('Invalid ambient cutoff')
        # A zero cutoff never culls in the original. The native mixer still
        # needs a finite far plane for attenuation.
        if not cutoff:options['far']=1_000_000.
        return path,options,cutoff
    def _stream_source(self,name,pins):
        from backend.game_engine_adapter_assets import asset_path
        from backend.game_engine_audio_archive import ArchiveAudioSource
        loose=asset_path(name)
        if loose.is_file():return loose
        size=self._request('archive_audio_probe',entry=name)['size']
        return ArchiveAudioSource(Path(self.directory),name,size) if size>8*1024*1024 else self._resolve(name,pins)
    def prepare_file(self,name,pins):return self._stream_source(name,pins),1.,name
    def provider(self,ident):return self._request('audio_provider',id=ident)
    def entity_catalog(self,op,**args):
        key=(op,tuple(sorted(args.items())))
        if key not in self.entity_rows:
            self.entity_rows[key]=self._request(op,**args)
            while len(self.entity_rows)>128:self.entity_rows.popitem(last=False)
        self.entity_rows.move_to_end(key)
        return self.entity_rows[key]
    def entity_effect(self,sound,pins):
        """Resolve committed entity events on the same bounded IO lane as beds."""
        event=sound['entity_event'];c=sound['context'];position=c['position'];specs=[]
        if c['kind']=='gameobject':
            slots=self.entity_catalog('gameobject_audio',display_id=c['display_id'])['slots']
            slot=int(event[3]) if event.startswith('$GO') else 6+int(event[3]) if event.startswith('$GC') else {'open':1,'close':3,'destroy':4,'opened':5,'body_loop':2,'stand':0}[event]
            specs.append((slots[slot],'object',position,event=='body_loop'))
        elif event in ('swing','impact'):
            args={'kind':event,'critical':c.get('critical',False)}
            args.update({'swing_type':c['swing_type']} if event=='swing' else {k:c[k] for k in ('weapon_subclass','metal','target_slot')})
            specs.append((self.entity_catalog('combat_audio',**args)['kit'],event,position,False))
        else:
            identity={'model_id':c['model_id']} if event=='pet_dismiss' and c.get('model_id') else {'display_id':c['display_id']}
            voice=self.entity_catalog('creature_voice',**identity)
            if event in ('$FSD','footstep'):
                if c.get('hover') or c.get('stealth') or c.get('ghost'):return []
                if c.get('material_id') is not None:
                    foley=self.entity_catalog('material_audio',material_id=c['material_id'])['foley']
                    specs.append((foley,'foley',(position[0],position[1]+2.,position[2]),False))
                depth=c.get('water_depth',0.)
                if not c.get('swimming') and depth<=.75*c.get('collision_height',2.):
                    surface={k:c[k] for k in ('terrain_id','ground_effect_id') if c.get(k) is not None}
                    row=self.entity_catalog('footstep_audio',footstep_class=voice.get('footstep_class',0),**surface)
                    kit=row['splash'] or row['dry'] if depth>0 else row['dry']
                    specs.append((kit,'footstep',position,False))
            else:
                if not voice.get('found'):return []
                fields={'$FDX':'stand','$WNG':'wing_flap','$WGG':'wing_glide'}
                if event.startswith('$FD') and event[-1] in '1234':kit=voice['fidget'][int(event[-1])-1]
                elif event.startswith('$AH') and event[-1] in '0123':kit=voice['custom_attack'][int(event[-1])]
                elif event=='exertion':kit=voice['exertion'][int(c.get('critical',False))]
                elif event=='injury':kit=voice['injury'][2 if c.get('crushing') else int(c.get('critical',False))]
                else:kit=voice[fields.get(event,'loop_sound' if event=='body_loop' else event)]
                specs.append((kit,'body' if event=='body_loop' else 'vocal',position,event=='body_loop'))
        prepared=[]
        for kit,channel,at,force_loop in specs[:3]:
            if not kit:continue
            # Looping GO/creature channels share the existing kit emitter pool.
            # Never leave an unowned loop in the short-file mixer.
            row=self.entity_catalog('sound_kit',kit=kit)
            if force_loop or row['flags']&0x200:
                prepared.append({'loop_kit':kit,'channel':channel,'position':at})
            else:
                path,options=self.effect({'kit':kit,'position':at},pins)
                prepared.append({'path':path,'options':options,'channel':channel})
        return prepared
    def close(self):self.cache.close();self.lru.clear();self.kits.clear();self.picks.clear();self.areas.clear();self.entity_rows.clear()

class ZoneAudio:
    def __init__(self,streams,directory,*,clock=time.monotonic,short_sounds=None):
        self.streams=streams;self.clock=clock;self.assets=AudioAssets(directory);self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='gg-zone-audio')
        self.future=None;self.job=None;self.closed=False;self.key=None;self.catalog=None;self.beds={'ghost':0,'underwater':0};self.errors=[];self._warned=OrderedDict();self.retry_at=0.
        self.context={};self.zone_music=0;self.music_kit=0;self.next_track_at=None;self.intro_last=OrderedDict();self.intro=None;self.ambience_kit=0;self.ambience_played=0;self.ambience_fade=5000;self.was_underwater=False;self.music_live=False;self.lua_path=None;self.lua_request=None;self.lua_serial=0;self.suppressed=False;self.rng=Random();self.opens=0
        self.provider=None;self.provider_applied=None;self.server_kit=None
        self.short_sounds=short_sounds;self.sound_queue=deque();self.sound_generation=0;self.model_serial=0;self.model_owners={};self.entity_voices={};self.entity_loops={};self.stand_at=-float('inf');self.entity_events=0
        self.music_attempts=0;self.effect_attempts=0
        from backend.game_engine_adapter_emitters import AmbientEmitters
        self.emitters=AmbientEmitters(short_sounds) if short_sounds else None;self.listener=(0.,0.,0.)
    def _error(self,exc):
        text=str(exc)[:240]
        if text not in self._warned:
            self._warned[text]=None;self.errors=(self.errors+[text])[-16:]
            while len(self._warned)>128:self._warned.popitem(last=False)
    def _submit(self,job,method,*args):self.job=job;self.future=self.pool.submit(method,*args)
    def _phase_kit(self,kind):
        row=(self.catalog or {}).get(kind)
        return int(row['kits'][self.context.get('phase',0)]) if row else 0
    def _desired_ambience(self):
        c=self.context
        if c.get('ghost'):return self.beds['ghost']
        if c.get('underwater'):return self.beds['underwater']
        if c.get('weather') and not c.get('indoors'):return c['weather']
        return self._phase_kit('ambience')
    def _gap(self,now):
        row=(self.catalog or {}).get('music')
        if not row:return None
        if self.context.get('no_delay'):return now
        p=self.context.get('phase',0);low=int(row['silence_min'][p]);high=max(low,int(row['silence_max'][p]))
        return now+self.rng.randint(low,high)/1000.
    def _land_catalog(self,row,beds,now):
        self.catalog=row;self.beds=beds
        self.retry_at=now+2. if row.get('unavailable') else 0.
        for note in row.get('notes',[]):self._error(note)
        if row.get('interior_note'):self._error(row['interior_note'])
        music=(row.get('music') or {}).get('id',0)
        if music!=self.zone_music:
            self.zone_music=music;self.streams.stop('zone',4000);self.music_live=False;self.music_kit=0
            self.next_track_at=now if row.get('music') else None
            intro=row.get('intro');self.intro=None
            if intro and intro['kit'] and now>=self.intro_last.get(intro['id'],-float('inf'))+intro['delay_minutes']*60:self.intro=intro
    def _finish(self,now):
        if self.future is None or not self.future.done():return
        future,job=self.future,self.job;self.future=None;self.job=None
        try:
            value=future.result()
            kind,token=job
            if kind=='catalog':
                if token==self.key:self._land_catalog(*value,now)
            elif kind=='ambience':
                if token!=self._desired_ambience():return
                path,gain,_=value
                self.streams.play(path,'ambience',gain,loop=True,fade_in_ms=self.ambience_fade,fade_out_ms=self.ambience_fade)
                self.ambience_played=token;self.opens+=1
            elif kind in ('music','intro'):
                if token[0]!=self.key or self.catalog is None or token[1]!=self.zone_music or self.lua_path or self.lua_request or self.suppressed:return
                path,gain,_=value;kit=token[2]
                self.streams.play(path,'zone',gain,loop=False,fade_in_ms=0,fade_out_ms=4000)
                self.music_kit=kit;self.music_live=True;self.next_track_at=None;self.opens+=1
                self.music_attempts=0
                if kind=='intro':
                    self.intro_last[token[3]]=now;self.intro_last.move_to_end(token[3]);self.intro=None
                    while len(self.intro_last)>128:self.intro_last.popitem(last=False)
            elif kind=='lua':
                if token!=self.lua_serial:return
                path,gain,name=value
                self.streams.play(path,'lua',gain,loop=True,fade_in_ms=0,fade_out_ms=4000)
                self.streams.pause('lua',self.suppressed)
                self.lua_path=name;self.lua_request=None;self.streams.stop('zone',4000);self.music_live=False;self.opens+=1
            elif kind=='provider' and token==self.provider:
                self.streams.audio.reverb(value['wet'],value['feedback'],value['damping'],1);self.provider_applied=token
            elif kind=='effect' and self.short_sounds:
                generation,owner=token
                if generation!=self.sound_generation or owner and self.model_owners.get(owner[0])!=owner[1]:return
                path,options=value;self.short_sounds.play(path,**options)
            elif kind=='spell_effect' and self.short_sounds:
                generation,owner=token
                if generation!=self.sound_generation or self.model_owners.get(owner[0])!=owner[1]:return
                path,options=value;unique=('entity',owner[0],'spell')
                self.short_sounds.play(path,**{**options,'unique':unique});self.entity_voices.setdefault(owner[0],set()).add(unique)
            elif kind=='entity' and self.short_sounds:
                generation,guard=token;owner,serial=guard
                if generation!=self.sound_generation or self.model_owners.get(owner)!=serial:return
                for row in value:
                    if row.get('loop_kit'):
                        loop_owner=owner+':audio:'+row['channel']
                        if self.emitters and self.emitters.register(loop_owner,row['loop_kit'],row['position']):
                            self.entity_loops.setdefault(owner,set()).add(loop_owner)
                    else:
                        channel=row['channel'];unique=('entity',owner,channel)
                        # The original terrain-step lane caps six voices; foley
                        # and creature speech retain their own channels.
                        if channel=='footstep' and sum(self.short_sounds.has(k) for keys in self.entity_voices.values() for k in keys if k[2]=='footstep')>=6 and not self.short_sounds.has(unique):continue
                        self.short_sounds.play(row['path'],**{**row['options'],'unique':unique})
                        self.entity_voices.setdefault(owner,set()).add(unique)
            elif kind=='emitter' and self.emitters:self.emitters.resolve(token,value)
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            self._error(exc)
            kind,token=job
            if kind=='catalog' and token==self.key:self.retry_at=now+2.
            elif kind=='ambience' and token==self.ambience_kit:
                self.streams.stop('ambience',self.ambience_fade);self.ambience_played=token
            elif kind=='intro' and token[0]==self.key:self.intro=None
            elif kind=='lua' and token==self.lua_serial:self.lua_request=None
            elif kind=='provider' and token==self.provider:self.streams.audio.reverb(0);self.provider_applied=token
            elif kind=='emitter' and self.emitters:self.emitters.resolve(token,error=exc)
    def update(self,*,area_id,interior=None,minute=720,indoors=False,underwater=False,ghost=False,weather=0,no_delay=False,suppressed=False,hold=False,reverb=True):
        if self.closed:return
        now=self.clock()
        # Interior keys and IDs come from the retained native scene, never file paths.
        key=(int(area_id),tuple(sorted(interior.items())) if interior else ())
        self.context={'phase':phase(minute),'indoors':bool(indoors),'underwater':bool(underwater),'ghost':bool(ghost),'weather':int(weather),'no_delay':bool(no_delay)}
        if hold:
            self.streams.stop('zone',250);self.streams.stop('ambience',250);self.streams.stop('lua',250)
            self.key=None;self.catalog=None;self.zone_music=0;self.music_live=False;self.lua_path=None;self.lua_request=None;self.ambience_kit=0;self.ambience_played=0;self.next_track_at=None
            self.server_kit=None;self.sound_generation+=1;self.sound_queue.clear()
            self._clear_entity_audio();self.model_owners.clear()
            if self.emitters:self.emitters.clear()
            self.lua_serial+=1;return
        if key!=self.key:self.key=key;self.catalog=None;self.retry_at=0
        if bool(suppressed)!=self.suppressed:
            self.suppressed=bool(suppressed)
            if self.lua_path:self.streams.pause('lua',self.suppressed)
            elif self.suppressed:self.streams.stop('zone',0);self.music_live=False;self.next_track_at=None
            else:self.next_track_at=now+3.
        self._finish(now)
        if self.emitters:self.emitters.update(self.listener)
        if self.lua_path and not self.streams.active('lua') and 'lua' not in self.streams.pending:
            self.lua_path=None;self.music_live=False;self.next_track_at=now+6.
        desired=self._desired_ambience()
        if desired!=self.ambience_kit:
            self.ambience_kit=desired;self.ambience_fade=0 if bool(underwater)!=self.was_underwater else 5000
            self.streams.pending.pop('ambience',None)
            if not desired:self.streams.stop('ambience',self.ambience_fade);self.ambience_played=0
        self.was_underwater=bool(underwater)
        self.provider=int((self.catalog or {}).get('sound_provider',[0,0])[int(bool(underwater))]) if reverb else 0
        if not self.provider and self.provider_applied!=0:self.streams.audio.reverb(0);self.provider_applied=0
        if self.music_live and not self.streams.active('zone') and 'zone' not in self.streams.pending:
            self.music_live=False;self.music_kit=0;self.next_track_at=self._gap(now)
        if self.future is not None:return
        if (self.catalog is None or self.catalog.get('unavailable')) and now>=self.retry_at:self._submit(('catalog',self.key),self.assets.catalog,self.key);return
        pins=self.streams.pinned_paths()
        if self.emitters:pins|=self.emitters.pinned()
        if self.short_sounds:pins|={decoder.path for decoder,queue in self.short_sounds.pending.values()}
        if self.lua_request is not None:self._submit(('lua',self.lua_serial),self.assets.prepare_file,self.lua_request,pins);return
        if self.server_kit is not None and not self.suppressed and not self.lua_path:
            kit,self.server_kit=self.server_kit,None;self._submit(('music',(self.key,self.zone_music,kit)),self.assets.prepare,kit,pins);return
        if self.ambience_kit and self.ambience_played!=self.ambience_kit:
            self._submit(('ambience',self.ambience_kit),self.assets.prepare,self.ambience_kit,pins);return
        if self.provider!=self.provider_applied:
            self._submit(('provider',self.provider),self.assets.provider,self.provider);return
        music_ready=not (self.suppressed or self.lua_path or self.music_live)
        if music_ready and self.intro is not None:
            row=self.intro;self._submit(('intro',(self.key,self.zone_music,row['kit'],row['id'])),self.assets.prepare,row['kit'],pins);return
        if music_ready and self.next_track_at is not None and now>=self.next_track_at and (not self.sound_queue or self.music_attempts<2):
            kit=self._phase_kit('music')
            if kit:self.music_attempts+=1;self._submit(('music',(self.key,self.zone_music,kit)),self.assets.prepare,kit,pins);return
        emitter=self.emitters.preparation() if self.emitters else None
        if emitter and (not self.sound_queue or self.effect_attempts>=4):
            serial,kit,position=emitter;self.effect_attempts=0
            self._submit(('emitter',serial),self.assets.emitter,kit,position,pins)
        elif self.sound_queue:
            self.music_attempts=0
            self.effect_attempts+=1
            sound=self.sound_queue.popleft()
            if sound.get('spell_effect'):self._submit(('spell_effect',(self.sound_generation,sound['owner'])),self.assets.effect,sound,pins)
            elif 'entity_event' in sound:self._submit(('entity',(self.sound_generation,sound['owner'])),self.assets.entity_effect,sound,pins)
            else:self._submit(('effect',(self.sound_generation,sound.get('owner'))),self.assets.effect,sound,pins)
    def lua_music(self,path=None):
        if self.closed:return
        self.lua_serial+=1;self.streams.stop('lua',4000);self.lua_path=None;self.lua_request=path;self.next_track_at=self.clock()+6.
    def sound(self,sound):
        if self.closed or self.short_sounds is None:return False
        key=sound.get('file',sound.get('kit'))
        if isinstance(key,bool) or not isinstance(key,(int,str)) or isinstance(key,int) and not 0<key<=0xffffffff or isinstance(key,str) and (not key or len(key)>512):return False
        position=sound.get('position')
        if position is not None and (not isinstance(position,(list,tuple)) or len(position)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>2_000_000 for v in position)):return False
        if len(self.sound_queue)>=64:self._error('World sound request capacity exceeded');return False
        self.sound_queue.append(dict(sound));return True
    def server_music(self,kit):
        # Decoded SMSG_PLAY_MUSIC uses the same zone slot, with repeated live pushes ignored.
        if self.closed or self.suppressed or self.lua_path or self.lua_request:return False
        if isinstance(kit,bool) or not isinstance(kit,int) or not 0<kit<=0xffffffff:return False
        if self.music_kit==kit and self.streams.active('zone'):return True
        if self.job and self.job[0]=='music' and self.job[1][2]==kit:return True
        self.server_kit=kit;return True

    def spell_sound(self,owner,kit,position):
        if self.closed or not isinstance(owner,str) or not owner.startswith('entity:spell:') or len(owner)>104:return False
        if owner not in self.model_owners:
            if len(self.model_owners)>=256:return False
            self.model_serial+=1;self.model_owners[owner]=self.model_serial
        return self.sound(dict(kit=kit,position=position,owner=(owner,self.model_owners[owner]),spell_effect=True))
    def entity_event(self,owner,event,context):
        """Queue an actual actor/GO event with its committed world identity.

        The caller supplies sampled surface and unit state. An absent display,
        material or ground layer stays silent; no guessed character voice.
        """
        if self.closed or self.short_sounds is None or not isinstance(owner,str) or not owner.startswith(('world:','entity:')) or len(owner)>104 or not isinstance(context,dict):return False
        kind=context.get('kind');position=context.get('position')
        creature={'death','stun','aggro','alert','stand','body_loop','wing_flap','wing_glide','jump_start','jump_end','pet_attack','pet_order','pet_dismiss','exertion','injury','footstep','$FSD','$FDX','$FD1','$FD2','$FD3','$FD4','$WNG','$WGG','$AH0','$AH1','$AH2','$AH3','swing','impact'}
        objects={'open','close','destroy','opened','body_loop','stand','$GO0','$GO1','$GO2','$GO3','$GO4','$GO5','$GC0','$GC1','$GC2','$GC3'}
        if kind not in ('creature','player','gameobject') or event not in (objects if kind=='gameobject' else creature):return False
        if not isinstance(position,(list,tuple)) or len(position)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>2_000_000 for v in position):return False
        ident=context.get('model_id') if event=='pet_dismiss' and context.get('model_id') else context.get('display_id')
        if type(ident) is not int or not 0<ident<=0xffffffff:return False
        ints=('display_id','model_id','material_id','terrain_id','ground_effect_id','swing_type','weapon_subclass','target_slot')
        flags=('critical','crushing','hover','stealth','ghost','swimming','self_player','metal')
        floats=('water_depth','collision_height')
        c={'kind':kind,'position':tuple(position)}
        for key in ints:
            if context.get(key) is not None:
                if type(context[key]) is not int or not 0<=context[key]<=0xffffffff:return False
                c[key]=context[key]
        for key in flags:
            if key in context:
                if type(context[key]) is not bool:return False
                c[key]=context[key]
        for key in floats:
            if key in context:
                value=context[key]
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=10000:return False
                c[key]=value
        if c.get('terrain_id') is not None and c.get('ground_effect_id') is not None:return False
        if event=='swing' and 'swing_type' not in c:return False
        if event=='impact' and (any(k not in c for k in ('weapon_subclass','metal','target_slot')) or c['target_slot']>=10):return False
        if event in ('$FDX','stand'):
            if c.get('self_player') or (101*self.rng.getrandbits(32)>>32)>40 or self.clock()<self.stand_at+10.:return False
            self.stand_at=self.clock()
        if event in ('death','destroy'):
            # A committed death retires the old speech/body generation. A
            # wound decode already in flight cannot mask or follow its death.
            self.release_model(owner)
        if kind=='gameobject' and event in ('open','close','destroy') and self.emitters:
            for loop in self.entity_loops.pop(owner,()):self.emitters.release(loop)
        if len(self.sound_queue)>=64:self._error('World sound request capacity exceeded');return False
        if owner not in self.model_owners:
            if len(self.model_owners)>=256:self._error('Model sound owner capacity exceeded');return False
            self.model_serial+=1;self.model_owners[owner]=self.model_serial
        self.sound_queue.append({'entity_event':event,'context':c,'owner':(owner,self.model_owners[owner])});self.entity_events+=1
        return True
    def update_entity(self,owner,position):
        from backend.game_engine_adapter_emitters import point
        if not point(position):return False
        for key in self.entity_voices.get(owner,()):
            at=(position[0],position[1]+2.,position[2]) if key[2]=='foley' else position
            self.short_sounds.move(key,at)
        if self.emitters:
            for loop in self.entity_loops.get(owner,()):
                slot=self.emitters.handles.get(loop)
                if slot is not None:self.emitters.register(loop,self.emitters.entries[slot]['kit'],position)
        return True
    def model_events(self,owner,events,context=None):
        if self.closed or not isinstance(owner,str) or not owner.startswith(('world:','entity:')) or len(owner)>128 or not isinstance(events,dict):return False
        rows=events.get('keys',[])
        if not isinstance(rows,list) or len(rows)>64:return False
        if owner not in self.model_owners:
            if len(self.model_owners)>=256:self._error('Model sound owner capacity exceeded');return False
            self.model_serial+=1;self.model_owners[owner]=self.model_serial
        guard=(owner,self.model_owners[owner])
        if events.get('discarded_window'):self._error('Model event window discarded after pause')
        if events.get('dropped'):self._error('Model event frame capacity exceeded')
        accepted=False
        for row in rows:
            if not isinstance(row,dict):continue
            tag=row.get('tag');kit=row.get('data');position=row.get('position')
            if tag in ('$SND','$DSO'):
                if kit:accepted=self.sound({'kit':kit,'position':position,'owner':guard}) or accepted
            elif tag=='$DSL' and self.emitters:
                if kit:accepted=self.emitters.register(owner,kit,position) or accepted
            elif tag=='$DSE' and self.emitters:self.emitters.release(owner);accepted=True
            elif context is not None:
                c={**context,'position':position or context.get('position')}
                accepted=self.entity_event(owner,tag,c) or accepted
            else:self._error('Unmapped model event: '+str(tag)[:16])
        return accepted
    def release_model(self,owner):
        self.model_owners.pop(owner,None)
        self.sound_queue=deque(r for r in self.sound_queue if not r.get('owner') or r['owner'][0]!=owner)
        for key in self.entity_voices.pop(owner,()):self.short_sounds.stop(key)
        if self.emitters:
            for loop in self.entity_loops.pop(owner,()):self.emitters.release(loop)
        if self.emitters:self.emitters.release(owner)
    def _clear_entity_audio(self):
        for keys in self.entity_voices.values():
            for key in keys:self.short_sounds.stop(key)
        self.entity_voices.clear();self.entity_loops.clear()
    def diagnostics(self):
        return {'source':'GG_ENGINE_DBC','zone_music':self.zone_music,'music_kit':self.music_kit,'ambience_kit':self.ambience_kit,'ambience_played':self.ambience_played,'next_track_at':self.next_track_at,'pending':self.job[0] if self.job else None,'opens':self.opens,'errors':list(self.errors),
                'provider':self.provider_applied,'entity_events':self.entity_events,'entity_owners':len(self.model_owners),'entity_voices':sum(len(keys) for keys in self.entity_voices.values()),'emitters':self.emitters.diagnostics() if self.emitters else None,'limitations':['Tracks up to 8 MiB use the bounded file cache; larger tracks stream original archive sectors without extraction','Entity sounds require original display/voice/material/terrain DBC and actual sampled identity; absent rows stay silent','Spell/mount/sheathe/vocal graphs and exact original voice latch probabilities remain partial']}
    def close(self):
        if self.closed:return
        self.closed=True;self.pool.shutdown(wait=True,cancel_futures=True);self.future=None
        self.sound_generation+=1;self.sound_queue.clear()
        self._clear_entity_audio();self.model_owners.clear()
        if self.emitters:self.emitters.clear()
        for channel in ('zone','ambience','lua'):self.streams.stop(channel,250)
        self.assets.close()
