#pragma once
#import <Foundation/Foundation.h>

BOOL SHDWBackgroundAttributionInstall(NSString * _Nullable (^ _Nonnull profileForOwner)(NSString * _Nonnull owner));
NSString * _Nullable SHDWBackgroundConstructionProfile(void);
NSString * _Nullable SHDWBackgroundOwnerForParameters(id _Nullable parameters);
