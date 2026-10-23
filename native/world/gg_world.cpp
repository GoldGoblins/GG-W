// Cache and window algorithms ported from samwhosung/engine (MIT).
// See provenance.json for the exact source files and intentional adaptations.
#include "gg_world.h"
#include <algorithm>
#include <cmath>
#include <list>
#include <unordered_map>
#include <vector>

namespace {
constexpr uint32_t MAX_ROWS = 65536;
constexpr double COORD_LIMIT = 1e12;
bool finite_coord(double v) { return std::isfinite(v) && std::abs(v) <= COORD_LIMIT; }
bool valid_view(const GgwView* v) {
    if (!v || !std::isfinite(v->tangent) || v->tangent <= 0 || v->tangent > 100 ||
        !std::isfinite(v->aspect) || v->aspect <= 0 || v->aspect > 100 ||
        !finite_coord(v->far_clip) || v->far_clip <= 0) return false;
    const double* axes[] = {v->forward, v->right, v->up};
    for (int i=0; i<3; ++i) if (!finite_coord(v->origin[i])) return false;
    for (auto axis : axes) {
        double length = 0;
        for (int i=0; i<3; ++i) {
            if (!std::isfinite(axis[i])) return false;
            length += axis[i]*axis[i];
        }
        if (std::abs(length-1) > 1e-6) return false;
    }
    for (int a=0; a<3; ++a) for (int b=a+1; b<3; ++b) {
        double dot=0; for (int i=0; i<3; ++i) dot+=axes[a][i]*axes[b][i];
        if (std::abs(dot)>1e-6) return false;
    }
    return true;
}
bool valid_box(const GgwBox& b) {
    for (int i=0; i<3; ++i)
        if (!finite_coord(b.low[i]) || !finite_coord(b.high[i]) || b.low[i]>b.high[i]) return false;
    return true;
}
struct Index { std::vector<GgwBox> boxes; };
struct Stamp { double x=0, z=0, time=0; bool stamped=false; std::list<uint64_t>::iterator lru; };
struct Cache {
    explicit Cache(uint32_t cap) : capacity(cap) { entries.reserve(cap); }
    uint32_t capacity;
    std::list<uint64_t> order;
    std::unordered_map<uint64_t, Stamp> entries;
    void erase(uint64_t id) {
        auto it=entries.find(id);
        if (it!=entries.end()) { order.erase(it->second.lru); entries.erase(it); }
    }
};
}

