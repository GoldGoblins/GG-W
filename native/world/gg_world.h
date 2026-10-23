// GG world core. GgEngine-derived algorithms: Copyright (c) 2026 Sam, MIT.
// Original notice: ../../backend/licenses/engine-MIT.txt. GG adaptations below.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#if defined(_WIN32) && defined(GG_NATIVE_BUILD)
#define GGW_API __declspec(dllexport)
#elif defined(_WIN32)
#define GGW_API __declspec(dllimport)
#elif defined(__GNUC__)
#define GGW_API __attribute__((visibility("default")))
#else
#define GGW_API
#endif
typedef struct { double origin[3], forward[3], right[3], up[3], tangent, aspect, far_clip; } GgwView;
typedef struct { double low[3], high[3]; } GgwBox;
typedef struct { double center[3], radius; } GgwSphere;
typedef struct { int64_t x, z; int32_t inner, outer; } GgwWindow;
typedef struct { int64_t x, z; } GgwCell;
typedef struct { uint64_t id; double x, z, time; uint8_t stamped; } GgwStamp;
// Counts return -1 on invalid inputs; cache put/touch return 0 on success.
// Handles have one owner; callers serialize access, including destruction.
GGW_API uint32_t ggw_abi_version(void);
GGW_API int ggw_window(double x, double z, double far_clip, double cell_m, GgwWindow* out);
GGW_API int ggw_grid_candidates(double x, double z, double cell_m, uint32_t radius, GgwCell* out, uint32_t capacity);
GGW_API int ggw_cull_spheres(const GgwView* view, const GgwSphere* spheres, uint32_t count, uint8_t* visible);
GGW_API void* ggw_index_create(const GgwBox* boxes, uint32_t count);
GGW_API void ggw_index_destroy(void* index);
GGW_API int ggw_index_select(void* index, const GgwView* view, double padding, uint32_t* rows, double* distances, uint32_t capacity);
GGW_API int ggw_index_select_subset(void* index, const GgwView* view, double padding, const uint32_t* candidates, uint32_t count, uint32_t* rows, double* distances, uint32_t capacity);
GGW_API void* ggw_cache_create(uint32_t capacity);
GGW_API void ggw_cache_destroy(void* cache);
GGW_API int ggw_cache_put(void* cache, uint64_t id, uint64_t* evicted);
GGW_API int ggw_cache_touch(void* cache, uint64_t id);
GGW_API int ggw_cache_touch_many(void* cache, const uint64_t* ids, uint32_t count);
GGW_API int ggw_cache_move(void* cache, uint64_t id, uint8_t last);
GGW_API int ggw_cache_erase(void* cache, uint64_t id);
GGW_API void ggw_cache_clear(void* cache);
GGW_API int ggw_cache_scope(void* cache, double x, double z, double radius, double now, uint64_t* expired, uint32_t capacity);
GGW_API int ggw_cache_stamps(void* cache, GgwStamp* out, uint32_t capacity);
#ifdef __cplusplus
}
#endif
