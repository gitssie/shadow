#ifndef SHDW_LOCALIZATION_FUNCTION_HOOK_H
#define SHDW_LOCALIZATION_FUNCTION_HOOK_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

bool SHDWLocalizationHookFunction(const char *symbol, void *target,
                                  void *replacement, void **original);

#ifdef __cplusplus
}
#endif

#endif
