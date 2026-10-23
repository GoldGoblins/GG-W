"""Qt-thread sound and Lua presentation shared by the desktop and game client."""
from __future__ import annotations
import array,json,math,time,wave
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,QCoreApplication,QAbstractListModel,QModelIndex,Qt
from backend.game_engine_native_presentation import Audio,Lua,library,status
from backend.game_engine_adapter_assets import asset_path
from backend.game_engine_adapter_gameplay import GameplayViews
PROJECT=Path(__file__).resolve().parents[1]
CLIPS=('step-grass','step-stone','step-water','ui-click','attack','hit','ambience','music')

def load_toc(path):
    """GgEngine TOC order, within the selected addon directory only."""
    path=Path(path);root=path.parent.resolve();directives={};files=[]
    if path.stat().st_size>16384:raise ValueError('addon manifest too large')
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line=raw.strip()
        if line.startswith('##'):
            if ':' in line:
                key,value=line[2:].split(':',1);directives[key.strip().lower()]=value.strip()
        elif line and not line.startswith('#'):
            entry=(root/line.replace('\\','/')).resolve()
            if not entry.is_relative_to(root) or entry.suffix!='.lua' or not entry.is_file():raise ValueError('unsupported or escaping addon source')
            if entry.stat().st_size>262144 or len(files)>=32:raise ValueError('addon source capacity exceeded')
            files.append(entry)
    if directives.get('interface')!='1':raise ValueError('unsupported GG Lua interface')
    return directives,files

class FrameModel(QAbstractListModel):
    """Retain UI delegates across snapshot text/value updates."""
    ROLE=Qt.UserRole+1
    def __init__(self,parent=None):super().__init__(parent);self.rows=[]
    def roleNames(self):return {self.ROLE:b'frameData'}
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.DisplayRole):
        return self.rows[index.row()] if role==self.ROLE and index.isValid() and 0<=index.row()<len(self.rows) else None
    def sync(self,rows):
        if [r['id'] for r in rows]!=[r['id'] for r in self.rows]:
            self.beginResetModel();self.rows=rows;self.endResetModel();return
        for i,row in enumerate(rows):
            if row!=self.rows[i]:self.rows[i]=row;self.dataChanged.emit(self.index(i),self.index(i),[self.ROLE])

