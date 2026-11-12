#import <Foundation/Foundation.h>
#import "Profiles.h"
#include <xpc/xpc.h>

BOOL SHDWTransportIsNetworkingService(const char *service);

// Returns the original message unless an explicit supported profile is valid.
xpc_object_t SHDWTransportBootstrapMessage(xpc_object_t original, NSString *profile, NSString *owner);

// Returns immutable values only after validating the bootstrap launch identity.
NSDictionary *SHDWTransportSnapshot(xpc_object_t bootstrap, xpc_object_t event);
