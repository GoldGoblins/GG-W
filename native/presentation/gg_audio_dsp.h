#pragma once
// GgEngine's 2 ms look-ahead limiter and vendored Kira/Freeverb equations.
// MIT attribution is recorded in provenance.json and backend/licenses.
#include <array>
#include <algorithm>
#include <cmath>
#include <vector>
namespace gg_audio {
struct Stereo { float l=0,r=0; };
struct Limiter {
    struct Minimum { unsigned long long at=0; float gain=1; };
    std::vector<Stereo> delay;std::vector<Minimum> window;std::vector<float> history;
    size_t cursor=0,head=0,count=0;unsigned long long n=0;double sum=0;float gain=1,release;
    explicit Limiter(unsigned rate):delay(std::max(1u,unsigned(std::round(.002*rate)))),window(delay.size()+2),history(delay.size(),1),sum(delay.size()),release(std::exp(-1.f/(.12f*rate))) {}
    Stereo step(Stereo in) {
        const float peak=std::max(std::abs(in.l),std::abs(in.r)),required=peak>.99f?.99f/peak:1;
        while(count&&window[(head+count-1)%window.size()].gain>=required)--count;
        window[(head+count)%window.size()]={n,required};++count;
        const auto oldest=n>delay.size()?n-delay.size():0;
        while(count&&window[head].at<oldest){head=(head+1)%window.size();--count;}
        float minimum=count?window[head].gain:1;
        sum+=double(minimum)-history[cursor];history[cursor]=minimum;
        gain=std::min(float(sum/delay.size()),1-(1-gain)*release);
        Stereo out={delay[cursor].l*gain,delay[cursor].r*gain};delay[cursor]=in;cursor=(cursor+1)%delay.size();++n;return out;
    }
};
struct Filter {
    std::vector<float> data;size_t cursor=0;float store=0;
    void init(unsigned n){data.assign(std::max(1u,n),0);cursor=0;store=0;}
    float comb(float input,float feedback,float damping){float out=data[cursor];store=out*(1-damping)+store*damping;data[cursor]=input+store*feedback;cursor=(cursor+1)%data.size();return out;}
    float allpass(float input){float old=data[cursor];data[cursor]=input+old*.5f;cursor=(cursor+1)%data.size();return old-input;}
};
struct Reverb {
    std::array<std::array<Filter,2>,8> combs;std::array<std::array<Filter,2>,4> passes;
    float wet=0,feedback=.9f,damping=.1f,width=1;
    explicit Reverb(unsigned rate){
        const unsigned comb[]={1116,1188,1277,1356,1422,1491,1557,1617},pass[]={556,441,341,225};
        for(unsigned ch=0;ch<2;++ch){for(unsigned i=0;i<8;++i)combs[i][ch].init(unsigned((comb[i]+ch*23)*double(rate)/44100));for(unsigned i=0;i<4;++i)passes[i][ch].init(unsigned((pass[i]+ch*23)*double(rate)/44100));}
    }
    Stereo step(Stereo in){
        Stereo out;float mono=(in.l+in.r)*.015f;
        for(auto& pair:combs){out.l+=pair[0].comb(mono,feedback,damping);out.r+=pair[1].comb(mono,feedback,damping);}
        for(auto& pair:passes){out.l=pair[0].allpass(out.l);out.r=pair[1].allpass(out.r);}
        const float a=width*.5f+.5f,b=(1-width)*.5f;
        return {(out.l*a+out.r*b)*wet,(out.r*a+out.l*b)*wet};
    }
};
}
