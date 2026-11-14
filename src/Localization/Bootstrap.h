#import <Foundation/Foundation.h>
#include <xpc/xpc.h>

BOOL SHDWLocalizationIsWebContentService(const char *service);
BOOL SHDWLocalizationBootstrapHasPayload(xpc_object_t bootstrap);

// Returns the original message when there is no valid explicit override.
xpc_object_t SHDWLocalizationBootstrapMessage(xpc_object_t original,
                                             NSDictionary *resolved,
                                             NSString *owner);

// Returns only immutable resolved values after validating the launch identity.
NSDictionary *SHDWLocalizationSnapshot(xpc_object_t bootstrap, xpc_object_t event);

NSDictionary *SHDWLocalizationNetworkingSnapshot(xpc_object_t bootstrap, xpc_object_t event);