class Presentation(QObject):
    uiChanged=Signal();audioChanged=Signal();addonsChanged=Signal();clientControlsChanged=Signal();nameplatesChanged=Signal();textureSettingsChanged=Signal()
    def __init__(self,parent=None,*,device=True):
        super().__init__(parent)
        self.lua=None;self.audio=None;self.sink=None;self.output=None;self.timer=QTimer(self);self._frame_model=FrameModel(self);self._canvas=None;self.full_ui=False
        self.timer.setInterval(10);self.timer.timeout.connect(self._pump)
        self._frames='[]';self._audio_json='{}';self.errors=[];self.last_update=0.;self._lua_tick_last=time.monotonic();self.updates=0
        self.active=True;self.focused=True;self.running=False;self.muted=False;self.music_streams=None;self.short_sounds=None;self.audio_zone=None;self.snapshot={};self.progression={};self.gameplay_views=GameplayViews();self.file_clips={};self.unsupported_requests=[]
        from backend.game_engine_adapter_client_tools import ClientTools
        self.client_tools=ClientTools(self)
        from backend.game_engine_adapter_graphics import ClientGraphics
        self.graphics=ClientGraphics(self)
        self._nameplate_bits=0
        self._nameplate_report={}
        self._nameplate_pending=None;self._nameplate_scheduled=False
        self._ui_input_scheduled=False
        from backend.game_engine_adapter_formats import AssetCache
        self.sound_assets=AssetCache()
        from random import Random
        self.sound_random=Random();self.sound_pick={}
        self.zone_audio=None;self.zone_source=None;self.zone_context=None;self._default_voices=[]
        from backend.game_engine_adapter_entity_audio import EntityAudio
        self.entity_audio=EntityAudio()
        from backend.game_engine_adapter_spell_audio import SpellAudio
        self.spell_audio=SpellAudio()
        from backend.game_engine_adapter_world_actors import WorldActors
        self.world_actors=WorldActors(self)
        self._world_actor_rows=None;self._world_actor_rows_scope=None
        self.volumes={'master':.5,'sfx':1.,'music':.4,'ambience':.6}
        self.runtime_settings={'MasterSoundEffects':'1','EnableMusic':'1','EnableAmbience':'1','SoundReverb':'1','SoundZoneMusicNoDelay':'0','spellEffectLevel':'2','ffx':'1','ffxGlow':'1','ffxDeath':'1','trilinear':'1','ChatBubbles':'1','ChatBubblesParty':'0'};self.particle_density=1.
        self.last_position=None;self.step_distance=0.;self.last_sequence=None;self.last_ability=None;self.last_health=None
        self.submitted_frames=0;self.rendered_frames=0;self.underruns=0;self._pending=b'';self.audio_state='NOT_INITIALIZED';self.loaded_addons=[]
        self.character_key=None
        self.local_character_mode=False
        self._addon_json='{}';self._ui_generation=0;self._addon_error=''
        self._addon_editor=None
        self._client_controls_json='{}'
        if library():
            self._init_lua()
            self._init_audio(device)
        else:self.audio_state='NATIVE_UNAVAILABLE'
        app=QCoreApplication.instance()
        if app:app.aboutToQuit.connect(self.close)
        self._notify_audio()

    def _error(self,exc):
        text=type(exc).__name__+': '+str(exc)[:240]
        if text not in self.errors:self.errors=(self.errors+[text])[-16:]

    def _init_lua(self,clock_floor=0.):
        try:
            from backend.game_engine_adapter_ui import GgEngineUI,available
            if available():
                self.lua=GgEngineUI(clock=max(time.monotonic(),clock_floor));self.full_ui=True
                self.lua.saving_enabled=not (self.local_character_mode and self.character_key is None)
                self._sync_runtime_settings()
                state,character=self._addon_roots(self.character_key)
                characters=getattr(self.parent(),'_local_characters',None)
                if self.character_key is not None and characters is not None:
                    from backend.game_engine_adapter_addon_state import bind_local_roster
                    bind_local_roster(self.lua,state,self.character_key,characters)
                self.loaded_addons=self.lua.load_addons(PROJECT/'qml/game/framexml',state,assets=self.sound_assets,core_root=PROJECT/'qml/game/Interface/FrameXML',character_saved_root=character)
                self.graphics.seed()
                self._prepare_world_frame(self.lua)
                self._ui_generation+=1;self.refreshAddons()
                self._update_frames();self._lua_tick_last=time.monotonic();return
            self.lua=Lua();root=PROJECT/'qml/game/lua'
            self.lua.execute((root/'host.lua').read_text(),'GG host')
            for manifest in sorted(root.glob('*/*.toc'))[:16]:
                metadata,files=load_toc(manifest)
                for path in files:self.lua.execute(path.read_text(),manifest.parent.name+'/'+path.name)
                self.loaded_addons.append({'id':manifest.parent.name,'title':metadata.get('title',manifest.parent.name)})
            self.lua.event('ADDON_LOADED');self._update_frames()
        except (OSError,ValueError,MemoryError,RuntimeError,TimeoutError) as exc:self._error(exc)

    @staticmethod
    def _addon_roots(key):
        from backend.application_paths import STATE_HOME
        state=Path(__import__('os').environ.get('XDG_STATE_HOME',str(STATE_HOME)))/'goldgoblins/gg-game/addons'
        if key is None:return state,state
        import uuid
        if not isinstance(key,str) or uuid.UUID(key).hex!=key:raise ValueError('Invalid local character UI profile')
        character=state/'characters'/key
        if not character.resolve().is_relative_to(state.resolve()):raise ValueError('Escaping local character UI profile')
        return state,character

    def save_character_ui(self,key):
        if not self.full_ui or not self.lua:return
        if self.character_key!=key:raise ValueError('Karaktärens gränssnitt hör till en annan sparprofil.')
        try:self.lua.save()
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            self._error(exc);raise ValueError('Karaktärens gränssnittsinställningar kunde inte sparas.') from exc

    def set_character(self,key,*,initial_snapshot=None):
        """Save the previous UI, prepare the next VM, then commit its identity."""
        if key==self.character_key:return True
        return self._replace_ui(key,local_mode=True,initial_snapshot=initial_snapshot)

    def _replace_ui(self,key,*,local_mode,initial_snapshot=None):
        if not self.full_ui or not self.lua:self.character_key=key;return True
        candidate=None
        try:
            from backend.game_engine_adapter_ui import GgEngineUI
            state,character=self._addon_roots(key)
            clock=time.monotonic()
            if not self.lua.closed:
                clock=max(clock,self.lua.evaluate('return GetTime()')[0])
                self.lua.event('PLAYER_LOGOUT');self.lua.save()
            candidate=GgEngineUI(clock=max(time.monotonic(),clock))
            candidate.resize(*self.lua._size)
            candidate.saving_enabled=not (local_mode and key is None)
            settings={**self.runtime_settings,**{name:str(self.volumes[bus]) for name,bus in (('MasterVolume','master'),('SoundVolume','sfx'),('MusicVolume','music'),('AmbienceVolume','ambience'))}}
            self._seed_texture_settings(candidate)
            candidate.request('runtime_config',values=settings)
            candidate_views=GameplayViews()
            if initial_snapshot is not None:
                # Seed the model before any addon file/ADDON_LOADED/login
                # handler runs, rather than fixing its identity on a later tick.
                data=candidate_views.update(initial_snapshot)
                self._publish_full_ui(candidate,initial_snapshot,data,emit_pending=False)
            characters=getattr(self.parent(),'_local_characters',None)
            if key is not None and characters is not None:
                from backend.game_engine_adapter_addon_state import bind_local_roster
                bind_local_roster(candidate,state,key,characters)
            loaded=candidate.load_addons(PROJECT/'qml/game/framexml',state,assets=self.sound_assets,
                core_root=PROJECT/'qml/game/Interface/FrameXML',character_saved_root=character)
            if self.graphics.values:candidate.request('graphics_seed',values=self.graphics.values)
            self._prepare_world_frame(candidate)
        except (OSError,ValueError,RuntimeError,MemoryError,TimeoutError) as exc:
            if candidate:candidate.close()
            self._error(exc);return False
        previous=self.lua;self.lua=candidate;self.character_key=key;self.loaded_addons=loaded
        self.graphics.changed_vm()
        self._nameplate_pending=None;self._nameplate_report={}
        self._nameplate_mode({'nameplates':{'bits':0}})
        self.local_character_mode=local_mode
        self._ui_generation+=1;self._addon_error=''
        self._addon_editor=None
        self.gameplay_views=candidate_views
        if initial_snapshot is not None:
            self.snapshot=initial_snapshot;self.running=initial_snapshot.get('state')=='RUNNING'
            self._publish_client_controls(initial_snapshot)
            self.progression=initial_snapshot.get('progression',{})
            self._freeze_gameplay_views()
        elif hasattr(self,'_shown_gameplay'):del self._shown_gameplay
        self._request_snapshot=None;self.last_sequence=None;self.last_position=None;self.last_health=None
        self.last_update=0.;self._lua_tick_last=time.monotonic()
        # The local login attaches its canvas before a character's saving
        # scope exists. Rebind applied account graphics when that scope opens.
        self.graphics.attach(self.graphics.standalone)
        self.world_actors.close()
        self._world_actor_rows=None;self._world_actor_rows_scope=None
        self.entity_audio.close()
        self.spell_audio.close()
        previous.close()
        if initial_snapshot is not None:
            try:self._publish_shared_events(candidate,initial_snapshot)
            except (OSError,ValueError,RuntimeError,MemoryError,TimeoutError) as exc:
                # The new character/VM is already committed. Keep failed
                # events durable for the next publish instead of rolling
                # back the character while leaving this accepted VM active.
                self._error(exc)
        try:
            self._update_frames();self.refreshAddons()
        except (OSError,ValueError,RuntimeError,MemoryError,TimeoutError) as exc:
            # A timed-out postcommit event can close the accepted worker.
            # Rendering must not unwind the already committed character/VM.
            self._error(exc)
        return True

    @staticmethod
    def _prepare_world_frame(ui):
        ui.execute("if not WorldFrame then WorldFrame=CreateFrame('WorldFrame','WorldFrame');WorldFrame:SetAllPoints() end")
        from backend.game_engine_adapter_navigation import install as install_navigation
        install_navigation(ui)
        ui.execute(Path(__file__).with_name('game_engine_adapter_spells.lua').read_text())

    def _init_audio(self,device):
        try:
            rate=48000
            if device:
                from PySide6.QtMultimedia import QAudioFormat,QAudioSink,QMediaDevices
                selected=QMediaDevices.defaultAudioOutput()
                if selected.isNull():self.audio_state='NO_OUTPUT_DEVICE';return
                fmt=QAudioFormat();fmt.setSampleRate(rate);fmt.setChannelCount(2);fmt.setSampleFormat(QAudioFormat.Float)
                if not selected.isFormatSupported(fmt):self.audio_state='UNSUPPORTED_OUTPUT_FORMAT';return
                self.sink=QAudioSink(selected,fmt,self);self.sink.setBufferSize(rate*8//10)
            self.audio=Audio(rate)
            from backend.game_engine_audio_stream import MusicStreams
            self.music_streams=MusicStreams(self.audio)
            from backend.game_engine_audio_short import ShortSounds
            self.short_sounds=ShortSounds(self.audio)
            for i,name in enumerate(CLIPS):
                with wave.open(str(PROJECT/'qml/game/audio'/f'{name}.wav'),'rb') as w:
                    if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getnframes()>w.getframerate()*30:raise ValueError('invalid GG audio clip')
                    samples=array.array('h',w.readframes(w.getnframes()));self.audio.clip(i,[x/32768 for x in samples],w.getframerate())
            self._default_voices.append(self.audio.play(6,2,gain=.22,loop=True))
            try:self.music_streams.play(PROJECT/'qml/game/audio/music.wav',channel='zone')
            except RuntimeError:
                self._default_voices.append(self.audio.play(7,1,gain=.22,loop=True))
            self.audio_state='OFFLINE'
            if self.sink:
                self.output=self.sink.start()
                if self.output is None:self.audio_state='DEVICE_START_FAILED';return
                self.audio_state='DEVICE_READY';self.timer.start()
        except (OSError,ValueError,RuntimeError) as exc:self.audio_state='ERROR';self._error(exc)

    def _pump(self):
        if not self.audio or not self.sink or not self.output:return
        try:
            self._pump_short_sounds()
            if self.zone_audio and self.zone_context:self.zone_audio.update(**self.zone_context)
            if self.music_streams:
                self.music_streams.pump()
                for message in self.music_streams.errors:self._error(RuntimeError(message))
                self.music_streams.errors.clear()
            from PySide6.QtMultimedia import QAudio
            # Qt 6.10 returns QtAudio.Error while QAudio is a compatibility
            # namespace. Compare enum values across supported PySide versions.
            error=self.sink.error().value
            if error not in (QAudio.NoError.value,QAudio.UnderrunError.value):
                self.audio_state='DEVICE_ERROR';self.timer.stop();self._notify_audio();return
            if error==QAudio.UnderrunError.value:self.underruns+=1
            free=int(self.sink.bytesFree())
            if self._pending:
                n=self.output.write(self._pending[:free]);n=max(0,n);self._pending=self._pending[n:];free-=n
            if not self._pending and free>=8:
                frames=min(2048,free//8);data=self.audio.render(frames);self.rendered_frames+=frames
                n=max(0,self.output.write(data));self.submitted_frames+=n//8;self._pending=data[n:]
        except (RuntimeError,ValueError) as exc:self._error(exc);self.timer.stop()

    @staticmethod
    def _seed_texture_settings(lua):
        # The original host setter updates registered CVars only. Register
        # through the original Lua API once per VM, including reload candidates.
        if not getattr(lua,'_gg_texture_settings_seeded',False):
            lua.execute("RegisterCVar('trilinear','1') RegisterCVar('ChatBubbles','1') RegisterCVar('ChatBubblesParty','0')",'GG client presentation defaults')
            lua._gg_texture_settings_seeded=True

    def _sync_runtime_settings(self):
        if self.lua and self.full_ui:
            self._seed_texture_settings(self.lua)
            values={**self.runtime_settings,**{name:str(self.volumes[bus]) for name,bus in (('MasterVolume','master'),('SoundVolume','sfx'),('MusicVolume','music'),('AmbienceVolume','ambience'))}}
            rows=list(values.items())
            for offset in range(0,len(rows),16):self.lua.request('runtime_config',values=dict(rows[offset:offset+16]))
    def _runtime_cvars(self,rows):
        buses={'mastervolume':'master','soundvolume':'sfx','musicvolume':'music','ambiencevolume':'ambience'}
        names={name.casefold():name for name in self.runtime_settings}
        changed=False;previous_filter=self.textureTrilinear
        for name,value in rows[:64]:
            key=name.casefold()
            if key not in buses and key not in names:continue
            try:
                number=float(value)
                if not math.isfinite(number):raise ValueError('Non-finite runtime setting')
                if key in buses:
                    if not 0<=number<=1:raise ValueError('Volume outside 0..1')
                    self.volumes[buses[key]]=number
                elif key=='spelleffectlevel':
                    if number not in (0,1,2):raise ValueError('Spell effect level outside 0..2')
                    self.runtime_settings[names[key]]=str(int(number));self.particle_density=(.33,.66,1.)[int(number)]
                else:
                    if number not in (0,1):raise ValueError('Runtime switch requires 0 or 1')
                    self.runtime_settings[names[key]]=str(int(number))
                changed=True
            except (ValueError,OverflowError):self._unsupported('Invalid runtime CVar: '+name)
        if rows:self._sync_runtime_settings()
        if previous_filter!=self.textureTrilinear:self.textureSettingsChanged.emit()
        if changed:
            self.audio_zone=None;self._gain();self._notify_audio()
            world=getattr(self.parent(),'_engine_world_stream',None)
            if world:world.lightingChanged.emit()
    def _gain(self):
        if self.audio:
            volumes=dict(self.volumes)
            if self.runtime_settings['EnableMusic']=='0':volumes['music']=0.
            if self.runtime_settings['EnableAmbience']=='0':volumes['ambience']=0.
            self.audio.gain(**volumes,enabled=self.active and self.focused and self.running and not self.muted and self.runtime_settings['MasterSoundEffects']=='1')

    def _notify_audio(self):
        value=json.dumps({'state':self.audio_state,'muted':self.muted,**self.volumes},separators=(',',':'))
        if value!=self._audio_json:self._audio_json=value;self.audioChanged.emit()

    def _update_frames(self):
        if not self.lua:return
        rows=self.lua.frames()
        if self._canvas:self._canvas.sync(rows)
        if not self.full_ui:self._frame_model.sync(rows)
        value=json.dumps(rows,ensure_ascii=False,separators=(',',':'))
        if value!=self._frames:self._frames=value;self.uiChanged.emit()

    def queue_ui_input(self):
        # Physical UI actions also work when the world simulation is paused.
        # Leave Qt's event callback before dispatching into the host/QML models.
        if not self._ui_input_scheduled:
            self._ui_input_scheduled=True;QTimer.singleShot(0,self._drive_ui_input)

    def _drive_ui_input(self):
        self._ui_input_scheduled=False
        if not self.lua or self.lua.closed:return
        self.last_update=0.;self.update(self.snapshot)

    def _world_audio(self,world):
        host=self.parent();stream=getattr(host,'_engine_world_stream',None)
        source=stream.cache.archive_source if stream is not None and stream.active else None
        if source!=self.zone_source:
            if self.zone_audio:
                self.zone_audio.close();self.zone_audio=None
                self.short_sounds.close()
                from backend.game_engine_audio_short import ShortSounds
                self.short_sounds=ShortSounds(self.audio)
            self.zone_source=source;self.zone_context=None
            if source:
                from backend.game_engine_adapter_audio import ZoneAudio
                for voice in self._default_voices:
                    if voice>=0 and self.audio.voice_active(voice):self.audio.fade(voice,0,0,True)
                self._default_voices.clear();self.music_streams.stop('zone',0)
                self.zone_audio=ZoneAudio(self.music_streams,source,short_sounds=self.short_sounds)
            elif self.music_streams:
                self._default_voices.append(self.audio.play(6,2,gain=.22,loop=True))
                self.music_streams.play(PROJECT/'qml/game/audio/music.wav',channel='zone')
        if self.zone_audio:
            cfg=stream.light.config or {};minute=cfg.get('minute',720)+stream.clock_ms/60000*cfg.get('time_scale',1)
            eye=stream.camera.eye if stream.camera else stream.position;water=stream.water_sample(*eye)
            self.zone_context={'area_id':world.get('area_id',0),'interior':stream.interior_audio_at(*stream.position),'minute':minute,'indoors':world['indoors'],
                'underwater':water['body_kind'] in ('STILL','WATER','RAPIDS','OCEAN') and eye[1]<water['height_m'],'ghost':cfg.get('ghost',False),
                'weather':(stream.weather.config or {}).get('sound_id',0),'no_delay':self.runtime_settings.get('SoundZoneMusicNoDelay')=='1',
                'suppressed':bool(self.snapshot.get('cinematic',{}).get('music_suppressed',False)),'reverb':self.runtime_settings['SoundReverb']=='1','hold':not world.get('world_loaded',False)}
            self.zone_audio.listener=stream.camera.eye if stream.camera else stream.position
            self.zone_audio.update(**self.zone_context)

    def world_model_events(self,owner,events):
        if self.zone_audio and self.running:return self.zone_audio.model_events(owner,events)
        return False
    def world_model_removed(self,owner):
        if self.zone_audio:self.zone_audio.release_model(owner)

    def world_music_packet(self,payload):
        import struct
        payload=bytes(payload)
        if len(payload)!=4 or self.zone_audio is None:return False
        return self.zone_audio.server_music(struct.unpack('<I',payload)[0])

    def _freeze_gameplay_views(self):
        from copy import copy
        self._shown_gameplay=copy(self.gameplay_views)
        for field in ('bank','merchant','quest','local','services'):
            setattr(self._shown_gameplay,field,copy(getattr(self.gameplay_views,field)))

    def _publish_committed_ui(self,result):
        """Lua events observe committed getters while displayed IDs stay frozen."""
        if (result.get('client_events') and self.full_ui and self.lua and isinstance(result.get('player'),dict)
                and all(isinstance(result.get(key),dict) for key in ('items','bank','merchant'))):
            data=self.gameplay_views.update(result)
            self._request_snapshot=result
            self._publish_full_ui(self.lua,result,data)
        self._publish_client_controls(result)
        for event in result.get('client_events',[])[:128]:self.lua.event(event['event'],*event['args'])
        self.client_tools.events(result.get('client_events',[]))

    def _publish_full_ui(self,lua,snapshot,data,*,emit_pending=True):
        from backend.game_engine_adapter_world import environment
        player=snapshot['player'];progression=snapshot.get('progression',self.progression)
        combat=snapshot.get('combat_live',{});actor=combat.get('player',{})
        data=dict(data);data['world']=environment(snapshot)
        data['combat_profile']=combat.get('profile')
        from backend.game_engine_adapter_identity import identity
        data['identity']=identity(snapshot)
        from backend.game_engine_adapter_navigation import presentation_imported_navigation
        data['navigation']=presentation_imported_navigation(self,snapshot,lua)
        data['client_controls']=player.get('client_controls',{})
        stream=getattr(self.parent(),'_engine_world_stream',None)
        life=player.get('client_controls',{}).get('services',{}).get('lifecycle',{})
        if stream and stream.light.player_ghost!=bool(life.get('ghost')):
            stream.light.player_ghost=bool(life.get('ghost'));stream.light.next_ms=0;stream.light._room()
        lua.publish(player,snapshot.get('state')=='RUNNING',
            float(actor.get('health',actor.get('hp',100))),float(combat.get('resource',100)),
            max_health=float(actor.get('max_health',actor.get('max_hp',100))),
            max_resource=float(combat.get('resource_capacity',100)),
            level=float(player.get('level',progression.get('level',1))),
            xp=float(progression.get('xp',0)),xp_to_next=float(progression.get('xp_to_next',100)),
            name=str(player.get('name','Gold Goblin')),target=snapshot.get('targeting',{}).get('selected'),**data)
        if emit_pending:self._publish_shared_events(lua,snapshot)

    def _publish_shared_events(self,lua,snapshot):
        # Initial getters are seeded before addon loading. Deliver retained
        # messages only after the accepted VM has installed its handlers.
        if getattr(self,'_shared_events_lua',None) is not lua:
            self._shared_events_lua=lua;self._shared_events_seen=set()
        pending=snapshot.get('player',{}).get('client_controls',{}).get('services',{}).get('shared_pending_events',[])[:128]
        present={event['key'] for event in pending}
        self._shared_events_seen.intersection_update(present)
        for event in pending:
            if event['key'] not in self._shared_events_seen:
                lua.event(event['event'],*event['args'])
                self._shared_events_seen.add(event['key'])
        ack_ids=[event['ack_id'] for event in pending if event.get('ack_id') and event['key'] in self._shared_events_seen]
        if (ack_ids and not getattr(self,'_shared_chat_ack_scheduled',False)
                and time.monotonic()>=getattr(self,'_shared_chat_ack_retry_at',0.)):
            self._shared_chat_ack_request=(self.character_key,lua,ack_ids[:64])
            self._shared_chat_ack_scheduled=True
            QTimer.singleShot(0,self._ack_shared_chat)

    @Slot()
    def _ack_shared_chat(self):
        self._shared_chat_ack_scheduled=False
        key,lua,ids=self._shared_chat_ack_request
        if key is None or key!=self.character_key or lua is not self.lua or lua.closed:return
        call=getattr(self.parent(),'gameEngineClientControl',None)
        if not callable(call):return
        try:
            result=call(json.dumps(dict(kind='local',op='SharedChatAck',ids=ids)))
            if isinstance(result,str):result=json.loads(result)
            if not isinstance(result,dict) or result.get('error'):
                self._shared_chat_ack_retry_at=time.monotonic()+1.
        except (OSError,ValueError,TypeError,RuntimeError,TimeoutError):
            # The already shown event stays deduplicated in this VM. Its
            # durable queue remains pending until a later successful ack.
            self._shared_chat_ack_retry_at=time.monotonic()+1.

    def _world_actor_snapshot(self,snapshot):
        """Inspector deltas reuse the last real bounded world entity packet.

        Missing render rows mean this packet does not carry that stream. An
        explicit empty canonical list still retires the visible world actors.
        """
        stream=getattr(self.parent(),'_engine_world_stream',None)
        cache=getattr(stream,'cache',None)
        if not getattr(stream,'active',False) or cache is None or cache.closed or cache.archive_source is None:
            self._world_actor_rows=None;self._world_actor_rows_scope=None
            return snapshot
        scope=(id(self.lua),id(cache),str(cache.archive_source),(getattr(stream,'config',None) or {}).get('map'),self.character_key)
        if scope!=self._world_actor_rows_scope:
            self._world_actor_rows=None;self._world_actor_rows_scope=scope
        render=snapshot.get('render')
        rows=render.get('entities') if isinstance(render,dict) else None
        if isinstance(rows,list):self._world_actor_rows=rows[:128]
        if self._world_actor_rows is None:return snapshot
        return {**snapshot,'render':{**(render if isinstance(render,dict) else {}),'entities':self._world_actor_rows}}

    def update(self,snapshot):
        if getattr(self,'_draining_requests',False):return
        if not isinstance(snapshot,dict) or not isinstance(snapshot.get('player'),dict):return
        # Render callbacks can arrive between inspector/UI publication ticks.
        # Keep their authoritative rows even when this UI tick is throttled.
        self._world_actor_snapshot(snapshot)
        now=time.monotonic()
        if now-self.last_update<.1:return
        elapsed=min(1.,max(0.,now-self._lua_tick_last))
        self.last_update=now;self.updates+=1
        self.client_tools.snapshot(snapshot)
        if self.lua and self.full_ui:
            try:
                # Mouse/key intents address the previously displayed rows.
                # Refresh destinations first; displayed ids remain frozen.
                # Drain before publishing a newer list into the native UI.
                self.gameplay_views.update(snapshot)
                self._ui_requests(self.lua.request('requests'))
                if self._request_snapshot is not None:snapshot=self._request_snapshot
                self._reconcile_cursor()
            except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
                self._error(exc);return
        player=snapshot['player'];self.running=snapshot.get('state')=='RUNNING'
        self.snapshot=snapshot
        self._publish_client_controls(snapshot)
        if isinstance(snapshot.get('progression'),dict):self.progression=snapshot['progression']
        combat=snapshot.get('combat_live',{});actor=combat.get('player',{})
        health=float(actor.get('health',actor.get('hp',100)));resource=float(combat.get('resource',100))
        try:
            if self.audio:
                self.audio.listener(*(float(player.get(k,0)) for k in ('x','y','z','yaw')));self._gain()
                from backend.game_engine_adapter_world import environment
                world=environment(snapshot)
                self._world_audio(world)
                stream=getattr(self.parent(),'_engine_world_stream',None)
                config=getattr(stream,'config',None) or {}
                audio_snapshot=self.world_actors.bound_snapshot(self._world_actor_snapshot(snapshot),stream)
                self.entity_audio.update(self.zone_audio if world.get('world_loaded') else None,audio_snapshot,stream,
                    scope=(id(self.lua),str(self.zone_source),config.get('map')),running=self.running)
                self.spell_audio.update(self.zone_audio if world.get('world_loaded') else None,snapshot,
                    scope=(id(self.lua),str(self.zone_source),config.get('map'),self.character_key),running=self.running)
                self.world_actors.update(audio_snapshot,stream,self.entity_audio,
                    scope=(id(self.lua),str(self.zone_source),config.get('map'),self.character_key),
                    running=self.running,particle_density=self.particle_density)
                self._movement(player)
                zone=(str(world.get('biome','')),str(world.get('medium','LAND')),world['indoors'])
                if zone!=self.audio_zone:
                    wet=0. if self.runtime_settings['SoundReverb']=='0' else .32 if zone[1]=='WATER' else .22 if zone[2] else .08 if zone[0] in ('FOREST','JUNGLE') else .015
                    if not self.zone_audio:self.audio.reverb(wet,.84 if zone[1]=='WATER' else .72,.45 if zone[1]=='WATER' else .18,1)
                    if self.music_streams and self.audio_zone is not None and not self.zone_audio:self.music_streams.play(PROJECT/'qml/game/audio/music.wav',channel='zone',gain=.12 if zone[1]=='WATER' else .22)
                    self.audio_zone=zone
                ability=(player.get('last_ability'),player.get('last_ability_time'))
                if self.running and self.last_ability is not None and ability!=self.last_ability and ability[0]:self.audio.play(4,gain=.5)
                if self.running and self.last_health is not None and health<self.last_health:self.audio.play(5,gain=.5)
                self.last_ability=ability;self.last_health=health
            if self.lua:
                if self.full_ui:
                    data=self.gameplay_views.update(snapshot)
                    self._freeze_gameplay_views()
                    self._publish_full_ui(self.lua,snapshot,data)
                else:self.lua.publish(player,self.running,health,resource)
                if self.full_ui:self.lua.tick(elapsed);self._lua_tick_last=now
                else:self.lua.event('SNAPSHOT')
                events=snapshot.get('event_journal',{}).get('events',[])
                if events:
                    latest=max(int(e.get('sequence',0)) for e in events)
                    if self.last_sequence is not None and latest>=self.last_sequence:
                        for e in [e for e in events if int(e.get('sequence',0))>self.last_sequence][-8:]:
                            if self.running and e.get('kind') in ('PET_ATTACK','GROUP_ATTACK','PET_HIT','GROUP_HIT'):
                                if self.audio:self.audio.play(5 if e['kind'].endswith('HIT') else 4,gain=.3)
                            text={'START':'Redo att utforska','PLAY':'Redo att utforska','PAUSE':'Äventyret är pausat','RESET':'En ny resa börjar'}.get(e.get('kind'),str(e.get('text',e.get('kind',''))))
                            self.lua.event('GAME_EVENT',text[:200])
                    self.last_sequence=latest
                self._update_frames()
                if self.full_ui:
                    self._ui_requests(self.lua.request('requests'))
        except (OSError,wave.Error,ValueError,RuntimeError,TimeoutError) as exc:self._error(exc)

    def _ui_requests(self,requests):
        self._request_snapshot=None
        self.client_tools.flags(requests.get('client_tools'))
        for error in requests.get('ui_errors',[])[:32]:self.lua.event('UI_ERROR_MESSAGE',str(error)[:200])
        self._media_requests(requests)
        self._game_requests(requests)
        self.client_tools.requests(requests.get('client_tools'))
        self.graphics.requests(requests)
        self._nameplate_mode(requests)

    def _nameplate_mode(self,requests):
        value=requests.get('nameplates',{}).get('bits',self._nameplate_bits)
        if value!=self._nameplate_bits:
            self._nameplate_bits=value;self.nameplatesChanged.emit()

    def _media_requests(self,requests):
        self._runtime_cvars(requests.get('cvars',[]))
        for sound in requests.get('sounds',[]):self._sound_request(sound)
        for music in requests.get('music',[]):
            if self.zone_audio:
                if music.get('stop'):self.zone_audio.lua_music()
                elif music.get('play'):self.zone_audio.lua_music(music['play'])
            elif music.get('stop') and self.music_streams:self.music_streams.stop()
            elif music.get('play') and self.music_streams:
                path=self.sound_assets.resolve(music['play'])
                if not path.is_relative_to(PROJECT/'qml') or not path.is_file():self._error(ValueError('Unknown music asset'))
                else:self.music_streams.play(path)

    def context_world(self,identity,context,sell):
        """A real merchant world click sells exactly the displayed cursor amount."""
        source=self.lua.request('cursor_source') if self.full_ui and self.lua else None
        shown=getattr(self,'_shown_gameplay',None)
        frozen=dict(shown.inventory_refs) if shown is not None else {}
        result=context(identity)
        if (not source or source.get('kind')!='item' or source.get('bag')!=0
                or not isinstance(result,dict) or result.get('error')):return result
        fresh=GameplayViews();fresh.update(result)
        if not fresh.merchant.opened:return result
        slot=source['slot'];ref=frozen.get(slot)
        if not ref or fresh.inventory_refs.get(slot)!=ref:
            result['error']='MERCHANT_CURSOR_SOURCE_CHANGED';return result
        plan=fresh.merchant.route_sell(0,slot,frozen)
        transaction=sell(*plan['args'],source['count']) if source.get('count') is not None else sell(*plan['args'])
        if isinstance(transaction,dict) and not transaction.get('error'):
            self.lua.request('cursor_sale_commit',bag=0,slot=slot)
            self.last_update=0.;self.update(transaction)
        return transaction

    def _reconcile_cursor(self):
        """A drag held across a repaint must still name the same physical item."""
        previous=getattr(self,'_shown_gameplay',None)
        if previous is None:return
        source=self.lua.request('cursor_source')
        if not source:return
        current=self.gameplay_views
        if source['kind']=='merchant':
            slot=source['row'];before=previous.merchant.buy_refs.get(slot)
            changed=not before or previous.merchant.vendor_id!=current.merchant.vendor_id or before!=current.merchant.buy_refs.get(slot)
        else:
            def ref(views):
                bag=source['bag'];slot=source['slot']
                if bag==0:return views.inventory_refs.get(slot)
                if bag==-1:return views.bank.bank_refs.get(slot)
                if bag==-100:return views.equipment_refs.get(slot)
                return None
            before=ref(previous);changed=not before or before!=ref(current)
        if changed:self.lua.request('cursor_clear')

    def _sound_request(self,sound):
        if not self.audio:return
        if self.zone_audio:
            if not self.zone_audio.sound(sound):self._unsupported('World sound request could not be queued')
            return
        kits={'GG_UI_CLICK':3,'igMainMenuOption':3,'igMainMenuOpen':3,'igMainMenuClose':3}
        if sound.get('kit') in kits:self.audio.play(kits[sound['kit']],gain=.4);return
        if sound.get('file'):
            self.short_sounds.play(self.sound_assets.resolve(sound['file']));return
        if sound.get('kit') is not None:
            try:
                self.sound_assets.resolve('DBFilesClient/SoundEntries.dbc')
                if self.sound_assets.archive_source:
                    kit=self.sound_assets._reader().request('sound_kit',kit=sound['kit']);files=kit['files']
                    if not files:return
                    weights=[max(0,int(weight)) for path,weight in files]
                    remaining=self.sound_pick.setdefault(kit['id'],weights.copy())
                    if len(remaining)!=len(weights) or not sum(remaining):remaining=weights.copy();self.sound_pick[kit['id']]=remaining
                    total=sum(remaining);choice=0
                    if total:
                        draw=self.sound_random.getrandbits(32)%total
                        for i,weight in enumerate(remaining):
                            if draw<weight:choice=i;remaining[i]-=1;break
                            draw-=weight
                    path=files[choice][0]
                    flags=kit['flags'];gain=max(0,min(1,kit['volume']))
                    if flags&0x800:gain=max(0,min(1,gain+(((self.sound_random.getrandbits(32)*31)>>32)-15)*.01))
                    frequency=(22050*(((self.sound_random.getrandbits(32)*31)>>32)+85))//100 if flags&0x400 else None
                    self.short_sounds.play(self.sound_assets.resolve(path),gain=gain,bus=1 if kit['sound_type']==28 else 2 if kit['sound_type']==50 else 0,loop=bool(flags&0x200),frequency=frequency,unique=kit['id'] if flags&0x20 else None);return
            except ValueError as exc:
                self._unsupported('Sound kit: '+str(exc));return
        self._unsupported('Sound kit: '+str(sound.get('kit')))

    def _pump_short_sounds(self):
        if not self.short_sounds:return
        self.short_sounds.pump()
        for message in self.short_sounds.errors:self._error(RuntimeError(message))
        self.short_sounds.errors.clear()

    def _unsupported(self,text):
        if text not in self.unsupported_requests:self.unsupported_requests=(self.unsupported_requests+[text[:200]])[-32:]

    def _game_requests(self,requests):
        if getattr(self,'_draining_requests',False):return
        self._draining_requests=True
        try:self._dispatch_game_requests(requests)
        finally:self._draining_requests=False

    def run_macro(self,index):
        """Original per-line event route, with a finite synchronous intent chain."""
        if not self.full_ui or not self.lua:return {'error':'MACRO_UI_UNAVAILABLE'}
        stack=getattr(self,'_macro_stack',[]);outer=not stack
        if outer:self._macro_budget=256;self._macro_error=None
        if index in stack or len(stack)>=8:
            self._macro_error='MACRO_RECURSION_LIMIT';self.lua.event('UI_ERROR_MESSAGE',self._macro_error)
            return {'error':self._macro_error}
        packet=self.lua.request('macros');self._macro_views(packet)
        macro=self.gameplay_views.macros.get(index)
        if not macro:return {'error':'MACRO_NOT_FOUND'}
        lines=[line.strip() for line in macro['body'].replace('\r','\n').split('\n') if line.strip()]
        if not lines:return {'error':'MACRO_EMPTY'}
        self._macro_stack=stack+[index]
        try:
            for line in lines:
                if self._macro_error:break
                if self._macro_budget<=0:
                    self._macro_error='MACRO_INTENT_LIMIT';break
                self._macro_budget-=1
                result=self.lua.request('macro_line',line=line,timeout=1)
                requests=self.lua.request('requests')
                self.client_tools.flags(requests.get('client_tools'))
                self._media_requests(requests)
                self._dispatch_game_requests(requests)
                self.client_tools.requests(requests.get('client_tools'))
                self.graphics.requests(requests)
                self._nameplate_mode(requests)
                if result.get('fallback'):self._macro_local_line(result['fallback'])
            if self._macro_error:
                self.lua.event('UI_ERROR_MESSAGE',self._macro_error)
                return {'error':self._macro_error}
            return {'ok':True,'macro_index':index,'lines':len(lines)}
        except (ValueError,RuntimeError,TimeoutError) as exc:
            self._macro_error='MACRO_SCRIPT_FAILED'
            # Requests queued before a Lua error belong to this failed chain.
            # They must not reappear on a later frame outside its depth limit.
            try:self.lua.request('requests')
            except (ValueError,RuntimeError,TimeoutError):pass
            self._error(exc);self.lua.event('UI_ERROR_MESSAGE','Macro: '+str(exc)[:180])
            return {'error':'MACRO_SCRIPT_FAILED'}
        finally:self._macro_stack=stack

    def _macro_views(self,packet):
        if not isinstance(packet,dict):return
        self.gameplay_views.macros={int(row['index']):dict(row) for row in packet.get('rows',[])[:36]}
        rows=[{'index':r['index'],'name':r['name'],'texture':r.get('texture'),
            'ability':self.gameplay_views.spell_refs.get(r.get('bound_spell')),
            'unresolved':r.get('bound_spell',0)==-1} for r in self.gameplay_views.macros.values()]
        call=getattr(self.parent(),'gameEngineMacroState',None)
        if callable(call) and getattr(self,'_sent_macros',None)!=rows:
            result=call(json.dumps(rows,ensure_ascii=False))
            if isinstance(result,str):result=json.loads(result)
            if isinstance(result,dict) and result.get('error'):self._error(ValueError(result['error']))
            else:self._sent_macros=rows

    def _macro_local_line(self,line):
        line=line.strip()
        if not line:return
        parts=line.split(None,1);command=parts[0].casefold();args=parts[1].strip() if len(parts)>1 else ''
        method=None;values=();control=None
        if not line.startswith('/'):
            control={'kind':'local','op':'Chat','text':line,'chat_type':'SAY'}
        elif command=='/use':
            rows=self.gameplay_views.items.get('inventory',[])
            row=next((r for r in rows if args.casefold() in (str(r.get('name','')).casefold(),str(r.get('definition_id','')).casefold())),None)
            if row:method='gameEngineContainerUseItem';values=(row['definition_id'],row['instance_id'])
        elif command=='/attack':method='gameEngineActionCommand';values=('ATTACK',)
        elif command=='/cleartarget':control={'kind':'player','op':'Clear'}
        elif command in ('/targetnearest','/targetenemy','/targetfriend'):
            control={'kind':'player','op':'Nearest','mode':'Friend' if command=='/targetfriend' else 'Enemy','reverse':args=='1'}
        elif command in ('/target','/targetexact') and args:
            control={'kind':'player','op':'ByName','name':args,'exact':command=='/targetexact'}
        elif command in ('/assist','/follow'):
            control={'kind':'player','op':('AssistByName' if command=='/assist' else 'FollowByName') if args else ('Assist' if command=='/assist' else 'Follow')}
            control['name' if args else 'unit']=args or 'target'
        elif command in ('/targetlasttarget','/targetlastenemy','/stopfollow'):
            control={'kind':'player','op':{'/targetlasttarget':'LastTarget','/targetlastenemy':'LastEnemy','/stopfollow':'StopFollow'}[command]}
        elif command in ('/stand','/sleep','/kneel'):
            control={'kind':'player','op':'Stand','state':{'/stand':0,'/sleep':3,'/kneel':8}[command]}
        elif command in ('/sit','/sheathe','/walk','/run','/autorun'):
            control={'kind':'input','op':'Fire','key':{'/sit':'SitOrStand','/sheathe':'ToggleSheath','/walk':'ToggleRun','/run':'ToggleRun','/autorun':'ToggleAutoRun'}[command]}
        elif command in ('/say','/s','/yell','/y','/emote','/e'):
            control={'kind':'local','op':'Chat','text':args,'chat_type':{'/say':'SAY','/s':'SAY','/yell':'YELL','/y':'YELL','/emote':'EMOTE','/e':'EMOTE'}[command]}
        elif command in ('/whisper','/w','/tell','/t'):
            recipient,_,text=args.partition(' ')
            control={'kind':'local','op':'Chat','text':text.strip(),'chat_type':'WHISPER','target':recipient}
        elif command in ('/pvp','/played'):control={'kind':'local','op':'Pvp' if command=='/pvp' else 'Played'}
        elif command in ('/roll','/random'):
            try:
                bounds=[int(n) for n in args.split()] if args else [1,100]
                if len(bounds)==1:bounds=[1,bounds[0]]
                if len(bounds)!=2:raise ValueError('two roll bounds required')
                control={'kind':'local','op':'Roll','low':bounds[0],'high':bounds[1]}
            except ValueError:
                self._macro_error='MACRO_INVALID_ROLL';return
        if control is not None:method='gameEngineClientControl';values=(json.dumps(control,ensure_ascii=False),)
        call=getattr(self.parent(),method,None) if method else None
        if not callable(call):
            self._macro_error='MACRO_COMMAND_UNSUPPORTED'
            self._unsupported('GG macro line: '+line[:200]);return
        result=call(*values)
        if isinstance(result,str):result=json.loads(result)
        if isinstance(result,dict) and result.get('error'):self.lua.event('UI_ERROR_MESSAGE',str(result['error'])[:200])
        if isinstance(result,dict):
            self._publish_committed_ui(result)
        if isinstance(result,dict) and isinstance(result.get('player'),dict):
            self._request_snapshot=result;self.gameplay_views.update(result)

    def _dispatch_game_requests(self,requests):
        self._macro_views(requests.get('macros'))
        if getattr(self,'_macro_stack',[]):
            count=sum(len(value) for key,value in requests.items() if isinstance(value,list) and key not in ('sounds','music'))
            if count>self._macro_budget:
                self._macro_error='MACRO_INTENT_LIMIT';return
            self._macro_budget-=count
        host=self.parent()
        cursor=requests.get('cursor')
        if isinstance(cursor,dict):
            mode=cursor.get('override') or ('Repair' if cursor.get('repair') else 'Point')
            if mode!=getattr(self,'_cursor_mode',None):
                self._cursor_mode=mode
                if self._canvas:self._canvas.setCursorMode(mode)
        missing=requests.get('unimplemented',[])
        if missing:
            # Every original queue is accounted for. Missing gameplay must
            # report failure and cannot accumulate/replay on a future tick.
            for row in missing[:128]:self._unsupported('Required GgEngine host: '+str(row.get('method',''))[:128])
            self.lua.event('UI_ERROR_MESSAGE','Den här funktionen saknar ännu en spelkoppling i den lokala världen.')
        # Requests refer to the rows shown when the worker queued them.
        # Refreshing eligibility after a purchase must never reinterpret a
        # second queued row as a different physical product.
        from copy import copy
        shown=getattr(self,'_shown_gameplay',self.gameplay_views)
        merchant_requests=copy(shown.merchant)
        bank_requests=copy(shown.bank)
        quest_requests=copy(shown.quest)
        local_requests=copy(shown.local)
        service_requests=copy(shown.services)
        inventory_sources=dict(shown.inventory_refs)
        chat_lines=requests.get('chat_input',[])
        if isinstance(chat_lines,list) and len(chat_lines)<=64:
            for line in chat_lines:
                if isinstance(line,str) and len(line)<=255 and not any(c in line for c in ('\0','\r','\n')):self._macro_local_line(line)
                else:self.lua.event('UI_ERROR_MESSAGE','Ogiltig chattrad.')
        else:self.lua.event('UI_ERROR_MESSAGE','För många chattrader; inga rader utfördes.')
        talent_sources=dict(shown.talent_refs)
        def dispatch(method,*args):
            call=getattr(host,method,None)
            if not callable(call):self._unsupported(method);return
            try:
                result=call(*args)
                if isinstance(result,str):result=json.loads(result)
                if isinstance(result,dict) and result.get('error'):self.lua.event('UI_ERROR_MESSAGE',str(result['error'])[:200])
                if isinstance(result,dict):
                    self._publish_committed_ui(result)
                # A second intent in this drain sees the first transaction's
                # real destinations and remaining stock, without nested ticks.
                if isinstance(result,dict) and all(isinstance(result.get(k),dict) for k in ('items','bank','merchant')):
                    self.gameplay_views.update(result)
                    if isinstance(result.get('player'),dict):self._request_snapshot=result
                return result
            except (TypeError,ValueError,RuntimeError) as exc:self._error(exc)
        def route(planner,*args):
            try:
                plan=planner(*args)
                if plan:return dispatch(plan['method'],*plan['args'])
            except ValueError as exc:
                self._unsupported(str(exc));self.lua.event('UI_ERROR_MESSAGE',str(exc)[:200])
        controls=[dict(row,kind='camera') for row in requests.get('camera_views',[])[:128]]
        controls += [dict(row,kind='input') for row in requests.get('binding_input',[])[:128]]
        controls += [{'kind':'worn','op':op} for op in requests.get('worn_display',[])[:128]]
        if sum(len(requests.get(k,[])) for k in ('camera_views','binding_input','worn_display'))>128:
            dispatch('gameEngineClientControl',json.dumps({'kind':'input','op':'Cancel'}));self._unsupported('GG client control capacity exceeded')
        elif controls:dispatch('gameEngineClientControls',json.dumps(controls))
        for row in requests.get('follows',[])[:64]:dispatch('gameEngineClientControl',json.dumps(dict(row,kind='player')))
        for row in requests.get('nameplates',{}).get('clicks',[])[:64]:
            identity=row.get('id','')
            if row.get('button')=='RightButton':dispatch('gameEngineWorldContext',identity)
            elif row.get('button')=='LeftButton':dispatch('gameEngineClientControl',json.dumps(dict(kind='player',op='Select',unit=identity)))
        for row in requests.get('emotes',[])[:64]:
            posture={'SIT':1,'STAND':0,'SLEEP':3,'KNEEL':8}.get(str(row.get('token','')).upper())
            if posture is not None:dispatch('gameEngineClientControl',json.dumps({'kind':'player','op':'Stand','state':posture}))
            else:self.lua.event('CHAT_MSG_TEXT_EMOTE',str(row.get('token',''))[:128],str(self.snapshot.get('player',{}).get('name','Gold Goblin')))
        for row in requests.get('local_client',[])[:128]:
            if row.get('op')=='MinimapPing':
                from backend.game_engine_adapter_minimap import route_ping
                route_ping(self,row,dispatch)
            else:
                intent=dict(row,kind='local')
                service_requests.freeze_channel(intent)
                dispatch('gameEngineClientControl',json.dumps(intent))
        if len(requests.get('local_client',[]))>128:self.lua.event('UI_ERROR_MESSAGE','För många lokala klientkommandon.')
        service_rows=requests.get('services',[])
        if len(service_rows)>128:
            self.lua.event('UI_ERROR_MESSAGE','För många tjänstekommandon; inga affärer genomfördes.')
        else:
            for row in service_rows:
                try:
                    if row.get('op')=='InventoryDropOnUnit' and self.lua.evaluate('return CursorHasItem()')!=[1]:continue
                    result=dispatch('gameEngineClientControl',json.dumps(service_requests.route(row,inventory_sources,shown.equipment_refs)))
                    if isinstance(result,dict) and not result.get('error') and row.get('op')=='InventoryDropOnUnit':self.lua.request('cursor_clear')
                    if isinstance(result,dict) and not result.get('error') and row.get('op') in ('AuctionStart','MailSend'):
                        self.lua.request('auction_sell_clear' if row['op']=='AuctionStart' else 'mail_compose_clear')
                except ValueError as exc:self.lua.event('UI_ERROR_MESSAGE',str(exc))
        for slot,packed in requests.get('action_sets',[])[:240]:
            if not 1<=slot<=120:self._unsupported('GG action slot outside original 120 slots');continue
            if packed==0:entry={'kind':'EMPTY'}
            else:
                ref=self.gameplay_views.action_refs.get((packed>>24,packed&0xffffff))
                if not ref:self._unsupported('Unknown GG packed action');continue
                entry={'kind':ref[0],'ref':ref[1]}
            dispatch('gameEngineActionBarEdit',json.dumps({'index':slot-1,**entry}))
        if len(requests.get('action_sets',[]))>240:self._unsupported('Action edit capacity exceeded')
        for call in requests.get('calls',[])[:64]:
            op=call['op']
            if op=='action':
                slot=int(call['index']);rows=self.gameplay_views.update(getattr(self,'_request_snapshot',None) or self.snapshot)['actions']
                entry=next((r for r in rows if r.get('index')==slot),{})
                if entry.get('kind')=='MACRO':
                    result=self.run_macro(int(entry['ref']))
                    if result.get('error'):self.lua.event('UI_ERROR_MESSAGE',result['error'])
                else:dispatch('gameEngineActionUse',slot)
            elif op=='clear':dispatch('gameEngineClientControl',json.dumps({'kind':'player','op':'Clear'}))
            elif op=='attack':dispatch('gameEngineActionCommand','ATTACK')
            elif op=='stop_cast':
                dispatch('gameEngineClientControl',json.dumps(dict(kind='spell',op='Stop')))
                dispatch('gameEngineClientControl',json.dumps(dict(kind='service',op='StuckCancel',session=service_requests.value.get('session',-1))))
                if callable(getattr(host,'gameEngineCraftingStop',None)):dispatch('gameEngineCraftingStop')
            elif op=='spell':
                ref=self.gameplay_views.spell_refs.get(int(call['spell_id']))
                if ref:
                    spell=self.gameplay_views.spells.get(ref,{})
                    if call.get('on_self') and spell.get('ability_kind') in ('SPELL','FORM'):
                        dispatch('gameEngineClientControl',json.dumps(dict(kind='spell',op='Cast',ref=ref,on_self=True)))
                    else:dispatch('gameEngineAbility',ref)
                else:self._unsupported('Unknown GG ability')
            elif op=='container':
                if merchant_requests.opened:
                    route(merchant_requests.route_sell,call['bag'],call['slot'],inventory_sources)
                elif bank_requests.opened:
                    route(bank_requests.route_use,call['bag'],call['slot'],inventory_sources)
                elif call['bag']==0:
                    ref=inventory_sources.get(int(call['slot']))
                    if ref:dispatch('gameEngineContainerUseItem',*ref)
                    else:self._unsupported('Unknown GG inventory slot')
                else:self._unsupported('Unknown GG container')
            elif op in ('nearest','select','by_name','assist','assist_name','last_target','last_enemy'):
                command={'nearest':'Nearest','select':'Select','by_name':'ByName','assist':'Assist','assist_name':'AssistByName','last_target':'LastTarget','last_enemy':'LastEnemy'}[op]
                dispatch('gameEngineClientControl',json.dumps(dict(call,kind='player',op=command)))
            elif op=='stop_targeting':
                dispatch('gameEngineClientControl',json.dumps(dict(kind='spell',op='StopTargeting')))
                if service_requests.value.get('item_targeting',{}).get('active'):
                    dispatch('gameEngineClientControl',json.dumps(service_requests.route({'op':'EnchantCancel'},inventory_sources,shown.equipment_refs)))
                self.lua.request('cursor_clear')
            elif op=='spell_target':
                dispatch('gameEngineClientControl',json.dumps(dict(kind='spell',op='Target',unit=call.get('unit',''))))
            elif op in ('pet_spell','pet_action','pet_order'):
                command={'pet_action':{'op':'PetAction','slot':call.get('slot')},
                         'pet_order':{'op':'PetOrder','word':call.get('word')},
                         'pet_spell':{'op':'PetSpell','spell_id':call.get('spell_id')}}[op]
                dispatch('gameEngineClientControl',json.dumps(dict(command,kind='service')))
            elif op=='form':
                ref=self.gameplay_views.spell_refs.get(int(call['spell_id']))
                if ref:dispatch('gameEngineAbility',ref)
                else:self.lua.event('UI_ERROR_MESSAGE','Den här formen finns inte i karaktärens förmågebok.')
            elif op=='inventory':
                instance=shown.equipment_refs.get(int(call['slot']))
                item=next((r for r in self.gameplay_views.items.get('equipment',[]) if r.get('instance_id')==instance),None)
                if item:dispatch('gameEngineContainerUseItem',item['definition_id'],instance)
                else:self.lua.event('UI_ERROR_MESSAGE','Ingen utrustning på den platsen.')
            else:self._unsupported('Call: '+str(call))
        if len(requests.get('calls',[]))>64:self._unsupported('Script call capacity exceeded')
        for row,quantity in requests.get('merchant_buys',[])[:64]:
            route(merchant_requests.route_buy,row,quantity)
        sales=requests.get('merchant_sells',[])
        sale_counts=requests.get('merchant_sale_counts')
        sale_metadata_ok=(sale_counts is None or isinstance(sale_counts,list) and len(sale_counts)==len(sales)
            and all(isinstance(row,list) and len(row)==3 and row[:2]==source
                    and type(row[2]) is int and 0<=row[2]<=999 for row,source in zip(sale_counts,sales)))
        if not sale_metadata_ok:
            self._unsupported('Merchant sale metadata changed');self.lua.event('UI_ERROR_MESSAGE','Merchant sale metadata changed')
        else:
            for index,(bag,slot) in enumerate(sales[:64]):
                count=sale_counts[index][2] if sale_counts is not None else 0
                result=route(merchant_requests.route_sell,bag,slot,inventory_sources,count)
                if sale_counts is not None:
                    ref=inventory_sources.get(slot) if bag==0 else None
                    unchanged=ref is not None and self.gameplay_views.inventory_refs.get(slot)==ref
                    item=next((row for row in self.gameplay_views.items.get('inventory',[]) if ref and row.get('instance_id')==ref[1]),{})
                    amount_available=not count or count<=int(item.get('quantity',0))
                    failed=not isinstance(result,dict) or bool(result.get('error'))
                    self.lua.request('merchant_sale_finish',index=index,restore=failed and unchanged and amount_available)
        if any(len(requests.get(key,[]))>64 for key in ('merchant_buys','merchant_sells')):self._unsupported('Merchant request capacity exceeded')
        for bag,slot,entry in requests.get('merchant_slot_buys',[])[:64]:route(merchant_requests.route_buy_slot,bag,slot,entry)
        for row in requests.get('merchant_buybacks',[])[:64]:route(merchant_requests.route_buyback,row)
        for bag,slot in requests.get('container_repairs',[])[:64]:
            source=inventory_sources.get(slot) if bag==0 else None
            if source:route(merchant_requests.route_repair,source[1])
            else:self.lua.event('UI_ERROR_MESSAGE','Unknown GG repair bag slot')
        for slot in requests.get('inventory_repairs',[])[:24]:
            source=shown.equipment_refs.get(slot)
            if source:route(merchant_requests.route_repair,source)
            else:self.lua.event('UI_ERROR_MESSAGE','Unknown GG repair equipment slot')
        if requests.get('repair_all'):route(merchant_requests.route_repair)
        if any(len(requests.get(key,[]))>64 for key in ('merchant_slot_buys','merchant_buybacks','container_repairs','inventory_repairs')):self._unsupported('Merchant request capacity exceeded')
        from backend.game_engine_adapter_gameplay import EQUIPMENT_NAMES
        for move in requests.get('item_moves',[])[:64]:
            if -1 in (move['src_bag'],move['dst_bag']):
                before=bank_requests.bank_refs if move['src_bag']==-1 else inventory_sources
                current=self.gameplay_views.bank.bank_refs if move['src_bag']==-1 else self.gameplay_views.inventory_refs
                if before.get(move['src_slot'])!=current.get(move['src_slot']):
                    self._unsupported('GG queued bank source changed');self.lua.event('UI_ERROR_MESSAGE','GG queued bank source changed');continue
                route(self.gameplay_views.bank.route,move,self.gameplay_views.inventory_refs)
                continue
            source=inventory_sources.get(int(move['src_slot'])) if move['src_bag']==0 else None
            if source and source!=self.gameplay_views.inventory_refs.get(int(move['src_slot'])):
                self._unsupported('GG queued inventory source changed');self.lua.event('UI_ERROR_MESSAGE','GG queued inventory source changed');continue
            if move.get('count') is not None:
                if source and move['dst_bag']==0 and 1<=move['dst_slot']<=64:dispatch('gameEngineInventoryStack',source[1],int(move['dst_slot'])-1,int(move['count']))
                else:self._unsupported('GG split-stack destination: '+str(move))
                continue
            if source and move['dst_bag']==-100 and move['dst_slot'] in EQUIPMENT_NAMES:
                dispatch('gameEngineItemEquip',source[1],EQUIPMENT_NAMES[move['dst_slot']])
            elif source and move['dst_bag']==0 and 1<=move['dst_slot']<=64:
                dispatch('gameEngineInventoryMove',source[1],int(move['dst_slot'])-1)
            elif move['src_bag']==-100 and move['dst_bag']==0 and 1<=move['dst_slot']<=64:
                worn=shown.equipment_refs.get(int(move['src_slot']))
                if worn!=self.gameplay_views.equipment_refs.get(int(move['src_slot'])):
                    self._unsupported('GG queued equipment source changed');self.lua.event('UI_ERROR_MESSAGE','GG queued equipment source changed');continue
                if worn:dispatch('gameEngineEquipmentMove',worn,int(move['dst_slot'])-1)
                else:self._unsupported('Unknown GG equipment source')
            else:self._unsupported('GG item cursor move: '+str(move))
        for bag,slot in requests.get('autoequips',[])[:64]:
            source=inventory_sources.get(int(slot)) if bag==0 else None
            if source and source!=self.gameplay_views.inventory_refs.get(int(slot)):
                self._unsupported('GG queued autoequip source changed');self.lua.event('UI_ERROR_MESSAGE','GG queued autoequip source changed');continue
            if source:dispatch('gameEngineItemEquip',source[1],'')
            else:self._unsupported('Unknown GG autoequip source')
        if len(requests.get('item_moves',[]))>64 or len(requests.get('autoequips',[]))>64:self._unsupported('GG item move capacity exceeded')
        for row in requests.get('gossip_selects',[])[:32]:route(quest_requests.gossip,row)
        for row in requests.get('gossip_quests',[])[:32]:route(quest_requests.select,row)
        for row in requests.get('quest_selects',[])[:32]:route(quest_requests.select,row['index'],row['active'])
        for row in requests.get('quest_actions',[])[:32]:route(quest_requests.action,row['op'],row.get('choice',0))
        for key in requests.get('quest_abandons',[])[:20]:route(quest_requests.abandon,key)
        if requests.get('gossip_close'):dispatch('gameEngineGossipClose')
        for key in requests.get('quest_shares',[])[:20]:
            ref=quest_requests.log.get(key) if type(key) is int else None
            if ref:dispatch('gameEngineClientControl',json.dumps({'kind':'service','op':'QuestShare','quest':ref,'session':service_requests.value.get('session',-1)}))
            else:self.lua.event('UI_ERROR_MESSAGE','QUEST_NOT_SHOWN')
        if requests.get('quest_confirms'):dispatch('gameEngineClientControl',json.dumps({'kind':'service','op':'QuestShareConfirm','session':service_requests.value.get('session',-1)}))
        if any(len(requests.get(key,[]))>32 for key in ('gossip_selects','gossip_quests','quest_selects','quest_actions','quest_abandons')):self._unsupported('Quest request capacity exceeded')
        if requests.get('bank_close'):dispatch('gameEngineBankClose')
        if requests.get('merchant_close'):dispatch('gameEngineMerchantClose')
        if requests.get('bank_purchase'):self._unsupported('GG bank has fixed capacity; purchasing bag slots is not implemented')
        for tab,index in requests.get('talent_learns',[])[:32]:
            ref=talent_sources.get((tab,index))
            if ref:dispatch('gameEngineTalent',ref)
            else:self.lua.event('UI_ERROR_MESSAGE','TALENT_UNKNOWN')
        if requests.get('talent_wipes'):dispatch('gameEngineClientControl',json.dumps({'kind':'player','op':'Respec'}))
        if len(requests.get('talent_learns',[]))>32:self._unsupported('GG talent request capacity exceeded')
        for spell in requests.get('craft_dos',[])[:32]:route(local_requests.craft,spell)
        for spell,count in requests.get('trade_skill_dos',[])[:32]:route(local_requests.craft,spell,count)
        if requests.get('craft_close') or requests.get('trade_skill_close'):route(local_requests.close_craft)
        for slot in requests.get('loot_picks',[])[:64]:route(local_requests.loot,slot)
        if requests.get('loot_close'):route(local_requests.close_loot)
        for slot in requests.get('loot_confirms',[])[:64]:route(local_requests.loot_confirm,slot)
        for slot,candidate in requests.get('loot_master_gives',[])[:64]:route(local_requests.master_loot,slot,candidate)
        if any(len(requests.get(key,[]))>32 for key in ('craft_dos','trade_skill_dos')):self._unsupported('GG crafting intent capacity exceeded')
        if len(requests.get('loot_picks',[]))>64:self._unsupported('GG loot intent capacity exceeded')
        for request in requests.get('session',[])[:8]:
            characters=getattr(host,'_local_characters',None)
            if request in ('Logout','ForceLogout'):
                if characters and characters.active_id:
                    if not characters.logout():self.lua.event('UI_ERROR_MESSAGE',characters.error[:200])
                else:dispatch('gameEnginePause')
            elif request=='CancelLogout':
                if characters and characters.phase!='WORLD':self.lua.event('UI_ERROR_MESSAGE','LOCAL_CHARACTER_REQUIRED')
                else:dispatch('gameEngineStart')
            elif request in ('Quit','ForceQuit'):dispatch('gameEngineRequestClose')
            elif request=='ReloadUi':self._reload_ui()
            elif request=='StopCinematic':dispatch('gameEngineClientControl',json.dumps(dict(kind='service',op='CinematicStop')))
            else:self._unsupported('Session: '+request)

    def _reload_ui(self):
        # Rebuild only the game Lua VM; the desktop/chat process stays alive.
        if not self.full_ui or not self.lua:return False
        snapshot=self.snapshot if isinstance(self.snapshot.get('player'),dict) else None
        return self._replace_ui(self.character_key,local_mode=self.local_character_mode,initial_snapshot=snapshot)

    def _movement(self,player):
        pos=tuple(float(player.get(k,0)) for k in ('x','z','time_s'))
        if self.entity_audio.player_claimed:
            self.step_distance=0.;self.last_position=pos;return
        if self.last_position and self.running and player.get('grounded',False) and str(player.get('vehicle','NONE'))=='NONE':
            dx,dz,dt=(pos[i]-self.last_position[i] for i in range(3));distance=math.hypot(dx,dz)
            if 0<dt<=.5 and distance<5:
                self.step_distance+=distance
                if self.step_distance>=1.4:
                    self.step_distance=math.fmod(self.step_distance,1.4)
                    clip=2 if str(player.get('medium','')).upper() in ('WATER','WADING') else 0 if str(player.get('biome','')).upper() in ('FOREST','GRASSLAND','MEADOW') else 1
                    self.audio.play(clip,position=tuple(float(player.get(k,0)) for k in ('x','y','z')),gain=.55,reverb=True)
            else:self.step_distance=0
        self.last_position=pos

    @Property(str,notify=uiChanged)
    def framesJson(self):return self._frames
    @Property(QObject,constant=True)
    def framesModel(self):return self._frame_model
    @Property(QObject,constant=True)
    def worldActors(self):return self.world_actors
    @Property(bool,notify=textureSettingsChanged)
    def textureTrilinear(self):return self.runtime_settings['trilinear']=='1'
    @Property(bool,constant=True)
    def engineUiEnabled(self):return self.full_ui
    @Slot(QObject,bool)
    def attachCanvas(self,item,standalone):
        if not self.full_ui:return
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        # Keep the QML parent wrapper alive alongside its Python canvas.
        self._canvas_parent=item
        self._canvas=GgEngineCanvas(self,item,0 if standalone else 174);self._canvas.sync(self.lua.rows)
        self._canvas.setCursorMode(getattr(self,'_cursor_mode','Point'))
        self.graphics.attach(standalone)
    @Property(str,notify=audioChanged)
    def audioJson(self):return self._audio_json
    def _publish_client_controls(self,snapshot):
        controls=snapshot.get('player',{}).get('client_controls')
        if not isinstance(controls,dict):return
        value=json.dumps(controls,allow_nan=False,separators=(',',':'))
        if value!=self._client_controls_json:self._client_controls_json=value;self.clientControlsChanged.emit()
    @Property(str,notify=clientControlsChanged)
    def clientControlsJson(self):return self._client_controls_json
    @Property('QVariantList',notify=clientControlsChanged)
    def nameplateSubjects(self):
        if not self.full_ui or not self._nameplate_bits:return []
        services=self.snapshot.get('player',{}).get('client_controls',{}).get('services',{})
        members=services.get('group',{}).get('members',[])
        return [dict(p) for p in services.get('people',[]) if p.get('online') and p.get('health',0)>0
                and p.get('distance_sq',1e12)<=400 and self._nameplate_bits & (8 if p.get('id') in members else 1)][:64]
    @Property('QVariantList',notify=clientControlsChanged)
    def worldFeedbackSubjects(self):
        if not self.full_ui:return []
        controls=self.snapshot.get('player',{}).get('client_controls',{})
        rows=[]
        for item in controls.get('world_feedback',[])[:112]:
            if item.get('kind')=='BUBBLE':
                switch='ChatBubblesParty' if item.get('channel')=='PARTY' else 'ChatBubbles'
                if self.runtime_settings[switch]!='1':continue
                # The original plate/bubble slot is exclusive.
                person=next((p for p in controls.get('services',{}).get('people',[]) if p['id']==item.get('actor')),None)
                if person:
                    friends=controls.get('services',{}).get('group',{}).get('members',[])
                    if self._nameplate_bits & (8 if person['id'] in friends else 1):continue
            rows.append(dict(item))
        from backend.game_engine_adapter_minimap import quest_signals
        signals=quest_signals(self.snapshot)
        for person in controls.get('services',{}).get('people',[])[:64]:
            marker=signals.get(person['id'])
            if marker and person.get('online') and person.get('health',0)>0 and person.get('distance_sq',1e12)<=3600:
                rows.append(dict(id='quest:'+person['id'],kind='QUEST',actor=person['id'],text=marker,
                    x=person['x'],y=person['y']+2.5,z=person['z'],alpha=1.,age=0.))
        return rows[:176]
    @Property(bool,notify=nameplatesChanged)
    def nameplatesEnabled(self):return self.full_ui and bool(self._nameplate_bits)
    @Slot('QVariantList',bool,bool)
    def updateNameplates(self,rows,freelook,targeting):
        if not self.full_ui or not self.lua or self.lua.closed:return
        if len(rows)>64:self._error(ValueError('Nameplate projection capacity exceeded'));return
        # Leave the QML camera callback before updating painter/model state or
        # emitting UI signals. Only the newest camera projection is retained.
        self._nameplate_pending=(rows,freelook,targeting)
        if not self._nameplate_scheduled:
            self._nameplate_scheduled=True;QTimer.singleShot(0,self._drive_nameplates)
    def _drive_nameplates(self):
        self._nameplate_scheduled=False;pending=self._nameplate_pending;self._nameplate_pending=None
        if not pending or not self.full_ui or not self.lua or self.lua.closed:return
        rows,freelook,targeting=pending
        try:
            self._nameplate_report=self.lua.request('nameplates',rows=rows,freelook=freelook,targeting=targeting)
            self._nameplate_report['projected']=len(rows)
            self._update_frames()
        except (ValueError,RuntimeError,TimeoutError) as exc:self._error(exc)
    @Property(str,notify=addonsChanged)
    def addonsJson(self):return self._addon_json

    @Slot()
    def refreshAddons(self):
        rows=[];can_edit=False;choices={}
        try:
            if self.full_ui and self.lua:
                rows=self.lua.request('addon_status')
                can_edit=self.lua.saving_enabled and not (self.local_character_mode and self.character_key is None)
                if self.lua.character_saved_root and self.lua.character_saved_root/'addons.json' in self.lua.held_saves:
                    can_edit=False
                    self._addon_error='Tilläggsinställningarna kunde inte läsas. Filen har bevarats.'
                if self._addon_editor:choices=self._addon_editor.view(rows);rows=choices.pop('rows')
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:self._error(exc)
        value=json.dumps({'rows':rows,'can_edit':can_edit,'generation':self._ui_generation,
                          'error':self._addon_error,'can_select_characters':bool(getattr(self.lua,'_addon_roster_context',None)),**choices},ensure_ascii=False)
        if value!=self._addon_json:self._addon_json=value;self.addonsChanged.emit()

    @Slot(int,result=bool)
    def beginAddonChoices(self,generation):
        try:
            if generation!=self._ui_generation or not self.lua or not self.lua.saving_enabled:raise ValueError('Addon list changed')
            self.lua.save()
            from backend.game_engine_adapter_addon_choices import AddonChoices
            self._addon_editor=AddonChoices(self.lua);self._addon_error='';self.refreshAddons();return True
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:self._addon_error=str(exc)[:160];self.refreshAddons();return False

    @Slot(str,int,result=bool)
    def selectAddonCharacter(self,identity,generation):
        try:
            if generation!=self._ui_generation or not self._addon_editor:raise ValueError('Addon list changed')
            self._addon_editor.select(identity);self.refreshAddons();return True
        except (OSError,ValueError) as exc:self._addon_error=str(exc)[:160];self.refreshAddons();return False

    @Slot(str,bool,int,result=bool)
    def stageAddonChoice(self,name,enabled,generation):
        try:
            if generation!=self._ui_generation or not self._addon_editor:raise ValueError('Addon list changed')
            self._addon_editor.set(name,enabled);self._addon_error='';self.refreshAddons();return True
        except (OSError,ValueError) as exc:self._addon_error=str(exc)[:160];self.refreshAddons();return False

    @Slot(bool,int,result=bool)
    def finishAddonChoices(self,save,generation):
        try:
            if generation!=self._ui_generation:raise ValueError('Addon list changed')
            if self._addon_editor and save:self._addon_editor.save()
            self._addon_editor=None;self._addon_error='';self.refreshAddons();return True
        except (OSError,ValueError) as exc:self._addon_error=str(exc)[:160];self.refreshAddons();return False

    @Slot(str,bool,int,result=bool)
    def setAddon(self,name,enabled,generation):
        try:
            if (generation!=self._ui_generation or not self.full_ui or not self.lua
                    or not self.lua.saving_enabled or self.local_character_mode and self.character_key is None):
                raise ValueError('Välj en karaktär och öppna tilläggslistan igen.')
            rows=self.lua.request('addon_status')
            if not any(r['id']==name for r in rows):raise ValueError('Tillägget finns inte i den aktuella listan.')
            self.lua.request('addon_toggle',name=name,enabled=bool(enabled))
            self.lua.save();self._addon_error='';self.refreshAddons();return True
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            self._error(exc);self._addon_error='Valet kunde inte sparas. '+str(exc)[:160]
            self.refreshAddons();return False

    @Slot(int,result=bool)
    def reloadAddons(self,generation):
        if (generation!=self._ui_generation or not self.lua or not self.lua.saving_enabled
                or self.local_character_mode and self.character_key is None):
            self._addon_error='Välj en karaktär och öppna tilläggslistan igen.'
            self.refreshAddons();return False
        result=self._reload_ui()
        if not result:self._addon_error='Gränssnittet kunde inte laddas om. Det tidigare är kvar.'
        self.refreshAddons();return result
    @Slot(bool,bool)
    def setActivity(self,active,focused):
        self.active=active;self.focused=focused;self._gain()
        # Stop pumping while hidden to avoid doing silent work in other tabs.
        if self.sink:
            if active and not self.timer.isActive():self.sink.resume();self.timer.start()
            elif not active:self.timer.stop();self.sink.suspend()
    @Slot(str,float,result=bool)
    def setVolume(self,bus,value):
        if bus not in self.volumes or not math.isfinite(value) or not 0<=value<=1:return False
        self.volumes[bus]=value;self._sync_runtime_settings();self._gain();self._notify_audio();return True
    @Slot(bool)
    def setMuted(self,muted):self.muted=muted;self._gain();self._notify_audio()
    @Slot(str,result=bool)
    def click(self,identity):
        try:
            if not self.lua:return False
            self.lua.click(identity);self._update_frames()
            if self.audio:self.audio.play(3,gain=.4)
            return True
        except (ValueError,RuntimeError,TimeoutError) as exc:self._error(exc);return False
    @Slot(result=str)
    def diagnostics(self):
        return json.dumps({'native':status(),'lua':{'core':'GG_ENGINE_FULL' if self.full_ui else 'GG_LEGACY','addons':self.loaded_addons,'updates':self.updates,'memory_bytes':self.lua.memory() if self.lua else 0,'warnings':getattr(self.lua,'warnings',[]),'errors':getattr(self.lua,'errors',[])},
            'world_actors':json.loads(self.world_actors.diagnostics),
            'audio':{'state':self.audio_state,'voices':self.audio.voices() if self.audio else 0,'mixed_frames':self.rendered_frames,
                     'submitted_frames':self.submitted_frames,'processed_us':self.sink.processedUSecs() if self.sink else 0,'underrun_polls':self.underruns,
                     'device_error':self.sink.error().name if self.sink else None,'device_state':self.sink.state().name if self.sink else None,'world':self.zone_audio.diagnostics() if self.zone_audio else None},'unsupported_requests':self.unsupported_requests,'ui_missing_assets':sorted(self._canvas.missing) if self._canvas else [],'ui_unsupported_draws':sorted(self._canvas.unsupported) if self._canvas else [],'ui_asset_adaptations':sorted(self._canvas.assets.adaptations) if self._canvas else [],'errors':self.errors})
    @Slot()
    def close(self):
        self.timer.stop()
        self.client_tools.close()
        self.world_actors.close()
        self._world_actor_rows=None;self._world_actor_rows_scope=None
        self.entity_audio.close()
        self.spell_audio.close()
        if self._canvas:self._canvas.close()
        if self.sink:self.sink.stop();self.output=None
        if self.zone_audio:self.zone_audio.close();self.zone_audio=None
        if self.music_streams:self.music_streams.close();self.music_streams=None
        if self.short_sounds:self.short_sounds.close();self.short_sounds=None
        self.sound_assets.close()
        if self.audio:self.audio.close();self.audio=None
        if self.lua:
            if self.full_ui:
                try:self.lua.save()
                except (ValueError,OSError,RuntimeError,TimeoutError) as exc:self._error(exc)
            self.lua.close();self.lua=None

def presentation_for(host):
    if not hasattr(host,'_game_presentation'):
        host._game_presentation=Presentation(host)
    return host._game_presentation

def use_action_for(host,runtime,index):
    """Both Qt hosts use this route for native buttons and their hotkeys."""
    with runtime._lock:
        if not isinstance(index,int) or not 0<=index<len(runtime._actions.slots):return {'error':'ACTION_SLOT_INVALID'}
        entry=dict(runtime._actions.slots[index])
    if entry.get('kind')!='MACRO':return runtime.action_use(index)
    presentation=presentation_for(host)
    # Publish the current book before a direct key press resolves cast names.
    presentation.last_update=0;presentation.update(runtime.snapshot())
    result=presentation.run_macro(int(entry['ref']))
    snapshot=runtime.snapshot();snapshot['action_result']=result
    if result.get('error'):snapshot['error']=result['error']
    return snapshot
