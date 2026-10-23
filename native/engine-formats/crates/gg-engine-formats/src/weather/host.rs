//! Bounded C ABI state/renderer host; simulation and source geometry stay in the original kernels.
use super::*;
use render::FlakeView;
#[derive(Default,Clone)]
pub struct System {state:WeatherState,wind:WeatherWind,heights:HeightCache,rain:Pool,snow:Pool,mist:Mist,rng:u32,last_cut:u32,last_ms:Option<u64>,generation:u64,view:Option<FlakeView>,draw:bool,revision:u64,fog:[f32;3],sound_id:u32}
fn scalar(v:&Value,lo:f64,hi:f64)->Result<f32,String>{let n=v.as_f64().ok_or("invalid weather scalar")?;if !n.is_finite()||n<lo||n>hi{return Err("invalid weather scalar".into());}Ok(n as f32)}
fn ms(v:&Value)->Result<u64,String>{v.as_u64().filter(|n|*n<=315576000000).ok_or("invalid weather time".into())}
fn point(v:&Value)->Result<Vec3,String>{let a=v.as_array().filter(|a|a.len()==3).ok_or("invalid weather vector")?;Ok(Vec3::new(scalar(&a[2],-2e6,2e6)?,scalar(&a[1],-2e6,2e6)?,-scalar(&a[0],-2e6,2e6)?))}
fn qt(p:Vec3)->Vec3{Vec3::new(-p.z,p.y,p.x)}
impl System {
    pub fn set(&mut self,v:&Value)->Result<Value,String>{
        let kind=v["kind"].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid weather kind")?;
        let grade=scalar(&v["grade"],0.,1.)?;let instant=v["instant"].as_bool().ok_or("invalid weather instant flag")?;let now=ms(&v["now_ms"])?;
        let quality=v["quality"].as_u64().filter(|n|*n<=3).ok_or("invalid weather density quality")?;
        let sound_id=if v["sound_id"].is_null(){self.sound_id}else{v["sound_id"].as_u64().and_then(|n|u32::try_from(n).ok()).ok_or("invalid weather sound kit")?};
        if self.last_ms.is_some_and(|old|now<old){return Err("weather clock went backwards".into());}
        self.sound_id=sound_id;self.state.weather_density=quality as u8;self.state.apply(WeatherKind::from_wire(kind),grade,instant,now as f64/1000.);self.state.resolve(now as f64/1000.);
        if self.rng==0{self.rng=0x9E3779B9;}Ok(self.snapshot())
    }
    pub fn frame(&mut self,v:&Value,pages:&HashMap<String,crate::collision::Page>)->Result<Value,String>{
        let now=ms(&v["now_ms"])?;
        if self.last_ms.is_some_and(|old|now<old){return Err("weather clock went backwards".into());}
        let eye=point(&v["view"]["eye"])?;let forward=point(&v["view"]["forward"])?.try_normalize().ok_or("invalid weather view")?;
        let right=forward.cross(point(&v["view"]["up"])?).try_normalize().ok_or("invalid weather view")?;let up=right.cross(forward);
        let fov=scalar(&v["view"]["fov"],1.,179.)?;let player=point(&v["player"])?;let facing=point(&v["facing"])?;let speed=scalar(&v["speed"],0.,200.)?;
        let draw=v["draw"].as_bool().ok_or("invalid weather draw flag")?;let mut fog=[0.;3];let color=v["fog"].as_array().filter(|c|c.len()==3).ok_or("invalid weather fog")?;
        for (o,c) in fog.iter_mut().zip(color){*o=scalar(c,0.,1.)?;}
        let revision=v["collision_revision"].as_u64().ok_or("invalid weather collision revision")?;
        let dt=self.last_ms.map_or(0.,|old|(now-old) as f32/1000.);self.last_ms=Some(now);self.draw=draw;self.fog=fog;
        self.view=Some(FlakeView{eye,forward,right,up,world_per_px:(fov.to_radians()*0.5).tan()/SNOW_PX_REF_HEIGHT});
        if revision!=self.revision{self.heights=HeightCache::default();self.revision=revision;}
        self.state.resolve(now as f64/1000.);self.wind.update(player,facing,speed,dt);
        let t=now as f32/1000.;
        if self.last_cut!=self.state.cut_seq{self.last_cut=self.state.cut_seq;self.rain.cut(t);self.snow.cut(t);self.mist.cut();}
        if dt>0.{
            // Fix the original host's indoor early-return: drops continue unseen,
            // while only the mist and draw follow the weather-visible gate.
            pool::run_kind(&mut self.rain,WeatherKind::Rain,&self.state,&self.wind,&mut self.heights,pages,&mut self.rng,t,dt,eye);
            pool::run_kind(&mut self.snow,WeatherKind::Snow,&self.state,&self.wind,&mut self.heights,pages,&mut self.rng,t,dt,eye);
            if draw{mist::run_mist(&mut self.mist,&self.state,&self.wind,&mut self.heights,pages,&mut self.rng,dt,eye);}
        }
        self.generation+=1;Ok(self.snapshot())
    }
    fn counts(&self)->[usize;5]{[self.rain.drops.len(),self.rain.patters.len(),self.snow.drops.len(),self.snow.patters.len(),self.mist.count()]}
    pub fn snapshot(&self)->Value{
        json!({"kind":format!("{:?}",self.state.effect_kind).to_uppercase(),"sound_id":self.sound_id,"intensity":self.state.intensity_a,"density":self.state.effect_density,"sky_density":self.state.sky_density,"storm_blend":state::storm_blend(self.state.sky_density),"cut":self.state.cut_seq,"quality":self.state.weather_density,"generation":self.generation,"counts":self.counts(),"pending":[self.rain.pending_len(),self.snow.pending_len()],"draw":self.draw,"eye":self.view.as_ref().map(|v|qt(v.eye).to_array()),"wind":qt(self.wind.vel).to_array(),"spawn_slab_up":qt(self.wind.slab*Vec3::Y).to_array(),"native_bytes":self.rain.allocated_bytes()+self.snow.allocated_bytes()+self.mist.allocated_bytes()+self.heights.allocated_bytes()})
    }
    pub fn draw(&self,v:&Value,blob:&mut Vec<u8>)->Result<Value,String>{
        if v["generation"].as_u64()!=Some(self.generation){return Err("stale weather draw generation".into());}
        let kind=v["kind"].as_u64().filter(|n|*n<5).ok_or("invalid weather layer")? as usize;
        let offset=v["offset"].as_u64().filter(|n|*n<=pool_bound(WeatherKind::Snow) as u64).ok_or("invalid weather page offset")? as usize;
        let limit=v["limit"].as_u64().filter(|n|*n>0&&*n<=32768).ok_or("weather draw page capacity exceeded")? as usize;
        let view=self.view.as_ref().ok_or("weather view not set")?;let mut verts=Vec::new();
        let range=|len:usize|offset.min(len)..(offset+limit).min(len);
        if self.draw{match kind{
            0=>render::push_streaks(&mut verts,&self.rain.drops[range(self.rain.drops.len())],self.wind.tilt,view.eye),
            1=>render::push_patters(&mut verts,&self.rain.patters[range(self.rain.patters.len())],view.right,view.up),
            2=>render::push_flakes(&mut verts,&self.snow.drops[range(self.snow.drops.len())],&[],view),
            3=>render::push_flakes(&mut verts,&[],&self.snow.patters[range(self.snow.patters.len())],view),
            4=>mist::push_mist(&mut verts,&self.mist,view.right,view.up,view.eye,self.fog),_=>unreachable!()
        }}
        let triangle=kind<2;let points:Vec<(f32,f32,f32,f32)>=if triangle{vec![(-1.,0.,0.,1.),(1.,0.,1.,1.),(0.,1.,0.5,if kind==1{0.172}else{0.})]}else{vec![(-1.,-1.,0.,1.),(1.,-1.,1.,1.),(1.,1.,1.,0.),(-1.,1.,0.,0.)]};
        let mesh_offset=blob.len();for (x,y,u,w) in &points{for f in [*x,*y,0.,0.,0.,1.,*u,*w]{blob.extend_from_slice(&f.to_le_bytes());}}
        let instance_offset=blob.len();let mut count=0;let n=if triangle{3}else{4};
        for vertex in verts.chunks_exact(n){
            let mut p:Vec<Vec3>=vertex.iter().map(|v|Vec3::from_array(v.pos)).collect();
            if !matches!(kind,2|3){for p in &mut p{*p-=view.eye;}}
            if kind==1{p.swap(1,2);}
            let (center,x,y)=if triangle{let c=(p[0]+p[1])*0.5;(c,(p[1]-p[0])*0.5,p[2]-c)}else{((p[0]+p[2])*0.5,(p[1]-p[0])*0.5,(p[3]-p[0])*0.5)};
            let (center,x,y)=(qt(center),qt(x),qt(y));let z=x.cross(y).normalize_or(Vec3::Z);
            let rgba=if kind==4{[vertex[0].color[0],vertex[0].color[1],vertex[0].color[2],1.]}else{vertex[0].color};
            let custom=if kind==1{[vertex[0].uv[0],vertex[0].uv[1]-0.25,0.25,0.25]}else if kind==4{[vertex[0].color[3],vertex[1].color[3],vertex[2].color[3],vertex[3].color[3]]}else{[0.,0.,1.,1.]};
            for f in [x.x,y.x,z.x,center.x,x.y,y.y,z.y,center.y,x.z,y.z,z.z,center.z].into_iter().chain(rgba).chain(custom){if !f.is_finite(){return Err("non-finite weather instance".into());}blob.extend_from_slice(&f.to_le_bytes());}
            count+=1;
        }
        let total=self.counts()[kind];let next=(offset+limit<total).then_some(offset+limit);let capacity=match kind{0=>32768.min(pool_bound(WeatherKind::Rain).saturating_sub(offset)),1|3=>GROUND_CAP,2=>32768,4=>128,_=>0};
        let row=json!({"kind":"weather","layer":kind,"offset":mesh_offset,"vertices":points.len(),"stride":32,"indices":if triangle{vec![0,1,2]}else{vec![0,1,2,0,2,3]},"bounds":[[-1.,-1.,-1.],[1.,1.,1.]],"blend":if triangle{6}else{2},"instances_finite":true,"instance_offset":instance_offset,"instance_count":count,"instance_capacity":capacity,"camera_anchor":qt(view.eye).to_array(),"visible":self.draw&&count>0});
        Ok(json!({"format":"WEATHER_INSTANCES","row":row,"next":next,"blob_kind":"vertices_instances","blob_bytes":blob.len()}))
    }
}
