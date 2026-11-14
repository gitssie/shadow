#pragma once
#import <Foundation/Foundation.h>

@class SHDWHookSession;

// Returns NO before installing hooks when the native TLS boundary is
// unsupported.
FOUNDATION_EXPORT BOOL SHDWNativeTLSInstall(NSString *profile,
                                            NSString *libraryPath,
                                            NSString *CAPath,
                                            SHDWHookSession *hooks);

// Installs through a retained hook session owned by the TLS adapter.
FOUNDATION_EXPORT BOOL SHDWNativeTLSPrepare(NSString *profile,
                                            NSString *libraryPath,
                                            NSString *CAPath);
