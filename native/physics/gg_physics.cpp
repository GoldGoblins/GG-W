// GG adapter over the unmodified, MIT-licensed Box3D core.
#include "gg_physics.h"
#include "box3d/box3d.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr uint32_t max_events = 8192, max_vertices = 65536;
constexpr uint64_t max_geometry = 64ULL * 1024 * 1024, max_recording = 32ULL * 1024 * 1024;
std::mutex gate;
thread_local std::string error;
void require(bool ok, const char* message) { if (!ok) throw std::invalid_argument(message); }
double number(double x, double low, double high) {
    require(std::isfinite(x) && x >= low && x <= high, "physics number out of range"); return x;
}
b3Vec3 vec(const double* p, double limit=1e6) {
    require(p, "missing physics vector");
    return {float(number(p[0],-limit,limit)),float(number(p[1],-limit,limit)),float(number(p[2],-limit,limit))};
}
b3Pos pos(const double* p) {
    require(p, "missing physics position");
    return {number(p[0],-1e9,1e9),number(p[1],-1e9,1e9),number(p[2],-1e9,1e9)};
}
b3Quat quat(const double* p) {
    require(p, "missing physics rotation"); double n=0;
    for (int i=0;i<4;++i) { number(p[i],-1,1); n+=p[i]*p[i]; }
    require(std::abs(n-1)<1e-4, "physics rotation must be a unit quaternion");
    return {{float(p[0]),float(p[1]),float(p[2])},float(p[3])};
}
void store(double* out, b3Vec3 v) { out[0]=v.x;out[1]=v.y;out[2]=v.z; }
void store(double* out, b3Pos v) { out[0]=v.x;out[1]=v.y;out[2]=v.z; }
void store(double* out, b3Quat q) { out[0]=q.v.x;out[1]=q.v.y;out[2]=q.v.z;out[3]=q.s; }
struct Shape {
    b3ShapeId id{}; uint64_t body=0, bytes=0;
    b3HullData* hull=nullptr; b3MeshData* mesh=nullptr; b3HeightFieldData* height=nullptr;
    ~Shape() { if(hull)b3DestroyHull(hull);if(mesh)b3DestroyMesh(mesh);if(height)b3DestroyHeightField(height); }
};
struct Joint { b3JointId id{}; uint64_t a,b; };
struct World {
    b3WorldId id{}; uint32_t capacity=0; uint64_t next=1, bytes=0, steps=0;
    double step_ms=0; bool overflow=false, recording=false, recording_overflow=false;
    uint64_t recorded_geometry=0;
    b3Recording* record=nullptr;
    std::map<uint64_t,b3BodyId> bodies;
    std::map<uint64_t,std::unique_ptr<Shape>> shapes;
    std::map<uint64_t,Joint> joints;
    std::map<uint64_t,uint64_t> shape_keys;
    std::vector<GgpEvent> events;
    ~World() {
        if (B3_IS_NON_NULL(id)) { if(recording)b3World_StopRecording(id);b3DestroyWorld(id); }
        shapes.clear(); if(record)b3DestroyRecording(record);
    }
    void record_bound() {
        if(recording && (b3Recording_GetSize(record)>int(max_recording/2) || recorded_geometry>max_recording/2)) {
            // Overflow must never turn an already committed body mutation
            // into a failed creation with an unreachable native handle.
            b3World_StopRecording(id);recording=false;recording_overflow=true;
            b3DestroyRecording(record);record=nullptr;
        }
    }
};
std::map<uint64_t,std::unique_ptr<World>> worlds;
uint64_t next_world=1;
World& world(uint64_t id) { auto it=worlds.find(id);require(it!=worlds.end(),"closed or invalid physics world");return *it->second; }
b3BodyId body(World& w,uint64_t id) {
    auto it=w.bodies.find(id);require(it!=w.bodies.end(),"closed or invalid physics body");return it->second;
}
Joint& joint(World& w,uint64_t id) {
    auto it=w.joints.find(id);require(it!=w.joints.end(),"closed or invalid physics joint");return it->second;
}
template<class R,class F> R call(F f,R failure) noexcept {
    std::lock_guard<std::mutex> lock(gate);error.clear();
    try { return f(); } catch(const std::exception& e) { error=e.what(); }
    catch(...) { error="native physics operation failed"; } return failure;
}
uint64_t key(World& w,b3ShapeId id) {
    auto it=w.shape_keys.find(b3StoreShapeId(id));return it==w.shape_keys.end()?0:it->second;
}
void append(World& w,uint32_t kind,b3ShapeId a,b3ShapeId b,b3Pos p={},b3Vec3 n={},double speed=0) {
    if(w.events.size()==max_events) { w.overflow=true;return; }
    GgpEvent e{};e.kind=kind;e.shape_a=key(w,a);e.shape_b=key(w,b);
    auto aa=w.shapes.find(e.shape_a),bb=w.shapes.find(e.shape_b);
    e.body_a=aa==w.shapes.end()?0:aa->second->body;e.body_b=bb==w.shapes.end()?0:bb->second->body;
    store(e.point,p);store(e.normal,n);e.speed=speed;w.events.push_back(e);
}
GgpBodyState state(World& w,uint64_t key_) {
    auto id=body(w,key_);GgpBodyState s{};s.body=key_;
    store(s.position,b3Body_GetPosition(id));store(s.rotation,b3Body_GetRotation(id));
    store(s.linear_velocity,b3Body_GetLinearVelocity(id));store(s.angular_velocity,b3Body_GetAngularVelocity(id));
    s.mass=b3Body_GetMass(id);s.type=b3Body_GetType(id);s.awake=b3Body_IsAwake(id);return s;
}
std::vector<b3Vec3> points(const double* p,uint32_t count,uint32_t limit=max_vertices) {
    require(p && count>0 && count<=limit,"invalid physics point capacity");
    std::vector<b3Vec3> out;out.reserve(count);
    for(uint32_t i=0;i<count;++i)out.push_back(vec(p+i*3));
    return out;
}
struct CastContext { World* world;GgpHit result{}; };
float cast_hit(b3ShapeId id,b3Pos p,b3Vec3 n,float fraction,uint64_t,int,int,void* raw) {
    auto& c=*static_cast<CastContext*>(raw);
    if(!c.result.hit || fraction<c.result.fraction) {
        c.result.hit=1;c.result.shape=key(*c.world,id);
        auto it=c.world->shapes.find(c.result.shape);c.result.body=it==c.world->shapes.end()?0:it->second->body;
        store(c.result.point,p);store(c.result.normal,n);c.result.fraction=fraction;
    } return float(c.result.fraction);
}
struct OverlapContext { World* world;std::vector<uint64_t> keys;uint32_t capacity;bool overflow=false; };
bool overlap_hit(b3ShapeId id,void* raw) {
    auto& c=*static_cast<OverlapContext*>(raw);auto k=key(*c.world,id);
    if(std::find(c.keys.begin(),c.keys.end(),k)!=c.keys.end())return true;
    if(c.keys.size()==c.capacity) { c.overflow=true;return false; }
    c.keys.push_back(k);return true;
}
}

