#import "UniversalHooks.h"
#import <MapKit/MapKit.h>
#import <CoreTelephony/CTTelephonyNetworkInfo.h>
#import "../../policy/NetworkQueryPolicy.h"
#import "../../policy/FingerprintPolicy.h"
#import "../../policy/FingerprintStorage.h"
#include <limits.h>
#include <stdlib.h>
#include <execinfo.h>
#include <sys/sysctl.h>

static char shdw_map_bundle[PATH_MAX], shdw_map_canonical_bundle[PATH_MAX];
static char shdw_map_candidate_key;
static BOOL shdw_fingerprint_enabled;
static NSString *shdw_fingerprint_bundle_id;
static unsigned shdw_map_install_state;
static unsigned shdw_radio_install_state;
static unsigned shdw_sim_install_state;
static unsigned shdw_pasteboard_install_state;
static unsigned shdw_memory_install_state;
static unsigned shdw_version_install_state;

static BOOL shdw_map_app_caller(const void *caller) {
    if(!shdw_caller_is_external(caller)) return NO;
    Dl_info image = {0};
    BOOL applies = NO;
    SHADOW_INTERNAL_SCOPE {
        if(dladdr(caller, &image) && image.dli_fname)
            applies = SHDWNetworkQueryPathMatches(image.dli_fname, shdw_map_bundle) ||
                SHDWNetworkQueryPathMatches(image.dli_fname, shdw_map_canonical_bundle);
    }
    return applies;
}

BOOL shdw_fingerprint_is_enabled(void) { return shdw_fingerprint_enabled; }

BOOL shdw_fingerprint_app_caller(const void *caller) {
    return shdw_fingerprint_enabled && shdw_map_app_caller(caller);
}

NSString *shdw_fingerprint_bundle_identifier_for_caller(const void *caller) {
    return shdw_fingerprint_enabled && shdw_map_app_caller(caller) ? shdw_fingerprint_bundle_id : nil;
}

BOOL shdw_fingerprint_sysctl_query(const char *name, void *value, size_t *length,
    void *newp, size_t newlen, const void *caller, int *result) {
    if(newp || newlen || !shdw_fingerprint_enabled) return NO;
    int saved = errno;
    if(!SHDWFingerprintVersionValue(name) && !SHDWFingerprintBootName(name)) {
        errno = saved;
        return NO;
    }
    BOOL applies = shdw_map_app_caller(caller);
    errno = saved;
    if(!applies) return NO;
    if(SHDWFingerprintBootName(name)) {
        SHADOW_INTERNAL_SCOPE { return SHDWFingerprintBootQuery(name, value, length, result); }
    }
    return SHDWFingerprintVersionQuery(name, value, length, result);
}

void shdw_fingerprint_uname_value(struct utsname *value, const void *caller) {
    int saved = errno;
    if(shdw_fingerprint_enabled && value && shdw_map_app_caller(caller))
        SHDWFingerprintUnameValue(value);
    errno = saved;
}

BOOL shdw_fingerprint_sysctl_mib_query(const int *mib, u_int count, void *value, size_t *length,
    void *newp, size_t newlen, const void *caller, int *result) {
    if(!mib || count != 2 || mib[0] != CTL_KERN || newp || newlen ||
       !shdw_fingerprint_enabled) return NO;
    int saved = errno;
    BOOL applies = shdw_map_app_caller(caller);
    errno = saved;
    if(!applies) return NO;
    static const char *names[] = {"kern.osproductversion", "kern.osversion", "kern.boottime", "kern.bootsessionuuid",
                                "kern.osrelease", "kern.version", "kern.hostname"};
    static int selectors[7][CTL_MAXNAME];
    static size_t counts[7];
    static dispatch_once_t once;
    SHADOW_INTERNAL_SCOPE {
        dispatch_once(&once, ^{
            for(unsigned i = 0; i < 7; i++) {
                counts[i] = CTL_MAXNAME;
                if(sysctlnametomib(names[i], selectors[i], &counts[i]) != 0) counts[i] = 0;
            }
        });
    }
    errno = saved;
    for(unsigned i = 0; i < 7; i++) {
        if(counts[i] == count && !memcmp(mib, selectors[i], count * sizeof(*mib)))
            return shdw_fingerprint_sysctl_query(names[i], value, length, NULL, 0, caller, result);
    }
    return NO;
}

