#import "FingerprintPolicy.h"
#import "FingerprintStorage.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/time.h>
#include <sys/utsname.h>
#include <sys/sysctl.h>
#include <math.h>

static const NSOperatingSystemVersion shdw_os_version = {18, 7, 1};
static const char shdw_os_build[] = "22H31";
static const char shdw_kernel_release[] = "24.6.0";
static const char shdw_kernel_version[] =
    "Darwin Kernel Version 24.6.0: Tue Aug 12 00:02:59 PDT 2025; root:xnu-11417.140.69.700.6~5/RELEASE_ARM64_T8110";

NSOperatingSystemVersion SHDWFingerprintOSVersion(void) {
    return shdw_os_version;
}

BOOL SHDWFingerprintOSVersionAtLeast(NSOperatingSystemVersion requested) {
    NSOperatingSystemVersion current = SHDWFingerprintOSVersion();
    if(current.majorVersion != requested.majorVersion) return current.majorVersion > requested.majorVersion;
    if(current.minorVersion != requested.minorVersion) return current.minorVersion > requested.minorVersion;
    return current.patchVersion >= requested.patchVersion;
}

NSString *SHDWFingerprintOSVersionString(void) {
    return [NSString stringWithUTF8String:SHDWFingerprintVersionValue("kern.osproductversion")];
}

NSUUID *SHDWFingerprintVendorIdentifier(NSString *bundleID) {
    NSString *value = SHDWFingerprintData(bundleID)[@"VendorIdentifier"];
    return [value isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:value] : nil;
}

NSString *SHDWFingerprintUserAgent(NSString *userAgent) {
    if(!userAgent.length) return userAgent;
    static NSRegularExpression *pattern;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        pattern = [NSRegularExpression regularExpressionWithPattern:
            @"\\bCPU (?:iPhone )?OS ([0-9]+(?:[_.][0-9]+){0,2}) like Mac OS X\\b" options:0 error:NULL];
    });
    NSTextCheckingResult *match = [pattern firstMatchInString:userAgent options:0
        range:NSMakeRange(0, userAgent.length)];
    if(!match) return userAgent;
    NSRange versionRange = [match rangeAtIndex:1];
    NSString *version = [SHDWFingerprintOSVersionString() stringByReplacingOccurrencesOfString:@"." withString:@"_"];
    if([[userAgent substringWithRange:versionRange] isEqualToString:version]) return userAgent;
    return [userAgent stringByReplacingCharactersInRange:versionRange withString:version];
}

const char *SHDWFingerprintVersionValue(const char *name) {
    if(!name) return NULL;
    if(!strcmp(name, "kern.osversion")) return shdw_os_build;
    if(!strcmp(name, "kern.osrelease")) return shdw_kernel_release;
    if(!strcmp(name, "kern.version")) return shdw_kernel_version;
    if(!strcmp(name, "kern.osproductversion")) {
        static char version[32];
        static dispatch_once_t once;
        dispatch_once(&once, ^{
            snprintf(version, sizeof(version), "%ld.%ld.%ld", (long)shdw_os_version.majorVersion,
                (long)shdw_os_version.minorVersion, (long)shdw_os_version.patchVersion);
        });
        return version;
    }
    return NULL;
}

BOOL SHDWFingerprintUnameValue(struct utsname *value) {
    if(!value) return NO;
    const char *release = SHDWFingerprintVersionValue("kern.osrelease");
    const char *version = SHDWFingerprintVersionValue("kern.version");
    if(strlen(release) >= sizeof(value->release) || strlen(version) >= sizeof(value->version)) return NO;
    memcpy(value->release, release, strlen(release) + 1);
    memcpy(value->version, version, strlen(version) + 1);
    return YES;
}

BOOL SHDWFingerprintVersionQuery(const char *name, void *value, size_t *length, int *result) {
    const char *version = SHDWFingerprintVersionValue(name);
    if(!version || !result) return NO;
    if(!length) {
        if(value) {
            errno = ENOMEM;
            *result = -1;
        } else {
            *result = 0;
        }
        return YES;
    }
    size_t required = strlen(version) + 1;
    size_t capacity = *length;
    if(value && capacity < required) {
        *length = 0;
        errno = ENOMEM;
        *result = -1;
        return YES;
    }
    if(value) memcpy(value, version, required);
    *length = required;
    *result = 0;
    return YES;
}

