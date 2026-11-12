#import <Foundation/Foundation.h>
#include <xpc/xpc.h>
#import "../ShadowCore.dylib/policy/WebUserAgent.h"

xpc_object_t SHDWWebUserAgentBootstrapMessage(xpc_object_t original, NSString *version, NSString *owner);
NSDictionary *SHDWWebUserAgentSnapshot(xpc_object_t bootstrap, xpc_object_t event);
