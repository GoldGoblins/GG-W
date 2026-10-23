#include "gg_presentation.h"
#include <array>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <string>
int main(int argc,char** argv) {
    assert((argc==1||argc==2)&&ggm_abi_version()==1);
    const bool host_api=argc==2;
    std::string source="assert(os==nil and io==nil and package==nil and debug==nil and pcall==nil); function GG_DrawJson() return '[]' end";
    if(host_api){std::ifstream f(argv[1]);source.assign(std::istreambuf_iterator<char>(f),{});assert(!source.empty());}
    for(int n=0;n<50;++n) {
        auto* vm=ggm_lua_create(524288);assert(vm);
        assert(ggm_lua_exec(vm,source.data(),source.size(),"host")==0);
        const char* addon="local f=CreateFrame('Button','Probe');f:SetText('Ready');f:RegisterEvent('SNAPSHOT');f:SetScript('OnEvent',function() f:SetText('Updated') end)";
        if(host_api){
            assert(ggm_lua_exec(vm,addon,std::char_traits<char>::length(addon),"probe")==0);
            GgmSnapshot snap{1,2,3,0,4,2,90,100,1};assert(ggm_lua_snapshot(vm,&snap,"0:0","FOREST")==0);
            assert(ggm_lua_event(vm,"SNAPSHOT","")==0);
        }
        std::array<char,65536> json{};
        assert(ggm_lua_frames(vm,json.data(),json.size())>0);
        const char* loop="while true do end";assert(ggm_lua_exec(vm,loop,std::char_traits<char>::length(loop),"budget")==-1);
        const char* oom="retained=string.rep('x',1000000)";assert(ggm_lua_exec(vm,oom,std::char_traits<char>::length(oom),"memory")==-1);
        assert(ggm_lua_frames(vm,json.data(),json.size())>0);ggm_lua_destroy(vm);
    }
    for(int n=0;n<100;++n) {
        auto* a=ggm_audio_create(48000);assert(a);std::array<float,256> clip{};clip.fill(1);
        assert(ggm_audio_clip(a,0,clip.data(),clip.size(),48000)==0);assert(ggm_audio_gain(a,1,1,1,1,1)==0);
        for(int i=0;i<64;++i) assert(ggm_audio_play(a,0,0,0,0,10,1,2,60,3)>=0);
        assert(ggm_audio_play(a,0,0,0,0,0,1,2,60,1)==-2);std::array<float,8192> out{};
        assert(ggm_audio_render(a,out.data(),4096)==4096);
        for(float x:out) assert(std::isfinite(x)&&std::abs(x)<=.99001f);
        assert(ggm_audio_stop(a,-1)==0);ggm_audio_destroy(a);
    }
    for(int n=0;n<16;++n){
        auto* a=ggm_audio_create(48000);assert(a);assert(ggm_audio_gain(a,1,1,1,1,1)==0);
        std::array<float,512> pcm{};for(size_t i=0;i<pcm.size();++i)pcm[i]=(i%2)?-.3f:.6f;
        assert(ggm_audio_reverb(a,.5f,.9f,.1f,1)==0);assert(ggm_audio_clip(a,0,pcm.data(),96,48000)==0);
        assert(ggm_audio_play(a,0,0,0,0,0,1,2,60,6)>=0);
        for(unsigned slot=0;slot<4;++slot){
            assert(ggm_audio_stream_create(a,slot,24000,256)==0);
            assert(ggm_audio_stream_write(a,slot,pcm.data(),256,1)==256);
            assert(ggm_audio_stream_free(a,slot)==0);int voice=ggm_audio_stream_play(a,slot,1,.5f);assert(voice>=0);
            assert(ggm_audio_fade(a,voice,0,20,1)==0);
        }
        std::array<float,32768> samples{};assert(ggm_audio_render(a,samples.data(),16384)==16384);
        for(float x:samples)assert(std::isfinite(x)&&std::abs(x)<=.99001f);
        for(unsigned slot=0;slot<4;++slot){assert(ggm_audio_stream_active(a,slot)<0);assert(ggm_audio_stream_create(a,slot,48000,512)==0);}
        ggm_audio_destroy(a);
    }
    for(int n=0;n<16;++n){
        auto* a=ggm_audio_create(48000);assert(a);assert(ggm_audio_gain(a,1,1,1,1,1)==0);
        std::array<float,4800> pcm{};for(size_t i=0;i<pcm.size();i+=2)pcm[i]=.4f;
        assert(ggm_audio_clip_channels(a,8,pcm.data(),2400,24000,2)==0);
        int v=ggm_audio_play(a,8,0,0,0,0,1,2,60,0);assert(v>=0);auto token=ggm_audio_voice_token(a,v);assert(token>0);
        assert(ggm_audio_pitch(a,v,2)==0);std::array<float,8192> stereo{};
        assert(ggm_audio_render(a,stereo.data(),4096)==4096);double energy=0;
        for(size_t i=0;i<stereo.size();i+=2){energy+=stereo[i]*stereo[i];assert(stereo[i+1]==0);}
        assert(energy>1&&!ggm_audio_voice_active(a,v));
        int next=ggm_audio_play(a,8,0,0,0,0,1,2,60,0);assert(next==v&&ggm_audio_voice_token(a,next)!=token);
        assert(ggm_audio_pitch(a,next,0)==-1&&ggm_audio_pitch(a,next,9)==-1);
        assert(ggm_audio_clip_channels(a,9,pcm.data(),2400,24000,3)==-1);ggm_audio_destroy(a);
    }
    GgmInstance row{1,2,3,1,10,20,30,1,1,1,1,.5};std::array<float,20> out{};
    assert(ggm_pack_instances(&row,1,out.data(),1)==1&&out[15]==.5);
    row.x=std::numeric_limits<double>::quiet_NaN();out.fill(17);
    assert(ggm_pack_instances(&row,1,out.data(),1)==-1&&out[0]==17);
    std::cout<<"{\"status\":\"PASS\",\"lua_host_api_tested\":"<<(host_api?"true":"false")<<",\"checks\":[\"instance-buffer\",\"audio-voices-limiter-lifetime\",\"audio-reverb-stream-fade-lifetime\",\"audio-stereo-pitch-voice-generation\",\"Lua-sandbox-instructions-memory-lifetime\"]}\n";
}
