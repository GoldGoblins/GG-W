#ifndef GG_GG_ENGINE_UI_H
#define GG_GG_ENGINE_UI_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* ABI 1. One owning thread per handle; destroy exactly once. Requests and
 * responses are UTF-8 JSON, at most 16 MiB. A successful transport returns 0;
 * inspect the response's "ok" property for a script/validation error. Response
 * storage belongs to the handle and is valid until its next request/destroy.
 * The Qt text measurer must remain alive until the handle is destroyed. Its
 * return value is the byte length written, or 0 if measurement fails. */
typedef size_t (*ggbu_measure_fn)(void *user, const void *request,
                                size_t request_bytes, void *output,
                                size_t output_capacity);
uint32_t ggbu_abi_version(void);
void *ggbu_create(void);
void ggbu_destroy(void *handle);
int32_t ggbu_text_measurer(void *handle, ggbu_measure_fn callback, void *user);
int32_t ggbu_request(void *handle, const void *request, size_t request_bytes);
const void *ggbu_response(void *handle, size_t *response_bytes);

#ifdef __cplusplus
}
#endif
#endif
