#pragma once
#include <stdint.h>
#if defined(_WIN32) && defined(GG_NATIVE_BUILD)
#define GGM_API __declspec(dllexport)
#elif defined(_WIN32)
#define GGM_API __declspec(dllimport)
#else
#define GGM_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* Calls on a handle are serialized by the owner. No Qt/Python objects cross this ABI. */
typedef struct { double x,y,z,scale,pitch,yaw,roll,tint,r,g,b,alpha; } GgmInstance;
typedef struct { double x,y,z,yaw,time,speed,health,resource; uint32_t running; } GgmSnapshot;
GGM_API uint32_t ggm_abi_version(void);
GGM_API int ggm_pack_instances(const GgmInstance*,uint32_t,float*,uint32_t);
GGM_API void* ggm_audio_create(uint32_t rate);
GGM_API void ggm_audio_destroy(void*);
GGM_API int ggm_audio_clip(void*,uint32_t,const float*,uint32_t,uint32_t);
GGM_API int ggm_audio_clip_channels(void*,uint32_t,const float*,uint32_t,uint32_t,uint32_t);
GGM_API int ggm_audio_pitch(void*,uint32_t,float);
GGM_API int ggm_audio_voice_active(void*,uint32_t);
GGM_API int ggm_audio_voice_stop(void*,uint32_t,uint64_t);
GGM_API int ggm_audio_voice_position(void*,uint32_t,uint64_t,double,double,double);
GGM_API int ggm_audio_clip_active(void*,uint32_t);
GGM_API int ggm_audio_clip_release(void*,uint32_t);
GGM_API uint64_t ggm_audio_voice_token(void*,uint32_t);
GGM_API int ggm_audio_play(void*,uint32_t,uint32_t,double,double,double,float,float,float,uint32_t);
GGM_API int ggm_audio_listener(void*,double,double,double,double);
GGM_API int ggm_audio_gain(void*,float,float,float,float,uint32_t);
GGM_API int ggm_audio_render(void*,float*,uint32_t);
GGM_API int ggm_audio_stop(void*,int);
GGM_API uint32_t ggm_audio_voices(void*);
GGM_API int ggm_audio_reverb(void*,float,float,float,float);
GGM_API int ggm_audio_fade(void*,uint32_t,float,uint32_t,uint32_t);
GGM_API int ggm_audio_pause(void*,uint32_t,uint32_t);
GGM_API int ggm_audio_stream_create(void*,uint32_t,uint32_t,uint32_t);
GGM_API int ggm_audio_stream_write(void*,uint32_t,const float*,uint32_t,uint32_t);
GGM_API int ggm_audio_stream_free(void*,uint32_t);
GGM_API int ggm_audio_stream_play(void*,uint32_t,uint32_t,float);
GGM_API int ggm_audio_stream_active(void*,uint32_t);
GGM_API void* ggm_lua_create(uint32_t);
GGM_API void ggm_lua_destroy(void*);
GGM_API int ggm_lua_exec(void*,const char*,uint32_t,const char*);
GGM_API int ggm_lua_snapshot(void*,const GgmSnapshot*,const char*,const char*);
GGM_API int ggm_lua_event(void*,const char*,const char*);
GGM_API int ggm_lua_click(void*,const char*);
GGM_API int ggm_lua_frames(void*,char*,uint32_t);
GGM_API int ggm_lua_error(void*,char*,uint32_t);
GGM_API uint32_t ggm_lua_memory(void*);
#ifdef __cplusplus
}
#endif
