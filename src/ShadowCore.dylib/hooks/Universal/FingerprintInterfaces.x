#import "UniversalHooks.h"
#import "../../policy/FingerprintInterfaces.h"

int (*original_getifaddrs)(struct ifaddrs **);
static void (*original_fingerprint_freeifaddrs)(struct ifaddrs *);
static BOOL shdw_fingerprint_interfaces_ready;
static const BOOL shdw_fingerprint_interface_mapping_enabled = NO;
static int (*shdw_fingerprint_native_getifaddrs)(struct ifaddrs **);
static void (*shdw_fingerprint_native_freeifaddrs)(struct ifaddrs *);

int replaced_getifaddrs(struct ifaddrs **interfaces) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    int status = (original_getifaddrs ?: shdw_fingerprint_native_getifaddrs)(interfaces);
    int saved = errno;
    if(status == 0 && interfaces && shdw_fingerprint_interfaces_ready &&
       shdw_fingerprint_interface_mapping_enabled) {
        @autoreleasepool {
            NSString *bundle = shdw_fingerprint_bundle_identifier_for_caller(caller);
            if(bundle.length) {
                SHADOW_INTERNAL_SCOPE {
                    struct ifaddrs *copy = NULL;
                    if(SHDWFingerprintCopyInterfaces(bundle, *interfaces, &copy)) {
                        if(*interfaces) (original_fingerprint_freeifaddrs ?: shdw_fingerprint_native_freeifaddrs)(*interfaces);
                        *interfaces = copy;
                    }
                }
            }
        }
    }
    errno = saved;
    return status;
}

static void shdw_fingerprint_freeifaddrs(struct ifaddrs *interfaces) {
    int saved = errno;
    if(!SHDWFingerprintReleaseInterfaces(interfaces))
        (original_fingerprint_freeifaddrs ?: shdw_fingerprint_native_freeifaddrs)(interfaces);
    errno = saved;
}

void *shdw_sym_policy_lookup_fingerprint(const char *name) {
    if(!shdw_fingerprint_interfaces_ready || !name) return NULL;
    if(!strcmp(name, "getifaddrs") && original_getifaddrs) return (void *)&replaced_getifaddrs;
    if(!strcmp(name, "freeifaddrs") && original_fingerprint_freeifaddrs) return (void *)&shdw_fingerprint_freeifaddrs;
    return NULL;
}

void shdw_universal_fingerprint_interfaces(SHDWHookSession *hooks) {
    original_getifaddrs = dlsym(RTLD_DEFAULT, "getifaddrs");
    original_fingerprint_freeifaddrs = dlsym(RTLD_DEFAULT, "freeifaddrs");
    if(!original_getifaddrs || !original_fingerprint_freeifaddrs) return;
    shdw_fingerprint_native_getifaddrs = original_getifaddrs;
    shdw_fingerprint_native_freeifaddrs = original_fingerprint_freeifaddrs;
    if(!shdw_fingerprint_interface_mapping_enabled) return;
    BOOL release = [hooks hookRebindSymbol:@"freeifaddrs" withReplacement:shdw_fingerprint_freeifaddrs
        outOldPtr:(void **)&original_fingerprint_freeifaddrs];
    if(!release) return;
    shdw_fingerprint_interfaces_ready = YES;
    [hooks hookRebindSymbol:@"getifaddrs" withReplacement:replaced_getifaddrs
        outOldPtr:(void **)&original_getifaddrs];
}
