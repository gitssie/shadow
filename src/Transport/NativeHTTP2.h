#pragma once
#import <Foundation/Foundation.h>
#include "NativeHTTP2Policy.h"
typedef BOOL (*SHDWNativeHTTP2ConfigurationResolver)(void *sessionUser,
    SHDWH2Configuration *outConfiguration);
// Set before Prepare. A resolver refusal leaves that connection native.
BOOL SHDWNativeHTTP2SetConfigurationResolver(SHDWNativeHTTP2ConfigurationResolver resolver);
BOOL SHDWNativeHTTP2Prepare(const SHDWH2Configuration *configuration);
void SHDWNativeHTTP2Activate(void);