uint32_t ggp_abi_version(void) { return 1; }
const char* ggp_last_error(void) { return error.c_str(); }
uint64_t ggp_world_create(const GgpWorldDef* d) {
    return call<uint64_t>([&] {
        require(d && d->workers>=1 && d->workers<=16 && d->max_bodies>=1 && d->max_bodies<=8192 && worlds.size()<8,"physics world capacity invalid");
        auto def=b3DefaultWorldDef();def.gravity=vec(d->gravity,1000);def.workerCount=d->workers;
        def.enableContinuous=true;def.enableSleep=true;def.maximumLinearSpeed=1000;
        auto w=std::make_unique<World>();w->capacity=d->max_bodies;w->events.reserve(max_events);
        w->id=b3CreateWorld(&def);require(B3_IS_NON_NULL(w->id),"Box3D could not create world");
        uint64_t id=next_world++;worlds.emplace(id,std::move(w));return id;
    },0);
}
int ggp_world_destroy(uint64_t id) {
    return call<int>([&] { world(id);worlds.erase(id);return 0; },-1);
}
int ggp_world_gravity(uint64_t id,const double* gravity) {
    return call<int>([&] { auto& w=world(id);b3World_SetGravity(w.id,vec(gravity,1000));w.record_bound();return 0; },-1);
}
int ggp_world_step(uint64_t id,double dt,uint32_t substeps) {
    return call<int>([&] {
        auto& w=world(id);number(dt,1e-6,1./30);require(substeps>=1 && substeps<=16,"physics substeps invalid");
        auto begin=std::chrono::steady_clock::now();b3World_Step(w.id,float(dt),int(substeps));
        w.step_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();++w.steps;
        w.events.clear();w.overflow=false;
        auto c=b3World_GetContactEvents(w.id);
        for(int i=0;i<c.beginCount;++i)append(w,0,c.beginEvents[i].shapeIdA,c.beginEvents[i].shapeIdB);
        for(int i=0;i<c.endCount;++i)append(w,1,c.endEvents[i].shapeIdA,c.endEvents[i].shapeIdB);
        for(int i=0;i<c.hitCount;++i) {auto& e=c.hitEvents[i];append(w,2,e.shapeIdA,e.shapeIdB,e.point,e.normal,e.approachSpeed);}
        auto s=b3World_GetSensorEvents(w.id);
        for(int i=0;i<s.beginCount;++i)append(w,3,s.beginEvents[i].sensorShapeId,s.beginEvents[i].visitorShapeId);
        for(int i=0;i<s.endCount;++i)append(w,4,s.endEvents[i].sensorShapeId,s.endEvents[i].visitorShapeId);
        auto b=b3World_GetBodyEvents(w.id);
        for(int i=0;i<b.moveCount;++i)if(b.moveEvents[i].fellAsleep) {
            if(w.events.size()==max_events) {w.overflow=true;break;}
            GgpEvent e{};e.kind=5;e.body_a=uint64_t(reinterpret_cast<uintptr_t>(b.moveEvents[i].userData));
            store(e.point,b.moveEvents[i].transform.p);w.events.push_back(e);
        }
        w.record_bound();return 0;
    },-1);
}
int ggp_world_stats(uint64_t id,GgpStats* out) {
    return call<int>([&] {
        require(out,"missing physics stats output");auto& w=world(id);auto c=b3World_GetCounters(w.id);
        *out={uint32_t(w.bodies.size()),uint32_t(w.shapes.size()),uint32_t(w.joints.size()),uint32_t(c.contactCount),
              uint32_t(b3World_GetAwakeBodyCount(w.id)),uint32_t(b3World_GetWorkerCount(w.id)),uint32_t(w.events.size()),
              uint32_t(w.overflow),uint32_t(w.recording),uint32_t(w.recording_overflow),w.bytes,w.steps,w.step_ms};return 0;
    },-1);
}
uint64_t ggp_body_create(uint64_t wid,const GgpBodyDef* d) {
    return call<uint64_t>([&] {
        auto& w=world(wid);require(d && d->type<=2 && d->flags<=15 && d->locks<=63 && w.bodies.size()<w.capacity,"invalid physics body definition or capacity");
        auto def=b3DefaultBodyDef();def.type=b3BodyType(d->type);def.position=pos(d->position);def.rotation=quat(d->rotation);
        def.linearVelocity=vec(d->linear_velocity,1000);def.angularVelocity=vec(d->angular_velocity,1000);
        def.linearDamping=float(number(d->linear_damping,0,1000));def.angularDamping=float(number(d->angular_damping,0,1000));
        def.gravityScale=float(number(d->gravity_scale,-100,100));def.isBullet=d->flags&1;def.enableSleep=d->flags&2;
        def.isEnabled=d->flags&4;def.isAwake=d->flags&8;
        def.motionLocks={bool(d->locks&1),bool(d->locks&2),bool(d->locks&4),bool(d->locks&8),bool(d->locks&16),bool(d->locks&32)};
        uint64_t k=w.next++;def.userData=reinterpret_cast<void*>(uintptr_t(k));
        auto id=b3CreateBody(w.id,&def);require(B3_IS_NON_NULL(id),"Box3D could not create body");
        try {w.bodies.emplace(k,id);}catch(...) {b3DestroyBody(id);throw;}
        w.record_bound();return k;
    },0);
}
int ggp_body_destroy(uint64_t wid,uint64_t bid) {
    return call<int>([&] {
        auto& w=world(wid);auto id=body(w,bid);b3DestroyBody(id);
        for(auto it=w.joints.begin();it!=w.joints.end();)if(it->second.a==bid || it->second.b==bid)it=w.joints.erase(it);else ++it;
        for(auto it=w.shapes.begin();it!=w.shapes.end();)if(it->second->body==bid) {
            w.bytes-=it->second->bytes;w.shape_keys.erase(b3StoreShapeId(it->second->id));it=w.shapes.erase(it);
        }else ++it;
        w.bodies.erase(bid);w.record_bound();return 0;
    },-1);
}
int ggp_body_state(uint64_t wid,uint64_t bid,GgpBodyState* out) {
    return call<int>([&] {require(out,"missing physics state output");*out=state(world(wid),bid);return 0;},-1);
}
int ggp_body_states(uint64_t wid,GgpBodyState* out,uint32_t capacity) {
    return call<int>([&] {auto& w=world(wid);require(capacity>=w.bodies.size() && (out || w.bodies.empty()),"physics state output capacity exceeded");
        uint32_t i=0;for(auto& b:w.bodies)out[i++]=state(w,b.first);return int(i);},-1);
}
int ggp_body_transform(uint64_t wid,uint64_t bid,const double* p,const double* q) {
    return call<int>([&] {auto& w=world(wid);auto pp=pos(p);auto qq=quat(q);b3Body_SetTransform(body(w,bid),pp,qq);w.record_bound();return 0;},-1);
}
int ggp_body_velocity(uint64_t wid,uint64_t bid,const double* l,const double* a) {
    return call<int>([&] {auto& w=world(wid);auto ll=vec(l,1000);auto aa=vec(a,1000);auto b=body(w,bid);
        b3Body_SetLinearVelocity(b,ll);b3Body_SetAngularVelocity(b,aa);w.record_bound();return 0;},-1);
}
int ggp_body_force(uint64_t wid,uint64_t bid,const double* value,const double* point,uint32_t mode) {
    return call<int>([&] {auto& w=world(wid);auto b=body(w,bid);auto v=vec(value);require(mode<=3,"invalid physics force mode");
        auto p=point?pos(point):b3Body_GetWorldCenterOfMass(b);
        if(mode==0)b3Body_ApplyForce(b,v,p,true);else if(mode==1)b3Body_ApplyLinearImpulse(b,v,p,true);
        else if(mode==2)b3Body_ApplyTorque(b,v,true);else b3Body_ApplyAngularImpulse(b,v,true);
        w.record_bound();return 0;},-1);
}
int ggp_body_awake(uint64_t wid,uint64_t bid,uint32_t awake) {
    return call<int>([&] {require(awake<=1,"invalid physics awake flag");auto& w=world(wid);b3Body_SetAwake(body(w,bid),awake);w.record_bound();return 0;},-1);
}
uint64_t ggp_shape_create(uint64_t wid,uint64_t bid,const GgpShapeDef* d) {
    return call<uint64_t>([&] {
        auto& w=world(wid);auto b=body(w,bid);
        require(d && d->kind<=7 && d->flags<=15 && w.shapes.size()<w.capacity*4,"invalid physics shape definition or capacity");
        auto def=b3DefaultShapeDef();def.density=float(number(d->density,0,1e6));
        def.baseMaterial.friction=float(number(d->friction,0,100));def.baseMaterial.restitution=float(number(d->restitution,0,1));
        def.filter.categoryBits=d->category;def.filter.maskBits=d->mask;def.isSensor=d->flags&1;
        def.enableSensorEvents=d->flags&2;def.enableContactEvents=d->flags&4;def.enableHitEvents=d->flags&8;
        auto center=vec(d->center);auto rotation=quat(d->rotation);auto s=std::make_unique<Shape>();s->body=bid;
        for(double x:d->dimensions)number(x,0,50000);
        auto transform=b3Transform{center,rotation};
        if(d->kind==0) {
            require(d->dimensions[0]>=.001 && d->dimensions[1]>=.001 && d->dimensions[2]>=.001,"invalid box dimensions");
            auto h=b3MakeTransformedBoxHull(float(d->dimensions[0]),float(d->dimensions[1]),float(d->dimensions[2]),transform);
            s->bytes=h.base.byteCount;
            require(w.bytes+s->bytes<=max_geometry,"physics geometry capacity exceeded");
            s->id=b3CreateHullShape(b,&def,&h.base);
        } else if(d->kind==1) {
            require(d->dimensions[0]>=.001,"invalid sphere radius");b3Sphere sphere{center,float(d->dimensions[0])};s->id=b3CreateSphereShape(b,&def,&sphere);
        } else if(d->kind==2) {
            require(d->dimensions[0]>=.001,"invalid capsule radius");auto axis=b3RotateVector(rotation,{0,float(d->dimensions[1]),0});
            b3Capsule capsule{b3Sub(center,axis),b3Add(center,axis),float(d->dimensions[0])};s->id=b3CreateCapsuleShape(b,&def,&capsule);
        } else if(d->kind==3 || d->kind==6 || d->kind==7) {
            if(d->kind==3) {auto pp=points(d->points,d->point_count,256);require(pp.size()>=4,"hull needs four points");s->hull=b3CreateHull(pp.data(),int(pp.size()),256);}
            else {require(d->dimensions[0]>=.001 && d->dimensions[1]>=.001,"invalid cylinder or cone dimensions");
                if(d->kind==6)s->hull=b3CreateCylinder(float(d->dimensions[1]*2),float(d->dimensions[0]),0,16);
                else if(d->dimensions[2]>0)s->hull=b3CreateCone(float(d->dimensions[1]*2),float(d->dimensions[0]),float(d->dimensions[2]),16);
                else {
                    b3Vec3 cone[17]{};cone[16]={0,float(d->dimensions[1]),0};
                    for(int i=0;i<16;++i) {float angle=float(i)*2*B3_PI/16;
                        cone[i]={float(d->dimensions[0])*b3Cos(angle),-float(d->dimensions[1]),float(d->dimensions[0])*b3Sin(angle)};}
                    s->hull=b3CreateHull(cone,17,17);
                }
            }
            require(s->hull,"invalid convex hull geometry");s->bytes=s->hull->byteCount;
            require(w.bytes+s->bytes<=max_geometry,"physics geometry capacity exceeded");
            s->id=b3CreateTransformedHullShape(b,&def,s->hull,transform,b3Vec3_one);
        } else if(d->kind==4) {
            require(b3Body_GetType(b)!=b3_dynamicBody,"triangle meshes require a static or kinematic body");
            auto pp=points(d->points,d->point_count);require(d->indices && d->index_count>=3 && d->index_count%3==0 && d->index_count<=393216,"invalid mesh triangle capacity");
            require(w.bytes+pp.size()*64+d->index_count*32<=max_geometry,"physics geometry capacity exceeded");
            for(auto& p:pp)p=b3TransformPoint(transform,p);
            std::vector<int32_t> indices;indices.reserve(d->index_count);
            for(uint32_t i=0;i<d->index_count;++i) {require(d->indices[i]<pp.size(),"invalid mesh index");indices.push_back(int32_t(d->indices[i]));}
            for(uint32_t i=0;i<d->index_count;i+=3)require(b3LengthSquared(b3Cross(b3Sub(pp[indices[i+1]],pp[indices[i]]),b3Sub(pp[indices[i+2]],pp[indices[i]])))>1e-12,"degenerate mesh triangle");
            b3MeshDef md{};md.vertices=pp.data();md.indices=indices.data();md.vertexCount=int(pp.size());md.triangleCount=int(indices.size()/3);md.identifyEdges=true;
            s->mesh=b3CreateMesh(&md,nullptr,0);require(s->mesh,"invalid mesh geometry");s->bytes=s->mesh->byteCount;
            require(w.bytes+s->bytes<=max_geometry,"physics geometry capacity exceeded");s->id=b3CreateMeshShape(b,&def,s->mesh,b3Vec3_one);
        } else {
            require(b3Body_GetType(b)!=b3_dynamicBody,"height fields require a static or kinematic body");
            require(d->count_x>=2 && d->count_z>=2 && uint64_t(d->count_x)*d->count_z<=max_vertices && d->point_count==d->count_x*d->count_z && d->points,"invalid height field capacity");
            require(w.bytes+d->point_count*64<=max_geometry,"physics geometry capacity exceeded");
            require(b3LengthSquared(center)==0 && std::abs(rotation.s-1)<1e-6,"height field transform belongs on its body");
            require(d->dimensions[0]>=.001 && d->dimensions[1]>=.001 && d->dimensions[2]>=.001,"invalid height field scale");
            std::vector<float> heights;heights.reserve(d->point_count);for(uint32_t i=0;i<d->point_count;++i)heights.push_back(float(number(d->points[i],-50000,50000)));
            b3HeightFieldDef hd{};hd.heights=heights.data();hd.countX=int(d->count_x);hd.countZ=int(d->count_z);hd.scale=vec(d->dimensions);
            hd.globalMinimumHeight=*std::min_element(heights.begin(),heights.end());hd.globalMaximumHeight=*std::max_element(heights.begin(),heights.end());
            s->height=b3CreateHeightField(&hd);require(s->height,"invalid height field geometry");s->bytes=s->height->byteCount;
            require(w.bytes+s->bytes<=max_geometry,"physics geometry capacity exceeded");s->id=b3CreateHeightFieldShape(b,&def,s->height);
        }
        require(B3_IS_NON_NULL(s->id),"Box3D could not create shape");uint64_t k=w.next++;auto native=s->id;auto bytes=s->bytes;
        try {w.shape_keys.emplace(b3StoreShapeId(native),k);w.shapes.emplace(k,std::move(s));}
        catch(...) {w.shape_keys.erase(b3StoreShapeId(native));b3DestroyShape(native,true);throw;}
        w.bytes+=bytes;if(w.recording)w.recorded_geometry+=bytes;w.record_bound();return k;
    },0);
}
int ggp_shape_destroy(uint64_t wid,uint64_t sid) {
    return call<int>([&] {auto& w=world(wid);auto it=w.shapes.find(sid);require(it!=w.shapes.end(),"closed or invalid physics shape");
        b3DestroyShape(it->second->id,true);w.shape_keys.erase(b3StoreShapeId(it->second->id));w.bytes-=it->second->bytes;w.shapes.erase(it);w.record_bound();return 0;},-1);
}
uint64_t ggp_joint_create(uint64_t wid,const GgpJointDef* d) {
    return call<uint64_t>([&] {
        auto& w=world(wid);require(d && d->kind<=8 && d->flags<=15 && d->body_a!=d->body_b && w.joints.size()<w.capacity*4,"invalid physics joint definition or capacity");
        auto a=body(w,d->body_a),b=body(w,d->body_b);
        require(b3Body_GetType(a)==b3_dynamicBody || b3Body_GetType(b)==b3_dynamicBody,"joint needs a dynamic body");
        auto base=b3DefaultDistanceJointDef().base;base.bodyIdA=a;base.bodyIdB=b;base.localFrameA={vec(d->anchor_a),quat(d->rotation_a)};base.localFrameB={vec(d->anchor_b),quat(d->rotation_b)};
        base.collideConnected=d->flags&1;bool spring=d->flags&2,limit=d->flags&4,motor=d->flags&8;
        float hz=float(number(d->hertz,0,1000)),damping=float(number(d->damping,0,100)),speed=float(number(d->motor_speed,-1000,1000)),maxmotor=float(number(d->max_motor,0,1e6));
        float length=float(number(d->length,.001,100000)),lo=float(number(d->lower,-100000,100000)),hi=float(number(d->upper,-100000,100000));require(lo<=hi,"joint lower limit exceeds upper limit");
        auto linear=vec(d->linear_velocity,1000),angular=vec(d->angular_velocity,1000);b3JointId id{};
        switch(d->kind) {
        case 0:{auto x=b3DefaultDistanceJointDef();x.base=base;x.length=length;x.enableSpring=spring;x.hertz=hz;x.dampingRatio=damping;x.enableLimit=limit;x.minLength=std::max(.001f,lo);x.maxLength=std::max(x.minLength,hi);x.enableMotor=motor;x.motorSpeed=speed;x.maxMotorForce=maxmotor;id=b3CreateDistanceJoint(w.id,&x);break;}
        case 1:{auto x=b3DefaultRevoluteJointDef();x.base=base;x.enableSpring=spring;x.hertz=hz;x.dampingRatio=damping;x.enableLimit=limit;x.lowerAngle=lo;x.upperAngle=hi;x.enableMotor=motor;x.motorSpeed=speed;x.maxMotorTorque=maxmotor;id=b3CreateRevoluteJoint(w.id,&x);break;}
        case 2:{auto x=b3DefaultPrismaticJointDef();x.base=base;x.enableSpring=spring;x.hertz=hz;x.dampingRatio=damping;x.enableLimit=limit;x.lowerTranslation=lo;x.upperTranslation=hi;x.enableMotor=motor;x.motorSpeed=speed;x.maxMotorForce=maxmotor;id=b3CreatePrismaticJoint(w.id,&x);break;}
        case 3:{auto x=b3DefaultSphericalJointDef();x.base=base;x.enableSpring=spring;x.hertz=hz;x.dampingRatio=damping;x.enableTwistLimit=limit;x.lowerTwistAngle=lo;x.upperTwistAngle=hi;x.enableMotor=motor;x.motorVelocity=angular;x.maxMotorTorque=maxmotor;id=b3CreateSphericalJoint(w.id,&x);break;}
        case 4:{auto x=b3DefaultWeldJointDef();x.base=base;x.linearHertz=spring?hz:0;x.angularHertz=spring?hz:0;x.linearDampingRatio=damping;x.angularDampingRatio=damping;id=b3CreateWeldJoint(w.id,&x);break;}
        case 5:{auto x=b3DefaultWheelJointDef();x.base=base;x.enableSuspensionSpring=spring;x.suspensionHertz=hz;x.suspensionDampingRatio=damping;x.enableSuspensionLimit=limit;x.lowerSuspensionLimit=lo;x.upperSuspensionLimit=hi;x.enableSpinMotor=motor;x.spinSpeed=speed;x.maxSpinTorque=maxmotor;id=b3CreateWheelJoint(w.id,&x);break;}
        case 6:{auto x=b3DefaultMotorJointDef();x.base=base;x.linearVelocity=linear;x.angularVelocity=angular;x.maxVelocityForce=maxmotor;x.maxVelocityTorque=maxmotor;x.linearHertz=spring?hz:0;x.angularHertz=spring?hz:0;id=b3CreateMotorJoint(w.id,&x);break;}
        case 7:{auto x=b3DefaultParallelJointDef();x.base=base;x.hertz=hz;x.dampingRatio=damping;x.maxTorque=maxmotor;id=b3CreateParallelJoint(w.id,&x);break;}
        case 8:{auto x=b3DefaultFilterJointDef();x.base=base;id=b3CreateFilterJoint(w.id,&x);break;}
        }
        require(B3_IS_NON_NULL(id),"Box3D could not create joint");uint64_t k=w.next++;
        try {w.joints.emplace(k,Joint{id,d->body_a,d->body_b});}catch(...) {b3DestroyJoint(id,true);throw;}
        w.record_bound();return k;
    },0);
}
int ggp_joint_destroy(uint64_t wid,uint64_t jid) {
    return call<int>([&] {auto& w=world(wid);b3DestroyJoint(joint(w,jid).id,true);w.joints.erase(jid);w.record_bound();return 0;},-1);
}
int ggp_joint_force(uint64_t wid,uint64_t jid,double* force,double* torque) {
    return call<int>([&] {require(force && torque,"missing joint force output");auto& w=world(wid);auto j=joint(w,jid).id;
        store(force,b3Joint_GetConstraintForce(j));store(torque,b3Joint_GetConstraintTorque(j));return 0;},-1);
}
int ggp_cast(uint64_t wid,const double* origin,const double* translation,const double* pp,uint32_t count,double radius,uint64_t mask,GgpHit* out) {
    return call<int>([&] {
        require(out,"missing cast output");auto& w=world(wid);auto o=pos(origin);auto t=vec(translation);number(radius,0,50000);
        require(b3LengthSquared(t)>0,"cast translation must be nonzero");auto filter=b3DefaultQueryFilter();filter.maskBits=mask;
        CastContext c{&w,{}};c.result.fraction=1;
        if(count==0) {require(radius==0,"ray radius must be zero");b3World_CastRay(w.id,o,t,filter,cast_hit,&c);}
        else {auto p=points(pp,count,256);b3ShapeProxy proxy{p.data(),int(count),float(radius)};b3World_CastShape(w.id,o,&proxy,t,filter,cast_hit,&c);}
        *out=c.result;return 0;
    },-1);
}
int ggp_overlap(uint64_t wid,const double* origin,const double* pp,uint32_t count,double radius,uint64_t mask,uint64_t* out,uint32_t capacity) {
    return call<int>([&] {
        require(out && capacity>=1 && capacity<=32768,"invalid overlap output capacity");auto& w=world(wid);auto o=pos(origin);auto p=points(pp,count,256);number(radius,0,50000);
        b3ShapeProxy proxy{p.data(),int(count),float(radius)};auto filter=b3DefaultQueryFilter();filter.maskBits=mask;
        OverlapContext c{&w,{},capacity,false};c.keys.reserve(capacity);b3World_OverlapShape(w.id,o,&proxy,filter,overlap_hit,&c);
        require(!c.overflow,"physics overlap output capacity exceeded");std::sort(c.keys.begin(),c.keys.end());
        std::copy(c.keys.begin(),c.keys.end(),out);return int(c.keys.size());
    },-1);
}
int ggp_events(uint64_t wid,GgpEvent* out,uint32_t capacity) {
    return call<int>([&] {auto& w=world(wid);require(capacity>=w.events.size() && (out || w.events.empty()),"physics event output capacity exceeded");
        std::copy(w.events.begin(),w.events.end(),out);return int(w.events.size());},-1);
}
int ggp_record_start(uint64_t wid) {
    return call<int>([&] {auto& w=world(wid);require(!w.recording,"physics recording already started");
        require(w.bytes<=max_recording/2,"physics geometry exceeds recording capacity");
        if(!w.record)w.record=b3CreateRecording(65536);
        require(w.record,"could not allocate recording");
        w.recording_overflow=false;w.recorded_geometry=w.bytes;
        b3World_StartRecording(w.id,w.record);w.recording=true;w.record_bound();return 0;},-1);
}
int ggp_record_stop(uint64_t wid) {
    return call<int>([&] {auto& w=world(wid);require(!w.recording_overflow,"physics recording capacity exceeded");require(w.record,"physics recording not started");
        if(w.recording) {b3World_StopRecording(w.id);w.recording=false;}
        int n=b3Recording_GetSize(w.record);require(n<=int(max_recording),"physics recording capacity exceeded");return n;},-1);
}
int ggp_record_copy(uint64_t wid,uint8_t* out,uint32_t capacity) {
    return call<int>([&] {auto& w=world(wid);require(w.record && !w.recording,"physics recording must be stopped");int n=b3Recording_GetSize(w.record);
        require(out && n<=int(max_recording) && capacity>=uint32_t(n),"physics recording output capacity exceeded");
        std::memcpy(out,b3Recording_GetData(w.record),n);return n;},-1);
}
int ggp_replay_validate(const uint8_t* data,uint32_t size) {
    return call<int>([&] {require(data && size>=16 && size<=max_recording,"invalid physics replay capacity");return b3ValidateReplay(data,int(size),1)?1:0;},-1);
}
