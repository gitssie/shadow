#import "Sessions.h"
#import "../Transport/Profiles.h"
#import "../ShadowCore.dylib/policy/CurlTransport.h"

static NSDictionary *processSnapshot;
static BOOL installSucceeded;

BOOL SHDWNetworkingInstall(NSDictionary *snapshot) {
    if (!SHDWTransportProfileIsSupported(snapshot[@"Profile"]) || ![snapshot[@"Owner"] length]) return NO;
    @synchronized(NSURLSession.class) {
        if (processSnapshot) return installSucceeded && [processSnapshot isEqual:snapshot];
        SHDWCurlTransportPrepareProfile(snapshot[@"Profile"]);
        if (!SHDWCurlTransportReady()) return NO;
        processSnapshot = [snapshot copy];
        installSucceeded = YES;
        return YES;
    }
}

void SHDWRebindJournalNote(const char *name, void *replacement, void **original) {
    (void)name; (void)replacement; (void)original;
}
