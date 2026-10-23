#ifndef GG_GG_ENGINE_ASSETS_H
#define GG_GG_ENGINE_ASSETS_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* UTF-8 root restricts every file request, including resolved symlinks.
 * One owning thread per handle. JSON response and optional blob are borrowed
 * until next request/destroy. Inspect JSON "ok" even when transport returns 0. */
uint32_t gga_abi_version(void);
void *gga_create(const char *root);
void gga_destroy(void *handle);
int32_t gga_request(void *handle, const void *json, size_t bytes);
const void *gga_response(void *handle, size_t *bytes);
const void *gga_blob(void *handle, size_t *bytes);
#ifdef __cplusplus
}
#endif
#endif