static BOOL shdw_fingerprint_resource_caller(const void *caller) {
    if(!shdw_caller_is_external(caller)) return NO;
    if(shdw_map_app_caller(caller)) return YES;
    Dl_info image = {0};
    SHADOW_INTERNAL_SCOPE {
        if(!dladdr(caller, &image) || !image.dli_fname ||
           (!strstr(image.dli_fname, "/Foundation.framework/") &&
            !strstr(image.dli_fname, "/libswiftFoundation.dylib"))) return NO;
    }
    void *frames[24];
    int count = backtrace(frames, 24);
    for(int i = 1; i < count; i++) if(shdw_map_app_caller(frames[i])) return YES;
    return NO;
}

void shdw_fingerprint_sysctl_value(const char *name, void *value, size_t length, const void *caller) {
    if(shdw_fingerprint_enabled && name && !strcmp(name, "hw.memsize") &&
       value && length == sizeof(uint64_t) && shdw_map_app_caller(caller)) {
        SHADOW_INTERNAL_SCOPE {
            uint64_t nativeSize;
            memcpy(&nativeSize, value, sizeof(nativeSize));
            uint64_t adjusted = SHDWFingerprintMemorySize(shdw_fingerprint_bundle_id, nativeSize);
            memcpy(value, &adjusted, sizeof(adjusted));
        }
        return;
    }
    if(shdw_fingerprint_enabled && name && !strcmp(name, "security.mac.amfi.developer_mode_status") &&
       shdw_fingerprint_resource_caller(caller)) SHDWFingerprintSysctlValue(name, value, length);
}



static void shdw_map_explicit(MKMapView *map, const void *caller) {
    if(objc_getAssociatedObject(map, &shdw_map_candidate_key) && shdw_map_app_caller(caller))
        objc_setAssociatedObject(map, &shdw_map_candidate_key, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}

%group shadowhook_map_defaults
%hook MKMapView
- (instancetype)initWithFrame:(CGRect)frame {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL candidate = frame.size.width < 0 && frame.size.height < 0 && shdw_map_app_caller(caller);
    MKMapView *map = %orig(frame);
    if(map && candidate)
        objc_setAssociatedObject(map, &shdw_map_candidate_key, @YES, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    return map;
}
- (CLLocationCoordinate2D)centerCoordinate {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(objc_getAssociatedObject(self, &shdw_map_candidate_key) &&
       !self.superview && !self.window && shdw_map_app_caller(caller)) {
        SHDWFingerprintCoordinate value = SHDWFingerprintCountryCenter();
        CLLocationCoordinate2D center = {value.latitude, value.longitude};
        return center;
    }
    return %orig;
}
- (void)setCenterCoordinate:(CLLocationCoordinate2D)center {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(center);
}
- (void)setCenterCoordinate:(CLLocationCoordinate2D)center animated:(BOOL)animated {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(center, animated);
}
- (void)setRegion:(MKCoordinateRegion)region {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(region);
}
- (void)setRegion:(MKCoordinateRegion)region animated:(BOOL)animated {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(region, animated);
}
- (void)setCamera:(MKMapCamera *)camera {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(camera);
}
- (void)setCamera:(MKMapCamera *)camera animated:(BOOL)animated {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(camera, animated);
}
- (void)setVisibleMapRect:(MKMapRect)rect {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(rect);
}
- (void)setVisibleMapRect:(MKMapRect)rect animated:(BOOL)animated {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(rect, animated);
}
- (void)setVisibleMapRect:(MKMapRect)rect edgePadding:(UIEdgeInsets)padding animated:(BOOL)animated {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(rect, padding, animated);
}
- (void)setUserTrackingMode:(MKUserTrackingMode)mode {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(mode);
}
- (void)setUserTrackingMode:(MKUserTrackingMode)mode animated:(BOOL)animated {
    shdw_map_explicit(self, __builtin_extract_return_addr(__builtin_return_address(0)));
    %orig(mode, animated);
}
%end
%end

%group shadowhook_fingerprint_radio
%hook CTTelephonyNetworkInfo
- (NSDictionary<NSString *, NSString *> *)serviceCurrentRadioAccessTechnology {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller))
        return SHDWFingerprintRadioTechnologies(nil);
    return %orig;
}
%end
%end

