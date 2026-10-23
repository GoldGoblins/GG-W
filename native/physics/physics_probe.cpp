#include "gg_physics.h"
#include <cmath>
#include <cstdio>
#include <stdexcept>
static void check(bool ok) { if(!ok)throw std::runtime_error(ggp_last_error()); }
int main() {
    try {
        GgpWorldDef wd{{0,-9.81,0},1,32};auto w=ggp_world_create(&wd);check(w!=0);
        GgpBodyDef bd{};bd.rotation[3]=1;bd.flags=14;bd.gravity_scale=1;
        bd.position[1]=-.5;auto ground=ggp_body_create(w,&bd);check(ground!=0);
        GgpShapeDef sd{};sd.rotation[3]=1;sd.category=1;sd.mask=UINT64_MAX;
        sd.density=1;sd.friction=.6;sd.flags=14;
        sd.dimensions[0]=5;sd.dimensions[1]=.5;sd.dimensions[2]=5;
        check(ggp_shape_create(w,ground,&sd)!=0);
        bd.type=2;bd.position[1]=4;auto ball=ggp_body_create(w,&bd);check(ball!=0);
        sd.kind=1;sd.dimensions[0]=.5;check(ggp_shape_create(w,ball,&sd)!=0);
        for(int i=0;i<240;++i)check(ggp_world_step(w,1./60,4)==0);
        GgpBodyState state{};check(ggp_body_state(w,ball,&state)==0);
        check(std::isfinite(state.position[1]) && std::abs(state.position[1]-.5)<.06);
        check(ggp_record_start(w)==0);
        for(int i=0;i<8;++i)check(ggp_world_step(w,1./60,4)==0);
        check(ggp_record_stop(w)>0);check(ggp_world_destroy(w)==0);
        std::printf("{\"status\":\"PASS\",\"backend\":\"BOX3D\",\"settled_y\":%.6f}\n",state.position[1]);return 0;
    }catch(const std::exception& e) {std::fprintf(stderr,"physics probe: %s\n",e.what());return 1;}
}
