#import "Environment.h"
#import <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

BOOL SHDWLocalizationApplyEnvironment(NSDictionary *resolved) {
    int saved = errno;
    if(![resolved isKindOfClass:NSDictionary.class]) {
        errno = saved;
        return NO;
    }
    NSString *identifier = resolved[@"LocaleIdentifier"];
    NSArray *languages = resolved[@"Languages"];
    NSString *zoneName = resolved[@"TimeZone"];
    if(![identifier isKindOfClass:NSString.class] || !identifier.length ||
       ![zoneName isKindOfClass:NSString.class] || !zoneName.length ||
       ![languages isKindOfClass:NSArray.class] || !languages.count) {
        errno = saved;
        return NO;
    }
    for(id language in languages) {
        if(![language isKindOfClass:NSString.class] || ![language length]) {
            errno = saved;
            return NO;
        }
    }
    NSLocale *locale = [[NSLocale alloc] initWithLocaleIdentifier:identifier];
    NSTimeZone *zone = [NSTimeZone timeZoneWithName:zoneName];
    if(!locale || !zone || strlen(zoneName.UTF8String) !=
       [zoneName lengthOfBytesUsingEncoding:NSUTF8StringEncoding]) {
        errno = saved;
        return NO;
    }
    if(setenv("TZ", zoneName.UTF8String, 1) != 0) {
        errno = saved;
        return NO;
    }
    tzset();
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    NSMutableDictionary *arguments = [[defaults volatileDomainForName:NSArgumentDomain] mutableCopy];
    if(!arguments) arguments = [NSMutableDictionary dictionary];
    arguments[@"AppleLocale"] = identifier;
    arguments[@"AppleLanguages"] = [languages copy];
    [defaults setVolatileDomain:arguments forName:NSArgumentDomain];
    [NSTimeZone setDefaultTimeZone:zone];
    CFTimeZoneSetDefault((__bridge CFTimeZoneRef)zone);

    // ICU maintains defaults independently of Foundation and libc.
    typedef void (*SetLocale)(const char *, int32_t *);
    typedef void (*SetZone)(const uint16_t *, int32_t *);
    SetLocale setLocale = (SetLocale)dlsym(RTLD_DEFAULT, "uloc_setDefault");
    SetZone setZone = (SetZone)dlsym(RTLD_DEFAULT, "ucal_setDefaultTimeZone");
    if(setLocale) {
        int32_t status = 0;
        setLocale(identifier.UTF8String, &status);
    }
    if(setZone) {
        NSUInteger count = zoneName.length;
        uint16_t *characters = calloc(count + 1, sizeof(uint16_t));
        if(characters) {
            [zoneName getCharacters:characters range:NSMakeRange(0, count)];
            int32_t status = 0;
            setZone(characters, &status);
            free(characters);
        }
    }
    errno = saved;
    return YES;
}
