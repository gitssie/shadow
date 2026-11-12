#ifndef SHDW_LOCALIZATION_FUNCTION_HOOK_H
#define SHDW_LOCALIZATION_FUNCTION_HOOK_H

#include <stdbool.h>

bool SHDWLocalizationHookFunction(const char *symbol, void *target,
                                  void *replacement, void **original);

#endif