uint32_t ggw_abi_version(void) { return 1; }
int ggw_window(double x, double z, double far_clip, double cell_m, GgwWindow* out) {
    if (!out || !finite_coord(x) || !finite_coord(z) || !finite_coord(far_clip) ||
        !std::isfinite(cell_m) || cell_m<1e-6 || cell_m>COORD_LIMIT) return -1;
    const double cx=std::floor(x/cell_m), cz=std::floor(z/cell_m);
    const double inner=1+std::trunc(std::max(0.0,far_clip)/cell_m);
    if (std::abs(cx)>1e15 || std::abs(cz)>1e15 || inner>4096) return -1;
    *out={static_cast<int64_t>(cx),static_cast<int64_t>(cz),static_cast<int32_t>(inner),
          std::max(static_cast<int32_t>(inner)+2,8)};
    return 0;
}
int ggw_grid_candidates(double x, double z, double cell_m, uint32_t radius, GgwCell* out, uint32_t capacity) {
    GgwWindow window{};
    if (radius>32 || ggw_window(x,z,0,cell_m,&window)<0) return -1;
    const uint32_t count=(2*radius+1)*(2*radius+1);
    if (!out || capacity<count) return -1;
    try {
        struct Candidate { GgwCell cell; double distance; };
        std::vector<Candidate> candidates; candidates.reserve(count);
        for (int64_t dx=-static_cast<int64_t>(radius); dx<=radius; ++dx)
            for (int64_t dz=-static_cast<int64_t>(radius); dz<=radius; ++dz) {
                GgwCell c{window.x+dx,window.z+dz};
                double px=(c.x+.5)*cell_m-x, pz=(c.z+.5)*cell_m-z;
                candidates.push_back({c,px*px+pz*pz});
            }
        // Equal priorities retain the original x-major grid order.
        std::stable_sort(candidates.begin(),candidates.end(),[](const auto& a,const auto& b){return a.distance<b.distance;});
        for (uint32_t i=0;i<count;++i) out[i]=candidates[i].cell;
        return static_cast<int>(count);
    } catch (...) { return -1; }
}
int ggw_cull_spheres(const GgwView* view, const GgwSphere* spheres, uint32_t count, uint8_t* visible) {
    if (!valid_view(view) || count>MAX_ROWS || (count && (!spheres || !visible))) return -1;
    for (uint32_t n=0;n<count;++n) {
        const auto& s=spheres[n];
        if (!finite_coord(s.radius) || s.radius<0) return -1;
        for (double c:s.center) if (!finite_coord(c)) return -1;
    }
    const double tx=view->tangent*view->aspect;
    const double side_scale=std::sqrt(1+tx*tx), up_scale=std::sqrt(1+view->tangent*view->tangent);
    for (uint32_t n=0;n<count;++n) {
        const auto& s=spheres[n]; double depth=0,side=0,up=0;
        for (int i=0;i<3;++i) {
            const double d=s.center[i]-view->origin[i];
            depth+=d*view->forward[i]; side+=d*view->right[i]; up+=d*view->up[i];
        }
        // Signed side planes: conservative for a sphere straddling the camera.
        visible[n]=depth>=-s.radius && depth<=view->far_clip+s.radius &&
            std::abs(side)<=depth*tx+s.radius*side_scale &&
            std::abs(up)<=depth*view->tangent+s.radius*up_scale;
    }
    return static_cast<int>(count);
}
void* ggw_index_create(const GgwBox* boxes,uint32_t count) {
    if (count>MAX_ROWS || (count && !boxes)) return nullptr;
    for (uint32_t i=0;i<count;++i) if (!valid_box(boxes[i])) return nullptr;
    try {
        auto index=new Index;
        try { if (count) index->boxes.assign(boxes,boxes+count); }
        catch (...) { delete index; return nullptr; }
        return index;
    } catch (...) { return nullptr; }
}
void ggw_index_destroy(void* index) { delete static_cast<Index*>(index); }
int ggw_index_select(void* index,const GgwView* view,double padding,uint32_t* rows,double* distances,uint32_t capacity) {
    if (!index) return -1;
    return ggw_index_select_subset(index,view,padding,nullptr,static_cast<uint32_t>(static_cast<Index*>(index)->boxes.size()),rows,distances,capacity);
}
int ggw_index_select_subset(void* index,const GgwView* view,double padding,const uint32_t* candidates,uint32_t n_candidates,uint32_t* rows,double* distances,uint32_t capacity) {
    if (!index || !valid_view(view) || !finite_coord(padding) || padding<0) return -1;
    const auto& boxes=static_cast<Index*>(index)->boxes;
    if (n_candidates>MAX_ROWS || capacity<n_candidates || (n_candidates && (!rows || !distances))) return -1;
    if (!candidates && n_candidates!=boxes.size()) return -1;
    if (candidates) for (uint32_t i=0;i<n_candidates;++i) if (candidates[i]>=boxes.size()) return -1;
    const double reach=view->far_clip*std::sqrt(1+view->tangent*view->tangent*(1+view->aspect*view->aspect))+padding;
    int count=0;
    for (uint32_t i=0;i<n_candidates;++i) {
        const uint32_t n=candidates?candidates[i]:i;
        double distance2=0;
        for (int i=0;i<3;++i) {
            const double d=std::max({boxes[n].low[i]-view->origin[i],0.0,view->origin[i]-boxes[n].high[i]});
            distance2+=d*d;
        }
        const double distance=std::sqrt(distance2);
        if (distance<=reach) { rows[count]=n; distances[count++]=distance; }
    }
    return count;
}
void* ggw_cache_create(uint32_t capacity) {
    if (!capacity || capacity>MAX_ROWS) return nullptr;
    try { return new Cache(capacity); } catch (...) { return nullptr; }
}
void ggw_cache_destroy(void* cache) { delete static_cast<Cache*>(cache); }
int ggw_cache_put(void* cache,uint64_t id,uint64_t* evicted) {
    if (!cache || !id || !evicted) return -1;
    auto& c=*static_cast<Cache*>(cache); *evicted=0;
    if (c.entries.count(id)) return ggw_cache_touch(cache,id);
    try {
        c.order.push_back(id);
        try { c.entries.emplace(id,Stamp{0,0,0,false,std::prev(c.order.end())}); }
        catch (...) { c.order.pop_back(); return -1; }
        if (c.entries.size()>c.capacity) { *evicted=c.order.front(); c.erase(*evicted); }
        return 0;
    } catch (...) { return -1; }
}
int ggw_cache_touch(void* cache,uint64_t id) {
    if (!cache || !id) return -1;
    auto& c=*static_cast<Cache*>(cache); auto it=c.entries.find(id);
    if (it==c.entries.end()) return -1;
    it->second.stamped=false; c.order.splice(c.order.end(),c.order,it->second.lru);
    return 0;
}
int ggw_cache_touch_many(void* cache,const uint64_t* ids,uint32_t count) {
    if (!cache || count>MAX_ROWS || (count && !ids)) return -1;
    auto& c=*static_cast<Cache*>(cache);
    for (uint32_t i=0;i<count;++i) if (!ids[i] || !c.entries.count(ids[i])) return -1;
    for (uint32_t i=0;i<count;++i) ggw_cache_touch(cache,ids[i]);
    return 0;
}
int ggw_cache_move(void* cache,uint64_t id,uint8_t last) {
    if (!cache || !id) return -1;
    auto& c=*static_cast<Cache*>(cache);auto it=c.entries.find(id);
    if (it==c.entries.end()) return -1;
    c.order.splice(last?c.order.end():c.order.begin(),c.order,it->second.lru);
    return 0;
}
int ggw_cache_erase(void* cache,uint64_t id) {
    if (!cache) return -1;
    static_cast<Cache*>(cache)->erase(id); return 0;
}
void ggw_cache_clear(void* cache) {
    if (cache) { auto& c=*static_cast<Cache*>(cache); c.entries.clear(); c.order.clear(); }
}
int ggw_cache_scope(void* cache,double x,double z,double radius,double now,uint64_t* expired,uint32_t capacity) {
    if (!cache || !finite_coord(x) || !finite_coord(z) || !finite_coord(radius) || radius<0 || !finite_coord(now)) return -1;
    auto& c=*static_cast<Cache*>(cache);
    if (capacity<c.entries.size() || (!c.entries.empty() && !expired)) return -1;
    int count=0;
    for (auto it=c.order.begin();it!=c.order.end();) {
        const uint64_t id=*it++; auto& s=c.entries.at(id);
        if (!s.stamped) { s.x=x; s.z=z; s.time=now; s.stamped=true; }
        else if (std::hypot(s.x-x,s.z-z)>radius && now-s.time>=30.0) {
            expired[count++]=id; c.erase(id);
        }
    }
    return count;
}
int ggw_cache_stamps(void* cache,GgwStamp* out,uint32_t capacity) {
    if (!cache) return -1;
    const auto& c=*static_cast<Cache*>(cache);
    if (capacity<c.entries.size() || (!c.entries.empty() && !out)) return -1;
    int count=0;
    for (uint64_t id:c.order) {
        const auto& s=c.entries.at(id); out[count++]={id,s.x,s.z,s.time,static_cast<uint8_t>(s.stamped)};
    }
    return count;
}
