#pragma once
#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN

@class SHDWHookSession;
typedef NSString * _Nullable (^SHDWNativeTLSProfileResolver)(id parameters);
FOUNDATION_EXPORT BOOL SHDWNativeTLSSetProfileResolver(SHDWNativeTLSProfileResolver _Nullable resolver);

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
NS_ASSUME_NONNULL_END