%group shadowhook_fingerprint_version
%hook UIDevice
- (NSString *)name {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller)) return @"iPhone";
    return %orig;
}
- (NSUUID *)identifierForVendor {
    if(shdw_fingerprint_enabled) {
        SHADOW_INTERNAL_SCOPE {
            NSUUID *identifier = SHDWFingerprintVendorIdentifier(shdw_fingerprint_bundle_id);
            if(identifier) return identifier;
        }
    }
    return %orig;
}
- (NSString *)systemVersion {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller))
        return SHDWFingerprintOSVersionString();
    return %orig;
}
%end
%hook NSProcessInfo
- (NSString *)hostName {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller)) return @"iPhone";
    return %orig;
}
- (NSOperatingSystemVersion)operatingSystemVersion {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller))
        return SHDWFingerprintOSVersion();
    return %orig;
}
- (BOOL)isOperatingSystemAtLeastVersion:(NSOperatingSystemVersion)version {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller))
        return SHDWFingerprintOSVersionAtLeast(version);
    return %orig;
}
- (NSString *)operatingSystemVersionString {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller)) {
        const char *build = SHDWFingerprintVersionValue("kern.osversion");
        if(build) return [NSString stringWithFormat:@"Version %@ (Build %s)", SHDWFingerprintOSVersionString(), build];
    }
    return %orig;
}
%end
%end

%group shadowhook_fingerprint_memory
%hook NSProcessInfo
- (unsigned long long)physicalMemory {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    BOOL applies = shdw_fingerprint_enabled && shdw_map_app_caller(caller);
    unsigned long long nativeSize;
    SHADOW_INTERNAL_SCOPE {
        nativeSize = %orig;
    }
    if(!applies) return nativeSize;
    SHADOW_INTERNAL_SCOPE { return SHDWFingerprintMemorySize(shdw_fingerprint_bundle_id, nativeSize); }
    return nativeSize;
}
%end
%end

%group shadowhook_fingerprint_pasteboard
%hook UIPasteboard
- (NSInteger)changeCount {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(shdw_fingerprint_enabled && shdw_map_app_caller(caller)) {
        BOOL general;
        SHADOW_INTERNAL_SCOPE { general = [[(UIPasteboard *)self name] isEqualToString:UIPasteboardNameGeneral]; }
        if(general) return 0;
    }
    return %orig;
}
%end
%end

%group shadowhook_fingerprint_sim
%hook CoreTelephonyClient
- (id)getDataStatusBasic:(id)context error:(NSError **)error {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    id status = %orig(context, error);
    if(!shdw_fingerprint_enabled || !shdw_fingerprint_resource_caller(caller)) return status;
    @try {
        Class cls = objc_getClass("CTDataStatusBasic");
        if(!cls || (status && ![status isKindOfClass:cls])) return status;
        id adjusted = status ? [status copy] : [[cls alloc] init];
        if(adjusted == status) adjusted = [[cls alloc] init];
        if(!adjusted || adjusted == status) return status;
        [adjusted setValuesForKeysWithDictionary:SHDWFingerprintSIMState()];
        if(error) *error = nil;
        return adjusted;
    } @catch(NSException *exception) {
        (void)exception;
        return status;
    }
}
%end
%end

