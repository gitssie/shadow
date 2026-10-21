#import <Foundation/Foundation.h>
#include <ifaddrs.h>

BOOL SHDWFingerprintCopyInterfaces(NSString *bundleID, const struct ifaddrs *source,
                                  struct ifaddrs **result);
BOOL SHDWFingerprintReleaseInterfaces(struct ifaddrs *interfaces);
