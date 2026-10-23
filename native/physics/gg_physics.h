// GG GAME ENGINE physics ABI. Box3D remains an independently attributed dependency.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#if defined(_WIN32) && defined(GG_NATIVE_BUILD)
#define GGP_API __declspec(dllexport)
#elif defined(_WIN32)
#define GGP_API __declspec(dllimport)
#elif defined(__GNUC__)
#define GGP_API __attribute__((visibility("default")))
#else
#define GGP_API
#endif
// Vectors use metres, seconds, kilograms; quaternions are x,y,z,w.
// Handles never own scene nodes. Calls are serialized, including destruction.
typedef struct {
    double gravity[3];
    uint32_t workers, max_bodies;
} GgpWorldDef;
typedef struct {
    double position[3], rotation[4], linear_velocity[3], angular_velocity[3];
    double linear_damping, angular_damping, gravity_scale;
    uint32_t type, flags, locks;
} GgpBodyDef;
typedef struct {
    uint32_t kind, flags;
    uint64_t category, mask;
    double density, friction, restitution, dimensions[3], center[3], rotation[4];
    const double* points;
    const uint32_t* indices;
    uint32_t point_count, index_count, count_x, count_z;
} GgpShapeDef;
typedef struct {
    uint64_t body;
    double position[3], rotation[4], linear_velocity[3], angular_velocity[3];
    double mass;
    uint32_t type, awake;
} GgpBodyState;
typedef struct {
    uint64_t body_a, body_b;
    uint32_t kind, flags;
    double anchor_a[3], anchor_b[3], rotation_a[4], rotation_b[4];
    double length, lower, upper, hertz, damping, motor_speed, max_motor;
    double linear_velocity[3], angular_velocity[3];
} GgpJointDef;
typedef struct {
    uint64_t shape, body;
    double point[3], normal[3], fraction;
    uint32_t hit;
} GgpHit;
typedef struct {
    uint32_t kind;
    uint64_t shape_a, shape_b, body_a, body_b;
    double point[3], normal[3], speed;
} GgpEvent;
typedef struct {
    uint32_t bodies, shapes, joints, contacts, awake, workers, events, event_overflow, recording, recording_overflow;
    uint64_t geometry_bytes, steps;
    double step_ms;
} GgpStats;
GGP_API uint32_t ggp_abi_version(void);
GGP_API const char* ggp_last_error(void);
GGP_API uint64_t ggp_world_create(const GgpWorldDef* def);
GGP_API int ggp_world_destroy(uint64_t world);
GGP_API int ggp_world_step(uint64_t world, double dt, uint32_t substeps);
GGP_API int ggp_world_gravity(uint64_t world, const double* gravity);
GGP_API int ggp_world_stats(uint64_t world, GgpStats* out);
GGP_API uint64_t ggp_body_create(uint64_t world, const GgpBodyDef* def);
GGP_API int ggp_body_destroy(uint64_t world, uint64_t body);
GGP_API int ggp_body_state(uint64_t world, uint64_t body, GgpBodyState* out);
GGP_API int ggp_body_states(uint64_t world, GgpBodyState* out, uint32_t capacity);
GGP_API int ggp_body_transform(uint64_t world, uint64_t body, const double* position, const double* rotation);
GGP_API int ggp_body_velocity(uint64_t world, uint64_t body, const double* linear, const double* angular);
GGP_API int ggp_body_force(uint64_t world, uint64_t body, const double* value, const double* point, uint32_t mode);
GGP_API int ggp_body_awake(uint64_t world, uint64_t body, uint32_t awake);
GGP_API uint64_t ggp_shape_create(uint64_t world, uint64_t body, const GgpShapeDef* def);
GGP_API int ggp_shape_destroy(uint64_t world, uint64_t shape);
GGP_API uint64_t ggp_joint_create(uint64_t world, const GgpJointDef* def);
GGP_API int ggp_joint_destroy(uint64_t world, uint64_t joint);
GGP_API int ggp_joint_force(uint64_t world, uint64_t joint, double* force, double* torque);
GGP_API int ggp_cast(uint64_t world, const double* origin, const double* translation,
    const double* points, uint32_t count, double radius, uint64_t mask, GgpHit* out);
GGP_API int ggp_overlap(uint64_t world, const double* origin, const double* points,
    uint32_t count, double radius, uint64_t mask, uint64_t* shapes, uint32_t capacity);
GGP_API int ggp_events(uint64_t world, GgpEvent* out, uint32_t capacity);
GGP_API int ggp_record_start(uint64_t world);
GGP_API int ggp_record_stop(uint64_t world);
GGP_API int ggp_record_copy(uint64_t world, uint8_t* out, uint32_t capacity);
GGP_API int ggp_replay_validate(const uint8_t* data, uint32_t size);
#ifdef __cplusplus
}
#endif
