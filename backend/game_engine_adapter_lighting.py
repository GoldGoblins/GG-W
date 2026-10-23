"""Time, location and camera submersion over the original native LightCatalog."""
import math,time

def settings(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('World lighting must be an object')
    map_id=value.get('map_id');minute=value.get('minute',720);scale=value.get('time_scale',1)
    if isinstance(map_id,bool) or not isinstance(map_id,int) or not 0<=map_id<=0xffffffff:raise ValueError('Invalid lighting map ID')
    for number,low,high in ((minute,0,1439.999999),(scale,0,86400)):
        if isinstance(number,bool) or not isinstance(number,(float,int)) or not math.isfinite(number) or not low<=number<=high:raise ValueError('Invalid lighting clock')
    if not isinstance(value.get('stormy',False),bool) or not isinstance(value.get('ghost',False),bool):raise ValueError('Invalid lighting weather/state')
    return {'map_id':map_id,'minute':minute,'time_scale':scale,'stormy':value.get('stormy',False),'ghost':value.get('ghost',False)}

class WorldLighting:
    def __init__(self,stream):
        self.stream=stream;self.config=None;self.future=None;self.signature=None;self.next_ms=0;self.frames=0;self.error='';self.state={'source':'GG_MANIFEST_DEFAULTS','ambient':[.25]*3,'diffuse':[.75]*3,'to_light':[0,1,0],'sidn':0,'fog':None}
        self.clouds=None;self.art=None
        self.weather_blend=None;self.next_real=0
        self.player_ghost=False
        from backend.game_engine_adapter_skybox import Skyboxes,WmoCrossfade
        self.skyboxes=Skyboxes(stream);self.crossfade=WmoCrossfade();self.scene_state=dict(self.state)
    def configure(self,value):self.config=settings(value)
    def request(self):
        s=self.stream;cfg=self.config;eye=s.camera.eye if s.camera else s.position;origin=s.config['origin'];water=s.water_sample(*eye)
        submerged=water['body_kind']!='NONE' and eye[1]<water['height_m'];kind=water['body_kind'] if submerged else 'DRY'
        if kind=='STILL':kind='WATER'
        minutes=cfg['minute']+s.clock_ms/60000*cfg['time_scale']
        return {'far_clip':s.detailedFar,'map_id':cfg['map_id'],'minute':minutes%1440,'day_count':int(minutes//1440),
                'position':[eye[0]+origin[0],origin[1]-eye[2],eye[1]+origin[2]],'submersion':kind,'stormy':cfg['stormy'],'storm_blend':s.weather.state['storm_blend'] if s.weather.config is not None else int(cfg['stormy']),'ghost':cfg['ghost'] or self.player_ghost,
                'submersion_depth':max(0,water['height_m']-eye[1]) if submerged else 0,'interior':s.query(*eye)['indoors'],'view_forward':s.view['forward'] if s.view else [0,0,-1]}
    def finish(self):
        if self.future is None or not self.future.done():return
        future,self.future=self.future,None
        try:
            result,data,art,sky,wanted,sky_error=future.result()
            if art is not None and self.art is None:
                from backend.game_engine_adapter_celestial import SkyArt
                self.art=SkyArt(self.stream,art)
            if result.get('clouds'):
                from backend.game_engine_adapter_sky import CloudLayer
                if self.clouds is None:self.clouds=CloudLayer(self.stream)
                self.clouds.update(data)
            self.scene_state=result
            if sky_error:
                if len(self.skyboxes.failures)<8:self.skyboxes.failures[wanted]=sky_error
            self.skyboxes.finish(sky,wanted)
            self._room()
            self.frames+=1;self.error=''
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:self.error=str(exc)[:240]
    def advance(self):
        self._room()
        from backend.game_engine_adapter_skybox import wmo_sky
        wanted=wmo_sky(self.stream)
        if self.config is None and not wanted:return
        self.finish();s=self.stream
        if self.future is not None or s.pending is not None or s.horizon.future is not None or s.weather.future is not None or not self.due():return
        if any(key not in s.pages and time.monotonic()>=s.errors.get(key,(0,''))[0] for key in s.desired(s.position[0],s.position[2])):return
        from backend.game_engine_adapter_celestial import flare_visibility
        value={**self.request(),'clock_ms':int(s.clock_ms),'flare_visibility':flare_visibility(s,self.state)} if self.config else None;self.next_ms=s.clock_ms+100;self.next_real=time.monotonic()+.1;self.weather_blend=s.weather.state['storm_blend']
        self.future=s.pool.submit(self._sample,value,self.art is None,wanted,int(s.clock_ms),set(self.skyboxes.arts),dict(self.skyboxes.failures),s.budget_limit-s.bytes)
    def _room(self):
        from backend.game_engine_adapter_skybox import wmo_fog
        s=self.stream;scene=self.scene_state;dry=scene.get('submersion','DRY')=='DRY'
        self.crossfade.advance(s.clock_ms,wmo_fog(s),dry)
        result={**scene,'wmo_crossfade':self.crossfade.weight}
        result['ghost']=bool(scene.get('ghost',False) or self.player_ghost)
        if dry:result['fog']=self.crossfade.fog(scene.get('fog'),s.detailedFar)
        wanted,weight=self.skyboxes.slot(scene);before=self.skyboxes.replaces_celestial
        self.skyboxes.wanted=wanted;self.skyboxes.apply(weight)
        if result!=self.state or before!=self.skyboxes.replaces_celestial:
            self.state=result;s.lightingChanged.emit()
    def due(self):
        s=self.stream
        return s.clock_ms>=self.next_ms or (s.weather.config is not None and self.weather_blend!=s.weather.state['storm_blend'] and time.monotonic()>=self.next_real)
    def _sample(self,value,want_art,wmo,clock,known,failed,available):
        from backend.game_engine_adapter_formats import NativeFormats
        result,data=NativeFormats._unpack(self.stream.cache._reader().request('atmosphere',timeout=2,clouds=True,**value)) if value else (dict(self.scene_state),b'')
        from backend.game_engine_adapter_celestial import resources
        wanted=result.get('skybox') or wmo;sky=None;error=''
        # Publish the common sky/cloud art first. Its initial reservation must
        # be included in the next skybox allocation's available budget.
        if wanted and wanted not in failed and (not want_art or not value):
            try:sky=self.skyboxes.prepare(wanted,clock,known,available)
            except (ValueError,OSError,RuntimeError,TimeoutError) as exc:error=str(exc)[:240]
        return result,data,resources(self.stream.cache) if want_art and value else None,sky,wanted,error
    def close(self):
        self.skyboxes.close()
        if self.clouds:self.clouds.close();self.clouds=None
        if self.art:self.art.close();self.art=None