BOOL SHDWFingerprintBootName(const char *name) {
    return name && (!strcmp(name, "kern.boottime") || !strcmp(name, "kern.bootsessionuuid"));
}

BOOL SHDWFingerprintBootQuery(const char *name, void *value, size_t *length, int *result) {
    if(!result || !SHDWFingerprintBootName(name)) return NO;
    NSDictionary *data = SHDWFingerprintData(NSBundle.mainBundle.bundleIdentifier);
    if(!data[@"NativeBootTimestamp"] || !data[@"BootTimeOffset"]) return NO;
    struct timeval boot = {0};
    const void *bytes;
    size_t required;
    if(!strcmp(name, "kern.boottime")) {
        int saved = errno;
        struct timeval nativeBoot = {0};
        size_t nativeLength = sizeof(nativeBoot);
        int nativeStatus = sysctlbyname("kern.boottime", &nativeBoot, &nativeLength, NULL, 0);
        errno = saved;
        if(nativeStatus != 0 || nativeLength != sizeof(nativeBoot)) return NO;
        double timestamp = (double)nativeBoot.tv_sec + nativeBoot.tv_usec / 1000000.0 + [data[@"BootTimeOffset"] doubleValue];
        boot.tv_sec = (time_t)floor(timestamp);
        boot.tv_usec = (suseconds_t)llround((timestamp - floor(timestamp)) * 1000000);
        if(boot.tv_usec == 1000000) { boot.tv_sec++; boot.tv_usec = 0; }
        bytes = &boot;
        required = sizeof(boot);
    } else {
        NSString *uuid = data[@"BootSessionUUID"];
        if(!uuid.length) return NO;
        bytes = uuid.UTF8String;
        required = strlen(bytes) + 1;
    }
    if(!length) {
        if(value) { errno = ENOMEM; *result = -1; }
        else *result = 0;
        return YES;
    }
    if(value && *length < required) {
        *length = 0; errno = ENOMEM; *result = -1;
        return YES;
    }
    if(value) memcpy(value, bytes, required);
    *length = required;
    *result = 0;
    return YES;
}

SHDWFingerprintCoordinate SHDWFingerprintCountryCenter(void) {
    return (SHDWFingerprintCoordinate){46.227638, 2.213749};
}

uint64_t SHDWFingerprintMemorySize(NSString *bundleID, uint64_t nativeSize) {
    const uint64_t maximumDelta = 64 * UINT64_C(16384);
    if(!bundleID.length || nativeSize <= maximumDelta || nativeSize > UINT64_MAX - maximumDelta)
        return nativeSize;
    int64_t delta = [SHDWFingerprintData(bundleID)[@"MemoryDelta"] longLongValue];
    if(delta < -(int64_t)maximumDelta || delta > (int64_t)maximumDelta) return nativeSize;
    return delta < 0 ? nativeSize - (uint64_t)(-delta) : nativeSize + (uint64_t)delta;
}

NSDictionary<NSString *, NSString *> *SHDWFingerprintRadioTechnologies(NSDictionary<NSString *, NSString *> *services) {
    (void)services;
    return @{@"0000000100000001": @"CTRadioAccessTechnologyLTE",
             @"0000000100000002": @"CTRadioAccessTechnologyNRNSA"};
}

void SHDWFingerprintSysctlValue(const char *name, void *value, size_t length) {
    if(name && !strcmp(name, "security.mac.amfi.developer_mode_status") && value && length == sizeof(int)) {
        int disabled = 0;
        memcpy(value, &disabled, sizeof(disabled));
    }
}

NSDictionary<NSString *, NSNumber *> *SHDWFingerprintSIMState(void) {
    return @{@"attached": @YES, @"hasIndicator": @YES, @"inHomeCountry": @YES,
             @"roamAllowed": @NO, @"cellularDataPossible": @YES, @"newRadioCoverage": @YES};
}
