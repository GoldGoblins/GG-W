// GG C++/Qt adaptation. GgEngine source attribution and deltas: provenance.json.
#include "gg_presentation.h"
#include "gg_audio_dsp.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <new>
#include <vector>
extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}
namespace {
constexpr uint32_t MAX_ROWS=65536, MAX_CLIPS=32, MAX_VOICES=64, MAX_STREAMS=6;
bool is_finite(double x) { return std::isfinite(x); }
bool unit(double x) { return is_finite(x)&&x>=0&&x<=1; }
bool coordinate(double x) { return is_finite(x)&&std::abs(x)<=1e12; }
double linear(double t) { return t*(t*(t*.305306011+.682171111)+.012522878); }
struct Clip { std::vector<float> data; uint32_t rate=0,channels=1; };
struct Voice { bool on=false,loop=false,spatial=false; uint32_t clip=0,bus=0; double at=0,x=0,y=0,z=0; float gain=0,min=1,max=50,l=0,r=0,pitch=1; uint64_t token=0; bool paused=false; };
struct Stream {std::vector<float> data;uint32_t rate=0,capacity=0,read=0,write=0,used=0;bool end=false;};
struct Fade {uint32_t remaining=0;float target=0,step=0;bool stop=false;};
struct Audio {
    uint32_t rate;uint64_t next_voice_token=1; std::array<Clip,MAX_CLIPS> clips; std::array<Voice,MAX_VOICES> voices;
    std::array<Stream,MAX_STREAMS> streams;std::array<int,MAX_VOICES> voice_stream;std::array<bool,MAX_VOICES> sends{};std::array<Fade,MAX_VOICES> fades{};
    gg_audio::Limiter lookahead;gg_audio::Reverb reverb;std::array<float,32768> wet{};
    double x=0,y=0,z=0,yaw=0; float master=.5f,buses[3]={1,.4f,.6f},gate=0,output=0,limiter=1;
    explicit Audio(uint32_t r):rate(r),lookahead(r),reverb(r) {voice_stream.fill(-1);}
};
// Pure gain terms ported from engine-app/src/sound/math.rs.
float attenuation(double d,float near,float far) {
    if(d>=far) return 0;
    const double roll=d<=near?1:near/(near+4*(d-near));
    return static_cast<float>(roll*(1-std::clamp((d-far*.9)/(far*.1),0.,1.)));
}
struct Vm {
    lua_State* L=nullptr; size_t used=0,limit; int budget=0; char error[512]{};
    explicit Vm(uint32_t n):limit(n) {}
    ~Vm() { if(L) lua_close(L); }
};
void* allocate(void* ud,void* ptr,size_t old,size_t next) {
    auto* v=static_cast<Vm*>(ud);
    if(!ptr) old=0;
    if(!next) { std::free(ptr); v->used-=old; return nullptr; }
    if(next>v->limit || v->used-old>v->limit-next) return nullptr;
    void* p=std::realloc(ptr,next);
    if(p) v->used=v->used-old+next;
    return p;
}
void hook(lua_State* L,lua_Debug*) {
    void* ud=nullptr; lua_getallocf(L,&ud); auto* v=static_cast<Vm*>(ud);
    if((v->budget-=1000)<=0) luaL_error(L,"Lua instruction budget exceeded");
}
int initialize(lua_State* L) {
    // No OS/file/module/debug/coroutine access. No script-side protected call:
    // it cannot catch and repeatedly retry an exhausted instruction budget.
    for(auto open:{luaopen_base,luaopen_table,luaopen_string,luaopen_math}) { lua_pushcfunction(L,open); lua_call(L,0,0); }
    for(const char* n: {"coroutine","dofile","loadfile","loadstring","load","getfenv","setfenv","newproxy","collectgarbage","pcall","xpcall","print"}) { lua_pushnil(L); lua_setglobal(L,n); }
    return 0;
}
int function(Vm* v,const char* name) {
    if(!v || !name) return -1;
    lua_getglobal(v->L,name);
    if(!lua_isfunction(v->L,-1)) { lua_pop(v->L,1); std::snprintf(v->error,sizeof(v->error),"Missing Lua host function: %.100s",name); return -1; }
    return 0;
}
int copy_text(const char* s,char* out,uint32_t cap) {
    if(!s||!out||cap<1) return -1;
    size_t n=std::strlen(s); if(n>=cap) return -1;
    std::memcpy(out,s,n+1); return static_cast<int>(n);
}
enum class Op { Exec,Snapshot,Event,Click,Frames };
struct Request { Vm* vm; Op op; const char* one=nullptr; const char* two=nullptr; uint32_t length=0; const GgmSnapshot* snapshot=nullptr; char* out=nullptr; uint32_t capacity=0; int result=0; };
int invoke(lua_State* L) {
    auto* r=static_cast<Request*>(lua_touserdata(L,1)); lua_settop(L,0);
    if(r->op==Op::Exec) {
        if(luaL_loadbuffer(L,r->one,r->length,r->two)) return lua_error(L);
        lua_call(L,0,0); return 0;
    }
    const char* name=r->op==Op::Snapshot?"GG_Publish":r->op==Op::Event?"GG_Dispatch":r->op==Op::Click?"GG_Click":"GG_DrawJson";
    if(function(r->vm,name)) return luaL_error(L,"Missing Lua host function");
    if(r->op==Op::Snapshot) {
        const auto* s=r->snapshot;
        for(double d:{s->x,s->y,s->z,s->yaw,s->time,s->speed,s->health,s->resource}) lua_pushnumber(L,d);
        lua_pushboolean(L,s->running);lua_pushstring(L,r->one);lua_pushstring(L,r->two);lua_call(L,11,0);
    } else if(r->op==Op::Event) {
        lua_pushstring(L,r->one);lua_pushstring(L,r->two);lua_call(L,2,0);
    } else if(r->op==Op::Click) {
        lua_pushstring(L,r->one);lua_call(L,1,0);
    } else {
        lua_call(L,0,1);r->result=copy_text(lua_tostring(L,-1),r->out,r->capacity);
    }
    return 0;
}
int run(Request& r) {
    auto* v=r.vm;v->budget=100000;lua_sethook(v->L,hook,LUA_MASKCOUNT,1000);
    int code=lua_cpcall(v->L,invoke,&r);lua_sethook(v->L,nullptr,0,0);
    if(code) { const char* e=lua_type(v->L,-1)==LUA_TSTRING?lua_tostring(v->L,-1):"Lua error";std::snprintf(v->error,sizeof(v->error),"%s",e);lua_pop(v->L,1);return -1; }
    v->error[0]=0;return r.result;
}
}
uint32_t ggm_abi_version() { return 1; }
int ggm_pack_instances(const GgmInstance* rows,uint32_t n,float* out,uint32_t cap) {
    if(n>MAX_ROWS||cap<n||(!rows&&n)||(!out&&n)) return -1;
    for(uint32_t i=0;i<n;++i) {
        const auto& a=rows[i];
        for(double t:{a.x,a.y,a.z,a.scale,a.pitch,a.yaw,a.roll}) if(!coordinate(t)) return -1;
        if(a.scale<0 || a.scale>1e6 || !is_finite(a.tint)||!unit(a.r)||!unit(a.g)||!unit(a.b)||!unit(a.alpha)) return -1;
    }
    for(uint32_t i=0;i<n;++i) {
        const auto& a=rows[i]; const double rad=3.14159265358979323846/180;
        double sx=std::sin(a.pitch*rad),cx=std::cos(a.pitch*rad),sy=std::sin(a.yaw*rad),cy=std::cos(a.yaw*rad),sz=std::sin(a.roll*rad),cz=std::cos(a.roll*rad);
        double t=std::round(std::clamp(a.tint,0.,1.)*65535)/65535,colour=linear(t);
        std::array<double,20> m={(cy*cz+sy*sx*sz)*a.scale,(-cy*sz+sy*sx*cz)*a.scale,sy*cx*a.scale,a.x,
            cx*sz*a.scale,cx*cz*a.scale,-sx*a.scale,a.y,
            (-sy*cz+cy*sx*sz)*a.scale,(sy*sz+cy*sx*cz)*a.scale,cy*cx*a.scale,a.z,
            linear(a.r)*colour,linear(a.g)*colour,linear(a.b)*colour,a.alpha,0,0,0,0};
        for(unsigned j=0;j<20;++j) out[i*20+j]=static_cast<float>(m[j]);
    }
    return static_cast<int>(n);
}
void* ggm_audio_create(uint32_t rate) { if(rate<8000||rate>192000) return nullptr; try{return new Audio(rate);}catch(...){return nullptr;} }
void ggm_audio_destroy(void* p) { delete static_cast<Audio*>(p); }
int ggm_audio_clip(void* p,uint32_t id,const float* data,uint32_t n,uint32_t rate) {
    return ggm_audio_clip_channels(p,id,data,n,rate,1);
}
int ggm_audio_clip_channels(void* p,uint32_t id,const float* data,uint32_t n,uint32_t rate,uint32_t channels) {
    auto* a=static_cast<Audio*>(p); if(!a||id>=MAX_CLIPS||!data||!n||rate<8000||rate>192000||n>rate*30||channels<1||channels>2) return -1;
    size_t count=size_t(n)*channels,total=count;
    for(unsigned i=0;i<MAX_CLIPS;++i)if(i!=id)total+=a->clips[i].data.size();
    if(total>64*1024*1024/sizeof(float))return -1;
    for(size_t i=0;i<count;++i) if(!std::isfinite(data[i])||std::abs(data[i])>1) return -1;
    for(unsigned i=0;i<MAX_VOICES;++i)if(a->voices[i].on&&a->voice_stream[i]<0&&a->voices[i].clip==id) return -1;
    try { a->clips[id].data.assign(data,data+count); a->clips[id].rate=rate;a->clips[id].channels=channels; } catch(...) { return -1; }
    return 0;
}
int ggm_audio_pitch(void* p,uint32_t voice,float pitch){auto* a=static_cast<Audio*>(p);if(!a||voice>=MAX_VOICES||!a->voices[voice].on||!is_finite(pitch)||pitch<.01f||pitch>8.f)return -1;a->voices[voice].pitch=pitch;return 0;}
int ggm_audio_voice_active(void* p,uint32_t voice){auto* a=static_cast<Audio*>(p);return a&&voice<MAX_VOICES&&a->voices[voice].on?1:0;}
uint64_t ggm_audio_voice_token(void* p,uint32_t voice){auto* a=static_cast<Audio*>(p);return a&&voice<MAX_VOICES&&a->voices[voice].on?a->voices[voice].token:0;}
int ggm_audio_voice_stop(void* p,uint32_t voice,uint64_t token){auto* a=static_cast<Audio*>(p);if(!a||voice>=MAX_VOICES||!token)return -1;if(a->voices[voice].on&&a->voices[voice].token==token){a->voices[voice].on=false;a->fades[voice]={};}return 0;}
int ggm_audio_voice_position(void* p,uint32_t voice,uint64_t token,double x,double y,double z){auto* a=static_cast<Audio*>(p);if(!a||voice>=MAX_VOICES||!token||!coordinate(x)||!coordinate(y)||!coordinate(z))return -1;auto& v=a->voices[voice];if(v.on&&v.token==token&&v.spatial){v.x=x;v.y=y;v.z=z;}return 0;}
int ggm_audio_clip_active(void* p,uint32_t id){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_CLIPS)return -1;for(unsigned i=0;i<MAX_VOICES;++i)if(a->voices[i].on&&a->voice_stream[i]<0&&a->voices[i].clip==id)return 1;return 0;}
int ggm_audio_clip_release(void* p,uint32_t id){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_CLIPS||ggm_audio_clip_active(p,id)!=0)return -1;std::vector<float>().swap(a->clips[id].data);a->clips[id].rate=0;return 0;}
int ggm_audio_play(void* p,uint32_t clip,uint32_t bus,double x,double y,double z,float gain,float near,float far,uint32_t flags) {
    auto* a=static_cast<Audio*>(p);
    if(!a||clip>=MAX_CLIPS||a->clips[clip].data.empty()||bus>2||!coordinate(x)||!coordinate(y)||!coordinate(z)||!unit(gain)||!is_finite(near)||!is_finite(far)||near<=0||far<=near||far>1e6||flags>7) return -1;
    for(unsigned i=0;i<MAX_VOICES;++i) if(!a->voices[i].on) {
        a->voices[i]={true,bool(flags&1),bool(flags&2),clip,bus,0,x,y,z,gain,near,far,0,0};a->voices[i].token=a->next_voice_token++;a->voice_stream[i]=-1;a->sends[i]=bool(flags&4)&&bool(flags&2)&&bus==0;a->fades[i]={}; return static_cast<int>(i);
    }
    return -2; // explicit voice capacity, no arbitrary eviction
}
int ggm_audio_listener(void* p,double x,double y,double z,double yaw) {
    auto* a=static_cast<Audio*>(p); if(!a||!coordinate(x)||!coordinate(y)||!coordinate(z)||!coordinate(yaw)) return -1;
    a->x=x;a->y=y;a->z=z;a->yaw=yaw;return 0;
}
int ggm_audio_gain(void* p,float master,float sfx,float music,float ambience,uint32_t gate) {
    auto* a=static_cast<Audio*>(p);if(!a||!unit(master)||!unit(sfx)||!unit(music)||!unit(ambience)||gate>1) return -1;
    a->master=master;a->buses[0]=sfx;a->buses[1]=music;a->buses[2]=ambience;a->gate=static_cast<float>(gate);return 0;
}
int ggm_audio_render(void* p,float* out,uint32_t n) {
    auto* a=static_cast<Audio*>(p);if(!a||!out||n>16384) return -1;
    std::fill(out,out+n*2,0.f);
    std::fill(a->wet.begin(),a->wet.begin()+n*2,0.f);
    const float glide=static_cast<float>(1-std::exp(-1./(.015*a->rate)));
    for(unsigned voice=0;voice<MAX_VOICES;++voice) if(a->voices[voice].on&&!a->voices[voice].paused) {
        auto& v=a->voices[voice];auto& fade=a->fades[voice];
        const auto advance_fade=[&](){if(fade.remaining){v.gain+=fade.step;if(--fade.remaining==0){v.gain=fade.target;if(fade.stop)v.on=false;}}};
        if(a->voice_stream[voice]>=0){
            auto& s=a->streams[unsigned(a->voice_stream[voice])];
            for(uint32_t i=0;i<n;++i){
                if(s.used<2&&!s.end){advance_fade();if(!v.on)break;continue;}
                if(!s.used){if(s.end)v.on=false;break;}
                const auto next=(s.read+(s.used>1?1:0))%s.capacity;const float fraction=float(v.at);
                const float left=s.data[s.read*2]+fraction*(s.data[next*2]-s.data[s.read*2]);
                const float right=s.data[s.read*2+1]+fraction*(s.data[next*2+1]-s.data[s.read*2+1]);
                const float volume=v.gain*a->master*a->buses[v.bus];v.l+=(volume-v.l)*glide;
                out[i*2]+=left*v.l;out[i*2+1]+=right*v.l;
                v.at+=double(s.rate)/a->rate;const auto consumed=std::min(s.used,uint32_t(v.at));s.read=(s.read+consumed)%s.capacity;s.used-=consumed;v.at-=consumed;
                if(!s.used)v.at=0;
                advance_fade();if(!v.on)break;
            }continue;
        }
        const auto& c=a->clips[v.clip]; double dx=v.x-a->x,dy=v.y-a->y,dz=v.z-a->z,dist=std::sqrt(dx*dx+dy*dy+dz*dz);
        float spatial=v.spatial?attenuation(dist,v.min,v.max):1;
        double pan=v.spatial&&dist>1e-6?std::clamp((dx*std::cos(a->yaw)-dz*std::sin(a->yaw))/dist,-1.,1.):0;
        float volume=a->master*a->buses[v.bus]*spatial;
        float left=volume*static_cast<float>(std::sqrt((1-pan)*.5)),right=volume*static_cast<float>(std::sqrt((1+pan)*.5));
        for(uint32_t i=0;i<n;++i) {
            const size_t frames=c.data.size()/c.channels;
            if(v.at>=frames) { if(v.loop) v.at=std::fmod(v.at,double(frames)); else { v.on=false;break; } }
            size_t k=static_cast<size_t>(v.at),next=k+1<frames?k+1:(v.loop?0:k);
            const auto sample=[&](unsigned channel){return c.data[k*c.channels+channel]+static_cast<float>(v.at-k)*(c.data[next*c.channels+channel]-c.data[k*c.channels+channel]);};
            float sample_l=sample(0),sample_r=c.channels==2?sample(1):sample_l;
            if(v.spatial&&c.channels==2)sample_l=sample_r=(sample_l+sample_r)*.5f;
            v.l+=(left*v.gain-v.l)*glide;v.r+=(right*v.gain-v.r)*glide;
            const float l=sample_l*v.l,r=sample_r*v.r;
            out[i*2]+=l;out[i*2+1]+=r;if(a->sends[voice]){a->wet[i*2]+=l;a->wet[i*2+1]+=r;}
            v.at+=double(c.rate)/a->rate*v.pitch;advance_fade();if(!v.on)break;
        }
    }
    for(uint32_t i=0;i<n;++i) {
        auto wet=a->reverb.step({a->wet[i*2],a->wet[i*2+1]});
        auto mixed=a->lookahead.step({out[i*2]+wet.l,out[i*2+1]+wet.r});
        a->output+=(a->gate-a->output)*glide;
        out[i*2]=mixed.l*a->output;out[i*2+1]=mixed.r*a->output;
    }
    return static_cast<int>(n);
}
int ggm_audio_stop(void* p,int bus) { auto* a=static_cast<Audio*>(p);if(!a||bus<-1||bus>2) return -1;for(auto& v:a->voices) if(bus<0||int(v.bus)==bus) v.on=false;return 0; }
uint32_t ggm_audio_voices(void* p) { auto* a=static_cast<Audio*>(p);if(!a) return 0;uint32_t n=0;for(auto& v:a->voices) n+=v.on;return n; }
int ggm_audio_reverb(void* p,float wet,float feedback,float damping,float width){auto* a=static_cast<Audio*>(p);if(!a||!is_finite(wet)||wet<0||wet>2||!unit(feedback)||feedback>=1||!unit(damping)||!unit(width))return -1;a->reverb.wet=wet;a->reverb.feedback=feedback;a->reverb.damping=damping;a->reverb.width=width;return 0;}
int ggm_audio_fade(void* p,uint32_t voice,float target,uint32_t ms,uint32_t stop){auto* a=static_cast<Audio*>(p);if(!a||voice>=MAX_VOICES||!a->voices[voice].on||!unit(target)||ms>60000||stop>1)return -1;const auto frames=std::max(1u,uint32_t(uint64_t(ms)*a->rate/1000));a->fades[voice]={frames,target,(target-a->voices[voice].gain)/frames,bool(stop)};if(stop)a->voices[voice].paused=false;return 0;}
int ggm_audio_pause(void* p,uint32_t voice,uint32_t paused){auto* a=static_cast<Audio*>(p);if(!a||voice>=MAX_VOICES||!a->voices[voice].on||paused>1)return -1;auto& v=a->voices[voice];if(v.paused&&!paused)v.l=v.r=0;v.paused=bool(paused);return 0;}
int ggm_audio_stream_create(void* p,uint32_t id,uint32_t rate,uint32_t cap){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_STREAMS||rate<8000||rate>192000||cap<2||cap>rate*2)return -1;for(unsigned i=0;i<MAX_VOICES;++i)if(a->voices[i].on&&a->voice_stream[i]==int(id))return -1;try{a->streams[id].data.assign(cap*2,0);}catch(...){return -1;}auto& s=a->streams[id];s.rate=rate;s.capacity=cap;s.read=s.write=s.used=0;s.end=false;return 0;}
int ggm_audio_stream_free(void* p,uint32_t id){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_STREAMS||!a->streams[id].capacity)return -1;return int(a->streams[id].capacity-a->streams[id].used);}
int ggm_audio_stream_write(void* p,uint32_t id,const float* data,uint32_t n,uint32_t end){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_STREAMS||!a->streams[id].capacity||(!data&&n)||n>16384||end>1)return -1;auto& s=a->streams[id];if(s.end)return -1;const auto accepted=std::min(n,s.capacity-s.used);for(uint32_t i=0;i<accepted*2;++i)if(!std::isfinite(data[i])||std::abs(data[i])>1)return -1;for(uint32_t i=0;i<accepted;++i){s.data[s.write*2]=data[i*2];s.data[s.write*2+1]=data[i*2+1];s.write=(s.write+1)%s.capacity;}s.used+=accepted;if(end&&accepted==n)s.end=true;return int(accepted);}
int ggm_audio_stream_play(void* p,uint32_t id,uint32_t bus,float gain){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_STREAMS||!a->streams[id].capacity||bus>2||!unit(gain))return -1;for(unsigned i=0;i<MAX_VOICES;++i)if(a->voices[i].on&&a->voice_stream[i]==int(id))return -1;for(unsigned i=0;i<MAX_VOICES;++i)if(!a->voices[i].on){a->voices[i]={true,false,false,0,bus,0,0,0,0,gain,1,50,0,0};a->voices[i].token=a->next_voice_token++;a->voice_stream[i]=int(id);a->sends[i]=false;a->fades[i]={};return int(i);}return -2;}
int ggm_audio_stream_active(void* p,uint32_t id){auto* a=static_cast<Audio*>(p);if(!a||id>=MAX_STREAMS)return -1;for(unsigned i=0;i<MAX_VOICES;++i)if(a->voices[i].on&&a->voice_stream[i]==int(id))return int(i);return -1;}
void* ggm_lua_create(uint32_t cap) {
    if(cap<524288||cap>16777216) return nullptr;
    auto* v=new(std::nothrow) Vm(cap);if(!v) return nullptr;
    v->L=lua_newstate(allocate,v);if(!v->L) { delete v;return nullptr; }
    if(lua_cpcall(v->L,initialize,nullptr)) { delete v;return nullptr; }
    return v;
}
void ggm_lua_destroy(void* p) { delete static_cast<Vm*>(p); }
int ggm_lua_exec(void* p,const char* source,uint32_t n,const char* name) {
    auto* v=static_cast<Vm*>(p);if(!v||!source||n>262144||!name) return -1;
    Request r{v,Op::Exec,source,name,n};return run(r);
}
int ggm_lua_snapshot(void* p,const GgmSnapshot* s,const char* cell,const char* biome) {
    auto* v=static_cast<Vm*>(p);if(!v||!s||!cell||!biome||std::strlen(cell)>96||std::strlen(biome)>96) return -1;
    for(double d:{s->x,s->y,s->z,s->yaw,s->time,s->speed,s->health,s->resource}) if(!coordinate(d)) return -1;
    Request r{v,Op::Snapshot,cell,biome,0,s};return run(r);
}
int ggm_lua_event(void* p,const char* event,const char* payload) {
    auto* v=static_cast<Vm*>(p);if(!v||!event||!payload||std::strlen(event)>64||std::strlen(payload)>512) return -1;
    Request r{v,Op::Event,event,payload};return run(r);
}
int ggm_lua_click(void* p,const char* id) { auto* v=static_cast<Vm*>(p);if(!v||!id||std::strlen(id)>96) return -1;Request r{v,Op::Click,id};return run(r); }
int ggm_lua_frames(void* p,char* out,uint32_t cap) {
    auto* v=static_cast<Vm*>(p);if(!v||!out||cap<1) return -1;Request r{v,Op::Frames,nullptr,nullptr,0,nullptr,out,cap};return run(r);
}
int ggm_lua_error(void* p,char* out,uint32_t cap) { auto* v=static_cast<Vm*>(p);return v?copy_text(v->error,out,cap):-1; }
uint32_t ggm_lua_memory(void* p) { auto* v=static_cast<Vm*>(p);return v?static_cast<uint32_t>(v->used):0; }
