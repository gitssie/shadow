#import <Shadow/FingerprintMemory.h>
#import <Shadow/FingerprintConfiguration.h>
#import "FingerprintPolicy.h"
#import "FingerprintStorage.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/time.h>
#include <sys/utsname.h>
#include <sys/sysctl.h>
#include <math.h>

static NSDictionary *SHDWFingerprintCurrentConfiguration(void) {
    return SHDWFingerprintConfig(NSBundle.mainBundle.bundleIdentifier);
}
static NSDictionary *SHDWFingerprintSystemProfile(void) {
    return SHDWFingerprintSystem(NSBundle.mainBundle.bundleIdentifier);
}
BOOL SHDWFingerprintInterceptsReceipts(void) {
    return [SHDWFingerprintCurrentConfiguration()[@"Receipts"][@"InterceptEnabled"] boolValue];
}
NSOperatingSystemVersion SHDWFingerprintOSVersion(void) {
    NSDictionary *profile = SHDWFingerprintSystemProfile();
    NSArray *parts = [profile[@"Version"] componentsSeparatedByString:@"."];
    return (NSOperatingSystemVersion){parts.count > 0 ? [parts[0] integerValue] : 0, parts.count > 1 ? [parts[1] integerValue] : 0, parts.count > 2 ? [parts[2] integerValue] : 0};
}

BOOL SHDWFingerprintOSVersionAtLeast(NSOperatingSystemVersion requested) {
    NSOperatingSystemVersion current = SHDWFingerprintOSVersion();
    if(current.majorVersion != requested.majorVersion) return current.majorVersion > requested.majorVersion;
    if(current.minorVersion != requested.minorVersion) return current.minorVersion > requested.minorVersion;
    return current.patchVersion >= requested.patchVersion;
}

NSString *SHDWFingerprintOSVersionString(void) {
    return SHDWFingerprintSystemProfile()[@"Version"];
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
    if(!strcmp(name, "kern.hostname")) return "iPhone";
    NSDictionary *profile = SHDWFingerprintSystemProfile();
    if(!profile) return NULL;
    if(!strcmp(name, "kern.osversion")) return [profile[@"Build"] UTF8String];
    if(!strcmp(name, "kern.osrelease")) return [profile[@"Darwin"] UTF8String];
    if(!strcmp(name, "kern.version")) return [profile[@"Kernel"] UTF8String];
    if(!strcmp(name, "kern.osproductversion")) return [profile[@"Version"] UTF8String];
    return NULL;
}

BOOL SHDWFingerprintUnameValue(struct utsname *value) {
    if(!value) return NO;
    memcpy(value->nodename, "iPhone", sizeof("iPhone"));
    const char *release = SHDWFingerprintVersionValue("kern.osrelease");
    const char *version = SHDWFingerprintVersionValue("kern.version");
    if (!release || !version) return YES;
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
    return SHDWFingerprintCountryCenterForCode([NSLocale.currentLocale objectForKey:NSLocaleCountryCode]);
}

SHDWFingerprintCoordinate SHDWFingerprintCountryCenterForCode(NSString *country) {
    if ([country isEqualToString:@"FR"]) return (SHDWFingerprintCoordinate){46.227638, 2.213749};
    if ([country isEqualToString:@"GB"]) return (SHDWFingerprintCoordinate){55.378051, -3.435973};
    return (SHDWFingerprintCoordinate){37.09024, -95.712891};
}

uint64_t SHDWFingerprintMemorySize(NSString *bundleID, uint64_t nativeSize) {
    if (!bundleID.length) return nativeSize;
    return SHDWFingerprintProjectedMemory(nativeSize,
        [SHDWFingerprintData(bundleID)[@"MemoryDelta"] longLongValue]);
}

NSDictionary<NSString *, NSString *> *SHDWFingerprintRadioTechnologies(NSDictionary<NSString *, NSString *> *services) {
    (void)services;
    NSArray *radios = SHDWFingerprintCurrentConfiguration()[@"Network"][@"RadioTechnologies"];
    NSMutableDictionary *result = [NSMutableDictionary new];
    if ([radios containsObject:@"4g"]) result[@"0000000100000001"] = @"CTRadioAccessTechnologyLTE";
    if ([radios containsObject:@"5g"]) result[@"0000000100000002"] = @"CTRadioAccessTechnologyNRNSA";
    return [result copy];
}

void SHDWFingerprintSysctlValue(const char *name, void *value, size_t length) {
    if(name && !strcmp(name, "security.mac.amfi.developer_mode_status") && value && length == sizeof(int)) {
        int disabled = 0;
        memcpy(value, &disabled, sizeof(disabled));
    }
}

NSDictionary<NSString *, NSNumber *> *SHDWFingerprintSIMState(void) {
    return @{@"attached": @YES, @"hasIndicator": @YES, @"inHomeCountry": @YES,
             @"roamAllowed": @NO, @"cellularDataPossible": @YES, @"newRadioCoverage": @([SHDWFingerprintCurrentConfiguration()[@"Network"][@"RadioTechnologies"] containsObject:@"5g"])};
}