void shdw_universal_fingerprint_prepare(SHDWHookSession *hooks) {
    if(!shdw_fingerprint_enabled || !hooks) return;
    shdw_universal_fingerprint_receipts_prepare(hooks);
    shdw_universal_fingerprint_webkit_prepare(hooks);
    shdw_universal_fingerprint_system_version_prepare(hooks);
    SHDWHookSession *previous = SHDWHookSessionSetCurrent(hooks);
    @try {
        unsigned expected = 0;
        if(__atomic_compare_exchange_n(&shdw_version_install_state, &expected, 1, NO,
           __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            Class processInfoClass = object_getClass(NSProcessInfo.processInfo);
            %init(shadowhook_fingerprint_version, NSProcessInfo = processInfoClass);
            __atomic_store_n(&shdw_version_install_state, 2, __ATOMIC_RELEASE);
        }
        expected = 0;
        if(__atomic_compare_exchange_n(&shdw_memory_install_state, &expected, 1, NO,
           __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            Class processInfoClass = object_getClass(NSProcessInfo.processInfo);
            %init(shadowhook_fingerprint_memory, NSProcessInfo = processInfoClass);
            __atomic_store_n(&shdw_memory_install_state, 2, __ATOMIC_RELEASE);
        }
        expected = 0;
        Class pasteboardClass = objc_getClass("_UIConcretePasteboard");
        if(!pasteboardClass) pasteboardClass = objc_getClass("UIConcretePasteboard");
        if(pasteboardClass && class_getInstanceMethod(pasteboardClass, @selector(changeCount)) &&
           __atomic_compare_exchange_n(&shdw_pasteboard_install_state,
           &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_fingerprint_pasteboard, UIPasteboard = pasteboardClass);
            __atomic_store_n(&shdw_pasteboard_install_state, 2, __ATOMIC_RELEASE);
        }
        expected = 0;
        if(objc_getClass("MKMapView") && __atomic_compare_exchange_n(&shdw_map_install_state,
           &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_map_defaults);
            __atomic_store_n(&shdw_map_install_state, 2, __ATOMIC_RELEASE);
        }
        expected = 0;
        if(objc_getClass("CTTelephonyNetworkInfo") && __atomic_compare_exchange_n(&shdw_radio_install_state,
           &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_fingerprint_radio);
            __atomic_store_n(&shdw_radio_install_state, 2, __ATOMIC_RELEASE);
        }
        if(__atomic_load_n(&shdw_sim_install_state, __ATOMIC_ACQUIRE) == 0) {
            expected = 0;
            Class client = objc_getClass("CoreTelephonyClient");
            Class status = objc_getClass("CTDataStatusBasic");
            Method method = client ? class_getInstanceMethod(client, @selector(getDataStatusBasic:error:)) : NULL;
            char resultType[8] = {0}, contextType[8] = {0}, errorType[8] = {0};
            if(method) {
                method_getReturnType(method, resultType, sizeof(resultType));
                method_getArgumentType(method, 2, contextType, sizeof(contextType));
                method_getArgumentType(method, 3, errorType, sizeof(errorType));
            }
            BOOL supported = status && method && method_getNumberOfArguments(method) == 4 &&
                resultType[0] == '@' && contextType[0] == '@' && errorType[0] == '^';
            for(NSString *key in SHDWFingerprintSIMState()) {
                NSString *setter = [NSString stringWithFormat:@"set%@%@:", [[key substringToIndex:1] uppercaseString],
                    [key substringFromIndex:1]];
                if(!class_getInstanceMethod(status, NSSelectorFromString(setter))) supported = NO;
            }
            if(supported && __atomic_compare_exchange_n(&shdw_sim_install_state,
               &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
                %init(shadowhook_fingerprint_sim);
                __atomic_store_n(&shdw_sim_install_state, 2, __ATOMIC_RELEASE);
            }
        }
    } @finally {
        SHDWHookSessionSetCurrent(previous);
    }
}

void shdw_universal_fingerprint(SHDWHookSession *hooks) {
    const char *path = NSBundle.mainBundle.bundlePath.fileSystemRepresentation;
    if(path) {
        snprintf(shdw_map_bundle, sizeof(shdw_map_bundle), "%s", path);
        realpath(path, shdw_map_canonical_bundle);
    }
    shdw_fingerprint_bundle_id = [NSBundle.mainBundle.bundleIdentifier copy];
    NSDictionary *data;
    SHADOW_INTERNAL_SCOPE {
        data = SHDWFingerprintData(shdw_fingerprint_bundle_id);
        if (data.count) SHDWFingerprintSystem(shdw_fingerprint_bundle_id);
    }
    shdw_universal_fingerprint_receipts(hooks);
    shdw_fingerprint_enabled = data.count > 0;
    if(!shdw_fingerprint_enabled) return;
    shdw_universal_fingerprint_interfaces(hooks);
    shdw_universal_url_resources(hooks);
    shdw_universal_file_attributes(hooks);
    shdw_universal_fingerprint_prepare(hooks);
}
