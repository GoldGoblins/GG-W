#include "gg_world.h"
#include <iostream>
int main() {
    GgwWindow window{};
    if (ggw_window(-.01,-64.01,256,64,&window) || window.x!=-1 || window.z!=-2 || window.inner!=5 || window.outer!=8) return 1;
    void* cache=ggw_cache_create(2); if (!cache) return 2;
    uint64_t evicted=0,expired[2]{};
    bool ok=ggw_cache_put(cache,1,&evicted)==0 && ggw_cache_scope(cache,0,0,100,0,expired,2)==0 &&
        ggw_cache_scope(cache,500,0,100,29,expired,2)==0 && ggw_cache_scope(cache,500,0,100,30,expired,2)==1 && expired[0]==1;
    ggw_cache_destroy(cache);
    if (!ok) return 3;
    GgwView view{{0,0,0},{0,0,1},{-1,0,0},{0,1,0},.4,1.6,100};
    GgwSphere spheres[2]{{{0,0,10},1.5},{{0,0,-10},1.5}};
    uint8_t visible[2]{};
    if (ggw_cull_spheres(&view,spheres,2,visible)!=2 || !visible[0] || visible[1]) return 4;
    GgwBox boxes[2]{{{-1,-1,10},{1,1,12}},{{999,0,1000},{1001,2,1002}}};
    void* index=ggw_index_create(boxes,2);if (!index) return 5;
    uint32_t rows[2]{};double distances[2]{};
    ok=ggw_index_select(index,&view,0,rows,distances,2)==1 && rows[0]==0 && distances[0]==10;
    ggw_index_destroy(index);if (!ok) return 6;
    // Repeated LRU insert/erase cycles exercise ownership and iterator lifetime.
    cache=ggw_cache_create(2);if (!cache) return 7;
    for (uint64_t id=1;id<20000;++id) {
        if (ggw_cache_put(cache,id,&evicted)<0 || ggw_cache_touch(cache,id)<0) return 8;
        if (ggw_cache_scope(cache,0,0,100,static_cast<double>(id),expired,2)<0) return 9;
    }
    ggw_cache_destroy(cache);
    std::cout << "{\"status\":\"PASS\",\"abi\":1,\"checks\":[\"negative-grid-window\",\"30-second-residency\",\"sphere-culling\",\"sector-selection\",\"LRU-lifetime-stress\"]}\n";
    return 0;
}
