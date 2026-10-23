#ifndef GG_GG_ENGINE_CLIENT_H
#define GG_GG_ENGINE_CLIENT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
uint32_t ggc_abi_version(void);
void *ggc_create(void);
void ggc_destroy(void *client);
int ggc_request(void *client, const uint8_t *json, size_t length);
const uint8_t *ggc_response(void *client, size_t *length);
#ifdef __cplusplus
}
#endif
#endif
